"""Offline, cited registry of major building-energy compliance programs.

This is a screening registry, not a live legal service.  Each entry exposes its
verification date and an official source so a user can re-check amendments,
rules, deadlines, occupancy classifications, and enforcement discretion.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
from typing import Any


REGISTRY_VERIFICATION_NOTE = (
    "Static offline registry; re-verify the cited law and agency guidance before reliance."
)


ENERGY_RULE_REGISTRY: dict[str, dict[str, Any]] = {
    "nyc": {
        "jurisdiction": "New York City, New York",
        "law": "Local Law 97 of 2019 (Building Emissions Law)",
        "program": "NYC Building Emissions Law / LL97",
        "thresholds": {
            "general": "A covered building generally exceeds 25,000 gross square feet.",
            "aggregation": (
                "Two or more buildings on the same tax lot generally are covered when "
                "their combined area exceeds 50,000 square feet; condominium aggregation "
                "has a related over-50,000-square-foot rule."
            ),
            "screen_sf_operator": ">",
            "screen_sf": 25_000,
            "exceptions": "Statutory exceptions and special rules require building-specific review.",
        },
        "cadence": {
            "reporting": "Annual emissions report, generally due May 1 for the prior calendar year.",
            "first_emissions_report": "2025-05-01 for calendar-year 2024 emissions",
            "performance_periods": ["2024-2029", "2030-2034", "2035-2039", "2040 and later"],
        },
        "emissions_caps": {
            "metric": "kg CO2e per square foot per year",
            "shape": "Occupancy-group-specific limits tighten by compliance period.",
            "limit_formula": (
                "annual limit (metric tons CO2e) = sum of each occupancy group's "
                "square feet x applicable kg CO2e/sf cap / 1,000"
            ),
            "warning": (
                "A single building type is not enough to calculate the cap; the legally "
                "recognized occupancy-group area schedule and current emissions factors are required."
            ),
        },
        "penalty_shape": {
            "formula": "max(0, reported annual metric tons CO2e - annual emissions limit) x $268",
            "excess_emissions_rate_dollars_per_metric_ton_co2e": 268,
            "failure_to_report": "$0.50 per covered-building square foot for each month the report is not filed, subject to the law's terms.",
            "false_statement": "Separate criminal/civil consequences may apply; intent and defenses require counsel review.",
        },
        "sources": [
            {
                "label": "NYC Department of Buildings — Local Law 97",
                "citation": "N.Y.C. Admin. Code §§ 28-320.3, 28-320.6.1 and 28-320.6.2",
                "url": "https://www.nyc.gov/site/sustainablebuildings/ll97/local-law-97.page",
            }
        ],
        "last_verified": "2025-02-15",
    },
    "boston": {
        "jurisdiction": "Boston, Massachusetts",
        "law": "Building Emissions Reduction and Disclosure Ordinance (BERDO 2.0)",
        "program": "Boston BERDO",
        "thresholds": {
            "general": "Buildings at least 20,000 square feet or with at least 15 residential units are generally covered.",
            "performance_timing": (
                "Emissions standards begin in 2025 for buildings at least 35,000 square "
                "feet or 35 units and in 2030 for the smaller covered tier."
            ),
            "screen_sf_operator": ">=",
            "screen_sf": 20_000,
            "unit_count_route": 15,
        },
        "cadence": {
            "reporting": "Annual energy and water report, generally due May 15; verification follows the ordinance/rule schedule.",
            "performance": "Five-year emissions-standard steps through carbon neutrality in 2050, subject to approved compliance options.",
        },
        "performance_standard": {
            "metric": "annual kg CO2e per square foot, by building use",
            "shape": "Use-specific emissions standards decline on five-year schedules.",
            "flexibility": "Review boards, individual compliance schedules, renewable-energy options, and alternative compliance payments have rule-specific conditions.",
        },
        "penalty_shape": {
            "formula": "Daily noncompliance penalties are tiered by covered-building size/unit count; alternative compliance payments use an excess-emissions price.",
            "large_building_daily_max_dollars": 1_000,
            "small_covered_building_daily_max_dollars": 300,
            "alternative_compliance_payment_shape": "excess metric tons CO2e x the ordinance/rule payment rate",
        },
        "sources": [
            {
                "label": "City of Boston — BERDO",
                "citation": "Boston Ordinances ch. VII, §§ 7-2.2 through 7-2.9",
                "url": "https://www.boston.gov/departments/environment/building-emissions-reduction-and-disclosure",
            }
        ],
        "last_verified": "2025-02-15",
    },
    "dc": {
        "jurisdiction": "District of Columbia",
        "law": "Clean Energy DC Omnibus Amendment Act — Building Energy Performance Standards",
        "program": "DC BEPS",
        "thresholds": {
            "general": "Private buildings at least 25,000 square feet are within the phased BEPS/benchmarking screen; cycle and ownership rules control actual coverage.",
            "dc_owned": "District-owned buildings have a lower statutory size route.",
            "screen_sf_operator": ">=",
            "screen_sf": 25_000,
            "cycle_warning": "The applicable BEPS period, delay legislation, and agency building list must be checked.",
        },
        "cadence": {
            "benchmarking": "Annual benchmarking, generally due April 1 for prior-year data.",
            "performance": "Multi-year BEPS compliance periods with pathway selection, interim obligations, and end-of-period evaluation.",
        },
        "performance_standard": {
            "metric": "ENERGY STAR score or source EUI standard by property type",
            "shape": "A covered building follows a performance, standard-target, prescriptive, or approved alternative pathway.",
        },
        "penalty_shape": {
            "formula": "Performance penalties are prorated from a statutory maximum based on the building's distance from its pathway target and time out of compliance.",
            "maximum_shape": "up to $10 per square foot, subject to the statutory/program cap and current enforcement rules",
            "benchmarking": "Separate administrative enforcement can apply to missing or inaccurate benchmarking reports.",
        },
        "sources": [
            {
                "label": "DC Department of Energy & Environment — BEPS",
                "citation": "D.C. Code § 6-1451.09; 20 DCMR ch. 35",
                "url": "https://doee.dc.gov/service/building-energy-performance-standards-beps",
            }
        ],
        "last_verified": "2025-02-15",
    },
    "california": {
        "jurisdiction": "California",
        "law": "Assembly Bill 802 Building Energy Benchmarking Program",
        "program": "California AB 802 benchmarking",
        "thresholds": {
            "general": "Covered commercial and multifamily buildings generally exceed 50,000 gross square feet.",
            "accounts": "Residential/mixed-use coverage also depends on the regulatory utility-account criteria.",
            "screen_sf_operator": ">",
            "screen_sf": 50_000,
            "local_rules": "Local benchmarking/performance ordinances may add stricter duties.",
        },
        "cadence": {
            "benchmarking": "Annual report to the California Energy Commission, generally due June 1.",
            "performance": "AB 802 is a statewide benchmarking/disclosure program, not a statewide LL97-style emissions cap.",
        },
        "penalty_shape": {
            "formula": "Administrative/civil enforcement under the statute and benchmarking regulations; no statewide per-ton emissions-fine formula.",
            "warning": "The current CEC enforcement process and any overlapping local ordinance control the actual exposure.",
        },
        "sources": [
            {
                "label": "California Energy Commission — Building Energy Benchmarking Program",
                "citation": "Cal. Pub. Res. Code § 25402.10; 20 CCR §§ 1680-1685",
                "url": "https://www.energy.ca.gov/programs-and-topics/programs/building-energy-benchmarking-program",
            }
        ],
        "last_verified": "2025-02-15",
    },
    "austin": {
        "jurisdiction": "Austin, Texas",
        "law": "Energy Conservation Audit and Disclosure Ordinance",
        "program": "Austin ECAD",
        "thresholds": {
            "general": "Commercial facilities at least 10,000 square feet generally enter the ECAD rating/disclosure screen.",
            "service_territory": "Coverage depends on location/service conditions and statutory exceptions.",
            "screen_sf_operator": ">=",
            "screen_sf": 10_000,
        },
        "cadence": {
            "rating": "Annual commercial energy rating/reporting cycle, generally due June 1 under ECAD guidance.",
            "transaction_disclosure": "Required energy information is disclosed in covered sale transactions on the ordinance timeline.",
        },
        "performance_standard": {
            "shape": "Audit/rating and disclosure program; this registry does not infer a citywide emissions cap from ECAD.",
        },
        "penalty_shape": {
            "formula": "Municipal-code offense/fine structure per violation; no per-ton emissions formula.",
            "warning": "The charged offense, notice, cure, and current municipal maximum require code review.",
        },
        "sources": [
            {
                "label": "City of Austin — ECAD",
                "citation": "Austin City Code ch. 6-7",
                "url": "https://www.austintexas.gov/ecad",
            }
        ],
        "last_verified": "2025-02-15",
    },
    "denver": {
        "jurisdiction": "Denver, Colorado",
        "law": "Energize Denver Ordinance",
        "program": "Energize Denver",
        "thresholds": {
            "performance": "Buildings at least 25,000 square feet generally have benchmarking and EUI performance duties.",
            "prescriptive": "Buildings from 5,000 through 24,999 square feet generally have lighting/renewable-energy prescriptive duties.",
            "screen_sf_operator": ">=",
            "screen_sf": 5_000,
            "performance_screen_sf": 25_000,
        },
        "cadence": {
            "benchmarking": "Annual benchmarking, generally due June 1 for buildings in the benchmarking tier.",
            "performance": "Interim and final target years/pathways culminate in 2030, with schedule adjustments governed by current rules.",
        },
        "performance_standard": {
            "metric": "weather-normalized site EUI by building type",
            "shape": "Covered large buildings reduce EUI to building-type targets through assigned interim/final targets or approved alternate compliance options.",
        },
        "penalty_shape": {
            "formula": "Administrative penalties/alternate compliance payments are shaped by benchmarking failure or quantified performance shortfall under current program rules.",
            "warning": "Target adjustments, timeline changes, electrification credits, and current payment rates must be checked in the building's compliance record.",
        },
        "sources": [
            {
                "label": "City and County of Denver — Energize Denver Hub",
                "citation": "D.R.M.C. §§ 10-400 et seq. and Energize Denver rules",
                "url": "https://www.denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Climate-Action-Sustainability-and-Resiliency/High-Performance-Buildings-and-Homes/Energize-Denver-Hub",
            }
        ],
        "last_verified": "2025-02-15",
    },
}

# Public alias for callers that use the shorter registry name.
ENERGY_RULES = ENERGY_RULE_REGISTRY


JURISDICTION_ALIASES: dict[str, str] = {
    "nyc": "nyc",
    "new york city": "nyc",
    "new york city ny": "nyc",
    "new york ny": "nyc",
    "boston": "boston",
    "boston ma": "boston",
    "dc": "dc",
    "washington dc": "dc",
    "district of columbia": "dc",
    "california": "california",
    "ca": "california",
    "austin": "austin",
    "austin tx": "austin",
    "denver": "denver",
    "denver co": "denver",
}


def _normalized_jurisdiction(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _sf(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("building.sf must be a finite non-negative number")
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("building.sf must be a finite non-negative number") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("building.sf must be a finite non-negative number")
    return result


def _applicability(
    key: str,
    square_feet: Decimal | None,
    building_type: str,
) -> dict[str, Any]:
    if square_feet is None:
        return {
            "status": "UNKNOWN",
            "reason": "Building square footage was not supplied; threshold screening is unavailable.",
            "building_type": building_type or "UNKNOWN",
        }

    applies = False
    tier: str | None = None
    if key in {"boston", "dc", "austin"}:
        applies = square_feet >= Decimal(str(ENERGY_RULE_REGISTRY[key]["thresholds"]["screen_sf"]))
    elif key in {"nyc", "california"}:
        applies = square_feet > Decimal(str(ENERGY_RULE_REGISTRY[key]["thresholds"]["screen_sf"]))
    elif key == "denver":
        applies = square_feet >= Decimal("5000")
        if applies:
            tier = "PERFORMANCE_AND_BENCHMARKING" if square_feet >= Decimal("25000") else "PRESCRIPTIVE_5K_TO_24,999_SF"

    if applies:
        status = "APPLIES_SIZE_SCREEN"
        reason = "Supplied square footage meets the registry's basic size screen."
    else:
        status = "BELOW_SIZE_SCREEN"
        reason = (
            "Supplied square footage does not meet the basic size screen; aggregation, "
            "residential-unit, ownership, use, or local-law routes may still require review."
        )
    return {
        "status": status,
        "reason": reason,
        "sf": int(square_feet) if square_feet == square_feet.to_integral_value() else float(square_feet),
        "building_type": building_type or "UNKNOWN",
        "tier": tier,
        "final_determination": "PROFESSIONAL_VERIFICATION_REQUIRED",
    }


def energy_compliance(
    jurisdiction: str,
    building: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a cited energy-rule screen or an honest ``UNKNOWN`` response."""

    try:
        if not isinstance(jurisdiction, str) or not jurisdiction.strip():
            raise ValueError("jurisdiction must be a non-empty string")
        if building is None or not isinstance(building, Mapping):
            raise ValueError("building must be a mapping")
        normalized = _normalized_jurisdiction(jurisdiction)
        key = JURISDICTION_ALIASES.get(normalized)
        if key is None:
            return {
                "status": "UNKNOWN",
                "jurisdiction": jurisdiction,
                "law": "UNKNOWN",
                "requirements": "UNKNOWN",
                "applicability": {
                    "status": "UNKNOWN",
                    "reason": "Jurisdiction is not in the offline energy-rule registry.",
                },
                "sources": [],
                "source": None,
                "last_verified": None,
                "honesty": (
                    "UNKNOWN — no rule is inferred. Obtain a jurisdiction-specific code "
                    "and agency review before setting a compliance calendar or budget."
                ),
            }

        result = deepcopy(ENERGY_RULE_REGISTRY[key])
        square_feet = _sf(building.get("sf"))
        building_type = str(building.get("type") or "").strip()
        result.update(
            {
                "status": "KNOWN_RULE_SCREEN",
                "registry_key": key,
                "requested_jurisdiction": jurisdiction,
                "building": {
                    "sf": (
                        None
                        if square_feet is None
                        else int(square_feet)
                        if square_feet == square_feet.to_integral_value()
                        else float(square_feet)
                    ),
                    "type": building_type or "UNKNOWN",
                },
                "applicability": _applicability(key, square_feet, building_type),
                "verification_note": REGISTRY_VERIFICATION_NOTE,
                "honesty": (
                    "Jurisdiction-cited screening only. Applicability, exemptions, "
                    "occupancy mix, emissions factors, deadlines, and penalties require "
                    "confirmation against the cited current authority."
                ),
            }
        )
        result["source"] = result["sources"][0]
        result["citation"] = result["source"]["citation"]
        result["requirements"] = {
            "thresholds": result["thresholds"],
            "cadence": result["cadence"],
            "performance_standard": result.get(
                "performance_standard",
                result.get("emissions_caps"),
            ),
        }
        return result
    except Exception as exc:
        return {"error": f"energy_compliance: {exc}"}


__all__ = ["ENERGY_RULE_REGISTRY", "ENERGY_RULES", "energy_compliance"]
