"""Coverage 5: JV workspace authorization and actor-private saved searches."""

import pytest
from fastmcp.exceptions import ToolError

from tests.access.helpers import call_data


async def test_saved_searches_remain_actor_private_inside_the_jv_workspace(
    real_server, identity, ctx_op, ctx_op_jv, ctx_jv
):
    # Operator's private workspace record:
    identity["ctx"] = ctx_op
    await call_data(
        real_server,
        "save_search",
        {"name": "private op box", "location": "Houston, TX"},
    )
    # Operator shares a record by acting inside the JV workspace:
    identity["ctx"] = ctx_op_jv
    await call_data(
        real_server,
        "save_search",
        {"name": "jv shared box", "location": "Dallas, TX"},
    )
    operator_visible = await call_data(real_server, "list_searches")
    assert operator_visible["count"] == 1
    assert operator_visible["searches"][0]["name"] == "jv shared box"

    # Saved searches are private to the actor even inside a shared workspace.
    identity["ctx"] = ctx_jv
    visible = await call_data(real_server, "list_searches")
    assert visible["count"] == 0


async def test_jv_partner_is_territory_limited_on_real_tools(
    real_server, identity, ctx_jv
):
    identity["ctx"] = ctx_jv
    data = await call_data(
        real_server,
        "save_search",
        {"name": "in territory", "location": "Austin, TX"},
    )
    assert "error" not in data
    with pytest.raises(ToolError, match="territor"):
        await call_data(
            real_server,
            "save_search",
            {"name": "out of territory", "location": "Miami, FL"},
        )
