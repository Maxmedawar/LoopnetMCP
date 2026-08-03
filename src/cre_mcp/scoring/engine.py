"""Generic missing-data-aware rubric scoring engine."""

import logging
from dataclasses import dataclass

from cre_mcp.eval.status import UNCALIBRATED_DISCLAIMER, is_score_calibrated
from cre_mcp.market.intel import market_score as calculate_market_score
from cre_mcp.models.deals import DealContext
from cre_mcp.models.scoring import (
    DealScore,
    Rubric,
    RubricResult,
    SignalResult,
    SignalSpec,
)
from cre_mcp.scoring.explain import render_explanation
from cre_mcp.scoring.rubrics import CORE_RUBRIC, applicable_rubrics
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.scoring.signals import DISQUALIFIER_PREDICATES, SIGNAL_EXTRACTORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Evaluation:
    result: RubricResult
    available_weight: float
    required_present: int
    required_total: int


def _clamp(value: float) -> float:
    return max(T.NORMALIZED_MIN, min(T.NORMALIZED_MAX, value))


def _normalize(raw_value: float, signal: SignalSpec) -> float:
    if not signal.bands:
        return _clamp(raw_value)
    for band_index, band in enumerate(signal.bands):
        if band.up_to is None:
            return _clamp(band.score)
        if signal.higher_is_better:
            if raw_value < band.up_to:
                return _clamp(band.score)
        elif (
            raw_value < band.up_to
            if band_index < T.LOWER_EXCLUSIVE_EDGE_COUNTS.get(signal.key, 0)
            else raw_value <= band.up_to
        ):
            return _clamp(band.score)
    return T.NORMALIZED_MIN


def _disqualifier_hits(ctx: DealContext, rubric: Rubric) -> list[str]:
    specs = list(rubric.disqualifiers)
    if rubric.include_core:
        specs.extend(CORE_RUBRIC.disqualifiers)
    hits: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        if spec.key in seen:
            continue
        seen.add(spec.key)
        predicate = DISQUALIFIER_PREDICATES.get(spec.predicate)
        if predicate is None:
            logger.warning("Unknown disqualifier predicate: %s", spec.predicate)
            continue
        try:
            matched = predicate(ctx)
        except Exception as exc:
            logger.warning("Disqualifier predicate %s failed: %s", spec.key, exc)
            matched = False
        if matched:
            hits.append(spec.reason_template)
    return hits


def _signal_reliability(ctx: DealContext, signal: SignalSpec) -> float:
    if signal.key == "price_vs_avm":
        if _raw_avm_present(ctx):
            return T.AVM_RAW_SOURCE_CONFIDENCE
        if ctx.value_estimate is not None:
            return _clamp(ctx.value_estimate.confidence)
    if signal.key in {"price_vs_replacement", "price_per_sf_vs_replacement"}:
        assumptions = ctx.underwriting.assumptions_used if ctx.underwriting else {}
        replacement = assumptions.get("replacement_cost_per_sf")
        if (
            isinstance(replacement, dict)
            and replacement.get("source") == "regional_estimate"
        ):
            return T.REPLACEMENT_COST_ESTIMATE_CONFIDENCE
        if not isinstance(replacement, dict):
            return T.REPLACEMENT_COST_ESTIMATE_CONFIDENCE
    return T.FULL_COVERAGE


def _raw_avm_present(ctx: DealContext) -> bool:
    value = ctx.listing.raw.get("avm")
    if value is None or isinstance(value, bool):
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _evaluate_signals(ctx: DealContext, rubric: Rubric) -> _Evaluation:
    total_weight = sum(signal.weight for signal in rubric.signals)
    available_weight = T.NO_COVERAGE
    earned = T.NO_COVERAGE
    results: list[SignalResult] = []
    required_total = sum(signal.required for signal in rubric.signals)
    required_present = 0

    for signal in rubric.signals:
        extractor = SIGNAL_EXTRACTORS.get(signal.extractor)
        if extractor is None:
            raw_value = None
            note = f"Unknown extractor: {signal.extractor}"
        else:
            try:
                raw_value = extractor(ctx)
                note = None
            except Exception as exc:
                logger.warning("Signal extractor %s failed: %s", signal.key, exc)
                raw_value = None
                note = str(exc)
        if raw_value is None:
            results.append(
                SignalResult(
                    key=signal.key,
                    missing=True,
                    note=note or "Input unavailable; weight excluded.",
                )
            )
            continue
        normalized = _normalize(raw_value, signal)
        effective_weight = signal.weight * _signal_reliability(ctx, signal)
        weighted = normalized * effective_weight
        available_weight += effective_weight
        earned += weighted
        if signal.required:
            required_present += 1
        results.append(
            SignalResult(
                key=signal.key,
                raw_value=raw_value,
                normalized=normalized,
                weighted_points=weighted,
                missing=False,
                note=note,
            )
        )

    raw_score = (
        T.SCORE_SCALE * earned / available_weight
        if available_weight > T.NO_COVERAGE
        else T.NO_COVERAGE
    )
    coverage = (
        available_weight / total_weight
        if total_weight > T.NO_COVERAGE
        else T.NO_COVERAGE
    )
    return _Evaluation(
        result=RubricResult(
            strategy=rubric.strategy,
            signal_results=results,
            raw_score=round(raw_score, 2),
            coverage=round(coverage, 4),
        ),
        available_weight=available_weight,
        required_present=required_present,
        required_total=required_total,
    )


