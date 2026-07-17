"""Post-signing control scenarios for commercial master-lease positions.

The calculations in this module are deterministic cash-at-risk conventions, not
predictions or legal interpretations.  Contractual rights are never inferred from
an event name: the checklist either points to caller-supplied clause material or
states that the source is missing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


CONTROL_EVENTS = (
    "early_termination",
    "casualty",
    "condemnation",
    "cotenancy_failure",
    "owner_default",
    "subtenant_default",
)

_EVENT_CONVENTIONS: dict[str, dict[str, Any]] = {
    "early_termination": {
        "low_months": 1,
        "high_months": None,
        "security_at_risk": True,
        "review_points": (
            "termination triggers and any cure period",
            "continuing rent, acceleration, surrender, and restoration language",
            "treatment of security and prepaid amounts",
        ),
        "mitigations": (
            "Freeze discretionary spend and prepare a weekly cash runway.",
            "Seek a documented consensual termination, replacement tenant, or assignment.",
            "Preserve payment, notice, handback, and mitigation evidence.",
        ),
    },
    "casualty": {
        "low_months": 3,
        "high_months": 12,
        "security_at_risk": True,
        "review_points": (
            "rent abatement start, scope, and end conditions",
            "restoration responsibility, insurance proceeds, and completion deadlines",
            "termination rights, notice mechanics, and damage thresholds",
        ),
        "mitigations": (
            "Notify carriers and contractual counterparties through the required channels.",
            "Separate life-safety stabilization from disputed restoration scope.",
            "Build insured and uninsured cash schedules and document business interruption.",
        ),
    },
    "condemnation": {
        "low_months": 1,
        "high_months": 6,
        "security_at_risk": True,
        "review_points": (
            "partial versus total taking thresholds",
            "rent reduction, termination, and possession consequences",
            "allocation of awards and treatment of relocation claims",
        ),
        "mitigations": (
            "Preserve notices, plans, appraisals, and proof of relocation expense.",
            "Model continued operations, partial relocation, and full relocation separately.",
            "Coordinate any claim or settlement position with condemnation counsel.",
        ),
    },
    "cotenancy_failure": {
        "low_months": 3,
        "high_months": 12,
        "security_at_risk": False,
        "review_points": (
            "named co-tenant, occupancy, opening, and replacement tests",
            "alternative-rent formula and commencement conditions",
            "termination deadlines, notice, cure, and recapture provisions",
        ),
        "mitigations": (
            "Verify the co-tenancy facts against dated occupancy evidence.",
            "Prepare ordinary-rent and alternative-rent cash schedules without netting them.",
            "Pursue replacement occupancy and temporary traffic measures.",
        ),
    },
    "owner_default": {
        "low_months": 1,
        "high_months": 6,
        "security_at_risk": True,
        "review_points": (
            "owner obligations, default definition, notice, and cure periods",
            "offset, self-help, termination, and specific-performance language",
            "lender notice, subordination, non-disturbance, and attornment requirements",
        ),
        "mitigations": (
            "Document the condition and send only notices required by reviewed documents.",
            "Segregate disputed amounts rather than assuming a right to offset.",
            "Open an owner, lender, and subtenant continuity workstream with counsel.",
        ),
    },
    "subtenant_default": {
        "low_months": 3,
        "high_months": None,
        "security_at_risk": False,
        "review_points": (
            "subtenant default, notice, cure, and collection provisions",
            "recapture, termination, reletting, and mitigation language",
            "master-lease obligations that continue despite subtenant nonpayment",
        ),
        "mitigations": (
            "Start a penny-exact receivable and notice timeline.",
            "Market the space and qualify replacement occupants while preserving evidence.",
            "Confirm that enforcement and reletting steps comply with both lease layers.",
        ),
    },
}


def _mapping(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _integer(name: str, value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _optional_cents(source: Mapping[str, Any], keys: Sequence[str]) -> tuple[int, bool]:
    for key in keys:
        value = source.get(key)
        if value is not None:
            return _integer(key, value), True
    return 0, False


def _required_cents(source: Mapping[str, Any], keys: Sequence[str]) -> int:
    value, supplied = _optional_cents(source, keys)
    if not supplied:
        raise ValueError(f"position.{keys[0]} is required and cannot be null")
    return value


def _event_spec(raw: Any, index: int) -> tuple[str, Mapping[str, Any]]:
    if isinstance(raw, str):
        name = raw.strip()
        spec: Mapping[str, Any] = {}
    elif isinstance(raw, Mapping):
        candidate = raw.get("event", raw.get("type", raw.get("name")))
        if not isinstance(candidate, str) or not candidate.strip():
            raise ValueError(f"events[{index}] must include a non-empty event")
        name = candidate.strip()
        spec = raw
    else:
        raise TypeError(f"events[{index}] must be a string or mapping")
    if name not in CONTROL_EVENTS:
        allowed = ", ".join(CONTROL_EVENTS)
        raise ValueError(f"events[{index}] must be one of: {allowed}")
    return name, spec


def _duration_range(
    event: str, spec: Mapping[str, Any], remaining_months: int
) -> tuple[int, int, str]:
    convention = _EVENT_CONVENTIONS[event]
    low = min(int(convention["low_months"]), remaining_months)
    high_cap = convention["high_months"]
    high = remaining_months if high_cap is None else min(int(high_cap), remaining_months)
    raw = spec.get("duration_months_range")
    if raw is not None:
        if isinstance(raw, Mapping):
            low_raw = raw.get("low")
            high_raw = raw.get("high")
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) == 2:
            low_raw, high_raw = raw
        else:
            raise ValueError("duration_months_range must be a two-item sequence or low/high mapping")
        low = _integer("duration_months_range.low", low_raw)
        high = _integer("duration_months_range.high", high_raw)
        if low > high:
            raise ValueError("duration_months_range.low cannot exceed high")
        if high > remaining_months:
            raise ValueError("duration_months_range.high cannot exceed remaining term")
        source = "caller-supplied duration range"
    else:
        source = "disclosed operating convention"
    return low, high, source


def _clause_input(
    position: Mapping[str, Any], spec: Mapping[str, Any], event: str
) -> tuple[Any, str]:
    for key in ("clause", "lease_clause", "clause_text"):
        if spec.get(key) is not None:
            return spec[key], f"events.{event}.{key}"
    for container_name in ("lease_clauses", "clauses"):
        container = position.get(container_name)
        if container is not None:
            _mapping(f"position.{container_name}", container)
            if container.get(event) is not None:
                return container[event], f"position.{container_name}.{event}"
    direct_key = f"{event}_clause"
    if position.get(direct_key) is not None:
        return position[direct_key], f"position.{direct_key}"
    return None, f"position.lease_clauses.{event}"


def _citation(clause: Any, default_locator: str) -> tuple[dict[str, Any] | None, Mapping[str, Any] | None]:
    if clause is None:
        return None, None
    if isinstance(clause, str):
        text = clause.strip()
        if not text:
            raise ValueError(f"{default_locator} must not be empty")
        quote = text[:500]
        return {
            "quote": quote,
            "locator": default_locator,
            "source": "caller_supplied_lease_text",
            "quote_truncated": len(text) > len(quote),
        }, None
    if not isinstance(clause, Mapping):
        raise TypeError(f"{default_locator} must be text or a mapping")
    structured = clause
    text_value = next(
        (structured.get(key) for key in ("text", "clause_text", "quote") if structured.get(key) is not None),
        None,
    )
    locator_value = next(
        (structured.get(key) for key in ("locator", "section", "citation") if structured.get(key) is not None),
        default_locator,
    )
    if text_value is None:
        return None, structured
    if not isinstance(text_value, str) or not text_value.strip():
        raise ValueError(f"{default_locator}.text must be non-empty text or null")
    if not isinstance(locator_value, str) or not locator_value.strip():
        raise ValueError(f"{default_locator}.locator must be non-empty text")
    text = text_value.strip()
    quote = text[:500]
    return {
        "quote": quote,
        "locator": locator_value.strip(),
        "source": "caller_supplied_lease_text",
        "quote_truncated": len(text) > len(quote),
    }, structured


def _structured_items(clause: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    if clause is None:
        return []
    items: list[tuple[str, str]] = []
    for key in ("rights", "remedies", "conditions", "notice_requirements", "cure_periods"):
        raw = clause.get(key)
        if raw is None:
            continue
        values = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else [raw]
        for value in values:
            if isinstance(value, Mapping):
                rendered = str(value.get("text", value.get("value", ""))).strip()
            else:
                rendered = str(value).strip()
            if rendered:
                items.append((key, rendered))
    return items


def _rights_checklist(
    event: str,
    citation: Mapping[str, Any] | None,
    clause: Mapping[str, Any] | None,
    default_locator: str,
) -> list[dict[str, Any]]:
    structured = _structured_items(clause)
    if structured:
        return [
            {
                "status": "verify_with_counsel",
                "item": f"Verify caller-supplied {kind.replace('_', ' ')}: {text}",
                "source_supported": True,
                "citation": dict(citation) if citation is not None else {
                    "quote": text[:500],
                    "locator": default_locator,
                    "source": "caller_supplied_structured_clause",
                    "quote_truncated": len(text) > 500,
                },
            }
            for kind, text in structured
        ]
    if citation is not None:
        return [
            {
                "status": "review_cited_clause",
                "item": f"Determine whether the cited clause addresses {point}.",
                "source_supported": True,
                "citation": dict(citation),
            }
            for point in _EVENT_CONVENTIONS[event]["review_points"]
        ]
    return [
        {
            "status": "missing_source",
            "item": (
                f"Obtain the governing {event.replace('_', ' ')} clause before identifying "
                "contractual rights or remedies."
            ),
            "source_supported": False,
            "citation": None,
        }
    ]


def control_scenarios(
    position: Mapping[str, Any],
    events: Sequence[str | Mapping[str, Any]],
) -> dict[str, Any]:
    """Model bounded control-period cash exposure for specified disruption events.

    Low exposure uses the current monthly negative carry over the convention horizon.
    High exposure assumes zero sublease cash over that horizon.  Security is included
    in the high case only for events where control or possession may be impaired.
    Caller-supplied additional costs and duration ranges remain explicitly labeled.
    """

    position = _mapping("position", position)
    if (
        not isinstance(events, Sequence)
        or isinstance(events, (str, bytes))
        or not events
    ):
        raise ValueError("events must be a non-empty sequence")

    master_rent = _required_cents(
        position,
        ("master_rent_owed_cents", "master_rent_cents", "monthly_master_rent_cents"),
    )
    remaining_months, has_remaining = _optional_cents(
        position, ("remaining_term_months", "term_months")
    )
    if not has_remaining:
        raise ValueError("position.remaining_term_months or term_months is required")
    received, has_received = _optional_cents(
        position, ("sublease_received_cents", "monthly_sublease_received_cents")
    )
    billed, has_billed = _optional_cents(
        position, ("sublease_billed_cents", "monthly_sublease_billed_cents")
    )
    if not has_billed:
        billed = received
    reserves, has_reserves = _optional_cents(position, ("reserves_cents",))
    security, has_security = _optional_cents(
        position, ("security_cents", "security_deposit_cents")
    )
    expenses, has_expenses = _optional_cents(
        position,
        ("expense_cents", "monthly_expense_cents", "monthly_operating_expense_cents"),
    )
    full_monthly_cash_obligation = master_rent + expenses
    monthly_negative_carry = max(full_monthly_cash_obligation - received, 0)
    used_original_term_fallback = (
        position.get("remaining_term_months") is None
        and position.get("term_months") is not None
    )
    parsed = [_event_spec(raw, index) for index, raw in enumerate(events)]
    names = [name for name, _ in parsed]
    if len(names) != len(set(names)):
        raise ValueError("events cannot contain duplicates")

    modeled: list[dict[str, Any]] = []
    for event, spec in parsed:
        low_months, high_months, duration_source = _duration_range(
            event, spec, remaining_months
        )
        extra_low, _ = _optional_cents(spec, ("additional_cost_low_cents",))
        extra_high, _ = _optional_cents(spec, ("additional_cost_high_cents",))
        if extra_low > extra_high:
            raise ValueError(
                f"{event}.additional_cost_low_cents cannot exceed additional_cost_high_cents"
            )
        security_at_risk = bool(_EVENT_CONVENTIONS[event]["security_at_risk"])
        low_exposure = monthly_negative_carry * low_months + extra_low
        high_exposure = (
            full_monthly_cash_obligation * high_months
            + extra_high
            + (security if security_at_risk else 0)
        )
        high_exposure = max(high_exposure, low_exposure)
        clause, default_locator = _clause_input(position, spec, event)
        citation, structured_clause = _citation(clause, default_locator)
        checklist = _rights_checklist(
            event, citation, structured_clause, default_locator
        )
        modeled.append(
            {
                "cash_exposure_range_cents": {
                    "low": low_exposure,
                    "high": high_exposure,
                },
                "cash_exposure_low_cents": low_exposure,
                "cash_exposure_high_cents": high_exposure,
                "event": event,
                "rent_owed_vs_received": {
                    "master_rent_owed_cents": master_rent,
                    "monthly_master_rent_owed_cents": master_rent,
                    "expense_cents": expenses,
                    "monthly_expense_cents": expenses,
                    "full_monthly_cash_obligation_cents": full_monthly_cash_obligation,
                    "monthly_sublease_rent_received_cents": received,
                    "monthly_negative_carry_cents": monthly_negative_carry,
                    "sublease_billed_not_received_cents": max(billed - received, 0),
                },
                "exposure_duration_months_range": {
                    "low": low_months,
                    "high": high_months,
                    "source": duration_source,
                },
                "unfunded_after_reserves_range_cents": {
                    "low": max(low_exposure - reserves, 0),
                    "high": max(high_exposure - reserves, 0),
                },
                "exposure_convention": (
                    "Low = max(master rent + monthly expense − sublease cash received, 0) "
                    "× low duration + supplied low additional cost. High = (master rent + "
                    "monthly expense) × high duration + supplied high additional cost"
                    + (" + security at risk." if security_at_risk else ".")
                ),
                "exposure_formula_inputs_cents": {
                    "master_rent_owed": master_rent,
                    "monthly_expense": expenses,
                    "sublease_cash_received": received,
                    "current_monthly_negative_carry": monthly_negative_carry,
                    "additional_cost_low": extra_low,
                    "additional_cost_high": extra_high,
                    "security_at_risk_in_high_case": security if security_at_risk else 0,
                },
                "rights_remedies_checklist": checklist,
                "clause_citation": dict(citation) if citation is not None else None,
                "counsel_flag": True,
                "counsel_note": (
                    "CRE counsel must interpret triggers, enforceability, notice, cure, "
                    "abatement, offset, termination, award, and remedy language before action."
                ),
                "mitigation_options": list(_EVENT_CONVENTIONS[event]["mitigations"]),
                "assumptions": [
                    "No contractual right or insurance recovery is netted from exposure.",
                    "High case assumes no sublease collections during the high duration.",
                    "Security-at-risk treatment is a stress convention, not a forfeiture conclusion.",
                ],
            }
        )

    missing_inputs = []
    if not has_received:
        missing_inputs.append("sublease_received_cents (modeled as zero)")
    if not has_billed:
        missing_inputs.append("sublease_billed_cents (modeled equal to received)")
    if not has_reserves:
        missing_inputs.append("reserves_cents (modeled as zero)")
    if not has_security:
        missing_inputs.append("security_cents (modeled as zero)")
    if not has_expenses:
        missing_inputs.append("expense_cents (modeled as zero)")
    if used_original_term_fallback:
        missing_inputs.append(
            "remaining_term_months (term_months used as a disclosed original-term fallback)"
        )

    return {
        "rent_owed_vs_received_exposure": {
            "master_rent_owed_cents": master_rent,
            "monthly_master_rent_owed_cents": master_rent,
            "expense_cents": expenses,
            "monthly_expense_cents": expenses,
            "full_monthly_cash_obligation_cents": full_monthly_cash_obligation,
            "monthly_sublease_rent_billed_cents": billed,
            "monthly_sublease_rent_received_cents": received,
            "monthly_negative_carry_cents": monthly_negative_carry,
            "collection_gap_cents": max(billed - received, 0),
            "remaining_term_gross_master_rent_cents": master_rent * remaining_months,
            "remaining_term_gross_cash_obligation_cents": (
                full_monthly_cash_obligation * remaining_months
            ),
            "remaining_term_months": remaining_months,
            "remaining_term_source": (
                "term_months fallback; elapsed term was not derived"
                if used_original_term_fallback
                else "remaining_term_months"
            ),
            "warning": (
                "Master rent remains owed when sublease space is vacant or subtenant cash "
                "is not received; billed rent is not treated as cash."
            ),
        },
        "scenarios": modeled,
        "events_modeled": names,
        "missing_inputs": missing_inputs,
        "posture": (
            "Operating stress ranges only. They are not forecasts, legal conclusions, "
            "insurance coverage opinions, or authority to exercise a remedy."
        ),
    }


__all__ = ["CONTROL_EVENTS", "control_scenarios"]
