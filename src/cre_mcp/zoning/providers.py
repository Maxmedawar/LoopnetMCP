"""Authoritative municipal zoning-provider registry and query builders.

The registry deliberately describes only sources documented in
``docs/reference/ZONING_SOURCES.md``.  A provider identifies zoning polygons;
it does not imply that FAR, height, setback, parking, or permitted-use rules
are present in the GIS response.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlencode


QueryKind = Literal["arcgis", "socrata", "no_zoning"]


@dataclass(frozen=True)
class LayerSpec:
    """One queryable zoning or overlay layer and its documented field map."""

    endpoint: str
    layer: str
    district_fields: tuple[str, ...] = ()
    description_fields: tuple[str, ...] = ()
    ordinance_fields: tuple[str, ...] = ()
    effective_date_fields: tuple[str, ...] = ()
    overlay_name_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ZoningProvider:
    """A jurisdiction-specific public zoning source."""

    key: str
    jurisdiction: str
    aliases: tuple[str, ...]
    kind: QueryKind
    base_layer: LayerSpec
    code_link: str
    overlay_layers: tuple[LayerSpec, ...] = ()
    inline_overlay_fields: tuple[str, ...] = ()
    geometry_field: str | None = None
    notes: str | None = None


ATLANTA_LAND_USE = (
    "https://gis.atlantaga.gov/dpcd/rest/services/"
    "LandUsePlanning/LandUsePlanning/MapServer"
)


PROVIDERS: dict[str, ZoningProvider] = {
    "austin": ZoningProvider(
        key="austin",
        jurisdiction="Austin, TX",
        aliases=("Austin", "Austin, TX", "City of Austin"),
        kind="arcgis",
        # The reference's Zoning_2 service currently contains overlay layers.
        # The same official Shared catalog publishes the live base as Zoning_1/0.
        base_layer=LayerSpec(
            endpoint=(
                "https://maps.austintexas.gov/gis/rest/Shared/"
                "Zoning_1/MapServer/0"
            ),
            layer="0 — Zoning",
            district_fields=("ZONING_ZTYPE", "ZONING_BASE"),
            ordinance_fields=("ORDINANCE_NUMBER",),
            effective_date_fields=("EFFECTIVE_DATE",),
        ),
        code_link=(
            "https://library.municode.com/tx/austin/codes/code_of_ordinances"
        ),
        notes=(
            "The documented Zoning_2 service was overlay-only when verified "
            "2026-07-14; base zoning is the adjacent official Zoning_1 layer 0."
        ),
    ),
    "phoenix": ZoningProvider(
        key="phoenix",
        jurisdiction="Phoenix, AZ",
        aliases=("Phoenix", "Phoenix, AZ", "City of Phoenix"),
        kind="arcgis",
        base_layer=LayerSpec(
            endpoint=(
                "https://maps.phoenix.gov/pub/rest/services/Public/"
                "Zoning/MapServer/0"
            ),
            layer="0 — Zoning (native SR 2868)",
            district_fields=("ZONING", "LABEL1", "GEN_ZONE"),
            description_fields=("REDEFINE1",),
            ordinance_fields=("ORD_NUM",),
            effective_date_fields=("DATE_APPRO",),
        ),
        overlay_layers=(
            LayerSpec(
                endpoint=(
                    "https://maps.phoenix.gov/pub/rest/services/Public/"
                    "ZoningOverlays/MapServer/0"
                ),
                layer="0 — Zoning Overlays (native SR 2868)",
                overlay_name_fields=("NAME", "REGULATORY"),
                description_fields=("REGULATORY",),
            ),
        ),
        code_link="https://phoenix.municipal.codes/ZO",
    ),
    "denver": ZoningProvider(
        key="denver",
        jurisdiction="Denver, CO",
        aliases=("Denver", "Denver, CO", "City and County of Denver"),
        kind="arcgis",
        base_layer=LayerSpec(
            endpoint="https://denvergov.org/maps/data/Zoning/MapServer/1",
            layer="1 — Zoning",
            district_fields=("ZONE_DISTRICT", "PUD_STD_ZONE_DIST"),
            description_fields=("ZONE_DESCRIPTION", "NOTES", "GIS_NOTE"),
            ordinance_fields=("ORD_NUM", "ORD_YEAR"),
        ),
        inline_overlay_fields=("OVERLAY_DISTRICT",),
        code_link=(
            "https://library.municode.com/co/denver/codes/"
            "code_of_ordinances"
        ),
    ),
    "dallas": ZoningProvider(
        key="dallas",
        jurisdiction="Dallas, TX",
        aliases=("Dallas", "Dallas, TX", "City of Dallas"),
        kind="arcgis",
        base_layer=LayerSpec(
            endpoint=(
                "https://gis.dallascityhall.com/arcgis/rest/services/"
                "sdc_public/Zoning/MapServer/1"
            ),
            layer="1 — Zoning polygon layer",
            district_fields=(
                "ZONING",
                "ZONE",
                "ZONE_DISTRICT",
                "ZONE_CODE",
                "PD_NO",
            ),
            description_fields=("DESCRIPTION", "ZONE_DESC", "ZONING_DESC"),
            ordinance_fields=("ORDINANCE", "ORD_NUM", "ORDINANCE_NUMBER"),
            effective_date_fields=("EFFECTIVE_DATE",),
        ),
        code_link="https://codelibrary.amlegal.com/codes/dallas/latest/overview",
        notes=(
            "The municipal service has documented vhost drift; discover the "
            "current layer through Dallas Open Data if this URL fails."
        ),
    ),
    "atlanta": ZoningProvider(
        key="atlanta",
        jurisdiction="Atlanta, GA",
        aliases=("Atlanta", "Atlanta, GA", "City of Atlanta"),
        kind="arcgis",
        base_layer=LayerSpec(
            endpoint=f"{ATLANTA_LAND_USE}/0",
            layer="0 — Zoning District",
            district_fields=("ZONECLASS",),
            description_fields=("ZONEDESC",),
            ordinance_fields=("ORDINANCE", "ORDINANCE_NUMBER", "ORD_NUM"),
            effective_date_fields=("SUNRISE",),
        ),
        overlay_layers=(
            LayerSpec(
                endpoint=f"{ATLANTA_LAND_USE}/1",
                layer="1 — Zoning Overlay",
                overlay_name_fields=("ZONECLASS", "LABEL", "SPI"),
                description_fields=("ZONEDESC",),
            ),
            LayerSpec(
                endpoint=f"{ATLANTA_LAND_USE}/2",
                layer="2 — Inclusionary Zoning",
                overlay_name_fields=("NAME", "BPA_SUBAREA", "BPA_SEGMENT"),
            ),
            LayerSpec(
                endpoint=f"{ATLANTA_LAND_USE}/4",
                layer="4 — BeltLine TCU Corridor",
                overlay_name_fields=("NAME", "LABEL", "ZONECLASS"),
            ),
            LayerSpec(
                endpoint=f"{ATLANTA_LAND_USE}/5",
                layer="5 — Building Moratorium",
                overlay_name_fields=("NAME", "LABEL", "ZONECLASS"),
                effective_date_fields=("SUNRISE", "START_DATE"),
            ),
            LayerSpec(
                endpoint=f"{ATLANTA_LAND_USE}/6",
                layer="6 — Historic District",
                overlay_name_fields=("NAME", "LABEL", "DISTRICT"),
            ),
            LayerSpec(
                endpoint=f"{ATLANTA_LAND_USE}/7",
                layer="7 — Landmark Building Site",
                overlay_name_fields=("NAME", "LABEL", "LANDMARK"),
            ),
        ),
        code_link=(
            "https://library.municode.com/ga/atlanta/codes/code_of_ordinances"
        ),
        notes=(
            "The reference's OpenDataService layer 22 returned service-not-found "
            "on 2026-07-14; the same documented LandUsePlanning service layer 0 "
            "is the live authoritative ZONECLASS layer."
        ),
    ),
    "las_vegas_city": ZoningProvider(
        key="las_vegas_city",
        jurisdiction="City of Las Vegas, NV",
        aliases=(
            "City of Las Vegas",
            "City of Las Vegas, NV",
            "Las Vegas city",
            "Las Vegas, NV",
        ),
        kind="arcgis",
        base_layer=LayerSpec(
            endpoint=(
                "https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/"
                "rest/services/ZONING/FeatureServer/5"
            ),
            layer="5 — City of Las Vegas Zoning",
            district_fields=("ZONE", "UDC_ZONE", "ROIZONE"),
            description_fields=("DESCRIPTION",),
            ordinance_fields=("ORD",),
            effective_date_fields=("UDC_DATE",),
        ),
        code_link=(
            "https://library.municode.com/nv/las_vegas/codes/"
            "code_of_ordinances"
        ),
        notes=(
            "City limits only. The Las Vegas Strip is unincorporated Clark "
            "County and must use the Clark County provider."
        ),
    ),
    "clark_county": ZoningProvider(
        key="clark_county",
        jurisdiction="Clark County, NV (unincorporated)",
        aliases=(
            "Clark County",
            "Clark County, NV",
            "Unincorporated Clark County",
            "Las Vegas Strip",
            "The Strip",
        ),
        kind="arcgis",
        base_layer=LayerSpec(
            endpoint=(
                "https://maps.clarkcountynv.gov/arcgis/rest/services/"
                "OpenData/PlanningandZoning/MapServer/11"
            ),
            layer="11 — Clark County Zoning",
            district_fields=("ZNCLASS", "MLL_ZNCLASS"),
            description_fields=("Description",),
            ordinance_fields=("ORDINANCE", "ORD_NUM"),
            effective_date_fields=("EFFECTIVE_DATE",),
        ),
        code_link=(
            "https://library.municode.com/nv/clark_county/codes/"
            "code_of_ordinances?nodeId=TIT30UNDECO_30.36ZODIMA"
        ),
    ),
    "new_york_city": ZoningProvider(
        key="new_york_city",
        jurisdiction="New York City, NY",
        aliases=("New York", "New York, NY", "New York City", "NYC"),
        kind="socrata",
        base_layer=LayerSpec(
            endpoint="https://data.cityofnewyork.us/resource/64uk-42ks.json",
            layer="PLUTO — Socrata dataset 64uk-42ks",
            district_fields=("zonedist1",),
            effective_date_fields=("zoningdate",),
        ),
        inline_overlay_fields=(
            "zonedist2",
            "zonedist3",
            "zonedist4",
            "overlay1",
            "overlay2",
            "spdist1",
            "spdist2",
            "spdist3",
            "ltdheight",
            "histdist",
        ),
        geometry_field="geom",
        code_link="https://zr.planning.nyc.gov/",
        notes=(
            "PLUTO contains additional tax-lot attributes, but this adapter "
            "returns only district/overlay identity and never treats PLUTO FAR "
            "fields as verified development standards."
        ),
    ),
    "san_francisco": ZoningProvider(
        key="san_francisco",
        jurisdiction="San Francisco, CA",
        aliases=("San Francisco", "San Francisco, CA", "SF"),
        kind="arcgis",
        base_layer=LayerSpec(
            endpoint=(
                "http://sfplanninggis.org/arcgiswa/rest/services/"
                "PlanningData/MapServer/3"
            ),
            layer="3 — Zoning Map - Zoning Districts",
            district_fields=("zoning", "zoning_sim"),
            description_fields=("districtname", "codesection"),
            effective_date_fields=("last_edit",),
        ),
        code_link=(
            "https://codelibrary.amlegal.com/codes/san_francisco/"
            "latest/overview"
        ),
        notes="The official GIS host is HTTP-only as documented.",
    ),
    "seattle": ZoningProvider(
        key="seattle",
        jurisdiction="Seattle, WA",
        aliases=("Seattle", "Seattle, WA", "City of Seattle"),
        kind="socrata",
        base_layer=LayerSpec(
            endpoint="https://data.seattle.gov/resource/n8h3-r7is.json",
            layer="Current Land Use Zoning Detail — Socrata n8h3-r7is",
            district_fields=(
                "zoning",
                "current_zoning",
                "zone_class",
                "zonelut",
                "base_zone",
            ),
            description_fields=("zonelut_de", "description", "zone_desc"),
            effective_date_fields=("effective_date", "last_update"),
        ),
        inline_overlay_fields=("overlay", "overlay_zone"),
        geometry_field="geom",
        code_link=(
            "https://www.seattle.gov/sdci/codes/codes-we-enforce-(a-z)/zoning"
        ),
        notes=(
            "The Socrata catalog entry is federated from Seattle ArcGIS. If "
            "SODA stops proxying it, use the ArcGIS mirror cited in discovery."
        ),
    ),
    "houston": ZoningProvider(
        key="houston",
        jurisdiction="Houston, TX",
        aliases=("Houston", "Houston, TX", "City of Houston"),
        kind="no_zoning",
        base_layer=LayerSpec(
            endpoint="https://cohgis-mycity.opendata.arcgis.com/",
            layer="No zoning layer — COHGIS Land Use / Special District discovery",
        ),
        code_link=(
            "https://library.municode.com/tx/houston/codes/"
            "code_of_ordinances?nodeId=COOR_CH42SUDEPL"
        ),
        notes=(
            "Houston has no municipal zoning. Development is governed by "
            "Chapter 42 subdivision rules, deed restrictions, and special "
            "districts; COH land use is descriptive, not legal zoning."
        ),
    ),
}


def _jurisdiction_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


_PROVIDER_ALIASES = {
    _jurisdiction_token(alias): provider
    for provider in PROVIDERS.values()
    for alias in (provider.key, provider.jurisdiction, *provider.aliases)
}


def resolve_provider(jurisdiction: str | None) -> ZoningProvider | None:
    """Resolve an explicit/naive city-state string; never infer from a point."""

    if not jurisdiction or not jurisdiction.strip():
        return None
    return _PROVIDER_ALIASES.get(_jurisdiction_token(jurisdiction))


def build_arcgis_query(
    provider_or_layer: ZoningProvider | LayerSpec,
    lat: float,
    lon: float,
) -> str:
    """Build the documented WGS84 ArcGIS point-in-polygon query."""

    layer = (
        provider_or_layer.base_layer
        if isinstance(provider_or_layer, ZoningProvider)
        else provider_or_layer
    )
    geometry = {
        "x": float(lon),
        "y": float(lat),
        "spatialReference": {"wkid": 4326},
    }
    params = {
        "where": "1=1",
        "geometry": json.dumps(geometry, separators=(",", ":")),
        "geometryType": "esriGeometryPoint",
        # Critical for native projected sources such as Phoenix SR 2868.
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    return f"{layer.endpoint.rstrip('/')}/query?{urlencode(params)}"


def build_socrata_zoning_query(
    provider: ZoningProvider,
    lat: float,
    lon: float,
) -> str:
    """Build a Socrata point-in-polygon query for a polygon-backed dataset."""

    if provider.kind != "socrata" or not provider.geometry_field:
        raise ValueError(f"{provider.key} is not a Socrata polygon provider")
    point = f"POINT ({float(lon)} {float(lat)})"
    params = {
        "$where": f"intersects({provider.geometry_field}, '{point}')",
        "$limit": "10",
    }
    return f"{provider.base_layer.endpoint}?{urlencode(params)}"


def _attributes(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    features = payload.get("features")
    if not isinstance(features, list):
        return []
    rows: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        attributes = feature.get("attributes")
        if isinstance(attributes, dict):
            rows.append(attributes)
    return rows


def _value(attributes: dict[str, Any], fields: tuple[str, ...]) -> Any:
    folded = {str(key).casefold(): value for key, value in attributes.items()}
    for field_name in fields:
        value = folded.get(field_name.casefold())
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value.strip() if isinstance(value, str) else value
    return None


def _date_value(attributes: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    value = _value(attributes, fields)
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(
                value / 1000,
                tz=timezone.utc,
            ).isoformat().replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return str(value)
    return str(value)


def normalize_base_payload(
    provider: ZoningProvider,
    payload: Any,
) -> list[dict[str, Any]]:
    """Map ArcGIS features or Socrata rows into the common base-zone shape."""

    records: list[dict[str, Any]] = []
    for attributes in _attributes(payload):
        district = _value(attributes, provider.base_layer.district_fields)
        if district is None:
            continue
        inline_overlays: list[dict[str, Any]] = []
        for field_name in provider.inline_overlay_fields:
            overlay = _value(attributes, (field_name,))
            if overlay is None:
                continue
            inline_overlays.append(
                {
                    "name": str(overlay),
                    "description": None,
                    "ordinance": None,
                    "effective_date": None,
                    "source_endpoint": provider.base_layer.endpoint,
                    "source_layer": (
                        f"{provider.base_layer.layer} field {field_name}"
                    ),
                }
            )
        records.append(
            {
                "district": str(district),
                "description": (
                    str(description)
                    if (
                        description := _value(
                            attributes,
                            provider.base_layer.description_fields,
                        )
                    )
                    is not None
                    else None
                ),
                "ordinance": (
                    str(ordinance)
                    if (
                        ordinance := _value(
                            attributes,
                            provider.base_layer.ordinance_fields,
                        )
                    )
                    is not None
                    else None
                ),
                "effective_date": _date_value(
                    attributes,
                    provider.base_layer.effective_date_fields,
                ),
                "source_endpoint": provider.base_layer.endpoint,
                "source_layer": provider.base_layer.layer,
                "inline_overlays": inline_overlays,
            }
        )
    return records


def normalize_overlay_payload(
    layer: LayerSpec,
    payload: Any,
) -> list[dict[str, Any]]:
    """Map matched overlay features to source-cited common overlay records."""

    overlays: list[dict[str, Any]] = []
    for attributes in _attributes(payload):
        name = _value(
            attributes,
            layer.overlay_name_fields
            + layer.district_fields
            + layer.description_fields,
        )
        # A matched single-purpose layer is meaningful even if it has no label.
        name = str(name) if name is not None else layer.layer.split(" — ", 1)[-1]
        description = _value(attributes, layer.description_fields)
        ordinance = _value(attributes, layer.ordinance_fields)
        overlays.append(
            {
                "name": name,
                "description": str(description) if description is not None else None,
                "ordinance": str(ordinance) if ordinance is not None else None,
                "effective_date": _date_value(
                    attributes,
                    layer.effective_date_fields,
                ),
                "source_endpoint": layer.endpoint,
                "source_layer": layer.layer,
            }
        )
    return overlays


def code_link_for(state: str, city: str) -> str | None:
    """Return a verified human-readable zoning-code library link when wired."""

    combined = resolve_provider(f"{city}, {state}") or resolve_provider(city)
    return combined.code_link if combined is not None else None


__all__ = [
    "LayerSpec",
    "PROVIDERS",
    "ZoningProvider",
    "build_arcgis_query",
    "build_socrata_zoning_query",
    "code_link_for",
    "normalize_base_payload",
    "normalize_overlay_payload",
    "resolve_provider",
]
