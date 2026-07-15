"""Plain-wrapper surface and error-boundary checks."""

import inspect

from cre_mcp.valuation import tools


TOOL_FUNCTIONS = (
    tools.suite_rollover_model,
    tools.value_interest_split,
    tools.reconcile_valuation_approaches,
    tools.forced_sale_value,
    tools.incentive_cliff_analysis,
    tools.risk_adjusted_residual,
    tools.insurance_repricing_impact,
)


def test_plain_tools_have_explicit_signatures_and_structured_error_boundary():
    for function in TOOL_FUNCTIONS:
        assert all(
            parameter.kind is not inspect.Parameter.VAR_KEYWORD
            for parameter in inspect.signature(function).parameters.values()
        )

    assert "error" in tools.suite_rollover_model(None)
    assert "error" in tools.value_interest_split(None, None, None)
    assert "error" in tools.reconcile_valuation_approaches(None, None, None)
    assert "error" in tools.forced_sale_value(None, None, None, None)
    assert "error" in tools.incentive_cliff_analysis(None, None)
    assert "error" in tools.risk_adjusted_residual(None, None)
    assert "error" in tools.insurance_repricing_impact(None, None, None)
