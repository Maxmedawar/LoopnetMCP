"""Post-result territory enforcement for location-bearing search records."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.tool import ToolResult
from mcp.types import Annotations, TextContent

from cre_mcp.access.context import local_context
from cre_mcp.access.engine import RESULT_TERRITORY_DENIAL
from cre_mcp.access.middleware import install_access
from cre_mcp.access.result_models import (
    CoverageSummary,
    DealAnalysisResult,
    MarketIntelResult,
)
from cre_mcp.comps.records import COUNTY_SALES_ENDPOINTS, map_sale_comp
from cre_mcp.compliance import tools as compliance_tools
from cre_mcp.enrichment.counties import COUNTY_PARCEL_ENDPOINTS
from cre_mcp.geo.resolver import GeoResolver, project_for_release
from cre_mcp.models import Deal, OwnerRecord, ParcelRecord, RentComps, ValueEstimate
from cre_mcp.models.geo import GeoLevel, GeoRef
from cre_mcp.models.listings import (
    AggregatedSearchResult,
    Listing,
    MarketOverview,
    PropertySummary,
    SearchResult,
)
from cre_mcp.sources.crexi.mapping import map_asset
from cre_mcp.siteintel import tools as siteintel_tools
from cre_mcp.tools.deal_tools import _geo_from_listing
from cre_mcp.tools import market_tools, owner_tools

_LIMITED_CONTEXT_FIXTURES = ("ctx_loc", "ctx_jv")
_RESULT_COLLECTIONS = ("properties", "listings")

# These are the exact release failures reproduced by the independent protocol
# review.  Keep the case tables and the count assertion together so reducing
# either matrix is an explicit test failure, not a quiet loss of coverage.
_CROSS_PROFILE_PROTOCOL_ESCAPES = (
    (
        "country-text",
        {
            "address": "Miami FL USA",
            "city": "Dallas",
            "state": "TX",
            "zip_code": None,
            "name": "Miami location fixture",
        },
    ),
    (
        "city-state-portland-or",
        {
            "address": "Portland OR",
            "city": "Dallas",
            "state": "TX",
            "zip_code": None,
            "name": "Portland location fixture",
        },
    ),
    (
        "city-state-omaha-ne",
        {
            "address": "Omaha NE",
            "city": "Dallas",
            "state": "TX",
            "zip_code": None,
            "name": "Omaha location fixture",
        },
    ),
    (
        "city-state-indianapolis-in",
        {
            "address": "Indianapolis IN",
            "city": "Dallas",
            "state": "TX",
            "zip_code": None,
            "name": "Indianapolis location fixture",
        },
    ),
    (
        "omitted-required-location",
        {
            "state": "TX",
            "name": "Omitted location fixture",
            "_omit": ("address", "city", "zip_code"),
        },
    ),
    (
        "null-required-location",
        {
            "address": None,
            "city": None,
            "state": "TX",
            "zip_code": None,
            "name": "Null location fixture",
        },
    ),
)

_EXACT_GRANT_PROTOCOL_ESCAPES = (
    (
        "country-state",
        {
            "address": "Miami FL USA",
            "city": "Dallas",
            "state": "TX",
            "zip_code": "75201",
            "name": "Miami state fixture",
        },
    ),
    (
        "bare-city-state",
        {
            "address": "Portland OR",
            "city": "Dallas",
            "state": "TX",
            "zip_code": "75201",
            "name": "Portland state fixture",
        },
    ),
    (
        "full-state-name",
        {
            "address": "Miami Florida USA",
            "city": "Dallas",
            "state": "TX",
            "zip_code": "75201",
            "name": "Florida state fixture",
        },
    ),
    (
        "bare-zip-country",
        {
            "address": "Miami 33101 USA",
            "city": "Dallas",
            "state": "TX",
            "zip_code": "75201",
            "name": "Miami ZIP fixture",
        },
    ),
)

_EXACT_GRANT_CASES = (
    ("state", "TX", "TX"),
    ("city", "Dallas, TX", "Dallas, TX"),
    ("zip", "75201", "75201"),
)

_INCOMPLETE_CITY_VALUES = (
    "TX",
    "Texas",
    "75201",
    "Dallas USA",
    "Miami USA",
    "Dallas United States",
    "Dallas 75201",
    "Dallas 75201 USA",
)

_COMPLETE_CITY_VALUES = (
    "Dallas",
    "Dallas, TX",
    "dallas texas USA",
    "Dallas TX 75201",
    "Dallas, Texas 75201 USA",
)

_NON_ASCII_ZIP_VALUES = (
    "７５２０１",
    "٧٥٢٠١",
    "７５２０１-４３２１",
    "٧٥٢٠١-٤٣٢١",
)

_NON_ASCII_QUERY_LOCATIONS = (
    "７５２０１",
    "٧٥٢٠١",
    "７５２０１-４３２１",
    "٧٥٢٠١-٤٣٢١",
    "Dallas TX ７５２０１",
    "Dallas TX ٧٥٢٠١-٤٣٢١ USA",
)

_ASCII_QUERY_LOCATION_CONTROLS = (
    "75201",
    "75201-4321",
    "Dallas TX 75201",
    "Dallas TX 75201-4321 USA",
)

_STREET_TAIL_ZIP_CONTROLS = (
    "123 Oak Ct 75201",
    "123 Main St IN 75201",
    "123 Main St NE 75201",
    "123 Main St OR 75201",
)

_FULL_STATE_NAME_COLLISION_CONTROLS = (
    ("city-prefix", "MO", "100 Main Street Kansas City MO", "Kansas City", "MO"),
    ("street-name", "TX", "100 Texas Avenue Dallas TX", "Dallas", "TX"),
    (
        "city-and-street-names",
        "DC",
        "100 New York Avenue Washington DC",
        "Washington",
        "DC",
    ),
)

_LABELED_AND_TERMINATED_LOCATION_ESCAPES = (
    (
        "labeled-zip",
        "ZIP 33101, 90 Ocean Drive",
        "ZIP 33101, 100 Main Street, Dallas, TX 75201",
    ),
    (
        "labeled-postal-code",
        "Postal Code 33101; 90 Ocean Drive",
        "Postal Code 33101; 100 Main Street, Dallas, TX 75201",
    ),
    (
        "full-state-zip-and-separator",
        "Miami Florida 33101 and 90 Ocean Drive",
        "Miami Florida 33101 and 100 Main Street Dallas Texas 75201",
    ),
    (
        "full-state-zip-plus-separator",
        "Miami Florida 33101 + 90 Ocean Drive",
        "Miami Florida 33101 + 100 Main Street Dallas Texas 75201",
    ),
)

_BARE_ASCII_LOCATION_ESCAPES = (
    ("zip-code-label", "ZIP Code 33101, 100 Main Street Dallas TX 75201"),
    ("zipcode-label", "Zipcode 33101, 100 Main Street Dallas TX 75201"),
    ("bare-leading-zip", "33101 100 Main Street Dallas TX 75201"),
    (
        "ampersand-separator",
        "Miami Florida 33101 & 100 Main Street Dallas TX 75201",
    ),
    (
        "to-separator",
        "Miami Florida 33101 to 100 Main Street Dallas TX 75201",
    ),
)

_FULL_STATE_PROSE_ESCAPES = (
    ("ampersand", "Miami Florida & 100 Main Street Dallas TX 75201"),
    ("to", "Miami Florida to 100 Main Street Dallas TX 75201"),
    ("period", "Miami Florida. 100 Main Street Dallas TX 75201"),
    ("then", "Miami Florida then 100 Main Street Dallas TX 75201"),
)

_UNICODE_FORMAT_LOCATION_ESCAPES = (
    (
        "zero-width-space-in-zip",
        "Miami FL 33\u200b101, 100 Main Street Dallas TX 75201",
    ),
    (
        "zero-width-space-in-state",
        "Miami F\u200bL 33101, 100 Main Street Dallas TX 75201",
    ),
    (
        "word-joiner-in-zip",
        "Miami Florida 33\u2060101, 100 Main Street Dallas TX 75201",
    ),
)

_EXACT_CITY_ZIP_CONTRADICTIONS = (
    (
        "city-grant-wrong-zip",
        "Dallas, TX",
        "Dallas, TX 78701",
        "Dallas",
        "78701",
    ),
    (
        "zip-grant-wrong-city",
        "75201",
        "Austin, TX 75201",
        "Austin",
        "75201",
    ),
)

_USPS_CITY_ZIP_CONTROLS = (
    ("Dallas, TX", "Dallas", "TX", "75201"),
    ("Austin, TX", "Austin", "TX", "78701"),
    ("Washington, DC", "Washington", "DC", "20001"),
    ("Fishers Island, NY", "Fishers Island", "NY", "06390"),
    ("St. Louis, MO", "St. Louis", "MO", "63101"),
)

_SHARED_ZIP_CENSUS_PLACE_CONTROLS = (
    ("University Park", "TX", "75205"),
    ("Highland Park", "TX", "75205"),
    ("West Lake Hills", "TX", "78746"),
    ("Jersey Village", "TX", "77040"),
    ("Bal Harbour", "FL", "33154"),
)

_STATE_NAME_STREET_TYPE_CONTROLS = (
    ("square", "One Washington Square", "San Jose", "CA", "95192"),
    ("plaza", "100 Texas Plaza", "Dallas", "TX", "75201"),
    ("highway", "100 California Highway", "Dallas", "TX", "75201"),
)


def _legacy_result(
    *records: PropertySummary,
    error: str | None = None,
    query_location: str = "Dallas, TX",
) -> dict:
    result = SearchResult(
        query_location=query_location,
        properties=list(records),
    ).model_dump(mode="json")
    if error is not None:
        result["error"] = error
    return result


def _aggregate_result(
    *records: Listing,
    error: str | None = None,
    query_location: str = "Dallas, TX",
) -> dict:
    result = AggregatedSearchResult(
        query_location=query_location,
        listings=list(records),
    ).model_dump(mode="json")
    if error is not None:
        result["error"] = error
    return result


def _property(
    *,
    state: str = "TX",
    address: str = "100 Main Street, Dallas, TX",
    city: str = "Dallas",
    zip_code: str | None = "75201",
) -> PropertySummary:
    return PropertySummary(
        name="Fixture Property",
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        url="https://example.test/property",
    )


def _listing(
    *,
    state: str = "TX",
    address: str = "200 Main Street, Dallas, TX",
    city: str = "Dallas",
    zip_code: str | None = "75202",
    raw: dict[str, Any] | None = None,
) -> Listing:
    return Listing(
        source="fixture",
        source_id="listing-1",
        name="Fixture Listing",
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        url="https://example.test/listing",
        raw=raw or {},
    )


def _collection_result(
    collection: str,
    *,
    state: str,
    address: str,
    city: str,
    zip_code: str | None,
    raw: dict[str, Any] | None = None,
    query_location: str = "Dallas, TX",
) -> dict:
    if collection == "properties":
        return _legacy_result(
            _property(
                state=state,
                address=address,
                city=city,
                zip_code=zip_code,
            ),
            query_location=query_location,
        )
    return _aggregate_result(
        _listing(
            state=state,
            address=address,
            city=city,
            zip_code=zip_code,
            raw=raw,
        ),
        query_location=query_location,
    )


def _typed_record_dict(collection: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Build one real property/listing record, then apply a malformed mutation."""
    if collection == "properties":
        record = _property().model_dump(mode="json")
    else:
        record = _listing().model_dump(mode="json")
    omitted = changes.get("_omit", ())
    record.update({key: value for key, value in changes.items() if key != "_omit"})
    for key in omitted:
        record.pop(key, None)
    return record


