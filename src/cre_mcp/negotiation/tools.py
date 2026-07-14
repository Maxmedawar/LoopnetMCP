"""Plain negotiation functions; this module performs no MCP registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig

from .approvals import list_approvals as _list_approvals
from .approvals import record_term_approval as _record_term_approval
from .commitments import list_commitments as _list_commitments
from .commitments import record_commitment_note as _record_commitment_note
from .concessions import value_concession as _value_concession
from .drift import detect_term_drift as _detect_term_drift
from .plan import build_negotiation_plan as _build_negotiation_plan


def build_negotiation_plan(
    deal_economics: dict[str, Any],
    counterparty: dict[str, Any] | None = None,
    structure_options: list[Any] | None = None,
) -> dict[str, Any]:
    return _build_negotiation_plan(deal_economics, counterparty, structure_options)


def value_concession(
    concession: dict[str, Any],
    deal_economics: dict[str, Any],
    perspective: str = "both",
) -> dict[str, Any]:
    return _value_concession(concession, deal_economics, perspective)


def detect_term_drift(
    agreed_terms: dict[str, Any], draft_text: str
) -> dict[str, Any]:
    return _detect_term_drift(agreed_terms, draft_text)


def record_negotiation_commitment(
    deal_id: str,
    text: str,
    made_by: str,
    due: Any = None,
    *,
    source: str = "note",
    made_at: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    return _record_commitment_note(
        deal_id,
        text,
        made_by,
        due,
        source=source,
        made_at=made_at,
        db_path=db_path,
        config=config,
    )


def list_negotiation_commitments(
    deal_id: str,
    *,
    status: str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> list[dict[str, Any]]:
    return _list_commitments(deal_id, status=status, db_path=db_path, config=config)


def record_term_approval(
    deal_id: str,
    term: str,
    standard_value: Any,
    approved_value: Any,
    approved_by: str,
    why: str,
    *,
    at: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    return _record_term_approval(
        deal_id,
        term,
        standard_value,
        approved_value,
        approved_by,
        why,
        at=at,
        db_path=db_path,
        config=config,
    )


def negotiation_approval_log(
    deal_id: str,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> list[dict[str, Any]]:
    return _list_approvals(deal_id, db_path=db_path, config=config)


__all__ = [
    "build_negotiation_plan",
    "detect_term_drift",
    "list_negotiation_commitments",
    "negotiation_approval_log",
    "record_negotiation_commitment",
    "record_term_approval",
    "value_concession",
]
