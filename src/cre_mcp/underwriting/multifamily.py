"""Multifamily income build-up from a rent roll, with a no-invention contract.

The engine could not underwrite a multifamily listing that carried a unit count
and an average rent but no stated gross potential rent — which is most of them.
`underwrite_listing` requires `gross_potential_rent` on the listing, and there
was no path from units and rent to it, so those deals returned `None`.

Two things follow from closing that gap, and the second is the point of this
module.

The first is arithmetic, and it is the conventional five lines:

    annual income  = units × rent per unit × 12 × occupancy
    other income   = annual income × other income %
    gross income   = annual income + other income
    expenses       = gross income × expense %
    NOI            = gross income − expenses

Note where the expense percentage lands: on gross income, *after* vacancy.
`metrics.net_operating_income` applied it to pre-vacancy GPR, which overstates
expenses and understates NOI by the vacancy fraction of the ratio — about 6% of
NOI at 5% vacancy and a 40% ratio. This module is the correct convention and
`metrics.py` was corrected to match it.

The second is the contract. A missing input must reach the model as a refusal
it cannot paper over, because the failure mode is not a wrong number — it is a
*plausible* one. An agent handed `None` will reach for a market average, and a
market average presented as this property's rent is indistinguishable from a
real figure to the person acting on it.

So this returns one of two shapes and never a partial number:

  * `status="OK"` with the figures, plus `assumed_inputs` naming every value
    that came from a default rather than from the caller. An assumption is not
    a blocker, but it is never silent.
  * `status="NEEDS_INPUT"` with `missing_inputs`, and for each one a
    `resolution` saying whether to ask the operator or which document answers
    it. No figures at all — not even the ones that were computable — because a
    partially-filled result is the thing an agent completes from memory.
"""

from __future__ import annotations

import math
from typing import Any

#: What answers each input, in the words the agent should use. "ask" means the
#: operator knows it; a document name means it is on paper and should be read
#: rather than guessed.
INPUT_RESOLUTIONS: dict[str, str] = {
    "units": (
        "ask the operator for the unit count, or read it from the offering "
        "memorandum or the county assessor record"
    ),
    "rent_per_unit_month": (
        "read the average in-place monthly rent from the rent roll or T-12; "
        "ask the operator if neither is available. Do not substitute a market "
        "average — that is a different number and it belongs in the "
        "stabilized case, not here"
    ),
    "occupancy_pct": (
        "read current physical occupancy from the rent roll; ask the operator "
        "if it is not stated"
    ),
    "expense_pct": (
        "compute it from the T-12 operating statement, or ask the operator. "
        "The default below is a screening ratio, not this property's expenses"
    ),
    "cap_rate_pct": (
        "ask the operator which cap rate they are underwriting to, or use "
        "get_comps for recent closed sales in this submarket"
    ),
    "stabilized_rent_per_unit_month": (
        "ask the operator for the post-renovation rent they underwrite, or "
        "use get_rent_comparables for the submarket"
    ),
    "renovation_capex": (
        "ask the operator for the total renovation budget; it is required "
        "before a value-add deal can be priced on yield-on-cost"
    ),
}

#: Screening defaults. Every one of these is reported in `assumed_inputs` when
#: it is used, with the instruction to replace it. None of them is applied to a
#: field the caller must supply.
DEFAULT_OTHER_INCOME_PCT = 0.0
DEFAULT_EXPENSE_PCT = 40.0
DEFAULT_OCCUPANCY_PCT = 95.0

_REQUIRED = ("units", "rent_per_unit_month")


class MultifamilyInputError(ValueError):
    """An input was supplied but is not a usable number."""


