"""Lease-sourced and manually authorized property billing."""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence

from cre_mcp.leases.abstract import abstract_lease
from cre_mcp.leases.reader import read_lease
from cre_mcp.leases.schedule import rent_schedule

from .store import BookStore, require_cents

MANUAL_KINDS = frozenset({"cam", "tax", "ins", "other"})


def validate_period(value: str, *, name: str = "period") -> str:
    """Validate and normalize a ``YYYY-MM`` accounting period."""

    text = str(value).strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM") from exc
    if parsed.strftime("%Y-%m") != text:
        raise ValueError(f"{name} must be YYYY-MM")
    return text


def normalize_period_range(
    period_range: str | Sequence[str] | Mapping[str, str],
) -> tuple[str, str]:
    """Accept one period, a two-item range, or a from/to mapping."""

    if isinstance(period_range, str):
        start = end = validate_period(period_range)
    elif isinstance(period_range, Mapping):
        raw_start = period_range.get("from_period") or period_range.get("start")
        raw_end = period_range.get("to_period") or period_range.get("end") or raw_start
        if raw_start is None or raw_end is None:
            raise ValueError("period_range mapping needs from_period/start and to_period/end")
        start = validate_period(raw_start, name="from_period")
        end = validate_period(raw_end, name="to_period")
    else:
        values = list(period_range)
        if len(values) != 2:
            raise ValueError("period_range must contain exactly two YYYY-MM values")
        start = validate_period(values[0], name="from_period")
        end = validate_period(values[1], name="to_period")
    if start > end:
        raise ValueError("from_period must be on or before to_period")
    return start, end


