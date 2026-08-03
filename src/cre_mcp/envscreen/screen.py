"""Federal environmental screening pipeline and REC-candidate conventions."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterable, Mapping
from typing import Any

from cre_mcp.envscreen.federal import (
    ECHO_SOURCE,
    FRS_PROGRAMS,
    FRS_SOURCE,
    echo_radius,
    frs_radius,
)
from cre_mcp.envscreen.hazards import (
    FEMA_SOURCE,
    USFS_SOURCE,
    USGS_DESIGN_SOURCE,
    USGS_QUAKE_SOURCE,
)
from cre_mcp.http.fetch import FetchClient

SOURCE_REGISTER = {
    "epa_envirofacts": {
        "name": "EPA Envirofacts",
        "url": "https://www.epa.gov/enviro/envirofacts-data-service-api",
        "auth": "None",
        "reliability": "A",
    },
    "epa_frs_arcgis": {
        "name": "EPA FRS ArcGIS",
        "url": "https://geodata.epa.gov/arcgis/rest/services/OEI/FRS_INTERESTS/MapServer",
        "auth": "None",
        "reliability": "A",
    },
    "epa_frs_rest": dict(FRS_SOURCE),
    "epa_ust_finder": {
        "name": "EPA UST Finder",
        "url": "https://www.epa.gov/ust/ust-finder",
        "auth": "None",
        "reliability": "B",
    },
    "epa_echo": dict(ECHO_SOURCE),
    "epa_acres": {
        "name": "EPA ACRES",
        "url": "https://geopub.epa.gov/arcgis/rest/services/EMEF/efpoints/MapServer/5",
        "auth": "None",
        "reliability": "A",
    },
    "tx_tceq_lpst": {
        "name": "TX TCEQ LPST",
        "url": "https://gis-tceq.opendata.arcgis.com/maps/TCEQ::lpst-points",
        "auth": "None",
        "reliability": "A",
    },
    "tx_tceq_dry_cleaner": {
        "name": "TX TCEQ Dry Cleaner",
        "url": "https://www.tceq.texas.gov/agency/data/lookup-data/drycleaners-data-records.html",
        "auth": "None",
        "reliability": "C",
    },
    "ca_geotracker": {
        "name": "CA GeoTracker",
        "url": "https://gispublic.waterboards.ca.gov/portalserver/rest/services/Geotracker",
        "auth": "None",
        "reliability": "A",
    },
    "ca_envirostor": {
        "name": "CA EnviroStor",
        "url": "https://www.envirostor.dtsc.ca.gov/public/data_download.asp",
        "auth": "None",
        "reliability": "A",
    },
    "fl_fdep_clm": {
        "name": "FL FDEP CLM",
        "url": "https://ca.dep.state.fl.us/arcgis/rest/services/Map_Direct/Environment/MapServer",
        "auth": "None",
        "reliability": "A",
    },
    "az_adeq": {
        "name": "AZ ADEQ",
        "url": "https://legacy.azdeq.gov/databases/lustsearch_drupal.html",
        "auth": "None",
        "reliability": "B",
    },
    "ga_epd_hsi": {
        "name": "GA EPD HSI",
        "url": "https://epd.georgia.gov/about-us/land-protection-branch/hazardous-waste/hazardous-site-inventory",
        "auth": "None",
        "reliability": "B",
    },
    "co_ops": {
        "name": "CO OPS",
        "url": "https://ops.colorado.gov/Petroleum/maps",
        "auth": "None",
        "reliability": "B",
    },
    "nv_ndep": {
        "name": "NV NDEP",
        "url": "https://ndep.nv.gov/environmental-cleanup/site-cleanup-program/site-cleanup-database",
        "auth": "None",
        "reliability": "C",
    },
    "nc_deq": {
        "name": "NC DEQ",
        "url": "https://data-ncdenr.opendata.arcgis.com/",
        "auth": "None",
        "reliability": "A",
    },
    "sanborn_loc": {
        "name": "Sanborn (LoC)",
        "url": "https://www.loc.gov/collections/sanborn-maps/",
        "auth": "None",
        "reliability": "D (auto) / B (manual)",
    },
    "usgs_earthexplorer": {
        "name": "USGS EarthExplorer",
        "url": "https://earthexplorer.usgs.gov/",
        "auth": "Free account for M2M",
        "reliability": "B",
    },
    "fema_nfhl": dict(FEMA_SOURCE),
    "usfs_whp": dict(USFS_SOURCE),
    "usgs_design_maps": dict(USGS_DESIGN_SOURCE),
    "usgs_earthquake_catalog": dict(USGS_QUAKE_SOURCE),
}

SEVERITY_CONVENTION = {
    "high": "SEMS, or confirmed RCRA corrective-action, at ON/ADJACENT distance (<=0.5 mi).",
    "review": "Other regulated-facility, dry-cleaner, violation, or enforcement signal requiring record review.",
    "context": "TRI/NPDES presence is regulatory context, not proof of a REC or contamination.",
    "informational": "ECHO presence without a stronger contamination signal.",
}

UNCOVERABLE_GAPS = {
    "site_reconnaissance": "No free API can observe stained soil, tanks/vents, PCB transformers, floor drains, distressed vegetation, or other site-walk conditions.",
    "historical_use": "Occupancy history, post-1930 Sanborns, interpreted historic aerials, and former gas-station/dry-cleaner use are not established by this screen.",
    "chain_of_title": "Prior owners and deed history require county and professional title research.",
    "interviews": "Current and past owners, occupants, and local officials have not been interviewed.",
    "regulatory_file_review": "Agency paper/electronic case files, closure conditions, contaminant details, and state-only records have not been reviewed.",
    "plume_and_vapor_reasoning": "Groundwater flow, plume direction, vapor encroachment/intrusion, and ASTM E2600 reasoning are not visible to free radius APIs.",
    "data_currency_and_coverage": "Federal and state feeds can lag, omit historic facilities, and contain imprecise coordinates; a null is not evidence of a clean property.",
    "non_scope_items": "Asbestos, lead paint, mold, radon, wetlands, endangered species, and cultural resources are not resolved here.",
}


def _validate_radii(radii: Iterable[float]) -> list[float]:
    normalized = sorted({float(radius) for radius in radii})
    if not normalized:
        raise ValueError("radii must contain at least one radius")
    if any(not math.isfinite(radius) or radius <= 0 or radius > 5 for radius in normalized):
        raise ValueError("each radius must be greater than 0 and at most 5 miles")
    return normalized


def _merge_flag_value(left: Any, right: Any) -> Any:
    if left is None:
        return right
    if right is None:
        return left
    if isinstance(left, bool) and isinstance(right, bool):
        return left or right
    if isinstance(left, list) and isinstance(right, list):
        return sorted({str(value) for value in left + right})
    return left


def dedupe_hits(hits: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe registry IDs, retaining minimum distance and merged citations."""
    deduped: dict[str, dict[str, Any]] = {}
    anonymous = 0
    for raw in hits:
        hit = dict(raw)
        registry_id = hit.get("registry_id")
        if registry_id:
            key = f"registry:{registry_id}"
        else:
            anonymous += 1
            key = f"anonymous:{anonymous}:{hit.get('source')}:{hit.get('name')}"
        program = str(hit.get("program") or "UNKNOWN")
        source = str(hit.get("source") or "Unknown source")
        flags = dict(hit.get("flags") or {})
        if key not in deduped:
            hit["programs"] = sorted(
                {program, *(str(value) for value in flags.get("programs", []))}
            )
            hit["source_citations"] = [
                {
                    "source": source,
                    "source_url": hit.get("source_url"),
                    "distance_mi": hit.get("distance_mi"),
                }
            ]
            deduped[key] = hit
            continue
        current = deduped[key]
        current_distance = float(current.get("distance_mi", math.inf))
        new_distance = float(hit.get("distance_mi", math.inf))
        if new_distance < current_distance:
            for field in (
                "name",
                "program",
                "distance_mi",
                "source",
                "source_url",
                "coordinates",
            ):
                current[field] = hit.get(field)
        current["programs"] = sorted(
            {
                *current.get("programs", []),
                program,
                *(str(value) for value in flags.get("programs", [])),
            }
        )
        existing_flags = dict(current.get("flags") or {})
        for flag, value in flags.items():
            existing_flags[flag] = _merge_flag_value(existing_flags.get(flag), value)
        current["flags"] = existing_flags
        citation = {
            "source": source,
            "source_url": hit.get("source_url"),
            "distance_mi": hit.get("distance_mi"),
        }
        if citation not in current["source_citations"]:
            current["source_citations"].append(citation)
    return sorted(
        deduped.values(),
        key=lambda item: (float(item.get("distance_mi", math.inf)), str(item.get("name"))),
    )


