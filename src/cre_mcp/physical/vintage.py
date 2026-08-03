"""Construction-vintage risk conventions for physical diligence.

This module intentionally accepts structured inputs only.  It does not parse a
PCA, infer installed materials, or make code-compliance determinations.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from typing import Any


DISCLAIMER = (
    "Screening conventions only; this output does not replace a licensed PCA, "
    "architect, engineer, environmental professional, or code specialist. "
    "Potential materials and conditions require records review, field inspection, "
    "sampling, and specialist confirmation."
)

STRUCTURED_INPUT_NOTE = (
    "Structured inputs v1 only. PCA PDF parsing and extraction are out of scope; "
    "enter the verified construction year, building type, and state directly."
)

# These labels deliberately mirror the public vocabulary in
# ``cre_mcp.envscreen.hazards.hazard_profile`` without importing its
# network-facing implementation.  A vintage flag is not a site-hazard result.
SEISMIC_VOCABULARY_CROSS_REFERENCE: dict[str, str] = {
    "hazard_key": "seismic",
    "envscreen_result_key": "seismic_design",
    "design_category_key": "seismic_design_category",
    "reference_document": "ASCE 7-22",
    "site_assumption": "Default Site Class D is a screening assumption",
    "required_follow_up": (
        "Pair the vintage screen with envscreen seismic-design results and obtain "
        "site-specific structural and geotechnical evaluation."
    ),
}


SEISMIC_STATES = frozenset(
    {
        "AK",
        "AR",
        "AZ",
        "CA",
        "HI",
        "ID",
        "IL",
        "KY",
        "MO",
        "MT",
        "NM",
        "NV",
        "OK",
        "OR",
        "SC",
        "TN",
        "UT",
        "WA",
        "WY",
    }
)

SOUTHEAST_STATES = frozenset(
    {
        "AL",
        "AR",
        "FL",
        "GA",
        "KY",
        "LA",
        "MS",
        "NC",
        "SC",
        "TN",
        "TX",
        "VA",
        "WV",
    }
)


_STATE_NAMES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


# Public, auditable screening conventions. Bounds are inclusive; ``None`` means
# the rule is construction/geography based rather than age bounded.
VINTAGE_RISK_CONVENTIONS: dict[str, dict[str, Any]] = {
    "asbestos": {
        "title": "Potential asbestos-containing materials",
        "era": "pre-1980",
        "year_min": None,
        "year_max": 1979,
        "why": (
            "Many pre-1980 buildings used asbestos-containing fireproofing, "
            "insulation, flooring, mastics, roofing, or other products; year alone "
            "does not establish presence or absence."
        ),
        "specialist_test": "ACM survey with targeted sampling before disturbance",
        "specialist": "licensed asbestos inspector/environmental consultant",
        "severity": "high",
    },
    "lead_paint": {
        "title": "Potential lead-based paint",
        "era": "pre-1978",
        "year_min": None,
        "year_max": 1977,
        "why": (
            "Lead-based paint may be present in buildings painted before the 1978 "
            "federal consumer-use ban; commercial applicability and actual coatings "
            "must be evaluated in context."
        ),
        "specialist_test": "lead-based-paint inspection/risk assessment and sampling",
        "specialist": "certified lead inspector or risk assessor",
        "severity": "high",
    },
    "fire_sprinkler_legacy": {
        "title": "Legacy fire-sprinkler and life-safety design",
        "era": "pre-1990",
        "year_min": None,
        "year_max": 1989,
        "why": (
            "A pre-1990 original fire-protection design may predate later sprinkler, "
            "alarm, egress, and seismic-bracing standards; current obligations depend "
            "on local adoption, occupancy, alterations, and system records."
        ),
        "specialist_test": (
            "fire/life-safety survey, hydraulic/design review, and inspection/testing "
            "records review"
        ),
        "specialist": "licensed fire-protection engineer",
        "severity": "high",
    },
    "aluminum_wiring": {
        "title": "Potential aluminum branch-circuit wiring",
        "era": "1965-1973",
        "year_min": 1965,
        "year_max": 1973,
        "why": (
            "Solid aluminum branch-circuit wiring was used during this period and "
            "can present connection/overheating concerns if installed or remediated "
            "improperly."
        ),
        "specialist_test": "electrical panel and representative branch-circuit survey",
        "specialist": "licensed electrician or electrical engineer",
        "severity": "high",
    },
    "polybutylene_plumbing": {
        "title": "Potential polybutylene plumbing",
        "era": "1978-1995",
        "year_min": 1978,
        "year_max": 1995,
        "why": (
            "Polybutylene supply piping was installed during this era and can fail at "
            "fittings or after oxidant exposure; construction year does not confirm "
            "pipe material."
        ),
        "specialist_test": "plumbing material survey with concealed-area sampling as needed",
        "specialist": "licensed plumber or plumbing engineer",
        "severity": "high",
    },
    "galvanized_plumbing": {
        "title": "Potential galvanized water piping",
        "era": "pre-1960",
        "year_min": None,
        "year_max": 1959,
        "why": (
            "Older galvanized piping can have internal corrosion, reduced flow, or "
            "leak risk; later partial replacements may leave concealed original runs."
        ),
        "specialist_test": "piping material/condition survey and water-flow testing",
        "specialist": "licensed plumber or plumbing engineer",
        "severity": "medium",
    },
    "eifs_moisture": {
        "title": "Potential barrier-EIFS moisture intrusion",
        "era": "1990-1999",
        "year_min": 1990,
        "year_max": 1999,
        "why": (
            "Some 1990s exterior insulation and finish systems had drainage, sealant, "
            "or detailing vulnerabilities that can conceal moisture damage; the facade "
            "system must first be identified."
        ),
        "specialist_test": "facade probe/moisture survey including flashing and sealants",
        "specialist": "building-envelope architect or engineer",
        "severity": "medium",
    },
    "chinese_drywall": {
        "title": "Potential imported drywall corrosion/indoor-air issue",
        "era": "2001-2009 in Southeast/Gulf states",
        "year_min": 2001,
        "year_max": 2009,
        "why": (
            "Some imported drywall installed during the mid-2000s rebuilding boom, "
            "especially in Southeast/Gulf markets, was associated with sulfur odors "
            "and corrosion; geography and year are screening proxies only."
        ),
        "specialist_test": (
            "drywall origin/marking inspection, corrosion survey, and laboratory "
            "evaluation when indicated"
        ),
        "specialist": "qualified indoor-environmental/building-material consultant",
        "severity": "high",
    },
    "frt_plywood": {
        "title": "Potential fire-retardant-treated plywood degradation",
        "era": "1980-1989 roof construction",
        "year_min": 1980,
        "year_max": 1989,
        "why": (
            "Some 1980s fire-retardant-treated roof sheathing experienced heat-related "
            "strength degradation; building year does not establish roof deck material "
            "or replacement history."
        ),
        "specialist_test": "roof-deck identification, condition survey, and structural testing",
        "specialist": "licensed structural engineer and roofing consultant",
        "severity": "high",
    },
    "unreinforced_masonry": {
        "title": "Potential unreinforced-masonry seismic vulnerability",
        "era": "masonry/brick construction in a seismic-screen state",
        "year_min": None,
        "year_max": None,
        "why": (
            "Unreinforced masonry can have brittle wall, parapet, diaphragm-connection, "
            "and out-of-plane failure modes in earthquakes; a building-type label and "
            "state screen cannot determine reinforcement or site hazard."
        ),
        "specialist_test": (
            "structural seismic evaluation plus site-specific geotechnical/hazard review"
        ),
        "specialist": "licensed structural engineer and geotechnical engineer",
        "severity": "high",
    },
}

# Readable aliases for callers/tests that prefer "table" terminology.
VINTAGE_RISK_TABLE = VINTAGE_RISK_CONVENTIONS
ERA_RISK_TABLE = VINTAGE_RISK_CONVENTIONS


def _normalize_year(year_built: Any) -> int:
    if isinstance(year_built, bool):
        raise TypeError("year_built must be a four-digit integer")
    if isinstance(year_built, float) and not math.isfinite(year_built):
        raise ValueError("year_built must be finite")
    try:
        year = int(year_built)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError("year_built must be a four-digit integer") from exc
    if isinstance(year_built, float) and year_built != year:
        raise ValueError("year_built must be a whole year")
    if isinstance(year_built, str) and year_built.strip() != str(year):
        raise ValueError("year_built must be a four-digit integer")
    if not 1600 <= year <= date.today().year:
        raise ValueError(
            f"year_built must be between 1600 and {date.today().year}"
        )
    return year


def _normalize_building_type(building_type: Any) -> str:
    if not isinstance(building_type, str) or not building_type.strip():
        raise TypeError("building_type must be a non-empty string")
    return " ".join(building_type.strip().casefold().replace("-", " ").split())


def _normalize_state(state: Any) -> str | None:
    if state is None:
        return None
    if not isinstance(state, str) or not state.strip():
        raise TypeError("state must be a two-letter code or state name")
    value = " ".join(state.strip().casefold().replace(".", "").split())
    if value in _STATE_NAMES:
        return _STATE_NAMES[value]
    code = value.upper()
    if len(code) == 2 and code in set(_STATE_NAMES.values()):
        return code
    raise ValueError("state must be a recognized US state or DC")


def _year_matches(year: int, convention: Mapping[str, Any]) -> bool:
    lower = convention.get("year_min")
    upper = convention.get("year_max")
    return (lower is None or year >= int(lower)) and (
        upper is None or year <= int(upper)
    )


def _flag(risk_id: str) -> dict[str, Any]:
    convention = VINTAGE_RISK_CONVENTIONS[risk_id]
    return {
        "risk_id": risk_id,
        "title": convention["title"],
        "era": convention["era"],
        "why": convention["why"],
        "specialist_test": convention["specialist_test"],
        "specialist": convention["specialist"],
        "severity": convention["severity"],
        "basis": "model_estimate",
        "caveat": (
            "Era/type screening flag only; presence, condition, and compliance have "
            "not been observed or professionally determined."
        ),
    }


def vintage_risk_screen(
    year_built: int,
    building_type: str,
    state: str | None = None,
) -> dict[str, Any]:
    """Return deterministic construction-era flags and specialist follow-ups.

    Year ranges in :data:`VINTAGE_RISK_CONVENTIONS` are inclusive.  ``pre-1980``
    therefore means a construction year through 1979.  A flag identifies a
    diligence question, not the presence of a material, defect, or violation.
    """

    year = _normalize_year(year_built)
    normalized_type = _normalize_building_type(building_type)
    state_code = _normalize_state(state)

    ordered_year_rules = (
        "asbestos",
        "lead_paint",
        "fire_sprinkler_legacy",
        "aluminum_wiring",
        "polybutylene_plumbing",
        "galvanized_plumbing",
        "eifs_moisture",
        "chinese_drywall",
        "frt_plywood",
    )
    flags: list[dict[str, Any]] = []
    for risk_id in ordered_year_rules:
        convention = VINTAGE_RISK_CONVENTIONS[risk_id]
        if not _year_matches(year, convention):
            continue
        if risk_id == "chinese_drywall" and state_code not in SOUTHEAST_STATES:
            continue
        flags.append(_flag(risk_id))

    masonry_terms = (
        "unreinforced masonry",
        "urm",
        "brick",
        "masonry",
        "clay tile",
        "adobe",
    )
    is_masonry_candidate = any(term in normalized_type for term in masonry_terms)
    if is_masonry_candidate and state_code in SEISMIC_STATES:
        flags.append(_flag("unreinforced_masonry"))

    limitations = {
        "input_version": "structured_inputs_v1",
        "pca_pdf_parsing": "out_of_scope",
        "materials": (
            "Construction year does not prove that a flagged material was installed "
            "or that an unflagged material is absent."
        ),
        "renovations": (
            "Unknown renovations, replacements, local code history, occupancy, and "
            "maintenance can materially change the result."
        ),
        "geography": (
            "State-level seismic and Southeast/Gulf screens are coarse; use address-"
            "specific hazard, permit, and professional review."
        ),
    }

    return {
        "report_type": "VINTAGE / CONSTRUCTION-TYPE RISK SCREEN",
        "inputs": {
            "year_built": year,
            "building_type": building_type.strip(),
            "state": state_code,
        },
        "flags": flags,
        "flag_count": len(flags),
        "no_flags_note": (
            None
            if flags
            else "No listed era convention matched; this is not evidence of no physical risk."
        ),
        "seismic_cross_reference": dict(SEISMIC_VOCABULARY_CROSS_REFERENCE),
        "structured_input_note": STRUCTURED_INPUT_NOTE,
        "limitations": limitations,
        "disclaimer": DISCLAIMER,
    }


__all__ = [
    "DISCLAIMER",
    "ERA_RISK_TABLE",
    "SEISMIC_STATES",
    "SEISMIC_VOCABULARY_CROSS_REFERENCE",
    "SOUTHEAST_STATES",
    "STRUCTURED_INPUT_NOTE",
    "VINTAGE_RISK_CONVENTIONS",
    "VINTAGE_RISK_TABLE",
    "vintage_risk_screen",
]
