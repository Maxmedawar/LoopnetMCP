"""Accessibility, fire/life-safety, and code-trigger exposure screening.

This module uses deliberately broad conventions.  Adopted codes, safe harbors,
valuation thresholds, path-of-travel limits, and change-of-occupancy rules vary
by jurisdiction.  Every checklist line therefore requires local verification.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from math import isfinite
from typing import Any

from cre_mcp.physical.capex import replacement_cost_range


DISCLAIMER = (
    "Screening estimate only; it does not replace a licensed PCA provider, "
    "architect, accessibility consultant, fire-protection engineer, code "
    "counsel, contractor, or other licensed engineer."
)
VERIFY_LOCAL = "verify w/ local code counsel/architect"
INPUT_SCOPE = (
    "Structured inputs v1 only. PCA PDF parsing and plan/code-set review are "
    "out of scope."
)


CODE_TRIGGER_CONVENTIONS: dict[str, dict[str, Any]] = {
    "altered_area_accessibility": {
        "category": "accessibility",
        "cost_system": "ada",
        "extent": 0.05,
        "severity": "high",
        "convention": (
            "Renovated/altered areas commonly require an accessible route and "
            "related barrier work; exact scope and cost caps vary locally."
        ),
    },
    "change_of_use_accessibility": {
        "category": "accessibility",
        "cost_system": "ada",
        "extent": 0.10,
        "severity": "high",
        "convention": (
            "A change of occupancy/use can trigger accessibility review for "
            "the altered area, accessible route, services, toilets, and parking."
        ),
    },
    "change_of_use_energy": {
        "category": "energy",
        "cost_system": "hvac",
        "extent": 0.15,
        "severity": "medium",
        "convention": (
            "A change of use or major renovation can trigger adopted energy-code "
            "requirements for envelope, lighting, controls, and mechanical work."
        ),
    },
    "change_of_use_fire": {
        "category": "fire_life_safety",
        "cost_system": "fire_life_safety",
        "extent": 1.0,
        "severity": "high",
        "convention": (
            "Occupancy/use changes can change egress, occupant-load, alarm, "
            "sprinkler, separation, and fire-resistance requirements."
        ),
    },
    "major_renovation_energy": {
        "category": "energy",
        "cost_system": "hvac",
        "extent": 0.20,
        "severity": "medium",
        "convention": (
            "Substantial work commonly triggers current-code review of affected "
            "lighting, controls, mechanical, envelope, and commissioning scope."
        ),
    },
    "major_renovation_fire": {
        "category": "fire_life_safety",
        "cost_system": "fire_life_safety",
        "extent": 1.0,
        "severity": "high",
        "convention": (
            "Substantial renovation commonly triggers current review of alarm, "
            "sprinkler, egress, emergency lighting, and rated assemblies."
        ),
    },
    "legacy_accessibility": {
        "category": "accessibility",
        "cost_system": "ada",
        "extent": 0.05,
        "severity": "medium",
        "convention": (
            "A pre-1991 property without a later renovation date warrants an "
            "existing-barrier and readily-achievable-removal survey."
        ),
    },
    "legacy_fire_system": {
        "category": "fire_life_safety",
        "cost_system": "fire_life_safety",
        "extent": 1.0,
        "severity": "high",
        "convention": (
            "A pre-1990 building warrants a current-code and records review of "
            "sprinklers, alarms, egress, fire ratings, and inspection history."
        ),
    },
    "vertical_access": {
        "category": "accessibility",
        "cost_system": "ada",
        "extent": 0.08,
        "severity": "high",
        "convention": (
            "Multi-story altered facilities require review of accessible vertical "
            "routes; elevator exceptions and scoping vary by use and jurisdiction."
        ),
    },
}


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive number") from exc
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be a positive number")
    return number


def _year(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a four-digit year")
    try:
        numeric_year = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a four-digit year") from exc
    if not isfinite(numeric_year) or not numeric_year.is_integer():
        raise ValueError(f"{field} must be a four-digit year")
    year = int(numeric_year)
    if year < 1700 or year > date.today().year:
        raise ValueError(f"{field} must be between 1700 and {date.today().year}")
    return year


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().casefold()
    false_values = {"", "no", "none", "false", "0", "n/a", "unchanged"}
    return normalized not in false_values and "no change" not in normalized


def _scope(scope: Any) -> tuple[bool, bool, str | None]:
    """Return (has renovation, looks major, normalized description)."""

    if scope is None:
        return False, False, None
    if isinstance(scope, str):
        normalized = scope.strip().casefold()
        if not normalized or normalized in {"none", "no", "n/a"}:
            return False, False, None
        major_terms = ("major", "substantial", "gut", "full", "structural", "redevelop")
        return True, any(term in normalized for term in major_terms), scope.strip()
    if isinstance(scope, Mapping):
        if not scope:
            return False, False, None
        label = str(
            scope.get("level")
            or scope.get("type")
            or scope.get("description")
            or "structured renovation scope"
        )
        fraction = scope.get("fraction", scope.get("percent_of_building"))
        fraction_number = None
        if fraction is not None and not isinstance(fraction, bool):
            try:
                fraction_number = float(fraction)
                if fraction_number > 1:
                    fraction_number /= 100
            except (TypeError, ValueError):
                fraction_number = None
        major = any(
            term in label.casefold()
            for term in ("major", "substantial", "gut", "full", "structural", "redevelop")
        ) or (fraction_number is not None and fraction_number >= 0.50)
        return True, major, label
    raise ValueError("planned.renovation_scope must be a string, dictionary, or null")


def _exposure_line(
    trigger_id: str,
    trigger: str,
    building_sf: float,
    floors: int,
) -> dict[str, Any]:
    convention = CODE_TRIGGER_CONVENTIONS[trigger_id]
    cost = replacement_cost_range(
        convention["cost_system"],
        building_sf=building_sf,
        floors=floors,
        extent=convention["extent"],
    )
    return {
        "trigger_id": trigger_id,
        "trigger": trigger,
        "category": convention["category"],
        "upgrade_checklist": convention["convention"],
        "severity": convention["severity"],
        "exposure_cost_range": {"low": cost["low"], "high": cost["high"]},
        "cost_basis": {
            "system": convention["cost_system"],
            "quantity": cost["quantity"],
            "unit": cost["unit"],
            "extent": convention["extent"],
            "source_note": cost["source_note"],
        },
        "classification": "professional_opinion_needed",
        "verification": VERIFY_LOCAL,
        "professional_disclaimer": DISCLAIMER,
    }


def ada_code_exposure(
    building: dict[str, Any],
    planned: dict[str, Any],
) -> dict[str, Any]:
    """Screen for upgrade triggers and convention-based exposure ranges.

    Cost ranges are not additive bids: multiple checklist lines can overlap in
    scope.  They are generated from the shared CapEx convention table and must
    be replaced with local design and contractor pricing.
    """

    if not isinstance(building, dict):
        raise ValueError("building must be a dictionary")
    if not isinstance(planned, dict):
        raise ValueError("planned must be a dictionary")
    missing = [key for key in ("year_built", "type", "sf") if key not in building]
    if missing:
        raise ValueError(f"building missing required field(s): {', '.join(missing)}")

    year_built = _year(building["year_built"], "building.year_built")
    raw_building_type = building["type"]
    if not isinstance(raw_building_type, str) or not raw_building_type.strip():
        raise ValueError("building.type is required")
    building_type = raw_building_type.strip()
    sf = _positive_number(building["sf"], "building.sf")
    floors_number = _positive_number(building.get("floors", 1), "building.floors")
    if not floors_number.is_integer():
        raise ValueError("building.floors must be a whole number")
    floors = int(floors_number)
    last_renovation = (
        _year(building["last_renovation"], "building.last_renovation")
        if building.get("last_renovation") is not None
        else None
    )
    if last_renovation is not None and last_renovation < year_built:
        raise ValueError("building.last_renovation cannot predate building.year_built")

    change_of_use = _is_true(planned.get("change_of_use"))
    has_renovation, major_renovation, scope_description = _scope(
        planned.get("renovation_scope")
    )

    requested: list[tuple[str, str]] = []
    if has_renovation:
        requested.append(("altered_area_accessibility", "planned renovation/alteration"))
    if change_of_use:
        requested.extend(
            [
                ("change_of_use_accessibility", "planned change of use/occupancy"),
                ("change_of_use_energy", "planned change of use/occupancy"),
                ("change_of_use_fire", "planned change of use/occupancy"),
            ]
        )
    if major_renovation:
        requested.extend(
            [
                ("major_renovation_energy", "major-renovation convention screen"),
                ("major_renovation_fire", "major-renovation convention screen"),
            ]
        )
    if year_built < 1991 and (last_renovation is None or last_renovation < 1991):
        requested.append(("legacy_accessibility", "pre-1991 accessibility vintage"))
    if year_built < 1990 and (last_renovation is None or last_renovation < 1990):
        requested.append(("legacy_fire_system", "pre-1990 fire/life-safety vintage"))
    if floors > 1 and (has_renovation or change_of_use):
        requested.append(("vertical_access", "multi-story planned work/use change"))

    seen: set[str] = set()
    checklist: list[dict[str, Any]] = []
    for trigger_id, trigger in requested:
        if trigger_id not in seen:
            seen.add(trigger_id)
            checklist.append(_exposure_line(trigger_id, trigger, sf, floors))

    low = round(sum(item["exposure_cost_range"]["low"] for item in checklist), 2)
    high = round(sum(item["exposure_cost_range"]["high"] for item in checklist), 2)
    return {
        "report_type": "code_exposure",
        "inputs": {
            "building": {
                "year_built": year_built,
                "type": building_type,
                "sf": sf,
                "floors": floors,
                "last_renovation": last_renovation,
            },
            "planned": {
                "change_of_use": change_of_use,
                "renovation_scope": scope_description,
                "major_renovation_convention_match": major_renovation,
            },
        },
        "triggered_upgrades": checklist,
        "checklist": checklist,
        "trigger_count": len(checklist),
        "gross_exposure_cost_range": {"low": low, "high": high},
        "cost_warning": (
            "Gross line sum is a screening ceiling/ordering aid, not a bid; "
            "scopes may overlap and all pricing requires local GC/design quotes."
        ),
        "jurisdiction_warning": (
            "Thresholds, exceptions, adopted code editions, cost caps, and "
            "enforcement are jurisdiction-dependent; " + VERIFY_LOCAL + "."
        ),
        "input_scope": INPUT_SCOPE,
        "disclaimer": DISCLAIMER,
    }


__all__ = [
    "CODE_TRIGGER_CONVENTIONS",
    "DISCLAIMER",
    "INPUT_SCOPE",
    "VERIFY_LOCAL",
    "ada_code_exposure",
]
