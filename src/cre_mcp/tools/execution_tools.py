"""MCP boundaries for offers, contacts, outreach, counters, and LOI drafts."""

import logging
from typing import Any

from cre_mcp.execution.contacts import find_contact as assemble_contact
from cre_mcp.execution.loi import generate_loi as draft_loi
from cre_mcp.execution.negotiate import handle_counter as coach_counter
from cre_mcp.execution.offer import recommend_offer as recommend_context_offer
from cre_mcp.execution.outreach import draft_outreach as compose_outreach
from cre_mcp.models import Deal, DealContext
from cre_mcp.tools.deal_tools import analyze_deal

logger = logging.getLogger(__name__)


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
        source,
        url_or_id,
        strategy,
    )
    try:
        ctx = await _deal_context(url_or_id, source, strategy)
        return recommend_context_offer(ctx).model_dump(mode="json")
    except Exception as exc:
        logger.error("recommend_offer error: %s", exc)
        return {"error": str(exc)}


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
    logger.info("generate_loi called: source=%s listing=%s", source, url_or_id)
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
        logger.error("generate_loi error: %s", exc)
        return {"error": str(exc)}


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
    logger.info("find_contact called: source=%s listing=%s", source, url_or_id)
    try:
        ctx = await _deal_context(url_or_id, source)
        return (await assemble_contact(ctx)).model_dump(mode="json")
    except Exception as exc:
        logger.error("find_contact error: %s", exc)
        return {"error": str(exc)}


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
        source,
        url_or_id,
        channel,
        angle,
    )
    try:
        ctx = await _deal_context(url_or_id, source)
        return (
            await compose_outreach(ctx, channel=channel, angle=angle)  # type: ignore[arg-type]
        ).model_dump(mode="json")
    except Exception as exc:
        logger.error("draft_outreach error: %s", exc)
        return {"error": str(exc)}


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
    logger.info("handle_counter called: source=%s listing=%s", source, url_or_id)
    try:
        ctx = await _deal_context(url_or_id, source)
        return coach_counter(ctx, counter_text).model_dump(mode="json")
    except Exception as exc:
        logger.error("handle_counter error: %s", exc)
        return {"error": str(exc)}


__all__ = [
    "draft_outreach",
    "find_contact",
    "generate_loi",
    "handle_counter",
    "recommend_offer",
]