def _typed_collection_payload(
    collection: str,
    record: dict[str, Any],
    *,
    query_location: str = "Dallas, TX",
) -> dict[str, Any]:
    """Place a possibly malformed record in an otherwise real result envelope."""
    if collection == "properties":
        payload = _legacy_result(_property())
    else:
        payload = _aggregate_result(_listing())
    payload["query_location"] = query_location
    payload[collection] = [record]
    return payload


async def _call_search(
    registry,
    audit,
    identity,
    result: Any | Callable[[], Any],
    location: str = "Dallas, TX",
):
    """Run a real FastMCP call so middleware receives an actual ToolResult."""
    app = FastMCP(name="result-territory-test")

    @app.tool
    async def search_properties(location: str):
        return result() if callable(result) else result

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            return await client.call_tool(
                "search_properties", {"location": location}
            )
    finally:
        uninstall()


async def _call_owner_lookup(
    registry,
    audit,
    identity,
    args: dict[str, Any],
    executions: list[int],
):
    """Run owner_lookup through the real FastMCP request middleware path."""
    app = FastMCP(name="owner-request-territory-test")

    @app.tool
    async def owner_lookup(
        address: str | None = None,
        apn: str | None = None,
        county: str | None = None,
    ):
        del address, apn, county
        executions[0] += 1
        site_address = {
            "DC": "100 Main Street, Washington, DC 20001",
            "MO": "100 Main Street, Kansas City, MO 64106",
            "NC": "100 Main Street, Charlotte, NC 28202",
            "TX": "100 Main Street, Dallas, TX 75201",
        }.get(
            identity["ctx"].territories[0],
            "100 Main Street, Dallas, TX 75201",
        )
        return OwnerRecord(
            name="Request Territory Fixture",
            normalized_name="REQUEST TERRITORY FIXTURE",
            entity_type="company",
            parcels=[ParcelRecord(site_address=site_address)],
        ).model_dump(mode="json")

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            return await client.call_tool("owner_lookup", args)
    finally:
        uninstall()


async def _call_market_overview(
    registry,
    audit,
    identity,
    location: str,
    executions: list[int],
):
    """Run a real single-location market tool through request middleware."""
    app = FastMCP(name="market-request-territory-test")

    @app.tool
    async def get_market_overview(location: str):
        executions[0] += 1
        return MarketOverview(
            location=location,
            total_listings=0,
            sample_listings=[],
        ).model_dump(mode="json")

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            return await client.call_tool(
                "get_market_overview",
                {"location": location},
            )
    finally:
        uninstall()


async def _call_protocol_tool(
    registry,
    audit,
    identity,
    *,
    tool_name: str,
    tool: Callable[..., Any],
    arguments: dict[str, Any],
):
    """Call one named fake through the same FastMCP access path as production."""
    app = FastMCP(name=f"{tool_name}-result-territory-test")
    app.tool(name=tool_name)(tool)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            return await client.call_tool(tool_name, arguments)
    finally:
        uninstall()


async def _assert_generic_result_denial(
    registry,
    audit,
    identity,
    result,
    *,
    location: str = "Dallas, TX",
    secrets: tuple[str, ...] = (),
) -> None:
    workspace = identity["ctx"].workspace_id
    before = len(
        [event for event in audit.events(workspace) if event.tool == "search_properties"]
    )

    with pytest.raises(ToolError) as caught:
        await _call_search(
            registry,
            audit,
            identity,
            result,
            location=location,
        )

    events = [
        event for event in audit.events(workspace) if event.tool == "search_properties"
    ]
    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert len(events) == before + 1
    assert events[-1].decision == "denied"
    assert events[-1].reason == RESULT_TERRITORY_DENIAL
    for secret in secrets:
        assert secret not in str(caught.value)
        assert secret not in events[-1].reason


def test_protocol_regression_matrix_counts_are_permanent():
    for cases in (
        _CROSS_PROFILE_PROTOCOL_ESCAPES,
        _EXACT_GRANT_PROTOCOL_ESCAPES,
    ):
        assert len({case[0] for case in cases}) == len(cases)
        assert len(
            {
                json.dumps(case[1], sort_keys=True, separators=(",", ":"))
                for case in cases
            }
        ) == len(cases)
    assert len(set(_LIMITED_CONTEXT_FIXTURES)) == len(_LIMITED_CONTEXT_FIXTURES)
    assert len(set(_RESULT_COLLECTIONS)) == len(_RESULT_COLLECTIONS)
    assert len({case[0] for case in _EXACT_GRANT_CASES}) == len(
        _EXACT_GRANT_CASES
    )
    assert len({case[1] for case in _EXACT_GRANT_CASES}) == len(
        _EXACT_GRANT_CASES
    )
    assert (
        len(_LIMITED_CONTEXT_FIXTURES)
        * len(_RESULT_COLLECTIONS)
        * len(_CROSS_PROFILE_PROTOCOL_ESCAPES)
        == 24
    )
    assert (
        len(_LIMITED_CONTEXT_FIXTURES)
        * len(_EXACT_GRANT_CASES)
        * len(_RESULT_COLLECTIONS)
        * len(_EXACT_GRANT_PROTOCOL_ESCAPES)
        == 48
    )
    assert (
        len(_LIMITED_CONTEXT_FIXTURES)
        * len(_RESULT_COLLECTIONS)
        * 3  # address, city, state
        * 4  # omitted, null, empty, non-string
        == 48
    )
    assert len(_LIMITED_CONTEXT_FIXTURES) * len(_RESULT_COLLECTIONS) == 4
    assert len(_INCOMPLETE_CITY_VALUES) == 8
    assert len(_COMPLETE_CITY_VALUES) == 5
    assert len(_NON_ASCII_ZIP_VALUES) == 4
    assert len(_NON_ASCII_QUERY_LOCATIONS) == 6
    assert len(_ASCII_QUERY_LOCATION_CONTROLS) == 4
    assert len(_STREET_TAIL_ZIP_CONTROLS) == 4
    assert len(_FULL_STATE_NAME_COLLISION_CONTROLS) == 3
    assert len(_LABELED_AND_TERMINATED_LOCATION_ESCAPES) == 4
    assert len(_BARE_ASCII_LOCATION_ESCAPES) == 5
    assert len(_FULL_STATE_PROSE_ESCAPES) == 4
    assert len(_UNICODE_FORMAT_LOCATION_ESCAPES) == 3
    assert len(_EXACT_CITY_ZIP_CONTRADICTIONS) == 2
    assert len(_USPS_CITY_ZIP_CONTROLS) == 5
    assert len(_SHARED_ZIP_CENSUS_PLACE_CONTROLS) == 5
    assert len(_STATE_NAME_STREET_TYPE_CONTROLS) == 3


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "escape_name,changes",
    _CROSS_PROFILE_PROTOCOL_ESCAPES,
    ids=[case[0] for case in _CROSS_PROFILE_PROTOCOL_ESCAPES],
)
async def test_cross_profile_collection_protocol_escapes_fail_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    escape_name,
    changes,
):
    """Permanent 24-case matrix reproduced through the real MCP protocol."""
    del escape_name
    identity["ctx"] = request.getfixturevalue(context_fixture)
    record = _typed_record_dict(collection, changes)
    payload = _typed_collection_payload(
        collection,
        record,
        query_location="TX",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location="TX",
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "grant_name,territory,request_location",
    _EXACT_GRANT_CASES,
    ids=[case[0] for case in _EXACT_GRANT_CASES],
)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "escape_name,changes",
    _EXACT_GRANT_PROTOCOL_ESCAPES,
    ids=[case[0] for case in _EXACT_GRANT_PROTOCOL_ESCAPES],
)
async def test_exact_state_city_zip_protocol_escapes_fail_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    grant_name,
    territory,
    request_location,
    collection,
    escape_name,
    changes,
):
    """Permanent 48-case matrix reproduced through the real MCP protocol."""
    del grant_name, escape_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    record = _typed_record_dict(collection, changes)
    payload = _typed_collection_payload(
        collection,
        record,
        query_location=request_location,
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location=request_location,
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("field", ("address", "city", "state"))
@pytest.mark.parametrize("mode", ("omitted", "null", "empty", "non-string"))
async def test_required_location_fields_fail_closed_at_protocol_boundary(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    field,
    mode,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    if mode == "omitted":
        changes = {"_omit": (field,)}
    elif mode == "null":
        changes = {field: None}
    elif mode == "empty":
        changes = {field: "   "}
    else:
        changes = {field: 7}
    record = _typed_record_dict(collection, changes)

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        _typed_collection_payload(collection, record),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "mode,expected_denial",
    (
        ("omitted", False),
        ("null", False),
        ("empty", True),
        ("whitespace", True),
        ("non-string", True),
    ),
)
async def test_optional_zip_contract_is_type_safe_at_protocol_boundary(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    mode,
    expected_denial,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    if mode == "omitted":
        changes = {"_omit": ("zip_code",)}
    elif mode == "null":
        changes = {"zip_code": None}
    elif mode == "empty":
        changes = {"zip_code": ""}
    elif mode == "whitespace":
        changes = {"zip_code": "   "}
    else:
        changes = {"zip_code": 75201}
    payload = _typed_collection_payload(
        collection,
        _typed_record_dict(collection, changes),
    )

    if expected_denial:
        await _assert_generic_result_denial(
            registry,
            audit,
            identity,
            payload,
        )
    else:
        call_result = await _call_search(
            registry,
            audit,
            identity,
            payload,
        )
        assert call_result.data[collection][0].get("zip_code") is None


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_owner_lookup_rejects_each_conflicting_request_location_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """Every location-bearing request argument is independently restrictive."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError, match="territor"):
        await _call_owner_lookup(
            registry,
            audit,
            identity,
            {
                "address": "90 Ocean Drive, Miami, FL",
                "county": "Harris County, TX",
            },
            executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_owner_lookup_washington_dc_request_executes(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("DC",)}
    )
    executions = [0]

    result = await _call_owner_lookup(
        registry,
        audit,
        identity,
        {"address": "100 Main Street, Washington, DC 20001"},
        executions,
    )

    assert executions == [1]
    assert result.data["normalized_name"] == "REQUEST TERRITORY FIXTURE"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("address", ("Miami", "Miami USA"))
async def test_owner_lookup_ambiguous_locality_is_not_rescued_by_safe_county(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    address,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError, match="territor"):
        await _call_owner_lookup(
            registry,
            audit,
            identity,
            {"address": address, "county": "Harris County, TX"},
            executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_owner_lookup_leading_zip_conflict_denies_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError, match="territor"):
        await _call_owner_lookup(
            registry,
            audit,
            identity,
            {
                "address": "33101; 100 Main St Dallas TX 75201",
                "county": "Harris County, TX",
            },
            executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "escape_name,request_address,result_address",
    _LABELED_AND_TERMINATED_LOCATION_ESCAPES,
    ids=[case[0] for case in _LABELED_AND_TERMINATED_LOCATION_ESCAPES],
)
async def test_owner_lookup_labeled_or_terminated_location_escape_denies_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    escape_name,
    request_address,
    result_address,
):
    """Preserve independently reproduced request-address escapes."""
    del escape_name, result_address
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError, match="territor"):
        await _call_owner_lookup(
            registry,
            audit,
            identity,
            {
                "address": request_address,
                "county": "Harris County, TX",
            },
            executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "escape_name,address",
    _BARE_ASCII_LOCATION_ESCAPES,
    ids=[case[0] for case in _BARE_ASCII_LOCATION_ESCAPES],
)
async def test_owner_lookup_bare_ascii_zip_escape_denies_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    escape_name,
    address,
):
    """Preserve ASCII ZIP claims missed by delimiter-specific scanners."""
    del escape_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError, match="territor"):
        await _call_owner_lookup(
            registry,
            audit,
            identity,
            {"address": address, "county": "Harris County, TX"},
            executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "escape_name,address",
    _FULL_STATE_PROSE_ESCAPES,
    ids=[case[0] for case in _FULL_STATE_PROSE_ESCAPES],
)
async def test_owner_lookup_full_state_prose_escape_denies_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    escape_name,
    address,
):
    """A full state name remains authoritative before arbitrary provider prose."""
    del escape_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError, match="territor"):
        await _call_owner_lookup(
            registry,
            audit,
            identity,
            {"address": address, "county": "Harris County, TX"},
            executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "escape_name,address",
    _UNICODE_FORMAT_LOCATION_ESCAPES,
    ids=[case[0] for case in _UNICODE_FORMAT_LOCATION_ESCAPES],
)
async def test_owner_lookup_unicode_format_escape_denies_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    escape_name,
    address,
):
    """Invisible Unicode format characters cannot split location claims."""
    del escape_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError, match="territor"):
        await _call_owner_lookup(
            registry,
            audit,
            identity,
            {"address": address, "county": "Harris County, TX"},
            executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_accented_city_request_remains_valid_for_state_grant(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    result = await _call_market_overview(
        registry,
        audit,
        identity,
        "Peñitas, TX",
        executions,
    )

    assert executions == [1]
    assert result.data["location"] == "Peñitas, TX"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("address", _STREET_TAIL_ZIP_CONTROLS)
async def test_street_tail_before_zip_request_remains_valid_for_state_grant(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    address,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    result = await _call_owner_lookup(
        registry,
        audit,
        identity,
        {"address": address, "county": "Harris County, TX"},
        executions,
    )

    assert executions == [1]
    assert result.data["normalized_name"] == "REQUEST TERRITORY FIXTURE"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "case_name,territory,address,city,state",
    _FULL_STATE_NAME_COLLISION_CONTROLS,
    ids=[case[0] for case in _FULL_STATE_NAME_COLLISION_CONTROLS],
)
async def test_full_state_name_city_and_street_collisions_remain_valid_requests(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    case_name,
    territory,
    address,
    city,
    state,
):
    del case_name, city, state
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    result = await _call_owner_lookup(
        registry,
        audit,
        identity,
        {"address": address},
        executions,
    )

    assert executions == [1]
    assert result.data["normalized_name"] == "REQUEST TERRITORY FIXTURE"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "case_name,territory,location,city,zip_code",
    _EXACT_CITY_ZIP_CONTRADICTIONS,
    ids=[case[0] for case in _EXACT_CITY_ZIP_CONTRADICTIONS],
)
async def test_exact_city_zip_request_contradictions_deny_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    case_name,
    territory,
    location,
    city,
    zip_code,
):
    """Exact city/ZIP grants cannot be satisfied by contradictory pairs."""
    del case_name, city, zip_code
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    with pytest.raises(ToolError, match="territor"):
        await _call_market_overview(
            registry,
            audit,
            identity,
            location,
            executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "territory,expected_execution",
    (("CT", 0), ("NY", 1)),
    ids=("connecticut-denied", "new-york-allowed"),
)
async def test_fishers_island_06390_uses_authoritative_new_york_override(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    territory,
    expected_execution,
):
    """USPS assigns ZIP 06390 to Fishers Island, New York, not Connecticut."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    if expected_execution:
        result = await _call_market_overview(
            registry,
            audit,
            identity,
            "06390",
            executions,
        )
        assert result.data["location"] == "06390"
    else:
        with pytest.raises(ToolError, match="territor"):
            await _call_market_overview(
                registry,
                audit,
                identity,
                "06390",
                executions,
            )

    assert executions == [expected_execution]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("grant_kind", ("city", "zip"))
@pytest.mark.parametrize(
    "city_territory,city,state,zip_code",
    _USPS_CITY_ZIP_CONTROLS,
    ids=("dallas", "austin", "washington-dc", "fishers-island", "st-louis"),
)
async def test_documented_city_zip_request_pairs_release_for_exact_grants(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    grant_kind,
    city_territory,
    city,
    state,
    zip_code,
):
    territory = city_territory if grant_kind == "city" else zip_code
    location = f"{city}, {state} {zip_code}"
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    result = await _call_market_overview(
        registry,
        audit,
        identity,
        location,
        executions,
    )

    assert executions == [1]
    assert result.data["location"] == location


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_state_grant_request_rejects_nonexistent_city_zip_pair(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError, match="territor"):
        await _call_market_overview(
            registry,
            audit,
            identity,
            "Fixture City, TX 77001",
            executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_owner_lookup_plain_street_and_safe_county_executes(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    result = await _call_owner_lookup(
        registry,
        audit,
        identity,
        {"address": "100 Main Street", "county": "Harris County, TX"},
        executions,
    )

    assert executions == [1]
    assert result.data["normalized_name"] == "REQUEST TERRITORY FIXTURE"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
async def test_leading_zip_claim_before_separator_cannot_be_hidden(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    address = "33101; 100 Main St Dallas TX 75201"
    payload = _collection_result(
        collection,
        state="TX",
        address=address,
        city="Dallas",
        zip_code="75201",
        query_location="TX",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location="TX",
        secrets=("33101",),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "escape_name,request_address,result_address",
    _LABELED_AND_TERMINATED_LOCATION_ESCAPES,
    ids=[case[0] for case in _LABELED_AND_TERMINATED_LOCATION_ESCAPES],
)
async def test_labeled_or_terminated_result_location_escape_fails_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    escape_name,
    request_address,
    result_address,
):
    """Preserve independently reproduced result-address escapes."""
    del escape_name, request_address
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address=result_address,
        city="Dallas",
        zip_code="75201",
        query_location="TX",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location="TX",
        secrets=("33101",),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "escape_name,address",
    _BARE_ASCII_LOCATION_ESCAPES,
    ids=[case[0] for case in _BARE_ASCII_LOCATION_ESCAPES],
)
async def test_bare_ascii_zip_result_location_escape_fails_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    escape_name,
    address,
):
    """Every returned record exposes every non-unit ASCII ZIP claim."""
    del escape_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address=address,
        city="Dallas",
        zip_code="75201",
        query_location="TX",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location="TX",
        secrets=("33101",),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "escape_name,address",
    _FULL_STATE_PROSE_ESCAPES,
    ids=[case[0] for case in _FULL_STATE_PROSE_ESCAPES],
)
async def test_full_state_prose_result_location_escape_fails_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    escape_name,
    address,
):
    """Returned addresses cannot hide a state claim behind provider prose."""
    del escape_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address=address,
        city="Dallas",
        zip_code="75201",
        query_location="TX",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location="TX",
        secrets=("Miami", "Florida"),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "escape_name,address",
    _UNICODE_FORMAT_LOCATION_ESCAPES,
    ids=[case[0] for case in _UNICODE_FORMAT_LOCATION_ESCAPES],
)
async def test_unicode_format_result_location_escape_fails_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    escape_name,
    address,
):
    del escape_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address=address,
        city="Dallas",
        zip_code="75201",
        query_location="TX",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location="TX",
        secrets=("Miami",),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
