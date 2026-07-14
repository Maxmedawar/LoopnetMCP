"""Phase 22 outcome and calibration MCP boundary tests."""

import csv
from unittest.mock import patch

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.eval.status import set_score_calibrated
from cre_mcp.scoring.engine import score
from cre_mcp.scoring.rubrics import RUBRIC_REGISTRY
from cre_mcp.server import mcp
from cre_mcp.tools.eval_tools import backtest_score, record_deal_outcome
from tests.scoring.builders import deal_context


@pytest.fixture(autouse=True)
def _reset_calibration_status():
    set_score_calibrated(False)
    yield
    set_score_calibrated(False)


def _write_calibrated_csv(path):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["predicted_score", "predicted_grade", "realized_good"],
        )
        writer.writeheader()
        for grade, predicted, good_count in (("A", 95, 45), ("B", 75, 35), ("C", 60, 15)):
            for index in range(50):
                writer.writerow(
                    {
                        "predicted_score": predicted,
                        "predicted_grade": grade,
                        "realized_good": index < good_count,
                    }
                )


@pytest.mark.asyncio
async def test_record_outcome_tool_and_accumulated_backtest(tmp_path):
    store = DealStore(tmp_path / "eval.db")
    ctx = deal_context(source_id="eval-deal")
    deal_id = await store.save_deal(
        ctx.listing,
        score=85,
        grade="B",
        strategy="nnn_retail",
    )
    assert deal_id is not None
    with patch("cre_mcp.tools.eval_tools.get_deal_store", return_value=store):
        recorded = await record_deal_outcome(
            deal_id,
            closed=True,
            purchase_price=950_000,
            realized_irr=12,
            realized_equity_multiple=1.7,
            went_bad=False,
        )
        report = await backtest_score()

    assert recorded["status"] == "recorded"
    assert recorded["outcome"]["predicted_score"] == 85
    assert report["n"] == 1
    assert report["calibrated"] is False


@pytest.mark.asyncio
async def test_csv_backtest_calibrates_and_removes_subsequent_score_disclaimer(tmp_path):
    dataset = tmp_path / "calibrated.csv"
    _write_calibrated_csv(dataset)

    report = await backtest_score(str(dataset))
    result = score(deal_context(), RUBRIC_REGISTRY["nnn_retail"])

    assert report["calibrated"] is True
    assert report["discrimination"] > 0.5
    assert result.calibrated is True
    assert result.calibration_disclaimer is None


@pytest.mark.asyncio
async def test_eval_tool_errors_are_error_dicts(tmp_path):
    assert "error" in await backtest_score(str(tmp_path / "missing.csv"))
    store = DealStore(tmp_path / "eval.db")
    with patch("cre_mcp.tools.eval_tools.get_deal_store", return_value=store):
        result = await record_deal_outcome(
            "missing",
            closed=True,
            purchase_price=100_000,
        )
    assert "error" in result


@pytest.mark.asyncio
async def test_phase22_tools_are_registered_and_total_is_forty_seven():
    tools = await mcp.get_tools()
    assert {"backtest_score", "record_deal_outcome"} <= set(tools)
    assert len(tools) == 47
