"""Round-seven protocol regressions for authoritative US location requests.

Every case crosses the real FastMCP ``Client`` boundary and the production
``install_access`` middleware path.  The payloads are production-shaped but
contain only synthetic property data.
"""

from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from cre_mcp.access.engine import RESULT_TERRITORY_DENIAL
from cre_mcp.access.middleware import install_access
from cre_mcp.models.comps import SaleComp, ValueEstimate
from cre_mcp.models.enrichment import OwnerRecord, ParcelRecord
from cre_mcp.models.listings import PropertySummary, SearchResult


_RESTRICTED_CONTEXT_FIXTURES = ("ctx_loc", "ctx_jv")

_AMBIGUOUS_CENSUS_PLACE_REQUESTS = (
    (
        "Burbank, CA",
        "Burbank",
        "CA",
        "91502",
        "100 First Street",
        "same-name-place-without-zip",
    ),
    (
        "Chevy Chase, MD 20815",
        "Chevy Chase",
        "MD",
        "20815",
        "100 Wisconsin Avenue",
        "zip-still-matches-two-places-md",
    ),
    (
        "Pewaukee, WI 53072",
        "Pewaukee",
        "WI",
        "53072",
        "100 Main Street",
        "county-and-zip-still-match-two-places-wi",
    ),
    (
        "Superior, WI 54880",
        "Superior",
        "WI",
        "54880",
        "100 Tower Avenue",
        "zip-still-matches-two-places-wi",
    ),
)

_POSTAL_EXACT_ZIP_CONTROLS = (
    ("Bronx", "NY", "10451", "100 Main Street", "postal-borough-bronx"),
    (
        "Staten Island",
        "NY",
        "10301",
        "100 Stuyvesant Place",
        "postal-borough-staten-island",
    ),
    ("Burbank", "CA", "91502", "100 First Street", "zip-disambiguates-burbank"),
)

_STATE_NAME_CITY_CONTROLS = (
    ("Washington", "DC", "20001", "100 Main Street"),
    ("New York", "NY", "10001", "100 Broadway"),
)

_DIGIT_BEARING_PLACE_CONTROLS = (
    ("Route 7 Gateway", "CT", "06877"),
    ("Kickapoo Site 1", "KS", "66439"),
    ("Kickapoo Site 2", "KS", "66439"),
    ("Kickapoo Site 5", "KS", "66439"),
    ("Kickapoo Site 7", "KS", "66439"),
    ("Kickapoo Site 6", "KS", "66527"),
)

_INVALID_COLLECTION_MEMBERS = (
    pytest.param(None, id="null-member"),
    pytest.param(7, id="non-string-member"),
    pytest.param("   ", id="blank-member"),
)

_UNRESOLVED_SCALAR_TAIL_CASES = (
    ("TX; Miami", "state-semicolon-city"),
    ("TX; Unknown", "state-semicolon-unknown"),
    ("TX / N/A", "state-slash-na"),
    ("Texas; Miami", "state-name-semicolon-city"),
    ("75201; Miami", "zip-semicolon-city"),
    ("Dallas, TX; Miami", "city-state-semicolon-city"),
    ("Dallas, TX; 90 Ocean Drive", "city-state-semicolon-street"),
    ("Dallas, TX / 90 Ocean Drive", "city-state-slash-street"),
    ("Dallas, TX and 90 Ocean Drive", "city-state-and-street"),
)

_SCALAR_PREFIX_ESCAPE_CASES = (
    ("Dallas, TX & Miami", "scalar-city-state-ampersand-city"),
    ("Dallas, TX to Miami", "scalar-city-state-to-city"),
    ("Dallas, TX then Miami", "scalar-city-state-then-city"),
    ("Dallas, TX, Miami", "scalar-city-state-comma-city"),
    ("Dallas, TX: Miami", "scalar-city-state-colon-city"),
    ("Dallas, TX • Miami", "scalar-city-state-bullet-city"),
    ("Dallas, TX -> Miami", "scalar-city-state-arrow-city"),
    ("Dallas, TX—Miami", "scalar-city-state-em-dash-city"),
    ("75201 & Miami", "scalar-zip-ampersand-city"),
    ("75201 to Miami", "scalar-zip-to-city"),
    ("Unknown & 75201", "scalar-unknown-ampersand-zip"),
    ("Miami to 75201", "scalar-city-to-zip"),
    ("Miami, 75201", "scalar-city-comma-zip"),
    ("Unknown: 75201", "scalar-unknown-colon-zip"),
    ("75201 USA extra", "scalar-zip-country-extra"),
    ("Dallas, TX near 75201", "scalar-city-state-near-zip"),
)

