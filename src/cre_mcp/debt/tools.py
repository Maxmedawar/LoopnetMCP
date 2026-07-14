"""Plain debt-analysis callables for later MCP registration by the director."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Mapping, Sequence

from cre_mcp.debt.assumable import value_assumable_debt as _value_assumable_debt
from cre_mcp.debt.covenants import covenant_forecast as _covenant_forecast
from cre_mcp.debt.refi_vs_assume import compare_capital_paths as _compare_capital_paths
from cre_mcp.debt.termsheet import (
    QUOTED_TERMS_WARNING,
    TermSheet,
    compare_term_sheets as _compare_term_sheets,
)


def _attach_honesty(result: dict[str, Any], assumption_sheet: Mapping[str, Any]) -> dict[str, Any]:
    result["warning"] = QUOTED_TERMS_WARNING
    result["lender_ledger_pointer"] = "lender_track_record"
    result.setdefault("assumption_sheet", dict(assumption_sheet))
    return result


def compare_term_sheets(
    sheets: Iterable[TermSheet | Mapping[str, Any]],
    deal: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare structured quotes; this plain function is intentionally not registered."""
    materialized = list(sheets)
    result = _compare_term_sheets(materialized, deal)
    inputs = [asdict(sheet) if isinstance(sheet, TermSheet) else dict(sheet) for sheet in materialized]
    return _attach_honesty(result, {"term_sheets": inputs, "deal": dict(deal)})


def covenant_forecast(
    loan: TermSheet | Mapping[str, Any],
    noi_path: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    valuation_path: Sequence[Mapping[str, Any] | float] | Mapping[Any, Any] | None = None,
    *,
    base_noi: float | None = None,
    growth: float | None = None,
    periods: int | None = None,
) -> dict[str, Any]:
    """Project covenants; every forward value remains visibly labeled a projection."""
    result = _covenant_forecast(
        loan,
        noi_path,
        valuation_path,
        base_noi=base_noi,
        growth=growth,
        periods=periods,
    )
    raw_loan = asdict(loan) if isinstance(loan, TermSheet) else dict(loan)
    return _attach_honesty(result, {
        "loan": raw_loan,
        "noi_path": noi_path,
        "valuation_path": valuation_path,
        "base_noi": base_noi,
        "growth": growth,
        "periods": periods,
    })


def value_assumable_debt(
    existing_loan: Mapping[str, Any],
    market: Mapping[str, Any],
    price: float | None,
    hold_years: float | None,
) -> dict[str, Any]:
    """Value conditional debt savings; lender approval is never presumed."""
    result = _value_assumable_debt(existing_loan, market, price, hold_years)
    return _attach_honesty(result, {
        "existing_loan": dict(existing_loan),
        "market": dict(market),
        "price": price,
        "hold_years": hold_years,
    })


def compare_capital_paths(
    current_position: Mapping[str, Any],
    options: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare assumption/refi/supplemental/mod/sale paths without registering a tool."""
    result = _compare_capital_paths(current_position, options)
    return _attach_honesty(result, {
        "current_position": dict(current_position),
        "options": options,
    })


__all__ = [
    "compare_capital_paths",
    "compare_term_sheets",
    "covenant_forecast",
    "value_assumable_debt",
]
