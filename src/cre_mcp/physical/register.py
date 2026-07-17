"""Assemble physical-diligence outputs into a decision-oriented risk register.

The register deliberately separates what was observed from model estimates and
items that need a licensed professional.  It is an organizing screen, not a
Property Condition Assessment (PCA), code opinion, or engineering report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any


DISCLAIMER = (
    "Screening output only; it does not replace a licensed PCA provider, "
    "architect, code professional, contractor, or engineer."
)
INPUT_SCOPE = (
    "Structured inputs v1 only. PCA PDF parsing and source-document "
    "verification are out of scope."
)

REGISTER_TAGS = {
    "observed_fact",
    "model_estimate",
    "professional_opinion_needed",
}

SEVERITY_WEIGHTS = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "moderate": 3,
    "low": 2,
    "informational": 1,
    "unknown": 1,
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number >= 0 else None


def _range(value: Any) -> dict[str, float] | None:
    """Normalize the common range shapes emitted by the physical modules."""

    if not isinstance(value, Mapping):
        return None
    low = _number(value.get("low", value.get("min")))
    high = _number(value.get("high", value.get("max")))
    if low is None and high is None:
        return None
    low = high if low is None else low
    high = low if high is None else high
    assert low is not None and high is not None
    if low > high:
        low, high = high, low
    return {"low": round(low, 2), "high": round(high, 2)}


def _cost_range(entry: Mapping[str, Any]) -> dict[str, float] | None:
    for key in (
        "cost_range",
        "estimated_cost_range",
        "replacement_cost_range",
        "exposure_cost_range",
    ):
        candidate = entry.get(key)
        # A RUL result without a building quantity exposes the shared unit-rate
        # convention.  That $/sf or $/unit range is not a project total and must
        # not be ranked as though it were one.
        if (
            key == "replacement_cost_range"
            and isinstance(candidate, Mapping)
            and candidate.get("status") == "unit_convention_only"
        ):
            continue
        normalized = _range(candidate)
        if normalized is not None:
            return normalized
    low = entry.get("cost_low", entry.get("low_cost"))
    high = entry.get("cost_high", entry.get("high_cost"))
    return _range({"low": low, "high": high})


def _severity(entry: Mapping[str, Any]) -> str:
    supplied = str(entry.get("severity") or "").strip().casefold()
    if supplied in SEVERITY_WEIGHTS:
        return supplied
    condition = str(entry.get("condition") or "").strip().casefold()
    return {
        "failed": "critical",
        "poor": "high",
        "fair": "medium",
        "good": "low",
    }.get(condition, "medium")


def _needs_professional(entry: Mapping[str, Any], source: str) -> bool:
    if entry.get("engineer_verify") is True:
        return True
    if entry.get("professional_verification_required") is True:
        return True
    if entry.get("specialist") or entry.get("specialist_test"):
        return True
    if entry.get("verify_with") or entry.get("verification"):
        return True
    return source in {"vintage", "code_exposure"}


def _tag(entry: Mapping[str, Any], source: str) -> str:
    supplied_tags: list[str] = []
    for key in ("tag", "classification", "basis", "evidence_type"):
        supplied = str(entry.get(key) or "").strip().casefold()
        if supplied in REGISTER_TAGS:
            supplied_tags.append(supplied)
    if "professional_opinion_needed" in supplied_tags:
        return "professional_opinion_needed"
    if _needs_professional(entry, source):
        return "professional_opinion_needed"
    if supplied_tags:
        return supplied_tags[0]
    if entry.get("observed") is True or entry.get("observed_fact") is True:
        return "observed_fact"
    return "model_estimate"


def _description(entry: Mapping[str, Any]) -> str:
    for key in ("description", "title", "finding", "system", "risk_id", "upgrade"):
        value = entry.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "Physical diligence item"


def _looks_like_row(value: Mapping[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "description",
            "title",
            "finding",
            "system",
            "risk_id",
            "upgrade",
            "rul_range_years",
            "remaining_useful_life_years",
        )
    )


def _flatten(value: Any, source: str = "unspecified") -> list[tuple[str, dict[str, Any]]]:
    """Accept direct rows as well as outputs from capex/RUL/vintage/code modules."""

    rows: list[tuple[str, dict[str, Any]]] = []
    if isinstance(value, Mapping):
        source_here = str(value.get("source_module") or value.get("report_type") or source)

        buckets = value.get("buckets")
        if isinstance(buckets, Mapping):
            for bucket_name, bucket in buckets.items():
                if isinstance(bucket, Mapping):
                    items = bucket.get("line_items", bucket.get("items", bucket.get("findings", [])))
                else:
                    items = bucket
                for child_source, item in _flatten(items, "capex"):
                    item.setdefault("timing_bucket", str(bucket_name))
                    rows.append((child_source, item))
            return rows

        for key, child_source in (
            ("flags", "vintage"),
            ("triggered_upgrades", "code_exposure"),
            ("checklist", "code_exposure"),
            ("exposures", "code_exposure"),
            ("rows", "register"),
        ):
            child = value.get(key)
            if isinstance(child, Sequence) and not isinstance(child, (str, bytes)):
                rows.extend(_flatten(child, child_source))
                return rows

        if _looks_like_row(value):
            rows.append((source_here, dict(value)))
            return rows

        # A mapping of named module outputs is also a valid structured-v1 input.
        for key, child in value.items():
            if isinstance(child, (Mapping, list, tuple)):
                rows.extend(_flatten(child, str(key)))
        return rows

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            rows.extend(_flatten(child, source))
        return rows
    raise ValueError("entries must contain dictionaries or lists of dictionaries")


def physical_risk_register(
    entries: list[dict[str, Any]] | dict[str, Any] | str | None,
    deal_id: str | list[dict[str, Any]] | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one register, ranked by severity multiplied by upper-range cost.

    ``entries`` may contain direct rows or whole results from the capex, RUL,
    vintage, and code-exposure modules.  Classification is conservative:
    anything with an engineer/specialist/code-verification flag is labeled
    ``professional_opinion_needed``.
    """

    # Canonical order is (entries, deal_id=None), but accept the mission-spec's
    # shorthand positional order (deal_id, entries) as well.
    if isinstance(entries, str) and isinstance(deal_id, (list, dict)):
        entries, deal_id = deal_id, entries
    elif entries is None and isinstance(deal_id, (list, dict)):
        entries, deal_id = deal_id, None

    if deal_id is not None and (not isinstance(deal_id, str) or not deal_id.strip()):
        raise ValueError("deal_id must be a non-empty string when provided")
    if not isinstance(entries, (list, dict)):
        raise ValueError("entries must be a list or dictionary")

    flattened = _flatten(entries)
    register: list[dict[str, Any]] = []
    for index, (source, entry) in enumerate(flattened, start=1):
        severity = _severity(entry)
        cost = _cost_range(entry)
        severity_weight = SEVERITY_WEIGHTS[severity]
        high_cost = cost["high"] if cost else 0.0
        # Unknown-dollar items still sort by severity; dollars break ties and
        # elevate expensive items within a severity class.
        priority_score = severity_weight * max(high_cost, 1.0)
        tag = _tag(entry, source)
        register.append(
            {
                "row_id": f"PHYS-{index:03d}",
                "source_module": source,
                "description": _description(entry),
                "severity": severity,
                "cost_range": cost,
                "tag": tag,
                "priority_score": round(priority_score, 2),
                "timing_bucket": entry.get("timing_bucket", entry.get("bucket")),
                "system": entry.get("system"),
                "why": entry.get("why", entry.get("rationale")),
                "recommended_action": entry.get(
                    "recommended_action",
                    entry.get("specialist_test", entry.get("verification")),
                ),
                "source_detail": entry,
            }
        )

    register.sort(
        key=lambda row: (
            row["priority_score"],
            SEVERITY_WEIGHTS[row["severity"]],
            (row["cost_range"] or {}).get("high", 0.0),
        ),
        reverse=True,
    )
    tag_counts = {tag: 0 for tag in sorted(REGISTER_TAGS)}
    for row in register:
        tag_counts[row["tag"]] += 1

    return {
        "report_type": "physical_risk_register",
        "deal_id": deal_id.strip() if deal_id else None,
        "rows": register,
        "row_count": len(register),
        "tag_counts": tag_counts,
        "sort_method": "descending severity weight × upper-bound cost; severity used when cost is unknown",
        "input_scope": INPUT_SCOPE,
        "disclaimer": DISCLAIMER,
    }


__all__ = [
    "DISCLAIMER",
    "INPUT_SCOPE",
    "REGISTER_TAGS",
    "SEVERITY_WEIGHTS",
    "physical_risk_register",
]
