"""Coverage 5: JV records. A JV is itself a workspace: the operator's JV key
writes into it, the JV partner's key reads it — and nothing else."""

import pytest
from fastmcp.exceptions import ToolError

from tests.access.helpers import call_data


async def test_jv_partner_sees_records_shared_into_the_jv_workspace(
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
    # The JV partner sees exactly the JV workspace's records:
    identity["ctx"] = ctx_jv
    visible = await call_data(real_server, "list_searches")
    assert visible["count"] == 1
    assert visible["searches"][0]["name"] == "jv shared box"


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
