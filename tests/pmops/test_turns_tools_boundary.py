"""Adversarial checks for unit turns and the plain PM-operations boundary."""

from __future__ import annotations

import inspect
import sqlite3

import pytest

from cre_mcp.pmops import tools
from cre_mcp.pmops.turns import TURN_STAGES, record_turn, turn_board


REQUIRED_TOOLS = {
    "record_workorder",
    "triage_queue",
    "pm_schedule",
    "record_vendor",
    "compare_vendors",
    "repeat_repair_analysis",
    "record_turn",
    "turn_board",
    "deferred_maintenance_screen",
    "balance_validation",
}


def test_turn_board_has_deterministic_day_math_and_critical_path(tmp_path):
    path = tmp_path / "pmops.db"
    recorded = record_turn(
        " 2B ",
        "2026-07-01",
        [
            {
                "item": "Paint walls",
                "status": "in_progress",
                "cost_cents": 125_001,
                "vendor": None,
                "completed_date": None,
                "notes": None,
            }
        ],
        vendor=None,
        target_ready="2026-07-10",
        status="vendor",
        db_path=path,
    )
    assert recorded["unit"] == "2B"
    assert recorded["known_scope_cost_cents"] == 125_001
    assert recorded["unknown_scope_cost_count"] == 0

    # Future move-outs remain visible, but never create negative vacancy days.
    record_turn(
        "3C",
        "2026-07-20",
        [],
        vendor=None,
        target_ready=None,
        status="inspect",
        db_path=path,
    )

    board = turn_board(as_of="2026-07-14", db_path=path)
    first = board["turns"][0]
    second = board["turns"][1]

    assert board["as_of"] == "2026-07-14"
    assert board["critical_path"] == list(TURN_STAGES)
    assert first["unit"] == "2B"
    assert first["days_vacant"] == 13
    assert first["days_past_target"] == 4
    assert first["bottleneck"] is True
    assert "past due" in first["bottleneck_basis"]
    assert first["critical_path"] == [
        {"stage": "inspect", "state": "complete"},
        {"stage": "scope", "state": "complete"},
        {"stage": "vendor", "state": "current"},
        {"stage": "work", "state": "pending"},
        {"stage": "ready", "state": "pending"},
    ]
    assert second["unit"] == "3C"
    assert second["days_vacant"] == 0
    assert second["bottleneck"] is False
    assert "clamped" in second["bottleneck_basis"]
    assert "max(0" in board["days_vacant_formula"]


def test_turn_scope_is_json_and_unknown_or_malformed_fields_are_rejected(tmp_path):
    path = tmp_path / "pmops.db"
    record_turn(
        "101",
        "2026-06-30",
        [{"item": "Flooring", "cost_cents": None, "vendor": None}],
        vendor=None,
        target_ready=None,
        status="scope",
        db_path=path,
    )

    with sqlite3.connect(path) as connection:
        encoded = connection.execute(
            "SELECT scope_items_json FROM pm_turns WHERE unit='101'"
        ).fetchone()[0]
    assert '"cost_cents":null' in encoded
    assert '"vendor":null' in encoded

    with pytest.raises(ValueError, match=r"unrecognized inputs.*scope_items\[0\].*cost"):
        record_turn(
            "102",
            "2026-06-30",
            [{"item": "Flooring", "cost": 100.50}],
            db_path=path,
        )
    with pytest.raises(ValueError, match="integer number of cents"):
        record_turn(
            "102",
            "2026-06-30",
            [{"item": "Flooring", "cost_cents": 100.50}],
            db_path=path,
        )
    with pytest.raises(ValueError, match=r"scope_items\[0\] must be a mapping"):
        record_turn("102", "2026-06-30", ["Flooring"], db_path=path)


def test_tools_are_plain_functions_with_explicit_non_variadic_signatures():
    source = inspect.getsource(tools).casefold()
    assert "import fastmcp" not in source
    assert "from fastmcp" not in source
    assert "@mcp" not in source
    assert REQUIRED_TOOLS == set(tools.__all__)

    forbidden = {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    for name in tools.__all__:
        function = getattr(tools, name)
        assert inspect.isfunction(function), name
        assert not [
            parameter.name
            for parameter in inspect.signature(function).parameters.values()
            if parameter.kind in forbidden
        ], name


def test_every_tool_turns_malformed_inputs_into_an_error_object(tmp_path):
    path = tmp_path / "pmops.db"
    results = [
        tools.record_workorder(None, None, None, None, None, None, None, db_path=path),
        tools.triage_queue(as_of="not-a-date", db_path=path),
        tools.pm_schedule(None, as_of="not-a-date"),
        tools.record_vendor(None, None, db_path=path),
        tools.compare_vendors(None, db_path=path),
        tools.repeat_repair_analysis(window_months=0, db_path=path),
        tools.record_turn(None, None, None, db_path=path),
        tools.turn_board(as_of="not-a-date", db_path=path),
        tools.deferred_maintenance_screen(None),
        tools.balance_validation(None),
    ]

    assert all(isinstance(result, dict) for result in results)
    assert all(isinstance(result.get("error"), str) for result in results)
    assert all(result["error"].strip() for result in results)


def test_tools_surface_nested_unrecognized_input_in_error_object(tmp_path):
    result = tools.record_turn(
        "201",
        "2026-07-01",
        [{"item": "Paint", "cost_cent": 12_000}],
        db_path=tmp_path / "pmops.db",
    )

    assert "error" in result
    assert "unrecognized inputs" in result["error"]
    assert "cost_cent" in result["error"]


def test_tool_error_boundary_dequotes_keys_and_never_returns_blank(monkeypatch):
    def raise_blank(*args, **kwargs):
        raise Exception()

    monkeypatch.setattr(tools, "_turn_board", raise_blank)
    assert tools.turn_board()["error"] == "Exception"

    def raise_key(*args, **kwargs):
        raise KeyError("missing_field")

    monkeypatch.setattr(tools, "_turn_board", raise_key)
    assert tools.turn_board()["error"] == "missing_field"
