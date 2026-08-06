"""Entity-structure and guarded 1031 exchange models."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class StructureIntent(BaseModel):
    """User intent used for deterministic structure screening."""

    mode: Literal["solo", "1031", "syndication", "oz"]
    investors: int = Field(default=0, ge=0)
    passive: bool | None = None
    state: str | None = None


class StructureAdvice(BaseModel):
    """Non-binding structure screen with explicit eligibility traps and counsel gate."""

    intent: StructureIntent
    recommended: Literal["LLC", "DST", "TIC", "QOF"]
    rationale: str
    alternatives: list[str] = Field(default_factory=list)
    eligibility_notes: dict[str, str] = Field(default_factory=dict)
    traps: list[str] = Field(default_factory=list)
    authorities: list[str] = Field(default_factory=list)
    counsel_gate: str
    disclaimer: str


class ExchangeReplacement(BaseModel):
    """One formally tracked replacement-property candidate."""

    deal_id: str
    value: float | None = None
    identified_at: date


class Exchange(BaseModel):
    """Persistent 1031 clock and identification status."""

    exchange_id: int | str
    relinquished_deal_id: str
    relinquished_close_date: date
    identification_deadline: date
    exchange_deadline: date
    days_to_identification_deadline: int
    days_to_exchange_deadline: int
    identification_locked: bool
    status: Literal[
        "planned",
        "identification_open",
        "identification_locked",
        "expired",
    ]
    replacements: list[ExchangeReplacement] = Field(default_factory=list)
    identification_rule_status: str
    next_action: str
    deadline_caveat: str
    qi_gate: str
    cpa_gate: str
    disclaimer: str


class BootBasisResult(BaseModel):
    """Simplified boot and carryover-basis estimate for CPA verification."""

    relinquished_price: float
    relinquished_adjusted_basis: float
    relinquished_debt: float
    replacement_price: float
    replacement_debt: float
    relinquished_equity: float
    replacement_equity: float
    realized_gain: float
    cash_boot: float
    debt_boot: float
    estimated_boot: float
    estimated_taxable_boot: float
    taxable_boot_flag: bool
    deferred_gain: float
    estimated_carryover_basis: float
    replacement_value_test_passed: bool
    debt_replaced_or_cash_offset_test_passed: bool
    assumptions: list[str] = Field(default_factory=list)
    qi_gate: str
    cpa_gate: str
    disclaimer: str


__all__ = [
    "BootBasisResult",
    "Exchange",
    "ExchangeReplacement",
    "StructureAdvice",
    "StructureIntent",
]
