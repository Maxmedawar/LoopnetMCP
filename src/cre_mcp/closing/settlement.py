"""Penny-exact, auditable settlement-statement reconciliation.

Amounts are integer cents.  Prorations round half-up only after the complete
fraction is calculated, and every result carries the arithmetic needed to
check it by hand.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


_CATEGORY_ALIASES = {
    "rent": "rent",
    "rents": "rent",
    "rent_roll": "rent",
    "deposit": "deposit",
    "deposits": "deposit",
    "security_deposit": "deposit",
    "security_deposits": "deposit",
    "tax": "tax",
    "taxes": "tax",
    "tax_bill": "tax",
    "tax_bills": "tax",
    "cam": "cam",
    "cam_balance": "cam",
    "cam_balances": "cam",
    "credit": "credit",
    "credits": "credit",
}


def _cents(value: Any, name: str, *, nonnegative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _date(value: Any, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD)") from exc
    raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD)")


def _convention(value: Any) -> str:
    normalized = str(value).strip().lower().replace("-", "_")
    aliases = {
        "365": "365",
        "actual_365": "365",
        "act_365": "365",
        "360": "360",
        "30_360": "360",
        "actual": "actual_days",
        "actual_day": "actual_days",
        "actual_days": "actual_days",
    }
    if normalized not in aliases:
        raise ValueError("convention must be 365, 360, or actual_days")
    return aliases[normalized]


def _rows(value: Any, name: str) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        # A single money row is accepted; otherwise a keyed mapping becomes rows.
        if any(str(key).endswith("_cents") for key in value) or "amount_cents" in value:
            return [value]
        return [dict(row, name=str(key)) if isinstance(row, Mapping) else {"name": str(key), "amount_cents": row}
                for key, row in value.items()]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = []
        for index, row in enumerate(value):
            if not isinstance(row, Mapping):
                raise ValueError(f"{name}[{index}] must be an object")
            result.append(row)
        return result
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a list, object, or integer cents")
    return [{"amount_cents": value}]


def _category(value: Any) -> str | None:
    if value is None:
        return None
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    return _CATEGORY_ALIASES.get(key, key or None)


def _statement_category(row: Mapping[str, Any]) -> str | None:
    explicit = _category(row.get("category", row.get("type", row.get("kind"))))
    if explicit is not None:
        return explicit
    text = " ".join(str(row.get(key, "")) for key in ("description", "name", "label")).casefold()
    for token, category in (
        ("security deposit", "deposit"), ("deposit", "deposit"),
        ("tax", "tax"), ("cam", "cam"), ("common area", "cam"),
        ("rent", "rent"), ("credit", "credit"),
    ):
        if token in text:
            return category
    return None


def _label(row: Mapping[str, Any], category: str, index: int) -> str:
    for key in ("description", "name", "tenant", "holder", "label", "id", "line_id"):
        if row.get(key) not in (None, ""):
            return str(row[key]).strip()
    return f"{category} {index + 1}"


def _line_id(row: Mapping[str, Any], category: str, index: int) -> str:
    value = row.get("line_id", row.get("id", row.get("statement_line_id")))
    return str(value).strip() if value not in (None, "") else f"expected:{category}:{index + 1}"


def _period(row: Mapping[str, Any], category: str, closing: date) -> tuple[date, date]:
    if row.get("period_start") is not None or row.get("period_end") is not None:
        if row.get("period_start") is None or row.get("period_end") is None:
            raise ValueError(f"{category} period_start and period_end must be supplied together")
        start = _date(row["period_start"], f"{category}.period_start")
        end = _date(row["period_end"], f"{category}.period_end")
    elif category in {"rent", "cam"}:
        start = closing.replace(day=1)
        end = closing.replace(day=calendar.monthrange(closing.year, closing.month)[1])
    else:
        start = date(closing.year, 1, 1)
        end = date(closing.year, 12, 31)
    if end < start:
        raise ValueError(f"{category}.period_end cannot precede period_start")
    return start, end


def _party_days(start: date, end: date, closing: date, closing_day_owner: str) -> tuple[int, int]:
    total = (end - start).days + 1
    seller_end = closing if closing_day_owner == "seller" else closing - timedelta(days=1)
    if seller_end < start:
        seller_days = 0
    elif seller_end >= end:
        seller_days = total
    else:
        seller_days = (seller_end - start).days + 1
    return seller_days, total - seller_days


def _amount(row: Mapping[str, Any], category: str) -> tuple[int, str]:
    keys = {
        "rent": ("monthly_rent_cents", "rent_cents", "annual_rent_cents", "amount_cents"),
        "tax": ("annual_tax_cents", "tax_bill_cents", "bill_amount_cents", "amount_cents"),
        "cam": ("monthly_cam_cents", "annual_cam_cents", "cam_balance_cents", "amount_cents"),
        "deposit": ("deposit_cents", "security_deposit_cents", "amount_cents"),
        "credit": ("credit_cents", "amount_cents"),
    }[category]
    for key in keys:
        if key in row and row[key] is not None:
            return _cents(row[key], f"{category}.{key}"), key
    raise ValueError(f"{category} row is missing an integer cents amount")


def _round_fraction(numerator: int, denominator: int) -> int:
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _expected_line(
    row: Mapping[str, Any],
    category: str,
    index: int,
    closing: date,
    convention: str,
    closing_day_owner: str,
) -> dict[str, Any]:
    raw_amount, amount_key = _amount(row, category)
    label = _label(row, category, index)
    line_id = _line_id(row, category, index)
    if category in {"deposit", "credit"} or row.get("prorate") is False:
        return {
            "line_id": line_id,
            "category": category,
            "description": label,
            "expected_amount_cents": raw_amount,
            "basis_amount_cents": raw_amount,
            "owned_days": None,
            "denominator_days": None,
            "per_diem_exact": None,
            "arithmetic": f"{raw_amount} cents (not prorated) = {raw_amount} cents",
        }

    start, end = _period(row, category, closing)
    seller_days, buyer_days = _party_days(start, end, closing, closing_day_owner)
    default_party = "buyer" if category in {"rent", "cam"} else "seller"
    allocated_to = str(row.get("allocate_to", row.get("proration_party", default_party))).strip().lower()
    if allocated_to not in {"buyer", "seller"}:
        raise ValueError(f"{category}.allocate_to must be buyer or seller")
    owned_days = buyer_days if allocated_to == "buyer" else seller_days

    if convention == "actual_days":
        denominator = (end - start).days + 1
        basis_amount = raw_amount
    else:
        denominator = int(convention)
        # Monthly inputs are annualized for 365/360 day-count calculations.
        monthly = amount_key.startswith("monthly_") or (
            category in {"rent", "cam"} and amount_key in {"rent_cents", "amount_cents"}
            and start.day == 1 and end.month == start.month
        )
        basis_amount = raw_amount * 12 if monthly else raw_amount
    numerator = basis_amount * owned_days
    expected = _round_fraction(numerator, denominator)
    statement_sign = row.get("statement_sign", 1)
    if isinstance(statement_sign, bool) or statement_sign not in {-1, 1}:
        raise ValueError(f"{category}.statement_sign must be 1 or -1")
    expected *= statement_sign
    return {
        "line_id": line_id,
        "category": category,
        "description": label,
        "allocated_to": allocated_to,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "seller_days": seller_days,
        "buyer_days": buyer_days,
        "owned_days": owned_days,
        "denominator_days": denominator,
        "basis_amount_cents": basis_amount,
        "per_diem_exact": f"{basis_amount}/{denominator}",
        "expected_amount_cents": expected,
        "arithmetic": (
            f"round_half_up({basis_amount} cents x {owned_days} {allocated_to}-owned days "
            f"/ {denominator} day denominator) x {statement_sign} = {expected} cents"
        ),
    }


def _statement_lines(statement: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = statement.get("line_items", statement.get("items"))
    if raw is None:
        raise ValueError("statement.line_items is required")
    rows = _rows(raw, "statement.line_items")
    result = []
    for index, row in enumerate(rows):
        amount = _cents(row.get("amount_cents"), f"statement.line_items[{index}].amount_cents")
        category = _statement_category(row)
        result.append({
            "line_id": str(row.get("line_id", row.get("id", f"statement:{index + 1}"))),
            "category": category,
            "description": _label(row, category or "line", index),
            "amount_cents": amount,
        })
    return result


def _matches(expected: dict[str, Any], statements: list[dict[str, Any]], used: set[int]) -> int | None:
    wanted_id = expected["line_id"]
    exact_id = [i for i, row in enumerate(statements) if i not in used and row["line_id"] == wanted_id]
    if exact_id:
        return exact_id[0]
    description = expected["description"].casefold()
    exact_description = [i for i, row in enumerate(statements) if i not in used
                         and row["category"] == expected["category"]
                         and row["description"].casefold() == description]
    if exact_description:
        return exact_description[0]
    same_category = [i for i, row in enumerate(statements) if i not in used
                     and row["category"] == expected["category"]]
    return same_category[0] if same_category else None


def reconcile_settlement(
    statement: Mapping[str, Any],
    expected: Mapping[str, Any],
    convention: str | int = "actual_days",
    closing_day_owner: str = "buyer",
) -> dict[str, Any]:
    """Recompute and compare settlement lines, returning errors as data."""

    try:
        if not isinstance(statement, Mapping) or not isinstance(expected, Mapping):
            raise ValueError("statement and expected must be objects")
        normalized_convention = _convention(convention)
        owner = str(closing_day_owner).strip().lower()
        if owner not in {"buyer", "seller"}:
            raise ValueError("closing_day_owner must be buyer or seller")
        closing_raw = statement.get("closing_date", expected.get("closing_date"))
        if closing_raw is None:
            raise ValueError("closing_date is required in statement or expected")
        closing = _date(closing_raw, "closing_date")

        categories = (
            ("rent", expected.get("rent_roll")),
            ("deposit", expected.get("deposits_held")),
            ("tax", expected.get("tax_bills")),
            ("cam", expected.get("cam_balances", expected.get("CAM_balances"))),
            ("credit", expected.get("credits")),
        )
        expected_lines = []
        for category, raw_rows in categories:
            for index, row in enumerate(_rows(raw_rows, category)):
                expected_lines.append(
                    _expected_line(row, category, index, closing, normalized_convention, owner)
                )
        statements = _statement_lines(statement)
        used: set[int] = set()
        discrepancies = []
        for line in expected_lines:
            match_index = _matches(line, statements, used)
            statement_amount = statements[match_index]["amount_cents"] if match_index is not None else None
            if match_index is not None:
                used.add(match_index)
            delta = None if statement_amount is None else statement_amount - line["expected_amount_cents"]
            line["statement_amount_cents"] = statement_amount
            line["delta_cents"] = delta
            line["matched_statement_line_id"] = statements[match_index]["line_id"] if match_index is not None else None
            if delta is None or delta != 0:
                discrepancies.append({
                    "line_id": line["line_id"],
                    "category": line["category"],
                    "description": line["description"],
                    "expected_amount_cents": line["expected_amount_cents"],
                    "statement_amount_cents": statement_amount,
                    "delta_cents": delta,
                    "reason": "statement line missing" if delta is None else "statement amount differs from recomputation",
                    "arithmetic": line["arithmetic"],
                })
        for index, row in enumerate(statements):
            if index not in used:
                discrepancies.append({
                    "line_id": row["line_id"], "category": row["category"],
                    "description": row["description"], "expected_amount_cents": None,
                    "statement_amount_cents": row["amount_cents"], "delta_cents": None,
                    "reason": "statement line has no expected counterpart", "arithmetic": None,
                })

        expected_deposits = sum(line["expected_amount_cents"] for line in expected_lines if line["category"] == "deposit")
        statement_deposits = sum(row["amount_cents"] for row in statements if row["category"] == "deposit")
        deposits_supplied = "deposits_held" in expected
        deposit_delta = statement_deposits - expected_deposits if deposits_supplied else None
        expected_total = sum(line["expected_amount_cents"] for line in expected_lines)
        statement_total = sum(row["amount_cents"] for row in statements)
        return {
            "ok": not discrepancies,
            "status": "reconciled" if not discrepancies else "discrepancies_found",
            "closing_date": closing.isoformat(),
            "convention": normalized_convention,
            "closing_day_owner": owner,
            "rounding": "round half-up to the nearest cent after calculating the full fraction",
            "delta_direction": "statement_amount_cents - expected_amount_cents",
            "expected_lines": expected_lines,
            "statement_lines": statements,
            "discrepancies": discrepancies,
            "deposit_transfer_check": {
                "expected_deposits_cents": expected_deposits if deposits_supplied else None,
                "statement_deposits_cents": statement_deposits,
                "delta_cents": deposit_delta,
                "transferred_in_full": deposit_delta == 0 if deposits_supplied else None,
                "reason": None if deposits_supplied else "deposits_held was not supplied; transfer cannot be verified",
            },
            "totals": {
                "expected_cents": expected_total,
                "statement_cents": statement_total,
                "delta_cents": statement_total - expected_total,
                "arithmetic": f"{statement_total} statement cents - {expected_total} expected cents = {statement_total - expected_total} cents",
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


__all__ = ["reconcile_settlement"]
