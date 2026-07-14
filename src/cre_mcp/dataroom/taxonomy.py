"""Explicit commercial-real-estate document taxonomies by deal type.

The taxonomy is a grading convention, not a legal opinion.  Required items are
included in completeness scoring.  Conditional items are included only after
their trigger is known to apply (represented by a non-``missing`` item status).
"""

from __future__ import annotations

from typing import Literal, TypedDict

DealType = Literal["retail_nnn", "multifamily", "office", "industrial", "land"]
Phase = Literal["loi", "diligence", "financing", "closing"]
Requirement = Literal["required", "conditional"]

DEAL_TYPES: tuple[DealType, ...] = (
    "retail_nnn",
    "multifamily",
    "office",
    "industrial",
    "land",
)
PHASES: tuple[Phase, ...] = ("loi", "diligence", "financing", "closing")


class DocumentRequirement(TypedDict):
    """One transparent row in a deal-type document taxonomy."""

    doc_key: str
    label: str
    phase: Phase
    requirement: Requirement
    required: bool
    trigger: str | None
    why_it_matters: str
    what_missing_costs: str


def _doc(
    doc_key: str,
    label: str,
    phase: Phase,
    why_it_matters: str,
    what_missing_costs: str,
    *,
    trigger: str | None = None,
) -> DocumentRequirement:
    requirement: Requirement = "conditional" if trigger else "required"
    return {
        "doc_key": doc_key,
        "label": label,
        "phase": phase,
        "requirement": requirement,
        "required": requirement == "required",
        "trigger": trigger,
        "why_it_matters": why_it_matters,
        "what_missing_costs": what_missing_costs,
    }


