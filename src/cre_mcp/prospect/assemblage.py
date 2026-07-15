"""Heuristic adjacent-parcel discovery on configured county ArcGIS layers."""

from __future__ import annotations

import math
import re
from typing import Any

from cre_mcp.enrichment.arcgis import map_parcel
from cre_mcp.enrichment.counties import CountyParcelConfig, config_for_geo
from cre_mcp.enrichment.owner import normalize_owner_name
from cre_mcp.geo import resolve
from cre_mcp.http.arcgis import arcgis_query

_POINT_ENVELOPE_DEGREES = 0.00075
_POLYGON_ENVELOPE_EPSILON = 0.000001


def _text(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def _number(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _coordinates(geometry: object) -> list[tuple[float, float]]:
    if not isinstance(geometry, dict):
        return []
    if geometry.get("x") is not None and geometry.get("y") is not None:
        try:
            return [(float(geometry["x"]), float(geometry["y"]))]
        except (TypeError, ValueError):
            return []
    coordinates: list[tuple[float, float]] = []
    for collection_name in ("rings", "paths"):
        collections = geometry.get(collection_name)
        if not isinstance(collections, list):
            continue
        for collection in collections:
            if not isinstance(collection, list):
                continue
            for point in collection:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                try:
                    coordinates.append((float(point[0]), float(point[1])))
                except (TypeError, ValueError):
                    continue
    return coordinates


def _bounds(geometry: object) -> tuple[float, float, float, float] | None:
    coordinates = _coordinates(geometry)
    if not coordinates:
        return None
    xs = [point[0] for point in coordinates]
    ys = [point[1] for point in coordinates]
    return min(xs), min(ys), max(xs), max(ys)


def _bounds_connect(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    """Return whether two parcel bounds touch or overlap within query tolerance."""

    tolerance = _POLYGON_ENVELOPE_EPSILON * 2
    return not (
        first[2] < second[0] - tolerance
        or second[2] < first[0] - tolerance
        or first[3] < second[1] - tolerance
        or second[3] < first[1] - tolerance
    )


def _query_envelope(
    geometry: object,
    *,
    fallback_lat: float | None,
    fallback_lon: float | None,
) -> tuple[dict[str, Any], str]:
    coordinates = _coordinates(geometry)
    if coordinates:
        xs = [point[0] for point in coordinates]
        ys = [point[1] for point in coordinates]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        is_area = xmax > xmin and ymax > ymin and len(coordinates) > 1
        padding = _POLYGON_ENVELOPE_EPSILON if is_area else _POINT_ENVELOPE_DEGREES
        return (
            {
                "xmin": xmin - padding,
                "ymin": ymin - padding,
                "xmax": xmax + padding,
                "ymax": ymax + padding,
                "spatialReference": {"wkid": 4326},
            },
            (
                "subject_geometry_envelope_intersection"
                if is_area
                else "point_proximity_envelope_fallback"
            ),
        )
    if fallback_lat is None or fallback_lon is None:
        raise ValueError(
            "The county layer did not return subject geometry; provide lat and lon "
            "to permit an explicitly labeled proximity-envelope fallback"
        )
    return (
        {
            "xmin": fallback_lon - _POINT_ENVELOPE_DEGREES,
            "ymin": fallback_lat - _POINT_ENVELOPE_DEGREES,
            "xmax": fallback_lon + _POINT_ENVELOPE_DEGREES,
            "ymax": fallback_lat + _POINT_ENVELOPE_DEGREES,
            "spatialReference": {"wkid": 4326},
        },
        "point_proximity_envelope_fallback",
    )


def _field_list(config: CountyParcelConfig) -> str:
    fields = dict.fromkeys(
        field for field in config.field_map.values() if isinstance(field, str) and field
    )
    return ",".join(fields) or "*"


def _quote(value: str) -> str:
    return value.replace("'", "''")


def _parcel_view(attributes: dict[str, Any], config: CountyParcelConfig) -> dict[str, Any]:
    parcel = map_parcel(attributes, config)
    return {
        "parcel_id": parcel.apn,
        "site_address": parcel.site_address,
        "owner_name": parcel.owner_name,
        "assessed_value": parcel.assessed_value,
        "sf": parcel.building_sqft,
        "use": parcel.use_code,
        "geometry": attributes.get("_geometry"),
    }


def fragmentation_report(parcels: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Summarize ownership fragmentation in the supplied contiguous parcel order.

    The function does not infer legal control. The caller's list order is treated as
    the contiguity sequence, so the basis is exposed with the result.
    """

    if parcels is None:
        parcels = []
    if not isinstance(parcels, list):
        raise ValueError("parcels must be a list")

    owners: list[str | None] = []
    display_names: dict[str, str] = {}
    unrecognized_rows: list[int] = []
    recognized_fields = {
        "parcel_id",
        "apn",
        "site_address",
        "owner_name",
        "assessed_value",
        "sf",
        "use",
        "geometry",
    }
    unrecognized_fields: set[str] = set()
    for index, parcel in enumerate(parcels):
        if not isinstance(parcel, dict):
            unrecognized_rows.append(index)
            owners.append(None)
            continue
        unrecognized_fields.update(str(key) for key in parcel if key not in recognized_fields)
        owner_name = _text(parcel.get("owner_name"))
        owner = normalize_owner_name(owner_name) if owner_name else None
        owners.append(owner or None)
        if owner:
            display_names.setdefault(owner, owner_name or owner)

    bounds = [
        _bounds(parcel.get("geometry")) if isinstance(parcel, dict) else None
        for parcel in parcels
    ]
    use_geometry_graph = bool(parcels) and all(bound is not None for bound in bounds)
    longest_owner: str | None = None
    longest_run = 0
    if use_geometry_graph:
        visited: set[int] = set()
        for start, owner in enumerate(owners):
            if start in visited or owner is None:
                continue
            component = {start}
            frontier = [start]
            visited.add(start)
            while frontier:
                current = frontier.pop()
                for candidate, candidate_owner in enumerate(owners):
                    if candidate in component or candidate_owner != owner:
                        continue
                    current_bounds = bounds[current]
                    candidate_bounds = bounds[candidate]
                    if (
                        current_bounds is not None
                        and candidate_bounds is not None
                        and _bounds_connect(current_bounds, candidate_bounds)
                    ):
                        component.add(candidate)
                        visited.add(candidate)
                        frontier.append(candidate)
            if len(component) > longest_run:
                longest_owner = owner
                longest_run = len(component)
    else:
        current_owner: str | None = None
        current_run = 0
        for owner in owners:
            if owner is not None and owner == current_owner:
                current_run += 1
            elif owner is not None:
                current_owner = owner
                current_run = 1
            else:
                current_owner = None
                current_run = 0
            if current_run > longest_run:
                longest_owner = owner
                longest_run = current_run

    distinct = sorted({owner for owner in owners if owner is not None})
    return {
        "label": "HEURISTIC",
        "heuristic_basis": (
            "Distinct normalized assessor owner names and the largest connected "
            "same-owner component using parcel bounding boxes."
            if use_geometry_graph
            else "Distinct normalized assessor owner names and consecutive equal-owner "
            "records in the supplied parcel order because usable geometry was missing."
        ),
        "contiguity_method": (
            "touching_or_overlapping_geometry_bounds"
            if use_geometry_graph
            else "supplied_order_fallback"
        ),
        "control_caution": "Assessor-name similarity is not proof of common legal control.",
        "parcel_count": len(parcels),
        "distinct_owners": len(distinct),
        "unknown_owner_count": sum(owner is None for owner in owners),
        "largest_contiguous_same_owner_run": longest_run,
        "largest_run_owner": (
            display_names.get(longest_owner) if longest_owner is not None else None
        ),
        "owner_sequence": [display_names.get(owner) if owner else None for owner in owners],
        "unrecognized_rows": unrecognized_rows,
        "unrecognized_input_fields": sorted(unrecognized_fields),
    }


async def adjacent_parcels(
    lat: float | None = None,
    lon: float | None = None,
    parcel_id: str | None = None,
    county: str | None = None,
) -> dict[str, Any]:
    """Find envelope-intersection candidates on an owner-lookup county layer.

    ``county`` is required because parcel identifiers are county-scoped and the
    configured provider registry is keyed by county FIPS.
    """

    has_lat = lat is not None
    has_lon = lon is not None
    if has_lat != has_lon:
        raise ValueError("lat and lon must be supplied together")
    if parcel_id is None and not (has_lat and has_lon):
        raise ValueError("Provide lat and lon, or parcel_id")
    if not _text(county):
        raise ValueError("county is required to select a configured parcel layer")

    latitude: float | None = None
    longitude: float | None = None
    if has_lat and has_lon:
        latitude = _number(lat, "lat")
        longitude = _number(lon, "lon")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("lat/lon are outside WGS84 bounds")

    geo = await resolve(str(county))
    config = config_for_geo(geo)
    if config is None:
        raise ValueError(f"No configured public county parcel layer for {county}")
    fields = _field_list(config)

    if parcel_id is not None:
        apn_field = config.field_map.get("apn")
        if not apn_field:
            raise ValueError(f"{config.name} does not expose a configured parcel-id field")
        normalized_id = re.sub(r"\s+", "", str(parcel_id)).upper()
        if not normalized_id:
            raise ValueError("parcel_id cannot be blank")
        subject_rows = await arcgis_query(
            config.arcgis_url,
            where=f"UPPER({apn_field})='{_quote(normalized_id)}'",
            out_fields=fields,
            return_geometry=True,
            out_sr=4326,
            result_count=1,
        )
        subject_basis = "parcel_id"
    else:
        subject_rows = await arcgis_query(
            config.arcgis_url,
            geometry={
                "x": longitude,
                "y": latitude,
                "spatialReference": {"wkid": 4326},
            },
            out_fields=fields,
            return_geometry=True,
            out_sr=4326,
            result_count=1,
        )
        subject_basis = "coordinate_intersection"
    if not subject_rows:
        raise ValueError("No subject parcel found on the configured county layer")

    subject_attributes = subject_rows[0]
    subject = _parcel_view(subject_attributes, config)
    envelope, query_method = _query_envelope(
        subject_attributes.get("_geometry"),
        fallback_lat=latitude,
        fallback_lon=longitude,
    )
    candidate_rows = await arcgis_query(
        config.arcgis_url,
        geometry=envelope,
        out_fields=fields,
        return_geometry=True,
        out_sr=4326,
        result_count=200,
    )

    subject_id = _text(subject.get("parcel_id"))
    neighbors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for attributes in candidate_rows:
        candidate = _parcel_view(attributes, config)
        candidate_id = _text(candidate.get("parcel_id"))
        identity = candidate_id or repr(candidate.get("geometry"))
        if (subject_id and candidate_id == subject_id) or identity in seen:
            continue
        seen.add(identity)
        neighbors.append(candidate)

    assemblage_parcels = [subject, *neighbors]
    return {
        "status": "OK",
        "label": "HEURISTIC",
        "heuristic_basis": (
            "Candidates are county ArcGIS features intersecting the subject parcel's "
            "WGS84 envelope. Envelope intersection can include parcels that do not "
            "share a legal boundary."
            if query_method == "subject_geometry_envelope_intersection"
            else "The county returned point/no polygon geometry, so candidates are "
            "features in an approximately 75-metre coordinate envelope; they are "
            "proximity candidates, not proven adjacent parcels."
        ),
        "subject_lookup_basis": subject_basis,
        "adjacency_query_method": query_method,
        "subject": subject,
        "neighbors": neighbors,
        "neighbor_count": len(neighbors),
        "fragmentation_report": fragmentation_report(assemblage_parcels),
        "fragmentation_scope": "subject_and_neighbors_in_provider_order",
        "source": {
            "county": config.name,
            "county_fips": config.fips,
            "layer": config.arcgis_url,
        },
        "verification": (
            "Heuristic only: verify legal adjacency, parcel boundaries, ownership, "
            "and assemblage feasibility with county records, title, and a survey."
        ),
    }


__all__ = ["adjacent_parcels", "fragmentation_report"]
