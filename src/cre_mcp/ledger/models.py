"""Ledger record models — every row is evidence, cited and dated."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ClaimVerdict = Literal["corroborated", "overridden", "unresolved"]
QuoteStage = Literal["quoted", "term_sheet", "committed", "closed", "died"]
DefectOutcome = Literal["open", "retrade", "kill", "cure", "absorbed", "no_impact"]


class ClaimOutcomeRecord(BaseModel):
    """One counterparty assertion measured against reconciled document truth.

    Recorded for hits and misses alike: ``corroborated`` claims build a
    counterparty's credibility exactly as ``overridden`` ones erode it.
    """

    deal_id: str
    field: str  # canonical field name (noi, base_rent, rentable_sf, ...)
    subject: str | None = None
    counterparty: str | None = None  # broker/seller name when known; deal-level otherwise
    counterparty_role: Literal["broker", "seller", "lender", "unknown"] = "unknown"
    claimed_value: float | str | None
    claimed_doc_kind: str  # om / listing / seller_rep / ...
    proven_value: float | str | None
    proven_doc_kind: str | None = None  # the authority that won (executed_lease, t12, ...)
    verdict: ClaimVerdict
    delta_pct: float | None = None  # |claimed-proven|/proven for numeric claims
    severity: str | None = None  # from the reconciliation conflict, when one existed
    source_document_id: str | None = None
    recorded_at: str


class QuoteRecord(BaseModel):
    """One lender quote and, over time, what actually closed."""

    quote_id: str
    deal_id: str
    lender: str
    stage: QuoteStage = "quoted"
    rate_pct: float | None = None
    proceeds: float | None = None
    ltv_pct: float | None = None
    io_months: int | None = None
    amort_years: int | None = None
    recourse: str | None = None  # full / partial / non-recourse / bad-boy
    prepay: str | None = None
    notes: str | None = None
    # Filled when the loan closes (or dies): the truth column.
    final_rate_pct: float | None = None
    final_proceeds: float | None = None
    final_recourse: str | None = None
    retrade_rate_bps: float | None = None  # final - quoted, positive = worse for borrower
    retrade_proceeds_pct: float | None = None  # (final - quoted)/quoted
    days_quote_to_close: int | None = None
    quoted_at: str
    resolved_at: str | None = None


class DefectRecord(BaseModel):
    """A flagged defect and what it eventually did to the deal."""

    defect_id: str
    deal_id: str
    defect_type: str  # e.g. noi_overstated, sf_mismatch, lease_expiry_cliff, title_lien
    description: str
    severity: str  # info / warning / material / fatal (truth-engine vocabulary)
    discovered_stage: str  # screening / diligence / closing / post_close
    discovered_by: str  # tool or human that flagged it
    outcome: DefectOutcome = "open"
    outcome_notes: str | None = None
    dollar_impact: float | None = None  # signed: negative = cost/price reduction
    flagged_at: str
    resolved_at: str | None = None


class CounterpartyTrackRecord(BaseModel):
    """Aggregated claim accuracy for one counterparty (or one deal).

    Honestly UNCALIBRATED until the sample is real: ``sample_size`` is always
    surfaced and small samples carry an explicit warning.
    """

    counterparty: str | None
    deals: int
    claims_total: int
    claims_corroborated: int
    claims_overridden: int
    accuracy_rate: float | None = None  # corroborated / (corroborated + overridden)
    mean_overstatement_pct: float | None = None  # numeric overridden claims only
    worst_fields: list[dict] = Field(default_factory=list)  # [{field, overridden, mean_delta_pct}]
    sample_warning: str | None = None