async def test_accented_city_result_remains_valid_for_state_grant(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address="100 Main Street, Peñitas, TX",
        city="Peñitas",
        zip_code=None,
        query_location="TX",
    )

    result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location="TX",
    )

    assert result.data[collection][0]["city"] == "Peñitas"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("address", _STREET_TAIL_ZIP_CONTROLS)
async def test_street_tail_before_zip_result_remains_valid_for_state_grant(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    address,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address=address,
        city="Dallas",
        zip_code="75201",
        query_location="TX",
    )

    result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location="TX",
    )

    assert result.data[collection][0]["address"] == address


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "case_name,territory,address,city,state",
    _FULL_STATE_NAME_COLLISION_CONTROLS,
    ids=[case[0] for case in _FULL_STATE_NAME_COLLISION_CONTROLS],
)
async def test_full_state_name_city_and_street_collisions_remain_valid_results(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    case_name,
    territory,
    address,
    city,
    state,
):
    del case_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    payload = _collection_result(
        collection,
        state=state,
        address=address,
        city=city,
        zip_code=None,
        query_location=territory,
    )

    result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location=territory,
    )

    assert result.data[collection][0]["address"] == address


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "case_name,territory,contradictory_location,city,zip_code",
    _EXACT_CITY_ZIP_CONTRADICTIONS,
    ids=[case[0] for case in _EXACT_CITY_ZIP_CONTRADICTIONS],
)
async def test_exact_city_zip_result_contradictions_fail_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    case_name,
    territory,
    contradictory_location,
    city,
    zip_code,
):
    """Every returned record must satisfy an authoritative exact pair."""
    del case_name, contradictory_location
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address=f"100 Main Street, {city}, TX",
        city=city,
        zip_code=zip_code,
        query_location=territory,
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location=territory,
        secrets=(city, zip_code),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "territory,state,city,expected_release",
    (
        ("CT", "CT", "Mystic", False),
        ("NY", "NY", "Fishers Island", True),
    ),
    ids=("connecticut-denied", "new-york-allowed"),
)
async def test_fishers_island_06390_result_uses_authoritative_new_york_override(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    territory,
    state,
    city,
    expected_release,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    payload = _collection_result(
        collection,
        state=state,
        address=f"100 Main Street, {city}, {state} 06390",
        city=city,
        zip_code="06390",
        query_location=territory,
    )

    if expected_release:
        result = await _call_search(
            registry,
            audit,
            identity,
            payload,
            location=territory,
        )
        assert result.data[collection][0]["zip_code"] == "06390"
    else:
        await _assert_generic_result_denial(
            registry,
            audit,
            identity,
            payload,
            location=territory,
            secrets=("06390",),
        )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("grant_kind", ("city", "zip"))
@pytest.mark.parametrize(
    "city_territory,city,state,zip_code",
    _USPS_CITY_ZIP_CONTROLS,
    ids=("dallas", "austin", "washington-dc", "fishers-island", "st-louis"),
)
async def test_documented_city_zip_result_pairs_release_for_exact_grants(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    grant_kind,
    city_territory,
    city,
    state,
    zip_code,
):
    territory = city_territory if grant_kind == "city" else zip_code
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    payload = _collection_result(
        collection,
        state=state,
        address=f"100 Main Street, {city}, {state} {zip_code}",
        city=city,
        zip_code=zip_code,
        query_location=territory,
    )

    result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location=territory,
    )

    assert result.data[collection][0]["zip_code"] == zip_code


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "city,state,zip_code",
    _SHARED_ZIP_CENSUS_PLACE_CONTROLS,
    ids=(
        "university-park",
        "highland-park",
        "west-lake-hills",
        "jersey-village",
        "bal-harbour",
    ),
)
async def test_state_grant_releases_shared_zip_census_places_at_protocol_boundary(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    city,
    state,
    zip_code,
):
    """A ZIP's single primary postal name must not exclude real places in it."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (state,)}
    )
    payload = _collection_result(
        collection,
        state=state,
        address=f"100 Main Street, {city}, {state} {zip_code}",
        city=city,
        zip_code=zip_code,
        query_location=state,
    )

    result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location=state,
    )

    assert result.data[collection][0]["city"] == city
    assert result.data[collection][0]["zip_code"] == zip_code


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "case_name,address,city,state,zip_code",
    _STATE_NAME_STREET_TYPE_CONTROLS,
    ids=[case[0] for case in _STATE_NAME_STREET_TYPE_CONTROLS],
)
async def test_state_names_in_valid_street_types_release_at_protocol_boundary(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    case_name,
    address,
    city,
    state,
    zip_code,
):
    """Street names that resemble states are not independent location claims."""
    del case_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (state,)}
    )
    full_address = f"{address}, {city}, {state} {zip_code}"
    payload = _collection_result(
        collection,
        state=state,
        address=full_address,
        city=city,
        zip_code=zip_code,
        query_location=state,
    )

    result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location=state,
    )

    assert result.data[collection][0]["address"] == full_address


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_analyze_deal_releases_its_own_county_georef_shape(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """The result validator must accept the county GeoRef made by the tool."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    listing = Listing(
        source="county",
        source_id="48113:abc",
        name="Dallas County fixture",
        address="100 Main Street, Dallas, TX 75201",
        city="Dallas",
        state="TX",
        zip_code="75201",
        url="https://example.test/county/48113/abc",
        raw={},
    )
    geo = _geo_from_listing(listing)
    assert geo is not None
    assert geo.name == "Dallas County, TX"
    payload = DealAnalysisResult(
        listing=listing,
        rent_comps=RentComps(geo=geo),
        score_calibrated=True,
        score_calibration_disclaimer=None,
    ).model_dump(mode="json")

    async def fake_analyze_deal(url_or_id: str) -> dict[str, Any]:
        del url_or_id
        return payload

    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="analyze_deal",
        tool=fake_analyze_deal,
        arguments={"url_or_id": "48113:abc"},
    )

    assert result.data["rent_comps"]["geo"] == geo.model_dump(mode="json")


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_analyze_deal_releases_district_of_columbia_county_equivalent(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """DC's county-equivalent legal name has no ``County`` suffix."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("DC",)}
    )
    listing = Listing(
        source="county",
        source_id="11001:abc",
        name="District of Columbia fixture",
        address="100 New York Avenue NW, Washington, DC 20001",
        city="Washington",
        state="DC",
        zip_code="20001",
        url="https://example.test/county/11001/abc",
        raw={},
    )
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="11",
        county_fips="11001",
        name="District of Columbia",
    )
    payload = DealAnalysisResult(
        listing=listing,
        rent_comps=RentComps(geo=geo),
        score_calibrated=True,
        score_calibration_disclaimer=None,
    ).model_dump(mode="json")

    async def fake_analyze_deal(url_or_id: str) -> dict[str, Any]:
        del url_or_id
        return payload

    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="analyze_deal",
        tool=fake_analyze_deal,
        arguments={"url_or_id": "11001:abc"},
    )

    assert result.data["rent_comps"]["geo"] == geo.model_dump(mode="json")


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_market_intel_rejects_unproven_geocoder_tract_then_releases_city_projection(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """Reject an unproved tract carrier while preserving the exact city."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    fixture_path = (
        Path(__file__).parents[1] / "fixtures" / "census" / "geocoder.json"
    )
    resolver = object.__new__(GeoResolver)
    geo = resolver._parse_geocoder(
        json.loads(fixture_path.read_text(encoding="utf-8")),
        "Austin, TX",
    )
    assert geo is not None
    assert geo.name == "Austin city"
    use_production_projection = [False]

    async def fake_market_intel(location: str) -> dict[str, Any]:
        del location
        selected_geo = (
            project_for_release(geo)
            if use_production_projection[0]
            else geo
        )
        return MarketIntelResult(
            geo=selected_geo,
            market_score=0.0,
            score_confidence=0.0,
            coverage_summary=CoverageSummary(
                covered=0,
                total=0,
                ratio=0.0,
            ),
        ).model_dump(mode="json")

    with pytest.raises(ToolError, match=RESULT_TERRITORY_DENIAL):
        await _call_protocol_tool(
            registry,
            audit,
            identity,
            tool_name="market_intel",
            tool=fake_market_intel,
            arguments={"location": "Austin, TX"},
        )

    use_production_projection[0] = True
    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="market_intel",
        tool=fake_market_intel,
        arguments={"location": "Austin, TX"},
    )

    expected_geo = geo.model_copy(update={"tract": None}).model_dump(mode="json")
    assert result.data["geo"] == expected_geo


