"""Deterministic control-structure recommendations for lease-up execution."""

from __future__ import annotations

import math
from typing import Any

_STRUCTURES: tuple[dict[str, Any], ...] = (
    {
        "name": "purchase_option",
        "base_probability": 0.58,
        "nonrefundable_exposure": "Low to moderate option consideration",
        "what_it_costs": "Negotiated option fee, diligence costs, and extension fees",
        "seller_problem_solved": "Creates a defined sale path while the buyer secures a tenant",
        "buyer_risk": "Option payments can be lost if leasing or financing fails",
        "when_to_use": "Use when tenant commitment must precede acquisition and the seller can wait",
    },
    {
        "name": "master_lease",
        "base_probability": 0.45,
        "nonrefundable_exposure": "Rent, deposit, and operating obligations",
        "what_it_costs": "Master rent, security deposit, insurance, and property operating costs",
        "seller_problem_solved": "Replaces vacancy with contractual income and active management",
        "buyer_risk": "Rent remains due even if the replacement tenant is delayed",
        "when_to_use": "Use when rent can be covered during lease-up and ownership can remain with the seller",
    },
    {
        "name": "seller_financing",
        "base_probability": 0.42,
        "nonrefundable_exposure": "Down payment plus closing and diligence costs",
        "what_it_costs": "Down payment, negotiated interest, legal documents, and closing costs",
        "seller_problem_solved": "Creates installment income and may support the seller's desired price",
        "buyer_risk": "Buyer owns the vacancy and must service debt before tenant rent begins",
        "when_to_use": "Use when bank liquidity is constrained but the seller values income over cash at close",
    },
    {
        "name": "extended_close",
        "base_probability": 0.60,
        "nonrefundable_exposure": "Deposit after negotiated diligence milestones",
        "what_it_costs": "Earnest money, extension deposits, diligence, and legal costs",
        "seller_problem_solved": "Preserves a committed sale while allowing more time to close",
        "buyer_risk": "Deposit hardening can arrive before tenant and financing certainty",
        "when_to_use": "Use when the seller wants a sale contract and tenant approval needs a longer runway",
    },
    {
        "name": "assignment",
        "base_probability": 0.35,
        "nonrefundable_exposure": "Contract deposit and diligence spend",
        "what_it_costs": "Earnest money, legal work, diligence, and any negotiated assignment consideration",
        "seller_problem_solved": "Delivers a buyer under a single contract without requiring seller financing",
        "buyer_risk": "Assignment rights may be restricted and an assignee may not perform",
        "when_to_use": "Use only with express assignment rights and a credible takeout buyer or tenant developer",
    },
    {
        "name": "ground_lease",
        "base_probability": 0.38,
        "nonrefundable_exposure": "Predevelopment costs and ground rent after commencement",
        "what_it_costs": "Ground rent, entitlement work, construction, and long-term site obligations",
        "seller_problem_solved": "Retains land ownership while creating durable income",
        "buyer_risk": "Entitlement and construction capital are at risk on land the buyer does not own",
        "when_to_use": "Use for a durable pad location where new construction and a long lease term are justified",
    },
)


def _level(value: str | float | int | None, *, liquidity: bool = False) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized in {"low", "limited", "weak", "unmotivated"}:
            return "low"
        if normalized in {"high", "strong", "motivated", "very_motivated"}:
            return "high"
        return "medium"
    if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError("motivation and liquidity values must be non-negative")
    number = float(value)
    if liquidity:
        if number <= 1:
            return "low" if number < 0.34 else "high" if number >= 0.67 else "medium"
        return "low" if number < 250_000 else "high" if number >= 1_000_000 else "medium"
    if number <= 1:
        return "low" if number < 0.34 else "high" if number >= 0.67 else "medium"
    return "low" if number < 4 else "high" if number >= 7 else "medium"


def recommend_control_structure(
    *,
    seller_motivation: str | float | int | None = None,
    buyer_liquidity: str | float | int | None = None,
    needs_tenant_first: bool = True,
    timeline_months: int | None = None,
) -> list[dict[str, object]]:
    """Rank six control structures using transparent, repeatable heuristics."""

    if not isinstance(needs_tenant_first, bool):
        raise ValueError("needs_tenant_first must be a boolean")
    if timeline_months is not None and (
        isinstance(timeline_months, bool) or timeline_months <= 0
    ):
        raise ValueError("timeline_months must be a positive integer")

    motivation = _level(seller_motivation)
    liquidity = _level(buyer_liquidity, liquidity=True)
    adjustments: dict[str, float] = {item["name"]: 0.0 for item in _STRUCTURES}

    if needs_tenant_first:
        adjustments["purchase_option"] += 0.25
        adjustments["extended_close"] += 0.20
        adjustments["master_lease"] += 0.10
        adjustments["assignment"] += 0.05
    if liquidity == "low":
        adjustments["seller_financing"] += 0.25
        adjustments["master_lease"] += 0.20
        adjustments["purchase_option"] += 0.12
        adjustments["assignment"] += 0.08
    elif liquidity == "high":
        adjustments["extended_close"] += 0.05
        adjustments["ground_lease"] += 0.05
    if motivation == "high":
        adjustments["seller_financing"] += 0.15
        adjustments["master_lease"] += 0.12
        adjustments["purchase_option"] += 0.10
        adjustments["extended_close"] += 0.08
    elif motivation == "low":
        adjustments["purchase_option"] -= 0.12
        adjustments["master_lease"] -= 0.10
        adjustments["seller_financing"] -= 0.10
    if timeline_months is not None:
        if timeline_months <= 3:
            adjustments["purchase_option"] += 0.08
            adjustments["assignment"] += 0.08
            adjustments["ground_lease"] -= 0.12
        elif timeline_months >= 9:
            adjustments["extended_close"] += 0.15
            adjustments["purchase_option"] += 0.10
            adjustments["ground_lease"] += 0.05

    recommendations: list[dict[str, object]] = []
    for order, structure in enumerate(_STRUCTURES):
        probability = structure["base_probability"] + adjustments[structure["name"]]
        recommendations.append(
            {
                "name": structure["name"],
                "nonrefundable_exposure": structure["nonrefundable_exposure"],
                "what_it_costs": structure["what_it_costs"],
                "seller_problem_solved": structure["seller_problem_solved"],
                "buyer_risk": structure["buyer_risk"],
                "execution_probability": round(max(0.0, min(1.0, probability)), 2),
                "when_to_use": structure["when_to_use"],
                "_order": order,
            }
        )

    recommendations.sort(
        key=lambda item: (-float(item["execution_probability"]), int(item["_order"]))
    )
    for recommendation in recommendations:
        del recommendation["_order"]
    return recommendations


__all__ = ["recommend_control_structure"]
