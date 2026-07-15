"""Heuristic maintenance screening and penny-exact balance validation.

The deferred-maintenance screen intentionally reports its assumptions and
arithmetic.  It identifies patterns for follow-up; it does not establish that
maintenance was deferred.  Balance validation keeps all money in integer cents.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from cre_mcp.books.store import BookStore


REPAIR_TREND_MIN_PERIODS = 3
RISING_REPAIR_THRESHOLD_BPS = 2_500  # 25% increase in average monthly repair spend
EMERGENCY_RATIO_THRESHOLD_BPS = 3_000  # 30% of repair spend

_EXPENSE_FIELDS = frozenset({"period", "category", "amount_cents", "memo"})
_BALANCE_FIELDS = (
    "deposits_held_cents",
    "prepaid_cents",
    "ar_cents",
    "ap_cents",
)
_REPAIR_TERMS = (
    "repair",
    "maintenance",
    "r&m",
    "service call",
    "emergency",
    "after hours",
)
_CAPEX_TERMS = (
    "capex",
    "capital expenditure",
    "capital improvement",
    "capital replacement",
)
_EMERGENCY_TERMS = ("emergency", "urgent", "after hours", "after-hours")


def _period(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM")
    normalized = value.strip()
    try:
        parsed = date.fromisoformat(normalized + "-01")
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM") from exc
    if parsed.strftime("%Y-%m") != normalized:
        raise ValueError(f"{field} must be YYYY-MM")
    return normalized


def _text(value: Any, *, field: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")
    return value.strip()


def _cents(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer number of cents")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(term in folded for term in terms)


def deferred_maintenance_screen(
    expense_lines: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Screen recorded expenses for two disclosed deferred-maintenance patterns."""

    if (
        isinstance(expense_lines, (str, bytes, Mapping))
        or not isinstance(expense_lines, Sequence)
    ):
        raise ValueError("expense_lines must be a sequence of mappings")

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(expense_lines):
        path = f"expense_lines[{index}]"
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path} must be a mapping")
        unknown = sorted(str(key) for key in set(raw) - _EXPENSE_FIELDS)
        if unknown:
            raise ValueError(f"unrecognized inputs at {path}: {', '.join(unknown)}")
        missing = [field for field in ("period", "category", "amount_cents") if field not in raw]
        if missing:
            raise ValueError(f"{path} missing required fields: {', '.join(missing)}")
        period = _period(raw["period"], field=f"{path}.period")
        category = _text(raw["category"], field=f"{path}.category")
        assert category is not None
        amount = _cents(raw["amount_cents"], field=f"{path}.amount_cents")
        memo = _text(raw.get("memo"), field=f"{path}.memo", nullable=True)
        search_text = f"{category} {memo or ''}"
        is_capex = _contains(category, _CAPEX_TERMS)
        is_repair = _contains(search_text, _REPAIR_TERMS) and not is_capex
        is_emergency = is_repair and _contains(search_text, _EMERGENCY_TERMS)
        normalized.append(
            {
                "period": period,
                "category": category,
                "amount_cents": amount,
                "memo": memo,
                "classification": (
                    "capex" if is_capex else "emergency_repair" if is_emergency else "repair" if is_repair else "other"
                ),
                "is_repair": is_repair,
                "is_capex": is_capex,
                "is_emergency_repair": is_emergency,
            }
        )

    periods = sorted({line["period"] for line in normalized})
    repair_by_period = {period: 0 for period in periods}
    for line in normalized:
        if line["is_repair"]:
            repair_by_period[line["period"]] += line["amount_cents"]

    repair_total = sum(repair_by_period.values())
    capex_total = sum(line["amount_cents"] for line in normalized if line["is_capex"])
    emergency_total = sum(
        line["amount_cents"] for line in normalized if line["is_emergency_repair"]
    )

    enough_periods = len(periods) >= REPAIR_TREND_MIN_PERIODS
    split_at = len(periods) // 2
    early_periods = periods[:split_at]
    recent_periods = periods[split_at:]
    early_sum = sum(repair_by_period[period] for period in early_periods)
    recent_sum = sum(repair_by_period[period] for period in recent_periods)
    early_count = len(early_periods)
    recent_count = len(recent_periods)

    rising = False
    if enough_periods and early_count and recent_count and recent_sum > 0:
        if early_sum == 0:
            rising = True
        else:
            # recent average / early average >= 1.25, with integer arithmetic.
            rising = (
                recent_sum * early_count * 10_000
                >= early_sum * recent_count * (10_000 + RISING_REPAIR_THRESHOLD_BPS)
            )
    no_capex = capex_total == 0
    rising_without_capex = rising and no_capex and repair_total > 0

    if early_sum:
        change_bps: int | None = (
            (recent_sum * early_count - early_sum * recent_count)
            * 10_000
            // (early_sum * recent_count)
        )
    else:
        change_bps = None

    emergency_ratio_bps = (
        emergency_total * 10_000 // repair_total if repair_total else None
    )
    emergency_ratio_triggered = (
        repair_total > 0
        and emergency_total * 10_000
        >= repair_total * EMERGENCY_RATIO_THRESHOLD_BPS
    )

    trend_heuristic = {
        "heuristic_id": "rising_repairs_without_capex",
        "label": "HEURISTIC — rising recorded repair spend with no recorded capex",
        "triggered": rising_without_capex,
        "thresholds": {
            "minimum_distinct_periods": REPAIR_TREND_MIN_PERIODS,
            "minimum_recent_average_increase_bps": RISING_REPAIR_THRESHOLD_BPS,
            "requires_zero_recorded_capex_cents": True,
        },
        "arithmetic": {
            "periods": periods,
            "repair_spend_by_period_cents": repair_by_period,
            "early_periods": early_periods,
            "early_repair_sum_cents": early_sum,
            "early_average_fraction": f"{early_sum}/{early_count}" if early_count else None,
            "recent_periods": recent_periods,
            "recent_repair_sum_cents": recent_sum,
            "recent_average_fraction": f"{recent_sum}/{recent_count}" if recent_count else None,
            "recent_average_change_bps": change_bps,
            "recorded_capex_cents": capex_total,
        },
        "basis": (
            "The recorded months are split chronologically into an early half and a "
            "recent half. A flag requires at least three periods, a recent average at "
            "least 25% above the early average (any positive recent average when the "
            "early baseline is zero), and zero lines classified as recorded capex spend."
        ),
        "limitations": (
            "Category-keyword classification can miss differently coded work, and no "
            "capex in these lines does not prove that no capex occurred elsewhere."
        ),
    }
    emergency_heuristic = {
        "heuristic_id": "high_emergency_repair_ratio",
        "label": "HEURISTIC — high emergency share of recorded repair spend",
        "triggered": emergency_ratio_triggered,
        "thresholds": {
            "minimum_emergency_share_bps": EMERGENCY_RATIO_THRESHOLD_BPS,
        },
        "arithmetic": {
            "emergency_repair_cents": emergency_total,
            "total_repair_cents": repair_total,
            "emergency_share_bps": emergency_ratio_bps,
            "formula": "emergency_repair_cents * 10,000 / total_repair_cents",
        },
        "basis": (
            "A flag occurs when emergency/urgent/after-hours lines are at least 30% "
            "of recorded repair spend."
        ),
        "limitations": (
            "Memo and category keywords are a screening proxy; legitimate one-time "
            "events can produce a high emergency share."
        ),
    }
    heuristics = [trend_heuristic, emergency_heuristic]
    flagged = [item["heuristic_id"] for item in heuristics if item["triggered"]]

    return {
        "screening_flag": bool(flagged),
        "deferred_maintenance_proven": False,
        "flagged_heuristics": flagged,
        "heuristics": heuristics,
        "totals": {
            "all_expense_cents": sum(line["amount_cents"] for line in normalized),
            "repair_cents": repair_total,
            "emergency_repair_cents": emergency_total,
            "capex_cents": capex_total,
        },
        "classified_lines": normalized,
        "classification_basis": {
            "repair_terms": list(_REPAIR_TERMS),
            "capex_terms": list(_CAPEX_TERMS),
            "emergency_terms": list(_EMERGENCY_TERMS),
        },
        "honesty": (
            "These are convention-labeled screening heuristics, not a causal finding. "
            "Review invoices, work orders, capitalization policy, and physical condition."
        ),
    }