_UNRESOLVED_SCALAR_TAIL_CASES += _SCALAR_PREFIX_ESCAPE_CASES

_SCALAR_CITY_STATE_ZIP_CONTROLS = (
    ("Dallas, TX: 75201", "scalar-city-state-colon-zip"),
    ("Dallas, TX zip 75201", "scalar-city-state-zip-label"),
)

_OBFUSCATED_OUT_OF_SCOPE_STATE_FORMS = (
    ("F.L.", "dot"),
    ("F L", "space"),
    ("F-L", "hyphen"),
    ("F/L", "slash"),
    ("F_L", "underscore"),
    ("F•L", "bullet"),
)

_ADDRESS_COMPOUND_TAIL_CASES = (
    ("; Miami", "semicolon-city"),
    (" and Unknown", "and-unknown"),
    (" / N/A", "slash-na"),
    ("; 90 Ocean Drive", "semicolon-second-street"),
    (" / 90 Ocean Drive", "slash-second-street"),
    (" and 90 Ocean Drive", "and-second-street"),
) + tuple(
    (f"{separator}Miami {state_form}", f"{separator_id}-{state_id}")
    for separator, separator_id in (
        ("; ", "semicolon-obfuscated-fl"),
        (" / ", "slash-obfuscated-fl"),
        (" and ", "and-obfuscated-fl"),
    )
    for state_form, state_id in _OBFUSCATED_OUT_OF_SCOPE_STATE_FORMS
)

_INCOMPLETE_ADDRESS_WITH_SAFE_COUNTY_CASES = (
    ("90 Ocean Drive, Miami", "comma-city"),
    ("90 Ocean Drive, Unknown", "comma-unknown"),
    ("90 Ocean Drive, N/A", "comma-na"),
    ("90 Ocean Drive Miami", "space-city"),
    ("90 Ocean Drive Unknown", "space-unknown"),
    ("90 Ocean Drive N/A", "space-na"),
    ("90 Ocean Drive in Miami", "in-city"),
    ("90 Ocean Drive near Miami", "near-city"),
)

_SAFE_STREET_COMPONENT_CONTROLS = (
    ("90 Ocean Drive", "street-only"),
    ("90 Ocean Drive, Suite 200", "comma-suite"),
    ("90 Ocean Drive Suite 200", "space-suite"),
    ("90 Ocean Drive Unit 200", "space-unit"),
)

_SAFE_COMPLETE_ADDRESS_SUFFIX_CONTROLS = (
    (", Suite 200", "comma-suite"),
    (", Unit 200", "comma-unit"),
    (" USA", "country"),
    (" 75201 USA", "zip-country"),
)

_PROPERTY_ADDRESS_PREFIX_FAILURES = (
    (
        "Miami & 100 Main Street, Dallas, TX 75201",
        "property-prefix-miami-ampersand",
    ),
    (
        "Unknown to 100 Main Street, Dallas, TX 75201",
        "property-prefix-unknown-to",
    ),
    (
        "Miami, 100 Main Street, Dallas, TX 75201",
        "property-prefix-miami-comma",
    ),
    (
        "Unknown: 100 Main Street, Dallas, TX 75201",
        "property-prefix-unknown-colon",
    ),
    (
        "Miami • 100 Main Street, Dallas, TX 75201",
        "property-prefix-miami-bullet",
    ),
    (
        "Miami -> 100 Main Street, Dallas, TX 75201",
        "property-prefix-miami-arrow",
    ),
    (
        "Miami—100 Main Street, Dallas, TX 75201",
        "property-prefix-miami-em-dash",
    ),
    (
        "Unknown\n100 Main Street, Dallas, TX 75201",
        "property-prefix-unknown-newline",
    ),
    (
        "90 Ocean Drive and 100 Main Street, Dallas, TX 75201",
        "property-prefix-second-street-and",
    ),
    (
        "90 Ocean Drive; 100 Main Street, Dallas, TX 75201",
        "property-prefix-second-street-semicolon",
    ),
    (
        "90 Ocean Drive / 100 Main Street, Dallas, TX 75201",
        "property-prefix-second-street-slash",
    ),
)

_PROPERTY_ADDRESS_PREFIX_CONTROLS = (
    (
        "100 Main Street, Dallas, TX 75201",
        "property-prefix-control-full-address",
    ),
    (
        "100 Main Street Suite 200, Dallas, TX 75201",
        "property-prefix-control-suite",
    ),
    (
        "100 Main Street, Unit 200, Dallas, TX 75201",
        "property-prefix-control-unit",
    ),
    (
        "100 NE 2nd Avenue, Dallas, TX 75201",
        "property-prefix-control-directional",
    ),
)

