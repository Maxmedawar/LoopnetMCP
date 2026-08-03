"""MCP boundaries for execution coaching from offer through closing."""

import logging
from typing import Any

from cre_mcp.access.context import current_context
from cre_mcp.access.engine import structured_property_within_territories
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.deals.store import get_deal_store
from cre_mcp.execution.closing import closing_plan as build_closing_plan
from cre_mcp.execution.contacts import find_contact as assemble_contact
from cre_mcp.execution.debt import size_debt as size_context_debt
from cre_mcp.execution.diligence import due_diligence_plan as build_diligence_plan
from cre_mcp.execution.financing import financing_options as screen_financing
from cre_mcp.execution.loi import generate_loi as draft_loi
from cre_mcp.execution.negotiate import handle_counter as coach_counter
from cre_mcp.execution.offer import recommend_offer as recommend_context_offer
from cre_mcp.execution.outreach import draft_outreach as compose_outreach
from cre_mcp.execution.qualify import qualify_me as screen_buyer
from cre_mcp.models import Deal, DealContext
from cre_mcp.source_rights.output import safe_error_message, safe_source_reference
from cre_mcp.tools.deal_tools import analyze_deal

logger = logging.getLogger(__name__)


def _safe_failure(operation: str, exc: Exception) -> dict[str, str]:
    message = safe_error_message(exc)
    logger.error("%s error: %s", operation, message)
    return {"error": message}


async def _deal_context(
    url_or_id: str,
    source: str,
    strategy: str | None = None,
) -> DealContext:
    payload = await analyze_deal(url_or_id, source=source, strategy=strategy)
    if "error" in payload:
        raise ValueError(str(payload["error"]))
    deal = Deal.model_validate(payload)
    listing = deal.listing
    tenant = current_context()
    if (
        tenant is not None
        and not tenant.trusted
        and tenant.profile in TERRITORY_LIMITED
        and not structured_property_within_territories(
            listing.model_dump(mode="json"),
            tenant.territories,
        )
    ):
        raise ValueError("restricted listing result denied")
    if strategy is not None:
        raw = dict(listing.raw)
        raw["strategy"] = strategy
        listing = listing.model_copy(update={"raw": raw})
    return DealContext(
        listing=listing,
        facts=deal.facts,
        value_estimate=deal.value_estimate,
        market=deal.market_pack,
        parcel=deal.parcel,
        attributes=deal.attributes,
        rent_comps=deal.rent_comps,
        underwriting=deal.underwriting,
    )


async def recommend_offer(
    url_or_id: str,
    source: str = "loopnet",
    strategy: str | None = None,
) -> dict:
    """Recommend an explained opening, target, and walk-away offer range.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        source: Registered source name. Defaults to LoopNet.
        strategy: Optional scoring strategy used to choose return thresholds.

    Returns:
        An OfferRecommendation with prices, cap rates, confidence, terms, and guardrails.
    """
    logger.info(
        "recommend_offer called: source=%s listing=%s strategy=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
        safe_source_reference(strategy or ""),
    )
    try:
        ctx = await _deal_context(url_or_id, source, strategy)
        return recommend_context_offer(ctx).model_dump(mode="json")
    except Exception as exc:
        return _safe_failure("recommend_offer", exc)


