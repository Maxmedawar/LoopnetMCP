"""Human location to government geography resolution."""

import logging
import re
from typing import Any

from cre_mcp.access.context import current_runtime_config, resolve_runtime_config
from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.geo.constants import CITY_FALLBACKS, COUNTY_FIPS, STATE_FIPS
from cre_mcp.geo.crosswalk import GeoCrosswalk, STATIC_CROSSWALK
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import AuthSpec, GovApiClient
from cre_mcp.models.geo import GeoLevel, GeoRef
from cre_mcp.source_rights.gate import SourceRightsDeniedError, require_url
from cre_mcp.source_rights.output import safe_error_message, safe_source_reference

logger = logging.getLogger(__name__)

_CENSUS_GEOCODER_URL = (
    "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
)
_HUD_CROSSWALK_URL = "https://www.huduser.gov/hudapi/public/usps"
class GeoResolutionError(ValueError):
    """Raised when a human location cannot be mapped to a supported geography."""


class GeoResolver:
    """Resolve ZIP, state, county, city, and address inputs to GeoRef."""

    def __init__(
        self,
        config: CreConfig | None = None,
        *,
        fetch: FetchClient | None = None,
        crosswalk: GeoCrosswalk | None = None,
        cache: SQLiteCache | None = None,
    ):
        self.config = resolve_runtime_config(config)
        self.fetch = fetch or get_fetch_client()
        self.cache = cache or SQLiteCache(self.config.cache_db_path)
        self.crosswalk = crosswalk or GeoCrosswalk(self.config, fetch=self.fetch)
        self.client = GovApiClient(
            self.fetch,
            AuthSpec(kind="none"),
            "https://geocoding.geo.census.gov/geocoder/geographies",
        )

    async def _from_cache(self, location: str) -> GeoRef | None:
        payload = await self.cache.get(f"geo:v1:{location.casefold().strip()}")
        return GeoRef.model_validate(payload) if payload is not None else None

    async def _store(
        self,
        location: str,
        geo: GeoRef,
        *,
        ttl_seconds: int = 0,
    ) -> GeoRef:
        if ttl_seconds <= 0:
            return geo
        await self.cache.set(
            f"geo:v1:{location.casefold().strip()}",
            geo.model_dump(mode="json"),
            ttl_seconds=ttl_seconds,
        )
        return geo

    @staticmethod
    def _first(items: Any) -> dict[str, Any]:
        return items[0] if isinstance(items, list) and items else {}

    def _parse_geocoder(self, payload: Any, location: str) -> GeoRef | None:
        if not isinstance(payload, dict):
            return None
        result = payload.get("result", {})
        match = self._first(result.get("addressMatches", []))
        geographies = match.get("geographies", {}) if isinstance(match, dict) else {}
        state = self._first(geographies.get("States", []))
        county = self._first(geographies.get("Counties", []))
        place = self._first(geographies.get("Incorporated Places", []))
        tract = self._first(geographies.get("Census Tracts", []))
        state_fips = str(state.get("STATE") or state.get("GEOID") or "")
        county_fips = county.get("GEOID")
        if not state_fips:
            return None
        components = match.get("addressComponents", {})
        return GeoRef(
            level=GeoLevel.CITY if place else GeoLevel.TRACT if tract else GeoLevel.COUNTY,
            state_fips=state_fips.zfill(2),
            county_fips=str(county_fips).zfill(5) if county_fips else None,
            zip=str(components.get("zip")) if components.get("zip") else None,
            tract=str(tract.get("GEOID")) if tract.get("GEOID") else None,
            name=str(place.get("NAME") or match.get("matchedAddress") or location),
        )

    async def _geocode(self, location: str) -> GeoRef | None:
        payload = await self.client.get(
            "onelineaddress",
            {
                "address": location,
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
                "format": "json",
            },
        )
        return self._parse_geocoder(payload, location)

    async def resolve(self, location: str) -> GeoRef:
        """Resolve a human location without requiring API credentials."""
        normalized = location.strip()
        if not normalized:
            raise GeoResolutionError("Location cannot be empty")

        if re.fullmatch(r"\d{5}", normalized):
            fallback = STATIC_CROSSWALK.get(normalized)
            if fallback is not None and self.config.hud_api_token is None:
                county, cbsa = fallback
                return GeoRef(
                    level=GeoLevel.ZIP,
                    state_fips=county[:2],
                    county_fips=county,
                    cbsa=cbsa,
                    zip=normalized,
                    name=normalized,
                )
            record = require_url(
                _HUD_CROSSWALK_URL,
                method="GET",
                config=self.config,
            )
            cache_ttl = (
                record.operating_policy.persistent_cache_ttl_seconds
                if record is not None
                else 0
            )
            if cache_ttl > 0:
                cached = await self._from_cache(normalized)
                if cached is not None:
                    return cached
            county = await self.crosswalk.zip_to_county(normalized)
            cbsa = await self.crosswalk.zip_to_cbsa(normalized)
            if county is None:
                raise GeoResolutionError(f"No county crosswalk found for ZIP {normalized}")
            return await self._store(
                normalized,
                GeoRef(
                    level=GeoLevel.ZIP,
                    state_fips=county[:2],
                    county_fips=county,
                    cbsa=cbsa,
                    zip=normalized,
                    name=normalized,
                ),
                ttl_seconds=cache_ttl,
            )

        upper = normalized.upper()
        if upper in STATE_FIPS:
            return GeoRef(
                level=GeoLevel.STATE,
                state_fips=STATE_FIPS[upper],
                name=upper,
            )

        segments = [part.strip() for part in normalized.split(",") if part.strip()]
        if len(segments) >= 2 and segments[-1].upper() in STATE_FIPS:
            state = segments[-1].upper()
            # The locality used for county/city fallback is the segment just
            # before the state (the city). This lets a full street address like
            # "8600 Cross Park Dr, Austin, TX" degrade to its city ("Austin")
            # instead of failing, while "Austin, TX" still resolves as before.
            local_name = segments[-2]
            county_name = re.sub(r"\s+county$", "", local_name, flags=re.I).casefold()
            county_fips = COUNTY_FIPS.get((county_name, state))
            if county_fips and local_name.casefold().endswith("county"):
                return GeoRef(
                    level=GeoLevel.COUNTY,
                    state_fips=STATE_FIPS[state],
                    county_fips=county_fips,
                    name=f"{local_name}, {state}",
                )
            fallback = CITY_FALLBACKS.get((local_name.casefold(), state))
            try:
                record = require_url(
                    _CENSUS_GEOCODER_URL,
                    method="GET",
                    config=self.config,
                )
            except SourceRightsDeniedError:
                if fallback is None:
                    raise
                county, cbsa, name = fallback
                return GeoRef(
                    level=GeoLevel.CITY,
                    state_fips=STATE_FIPS[state],
                    county_fips=county,
                    cbsa=cbsa,
                    name=name,
                )
            cache_ttl = (
                record.operating_policy.persistent_cache_ttl_seconds
                if record is not None
                else 0
            )
            if cache_ttl > 0:
                cached = await self._from_cache(normalized)
                if cached is not None:
                    return cached
            try:
                geocoded = await self._geocode(normalized)
            except Exception as exc:
                logger.warning(
                    "Census geocoding failed for %s: %s",
                    safe_source_reference(normalized),
                    safe_error_message(exc),
                )
                geocoded = None
            if geocoded is not None:
                return await self._store(
                    normalized,
                    geocoded,
                    ttl_seconds=cache_ttl,
                )
            if fallback:
                county, cbsa, name = fallback
                return GeoRef(
                    level=GeoLevel.CITY,
                    state_fips=STATE_FIPS[state],
                    county_fips=county,
                    cbsa=cbsa,
                    name=name,
                )

        raise GeoResolutionError(f"Could not resolve location: {location}")


_resolver: GeoResolver | None = None


async def resolve(location: str) -> GeoRef:
    """Resolve with the module-level shared resolver."""
    global _resolver
    runtime = current_runtime_config()
    if runtime is not None:
        return await GeoResolver(runtime).resolve(location)
    if _resolver is None:
        _resolver = GeoResolver()
    return project_for_release(await _resolver.resolve(location))


def project_for_release(geo: GeoRef) -> GeoRef:
    """Drop an unproved sub-city carrier only for restricted execution.

    Census geocoder responses include an address tract even when the requested
    and returned geography is city-level.  The checked-in authority proves
    tract existence, county, and ZIP intersections but does not prove one
    common tract-to-place relationship.  Restricted profiles therefore expose
    the city projection and omit that unrelated carrier.  Full operators retain
    the original resolver object unchanged.
    """

    from cre_mcp.access.context import current_context
    from cre_mcp.access.profiles import TERRITORY_LIMITED

    context = current_context()
    if (
        context is not None
        and not context.trusted
        and context.profile in TERRITORY_LIMITED
        and geo.level == GeoLevel.CITY
        and geo.tract is not None
    ):
        return geo.model_copy(update={"tract": None})
    return geo
