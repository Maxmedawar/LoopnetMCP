"""Closed result envelopes accepted by restricted workspace profiles.

These models describe complete client-visible tool results.  The access engine
validates them with strict JSON semantics and ``extra='forbid'`` before it
walks every capability-declared property location path.
"""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from cre_mcp.models.comps import SaleComp, ValueEstimate
from cre_mcp.models.deals import Deal
from cre_mcp.models.enrichment import OwnerRecord, ParcelRecord
from cre_mcp.models.listings import Listing
from cre_mcp.models.market import MarketPack, RentComparable
from cre_mcp.models.tax import AfterTaxResult
from cre_mcp.truth.noi_bridge import FatalFlawReport, NOIBridge


class ClosedResultModel(BaseModel):
    """Base for access-boundary envelopes with no undeclared fields."""

    model_config = ConfigDict(extra="forbid")


class RestrictedListing(Listing):
    """Restricted listing with unreconciled coordinates and raw data removed."""

    model_config = ConfigDict(extra="forbid")

    lat: None = None
    lon: None = None
    raw: dict[str, object] = Field(default_factory=dict)

    @field_validator("raw")
    @classmethod
    def _empty_raw(cls, value: dict[str, object]) -> dict[str, object]:
        if value:
            raise ValueError("listing provider raw data is not accepted")
        return value


class RestrictedSaleComp(SaleComp):
    """Restricted county comp with coordinates removed pending geofencing."""

    model_config = ConfigDict(extra="forbid")

    lat: None = None
    lon: None = None


class ValueProvenance(ClosedResultModel):
    method: str
    confidence: float
    n_comps: int


class CoverageSummary(ClosedResultModel):
    covered: int
    total: int
    ratio: float
    missing: list[str] = Field(default_factory=list)


class MarketIntelResult(MarketPack):
    model_config = ConfigDict(extra="forbid")

    market_score: float
    score_confidence: float
    coverage_summary: CoverageSummary


class RankedMarketIntelResult(MarketIntelResult):
    location: str
    rank: int


class CompareMarketsResult(ClosedResultModel):
    markets: list[RankedMarketIntelResult] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)
    count: int

    @model_validator(mode="after")
    def _count_matches_markets(self) -> "CompareMarketsResult":
        if self.count != len(self.markets):
            raise ValueError("count must equal the number of returned markets")
        return self


class DedupeListingRecord(ClosedResultModel):
    source: str
    source_id: str
    address: str
    city: str
    state: str
    zip: str | None = None
    price: str | int | float | None = None
    seen_date: str | None = None


class DedupePriceHistory(ClosedResultModel):
    source: str
    source_id: str
    price: str | int | float
    seen_date: str | None = None


class DedupeGroup(ClosedResultModel):
    canonical: DedupeListingRecord
    members: list[DedupeListingRecord]
    tier: str
    match_basis: str | None = None
    price_history: list[DedupePriceHistory] = Field(default_factory=list)


class DedupeCandidateReference(ClosedResultModel):
    source: str
    source_id: str
    address: str
    city: str
    state: str
    zip: str | None = None


class DedupeCandidateMatch(ClosedResultModel):
    left: DedupeCandidateReference
    right: DedupeCandidateReference
    tier: str
    match_basis: str
    score: float
    requires_human_confirmation: bool


class DedupeListingsResult(ClosedResultModel):
    groups: list[DedupeGroup] = Field(default_factory=list)
    candidate_matches: list[DedupeCandidateMatch] = Field(default_factory=list)
    fuzzy_threshold: float
    honesty: str


class PortfolioInputRecord(ClosedResultModel):
    owner_name: str
    business_name: str | None = None
    use: str | None = None
    property_type: str | None = None
    sf: str | int | float | None = None
    assessed_value: str | int | float | None = None
    address: str
    parcel_id: str | int | None = None
    property_id: str | int | None = None
    lat: None = None
    lon: None = None
    latitude: None = None
    longitude: None = None


class PortfolioProperty(ClosedResultModel):
    record_index: int
    address: str
    parcel_id: str | int | None = None
    property_id: str | int | None = None
    use: str | None = None
    sf: str | int | float | None = None
    size_to_median_ratio: float | None = None
    noncore_outlier_flag: bool
    signal_label: str
    basis: list[str]
    inference_caution: str
    unrecognized_fields: list[str] = Field(default_factory=list)


class PortfolioProfile(ClosedResultModel):
    use_counts: dict[str, int] = Field(default_factory=dict)
    modal_use_for_outlier_test: str | None = None
    median_sf: float | None = None
    usable_size_count: int
    size_ratio_outlier_threshold: float


class PortfolioOwner(ClosedResultModel):
    normalized_owner_name: str
    owner_name_variants: list[str]
    property_count: int
    signal_label: str
    grouping_basis: str
    profile: PortfolioProfile
    dispersion_note: str
    noncore_outlier_count: int
    properties: list[PortfolioProperty] = Field(min_length=1)
    seller_intent_caution: str

    @model_validator(mode="after")
    def _property_count_matches_records(self) -> "PortfolioOwner":
        if self.property_count != len(self.properties):
            raise ValueError("property_count must equal the number of properties")
        return self


class PortfolioMethodology(ClosedResultModel):
    label: str
    minimum_properties: int
    type_outlier_convention: str
    size_outlier_convention: str


class PortfolioSkippedRecord(ClosedResultModel):
    record_index: int
    reason: str
    unrecognized_fields: list[str] = Field(default_factory=list)


class PortfolioOwnerScanResult(ClosedResultModel):
    methodology: PortfolioMethodology
    record_count: int
    owner_group_count: int
    owners: list[PortfolioOwner] = Field(default_factory=list)
    skipped_records: list[PortfolioSkippedRecord] = Field(default_factory=list)
    unrecognized_input_fields: list[str] = Field(default_factory=list)


class RouteListingInput(ClosedResultModel):
    deal_id: str | int | None = None
    source_id: str | int | None = None
    id: str | int | None = None
    url: str | None = None
    address: str
    city: str
    state: str
    zip_code: str | None = None
    zip: str | None = None
    postal_code: str | None = None
    property_type: str | None = None
    asset_type: str | None = None
    type: str | None = None
    price_usd: str | int | float | None = None
    price: str | int | float | None = None
    asking_price: str | int | float | None = None
    size_sqft: str | int | float | None = None
    square_feet: str | int | float | None = None
    building_size: str | int | float | None = None
    size: str | int | float | None = None
    strategy: str | None = None
    strategy_hint: str | None = None
    listing_type: str | None = None


class RouteListingResult(ClosedResultModel):
    id: str | int
    recorded_fields: list[str]
    address: str
    city: str
    state: str
    zip_code: str | None = None


class RouteCandidate(ClosedResultModel):
    name: str
    score: float
    reasons: list[str]
    evidence_gaps: list[str]
    matched_mandate_index: int
    matched_mandate: str
    rank: int


class RouteLeadResult(ClosedResultModel):
    listing: RouteListingResult
    recommended: RouteCandidate | None = None
    routes: list[RouteCandidate] = Field(default_factory=list)
    candidate_count: int
    team_members_reviewed: int
    message: str
    honesty: str


