"""MCP boundaries for realized outcomes and score calibration."""

from __future__ import annotations

import asyncio
import logging

from cre_mcp.deals.store import get_deal_store
from cre_mcp.eval.backtest import backtest, load_csv
from cre_mcp.eval.status import set_score_calibrated
from cre_mcp.source_rights.output import safe_error_message, safe_source_reference

logger = logging.getLogger(__name__)


async def record_deal_outcome(
    deal_id: str,
    closed: bool,
    purchase_price: float | None = None,
    realized_hold_years: float | None = None,
    realized_irr: float | None = None,
    realized_equity_multiple: float | None = None,
    went_bad: bool | None = None,
    notes: str | None = None,
) -> dict:
    """Persist one realized deal outcome against its frozen predicted score.

    Args:
        deal_id: Existing source-qualified DealStore identifier.
        closed: Whether the acquisition actually closed.
        purchase_price: Actual purchase price; required when closed is true.
        realized_hold_years: Optional realized ownership period.
        realized_irr: Optional realized IRR, as decimal or percentage.
        realized_equity_multiple: Optional realized equity multiple.
        went_bad: Optional explicit adverse-outcome label.
        notes: Optional factual outcome notes.

    Returns:
        The persisted score/outcome row or an error dictionary.
    """
    logger.info(
        "record_deal_outcome called: deal=%s",
        safe_source_reference(deal_id),
    )
    try:
        store = get_deal_store()
        values = {
            "closed": closed,
            "purchase_price": purchase_price,
            "realized_hold_years": realized_hold_years,
            "realized_irr": realized_irr,
            "realized_equity_multiple": realized_equity_multiple,
            "went_bad": went_bad,
            "notes": notes,
        }
        if hasattr(store, "record_outcome_result"):
            outcome = await store.record_outcome_result(deal_id, values)
        else:
            saved = await store.record_outcome(deal_id, values)
            if not saved:
                raise ValueError(
                    f"unknown deal_id or outcome persistence unavailable: {deal_id}"
                )
            outcome = next(
                (
                    item
                    for item in await store.get_outcomes()
                    if item["deal_id"] == deal_id
                ),
                None,
            )
        if outcome is None:
            raise ValueError(
                f"unknown deal_id or outcome persistence unavailable: {deal_id}"
            )
        return {
            "status": "recorded",
            "outcome": outcome,
            "calibration_note": (
                "This observation contributes only when it has a frozen predicted score and "
                "a realized-good, realized-IRR, or went-bad label."
            ),
        }
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("record_deal_outcome error: %s", message)
        return {"error": message}


async def backtest_score(dataset_path: str | None = None) -> dict:
    """Backtest Medawar Deal Scores against a CSV or accumulated outcomes.

    Args:
        dataset_path: Optional CSV with predicted_score and realized_good or realized_irr.
            When omitted, uses outcomes accumulated through record_deal_outcome.

    Returns:
        CalibrationReport with grade hit rates, Brier loss, rank discrimination,
        Wilson confidence intervals, calibration status, and caveats.
    """
    logger.info(
        "backtest_score called: dataset=%s",
        safe_source_reference(dataset_path or "DealStore"),
    )
    try:
        if dataset_path is not None:
            rows = await asyncio.to_thread(load_csv, dataset_path)
        else:
            rows = await get_deal_store().get_outcomes()
        report = await asyncio.to_thread(backtest, rows)
        set_score_calibrated(report.calibrated)
        return report.model_dump(mode="json")
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("backtest_score error: %s", message)
        set_score_calibrated(False)
        return {"error": message}


__all__ = ["backtest_score", "record_deal_outcome"]
