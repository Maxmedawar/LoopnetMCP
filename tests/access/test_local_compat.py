"""Coverage 9: the trusted local workspace preserves current local behavior —
same enforcement code path, but full visibility, no approval friction, the
legacy storage location, and pre-existing records intact."""

from fastmcp import FastMCP

from cre_mcp.access.context import local_context
from cre_mcp.access.middleware import install_access

from tests.access.helpers import call_data, tool_names


async def test_local_workspace_uses_legacy_path_and_preserves_records(
    real_server, identity, tmp_path
):
    # A record written before access control existed:
    from cre_mcp.deals.store import DealStore

    legacy_db = tmp_path / "cache.db"
    await DealStore(db_path=legacy_db).save_search(
        "legacy-box", {"location": "Austin, TX"}, None
    )

    identity["ctx"] = local_context()
    listed = await call_data(real_server, "list_searches")
    assert listed["count"] == 1
    assert listed["searches"][0]["name"] == "legacy-box"

    saved = await call_data(
        real_server, "save_search", {"name": "new-box", "location": "Miami, FL"}
    )
    assert "error" not in saved
    # Still the legacy file — no per-workspace relocation for local:
    assert legacy_db.exists()
    assert not (tmp_path / "workspaces" / "local").exists()


async def test_trusted_local_sees_everything_and_skips_approvals(
    mini_mcp, identity
):
    identity["ctx"] = local_context()
    names = await tool_names(mini_mcp)
    assert "totally_unclassified_tool" in names
    # Sensitive tool executes directly — no approval_required envelope:
    data = await call_data(mini_mcp, "generate_loi", {"deal_id": "d-1"})
    assert data == {"ok": True, "loi_for": "d-1"}


async def test_trusted_local_keeps_explicit_db_path_arguments(
    mini_mcp, identity
):
    identity["ctx"] = local_context()
    data = await call_data(
        mini_mcp,
        "save_deal",
        {"url_or_id": "deal-1", "db_path": "/tmp/explicit-local.db"},
    )
    assert data["received_db_path"] == "/tmp/explicit-local.db"


async def test_hosted_dependency_failure_never_defaults_to_trusted_local(
    registry, audit, monkeypatch
):
    app = FastMCP(name="fail-closed-test")

    @app.tool
    async def generate_loi(deal_id: str) -> dict:
        return {"ok": True, "loi_for": deal_id}

    def dependency_failure():
        raise RuntimeError("request dependency unavailable")

    monkeypatch.setattr(
        "fastmcp.server.dependencies.get_access_token",
        dependency_failure,
    )
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        runtime_mode="http",
        admission_repository=object(),
        domain_repository_provider=object(),
    )
    try:
        names = await tool_names(app)
        assert names == set()
    finally:
        uninstall()


async def test_trusted_local_exists_only_when_stdio_is_explicit(registry, audit):
    app = FastMCP(name="explicit-stdio-test")

    @app.tool
    async def generate_loi(deal_id: str) -> dict:
        return {"ok": True, "loi_for": deal_id}

    fail_closed = install_access(app, registry=registry, audit_log=audit)
    try:
        assert await tool_names(app) == set()
    finally:
        fail_closed()

    explicit_stdio = install_access(
        app,
        registry=registry,
        audit_log=audit,
        runtime_mode="stdio",
    )
    try:
        assert await tool_names(app) == {"generate_loi"}
    finally:
        explicit_stdio()
