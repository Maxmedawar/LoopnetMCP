"""Deterministic lender-type eligibility and typical-term screening."""

from __future__ import annotations

import math
import re
from typing import Any

from cre_mcp.execution.debt import anchored_rate
from cre_mcp.execution.guardrails import financing_guardrail
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import FinancingOption
from cre_mcp.scoring.rubrics import thresholds as T


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _raw_number(ctx: DealContext, *keys: str) -> float | None:
    for key in keys:
        if (number := _number(ctx.listing.raw.get(key))) is not None:
            return number
    return None


def _property_type(ctx: DealContext) -> str:
    return re.sub(r"[^a-z]+", "_", (ctx.listing.property_type or "").casefold()).strip("_")


def _is_multifamily(ctx: DealContext) -> bool:
    property_type = _property_type(ctx)
    return any(token in property_type for token in ("multifamily", "multi_family", "apartment"))


def _business_plan(ctx: DealContext) -> str:
    values = [
        ctx.listing.raw.get("business_plan"),
        ctx.listing.raw.get("strategy"),
        ctx.listing.raw.get("investment_strategy"),
        ctx.facts.strategy_hint if ctx.facts else None,
    ]
    return " ".join(str(value).casefold() for value in values if value)


def _is_transitional(ctx: DealContext) -> bool:
    plan = _business_plan(ctx)
    return ctx.listing.is_distressed or any(
        token in plan
        for token in (
            "value_add",
            "value-add",
            "renovation",
            "rehab",
            "lease_up",
            "lease-up",
            "transitional",
            "distressed",
        )
    )


def _occupancy_pct(ctx: DealContext) -> float | None:
    value = _raw_number(ctx, "occupancy_pct", "occupancy_rate", "physical_occupancy")
    if value is None:
        return None
    return value * 100 if 0 <= value <= 1 else value


def _is_stabilized(ctx: DealContext) -> tuple[bool, str]:
    explicit = ctx.listing.raw.get("stabilized")
    if isinstance(explicit, bool):
        return explicit, "the listing explicitly marks the asset as stabilized" if explicit else (
            "the listing explicitly marks the asset as not stabilized"
        )
    occupancy = _occupancy_pct(ctx)
    if occupancy is not None:
        return (
            occupancy >= T.FINANCING_STABILIZED_OCCUPANCY_PCT,
            f"reported occupancy is {occupancy:.1f}% versus the "
            f"{T.FINANCING_STABILIZED_OCCUPANCY_PCT:.1f}% screening floor",
        )
    if _is_transitional(ctx):
        return False, "the stated business plan is transitional/value-add"
    noi = ctx.underwriting.noi if ctx.underwriting else ctx.listing.noi_usd
    if noi is not None and noi > 0:
        return True, "stabilization is inferred from positive current NOI; verify trailing occupancy"
    return False, "stabilized operations cannot be verified from the available data"


def _owner_occupancy_pct(ctx: DealContext) -> float | None:
    explicit = ctx.listing.raw.get("owner_occupied")
    if isinstance(explicit, bool):
        return 100.0 if explicit else 0.0
    value = _raw_number(
        ctx,
        "owner_occupancy_pct",
        "owner_occupied_pct",
        "business_occupancy_pct",
    )
    if value is not None:
        return value * 100 if 0 <= value <= 1 else value
    status = str(ctx.listing.raw.get("occupancy_status", "")).casefold()
    return 100.0 if "owner" in status and "occup" in status else None


def _is_nnn_investment(ctx: DealContext) -> bool:
    plan = _business_plan(ctx)
    purity = ctx.facts.nnn_purity if ctx.facts else None
    text = " ".join(
        value.casefold()
        for value in (
            str(purity or ""),
            str(ctx.listing.raw.get("lease_type", "")),
            str(ctx.listing.raw.get("investment_type", "")),
            plan,
        )
    )
    investment_label = str(ctx.listing.raw.get("investment_type", "")).casefold()
    return any(
        token in text
        for token in ("nnn", "triple net", "absolute", "net lease")
    ) or any(
        token in investment_label
        for token in ("passive", "investment property", "leased investment")
    )


