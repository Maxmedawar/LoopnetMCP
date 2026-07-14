"""Score-outcome calibration and backtest models."""

from pydantic import BaseModel, Field


class GradeCalibration(BaseModel):
    """Observed outcome rate and uncertainty for one predicted grade band."""

    grade: str
    n: int = Field(ge=0)
    good_outcomes: int = Field(ge=0)
    mean_predicted_score: float
    mean_predicted_probability: float
    actual_good_rate: float
    hit_rate: float
    ci_low: float
    ci_high: float


class CalibrationReport(BaseModel):
    """Honest score calibration diagnostics over a labeled outcome set."""

    n: int = Field(ge=0)
    excluded: int = Field(ge=0)
    by_grade: list[GradeCalibration] = Field(default_factory=list)
    overall_good_rate: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    brier: float | None = None
    discrimination: float | None = None
    discrimination_method: str = "Spearman rank correlation: predicted score vs realized-good outcome"
    curve_monotonic: bool = False
    calibrated: bool = False
    calibration_threshold: int = Field(gt=0)
    caveats: list[str] = Field(default_factory=list)


__all__ = ["CalibrationReport", "GradeCalibration"]
