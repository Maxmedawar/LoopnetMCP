"""Exact arithmetic and durable renewal-operations tests."""

import sqlite3

import pytest

from cre_mcp.compliance.insurance_ops import InsuranceOpsStore
from cre_mcp.compliance.tax_appeal import build_appeal_package


def test_appeal_income_cap_math_and_comp_psf_are_exact():
    result = build_appeal_package(
        {
            "assessed_value": 1_500_000,
            "noi_actual": 90_000,
            "cap_rate": 0.075,
            "sf": 10_000,
            "comps": [{"psf": 110}, {"psf": 130}],
            "condition_notes": ["Roof has documented deferred maintenance."],
        },
        {
            "deadline": "2026-09-15",
            "board": "County Assessment Appeals Board",
            "deadline_source": "assessment notice supplied by owner",
        },
    )

    assert result["income_approach"] == {
        "type": "income_approach",
        "formula": "noi_actual / cap_rate",
        "noi_actual": 90_000.0,
        "cap_rate": 0.075,
        "indicated_value": 1_200_000.0,
        "assessed_value": 1_500_000.0,
        "assessed_minus_indicated": 300_000.0,
        "supports_over_assessment": True,
    }
    assert result["comparable_psf_evidence"]["assessed_psf"] == 150.0
    assert result["comparable_psf_evidence"]["average_comp_psf"] == 120.0
    assert result["comparable_psf_evidence"]["assessed_minus_average_comp_psf"] == 30.0
    assert result["comparable_psf_evidence"]["comp_indicated_value"] == 1_200_000.0
    assert result["condition_evidence"]["notes"] == [
        "Roof has documented deferred maintenance."
    ]
    assert result["filing_status"] == "NOT FILED"
    assert result["consultant_counsel_required"] is True
    assert "not a tax appeal or filing" in result["disclaimer"]
    assert result["deadline_tracking"]["deadline"] == "2026-09-15"
    assert result["deadline_tracking"]["source"] == "assessment notice supplied by owner"


def test_appeal_does_not_invent_cap_rate_or_deadline():
    assessment = {
        "assessed_value": 1_000_000,
        "noi_actual": 70_000,
        "sf": 10_000,
        "comps": [],
        "condition_notes": None,
    }
    with pytest.raises(ValueError, match="no market cap rate is inferred"):
        build_appeal_package(assessment, {})

    assessment["cap_rate"] = 7
    result = build_appeal_package(assessment, {})
    assert result["assessment_inputs"]["cap_rate"] == 0.07
    assert result["assessment_inputs"]["cap_rate_input_interpretation"] == "percent"
    assert result["deadline_tracking"]["deadline"] is None
    assert result["deadline_tracking"]["status"] == "UNKNOWN"
    assert result["comparable_psf_evidence"]["average_comp_psf"] is None


def test_policy_and_claim_persist_only_owned_table(tmp_path):
    db_path = tmp_path / "insurance.sqlite"
    store = InsuranceOpsStore(db_path)
    stored = store.record_policy(
        "101 Main",
        "Carrier A",
        "property",
        125_000,
        "2026-10-01",
    )
    updated = store.record_claim(
        "101 Main",
        "Carrier A",
        "property",
        {
            "loss_date": "2026-01-15",
            "incurred_cents": 50_000,
            "status": "open",
        },
    )

    assert stored["claims"] == []
    assert updated["claims"] == [
        {
            "incurred_cents": 50_000,
            "loss_date": "2026-01-15",
            "status": "open",
        }
    ]
    with sqlite3.connect(db_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        columns = [
            row[1] for row in connection.execute("PRAGMA table_info(ins_policies)")
        ]
    assert table_names == {"ins_policies"}
    assert columns == [
        "asset",
        "carrier",
        "line",
        "premium_cents",
        "expiry",
        "claims_json",
    ]


def test_renewal_radar_window_is_inclusive_and_excludes_expired(tmp_path):
    store = InsuranceOpsStore(tmp_path / "radar.sqlite")
    store.record_policy("A", "Carrier A", "property", 100, "2026-07-13")
    store.record_policy("B", "Carrier B", "liability", 200, "2026-07-14")
    store.record_policy("C", "Carrier C", "property", 300, "2026-11-11")
    store.record_policy("D", "Carrier D", "property", 400, "2026-11-12")

    result = store.renewal_radar(as_of="2026-07-14")

    assert result["window_end"] == "2026-11-11"
    assert [(item["asset"], item["days_to_expiry"]) for item in result["renewals"]] == [
        ("B", 0),
        ("C", 120),
    ]
    assert result["window_convention"].endswith("inclusive")


def test_loss_run_summary_and_nonrenewal_signal_use_explicit_convention(tmp_path):
    store = InsuranceOpsStore(tmp_path / "claims.sqlite")
    store.record_policy("A", "Carrier A", "property", 100_000, "2026-08-01")
    store.record_claim(
        "A",
        "Carrier A",
        "property",
        {"loss_date": "2024-01-01", "amount_cents": 20_000, "status": "closed"},
    )
    store.record_claim(
        "A",
        "Carrier A",
        "property",
        {"loss_date": "2026-06-01", "incurred_cents": 30_000, "status": "open"},
    )
    store.record_claim(
        "A",
        "Carrier A",
        "property",
        {"loss_date": "2020-01-01", "paid_cents": 10_000, "status": "settled"},
    )

    policy = store.renewal_radar(days=60, as_of="2026-07-14")["renewals"][0]
    summary = policy["loss_run_summary"]
    assert summary["stored_claim_count"] == 3
    assert summary["total_incurred_or_amount_cents"] == 60_000
    assert summary["open_claim_count"] == 1
    assert summary["dated_claims_in_trailing_1095_days"] == 2
    assert summary["frequency_signal"] == "ELEVATED"
    assert "at least 2" in summary["convention"]
    assert "does not predict carrier nonrenewal" in policy["nonrenewal_risk_note"]


def test_carrier_concentration_uses_all_unexpired_premium_not_only_radar(tmp_path):
    store = InsuranceOpsStore(tmp_path / "concentration.sqlite")
    store.record_policy("A", "Carrier A", "property", 600, "2026-08-01")
    store.record_policy("B", "Carrier B", "property", 250, "2027-08-01")
    store.record_policy("C", "Carrier B", "liability", 150, "2027-09-01")
    store.record_policy("Expired", "Carrier C", "property", 10_000, "2026-01-01")

    result = store.renewal_radar(days=30, as_of="2026-07-14")
    concentration = result["carrier_concentration"]

    assert result["renewal_count"] == 1
    assert concentration["active_premium_cents"] == 1_000
    assert concentration["by_carrier"] == [
        {
            "carrier": "Carrier A",
            "premium_cents": 600,
            "premium_share": 0.6,
            "flagged": True,
        },
        {
            "carrier": "Carrier B",
            "premium_cents": 400,
            "premium_share": 0.4,
            "flagged": False,
        },
    ]
    assert concentration["flagged_carriers"] == ["Carrier A"]
    assert "entered premium cents" in concentration["note"]


def test_updating_policy_without_claims_preserves_loss_history(tmp_path):
    store = InsuranceOpsStore(tmp_path / "preserve.sqlite")
    store.record_policy("A", "Carrier", "property", 100, "2026-08-01")
    store.record_claim(
        "A", "Carrier", "property", {"loss_date": "2026-01-01", "amount_cents": 5}
    )
    updated = store.record_policy("A", "Carrier", "property", 150, "2026-09-01")

    assert updated["premium_cents"] == 150
    assert updated["expiry"] == "2026-09-01"
    assert len(updated["claims"]) == 1