class ArbitrageSpaceInput(ClosedResultModel):
    id: str | int | None = None
    address: str
    city: str
    state: str
    zip_code: str | None = None
    building_sqft: int | float | str | None = None
    master_rent_annual: int | float | str | None = None
    asking_rent_psf: int | float | str | None = None
    achievable_sublease_psf: int | float | str | None = None
    sublease_occupancy: int | float | str | None = None
    ti_psf: int | float | str | None = None
    free_rent_months: int | float | str | None = None
    mgmt_pct: int | float | str | None = None
    other_annual_costs: int | float | str | None = None
    term_years: int | None = None
    your_rent_escalation_pct: int | float | str | None = None
    sublease_escalation_pct: int | float | str | None = None
    personal_guarantee: bool | None = None


class ArbitrageSkippedSpace(ClosedResultModel):
    space: str
    reason: str


class ArbitrageScreeningSummary(ClosedResultModel):
    input_count: int
    positive_count: int
    filtered_non_positive_count: int
    filtered_count: int
    skipped_missing_or_invalid_count: int
    skipped_spaces: list[ArbitrageSkippedSpace] = Field(default_factory=list)


class ArbitrageProjection(ClosedResultModel):
    year: int
    income: float
    cost: float
    net: float
    margin: float | None = None


class ArbitrageEconomics(ClosedResultModel):
    master_rent_annual: float
    building_sqft: float
    sublease_rent_psf: float
    sublease_occupancy: float
    ti_psf: float
    free_rent_months: float
    mgmt_pct: float
    other_annual_costs: float
    term_years: int
    your_rent_escalation_pct: float
    sublease_escalation_pct: float
    personal_guarantee: bool
    gross_potential_sublease_income: float
    gross_sublease_income: float
    amortized_ti: float
    amortized_free_rent: float
    variable_cost: float
    fixed_cost: float
    total_cost: float
    net_cash_flow_annual: float
    margin_pct: float | None = None
    rent_coverage: float | None = None
    breakeven_occupancy: float | None = None
    breakeven_sublease_psf: float | None = None
    negative_carry_exposure_annual: float
    negative_carry_exposure_full_term: float
    negative_carry_note: str
    projection: list[ArbitrageProjection] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    explanation: str


class ArbitrageOpportunity(ArbitrageSpaceInput):
    master_rent_annual: float
    achievable_sublease_psf: float
    economics: ArbitrageEconomics
    opportunity_label: str
    risk_label: str
    caveat: str
    rank: int
    filtered_count: int
    filtered_non_positive_count: int
    skipped_missing_or_invalid_count: int
    screening_summary: ArbitrageScreeningSummary


class ArbitrageOpportunitiesResult(ArbitrageScreeningSummary):
    count: int
    opportunities: list[ArbitrageOpportunity] = Field(default_factory=list)


class DealSearchResult(ClosedResultModel):
    query_location: str
    strategy: str | None = None
    deals: list[Deal] = Field(default_factory=list)
    total_scored: int
    returned: int
    errors: dict[str, str] = Field(default_factory=dict)
    per_source_counts: dict[str, int] = Field(default_factory=dict)
    deduped: int
    score_calibrated: bool
    score_calibration_disclaimer: str | None = None


class DealAnalysisResult(Deal):
    model_config = ConfigDict(extra="forbid")

    score_calibrated: bool
    score_calibration_disclaimer: str | None = None
    value_provenance: ValueProvenance | None = None
    warnings: dict[str, str] = Field(default_factory=dict)


class CompsSubject(ClosedResultModel):
    source: str
    source_id: str
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    asking_price: float | None = None


class CompsResult(ClosedResultModel):
    subject: CompsSubject
    value_estimate: ValueEstimate
    value_provenance: ValueProvenance
    comps: list[SaleComp] = Field(default_factory=list)
    explanation: str
    coverage_note: str


class AlertDeal(Deal):
    model_config = ConfigDict(extra="forbid")

    saved_search_id: int | str
    saved_search_name: str


class AlertSearchResult(ClosedResultModel):
    search_id: int | str
    name: str
    new_count: int
    scanned: int
    source_errors: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class AlertCheckResult(ClosedResultModel):
    searches_checked: int
    new_count: int
    new_deals: list[AlertDeal] = Field(default_factory=list)
    results: list[AlertSearchResult] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)
    alert_mode: str
    hosting_note: str


class SavedSearchQuery(ClosedResultModel):
    location: str
    strategy: str | None = None
    property_type: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    size_min: float | None = None
    size_max: float | None = None
    sources: list[str] = Field(default_factory=list)


class SaveSearchResult(ClosedResultModel):
    search_id: int | str
    name: str
    query: SavedSearchQuery
    min_score: float | None = None
    alert_mode: str
    hosting_note: str


class SavedSearchRow(ClosedResultModel):
    id: int | str
    name: str
    query: SavedSearchQuery
    min_score: float | None = None
    created_at: str
    seen_count: int


class ListSearchesResult(ClosedResultModel):
    searches: list[SavedSearchRow] = Field(default_factory=list)
    count: int
    alert_mode: str
    hosting_note: str


class DealNote(ClosedResultModel):
    text: str
    stage: str
    created_at: str


class CompactDealRow(ClosedResultModel):
    deal_id: str
    source: str
    source_id: str
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    price_usd: float | None = None
    stage: str
    score: float | None = None
    grade: str | None = None
    strategy: str | None = None
    last_note: DealNote | None = None
    created_at: str
    updated_at: str
    dd_total: int
    dd_complete: int


class ListDealsResult(ClosedResultModel):
    deals: list[CompactDealRow] = Field(default_factory=list)
    count: int


class PipelineDealRow(CompactDealRow):
    url: str | None = None
    notes: list[DealNote] = Field(default_factory=list)


class ListPipelineResult(ClosedResultModel):
    stage: str | None = None
    deals: list[PipelineDealRow] = Field(default_factory=list)
    by_stage: dict[str, list[PipelineDealRow]] = Field(default_factory=dict)
    count: int


class ControlListingRaw(ClosedResultModel):
    aadt: int | float | str | None = None
    traffic_aadt: int | float | str | None = None
    population_3mi: int | float | str | None = None
    three_mile_population: int | float | str | None = None
    median_income: int | float | str | None = None
    median_household_income: int | float | str | None = None
    parcel_acres: int | float | str | None = None
    lot_acres: int | float | str | None = None
    building_sqft: int | float | str | None = None
    size_sqft_num: int | float | str | None = None
    has_drive_thru: bool | str | None = None
    nearby_categories: list[str] = Field(default_factory=list)
    value_vacant: int | float | str | None = None
    vacant_value: int | float | str | None = None
    achievable_rent_psf: int | float | str | None = None
    market_rent_psf: int | float | str | None = None
    market_cap_rate: int | float | str | None = None
    days_on_market: int | float | str | None = None
    dom: int | float | str | None = None
    marketing_days: int | float | str | None = None
    listing_days: int | float | str | None = None


class ControlListingInput(Listing):
    model_config = ConfigDict(extra="forbid")

    lat: None = None
    lon: None = None
    raw: ControlListingRaw = Field(default_factory=ControlListingRaw)


class ControlVacancy(ClosedResultModel):
    is_vacant_candidate: bool
    signals: list[str] = Field(default_factory=list)
    confidence: float


class ControlTenantMatch(ClosedResultModel):
    brand: str
    fit_score: float
    met: list[str] = Field(default_factory=list)
    unmet: list[str] = Field(default_factory=list)
    reasons: str