_INCOMPLETE_PROPERTY_ADDRESS_RESULTS = (
    ("TX", "state-code"),
    ("Texas", "state-name"),
    ("Dallas, TX", "city-state"),
    ("75201", "zip"),
    ("100 Main Street, TX", "street-state"),
    ("100 Main Street, 75201", "street-zip"),
)

_COMPLETE_PROPERTY_ADDRESS_CONTROLS = (
    ("100 Main Street, Dallas, TX", "city-state"),
    ("100 Main Street, Dallas, TX 75201", "zip"),
    ("100 Main Street, Dallas, Texas 75201 USA", "state-name-country"),
    ("100 Main Street Suite 200, Dallas, TX 75201", "unit"),
    ("100 Main Street, Ste. 200, Dallas, TX", "dotted-ste"),
    ("100 Main Street #200, Dallas, TX", "bare-unit"),
    ("100 Main Street, #200, Dallas, TX", "comma-bare-unit"),
    ("100 Main Street, 2nd Floor, Dallas, TX", "ordinal-floor"),
)

_STRUCTURED_ADDRESS_HIDDEN_TAIL_CASES = (
    ("90 Ocean Drive Miami, Dallas, TX", "city"),
    ("90 Ocean Drive Unknown, Dallas, TX", "unknown"),
    ("90 Ocean Drive N/A, Dallas, TX", "na"),
    ("90 Ocean Drive near Miami, Dallas, TX", "near-city"),
)

_STRUCTURED_ADDRESS_HIDDEN_TAIL_CONTROLS = (
    ("90 Ocean Drive Suite 200, Dallas, TX", "unit"),
    ("90 Ocean Drive, Ste. 200, Dallas, TX", "dotted-ste"),
    ("90 Ocean Drive #200, Dallas, TX", "bare-unit"),
    ("90 Ocean Drive, #200, Dallas, TX", "comma-bare-unit"),
    ("90 Ocean Drive, 2nd Floor, Dallas, TX", "ordinal-floor"),
)

_EXACT_DALLAS_GRANTS = (
    ("Dallas, TX", "city"),
    ("75201", "zip"),
)


async def _call_production_shaped_search(
    registry,
    audit,
    identity,
    *,
    location: str,
    city: str,
    state: str,
    zip_code: str,
    street_address: str,
    extra_properties: tuple[PropertySummary, ...] = (),
    executions: list[int] | None = None,
) -> tuple[Any, list[int]]:
    """Call a synthetic search through the production access middleware."""

    if executions is None:
        executions = [0]
    app = FastMCP(name="territory-round-seven-geography")

    @app.tool
    async def search_properties(location: str) -> dict:
        executions[0] += 1
        return SearchResult(
            query_location=location,
            properties=[
                PropertySummary(
                    name="Synthetic Geography Fixture",
                    address=street_address,
                    city=city,
                    state=state,
                    zip_code=zip_code,
                    url="https://example.test/property",
                ),
                *extra_properties,
            ],
        ).model_dump(mode="json")

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool(
                "search_properties",
                {"location": location},
            )
    finally:
        uninstall()
    return result, executions


async def _call_owner_lookup_fixture(
    registry,
    audit,
    identity,
    *,
    arguments: dict[str, Any],
    site_address: str,
    executions: list[int] | None = None,
    include_parcel: bool = True,
) -> tuple[Any, list[int]]:
    """Call a typed owner result through the production access boundary."""

    if executions is None:
        executions = [0]
    app = FastMCP(name="territory-round-seven-owner")

    @app.tool
    async def owner_lookup(
        address: str | None = None,
        apn: str | None = None,
        county: str | None = None,
    ) -> dict[str, Any]:
        del address, apn, county
        executions[0] += 1
        return OwnerRecord(
            name="Synthetic Geography Owner",
            normalized_name="SYNTHETIC GEOGRAPHY OWNER",
            entity_type="company",
            parcels=(
                [ParcelRecord(site_address=site_address)]
                if include_parcel
                else []
            ),
        ).model_dump(mode="json")

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool("owner_lookup", arguments)
    finally:
        uninstall()
    return result, executions


