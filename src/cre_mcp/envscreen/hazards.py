"""Flood, wildfire, and seismic hazard lookups for pre-Phase-I screening."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from cre_mcp.http.fetch import FetchClient, get_fetch_client

FEMA_NFHL_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/"
    "MapServer/28/query"
)
USFS_WHP_URL = (
    "https://apps.fs.usda.gov/fsgisx01/rest/services/RDW_Wildfire/"
    "RMRS_WRC_WildfireHazardPotential/ImageServer/identify"
)
USFS_WHP_MIGRATED_URL = (
    "https://imagery.geoplatform.gov/iipp/rest/services/Fire_Aviation/"
    "USFS_EDW_RMRS_WildfireHazardPotentialClassified/ImageServer/identify"
)
USGS_DESIGN_URL = "https://earthquake.usgs.gov/ws/designmaps/asce7-22.json"
USGS_QUAKE_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

FEMA_SOURCE = {
    "name": "FEMA NFHL",
    "url": "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer",
    "endpoint": FEMA_NFHL_URL,
    "auth": "None",
    "reliability": "A",
}
USFS_SOURCE = {
    "name": "USFS WHP",
    "url": "https://apps.fs.usda.gov/arcx/rest/services/RDW_Wildfire/RMRS_WildfireHazardPotential_2023/MapServer",
    "endpoint": USFS_WHP_URL,
    "auth": "None",
    "reliability": "A",
}
USGS_DESIGN_SOURCE = {
    "name": "USGS ASCE 7-22 Design Maps",
    "url": "https://earthquake.usgs.gov/ws/designmaps/",
    "endpoint": USGS_DESIGN_URL,
    "auth": "None",
    "reliability": "A",
}
USGS_QUAKE_SOURCE = {
    "name": "USGS Earthquake Catalog",
    "url": "https://earthquake.usgs.gov/fdsnws/event/1/",
    "endpoint": USGS_QUAKE_URL,
    "auth": "None",
    "reliability": "A",
}

FLOOD_NULL_NOTE = "not mapped, not evaluated \u2260 no risk"
WHP_CLASSES = {
    1: "very_low",
    2: "low",
    3: "moderate",
    4: "high",
    5: "very_high",
    6: "non_burnable",
    7: "water",
}


def _validate_point(lat: float, lon: float) -> tuple[float, float]:
    latitude = float(lat)
    longitude = float(lon)
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("latitude must be finite and between -90 and 90")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("longitude must be finite and between -180 and 180")
    return latitude, longitude


def _error(payload: Any, source: str) -> str | None:
    if not isinstance(payload, Mapping):
        return f"{source} response must be a JSON object"
    error = payload.get("error") or payload.get("Error")
    if not error:
        return None
    if isinstance(error, Mapping):
        return str(error.get("message") or error.get("details") or error)
    return str(error)


def _result(
    source: Mapping[str, str],
    *,
    status: str,
    url: str,
    hits: list[dict[str, Any]] | None = None,
    note: str | None = None,
    error: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "source": source["name"],
        "status": status,
        "hits": hits or [],
        "query_url": url,
        "note": note,
        "error": str(error) if error is not None else None,
        **extra,
    }


def parse_flood_payload(payload: Any) -> list[dict[str, Any]]:
    """Extract NFHL layer-28 attributes and normalize BFE sentinels."""
    message = _error(payload, "FEMA NFHL")
    if message:
        raise ValueError(message)
    features = payload.get("features") if isinstance(payload, Mapping) else None
    if features is None:
        raise ValueError("FEMA NFHL response omitted features")
    if not isinstance(features, list):
        raise ValueError("FEMA NFHL features must be a list")
    zones: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        attrs = feature.get("attributes")
        if not isinstance(attrs, Mapping):
            continue
        raw_bfe = attrs.get("STATIC_BFE")
        try:
            bfe = float(raw_bfe) if raw_bfe not in (None, "") else None
        except (TypeError, ValueError):
            bfe = None
        if bfe is not None and bfe <= -9999:
            bfe = None
        sfha_raw = attrs.get("SFHA_TF")
        sfha = None
        if sfha_raw is not None:
            sfha = str(sfha_raw).strip().upper() in {"T", "Y", "TRUE", "1"}
        zones.append(
            {
                "flood_zone": attrs.get("FLD_ZONE"),
                "zone_subtype": attrs.get("ZONE_SUBTY"),
                "special_flood_hazard_area": sfha,
                "static_bfe_ft": bfe,
                "source": FEMA_SOURCE["name"],
                "source_url": FEMA_SOURCE["url"],
            }
        )
    return zones


async def fema_flood_zone(
    lat: float,
    lon: float,
    *,
    fetch: FetchClient | None = None,
) -> dict[str, Any]:
    """Return the NFHL polygon(s) intersecting a point, or an explicit null."""
    latitude, longitude = _validate_point(lat, lon)
    params = {
        "geometry": f"{longitude:g},{latitude:g}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE",
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{FEMA_NFHL_URL}?{urlencode(params)}"
    try:
        payload = await (fetch or get_fetch_client()).get_json(url)
        zones = parse_flood_payload(payload)
        return _result(
            FEMA_SOURCE,
            status="hit" if zones else "null",
            url=url,
            hits=zones,
            note=None if zones else FLOOD_NULL_NOTE,
            zone=zones[0] if zones else None,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return _result(
            FEMA_SOURCE,
            status="query_failed",
            url=url,
            error=exc,
            zone=None,
        )


def parse_whp_payload(payload: Any) -> dict[str, Any] | None:
    """Normalize a USFS ImageServer identify response."""
    message = _error(payload, "USFS WHP")
    if message:
        raise ValueError(message)
    if not isinstance(payload, Mapping):
        raise ValueError("USFS WHP response must be a JSON object")
    raw = payload.get("value")
    if raw is None:
        values = payload.get("properties")
        raw = values.get("Values", [None])[0] if isinstance(values, Mapping) else None
    if raw is None or str(raw).strip().casefold() in {"nodata", "no data", "null"}:
        return None
    try:
        value = int(float(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unrecognized USFS WHP value: {raw!r}") from exc
    return {
        "class_value": value,
        "class_label": WHP_CLASSES.get(value, "unknown"),
        "resolution_m": 270,
        "source": USFS_SOURCE["name"],
        "source_url": USFS_SOURCE["url"],
        "parcel_specific": False,
    }


def _whp_url(base: str, latitude: float, longitude: float) -> str:
    geometry = {
        "x": longitude,
        "y": latitude,
        "spatialReference": {"wkid": 4326},
    }
    params = {
        "geometry": json.dumps(geometry, separators=(",", ":")),
        "geometryType": "esriGeometryPoint",
        "sr": "4326",
        "returnGeometry": "false",
        "f": "json",
    }
    return f"{base}?{urlencode(params)}"


async def wildfire_hazard(
    lat: float,
    lon: float,
    *,
    fetch: FetchClient | None = None,
) -> dict[str, Any]:
    """Point-sample the 270 m USFS Wildfire Hazard Potential raster."""
    latitude, longitude = _validate_point(lat, lon)
    client = fetch or get_fetch_client()
    attempted: list[str] = []
    last_error: Exception | None = None
    for endpoint in (USFS_WHP_URL, USFS_WHP_MIGRATED_URL):
        url = _whp_url(endpoint, latitude, longitude)
        attempted.append(url)
        try:
            payload = await client.get_json(url)
            hazard = parse_whp_payload(payload)
            return _result(
                USFS_SOURCE,
                status="hit" if hazard else "null",
                url=url,
                hits=[hazard] if hazard else [],
                note=(
                    "No raster value at this point; this is not a parcel-level no-risk finding."
                    if hazard is None
                    else "Landscape-scale 270 m screening value; structure and defensible-space conditions are not evaluated."
                ),
                hazard=hazard,
                attempted_urls=attempted,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = exc
    return _result(
        USFS_SOURCE,
        status="query_failed",
        url=attempted[-1],
        error=last_error or "USFS WHP query failed",
        hazard=None,
        attempted_urls=attempted,
    )


def parse_design_payload(payload: Any) -> dict[str, Any]:
    """Extract the ASCE 7-22 values used by a screening profile."""
    message = _error(payload, "USGS Design Maps")
    if message:
        raise ValueError(message)
    if not isinstance(payload, Mapping):
        raise ValueError("USGS design response must be a JSON object")
    request = payload.get("request")
    if isinstance(request, Mapping) and request.get("status") not in (None, "success"):
        raise ValueError(f"USGS design request status: {request.get('status')}")
    response = payload.get("response", payload)
    data = response.get("data") if isinstance(response, Mapping) else None
    if not isinstance(data, Mapping):
        raise ValueError("USGS design response omitted response.data")
    aliases = {
        "SS": "ss",
        "S1": "s1",
        "SMS": "sms",
        "SM1": "sm1",
        "SDS": "sds",
        "SD1": "sd1",
    }
    values = {label: data.get(field) for label, field in aliases.items()}
    if all(value is None for value in values.values()):
        raise ValueError("USGS design response omitted spectral values")
    return {
        **values,
        "seismic_design_category": data.get("sdc"),
        "site_class": (
            request.get("parameters", {}).get("siteClass")
            if isinstance(request, Mapping)
            and isinstance(request.get("parameters"), Mapping)
            else "D"
        ),
        "reference_document": "ASCE 7-22",
        "site_specific_geotech_required": True,
        "source": USGS_DESIGN_SOURCE["name"],
        "source_url": USGS_DESIGN_SOURCE["url"],
    }


async def seismic_design_values(
    lat: float,
    lon: float,
    *,
    fetch: FetchClient | None = None,
) -> dict[str, Any]:
    """Query ASCE 7-22 design values using the explicit default Site Class D."""
    latitude, longitude = _validate_point(lat, lon)
    params = {
        "latitude": f"{latitude:g}",
        "longitude": f"{longitude:g}",
        "riskCategory": "II",
        "siteClass": "D",
        "title": "Pre-Phase I Screen",
    }
    url = f"{USGS_DESIGN_URL}?{urlencode(params)}"
    try:
        payload = await (fetch or get_fetch_client()).get_json(url)
        values = parse_design_payload(payload)
        return _result(
            USGS_DESIGN_SOURCE,
            status="hit",
            url=url,
            hits=[values],
            note="Site Class D is a screening assumption; site-specific geotechnical work is required.",
            design_values=values,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return _result(
            USGS_DESIGN_SOURCE,
            status="query_failed",
            url=url,
            error=exc,
            design_values=None,
        )


async def earthquake_catalog(
    lat: float,
    lon: float,
    *,
    radius_km: float = 50,
    min_magnitude: float = 2.5,
    fetch: FetchClient | None = None,
) -> dict[str, Any]:
    """Count earthquakes returned by the USGS FDSN radial catalog query."""
    latitude, longitude = _validate_point(lat, lon)
    radius = float(radius_km)
    magnitude = float(min_magnitude)
    if not math.isfinite(radius) or radius <= 0 or radius > 20001.6:
        raise ValueError("radius_km must be greater than 0 and at most 20001.6")
    if not math.isfinite(magnitude):
        raise ValueError("min_magnitude must be finite")
    params = {
        "format": "geojson",
        "latitude": f"{latitude:g}",
        "longitude": f"{longitude:g}",
        "maxradiuskm": f"{radius:g}",
        "minmagnitude": f"{magnitude:g}",
    }
    url = f"{USGS_QUAKE_URL}?{urlencode(params)}"
    try:
        payload = await (fetch or get_fetch_client()).get_json(url)
        message = _error(payload, "USGS Earthquake Catalog")
        if message:
            raise ValueError(message)
        if not isinstance(payload, Mapping):
            raise ValueError("USGS catalog response must be a JSON object")
        features = payload.get("features")
        if not isinstance(features, list):
            raise ValueError("USGS catalog response omitted features")
        count = len(features)
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping) and isinstance(metadata.get("count"), int):
            count = int(metadata["count"])
        hit = {
            "count": count,
            "radius_km": radius,
            "minimum_magnitude": magnitude,
            "source": USGS_QUAKE_SOURCE["name"],
            "source_url": USGS_QUAKE_SOURCE["url"],
        }
        return _result(
            USGS_QUAKE_SOURCE,
            status="hit" if count else "null",
            url=url,
            hits=[hit] if count else [],
            note=(
                None
                if count
                else "No catalog events matched the stated radius and magnitude filters; this is not a seismic safety finding."
            ),
            count=count,
            radius_km=radius,
            minimum_magnitude=magnitude,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return _result(
            USGS_QUAKE_SOURCE,
            status="query_failed",
            url=url,
            error=exc,
            count=None,
            radius_km=radius,
            minimum_magnitude=magnitude,
        )


HAZARD_GAPS = {
    "flood": "NFHL does not model every unmapped area, pluvial flooding, future climate, or structure-specific LOMA status.",
    "wildfire": "A 270 m landscape raster cannot see defensible space, structure hardening, or parcel micro-topography.",
    "seismic": "Default Site Class D is not measured Vs30 or borehole data; site-specific geotechnical evaluation is required.",
}


async def hazard_profile(
    lat: float,
    lon: float,
    *,
    fetch: FetchClient | None = None,
) -> dict[str, Any]:
    """Build an explicitly qualified flood, wildfire, and seismic profile."""
    latitude, longitude = _validate_point(lat, lon)
    flood, wildfire, design, quakes = await asyncio.gather(
        fema_flood_zone(latitude, longitude, fetch=fetch),
        wildfire_hazard(latitude, longitude, fetch=fetch),
        seismic_design_values(latitude, longitude, fetch=fetch),
        earthquake_catalog(latitude, longitude, fetch=fetch),
    )
    results = [flood, wildfire, design, quakes]
    return {
        "report_type": "PRE-PHASE-I PHYSICAL HAZARD SCREEN",
        "location": {"lat": latitude, "lon": longitude},
        "results": {
            "flood": flood,
            "wildfire": wildfire,
            "seismic_design": design,
            "earthquake_catalog": quakes,
        },
        "sources_queried": [result["source"] for result in results],
        "sources_null": [
            result["source"] for result in results if result["status"] == "null"
        ],
        "sources_failed": [
            result["source"]
            for result in results
            if result["status"] == "query_failed"
        ],
        "uncoverable_gaps": dict(HAZARD_GAPS),
    }


# Descriptive aliases for direct module consumers. The integration-facing
# callables remain the plain functions in ``envscreen.tools``.
flood_zone = fema_flood_zone
usfs_whp = wildfire_hazard
usgs_seismic_design = seismic_design_values
quake_catalog = earthquake_catalog


__all__ = [
    "FEMA_SOURCE",
    "FLOOD_NULL_NOTE",
    "HAZARD_GAPS",
    "USFS_SOURCE",
    "USGS_DESIGN_SOURCE",
    "USGS_QUAKE_SOURCE",
    "earthquake_catalog",
    "fema_flood_zone",
    "flood_zone",
    "hazard_profile",
    "parse_design_payload",
    "parse_flood_payload",
    "parse_whp_payload",
    "seismic_design_values",
    "quake_catalog",
    "usfs_whp",
    "usgs_seismic_design",
    "wildfire_hazard",
]
