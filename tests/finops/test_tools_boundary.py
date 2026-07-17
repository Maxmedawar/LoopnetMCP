"""Black-box checks for the plain, exception-containing finops boundary."""

from __future__ import annotations

import inspect

import pytest

from cre_mcp.finops import tools


def test_finops_tools_are_plain_and_have_explicit_non_variadic_signatures():
    source = inspect.getsource(tools).casefold()
    assert "import fastmcp" not in source
    assert "from fastmcp" not in source
    assert "@mcp" not in source

    forbidden = {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    for name in tools.__all__:
        parameters = inspect.signature(getattr(tools, name)).parameters.values()
        assert not [parameter.name for parameter in parameters if parameter.kind in forbidden]


@pytest.mark.parametrize(
    "invoke",
    [
        lambda path: tools.cash_requirements(45, {}, as_of="2026-07-14"),
        lambda path: tools.detect_assumable(None),
        lambda path: tools.record_lender_profile({}, db_path=path),
        lambda path: tools.match_lenders("not a mapping", db_path=path),
        lambda path: tools.cap_cost_context({}, {}),
        lambda path: tools.prepare_waiver_request(
            {}, {}, {"type": "unsupported", "terms": "none"}
        ),
        lambda path: tools.record_reporting_item("", "", None, "bad", db_path=path),
        lambda path: tools.record_reporting("", "", None, "bad", db_path=path),
        lambda path: tools.reporting_calendar(-1, db_path=path, as_of="2026-07-14"),
        lambda path: tools.reconcile_note_chain("not document mappings"),
    ],
    ids=[
        "cash",
        "assumable",
        "record-lender",
        "match-lender",
        "cap",
        "waiver",
        "record-reporting-item",
        "record-reporting-alias",
        "reporting-calendar",
        "note-chain",
    ],
)
def test_every_finops_tool_contains_invalid_input_as_nonblank_error(tmp_path, invoke):
    result = invoke(tmp_path / "finops-boundary.db")

    assert isinstance(result, dict)
    assert isinstance(result.get("error"), str)
    assert result["error"].strip()
