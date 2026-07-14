"""Offer recommendation math, motivation, confidence, and missing-data behavior."""

from cre_mcp.execution.offer import recommend_offer
from cre_mcp.models import ParcelRecord
from tests.scoring.builders import deal_context, market_pack


def _context(*, raw=None):
    values = {
        "strategy": "nnn_retail",
        "tenant_credit_rating": "BBB",
        "lease_years_remaining": 12,
    }
    values.update(raw or {})
    return deal_context(
        price=1_100_000,
        noi=70_000,
        raw=values,
        market=market_pack({"treasury_10yr": 4.0, "mortgage_rate": 6.5}),
    )


def test_offer_prices_order_caps_reverse_and_rationale_uses_actual_numbers():
    result = recommend_offer(_context())

    assert result.open_price < result.target_price < result.walk_price
    assert result.open_cap > result.target_cap > result.walk_cap
    assert "$1,100,000" in result.rationale
    assert f"${result.target_price:,.0f}" in result.rationale
    assert "1.25x DSCR" in result.rationale
    assert "current NOI" in result.rationale
    assert result.key_terms["financing_contingency"]["stance"] == (
        "retain_until_written_lender_commitment"
    )


def test_seller_motivation_widens_only_the_opening_buffer():
    baseline = recommend_offer(_context())
    motivated_ctx = _context(
        raw={
            "days_on_market": 180,
            "price_reductions": [{"percent": 5}, {"percent": 3}],
        }
    )
    motivated_ctx.parcel = ParcelRecord(
        site_address="100 Congress Ave, Austin, TX 78701",
        owner_mailing_address="PO Box 1, Denver, CO 80202",
        last_sale_date="2000-01-01",
    )
    motivated = recommend_offer(motivated_ctx)

    baseline_buffer = 1 - baseline.open_price / baseline.target_price
    motivated_buffer = 1 - motivated.open_price / motivated.target_price
    assert motivated.target_price == baseline.target_price
    assert motivated.walk_price == baseline.walk_price
    assert motivated_buffer > baseline_buffer
    assert "absentee ownership" in motivated.rationale
    assert "price cut" in motivated.rationale
    assert "180 days" in motivated.rationale


def test_missing_sale_comps_lowers_confidence_and_is_explicit():
    thin = recommend_offer(_context())
    supported = recommend_offer(_context(raw={"market_value": 1_050_000}))

    assert thin.confidence < supported.confidence
    assert any("Phase 14" in caveat for caveat in thin.caveats)
    assert not any("Phase 14" in caveat for caveat in supported.caveats)


def test_value_add_multifamily_uses_stabilized_yield_on_cost():
    ctx = deal_context(
        property_type="multifamily",
        price=5_000_000,
        noi=250_000,
        raw={
            "strategy": "value_add_multifamily",
            "stabilized_noi": 500_000,
            "renovation_capex": 1_000_000,
        },
    )
    result = recommend_offer(ctx)

    assert result.open_price < result.target_price < result.walk_price
    assert "yield-on-cost" in result.rationale


def test_offer_is_nonfatal_when_price_noi_market_and_comps_are_missing():
    ctx = deal_context(price=None, noi=None, market=None, raw={})
    result = recommend_offer(ctx)

    assert result.open_price is None
    assert result.target_price is None
    assert result.walk_price is None
    assert result.confidence < 0.5
    assert any("NOI is unavailable" in caveat for caveat in result.caveats)
    assert "not legal or financial advice" in result.rationale
