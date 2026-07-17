"""Penny-exact, source-traced property billing tests."""

import json

from cre_mcp.books.billing import (
    lease_to_billing_audit,
    post_manual_charge,
    post_scheduled_charges,
)
from cre_mcp.books.store import BookStore


def _lease(tmp_path, monthly="1,000.01", annual="12,000.12"):
    path = tmp_path / "alpha-lease.txt"
    path.write_text(
        "BASE RENT\n"
        f"January 1, 2025 - December 31, 2025 {annual} {monthly} 12.00\n",
        encoding="utf-8",
    )
    return path


def _tenancy(store, lease_path):
    return store.setup_tenancy(
        tenancy_id="tenant-alpha",
        deal_id="deal-1",
        unit="Suite 100",
        tenant_name="Alpha Retail LLC",
        lease_ref=lease_path,
    )


def test_schedule_billing_is_penny_exact_cited_and_idempotent(tmp_path):
    store = BookStore(tmp_path / "books.db")
    tenancy = _tenancy(store, _lease(tmp_path))

    first = post_scheduled_charges(tenancy, "2025-01", store=store)
    second = post_scheduled_charges(tenancy, "2025-01", store=store)

    assert first["posted"][0]["amount_cents"] == 100_001
    detail = json.loads(first["posted"][0]["source_detail"])
    assert detail["citation"]["source_path"].endswith("alpha-lease.txt")
    assert "1,000.01" in detail["citation"]["lease_quotes"]
    assert second["posted"] == []
    assert second["already_posted"][0]["amount_cents"] == 100_001
    assert len(store.list_charges(period="2025-01")) == 1


def test_manual_charge_preserves_author_and_integer_cents(tmp_path):
    store = BookStore(tmp_path / "books.db")
    _tenancy(store, _lease(tmp_path))

    result = post_manual_charge(
        "tenant-alpha",
        "2025-01",
        "cam",
        25_067,
        author="Max Medawar",
        source_detail="January CAM estimate",
        store=store,
    )

    assert result["charge"]["amount_cents"] == 25_067
    detail = json.loads(result["charge"]["source_detail"])
    assert detail == {
        "author": "Max Medawar",
        "detail": "January CAM estimate",
    }


def test_lease_audit_catches_overbilling_with_lease_side_citation(tmp_path):
    store = BookStore(tmp_path / "books.db")
    tenancy = _tenancy(store, _lease(tmp_path, monthly="1,000.00", annual="12,000.00"))
    post_scheduled_charges(tenancy, "2025-01", store=store)
    store.add_charge(
        tenancy_id="tenant-alpha",
        period="2025-01",
        kind="rent",
        amount_cents=10_000,
        source="manual",
        source_detail={"author": "Bookkeeper", "reason": "unsupported rent add-on"},
    )

    audit = lease_to_billing_audit(tenancy, "2025-01", store=store)

    discrepancy = audit["discrepancies"][0]
    assert discrepancy["status"] == "over_billed"
    assert discrepancy["lease_expected_cents"] == 100_000
    assert discrepancy["posted_rent_cents"] == 110_000
    assert discrepancy["delta_cents"] == 10_000
    assert "1,000.00" in discrepancy["lease_citation"]["lease_quotes"]
