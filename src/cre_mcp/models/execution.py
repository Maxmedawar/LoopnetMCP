"""Execution-layer offer and letter-of-intent models."""

from typing import Any

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
