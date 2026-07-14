"""Bank-import deduplication and no-guess matching tests."""

from cre_mcp.books.bankimport import import_bank_csv, match_receipts
from cre_mcp.books.store import BookStore


def _scheduled_charge(store, tenancy_id, charge_id):
    store.add_charge(
        charge_id=charge_id,
        tenancy_id=tenancy_id,
        period="2025-01",
        kind="rent",
        amount_cents=100_000,
        source="schedule",
        source_detail={"lease_ref": f"{tenancy_id}.txt", "citation": "Base Rent"},
    )


def test_csv_duplicate_is_disclosed_and_ambiguous_amount_stays_unmatched(tmp_path):
    store = BookStore(tmp_path / "books.db")
    store.setup_tenancy(
        tenancy_id="alpha",
        deal_id="d1",
        unit="100",
        tenant_name="Alpha Retail LLC",
    )
    store.setup_tenancy(
        tenancy_id="beta",
        deal_id="d1",
        unit="200",
        tenant_name="Beta Foods LLC",
    )
    _scheduled_charge(store, "alpha", "alpha-rent")
    _scheduled_charge(store, "beta", "beta-rent")
    export = tmp_path / "bank-export.csv"
    export.write_text(
        "Posted Date,Amount,Description\n"
        "01/05/2025,1000.00,MONTHLY RENT\n"
        "01/05/2025,1000.00,MONTHLY RENT\n"
        "01/06/2025,1000.00,ACH ALPHA RETAIL LLC RENT\n"
        "01/07/2025,-25.00,MONTHLY BANK FEE\n",
        encoding="utf-8",
    )

    imported = import_bank_csv(
        export,
        {
            "date_col": "Posted Date",
            "amount_col": "Amount",
            "desc_col": "Description",
            "debit_credit": "credits_positive",
        },
        store=store,
    )
    matched = match_receipts("2025-01", store=store)

    assert imported["source_row_count"] == 4
    assert imported["candidate_receipt_count"] == 2
    assert imported["ignored_outflow_count"] == 1
    assert len(imported["duplicate_rows"]) == 1
    ambiguous = next(
        receipt for receipt in matched["receipts"] if receipt["payer_hint"] == "MONTHLY RENT"
    )
    assert ambiguous["status"] == "unmatched"
    assert ambiguous["matched_charge_ids"] == []
    assert {candidate["tenancy_id"] for candidate in ambiguous["candidates"]} == {
        "alpha",
        "beta",
    }
    clear = next(
        receipt for receipt in matched["receipts"] if "ALPHA" in receipt["payer_hint"]
    )
    assert clear["status"] == "matched"
    assert clear["tenancy_id"] == "alpha"
    assert clear["matched_charge_ids"] == ["alpha-rent"]
