"""Adversarial contracts for transparent asset-management arithmetic."""

from __future__ import annotations

import inspect

import pytest

from cre_mcp.assetmgmt import tools
from cre_mcp.assetmgmt.benchmarks import flag_underperformance
from cre_mcp.assetmgmt.capex_rank import prioritize_capex
from cre_mcp.assetmgmt.marginal import marginal_return
from cre_mcp.assetmgmt.noi_forecast import noi_by_tenant, variance_explain
from cre_mcp.assetmgmt.plan import InitiativeStore, business_plan, rank_initiatives
from cre_mcp.assetmgmt.tracker import initiative_tracker
from cre_mcp.assetmgmt.watchlist import portfolio_watchlist


def test_initiative_ranking_exposes_and_matches_the_hand_calculation(tmp_path) -> None:
    store = InitiativeStore(tmp_path / "assetmgmt.db")
    store.upsert_initiative(
        deal_id="deal-rank",
        initiative="Higher value",
        owner=None,
        cost_cents=1_000_000,
        noi_impact_cents_annual=100_000,
        start=None,
        months=None,
        status="planned",
        baseline=None,
    )
    store.upsert_initiative(
        deal_id="deal-rank",
        initiative="Lower value",
        cost_cents=1_500_000,
        noi_impact_cents_annual=100_000,
        status="planned",
    )

    result = rank_initiatives(
        "deal-rank",
        input_cap_rate=0.05,
        execution_success_by_status={"planned": 0.8},
        bandwidth=1,
        store=store,
    )

    higher, lower = result["ranked_initiatives"]
    assert higher["initiative"] == "Higher value"
    assert higher["capitalized_noi_value_cents"] == 2_000_000
    assert higher["value_less_cost_cents"] == 1_000_000
    assert higher["execution_success_probability"] == pytest.approx(0.8)
    assert higher["risk_adjusted_value_cents"] == 800_000
    assert higher["recommended"] is True
    assert lower["risk_adjusted_value_cents"] == 400_000
    assert lower["recommended"] is False
    assert [row["initiative"] for row in result["selected_initiatives"]] == [
        "Higher value"
    ]
    assert "noi_impact_cents_annual / input_cap_rate" in result["formula"]
    assert "bandwidth" in result["conventions"]
    assert "800000 cents" in higher["recommendation_math"]


def test_business_plan_links_owners_milestones_and_the_noi_bridge(tmp_path) -> None:
    store = InitiativeStore(tmp_path / "business-plan.db")
    store.upsert_initiative(
        deal_id="deal-plan",
        initiative="Renew anchor",
        owner="Leasing lead",
        cost_cents=250_000,
        noi_impact_cents_annual=100_000,
        start="2026-02-01",
        months=4,
        baseline={"milestones": ["term sheet", "signed amendment"]},
    )

    result = business_plan(
        "deal-plan",
        2026,
        budget_hooks={"baseline_noi_cents_annual": 5_000_000},
        store=store,
    )

    initiative = result["initiatives"][0]
    assert initiative["owner"] == "Leasing lead"
    assert [item["milestone"] for item in initiative["milestones"]] == [
        "term sheet",
        "signed amendment",
    ]
    assert result["totals"] == {
        "initiative_count": 1,
        "cost_cents": 250_000,
        "noi_impact_cents_annual": 100_000,
    }
    assert result["expected_noi_bridge"]["expected_noi_cents_annual"] == 5_100_000
    assert "baseline_noi_cents_annual +" in result["expected_noi_bridge"][
        "calculation"
    ]


