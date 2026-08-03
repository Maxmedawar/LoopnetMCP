"""Nearby building-permit lookups for the documented Socrata cities."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Mapping
from urllib.parse import urlencode

from cre_mcp.access.context import current_runtime_config
from cre_mcp.http.errors import FetchClientError
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.source_rights.gate import require_url

if TYPE_CHECKING:
    from cre_mcp.config import CreConfig


@dataclass(frozen=True)
class PermitSource:
    key: str
    city: str
    aliases: tuple[str, ...]
    portal: str
    dataset_id: str
    dataset_name: str
    date_field: str
    location_field: str

    @property
    def endpoint(self) -> str:
        return f"https://{self.portal}/resource/{self.dataset_id}.json"


PERMIT_SOURCES: dict[str, PermitSource] = {
    "austin": PermitSource(
        key="austin",
        city="Austin, TX",
        aliases=("Austin", "Austin, TX"),
        portal="data.austintexas.gov",
        dataset_id="3syk-w9eu",
        dataset_name="Issued Construction Permits",
        date_field="issue_date",
        location_field="location",
    ),
    "chicago": PermitSource(
        key="chicago",
        city="Chicago, IL",
        aliases=("Chicago", "Chicago, IL"),
        portal="data.cityofchicago.org",
        dataset_id="ydr8-5enu",
        dataset_name="Building Permits",
        date_field="issue_date",
        location_field="location",
    ),
    "san_francisco": PermitSource(
        key="san_francisco",
        city="San Francisco, CA",
        aliases=("San Francisco", "San Francisco, CA", "SF"),
        portal="data.sfgov.org",
        dataset_id="i98e-djp9",
        dataset_name="Building Permits",
        date_field="issued_date",
        location_field="location",
    ),
    "los_angeles": PermitSource(
        key="los_angeles",
        city="Los Angeles, CA",
        aliases=("Los Angeles", "Los Angeles, CA", "LA"),
        portal="data.lacity.org",
        dataset_id="pi9x-tg5x",
        dataset_name="Building and Safety - Building Permits",
        date_field="issue_date",
        location_field="geolocation",
    ),
    "seattle": PermitSource(
        key="seattle",
        city="Seattle, WA",
        aliases=("Seattle", "Seattle, WA"),
        portal="data.seattle.gov",
        dataset_id="76t5-zqzr",
        dataset_name="Building Permits",
        date_field="issueddate",
        location_field="location1",
    ),
}


def _token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


_ALIASES = {
    _token(alias): source
    for source in PERMIT_SOURCES.values()
    for alias in (source.key, source.city, *source.aliases)
}


# Socrata schemas contain source-native contact, fee, and administrative fields
# that are not part of this adapter's output contract. Select and normalize only
# the fields required by downstream permit analysis. Unknown upstream additions
# therefore cannot silently become hosted output.
_TEXT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "permit_id": (
        "permit_number",
        "permit_no",
        "permit_id",
        "record_number",
        "record_id",
        "permit_",
        "id",
    ),
    "source_record_id": ("id", "record_id", "record_number"),
    "permit_status": ("permit_status", "status", "current_status"),
    "permit_milestone": ("permit_milestone", "milestone"),
    "permit_type": (
        "permit_type",
        "permit_type_definition",
        "permittypemapped",
        "type",
    ),
    "permit_subtype": (
        "permit_sub_type",
        "permit_subtype",
        "permittypedesc",
        "subtype",
    ),
    "work_class": ("work_class", "workclass"),
    "work_type": ("work_type", "worktype"),
    "description": (
        "work_description",
        "work_desc",
        "description",
        "project_description",
    ),
    "application_date": (
        "application_start_date",
        "application_date",
        "applieddate",
    ),
    "issue_date": ("issue_date", "issued_date", "issueddate", "permit_date"),
    "expiration_date": ("expiration_date", "expiresdate", "expiry_date"),
    "completion_date": (
        "completion_date",
        "completed_date",
        "final_date",
    ),
    "address": (
        "address",
        "site_address",
        "project_address",
        "property_address",
        "full_address",
    ),
    "street_number": ("street_number", "street_no", "housenumber"),
    "street_direction": ("street_direction", "street_dir"),
    "street_name": ("street_name", "streetname"),
    "street_suffix": ("street_suffix", "street_type"),
    "unit": ("unit", "unit_number", "suite"),
    "parcel_id": ("parcel_id", "parcel_number", "apn", "pin", "pin_list"),
    "community_area": ("community_area",),
    "ward": ("ward",),
    "census_tract": ("census_tract",),
}

_REPORTED_COST_FIELDS = (
    "reported_cost",
    "estimated_cost",
    "estimated_value",
    "valuation",
    "job_value",
)
_REPORTED_AREA_FIELDS = (
    "total_new_addition_sqft",
    "new_addition_demo_floor_area",
    "remodel_total_sqft",
    "total_existing_bldg_sqft",
    "building_area",
    "square_feet",
    "floor_area",
    "floor_area_l_a_building_code_definition",
    "projectareasqft",
    "squarefeet",
)


def _text_value(
    row: Mapping[str, Any],
    aliases: tuple[str, ...],
    *,
    max_length: int = 4_000,
) -> str | None:
    for field in aliases:
        value = row.get(field)
        if value is None or isinstance(value, (bool, dict, list, tuple, set)):
            continue
        text = str(value).strip()
        if text:
            return text[:max_length]
    return None


def _nonnegative_number(
    row: Mapping[str, Any], aliases: tuple[str, ...]
) -> float | None:
    for field in aliases:
        value = row.get(field)
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(str(value).replace(",", "").replace("$", ""))
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number >= 0:
            return number
    return None


def _coordinate(row: Mapping[str, Any], axis: str) -> float | None:
    aliases = (
        ("latitude", "lat")
        if axis == "latitude"
        else ("longitude", "lon", "lng")
    )
    value: Any = next(
        (row[field] for field in aliases if row.get(field) not in (None, "")),
        None,
    )
    if value is None:
        for location_field in ("location", "location1", "geolocation"):
            location = row.get(location_field)
            if not isinstance(location, Mapping):
                continue
            direct = location.get(axis)
            if direct not in (None, ""):
                value = direct
                break
            coordinates = location.get("coordinates")
            if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
                value = coordinates[1 if axis == "latitude" else 0]
                break
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    bound = 90 if axis == "latitude" else 180
    return number if math.isfinite(number) and -bound <= number <= bound else None


def _normalize_permit_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {
        field: value
        for field, aliases in _TEXT_FIELD_ALIASES.items()
        if (value := _text_value(row, aliases)) is not None
    }
    if "address" not in normalized:
        address = " ".join(
            part
            for field in (
                "street_number",
                "street_direction",
                "street_name",
                "street_suffix",
                "unit",
            )
            if (part := normalized.get(field))
        )
        if address:
            normalized["address"] = address

    reported_cost = _nonnegative_number(row, _REPORTED_COST_FIELDS)
    if reported_cost is not None:
        normalized["reported_cost"] = reported_cost
    reported_area = _nonnegative_number(row, _REPORTED_AREA_FIELDS)
    if reported_area is not None:
        normalized["reported_area_sf"] = reported_area
    for axis in ("latitude", "longitude"):
        coordinate = _coordinate(row, axis)
        if coordinate is not None:
            normalized[axis] = coordinate
    return normalized


def resolve_permit_source(city: str) -> PermitSource | None:
    if not city or not city.strip():
        return None
    return _ALIASES.get(_token(city))


def _point(lat: float, lon: float) -> tuple[float, float]:
    if isinstance(lat, bool) or isinstance(lon, bool):
        raise ValueError("Latitude and longitude must be numeric")
    try:
        latitude = float(lat)
        longitude = float(lon)
    except (TypeError, ValueError) as exc:
        raise ValueError("Latitude and longitude must be numeric") from exc
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Latitude/longitude are outside WGS84 bounds")
    return latitude, longitude


def build_permit_query(
    lat: float,
    lon: float,
    city: str,
    since_days: int,
    *,
    today: date | datetime | None = None,
) -> tuple[PermitSource, str, str]:
    """Return source, SODA URL, and the query's lower-bound timestamp."""

    latitude, longitude = _point(lat, lon)
    source = resolve_permit_source(city)
    if source is None:
        raise ValueError(f"Unsupported Socrata permit city: {city}")
    if isinstance(since_days, bool) or not isinstance(since_days, int):
        raise ValueError("since_days must be a non-negative integer")
    if since_days < 0:
        raise ValueError("since_days must be a non-negative integer")

    current = today or datetime.now(timezone.utc)
    current_date = current.date() if isinstance(current, datetime) else current
    since_date = current_date - timedelta(days=since_days)
    since_timestamp = f"{since_date.isoformat()}T00:00:00.000"
    where = (
        f"{source.date_field} > '{since_timestamp}' AND "
        f"within_circle({source.location_field}, {latitude}, {longitude}, 500)"
    )
    params = {"$where": where, "$limit": "1000"}
    return source, f"{source.endpoint}?{urlencode(params)}", since_timestamp


