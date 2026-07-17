"""Typed lease abstractions whose leaves are source-cited claims.

The honesty invariant is deliberately structural: a contractual field is not a
bare scalar.  It is a value plus a verbatim quote, locator, confidence, status,
and source layer.  If the document is silent, the value is ``None`` and the
status is ``missing``; constructors reject contradictory claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ClaimStatus = Literal["stated", "inferred", "missing"]
OptionType = Literal[
    "renew", "extend", "terminate", "expand", "rofr", "rofo", "purchase"
]


@dataclass
class CitedClaim:
    """One lease field with the evidence needed to audit it."""

    value: Any | None = None
    quote: str = ""
    locator: str = ""
    confidence: float = 0.0
    status: ClaimStatus = "missing"
    source: str = "base"

    def __post_init__(self) -> None:
        if self.status not in {"stated", "inferred", "missing"}:
            raise ValueError("claim status must be stated, inferred, or missing")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("claim confidence must be between 0 and 1")
        if len(self.quote) > 200:
            raise ValueError("claim quote must be at most 200 characters")
        if self.status == "missing":
            if self.value is not None:
                raise ValueError("a missing claim cannot carry a value")
            if self.confidence != 0.0:
                raise ValueError("a missing claim must have zero confidence")
        elif self.value is None:
            raise ValueError("a stated or inferred claim must carry a value")

    @classmethod
    def missing(cls, *, source: str = "base") -> CitedClaim:
        return cls(source=source)

    @classmethod
    def stated(
        cls,
        value: Any,
        *,
        quote: str,
        locator: str,
        confidence: float,
        source: str = "base",
    ) -> CitedClaim:
        return cls(value, quote[:200], locator, confidence, "stated", source)

    @classmethod
    def inferred(
        cls,
        value: Any,
        *,
        quote: str,
        locator: str,
        confidence: float,
        source: str = "base",
    ) -> CitedClaim:
        return cls(value, quote[:200], locator, confidence, "inferred", source)


def _missing() -> CitedClaim:
    return CitedClaim.missing()


@dataclass
class Parties:
    landlord: CitedClaim = field(default_factory=_missing)
    tenant: CitedClaim = field(default_factory=_missing)
    guarantor: CitedClaim = field(default_factory=_missing)


@dataclass
class Premises:
    address: CitedClaim = field(default_factory=_missing)
    suite: CitedClaim = field(default_factory=_missing)
    rentable_sf: CitedClaim = field(default_factory=_missing)


@dataclass
class LeaseDates:
    commencement: CitedClaim = field(default_factory=_missing)
    expiration: CitedClaim = field(default_factory=_missing)
    term_months: CitedClaim = field(default_factory=_missing)


@dataclass
class RentPeriod:
    """One stated base-rent period; unavailable columns stay explicitly missing."""

    start: CitedClaim = field(default_factory=_missing)
    end: CitedClaim = field(default_factory=_missing)
    annual: CitedClaim = field(default_factory=_missing)
    monthly: CitedClaim = field(default_factory=_missing)
    psf: CitedClaim = field(default_factory=_missing)
    label: CitedClaim = field(default_factory=_missing)


@dataclass
class Escalations:
    fixed_steps: CitedClaim = field(default_factory=_missing)
    cpi_index: CitedClaim = field(default_factory=_missing)
    cpi_cap_pct: CitedClaim = field(default_factory=_missing)
    cpi_floor_pct: CitedClaim = field(default_factory=_missing)
    cpi_frequency_months: CitedClaim = field(default_factory=_missing)
    percentage_rent: CitedClaim = field(default_factory=_missing)
    percentage_rate: CitedClaim = field(default_factory=_missing)
    percentage_breakpoint: CitedClaim = field(default_factory=_missing)
    percentage_breakpoint_type: CitedClaim = field(default_factory=_missing)


@dataclass
class RecoveryStructure:
    lease_type: CitedClaim = field(default_factory=_missing)
    cam_recovery: CitedClaim = field(default_factory=_missing)
    tax_recovery: CitedClaim = field(default_factory=_missing)
    insurance_recovery: CitedClaim = field(default_factory=_missing)
    cam_cap_pct: CitedClaim = field(default_factory=_missing)
    base_year: CitedClaim = field(default_factory=_missing)
    admin_fee_pct: CitedClaim = field(default_factory=_missing)
    gross_up_pct: CitedClaim = field(default_factory=_missing)


@dataclass
class LeaseOption:
    option_type: CitedClaim = field(default_factory=_missing)
    exercise_window: CitedClaim = field(default_factory=_missing)
    notice_deadline_rule: CitedClaim = field(default_factory=_missing)
    rent_basis: CitedClaim = field(default_factory=_missing)


@dataclass
class Security:
    deposit: CitedClaim = field(default_factory=_missing)
    letter_of_credit: CitedClaim = field(default_factory=_missing)
    guaranty_type: CitedClaim = field(default_factory=_missing)


@dataclass
class Restrictions:
    permitted_use: CitedClaim = field(default_factory=_missing)
    exclusive_use: CitedClaim = field(default_factory=_missing)
    radius: CitedClaim = field(default_factory=_missing)
    co_tenancy: CitedClaim = field(default_factory=_missing)
    go_dark: CitedClaim = field(default_factory=_missing)
    continuous_operation: CitedClaim = field(default_factory=_missing)
    assignment_subletting_consent: CitedClaim = field(default_factory=_missing)


@dataclass
class InsuranceRequirement:
    coverage_type: CitedClaim = field(default_factory=_missing)
    per_occurrence: CitedClaim = field(default_factory=_missing)
    aggregate: CitedClaim = field(default_factory=_missing)
    requirement: CitedClaim = field(default_factory=_missing)


@dataclass
class DefaultCurePeriod:
    default_type: CitedClaim = field(default_factory=_missing)
    cure_days: CitedClaim = field(default_factory=_missing)
    notice_required: CitedClaim = field(default_factory=_missing)


@dataclass
class LeaseAbstract:
    """Standardized clause layer for one effective commercial lease."""

    parties: Parties = field(default_factory=Parties)
    premises: Premises = field(default_factory=Premises)
    dates: LeaseDates = field(default_factory=LeaseDates)
    rent_schedule: list[RentPeriod] = field(default_factory=list)
    escalations: Escalations = field(default_factory=Escalations)
    recovery: RecoveryStructure = field(default_factory=RecoveryStructure)
    options: list[LeaseOption] = field(default_factory=list)
    security: Security = field(default_factory=Security)
    restrictions: Restrictions = field(default_factory=Restrictions)
    insurance_requirements: list[InsuranceRequirement] = field(default_factory=list)
    default_cure_periods: list[DefaultCurePeriod] = field(default_factory=list)
    source_path: str | None = None
    deal_id: str | None = None
    sanitization_redactions: int = 0
    amendment_count: int = 0

    # Common convenience aliases keep call sites readable without weakening the
    # nested model or duplicating state.
    @property
    def landlord(self) -> CitedClaim:
        return self.parties.landlord

    @property
    def tenant(self) -> CitedClaim:
        return self.parties.tenant

    @property
    def guarantor(self) -> CitedClaim:
        return self.parties.guarantor

    @property
    def commencement(self) -> CitedClaim:
        return self.dates.commencement

    @property
    def expiration(self) -> CitedClaim:
        return self.dates.expiration


__all__ = [
    "ClaimStatus",
    "OptionType",
    "CitedClaim",
    "Parties",
    "Premises",
    "LeaseDates",
    "RentPeriod",
    "Escalations",
    "RecoveryStructure",
    "LeaseOption",
    "Security",
    "Restrictions",
    "InsuranceRequirement",
    "DefaultCurePeriod",
    "LeaseAbstract",
]