def _income_property_documents(
    *,
    estoppel_trigger: str | None = None,
) -> tuple[DocumentRequirement, ...]:
    """Documents common to stabilized or leased income-property acquisitions."""

    return (
        _doc(
            "offering_memorandum", "Offering memorandum", "loi",
            "Frames the seller's marketed tenancy, economics, and property facts.",
            "Missing baseline marketing claims slows initial underwriting and later variance checks.",
        ),
        _doc(
            "purchase_sale_agreement", "Executed purchase and sale agreement", "diligence",
            "Controls deadlines, access rights, deliverables, remedies, and closing conditions.",
            "Missing governing terms can cause missed termination rights or an accidental hard deposit.",
        ),
        _doc(
            "seller_disclosures", "Seller and property disclosures", "diligence",
            "Surfaces known defects, disputes, notices, and prior conditions.",
            "Undisclosed issues can become late retrades, claims, or unpriced capital work.",
        ),
        _doc(
            "t12_operating_statement", "Trailing-12 operating statement", "loi",
            "Tests current income and expenses against marketed NOI.",
            "Missing actuals leaves valuation dependent on an unverified pro forma.",
        ),
        _doc(
            "historical_financials", "Three years of operating statements", "diligence",
            "Shows seasonality, recurring expense levels, and trend breaks.",
            "Missing history hides volatility and weakens normalized-NOI support.",
        ),
        _doc(
            "rent_roll", "Current certified rent roll", "loi",
            "Defines occupied area, rent, term, options, deposits, and arrears.",
            "Missing tenancy detail can overstate rent, occupancy, and durable value.",
        ),
        _doc(
            "all_leases", "All leases and guaranties", "diligence",
            "Executed language, not the rent roll, establishes rent and tenant obligations.",
            "Missing leases can conceal termination rights, caps, options, or weak guaranties.",
        ),
        _doc(
            "lease_amendments", "All lease amendments and side letters", "diligence",
            "Later agreements can override economics and remedies in the original lease.",
            "A missing amendment can make abstraction and underwriting materially wrong.",
            trigger="Any lease has been amended, assigned, renewed, or supplemented by a side letter.",
        ),
        _doc(
            "tenant_ledgers", "Tenant ledgers and receivables aging", "diligence",
            "Validates collections, concessions, credits, and delinquency.",
            "Missing ledgers can turn contractual rent into overstated collectible rent.",
        ),
        _doc(
            "estoppels", "Tenant estoppel certificates", "diligence",
            "Confirms lease facts, defaults, deposits, and tenant claims directly with occupants.",
            "Missing estoppels can fail a lender or PSA condition and force a closing delay or retrade.",
            trigger=estoppel_trigger,
        ),
        _doc(
            "sndas", "SNDAs and nondisturbance agreements", "financing",
            "Aligns tenant rights with the new lender's lien and foreclosure remedies.",
            "Missing required SNDAs can hold up loan approval or jeopardize key-tenant continuity.",
            trigger="The lender, PSA, or a tenant lease requires an SNDA or recognition agreement.",
        ),
        _doc(
            "service_contracts", "Service, maintenance, and management contracts", "diligence",
            "Reveals assumable obligations, termination windows, and true operating costs.",
            "Missing contracts can leave uncancelled obligations or understated expenses.",
        ),
        _doc(
            "utility_bills", "Utility bills and usage history", "diligence",
            "Supports expense normalization and identifies unusual consumption.",
            "Missing usage data obscures leaks, owner-paid loads, and budget variance.",
        ),
        _doc(
            "tax_bills", "Real-estate tax bills and assessments", "diligence",
            "Confirms current burden, parcels, exemptions, and delinquency.",
            "Missing bills can understate reassessed taxes or leave liens unresolved.",
        ),
        _doc(
            "insurance_loss_runs", "Insurance loss runs", "diligence",
            "Claims history affects insurability, premiums, and hidden physical risk.",
            "Missing loss history can cause late premium shocks or carrier declinations.",
        ),
        _doc(
            "property_insurance_policy", "Current property insurance policy", "financing",
            "Shows limits, exclusions, deductibles, and lender-compliance gaps.",
            "Missing coverage evidence can prevent loan funding and leave risks unpriced.",
        ),
        _doc(
            "tenant_cois", "Tenant certificates of insurance", "diligence",
            "Evidence of tenant coverage helps test compliance with lease risk allocation.",
            "Missing COIs leave uninsured tenant-caused losses and defaults unidentified.",
            trigger="Leases require tenants to maintain insurance and deliver evidence.",
        ),
        _doc(
            "title_commitment", "Title commitment", "diligence",
            "Identifies vesting, liens, exceptions, and requirements to issue the owner's policy.",
            "Missing title work compresses cure time and can leave liens or access defects at closing.",
        ),
        _doc(
            "title_exception_documents", "Title exception documents", "diligence",
            "The underlying instruments define easements, restrictions, and use limitations.",
            "Missing exception instruments makes title review superficial and can hide material burdens.",
        ),
        _doc(
            "alta_survey", "Current ALTA/NSPS survey", "diligence",
            "Plots boundaries, access, easements, encroachments, and improvements against title.",
            "Missing ALTA work can leave title gaps, access defects, or encroachments for closing.",
        ),
        _doc(
            "phase_i", "Phase I environmental site assessment", "diligence",
            "Supports the innocent-landowner defense and identifies recognized environmental conditions.",
            "Missing or stale Phase I work can create cleanup exposure and lender refusal.",
        ),
        _doc(
            "phase_ii", "Phase II environmental investigation", "diligence",
            "Sampling defines whether a recognized condition is real and financially bounded.",
            "Skipping indicated testing can leave contamination unquantified and unfinanceable.",
            trigger="The Phase I identifies a REC, data gap, or other condition requiring sampling.",
        ),
        _doc(
            "pca", "Property condition assessment", "diligence",
            "Provides independent near-term and reserve capital requirements.",
            "Missing physical diligence can produce immediate capex misses and lender conditions.",
        ),
        _doc(
            "zoning_report", "Zoning report or zoning verification letter", "diligence",
            "Confirms legal use, setbacks, parking, and rebuild status.",
            "Missing zoning evidence can leave a nonconforming or non-rebuildable asset unpriced.",
        ),
        _doc(
            "certificates_of_occupancy", "Certificates of occupancy", "diligence",
            "Evidence of lawful occupancy is central to continued operation and lending.",
            "Missing COs can trigger code work, tenant disruption, or a lender condition.",
        ),
        _doc(
            "appraisal", "Lender appraisal", "financing",
            "Supports collateral value and loan sizing.",
            "Missing or delayed appraisal can reduce proceeds or miss the financing deadline.",
        ),
        _doc(
            "loan_commitment", "Executed loan commitment", "financing",
            "Fixes proceeds, conditions, pricing, recourse, and expiration.",
            "Missing binding terms leaves the capital stack and closing certainty unresolved.",
        ),
        _doc(
            "lender_closing_checklist", "Lender closing checklist", "financing",
            "Makes every funding condition and responsible party visible.",
            "An untracked condition can surface after the deposit goes hard and delay funding.",
        ),
        _doc(
            "buyer_entity_authority", "Buyer entity and authority documents", "closing",
            "Confirms the buyer exists and signatories can bind it.",
            "Missing authority documents can stop execution, escrow, or loan funding.",
        ),
        _doc(
            "loan_payoff", "Seller loan payoff and release documentation", "closing",
            "Clears monetary liens and establishes closing cash requirements.",
            "Missing payoff evidence can prevent clean title and timely recording.",
        ),
        _doc(
            "settlement_statement", "Settlement statement and prorations", "closing",
            "Reconciles purchase price, credits, deposits, taxes, rent, and closing costs.",
            "Missing review can produce expensive proration errors or an incorrect wire.",
        ),
        _doc(
            "deed", "Approved deed", "closing",
            "Transfers the intended estate from the correct vesting party.",
            "A missing or defective deed prevents recordable conveyance.",
        ),
        _doc(
            "closing_escrow_instructions", "Joint closing and escrow instructions", "closing",
            "Controls document release, recording, and disbursement conditions.",
            "Missing aligned instructions creates funding, release, and wire-control risk.",
        ),
    )


