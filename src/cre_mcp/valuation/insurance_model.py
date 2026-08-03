"""Insurance repricing bridge from quoted premium to NOI.

This module compares supplied economic terms only.  It cannot determine policy
wording, carrier solvency/appetite, coinsurance compliance, or whether a stated
limit is adequate for the actual exposure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
from typing import Any


DISCLAIMER = (
    "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
)
CRITICAL_COVERAGES: dict[str, tuple[str, ...]] = {
    "business_interruption": (
        "bi",
        "business interruption",
        "business income",
        "time element",
    ),
    "flood": ("flood",),
    "wind": ("wind", "windstorm", "named storm", "hurricane"),
}


def _number(value: Any, label: str, *, non_negative: bool = True) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number) or (non_negative and number < 0):
        qualifier = " non-negative" if non_negative else ""
        raise ValueError(f"{label} must be a finite{qualifier} number")
    return number


def _range(
    value: Any,
    label: str,
    *,
    non_negative: bool = True,
) -> dict[str, float]:
    if isinstance(value, Mapping):
        low = _number(value.get("low"), f"{label}.low", non_negative=non_negative)
        high = _number(value.get("high"), f"{label}.high", non_negative=non_negative)
        base = _number(
            value.get("base", (low + high) / 2),
            f"{label}.base",
            non_negative=non_negative,
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
        if len(values) not in {2, 3}:
            raise ValueError(f"{label} sequence must contain two or three values")
        low = _number(values[0], f"{label}[0]", non_negative=non_negative)
        high = _number(values[-1], f"{label}[-1]", non_negative=non_negative)
        base = (
            _number(values[1], f"{label}[1]", non_negative=non_negative)
            if len(values) == 3
            else (low + high) / 2
        )
    else:
        low = high = base = _number(value, label, non_negative=non_negative)
    if not low <= base <= high:
        raise ValueError(f"{label} must satisfy low <= base <= high")
    return {"low": low, "base": base, "high": high}


def _coverage_ranges(value: Any, label: str) -> dict[str, dict[str, float]]:
    """Normalize a scalar/range as ``all`` or a coverage-keyed mapping."""

    if value is None:
        return {}
    if isinstance(value, Mapping):
        keys = {str(key).lower() for key in value}
        if {"low", "high"}.issubset(keys):
            return {"all": _range(value, label)}
        result: dict[str, dict[str, float]] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip().lower().replace("-", "_").replace(" ", "_")
            if not key:
                raise ValueError(f"{label} contains an empty coverage name")
            result[key] = _range(raw_value, f"{label}.{key}")
        return result
    return {"all": _range(value, label)}


def _money_range(value: Mapping[str, float]) -> dict[str, float]:
    return {key: round(float(amount), 2) for key, amount in value.items()}


def _is_scalar_range(value: Mapping[str, float]) -> bool:
    return value["low"] == value["base"] == value["high"]


def _scalar_or_range(value: Mapping[str, float]) -> float | dict[str, float]:
    rounded = _money_range(value)
    return rounded["base"] if _is_scalar_range(value) else rounded


def _difference(
    minuend: Mapping[str, float], subtrahend: Mapping[str, float]
) -> dict[str, float]:
    return {
        "low": minuend["low"] - subtrahend["high"],
        "base": minuend["base"] - subtrahend["base"],
        "high": minuend["high"] - subtrahend["low"],
    }


def _warning(
    code: str,
    message: str,
    *,
    severity: str = "WARNING",
    coverage: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if coverage is not None:
        result["coverage"] = coverage
    return result


def _coverage_term_matches(text: str, term: str) -> bool:
    """Match the BI abbreviation as a token while retaining phrase matching."""
    if term == "bi":
        return re.search(r"\bbi\b", text) is not None
    return term == text or term in text


def _deductible_warnings(
    current: Mapping[str, Mapping[str, float]],
    quoted: Mapping[str, Mapping[str, float]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if not quoted:
        return [
            _warning(
                "QUOTE_DEDUCTIBLE_MISSING",
                "The quote has no deductible terms; obtain and compare all peril deductibles.",
            )
        ]
    coverages = ({key for key in current if key != "all"} | {key for key in quoted if key != "all"})
    if not coverages:
        coverages = {"all"}
    for coverage in sorted(coverages):
        current_range = current.get(coverage, current.get("all"))
        quote_range = quoted.get(coverage, quoted.get("all"))
        if quote_range is None:
            warnings.append(
                _warning(
                    "QUOTE_DEDUCTIBLE_MISSING",
                    f"No quoted deductible was supplied for {coverage}.",
                    coverage=coverage,
                )
            )
            continue
        if current_range is None:
            warnings.append(
                _warning(
                    "DEDUCTIBLE_BASELINE_MISSING",
                    f"No current deductible was supplied for {coverage}; change cannot be measured.",
                    coverage=coverage,
                )
            )
            continue
        if quote_range["high"] > current_range["high"]:
            warnings.append(
                _warning(
                    "HIGHER_DEDUCTIBLE",
                    (
                        f"Quoted {coverage} deductible reaches ${quote_range['high']:,.2f}, "
                        f"above the current ${current_range['high']:,.2f}; quantify retained loss."
                    ),
                    coverage=coverage,
                )
            )
        elif quote_range["low"] != current_range["low"] or quote_range["high"] != current_range["high"]:
            warnings.append(
                _warning(
                    "DEDUCTIBLE_CHANGED",
                    f"Quoted {coverage} deductible differs from the current term.",
                    severity="REVIEW",
                    coverage=coverage,
                )
            )
    return warnings


def _limits_warnings(
    current: Mapping[str, Mapping[str, float]],
    quoted: Mapping[str, Mapping[str, float]],
) -> list[dict[str, Any]]:
    if not quoted:
        return [
            _warning(
                "QUOTE_LIMITS_MISSING",
                "The quote has no limits schedule; limits, sublimits, aggregates, and coinsurance are unverified.",
            )
        ]
    warnings: list[dict[str, Any]] = []
    coverages = ({key for key in current if key != "all"} | {key for key in quoted if key != "all"})
    if not coverages:
        coverages = {"all"}
    for coverage in sorted(coverages):
        current_range = current.get(coverage, current.get("all"))
        quote_range = quoted.get(coverage, quoted.get("all"))
        if quote_range is None:
            warnings.append(
                _warning(
                    "QUOTE_LIMIT_MISSING",
                    f"No quoted limit was supplied for current coverage {coverage}.",
                    coverage=coverage,
                )
            )
            continue
        if current_range is None:
            warnings.append(
                _warning(
                    "LIMIT_BASELINE_MISSING",
                    f"No current limit was supplied for {coverage}; adequacy cannot be compared.",
                    severity="REVIEW",
                    coverage=coverage,
                )
            )
            continue
        if quote_range["high"] < current_range["low"]:
            warnings.append(
                _warning(
                    "LOWER_LIMIT",
                    f"Quoted {coverage} limit is below the current stated limit range.",
                    coverage=coverage,
                )
            )
        elif quote_range["low"] < current_range["high"]:
            warnings.append(
                _warning(
                    "POSSIBLE_LOWER_LIMIT",
                    f"Quoted {coverage} limit range can fall below the current term.",
                    severity="REVIEW",
                    coverage=coverage,
                )
            )
    return warnings


def _exclusion_warnings(exclusions: Sequence[str]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    normalized = [
        str(item).strip().lower().replace("_", " ").replace("-", " ")
        for item in exclusions
    ]
    for coverage, terms in CRITICAL_COVERAGES.items():
        matches = [
            original
            for original, text in zip(exclusions, normalized)
            if any(_coverage_term_matches(text, term) for term in terms)
        ]
        label = "BI/business interruption" if coverage == "business_interruption" else coverage
        if matches:
            warnings.append(
                _warning(
                    f"{coverage.upper()}_EXCLUSION",
                    f"Quoted exclusions identify {label}: {matches}; model uninsured loss and downtime.",
                    severity="CRITICAL",
                    coverage=coverage,
                )
            )
        else:
            warnings.append(
                _warning(
                    f"{coverage.upper()}_UNVERIFIED",
                    (
                        f"No explicit {label} exclusion was supplied, but absence from this list "
                        "does not establish coverage; verify forms, sublimits, waiting periods, and deductibles."
                    ),
                    severity="REVIEW",
                    coverage=coverage,
                )
            )
    return warnings


def insurance_repricing(
    current: Mapping[str, Any] | None,
    quotes: Sequence[Mapping[str, Any]] | None,
    noi: Mapping[str, Any] | Sequence[float] | float | None,
) -> dict[str, Any]:
    """Compare quote premium ranges and bridge the delta into NOI.

    Starting NOI is assumed to include the current premium. Therefore quoted
    NOI equals starting NOI minus ``quoted premium - current premium``.
    """

    try:
        if not isinstance(current, Mapping):
            raise ValueError("current must be a mapping")
        if quotes is None or isinstance(quotes, (str, bytes, Mapping)):
            raise ValueError("quotes must be a sequence of quote mappings")
        current_premium = _range(current.get("premium"), "current.premium")
        current_deductibles = _coverage_ranges(
            current.get("deductibles", current.get("deductible")),
            "current.deductibles",
        )
        current_limits = _coverage_ranges(current.get("limits"), "current.limits")
        noi_range = _range(noi, "noi", non_negative=False)

        quote_results: list[dict[str, Any]] = []
        for index, quote in enumerate(quotes):
            if not isinstance(quote, Mapping):
                raise ValueError(f"quotes[{index}] must be a mapping")
            carrier = str(quote.get("carrier") or "").strip()
            if not carrier:
                raise ValueError(f"quotes[{index}].carrier is required")
            quote_premium = _range(quote.get("premium"), f"quotes[{index}].premium")
            quote_deductibles = _coverage_ranges(
                quote.get("deductible", quote.get("deductibles")),
                f"quotes[{index}].deductible",
            )
            quote_limits = _coverage_ranges(
                quote.get("limits"), f"quotes[{index}].limits"
            )
            raw_exclusions = quote.get("exclusions", [])
            if isinstance(raw_exclusions, str):
                exclusions = [raw_exclusions]
            elif isinstance(raw_exclusions, Sequence) and not isinstance(raw_exclusions, bytes):
                exclusions = []
                for exclusion_index, exclusion in enumerate(raw_exclusions):
                    if not isinstance(exclusion, str) or not exclusion.strip():
                        raise ValueError(
                            f"quotes[{index}].exclusions[{exclusion_index}] must be non-empty text"
                        )
                    exclusions.append(exclusion.strip())
            else:
                raise ValueError(f"quotes[{index}].exclusions must be a sequence of text")

            premium_delta = _difference(quote_premium, current_premium)
            noi_impact = {
                "low": -premium_delta["high"],
                "base": -premium_delta["base"],
                "high": -premium_delta["low"],
            }
            noi_after = {
                "low": noi_range["low"] + noi_impact["low"],
                "base": noi_range["base"] + noi_impact["base"],
                "high": noi_range["high"] + noi_impact["high"],
            }
            deductible_warnings = _deductible_warnings(
                current_deductibles, quote_deductibles
            )
            limits_warnings = _limits_warnings(current_limits, quote_limits)
            exclusion_warnings = _exclusion_warnings(exclusions)
            other_exclusion_warnings = [
                _warning(
                    "OTHER_EXCLUSION",
                    f"Review quoted exclusion with the broker and coverage counsel: {exclusion}",
                    severity="REVIEW",
                )
                for exclusion in exclusions
                if not any(
                    _coverage_term_matches(
                        exclusion.lower().replace("_", " ").replace("-", " "),
                        term,
                    )
                    for terms in CRITICAL_COVERAGES.values()
                    for term in terms
                )
            ]
            structured_warnings = (
                deductible_warnings
                + limits_warnings
                + exclusion_warnings
                + other_exclusion_warnings
            )
            quote_results.append(
                {
                    "carrier": carrier,
                    "current_premium_range": _money_range(current_premium),
                    "quoted_premium_range": _money_range(quote_premium),
                    "premium_delta_range": _money_range(premium_delta),
                    "premium_delta": _scalar_or_range(premium_delta),
                    "noi_before_range": _money_range(noi_range),
                    "noi_impact_range": _money_range(noi_impact),
                    "noi_impact": _scalar_or_range(noi_impact),
                    "noi_delta": _scalar_or_range(noi_impact),
                    "noi_after_range": _money_range(noi_after),
                    "noi_after": _scalar_or_range(noi_after),
                    "deductibles": quote_deductibles,
                    "limits": quote_limits,
                    "exclusions": exclusions,
                    "deductible_gap_warnings": deductible_warnings,
                    "limits_gap_warnings": limits_warnings,
                    "exclusion_warnings": exclusion_warnings,
                    "warning_details": structured_warnings,
                    "warnings": [warning["message"] for warning in structured_warnings],
                    "broker_verify": True,
                }
            )

        return {
            "status": "ANALYTICAL_ESTIMATE",
            "disclaimer": DISCLAIMER,
            "method": (
                "Premium delta = quoted premium - current premium; NOI impact = "
                "-premium delta; quoted NOI = current NOI + NOI impact. Range "
                "subtraction uses endpoint arithmetic."
            ),
            "current": {
                "premium_range": _money_range(current_premium),
                "deductibles": current_deductibles,
                "limits": current_limits,
            },
            "noi_before_range": _money_range(noi_range),
            "quote_impacts": quote_results,
            "quotes": quote_results,
            "broker_verify": True,
            "broker_verification_flag": {
                "required": True,
                "reason": (
                    "A licensed insurance broker must verify carrier, forms, exclusions, "
                    "limits/sublimits, aggregates, coinsurance, deductibles, and BI period."
                ),
            },
            "coverage_warning": (
                "This comparison does not establish that BI/business interruption, flood, "
                "wind, ordinance/law, or any other peril is covered or adequately limited."
            ),
        }
    except Exception as exc:
        return {"error": f"insurance_repricing: {exc}"}


__all__ = ["insurance_repricing"]
