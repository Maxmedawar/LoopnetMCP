"""Relationship-intelligence MCP boundaries with closed restricted projections.

The public functions remain registration-neutral. Territory-limited workspaces
receive only records that bind exactly to the workspace-owned deal and
commitment stores; trusted/full-operator calls retain the original payloads.
Implementation failures stay contained at the stable ``{"error": ...}``
boundary for middleware enforcement.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.access.context import current_context
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.access.result_models import (
    RestrictedCounterpartyDossierResult,
    RestrictedMeetingBriefingResult,
)
from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DealStore
from cre_mcp.negotiation.commitments import CommitmentStore
from cre_mcp.source_rights.output import safe_error_message

from .appraisal_challenge import challenge_appraisal as _challenge_appraisal
from .briefing import meeting_briefing as _meeting_briefing
from .coverage import coverage_report as _coverage_report
from .coverage import route_lead as _route_lead
from .dossier import counterparty_dossier as _counterparty_dossier
from .stalls import record_thread_state as _record_thread_state
from .stalls import stalled_threads as _stalled_threads
from .whotocall import who_to_call as _who_to_call

logger = logging.getLogger(__name__)


_DOSSIER_RED_FLAG_KINDS = frozenset(
    {
        "overridden_claims",
        "quotes_died",
        "adverse_retrades",
        "broken_commitments_by_them",
        "material_or_outcome_defects",
        "registry_flags_for_candidate_matches",
    }
)


def _restricted_projection_required() -> bool:
    context = current_context()
    return bool(
        context is not None
        and not context.trusted
        and context.profile in TERRITORY_LIMITED
    )


def _required_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label)


def _mapping_rows(value: object, label: str) -> list[Mapping[str, Any]]:
    if type(value) is not list or not all(isinstance(row, Mapping) for row in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _unique_text_rows(value: object, label: str) -> list[str]:
    if type(value) is not list or not value:
        raise ValueError(f"{label} must be a non-empty list")
    rows = [_required_text(item, f"{label}[]") for item in value]
    if len(rows) != len(set(rows)):
        raise ValueError(f"{label} values must be unique")
    return rows


def _subject_property(value: object, label: str) -> dict[str, object]:
    record = _required_mapping(value, label)
    zip_code = record.get("zip_code")
    if zip_code is not None:
        zip_code = _required_text(zip_code, f"{label}.zip_code")
    return {
        "address": _required_text(record.get("address"), f"{label}.address"),
        "city": _required_text(record.get("city"), f"{label}.city"),
        "state": _required_text(record.get("state"), f"{label}.state"),
        "zip_code": zip_code,
    }


def _same_json(left: object, right: object) -> bool:
    """Compare store-derived JSON with key order ignored and types preserved."""

    try:
        return json.dumps(
            left,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ) == json.dumps(
            right,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError):
        return False


async def _stored_deal(
    store: DealStore,
    deal_id: str,
) -> Mapping[str, Any]:
    deal = await store.get_deal(deal_id)
    if not isinstance(deal, Mapping) or deal.get("deal_id") != deal_id:
        raise ValueError(f"unknown or mismatched deal anchor: {deal_id}")
    return deal


def _project_deal(deal: Mapping[str, Any]) -> dict[str, object]:
    deal_id = _required_text(deal.get("deal_id"), "stored deal.deal_id")
    return {
        "deal_id": deal_id,
        "property": _subject_property(deal.get("listing"), f"deal {deal_id}.listing"),
        "stage": _required_text(deal.get("stage"), f"deal {deal_id}.stage"),
        "score": deal.get("score"),
        "updated_at": _optional_text(
            deal.get("updated_at"), f"deal {deal_id}.updated_at"
        ),
    }


async def _project_deal_anchors(
    deal_ids: list[str],
    store: DealStore,
) -> tuple[list[dict[str, object]], dict[str, Mapping[str, Any]]]:
    projected: list[dict[str, object]] = []
    stored: dict[str, Mapping[str, Any]] = {}
    for deal_id in deal_ids:
        deal = await _stored_deal(store, deal_id)
        stored[deal_id] = deal
        projected.append(_project_deal(deal))
    return projected, stored


async def _validate_stored_events(
    raw_events: object,
    deal_ids: list[str],
    store: DealStore,
) -> list[dict[str, object]]:
    rows = _mapping_rows(raw_events, "relation events")
    allowed = set(deal_ids)
    remaining_by_deal: dict[str, list[dict[str, Any]]] = {}
    projected: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        deal_id = _required_text(row.get("deal_id"), f"events[{index}].deal_id")
        if deal_id not in allowed:
            raise ValueError("relation event is not bound to a returned deal")
        if deal_id not in remaining_by_deal:
            timeline = await store.get_deal_timeline(deal_id)
            if not isinstance(timeline, Mapping) or timeline.get("deal_id") != deal_id:
                raise ValueError("relation event timeline does not match its deal")
            stored_events = _mapping_rows(
                timeline.get("events"), f"stored timeline {deal_id}.events"
            )
            remaining_by_deal[deal_id] = [
                {**dict(stored_event), "deal_id": deal_id}
                for stored_event in stored_events
            ]
        candidates = remaining_by_deal[deal_id]
        matched_index = next(
            (
                candidate_index
                for candidate_index, candidate in enumerate(candidates)
                if _same_json(candidate, dict(row))
            ),
            None,
        )
        if matched_index is None:
            raise ValueError("relation event does not match the owned deal timeline")
        candidates.pop(matched_index)
        projected.append(
            {
                "deal_id": deal_id,
                "event_ts": _optional_text(
                    row.get("event_ts"), f"events[{index}].event_ts"
                ),
                "created_at": _optional_text(
                    row.get("created_at"), f"events[{index}].created_at"
                ),
            }
        )
    return projected


def _as_of_date(value: object) -> tuple[str, date]:
    text = _required_text(value, "as_of")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("as_of must be an ISO datetime") from exc
    return text, parsed.date()


def _annotated_open_commitments(
    deal_ids: list[str],
    store: CommitmentStore,
    report_date: date,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for deal_id in deal_ids:
        for stored in store.list_commitments(deal_id, status="open"):
            row = dict(stored)
            if row.get("deal_id") != deal_id:
                raise ValueError("commitment store returned a mismatched deal anchor")
            raw_due = row.get("due")
            try:
                parsed_due = date.fromisoformat(raw_due) if raw_due is not None else None
            except (TypeError, ValueError) as exc:
                raise ValueError("stored commitment due date is malformed") from exc
            row["overdue"] = parsed_due is not None and parsed_due < report_date
            row["due_status"] = (
                "overdue"
                if row["overdue"]
                else ("dated_open" if parsed_due is not None else "no_due_date_recorded")
            )
            rows.append(row)
    return rows


def _require_exact_rows(
    actual: object,
    expected: list[dict[str, Any]],
    label: str,
) -> list[Mapping[str, Any]]:
    rows = _mapping_rows(actual, label)
    if len(rows) != len(expected) or any(
        not _same_json(dict(row), expected[index]) for index, row in enumerate(rows)
    ):
        raise ValueError(f"{label} do not match the owned store")
    return rows


async def _restricted_meeting_projection(
    requested_counterparty: str,
    requested_deal_id: str | None,
    result: object,
) -> dict[str, Any]:
    envelope = _required_mapping(result, "meeting briefing result")
    counterparty = _required_text(requested_counterparty, "counterparty")
    if envelope.get("counterparty") != counterparty:
        raise ValueError("meeting briefing counterparty does not match the request")
    normalized_deal_id = (
        _required_text(requested_deal_id, "deal_id")
        if requested_deal_id is not None
        else None
    )
    if envelope.get("deal_id") != normalized_deal_id:
        raise ValueError("meeting briefing deal does not match the request")

    deal_ids = _unique_text_rows(envelope.get("deal_scope"), "deal_scope")
    if normalized_deal_id is not None and deal_ids != [normalized_deal_id]:
        raise ValueError("meeting briefing scope does not match the requested deal")
    context_rows = _mapping_rows(envelope.get("deal_context"), "deal_context")
    context_ids = [
        _required_text(row.get("deal_id"), f"deal_context[{index}].deal_id")
        for index, row in enumerate(context_rows)
    ]
    if context_ids != deal_ids:
        raise ValueError("meeting deal context does not exactly match deal_scope")

    deal_store = DealStore()
    stored_summaries = {
        row.get("deal_id"): row
        for row in await deal_store.list_deals()
        if isinstance(row, Mapping) and isinstance(row.get("deal_id"), str)
    }
    if len(stored_summaries) < len(deal_ids):
        raise ValueError("meeting deal summaries are incomplete")
    for index, row in enumerate(context_rows):
        stored_summary = stored_summaries.get(deal_ids[index])
        if not isinstance(stored_summary, Mapping) or not _same_json(
            dict(row), dict(stored_summary)
        ):
            raise ValueError("meeting deal context does not match the owned store")

    deals, _stored = await _project_deal_anchors(deal_ids, deal_store)
    raw_events = envelope.get("last_5_events")
    events = await _validate_stored_events(raw_events, deal_ids, deal_store)
    if len(events) > 5:
        raise ValueError("meeting briefing may return at most five events")

    as_of, report_date = _as_of_date(envelope.get("as_of"))
    open_envelope = _required_mapping(
        envelope.get("open_commitments"), "open_commitments"
    )
    expected_open = _annotated_open_commitments(
        deal_ids,
        CommitmentStore(),
        report_date,
    )
    expected_theirs = [row for row in expected_open if row.get("made_by") == "them"]
    expected_ours = [row for row in expected_open if row.get("made_by") == "us"]
    expected_overdue = [row for row in expected_open if row["overdue"]]
    _require_exact_rows(open_envelope.get("theirs"), expected_theirs, "theirs")
    _require_exact_rows(open_envelope.get("ours"), expected_ours, "ours")
    _require_exact_rows(open_envelope.get("overdue"), expected_overdue, "overdue")
    _require_exact_rows(
        open_envelope.get("theirs_overdue"),
        [row for row in expected_theirs if row["overdue"]],
        "theirs_overdue",
    )
    _require_exact_rows(
        open_envelope.get("ours_overdue"),
        [row for row in expected_ours if row["overdue"]],
        "ours_overdue",
    )
    if open_envelope.get("sample_size") != len(expected_open):
        raise ValueError("meeting commitment sample size does not match the store")

    state = _required_mapping(
        envelope.get("active_negotiation_state"), "active_negotiation_state"
    )
    expected_status = (
        "active_open_items"
        if expected_open
        else ("recorded_context_no_open_items" if events else "no_recorded_state")
    )
    expected_state_counts = {
        "open_commitment_count": len(expected_open),
        "open_from_them": len(expected_theirs),
        "open_from_us": len(expected_ours),
        "overdue_count": len(expected_overdue),
    }
    if state.get("status") != expected_status or any(
        state.get(key) != expected for key, expected in expected_state_counts.items()
    ):
        raise ValueError("meeting negotiation state does not reconcile")

    commitments = [
        {
            "commitment_id": row.get("id"),
            "deal_id": row.get("deal_id"),
            "made_by": row.get("made_by"),
            "status": row.get("status"),
            "due": row.get("due"),
            "overdue": row.get("overdue"),
        }
        for row in (*expected_theirs, *expected_ours)
    ]
    return RestrictedMeetingBriefingResult.model_validate(
        {
            "counterparty": counterparty,
            "deal_id": normalized_deal_id,
            "as_of": as_of,
            "status": expected_status,
            "deals": deals,
            "events": events,
            "commitments": commitments,
            "deal_count": len(deals),
            "event_count": len(events),
            "commitment_count": len(commitments),
            "overdue_count": len(expected_overdue),
        },
        strict=True,
    ).model_dump(mode="json")


async def _restricted_dossier_projection(
    requested_name: str,
    result: object,
) -> dict[str, Any]:
    envelope = _required_mapping(result, "counterparty dossier result")
    name = _required_text(requested_name, "name")
    if envelope.get("who") != name:
        raise ValueError("counterparty dossier name does not match the request")
    deal_ids = _unique_text_rows(envelope.get("linked_deal_ids"), "linked_deal_ids")
    deal_store = DealStore()
    deals, stored_deals = await _project_deal_anchors(deal_ids, deal_store)

    evidence = _required_mapping(envelope.get("evidence_summary"), "evidence_summary")
    deal_events = _required_mapping(evidence.get("deal_events"), "deal_events")
    raw_events = _mapping_rows(deal_events.get("records"), "deal event records")
    if deal_events.get("sample_size") != len(raw_events):
        raise ValueError("dossier event sample size does not reconcile")
    if deal_events.get("deal_sample_size") != len(
        {row.get("deal_id") for row in raw_events}
    ):
        raise ValueError("dossier event deal sample size does not reconcile")
    events = await _validate_stored_events(raw_events, deal_ids, deal_store)

    evidence_properties: list[dict[str, object]] = []
    for index, raw_event in enumerate(raw_events):
        detail = raw_event.get("detail")
        if not isinstance(detail, Mapping) or "property" not in detail:
            continue
        deal_id = _required_text(
            raw_event.get("deal_id"), f"deal event records[{index}].deal_id"
        )
        property_record = _subject_property(
            detail.get("property"), f"deal event records[{index}].detail.property"
        )
        stored_property = _project_deal(stored_deals[deal_id])["property"]
        if not _same_json(property_record, stored_property):
            raise ValueError("dossier property evidence does not match its deal anchor")
        evidence_properties.append(
            {"deal_id": deal_id, "property": property_record}
        )

    raw_flags = _mapping_rows(envelope.get("red_flags"), "red_flags")
    red_flags: list[dict[str, object]] = []
    for index, row in enumerate(raw_flags):
        kind = _required_text(row.get("kind"), f"red_flags[{index}].kind")
        count = row.get("count")
        if kind not in _DOSSIER_RED_FLAG_KINDS:
            raise ValueError("dossier red flag kind is not recognized")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("dossier red flag count is malformed")
        red_flags.append({"kind": kind, "count": count})

    as_of, _report_date = _as_of_date(envelope.get("as_of"))
    return RestrictedCounterpartyDossierResult.model_validate(
        {
            "who": name,
            "as_of": as_of,
            "deals": deals,
            "evidence_properties": evidence_properties,
            "events": events,
            "red_flags": red_flags,
            "deal_count": len(deals),
            "evidence_property_count": len(evidence_properties),
            "event_count": len(events),
            "red_flag_count": len(red_flags),
        },
        strict=True,
    ).model_dump(mode="json")


def _error(tool_name: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = safe_error_message(message or exc.__class__.__name__)
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
        result = await _counterparty_dossier(
            name,
            db_path=db_path,
            license_screen=license_screen,
            verifyreg_output=verifyreg_output,
            as_of=as_of,
        )
        if _restricted_projection_required():
            return await _restricted_dossier_projection(name, result)
        return result
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
        result = await _meeting_briefing(
            counterparty,
            deal_id,
            db_path=db_path,
            license_screen=license_screen,
            as_of=as_of,
        )
        if _restricted_projection_required():
            return await _restricted_meeting_projection(
                counterparty,
                deal_id,
                result,
            )
        return result
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
        result = _challenge_appraisal(appraisal, evidence)
        tenant = current_context()
        if (
            tenant is not None
            and not tenant.trusted
            and tenant.profile in TERRITORY_LIMITED
        ):
            for row in result.get("divergence_table", []):
                if not isinstance(row, dict):
                    continue
                for field in ("their_input", "our_evidence"):
                    if type(row.get(field)) not in (int, float, type(None)):
                        row[field] = None
        return result
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
