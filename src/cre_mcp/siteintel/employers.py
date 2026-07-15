"""State WARN-notice adapters with explicit feed provenance."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlencode

from cre_mcp.http.fetch import FetchClient, get_fetch_client


TX_WARN_SOURCE_URL = "https://data.texas.gov/resource/8w53-c4f6.json"
TX_WARN_DATASET_URL = "https://data.texas.gov/api/views/8w53-c4f6"
CA_WARN_LANDING_URL = (
    "https://edd.ca.gov/en/jobs_and_training/layoff_services_warn"
)
CA_WARN_SOURCE_URL = (
    "https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx"
)


def _as_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("since must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("since must be an ISO date (YYYY-MM-DD)") from exc


def _row_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def parse_tx_warn_rows(
    payload: Any,
    since: str | date | datetime,
) -> list[dict[str, Any]]:
    """Normalize rows from TWC's official Socrata WARN dataset."""

    since_date = _as_date(since)
    if not isinstance(payload, list):
        raise ValueError("Texas WARN response must be a JSON list")
    events: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        notice_date = _row_date(row.get("notice_date"))
        if notice_date is None or notice_date < since_date:
            continue
        employer = str(row.get("job_site_name") or "").strip()
        effective = _row_date(row.get("layoff_date"))
        if not employer or effective is None:
            continue
        city = str(row.get("city_name") or "").strip()
        county = str(row.get("county_name") or "").strip()
        location_parts = [part for part in (city, county and f"{county} County", "TX") if part]
        events.append(
            {
                "employer": employer,
                "location": ", ".join(location_parts),
                "affected": _integer(row.get("total_layoff_number")),
                "effective_date": effective.isoformat(),
                "source_url": TX_WARN_SOURCE_URL,
            }
        )
    events.sort(key=lambda item: (item["effective_date"], item["employer"]))
    return events


def _tx_request_url(since_date: date) -> str:
    select = ",".join(
        (
            "notice_date",
            "job_site_name",
            "county_name",
            "total_layoff_number",
            "layoff_date",
            "city_name",
        )
    )
    where = f"notice_date >= '{since_date.isoformat()}T00:00:00.000'"
    return f"{TX_WARN_SOURCE_URL}?{urlencode({'$select': select, '$where': where, '$order': 'notice_date DESC', '$limit': '5000'})}"


async def employer_events(
    state: str,
    since: str | date | datetime | None = None,
    *,
    fetch: FetchClient | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Fetch normalized WARN events.

    ``since`` applies to the notice date, while ``effective_date`` in each event
    is the reported layoff/closure effective date.
    """

    if not isinstance(state, str) or not state.strip():
        return {"error": "state must be a non-empty string"}
    retrieved_date = today or datetime.now(timezone.utc).date()
    try:
        since_date = (
            retrieved_date.replace(month=1, day=1)
            if since is None
            else _as_date(since)
        )
    except ValueError as exc:
        return {"error": str(exc)}
    token = state.strip().casefold()
    if token in {"ca", "california"}:
        return {
            "status": "UNSUPPORTED",
            "state": "CA",
            "since": since_date.isoformat(),
            "count": 0,
            "events": [],
            "source_url": CA_WARN_SOURCE_URL,
            "landing_url": CA_WARN_LANDING_URL,
            "source_format": "XLSX",
            "source_retrieved_date": retrieved_date.isoformat(),
            "reason": (
                "California EDD currently publishes the row-level report as XLSX; "
                "the shared FetchClient has no binary response API, so live parsing "
                "is not represented as supported"
            ),
        }
    if token not in {"tx", "texas"}:
        return {
            "status": "UNSUPPORTED",
            "state": state.strip().upper(),
            "since": since_date.isoformat(),
            "count": 0,
            "events": [],
            "reason": "Supported WARN adapters: TX; CA is documented but live-unsupported",
        }

    request_url = _tx_request_url(since_date)
    try:
        payload = await (fetch or get_fetch_client()).get_json(request_url)
        if isinstance(payload, dict) and payload.get("error"):
            return {"error": f"Texas WARN feed failed: {payload['error']}"}
        events = parse_tx_warn_rows(payload, since_date)
    except Exception as exc:
        return {"error": f"Texas WARN feed failed: {exc}"}
    return {
        "status": "OK",
        "state": "TX",
        "since": since_date.isoformat(),
        "count": len(events),
        "events": events,
        "source_url": TX_WARN_SOURCE_URL,
        "dataset_url": TX_WARN_DATASET_URL,
        "request_url": request_url,
        "source_retrieved_date": retrieved_date.isoformat(),
        "since_convention": (
            "omitted since defaults to the start of the current calendar year; "
            "since filters notice_date, not effective_date"
            if since is None
            else "since filters notice_date, not effective_date"
        ),
    }


__all__ = [
    "CA_WARN_LANDING_URL",
    "CA_WARN_SOURCE_URL",
    "TX_WARN_DATASET_URL",
    "TX_WARN_SOURCE_URL",
    "employer_events",
    "parse_tx_warn_rows",
]