def test_tenant_noi_path_labels_contract_downtime_and_market_rollover() -> None:
    result = noi_by_tenant(
        deal_id=None,
        tenancies=[
            {
                "tenancy_id": "tenant-1",
                "tenant_name": "Anchor",
                "unit": "Suite 1",
                "monthly_contract_rent_cents": 100_000,
                "lease_expiration": "2026-07-31",
                "rollover_downtime_months": 1,
                "monthly_opex_cents": 20_000,
            }
        ],
        market_assumptions={
            "start_period": "2026-07",
            "months": 3,
            "monthly_market_rent_cents": 120_000,
        },
    )

    path = result["per_tenant"][0]["path"]
    assert [row["period"] for row in path] == ["2026-07", "2026-08", "2026-09"]
    assert [row["rent_cents"] for row in path] == [100_000, 0, 120_000]
    assert [row["noi_cents"] for row in path] == [80_000, -20_000, 100_000]
    assert path[0]["rollover_period"] is False
    assert all(row["rollover_period"] for row in path[1:])
    assert all("CONVENTION" in row["rent_basis"] for row in path[1:])
    assert result["source"] == "structured input"
    assert result["assumptions"]["rollover_conventions"]
    assert "contract-or-labeled-rollover" in result["formula"]


def test_variance_decomposition_sums_exactly_to_actual_minus_budget() -> None:
    result = variance_explain(
        budget={
            "potential_rent_cents": 1_000_000,
            "occupancy": 0.80,
            "other_income_cents": 100_000,
            "timing_cents": 10_000,
            "opex_cents": 300_000,
        },
        actuals={
            "potential_rent_cents": 1_200_000,
            "occupancy": 0.75,
            "other_income_cents": 130_000,
            "timing_cents": -10_000,
            "opex_cents": 350_000,
        },
    )

    assert result["budget_noi_cents"] == 610_000
    assert result["actual_noi_cents"] == 670_000
    assert result["total_delta_cents"] == 60_000
    assert result["drivers"] == {
        "occupancy_cents": -50_000,
        "rate_cents": 180_000,
        "opex_cents": -50_000,
        "timing_cents": -20_000,
    }
    assert sum(result["drivers"].values()) == result["total_delta_cents"]
    assert result["decomposition_check"] == {
        "sum_driver_cents": 60_000,
        "total_delta_cents": 60_000,
        "difference_cents": 0,
        "exact": True,
    }
    assert all(line["formula"] and line["numbers"] for line in result["lines"])


def test_variance_rejects_incomplete_vacancy_shape_instead_of_confident_bad_noi() -> None:
    """Director probe: vacancy_pct must not disappear into an opex-only bridge."""

    result = tools.variance_explain(
        budget={
            "gpr_cents": 40_000_000,
            "vacancy_pct": 5,
            "opex_cents": 14_000_000,
        },
        actuals={
            "gpr_cents": 41_000_000,
            "vacancy_pct": 8,
            "opex_cents": 15_000_000,
        },
    )

    messages = result.get("not_computable") or [result.get("error", "")]
    assert messages
    explanation = " ".join(str(message) for message in messages)
    for expected_name in ("potential_rent_cents", "occupancy", "opex_cents"):
        assert expected_name in explanation
    for wrong_name in ("gpr_cents", "vacancy_pct"):
        assert wrong_name in explanation
    assert result.get("total_delta_cents") is None


def test_valid_variance_surfaces_a_stray_typo_without_changing_the_math() -> None:
    result = tools.variance_explain(
        budget={
            "potential_rent_cents": 40_000_000,
            "occupancy": 0.95,
            "opex_cents": 14_000_000,
            "vacnacy_pct": 5,
        },
        actuals={
            "potential_rent_cents": 41_000_000,
            "occupancy": 0.92,
            "opex_cents": 15_000_000,
        },
    )

    assert "error" not in result
    assert result["budget_noi_cents"] == 24_000_000
    assert result["actual_noi_cents"] == 22_720_000
    assert result["total_delta_cents"] == -1_280_000
    assert result["decomposition_check"]["exact"] is True
    assert "budget.vacnacy_pct" in result["unrecognized_inputs"]