class ControlSpread(ClosedResultModel):
    value_vacant: float
    achievable_rent_psf: float
    building_sqft: float
    market_cap_rate: float
    annual_rent: float
    value_leased: float
    ti_psf: float
    tenant_improvements: float
    leasing_commission_pct: float
    leasing_commission: float
    months_vacant: int
    carry_annual: float
    vacancy_carry: float
    costs: float
    total_costs: float
    gross_spread: float
    execution_risk_haircut: float
    net_spread: float
    return_on_control: float | None = None
    explanation: str


class ControlScoreComponents(ClosedResultModel):
    vacancy: float
    tenant_fit: float
    spread: float


class ControlOpportunity(ClosedResultModel):
    listing: Listing
    vacancy: ControlVacancy
    tenant_matches: list[ControlTenantMatch] = Field(default_factory=list)
    spread: ControlSpread | None = None
    control_score: float
    score_components: ControlScoreComponents
    rank: int


class ControlOpportunitiesResult(ClosedResultModel):
    count: int
    opportunities: list[ControlOpportunity] = Field(default_factory=list)
    methodology: str


class EmployerWarnEvent(ClosedResultModel):
    employer: str
    location: str
    # The restricted projection authorizes the exact event location. A second
    # free-form county is an independent location carrier and is deliberately
    # unavailable at this boundary until it can be reconciled authoritatively.
    county: None = None
    affected: int | None = None
    effective_date: str
    source_url: str


class EmployerWarnEventsResult(ClosedResultModel):
    status: str
    state: str
    since: str
    count: int
    events: list[EmployerWarnEvent] = Field(default_factory=list)
    source_url: str | None = None
    dataset_url: str | None = None
    request_url: str | None = None
    landing_url: str | None = None
    source_format: str | None = None
    source_retrieved_date: str | None = None
    since_convention: str | None = None
    reason: str | None = None


class TenantProspectDemographics(ClosedResultModel):
    traffic_aadt: int | float | str | None = None
    aadt: int | float | str | None = None
    population: int | float | str | None = None
    population_3mi: int | float | str | None = None
    median_income: int | float | str | None = None
    median_household_income: int | float | str | None = None


class TenantProspectSiteInput(ClosedResultModel):
    address: str
    city: str
    state: str
    zip_code: str | None = None
    sf: int | float | str
    demographics: TenantProspectDemographics = Field(
        default_factory=TenantProspectDemographics
    )
    lat: None = None
    lon: None = None
    whitespace_radius_m: int | float | str | None = None
    parcel_acres: int | float | str | None = None
    frontage: int | float | str | None = None
    frontage_ft: int | float | str | None = None
    has_drive_thru: bool | None = None


class TenantProspect(ClosedResultModel):
    brand: str
    fit_score: float
    met: list[str] = Field(default_factory=list)
    unmet: list[str] = Field(default_factory=list)
    reasons: str
    category: str
    catalog_expansion_mode: str
    catalog_source: str
    catalog_confidence: float
    base_fit_score: float
    watch_adjustment: float
    watch_adjustment_reasons: list[str] = Field(default_factory=list)
    prospect_score: float
    whitespace_status: str
    whitespace_note: str
    frontage_screen: str | None = None
    signal_count: int
    pursuit_disclaimer: str
    rank: int


class TenantProspectListResult(ClosedResultModel):
    prospects: list[TenantProspect] = Field(default_factory=list)
    catalog_count: int
    catalog_coverage_note: str
    cotenancy_source: str
    cotenancy_observation_count: int
    whitespace_radius_m: int
    ranking_method: str
    watch_hook_note: str
    site_inputs: TenantProspectSiteInput


class SubjectProperty(ClosedResultModel):
    """Small required property identity used by otherwise non-locating tools."""

    address: str
    city: str
    state: str
    zip_code: str | None = None


class RestrictedNOIBridgeResult(NOIBridge):
    model_config = ConfigDict(extra="forbid")

    property: SubjectProperty


class RestrictedNOIBridgeInsufficientResult(ClosedResultModel):
    deal_id: str
    note: str
    property: SubjectProperty


class RestrictedDealTruthReportResult(ClosedResultModel):
    report: FatalFlawReport
    noi_bridge: NOIBridge
    property: SubjectProperty


class RestrictedDealTruthInsufficientResult(ClosedResultModel):
    deal_id: str
    verdict: Literal["insufficient_data"]
    note: str
    property: SubjectProperty


NonBlankText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class RestrictedRentComparable(RentComparable):
    """Restricted rent evidence with one mandatory, resolvable location."""

    model_config = ConfigDict(extra="forbid")

    location: NonBlankText
NumberValue = int | float
OptionalNumberValue = int | float | None


class RestrictedWorkflowLocation(ClosedResultModel):
    """One complete scalar location carried by a restricted workflow."""

    location: NonBlankText


class RestrictedOvernightChange(ClosedResultModel):
    property: SubjectProperty
    event_type: Literal[
        "price_change",
        "status_change",
        "broker_change",
        "dom_milestone",
    ]
    previous_captured_at: str | None = None
    captured_at: str | None = None
    from_snapshot_id: int = Field(ge=1)
    to_snapshot_id: int = Field(ge=1)
    direction: Literal["decrease", "increase"] | None = None
    pct_change: OptionalNumberValue = None
    milestone_days: int | None = Field(default=None, ge=0)


class RestrictedOvernightDeadline(ClosedResultModel):
    property: SubjectProperty
    source: Literal["dd_item", "exchange_clock"]
    deadline: NonBlankText
    days_left: int
    transition: Literal[
        "became_overdue",
        "entered_7_day_window",
        "entered_30_day_window",
        "new_or_updated_overdue",
        "new_or_updated_within_7_day_window",
        "new_or_updated_within_30_day_window",
    ]
    severity: Literal["urgent", "important", "value_destroying"]


class RestrictedOvernightAttention(ClosedResultModel):
    property: SubjectProperty
    stage: Literal[
        "lead",
        "analyzing",
        "contacted",
        "loi",
        "under_contract",
        "diligence",
        "closing",
    ]
    flag_types: list[Literal["no_recent_event", "stage_stuck", "overdue_dd"]] = (
        Field(min_length=1)
    )


class RestrictedOvernightSummaryCounts(ClosedResultModel):
    listing_changes: int = Field(ge=0)
    price_changes: int = Field(ge=0)
    status_changes: int = Field(ge=0)
    broker_changes: int = Field(ge=0)
    dom_milestones: int = Field(ge=0)
    approaching_deadlines: int = Field(ge=0)
    dd_deadline_transitions: int = Field(ge=0)
    exchange_clock_transitions: int = Field(ge=0)
    needs_attention: int = Field(ge=0)


class RestrictedOvernightChangesResult(ClosedResultModel):
    as_of: NonBlankText
    since: NonBlankText
    changes: list[RestrictedOvernightChange] = Field(default_factory=list)
    deadlines: list[RestrictedOvernightDeadline] = Field(default_factory=list)
    attention: list[RestrictedOvernightAttention] = Field(default_factory=list)
    summary_counts: RestrictedOvernightSummaryCounts

    @model_validator(mode="after")
    def _counts_reconcile(self) -> "RestrictedOvernightChangesResult":
        counts = self.summary_counts
        expected = {
            "listing_changes": len(self.changes),
            "price_changes": sum(row.event_type == "price_change" for row in self.changes),
            "status_changes": sum(row.event_type == "status_change" for row in self.changes),
            "broker_changes": sum(row.event_type == "broker_change" for row in self.changes),
            "dom_milestones": sum(row.event_type == "dom_milestone" for row in self.changes),
            "approaching_deadlines": len(self.deadlines),
            "dd_deadline_transitions": sum(row.source == "dd_item" for row in self.deadlines),
            "exchange_clock_transitions": sum(row.source == "exchange_clock" for row in self.deadlines),
            "needs_attention": len(self.attention),
        }
        if counts.model_dump() != expected:
            raise ValueError("overnight summary counts do not reconcile")
        return self


