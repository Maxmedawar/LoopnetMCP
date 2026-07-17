"""MCP boundaries for capital CRM, compliance, economics, and draft documents."""

from __future__ import annotations

import logging
from typing import Any

from cre_mcp.capital.docs import draft_form_d as compose_form_d
from cre_mcp.capital.docs import draft_ppm as compose_ppm
from cre_mcp.capital.exemption import check_solicitation as screen_solicitation
from cre_mcp.capital.waterfall import model_waterfall as calculate_waterfall
from cre_mcp.deals.store import get_deal_store
from cre_mcp.execution.debt import size_debt as size_context_debt
from cre_mcp.execution.guardrails import capital_guardrail
from cre_mcp.models import Deal, DealContext, InvestorRecord
from cre_mcp.tools.deal_tools import analyze_deal

logger = logging.getLogger(__name__)


async def _deal_context(url_or_id: str, source: str) -> DealContext:
    payload = await analyze_deal(url_or_id, source=source)
    if "error" in payload:
        raise ValueError(str(payload["error"]))
    deal = Deal.model_validate(payload)
    return DealContext(
        listing=deal.listing,
        facts=deal.facts,
        value_estimate=deal.value_estimate,
        market=deal.market_pack,
        parcel=deal.parcel,
        attributes=deal.attributes,
        rent_comps=deal.rent_comps,
        underwriting=deal.underwriting,
    )


async def add_investor(
    name: str,
    accredited: bool | None = None,
    accreditation_verified: bool = False,
    relationship: str = "new",
    contact: str | None = None,
) -> dict:
    """Add a prospective investor to the persistent, compliance-aware CRM.

    Args:
        name: Investor/person/entity name.
        accredited: Known accredited status; None means not yet assessed.
        accreditation_verified: Whether reasonable 506(c)-style verification is documented.
        relationship: Preexisting or new.
        contact: Optional contact note, email, or phone.

    Returns:
        Investor record plus the mandatory securities-attorney hard gate.
    """
    logger.info("add_investor called: name=%s relationship=%s", name, relationship)
    try:
        store = get_deal_store()
        investor_id = await store.add_investor(
            name,
            accredited=accredited,
            accreditation_verified=accreditation_verified,
            relationship=relationship,
            contact=contact,
        )
        if investor_id is None:
            raise RuntimeError("investor could not be persisted")
        record = await store.get_investor(investor_id)
        if record is None:
            raise RuntimeError("persisted investor could not be read")
        result = InvestorRecord.model_validate(record).model_dump(mode="json")
        result["guardrail"] = capital_guardrail(
            "Adding a CRM record is not permission to offer securities; counsel must approve "
            "the exemption, relationship evidence, questionnaire, and verification process."
        )
        return result
    except Exception as exc:
        logger.error("add_investor error: %s", exc)
        return {"error": str(exc)}


async def list_investors() -> dict:
    """List investor CRM records and non-binding commitments.

    Returns:
        Investor records, totals, and the mandatory securities-attorney hard gate.
    """
    logger.info("list_investors called")
    try:
        investors = [
            InvestorRecord.model_validate(item).model_dump(mode="json")
            for item in await get_deal_store().list_investors()
        ]
        return {
            "investors": investors,
            "count": len(investors),
            "total_indicated": sum(item["total_commitments"] for item in investors),
            "guardrail": capital_guardrail(
                "Treat CRM status and commitments as internal records only; counsel controls "
                "who may receive offering material and when money may be accepted."
            ),
        }
    except Exception as exc:
        logger.error("list_investors error: %s", exc)
        return {"error": str(exc)}


