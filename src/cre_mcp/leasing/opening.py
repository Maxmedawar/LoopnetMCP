"""Transparent retail-opening critical-path date math.

This module is a planning aid.  It deliberately quotes, rather than interprets,
the supplied rent-commencement trigger and labels default durations as
conventions that must be replaced with project- and jurisdiction-specific facts.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any


DEFAULT_DURATION_DAYS: dict[str, int] = {
    "permit": 90,
    "ti_buildout": 120,
    "fixturing": 14,
}

_DURATION_FIELDS: dict[str, tuple[str, ...]] = {
    "permit": ("permits_est_days", "permit_est_days", "permitting_est_days"),
    "ti_buildout": ("ti_buildout_est_days", "buildout_est_days", "ti_est_days"),
    "fixturing": ("fixturing_days", "fixturing_est_days", "fixture_est_days"),
}


def _as_date(value: Any, *, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{label} must be an ISO date")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} cannot be blank")
    try:
        # Accept an ISO datetime without allowing its timezone to move the
        # stated project calendar date.
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _first(mapping: Mapping[str, Any], names: tuple[str, ...]) -> tuple[str | None, Any]:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return name, mapping[name]
    return None, None


def _milestone_date(
    milestones: Mapping[str, Any],
    names: tuple[str, ...],
    *,
    label: str,
) -> tuple[date | None, str | None]:
    name, value = _first(milestones, names)
    if name is None:
        return None, None
    if isinstance(value, Mapping):
        nested_name, nested_value = _first(
            value, ("date", "target_date", "scheduled_date", "value")
        )
        if nested_name is None:
            return None, name
        value = nested_value
    return _as_date(value, label=label), name


def _duration(
    milestones: Mapping[str, Any], stage: str
) -> tuple[int, str, str | None]:
    field, raw = _first(milestones, _DURATION_FIELDS[stage])
    if field is None:
        return DEFAULT_DURATION_DAYS[stage], "planning convention", None
    if isinstance(raw, bool):
        raise TypeError(f"{field} must be a whole number of calendar days")
    try:
        number = float(raw)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field} must be a whole number of calendar days") from exc
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(f"{field} must be a non-negative whole number of calendar days")
    return int(number), "supplied input", field


def _trigger(milestones: Mapping[str, Any]) -> tuple[str | None, str | None]:
    field, value = _first(
        milestones,
        (
            "rent_commencement_trigger",
            "rent_commencement_trigger_text",
            "rent_commencement_clause",
            "rent_start_trigger",
        ),
    )
    if field is None:
        rent_value = milestones.get("rent_commencement")
        if isinstance(rent_value, Mapping):
            nested, value = _first(rent_value, ("trigger", "trigger_text", "terms"))
            if nested is not None:
                field = f"rent_commencement.{nested}"
        elif isinstance(rent_value, str):
            try:
                _as_date(rent_value, label="rent commencement")
            except ValueError:
                field = "rent_commencement"
                value = rent_value
    if field is None:
        return None, None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text so it can be quoted without interpretation")
    if not value.strip():
        raise ValueError(f"{field} cannot be blank")
    # Preserve whitespace and capitalization: this is a quote from input, not
    # normalized legal language.
    return value, field


def _step(
    milestone: str,
    dependency: str | None,
    start: date,
    finish: date,
    duration_days: int,
    basis: str,
) -> dict[str, Any]:
    return {
        "milestone": milestone,
        "dependency": dependency,
        "start_date": start.isoformat(),
        "finish_date": finish.isoformat(),
        "date": finish.isoformat(),
        "duration_days": duration_days,
        "duration_basis": basis,
    }


def opening_critical_path(
    lease_milestones: Mapping[str, Any],
    jurisdiction_note: str | None = None,
) -> dict[str, Any]:
    """Build an execution-to-opening dependency chain using calendar days.

    Accepted execution aliases are ``execution`` and ``execution_date``.
    Optional targets include ``target_open``/``target_open_date`` and
    ``rent_commencement_date``.  Missing permit, TI-buildout, and fixturing
    durations use exposed planning conventions of 90, 120, and 14 calendar
    days respectively.  Those defaults are not jurisdiction or contractor
    benchmarks.
    """

    if not isinstance(lease_milestones, Mapping):
        raise TypeError("lease_milestones must be a mapping")
    execution, execution_field = _milestone_date(
        lease_milestones,
        ("execution", "execution_date", "lease_execution", "lease_execution_date"),
        label="lease_milestones.execution",
    )
    if execution is None:
        raise ValueError("lease_milestones.execution is required as an ISO date")

    if jurisdiction_note is not None:
        if not isinstance(jurisdiction_note, str):
            raise TypeError("jurisdiction_note must be text")
        if not jurisdiction_note.strip():
            raise ValueError("jurisdiction_note cannot be blank")

    permit_days, permit_basis, permit_field = _duration(lease_milestones, "permit")
    ti_days, ti_basis, ti_field = _duration(lease_milestones, "ti_buildout")
    fixture_days, fixture_basis, fixture_field = _duration(
        lease_milestones, "fixturing"
    )

    permit_complete = execution + timedelta(days=permit_days)
    ti_complete = permit_complete + timedelta(days=ti_days)
    fixture_complete = ti_complete + timedelta(days=fixture_days)
    projected_open = fixture_complete

    target_open, target_open_field = _milestone_date(
        lease_milestones,
        (
            "target_open",
            "target_open_date",
            "opening_date",
            "open_date",
            "opening",
            "open",
        ),
        label="target open",
    )
    rent_date, rent_date_field = _milestone_date(
        lease_milestones,
        ("rent_commencement_date", "rent_start_date", "rent_commencement_target"),
        label="rent commencement",
    )
    if rent_date is None and isinstance(lease_milestones.get("rent_commencement"), Mapping):
        rent_value = lease_milestones["rent_commencement"]
        nested_name, nested_value = _first(
            rent_value, ("date", "target_date", "scheduled_date")
        )
        if nested_name is not None:
            rent_date = _as_date(nested_value, label="rent commencement")
            rent_date_field = f"rent_commencement.{nested_name}"
    elif rent_date is None and isinstance(
        lease_milestones.get("rent_commencement"), (str, date)
    ):
        direct_rent_value = lease_milestones["rent_commencement"]
        try:
            rent_date = _as_date(direct_rent_value, label="rent commencement")
            rent_date_field = "rent_commencement"
        except ValueError:
            # A non-date string is handled below as quoted trigger language.
            pass

    trigger, trigger_field = _trigger(lease_milestones)
    lag_field, lag_raw = _first(
        lease_milestones,
        ("rent_commencement_lag_days", "rent_start_lag_days"),
    )
    lag_days: int | None = None
    if lag_field is not None:
        if isinstance(lag_raw, bool):
            raise TypeError(f"{lag_field} must be a whole number of calendar days")
        try:
            lag_number = float(lag_raw)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"{lag_field} must be a whole number of calendar days"
            ) from exc
        if not math.isfinite(lag_number) or lag_number < 0 or not lag_number.is_integer():
            raise ValueError(
                f"{lag_field} must be a non-negative whole number of calendar days"
            )
        lag_days = int(lag_number)

    if rent_date is not None:
        projected_rent = rent_date
        rent_basis = f"supplied date ({rent_date_field})"
    elif lag_days is not None:
        projected_rent = projected_open + timedelta(days=lag_days)
        rent_basis = f"supplied lag ({lag_field})"
    else:
        projected_rent = projected_open
        rent_basis = (
            "planning placeholder: same date as projected opening; quoted lease "
            "language controls and has not been interpreted"
        )

    open_slack = (
        (target_open - projected_open).days if target_open is not None else None
    )
    rent_slack = (
        (rent_date - projected_open).days
        if rent_date is not None
        else lag_days
    )

    chain = [
        _step("execution", None, execution, execution, 0, f"supplied ({execution_field})"),
        _step(
            "permit",
            "execution",
            execution,
            permit_complete,
            permit_days,
            permit_basis,
        ),
        _step(
            "ti_buildout",
            "permit",
            permit_complete,
            ti_complete,
            ti_days,
            ti_basis,
        ),
        _step(
            "fixturing",
            "ti_buildout",
            ti_complete,
            fixture_complete,
            fixture_days,
            fixture_basis,
        ),
        _step("open", "fixturing", projected_open, projected_open, 0, "dependency math"),
        _step(
            "rent_commencement",
            "open (subject to the quoted lease trigger)",
            projected_open,
            projected_rent,
            (projected_rent - projected_open).days,
            rent_basis,
        ),
    ]

    risks: list[dict[str, Any]] = [
        {
            "stage": "permit",
            "status": "flag",
            "risk": "Permit review timing is jurisdiction-dependent.",
            "jurisdiction_note": jurisdiction_note,
            "action": (
                "Validate scope, submittal completeness, review queues, resubmittal cycles, "
                "inspections, and certificate-of-occupancy requirements with the jurisdiction."
            ),
        }
    ]
    if jurisdiction_note is None:
        risks[0]["gap"] = "No jurisdiction note was supplied."
    if target_open is not None and open_slack is not None and open_slack < 0:
        risks.append(
            {
                "stage": "open",
                "status": "negative_slack",
                "risk": f"The dependency path is {-open_slack} calendar day(s) later than the supplied target open date.",
            }
        )
    if rent_date is not None and rent_slack is not None and rent_slack < 0:
        risks.append(
            {
                "stage": "rent_commencement",
                "status": "date_collision",
                "risk": f"The supplied rent commencement is {-rent_slack} calendar day(s) before projected opening.",
            }
        )
    if trigger is None:
        risks.append(
            {
                "stage": "rent_commencement",
                "status": "missing_input",
                "risk": "No rent-commencement trigger text was supplied; the lease trigger must be reviewed.",
            }
        )

    duration_assumptions = {
        "permits_est_days": {
            "days": permit_days,
            "basis": permit_basis,
            "input_field": permit_field,
        },
        "ti_buildout_est_days": {
            "days": ti_days,
            "basis": ti_basis,
            "input_field": ti_field,
        },
        "fixturing_days": {
            "days": fixture_days,
            "basis": fixture_basis,
            "input_field": fixture_field,
        },
    }
    return {
        "dependency_chain": chain,
        "critical_path": [dict(step) for step in chain],
        "chain_order": [step["milestone"] for step in chain],
        "execution_date": execution.isoformat(),
        "permit_complete_date": permit_complete.isoformat(),
        "ti_complete_date": ti_complete.isoformat(),
        "fixturing_complete_date": fixture_complete.isoformat(),
        "projected_open_date": projected_open.isoformat(),
        "estimated_open": projected_open.isoformat(),
        "projected_rent_commencement_date": projected_rent.isoformat(),
        "estimated_rent_commencement": projected_rent.isoformat(),
        "target_open_date": target_open.isoformat() if target_open else None,
        "supplied_rent_commencement_date": rent_date.isoformat() if rent_date else None,
        "slack_days": {
            "to_target_open": open_slack,
            "from_projected_open_to_rent_commencement": rent_slack,
        },
        "open_slack_days": open_slack,
        "rent_commencement_slack_days": rent_slack,
        "rent_commencement_trigger": trigger,
        "quoted_rent_commencement_trigger": trigger,
        "rent_commencement_trigger_input_field": trigger_field,
        "jurisdiction_note": jurisdiction_note,
        "risk_points": risks,
        "assumptions": {
            "duration_days": duration_assumptions,
            "calendar_basis": "All durations and slack use elapsed calendar days, not business days.",
            "sequence_convention": "TI begins after permit completion; fixturing begins after TI completion; no overlap is modeled.",
            "rent_commencement_treatment": rent_basis,
            "legal_limitation": "The quoted trigger is not interpreted; the executed lease and counsel control.",
        },
        "input_echo": dict(lease_milestones),
    }


__all__ = ["DEFAULT_DURATION_DAYS", "opening_critical_path"]
