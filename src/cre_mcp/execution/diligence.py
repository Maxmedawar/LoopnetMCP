"""Asset-aware due-diligence checklist generation and persistence."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta

from cre_mcp.deals.store import DealStore, get_deal_store
from cre_mcp.execution.guardrails import execution_guardrail
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import DDItem, DDPlan


@dataclass(frozen=True)
class _DDItemSpec:
    key: str
    label: str
    why: str
    what_clears_it: str
    what_should_make_you_terminate: str
    who_to_hire: str
    buffer_before_expiration_days: int


CORE_DD_ITEMS: tuple[_DDItemSpec, ...] = (
    _DDItemSpec(
        "title_exceptions",
        "Title commitment and exception review",
        "Title exceptions can defeat access, use, financing, or the ownership you think you are buying.",
        "A current commitment, underlying exception documents, tax/lien search, and written attorney clearance of unacceptable exceptions.",
        "Uncured ownership defects, liens, access failures, use restrictions, or exceptions that your lender/title insurer will not accept.",
        "CRE attorney and title officer",
        20,
    ),
    _DDItemSpec(
        "leases_rent_roll",
        "Leases and rent-roll reconciliation",
        "The leases—not the marketing summary—control rent, options, expenses, defaults, and tenant rights.",
        "Every lease/amendment plus a rent roll tied tenant-by-tenant to recent receipts and the T-12.",
        "Material side agreements, undisclosed concessions/defaults, or rent/term economics that do not support underwriting.",
        "CRE attorney and lease auditor",
        20,
    ),
    _DDItemSpec(
        "t12_bank_tieout",
        "T-12 tie-out to bank statements",
        "A spreadsheet can overstate collections or omit recurring expenses; cash evidence tests the stated NOI.",
        "Trailing 12-month general ledger and operating statements reconciled to bank deposits, invoices, tax bills, and the rent roll.",
        "Unsupported revenue, recurring expenses omitted from underwriting, unexplained related-party payments, or a material NOI shortfall.",
        "CRE accountant or experienced property-management auditor",
        18,
    ),
    _DDItemSpec(
        "zoning_co",
        "Zoning, permitted use, and certificate of occupancy",
        "Current operations may be legal nonconforming, restricted, or missing approvals needed after closing.",
        "Written zoning verification, permitted-use confirmation, open-permit search, and valid CO where required.",
        "The intended/current use is prohibited, required occupancy approval is missing, or an incurable violation impairs value or financing.",
        "Land-use attorney or zoning consultant",
        15,
    ),
    _DDItemSpec(
        "service_contracts",
        "Service contracts and property obligations",
        "Assignable vendor, management, maintenance, and equipment contracts can add costs or survive closing.",
        "Complete contract schedule showing price, term, termination rights, assignment, and written cancellation/assumption plan.",
        "Material undisclosed obligations, above-market non-cancellable contracts, or essential service rights that cannot transfer.",
        "CRE attorney and property manager",
        15,
    ),
    _DDItemSpec(
        "survey_alta",
        "Survey / ALTA review",
        "Boundary, access, encroachment, easement, and parking issues often appear only when survey and title are read together.",
        "Current ALTA/NSPS survey certified as required by lender/title plus attorney/title acceptance of every plotted issue.",
        "Material encroachment, insufficient legal access/parking, boundary conflict, or uninsurable survey defect.",
        "Licensed surveyor, CRE attorney, and title officer",
        12,
    ),
    _DDItemSpec(
        "phase_i",
        "Phase I environmental site assessment",
        "Environmental liability can follow the property and can dwarf the purchase price.",
        "Current ASTM-compliant Phase I, reliance rights for buyer/lender, and acceptable resolution of any recognized environmental condition.",
        "Unquantified contamination, required Phase II/remediation beyond your approved budget, or no viable liability/risk allocation.",
        "Qualified environmental consultant and environmental counsel if flagged",
        12,
    ),
    _DDItemSpec(
        "pca",
        "Property condition assessment (PCA)",
        "Roof, structure, pavement, HVAC, life-safety, and accessibility work can consume the return immediately after closing.",
        "Independent PCA with immediate repairs and 5-10 year capital schedule incorporated into underwriting and loan reserves.",
        "Unsafe conditions, unfinanceable defects, or near-term capital needs that break returns and the seller will not cure or credit.",
        "Commercial building inspector/engineer and relevant specialists",
        12,
    ),
    _DDItemSpec(
        "insurance_loss_runs",
        "Insurance quotes and loss runs",
        "Premiums, exclusions, deductibles, flood/wind exposure, and prior claims can change NOI or make the asset uninsurable.",
        "Bind-ready coverage matching lender/lease requirements, reviewed loss runs, and modeled premium/deductible costs.",
        "Required coverage is unavailable or uneconomic, material claims are unresolved, or exclusions leave a catastrophic gap.",
        "CRE insurance broker and lender risk team",
        10,
    ),
    _DDItemSpec(
        "litigation_violations",
        "Litigation, code, permit, tax, and violation search",
        "Pending disputes and government violations can transfer risk, delay closing, or impair use.",
        "Attorney-reviewed litigation/UCC/judgment search plus written municipal confirmation of open permits, code, fire, and tax status.",
        "Unresolved material litigation, unbonded/uncured violations, delinquent taxes, or enforcement that cannot be cleared before closing.",
        "CRE attorney, title officer, and municipal permit specialist",
        10,
    ),
)


RETAIL_DD_ITEMS: tuple[_DDItemSpec, ...] = (
    _DDItemSpec(
        "tenant_estoppel",
        "Tenant estoppel certificate",
        "The tenant—not the seller—must confirm the lease economics, documents, deposits, and default status you are buying.",
        "Executed attorney/lender-approved estoppel confirming rent, term, deposits, options, amendments, no defaults, and no side agreements.",
        "The tenant disputes economics/default status, reveals undisclosed rights, or refuses a contractually required estoppel.",
        "CRE attorney, seller/tenant contact, and lender counsel",
        5,
    ),
    _DDItemSpec(
        "snda",
        "Subordination, nondisturbance, and attornment agreement (SNDA)",
        "The SNDA defines lien priority, tenant protection, and whether the tenant must recognize a lender or foreclosure buyer.",
        "Executed lender/tenant/attorney-approved SNDA consistent with the lease and loan documents.",
        "A required SNDA cannot be obtained or creates foreclosure/lease rights the lender or buyer will not accept.",
        "CRE attorney, lender counsel, and tenant counsel/contact",
        5,
    ),
    _DDItemSpec(
        "co_tenancy_go_dark",
        "Co-tenancy, exclusives, and go-dark review",
        "Retail clauses can reduce rent or permit termination when an anchor closes, occupancy falls, or another use enters the center.",
        "Lease abstract and attorney memo mapping every co-tenancy, exclusive, kick-out, radius, assignment, and go-dark trigger to current facts.",
        "An active or likely trigger causes rent loss/termination, blocks the business plan, or creates uncapped landlord exposure.",
        "Retail lease attorney",
        15,
    ),
)


MULTIFAMILY_DD_ITEMS: tuple[_DDItemSpec, ...] = (
    _DDItemSpec(
        "unit_walks",
        "Unit-by-unit occupied and vacant walk",
        "Sampling can hide down units, health/safety issues, unreported concessions, and renovation scope.",
        "100% unit access log with photos, condition/occupancy status, lease match, repair scope, and priced renovation schedule.",
        "Material occupied/vacant mismatch, unsafe conditions, access refusal, or repairs/concessions that break the renovation budget.",
        "Multifamily inspector, contractor, and property manager",
        12,
    ),
    _DDItemSpec(
        "utilities",
        "Utility bills and allocation audit",
        "Owner-paid leakage, master meters, RUBS limits, and seasonal usage materially affect controllable expenses.",
        "24 months of bills and meter inventory reconciled to the T-12, tenant bill-backs, local rules, and projected usage.",
        "Unmodeled owner-paid utilities, illegal/uncollectible allocations, leaks, or infrastructure work that breaks NOI.",
        "Utility audit consultant and property manager",
        15,
    ),
    _DDItemSpec(
        "payroll_staffing",
        "Payroll, staffing, and employee obligations",
        "On-site labor and accrued obligations may be understated or transfer unexpectedly.",
        "Payroll register, staffing schedule, benefits/PTO liabilities, contracts, and a written retain/terminate/transition plan.",
        "Unfunded material obligations, operationally unsafe staffing, or payroll normalization that breaks underwriting.",
        "Employment counsel, accountant, and property manager",
        15,
    ),
    _DDItemSpec(
        "deferred_maintenance",
        "Deferred-maintenance scope and bids",
        "Recurring work orders and deferred systems can turn a value-add budget into an uncontrolled capital project.",
        "Work-order history, code/fire files, unit/PCA findings, and trade bids rolled into a funded scope with contingency.",
        "Critical scope cannot be priced, schedule exceeds available carry, or total project cost destroys the approved return.",
        "General contractor, engineer, and property manager",
        8,
    ),
)


def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").casefold()).strip("_")


def _asset_flags(ctx: DealContext) -> tuple[bool, bool, str]:
    property_type = _normalize(ctx.listing.property_type)
    subtype = _normalize(ctx.listing.property_subtype)
    strategy = _normalize(ctx.facts.strategy_hint if ctx.facts else None)
    combined = "_".join((property_type, subtype, strategy))
    multifamily = any(token in combined for token in ("multifamily", "multi_family", "apartment"))
    retail = any(token in combined for token in ("retail", "nnn", "net_lease", "single_tenant"))
    asset_class = "multifamily" if multifamily else "retail/NNN" if retail else property_type or "commercial"
    return retail, multifamily, asset_class


def _coerce_start_date(value: date | str | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("start_date must be an ISO date (YYYY-MM-DD)") from exc


def _due_offset(dd_days: int, buffer_at_30_days: int) -> int:
    """Scale a pre-expiration review buffer, then back-solve its due day."""
    scaled_buffer = math.ceil(buffer_at_30_days * dd_days / 30)
    return max(0, dd_days - min(dd_days, scaled_buffer))


async def due_diligence_plan(
    ctx: DealContext,
    dd_days: int = 30,
    start_date: date | str | None = None,
    *,
    store: DealStore | None = None,
) -> DDPlan:
    """Build and persist an ordered checklist against the contractual DD expiry."""
    if isinstance(dd_days, bool) or dd_days <= 0:
        raise ValueError("dd_days must be a positive integer")
    start = _coerce_start_date(start_date)
    expiration = start + timedelta(days=dd_days)
    retail, multifamily, asset_class = _asset_flags(ctx)
    specs = list(CORE_DD_ITEMS)
    if retail:
        specs.extend(RETAIL_DD_ITEMS)
    if multifamily:
        specs.extend(MULTIFAMILY_DD_ITEMS)

    items = [
        DDItem(
            key=spec.key,
            label=spec.label,
            why=spec.why,
            what_clears_it=spec.what_clears_it,
            what_should_make_you_terminate=spec.what_should_make_you_terminate,
            who_to_hire=spec.who_to_hire,
            due_offset_days=(offset := _due_offset(dd_days, spec.buffer_before_expiration_days)),
            deadline=start + timedelta(days=offset),
        )
        for spec in specs
    ]
    items.sort(key=lambda item: (item.due_offset_days, item.key))

    active_store = store or get_deal_store()
    expected_id = DealStore.deal_id_for(ctx.listing)
    replace_diligence = getattr(active_store, "replace_diligence", None)
    if callable(replace_diligence):
        stored = await replace_diligence(ctx.listing, items)
        deal_id = str(stored["deal_id"])
        persisted = True
        rows = stored["items"]
    else:
        saved_id = await active_store.save_deal(ctx.listing)
        persisted = saved_id is not None
        deal_id = saved_id or expected_id
        if persisted:
            persisted = await active_store.save_dd_items(deal_id, items)
        rows = await active_store.get_dd_items(deal_id) if persisted else []
    if persisted:
        statuses = {row["key"]: row["status"] for row in rows}
        items = [
            item.model_copy(update={"status": statuses.get(item.key, item.status)})
            for item in items
        ]

    complete = sum(item.status == "complete" for item in items)
    remaining = max((expiration - date.today()).days, 0)
    summary = (
        f"{remaining} calendar days remain until diligence expires on "
        f"{expiration.isoformat()}; {complete} of {len(items)} items are complete. "
        "Escalate any termination issue before the contractual notice cutoff."
    )
    return DDPlan(
        deal_id=deal_id,
        deal_ref=expected_id,
        asset_class=asset_class,
        dd_days=dd_days,
        start_date=start,
        expiration_date=expiration,
        countdown_summary=summary,
        items=items,
        persistence_status="saved" if persisted else "unavailable",
        guardrail=execution_guardrail(
            "Have your CRE attorney calendar the contract's exact notice deadlines now; "
            "engage the named specialists and do not waive diligence by silence."
        ),
    )


__all__ = [
    "CORE_DD_ITEMS",
    "MULTIFAMILY_DD_ITEMS",
    "RETAIL_DD_ITEMS",
    "due_diligence_plan",
]
