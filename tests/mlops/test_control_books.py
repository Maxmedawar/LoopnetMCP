from __future__ import annotations

import sqlite3

from cre_mcp.mlops.control_books import ControlBookStore


def test_position_status_is_penny_exact_and_security_is_not_reserve(tmp_path):
    db_path = tmp_path / "control.db"
    store = ControlBookStore(db_path)
    store.open_position(
        position_id="ml-216",
        property="101 Main St",
        owner_name="Owner LLC",
        master_rent_cents=500_000,
        term_months=60,
        security_cents=900_000,
        reserves_cents=600_000,
        started_at="2026-01-01",
    )
    for flow_type, cents in (
        ("master_rent_due", 500_000),
        ("master_rent_paid", 500_000),
        ("sublease_billed", 800_000),
        ("sublease_received", 450_000),
        ("expense", 100_000),
        ("reserve_draw", 150_000),
    ):
        store.record_flow(
            position_id="ml-216",
            period="2026-07",
            type=flow_type,
            cents=cents,
        )

    status = store.position_status("ml-216", "2026-07")

    assert next(iter(status)) == "rent_owed_vs_received_exposure"
    assert status["rent_owed_vs_received_exposure"]["signed_exposure_cents"] == 50_000
    assert status["negative_carry_burn_rate_cents"] == 150_000
    assert status["reserve_balance_cents"] == 450_000
    assert status["reserve_months_remaining"] == 3.0
    assert status["sublease_occupancy"] == 0.5625
    assert status["break_even_sublease_occupancy"] == 0.75


def test_position_fallback_and_unknown_denominators_remain_honest(tmp_path):
    store = ControlBookStore(tmp_path / "fallback.db")
    opened = store.open_position(
        property="Vacant Center",
        master_rent_cents=333_333,
        term_months=12,
    )

    status = store.position_status(opened["position_id"], "2026-08")

    assert opened["owner_name"] is None
    assert opened["security_cents"] is None
    assert opened["reserves_cents"] is None
    assert status["master_rent_owed_cents"] == 333_333
    assert status["negative_carry_burn_rate_cents"] == 333_333
    assert status["sublease_occupancy"] is None
    assert status["break_even_sublease_occupancy"] is None
    assert status["reserve_months_remaining"] is None
    assert status["gaps"]


def test_control_store_owns_only_the_two_ml_book_tables(tmp_path):
    db_path = tmp_path / "owned.db"
    store = ControlBookStore(db_path)
    store.open_position(
        position_id="owned",
        property="Owned Tables",
        master_rent_cents=1,
        term_months=1,
    )

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert tables == {"ml_positions", "ml_flows"}
