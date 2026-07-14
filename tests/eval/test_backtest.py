"""Deterministic calibration, discrimination, and Brier tests."""

import pytest

from cre_mcp.eval.backtest import MIN_CALIBRATION_SAMPLES, backtest


def _grade_rows(grade, score, n, good):
    return [
        {
            "predicted_score": score,
            "predicted_grade": grade,
            "realized_good": index < good,
        }
        for index in range(n)
    ]


def test_large_ordered_a_b_c_dataset_has_good_discrimination_and_calibrates():
    rows = [
        *_grade_rows("A", 95, 50, 45),
        *_grade_rows("B", 75, 50, 35),
        *_grade_rows("C", 60, 50, 15),
    ]

    report = backtest(rows)

    assert report.n >= MIN_CALIBRATION_SAMPLES
    assert report.curve_monotonic is True
    assert report.discrimination is not None
    assert report.discrimination > 0.5
    assert report.calibrated is True
    assert [item.grade for item in report.by_grade] == ["A", "B", "C"]
    assert [item.actual_good_rate for item in report.by_grade] == [0.9, 0.7, 0.3]
    assert all(0 <= item.ci_low <= item.actual_good_rate <= item.ci_high <= 1 for item in report.by_grade)


def test_large_nonmonotonic_random_like_dataset_is_not_calibrated():
    rows = [
        *_grade_rows("A", 95, 50, 25),
        *_grade_rows("B", 75, 50, 40),
        *_grade_rows("C", 60, 50, 10),
    ]

    report = backtest(rows)

    assert report.n >= MIN_CALIBRATION_SAMPLES
    assert report.curve_monotonic is False
    assert report.calibrated is False
    assert any("not monotonic" in caveat for caveat in report.caveats)


def test_brier_and_grade_hit_rate_match_hand_calculation():
    report = backtest(
        [
            {"predicted_score": 80, "predicted_grade": "B", "realized_good": True},
            {"predicted_score": 20, "predicted_grade": "D", "realized_good": False},
        ]
    )

    assert report.brier == pytest.approx(((0.8 - 1) ** 2 + (0.2 - 0) ** 2) / 2)
    assert {item.grade: item.hit_rate for item in report.by_grade} == {
        "B": 1.0,
        "D": 0.0,
    }
    assert report.overall_good_rate == 0.5
    assert report.ci_low < 0.5 < report.ci_high
    assert report.calibrated is False


def test_realized_irr_can_supply_label_and_invalid_rows_are_excluded():
    report = backtest(
        [
            {"predicted_score": 90, "predicted_grade": "A", "realized_irr": 12},
            {"predicted_score": 50, "predicted_grade": "D", "realized_irr": 0.04},
            {"predicted_score": "bad", "predicted_grade": "C", "realized_good": True},
            {"predicted_score": 70, "predicted_grade": "B"},
            {
                "predicted_score": 85,
                "predicted_grade": "B",
                "closed": False,
                "went_bad": False,
            },
        ]
    )

    assert report.n == 2
    assert report.excluded == 3
    assert [item.actual_good_rate for item in report.by_grade] == [1.0, 0.0]
    assert any("2 outcome label(s)" in caveat for caveat in report.caveats)
