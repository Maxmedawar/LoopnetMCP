"""Factual, cited lease-obligation notice drafts that never transmit."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any


NOTICE_TYPES = frozenset(
    {"default", "cure", "option_exercise", "rent_step", "estoppel_request"}
)
COUNSEL_ROUTING = "legal wording must be approved by counsel before sending"

_FACT_KEYS = frozenset(
    {
        "cited_clause", "clause", "clause_quote", "clause_locator", "citation",
        "lease_date", "tenant", "landlord", "recipient", "sender", "property",
        "premises", "notice_date", "event_date", "trigger_date", "effective_date",
        "deadline", "deadline_days", "cure_days", "notice_days", "amount_cents",
        "rent_amount_cents", "default_amount_cents", "option_expiration",
        "rent_step_date", "facts", "dates", "amounts", "parties",
    }
)
_PARAM_KEYS = frozenset(
    {
        "notice_date", "event_date", "trigger_date", "effective_date", "deadline",
        "deadline_days", "cure_days", "notice_days", "amount_cents",
        "rent_amount_cents", "new_rent_cents", "default_amount_cents",
        "option_expiration", "rent_step_date", "recipient", "sender", "property",
        "premises", "description", "breach_description", "request_details",
        "option_type", "delivery_method", "response_due_date", "facts", "dates",
        "amounts", "parties",
    }
)
_CLAUSE_KEYS = frozenset(
    {
        "quote", "clause_quote", "locator", "page", "cell", "doc_ref", "source",
        "deadline_days", "cure_days", "notice_days", "days", "days_before",
        "notice_days_before", "day_basis", "deadline_basis",
    }
)
_NESTED_KEYS = {
    "facts": frozenset({"description", "breach_description", "request_details", "option_type"}),
    "dates": frozenset(
        {"notice_date", "event_date", "trigger_date", "effective_date", "deadline",
         "option_expiration", "rent_step_date", "response_due_date"}
    ),
    "amounts": frozenset(
        {"amount_cents", "rent_amount_cents", "new_rent_cents", "default_amount_cents"}
    ),
    "parties": frozenset({"tenant", "landlord", "recipient", "sender"}),
}


def _unknown(value: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    extras = sorted(str(key) for key in value if key not in allowed)
    if extras:
        raise ValueError(f"unrecognized inputs at {path}: {', '.join(extras)}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


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


def _day(value: Any, name: str, *, nullable: bool = False) -> date | None:
    if value is None and nullable:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value, name)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _cents(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer number of cents")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _flatten(source: Mapping[str, Any], path: str) -> dict[str, Any]:
    result = dict(source)
    for group, allowed in _NESTED_KEYS.items():
        nested = source.get(group)
        if nested is None:
            continue
        nested_mapping = _mapping(nested, f"{path}.{group}")
        _unknown(nested_mapping, allowed, f"{path}.{group}")
        for key, value in nested_mapping.items():
            if key in result and result[key] != value:
                raise ValueError(f"conflicting values for {path}.{key}")
            result[key] = value
        result.pop(group, None)
    return result


def _clause(facts: Mapping[str, Any]) -> dict[str, Any]:
    raw = facts.get("cited_clause", facts.get("clause"))
    if raw is None:
        quote = facts.get("clause_quote")
        locator = facts.get("clause_locator")
        citation = facts.get("citation")
        if citation is not None:
            citation = _mapping(citation, "lease_facts.citation")
            _unknown(citation, _CLAUSE_KEYS, "lease_facts.citation")
        raw = {"quote": quote, "locator": locator, **dict(citation or {})}
    elif isinstance(raw, str):
        raw = {"quote": raw, "locator": facts.get("clause_locator")}
    else:
        raw = dict(_mapping(raw, "lease_facts.cited_clause"))
    _unknown(raw, _CLAUSE_KEYS, "lease_facts.cited_clause")
    quote = _text(raw.get("quote", raw.get("clause_quote")), "cited clause quote")
    locator_parts = [raw.get("locator")]
    if raw.get("page") is not None:
        locator_parts.append(f"p{raw['page']}")
    if raw.get("cell") is not None:
        locator_parts.append(str(raw["cell"]))
    locator = " · ".join(str(item).strip() for item in locator_parts if item not in (None, ""))
    if not locator:
        raise ValueError("cited clause locator is required")
    return {**raw, "quote": quote, "locator": locator}


def _add_business_days(start: date, days: int) -> date:
    current = start
    remaining = days
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _subtract_business_days(start: date, days: int) -> date:
    current = start
    remaining = days
    while remaining:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _deadline(clause: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any] | None:
    explicit = values.get("deadline", values.get("response_due_date"))
    if explicit is not None:
        return {
            "deadline": _day(explicit, "deadline").isoformat(),
            "calculation": "caller-supplied date; no clause-day arithmetic was available",
            "clause_citation": {"quote": clause["quote"], "locator": clause["locator"]},
        }

    before_raw = clause.get("days_before", clause.get("notice_days_before"))
    days_raw = before_raw
    direction = "before" if before_raw is not None else "after"
    if days_raw is None:
        for key in ("deadline_days", "cure_days", "notice_days", "days"):
            if clause.get(key) is not None:
                days_raw = clause[key]
                break
    if days_raw is None:
        return None
    days = _nonnegative_int(days_raw, "clause deadline days")
    if direction == "before":
        anchor_raw = values.get("option_expiration", values.get("effective_date", values.get("rent_step_date")))
        anchor_name = "option_expiration/effective_date/rent_step_date"
    else:
        anchor_raw = values.get("trigger_date", values.get("event_date", values.get("notice_date")))
        anchor_name = "trigger_date/event_date/notice_date"
    anchor = _day(anchor_raw, anchor_name, nullable=True)
    if anchor is None:
        raise ValueError(f"{anchor_name} is required for clause deadline math")
    basis = str(clause.get("day_basis", clause.get("deadline_basis", "calendar_days"))).strip().casefold()
    if basis not in {"calendar_days", "calendar", "business_days", "business"}:
        raise ValueError("clause day_basis must be calendar_days or business_days")
    if direction == "before" and basis in {"business_days", "business"}:
        deadline = _subtract_business_days(anchor, days)
    elif direction == "before":
        deadline = anchor - timedelta(days=days)
    elif basis in {"business_days", "business"}:
        deadline = _add_business_days(anchor, days)
    else:
        deadline = anchor + timedelta(days=days)
    return {
        "deadline": deadline.isoformat(),
        "anchor_date": anchor.isoformat(),
        "days": days,
        "direction": direction,
        "day_basis": "business_days" if basis in {"business_days", "business"} else "calendar_days",
        "calculation": f"{anchor.isoformat()} {direction} {days} {basis.replace('_', ' ')} = {deadline.isoformat()}",
        "clause_citation": {"quote": clause["quote"], "locator": clause["locator"]},
    }


def _money(amount_cents: int) -> str:
    dollars, cents = divmod(amount_cents, 100)
    return f"${dollars:,}.{cents:02d}"


def draft_obligation_notice(
    lease_facts: Mapping[str, Any] | None,
    notice_type: str,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble cited facts and deadline math; perform no delivery action."""

    facts = _mapping(lease_facts, "lease_facts")
    _unknown(facts, _FACT_KEYS, "lease_facts")
    supplied = {} if params is None else _mapping(params, "params")
    _unknown(supplied, _PARAM_KEYS, "params")
    normalized_type = _text(notice_type, "notice_type").casefold()
    if normalized_type not in NOTICE_TYPES:
        raise ValueError(f"notice_type must be one of: {', '.join(sorted(NOTICE_TYPES))}")
    clause = _clause(facts)
    fact_values = _flatten(facts, "lease_facts")
    param_values = _flatten(supplied, "params")
    values = {key: value for key, value in fact_values.items() if value is not None}
    values.update({key: value for key, value in param_values.items() if value is not None})

    date_fields: dict[str, str] = {}
    for key in (
        "notice_date", "event_date", "trigger_date", "effective_date", "option_expiration",
        "rent_step_date", "response_due_date",
    ):
        if values.get(key) is not None:
            date_fields[key] = _day(values[key], key).isoformat()
    amount_fields: dict[str, int] = {}
    for key in ("amount_cents", "rent_amount_cents", "new_rent_cents", "default_amount_cents"):
        if values.get(key) is not None:
            amount_fields[key] = _cents(values[key], key)
    deadline_math = _deadline(clause, values)

    lines = [
        f"FACTUAL {normalized_type.replace('_', ' ').upper()} NOTICE DRAFT",
        f"Lease clause ({clause['locator']}): \"{clause['quote']}\"",
    ]
    for key in ("sender", "recipient", "landlord", "tenant", "property", "premises"):
        if values.get(key) is not None:
            lines.append(f"{key.replace('_', ' ').title()}: {_text(values[key], key)}")
    for key, value in date_fields.items():
        lines.append(f"{key.replace('_', ' ').title()}: {value}")
    for key, value in amount_fields.items():
        lines.append(f"{key.replace('_', ' ').title()}: {_money(value)} ({value} cents)")
    for key in ("description", "breach_description", "request_details", "option_type"):
        if values.get(key) is not None:
            lines.append(f"{key.replace('_', ' ').title()}: {_text(values[key], key)}")
    if deadline_math is not None:
        lines.append(f"Calculated deadline: {deadline_math['deadline']} ({deadline_math['calculation']})")
    lines.append(COUNSEL_ROUTING)

    return {
        "notice_type": normalized_type,
        "status": "draft_only",
        "content": "\n".join(lines),
        "cited_clause": {"quote": clause["quote"], "locator": clause["locator"]},
        "dates": date_fields,
        "amounts_cents": amount_fields,
        "deadline_math": deadline_math,
        "counsel_routing": COUNSEL_ROUTING,
        "legal_review_required": True,
        "delivery_status": "not_sent",
        "sent": False,
        "performed_actions": [],
        "honesty": (
            "Factual assembly only. No legal sufficiency, service method, waiver, default, "
            "or enforceability conclusion is made. This function never transmits a notice."
        ),
    }


__all__ = ["COUNSEL_ROUTING", "NOTICE_TYPES", "draft_obligation_notice"]