class RestrictedStaleEvidence(ClosedResultModel):
    snapshot_count: int = Field(ge=1)
    latest_dom: int | None = Field(default=None, ge=0)
    price_cut_count: int = Field(ge=0)
    price_cut_velocity_per_30_days: OptionalNumberValue = None
    cumulative_price_change_pct: OptionalNumberValue = None
    observation_days: OptionalNumberValue = None


class RestrictedStaleScoreRules(ClosedResultModel):
    dom_90_to_179: int = Field(ge=0)
    dom_180_plus: int = Field(ge=0)
    one_price_cut: int = Field(ge=0)
    two_plus_price_cuts: int = Field(ge=0)
    one_plus_cuts_per_30_days: int = Field(ge=0)
    two_plus_cuts_per_30_days: int = Field(ge=0)


class RestrictedStaleConvention(ClosedResultModel):
    stale_dom_days: int = Field(ge=0)
    very_stale_dom_days: int = Field(ge=0)
    score_rules: RestrictedStaleScoreRules


class RestrictedStaleListingSignalsResult(ClosedResultModel):
    listing_key: NonBlankText
    property: SubjectProperty
    negotiability_signal: Literal[
        "insufficient_data",
        "none",
        "weak",
        "moderate",
        "strong",
    ]
    heuristic_score: int = Field(ge=0)
    evidence: RestrictedStaleEvidence
    convention: RestrictedStaleConvention
    thin_data: bool


class BuyerMatchDealInput(ClosedResultModel):
    price: NumberValue
    type: NonBlankText
    market: NonBlankText

    @model_validator(mode="after")
    def _positive_price(self) -> "BuyerMatchDealInput":
        if isinstance(self.price, bool) or self.price <= 0:
            raise ValueError("buyer-match price must be positive")
        return self


class RestrictedBuyerFitDimension(ClosedResultModel):
    status: NonBlankText
    points: NumberValue
    max_points: NumberValue


class RestrictedBuyerFitDimensions(ClosedResultModel):
    check_size: RestrictedBuyerFitDimension
    asset_type: RestrictedBuyerFitDimension
    geography: RestrictedBuyerFitDimension


class RestrictedBuyerMatch(ClosedResultModel):
    buyer_id: NonBlankText
    name: NonBlankText
    type: NonBlankText
    check_size_min: OptionalNumberValue = None
    check_size_max: OptionalNumberValue = None
    asset_types: list[NonBlankText] = Field(default_factory=list)
    fit_score: NumberValue
    fit_score_max: NumberValue
    fit_status: NonBlankText
    check_size_fit: NonBlankText
    fit_dimensions: RestrictedBuyerFitDimensions
    bids_made: int = Field(ge=0)
    retrades: int = Field(ge=0)
    closes: int = Field(ge=0)
    behavioral_history_status: NonBlankText
    behavioral_score: OptionalNumberValue = None
    behavior_used_in_fit_score: bool
    fit_rank: int = Field(ge=1)


class RestrictedBuyerFitRubric(ClosedResultModel):
    check_size: NumberValue
    unknown_check_size_neutral_credit: NumberValue
    asset_type: NumberValue
    geography: NumberValue
    unrecorded_preference_neutral_credit: NumberValue
    behavioral_history_weight: NumberValue


class RestrictedBuyerMatchResult(ClosedResultModel):
    deal: BuyerMatchDealInput
    buyer_count: int = Field(ge=0)
    matches: list[RestrictedBuyerMatch] = Field(default_factory=list)
    fit_rubric: RestrictedBuyerFitRubric

    @model_validator(mode="after")
    def _buyer_rows_reconcile(self) -> "RestrictedBuyerMatchResult":
        if self.buyer_count != len(self.matches):
            raise ValueError("buyer count does not reconcile")
        if [row.fit_rank for row in self.matches] != list(
            range(1, self.buyer_count + 1)
        ):
            raise ValueError("buyer ranks must be complete and ordered")
        return self


LocationInput = NonBlankText | list[NonBlankText]
NumberishInput = NonBlankText | int | float


class LenderMatchDealInput(ClosedResultModel):
    deal: NonBlankText | None = None
    deal_id: NonBlankText | None = None
    name: NonBlankText | None = None
    loan_amount_cents: NumberishInput | None = None
    size_cents: NumberishInput | None = None
    requested_loan_cents: NumberishInput | None = None
    debt_cents: NumberishInput | None = None
    geography: LocationInput | None = None
    geographies: LocationInput | None = None
    market: LocationInput | None = None
    state: LocationInput | None = None
    asset_type: LocationInput | None = None
    type: LocationInput | None = None
    leverage: NumberishInput | None = None
    ltv: NumberishInput | None = None
    leverage_pct: NumberishInput | None = None
    rate_context: NonBlankText | None = None
    index: NonBlankText | None = None
    term_years: NumberishInput | None = None
    recourse: bool | NonBlankText | None = None

    @model_validator(mode="after")
    def _one_unambiguous_location_alias(self) -> "LenderMatchDealInput":
        supplied = [
            field
            for field in ("geography", "geographies", "market", "state")
            if getattr(self, field) is not None
        ]
        if len(supplied) != 1:
            raise ValueError("exactly one lender geography alias is required")
        raw = getattr(self, supplied[0])
        values = raw if isinstance(raw, list) else [raw]
        if not values or len({value.casefold() for value in values}) != len(values):
            raise ValueError("lender geography values must be nonempty and unique")
        return self


class RestrictedLenderDeal(ClosedResultModel):
    loan_amount_cents: int | None = Field(default=None, ge=0)
    locations: list[RestrictedWorkflowLocation]
    asset_types: list[NonBlankText] = Field(default_factory=list)
    leverage: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _locations_are_nonempty_unique(self) -> "RestrictedLenderDeal":
        values = [item.location.casefold() for item in self.locations]
        if not values or len(set(values)) != len(values):
            raise ValueError("lender result locations must be nonempty and unique")
        return self


class RestrictedLenderFitDimensions(ClosedResultModel):
    size: RestrictedBuyerFitDimension
    geography: RestrictedBuyerFitDimension
    asset_type: RestrictedBuyerFitDimension
    leverage: RestrictedBuyerFitDimension


class RestrictedLenderMatch(ClosedResultModel):
    lender_id: int | NonBlankText
    name: NonBlankText
    type: NonBlankText
    size_min_cents: int | None = Field(default=None, ge=0)
    size_max_cents: int | None = Field(default=None, ge=0)
    leverage_max: float | None = Field(default=None, ge=0, le=1)
    asset_types: list[NonBlankText] = Field(default_factory=list)
    fit_score: NumberValue
    fit_score_max: NumberValue
    fit_status: NonBlankText
    fit_dimensions: RestrictedLenderFitDimensions
    last_confirmed: str | None = None
    is_stale: bool | None = None
    days_since_confirmed: int | None = None
    fit_rank: int = Field(ge=1)


class RestrictedLenderFitRubric(ClosedResultModel):
    size: NumberValue
    geography: NumberValue
    asset_type: NumberValue
    leverage: NumberValue
    unknown_values_receive_neutral_partial_credit: bool