RETAIL_NNN_DOCUMENTS = _income_property_documents() + (
    _doc(
        "cam_reconciliations", "CAM and tax reconciliations", "diligence",
        "Tests reimbursements and unresolved tenant credits under the lease.",
        "Missing reconciliations can overstate NNN recoveries and inherit tenant disputes.",
    ),
    _doc(
        "roof_hvac_warranties", "Roof and HVAC warranties", "diligence",
        "Shows remaining coverage for two major retail capital exposures.",
        "Missing warranties can shift near-term repair cost entirely to the buyer.",
        trigger="Seller or tenant represents that transferable roof or HVAC warranties exist.",
    ),
    _doc(
        "tenant_financials", "Tenant and guarantor financials", "diligence",
        "Supports credit assessment behind a long-duration income stream.",
        "Missing credit evidence can hide a weak guarantor and misprice cap-rate risk.",
    ),
    _doc(
        "franchise_agreements", "Franchise and operator agreements", "diligence",
        "Operator rights and brand termination can affect site continuity and credit.",
        "Missing brand agreements can conceal termination or change-of-control risk.",
        trigger="The tenant operates under a franchise, license, or branded operator agreement.",
    ),
    _doc(
        "reciprocal_easement_agreement", "REA and shopping-center declarations", "diligence",
        "Allocates access, parking, maintenance, signage, and shared costs.",
        "Missing REA terms can impair access or create uncapped shared obligations.",
        trigger="The parcel shares access, parking, signage, or facilities with another parcel.",
    ),
)


MULTIFAMILY_DOCUMENTS = _income_property_documents(
    estoppel_trigger="The PSA, lender, or diligence plan calls for tenant estoppels or a sampled confirmation program.",
) + (
    _doc(
        "unit_inspection_report", "Unit-by-unit inspection report", "diligence",
        "Validates occupancy, condition, concessions, and deferred maintenance by unit.",
        "Missing unit access can hide vacancy, damage, and renovation scope.",
    ),
    _doc(
        "delinquency_report", "Delinquency and bad-debt report", "diligence",
        "Separates billed rent from collectible cash and recurring loss.",
        "Missing delinquency data overstates effective rent and resident quality.",
    ),
    _doc(
        "security_deposit_ledger", "Security-deposit ledger and bank evidence", "diligence",
        "Establishes resident liabilities that must transfer at closing.",
        "Missing deposit records can create post-closing resident claims and cash shortfalls.",
    ),
    _doc(
        "resident_policy_addenda", "Resident policies and standard addenda", "diligence",
        "Defines fees, utilities, pets, parking, and recurring resident obligations.",
        "Missing addenda can make ancillary-income and compliance assumptions unreliable.",
    ),
    _doc(
        "rental_licenses", "Rental licenses and inspection certificates", "diligence",
        "Confirms authority to operate units and known code conditions.",
        "Missing licenses can lead to fines, rent restrictions, or forced remediation.",
    ),
    _doc(
        "regulatory_agreements", "Affordable-housing regulatory agreements", "diligence",
        "Controls rents, tenant eligibility, transfers, and compliance periods.",
        "Missing restrictions can invalidate market-rent assumptions and delay approvals.",
        trigger="The property has affordable units, subsidies, tax credits, bonds, or recorded use restrictions.",
    ),
)


