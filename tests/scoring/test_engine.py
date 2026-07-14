"""Generic engine edge, denominator, disqualifier, and market-blend tests."""

from unittest.mock import patch

import pytest

from cre_mcp.models import Band, DisqualifierSpec, Rubric, SignalSpec
from cre_mcp.eval.status import UNCALIBRATED_DISCLAIMER, set_score_calibrated
from cre_mcp.scoring.engine import score
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.scoring.signals import SIGNAL_EXTRACTORS
from tests.scoring.builders import deal_context, market_pack


def _rubric(*signals, disqualifiers=None, market_weight=0.0):
    return Rubric(
        strategy="test",
        display_name="Test Rubric",
        signals=list(signals),
        disqualifiers=disqualifiers or [],
        include_core=False,
        market_weight=market_weight,
    )


def _signal(key, weight=1.0, required=False):
    return SignalSpec(
        key=key,
        label=key,
        extractor=key,
        weight=weight,
        bands=[
            Band(up_to=5, score=0.2),
            Band(up_to=10, score=0.6),
            Band(up_to=None, score=1.0),
        ],
        higher_is_better=True,
        required=required,
    )


def test_band_edges_start_the_higher_band_at_equality():
    ctx = deal_context(raw={"lease_years_remaining": 5})
    result = score(ctx, _rubric(_signal("lease_years_remaining")))
    assert result.rubric_result.signal_results[0].normalized == 0.6
    assert result.rubric_result.raw_score == 60.0


def test_score_discloses_uncalibrated_status_by_default_and_drops_after_backtest():
    set_score_calibrated(False)
    try:
        uncalibrated = score(
            deal_context(raw={"lease_years_remaining": 12}),
            _rubric(_signal("lease_years_remaining")),
        )
        assert uncalibrated.calibrated is False
        assert uncalibrated.calibration_disclaimer == UNCALIBRATED_DISCLAIMER

        set_score_calibrated(True)
        calibrated = score(
            deal_context(raw={"lease_years_remaining": 12}),
            _rubric(_signal("lease_years_remaining")),
        )
        assert calibrated.calibrated is True
        assert calibrated.calibration_disclaimer is None
    finally:
        set_score_calibrated(False)


def test_mixed_strict_and_inclusive_supply_band_edges():
    rubric = _rubric(
        SignalSpec(
            key="supply_pipeline",
            label="Supply",
            extractor="supply_pipeline",
            weight=1,
            bands=[
                Band(up_to=edge, score=value)
                for edge, value in T.SIGNAL_BANDS["supply_pipeline"]
            ],
            higher_is_better=False,
        )
    )

    at_two = score(deal_context(raw={"supply_pipeline_pct": 2}), rubric)
    at_seven = score(deal_context(raw={"supply_pipeline_pct": 7}), rubric)
    assert at_two.rubric_result.signal_results[0].normalized == 0.7
    assert at_seven.rubric_result.signal_results[0].normalized == 0.35


def test_missing_signal_drops_weight_from_denominator():
    ctx = deal_context(raw={"lease_years_remaining": 12})
    rubric = _rubric(
        _signal("lease_years_remaining", weight=0.25),
        _signal("traffic_count", weight=0.75),
    )
    result = score(ctx, rubric)
    assert result.rubric_result.raw_score == 100.0
    assert result.score == 100.0
    assert result.rubric_result.coverage == 0.25


def test_missing_required_signal_penalizes_confidence_beyond_weight_coverage():
    ctx = deal_context(raw={"lease_years_remaining": 12})
    rubric = _rubric(
        _signal("lease_years_remaining", weight=0.5, required=True),
        _signal("traffic_count", weight=0.5, required=True),
    )
    result = score(ctx, rubric)
    assert result.rubric_result.coverage == 0.5
    assert result.confidence == 0.25


def test_disqualifier_short_circuits_before_extractors():
    key = "should_not_run"

    def fail(_ctx):
        raise AssertionError("extractor ran after DQ")

    SIGNAL_EXTRACTORS[key] = fail
    try:
        rubric = _rubric(
            SignalSpec(key=key, label=key, extractor=key, weight=1.0),
            disqualifiers=[
                DisqualifierSpec(
                    key="core_title_defect",
                    predicate="core_title_defect",
                    reason_template="title defect",
                )
            ],
        )
        result = score(deal_context(raw={"title_clear": False}), rubric)
    finally:
        SIGNAL_EXTRACTORS.pop(key)
    assert result.score == 0
    assert result.grade == "DQ"
    assert result.rubric_result.disqualified is True
    assert result.rubric_result.signal_results == []


def test_market_blend_uses_weight_and_renormalizes_when_market_missing():
    rubric = _rubric(_signal("lease_years_remaining"), market_weight=0.20)
    with patch("cre_mcp.scoring.engine.calculate_market_score", return_value=(80.0, 1.0)):
        with_market = score(
            deal_context(raw={"lease_years_remaining": 7}, market=market_pack({"population": 1_000_000})),
            rubric,
        )
    without_market = score(
        deal_context(raw={"lease_years_remaining": 7}, market=None),
        rubric,
    )
    assert with_market.rubric_result.raw_score == 60.0
    assert with_market.score == pytest.approx(64.0)
    assert with_market.market_score == 80.0
    assert without_market.score == 60.0
    assert without_market.market_score is None
