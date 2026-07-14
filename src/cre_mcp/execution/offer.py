"""Underwriting-grounded offer range recommendation."""

from __future__ import annotations

import math
from statistics import median
from typing import Any

from cre_mcp.execution.guardrails import execution_guardrail
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import OfferRecommendation
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.scoring.signals import owner_absentee, owner_tenure_years
from cre_mcp.underwriting.metrics import mortgage_constant


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _raw_number(ctx: DealContext, *keys: str) -> float | None:
    for key in keys:
        value = _number(ctx.listing.raw.get(key))
        if value is not None:
            return value
    return None


def _deal_ref(ctx: DealContext) -> str:
    return f"{ctx.listing.source}:{ctx.listing.source_id}"


def _strategy(ctx: DealContext) -> str:
    explicit = ctx.listing.raw.get("strategy")
    if isinstance(explicit, str) and explicit in T.OFFER_TARGET_CAP_PCT_BY_STRATEGY:
        return explicit
    if ctx.listing.is_distressed:
        return "distressed"
    property_type = (ctx.listing.property_type or "").casefold()
    if property_type in {"multifamily", "multi-family", "apartment"}:
        return "value_add_multifamily"
    if property_type == "retail":
        nnn_keys = {
            "tenant_credit_rating",
            "lease_years_remaining",
            "lease_type",
            "guaranty_type",
        }
        return (
            "nnn_retail"
            if nnn_keys.intersection(ctx.listing.raw)
            else "location_retail"
        )
    return "core"


def _credit_band(ctx: DealContext) -> tuple[float, float] | None:
    rating = (
        ctx.underwriting.tenant_credit_tier
        if ctx.underwriting and ctx.underwriting.tenant_credit_tier
        else ctx.listing.raw.get("tenant_credit_rating")
    )
    if not rating:
        return None
    normalized = str(rating).upper()
    if normalized.startswith(("AAA", "AA")):
        return T.NNN_CAP_RATE_RANGES["AAA_AA"]
    if normalized.startswith("A"):
        return T.NNN_CAP_RATE_RANGES["A"]
    if normalized.startswith("BBB"):
        return T.NNN_CAP_RATE_RANGES["BBB"]
    return T.NNN_CAP_RATE_RANGES["SUB_IG"]


def _treasury(ctx: DealContext) -> float | None:
    if ctx.market is None or ctx.market.treasury_10yr is None:
        return None
    return _number(ctx.market.treasury_10yr.value)


def _cap_targets(ctx: DealContext, strategy: str) -> tuple[float, float]:
    target = T.OFFER_TARGET_CAP_PCT_BY_STRATEGY[strategy]
    walk = T.OFFER_WALK_CAP_PCT_BY_STRATEGY[strategy]
    if strategy == "nnn_retail" and (band := _credit_band(ctx)) is not None:
        low, high = band
        target = low + (high - low) * T.OFFER_NNN_TARGET_BAND_POSITION
        walk = low + (high - low) * T.OFFER_NNN_WALK_BAND_POSITION
    treasury = _treasury(ctx)
    if treasury is not None:
        target = max(
            target,
            treasury + T.OFFER_TARGET_TREASURY_SPREAD_BPS / 100,
        )
        walk = max(
            walk,
            treasury + T.OFFER_WALK_TREASURY_SPREAD_BPS / 100,
        )
    return target, min(target, walk)


def _sale_comp_value(ctx: DealContext) -> float | None:
    if ctx.value_estimate is not None:
        estimated = _number(ctx.value_estimate.mid or ctx.value_estimate.value)
        if estimated is not None and estimated > 0:
            return estimated
    direct = _raw_number(ctx, "market_value", "avm", "sale_comp_value")
    if direct is not None and direct > 0:
        return direct
    values: list[float] = []
    for key in ("sale_comps", "comps"):
        rows = ctx.listing.raw.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            value = (
                _number(row.get("sale_price") or row.get("price"))
                if isinstance(row, dict)
                else _number(row)
            )
            if value is not None and value > 0:
                values.append(value)
    return median(values) if values else None


def _assumption(ctx: DealContext, key: str) -> float | None:
    if ctx.underwriting is None:
        return None
    item = ctx.underwriting.assumptions_used.get(key)
    return _number(item.get("value")) if isinstance(item, dict) else None


def _dscr_price_limit(
    ctx: DealContext,
    noi: float | None,
    strategy: str,
) -> float | None:
    if noi is None or noi <= 0:
        return None
    ltv = _assumption(ctx, "ltv")
    rate = _assumption(ctx, "annual_interest_rate")
    amortization = _assumption(ctx, "amortization_years")
    minimum_dscr = T.OFFER_MIN_DSCR_BY_STRATEGY[strategy]
    constant = mortgage_constant(
        rate,
        int(amortization) if amortization is not None else None,
    )
    if ltv is None or not 0 < ltv < 1 or constant is None or constant <= 0:
        return None
    maximum_debt_service = noi / minimum_dscr
    maximum_loan = maximum_debt_service / constant
    return maximum_loan / ltv