class RestrictedLenderMatchResult(ClosedResultModel):
    as_of: NonBlankText
    stale_after_days: int = Field(ge=0)
    deal: RestrictedLenderDeal
    lender_count: int = Field(ge=0)
    matches: list[RestrictedLenderMatch] = Field(default_factory=list)
    fit_rubric: RestrictedLenderFitRubric

    @model_validator(mode="after")
    def _lender_rows_reconcile(self) -> "RestrictedLenderMatchResult":
        if self.lender_count != len(self.matches):
            raise ValueError("lender count does not reconcile")
        if [row.fit_rank for row in self.matches] != list(
            range(1, self.lender_count + 1)
        ):
            raise ValueError("lender ranks must be complete and ordered")
        return self


class RestrictedDealTimelineEvent(ClosedResultModel):
    event_type: NonBlankText
    event_ts: str | None = None
    created_at: str | None = None


class RestrictedDealTimelineDecision(ClosedResultModel):
    system_verdict: str | None = None
    expert_verdict: str | None = None
    agreed: bool | None = None
    created_at: str | None = None


class RestrictedDealTimelineResult(ClosedResultModel):
    deal_id: NonBlankText
    property: SubjectProperty
    events: list[RestrictedDealTimelineEvent] = Field(default_factory=list)
    ic_decisions: list[RestrictedDealTimelineDecision] = Field(default_factory=list)
    event_count: int = Field(ge=0)
    ic_decision_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _timeline_counts_reconcile(self) -> "RestrictedDealTimelineResult":
        if self.event_count != len(self.events):
            raise ValueError("timeline event count does not reconcile")
        if self.ic_decision_count != len(self.ic_decisions):
            raise ValueError("timeline decision count does not reconcile")
        return self


class RestrictedDealDocument(ClosedResultModel):
    document_id: NonBlankText
    doc_kind: NonBlankText
    source_channel: NonBlankText
    origin: str | None = None
    n_pages: int | None = None
    parse_status: NonBlankText
    redactions: int = Field(ge=0)
    ingested_at: str | None = None
    claim_count: int = Field(ge=0)


class RestrictedDealDocumentsResult(ClosedResultModel):
    deal_id: NonBlankText
    property: SubjectProperty
    document_count: int = Field(ge=0)
    total_claims: int = Field(ge=0)
    documents: list[RestrictedDealDocument] = Field(default_factory=list)

    @model_validator(mode="after")
    def _document_counts_reconcile(self) -> "RestrictedDealDocumentsResult":
        if self.document_count != len(self.documents):
            raise ValueError("document count does not reconcile")
        if self.total_claims != sum(row.claim_count for row in self.documents):
            raise ValueError("claim total does not reconcile")
        return self


class RestrictedRelationDeal(ClosedResultModel):
    deal_id: NonBlankText
    property: SubjectProperty
    stage: Literal[
        "lead",
        "analyzing",
        "contacted",
        "loi",
        "under_contract",
        "diligence",
        "closing",
        "owned",
        "passed",
    ]
    score: OptionalNumberValue = None
    updated_at: NonBlankText | None = None


class RestrictedRelationEvent(ClosedResultModel):
    deal_id: NonBlankText
    event_ts: NonBlankText | None = None
    created_at: NonBlankText | None = None


class RestrictedRelationCommitment(ClosedResultModel):
    commitment_id: int = Field(ge=1)
    deal_id: NonBlankText
    made_by: Literal["us", "them"]
    status: Literal["open"]
    due: NonBlankText | None = None
    overdue: bool


class RestrictedMeetingBriefingResult(ClosedResultModel):
    counterparty: NonBlankText
    deal_id: NonBlankText | None = None
    as_of: NonBlankText
    status: Literal[
        "active_open_items",
        "recorded_context_no_open_items",
        "no_recorded_state",
    ]
    deals: list[RestrictedRelationDeal] = Field(min_length=1)
    events: list[RestrictedRelationEvent] = Field(default_factory=list)
    commitments: list[RestrictedRelationCommitment] = Field(default_factory=list)
    deal_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    commitment_count: int = Field(ge=0)
    overdue_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _meeting_rows_are_bound(self) -> "RestrictedMeetingBriefingResult":
        ids = [row.deal_id for row in self.deals]
        if len(ids) != len(set(ids)):
            raise ValueError("meeting deal anchors must be unique")
        allowed = set(ids)
        if self.deal_id is not None and self.deal_id not in allowed:
            raise ValueError("requested meeting deal is not anchored")
        if any(row.deal_id not in allowed for row in self.events):
            raise ValueError("meeting event is not bound to a deal anchor")
        if any(row.deal_id not in allowed for row in self.commitments):
            raise ValueError("meeting commitment is not bound to a deal anchor")
        if (
            self.deal_count != len(self.deals)
            or self.event_count != len(self.events)
            or self.commitment_count != len(self.commitments)
            or self.overdue_count != sum(row.overdue for row in self.commitments)
        ):
            raise ValueError("meeting counts do not reconcile")
        return self


class RestrictedDossierPropertyEvidence(ClosedResultModel):
    deal_id: NonBlankText
    property: SubjectProperty


class RestrictedDossierRedFlag(ClosedResultModel):
    kind: Literal[
        "overridden_claims",
        "quotes_died",
        "adverse_retrades",
        "broken_commitments_by_them",
        "material_or_outcome_defects",
        "registry_flags_for_candidate_matches",
    ]
    count: int = Field(ge=1)


class RestrictedCounterpartyDossierResult(ClosedResultModel):
    who: NonBlankText
    as_of: NonBlankText
    deals: list[RestrictedRelationDeal] = Field(min_length=1)
    evidence_properties: list[RestrictedDossierPropertyEvidence] = Field(
        default_factory=list
    )
    events: list[RestrictedRelationEvent] = Field(default_factory=list)
    red_flags: list[RestrictedDossierRedFlag] = Field(default_factory=list)
    deal_count: int = Field(ge=0)
    evidence_property_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    red_flag_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _dossier_rows_are_bound(self) -> "RestrictedCounterpartyDossierResult":
        ids = [row.deal_id for row in self.deals]
        if len(ids) != len(set(ids)):
            raise ValueError("dossier deal anchors must be unique")
        allowed = set(ids)
        if any(row.deal_id not in allowed for row in self.events):
            raise ValueError("dossier event is not bound to a deal anchor")
        if any(row.deal_id not in allowed for row in self.evidence_properties):
            raise ValueError("dossier property evidence is not bound to a deal anchor")
        if (
            self.deal_count != len(self.deals)
            or self.evidence_property_count != len(self.evidence_properties)
            or self.event_count != len(self.events)
            or self.red_flag_count != len(self.red_flags)
        ):
            raise ValueError("dossier counts do not reconcile")
        return self


class ContactBroker(ClosedResultModel):
    name: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None


class ContactPrincipal(ClosedResultModel):
    name: str
    title: str | None = None
    address: None = None


class ContactRegisteredAgent(ClosedResultModel):
    name: str
    address: None = None
    entity_name: str | None = None
    state: str
    status: str | None = None
    principals: list[ContactPrincipal] = Field(default_factory=list)
    source_url: str | None = None


class ContactInfoResult(ClosedResultModel):
    subject_property: SubjectProperty
    broker: ContactBroker | None = None
    owner_name: str | None = None
    owner_mailing: None = None
    entity_type: str | None = None
    registered_agent: ContactRegisteredAgent | None = None
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    skiptrace_available: bool = False
    disclaimer: str


