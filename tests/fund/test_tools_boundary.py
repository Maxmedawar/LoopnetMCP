"""Black-box checks for the plain, unregistered fund boundary."""

from __future__ import annotations

import inspect

import pytest

from cre_mcp.fund import tools


@pytest.mark.parametrize(
    "invoke",
    [
        lambda db: tools.compare_jv_structures([], {}),
        lambda db: tools.forecast_capital_calls("bad", db_path=db),
        lambda db: tools.record_fund_mark("A", "bad", 1, "cost", db_path=db),
        lambda db: tools.record_fund_flow("2026-Q2", "other", 1, db_path=db),
        lambda db: tools.nav_report(
            "2026-Q2", 0, 0, cash_source="bank", liabilities_source="ledger", db_path=db
        ),
        lambda db: tools.check_mandate_limits({}, [], {}),
        lambda db: tools.quarterly_investor_report("guaranteed return", db_path=db),
        lambda db: tools.record_investor_touch("", "call", db_path=db),
        lambda db: tools.investor_engagement_report("LP", as_of="bad", db_path=db),
    ],
    ids=[
        "jv",
        "calls",
        "mark",
        "flow",
        "nav",
        "mandate",
        "quarterly-report",
        "touch",
        "engagement",
    ],
)
def test_every_plain_tool_contains_errors(tmp_path, invoke):
    result = invoke(tmp_path / "fund.db")

    assert isinstance(result, dict)
    assert isinstance(result.get("error"), str)
    assert result["error"].strip()


def test_boundary_is_plain_python_without_fastmcp_registration():
    source = inspect.getsource(tools).casefold()

    assert "import fastmcp" not in source
    assert "from fastmcp" not in source
    assert "@mcp" not in source


def test_boundary_happy_path_preserves_governed_ids_and_honesty(tmp_path):
    path = tmp_path / "fund.db"
    mark = tools.record_fund_mark(
        "Asset A",
        "2026-Q2",
        1_000_001,
        "appraisal",
        source_label="appraisal report 44",
        db_path=path,
    )
    flow = tools.record_fund_flow(
        "2026-Q2",
        "distribution",
        10_001,
        investor="LP One",
        attribution="income",
        source_label="administrator ledger 7",
        db_path=path,
    )
    touch = tools.record_investor_touch(
        "LP One",
        "meeting",
        "2026-07-01T00:00:00Z",
        db_path=path,
    )

    assert mark["source_ref"] == {"table": "fund_marks", "id": 1}
    assert flow["source_ref"] == {"table": "fund_flows", "id": 1}
    assert touch["source_ref"] == {"table": "ir_touches", "id": 1}
    engagement = tools.investor_engagement_report(
        "LP One", as_of="2026-07-10T00:00:00Z", db_path=path
    )
    assert "UNCALIBRATED" in engagement["honesty"]
