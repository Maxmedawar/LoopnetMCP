from __future__ import annotations

import inspect

from cre_mcp.mlops import tools


TOOL_NAMES = (
    "open_ml_position",
    "record_ml_flow",
    "ml_position_status",
    "ml_control_scenarios",
    "price_control_option",
    "record_ml_watch_item",
    "ml_breach_report",
    "package_control_exit",
)


def test_mlops_boundaries_are_plain_explicit_functions():
    for name in TOOL_NAMES:
        function = getattr(tools, name)
        assert inspect.isfunction(function)
        assert not inspect.iscoroutinefunction(function)
        assert all(
            parameter.kind is not inspect.Parameter.VAR_KEYWORD
            for parameter in inspect.signature(function).parameters.values()
        )


def test_boundary_returns_only_error_instead_of_raising(tmp_path):
    flow_error = tools.record_ml_flow(
        "missing",
        "2026-07",
        "expense",
        1,
        db_path=tmp_path / "boundary.db",
    )
    watch_error = tools.record_ml_watch_item(
        "ml-x",
        "not_a_watch_type",
        None,
        "high",
        "open",
        db_path=tmp_path / "boundary.db",
    )

    assert set(flow_error) == {"error"}
    assert set(watch_error) == {"error"}