async def test_full_operator_preserves_production_geocoder_tract(
    registry,
    audit,
    identity,
    ctx_op,
):
    """The restricted projection does not alter full-operator resolver data."""

    identity["ctx"] = ctx_op
    fixture_path = (
        Path(__file__).parents[1] / "fixtures" / "census" / "geocoder.json"
    )
    resolver = object.__new__(GeoResolver)
    geo = resolver._parse_geocoder(
        json.loads(fixture_path.read_text(encoding="utf-8")),
        "Austin, TX",
    )
    assert geo is not None and geo.tract == "48453000700"

    async def fake_market_intel(location: str) -> dict[str, Any]:
        del location
        return MarketIntelResult(
            geo=project_for_release(geo),
            market_score=0.0,
            score_confidence=0.0,
            coverage_summary=CoverageSummary(covered=0, total=0, ratio=0.0),
        ).model_dump(mode="json")

    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="market_intel",
        tool=fake_market_intel,
        arguments={"location": "Austin, TX"},
    )

    assert result.data["geo"]["tract"] == "48453000700"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_save_search_binds_nested_result_location_to_request(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = {
        "search_id": 1,
        # Saved-search names are a caller-owned label, not location authority.
        "name": "Miami, FL is allowed as my own note",
        "query": {
            "location": "TX",
            "strategy": None,
            "property_type": None,
            "price_min": None,
            "price_max": None,
            "size_min": None,
            "size_max": None,
            "sources": ["loopnet"],
        },
        "min_score": None,
        "alert_mode": "pull_on_demand",
        "hosting_note": "fixture",
    }

    async def fake_save_search(name: str, location: str) -> dict[str, Any]:
        del name, location
        return payload

    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="save_search",
        tool=fake_save_search,
        arguments={"name": payload["name"], "location": "TX"},
    )

    assert result.data == payload


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_save_search_denies_mismatched_nested_result_location(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = {
        "search_id": 1,
        "name": "fixture",
        "query": {
            "location": "Miami, FL",
            "strategy": None,
            "property_type": None,
            "price_min": None,
            "price_max": None,
            "size_min": None,
            "size_max": None,
            "sources": ["loopnet"],
        },
        "min_score": None,
        "alert_mode": "pull_on_demand",
        "hosting_note": "fixture",
    }

    async def fake_save_search(name: str, location: str) -> dict[str, Any]:
        del name, location
        return payload

    with pytest.raises(ToolError, match=RESULT_TERRITORY_DENIAL):
        await _call_protocol_tool(
            registry,
            audit,
            identity,
            tool_name="save_search",
            tool=fake_save_search,
            arguments={"name": "fixture", "location": "TX"},
        )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "finding",
    (
        {
            "rec_type": "UST",
            "location": "Miami, FL 33132",
            "medium": "soil",
        },
        {
            "rec_type": "unregistered finding",
            "location": "Miami, FL 33132",
            "medium": "soil",
        },
    ),
    ids=("known-rec", "unknown-rec"),
)
async def test_actual_phase2_scope_denies_regional_location_echo(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    finding,
):
    """Caller-supplied regional text cannot bypass result enforcement."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )

    with pytest.raises(ToolError) as caught:
        await _call_protocol_tool(
            registry,
            audit,
            identity,
            tool_name="phase2_scope",
            tool=compliance_tools.phase2_scope,
            arguments={"phase1_findings": [finding]},
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)
    event = audit.events(identity["ctx"].workspace_id)[-1]
    assert event.tool == "phase2_scope"
    assert event.decision == "denied"
    assert event.reason == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_actual_phase2_scope_releases_only_on_site_descriptors(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """Non-geographic on-site descriptors remain usable for limited profiles."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    findings = [
        {
            "rec_type": "UST",
            "location": "north parking lot",
            "medium": "soil",
        },
        {
            "rec_type": "dry cleaner",
            "location": "former Suite 12",
            "medium": "sub-slab vapor",
        },
        {
            "rec_type": "groundwater plume",
            "location": "southern property boundary",
            "medium": "groundwater",
        },
    ]

    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="phase2_scope",
        tool=compliance_tools.phase2_scope,
        arguments={"phase1_findings": findings},
    )

    assert [item["location"] for item in result.data["scope_items"]] == [
        finding["location"] for finding in findings
    ]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("wrapped", (False, True), ids=("sequence", "envelope"))
