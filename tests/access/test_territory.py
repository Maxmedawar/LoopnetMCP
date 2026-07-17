"""Coverage 3: territory rules for Local Scout and JV Partner.

Grants come only from the registry (TX for both ws-loc and ws-jv). Location
forms: state code, "City, ST", and 5-digit zip.
"""

import pytest
from fastmcp.exceptions import ToolError

from cre_mcp.access.capabilities import ToolCapability
from cre_mcp.access.engine import AccessEngine
from tests.access.helpers import call_data


@pytest.mark.parametrize("location", ["TX", "Houston, TX", "77001"])
async def test_local_scout_allowed_inside_territory(
    mini_mcp, identity, ctx_loc, location
):
    identity["ctx"] = ctx_loc
    data = await call_data(mini_mcp, "search_properties", {"location": location})
    assert data["ok"] is True


@pytest.mark.parametrize("location", ["Miami, FL", "FL", "33101"])
async def test_local_scout_denied_outside_territory(
    mini_mcp, identity, ctx_loc, location
):
    identity["ctx"] = ctx_loc
    with pytest.raises(ToolError, match="territor"):
        await call_data(mini_mcp, "search_properties", {"location": location})


async def test_jv_partner_denied_outside_territory(mini_mcp, identity, ctx_jv):
    identity["ctx"] = ctx_jv
    with pytest.raises(ToolError, match="territor"):
        await call_data(mini_mcp, "search_properties", {"location": "New York, NY"})


async def test_jv_partner_allowed_inside_territory(mini_mcp, identity, ctx_jv):
    identity["ctx"] = ctx_jv
    data = await call_data(mini_mcp, "search_properties", {"location": "Dallas, TX"})
    assert data["ok"] is True


async def test_full_operator_is_not_territory_limited(mini_mcp, identity, ctx_op):
    identity["ctx"] = ctx_op
    data = await call_data(mini_mcp, "search_properties", {"location": "Miami, FL"})
    assert data["ok"] is True


def test_every_location_in_a_list_valued_param_is_checked(registry, ctx_loc):
    capability = ToolCapability(
        tool="compare_markets",
        allowed_profiles=("local_scout",),
        territory_params=("locations",),
    )
    engine = AccessEngine(registry, {"compare_markets": capability})

    allowed, _ = engine.check_call(
        ctx_loc,
        "compare_markets",
        {"locations": ["Dallas, TX", "77001"]},
    )
    denied, _ = engine.check_call(
        ctx_loc,
        "compare_markets",
        {"locations": ["Dallas, TX", "Miami, FL"]},
    )

    assert allowed.outcome == "allowed"
    assert denied.outcome == "denied"
    assert "Miami, FL" in denied.reason


def test_optional_territory_params_require_one_resolvable_value(registry, ctx_loc):
    capability = ToolCapability(
        tool="owner_lookup",
        allowed_profiles=("local_scout",),
        territory_params=("address", "county"),
    )
    engine = AccessEngine(registry, {"owner_lookup": capability})

    missing, _ = engine.check_call(
        ctx_loc,
        "owner_lookup",
        {"apn": "123-456"},
    )
    allowed, _ = engine.check_call(
        ctx_loc,
        "owner_lookup",
        {"address": "100 Main Street", "county": "Harris County, TX"},
    )
    denied, _ = engine.check_call(
        ctx_loc,
        "owner_lookup",
        {"address": "100 Main Street", "county": "Miami-Dade County, FL"},
    )

    assert missing.outcome == "denied"
    assert "territory argument is required" in missing.reason
    assert allowed.outcome == "allowed"
    assert denied.outcome == "denied"
    assert "Miami-Dade County, FL" in denied.reason
