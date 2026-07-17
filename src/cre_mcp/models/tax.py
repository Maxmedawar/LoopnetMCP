"""Deterministic after-tax return scenario models."""

from typing import Any

from pydantic import BaseModel, Field


class DepreciationYear(BaseModel):
    """One modeled tax year of depreciation and tax-shield treatment."""

    year: int = Field(gt=0)
    building_depreciation: float
    cost_seg_depreciation: float
    bonus_depreciation: float
    total_depreciation: float
    potential_tax_shield: float
    modeled_usable_tax_shield: float


class AfterTaxResult(BaseModel):
    """Pre-tax and after-tax cash-flow comparison with exit-tax decomposition."""

    deal_ref: str
    purchase_price: float
    equity_invested: float
    initial_debt: float
    improvement_basis: float
    land_basis: float
    recovery_period_years: float
    depreciation_schedule: list[DepreciationYear] = Field(default_factory=list)
    total_building_depreciation: float
    total_cost_seg_depreciation: float
    total_depreciation: float
    depreciation_annual: float = Field(
        description="First modeled year's total depreciation, in dollars."
    )
    adjusted_tax_basis_at_exit: float
    exit_sale_price: float
    net_sale_price_before_debt: float
    debt_balance_at_exit: float
    total_gain: float
    unrecaptured_1250_gain: float
    unrecaptured_1250_rate: float
    unrecaptured_1250_tax: float
    recapture_1250: float = Field(
        description="Modeled federal tax on unrecaptured section 1250 gain, in dollars."
    )
    section_1245_recapture: float
    section_1245_recapture_tax: float
    remaining_capital_gain: float
    capital_gains_tax: float
    total_exit_tax: float
    pre_tax_cash_flows: list[float] = Field(default_factory=list)
    after_tax_cash_flows: list[float] = Field(default_factory=list)
    pre_tax_irr: float | None = Field(
        default=None,
        description="Modeled pre-tax IRR in percentage points.",
    )
    after_tax_irr: float | None = Field(
        default=None,
        description="Modeled after-tax IRR in percentage points.",
    )
    # Backward-compatible explicit-unit aliases retained for Phase 20 clients.
    pre_tax_irr_pct: float | None = None
    after_tax_irr_pct: float | None = None
    pre_tax_equity_multiple: float | None = None
    after_tax_equity_multiple: float | None = None
    assumptions_used: dict[str, Any] = Field(default_factory=dict)
    cpa_gate: str


__all__ = ["AfterTaxResult", "DepreciationYear"]
