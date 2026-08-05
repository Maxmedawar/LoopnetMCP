"""Permanent protocol regressions found during OAuth release-correctness review.

Every test calls a real FastMCP tool through ``Client`` and the production
access middleware.  The fixtures are production-shaped, but contain no real
customer or provider data.
"""

import json
from collections.abc import Callable
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from cre_mcp.access.capabilities import CAPABILITIES
from cre_mcp.access.engine import RESULT_TERRITORY_DENIAL
from cre_mcp.access.middleware import install_access
from cre_mcp.arbitrage.economics import master_lease_arbitrage
from cre_mcp.compliance import tools as compliance_tools
from cre_mcp.leasing import tools as leasing_tools
from cre_mcp.models import (
    Deal,
    DealScore,
    GeoLevel,
    GeoRef,
    Listing,
    MarketOverview,
    MarketPack,
    OwnerRecord,
    ParcelRecord,
    PropertyDetail,
    PropertySummary,
    RentComparable,
    RentComps,
    RubricResult,
    SaleComp,
    UnderwritingResult,
    ValueEstimate,
)
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import ContactInfo
from cre_mcp.models.listings import AggregatedSearchResult, SearchResult
from cre_mcp.prospect import tools as prospect_tools
from cre_mcp.relations import tools as relation_tools
from cre_mcp.tax import after_tax as after_tax_module
from cre_mcp.taxecon import tools as taxecon_tools
from cre_mcp.tools import (
    deal_tools,
    execution_tools,
    listing_tools,
    market_tools,
    ops_tools,
    pipeline_tools,
)


_ROUTE_ZIP_ALIAS_ESCAPES = (
    ("zip", {"zip": "33101"}),
    ("postal-code", {"postal_code": "33101"}),
    ("conflicting-aliases", {"zip": "33101", "postal_code": "10001"}),
)

_PERMIT_ROW_REQUEST_ESCAPES = (
    ("unknown-field", {"totally_unknown_provider_field": "Miami, FL 33101"}),
    (
        "outer-attributes-conflict",
        {
            "attributes": {
                "address": "90 Ocean Drive, Miami, FL 33101",
                "city": "Miami",
                "state": "FL",
                "zip_code": "33101",
                "permit_date": "2020-01-01",
            }
        },
    ),
    ("unicode-address", {"address": "１００ Main Street, Dallas, TX 75201"}),
    ("unicode-zip", {"zip_code": "７５２０１"}),
    ("location-string", {"location": "Miami, FL 33101"}),
    (
        "location-object",
        {
            "location": {
                "type": "Point",
                "coordinates": [-80.1918, 25.7617],
                "human_address": "Miami, FL 33101",
            }
        },
    ),
    (
        "geolocation-object",
        {
            "geolocation": {
                "type": "Point",
                "coordinates": [-80.1918, 25.7617],
                "human_address": "Miami, FL 33101",
            }
        },
    ),
    ("location1-string", {"location1": "Miami, FL 33101"}),
    ("latitude-longitude", {"latitude": 25.7617, "longitude": -80.1918}),
    ("xy-coordinates", {"xcoordinate": -80.1918, "ycoordinate": 25.7617}),
    ("census-tract", {"census_tract": "12086000100"}),
    ("community-area", {"community_area": "Miami"}),
    ("ward", {"ward": "Miami"}),
    (
        "attributes-spatial-carrier",
        {
            "attributes": {
                "location": {
                    "type": "Point",
                    "coordinates": [-80.1918, 25.7617],
                    "human_address": "Miami, FL 33101",
                }
            }
        },
    ),
)


def _without_provider_raw(value: Any) -> Any:
    """Mirror the hosted source-rights contract for release-shape assertions."""
    if isinstance(value, dict):
        return {
            key: _without_provider_raw(item)
            for key, item in value.items()
            if key != "raw"
        }
    if isinstance(value, list):
        return [_without_provider_raw(item) for item in value]
    return value

_UNPERMITTED_UNSUPPORTED_ENVELOPES = (
    "single-mapping",
    "results-envelope",
    "uppercase-permits-envelope",
)

_LIMITED_CONTEXT_FIXTURES = ("ctx_loc", "ctx_jv")
_RESULT_COLLECTIONS = ("properties", "listings")

_NATIONWIDE_CITY_ZIP_CONTROLS = (
    ("Houston", "TX", "77002"),
    ("San Francisco", "CA", "94105"),
    ("Chicago", "IL", "60601"),
    ("Seattle", "WA", "98101"),
    ("New York", "NY", "10001"),
    ("Philadelphia", "PA", "19103"),
)

_COMMON_CITY_SPELLING_CONTROLS = (
    ("O'Fallon", "MO", "63366"),
    ("Wilkes-Barre", "PA", "18701"),
    ("Mt Kisco", "NY", "10549"),
    ("Winston Salem", "NC", "27101"),
    ("Añasco", "PR", "00610"),
    ("Peñuelas", "PR", "00624"),
    ("Cañon City", "CO", "81212"),
    ("Doña Ana", "NM", "88032"),
    ("Washington", "D.C.", "20001"),
)

_INVALID_OR_OTHER_JURISDICTION_ZIPS = (
    ("unassigned-texas-prefix", "TX", "Fixture City", "75000"),
    ("unassigned-alaska-prefix", "AK", "Fixture City", "99999"),
    ("virgin-islands-not-puerto-rico", "PR", "St Thomas", "00802"),
    ("american-samoa-not-hawaii", "HI", "Pago Pago", "96799"),
    ("military-aa-not-florida", "FL", "APO", "34002"),
)

_SEMANTIC_UNKNOWN_LOCATION_CASES = (
    ("N/A", "Dallas"),
    ("Unknown", "Dallas"),
    ("100 Main Street, Dallas, TX", "N/A"),
    ("100 Main Street, Dallas, TX", "Unknown"),
    ("N/A", "Unknown"),
)

_MULTI_LOCATION_CITY_VALUES = (
    "Miami, FL / Dallas",
    "Miami FL; Dallas",
    "Miami, FL + Dallas",
    "Miami FL and Dallas",
)

_PROSE_LOCATION_CONNECTOR_ESCAPES = (
    "200 Ocean Dr Miami FL to 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL then 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL followed by 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL versus 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL vs 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL near 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL plus 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL aka 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL formerly 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL or 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL before 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL after 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL from 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL with 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL secondary 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL mailing address 100 Main Street Dallas TX 75201",
    "200 Ocean Dr Miami FL property address 100 Main Street Dallas TX 75201",
)

_MULTIWORD_STATE_WHITESPACE_ADDRESSES = (
    "90 Ocean Drive, Miami North   Carolina USA",
    "90 Ocean Drive, Miami New\tYork USA",
    "90 Ocean Drive, Miami South  Dakota USA",
    "90 Ocean Drive, Miami District  of Columbia USA",
)

_PROPERTY_BEARING_EGRESS_TOOLS = (
    "get_property_details",
    "get_market_overview",
    "find_deals",
    "find_distressed",
    "analyze_deal",
    "get_comps",
    "owner_lookup",
    "get_rent_comparables",
    "check_alerts",
    "list_deals",
    "list_pipeline",
    "list_searches",
    "find_control_opportunities",
    "market_intel",
    "compare_markets",
    "dedupe_listings",
    "portfolio_owner_scan",
    "route_lead",
    "find_arbitrage_opportunities",
)

_PROPERTY_BEARING_EGRESS_CONTEXTS = tuple(
    (context_fixture, tool_name)
    for tool_name in _PROPERTY_BEARING_EGRESS_TOOLS
    for context_fixture in (
        ("ctx_jv",)
        if tool_name in {"list_deals", "list_pipeline"}
        else _LIMITED_CONTEXT_FIXTURES
    )
)

_DEAL_NESTED_LOCATION_PATHS = (
    "sale_comps[].address",
    "market_pack.geo",
    "parcel.site_address",
    "owner.parcels[].site_address",
    "rent_comps.geo",
    "rent_comps.comps[].location",
)

_DEAL_EGRESS_TOOLS = (
    "find_deals",
    "find_distressed",
    "analyze_deal",
    "check_alerts",
)

_RESTRICTED_OPEN_ENVELOPE_TOOLS = (
    "find_contact",
    "after_tax_returns",
    "audit_assessor_record",
    "challenge_appraisal",
    "stalled_project_signals",
)

_RESTRICTED_STRUCTURED_REQUEST_TOOLS = (
    "audit_assessor_record",
    "challenge_appraisal",
    "stalled_project_signals",
)

_REQUEST_PROPERTY_RECORD_TOOLS = (
    "dedupe_listings",
    "portfolio_owner_scan",
    "route_lead",
    "find_arbitrage_opportunities",
    "find_control_opportunities",
)

_BARE_OR_NON_STREET_ADDRESSES = (
    "Miami",
    "Houston",
    "Narnia",
    "Dallas",
    "Miami USA",
    "0",
    "90",
    "123",
    "Suite 33101, USA",
)

_OBFUSCATED_OUT_OF_SCOPE_ADDRESS_TAILS = (
    "100 Main Street, Miami F.L.",
    "100 Main Street, Miami F L",
    "100 Main Street, Miami F-L",
    "100 Main Street, Miami F/L",
    "100 Main Street, Miami F_L",
    "100 Main Street, Miami F•L",
)

_INCONSISTENT_GEO_REFS = (
    (
        "county-state-prefix",
        {
            "level": "county",
            "state_fips": "48",
            "county_fips": "12086",
            "cbsa": None,
            "zip": None,
            "tract": None,
            "name": "Harris County, TX",
        },
    ),
    (
        "county-name-fips-mismatch",
        {
            "level": "county",
            "state_fips": "48",
            "county_fips": "48113",
            "cbsa": None,
            "zip": None,
            "tract": None,
            "name": "Miami-Dade County",
        },
    ),
    (
        "tract-county-prefix",
        {
            "level": "tract",
            "state_fips": "48",
            "county_fips": "48113",
            "cbsa": None,
            "zip": None,
            "tract": "12086000100",
            "name": "Dallas, TX",
        },
    ),
    (
        "cross-state-cbsa",
        {
            "level": "cbsa",
            "state_fips": "48",
            "county_fips": None,
            "cbsa": "19100",
            "zip": None,
            "tract": None,
            "name": "Dallas-Fort Worth-Arlington, TX",
        },
    ),
)


def _property_values(state: str) -> tuple[str, str, str]:
    if state == "TX":
        return "Dallas", "75201", "100 Main Street, Dallas, TX 75201"
    return "Miami", "33101", "90 Ocean Drive, Miami, FL 33101"


def _property(
    *,
    state: str = "TX",
    city: str | None = None,
    zip_code: str | None = None,
    address: str | None = None,
) -> PropertySummary:
    default_city, default_zip, default_address = _property_values(state)
    return PropertySummary(
        name="Protocol Fixture Property",
        address=default_address if address is None else address,
        city=default_city if city is None else city,
        state=state,
        zip_code=default_zip if zip_code is None else zip_code,
        url="https://example.test/property",
    )


def _listing(
    *,
    state: str = "TX",
    city: str | None = None,
    zip_code: str | None = None,
    address: str | None = None,
) -> Listing:
    default_city, default_zip, default_address = _property_values(state)
    return Listing(
        source="fixture",
        source_id=f"fixture-{state.lower()}",
        name="Protocol Fixture Listing",
        address=default_address if address is None else address,
        city=default_city if city is None else city,
        state=state,
        zip_code=default_zip if zip_code is None else zip_code,
        url="https://example.test/listing",
    )


def _geo(state: str) -> GeoRef:
    city, zip_code, _address = _property_values(state)
    return GeoRef(
        level=GeoLevel.ZIP,
        state_fips="48" if state == "TX" else "12",
        zip=zip_code,
        name=f"{city}, {state}",
    )


def _state_geo(state: str) -> GeoRef:
    """Return the exact state-level GeoRef used by state request controls."""

    return GeoRef(
        level=GeoLevel.STATE,
        state_fips="48" if state == "TX" else "12",
        name=state,
    )


def _compact_deal_row(state: str, *, include_zip: bool = True) -> dict[str, Any]:
    city, zip_code, address = _property_values(state)
    row: dict[str, Any] = {
        "deal_id": f"fixture:{state.lower()}",
        "source": "fixture",
        "source_id": f"fixture-{state.lower()}",
        "name": "Protocol Fixture Deal",
        "address": address,
        "city": city,
        "state": state,
        "price_usd": 1_000_000.0,
        "stage": "lead",
        "score": None,
        "grade": None,
        "strategy": None,
        "last_note": None,
        "created_at": "2026-08-01T00:00:00+00:00",
        "updated_at": "2026-08-01T00:00:00+00:00",
        "dd_total": 0,
        "dd_complete": 0,
    }
    if include_zip:
        row["zip_code"] = zip_code
    return row


