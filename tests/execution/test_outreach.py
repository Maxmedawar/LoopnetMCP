"""Deterministic channel and angle outreach coaching."""

import pytest

from cre_mcp.execution.outreach import draft_outreach
from cre_mcp.models import BrokerContact, ContactInfo, ListingFacts
from tests.scoring.builders import deal_context


def _ctx():
    ctx = deal_context(
        price=1_100_000,
        noi=70_000,
        size=4_000,
        raw={"strategy": "nnn_retail", "tenant_credit_rating": "BBB"},
    )
    ctx.facts = ListingFacts(
        tenant_name="Example Tenant",
        lease_years_remaining=12,
        nnn_purity="absolute",
        strategy_hint="nnn_retail",
    )
    return ctx


def _contact():
    return ContactInfo(
        broker=BrokerContact(
            name="Jordan Broker",
            company="Capstone CRE",
            phone="512-555-0100",
        ),
        owner_name="ELEGANT AUSTIN LLC",
        owner_mailing="26 Stonegate Park Ct, Spring, TX 77379",
        entity_type="llc",
        disclaimer="fixture",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["call", "email", "letter"])
@pytest.mark.parametrize(
    "angle",
    ["buyer_direct", "via_broker", "absentee_owner", "off_market"],
)
async def test_every_channel_and_angle_is_complete_deal_specific_and_guarded(channel, angle):
    result = await draft_outreach(_ctx(), channel, angle, contact=_contact())

    assert result.channel == channel
    assert result.angle == angle
    assert "100 Congress Ave" in result.script
    assert "$" in result.value_hook
    assert result.opener and result.ask
    assert len(result.objection_lines) >= 3
    assert result.script.endswith(result.guardrail)
    assert "not legal or financial advice" in result.guardrail
    assert (result.subject is None) is (channel == "call")


@pytest.mark.asyncio
async def test_unknown_outreach_values_are_rejected():
    with pytest.raises(ValueError, match="channel"):
        await draft_outreach(_ctx(), "text", contact=_contact())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="angle"):
        await draft_outreach(
            _ctx(),
            "email",
            "pressure_seller",  # type: ignore[arg-type]
            contact=_contact(),
        )