OFFICE_DOCUMENTS = _income_property_documents() + (
    _doc(
        "cam_reconciliations", "Operating-expense reconciliations", "diligence",
        "Validates base years, stops, gross-ups, exclusions, and tenant credits.",
        "Missing reconciliations can materially overstate recoveries and NOI.",
    ),
    _doc(
        "tenant_improvement_obligations", "TI and leasing-commission obligations", "diligence",
        "Quantifies unfunded concessions and broker payments under signed leases.",
        "Missing schedules can create major post-closing cash calls.",
    ),
    _doc(
        "space_measurements", "BOMA measurements and stacking plan", "diligence",
        "Supports rentable area, load factors, vacancy, and tenant premises.",
        "Missing measurements can distort rent per foot and leased-area calculations.",
    ),
    _doc(
        "building_system_reports", "Elevator, life-safety, and major-system reports", "diligence",
        "Shows compliance and condition of systems material to office occupancy.",
        "Missing reports can conceal shutdown risk and near-term modernization cost.",
    ),
    _doc(
        "parking_agreements", "Parking leases and allocation records", "diligence",
        "Parking supply and rights can drive tenant demand and separate income.",
        "Missing rights can impair leasing and overstate parking revenue.",
        trigger="Parking is leased, shared, separately operated, or allocated by tenant agreement.",
    ),
)


INDUSTRIAL_DOCUMENTS = _income_property_documents() + (
    _doc(
        "environmental_compliance_records", "Environmental permits and compliance records", "diligence",
        "Industrial uses may create regulated storage, discharge, or waste obligations.",
        "Missing records can hide violations, cleanup cost, or operational restrictions.",
        trigger="Current or prior operations used regulated materials or required environmental permits.",
    ),
    _doc(
        "fire_sprinkler_reports", "Fire-sprinkler and suppression reports", "diligence",
        "Confirms protection level, inspections, and warehouse-use compatibility.",
        "Missing reports can cause insurer or fire-marshal conditions and capex.",
    ),
    _doc(
        "dock_equipment_records", "Dock, door, and material-handling equipment records", "diligence",
        "Documents condition of operationally critical loading infrastructure.",
        "Missing records can hide immediate repair cost and tenant disruption.",
    ),
    _doc(
        "roof_warranty", "Roof warranty and repair history", "diligence",
        "Large industrial roofs are a concentrated capital and water-intrusion risk.",
        "Missing history can leave a seven-figure replacement or claim unpriced.",
    ),
    _doc(
        "rail_access_agreements", "Rail spur and access agreements", "diligence",
        "Controls continued rail access, maintenance, and liability allocation.",
        "Missing rights can eliminate a material operating feature.",
        trigger="The property is marketed with active or potential rail service.",
    ),
)