class RestrictedAfterTaxResult(AfterTaxResult):
    model_config = ConfigDict(extra="forbid")

    subject_property: SubjectProperty


JsonScalar = str | int | float | bool | None
NumericText = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^\s*\$?\s*[+-]?(?:(?:\d{1,3}(?:,\d{3})+)|\d+|\d*\.\d+)"
            r"(?:\.\d+)?(?:[eE][+-]?\d+)?\s*%?\s*$"
        )
    ),
]
NumericInput = int | float | NumericText | None
NumericResult = int | float | None


class RestrictedParcelRecord(ParcelRecord):
    """Client-visible parcel with non-site location carriers removed."""

    model_config = ConfigDict(extra="forbid")

    site_address: NonBlankText
    owner_mailing_address: None = None
    lat: None = None
    lon: None = None
    raw: dict[str, JsonScalar] = Field(default_factory=dict)

    @field_validator("raw")
    @classmethod
    def _empty_raw(cls, value: dict[str, JsonScalar]) -> dict[str, JsonScalar]:
        if value:
            raise ValueError("parcel provider raw data is not accepted")
        return value


class RestrictedOwnerRecord(OwnerRecord):
    """Client-visible owner record with mailing egress closed at the DTO."""

    model_config = ConfigDict(extra="forbid")

    mailing_address: None = None
    parcels: list[RestrictedParcelRecord] = Field(min_length=1)


class AssessorRecordInput(ClosedResultModel):
    address: str | None = None
    site_address: str | None = None
    property_address: str | None = None
    full_address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    zip: str | None = None
    apn: str | None = None
    parcel_id: str | int | None = None
    owner_name: str | None = None
    owner_mailing_address: None = None
    assessed_value: JsonScalar = None
    total_assessed_value: JsonScalar = None
    market_value: JsonScalar = None
    building_sqft: JsonScalar = None
    building_sf: JsonScalar = None
    square_feet: JsonScalar = None
    sqft: JsonScalar = None
    gross_building_area: JsonScalar = None
    year_built: JsonScalar = None
    built_year: JsonScalar = None
    construction_year: JsonScalar = None
    use_code: JsonScalar = None
    use: JsonScalar = None
    property_use: JsonScalar = None
    property_type: JsonScalar = None
    class_code: JsonScalar = None
    units: JsonScalar = None
    unit_count: JsonScalar = None
    number_of_units: JsonScalar = None
    land_value: JsonScalar = None
    last_sale_price: JsonScalar = None
    last_sale_date: JsonScalar = None
    lat: None = None
    lon: None = None
    raw: dict[str, JsonScalar] = Field(default_factory=dict)

    @field_validator("raw")
    @classmethod
    def _empty_raw(cls, value: dict[str, JsonScalar]) -> dict[str, JsonScalar]:
        if value:
            raise ValueError("assessor provider raw data is not accepted")
        return value


class AssessorParcelEnvelopeInput(ClosedResultModel):
    parcel: AssessorRecordInput


class AssessorOwnerEnvelopeInput(ClosedResultModel):
    name: str | None = None
    normalized_name: str | None = None
    entity_type: str | None = None
    absentee: bool | None = None
    mailing_address: None = None
    parcels: list[AssessorRecordInput] = Field(min_length=1)


class AssessorCompBand(ClosedResultModel):
    low: JsonScalar = None
    base: JsonScalar = None
    high: JsonScalar = None


class AssessorStatedFactsInput(ClosedResultModel):
    building_sqft: JsonScalar = None
    building_sf: JsonScalar = None
    square_feet: JsonScalar = None
    sqft: JsonScalar = None
    rentable_sqft: JsonScalar = None
    listing_sqft: JsonScalar = None
    year_built: JsonScalar = None
    built_year: JsonScalar = None
    construction_year: JsonScalar = None
    listing_year_built: JsonScalar = None
    use_code: JsonScalar = None
    use: JsonScalar = None
    property_use: JsonScalar = None
    property_type: JsonScalar = None
    listing_property_type: JsonScalar = None
    lease_use: JsonScalar = None
    units: JsonScalar = None
    unit_count: JsonScalar = None
    number_of_units: JsonScalar = None
    listing_units: JsonScalar = None
    lease_units: JsonScalar = None
    assessed_value_psf_comps: AssessorCompBand | JsonScalar = None
    comp_value_psf: AssessorCompBand | JsonScalar = None
    comparable_value_psf: AssessorCompBand | JsonScalar = None
    market_value_psf: AssessorCompBand | JsonScalar = None
    comps_psf: AssessorCompBand | JsonScalar = None


class AssessorDiscrepancy(ClosedResultModel):
    field: str
    assessor_value: int | float | bool | None = None
    stated_value: int | float | bool | None = None
    difference: float | None = None
    direction_of_tax_impact: str
    appeal_signal: bool
    reason: str
    next_step: str


class AssessorAssumption(ClosedResultModel):
    driver: str
    value: dict[str, JsonScalar]
    source: str


class AssessorAuditResult(ClosedResultModel):
    subject_property: SubjectProperty
    status: str
    record_shape: str
    fields_compared: list[str] = Field(default_factory=list)
    missing_or_uncompared_fields: list[str] = Field(default_factory=list)
    discrepancies: list[AssessorDiscrepancy] = Field(default_factory=list)
    appeal_signal_count: int
    appeal_signals: list[AssessorDiscrepancy] = Field(default_factory=list)
    assessor_implied_value_psf: float | None = None
    caveats: list[str] = Field(default_factory=list)
    assumption_sheet: list[AssessorAssumption] = Field(default_factory=list)
    professional_review_required: bool
    professional_review_flag: bool
    verify_with_county_assessor_or_tax_counsel_before_reliance: bool
    verification_message: str


class AppraisalComparableInput(SubjectProperty):
    id: str | int | None = None
    comp_id: str | int | None = None
    name: str | None = None
    cap_rate: NumericInput = None
    cap_rate_used: NumericInput = None
    cap_rate_pct: NumericInput = None
    rent_psf: NumericInput = None
    rent_psf_used: NumericInput = None
    asking_rent_psf: NumericInput = None


class AppraisalInput(SubjectProperty):
    value: NumericInput = None
    cap_rate_used: NumericInput = None
    rent_psf_used: NumericInput = None
    expenses_used: NumericInput = None
    comps_used: list[AppraisalComparableInput] = Field(default_factory=list)


class AppraisalEvidenceInput(SubjectProperty):
    our_rent_roll_psf: NumericInput = None
    our_noi: NumericInput = None
    our_expenses: NumericInput = None
    our_operating_expenses: NumericInput = None
    expense_total: NumericInput = None
    market_comps: list[AppraisalComparableInput] = Field(default_factory=list)


class AppraisalDivergence(ClosedResultModel):
    field: str
    their_input: NumericResult = None
    our_evidence: NumericResult = None
    delta: int | float | None = None
    delta_pct: float | None = None
    units: str
    materiality: str
    evidence_basis: str
    delta_bps: float | None = None
    market_comp_median_rent_psf: float | None = None
    market_comp_sample_size: int | None = None
    their_comp_count: int | None = None
    market_comp_count: int | None = None
    overlap_count: int | None = None
    additional_market_comps: list[AppraisalComparableInput] = Field(
        default_factory=list
    )
    note: str | None = None


class AppraisalSampleSizes(ClosedResultModel):
    appraisal_comps: int
    market_comps: int