def test_noi_by_tenant_surfaces_mapping_typo_without_changing_noi() -> None:
    result = tools.noi_by_tenant(
        tenancies=[
            {
                "tenancy_id": "tenant-one",
                "tenant_name": "Tenant One",
                "unit": "100",
                "monthly_contract_rent_cents": 100_000,
                "monthly_opex_cents": 30_000,
                "lease_expiration": "2026-12-31",
                "monthly_contract_rent_cent": 900_000,
            }
        ],
        market_assumptions={"start_period": "2026-07", "months": 1},
    )

    assert "error" not in result
    assert result["per_tenant"][0]["path"][0]["noi_cents"] == 70_000
    assert (
        "tenancies[0].monthly_contract_rent_cent"
        in result["unrecognized_inputs"]
    )


def test_safety_and_compliance_precede_an_extreme_discretionary_return() -> None:
    result = prioritize_capex(
        [
            {
                "item": "Lobby cosmetics",
                "cost_cents": 1,
                "category": "return",
                "urgency": "critical",
                "noi_or_risk_impact": 1_000_000_000,
            },
            {
                "item": "Low-urgency life-safety repair",
                "cost_cents": 10_000_000,
                "category": "safety",
                "urgency": "low",
                "noi_or_risk_impact": -5_000_000,
            },
            {
                "item": "Accessibility compliance",
                "cost_cents": 9_000_000,
                "category": "compliance",
                "urgency": "medium",
                "noi_or_risk_impact": None,
            },
        ]
    )

    ranked = result["ranked_requests"]
    assert {row["category"] for row in ranked[:2]} == {"safety", "compliance"}
    assert all(row["mandatory_gate"] for row in ranked[:2])
    assert ranked[2]["item"] == "Lobby cosmetics"
    assert "regardless" in result["ordering_convention"].casefold()
    assert result["return_formula"]["simple_annual_return"]


def test_initiative_tracker_reports_exact_cost_noi_and_net_deltas(tmp_path) -> None:
    store = InitiativeStore(tmp_path / "tracker.db")
    store.upsert_initiative(
        deal_id="deal-track",
        initiative="Roof project",
        owner="Asset manager",
        cost_cents=1_000_000,
        noi_impact_cents_annual=100_000,
        baseline={
            "forecast_cost_cents": 1_000_000,
            "forecast_noi_impact_cents": 100_000,
        },
    )

    result = initiative_tracker(
        "deal-track",
        actuals=[
            {
                "initiative": "Roof project",
                "actual_cost_cents": 1_200_000,
                "actual_noi_impact_cents": 80_000,
            }
        ],
        as_of="2026-07-14",
        store=store,
    )

    row = result["initiatives"][0]
    assert row["forecast_cost_cents"] == 1_000_000
    assert row["actual_cost_cents"] == 1_200_000
    assert row["cost_delta_cents"] == 200_000
    assert row["forecast_noi_impact_cents"] == 100_000
    assert row["actual_noi_impact_cents"] == 80_000
    assert row["noi_delta_cents"] == -20_000
    assert row["net_performance_delta_cents"] == -220_000
    assert row["status"] == "behind"
    assert row["delta_math"]["identity_values_cents"] == {
        "cost": {"actual": 1_200_000, "forecast": 1_000_000, "delta": 200_000},
        "noi": {"actual": 80_000, "forecast": 100_000, "delta": -20_000},
        "net": -220_000,
    }
    assert result["totals"]["net_performance_delta_cents"] == -220_000
    assert result["overall_status"] == "behind"
    assert "actual - forecast" in result["conventions"]["cost_delta"]


