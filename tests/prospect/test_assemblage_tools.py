"""Network-free tests for assemblage math, ArcGIS flow, and tool boundaries."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.models.geo import GeoLevel, GeoRef
from cre_mcp.prospect.assemblage import adjacent_parcels, fragmentation_report


def _polygon(xmin: float, ymin: float, xmax: float, ymax: float) -> dict:
    return {
        "rings": [
            [
                [xmin, ymin],
                [xmax, ymin],
                [xmax, ymax],
                [xmin, ymax],
                [xmin, ymin],
            ]
        ],
        "spatialReference": {"wkid": 4326},
    }


def _feature(parcel_id: str, owner: str, xmin: float) -> dict:
    return {
        "PARCEL_ID": parcel_id,
        "NAME": owner,
        "SITUS_ADD_DOR": f"{parcel_id} TEST ST",
        "ZONING": "C2",
        "_geometry": _polygon(xmin, 34.5, xmin + 0.001, 34.501),
    }


def test_fragmentation_math_normalizes_owners_and_exposes_sequence_basis():
    result = fragmentation_report(
        [
            {"parcel_id": "1", "owner_name": "Alpha Holdings, LLC"},
            {"parcel_id": "2", "owner_name": "ALPHA HOLDINGS LLC"},
            {"parcel_id": "3", "owner_name": "Beta Partners"},
            {"parcel_id": "4", "owner_name": None},
        ]
    )

    assert result["label"] == "HEURISTIC"
    assert result["parcel_count"] == 4
    assert result["distinct_owners"] == 2
    assert result["unknown_owner_count"] == 1
    assert result["largest_contiguous_same_owner_run"] == 2
    assert result["largest_run_owner"] == "Alpha Holdings, LLC"
    assert "supplied parcel order" in result["heuristic_basis"]


def test_fragmentation_geometry_does_not_join_separated_same_owner_parcels():
    result = fragmentation_report(
        [
            {
                "parcel_id": "1",
                "owner_name": "Alpha LLC",
                "geometry": _polygon(-112.0, 34.0, -111.999, 34.001),
            },
            {
                "parcel_id": "2",
                "owner_name": "Alpha LLC",
                "geometry": _polygon(-111.990, 34.0, -111.989, 34.001),
            },
        ]
    )

    assert result["contiguity_method"] == "touching_or_overlapping_geometry_bounds"
    assert result["largest_contiguous_same_owner_run"] == 1


@pytest.mark.asyncio
async def test_adjacent_parcels_envelope_queries_configured_owner_provider():
    subject = _feature("P1", "ALPHA LLC", -112.0)
    same_owner = _feature("P2", "Alpha, LLC", -111.999)
    other_owner = _feature("P3", "BETA LLC", -111.998)
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="04",
        county_fips="04025",
        name="Yavapai County, AZ",
    )

    with (
        patch(
            "cre_mcp.prospect.assemblage.resolve",
            new=AsyncMock(return_value=geo),
        ),
        patch(
            "cre_mcp.prospect.assemblage.arcgis_query",
            new=AsyncMock(side_effect=[[subject], [subject, same_owner, other_owner]]),
        ) as query,
    ):
        result = await adjacent_parcels(parcel_id="P1", county="Yavapai County, AZ")

    assert result["label"] == "HEURISTIC"
    assert result["adjacency_query_method"] == (
        "subject_geometry_envelope_intersection"
    )
    assert result["neighbor_count"] == 2
    assert [row["owner_name"] for row in result["neighbors"]] == [
        "Alpha, LLC",
        "BETA LLC",
    ]
    assert result["fragmentation_report"]["distinct_owners"] == 2
    assert result["fragmentation_report"]["largest_contiguous_same_owner_run"] == 2
    assert "verify legal adjacency" in result["verification"]
    subject_call, neighbor_call = query.await_args_list
    assert subject_call.kwargs["return_geometry"] is True
    assert neighbor_call.kwargs["geometry"]["spatialReference"] == {"wkid": 4326}
    assert neighbor_call.kwargs["return_geometry"] is True


@pytest.mark.asyncio
async def test_find_adjacent_parcels_boundary_returns_error_dictionary():
    from cre_mcp.prospect.tools import find_adjacent_parcels

    result = await find_adjacent_parcels(lat=30.0, county="Travis County, TX")
    assert result == {"error": "lat and lon must be supplied together"}


def test_plain_tool_boundaries_are_explicit_and_capture_errors():
    from cre_mcp.prospect import tools

    assert tools.sale_leaseback_candidates(None)["record_count"] == 0
    assert tools.portfolio_owner_scan(None)["record_count"] == 0
    assert tools.adjust_rent_comp(None, None)["error"]
    stalled = tools.stalled_project_signals([], as_of=date(2026, 7, 14))
    assert stalled["signals"] == []
    assert tools.micro_location_score(None)["missing_factors"]