def _deal_with_nested_location(path: str, state: str) -> Deal:
    _city, _zip_code, address = _property_values(state)
    kwargs: dict[str, Any] = {"listing": _listing(state="TX")}
    if path == "sale_comps[].address":
        kwargs["sale_comps"] = [
            SaleComp(
                source="Synthetic County",
                county_fips="12086" if state == "FL" else "48113",
                parcel_id="nested-comp",
                address=address,
                sale_price=900_000,
            )
        ]
    elif path == "market_pack.geo":
        kwargs["market_pack"] = MarketPack(geo=_geo(state))
    elif path == "parcel.site_address":
        kwargs["parcel"] = ParcelRecord(site_address=address)
    elif path == "owner.parcels[].site_address":
        kwargs["owner"] = OwnerRecord(
            name="Protocol Fixture Owner",
            normalized_name="PROTOCOL FIXTURE OWNER",
            entity_type="company",
            parcels=[ParcelRecord(site_address=address)],
        )
    elif path == "rent_comps.geo":
        kwargs["rent_comps"] = RentComps(geo=_geo(state))
    elif path == "rent_comps.comps[].location":
        kwargs["rent_comps"] = RentComps(
            geo=_geo("TX"),
            comps=[
                RentComparable(
                    source="Synthetic Rent",
                    rent=2_000,
                    location=f"{address}",
                )
            ],
        )
    else:
        raise AssertionError(f"unknown nested deal path: {path}")
    return Deal(**kwargs)


def _deal_egress_payload(tool_name: str, deal: Deal) -> dict[str, Any]:
    serialized = deal.model_dump(mode="json")
    if tool_name in {"find_deals", "find_distressed"}:
        return {
            "query_location": "TX",
            "strategy": "distressed" if tool_name == "find_distressed" else None,
            "deals": [serialized],
            "total_scored": 1,
            "returned": 1,
            "errors": {},
            "per_source_counts": {"fixture": 1},
            "deduped": 0,
            "score_calibrated": False,
            "score_calibration_disclaimer": "Protocol fixture is uncalibrated.",
        }
    if tool_name == "analyze_deal":
        return {
            **serialized,
            "score_calibrated": False,
            "score_calibration_disclaimer": "Protocol fixture is uncalibrated.",
        }
    if tool_name == "check_alerts":
        return {
            "searches_checked": 1,
            "new_count": 1,
            "new_deals": [
                {
                    **serialized,
                    "saved_search_id": 1,
                    "saved_search_name": "Protocol Fixture Search",
                }
            ],
            "results": [
                {
                    "search_id": 1,
                    "name": "Protocol Fixture Search",
                    "new_count": 1,
                    "scanned": 1,
                    "source_errors": {},
                }
            ],
            "errors": {},
            "alert_mode": "pull_on_demand",
            "hosting_note": "Synthetic protocol fixture.",
        }
    raise AssertionError(f"unknown deal egress tool: {tool_name}")


def _search_payload(
    collection: str,
    *,
    query_location: str,
    state: str,
    city: str,
    zip_code: str | None,
    address: str,
) -> dict[str, Any]:
    if collection == "properties":
        return SearchResult(
            query_location=query_location,
            properties=[
                _property(
                    state=state,
                    city=city,
                    zip_code=zip_code,
                    address=address,
                )
            ],
        ).model_dump(mode="json")
    return AggregatedSearchResult(
        query_location=query_location,
        listings=[
            _listing(
                state=state,
                city=city,
                zip_code=zip_code,
                address=address,
            )
        ],
    ).model_dump(mode="json")


async def _call_search(
    registry,
    audit,
    identity,
    result: Any | Callable[[], Any],
    *,
    location: str,
):
    app = FastMCP(name="territory-release-search-regression")

    @app.tool
    async def search_properties(location: str):
        del location
        return result() if callable(result) else result

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            return await client.call_tool("search_properties", {"location": location})
    finally:
        uninstall()


async def _call_owner_lookup(
    registry,
    audit,
    identity,
    *,
    address: str,
    county: str | None,
    executions: list[int],
):
    app = FastMCP(name="territory-release-owner-regression")

    @app.tool
    async def owner_lookup(
        address: str | None = None,
        apn: str | None = None,
        county: str | None = None,
    ):
        del apn, county
        executions[0] += 1
        return OwnerRecord(
            name="Protocol Fixture Owner",
            normalized_name="PROTOCOL FIXTURE OWNER",
            entity_type="company",
            parcels=[ParcelRecord(site_address=address)],
        ).model_dump(mode="json")

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            args: dict[str, Any] = {"address": address}
            if county is not None:
                args["county"] = county
            return await client.call_tool("owner_lookup", args)
    finally:
        uninstall()


def _property_egress_payload(tool_name: str, state: str) -> dict[str, Any]:
    city, zip_code, address = _property_values(state)
    listing = _listing(state=state)
    summary = _property(state=state)

    if tool_name == "get_property_details":
        return PropertyDetail(
            name="Protocol Fixture Detail",
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            url="https://example.test/detail",
        ).model_dump(mode="json")
    if tool_name == "get_market_overview":
        return MarketOverview(
            location="TX",
            total_listings=1,
            sample_listings=[summary],
        ).model_dump(mode="json")

    deal = Deal(listing=listing)
    if tool_name in {"find_deals", "find_distressed"}:
        return {
            "query_location": "TX",
            "strategy": "distressed" if tool_name == "find_distressed" else None,
            "deals": [deal.model_dump(mode="json")],
            "total_scored": 1,
            "returned": 1,
            "errors": {},
            "per_source_counts": {"fixture": 1},
            "deduped": 0,
            "score_calibrated": False,
            "score_calibration_disclaimer": "Protocol fixture is uncalibrated.",
        }
    if tool_name == "analyze_deal":
        payload = deal.model_dump(mode="json")
        payload.update(
            {
                "score_calibrated": False,
                "score_calibration_disclaimer": "Protocol fixture is uncalibrated.",
            }
        )
        return payload
    if tool_name == "get_comps":
        estimate = ValueEstimate(
            value=1_000_000,
            low=900_000,
            mid=1_000_000,
            high=1_100_000,
            method="county_comps",
            n_comps=1,
            confidence=0.75,
            error_band=0.10,
            source="Synthetic protocol fixture.",
        )
        comp = SaleComp(
            source="Synthetic County",
            county_fips="12086" if state == "FL" else "48113",
            parcel_id="fixture-comp",
            address=address,
            sale_price=900_000,
        )
        return {
            "subject": {
                "source": listing.source,
                "source_id": listing.source_id,
                "address": address,
                "city": city,
                "state": state,
                "zip_code": zip_code,
                "asking_price": listing.price_usd,
            },
            "value_estimate": estimate.model_dump(mode="json"),
            "value_provenance": {
                "method": estimate.method,
                "confidence": estimate.confidence,
                "n_comps": estimate.n_comps,
            },
            "comps": [comp.model_dump(mode="json")],
            "explanation": "Synthetic protocol fixture.",
            "coverage_note": "Synthetic protocol fixture.",
        }
    if tool_name == "owner_lookup":
        return OwnerRecord(
            name="Protocol Fixture Owner",
            normalized_name="PROTOCOL FIXTURE OWNER",
            entity_type="company",
            parcels=[ParcelRecord(site_address=address)],
        ).model_dump(mode="json")
    if tool_name == "get_rent_comparables":
        return RentComps(
            geo=_state_geo(state),
            comps=[
                RentComparable(
                    source="Synthetic Rent",
                    rent=2_000,
                    location=address,
                )
            ],
        ).model_dump(mode="json")
    if tool_name == "check_alerts":
        return _deal_egress_payload(tool_name, Deal(listing=listing))
    if tool_name == "list_deals":
        return {"deals": [_compact_deal_row(state)], "count": 1}
    if tool_name == "list_pipeline":
        row = {**_compact_deal_row(state), "url": listing.url, "notes": []}
        return {
            "stage": None,
            "deals": [row],
            "by_stage": {"lead": [row]},
            "count": 1,
        }
    if tool_name == "list_searches":
        return {
            "searches": [
                {
                    "id": 1,
                    "name": "Protocol Fixture Search",
                    "query": {
                        "location": f"{city}, {state}",
                        "strategy": None,
                        "property_type": None,
                        "price_min": None,
                        "price_max": None,
                        "size_min": None,
                        "size_max": None,
                        "sources": ["loopnet"],
                    },
                    "min_score": None,
                    "created_at": "2026-08-01T00:00:00+00:00",
                    "seen_count": 0,
                }
            ],
            "count": 1,
            "alert_mode": "pull_on_demand",
            "hosting_note": "Synthetic protocol fixture.",
        }
    if tool_name == "find_control_opportunities":
        return {
            "count": 1,
            "opportunities": [
                {
                    "listing": listing.model_dump(mode="json"),
                    "vacancy": {"is_vacant_candidate": False, "confidence": 0.0},
                    "tenant_matches": [],
                    "spread": None,
                    "control_score": 0.0,
                    "score_components": {
                        "vacancy": 0.0,
                        "tenant_fit": 0.0,
                        "spread": 0.0,
                    },
                    "rank": 1,
                }
            ],
            "methodology": "Synthetic protocol fixture.",
        }
    if tool_name == "market_intel":
        payload = MarketPack(geo=_state_geo(state)).model_dump(mode="json")
        payload.update(
            {
                "market_score": 0.0,
                "score_confidence": 0.0,
                "coverage_summary": {
                    "covered": 0,
                    "total": 0,
                    "ratio": 0.0,
                    "missing": [],
                },
            }
        )
        return payload
    if tool_name == "compare_markets":
        market = _property_egress_payload("market_intel", state)
        return {
            "markets": [{"location": state, **market, "rank": 1}],
            "errors": {},
            "count": 1,
        }
    if tool_name == "dedupe_listings":
        record = {
            "source": "fixture",
            "source_id": f"fixture-{state.lower()}",
            "address": address,
            "city": city,
            "state": state,
            "zip": zip_code,
            "price": None,
            "seen_date": None,
        }
        return {
            "groups": [
                {
                    "canonical": record,
                    "members": [record],
                    "tier": "unique",
                    "match_basis": None,
                    "price_history": [],
                }
            ],
            "candidate_matches": [],
            "fuzzy_threshold": 0.8,
            "honesty": "Synthetic protocol fixture.",
        }
    if tool_name == "portfolio_owner_scan":
        return {
            "methodology": {
                "label": "Synthetic protocol fixture.",
                "minimum_properties": 1,
                "type_outlier_convention": "Synthetic convention.",
                "size_outlier_convention": "Synthetic convention.",
            },
            "record_count": 1,
            "owner_group_count": 1,
            "owners": [
                {
                    "normalized_owner_name": "fixture owner",
                    "owner_name_variants": ["Fixture Owner LLC"],
                    "property_count": 1,
                    "signal_label": "HEURISTIC PORTFOLIO GROUP",
                    "grouping_basis": "Synthetic protocol fixture.",
                    "profile": {
                        "use_counts": {"retail": 1},
                        "modal_use_for_outlier_test": None,
                        "median_sf": 10000.0,
                        "usable_size_count": 1,
                        "size_ratio_outlier_threshold": 3.0,
                    },
                    "dispersion_note": "Synthetic protocol fixture.",
                    "noncore_outlier_count": 0,
                    "properties": [
                        {
                            "record_index": 0,
                            "address": address,
                            "parcel_id": "fixture-parcel",
                            "property_id": "fixture-property",
                            "use": "retail",
                            "sf": 10000,
                            "size_to_median_ratio": 1.0,
                            "noncore_outlier_flag": False,
                            "signal_label": "HEURISTIC SCREEN",
                            "basis": ["Synthetic protocol fixture."],
                            "inference_caution": "Synthetic protocol fixture.",
                            "unrecognized_fields": [],
                        }
                    ],
                    "seller_intent_caution": "Synthetic protocol fixture.",
                }
            ],
            "skipped_records": [],
            "unrecognized_input_fields": [],
        }
    if tool_name == "route_lead":
        return {
            "listing": {
                "id": f"fixture-{state.lower()}",
                "recorded_fields": [
                    "address",
                    "city",
                    "source_id",
                    "state",
                    "zip_code",
                ],
                "address": address,
                "city": city,
                "state": state,
                "zip_code": zip_code,
            },
            "recommended": None,
            "routes": [],
            "candidate_count": 0,
            "team_members_reviewed": 1,
            "message": "no recorded mandate-matched candidates",
            "honesty": "Synthetic protocol fixture.",
        }
    if tool_name == "find_arbitrage_opportunities":
        economics = master_lease_arbitrage(
            master_rent_annual=100000.0,
            building_sqft=10000.0,
            sublease_rent_psf=20.0,
        )
        summary = {
            "input_count": 1,
            "positive_count": 1,
            "filtered_non_positive_count": 0,
            "filtered_count": 0,
            "skipped_missing_or_invalid_count": 0,
            "skipped_spaces": [],
        }
        return {
            **summary,
            "count": 1,
            "opportunities": [
                {
                    "id": f"fixture-{state.lower()}",
                    "address": address,
                    "city": city,
                    "state": state,
                    "zip_code": zip_code,
                    "building_sqft": 10000,
                    "master_rent_annual": 100000.0,
                    "asking_rent_psf": None,
                    "achievable_sublease_psf": 20.0,
                    "sublease_occupancy": None,
                    "ti_psf": None,
                    "free_rent_months": None,
                    "mgmt_pct": None,
                    "other_annual_costs": None,
                    "term_years": None,
                    "your_rent_escalation_pct": None,
                    "sublease_escalation_pct": None,
                    "personal_guarantee": None,
                    "economics": economics,
                    "opportunity_label": "positive_spread_candidate",
                    "risk_label": "underwrite_further",
                    "caveat": "Synthetic protocol fixture.",
                    "rank": 1,
                    "filtered_count": 0,
                    "filtered_non_positive_count": 0,
                    "skipped_missing_or_invalid_count": 0,
                    "screening_summary": summary,
                }
            ],
        }
    raise AssertionError(f"unknown tool fixture: {tool_name}")