async def test_actual_unpermitted_screen_releases_typed_in_scope_permits(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    wrapped,
):
    """Both public permit-history shapes pass after exact request validation."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    permit = {
        "address": "100 Main Street",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
        "permit_number": "TX-100",
        "type": "roofing permit",
        "date": "2023-08-09",
        "desc": "Tear off existing roof and reroof the building",
    }
    history: Any = {"status": "OK", "permits": [permit]} if wrapped else [permit]

    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="unpermitted_work_screen",
        tool=compliance_tools.unpermitted_work_screen,
        arguments={
            "observed_improvements": [
                {"desc": "Complete roof replacement", "est_year": 2023}
            ],
            "permit_history": history,
        },
    )

    returned = result.data["matches"][0]["plausible_permits"][0]["permit"]
    assert returned == {**permit, "city": "DALLAS"}
    assert result.data["permit_history_status"] == ("OK" if wrapped else None)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_actual_unpermitted_screen_denies_out_of_scope_permit_request(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    permit = {
        "address": "100 Ocean Drive",
        "city": "Miami",
        "state": "FL",
        "zip_code": "33132",
        "type": "roofing permit",
        "date": "2023-08-09",
        "desc": "Tear off existing roof and reroof the building",
    }

    with pytest.raises(ToolError, match="property request"):
        await _call_protocol_tool(
            registry,
            audit,
            identity,
            tool_name="unpermitted_work_screen",
            tool=compliance_tools.unpermitted_work_screen,
            arguments={
                "observed_improvements": [
                    {"desc": "Complete roof replacement", "est_year": 2023}
                ],
                "permit_history": [permit],
            },
        )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_unpermitted_screen_denies_out_of_scope_returned_permit(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """Post-result enforcement remains independent of request validation."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    request_permit = {
        "address": "100 Main Street",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
        "type": "roofing permit",
        "date": "2023-08-09",
        "desc": "Tear off existing roof and reroof the building",
    }
    returned_permit = {
        **request_permit,
        "address": "100 Ocean Drive",
        "city": "Miami",
        "state": "FL",
        "zip_code": "33132",
    }
    payload = compliance_tools.unpermitted_work_screen(
        [{"desc": "Complete roof replacement", "est_year": 2023}],
        [returned_permit],
    )

    async def fake_unpermitted_work_screen(
        observed_improvements: list[dict[str, Any]],
        permit_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        del observed_improvements, permit_history
        return payload

    with pytest.raises(ToolError) as caught:
        await _call_protocol_tool(
            registry,
            audit,
            identity,
            tool_name="unpermitted_work_screen",
            tool=fake_unpermitted_work_screen,
            arguments={
                "observed_improvements": [
                    {"desc": "Complete roof replacement", "est_year": 2023}
                ],
                "permit_history": [request_permit],
            },
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_actual_warn_projection_removes_county_only_secondary_location(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    """A request-bound state row remains counted without leaking opaque data."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = {
        "status": "OK",
        "state": "TX",
        "since": "2026-01-01",
        "count": 1,
        "events": [
            {
                "employer": "County Only",
                "location": "Denton County, TX",
                "affected": 20,
                "effective_date": "2026-07-02",
                "source_url": "https://example.test/warn",
            }
        ],
    }

    async def fake_events(state: str, since: str | None):
        del state, since
        return payload

    monkeypatch.setattr(siteintel_tools, "_employer_events", fake_events)
    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="employer_warn_events",
        tool=siteintel_tools.employer_warn_events,
        arguments={"state": "TX"},
    )

    assert result.data["count"] == 1
    assert result.data["events"][0]["location"] == "TX"
    assert result.data["events"][0]["county"] is None


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_actual_owner_lookup_projects_provider_raw_before_release(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    """The production boundary keeps the parcel but removes its opaque blob."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    owner = OwnerRecord(
        name="Protocol Fixture Owner",
        normalized_name="PROTOCOL FIXTURE OWNER",
        entity_type="company",
        parcels=[
            ParcelRecord(
                apn="fixture",
                site_address="100 Main Street, Dallas, TX 75201",
                raw={
                    "provider_record_id": "fixture",
                    "untrusted_location": "Miami, FL 33132",
                },
            )
        ],
    )

    class FakeOwnerLookup:
        async def lookup(self, *, address, apn, county):
            del address, apn, county
            return owner

    monkeypatch.setattr(owner_tools, "_engine", lambda: FakeOwnerLookup())
    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="owner_lookup",
        tool=owner_tools.owner_lookup,
        arguments={
            "address": "100 Main Street, Dallas, TX 75201",
            "county": "Dallas County, TX",
        },
    )

    assert result.data["parcels"][0]["site_address"].endswith("TX 75201")
    assert result.data["parcels"][0]["raw"] == {}


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_actual_get_comps_releases_street_only_subject_shape(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    """The existing production Listing shape keeps locality in separate fields."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    listing = Listing(
        source="crexi",
        source_id="123",
        name="Retail subject",
        address="100 Main St",
        city="Austin",
        state="TX",
        property_type="retail",
        price_usd=1_100_000,
        size_sqft_num=10_000,
        url="https://www.crexi.com/properties/123/example",
    )
    estimate = ValueEstimate(
        value=1_000_000,
        method="fhfa_trend",
        n_comps=0,
        confidence=0.35,
        source="fixture",
    )

    async def fake_analyze_deal(*args, **kwargs):
        del args, kwargs
        return Deal(
            listing=listing,
            value_estimate=estimate,
        ).model_dump(mode="json")

    monkeypatch.setattr(market_tools, "analyze_deal", fake_analyze_deal)
    monkeypatch.setattr(market_tools, "_paid_comps_providers", lambda *_args: [])

    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="get_comps",
        tool=market_tools.get_comps,
        arguments={"url_or_id": "123", "source": "crexi"},
    )

    assert result.data["subject"]["address"] == "100 Main St"
    assert result.data["subject"]["city"] == "Austin"
    assert result.data["subject"]["state"] == "TX"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_actual_get_comps_releases_real_county_sale_comp_shape(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    """A configured county FIPS can scope a street-only public sale comp."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("NC",)}
    )
    fixture_path = (
        Path(__file__).parents[1] / "fixtures" / "comps" / "guilford_sales.json"
    )
    row = json.loads(fixture_path.read_text(encoding="utf-8"))[0]
    comp = map_sale_comp(row, COUNTY_PARCEL_ENDPOINTS["37081"])
    assert comp is not None
    assert comp.address == "811 VAIL AVE"
    listing = Listing(
        source="fixture",
        source_id="subject",
        name="Subject",
        address="999 TEST RD",
        city="Greensboro",
        state="NC",
        property_type="residential",
        price_usd=200_000,
        url="https://example.test/subject",
    )
    estimate = ValueEstimate(
        value=200_000,
        method="county_comps",
        n_comps=1,
        confidence=0.5,
        source="fixture",
    )

    async def fake_analyze_deal(*args, **kwargs):
        del args, kwargs
        return Deal(
            listing=listing,
            value_estimate=estimate,
            sale_comps=[comp],
        ).model_dump(mode="json")

    monkeypatch.setattr(market_tools, "analyze_deal", fake_analyze_deal)
    monkeypatch.setattr(market_tools, "_paid_comps_providers", lambda *_args: [])

    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="get_comps",
        tool=market_tools.get_comps,
        arguments={"url_or_id": "subject", "source": "fixture"},
    )

    assert result.data["comps"][0]["county_fips"] == "37081"
    assert result.data["comps"][0]["address"] == "811 VAIL AVE"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_actual_get_comps_releases_king_county_directional_shape(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    """A terminal compass directional is not a Nebraska state claim."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("WA",)}
    )
    fixture_path = (
        Path(__file__).parents[1] / "fixtures" / "comps" / "phase23_sales.json"
    )
    row = json.loads(fixture_path.read_text(encoding="utf-8"))["53033"]
    comp = map_sale_comp(row, COUNTY_SALES_ENDPOINTS["53033"])
    assert comp is not None
    assert comp.address == "11745 24TH AVE NE"
    listing = Listing(
        source="fixture",
        source_id="subject",
        name="Subject",
        address="999 TEST RD",
        city="Seattle",
        state="WA",
        zip_code="98101",
        property_type="residential",
        price_usd=760_000,
        url="https://example.test/subject",
    )
    estimate = ValueEstimate(
        value=760_000,
        method="county_comps",
        n_comps=1,
        confidence=0.5,
        source="fixture",
    )

    async def fake_analyze_deal(*args, **kwargs):
        del args, kwargs
        return Deal(
            listing=listing,
            value_estimate=estimate,
            sale_comps=[comp],
        ).model_dump(mode="json")

    monkeypatch.setattr(market_tools, "analyze_deal", fake_analyze_deal)
    monkeypatch.setattr(market_tools, "_paid_comps_providers", lambda *_args: [])

    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="get_comps",
        tool=market_tools.get_comps,
        arguments={"url_or_id": "subject", "source": "fixture"},
    )

    assert result.data["comps"][0]["county_fips"] == "53033"
    assert result.data["comps"][0]["address"] == "11745 24TH AVE NE"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_get_comps_releases_paid_provider_fips_with_complete_address(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """Paid-provider FIPS outside fallback coverage needs an exact address."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("Denver, CO",)}
    )
    payload = {
        "subject": {
            "source": "attom",
            "source_id": "subject",
            "address": "100 Market Street",
            "city": "Denver",
            "state": "CO",
            "zip_code": "80202",
            "asking_price": 1_000_000.0,
        },
        "value_estimate": {
            "value": 1_000_000.0,
            "low": None,
            "mid": None,
            "high": None,
            "method": "attom",
            "n_comps": 1,
            "confidence": 0.5,
            "error_band": None,
            "as_of": None,
            "source": "fixture",
        },
        "value_provenance": {"method": "attom", "confidence": 0.5, "n_comps": 1},
        "comps": [
            {
                "source": "attom",
                "county_fips": "08031",
                "parcel_id": "fixture",
                "address": "123 Main St, Denver, CO 80202",
                "sale_price": 975_000.0,
                "sale_date": "2026-01-01",
                "sqft": None,
                "units": None,
                "use_code": None,
                "lat": None,
                "lon": None,
                "distance_miles": None,
                "time_adjusted_price": None,
            }
        ],
        "explanation": "fixture",
        "coverage_note": "fixture",
    }

    async def fake_get_comps(url_or_id: str, source: str = "loopnet") -> dict[str, Any]:
        del url_or_id, source
        return payload

    result = await _call_protocol_tool(
        registry,
        audit,
        identity,
        tool_name="get_comps",
        tool=fake_get_comps,
        arguments={"url_or_id": "subject", "source": "attom"},
    )

    assert result.data["comps"][0]["county_fips"] == "08031"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("territory", ("Greensboro, NC", "27401"))