async def generate_loi(
    url_or_id: str,
    price: float | None = None,
    earnest_money_pct: float | None = None,
    dd_days: int | None = None,
    closing_days: int | None = None,
    buyer_entity: str | None = None,
    state: str | None = None,
    source: str = "loopnet",
) -> dict:
    """Draft a complete, explained, non-binding LOI for attorney review.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        price: Proposed price; omit to use the offer recommendation's target.
        earnest_money_pct: Deposit as a percentage of price.
        dd_days: Proposed due-diligence period.
        closing_days: Proposed closing period after diligence.
        buyer_entity: Buyer legal entity or formation placeholder.
        state: Property-state override for jurisdiction notes.
        source: Registered source name. Defaults to LoopNet.

    Returns:
        A non-binding LoiDraft with markdown, term explanations, and attorney flags.
    """
    logger.info(
        "generate_loi called: source=%s listing=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        recommendation = recommend_context_offer(ctx)
        selected_price = price if price is not None else recommendation.target_price
        if selected_price is None:
            raise ValueError(
                "A price is required because the available deal data cannot derive a target"
            )
        terms: dict[str, Any] = {"price": selected_price}
        for key, value in (
            ("earnest_money_pct", earnest_money_pct),
            ("dd_days", dd_days),
            ("closing_days", closing_days),
            ("buyer_entity", buyer_entity),
            ("state", state),
        ):
            if value is not None:
                terms[key] = value
        return draft_loi(ctx, terms).model_dump(mode="json")
    except Exception as exc:
        return _safe_failure("generate_loi", exc)


async def find_contact(
    url_or_id: str,
    source: str = "loopnet",
) -> dict:
    """Find the listing broker, assessor owner, and available public entity contact.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        source: Registered source name. Defaults to LoopNet.

    Returns:
        A source-labeled ContactInfo package; paid skip-trace is optional.
    """
    logger.info(
        "find_contact called: source=%s listing=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        payload = (await assemble_contact(ctx)).model_dump(mode="json")
        tenant = current_context()
        if (
            tenant is not None
            and not tenant.trusted
            and tenant.profile in TERRITORY_LIMITED
        ):
            payload["owner_mailing"] = None
            registered_agent = payload.get("registered_agent")
            if isinstance(registered_agent, dict):
                registered_agent["address"] = None
                for principal in registered_agent.get("principals") or []:
                    if isinstance(principal, dict):
                        principal["address"] = None
            payload["subject_property"] = {
                "address": ctx.listing.address,
                "city": ctx.listing.city,
                "state": ctx.listing.state,
                "zip_code": ctx.listing.zip_code,
            }
        return payload
    except Exception as exc:
        return _safe_failure("find_contact", exc)


async def draft_outreach(
    url_or_id: str,
    channel: str = "email",
    angle: str | None = None,
    source: str = "loopnet",
) -> dict:
    """Draft deterministic, deal-specific call, email, or letter outreach.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        channel: One of call, email, or letter.
        angle: Optional buyer_direct, via_broker, absentee_owner, or off_market frame.
        source: Registered source name. Defaults to LoopNet.

    Returns:
        A complete OutreachDraft ending with the execution guardrail.
    """
    logger.info(
        "draft_outreach called: source=%s listing=%s channel=%s angle=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
        safe_source_reference(channel),
        safe_source_reference(angle or ""),
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        return (
            await compose_outreach(ctx, channel=channel, angle=angle)  # type: ignore[arg-type]
        ).model_dump(mode="json")
    except Exception as exc:
        return _safe_failure("draft_outreach", exc)


async def handle_counter(
    url_or_id: str,
    counter_text: str,
    source: str = "loopnet",
) -> dict:
    """Parse a seller counter and coach a guarded accept/counter/hold/walk response.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        counter_text: Seller or broker counter terms in ordinary text.
        source: Registered source name. Defaults to LoopNet.

    Returns:
        CounterAdvice with parsed meaning, verdict, reply, and explicit red flags.
    """
    logger.info(
        "handle_counter called: source=%s listing=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        return coach_counter(ctx, counter_text).model_dump(mode="json")
    except Exception as exc:
        return _safe_failure("handle_counter", exc)


async def financing_options(
    url_or_id: str,
    source: str = "loopnet",
) -> list[dict] | dict:
    """Screen and rank lender types that typically fund this specific asset.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        source: Registered source name. Defaults to LoopNet.

    Returns:
        Ranked eligible and ineligible FinancingOptions with FRED-anchored estimates.
    """
    logger.info(
        "financing_options called: source=%s listing=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        return [option.model_dump(mode="json") for option in screen_financing(ctx)]
    except Exception as exc:
        return _safe_failure("financing_options", exc)


async def qualify_me(
    url_or_id: str,
    net_worth: float,
    liquid: float,
    experience_deals: int = 0,
    credit_tier: str | None = None,
    source: str = "loopnet",
) -> dict:
    """Screen buyer cash, net worth, liquidity, experience, and optional credit tier.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        net_worth: Buyer/guarantor net worth in dollars.
        liquid: Buyer liquid funds available before closing in dollars.
        experience_deals: Prior directly relevant CRE deals completed.
        credit_tier: Optional poor, fair, good, very_good, or excellent tier.
        source: Registered source name. Defaults to LoopNet.

    Returns:
        QualifyResult with cash-to-close, explicit gates, gaps, and guidance.
    """
    logger.info(
        "qualify_me called: source=%s listing=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        result = screen_buyer(
            ctx,
            {
                "net_worth": net_worth,
                "liquid": liquid,
                "experience_deals": experience_deals,
                "credit_tier": credit_tier,
            },
        )
        return result.model_dump(mode="json", by_alias=True)
    except Exception as exc:
        return _safe_failure("qualify_me", exc)


async def size_debt(
    url_or_id: str,
    scenario: str = "agency",
    ltv: float | None = None,
    rate: float | None = None,
    amort_years: int | None = None,
    min_dscr: float | None = None,
    source: str = "loopnet",
) -> dict:
    """Size debt to the lesser of property-value LTV and NOI DSCR proceeds.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        scenario: Agency, bridge, or bank typical structure.
        ltv: Optional decimal (0.70) or percentage (70) override.
        rate: Optional decimal (0.07) or percentage (7) annual-rate override.
        amort_years: Optional positive amortization term override.
        min_dscr: Optional positive minimum DSCR override.
        source: Registered source name. Defaults to LoopNet.

    Returns:
        DebtSizing with constraints, proceeds, equity, returns, and assumptions.
    """
    logger.info(
        "size_debt called: source=%s listing=%s scenario=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
        safe_source_reference(scenario),
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        return size_context_debt(
            ctx,
            scenario,  # type: ignore[arg-type]
            ltv=ltv,
            rate=rate,
            amort_years=amort_years,
            min_dscr=min_dscr,
        ).model_dump(mode="json")
    except Exception as exc:
        return _safe_failure("size_debt", exc)


async def due_diligence_plan(
    url_or_id: str,
    dd_days: int = 30,
    start_date: str | None = None,
    source: str = "loopnet",
) -> dict:
    """Build and persist an asset-aware diligence checklist on a contract clock.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        dd_days: Positive number of calendar days in the diligence period.
        start_date: Optional ISO date (YYYY-MM-DD); defaults to today.
        source: Registered source name. Defaults to LoopNet.

    Returns:
        A persisted DDPlan with clear/terminate tests, specialists, and deadlines.
    """
    logger.info(
        "due_diligence_plan called: source=%s listing=%s dd_days=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
        dd_days,
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        plan = await build_diligence_plan(
            ctx,
            dd_days=dd_days,
            start_date=start_date,
            store=get_deal_store(),
        )
        return plan.model_dump(mode="json")
    except Exception as exc:
        return _safe_failure("due_diligence_plan", exc)


async def closing_plan(
    url_or_id: str,
    state: str | None = None,
    source: str = "loopnet",
) -> dict:
    """Build a state-routed entity-to-funding closing runway.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        state: Optional two-letter property-state override.
        source: Registered source name. Defaults to LoopNet.

    Returns:
        ClosingPlan with ordered professional gates and the wire-fraud protocol.
    """
    logger.info(
        "closing_plan called: source=%s listing=%s state=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
        safe_source_reference(state or ""),
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        return build_closing_plan(ctx, state=state).model_dump(mode="json")
    except Exception as exc:
        return _safe_failure("closing_plan", exc)


async def save_deal(
    url_or_id: str,
    source: str = "loopnet",
) -> dict:
    """Save or refresh a source listing in the persistent deal workspace.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        source: Registered source name. Defaults to LoopNet.

    Returns:
        The stable source-qualified deal_id, or an error dictionary.
    """
    logger.info(
        "save_deal called: source=%s listing=%s",
        safe_source_reference(source),
        safe_source_reference(url_or_id, source=source),
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        deal_id = await get_deal_store().save_deal(ctx.listing)
        if deal_id is None:
            raise RuntimeError("deal could not be persisted; check the SQLite path and logs")
        return {"deal_id": deal_id}
    except Exception as exc:
        return _safe_failure("save_deal", exc)


async def list_deals() -> dict:
    """List compact summaries from the persistent deal workspace.

    Returns:
        A consistent object containing deals and count, or an error dictionary.
    """
    logger.info("list_deals called")
    try:
        deals = await get_deal_store().list_deals()
        ctx = current_context()
        if (
            ctx is not None
            and not ctx.trusted
            and ctx.profile in TERRITORY_LIMITED
        ):
            deals = [{**deal, "last_note": None} for deal in deals]
        return {"deals": deals, "count": len(deals)}
    except Exception as exc:
        return _safe_failure("list_deals", exc)


__all__ = [
    "closing_plan",
    "draft_outreach",
    "due_diligence_plan",
    "find_contact",
    "financing_options",
    "generate_loi",
    "handle_counter",
    "list_deals",
    "qualify_me",
    "recommend_offer",
    "save_deal",
    "size_debt",
]