class AppraisalChallengeResult(ClosedResultModel):
    package_type: str
    status: str
    divergence_table: list[AppraisalDivergence] = Field(default_factory=list)
    material_divergence_count: int
    missing_or_unassessable: list[str] = Field(default_factory=list)
    appraisal_inputs: AppraisalInput
    submitted_evidence: AppraisalEvidenceInput
    sample_sizes: AppraisalSampleSizes
    requested_review: str
    rov_framing: str
    mandatory_caveat: str
    honesty: str


class Phase2CostRange(ClosedResultModel):
    low: int
    high: int


class Phase2ScopeItem(ClosedResultModel):
    index: int
    rec_type: str
    location: JsonScalar = None
    medium: JsonScalar = None
    scope_convention: str
    scope_elements: list[str] = Field(default_factory=list)
    cost_range_usd: Phase2CostRange
    status: str
    professional_requirement: str


class Phase2UnknownRecType(ClosedResultModel):
    index: int
    rec_type: str
    location: JsonScalar = None
    medium: JsonScalar = None
    status: str
    reason: str


class Phase2ScopeResult(ClosedResultModel):
    status: str
    scope_items: list[Phase2ScopeItem] = Field(default_factory=list)
    unknown_rec_types: list[Phase2UnknownRecType] = Field(default_factory=list)
    aggregate_cost_range_usd: Phase2CostRange | None = None
    cost_convention: str
    disclaimer: str
    limitations: str


class PermitPropertyFields(ClosedResultModel):
    address: str | None = None
    site_address: str | None = None
    project_address: str | None = None
    property_address: str | None = None
    location_address: str | None = None
    full_address: str | None = None
    street_address: str | None = None
    city: str | None = None
    city_name: str | None = None
    municipality: str | None = None
    state: str | None = None
    state_code: str | None = None
    state_abbr: str | None = None
    zip_code: str | None = None
    zip: str | None = None
    zipcode: str | None = None
    postal_code: str | None = None
    street_number: str | int | None = None
    address_number: str | int | None = None
    house_number: str | int | None = None
    street_direction: str | None = None
    pre_direction: str | None = None
    direction: str | None = None
    street_name: str | None = None
    street: str | None = None
    suffix: str | None = None
    street_suffix: str | None = None
    street_type: str | None = None
    permit_number: JsonScalar = None
    permit_no: JsonScalar = None
    permit_id: JsonScalar = None
    permit_: JsonScalar = None
    record_number: JsonScalar = None
    record_id: JsonScalar = None
    id: JsonScalar = None
    issued_date: JsonScalar = None
    issue_date: JsonScalar = None
    issueddate: JsonScalar = None
    issuance_date: JsonScalar = None
    permit_date: JsonScalar = None
    filing_date: JsonScalar = None
    filed_date: JsonScalar = None
    application_date: JsonScalar = None
    application_start_date: JsonScalar = None
    applied_date: JsonScalar = None
    created_date: JsonScalar = None
    created_at: JsonScalar = None
    date: JsonScalar = None
    type: JsonScalar = None
    permit_type: JsonScalar = None
    work_type: JsonScalar = None
    desc: JsonScalar = None
    description: JsonScalar = None
    work_description: JsonScalar = None
    permit_status: JsonScalar = None


class PermitPropertyInput(PermitPropertyFields):
    pass


class PermitProviderLocation(ClosedResultModel):
    """Known Socrata point encodings used by the supported permit adapters."""

    type: str | None = None
    coordinates: list[int | float] | None = None
    latitude: str | int | float | None = None
    longitude: str | int | float | None = None
    human_address: str | None = None


class PermitProviderFields(PermitPropertyFields):
    """Known first-party permit-provider fields not copied to restricted output."""

    permit_milestone: JsonScalar = None
    review_type: JsonScalar = None
    processing_time: JsonScalar = None
    reported_cost: JsonScalar = None
    pin_list: JsonScalar = None
    # These provider fields are independent spatial carriers.  The restricted
    # permit contract authorizes only the canonical address/city/state/ZIP
    # identity above, so accepting an ignored value here would let a caller
    # pair an in-scope canonical address with out-of-scope spatial metadata.
    # Requiring JSON null preserves the known provider schema while failing
    # closed until each carrier can be authoritatively reconciled.
    census_tract: None = None
    community_area: None = None
    ward: None = None
    latitude: None = None
    longitude: None = None
    xcoordinate: None = None
    ycoordinate: None = None
    location: None = None
    geolocation: None = None
    location1: None = None
    building_fee_paid: JsonScalar = None
    building_fee_subtotal: JsonScalar = None
    building_fee_unpaid: JsonScalar = None
    building_fee_waived: JsonScalar = None
    other_fee_paid: JsonScalar = None
    other_fee_subtotal: JsonScalar = None
    other_fee_unpaid: JsonScalar = None
    other_fee_waived: JsonScalar = None
    subtotal_paid: JsonScalar = None
    subtotal_unpaid: JsonScalar = None
    subtotal_waived: JsonScalar = None
    total_fee: JsonScalar = None
    zoning_fee_paid: JsonScalar = None
    zoning_fee_subtotal: JsonScalar = None
    zoning_fee_unpaid: JsonScalar = None
    zoning_fee_waived: JsonScalar = None
    contact_1_city: JsonScalar = None
    contact_1_name: JsonScalar = None
    contact_1_state: JsonScalar = None
    contact_1_type: JsonScalar = None
    contact_1_zipcode: JsonScalar = None
    contact_2_city: JsonScalar = None
    contact_2_name: JsonScalar = None
    contact_2_state: JsonScalar = None
    contact_2_type: JsonScalar = None
    contact_2_zipcode: JsonScalar = None
    contact_3_city: JsonScalar = None
    contact_3_name: JsonScalar = None
    contact_3_state: JsonScalar = None
    contact_3_type: JsonScalar = None
    contact_3_zipcode: JsonScalar = None
    contact_4_city: JsonScalar = None
    contact_4_name: JsonScalar = None
    contact_4_state: JsonScalar = None
    contact_4_type: JsonScalar = None
    contact_4_zipcode: JsonScalar = None
    contact_5_city: JsonScalar = None
    contact_5_name: JsonScalar = None
    contact_5_state: JsonScalar = None
    contact_5_type: JsonScalar = None
    contact_5_zipcode: JsonScalar = None
    contact_6_city: JsonScalar = None
    contact_6_name: JsonScalar = None
    contact_6_state: JsonScalar = None
    contact_6_type: JsonScalar = None
    contact_6_zipcode: JsonScalar = None
    contact_7_city: JsonScalar = None
    contact_7_name: JsonScalar = None
    contact_7_state: JsonScalar = None
    contact_7_type: JsonScalar = None
    contact_7_zipcode: JsonScalar = None


class PermitProviderAttributes(PermitProviderFields):
    """Closed ArcGIS attributes object for one permit feature."""


class PermitProviderPropertyInput(PermitProviderFields):
    """Closed request-only provider row; unknown fields fail closed."""

    attributes: PermitProviderAttributes | None = None


