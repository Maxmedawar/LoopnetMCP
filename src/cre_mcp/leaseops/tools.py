"""Plain, unregistered lease-operations functions for later MCP wiring."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .certificates import certificate_gaps as _certificate_gaps
from .certificates import expire_radar as _expire_radar
from .certificates import record_certificate as _record_certificate
from .lineage import trace_input as _trace_input
from .notices import draft_obligation_notice as _draft_obligation_notice
from .recon import lease_vs_books as _lease_vs_books
from .requests import diligence_request_list as _diligence_request_list

logger = logging.getLogger(__name__)


def _error(tool_name: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = message or exc.__class__.__name__
    logger.error("%s error: %s", tool_name, message)
    return {"error": message}


def reconcile_lease_vs_books(
    tenancy_id: str | None,
    period_range: str | Sequence[str] | Mapping[str, str],
    lease_abstract: Any = None,
    books_data: Mapping[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compare cited lease commencement, rent, and deposit with read-only books."""

    try:
        return _lease_vs_books(
            tenancy_id,
            period_range,
            lease_abstract,
            books_data,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("reconcile_lease_vs_books", exc)


def record_certificate(
    tenancy_or_deal: str | Mapping[str, Any],
    kind: str | None = None,
    party: str | None = None,
    amount_cents: int | None = None,
    expires: Any = None,
    status: str | None = None,
    doc_ref: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Record one entered COI, guaranty, letter of credit, or deposit fact."""

    try:
        return _record_certificate(
            tenancy_or_deal,
            kind,
            party,
            amount_cents,
            expires,
            status,
            doc_ref,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("record_certificate", exc)


def certificate_radar(
    days: int = 90,
    tenancy_or_deal: str | None = None,
    requirements: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    as_of: Any = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return the inclusive expiry radar and, when supplied, lease-requirement gaps."""

    try:
        radar = _expire_radar(
            days,
            tenancy_or_deal,
            as_of=as_of,
            db_path=db_path,
        )
        if requirements is not None:
            if tenancy_or_deal is None:
                raise ValueError("tenancy_or_deal is required when requirements are supplied")
            gaps = _certificate_gaps(
                tenancy_or_deal,
                requirements,
                as_of=as_of,
                db_path=db_path,
            )
            radar["gaps_report"] = gaps
            radar["requirement_gaps"] = gaps["gaps"]
        return radar
    except Exception as exc:
        return _error("certificate_radar", exc)


def draft_obligation_notice(
    lease_facts: Mapping[str, Any] | None,
    notice_type: str,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a factual, unsent obligation-notice draft for counsel review."""

    try:
        return _draft_obligation_notice(lease_facts, notice_type, params)
    except Exception as exc:
        return _error("draft_obligation_notice", exc)


async def trace_input_lineage(
    deal_id: str,
    field: str,
    subject: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Walk one truth-store field from raw source location through reconciliation."""

    try:
        return await _trace_input(deal_id, field, subject, db_path=db_path)
    except Exception as exc:
        return _error("trace_input_lineage", exc)


def diligence_request_list(
    deal_id: str,
    truth_report: Mapping[str, Any] | None,
    data_room_index: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Rank truth conflicts and data-room gaps into a ready-to-send request list."""

    try:
        return _diligence_request_list(deal_id, truth_report, data_room_index)
    except Exception as exc:
        return _error("diligence_request_list", exc)


__all__ = [
    "certificate_radar",
    "diligence_request_list",
    "draft_obligation_notice",
    "reconcile_lease_vs_books",
    "record_certificate",
    "trace_input_lineage",
]