def _validate_balance_map(values: Mapping[str, Any], *, field: str) -> dict[str, int]:
    if not isinstance(values, Mapping):
        raise ValueError(f"{field} must be a mapping")
    unknown = sorted(str(key) for key in set(values) - set(_BALANCE_FIELDS))
    missing = [key for key in _BALANCE_FIELDS if key not in values]
    if unknown:
        raise ValueError(f"unrecognized inputs at {field}: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"{field} missing required fields: {', '.join(missing)}")
    return {
        key: _cents(values[key], field=f"{field}.{key}")
        for key in _BALANCE_FIELDS
    }


def _books_expected(store: BookStore) -> tuple[dict[str, int | None], dict[str, Any]]:
    """Derive only the balance line the current books can prove: gross less paid AR."""

    charges = store.list_charges()
    receipts = store.list_receipts()
    tenancies = store.list_tenancies()
    charge_by_id = {str(charge["charge_id"]): charge for charge in charges}
    paid_charge_ids: set[str] = set()
    valid_receipt_ids: list[str] = []
    integrity_gaps: list[dict[str, Any]] = []

    for receipt in receipts:
        if receipt.get("status") != "matched":
            continue
        receipt_id = str(receipt["receipt_id"])
        ids = [str(value) for value in receipt.get("matched_charge_ids", [])]
        linked = [charge_by_id.get(charge_id) for charge_id in ids]
        missing = [charge_id for charge_id, charge in zip(ids, linked) if charge is None]
        duplicates = [charge_id for charge_id in ids if charge_id in paid_charge_ids]
        valid = [charge for charge in linked if charge is not None]
        linked_total = sum(int(charge["amount_cents"]) for charge in valid)
        tenancy_ids = {str(charge["tenancy_id"]) for charge in valid}
        reason: str | None = None
        if not ids:
            reason = "matched receipt has no linked charge IDs"
        elif missing:
            reason = "matched receipt references unknown charge IDs"
        elif duplicates or len(ids) != len(set(ids)):
            reason = "a charge is linked more than once"
        elif len(tenancy_ids) != 1 or str(receipt.get("tenancy_id") or "") not in tenancy_ids:
            reason = "receipt and linked charges do not identify exactly one tenancy"
        elif linked_total != int(receipt["amount_cents"]):
            reason = "receipt and linked charges are not penny-exact"
        if reason is not None:
            integrity_gaps.append(
                {
                    "receipt_id": receipt_id,
                    "reason": reason,
                    "receipt_amount_cents": int(receipt["amount_cents"]),
                    "linked_charge_total_cents": linked_total,
                    "missing_charge_ids": missing,
                    "duplicate_charge_ids": duplicates,
                }
            )
            continue
        paid_charge_ids.update(ids)
        valid_receipt_ids.append(receipt_id)

    billed_cents = sum(int(charge["amount_cents"]) for charge in charges)
    paid_cents = sum(
        int(charge_by_id[charge_id]["amount_cents"]) for charge_id in paid_charge_ids
    )
    expected: dict[str, int | None] = {
        "deposits_held_cents": None,
        "prepaid_cents": None,
        "ar_cents": billed_cents - paid_cents,
        "ap_cents": None,
    }
    trace = {
        "source": "read-only cre_mcp.books.store.BookStore records",
        "tenancy_count": len(tenancies),
        "charge_count": len(charges),
        "receipt_count": len(receipts),
        "billed_cents": billed_cents,
        "valid_matched_cash_cents": paid_cents,
        "ar_formula": "sum(all charge cents) - sum(penny-exact matched charge cents)",
        "paid_charge_ids": sorted(paid_charge_ids),
        "valid_receipt_ids": sorted(valid_receipt_ids),
        "integrity_gaps": integrity_gaps,
        "unavailable_reason": {
            "deposits_held_cents": "books tables do not store a security-deposit liability ledger",
            "prepaid_cents": "unmatched receipts are not assumed to be tenant prepayments",
            "ap_cents": "books tables do not store an accounts-payable ledger",
        },
    }
    return expected, trace


def balance_validation(
    balances: Mapping[str, Any],
    expected: Mapping[str, Any] | None = None,
    *,
    db_path: str | Path | None = None,
    store: BookStore | None = None,
) -> dict[str, Any]:
    """Compare each supplied balance line in cents against a transparent source.

    Pass ``expected`` for a four-line structured control balance.  If it is
    omitted, the function reads BookStore records and derives only AR; deposits,
    prepaids, and AP remain explicitly unavailable because those ledgers do not
    exist in the current books schema.
    """

    actual = _validate_balance_map(balances, field="balances")
    if expected is not None and (db_path is not None or store is not None):
        raise ValueError("provide structured expected or a books source, not both")
    if store is not None and db_path is not None:
        raise ValueError("provide store or db_path, not both")

    if expected is not None:
        expected_values: dict[str, int | None] = _validate_balance_map(
            expected, field="expected"
        )
        source = {
            "source": "caller-provided structured expected balances",
            "derivation": "No inference; each expected line was supplied in integer cents.",
        }
    else:
        expected_values, source = _books_expected(store or BookStore(db_path))

    lines: list[dict[str, Any]] = []
    for key in _BALANCE_FIELDS:
        expected_cents = expected_values[key]
        if expected_cents is None:
            line = {
                "line": key,
                "recorded_cents": actual[key],
                "expected_cents": None,
                "delta_cents": None,
                "match": None,
                "status": "unavailable",
                "arithmetic": None,
                "reason": source["unavailable_reason"][key],
            }
        else:
            delta = actual[key] - expected_cents
            line = {
                "line": key,
                "recorded_cents": actual[key],
                "expected_cents": expected_cents,
                "delta_cents": delta,
                "match": delta == 0,
                "status": "match" if delta == 0 else "mismatch",
                "arithmetic": f"{actual[key]} - {expected_cents} = {delta} cents",
                "reason": None,
            }
        lines.append(line)

    comparable = [line for line in lines if line["match"] is not None]
    unavailable = [line["line"] for line in lines if line["match"] is None]
    mismatches = [line["line"] for line in lines if line["match"] is False]
    all_four_available = not unavailable
    penny_exact = all_four_available and not mismatches

    return {
        "penny_exact": penny_exact,
        "balanced": penny_exact,
        "all_available_lines_match": bool(comparable) and not mismatches,
        "lines": lines,
        "by_line": {line["line"]: line for line in lines},
        "mismatches": mismatches,
        "unavailable_lines": unavailable,
        "source_basis": source,
        "honesty": (
            "A penny-exact result requires all four expected lines and zero-cent "
            "deltas. Book-derived validation does not fabricate deposit, prepaid, or "
            "AP ledgers that the books schema does not contain."
        ),
    }


__all__ = [
    "EMERGENCY_RATIO_THRESHOLD_BPS",
    "REPAIR_TREND_MIN_PERIODS",
    "RISING_REPAIR_THRESHOLD_BPS",
    "balance_validation",
    "deferred_maintenance_screen",
]
