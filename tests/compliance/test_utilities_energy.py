"""Exact-arithmetic and honesty tests for utilities and energy-rule screens."""

import pytest

from cre_mcp.compliance.energy_rules import energy_compliance
from cre_mcp.compliance.utilities import retrofit_screen, utility_anomalies


def test_utility_spike_intensity_and_bill_decomposition_are_exact():
    result = utility_anomalies(
        [
            {
                "period": "2025-01",
                "meter": "electric-1",
                "kwh_or_unit": 100,
                "amount_cents": 10_000,
                "sf": 1_000,
            },
            {
                "period": "2025-02",
                "meter": "electric-1",
                "kwh_or_unit": 150,
                "amount_cents": 18_000,
                "sf": 1_000,
            },
        ]
    )

    assert result["threshold_conventions"]["usage_spike"]["threshold_pct"] == 25
    assert [row["usage_per_sf"] for row in result["meter_trends"][0]["observations"]] == [
        0.1,
        0.15,
    ]
    assert result["spikes"][0]["usage_change_pct"] == 50
    decomposition = result["rate_vs_usage_decomposition"][0]
    assert decomposition["amount_delta_cents"] == 8_000
    assert decomposition["usage_effect_cents"] == 5_000
    assert decomposition["rate_effect_cents"] == 3_000
    assert decomposition["tariff_effect_cents"] == 3_000
    assert decomposition["explained_change_cents"] == 8_000
    assert decomposition["reconciliation_difference_cents"] == 0
    assert decomposition["reconciles_exactly"] is True
    assert decomposition["primary_driver"] == "usage"


def test_spike_threshold_is_inclusive_and_exposed():
    result = utility_anomalies(
        [
            {"period": "1", "meter": "gas", "kwh_or_unit": 80, "amount_cents": 800},
            {"period": "2", "meter": "gas", "kwh_or_unit": 100, "amount_cents": 1_000},
        ],
        spike_threshold_pct=25,
    )

    assert len(result["spikes"]) == 1
    assert result["spikes"][0]["usage_change_pct"] == 25
    assert "greater than or equal" in result["threshold_conventions"]["usage_spike"]["trigger"]


def test_master_submeter_reconciliation_uses_explicit_roles():
    result = utility_anomalies(
        [
            {
                "period": "2025-01",
                "meter": "campus-feed",
                "meter_role": "master",
                "kwh_or_unit": 1_000,
                "amount_cents": 20_000,
            },
            {
                "period": "2025-01",
                "meter": "tenant-a",
                "meter_role": "submeter",
                "kwh_or_unit": 600,
                "amount_cents": 12_000,
            },
            {
                "period": "2025-01",
                "meter": "tenant-b",
                "meter_role": "submeter",
                "kwh_or_unit": 350,
                "amount_cents": 7_000,
            },
        ]
    )

    row = result["submeter_reconciliation"][0]
    assert row["master_usage"] == 1_000
    assert row["submeter_usage_total"] == 950
    assert row["unreconciled_usage"] == 50
    assert row["absolute_variance_pct_of_master"] == 5
    assert row["within_tolerance"] is True


def test_retrofit_payback_range_is_convention_labeled():
    result = retrofit_screen(
        {"annual_usage": 100_000, "annual_cost_cents": 2_000_000},
        [
            {
                "name": "LED lighting",
                "cost_cents": [400_000, 600_000],
                "savings_pct": [10, 20],
            }
        ],
    )

    measure = result["measures"][0]
    assert measure["annual_savings_range_cents"] == {"low": 200_000, "high": 400_000}
    assert measure["simple_payback_years"] == {"low": 1.0, "high": 3.0}
    assert measure["payback_range_label"].startswith("CONVENTION:")
    assert result["status"] == "CONVENTION_BASED_SCREEN"


def test_ll97_entry_has_cap_and_cited_penalty_formula_shape():
    result = energy_compliance("NYC", {"sf": 30_000, "type": "office"})

    assert result["status"] == "KNOWN_RULE_SCREEN"
    assert "Local Law 97" in result["law"]
    assert result["applicability"]["status"] == "APPLIES_SIZE_SCREEN"
    assert "occupancy" in result["emissions_caps"]["limit_formula"]
    assert result["penalty_shape"]["excess_emissions_rate_dollars_per_metric_ton_co2e"] == 268
    assert "$268" in result["penalty_shape"]["formula"]
    assert result["source"]["citation"].startswith("N.Y.C. Admin. Code")
    assert result["source"]["url"].startswith("https://www.nyc.gov/")
    assert result["last_verified"]


@pytest.mark.parametrize(
    ("jurisdiction", "law_fragment"),
    [
        ("Boston, MA", "BERDO"),
        ("Washington, DC", "Building Energy Performance Standards"),
        ("California", "Assembly Bill 802"),
        ("Austin, TX", "Audit and Disclosure"),
        ("Denver, CO", "Energize Denver"),
    ],
)
def test_other_registry_entries_are_cited(jurisdiction, law_fragment):
    result = energy_compliance(jurisdiction, {"sf": 60_000, "type": "office"})

    assert law_fragment in result["law"]
    assert result["sources"][0]["citation"]
    assert result["sources"][0]["url"].startswith("https://")
    assert result["last_verified"]
    assert "re-verify" in result["verification_note"]


def test_unlisted_jurisdiction_is_unknown_without_inference():
    result = energy_compliance("Fresno, California", {"sf": 90_000, "type": "warehouse"})

    assert result["status"] == "UNKNOWN"
    assert result["law"] == "UNKNOWN"
    assert result["requirements"] == "UNKNOWN"
    assert result["applicability"]["status"] == "UNKNOWN"
    assert result["sources"] == []
    assert "no rule is inferred" in result["honesty"]