async def test_actual_get_comps_denies_county_only_comp_for_narrow_grant(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
    territory,
):
    """County FIPS is insufficient authority for a city- or ZIP-only grant."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    fixture_path = (
        Path(__file__).parents[1] / "fixtures" / "comps" / "guilford_sales.json"
    )
    row = json.loads(fixture_path.read_text(encoding="utf-8"))[0]
    comp = map_sale_comp(row, COUNTY_PARCEL_ENDPOINTS["37081"])
    assert comp is not None
    listing = Listing(
        source="fixture",
        source_id="subject",
        name="Subject",
        address="999 TEST RD",
        city="Greensboro",
        state="NC",
        zip_code="27401",
        property_type="residential",
        price_usd=200_000,
        url="https://example.test/subject",
    )
    estimate = ValueEstimate(
        value=200_000,
        method="county_comps",
        n_comps=1,
        confidence=0.5,
        source="fixture",
    )

    async def fake_analyze_deal(*args, **kwargs):
        del args, kwargs
        return Deal(
            listing=listing,
            value_estimate=estimate,
            sale_comps=[comp],
        ).model_dump(mode="json")

    monkeypatch.setattr(market_tools, "analyze_deal", fake_analyze_deal)
    monkeypatch.setattr(market_tools, "_paid_comps_providers", lambda *_args: [])

    with pytest.raises(ToolError) as caught:
        await _call_protocol_tool(
            registry,
            audit,
            identity,
            tool_name="get_comps",
            tool=market_tools.get_comps,
            arguments={"url_or_id": "subject", "source": "fixture"},
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "811 VAIL" not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
async def test_state_grant_result_rejects_nonexistent_city_zip_pair(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address="100 Fixture Way, Fixture City, TX 77001",
        city="Fixture City",
        zip_code="77001",
        query_location="TX",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location="TX",
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "city,record_zip,territory",
    (
        ("Dallas TX 75201", "75202", "75202"),
        ("Dallas, TX 75202", "75201", "75201"),
    ),
    ids=("reviewer-exact", "inverse-conflict"),
)
async def test_city_embedded_zip_must_reconcile_with_structured_zip(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    city,
    record_zip,
    territory,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address="100 Main Street",
        city=city,
        zip_code=record_zip,
        query_location=territory,
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location=territory,
        secrets=(city,),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
async def test_valid_washington_dc_record_releases(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("DC",)}
    )
    payload = _collection_result(
        collection,
        state="DC",
        address="100 Main Street, Washington, DC 20001",
        city="Washington",
        zip_code="20001",
        query_location="DC",
    )

    call_result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location="DC",
    )

    assert call_result.data[collection][0]["city"] == "Washington"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("city", _INCOMPLETE_CITY_VALUES)
async def test_incomplete_or_ambiguous_city_field_fails_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    city,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address="100 Main Street",
        city=city,
        zip_code="75201",
        query_location="TX",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location="TX",
        secrets=(city,),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("city", _COMPLETE_CITY_VALUES)
async def test_plain_or_complete_normalized_city_field_releases(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    city,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _collection_result(
        collection,
        state="TX",
        address="100 Main Street",
        city=city,
        zip_code="75201",
        query_location="TX",
    )

    call_result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location="TX",
    )

    assert call_result.data[collection][0]["city"] == city


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("zip_value", _NON_ASCII_ZIP_VALUES)
@pytest.mark.parametrize("carrier", ("zip-field", "city-field", "address-field"))
async def test_non_ascii_zip_digits_fail_closed_in_every_result_location_carrier(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    zip_value,
    carrier,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    changes: dict[str, Any] = {
        "address": "100 Main Street",
        "city": "Dallas",
        "state": "TX",
        "zip_code": None,
    }
    if carrier == "zip-field":
        changes["zip_code"] = zip_value
    elif carrier == "city-field":
        changes["city"] = f"Dallas TX {zip_value}"
    else:
        changes["address"] = f"100 Main Street, Dallas, TX {zip_value}"
    payload = _typed_collection_payload(
        collection,
        _typed_record_dict(collection, changes),
        query_location="TX",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location="TX",
        secrets=(zip_value,),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("location", _NON_ASCII_QUERY_LOCATIONS)
async def test_non_ascii_zip_digits_in_requested_search_deny_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    location,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = 0

    def result():
        nonlocal executions
        executions += 1
        return _legacy_result(_property(), query_location=location)

    with pytest.raises(ToolError, match="territor"):
        await _call_search(
            registry,
            audit,
            identity,
            result,
            location=location,
        )

    assert executions == 0


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("location", _ASCII_QUERY_LOCATION_CONTROLS)
async def test_ascii_zip_requested_search_controls_release(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    location,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _legacy_result(_property(), query_location=location)

    call_result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location=location,
    )

    assert call_result.data["query_location"] == location


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
async def test_real_crexi_empty_address_city_record_fails_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    provider_asset = {
        "id": "provider-1",
        "name": "90 Ocean Drive, Miami, FL",
        "locations": [{"state": {"code": "TX"}}],
        "description": "Location text that is not a structured authorization field",
    }
    listing = map_asset(provider_asset)
    assert listing.address == ""
    assert listing.city == ""
    assert listing.state == "TX"
    assert "Miami" in listing.name
    assert "Miami" in listing.raw["name"]
    if collection == "listings":
        payload = _aggregate_result(listing)
    else:
        # Preserve the same provider-shaped location values in the legacy
        # collection without using name/raw as authorization evidence.
        record = _typed_record_dict(
            "properties",
            {
                "name": listing.name,
                "address": listing.address,
                "city": listing.city,
                "state": listing.state,
                "zip_code": listing.zip_code,
            },
        )
        payload = _typed_collection_payload("properties", record)

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        secrets=("90 Ocean Drive", "Miami"),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "address",
    (
        "Miami fl USA",
        "MIAMI fL united states",
        "Portland OR",
        "Omaha NE",
        "Indianapolis IN",
        "Hartford CT",
        "Miami Florida USA",
    ),
)
async def test_case_state_name_and_country_variants_cannot_hide_conflicts(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    address,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    record = _typed_record_dict(
        collection,
        {
            "address": address,
            "city": "Dallas",
            "state": "TX",
            "zip_code": "75201",
        },
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        _typed_collection_payload(collection, record),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "address,city,state,zip_code",
    (
        ("100 Main St, Dallas, tx 75201-4321", "dallas", "tx", "75201-4321"),
        ("100 Main St, Dallas, Texas, USA", "Dallas", "Texas", None),
        ("100 Main St Dallas TX USA", "Dallas", "TX", None),
        ("100 Main St, Dallas, TX 75201 USA", "Dallas", "TX", "75201-4321"),
    ),
    ids=(
        "mixed-case-code-and-zip4",
        "full-state-name-country",
        "bare-city-state-country",
        "zip-country-and-zip4",
    ),
)
async def test_normalized_complete_result_locations_release(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    address,
    city,
    state,
    zip_code,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    payload = _typed_collection_payload(
        collection,
        _typed_record_dict(
            collection,
            {
                "address": address,
                "city": city,
                "state": state,
                "zip_code": zip_code,
            },
        ),
        query_location="TX",
    )

    call_result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location="TX",
    )

    assert call_result.data[collection][0]["address"] == address


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "malformation",
    (
        "missing-query-location",
        "null-query-location",
        "empty-query-location",
        "unknown-top-level-structure",
        "unknown-location-bearing-structure",
        "unknown-record-field",
        "both-result-collections",
    ),
)
async def test_typed_result_envelope_rejects_unknown_or_incomplete_shapes(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    malformation,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    record = _typed_record_dict(collection, {})
    payload = _typed_collection_payload(collection, record)
    if malformation == "missing-query-location":
        payload.pop("query_location")
    elif malformation == "null-query-location":
        payload["query_location"] = None
    elif malformation == "empty-query-location":
        payload["query_location"] = "   "
    elif malformation == "unknown-top-level-structure":
        payload["provider_status"] = {"ok": True}
    elif malformation == "unknown-location-bearing-structure":
        payload["provider_location"] = {
            "address": "90 Ocean Drive",
            "city": "Miami",
            "state": "FL",
        }
    elif malformation == "unknown-record-field":
        payload[collection][0]["provider_location"] = "Miami, FL"
    else:
        other = "listings" if collection == "properties" else "properties"
        payload[other] = [
            _typed_record_dict(other, {})
        ]

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        secrets=("90 Ocean Drive", "Miami")
        if "location" in malformation
        else (),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "territory,request_location,result_query_location",
    (
        ("TX", "Dallas, TX", "Houston, TX"),
        ("TX", "TX", "Dallas, TX"),
        ("75201", "75201", "75202"),
    ),
    ids=(
        "same-state-other-city",
        "unexpectedly-narrowed-state-query",
        "other-zip",
    ),
)
async def test_result_query_location_must_bind_to_authorized_request(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    territory,
    request_location,
    result_query_location,
):
    """A safe-looking record cannot legitimize a mismatched result envelope."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    payload = _typed_collection_payload(
        collection,
        _typed_record_dict(
            collection,
            {
                "address": "100 Main Street, Dallas, TX 75201",
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75201",
            },
        ),
        query_location=result_query_location,
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        location=request_location,
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "territory,request_location,result_query_location",
    (
        ("TX", "texas USA", "TX"),
        ("Dallas, TX", "Dallas Texas United States", "dallas, tx"),
        ("75201", "75201-4321 USA", "75201"),
    ),
    ids=("state", "city-state", "zip-plus-four"),
)
async def test_result_query_location_accepts_only_normalized_equivalence(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    territory,
    request_location,
    result_query_location,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    payload = _typed_collection_payload(
        collection,
        _typed_record_dict(
            collection,
            {
                "address": "100 Main Street, Dallas, TX 75201",
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75201",
            },
        ),
        query_location=result_query_location,
    )

    call_result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location=request_location,
    )

    assert call_result.data["query_location"] == result_query_location


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "territory,request_location",
    (
        ("TX", "texas"),
        ("TX", "Dallas TX USA"),
        ("TX", "Dallas, Texas, United States"),
        ("TX", "75201 USA"),
        ("Dallas, TX", "dallas texas usa"),
        ("75201", "75201-4321"),
    ),
    ids=(
        "full-state-name",
        "city-state-country",
        "city-full-state-country",
        "zip-country",
        "city-grant-normalization",
        "zip4-normalization",
    ),
)
async def test_requested_search_normalization_releases_only_exact_scope(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    territory,
    request_location,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    payload = _legacy_result(
        _property(),
        query_location=request_location,
    )

    call_result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location=request_location,
    )

    assert call_result.data["properties"][0]["state"] == "TX"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "territory,request_location",
    (
        ("TX", "Dallas"),
        ("Dallas, TX", "TX"),
        ("75201", "Dallas TX"),
        ("Dallas, TX", "Austin TX"),
        ("75201", "75202"),
    ),
    ids=(
        "ambiguous-bare-city",
        "state-cannot-broaden-city-grant",
        "city-cannot-broaden-zip-grant",
        "other-city",
        "other-zip",
    ),
)
async def test_requested_search_is_intersected_before_tool_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    territory,
    request_location,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = 0

    def result():
        nonlocal executions
        executions += 1
        return _legacy_result(_property())

    with pytest.raises(ToolError, match="territor"):
        await _call_search(
            registry,
            audit,
            identity,
            result,
            location=request_location,
        )

    assert executions == 0


@pytest.mark.parametrize("context_fixture", ["ctx_loc", "ctx_jv"])
async def test_territory_limited_profiles_deny_out_of_scope_legacy_result(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    leaked_address = "90 Ocean Drive, Miami, FL"

    with pytest.raises(ToolError, match="result.*territor") as caught:
        await _call_search(
            registry,
            audit,
            identity,
            _legacy_result(
                _property(
                    state="FL",
                    address=leaked_address,
                    city="Miami",
                    zip_code="33101",
                )
            ),
        )

    event = audit.events(identity["ctx"].workspace_id)[-1]
    assert event.tool == "search_properties"
    assert event.decision == "denied"
    for secret in (leaked_address, "Miami", "33101"):
        assert secret not in str(caught.value)
        assert secret not in event.reason


async def test_every_returned_record_is_validated(
    registry, audit, identity, ctx_loc
):
    identity["ctx"] = ctx_loc
    result = _legacy_result(
        _property(),
        _property(
            state="FL",
            address="91 Ocean Drive, Miami, FL",
            city="Miami",
            zip_code="33101",
        ),
    )

    with pytest.raises(ToolError, match="result.*territor"):
        await _call_search(registry, audit, identity, result)


async def test_every_present_declared_collection_is_validated(
    registry, audit, identity, ctx_loc
):
    identity["ctx"] = ctx_loc
    result = _legacy_result(_property())
    result["listings"] = _aggregate_result(
        _listing(
            state="FL",
            address="94 Ocean Drive, Miami, FL",
            city="Miami",
            zip_code="33101",
        )
    )["listings"]

    with pytest.raises(ToolError, match="result.*territor"):
        await _call_search(registry, audit, identity, result)


@pytest.mark.parametrize(
    "result",
    [
        _legacy_result(
            _property(
                state="TX",
                address="92 Ocean Drive, Miami, FL",
                city="Dallas",
                zip_code=None,
            )
        ),
        _legacy_result(
            _property(
                state="FL",
                address="300 Main Street, Dallas, TX",
                city="Dallas",
                zip_code=None,
            )
        ),
    ],
    ids=["out-address-in-state", "in-address-out-state"],
)
async def test_conflicting_resolvable_location_fields_fail_closed(
    registry, audit, identity, ctx_loc, result
):
    identity["ctx"] = ctx_loc

    with pytest.raises(ToolError, match="result.*territor"):
        await _call_search(registry, audit, identity, result)


@pytest.mark.parametrize("context_fixture", ["ctx_loc", "ctx_jv"])
@pytest.mark.parametrize("collection", ["properties", "listings"])
@pytest.mark.parametrize("conflict", ["same-state-city", "same-state-zip"])
async def test_exact_claim_contradictions_fail_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    conflict,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    if conflict == "same-state-city":
        result = _collection_result(
            collection,
            state="TX",
            address="100 Main Street, Austin, TX",
            city="Dallas",
            zip_code=None,
        )
        secrets = ("Austin",)
    else:
        result = _collection_result(
            collection,
            state="TX",
            address="100 Main Street, Dallas, TX 73301",
            city="Dallas",
            zip_code="75201",
        )
        secrets = ("73301",)

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        secrets=secrets,
    )


@pytest.mark.parametrize("collection", ["properties", "listings"])
@pytest.mark.parametrize(
    "ambiguous_address,secret",
    [
        (
            "90 Ocean Drive, Miami, FL, Dallas, TX 75201",
            "Miami",
        ),
        (
            "100 Congress Avenue, Austin, TX 73301, Dallas, TX 75201",
            "73301",
        ),
    ],
    ids=["earlier-out-of-state-claim", "earlier-same-state-city-and-zip"],
)
async def test_multiple_claims_inside_declared_address_fail_closed(
    registry,
    audit,
    identity,
    ctx_loc,
    collection,
    ambiguous_address,
    secret,
):
    identity["ctx"] = ctx_loc
    result = _collection_result(
        collection,
        state="TX",
        address=ambiguous_address,
        city="Dallas",
        zip_code="75201",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        secrets=(secret,),
    )


