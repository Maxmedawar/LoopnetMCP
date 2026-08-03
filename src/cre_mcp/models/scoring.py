"""Declarative scoring-rubric and result models."""

from pydantic import BaseModel, Field

UNCALIBRATED_DISCLAIMER = (
    "Confidence is UNCALIBRATED — this score is a screening signal, not a validated "
    "probability of success. It has not yet been backtested against realized outcomes."
)


class Band(BaseModel):
    up_to: float | None
    score: float


class SignalSpec(BaseModel):
    key: str
    label: str
    extractor: str
    weight: float
    bands: list[Band] = Field(default_factory=list)
    higher_is_better: bool = True
    required: bool = False


class DisqualifierSpec(BaseModel):
    key: str
    predicate: str
    reason_template: str


class Rubric(BaseModel):
    strategy: str
    display_name: str
    signals: list[SignalSpec] = Field(default_factory=list)
    disqualifiers: list[DisqualifierSpec] = Field(default_factory=list)
    include_core: bool = True
    market_weight: float = 0.20


class SignalResult(BaseModel):
    key: str
    raw_value: float | None = None
    normalized: float | None = None
    weighted_points: float = 0.0
    missing: bool = False
    note: str | None = None


class RubricResult(BaseModel):
    strategy: str
    signal_results: list[SignalResult] = Field(default_factory=list)
    disqualified: bool = False
    disqualifier_hits: list[str] = Field(default_factory=list)
    raw_score: float = 0.0
    coverage: float = 0.0


class DealScore(BaseModel):
    strategy: str
    score: float
    grade: str
    confidence: float
    rubric_result: RubricResult
    market_score: float | None = None
    explanation: str
    gated: bool = False
    calibrated: bool = False
    calibration_disclaimer: str | None = UNCALIBRATED_DISCLAIMER
