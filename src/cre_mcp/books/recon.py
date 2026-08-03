"""Rent-to-cash reconciliation and convention-labeled receivable aging."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from .billing import validate_period
from .store import BookStore

AGING_BUCKETS = ("0-30", "31-60", "61-90", "90+")
_STAGE_BY_BUCKET: dict[str, dict[str, Any]] = {
    "0-30": {
        "label": "CONVENTION — reminder stage",
        "suggested_next_step": "Send a payment reminder and confirm remittance details.",
        "legal_step": False,
        "counsel_review_required": False,
    },
    "31-60": {
        "label": "CONVENTION — notice stage",
        "suggested_next_step": "Prepare the lease-required delinquency notice.",
        "legal_step": True,
        "counsel_review_required": True,
    },
    "61-90": {
        "label": "CONVENTION — escalation stage",
        "suggested_next_step": "Escalate collection and review lease remedies with counsel.",
        "legal_step": True,
        "counsel_review_required": True,
    },
    "90+": {
        "label": "CONVENTION — legal escalation stage",
        "suggested_next_step": "Escalate to counsel before default or enforcement action.",
        "legal_step": True,
        "counsel_review_required": True,
    },
}


def _as_date(value: date | datetime | str | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("as_of must be an ISO date") from exc


def aging_bucket(age_days: int) -> str:
    """Return the disclosed aging convention bucket for a non-negative age."""

    if age_days < 0:
        raise ValueError("age_days cannot be negative")
    if age_days <= 30:
        return "0-30"
    if age_days <= 60:
        return "31-60"
    if age_days <= 90:
        return "61-90"
    return "90+"


def _valid_payments(
    books: BookStore,
) -> tuple[set[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate receipt-to-charge traces before treating any cents as collected."""

    charges = {charge["charge_id"]: charge for charge in books.list_charges()}
    paid_ids: set[str] = set()
    allocations: list[dict[str, Any]] = []
    integrity_gaps: list[dict[str, Any]] = []
    for receipt in books.list_receipts(status="matched"):
        ids = [str(value) for value in receipt["matched_charge_ids"]]
        linked = [charges.get(charge_id) for charge_id in ids]
        missing = [charge_id for charge_id, charge in zip(ids, linked) if charge is None]
        duplicated = [charge_id for charge_id in ids if charge_id in paid_ids]
        valid = [charge for charge in linked if charge is not None]
        tenancies = {str(charge["tenancy_id"]) for charge in valid}
        linked_total = sum(int(charge["amount_cents"]) for charge in valid)
        if (
            not ids
            or missing
            or duplicated
            or len(tenancies) != 1
            or linked_total != int(receipt["amount_cents"])
            or str(receipt.get("tenancy_id") or "") not in tenancies
        ):
            integrity_gaps.append(
                {
                    "receipt_id": receipt["receipt_id"],
                    "receipt_amount_cents": receipt["amount_cents"],
                    "linked_charge_total_cents": linked_total,
                    "missing_charge_ids": missing,
                    "already_paid_charge_ids": duplicated,
                    "reason": (
                        "Matched receipt trace is not a one-tenancy, penny-exact set; "
                        "it is excluded from collected cash."
                    ),
                }
            )
            continue
        paid_ids.update(ids)
        for charge in valid:
            allocations.append(
                {
                    "receipt_id": receipt["receipt_id"],
                    "charge_id": charge["charge_id"],
                    "tenancy_id": charge["tenancy_id"],
                    "period": charge["period"],
                    "amount_cents": charge["amount_cents"],
                }
            )
    return paid_ids, allocations, integrity_gaps


def _group_amounts(rows: list[Mapping[str, Any]], key: str) -> dict[str, int]:
    grouped: dict[str, int] = {}
    for row in rows:
        label = str(row[key])
        grouped[label] = grouped.get(label, 0) + int(row["amount_cents"])
    return dict(sorted(grouped.items()))


