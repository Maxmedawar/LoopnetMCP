"""Adversarial workflow tests for penny math, composition, and provenance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.analytics.workflows import cam_true_up, owner_report
from cre_mcp.assetmgmt.plan import InitiativeStore
from cre_mcp.books.store import BookStore
from cre_mcp.leases.models import CitedClaim
from cre_mcp.leases.recoveries import CAMCap, ProRataShare, RecoveryTerms


def _claim(value: Any, quote: str) -> CitedClaim:
    return CitedClaim.stated(
        value,
        quote=quote,
        locator="test executed lease p.14",
        confidence=1.0,
    )


def _capped_terms() -> RecoveryTerms:
    return RecoveryTerms(
        cam_recovery=_claim("pro_rata", "Tenant pays pro rata CAM."),
        cam_cap=CAMCap(
            pct=_claim(0.05, "CAM increases are capped at five percent."),
            cumulative_vs_noncumulative=_claim(
                "noncumulative", "The cap is non-cumulative."
            ),
            over_base_vs_yoy=_claim("yoy", "The cap is year-over-year."),
        ),
        admin_fee_pct=_claim(0.10, "A ten percent administrative fee applies."),
        pro_rata_share=ProRataShare(
            stated_pct=_claim(0.50, "Tenant's pro rata share is fifty percent.")
        ),
    )


def _simple_terms() -> RecoveryTerms:
    return RecoveryTerms(
        cam_recovery=_claim("pro_rata", "Tenant pays pro rata CAM."),
        pro_rata_share=ProRataShare(
            stated_pct=_claim(1.0, "Tenant's pro rata share is one hundred percent.")
        ),
    )


def _assert_figure(figure: Mapping[str, Any]) -> None:
    assert "value" in figure
    assert isinstance(figure.get("source"), str)
    assert figure["source"]


def _assert_all_numbers_are_source_tagged(value: Any, path: str = "report") -> None:
    """Reject a naked report number unless it is the value leaf of a source figure."""

    if isinstance(value, Mapping):
        if "value" in value:
            _assert_figure(value)
            return
        for key, item in value.items():
            _assert_all_numbers_are_source_tagged(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _assert_all_numbers_are_source_tagged(item, f"{path}[{index}]")
        return
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    assert not isinstance(value, (int, float)), f"naked numeric figure at {path}"


def test_cam_true_up_cap_billed_and_audit_step_identities_are_penny_exact() -> None:
    result = cam_true_up(
        {
            "tenancy_id": "tenant-1",
            "tenant_name": "Penny Retailer",
            "estimated_billed_cents": 25_000,
        },
        _capped_terms(),
        # Integer cost-pool units preserve cents through the recovery calculator.
        {"cam": {"current": 100_001, "prior": 50_000}},
        period="2026-01",
    )

    # CAM cap: 50,000 prior × 1.05 = 52,500 eligible pool.
    # Tenant share: 52,500 × 50% = 26,250; admin: 2,625.
    assert result["status"] == "TENANT_OWES"
    assert result["actual_cam_cost_cents"] == 100_001
    assert result["cap_eligible_cam_cents"] == 52_500
    assert result["cap_reduction_cents"] == 47_501
    assert result["actual_recovery_cents"] == 28_875
    assert result["estimated_billed_cents"] == 25_000
    assert result["true_up_cents"] == 3_875

    steps = result["audit_steps"]
    assert [step["step"] for step in steps] == list(range(1, 8))
    assert [step["name"] for step in steps] == [
        "actual_cam_pool",
        "cap_test",
        "tenant_share",
        "admin_fee",
        "actual_recovery",
        "estimated_billed",
        "true_up",
    ]
    assert steps[1]["input_cents"] - steps[1]["result_cents"] == steps[1][
        "cap_reduction_cents"
    ]
    assert steps[2]["result_cents"] + steps[3]["result_cents"] == steps[4][
        "result_cents"
    ]
    assert steps[4]["result_cents"] - steps[5]["result_cents"] == steps[6][
        "result_cents"
    ]
    assert all(step["formula"] and step["source"] for step in steps)
    assert result["source_tags"]["recovery"]
    assert result["source_tags"]["billed"]


def test_cam_true_up_converts_lease_module_dollars_to_integer_cents() -> None:
    result = cam_true_up(
        {"tenancy_id": "tenant-dollar", "estimated_billed_cents": 0},
        _simple_terms(),
        {"cam": 1_000.01},
    )

    # leases.recoveries uses dollar amounts.  The workflow boundary promises
    # integer-cent output, so $1,000.01 must not become a rounded 1,000 cents.
    assert result["actual_cam_cost_cents"] == 100_001
    assert result["cap_eligible_cam_cents"] == 100_001
    assert result["actual_recovery_cents"] == 100_001
    assert result["true_up_cents"] == 100_001
    assert all(isinstance(result[key], int) for key in (
        "actual_cam_cost_cents",
        "actual_recovery_cents",
        "estimated_billed_cents",
        "true_up_cents",
    ))


def test_cam_true_up_structured_unknown_null_and_money_errors_are_contained() -> None:
    unrecognized_tenancy = cam_true_up(
        {
            "tenancy_id": "tenant-typo",
            "estimated_billed_cents": 0,
            "tenat_name": "must not be silently dropped",
        },
        _simple_terms(),
        {"cam_cents": 100},
    )
    assert unrecognized_tenancy == {
        "error": "unrecognized input fields",
        "unrecognized_inputs": ["tenancy.tenat_name"],
    }

    unrecognized_cost = cam_true_up(
        {"tenancy_id": "tenant-1", "estimated_billed_cents": 0},
        _simple_terms(),
        {"cam_cents": 100, "cam_centz": 999},
    )
    assert unrecognized_cost["error"].startswith("cam_true_up:")
    assert "actual_costs.cam_centz" in unrecognized_cost["error"]

    assert cam_true_up(None, _simple_terms(), {"cam_cents": 100})[  # type: ignore[arg-type]
        "error"
    ].startswith("cam_true_up:")
    missing_terms = cam_true_up(
        {"tenancy_id": "tenant-1", "estimated_billed_cents": 0},
        None,
        {"cam_cents": 100},
    )
    assert missing_terms["error"].startswith("cam_true_up:")
    assert "recovery_terms" in missing_terms["error"]

    lossy_cents = cam_true_up(
        {"tenancy_id": "tenant-1", "estimated_billed_cents": 0},
        _simple_terms(),
        {"cam_cents": 100.25},
    )
    assert lossy_cents["error"].startswith("cam_true_up:")
    assert "actual_costs.cam" in lossy_cents["error"] or "integer" in lossy_cents[
        "error"
    ]


def test_owner_report_composes_real_books_variance_and_initiatives_with_sources(
    tmp_path,
) -> None:
    db_path = tmp_path / "owner-report.sqlite"
    books = BookStore(db_path)
    books.setup_tenancy(
        tenancy_id="tenant-owner-1",
        deal_id="deal-owner-1",
        unit="100",
        tenant_name="Owner Report Tenant",
    )
    books.add_charge(
        charge_id="charge-owner-1",
        tenancy_id="tenant-owner-1",
        period="2026-01",
        kind="rent",
        amount_cents=100_000,
        source="schedule",
        source_detail={"test": "signed rent schedule"},
    )

    initiative_store = InitiativeStore(db_path)
    initiative_store.upsert_initiative(
        "deal-owner-1",
        "Roof coating",
        10_000,
        12_000,
        owner="Asset Manager",
        start="2026-01-01",
        months=1,
        status="in_progress",
        baseline={
            "forecast_cost_cents_by_period": {"2026-01": 10_000},
            "forecast_noi_impact_cents_by_period": {"2026-01": 1_000},
        },
    )

    budget = {
        "lines": [
            {"line": "rent", "amount_cents": 100_000, "driver": "rate", "noi_sign": 1},
            {"line": "opex", "amount_cents": 30_000, "driver": "opex", "noi_sign": -1},
        ],
        "budegt_note": "deliberate typo must surface",
    }
    actuals = {
        "lines": [
            {"line": "rent", "amount_cents": 105_000, "driver": "rate", "noi_sign": 1},
            {"line": "opex", "amount_cents": 32_000, "driver": "opex", "noi_sign": -1},
        ]
    }
    report = owner_report(
        "2026-01",
        "deal-owner-1",
        budget,
        actuals,
        [
            {
                "initiative": "Roof coating",
                "actual_cost_cents": 9_000,
                "actual_noi_impact_cents": 1_200,
                "elapsed_months": 1,
                "source": "paid invoice and PM certification",
            }
        ],
        db_path,
    )

    assert report["period"] == "2026-01"
    assert report["deal_id"] == "deal-owner-1"
    assert report["collections"]["status"] == "AVAILABLE"
    assert report["variance"]["status"] == "AVAILABLE"
    assert report["initiatives"]["status"] == "on_track"

    collections = report["collections"]["figures"]
    assert {key: figure["value"] for key, figure in collections.items()} == {
        "scheduled_cents": 100_000,
        "billed_cents": 100_000,
        "collected_cents": 0,
        "outstanding_cents": 100_000,
    }
    variance = report["variance"]["figures"]
    assert variance["budget_noi_cents"]["value"] == 70_000
    assert variance["actual_noi_cents"]["value"] == 73_000
    assert variance["total_delta_cents"]["value"] == 3_000
    item = report["initiatives"]["items"][0]
    assert item["initiative"] == "Roof coating"
    assert item["status"] == "on_track"
    assert item["cost_delta_cents"]["value"] == -1_000
    assert item["noi_delta_cents"]["value"] == 200

    # A real misspelled budget field must be promoted, not merely buried inside
    # the variance payload or accepted only when the caller self-reports it.
    assert report["unrecognized_inputs"] == ["budget.budegt_note"]

    for section_name in ("collections", "variance", "initiatives"):
        section = report[section_name]
        assert section["status"] in {
            "AVAILABLE",
            "NOT_AVAILABLE",
            "on_track",
            "behind",
            "not_assessable",
        }
        assert section["source"] == report["source_registry"][section_name]
        assert "read-only" in section["source"]
        _assert_all_numbers_are_source_tagged(section, section_name)


def test_owner_report_null_and_structured_type_errors_are_contained(tmp_path) -> None:
    db_path = tmp_path / "owner-errors.sqlite"
    assert owner_report(None, "deal", db_path=db_path)["error"].startswith(  # type: ignore[arg-type]
        "owner_report:"
    )
    no_deal = owner_report("2026-01", None, db_path=db_path)  # type: ignore[arg-type]
    assert no_deal["error"].startswith("owner_report:")
    assert "deal_id" in no_deal["error"]

    malformed_actuals = owner_report(
        "2026-01",
        "deal",
        {"lines": [{"line": "rent", "amount_cents": 1}]},
        [],  # type: ignore[arg-type]
        db_path=db_path,
    )
    assert malformed_actuals["variance"]["status"] == "NOT_AVAILABLE"
    assert "actuals must be a mapping" in malformed_actuals["variance"]["reason"]
    assert malformed_actuals["variance"]["source"] == malformed_actuals[
        "source_registry"
    ]["variance"]
