"""Coverage 6: Full Operator approval gate on sensitive transaction actions.

Contract: sensitive call returns {"approval_required": true, "approval_id": ...}
as a RESULT. Approval is granted server-side in the registry. The retry carries
the reserved `_approval_id` argument, verified against (workspace, tool,
args_hash) — all server-side.
"""

import pytest
from fastmcp.exceptions import ToolError

from tests.access.helpers import call_data


async def test_sensitive_tool_requires_approval(mini_mcp, identity, ctx_op):
    identity["ctx"] = ctx_op
    data = await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})
    assert data["approval_required"] is True
    assert data["tool"] == "generate_loi"
    assert data["approval_id"]


async def test_granted_approval_lets_the_same_call_through(
    mini_mcp, identity, ctx_op, registry
):
    identity["ctx"] = ctx_op
    pending = await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})
    registry.grant_approval(pending["approval_id"])
    data = await call_data(
        mini_mcp,
        "generate_loi",
        {"deal_id": "d-1", "_approval_id": pending["approval_id"]},
    )
    assert data == {"ok": True, "loi_for": "d-1"}


async def test_approval_does_not_transfer_to_different_args(
    mini_mcp, identity, ctx_op, registry
):
    identity["ctx"] = ctx_op
    pending = await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})
    registry.grant_approval(pending["approval_id"])
    with pytest.raises(ToolError, match="approval"):
        await call_data(
            mini_mcp,
            "generate_loi",
            {"deal_id": "d-OTHER", "_approval_id": pending["approval_id"]},
        )


async def test_ungrated_or_unknown_approval_id_is_denied(
    mini_mcp, identity, ctx_op
):
    identity["ctx"] = ctx_op
    pending = await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})
    # Not granted yet:
    with pytest.raises(ToolError, match="approval"):
        await call_data(
            mini_mcp,
            "generate_loi",
            {"deal_id": "d-1", "_approval_id": pending["approval_id"]},
        )
    with pytest.raises(ToolError, match="approval"):
        await call_data(
            mini_mcp,
            "generate_loi",
            {"deal_id": "d-1", "_approval_id": "ap-forged"},
        )


async def test_approval_is_workspace_bound(
    mini_mcp, identity, ctx_op, ctx_op_jv, registry
):
    identity["ctx"] = ctx_op
    pending = await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})
    registry.grant_approval(pending["approval_id"])
    # A different workspace cannot spend ws-op's approval.
    identity["ctx"] = ctx_op_jv
    with pytest.raises(ToolError, match="approval"):
        await call_data(
            mini_mcp,
            "generate_loi",
            {"deal_id": "d-1", "_approval_id": pending["approval_id"]},
        )
