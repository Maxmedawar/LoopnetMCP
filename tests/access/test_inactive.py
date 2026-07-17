"""Coverage 4: inactive access — a suspended grant is denied everything."""

import pytest
from fastmcp.exceptions import ToolError

from tests.access.helpers import call_data, tool_names


async def test_inactive_grant_lists_no_tools(mini_mcp, identity, ctx_off):
    identity["ctx"] = ctx_off
    assert await tool_names(mini_mcp) == set()


async def test_inactive_grant_calls_are_denied(mini_mcp, identity, ctx_off):
    identity["ctx"] = ctx_off
    with pytest.raises(ToolError, match="inactive|denied"):
        await call_data(mini_mcp, "search_properties", {"location": "TX"})


async def test_inactive_denial_is_audited(mini_mcp, identity, ctx_off, audit):
    identity["ctx"] = ctx_off
    with pytest.raises(ToolError):
        await call_data(mini_mcp, "search_properties", {"location": "TX"})
    events = audit.events(workspace_id="ws-off")
    assert any(
        e.tool == "search_properties" and e.decision == "denied" for e in events
    )
