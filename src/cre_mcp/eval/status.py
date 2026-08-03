"""Fail-safe process status for score calibration disclosure."""

from cre_mcp.models.scoring import UNCALIBRATED_DISCLAIMER

# Deliberately defaults false on every process start. A current successful backtest
# must opt the running server in; stale calibration can never suppress the warning.
_score_calibrated = False


def is_score_calibrated() -> bool:
    """Return whether this process has produced a passing calibration report."""
    return _score_calibrated


def set_score_calibrated(value: bool) -> None:
    """Apply the latest backtest result to subsequent score outputs."""
    global _score_calibrated
    _score_calibrated = bool(value)


__all__ = [
    "UNCALIBRATED_DISCLAIMER",
    "is_score_calibrated",
    "set_score_calibrated",
]
