"""Adversarial tests for calendars, permit reconciliation, and Phase II scoping."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from cre_mcp.compliance.calendar import compliance_calendar, upcoming
from cre_mcp.compliance.phase2 import phase2_scope
from cre_mcp.compliance.unpermitted import unpermitted_work_screen


AS_OF = date(2026, 7, 14)


def _asset() -> dict[str, Any]:
    return {
        "state": "CA",
        "city": "Los Angeles",
        "type": "retail",
        "systems": ["elevator", "backflow", "fire alarm", "sprinkler"],
        "licenses": [
            {
                "name": "Los Angeles business license",
                "due_date": "2026-08-01",
                "source_label": "Los Angeles business-license record supplied by caller",
            }
        ],
    }


def _obligation(result: dict[str, Any], needle: str) -> dict[str, Any]:
    normalized_needle = needle.casefold().replace("-", " ")
    matches = [
        row
        for row in result["obligations"]
        if normalized_needle
        in str(row.get("obligation", "")).casefold().replace("-", " ")
    ]
    assert matches, f"missing {needle!r} in {result['obligations']!r}"
    return matches[0]


def test_calendar_assembles_tax_license_and_each_system_with_sources(
    tmp_path: Path,
) -> None:
    result = compliance_calendar(
        _asset(),
        db_path=tmp_path / "calendar.db",
        as_of=AS_OF,
    )

    assert "error" not in result
    obligations = result["obligations"]
    assert obligations
    assert all(str(row.get("source_label", "")).strip() for row in obligations)
    assert all("due_date" in row for row in obligations)
    assert all(row.get("asset_id") == result["asset_id"] for row in obligations)

    property_tax = _obligation(result, "property tax")
    assert "california" in property_tax["source_label"].casefold()
    assert "annual" in _obligation(result, "elevator")["cadence"].casefold()
    assert "annual" in _obligation(result, "backflow")["cadence"].casefold()
    assert "annual" in _obligation(result, "fire alarm")["cadence"].casefold()

    sprinkler = _obligation(result, "sprinkler")
    assert "5" in sprinkler["cadence"]
    assert "year" in sprinkler["cadence"].casefold()
    license_row = _obligation(result, "business license")
    assert license_row["due_date"] == "2026-08-01"
    assert license_row["source_label"].startswith("Los Angeles")


def test_calendar_owns_only_its_table_and_preserves_existing_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "shared.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel(value) VALUES ('preserve-me')")

    compliance_calendar(_asset(), db_path=db_path, as_of=AS_OF)

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "comp_calendar" in tables
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == (
            "preserve-me"
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(comp_calendar)")
        }
        assert {"asset_id", "obligation", "due_date", "source_label"} <= columns


def test_upcoming_uses_persisted_rows_and_exact_inclusive_window(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "calendar.db"
    assembled = compliance_calendar(_asset(), db_path=db_path, as_of=AS_OF)

    within_30 = upcoming(
        30,
        db_path=db_path,
        as_of=AS_OF,
        asset=assembled["asset_id"],
    )
    within_10 = upcoming(
        10,
        db_path=db_path,
        as_of=AS_OF,
        asset=assembled["asset_id"],
    )

    assert "error" not in within_30
    license_row = _obligation(within_30, "business license")
    assert license_row["due_date"] == "2026-08-01"
    assert all(row["due_date"] <= "2026-08-13" for row in within_30["obligations"])
    assert not any(
        "business license" in row["obligation"].casefold()
        for row in within_10["obligations"]
    )


def test_upcoming_rejects_negative_window_at_error_boundary(tmp_path: Path) -> None:
    result = upcoming(-1, db_path=tmp_path / "calendar.db", as_of=AS_OF)

    assert set(result) == {"error"}
    assert "non-negative" in result["error"].casefold()


def test_manual_permit_plausibly_matches_description_type_and_year() -> None:
    result = unpermitted_work_screen(
        [{"desc": "Complete roof replacement", "est_year": 2023}],
        [
            {
                "type": "roofing permit",
                "date": "2023-08-09",
                "desc": "Tear off existing roof and reroof the building",
            }
        ],
    )

    assert "error" not in result
    assert result["flags"] == []


def test_permits_near_payload_matches_one_improvement_and_flags_the_other() -> None:
    result = unpermitted_work_screen(
        [
            {"desc": "New 400 amp electrical service and panel", "est_year": 2025},
            {"desc": "Rear storage-room addition", "est_year": 2020},
        ],
        {
            "status": "OK",
            "permits": [
                {
                    "permit_type": "PERMIT - EXPRESS PERMIT PROGRAM",
                    "work_type": "Electrical Work",
                    "issue_date": "2025-07-15T00:00:00.000",
                    "work_description": "NEW 400 AMP ELECTRICAL SERVICE AND PANEL",
                }
            ],
        },
    )

    assert "error" not in result
    assert len(result["flags"]) == 1
    flag = result["flags"][0]
    assert "storage" in str(flag).casefold()
    assert "code professional verification required" in str(flag).casefold()


def test_similar_but_stale_permit_does_not_clear_recent_work() -> None:
    result = unpermitted_work_screen(
        [{"desc": "Install two rooftop HVAC units", "est_year": 2025}],
        [
            {
                "type": "mechanical",
                "date": "2010-03-04",
                "desc": "Install rooftop HVAC units",
            }
        ],
    )

    assert len(result["flags"]) == 1
    assert "verification required" in str(result["flags"][0]).casefold()


def test_malformed_permits_near_payload_returns_error_boundary() -> None:
    result = unpermitted_work_screen(
        [{"desc": "Tenant buildout", "est_year": None}],
        {"status": "OK", "permits": None},
    )

    assert set(result) == {"error"}
    assert "permits" in result["error"].casefold()


def test_phase2_scope_maps_each_rec_to_the_required_field_method() -> None:
    result = phase2_scope(
        [
            {"rec_type": "UST", "location": "north parking lot", "medium": "soil"},
            {
                "rec_type": "dry cleaner",
                "location": "former Suite 12",
                "medium": "vapor",
            },
            {
                "rec_type": "groundwater release",
                "location": "southern property boundary",
                "medium": "groundwater",
            },
        ]
    )

    assert "error" not in result
    assert len(result["scope_items"]) == 3
    scopes = {
        str(item["rec_type"]).casefold(): str(item.get("scope_elements", "")).casefold()
        for item in result["scope_items"]
    }
    assert "soil boring" in scopes["ust"]
    assert ("near" in scopes["ust"] or "adjacent" in scopes["ust"])
    assert "ust" in scopes["ust"]
    assert "vapor pin" in scopes["dry cleaner"]
    assert "groundwater" in scopes["groundwater release"]
    assert "well" in scopes["groundwater release"]
    assert "downgradient" in scopes["groundwater release"]


def test_phase2_costs_are_ranges_labeled_as_conventions_not_quotes() -> None:
    result = phase2_scope(
        [{"rec_type": "UST", "location": "loading area", "medium": "soil"}]
    )

    item = result["scope_items"][0]
    cost_range = item["cost_range_usd"]
    assert cost_range["low"] > 0
    assert cost_range["high"] > cost_range["low"]
    assert "convention" in str(result["cost_convention"]).casefold()
    assert "quote" not in str(result["cost_convention"]).casefold() or (
        "not a quote" in str(result["cost_convention"]).casefold()
    )
    assert (
        "licensed environmental consultant must scope/perform"
        in result["disclaimer"].casefold()
    )


def test_phase2_nullable_findings_are_an_honest_empty_scope() -> None:
    result = phase2_scope(None)

    assert "error" not in result
    assert result["scope_items"] == []
    assert result["aggregate_cost_range_usd"] is None
    assert "licensed environmental consultant" in result["disclaimer"].casefold()
