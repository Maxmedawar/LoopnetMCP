"""Illustrative interest-rate-cap cost context with penny-exact reserve math.

This is deliberately not an options pricer or quote feed.  It applies a small,
published-in-code underwriting convention grid to caller-supplied loan facts so
that a financing team can size a rough premium reserve before requesting live
dealer quotes.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


CONVENTION_CITATION = (
    "MODELING CONVENTION — illustrative cap-premium range grid published in "
    "cre_mcp.finops.hedges; premium basis points vary by term and strike distance. "
    "It is an underwriting reserve convention, not observed market data or a quote."
)
LIVE_QUOTE_WARNING = (
    "Get live quotes from a licensed provider before relying on cap cost, timing, "
    "counterparty, collateral, or documentation terms."
)

# Premium cost as basis points of notional.  Strike-distance buckets are the cap
# strike less the current index, measured in basis points.  The deliberately wide
# ranges keep this useful as reserve context without presenting false precision.
CONVENTION_GRID_BPS: dict[int, tuple[dict[str, Any], ...]] = {
    1: (
        {"bucket": "at_or_below_index", "min_exclusive": None, "max_inclusive": 0, "low": 90, "high": 180},
        {"bucket": "1_to_50_bps_above", "min_exclusive": 0, "max_inclusive": 50, "low": 60, "high": 140},
        {"bucket": "51_to_100_bps_above", "min_exclusive": 50, "max_inclusive": 100, "low": 35, "high": 100},
        {"bucket": "101_to_200_bps_above", "min_exclusive": 100, "max_inclusive": 200, "low": 15, "high": 65},
        {"bucket": "over_200_bps_above", "min_exclusive": 200, "max_inclusive": None, "low": 5, "high": 35},
    ),
    2: (
        {"bucket": "at_or_below_index", "min_exclusive": None, "max_inclusive": 0, "low": 180, "high": 360},
        {"bucket": "1_to_50_bps_above", "min_exclusive": 0, "max_inclusive": 50, "low": 125, "high": 285},
        {"bucket": "51_to_100_bps_above", "min_exclusive": 50, "max_inclusive": 100, "low": 80, "high": 210},
        {"bucket": "101_to_200_bps_above", "min_exclusive": 100, "max_inclusive": 200, "low": 35, "high": 135},
        {"bucket": "over_200_bps_above", "min_exclusive": 200, "max_inclusive": None, "low": 15, "high": 75},
    ),
    3: (
        {"bucket": "at_or_below_index", "min_exclusive": None, "max_inclusive": 0, "low": 275, "high": 550},
        {"bucket": "1_to_50_bps_above", "min_exclusive": 0, "max_inclusive": 50, "low": 195, "high": 435},
        {"bucket": "51_to_100_bps_above", "min_exclusive": 50, "max_inclusive": 100, "low": 125, "high": 325},
        {"bucket": "101_to_200_bps_above", "min_exclusive": 100, "max_inclusive": 200, "low": 60, "high": 210},
        {"bucket": "over_200_bps_above", "min_exclusive": 200, "max_inclusive": None, "low": 25, "high": 115},
    ),
    4: (
        {"bucket": "at_or_below_index", "min_exclusive": None, "max_inclusive": 0, "low": 375, "high": 750},
        {"bucket": "1_to_50_bps_above", "min_exclusive": 0, "max_inclusive": 50, "low": 265, "high": 595},
        {"bucket": "51_to_100_bps_above", "min_exclusive": 50, "max_inclusive": 100, "low": 175, "high": 445},
        {"bucket": "101_to_200_bps_above", "min_exclusive": 100, "max_inclusive": 200, "low": 85, "high": 290},
        {"bucket": "over_200_bps_above", "min_exclusive": 200, "max_inclusive": None, "low": 35, "high": 160},
    ),
    5: (
        {"bucket": "at_or_below_index", "min_exclusive": None, "max_inclusive": 0, "low": 475, "high": 950},
        {"bucket": "1_to_50_bps_above", "min_exclusive": 0, "max_inclusive": 50, "low": 335, "high": 750},
        {"bucket": "51_to_100_bps_above", "min_exclusive": 50, "max_inclusive": 100, "low": 225, "high": 565},
        {"bucket": "101_to_200_bps_above", "min_exclusive": 100, "max_inclusive": 200, "low": 110, "high": 370},
        {"bucket": "over_200_bps_above", "min_exclusive": 200, "max_inclusive": None, "low": 45, "high": 205},
    ),
}

_LOAN_FIELDS = frozenset(
    {
        "balance",
        "balance_cents",
        "index",
        "index_name",
        "index_pct",
        "index_rate",
        "index_rate_pct",
        "spread",
        "spread_bps",
    }
)
_CAP_FIELDS = frozenset({"strike", "strike_pct", "term_years"})


def _decimal(value: Any, label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not parsed.is_finite():
        raise ValueError(f"{label} must be a finite number")
    return parsed


def _cents(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer number of cents")
    if value <= 0:
        raise ValueError(f"{label} must be positive")
    return value


def _rate_pct(value: Any, label: str) -> Decimal:
    parsed = _decimal(value, label)
    if parsed < 0:
        raise ValueError(f"{label} must be nonnegative")
    # Both 0.0525 and 5.25 are common structured representations of 5.25%.
    return parsed * Decimal(100) if parsed <= 1 else parsed


def _spread_bps(value: Any, label: str) -> Decimal:
    parsed = _decimal(value, label)
    if parsed < 0:
        raise ValueError(f"{label} must be nonnegative")
    if parsed <= 1:
        return parsed * Decimal(10_000)
    if parsed <= 25:
        return parsed * Decimal(100)
    return parsed


def _term(value: Any) -> int:
    parsed = _decimal(value, "cap.term_years")
    if parsed != parsed.to_integral_value():
        raise ValueError("cap.term_years must be a whole number from 1 through 5")
    years = int(parsed)
    if years not in CONVENTION_GRID_BPS:
        raise ValueError("cap.term_years must be a whole number from 1 through 5")
    return years


def _premium_cents(balance_cents: int, premium_bps: int) -> int:
    return int(
        (Decimal(balance_cents) * Decimal(premium_bps) / Decimal(10_000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def _escrow_case(target_cents: int, months: int) -> dict[str, Any]:
    base, remainder = divmod(target_cents, months)
    return {
        "target_cents": target_cents,
        "months": months,
        "base_monthly_cents": base,
        "remainder_cents": remainder,
        "months_at_base_plus_one_cent": remainder,
        "months_at_base_cents": months - remainder,
        "maximum_monthly_cents": base + (1 if remainder else 0),
        "exact_total_check_cents": (base * months) + remainder,
    }


def _select_bucket(term_years: int, distance_bps: Decimal) -> dict[str, Any]:
    for entry in CONVENTION_GRID_BPS[term_years]:
        lower = entry["min_exclusive"]
        upper = entry["max_inclusive"]
        if (lower is None or distance_bps > lower) and (
            upper is None or distance_bps <= upper
        ):
            return dict(entry)
    raise RuntimeError("cap convention grid has no matching strike-distance bucket")


def _index(loan: Mapping[str, Any]) -> tuple[str | None, Decimal | None]:
    named = loan.get("index_name")
    explicit_rate = loan.get(
        "index_rate_pct",
        loan.get("index_rate", loan.get("index_pct")),
    )
    raw_index = loan.get("index")
    if explicit_rate is not None:
        return (
            str(named or raw_index).strip() if named or raw_index is not None else None,
            _rate_pct(explicit_rate, "loan.index_rate"),
        )
    if raw_index is None:
        return (str(named).strip() if named not in (None, "") else None, None)
    try:
        _decimal(raw_index, "loan.index")
    except ValueError:
        index_name = str(raw_index).strip()
        if not index_name:
            raise ValueError("loan.index cannot be blank")
        return index_name, None
    return (
        str(named).strip() if named not in (None, "") else None,
        _rate_pct(raw_index, "loan.index"),
    )


def _full_term_envelope(term_years: int) -> dict[str, Any]:
    entries = CONVENTION_GRID_BPS[term_years]
    return {
        "bucket": "unknown_index_rate_full_term_envelope",
        "min_exclusive": None,
        "max_inclusive": None,
        "low": min(int(entry["low"]) for entry in entries),
        "high": max(int(entry["high"]) for entry in entries),
    }


def cap_cost_context(
    loan: Mapping[str, Any] | None,
    cap: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a disclosed convention range and exact monthly reserve arithmetic."""

    if not isinstance(loan, Mapping):
        raise ValueError("loan must be an object")
    if not isinstance(cap, Mapping):
        raise ValueError("cap must be an object")

    balance_raw = loan.get("balance_cents", loan.get("balance"))
    if "balance" in loan and "balance_cents" in loan and loan["balance"] != loan["balance_cents"]:
        raise ValueError("loan.balance and loan.balance_cents conflict")
    balance_cents = _cents(balance_raw, "loan.balance")
    strike_raw = cap.get("strike_pct", cap.get("strike"))
    index_name, index_pct = _index(loan)
    strike_pct = _rate_pct(strike_raw, "cap.strike")
    term_years = _term(cap.get("term_years"))
    spread_bps = None
    if loan.get("spread_bps", loan.get("spread")) is not None:
        spread_bps = _spread_bps(
            loan.get("spread_bps", loan.get("spread")), "loan.spread"
        )

    distance_bps = (
        (strike_pct - index_pct) * Decimal(100)
        if index_pct is not None
        else None
    )
    selected = (
        _select_bucket(term_years, distance_bps)
        if distance_bps is not None
        else _full_term_envelope(term_years)
    )
    low_cents = _premium_cents(balance_cents, int(selected["low"]))
    high_cents = _premium_cents(balance_cents, int(selected["high"]))
    months = term_years * 12
    low_escrow = _escrow_case(low_cents, months)
    high_escrow = _escrow_case(high_cents, months)
    unrecognized = sorted(
        [f"loan.{key}" for key in loan if key not in _LOAN_FIELDS]
        + [f"cap.{key}" for key in cap if key not in _CAP_FIELDS]
    )

    cost_range = {"low": low_cents, "high": high_cents}
    monthly_range = {
        "low": low_escrow["base_monthly_cents"],
        "high": high_escrow["maximum_monthly_cents"],
    }
    selected_public = {
        "term_years": term_years,
        "strike_distance_bucket": selected["bucket"],
        "premium_low_bps_of_notional": selected["low"],
        "premium_high_bps_of_notional": selected["high"],
    }
    return {
        "status": "illustrative_convention_range_only",
        "loan": {
            "balance_cents": balance_cents,
            "index": index_name,
            "index_pct": float(index_pct) if index_pct is not None else None,
            "spread_bps": float(spread_bps) if spread_bps is not None else None,
        },
        "cap": {
            "strike_pct": float(strike_pct),
            "term_years": term_years,
            "strike_distance_bps": float(distance_bps) if distance_bps is not None else None,
        },
        "cost_range_cents": cost_range,
        "premium_range_cents": cost_range,
        "cost_range": {"low_cents": low_cents, "high_cents": high_cents},
        "escrow": {
            "purpose": "Illustrative even monthly reserve toward the modeled cap premium; not a dealer-required escrow schedule.",
            "months": months,
            "monthly_range_cents": monthly_range,
            "low_case": low_escrow,
            "high_case": high_escrow,
        },
        "convention_grid": {
            "unit": "premium basis points of notional",
            "selected": selected_public,
            "citation": CONVENTION_CITATION,
        },
        "citation": CONVENTION_CITATION,
        "live_quote_warning": LIVE_QUOTE_WARNING,
        "input_gaps": (
            [
                "loan current index rate is not supplied; the selected range is the full low-to-high envelope across all strike-distance buckets for the term"
            ]
            if index_pct is None
            else []
        ),
        "unrecognized_inputs": unrecognized,
    }


__all__ = [
    "CONVENTION_CITATION",
    "CONVENTION_GRID_BPS",
    "LIVE_QUOTE_WARNING",
    "cap_cost_context",
]
