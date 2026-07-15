from __future__ import annotations

import inspect

from cre_mcp.siteintel import tools


def test_plain_tool_functions_have_explicit_signatures() -> None:
    functions = (
        tools.dedupe_listings,
        tools.trade_area_profile,
        tools.supply_pipeline_signal,
        tools.employer_warn_events,
        tools.retail_gap_note,
    )

    for function in functions:
        assert all(
            parameter.kind is not inspect.Parameter.VAR_KEYWORD
            for parameter in inspect.signature(function).parameters.values()
        )
        assert function.__module__ == "cre_mcp.siteintel.tools"


def test_sync_tool_validation_uses_error_boundary() -> None:
    assert "error" in tools.dedupe_listings([{"source": "only"}])
    assert "error" in tools.trade_area_profile(91, 0)
    assert "error" in tools.retail_gap_note({}, "restaurant")


async def test_async_tool_validation_uses_error_boundary() -> None:
    assert "error" in await tools.supply_pipeline_signal("", 365)
    assert "error" in await tools.employer_warn_events("", None)
