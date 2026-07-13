"""HUD FHA single-family REO ArcGIS source."""

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from cre_mcp.geo.resolver import STATE_FIPS
from cre_mcp.http.arcgis import arcgis_query
from cre_mcp.models import Listing, ListingRef, SourceCapabilities
from cre_mcp.models.geo import GeoLevel, GeoRef
from cre_mcp.sources.base import ListingSource, SearchQuery, SourceError

logger = logging.getLogger(__name__)

HUD_REO_LAYER = (
    "https://services.arcgis.com/VTyQ9soqVukalItT/arcgis/rest/services/"
    "SF_REO/FeatureServer/0"
)
_STATE_ABBR = {fips: abbreviation for abbreviation, fips in STATE_FIPS.items()}
_PAGE_SIZE = 100
# Census TIGERweb county extents for the configured county distressed feeds.
_COUNTY_EXTENTS = {
    "37081": (
        -80.0468690002167,
        35.89985099980246,
        -79.53241000034262,
        36.257183999707166,
    ),
    "04025": (
        -113.3343590003408,
        33.88246899997447,
        -111.46053999961102,
        35.53119400016106,
    ),
    "08035": (
        -105.32944499965761,
        39.12947900008431,
        -104.66058399994039,
        39.56619299967445,
    ),
}


def _escape(value: str) -> str:
    return value.replace("'", "''")


def _where_for(query: SearchQuery) -> str:
    geo = query.geo if isinstance(query.geo, GeoRef) else None
    if geo and geo.level == GeoLevel.ZIP and geo.zip:
        return f"DISPLAY_ZIP_CODE='{_escape(geo.zip)}'"
    state = _STATE_ABBR.get(geo.state_fips) if geo else None
    zip_match = re.search(r"\b(\d{5})\b", query.location)
    if zip_match:
        return f"DISPLAY_ZIP_CODE='{zip_match.group(1)}'"
    state_match = re.search(r"(?:^|,\s*|\s)([A-Za-z]{2})\s*$", query.location)
    state = state or (state_match.group(1).upper() if state_match else None)
    if not state:
        return "1=1"
    if geo and geo.level == GeoLevel.COUNTY:
        return f"STATE_CODE='{_escape(state)}'"
    parts = [part.strip() for part in query.location.rsplit(",", 1)]
    if len(parts) == 2 and parts[0] and not parts[0].casefold().endswith("county"):
        return (
            f"STATE_CODE='{_escape(state)}' AND "
            f"CITY='{_escape(parts[0].upper())}'"
        )
    return f"STATE_CODE='{_escape(state)}'"


def _geometry_for(query: SearchQuery) -> dict[str, Any] | None:
    geo = query.geo if isinstance(query.geo, GeoRef) else None
    extent = _COUNTY_EXTENTS.get(geo.county_fips) if geo else None
    if extent is None:
        return None
    xmin, ymin, xmax, ymax = extent
    return {
        "xmin": xmin,
        "ymin": ymin,
        "xmax": xmax,
        "ymax": ymax,
        "spatialReference": {"wkid": 4326},
    }


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _acquired(value: Any) -> str | None:
    numeric = _number(value)
    if numeric is None:
        return None
    try:
        return datetime.fromtimestamp(numeric / 1_000, tz=UTC).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def map_hud_reo(attributes: dict[str, Any]) -> Listing:
    """Map one live FHA REO feature into the unified listing shape."""
    source_id = str(attributes.get("CASE_NUM") or attributes.get("OBJECTID") or "")
    address = str(attributes.get("ADDRESS") or "").strip()
    if not address:
        address = " ".join(
            str(attributes.get(key) or "").strip()
            for key in ("STREET_NUM", "DIRECTION_PREFIX", "STREET_NAME")
        ).strip()
    city = str(attributes.get("CITY") or "").strip().title()
    state = str(attributes.get("STATE_CODE") or "").strip().upper()
    zip_value = attributes.get("DISPLAY_ZIP_CODE")
    zip_code = str(zip_value).zfill(5) if zip_value not in (None, "") else None
    url = f"{HUD_REO_LAYER}?case={quote(source_id)}"
    raw = dict(attributes)
    raw.setdefault("distress_type", "reo")
    return Listing(
        source="hud_reo",
        source_id=source_id,
        refs=[ListingRef(source="hud_reo", source_id=source_id, url=url)],
        name=f"HUD REO — {address or source_id}",
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        property_type="special-purpose",
        property_subtype="FHA single-family REO",
        listing_type="for-sale",
        url=url,
        last_updated=_acquired(attributes.get("DATE_ACQUIRED")),
        lat=_number(attributes.get("MAP_LATITUDE")),
        lon=_number(attributes.get("MAP_LONGITUDE")),
        is_distressed=True,
        distress_type="reo",
        raw=raw,
    )


class HudReoSource(ListingSource):
    """Free, no-auth HUD FHA REO inventory."""

    name = "hud_reo"
    capabilities = SourceCapabilities(
        supports_distressed=True,
        supports_lease=False,
        supports_price_filter=False,
        supports_size_filter=False,
    )

    async def search(self, query: SearchQuery) -> list[Listing]:
        try:
            attributes = await arcgis_query(
                HUD_REO_LAYER,
                where=_where_for(query),
                geometry=_geometry_for(query),
                result_offset=(max(query.page, 1) - 1) * _PAGE_SIZE,
                result_count=_PAGE_SIZE,
            )
        except Exception as exc:
            raise SourceError(self.name, str(exc), retryable=True) from exc
        listings = [map_hud_reo(item) for item in attributes]
        if query.property_type is not None:
            listings = [
                listing
                for listing in listings
                if listing.property_type == query.property_type.value
            ]
        return listings

    async def get_detail(self, ref: ListingRef) -> Listing:
        if ref.source != self.name:
            raise SourceError(self.name, f"HUD REO cannot resolve {ref.source!r}")
        try:
            attributes = await arcgis_query(
                HUD_REO_LAYER,
                where=f"CASE_NUM='{_escape(ref.source_id)}'",
                result_count=1,
            )
        except Exception as exc:
            raise SourceError(self.name, str(exc), retryable=True) from exc
        if not attributes:
            raise SourceError(self.name, f"HUD REO listing not found: {ref.source_id}")
        return map_hud_reo(attributes[0])


__all__ = ["HUD_REO_LAYER", "HudReoSource", "map_hud_reo"]
