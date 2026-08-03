"""Transparent forced-sale screening with marketing and cost ranges.

The discount grid below is an internal analytical convention, not empirical market
evidence.  Returning the entire grid alongside the selected band makes the choice
auditable and prevents a screening discount from masquerading as an appraisal input.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


DISCLAIMER = (
    "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
)
CONVENTION_CITATION = (
    "Internal forced-sale analytical convention table v1: marketing-period and "
    "liquidity discount bands; screening convention, not observed market evidence."
)

# Shorter exposure and thinner liquidity receive wider/higher discount bands.  These
# are published conventions, not claims about a particular market or asset.
DISCOUNT_CONVENTION_TABLE: dict[str, dict[str, tuple[float, float]]] = {
    "0_to_3_months": {
        "high": (0.05, 0.10),
        "normal": (0.08, 0.15),
        "thin": (0.12, 0.22),
        "illiquid": (0.18, 0.30),
    },
    "over_3_to_6_months": {
        "high": (0.03, 0.07),
        "normal": (0.05, 0.10),
        "thin": (0.09, 0.17),
        "illiquid": (0.14, 0.25),
    },
    "over_6_to_12_months": {
        "high": (0.01, 0.04),
        "normal": (0.03, 0.07),
        "thin": (0.06, 0.12),
        "illiquid": (0.10, 0.20),
    },
    "over_12_months": {
        "high": (0.00, 0.03),
        "normal": (0.02, 0.05),
        "thin": (0.04, 0.09),
        "illiquid": (0.08, 0.15),
    },
}


def _number(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    cleaned: Any = value
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1]
    try:
        number = float(cleaned)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _range(value: Any, label: str, *, nonnegative: bool = True) -> tuple[float, float]:
    if isinstance(value, Mapping):
        nested_key = next(
            (key for key in ("range", "value_range") if key in value), None
        )
        if nested_key is not None:
            return _range(value[nested_key], f"{label}.{nested_key}", nonnegative=nonnegative)
        low_key = next(
            (key for key in ("low", "min", "minimum") if key in value), None
        )
        high_key = next(
            (key for key in ("high", "max", "maximum") if key in value), None
        )
        if low_key is None or high_key is None:
            raise ValueError(f"{label} range must include low and high")
        low = _number(value[low_key], f"{label}.{low_key}")
        high = _number(value[high_key], f"{label}.{high_key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
        if len(values) != 2:
            raise ValueError(f"{label} range must contain exactly two values")
        low = _number(values[0], f"{label}[0]")
        high = _number(values[1], f"{label}[1]")
    else:
        low = high = _number(value, label)
    if low > high:
        raise ValueError(f"{label} range must be ordered low to high")
    if nonnegative and low < 0:
        raise ValueError(f"{label} must be non-negative")
    return low, high


def _as_range(low: float, high: float) -> dict[str, float]:
    return {"low": low, "high": high}


def _rate_range(value: Any, label: str) -> tuple[float, float]:
    low, high = _range(value, label)
    low = low / 100 if low > 1 else low
    high = high / 100 if high > 1 else high
    if low < 0 or high > 1:
        raise ValueError(f"{label} must be a decimal or percent from 0% to 100%")
    return low, high


def _period_band(months: float) -> str:
    if months <= 3:
        return "0_to_3_months"
    if months <= 6:
        return "over_3_to_6_months"
    if months <= 12:
        return "over_6_to_12_months"
    return "over_12_months"


def _liquidity(value: Any) -> tuple[str, str]:
    if isinstance(value, Mapping):
        raw = value.get("convention", value.get("liquidity", value.get("level")))
    else:
        raw = value
    if raw is None:
        raise ValueError("market_liquidity convention is required")
    normalized = str(raw).strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "high": "high",
        "liquid": "high",
        "deep": "high",
        "strong": "high",
        "normal": "normal",
        "average": "normal",
        "moderate": "normal",
        "typical": "normal",
        "balanced": "normal",
        "thin": "thin",
        "low": "thin",
        "limited": "thin",
        "illiquid": "illiquid",
        "very_low": "illiquid",
        "distressed": "illiquid",
    }
    selected = aliases.get(normalized)
    if selected is None:
        raise ValueError(
            "market_liquidity must be high/liquid, normal/average, thin/low, or illiquid"
        )
    return selected, str(raw)


def _looks_like_dollars(value: Any) -> bool:
    return isinstance(value, str) and "$" in value


def _sale_cost_inputs(value: Any) -> tuple[tuple[float, float], tuple[float, float], str]:
    """Return a sale-cost rate range, dollar range, and transparent input basis."""

    zero = (0.0, 0.0)
    if isinstance(value, Mapping):
        basis = str(value.get("basis", value.get("unit", ""))).strip().casefold()
        rate_value = next(
            (
                value[key]
                for key in (
                    "rate",
                    "rate_range",
                    "percent",
                    "percentage",
                    "pct",
                    "commission_rate",
                )
                if key in value
            ),
            None,
        )
        dollar_value = next(
            (
                value[key]
                for key in (
                    "amount",
                    "amount_range",
                    "dollars",
                    "dollar_range",
                    "fixed_amount",
                    "total",
                )
                if key in value
            ),
            None,
        )
        has_endpoints = any(key in value for key in ("low", "min", "minimum")) and any(
            key in value for key in ("high", "max", "maximum")
        )
        inferred = ""
        if rate_value is None and dollar_value is None and "value" in value:
            if basis in {"rate", "percent", "percentage", "pct"}:
                rate_value = value["value"]
            elif basis in {"dollar", "dollars", "amount", "fixed"}:
                dollar_value = value["value"]
            else:
                raise ValueError("cost_of_sale.value requires a rate or dollar basis")
        elif rate_value is None and dollar_value is None and has_endpoints:
            endpoints = _range(value, "cost_of_sale")
            if basis in {"dollar", "dollars", "amount", "fixed"}:
                dollar_value = endpoints
            elif basis in {"rate", "percent", "percentage", "pct"}:
                rate_value = endpoints
            elif endpoints[1] <= 100:
                rate_value = endpoints
                inferred = "bare range at or below 100 interpreted as a percent/rate"
            else:
                dollar_value = endpoints
                inferred = "bare range over 100 interpreted as dollars"
        if rate_value is None and dollar_value is None:
            raise ValueError(
                "cost_of_sale mapping must provide rate/percent, amount/dollars, or low/high"
            )
        rates = _rate_range(rate_value, "cost_of_sale.rate") if rate_value is not None else zero
        dollars = _range(dollar_value, "cost_of_sale.amount") if dollar_value is not None else zero
        parts = []
        if rate_value is not None:
            parts.append("rate")
        if dollar_value is not None:
            parts.append("fixed dollars")
        if inferred:
            parts.append(inferred)
        return rates, dollars, " plus ".join(parts)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        endpoints = _range(value, "cost_of_sale")
        if endpoints[1] <= 100:
            return (
                _rate_range(endpoints, "cost_of_sale"),
                zero,
                "bare sequence range at or below 100 interpreted as a percent/rate",
            )
        return (
            zero,
            endpoints,
            "bare sequence range over 100 interpreted as fixed dollars",
        )

    if _looks_like_dollars(value):
        return zero, _range(value, "cost_of_sale"), "scalar with $ interpreted as fixed dollars"
    number = _number(value, "cost_of_sale")
    if number < 0:
        raise ValueError("cost_of_sale must be non-negative")
    if number <= 100:
        return _rate_range(number, "cost_of_sale"), zero, (
            "scalar at or below 1 interpreted as a decimal rate; scalar over 1 through "
            "100 interpreted as a percent"
        )
    return zero, (number, number), "scalar over 100 interpreted as fixed dollars"


def _carrying_cost_total(
    value: Any | None,
    months: float,
    market_value: tuple[float, float],
) -> tuple[tuple[float, float], str]:
    if value is None:
        return (0.0, 0.0), "not supplied; optional carrying cost set to $0"
    if not isinstance(value, Mapping):
        total = _range(value, "carrying_costs")
        return total, "scalar or bare range interpreted as total over the marketing period"

    candidates = (
        ("monthly", "monthly dollars"),
        ("monthly_range", "monthly dollars"),
        ("monthly_cost", "monthly dollars"),
        ("monthly_cost_range", "monthly dollars"),
        ("annual", "annual dollars"),
        ("annual_range", "annual dollars"),
        ("annual_cost", "annual dollars"),
        ("annual_cost_range", "annual dollars"),
        ("total", "total dollars"),
        ("total_range", "total dollars"),
        ("amount", "total dollars"),
        ("amount_range", "total dollars"),
        ("annual_rate", "annual value rate"),
        ("annual_rate_range", "annual value rate"),
    )
    found = [(key, basis) for key, basis in candidates if key in value]
    if len(found) > 1:
        raise ValueError("carrying_costs must use one monthly, annual, total, or annual_rate basis")
    if not found:
        if any(key in value for key in ("low", "min", "minimum")) and any(
            key in value for key in ("high", "max", "maximum")
        ):
            total = _range(value, "carrying_costs")
            return total, "bare mapping range interpreted as total over the marketing period"
        raise ValueError(
            "carrying_costs mapping must provide monthly, annual, total, amount, or annual_rate"
        )
    key, basis = found[0]
    if basis == "annual value rate":
        rate = _rate_range(value[key], f"carrying_costs.{key}")
        return (
            market_value[0] * rate[0] * months / 12,
            market_value[1] * rate[1] * months / 12,
        ), "annual rate of market value multiplied by marketing_period / 12"
    amounts = _range(value[key], f"carrying_costs.{key}")
    if basis == "monthly dollars":
        return (amounts[0] * months, amounts[1] * months), (
            "monthly dollar range multiplied by marketing_period_months"
        )
    if basis == "annual dollars":
        return (amounts[0] * months / 12, amounts[1] * months / 12), (
            "annual dollar range multiplied by marketing_period_months / 12"
        )
    return amounts, "stated total over the marketing period"


def _published_table() -> dict[str, dict[str, dict[str, float]]]:
    return {
        period: {
            liquidity: _as_range(*discount_range)
            for liquidity, discount_range in levels.items()
        }
        for period, levels in DISCOUNT_CONVENTION_TABLE.items()
    }


def forced_sale_value(
    market_value: Any,
    marketing_period: Any,
    market_liquidity: Any,
    cost_of_sale: Any,
    carrying_costs: Any | None = None,
) -> dict[str, Any]:
    """Estimate a forced-sale net range using a fully exposed internal grid.

    Rate inputs accept either decimals or percentages.  ``cost_of_sale`` can be a
    rate, fixed-dollar amount, range, or a mapping containing both rate and amount.
    Malformed input is contained at the public boundary as ``{"error": ...}``.
    """

    try:
        market = _range(market_value, "market_value")
        months = _number(marketing_period, "marketing_period")
        if months < 0:
            raise ValueError("marketing_period must be non-negative months")
        liquidity, supplied_liquidity = _liquidity(market_liquidity)
        period_band = _period_band(months)
        discount = DISCOUNT_CONVENTION_TABLE[period_band][liquidity]

        gross_forced = (
            market[0] * (1 - discount[1]),
            market[1] * (1 - discount[0]),
        )
        discount_amount = (
            market[0] * discount[0],
            market[1] * discount[1],
        )

        sale_rates, fixed_sale_costs, sale_cost_basis = _sale_cost_inputs(cost_of_sale)
        sale_cost_amount = (
            gross_forced[0] * sale_rates[0] + fixed_sale_costs[0],
            gross_forced[1] * sale_rates[1] + fixed_sale_costs[1],
        )
        carry_total, carrying_basis = _carrying_cost_total(
            carrying_costs, months, market
        )

        net = (
            gross_forced[0] * (1 - sale_rates[1])
            - fixed_sale_costs[1]
            - carry_total[1],
            gross_forced[1] * (1 - sale_rates[0])
            - fixed_sale_costs[0]
            - carry_total[0],
        )
        if net[0] > net[1]:
            raise ValueError("cost assumptions do not produce an ordered net range")

        return {
            "market_value_range": _as_range(*market),
            "marketing_period_months": months,
            "market_liquidity": {
                "supplied": supplied_liquidity,
                "normalized_convention": liquidity,
            },
            "discount_convention": {
                "period_band": period_band,
                "liquidity": liquidity,
                "discount_rate_range": _as_range(*discount),
                "citation": CONVENTION_CITATION,
                "source": CONVENTION_CITATION,
                "status": "internal screening convention; not a market observation or prediction",
            },
            "discount_convention_table": _published_table(),
            "convention_citation": CONVENTION_CITATION,
            "forced_sale_discount_amount_range": _as_range(*discount_amount),
            "gross_forced_sale_value_range": _as_range(*gross_forced),
            "cost_of_sale": {
                "rate_range": _as_range(*sale_rates),
                "fixed_dollar_range": _as_range(*fixed_sale_costs),
                "amount_range": _as_range(*sale_cost_amount),
                "input_basis": sale_cost_basis,
                "calculation": "discounted gross sale value * rate + fixed dollars",
            },
            "carrying_costs": {
                "total_over_marketing_range": _as_range(*carry_total),
                "input_basis": carrying_basis,
            },
            "net_forced_sale_value_range": _as_range(*net),
            "method": (
                "market value less selected forced-sale discount, sale costs, and "
                "carrying costs over the stated marketing period"
            ),
            "disclaimer": DISCLAIMER,
        }
    except Exception as exc:  # Public analytical boundary: never leak malformed-input errors.
        return {"error": str(exc)}
