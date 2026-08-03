"""Plain asset-management tool boundaries for later FastMCP registration."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from cre_mcp.source_rights.output import safe_error_message

from .benchmarks import flag_underperformance as _flag_underperformance
from .capex_rank import prioritize_capex as _prioritize_capex
from .marginal import marginal_return as _marginal_return
from .noi_forecast import noi_by_tenant as _noi_by_tenant
from .noi_forecast import variance_explain as _variance_explain
from .plan import business_plan as _business_plan
from .plan import rank_initiatives as _rank_initiatives
from .plan import upsert_initiative as _upsert_initiative
from .tracker import initiative_tracker as _initiative_tracker
from .watchlist import portfolio_watchlist as _portfolio_watchlist

logger = logging.getLogger(__name__)


def _error(tool_name: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = safe_error_message(message or exc.__class__.__name__)
    logger.error("%s error: %s", tool_name, message)
    return {"error": message}


def upsert_initiative(
    deal_id: str,
    initiative: str,
    cost_cents: int,
    noi_impact_cents_annual: int,
    owner: str | None = None,
    start: date | datetime | str | None = None,
    months: int | None = None,
    status: str | None = "planned",
    baseline: Mapping[str, Any] | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist one initiative baseline using integer cents."""

    try:
        return _upsert_initiative(
            deal_id,
            initiative,
            cost_cents,
            noi_impact_cents_annual,
            owner,
            start,
            months,
            status,
            baseline,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("upsert_initiative", exc)


def business_plan(
    deal_id: str,
    year: int,
    budget_hooks: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build an annual initiative plan with a budget-linked NOI bridge."""

    try:
        return _business_plan(deal_id, year, budget_hooks, db_path=db_path)
    except Exception as exc:
        return _error("business_plan", exc)


def rank_initiatives(
    deal_id: str,
    input_cap_rate: float | Decimal | str = 0.07,
    execution_success_by_status: Mapping[str, float | Decimal | str] | None = None,
    bandwidth: int = 3,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Rank initiatives using the disclosed capitalization and risk convention."""

    try:
        return _rank_initiatives(
            deal_id,
            input_cap_rate,
            execution_success_by_status,
            bandwidth,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("rank_initiatives", exc)


def noi_by_tenant(
    deal_id: str | None = None,
    tenancies: Sequence[Mapping[str, Any]] | None = None,
    market_assumptions: Mapping[str, Any] | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build tenant/unit NOI paths from structured input or property books."""

    try:
        return _noi_by_tenant(
            deal_id,
            tenancies,
            market_assumptions,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("noi_by_tenant", exc)


def variance_explain(
    budget: Mapping[str, Any],
    actuals: Mapping[str, Any] | None = None,
    *,
    deal_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Attribute actual-minus-budget NOI with a penny-exact bridge."""

    try:
        return _variance_explain(
            budget,
            actuals,
            deal_id=deal_id,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("variance_explain", exc)


def prioritize_capex(
    requests: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply the mandatory safety/compliance gate and return screen."""

    try:
        return _prioritize_capex(requests)
    except Exception as exc:
        return _error("prioritize_capex", exc)


def initiative_tracker(
    deal_id: str,
    actuals: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    from_period: str | None = None,
    to_period: str | None = None,
    as_of: date | datetime | str | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compare initiative baselines with structured or book-derived actuals."""

    try:
        return _initiative_tracker(
            deal_id,
            actuals,
            from_period,
            to_period,
            as_of,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("initiative_tracker", exc)


def flag_underperformance(
    portfolio: Sequence[Mapping[str, Any]],
    benchmarks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Flag threshold exceptions while labeling small-sample limits."""

    try:
        return _flag_underperformance(portfolio, benchmarks)
    except Exception as exc:
        return _error("flag_underperformance", exc)


def marginal_return(
    next_dollar: Mapping[str, Any],
    opportunity_cost_rate: Any,
) -> dict[str, Any]:
    """Rank investment uses by time-adjusted marginal return."""

    try:
        return _marginal_return(next_dollar, opportunity_cost_rate)
    except Exception as exc:
        return _error("marginal_return", exc)


def portfolio_watchlist(
    portfolio: Sequence[Mapping[str, Any]],
    as_of: date | datetime | str | None = None,
    horizons_days: Mapping[str, int] | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return exception-only asset events sorted by disclosed urgency tiers."""

    try:
        return _portfolio_watchlist(
            portfolio,
            as_of,
            horizons_days,
            db_path,
        )
    except Exception as exc:
        return _error("portfolio_watchlist", exc)


__all__ = [
    "business_plan",
    "flag_underperformance",
    "initiative_tracker",
    "marginal_return",
    "noi_by_tenant",
    "portfolio_watchlist",
    "prioritize_capex",
    "rank_initiatives",
    "upsert_initiative",
    "variance_explain",
]
