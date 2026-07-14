"""Execution-layer offer, contact, outreach, and negotiation models."""

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


__all__ = [
    "BrokerContact",
    "BusinessPrincipal",
    "ContactInfo",
    "CounterAdvice",
    "LoiDraft",
    "OfferRecommendation",
    "OutreachDraft",
    "RegisteredAgentContact",
]