async def _call_property_egress_tool(
    registry,
    audit,
    identity,
    *,
    tool_name: str,
    payload: dict[str, Any],
    request_location: str = "TX",
):
    app = FastMCP(name=f"territory-release-{tool_name}")

    if tool_name == "get_property_details":

        async def fixture(url_or_id: str, source: str | None = None):
            del url_or_id, source
            return payload

        args = {"url_or_id": "fixture:property"}
    elif tool_name == "get_market_overview":

        async def fixture(location: str, property_type: str | None = None):
            del location, property_type
            return payload

        args = {"location": request_location}
    elif tool_name in {"find_deals", "find_distressed"}:

        async def fixture(location: str):
            del location
            return payload

        args = {"location": request_location}
    elif tool_name in {"analyze_deal", "get_comps"}:

        async def fixture(url_or_id: str):
            del url_or_id
            return payload

        args = {"url_or_id": "fixture:property"}
    elif tool_name == "owner_lookup":

        async def fixture(
            address: str | None = None,
            apn: str | None = None,
            county: str | None = None,
        ):
            del address, apn, county
            return payload

        args = {
            "address": "100 Main Street, Dallas, TX 75201",
        }
    elif tool_name == "get_rent_comparables":

        async def fixture(
            location: str,
            bedrooms: int | None = None,
            property_type: str | None = None,
        ):
            del location, bedrooms, property_type
            return payload

        args = {"location": request_location}
    elif tool_name == "check_alerts":

        async def fixture(search_id: int | None = None):
            del search_id
            return payload

        args = {}
    elif tool_name == "list_deals":

        async def fixture():
            return payload

        args = {}
    elif tool_name == "list_pipeline":

        async def fixture(stage: str | None = None):
            del stage
            return payload

        args = {}
    elif tool_name == "list_searches":

        async def fixture():
            return payload

        args = {}
    elif tool_name == "find_control_opportunities":

        async def fixture(listings: list[dict[str, Any]]):
            del listings
            return payload

        args = {"listings": [_listing(state="TX").model_dump(mode="json")]}
    elif tool_name == "market_intel":

        async def fixture(location: str):
            del location
            return payload

        args = {"location": request_location}
    elif tool_name == "compare_markets":

        async def fixture(locations: list[str]):
            del locations
            return payload

        args = {"locations": [request_location]}
    elif tool_name == "dedupe_listings":

        async def fixture(listings: list[dict[str, Any]]):
            del listings
            return payload

        args = {
            "listings": [
                {
                    "source": "fixture",
                    "source_id": "request-tx",
                    "address": "100 Main Street, Dallas, TX 75201",
                    "city": "Dallas",
                    "state": "TX",
                    "zip": "75201",
                    "price": None,
                    "seen_date": None,
                }
            ]
        }
    elif tool_name == "portfolio_owner_scan":

        async def fixture(
            records: list[dict[str, Any]] | None = None,
            min_properties: int = 2,
        ):
            del records, min_properties
            return payload

        args = {
            "records": [
                {
                    "owner_name": "Fixture Owner LLC",
                    "address": "100 Main Street, Dallas, TX 75201",
                }
            ],
            "min_properties": 1,
        }
    elif tool_name == "route_lead":

        async def fixture(
            listing: dict[str, Any],
            team: list[dict[str, Any]],
        ):
            del listing, team
            return payload

        args = {
            "listing": {
                "source_id": "request-tx",
                "address": "100 Main Street, Dallas, TX 75201",
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75201",
            },
            "team": [{"name": "Fixture", "mandates": []}],
        }
    elif tool_name == "find_arbitrage_opportunities":

        async def fixture(
            spaces: list[dict[str, Any]],
            achievable_sublease_psf: float | None = None,
        ):
            del spaces, achievable_sublease_psf
            return payload

        args = {
            "spaces": [
                {
                    "id": "request-tx",
                    "address": "100 Main Street, Dallas, TX 75201",
                    "city": "Dallas",
                    "state": "TX",
                    "zip_code": "75201",
                    "building_sqft": 10000,
                    "master_rent_annual": 100000,
                    "achievable_sublease_psf": 20,
                }
            ]
        }
    else:
        raise AssertionError(f"unknown tool fixture: {tool_name}")

    app.tool(name=tool_name)(fixture)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            return await client.call_tool(tool_name, args)
    finally:
        uninstall()


def test_release_regression_matrix_counts_are_permanent():
    assert len(_NATIONWIDE_CITY_ZIP_CONTROLS) == 6
    assert (
        len(_LIMITED_CONTEXT_FIXTURES)
        * len(_RESULT_COLLECTIONS)
        * 3
        * len(_NATIONWIDE_CITY_ZIP_CONTROLS)
        == 72
    )
    assert len(_INVALID_OR_OTHER_JURISDICTION_ZIPS) == 5
    assert len(_SEMANTIC_UNKNOWN_LOCATION_CASES) == 5
    assert len(_MULTI_LOCATION_CITY_VALUES) == 4
    assert len(_PROSE_LOCATION_CONNECTOR_ESCAPES) == 17
    assert len(_MULTIWORD_STATE_WHITESPACE_ADDRESSES) == 4
    assert len(_COMMON_CITY_SPELLING_CONTROLS) == 9
    assert len(_PROPERTY_BEARING_EGRESS_TOOLS) == 19
    assert len(_PROPERTY_BEARING_EGRESS_CONTEXTS) == 36
    assert len(_DEAL_NESTED_LOCATION_PATHS) == 6
    assert len(_DEAL_EGRESS_TOOLS) == 4
    assert len(_RESTRICTED_OPEN_ENVELOPE_TOOLS) == 5
    assert len(_RESTRICTED_STRUCTURED_REQUEST_TOOLS) == 3
    assert len(_REQUEST_PROPERTY_RECORD_TOOLS) == 5
    assert len(_BARE_OR_NON_STREET_ADDRESSES) == 9
    assert len(_OBFUSCATED_OUT_OF_SCOPE_ADDRESS_TAILS) == 6
    assert len(_INCONSISTENT_GEO_REFS) == 4


