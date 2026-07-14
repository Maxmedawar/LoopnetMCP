"""End-to-end owner_lookup tool boundary."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from cre_mcp.models import OwnerRecord, ParcelRecord
from cre_mcp.server import mcp
from cre_mcp.tools.owner_tools import owner_lookup


def _owner() -> OwnerRecord:
    parcel = ParcelRecord(
        apn="1",
        site_address="100 A S ELM ST, NC",
        owner_name="SIT-IN MOVEMENT INC",
        owner_mailing_address="134 S ELM ST, GREENSBORO, NC, 27401",
        assessed_value=7_987_248,
        land_value=2_909_800,
        last_sale_date="2022-04-01",
        year_built=1983,
        use_code="OFFICE",
    )
    return OwnerRecord(
        name="SIT-IN MOVEMENT INC",
        normalized_name="SIT IN MOVEMENT INC",
        entity_type="corp",
        absentee=False,
        mailing_address=parcel.owner_mailing_address,
        parcels=[parcel],
    )


@pytest.mark.asyncio
async def test_owner_lookup_returns_normalized_owner_record():
    engine = Mock()
    engine.lookup = AsyncMock(return_value=_owner())
    with patch("cre_mcp.tools.owner_tools._engine", return_value=engine):
        result = await owner_lookup(
            address="100 A S Elm St",
            county="Guilford County, NC",
        )

    assert "error" not in result
    assert result["normalized_name"] == "SIT IN MOVEMENT INC"
    assert result["entity_type"] == "corp"
    assert result["parcels"][0]["land_value"] == 2_909_800
    engine.lookup.assert_awaited_once_with(
        address="100 A S Elm St",
        apn=None,
        county="Guilford County, NC",
    )


@pytest.mark.asyncio
async def test_owner_lookup_returns_error_dict_for_missing_record():
    engine = Mock()
    engine.lookup = AsyncMock(return_value=None)
    with patch("cre_mcp.tools.owner_tools._engine", return_value=engine):
        result = await owner_lookup(apn="missing", county="Guilford County, NC")
    assert result == {"error": "No configured county parcel record found"}


@pytest.mark.asyncio
async def test_owner_lookup_is_registered_with_the_nineteen_tool_suite():
    tools = await mcp.get_tools()
    assert "owner_lookup" in tools
    assert len(tools) == 23
