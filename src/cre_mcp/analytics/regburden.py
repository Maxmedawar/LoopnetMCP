"""Static, cited regulatory-burden screening for major U.S. CRE markets.

This registry is intentionally a coarse triage aid.  The eviction labels are
explicit conventions rather than measured disposition times, and the presence
of a rule says nothing about whether a particular asset, tenancy, project, or
filing is covered.  Every known record exposes the snapshot date and official
sources so amendments can be checked before reliance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from importlib import import_module
import re
from typing import Any


LAST_VERIFIED = "2025-02-15"
UNKNOWN = "UNKNOWN"
LEGAL_CAVEAT = (
    "Static jurisdiction-level screening only; re-verify the current adopted law, "
    "coverage, exemptions, procedures, agency rules, and effective dates with local counsel."
)


def _source(identifier: str, label: str, citation: str, url: str) -> dict[str, str]:
    return {
        "id": identifier,
        "label": label,
        "citation": citation,
        "url": url,
    }


def _market(
    jurisdiction: str,
    *,
    rent_presence: str,
    rent_note: str,
    rent_source: dict[str, str],
    eviction_speed: str,
    eviction_note: str,
    eviction_source: dict[str, str],
    inclusionary_presence: str,
    inclusionary_note: str,
    inclusionary_source: dict[str, str],
    energy_presence: str,
    energy_note: str,
    energy_key: str | None,
    energy_source: dict[str, str] | None = None,
) -> dict[str, Any]:
    sources = [rent_source, eviction_source, inclusionary_source]
    if energy_source is not None:
        sources.append(energy_source)
    return {
        "jurisdiction": jurisdiction,
        "rent_control": {
            "presence": rent_presence,
            "note": rent_note,
            "source_ids": [rent_source["id"]],
        },
        "eviction_process_speed": {
            "convention": eviction_speed,
            "speed_convention": eviction_speed,
            "note": eviction_note,
            "basis": (
                "Qualitative judicial-process convention for initial underwriting triage; "
                "not an observed or promised case timeline."
            ),
            "source_ids": [eviction_source["id"]],
        },
        "inclusionary_requirements": {
            "presence": inclusionary_presence,
            "note": inclusionary_note,
            "source_ids": [inclusionary_source["id"]],
        },
        "building_performance_laws": {
            "presence": energy_presence,
            "note": energy_note,
            "energy_rules_registry_key": energy_key,
            "source_ids": (
                [energy_source["id"]]
                if energy_source is not None
                else [f"compliance.energy_rules:{energy_key}"]
                if energy_key is not None
                else []
            ),
        },
        "sources": sources,
        "last_verified": LAST_VERIFIED,
    }


REGULATORY_BURDEN_REGISTRY: dict[str, dict[str, Any]] = {
    "nyc": _market(
        "New York City, New York",
        rent_presence="PRESENT",
        rent_note="Rent stabilization applies to covered units; coverage is building- and unit-specific.",
        rent_source=_source(
            "nyc-rent",
            "NYC HPD — Rent Stabilization",
            "N.Y.C. Admin. Code §§ 26-501 et seq.; N.Y. Unconsol. Law §§ 8621 et seq.",
            "https://www.nyc.gov/site/hpd/services-and-information/rent-stabilization.page",
        ),
        eviction_speed="SLOWER",
        eviction_note="Judicial Housing Court process with predicate notices and case-specific defenses.",
        eviction_source=_source(
            "nyc-eviction",
            "New York City Housing Court — Starting a Case",
            "N.Y. Real Prop. Acts. Law art. 7 and applicable predicate-notice statutes",
            "https://www.nycourts.gov/courts/nyc/housing/startingcase.shtml",
        ),
        inclusionary_presence="PRESENT",
        inclusionary_note="Mandatory Inclusionary Housing applies in mapped areas; other programs are project-specific.",
        inclusionary_source=_source(
            "nyc-inclusionary",
            "NYC Planning — Mandatory Inclusionary Housing",
            "New York City Zoning Resolution §§ 23-154 and 23-90 et seq.",
            "https://www.nyc.gov/site/planning/plans/mih/mandatory-inclusionary-housing.page",
        ),
        energy_presence="PRESENT",
        energy_note="Local Law 97 building-emissions screen is cross-referenced to compliance.energy_rules.",
        energy_key="nyc",
    ),
    "los_angeles": _market(
        "Los Angeles, California",
        rent_presence="PRESENT",
        rent_note="The City Rent Stabilization Ordinance applies to covered rental units; exemptions and dates matter.",
        rent_source=_source(
            "la-rent",
            "Los Angeles Housing Department — Rent Stabilization Ordinance",
            "Los Angeles Municipal Code §§ 151.00 et seq.",
            "https://housing2.lacity.org/residents/rso-overview",
        ),
        eviction_speed="SLOWER",
        eviction_note="California unlawful-detainer litigation plus local just-cause and notice rules can add process steps.",
        eviction_source=_source(
            "la-eviction",
            "California Courts — Eviction",
            "Cal. Code Civ. Proc. §§ 1159-1179a; Los Angeles Municipal Code ch. XVI",
            "https://selfhelp.courts.ca.gov/eviction",
        ),
        inclusionary_presence="CONDITIONAL",
        inclusionary_note="Affordable-unit, fee, and incentive requirements depend on geography and development pathway.",
        inclusionary_source=_source(
            "la-inclusionary",
            "Los Angeles City Planning — Housing Initiatives",
            "Los Angeles Municipal Code § 19.18 and §§ 12.22 A.25, A.31",
            "https://planning.lacity.gov/plans-policies/housing-initiatives",
        ),
        energy_presence="BENCHMARKING_PRESENT",
        energy_note="California AB 802 is the available statewide cross-reference; local Los Angeles duties require separate review.",
        energy_key="california",
    ),
    "san_francisco": _market(
        "San Francisco, California",
        rent_presence="PRESENT",
        rent_note="The San Francisco Rent Ordinance applies to covered units and separately regulates specified evictions.",
        rent_source=_source(
            "sf-rent",
            "San Francisco Rent Board — Rent Ordinance",
            "San Francisco Administrative Code ch. 37",
            "https://www.sf.gov/information/about-rent-ordinance",
        ),
        eviction_speed="SLOWER",
        eviction_note="California unlawful detainer is judicial, with additional local just-cause requirements for covered tenancies.",
        eviction_source=_source(
            "sf-eviction",
            "San Francisco Rent Board — Evictions",
            "Cal. Code Civ. Proc. §§ 1159-1179a; San Francisco Administrative Code § 37.9",
            "https://www.sf.gov/information/evictions",
        ),
        inclusionary_presence="PRESENT",
        inclusionary_note="The Inclusionary Affordable Housing Program applies under project-size and pathway rules.",
        inclusionary_source=_source(
            "sf-inclusionary",
            "San Francisco Planning — Inclusionary Affordable Housing",
            "San Francisco Planning Code §§ 415 et seq.",
            "https://sfplanning.org/project/inclusionary-affordable-housing-program",
        ),
        energy_presence="BENCHMARKING_PRESENT",
        energy_note="California AB 802 is the available statewide cross-reference; San Francisco local rules are additive.",
        energy_key="california",
    ),
    "boston": _market(
        "Boston, Massachusetts",
        rent_presence="ABSENT",
        rent_note="Massachusetts generally preempts local rent control absent a later authorizing law.",
        rent_source=_source(
            "boston-rent",
            "Massachusetts General Laws — Rent Control Prohibition",
            "Mass. Gen. Laws ch. 40P",
            "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleVII/Chapter40P",
        ),
        eviction_speed="MODERATE",
        eviction_note="Summary process is judicial; notice grounds, tenancy type, and defenses determine actual timing.",
        eviction_source=_source(
            "boston-eviction",
            "Massachusetts Trial Court — Eviction",
            "Mass. Gen. Laws ch. 239 and Uniform Summary Process Rules",
            "https://www.mass.gov/eviction-for-landlords",
        ),
        inclusionary_presence="PRESENT",
        inclusionary_note="Boston's Inclusionary Development Policy applies to covered developments and zoning relief pathways.",
        inclusionary_source=_source(
            "boston-inclusionary",
            "Boston Planning Department — Inclusionary Development Policy",
            "Boston Zoning Code art. 79; current Inclusionary Development Policy",
            "https://www.bostonplans.org/housing/income-asset-and-program-limits/inclusionary-development-policy",
        ),
        energy_presence="PRESENT",
        energy_note="BERDO is cross-referenced to compliance.energy_rules.",
        energy_key="boston",
    ),
    "dc": _market(
        "District of Columbia",
        rent_presence="PRESENT",
        rent_note="The Rental Housing Act regulates rent for covered units, subject to exemptions and filings.",
        rent_source=_source(
            "dc-rent",
            "District of Columbia — Rent Control",
            "D.C. Code §§ 42-3501.01 et seq.",
            "https://dhcd.dc.gov/service/rent-control",
        ),
        eviction_speed="SLOWER",
        eviction_note="Possession actions are judicial and interact with statutory cause, notice, and tenant-protection rules.",
        eviction_source=_source(
            "dc-eviction",
            "DC Courts — Landlord and Tenant Branch",
            "D.C. Code §§ 16-1501 et seq. and 42-3505.01",
            "https://www.dccourts.gov/services/civil-matters/landlord-tenant",
        ),
        inclusionary_presence="PRESENT",
        inclusionary_note="Inclusionary Zoning applies to covered residential development and bonus-density rules.",
        inclusionary_source=_source(
            "dc-inclusionary",
            "DC Department of Housing — Inclusionary Zoning",
            "D.C. Code §§ 6-1041.01 et seq.; 11-C DCMR ch. 10",
            "https://dhcd.dc.gov/service/inclusionary-zoning-iz-affordable-housing-program",
        ),
        energy_presence="PRESENT",
        energy_note="DC BEPS is cross-referenced to compliance.energy_rules.",
        energy_key="dc",
    ),
    "chicago": _market(
        "Chicago, Illinois",
        rent_presence="ABSENT",
        rent_note="Illinois law preempts municipal rent control.",
        rent_source=_source(
            "chicago-rent",
            "Illinois Rent Control Preemption Act",
            "50 ILCS 825/1 et seq.",
            "https://www.ilga.gov/legislation/ilcs/ilcs3.asp?ActID=748&ChapterID=11",
        ),
        eviction_speed="MODERATE",
        eviction_note="Forcible-entry-and-detainer actions are judicial and Chicago notice protections may apply.",
        eviction_source=_source(
            "chicago-eviction",
            "Illinois Courts — Eviction",
            "735 ILCS 5/9-101 et seq.; Chicago Municipal Code § 5-12-130",
            "https://www.illinoiscourts.gov/forms/approved-forms/forms-approved-forms-circuit-court/eviction",
        ),
        inclusionary_presence="PRESENT",
        inclusionary_note="The Affordable Requirements Ordinance applies to covered residential projects and trigger events.",
        inclusionary_source=_source(
            "chicago-inclusionary",
            "Chicago Department of Housing — Affordable Requirements Ordinance",
            "Chicago Municipal Code § 2-44-085",
            "https://www.chicago.gov/city/en/depts/doh/provdrs/developers/svcs/aro.html",
        ),
        energy_presence="BENCHMARKING_PRESENT",
        energy_note="Chicago benchmarking exists but is not listed in compliance.energy_rules.",
        energy_key=None,
        energy_source=_source(
            "chicago-energy",
            "Chicago Energy Benchmarking",
            "Chicago Municipal Code § 18-14-101 et seq.",
            "https://www.chicago.gov/city/en/progs/env/building-energy-benchmarking---transparency.html",
        ),
    ),
    "seattle": _market(
        "Seattle, Washington",
        rent_presence="ABSENT",
        rent_note="Washington law preempts local regulation of rent amounts.",
        rent_source=_source(
            "seattle-rent",
            "Revised Code of Washington — Rent Regulation Preemption",
            "RCW 35.21.830",
            "https://app.leg.wa.gov/rcw/default.aspx?cite=35.21.830",
        ),
        eviction_speed="MODERATE",
        eviction_note="Unlawful detainer is judicial, with state and Seattle cause/notice protections affecting the path.",
        eviction_source=_source(
            "seattle-eviction",
            "Washington Courts — Eviction Resolution",
            "RCW ch. 59.12 and ch. 59.18; Seattle Municipal Code ch. 22.205",
            "https://www.courts.wa.gov/newsinfo/index.cfm?fa=newsinfo.EvictionResolutionProgram",
        ),
        inclusionary_presence="PRESENT",
        inclusionary_note="Mandatory Housing Affordability requirements apply in mapped multifamily and commercial zones.",
        inclusionary_source=_source(
            "seattle-inclusionary",
            "Seattle Office of Planning — Mandatory Housing Affordability",
            "Seattle Municipal Code chs. 23.58B and 23.58C",
            "https://www.seattle.gov/opcd/ongoing-initiatives/mandatory-housing-affordability",
        ),
        energy_presence="PRESENT",
        energy_note="Seattle Building Emissions Performance Standard exists but is not listed in compliance.energy_rules.",
        energy_key=None,
        energy_source=_source(
            "seattle-energy",
            "Seattle Building Emissions Performance Standard",
            "Seattle Municipal Code ch. 22.925",
            "https://www.seattle.gov/environment/climate-change/buildings-and-energy/building-emissions-performance-standard",
        ),
    ),
    "portland": _market(
        "Portland, Oregon",
        rent_presence="STATEWIDE_PRESENT",
        rent_note="Oregon's statewide annual rent-increase limit applies to covered tenancies; exemptions and current annual limits matter.",
        rent_source=_source(
            "portland-rent",
            "Oregon Revised Statutes — Rent Increases",
            "ORS 90.323",
            "https://www.oregonlegislature.gov/bills_laws/ors/ors090.html",
        ),
        eviction_speed="MODERATE",
        eviction_note="Residential possession is judicial and state/Portland relocation or cause rules may add prerequisites.",
        eviction_source=_source(
            "portland-eviction",
            "Oregon Judicial Department — Residential Eviction",
            "ORS chs. 90 and 105; Portland City Code ch. 30.01",
            "https://www.courts.oregon.gov/forms/Pages/residential-eviction.aspx",
        ),
        inclusionary_presence="PRESENT",
        inclusionary_note="Portland Inclusionary Housing applies to covered multifamily projects.",
        inclusionary_source=_source(
            "portland-inclusionary",
            "Portland Housing Bureau — Inclusionary Housing",
            "Portland City Code § 30.01.120",
            "https://www.portland.gov/phb/inclusionary-housing",
        ),
        energy_presence="BENCHMARKING_PRESENT",
        energy_note="Portland commercial-building energy reporting exists but is not listed in compliance.energy_rules.",
        energy_key=None,
        energy_source=_source(
            "portland-energy",
            "Portland Commercial Building Energy Reporting",
            "Portland City Code ch. 17.104",
            "https://www.portland.gov/bps/climate-action/energy-benchmarking",
        ),
    ),
    "denver": _market(
        "Denver, Colorado",
        rent_presence="ABSENT",
        rent_note="No local rent-control program is identified in this snapshot; verify later state or local changes.",
        rent_source=_source(
            "denver-rent",
            "Colorado Revised Statutes — Rent Control",
            "C.R.S. § 38-12-301",
            "https://leg.colorado.gov/sites/default/files/images/olls/crs2024-title-38.pdf",
        ),
        eviction_speed="MODERATE",
        eviction_note="Forcible entry and detainer is judicial; notice grounds and defenses determine timing.",
        eviction_source=_source(
            "denver-eviction",
            "Colorado Judicial Branch — Evictions",
            "C.R.S. §§ 13-40-101 et seq.",
            "https://www.coloradojudicial.gov/self-help/evictions",
        ),
        inclusionary_presence="PRESENT",
        inclusionary_note="Expanding Housing Affordability imposes affordability or fee obligations on covered development.",
        inclusionary_source=_source(
            "denver-inclusionary",
            "Denver Community Planning — Expanding Housing Affordability",
            "Denver Revised Municipal Code ch. 27, art. V",
            "https://www.denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Community-Planning-and-Development/Denver-Zoning-Code/Expanding-Housing-Affordability",
        ),
        energy_presence="PRESENT",
        energy_note="Energize Denver is cross-referenced to compliance.energy_rules.",
        energy_key="denver",
    ),
    "austin": _market(
        "Austin, Texas",
        rent_presence="ABSENT_WITH_NARROW_EXCEPTION",
        rent_note="Texas generally preempts municipal rent control except a narrow disaster route requiring state approval.",
        rent_source=_source(
            "austin-rent",
            "Texas Local Government Code — Rent Control",
            "Tex. Loc. Gov't Code § 214.902",
            "https://statutes.capitol.texas.gov/Docs/LG/htm/LG.214.htm",
        ),
        eviction_speed="FASTER",
        eviction_note="Convention reflects Texas's streamlined judicial possession framework, not a guaranteed timeline.",
        eviction_source=_source(
            "austin-eviction",
            "Texas Justice Court Rules — Eviction Cases",
            "Tex. Prop. Code ch. 24; Tex. R. Civ. P. 500-510",
            "https://www.txcourts.gov/rules-forms/rules-standards/",
        ),
        inclusionary_presence="CONDITIONAL_INCENTIVE_PROGRAMS",
        inclusionary_note="Affordability set-asides principally arise through elected density-bonus or incentive programs.",
        inclusionary_source=_source(
            "austin-inclusionary",
            "Austin Housing — Development Incentive Programs",
            "Austin Land Development Code §§ 4-18-1 et seq. and program-specific provisions",
            "https://www.austintexas.gov/department/development-incentives-and-agreements",
        ),
        energy_presence="AUDIT_AND_DISCLOSURE_PRESENT",
        energy_note="Austin ECAD is cross-referenced to compliance.energy_rules.",
        energy_key="austin",
    ),
    "miami": _market(
        "Miami, Florida",
        rent_presence="ABSENT_WITH_EMERGENCY_EXCEPTION",
        rent_note="Florida generally preempts local rent control outside a procedurally limited housing-emergency route.",
        rent_source=_source(
            "miami-rent",
            "Florida Statutes — Rent Control Preemption",
            "Fla. Stat. §§ 125.0103 and 166.043",
            "https://www.leg.state.fl.us/statutes/",
        ),
        eviction_speed="FASTER",
        eviction_note="Convention reflects Florida's summary judicial possession procedure, not a guaranteed case duration.",
        eviction_source=_source(
            "miami-eviction",
            "Florida Statutes — Landlord and Tenant",
            "Fla. Stat. §§ 83.20-83.251 and 83.56-83.62",
            "https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0000-0099/0083/0083.html",
        ),
        inclusionary_presence="CONDITIONAL",
        inclusionary_note="Workforce-housing obligations or incentives vary by Miami/Miami-Dade geography and elected program.",
        inclusionary_source=_source(
            "miami-inclusionary",
            "Miami-Dade Workforce Housing Development Program",
            "Miami-Dade County Code ch. 33, art. XIIA",
            "https://www.miamidade.gov/global/economy/building/workforce-housing-development-program.page",
        ),
        energy_presence="UNKNOWN",
        energy_note="No Miami-specific entry is listed in compliance.energy_rules; no local requirement is inferred.",
        energy_key=None,
    ),
    "atlanta": _market(
        "Atlanta, Georgia",
        rent_presence="ABSENT",
        rent_note="Georgia law preempts local regulation of rent amounts.",
        rent_source=_source(
            "atlanta-rent",
            "Georgia Code — Rent Regulation",
            "O.C.G.A. § 44-7-19",
            "https://law.justia.com/codes/georgia/title-44/chapter-7/article-1/section-44-7-19/",
        ),
        eviction_speed="FASTER",
        eviction_note="Convention reflects Georgia's dispossessory framework, not a guaranteed timeline or outcome.",
        eviction_source=_source(
            "atlanta-eviction",
            "Georgia Magistrate Courts — Dispossessory",
            "O.C.G.A. §§ 44-7-49 et seq.",
            "https://georgiamagistratecouncil.com/forms/",
        ),
        inclusionary_presence="PRESENT_IN_DESIGNATED_AREAS",
        inclusionary_note="Atlanta's inclusionary zoning applies in specified BeltLine and Westside overlay areas.",
        inclusionary_source=_source(
            "atlanta-inclusionary",
            "City of Atlanta — Inclusionary Zoning",
            "Atlanta Code of Ordinances ch. 54, art. IV",
            "https://www.atlantaga.gov/government/departments/city-planning/housing/inclusionary-zoning",
        ),
        energy_presence="BENCHMARKING_AND_AUDIT_PRESENT",
        energy_note="Atlanta CBEEO exists but is not listed in compliance.energy_rules.",
        energy_key=None,
        energy_source=_source(
            "atlanta-energy",
            "Atlanta Commercial Buildings Energy Efficiency Ordinance",
            "Atlanta Code of Ordinances ch. 75",
            "https://www.atlantaga.gov/government/departments/city-planning/office-of-buildings/commercial-buildings-energy-efficiency-ordinance",
        ),
    ),
}


JURISDICTION_ALIASES: dict[str, str] = {
    "nyc": "nyc",
    "new york": "nyc",
    "new york city": "nyc",
    "new york city ny": "nyc",
    "los angeles": "los_angeles",
    "los angeles ca": "los_angeles",
    "la": "los_angeles",
    "san francisco": "san_francisco",
    "san francisco ca": "san_francisco",
    "sf": "san_francisco",
    "boston": "boston",
    "boston ma": "boston",
    "dc": "dc",
    "washington dc": "dc",
    "district of columbia": "dc",
    "chicago": "chicago",
    "chicago il": "chicago",
    "seattle": "seattle",
    "seattle wa": "seattle",
    "portland": "portland",
    "portland or": "portland",
    "portland oregon": "portland",
    "denver": "denver",
    "denver co": "denver",
    "austin": "austin",
    "austin tx": "austin",
    "miami": "miami",
    "miami fl": "miami",
    "atlanta": "atlanta",
    "atlanta ga": "atlanta",
}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _load_energy_registry() -> tuple[Mapping[str, Any] | None, str | None]:
    """Read the compliance registry without making this module depend on its API."""

    try:
        module = import_module("cre_mcp.compliance.energy_rules")
        registry = getattr(module, "ENERGY_RULE_REGISTRY", None)
        if not isinstance(registry, Mapping):
            return None, "ENERGY_RULE_REGISTRY is unavailable or has an unrecognized shape"
        return registry, None
    except Exception as exc:  # availability metadata, never a hard dependency
        return None, f"compliance.energy_rules unavailable: {exc}"


def _energy_cross_reference(
    key: str | None,
    registry: Mapping[str, Any] | None,
    registry_issue: str | None,
) -> dict[str, Any]:
    base = {
        "module": "cre_mcp.compliance.energy_rules",
        "read_only": True,
        "registry_key": key,
    }
    if key is None:
        return {
            **base,
            "status": "NOT_LISTED",
            "note": "No compliance.energy_rules entry is claimed for this market.",
        }
    if registry is None:
        return {
            **base,
            "status": "REGISTRY_UNAVAILABLE",
            "note": registry_issue or "Energy-rule registry was unavailable.",
        }
    entry = registry.get(key)
    if not isinstance(entry, Mapping):
        return {
            **base,
            "status": "KEY_NOT_FOUND",
            "note": "The configured key is not present; no energy rule is inferred.",
        }
    return {
        **base,
        "status": "AVAILABLE",
        "program": entry.get("program"),
        "law": entry.get("law"),
        "last_verified": entry.get("last_verified"),
        "sources": deepcopy(entry.get("sources", [])),
    }


def _unknown_record(requested: str) -> dict[str, Any]:
    unknown_dimension = {
        "presence": UNKNOWN,
        "note": "Jurisdiction is not in the static regulatory-burden registry.",
        "source_ids": [],
    }
    return {
        "status": UNKNOWN,
        "requested_jurisdiction": requested,
        "jurisdiction": requested,
        "rent_control": deepcopy(unknown_dimension),
        "eviction_process_speed": {
            "convention": UNKNOWN,
            "speed_convention": UNKNOWN,
            "note": "Jurisdiction is not in the static regulatory-burden registry.",
            "basis": "No process-speed convention is inferred.",
            "source_ids": [],
        },
        "inclusionary_requirements": deepcopy(unknown_dimension),
        "building_performance_laws": {
            **deepcopy(unknown_dimension),
            "cross_reference": _energy_cross_reference(None, None, None),
        },
        "sources": [],
        "last_verified": None,
        "honesty": "UNKNOWN — obtain jurisdiction-specific legal and agency review.",
    }


def regulatory_burden(jurisdictions: Sequence[str] | None) -> dict[str, Any]:
    """Return registry screens for the requested jurisdiction names."""

    try:
        if jurisdictions is None or isinstance(jurisdictions, (str, bytes, Mapping)):
            raise ValueError("jurisdictions must be a sequence of jurisdiction names")
        if not jurisdictions:
            raise ValueError("jurisdictions must contain at least one name")
        registry, registry_issue = _load_energy_registry()
        results: list[dict[str, Any]] = []
        for index, requested in enumerate(jurisdictions):
            if not isinstance(requested, str) or not requested.strip():
                raise ValueError(
                    f"jurisdictions[{index}] must be a non-empty jurisdiction name"
                )
            key = JURISDICTION_ALIASES.get(_normalize(requested))
            if key is None:
                results.append(_unknown_record(requested))
                continue
            record = deepcopy(REGULATORY_BURDEN_REGISTRY[key])
            record["status"] = "KNOWN_REGISTRY_SCREEN"
            record["registry_key"] = key
            record["requested_jurisdiction"] = requested
            energy_key = record["building_performance_laws"].get(
                "energy_rules_registry_key"
            )
            record["building_performance_laws"]["cross_reference"] = (
                _energy_cross_reference(energy_key, registry, registry_issue)
            )
            record["honesty"] = LEGAL_CAVEAT
            results.append(record)

        unknown_count = sum(row["status"] == UNKNOWN for row in results)
        return {
            "status": "PARTIAL_UNKNOWN" if unknown_count else "REGISTRY_SCREEN",
            "results": results,
            "jurisdictions": results,
            "known_count": len(results) - unknown_count,
            "unknown_count": unknown_count,
            "registry_market_count": len(REGULATORY_BURDEN_REGISTRY),
            "unrecognized_inputs": [],
            "methodology": {
                "eviction_speed": (
                    "SLOWER/MODERATE/FASTER are qualitative process conventions, "
                    "not measured durations, service-level commitments, or predictions."
                ),
                "presence": (
                    "Presence is a jurisdiction-level flag and does not establish "
                    "asset-, unit-, tenancy-, project-, or filing-level applicability."
                ),
                "energy_cross_reference": (
                    "Read-only metadata from cre_mcp.compliance.energy_rules when a "
                    "registry key is available; absence never implies no law."
                ),
            },
            "last_verified": LAST_VERIFIED,
            "honesty": LEGAL_CAVEAT,
        }
    except Exception as exc:
        return {"error": f"regulatory_burden: {exc}"}


__all__ = [
    "JURISDICTION_ALIASES",
    "REGULATORY_BURDEN_REGISTRY",
    "regulatory_burden",
]
