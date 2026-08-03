"""Convert structured physical findings into planning-level CapEx ranges.

This module intentionally uses transparent convention ranges rather than
pretending to produce bids.  It accepts structured-v1 findings only; parsing a
PCA PDF and validating the underlying observations are outside its scope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any


DISCLAIMER = (
    "Planning screen only; this does not replace a licensed PCA provider, "
    "engineer, architect, specialist consultant, or local contractor bids."
)
INPUT_SCOPE_NOTE = (
    "Structured inputs v1 only; PCA PDF parsing and source-document "
    "verification are out of scope."
)
_SOURCE_NOTE = (
    "Convention: national average class-B planning range in current dollars; "
    "verify w/ local GC bids."
)

# Transparent, deliberately broad order-of-magnitude replacement conventions.
# ``low`` and ``high`` are rates in the stated unit, not site-specific quotes.
CAPEX_COST_CONVENTIONS: dict[str, dict[str, str | float]] = {
    "roof": {
        "low": 8.0,
        "high": 18.0,
        "unit": "USD/roof_sf",
        "basis": "roof_area_sf",
        "description": "Commercial roof membrane replacement, including ordinary tear-off.",
        "source_note": _SOURCE_NOTE,
    },
    "hvac": {
        "low": 12.0,
        "high": 30.0,
        "unit": "USD/building_sf",
        "basis": "building_sf",
        "description": "Distributed class-B HVAC replacement allowance.",
        "source_note": _SOURCE_NOTE,
    },
    "plumbing": {
        "low": 8.0,
        "high": 24.0,
        "unit": "USD/affected_sf",
        "basis": "affected_sf",
        "description": "Commercial plumbing replacement or substantial rehabilitation.",
        "source_note": _SOURCE_NOTE,
    },
    "electrical": {
        "low": 7.0,
        "high": 20.0,
        "unit": "USD/affected_sf",
        "basis": "affected_sf",
        "description": "Commercial electrical distribution modernization allowance.",
        "source_note": _SOURCE_NOTE,
    },
    "elevator": {
        "low": 175_000.0,
        "high": 350_000.0,
        "unit": "USD/elevator",
        "basis": "elevator_count",
        "description": "Full elevator modernization per cab/controller system.",
        "source_note": _SOURCE_NOTE,
    },
    "paving": {
        "low": 4.0,
        "high": 10.0,
        "unit": "USD/affected_sf",
        "basis": "affected_sf",
        "description": "Parking and drive-area mill/overlay or replacement allowance.",
        "source_note": _SOURCE_NOTE,
    },
    "facade": {
        "low": 12.0,
        "high": 45.0,
        "unit": "USD/affected_sf",
        "basis": "affected_sf",
        "description": "Facade repair and envelope rehabilitation allowance.",
        "source_note": _SOURCE_NOTE,
    },
    "structure": {
        "low": 25.0,
        "high": 100.0,
        "unit": "USD/affected_sf",
        "basis": "affected_sf",
        "description": "Planning allowance for structural repair; scope varies materially.",
        "source_note": _SOURCE_NOTE,
    },
    "ada": {
        "low": 4.0,
        "high": 16.0,
        "unit": "USD/affected_sf",
        "basis": "affected_sf",
        "description": "Accessibility path, restroom, signage, and hardware allowance.",
        "source_note": _SOURCE_NOTE,
    },
    "fire_life_safety": {
        "low": 3.0,
        "high": 12.0,
        "unit": "USD/affected_sf",
        "basis": "affected_sf",
        "description": "Fire alarm, sprinkler, egress, and life-safety upgrade allowance.",
        "source_note": _SOURCE_NOTE,
    },
}

# Friendly alias for callers that use the generic table name.
COST_CONVENTION_TABLE = CAPEX_COST_CONVENTIONS

_CONDITION_BUCKET = {
    "failed": "immediate",
    "poor": "yr-1",
    "fair": "yr-5",
    "good": "yr-10",
}
_SEVERITY = {
    "failed": "critical",
    "poor": "high",
    "fair": "medium",
    "good": "low",
}
_ENGINEER_SYSTEMS = {
    "electrical",
    "elevator",
    "facade",
    "structure",
    "fire_life_safety",
}


def _finite_number(name: str, value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be a finite {qualifier} number")
    return number


def _positive_floors(value: Any) -> int:
    number = _finite_number("building.floors", value, positive=True)
    if not number.is_integer():
        raise ValueError("building.floors must be a positive integer")
    return int(number)


def _normalize_system(system: Any) -> str:
    if not isinstance(system, str) or not system.strip():
        raise ValueError("finding.system is required")
    normalized = system.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in CAPEX_COST_CONVENTIONS:
        raise ValueError(
            "finding.system must be one of "
            f"{sorted(CAPEX_COST_CONVENTIONS)}"
        )
    return normalized


def _extent_quantity(
    *,
    system: str,
    basis: str,
    building_sf: float,
    floors: int,
    extent: Any,
) -> tuple[float, str]:
    """Return quantity and an explicit explanation of any proxy used."""

    base = building_sf / floors if basis == "roof_area_sf" else building_sf
    base_label = (
        "roof-area proxy = building sf / floors"
        if basis == "roof_area_sf"
        else "building sf proxy"
    )
    if basis == "elevator_count":
        if extent is None:
            return 1.0, "one-cab proxy; actual elevator count was not supplied"
        if isinstance(extent, Mapping):
            extent = extent.get("units", extent.get("count"))
        count = _finite_number("finding.extent", extent, positive=True)
        if not count.is_integer():
            raise ValueError("elevator extent must be a positive whole-unit count")
        return count, "extent supplied as elevator count"

    if extent is None:
        return base, base_label
    if isinstance(extent, Mapping):
        if "fraction" in extent:
            fraction = _finite_number(
                "finding.extent.fraction", extent["fraction"], positive=True
            )
            if fraction > 1:
                raise ValueError("finding.extent.fraction must be between 0 and 1")
            return base * fraction, f"extent {fraction:.2%} x {base_label}"
        elif "sf" in extent:
            affected = _finite_number(
                "finding.extent.sf", extent["sf"], positive=True
            )
            return affected, "extent supplied as affected sf"
        else:
            raise ValueError("finding.extent mapping needs fraction or sf")
    if isinstance(extent, str):
        label = extent.strip().lower()
        named = {"full": 1.0, "all": 1.0, "partial": 0.5, "localized": 0.1}
        if label.endswith("%"):
            fraction = _finite_number(
                "finding.extent", label[:-1], positive=True
            ) / 100.0
            if fraction > 1:
                raise ValueError("percentage finding.extent cannot exceed 100%")
            return base * fraction, f"extent {fraction:.2%} x {base_label}"
        elif label in named:
            extent = named[label]
    amount = _finite_number("finding.extent", extent, positive=True)
    if amount <= 1:
        return base * amount, f"extent {amount:.2%} x {base_label}"
    return amount, "extent supplied as affected sf"


def replacement_cost_range(
    system: str,
    *,
    building_sf: float,
    floors: int = 1,
    extent: Any = None,
) -> dict[str, Any]:
    """Estimate a full-scope replacement range from the exposed convention.

    For square-foot systems, numeric extent greater than 0 through 1 means the affected
    fraction; values above 1 mean actual affected square feet.  Elevator extent
    is a whole-unit count.  Roof area defaults to building SF divided by floors.
    """

    normalized = _normalize_system(system)
    sf = _finite_number("building_sf", building_sf, positive=True)
    floor_count = _positive_floors(floors)
    convention = CAPEX_COST_CONVENTIONS[normalized]
    quantity, quantity_note = _extent_quantity(
        system=normalized,
        basis=str(convention["basis"]),
        building_sf=sf,
        floors=floor_count,
        extent=extent,
    )
    low = round(quantity * float(convention["low"]), 2)
    high = round(quantity * float(convention["high"]), 2)
    return {
        "low": low,
        "high": high,
        "quantity": round(quantity, 2),
        "quantity_unit": "elevators" if normalized == "elevator" else "sf",
        "unit": convention["unit"],
        "rate_range": {
            "low": float(convention["low"]),
            "high": float(convention["high"]),
            "unit": convention["unit"],
        },
        "basis": convention["basis"],
        "quantity_note": quantity_note,
        "source_note": convention["source_note"],
        "input_scope_note": INPUT_SCOPE_NOTE,
        "disclaimer": DISCLAIMER,
    }


def findings_to_capex(
    findings: Sequence[Mapping[str, Any]],
    building: Mapping[str, Any],
) -> dict[str, Any]:
    """Bucket structured findings and estimate transparent CapEx ranges."""

    if isinstance(findings, (str, bytes)) or not isinstance(findings, Sequence):
        raise ValueError("findings must be a list of dictionaries")
    if not isinstance(building, Mapping):
        raise ValueError("building must be a dictionary")
    sf = _finite_number("building.sf", building.get("sf"), positive=True)
    floors = _positive_floors(building.get("floors", 1))
    building_type = building.get("type")
    if not isinstance(building_type, str) or not building_type.strip():
        raise ValueError("building.type is required")

    buckets: dict[str, dict[str, Any]] = {
        name: {"items": [], "line_items": [], "cost_range": {"low": 0.0, "high": 0.0}}
        for name in ("immediate", "yr-1", "yr-5", "yr-10")
    }
    for index, raw in enumerate(findings):
        if not isinstance(raw, Mapping):
            raise ValueError(f"findings[{index}] must be a dictionary")
        system = _normalize_system(raw.get("system"))
        condition_raw = raw.get("condition")
        if not isinstance(condition_raw, str):
            raise ValueError(f"findings[{index}].condition is required")
        condition = condition_raw.strip().lower()
        if condition not in _CONDITION_BUCKET:
            raise ValueError(
                f"findings[{index}].condition must be one of {sorted(_CONDITION_BUCKET)}"
            )
        age = raw.get("age_years")
        if age is not None:
            age = _finite_number(f"findings[{index}].age_years", age)
        notes = raw.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ValueError(f"findings[{index}].notes must be a string")

        cost = replacement_cost_range(
            system,
            building_sf=sf,
            floors=floors,
            extent=raw.get("extent"),
        )
        bucket_name = _CONDITION_BUCKET[condition]
        verify_reasons: list[str] = []
        if system in _ENGINEER_SYSTEMS:
            verify_reasons.append("system scope requires specialist review")
        if condition in {"poor", "failed"}:
            verify_reasons.append("poor/failed condition requires field verification")
        if raw.get("extent") is None:
            verify_reasons.append("quantity uses a building-data proxy")
        line = {
            "finding_index": index,
            "system": system,
            "condition": condition,
            "age_years": age,
            "extent": raw.get("extent"),
            "notes": notes,
            "bucket": bucket_name,
            "severity": _SEVERITY[condition],
            "cost_range": {"low": cost["low"], "high": cost["high"]},
            "cost_basis": {
                key: cost[key]
                for key in ("quantity", "quantity_unit", "rate_range", "basis", "quantity_note")
            },
            "source_note": cost["source_note"],
            "engineer_verify": bool(verify_reasons),
            "engineer_verify_reasons": verify_reasons,
            "tag": "model_estimate",
        }
        bucket = buckets[bucket_name]
        bucket["items"].append(line)
        # Same objects under both names keep compatibility without divergent data.
        bucket["line_items"] = bucket["items"]
        bucket["cost_range"] = {
            "low": round(bucket["cost_range"]["low"] + cost["low"], 2),
            "high": round(bucket["cost_range"]["high"] + cost["high"], 2),
        }

    total = {
        "low": round(sum(bucket["cost_range"]["low"] for bucket in buckets.values()), 2),
        "high": round(sum(bucket["cost_range"]["high"] for bucket in buckets.values()), 2),
    }
    reserve = {
        "low": round(total["low"] / sf / 10.0, 2),
        "high": round(total["high"] / sf / 10.0, 2),
    }
    result: dict[str, Any] = {
        "report_type": "physical_capex_screen",
        "building": {"sf": sf, "floors": floors, "type": building_type.strip()},
        "buckets": buckets,
        "total_cost_range": total,
        "reserve_per_sf_recommendation": reserve,
        "reserve_basis": (
            "smoothed annual USD/building sf over a 10-year planning horizon; "
            "not a funded reserve study"
        ),
        "near_term_funding_warning": (
            "Immediate and yr-1 work must be funded on its stated schedule; the "
            "smoothed reserve/SF figure must not be used to defer near-term work."
        ),
        "input_scope_note": INPUT_SCOPE_NOTE,
        "disclaimer": DISCLAIMER,
    }
    # Intuitive top-level bucket aliases for direct callers.
    result.update(buckets)
    return result


__all__ = [
    "CAPEX_COST_CONVENTIONS",
    "COST_CONVENTION_TABLE",
    "DISCLAIMER",
    "INPUT_SCOPE_NOTE",
    "findings_to_capex",
    "replacement_cost_range",
]
