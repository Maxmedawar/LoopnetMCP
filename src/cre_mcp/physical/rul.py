"""Transparent remaining-useful-life conventions for commercial building systems.

The estimates in this module are screening conventions.  They are deliberately
range-based and keep the age/condition arithmetic visible; they are not a
substitute for a property-condition assessment, destructive testing, equipment
records, or a licensed engineer's opinion.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from importlib import import_module
from math import isfinite
from typing import Any


DISCLAIMER = (
    "Screening estimate only; this does not replace a licensed PCA provider or "
    "engineer. Verify condition, installation date, maintenance history, and "
    "replacement scope with qualified local professionals."
)
STRUCTURED_INPUT_NOTE = (
    "Structured inputs v1; PCA PDF parsing is out of scope and no document was "
    "parsed to produce this estimate."
)

_GENERAL_SOURCE_NOTE = (
    "convention: national commercial-building planning range; verify with "
    "manufacturer records and a licensed PCA provider/engineer"
)


def _lifespan(
    low: float,
    high: float,
    capex_system: str,
    description: str,
    *,
    source_note: str = _GENERAL_SOURCE_NOTE,
) -> dict[str, Any]:
    return {
        "low": low,
        "high": high,
        "unit": "years",
        "capex_system": capex_system,
        "description": description,
        "source_note": source_note,
    }


# Exposed so callers can inspect, replace, or version the assumptions instead of
# treating the model's useful-life numbers as measured facts.
LIFESPAN_CONVENTIONS: dict[str, dict[str, Any]] = {
    "roof_generic": _lifespan(15, 30, "roof", "Roof system, assembly unknown"),
    "built_up_roof": _lifespan(20, 30, "roof", "Built-up asphalt roof (BUR)"),
    "modified_bitumen_roof": _lifespan(
        15, 25, "roof", "Modified-bitumen membrane roof"
    ),
    "single_ply_roof": _lifespan(
        15, 25, "roof", "Single-ply membrane roof (TPO, PVC, or EPDM)"
    ),
    "metal_roof": _lifespan(30, 50, "roof", "Commercial metal roof"),
    "asphalt_shingle_roof": _lifespan(
        20, 30, "roof", "Asphalt-shingle roof"
    ),
    "hvac_generic": _lifespan(15, 25, "hvac", "HVAC system, assembly unknown"),
    "rooftop_hvac_unit": _lifespan(
        15, 20, "hvac", "Packaged rooftop HVAC unit (RTU)"
    ),
    "split_hvac_system": _lifespan(
        15, 20, "hvac", "Commercial split HVAC system"
    ),
    "air_handler": _lifespan(15, 25, "hvac", "Air-handling unit"),
    "boiler": _lifespan(20, 35, "hvac", "Commercial heating boiler"),
    "chiller": _lifespan(20, 30, "hvac", "Commercial chiller"),
    "cooling_tower": _lifespan(15, 25, "hvac", "Cooling tower"),
    "plumbing_generic": _lifespan(
        40, 70, "plumbing", "Domestic plumbing distribution, material unknown"
    ),
    "domestic_water_heater": _lifespan(
        10, 20, "plumbing", "Commercial domestic water heater"
    ),
    "electrical_generic": _lifespan(
        30, 50, "electrical", "Electrical distribution, equipment unknown"
    ),
    "elevator": _lifespan(
        20, 30, "elevator", "Elevator controls and major mechanical modernization"
    ),
    "hydraulic_elevator": _lifespan(
        20, 30, "elevator", "Hydraulic elevator modernization cycle"
    ),
    "traction_elevator": _lifespan(
        25, 35, "elevator", "Traction elevator modernization cycle"
    ),
    "paving": _lifespan(15, 25, "paving", "Asphalt paving system"),
    "facade": _lifespan(
        25, 50, "facade", "Facade sealants/coatings and major envelope renewal"
    ),
    "structure": _lifespan(
        50, 100, "structure", "Primary structure, absent a known defect"
    ),
    "fire_alarm": _lifespan(
        10, 20, "fire_life_safety", "Fire-alarm control and initiating system"
    ),
    "fire_sprinkler": _lifespan(
        20, 50, "fire_life_safety", "Fire-sprinkler distribution system"
    ),
    "fire_life_safety_generic": _lifespan(
        10, 25, "fire_life_safety", "Fire/life-safety system, assembly unknown"
    ),
}

# Also expose the broad system names directly for table consumers.  Resolution
# still uses the ``*_generic`` keys so confidence can reflect an unknown
# assembly.
LIFESPAN_CONVENTIONS.update(
    {
        "roof": LIFESPAN_CONVENTIONS["roof_generic"],
        "hvac": LIFESPAN_CONVENTIONS["hvac_generic"],
        "plumbing": LIFESPAN_CONVENTIONS["plumbing_generic"],
        "electrical": LIFESPAN_CONVENTIONS["electrical_generic"],
        "fire_life_safety": LIFESPAN_CONVENTIONS[
            "fire_life_safety_generic"
        ],
    }
)

# Descriptive aliases make the exposed table discoverable under common names.
LIFESPAN_CONVENTION_TABLE = LIFESPAN_CONVENTIONS
SYSTEM_LIFESPAN_CONVENTIONS = LIFESPAN_CONVENTIONS

SYSTEM_ALIASES = {
    "roof": "roof_generic",
    "roofing": "roof_generic",
    "built_up": "built_up_roof",
    "built_up_roofing": "built_up_roof",
    "bur": "built_up_roof",
    "modified_bitumen": "modified_bitumen_roof",
    "mod_bit": "modified_bitumen_roof",
    "single_ply": "single_ply_roof",
    "tpo": "single_ply_roof",
    "pvc": "single_ply_roof",
    "epdm": "single_ply_roof",
    "metal_roofing": "metal_roof",
    "asphalt_shingle": "asphalt_shingle_roof",
    "shingle_roof": "asphalt_shingle_roof",
    "hvac": "hvac_generic",
    "rtu": "rooftop_hvac_unit",
    "rooftop_unit": "rooftop_hvac_unit",
    "packaged_rooftop_unit": "rooftop_hvac_unit",
    "split_system": "split_hvac_system",
    "ahu": "air_handler",
    "plumbing": "plumbing_generic",
    "water_heater": "domestic_water_heater",
    "electrical": "electrical_generic",
    "elevators": "elevator",
    "parking_lot": "paving",
    "asphalt_paving": "paving",
    "building_envelope": "facade",
    "structural": "structure",
    "fire_life_safety": "fire_life_safety_generic",
    "fire/life/safety": "fire_life_safety_generic",
    "sprinkler": "fire_sprinkler",
}

CONDITION_FACTORS: dict[str, tuple[float, float]] = {
    "good": (1.00, 1.15),
    "fair": (0.85, 1.00),
    "poor": (0.45, 0.70),
    "failed": (0.00, 0.00),
}
MAINTENANCE_FACTORS: dict[str, tuple[float, float]] = {
    "excellent": (1.05, 1.10),
    "good": (1.00, 1.05),
    "fair": (0.95, 1.00),
    "poor": (0.80, 0.90),
    "unknown": (0.90, 1.00),
}


def _slug(value: Any) -> str:
    return "_".join(str(value).strip().lower().replace("/", " ").split()).replace(
        "-", "_"
    )


def _resolve_system(system: str) -> tuple[str, dict[str, Any]]:
    if not isinstance(system, str) or not system.strip():
        raise ValueError("system is required")
    key = _slug(system)
    key = SYSTEM_ALIASES.get(key, key)
    if key not in LIFESPAN_CONVENTIONS:
        accepted = sorted(set(LIFESPAN_CONVENTIONS) | set(SYSTEM_ALIASES))
        raise ValueError(f"unknown system {system!r}; expected one of {accepted}")
    return key, LIFESPAN_CONVENTIONS[key]


def _finite_nonnegative(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite non-negative number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite non-negative number") from exc
    if not isfinite(number) or number < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    return number


def _resolve_age(
    install_year_or_age: int | float | Mapping[str, Any],
) -> tuple[float, str, int | None]:
    as_of_year = date.today().year
    if isinstance(install_year_or_age, Mapping):
        has_age = "age_years" in install_year_or_age
        has_year = "install_year" in install_year_or_age
        if has_age == has_year:
            raise ValueError(
                "install_year_or_age mapping must contain exactly one of "
                "'install_year' or 'age_years'"
            )
        if has_age:
            age = _finite_nonnegative(
                install_year_or_age["age_years"], "age_years"
            )
            return age, "age_years", None
        raw_year = _finite_nonnegative(
            install_year_or_age["install_year"], "install_year"
        )
        if not raw_year.is_integer():
            raise ValueError("install_year must be a whole calendar year")
        install_year = int(raw_year)
        if not 1800 <= install_year <= as_of_year:
            raise ValueError(
                f"install_year must be between 1800 and {as_of_year}"
            )
        return float(as_of_year - install_year), "install_year", install_year

    raw = _finite_nonnegative(install_year_or_age, "install_year_or_age")
    if 1800 <= raw <= as_of_year:
        if not raw.is_integer():
            raise ValueError("an install year must be a whole calendar year")
        install_year = int(raw)
        return float(as_of_year - install_year), "install_year", install_year
    if raw > as_of_year:
        raise ValueError(f"install year cannot be later than {as_of_year}")
    return raw, "age_years", None


def replacement_cost_convention(
    system: str,
    *,
    building_sf: float | None = None,
    floors: int = 1,
    extent: float | int | None = None,
) -> dict[str, Any]:
    """Return the matching CapEx cost convention, and a total when quantity exists.

    The lazy import keeps the useful-life convention table independently usable
    while making the cost link consume the single cost table owned by
    :mod:`cre_mcp.physical.capex`.  No replacement total is fabricated when
    ``building_sf`` is absent.
    """
    _, lifespan = _resolve_system(system)
    capex_system = str(lifespan["capex_system"])
    capex = import_module("cre_mcp.physical.capex")
    table = getattr(capex, "CAPEX_COST_CONVENTIONS")
    convention = dict(table[capex_system])
    if building_sf is None:
        return {
            "status": "unit_convention_only",
            "capex_system": capex_system,
            "low": convention["low"],
            "high": convention["high"],
            "unit": convention["unit"],
            "basis": convention["basis"],
            "source_note": convention["source_note"],
            "description": convention.get("description"),
            "quantity_required_for_total": True,
        }
    total = capex.replacement_cost_range(
        capex_system,
        building_sf=building_sf,
        floors=floors,
        extent=extent,
    )
    return {"status": "estimated_total", "capex_system": capex_system, **total}


def _confidence(
    convention_key: str, maintenance_quality: str, interpretation: str
) -> tuple[str, list[str]]:
    limitations: list[str] = []
    if convention_key.endswith("_generic"):
        limitations.append("generic system type; assembly/material is unknown")
    if maintenance_quality == "unknown":
        limitations.append("maintenance quality was not supplied")
    if interpretation == "age_years":
        limitations.append("age was supplied without an installation-year record")
    if not limitations:
        return "high", limitations
    return ("low" if len(limitations) >= 2 else "medium"), limitations


def remaining_useful_life(
    system: str,
    install_year_or_age: int | float | Mapping[str, Any],
    condition: str,
    maintenance_quality: str | None = None,
    *,
    building_sf: float | None = None,
    floors: int = 1,
    extent: float | int | None = None,
) -> dict[str, Any]:
    """Estimate a system's remaining useful life from transparent conventions.

    ``install_year_or_age`` accepts a year (for example ``2012``), an age in
    years (for example ``14``), or an explicit ``{"install_year": 2012}`` /
    ``{"age_years": 14}`` mapping.  The remaining range is the condition- and
    maintenance-adjusted convention lifespan less age, floored at zero.

    Replacement cost is linked to the CapEx module's exposed convention table.
    Without ``building_sf`` the response gives only that table's unit range;
    with it, the CapEx helper computes an estimated total.
    """
    convention_key, convention = _resolve_system(system)
    age, interpretation, install_year = _resolve_age(install_year_or_age)

    condition_key = _slug(condition)
    if condition_key not in CONDITION_FACTORS:
        raise ValueError(
            f"condition must be one of {sorted(CONDITION_FACTORS)}"
        )
    maintenance_key = _slug(maintenance_quality or "unknown")
    if maintenance_key not in MAINTENANCE_FACTORS:
        raise ValueError(
            f"maintenance_quality must be one of {sorted(MAINTENANCE_FACTORS)}"
        )

    condition_low, condition_high = CONDITION_FACTORS[condition_key]
    maintenance_low, maintenance_high = MAINTENANCE_FACTORS[maintenance_key]
    # Condition/maintenance can improve where within the convention range an
    # asset lands, but this screen does not extend life beyond the published
    # upper convention without a professional condition assessment.
    adjusted_life_low = min(
        float(convention["high"]),
        float(convention["low"]) * condition_low * maintenance_low,
    )
    adjusted_life_high = min(
        float(convention["high"]),
        float(convention["high"]) * condition_high * maintenance_high,
    )
    rul_low = max(0.0, adjusted_life_low - age)
    rul_high = max(rul_low, adjusted_life_high - age)
    if condition_key == "failed":
        rul_low = rul_high = 0.0

    confidence, confidence_limitations = _confidence(
        convention_key, maintenance_key, interpretation
    )
    engineer_flags = [
        "licensed PCA provider/engineer must verify remaining useful life",
        "verify installation date and maintenance history from property records",
    ]
    if condition_key in {"poor", "failed"}:
        engineer_flags.append(
            "poor/failed condition requires prompt specialist assessment"
        )
    if age >= float(convention["high"]):
        engineer_flags.append(
            "reported age is at or beyond the unadjusted convention range"
        )
    if convention_key in {"elevator", "hydraulic_elevator", "traction_elevator"}:
        engineer_flags.append(
            "licensed elevator contractor must confirm modernization scope"
        )
    if convention_key == "structure":
        engineer_flags.append(
            "structural engineer must evaluate any distress or known defect"
        )

    rul_range = {"low": round(rul_low, 1), "high": round(rul_high, 1)}
    return {
        "system": _slug(system),
        "matched_convention": convention_key,
        "input_age_years": round(age, 1),
        "input_interpretation": interpretation,
        "install_year": install_year,
        "as_of_year": date.today().year,
        "condition": condition_key,
        "maintenance_quality": maintenance_key,
        "lifespan_convention_years": {
            "low": convention["low"],
            "high": convention["high"],
        },
        "remaining_useful_life_years": rul_range,
        "rul_range_years": dict(rul_range),
        "rul_years": dict(rul_range),
        "calculation": (
            "max(0, min(convention high, convention lifespan x condition "
            "factor x maintenance factor) - age)"
        ),
        "convention_source_note": convention["source_note"],
        "replacement_cost_range": replacement_cost_convention(
            convention_key,
            building_sf=building_sf,
            floors=floors,
            extent=extent,
        ),
        "confidence": confidence,
        "confidence_label": confidence,
        "confidence_limitations": confidence_limitations,
        "engineer_verify": True,
        "engineer_verify_flags": engineer_flags,
        "professional_opinion_needed": True,
        "input_scope_note": STRUCTURED_INPUT_NOTE,
        "disclaimer": DISCLAIMER,
    }


__all__ = [
    "CONDITION_FACTORS",
    "DISCLAIMER",
    "LIFESPAN_CONVENTIONS",
    "LIFESPAN_CONVENTION_TABLE",
    "MAINTENANCE_FACTORS",
    "STRUCTURED_INPUT_NOTE",
    "SYSTEM_LIFESPAN_CONVENTIONS",
    "remaining_useful_life",
    "replacement_cost_convention",
]