def test_profile_capability_counts_are_release_locked():
    """Prevent a fail-closed repair from silently removing product access."""

    expected = {
        "local_scout": 103,
        "national_scout": 115,
        "full_operator": 274,
        "jv_partner": 170,
    }
    observed = {
        profile: sum(
            profile in capability.allowed_profiles
            for capability in CAPABILITIES.values()
        )
        for profile in expected
    }

    assert len(CAPABILITIES) == 274
    assert observed == expected


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("grant_kind", ("state", "city", "zip"))
@pytest.mark.parametrize(
    "city,state,zip_code",
    _NATIONWIDE_CITY_ZIP_CONTROLS,
    ids=[case[0].lower().replace(" ", "-") for case in _NATIONWIDE_CITY_ZIP_CONTROLS],
)
async def test_assigned_city_zip_pairs_release_for_state_city_and_zip_grants(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    grant_kind,
    city,
    state,
    zip_code,
):
    territory = {
        "state": state,
        "city": f"{city}, {state}",
        "zip": zip_code,
    }[grant_kind]
    requested = f"{city}, {state} {zip_code}"
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    payload = _search_payload(
        collection,
        query_location=requested,
        state=state,
        city=city,
        zip_code=zip_code,
        address=f"100 Main Street, {city}, {state} {zip_code}",
    )

    result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location=requested,
    )

    assert result.data[collection][0]["zip_code"] == zip_code


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize(
    "city,state,zip_code",
    _COMMON_CITY_SPELLING_CONTROLS,
    ids=[
        case[0].lower().replace(" ", "-")
        for case in _COMMON_CITY_SPELLING_CONTROLS
    ],
)
async def test_common_city_spellings_release_for_state_grants(
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
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (state,)}
    )
    requested = f"{city}, {state} {zip_code}"
    payload = _search_payload(
        collection,
        query_location=requested,
        state=state,
        city=city,
        zip_code=zip_code,
        address=f"100 Main Street, {city}, {state} {zip_code}",
    )

    result = await _call_search(
        registry,
        audit,
        identity,
        payload,
        location=requested,
    )

    assert result.data[collection][0]["zip_code"] == zip_code


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_nonexistent_city_state_request_denies_before_execution(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    def result():
        executions[0] += 1
        return _search_payload(
            "properties",
            query_location="Honolulu, TX",
            state="TX",
            city="Honolulu",
            zip_code=None,
            address="100 Main Street",
        )

    with pytest.raises(ToolError, match="territor"):
        await _call_search(
            registry,
            audit,
            identity,
            result,
            location="Honolulu, TX",
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_find_deals_deep_refresh_is_validated_before_reranking(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    """A refreshed provider row cannot influence a restricted result first."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    initial_high = _listing(state="TX").model_copy(
        update={"source_id": "high", "price_usd": 100.0}
    )
    initial_low = _listing(state="TX").model_copy(
        update={"source_id": "low", "price_usd": 90.0}
    )
    refreshed_out_of_scope = _listing(state="FL").model_copy(
        update={"source_id": "high", "price_usd": 1.0}
    )

    class FixtureSource:
        detail_calls = 0

        async def get_detail(self, _ref):
            self.detail_calls += 1
            return refreshed_out_of_scope

    source = FixtureSource()

    class FixtureRegistry:
        async def search_all(self, query, *, sources):
            assert query.location == "TX"
            assert sources == ["fixture"]
            return AggregatedSearchResult(
                query_location="TX",
                listings=[initial_high, initial_low],
                per_source_counts={"fixture": 2},
            )

        def get_authorized(self, source_name):
            assert source_name == "fixture"
            return source

    async def no_market(_location):
        return None, None

    value_calls = [0]

    async def no_value(*_args, **_kwargs):
        value_calls[0] += 1
        return [], None

    def ranked_deal(listing, *_args, **_kwargs):
        rank_value = float(listing.price_usd or 0.0)
        ranked_score = DealScore(
            strategy="protocol_fixture",
            score=rank_value,
            grade="fixture",
            confidence=1.0,
            rubric_result=RubricResult(strategy="protocol_fixture"),
            explanation="Synthetic protocol ranking fixture.",
        )
        return Deal(
            listing=listing,
            scores=[ranked_score],
            best_strategy=ranked_score.strategy,
        )

    monkeypatch.setattr(deal_tools, "registry", FixtureRegistry())
    monkeypatch.setattr(deal_tools, "_market_for", no_market)
    monkeypatch.setattr(deal_tools, "_value_for", no_value)
    monkeypatch.setattr(deal_tools, "_deal", ranked_deal)

    app = FastMCP(name="find-deals-deep-refresh-territory-regression")
    app.tool()(deal_tools.find_deals)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool(
                    "find_deals",
                    {
                        "location": "TX",
                        "sources": ["fixture"],
                        "limit": 1,
                        "deep": True,
                    },
                )
    finally:
        uninstall()

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert source.detail_calls == 1
    assert value_calls == [0]


def test_expanded_release_regression_counts_are_permanent() -> None:
    assert len(_LIMITED_CONTEXT_FIXTURES) == 2
    assert len(_LIMITED_CONTEXT_FIXTURES) * len(_ROUTE_ZIP_ALIAS_ESCAPES) == 6
    assert (
        len(_LIMITED_CONTEXT_FIXTURES)
        * 2  # unpermitted and stalled permit consumers
        * len(_PERMIT_ROW_REQUEST_ESCAPES)
        == 56
    )
    assert (
        len(_LIMITED_CONTEXT_FIXTURES)
        * len(_UNPERMITTED_UNSUPPORTED_ENVELOPES)
        == 6
    )
    assert len(_LIMITED_CONTEXT_FIXTURES) * 8 == 16
    assert len(_LIMITED_CONTEXT_FIXTURES) * 3 == 6


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_core_listing_result_rejects_unreconciled_coordinates(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    listing = _listing().model_copy(update={"lat": 25.7617, "lon": -80.1918})
    payload = AggregatedSearchResult(
        query_location="TX",
        listings=[listing],
    ).model_dump(mode="json")

    with pytest.raises(ToolError) as caught:
        await _call_search(
            registry,
            audit,
            identity,
            payload,
            location="TX",
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_sale_comp_result_rejects_unreconciled_coordinates(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _property_egress_payload("get_comps", "TX")
    payload["comps"][0]["lat"] = 25.7617
    payload["comps"][0]["lon"] = -80.1918

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name="get_comps",
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_owner_parcel_result_rejects_unreconciled_coordinates(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    app = FastMCP(name="owner-coordinate-egress-regression")

    @app.tool(name="owner_lookup")
    async def fixture(
        address: str | None = None,
        apn: str | None = None,
        county: str | None = None,
    ):
        del apn, county
        return OwnerRecord(
            name="Protocol Fixture Owner",
            normalized_name="PROTOCOL FIXTURE OWNER",
            entity_type="company",
            parcels=[
                ParcelRecord(
                    site_address=address,
                    lat=25.7617,
                    lon=-80.1918,
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
                await client.call_tool(
                    "owner_lookup",
                    {
                        "address": "100 Main Street, Dallas, TX 75201",
                        "county": "Dallas County, TX",
                    },
                )
    finally:
        uninstall()

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


async def test_tenant_prospect_rejects_operational_coordinates_before_execution(
    request, registry, audit, identity
):
    identity["ctx"] = request.getfixturevalue("ctx_jv").model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name="tenant-prospect-coordinate-ingress-regression")

    @app.tool(name="tenant_prospect_list")
    async def fixture(
        site: dict[str, Any],
        existing_cotenancy: list[str | dict[str, Any]] | None = None,
    ):
        del site, existing_cotenancy
        executions[0] += 1
        return {}

    site = {
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
        "sf": 10_000,
        "lat": 25.7617,
        "lon": -80.1918,
    }
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool("tenant_prospect_list", {"site": site})
    finally:
        uninstall()

    assert executions == [0]


async def test_tenant_prospect_result_rejects_unreconciled_coordinates(
    request, registry, audit, identity
):
    identity["ctx"] = request.getfixturevalue("ctx_jv").model_copy(
        update={"territories": ("TX",)}
    )
    app = FastMCP(name="tenant-prospect-coordinate-egress-regression")

    @app.tool(name="tenant_prospect_list")
    async def fixture(
        site: dict[str, Any],
        existing_cotenancy: list[str | dict[str, Any]] | None = None,
    ):
        payload = leasing_tools.tenant_prospect_list(site, existing_cotenancy)
        payload["site_inputs"]["lat"] = 25.7617
        payload["site_inputs"]["lon"] = -80.1918
        return payload

    site = {
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
        "sf": 10_000,
    }
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool("tenant_prospect_list", {"site": site})
    finally:
        uninstall()

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "coordinate_fields",
    (
        {"lat": 25.7617, "lon": -80.1918},
        {"latitude": 28.5383, "longitude": -81.3792},
    ),
    ids=("lat-lon", "latitude-longitude"),
)
async def test_portfolio_scan_rejects_operational_coordinate_aliases(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    coordinate_fields,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name="portfolio-coordinate-ingress-regression")

    @app.tool(name="portfolio_owner_scan")
    async def fixture(
        records: list[dict[str, Any]] | None = None,
        min_properties: int = 2,
    ):
        del records, min_properties
        executions[0] += 1
        return {}

    app_uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(
                    "portfolio_owner_scan",
                    {
                        "records": [
                            {
                                "owner_name": "Protocol Fixture Owner",
                                "address": "100 Main Street, Dallas, TX 75201",
                                **coordinate_fields,
                            }
                        ],
                        "min_properties": 1,
                    },
                )
    finally:
        app_uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_control_listing_rejects_operational_coordinates_before_execution(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name="control-coordinate-ingress-regression")

    @app.tool(name="find_control_opportunities")
    async def fixture(listings: list[dict[str, Any]]):
        del listings
        executions[0] += 1
        return {}

    listing = _listing().model_copy(
        update={"lat": 25.7617, "lon": -80.1918}
    ).model_dump(mode="json")
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(
                    "find_control_opportunities", {"listings": [listing]}
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_control_listing_result_rejects_unreconciled_coordinates(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _property_egress_payload("find_control_opportunities", "TX")
    payload["opportunities"][0]["listing"]["lat"] = 25.7617
    payload["opportunities"][0]["listing"]["lon"] = -80.1918

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name="find_control_opportunities",
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "outer_fields",
    (
        {"address": "90 Ocean Drive, Miami, FL 33101"},
        {"state": "FL"},
        {
            "address": "100 Main Street, Dallas, TX 75201",
            "city": "Dallas",
            "state": "TX",
        },
    ),
    ids=("outer-address", "outer-state", "mixed-single-and-collection"),
)
async def test_stalled_permit_envelope_rejects_outer_property_fields(
    request, registry, audit, identity, context_fixture, outer_fields
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name="stalled-envelope-ambiguity-regression")

    @app.tool(name="stalled_project_signals")
    async def fixture(
        permits: dict[str, Any] | None = None,
        min_age_days: int | None = 365,
        as_of: str | None = None,
    ):
        del permits, min_age_days, as_of
        executions[0] += 1
        return {}

    payload = {**outer_fields, "permits": [_permit_request_row()]}
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(
                    "stalled_project_signals", {"permits": payload}
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "shape",
    ("sequence", "single", "permits", "results", "records", "features", "items", "data"),
)
async def test_stalled_permit_public_representations_release_when_in_scope(
    request, registry, audit, identity, context_fixture, shape
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    permit = _permit_request_row()
    if shape == "sequence":
        permits: Any = [permit]
    elif shape == "single":
        permits = permit
    else:
        permits = {shape: [permit]}
    app = FastMCP(name="stalled-public-representation-control")
    app.tool(name="stalled_project_signals")(
        prospect_tools.stalled_project_signals
    )
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool(
                "stalled_project_signals",
                {"permits": permits, "as_of": "2026-08-01"},
            )
    finally:
        uninstall()

    assert result.data["signal_count"] == 1
    assert result.data["signals"][0]["record"]["state"] == "TX"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("shape", ("flat", "parcel", "parcels"))
async def test_assessor_public_representations_release_when_in_scope(
    request, registry, audit, identity, context_fixture, shape
):
    """Every documented assessor input shape uses the production boundary."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    parcel = {
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
        "building_sqft": 12_000,
        "use_code": "office",
    }
    if shape == "flat":
        record: dict[str, Any] = parcel
    elif shape == "parcel":
        record = {"parcel": parcel}
    else:
        record = {"name": "Synthetic Owner LLC", "parcels": [parcel]}
    app = FastMCP(name="assessor-public-representation-control")
    app.tool(name="audit_assessor_record")(taxecon_tools.audit_assessor_record)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool(
                "audit_assessor_record",
                {
                    "record": record,
                    "stated_facts": {
                        "building_sqft": 10_000,
                        "use_code": "retail",
                    },
                },
            )
    finally:
        uninstall()

    assert result.data["subject_property"] == {
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "DALLAS",
        "state": "TX",
        "zip_code": "75201",
    }


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("shape", ("flat-plus-parcel", "parcel-plus-parcels"))
async def test_assessor_ambiguous_representations_fail_before_execution(
    request, registry, audit, identity, context_fixture, shape
):
    """Two competing assessor shapes cannot choose a convenient property."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    parcel = {
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
    }
    record = (
        {**parcel, "parcel": parcel}
        if shape == "flat-plus-parcel"
        else {"parcel": parcel, "parcels": [parcel]}
    )
    executions = [0]
    app = FastMCP(name="assessor-ambiguous-representation-regression")

    @app.tool(name="audit_assessor_record")
    async def fixture(record: dict[str, Any], stated_facts: dict[str, Any]):
        del record, stated_facts
        executions[0] += 1
        return {}

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(
                    "audit_assessor_record",
                    {"record": record, "stated_facts": {}},
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("tool_name", ("unpermitted_work_screen", "audit_assessor_record"))
async def test_empty_property_envelopes_fail_before_execution(
    request, registry, audit, identity, context_fixture, tool_name
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name=f"{tool_name}-empty-envelope-regression")
    if tool_name == "unpermitted_work_screen":

        async def fixture(
            observed_improvements: list[dict[str, Any]],
            permit_history: dict[str, Any],
        ):
            del observed_improvements, permit_history
            executions[0] += 1
            return {}

        args = {"observed_improvements": [], "permit_history": {"permits": []}}
    else:

        async def fixture(record: dict[str, Any], stated_facts: dict[str, Any]):
            del record, stated_facts
            executions[0] += 1
            return {}

        args = {"record": {"parcels": []}, "stated_facts": {}}
    app.tool(name=tool_name)(fixture)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(tool_name, args)
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "case_name,aliases",
    _ROUTE_ZIP_ALIAS_ESCAPES,
    ids=[case[0] for case in _ROUTE_ZIP_ALIAS_ESCAPES],
)
async def test_route_lead_rejects_conflicting_or_out_of_scope_zip_aliases(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    case_name,
    aliases,
):
    """Every accepted ZIP spelling participates in pre-execution territory."""
    del case_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name="route-zip-alias-regression")

    @app.tool(name="route_lead")
    async def fixture(listing: dict[str, Any], team: list[dict[str, Any]]):
        del listing, team
        executions[0] += 1
        return _property_egress_payload("route_lead", "TX")

    listing = {
        "source_id": "request-tx",
        "address": "100 Main Street, Dallas, TX",
        "city": "Dallas",
        "state": "TX",
        **aliases,
    }
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(
                    "route_lead",
                    {"listing": listing, "team": [{"name": "Fixture"}]},
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_owner_lookup_result_dto_rejects_mailing_location_egress(
    request, registry, audit, identity, context_fixture
):
    """The post-result gate distrusts a tool that forgets the projection."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    app = FastMCP(name="owner-mailing-egress-regression")

    @app.tool(name="owner_lookup")
    async def fixture(
        address: str | None = None,
        apn: str | None = None,
        county: str | None = None,
    ):
        del apn, county
        return OwnerRecord(
            name="Protocol Fixture Owner",
            normalized_name="PROTOCOL FIXTURE OWNER",
            entity_type="company",
            mailing_address="90 Ocean Drive, Miami, FL 33101",
            parcels=[
                ParcelRecord(
                    site_address=address,
                    owner_mailing_address="90 Ocean Drive, Miami, FL 33101",
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
                await client.call_tool(
                    "owner_lookup",
                    {
                        "address": "100 Main Street, Dallas, TX 75201",
                        "county": "Dallas County, TX",
                    },
                )
    finally:
        uninstall()

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "carrier",
    ("owner_mailing", "registered_agent", "principal"),
)
async def test_find_contact_result_dto_rejects_secondary_address_egress(
    request, registry, audit, identity, context_fixture, carrier
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    agent = {
        "name": "Protocol Agent",
        "address": None,
        "entity_name": "Protocol Fixture Owner LLC",
        "state": "TX",
        "status": "active",
        "principals": [],
        "source_url": "https://example.test/registry",
    }
    payload = {
        "subject_property": {
            "address": "100 Main Street, Dallas, TX 75201",
            "city": "Dallas",
            "state": "TX",
            "zip_code": "75201",
        },
        "broker": None,
        "owner_name": "Protocol Fixture Owner LLC",
        "owner_mailing": None,
        "entity_type": "company",
        "registered_agent": agent,
        "phones": [],
        "emails": [],
        "sources": [],
        "skiptrace_available": False,
        "disclaimer": "Synthetic protocol fixture.",
    }
    if carrier == "owner_mailing":
        payload["owner_mailing"] = "90 Ocean Drive, Miami, FL 33101"
    elif carrier == "registered_agent":
        agent["address"] = "90 Ocean Drive, Miami, FL 33101"
    else:
        agent["principals"] = [
            {
                "name": "Protocol Principal",
                "title": "Manager",
                "address": "90 Ocean Drive, Miami, FL 33101",
            }
        ]

    async def fixture(url_or_id: str, source: str = "loopnet"):
        del url_or_id, source
        return payload

    app = FastMCP(name="contact-address-egress-regression")
    app.tool(name="find_contact")(fixture)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool(
                    "find_contact", {"url_or_id": "fixture:property"}
                )
    finally:
        uninstall()

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_warn_result_rejects_unreconciled_county_location_carrier(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _warn_payload(state="TX", location="Dallas, TX")
    payload["events"][0]["county"] = "Miami-Dade County"

    with pytest.raises(ToolError) as caught:
        await _call_warn_fixture(registry, audit, identity, payload)

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "url_or_id",
    (
        "１２３ Main Street, Miami, FL ３３１０１",
        "١٢٣ Main Street, Miami, FL ٣٣١٠١",
    ),
)
async def test_get_comps_rejects_unicode_decimal_address_before_execution(
    request, registry, audit, identity, context_fixture, url_or_id
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name="get-comps-unicode-classifier-regression")

    @app.tool(name="get_comps")
    async def fixture(url_or_id: str, source: str = "loopnet"):
        del url_or_id, source
        executions[0] += 1
        return {}

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool("get_comps", {"url_or_id": url_or_id})
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_get_comps_rejects_out_of_scope_direct_address_before_execution(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    """The production direct-address branch is request-scoped before I/O."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    async def address_comps(address: str):
        del address
        executions[0] += 1
        raise AssertionError("out-of-scope direct address reached provider path")

    monkeypatch.setattr(market_tools, "_address_comps", address_comps)
    app = FastMCP(name="get-comps-direct-address-request-regression")
    app.tool(name="get_comps")(market_tools.get_comps)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(
                    "get_comps",
                    {"url_or_id": "90 Ocean Drive, Miami, FL 33101 USA"},
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_get_comps_releases_in_scope_direct_address_through_production_tool(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    """An exact in-scope address reaches the real tool and is checked again."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    subject = _listing()
    estimate = ValueEstimate(
        value=1_000_000,
        low=900_000,
        mid=1_000_000,
        high=1_100_000,
        method="fhfa_trend",
        n_comps=0,
        confidence=0.35,
        error_band=0.10,
        source="Synthetic protocol fixture.",
    )

    async def address_comps(address: str):
        assert address == "100 Main Street, Dallas, Texas 75201 USA"
        executions[0] += 1
        return subject, estimate, []

    monkeypatch.setattr(market_tools, "_address_comps", address_comps)
    app = FastMCP(name="get-comps-direct-address-positive-control")
    app.tool(name="get_comps")(market_tools.get_comps)
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
                {"url_or_id": "100 Main Street, Dallas, Texas 75201 USA"},
            )
    finally:
        uninstall()

    assert executions == [1]
    assert result.data["subject"]["state"] == "TX"
    assert result.data["subject"]["zip_code"] == "75201"


def _permit_request_row() -> dict[str, Any]:
    return {
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
        "permit_number": "TX-100",
        "permit_date": "2020-01-01",
        "type": "roofing permit",
        "desc": "Complete roof replacement",
    }


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "tool_name", ("unpermitted_work_screen", "stalled_project_signals")
)
@pytest.mark.parametrize(
    "case_name,mutation",
    _PERMIT_ROW_REQUEST_ESCAPES,
    ids=[case[0] for case in _PERMIT_ROW_REQUEST_ESCAPES],
)
async def test_permit_consumers_reject_ambiguous_or_unknown_rows_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
    case_name,
    mutation,
):
    del case_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    permit = {**_permit_request_row(), **mutation}
    app = FastMCP(name=f"{tool_name}-request-row-regression")
    if tool_name == "unpermitted_work_screen":

        async def fixture(
            observed_improvements: list[dict[str, Any]],
            permit_history: list[dict[str, Any]],
        ):
            del observed_improvements, permit_history
            executions[0] += 1
            return {}

        args = {
            "observed_improvements": [
                {"desc": "Complete roof replacement", "est_year": 2020}
            ],
            "permit_history": [permit],
        }
    else:

        async def fixture(
            permits: list[dict[str, Any]] | None = None,
            min_age_days: int | None = 365,
            as_of: str | None = None,
        ):
            del permits, min_age_days, as_of
            executions[0] += 1
            return {}

        args = {"permits": [permit]}
    app.tool(name=tool_name)(fixture)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(tool_name, args)
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "shape",
    _UNPERMITTED_UNSUPPORTED_ENVELOPES,
)
async def test_unpermitted_screen_rejects_unsupported_mapping_shapes(
    request, registry, audit, identity, context_fixture, shape
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    permit = _permit_request_row()
    if shape == "single-mapping":
        history: Any = permit
    elif shape == "results-envelope":
        history = {"status": "OK", "results": [permit]}
    else:
        history = {"status": "OK", "PERMITS": [permit]}
    executions = [0]
    app = FastMCP(name="unpermitted-envelope-regression")

    @app.tool(name="unpermitted_work_screen")
    async def fixture(
        observed_improvements: list[dict[str, Any]],
        permit_history: Any,
    ):
        del observed_improvements, permit_history
        executions[0] += 1
        return {}

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(
                    "unpermitted_work_screen",
                    {
                        "observed_improvements": [
                            {
                                "desc": "Complete roof replacement",
                                "est_year": 2020,
                            }
                        ],
                        "permit_history": history,
                    },
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_stalled_signal_reconciles_normalized_and_nested_addresses(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name="stalled-signal-address-reconciliation")

    @app.tool(name="stalled_project_signals")
    async def fixture(
        permits: list[dict[str, Any]] | None = None,
        min_age_days: int | None = 365,
        as_of: str | None = None,
    ):
        executions[0] += 1
        payload = prospect_tools.stalled_project_signals(
            permits,
            min_age_days=min_age_days,
            as_of=as_of,
        )
        payload["signals"][0]["normalized_address"] = (
            "90 Ocean Drive, Miami, FL 33101"
        )
        return payload

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool(
                    "stalled_project_signals",
                    {
                        "permits": [_permit_request_row()],
                        "as_of": "2026-08-01",
                    },
                )
    finally:
        uninstall()

    assert executions == [1]
    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)


def _appraisal_protocol_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    subject = {
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
    }
    return (
        {
            **subject,
            "value": "$1,000,000",
            "cap_rate_used": "6%",
            "rent_psf_used": 20,
            "expenses_used": 40_000,
            "comps_used": [],
        },
        {
            **subject,
            "our_rent_roll_psf": 22,
            "our_noi": 70_000,
            "our_expenses": 35_000,
            "market_comps": [],
        },
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("carrier", ("appraisal", "evidence"))
async def test_appraisal_nested_comp_requests_are_intersected_before_execution(
    request, registry, audit, identity, context_fixture, carrier
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    appraisal, evidence = _appraisal_protocol_inputs()
    out_of_scope_comp = {
        "address": "90 Ocean Drive, Miami, FL 33101",
        "city": "Miami",
        "state": "FL",
        "zip_code": "33101",
        "id": "fl-comp",
    }
    if carrier == "appraisal":
        appraisal["comps_used"] = [out_of_scope_comp]
    else:
        evidence["market_comps"] = [out_of_scope_comp]
    executions = [0]
    app = FastMCP(name="appraisal-nested-request-regression")

    @app.tool(name="challenge_appraisal")
    async def fixture(appraisal: dict[str, Any], evidence: dict[str, Any]):
        del appraisal, evidence
        executions[0] += 1
        return {}

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(
                    "challenge_appraisal",
                    {"appraisal": appraisal, "evidence": evidence},
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "carrier",
    ("appraisal_inputs", "submitted_evidence", "divergence_table"),
)
async def test_appraisal_nested_comp_results_are_all_validated_before_release(
    request, registry, audit, identity, context_fixture, carrier
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    appraisal, evidence = _appraisal_protocol_inputs()
    out_of_scope_comp = {
        "address": "90 Ocean Drive, Miami, FL 33101",
        "city": "Miami",
        "state": "FL",
        "zip_code": "33101",
        "id": "fl-comp",
    }
    app = FastMCP(name="appraisal-nested-result-regression")

    @app.tool(name="challenge_appraisal")
    async def fixture(appraisal: dict[str, Any], evidence: dict[str, Any]):
        payload = relation_tools.challenge_appraisal(appraisal, evidence)
        if carrier == "appraisal_inputs":
            payload["appraisal_inputs"]["comps_used"] = [out_of_scope_comp]
        elif carrier == "submitted_evidence":
            payload["submitted_evidence"]["market_comps"] = [out_of_scope_comp]
        else:
            row = next(
                item
                for item in payload["divergence_table"]
                if item["field"] == "comps_used"
            )
            row["additional_market_comps"] = [out_of_scope_comp]
        return payload

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool(
                    "challenge_appraisal",
                    {"appraisal": appraisal, "evidence": evidence},
                )
    finally:
        uninstall()

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)


def _tenant_site(state: str) -> dict[str, Any]:
    city, zip_code, address = _property_values(state)
    return {
        "sf": 10_000,
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "demographics": {},
    }


async def _call_actual_tenant_prospects(registry, audit, identity, site):
    app = FastMCP(name="tenant-prospect-territory-regression")
    app.tool(name="tenant_prospect_list")(leasing_tools.tenant_prospect_list)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            return await client.call_tool(
                "tenant_prospect_list",
                {"site": site, "existing_cotenancy": []},
            )
    finally:
        uninstall()


async def test_actual_tenant_prospect_list_denies_out_of_scope_site(
    registry, audit, identity, ctx_jv
):
    identity["ctx"] = ctx_jv.model_copy(update={"territories": ("TX",)})

    with pytest.raises(ToolError, match="territor"):
        await _call_actual_tenant_prospects(
            registry,
            audit,
            identity,
            _tenant_site("FL"),
        )


async def test_actual_tenant_prospect_list_releases_in_scope_site(
    registry, audit, identity, ctx_jv
):
    identity["ctx"] = ctx_jv.model_copy(update={"territories": ("TX",)})
    site = _tenant_site("TX")

    result = await _call_actual_tenant_prospects(
        registry,
        audit,
        identity,
        site,
    )

    assert result.data["site_inputs"] == site
    assert result.data["catalog_count"] == len(result.data["prospects"])


async def test_tenant_prospect_list_validates_returned_site_again(
    registry, audit, identity, ctx_jv
):
    identity["ctx"] = ctx_jv.model_copy(update={"territories": ("TX",)})
    app = FastMCP(name="tenant-prospect-egress-regression")

    @app.tool(name="tenant_prospect_list")
    async def fixture(
        site: dict[str, Any],
        existing_cotenancy: list[dict[str, Any]] | None = None,
    ):
        del site, existing_cotenancy
        return {
            "prospects": [],
            "catalog_count": 0,
            "catalog_coverage_note": "Synthetic protocol fixture.",
            "cotenancy_source": "Synthetic protocol fixture.",
            "cotenancy_observation_count": 0,
            "whitespace_radius_m": 1609,
            "ranking_method": "Synthetic protocol fixture.",
            "watch_hook_note": "Synthetic protocol fixture.",
            "site_inputs": _tenant_site("FL"),
        }

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool(
                    "tenant_prospect_list",
                    {"site": _tenant_site("TX"), "existing_cotenancy": []},
                )
    finally:
        uninstall()

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("address", _BARE_OR_NON_STREET_ADDRESSES)
async def test_bare_or_non_street_address_cannot_borrow_sibling_location_fields(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    address,
):
    """A city, label, or number is not a property address."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _search_payload(
        collection,
        query_location="TX",
        state="TX",
        city="Dallas",
        zip_code="75201",
        address=address,
    )

    with pytest.raises(ToolError) as caught:
        await _call_search(registry, audit, identity, payload, location="TX")

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("address", _OBFUSCATED_OUT_OF_SCOPE_ADDRESS_TAILS)
async def test_obfuscated_state_tail_cannot_borrow_in_scope_sibling_fields(
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
    payload = _search_payload(
        collection,
        query_location="TX",
        state="TX",
        city="Dallas",
        zip_code="75201",
        address=address,
    )

    with pytest.raises(ToolError) as caught:
        await _call_search(registry, audit, identity, payload, location="TX")

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "_case,geo",
    _INCONSISTENT_GEO_REFS,
    ids=[case for case, _geo_ref in _INCONSISTENT_GEO_REFS],
)
async def test_inconsistent_or_cross_state_geo_reference_fails_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    _case,
    geo,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _property_egress_payload("market_intel", "TX")
    payload["geo"] = geo

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name="market_intel",
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "county_fips,name,request_location",
    (
        ("48113", "Dallas County, TX", "Dallas County, TX"),
        ("48201", "Harris County", "Harris County, TX"),
    ),
    ids=("dallas-with-state", "harris-sibling-state"),
)
async def test_authoritative_same_state_county_geo_reference_releases(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    county_fips,
    name,
    request_location,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _property_egress_payload("market_intel", "TX")
    payload["geo"] = {
        "level": "county",
        "state_fips": "48",
        "county_fips": county_fips,
        "cbsa": None,
        "zip": None,
        "tract": None,
        "name": name,
    }

    result = await _call_property_egress_tool(
        registry,
        audit,
        identity,
        tool_name="market_intel",
        payload=payload,
        request_location=request_location,
    )

    assert result.data["geo"]["county_fips"] == county_fips
    assert result.data["geo"]["name"] == name


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_arbitrage_economics_rejects_undeclared_nested_property(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _property_egress_payload("find_arbitrage_opportunities", "TX")
    payload["opportunities"][0]["economics"]["other_property"] = {
        "address": "90 Ocean Drive, Miami, FL 33101"
    }

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name="find_arbitrage_opportunities",
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("carrier", ("vacancy", "tenant_match"))
async def test_control_result_rejects_undeclared_nested_property(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    carrier,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _property_egress_payload("find_control_opportunities", "TX")
    opportunity = payload["opportunities"][0]
    if carrier == "vacancy":
        opportunity["vacancy"]["hidden_property"] = {
            "address": "90 Ocean Drive, Miami, FL 33101"
        }
    else:
        opportunity["tenant_matches"] = [
            {
                "brand": "Protocol Tenant",
                "fit_score": 0.5,
                "met": [],
                "unmet": [],
                "reasons": "Synthetic protocol fixture.",
                "hidden_site": "90 Ocean Drive, Miami, FL 33101",
            }
        ]

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name="find_control_opportunities",
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_route_lead_rejects_alternate_listing_geography_before_execution(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name="route-lead-request-carrier-regression")

    @app.tool(name="route_lead")
    async def fixture(listing: dict[str, Any], team: list[dict[str, Any]]):
        del listing, team
        executions[0] += 1
        return _property_egress_payload("route_lead", "TX")

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    listing = {
        "source_id": "request-tx",
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
        "market": "Miami, FL",
    }
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="territor"):
                await client.call_tool(
                    "route_lead",
                    {"listing": listing, "team": [{"name": "Fixture"}]},
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_actual_route_lead_does_not_echo_mandate_location_text(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    app = FastMCP(name="route-lead-output-sanitization-regression")
    app.tool(name="route_lead")(relation_tools.route_lead)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool(
                "route_lead",
                {
                    "listing": {
                        "source_id": "request-tx",
                        "address": "100 Main Street, Dallas, TX 75201",
                        "city": "Dallas",
                        "state": "TX",
                        "zip_code": "75201",
                        "property_type": "retail",
                    },
                    "team": [
                        {
                            "name": "Fixture",
                            "mandates": [
                                {
                                    "property_types": ["retail"],
                                    "states": ["TX"],
                                    "notes": (
                                        "Do not echo 90 Ocean Drive, Miami, "
                                        "FL 33101"
                                    ),
                                }
                            ],
                        }
                    ],
                },
            )
    finally:
        uninstall()

    encoded = json.dumps(result.data, sort_keys=True)
    assert result.data["recommended"]["matched_mandate"] == "structured mandate"
    assert "Miami" not in encoded
    assert "33101" not in encoded


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_control_request_rejects_undeclared_raw_property_before_execution(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name="control-request-raw-regression")

    @app.tool(name="find_control_opportunities")
    async def fixture(listings: list[dict[str, Any]]):
        del listings
        executions[0] += 1
        return _property_egress_payload("find_control_opportunities", "TX")

    listing = _listing(state="TX").model_dump(mode="json")
    listing["raw"] = {
        "hidden_property": "90 Ocean Drive, Miami, FL 33101",
    }
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="territor"):
                await client.call_tool(
                    "find_control_opportunities",
                    {"listings": [listing]},
                )
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("tool_name", ("list_deals", "list_pipeline"))
async def test_jv_deal_lists_do_not_release_note_location_text(
    registry, audit, identity, ctx_jv, tool_name
):
    identity["ctx"] = ctx_jv.model_copy(update={"territories": ("TX",)})
    note = {
        "text": "90 Ocean Drive, Miami, FL 33101",
        "stage": "lead",
        "created_at": "2026-08-01T00:00:00+00:00",
    }
    if tool_name == "list_deals":
        row = {**_compact_deal_row("TX"), "last_note": note}
        payload = {"deals": [row], "count": 1}
    else:
        row = {
            **_compact_deal_row("TX"),
            "last_note": note,
            "url": "https://example.test/listing",
            "notes": [note],
        }
        payload = {
            "stage": None,
            "deals": [row],
            "by_stage": {"lead": [row]},
            "count": 1,
        }

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("tool_name", _DEAL_EGRESS_TOOLS)
async def test_underwriting_assumptions_cannot_carry_undeclared_property(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    deal = Deal(
        listing=_listing(state="TX"),
        underwriting=UnderwritingResult(
            assumptions_used={
                "hidden_location": {
                    "value": "90 Ocean Drive, Miami, FL 33101",
                    "source": "synthetic protocol fixture",
                }
            }
        ),
    )
    payload = _deal_egress_payload(tool_name, deal)

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


def _warn_payload(*, state: str, location: str) -> dict[str, Any]:
    return {
        "status": "OK",
        "state": state,
        "since": "2026-01-01",
        "count": 1,
        "events": [
            {
                "employer": "Protocol Fixture Employer",
                "location": location,
                "affected": 10,
                "effective_date": "2026-08-01",
                "source_url": "https://example.test/warn",
            }
        ],
        "source_url": "https://example.test/warn",
        "dataset_url": "https://example.test/warn-dataset",
        "request_url": "https://example.test/warn?state=TX",
        "source_retrieved_date": "2026-08-01",
        "since_convention": "Synthetic protocol fixture.",
    }


async def _call_warn_fixture(registry, audit, identity, payload):
    app = FastMCP(name="warn-territory-regression")

    @app.tool(name="employer_warn_events")
    async def fixture(state: str, since: str | None = None):
        del state, since
        return payload

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            return await client.call_tool(
                "employer_warn_events",
                {"state": "TX", "since": "2026-01-01"},
            )
    finally:
        uninstall()


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("mismatch", ("event", "envelope"))
async def test_warn_result_validates_envelope_and_every_event_location(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    mismatch,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _warn_payload(
        state="FL" if mismatch == "envelope" else "TX",
        location=(
            "Dallas, TX"
            if mismatch == "envelope"
            else "Miami, Miami-Dade County, FL"
        ),
    )

    with pytest.raises(ToolError) as caught:
        await _call_warn_fixture(registry, audit, identity, payload)

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_warn_result_releases_complete_in_scope_event(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _warn_payload(state="TX", location="Dallas, TX")

    result = await _call_warn_fixture(registry, audit, identity, payload)

    expected = dict(payload)
    expected["request_url"] = "https://example.test/warn"
    assert result.data == expected


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
async def test_nonexistent_city_state_result_fails_closed(
    request, registry, audit, identity, context_fixture, collection
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _search_payload(
        collection,
        query_location="TX",
        state="TX",
        city="Honolulu",
        zip_code=None,
        address="100 Main Street",
    )

    with pytest.raises(ToolError) as caught:
        await _call_search(registry, audit, identity, payload, location="TX")

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "case_name,territory,city,zip_code",
    _INVALID_OR_OTHER_JURISDICTION_ZIPS,
    ids=[case[0] for case in _INVALID_OR_OTHER_JURISDICTION_ZIPS],
)
async def test_unassigned_or_other_jurisdiction_zip_denies_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    case_name,
    territory,
    city,
    zip_code,
):
    del case_name
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": (territory,)}
    )
    executions = [0]

    def result():
        executions[0] += 1
        return _search_payload(
            "properties",
            query_location=zip_code,
            state=territory,
            city=city,
            zip_code=zip_code,
            address=f"100 Main Street, {city}, {territory} {zip_code}",
        )

    with pytest.raises(ToolError, match="territor"):
        await _call_search(
            registry,
            audit,
            identity,
            result,
            location=zip_code,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_five_digit_street_number_is_not_a_zip_request_claim(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    result = await _call_owner_lookup(
        registry,
        audit,
        identity,
        address="12345 Main Street, Dallas, TX 75201",
        county=None,
        executions=executions,
    )

    assert result.data["name"] == "Protocol Fixture Owner"
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
async def test_five_digit_street_number_is_not_a_zip_result_claim(
    request, registry, audit, identity, context_fixture, collection
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    address = "12345 Main Street, Dallas, TX 75201"
    payload = _search_payload(
        collection,
        query_location="TX",
        state="TX",
        city="Dallas",
        zip_code="75201",
        address=address,
    )

    result = await _call_search(
        registry, audit, identity, payload, location="TX"
    )

    assert result.data[collection][0]["address"] == address


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_full_state_name_inside_numbered_street_is_not_a_request_claim(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("VA",)}
    )
    executions = [0]

    result = await _call_owner_lookup(
        registry,
        audit,
        identity,
        address="700 George Washington Memorial Parkway, McLean, VA 22101",
        county=None,
        executions=executions,
    )

    assert result.data["name"] == "Protocol Fixture Owner"
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
async def test_full_state_name_inside_numbered_street_is_not_a_result_claim(
    request, registry, audit, identity, context_fixture, collection
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("VA",)}
    )
    address = "700 George Washington Memorial Parkway, McLean, VA 22101"
    payload = _search_payload(
        collection,
        query_location="VA",
        state="VA",
        city="McLean",
        zip_code="22101",
        address=address,
    )

    result = await _call_search(
        registry, audit, identity, payload, location="VA"
    )

    assert result.data[collection][0]["address"] == address


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_nfkc_state_conflict_in_request_denies_before_execution(
    request, registry, audit, identity, context_fixture
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
            address="90 Ocean Drive, Miami ＦＬ; 100 Main Street, Dallas TX",
            county="Dallas, TX",
            executions=executions,
        )

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("carrier", ("address", "city"))
async def test_nfkc_state_conflict_in_result_location_carrier_fails_closed(
    request, registry, audit, identity, context_fixture, collection, carrier
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    address = "100 Main Street, Dallas, TX 75201"
    city = "Dallas"
    if carrier == "address":
        address = "90 Ocean Drive, Miami ＦＬ; 100 Main Street, Dallas TX 75201"
    else:
        city = "Miami, ＦＬ"
    payload = _search_payload(
        collection,
        query_location="TX",
        state="TX",
        city=city,
        zip_code="75201",
        address=address,
    )

    with pytest.raises(ToolError) as caught:
        await _call_search(registry, audit, identity, payload, location="TX")

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("address,city", _SEMANTIC_UNKNOWN_LOCATION_CASES)
async def test_semantic_unknown_required_location_values_fail_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    collection,
    address,
    city,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _search_payload(
        collection,
        query_location="TX",
        state="TX",
        city=city,
        zip_code="75201",
        address=address,
    )

    with pytest.raises(ToolError) as caught:
        await _call_search(registry, audit, identity, payload, location="TX")

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("city", _MULTI_LOCATION_CITY_VALUES)
async def test_multi_location_city_field_fails_closed(
    request, registry, audit, identity, context_fixture, collection, city
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _search_payload(
        collection,
        query_location="TX",
        state="TX",
        city=city,
        zip_code="75201",
        address="100 Main Street",
    )

    with pytest.raises(ToolError) as caught:
        await _call_search(registry, audit, identity, payload, location="TX")

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("address", _PROSE_LOCATION_CONNECTOR_ESCAPES)
async def test_prose_connector_cannot_hide_second_result_location(
    request, registry, audit, identity, context_fixture, collection, address
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _search_payload(
        collection,
        query_location="TX",
        state="TX",
        city="Dallas",
        zip_code="75201",
        address=address,
    )

    with pytest.raises(ToolError) as caught:
        await _call_search(registry, audit, identity, payload, location="TX")

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("collection", _RESULT_COLLECTIONS)
@pytest.mark.parametrize("address", _MULTIWORD_STATE_WHITESPACE_ADDRESSES)
async def test_multiword_state_whitespace_in_result_fails_closed(
    request, registry, audit, identity, context_fixture, collection, address
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _search_payload(
        collection,
        query_location="TX",
        state="TX",
        city="Dallas",
        zip_code="75201",
        address=address,
    )

    with pytest.raises(ToolError) as caught:
        await _call_search(registry, audit, identity, payload, location="TX")

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "address",
    (
        "100 Main St, Raleigh North   Carolina",
        "100 Main St, New\tYork New\tYork",
    ),
)
async def test_multiword_state_whitespace_in_multi_parameter_request_denies(
    request, registry, audit, identity, context_fixture, address
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
            address=address,
            county="Dallas, TX",
            executions=executions,
        )

    assert executions == [0]


@pytest.mark.parametrize(
    "context_fixture,tool_name",
    _PROPERTY_BEARING_EGRESS_CONTEXTS,
)
async def test_every_property_bearing_tool_denies_out_of_scope_nested_record(
    request, registry, audit, identity, context_fixture, tool_name
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _property_egress_payload(tool_name, "FL")

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)
    assert "33101" not in str(caught.value)


@pytest.mark.parametrize(
    "context_fixture,tool_name",
    _PROPERTY_BEARING_EGRESS_CONTEXTS,
)
async def test_every_property_bearing_tool_releases_in_scope_nested_record(
    request, registry, audit, identity, context_fixture, tool_name
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _property_egress_payload(tool_name, "TX")

    result = await _call_property_egress_tool(
        registry,
        audit,
        identity,
        tool_name=tool_name,
        payload=payload,
    )

    assert json.dumps(result.data, sort_keys=True) == json.dumps(
        _without_provider_raw(payload), sort_keys=True
    )


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("tool_name", _DEAL_EGRESS_TOOLS)
@pytest.mark.parametrize("nested_path", _DEAL_NESTED_LOCATION_PATHS)
async def test_every_nested_deal_location_path_denies_out_of_scope_record(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
    nested_path,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = _deal_egress_payload(
        tool_name,
        _deal_with_nested_location(nested_path, "FL"),
    )

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)
    assert "33101" not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("tool_name", _DEAL_EGRESS_TOOLS)
async def test_nested_deal_location_paths_release_when_all_are_in_scope(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    deal = Deal(
        listing=_listing(state="TX"),
        sale_comps=[
            SaleComp(
                source="Synthetic County",
                county_fips="48113",
                parcel_id="nested-comp",
                address="100 Main Street, Dallas, TX 75201",
                sale_price=900_000,
            )
        ],
        market_pack=MarketPack(geo=_geo("TX")),
        parcel=ParcelRecord(site_address="100 Main Street, Dallas, TX 75201"),
        owner=OwnerRecord(
            name="Protocol Fixture Owner",
            normalized_name="PROTOCOL FIXTURE OWNER",
            entity_type="company",
            parcels=[
                ParcelRecord(site_address="100 Main Street, Dallas, TX 75201")
            ],
        ),
        rent_comps=RentComps(
            geo=_geo("TX"),
            comps=[
                RentComparable(
                    source="Synthetic Rent",
                    rent=2_000,
                    location="100 Main Street, Dallas, TX 75201",
                )
            ],
        ),
    )
    payload = _deal_egress_payload(tool_name, deal)

    result = await _call_property_egress_tool(
        registry,
        audit,
        identity,
        tool_name=tool_name,
        payload=payload,
    )

    assert json.dumps(result.data, sort_keys=True) == json.dumps(
        _without_provider_raw(payload), sort_keys=True
    )


@pytest.mark.parametrize("tool_name", ("list_deals", "list_pipeline"))
async def test_zip_granted_jv_denies_compact_rows_that_omit_zip(
    registry, audit, identity, ctx_jv, tool_name
):
    identity["ctx"] = ctx_jv.model_copy(update={"territories": ("75201",)})
    row = _compact_deal_row("TX", include_zip=False)
    row["address"] = "100 Main Street"
    if tool_name == "list_deals":
        payload = {"deals": [row], "count": 1}
    else:
        pipeline_row = {
            **row,
            "url": "https://example.test/listing",
            "notes": [],
        }
        payload = {
            "stage": None,
            "deals": [pipeline_row],
            "by_stage": {"lead": [pipeline_row]},
            "count": 1,
        }

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "tool_name",
    (
        "search_properties",
        "find_deals",
        "find_distressed",
        "analyze_deal",
        "check_alerts",
        "find_control_opportunities",
    ),
)
async def test_arbitrary_listing_raw_is_not_released_to_restricted_profiles(
    request, registry, audit, identity, context_fixture, tool_name
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    listing = _listing(state="TX").model_copy(
        update={"raw": {"property_address": "90 Ocean Drive, Miami, FL 33101"}}
    )
    if tool_name == "search_properties":
        payload = AggregatedSearchResult(
            query_location="TX",
            listings=[listing],
        ).model_dump(mode="json")
        call = _call_search(
            registry,
            audit,
            identity,
            payload,
            location="TX",
        )
    elif tool_name == "find_control_opportunities":
        payload = _property_egress_payload(tool_name, "TX")
        payload["opportunities"][0]["listing"] = listing.model_dump(mode="json")
        call = _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            payload=payload,
        )
    else:
        payload = _deal_egress_payload(tool_name, Deal(listing=listing))
        call = _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            payload=payload,
        )

    with pytest.raises(ToolError) as caught:
        await call

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("tool_name", _DEAL_EGRESS_TOOLS)
@pytest.mark.parametrize("carrier", ("parcel", "owner.parcels[]"))
async def test_arbitrary_nested_parcel_raw_is_not_released(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
    carrier,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    parcel = ParcelRecord(
        site_address="100 Main Street, Dallas, TX 75201",
        raw={"property_address": "90 Ocean Drive, Miami, FL 33101"},
    )
    if carrier == "parcel":
        deal = Deal(listing=_listing(state="TX"), parcel=parcel)
    else:
        deal = Deal(
            listing=_listing(state="TX"),
            owner=OwnerRecord(
                name="Protocol Fixture Owner",
                normalized_name="PROTOCOL FIXTURE OWNER",
                entity_type="company",
                parcels=[parcel],
            ),
        )
    payload = _deal_egress_payload(tool_name, deal)

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Miami" not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_owner_lookup_parcel_raw_is_not_released(
    request, registry, audit, identity, context_fixture
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    payload = OwnerRecord(
        name="Protocol Fixture Owner",
        normalized_name="PROTOCOL FIXTURE OWNER",
        entity_type="company",
        parcels=[
            ParcelRecord(
                site_address="100 Main Street, Dallas, TX 75201",
                raw={"property_address": "90 Ocean Drive, Miami, FL 33101"},
            )
        ],
    ).model_dump(mode="json")

    with pytest.raises(ToolError) as caught:
        await _call_property_egress_tool(
            registry,
            audit,
            identity,
            tool_name="owner_lookup",
            payload=payload,
        )

    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_stale_saved_search_is_denied_before_nested_provider_execution(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]

    class StoredSearches:
        async def get_search(self, search_id: int):
            assert search_id == 1
            return {
                "id": 1,
                "name": "Stale Florida Search",
                "query": {"location": "Miami, FL", "sources": ["loopnet"]},
                "min_score": None,
                "created_at": "2026-08-01T00:00:00+00:00",
                "seen_count": 0,
            }

    async def forbidden_find_deals(**_kwargs):
        executions[0] += 1
        return {"deals": [], "errors": {}}

    monkeypatch.setattr(pipeline_tools, "get_search_store", lambda: StoredSearches())
    monkeypatch.setattr(pipeline_tools, "find_deals", forbidden_find_deals)
    app = FastMCP(name="territory-stale-alert-regression")
    app.tool(name="check_alerts")(pipeline_tools.check_alerts)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool("check_alerts", {"search_id": 1})
    finally:
        uninstall()

    assert executions == [0]
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_market_overview_denies_provider_row_before_aggregation(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    builds = [0]

    class OutOfScopeRegistry:
        async def search_all(self, _query, *, sources):
            assert sources == ["loopnet"]
            return AggregatedSearchResult(
                query_location="TX",
                listings=[_listing(state="FL")],
            )

    def forbidden_build(*_args, **_kwargs):
        builds[0] += 1
        raise AssertionError("aggregate builder must not see an unauthorized row")

    monkeypatch.setattr(listing_tools, "registry", OutOfScopeRegistry())
    monkeypatch.setattr(listing_tools, "build_market_overview", forbidden_build)
    app = FastMCP(name="territory-market-aggregate-regression")
    app.tool(name="get_market_overview")(listing_tools.get_market_overview)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool("get_market_overview", {"location": "TX"})
    finally:
        uninstall()

    assert builds == [0]
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_actual_search_preserves_pagination_after_raw_projection(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
):
    """Provider metadata remains functional without becoming client egress."""
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    listing = _listing(state="TX").model_copy(
        update={
            "raw": {
                "loopnet_search": {"total_results": 87, "has_next_page": True},
                "provider_secret": "must-not-egress",
            }
        }
    )

    class InScopeRegistry:
        async def search_all(self, query, *, sources):
            assert query.location == "TX"
            assert sources == ["loopnet"]
            return AggregatedSearchResult(
                query_location="TX",
                listings=[listing],
            )

    monkeypatch.setattr(listing_tools, "registry", InScopeRegistry())
    app = FastMCP(name="territory-search-pagination-regression")
    app.tool(name="search_properties")(listing_tools.search_properties)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool("search_properties", {"location": "TX"})
    finally:
        uninstall()

    assert result.data["total_results"] == 87
    assert result.data["has_next_page"] is True
    assert len(result.data["properties"]) == 1
    assert "provider_secret" not in json.dumps(result.data)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("tool_name", _RESTRICTED_OPEN_ENVELOPE_TOOLS)
async def test_restored_property_envelope_tools_reject_untyped_results(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    app = FastMCP(name=f"territory-open-envelope-{tool_name}")

    if tool_name == "find_contact":

        async def fixture(url_or_id: str, source: str = "loopnet"):
            del url_or_id, source
            executions[0] += 1
            return {"contact": "90 Ocean Drive, Miami, FL 33101"}

        args = {"url_or_id": "fixture:property"}
    elif tool_name == "after_tax_returns":

        async def fixture(
            url_or_id: str,
            marginal_rate: float = 0.37,
            bonus_pct: float | None = None,
            cost_seg: bool = False,
            hold_years: int = 5,
            source: str = "loopnet",
        ):
            del url_or_id, marginal_rate, bonus_pct, cost_seg, hold_years, source
            executions[0] += 1
            return {"property": "90 Ocean Drive, Miami, FL 33101"}

        args = {"url_or_id": "fixture:property"}
    elif tool_name == "audit_assessor_record":

        async def fixture(record: dict[str, Any], stated_facts: dict[str, Any]):
            del record, stated_facts
            executions[0] += 1
            return {"property": "90 Ocean Drive, Miami, FL 33101"}

        args = {
            "record": {
                "address": "100 Main Street, Dallas, TX 75201",
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75201",
            },
            "stated_facts": {"building_sqft": 10_000},
        }
    elif tool_name == "challenge_appraisal":

        async def fixture(appraisal: dict[str, Any], evidence: dict[str, Any]):
            del appraisal, evidence
            executions[0] += 1
            return {"property": "90 Ocean Drive, Miami, FL 33101"}

        args = {
            "appraisal": {
                "address": "100 Main Street, Dallas, TX 75201",
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75201",
                "comps_used": [],
            },
            "evidence": {
                "address": "100 Main Street, Dallas, TX 75201",
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75201",
                "market_comps": [],
            },
        }
    else:

        async def fixture(
            permits: list[dict[str, Any]] | None = None,
            min_age_days: int | None = 365,
            as_of: str | None = None,
        ):
            del permits, min_age_days, as_of
            executions[0] += 1
            return {"property": "90 Ocean Drive, Miami, FL 33101"}

        args = {
            "permits": [
                {
                    "address": "100 Main Street, Dallas, TX 75201",
                    "city": "Dallas",
                    "state": "TX",
                    "zip_code": "75201",
                    "permit_date": "2020-01-01",
                }
            ]
        }
    app.tool(name=tool_name)(fixture)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool(tool_name, args)
    finally:
        uninstall()

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("tool_name", _RESTRICTED_STRUCTURED_REQUEST_TOOLS)
@pytest.mark.parametrize(
    "request_kind",
    ("out_of_scope", "incomplete", "omitted", "null"),
)
async def test_restored_structured_property_tools_reject_bad_requests_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
    request_kind,
):
    """Required property subjects are intersected before a tool can run."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    subject: dict[str, Any] = {
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
    }
    if request_kind == "out_of_scope":
        subject.update(
            address="90 Ocean Drive, Miami, FL 33101",
            city="Miami",
            state="FL",
            zip_code="33101",
        )
    elif request_kind == "incomplete":
        subject["city"] = ""
    elif request_kind == "omitted":
        subject.pop("address")
    else:
        subject["address"] = None

    app = FastMCP(name=f"territory-request-contract-{tool_name}")
    if tool_name == "audit_assessor_record":

        async def fixture(record: dict[str, Any], stated_facts: dict[str, Any]):
            del record, stated_facts
            executions[0] += 1
            return {}

        args = {
            "record": subject,
            "stated_facts": {"building_sqft": 10_000},
        }
    elif tool_name == "challenge_appraisal":

        async def fixture(appraisal: dict[str, Any], evidence: dict[str, Any]):
            del appraisal, evidence
            executions[0] += 1
            return {}

        args = {
            "appraisal": {**subject, "comps_used": []},
            "evidence": {
                "address": "100 Main Street, Dallas, TX 75201",
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75201",
                "market_comps": [],
            },
        }
    else:

        async def fixture(
            permits: list[dict[str, Any]] | None = None,
            min_age_days: int | None = 365,
            as_of: str | None = None,
        ):
            del permits, min_age_days, as_of
            executions[0] += 1
            return {}

        args = {"permits": [{**subject, "permit_date": "2020-01-01"}]}

    app.tool(name=tool_name)(fixture)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool(tool_name, args)
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_stalled_projects_rejects_empty_required_permit_collection(
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
    app = FastMCP(name="territory-empty-permit-request")

    @app.tool(name="stalled_project_signals")
    async def fixture(
        permits: list[dict[str, Any]] | None = None,
        min_age_days: int | None = 365,
        as_of: str | None = None,
    ):
        del permits, min_age_days, as_of
        executions[0] += 1
        return {}

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool("stalled_project_signals", {"permits": []})
    finally:
        uninstall()

    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("tool_name", _RESTRICTED_OPEN_ENVELOPE_TOOLS)
async def test_restored_property_envelope_tools_release_in_scope_production_results(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
):
    """Exercise each restored production adapter through FastMCP middleware."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    subject = {
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
    }
    listing = _listing().model_copy(
        update={
            **subject,
            "property_type": "retail",
            "price_usd": 1_000_000.0,
            "noi_usd": 100_000.0,
        }
    )
    ctx = DealContext(listing=listing)

    if tool_name == "find_contact":

        async def deal_context_fixture(url_or_id: str, source: str):
            del url_or_id, source
            return ctx

        async def contact_fixture(_ctx: DealContext):
            return ContactInfo(
                owner_name="Protocol Fixture Owner LLC",
                entity_type="company",
                disclaimer="Synthetic protocol fixture.",
            )

        monkeypatch.setattr(execution_tools, "_deal_context", deal_context_fixture)
        monkeypatch.setattr(execution_tools, "assemble_contact", contact_fixture)
        tool = execution_tools.find_contact
        args: dict[str, Any] = {"url_or_id": "fixture:property"}
    elif tool_name == "after_tax_returns":

        async def deal_context_fixture(url_or_id: str, source: str):
            del url_or_id, source
            return ctx

        monkeypatch.setattr(ops_tools, "_deal_context", deal_context_fixture)
        monkeypatch.setattr(
            ops_tools,
            "calculate_after_tax_returns",
            after_tax_module.after_tax_returns,
        )
        tool = ops_tools.after_tax_returns
        args = {"url_or_id": "fixture:property", "hold_years": 2}
    elif tool_name == "audit_assessor_record":
        tool = taxecon_tools.audit_assessor_record
        args = {
            "record": {**subject, "building_sqft": 12_000, "use_code": "office"},
            "stated_facts": {
                "building_sqft": 10_000,
                "use_code": "retail",
            },
        }
    elif tool_name == "challenge_appraisal":
        tool = relation_tools.challenge_appraisal
        args = {
            "appraisal": {
                **subject,
                "value": "$1,000,000",
                "cap_rate_used": "6%",
                "rent_psf_used": 20,
                "expenses_used": 40_000,
                "comps_used": [],
            },
            "evidence": {
                **subject,
                "our_rent_roll_psf": 22,
                "our_noi": 70_000,
                "our_expenses": 35_000,
                "market_comps": [],
            },
        }
    else:
        tool = prospect_tools.stalled_project_signals
        args = {
            "permits": [
                {
                    **subject,
                    "permit_number": "TX-100",
                    "permit_date": "2020-01-01",
                }
            ],
            "as_of": "2026-08-01",
        }

    app = FastMCP(name=f"territory-production-result-{tool_name}")
    app.tool(name=tool_name)(tool)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool(tool_name, args)
    finally:
        uninstall()

    if tool_name in {"find_contact", "after_tax_returns", "audit_assessor_record"}:
        assert result.data["subject_property"]["state"] == "TX"
    elif tool_name == "challenge_appraisal":
        assert result.data["appraisal_inputs"]["state"] == "TX"
        assert result.data["submitted_evidence"]["state"] == "TX"
    else:
        assert result.data["signals"][0]["record"]["state"] == "TX"


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "tool_name,echo_field",
    (
        ("audit_assessor_record", "assessor_value"),
        ("challenge_appraisal", "their_input"),
    ),
)
async def test_restricted_semantic_echo_fields_cannot_carry_hidden_properties(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
    echo_field,
):
    """Typed non-location fields cannot become an address-smuggling channel."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    subject = {
        "address": "100 Main Street, Dallas, TX 75201",
        "city": "Dallas",
        "state": "TX",
        "zip_code": "75201",
    }
    app = FastMCP(name=f"territory-semantic-echo-{tool_name}")
    if tool_name == "audit_assessor_record":

        async def fixture(record: dict[str, Any], stated_facts: dict[str, Any]):
            payload = taxecon_tools.audit_assessor_record(record, stated_facts)
            payload["discrepancies"][0][echo_field] = (
                "90 Ocean Drive, Miami, FL 33101"
            )
            return payload

        args: dict[str, Any] = {
            "record": {**subject, "building_sqft": 12_000},
            "stated_facts": {"building_sqft": 10_000},
        }
    else:

        async def fixture(appraisal: dict[str, Any], evidence: dict[str, Any]):
            payload = relation_tools.challenge_appraisal(appraisal, evidence)
            payload["divergence_table"][0][echo_field] = (
                "90 Ocean Drive, Miami, FL 33101"
            )
            return payload

        args = {
            "appraisal": {
                **subject,
                "value": 1_000_000,
                "cap_rate_used": 6,
                "rent_psf_used": 20,
                "expenses_used": 40_000,
                "comps_used": [],
            },
            "evidence": {
                **subject,
                "our_rent_roll_psf": 22,
                "our_noi": 70_000,
                "our_expenses": 35_000,
                "market_comps": [],
            },
        }

    app.tool(name=tool_name)(fixture)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool(tool_name, args)
    finally:
        uninstall()

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert "Ocean Drive" not in str(caught.value)


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
async def test_restricted_appraisal_locationless_public_shape_fails_closed(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    app = FastMCP(name="appraisal-canonical-compatibility")
    app.tool(name="challenge_appraisal")(relation_tools.challenge_appraisal)
    args = {
        "appraisal": {
            "value": 10_000_000,
            "cap_rate_used": 0.06,
            "rent_psf_used": 24,
            "expenses_used": 300_000,
            "comps_used": [
                {"id": "A", "address": "1 Main"},
                {"id": "B", "address": "2 Main"},
            ],
        },
        "evidence": {
            "our_rent_roll_psf": 27,
            "our_noi": 660_000,
            "our_expenses": 360_000,
            "market_comps": [
                {"id": "A", "cap_rate": 0.065, "rent_psf": 27},
                {"id": "C", "cap_rate": 0.07, "rent_psf": 29},
            ],
        },
    }
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="property request"):
                await client.call_tool("challenge_appraisal", args)
    finally:
        uninstall()


async def test_full_operator_appraisal_locationless_public_shape_remains_compatible(
    registry,
    audit,
    identity,
    ctx_op,
):
    identity["ctx"] = ctx_op
    app = FastMCP(name="appraisal-canonical-full-operator")
    app.tool(name="challenge_appraisal")(relation_tools.challenge_appraisal)
    args = {
        "appraisal": {
            "value": 10_000_000,
            "cap_rate_used": 0.06,
            "rent_psf_used": 24,
            "expenses_used": 300_000,
            "comps_used": [
                {"id": "A", "address": "1 Main"},
                {"id": "B", "address": "2 Main"},
            ],
        },
        "evidence": {
            "our_rent_roll_psf": 27,
            "our_noi": 660_000,
            "our_expenses": 360_000,
            "market_comps": [
                {"id": "A", "cap_rate": 0.065, "rent_psf": 27},
                {"id": "C", "cap_rate": 0.07, "rent_psf": 29},
            ],
        },
    }
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool("challenge_appraisal", args)
    finally:
        uninstall()

    assert result.data["status"] == "DIVERGENCES_FOUND"
    assert result.data["sample_sizes"] == {
        "appraisal_comps": 2,
        "market_comps": 2,
    }


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("tool_name", ("find_contact", "after_tax_returns"))
async def test_opaque_property_ids_are_resolved_and_checked_before_downstream_work(
    request,
    monkeypatch,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
):
    """An opaque ID is authorized from its resolved listing before enrichment."""

    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    out_of_scope = Deal(listing=_listing(state="FL")).model_dump(mode="json")
    executions = [0]

    async def analyze_fixture(*args: Any, **kwargs: Any):
        del args, kwargs
        return out_of_scope

    if tool_name == "find_contact":

        async def downstream_fixture(_ctx: DealContext):
            executions[0] += 1
            return ContactInfo(disclaimer="must not execute")

        monkeypatch.setattr(execution_tools, "analyze_deal", analyze_fixture)
        monkeypatch.setattr(execution_tools, "assemble_contact", downstream_fixture)
        tool = execution_tools.find_contact
        args = {"url_or_id": "fixture:out-of-scope"}
    else:

        def downstream_fixture(_ctx: DealContext, _assumptions: dict[str, Any]):
            executions[0] += 1
            raise AssertionError("after-tax calculation must not execute")

        monkeypatch.setattr(ops_tools, "analyze_deal", analyze_fixture)
        monkeypatch.setattr(
            ops_tools,
            "calculate_after_tax_returns",
            downstream_fixture,
        )
        tool = ops_tools.after_tax_returns
        args = {"url_or_id": "fixture:out-of-scope"}

    app = FastMCP(name=f"territory-opaque-preflight-{tool_name}")
    app.tool(name=tool_name)(tool)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool(tool_name, args)
    finally:
        uninstall()

    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _LIMITED_CONTEXT_FIXTURES)
@pytest.mark.parametrize("tool_name", _REQUEST_PROPERTY_RECORD_TOOLS)
@pytest.mark.parametrize("request_kind", ("out_of_scope", "incomplete"))
async def test_property_record_requests_fail_closed_before_execution(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    tool_name,
    request_kind,
):
    identity["ctx"] = request.getfixturevalue(context_fixture).model_copy(
        update={"territories": ("TX",)}
    )
    executions = [0]
    if request_kind == "out_of_scope":
        city: str | None = "Miami"
        state = "FL"
        zip_code = "33101"
        address = "90 Ocean Drive, Miami, FL 33101"
    else:
        city = None
        state = "TX"
        zip_code = "75201"
        address = "100 Main Street"

    app = FastMCP(name=f"territory-property-request-{tool_name}")
    if tool_name == "dedupe_listings":

        async def fixture(listings: list[dict[str, Any]]):
            del listings
            executions[0] += 1
            return _property_egress_payload(tool_name, "TX")

        args = {
            "listings": [
                {
                    "source": "fixture",
                    "source_id": "request",
                    "address": address,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                }
            ]
        }
    elif tool_name == "portfolio_owner_scan":

        async def fixture(
            records: list[dict[str, Any]] | None = None,
            min_properties: int = 2,
        ):
            del records, min_properties
            executions[0] += 1
            return _property_egress_payload(tool_name, "TX")

        args = {
            "records": [
                {
                    "owner_name": "Fixture Owner LLC",
                    "address": address,
                }
            ]
        }
    elif tool_name == "route_lead":

        async def fixture(
            listing: dict[str, Any],
            team: list[dict[str, Any]],
        ):
            del listing, team
            executions[0] += 1
            return _property_egress_payload(tool_name, "TX")

        args = {
            "listing": {
                "source_id": "request",
                "address": address,
                "city": city,
                "state": state,
                "zip_code": zip_code,
            },
            "team": [{"name": "Fixture", "mandates": []}],
        }
    elif tool_name == "find_arbitrage_opportunities":

        async def fixture(
            spaces: list[dict[str, Any]],
            achievable_sublease_psf: float | None = None,
        ):
            del spaces, achievable_sublease_psf
            executions[0] += 1
            return _property_egress_payload(tool_name, "TX")

        args = {
            "spaces": [
                {
                    "id": "request",
                    "address": address,
                    "city": city,
                    "state": state,
                    "zip_code": zip_code,
                    "building_sqft": 10000,
                    "master_rent_annual": 100000,
                    "achievable_sublease_psf": 20,
                }
            ]
        }
    else:

        async def fixture(listings: list[dict[str, Any]]):
            del listings
            executions[0] += 1
            return _property_egress_payload(tool_name, "TX")

        listing_payload = _listing(state=state).model_dump(mode="json")
        listing_payload.update(
            {
                "address": address,
                "city": city,
                "state": state,
                "zip_code": zip_code,
            }
        )
        args = {"listings": [listing_payload]}

    app.tool(name=tool_name)(fixture)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            with pytest.raises(ToolError, match="territor"):
                await client.call_tool(tool_name, args)
    finally:
        uninstall()

    assert executions == [0]
