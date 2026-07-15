"""Stable plain-function facade and error-boundary tests."""

from __future__ import annotations

import inspect

import pytest

from cre_mcp.relations import tools


MISSION_NAMES = {
    "counterparty_dossier",
    "who_to_call",
    "meeting_briefing",
    "record_thread_state",
    "stalled_threads",
    "deal_coverage_report",
    "route_lead",
    "challenge_appraisal",
}


def test_tools_are_plain_explicit_functions_without_kwargs_or_registration() -> None:
    assert set(tools.__all__) == MISSION_NAMES
    for name in MISSION_NAMES:
        function = getattr(tools, name)
        assert inspect.isfunction(function), name
        assert function.__module__ == "cre_mcp.relations.tools"
        assert all(
            parameter.kind is not inspect.Parameter.VAR_KEYWORD
            for parameter in inspect.signature(function).parameters.values()
        ), f"{name} must not accept **kwargs"
        assert not hasattr(function, "fn"), f"{name} must not be a registered MCP tool"


@pytest.mark.asyncio
async def test_tools_contain_core_validation_at_exact_error_dict_boundary(tmp_path) -> None:
    path = tmp_path / "boundary.db"
    assert await tools.counterparty_dossier("", db_path=path) == {
        "error": "name cannot be blank"
    }
    invalid_need = await tools.who_to_call(
        {"type": "magician", "deal_context": {}}, db_path=path
    )
    assert set(invalid_need) == {"error"}
    assert "need.type" in invalid_need["error"]
    assert await tools.meeting_briefing("", db_path=path) == {
        "error": "counterparty cannot be blank"
    }
    assert tools.record_thread_state(
        "deal",
        "Seller",
        "inbound",
        "access",
        "2026-07-01T12:00:00+00:00",
        "nobody",
        db_path=path,
    ) == {"error": "awaiting must be us or them"}
    assert tools.stalled_threads(-1, db_path=path) == {
        "error": "days must be a non-negative integer"
    }
    assert tools.deal_coverage_report(0, db_path=path) == {
        "error": "period day count must be positive"
    }
    assert set(tools.route_lead({}, "Alex")) == {"error"}  # type: ignore[arg-type]
    assert tools.challenge_appraisal([], {}) == {  # type: ignore[arg-type]
        "error": "appraisal must be a plain dictionary"
    }
