"""Additional conservative matching and bank-import integrity coverage."""

from __future__ import annotations

from cre_mcp.books.bankimport import import_bank_csv, match_receipts
from cre_mcp.books.store import BookStore


def _tenancy(store, tenancy_id="alpha", name="Alpha Retail LLC"):
    store.setup_tenancy(
        tenancy_id=tenancy_id,
        deal_id="deal-match",
        unit=tenancy_id,
        tenant_name=name,
    )


def _charge(store, charge_id, amount_cents):
    store.add_charge(
        charge_id=charge_id,
        tenancy_id="alpha",
        period="2026-07",
        kind="rent",
        amount_cents=amount_cents,
        source="schedule",
        source_detail={"lease_ref": "alpha.txt", "citation": "Base Rent"},
    )


def test_duplicate_bank_rows_are_disclosed_and_counted_once(tmp_path):
    store = BookStore(tmp_path / "books.db")
    export = tmp_path / "bank.csv"
    export.write_text(
        "Date,Amount,Description\n"
        "07/03/2026,3333.33,ACH ALPHA RETAIL RENT\n"
        "07/03/2026,3333.33,ACH ALPHA RETAIL RENT\n"
        "07/03/2026,3333.33,ACH ALPHA RETAIL RENT\n",
        encoding="utf-8",
    )

    result = import_bank_csv(
        export,
        {
            "date_col": "Date",
            "amount_col": "Amount",
            "desc_col": "Description",
            "debit_credit": "credits_positive",
        },
        store=store,
    )

    assert result["source_row_count"] == 3
    assert result["candidate_receipt_count"] == 1
    assert result["inserted_receipt_count"] == 1
    assert [item["line_number"] for item in result["duplicate_rows"]] == [3, 4]
    assert all(item["duplicates_line_number"] == 2 for item in result["duplicate_rows"])
    receipts = store.list_receipts(period="2026-07")
    assert len(receipts) == 1
    assert sum(item["amount_cents"] for item in receipts) == 333_333


def test_reimport_is_evidenced_and_does_not_duplicate_cash(tmp_path):
    store = BookStore(tmp_path / "books.db")
    export = tmp_path / "bank.csv"
    export.write_text(
        "Date,Amount,Description\n07/03/2026,1000.00,ACH ALPHA RENT\n",
        encoding="utf-8",
    )
    mapping = {
        "date_col": "Date",
        "amount_col": "Amount",
        "desc_col": "Description",
        "debit_credit": "credits_positive",
    }

    first = import_bank_csv(export, mapping, store=store)
    second = import_bank_csv(export, mapping, store=store)

    assert first["already_imported"] is False
    assert first["inserted_receipt_count"] == 1
    assert second["already_imported"] is True
    assert second["inserted_receipt_count"] == 0
    assert len(store.list_receipts(period="2026-07")) == 1


def test_one_deposit_with_two_exact_charge_set_candidates_stays_unmatched(tmp_path):
    store = BookStore(tmp_path / "books.db")
    _tenancy(store)
    _charge(store, "half-a", 50_000)
    _charge(store, "half-b", 50_000)
    _charge(store, "whole", 100_000)
    store.add_receipt(
        receipt_id="ambiguous-deposit",
        date="2026-07-05",
        amount_cents=100_000,
        payer_hint="ACH ALPHA RETAIL LLC",
        method="bank_csv",
        import_id=None,
    )

    result = match_receipts("2026-07", store=store)

    receipt = result["receipts"][0]
    assert receipt["status"] == "unmatched"
    assert receipt["tenancy_id"] is None
    assert receipt["matched_charge_ids"] == []
    assert {tuple(item["charge_ids"]) for item in receipt["candidates"]} == {
        ("half-a", "half-b"),
        ("whole",),
    }
    assert receipt["decision"] == "not_matched_ambiguous_exact_candidates"


def test_likely_partial_receipt_is_listed_but_never_allocated(tmp_path):
    store = BookStore(tmp_path / "books.db")
    _tenancy(store)
    _charge(store, "full-rent", 100_000)
    store.add_receipt(
        receipt_id="partial-deposit",
        date="2026-07-05",
        amount_cents=40_000,
        payer_hint="ACH ALPHA RETAIL LLC",
        method="bank_csv",
        import_id=None,
    )

    result = match_receipts("2026-07", store=store)

    receipt = result["receipts"][0]
    assert receipt["status"] == "partial"
    assert receipt["matched_charge_ids"] == []
    assert receipt["candidates"][0]["charge_ids"] == ["full-rent"]
    assert receipt["candidates"][0]["expected_amount_cents"] == 100_000

