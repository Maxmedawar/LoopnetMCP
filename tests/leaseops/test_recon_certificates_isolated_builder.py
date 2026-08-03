"""Focused tests for lease/books reconciliation and certificate operations."""

from __future__ import annotations

import sqlite3

import pytest

from cre_mcp.leaseops.certificates import CertificateStore
from cre_mcp.leaseops.recon import lease_vs_books
from cre_mcp.leases.models import CitedClaim, LeaseAbstract, LeaseDates, RentPeriod, Security


def _stated(value, quote, locator):
    return CitedClaim.stated(
        value,
        quote=quote,
        locator=locator,
        confidence=0.99,
    )


def test_lease_vs_books_catches_rent_mismatch_with_both_sides_cited():
    abstract = LeaseAbstract(
        dates=LeaseDates(
            commencement=_stated(
                "2026-01-01", "Term commences January 1, 2026.", "Lease §2"
            )
        ),
        rent_schedule=[
            RentPeriod(
                start=_stated("2026-01-01", "January 1, 2026", "Lease §4 table"),
                end=_stated("2026-12-31", "December 31, 2026", "Lease §4 table"),
                monthly=_stated(1_000, "$1,000.00 per month", "Lease §4 table"),
            )
        ],
        security=Security(
            deposit=_stated(5_000, "$5,000 security deposit", "Lease §6")
        ),
        source_path="signed-lease.pdf",
    )
    books = {
        "tenancy_id": "tenant-a",
        "commencement": "2026-01-01",
        "commencement_citation": {"source": "property system tenancy export"},
        "held_deposit_cents": 500_000,
        "deposit_citation": {"source": "deposit ledger", "entry": "DEP-1"},
        "charges": [
            {
                "charge_id": "JUL-RENT",
                "tenancy_id": "tenant-a",
                "period": "2026-07",
                "kind": "rent",
                "amount_cents": 90_000,
                "source": "manual",
                "source_detail": {"journal": "AR-77", "author": "Controller"},
            }
        ],
    }

    result = lease_vs_books("tenant-a", "2026-07", abstract, books)

    assert result["fields"]["commencement"]["status"] == "match"
    assert result["fields"]["deposit"]["status"] == "match"
    rent = result["fields"]["rent"]
    assert rent["status"] == "mismatch"
    period = rent["periods"][0]
    assert period["lease"]["amount_cents"] == 100_000
    assert period["books"]["amount_cents"] == 90_000
    assert period["delta_cents"] == -10_000
    assert period["lease"]["citation"]["source_path"] == "signed-lease.pdf"
    assert "$1,000.00 per month" in period["lease"]["citation"]["lease_quotes"]
    assert period["books"]["citations"] == [
        {
            "charge_id": "JUL-RENT",
            "source": "manual",
            "source_detail": {"journal": "AR-77", "author": "Controller"},
        }
    ]


def test_reconciliation_rejects_unrecognized_financial_input():
    abstract = {
        "commencement": "2026-01-01",
        "rent_schedule": [
            {
                "period": "2026-07",
                "monthly_cents": 100_000,
                "monthly_centz": 1,
            }
        ],
    }

    with pytest.raises(ValueError, match="unrecognized inputs.*monthly_centz"):
        lease_vs_books(None, "2026-07", abstract, {"charges": []})


@pytest.mark.parametrize(
    ("collection", "row"),
    [
        (
            "charges",
            {
                "tenancy_id": "tenant-b",
                "period": "2026-07",
                "kind": "rent",
                "amount_cents": 100_000,
            },
        ),
        (
            "holds",
            {
                "tenancy_id": "tenant-b",
                "kind": "deposit",
                "amount_cents": 500_000,
                "status": "held",
            },
        ),
    ],
)
def test_reconciliation_rejects_cross_tenancy_books_rows(collection, row):
    abstract = {
        "rent_schedule": [{"period": "2026-07", "monthly_cents": 100_000}],
    }
    books = {"tenancy_id": "tenant-a", "charges": [], "holds": [], collection: [row]}

    with pytest.raises(ValueError, match=rf"{collection}\[0\]\.tenancy_id does not match"):
        lease_vs_books("tenant-a", "2026-07", abstract, books)


