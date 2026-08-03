"""Utility-bill anomaly analysis and convention-based retrofit screening.

The calculations in this module use only the supplied bills.  In particular,
the rate effect is based on the *blended* cents-per-unit visible in each bill;
without a tariff schedule it must not be described as a verified tariff change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
import re
from typing import Any


DEFAULT_SPIKE_THRESHOLD_PCT = Decimal("25")
DEFAULT_RECONCILIATION_TOLERANCE_PCT = Decimal("5")


def _decimal(
    value: Any,
    label: str,
    *,
    allow_zero: bool = True,
) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite non-negative number")
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a finite non-negative number") from exc
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        qualifier = "positive" if not allow_zero else "non-negative"
        raise ValueError(f"{label} must be a finite {qualifier} number")
    return number


def _json_number(value: Decimal | None) -> int | float | None:
    """Return a JSON-friendly number without discarding exact whole cents."""

    if value is None:
        return None
    integral = value.to_integral_value()
    if value == integral:
        return int(integral)
    return float(value)


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return numerator / denominator * Decimal("100")


def _meter_role(row: Mapping[str, Any], meter: str) -> tuple[str | None, str]:
    """Read an explicit role first, then use a documented meter-name fallback."""

    for field in ("meter_role", "role", "meter_type"):
        raw = row.get(field)
        if raw in (None, ""):
            continue
        normalized = re.sub(r"[^a-z]+", "", str(raw).casefold())
        if normalized in {"master", "main", "wholebuilding"}:
            return "master", f"explicit {field}"
        if normalized in {"submeter", "sub", "tenant"}:
            return "submeter", f"explicit {field}"

    normalized_meter = re.sub(r"[^a-z0-9]+", " ", meter.casefold()).strip()
    words = set(normalized_meter.split())
    if "master" in words or "main" in words:
        return "master", "meter-name convention"
    if "submeter" in words or "sub" in words or normalized_meter.startswith("submeter"):
        return "submeter", "meter-name convention"
    return None, "unclassified"


def _driver(
    amount_delta: Decimal,
    usage_effect: Decimal,
    rate_effect: Decimal,
) -> tuple[str, str]:
    if amount_delta <= 0:
        return "bill_not_up", "Bill did not increase from the comparison period."
    positive_usage = max(usage_effect, Decimal("0"))
    positive_rate = max(rate_effect, Decimal("0"))
    if positive_usage == positive_rate and positive_usage > 0:
        return "mixed", "Positive usage and blended-rate effects were equal."
    if positive_usage > positive_rate:
        return "usage", "The positive usage effect was larger than the positive blended-rate effect."
    if positive_rate > positive_usage:
        return (
            "tariff_or_rate",
            "The positive blended-rate effect was larger; tariff verification requires the rate schedule.",
        )
    return "unresolved", "The supplied arithmetic does not isolate a positive driver."


def utility_anomalies(
    bills: Sequence[Mapping[str, Any]] | None,
    spike_threshold_pct: float | None = None,
    reconciliation_tolerance_pct: float | None = None,
) -> dict[str, Any]:
    """Analyze usage intensity, spikes, bill drivers, and meter reconciliation.

    A spike is a period-over-period usage increase greater than or equal to the
    exposed percentage threshold.  Rate/usage decomposition uses the exact
    identity::

        bill change = (usage change * prior blended rate)
                    + (current usage * blended-rate change)

    ``meter_role``/``role``/``meter_type`` may identify ``master`` and
    ``submeter`` rows.  If absent, meter names containing ``master``/``main``
    or ``submeter``/``sub`` are used as an explicitly reported convention.
    """

    try:
        if bills is None or isinstance(bills, (str, bytes, Mapping)):
            raise ValueError("bills must be a sequence of bill mappings")
        spike_threshold = (
            DEFAULT_SPIKE_THRESHOLD_PCT
            if spike_threshold_pct is None
            else _decimal(spike_threshold_pct, "spike_threshold_pct")
        )
        reconciliation_tolerance = (
            DEFAULT_RECONCILIATION_TOLERANCE_PCT
            if reconciliation_tolerance_pct is None
            else _decimal(
                reconciliation_tolerance_pct,
                "reconciliation_tolerance_pct",
            )
        )

        normalized: list[dict[str, Any]] = []
        internal: list[dict[str, Any]] = []
        for index, row in enumerate(bills):
            if not isinstance(row, Mapping):
                raise ValueError(f"bills[{index}] must be a mapping")
            period = str(row.get("period") or "").strip()
            meter = str(row.get("meter") or "").strip()
            if not period:
                raise ValueError(f"bills[{index}].period must be non-empty")
            if not meter:
                raise ValueError(f"bills[{index}].meter must be non-empty")
            usage = _decimal(row.get("kwh_or_unit"), f"bills[{index}].kwh_or_unit")
            amount = _decimal(row.get("amount_cents"), f"bills[{index}].amount_cents")
            if amount != amount.to_integral_value():
                raise ValueError(f"bills[{index}].amount_cents must be whole cents")
            sf_raw = row.get("sf")
            sf = (
                None
                if sf_raw in (None, "")
                else _decimal(sf_raw, f"bills[{index}].sf", allow_zero=False)
            )
            role, role_basis = _meter_role(row, meter)
            rate = amount / usage if usage else None
            usage_per_sf = usage / sf if sf is not None else None
            public_row = {
                "period": period,
                "meter": meter,
                "kwh_or_unit": _json_number(usage),
                "amount_cents": int(amount),
                "sf": _json_number(sf),
                "usage_per_sf": _json_number(usage_per_sf),
                "blended_rate_cents_per_unit": _json_number(rate),
                "meter_role": role,
                "meter_role_basis": role_basis,
            }
            normalized.append(public_row)
            internal.append(
                {
                    "index": index,
                    "period": period,
                    "meter": meter,
                    "usage": usage,
                    "amount": amount,
                    "sf": sf,
                    "usage_per_sf": usage_per_sf,
                    "rate": rate,
                    "role": role,
                    "role_basis": role_basis,
                }
            )

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in internal:
            grouped.setdefault(str(row["meter"]), []).append(row)

        trends: list[dict[str, Any]] = []
        comparisons: list[dict[str, Any]] = []
        spikes: list[dict[str, Any]] = []
        for meter, rows in sorted(grouped.items()):
            rows.sort(key=lambda item: (str(item["period"]), int(item["index"])))
            observations = [
                {
                    "period": row["period"],
                    "usage": _json_number(row["usage"]),
                    "sf": _json_number(row["sf"]),
                    "usage_per_sf": _json_number(row["usage_per_sf"]),
                }
                for row in rows
            ]
            trends.append(
                {
                    "meter": meter,
                    "metric": "kwh_or_unit per supplied square foot",
                    "observations": observations,
                    "trend_status": (
                        "AVAILABLE"
                        if any(row["usage_per_sf"] is not None for row in rows)
                        else "SF_NOT_PROVIDED"
                    ),
                }
            )
            for previous, current in zip(rows, rows[1:]):
                usage_delta = current["usage"] - previous["usage"]
                amount_delta = current["amount"] - previous["amount"]
                usage_change_pct = _percent(usage_delta, previous["usage"])
                is_spike = (
                    current["usage"] > 0
                    if previous["usage"] == 0
                    else usage_delta > 0 and usage_change_pct >= spike_threshold
                )
                comparison: dict[str, Any] = {
                    "meter": meter,
                    "prior_period": previous["period"],
                    "current_period": current["period"],
                    "prior_usage": _json_number(previous["usage"]),
                    "current_usage": _json_number(current["usage"]),
                    "usage_delta": _json_number(usage_delta),
                    "usage_change_pct": _json_number(usage_change_pct),
                    "amount_delta_cents": int(amount_delta),
                    "spike": is_spike,
                    "spike_threshold_pct": _json_number(spike_threshold),
                }
                if previous["rate"] is None or current["rate"] is None:
                    comparison.update(
                        {
                            "decomposition_status": "UNKNOWN_ZERO_USAGE",
                            "prior_blended_rate_cents_per_unit": _json_number(previous["rate"]),
                            "current_blended_rate_cents_per_unit": _json_number(current["rate"]),
                            "usage_effect_cents": None,
                            "rate_effect_cents": None,
                            "tariff_effect_cents": None,
                            "explained_change_cents": None,
                            "reconciliation_difference_cents": None,
                            "primary_driver": "unresolved",
                        }
                    )
                else:
                    usage_effect = usage_delta * previous["rate"]
                    # Algebraically this is current usage x blended-rate change.
                    # Deriving it as the exact residual prevents repeating decimal
                    # rates (for example 100 cents / 3 units) from leaving a tiny
                    # Decimal context-rounding remainder in the cent identity.
                    rate_effect = amount_delta - usage_effect
                    explained = usage_effect + rate_effect
                    difference = amount_delta - explained
                    primary_driver, explanation = _driver(
                        amount_delta,
                        usage_effect,
                        rate_effect,
                    )
                    comparison.update(
                        {
                            "decomposition_status": "AVAILABLE",
                            "prior_blended_rate_cents_per_unit": _json_number(previous["rate"]),
                            "current_blended_rate_cents_per_unit": _json_number(current["rate"]),
                            "usage_effect_cents": _json_number(usage_effect),
                            "rate_effect_cents": _json_number(rate_effect),
                            "tariff_effect_cents": _json_number(rate_effect),
                            "explained_change_cents": _json_number(explained),
                            "reconciliation_difference_cents": _json_number(difference),
                            "reconciles_exactly": difference == 0,
                            "primary_driver": primary_driver,
                            "driver_explanation": explanation,
                        }
                    )
                comparisons.append(comparison)
                if is_spike:
                    spikes.append(
                        {
                            "meter": meter,
                            "prior_period": previous["period"],
                            "current_period": current["period"],
                            "prior_usage": _json_number(previous["usage"]),
                            "current_usage": _json_number(current["usage"]),
                            "usage_change_pct": _json_number(usage_change_pct),
                            "threshold_pct": _json_number(spike_threshold),
                            "reason": (
                                "Usage rose from zero; percent change is undefined."
                                if previous["usage"] == 0
                                else "Usage increase met or exceeded the exposed threshold."
                            ),
                        }
                    )

        reconciliation: list[dict[str, Any]] = []
        period_rows: dict[str, list[dict[str, Any]]] = {}
        for row in internal:
            period_rows.setdefault(str(row["period"]), []).append(row)
        for period, rows in sorted(period_rows.items()):
            masters = [row for row in rows if row["role"] == "master"]
            submeters = [row for row in rows if row["role"] == "submeter"]
            if not masters or not submeters:
                continue
            master_usage = sum((row["usage"] for row in masters), Decimal("0"))
            submeter_usage = sum((row["usage"] for row in submeters), Decimal("0"))
            variance = master_usage - submeter_usage
            variance_pct = _percent(abs(variance), master_usage)
            reconciliation.append(
                {
                    "period": period,
                    "master_meters": [row["meter"] for row in masters],
                    "submeters": [row["meter"] for row in submeters],
                    "master_usage": _json_number(master_usage),
                    "submeter_usage_total": _json_number(submeter_usage),
                    "unreconciled_usage": _json_number(variance),
                    "variance_units": _json_number(variance),
                    "absolute_variance_pct_of_master": _json_number(variance_pct),
                    "tolerance_pct": _json_number(reconciliation_tolerance),
                    "within_tolerance": (
                        variance == 0
                        if variance_pct is None
                        else variance_pct <= reconciliation_tolerance
                    ),
                }
            )

        conventions = {
            "usage_spike": {
                "threshold_pct": _json_number(spike_threshold),
                "comparison": "current usage versus immediately prior supplied period for the same meter",
                "trigger": "increase greater than or equal to threshold; any positive usage after zero is flagged",
            },
            "rate_vs_usage": {
                "formula": "amount change = (usage change x prior blended rate) + (current usage x blended-rate change)",
                "rate_warning": "Blended-rate movement can reflect tariff, fixed charges, taxes, demand charges, or data mix; tariff causation is not verified.",
            },
            "submeter_reconciliation": {
                "tolerance_pct": _json_number(reconciliation_tolerance),
                "basis": "absolute master-minus-submeter usage divided by master usage",
                "role_identification": "explicit meter_role/role/meter_type, then documented meter-name fallback",
            },
        }
        return {
            "status": "ANALYTICAL_SCREEN",
            "bills": normalized,
            "threshold_conventions": conventions,
            "conventions": conventions,
            "usage_per_sf_trends": trends,
            "meter_trends": trends,
            "spikes": spikes,
            "rate_vs_usage_decomposition": comparisons,
            "submeter_reconciliation": reconciliation,
            "submeter_master_reconciliation": reconciliation,
            "honesty": (
                "Results are arithmetic screens from supplied bills, not a tariff audit, "
                "engineering analysis, or assurance that all submeters were supplied."
            ),
        }
    except Exception as exc:
        return {"error": f"utility_anomalies: {exc}"}


def _range(
    value: Any,
    low_value: Any,
    high_value: Any,
    label: str,
) -> tuple[Decimal, Decimal]:
    if value is not None:
        if isinstance(value, Mapping):
            low = _decimal(value.get("low"), f"{label}.low")
            high = _decimal(value.get("high"), f"{label}.high")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            values = list(value)
            if len(values) != 2:
                raise ValueError(f"{label} sequence must contain [low, high]")
            low = _decimal(values[0], f"{label}[0]")
            high = _decimal(values[1], f"{label}[1]")
        else:
            low = high = _decimal(value, label)
    else:
        low = _decimal(low_value, f"{label}_low")
        high = _decimal(high_value, f"{label}_high")
    if low > high:
        raise ValueError(f"{label} must satisfy low <= high")
    return low, high


def retrofit_screen(
    usage: Mapping[str, Any] | int | float | None,
    measures: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Return convention-labeled simple-payback ranges for retrofit measures.

    ``usage`` may be an annual-usage scalar or a mapping with ``annual_usage``
    (``annual_kwh`` is an alias), plus either ``annual_cost_cents`` or
    ``unit_rate_cents_per_unit``.  Each measure supplies ``cost_cents`` and
    either ``annual_savings_cents`` or ``savings_pct`` as a scalar, ``[low,
    high]``, or ``{"low": ..., "high": ...}``.
    """

    try:
        if usage is None:
            raise ValueError("usage is required")
        if isinstance(usage, Mapping):
            annual_usage_raw = usage.get("annual_usage", usage.get("annual_kwh"))
            annual_usage = _decimal(annual_usage_raw, "usage.annual_usage")
            annual_cost_raw = usage.get("annual_cost_cents")
            if annual_cost_raw in (None, ""):
                unit_rate_raw = usage.get("unit_rate_cents_per_unit")
                annual_cost = (
                    None
                    if unit_rate_raw in (None, "")
                    else annual_usage
                    * _decimal(unit_rate_raw, "usage.unit_rate_cents_per_unit")
                )
            else:
                annual_cost = _decimal(annual_cost_raw, "usage.annual_cost_cents")
        else:
            annual_usage = _decimal(usage, "usage")
            annual_cost = None
        if measures is None or isinstance(measures, (str, bytes, Mapping)):
            raise ValueError("measures must be a sequence of measure mappings")

        screened: list[dict[str, Any]] = []
        for index, measure in enumerate(measures):
            if not isinstance(measure, Mapping):
                raise ValueError(f"measures[{index}] must be a mapping")
            name = str(measure.get("name") or "").strip()
            if not name:
                raise ValueError(f"measures[{index}].name must be non-empty")
            cost_low, cost_high = _range(
                measure.get("cost_cents"),
                measure.get("cost_cents_low"),
                measure.get("cost_cents_high"),
                f"measures[{index}].cost_cents",
            )
            savings_cents_value = measure.get("annual_savings_cents")
            if savings_cents_value is not None or (
                measure.get("annual_savings_cents_low") is not None
                and measure.get("annual_savings_cents_high") is not None
            ):
                savings_low, savings_high = _range(
                    savings_cents_value,
                    measure.get("annual_savings_cents_low"),
                    measure.get("annual_savings_cents_high"),
                    f"measures[{index}].annual_savings_cents",
                )
                savings_pct_low = savings_pct_high = None
            else:
                if annual_cost is None:
                    raise ValueError(
                        f"measures[{index}] needs annual_savings_cents because usage has no annual cost/rate"
                    )
                savings_pct_low, savings_pct_high = _range(
                    measure.get("savings_pct"),
                    measure.get("savings_pct_low"),
                    measure.get("savings_pct_high"),
                    f"measures[{index}].savings_pct",
                )
                savings_low = annual_cost * savings_pct_low / Decimal("100")
                savings_high = annual_cost * savings_pct_high / Decimal("100")

            payback_low = cost_low / savings_high if savings_high > 0 else None
            payback_high = cost_high / savings_low if savings_low > 0 else None
            screened.append(
                {
                    "name": name,
                    "cost_range_cents": {
                        "low": _json_number(cost_low),
                        "high": _json_number(cost_high),
                    },
                    "annual_savings_range_cents": {
                        "low": _json_number(savings_low),
                        "high": _json_number(savings_high),
                    },
                    "savings_pct_range": (
                        None
                        if savings_pct_low is None
                        else {
                            "low": _json_number(savings_pct_low),
                            "high": _json_number(savings_pct_high),
                        }
                    ),
                    "simple_payback_years": {
                        "low": None if payback_low is None else round(float(payback_low), 2),
                        "high": None if payback_high is None else round(float(payback_high), 2),
                    },
                    "payback_range_label": (
                        "CONVENTION: optimistic = low cost / high annual savings; "
                        "conservative = high cost / low annual savings"
                    ),
                }
            )

        return {
            "status": "CONVENTION_BASED_SCREEN",
            "annual_usage": _json_number(annual_usage),
            "annual_cost_cents": _json_number(annual_cost),
            "measures": screened,
            "catalog_conventions": {
                "costs": "Supplied catalog ranges; incentives, escalation, financing, and soft costs are included only if the catalog includes them.",
                "savings": "Supplied annual savings or supplied percentage of annual blended utility cost; interactive measure effects are not modeled.",
                "payback": "Simple payback only: optimistic low cost/high savings through conservative high cost/low savings.",
            },
            "honesty": (
                "CONVENTION-BASED PRELIMINARY SCREEN; an energy engineer and current "
                "vendor pricing are required before investment or compliance decisions."
            ),
        }
    except Exception as exc:
        return {"error": f"retrofit_screen: {exc}"}


__all__ = ["retrofit_screen", "utility_anomalies"]
