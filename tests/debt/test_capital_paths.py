"""Capital-path table and plain wrapper honesty metadata."""

from cre_mcp.debt.refi_vs_assume import compare_capital_paths
from cre_mcp.debt.tools import compare_term_sheets


def test_sale_path_returns_lazy_taxecon_hook_and_missing_timing():
    result = compare_capital_paths(
        {"price": 1_000_000, "hold_years": 5},
        {"sale-context": {}},
    )
    row = result["paths"][0]

    assert row["path"] == "sale-context"
    assert row["proceeds"]["hook"].endswith("net_sale_proceeds")
    assert row["timing"]["status"] == "not_computable"
    assert row["lender_ledger_pointer"] == "lender_track_record"


def test_plain_tool_wrapper_has_warning_and_scope_without_registration():
    result = compare_term_sheets([], {"noi": 1, "price": 1, "hold_years": 1})

    assert result["status"] == "not_computable"
    assert "quoted terms are not closed terms" in result["warning"]
    assert result["lender_ledger_pointer"] == "lender_track_record"
    assert "PDF term-sheet parsing is not included" in result["scope"]
