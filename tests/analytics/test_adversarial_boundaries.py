"""Cross-module black-box boundary and honesty checks for analytics tools."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from cre_mcp.analytics import tools
from cre_mcp.analytics.costseg import BONUS_WARNING, FILING_REQUIREMENT
from cre_mcp.analytics.envelope import CODE_CAVEAT
from cre_mcp.analytics.lp_exposure import lp_portfolio_exposure
from cre_mcp.analytics.regburden import LEGAL_CAVEAT
from cre_mcp.analytics.trends import HONESTY_NOTICE
from cre_mcp.books.store import BookStore


TOOL_NAMES = (
    "audit_seller_model",
    "cost_seg_preview",
    "trend_bands",
    "regulatory_burden",
    "zoning_envelope",
    "lp_portfolio_exposure",
    "cam_true_up",
    "owner_report",
)


def _call_with_null_required_arguments(function: Any) -> dict[str, Any]:
    positional: list[None] = []
    keyword: dict[str, None] = {}
    for parameter in inspect.signature(function).parameters.values():
        if parameter.default is not inspect.Parameter.empty:
            continue
        if parameter.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }:
            positional.append(None)
        elif parameter.kind == inspect.Parameter.KEYWORD_ONLY:
            keyword[parameter.name] = None
    return function(*positional, **keyword)


def test_tools_are_plain_sync_nonvariadic_functions_without_fastmcp_registration() -> None:
    module_source = inspect.getsource(tools).lower()
    assert "from fastmcp" not in module_source
    assert "import fastmcp" not in module_source
    assert "mcp.tool(" not in module_source

    for name in TOOL_NAMES:
        function = getattr(tools, name)
        assert inspect.isfunction(function), name
        assert not inspect.iscoroutinefunction(function), name
        kinds = {parameter.kind for parameter in inspect.signature(function).parameters.values()}
        assert inspect.Parameter.VAR_POSITIONAL not in kinds, name
        assert inspect.Parameter.VAR_KEYWORD not in kinds, name


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_every_plain_tool_contains_invalid_input_at_error_boundary(tool_name: str) -> None:
    result = _call_with_null_required_arguments(getattr(tools, tool_name))
    assert isinstance(result, dict), tool_name
    assert isinstance(result.get("error"), str) and result["error"], (tool_name, result)


def test_nullable_optional_defaults_remain_unknown_or_disabled_not_invented() -> None:
    costseg = tools.cost_seg_preview(
        1_000_000,
        20,
        [{"class": "5yr", "pct": 100}],
    )
    assert costseg["apply_bonus"] is False
    assert costseg["bonus_rate"] == 0

    envelope = tools.zoning_envelope(
        {
            "lot": {"sf": 10_000, "width": 100, "depth": 100},
            "setbacks": {"front": 0, "side": 0, "rear": 0},
            "far": None,
            "max_height_ft": None,
            "parking_ratio": None,
        }
    )
    assert envelope["modeled_gba_sf"] is None
    assert envelope["parking_implied_land_take_sf"] is None

    exposure = tools.lp_portfolio_exposure(
        [
            {
                "sponsor": "Sponsor A",
                "asset_type": "retail",
                "market": "Phoenix",
                "equity_cents": 10_000,
            }
        ]
    )
    assert exposure["unknown_debt_maturity_equity_cents"] == 10_000
    assert exposure["unknown_tenant_concentration_equity_cents"] == 10_000


def test_exact_honesty_and_professional_caveats_survive_plain_tool_boundaries() -> None:
    trend = tools.trend_bands(
        [
            {"period": 2022, "value": 1},
            {"period": 2023, "value": 2},
            {"period": 2024, "value": 3},
            {"period": 2025, "value": 4},
        ],
        2,
    )
    assert trend["honesty"] == HONESTY_NOTICE
    assert HONESTY_NOTICE == (
        "extrapolation of history, NOT a forecast; bands show past variability only."
    )

    envelope = tools.zoning_envelope(
        {
            "lot": {"sf": 10_000, "width": 100, "depth": 100},
            "setbacks": {"front": 0, "side": 0, "rear": 0},
        }
    )
    assert envelope["caveat"] == CODE_CAVEAT
    assert CODE_CAVEAT.startswith(
        "code values must come from the adopted code — see zoning_code_link"
    )

    costseg = tools.cost_seg_preview(
        100_000,
        0,
        [{"class": "5yr", "pct": 1}],
    )
    assert costseg["filing_requirement"] == FILING_REQUIREMENT
    assert FILING_REQUIREMENT == (
        "engineering-based cost-seg study + CPA required for filing"
    )
    assert BONUS_WARNING in costseg["warnings"]

    regulatory = tools.regulatory_burden(["New York City"])
    assert regulatory["honesty"] == LEGAL_CAVEAT


def test_unknown_maturity_rolls_up_but_never_becomes_a_concentration_flag() -> None:
    result = lp_portfolio_exposure(
        [
            {
                "sponsor": "Sponsor A",
                "asset_type": "retail",
                "market": "Phoenix",
                "equity_cents": 90_000,
                "debt_maturity": None,
                "tenant_concentration": None,
            },
            {
                "sponsor": "Sponsor B",
                "asset_type": "industrial",
                "market": "Dallas",
                "equity_cents": 10_000,
                "debt_maturity": "2030-06-30",
                "tenant_concentration": 0.10,
            },
        ],
        thresholds={"maturity_year": 0.25},
    )

    assert result["by_maturity_year"]["UNKNOWN"]["equity_cents"] == 90_000
    assert not any(
        flag["dimension"] == "maturity_year" and flag["value"] == "UNKNOWN"
        for flag in result["concentration_flags"]
    )


def test_unrecognized_inputs_are_visible_across_structured_calculators() -> None:
    trend = tools.trend_bands(
        [
            {"period": "one", "value": 1, "vaule": 999},
            {"period": "two", "value": 2},
        ],
        1,
    )
    assert trend["unrecognized_inputs"] == ["series[0].vaule"]

    envelope = tools.zoning_envelope(
        {
            "lot": {"sf": 10_000, "width": 100, "depth": 100},
            "setbacks": {"front": 0, "side": 0, "rear": 0},
            "overlay_typo": "not silently used",
        }
    )
    assert envelope["unrecognized_inputs"] == ["code_params.overlay_typo"]

    costseg = tools.cost_seg_preview(
        100_000,
        0,
        [{"class": "5yr", "pct": 100, "seller_guess": 50}],
    )
    assert costseg["unrecognized_inputs"] == ["components[0].seller_guess"]

    exposure = tools.lp_portfolio_exposure(
        [
            {
                "sponsor": "Sponsor A",
                "asset_type": "retail",
                "market": "Phoenix",
                "equity_cents": 1,
                "sponser": "typo",
            }
        ]
    )
    assert exposure["error"]
    assert exposure["unrecognized_inputs"] == ["positions[0].sponser"]

    cam_unknown = tools.cam_true_up(
        {
            "tenancy_id": "tenancy-1",
            "tenant_name": "Tenant One",
            "estimated_billed_cents": 24_000,
            "tenat_typo": "visible",
        },
        "Tenant shall pay Tenant's Proportionate Share (50%) of Common Area Maintenance costs.",
        {"cam": 1_000},
    )
    assert cam_unknown["unrecognized_inputs"] == ["tenancy.tenat_typo"]

    cost_unknown = tools.cam_true_up(
        {"tenancy_id": "tenancy-1", "estimated_billed_cents": 24_000},
        "Tenant shall pay Tenant's Proportionate Share (50%) of Common Area Maintenance costs.",
        {"cam": 1_000, "cost_typo": "visible"},
    )
    assert cost_unknown["unrecognized_inputs"] == ["actual_costs.cost_typo"]


def test_cam_dollar_and_cent_inputs_produce_same_penny_exact_true_up() -> None:
    tenancy = {"tenancy_id": "tenancy-1", "estimated_billed_cents": 20_000}
    terms = (
        "Tenant shall pay Tenant's Proportionate Share (50%) of Common Area "
        "Maintenance costs."
    )
    dollars = tools.cam_true_up(tenancy, terms, {"cam": 1_000})
    cents = tools.cam_true_up(tenancy, terms, {"cam_cents": 100_000})

    for result in (dollars, cents):
        assert result["actual_cam_cost_cents"] == 100_000
        assert result["recoverable_after_cap_cents"] == 50_000
        assert result["estimated_billed_cents"] == 20_000
        assert result["true_up_cents"] == 30_000
        assert result["audit_steps"][-1]["formula"] == (
            "actual_recovery_cents - estimated_billed_cents"
        )
        assert all(step["source_tag"]["read_only"] is True for step in result["audit_steps"])


def test_owner_report_tags_every_structured_figure_including_nulls(tmp_path) -> None:
    database = tmp_path / "owner-report.sqlite3"
    books = BookStore(database)
    books.setup_tenancy(
        tenancy_id="owner-tenant",
        deal_id="deal-owner-report",
        unit="100",
        tenant_name="Owner Report Tenant",
    )
    books.add_charge(
        charge_id="owner-rent",
        tenancy_id="owner-tenant",
        period="2026-01",
        kind="rent",
        amount_cents=100_001,
        source="schedule",
        source_detail={"lease_ref": "owner-lease", "citation": "Base Rent"},
    )
    result = tools.owner_report(
        "2026-01",
        "deal-owner-report",
        db_path=database,
    )
    assert "error" not in result

    def assert_figure(figure: dict[str, Any]) -> None:
        assert set(("value", "unit", "source_tag", "source")) <= set(figure)
        assert isinstance(figure["source"], str) and "read-only" in figure["source"]
        assert figure["source_tag"]["module"]
        assert figure["source_tag"]["detail"]
        assert figure["source_tag"]["read_only"] is True

    for figure in result["collections"]["figures"].values():
        assert_figure(figure)
    assert result["collections"]["figures"]["billed_cents"]["value"] == 100_001
    assert_figure(result["collections"]["integrity_gap_count"])
    assert_figure(result["collections"]["tenancy_count"])
    assert result["variance"]["status"] == "NOT_AVAILABLE"
    assert all(
        figure["value"] is None for figure in result["variance"]["figures"].values()
    )
    assert result["initiatives"]["status"] == "not_assessable"
    for figure in result["initiatives"]["figures"].values():
        assert_figure(figure)
    assert result["source_tagging"] == (
        "Every monetary, count, boolean, and status figure has an explicit "
        "read-only source tag."
    )


def test_audit_tool_rejects_nullable_path_without_touching_filesystem() -> None:
    result = tools.audit_seller_model(None)
    assert result == {"error": "xlsx_path is required"}
    assert not Path("None").exists()
