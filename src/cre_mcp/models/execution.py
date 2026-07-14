"""Execution-layer coaching, diligence, and closing models."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class OfferRecommendation(BaseModel):
    """Negotiation range derived from a deal's current underwriting facts."""

    deal_ref: str
    open_price: float | None = None
    target_price: float | None = None
    walk_price: float | None = None
    open_cap: float | None = None
    target_cap: float | None = None
    walk_cap: float | None = None
    rationale: str
    key_terms: dict[str, Any] = Field(default_factory=dict)
    confidence: float
    caveats: list[str] = Field(default_factory=list)


class LoiDraft(BaseModel):
    """Non-binding, explained LOI draft that is gated for attorney review."""

    deal_ref: str
    buyer_entity: str
    price: float
    earnest_money: float
    dd_days: int
    closing_days: int
    contingencies: list[str] = Field(default_factory=list)
    body_markdown: str
    term_notes: dict[str, str] = Field(default_factory=dict)
    attorney_review_flags: list[str] = Field(default_factory=list)
    disclaimer: str


class BrokerContact(BaseModel):
    """Listing-broker contact details preserved from the source listing."""

    name: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None


class BusinessPrincipal(BaseModel):
    """A public officer or principal returned by a business registry."""

    name: str
    title: str | None = None
    address: str | None = None


class RegisteredAgentContact(BaseModel):
    """Public registered-agent record for an entity owner."""

    name: str
    address: str | None = None
    entity_name: str | None = None
    state: str
    status: str | None = None
    principals: list[BusinessPrincipal] = Field(default_factory=list)
    source_url: str | None = None


class ContactInfo(BaseModel):
    """Free-first broker, owner, and public business-registry contact package."""

    broker: BrokerContact | None = None
    owner_name: str | None = None
    owner_mailing: str | None = None
    entity_type: str | None = None
    registered_agent: RegisteredAgentContact | None = None
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    skiptrace_available: bool = False
    disclaimer: str


class OutreachDraft(BaseModel):
    """Deterministic, deal-specific first-touch coaching draft."""

    deal_ref: str
    channel: Literal["call", "email", "letter"]
    angle: Literal["buyer_direct", "via_broker", "absentee_owner", "off_market"]
    recipient: str
    subject: str | None = None
    opener: str
    value_hook: str
    ask: str
    objection_lines: list[str] = Field(default_factory=list)
    script: str
    guardrail: str


class CounterAdvice(BaseModel):
    """Plain-English read and guarded response to a seller counteroffer."""

    read: str
    verdict: Literal["hold", "counter", "accept", "walk"]
    suggested_counter: dict[str, Any] = Field(default_factory=dict)
    reasoning: list[str] = Field(default_factory=list)
    reply_template: str
    red_flags: list[str] = Field(default_factory=list)


class FinancingOption(BaseModel):
    """One lender type screened against the subject asset and business plan."""

    type: str
    fit: Literal["strong", "possible", "not_eligible"]
    eligible: bool
    typical_ltv_range: tuple[float, float]
    typical_rate: float | None = None
    rate_basis: str
    amort_years: int
    io_available: bool
    recourse: str
    eligibility_note: str
    why_or_why_not: str
    guardrail: str


class BuyerProfile(BaseModel):
    """Buyer financial capacity used for a deterministic lender-gate screen."""

    net_worth: float = Field(ge=0)
    liquid: float = Field(ge=0)
    experience_deals: int = Field(default=0, ge=0)
    credit_tier: str | None = None


class QualificationGate(BaseModel):
    """One explicit lender-screening comparison."""

    name: str
    required: str | float
    buyer_has: str | float
    passed: bool = Field(serialization_alias="pass")


class QualifyResult(BaseModel):
    """Buyer qualification screen with cash needs and remediable gaps."""

    deal_ref: str
    selected_scenario: Literal["agency", "bridge", "bank"]
    cash_to_close: float
    breakdown: dict[str, float] = Field(default_factory=dict)
    gates: list[QualificationGate] = Field(default_factory=list)
    verdict: Literal["qualifies", "needs_partner", "short_on_cash", "no"]
    gaps: list[str] = Field(default_factory=list)
    guidance: str
    guardrail: str


class DebtSizing(BaseModel):
    """DSCR- and LTV-constrained loan proceeds for one deterministic scenario."""

    deal_ref: str
    scenario: Literal["agency", "bridge", "bank"]
    property_value: float
    purchase_price: float
    noi: float | None = None
    max_loan: float
    proceeds: float
    ltv_constraint: float
    dscr_constraint: float | None = None
    binding_constraint: Literal["ltv", "dscr"]
    equity_required: float
    annual_debt_service: float
    dscr: float | None = None
    cash_on_cash: float | None = None
    assumptions_used: dict[str, Any] = Field(default_factory=dict)
    guardrail: str


DDStatus = Literal["not_started", "in_progress", "blocked", "complete", "waived"]


class DDItem(BaseModel):
    """One trackable diligence gate with a novice-readable clear/terminate test."""

    key: str
    label: str
    why: str
    what_clears_it: str
    what_should_make_you_terminate: str
    who_to_hire: str
    due_offset_days: int = Field(ge=0)
    deadline: date
    status: DDStatus = "not_started"


class DDPlan(BaseModel):
    """Asset-aware diligence checklist anchored to a contractual clock."""

    deal_id: str
    deal_ref: str
    asset_class: str
    dd_days: int = Field(gt=0)
    start_date: date
    expiration_date: date
    countdown_summary: str
    items: list[DDItem] = Field(default_factory=list)
    persistence_status: Literal["saved", "unavailable"] = "saved"
    guardrail: str


class ClosingStep(BaseModel):
    """One ordered closing action and its professional/condition gate."""

    order: int = Field(gt=0)
    title: str
    detail: str
    who: str
    gate: str


class ClosingPlan(BaseModel):
    """State-routed closing runway with a prominent anti-wire-fraud protocol."""

    deal_ref: str
    state: str
    closing_mode: str
    state_note: str
    steps: list[ClosingStep] = Field(default_factory=list)
    wire_fraud_warning: str
    red_flags: list[str] = Field(default_factory=list)
    guardrail: str


__all__ = [
    "BrokerContact",
    "BusinessPrincipal",
    "ContactInfo",
    "CounterAdvice",
    "ClosingPlan",
    "ClosingStep",
    "BuyerProfile",
    "DDItem",
    "DDPlan",
    "DDStatus",
    "DebtSizing",
    "FinancingOption",
    "LoiDraft",
    "OfferRecommendation",
    "OutreachDraft",
    "QualificationGate",
    "QualifyResult",
    "RegisteredAgentContact",
]
