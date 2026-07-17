"""Transparent, uncalibrated micro-location screening heuristic.

The score in this module is deliberately simple.  It uses only supplied site
observations and supplied nearby-anchor enrichment; it does not infer facts
from imagery, call a network service, or claim a relationship to property
performance.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.enrichment.nearby import classify_anchor

CALIBRATION_LABEL = "UNCALIBRATED"

# Points sum to 100.  These are screening conventions, not fitted coefficients.
FACTOR_WEIGHTS: dict[str, int] = {
    "corner": 15,
    "frontage_ft": 20,
    "signalized_intersection": 15,
    "ingress_egress_count": 20,
    "median_break": 10,
    "visibility_notes": 10,
    "nearby_anchors": 10,
}

_SITE_FIELDS = frozenset(
    {
        "corner",
        "frontage_ft",
        "signalized_intersection",
        "ingress_egress_count",
        "median_break",
        "visibility_notes",
    }
)
_ANCHOR_SUMMARY_FIELDS = frozenset(
    {
        "anchor_count",
        "complementary",
        "competitors",
        "brands",
        "summary",
    }
)
_POSITIVE_VISIBILITY_CUES = frozenset(
    {
        "clear",
        "excellent",
        "good",
        "high",
        "prominent",
        "pylon",
        "signage",
        "unobstructed",
        "visible",
    }
)
_NEGATIVE_VISIBILITY_CUES = frozenset(
    {
        "blocked",
        "hidden",
        "limited",
        "low",
        "none",
        "obscured",
        "poor",
    }
)


def _error(message: str, unrecognized_inputs: Sequence[str] = ()) -> dict[str, Any]:
    """Return the repository's data boundary shape for invalid input."""
    return {
        "error": message,
        "calibration": CALIBRATION_LABEL,
        "unrecognized_inputs": sorted(set(unrecognized_inputs)),
    }


def _number(
    site: Mapping[str, Any],
    field: str,
) -> tuple[float | None, str | None]:
    raw = site.get(field)
    if raw is None:
        return None, None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, f"site.{field} must be a non-negative finite number or null"
    parsed = float(raw)
    if not math.isfinite(parsed) or parsed < 0:
        return None, f"site.{field} must be a non-negative finite number or null"
    return parsed, None


def _boolean(
    site: Mapping[str, Any],
    field: str,
) -> tuple[bool | None, str | None]:
    raw = site.get(field)
    if raw is None:
        return None, None
    if not isinstance(raw, bool):
        return None, f"site.{field} must be a boolean or null"
    return raw, None


def _visibility_score(notes: str) -> tuple[float, str]:
    tokens = set(re.findall(r"[a-z]+", notes.casefold()))
    positive = sorted(tokens & _POSITIVE_VISIBILITY_CUES)
    negative = sorted(tokens & _NEGATIVE_VISIBILITY_CUES)
    normalized_notes = " ".join(re.findall(r"[a-z]+", notes.casefold()))
    negative_phrases = sorted(
        phrase
        for phrase in ("no signage", "no visibility", "not clear", "not visible")
        if phrase in normalized_notes
    )
    if negative_phrases:
        negative.extend(negative_phrases)
        # Negated positive words are not evidence on both sides of the heuristic.
        positive = [
            cue
            for cue in positive
            if not any(cue in phrase.split() for phrase in negative_phrases)
        ]
    if positive and not negative:
        return 1.0, f"positive supplied-note cues: {', '.join(positive)}"
    if negative and not positive:
        return 0.0, f"negative supplied-note cues: {', '.join(negative)}"
    if positive and negative:
        return (
            0.5,
            "mixed supplied-note cues: "
            f"positive {', '.join(positive)}; negative {', '.join(negative)}",
        )
    return 0.5, "notes supplied but no convention cue matched; neutral credit"


