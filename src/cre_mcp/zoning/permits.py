"""Nearby building-permit lookups for the documented Socrata cities."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from cre_mcp.http.errors import FetchClientError
from cre_mcp.http.fetch import FetchClient, get_fetch_client


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
    token = os.getenv("CRE_SOCRATA_APP_TOKEN", "").strip()
    headers = {"X-App-Token": token} if token else None
    payload = await (fetch or get_fetch_client()).get_json(
        request_url,
        headers=headers,
    )
    if isinstance(payload, dict) and payload.get("error"):
        raise FetchClientError(
            f"Socrata permit query failed for {source.dataset_id}: {payload}"
        )
    if not isinstance(payload, list):
        raise FetchClientError(
            f"Socrata permit response for {source.dataset_id} must be a JSON list"
        )
    permits = [row for row in payload if isinstance(row, dict)]
    return {
        "status": "OK",
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