def _proximity(distance_mi: float) -> str:
    if distance_mi <= 0.25:
        return "ON"
    if distance_mi <= 0.5:
        return "ADJACENT"
    return "NEARBY"


def rec_candidate(hit: Mapping[str, Any]) -> dict[str, Any]:
    """Apply transparent screening labels; these are not ASTM REC determinations."""
    distance = float(hit.get("distance_mi", math.inf))
    proximity = _proximity(distance)
    flags = dict(hit.get("flags") or {})
    programs = {str(value).upper() for value in hit.get("programs", [])}
    programs.add(str(hit.get("program") or "").upper())
    high_signal = proximity in {"ON", "ADJACENT"} and (
        "SEMS" in programs
        or ("RCRAINFO" in programs and flags.get("corrective_action") is True)
    )
    context_only = bool(programs.intersection({"TRIS", "NPDES"}))
    review_signal = bool(
        flags.get("dry_cleaner_naics")
        or flags.get("current_violation")
        or flags.get("formal_enforcement_5yr")
        or "ACRES" in programs
        or "RCRAINFO" in programs
    )
    if high_signal:
        severity = "high"
        basis = SEVERITY_CONVENTION["high"]
    elif review_signal:
        severity = "review"
        basis = SEVERITY_CONVENTION["review"]
    elif context_only:
        severity = "context"
        basis = SEVERITY_CONVENTION["context"]
    else:
        severity = "informational"
        basis = SEVERITY_CONVENTION["informational"]
    return {
        "name": hit.get("name"),
        "registry_id": hit.get("registry_id"),
        "programs": sorted(program for program in programs if program),
        "distance_mi": distance,
        "proximity": proximity,
        "severity": severity,
        "severity_basis": basis,
        "severity_is_screening_convention": True,
        "flags": flags,
        "source_citations": list(hit.get("source_citations") or []),
    }