def _number(value: Any, field: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MultifamilyInputError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise MultifamilyInputError(f"{field} must be a finite number")
    if not minimum <= number <= maximum:
        raise MultifamilyInputError(
            f"{field} must be between {minimum:g} and {maximum:g}"
        )
    return number


def _needs_input(missing: list[str]) -> dict[str, Any]:
    return {
        "status": "NEEDS_INPUT",
        "missing_inputs": missing,
        "resolution": {name: INPUT_RESOLUTIONS[name] for name in missing},
        "instruction": (
            "Ask the operator for these values or read them from the named "
            "document. Do not estimate them, and do not carry a market average "
            "in as though it were this property's figure."
        ),
    }


def multifamily_income(
    *,
    units: Any = None,
    rent_per_unit_month: Any = None,
    occupancy_pct: Any = None,
    other_income_pct: Any = None,
    expense_pct: Any = None,
) -> dict[str, Any]:
    """Build annual income through NOI from a rent roll, or refuse and say why."""
    missing = [
        name
        for name, value in (
            ("units", units),
            ("rent_per_unit_month", rent_per_unit_month),
        )
        if value is None
    ]
    if missing:
        return _needs_input(missing)

    unit_count = _number(units, "units", minimum=1, maximum=100_000)
    if unit_count != int(unit_count):
        raise MultifamilyInputError("units must be a whole number")
    rent = _number(
        rent_per_unit_month, "rent_per_unit_month", minimum=0, maximum=1_000_000
    )

    assumed: dict[str, Any] = {}
    if occupancy_pct is None:
        occupancy = DEFAULT_OCCUPANCY_PCT
        assumed["occupancy_pct"] = {
            "value": occupancy,
            "resolution": INPUT_RESOLUTIONS["occupancy_pct"],
        }
    else:
        occupancy = _number(occupancy_pct, "occupancy_pct", minimum=0, maximum=100)
    if other_income_pct is None:
        other_pct = DEFAULT_OTHER_INCOME_PCT
        assumed["other_income_pct"] = {
            "value": other_pct,
            "resolution": (
                "zero is assumed rather than estimated; supply the real figure "
                "from the T-12 if this property has laundry, parking, RUBS or "
                "fee income"
            ),
        }
    else:
        other_pct = _number(other_income_pct, "other_income_pct", minimum=0, maximum=100)
    if expense_pct is None:
        expenses_pct = DEFAULT_EXPENSE_PCT
        assumed["expense_pct"] = {
            "value": expenses_pct,
            "resolution": INPUT_RESOLUTIONS["expense_pct"],
        }
    else:
        expenses_pct = _number(expense_pct, "expense_pct", minimum=0, maximum=100)

    gross_potential_rent = unit_count * rent * 12
    annual_income = gross_potential_rent * (occupancy / 100)
    other_income = annual_income * (other_pct / 100)
    gross_income = annual_income + other_income
    operating_expenses = gross_income * (expenses_pct / 100)
    net_operating_income = gross_income - operating_expenses

    return {
        "status": "OK",
        "gross_potential_rent": gross_potential_rent,
        "annual_income": annual_income,
        "other_income": other_income,
        "gross_income": gross_income,
        "operating_expenses": operating_expenses,
        "noi": net_operating_income,
        "inputs_used": {
            "units": int(unit_count),
            "rent_per_unit_month": rent,
            "occupancy_pct": occupancy,
            "other_income_pct": other_pct,
            "expense_pct": expenses_pct,
        },
        "assumed_inputs": assumed,
        "formulas": {
            "annual_income": "units × rent_per_unit_month × 12 × occupancy%",
            "other_income": "annual_income × other_income%",
            "gross_income": "annual_income + other_income",
            "operating_expenses": "gross_income × expense%",
            "noi": "gross_income − operating_expenses",
        },
    }


def multifamily_offer_inputs(
    *,
    units: Any = None,
    rent_per_unit_month: Any = None,
    occupancy_pct: Any = None,
    other_income_pct: Any = None,
    expense_pct: Any = None,
    cap_rate_pct: Any = None,
    stabilized_rent_per_unit_month: Any = None,
    renovation_capex: Any = None,
) -> dict[str, Any]:
    """Add the naive cap-rate price, and say plainly what it is not.

    `NOI ÷ cap` answers "what price yields this cap rate". It is not an offer:
    it takes no account of the ask, of closed comparable sales, or of whether
    the deal carries its own debt. `execution.offer.recommend_offer` is what
    produces an open/target/walk band, and this result is one of its inputs.

    Occupancy well below stabilized is the case this matters most for. Pricing
    a 80%-occupied property off current NOI prices the problem rather than the
    property, so when the stabilized inputs are absent they are reported as
    missing for the value-add path rather than quietly skipped.
    """
    income = multifamily_income(
        units=units,
        rent_per_unit_month=rent_per_unit_month,
        occupancy_pct=occupancy_pct,
        other_income_pct=other_income_pct,
        expense_pct=expense_pct,
    )
    if income["status"] != "OK":
        return income
    if cap_rate_pct is None:
        return _needs_input(["cap_rate_pct"])
    cap = _number(cap_rate_pct, "cap_rate_pct", minimum=0.01, maximum=100)

    price_at_cap = income["noi"] / (cap / 100)
    result = dict(income)
    result["cap_rate_pct"] = cap
    result["price_at_cap_rate"] = price_at_cap
    result["formulas"] = {
        **income["formulas"],
        "price_at_cap_rate": "noi ÷ cap_rate%",
    }
    result["not_an_offer"] = (
        "price_at_cap_rate is the price at which this NOI yields the cap rate "
        "supplied. It is not an offer: it ignores the asking price, closed "
        "comparable sales, and whether the deal services its own debt. Pass "
        "these figures to the offer engine for an open/target/walk band."
    )

    occupancy = income["inputs_used"]["occupancy_pct"]
    value_add_missing = [
        name
        for name, value in (
            ("stabilized_rent_per_unit_month", stabilized_rent_per_unit_month),
            ("renovation_capex", renovation_capex),
        )
        if value is None
    ]
    if occupancy < 90 and value_add_missing:
        result["value_add_note"] = {
            "reason": (
                f"occupancy is {occupancy:g}%, which is a value-add profile "
                "rather than a stabilized one. Pricing it off current NOI "
                "prices the vacancy, not the property"
            ),
            "missing_inputs": value_add_missing,
            "resolution": {
                name: INPUT_RESOLUTIONS[name] for name in value_add_missing
            },
        }
    elif not value_add_missing:
        stabilized_rent = _number(
            stabilized_rent_per_unit_month,
            "stabilized_rent_per_unit_month",
            minimum=0,
            maximum=1_000_000,
        )
        capex = _number(
            renovation_capex, "renovation_capex", minimum=0, maximum=1_000_000_000
        )
        stabilized = multifamily_income(
            units=income["inputs_used"]["units"],
            rent_per_unit_month=stabilized_rent,
            occupancy_pct=income["inputs_used"]["occupancy_pct"],
            other_income_pct=income["inputs_used"]["other_income_pct"],
            expense_pct=income["inputs_used"]["expense_pct"],
        )
        result["stabilized_noi"] = stabilized["noi"]
        result["renovation_capex"] = capex
    return result


__all__ = [
    "DEFAULT_EXPENSE_PCT",
    "DEFAULT_OCCUPANCY_PCT",
    "DEFAULT_OTHER_INCOME_PCT",
    "INPUT_RESOLUTIONS",
    "MultifamilyInputError",
    "multifamily_income",
    "multifamily_offer_inputs",
]
