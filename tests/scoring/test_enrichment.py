"""Parcel-aware scoring and analyze_deal confidence coverage."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from cre_mcp.models import OwnerRecord, ParcelRecord, SourceCapabilities
from cre_mcp.scoring.engine import score
from cre_mcp.scoring.rubrics import NNN_RETAIL_RUBRIC
from cre_mcp.scoring.signals import assessor_last_sale_delta, owner_tenure_years
from cre_mcp.tools.deal_tools import analyze_deal
from tests.scoring.builders import deal_context
from tests.tools.test_deal_tools import _geo, _listing, _market


def test_parcel_values_activate_land_sale_and_tenure_signals():
    context = deal_context(
        property_type="retail",
        price=1_500_000,
        raw={"strategy": "nnn_retail"},
        source_id="parcel",
    )
    context.parcel = ParcelRecord(
        site_address="100 Main St, Greensboro, NC 27401",
        owner_name="Owner LLC",
        owner_mailing_address="PO Box 2, Charlotte, NC 28202",
        land_value=750_000,
        last_sale_price=1_000_000,
        last_sale_date="2016-01-01",
    )

    assert assessor_last_sale_delta(context) is not None
    assert owner_tenure_years(context) is not None
    result = score(context, NNN_RETAIL_RUBRIC)
    residual = next(
        item for item in result.rubric_result.signal_results
        if item.key == "residual_value_land"
    )
    assert residual.raw_value == 0.5
    assert residual.missing is False


@pytest.mark.asyncio
async def test_analyze_deal_score_confidence_rises_with_parcel_record():
    listing = _listing("31948105")
    listing.raw.pop("land_value")
    source = Mock(capabilities=SourceCapabilities(detail_is_expensive=True))
    source.get_detail = AsyncMock(return_value=listing)
    fake_registry = Mock()
    fake_registry.get.return_value = source
    market_engine = Mock()
    market_engine.get_market_pack = AsyncMock(return_value=_market())
    parcel = ParcelRecord(
        apn="1",
        site_address="31948105 Congress Ave, Austin, TX 78701",
        owner_name="Long Hold Retail LLC",
        owner_mailing_address="PO Box 5, Dallas, TX 75201",
        land_value=1_000_000,
        last_sale_price=1_500_000,
        last_sale_date="2000-01-01",
    )
    owner = OwnerRecord(
        name="Long Hold Retail LLC",
        normalized_name="LONG HOLD RETAIL LLC",
        entity_type="llc",
        absentee=True,
        mailing_address=parcel.owner_mailing_address,
        parcels=[parcel],
    )
    owner_engine = Mock()
    owner_engine.lookup = AsyncMock(side_effect=[None, owner])

    with patch("cre_mcp.tools.deal_tools.registry", fake_registry), patch(
        "cre_mcp.tools.deal_tools.resolve", new=AsyncMock(return_value=_geo())
    ), patch(
        "cre_mcp.tools.deal_tools._market_engine", return_value=market_engine
    ), patch(
        "cre_mcp.tools.deal_tools._owner_engine", return_value=owner_engine
    ):
        without = await analyze_deal("31948105", strategy="nnn_retail")
        enriched = await analyze_deal("31948105", strategy="nnn_retail")

    assert enriched["parcel"]["apn"] == "1"
    assert enriched["owner"]["absentee"] is True
    assert enriched["scores"][0]["confidence"] > without["scores"][0]["confidence"]
    assert enriched["scores"][0]["score"] > without["scores"][0]["score"]