def test_benchmark_small_sample_uses_thresholds_without_fake_statistics() -> None:
    result = flag_underperformance(
        [
            {
                "deal_id": "underperformer",
                "asset_type": "office",
                "metrics": {
                    "occupancy": 0.70,
                    "opex_psf": 2_000,
                    "collections_rate": 0.80,
                    "noi_psf": 500,
                },
            },
            {
                "deal_id": "healthy-peer",
                "asset_type": "office",
                "metrics": {
                    "occupancy": 0.95,
                    "opex_psf": 1_000,
                    "collections_rate": 0.99,
                    "noi_psf": 1_200,
                },
            },
        ]
    )

    assert result["sample_size"] == 2
    assert result["small_sample"] is True
    assert result["no_fake_statistics"] is True
    assert "n < 5" in result["small_sample_honesty"]
    office_stats = result["cohort_statistics"]["office"]
    assert office_stats["small_sample"] is True
    for metric_stats in office_stats["metrics"].values():
        assert metric_stats["n"] == 2
        assert metric_stats["mean"] is None
        assert metric_stats["standard_deviation"] is None
        assert metric_stats["statistics_used"] is False
    assert result["flags"]
    assert {flag["deal_id"] for flag in result["flags"]} == {"underperformer"}
    assert all(flag["threshold_breach"] for flag in result["flags"])
    assert all(flag["peer_z_score"] is None for flag in result["flags"])
    assert all(flag["peer_z_breach"] is False for flag in result["flags"])


def test_benchmark_surfaces_metric_typo_without_creating_a_false_flag() -> None:
    result = tools.flag_underperformance(
        [
            {
                "deal_id": "healthy-office",
                "asset_type": "office",
                "metrics": {
                    "occupancy": 0.95,
                    "opex_psf": 1_000,
                    "collections_rate": 0.99,
                    "noi_psf": 1_200,
                    "ocupancy": 0.10,
                },
            }
        ]
    )

    assert "error" not in result
    assert result["flags"] == []
    assert "portfolio[0].metrics.ocupancy" in result["unrecognized_inputs"]


def test_marginal_return_time_adjustment_reverses_the_gross_order() -> None:
    result = marginal_return(
        {
            "options": [
                {
                    "use": "Slow larger lift",
                    "cost_cents": 100_000,
                    "expected_noi_delta_cents": 25_000,
                    "months": 24,
                },
                {
                    "use": "Immediate smaller lift",
                    "cost_cents": 100_000,
                    "expected_noi_delta_cents": 18_000,
                    "months": 0,
                },
            ]
        },
        opportunity_cost_rate=0.25,
    )

    ranked = result["ranked_options"]
    assert [row["use"] for row in ranked] == [
        "Immediate smaller lift",
        "Slow larger lift",
    ]
    immediate, slow = ranked
    assert slow["gross_marginal_return"] > immediate["gross_marginal_return"]
    assert slow["discount_factor"] == pytest.approx(1.5625)
    assert slow["present_value_noi_delta_cents"] == 16_000
    assert slow["time_adjusted_marginal_return"] == pytest.approx(0.16)
    assert "months / 12" in result["formula"]["discount_factor"]


def test_watchlist_contains_only_exceptions_and_omits_quiet_assets() -> None:
    result = portfolio_watchlist(
        [
            {
                "asset": "Quiet Center",
                "leases": [
                    {"tenant": "Stable Tenant", "rollover_date": "2028-01-01"}
                ],
                "loan_maturities": [],
                "tax_reassessment_flag": False,
                "insurance_renewals": [],
                "capex_urgents": [],
                "tenant_credit_signals": [],
                "collections": {"billed_cents": 100_000, "collected_cents": 99_000},
            },
            {
                "asset": "Judgment Center",
                "leases": [
                    {"tenant": "Anchor", "rollover_date": "2026-07-20"}
                ],
                "capex_urgents": [{"item": "Fire panel", "urgency": "critical"}],
                "collections": {"billed_cents": 100_000, "collected_cents": 70_000},
            },
        ],
        as_of="2026-07-14",
    )

    exceptions = result["exceptions"]
    assert exceptions == result["items"]
    assert exceptions
    assert {item["asset"] for item in exceptions} == {"Judgment Center"}
    assert {item["category"] for item in exceptions} == {
        "lease_rollover",
        "urgent_capex",
        "collections",
    }
    rollover = next(item for item in exceptions if item["category"] == "lease_rollover")
    assert rollover["days_to_event"] == 6
    assert all(item["why_it_needs_judgment"] for item in exceptions)
    assert result["quiet_asset_count"] == 1
    assert "exceptions only" in result["conventions"]["output_rule"]


