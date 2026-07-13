"""Human location to government geography resolution."""

import logging
import re
from typing import Any

from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.geo.crosswalk import GeoCrosswalk
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import AuthSpec, GovApiClient
from cre_mcp.models.geo import GeoLevel, GeoRef

logger = logging.getLogger(__name__)

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
    "CO": "08", "CT": "09", "DE": "10", "DC": "11", "FL": "12",
    "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18",
    "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23",
    "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
    "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
    "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55",
    "WY": "56", "PR": "72",
}

COUNTY_FIPS = {
    ("travis", "TX"): "48453",
    ("dallas", "TX"): "48113",
    ("harris", "TX"): "48201",
    ("bexar", "TX"): "48029",
    ("tarrant", "TX"): "48439",
    ("los angeles", "CA"): "06037",
    ("san francisco", "CA"): "06075",
    ("new york", "NY"): "36061",
    ("miami-dade", "FL"): "12086",
    ("cook", "IL"): "17031",
}

CITY_FALLBACKS = {
    ("austin", "TX"): ("48453", "12420", "Austin, TX"),
    ("dallas", "TX"): ("48113", "19100", "Dallas, TX"),
    ("houston", "TX"): ("48201", "26420", "Houston, TX"),
    ("san francisco", "CA"): ("06075", "41860", "San Francisco, CA"),
    ("new york", "NY"): ("36061", "35620", "New York, NY"),
}


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
        self.config = config or CreConfig()
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

    async def _store(self, location: str, geo: GeoRef) -> GeoRef:
        await self.cache.set(
            f"geo:v1:{location.casefold().strip()}",
            geo.model_dump(mode="json"),
            ttl_seconds=90 * 24 * 60 * 60,
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
        cached = await self._from_cache(normalized)
        if cached is not None:
            return cached

        if re.fullmatch(r"\d{5}", normalized):
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
            )

        upper = normalized.upper()
        if upper in STATE_FIPS:
            return await self._store(
                normalized,
                GeoRef(
                    level=GeoLevel.STATE,
                    state_fips=STATE_FIPS[upper],
                    name=upper,
                ),
            )

        parts = [part.strip() for part in normalized.rsplit(",", 1)]
        if len(parts) == 2 and parts[1].upper() in STATE_FIPS:
            local_name, state = parts[0], parts[1].upper()
            county_name = re.sub(r"\s+county$", "", local_name, flags=re.I).casefold()
            county_fips = COUNTY_FIPS.get((county_name, state))
            if county_fips and local_name.casefold().endswith("county"):
                return await self._store(
                    normalized,
                    GeoRef(
                        level=GeoLevel.COUNTY,
                        state_fips=STATE_FIPS[state],
                        county_fips=county_fips,
                        name=f"{local_name}, {state}",
                    ),
                )
            try:
                geocoded = await self._geocode(normalized)
            except Exception as exc:
                logger.warning("Census geocoding failed for %s: %s", normalized, exc)
                geocoded = None
            if geocoded is not None:
                return await self._store(normalized, geocoded)
            fallback = CITY_FALLBACKS.get((local_name.casefold(), state))
            if fallback:
                county, cbsa, name = fallback
                return await self._store(
                    normalized,
                    GeoRef(
                        level=GeoLevel.CITY,
                        state_fips=STATE_FIPS[state],
                        county_fips=county,
                        cbsa=cbsa,
                        name=name,
                    ),
                )

        raise GeoResolutionError(f"Could not resolve location: {location}")


_resolver: GeoResolver | None = None


async def resolve(location: str) -> GeoRef:
    """Resolve with the module-level shared resolver."""
    global _resolver
    if _resolver is None:
        _resolver = GeoResolver()
    return await _resolver.resolve(location)

