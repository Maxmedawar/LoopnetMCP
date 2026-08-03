"""Penny-exact, dated financing cash-requirement schedules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any


HORIZONS = frozenset({30, 60, 90})
REQUIREMENT_CATEGORIES = (
    "closings",
    "capex",
    "reserves",
    "capital_calls",
    "operating_shortfalls",
)

_INPUT_KEYS = frozenset(
    {
        *REQUIREMENT_CATEGORIES,
        "available",
        "available_cents",
        "available_cash_cents",
        "as_of",
    }
)
_ROW_KEYS = frozenset(
    {
        "date",
        "due_date",
        "closing_date",
        "month",
        "cents",
        "amount_cents",
        "required_cents",
        "equity_cents",
        "capex_cents",
        "reserve_cents",
        "call_cents",
        "lp_call_cents",
        "gross_need_cents",
        "shortfall_cents",
        "deal",
        "deal_id",
        "investor",
        "description",
        "label",
        "notes",
        "source",
        "source_ref",
        "investor_calls",
        "needs_cents",
        "gp_coinvest_cents",
        "gp_coinvest_source_ref",
        "unfunded_gap_cents",
        "balance_check_cents",
    }
)
_FUND_FORECAST_KEYS = frozenset(
    {
        "schedule",
        "investor_tracking",
        "totals_cents",
        "gp_coinvest_pct",
        "gp_coinvest_source_ref",
        "allocation_method",
        "distribution_forecast",
        "default_remedy",
        "counsel_flag",
        "anti_fraud_warning",
        "guardrail",
        "warning",
        "unrecognized_inputs",
    }
)
_CENTS_KEYS = {
    "closings": ("equity_cents", "cents", "amount_cents", "required_cents"),
    "capex": ("capex_cents", "cents", "amount_cents", "required_cents"),
    "reserves": ("reserve_cents", "cents", "amount_cents", "required_cents"),
    "capital_calls": (
        "call_cents",
        "cents",
        "amount_cents",
        "lp_call_cents",
        "gross_need_cents",
        "required_cents",
    ),
    "operating_shortfalls": (
        "shortfall_cents",
        "cents",
        "amount_cents",
        "required_cents",
    ),
}


def _iso_date(value: Any, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{label} is required")
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO date or datetime") from exc
        return parsed.date()


def _cents(value: Any, label: str) -> int:
    """Accept exact integer cents only; floats and booleans are ambiguous."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer number of cents")
    if value < 0:
        raise ValueError(f"{label} must be nonnegative")
    return value


def _unknown_keys(
    value: Mapping[str, Any], allowed: frozenset[str], *, path: str
) -> list[str]:
    return [
        f"{path}.{key}"
        for key in value
        if not isinstance(key, str) or key not in allowed
    ]


def _materialize_rows(value: Any, category: str) -> tuple[list[Any], list[str]]:
    if value is None:
        return [], []
    if category == "capital_calls" and isinstance(value, Mapping) and "schedule" in value:
        unknown = _unknown_keys(value, _FUND_FORECAST_KEYS, path="inputs.capital_calls")
        schedule = value.get("schedule")
        if isinstance(schedule, (str, bytes, bytearray)) or not isinstance(
            schedule, Sequence
        ):
            raise ValueError("inputs.capital_calls.schedule must be a list of mappings")
        return list(schedule), unknown
    if isinstance(value, Mapping):
        if any(key in value for key in ("date", "due_date", "closing_date", "month")):
            return [value], []
        rows: list[dict[str, Any]] = []
        for raw_date, raw_amount in value.items():
            if isinstance(raw_amount, Mapping):
                rows.append({"date": raw_date, **dict(raw_amount)})
            else:
                rows.append({"date": raw_date, "cents": raw_amount})
        return rows, []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value), []
    raise ValueError(f"inputs.{category} must be a list or dated mapping")


