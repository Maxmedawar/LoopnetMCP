"""Convention-based Phase II ESA scope organizer for supplied Phase I RECs."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


CONSULTANT_DISCLAIMER = "licensed environmental consultant must scope/perform"
COST_CONVENTION = (
    "Screening-level 2026 USD convention ranges for initial investigation only; "
    "they are not bids and exclude access, permitting, waste disposal, delineation, "
    "remediation, litigation support, and unusual drilling conditions."
)

_REC_RULES: dict[str, dict[str, Any]] = {
    "ust": {
        "terms": (
            "ust",
            "underground storage tank",
            "petroleum tank",
            "fuel tank",
            "gas station",
            "service station",
        ),
        "scope_elements": (
            "Advance soil borings near the suspected UST basin, including hydraulically downgradient locations.",
            "Collect depth-discrete soil samples for petroleum constituents selected by the consultant.",
            "Evaluate whether temporary or permanent groundwater points are warranted based on field conditions.",
        ),
        "cost_range_usd": {"low": 12_000, "high": 35_000},
    },
    "dry_cleaner": {
        "terms": (
            "dry cleaner",
            "dry cleaning",
            "perc",
            "pce",
            "tetrachloroethylene",
            "chlorinated solvent",
            "vapor intrusion",
        ),
        "scope_elements": (
            "Advance soil borings near former/current dry-cleaning equipment, drains, and chemical-storage areas.",
            "Install sub-slab vapor pins and collect vapor samples on a consultant-designed grid.",
            "Analyze the appropriate soil/vapor media for chlorinated solvents and evaluate vapor-intrusion pathways.",
        ),
        "cost_range_usd": {"low": 20_000, "high": 50_000},
    },
    "groundwater": {
        "terms": (
            "groundwater",
            "ground water",
            "plume",
            "downgradient",
            "offsite release",
            "off-site release",
        ),
        "scope_elements": (
            "Install groundwater wells at consultant-selected upgradient and downgradient locations.",
            "Survey groundwater elevations and infer the local gradient without assuming regional flow direction.",
            "Sample wells for contaminants tied to the documented REC and establish data-quality controls.",
        ),
        "cost_range_usd": {"low": 25_000, "high": 70_000},
    },
}


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _rule_for(finding: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    text = " ".join(
        _normalized(finding.get(key))
        for key in ("rec_type", "location", "medium", "description", "desc")
    )
    for key, rule in _REC_RULES.items():
        if any(_normalized(term) in text for term in rule["terms"]):
            return key, rule
    return None


def phase2_scope(
    phase1_findings: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Map structured REC descriptions to conventional investigation elements."""

    if phase1_findings is None:
        phase1_findings = []
    if isinstance(phase1_findings, (str, bytes)) or not isinstance(
        phase1_findings, Sequence
    ):
        raise TypeError("phase1_findings must be a sequence")
    scope_items: list[dict[str, Any]] = []
    unknown_rec_types: list[dict[str, Any]] = []
    total_low = 0
    total_high = 0
    for index, finding in enumerate(phase1_findings):
        if not isinstance(finding, Mapping):
            raise TypeError("each Phase I finding must be a mapping")
        rec_type = str(finding.get("rec_type") or "").strip()
        if not rec_type:
            raise ValueError("each Phase I finding needs rec_type")
        location = finding.get("location")
        medium = finding.get("medium")
        resolved = _rule_for(finding)
        if resolved is None:
            unknown_rec_types.append(
                {
                    "index": index,
                    "rec_type": rec_type,
                    "location": location,
                    "medium": medium,
                    "status": "UNKNOWN_SCOPE",
                    "reason": "No standard scope convention is registered for this REC description.",
                }
            )
            continue
        rule_key, rule = resolved
        cost = dict(rule["cost_range_usd"])
        total_low += int(cost["low"])
        total_high += int(cost["high"])
        scope_items.append(
            {
                "index": index,
                "rec_type": rec_type,
                "location": location,
                "medium": medium,
                "scope_convention": rule_key,
                "scope_elements": list(rule["scope_elements"]),
                "cost_range_usd": cost,
                "status": "CONSULTANT_SCOPING_REQUIRED",
                "professional_requirement": CONSULTANT_DISCLAIMER,
            }
        )
    return {
        "status": "SCOPE_CONVENTIONS_ASSEMBLED" if scope_items else "NO_STANDARD_SCOPE_ASSEMBLED",
        "scope_items": scope_items,
        "unknown_rec_types": unknown_rec_types,
        "aggregate_cost_range_usd": (
            {"low": total_low, "high": total_high} if scope_items else None
        ),
        "cost_convention": COST_CONVENTION,
        "disclaimer": CONSULTANT_DISCLAIMER,
        "limitations": (
            "Scope elements are starting conventions only. The Phase I report, conceptual "
            "site model, access, utilities, geology, regulatory program, and consultant judgment control."
        ),
    }


__all__ = ["CONSULTANT_DISCLAIMER", "COST_CONVENTION", "phase2_scope"]
