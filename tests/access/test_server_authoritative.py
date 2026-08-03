"""Coverage 10: workspace, role, plan, territory, and ownership are server
truth. Client-supplied values in MCP arguments never override them, and
storage-path arguments are stripped in cloud mode."""

import pytest
from fastmcp.exceptions import ToolError

from tests.access.helpers import call_data


async def test_args_cannot_escalate_role_or_territory(
    mini_mcp, identity, ctx_loc
):
    identity["ctx"] = ctx_loc
    # The client CLAIMS to be an operator workspace; server context must win.
    with pytest.raises(ToolError, match="territor"):
        await call_data(
            mini_mcp,
            "search_properties",
            {
                "location": "Miami, FL",
                "workspace_id": "ws-op",
                "role": "full_operator",
            },
        )


async def test_identity_args_are_stripped_before_the_tool_runs(
    mini_mcp, identity, ctx_op
):
    identity["ctx"] = ctx_op
    data = await call_data(
        mini_mcp,
        "search_properties",
        {"location": "TX", "workspace_id": "ws-other", "role": "admin"},
    )
    assert data["received"]["workspace_id"] is None
    assert data["received"]["role"] is None


async def test_db_path_is_stripped_in_cloud_mode(mini_mcp, identity, ctx_op):
    identity["ctx"] = ctx_op
    data = await call_data(
        mini_mcp,
        "save_deal",
        {"url_or_id": "deal-1", "db_path": "/tmp/evil.db"},
    )
    assert data["received_db_path"] is None