def _asset_value(ctx: DealContext) -> float | None:
    values = [ctx.listing.price_usd]
    if ctx.value_estimate is not None:
        values.append(ctx.value_estimate.mid or ctx.value_estimate.value)
    positive = [float(value) for value in values if value is not None and value > 0]
    return min(positive) if positive else None


def _option(
    ctx: DealContext,
    option_type: str,
    *,
    eligible: bool,
    strong: bool,
    eligibility_note: str,
    reason: str,
) -> FinancingOption:
    anchor = T.FINANCING_OPTION_RATE_ANCHOR[option_type]
    spread = T.FINANCING_OPTION_SPREAD_BPS[option_type]
    rate, rate_basis = anchored_rate(ctx, anchor, spread)
    return FinancingOption(
        type={
            "agency": "agency_multifamily",
            "bank": "bank_local",
            "cmbs": "cmbs_conduit",
            "bridge": "bridge_debt_fund",
            "sba": "sba_504_7a",
        }[option_type],
        fit="strong" if eligible and strong else "possible" if eligible else "not_eligible",
        eligible=eligible,
        typical_ltv_range=T.FINANCING_OPTION_LTV_RANGE_PCT[option_type],
        typical_rate=rate,
        rate_basis=rate_basis,
        amort_years=T.FINANCING_OPTION_AMORT_YEARS[option_type],
        io_available=T.FINANCING_OPTION_IO_AVAILABLE[option_type],
        recourse=T.FINANCING_OPTION_RECOURSE[option_type],
        eligibility_note=eligibility_note,
        why_or_why_not=reason,
        guardrail=financing_guardrail(
            "This is a lender-type screen using typical terms, not a named-lender match."
        ),
    )