def _unsupported(city: str) -> dict[str, Any]:
    return {
        "status": "UNSUPPORTED",
        "city": city,
        "count": 0,
        "permits": [],
        "source_endpoint": None,
        "source_layer": None,
        "discovery_hint": (
            "This adapter supports only the documented Socrata permit cities: "
            "Austin, Chicago, San Francisco, Los Angeles, and Seattle. Search "
            "the city's ArcGIS/Open Data portal for a permit FeatureServer."
        ),
    }


async def permits_near(
    lat: float,
    lon: float,
    city: str,
    since_days: int,
    *,
    fetch: FetchClient | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Fetch permits within 500 metres and the requested lookback window."""

    source = resolve_permit_source(city)
    if source is None:
        return _unsupported(city)
    source, request_url, since_timestamp = build_permit_query(
        lat,
        lon,
        city,
        since_days,
    )
    runtime = current_runtime_config() or config
    require_url(request_url, config=runtime)
    token = (
        runtime.socrata_app_token.get_secret_value().strip()
        if runtime is not None and runtime.socrata_app_token is not None
        else ""
    )
    headers = {"X-App-Token": token} if token else None
    payload = await (fetch or get_fetch_client()).get_json(
        request_url,
        headers=headers,
    )
    if isinstance(payload, dict) and payload.get("error"):
        raise FetchClientError(
            f"Socrata permit query failed for dataset {source.dataset_id}"
        )
    if not isinstance(payload, list):
        raise FetchClientError(
            f"Socrata permit response for {source.dataset_id} must be a JSON list"
        )
    permits = [
        _normalize_permit_row(row)
        for row in payload
        if isinstance(row, Mapping)
    ]
    return {
        "status": "OK",
        "source": f"permits.{source.key}",
        "city": source.city,
        "count": len(permits),
        "permits": permits,
        "since": since_timestamp,
        "radius_m": 500,
        "source_endpoint": source.endpoint,
        "source_layer": f"{source.dataset_name} ({source.dataset_id})",
        "dataset_id": source.dataset_id,
        "request_url": request_url,
        "app_token_used": bool(token),
    }


__all__ = [
    "PERMIT_SOURCES",
    "PermitSource",
    "build_permit_query",
    "permits_near",
    "resolve_permit_source",
]
