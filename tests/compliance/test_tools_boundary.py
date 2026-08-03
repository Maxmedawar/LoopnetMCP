"""The unregistered plain-function layer keeps failures structured."""

from cre_mcp.compliance import tools


def test_appeal_tool_converts_missing_required_inputs_to_error() -> None:
    result = tools.build_appeal_package(None, None)

    assert set(result) == {"error"}
    assert "assessment" in result["error"]


def test_insurance_tool_converts_missing_policy_to_error(tmp_path) -> None:
    result = tools.record_claim(
        "missing",
        "carrier",
        "property",
        {"loss_date": "2026-01-01"},
        db_path=tmp_path / "insurance.db",
    )

    assert set(result) == {"error"}
    assert "policy not found" in result["error"]


def test_calendar_and_permit_tools_preserve_error_boundary(tmp_path) -> None:
    calendar_result = tools.upcoming(-1, db_path=tmp_path / "calendar.db")
    permit_result = tools.unpermitted_work_screen(
        [{"desc": "Tenant buildout"}],
        {"status": "OK", "permits": None},
    )

    assert set(calendar_result) == {"error"}
    assert set(permit_result) == {"error"}


def test_phase2_tool_accepts_nullable_optional_findings() -> None:
    result = tools.phase2_scope(None)

    assert "error" not in result
    assert result["scope_items"] == []
    assert "licensed environmental consultant" in result["disclaimer"]
