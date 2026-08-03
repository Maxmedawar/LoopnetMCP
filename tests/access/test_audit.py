"""Coverage 8: audit events for allowed, denied, and approval decisions."""

import pytest
from fastmcp.exceptions import ToolError

from tests.access.helpers import call_data, tool_names


async def test_allowed_call_is_audited(mini_mcp, identity, ctx_op, audit):
    identity["ctx"] = ctx_op
    await call_data(mini_mcp, "search_properties", {"location": "TX"})
    events = audit.events(workspace_id="ws-op")
    assert any(
        e.tool == "search_properties" and e.decision == "allowed" for e in events
    )


async def test_denied_call_is_audited_with_reason(
    mini_mcp, identity, ctx_loc, audit
):
    identity["ctx"] = ctx_loc
    with pytest.raises(ToolError):
        await call_data(mini_mcp, "search_properties", {"location": "Miami, FL"})
    events = audit.events(workspace_id="ws-loc")
    denied = [e for e in events if e.decision == "denied"]
    assert denied and denied[-1].reason


async def test_approval_required_is_audited(mini_mcp, identity, ctx_op, audit):
    identity["ctx"] = ctx_op
    await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})
    events = audit.events(workspace_id="ws-op")
    assert any(e.decision == "approval_required" for e in events)


async def test_listing_emits_summary_event(mini_mcp, identity, ctx_nat, audit):
    identity["ctx"] = ctx_nat
    await tool_names(mini_mcp)
    events = audit.events(workspace_id="ws-nat")
    assert any(e.tool == "__list_tools__" for e in events)


async def test_events_carry_timestamp_and_workspace(
    mini_mcp, identity, ctx_op, audit
):
    identity["ctx"] = ctx_op
    await call_data(mini_mcp, "search_properties", {"location": "TX"})
    event = audit.events(workspace_id="ws-op")[-1]
    assert event.ts and event.workspace_id == "ws-op"


async def test_hosted_middleware_sanitizes_every_tool_result(
    mini_mcp,
    identity,
    ctx_op,
):
    identity["ctx"] = ctx_op

    data = await call_data(mini_mcp, "list_deals")

    assert data == {"ok": True, "deals": []}
    assert "fixture-output-secret" not in repr(data)


async def test_denial_reason_and_audit_never_echo_client_credentials(
    mini_mcp,
    identity,
    ctx_loc,
    audit,
):
    secret = "middleware-denial-secret-731"
    identity["ctx"] = ctx_loc

    with pytest.raises(ToolError) as caught:
        await call_data(
            mini_mcp,
            "search_properties",
            {"location": f"Miami, FL token={secret}"},
        )

    assert secret not in str(caught.value)
    events = audit.events(workspace_id=ctx_loc.workspace_id)
    assert secret not in events[-1].reason