class PermitInputEnvelope(ClosedResultModel):
    """Closed stalled-permit collection wrapper with one exact collection."""

    status: JsonScalar = None
    city: str | None = None
    count: JsonScalar = None
    permits: list[PermitProviderPropertyInput] | None = None
    results: list[PermitProviderPropertyInput] | None = None
    records: list[PermitProviderPropertyInput] | None = None
    features: list[PermitProviderPropertyInput] | None = None
    items: list[PermitProviderPropertyInput] | None = None
    data: list[PermitProviderPropertyInput] | None = None
    since: JsonScalar = None
    radius_m: JsonScalar = None
    source_endpoint: JsonScalar = None
    source_layer: JsonScalar = None
    dataset_id: JsonScalar = None
    request_url: JsonScalar = None
    app_token_used: JsonScalar = None

    @model_validator(mode="after")
    def _one_collection(self) -> "PermitInputEnvelope":
        collections = (
            self.permits,
            self.results,
            self.records,
            self.features,
            self.items,
            self.data,
        )
        supplied = [collection for collection in collections if collection is not None]
        if len(supplied) != 1 or not supplied[0]:
            raise ValueError("permit envelope must contain one non-empty collection")
        return self


class UnpermittedPermitEnvelopeInput(ClosedResultModel):
    """The exact first-party ``permits_near`` shape accepted by this tool."""

    status: JsonScalar = None
    city: str | None = None
    count: JsonScalar = None
    permits: list[PermitProviderPropertyInput] = Field(min_length=1)
    since: JsonScalar = None
    radius_m: JsonScalar = None
    source_endpoint: JsonScalar = None
    source_layer: JsonScalar = None
    dataset_id: JsonScalar = None
    request_url: JsonScalar = None
    app_token_used: JsonScalar = None
    discovery_hint: str | None = None


class UnpermittedObservedImprovement(ClosedResultModel):
    index: int
    desc: str
    est_year: int | None = None


class UnpermittedPermitMatch(ClosedResultModel):
    permit: PermitPropertyInput
    category_overlap: list[str] = Field(default_factory=list)
    token_overlap: list[str] = Field(default_factory=list)
    observed_year: int | None = None
    permit_year: int | None = None
    year_difference: int | None = None
    basis: str


class UnpermittedMatch(ClosedResultModel):
    observed_improvement: UnpermittedObservedImprovement
    plausible_permits: list[UnpermittedPermitMatch] = Field(default_factory=list)


class UnpermittedFlag(UnpermittedObservedImprovement):
    reason: str
    verification: str
    status: str


class UnpermittedMatchingConvention(ClosedResultModel):
    year_tolerance: int
    text_rule: str
    limit: str


class UnpermittedWorkScreenResult(ClosedResultModel):
    status: str
    flags: list[UnpermittedFlag] = Field(default_factory=list)
    matches: list[UnpermittedMatch] = Field(default_factory=list)
    observed_count: int
    permit_count: int
    permit_history_status: str | None = None
    matching_convention: UnpermittedMatchingConvention
    disclaimer: str


class StalledSignal(ClosedResultModel):
    permit_id: JsonScalar = None
    permit_id_field: str | None = None
    address: str
    normalized_address: str
    address_field: str
    permit_date: str
    date_field: str
    age_days: int
    threshold_days: int
    successor_activity_found: bool
    heuristic_basis: str
    inference_label: str
    source_record_index: int
    record: PermitPropertyInput


class StalledUnrecognizedRecord(ClosedResultModel):
    index: int
    reason: str
    value_type: str | None = None
    available_fields: list[str] = Field(default_factory=list)
    raw_address: JsonScalar = None
    raw_date: JsonScalar = None


class StalledProjectsResult(ClosedResultModel):
    signals: list[StalledSignal] = Field(default_factory=list)
    signal_count: int
    records_evaluated: int
    min_age_days: int
    as_of: str
    heuristic_basis: str
    inference_label: str
    verification_notice: str
    unrecognized_records: list[StalledUnrecognizedRecord] = Field(default_factory=list)
    input_notes: list[str] = Field(default_factory=list)


RESULT_MODEL_EXPORTS: tuple[type[BaseModel], ...] = (
    AlertCheckResult,
    AlertDeal,
    AlertSearchResult,
    AppraisalChallengeResult,
    AppraisalComparableInput,
    AppraisalDivergence,
    AppraisalEvidenceInput,
    AppraisalInput,
    AppraisalSampleSizes,
    ArbitrageEconomics,
    ArbitrageOpportunitiesResult,
    ArbitrageOpportunity,
    ArbitrageProjection,
    ArbitrageScreeningSummary,
    ArbitrageSkippedSpace,
    ArbitrageSpaceInput,
    AssessorAssumption,
    AssessorAuditResult,
    AssessorCompBand,
    AssessorDiscrepancy,
    AssessorOwnerEnvelopeInput,
    AssessorParcelEnvelopeInput,
    AssessorRecordInput,
    AssessorStatedFactsInput,
    BuyerMatchDealInput,
    CompactDealRow,
    CompsResult,
    CompsSubject,
    CompareMarketsResult,
    ContactBroker,
    ContactInfoResult,
    ContactPrincipal,
    ContactRegisteredAgent,
    ControlOpportunitiesResult,
    ControlOpportunity,
    ControlListingInput,
    ControlListingRaw,
    ControlScoreComponents,
    ControlSpread,
    ControlTenantMatch,
    ControlVacancy,
    CoverageSummary,
    DealAnalysisResult,
    DealNote,
    DealSearchResult,
    DedupeCandidateMatch,
    DedupeCandidateReference,
    DedupeGroup,
    DedupeListingRecord,
    DedupeListingsResult,
    DedupePriceHistory,
    EmployerWarnEvent,
    EmployerWarnEventsResult,
    ListDealsResult,
    ListPipelineResult,
    ListSearchesResult,
    LenderMatchDealInput,
    MarketIntelResult,
    Phase2CostRange,
    Phase2ScopeItem,
    Phase2ScopeResult,
    Phase2UnknownRecType,
    PermitInputEnvelope,
    PermitPropertyInput,
    PermitProviderPropertyInput,
    PipelineDealRow,
    PortfolioInputRecord,
    PortfolioMethodology,
    PortfolioOwner,
    PortfolioOwnerScanResult,
    PortfolioProfile,
    PortfolioProperty,
    PortfolioSkippedRecord,
    RankedMarketIntelResult,
    RestrictedAfterTaxResult,
    RestrictedBuyerMatchResult,
    RestrictedDealDocumentsResult,
    RestrictedDealTruthInsufficientResult,
    RestrictedDealTruthReportResult,
    RestrictedOvernightChangesResult,
    RestrictedListing,
    RestrictedLenderMatchResult,
    RestrictedMeetingBriefingResult,
    RestrictedNOIBridgeInsufficientResult,
    RestrictedNOIBridgeResult,
    RestrictedOwnerRecord,
    RestrictedParcelRecord,
    RestrictedRentComparable,
    RestrictedSaleComp,
    RestrictedCounterpartyDossierResult,
    RestrictedDealTimelineResult,
    RestrictedStaleListingSignalsResult,
    RestrictedWorkflowLocation,
    RouteCandidate,
    RouteLeadResult,
    RouteListingInput,
    RouteListingResult,
    SaveSearchResult,
    SavedSearchQuery,
    SavedSearchRow,
    StalledProjectsResult,
    StalledSignal,
    StalledUnrecognizedRecord,
    SubjectProperty,
    TenantProspect,
    TenantProspectDemographics,
    TenantProspectListResult,
    TenantProspectSiteInput,
    UnpermittedFlag,
    UnpermittedMatch,
    UnpermittedMatchingConvention,
    UnpermittedObservedImprovement,
    UnpermittedPermitEnvelopeInput,
    UnpermittedPermitMatch,
    UnpermittedWorkScreenResult,
    ValueProvenance,
)


__all__ = [model.__name__ for model in RESULT_MODEL_EXPORTS]