def rent_to_cash(
    period: str,
    *,
    db_path: str | Path | None = None,
    store: BookStore | None = None,
) -> dict[str, Any]:
    """Bridge scheduled rent to billed charges, matched cash, and outstanding AR."""

    normalized_period = validate_period(period)
    books = store or BookStore(db_path)
    charges = books.list_charges(period=normalized_period)
    _, allocations, integrity_gaps = _valid_payments(books)
    period_allocations = [
        allocation
        for allocation in allocations
        if allocation["period"] == normalized_period
    ]
    allocation_by_tenancy = _group_amounts(period_allocations, "tenancy_id")
    charges_by_tenancy: dict[str, list[dict[str, Any]]] = {}
    for charge in charges:
        charges_by_tenancy.setdefault(str(charge["tenancy_id"]), []).append(charge)
    tenancies = {row["tenancy_id"]: row for row in books.list_tenancies()}

    rows: list[dict[str, Any]] = []
    for tenancy_id in sorted(charges_by_tenancy):
        tenancy_charges = charges_by_tenancy[tenancy_id]
        scheduled_rows = [row for row in tenancy_charges if row["source"] == "schedule"]
        non_schedule = [row for row in tenancy_charges if row["source"] != "schedule"]
        scheduled_cents = sum(int(row["amount_cents"]) for row in scheduled_rows)
        billed_cents = sum(int(row["amount_cents"]) for row in tenancy_charges)
        collected_cents = allocation_by_tenancy.get(tenancy_id, 0)
        outstanding_cents = billed_cents - collected_cents
        manual_by_kind = _group_amounts(non_schedule, "kind")
        paid_charge_ids = {
            str(allocation["charge_id"])
            for allocation in period_allocations
            if allocation["tenancy_id"] == tenancy_id
        }
        unpaid = [
            row for row in tenancy_charges if row["charge_id"] not in paid_charge_ids
        ]
        tenancy = tenancies.get(tenancy_id, {})
        rows.append(
            {
                "tenancy_id": tenancy_id,
                "tenant_name": tenancy.get("tenant_name", "unknown tenancy"),
                "unit": tenancy.get("unit"),
                "scheduled_cents": scheduled_cents,
                "billed_cents": billed_cents,
                "collected_cents": collected_cents,
                "outstanding_cents": outstanding_cents,
                "deltas": {
                    "scheduled_to_billed_cents": billed_cents - scheduled_cents,
                    "scheduled_to_billed_explanation": {
                        "non_schedule_charge_ids": [row["charge_id"] for row in non_schedule],
                        "non_schedule_by_kind_cents": manual_by_kind,
                    },
                    "billed_to_collected_cents": collected_cents - billed_cents,
                    "billed_to_collected_explanation": {
                        "unpaid_charge_ids": [row["charge_id"] for row in unpaid],
                        "unpaid_by_kind_cents": _group_amounts(unpaid, "kind"),
                    },
                },
                "trace": {
                    "scheduled_charge_ids": [row["charge_id"] for row in scheduled_rows],
                    "all_billed_charge_ids": [row["charge_id"] for row in tenancy_charges],
                    "receipt_allocations": [
                        allocation
                        for allocation in period_allocations
                        if allocation["tenancy_id"] == tenancy_id
                    ],
                },
            }
        )

    rollup = {
        "scheduled_cents": sum(row["scheduled_cents"] for row in rows),
        "billed_cents": sum(row["billed_cents"] for row in rows),
        "collected_cents": sum(row["collected_cents"] for row in rows),
        "outstanding_cents": sum(row["outstanding_cents"] for row in rows),
    }
    rollup["scheduled_to_billed_cents"] = (
        rollup["billed_cents"] - rollup["scheduled_cents"]
    )
    rollup["billed_to_collected_cents"] = (
        rollup["collected_cents"] - rollup["billed_cents"]
    )
    unapplied = [
        receipt
        for receipt in books.list_receipts(period=normalized_period)
        if receipt["status"] != "matched"
    ]
    return {
        "period": normalized_period,
        "tenancies": rows,
        "rollup": rollup,
        "unapplied_receipts": unapplied,
        "integrity_gaps": integrity_gaps,
        "honest_gaps": [
            "Bad-debt write-offs are not yet modeled, so outstanding is billed less matched cash.",
            "Partial and unmatched receipts are disclosed but never netted against AR.",
        ],
    }