LAND_DOCUMENTS: tuple[DocumentRequirement, ...] = (
    _doc(
        "offering_memorandum", "Offering memorandum or land package", "loi",
        "Provides the seller's acreage, use, access, and entitlement claims.",
        "Missing baseline claims slows site screening and later variance checks.",
    ),
    _doc(
        "purchase_sale_agreement", "Executed purchase and sale agreement", "diligence",
        "Controls feasibility, access, extension, termination, and closing rights.",
        "Missing terms can cause lost feasibility rights or an accidental hard deposit.",
    ),
    _doc(
        "vesting_deed", "Current vesting deed", "loi",
        "Confirms the estate, grantor, legal description, and prior reservations.",
        "Missing vesting evidence can mean negotiating with the wrong party or acreage.",
    ),
    _doc(
        "title_commitment", "Title commitment", "diligence",
        "Identifies liens, mineral reservations, easements, and issuance requirements.",
        "Missing title work compresses cure time and can leave unbuildable burdens.",
    ),
    _doc(
        "title_exception_documents", "Title exception documents", "diligence",
        "Recorded instruments define access, utilities, restrictions, and third-party rights.",
        "Missing instruments can hide fatal use or development constraints.",
    ),
    _doc(
        "alta_survey", "ALTA/NSPS land-title survey", "diligence",
        "Reconciles boundaries, access, easements, encroachments, and legal description.",
        "Missing survey work can leave acreage, access, and title gaps at closing.",
    ),
    _doc(
        "boundary_topographic_survey", "Boundary and topographic survey", "diligence",
        "Defines slopes, features, and usable site geometry for concept planning.",
        "Missing terrain data can overstate buildable area and site yield.",
    ),
    _doc(
        "zoning_letter", "Zoning verification letter", "loi",
        "Confirms current district and permitted-use framework.",
        "Missing verification can anchor value to a use that is not allowed.",
    ),
    _doc(
        "zoning_code_excerpts", "Applicable zoning code and overlays", "diligence",
        "Controls density, height, setbacks, parking, and approval path.",
        "Missing rules can invalidate the concept plan and residual land value.",
    ),
    _doc(
        "entitlement_approvals", "Existing entitlement approvals and conditions", "diligence",
        "Defines vested rights, conditions, expiration, and remaining approvals.",
        "Missing approvals can make represented entitlements unusable or expired.",
        trigger="Seller represents that zoning, site-plan, subdivision, or other entitlements exist.",
    ),
    _doc(
        "development_agreement", "Development or annexation agreement", "diligence",
        "May fix land use, fees, infrastructure, phasing, and public obligations.",
        "Missing agreement terms can create unbudgeted obligations or use limits.",
        trigger="The site is subject to a development, annexation, reimbursement, or public-infrastructure agreement.",
    ),
    _doc(
        "concept_site_plan", "Concept site plan and yield study", "loi",
        "Translates zoning and physical constraints into usable units or square feet.",
        "Missing yield work makes the land basis speculative rather than use-tested.",
    ),
    _doc(
        "utility_will_serve_letters", "Utility will-serve letters", "diligence",
        "Confirms service availability, capacity, connection point, and conditions.",
        "Missing commitments can expose fatal capacity limits and off-site cost.",
    ),
    _doc(
        "utility_maps", "Utility maps and capacity studies", "diligence",
        "Locates infrastructure and tests extension and upgrade requirements.",
        "Missing utility evidence can understate schedule and horizontal cost.",
    ),
    _doc(
        "access_evidence", "Legal and physical access evidence", "diligence",
        "Development requires insurable access with adequate geometry and control.",
        "Missing access can make the parcel landlocked or commercially unusable.",
    ),
    _doc(
        "traffic_study", "Traffic-impact or access study", "diligence",
        "Tests trip capacity, turn movements, and required roadway improvements.",
        "Missing traffic work can hide off-site improvements or entitlement denial risk.",
        trigger="The proposed use or jurisdiction requires traffic analysis or access permits.",
    ),
    _doc(
        "phase_i", "Phase I environmental site assessment", "diligence",
        "Identifies recognized environmental conditions and supports liability defenses.",
        "Missing or stale work can leave cleanup exposure and financing risk.",
    ),
    _doc(
        "phase_ii", "Phase II environmental investigation", "diligence",
        "Sampling bounds suspected contamination and remediation scope.",
        "Skipping indicated testing can leave the site unfinanceable or uneconomic.",
        trigger="The Phase I identifies a REC, data gap, or condition requiring sampling.",
    ),
    _doc(
        "wetlands_delineation", "Wetlands delineation and jurisdictional evidence", "diligence",
        "Defines regulated areas, buffers, and permitting implications.",
        "Missing delineation can materially reduce developable acreage.",
        trigger="Desktop review, site conditions, or agency maps indicate possible wetlands or waters.",
    ),
    _doc(
        "floodplain_map", "Floodplain determination and hydraulic evidence", "diligence",
        "Identifies floodway, elevation, insurance, and fill constraints.",
        "Missing flood analysis can erase site yield or add major mitigation cost.",
    ),
    _doc(
        "geotechnical_report", "Geotechnical report", "diligence",
        "Tests bearing, groundwater, expansive soils, and foundation assumptions.",
        "Missing subsurface data can hide large foundation and earthwork premiums.",
    ),
    _doc(
        "endangered_species_review", "Protected-species and habitat review", "diligence",
        "Identifies seasonal surveys, habitat constraints, and agency consultation.",
        "Missing review can stop grading and materially delay approvals.",
        trigger="Known habitat, mapped species, or agency screening indicates potential presence.",
    ),
    _doc(
        "archaeological_cultural_review", "Cultural-resources review", "diligence",
        "Identifies survey and mitigation duties before disturbance.",
        "Missing review can cause stop-work orders and entitlement delay.",
        trigger="The jurisdiction, funding source, or prior record requires cultural-resource review.",
    ),
    _doc(
        "property_tax_bills", "Property-tax bills and assessments", "diligence",
        "Confirms parcels, delinquency, exemptions, and current carrying cost.",
        "Missing bills can conceal liens, split parcels, or tax assumptions.",
    ),
    _doc(
        "impact_fee_schedule", "Impact-fee and tap-fee schedule", "diligence",
        "Quantifies major public charges tied to the development program.",
        "Missing fee data can materially overstate residual land value.",
    ),
    _doc(
        "farm_tenant_estoppels", "Farm, ground-tenant, or occupant estoppels", "diligence",
        "Confirms possession, termination, rent, crop, and other occupancy claims.",
        "Missing estoppels can leave holdover or possessory rights unresolved at closing.",
        trigger="Any farm tenant, ground tenant, licensee, billboard operator, or other occupant has rights to the land.",
    ),
    _doc(
        "mineral_water_rights", "Mineral and water-rights instruments", "diligence",
        "Severed estates and water rights can affect use, value, and surface control.",
        "Missing instruments can conceal third-party entry rights or inadequate water.",
        trigger="Title, geography, or intended use makes mineral or water rights material.",
    ),
    _doc(
        "appraisal", "Lender appraisal", "financing",
        "Supports as-is collateral value and loan sizing.",
        "Missing or delayed appraisal can reduce proceeds or miss financing dates.",
    ),
    _doc(
        "loan_commitment", "Executed acquisition or land-loan commitment", "financing",
        "Fixes proceeds, recourse, reserves, conditions, and expiration.",
        "Missing binding terms leaves the capital stack and close uncertain.",
    ),
    _doc(
        "buyer_entity_authority", "Buyer entity and authority documents", "closing",
        "Confirms buyer existence and signature authority.",
        "Missing authority documents can stop escrow and loan funding.",
    ),
    _doc(
        "loan_payoff", "Seller payoff and lien-release documentation", "closing",
        "Clears monetary liens and establishes closing funds.",
        "Missing payoff evidence can prevent clean title and recording.",
    ),
    _doc(
        "settlement_statement", "Settlement statement", "closing",
        "Reconciles price, deposits, credits, taxes, fees, and proceeds.",
        "Missing review can create proration errors or an incorrect wire.",
    ),
    _doc(
        "deed", "Approved deed", "closing",
        "Transfers the correct land estate using the reconciled legal description.",
        "A defective deed or description prevents recordable conveyance.",
    ),
    _doc(
        "closing_escrow_instructions", "Joint closing and escrow instructions", "closing",
        "Controls document release, recording, and disbursement.",
        "Missing aligned instructions creates funding and release risk.",
    ),
)


