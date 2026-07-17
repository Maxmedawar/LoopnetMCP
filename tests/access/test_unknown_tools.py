"""Coverage 7: unclassified tools are denied in cloud mode, and the
capability matrix must cover every registered tool exactly."""

import pytest
from fastmcp.exceptions import ToolError

from tests.access.helpers import call_data, tool_names


async def test_unclassified_tool_is_hidden_in_cloud(mini_mcp, identity, ctx_op):
    identity["ctx"] = ctx_op
    assert "totally_unclassified_tool" not in await tool_names(mini_mcp)


async def test_unclassified_tool_call_is_denied_in_cloud(
    mini_mcp, identity, ctx_op
):
    identity["ctx"] = ctx_op
    with pytest.raises(ToolError, match="denied|unclassified"):
        await call_data(mini_mcp, "totally_unclassified_tool")


async def test_matrix_covers_every_registered_tool_exactly():
    from cre_mcp.access.capabilities import CAPABILITIES
    from cre_mcp.server import mcp

    registered = set((await mcp.get_tools()).keys())
    classified = set(CAPABILITIES)
    missing = sorted(registered - classified)
    stale = sorted(classified - registered)
    assert not missing, f"unclassified registered tools: {missing[:10]}..."
    assert not stale, f"matrix entries for unregistered tools: {stale[:10]}..."


async def test_matrix_entries_are_well_formed_and_machine_readable():
    from cre_mcp.access.capabilities import CAPABILITIES, export_matrix
    from cre_mcp.access.profiles import Profile
    from cre_mcp.server import mcp

    tools = await mcp.get_tools()
    matrix = export_matrix()
    valid_profiles = {p.value for p in Profile}
    for name, cap in CAPABILITIES.items():
        assert cap.allowed_profiles, f"{name}: no profile may use the tool"
        assert len(cap.allowed_profiles) == len(set(cap.allowed_profiles)), name
        assert set(cap.allowed_profiles) <= valid_profiles, name
        assert "full_operator" in cap.allowed_profiles, name
        if cap.sensitive or cap.sensitive_params:
            assert cap.approval, f"{name}: sensitive without approval class"
        assert cap.module == tools[name].fn.__module__, f"{name}: stale module"
        # Declared param names must exist on the tool's actual schema, so the
        # matrix cannot silently drift from real signatures.
        schema_props = set(
            (tools[name].parameters or {}).get("properties", {})
        )
        assert set(cap.territory_params) <= schema_props, name
        assert set(cap.sensitive_params) <= schema_props, name
        assert set(cap.preserve_params) <= schema_props, name
        entry = matrix[name]
        for key in (
            "allowed_profiles",
            "sensitive",
            "sensitive_params",
            "territory_params",
            "preserve_params",
            "ownership_relevant",
            "quota",
            "approval",
        ):
            assert key in entry, f"{name} export missing {key}"