def test_certificate_expiry_radar_window_is_inclusive_and_keeps_expired_separate(tmp_path):
    store = CertificateStore(tmp_path / "certificates.sqlite")
    for party, expiry in (
        ("Expired", "2026-07-13"),
        ("Today", "2026-07-14"),
        ("Boundary", "2026-08-13"),
        ("Outside", "2026-08-14"),
        ("Undated", None),
    ):
        store.record_certificate(
            "tenant-a", "coi", party, 100_000, expiry, "active", None
        )

    result = store.expire_radar(
        30, as_of="2026-07-14", tenancy_or_deal="tenant-a"
    )

    assert result["window_end"] == "2026-08-13"
    assert [(row["party"], row["days_to_expiry"]) for row in result["expiring"]] == [
        ("Today", 0),
        ("Boundary", 30),
    ]
    assert [(row["party"], row["days_to_expiry"]) for row in result["expired"]] == [
        ("Expired", -1)
    ]
    assert [row["party"] for row in result["undated"]] == ["Undated"]
    assert result["window_convention"].endswith("inclusive")


def test_certificate_radar_honors_expired_status_without_an_expiry_date(tmp_path):
    store = CertificateStore(tmp_path / "status-expired.sqlite")
    store.record_certificate(
        "tenant-a", "guaranty", "Guarantor LLC", None, None, "expired", None
    )

    result = store.expire_radar(
        30, as_of="2026-07-14", tenancy_or_deal="tenant-a"
    )

    assert result["undated"] == []
    assert result["expired"][0]["days_to_expiry"] is None
    assert "entered status" in result["expired"][0]["expiry_basis"]


def test_certificate_gap_uses_entered_limit_and_table_is_owned(tmp_path):
    db_path = tmp_path / "certificate-gaps.sqlite"
    store = CertificateStore(db_path)
    recorded = store.record_certificate(
        {
            "tenancy_or_deal": "tenant-a",
            "kind": "coi",
            "party": "Tenant LLC",
            "amount_cents": 100_000_000,
            "expires": "2027-01-01",
            "status": "received",
            "doc_ref": None,
        }
    )
    report = store.gaps_report(
        "tenant-a",
        [
            {
                "kind": "coi",
                "party": "Tenant LLC",
                "required_amount_cents": 200_000_000,
                "clause_quote": "Tenant shall maintain $2,000,000 aggregate.",
                "locator": "Lease §11",
            },
            {
                "kind": "deposit",
                "required_amount_cents": 500_000,
                "clause_quote": "Security deposit: $5,000.",
                "locator": "Lease §6",
            },
        ],
        as_of="2026-07-14",
    )

    assert recorded["amount_cents"] == 100_000_000
    assert [gap["status"] for gap in report["gaps"]] == [
        "insufficient_amount",
        "missing",
    ]
    assert report["gaps"][0]["requirement"]["citation"]["quote"].startswith(
        "Tenant shall maintain"
    )
    assert "never summed" in report["eligibility_convention"]

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        columns = [
            row[1]
            for row in connection.execute("PRAGMA table_info(lo_certificates)")
        ]
    assert tables == {"lo_certificates"}
    assert columns == [
        "tenancy_or_deal",
        "kind",
        "party",
        "amount_cents",
        "expires",
        "status",
        "doc_ref",
    ]


def test_certificate_mapping_rejects_unknown_key_and_accepts_nullable_optionals(tmp_path):
    store = CertificateStore(tmp_path / "strict.sqlite")
    with pytest.raises(ValueError, match="unrecognized inputs.*expiration"):
        store.record_certificate(
            {
                "tenancy_or_deal": "tenant-a",
                "kind": "guaranty",
                "party": "Guarantor LLC",
                "amount_cents": None,
                "expires": None,
                "status": "active",
                "doc_ref": None,
                "expiration": "2027-01-01",
            }
        )

    record = store.record_certificate(
        "tenant-a", "guaranty", "Guarantor LLC", None, None, "active", None
    )
    assert record["amount_cents"] is None
    assert record["expires"] is None
    assert record["doc_ref"] is None

    with pytest.raises(ValueError, match="status must be one of"):
        store.record_certificate(
            "tenant-a", "coi", "Tenant LLC", None, None, "expried", None
        )