@pytest.mark.parametrize("collection", ["properties", "listings"])
@pytest.mark.parametrize(
    "territory,request_location",
    [
        ("TX", "TX"),
        ("Dallas, TX", "Dallas, TX"),
        ("75201", "75201"),
    ],
    ids=["exact-state-grant", "exact-city-grant", "exact-zip-grant"],
)
@pytest.mark.parametrize(
    "ambiguous_address,secret",
    [
        (
            "200 Ocean Dr Miami FL 33139, Dallas, TX 75201",
            "Miami",
        ),
        (
            "123 Congress Ave Austin TX 73301, Dallas, TX 75201",
            "73301",
        ),
        (
            "123 Congress Ave Austin TX 75201, Dallas, TX 75201",
            "Austin",
        ),
        (
            "123 Congress Ave Austin TX 73301-4321, Dallas, TX 75201",
            "73301-4321",
        ),
        (
            "200 Ocean Dr Miami FL, Dallas, TX 75201",
            "Miami",
        ),
        (
            "123 Congress Ave Austin TX, Dallas, TX 75201",
            "Austin",
        ),
    ],
    ids=[
        "hidden-state",
        "hidden-zip",
        "hidden-city",
        "hidden-zip-plus-four",
        "hidden-state-city-without-zip",
        "hidden-same-state-city-without-zip",
    ],
)
async def test_punctuation_free_address_claims_fail_closed_for_exact_grants(
    registry,
    audit,
    identity,
    ctx_loc,
    collection,
    territory,
    request_location,
    ambiguous_address,
    secret,
):
    identity["ctx"] = ctx_loc.model_copy(
        update={"territories": (territory,)}
    )
    result = _collection_result(
        collection,
        state="TX",
        address=ambiguous_address,
        city="Dallas",
        zip_code="75201",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        location=request_location,
        secrets=(secret,),
    )


@pytest.mark.parametrize("context_fixture", ["ctx_loc", "ctx_jv"])
@pytest.mark.parametrize("collection", ["properties", "listings"])
@pytest.mark.parametrize(
    "territory,request_location",
    [
        ("Dallas, TX", "Dallas, TX"),
        ("75201", "75201"),
    ],
    ids=["exact-city-grant", "exact-zip-grant"],
)
@pytest.mark.parametrize(
    "address,secrets",
    [
        (
            "200 Ocean Dr Miami FL; Dallas TX 75201",
            ("Miami",),
        ),
        (
            "123 Congress Ave Austin TX; Dallas TX 75201",
            ("Austin",),
        ),
        (
            "200 Ocean Dr Miami FL / Dallas TX 75201",
            ("Miami",),
        ),
        (
            "123 Congress Ave Austin TX / Dallas TX 75201",
            ("Austin",),
        ),
        (
            "200 Ocean Dr Miami FL Dallas TX 75201",
            ("Miami",),
        ),
        (
            "123 Congress Ave Austin TX Dallas TX 75201",
            ("Austin",),
        ),
        (
            "200 Ocean Dr Miami FL - Dallas TX 75201",
            ("Miami",),
        ),
        (
            "200 Ocean Dr Miami FL | Dallas TX 75201",
            ("Miami",),
        ),
        (
            "200 Ocean Dr Miami FL (Dallas TX 75201)",
            ("Miami",),
        ),
        (
            "200 Ocean Dr Miami FL: Dallas TX 75201",
            ("Miami",),
        ),
        (
            "200 Ocean Dr Miami FL \\ Dallas TX 75201",
            ("Miami",),
        ),
        (
            "200 Ocean Dr Miami FL [Dallas TX 75201]",
            ("Miami",),
        ),
    ],
    ids=[
        "semicolon-miami",
        "semicolon-austin",
        "slash-miami",
        "slash-austin",
        "whitespace-miami",
        "whitespace-austin",
        "hyphen-miami",
        "pipe-miami",
        "parenthesized-miami",
        "colon-miami",
        "backslash-miami",
        "bracketed-miami",
    ],
)
async def test_state_only_claims_across_address_separators_fail_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    territory,
    request_location,
    address,
    secrets,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    result = _collection_result(
        collection,
        state="TX",
        address=address,
        city="Dallas",
        zip_code="75201",
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        location=request_location,
        secrets=secrets,
    )


@pytest.mark.parametrize("context_fixture", ["ctx_loc", "ctx_jv"])
@pytest.mark.parametrize("collection", ["properties", "listings"])
@pytest.mark.parametrize(
    "territory,request_location,record_zip",
    [
        ("Dallas, TX", "Dallas, TX", "75201"),
        ("75201", "75201", "75201"),
        ("75201", "75201", "75201-4321"),
    ],
    ids=[
        "exact-city-grant",
        "five-digit-zip-grant-and-result",
        "five-digit-zip-grant-matches-zip-plus-four",
    ],
)
@pytest.mark.parametrize(
    "address_template,secrets",
    [
        (
            "123 Congress Ave Austin TX 73301; Dallas TX {record_zip}",
            ("Austin", "73301"),
        ),
        (
            "123 Congress Ave Austin TX 73301 / Dallas TX {record_zip}",
            ("Austin", "73301"),
        ),
        (
            "123 Congress Ave Austin TX 73301 Dallas, TX {record_zip}",
            ("Austin", "73301"),
        ),
        (
            "200 Ocean Dr Miami FL 33139 Dallas, TX {record_zip}",
            ("Miami", "33139"),
        ),
    ],
    ids=[
        "semicolon",
        "slash",
        "whitespace-austin",
        "whitespace-miami",
    ],
)
async def test_every_exact_claim_across_noncomma_separators_fails_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    territory,
    request_location,
    record_zip,
    address_template,
    secrets,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    address = address_template.format(record_zip=record_zip)
    result = _collection_result(
        collection,
        state="TX",
        address=address,
        city="Dallas",
        zip_code=record_zip,
        query_location=request_location,
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        location=request_location,
        secrets=secrets,
    )


