"""Plain closing functions for later FastMCP registration by the integrator."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

from .command_center import closing_day as _closing_day
from .funding import verify_funding_package as _verify_funding_package
from .obligations_extract import (
    extract_contract_obligations as _extract_contract_obligations,
)
from .postmortem import deal_postmortem as _deal_postmortem
from .settlement import reconcile_settlement as _reconcile_settlement


logger = logging.getLogger(__name__)


def _error(tool_name: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = message or exc.__class__.__name__
    logger.error("%s error: %s", tool_name, message)
    return {"error": message}


def extract_contract_obligations(text: str, kind: str) -> dict[str, Any]:
    """Extract cited legal obligations for counsel review; never give legal advice."""

    try:
        return _extract_contract_obligations(text, kind)
    except Exception as exc:
        return _error("extract_contract_obligations", exc)


def reconcile_settlement(
    statement: Mapping[str, Any],
    expected: Mapping[str, Any],
    convention: str | int = "actual_days",
    closing_day_owner: str = "buyer",
) -> dict[str, Any]:
    """Recompute and reconcile settlement lines using integer-cent arithmetic."""

    try:
        return _reconcile_settlement(
            statement,
            expected,
            convention,
            closing_day_owner,
        )
    except Exception as exc:
        return _error("reconcile_settlement", exc)


def verify_funding_package(
    sources_uses: Mapping[str, Any],
    payoff_letters: Sequence[Mapping[str, Any]],
    wires: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Prepare human funding checks without verifying or authorizing any wire."""

    try:
        return _verify_funding_package(sources_uses, payoff_letters, wires)
    except Exception as exc:
        return _error("verify_funding_package", exc)


def closing_day_runbook(
    deal_id: str,
    closing_date: Any,
    funding_checklist: dict[str, Any] | None = None,
    obligations: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose the read-only closing runway and human execution runbook."""

    try:
        return _closing_day(deal_id, closing_date, funding_checklist, obligations)
    except Exception as exc:
        return _error("closing_day_runbook", exc)


def record_deal_postmortem(
    deal_id: str,
    timeline_events: Sequence[Mapping[str, Any]],
    outcome: Mapping[str, Any],
    drift_results: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Record a structured postmortem with hypotheses, not causal conclusions."""

    try:
        return _deal_postmortem(
            deal_id,
            timeline_events,
            outcome,
            drift_results,
            db_path,
        )
    except Exception as exc:
        return _error("record_deal_postmortem", exc)


__all__ = [
    "closing_day_runbook",
    "extract_contract_obligations",
    "reconcile_settlement",
    "record_deal_postmortem",
    "verify_funding_package",
]
