"""Compact, evidence-linked pre-call counterparty briefing."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DealStore
from cre_mcp.ledger.store import LedgerStore
from cre_mcp.negotiation.commitments import CommitmentStore

from .dossier import (
    ANECDOTE_NOTE,
    _as_utc,
    _collect_evidence,
    _last_interaction,
    _parse_time,
    _required_text,
)


def _due_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _annotate_commitment(
    commitment: Mapping[str, Any], as_of: datetime
) -> dict[str, Any]:
    row = dict(commitment)
    parsed_due = _due_date(row.get("due"))
    row["overdue"] = parsed_due is not None and parsed_due < as_of.date()
    row["due_status"] = (
        "overdue"
        if row["overdue"]
        else ("dated_open" if parsed_due is not None else "no_due_date_recorded")
    )
    return row


def _dedupe_commitments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        identity = (
            row.get("id"),
            row.get("deal_id"),
            row.get("made_by"),
            row.get("commitment"),
            row.get("made_at"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(row)
    return result


def _event_sort_key(event: Mapping[str, Any]) -> tuple[datetime, str]:
    parsed = _parse_time(event.get("event_ts") or event.get("created_at"))
    return parsed or datetime.min.replace(tzinfo=UTC), str(event.get("event_type", ""))


def _track_record_highlights(evidence: Mapping[str, Any]) -> dict[str, Any]:
    claims = evidence["claims"]
    quotes = evidence["quotes"]
    commitments = evidence["commitments"]
    corroborated = sum(claim.verdict == "corroborated" for claim in claims)
    overridden = sum(claim.verdict == "overridden" for claim in claims)
    tested = corroborated + overridden
    closed = sum(quote.stage == "closed" for quote in quotes)
    died = sum(quote.stage == "died" for quote in quotes)
    statuses = Counter(str(item.get("status", "unknown")) for item in commitments)
    theirs_kept = sum(
        item.get("made_by") == "them" and item.get("status") == "kept"
        for item in commitments
    )
    theirs_broken = sum(
        item.get("made_by") == "them" and item.get("status") == "broken"
        for item in commitments
    )
    serious_defects = sum(
        defect.severity in {"material", "fatal"}
        or defect.outcome in {"retrade", "kill"}
        for defect in evidence["defects"]
    )
    return {
        "claim_sample_size": len(claims),
        "quote_sample_size": len(quotes),
        "commitment_sample_size": len(commitments),
        "defect_sample_size": len(evidence["defects"]),
        "claim_track_record": {
            "sample_size": len(claims),
            "tested_sample_size": tested,
            "corroborated": corroborated,
            "overridden": overridden,
            "accuracy_rate": round(corroborated / tested, 4) if tested else None,
        },
        "lender_quote_history": {
            "sample_size": len(quotes),
            "resolved_sample_size": closed + died,
            "closed": closed,
            "died": died,
        },
        "commitment_history": {
            "sample_size": len(commitments),
            "status_counts": dict(sorted(statuses.items())),
            "kept_by_them": theirs_kept,
            "broken_by_them": theirs_broken,
            "attribution_note": (
                "Commitments name parties only as us/them and are associated through "
                "the selected deal scope, not asserted as named-party identity proof."
            ),
        },
        "attributed_defects": {
            "sample_size": len(evidence["defects"]),
            "material_fatal_retrade_or_kill": serious_defects,
        },
        "honesty": ANECDOTE_NOTE,
    }


def _agenda(open_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agenda: list[dict[str, Any]] = []
    for row in sorted(
        open_rows,
        key=lambda item: (
            not item["overdue"],
            item.get("due") is None,
            str(item.get("due") or ""),
            int(item.get("id") or 0),
        ),
    ):
        made_by = str(row.get("made_by", "unknown"))
        if row["overdue"] and made_by == "them":
            action = "Resolve overdue counterparty commitment"
        elif row["overdue"] and made_by == "us":
            action = "Acknowledge and resolve our overdue commitment"
        elif made_by == "them":
            action = "Confirm status and timing of counterparty commitment"
        else:
            action = "Confirm our owner, delivery date, and next update"
        agenda.append(
            {
                "priority": len(agenda) + 1,
                "agenda_item": f"{action}: {row.get('commitment')}",
                "made_by": made_by,
                "due": row.get("due"),
                "overdue": row["overdue"],
                "deal_id": row.get("deal_id"),
                "source_ref": {"table": "neg_commitments", "id": row.get("id")},
            }
        )
    if not agenda:
        agenda.append(
            {
                "priority": 1,
                "agenda_item": (
                    "Confirm current priorities and next steps; no open commitments "
                    "were recorded in scope."
                ),
                "made_by": None,
                "due": None,
                "overdue": False,
                "deal_id": None,
                "source_ref": None,
            }
        )
    return agenda


async def meeting_briefing(
    counterparty: str,
    deal_id: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
    ledger_store: LedgerStore | None = None,
    deal_store: DealStore | None = None,
    license_screen: Mapping[str, Any] | None = None,
    as_of: Any = None,
) -> dict[str, Any]:
    """Build a one-page-equivalent briefing from recorded pre-call evidence."""

    normalized_counterparty = _required_text(counterparty, "counterparty")
    normalized_deal_id = (
        _required_text(deal_id, "deal_id") if deal_id is not None else None
    )
    report_as_of = _as_utc(as_of)
    evidence = await _collect_evidence(
        normalized_counterparty,
        db_path=db_path,
        config=config,
        ledger_store=ledger_store,
        deal_store=deal_store,
        license_screen=license_screen,
        as_of=report_as_of,
    )
    relevant_deal_ids = (
        [normalized_deal_id]
        if normalized_deal_id is not None
        else list(evidence["linked_deal_ids"])
    )

    commitments = [
        dict(item)
        for item in evidence["commitments"]
        if not relevant_deal_ids or item.get("deal_id") in relevant_deal_ids
    ]
    if normalized_deal_id is not None:
        commitment_store = CommitmentStore(evidence["path"])
        for raw_item in commitment_store.list_commitments(normalized_deal_id):
            item = dict(raw_item)
            item["deal_id"] = normalized_deal_id
            commitments.append(item)
    commitments = _dedupe_commitments(commitments)
    annotated_open = [
        _annotate_commitment(item, report_as_of)
        for item in commitments
        if item.get("status") == "open"
    ]
    ours = [item for item in annotated_open if item.get("made_by") == "us"]
    theirs = [item for item in annotated_open if item.get("made_by") == "them"]
    overdue = [item for item in annotated_open if item["overdue"]]

    if normalized_deal_id is not None:
        scoped_events = [
            event
            for event in evidence["all_events"]
            if event.get("deal_id") == normalized_deal_id
        ]
    else:
        scoped_events = list(evidence["events"])
    recent_events = sorted(scoped_events, key=_event_sort_key, reverse=True)[:5]

    deal_context = [
        evidence["deal_summaries"][selected_id]
        for selected_id in relevant_deal_ids
        if selected_id in evidence["deal_summaries"]
    ]
    latest_event = recent_events[0] if recent_events else None
    state = (
        "active_open_items"
        if annotated_open
        else ("recorded_context_no_open_items" if recent_events else "no_recorded_state")
    )
    return {
        "counterparty": normalized_counterparty,
        "deal_id": normalized_deal_id,
        "deal_scope": relevant_deal_ids,
        "as_of": report_as_of.isoformat(),
        "open_commitments": {
            "sample_size": len(annotated_open),
            "theirs": theirs,
            "ours": ours,
            "overdue": overdue,
            "theirs_overdue": [item for item in theirs if item["overdue"]],
            "ours_overdue": [item for item in ours if item["overdue"]],
        },
        "last_5_events": recent_events,
        "active_negotiation_state": {
            "status": state,
            "open_commitment_count": len(annotated_open),
            "open_from_them": len(theirs),
            "open_from_us": len(ours),
            "overdue_count": len(overdue),
            "latest_event_type": latest_event.get("event_type") if latest_event else None,
            "latest_event_detail": latest_event.get("detail") if latest_event else None,
            "negotiation_state": (
                latest_event.get("detail", {}).get("negotiation_state")
                if latest_event and isinstance(latest_event.get("detail"), Mapping)
                else None
            ),
            "deal_stages": [
                {"deal_id": item.get("deal_id"), "stage": item.get("stage")}
                for item in deal_context
            ],
            "note": (
                "State is assembled from open neg_commitments, deal stages, and the "
                "recorded event timeline; it does not infer unrecorded intent."
            ),
        },
        "track_record_highlights": _track_record_highlights(evidence),
        "suggested_agenda_items": _agenda(annotated_open),
        "last_interaction": _last_interaction(evidence),
        "deal_context": deal_context,
        "honesty": ANECDOTE_NOTE,
        "scope": (
            "Pre-call internal one-pager assembled from permissioned recorded evidence. "
            "Verify current facts during the call and do not treat missing rows as proof "
            "that no obligation, issue, or interaction exists."
        ),
        "evidence_scope": (
            "Recorded permissioned commitments, deal events, ledgers, and governed "
            "touch history only; missing records remain unknown."
        ),
    }


__all__ = ["meeting_briefing"]
