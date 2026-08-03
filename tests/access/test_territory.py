"""Coverage 3: territory rules for Local Scout and JV Partner.

Grants come only from the registry (TX for both ws-loc and ws-jv). Location
forms: state code, "City, ST", and 5-digit zip.
"""

import pytest
from fastmcp.exceptions import ToolError

from cre_mcp.access.capabilities import ToolCapability
from cre_mcp.access.engine import AccessEngine
from cre_mcp.access.territory import (
    city_claim_is_unambiguous,
    city_county_fips,
    city_place_geoids,
    county_cbsa_codes,
    county_fips_for_name,
    county_identity_for_fips,
    non_place_city_county_fips,
    tract_identity_for_geoid,
    tract_zip_codes,
    zip_county_fips,
)
from tests.access.helpers import call_data


@pytest.mark.parametrize("location", ["TX", "Houston, TX", "77001"])
async def test_local_scout_allowed_inside_territory(
    mini_mcp, identity, ctx_loc, location
):
    identity["ctx"] = ctx_loc
    data = await call_data(mini_mcp, "search_properties", {"location": location})
    assert data["properties"][0]["state"] == "TX"


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
    assert data["properties"][0]["state"] == "TX"


async def test_full_operator_is_not_territory_limited(mini_mcp, identity, ctx_op):
    identity["ctx"] = ctx_op
    data = await call_data(mini_mcp, "search_properties", {"location": "Miami, FL"})
    assert data["properties"][0]["state"] == "FL"


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


def test_national_location_authority_reconciles_exact_city_zip_and_cbsa() -> None:
    assert city_county_fips("Seattle", "Washington") == frozenset({"53033"})
    assert city_county_fips("Los Angeles", "ca") == frozenset({"06037"})
    assert zip_county_fips("98101-1234 USA") == frozenset({"53033"})
    assert zip_county_fips("90001") == frozenset({"06037"})
    assert county_cbsa_codes("53033") == frozenset({"42660"})
    assert county_cbsa_codes("06037") == frozenset({"31080"})


def test_national_location_authority_preserves_multi_county_relationships() -> None:
    assert city_county_fips("Austin", "TX") == frozenset(
        {"48021", "48209", "48453", "48491"}
    )
    assert zip_county_fips("30102") == frozenset({"13015", "13057", "13067"})


def test_national_place_authority_preserves_identity_and_fails_closed_on_ambiguity() -> None:
    assert city_place_geoids("Austin", "TX") == frozenset({"4805000"})
    assert city_claim_is_unambiguous("Austin", "TX") is True
    assert city_place_geoids("Burbank", "CA") == frozenset(
        {"0608954", "0608968"}
    )
    assert city_claim_is_unambiguous("Burbank", "CA") is False
    assert city_place_geoids(
        "Burbank", "CA", county_fips="06037", zip_value="91502"
    ) == frozenset({"0608954"})
    assert city_place_geoids(
        "Pewaukee", "WI", county_fips="55133", zip_value="53072"
    ) == frozenset({"5562240", "5562250"})
    assert city_claim_is_unambiguous(
        "Pewaukee", "WI", county_fips="55133", zip_value="53072"
    ) is False
    assert non_place_city_county_fips("Washington", "DC") == frozenset(
        {"11001"}
    )
    assert city_claim_is_unambiguous(
        "Washington", "DC", county_fips="11001"
    ) is True
    assert city_claim_is_unambiguous(
        "Washington", "DC", county_fips="11003"
    ) is False


def test_national_tract_authority_requires_exact_existence_and_zip_relation() -> None:
    assert tract_identity_for_geoid("48453000700") == ("TX", "48453")
    assert tract_zip_codes("48453000700") == frozenset({"78701", "78712"})
    assert tract_identity_for_geoid("48113000000") is None
    assert tract_identity_for_geoid("48113999999") is None
    assert tract_zip_codes("48113999999") == frozenset()


def test_national_county_authority_keeps_county_equivalents_unambiguous() -> None:
    assert county_fips_for_name("Baltimore County", "MD") == frozenset({"24005"})
    assert county_fips_for_name("Baltimore city", "Maryland") == frozenset({"24510"})
    assert county_fips_for_name("Orleans Parish", "LA") == frozenset({"22071"})
    assert county_fips_for_name("Anchorage Municipality", "AK") == frozenset(
        {"02020"}
    )
    assert county_identity_for_fips("24510") == ("MD", "Baltimore city")


def test_national_location_authority_fails_closed_for_unknown_relations() -> None:
    assert city_county_fips("Atlantis", "WA") == frozenset()
    assert zip_county_fips("00000") == frozenset()
    assert county_fips_for_name("Atlantis County", "CA") == frozenset()
    assert county_identity_for_fips("99999") is None
    assert county_cbsa_codes("99999") == frozenset()