def iter_periods(start: str, end: str) -> list[str]:
    """Return inclusive accounting months in lexical/chronological order."""

    first = datetime.strptime(validate_period(start), "%Y-%m").date()
    last = datetime.strptime(validate_period(end), "%Y-%m").date()
    periods: list[str] = []
    cursor = first
    while cursor <= last:
        periods.append(cursor.strftime("%Y-%m"))
        cursor = date(
            cursor.year + (cursor.month == 12),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return periods


def _date_bounds(start: str, end: str) -> tuple[date, date]:
    start_date = datetime.strptime(start, "%Y-%m").date()
    end_first = datetime.strptime(end, "%Y-%m").date()
    end_date = date(
        end_first.year,
        end_first.month,
        calendar.monthrange(end_first.year, end_first.month)[1],
    )
    return start_date, end_date


def dollars_to_cents(value: Any) -> int:
    """Convert an already-calculated dollar value to cents without float math."""

    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("scheduled dollar value must be numeric") from exc
    if not decimal.is_finite() or decimal < 0:
        raise ValueError("scheduled dollar value must be finite and non-negative")
    return int((decimal * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _tenancy_record(
    tenancy: str | Mapping[str, Any], store: BookStore
) -> dict[str, Any]:
    if isinstance(tenancy, str):
        return store.get_tenancy(tenancy)
    try:
        tenancy_id = str(tenancy["tenancy_id"])
    except (KeyError, TypeError) as exc:
        raise ValueError("tenancy must be a tenancy_id or tenancy record") from exc
    # Reload the durable record so a caller cannot override its lease reference.
    return store.get_tenancy(tenancy_id)


def _lease_schedule(
    tenancy: Mapping[str, Any], start: str, end: str
) -> tuple[list[dict[str, object]], str]:
    lease_ref = tenancy.get("lease_ref")
    if not lease_ref:
        raise ValueError("tenancy has no lease_ref; scheduled rent cannot be inferred")
    lease_path = Path(str(lease_ref)).expanduser()
    if not lease_path.is_file():
        raise FileNotFoundError(lease_path)
    document = read_lease(lease_path)
    abstract = abstract_lease(document.text)
    abstract.source_path = document.source_path
    abstract.deal_id = str(tenancy.get("deal_id") or "") or None
    range_start, range_end = _date_bounds(start, end)
    rows = rent_schedule(abstract, range_start, range_end)
    return rows, document.source_path


def _schedule_detail(
    *,
    tenancy: Mapping[str, Any],
    row: Mapping[str, object],
    source_path: str,
) -> dict[str, Any]:
    quotes = [str(quote) for quote in row.get("source_quotes", []) if str(quote)]
    return {
        "calculator": "cre_mcp.leases.schedule.rent_schedule",
        "deal_id": tenancy.get("deal_id"),
        "lease_ref": source_path,
        "schedule_period": row["month"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "proration_convention": row["proration_convention"],
        "citation": {
            "source_path": source_path,
            "lease_quotes": quotes,
        },
    }


def _schedule_charge_id(tenancy_id: str, period: str) -> str:
    digest = hashlib.sha256(
        f"{tenancy_id}\x1f{period}\x1frent\x1fschedule".encode("utf-8")
    ).hexdigest()
    return f"bkc-schedule-{digest[:32]}"


def post_scheduled_charges(
    tenancy: str | Mapping[str, Any],
    period_range: str | Sequence[str] | Mapping[str, str],
    *,
    db_path: str | Path | None = None,
    store: BookStore | None = None,
) -> dict[str, Any]:
    """Post one cited, idempotent rent charge for each calculable lease month."""

    books = store or BookStore(db_path)
    record = _tenancy_record(tenancy, books)
    start, end = normalize_period_range(period_range)
    rows, source_path = _lease_schedule(record, start, end)
    posted: list[dict[str, Any]] = []
    already_posted: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for row in rows:
        period = str(row["month"])
        if row.get("status") != "calculated" or row.get("total_cash_rent") is None:
            gaps.append(
                {
                    "period": period,
                    "status": row.get("status"),
                    "missing_inputs": list(row.get("missing_inputs", [])),
                    "reason": "Lease schedule did not produce a supported cash-rent total.",
                }
            )
            continue
        detail = _schedule_detail(tenancy=record, row=row, source_path=source_path)
        charge, inserted = books.add_charge(
            charge_id=_schedule_charge_id(str(record["tenancy_id"]), period),
            tenancy_id=str(record["tenancy_id"]),
            period=period,
            kind="rent",
            amount_cents=dollars_to_cents(row["total_cash_rent"]),
            source="schedule",
            source_detail=detail,
        )
        (posted if inserted else already_posted).append(charge)
    return {
        "tenancy_id": record["tenancy_id"],
        "from_period": start,
        "to_period": end,
        "posted": posted,
        "already_posted": already_posted,
        "gaps": gaps,
        "honesty": (
            "Only calculated lease-schedule rows were posted. Missing CPI, sales, "
            "or period coverage remains an explicit gap."
        ),
    }


def post_manual_charge(
    tenancy_id: str,
    period: str,
    kind: str,
    amount_cents: int,
    *,
    author: str,
    source_detail: str | Mapping[str, Any] | None = None,
    charge_id: str | None = None,
    db_path: str | Path | None = None,
    store: BookStore | None = None,
) -> dict[str, Any]:
    """Post a non-rent charge with the responsible human author preserved."""

    normalized_kind = str(kind).strip().casefold()
    if normalized_kind not in MANUAL_KINDS:
        raise ValueError(
            "manual kind must be cam, tax, ins, or other; rent comes from the lease schedule"
        )
    normalized_author = str(author).strip()
    if not normalized_author:
        raise ValueError("author cannot be blank")
    books = store or BookStore(db_path)
    books.get_tenancy(tenancy_id)
    detail: dict[str, Any] = {"author": normalized_author}
    if isinstance(source_detail, Mapping):
        detail["detail"] = dict(source_detail)
    elif source_detail is not None:
        detail["detail"] = str(source_detail)
    charge, inserted = books.add_charge(
        charge_id=charge_id,
        tenancy_id=tenancy_id,
        period=validate_period(period),
        kind=normalized_kind,
        amount_cents=require_cents(amount_cents),
        source="manual",
        source_detail=detail,
    )
    return {"charge": charge, "posted": inserted}


def lease_to_billing_audit(
    tenancy: str | Mapping[str, Any],
    period_range: str | Sequence[str] | Mapping[str, str],
    *,
    db_path: str | Path | None = None,
    store: BookStore | None = None,
) -> dict[str, Any]:
    """Recompute contractual rent and compare it with every posted rent line."""

    books = store or BookStore(db_path)
    record = _tenancy_record(tenancy, books)
    start, end = normalize_period_range(period_range)
    rows, source_path = _lease_schedule(record, start, end)
    schedule_by_period = {str(row["month"]): row for row in rows}
    posted = books.list_charges(
        tenancy_id=str(record["tenancy_id"]), from_period=start, to_period=end
    )
    posted_rent: dict[str, list[dict[str, Any]]] = {}
    for charge in posted:
        if charge["kind"] == "rent":
            posted_rent.setdefault(str(charge["period"]), []).append(charge)

    results: list[dict[str, Any]] = []
    discrepancies: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for period in iter_periods(start, end):
        row = schedule_by_period[period]
        citation = _schedule_detail(
            tenancy=record, row=row, source_path=source_path
        )["citation"]
        charges = posted_rent.get(period, [])
        billed_cents = sum(int(charge["amount_cents"]) for charge in charges)
        if row.get("status") != "calculated" or row.get("total_cash_rent") is None:
            gap = {
                "period": period,
                "status": "not_auditable",
                "posted_rent_cents": billed_cents,
                "missing_inputs": list(row.get("missing_inputs", [])),
                "lease_citation": citation,
            }
            gaps.append(gap)
            results.append(gap)
            continue
        expected_cents = dollars_to_cents(row["total_cash_rent"])
        delta_cents = billed_cents - expected_cents
        status = (
            "over_billed"
            if delta_cents > 0
            else "under_billed"
            if delta_cents < 0
            else "matched"
        )
        result = {
            "period": period,
            "status": status,
            "lease_expected_cents": expected_cents,
            "posted_rent_cents": billed_cents,
            "delta_cents": delta_cents,
            "posted_charge_ids": [charge["charge_id"] for charge in charges],
            "lease_citation": citation,
        }
        results.append(result)
        if delta_cents:
            discrepancies.append(result)
    return {
        "tenancy_id": record["tenancy_id"],
        "from_period": start,
        "to_period": end,
        "periods": results,
        "discrepancies": discrepancies,
        "gaps": gaps,
    }


__all__ = [
    "dollars_to_cents",
    "iter_periods",
    "lease_to_billing_audit",
    "normalize_period_range",
    "post_manual_charge",
    "post_scheduled_charges",
    "validate_period",
]
