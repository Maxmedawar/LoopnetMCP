"""Evidence-linked deal postmortems with explicitly non-causal hypotheses."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Awaitable, TypeVar

from cre_mcp.ledger import LedgerStore, get_ledger_store


_T = TypeVar("_T")
_OUTCOMES = {"closed", "died"}
_CONSEQUENTIAL_DEFECT_OUTCOMES = {"retrade", "kill", "cure", "absorbed"}


def _await_sync(awaitable: Awaitable[_T]) -> _T:
    """Resolve the ledger's async read API from this synchronous domain function."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    # A sync FastMCP function can still be called by code already running an
    # event loop.  Resolve the independent SQLite read in a short-lived thread
    # rather than nesting event loops.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, awaitable).result()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError("ledger evidence must be mapping-like")


def _timeline_key(index_and_event: tuple[int, dict[str, Any]]) -> tuple[bool, str, int]:
    index, event = index_and_event
    raw = event.get("occurred_at", event.get("date", event.get("timestamp")))
    return (raw is None, "" if raw is None else str(raw), index)


def _normalize_timeline(timeline_events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(timeline_events, (str, bytes)):
        raise TypeError("timeline_events must be a sequence of objects")
    events: list[dict[str, Any]] = []
    for event in timeline_events:
        if not isinstance(event, Mapping):
            raise TypeError("each timeline event must be an object")
        events.append(dict(event))
    return [event for _, event in sorted(enumerate(events), key=_timeline_key)]


def _normalize_drift(drift_results: Any) -> list[dict[str, Any]]:
    if drift_results is None:
        return []
    if isinstance(drift_results, Mapping):
        candidate = drift_results
        for key in ("changes", "term_results", "terms", "results", "drift"):
            if key in drift_results:
                candidate = drift_results[key]
                break
        if isinstance(candidate, Mapping):
            return [dict(candidate)]
        drift_results = candidate
    if isinstance(drift_results, (str, bytes)) or not isinstance(drift_results, Sequence):
        raise TypeError("drift_results must be an object, a sequence of objects, or None")
    normalized: list[dict[str, Any]] = []
    for row in drift_results:
        if not isinstance(row, Mapping):
            raise TypeError("each drift result must be an object")
        normalized.append(dict(row))
    return normalized


def deal_postmortem(
    deal_id: str,
    timeline_events: Sequence[Mapping[str, Any]],
    outcome: Mapping[str, Any],
    drift_results: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a structured postmortem from supplied facts and defect-ledger evidence.

    No causal conclusion is generated. Every lesson and proposed screening-weight
    change is labeled ``HYPOTHESIS`` and retains its supporting evidence ids.
    ``db_path`` selects a ledger for deterministic testing or an alternate local
    environment; the defect ledger is only read through its public API.
    """

    if not isinstance(deal_id, str) or not deal_id.strip():
        raise ValueError("deal_id must be a non-empty string")
    if not isinstance(outcome, Mapping):
        raise TypeError("outcome must be an object")
    status = outcome.get("outcome", outcome.get("status"))
    if status not in _OUTCOMES:
        raise ValueError("outcome must identify status as closed or died")

    timeline = _normalize_timeline(timeline_events)
    drift = _normalize_drift(drift_results)
    store = LedgerStore(db_path) if db_path is not None else get_ledger_store()
    defects = [_as_dict(row) for row in _await_sync(store.defects_for(deal_id.strip()))]
    screening_defects = [
        row for row in defects if str(row.get("discovered_stage", "")).casefold() == "screening"
    ]

    signal_hypotheses: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    lessons: list[dict[str, Any]] = []
    for defect in screening_defects:
        defect_id = defect.get("defect_id")
        defect_type = defect.get("defect_type")
        consequential = defect.get("outcome") in _CONSEQUENTIAL_DEFECT_OUTCOMES
        signal_hypotheses.append(
            {
                "label": "HYPOTHESIS",
                "screening_signal": defect_type,
                "hypothesis": (
                    "This screening signal may have anticipated a consequential deal issue."
                    if consequential
                    else "This screening signal was present, but the available record does not show a consequential outcome."
                ),
                "evidence_defect_id": defect_id,
                "evidence_outcome": defect.get("outcome"),
                "causal_status": "not_established",
            }
        )
        recommendations.append(
            {
                "label": "HYPOTHESIS",
                "screening_signal": defect_type,
                "recommended_weight_change": "increase" if consequential else None,
                "recommendation": (
                    "Consider testing a higher future screening weight against more resolved outcomes."
                    if consequential
                    else "Do not change screening weight from this record alone."
                ),
                "evidence_defect_ids": [defect_id] if defect_id is not None else [],
                "confidence": "uncalibrated_single_deal",
            }
        )
        lessons.append(
            {
                "label": "HYPOTHESIS",
                "lesson": "Review this screening flag earlier in future deal gating.",
                "basis": "defect_ledger",
                "evidence_defect_ids": [defect_id] if defect_id is not None else [],
                "causal_status": "not_established",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "label": "HYPOTHESIS",
                "screening_signal": None,
                "recommended_weight_change": None,
                "recommendation": (
                    "No screening-weight change is supportable without a screening-stage defect linked to this deal."
                ),
                "evidence_defect_ids": [],
                "confidence": "insufficient_evidence",
            }
        )
    if drift:
        lessons.append(
            {
                "label": "HYPOTHESIS",
                "lesson": "Review the supplied LOI-to-close drift before attributing the outcome to screening.",
                "basis": "supplied_drift_results",
                "evidence_defect_ids": [],
                "causal_status": "not_established",
            }
        )
    if outcome.get("why") is not None:
        lessons.append(
            {
                "label": "HYPOTHESIS",
                "lesson": "The reported outcome reason is an input assertion that should be corroborated against the timeline and documents.",
                "basis": "reported_outcome_reason",
                "evidence_defect_ids": [],
                "causal_status": "not_established",
            }
        )

    return {
        "deal_id": deal_id.strip(),
        "outcome": {"status": status, "why": outcome.get("why")},
        "timeline": timeline,
        "defect_ledger_evidence": defects,
        "screening_signal_hypotheses": signal_hypotheses,
        "loi_to_close_changes": drift,
        "lessons": lessons,
        "screening_recommendations": recommendations,
        "honesty": {
            "classification": "HYPOTHESES_NOT_CONCLUSIONS",
            "causation_established": False,
            "limitations": (
                "Single-deal associations do not establish causation or a calibrated screening weight."
            ),
        },
    }


__all__ = ["deal_postmortem"]
