"""EPA federal radius searches for pre-Phase-I environmental screening."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlencode

from cre_mcp.http.fetch import FetchClient, get_fetch_client

FRS_URL = (
    "https://frs-public.epa.gov/ords/frs_public2/"
    "frs_rest_services.get_facilities"
)
ECHO_SEARCH_URL = (
    "https://echodata.epa.gov/echo/echo_rest_services.get_facilities"
)
ECHO_QID_URL = "https://echodata.epa.gov/echo/echo_rest_services.get_qid"

FRS_PROGRAMS = ("SEMS", "RCRAINFO", "TRIS", "ACRES", "NPDES")
DRY_CLEANER_NAICS = frozenset({"812310", "812320"})

FRS_SOURCE = {
    "name": "EPA FRS REST",
    "url": "https://www.epa.gov/frs/frs-rest-services",
    "endpoint": FRS_URL,
    "auth": "None",
    "reliability": "A",
}
ECHO_SOURCE = {
    "name": "EPA ECHO",
    "url": "https://echo.epa.gov/tools/web-services",
    "endpoint": ECHO_SEARCH_URL,
    "auth": "None",
    "reliability": "A",
}


def _validate_point(lat: float, lon: float) -> tuple[float, float]:
    latitude = float(lat)
    longitude = float(lon)
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("latitude must be finite and between -90 and 90")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("longitude must be finite and between -180 and 180")
    return latitude, longitude


def _validate_radius(radius_mi: float, *, maximum: float) -> float:
    radius = float(radius_mi)
    if not math.isfinite(radius) or radius <= 0 or radius > maximum:
        raise ValueError(f"radius_mi must be greater than 0 and at most {maximum:g}")
    return radius


def _get(row: Mapping[str, Any], *names: str) -> Any:
    folded = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        if name.casefold() in folded:
            return folded[name.casefold()]
    return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().casefold()
    if text in {"y", "yes", "true", "t", "1", "on", "current", "violation"}:
        return True
    if text in {"n", "no", "false", "f", "0", "off", "none"}:
        return False
    number = _as_float(value)
    return number > 0 if number is not None else None


def _codes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        values: Iterable[Any] = value.values()
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = value
    else:
        values = str(value).replace(",", " ").replace(";", " ").split()
    codes: set[str] = set()
    for item in values:
        if isinstance(item, Mapping):
            item = _get(item, "naics_code", "code", "NAICS")
        if item not in (None, ""):
            codes.add(str(item).strip())
    return sorted(codes)


def distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in statute miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    hav = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 3958.7613 * 2 * math.atan2(math.sqrt(hav), math.sqrt(1 - hav))


def _results_object(payload: Any, *, source: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{source} response must be a JSON object")
    results = _get(payload, "Results")
    if not isinstance(results, Mapping):
        results = payload
    error = _get(results, "Error", "error")
    if error:
        if isinstance(error, Mapping):
            message = _get(error, "ErrorMessage", "message") or str(error)
        else:
            message = str(error)
        raise ValueError(f"{source} query failed: {message}")
    return results


def _facility_rows(results: Mapping[str, Any], *names: str) -> list[Mapping[str, Any]]:
    rows = _get(results, *names)
    if rows is None:
        return []
    if isinstance(rows, Mapping):
        rows = [rows]
    if not isinstance(rows, list):
        raise ValueError("facility collection must be a list")
    return [row for row in rows if isinstance(row, Mapping)]


def normalize_frs_payload(
    payload: Any,
    *,
    lat: float,
    lon: float,
    program: str,
) -> list[dict[str, Any]]:
    """Normalize an FRS response into citation-ready facility hits."""
    latitude, longitude = _validate_point(lat, lon)
    results = _results_object(payload, source="EPA FRS REST")
    facilities = _facility_rows(results, "FRSFacility", "Facilities", "facilities")
    hits: list[dict[str, Any]] = []
    for row in facilities:
        facility_lat = _as_float(_get(row, "Latitude83", "latitude83", "latitude"))
        facility_lon = _as_float(_get(row, "Longitude83", "longitude83", "longitude"))
        if facility_lat is None or facility_lon is None:
            continue
        naics = _codes(
            _get(row, "NAICSCodes", "naics_codes", "NAICS_CODE", "naics")
        )
        interest_types = _get(row, "InterestTypes", "interest_types")
        corrective_raw = _get(
            row,
            "CorrectiveActionFlag",
            "corrective_action",
            "RCRACorrectiveAction",
        )
        corrective_action = _as_bool(corrective_raw)
        if corrective_action is None and interest_types:
            text = str(interest_types).casefold()
            if "corrective action" in text:
                corrective_action = True
        distance = distance_miles(latitude, longitude, facility_lat, facility_lon)
        hits.append(
            {
                "name": str(
                    _get(row, "FacilityName", "primary_name", "name")
                    or "Unnamed EPA facility"
                ),
                "program": program.upper(),
                "distance_mi": round(distance, 4),
                "registry_id": (
                    str(_get(row, "RegistryId", "registry_id") or "") or None
                ),
                "flags": {
                    "naics_codes": naics,
                    "dry_cleaner_naics": bool(DRY_CLEANER_NAICS.intersection(naics)),
                    "corrective_action": corrective_action,
                    "active_status": _get(row, "ActiveStatus", "active_status"),
                    "interest_types": interest_types,
                },
                "source": FRS_SOURCE["name"],
                "source_url": FRS_SOURCE["url"],
                "coordinates": {"lat": facility_lat, "lon": facility_lon},
            }
        )
    return hits


def _echo_programs(row: Mapping[str, Any]) -> list[str]:
    programs: set[str] = set()
    if _get(row, "AIRIds") or _as_bool(_get(row, "AIRFlag")):
        programs.add("ICIS-AIR")
    if _get(row, "NPDESIds") or _get(row, "CWAComplianceStatus") is not None:
        programs.add("NPDES")
    if _get(row, "RCRAIds") or _get(row, "RCRAComplianceStatus") is not None:
        programs.add("RCRAINFO")
    if _get(row, "TRIIds") or _as_bool(_get(row, "TRIFlag")):
        programs.add("TRIS")
    if _get(row, "SDWAIds") or _get(row, "SDWAComplianceStatus") is not None:
        programs.add("SDWIS")
    return sorted(programs)


def normalize_echo_payload(
    payload: Any,
    *,
    lat: float,
    lon: float,
    radius_mi: float,
) -> list[dict[str, Any]]:
    """Normalize ECHO QID facilities, retaining unknowns rather than clearing them."""
    latitude, longitude = _validate_point(lat, lon)
    radius = _validate_radius(radius_mi, maximum=20)
    results = _results_object(payload, source="EPA ECHO")
    facilities = _facility_rows(results, "Facilities", "facilities")
    hits: list[dict[str, Any]] = []
    for row in facilities:
        facility_lat = _as_float(_get(row, "FacLat", "latitude"))
        facility_lon = _as_float(_get(row, "FacLong", "FacLon", "longitude"))
        exact_distance = facility_lat is not None and facility_lon is not None
        distance = (
            distance_miles(latitude, longitude, facility_lat, facility_lon)
            if exact_distance
            else radius
        )
        programs = _echo_programs(row)
        naics = _codes(_get(row, "FacNAICSCodes", "NAICSCodes", "naics_codes"))
        current_violation = _as_bool(
            _get(row, "CurrVioFlag", "FacSNCFlg", "current_violation")
        )
        inspections = _as_int(
            _get(row, "Insp5yr", "FacInspectionCount", "inspections_5yr")
        )
        enforcement = _as_bool(_get(row, "Fea5yr", "formal_enforcement_5yr"))
        hits.append(
            {
                "name": str(_get(row, "FacName", "FacilityName", "name") or "Unnamed ECHO facility"),
                "program": programs[0] if len(programs) == 1 else "ECHO",
                "distance_mi": round(distance, 4),
                "registry_id": str(_get(row, "RegistryID", "registry_id") or "") or None,
                "flags": {
                    "programs": programs,
                    "current_violation": current_violation,
                    "inspections_5yr": inspections,
                    "formal_enforcement_5yr": enforcement,
                    "quarters_noncompliance": _as_int(
                        _get(row, "QtrsWithNC", "FacQtrsWithNC")
                    ),
                    "penalties": _get(row, "Penalties", "CAAPenalties"),
                    "naics_codes": naics,
                    "dry_cleaner_naics": bool(DRY_CLEANER_NAICS.intersection(naics)),
                    "distance_is_upper_bound": not exact_distance,
                },
                "source": ECHO_SOURCE["name"],
                "source_url": ECHO_SOURCE["url"],
                "coordinates": (
                    {"lat": facility_lat, "lon": facility_lon}
                    if exact_distance
                    else None
                ),
            }
        )
    return hits


def _source_result(
    *,
    source: Mapping[str, str],
    query_id: str,
    url: str,
    hits: list[dict[str, Any]] | None = None,
    error: Exception | str | None = None,
) -> dict[str, Any]:
    if error is not None:
        return {
            "source": source["name"],
            "query_id": query_id,
            "status": "query_failed",
            "hits": [],
            "query_url": url,
            "error": str(error),
        }
    normalized = hits or []
    return {
        "source": source["name"],
        "query_id": query_id,
        "status": "hit" if normalized else "null",
        "hits": normalized,
        "query_url": url,
        "error": None,
    }


async def frs_radius(
    lat: float,
    lon: float,
    radius_mi: float,
    program: str,
    *,
    fetch: FetchClient | None = None,
) -> dict[str, Any]:
    """Query one supported FRS program within at most five miles."""
    latitude, longitude = _validate_point(lat, lon)
    radius = _validate_radius(radius_mi, maximum=5)
    acronym = str(program).upper()
    if acronym not in FRS_PROGRAMS:
        raise ValueError(f"program must be one of {', '.join(FRS_PROGRAMS)}")
    params = {
        "latitude83": f"{latitude:g}",
        "longitude83": f"{longitude:g}",
        "search_radius": f"{radius:g}",
        "pgm_sys_acrnm": acronym,
        "output": "JSON",
    }
    url = f"{FRS_URL}?{urlencode(params)}"
    query_id = f"epa_frs_rest:{acronym}:{radius:g}mi"
    try:
        payload = await (fetch or get_fetch_client()).get_json(url)
        hits = normalize_frs_payload(
            payload, lat=latitude, lon=longitude, program=acronym
        )
        return _source_result(
            source=FRS_SOURCE, query_id=query_id, url=url, hits=hits
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return _source_result(
            source=FRS_SOURCE, query_id=query_id, url=url, error=exc
        )


async def frs_sweep(
    lat: float,
    lon: float,
    radius_mi: float,
    *,
    programs: Iterable[str] = FRS_PROGRAMS,
    fetch: FetchClient | None = None,
) -> list[dict[str, Any]]:
    """Query all requested FRS program acronyms concurrently."""
    return list(
        await asyncio.gather(
            *(
                frs_radius(lat, lon, radius_mi, program, fetch=fetch)
                for program in programs
            )
        )
    )


async def echo_radius(
    lat: float,
    lon: float,
    radius_mi: float,
    *,
    fetch: FetchClient | None = None,
) -> dict[str, Any]:
    """Run an ECHO radius search and resolve its short-lived QID result page(s)."""
    latitude, longitude = _validate_point(lat, lon)
    radius = _validate_radius(radius_mi, maximum=20)
    # p_sr is the documented parameter. ECHO currently also requires p_radius;
    # sending both preserves compatibility without weakening the documented query.
    params = {
        "output": "JSON",
        "p_lat": f"{latitude:g}",
        "p_long": f"{longitude:g}",
        "p_sr": f"{radius:g}",
        "p_radius": f"{radius:g}",
    }
    url = f"{ECHO_SEARCH_URL}?{urlencode(params)}"
    query_id = f"epa_echo:{radius:g}mi"
    client = fetch or get_fetch_client()
    try:
        search_payload = await client.get_json(url)
        results = _results_object(search_payload, source="EPA ECHO")
        direct = _facility_rows(results, "Facilities", "facilities")
        query_rows = _as_int(_get(results, "QueryRows"))
        qid = _get(results, "QueryID", "QID")
        if direct:
            detail_payload: Any = {"Results": {"Facilities": direct}}
        elif not qid or query_rows == 0:
            detail_payload = {"Results": {"Facilities": []}}
        else:
            all_facilities: list[Mapping[str, Any]] = []
            page = 1
            while page <= 100:
                page_url = f"{ECHO_QID_URL}?{urlencode({'output': 'JSON', 'qid': qid, 'pageno': page})}"
                page_payload = await client.get_json(page_url)
                page_results = _results_object(page_payload, source="EPA ECHO")
                rows = _facility_rows(page_results, "Facilities", "facilities")
                if not rows:
                    break
                all_facilities.extend(rows)
                if query_rows is None or len(all_facilities) >= query_rows:
                    break
                page += 1
            detail_payload = {"Results": {"Facilities": all_facilities}}
        hits = normalize_echo_payload(
            detail_payload,
            lat=latitude,
            lon=longitude,
            radius_mi=radius,
        )
        return _source_result(
            source=ECHO_SOURCE, query_id=query_id, url=url, hits=hits
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return _source_result(
            source=ECHO_SOURCE, query_id=query_id, url=url, error=exc
        )


__all__ = [
    "DRY_CLEANER_NAICS",
    "ECHO_SOURCE",
    "FRS_PROGRAMS",
    "FRS_SOURCE",
    "distance_miles",
    "echo_radius",
    "frs_radius",
    "frs_sweep",
    "normalize_echo_payload",
    "normalize_frs_payload",
]
