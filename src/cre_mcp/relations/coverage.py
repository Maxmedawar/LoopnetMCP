"""Recorded sourcing coverage and lightweight mandate routing."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig


SEARCH_EVENT_TYPES = frozenset(
    {"search", "searched", "sourced", "discovered", "listing_found", "listing_discovered"}
)
SCREEN_EVENT_TYPES = frozenset(
    {"screen", "screened", "reviewed", "analyzed", "analysed", "underwritten"}
)
REJECT_EVENT_TYPES = frozenset(
    {"reject", "rejected", "passed", "deal_passed", "screen_rejected"}
)
ADVANCE_EVENT_TYPES = frozenset(
    {"advance", "advanced", "contacted", "loi", "under_contract", "diligence"}
)
UNTOUCHED_NOTE = (
    "Untouched inventory is the non-negative difference between recorded searched "
    "inventory and recorded screening events. It is an instrumentation queue, not "
    "proof that a listing received no offline review."
)


def _db_path(
    db_path: str | Path | CreConfig | None,
    config: CreConfig | None,
) -> Path:
    if isinstance(db_path, CreConfig):
        return db_path.cache_db_path.expanduser()
    if db_path is not None:
        return Path(db_path).expanduser()
    return (config or CreConfig()).cache_db_path.expanduser()


def _as_utc(value: Any = None, *, label: str) -> datetime:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            raise ValueError(f"{label} cannot be blank")
        if text_value.endswith("Z"):
            text_value = f"{text_value[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text_value)
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO date or datetime") from exc
    else:
        raise ValueError(f"{label} must be a date, datetime, ISO string, or omitted")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _period_window(period: Any, as_of: datetime) -> tuple[datetime, datetime, str]:
    if isinstance(period, bool):
        raise ValueError("period must be a positive day count, named period, or date range")
    if isinstance(period, int):
        if period <= 0:
            raise ValueError("period day count must be positive")
        return as_of - timedelta(days=period), as_of, f"trailing_{period}_days"
    if isinstance(period, Mapping):
        start_value = period.get("start", period.get("from"))
        end_value = period.get("end", period.get("to", as_of))
        if start_value is None:
            raise ValueError("period mapping must provide start or from")
        start = _as_utc(start_value, label="period.start")
        end = _as_utc(end_value, label="period.end")
        if end < start:
            raise ValueError("period end must not precede period start")
        return start, end, "custom"
    if not isinstance(period, str):
        raise ValueError("period must be a positive day count, named period, or date range")
    text_value = period.strip().casefold()
    if not text_value:
        raise ValueError("period cannot be blank")
    named_days = {
        "day": 1,
        "daily": 1,
        "today": 1,
        "week": 7,
        "weekly": 7,
        "month": 30,
        "monthly": 30,
        "quarter": 90,
        "quarterly": 90,
    }
    if text_value in {"day", "daily", "today"}:
        start = datetime.combine(as_of.date(), time.min, tzinfo=UTC)
        return start, as_of, "calendar_day"
    if text_value in named_days:
        days = named_days[text_value]
        return as_of - timedelta(days=days), as_of, f"trailing_{days}_days"
    day_match = re.fullmatch(r"(\d+)\s*d(?:ays?)?", text_value)
    if day_match is not None:
        days = int(day_match.group(1))
        if days <= 0:
            raise ValueError("period day count must be positive")
        return as_of - timedelta(days=days), as_of, f"trailing_{days}_days"
    if "/" in text_value:
        start_text, end_text = text_value.split("/", 1)
        start = _as_utc(start_text, label="period start")
        end = _as_utc(end_text, label="period end")
        if end < start:
            raise ValueError("period end must not precede period start")
        return start, end, "custom"
    try:
        period_date = date.fromisoformat(text_value)
    except ValueError as exc:
        raise ValueError(
            "period must be daily/weekly/monthly, Nd, an ISO date, or start/end"
        ) from exc
    start = datetime.combine(period_date, time.min, tzinfo=UTC)
    end = datetime.combine(period_date, time.max, tzinfo=UTC)
    return start, end, "calendar_day"


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _event_bucket(event_type: Any, detail: Mapping[str, Any]) -> str | None:
    normalized = str(event_type or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized in SEARCH_EVENT_TYPES:
        return "searched"
    if normalized in SCREEN_EVENT_TYPES:
        return "screened"
    if normalized in REJECT_EVENT_TYPES:
        return "rejected"
    if normalized in ADVANCE_EVENT_TYPES:
        return "advanced"
    supplied_status = detail.get("coverage_status", detail.get("status"))
    if supplied_status is not None:
        status = str(supplied_status).strip().casefold().replace("-", "_").replace(" ", "_")
        if status in {"searched", "screened", "rejected", "advanced"}:
            return status
    if normalized in {"stage_change", "stage_changed", "pipeline_stage"}:
        stage = str(
            detail.get("to_stage", detail.get("new_stage", detail.get("stage", "")))
        ).strip().casefold()
        if stage == "passed":
            return "rejected"
        if stage in {"contacted", "loi", "under_contract", "diligence", "closing", "owned"}:
            return "advanced"
        if stage == "analyzing":
            return "screened"
    return None


def _coverage_rows(path: Path, start: datetime, end: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {
        "event_counts": {"searched": 0, "screened": 0, "rejected": 0, "advanced": 0},
        "classified_event_count": 0,
        "unclassified_event_count": 0,
        "saved_search_count": 0,
        "saved_match_count": 0,
    }
    if not path.exists():
        return result
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        if _table_exists(connection, "deal_events"):
            rows = connection.execute(
                """
                SELECT event_type, event_json
                FROM deal_events
                WHERE COALESCE(event_ts, created_at) >= ?
                  AND COALESCE(event_ts, created_at) <= ?
                ORDER BY COALESCE(event_ts, created_at), id
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            for row in rows:
                try:
                    decoded = json.loads(str(row["event_json"] or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    decoded = {}
                detail = decoded if isinstance(decoded, Mapping) else {}
                bucket = _event_bucket(row["event_type"], detail)
                if bucket is None:
                    result["unclassified_event_count"] += 1
                    continue
                result["event_counts"][bucket] += 1
                result["classified_event_count"] += 1
        if _table_exists(connection, "saved_searches"):
            result["saved_search_count"] = int(
                connection.execute("SELECT COUNT(*) FROM saved_searches").fetchone()[0]
            )
        if _table_exists(connection, "seen_matches"):
            result["saved_match_count"] = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM seen_matches
                    WHERE first_seen >= ? AND first_seen <= ?
                    """,
                    (start.isoformat(), end.isoformat()),
                ).fetchone()[0]
            )
    finally:
        connection.close()
    return result


def _conversion(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator * 100 / denominator, 2)


def coverage_report(
    period: Any,
    *,
    as_of: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Assemble the recorded sourcing funnel without inferring offline work."""

    report_as_of = _as_utc(as_of, label="as_of")
    start, end, label = _period_window(period, report_as_of)
    evidence = _coverage_rows(_db_path(db_path, config), start, end)
    event_counts = evidence["event_counts"]
    searched = int(evidence["saved_match_count"]) + int(event_counts["searched"])
    screened = int(event_counts["screened"])
    rejected = int(event_counts["rejected"])
    advanced = int(event_counts["advanced"])
    untouched = max(searched - screened, 0)
    counts = {
        "searched": searched,
        "screened": screened,
        "rejected": rejected,
        "advanced": advanced,
        "untouched": untouched,
    }
    instrumentation_gaps: list[str] = []
    if screened > searched:
        instrumentation_gaps.append(
            "Recorded screening events exceed recorded searched inventory; upstream search activity is incomplete."
        )
    if rejected + advanced > screened:
        instrumentation_gaps.append(
            "Recorded dispositions exceed recorded screening events; stage instrumentation is incomplete or events overlap."
        )
    if evidence["saved_search_count"] and not evidence["saved_match_count"]:
        instrumentation_gaps.append(
            "Saved searches exist but no seen_matches were recorded in this period; search runs themselves are not tracked."
        )
    funnel = dict(counts)
    funnel["screened_from_searched_pct"] = _conversion(screened, searched)
    funnel["rejected_from_screened_pct"] = _conversion(rejected, screened)
    funnel["advanced_from_screened_pct"] = _conversion(advanced, screened)
    return {
        "period": {
            "input": period,
            "label": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "as_of": report_as_of.isoformat(),
        },
        "counts": counts,
        "searched": searched,
        "screened": screened,
        "rejected": rejected,
        "advanced": advanced,
        "untouched": untouched,
        "funnel": funnel,
        "saved_searches": {
            "configured_count": int(evidence["saved_search_count"]),
            "matches_first_seen_in_period": int(evidence["saved_match_count"]),
        },
        "event_evidence": {
            "counts_by_stage": dict(event_counts),
            "classified_sample_size": int(evidence["classified_event_count"]),
            "unclassified_sample_size": int(evidence["unclassified_event_count"]),
        },
        "untouched_inventory_note": UNTOUCHED_NOTE,
        "instrumentation_gaps": instrumentation_gaps,
        "methodology": (
            "searched = seen_matches first recorded in-period + explicit search events; "
            "screened/rejected/advanced = classified in-period deal_events. Counts are "
            "recorded activity, may overlap, and do not establish total market coverage."
        ),
    }


def _listing_mapping(listing: Any) -> dict[str, Any]:
    if isinstance(listing, Mapping):
        return dict(listing)
    model_dump = getattr(listing, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dict(dumped)
    raise ValueError("listing must be a mapping or model with model_dump()")


def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item).strip() for item in value if str(item).strip()]
    normalized = str(value).strip()
    return [normalized] if normalized else []


def _first_value(values: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in values and values[key] is not None:
            return values[key]
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _text_matches(actual: Any, allowed: Any) -> bool | None:
    actual_values = [item.casefold() for item in _values(actual)]
    allowed_values = [item.casefold() for item in _values(allowed)]
    if not actual_values:
        return None
    return any(
        candidate == target or candidate in target or target in candidate
        for candidate in actual_values
        for target in allowed_values
    )


def _structured_mandate(
    listing: Mapping[str, Any], mandate: Mapping[str, Any]
) -> dict[str, Any]:
    reasons: list[str] = []
    gaps: list[str] = []
    conflicts: list[str] = []
    checks = 0
    dimensions = (
        (
            "property_type",
            ("property_types", "asset_types", "property_type", "asset_type", "types"),
            ("property_type", "asset_type", "type"),
        ),
        (
            "geography",
            ("geographies", "geography", "markets", "market", "states", "state"),
            ("market", "geography", "location", "city", "state", "county", "msa"),
        ),
        (
            "strategy",
            ("strategies", "strategy"),
            ("strategy", "strategy_hint", "listing_type"),
        ),
    )
    consumed: set[str] = {"name", "label", "description", "notes"}
    for label, mandate_keys, listing_keys in dimensions:
        requirement = _first_value(mandate, mandate_keys)
        consumed.update(key for key in mandate_keys if key in mandate)
        if requirement is None:
            continue
        checks += 1
        if label == "geography":
            actual_items: list[str] = []
            for listing_key in listing_keys:
                actual_items.extend(_values(listing.get(listing_key)))
            actual: Any = actual_items or None
        else:
            actual = _first_value(listing, listing_keys)
        match = _text_matches(actual, requirement)
        if match is True:
            reasons.append(f"{label} matched: {actual}")
        elif match is False:
            conflicts.append(f"{label} outside mandate: {actual}")
        else:
            gaps.append(f"listing has no recorded {label}")

    numeric_dimensions = (
        ("min_price", ("price_usd", "price", "asking_price"), "at least"),
        ("max_price", ("price_usd", "price", "asking_price"), "at most"),
        ("capacity", ("price_usd", "price", "asking_price"), "at most"),
        ("min_size", ("size_sqft", "square_feet", "building_size", "size"), "at least"),
        ("max_size", ("size_sqft", "square_feet", "building_size", "size"), "at most"),
    )
    for mandate_key, listing_keys, comparison in numeric_dimensions:
        if mandate_key not in mandate or mandate[mandate_key] is None:
            continue
        consumed.add(mandate_key)
        checks += 1
        required_number = _number(mandate[mandate_key])
        if required_number is None:
            conflicts.append(f"mandate {mandate_key} is not numeric")
            continue
        actual_raw = _first_value(listing, listing_keys)
        actual_number = _number(actual_raw)
        if actual_number is None:
            gaps.append(f"listing has no numeric {listing_keys[0]}")
            continue
        matched = actual_number >= required_number if comparison == "at least" else actual_number <= required_number
        if matched:
            reasons.append(f"{mandate_key} matched: {actual_number:g} is {comparison} {required_number:g}")
        else:
            conflicts.append(f"{mandate_key} conflict: {actual_number:g} is not {comparison} {required_number:g}")

    for key, requirement in mandate.items():
        if key in consumed or requirement is None:
            continue
        checks += 1
        actual = listing.get(key)
        match = _text_matches(actual, requirement)
        if match is True:
            reasons.append(f"{key} matched: {actual}")
        elif match is False:
            conflicts.append(f"{key} outside mandate: {actual}")
        else:
            gaps.append(f"listing has no recorded {key}")
    eligible = bool(reasons) and not conflicts
    score = round(len(reasons) * 100 / max(checks, 1), 2) if eligible else 0.0
    return {
        "eligible": eligible,
        "score": score,
        "reasons": reasons,
        "gaps": gaps,
        "conflicts": conflicts,
        "checks": checks,
    }


def _string_mandate(listing: Mapping[str, Any], mandate: str) -> dict[str, Any]:
    flattened = " ".join(
        str(value) for value in listing.values() if value is not None
    ).casefold()
    terms = [term for term in re.findall(r"[a-z0-9]+", mandate.casefold()) if len(term) > 1]
    matched = bool(terms) and all(term in flattened for term in terms)
    return {
        "eligible": matched,
        "score": 100.0 if matched else 0.0,
        "reasons": [f"mandate text matched: {mandate}"] if matched else [],
        "gaps": [],
        "conflicts": [] if matched else [f"mandate text did not match recorded listing fields: {mandate}"],
        "checks": 1,
    }


def _mandates(value: Any) -> list[Any]:
    if isinstance(value, (str, Mapping)):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    if value is None:
        return []
    raise ValueError("team mandates must be a mapping, string, or list")


def route_lead(
    listing: Any,
    team: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Rank team members whose caller-supplied mandates fit a listing."""

    listing_values = _listing_mapping(listing)
    if isinstance(team, (str, bytes)) or not isinstance(team, Sequence):
        raise ValueError("team must be a list of {name, mandates} mappings")
    routes: list[dict[str, Any]] = []
    reviewed = 0
    for index, member in enumerate(team):
        if not isinstance(member, Mapping):
            raise ValueError(f"team[{index}] must be a mapping")
        name = str(member.get("name") or "").strip()
        if not name:
            raise ValueError(f"team[{index}].name cannot be blank")
        member_mandates = _mandates(member.get("mandates"))
        reviewed += 1
        evaluations: list[tuple[int, dict[str, Any], Any]] = []
        for mandate_index, mandate in enumerate(member_mandates):
            if isinstance(mandate, Mapping):
                result = _structured_mandate(listing_values, mandate)
            elif isinstance(mandate, str):
                result = _string_mandate(listing_values, mandate)
            else:
                raise ValueError(
                    f"team[{index}].mandates[{mandate_index}] must be a mapping or string"
                )
            evaluations.append((mandate_index, result, mandate))
        eligible = [item for item in evaluations if item[1]["eligible"]]
        if not eligible:
            continue
        best_index, best, best_mandate = sorted(
            eligible,
            key=lambda item: (-float(item[1]["score"]), item[0]),
        )[0]
        routes.append(
            {
                "name": name,
                "score": best["score"],
                "reasons": list(best["reasons"]),
                "evidence_gaps": list(best["gaps"]),
                "matched_mandate_index": best_index,
                "matched_mandate": best_mandate,
                "team_order": index,
            }
        )
    routes.sort(
        key=lambda route: (
            -float(route["score"]),
            int(route["team_order"]),
            str(route["name"]).casefold(),
        )
    )
    for rank, route in enumerate(routes, start=1):
        route["rank"] = rank
        route.pop("team_order", None)
    listing_id = _first_value(listing_values, ("deal_id", "source_id", "id", "url", "address"))
    return {
        "listing": {"id": listing_id, "recorded_fields": sorted(listing_values)},
        "recommended": routes[0] if routes else None,
        "routes": routes,
        "candidate_count": len(routes),
        "team_members_reviewed": reviewed,
        "message": (
            "Ranked recorded mandate matches; verify current capacity and assignment."
            if routes
            else "no recorded mandate-matched candidates"
        ),
        "honesty": (
            "Routing uses only caller-supplied listing fields and recorded mandates. "
            "It does not establish availability, capacity, licensing, or approval to act."
        ),
    }


__all__ = ["UNTOUCHED_NOTE", "coverage_report", "route_lead"]
