"""AVM, regional replacement-cost, and estimator-confidence scoring inputs."""

import pytest

from cre_mcp.models import ParcelRecord, ValueEstimate
from cre_mcp.scoring.engine import score
from cre_mcp.scoring.rubrics import CORE_RUBRIC
from cre_mcp.scoring.signals import price_vs_avm, price_vs_replacement
from cre_mcp.scoring.signals import assessor_last_sale_delta
from tests.scoring.builders import deal_context


def test_price_vs_avm_uses_value_estimate_and_stays_none_without_one():
    ctx = deal_context(price=1_000_000)
    assert price_vs_avm(ctx) is None

    ctx.value_estimate = ValueEstimate(
        value=900_000,
        low=800_000,
        mid=900_000,
        high=1_000_000,
        method="county_comps",
        n_comps=4,
        confidence=0.75,
        error_band=0.10,
        source="fixture",
    )

    assert price_vs_avm(ctx) == pytest.approx(1_000_000 / 900_000)


def test_regional_replacement_signal_computes_but_is_marked_low_reliability():
    ctx = deal_context(price=1_000_000, size=5_000)

    assert price_vs_replacement(ctx) == pytest.approx((1_000_000 / 5_000) / 220)
    result = score(ctx, CORE_RUBRIC)
    signal = next(
        item
        for item in result.rubric_result.signal_results
        if item.key == "price_vs_avm"
    )
    assert signal.missing is True


def test_thin_value_estimate_contributes_less_coverage_than_county_comps():
    thin = deal_context(price=1_000_000)
    strong = deal_context(price=1_000_000)
    thin.value_estimate = ValueEstimate(
        value=900_000,
        mid=900_000,
        method="listing_context",
        confidence=0.20,
        source="fixture",
    )
    strong.value_estimate = thin.value_estimate.model_copy(
        update={"method": "county_comps", "confidence": 0.80}
    )

    assert score(thin, CORE_RUBRIC).rubric_result.coverage < score(
        strong,
        CORE_RUBRIC,
    ).rubric_result.coverage


def test_assessor_last_sale_delta_uses_subject_sale_when_wired():
    ctx = deal_context(price=1_000_000)
    ctx.parcel = ParcelRecord(
        apn="123",
        last_sale_price=800_000,
        last_sale_date="2025-01-01",
    )

    delta = assessor_last_sale_delta(ctx)

    assert delta is not None
    assert 1.0 < delta < 1.25
