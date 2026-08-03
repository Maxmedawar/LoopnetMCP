"""Infer owner engagement likelihood from observed transaction trigger events.

Free real feeds (county tax-delinquency, lien, foreclosure, and probate open
data, plus state UCC records) will be wired in later by the orchestrator. CMBS
special-servicing and watchlist data remains an honest paid-data gap requiring
providers such as Trepp or DBRS. This module is intentionally pure and does not
claim access to either source class.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from math import exp, prod

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TriggerType(str, Enum):
    """Observable events that may change an owner's willingness to engage."""

    LOAN_MATURITY = "loan_maturity"
    SPECIAL_SERVICING = "special_servicing"
    DSCR_DECLINE = "dscr_decline"
    TAX_DELINQUENCY = "tax_delinquency"
    LIEN = "lien"
    UCC_FILING = "ucc_filing"
    CODE_VIOLATION = "code_violation"
    LONG_VACANCY = "long_vacancy"
    TENANT_CLOSURE = "tenant_closure"
    TENANT_BANKRUPTCY = "tenant_bankruptcy"
    LEASE_EXPIRATION = "lease_expiration"
    FORECLOSURE_NOTICE = "foreclosure_notice"
    AUCTION_SCHEDULED = "auction_scheduled"
    PROBATE_ESTATE = "probate_estate"
    PRICE_CUT = "price_cut"
    LISTING_WITHDRAWN = "listing_withdrawn"


class SellerPriority(str, Enum):
    """Likely priorities to test during owner outreach."""

    CERTAINTY = "certainty"
    SPEED = "speed"
    TAX_TIMING = "tax_timing"
    DEBT_RELEASE = "debt_release"
    CONFIDENTIALITY = "confidentiality"
    PRICE = "price"


class MotivationSignal(BaseModel):
    """One sourced event relevant to an owner's willingness to transact."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    property_id: str = Field(min_length=1)
    owner_name: str | None = None
    trigger_type: TriggerType
    evidence_source: str = Field(min_length=1)
    evidence_url: str | None = None
    evidence_date: str | None = None
    severity: float = Field(ge=0.0, le=1.0)
    freshness_days: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("evidence_date")
    @classmethod
    def validate_evidence_date(cls, value: str | None) -> str | None:
        """Keep the API's string representation while rejecting non-ISO dates."""

        if value is None:
            return None
        try:
            if "T" in value or value.endswith("Z"):
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            else:
                date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("evidence_date must be an ISO-8601 date or datetime") from exc
        return value


