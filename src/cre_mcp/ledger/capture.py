"""Turn a reconciliation into claim-ledger evidence — automatically, on every run.

The truth engine already computes claim-vs-truth on every ``reconcile_deal_docs``
call and (until now) threw that evidence away. This module keeps it.

A claim is ledger-worthy when it came from a LOW-AUTHORITY, counterparty-authored
source (listing, OM, seller rep) and a HIGHER-AUTHORITY document existed to test it
against. Corroborated claims are recorded too: accuracy is a track record's other half.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from cre_mcp.ledger.models import ClaimOutcomeRecord
from cre_mcp.ledger.store import get_ledger_store
from cre_mcp.truth.models import DocKind
from cre_mcp.truth.reconcile import SOURCE_AUTHORITY, Reconciliation

logger = logging.getLogger(__name__)

# Counterparty-authored sources whose assertions we grade. Authority numbers come
# from the truth engine's ladder (HIGHER = more authoritative: lease 95 > OM 30).
_GRADED_DOC_KINDS = frozenset({DocKind.OM, DocKind.LISTING})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _delta_pct(claimed: float | str | None, proven: float | str | None) -> float | None:
    if isinstance(claimed, (int, float)) and isinstance(proven, (int, float)) and proven:
        return round(abs(claimed - proven) / abs(proven), 6)
    return None


def claims_from_reconciliation(
    recon: Reconciliation,
    *,
    counterparty: str | None = None,
    counterparty_role: str = "unknown",
) -> list[ClaimOutcomeRecord]:
    """Extract gradeable claim outcomes from one reconciliation result."""
    records: list[ClaimOutcomeRecord] = []
    recorded_at = _now()

    for res in recon.resolutions:
        proven_kind = res.lineage.doc_kind
        proven_authority = SOURCE_AUTHORITY.get(proven_kind, 5)

        # Gather every counterparty-authored claim on this field, from the conflict
        # (overridden values are kept there) and from corroborating docs.
        graded: list[tuple[float | str | None, DocKind, str, str]] = []
        # (claimed_value, claimed_doc_kind, verdict, document_id)

        if res.conflict is not None:
            for claim in res.conflict.claims:
                kind = claim.figure.lineage.doc_kind
                if kind not in _GRADED_DOC_KINDS:
                    continue
                value = claim.figure.value
                if value == res.value and kind == proven_kind:
                    continue  # the winning claim itself, not a graded assertion
                verdict = (
                    "unresolved"
                    if res.conflict.resolution == "unresolved"
                    else ("corroborated" if value == res.value else "overridden")
                )
                graded.append((value, kind, verdict, claim.figure.lineage.document_id))
        elif proven_kind in _GRADED_DOC_KINDS:
            # No conflict and the only source IS the counterparty: nothing proved or
            # disproved it — that is unverified, not corroborated. Skip: recording it
            # as a hit would inflate accuracy with untested claims.
            continue

        for value, kind, verdict, doc_id in graded:
            # An "override" only grades the counterparty when a genuinely
            # higher-authority document resolved the field (lease 95 beats OM 30).
            if verdict == "overridden" and SOURCE_AUTHORITY.get(kind, 5) >= proven_authority:
                continue
            records.append(
                ClaimOutcomeRecord(
                    deal_id=recon.deal_id,
                    field=res.field,
                    subject=res.subject,
                    counterparty=counterparty,
                    counterparty_role=counterparty_role,  # type: ignore[arg-type]
                    claimed_value=value,
                    claimed_doc_kind=kind,
                    proven_value=res.value,
                    proven_doc_kind=proven_kind,
                    verdict=verdict,  # type: ignore[arg-type]
                    delta_pct=_delta_pct(value, res.value),
                    severity=res.conflict.severity if res.conflict else None,
                    source_document_id=doc_id,
                    recorded_at=recorded_at,
                )
            )
    return records


async def capture_reconciliation(
    recon: Reconciliation,
    *,
    counterparty: str | None = None,
    counterparty_role: str = "unknown",
) -> int:
    """Persist claim outcomes from a reconciliation. Never raises: capture must
    not break the tool that triggered it."""
    try:
        records = claims_from_reconciliation(
            recon, counterparty=counterparty, counterparty_role=counterparty_role
        )
        if not records:
            return 0
        return await get_ledger_store().record_claims(records)
    except Exception:  # pragma: no cover - defensive: ledger failure is never fatal
        logger.exception("claim-ledger capture failed for deal %s", recon.deal_id)
        return 0
