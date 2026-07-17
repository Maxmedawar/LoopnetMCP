"""Plain disposition-engine callables for later MCP registration by the director.

Nothing in this module imports FastMCP or registers a tool.  The wrappers keep a
stable public surface while the implementation modules retain their own exposed
rubrics, assumptions, and persistence options.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .bids import normalize_bids as _normalize_bids
from .bids import record_bid as _record_bid
from .buyers import match_buyers as _match_buyers
from .buyers import record_buyer as _record_buyer
from .exits import compare_exit_paths as _compare_exit_paths
from .process import design_sale_process as _design_sale_process
from .readiness import disposition_readiness as _disposition_readiness


def disposition_readiness(
    deal_id: str,
    deal_type: str,
    target_sale_date: Any,
    audit_inputs: Mapping[str, Any] | None = None,
    as_of: Any = None,
) -> dict[str, Any]:
    """Return the six-dimension readiness audit without registering a tool."""

    try:
        return _disposition_readiness(
            deal_id,
            deal_type,
            target_sale_date,
            audit_inputs,
            as_of=as_of,
        )
    except Exception as exc:
        return {"error": str(exc)}


def record_buyer(
    name: str,
    buyer_type: str,
    check_size_min: Any = None,
    check_size_max: Any = None,
    geographies: Any = None,
    asset_types: Any = None,
    financing_style: str | None = None,
    source: str | None = None,
    notes: str | None = None,
    buyer_id: str | None = None,
) -> dict[str, Any]:
    """Persist one buyer in the disposition-owned buyer table."""

    try:
        return _record_buyer(
            buyer_id=buyer_id,
            name=name,
            buyer_type=buyer_type,
            check_size_min=check_size_min,
            check_size_max=check_size_max,
            geographies=geographies,
            asset_types=asset_types,
            financing_style=financing_style,
            source=source,
            notes=notes,
        )
    except Exception as exc:
        return {"error": str(exc)}


def match_buyers(
    deal: Mapping[str, Any],
) -> dict[str, Any]:
    """Rank the recorded buyer universe using disclosed attribute fit only."""

    try:
        return _match_buyers(deal)
    except Exception as exc:
        return {"error": str(exc)}


def record_bid(
    deal_id: str,
    buyer_id: str,
    price: Any,
    deposit: Any = None,
    dd_days: Any = None,
    closing_days: Any = None,
    contingencies: Any = None,
    financing: Any = None,
    bid_id: str | None = None,
    received_at: Any = None,
    status: str | None = None,
    final_price: Any = None,
) -> dict[str, Any]:
    """Persist or resolve one bid outcome in the disposition-owned bid ledger."""

    bid: dict[str, Any] = {
        "deal_id": deal_id,
        "buyer_id": buyer_id,
        "price": price,
    }
    optional_fields = {
        "deposit": deposit,
        "dd_days": dd_days,
        "closing_days": closing_days,
        "contingencies": contingencies,
        "financing": financing,
        "bid_id": bid_id,
        "received_at": received_at,
        "status": status,
        "final_price": final_price,
    }
    bid.update(
        {key: value for key, value in optional_fields.items() if value is not None}
    )
    try:
        return _record_bid(bid)
    except Exception as exc:
        return {"error": str(exc)}


def normalize_bids(
    deal_id: str,
    carry_cost_per_day: Any = 0.0,
    deposit_credit_rate: Any = 0.1,
    financing_risk_weights: Mapping[str, Any] | None = None,
    contingency_haircuts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a fully reconciled certainty-adjusted bid ranking."""

    try:
        return _normalize_bids(
            deal_id,
            carry_cost_per_day=carry_cost_per_day,
            deposit_credit_rate=deposit_credit_rate,
            financing_risk_weights=financing_risk_weights,
            contingency_haircuts=contingency_haircuts,
        )
    except Exception as exc:
        return {"error": str(exc)}


def design_sale_process(
    deal: Mapping[str, Any] | Any,
    objectives: Mapping[str, Any] | Any,
) -> dict[str, Any]:
    """Return governed brokered, targeted, and auction process framing."""

    try:
        return _design_sale_process(deal, objectives)
    except Exception as exc:
        return {"error": str(exc)}


def compare_exit_paths(
    deal: Mapping[str, Any],
    holder_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return range-based sale, recapitalization, exchange, and security paths."""

    try:
        return _compare_exit_paths(deal, holder_profile)
    except Exception as exc:
        return {"error": str(exc)}


__all__ = [
    "compare_exit_paths",
    "design_sale_process",
    "disposition_readiness",
    "match_buyers",
    "normalize_bids",
    "record_bid",
    "record_buyer",
]