async def record_commitment(
    deal_id: str,
    investor_id: int,
    amount: float,
) -> dict:
    """Record a non-binding investor indication against an already-saved deal.

    Args:
        deal_id: Stable source-qualified DealStore identifier.
        investor_id: Numeric investor identifier.
        amount: Positive non-binding indicated amount.

    Returns:
        Commitment record explicitly separated from accepting funds.
    """
    logger.info("record_commitment called: deal=%s investor=%s", deal_id, investor_id)
    try:
        store = get_deal_store()
        if await store.get_deal(deal_id) is None:
            raise ValueError(f"unknown deal_id: {deal_id}")
        if await store.get_investor(investor_id) is None:
            raise ValueError(f"unknown investor_id: {investor_id}")
        commitment_id = await store.record_commitment(deal_id, investor_id, amount)
        if commitment_id is None:
            raise RuntimeError("commitment could not be persisted")
        record = await store.get_commitment(commitment_id)
        if record is None:
            raise RuntimeError("persisted commitment could not be read")
        return {
            **record,
            "status": "NON-BINDING INDICATION ONLY — NO FUNDS ACCEPTED",
            "guardrail": capital_guardrail(
                "Do not send funding instructions, countersign a subscription, or accept money "
                "until counsel clears the offering and this purchaser."
            ),
        }
    except Exception as exc:
        logger.error("record_commitment error: %s", exc)
        return {"error": str(exc)}


async def check_solicitation(
    mode: str,
    action: str | dict[str, Any],
) -> dict:
    """Screen a proposed action under the preliminary Rule 506(b)/(c) gates.

    Args:
        mode: Rule 506(b) or 506(c), written as 506b/506c or equivalent.
        action: Action string or facts dictionary containing action, public/general_solicitation,
            accepting_money, accredited, accreditation_verified, relationship, and current
            non_accredited_count where relevant.

    Returns:
        Fail-closed ComplianceCheck; only explicit allowlisted actions can pass preliminary gates.
    """
    logger.info("check_solicitation called: mode=%s", mode)
    try:
        return screen_solicitation(mode, action).model_dump(mode="json")
    except Exception as exc:
        logger.error("check_solicitation error: %s", exc)
        return {"error": str(exc)}


async def model_waterfall(
    url_or_id: str,
    pref: float = 8.0,
    gp_promote: float = 20.0,
    lp_equity_pct: float = 90.0,
    catch_up: bool = True,
    hold_years: int = 5,
    total_equity: float | None = None,
    annual_cash_flow: float | None = None,
    exit_equity_proceeds: float | None = None,
    ltv: float = 70.0,
    tiered_splits: list[dict[str, float]] | None = None,
    source: str = "loopnet",
) -> dict:
    """Model a transparent LP/GP distribution waterfall for one analyzed deal.

    Args:
        url_or_id: Listing URL or source identifier.
        pref: Annual LP preferred-return scenario, decimal or percent.
        gp_promote: GP residual promote/carry, decimal or percent.
        lp_equity_pct: Percentage of contributed equity funded by LPs.
        catch_up: Whether to model a GP catch-up after capital return.
        hold_years: Scenario duration.
        total_equity: Optional invested-equity override; otherwise derived from price/LTV.
        annual_cash_flow: Optional flat annual distributable-cash override.
        exit_equity_proceeds: Optional terminal net equity proceeds; default is flat capital recovery.
        ltv: Scenario debt percentage used only when total_equity is omitted.
        tiered_splits: Optional IRR hurdle/split mappings.
        source: Registered listing source.

    Returns:
        WaterfallResult with yearly allocations, LP IRR/multiple, promote, assumptions, and gate.
    """
    logger.info("model_waterfall called: source=%s listing=%s", source, url_or_id)
    try:
        ctx = await _deal_context(url_or_id, source)
        structure: dict[str, Any] = {
            "pref": pref,
            "gp_promote": gp_promote,
            "lp_equity_pct": lp_equity_pct,
            "catch_up": catch_up,
            "hold_years": hold_years,
            "ltv": ltv,
            "tiered_splits": tiered_splits or [],
        }
        if total_equity is None or annual_cash_flow is None:
            debt = size_context_debt(ctx, "bank", ltv=ltv)
            structure["debt_sizing"] = debt.model_dump(mode="json")
            if total_equity is None:
                structure["total_equity"] = debt.equity_required
                structure["total_equity_source"] = (
                    "existing bank debt-sizing scenario: purchase price less constrained proceeds"
                )
            if annual_cash_flow is None and debt.noi is not None:
                structure["annual_cash_flow"] = max(
                    debt.noi - debt.annual_debt_service,
                    0.0,
                )
                structure["annual_cash_flow_source"] = (
                    "existing bank debt-sizing scenario: current NOI less modeled debt service"
                )
        for key, value in (
            ("total_equity", total_equity),
            ("annual_cash_flow", annual_cash_flow),
            ("exit_equity_proceeds", exit_equity_proceeds),
        ):
            if value is not None:
                structure[key] = value
        return calculate_waterfall(ctx, structure).model_dump(mode="json")
    except Exception as exc:
        logger.error("model_waterfall error: %s", exc)
        return {"error": str(exc)}


