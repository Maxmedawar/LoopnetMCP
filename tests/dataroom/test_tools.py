"""Plain-function boundary smoke tests (no FastMCP registration)."""

from cre_mcp.dataroom.tools import (
    closing_runway,
    data_room_index,
    init_data_room,
    init_transaction_plan,
    transaction_critical_path,
    update_data_room_item,
)


def test_plain_tools_share_configured_cache_database(dataroom_db):
    room = init_data_room("fixture:tools", "office")
    updated = update_data_room_item(
        "fixture:tools", "offering_memorandum", status="reviewed", assignee="Morgan"
    )
    index = data_room_index("fixture:tools")
    plan = init_transaction_plan("fixture:tools", "office", "2026-08-31")
    path = transaction_critical_path("fixture:tools")
    runway = closing_runway("fixture:tools")

    assert room["deal_type"] == "office"
    assert updated["status"] == "reviewed"
    assert index["initialized"] is True
    assert plan["task_count"] > 0
    assert path["initialized"] is True
    assert runway["closing_date"] == "2026-08-31"
