"""Plain financing-operations callables for later MCP registration.

This module deliberately has no FastMCP dependency or registration side effects.
Every public function contains failures at a stable ``{"error": ...}`` boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig

from .assumable_detect import detect_assumable as _detect_assumable
from .cashneeds import cash_requirements as _cash_requirements
from .hedges import cap_cost_context as _cap_cost_context
from .lenders import match_lenders as _match_lenders
from .lenders import record_lender_profile as _record_lender_profile
from .notechain import reconcile_note_chain as _reconcile_note_chain
from .reporting import record_reporting_item as _record_reporting_item
from .reporting import reporting_calendar as _reporting_calendar
from .waivers import prepare_waiver_request as _prepare_waiver_request


logger = logging.getLogger(__name__)


def _error(tool_name: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = message or exc.__class__.__name__
    logger.error("%s error: %s", tool_name, message)
    return {"error": message}


def cash_requirements(
    horizon_days: int,
    inputs: Mapping[str, Any],
    *,
    as_of: Any = None,
) -> dict[str, Any]:
    """Build a penny-exact 30/60/90-day cash requirement schedule."""

    try:
        return _cash_requirements(horizon_days, inputs, as_of=as_of)
    except Exception as exc:
        return _error("cash_requirements", exc)


def detect_assumable(
    listing_or_om_text: str | Mapping[str, Any],
) -> dict[str, Any]:
    """Detect and cite existing-financing language without inferring consent."""

    try:
        return _detect_assumable(listing_or_om_text)
    except Exception as exc:
        return _error("detect_assumable", exc)


def record_lender_profile(
    profile_or_name: Mapping[str, Any] | str | None = None,
    type: str | None = None,
    geographies: Sequence[str] | str | None = None,
    asset_types: Sequence[str] | str | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    leverage_max: Any = None,
    rate_context: str | None = None,
    last_confirmed: Any = None,
    source: str | None = None,
    *,
    name: str | None = None,
    lender_type: str | None = None,
    size_min_cents: int | None = None,
    size_max_cents: int | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Accrue a sourced lender-appetite profile in the owned table."""

    try:
        return _record_lender_profile(
            profile_or_name,
            type,
            geographies,
            asset_types,
            size_min,
            size_max,
            leverage_max,
            rate_context,
            last_confirmed,
            source,
            name=name,
            lender_type=lender_type,
            size_min_cents=size_min_cents,
            size_max_cents=size_max_cents,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("record_lender_profile", exc)


def match_lenders(
    deal: Mapping[str, Any],
    *,
    as_of: Any = None,
    stale_after_days: int = 180,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Rank stored appetite fit while keeping stale data visibly qualified."""

    try:
        return _match_lenders(
            deal,
            as_of=as_of,
            stale_after_days=stale_after_days,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("match_lenders", exc)


def cap_cost_context(
    loan: Mapping[str, Any],
    cap: Mapping[str, Any],
) -> dict[str, Any]:
    """Return an illustrative convention range and penny-exact escrow math."""

    try:
        return _cap_cost_context(loan, cap)
    except Exception as exc:
        return _error("cap_cost_context", exc)


def prepare_waiver_request(
    loan: Mapping[str, Any],
    covenant_results: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ask: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble a factual waiver/extension/modification request for review."""

    try:
        return _prepare_waiver_request(loan, covenant_results, ask)
    except Exception as exc:
        return _error("prepare_waiver_request", exc)


def record_reporting_item(
    loan: str,
    item: str,
    frequency: str | None,
    next_due: Any,
    recipient: str | None = None,
    status: str | None = "pending",
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Record one lender-reporting obligation in the owned table."""

    try:
        return _record_reporting_item(
            loan,
            item,
            frequency,
            next_due,
            recipient,
            status,
            db_path,
        )
    except Exception as exc:
        return _error("record_reporting_item", exc)


def record_reporting(
    loan: str,
    item: str,
    frequency: str | None,
    next_due: Any,
    recipient: str | None = None,
    status: str | None = "pending",
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Compatibility alias for :func:`record_reporting_item`."""

    return record_reporting_item(
        loan,
        item,
        frequency,
        next_due,
        recipient,
        status,
        db_path,
    )


def reporting_calendar(
    days: int = 60,
    db_path: str | Path | CreConfig | None = None,
    as_of: Any = None,
    loan: str | None = None,
) -> dict[str, Any]:
    """List lender deliverables due in the inclusive forward window."""

    try:
        return _reporting_calendar(days, db_path, as_of, loan)
    except Exception as exc:
        return _error("reporting_calendar", exc)


def reconcile_note_chain(
    docs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Walk note and mortgage transfers and flag continuity defects for counsel."""

    try:
        return _reconcile_note_chain(docs)
    except Exception as exc:
        return _error("reconcile_note_chain", exc)


__all__ = [
    "cap_cost_context",
    "cash_requirements",
    "detect_assumable",
    "match_lenders",
    "prepare_waiver_request",
    "reconcile_note_chain",
    "record_lender_profile",
    "record_reporting",
    "record_reporting_item",
    "reporting_calendar",
]
