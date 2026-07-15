"""Conservative encumbrance screening for a contemplated closing.

This module reports issues and workflow dependencies.  Its blocking and
priority labels are disclosed screening conventions, not conclusions about
attachment, validity, priority, insurability, payoff sufficiency, or whether an
encumbrance legally survives closing.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from cre_mcp.truth.sanitize import sanitize_text


_ALLOWED_TYPES = {
    "mortgage",
    "judgment",
    "tax_lien",
    "ucc",
    "mechanics",
    "hoa",
    "lis_pendens",
}

_POSTURE = (
    "ISSUE LIST ONLY — no finding is a legal conclusion about validity, attachment, "
    "priority, marketability, or policy coverage. Title company and counsel review "
    "are required before closing."
)

_PRIORITY_NOTES = {
    "mortgage": (
        "Priority convention: recording date is a review cue only; recording order, "
        "subordination, modifications, future advances, and governing law can change the result."
    ),
    "judgment": (
        "Priority convention: treat an unresolved judgment as a potential title impediment; "
        "attachment to this owner/property, exemptions, duration, and priority are jurisdiction-specific."
    ),
    "tax_lien": (
        "Priority convention: treat an unresolved tax lien as a potential senior or closing "
        "impediment; taxing authority, assessment period, notice, redemption, and governing law control."
    ),
    "ucc": (
        "Priority convention: a UCC filing does not by itself establish a real-property lien; "
        "counsel/title company must confirm debtor, collateral, fixtures, amendments, and termination."
    ),
    "mechanics": (
        "Priority convention: treat an unresolved mechanics lien as a closing impediment; "
        "relation-back, notice, filing deadline, waiver, and priority rules are jurisdiction-specific."
    ),
    "hoa": (
        "Priority convention: treat an unresolved HOA lien as a closing impediment; lien scope, "
        "super-priority amount, notice, and payoff requirements are jurisdiction-specific."
    ),
    "lis_pendens": (
        "Priority convention: lis pendens is routed as STOP because it signals pending property-related "
        "litigation; it does not establish the merits, and counsel/title company must confirm status and effect."
    ),
}


def _plain_number(value: Any, label: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative number or null")
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        if not cleaned:
            return None
        try:
            number = float(cleaned)
        except ValueError as exc:
            raise ValueError(f"{label} must be a non-negative number or null") from exc
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        raise ValueError(f"{label} must be a non-negative number or null")
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a non-negative finite number or null")
    return int(number) if number.is_integer() else number


def _recorded_date(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty date label or null")
    # Dates are retained as evidence labels.  Parsing a locale-specific recorder
    # date could falsely imply a chronology, so no date-order conclusion is made.
    return value.strip()


def _key(value: Any) -> str:
    sanitized = sanitize_text(str(value or "")).text
    return "".join(character for character in sanitized.casefold() if character.isalnum())


def _payoff_entries(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("closing_context.payoffs_arranged must be a list")
    entries: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if isinstance(raw, str):
            sanitized_holder = sanitize_text(raw)
            if not sanitized_holder.text.strip():
                raise ValueError(f"payoffs_arranged[{index}] cannot be blank")
            entries.append(
                {
                    "index": index,
                    "holder_key": _key(sanitized_holder.text),
                    "holder": sanitized_holder.text.strip(),
                    "type": None,
                    "record_index": None,
                    "arranged": True,
                    "redactions": sanitized_holder.redactions,
                }
            )
            continue
        if not isinstance(raw, Mapping):
            raise ValueError(f"payoffs_arranged[{index}] must be a holder string or object")
        arranged = raw.get("arranged", True)
        if not isinstance(arranged, bool):
            raise ValueError(f"payoffs_arranged[{index}].arranged must be boolean")
        raw_holder = raw.get("holder")
        sanitized_holder = sanitize_text(str(raw_holder)) if raw_holder is not None else sanitize_text("")
        holder_key = _key(sanitized_holder.text)
        record_index = raw.get("record_index")
        if record_index is not None and (isinstance(record_index, bool) or not isinstance(record_index, int)):
            raise ValueError(f"payoffs_arranged[{index}].record_index must be an integer or null")
        type_value = raw.get("type")
        normalized_type = str(type_value).strip().casefold().replace(" ", "_").replace("-", "_") if type_value is not None else None
        if normalized_type is not None and normalized_type not in _ALLOWED_TYPES:
            raise ValueError(f"payoffs_arranged[{index}].type is not a supported record type")
        if not holder_key and record_index is None:
            raise ValueError(f"payoffs_arranged[{index}] needs holder or record_index")
        entries.append(
            {
                "index": index,
                "holder_key": holder_key,
                "holder": sanitized_holder.text.strip() or None,
                "type": normalized_type,
                "record_index": record_index,
                "arranged": arranged,
                "redactions": sanitized_holder.redactions,
            }
        )
    return entries


def _payoff_match(entries: list[dict[str, Any]], record_index: int, record_type: str, holder: str) -> tuple[bool, str | None, int | None]:
    holder_key = _key(holder)
    for entry in entries:
        if not entry["arranged"]:
            continue
        if entry["record_index"] is not None:
            if entry["record_index"] == record_index and entry["type"] in (None, record_type):
                return True, "exact record_index/type match", entry["index"]
            continue
        if entry["holder_key"] == holder_key and entry["type"] in (None, record_type):
            return True, "exact normalized holder/type match", entry["index"]
    return False, None, None


def _status_group(status: str | None) -> str:
    if status is None:
        return "release_not_evidenced"
    lowered = " ".join(status.casefold().replace("_", " ").replace("-", " ").split())
    if re.search(r"\b(?:unreleased|unsatisfied|unterminated|not\s+released|not\s+satisfied|not\s+terminated|open|active|outstanding|pending|recorded|disputed)\b", lowered):
        return "unresolved"
    if re.search(r"\b(?:released|satisfied|terminated|dismissed|discharged|cancelled|canceled|paid|expunged)\b", lowered):
        return "cleared_status_reported"
    if re.search(r"\b(?:assumed|permitted|subordinated|ride\s+through|remain)\b", lowered):
        return "ride_through_reported"
    if re.search(r"\bpayoff\s+(?:arranged|ordered|approved)\b", lowered):
        return "payoff_reported_in_status_only"
    return "unresolved_status_unclear"


def _guidance(
    record_type: str,
    status_group: str,
    payoff_arranged: bool,
    blocks: bool | None,
) -> str:
    if status_group == "cleared_status_reported":
        return (
            "Give the release/satisfaction/dismissal evidence to the title company and ask it "
            "to confirm record status and final-policy treatment; the supplied status alone is not proof."
        )
    if status_group == "ride_through_reported":
        return (
            "Ask counsel and the title company to confirm the documented assumption, permission, "
            "or subordination and its final-policy treatment before allowing the item to remain."
        )
    if record_type == "lis_pendens":
        return (
            "STOP under the disclosed screening convention. Obtain the pleadings and recorded notice, "
            "and require counsel/title company direction plus recordable release, dismissal, or approved coverage."
        )
    if payoff_arranged:
        return (
            "Closing dependency: verify a current payoff/termination letter, recipient and wire controls, "
            "sufficient proceeds, release/recording instructions, and marked-commitment deletion with the title company."
        )
    if record_type == "ucc":
        return (
            "Ask counsel/title company to match debtor and collateral and determine whether a fixture filing, "
            "termination, payoff, subordination, or no real-property action is required."
        )
    if blocks is True:
        return (
            "Obtain the underlying instrument and title-company-approved payoff, release, satisfaction, "
            "or other written clearance; counsel must confirm the proposed path."
        )
    return "Ask the title company and counsel to identify the record's effect and required closing response."


def _classification(record_type: str, status_group: str, payoff_arranged: bool) -> tuple[bool | None, bool | None, str, str, bool]:
    """Return blocks, rides, disposition, severity, closing_dependency."""

    if status_group == "cleared_status_reported":
        return False, False, "reported_cleared_verify", "review", False
    if status_group == "ride_through_reported":
        return False, True, "reported_ride_through_verify", "high", True
    if record_type == "lis_pendens":
        return True, False, "stop_litigation_notice", "fatal", True
    if payoff_arranged:
        return False, False, "payoff_at_closing_dependency", "high", True
    if record_type == "ucc":
        return None, None, "effect_unknown_counsel_review", "review", True
    # For these record classes the engine intentionally uses a conservative
    # transaction-screening convention until title company evidence says otherwise.
    return True, False, "unresolved_closing_impediment_convention", "high", True


def _screen(records: Any, closing_context: Any) -> dict[str, Any]:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise ValueError("records must be a list of encumbrance objects")
    if not isinstance(closing_context, Mapping):
        raise ValueError("closing_context must be an object")

    price = _plain_number(closing_context.get("price"), "closing_context.price")
    payoff_entries = _payoff_entries(closing_context.get("payoffs_arranged"))
    findings: list[dict[str, Any]] = []
    matched_payoff_indexes: set[int] = set()
    sanitization_redactions = sum(entry["redactions"] for entry in payoff_entries)

    for index, raw in enumerate(records):
        if not isinstance(raw, Mapping):
            raise ValueError(f"records[{index}] must be an object")
        normalized_type = str(raw.get("type") or "").strip().casefold().replace(" ", "_").replace("-", "_")
        if normalized_type not in _ALLOWED_TYPES:
            allowed = ", ".join(sorted(_ALLOWED_TYPES))
            raise ValueError(f"records[{index}].type must be one of: {allowed}")
        holder_raw = raw.get("holder")
        if not isinstance(holder_raw, str) or not holder_raw.strip():
            raise ValueError(f"records[{index}].holder must be a non-empty string")
        if "recorded_date" not in raw:
            raise ValueError(f"records[{index}].recorded_date is required (use null if unknown)")
        sanitized_holder = sanitize_text(holder_raw)
        holder = sanitized_holder.text.strip()
        if not holder:
            raise ValueError(f"records[{index}].holder is empty after sanitization")
        amount = _plain_number(raw.get("amount"), f"records[{index}].amount")
        raw_recorded_date = raw.get("recorded_date")
        sanitized_date_redactions = 0
        if isinstance(raw_recorded_date, str):
            sanitized_date = sanitize_text(raw_recorded_date)
            raw_recorded_date = sanitized_date.text
            sanitized_date_redactions = sanitized_date.redactions
        recorded_date = _recorded_date(raw_recorded_date, f"records[{index}].recorded_date")
        status_value = raw.get("status")
        if status_value is not None and (not isinstance(status_value, str) or not status_value.strip()):
            raise ValueError(f"records[{index}].status must be a non-empty string or null")
        sanitized_status = sanitize_text(status_value) if isinstance(status_value, str) else sanitize_text("")
        status = sanitized_status.text.strip() if isinstance(status_value, str) else None
        sanitization_redactions += (
            sanitized_holder.redactions + sanitized_date_redactions + sanitized_status.redactions
        )
        status_group = _status_group(status)
        payoff_arranged, payoff_match_basis, payoff_index = _payoff_match(
            payoff_entries, index, normalized_type, holder
        )
        if payoff_index is not None:
            matched_payoff_indexes.add(payoff_index)
        blocks, rides, disposition, severity, closing_dependency = _classification(
            normalized_type, status_group, payoff_arranged
        )
        ratio = None
        if amount is not None and price not in (None, 0):
            ratio = round(float(amount) / float(price) * 100, 4)

        evidence_quote = (
            f"type={normalized_type}; holder={holder}; amount={amount if amount is not None else 'unknown'}; "
            f"recorded_date={recorded_date if recorded_date is not None else 'unknown'}; "
            f"status={status if status is not None else 'unknown'}"
        )[:200]
        finding = {
            "record_index": index,
            "type": normalized_type,
            "holder": holder,
            "amount": amount,
            "recorded_date": recorded_date,
            "status": status,
            "status_screen": status_group,
            "payoff_arranged": payoff_arranged,
            "payoff_match_basis": payoff_match_basis,
            "amount_to_price_pct": ratio,
            "blocks_closing": blocks,
            "ride_through": rides,
            "disposition": disposition,
            "severity": severity,
            "closing_dependency": closing_dependency,
            "priority_note": _PRIORITY_NOTES[normalized_type],
            "what_to_ask": _guidance(normalized_type, status_group, payoff_arranged, blocks),
            "who": ["title company", "counsel"],
            "classification_is_screening_convention": True,
            "counsel_review_required": True,
            "quote": evidence_quote,
            "locator": f"records[{index}]",
        }
        findings.append(finding)

    blocking = [finding for finding in findings if finding["blocks_closing"] is True]
    ride_through = [finding for finding in findings if finding["ride_through"] is True]
    cleared = [finding for finding in findings if finding["disposition"] == "reported_cleared_verify"]
    indeterminate = [finding for finding in findings if finding["blocks_closing"] is None]
    payoff_gaps = [
        {
            "record_index": finding["record_index"],
            "type": finding["type"],
            "holder": finding["holder"],
            "amount": finding["amount"],
            "gap": "No exact payoff arrangement was supplied for an unresolved monetary encumbrance.",
            "who": ["title company", "seller/current owner", "counsel"],
            "what_to_ask": finding["what_to_ask"],
            "severity": finding["severity"],
            "quote": finding["quote"],
            "locator": finding["locator"],
        }
        for finding in findings
        if finding["type"] in {"mortgage", "judgment", "tax_lien", "mechanics", "hoa"}
        and finding["status_screen"] not in {"cleared_status_reported", "ride_through_reported"}
        and not finding["payoff_arranged"]
    ]
    resolution_gaps = [
        {
            "record_index": finding["record_index"],
            "type": finding["type"],
            "holder": finding["holder"],
            "blocks_closing": finding["blocks_closing"],
            "what_to_ask": finding["what_to_ask"],
            "quote": finding["quote"],
            "locator": finding["locator"],
        }
        for finding in findings
        if finding["closing_dependency"]
    ]
    unmatched_payoffs = [
        {
            "payoff_index": entry["index"],
            "gap": "Payoff arrangement did not exactly match a supplied record by record index or normalized holder/type.",
            "quote": (
                f"holder={entry['holder'] or 'unknown'}; type={entry['type'] or 'unknown'}; "
                f"record_index={entry['record_index'] if entry['record_index'] is not None else 'unknown'}; "
                f"arranged={entry['arranged']}"
            )[:200],
            "locator": f"closing_context.payoffs_arranged[{entry['index']}]",
        }
        for entry in payoff_entries
        if entry["arranged"] and entry["index"] not in matched_payoff_indexes
    ]

    if not findings:
        closing_status = "REVIEW_REQUIRED"
    elif any(finding["type"] == "lis_pendens" for finding in blocking):
        closing_status = "STOP"
    elif blocking:
        closing_status = "BLOCKED_BY_SCREENING_CONVENTION"
    elif indeterminate:
        closing_status = "REVIEW_REQUIRED"
    elif any(finding["disposition"] == "payoff_at_closing_dependency" for finding in findings):
        closing_status = "CONDITIONAL_ON_DOCUMENTED_RELEASES"
    else:
        closing_status = "NO_BLOCKER_IDENTIFIED"

    missing_inputs: list[str] = []
    if not findings:
        missing_inputs.append("records")
    if price is None:
        missing_inputs.append("closing_context.price")
    if "payoffs_arranged" not in closing_context:
        missing_inputs.append("closing_context.payoffs_arranged")

    return {
        "closing_status": closing_status,
        "closing_price": price,
        "findings": findings,
        "blocking": blocking,
        "blocking_records": blocking,
        "ride_through": ride_through,
        "cleared_status_reported": cleared,
        "indeterminate_effect": indeterminate,
        "payoff_arrangement_gaps": payoff_gaps,
        "resolution_gaps": resolution_gaps,
        "unmatched_payoff_arrangements": unmatched_payoffs,
        "missing_inputs": missing_inputs,
        "input_gaps": [
            {
                "field": field,
                "severity": "review",
                "what_to_ask": "Supply the missing closing/title input; silence is not evidence of clear title.",
                "quote": None,
                "locator": field,
            }
            for field in missing_inputs
        ],
        "priority_notes": [
            {
                "record_index": finding["record_index"],
                "type": finding["type"],
                "note": finding["priority_note"],
                "is_convention": True,
                "quote": finding["quote"],
                "locator": finding["locator"],
            }
            for finding in findings
        ],
        "conventions": {
            "blocking": (
                "An unresolved mortgage, judgment, tax lien, mechanics lien, or HOA lien is "
                "screened as blocking unless exact payoff evidence is supplied; active lis pendens is STOP."
            ),
            "payoff_matching": (
                "Payoffs match only by exact record index/type or normalized holder/type. A match "
                "shows an arrangement was supplied, not that the payoff or release is sufficient."
            ),
            "ucc": (
                "UCC closing effect remains null until collateral, debtor, fixture status, and "
                "title treatment are reviewed."
            ),
            "status": (
                "A supplied cleared or ride-through status is routed for verification and is not "
                "accepted as proof of release, permission, priority, or policy coverage."
            ),
        },
        "title_company_review_required": True,
        "counsel_review_required": True,
        "sanitization_redactions": sanitization_redactions,
        "honesty": _POSTURE,
    }


def screen_encumbrances(records: list[dict[str, Any]], closing_context: dict[str, Any]) -> dict[str, Any]:
    """Screen lien/encumbrance records and expose closing-workflow gaps.

    All validation and unexpected exceptions are contained at this public
    boundary as ``{"error": ...}``.
    """

    try:
        return _screen(records, closing_context)
    except Exception as exc:  # boundary containment is intentional
        return {"error": str(exc)}


__all__ = ["screen_encumbrances"]
