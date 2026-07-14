"""Capital-raise CRM, compliance, waterfall, and draft-document models."""

from typing import Any, Literal

from pydantic import BaseModel, Field


InvestorRelationship = Literal["preexisting", "new"]


class InvestorRecord(BaseModel):
    """One prospective investor and the facts needed for preliminary Reg D gates."""

    investor_id: int
    name: str
    accredited: bool | None = None
    accreditation_verified: bool = False
    relationship: InvestorRelationship
    contact: dict[str, Any] | str | None = None
    created_at: str
    updated_at: str
    commitments: list[dict[str, Any]] = Field(default_factory=list)
    total_commitments: float = 0.0


class CommitmentRecord(BaseModel):
    """A non-binding capital indication associated with one persisted deal."""

    commitment_id: int
    deal_id: str
    investor_id: int
    amount: float = Field(gt=0)
    created_at: str
    updated_at: str


class ComplianceCheck(BaseModel):
    """A deterministic preliminary Reg D action gate, never an exemption opinion."""

    allowed: bool
    rule: str
    why: str
    remediation: list[str] = Field(default_factory=list)
    guardrail: str


class WaterfallYear(BaseModel):
    """One year of transparent LP/GP distribution allocation."""

    year: int = Field(gt=0)
    available_cash: float
    lp_preferred_return: float
    lp_return_of_capital: float
    gp_return_of_capital: float
    gp_catch_up: float
    lp_residual: float
    gp_residual: float
    lp_distribution: float
    gp_distribution: float
    unpaid_lp_preferred_return: float
    unreturned_lp_capital: float
    unreturned_gp_capital: float


class WaterfallResult(BaseModel):
    """Scenario waterfall with inspectable allocations and anti-fraud framing."""

    deal_ref: str
    total_equity: float
    lp_contribution: float
    gp_contribution: float
    preferred_return_rate: float
    gp_promote_rate: float
    catch_up: bool
    years: list[WaterfallYear] = Field(default_factory=list)
    lp_cash_flows: list[float] = Field(default_factory=list)
    gp_cash_flows: list[float] = Field(default_factory=list)
    lp_irr_pct: float | None = None
    lp_equity_multiple: float | None = None
    gp_promote_earned: float
    undistributed_cash: float
    assumptions_used: dict[str, Any] = Field(default_factory=dict)
    anti_fraud_warning: str
    guardrail: str


class CapitalDraft(BaseModel):
    """Attorney-review capital document skeleton, never an offering document."""

    document_type: Literal["PPM", "SUBSCRIPTION", "FORM_D"]
    status: Literal["DRAFT — ATTORNEY REVIEW REQUIRED"] = (
        "DRAFT — ATTORNEY REVIEW REQUIRED"
    )
    title: str
    body_markdown: str
    data: dict[str, Any] = Field(default_factory=dict)
    risk_factors: list[str] = Field(default_factory=list)
    anti_fraud_warning: str
    guardrail: str


__all__ = [
    "CapitalDraft",
    "CommitmentRecord",
    "ComplianceCheck",
    "InvestorRecord",
    "InvestorRelationship",
    "WaterfallResult",
    "WaterfallYear",
]
