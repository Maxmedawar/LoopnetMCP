"""V1 state-board integrations limited to genuine Socrata APIs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from cre_mcp.http.fetch import FetchClient, get_fetch_client

CO_REAL_ESTATE_API = "https://data.colorado.gov/resource/4zse-6bnw.json"
CO_ALL_PROFESSIONS_API = "https://data.colorado.gov/resource/7s5z-vewr.json"
TX_TDLR_API = "https://data.texas.gov/resource/7358-krk7.json"


class StateBoardError(RuntimeError):
    """A state-board API failed or returned an unsafe-to-interpret schema."""


def _soql_literal(value: str) -> str:
    return value.strip().upper().replace("'", "''")


def _co_name_where(name: str) -> str:
    tokens = [token for token in _soql_literal(name).replace(",", " ").split() if token]
    if not tokens:
        raise ValueError("Name filter cannot be empty")
    if len(tokens) == 1:
        token = tokens[0]
        return (
            f"(upper(firstname) like '%{token}%' or "
            f"upper(lastname) like '%{token}%')"
        )
    return (
        f"(upper(firstname) like '%{tokens[0]}%' and "
        f"upper(lastname) like '%{tokens[-1]}%')"
    )


def _tdlr_name_where(name: str) -> str:
    value = _soql_literal(name)
    if not value:
        raise ValueError("Name filter cannot be empty")
    return (
        f"(upper(business_name) like '%{value}%' or "
        f"upper(owner_name) like '%{value}%')"
    )


def _search_url(
    base: str,
    *,
    name: str | None,
    license_no: str | None,
    name_where: Any,
    license_field: str,
    limit: int,
) -> str:
    if not name and not license_no:
        raise ValueError("State-board search requires a name or license number")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    conditions: list[str] = []
    if name:
        conditions.append(name_where(name))
    if license_no:
        conditions.append(
            f"{license_field}='{_soql_literal(str(license_no))}'"
        )
    params: dict[str, Any] = {"$limit": limit}
    if conditions:
        params["$where"] = " and ".join(conditions)
    return f"{base}?{urlencode(params)}"


def _first(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _person_name(record: Mapping[str, Any]) -> str | None:
    parts = [
        _first(record, "firstname", "first_name"),
        _first(record, "middlename", "middle_name"),
        _first(record, "lastname", "last_name"),
    ]
    value = " ".join(str(part).strip() for part in parts if part not in (None, ""))
    return value or None


def _normalize(record: Mapping[str, Any], source: str) -> dict[str, Any]:
    license_no = _first(
        record,
        "licensenumber",
        "license_number",
        "license_no",
        "credential_number",
    )
    license_type = _first(
        record,
        "licensetype",
        "license_type",
        "license_subtype",
        "credential_type",
    )
    if license_no in (None, "") or license_type in (None, ""):
        raise StateBoardError(
            f"{source} schema drift: record lacks license number/type; failed closed"
        )
    name = _first(record, "business_name", "owner_name", "licensee_name", "full_name")
    if name in (None, ""):
        name = _person_name(record)
    return {
        "license_no": str(license_no),
        "type": str(license_type),
        "status": _first(record, "licensestatus", "license_status", "status"),
        "expiry": _first(
            record,
            "licenseexpirationdate",
            "license_expiration_date_mmddccyy",
            "license_expiration_date",
            "expiration_date",
        ),
        "source": source,
        "name": str(name) if name not in (None, "") else None,
    }


async def _query(
    url: str, source: str, client: FetchClient | None
) -> list[dict[str, Any]]:
    try:
        payload = await (client or get_fetch_client()).get_json(url)
    except Exception as exc:
        raise StateBoardError(f"{source} request failed closed: {exc}") from exc
    if not isinstance(payload, list):
        raise StateBoardError(
            f"{source} schema drift: expected a JSON list; failed closed"
        )
    candidates: list[dict[str, Any]] = []
    for record in payload:
        if not isinstance(record, Mapping):
            raise StateBoardError(
                f"{source} schema drift: non-object record; failed closed"
            )
        candidates.append(_normalize(record, source))
    return candidates


async def search_co_real_estate(
    name: str | None = None,
    license_no: str | None = None,
    *,
    limit: int = 25,
    client: FetchClient | None = None,
) -> list[dict[str, Any]]:
    """Search Colorado's licensed-real-estate-professionals dataset."""
    url = _search_url(
        CO_REAL_ESTATE_API,
        name=name,
        license_no=license_no,
        name_where=_co_name_where,
        license_field="licensenumber",
        limit=limit,
    )
    return await _query(url, "CO DORA 4zse-6bnw", client)


async def search_co_all_professions(
    name: str | None = None,
    license_no: str | None = None,
    *,
    limit: int = 25,
    client: FetchClient | None = None,
) -> list[dict[str, Any]]:
    """Search Colorado's all-professions DORA dataset."""
    url = _search_url(
        CO_ALL_PROFESSIONS_API,
        name=name,
        license_no=license_no,
        name_where=_co_name_where,
        license_field="licensenumber",
        limit=limit,
    )
    return await _query(url, "CO DORA 7s5z-vewr", client)


async def search_tx_tdlr(
    name: str | None = None,
    license_no: str | None = None,
    *,
    limit: int = 25,
    client: FetchClient | None = None,
) -> list[dict[str, Any]]:
    """Search Texas TDLR's all-licenses dataset (trades, not general contractors)."""
    url = _search_url(
        TX_TDLR_API,
        name=name,
        license_no=license_no,
        name_where=_tdlr_name_where,
        license_field="license_number",
        limit=limit,
    )
    return await _query(url, "TX TDLR 7358-krk7", client)


def tx_trec_link_out() -> dict[str, Any]:
    """Describe the honest V1 fallback for TREC's flat high-value files."""
    return {
        "status": "not_queryable",
        "candidates": [],
        "deep_link": "https://www.trec.texas.gov/apps/license-holder-search/",
        "documentation_url": "https://www.trec.texas.gov/public/high-value-data-sets",
        "note": (
            "V1 does not pretend TREC's high-value flat downloads are a stable "
            "single-record JSON API; use the official lookup and dataset documentation."
        ),
    }


__all__ = [
    "StateBoardError",
    "search_co_all_professions",
    "search_co_real_estate",
    "search_tx_tdlr",
    "tx_trec_link_out",
]