DOC_TAXONOMY: dict[DealType, tuple[DocumentRequirement, ...]] = {
    "retail_nnn": RETAIL_NNN_DOCUMENTS,
    "multifamily": MULTIFAMILY_DOCUMENTS,
    "office": OFFICE_DOCUMENTS,
    "industrial": INDUSTRIAL_DOCUMENTS,
    "land": LAND_DOCUMENTS,
}

# More explicit alias for callers that prefer the longer name.
DOCUMENT_TAXONOMY = DOC_TAXONOMY


def get_taxonomy(deal_type: str) -> tuple[DocumentRequirement, ...]:
    """Return the declared grading taxonomy for ``deal_type``.

    A tuple is returned so callers cannot accidentally add or remove rows from
    the module-level convention.  Individual rows should also be treated as
    read-only constants.
    """

    normalized = deal_type.strip().casefold()
    if normalized not in DOC_TAXONOMY:
        allowed = ", ".join(DEAL_TYPES)
        raise ValueError(f"deal_type must be one of: {allowed}")
    return DOC_TAXONOMY[normalized]  # type: ignore[index]


__all__ = [
    "DEAL_TYPES",
    "DOC_TAXONOMY",
    "DOCUMENT_TAXONOMY",
    "DocumentRequirement",
    "PHASES",
    "get_taxonomy",
]
