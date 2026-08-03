"""County, FHFA, listing-context, and no-data valuation paths."""

from cre_mcp.comps.avm import estimate_value
from cre_mcp.models import Listing, SaleComp
from tests.scoring.builders import market_pack


def _subject(*, raw=None) -> Listing:
    return Listing(
        source="fixture",
        source_id="subject",
        name="Retail subject",
        address="100 Main St",
        city="Austin",
        state="TX",
        property_type="retail",
        price_usd=1_100_000,
        size_sqft_num=10_000,
        url="https://example.test/subject",
        raw=raw or {},
    )


def _comp(index: int, price: float, sqft: float) -> SaleComp:
    return SaleComp(
        source="Fixture County public sales",
        county_fips="37081",
        parcel_id=str(index),
        sale_price=price,
        sale_date=f"202{index}-01-01",
        sqft=sqft,
        use_code="RETAIL STORE",
    )


def test_county_comps_produce_hpi_adjusted_range_and_error_band():
    comps = [
        _comp(3, 900_000, 9_000),
        _comp(4, 1_000_000, 10_000),
        _comp(5, 1_155_000, 11_000),
    ]

    result = estimate_value(
        _subject(),
        comps,
        market_pack({"fhfa_hpi_growth_1yr": 4.0}),
    )

    assert result.method == "county_comps"
    assert result.n_comps == 3
    assert result.low < result.mid < result.high
    assert result.value == result.mid
    assert result.error_band > 0
    assert result.confidence >= 0.6
    assert "FHFA" in result.source


def test_fhfa_prior_sale_fallback_is_labeled_and_lower_confidence():
    result = estimate_value(
        _subject(raw={"last_sale_price": 700_000, "last_sale_date": "2023-01-01"}),
        [],
        market_pack({"fhfa_hpi_growth_1yr": 5.0}),
    )

    assert result.method == "fhfa_trend"
    assert result.mid > 700_000
    assert result.confidence < 0.5
    assert result.error_band == 0.25
    assert "not a property-level appraisal" in result.source


def test_listing_context_fallback_is_explicitly_weak():
    subject = _subject(
        raw={"listing_context_prices": [850_000, 950_000, 1_050_000]}
    )

    result = estimate_value(subject, [], None)

    assert result.method == "listing_context"
    assert result.n_comps == 3
    assert result.mid == 950_000
    assert result.confidence <= 0.25
    assert "asking-price" in result.source
    assert "not closed sales" in result.source


def test_no_data_returns_none_value_without_crashing():
    result = estimate_value(_subject(), [], None)

    assert result.method == "none"
    assert result.value is None
    assert result.mid is None
    assert result.confidence == 0