def _grade(value: float) -> str:
    for cutoff, grade in T.GRADE_CUTOFFS:
        if value >= cutoff:
            return grade
    return T.FAIL_GRADE


def _calibration_disclosure() -> tuple[bool, str | None]:
    calibrated = is_score_calibrated()
    return calibrated, None if calibrated else UNCALIBRATED_DISCLAIMER


def score(ctx: DealContext, rubric: Rubric) -> DealScore:
    """Score one context with disqualifier short-circuit and partial-weight math."""
    calibrated, calibration_disclaimer = _calibration_disclosure()
    hits = _disqualifier_hits(ctx, rubric)
    if hits:
        result = RubricResult(
            strategy=rubric.strategy,
            disqualified=True,
            disqualifier_hits=hits,
            raw_score=T.NO_COVERAGE,
            coverage=T.NO_COVERAGE,
        )
        explanation = render_explanation(
            ctx,
            rubric,
            result,
            final_score=T.NO_COVERAGE,
            grade=T.DISQUALIFIED_GRADE,
            market_component=None,
            core_component=None,
        )
        return DealScore(
            strategy=rubric.strategy,
            score=T.NO_COVERAGE,
            grade=T.DISQUALIFIED_GRADE,
            confidence=T.NO_COVERAGE,
            rubric_result=result,
            market_score=None,
            explanation=explanation,
            gated=False,
            calibrated=calibrated,
            calibration_disclaimer=calibration_disclaimer,
        )

    strategy_eval = _evaluate_signals(ctx, rubric)
    core_eval = (
        _evaluate_signals(ctx, CORE_RUBRIC)
        if rubric.include_core
        else None
    )
    market_value: float | None = None
    market_confidence = T.NO_COVERAGE
    if ctx.market is not None:
        candidate, market_confidence = calculate_market_score(ctx.market)
        if market_confidence > T.NO_COVERAGE:
            market_value = candidate

    components: list[tuple[float, float]] = []
    if strategy_eval.available_weight > T.NO_COVERAGE:
        strategy_weight = (
            T.COMPOSITION_WEIGHTS["strategy"]
            if rubric.include_core
            else T.FULL_COVERAGE - rubric.market_weight
        )
        components.append((strategy_eval.result.raw_score, strategy_weight))
    if core_eval is not None and core_eval.available_weight > T.NO_COVERAGE:
        components.append((core_eval.result.raw_score, T.COMPOSITION_WEIGHTS["core"]))
    if market_value is not None:
        components.append((market_value, rubric.market_weight))

    component_weight = sum(weight for _, weight in components)
    final_score = (
        sum(value * weight for value, weight in components) / component_weight
        if component_weight > T.NO_COVERAGE
        else T.NO_COVERAGE
    )
    confidence = strategy_eval.result.coverage
    if strategy_eval.required_total:
        confidence *= strategy_eval.required_present / strategy_eval.required_total
    confidence = _clamp(confidence)
    final_score = max(T.NO_COVERAGE, min(T.SCORE_SCALE, final_score))
    gated = (
        strategy_eval.result.coverage < T.GATE_MIN_COVERAGE
        or confidence < T.GATE_MIN_CONFIDENCE
    )
    grade = T.NOT_RATED_GRADE if gated else _grade(final_score)
    explanation = render_explanation(
        ctx,
        rubric,
        strategy_eval.result,
        final_score=final_score,
        grade=grade,
        market_component=market_value,
        core_component=core_eval.result.raw_score if core_eval else None,
        gated=gated,
    )
    return DealScore(
        strategy=rubric.strategy,
        score=round(final_score, 2),
        grade=grade,
        confidence=round(confidence, 4),
        rubric_result=strategy_eval.result,
        market_score=market_value,
        explanation=explanation,
        gated=gated,
        calibrated=calibrated,
        calibration_disclaimer=calibration_disclaimer,
    )


def score_all(ctx: DealContext) -> list[DealScore]:
    """Score every applicable strategy and sort descending."""
    rubrics = applicable_rubrics(ctx)
    if ctx.listing.is_distressed:
        distressed = [rubric for rubric in rubrics if rubric.strategy == "distressed"]
        asset_scores = [
            score(ctx, rubric)
            for rubric in rubrics
            if rubric.strategy != "distressed"
        ]
        covered_assets = [
            item for item in asset_scores if item.confidence > T.NO_COVERAGE
        ]
        scoring_context = ctx
        if covered_assets:
            collateral = max(covered_assets, key=lambda item: item.score)
            raw = dict(ctx.listing.raw)
            raw["collateral_score"] = collateral.score
            scoring_context = ctx.model_copy(
                update={"listing": ctx.listing.model_copy(update={"raw": raw})}
            )
        scores = [score(scoring_context, rubric) for rubric in distressed]
        scores.extend(asset_scores)
    else:
        scores = [score(ctx, rubric) for rubric in rubrics]
    return sorted(scores, key=lambda item: (item.score, item.confidence), reverse=True)


def best(scores: list[DealScore]) -> DealScore | None:
    """Return the highest-ranked score, if any."""
    return max(scores, key=lambda item: (item.score, item.confidence), default=None)