def financing_options(ctx: DealContext) -> list[FinancingOption]:
    """Rank eligible and ineligible lender types for the subject asset."""
    units = ctx.listing.units
    if units is None:
        raw_units = _raw_number(ctx, "units", "number_of_units", "numberOfUnits")
        units = int(raw_units) if raw_units is not None else None
    multifamily = _is_multifamily(ctx)
    transitional = _is_transitional(ctx)
    stabilized, stabilization_note = _is_stabilized(ctx)
    value = _asset_value(ctx)
    property_type = _property_type(ctx) or "unknown property type"
    nnn_investment = _is_nnn_investment(ctx)
    owner_occupancy = _owner_occupancy_pct(ctx)

    agency_eligible = bool(
        multifamily
        and units is not None
        and units >= T.FINANCING_MIN_AGENCY_UNITS
        and stabilized
    )
    if not multifamily:
        agency_reason = "Agency here means Fannie/Freddie multifamily; this is not multifamily."
    elif units is None:
        agency_reason = "Unit count is missing; agency requires a verified 5+ unit property."
    elif units < T.FINANCING_MIN_AGENCY_UNITS:
        agency_reason = (
            f"The asset has {units} units; agency multifamily starts at "
            f"{T.FINANCING_MIN_AGENCY_UNITS} units."
        )
    elif not stabilized:
        agency_reason = f"Agency stabilization screen failed because {stabilization_note}."
    else:
        agency_reason = (
            f"The {units}-unit multifamily asset clears the initial stabilized agency screen; "
            "a lender must still underwrite occupancy, NOI, sponsor, and property condition."
        )

    bank_eligible = value is not None
    bank_reason = (
        f"Local and regional banks commonly evaluate smaller {property_type.replace('_', ' ')} "
        "assets, with lender-specific recourse and relationship requirements."
        if bank_eligible
        else "A bank screen needs a positive purchase price or value estimate."
    )

    cmbs_eligible = bool(
        value is not None
        and value >= T.FINANCING_CMBS_MIN_VALUE
        and stabilized
        and "land" not in property_type
    )
    if value is None:
        cmbs_reason = "CMBS cannot be screened without a value."
    elif value < T.FINANCING_CMBS_MIN_VALUE:
        cmbs_reason = (
            f"Value is ${value:,.0f}, below this engine's typical "
            f"${T.FINANCING_CMBS_MIN_VALUE:,.0f} conduit screen."
        )
    elif "land" in property_type:
        cmbs_reason = "Unstabilized land does not fit this conduit screen."
    elif not stabilized:
        cmbs_reason = f"CMBS requires stabilized cash flow; {stabilization_note}."
    else:
        cmbs_reason = (
            "Value and current operations clear the initial stabilized conduit screen; "
            "lease rollover, debt yield, reserves, and securitization structure still matter."
        )

    bridge_eligible = transitional
    bridge_reason = (
        "A transitional/value-add plan can fit short-term bridge or debt-fund execution, "
        "subject to renovation budget, carry, completion support, and exit financing."
        if bridge_eligible
        else "The available facts describe stabilized operations, so higher-cost bridge debt is not the primary fit."
    )

    sba_eligible = bool(
        not nnn_investment
        and owner_occupancy is not None
        and owner_occupancy >= T.FINANCING_SBA_EXISTING_OWNER_OCCUPANCY_PCT
    )
    if nnn_investment:
        sba_reason = (
            "Not eligible: a passive NNN/net-lease/investment property is tenant-occupied, not an "
            "owner-operated business property. SBA 504/7(a) is not investment-property debt."
        )
    elif owner_occupancy is None:
        sba_reason = (
            "Not eligible on current evidence: SBA requires owner occupancy, and no operating-"
            "business occupancy percentage is documented."
        )
    elif owner_occupancy < T.FINANCING_SBA_EXISTING_OWNER_OCCUPANCY_PCT:
        sba_reason = (
            f"Owner occupancy is {owner_occupancy:.1f}%, below the "
            f"{T.FINANCING_SBA_EXISTING_OWNER_OCCUPANCY_PCT:.1f}% existing-building rule."
        )
    else:
        sba_reason = (
            f"Reported owner occupancy is {owner_occupancy:.1f}%; an SBA lender must still "
            "verify the operating business, size, use of proceeds, guarantors, and eligibility."
        )

    ranked: list[tuple[int, FinancingOption]] = [
        (
            100 if agency_eligible else 10,
            _option(
                ctx,
                "agency",
                eligible=agency_eligible,
                strong=agency_eligible,
                eligibility_note="Fannie/Freddie multifamily: 5+ units and stabilized operations.",
                reason=agency_reason,
            ),
        ),
        (
            100 if bridge_eligible else 8,
            _option(
                ctx,
                "bridge",
                eligible=bridge_eligible,
                strong=bridge_eligible,
                eligibility_note="Transitional, renovation, lease-up, or value-add business plan.",
                reason=bridge_reason,
            ),
        ),
        (
            95 if sba_eligible else 5,
            _option(
                ctx,
                "sba",
                eligible=sba_eligible,
                strong=sba_eligible,
                eligibility_note="Operating-business owner occupancy; passive investment real estate excluded.",
                reason=sba_reason,
            ),
        ),
        (
            90 if cmbs_eligible else 9,
            _option(
                ctx,
                "cmbs",
                eligible=cmbs_eligible,
                strong=cmbs_eligible,
                eligibility_note="Stabilized commercial cash flow and typical value of at least $2 million.",
                reason=cmbs_reason,
            ),
        ),
        (
            80 if bank_eligible else 7,
            _option(
                ctx,
                "bank",
                eligible=bank_eligible,
                strong=bank_eligible and not transitional,
                eligibility_note="Broad commercial-property fit; local credit policy and recourse govern.",
                reason=bank_reason,
            ),
        ),
    ]
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [option for _, option in ranked]


__all__ = ["financing_options"]