async def draft_ppm(
    url_or_id: str,
    issuer_name: str | None = None,
    mode: str = "506b",
    target_raise: float | None = None,
    minimum_investment: float | None = None,
    pref: float = 8.0,
    gp_promote: float = 20.0,
    source: str = "loopnet",
) -> dict:
    """Draft a fact-grounded PPM skeleton for securities-attorney completion.

    Args:
        url_or_id: Listing URL or source identifier.
        issuer_name: Proposed issuer legal name or placeholder.
        mode: Proposed 506b or 506c path; counsel must select it.
        target_raise: Proposed offering amount.
        minimum_investment: Proposed minimum subscription.
        pref: Preferred-return scenario shown as a non-promised term.
        gp_promote: GP promote/carry scenario.
        source: Registered listing source.

    Returns:
        Clearly stamped DRAFT PPM skeleton with risks and hard gate.
    """
    logger.info("draft_ppm called: source=%s listing=%s", source, url_or_id)
    try:
        compliance = screen_solicitation(mode, "prepare_private_draft")
        ctx = await _deal_context(url_or_id, source)
        terms = {
            "issuer_name": issuer_name or "[ISSUER LEGAL NAME]",
            "exemption": mode,
            "target_raise": target_raise,
            "minimum_investment": minimum_investment,
            "pref": pref,
            "gp_promote": gp_promote,
        }
        draft = compose_ppm(ctx, terms).model_dump(mode="json")
        draft["preliminary_compliance_check"] = compliance.model_dump(mode="json")
        return draft
    except Exception as exc:
        logger.error("draft_ppm error: %s", exc)
        return {"error": str(exc)}


async def draft_form_d(
    issuer_name: str,
    issuer_state: str,
    offering_amount: float,
    mode: str = "506b",
    first_sale_date: str | None = None,
    minimum_investment: float | None = None,
    amount_sold: float = 0,
    related_persons: list[str] | None = None,
) -> dict:
    """Draft a Form D intake data set; this does not file anything.

    Args:
        issuer_name: Issuer legal name.
        issuer_state: Formation jurisdiction/state.
        offering_amount: Total proposed offering amount.
        mode: Proposed 506b or 506c exemption.
        first_sale_date: Optional YYYY-MM-DD date used to estimate the 15-day deadline.
        minimum_investment: Optional minimum subscription.
        amount_sold: Amount already sold as of the draft.
        related_persons: Names of directors, executive officers, promoters, and other filers.

    Returns:
        Clearly stamped DRAFT Form D intake organizer with hard gate.
    """
    logger.info("draft_form_d called: issuer=%s mode=%s", issuer_name, mode)
    try:
        compliance = screen_solicitation(mode, "prepare_form_d_data")
        if offering_amount <= 0:
            raise ValueError("offering_amount must be greater than zero")
        if amount_sold < 0 or amount_sold > offering_amount:
            raise ValueError("amount_sold must be between zero and offering_amount")
        draft = compose_form_d(
            {
                "name": issuer_name,
                "state": issuer_state,
                "related_persons": related_persons or [],
            },
            {
                "exemption": mode,
                "first_sale_date": first_sale_date,
                "target_raise": offering_amount,
                "minimum_investment": minimum_investment,
                "amount_sold": amount_sold,
                "remaining_to_be_sold": offering_amount - amount_sold,
            },
        ).model_dump(mode="json")
        draft["preliminary_compliance_check"] = compliance.model_dump(mode="json")
        return draft
    except Exception as exc:
        logger.error("draft_form_d error: %s", exc)
        return {"error": str(exc)}


__all__ = [
    "add_investor",
    "check_solicitation",
    "draft_form_d",
    "draft_ppm",
    "list_investors",
    "model_waterfall",
    "record_commitment",
]
