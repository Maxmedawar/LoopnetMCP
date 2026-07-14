"""Local bank-CSV ingestion and deliberately conservative receipt matching."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence

from .billing import validate_period
from .store import BookStore

_CREDITS_POSITIVE = frozenset(
    {
        "credit_positive",
        "credits_positive",
        "credits_are_positive",
        "debit_negative",
        "debits_negative",
        "inflows_positive",
    }
)
_DEBITS_POSITIVE = frozenset(
    {
        "debit_positive",
        "debits_positive",
        "debits_are_positive",
        "credit_negative",
        "credits_negative",
        "inflows_negative",
    }
)


def _column(mapping: Mapping[str, Any], name: str) -> str:
    value = str(mapping.get(name, "")).strip()
    if not value:
        raise ValueError(f"mapping requires {name}")
    return value


def _convention(mapping: Mapping[str, Any]) -> str:
    value = mapping.get("debit_credit", mapping.get("debit_credit_convention"))
    if isinstance(value, Mapping):
        value = value.get("convention")
    normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized in _CREDITS_POSITIVE:
        return "credits_positive"
    if normalized in _DEBITS_POSITIVE:
        return "debits_positive"
    raise ValueError(
        "debit_credit must state whether credits or debits are positive "
        "(for example, 'credits_positive')"
    )


def _signed_cents(raw: Any) -> int:
    text = str(raw).strip()
    if not text:
        raise ValueError("bank amount cannot be blank")
    negative_parentheses = text.startswith("(") and text.endswith(")")
    cleaned = text.replace("$", "").replace(",", "").strip()
    if negative_parentheses:
        cleaned = "-" + cleaned[1:-1].strip()
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid bank amount {raw!r}") from exc
    if not value.is_finite():
        raise ValueError(f"invalid bank amount {raw!r}")
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _receipt_amount(raw: Any, convention: str) -> int | None:
    signed = _signed_cents(raw)
    normalized = signed if convention == "credits_positive" else -signed
    return normalized if normalized > 0 else None


def _bank_date(raw: Any) -> str:
    text = str(raw).strip()
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y/%m/%d",
        "%m-%d-%Y",
        "%m-%d-%y",
    ):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unsupported bank date {raw!r}")


def import_bank_csv(
    path: str | Path,
    mapping: Mapping[str, Any],
    *,
    db_path: str | Path | None = None,
    store: BookStore | None = None,
) -> dict[str, Any]:
    """Import deposit rows from a bank export using explicit column semantics.

    Exact duplicate normalized rows in the same export share one deterministic
    receipt ID.  That protects cash totals from accidental duplicate exports,
    while the result discloses that a bank transaction ID is still unavailable.
    """

    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(source)
    date_col = _column(mapping, "date_col")
    amount_col = _column(mapping, "amount_col")
    desc_col = _column(mapping, "desc_col")
    convention = _convention(mapping)
    raw_bytes = source.read_bytes()
    canonical_mapping = json.dumps(mapping, sort_keys=True, separators=(",", ":"), default=str)
    import_hash = hashlib.sha256(raw_bytes + b"\x1f" + canonical_mapping.encode("utf-8")).hexdigest()
    import_id = f"bki-{import_hash[:32]}"

    rows: list[dict[str, Any]] = []
    raw_row_count = 0
    ignored_outflows = 0
    seen_receipts: dict[str, int] = {}
    duplicate_rows: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("bank CSV needs a header row")
        missing = [
            column
            for column in (date_col, amount_col, desc_col)
            if column not in reader.fieldnames
        ]
        if missing:
            raise ValueError(f"bank CSV is missing mapped columns: {', '.join(missing)}")
        for line_number, row in enumerate(reader, start=2):
            raw_row_count += 1
            try:
                amount_cents = _receipt_amount(row.get(amount_col), convention)
                normalized_date = _bank_date(row.get(date_col))
            except ValueError as exc:
                raise ValueError(f"bank CSV line {line_number}: {exc}") from exc
            if amount_cents is None:
                ignored_outflows += 1
                continue
            payer_hint = str(row.get(desc_col) or "").strip()
            fingerprint_payload = {
                "import_id": import_id,
                "date": normalized_date,
                "amount_cents": amount_cents,
                "payer_hint": payer_hint,
            }
            fingerprint = hashlib.sha256(
                json.dumps(
                    fingerprint_payload, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            receipt_id = f"bkr-{fingerprint[:32]}"
            if receipt_id in seen_receipts:
                duplicate_rows.append(
                    {
                        "line_number": line_number,
                        "duplicates_line_number": seen_receipts[receipt_id],
                        "receipt_id": receipt_id,
                    }
                )
                continue
            seen_receipts[receipt_id] = line_number
            rows.append(
                {
                    "receipt_id": receipt_id,
                    "date": normalized_date,
                    "amount_cents": amount_cents,
                    "payer_hint": payer_hint,
                    "source_line_number": line_number,
                }
            )

    books = store or BookStore(db_path)
    imported_receipts = 0
    with books.connection() as connection:
        new_import = books.create_import(
            import_id=import_id,
            filename=source.name,
            row_count=raw_row_count,
            mapping={
                **dict(mapping),
                "normalized_debit_credit": convention,
            },
            connection=connection,
        )
        for row in rows:
            inserted = books.add_receipt(
                receipt_id=row["receipt_id"],
                date=row["date"],
                amount_cents=row["amount_cents"],
                payer_hint=row["payer_hint"],
                method="bank_csv",
                import_id=import_id,
                connection=connection,
            )
            imported_receipts += int(inserted)
    return {
        "import_id": import_id,
        "filename": source.name,
        "source_row_count": raw_row_count,
        "candidate_receipt_count": len(rows),
        "inserted_receipt_count": imported_receipts,
        "ignored_outflow_count": ignored_outflows,
        "duplicate_rows": duplicate_rows,
        "already_imported": not new_import,
        "receipts": rows,
        "honesty": (
            "Exact normalized duplicate rows are collapsed because this mapping has no "
            "bank transaction-ID column. Verify duplicates if the bank can post two truly "
            "identical deposits."
        ),
    }


_LEGAL_SUFFIXES = {
    "llc",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "co",
    "lp",
    "llp",
    "ltd",
    "limited",
    "the",
}


def _tokens(value: Any) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", str(value).casefold()) if token]


def _tenant_hint(tenant_name: str, payer_hint: str) -> bool:
    tenant_tokens = [
        token for token in _tokens(tenant_name) if token not in _LEGAL_SUFFIXES and len(token) >= 3
    ]
    payer_tokens = set(_tokens(payer_hint))
    return bool(tenant_tokens and any(token in payer_tokens for token in tenant_tokens))


def _charge_sets(charges: Sequence[Mapping[str, Any]], target: int) -> list[list[str]]:
    """Find every exact charge set for small monthly ledgers, without guessing."""

    ordered = sorted(charges, key=lambda charge: str(charge["charge_id"]))
    if len(ordered) > 12:
        candidates: list[list[str]] = []
        if sum(int(charge["amount_cents"]) for charge in ordered) == target:
            candidates.append([str(charge["charge_id"]) for charge in ordered])
        for charge in ordered:
            if int(charge["amount_cents"]) == target:
                candidates.append([str(charge["charge_id"])])
        return candidates

    results: list[list[str]] = []

    def visit(index: int, remaining: int, selected: list[str]) -> None:
        if remaining == 0:
            if selected:
                results.append(list(selected))
            return
        if remaining < 0 or index >= len(ordered):
            return
        charge = ordered[index]
        amount = int(charge["amount_cents"])
        selected.append(str(charge["charge_id"]))
        visit(index + 1, remaining - amount, selected)
        selected.pop()
        visit(index + 1, remaining, selected)

    visit(0, target, [])
    unique = {tuple(candidate) for candidate in results}
    return [list(candidate) for candidate in sorted(unique)]


def _candidate(
    tenancy: Mapping[str, Any],
    charge_ids: Sequence[str],
    amount_cents: int,
    payer_hint: str,
) -> dict[str, Any]:
    return {
        "tenancy_id": tenancy["tenancy_id"],
        "tenant_name": tenancy["tenant_name"],
        "charge_ids": list(charge_ids),
        "expected_amount_cents": amount_cents,
        "tenant_hint_match": _tenant_hint(str(tenancy["tenant_name"]), payer_hint),
    }


def match_receipts(
    period: str,
    *,
    db_path: str | Path | None = None,
    store: BookStore | None = None,
) -> dict[str, Any]:
    """Auto-match only one unambiguous exact amount plus tenant hint.

    A likely partial payment is labeled ``partial`` but receives no allocation.
    Every ambiguous exact or partial possibility is returned as a candidate and
    remains available for human resolution.
    """

    normalized_period = validate_period(period)
    books = store or BookStore(db_path)
    charges = books.list_charges(period=normalized_period)
    tenancies = {item["tenancy_id"]: item for item in books.list_tenancies()}
    receipts = books.list_receipts(period=normalized_period)
    paid_ids = {
        str(charge_id)
        for receipt in books.list_receipts(status="matched")
        for charge_id in receipt["matched_charge_ids"]
    }
    outstanding: dict[str, list[dict[str, Any]]] = {}
    for charge in charges:
        if charge["charge_id"] not in paid_ids:
            outstanding.setdefault(str(charge["tenancy_id"]), []).append(charge)

    results: list[dict[str, Any]] = []
    matched_count = 0
    partial_count = 0
    unmatched_count = 0
    for receipt in receipts:
        if receipt["status"] == "matched":
            results.append({**receipt, "candidates": [], "decision": "already_matched"})
            continue
        exact: list[dict[str, Any]] = []
        partial: list[dict[str, Any]] = []
        for tenancy_id, tenancy_charges in outstanding.items():
            tenancy = tenancies.get(tenancy_id)
            if tenancy is None:
                continue
            for charge_ids in _charge_sets(tenancy_charges, int(receipt["amount_cents"])):
                exact.append(
                    _candidate(
                        tenancy,
                        charge_ids,
                        int(receipt["amount_cents"]),
                        str(receipt["payer_hint"]),
                    )
                )
            total = sum(int(charge["amount_cents"]) for charge in tenancy_charges)
            if (
                int(receipt["amount_cents"]) < total
                and _tenant_hint(str(tenancy["tenant_name"]), str(receipt["payer_hint"]))
            ):
                partial.append(
                    _candidate(
                        tenancy,
                        [str(charge["charge_id"]) for charge in tenancy_charges],
                        total,
                        str(receipt["payer_hint"]),
                    )
                )

        hinted_exact = [candidate for candidate in exact if candidate["tenant_hint_match"]]
        if len(hinted_exact) == 1:
            selected = hinted_exact[0]
            updated = books.update_receipt_match(
                str(receipt["receipt_id"]),
                tenancy_id=str(selected["tenancy_id"]),
                matched_charge_ids=selected["charge_ids"],
                status="matched",
            )
            paid_ids.update(selected["charge_ids"])
            outstanding[str(selected["tenancy_id"])] = [
                charge
                for charge in outstanding[str(selected["tenancy_id"])]
                if charge["charge_id"] not in set(selected["charge_ids"])
            ]
            matched_count += 1
            results.append(
                {
                    **updated,
                    "candidates": exact,
                    "decision": "auto_matched_exact_amount_and_tenant_hint",
                }
            )
        elif exact:
            updated = books.update_receipt_match(
                str(receipt["receipt_id"]),
                tenancy_id=None,
                matched_charge_ids=[],
                status="unmatched",
            )
            unmatched_count += 1
            results.append(
                {
                    **updated,
                    "candidates": exact,
                    "decision": "not_matched_ambiguous_exact_candidates",
                }
            )
        elif partial:
            updated = books.update_receipt_match(
                str(receipt["receipt_id"]),
                tenancy_id=None,
                matched_charge_ids=[],
                status="partial",
            )
            partial_count += 1
            results.append(
                {
                    **updated,
                    "candidates": exact + partial,
                    "decision": "not_allocated_likely_partial_or_ambiguous",
                }
            )
        else:
            updated = books.update_receipt_match(
                str(receipt["receipt_id"]),
                tenancy_id=None,
                matched_charge_ids=[],
                status="unmatched",
            )
            unmatched_count += 1
            results.append(
                {
                    **updated,
                    "candidates": exact,
                    "decision": "not_matched_missing_unique_amount_plus_tenant_hint",
                }
            )
    return {
        "period": normalized_period,
        "receipts": results,
        "matched_count": matched_count,
        "partial_count": partial_count,
        "unmatched_count": unmatched_count,
        "matching_rule": (
            "Auto-match requires exactly one exact charge-set amount whose tenant name "
            "is hinted by the bank description. Partial and ambiguous candidates are "
            "never allocated."
        ),
    }


__all__ = ["import_bank_csv", "match_receipts"]
