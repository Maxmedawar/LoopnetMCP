"""MCP boundaries for after-tax returns and post-close operating playbooks."""

from __future__ import annotations

import logging

from cre_mcp.deals.store import get_deal_store
from cre_mcp.models import Deal, DealContext
from cre_mcp.ops.playbook import operating_playbook as build_operating_playbook
from cre_mcp.tax.after_tax import after_tax_returns as calculate_after_tax_returns
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


async def after_tax_returns(
    url_or_id: str,
    marginal_rate: float = 0.37,
    bonus_pct: float | None = None,
    cost_seg: bool = False,
    hold_years: int = 5,
    source: str = "loopnet",
) -> dict:
    """Compare transparent pre-tax and after-tax CRE return scenarios.

    Args:
        url_or_id: Listing URL or source-specific identifier.
        marginal_rate: Investor ordinary marginal rate, decimal or percentage.
        bonus_pct: Optional explicit bonus-depreciation percentage; omitted means none assumed.
        cost_seg: Model simplified 5/7/15-year cost-seg components; requires a real study.
        hold_years: Ownership scenario length from 1 through 50 years.
        source: Registered listing source.

    Returns:
        AfterTaxResult with canonical pre_tax_irr, after_tax_irr, depreciation_annual,
        recapture_1250, detailed schedules/taxes, assumptions, and the CPA gate.
    """
    logger.info("after_tax_returns called: source=%s listing=%s", source, url_or_id)
    try:
        ctx = await _deal_context(url_or_id, source)
        assumptions = {
            "marginal_rate": marginal_rate,
            "bonus_pct": bonus_pct,
            "cost_seg": cost_seg,
            "hold_years": hold_years,
        }
        return calculate_after_tax_returns(ctx, assumptions).model_dump(mode="json")
    except Exception as exc:
        logger.error("after_tax_returns error: %s", exc)
        return {"error": str(exc)}


async def operating_playbook(
    url_or_id: str,
    source: str = "loopnet",
) -> dict:
    """Generate and persist an asset-aware post-close operating runway.

    Args:
        url_or_id: Listing URL or source-specific identifier.
        source: Registered listing source.

    Returns:
        Month-one, recurring, lease-critical, and strategic reminders with professional gates.
    """
    logger.info("operating_playbook called: source=%s listing=%s", source, url_or_id)
    try:
        ctx = await _deal_context(url_or_id, source)
        return (
            await build_operating_playbook(ctx, store=get_deal_store())
        ).model_dump(mode="json")
    except Exception as exc:
        logger.error("operating_playbook error: %s", exc)
        return {"error": str(exc)}


__all__ = ["after_tax_returns", "operating_playbook"]
