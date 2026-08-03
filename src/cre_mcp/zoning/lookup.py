"""Point zoning lookup across the explicitly wired municipal providers.

Jurisdiction resolution v1 is intentionally simple: callers pass an explicit
jurisdiction name such as ``"Phoenix, AZ"`` or a naive city/state string.
Resolving a jurisdiction boundary from latitude/longitude is a later phase.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cre_mcp.http.errors import FetchClientError
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.zoning.providers import (
    LayerSpec,
    ZoningProvider,
    build_arcgis_query,
    build_socrata_zoning_query,
    normalize_base_payload,
    normalize_overlay_payload,
    resolve_provider,
)


_POLITE_QUERY_INTERVAL_SECONDS = 0.21
_STANDARDS_GAP = {
    "far": None,
    "height": None,
    "setbacks": None,
    "parking": None,
    "permitted_uses": None,
    "reason": (
        "These rules are in the governing zoning code, not the zoning polygon "
        "response. Read the cited code library; no standards are inferred."
    ),
}


def _validate_point(lat: float, lon: float) -> tuple[float, float]:
    if isinstance(lat, bool) or isinstance(lon, bool):
        raise ValueError("Latitude and longitude must be numeric")
    try:
        latitude = float(lat)
        longitude = float(lon)
    except (TypeError, ValueError) as exc:
        raise ValueError("Latitude and longitude must be numeric") from exc
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180")
    return latitude, longitude


def _unsupported(jurisdiction: str | None) -> dict[str, Any]:
    requested = jurisdiction.strip() if jurisdiction and jurisdiction.strip() else None
    return {
        "status": "UNSUPPORTED",
        "has_zoning": None,
        "jurisdiction": requested,
        "district": None,
        "districts": [],
        "description": None,
        "overlays": [],
        "ordinance": None,
        "effective_date": None,
        "source_endpoint": None,
        "source_layer": None,
        "sources": [],
        "code_link": None,
        "development_standards": dict(_STANDARDS_GAP),
        "discovery_hint": (
            "Pass an explicitly wired city/state or county name. Coordinate-only "
            "jurisdiction boundary resolution is a later phase; search the local "
            "municipal/county ArcGIS Hub for a current zoning polygon layer."
        ),
        "jurisdiction_resolution": "explicit-or-naive-city-state-v1",
    }


def _houston(provider: ZoningProvider) -> dict[str, Any]:
    source = {
        "source_endpoint": provider.base_layer.endpoint,
        "source_layer": provider.base_layer.layer,
        "ordinance": None,
        "effective_date": None,
    }
    return {
        "status": "SUPPORTED_NO_ZONING",
        "has_zoning": False,
        "jurisdiction": provider.jurisdiction,
        "district": None,
        "districts": [],
        "description": (
            "Houston has no municipal zoning. COH land-use layers describe "
            "existing use but are not legal zoning. Development is governed by "
            "Chapter 42 subdivision rules, applicable special districts, and "
            "private deed restrictions; deed restrictions require separate "
            "title/document review."
        ),
        "overlays": [],
        "ordinance": None,
        "effective_date": None,
        "source_endpoint": provider.base_layer.endpoint,
        "source_layer": provider.base_layer.layer,
        "sources": [source],
        "code_link": provider.code_link,
        "development_standards": dict(_STANDARDS_GAP),
        "discovery_hint": (
            "Use the COHGIS Data Hub to discover current Land Use and Special "
            "District layers, then review Chapter 42 and recorded deed restrictions."
        ),
        "jurisdiction_resolution": "explicit-or-naive-city-state-v1",
        "provider_notes": provider.notes,
    }


def _raise_service_error(payload: Any, endpoint: str) -> None:
    if not isinstance(payload, dict) or not payload.get("error"):
        return
    error = payload["error"]
    if isinstance(error, dict):
        message = error.get("message") or error.get("details") or error
    else:
        message = error
    raise FetchClientError(f"Zoning query failed for {endpoint}: {message}")


def _citation(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_endpoint": record["source_endpoint"],
        "source_layer": record["source_layer"],
        "ordinance": record.get("ordinance"),
        "effective_date": record.get("effective_date"),
    }


def _dedupe_citations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    citations: list[dict[str, Any]] = []
    for item in items:
        key = (
            item.get("source_endpoint"),
            item.get("source_layer"),
            item.get("ordinance"),
            item.get("effective_date"),
        )
        if key in seen:
            continue
        seen.add(key)
        citations.append(item)
    return citations


async def _get_payload(
    fetch: FetchClient,
    provider: ZoningProvider,
    lat: float,
    lon: float,
) -> tuple[Any, str]:
    if provider.kind == "arcgis":
        request_url = build_arcgis_query(provider, lat, lon)
    elif provider.kind == "socrata":
        request_url = build_socrata_zoning_query(provider, lat, lon)
    else:  # guarded before this helper
        raise ValueError(f"Provider {provider.key} has no queryable zoning layer")
    payload = await fetch.get_json(request_url)
    _raise_service_error(payload, provider.base_layer.endpoint)
    return payload, request_url


async def _get_overlay(
    fetch: FetchClient,
    layer: LayerSpec,
    lat: float,
    lon: float,
) -> tuple[list[dict[str, Any]], str]:
    request_url = build_arcgis_query(layer, lat, lon)
    payload = await fetch.get_json(request_url)
    _raise_service_error(payload, layer.endpoint)
    return normalize_overlay_payload(layer, payload), request_url


async def zoning_at(
    lat: float,
    lon: float,
    jurisdiction: str | None,
    *,
    fetch: FetchClient | None = None,
) -> dict[str, Any]:
    """Return source-cited zoning at a point or an explicit honesty status."""

    latitude, longitude = _validate_point(lat, lon)
    provider = resolve_provider(jurisdiction)
    if provider is None:
        return _unsupported(jurisdiction)
    if provider.kind == "no_zoning":
        return _houston(provider)

    client = fetch or get_fetch_client()
    payload, request_url = await _get_payload(
        client,
        provider,
        latitude,
        longitude,
    )
    base_records = normalize_base_payload(provider, payload)
    overlays: list[dict[str, Any]] = [
        overlay
        for record in base_records
        for overlay in record.pop("inline_overlays", [])
    ]
    queried_sources = [
        {
            "source_endpoint": provider.base_layer.endpoint,
            "source_layer": provider.base_layer.layer,
            "request_url": request_url,
        }
    ]

    for layer in provider.overlay_layers:
        # Keep municipal traffic below the documented five-request/second ceiling.
        await asyncio.sleep(_POLITE_QUERY_INTERVAL_SECONDS)
        matched, overlay_url = await _get_overlay(
            client,
            layer,
            latitude,
            longitude,
        )
        overlays.extend(matched)
        queried_sources.append(
            {
                "source_endpoint": layer.endpoint,
                "source_layer": layer.layer,
                "request_url": overlay_url,
            }
        )

    primary = base_records[0] if base_records else None
    sources = [_citation(record) for record in base_records]
    sources.extend(_citation(overlay) for overlay in overlays)
    if not sources:
        sources.append(
            {
                "source_endpoint": provider.base_layer.endpoint,
                "source_layer": provider.base_layer.layer,
                "ordinance": None,
                "effective_date": None,
            }
        )

    result = {
        "status": "OK" if primary is not None else "NO_MATCH",
        # NO_MATCH may mean outside the supplied jurisdiction, not no zoning.
        "has_zoning": True if primary is not None else None,
        "jurisdiction": provider.jurisdiction,
        "district": primary["district"] if primary is not None else None,
        "districts": [record["district"] for record in base_records],
        "description": primary["description"] if primary is not None else None,
        "overlays": overlays,
        "ordinance": primary["ordinance"] if primary is not None else None,
        "effective_date": (
            primary["effective_date"] if primary is not None else None
        ),
        "source_endpoint": provider.base_layer.endpoint,
        "source_layer": provider.base_layer.layer,
        "sources": _dedupe_citations(sources),
        "queried_sources": queried_sources,
        "code_link": provider.code_link,
        "development_standards": dict(_STANDARDS_GAP),
        "discovery_hint": (
            None
            if primary is not None
            else (
                "No polygon intersected the point. Confirm the explicit "
                "jurisdiction and inspect its ArcGIS/Socrata discovery page; "
                "coordinate-based boundary resolution is not implemented in v1."
            )
        ),
        "jurisdiction_resolution": "explicit-or-naive-city-state-v1",
        "provider_notes": provider.notes,
    }
    return result


__all__ = ["zoning_at"]
