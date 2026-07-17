"""Underwriting output models."""

from typing import Any

from pydantic import BaseModel, Field


class UnderwritingResult(BaseModel):
    """Standard deal metrics with an explicit known-versus-assumed input echo."""

    noi: float | None = None
    cap_rate: float | None = None
    grm: float | None = None
    price_per_sf: float | None = None
    price_per_unit: float | None = None
    price_vs_replacement: float | None = None
    cash_on_cash: float | None = None
    dscr: float | None = None
    break_even_occupancy: float | None = None
    walt: float | None = None
    annual_debt_service: float | None = None
    exit_value: float | None = None
    unlevered_irr: float | None = None
    levered_irr: float | None = None
    equity_multiple: float | None = None
    tenant_credit_tier: str | None = None
    assumptions_used: dict[str, dict[str, Any]] = Field(default_factory=dict)
