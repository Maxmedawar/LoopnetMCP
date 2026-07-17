"""Plain construction-tool boundary and explicit-signature checks."""

from __future__ import annotations

import inspect

from cre_mcp.construction import tools


REQUIRED_TOOLS = {
    "development_budget",
    "compare_proposals",
    "level_bids",
    "reconcile_gmp",
    "forecast_draws",
    "audit_pay_app",
    "ve_option",
    "percent_complete",
    "closeout_register",
}


def test_tools_are_plain_functions_with_explicit_signatures():
    source = inspect.getsource(tools).casefold()
    assert "import fastmcp" not in source
    assert "from fastmcp" not in source
    assert "@mcp" not in source
    assert REQUIRED_TOOLS <= set(tools.__all__)

    forbidden = {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    for name in tools.__all__:
        function = getattr(tools, name)
        assert inspect.isfunction(function), name
        assert not [
            parameter.name
            for parameter in inspect.signature(function).parameters.values()
            if parameter.kind in forbidden
        ], name


def test_tool_boundary_turns_invalid_input_into_structured_errors():
    results = [
        tools.development_budget(None),
        tools.compare_proposals(None, None),
        tools.level_bids(None, None),
        tools.reconcile_gmp(None, None),
        tools.forecast_draws(None, None),
        tools.audit_pay_app(None, None),
        tools.ve_option(None),
        tools.percent_complete(None),
        tools.closeout_register(None),
    ]

    assert all(isinstance(result, dict) for result in results)
    assert all(isinstance(result.get("error"), str) for result in results)
    assert all(result["error"].strip() for result in results)
