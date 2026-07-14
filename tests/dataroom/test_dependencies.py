"""Dependency topology, blockers, critical path, and closing-runway tests."""

from datetime import date

import pytest

from cre_mcp.dataroom.dependencies import DependencyStore


def test_due_task_surfaces_its_incomplete_prerequisite(dataroom_db):
    store = DependencyStore(dataroom_db)
    store.upsert_task(
        "fixture:blocker", "access", "Secure access",
        deadline="2026-07-13", owner="seller", status="not_started", critical=True,
    )
    store.upsert_task(
        "fixture:blocker", "appraisal", "Complete appraisal",
        depends_on=["access"], deadline="2026-07-14", owner="lender", critical=True,
    )

    result = store.critical_path("fixture:blocker", as_of="2026-07-14")

    assert result["topological_order"] == ["access", "appraisal"]
    assert result["current_blockers"] == [
        {
            "blocked_task_key": "appraisal",
            "blocked_task_label": "Complete appraisal",
            "blocked_task_deadline": "2026-07-14",
            "prerequisite_task_key": "access",
            "prerequisite_label": "Secure access",
            "prerequisite_status": "not_started",
            "prerequisite_owner": "seller",
            "reason": "incomplete prerequisite of a due task",
        }
    ]


def test_cycle_detection_is_an_explicit_error(dataroom_db):
    store = DependencyStore(dataroom_db)
    store.upsert_task(
        "fixture:cycle", "a", "A", depends_on=["b"],
        deadline="2026-07-14", critical=True,
    )
    store.upsert_task(
        "fixture:cycle", "b", "B", depends_on=["a"],
        deadline="2026-07-14", critical=True,
    )

    with pytest.raises(ValueError, match="dependency cycle detected"):
        store.critical_path("fixture:cycle", as_of="2026-07-14")


def test_longest_critical_path_is_dependency_ordered(dataroom_db):
    store = DependencyStore(dataroom_db)
    for key, dependencies, critical in (
        ("access", [], True),
        ("appraisal", ["access"], True),
        ("approval", ["appraisal"], True),
        ("side_task", [], False),
    ):
        store.upsert_task(
            "fixture:path", key, key.replace("_", " ").title(),
            depends_on=dependencies, deadline="2026-07-20",
            owner="owner", critical=critical,
        )

    result = store.critical_path("fixture:path", as_of="2026-07-14")

    assert result["critical_path"] == ["access", "appraisal", "approval"]
    assert result["topological_order"].index("access") < result["topological_order"].index("appraisal")
    assert result["topological_order"].index("appraisal") < result["topological_order"].index("approval")
    assert "duration-free" in result["critical_path_convention"]


def test_standard_template_encodes_access_appraisal_estoppel_financing_order(dataroom_db):
    store = DependencyStore(dataroom_db)
    initialized = store.init_transaction_plan(
        "fixture:template", "retail_nnn", date(2026, 8, 31)
    )
    result = store.critical_path("fixture:template", as_of="2026-07-01")
    order = result["topological_order"]
    by_key = {task["task_key"]: task for task in initialized["tasks"]}

    assert order.index("property_access") < order.index("appraisal")
    assert order.index("request_estoppels") < order.index("receive_estoppels")
    assert order.index("appraisal") < order.index("financing_approval")
    assert order.index("receive_estoppels") < order.index("financing_approval")
    assert "appraisal" in by_key["financing_approval"]["depends_on"]
    assert initialized["dependency_inference"] == "CONVENTION"


def test_single_point_of_failure_calls_out_unassigned_and_sole_dependency(dataroom_db):
    store = DependencyStore(dataroom_db)
    store.upsert_task(
        "fixture:spof", "access", "Access", deadline="2026-07-13",
        owner=None, critical=True,
    )
    store.upsert_task(
        "fixture:spof", "appraisal", "Appraisal", depends_on=["access"],
        deadline="2026-07-14", owner="lender", critical=True,
    )

    result = store.critical_path("fixture:spof", as_of="2026-07-14")
    reasons = {(item["task_key"], item["reason"]) for item in result["single_points_of_failure"]}

    assert ("access", "unassigned_critical_task") in reasons
    assert ("access", "sole_incomplete_prerequisite") in reasons


def test_closing_runway_is_last_seven_days_and_keeps_external_blocker(dataroom_db):
    store = DependencyStore(dataroom_db)
    store.upsert_task(
        "fixture:runway", "outside", "Outside task", deadline="2026-07-23",
        owner="counsel", critical=True,
    )
    store.upsert_task(
        "fixture:runway", "window_start", "Window task", depends_on=["outside"],
        deadline="2026-07-24", owner="counsel", critical=True,
    )
    store.upsert_task(
        "fixture:runway", "close", "Close", depends_on=["window_start"],
        deadline="2026-07-31", owner="escrow", critical=True,
    )

    result = store.closing_runway("fixture:runway", as_of="2026-07-23")

    assert result["closing_date"] == "2026-07-31"
    assert result["window_start"] == "2026-07-24"
    assert result["task_keys"] == ["window_start", "close"]
    assert result["blocking_prerequisites"][0]["prerequisite_task_key"] == "outside"
    assert result["blocking_prerequisites"][0]["prerequisite_in_runway"] is False


def test_empty_dependency_plan_is_honest(dataroom_db):
    result = DependencyStore(dataroom_db).critical_path(
        "fixture:none", as_of="2026-07-14"
    )

    assert result["initialized"] is False
    assert result["critical_path"] == []
    assert result["current_blockers"] == []
    assert "No transaction dependency plan" in result["note"]
