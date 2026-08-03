"""Range-based disposition path comparison with explicit professional gates.

This module screens alternatives; it does not recommend a security, determine tax
treatment, or replace transaction counsel.  Sale-waterfall arithmetic is delegated
to :func:`cre_mcp.taxecon.net_sale_proceeds` rather than duplicated here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.taxecon import net_sale_proceeds


UNKNOWN_RANGE: dict[str, None] = {"low": None, "base": None, "high": None}
SALE_PRICE_SENSITIVITY = 0.05
RANGE_CONVENTION = (
    "All monetary outputs are low/base/high screening ranges. A scalar sale price "
    "is widened by the exposed +/-5% sale-price sensitivity; caller-supplied ranges "
    "are preserved. Timing and retained-control outputs are low/high ranges."
)


def _number(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite non-negative number")
    try:
        result = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite non-negative number") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return result


def _money_range(value: Any, label: str) -> dict[str, float]:
    """Normalize explicit ranges and visibly widen scalar price assumptions."""

    if isinstance(value, Mapping):
        low = _number(value.get("low"), f"{label}.low")
        high = _number(value.get("high"), f"{label}.high")
        base_raw = value.get("base", (low + high) / 2)
        base = _number(base_raw, f"{label}.base")
        if not low <= base <= high:
            raise ValueError(f"{label} must satisfy low <= base <= high")
        return {"low": low, "base": base, "high": high}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
        if len(values) not in {2, 3}:
            raise ValueError(f"{label} sequence must contain two or three values")
        low = _number(values[0], f"{label}[0]")
        high = _number(values[-1], f"{label}[-1]")
        base = _number(values[1], f"{label}[1]") if len(values) == 3 else (low + high) / 2
        if not low <= base <= high:
            raise ValueError(f"{label} must satisfy low <= base <= high")
        return {"low": low, "base": base, "high": high}
    base = _number(value, label)
    return {
        "low": round(base * (1 - SALE_PRICE_SENSITIVITY), 2),
        "base": base,
        "high": round(base * (1 + SALE_PRICE_SENSITIVITY), 2),
    }


def _unknown(reason: str) -> dict[str, Any]:
    return {**UNKNOWN_RANGE, "status": "NOT_COMPUTABLE", "reason": reason}


def _flag(discipline: str, reason: str) -> dict[str, Any]:
    return {"discipline": discipline, "mandatory": True, "reason": reason}


TAX_FLAG = _flag(
    "tax_counsel",
    "Entity, holding-period, basis, debt, depreciation-recapture, and state facts control tax treatment.",
)
SECURITIES_FLAG = _flag(
    "securities_counsel",
    "Offering, transfer, sponsor, investor-eligibility, and disclosure rules require securities-law review.",
)
REAL_ESTATE_FLAG = _flag(
    "real_estate_counsel",
    "Definitive documents, title, lender consents, transfer restrictions, and closing conditions require counsel.",
)


def _sale_waterfall(
    price_range: Mapping[str, float],
    economics: Mapping[str, Any],
    *,
    commission_pct: float,
    label: str,
    loan_balance: Any | None = None,
) -> dict[str, Any]:
    """Call the taxecon hook at the range endpoints and retain its workpapers."""

    raw_balance = economics.get("loan_balance", 0) if loan_balance is None else loan_balance
    state = str(economics.get("state") or "").strip().upper()
    if not state:
        return {
            "status": "NOT_COMPUTABLE",
            "delegated_to": "cre_mcp.taxecon.net_sale_proceeds",
            "module": "cre_mcp.taxecon",
            "function": "net_sale_proceeds",
            "net_proceeds_range": _unknown("state is required for the transfer-tax screen"),
            "envelope": _unknown("state is required for the transfer-tax screen"),
            "missing_inputs": ["state"],
            "path": label,
        }
    try:
        balance = _number(raw_balance, "loan_balance")
        workpapers = {
            case: net_sale_proceeds(
                price=price_range[case],
                loan_balance=balance,
                prepay=economics.get("prepay"),
                commission_pct=commission_pct,
                state=state,
                other_costs=economics.get("other_costs", 0),
                credits=economics.get("credits", 0),
                reserves_released=economics.get("reserves_released", 0),
                tax_profile=economics.get("tax_profile"),
            )
            for case in ("low", "base", "high")
        }
    except (TypeError, ValueError) as exc:
        return {
            "status": "NOT_COMPUTABLE",
            "delegated_to": "cre_mcp.taxecon.net_sale_proceeds",
            "module": "cre_mcp.taxecon",
            "function": "net_sale_proceeds",
            "net_proceeds_range": _unknown(str(exc)),
            "envelope": _unknown(str(exc)),
            "missing_inputs": ["valid seller-waterfall inputs"],
            "path": label,
        }

    low = workpapers["low"]["net_proceeds"].get("low")
    base = workpapers["base"]["net_proceeds"].get("base")
    high = workpapers["high"]["net_proceeds"].get("high")
    if not all(isinstance(value, (int, float)) for value in (low, base, high)):
        net_range: dict[str, Any] = _unknown(
            "taxecon could not compute at least one range endpoint; inspect delegated workpapers"
        )
        status = "NOT_COMPUTABLE"
    else:
        net_range = {"low": round(low, 2), "base": round(base, 2), "high": round(high, 2)}
        status = "ESTIMATE_RANGE"
    return {
        "status": status,
        "delegated_to": "cre_mcp.taxecon.net_sale_proceeds",
        "module": "cre_mcp.taxecon",
        "function": "net_sale_proceeds",
        "net_proceeds_range": net_range,
        "envelope": net_range,
        "result": workpapers["base"],
        "workpapers": workpapers,
        "path": label,
        "range_semantics": (
            "Low uses the low sale-price case and its low net; base uses base/base; "
            "high uses the high sale-price case and its high net."
        ),
    }


def _path(
    key: str,
    label: str,
    *,
    net_range: Mapping[str, Any],
    timing: tuple[float, float],
    control: tuple[float, float],
    tax_notes: list[str],
    liquidity: str,
    flags: list[dict[str, Any]],
    hook: Mapping[str, Any] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    disciplines = {str(flag["discipline"]) for flag in flags}
    result = {
        "path": key,
        "name": label,
        "net_to_seller_range": dict(net_range),
        "timing_months_range": {"low": timing[0], "high": timing[1]},
        "control_retained_range": {"low": control[0], "high": control[1], "unit": "percent"},
        "tax_character_notes": tax_notes,
        "liquidity": liquidity,
        "professional_flags": flags,
        "professional_review_required": True,
        "tax_counsel_required": "tax_counsel" in disciplines,
        "securities_counsel_required": "securities_counsel" in disciplines,
        "notes": notes or [],
    }
    if hook is not None:
        result["net_sale_proceeds_hook"] = dict(hook)
    return result


def compare_exit_paths(
    deal: Mapping[str, Any],
    holder_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare seven disposition/recapitalization paths as screening ranges.

    ``deal`` should provide ``price`` or ``price_range``/``sale_price_range`` and
    seller-waterfall inputs accepted by ``taxecon.net_sale_proceeds``.  Missing
    facts produce an honest ``NOT_COMPUTABLE`` range instead of an invented value.
    """

    economics = dict(deal)
    holder = dict(holder_profile or {})
    raw_price = economics.get(
        "sale_price_range", economics.get("price_range", economics.get("price"))
    )
    if raw_price is None:
        raise ValueError("deal requires price, price_range, or sale_price_range")
    price_range = _money_range(raw_price, "sale_price_range")
    direct_commission = _number(economics.get("direct_commission_pct", 0), "direct_commission_pct")
    broker_commission = _number(
        economics.get("broker_commission_pct", economics.get("commission_pct", 0.05)),
        "broker_commission_pct",
    )

    direct_hook = _sale_waterfall(
        price_range, economics, commission_pct=direct_commission, label="direct_sale"
    )
    brokered_hook = _sale_waterfall(
        price_range, economics, commission_pct=broker_commission, label="brokered_sale"
    )
    exchange_hook = _sale_waterfall(
        price_range,
        economics,
        commission_pct=_number(
            economics.get("exchange_commission_pct", broker_commission),
            "exchange_commission_pct",
        ),
        label="1031_exchange_sale_leg",
    )

    partial_fraction = economics.get("partial_sale_fraction_range")
    partial_hook: dict[str, Any]
    if partial_fraction is None:
        partial_net = _unknown(
            "partial_sale_fraction_range and allocated loan payoff are required"
        )
        partial_hook = {
            "status": "NOT_COMPUTABLE",
            "delegated_to": "cre_mcp.taxecon.net_sale_proceeds",
            "module": "cre_mcp.taxecon",
            "function": "net_sale_proceeds",
            "missing_inputs": ["partial_sale_fraction_range", "partial_sale_loan_balance"],
            "net_proceeds_range": partial_net,
            "envelope": partial_net,
        }
    else:
        fractions = _money_range(partial_fraction, "partial_sale_fraction_range")
        if fractions["high"] > 1:
            raise ValueError("partial_sale_fraction_range cannot exceed 1.0")
        partial_prices = {
            "low": price_range["low"] * fractions["low"],
            "base": price_range["base"] * fractions["base"],
            "high": price_range["high"] * fractions["high"],
        }
        if "partial_sale_loan_balance" not in economics:
            partial_net = _unknown("partial_sale_loan_balance is required; debt allocation is not guessed")
            partial_hook = {
                "status": "NOT_COMPUTABLE",
                "delegated_to": "cre_mcp.taxecon.net_sale_proceeds",
                "module": "cre_mcp.taxecon",
                "function": "net_sale_proceeds",
                "missing_inputs": ["partial_sale_loan_balance"],
                "net_proceeds_range": partial_net,
                "envelope": partial_net,
            }
        else:
            partial_hook = _sale_waterfall(
                partial_prices,
                economics,
                commission_pct=broker_commission,
                label="partial_sale",
                loan_balance=economics["partial_sale_loan_balance"],
            )
            partial_net = partial_hook["net_proceeds_range"]

    recap_net = (
        _money_range(economics["recap_proceeds_range"], "recap_proceeds_range")
        if economics.get("recap_proceeds_range") is not None
        else _unknown("recap_proceeds_range requires actual lender/investor terms")
    )
    upreit_net = (
        _money_range(economics["upreit_liquidity_range"], "upreit_liquidity_range")
        if economics.get("upreit_liquidity_range") is not None
        else _unknown("OP-unit value, lockup, debt allocation, and transaction costs require sponsor terms")
    )

    common_tax_note = (
        "Tax character is fact-specific; no gain, recapture, basis, or after-tax proceeds are calculated here."
    )
    paths = [
        _path(
            "direct_sale",
            "Direct sale",
            net_range=direct_hook["net_proceeds_range"],
            timing=(2, 6),
            control=(0, 0),
            tax_notes=[common_tax_note, "Generally a taxable sale unless a separate deferral structure qualifies."],
            liquidity="High at closing, subject to payoff, costs, holdbacks, and taxes.",
            flags=[TAX_FLAG, REAL_ESTATE_FLAG],
            hook=direct_hook,
            notes=["Lower distribution expense can reduce buyer reach and price discovery."],
        ),
        _path(
            "brokered_sale",
            "Brokered sale",
            net_range=brokered_hook["net_proceeds_range"],
            timing=(4, 9),
            control=(0, 0),
            tax_notes=[common_tax_note, "Brokerage changes selling costs, not the underlying tax character."],
            liquidity="High at closing, net of broker and transaction costs.",
            flags=[TAX_FLAG, REAL_ESTATE_FLAG],
            hook=brokered_hook,
            notes=["Broader exposure may improve price discovery but increases fees and information leakage."],
        ),
        _path(
            "recap",
            "Recapitalization",
            net_range=recap_net,
            timing=(3, 8),
            control=(holder.get("recap_control_low", 35), holder.get("recap_control_high", 80)),
            tax_notes=[common_tax_note, "Debt proceeds and equity redemptions can have different tax character."],
            liquidity="Partial and negotiated; future liquidity depends on governance and exit rights.",
            flags=[TAX_FLAG, REAL_ESTATE_FLAG, SECURITIES_FLAG],
            notes=["Requires real lender/investor terms before proceeds can be computed."],
        ),
        _path(
            "partial_sale",
            "Partial sale",
            net_range=partial_net,
            timing=(3, 8),
            control=(holder.get("partial_control_low", 20), holder.get("partial_control_high", 80)),
            tax_notes=[common_tax_note, "Entity versus asset sale and debt allocation can materially change gain and basis."],
            liquidity="Partial at closing; retained interest may be illiquid and transfer-restricted.",
            flags=[TAX_FLAG, REAL_ESTATE_FLAG, SECURITIES_FLAG],
            hook=partial_hook,
        ),
        _path(
            "1031_exchange",
            "Section 1031 exchange",
            net_range=exchange_hook["net_proceeds_range"],
            timing=(4, 10),
            control=(0, 100),
            tax_notes=[
                common_tax_note,
                "Deferral is conditional, not exemption; QI-before-closing, 45/180-day clocks, identification, value, debt, and boot rules apply.",
            ],
            liquidity="Sale proceeds generally remain restricted with the qualified intermediary until replacement closing.",
            flags=[TAX_FLAG, REAL_ESTATE_FLAG],
            hook=exchange_hook,
            notes=[
                "Cross-link: use cre_mcp.structure exchange tools for clocks/identification and boot-basis screening."
            ],
        ),
        _path(
            "upreit",
            "UPREIT contribution",
            net_range=upreit_net,
            timing=(5, 12),
            control=(0, 10),
            tax_notes=[
                common_tax_note,
                "A Section 721 contribution may defer gain only if the actual structure qualifies; debt shifts, disguised-sale rules, lockups, and later unit sales require advice.",
            ],
            liquidity="Staged and sponsor-dependent; OP units may be locked up, unlisted, or subject to redemption restrictions.",
            flags=[TAX_FLAG, SECURITIES_FLAG, REAL_ESTATE_FLAG],
            notes=["MANDATORY tax and securities counsel review before reliance or solicitation."],
        ),
        _path(
            "dst",
            "Delaware Statutory Trust replacement",
            net_range=exchange_hook["net_proceeds_range"],
            timing=(3, 8),
            control=(0, 0),
            tax_notes=[
                common_tax_note,
                "DST interests marketed as 1031 replacements require eligibility, debt, timing, beneficial-interest, and exchange-qualification review.",
            ],
            liquidity="Low; sponsor-controlled interests may lack a reliable secondary market and can have long holds.",
            flags=[TAX_FLAG, SECURITIES_FLAG, REAL_ESTATE_FLAG],
            hook=exchange_hook,
            notes=[
                "MANDATORY securities and tax counsel review; this is not an investment recommendation or offering analysis."
            ],
        ),
    ]

    return {
        "status": "SCREENING_COMPARISON",
        "paths": paths,
        "path_count": len(paths),
        "sale_price_range": price_range,
        "range_convention": RANGE_CONVENTION,
        "scalar_price_sensitivity": SALE_PRICE_SENSITIVITY,
        "holder_profile": holder,
        "professional_review_required": True,
        "not_legal_tax_or_investment_advice": True,
        "comparison_limit": (
            "Ranges are scenario frames, not forecasts or bids. Unknown proceeds remain uncomputed until "
            "actual structure, lender, sponsor, and seller facts are supplied."
        ),
    }


__all__ = ["RANGE_CONVENTION", "SALE_PRICE_SENSITIVITY", "compare_exit_paths"]
