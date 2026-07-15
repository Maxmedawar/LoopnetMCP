"""Human-controlled funding-package verification in integer cents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any


WIRE_HARD_FLAG = "human call-back verification required — wire fraud is unrecoverable"


def _cents(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _date(value: Any, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD)") from exc
    raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD)")


def _rows(value: Any, name: str) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be a list")
    result = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping):
            raise ValueError(f"{name}[{index}] must be an object")
        result.append(row)
    return result


def _funding_lines(value: Any, name: str) -> tuple[list[dict[str, Any]], int]:
    lines = []
    total = 0
    for index, row in enumerate(_rows(value, name)):
        amount = _cents(row.get("amount_cents"), f"{name}[{index}].amount_cents")
        label = row.get("name", row.get("description", row.get("source", row.get("use"))))
        lines.append({
            "line_id": str(row.get("line_id", row.get("id", f"{name}:{index + 1}"))),
            "name": str(label).strip() if label not in (None, "") else None,
            "amount_cents": amount,
        })
        total += amount
    return lines, total


def verify_funding_package(
    sources_uses: Mapping[str, Any],
    payoff_letters: Sequence[Mapping[str, Any]],
    wires: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Verify package arithmetic and prepare, but never perform, wire controls."""

    try:
        if not isinstance(sources_uses, Mapping):
            raise ValueError("sources_uses must be an object")
        closing_raw = sources_uses.get("closing_date")
        if closing_raw is None:
            raise ValueError("sources_uses.closing_date is required")
        closing = _date(closing_raw, "sources_uses.closing_date")
        sources, sources_total = _funding_lines(sources_uses.get("sources"), "sources")
        uses, uses_total = _funding_lines(sources_uses.get("uses"), "uses")
        funding_delta = sources_total - uses_total

        hard_flags: list[str] = []
        payoff_checks = []
        for index, letter in enumerate(_rows(payoff_letters, "payoff_letters")):
            amount = _cents(letter.get("amount_cents"), f"payoff_letters[{index}].amount_cents")
            good_raw = letter.get("good_through")
            good_through = _date(good_raw, f"payoff_letters[{index}].good_through") if good_raw is not None else None
            valid = good_through is not None and good_through >= closing
            reason = None
            if good_through is None:
                reason = "payoff good_through date is missing"
            elif not valid:
                reason = f"payoff expired {good_through.isoformat()} before closing {closing.isoformat()}"
            check = {
                "holder": str(letter["holder"]).strip() if letter.get("holder") not in (None, "") else None,
                "amount_cents": amount,
                "good_through": good_through.isoformat() if good_through is not None else None,
                "closing_date": closing.isoformat(),
                "valid_through_closing": valid,
                "blocking": not valid,
                "reason": reason,
            }
            payoff_checks.append(check)
            if not valid:
                hard_flags.append(f"payoff letter {index + 1}: {reason}")

        wire_checks = []
        for index, wire in enumerate(_rows(wires, "wires")):
            amount = _cents(wire.get("amount_cents"), f"wires[{index}].amount_cents")
            verified = wire.get("verified_by_callback")
            if not isinstance(verified, bool):
                verified = False
            flag = None if verified else WIRE_HARD_FLAG
            check = {
                "wire_index": index,
                "recipient": str(wire["recipient"]).strip() if wire.get("recipient") not in (None, "") else None,
                "bank": str(wire["bank"]).strip() if wire.get("bank") not in (None, "") else None,
                "account_last4": str(wire["account_last4"]).strip() if wire.get("account_last4") not in (None, "") else None,
                "amount_cents": amount,
                "instruction_source": str(wire["instruction_source"]).strip() if wire.get("instruction_source") not in (None, "") else None,
                "verified_by_callback": verified,
                "blocking": not verified,
                "hard_flag": flag,
                "control_owner": "human",
                "action": "Human independently calls a trusted, previously established number and records verification." if not verified else None,
            }
            wire_checks.append(check)
            if flag is not None:
                hard_flags.append(flag)

        if funding_delta != 0:
            hard_flags.append(
                f"sources and uses do not balance: {sources_total} - {uses_total} = {funding_delta} cents"
            )
        ready = funding_delta == 0 and all(not row["blocking"] for row in payoff_checks + wire_checks)
        return {
            "ok": ready,
            "status": "checklist_clear_for_human_authorization" if ready else "blocked",
            "closing_date": closing.isoformat(),
            "balanced": funding_delta == 0,
            "sources_total_cents": sources_total,
            "uses_total_cents": uses_total,
            "delta_cents": funding_delta,
            "sources_uses": {
                "sources": sources,
                "uses": uses,
                "sources_total_cents": sources_total,
                "uses_total_cents": uses_total,
                "delta_cents": funding_delta,
                "delta_direction": "sources_total_cents - uses_total_cents",
                "balanced": funding_delta == 0,
                "arithmetic": f"{sources_total} source cents - {uses_total} use cents = {funding_delta} cents",
            },
            "payoff_checks": payoff_checks,
            "wire_checks": wire_checks,
            "hard_flags": hard_flags,
            "authority": "This tool prepares a checklist only. A human performs call-back verification and authorizes any wire.",
        }
    except Exception as exc:
        return {"error": str(exc)}


__all__ = ["WIRE_HARD_FLAG", "verify_funding_package"]