async def environmental_screen(
    lat: float,
    lon: float,
    radii: Iterable[float] = frozenset({0.25, 0.5, 1.0}),
    *,
    fetch: FetchClient | None = None,
) -> dict[str, Any]:
    """Run federal ring searches and return a qualified REC-candidate memo."""
    latitude = float(lat)
    longitude = float(lon)
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("latitude must be finite and between -90 and 90")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("longitude must be finite and between -180 and 180")
    radius_values = _validate_radii(radii)

    tasks = []
    for radius in radius_values:
        tasks.extend(
            frs_radius(latitude, longitude, radius, program, fetch=fetch)
            for program in FRS_PROGRAMS
        )
        tasks.append(echo_radius(latitude, longitude, radius, fetch=fetch))
    source_results = list(await asyncio.gather(*tasks))
    normalized_hits = [
        hit
        for result in source_results
        if result["status"] == "hit"
        for hit in result["hits"]
    ]
    federal_hits = dedupe_hits(normalized_hits)
    candidates = [rec_candidate(hit) for hit in federal_hits]
    queried = [result["query_id"] for result in source_results]
    null = [
        result["query_id"]
        for result in source_results
        if result["status"] == "null"
    ]
    failed = [
        result["query_id"]
        for result in source_results
        if result["status"] == "query_failed"
    ]
    return {
        "report_type": "PRE-PHASE-I ENVIRONMENTAL SCREEN",
        "phase_i_substitute": False,
        "disclaimer": "This automated screen is not a Phase I ESA and does not make ASTM E1527-21 REC determinations.",
        "location": {"lat": latitude, "lon": longitude},
        "radii_mi": radius_values,
        "pipeline": {
            "geocode_and_parcel_resolution": "coordinates supplied; parcel geometry not resolved by this substrate",
            "federal_spatial_sweep": "completed with explicit per-query status",
            "deep_record_lookup": "not performed by this substrate",
            "state_overlay": "not performed by this substrate",
            "physical_hazards": "available separately through hazard_profile",
            "historical_signal": "current NAICS 812310/812320 only when returned by FRS/ECHO",
            "score_and_format": "REC candidates labeled under the disclosed screening severity convention",
        },
        "source_register": SOURCE_REGISTER,
        "source_results": source_results,
        "sources_queried": queried,
        "sources_null": null,
        "sources_failed": failed,
        "source_failures": [
            {"query_id": result["query_id"], "error": result["error"]}
            for result in source_results
            if result["status"] == "query_failed"
        ],
        "federal_hits": federal_hits,
        "rec_candidates": candidates,
        "severity_convention": SEVERITY_CONVENTION,
        "uncoverable_gaps": dict(UNCOVERABLE_GAPS),
    }


__all__ = [
    "SEVERITY_CONVENTION",
    "SOURCE_REGISTER",
    "UNCOVERABLE_GAPS",
    "dedupe_hits",
    "environmental_screen",
    "rec_candidate",
]
