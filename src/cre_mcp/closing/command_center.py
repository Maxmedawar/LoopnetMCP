"""Closing-day command center assembled from read-only execution evidence.

The command center does not send wires, mark wires verified, sign documents, or
record instruments.  It orders the evidence and human work into one runbook.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from cre_mcp.dataroom import closing_runway as dataroom_closing_runway


HUMAN_WIRE_WARNING = (
    "human call-back verification required — wire fraud is unrecoverable"
)


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            raise ValueError("closing_date is required")
        return date.fromisoformat(candidate).isoformat()
    raise ValueError("closing_date must be an ISO date, date, or datetime")


def _funding_flags(funding_checklist: dict[str, Any] | None) -> list[Any]:
    if not funding_checklist:
        return []
    for key in ("hard_flags", "flags"):
        value = funding_checklist.get(key)
        if isinstance(value, list):
            return value
    discrepancies = funding_checklist.get("discrepancies")
    if isinstance(discrepancies, list):
        return discrepancies
    return []


def _funding_is_blocked(funding_checklist: dict[str, Any] | None) -> bool:
    if funding_checklist is None:
        return True
    if funding_checklist.get("error"):
        return True
    if funding_checklist.get("ok") is False:
        return True
    if funding_checklist.get("status") in {"blocked", "error", "not_ready"}:
        return True
    if _funding_flags(funding_checklist):
        return True
    for key in ("balanced", "sources_equal_uses", "payoffs_current", "wires_verified"):
        if funding_checklist.get(key) is False:
            return True
    if funding_checklist.get("ready_to_fund") is False:
        return True
    sources_uses = funding_checklist.get("sources_uses")
    if isinstance(sources_uses, dict) and sources_uses.get("balanced") is False:
        return True
    payoff_checks = funding_checklist.get("payoff_checks")
    if isinstance(payoff_checks, list) and any(
        check.get("valid_through_closing") is False
        or check.get("good_through_closing") is False
        for check in payoff_checks
        if isinstance(check, dict)
    ):
        return True
    wire_checks = funding_checklist.get("wire_checks")
    if isinstance(wire_checks, list) and any(
        not bool(check.get("verified_by_callback"))
        for check in wire_checks
        if isinstance(check, dict)
    ):
        return True
    wires = funding_checklist.get("wires")
    if isinstance(wires, list):
        return any(
            not bool(wire.get("verified_by_callback"))
            for wire in wires
            if isinstance(wire, dict)
        )
    return False


def _post_closing_obligations(obligations: Any) -> list[dict[str, Any]]:
    if obligations is None:
        return []
    if isinstance(obligations, list):
        return [entry for entry in obligations if isinstance(entry, dict)]
    if not isinstance(obligations, dict):
        raise ValueError("obligations must be an extraction result or a list")
    if obligations.get("error"):
        return []
    for key in ("post_closing_obligations", "post_closing"):
        entries = obligations.get(key)
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
    entries = obligations.get("obligations")
    if isinstance(entries, list):
        return [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("category") in {"post_closing", "post_closing_obligation"}
        ]
    return []


def _add_item(
    runbook: list[dict[str, Any]],
    *,
    item_id: str,
    phase: str,
    description: str,
    owner: Any,
    status: Any,
    blocking_status: str,
    blockers: list[str] | None = None,
    due_date: Any = None,
    source: Any = None,
) -> None:
    runbook.append(
        {
            "order": len(runbook) + 1,
            "item_id": item_id,
            "phase": phase,
            "description": description,
            "owner": owner,
            "status": status,
            "blocking_status": blocking_status,
            "blockers": blockers or [],
            "due_date": due_date,
            "source": source,
        }
    )


def closing_day(
    deal_id: str,
    closing_date: Any,
    funding_checklist: dict[str, Any] | None = None,
    obligations: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one ordered, human-controlled closing runbook.

    ``funding_checklist`` is expected to be the output of funding verification;
    this function never changes its wire-verification state.  ``obligations`` may
    be the contract extraction result or its post-closing list.
    """

    try:
        if not isinstance(deal_id, str) or not deal_id.strip():
            raise ValueError("deal_id is required")
        normalized_deal_id = deal_id.strip()
        normalized_closing_date = _iso_date(closing_date)
        runway = dataroom_closing_runway(normalized_deal_id)
        if not isinstance(runway, dict):
            raise ValueError("data-room closing runway returned a non-object result")
        if runway.get("error"):
            raise ValueError(str(runway["error"]))

        runbook: list[dict[str, Any]] = []
        runway_blockers: dict[str, list[str]] = {}
        for blocker in runway.get("blocking_prerequisites", []):
            if not isinstance(blocker, dict):
                continue
            blocked_key = str(blocker.get("blocked_task_key") or "")
            prerequisite = str(blocker.get("prerequisite_task_key") or "")
            if blocked_key and prerequisite:
                runway_blockers.setdefault(blocked_key, []).append(prerequisite)

        for index, task in enumerate(runway.get("tasks", []), start=1):
            if not isinstance(task, dict):
                continue
            task_key = str(task.get("task_key") or f"runway_{index}")
            task_status = task.get("status")
            blockers = runway_blockers.get(task_key, [])
            complete = task_status in {"complete", "completed", "done", "satisfied"}
            blocking_status = "complete" if complete else "blocked" if blockers else "ready"
            _add_item(
                runbook,
                item_id=f"dataroom:{task_key}",
                phase="data_room_runway",
                description=str(task.get("label") or task_key),
                owner=task.get("owner"),
                status=task_status,
                blocking_status=blocking_status,
                blockers=blockers,
                due_date=task.get("deadline"),
                source="cre_mcp.dataroom.closing_runway",
            )

        funding_blocked = _funding_is_blocked(funding_checklist)
        funding_flags = _funding_flags(funding_checklist)
        funding_blockers = [
            str(flag.get("message") or flag.get("reason") or flag)
            if isinstance(flag, dict)
            else str(flag)
            for flag in funding_flags
        ]
        if funding_checklist is None:
            funding_blockers.append("funding checklist not supplied")
        _add_item(
            runbook,
            item_id="funding:verification_checklist",
            phase="funding",
            description="Human review of sources, uses, payoff dates, and wire call-backs",
            owner="closing_team",
            status=None if funding_checklist is None else funding_checklist.get("status"),
            blocking_status="blocked" if funding_blocked else "ready",
            blockers=funding_blockers,
            due_date=normalized_closing_date,
            source="verify_funding_package output",
        )

        runway_blocking_items = [
            item["item_id"]
            for item in runbook
            if item["blocking_status"] == "blocked"
        ]
        execution_blockers = list(runway_blocking_items)
        if funding_blocked:
            execution_blockers.append("funding:verification_checklist")
        fixed_sequence = (
            (
                "execution:signatures",
                "signature",
                "Authorized humans execute the final closing documents",
                "authorized_signatories",
                execution_blockers,
            ),
            (
                "execution:notary",
                "notary",
                "Notary acknowledges the executed recordable instruments",
                "notary",
                ["execution:signatures"],
            ),
            (
                "execution:recording",
                "recording",
                "Human closing team authorizes submission of recordable instruments",
                "title_or_escrow",
                ["execution:notary", "funding:verification_checklist"],
            ),
        )
        for item_id, phase, description, owner, blockers in fixed_sequence:
            _add_item(
                runbook,
                item_id=item_id,
                phase=phase,
                description=description,
                owner=owner,
                status="pending_human_action",
                blocking_status="blocked" if blockers else "ready",
                blockers=blockers,
                due_date=normalized_closing_date,
                source="closing sequence convention",
            )

        post_close = _post_closing_obligations(obligations)
        for index, obligation in enumerate(post_close, start=1):
            deadline = obligation.get("deadline_rule")
            _add_item(
                runbook,
                item_id=f"post_close:obligation_{index}",
                phase="post_closing",
                description=str(
                    obligation.get("summary")
                    or obligation.get("obligation")
                    or obligation.get("quote")
                    or f"Post-closing obligation {index}"
                ),
                owner=obligation.get("party"),
                status="calendar_required" if deadline else "deadline_unknown",
                blocking_status="not_blocking_closing",
                due_date=deadline,
                source={
                    "quote": obligation.get("quote"),
                    "locator": obligation.get("locator"),
                },
            )
            runbook[-1]["deadline_rule"] = deadline
            runbook[-1]["survival"] = obligation.get("survival")

        return {
            "deal_id": normalized_deal_id,
            "closing_date": normalized_closing_date,
            "runway": runway,
            "funding_checklist": funding_checklist,
            "post_closing_obligation_calendar": post_close,
            "runbook": runbook,
            "blocking_items": [
                item["item_id"] for item in runbook if item["blocking_status"] == "blocked"
            ],
            "wire_control": HUMAN_WIRE_WARNING,
            "authority": (
                "The tool prepares a verification checklist only. A human independently "
                "calls a trusted number and authorizes every wire, signature, and recording."
            ),
            "sequence_convention": "data-room runway, funding review, signature, notary, recording, post-close",
        }
    except Exception as exc:
        return {"error": str(exc)}


__all__ = ["closing_day"]
