"""Convention-cited preventive-maintenance scheduling.

The intervals here are planning conventions, not measurements or legal advice.
They are exposed so an operator can inspect and replace them.  System lifespan
context is read from :mod:`cre_mcp.physical.rul`; this module never changes the
physical convention table.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from cre_mcp.physical.rul import LIFESPAN_CONVENTIONS


SERVICE_INTERVAL_CONVENTIONS: dict[str, tuple[dict[str, Any], ...]] = {
    "hvac": (
        {
            "convention_id": "hvac_filter_quarterly",
            "task": "Replace or inspect HVAC filters",
            "interval_months": 3,
            "basis": (
                "Planning convention: inspect or replace filters quarterly; actual "
                "frequency depends on equipment, occupancy, and manufacturer guidance."
            ),
        },
        {
            "convention_id": "hvac_annual_service",
            "task": "Complete annual HVAC service",
            "interval_months": 12,
            "basis": (
                "Planning convention: qualified HVAC service annually; follow the "
                "manufacturer's maintenance schedule where it is more specific."
            ),
        },
    ),
    "roof": (
        {
            "convention_id": "roof_semiannual_inspection",
            "task": "Inspect roof and drainage",
            "interval_months": 6,
            "basis": (
                "Planning convention: inspect roof and drainage semiannually and "
                "after significant weather; warranty requirements may differ."
            ),
        },
    ),
    "elevator": (
        {
            "convention_id": "elevator_monthly_service",
            "task": "Complete elevator service visit",
            "interval_months": 1,
            "basis": (
                "Planning convention: monthly service visit; contract, equipment, "
                "and authority-having-jurisdiction requirements control."
            ),
        },
        {
            "convention_id": "elevator_annual_certificate_review",
            "task": "Verify elevator inspection/certificate",
            "interval_months": 12,
            "basis": (
                "Planning convention: annual certificate/inspection check. This is "
                "not a legal calendar; verify the local jurisdiction's actual cycle."
            ),
        },
    ),
    "backflow": (
        {
            "convention_id": "backflow_annual_test",
            "task": "Test backflow-prevention assembly",
            "interval_months": 12,
            "basis": (
                "Planning convention: annual backflow test; verify water-utility and "
                "local authority requirements."
            ),
        },
    ),
    "fire_alarm": (
        {
            "convention_id": "fire_alarm_annual_service",
            "task": "Inspect and test fire-alarm system",
            "interval_months": 12,
            "basis": (
                "Planning convention: annual qualified inspection/test; verify the "
                "adopted code, local authority, and system-specific schedule."
            ),
        },
    ),
    "fire_sprinkler": (
        {
            "convention_id": "fire_sprinkler_quarterly_check",
            "task": "Complete sprinkler-system quarterly check",
            "interval_months": 3,
            "basis": (
                "Planning convention: quarterly system check; component-specific and "
                "jurisdictional testing intervals may be different."
            ),
        },
        {
            "convention_id": "fire_sprinkler_annual_inspection",
            "task": "Complete sprinkler-system annual inspection",
            "interval_months": 12,
            "basis": (
                "Planning convention: annual qualified inspection; verify the adopted "
                "code and authority-having-jurisdiction requirements."
            ),
        },
    ),
    "domestic_water_heater": (
        {
            "convention_id": "water_heater_annual_service",
            "task": "Inspect and service domestic water heater",
            "interval_months": 12,
            "basis": (
                "Planning convention: annual inspection/service; follow the equipment "
                "manufacturer's instructions for flushing and safety checks."
            ),
        },
    ),
}


SYSTEM_ALIASES: dict[str, str] = {
    "air_conditioning": "hvac",
    "rooftop_hvac_unit": "hvac",
    "rooftop_unit": "hvac",
    "rtu": "hvac",
    "roofing": "roof",
    "elevators": "elevator",
    "backflow_preventer": "backflow",
    "backflow_prevention": "backflow",
    "sprinkler": "fire_sprinkler",
    "fire_sprinklers": "fire_sprinkler",
    "fire_life_safety": "fire_alarm",
    "water_heater": "domestic_water_heater",
}


_PHYSICAL_KEYS: dict[str, str] = {
    "hvac": "hvac_generic",
    "roof": "roof_generic",
    "elevator": "elevator",
    "backflow": "plumbing_generic",
    "fire_alarm": "fire_alarm",
    "fire_sprinkler": "fire_sprinkler",
    "domestic_water_heater": "domestic_water_heater",
}

_ASSET_FIELDS = frozenset({"asset", "system", "install_year", "last_service"})


def _as_date(value: date | datetime | str | None, *, field: str) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")
    return value.strip()


def _system_key(value: Any) -> str:
    system = _text(value, field="system")
    key = "_".join(
        system.casefold().replace("/", " ").replace("-", " ").split()
    )
    key = SYSTEM_ALIASES.get(key, key)
    if key not in SERVICE_INTERVAL_CONVENTIONS:
        accepted = sorted(set(SERVICE_INTERVAL_CONVENTIONS) | set(SYSTEM_ALIASES))
        raise ValueError(f"unknown system {system!r}; expected one of {accepted}")
    return key


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _physical_context(system: str, install_year: int | None, as_of: date) -> dict[str, Any]:
    convention_key = _PHYSICAL_KEYS[system]
    convention = LIFESPAN_CONVENTIONS[convention_key]
    context: dict[str, Any] = {
        "vocabulary_system": convention["capex_system"],
        "convention_key": convention_key,
        "lifespan_years": {
            "low": convention["low"],
            "high": convention["high"],
        },
        "description": convention["description"],
        "source_note": convention["source_note"],
        "read_only_source": "cre_mcp.physical.rul.LIFESPAN_CONVENTIONS",
    }
    if install_year is None:
        context.update(
            {
                "age_years": None,
                "remaining_life_years": None,
                "age_basis": "install_year not supplied; no age or RUL arithmetic performed",
            }
        )
        return context
    age = as_of.year - install_year
    context.update(
        {
            "age_years": age,
            "remaining_life_years": {
                "low": max(0, convention["low"] - age),
                "high": max(0, convention["high"] - age),
            },
            "age_basis": f"{as_of.year} as-of year - {install_year} install year = {age} years",
        }
    )
    return context


def pm_schedule(
    assets: Sequence[Mapping[str, Any]],
    as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Expand system records into a dated, convention-cited PM schedule.

    ``last_service`` is system-level input.  When a system has multiple PM tasks,
    the same date is deliberately applied to each and that assumption is shown on
    every item.  A missing date is never converted into an invented due date.
    """

    point = _as_date(as_of, field="as_of")
    if isinstance(assets, (str, bytes, Mapping)) or not isinstance(assets, Sequence):
        raise ValueError("assets must be a sequence of mappings")

    items: list[dict[str, Any]] = []
    for index, raw in enumerate(assets):
        path = f"assets[{index}]"
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path} must be a mapping")
        unknown = sorted(str(key) for key in set(raw) - _ASSET_FIELDS)
        if unknown:
            raise ValueError(f"unrecognized inputs at {path}: {', '.join(unknown)}")
        if "system" not in raw:
            raise ValueError(f"{path}.system is required")
        system = _system_key(raw["system"])

        asset_name = raw.get("asset")
        if asset_name is not None:
            asset_name = _text(asset_name, field=f"{path}.asset")

        install_year = raw.get("install_year")
        if install_year is not None:
            if isinstance(install_year, bool) or not isinstance(install_year, int):
                raise ValueError(f"{path}.install_year must be a whole calendar year or null")
            if not 1800 <= install_year <= point.year:
                raise ValueError(
                    f"{path}.install_year must be between 1800 and {point.year}"
                )

        last_service_raw = raw.get("last_service")
        last_service = (
            _as_date(last_service_raw, field=f"{path}.last_service")
            if last_service_raw is not None
            else None
        )
        if last_service is not None and last_service > point:
            raise ValueError(f"{path}.last_service cannot be later than as_of")

        physical = _physical_context(system, install_year, point)
        conventions = SERVICE_INTERVAL_CONVENTIONS[system]
        for convention in conventions:
            next_due = (
                _add_months(last_service, int(convention["interval_months"]))
                if last_service is not None
                else None
            )
            is_due = next_due is not None and next_due <= point
            schedule_status = (
                "due" if is_due else "upcoming" if next_due is not None else "unknown"
            )
            item = {
                "asset": asset_name,
                "asset_index": index,
                "system": system,
                "task": convention["task"],
                "last_service": last_service.isoformat() if last_service else None,
                "next_due": next_due.isoformat() if next_due else None,
                "due": is_due if next_due is not None else None,
                "status": schedule_status,
                "days_overdue": (point - next_due).days if is_due and next_due else 0 if next_due else None,
                "convention": dict(convention),
                "convention_citation": (
                    f"{convention['convention_id']}: every "
                    f"{convention['interval_months']} month(s) — {convention['basis']}"
                ),
                "date_basis": (
                    "caller-provided system-level last_service plus interval; the same "
                    "date is applied to each task for this system"
                    if last_service is not None
                    else "last_service not supplied; due date is unknown rather than inferred"
                ),
                "physical_rul_cross_link": dict(physical),
            }
            items.append(item)

    due_list = [item for item in items if item["due"] is True]
    upcoming = [item for item in items if item["due"] is False]
    unknown = [item for item in items if item["due"] is None]
    due_list.sort(
        key=lambda item: (
            item["next_due"] or "9999-12-31",
            item["asset"] or "",
            item["system"],
            item["task"],
        )
    )
    upcoming.sort(key=lambda item: (item["next_due"] or "", item["system"], item["task"]))

    return {
        "as_of": point.isoformat(),
        "due_list": due_list,
        "upcoming": upcoming,
        "unknown_due_date": unknown,
        "items": items,
        "counts": {
            "due": len(due_list),
            "upcoming": len(upcoming),
            "unknown": len(unknown),
            "total": len(items),
        },
        "convention_table": {
            system: [dict(convention) for convention in conventions]
            for system, conventions in SERVICE_INTERVAL_CONVENTIONS.items()
        },
        "honesty": (
            "Planning conventions only, not statutory or manufacturer requirements. "
            "Missing service dates remain unknown; install year only supplies screening "
            "RUL context from the physical convention vocabulary."
        ),
    }


__all__ = ["SERVICE_INTERVAL_CONVENTIONS", "SYSTEM_ALIASES", "pm_schedule"]