def _row_date(row: Mapping[str, Any], label: str) -> date:
    for key in ("date", "due_date", "closing_date"):
        if row.get(key) is not None:
            return _iso_date(row[key], f"{label}.{key}")
    month = row.get("month")
    if month is not None:
        text = str(month).strip()
        if len(text) == 7:
            text = f"{text}-01"
        return _iso_date(text, f"{label}.month")
    raise ValueError(f"{label} requires date, due_date, closing_date, or month")


def _row_cents(row: Mapping[str, Any], category: str, label: str) -> int:
    for key in _CENTS_KEYS[category]:
        if row.get(key) is not None:
            return _cents(row[key], f"{label}.{key}")
    if category == "capital_calls" and row.get("investor_calls") is not None:
        calls = row["investor_calls"]
        if isinstance(calls, (str, bytes, bytearray)) or not isinstance(calls, Sequence):
            raise ValueError(f"{label}.investor_calls must be a list of mappings")
        total = 0
        for index, call in enumerate(calls):
            if not isinstance(call, Mapping):
                raise ValueError(f"{label}.investor_calls[{index}] must be a mapping")
            total += _cents(
                call.get("call_cents"),
                f"{label}.investor_calls[{index}].call_cents",
            )
        return total
    accepted = ", ".join(_CENTS_KEYS[category])
    raise ValueError(f"{label} requires one cents field: {accepted}")


def _available_cents(inputs: Mapping[str, Any]) -> tuple[int | None, list[str]]:
    supplied: list[tuple[str, Any]] = [
        (key, inputs[key])
        for key in ("available_cents", "available_cash_cents", "available")
        if key in inputs and inputs[key] is not None
    ]
    if not supplied:
        return None, []
    normalized: list[tuple[str, int]] = []
    unknown: list[str] = []
    for key, raw in supplied:
        if isinstance(raw, Mapping):
            unknown.extend(
                _unknown_keys(
                    raw,
                    frozenset({"cents", "available_cents", "source", "source_ref"}),
                    path=f"inputs.{key}",
                )
            )
            amount = raw.get("available_cents", raw.get("cents"))
        else:
            amount = raw
        normalized.append((key, _cents(amount, f"inputs.{key}")))
    values = {amount for _, amount in normalized}
    if len(values) != 1:
        labels = ", ".join(key for key, _ in normalized)
        raise ValueError(f"conflicting available-cash inputs: {labels}")
    return normalized[0][1], unknown


