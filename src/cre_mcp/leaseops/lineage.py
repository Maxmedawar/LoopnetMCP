"""Read-only truth-store lineage walks for one canonical field."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.truth.models import FieldClaim
from cre_mcp.truth.reconcile import Reconciliation, resolve
from cre_mcp.truth.store import TruthStore, get_truth_store


def _text(value: Any, name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text" + (" or null" if nullable else ""))
    result = value.strip()
    if not result:
        if nullable:
            return None
        raise ValueError(f"{name} cannot be blank")
    return result


def _read_claims(path: Path, deal_id: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT claim_json FROM truth_claims WHERE deal_id=? ORDER BY field, subject, document_id",
            (deal_id,),
        ).fetchall()
        return [json.loads(str(row["claim_json"])) for row in rows]
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).casefold():
            return []
        raise
    finally:
        connection.close()


def _chain(claim: FieldClaim, *, role: str, explanation: str) -> dict[str, Any]:
    figure = claim.figure
    source = figure.lineage
    location = {
        "page": source.page,
        "cell": source.cell,
        "bbox": list(source.bbox) if source.bbox is not None else None,
    }
    return {
        "role": role,
        "document": {
            "document_id": source.document_id,
            "doc_kind": source.doc_kind.value,
            "source_channel": source.source_channel,
            "origin": source.origin,
        },
        "location": location,
        "raw_text": source.raw_text,
        "extraction": {
            "method": source.extraction_method.value,
            "confidence": figure.confidence,
            "flags": list(claim.flags),
        },
        "claim": {
            "field": claim.field,
            "subject": claim.subject,
            "value": figure.value,
            "unit": figure.unit,
        },
        "reconciliation": {"role": role, "explanation": explanation},
    }


def _resolution_for(reconciliation: Reconciliation, subject: str | None):
    return next(item for item in reconciliation.resolutions if item.subject == subject)


def _same_winner(claim: FieldClaim, resolution: Any) -> bool:
    line = claim.figure.lineage
    return (
        line.document_id == resolution.lineage.document_id
        and claim.figure.value == resolution.value
        and claim.subject == resolution.subject
    )


async def trace_input(
    deal_id: str,
    field: str,
    subject: str | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Trace every stored claim for one field through the reconciliation winner."""

    normalized_deal = _text(deal_id, "deal_id")
    normalized_field = _text(field, "field")
    normalized_subject = _text(subject, "subject", nullable=True)
    if db_path is None:
        store = get_truth_store()
        raw_claims = await store.get_claims(normalized_deal)
        source_path = str(getattr(store, "db_path", "configured truth store"))
    else:
        source_path = str(TruthStore(CreConfig(cache_db_path=Path(db_path))).db_path)
        raw_claims = _read_claims(Path(source_path), normalized_deal)

    claims: list[FieldClaim] = []
    malformed: list[str] = []
    for index, raw in enumerate(raw_claims):
        try:
            claim = FieldClaim.model_validate(raw)
        except Exception as exc:
            malformed.append(f"claim[{index}]: {exc}")
            continue
        if claim.field != normalized_field:
            continue
        if normalized_subject is not None and claim.subject != normalized_subject:
            continue
        claims.append(claim)
    if malformed:
        raise ValueError("malformed truth claims encountered: " + "; ".join(malformed))

    if not claims:
        return {
            "deal_id": normalized_deal,
            "field": normalized_field,
            "subject": normalized_subject,
            "status": "missing",
            "winner": None,
            "losers": [],
            "groups": [],
            "lineage_chain": [],
            "read_only": True,
            "truth_store_path": source_path,
            "honest_gap": (
                "No stored truth claim matches this deal, field, and optional subject; "
                "no value or source lineage was inferred."
            ),
        }

    reconciliation = resolve(normalized_deal, claims)
    groups: list[dict[str, Any]] = []
    subjects = sorted({claim.subject for claim in claims}, key=lambda value: (value is not None, value or ""))
    for group_subject in subjects:
        members = [claim for claim in claims if claim.subject == group_subject]
        resolution = _resolution_for(reconciliation, group_subject)
        winner = next(claim for claim in members if _same_winner(claim, resolution))
        losers = [claim for claim in members if claim is not winner]
        explanation = (
            resolution.conflict.explanation
            if resolution.conflict is not None
            else "Highest source authority, then confidence, determined the winner; values were not averaged."
        )
        winner_chain = _chain(winner, role="winner", explanation=explanation)
        loser_chains = [_chain(item, role="loser", explanation=explanation) for item in losers]
        groups.append(
            {
                "subject": group_subject,
                "resolved_value": resolution.value,
                "unit": resolution.unit,
                "confidence": resolution.confidence,
                "resolution": (
                    resolution.conflict.resolution if resolution.conflict is not None else "single_or_corroborated"
                ),
                "winner": winner_chain,
                "losers": loser_chains,
                "corroborating_documents": list(resolution.corroborating_docs),
                "conflict": resolution.conflict.model_dump(mode="json") if resolution.conflict is not None else None,
                "lineage_chain": [winner_chain, *loser_chains],
            }
        )

    first = groups[0]
    return {
        "deal_id": normalized_deal,
        "field": normalized_field,
        "subject": normalized_subject,
        "status": "resolved_with_conflict" if reconciliation.conflicts else "resolved",
        "winner": first["winner"] if len(groups) == 1 else None,
        "losers": first["losers"] if len(groups) == 1 else [],
        "groups": groups,
        "lineage_chain": first["lineage_chain"] if len(groups) == 1 else [],
        "read_only": True,
        "truth_store_path": source_path,
        "honest_gap": None,
    }


__all__ = ["trace_input"]
