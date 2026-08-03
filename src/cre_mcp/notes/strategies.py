"""Workout strategy comparison built from the note-pricing path economics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cre_mcp.notes.pricing import price_note
from cre_mcp.notes.timelines import COUNSEL_VERIFICATION_FLAG
from cre_mcp.notes.waterfall import coerce_range

RANGE_KEYS = ("low", "base", "high")
UNKNOWN_RANGE = {"low": "UNKNOWN", "base": "UNKNOWN", "high": "UNKNOWN"}


def _numeric_range(value: Mapping[str, Any]) -> bool:
    return all(isinstance(value.get(key), (int, float)) for key in RANGE_KEYS)


def _envelope(
    first: Mapping[str, float],
    second: Mapping[str, float],
) -> dict[str, float]:
    return {
        "low": round(min(first["low"], second["low"]), 8),
        "base": round((first["base"] + second["base"]) / 2.0, 8),
        "high": round(max(first["high"], second["high"]), 8),
    }


def _receiver_value(
    foreclosure_value: Mapping[str, float],
    receiver_cost: Mapping[str, float],
) -> dict[str, float]:
    return {
        "low": round(max(0.0, foreclosure_value["low"] - receiver_cost["high"]), 8),
        "base": round(max(0.0, foreclosure_value["base"] - receiver_cost["base"]), 8),
        "high": round(max(0.0, foreclosure_value["high"] - receiver_cost["low"]), 8),
    }


def _receiver_total_cost(
    foreclosure_cost: Mapping[str, float],
    receiver_cost: Mapping[str, float],
) -> dict[str, float]:
    return {
        "low": round(foreclosure_cost["low"] + receiver_cost["high"], 8),
        "base": round(foreclosure_cost["base"] + receiver_cost["base"], 8),
        "high": round(foreclosure_cost["high"] + receiver_cost["low"], 8),
    }


def _strategy_row(
    *,
    strategy: str,
    path: Mapping[str, Any] | None,
    expected_value: Mapping[str, Any],
    time_months: Mapping[str, Any],
    cost: Mapping[str, Any],
    key_risks: list[str],
    borrower_must_agree: str,
    flags: list[str],
    derivation: str,
    probability: Any = "NOT_ASSIGNED",
    probability_weighted_contribution: Mapping[str, Any] | None = None,
) -> dict:
    return {
        "strategy": strategy,
        "expected_value": dict(expected_value),
        "time_months": dict(time_months),
        "cost": dict(cost),
        "path_probability": path.get("probability") if path is not None else probability,
        "path_probability_source": (
            path.get("probability_source") if path is not None else "not_assigned_to_strategy"
        ),
        "probability_weighted_expected_contribution": dict(
            probability_weighted_contribution
            or (path.get("expected_contribution", UNKNOWN_RANGE) if path is not None else UNKNOWN_RANGE)
        ),
        "value_derivation": derivation,
        "key_risks": key_risks,
        "what_borrower_must_agree": borrower_must_agree,
        "professional_review_required": True,
        "professional_review_flags": [COUNSEL_VERIFICATION_FLAG, *flags],
    }


def compare_workouts(
    note_facts: Mapping[str, Any],
    borrower_posture: Mapping[str, Any] | None = None,
) -> dict:
    """Compare seven resolution strategies without inventing strategy probabilities.

    A caller may pass a precomputed ``pricing_result`` in ``note_facts``. Otherwise
    the required ``price_note`` arguments are read from that mapping.
    """

    facts = dict(note_facts)
    posture = dict(borrower_posture or {})
    pricing = facts.get("pricing_result")
    if pricing is None:
        required = (
            "upb",
            "rate",
            "payment_history",
            "collateral_value_range",
            "state",
            "lien_position",
            "costs",
            "target_yield_range",
        )
        missing = [key for key in required if key not in facts]
        if missing:
            raise ValueError(f"note_facts missing required pricing fields: {missing}")
        pricing = price_note(
            upb=facts["upb"],
            rate=facts["rate"],
            payment_history=facts["payment_history"],
            collateral_value_range=facts["collateral_value_range"],
            state=facts["state"],
            lien_position=facts["lien_position"],
            costs=facts["costs"],
            target_yield_range=facts["target_yield_range"],
            path_probabilities=facts.get("path_probabilities"),
        )

    path_map = {row["path"]: row for row in pricing.get("paths", [])}
    unknown_path = {
        "probability": "UNKNOWN",
        "probability_source": "UNKNOWN",
        "present_value": UNKNOWN_RANGE,
        "time_months": UNKNOWN_RANGE,
        "cost": UNKNOWN_RANGE,
        "expected_contribution": UNKNOWN_RANGE,
    }

    def path(name: str) -> Mapping[str, Any]:
        return path_map.get(name, unknown_path)

    reinstate = path("reinstate")
    modify = path("modify")
    foreclosure = path("foreclose_to_reo")
    dil = path("deed_in_lieu")
    sale = path("note_sale")

    cooperative = posture.get("cooperative")
    liquidity_to_cure = posture.get("liquidity_to_cure")
    financials_available = posture.get("financials_available")
    willing_to_convey = posture.get("willing_to_convey_dil")

    consensual_flag = (
        ["Borrower is reported uncooperative; consensual execution is presently unsupported."]
        if cooperative is False
        else []
    )
    cure_flags = [
        "Servicer/counsel must calculate the enforceable reinstatement amount and approve notices/agreement."
    ] + consensual_flag
    if liquidity_to_cure is False:
        cure_flags.append("Borrower is reported unable to fund a cure; do not treat reinstatement as executable.")

    modify_flags = [
        "Counsel/servicer and tax/accounting reviewers must approve modification documents, authority, accounting, and any debt-forgiveness consequences."
    ] + consensual_flag
    if financials_available is False:
        modify_flags.append("Current borrower financials are unavailable; sustainable modified debt service is unverified.")

    dil_flags = [
        "Title, environmental, tax, transfer-tax, tenant/occupancy, bankruptcy, and lender-liability diligence must clear before accepting title."
    ] + consensual_flag
    if willing_to_convey is False:
        dil_flags.append("Borrower is reported unwilling to convey; deed-in-lieu is presently unsupported.")

    rows: list[dict[str, Any]] = [
        _strategy_row(
            strategy="cure_reinstate",
            path=reinstate,
            expected_value=reinstate["present_value"],
            time_months=reinstate["time_months"],
            cost=reinstate["cost"],
            key_risks=[
                "Cure funds may not arrive or may be avoidable/clawed back in bankruptcy.",
                "Accepting funds or communications can waive/default-remedy rights if mishandled.",
                "The borrower may redefault after reinstatement.",
            ],
            borrower_must_agree="Pay the approved cure/reinstatement amount and resume enforceable contractual performance.",
            flags=cure_flags,
            derivation="Conditional PV and cost from the pricing reinstate path; no new probability added.",
        ),
        _strategy_row(
            strategy="modification",
            path=modify,
            expected_value=modify["present_value"],
            time_months=modify["time_months"],
            cost=modify["cost"],
            key_risks=[
                "Modified payment may be unaffordable or merely delay default.",
                "Priority, guaranties, waivers, and original-note enforceability can be impaired by defective documents.",
                "Principal/rate/term changes may create accounting or tax consequences.",
            ],
            borrower_must_agree="Provide verified financials, execute approved modification documents, make any trial/upfront payment, and comply with reporting covenants.",
            flags=modify_flags,
            derivation="Conditional PV and cost from the pricing modify path using the disclosed modification conventions.",
        ),
    ]

    if _numeric_range(reinstate["present_value"]) and _numeric_range(modify["present_value"]):
        forbearance_value = _envelope(reinstate["present_value"], modify["present_value"])
        forbearance_time = _envelope(reinstate["time_months"], modify["time_months"])
        forbearance_cost = _envelope(reinstate["cost"], modify["cost"])
    else:
        forbearance_value = forbearance_time = forbearance_cost = UNKNOWN_RANGE
    rows.append(
        _strategy_row(
            strategy="forbearance",
            path=None,
            expected_value=forbearance_value,
            time_months=forbearance_time,
            cost=forbearance_cost,
            key_risks=[
                "Forbearance consumes time while collateral, taxes, insurance, and rents can deteriorate.",
                "A standstill without milestones, admissions, reporting, and termination triggers can reduce leverage.",
                "The ultimate cure or modification remains uncertain.",
            ],
            borrower_must_agree="Execute a counsel-approved standstill with payments, reporting, access, milestones, acknowledgments, and automatic termination events.",
            flags=[
                "Forbearance value is a disclosed envelope of reinstate and modify paths; no success probability was invented.",
                *consensual_flag,
                *(["Current borrower financials are unavailable; forbearance feasibility is unverified."] if financials_available is False else []),
            ],
            derivation="Low/high envelope and base midpoint of pricing reinstate/modify paths; screening convention only.",
        )
    )
    rows.extend(
        [
            _strategy_row(
                strategy="foreclosure",
                path=foreclosure,
                expected_value=foreclosure["present_value"],
                time_months=foreclosure["time_months"],
                cost=foreclosure["cost"],
                key_risks=[
                    "Standing, notices, service, priority, defenses, court/sale delay, bankruptcy stay, redemption, and possession can change timing and recovery.",
                    "REO creates environmental, premises, tenant, insurance, tax, operating, and sale-price exposure.",
                    "A deficiency may be barred, limited, or uneconomic.",
                ],
                borrower_must_agree="No consensual agreement is required, but all borrower/occupant rights, notices, court orders, stays, and sale procedures must be honored.",
                flags=[
                    "Foreclosure counsel, title, bankruptcy, servicing/compliance, environmental, and property-management review are hard gates before action."
                ],
                derivation="Conditional PV, state timing, and cost from the pricing foreclose-to-REO path.",
            ),
            _strategy_row(
                strategy="deed_in_lieu",
                path=dil,
                expected_value=dil["present_value"],
                time_months=dil["time_months"],
                cost=dil["cost"],
                key_risks=[
                    "Junior liens and title defects are not extinguished as they may be in foreclosure.",
                    "Transfer can be attacked if insolvent, coerced, inadequately documented, or followed by bankruptcy.",
                    "Immediate ownership transfers property-level liabilities to the recipient.",
                ],
                borrower_must_agree="Voluntarily convey marketable title under approved documents, estoppels/releases, possession/tenant terms, and bankruptcy-safe consideration.",
                flags=dil_flags,
                derivation="Conditional PV and cost from the pricing deed-in-lieu path.",
            ),
            _strategy_row(
                strategy="note_sale",
                path=sale,
                expected_value=sale["present_value"],
                time_months=sale["time_months"],
                cost=sale["cost"],
                key_risks=[
                    "Broken chain, missing originals/allonges, data defects, repurchase claims, and servicing-transfer errors can impair value.",
                    "Bid depth and diligence retrades can be material.",
                    "Borrower/privacy/collection communications and transfer notices remain regulated.",
                ],
                borrower_must_agree="Generally no consent is assumed, but loan documents and applicable transfer, notice, privacy, licensing, servicing, and participation restrictions must permit the sale.",
                flags=[
                    "Transaction counsel and servicing/compliance review must approve the sale agreement, collateral file transfer, data room, representations, notices, and custody."
                ],
                derivation="Conditional PV and cost from the pricing note-sale path and its disclosed recovery-factor convention.",
            ),
        ]
    )

    upb = float(facts.get("upb", 0) or 0)
    cost_inputs = dict(facts.get("costs", {}) or {})
    receiver_cost = coerce_range(
        cost_inputs.get(
            "receiver_cost",
            {"low": upb * 0.01, "base": upb * 0.02, "high": upb * 0.04},
        ),
        "costs.receiver_cost",
    )
    if _numeric_range(foreclosure["present_value"]):
        receiver_value = _receiver_value(foreclosure["present_value"], receiver_cost)
        receiver_total_cost = _receiver_total_cost(foreclosure["cost"], receiver_cost)
        receiver_time = foreclosure["time_months"]
    else:
        receiver_value = receiver_total_cost = receiver_time = UNKNOWN_RANGE
    rows.append(
        _strategy_row(
            strategy="receiver",
            path=None,
            expected_value=receiver_value,
            time_months=receiver_time,
            cost=receiver_total_cost,
            key_risks=[
                "Appointment is document-, statute-, equity-, and judge-dependent and may be denied or delayed.",
                "Receiver fees, reporting, bonding, tenant operations, and capital needs can exceed the screening band.",
                "A receiver preserves/operates collateral but does not itself resolve lien priority or complete foreclosure.",
            ],
            borrower_must_agree="Consent may help but is not always required; absent enforceable consent, obtain the required court order and comply with debtor/tenant rights.",
            flags=[
                "Receivership counsel and the proposed receiver must approve authority, scope, budget, insurance, reporting, tenant/rent handling, and court filings.",
                "Receiver cost defaults to an explicit 1%/2%/4% of UPB screen unless caller-provided; it is not a fee quote.",
            ],
            derivation="Foreclosure-path conditional PV less receiver cost; foreclosure timing retained because receivership is interim, not a disposition.",
        )
    )

    top_flags = [
        COUNSEL_VERIFICATION_FLAG,
        "No strategy ranking is an instruction to act; accountable humans and licensed professionals must select and approve the path.",
        "Strategy probabilities were not invented. Any displayed path probabilities come unchanged from the pricing model and retain its convention/override label.",
        *pricing.get("professional_review_flags", []),
    ]
    return {
        "status": "MODELED_RANGE" if pricing.get("status") != "UNKNOWN" else "UNKNOWN",
        "strategies": rows,
        "comparison_table": rows,
        "pricing_price_range": pricing.get("price", UNKNOWN_RANGE),
        "pricing_probability_convention": pricing.get("probability_convention"),
        "borrower_posture": posture,
        "assumption_sheet": [
            {"driver": "note_facts", "value": facts, "source": "provided_unverified"},
            {"driver": "borrower_posture", "value": posture, "source": "provided_unverified"},
            {"driver": "receiver_cost", "value": receiver_cost, "source": "provided_unverified" if "receiver_cost" in cost_inputs else "screening_default_convention"},
        ],
        "professional_review_required": True,
        "professional_review_flags": top_flags,
    }


__all__ = ["compare_workouts"]
