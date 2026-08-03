"""Fixtures for tenant-aware access control.

Contract under test: .claude/specs/tenant-access-control.md (Addendum B).
Server-side identity only — grants live in WorkspaceRegistry, never in MCP
arguments. `identity` is a mutable holder standing in for the authenticated
connection: tests assign the TenantContext the server resolved, and the
middleware's injected resolver reads it. A resolver returning None models an
unauthenticated cloud connection.
"""

import pytest
from fastmcp import FastMCP

from cre_mcp.access.audit import AuditLog
from cre_mcp.access.middleware import install_access
from cre_mcp.access.profiles import Profile
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.access.territory import location_state


@pytest.fixture
def registry(tmp_path) -> WorkspaceRegistry:
    reg = WorkspaceRegistry(tmp_path / "registry.json")
    reg.add_plan("standard", {})
    reg.add_plan("tiny", {"search": 2})
    reg.add_grant("k-op", "ws-op", Profile.FULL_OPERATOR)
    reg.add_grant("k-op2", "ws-op2", Profile.FULL_OPERATOR)
    reg.add_grant("k-nat", "ws-nat", Profile.NATIONAL_SCOUT)
    reg.add_grant("k-loc", "ws-loc", Profile.LOCAL_SCOUT, territories=("TX",))
    reg.add_grant("k-jv", "ws-jv", Profile.JV_PARTNER, territories=("TX",))
    # The operator's second key: acting with full rights inside the shared
    # JV workspace (JV semantics v1 — a JV is itself a workspace).
    reg.add_grant("k-op-jv", "ws-jv", Profile.FULL_OPERATOR)
    reg.add_grant("k-off", "ws-off", Profile.FULL_OPERATOR, active=False)
    reg.add_grant("k-tiny", "ws-tiny", Profile.NATIONAL_SCOUT, plan="tiny")
    return reg


@pytest.fixture
def audit(tmp_path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl")


@pytest.fixture
def identity() -> dict:
    return {"ctx": None}


@pytest.fixture
def ctx_op(registry):
    return registry.resolve_key("k-op")


@pytest.fixture
def ctx_op2(registry):
    return registry.resolve_key("k-op2")


@pytest.fixture
def ctx_nat(registry):
    return registry.resolve_key("k-nat")


@pytest.fixture
def ctx_loc(registry):
    return registry.resolve_key("k-loc")


@pytest.fixture
def ctx_jv(registry):
    return registry.resolve_key("k-jv")


@pytest.fixture
def ctx_op_jv(registry):
    return registry.resolve_key("k-op-jv")


@pytest.fixture
def ctx_off(registry):
    return registry.resolve_key("k-off")


@pytest.fixture
def ctx_tiny(registry):
    return registry.resolve_key("k-tiny")


@pytest.fixture
def mini_mcp(registry, audit, identity):
    """A small FastMCP app whose fake tools reuse REAL registered tool names,
    so the production capability matrix governs them. Fakes echo the kwargs
    they actually received, which lets tests prove sanitization."""
    app = FastMCP(name="access-test")
    app._access_test_search_received = {}

    @app.tool
    async def search_properties(
        location: str,
        workspace_id: str | None = None,
        role: str | None = None,
        db_path: str | None = None,
    ) -> dict:
        state = location_state(location)
        normalized = location.casefold()
        if state == "TX" and "dallas" in normalized:
            city, zip_code = "Dallas", "75201"
        elif state == "TX":
            city, zip_code = "Houston", "77001"
        elif state == "FL":
            city, zip_code = "Miami", "33101"
        elif state == "NY":
            city, zip_code = "New York", "10001"
        else:
            city, zip_code = "Washington", "20001"
        app._access_test_search_received = {
            "location": location,
            "workspace_id": workspace_id,
            "role": role,
            "db_path": db_path,
        }
        return {
            "query_location": location,
            "query_property_type": None,
            "query_listing_type": None,
            "total_results": 1,
            "page": 1,
            "has_next_page": False,
            "properties": [
                {
                    "name": "Fixture Property",
                    "address": f"100 Main Street, {city}, {state} {zip_code}",
                    "city": city,
                    "state": state or location,
                    "zip_code": zip_code,
                    "url": "https://example.test/property",
                }
            ],
        }

    @app.tool
    async def generate_loi(deal_id: str) -> dict:
        return {"ok": True, "loi_for": deal_id}

    @app.tool
    async def save_deal(url_or_id: str, db_path: str | None = None) -> dict:
        return {"ok": True, "saved": url_or_id, "received_db_path": db_path}

    @app.tool
    async def list_deals() -> dict:
        return {"ok": True, "deals": []}

    @app.tool
    async def totally_unclassified_tool() -> dict:
        return {"ok": True}

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    yield app
    uninstall()


@pytest.fixture
def real_server(registry, audit, identity, tmp_path, monkeypatch):
    """The production server instance with access control installed and
    storage rooted in a temp directory. Legacy/local path: tmp/cache.db;
    cloud workspaces must land under tmp/workspaces/<id>/cache.db."""
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(tmp_path / "cache.db"))
    monkeypatch.delenv("LOOPNET_CACHE_DB_PATH", raising=False)
    from cre_mcp.access.middleware import AccessMiddleware
    from cre_mcp.server import mcp as production_mcp

    saved_middleware = list(production_mcp.middleware)
    production_mcp.middleware[:] = [
        item
        for item in production_mcp.middleware
        if not isinstance(item, AccessMiddleware)
    ]
    uninstall = install_access(
        production_mcp,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    yield production_mcp
    uninstall()
    production_mcp.middleware[:] = saved_middleware