@pytest.mark.parametrize("context_fixture", ["ctx_loc", "ctx_jv"])
@pytest.mark.parametrize("collection", ["properties", "listings"])
@pytest.mark.parametrize(
    "territory,request_location,record_zip",
    [
        ("Dallas, TX", "Dallas, TX", "75201"),
        ("75201", "75201", "75201-4321"),
    ],
    ids=["exact-city-grant", "five-digit-zip-grant"],
)
@pytest.mark.parametrize(
    "address",
    [
        "123 Oak Ct",
        "100 Main St Unit 33101",
        "100 Main St Unit 33101 USA",
        "123 Main St in Dallas TX 75201",
        "123 Main St or 456 Elm St, Dallas TX 75201",
        "123 MAIN ST IN DALLAS TX 75201",
        "123 MAIN ST OR 456 ELM ST, DALLAS TX 75201",
    ],
    ids=[
        "street-suffix-state-code",
        "labeled-unit-zip",
        "labeled-unit-zip-country",
        "lowercase-preposition",
        "lowercase-conjunction",
        "uppercase-preposition-feed",
        "uppercase-conjunction-feed",
    ],
)
async def test_ordinary_address_collisions_are_not_location_claims(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    territory,
    request_location,
    record_zip,
    address,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    result = _collection_result(
        collection,
        state="TX",
        address=address,
        city="Dallas",
        zip_code=record_zip,
        query_location=request_location,
    )

    call_result = await _call_search(
        registry,
        audit,
        identity,
        result,
        location=request_location,
    )

    assert call_result.data[collection][0]["address"] == address
    assert call_result.data[collection][0]["city"] == "Dallas"
    assert call_result.data[collection][0]["state"] == "TX"
    assert call_result.data[collection][0]["zip_code"] == record_zip


@pytest.mark.parametrize("collection", ["properties", "listings"])
@pytest.mark.parametrize(
    "address",
    [
        "123 NE 2nd Ave Dallas TX 75201",
        "123 Main St NE, Dallas, TX 75201",
        "123 Or Drive, Dallas, TX 75201",
        "123 Austin Street, Dallas, TX 75201",
    ],
    ids=[
        "directional-token",
        "directional-tail",
        "state-code-word",
        "city-name-in-street",
    ],
)
async def test_ordinary_address_text_does_not_create_false_claims(
    registry,
    audit,
    identity,
    ctx_loc,
    collection,
    address,
):
    identity["ctx"] = ctx_loc.model_copy(
        update={"territories": ("Dallas, TX",)}
    )
    result = _collection_result(
        collection,
        state="TX",
        address=address,
        city="Dallas",
        zip_code="75201",
    )

    call_result = await _call_search(
        registry,
        audit,
        identity,
        result,
        location="Dallas, TX",
    )

    assert call_result.data[collection][0]["address"] == address


@pytest.mark.parametrize(
    "result,collection",
    [
        (_legacy_result(_property()), "properties"),
        (_aggregate_result(_listing()), "listings"),
    ],
    ids=["legacy-properties", "aggregate-listings"],
)
async def test_real_search_shapes_release_through_fastmcp_structured_content(
    registry,
    audit,
    identity,
    ctx_loc,
    result,
    collection,
):
    identity["ctx"] = ctx_loc

    call_result = await _call_search(registry, audit, identity, result)

    assert call_result.structured_content is not None
    assert call_result.structured_content[collection] == result[collection]
    assert call_result.data[collection] == result[collection]


@pytest.mark.parametrize(
    "territory,request_location",
    [("Dallas, TX", "Dallas, TX"), ("75201", "75201")],
    ids=["city-state-grant", "zip-grant"],
)
async def test_consistent_narrow_territory_grants_release_matching_records(
    registry,
    audit,
    identity,
    ctx_loc,
    territory,
    request_location,
):
    identity["ctx"] = ctx_loc.model_copy(
        update={"territories": (territory,)}
    )

    call_result = await _call_search(
        registry,
        audit,
        identity,
        _legacy_result(
            _property(),
            query_location=request_location,
        ),
        location=request_location,
    )

    assert call_result.data["properties"][0]["state"] == "TX"


@pytest.mark.parametrize("context_fixture", ["ctx_loc", "ctx_jv"])
@pytest.mark.parametrize("collection", ["properties", "listings"])
@pytest.mark.parametrize(
    "territory,request_location,record_zip",
    [
        ("Dallas, TX", "Dallas, TX", "75201"),
        ("75201", "75201", "75201-4321"),
    ],
    ids=["exact-city-state", "five-digit-grant-matches-zip-plus-four"],
)
async def test_exact_narrow_claims_release_consistent_records(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    territory,
    request_location,
    record_zip,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    result = _collection_result(
        collection,
        state="TX",
        address=f"100 Main Street, Dallas, TX {record_zip}",
        city="Dallas",
        zip_code=record_zip,
        query_location=request_location,
    )

    call_result = await _call_search(
        registry,
        audit,
        identity,
        result,
        location=request_location,
    )

    assert call_result.data[collection][0]["zip_code"] == record_zip


async def test_exact_city_claim_can_contain_a_street_suffix_word(
    registry, audit, identity, ctx_loc
):
    identity["ctx"] = ctx_loc.model_copy(
        update={"territories": ("St. Louis, MO",)}
    )
    result = _legacy_result(
        _property(
            state="MO",
            address="100 Market Street, St. Louis, MO 63101",
            city="St. Louis",
            zip_code="63101",
        ),
        query_location="St. Louis, MO",
    )

    call_result = await _call_search(
        registry,
        audit,
        identity,
        result,
        location="St. Louis, MO",
    )

    assert call_result.data["properties"][0]["city"] == "St. Louis"


@pytest.mark.parametrize("context_fixture", ["ctx_loc", "ctx_jv"])
async def test_listing_raw_is_forbidden_from_restricted_result_egress(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    result = _collection_result(
        "listings",
        state="TX",
        address="100 Main Street, Dallas, TX 75201",
        city="Dallas",
        zip_code="75201",
        raw={
            "untrusted_location": "Miami, FL",
            "untrusted_zip": "33101",
        },
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        secrets=("Miami", "33101"),
    )


@pytest.mark.parametrize(
    "result,secret",
    [
        (
            _legacy_result(error="upstream search unavailable"),
            "upstream search unavailable",
        ),
        (
            _aggregate_result(error="one source timed out"),
            "one source timed out",
        ),
        (
            _legacy_result(
                error="Found owner at 90 Ocean Drive, Miami, FL 33101"
            ),
            "90 Ocean Drive",
        ),
    ],
    ids=[
        "legacy-empty-error",
        "aggregate-empty-error",
        "location-bearing-error",
    ],
)
@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_empty_error_result_collections_fail_closed_for_restricted_profiles(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    result,
    secret,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        secrets=(secret,),
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_search_tool_exception_is_sanitized_for_restricted_profiles(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """Provider exceptions are client-visible output and cannot bypass filtering."""
    identity["ctx"] = request.getfixturevalue(context_fixture)
    secret = "Found owner at 90 Ocean Drive, Miami, FL 33101"

    def leaking_provider_error():
        raise ToolError(secret)

    with pytest.raises(ToolError) as caught:
        await _call_search(
            registry,
            audit,
            identity,
            leaking_provider_error,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert secret not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("with_record", (False, True), ids=("empty", "with-record"))
async def test_aggregate_provider_error_map_fails_closed_for_restricted_profiles(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    with_record,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    records = (_listing(),) if with_record else ()
    payload = _aggregate_result(*records)
    payload["errors"] = {
        "provider": "Found owner at 90 Ocean Drive, Miami, FL 33101"
    }

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        payload,
        secrets=("90 Ocean Drive",),
    )


async def test_content_only_json_tool_result_is_validated(
    registry, audit, identity, ctx_loc
):
    identity["ctx"] = ctx_loc
    result = ToolResult(content=json.dumps(_legacy_result(_property())))

    await _call_search(registry, audit, identity, result)


async def test_structured_and_text_representations_must_both_be_safe(
    registry, audit, identity, ctx_loc
):
    identity["ctx"] = ctx_loc
    result = ToolResult(
        structured_content=_legacy_result(_property()),
        content=json.dumps(
            _legacy_result(
                _property(
                    state="FL",
                    address="93 Ocean Drive, Miami, FL",
                    city="Miami",
                    zip_code="33101",
                )
            )
        ),
    )

    with pytest.raises(ToolError, match="result.*territor"):
        await _call_search(registry, audit, identity, result)


@pytest.mark.parametrize("mismatch", ["record", "numeric-type"])
async def test_all_result_representations_must_be_exactly_equal(
    registry, audit, identity, ctx_loc, mismatch
):
    identity["ctx"] = ctx_loc
    structured = _legacy_result(_property())
    text_payload = _legacy_result(_property())
    if mismatch == "record":
        text_payload = _legacy_result(
            _property(
                address="500 Congress Avenue, Austin, TX",
                city="Austin",
                zip_code="78701",
            )
        )
    else:
        structured["representation_marker"] = 1
        text_payload["representation_marker"] = 1.0
    result = ToolResult(
        structured_content=structured,
        content=json.dumps(text_payload),
    )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        secrets=("Austin",) if mismatch == "record" else (),
    )


async def test_undeclared_tool_result_metadata_fails_closed(
    registry, audit, identity, ctx_loc
):
    identity["ctx"] = ctx_loc
    result = ToolResult(
        structured_content=_legacy_result(_property()),
        meta={"property": {"address": "95 Ocean Drive, Miami, FL"}},
    )

    with pytest.raises(ToolError, match="result.*territor"):
        await _call_search(registry, audit, identity, result)


class _FalseyMetadata(dict):
    def __bool__(self) -> bool:
        return False


class _OverriddenSerializationResult(ToolResult):
    def __init__(self, safe_payload: dict, leaked_payload: dict):
        super().__init__(structured_content=safe_payload)
        self._leaked_payload = leaked_payload

    def to_mcp_result(self):
        return ToolResult(
            structured_content=self._leaked_payload
        ).to_mcp_result()


@pytest.mark.parametrize("override", ["subclass", "instance-shadow"])
async def test_top_level_tool_result_serializer_override_fails_closed(
    registry,
    audit,
    identity,
    ctx_loc,
    override,
):
    identity["ctx"] = ctx_loc
    secret = "98 Ocean Drive, Miami, FL"
    safe_payload = _legacy_result(_property())
    leaked_payload = _legacy_result(
        _property(
            state="FL",
            address=secret,
            city="Miami",
            zip_code="33101",
        )
    )
    if override == "subclass":
        result = _OverriddenSerializationResult(
            safe_payload,
            leaked_payload,
        )
    else:
        result = ToolResult(structured_content=safe_payload)
        result.to_mcp_result = lambda: ToolResult(
            structured_content=leaked_payload
        ).to_mcp_result()

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        secrets=(secret, "Miami", "33101"),
    )


@pytest.mark.parametrize("context_fixture", ["ctx_loc", "ctx_jv"])
@pytest.mark.parametrize("collection", ["properties", "listings"])
@pytest.mark.parametrize(
    "territory,request_location,record_zip",
    [
        ("Dallas, TX", "Dallas, TX", "75201"),
        ("75201", "75201", "75201-4321"),
    ],
    ids=["exact-city-grant", "five-digit-zip-grant"],
)
async def test_mutated_text_content_discriminator_fails_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    territory,
    request_location,
    record_zip,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    secret = "mutated-discriminator-secret"
    payload = _collection_result(
        collection,
        state="TX",
        address=f"100 Main Street, Dallas, TX {record_zip}",
        city="Dallas",
        zip_code=record_zip,
    )
    payload["discriminator_secret"] = secret
    result = ToolResult(content=json.dumps(payload))
    assert len(result.content) == 1
    block = result.content[0]
    assert type(block) is TextContent
    block.type = "image"

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        location=request_location,
        secrets=(secret,),
    )


@pytest.mark.parametrize(
    "channel",
    ["top-level-meta", "block-meta", "block-extra", "annotation-extra"],
)
async def test_client_visible_result_side_channels_fail_closed(
    registry, audit, identity, ctx_loc, channel
):
    identity["ctx"] = ctx_loc
    secret = "96 Ocean Drive, Miami, FL"
    safe_payload = _legacy_result(_property())
    safe_text = json.dumps(safe_payload)
    if channel == "top-level-meta":
        result = ToolResult(
            structured_content=safe_payload,
            meta=_FalseyMetadata({"property_address": secret}),
        )
    elif channel == "block-meta":
        result = ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=safe_text,
                    _meta={"property_address": secret},
                )
            ]
        )
    elif channel == "block-extra":
        result = ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=safe_text,
                    property_address=secret,
                )
            ]
        )
    else:
        result = ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=safe_text,
                    annotations=Annotations(
                        audience=["user"],
                        property_address=secret,
                    ),
                )
            ]
        )

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
        secrets=(secret,),
    )


@pytest.mark.parametrize(
    "raw_json,secret",
    [
        (
            (
                '{"properties":[{"address":"97 Ocean Drive, Miami, FL",'
                '"city":"Miami","state":"FL","zip_code":"33101"}],'
                '"properties":[{"address":"100 Main Street, Dallas, TX",'
                '"city":"Dallas","state":"TX","zip_code":"75201"}]}'
            ),
            "97 Ocean Drive, Miami, FL",
        ),
        (
            (
                '{"properties":[{"address":"100 Main Street, Dallas, TX",'
                '"city":"Dallas","state":"FL","state":"TX",'
                '"zip_code":"75201"}]}'
            ),
            '"state":"FL"',
        ),
        (
            '{"properties":[],"integrity":{"value":1,"value":2}}',
            '"value":1',
        ),
    ],
    ids=["duplicate-top-level", "duplicate-record-field", "duplicate-nested-object"],
)
async def test_duplicate_json_keys_at_any_depth_fail_closed(
    registry, audit, identity, ctx_loc, raw_json, secret
):
    identity["ctx"] = ctx_loc

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        ToolResult(content=raw_json),
        secrets=(secret,),
    )


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
async def test_non_finite_json_constants_fail_closed(
    registry, audit, identity, ctx_loc, constant
):
    identity["ctx"] = ctx_loc
    raw_json = f'{{"properties":[],"metric":{constant}}}'

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        ToolResult(content=raw_json),
        secrets=(constant,),
    )


@pytest.mark.parametrize(
    "malformation",
    [
        "content-none",
        "content-tuple",
        "unsupported-block",
        "invalid-json",
        "depth-65",
        "decoder-recursion",
    ],
)
async def test_malformed_content_has_one_generic_audited_denial(
    registry, audit, identity, ctx_loc, malformation
):
    identity["ctx"] = ctx_loc
    safe_text = json.dumps(_legacy_result(_property()))
    if malformation == "invalid-json":
        result = ToolResult(content='{"properties":[')
    elif malformation in {"depth-65", "decoder-recursion"}:
        depth = 65 if malformation == "depth-65" else 1100
        raw_json = (
            '{"properties":[],"nested":'
            + "[" * depth
            + "0"
            + "]" * depth
            + "}"
        )
        result = ToolResult(content=raw_json)
    else:
        result = ToolResult(content=safe_text)
        if malformation == "content-none":
            result.content = None
        elif malformation == "content-tuple":
            result.content = tuple(result.content)
        else:
            result.content = [object()]

    await _assert_generic_result_denial(
        registry,
        audit,
        identity,
        result,
    )


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"properties": {}},
        {"properties": ["not a mapping"]},
        {"properties": [{"name": "location absent"}]},
        ToolResult(content="not-json"),
    ],
    ids=[
        "missing-collection",
        "non-list-collection",
        "non-mapping-record",
        "missing-location",
        "non-json-content",
    ],
)
async def test_unknown_declared_result_shapes_fail_closed(
    registry, audit, identity, ctx_loc, result
):
    identity["ctx"] = ctx_loc

    with pytest.raises(ToolError, match="result.*territor"):
        await _call_search(registry, audit, identity, result)


@pytest.mark.parametrize("context_fixture", ["ctx_nat", "ctx_op"])
async def test_non_limited_profiles_preserve_result_behavior(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    opaque = {"unexpected": [{"state": "FL"}]}

    call_result = await _call_search(registry, audit, identity, opaque)

    assert call_result.data == opaque


@pytest.mark.parametrize("context_fixture", ["ctx_nat", "ctx_op"])
async def test_non_limited_profiles_preserve_tool_exceptions(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture)
    message = "upstream provider unavailable"

    def provider_error():
        raise ToolError(message)

    with pytest.raises(ToolError, match=message):
        await _call_search(
            registry,
            audit,
            identity,
            provider_error,
        )


async def test_trusted_local_preserves_result_behavior(
    registry, audit, identity
):
    identity["ctx"] = local_context()
    opaque = {"unexpected": [{"state": "FL"}]}

    call_result = await _call_search(registry, audit, identity, opaque)

    assert call_result.data == opaque


async def test_tool_without_declared_result_policy_is_unchanged(
    registry, audit, identity, ctx_loc
):
    identity["ctx"] = ctx_loc
    app = FastMCP(name="no-result-policy-test")

    @app.tool
    async def capabilities():
        return {"opaque": [{"state": "FL"}]}

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool("capabilities", {})
    finally:
        uninstall()

    assert result.data == {"opaque": [{"state": "FL"}]}