def _motivation(ctx: DealContext) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if owner_absentee(ctx) == 1:
        reasons.append("public assessor data indicates absentee ownership")
    tenure = owner_tenure_years(ctx)
    if tenure is not None and tenure >= T.OFFER_MOTIVATION_LONG_TENURE_YEARS:
        reasons.append(f"ownership tenure is about {tenure:.1f} years")
    reductions = ctx.listing.raw.get("price_reductions")
    if (
        isinstance(reductions, list)
        and len(reductions) >= T.OFFER_MOTIVATION_PRICE_CUT_COUNT
    ):
        reasons.append(f"the listing shows {len(reductions)} price cut(s)")
    days = _raw_number(ctx, "days_on_market")
    if days is not None and days >= T.OFFER_MOTIVATION_DOM_DAYS:
        reasons.append(f"the listing has been marketed for {days:.0f} days")
    buffer = min(
        T.OFFER_MAX_OPEN_BUFFER_PCT,
        T.OFFER_OPEN_BUFFER_PCT
        + len(reasons) * T.OFFER_MOTIVATION_BUFFER_PER_SIGNAL_PCT,
    )
    return buffer, reasons


def _round_price(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    increment = T.OFFER_PRICE_ROUNDING_INCREMENT
    if value < increment:
        return round(value, 2)
    return math.floor(value / increment) * increment


def _confidence(
    ctx: DealContext,
    *,
    ask: float | None,
    noi: float | None,
    comp_value: float | None,
) -> float:
    present = {
        "ask_price": ask is not None,
        "noi": noi is not None,
        "underwriting": bool(
            ctx.underwriting
            and any(
                value is not None
                for value in (
                    ctx.underwriting.cap_rate,
                    ctx.underwriting.dscr,
                    ctx.underwriting.price_per_sf,
                )
            )
        ),
        "market_context": ctx.market is not None,
        "sale_comps": comp_value is not None,
    }
    return round(
        sum(
            T.OFFER_CONFIDENCE_WEIGHTS[key]
            for key, available in present.items()
            if available
        ),
        4,
    )


def _key_terms(strategy: str) -> dict[str, Any]:
    minimum_dscr = T.OFFER_MIN_DSCR_BY_STRATEGY[strategy]
    return {
        "earnest_money": {
            "range_pct": list(T.OFFER_EARNEST_MONEY_PCT_RANGE),
            "reason": (
                "Enough to show seriousness while limiting capital at risk before "
                "diligence."
            ),
        },
        "due_diligence": {
            "range_days": list(T.OFFER_DD_DAYS_RANGE),
            "reason": (
                "Time to inspect title, leases, physical condition, zoning, and "
                "environmental risk."
            ),
        },
        "financing_contingency": {
            "stance": "retain_until_written_lender_commitment",
            "reason": (
                "Protect the deposit until the lender confirms proceeds, pricing, "
                f"and at least {minimum_dscr:.2f}x DSCR."
            ),
        },
        "closing_timeline": {
            "range_days": list(T.OFFER_CLOSE_DAYS_RANGE),
            "reason": (
                "A conventional window for lender, title, survey, and entity work "
                "after diligence."
            ),
        },
        "strategy": strategy,
        "next_step_gate": execution_guardrail(
            "send the range to your lender for a proceeds check, then have CRE "
            "counsel shape the LOI."
        ),
    }


def _currency(value: float | None) -> str:
    return f"${value:,.0f}" if value is not None else "unavailable"


def _cap(value: float | None) -> str:
    return f"{value:.2f}%" if value is not None else "unavailable"


def recommend_offer(ctx: DealContext) -> OfferRecommendation:
    """Return an open/target/walk range from available facts without inventing data."""
    strategy = _strategy(ctx)
    ask = ctx.listing.price_usd
    noi = (
        ctx.underwriting.noi
        if ctx.underwriting and ctx.underwriting.noi is not None
        else ctx.listing.noi_usd
    )
    comp_value = _sale_comp_value(ctx)
    target_cap_basis, walk_cap_basis = _cap_targets(ctx, strategy)
    dscr_limit = _dscr_price_limit(ctx, noi, strategy)
    pricing_basis = "current NOI and strategy cap-rate thresholds"
    uses_yield_on_cost = False

    target_price: float | None = None
    walk_price: float | None = None
    if strategy == "value_add_multifamily":
        stabilized_noi = _raw_number(ctx, "stabilized_noi")
        capex = _raw_number(ctx, "renovation_capex")
        if stabilized_noi is not None and stabilized_noi > 0 and capex is not None:
            target_price = (
                stabilized_noi / (T.OFFER_VAM_TARGET_YOC_PCT / 100) - capex
            )
            walk_price = stabilized_noi / (T.OFFER_VAM_WALK_YOC_PCT / 100) - capex
            pricing_basis = (
                "stabilized NOI, renovation capex, and yield-on-cost thresholds"
            )
            uses_yield_on_cost = True

    if target_price is None and noi is not None and noi > 0:
        target_price = noi / (target_cap_basis / 100)
        walk_price = noi / (walk_cap_basis / 100)
    elif target_price is None and ask is not None and ask > 0:
        target_price = ask * (1 - T.OFFER_MISSING_NOI_TARGET_DISCOUNT_PCT)
        walk_price = ask * T.OFFER_WALK_MAX_ASK_MULTIPLIER
        pricing_basis = "asking price fallback because reliable NOI is unavailable"

    if target_price is not None and ask is not None:
        target_price = min(
            target_price,
            ask * T.OFFER_TARGET_MAX_ASK_MULTIPLIER,
        )
    if walk_price is not None and ask is not None:
        walk_price = min(
            walk_price,
            ask * T.OFFER_WALK_MAX_ASK_MULTIPLIER,
        )
    if comp_value is not None:
        if target_price is not None:
            target_price = min(
                target_price,
                comp_value * T.OFFER_COMP_TARGET_MAX_MULTIPLIER,
            )
        if walk_price is not None:
            walk_price = min(
                walk_price,
                comp_value * T.OFFER_COMP_WALK_MAX_MULTIPLIER,
            )
    if dscr_limit is not None:
        if walk_price is not None:
            walk_price = min(walk_price, dscr_limit)
        if target_price is not None:
            target_price = min(
                target_price,
                dscr_limit * T.OFFER_TARGET_DSCR_HEADROOM_MULTIPLIER,
            )
    if (
        target_price is not None
        and walk_price is not None
        and target_price >= walk_price
    ):
        target_price = walk_price * (1 - T.OFFER_TARGET_TO_WALK_MARGIN_PCT)

    buffer, motivation_reasons = _motivation(ctx)
    open_price = target_price * (1 - buffer) if target_price is not None else None
    walk_price = _round_price(walk_price)
    target_price = _round_price(target_price)
    if (
        target_price is not None
        and walk_price is not None
        and target_price >= walk_price
    ):
        target_price = _round_price(
            walk_price * (1 - T.OFFER_TARGET_TO_WALK_MARGIN_PCT)
        )
    open_price = _round_price(
        target_price * (1 - buffer) if target_price is not None else open_price
    )

    def cap_at(price: float | None) -> float | None:
        return round(100 * noi / price, 4) if noi is not None and price else None

    open_cap = cap_at(open_price)
    target_cap = cap_at(target_price)
    walk_cap = cap_at(walk_price)
    ask_cap = cap_at(ask)
    rationale_parts = [
        (
            f"The ask is {_currency(ask)} at {_cap(ask_cap)} based on "
            f"{_currency(noi)} of current NOI."
            if ask is not None and noi is not None
            else (
                f"The asking price is {_currency(ask)} and reliable current NOI is "
                f"{_currency(noi)}."
            )
        ),
        (
            f"Target {_currency(target_price)} produces {_cap(target_cap)} using "
            f"{pricing_basis}; open at {_currency(open_price)} ({_cap(open_cap)}) "
            f"with a {buffer * 100:.1f}% negotiation buffer."
        ),
    ]
    if uses_yield_on_cost:
        walk_guardrail = (
            f"the {T.OFFER_VAM_WALK_YOC_PCT:.2f}% minimum stabilized "
            "yield-on-cost"
        )
    else:
        walk_guardrail = f"the {walk_cap_basis:.2f}% minimum cap"
    rationale_parts.append(
        f"Walk at {_currency(walk_price)} ({_cap(walk_cap)}), the highest modeled "
        f"price that still respects {walk_guardrail} and "
        f"{T.OFFER_MIN_DSCR_BY_STRATEGY[strategy]:.2f}x DSCR guardrail."
    )
    if motivation_reasons:
        rationale_parts.append(
            "The opening buffer is wider because " + "; ".join(motivation_reasons) + "."
        )
    if dscr_limit is not None:
        rationale_parts.append(
            f"The financing math independently caps value near {_currency(dscr_limit)} "
            "under the underwriting LTV, rate, and amortization assumptions."
        )
    rationale_parts.append(
        execution_guardrail(
            "verify NOI and the lender's proceeds before treating the walk price as spendable."
        )
    )

    caveats: list[str] = []
    if comp_value is None:
        caveats.append(
            "A usable sale-comp value estimate is unavailable; this range leans on NOI, "
            "strategy cap thresholds, market rates, and the ask."
        )
    if noi is None:
        caveats.append(
            "Reliable NOI is unavailable, so cap rates and DSCR could not anchor the range."
        )
    if ctx.market is None:
        caveats.append(
            "Market-rate context is unavailable; confirm current debt pricing with a lender."
        )
    caveats.append(
        execution_guardrail(
            "confirm financing next and have a CRE attorney review any terms before signature."
        )
    )
    return OfferRecommendation(
        deal_ref=_deal_ref(ctx),
        open_price=open_price,
        target_price=target_price,
        walk_price=walk_price,
        open_cap=open_cap,
        target_cap=target_cap,
        walk_cap=walk_cap,
        rationale=" ".join(rationale_parts),
        key_terms=_key_terms(strategy),
        confidence=_confidence(
            ctx,
            ask=ask,
            noi=noi,
            comp_value=comp_value,
        ),
        caveats=caveats,
    )


__all__ = ["recommend_offer"]
