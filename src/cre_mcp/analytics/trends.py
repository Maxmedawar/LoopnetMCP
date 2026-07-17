"""Honest historical-trend extrapolation with residual-spread bands.

The output of this module is deliberately not called a forecast.  It extends
an ordinary least-squares line fitted to the supplied observations and places
one historical residual root-mean-square on either side.  The bands therefore
describe only the variability observed around that line; they do not estimate
future uncertainty or the probability of future outcomes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


HONESTY_NOTICE = (
    "extrapolation of history, NOT a forecast; bands show past variability only."
)


def _decimal(value: Any, label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be a finite number")
    return result


def _json_number(value: Decimal) -> int | float:
    integral = value.to_integral_value()
    if value == integral:
        return int(integral)
    return float(value)


def _future_period(periods: list[Any], step: int) -> Any:
    """Extend plainly numeric periods; label every other period explicitly."""

    if len(periods) >= 2:
        last = periods[-1]
        previous = periods[-2]
        if (
            isinstance(last, (int, float, Decimal))
            and not isinstance(last, bool)
            and isinstance(previous, (int, float, Decimal))
            and not isinstance(previous, bool)
        ):
            last_number = Decimal(str(last))
            spacing = last_number - Decimal(str(previous))
            projected = last_number + spacing * step
            return _json_number(projected)
    return f"future_{step}"


def trend_bands(
    series: Sequence[Mapping[str, Any]] | None,
    horizon: int | None,
) -> dict[str, Any]:
    """Extend a simple historical trend subject to a conservative horizon gate.

    ``horizon`` must not exceed half the number of supplied observations.  Each
    returned band is the fitted/extrapolated line plus or minus one in-sample
    residual root-mean-square.  This deliberately simple band is not a
    confidence interval, prediction interval, scenario distribution, or market
    forecast.
    """

    try:
        if series is None or isinstance(series, (str, bytes, Mapping)):
            raise ValueError("series must be a sequence of {period, value} mappings")
        if horizon is None or isinstance(horizon, bool) or not isinstance(horizon, int):
            raise ValueError("horizon must be a non-negative integer")
        if horizon < 0:
            raise ValueError("horizon must be a non-negative integer")
        if len(series) < 2:
            raise ValueError("series must contain at least two observations")

        history_count = len(series)
        values: list[Decimal] = []
        periods: list[Any] = []
        unrecognized: list[str] = []
        for index, row in enumerate(series):
            if not isinstance(row, Mapping):
                raise ValueError(f"series[{index}] must be a mapping")
            extras = sorted(str(key) for key in row if key not in {"period", "value"})
            unrecognized.extend(f"series[{index}].{field}" for field in extras)
            if "period" not in row or row.get("period") is None:
                raise ValueError(f"series[{index}].period is required and cannot be null")
            period = row.get("period")
            if isinstance(period, str) and not period.strip():
                raise ValueError(f"series[{index}].period cannot be blank")
            periods.append(period)
            values.append(_decimal(row.get("value"), f"series[{index}].value"))

        if horizon * 2 > history_count:
            return {
                "error": (
                    "trend_bands: horizon refused because it exceeds half the "
                    "history length"
                ),
                "status": "REFUSED_HORIZON_TOO_LONG",
                "history_count": history_count,
                "requested_horizon": horizon,
                "maximum_horizon": history_count // 2,
                "reason": (
                    "A simple line should not be extended more than half the "
                    "observed history; add history or shorten the horizon."
                ),
                "unrecognized_inputs": sorted(set(unrecognized)),
                "honesty": HONESTY_NOTICE,
            }

        n = Decimal(history_count)
        x_mean = Decimal(history_count - 1) / Decimal("2")
        y_mean = sum(values, Decimal("0")) / n
        denominator = sum(
            ((Decimal(index) - x_mean) ** 2 for index in range(history_count)),
            Decimal("0"),
        )
        slope = (
            sum(
                (
                    (Decimal(index) - x_mean) * (value - y_mean)
                    for index, value in enumerate(values)
                ),
                Decimal("0"),
            )
            / denominator
        )
        intercept = y_mean - slope * x_mean
        fitted = [intercept + slope * Decimal(index) for index in range(history_count)]
        residuals = [value - fit for value, fit in zip(values, fitted, strict=True)]
        with localcontext() as context:
            context.prec = 28
            residual_spread = (
                sum((residual**2 for residual in residuals), Decimal("0")) / n
            ).sqrt()

        history = [
            {
                "period": periods[index],
                "value": _json_number(values[index]),
                "fitted_trend": _json_number(fitted[index]),
                "residual": _json_number(residuals[index]),
            }
            for index in range(history_count)
        ]
        extrapolation = []
        for step in range(1, horizon + 1):
            center = intercept + slope * Decimal(history_count - 1 + step)
            extrapolation.append(
                {
                    "step": step,
                    "period": _future_period(periods, step),
                    "trend": _json_number(center),
                    "lower_band": _json_number(center - residual_spread),
                    "upper_band": _json_number(center + residual_spread),
                }
            )

        return {
            "status": "HISTORICAL_EXTRAPOLATION",
            "history_count": history_count,
            "horizon": horizon,
            "trend": {
                "intercept_at_first_observation": _json_number(intercept),
                "slope_per_period": _json_number(slope),
            },
            "residual_spread": _json_number(residual_spread),
            "band_method": (
                "trend plus/minus one in-sample residual root-mean-square; "
                "descriptive only, with no coverage probability"
            ),
            "history": history,
            "extrapolation": extrapolation,
            "projections": extrapolation,
            "bands": extrapolation,
            "unrecognized_inputs": sorted(set(unrecognized)),
            "honesty": HONESTY_NOTICE,
        }
    except Exception as exc:
        result: dict[str, Any] = {"error": f"trend_bands: {exc}"}
        if "unrecognized" in locals() and unrecognized:
            result["unrecognized_inputs"] = sorted(set(unrecognized))
        return result


__all__ = ["HONESTY_NOTICE", "trend_bands"]
