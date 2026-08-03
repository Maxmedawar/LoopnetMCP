"""Black-box tests for the plain property-books MCP boundary functions."""

from __future__ import annotations

import json

import pytest

from cre_mcp.books.store import BookStore
from cre_mcp.books.tools import (
    ar_aging,
    audit_lease_billing,
    import_bank_transactions,
    post_charges,
    reconcile_rent_to_cash,
    setup_tenancy,
)


def _setup(tmp_path, *, lease_ref=None):
    result = setup_tenancy(
        deal_id="deal-boundary",
        unit="Suite 300",
        tenant_name="Boundary Tenant LLC",
        lease_ref=lease_ref,
        tenancy_id="boundary-tenant",
        db_path=tmp_path / "books.db",
    )
    assert "error" not in result
    return result


@pytest.mark.parametrize(
    ("dollars", "expected_cents"),
    [
        (3333.33, 333_333),
        (0.1 + 0.2, 30),
        ("17.29", 1_729),
    ],
)
def test_post_charges_converts_dollar_inputs_to_exact_cents(
    tmp_path, dollars, expected_cents
):
    _setup(tmp_path)

    result = post_charges(
        "boundary-tenant",
        "2026-07",
        manual_charges=[
            {
                "period": "2026-07",
                "kind": "cam",
                "amount": dollars,
                "author": "Boundary Tester",
            }
        ],
        db_path=tmp_path / "books.db",
    )

    assert "error" not in result
    assert result["manual"][0]["charge"]["amount_cents"] == expected_cents


def test_post_charges_accepts_consistent_dollars_and_integer_cents(tmp_path):
    _setup(tmp_path)

    result = post_charges(
        "boundary-tenant",
        "2026-07",
        manual_charges=[
            {
                "period": "2026-07",
                "kind": "tax",
                "amount": "10.25",
                "amount_cents": 1_025,
                "author": "Boundary Tester",
            }
        ],
        db_path=tmp_path / "books.db",
    )

    assert "error" not in result
    assert result["manual"][0]["charge"]["amount_cents"] == 1_025


@pytest.mark.parametrize(
    "manual_charge",
    [
        {
            "period": "2026-07",
            "kind": "cam",
            "amount": "10.25",
            "amount_cents": 1_026,
            "author": "Boundary Tester",
        },
        {
            "period": "2026-07",
            "kind": "cam",
            "author": "Boundary Tester",
        },
    ],
    ids=["inconsistent", "neither"],
)
def test_post_charges_reports_invalid_amount_shapes(tmp_path, manual_charge):
    _setup(tmp_path)

    result = post_charges(
        "boundary-tenant",
        "2026-07",
        manual_charges=[manual_charge],
        db_path=tmp_path / "books.db",
    )

    assert isinstance(result.get("error"), str)
    assert "amount" in result["error"]
    assert "amount_cents" in result["error"]


def test_post_charges_negative_credit_is_rejected_without_losing_its_sign(tmp_path):
    _setup(tmp_path)

    result = post_charges(
        "boundary-tenant",
        "2026-07",
        manual_charges=[
            {
                "period": "2026-07",
                "kind": "other",
                "amount": "-12.34",
                "amount_cents": -1_234,
                "author": "Boundary Tester",
                "source_detail": "Tenant credit; credit ledger is not modeled yet",
            }
        ],
        db_path=tmp_path / "books.db",
    )

    assert isinstance(result.get("error"), str)
    assert "non-negative" in result["error"]
    assert BookStore(tmp_path / "books.db").list_charges() == []


def test_post_charges_missing_author_returns_traceability_error(tmp_path):
    _setup(tmp_path)

    result = post_charges(
        "boundary-tenant",
        "2026-07",
        manual_charges=[
            {
                "period": "2026-07",
                "kind": "cam",
                "amount": 3333.33,
            }
        ],
        db_path=tmp_path / "books.db",
    )

    assert isinstance(result.get("error"), str)
    assert "author" in result["error"]


@pytest.mark.parametrize(
    "invoke",
    [
        lambda db, missing: setup_tenancy(
            deal_id="", unit="1", tenant_name="Tenant", db_path=db
        ),
        lambda db, missing: post_charges(
            "missing-tenancy", "2026-07", db_path=db
        ),
        lambda db, missing: import_bank_transactions(
            missing,
            {
                "date_col": "Date",
                "amount_col": "Amount",
                "desc_col": "Description",
                "debit_credit": "credits_positive",
            },
            db_path=db,
        ),
        lambda db, missing: reconcile_rent_to_cash("July 2026", db_path=db),
        lambda db, missing: ar_aging("not-a-date", db_path=db),
        lambda db, missing: audit_lease_billing(
            "missing-tenancy", "2026-07", "2026-07", db_path=db
        ),
    ],
    ids=[
        "setup-tenancy",
        "post-charges",
        "bank-import",
        "rent-to-cash",
        "aging",
        "lease-audit",
    ],
)
def test_every_plain_tool_contains_failures_at_its_boundary(tmp_path, invoke):
    result = invoke(tmp_path / "books.db", tmp_path / "missing.csv")

    assert isinstance(result, dict)
    assert isinstance(result.get("error"), str)
    assert result["error"].strip()


def test_post_charges_tool_preserves_lease_schedule_citation(tmp_path):
    lease = tmp_path / "cited-lease.txt"
    lease.write_text(
        "BASE RENT\n"
        "January 1, 2026 - December 31, 2026 40,000.00 3,333.33 12.00\n",
        encoding="utf-8",
    )
    _setup(tmp_path, lease_ref=lease)

    result = post_charges(
        "boundary-tenant", "2026-07", db_path=tmp_path / "books.db"
    )

    assert "error" not in result
    charge = result["scheduled"]["posted"][0]
    detail = json.loads(charge["source_detail"])
    assert charge["amount_cents"] == 333_333
    assert detail["citation"]["source_path"] == str(lease)
    assert "3,333.33" in detail["citation"]["lease_quotes"]

