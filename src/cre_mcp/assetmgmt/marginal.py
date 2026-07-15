"""Time-adjusted marginal allocation of the next investment dollar."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Sequence


def _decimal(value: Any, *, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _cents(value: Any, *, name: str, non_negative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if non_negative and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _rate(value: Any) -> tuple[Decimal, str]:
    rate = _decimal(value, name="opportunity_cost_rate")
    if rate < 0:
        raise ValueError("opportunity_cost_rate must be non-negative")
    if rate > 1:
        return rate / Decimal(100), "percent input divided by 100 because it exceeded 1"
    return rate, "decimal annual rate supplied by caller"


def marginal_return(
    next_dollar: Mapping[str, Any],
    opportunity_cost_rate: Any,
) -> dict[str, Any]:
    """Rank uses by present value of annual NOI lift per invested cent."""

    if not isinstance(next_dollar, Mapping):
        raise ValueError("next_dollar must be a mapping containing options")
    options = next_dollar.get("options")
    if isinstance(options, (str, bytes)) or not isinstance(options, Sequence):
        raise ValueError("next_dollar.options must be a sequence")
    annual_rate, rate_convention = _rate(opportunity_cost_rate)
    ranked: list[dict[str, Any]] = []
    for index, option in enumerate(options):
        if not isinstance(option, Mapping):
            raise ValueError(f"next_dollar.options[{index}] must be a mapping")
        use = str(option.get("use") or "").strip()
        if not use:
            raise ValueError(f"next_dollar.options[{index}].use cannot be blank")
        cost = _cents(
            option.get("cost_cents"),
            name=f"next_dollar.options[{index}].cost_cents",
            non_negative=True,
        )
        if cost == 0:
            raise ValueError(f"next_dollar.options[{index}].cost_cents must be positive")
        noi_delta = _cents(
            option.get("expected_noi_delta_cents"),
            name=f"next_dollar.options[{index}].expected_noi_delta_cents",
        )
        months = option.get("months")
        if isinstance(months, bool) or not isinstance(months, int) or months < 0:
            raise ValueError(
                f"next_dollar.options[{index}].months must be a non-negative integer"
            )
        discount_factor = (Decimal(1) + annual_rate) ** (
            Decimal(months) / Decimal(12)
        )
        pv_decimal = Decimal(noi_delta) / discount_factor
        pv_cents = int(pv_decimal.quantize(Decimal(1), rounding=ROUND_HALF_UP))
        gross_return = Decimal(noi_delta) / Decimal(cost)
        time_adjusted_return = pv_decimal / Decimal(cost)
        net_value = pv_cents - cost
        ranked.append(
            {
                "use": use,
                "cost_cents": cost,
                "expected_noi_delta_cents_annual": noi_delta,
                "months_until_impact": months,
                "discount_factor": float(discount_factor),
                "present_value_noi_delta_cents": pv_cents,
                "gross_marginal_return": float(gross_return),
                "time_adjusted_marginal_return": float(time_adjusted_return),
                "time_adjusted_net_value_cents": net_value,
                "input_position": index,
            }
        )
    ranked.sort(
        key=lambda row: (
            -float(row["time_adjusted_marginal_return"]),
            int(row["months_until_impact"]),
            int(row["input_position"]),
        )
    )
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
        row["recommendation"] = (
            f"Rank {rank}: PV annual NOI lift {row['present_value_noi_delta_cents']} cents "
            f"on {row['cost_cents']} cents invested = "
            f"{row['time_adjusted_marginal_return']:.6f} per invested cent."
        )
        row.pop("input_position")
    return {
        "ranked_options": ranked,
        "opportunity_cost_rate": float(annual_rate),
        "rate_convention": rate_convention,
        "formula": {
            "discount_factor": "(1 + opportunity_cost_rate) ** (months / 12)",
            "present_value_noi_delta_cents": (
                "round(expected_noi_delta_cents / discount_factor)"
            ),
            "time_adjusted_marginal_return": (
                "unrounded present_value_noi_delta_cents / cost_cents"
            ),
            "ranking": "descending time_adjusted_marginal_return; faster impact breaks ties",
        },
        "honest_gaps": [
            "Expected NOI deltas are caller forecasts, not observed returns.",
            "The screen values one annual NOI run-rate and does not assume a holding period or terminal capitalization value.",
        ],
    }


__all__ = ["marginal_return"]