class OwnerMotivation(BaseModel):
    """Evidence-backed estimate of whether an owner will engage now."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    property_id: str
    owner_name: str | None
    engagement_probability: float = Field(ge=0.0, le=1.0)
    inferred_priorities: list[SellerPriority]
    signals: list[MotivationSignal]
    confidence: float = Field(ge=0.0, le=1.0)
    caveats: list[str]


TRIGGER_BASE_SEVERITY: dict[TriggerType, float] = {
    TriggerType.LOAN_MATURITY: 0.62,
    TriggerType.SPECIAL_SERVICING: 0.85,
    TriggerType.DSCR_DECLINE: 0.68,
    TriggerType.TAX_DELINQUENCY: 0.62,
    TriggerType.LIEN: 0.60,
    TriggerType.UCC_FILING: 0.55,
    TriggerType.CODE_VIOLATION: 0.45,
    TriggerType.LONG_VACANCY: 0.42,
    TriggerType.TENANT_CLOSURE: 0.52,
    TriggerType.TENANT_BANKRUPTCY: 0.65,
    TriggerType.LEASE_EXPIRATION: 0.40,
    TriggerType.FORECLOSURE_NOTICE: 0.87,
    TriggerType.AUCTION_SCHEDULED: 0.90,
    TriggerType.PROBATE_ESTATE: 0.50,
    TriggerType.PRICE_CUT: 0.42,
    TriggerType.LISTING_WITHDRAWN: 0.40,
}


TRIGGER_PRIORITIES: dict[TriggerType, list[SellerPriority]] = {
    TriggerType.LOAN_MATURITY: [SellerPriority.DEBT_RELEASE, SellerPriority.SPEED],
    TriggerType.SPECIAL_SERVICING: [
        SellerPriority.DEBT_RELEASE,
        SellerPriority.SPEED,
    ],
    TriggerType.DSCR_DECLINE: [SellerPriority.DEBT_RELEASE, SellerPriority.SPEED],
    TriggerType.TAX_DELINQUENCY: [SellerPriority.SPEED, SellerPriority.CERTAINTY],
    TriggerType.LIEN: [SellerPriority.SPEED, SellerPriority.CERTAINTY],
    TriggerType.UCC_FILING: [SellerPriority.SPEED, SellerPriority.CERTAINTY],
    TriggerType.CODE_VIOLATION: [SellerPriority.CERTAINTY, SellerPriority.PRICE],
    TriggerType.LONG_VACANCY: [SellerPriority.CERTAINTY, SellerPriority.PRICE],
    TriggerType.TENANT_CLOSURE: [SellerPriority.CERTAINTY],
    TriggerType.TENANT_BANKRUPTCY: [SellerPriority.CERTAINTY],
    TriggerType.LEASE_EXPIRATION: [SellerPriority.CERTAINTY],
    TriggerType.FORECLOSURE_NOTICE: [
        SellerPriority.DEBT_RELEASE,
        SellerPriority.SPEED,
    ],
    TriggerType.AUCTION_SCHEDULED: [
        SellerPriority.DEBT_RELEASE,
        SellerPriority.SPEED,
    ],
    TriggerType.PROBATE_ESTATE: [
        SellerPriority.CERTAINTY,
        SellerPriority.CONFIDENTIALITY,
    ],
    TriggerType.PRICE_CUT: [SellerPriority.PRICE],
    TriggerType.LISTING_WITHDRAWN: [SellerPriority.PRICE],
}


_FRESHNESS_HALF_LIFE_DAYS = 180.0
_TRANSACTION_CAVEAT = (
    "Engagement probability estimates willingness to engage; it does not imply "
    "that a transaction will occur."
)
_VERIFICATION_CAVEAT = (
    "Trigger evidence and underlying financial figures must be independently verified."
)


def _signal_weight(signal: MotivationSignal) -> float:
    effective_severity = max(
        signal.severity,
        TRIGGER_BASE_SEVERITY[signal.trigger_type],
    )
    if signal.freshness_days is None:
        return effective_severity
    decay = 0.5 ** (signal.freshness_days / _FRESHNESS_HALF_LIFE_DAYS)
    return effective_severity * decay


def _confidence(signals: list[MotivationSignal]) -> float:
    if not signals:
        return 0.05

    count_score = 1.0 - exp(-len(signals) / 2.0)
    recency_score = sum(
        0.5
        if signal.freshness_days is None
        else 0.5 ** (signal.freshness_days / _FRESHNESS_HALF_LIFE_DAYS)
        for signal in signals
    ) / len(signals)
    evidence_completeness = sum(
        (1.0 + float(bool(signal.evidence_url)) + float(bool(signal.evidence_date)))
        / 3.0
        for signal in signals
    ) / len(signals)

    value = (
        0.05
        + 0.30 * count_score
        + 0.35 * recency_score
        + 0.30 * evidence_completeness
    )
    return min(1.0, max(0.0, value))


def score_motivation(signals: list[MotivationSignal]) -> OwnerMotivation:
    """Estimate engagement probability from real events, not static distress.

    Severity uses the more conservative floor supplied by the trigger table and
    the observed signal. When age is known, each signal decays with a 180-day
    half-life. Independent evidence is combined with a saturating probability
    function so the result remains bounded.
    """

    if not signals:
        return OwnerMotivation(
            property_id="",
            owner_name=None,
            engagement_probability=0.0,
            inferred_priorities=[],
            signals=[],
            confidence=0.05,
            caveats=[
                "No trigger signals were provided; motivation cannot be inferred.",
                _TRANSACTION_CAVEAT,
                _VERIFICATION_CAVEAT,
            ],
        )

    property_ids = list(dict.fromkeys(signal.property_id for signal in signals))
    if len(property_ids) != 1:
        raise ValueError("all motivation signals must refer to the same property_id")

    owner_names = list(
        dict.fromkeys(
            signal.owner_name for signal in signals if signal.owner_name is not None
        )
    )
    owner_name = owner_names[0] if owner_names else None
    weights = [_signal_weight(signal) for signal in signals]
    engagement_probability = 1.0 - prod(1.0 - weight for weight in weights)

    priority_weights: dict[SellerPriority, float] = {}
    first_seen: dict[SellerPriority, int] = {}
    for signal, weight in zip(signals, weights, strict=True):
        for priority in TRIGGER_PRIORITIES[signal.trigger_type]:
            if priority not in first_seen:
                first_seen[priority] = len(first_seen)
            priority_weights[priority] = priority_weights.get(priority, 0.0) + weight
    inferred_priorities = sorted(
        priority_weights,
        key=lambda priority: (-priority_weights[priority], first_seen[priority]),
    )

    caveats = [_TRANSACTION_CAVEAT, _VERIFICATION_CAVEAT]
    if any(signal.freshness_days is None for signal in signals):
        caveats.append(
            "At least one signal has unknown freshness and was not age-decayed."
        )
    if any(
        signal.evidence_url is None or signal.evidence_date is None
        for signal in signals
    ):
        caveats.append("Some evidence metadata is incomplete, reducing confidence.")
    if owner_name is None:
        caveats.append("Owner identity is missing and should be resolved before outreach.")
    if len(owner_names) > 1:
        caveats.append(
            "Signals contain multiple owner names; ownership must be reconciled."
        )

    return OwnerMotivation(
        property_id=property_ids[0],
        owner_name=owner_name,
        engagement_probability=engagement_probability,
        inferred_priorities=inferred_priorities,
        signals=list(signals),
        confidence=_confidence(signals),
        caveats=caveats,
    )