def test_watchlist_urgency_sort_puts_critical_work_before_a_distant_event() -> None:
    result = portfolio_watchlist(
        [
            {
                "asset": "Distant Rollover",
                "leases": [{"tenant": "Tenant", "rollover_date": "2026-10-12"}],
            },
            {
                "asset": "Critical Work",
                "capex_urgents": [{"item": "Sprinkler failure", "urgency": "critical"}],
            },
        ],
        as_of="2026-07-14",
    )

    assert [item["asset"] for item in result["exceptions"]] == [
        "Critical Work",
        "Distant Rollover",
    ]
    assert "critical severity" in result["conventions"]["urgency_sort"].casefold()


def test_watchlist_surfaces_mapping_typo_without_polluting_exceptions() -> None:
    result = tools.portfolio_watchlist(
        [
            {
                "asset": "Quiet Typo Asset",
                "loan_maturites": [{"maturity_date": "2026-08-01"}],
            },
            {
                "asset": "Actual Exception",
                "capex_urgents": [
                    {"item": "Failed fire alarm", "urgency": "critical"}
                ],
            },
        ],
        as_of="2026-07-14",
    )

    assert "error" not in result
    assert {item["asset"] for item in result["exceptions"]} == {
        "Actual Exception"
    }
    assert result["quiet_asset_count"] == 1
    assert "exceptions only" in result["conventions"]["output_rule"]
    assert "portfolio[0].loan_maturites" in result["unrecognized_inputs"]


def test_plain_tool_exports_have_explicit_nonvariadic_signatures() -> None:
    assert set(tools.__all__) == {
        "business_plan",
        "flag_underperformance",
        "initiative_tracker",
        "marginal_return",
        "noi_by_tenant",
        "portfolio_watchlist",
        "prioritize_capex",
        "rank_initiatives",
        "upsert_initiative",
        "variance_explain",
    }
    forbidden = {
        inspect.Parameter.VAR_KEYWORD,
        inspect.Parameter.VAR_POSITIONAL,
    }
    for name in tools.__all__:
        function = getattr(tools, name)
        assert inspect.isfunction(function), f"{name} is not a plain function"
        assert not inspect.iscoroutinefunction(function), f"{name} unexpectedly async"
        assert not [
            parameter.name
            for parameter in inspect.signature(function).parameters.values()
            if parameter.kind in forbidden
        ], f"{name} exposes a variadic parameter"

    nullable_defaults = {
        "noi_by_tenant": {"deal_id", "tenancies", "market_assumptions"},
        "initiative_tracker": {"actuals", "from_period", "to_period", "as_of"},
        "flag_underperformance": {"benchmarks"},
        "portfolio_watchlist": {"as_of", "horizons_days"},
    }
    for function_name, parameter_names in nullable_defaults.items():
        parameters = inspect.signature(getattr(tools, function_name)).parameters
        assert all(parameters[name].default is None for name in parameter_names)


@pytest.mark.parametrize(
    ("function", "args"),
    [
        (tools.upsert_initiative, ("", "", 1.5, 0)),
        (tools.business_plan, ("", 2026)),
        (tools.rank_initiatives, ("",)),
        (tools.noi_by_tenant, ()),
        (tools.variance_explain, ({}, {})),
        (tools.prioritize_capex, ("not-a-request-sequence",)),
        (tools.initiative_tracker, ("",)),
        (tools.flag_underperformance, ("not-a-portfolio",)),
        (tools.marginal_return, ({}, 0.10)),
        (tools.portfolio_watchlist, ("not-a-portfolio",)),
    ],
    ids=lambda value: getattr(value, "__name__", None),
)
def test_every_plain_tool_contains_invalid_input_at_the_error_boundary(
    function, args
) -> None:
    result = function(*args)

    assert isinstance(result, dict)
    assert isinstance(result.get("error"), str)
    assert result["error"].strip()
