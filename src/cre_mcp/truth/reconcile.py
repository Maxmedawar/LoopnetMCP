"""Reconcile competing claims by SOURCE AUTHORITY — never by averaging.

Phase 25 emits a claim per document ("the OM says NOI is X", "the T12 says Y").
This module resolves each canonical field to ONE value using an authority ladder
(an executed lease outranks a marketing OM), surfaces every material disagreement
as a Conflict that keeps BOTH values for human review, and flags pro-forma numbers
masquerading as in-place. It never silently splits the difference.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from cre_mcp.truth.models import DocKind, FieldClaim, Lineage

# Higher wins. An executed lease + amendments is ground truth for rent/term; a
# marketing OM is the weakest document; a scraped listing weaker still.
SOURCE_AUTHORITY: dict[DocKind, int] = {
    DocKind.AMENDMENT: 100,
    DocKind.LEASE: 95,
    DocKind.ESTOPPEL: 90,
    DocKind.BANK_STMT: 80,
    DocKind.SURVEY: 72,
    DocKind.TAX_BILL: 78,
    DocKind.ASSESSOR: 70,
    DocKind.APPRAISAL: 65,
    DocKind.RENT_ROLL: 55,
    DocKind.T12: 50,
    DocKind.OM: 30,
    DocKind.LISTING: 20,
    DocKind.UNKNOWN: 5,
}

# A lower claim only becomes a conflict if it disagrees beyond this (rounding is
# not a conflict). Categorical mismatches always conflict.
_MATERIALITY = 0.02

Severity = Literal["info", "warning", "material", "fatal"]


class Conflict(BaseModel):
    field: str
    subject: str | None = None
    rule: str
    severity: Severity
    claims: list[FieldClaim]
    resolved_value: float | str | None
    resolution: Literal["auto_hierarchy", "corroborated", "unresolved"]
    needs_human_review: bool
    explanation: str


class FieldResolution(BaseModel):
    field: str
    subject: str | None = None
    value: float | str | None
    unit: str
    confidence: float
    lineage: Lineage
    corroborating_docs: list[str] = Field(default_factory=list)
    conflict: Conflict | None = None


class Reconciliation(BaseModel):
    deal_id: str
    resolutions: list[FieldResolution]
    conflicts: list[Conflict]
    doc_kinds_present: list[str] = Field(default_factory=list)
    generated_at: str


def _authority(claim: FieldClaim) -> int:
    return SOURCE_AUTHORITY.get(claim.figure.lineage.doc_kind, 5)


def _disagree(a: float | str | None, b: float | str | None) -> bool:
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        scale = max(abs(a), abs(b), 1e-9)
        return abs(a - b) / scale > _MATERIALITY
    return str(a).strip().casefold() != str(b).strip().casefold()


def _rank_key(claim: FieldClaim) -> tuple[int, float, str]:
    return (_authority(claim), claim.figure.confidence, claim.figure.lineage.document_id)


def resolve(deal_id: str, claims: list[FieldClaim]) -> Reconciliation:
    """Resolve every (field, subject) group to one value; surface conflicts."""
    groups: dict[tuple[str, str | None], list[FieldClaim]] = {}
    for claim in claims:
        groups.setdefault((claim.field, claim.subject), []).append(claim)

    resolutions: list[FieldResolution] = []
    conflicts: list[Conflict] = []

    for (field, subject), members in groups.items():
        ranked = sorted(members, key=_rank_key, reverse=True)
        winner = ranked[0]
        losers = ranked[1:]

        # Pro-forma masquerading as in-place: winner is projected but no in-place
        # figure exists to check it against.
        proforma_winner = "proforma_not_actual" in winner.flags

        disagreeing = [c for c in losers if _disagree(winner.figure.value, c.figure.value)]
        corroborating = [
            c.figure.lineage.document_id
            for c in losers
            if not _disagree(winner.figure.value, c.figure.value)
            and c.figure.lineage.document_id != winner.figure.lineage.document_id
        ]

        conflict: Conflict | None = None
        if disagreeing:
            worst = max(
                (abs(_rel(winner.figure.value, c.figure.value)) for c in disagreeing),
                default=0.0,
            )
            severity: Severity = "material" if worst > 0.10 else "warning"
            conflict = Conflict(
                field=field,
                subject=subject,
                rule="source_disagreement",
                severity=severity,
                claims=[winner, *disagreeing],
                resolved_value=winner.figure.value,
                resolution="auto_hierarchy",
                needs_human_review=severity in ("material", "fatal"),
                explanation=(
                    f"{field}{f' [{subject}]' if subject else ''}: "
                    f"{_cite(winner)} = {winner.figure.value} "
                    f"outranks " + "; ".join(f"{_cite(c)} = {c.figure.value}" for c in disagreeing)
                    + ". Higher-authority source wins; values NOT averaged."
                ),
            )
            conflicts.append(conflict)
        elif proforma_winner:
            conflict = Conflict(
                field=field,
                subject=subject,
                rule="proforma_as_actual",
                severity="material",
                claims=[winner],
                resolved_value=winner.figure.value,
                resolution="unresolved",
                needs_human_review=True,
                explanation=(
                    f"{field} = {winner.figure.value} is PRO FORMA/projected "
                    f"({_cite(winner)}); no verified in-place figure was provided to confirm it."
                ),
            )
            conflicts.append(conflict)

        confidence = winner.figure.confidence
        if corroborating:
            confidence = min(0.99, confidence + 0.1)

        resolutions.append(
            FieldResolution(
                field=field,
                subject=subject,
                value=winner.figure.value,
                unit=winner.figure.unit,
                confidence=confidence,
                lineage=winner.figure.lineage,
                corroborating_docs=corroborating,
                conflict=conflict,
            )
        )

    doc_kinds = sorted({c.figure.lineage.doc_kind.value for c in claims})
    return Reconciliation(
        deal_id=deal_id,
        resolutions=resolutions,
        conflicts=conflicts,
        doc_kinds_present=doc_kinds,
        generated_at=datetime.now(UTC).isoformat(),
    )


def _rel(a: float | str | None, b: float | str | None) -> float:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return (a - b) / max(abs(a), abs(b), 1e-9)
    return 1.0


def _cite(claim: FieldClaim) -> str:
    line = claim.figure.lineage
    loc = line.cell or (f"p{line.page}" if line.page else "")
    return f"{line.doc_kind.value}{f' {loc}' if loc else ''}"


__all__ = [
    "SOURCE_AUTHORITY",
    "Conflict",
    "FieldResolution",
    "Reconciliation",
    "resolve",
]
