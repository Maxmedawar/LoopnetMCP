"""GMP scope reconciliation with explicit placeholder and review flags.

This module does not certify a guaranteed maximum price.  It compares the
structured GMP inputs supplied by the caller with a structured drawing-scope
list.  Allowances, plugs, and contingency tests remain planning conventions
until the GC and design team validate them against bids and construction
documents.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any


CONVENTION_UNTIL_BID = "convention until bid"
GMP_CONTINGENCY_CONVENTION: dict[str, Any] = {
    "low_pct": 5.0,
    "high_pct": 10.0,
    "basis": "stated fixed-price line items plus separately stated allowances",
    "label": CONVENTION_UNTIL_BID,
    "warning": (
        "Planning screen only. Appropriate contingency depends on design maturity, "
        "delivery method, market, existing conditions, and retained owner risks."
    ),
}

_AMOUNT_KEYS = (
    "amount_cents",
    "allowance_cents",
    "contingency_cents",
    "total_cents",
    "cost_cents",
    "value_cents",
    "budget_cents",
)
_HIGH_RISK_TERMS = (
    "excluded",
    "excludes",
    "not included",
    "by owner",
    "owner furnished",
    "tbd",
    "to be determined",
    "unpriced",
    "not priced",
)
_MEDIUM_RISK_TERMS = (
    "allowance",
    "assume",
    "subject to",
    "design incomplete",
    "pending",
    "clarify",
    "verify",
    "future",
)


def _cents(value: Any, field: str, *, nonnegative: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer number of cents")
    if nonnegative and value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _rows(value: Any, field: str) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a list of objects")
    rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping):
            raise ValueError(f"{field}[{index}] must be an object")
        rows.append(row)
    return rows


def _label(value: Any, field: str) -> str:
    if isinstance(value, str):
        label = value.strip()
    elif isinstance(value, Mapping):
        raw = next(
            (
                value.get(key)
                for key in (
                    "scope_item",
                    "scope",
                    "item",
                    "line_item",
                    "description",
                    "desc",
                    "name",
                    "title",
                    "trade",
                    "cost_code",
                    "ref",
                    "id",
                )
                if value.get(key) not in (None, "")
            ),
            None,
        )
        label = str(raw).strip() if raw is not None else ""
    else:
        label = ""
    if not label:
        raise ValueError(f"{field} needs a non-empty scope label")
    return label


def _scope_key(label: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", label.casefold()))


def _amount(row: Mapping[str, Any], field: str) -> tuple[int | None, str | None]:
    for key in _AMOUNT_KEYS:
        if key in row and row[key] is not None:
            return _cents(row[key], f"{field}.{key}"), key
    return None, None


def _contingency(value: Any) -> tuple[int, str]:
    if value is None:
        return 0, "not supplied"
    if isinstance(value, Mapping):
        amount, key = _amount(value, "gmp.contingency")
        if amount is None:
            raise ValueError("gmp.contingency needs an integer cents amount")
        return amount, str(key)
    return _cents(value, "gmp.contingency"), "integer cents"


def _percent_from_bps(bps: int) -> float:
    return float((Decimal(bps) / Decimal(100)).quantize(Decimal("0.01")))


def _review_flags(*, inspector: bool = False) -> dict[str, bool]:
    return {
        "gc_review_required": True,
        "architect_review_required": True,
        "engineer_review_required": True,
        "inspector_review_required": inspector,
    }


def reconcile_gmp(
    gmp: Mapping[str, Any] | None,
    drawings_scope: Sequence[str | Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Reconcile stated GMP components against the drawing-scope checklist.

    Scope matching is deliberately literal after case/punctuation normalization.
    A match to an allowance is reported as an allowance placeholder, not as a
    fixed-price scope match.  The result is a control report, not an opinion on
    whether the documents or GMP are complete.
    """

    try:
        if not isinstance(gmp, Mapping):
            raise ValueError("gmp must be an object")
        if drawings_scope is None or isinstance(
            drawings_scope, (str, bytes, bytearray)
        ) or not isinstance(drawings_scope, Sequence):
            raise ValueError("drawings_scope must be a list")

        line_rows = _rows(gmp.get("line_items"), "gmp.line_items")
        allowance_rows = _rows(gmp.get("allowances"), "gmp.allowances")
        clarification_value = gmp.get("clarifications")
        if clarification_value is None:
            clarification_value = []
        if isinstance(clarification_value, (str, bytes, bytearray)) or not isinstance(
            clarification_value, Sequence
        ):
            raise ValueError("gmp.clarifications must be a list")

        line_items: list[dict[str, Any]] = []
        fixed_by_key: dict[str, list[dict[str, Any]]] = {}
        fixed_total = 0
        for index, row in enumerate(line_rows):
            label = _label(row, f"gmp.line_items[{index}]")
            amount, amount_key = _amount(row, f"gmp.line_items[{index}]")
            explicitly_unpriced = row.get("priced") is False or row.get("included") is False
            fixed_priced = amount is not None and amount > 0 and not explicitly_unpriced
            item = {
                "index": index,
                "scope_item": label,
                "amount_cents": amount,
                "amount_source": amount_key,
                "pricing_status": "fixed_priced" if fixed_priced else "unpriced_or_zero",
                "basis_tag": "gmp-stated",
                **_review_flags(),
            }
            line_items.append(item)
            if fixed_priced:
                fixed_total += int(amount)
                fixed_by_key.setdefault(_scope_key(label), []).append(item)

        allowances: list[dict[str, Any]] = []
        allowance_by_key: dict[str, list[dict[str, Any]]] = {}
        allowance_total = 0
        for index, row in enumerate(allowance_rows):
            label = _label(row, f"gmp.allowances[{index}]")
            amount, amount_key = _amount(row, f"gmp.allowances[{index}]")
            if amount is None:
                raise ValueError(f"gmp.allowances[{index}] needs an integer cents amount")
            allowance_total += amount
            item = {
                "index": index,
                "scope_item": label,
                "amount_cents": amount,
                "amount_source": amount_key,
                "pricing_status": "allowance_placeholder",
                "basis_tag": "gmp-stated allowance; not fixed-price evidence",
                "label": CONVENTION_UNTIL_BID,
                **_review_flags(),
            }
            allowances.append(item)
            allowance_by_key.setdefault(_scope_key(label), []).append(item)

        scope_matrix: list[dict[str, Any]] = []
        unpriced_scope: list[dict[str, Any]] = []
        seen_scope_keys: set[str] = set()
        for index, raw_scope in enumerate(drawings_scope):
            label = _label(raw_scope, f"drawings_scope[{index}]")
            key = _scope_key(label)
            duplicate = key in seen_scope_keys
            seen_scope_keys.add(key)
            fixed_matches = fixed_by_key.get(key, [])
            allowance_matches = allowance_by_key.get(key, [])
            if fixed_matches:
                status = "fixed_priced"
                reason = "literal normalized match to a positive GMP line item"
            elif allowance_matches:
                status = "allowance_only"
                reason = "matched only to an allowance; fixed pricing is not evidenced"
            else:
                status = "unpriced"
                reason = "no literal normalized match to a positive GMP line or allowance"
            matrix_row = {
                "drawing_scope_index": index,
                "scope_item": label,
                "status": status,
                "reason": reason,
                "fixed_match_count": len(fixed_matches),
                "allowance_match_count": len(allowance_matches),
                "duplicate_drawing_scope": duplicate,
                "basis_tag": "document-list reconciliation; not field-verified",
                **_review_flags(),
            }
            scope_matrix.append(matrix_row)
            if status != "fixed_priced":
                unpriced_scope.append(matrix_row.copy())

        clarification_flags: list[dict[str, Any]] = []
        for index, raw in enumerate(clarification_value):
            if isinstance(raw, Mapping):
                text = str(
                    raw.get("text")
                    or raw.get("clarification")
                    or raw.get("description")
                    or raw.get("note")
                    or ""
                ).strip()
            else:
                text = str(raw).strip()
            if not text:
                raise ValueError(f"gmp.clarifications[{index}] must not be empty")
            normalized = text.casefold()
            high_hits = [term for term in _HIGH_RISK_TERMS if term in normalized]
            medium_hits = [term for term in _MEDIUM_RISK_TERMS if term in normalized]
            if high_hits:
                severity = "high"
                hits = high_hits
            elif medium_hits:
                severity = "medium"
                hits = medium_hits
            else:
                severity = "review"
                hits = []
            clarification_flags.append(
                {
                    "index": index,
                    "clarification": text,
                    "risk_flag": bool(hits),
                    "severity": severity,
                    "matched_terms": hits,
                    "basis_tag": "keyword screen; professional interpretation required",
                    **_review_flags(),
                }
            )

        contingency_cents, contingency_source = _contingency(gmp.get("contingency"))
        contingency_basis = fixed_total + allowance_total
        if contingency_basis:
            bps = int(
                (Decimal(contingency_cents) * Decimal(10_000) / Decimal(contingency_basis)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            contingency_pct: float | None = _percent_from_bps(bps)
            if bps < 500:
                adequacy = "below_convention"
            elif bps <= 1_000:
                adequacy = "within_convention"
            else:
                adequacy = "above_convention"
        else:
            bps = None
            contingency_pct = None
            adequacy = "indeterminate_no_cost_basis"

        stated_total = gmp.get("total_cents")
        if stated_total is not None:
            stated_total = _cents(stated_total, "gmp.total_cents")
        component_total = fixed_total + allowance_total + contingency_cents
        possible_overlap = sorted(set(fixed_by_key).intersection(allowance_by_key))

        return {
            "report_type": "gmp_reconciliation",
            "line_items": line_items,
            "allowances": allowances,
            "scope_matrix": scope_matrix,
            "unpriced_scope": unpriced_scope,
            "unpriced_scope_items": [item["scope_item"] for item in unpriced_scope],
            "allowance_exposure_total_cents": allowance_total,
            "allowance_exposure_basis_tag": "gmp-stated allowances; convention until bid",
            "clarification_risk_flags": clarification_flags,
            "contingency_adequacy": adequacy,
            "contingency_pct": contingency_pct,
            "contingency_analysis": {
                "contingency_cents": contingency_cents,
                "amount_source": contingency_source,
                "cost_basis_cents": contingency_basis,
                "contingency_pct": contingency_pct,
                "contingency_basis_points": bps,
                "adequacy": adequacy,
                "convention": GMP_CONTINGENCY_CONVENTION.copy(),
                "basis_tag": CONVENTION_UNTIL_BID,
                **_review_flags(),
            },
            "totals": {
                "fixed_price_line_items_cents": fixed_total,
                "allowances_cents": allowance_total,
                "contingency_cents": contingency_cents,
                "component_sum_cents": component_total,
                "stated_gmp_total_cents": stated_total,
                "stated_total_variance_cents": (
                    stated_total - component_total if stated_total is not None else None
                ),
                "basis_tag": "arithmetic sum of caller-stated components",
            },
            "possible_line_allowance_overlap_keys": possible_overlap,
            "double_count_warning": bool(possible_overlap),
            "review_flags": {
                "gc_review_required": True,
                "architect_review_required": True,
                "engineer_review_required": True,
                "inspector_review_required": False,
                "inspector_note": (
                    "Document reconciliation is not field verification; inspector review "
                    "becomes required for installed-work and code-compliance assertions."
                ),
            },
            "honesty": (
                "Allowances and contingency adequacy are convention until bid. Scope "
                "matching is document-list reconciliation, not design completeness, "
                "field verification, or professional certification."
            ),
        }
    except Exception as exc:
        return {"error": f"reconcile_gmp: {exc}"}


__all__ = [
    "CONVENTION_UNTIL_BID",
    "GMP_CONTINGENCY_CONVENTION",
    "reconcile_gmp",
]