def ar_aging(
    as_of: date | datetime | str | None = None,
    *,
    db_path: str | Path | None = None,
    store: BookStore | None = None,
) -> dict[str, Any]:
    """Age fully unpaid charge lines using first-of-month due-date convention."""

    point = _as_date(as_of)
    books = store or BookStore(db_path)
    paid_ids, _, integrity_gaps = _valid_payments(books)
    tenancies = {row["tenancy_id"]: row for row in books.list_tenancies()}
    unpaid_by_tenancy: dict[str, list[dict[str, Any]]] = {}
    future_charge_ids: list[str] = []
    for charge in books.list_charges():
        if charge["charge_id"] in paid_ids:
            continue
        due = date.fromisoformat(str(charge["period"]) + "-01")
        age = (point - due).days
        if age < 0:
            future_charge_ids.append(str(charge["charge_id"]))
            continue
        item = {
            **charge,
            "due_date_convention": due.isoformat(),
            "age_days": age,
            "bucket": aging_bucket(age),
        }
        unpaid_by_tenancy.setdefault(str(charge["tenancy_id"]), []).append(item)

    rows: list[dict[str, Any]] = []
    rollup_buckets = {bucket: 0 for bucket in AGING_BUCKETS}
    bucket_rank = {bucket: index for index, bucket in enumerate(AGING_BUCKETS)}
    for tenancy_id in sorted(unpaid_by_tenancy):
        items = unpaid_by_tenancy[tenancy_id]
        buckets = {bucket: 0 for bucket in AGING_BUCKETS}
        for item in items:
            buckets[item["bucket"]] += int(item["amount_cents"])
            rollup_buckets[item["bucket"]] += int(item["amount_cents"])
        oldest_bucket = max(
            (bucket for bucket, amount in buckets.items() if amount),
            key=lambda bucket: bucket_rank[bucket],
        )
        stage = dict(_STAGE_BY_BUCKET[oldest_bucket])
        tenancy = tenancies.get(tenancy_id, {})
        rows.append(
            {
                "tenancy_id": tenancy_id,
                "tenant_name": tenancy.get("tenant_name", "unknown tenancy"),
                "unit": tenancy.get("unit"),
                "buckets_cents": buckets,
                "total_outstanding_cents": sum(buckets.values()),
                "oldest_age_days": max(item["age_days"] for item in items),
                "delinquency_stage": stage,
                "charges": items,
            }
        )

    unapplied = [
        receipt
        for receipt in books.list_receipts()
        if receipt["status"] != "matched" and receipt["date"] <= point.isoformat()
    ]
    return {
        "as_of": point.isoformat(),
        "tenancies": rows,
        "rollup_buckets_cents": rollup_buckets,
        "total_outstanding_cents": sum(rollup_buckets.values()),
        "future_charge_ids_excluded": future_charge_ids,
        "unapplied_receipts_cents": sum(
            int(receipt["amount_cents"]) for receipt in unapplied
        ),
        "unapplied_receipts": unapplied,
        "integrity_gaps": integrity_gaps,
        "convention": {
            "due_date": "First calendar day of each charge period; no contractual due-date field exists yet.",
            "bucket_boundaries": {
                "0-30": "0 through 30 days",
                "31-60": "31 through 60 days",
                "61-90": "61 through 90 days",
                "90+": "more than 90 days (91 days and later)",
            },
            "stages": _STAGE_BY_BUCKET,
            "legal_warning": (
                "Stage labels and next steps are operational conventions, not legal advice. "
                "Every legal_step=true action is flagged for counsel review."
            ),
        },
    }


__all__ = ["AGING_BUCKETS", "aging_bucket", "ar_aging", "rent_to_cash"]
