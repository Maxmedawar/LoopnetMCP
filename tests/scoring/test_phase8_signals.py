"""Phase 8 public-data attributes activate formerly missing signals."""

from cre_mcp.models import DealAttributes, MetricValue, RentComps
from cre_mcp.scoring.engine import score
from cre_mcp.scoring.rubrics import NNN_RETAIL_RUBRIC
from cre_mcp.scoring.signals import parking_adequacy, rent_gap_to_market, traffic_count
from tests.scoring.builders import deal_context, market_pack


def test_traffic_rent_gap_and_parking_compute_when_enrichment_is_present():
    context = deal_context(
        property_type="multifamily",
        raw={"in_place_rent_monthly": 1760},
    )
    context.attributes = DealAttributes(
        traffic_aadt=42_000,
        drive_thru=True,
        parking="80 Spaces (4.0/1,000 SF)",
        size_sqft=20_000,
    )
    context.rent_comps = RentComps(
        geo=market_pack().geo,
        market_rent_estimate=MetricValue(
            value=2200,
            unit="USD/month",
            source="Zillow ZORI",
        ),
    )

    assert traffic_count(context) == 42_000
    assert rent_gap_to_market(context) == 20.0
    assert parking_adequacy(context) == 4.0


def test_attribute_enrichment_increases_nnn_signal_coverage():
    context = deal_context(
        raw={
            "tenant_credit_rating": "A",
            "lease_years_remaining": 12,
        }
    )
    baseline = score(context, NNN_RETAIL_RUBRIC)
    context.attributes = DealAttributes(
        traffic_aadt=35_000,
        drive_thru=True,
        parking="4.5/1,000 SF",
        size_sqft=5_000,
    )
    enriched = score(context, NNN_RETAIL_RUBRIC)

    assert enriched.confidence > baseline.confidence
    for key in ("traffic_count", "visibility_corner", "parking_adequacy"):
        signal = next(
            item for item in enriched.rubric_result.signal_results if item.key == key
        )
        assert signal.missing is False
