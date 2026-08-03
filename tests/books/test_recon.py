"""Hand-computed rent bridge and exact aging-boundary tests."""

from cre_mcp.books.bankimport import match_receipts
from cre_mcp.books.recon import ar_aging, rent_to_cash
from cre_mcp.books.store import BookStore


def test_rent_to_cash_deltas_balance_to_hand_computed_values(tmp_path):
    store = BookStore(tmp_path / "books.db")
    store.setup_tenancy(
        tenancy_id="alpha",
        deal_id="d1",
        unit="100",
        tenant_name="Alpha Retail LLC",
    )
    store.add_charge(
        charge_id="rent",
        tenancy_id="alpha",
        period="2025-01",
        kind="rent",
        amount_cents=100_001,
        source="schedule",
        source_detail={"lease_ref": "alpha.txt", "citation": "Base Rent"},
    )
    store.add_charge(
        charge_id="cam",
        tenancy_id="alpha",
        period="2025-01",
        kind="cam",
        amount_cents=2_500,
        source="manual",
        source_detail={"author": "Max"},
    )
    store.add_receipt(
        receipt_id="deposit-1",
        date="2025-01-05",
        amount_cents=100_001,
        payer_hint="ACH ALPHA RETAIL LLC",
        method="bank_csv",
        import_id=None,
    )
    match_receipts("2025-01", store=store)

    result = rent_to_cash("2025-01", store=store)

    row = result["tenancies"][0]
    assert row["scheduled_cents"] == 100_001
    assert row["billed_cents"] == 102_501
    assert row["collected_cents"] == 100_001
    assert row["outstanding_cents"] == 2_500
    assert row["deltas"]["scheduled_to_billed_cents"] == 2_500
    assert row["deltas"]["billed_to_collected_cents"] == -2_500
    assert result["rollup"]["outstanding_cents"] == 2_500


def test_aging_bucket_boundaries_are_exact(tmp_path):
    store = BookStore(tmp_path / "books.db")
    store.setup_tenancy(
        tenancy_id="alpha",
        deal_id="d1",
        unit="100",
        tenant_name="Alpha Retail LLC",
    )
    store.add_charge(
        charge_id="jan-rent",
        tenancy_id="alpha",
        period="2025-01",
        kind="rent",
        amount_cents=100,
        source="schedule",
        source_detail={"lease_ref": "alpha.txt", "citation": "Base Rent"},
    )

    expected = {
        "2025-01-31": "0-30",
        "2025-02-01": "31-60",
        "2025-03-02": "31-60",
        "2025-03-03": "61-90",
        "2025-04-01": "61-90",
        "2025-04-02": "90+",
    }
    for as_of, bucket in expected.items():
        result = ar_aging(as_of, store=store)
        assert result["tenancies"][0]["charges"][0]["bucket"] == bucket
        assert result["rollup_buckets_cents"][bucket] == 100

    legal = ar_aging("2025-02-01", store=store)["tenancies"][0][
        "delinquency_stage"
    ]
    assert legal["label"].startswith("CONVENTION")
    assert legal["counsel_review_required"] is True
