"""Blunt, kind borrower qualification and cash-to-close screening."""

from __future__ import annotations

import re
from typing import Any

from cre_mcp.execution.debt import DebtScenario, size_debt
from cre_mcp.execution.financing import financing_options
from cre_mcp.execution.guardrails import financing_guardrail
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import (
    BuyerProfile,
    QualificationGate,
    QualifyResult,
)
from cre_mcp.scoring.rubrics import thresholds as T


def _scenario(ctx: DealContext) -> DebtScenario:
    options = financing_options(ctx)
    eligible = {option.type for option in options if option.eligible}
    if "agency_multifamily" in eligible:
        return "agency"
    if "bridge_debt_fund" in eligible:
        return "bridge"
    return "bank"


def _credit_tier(value: str) -> str:
    normalized = re.sub(r"[^a-z]+", "_", value.casefold()).strip("_")
    aliases = {
        "verygood": "very_good",
        "very": "very_good",
        "average": "fair",
        "strong": "good",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in T.QUALIFY_CREDIT_TIER_RANK:
        choices = ", ".join(T.QUALIFY_CREDIT_TIER_RANK)
        raise ValueError(f"credit_tier must be one of: {choices}")
    return normalized


def _profile(buyer: BuyerProfile | dict[str, Any]) -> BuyerProfile:
    return buyer if isinstance(buyer, BuyerProfile) else BuyerProfile.model_validate(buyer)


def qualify_me(
    ctx: DealContext,
    buyer: BuyerProfile | dict[str, Any],
) -> QualifyResult:
    """Compare buyer capacity with typical cash, liquidity, sponsor, and credit gates."""
    profile = _profile(buyer)
    scenario = _scenario(ctx)
    debt = size_debt(ctx, scenario)
    closing_costs = debt.purchase_price * T.QUALIFY_CLOSING_COST_PCT
    reserves = (
        debt.annual_debt_service / 12 * T.QUALIFY_RESERVE_MONTHS
    )
    down_payment = debt.equity_required
    cash_to_close = down_payment + closing_costs + reserves
    post_close_liquid = max(profile.liquid - down_payment - closing_costs, 0.0)
    net_worth_required = (
        debt.max_loan * T.QUALIFY_NET_WORTH_LOAN_RATIO[scenario]
    )
    experience_required = T.QUALIFY_MIN_EXPERIENCE_DEALS[scenario]

    gates = [
        QualificationGate(
            name="cash_to_close",
            required=cash_to_close,
            buyer_has=profile.liquid,
            passed=profile.liquid >= cash_to_close,
        ),
        QualificationGate(
            name="net_worth",
            required=net_worth_required,
            buyer_has=profile.net_worth,
            passed=profile.net_worth >= net_worth_required,
        ),
        QualificationGate(
            name="post_close_liquidity",
            required=reserves,
            buyer_has=post_close_liquid,
            passed=post_close_liquid >= reserves,
        ),
        QualificationGate(
            name="sponsor_experience",
            required=float(experience_required),
            buyer_has=float(profile.experience_deals),
            passed=profile.experience_deals >= experience_required,
        ),
    ]
    credit_failed = False
    if profile.credit_tier is not None:
        buyer_credit = _credit_tier(profile.credit_tier)
        minimum_credit = T.QUALIFY_MIN_CREDIT_TIER[scenario]
        credit_failed = (
            T.QUALIFY_CREDIT_TIER_RANK[buyer_credit]
            < T.QUALIFY_CREDIT_TIER_RANK[minimum_credit]
        )
        gates.append(
            QualificationGate(
                name="credit_tier",
                required=minimum_credit,
                buyer_has=buyer_credit,
                passed=not credit_failed,
            )
        )

    gate_by_name = {gate.name: gate for gate in gates}
    gaps: list[str] = []
    if not gate_by_name["cash_to_close"].passed:
        shortfall = cash_to_close - profile.liquid
        gaps.append(
            f"Liquid funds are short by about ${shortfall:,.0f} after including the "
            "down payment, closing costs, and lender reserves."
        )
    if not gate_by_name["net_worth"].passed:
        gaps.append(
            f"Net worth is below the typical {scenario} screen by about "
            f"${net_worth_required - profile.net_worth:,.0f}; a balance-sheet guarantor "
            "or co-sponsor may be required."
        )
    if not gate_by_name["post_close_liquidity"].passed:
        gaps.append(
            f"Post-close liquidity is below the {T.QUALIFY_RESERVE_MONTHS}-month debt-"
            "service reserve screen."
        )
    if not gate_by_name["sponsor_experience"].passed:
        gaps.append(
            f"The typical {scenario} screen expects at least {experience_required} prior "
            "deal(s); a first-timer usually needs an experienced operating/co-sponsor."
        )
    if credit_failed:
        gaps.append(
            f"The supplied credit tier is below the typical {scenario} screening tier; "
            "resolve credit issues or obtain lender-specific guidance before relying on proceeds."
        )
    if debt.noi is None:
        gaps.append(
            "Reliable NOI is unavailable, so debt service coverage has not been tested."
        )

    if credit_failed or debt.noi is None:
        verdict = "no"
        guidance = (
            "This is not lender-ready on the available facts. Fix the credit/NOI evidence "
            "before spending money on an application or non-refundable deposit."
        )
    elif not gate_by_name["cash_to_close"].passed or not gate_by_name[
        "post_close_liquidity"
    ].passed:
        verdict = "short_on_cash"
        guidance = (
            "Do not stretch reserves to make the down payment. Lower the price, raise more "
            "equity, or pursue a smaller deal while keeping post-close liquidity intact."
        )
    elif not gate_by_name["net_worth"].passed or not gate_by_name[
        "sponsor_experience"
    ].passed:
        verdict = "needs_partner"
        guidance = (
            "The deal may be financeable, but you are not yet the complete sponsor. Seek a "
            "co-sponsor who brings the missing balance sheet and directly relevant closing/"
            "operating experience; document economics and control with counsel."
        )
    else:
        verdict = "qualifies"
        guidance = (
            "You clear these preliminary screens. Prepare a personal financial statement, "
            "liquidity evidence, schedule of real estate, entity chart, and property diligence "
            "for an actual lender pre-screen."
        )

    return QualifyResult(
        deal_ref=f"{ctx.listing.source}:{ctx.listing.source_id}",
        selected_scenario=scenario,
        cash_to_close=cash_to_close,
        breakdown={
            "down_payment": down_payment,
            "closing_costs": closing_costs,
            "reserves": reserves,
            "loan_proceeds": debt.max_loan,
        },
        gates=gates,
        verdict=verdict,
        gaps=gaps,
        guidance=guidance,
        guardrail=financing_guardrail(
            "Ask a lender to pre-screen both the property and every guarantor before "
            "waiving financing or risking non-refundable money."
        ),
    )


__all__ = ["qualify_me"]
