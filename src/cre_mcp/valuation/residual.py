"""Transparent probability-weighted residual land-value screening.

This is a compact option-style screen for early development programs.  It uses
only the facts in the requested API: quantity, rent, cost, timeline, and three
stated probabilities.  It therefore makes no claim about financing, taxes,
discount rates, cap rates, exit proceeds, or sunk costs after a failed outcome.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any


DISCLAIMER = (
    "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
)
HONESTY = "conventions not predictions"


def _number(
    value: Any,
    label: str,
    *,
    non_negative: bool = True,
    positive: bool = False,
) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    invalid_sign = (non_negative and number < 0) or (positive and number <= 0)
    if not math.isfinite(number) or invalid_sign:
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{label} must be a finite {qualifier} number")
    return number


def _range(value: Any, label: str, *, positive: bool = False) -> dict[str, float]:
    if isinstance(value, Mapping):
        low = _number(value.get("low"), f"{label}.low", positive=positive)
        high = _number(value.get("high"), f"{label}.high", positive=positive)
        base = _number(
            value.get("base", (low + high) / 2),
            f"{label}.base",
            positive=positive,
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
        if len(values) not in {2, 3}:
            raise ValueError(f"{label} sequence must contain two or three values")
        low = _number(values[0], f"{label}[0]", positive=positive)
        high = _number(values[-1], f"{label}[-1]", positive=positive)
        base = (
            _number(values[1], f"{label}[1]", positive=positive)
            if len(values) == 3
            else (low + high) / 2
        )
    else:
        low = high = base = _number(value, label, positive=positive)
    if not low <= base <= high:
        raise ValueError(f"{label} must satisfy low <= base <= high")
    return {"low": low, "base": base, "high": high}


def _probability(value: Any, label: str) -> tuple[float, str, Any]:
    """Normalize decimal or percent notation and retain the stated convention."""

    convention: Any = None
    raw = value
    if isinstance(value, Mapping):
        raw = value.get("probability", value.get("value"))
        convention = value.get("convention", value.get("basis"))
    if raw is None or isinstance(raw, bool):
        raise ValueError(f"{label} must be a decimal or percent probability")
    interpretation: str
    if isinstance(raw, str) and raw.strip().endswith("%"):
        number = _number(raw.strip()[:-1], label) / 100
        interpretation = "percent string divided by 100"
    else:
        number = _number(raw, label)
        if number > 1:
            if number > 100:
                raise ValueError(f"{label} cannot exceed 100%")
            number /= 100
            interpretation = "numeric value above 1 interpreted as percent"
        else:
            interpretation = "numeric value from 0 through 1 interpreted as decimal"
    if not 0 <= number <= 1:
        raise ValueError(f"{label} must be between 0 and 1 or 0% and 100%")
    return number, interpretation, convention


def _money(value: float) -> float:
    return round(value, 2)


def _payoff(
    quantity: float,
    rent: float,
    cost: float,
    timeline: float,
    entitlement: float,
    cost_overrun: float,
    lease_up: float,
) -> float:
    raw_residual = quantity * (rent * timeline - cost)
    joint_probability = entitlement * (1 - cost_overrun) * lease_up
    return max(raw_residual, 0.0) * joint_probability


def risk_adjusted_residual(
    program: Mapping[str, Any] | None,
    probabilities: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a range of convention-weighted residual land values.

    Screening convention: ``rent`` is periodic rent per unit or SF and
    ``timeline`` is the number of matching rent periods. ``cost`` is total cost
    per unit or SF. A positive residual is paid only in the joint outcome where
    entitlement and lease-up succeed and no cost overrun occurs; all other
    outcomes receive zero land payoff.  This makes the result auditable without
    inventing overrun severity or failed-project recoveries.
    """

    try:
        if not isinstance(program, Mapping):
            raise ValueError("program must be a mapping")
        if not isinstance(probabilities, Mapping):
            raise ValueError("probabilities must be a mapping")

        quantity = _number(
            program.get("units_or_sf"), "program.units_or_sf", positive=True
        )
        rent = _range(program.get("rent"), "program.rent")
        cost = _range(program.get("cost"), "program.cost")
        timeline = _range(
            program.get("timeline"), "program.timeline", positive=True
        )
        timeline_unit = str(program.get("timeline_unit") or "stated rent periods").strip()

        entitlement, ent_note, ent_convention = _probability(
            probabilities.get("entitlement"), "probabilities.entitlement"
        )
        cost_overrun, overrun_note, overrun_convention = _probability(
            probabilities.get("cost_overrun"), "probabilities.cost_overrun"
        )
        lease_up, lease_note, lease_convention = _probability(
            probabilities.get("lease_up"), "probabilities.lease_up"
        )
        joint = entitlement * (1 - cost_overrun) * lease_up
        failure = 1 - joint

        gross = {
            "low": quantity * rent["low"] * timeline["low"],
            "base": quantity * rent["base"] * timeline["base"],
            "high": quantity * rent["high"] * timeline["high"],
        }
        total_cost = {
            "low": quantity * cost["low"],
            "base": quantity * cost["base"],
            "high": quantity * cost["high"],
        }
        unadjusted = {
            "low": gross["low"] - total_cost["high"],
            "base": gross["base"] - total_cost["base"],
            "high": gross["high"] - total_cost["low"],
        }
        positive_payoff = {key: max(value, 0.0) for key, value in unadjusted.items()}
        weighted = {key: value * joint for key, value in positive_payoff.items()}

        base_inputs = {
            "rent": rent["base"],
            "cost": cost["base"],
            "timeline": timeline["base"],
            "entitlement": entitlement,
            "cost_overrun": cost_overrun,
            "lease_up": lease_up,
        }

        def evaluate(changes: Mapping[str, float]) -> float:
            values = {**base_inputs, **changes}
            return _payoff(
                quantity,
                values["rent"],
                values["cost"],
                values["timeline"],
                values["entitlement"],
                values["cost_overrun"],
                values["lease_up"],
            )

        tornado: list[dict[str, Any]] = []
        for assumption, low_value, high_value, note in (
            ("rent", rent["low"], rent["high"], "caller-supplied rent range"),
            ("cost", cost["low"], cost["high"], "caller-supplied cost range"),
            (
                "timeline",
                timeline["low"],
                timeline["high"],
                "caller-supplied timeline range",
            ),
        ):
            values = [evaluate({assumption: low_value}), evaluate({assumption: high_value})]
            tornado.append(
                {
                    "assumption": assumption,
                    "one_at_a_time_range": {
                        "low": _money(min(values)),
                        "high": _money(max(values)),
                    },
                    "impact_span": _money(abs(values[1] - values[0])),
                    "test": note,
                }
            )

        baseline = evaluate({})
        for assumption, neutral, note in (
            ("entitlement", 1.0, "set entitlement success to 100%"),
            ("cost_overrun", 0.0, "set cost-overrun probability to 0%"),
            ("lease_up", 1.0, "set lease-up success to 100%"),
        ):
            neutral_value = evaluate({assumption: neutral})
            values = (baseline, neutral_value)
            tornado.append(
                {
                    "assumption": assumption,
                    "one_at_a_time_range": {
                        "low": _money(min(values)),
                        "high": _money(max(values)),
                    },
                    "impact_span": _money(abs(neutral_value - baseline)),
                    "test": note,
                }
            )
        tornado.sort(key=lambda item: (-float(item["impact_span"]), item["assumption"]))
        for rank, item in enumerate(tornado, start=1):
            item["rank"] = rank

        normalized_probabilities = {
            "entitlement": entitlement,
            "cost_overrun": cost_overrun,
            "lease_up": lease_up,
        }
        probability_conventions = {
            "entitlement": {
                "normalized": entitlement,
                "input_interpretation": ent_note,
                "stated_convention": ent_convention,
            },
            "cost_overrun": {
                "normalized": cost_overrun,
                "input_interpretation": overrun_note,
                "stated_convention": overrun_convention,
            },
            "lease_up": {
                "normalized": lease_up,
                "input_interpretation": lease_note,
                "stated_convention": lease_convention,
            },
        }
        weighted_range = {key: _money(value) for key, value in weighted.items()}
        return {
            "status": "ANALYTICAL_ESTIMATE",
            "disclaimer": DISCLAIMER,
            "honesty": HONESTY,
            "convention_warning": (
                "These probabilities and zero-payoff failure cases are conventions not predictions."
            ),
            "program": {
                "units_or_sf": quantity,
                "rent_range": rent,
                "cost_range": cost,
                "timeline_range": timeline,
                "timeline_unit": timeline_unit,
            },
            "probabilities": normalized_probabilities,
            "probability_conventions": probability_conventions,
            "probability_math": {
                "joint_success_formula": (
                    "entitlement * (1 - cost_overrun) * lease_up"
                ),
                "joint_success_probability": joint,
                "other_outcomes_probability": failure,
                "probability_sum": joint + failure,
                "sum_check": math.isclose(joint + failure, 1.0, abs_tol=1e-12),
                "failure_land_payoff": 0.0,
            },
            "gross_rent_over_timeline_range": {
                key: _money(value) for key, value in gross.items()
            },
            "development_cost_range": {
                key: _money(value) for key, value in total_cost.items()
            },
            "unadjusted_residual_range": {
                key: _money(value) for key, value in unadjusted.items()
            },
            "positive_land_payoff_range": {
                key: _money(value) for key, value in positive_payoff.items()
            },
            "probability_weighted_residual_land_value_range": weighted_range,
            "risk_adjusted_residual_range": weighted_range,
            "component_sum": {
                key: {
                    "joint_success_contribution": _money(weighted[key]),
                    "other_outcomes_contribution": 0.0,
                    "total": _money(weighted[key]),
                }
                for key in ("low", "base", "high")
            },
            "tornado_lite": tornado,
            "dominant_assumption": tornado[0]["assumption"] if tornado else None,
            "method": (
                "Unadjusted residual = units_or_sf * "
                "(periodic rent * timeline periods - total cost per unit_or_sf). "
                "Positive residual is multiplied by entitlement * "
                "(1 - cost_overrun) * lease_up; all other outcomes have a $0 land payoff."
            ),
            "unmodeled_items": [
                "operating expenses and vacancy beyond the lease-up probability",
                "cap/exit rate and terminal sale proceeds",
                "financing, taxes, and discounting",
                "cost-overrun severity and failed-project recovery or sunk costs",
            ],
        }
    except Exception as exc:
        return {"error": f"risk_adjusted_residual: {exc}"}


__all__ = ["risk_adjusted_residual"]