def _anchor_observation(
    nearby_anchors: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> tuple[int | None, str, list[str], str | None]:
    """Normalize either trade_area_anchors output or nearby POI output."""
    if nearby_anchors is None:
        return None, "nearby-anchor enrichment was not supplied", [], None

    if isinstance(nearby_anchors, Mapping):
        unrecognized = [
            f"nearby_anchors.{key}"
            for key in nearby_anchors
            if key not in _ANCHOR_SUMMARY_FIELDS
        ]
        raw_count = nearby_anchors.get("anchor_count")
        if raw_count is not None:
            if (
                isinstance(raw_count, bool)
                or not isinstance(raw_count, (int, float))
                or not math.isfinite(float(raw_count))
                or float(raw_count) < 0
                or not float(raw_count).is_integer()
            ):
                return (
                    None,
                    "invalid upstream anchor_count",
                    unrecognized,
                    "nearby_anchors.anchor_count must be a non-negative integer or null",
                )
            return (
                int(raw_count),
                "anchor_count supplied by enrichment-compatible summary",
                unrecognized,
                None,
            )

        complementary = nearby_anchors.get("complementary")
        if complementary is not None:
            if isinstance(complementary, (str, bytes)) or not isinstance(
                complementary, Sequence
            ):
                return (
                    None,
                    "invalid complementary-anchor collection",
                    unrecognized,
                    "nearby_anchors.complementary must be a sequence or null",
                )
            return (
                len(complementary),
                "count of supplied complementary anchors",
                unrecognized,
                None,
            )
        return None, "summary supplied without an anchor count", unrecognized, None

    if isinstance(nearby_anchors, (str, bytes)) or not isinstance(
        nearby_anchors, Sequence
    ):
        return (
            None,
            "invalid nearby-anchor input",
            [],
            "nearby_anchors must be an enrichment summary, a POI sequence, or null",
        )

    count = 0
    for index, poi in enumerate(nearby_anchors):
        if not isinstance(poi, Mapping):
            return (
                None,
                "invalid nearby POI",
                [],
                f"nearby_anchors[{index}] must be a mapping",
            )
        if classify_anchor(dict(poi)) == "complementary_anchor":
            count += 1
    return (
        count,
        "supplied POIs classified with cre_mcp.enrichment.nearby.classify_anchor",
        [],
        None,
    )


def micro_location_score(
    site: Mapping[str, Any] | None,
    nearby_anchors: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score a site's observable micro-location factors on a 0--100 convention.

    Missing factors earn zero in ``score_100`` and remain explicit.  The
    separately reported ``available_factor_score_100`` normalizes only across
    supplied factors so consumers cannot confuse missing evidence with observed
    weakness.  Neither score is calibrated to rents, sales, visits, or returns.
    """
    if site is None:
        site = {}
    if not isinstance(site, Mapping):
        return _error("site must be a mapping or null")

    unrecognized_inputs = [
        f"site.{key}" for key in site if key not in _SITE_FIELDS
    ]

    observations: dict[str, tuple[Any, float | None, str]] = {}
    for field in ("corner", "signalized_intersection", "median_break"):
        value, issue = _boolean(site, field)
        if issue:
            return _error(issue, unrecognized_inputs)
        observations[field] = (
            value,
            None if value is None else float(value),
            "full credit when true; zero when false",
        )

    frontage, issue = _number(site, "frontage_ft")
    if issue:
        return _error(issue, unrecognized_inputs)
    observations["frontage_ft"] = (
        frontage,
        None if frontage is None else min(frontage / 200.0, 1.0),
        "linear size convention: frontage_ft / 200, capped at 1.0",
    )

    ingress, issue = _number(site, "ingress_egress_count")
    if issue:
        return _error(issue, unrecognized_inputs)
    observations["ingress_egress_count"] = (
        ingress,
        None if ingress is None else min(ingress / 3.0, 1.0),
        "linear access convention: curb cuts / 3, capped at 1.0",
    )

    visibility = site.get("visibility_notes")
    if visibility is not None and not isinstance(visibility, str):
        return _error(
            "site.visibility_notes must be a string or null", unrecognized_inputs
        )
    if visibility is None or not visibility.strip():
        observations["visibility_notes"] = (
            visibility,
            None,
            "no non-empty visibility observation supplied",
        )
    else:
        visibility_value, visibility_basis = _visibility_score(visibility)
        observations["visibility_notes"] = (
            visibility,
            visibility_value,
            visibility_basis,
        )

    anchor_count, anchor_basis, anchor_unknown, anchor_issue = _anchor_observation(
        nearby_anchors
    )
    unrecognized_inputs.extend(anchor_unknown)
    if anchor_issue:
        return _error(anchor_issue, unrecognized_inputs)
    observations["nearby_anchors"] = (
        anchor_count,
        None if anchor_count is None else min(anchor_count / 5.0, 1.0),
        f"{anchor_basis}; linear convention: complementary anchors / 5, capped at 1.0",
    )

    factors: list[dict[str, Any]] = []
    missing_factors: list[str] = []
    weighted_points = 0.0
    available_weight = 0
    for factor, weight in FACTOR_WEIGHTS.items():
        observed_value, normalized_score, basis = observations[factor]
        available = normalized_score is not None
        points = weight * normalized_score if available else 0.0
        if available:
            weighted_points += points
            available_weight += weight
        else:
            missing_factors.append(factor)
        factors.append(
            {
                "factor": factor,
                "weight": weight,
                "observed_value": observed_value,
                "available": available,
                "normalized_score": (
                    round(normalized_score, 4)
                    if normalized_score is not None
                    else None
                ),
                "weighted_points": round(points, 2),
                "basis": basis,
            }
        )

    score = round(weighted_points, 2)
    available_score = (
        round(weighted_points / available_weight * 100.0, 2)
        if available_weight
        else None
    )
    return {
        "score": score,
        "score_100": score,
        "available_factor_score_100": available_score,
        "calibration": CALIBRATION_LABEL,
        "calibration_label": CALIBRATION_LABEL,
        "heuristic": True,
        "factor_weights": dict(FACTOR_WEIGHTS),
        "factor_weight_total": sum(FACTOR_WEIGHTS.values()),
        "factors": factors,
        "coverage_pct": available_weight,
        "missing_factors": missing_factors,
        "unrecognized_inputs": sorted(set(unrecognized_inputs)),
        "honesty": (
            "HEURISTIC — UNCALIBRATED. Factor weights and breakpoints are "
            "screening conventions, not coefficients calibrated to observed outcomes."
        ),
        "scope_note": (
            "Imagery and computer-vision review are out of scope. Verify access, "
            "frontage, visibility, intersection controls, and anchors in the field."
        ),
    }


__all__ = ["CALIBRATION_LABEL", "FACTOR_WEIGHTS", "micro_location_score"]
