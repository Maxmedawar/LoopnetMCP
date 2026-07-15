"""Deterministic note/mortgage assignment and endorsement continuity screen."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any


DOCUMENT_KINDS = frozenset({"note", "mortgage", "assignment", "allonge", "guaranty"})
CURATIVE_WORK_FLAG = "curative work needed — counsel"
COUNSEL_FLAG = (
    "Curative work needed — counsel and the title/custody parties must review originals, "
    "endorsements, assignments, recordation, authority, and applicable law."
)
_DOCUMENT_FIELDS = frozenset(
    {"kind", "from_party", "to_party", "date", "recorded"}
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    return normalized or None


def _party_key(value: str | None) -> str | None:
    return value.casefold() if value is not None else None


def _day(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO date or null") from exc
    raise ValueError(f"{label} must be an ISO date or null")


def _recorded(value: Any, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true, false, or null")
    return value


def _normalize_documents(
    docs: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    recognized: list[dict[str, Any]] = []
    unrecognized_documents: list[dict[str, Any]] = []
    unrecognized_inputs: list[str] = []
    for index, document in enumerate(docs):
        if not isinstance(document, Mapping):
            raise ValueError(f"docs[{index}] must be an object")
        raw_kind = _text(document.get("kind"))
        kind = raw_kind.casefold() if raw_kind is not None else None
        unknown_fields = sorted(set(document).difference(_DOCUMENT_FIELDS))
        unrecognized_inputs.extend(f"docs[{index}].{field}" for field in unknown_fields)
        if kind not in DOCUMENT_KINDS:
            reason = (
                "kind is missing"
                if kind is None
                else f"kind {raw_kind!r} is outside the note-chain vocabulary"
            )
            unrecognized_documents.append(
                {
                    "document_index": index,
                    "kind": raw_kind,
                    "reason": reason,
                    "document": dict(document),
                }
            )
            unrecognized_inputs.append(f"docs[{index}].kind: {reason}")
            continue
        recognized.append(
            {
                "document_index": index,
                "kind": kind,
                "from_party": _text(document.get("from_party")),
                "to_party": _text(document.get("to_party")),
                "date": _day(document.get("date"), f"docs[{index}].date"),
                "recorded": _recorded(
                    document.get("recorded"), f"docs[{index}].recorded"
                ),
            }
        )
    return recognized, unrecognized_documents, sorted(set(unrecognized_inputs))


def _ordered(rows: Sequence[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return sorted(
        (row for row in rows if row["kind"] == kind),
        key=lambda row: (
            row["date"] is None,
            row["date"] or "9999-12-31",
            row["document_index"],
        ),
    )


def _break(
    break_type: str,
    document: Mapping[str, Any] | None,
    message: str,
    *,
    expected: str | None = None,
    actual: str | None = None,
) -> dict[str, Any]:
    return {
        "type": break_type,
        "document_index": (
            document.get("document_index") if document is not None else None
        ),
        "date": document.get("date") if document is not None else None,
        "expected": expected,
        "actual": actual,
        "expected_from_party": expected,
        "actual_from_party": actual,
        "message": message,
        "action": CURATIVE_WORK_FLAG,
    }


def _opening_holder(
    notes: Sequence[dict[str, Any]], mortgages: Sequence[dict[str, Any]]
) -> tuple[str | None, list[dict[str, Any]]]:
    note_holder = notes[0]["to_party"] if notes else None
    mortgage_holder = mortgages[0]["to_party"] if mortgages else None
    breaks: list[dict[str, Any]] = []
    if (
        note_holder is not None
        and mortgage_holder is not None
        and _party_key(note_holder) != _party_key(mortgage_holder)
    ):
        breaks.append(
            _break(
                "opening_holder_mismatch",
                mortgages[0],
                "The original note payee and mortgagee supplied do not match exactly.",
                expected=note_holder,
                actual=mortgage_holder,
            )
        )
    return note_holder or mortgage_holder, breaks


def _assignment_walk(
    assignments: Sequence[dict[str, Any]],
    opening_holder: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    current_holder = opening_holder
    chain: list[dict[str, Any]] = []
    breaks: list[dict[str, Any]] = []
    for assignment in assignments:
        assignor = assignment["from_party"]
        assignee = assignment["to_party"]
        expected = current_holder
        link_valid: bool | None
        if assignor is None or assignee is None:
            link_valid = False
            missing = [
                field
                for field, value in (("from_party", assignor), ("to_party", assignee))
                if value is None
            ]
            breaks.append(
                _break(
                    "assignment_party_missing",
                    assignment,
                    f"Assignment is missing {', '.join(missing)} and cannot establish a complete link.",
                    expected=expected,
                    actual=assignor,
                )
            )
        elif expected is None:
            link_valid = None
        elif _party_key(assignor) != _party_key(expected):
            link_valid = False
            breaks.append(
                _break(
                    "assignment_chain_break",
                    assignment,
                    f"Assignment chain break: expected assignor {expected!r}, received {assignor!r}.",
                    expected=expected,
                    actual=assignor,
                )
            )
        else:
            link_valid = True
        if assignment["recorded"] is False:
            breaks.append(
                _break(
                    "assignment_not_recorded",
                    assignment,
                    "Assignment is explicitly marked unrecorded.",
                )
            )
        elif assignment["recorded"] is None:
            breaks.append(
                _break(
                    "assignment_recording_unknown",
                    assignment,
                    "Assignment recordation status is not supplied.",
                )
            )
        chain.append(
            {
                **assignment,
                "expected_from_party": expected,
                "link_valid": link_valid,
                "link": f"{assignor} -> {assignee}",
            }
        )
        if assignee is not None:
            current_holder = assignee
    return chain, breaks, current_holder


def _endorsement_walk(
    allonges: Sequence[dict[str, Any]],
    note_holder: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    current_holder = note_holder
    chain: list[dict[str, Any]] = []
    breaks: list[dict[str, Any]] = []
    if allonges and current_holder is None:
        breaks.append(
            _break(
                "opening_note_holder_unknown",
                allonges[0],
                "No original note payee was supplied to anchor the first allonge.",
                actual=allonges[0]["from_party"],
            )
        )
    for allonge in allonges:
        endorser = allonge["from_party"]
        endorsee = allonge["to_party"]
        expected = current_holder
        continuity: bool | None
        if endorser is None or endorsee is None:
            continuity = False
            breaks.append(
                _break(
                    "allonge_party_missing",
                    allonge,
                    "Allonge is missing an endorser or endorsee and cannot establish endorsement continuity.",
                    expected=expected,
                    actual=endorser,
                )
            )
        elif expected is None:
            continuity = None
        elif _party_key(endorser) != _party_key(expected):
            continuity = False
            breaks.append(
                _break(
                    "endorsement_chain_break",
                    allonge,
                    f"Endorsement chain break: expected endorser {expected!r}, received {endorser!r}.",
                    expected=expected,
                    actual=endorser,
                )
            )
        else:
            continuity = True
        chain.append(
            {
                **allonge,
                "expected_from_party": expected,
                "continuity": continuity,
                "link": f"{endorser} -> {endorsee}",
            }
        )
        if endorsee is not None:
            current_holder = endorsee
    return chain, breaks, current_holder


def reconcile_note_chain(
    docs: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Walk supplied assignments/allonges and flag every exact continuity gap.

    Party matching is case-insensitive and whitespace-normalized, but no legal-name
    equivalence, merger, agency, blank endorsement, or corrective instrument is
    inferred.
    """

    if isinstance(docs, (str, bytes, bytearray)) or not isinstance(docs, Sequence):
        raise ValueError("docs must be a list of document objects")
    recognized, unrecognized_documents, unrecognized_inputs = _normalize_documents(docs)
    notes = _ordered(recognized, "note")
    mortgages = _ordered(recognized, "mortgage")
    assignments = _ordered(recognized, "assignment")
    allonges = _ordered(recognized, "allonge")
    guaranties = _ordered(recognized, "guaranty")

    opening_holder, opening_breaks = _opening_holder(notes, mortgages)
    assignment_chain, assignment_breaks, mortgage_chain_holder = _assignment_walk(
        assignments, opening_holder
    )
    note_holder = notes[0]["to_party"] if notes else None
    endorsement_chain, endorsement_breaks, endorsed_note_holder = _endorsement_walk(
        allonges, note_holder
    )
    holder_breaks: list[dict[str, Any]] = []
    if (
        assignments
        and mortgage_chain_holder is not None
        and endorsed_note_holder is not None
        and _party_key(mortgage_chain_holder) != _party_key(endorsed_note_holder)
    ):
        holder_breaks.append(
            _break(
                "note_mortgage_holder_divergence",
                assignments[-1],
                "The supplied mortgage-assignment chain and note-endorsement chain end with different holders.",
                expected=mortgage_chain_holder,
                actual=endorsed_note_holder,
            )
        )
    breaks = opening_breaks + assignment_breaks + endorsement_breaks + holder_breaks
    recording_gaps = [
        item for item in breaks if "record" in str(item["type"])
    ]
    endorsement_continuity = {
        "opening_note_holder": note_holder,
        "current_endorsed_note_holder": endorsed_note_holder,
        "chain": endorsement_chain,
        "breaks": endorsement_breaks + holder_breaks,
        "continuous": not (endorsement_breaks or holder_breaks),
    }
    limitations: list[dict[str, Any]] = []
    if assignments and opening_holder is None:
        limitations.append(
            {
                "type": "opening_holder_not_supplied",
                "message": (
                    "No original note payee or mortgagee party was supplied; the first "
                    "complete assignment establishes the working assignor for this screen only."
                ),
                "impact": "The opening link is unverified, but absence alone is not treated as a contradictory chain break.",
            }
        )
    if assignments and note_holder is None:
        limitations.append(
            {
                "type": "note_holder_not_supplied",
                "message": "The supplied note does not identify a payee/current endorsed holder.",
                "impact": "Mortgage-assignment continuity can be walked, but note-endorsement ownership is not established.",
            }
        )
    needs_curative_work = bool(breaks or unrecognized_documents)
    return {
        "status": (
            "curative_review_required"
            if needs_curative_work
            else "continuous_on_supplied_documents"
        ),
        "documents": recognized,
        "chain": assignment_chain,
        "assignment_chain": assignment_chain,
        "opening_holder": opening_holder,
        "current_assignment_holder": mortgage_chain_holder,
        "breaks": breaks,
        "gaps": breaks,
        "recording_gaps": recording_gaps,
        "endorsement_continuity": endorsement_continuity,
        "guaranties": guaranties,
        "chain_complete": not needs_curative_work,
        "curative_work_needed": needs_curative_work,
        "curative_work_flag": CURATIVE_WORK_FLAG if needs_curative_work else None,
        "counsel_flag": COUNSEL_FLAG if needs_curative_work else None,
        "warnings": limitations,
        "limitations": limitations,
        "unrecognized_documents": unrecognized_documents,
        "unrecognized_inputs": unrecognized_inputs,
        "matching_convention": (
            "Party links compare case-insensitively after whitespace normalization only; "
            "dates sort ascending with undated documents last and input order as the tie-breaker."
        ),
        "scope_note": (
            "Supplied-document inventory screen only. Absence of a flagged break does not prove "
            "ownership, possession of originals, enforceability, authority, priority, or complete public records."
        ),
    }


__all__ = [
    "COUNSEL_FLAG",
    "CURATIVE_WORK_FLAG",
    "DOCUMENT_KINDS",
    "reconcile_note_chain",
]
