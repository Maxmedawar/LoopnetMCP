"""Candidate searches for FINRA BrokerCheck and SEC IAPD.

Both services are undocumented public JSON APIs.  Callers must treat failures as
unknown/error states, never as proof that a person or firm is not registered.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal
from urllib.parse import urlencode

from cre_mcp.http.fetch import FetchClient, get_fetch_client

BROKERCHECK_API = "https://api.brokercheck.finra.org/search"
IAPD_API = "https://api.adviserinfo.sec.gov/search"
BROKERCHECK_SITE = "https://brokercheck.finra.org"
IAPD_SITE = "https://adviserinfo.sec.gov"

UNDOCUMENTED_API_NOTE = (
    "This is an undocumented public JSON API and may change or require "
    "authentication without notice. Failures are closed as errors, not treated "
    "as no matches."
)

EntityType = Literal["individual", "firm"]


class RegistryAPIError(RuntimeError):
    """An undocumented registry API could not be safely interpreted."""


def _search_url(base: str, entity_type: EntityType, name: str, state: str | None) -> str:
    if not name.strip():
        raise ValueError("Registry search requires a non-empty name or CRD")
    params = {
        "hl": "true",
        "includePrevious": "true",
        "nrows": 12,
        "query": name.strip(),
        "r": 25,
        "sort": "score desc",
        "wt": "json",
    }
    if state:
        params["state"] = state.strip().upper()
    return f"{base}/{entity_type}?{urlencode(params)}"


def _hits(payload: Any, source: str) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise RegistryAPIError(
            f"{source} schema drift: expected a JSON object. {UNDOCUMENTED_API_NOTE}"
        )
    if payload.get("errorCode") not in (None, 0, "0"):
        message = payload.get("errorMessage") or "unknown registry error"
        raise RegistryAPIError(
            f"{source} returned an error: {message}. {UNDOCUMENTED_API_NOTE}"
        )
    hits_wrapper = payload.get("hits")
    if not isinstance(hits_wrapper, Mapping):
        raise RegistryAPIError(
            f"{source} schema drift: missing hits object. {UNDOCUMENTED_API_NOTE}"
        )
    records = hits_wrapper.get("hits")
    if not isinstance(records, list):
        raise RegistryAPIError(
            f"{source} schema drift: hits.hits is not a list. "
            f"{UNDOCUMENTED_API_NOTE}"
        )
    for record in records:
        if not isinstance(record, Mapping) or not isinstance(record.get("_source"), Mapping):
            raise RegistryAPIError(
                f"{source} schema drift: a hit has no _source object. "
                f"{UNDOCUMENTED_API_NOTE}"
            )
    return records


def _first(source: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, "", []):
            return value
    return None


def _full_name(source: Mapping[str, Any]) -> str | None:
    parts = [
        source.get("ind_firstname"),
        source.get("ind_middlename"),
        source.get("ind_lastname"),
        source.get("ind_namesuffix"),
    ]
    name = " ".join(str(part).strip() for part in parts if part not in (None, ""))
    return name or None


def _current_firm(source: Mapping[str, Any], *, adviser: bool = False) -> str | None:
    keys = (
        ("ind_ia_current_employments", "ind_current_employments")
        if adviser
        else ("ind_current_employments", "ind_ia_current_employments")
    )
    employments = _first(source, keys)
    if isinstance(employments, list):
        for employment in employments:
            if isinstance(employment, Mapping) and employment.get("firm_name"):
                return str(employment["firm_name"])
    return None


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, Mapping):
                candidate = _first(
                    item,
                    ("exam", "exam_name", "state", "state_code", "registration"),
                )
                if candidate not in (None, ""):
                    result.append(str(candidate).strip())
        return result
    return [str(value).strip()]


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _broker_candidate(hit: Mapping[str, Any], entity_type: EntityType) -> dict[str, Any]:
    source = hit["_source"]
    prefix = "ind" if entity_type == "individual" else "firm"
    crd = _first(source, (f"{prefix}_source_id", f"{prefix}_crd", "crd"))
    firm_name = _first(source, ("firm_name", "org_name"))
    name = _full_name(source) if entity_type == "individual" else firm_name
    if crd in (None, "") or name in (None, ""):
        raise RegistryAPIError(
            "FINRA BrokerCheck schema drift: hit lacks CRD/name. "
            f"{UNDOCUMENTED_API_NOTE}"
        )
    if entity_type == "individual":
        firm_name = _current_firm(source)

    disclosure_count = _optional_int(
        _first(
            source,
            (
                f"{prefix}_bc_disclosure_count",
                f"{prefix}_disclosure_count",
                "disclosure_count",
            ),
        )
    )
    disclosure_flag = _first(
        source,
        (f"{prefix}_bc_disclosure_fl", f"{prefix}_disclosure_fl"),
    )
    if disclosure_count is None and str(disclosure_flag).upper() == "N":
        disclosure_count = 0

    candidate: dict[str, Any] = {
        "crd": str(crd),
        "name": str(name),
        "firm": str(firm_name) if firm_name not in (None, "") else None,
        "exams": _string_list(
            _first(source, (f"{prefix}_exams", f"{prefix}_approved_exams", "exams"))
        ),
        "states": _string_list(
            _first(
                source,
                (
                    f"{prefix}_registered_states",
                    f"{prefix}_state_registrations",
                    "states",
                ),
            )
        ),
        "disclosure_count": disclosure_count,
        "bc_url": f"{BROKERCHECK_SITE}/{entity_type}/summary/{crd}",
    }
    if disclosure_flag not in (None, ""):
        candidate["disclosure_flag"] = str(disclosure_flag).upper()
    return candidate


def _iapd_candidate(hit: Mapping[str, Any], entity_type: EntityType) -> dict[str, Any]:
    source = hit["_source"]
    prefix = "ind" if entity_type == "individual" else "firm"
    crd = _first(source, (f"{prefix}_source_id", f"{prefix}_crd", "crd"))
    firm_name = _first(source, ("firm_name", "org_name"))
    if entity_type == "individual":
        firm_name = _current_firm(source, adviser=True)
    if crd in (None, ""):
        raise RegistryAPIError(
            f"SEC IAPD schema drift: hit lacks CRD. {UNDOCUMENTED_API_NOTE}"
        )
    return {
        "crd": str(crd),
        "firm": str(firm_name) if firm_name not in (None, "") else None,
        "iapd_url": f"{IAPD_SITE}/{entity_type}/summary/{crd}",
    }


async def _search(
    *,
    base: str,
    source_name: str,
    name: str,
    state: str | None,
    entity_type: EntityType,
    client: FetchClient | None,
    parser: Any,
) -> list[dict[str, Any]]:
    url = _search_url(base, entity_type, name, state)
    try:
        payload = await (client or get_fetch_client()).get_json(url)
        return [parser(hit, entity_type) for hit in _hits(payload, source_name)]
    except RegistryAPIError:
        raise
    except Exception as exc:
        raise RegistryAPIError(
            f"{source_name} request failed closed: {exc}. {UNDOCUMENTED_API_NOTE}"
        ) from exc


async def search_brokercheck_individuals(
    name: str, state: str | None = None, *, client: FetchClient | None = None
) -> list[dict[str, Any]]:
    """Return possible individual matches; this does not verify identity."""
    return await _search(
        base=BROKERCHECK_API,
        source_name="FINRA BrokerCheck",
        name=name,
        state=state,
        entity_type="individual",
        client=client,
        parser=_broker_candidate,
    )


async def search_brokercheck_firms(
    name: str, state: str | None = None, *, client: FetchClient | None = None
) -> list[dict[str, Any]]:
    """Return possible firm matches; this does not verify identity."""
    return await _search(
        base=BROKERCHECK_API,
        source_name="FINRA BrokerCheck",
        name=name,
        state=state,
        entity_type="firm",
        client=client,
        parser=_broker_candidate,
    )


async def search_iapd_individuals(
    name: str, state: str | None = None, *, client: FetchClient | None = None
) -> list[dict[str, Any]]:
    """Return possible IAPD individual matches; this does not verify identity."""
    return await _search(
        base=IAPD_API,
        source_name="SEC IAPD",
        name=name,
        state=state,
        entity_type="individual",
        client=client,
        parser=_iapd_candidate,
    )


async def search_iapd_firms(
    name: str, state: str | None = None, *, client: FetchClient | None = None
) -> list[dict[str, Any]]:
    """Return possible IAPD firm matches; this does not verify identity."""
    return await _search(
        base=IAPD_API,
        source_name="SEC IAPD",
        name=name,
        state=state,
        entity_type="firm",
        client=client,
        parser=_iapd_candidate,
    )


__all__ = [
    "RegistryAPIError",
    "UNDOCUMENTED_API_NOTE",
    "search_brokercheck_firms",
    "search_brokercheck_individuals",
    "search_iapd_firms",
    "search_iapd_individuals",
]
