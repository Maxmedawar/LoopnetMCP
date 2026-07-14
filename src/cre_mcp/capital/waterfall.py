"""Deterministic LP/GP waterfall scenario modeling."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.capital.guardrails import (
    ANTI_FRAUD_WARNING,
    reject_unsubstantiated_performance_claims,
)
from cre_mcp.execution.guardrails import capital_guardrail
from cre_mcp.models.capital import WaterfallResult, WaterfallYear
from cre_mcp.models.deals import DealContext
from cre_mcp.underwriting.metrics import equity_multiple, levered_irr

DEFAULT_HOLD_YEARS = 5
DEFAULT_LTV = 0.70


def _number(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} is required")
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _fraction(value: Any, label: str, *, allow_zero: bool = True) -> float:
    number = _number(value, label)
    normalized = number / 100 if number > 1 else number
    minimum_ok = normalized >= 0 if allow_zero else normalized > 0
    if not minimum_ok or normalized > 1:
        qualifier = "between 0 and 100" if allow_zero else "greater than 0 and at most 100"
        raise ValueError(f"{label} must be a decimal or percentage {qualifier}")
    return normalized


def _first(values: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in values and values[key] is not None:
            return values[key]
    return None


def _deal_values(deal: DealContext | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(deal, DealContext):
        raw = dict(deal.listing.raw)
        return {
            "deal_ref": f"{deal.listing.source}:{deal.listing.source_id}",
            "price": deal.listing.price_usd,
            "noi": (
                deal.underwriting.noi
                if deal.underwriting is not None
                else deal.listing.noi_usd
            ),
            "annual_debt_service": (
                deal.underwriting.annual_debt_service
                if deal.underwriting is not None
                else None
            ),
            "cash_flows": raw.get("levered_cash_flows"),
            **raw,
        }
    values = dict(deal)
    listing = values.get("listing")
    if isinstance(listing, Mapping):
        values = {**dict(listing), **values}
    source = values.get("source")
    source_id = values.get("source_id")
    values.setdefault(
        "deal_ref",
        f"{source}:{source_id}" if source and source_id else "UNASSIGNED DEAL",
    )
    return values


def _total_equity(deal: Mapping[str, Any], structure: Mapping[str, Any]) -> tuple[float, str]:
    supplied = _first(
        structure,
        ("total_equity", "equity_required", "equity"),
    )
    if supplied is None:
        supplied = _first(deal, ("total_equity", "equity_required", "equity"))
    if supplied is not None:
        amount = _number(supplied, "total_equity")
        if amount <= 0:
            raise ValueError("total_equity must be greater than zero")
        return amount, str(structure.get("total_equity_source") or "caller/deal supplied")
    price_value = _first(deal, ("price", "price_usd", "asking_price"))
    price = _number(price_value, "deal price")
    if price <= 0:
        raise ValueError("deal price must be greater than zero")
    ltv = _fraction(structure.get("ltv", DEFAULT_LTV), "ltv")
    equity = price * (1 - ltv)
    if equity <= 0:
        raise ValueError("price and LTV produce no invested equity")
    return equity, f"deal price less {ltv:.1%} scenario debt"


def _annual_cash(
    deal: Mapping[str, Any],
    structure: Mapping[str, Any],
    total_equity: float,
) -> tuple[list[float], str, float | None]:
    raw_flows = _first(structure, ("annual_cash_flows", "cash_flows"))
    if raw_flows is None:
        raw_flows = _first(deal, ("annual_cash_flows", "cash_flows"))
    if raw_flows is not None:
        if not isinstance(raw_flows, Sequence) or isinstance(raw_flows, (str, bytes)):
            raise ValueError("annual_cash_flows must be a list")
        flows = [_number(item, "annual cash flow") for item in raw_flows]
        if flows and flows[0] < 0:
            flows = flows[1:]
        if not flows:
            raise ValueError("annual_cash_flows must contain at least one distribution year")
        if any(item < 0 for item in flows):
            raise ValueError("annual distributable cash cannot be negative")
        exit_proceeds = _first(structure, ("exit_proceeds", "exit_equity_proceeds"))
        if exit_proceeds is not None:
            exit_amount = _number(exit_proceeds, "exit_proceeds")
            if exit_amount < 0:
                raise ValueError("exit_proceeds cannot be negative")
            flows[-1] += exit_amount
            return flows, "supplied annual cash flows plus supplied exit proceeds", exit_amount
        return flows, "supplied annual cash flows (assumed to include any terminal proceeds)", None

    hold_years = int(structure.get("hold_years", DEFAULT_HOLD_YEARS))
    if hold_years <= 0 or hold_years > 50:
        raise ValueError("hold_years must be between 1 and 50")
    scalar = _first(structure, ("annual_cash_flow", "annual_distributable_cash"))
    if scalar is not None:
        annual = _number(scalar, "annual_cash_flow")
        source = str(
            structure.get("annual_cash_flow_source")
            or "caller-supplied flat annual distributable cash"
        )
    else:
        noi_value = _first(deal, ("noi", "noi_usd"))
        noi = _number(noi_value, "NOI") if noi_value is not None else 0.0
        debt_value = _first(deal, ("annual_debt_service", "debt_service"))
        debt_service = _number(debt_value, "annual_debt_service") if debt_value is not None else 0.0
        annual = max(noi - debt_service, 0.0)
        source = "flat current NOI less available modeled annual debt service"
    if annual < 0:
        raise ValueError("annual_cash_flow cannot be negative")
    flows = [annual for _ in range(hold_years)]
    exit_value = _first(structure, ("exit_proceeds", "exit_equity_proceeds"))
    if exit_value is None:
        exit_amount = total_equity
        exit_source = "flat invested-equity recovery; no appreciation assumed"
    else:
        exit_amount = _number(exit_value, "exit_proceeds")
        if exit_amount < 0:
            raise ValueError("exit_proceeds cannot be negative")
        exit_source = "caller-supplied exit equity proceeds"
    flows[-1] += exit_amount
    return flows, f"{source}; {exit_source}", exit_amount


def _tiers(structure: Mapping[str, Any], base_lp_split: float) -> list[dict[str, float]]:
    raw = structure.get("tiered_splits", structure.get("tiers", []))
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("tiered_splits must be a list of mappings")
    parsed: list[dict[str, float]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("each tiered split must be a mapping")
        hurdle = _fraction(
            _first(item, ("lp_irr_hurdle", "hurdle_irr", "hurdle")),
            "tier hurdle",
            allow_zero=False,
        )
        lp_split = _fraction(
            _first(item, ("lp_split", "lp_share")),
            "tier lp_split",
        )
        gp_value = _first(item, ("gp_split", "gp_share"))
        gp_split = 1 - lp_split if gp_value is None else _fraction(gp_value, "tier gp_split")
        if not math.isclose(lp_split + gp_split, 1.0, abs_tol=1e-9):
            raise ValueError("each tier LP and GP split must sum to 100%")
        parsed.append({"hurdle": hurdle, "lp_split": lp_split, "gp_split": gp_split})
    parsed.sort(key=lambda item: item["hurdle"])
    if parsed and base_lp_split <= 0:
        raise ValueError("base LP residual split must be positive when tiers are used")
    return parsed


def _lp_needed_at_hurdle(
    prior_lp_cash_flows: list[float],
    current_lp_distribution: float,
    year: int,
    hurdle: float,
) -> float:
    previous_npv = sum(
        cash / ((1 + hurdle) ** period)
        for period, cash in enumerate(prior_lp_cash_flows)
    )
    required_current_distribution = -previous_npv * ((1 + hurdle) ** year)
    return max(required_current_distribution - current_lp_distribution, 0.0)


def _allocate_residual(
    available: float,
    *,
    year: int,
    prior_lp_cash_flows: list[float],
    lp_distribution_so_far: float,
    base_lp_split: float,
    tiers: list[dict[str, float]],
    gp_equity_share: float,
) -> tuple[float, float, float]:
    lp_total = 0.0
    gp_total = 0.0
    promote = 0.0
    remaining = available
    lp_split = base_lp_split
    gp_split = 1 - lp_split
    for tier in tiers:
        lp_needed = _lp_needed_at_hurdle(
            prior_lp_cash_flows,
            lp_distribution_so_far + lp_total,
            year,
            tier["hurdle"],
        )
        total_needed = lp_needed / lp_split if lp_split > 0 else math.inf
        chunk = min(remaining, total_needed)
        lp_chunk = chunk * lp_split
        gp_chunk = chunk * gp_split
        lp_total += lp_chunk
        gp_total += gp_chunk
        promote += max(gp_chunk - chunk * gp_equity_share, 0.0)
        remaining -= chunk
        if remaining <= 1e-9 or chunk + 1e-9 < total_needed:
            return lp_total, gp_total, promote
        lp_split = tier["lp_split"]
        gp_split = tier["gp_split"]
    if remaining > 0:
        lp_chunk = remaining * lp_split
        gp_chunk = remaining * gp_split
        lp_total += lp_chunk
        gp_total += gp_chunk
        promote += max(gp_chunk - remaining * gp_equity_share, 0.0)
    return lp_total, gp_total, promote


def _money(value: float) -> float:
    rounded = round(value, 2)
    return 0.0 if rounded == 0 else rounded


def model_waterfall(
    deal: DealContext | Mapping[str, Any],
    structure: Mapping[str, Any],
) -> WaterfallResult:
    """Allocate scenario cash through pref, capital, catch-up, and split tiers."""
    deal_data = _deal_values(deal)
    terms = dict(structure)
    reject_unsubstantiated_performance_claims(deal_data, terms)
    total_equity, equity_source = _total_equity(deal_data, terms)
    lp_share = _fraction(terms.get("lp_equity_pct", terms.get("lp_share", 1.0)), "lp_equity_pct", allow_zero=False)
    pref_rate = _fraction(
        _first(terms, ("pref", "preferred_return", "preferred_return_rate"))
        if _first(terms, ("pref", "preferred_return", "preferred_return_rate")) is not None
        else 0.08,
        "preferred return",
    )
    promote_rate = _fraction(
        _first(terms, ("gp_promote", "promote", "carry"))
        if _first(terms, ("gp_promote", "promote", "carry")) is not None
        else 0.20,
        "gp promote",
    )
    if promote_rate >= 1:
        raise ValueError("gp promote must be below 100%")
    catch_up = bool(terms.get("catch_up", True))
    base_lp_split = _fraction(
        terms.get("lp_residual_split", 1 - promote_rate),
        "lp_residual_split",
        allow_zero=False,
    )
    gp_residual_value = terms.get("gp_residual_split")
    if gp_residual_value is not None:
        gp_residual_split = _fraction(gp_residual_value, "gp_residual_split")
        if not math.isclose(base_lp_split + gp_residual_split, 1.0, abs_tol=1e-9):
            raise ValueError("base LP and GP residual splits must sum to 100%")
    tier_terms = _tiers(terms, base_lp_split)
    annual_cash, cash_source, exit_amount = _annual_cash(deal_data, terms, total_equity)

    lp_contribution = total_equity * lp_share
    gp_contribution = total_equity - lp_contribution
    lp_unreturned = lp_contribution
    gp_unreturned = gp_contribution
    unpaid_pref = 0.0
    cumulative_pref_paid = 0.0
    cumulative_gp_catchup = 0.0
    promote_earned = 0.0
    undistributed = 0.0
    years: list[WaterfallYear] = []
    lp_cash_flows = [-lp_contribution]
    gp_cash_flows = [-gp_contribution]
    gp_equity_share = gp_contribution / total_equity

    for year, cash in enumerate(annual_cash, start=1):
        available = cash
        unpaid_pref += lp_unreturned * pref_rate
        pref_paid = min(available, unpaid_pref)
        unpaid_pref -= pref_paid
        available -= pref_paid
        cumulative_pref_paid += pref_paid

        lp_return = 0.0
        gp_return = 0.0
        total_unreturned = lp_unreturned + gp_unreturned
        if available > 0 and total_unreturned > 0:
            capital_paid = min(available, total_unreturned)
            lp_return = capital_paid * (lp_unreturned / total_unreturned)
            gp_return = capital_paid - lp_return
            lp_unreturned = max(lp_unreturned - lp_return, 0.0)
            gp_unreturned = max(gp_unreturned - gp_return, 0.0)
            available -= capital_paid

        gp_catchup = 0.0
        if catch_up and available > 0 and promote_rate > 0:
            catchup_target = cumulative_pref_paid * promote_rate / (1 - promote_rate)
            catchup_due = max(catchup_target - cumulative_gp_catchup, 0.0)
            gp_catchup = min(available, catchup_due)
            cumulative_gp_catchup += gp_catchup
            promote_earned += gp_catchup
            available -= gp_catchup

        lp_before_residual = pref_paid + lp_return
        lp_residual, gp_residual, residual_promote = _allocate_residual(
            available,
            year=year,
            prior_lp_cash_flows=lp_cash_flows,
            lp_distribution_so_far=lp_before_residual,
            base_lp_split=base_lp_split,
            tiers=tier_terms,
            gp_equity_share=gp_equity_share,
        )
        promote_earned += residual_promote
        allocated_residual = lp_residual + gp_residual
        available = max(available - allocated_residual, 0.0)
        undistributed += available
        lp_distribution = lp_before_residual + lp_residual
        gp_distribution = gp_return + gp_catchup + gp_residual
        lp_cash_flows.append(lp_distribution)
        gp_cash_flows.append(gp_distribution)
        years.append(
            WaterfallYear(
                year=year,
                available_cash=_money(cash),
                lp_preferred_return=_money(pref_paid),
                lp_return_of_capital=_money(lp_return),
                gp_return_of_capital=_money(gp_return),
                gp_catch_up=_money(gp_catchup),
                lp_residual=_money(lp_residual),
                gp_residual=_money(gp_residual),
                lp_distribution=_money(lp_distribution),
                gp_distribution=_money(gp_distribution),
                unpaid_lp_preferred_return=_money(unpaid_pref),
                unreturned_lp_capital=_money(lp_unreturned),
                unreturned_gp_capital=_money(gp_unreturned),
            )
        )

    lp_irr = levered_irr(lp_cash_flows)
    lp_multiple = equity_multiple(sum(lp_cash_flows[1:]), lp_contribution)
    return WaterfallResult(
        deal_ref=str(deal_data.get("deal_ref") or "UNASSIGNED DEAL"),
        total_equity=_money(total_equity),
        lp_contribution=_money(lp_contribution),
        gp_contribution=_money(gp_contribution),
        preferred_return_rate=pref_rate,
        gp_promote_rate=promote_rate,
        catch_up=catch_up,
        years=years,
        lp_cash_flows=[_money(item) for item in lp_cash_flows],
        gp_cash_flows=[_money(item) for item in gp_cash_flows],
        lp_irr_pct=round(lp_irr, 6) if lp_irr is not None else None,
        lp_equity_multiple=round(lp_multiple, 6) if lp_multiple is not None else None,
        gp_promote_earned=_money(promote_earned),
        undistributed_cash=_money(undistributed),
        assumptions_used={
            "equity": {"value": total_equity, "source": equity_source},
            "lp_equity_pct": lp_share,
            "preferred_return_rate": pref_rate,
            "preferred_return_basis": "annual simple accrual on unreturned LP capital; unpaid amount carries forward without compounding",
            "return_of_capital": "LP/GP pro rata to unreturned contributions after LP preferred return",
            "catch_up": "GP catch-up to the promote percentage of cumulative LP preferred return before residual splits" if catch_up else "disabled",
            "base_residual_split": {"lp": base_lp_split, "gp": 1 - base_lp_split},
            "tiered_splits": tier_terms,
            "cash_flows": {"values": annual_cash, "source": cash_source},
            "exit_equity_proceeds": exit_amount,
            "fees_taxes_reserves": "not deducted unless embedded in supplied distributable cash flows",
            "debt_sizing": terms.get("debt_sizing"),
        },
        anti_fraud_warning=ANTI_FRAUD_WARNING,
        guardrail=capital_guardrail(
            "Have securities counsel and a CPA reproduce the operating-agreement waterfall, "
            "review every scenario input, and approve all investor-facing presentation language."
        ),
    )


__all__ = ["DEFAULT_HOLD_YEARS", "DEFAULT_LTV", "model_waterfall"]
