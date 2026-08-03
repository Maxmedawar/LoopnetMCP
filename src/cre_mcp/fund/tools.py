"""Plain fund-operations callables for later MCP registration.

This module intentionally has no server-framework dependency or registration side
effects. Every public function contains implementation failures at a stable
``{"error": ...}`` boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.source_rights.output import safe_error_message

from .calls import forecast_capital_calls as _forecast_capital_calls
from .engagement import engagement_report as _engagement_report
from .engagement import record_investor_touch as _record_investor_touch
from .jv import compare_jv_structures as _compare_jv_structures
from .mandate import check_mandate_limits as _check_mandate_limits
from .nav import nav_report as _nav_report
from .nav import record_fund_flow as _record_fund_flow
from .nav import record_fund_mark as _record_fund_mark
from .reports import quarterly_investor_report as _quarterly_investor_report

logger = logging.getLogger(__name__)


def _error(tool_name: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = safe_error_message(message or exc.__class__.__name__)
    logger.error("%s error: %s", tool_name, message)
    return {"error": message}


def compare_jv_structures(
    structures: Sequence[Mapping[str, Any]],
    deal_cash_flows: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        return _compare_jv_structures(structures, deal_cash_flows)
    except Exception as exc:
        return _error("compare_jv_structures", exc)


def forecast_capital_calls(
    pipeline_needs: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    commitments: Sequence[Mapping[str, Any]] | None = None,
    *,
    gp_coinvest_pct: Any = 0,
    governing_docs: Mapping[str, Any] | str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _forecast_capital_calls(
            pipeline_needs,
            commitments,
            gp_coinvest_pct=gp_coinvest_pct,
            governing_docs=governing_docs,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("forecast_capital_calls", exc)


def record_fund_mark(
    asset: str,
    period: str,
    value_cents: int,
    source: str,
    *,
    source_label: str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _record_fund_mark(
            asset,
            period,
            value_cents,
            source,
            source_label=source_label,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("record_fund_mark", exc)


def record_fund_flow(
    period: str,
    flow_type: str | None = None,
    cents: int | None = None,
    *,
    type: str | None = None,
    investor: str | None = None,
    source_label: str = "caller-supplied fund flow",
    attribution: str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _record_fund_flow(
            period,
            flow_type,
            cents,
            type=type,
            investor=investor,
            source_label=source_label,
            attribution=attribution,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("record_fund_flow", exc)


def nav_report(
    period: str,
    cash_cents: int,
    liabilities_cents: int,
    *,
    cash_source: str | None = None,
    liabilities_source: str | None = None,
    fee_convention: str = "committed",
    management_fee_bps: int | None = None,
    fee_period_months: int = 3,
    fee_basis_cents: int | None = None,
    fee_basis_source: str | None = None,
    management_fee_source: str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    try:
        kwargs: dict[str, Any] = {
            "cash_source": cash_source,
            "liabilities_source": liabilities_source,
            "fee_convention": fee_convention,
            "management_fee_bps": management_fee_bps,
            "fee_period_months": fee_period_months,
            "fee_basis_cents": fee_basis_cents,
            "fee_basis_source": fee_basis_source,
            "db_path": db_path,
            "config": config,
        }
        if management_fee_source is not None:
            kwargs["management_fee_source"] = management_fee_source
        return _nav_report(period, cash_cents, liabilities_cents, **kwargs)
    except Exception as exc:
        return _error("nav_report", exc)


def check_mandate_limits(
    fund_rules: Mapping[str, Any],
    portfolio: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    proposed_deal: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        return _check_mandate_limits(fund_rules, portfolio, proposed_deal)
    except Exception as exc:
        return _error("check_mandate_limits", exc)


def quarterly_investor_report(
    period: str,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _quarterly_investor_report(period, db_path=db_path, config=config)
    except Exception as exc:
        return _error("quarterly_investor_report", exc)


def record_investor_touch(
    investor: str,
    type: str,
    at: Any = None,
    note: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _record_investor_touch(
            investor,
            type,
            at,
            note,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("record_investor_touch", exc)


def investor_engagement_report(
    investor: str | None = None,
    *,
    as_of: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _engagement_report(
            investor,
            as_of=as_of,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("investor_engagement_report", exc)


__all__ = [
    "check_mandate_limits",
    "compare_jv_structures",
    "forecast_capital_calls",
    "investor_engagement_report",
    "nav_report",
    "quarterly_investor_report",
    "record_fund_flow",
    "record_fund_mark",
    "record_investor_touch",
]
