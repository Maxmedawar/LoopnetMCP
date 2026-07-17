"""Coverage 11: permissions are enforced when listing tools AND again at
execution. Hiding a tool from the list is never the only barrier."""

import pytest
from fastmcp.exceptions import ToolError

from tests.access.helpers import call_data, tool_names


async def test_hidden_tool_is_also_denied_at_call_time(
    mini_mcp, identity, ctx_nat
):
    identity["ctx"] = ctx_nat
    assert "generate_loi" not in await tool_names(mini_mcp)
    with pytest.raises(ToolError, match="denied"):
        await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})


async def test_execution_recheck_uses_current_identity_not_prior_listing(
    mini_mcp, identity, ctx_op, ctx_nat
):
    # List as the operator (tool visible), then the connection's resolved
    # identity changes; execution must re-check against the CURRENT identity.
    identity["ctx"] = ctx_op
    assert "generate_loi" in await tool_names(mini_mcp)
    identity["ctx"] = ctx_nat
    with pytest.raises(ToolError, match="denied"):
        await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})


async def test_quota_is_enforced_at_execution(mini_mcp, identity, ctx_tiny, audit):
    # Plan "tiny" allows 2 calls in the "search" bucket per day.
    identity["ctx"] = ctx_tiny
    for _ in range(2):
        data = await call_data(mini_mcp, "search_properties", {"location": "OH"})
        assert data["ok"] is True
    with pytest.raises(ToolError, match="quota"):
        await call_data(mini_mcp, "search_properties", {"location": "OH"})
    events = audit.events(workspace_id="ws-tiny")
    assert any(e.decision == "denied" and "quota" in e.reason for e in events)
