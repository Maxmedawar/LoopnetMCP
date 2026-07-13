"""Golden snapshots for representative strategy deals."""

import json
from pathlib import Path

from cre_mcp.scoring.engine import score_all
from tests.scoring.builders import context_from_fixture

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "deals"
GOLDEN_PATH = FIXTURE_DIR / "golden.json"


def _snapshot(score) -> dict:
    return {
        "strategy": score.strategy,
        "score": score.score,
        "grade": score.grade,
        "confidence": score.confidence,
        "market_score": score.market_score,
        "rubric_raw_score": score.rubric_result.raw_score,
        "rubric_coverage": score.rubric_result.coverage,
        "disqualified": score.rubric_result.disqualified,
        "disqualifier_hits": score.rubric_result.disqualifier_hits,
        "explanation": score.explanation,
    }


def _actual() -> dict[str, list[dict]]:
    snapshots: dict[str, list[dict]] = {}
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        if path == GOLDEN_PATH:
            continue
        payload = json.loads(path.read_text())
        scores = score_all(context_from_fixture(payload))
        snapshots[payload["id"]] = [_snapshot(score) for score in scores]
    return snapshots


def test_deal_score_golden_snapshots(request):
    actual = _actual()
    if request.config.getoption("--update-golden"):
        GOLDEN_PATH.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")
    expected = json.loads(GOLDEN_PATH.read_text())
    assert actual == expected
    assert len(actual) == 9
    assert {scores[0]["strategy"] for scores in actual.values()} == {
        "nnn_retail",
        "value_add_multifamily",
        "location_retail",
    }
