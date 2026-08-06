"""End-to-end enforcement tests for the grouped hosted MCP surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from cre_mcp.access.audit import AuditLog
from cre_mcp.access.context import TenantContext
from cre_mcp.access.middleware import install_access
from cre_mcp.access.profiles import Profile
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.surface import CUSTOMER_SURFACE, build_customer_server
from cre_mcp.surface.server import resolve_surface_call


def _context(
    profile: Profile,
    *,
    quota_limits: dict[str, int] | None = None,
    territories: tuple[str, ...] = (),
) -> TenantContext:
    return TenantContext(
        workspace_id=f"surface-{profile.value}",
        profile=profile,
        quota_limits=quota_limits or {},
        territories=territories,
        actor_id="surface-test-actor",
        session_id="surface-test-session",
    )


def _internal_fixture() -> FastMCP:
    internal = FastMCP(name="surface-internal-fixture")
    internal._search_executions = 0

    @internal.tool(name="search_properties")
    async def search_properties(location: str) -> dict:
        internal._search_executions += 1
        city = "Dallas" if location == "Dallas, TX" else "Miami"
        state = "TX" if location == "Dallas, TX" else "FL"
        zip_code = "75201" if state == "TX" else "33101"
        return {
            "query_location": location,
            "query_property_type": None,
            "query_listing_type": None,
            "total_results": 1,
            "page": 1,
            "has_next_page": False,
            "properties": [
                {
                    "name": "Surface Fixture",
                    "address": f"100 Main Street, {city}, {state} {zip_code}",
                    "city": city,
                    "state": state,
                    "zip_code": zip_code,
                    "url": "https://example.test/property",
                }
            ],
        }

    @internal.tool(name="list_searches")
    async def list_searches() -> dict:
        return {"searches": [], "count": 0}

    @internal.tool(name="cap_cost_context")
    async def cap_cost_context() -> dict:
        return {
            "ok": True,
            "raw": {"authorization": "Bearer must-not-release"},
        }

    @internal.tool(name="generate_loi")
    async def generate_loi(deal_id: str) -> dict:
        return {"ok": True, "deal_id": deal_id}

    return internal


def _installed_surface(
    tmp_path: Path,
    identity: dict,
) -> tuple[FastMCP, WorkspaceRegistry, AuditLog, callable]:
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    audit = AuditLog(tmp_path / "audit.jsonl")
    app = build_customer_server(_internal_fixture())
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _context: identity["ctx"],
        tool_call_resolver=resolve_surface_call,
        tool_visibility_resolver=CUSTOMER_SURFACE.is_visible,
    )
    return app, registry, audit, uninstall


@pytest.mark.parametrize(
    "profile,expected",
    (
        (Profile.LOCAL_SCOUT, 8),
        (Profile.NATIONAL_SCOUT, 10),
        (Profile.FULL_OPERATOR, 20),
        (Profile.JV_PARTNER, 11),
    ),
)
async def test_live_tool_listing_is_profile_specific(
    tmp_path,
    profile,
    expected,
) -> None:
    identity = {"ctx": _context(profile, territories=("TX",))}
    app, _registry, _audit, uninstall = _installed_surface(tmp_path, identity)
    try:
        async with Client(app) as client:
            tools = await client.list_tools()
    finally:
        uninstall()

    assert len(tools) == expected
    assert {tool.name for tool in tools} == set(
        CUSTOMER_SURFACE.visible_names(profile)
    )


async def test_exact_action_keeps_territory_quota_source_rights_and_audit(
    tmp_path,
) -> None:
    identity = {
        "ctx": _context(
            Profile.LOCAL_SCOUT,
            quota_limits={"search": 1},
            territories=("TX",),
        )
    }
    app, _registry, audit, uninstall = _installed_surface(tmp_path, identity)
    try:
        async with Client(app) as client:
            result = await client.call_tool(
                "cre_discover",
                {
                    "action": "search_properties",
                    "arguments": {"location": "Dallas, TX"},
                },
            )
            with pytest.raises(ToolError, match="daily quota exceeded"):
                await client.call_tool(
                    "cre_discover",
                    {
                        "action": "search_properties",
                        "arguments": {"location": "Dallas, TX"},
                    },
                )
            safe = await client.call_tool(
                "cre_finance",
                {"action": "cap_cost_context", "arguments": {}},
            )
    finally:
        uninstall()

    assert result.data["query_location"] == "Dallas, TX"
    assert "raw" not in safe.data
    events = audit.events(identity["ctx"].workspace_id)
    assert any(
        event.tool == "search_properties" and event.decision == "allowed"
        for event in events
    )
    assert any(
        event.tool == "search_properties" and event.decision == "denied"
        for event in events
    )
    assert any(
        event.tool == "cap_cost_context" and event.decision == "allowed"
        for event in events
    )


async def test_out_of_territory_action_is_denied_before_execution(tmp_path) -> None:
    identity = {
        "ctx": _context(Profile.LOCAL_SCOUT, territories=("TX",))
    }
    app, _registry, audit, uninstall = _installed_surface(tmp_path, identity)
    internal = app
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="outside this workspace"):
                await client.call_tool(
                    "cre_discover",
                    {
                        "action": "search_properties",
                        "arguments": {"location": "Miami, FL"},
                    },
                )
    finally:
        uninstall()

    assert any(
        event.tool == "search_properties" and event.decision == "denied"
        for event in audit.events(identity["ctx"].workspace_id)
    )


async def test_approval_is_bound_to_exact_capability_and_arguments(tmp_path) -> None:
    identity = {"ctx": _context(Profile.FULL_OPERATOR)}
    app, registry, audit, uninstall = _installed_surface(tmp_path, identity)
    try:
        async with Client(app) as client:
            pending = await client.call_tool(
                "cre_offer",
                {
                    "action": "generate_loi",
                    "arguments": {"deal_id": "deal-1"},
                },
            )
            approval_id = pending.data["approval_id"]
            assert pending.data["tool"] == "cre_offer"
            assert pending.data["capability_id"] == "generate_loi"
            registry.grant_approval(approval_id)
            approved = await client.call_tool(
                "cre_offer",
                {
                    "action": "generate_loi",
                    "arguments": {
                        "deal_id": "deal-1",
                        "_approval_id": approval_id,
                    },
                },
            )
    finally:
        uninstall()

    assert approved.data == {"ok": True, "deal_id": "deal-1"}
    exact_events = [
        event
        for event in audit.events(identity["ctx"].workspace_id)
        if event.tool == "generate_loi"
    ]
    assert [event.decision for event in exact_events] == [
        "approval_required",
        "allowed",
    ]


async def test_direct_internal_and_unmapped_actions_cannot_bypass_surface(
    tmp_path,
) -> None:
    identity = {"ctx": _context(Profile.FULL_OPERATOR)}
    app, _registry, audit, uninstall = _installed_surface(tmp_path, identity)
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError):
                await client.call_tool(
                    "search_properties",
                    {"location": "Dallas, TX"},
                )
            for action in (
                "find_control_opportunities",
                "generate_loi",
                "totally_unknown_action",
            ):
                with pytest.raises(ToolError, match="grouped action"):
                    await client.call_tool(
                        "cre_discover",
                        {"action": action, "arguments": {}},
                    )
    finally:
        uninstall()

    denied = [event for event in audit.events() if event.decision == "denied"]
    assert denied
    assert all(event.tool != "find_control_opportunities" for event in denied)