def cash_requirements(
    horizon_days: int,
    inputs: Mapping[str, Any],
    *,
    as_of: Any = None,
) -> dict[str, Any]:
    """Build an inclusive dated cash-need schedule for a 30/60/90-day horizon.

    ``capital_calls`` accepts ordinary dated rows or the structured result of
    :func:`cre_mcp.fund.calls.forecast_capital_calls`.  The latter is consumed
    read-only; this module never mutates fund commitments or funded balances.
    """

    if isinstance(horizon_days, bool) or horizon_days not in HORIZONS:
        raise ValueError("horizon_days must be one of: 30, 60, 90")
    if not isinstance(inputs, Mapping):
        raise ValueError("inputs must be a mapping")
    anchor = _iso_date(
        as_of if as_of is not None else inputs.get("as_of", datetime.now(UTC).date()),
        "as_of",
    )
    horizon_end = anchor + timedelta(days=horizon_days)
    unrecognized_top_level = [
        str(key)
        for key in inputs
        if not isinstance(key, str) or key not in _INPUT_KEYS
    ]
    unrecognized = _unknown_keys(inputs, _INPUT_KEYS, path="inputs")
    available, available_unknown = _available_cents(inputs)
    unrecognized.extend(available_unknown)

    dated: dict[date, list[dict[str, Any]]] = {}
    excluded: list[dict[str, Any]] = []
    for category in REQUIREMENT_CATEGORIES:
        rows, container_unknown = _materialize_rows(inputs.get(category), category)
        unrecognized.extend(container_unknown)
        for index, raw_row in enumerate(rows):
            label = f"inputs.{category}[{index}]"
            if not isinstance(raw_row, Mapping):
                raise ValueError(f"{label} must be a mapping")
            unrecognized.extend(_unknown_keys(raw_row, _ROW_KEYS, path=label))
            due = _row_date(raw_row, label)
            amount = _row_cents(raw_row, category, label)
            item = {
                "category": category,
                "date": due.isoformat(),
                "cents": amount,
                "deal": raw_row.get("deal") or raw_row.get("deal_id"),
                "description": (
                    raw_row.get("description")
                    or raw_row.get("label")
                    or raw_row.get("notes")
                ),
                "source_ref": raw_row.get("source_ref") or raw_row.get("source"),
            }
            if anchor <= due <= horizon_end:
                dated.setdefault(due, []).append(item)
            else:
                excluded.append(item)

    schedule: list[dict[str, Any]] = []
    totals = {category: 0 for category in REQUIREMENT_CATEGORIES}
    cumulative = 0
    peak_daily_need = 0
    peak_daily_date: str | None = None
    for due in sorted(dated):
        items = dated[due]
        category_totals = {category: 0 for category in REQUIREMENT_CATEGORIES}
        for item in items:
            amount = int(item["cents"])
            category = str(item["category"])
            category_totals[category] += amount
            totals[category] += amount
        daily_total = sum(category_totals.values())
        cumulative += daily_total
        if daily_total > peak_daily_need or peak_daily_date is None:
            peak_daily_need = daily_total
            peak_daily_date = due.isoformat()
        schedule.append(
            {
                "date": due.isoformat(),
                "requirements_cents": category_totals,
                "total_requirement_cents": daily_total,
                "daily_need_cents": daily_total,
                "cumulative_requirement_cents": cumulative,
                "cumulative_need_cents": cumulative,
                "items": items,
                "balance_check_cents": daily_total - sum(
                    int(item["cents"]) for item in items
                ),
            }
        )

    peak_need = cumulative
    peak_need_date = schedule[-1]["date"] if schedule else None
    totals["total_requirement"] = peak_need
    if sum(totals[category] for category in REQUIREMENT_CATEGORIES) != peak_need:
        raise ArithmeticError("cash-requirement category totals did not balance")

    if available is None:
        available_minus_peak = None
        surplus = None
        shortfall = None
        coverage_ratio = None
        coverage_status = "unknown_available_cash"
    else:
        available_minus_peak = available - peak_need
        surplus = max(available_minus_peak, 0)
        shortfall = max(-available_minus_peak, 0)
        coverage_ratio = None if peak_need == 0 else available / peak_need
        coverage_status = "covered" if available >= peak_need else "shortfall"

    unrecognized_paths = sorted(set(unrecognized))
    unrecognized_result = sorted(set(unrecognized_top_level + unrecognized_paths))
    return {
        "as_of": anchor.isoformat(),
        "horizon_days": horizon_days,
        "horizon_end": horizon_end.isoformat(),
        "schedule": schedule,
        "dated_requirements": schedule,
        "excluded_outside_horizon": excluded,
        "totals_cents": totals,
        "peak_need_cents": peak_need,
        "peak_need_date": peak_need_date,
        "peak_daily_need_cents": peak_daily_need,
        "peak_daily_need_date": peak_daily_date,
        "available_cents": available,
        "coverage_vs_available_cents": available_minus_peak,
        "coverage": {
            "status": coverage_status,
            "available_cents": available,
            "peak_need_cents": peak_need,
            "available_minus_peak_cents": available_minus_peak,
            "surplus_cents": surplus,
            "shortfall_cents": shortfall,
            "coverage_ratio": coverage_ratio,
        },
        "calculation_note": (
            "Peak need is cumulative scheduled requirements through the horizon; "
            "peak daily need is reported separately. All money is integer cents."
        ),
        "capital_calls_read_only": True,
        "unrecognized_inputs": unrecognized_result,
        "unrecognized_input_paths": unrecognized_paths,
    }


__all__ = ["HORIZONS", "REQUIREMENT_CATEGORIES", "cash_requirements"]
