"""Round-seven protocol regressions for market result/request binding.

Every behavior crosses a real FastMCP ``Client`` boundary and the production
``install_access`` middleware.  The synthetic tool bodies return the same
closed Pydantic result shapes as the production market tools.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from cre_mcp.access.engine import RESULT_TERRITORY_DENIAL, _geo_record_claims
from cre_mcp.access.middleware import install_access
from cre_mcp.access.result_models import (
    CompareMarketsResult,
    CoverageSummary,
    MarketIntelResult,
    RankedMarketIntelResult,
)
from cre_mcp.access.territory import _national_location_authority
from cre_mcp.geo.constants import STATE_FIPS
from cre_mcp.models.geo import GeoLevel, GeoRef
from cre_mcp.models.market import RentComparable, RentComps


_RESTRICTED_CONTEXT_FIXTURES = ("ctx_loc", "ctx_jv")


def _geo(
    *,
    level: GeoLevel,
    name: str,
    state_fips: str = "48",
    county_fips: str | None = None,
    cbsa: str | None = None,
    zip_code: str | None = None,
    tract: str | None = None,
) -> GeoRef:
    return GeoRef(
        level=level,
        state_fips=state_fips,
        county_fips=county_fips,
        cbsa=cbsa,
        zip=zip_code,
        tract=tract,
        name=name,
    )


_GEOS = {
    "tx-state": _geo(level=GeoLevel.STATE, name="Texas"),
    "tx-state-code-name": _geo(level=GeoLevel.STATE, name="TX"),
    "dallas-city": _geo(
        level=GeoLevel.CITY,
        name="Dallas",
        county_fips="48113",
    ),
    "dallas-city-legal-name": _geo(
        level=GeoLevel.CITY,
        name="Dallas city",
        county_fips="48113",
    ),
    "austin-city": _geo(
        level=GeoLevel.CITY,
        name="Austin",
        county_fips="48453",
    ),
    "houston-city": _geo(
        level=GeoLevel.CITY,
        name="Houston",
        county_fips="48201",
    ),
    "dallas-county": _geo(
        level=GeoLevel.COUNTY,
        name="Dallas County, TX",
        county_fips="48113",
    ),
    "harris-county": _geo(
        level=GeoLevel.COUNTY,
        name="Harris County, TX",
        county_fips="48201",
    ),
    "utuado-county": _geo(
        level=GeoLevel.COUNTY,
        name="Utuado Municipio, PR",
        state_fips="72",
        county_fips="72141",
    ),
    "bronx-county": _geo(
        level=GeoLevel.COUNTY,
        name="Bronx County, NY",
        state_fips="36",
        county_fips="36005",
    ),
    "richmond-county": _geo(
        level=GeoLevel.COUNTY,
        name="Richmond County, NY",
        state_fips="36",
        county_fips="36085",
    ),
    "dallas-zip": _geo(
        level=GeoLevel.ZIP,
        name="75201",
        zip_code="75201",
    ),
    "dallas-other-zip": _geo(
        level=GeoLevel.ZIP,
        name="75202",
        zip_code="75202",
    ),
    "austin-zip": _geo(
        level=GeoLevel.ZIP,
        name="78701",
        zip_code="78701",
    ),
    "harris-tract": _geo(
        level=GeoLevel.TRACT,
        name="Houston, TX",
        county_fips="48201",
        tract="48201000100",
    ),
}


# The request and returned GeoRef are both inside a broad Texas grant.  These
# cases isolate missing exact request/result binding from ordinary geofencing.
_MARKET_BINDING_FAILURES = (
    ("mi-bind-state-to-city", "TX", "TX", "dallas-city"),
    ("mi-bind-city-to-sibling-city", "Dallas, TX", "TX", "austin-city"),
    (
        "mi-bind-county-to-sibling-county",
        "Dallas County, TX",
        "TX",
        "harris-county",
    ),
    ("mi-bind-zip-to-sibling-zip", "75201", "TX", "austin-zip"),
    ("mi-bind-state-to-tract", "TX", "TX", "harris-tract"),
)


_MARKET_NORMALIZATION_CONTROLS = (
    ("mi-control-state-name-country", "texas USA", "TX", "tx-state-code-name"),
    (
        "mi-control-city-case-state-name-country",
        "dALLas, texas usa",
        "Dallas, TX",
        "dallas-city-legal-name",
    ),
    (
        "mi-control-county-case-state-name-country",
        "dallas county, texas usa",
        "TX",
        "dallas-county",
    ),
    (
        "mi-control-zip-plus-four-country",
        "75201-4321 USA",
        "75201",
        "dallas-zip",
    ),
)


# These are exact GeoRef carrier escapes from the independent read-only audit.
# Each payload is a closed GeoRef, but its declared fields do not describe one
# authoritative place.
_MARKET_GEO_RECONCILIATION_FAILURES = (
    (
        "mi-geo-zip-name-other-city",
        "75201",
        "75201",
        _geo(level=GeoLevel.ZIP, name="Austin, TX", zip_code="75201"),
    ),
    (
        "mi-geo-zip-name-unknown",
        "75201",
        "75201",
        _geo(level=GeoLevel.ZIP, name="Atlantis", zip_code="75201"),
    ),
    (
        "mi-geo-county-carries-unrelated-zip",
        "75201",
        "75201",
        _geo(
            level=GeoLevel.COUNTY,
            name="Harris County, TX",
            county_fips="48201",
            zip_code="75201",
        ),
    ),
    (
        "mi-geo-tract-carries-unrelated-zip",
        "75201",
        "75201",
        _geo(
            level=GeoLevel.TRACT,
            name="Houston, TX",
            county_fips="48201",
            zip_code="75201",
            tract="48201000100",
        ),
    ),
    (
        "mi-geo-city-carries-sibling-county",
        "Dallas, TX",
        "Dallas, TX",
        _geo(
            level=GeoLevel.CITY,
            name="Dallas, TX",
            county_fips="48201",
        ),
    ),
    (
        "mi-geo-city-carries-miami-cbsa",
        "Dallas, TX",
        "Dallas, TX",
        _geo(
            level=GeoLevel.CITY,
            name="Dallas, TX",
            county_fips="48113",
            cbsa="33100",
        ),
    ),
    (
        "mi-geo-county-name-unknown",
        "Harris County, TX",
        "TX",
        _geo(
            level=GeoLevel.COUNTY,
            name="Atlantis",
            county_fips="48201",
        ),
    ),
    (
        "mi-geo-tract-name-unknown",
        "TX",
        "TX",
        _geo(
            level=GeoLevel.TRACT,
            name="Atlantis",
            county_fips="48201",
            tract="48201000100",
        ),
    ),
    (
        "mi-geo-zip-carries-harris-county-and-miami-cbsa",
        "75201",
        "75201",
        _geo(
            level=GeoLevel.ZIP,
            name="75201",
            county_fips="48201",
            cbsa="33100",
            zip_code="75201",
        ),
    ),
    (
        "mi-geo-zip-carries-harris-tract-without-county",
        "75201",
        "75201",
        _geo(
            level=GeoLevel.ZIP,
            name="75201",
            zip_code="75201",
            tract="48201000100",
        ),
    ),
    (
        "mi-geo-dallas-county-carries-miami-cbsa",
        "Dallas County, TX",
        "TX",
        _geo(
            level=GeoLevel.COUNTY,
            name="Dallas County, TX",
            county_fips="48113",
            cbsa="33100",
        ),
    ),
    (
        "mi-geo-harris-tract-named-dallas",
        "TX",
        "TX",
        _geo(
            level=GeoLevel.TRACT,
            name="Dallas, TX",
            county_fips="48201",
            tract="48201000100",
        ),
    ),
    (
        "mi-geo-harris-tract-named-dallas-address",
        "TX",
        "TX",
        _geo(
            level=GeoLevel.TRACT,
            name="100 Main Street, Dallas, TX 75201",
            county_fips="48201",
            tract="48201000100",
        ),
    ),
    (
        "mi-geo-dallas-city-carries-harris-county-and-tract",
        "Dallas, TX",
        "Dallas, TX",
        _geo(
            level=GeoLevel.CITY,
            name="Dallas, TX",
            county_fips="48201",
            tract="48201000100",
        ),
    ),
    (
        "mi-geo-zip-city-county-has-no-common-intersection",
        "00601",
        "00601",
        _geo(
            level=GeoLevel.ZIP,
            name="Adjuntas, PR 00601",
            state_fips="72",
            county_fips="72141",
            zip_code="00601",
        ),
    ),
    (
        "mi-geo-city-name-embeds-unrelated-zip",
        "Dallas, TX",
        "Dallas, TX",
        _geo(
            level=GeoLevel.CITY,
            name="Dallas, TX 78701",
            county_fips="48113",
        ),
    ),
    (
        "mi-geo-city-carries-invalid-zero-tract",
        "Dallas, TX",
        "Dallas, TX",
        _geo(
            level=GeoLevel.CITY,
            name="Dallas, TX",
            county_fips="48113",
            tract="48113000000",
        ),
    ),
    (
        "mi-geo-city-carries-unsupported-tract",
        "Dallas, TX",
        "Dallas, TX",
        _geo(
            level=GeoLevel.CITY,
            name="Dallas, TX",
            county_fips="48113",
            tract="48113999999",
        ),
    ),
    (
        "mi-geo-zip-carries-unsupported-tract",
        "75201",
        "75201",
        _geo(
            level=GeoLevel.ZIP,
            name="Dallas, TX 75201",
            county_fips="48113",
            zip_code="75201",
            tract="48113999999",
        ),
    ),
    (
        "mi-geo-dallas-city-carries-real-irving-tract",
        "Dallas, TX 75061",
        "Dallas, TX 75061",
        _geo(
            level=GeoLevel.CITY,
            name="Dallas, TX 75061",
            county_fips="48113",
            zip_code="75061",
            tract="48113014407",
        ),
    ),
)


_MARKET_GEO_RECONCILIATION_CONTROLS = (
    (
        "mi-geo-control-dallas-zip-carriers",
        "75201",
        "75201",
        _geo(
            level=GeoLevel.ZIP,
            name="75201",
            county_fips="48113",
            cbsa="19100",
            zip_code="75201",
        ),
    ),
    (
        "mi-geo-control-dallas-county-cbsa",
        "Dallas County, TX",
        "TX",
        _geo(
            level=GeoLevel.COUNTY,
            name="Dallas County, TX",
            county_fips="48113",
            cbsa="19100",
        ),
    ),
    (
        "mi-geo-control-dallas-city-carriers",
        "Dallas, TX",
        "Dallas, TX",
        _geo(
            level=GeoLevel.CITY,
            name="Dallas, TX",
            county_fips="48113",
            cbsa="19100",
        ),
    ),
    (
        "mi-geo-control-city-name-embeds-matching-zip",
        "Dallas, TX",
        "Dallas, TX",
        _geo(
            level=GeoLevel.CITY,
            name="Dallas, TX 75201",
            county_fips="48113",
        ),
    ),
)


# Unknown nested location carriers must never survive the closed GeoRef result
# contract.  These names mirror provider-shaped alternatives seen during the
# independent release audit.  Each value points outside the otherwise valid
# Dallas result so a future model expansion cannot silently reopen the escape.
_GEOREF_UNKNOWN_LOCATION_CARRIERS = (
    ("mi-georef-unknown-zip-code", "zip_code", "33132"),
    ("mi-georef-unknown-place-fips", "place_fips", "1245000"),
    ("mi-georef-unknown-csa", "csa", "370"),
    ("mi-georef-unknown-county-name", "county_name", "Miami-Dade County"),
    ("mi-georef-unknown-state-name", "state_name", "Florida"),
    ("mi-georef-unknown-metro", "metro", "Miami-Fort Lauderdale-Pompano Beach"),
)


# The access boundary must accept every authoritative national city/ZIP that
# the production resolver can emit, not only entries present in a hand-curated
# fallback subset.  Each request and workspace grant is exact, and every
# populated GeoRef carrier describes that same place.
_NATIONAL_EXACT_GEO_CONTROLS = (
    (
        "mi-national-city-seattle",
        "Seattle, WA",
        "Seattle, WA",
        _geo(
            level=GeoLevel.CITY,
            name="Seattle, WA",
            state_fips="53",
            county_fips="53033",
            cbsa="42660",
        ),
    ),
    (
        "mi-national-city-los-angeles",
        "Los Angeles, CA",
        "Los Angeles, CA",
        _geo(
            level=GeoLevel.CITY,
            name="Los Angeles, CA",
            state_fips="06",
            county_fips="06037",
            cbsa="31080",
        ),
    ),
    (
        "mi-national-zip-seattle-98101",
        "98101",
        "98101",
        _geo(
            level=GeoLevel.ZIP,
            name="98101",
            state_fips="53",
            county_fips="53033",
            cbsa="42660",
            zip_code="98101",
        ),
    ),
    (
        "mi-national-zip-los-angeles-90001",
        "90001",
        "90001",
        _geo(
            level=GeoLevel.ZIP,
            name="90001",
            state_fips="06",
            county_fips="06037",
            cbsa="31080",
            zip_code="90001",
        ),
    ),
    (
        "mi-national-postal-city-bronx-10451",
        "10451",
        "10451",
        _geo(
            level=GeoLevel.ZIP,
            name="Bronx, NY 10451",
            state_fips="36",
            county_fips="36005",
            zip_code="10451",
        ),
    ),
    (
        "mi-national-postal-city-staten-island-10301",
        "10301",
        "10301",
        _geo(
            level=GeoLevel.ZIP,
            name="Staten Island, NY 10301",
            state_fips="36",
            county_fips="36085",
            zip_code="10301",
        ),
    ),
    (
        "mi-national-non-place-city-washington-exact-grant",
        "Washington, DC",
        "Washington, DC",
        _geo(
            level=GeoLevel.CITY,
            name="Washington, DC",
            state_fips="11",
            county_fips="11001",
            cbsa="47900",
        ),
    ),
    (
        "mi-national-non-place-city-washington-state-grant",
        "Washington, DC",
        "DC",
        _geo(
            level=GeoLevel.CITY,
            name="Washington, DC",
            state_fips="11",
            county_fips="11001",
            cbsa="47900",
        ),
    ),
    (
        "mi-national-terminal-state-fort-washington-md",
        "Fort Washington, MD",
        "Fort Washington, MD",
        _geo(
            level=GeoLevel.CITY,
            name="Fort Washington CDP",
            state_fips="24",
            county_fips="24033",
            cbsa="47900",
        ),
    ),
    (
        "mi-national-terminal-state-west-new-york-nj",
        "West New York, NJ",
        "West New York, NJ",
        _geo(
            level=GeoLevel.CITY,
            name="West New York town",
            state_fips="34",
            county_fips="34017",
            cbsa="35620",
        ),
    ),
    (
        "mi-national-terminal-state-new-virginia-ia",
        "New Virginia, IA",
        "New Virginia, IA",
        _geo(
            level=GeoLevel.CITY,
            name="New Virginia city",
            state_fips="19",
            county_fips="19181",
            cbsa="19780",
        ),
    ),
    (
        "mi-national-terminal-state-lake-california-ca",
        "Lake California, CA",
        "Lake California, CA",
        _geo(
            level=GeoLevel.CITY,
            name="Lake California CDP",
            state_fips="06",
            county_fips="06103",
            cbsa="39780",
        ),
    ),
    (
        "mi-national-terminal-state-mount-washington-ky",
        "Mount Washington, KY",
        "Mount Washington, KY",
        _geo(
            level=GeoLevel.CITY,
            name="Mount Washington city",
            state_fips="21",
            county_fips="21029",
            cbsa="31140",
        ),
    ),
    (
        "mi-national-terminal-state-port-washington-ny",
        "Port Washington, NY",
        "Port Washington, NY",
        _geo(
            level=GeoLevel.CITY,
            name="Port Washington CDP",
            state_fips="36",
            county_fips="36059",
            cbsa="35620",
        ),
    ),
)


# These controls keep national authority expansion fail closed.  The state,
# city/ZIP, request, and grant agree, but the returned county and CBSA point to
# a different place in the same state.
_NATIONAL_GEO_CONTRADICTIONS = (
    (
        "mi-national-city-seattle-wrong-same-state-carriers",
        "Seattle, WA",
        "Seattle, WA",
        _geo(
            level=GeoLevel.CITY,
            name="Seattle, WA",
            state_fips="53",
            county_fips="53053",
            cbsa="44060",
        ),
    ),
    (
        "mi-national-city-los-angeles-wrong-same-state-carriers",
        "Los Angeles, CA",
        "Los Angeles, CA",
        _geo(
            level=GeoLevel.CITY,
            name="Los Angeles, CA",
            state_fips="06",
            county_fips="06075",
            cbsa="41860",
        ),
    ),
    (
        "mi-national-zip-seattle-wrong-same-state-carriers",
        "98101",
        "98101",
        _geo(
            level=GeoLevel.ZIP,
            name="98101",
            state_fips="53",
            county_fips="53053",
            cbsa="44060",
            zip_code="98101",
        ),
    ),
    (
        "mi-national-zip-los-angeles-wrong-same-state-carriers",
        "90001",
        "90001",
        _geo(
            level=GeoLevel.ZIP,
            name="90001",
            state_fips="06",
            county_fips="06075",
            cbsa="41860",
            zip_code="90001",
        ),
    ),
)


_RENT_TOP_LEVEL_BINDING_FAILURES = (
    ("rent-bind-state-to-city", "TX", "dallas-city"),
    ("rent-bind-city-to-sibling-city", "Dallas, TX", "austin-city"),
    (
        "rent-bind-county-to-sibling-county",
        "Dallas County, TX",
        "harris-county",
    ),
    ("rent-bind-zip-to-sibling-zip", "75201", "austin-zip"),
)


_RENT_COMP_FAILURES = (
    (
        "rent-comp-city-substitution",
        "Dallas, TX",
        "dallas-city",
        ("100 Congress Avenue, Austin, TX 78701",),
        None,
    ),
    (
        "rent-comp-county-substitution",
        "Dallas County, TX",
        "dallas-county",
        ("Harris County, TX",),
        None,
    ),
    (
        "rent-comp-zip-substitution",
        "75201",
        "dallas-zip",
        ("100 Main Street, Dallas, TX 75202",),
        None,
    ),
    (
        "rent-comp-mixed-second-record-substitution",
        "Dallas, TX",
        "dallas-city",
        (
            "100 Main Street, Dallas, TX 75201",
            "100 Congress Avenue, Austin, TX 78701",
        ),
        None,
    ),
    (
        "rent-comp-null-location",
        "Dallas, TX",
        "dallas-city",
        (None,),
        None,
    ),
    (
        "rent-comp-blank-location",
        "Dallas, TX",
        "dallas-city",
        ("   ",),
        None,
    ),
    (
        "rent-comp-omitted-location",
        "Dallas, TX",
        "dallas-city",
        (None,),
        0,
    ),
)


_RENT_BINDING_CONTROLS = (
    (
        "rent-control-state-normalization",
        "texas USA",
        "tx-state-code-name",
        (
            "100 Main Street, Dallas, TX 75201",
            "100 Congress Avenue, Austin, Texas 78701 USA",
        ),
    ),
    (
        "rent-control-city-normalization-every-comp",
        "dALLas, texas usa",
        "dallas-city-legal-name",
        (
            "100 Main Street, Dallas, TX 75201",
            "200 Elm Street, dallas, texas 75201 USA",
        ),
    ),
    (
        "rent-control-county-normalization",
        "dallas county, texas usa",
        "dallas-county",
        ("Dallas County, TX",),
    ),
    (
        "rent-control-zip-normalization-every-comp",
        "75201-4321 USA",
        "dallas-zip",
        (
            "100 Main Street, Dallas, TX 75201 USA",
            "75201-9999",
        ),
    ),
)


_RENT_POSTAL_COUNTY_CONTROLS = (
    (
        "rent-control-bronx-postal-city-within-county",
        "Bronx County, NY",
        "bronx-county",
        ("100 East 149th Street, Bronx, NY 10451",),
    ),
    (
        "rent-control-staten-island-postal-city-within-county",
        "Richmond County, NY",
        "richmond-county",
        ("100 Stuyvesant Place, Staten Island, NY 10301",),
    ),
)


_COMPARE_REQUEST_LOCATIONS = ("Dallas, TX", "Austin, TX")

# Rows are ``(returned location, GeoRef key)``.  Every result is a closed
# CompareMarketsResult; only its binding relationship is varied.
_COMPARE_BINDING_FAILURES = (
    (
        "compare-omitted-requested-market",
        _COMPARE_REQUEST_LOCATIONS,
        (("Dallas, TX", "dallas-city"),),
        1,
        {},
    ),
    (
        "compare-extra-unrequested-market",
        _COMPARE_REQUEST_LOCATIONS,
        (
            ("Dallas, TX", "dallas-city"),
            ("Austin, TX", "austin-city"),
            ("Houston, TX", "houston-city"),
        ),
        3,
        {},
    ),
    (
        "compare-duplicate-returned-market",
        _COMPARE_REQUEST_LOCATIONS,
        (
            ("Dallas, TX", "dallas-city"),
            ("Dallas, TX", "dallas-city"),
        ),
        2,
        {},
    ),
    (
        "compare-count-understates-markets",
        _COMPARE_REQUEST_LOCATIONS,
        (
            ("Dallas, TX", "dallas-city"),
            ("Austin, TX", "austin-city"),
        ),
        1,
        {},
    ),
    (
        "compare-count-overstates-markets",
        _COMPARE_REQUEST_LOCATIONS,
        (
            ("Dallas, TX", "dallas-city"),
            ("Austin, TX", "austin-city"),
        ),
        3,
        {},
    ),
    (
        "compare-empty-result-for-nonempty-request",
        _COMPARE_REQUEST_LOCATIONS,
        (),
        0,
        {},
    ),
    (
        "compare-partial-error-result",
        _COMPARE_REQUEST_LOCATIONS,
        (("Dallas, TX", "dallas-city"),),
        1,
        {"Austin, TX": "synthetic upstream failure"},
    ),
    (
        "compare-one-location-geo-pair-substituted",
        _COMPARE_REQUEST_LOCATIONS,
        (
            ("Dallas, TX", "austin-city"),
            ("Austin, TX", "austin-city"),
        ),
        2,
        {},
    ),
    (
        "compare-all-location-geo-pairs-swapped",
        _COMPARE_REQUEST_LOCATIONS,
        (
            ("Dallas, TX", "austin-city"),
            ("Austin, TX", "dallas-city"),
        ),
        2,
        {},
    ),
)


_COMPARE_BINDING_CONTROLS = (
    (
        "compare-control-exact-order",
        _COMPARE_REQUEST_LOCATIONS,
        (
            ("Dallas, TX", "dallas-city"),
            ("Austin, TX", "austin-city"),
        ),
    ),
    (
        "compare-control-reordered-results",
        _COMPARE_REQUEST_LOCATIONS,
        (
            ("Austin, TX", "austin-city"),
            ("Dallas, TX", "dallas-city"),
        ),
    ),
    (
        "compare-control-normalized-multiset",
        ("dALLas, texas USA", "78701-4321 USA"),
        (
            ("78701", "austin-zip"),
            ("Dallas, TX", "dallas-city-legal-name"),
        ),
    ),
)


def _market_payload(geo: GeoRef) -> dict[str, Any]:
    return MarketIntelResult(
        geo=geo,
        market_score=0.0,
        score_confidence=0.0,
        coverage_summary=CoverageSummary(
            covered=0,
            total=0,
            ratio=0.0,
        ),
    ).model_dump(mode="json")


def _rent_payload(
    geo: GeoRef,
    locations: Sequence[str | None] = (),
    *,
    omit_location_index: int | None = None,
) -> dict[str, Any]:
    comps: list[dict[str, Any]] = []
    for index, location in enumerate(locations):
        comp = RentComparable(
            source=f"Synthetic Rent {index + 1}",
            rent=2_000 + index,
            location=location,
        ).model_dump(mode="json")
        if index == omit_location_index:
            comp.pop("location")
        comps.append(comp)
    # Validate the complete payload through the production model.  Omitted
    # location currently validates because the field is optional, which is the
    # contract defect the corresponding regression preserves.
    payload = RentComps.model_validate(
        {
            "geo": geo.model_dump(mode="json"),
            "comps": comps,
        }
    ).model_dump(mode="json")
    if omit_location_index is not None:
        payload["comps"][omit_location_index].pop("location")
    return payload


def _ranked_market_payload(
    location: str,
    geo: GeoRef,
    rank: int,
) -> dict[str, Any]:
    payload = {
        **_market_payload(geo),
        "location": location,
        "rank": rank,
    }
    return RankedMarketIntelResult.model_validate(payload).model_dump(mode="json")


def _compare_payload(
    rows: Sequence[tuple[str, str]],
    *,
    count: int | None = None,
    errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    markets = [
        _ranked_market_payload(location, _GEOS[geo_key], rank)
        for rank, (location, geo_key) in enumerate(rows, start=1)
    ]
    payload = CompareMarketsResult(
        markets=markets,
        errors=dict(errors or {}),
        count=len(markets),
    ).model_dump(mode="json")
    # Count mismatches must cross the actual FastMCP and access-middleware
    # boundary.  Build a valid closed envelope first, then vary only the wire
    # payload so the production post-result validator, rather than this test
    # fixture's constructor, owns the rejection.
    if count is not None:
        payload["count"] = count
    return payload


async def _call_market_intel(
    registry,
    audit,
    identity,
    *,
    location: str,
    payload: dict[str, Any],
    executions: list[int],
) -> Any:
    app = FastMCP(name="round-seven-market-intel-binding")

    @app.tool
    async def market_intel(location: str) -> dict[str, Any]:
        del location
        executions[0] += 1
        return payload

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool("market_intel", {"location": location})
    finally:
        uninstall()
    return result


async def _call_rent_comparables(
    registry,
    audit,
    identity,
    *,
    location: str,
    payload: dict[str, Any],
    executions: list[int],
) -> Any:
    app = FastMCP(name="round-seven-rent-comparable-binding")

    @app.tool
    async def get_rent_comparables(
        location: str,
        bedrooms: int | None = None,
        property_type: str | None = None,
    ) -> dict[str, Any]:
        del location, bedrooms, property_type
        executions[0] += 1
        return payload

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool(
                "get_rent_comparables",
                {"location": location},
            )
    finally:
        uninstall()
    return result


async def _call_compare_markets(
    registry,
    audit,
    identity,
    *,
    locations: Sequence[str],
    payload: dict[str, Any],
    executions: list[int],
) -> Any:
    app = FastMCP(name="round-seven-compare-market-binding")

    @app.tool
    async def compare_markets(locations: list[str]) -> dict[str, Any]:
        del locations
        executions[0] += 1
        return payload

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool(
                "compare_markets",
                {"locations": list(locations)},
            )
    finally:
        uninstall()
    return result


def _assert_post_result_denial(audit, identity, tool_name: str, caught) -> None:
    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    event = audit.events(identity["ctx"].workspace_id)[-1]
    assert event.tool == tool_name
    assert event.decision == "denied"
    assert event.reason == RESULT_TERRITORY_DENIAL


def _case_signature(family: str, case: object) -> str:
    def default(value: object) -> object:
        if isinstance(value, GeoRef):
            return value.model_dump(mode="json")
        raise TypeError(type(value).__name__)

    return json.dumps(
        (family, case),
        default=default,
        sort_keys=True,
    )


def test_round_seven_market_binding_matrix_cardinality_and_uniqueness() -> None:
    tables = (
        ("market-binding-failure", _MARKET_BINDING_FAILURES, 5),
        ("market-normalization-control", _MARKET_NORMALIZATION_CONTROLS, 4),
        (
            "market-georef-reconciliation-failure",
            _MARKET_GEO_RECONCILIATION_FAILURES,
            20,
        ),
        (
            "market-georef-reconciliation-control",
            _MARKET_GEO_RECONCILIATION_CONTROLS,
            4,
        ),
        (
            "market-georef-unknown-location-carrier",
            _GEOREF_UNKNOWN_LOCATION_CARRIERS,
            6,
        ),
        ("national-exact-georef-control", _NATIONAL_EXACT_GEO_CONTROLS, 14),
        (
            "national-georef-contradiction",
            _NATIONAL_GEO_CONTRADICTIONS,
            4,
        ),
        ("rent-top-level-binding-failure", _RENT_TOP_LEVEL_BINDING_FAILURES, 4),
        ("rent-comp-failure", _RENT_COMP_FAILURES, 7),
        ("rent-binding-control", _RENT_BINDING_CONTROLS, 4),
        ("rent-postal-county-control", _RENT_POSTAL_COUNTY_CONTROLS, 2),
        ("compare-binding-failure", _COMPARE_BINDING_FAILURES, 9),
        ("compare-binding-control", _COMPARE_BINDING_CONTROLS, 3),
    )

    assert sum(expected for _family, _cases, expected in tables) == 86
    assert [len(cases) for _family, cases, _expected in tables] == [
        expected for _family, _cases, expected in tables
    ]
    case_ids = [case[0] for _family, cases, _expected in tables for case in cases]
    assert len(case_ids) == len(set(case_ids)) == 86
    signatures = [
        _case_signature(family, case)
        for family, cases, _expected in tables
        for case in cases
    ]
    assert len(signatures) == len(set(signatures)) == 86


def test_unsupported_tract_georef_fails_closed_without_relation_authority() -> None:
    """Formatted tract text is not treated as authority for restricted release."""

    assert _geo_record_claims(
        _GEOS["harris-tract"].model_dump(mode="json")
    ) is None


def test_every_single_identity_national_place_reconciles_as_city_georef() -> None:
    """Every unambiguous pinned Census place must survive the same engine path."""

    authority = _national_location_authority()
    failures: list[tuple[str, str, str, str]] = []
    checked = 0
    for (state, name), place_geoids in authority[2].items():
        if len(place_geoids) != 1:
            continue
        place_geoid = next(iter(place_geoids))
        for county_fips in authority[3][place_geoid]:
            cbsa_codes = authority[7].get(county_fips, frozenset())
            cbsa = next(iter(cbsa_codes)) if len(cbsa_codes) == 1 else None
            checked += 1
            claims = _geo_record_claims(
                {
                    "level": "city",
                    "state_fips": STATE_FIPS[state],
                    "county_fips": county_fips,
                    "cbsa": cbsa,
                    "zip": None,
                    "tract": None,
                    "name": name,
                }
            )
            if claims is None:
                failures.append((name, state, county_fips, place_geoid))

    # This is the exact number of county intersections for place names whose
    # state/name key resolves to one Census place GEOID in the pinned artifact.
    # Keep it locked so a truncated authority file cannot make the exhaustive
    # reconciliation loop quietly smaller.
    assert checked == 32_868
    assert failures == []


def test_every_authoritative_county_reconciles_as_county_georef() -> None:
    """Every pinned county-equivalent name must survive its declared FIPS."""

    authority = _national_location_authority()
    failures: list[tuple[str, str, str]] = []
    for county_fips, (state, name) in authority[0].items():
        cbsa_codes = authority[7].get(county_fips, frozenset())
        cbsa = next(iter(cbsa_codes)) if len(cbsa_codes) == 1 else None
        claims = _geo_record_claims(
            {
                "level": "county",
                "state_fips": STATE_FIPS[state],
                "county_fips": county_fips,
                "cbsa": cbsa,
                "zip": None,
                "tract": None,
                "name": name,
            }
        )
        if claims is None:
            failures.append((name, state, county_fips))

    assert len(authority[0]) == 3_221
    assert failures == []


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,location,territory,geo_key",
    _MARKET_BINDING_FAILURES,
    ids=[case[0] for case in _MARKET_BINDING_FAILURES],
)
async def test_market_intel_result_geography_binds_exactly_to_request(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    location,
    territory,
    geo_key,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    with pytest.raises(ToolError) as caught:
        await _call_market_intel(
            registry,
            audit,
            identity,
            location=location,
            payload=_market_payload(_GEOS[geo_key]),
            executions=executions,
        )

    assert executions == [1]
    _assert_post_result_denial(audit, identity, "market_intel", caught)


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,location,territory,geo_key",
    _MARKET_NORMALIZATION_CONTROLS,
    ids=[case[0] for case in _MARKET_NORMALIZATION_CONTROLS],
)
async def test_market_intel_exact_binding_accepts_normalized_equivalence(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    location,
    territory,
    geo_key,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    result = await _call_market_intel(
        registry,
        audit,
        identity,
        location=location,
        payload=_market_payload(_GEOS[geo_key]),
        executions=executions,
    )

    assert executions == [1]
    assert result.data["geo"] == _GEOS[geo_key].model_dump(mode="json")


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,location,territory,geo",
    _MARKET_GEO_RECONCILIATION_FAILURES,
    ids=[case[0] for case in _MARKET_GEO_RECONCILIATION_FAILURES],
)
async def test_market_intel_rejects_internally_inconsistent_georef_carriers(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    location,
    territory,
    geo,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    with pytest.raises(ToolError) as caught:
        await _call_market_intel(
            registry,
            audit,
            identity,
            location=location,
            payload=_market_payload(geo),
            executions=executions,
        )

    assert executions == [1]
    _assert_post_result_denial(audit, identity, "market_intel", caught)


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,location,territory,geo",
    _MARKET_GEO_RECONCILIATION_CONTROLS,
    ids=[case[0] for case in _MARKET_GEO_RECONCILIATION_CONTROLS],
)
async def test_market_intel_releases_authoritatively_consistent_georef_carriers(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    location,
    territory,
    geo,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    result = await _call_market_intel(
        registry,
        audit,
        identity,
        location=location,
        payload=_market_payload(geo),
        executions=executions,
    )

    assert executions == [1]
    assert result.data["geo"] == geo.model_dump(mode="json")


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,carrier,value",
    _GEOREF_UNKNOWN_LOCATION_CARRIERS,
    ids=[case[0] for case in _GEOREF_UNKNOWN_LOCATION_CARRIERS],
)
async def test_market_intel_rejects_unknown_nested_georef_location_carriers(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    carrier,
    value,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("Dallas, TX",)}
    )
    payload = _market_payload(_GEOS["dallas-city"])
    payload["geo"][carrier] = value
    executions = [0]

    with pytest.raises(ToolError) as caught:
        await _call_market_intel(
            registry,
            audit,
            identity,
            location="Dallas, TX",
            payload=payload,
            executions=executions,
        )

    assert executions == [1]
    _assert_post_result_denial(audit, identity, "market_intel", caught)


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,location,territory,geo",
    _NATIONAL_EXACT_GEO_CONTROLS,
    ids=[case[0] for case in _NATIONAL_EXACT_GEO_CONTROLS],
)
async def test_market_intel_releases_exact_national_city_and_zip_georefs(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    location,
    territory,
    geo,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    result = await _call_market_intel(
        registry,
        audit,
        identity,
        location=location,
        payload=_market_payload(geo),
        executions=executions,
    )

    assert executions == [1]
    assert result.data["geo"] == geo.model_dump(mode="json")


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,location,territory,geo",
    _NATIONAL_GEO_CONTRADICTIONS,
    ids=[case[0] for case in _NATIONAL_GEO_CONTRADICTIONS],
)
async def test_market_intel_denies_same_state_wrong_county_and_cbsa_carriers(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    location,
    territory,
    geo,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    with pytest.raises(ToolError) as caught:
        await _call_market_intel(
            registry,
            audit,
            identity,
            location=location,
            payload=_market_payload(geo),
            executions=executions,
        )

    assert executions == [1]
    _assert_post_result_denial(audit, identity, "market_intel", caught)


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,location,geo_key",
    _RENT_TOP_LEVEL_BINDING_FAILURES,
    ids=[case[0] for case in _RENT_TOP_LEVEL_BINDING_FAILURES],
)
async def test_rent_comparables_top_level_geography_binds_exactly_to_request(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    location,
    geo_key,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError) as caught:
        await _call_rent_comparables(
            registry,
            audit,
            identity,
            location=location,
            payload=_rent_payload(_GEOS[geo_key]),
            executions=executions,
        )

    assert executions == [1]
    _assert_post_result_denial(audit, identity, "get_rent_comparables", caught)


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,location,geo_key,comp_locations,omit_location_index",
    _RENT_COMP_FAILURES,
    ids=[case[0] for case in _RENT_COMP_FAILURES],
)
async def test_every_rent_comp_has_required_bound_location(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    location,
    geo_key,
    comp_locations,
    omit_location_index,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError) as caught:
        await _call_rent_comparables(
            registry,
            audit,
            identity,
            location=location,
            payload=_rent_payload(
                _GEOS[geo_key],
                comp_locations,
                omit_location_index=omit_location_index,
            ),
            executions=executions,
        )

    assert executions == [1]
    _assert_post_result_denial(audit, identity, "get_rent_comparables", caught)


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,location,geo_key,comp_locations",
    _RENT_BINDING_CONTROLS,
    ids=[case[0] for case in _RENT_BINDING_CONTROLS],
)
async def test_rent_comparable_binding_accepts_normalized_equivalence(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    location,
    geo_key,
    comp_locations,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    result = await _call_rent_comparables(
        registry,
        audit,
        identity,
        location=location,
        payload=_rent_payload(_GEOS[geo_key], comp_locations),
        executions=executions,
    )

    assert executions == [1]
    assert [comp["location"] for comp in result.data["comps"]] == list(
        comp_locations
    )


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,location,geo_key,comp_locations",
    _RENT_POSTAL_COUNTY_CONTROLS,
    ids=[case[0] for case in _RENT_POSTAL_COUNTY_CONTROLS],
)
async def test_rent_comparable_accepts_exact_postal_city_zip_within_county(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    location,
    geo_key,
    comp_locations,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("NY",)}
    )
    executions = [0]

    result = await _call_rent_comparables(
        registry,
        audit,
        identity,
        location=location,
        payload=_rent_payload(_GEOS[geo_key], comp_locations),
        executions=executions,
    )

    assert executions == [1]
    assert [comp["location"] for comp in result.data["comps"]] == list(
        comp_locations
    )


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,locations,rows,count,errors",
    _COMPARE_BINDING_FAILURES,
    ids=[case[0] for case in _COMPARE_BINDING_FAILURES],
)
async def test_compare_markets_result_is_exact_pairwise_bound_multiset(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    locations,
    rows,
    count,
    errors,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    with pytest.raises(ToolError) as caught:
        await _call_compare_markets(
            registry,
            audit,
            identity,
            locations=locations,
            payload=_compare_payload(rows, count=count, errors=errors),
            executions=executions,
        )

    assert executions == [1]
    _assert_post_result_denial(audit, identity, "compare_markets", caught)


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
async def test_compare_market_city_zip_cannot_bind_to_incompatible_county_geo(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """Pairwise binding intersects every city, ZIP, and county carrier."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("PR",)}
    )
    executions = [0]

    with pytest.raises(ToolError) as caught:
        await _call_compare_markets(
            registry,
            audit,
            identity,
            locations=("Adjuntas, PR 00601",),
            payload=_compare_payload(
                (("Adjuntas, PR 00601", "utuado-county"),)
            ),
            executions=executions,
        )

    assert executions == [1]
    _assert_post_result_denial(audit, identity, "compare_markets", caught)


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case_id,locations,rows",
    _COMPARE_BINDING_CONTROLS,
    ids=[case[0] for case in _COMPARE_BINDING_CONTROLS],
)
async def test_compare_markets_accepts_exact_or_reordered_normalized_multiset(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case_id,
    locations,
    rows,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _compare_payload(rows)
    executions = [0]

    result = await _call_compare_markets(
        registry,
        audit,
        identity,
        locations=locations,
        payload=payload,
        executions=executions,
    )

    assert executions == [1]
    assert result.data == payload
