"""Coverage 2: records written in one workspace are invisible to every other,
and each cloud workspace gets its own physical database under
<cache root>/workspaces/<workspace_id>/cache.db."""

from tests.access.helpers import call_data


async def test_records_do_not_cross_workspaces(
    real_server, identity, ctx_op, ctx_op2
):
    identity["ctx"] = ctx_op
    saved = await call_data(
        real_server,
        "save_search",
        {"name": "tx buy box", "location": "Houston, TX"},
    )
    assert "error" not in saved
    mine = await call_data(real_server, "list_searches")
    assert mine["count"] == 1

    identity["ctx"] = ctx_op2
    theirs = await call_data(real_server, "list_searches")
    assert theirs["count"] == 0


async def test_cloud_workspace_storage_is_physically_isolated(
    real_server, identity, ctx_op, tmp_path
):
    identity["ctx"] = ctx_op
    await call_data(
        real_server,
        "save_search",
        {"name": "tx buy box", "location": "Houston, TX"},
    )
    workspace_db = tmp_path / "workspaces" / "ws-op" / "cache.db"
    assert workspace_db.exists()
    # The legacy/local database must not have received the cloud record.
    legacy = tmp_path / "cache.db"
    if legacy.exists():
        from cre_mcp.deals.store import DealStore

        assert await DealStore(db_path=legacy).list_searches() == []
