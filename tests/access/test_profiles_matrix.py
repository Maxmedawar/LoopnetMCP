"""Coverage 1: each access profile is allowed/denied per the capability matrix."""

import pytest
from fastmcp.exceptions import ToolError

from tests.access.helpers import call_data, tool_names


async def test_full_operator_sees_operator_tools(mini_mcp, identity, ctx_op):
    identity["ctx"] = ctx_op
    names = await tool_names(mini_mcp)
    assert {"search_properties", "generate_loi", "save_deal", "list_deals"} <= names


async def test_national_scout_sees_scouting_only(mini_mcp, identity, ctx_nat):
    identity["ctx"] = ctx_nat
    names = await tool_names(mini_mcp)
    assert "search_properties" in names
    assert "generate_loi" not in names
    assert "save_deal" not in names
    assert "list_deals" not in names


async def test_local_scout_sees_scouting_only(mini_mcp, identity, ctx_loc):
    identity["ctx"] = ctx_loc
    names = await tool_names(mini_mcp)
    assert "search_properties" in names
    assert "generate_loi" not in names
    assert "save_deal" not in names


async def test_jv_partner_sees_scouting_and_jv_records(mini_mcp, identity, ctx_jv):
    identity["ctx"] = ctx_jv
    names = await tool_names(mini_mcp)
    assert "search_properties" in names
    assert "list_deals" in names
    assert "generate_loi" not in names
    assert "save_deal" not in names


async def test_national_scout_can_search_anywhere(mini_mcp, identity, ctx_nat):
    identity["ctx"] = ctx_nat
    data = await call_data(
        mini_mcp, "search_properties", {"location": "Miami, FL"}
    )
    assert data["ok"] is True


async def test_scout_call_to_operator_tool_is_denied(mini_mcp, identity, ctx_nat):
    identity["ctx"] = ctx_nat
    with pytest.raises(ToolError, match="denied"):
        await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})


async def test_jv_partner_call_to_transaction_tool_is_denied(
    mini_mcp, identity, ctx_jv
):
    identity["ctx"] = ctx_jv
    with pytest.raises(ToolError, match="denied"):
        await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})


async def test_unauthenticated_cloud_connection_gets_nothing(mini_mcp, identity):
    identity["ctx"] = None
    assert await tool_names(mini_mcp) == set()
    with pytest.raises(ToolError, match="denied"):
        await call_data(mini_mcp, "search_properties", {"location": "TX"})
