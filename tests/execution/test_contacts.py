"""Free broker/owner contacts, public LLC records, and paid-provider degradation."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.execution.contacts import (
    STATE_SOS_ENDPOINTS,
    RealEstateApiSkiptraceProvider,
    SosLookup,
    find_contact,
)
from cre_mcp.market.base import ProviderUnavailableError
from cre_mcp.models import ParcelRecord
from tests.scoring.builders import deal_context

FIXTURES = Path(__file__).parents[1] / "fixtures" / "execution"


def _ctx():
    ctx = deal_context(
        raw={"brokerEmail": "broker@example.test", "strategy": "nnn_retail"}
    )
    ctx.listing.broker_name = "Jordan Broker"
    ctx.listing.broker_company = "Capstone CRE"
    ctx.listing.broker_phone = "512-555-0100"
    ctx.parcel = ParcelRecord(
        apn="235486",
        site_address="8600 Cross Park Dr, Austin, TX 78754",
        owner_name="ELEGANT AUSTIN LLC",
        owner_mailing_address="26 Stonegate Park Ct, Spring, TX 77379",
    )
    return ctx


@pytest.mark.asyncio
async def test_texas_llc_fixture_maps_registered_agent_and_principals():
    search = json.loads((FIXTURES / "tx_sos_search.json").read_text())
    detail = json.loads((FIXTURES / "tx_sos_detail.json").read_text())
    fetch = AsyncMock()
    fetch.get_json.side_effect = [search, detail]

    result = await SosLookup(fetch).registered_agent("TX", "ELEGANT AUSTIN LLC")

    assert result is not None
    assert result.name == "IMRAN JAMAL"
    assert result.address == "17638 ROSE SUMMIT LN, RICHMOND, TX, 77407"
    assert result.status == "ACTIVE"
    assert {principal.name for principal in result.principals} == {
        "AFTAB AZIZ",
        "ZAHEER SHAIKH",
    }
    assert fetch.get_json.await_count == 2


@pytest.mark.asyncio
async def test_find_contact_assembles_listing_broker_owner_and_registry_sources():
    agent = await SosLookup(
        AsyncMock(
            get_json=AsyncMock(
                side_effect=[
                    json.loads((FIXTURES / "tx_sos_search.json").read_text()),
                    json.loads((FIXTURES / "tx_sos_detail.json").read_text()),
                ]
            )
        )
    ).registered_agent("TX", "ELEGANT AUSTIN LLC")
    sos = AsyncMock()
    sos.registered_agent.return_value = agent
    skiptrace = AsyncMock()
    skiptrace.available = False

    result = await find_contact(_ctx(), sos=sos, skiptrace=skiptrace)

    assert result.broker is not None
    assert result.broker.name == "Jordan Broker"
    assert result.broker.email == "broker@example.test"
    assert result.owner_name == "ELEGANT AUSTIN LLC"
    assert result.entity_type == "llc"
    assert result.registered_agent is not None
    assert result.phones == ["512-555-0100"]
    assert result.emails == ["broker@example.test"]
    assert "county assessor parcel record" in result.sources
    assert any("Texas" in source for source in result.sources)
    assert "confirm every name" in result.disclaimer


@pytest.mark.asyncio
async def test_skiptrace_absence_is_an_empty_nonfatal_coverage_gap():
    provider = RealEstateApiSkiptraceProvider(
        CreConfig(skiptrace_api_key=None),
        fetch=AsyncMock(),
    )
    assert provider.available is False
    with pytest.raises(ProviderUnavailableError):
        await provider.lookup(_ctx())

    ctx = deal_context(raw={})
    result = await find_contact(ctx, skiptrace=provider)
    assert result.skiptrace_available is False
    assert result.phones == []
    assert result.emails == []


@pytest.mark.asyncio
async def test_nonautomated_state_registry_gracefully_skips():
    fetch = AsyncMock()
    result = await SosLookup(fetch).registered_agent("FL", "EXAMPLE OWNER LLC")
    assert result is None
    fetch.get_json.assert_not_awaited()
    assert set(STATE_SOS_ENDPOINTS) == {"TX", "AZ", "NV", "FL", "GA"}
