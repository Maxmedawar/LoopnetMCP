import pytest

from cre_mcp.models import DealContext, Listing
from cre_mcp.scoring.engine import score, score_all
from cre_mcp.scoring.rubrics import DISTRESSED_RUBRIC


def _listing(**raw):
    return Listing(
        source="auction_com",
        source_id="2118171",
        name="205 S San Antonio Street",
        address="205 S San Antonio Street",
        city="Sabinal",
        state="TX",
        property_type="special-purpose",
        listing_type="for-sale",
        price_usd=60_000,
        size_sqft_num=3_685,
        url="https://www.auction.com/details/example-2118171",
        is_distressed=True,
        distress_type="bank_owned",
        raw={"avm": 283_454, **raw},
    )


def test_distressed_rubric_scores_partial_data_with_visible_confidence():
    result = score(DealContext(listing=_listing()), DISTRESSED_RUBRIC)
    signals = {item.key: item for item in result.rubric_result.signal_results}

    assert result.grade != "DQ"
    assert 0 < result.score <= 100
    assert 0 < result.confidence < 0.5
    assert signals["discount_to_bpo"].missing is False
    assert signals["ltv_at_entry"].missing is False
    assert signals["discount_to_upb"].missing is True
    assert signals["lien_position"].missing is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.55, 1.0),
        (0.5501, 0.80),
        (0.70, 0.80),
        (0.7001, 0.50),
        (0.85, 0.50),
        (0.8501, 0.15),
    ],
)
def test_distressed_discount_to_upb_band_edges(value, expected):
    result = score(
        DealContext(listing=_listing(discount_to_upb=value)),
        DISTRESSED_RUBRIC,
    )
    signal = next(
        item
        for item in result.rubric_result.signal_results
        if item.key == "discount_to_upb"
    )
    assert signal.normalized == expected


@pytest.mark.parametrize(
    "raw",
    [
        {"title_defect": True},
        {"lien_position": "second", "first_lien_default": True},
        {"collateral_score": 29},
        {"1031_days_remaining": 9, "signed_psa": False},
    ],
)
def test_distressed_disqualifiers_short_circuit(raw):
    result = score(
        DealContext(listing=_listing(**raw)),
        DISTRESSED_RUBRIC,
    )
    assert result.grade == "DQ"
    assert result.rubric_result.disqualified is True


def test_distressed_listing_routes_to_distressed_and_asset_rubrics():
    scores = score_all(DealContext(listing=_listing()))
    strategies = {item.strategy for item in scores}
    assert strategies == {"distressed", "core"}
    distressed = next(item for item in scores if item.strategy == "distressed")
    collateral = next(
        item
        for item in distressed.rubric_result.signal_results
        if item.key == "collateral_quality_carryover"
    )
    assert collateral.missing is False