async def _call_get_comps_fixture(
    registry,
    audit,
    identity,
    *,
    county_fips: str,
    comp_address: str,
    subject_address: str = "100 Main Street",
    subject_city: str = "Dallas",
    subject_state: str = "TX",
    subject_zip: str = "75201",
    executions: list[int] | None = None,
) -> tuple[Any, list[int]]:
    """Call a typed county comp result through the production boundary."""

    if executions is None:
        executions = [0]
    app = FastMCP(name="territory-round-seven-county-sale")
    estimate = ValueEstimate(
        value=1_000_000,
        low=900_000,
        mid=1_000_000,
        high=1_100_000,
        method="county_comps",
        n_comps=1,
        confidence=0.75,
        error_band=0.10,
        source="Synthetic protocol fixture",
    )

    @app.tool
    async def get_comps(url_or_id: str) -> dict[str, Any]:
        del url_or_id
        executions[0] += 1
        comp = SaleComp(
            source="Synthetic County",
            county_fips=county_fips,
            parcel_id="fixture-comp",
            address=comp_address,
            sale_price=900_000,
        )
        return {
            "subject": {
                "source": "fixture",
                "source_id": "subject-1",
                "address": subject_address,
                "city": subject_city,
                "state": subject_state,
                "zip_code": subject_zip,
                "asking_price": None,
            },
            "value_estimate": estimate.model_dump(mode="json"),
            "value_provenance": {
                "method": estimate.method,
                "confidence": estimate.confidence,
                "n_comps": estimate.n_comps,
            },
            "comps": [comp.model_dump(mode="json")],
            "explanation": "Synthetic protocol fixture",
            "coverage_note": "Synthetic protocol fixture",
        }

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool(
                "get_comps",
                {
                    "url_or_id": (
                        f"{subject_address}, {subject_city}, "
                        f"{subject_state} {subject_zip}"
                    )
                },
            )
    finally:
        uninstall()
    return result, executions


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "city,state,zip_code,street_address",
    _STATE_NAME_CITY_CONTROLS,
    ids=("washington-dc", "new-york-ny"),
)
async def test_exact_state_name_city_grant_releases_split_location_record(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    city,
    state,
    zip_code,
    street_address,
):
    """Separate typed fields are sufficient when every exact claim agrees."""

    location = f"{city}, {state}"
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (location,)}
    )

    result, executions = await _call_production_shaped_search(
        registry,
        audit,
        identity,
        location=location,
        city=city,
        state=state,
        zip_code=zip_code,
        street_address=street_address,
    )

    assert executions == [1]
    assert result.data["properties"][0]["address"] == street_address
    assert result.data["properties"][0]["city"] == city
    assert result.data["properties"][0]["state"] == state
    assert result.data["properties"][0]["zip_code"] == zip_code


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "city,state,zip_code",
    _DIGIT_BEARING_PLACE_CONTROLS,
    ids=(
        "route-7-gateway",
        "kickapoo-site-1",
        "kickapoo-site-2",
        "kickapoo-site-5",
        "kickapoo-site-7",
        "kickapoo-site-6",
    ),
)
async def test_exact_digit_bearing_place_grant_executes_and_releases(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    city,
    state,
    zip_code,
):
    """Pinned Census place names containing digits remain exact locations."""

    location = f"{city}, {state}"
    street_address = "100 Main Street"
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (location,)}
    )

    result, executions = await _call_production_shaped_search(
        registry,
        audit,
        identity,
        location=location,
        city=city,
        state=state,
        zip_code=zip_code,
        street_address=street_address,
    )

    assert executions == [1]
    assert result.data["properties"][0]["city"] == city
    assert result.data["properties"][0]["zip_code"] == zip_code


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("invalid_member", _INVALID_COLLECTION_MEMBERS)
async def test_list_valued_territory_param_rejects_every_invalid_member(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    invalid_member,
):
    """A valid sibling cannot hide an invalid member from request enforcement."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    app = FastMCP(name="territory-round-seven-collection-members")

    @app.tool
    async def compare_markets(locations: list[Any]) -> dict[str, Any]:
        del locations
        executions[0] += 1
        return {"markets": [], "errors": {}, "count": 0}

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="access denied"):
                await client.call_tool(
                    "compare_markets",
                    {"locations": ["Dallas, TX", invalid_member]},
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "location",
    [
        pytest.param(location, id=case_id)
        for location, case_id in _UNRESOLVED_SCALAR_TAIL_CASES
    ],
)
async def test_scalar_location_rejects_every_unresolved_compound_tail_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    location,
):
    """A valid leading claim cannot hide an unresolved compound suffix."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    app = FastMCP(name="territory-round-seven-scalar-tail")

    @app.tool
    async def search_properties(location: str) -> dict[str, Any]:
        executions[0] += 1
        return SearchResult(
            query_location=location,
            properties=[
                PropertySummary(
                    name="Synthetic Dallas Fixture",
                    address="100 Main Street",
                    city="Dallas",
                    state="TX",
                    zip_code="75201",
                    url="https://example.test/property",
                )
            ],
        ).model_dump(mode="json")

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool("search_properties", {"location": location})
    finally:
        uninstall()

    expected_denial = (
        f"access denied: {location!r} is outside this workspace's territory"
    )
    assert str(caught.value) == expected_denial
    event = audit.events(identity["ctx"].workspace_id)[-1]
    assert event.tool == "search_properties"
    assert event.decision == "denied"
    assert event.reason == expected_denial
    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "location",
    [
        pytest.param(location, id=case_id)
        for location, case_id in _SCALAR_CITY_STATE_ZIP_CONTROLS
    ],
)
async def test_scalar_city_state_zip_combinations_normalize_and_release(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    location,
):
    """Unambiguous, authoritative city/state/ZIP combinations remain valid."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    result, executions = await _call_production_shaped_search(
        registry,
        audit,
        identity,
        location=location,
        city="Dallas",
        state="TX",
        zip_code="75201",
        street_address="100 Main Street",
    )

    assert executions == [1]
    assert result.data["query_location"] == location
    assert result.data["properties"][0]["city"] == "Dallas"
    assert result.data["properties"][0]["zip_code"] == "75201"


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "tail",
    [
        pytest.param(tail, id=case_id)
        for tail, case_id in _ADDRESS_COMPOUND_TAIL_CASES
    ],
)
async def test_owner_result_rejects_every_unresolved_or_obfuscated_address_tail(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    tail,
):
    """An address result must account for every suffix after its locality."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    with pytest.raises(ToolError) as caught:
        await _call_owner_lookup_fixture(
            registry,
            audit,
            identity,
            arguments={"county": "Dallas County, TX"},
            site_address=f"100 Main Street, Dallas, TX{tail}",
            executions=executions,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "site_address",
    [
        pytest.param(site_address, id=case_id)
        for site_address, case_id in _PROPERTY_ADDRESS_PREFIX_FAILURES
    ],
)
async def test_owner_result_rejects_every_unresolved_property_address_prefix(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    site_address,
):
    """A safe trailing property address cannot hide an unresolved prefix."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    with pytest.raises(ToolError) as caught:
        await _call_owner_lookup_fixture(
            registry,
            audit,
            identity,
            arguments={"county": "Dallas County, TX"},
            site_address=site_address,
            executions=executions,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "site_address",
    [
        pytest.param(site_address, id=case_id)
        for site_address, case_id in _PROPERTY_ADDRESS_PREFIX_CONTROLS
    ],
)
async def test_owner_result_releases_single_address_unit_and_directional_controls(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    site_address,
):
    """Valid property-address syntax remains releasable after prefix hardening."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    result, executions = await _call_owner_lookup_fixture(
        registry,
        audit,
        identity,
        arguments={"county": "Dallas County, TX"},
        site_address=site_address,
    )

    assert executions == [1]
    assert result.data["parcels"][0]["site_address"] == site_address


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "address",
    [
        pytest.param(address, id=case_id)
        for address, case_id in _INCOMPLETE_ADDRESS_WITH_SAFE_COUNTY_CASES
    ],
)
async def test_incomplete_address_is_not_rescued_by_safe_county_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    address,
):
    """A supplied incomplete locality is invalid even beside a safe county."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    with pytest.raises(ToolError, match="access denied"):
        await _call_owner_lookup_fixture(
            registry,
            audit,
            identity,
            arguments={"address": address, "county": "Dallas County, TX"},
            site_address="100 Main Street, Dallas, TX 75201",
            executions=executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "address",
    [
        pytest.param(address, id=case_id)
        for address, case_id in _SAFE_STREET_COMPONENT_CONTROLS
    ],
)
async def test_safe_street_component_with_county_executes_and_releases(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    address,
):
    """Street-only and unit-only components remain valid with a safe county."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    result, executions = await _call_owner_lookup_fixture(
        registry,
        audit,
        identity,
        arguments={"address": address, "county": "Dallas County, TX"},
        site_address="100 Main Street, Dallas, TX 75201",
    )

    assert executions == [1]
    assert result.data["parcels"][0]["site_address"].endswith("TX 75201")


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param(suffix, id=case_id)
        for suffix, case_id in _SAFE_COMPLETE_ADDRESS_SUFFIX_CONTROLS
    ],
)
async def test_complete_address_suffix_controls_still_release(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    suffix,
):
    """Unit and country suffixes do not become false compound escapes."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    site_address = f"100 Main Street, Dallas, TX{suffix}"
    result, executions = await _call_owner_lookup_fixture(
        registry,
        audit,
        identity,
        arguments={"county": "Dallas County, TX"},
        site_address=site_address,
    )

    assert executions == [1]
    assert result.data["parcels"][0]["site_address"] == site_address


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "site_address",
    [
        pytest.param(site_address, id=case_id)
        for site_address, case_id in _INCOMPLETE_PROPERTY_ADDRESS_RESULTS
    ],
)
async def test_owner_result_rejects_incomplete_property_address(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    site_address,
):
    """A parcel site address must identify a street and complete locality."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    with pytest.raises(ToolError) as caught:
        await _call_owner_lookup_fixture(
            registry,
            audit,
            identity,
            arguments={"county": "Dallas County, TX"},
            site_address=site_address,
            executions=executions,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "site_address",
    [
        pytest.param(site_address, id=case_id)
        for site_address, case_id in _COMPLETE_PROPERTY_ADDRESS_CONTROLS
    ],
)
async def test_owner_result_releases_complete_property_address_control(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    site_address,
):
    """Complete normalized property addresses remain releasable."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    result, executions = await _call_owner_lookup_fixture(
        registry,
        audit,
        identity,
        arguments={"county": "Dallas County, TX"},
        site_address=site_address,
    )

    assert executions == [1]
    assert result.data["parcels"][0]["site_address"] == site_address


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "location,city,state,zip_code,street_address,_case_id",
    _AMBIGUOUS_CENSUS_PLACE_REQUESTS,
    ids=[case[-1] for case in _AMBIGUOUS_CENSUS_PLACE_REQUESTS],
)
async def test_ambiguous_same_name_city_grant_fails_closed_before_release(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    location,
    city,
    state,
    zip_code,
    street_address,
    _case_id,
):
    """A city grant cannot collapse distinct same-name Census places."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (location,)}
    )
    executions = [0]
    with pytest.raises(ToolError):
        await _call_production_shaped_search(
            registry,
            audit,
            identity,
            location=location,
            city=city,
            state=state,
            zip_code=zip_code,
            street_address=street_address,
            executions=executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
async def test_one_place_spanning_multiple_counties_remains_releasable(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """One place GEOID remains exact even when the place spans counties."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("Austin, TX",)}
    )
    result, executions = await _call_production_shaped_search(
        registry,
        audit,
        identity,
        location="Austin, TX",
        city="Austin",
        state="TX",
        zip_code="78701",
        street_address="100 Congress Avenue",
    )

    assert executions == [1]
    assert result.data["properties"][0]["city"] == "Austin"


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "city,state,zip_code,street_address,_case_id",
    _POSTAL_EXACT_ZIP_CONTROLS,
    ids=[case[-1] for case in _POSTAL_EXACT_ZIP_CONTROLS],
)
@pytest.mark.parametrize("grant_kind", ("state", "zip"))
async def test_exact_postal_city_zip_results_remain_releasable(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    city,
    state,
    zip_code,
    street_address,
    _case_id,
    grant_kind,
):
    """Exact ZIP claims anchor postal localities without Census place rows."""

    territory = state if grant_kind == "state" else zip_code
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    result, executions = await _call_production_shaped_search(
        registry,
        audit,
        identity,
        location=zip_code,
        city=city,
        state=state,
        zip_code=zip_code,
        street_address=street_address,
    )

    assert executions == [1]
    assert result.data["properties"][0]["zip_code"] == zip_code


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
async def test_owner_result_requires_at_least_one_validated_parcel(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """Property-derived owner identity cannot leave without a location anchor."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    with pytest.raises(ToolError) as caught:
        await _call_owner_lookup_fixture(
            registry,
            audit,
            identity,
            arguments={"county": "Dallas County, TX"},
            site_address="100 Main Street, Dallas, TX 75201",
            executions=executions,
            include_parcel=False,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "territory",
    [
        pytest.param(territory, id=case_id)
        for territory, case_id in _EXACT_DALLAS_GRANTS
    ],
)
async def test_county_sale_rejects_county_fips_that_conflicts_with_address(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    territory,
):
    """A forged exact address cannot make a sibling county comp releasable."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]
    with pytest.raises(ToolError) as caught:
        await _call_get_comps_fixture(
            registry,
            audit,
            identity,
            county_fips="48201",
            comp_address="101 Main Street, Dallas, TX 75201",
            executions=executions,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
async def test_county_sale_rejects_city_zip_county_without_common_intersection(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """A multi-county ZIP cannot make an incompatible city county releasable."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("00601",)}
    )
    executions = [0]
    with pytest.raises(ToolError) as caught:
        await _call_get_comps_fixture(
            registry,
            audit,
            identity,
            county_fips="72141",
            comp_address="101 Main Street, Adjuntas, PR 00601",
            subject_city="Adjuntas",
            subject_state="PR",
            subject_zip="00601",
            executions=executions,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "territory",
    [
        pytest.param(territory, id=case_id)
        for territory, case_id in _EXACT_DALLAS_GRANTS
    ],
)
async def test_county_sale_releases_reconciled_county_address_control(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    territory,
):
    """A known Dallas county/address pair remains releasable."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    result, executions = await _call_get_comps_fixture(
        registry,
        audit,
        identity,
        county_fips="48113",
        comp_address="101 Main Street, Dallas, TX 75201",
    )

    assert executions == [1]
    assert result.data["comps"][0]["county_fips"] == "48113"


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "street_address",
    [
        pytest.param(street_address, id=case_id)
        for street_address, case_id in _STRUCTURED_ADDRESS_HIDDEN_TAIL_CASES
    ],
)
async def test_structured_result_rejects_hidden_locality_inside_street_segment(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    street_address,
):
    """Sibling city/state fields cannot rescue an invalid street suffix."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    with pytest.raises(ToolError) as caught:
        await _call_production_shaped_search(
            registry,
            audit,
            identity,
            location="Dallas, TX",
            city="Dallas",
            state="TX",
            zip_code="75201",
            street_address=street_address,
            executions=executions,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "street_address",
    [
        pytest.param(street_address, id=case_id)
        for street_address, case_id in _STRUCTURED_ADDRESS_HIDDEN_TAIL_CONTROLS
    ],
)
async def test_structured_result_releases_unit_inside_street_segment_control(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    street_address,
):
    """A recognized unit between street and locality remains valid."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    result, executions = await _call_production_shaped_search(
        registry,
        audit,
        identity,
        location="Dallas, TX",
        city="Dallas",
        state="TX",
        zip_code="75201",
        street_address=street_address,
    )

    assert executions == [1]
    assert result.data["properties"][0]["address"] == street_address


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "street_address",
    [
        pytest.param(street_address, id=case_id)
        for street_address, case_id in _STRUCTURED_ADDRESS_HIDDEN_TAIL_CASES
    ],
)
async def test_structured_request_rejects_hidden_locality_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    street_address,
):
    """The shared typed record policy rejects the same ambiguity on input."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    app = FastMCP(name="territory-round-seven-structured-request")

    @app.tool
    async def find_control_opportunities(
        listings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        del listings
        executions[0] += 1
        return {"opportunities": [], "count": 0, "methodology": "fixture"}

    listing = {
        "source": "fixture",
        "source_id": "structured-request-1",
        "name": "Synthetic Structured Request",
        "address": street_address,
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
        "url": "https://example.test/property",
        "raw": {},
    }
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="access denied"):
                await client.call_tool(
                    "find_control_opportunities",
                    {"listings": [listing]},
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "street_address",
    [
        pytest.param(street_address, id=case_id)
        for street_address, case_id in _STRUCTURED_ADDRESS_HIDDEN_TAIL_CONTROLS
    ],
)
async def test_structured_request_unit_control_executes(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    street_address,
):
    """The stricter input grammar preserves a recognized unit suffix."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    app = FastMCP(name="territory-round-seven-structured-request-control")

    @app.tool
    async def find_control_opportunities(
        listings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        del listings
        executions[0] += 1
        return {"opportunities": [], "count": 0, "methodology": "fixture"}

    listing = {
        "source": "fixture",
        "source_id": "structured-request-control-1",
        "name": "Synthetic Structured Request",
        "address": street_address,
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
        "url": "https://example.test/property",
        "raw": {},
    }
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool(
                "find_control_opportunities",
                {"listings": [listing]},
            )
    finally:
        uninstall()

    assert executions == [1]
    assert result.data == {
        "opportunities": [],
        "count": 0,
        "methodology": "fixture",
    }


def test_round_seven_geography_protocol_case_count_is_release_locked() -> None:
    new_case_matrices = (
        _SCALAR_PREFIX_ESCAPE_CASES,
        _SCALAR_CITY_STATE_ZIP_CONTROLS,
        _PROPERTY_ADDRESS_PREFIX_FAILURES,
        _PROPERTY_ADDRESS_PREFIX_CONTROLS,
    )
    new_case_ids = [case_id for matrix in new_case_matrices for _, case_id in matrix]
    new_payload_signatures = [
        payload for matrix in new_case_matrices for payload, _ in matrix
    ]

    assert len(_SCALAR_PREFIX_ESCAPE_CASES) == 16
    assert len(_SCALAR_CITY_STATE_ZIP_CONTROLS) == 2
    assert len(_PROPERTY_ADDRESS_PREFIX_FAILURES) == 11
    assert len(_PROPERTY_ADDRESS_PREFIX_CONTROLS) == 4
    assert len(new_case_ids) == len(set(new_case_ids))
    assert len(new_payload_signatures) == len(set(new_payload_signatures))
    assert len(_STATE_NAME_CITY_CONTROLS) == 2
    assert len(_DIGIT_BEARING_PLACE_CONTROLS) == 6
    authoritative_place_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * (
        len(_STATE_NAME_CITY_CONTROLS) + len(_DIGIT_BEARING_PLACE_CONTROLS)
    )
    invalid_collection_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _INVALID_COLLECTION_MEMBERS
    )
    unresolved_scalar_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _UNRESOLVED_SCALAR_TAIL_CASES
    )
    scalar_city_state_zip_controls = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _SCALAR_CITY_STATE_ZIP_CONTROLS
    )
    unresolved_address_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _ADDRESS_COMPOUND_TAIL_CASES
    )
    property_address_prefix_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _PROPERTY_ADDRESS_PREFIX_FAILURES
    )
    property_address_prefix_controls = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _PROPERTY_ADDRESS_PREFIX_CONTROLS
    )
    incomplete_address_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _INCOMPLETE_ADDRESS_WITH_SAFE_COUNTY_CASES
    )
    street_control_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _SAFE_STREET_COMPONENT_CONTROLS
    )
    suffix_control_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _SAFE_COMPLETE_ADDRESS_SUFFIX_CONTROLS
    )
    incomplete_property_result_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _INCOMPLETE_PROPERTY_ADDRESS_RESULTS
    )
    complete_property_control_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _COMPLETE_PROPERTY_ADDRESS_CONTROLS
    )
    structured_hidden_tail_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _STRUCTURED_ADDRESS_HIDDEN_TAIL_CASES
    )
    structured_hidden_tail_controls = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _STRUCTURED_ADDRESS_HIDDEN_TAIL_CONTROLS
    )
    structured_request_hidden_tail_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _STRUCTURED_ADDRESS_HIDDEN_TAIL_CASES
    )
    structured_request_controls = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _STRUCTURED_ADDRESS_HIDDEN_TAIL_CONTROLS
    )
    empty_owner_result_cases = len(_RESTRICTED_CONTEXT_FIXTURES)
    county_sale_conflict_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _EXACT_DALLAS_GRANTS
    )
    county_sale_control_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * len(
        _EXACT_DALLAS_GRANTS
    )
    assert authoritative_place_cases == 16
    assert invalid_collection_cases == 6
    assert unresolved_scalar_cases == 50
    assert scalar_city_state_zip_controls == 4
    assert unresolved_address_cases == 48
    assert property_address_prefix_cases == 22
    assert property_address_prefix_controls == 8
    assert incomplete_address_cases == 16
    assert street_control_cases == 8
    assert suffix_control_cases == 8
    assert incomplete_property_result_cases == 12
    assert complete_property_control_cases == 16
    assert structured_hidden_tail_cases == 8
    assert structured_hidden_tail_controls == 10
    assert structured_request_hidden_tail_cases == 8
    assert structured_request_controls == 10
    assert empty_owner_result_cases == 2
    assert county_sale_conflict_cases == 4
    assert county_sale_control_cases == 4
    assert (
        authoritative_place_cases
        + invalid_collection_cases
        + unresolved_scalar_cases
        + scalar_city_state_zip_controls
        + unresolved_address_cases
        + property_address_prefix_cases
        + property_address_prefix_controls
        + incomplete_address_cases
        + street_control_cases
        + suffix_control_cases
        + incomplete_property_result_cases
        + complete_property_control_cases
        + structured_hidden_tail_cases
        + structured_hidden_tail_controls
        + structured_request_hidden_tail_cases
        + structured_request_controls
        + empty_owner_result_cases
        + county_sale_conflict_cases
        + county_sale_control_cases
    ) == 260
