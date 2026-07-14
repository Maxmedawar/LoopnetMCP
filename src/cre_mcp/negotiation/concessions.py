"""Transparent, deterministic valuation of common negotiation concessions.

The calculations in this module are deliberately small.  A concession is not a
DCF and an estimate of risk is not cash.  Missing economic inputs therefore stay
``None`` and are explained in the returned assumptions instead of being filled
with an industry convention.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


_SUPPORTED_TYPES = {
    "price_cut",
    "dd_extension",
    "rent_credit",
    "repair_credit",
    "contingency_waiver",
    "timing",
}
_PERSPECTIVES = {"both", "giver", "receiver", "us", "them"}


def _number(value: Any, name: str) -> float:
    """Return a finite, nonnegative number; booleans are never dollar inputs."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite nonnegative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return result


def _first_number(
    sources: tuple[Mapping[str, Any], ...],
    keys: tuple[str, ...],
) -> tuple[float | None, str | None]:
    for source in sources:
        for key in keys:
            if key in source and source[key] is not None:
                return _number(source[key], key), key
    return None, None


def _money(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _credit_amount(params: Mapping[str, Any], label: str) -> tuple[float, str]:
    amount, amount_key = _first_number(
        (params,),
        ("amount", "amount_usd", "credit", "credit_amount"),
    )
    if amount is not None:
        return amount, f"{amount_key}"

    monthly, monthly_key = _first_number(
        (params,),
        ("monthly_credit", "credit_per_month"),
    )
    months, months_key = _first_number((params,), ("months",))
    if monthly is None or months is None:
        raise ValueError(
            f"{label} requires amount or both monthly_credit and months"
        )
    return monthly * months, f"{monthly_key} * {months_key}"


def value_concession(
    concession: Mapping[str, Any],
    deal_economics: Mapping[str, Any],
    perspective: str = "both",
) -> dict[str, Any]:
    """Value a negotiation concession from the giver and receiver viewpoints.

    Supported types are ``price_cut``, ``dd_extension``, ``rent_credit``,
    ``repair_credit``, ``contingency_waiver``, and ``timing``.  Dollar values are
    face-value negotiation estimates, not tax or present-value conclusions.

    ``dd_extension`` uses ``daily_carry * days`` for the giver's cost.  Its value
    to the receiver is only quantified when ``option_value`` or
    ``option_value_per_day`` is supplied.  More diligence time may be useful,
    but this function never invents an option value for it.
    """

    if not isinstance(concession, Mapping):
        raise TypeError("concession must be a mapping")
    if not isinstance(deal_economics, Mapping):
        raise TypeError("deal_economics must be a mapping")
    if perspective not in _PERSPECTIVES:
        allowed = ", ".join(sorted(_PERSPECTIVES))
        raise ValueError(f"perspective must be one of: {allowed}")

    concession_type = concession.get("type")
    if concession_type not in _SUPPORTED_TYPES:
        allowed = ", ".join(sorted(_SUPPORTED_TYPES))
        raise ValueError(f"concession type must be one of: {allowed}")

    raw_params = concession.get("params", {})
    if raw_params is None:
        raw_params = {}
    if not isinstance(raw_params, Mapping):
        raise TypeError("concession params must be a mapping")
    # Top-level fields remain accepted for callers that already hold a flat term
    # record, while nested params take precedence.
    params = {key: value for key, value in concession.items() if key != "params"}
    params.update(raw_params)

    giver_cost: float | None = None
    receiver_value: float | None = None
    calculation = ""
    receiver_calculation = ""
    assumptions: list[dict[str, Any]] = []
    risk_notes: list[str] = []
    counsel_flags: list[str] = []

    if concession_type == "price_cut":
        amount, key = _first_number(
            (params,),
            ("amount", "amount_usd", "price_cut", "price_reduction"),
        )
        from_price, _ = _first_number((params,), ("from_price",))
        to_price, _ = _first_number((params,), ("to_price",))
        if (from_price is None) != (to_price is None):
            raise ValueError("price_cut requires both from_price and to_price when either is supplied")
        if from_price is not None and to_price is not None:
            if to_price > from_price:
                raise ValueError("price_cut to_price cannot exceed from_price")
            derived_amount = from_price - to_price
            if amount is not None and not math.isclose(
                amount, derived_amount, rel_tol=0.0, abs_tol=0.01
            ):
                raise ValueError("price_cut amount conflicts with from_price - to_price")
        if amount is None:
            if from_price is None or to_price is None:
                raise ValueError(
                    "price_cut requires amount or both from_price and to_price"
                )
            amount = from_price - to_price
            key = "from_price - to_price"
        giver_cost = receiver_value = amount
        calculation = f"giver cost = {key} = {amount:g}"
        receiver_calculation = "receiver value = the same face-dollar price reduction"
        assumptions.append(
            {
                "name": "price_cut_face_value",
                "value": amount,
                "source": "provided",
                "effect": "Dollar-for-dollar transfer; tax and financing effects excluded.",
            }
        )

    elif concession_type == "dd_extension":
        days, _ = _first_number((params,), ("days", "extension_days"))
        if days is None:
            raise ValueError("dd_extension requires days")
        daily_carry, carry_key = _first_number(
            (params, deal_economics),
            ("daily_carry", "daily_carry_cost", "carry_cost_per_day"),
        )
        if daily_carry is None:
            calculation = "giver cost is unknown: daily_carry was not supplied"
            assumptions.append(
                {
                    "name": "daily_carry",
                    "value": None,
                    "source": "missing",
                    "effect": "Giver cost cannot be quantified.",
                }
            )
        else:
            giver_cost = daily_carry * days
            calculation = f"giver cost = {days:g} days * {carry_key} ({daily_carry:g}/day)"
            assumptions.append(
                {
                    "name": "daily_carry",
                    "value": daily_carry,
                    "source": "provided",
                    "effect": "Applied for every extension day; no discounting.",
                }
            )

        option_value, option_key = _first_number(
            (params, deal_economics),
            ("option_value", "dd_option_value"),
        )
        option_per_day, option_day_key = _first_number(
            (params, deal_economics),
            ("option_value_per_day", "dd_option_value_per_day"),
        )
        if (
            option_value is not None
            and option_per_day is not None
            and not math.isclose(
                option_value, option_per_day * days, rel_tol=0.0, abs_tol=0.01
            )
        ):
            raise ValueError(
                "option_value conflicts with option_value_per_day * extension days"
            )
        if option_value is not None:
            receiver_value = option_value
            receiver_calculation = f"receiver value = provided {option_key}"
        elif option_per_day is not None:
            receiver_value = option_per_day * days
            receiver_calculation = (
                f"receiver value = {days:g} days * {option_day_key} "
                f"({option_per_day:g}/day)"
            )
        else:
            receiver_calculation = (
                "receiver option value is unknown; no option_value or "
                "option_value_per_day was supplied"
            )
        assumptions.append(
            {
                "name": "diligence_option_value",
                "value": receiver_value,
                "source": "provided" if receiver_value is not None else "missing",
                "effect": (
                    "Extra diligence time can preserve the receiver's option to walk or "
                    "retrade, but that value is not assumed to equal carry cost."
                ),
            }
        )
        risk_notes.append(
            "More diligence time may reveal defects or preserve optionality; quantify that "
            "benefit separately from the giver's carry."
        )

    elif concession_type in {"rent_credit", "repair_credit"}:
        amount, formula = _credit_amount(params, concession_type)
        giver_cost = receiver_value = amount
        calculation = f"giver cost = {formula}"
        receiver_calculation = "receiver value = face-dollar credit"
        assumptions.append(
            {
                "name": "credit_face_value",
                "value": amount,
                "source": "provided",
                "effect": "Treats the credit as a dollar-for-dollar transfer before tax.",
            }
        )
        if concession_type == "repair_credit":
            risk_notes.append(
                "A repair credit does not establish the actual repair scope or final cost; "
                "support it with bids, access rights, and responsibility language."
            )
        else:
            risk_notes.append(
                "Confirm when the rent credit is earned and whether default, assignment, or "
                "early termination changes it."
            )

    elif concession_type == "contingency_waiver":
        giver_cost, giver_key = _first_number(
            (params, deal_economics),
            ("estimated_risk_cost", "giver_cost", "risk_cost"),
        )
        receiver_value, receiver_key = _first_number(
            (params, deal_economics),
            ("receiver_value", "certainty_value"),
        )
        calculation = (
            f"giver cost = provided {giver_key}"
            if giver_cost is not None
            else "giver risk cost is unknown; no estimated_risk_cost was supplied"
        )
        receiver_calculation = (
            f"receiver value = provided {receiver_key}"
            if receiver_value is not None
            else "receiver certainty value is unknown; no receiver_value was supplied"
        )
        assumptions.extend(
            [
                {
                    "name": "waiver_risk_cost",
                    "value": giver_cost,
                    "source": "provided" if giver_cost is not None else "missing",
                    "effect": "An estimate is not a cap on actual loss or liability.",
                },
                {
                    "name": "counterparty_certainty_value",
                    "value": receiver_value,
                    "source": "provided" if receiver_value is not None else "missing",
                    "effect": "Must be evidenced rather than inferred from the waiver alone.",
                },
            ]
        )
        counsel_flags.append(
            "CRE counsel must review the exact contingency, survival, remedy, deposit, "
            "knowledge, and waiver language before it is offered or accepted."
        )
        risk_notes.append(
            "Waiving a contingency can expose the giver to deposit loss, closing liability, "
            "or an asset it cannot finance or use; the downside is not bounded here."
        )

    else:  # timing
        days, _ = _first_number((params,), ("days", "timing_days"))
        explicit_cost, explicit_cost_key = _first_number(
            (params,), ("giver_cost", "cost_to_giver")
        )
        daily_carry, carry_key = _first_number(
            (params, deal_economics),
            ("daily_carry", "daily_carry_cost", "carry_cost_per_day"),
        )
        if explicit_cost is not None:
            giver_cost = explicit_cost
            calculation = f"giver cost = provided {explicit_cost_key}"
        elif daily_carry is not None and days is not None:
            giver_cost = daily_carry * days
            calculation = f"giver cost = {days:g} days * {carry_key} ({daily_carry:g}/day)"
        else:
            calculation = (
                "giver cost is unknown: provide giver_cost, or both days and daily_carry"
            )

        explicit_value, explicit_value_key = _first_number(
            (params,), ("receiver_value", "value_to_receiver")
        )
        receiver_daily_carry, receiver_carry_key = _first_number(
            (params, deal_economics),
            ("receiver_daily_carry", "receiver_carry_cost_per_day"),
        )
        if explicit_value is not None:
            receiver_value = explicit_value
            receiver_calculation = f"receiver value = provided {explicit_value_key}"
        elif receiver_daily_carry is not None and days is not None:
            receiver_value = receiver_daily_carry * days
            receiver_calculation = (
                f"receiver value = {days:g} days * {receiver_carry_key} "
                f"({receiver_daily_carry:g}/day)"
            )
        else:
            receiver_calculation = (
                "receiver value is unknown: provide receiver_value, or both days and "
                "receiver_daily_carry"
            )
        if days is None and explicit_cost is None and explicit_value is None:
            raise ValueError(
                "timing requires days unless giver_cost or receiver_value is supplied"
            )
        assumptions.append(
            {
                "name": "timing_direction",
                "value": params.get("direction", "not_specified"),
                "source": "provided" if "direction" in params else "missing",
                "effect": "Earlier and later performance can reverse who benefits.",
            }
        )
        risk_notes.append(
            "Confirm whether the requested timing is earlier or later and identify lender, "
            "title, notice, tax, and operational dependencies."
        )

    giver_cost = _money(giver_cost)
    receiver_value = _money(receiver_value)
    ratio_value, _ = _first_number(
        (params, deal_economics), ("trade_candidate_ratio",)
    )
    if ratio_value == 0:
        raise ValueError("trade_candidate_ratio must be greater than zero")
    ratio_threshold = ratio_value if ratio_value is not None else 1.5
    if ratio_value is None:
        assumptions.append(
            {
                "name": "trade_candidate_ratio",
                "value": ratio_threshold,
                "source": "explicit default",
                "effect": "Flag only when receiver value is at least this multiple of giver cost.",
            }
        )

    value_cost_ratio: float | None = None
    if giver_cost is not None and receiver_value is not None:
        if giver_cost == 0:
            asymmetry_flag = receiver_value > 0
        else:
            value_cost_ratio = round(receiver_value / giver_cost, 4)
            asymmetry_flag = value_cost_ratio >= ratio_threshold
        asymmetry_reason = (
            "cheap for giver relative to evidenced receiver value"
            if asymmetry_flag
            else "evidenced receiver value does not clear the trade-candidate threshold"
        )
    else:
        asymmetry_flag = False
        asymmetry_reason = (
            "not assessable: both giver cost and receiver value must be quantified"
        )

    if perspective in {"giver", "us"}:
        perspective_view = "Focus on giver_cost; receiver_value remains shown for give-get discipline."
    elif perspective in {"receiver", "them"}:
        perspective_view = "Focus on receiver_value; giver_cost remains shown to expose asymmetry."
    else:
        perspective_view = "Both sides are shown; neither estimate is treated as the other side's fact."

    return {
        "type": concession_type,
        "perspective": perspective,
        "perspective_view": perspective_view,
        "giver_cost": giver_cost,
        "receiver_value": receiver_value,
        # Aliases make the direction unambiguous when this result is embedded in
        # a plan written from the user's perspective.
        "cost_to_giver": giver_cost,
        "value_to_receiver": receiver_value,
        "calculation": calculation,
        "receiver_value_calculation": receiver_calculation,
        "value_cost_ratio": value_cost_ratio,
        "asymmetry_flag": asymmetry_flag,
        "asymmetry_reason": asymmetry_reason,
        "trade_candidate": asymmetry_flag,
        "assumptions": assumptions,
        "risk_notes": risk_notes,
        "counsel_flags": counsel_flags,
    }


__all__ = ["value_concession"]
