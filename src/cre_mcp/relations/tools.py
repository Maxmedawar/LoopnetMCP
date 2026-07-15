"""Plain relationship-intelligence functions for later MCP registration.

This module intentionally has no FastMCP dependency or registration side effect.
Implementation failures are contained at the stable ``{"error": ...}`` boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig

from .appraisal_challenge import challenge_appraisal as _challenge_appraisal
from .briefing import meeting_briefing as _meeting_briefing
from .coverage import coverage_report as _coverage_report
from .coverage import route_lead as _route_lead
from .dossier import counterparty_dossier as _counterparty_dossier
from .stalls import record_thread_state as _record_thread_state
from .stalls import stalled_threads as _stalled_threads
from .whotocall import who_to_call as _who_to_call


logger = logging.getLogger(__name__)


def _error(tool_name: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = message or exc.__class__.__name__
    logger.error("%s error: %s", tool_name, message)
    return {"error": message}


async def counterparty_dossier(
    name: str,
    *,
    db_path: str | Path | None = None,
    license_screen: Mapping[str, Any] | None = None,
    verifyreg_output: Mapping[str, Any] | None = None,
    as_of: Any = None,
) -> dict[str, Any]:
    try:
        return await _counterparty_dossier(
            name,
            db_path=db_path,
            license_screen=license_screen,
            verifyreg_output=verifyreg_output,
            as_of=as_of,
        )
    except Exception as exc:
        return _error("counterparty_dossier", exc)


async def who_to_call(
    need: Mapping[str, Any],
    *,
    db_path: str | Path | None = None,
    as_of: Any = None,
    limit: int = 10,
) -> dict[str, Any]:
    try:
        return await _who_to_call(
            need,
            db_path=db_path,
            as_of=as_of,
            limit=limit,
        )
    except Exception as exc:
        return _error("who_to_call", exc)


async def meeting_briefing(
    counterparty: str,
    deal_id: str | None = None,
    *,
    db_path: str | Path | None = None,
    license_screen: Mapping[str, Any] | None = None,
    as_of: Any = None,
) -> dict[str, Any]:
    try:
        return await _meeting_briefing(
            counterparty,
            deal_id,
            db_path=db_path,
            license_screen=license_screen,
            as_of=as_of,
        )
    except Exception as exc:
        return _error("meeting_briefing", exc)


def record_thread_state(
    deal_id: str,
    counterparty: str,
    direction: str,
    topic: str,
    last_message_at: Any,
    awaiting: str,
    note: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _record_thread_state(
            deal_id,
            counterparty,
            direction,
            topic,
            last_message_at,
            awaiting,
            note,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("record_thread_state", exc)


def stalled_threads(
    days: int = 4,
    *,
    as_of: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _stalled_threads(
            days,
            as_of=as_of,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("stalled_threads", exc)


def deal_coverage_report(
    period: Any,
    *,
    as_of: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _coverage_report(
            period,
            as_of=as_of,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("deal_coverage_report", exc)


def route_lead(
    listing: Any,
    team: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        return _route_lead(listing, team)
    except Exception as exc:
        return _error("route_lead", exc)


def challenge_appraisal(
    appraisal: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _challenge_appraisal(appraisal, evidence)
    except Exception as exc:
        return _error("challenge_appraisal", exc)


__all__ = [
    "challenge_appraisal",
    "counterparty_dossier",
    "deal_coverage_report",
    "meeting_briefing",
    "record_thread_state",
    "route_lead",
    "stalled_threads",
    "who_to_call",
]
