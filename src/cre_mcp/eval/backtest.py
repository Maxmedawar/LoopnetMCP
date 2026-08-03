"""Stdlib-only calibration diagnostics for realized CRE deal outcomes."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from cre_mcp.models.evaluation import CalibrationReport, GradeCalibration
from cre_mcp.scoring.rubrics import thresholds as T

MIN_CALIBRATION_SAMPLES = 100
MIN_CALIBRATION_BUCKETS = 3
MIN_DISCRIMINATION = 0.10
MIN_GOOD_RATE_SPREAD = 0.10
REALIZED_GOOD_IRR_THRESHOLD_PCT = 8.0
WILSON_Z_95 = 1.959963984540054


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    normalized = str(value).strip().casefold()
    if normalized in {"true", "yes", "y", "1", "good", "success", "successful"}:
        return True
    if normalized in {"false", "no", "n", "0", "bad", "failure", "failed"}:
        return False
    return None


def _grade_for_score(score: float) -> str:
    for cutoff, grade in T.GRADE_CUTOFFS:
        if score >= cutoff:
            return grade
    return T.FAIL_GRADE


def _realized_good(row: Mapping[str, Any]) -> tuple[bool | None, bool]:
    closed = _bool(row.get("closed"))
    if closed is False:
        return (False, False) if _bool(row.get("went_bad")) is True else (None, False)
    explicit = _bool(row.get("realized_good"))
    if explicit is not None:
        return explicit, False
    irr = _number(row.get("realized_irr"))
    if irr is not None:
        irr_pct = irr * 100 if -1 <= irr <= 1 else irr
        return irr_pct >= REALIZED_GOOD_IRR_THRESHOLD_PCT, True
    went_bad = _bool(row.get("went_bad"))
    if went_bad is not None:
        return not went_bad, False
    return None, False


def _normalize_rows(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    materialized = list(rows)
    normalized: list[dict[str, Any]] = []
    irr_derived = 0
    for row in materialized:
        score = _number(row.get("predicted_score", row.get("score")))
        if score is None or not 0 <= score <= T.SCORE_SCALE:
            continue
        good, derived = _realized_good(row)
        if good is None:
            continue
        grade = str(row.get("predicted_grade") or row.get("grade") or "").strip()
        normalized.append(
            {
                "score": score,
                "grade": grade or _grade_for_score(score),
                "good": good,
            }
        )
        irr_derived += int(derived)
    return normalized, len(materialized) - len(normalized), irr_derived


def _wilson(successes: int, n: int) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    proportion = successes / n
    z2 = WILSON_Z_95**2
    denominator = 1 + z2 / n
    center = (proportion + z2 / (2 * n)) / denominator
    margin = (
        WILSON_Z_95
        * math.sqrt((proportion * (1 - proportion) + z2 / (4 * n)) / n)
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average = (index + 1 + end) / 2
        for position in range(index, end):
            ranks[ordered[position][0]] = average
        index = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_sum = sum((value - left_mean) ** 2 for value in left)
    right_sum = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_sum * right_sum)
    return numerator / denominator if denominator > 0 else None


def _spearman(scores: list[float], outcomes: list[bool]) -> float | None:
    return _pearson(
        _average_ranks(scores),
        _average_ranks([float(value) for value in outcomes]),
    )


def load_csv(path: str | Path) -> list[dict[str, str]]:
    """Load a caller-provided labeled CSV without third-party dependencies."""
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise ValueError(f"dataset_path is not a readable file: {resolved}")
    if resolved.suffix.casefold() != ".csv":
        raise ValueError("dataset_path must point to a CSV file")
    with resolved.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        if "predicted_score" not in headers:
            raise ValueError("CSV must include predicted_score")
        if not ({"realized_good", "realized_irr"} & headers):
            raise ValueError("CSV must include realized_good or realized_irr")
        return [dict(row) for row in reader]


def backtest(rows: Iterable[Mapping[str, Any]]) -> CalibrationReport:
    """Compute calibration, discrimination, Brier loss, and Wilson intervals."""
    data, excluded, irr_derived = _normalize_rows(rows)
    if not data:
        return CalibrationReport(
            n=0,
            excluded=excluded,
            calibration_threshold=MIN_CALIBRATION_SAMPLES,
            caveats=[
                "No rows had both a 0–100 predicted score and a realized-good label or realized IRR.",
                "The Medawar Deal Score remains uncalibrated until real labeled outcomes are supplied.",
            ],
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data:
        grouped[row["grade"]].append(row)
    buckets: list[GradeCalibration] = []
    for grade, items in grouped.items():
        n = len(items)
        successes = sum(int(item["good"]) for item in items)
        mean_score = sum(item["score"] for item in items) / n
        good_rate = successes / n
        low, high = _wilson(successes, n)
        buckets.append(
            GradeCalibration(
                grade=grade,
                n=n,
                good_outcomes=successes,
                mean_predicted_score=round(mean_score, 6),
                mean_predicted_probability=round(mean_score / T.SCORE_SCALE, 6),
                actual_good_rate=round(good_rate, 6),
                hit_rate=round(good_rate, 6),
                ci_low=round(low, 6),
                ci_high=round(high, 6),
            )
        )
    buckets.sort(key=lambda item: item.mean_predicted_score, reverse=True)

    scores = [float(row["score"]) for row in data]
    outcomes = [bool(row["good"]) for row in data]
    brier = sum(
        ((score / T.SCORE_SCALE) - float(good)) ** 2
        for score, good in zip(scores, outcomes, strict=True)
    ) / len(data)
    discrimination = _spearman(scores, outcomes)
    overall_successes = sum(outcomes)
    overall_rate = overall_successes / len(data)
    overall_low, overall_high = _wilson(overall_successes, len(data))

    ascending = sorted(buckets, key=lambda item: item.mean_predicted_score)
    monotonic = len(ascending) >= MIN_CALIBRATION_BUCKETS and all(
        left.actual_good_rate <= right.actual_good_rate
        for left, right in zip(ascending, ascending[1:])
    )
    spread = (
        max(item.actual_good_rate for item in buckets)
        - min(item.actual_good_rate for item in buckets)
    )
    calibrated = (
        len(data) >= MIN_CALIBRATION_SAMPLES
        and monotonic
        and discrimination is not None
        and discrimination >= MIN_DISCRIMINATION
        and spread >= MIN_GOOD_RATE_SPREAD
    )

    caveats = [
        "The 0–100 deal score is treated as a probability only to compute Brier loss; it is not itself a validated probability.",
        "Calibration is local to the supplied deals, strategies, markets, holding periods, and outcome definitions.",
        "Use a licensed historical CRE-outcomes dataset or keep recording closed-deal outcomes; do not infer causation from this report.",
    ]
    if irr_derived:
        caveats.append(
            f"{irr_derived} outcome label(s) were derived using realized IRR >= {REALIZED_GOOD_IRR_THRESHOLD_PCT:g}%."
        )
    if len(data) < MIN_CALIBRATION_SAMPLES:
        caveats.append(
            f"Sample is below the minimum calibration threshold of {MIN_CALIBRATION_SAMPLES}."
        )
    if not monotonic:
        caveats.append("Observed good-outcome rates are not monotonic across score/grade buckets.")
    if discrimination is None or discrimination < MIN_DISCRIMINATION:
        caveats.append("Rank discrimination is absent or too weak to validate ordering.")
    if spread < MIN_GOOD_RATE_SPREAD:
        caveats.append("Observed grade-band good rates do not separate meaningfully.")
    if calibrated:
        caveats.append(
            "The minimum mechanical calibration gate passed; continue monitoring drift and confidence intervals."
        )

    return CalibrationReport(
        n=len(data),
        excluded=excluded,
        by_grade=buckets,
        overall_good_rate=round(overall_rate, 6),
        ci_low=round(overall_low, 6),
        ci_high=round(overall_high, 6),
        brier=round(brier, 6),
        discrimination=(
            round(discrimination, 6) if discrimination is not None else None
        ),
        curve_monotonic=monotonic,
        calibrated=calibrated,
        calibration_threshold=MIN_CALIBRATION_SAMPLES,
        caveats=caveats,
    )


__all__ = [
    "MIN_CALIBRATION_SAMPLES",
    "REALIZED_GOOD_IRR_THRESHOLD_PCT",
    "backtest",
    "load_csv",
]
