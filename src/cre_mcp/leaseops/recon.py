"""Read-only reconciliation of cited lease economics against property books.

The lease is the contractual side of the comparison.  Rent is always calculated
through :func:`cre_mcp.leases.schedule.rent_schedule`; posted book lines are
never treated as a substitute for the lease.  The current ``BookStore`` schema
does not contain commencement or security-deposit holds, so those fields remain
honestly unavailable unless the caller supplies a books snapshot containing
them.
"""

from __future__ import annotations

import calendar
import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from cre_mcp.books.billing import normalize_period_range
from cre_mcp.books.store import BookStore
from cre_mcp.leases import LeaseAbstract, abstract_lease, read_lease, rent_schedule
from cre_mcp.leases.models import CitedClaim, LeaseDates, RentPeriod, Security


_ABSTRACT_KEYS = frozenset(
    {"dates", "commencement", "rent_schedule", "security", "deposit_cents", "source_path"}
)
_CLAIM_KEYS = frozenset({"value", "quote", "locator", "confidence", "status", "source"})
_RENT_ROW_KEYS = frozenset(
    {
        "period",
        "amount_cents",
        "monthly_cents",
        "annual_cents",
        "start",
        "end",
        "monthly",
        "annual",
        "label",
        "quote",
        "locator",
        "citation",
    }
)
_BOOKS_KEYS = frozenset(
    {
        "tenancy_id",
        "tenancy",
        "commencement",
        "commencement_date",
        "commencement_citation",
        "deposit_cents",
        "security_deposit_cents",
        "held_deposit_cents",
        "deposit_citation",
        "charges",
        "holds",
    }
)
_TENANCY_KEYS = frozenset(
    {"tenancy_id", "deal_id", "unit", "tenant_name", "lease_ref", "active", "commencement", "commencement_date"}
)
_CHARGE_KEYS = frozenset(
    {"charge_id", "tenancy_id", "period", "kind", "amount_cents", "source", "source_detail", "created_at"}
)
_HOLD_KEYS = frozenset(
    {"hold_id", "tenancy_id", "kind", "type", "amount_cents", "status", "source", "source_detail", "doc_ref"}
)
_PERIOD_RANGE_KEYS = frozenset({"from_period", "start", "to_period", "end"})


def _unknown(mapping: Mapping[str, Any], allowed: frozenset[str], *, path: str) -> None:
    extras = sorted(str(key) for key in mapping if key not in allowed)
    if extras:
        raise ValueError(f"unrecognized inputs at {path}: {', '.join(extras)}")


def _text(value: Any, *, name: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text" + (" or null" if nullable else ""))
    normalized = value.strip()
    if not normalized:
        if nullable:
            return None
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _cents(value: Any, *, name: str, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer number of cents")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _dollars_to_cents(value: Any, *, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    try:
        dollars = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TypeError(f"{name} must be numeric") from exc
    if not dollars.is_finite() or dollars < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return int((dollars * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _claim(value: Any, *, path: str) -> CitedClaim:
    if isinstance(value, CitedClaim):
        return value
    if isinstance(value, Mapping):
        _unknown(value, _CLAIM_KEYS, path=path)
        status = str(value.get("status") or ("missing" if value.get("value") is None else "stated"))
        if status not in {"stated", "inferred", "missing"}:
            raise ValueError(f"{path}.status must be stated, inferred, or missing")
        raw = value.get("value")
        if status == "missing":
            return CitedClaim.missing(source=str(value.get("source") or "caller"))
        constructor = CitedClaim.inferred if status == "inferred" else CitedClaim.stated
        return constructor(
            raw,
            quote=str(value.get("quote") or "")[:200],
            locator=str(value.get("locator") or ""),
            confidence=float(value.get("confidence", 1.0)),
            source=str(value.get("source") or "caller"),
        )
    if value is None:
        return CitedClaim.missing(source="caller")
    return CitedClaim.stated(value, quote="", locator="", confidence=0.5, source="caller")


def _normalize_range(
    value: str | Sequence[str] | Mapping[str, str],
) -> tuple[str, str]:
    if isinstance(value, Mapping):
        _unknown(value, _PERIOD_RANGE_KEYS, path="period_range")
        if (
            value.get("from_period") is not None
            and value.get("start") is not None
            and value["from_period"] != value["start"]
        ):
            raise ValueError("period_range contains conflicting from_period and start values")
        if (
            value.get("to_period") is not None
            and value.get("end") is not None
            and value["to_period"] != value["end"]
        ):
            raise ValueError("period_range contains conflicting to_period and end values")
    return normalize_period_range(value)


def _citation(claim: CitedClaim, source_path: str | None) -> dict[str, Any]:
    return {
        "source_path": source_path,
        "quote": claim.quote or None,
        "locator": claim.locator or None,
        "claim_status": claim.status,
        "confidence": claim.confidence,
        "source_layer": claim.source,
    }


def _claim_with_row_evidence(value: Any, row: Mapping[str, Any], *, path: str) -> CitedClaim:
    if isinstance(value, Mapping) or isinstance(value, CitedClaim):
        return _claim(value, path=path)
    if value is None:
        return CitedClaim.missing(source="caller")
    citation = row.get("citation")
    if citation is not None and not isinstance(citation, Mapping):
        raise TypeError(f"{path}.citation must be a mapping or null")
    citation = citation or {}
    return CitedClaim.stated(
        value,
        quote=str(row.get("quote") or citation.get("quote") or "")[:200],
        locator=str(row.get("locator") or citation.get("locator") or ""),
        confidence=1.0,
        source="caller",
    )


def _hydrate_abstract(value: LeaseAbstract | Mapping[str, Any]) -> LeaseAbstract:
    if isinstance(value, LeaseAbstract):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("lease_abstract must be a LeaseAbstract or mapping")
    _unknown(value, _ABSTRACT_KEYS, path="lease_abstract")

    dates = value.get("dates")
    if dates is not None and not isinstance(dates, Mapping):
        raise TypeError("lease_abstract.dates must be a mapping or null")
    if dates:
        _unknown(dates, frozenset({"commencement"}), path="lease_abstract.dates")
    commencement = value.get("commencement", (dates or {}).get("commencement"))

    security = value.get("security")
    if security is not None and not isinstance(security, Mapping):
        raise TypeError("lease_abstract.security must be a mapping or null")
    if security:
        _unknown(security, frozenset({"deposit"}), path="lease_abstract.security")
    deposit = (security or {}).get("deposit")
    if "deposit_cents" in value:
        if deposit is not None:
            raise ValueError(
                "lease_abstract contains both security.deposit and deposit_cents; provide one money shape"
            )
        deposit_cents = _cents(value.get("deposit_cents"), name="lease_abstract.deposit_cents", nullable=True)
        deposit = (
            None
            if deposit_cents is None
            else CitedClaim.stated(
                float(Decimal(deposit_cents) / Decimal(100)),
                quote="",
                locator="",
                confidence=0.5,
                source="caller",
            )
        )

    raw_schedule = value.get("rent_schedule") or []
    if not isinstance(raw_schedule, Sequence) or isinstance(raw_schedule, (str, bytes, bytearray)):
        raise TypeError("lease_abstract.rent_schedule must be a sequence")
    periods: list[RentPeriod] = []
    for index, raw in enumerate(raw_schedule):
        if not isinstance(raw, Mapping):
            raise TypeError(f"lease_abstract.rent_schedule[{index}] must be a mapping")
        _unknown(raw, _RENT_ROW_KEYS, path=f"lease_abstract.rent_schedule[{index}]")
        start = raw.get("start")
        end = raw.get("end")
        if raw.get("period") is not None:
            period = str(raw["period"])
            start_period, end_period = _normalize_range(period)
            start = f"{start_period}-01"
            parsed = datetime.strptime(end_period, "%Y-%m").date()
            end = date(parsed.year, parsed.month, calendar.monthrange(parsed.year, parsed.month)[1]).isoformat()

        monthly = raw.get("monthly")
        annual = raw.get("annual")
        if "amount_cents" in raw or "monthly_cents" in raw:
            cents = _cents(
                raw.get("amount_cents", raw.get("monthly_cents")),
                name=f"lease_abstract.rent_schedule[{index}].monthly_cents",
            )
            monthly = float(Decimal(cents) / Decimal(100))
        if "annual_cents" in raw:
            cents = _cents(raw.get("annual_cents"), name=f"lease_abstract.rent_schedule[{index}].annual_cents")
            annual = float(Decimal(cents) / Decimal(100))
        periods.append(
            RentPeriod(
                start=_claim_with_row_evidence(start, raw, path=f"lease_abstract.rent_schedule[{index}].start"),
                end=_claim_with_row_evidence(end, raw, path=f"lease_abstract.rent_schedule[{index}].end"),
                monthly=_claim_with_row_evidence(monthly, raw, path=f"lease_abstract.rent_schedule[{index}].monthly"),
                annual=_claim_with_row_evidence(annual, raw, path=f"lease_abstract.rent_schedule[{index}].annual"),
                label=_claim_with_row_evidence(raw.get("label"), raw, path=f"lease_abstract.rent_schedule[{index}].label"),
            )
        )

    return LeaseAbstract(
        dates=LeaseDates(commencement=_claim(commencement, path="lease_abstract.commencement")),
        rent_schedule=periods,
        security=Security(deposit=_claim(deposit, path="lease_abstract.security.deposit")),
        source_path=_text(value.get("source_path"), name="lease_abstract.source_path", nullable=True),
    )


def _date_bounds(start: str, end: str) -> tuple[date, date]:
    first = datetime.strptime(start, "%Y-%m").date()
    last = datetime.strptime(end, "%Y-%m").date()
    return first, date(last.year, last.month, calendar.monthrange(last.year, last.month)[1])


def _normalized_date(value: Any, *, name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value, name=name)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _source_detail(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _read_book_rows(
    tenancy_id: str,
    *,
    start: str | None = None,
    end: str | None = None,
    db_path: str | Path | None,
    store: BookStore | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read existing book tables without invoking their schema-initializing connection."""

    if store is not None:
        tenancy = store.get_tenancy(tenancy_id)
        charges = (
            store.list_charges(tenancy_id=tenancy_id, from_period=start, to_period=end)
            if start is not None and end is not None
            else []
        )
        return tenancy, charges

    path = BookStore(db_path).db_path.resolve()
    if not path.is_file():
        raise KeyError(f"unknown tenancy {tenancy_id!r}; books database does not exist")
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        tenancy_row = connection.execute(
            "SELECT * FROM bk_tenancies WHERE tenancy_id=?", (tenancy_id,)
        ).fetchone()
        if tenancy_row is None:
            raise KeyError(f"unknown tenancy {tenancy_id!r}")
        tenancy = dict(tenancy_row)
        tenancy["active"] = bool(tenancy["active"])
        charges: list[dict[str, Any]] = []
        if start is not None and end is not None:
            rows = connection.execute(
                """
                SELECT * FROM bk_charges
                WHERE tenancy_id=? AND period>=? AND period<=?
                ORDER BY period, tenancy_id, kind, charge_id
                """,
                (tenancy_id, start, end),
            ).fetchall()
            charges = [dict(row) for row in rows]
        return tenancy, charges
    except sqlite3.OperationalError as exc:
        raise ValueError("books database is missing the required tenancy/charge tables") from exc
    finally:
        connection.close()


def _books_snapshot(
    tenancy_id: str | None,
    books_data: Mapping[str, Any] | None,
    *,
    start: str,
    end: str,
    db_path: str | Path | None,
    store: BookStore | None,
) -> dict[str, Any]:
    if books_data is None:
        if tenancy_id is None:
            raise ValueError("books_data is required when tenancy_id is null")
        tenancy, charges = _read_book_rows(
            tenancy_id,
            start=start,
            end=end,
            db_path=db_path,
            store=store,
        )
        return {
            "tenancy_id": tenancy_id,
            "tenancy": tenancy,
            "commencement": None,
            "commencement_citation": None,
            "deposit_cents": None,
            "deposit_citation": None,
            "charges": charges,
            "holds": [],
            "limitations": [
                "bk_tenancies has no commencement column.",
                "The current books schema has no deposit-hold table.",
            ],
        }
    if not isinstance(books_data, Mapping):
        raise TypeError("books_data must be a mapping or null")
    _unknown(books_data, _BOOKS_KEYS, path="books_data")

    tenancy = books_data.get("tenancy") or {}
    if not isinstance(tenancy, Mapping):
        raise TypeError("books_data.tenancy must be a mapping or null")
    _unknown(tenancy, _TENANCY_KEYS, path="books_data.tenancy")
    identity_values = {
        str(value).strip()
        for value in (tenancy_id, books_data.get("tenancy_id"), tenancy.get("tenancy_id"))
        if value is not None and str(value).strip()
    }
    if len(identity_values) > 1:
        raise ValueError("books_data contains conflicting tenancy_id values")
    snapshot_id = next(iter(identity_values), None)

    commencement_values = [
        value
        for value in (
            books_data.get("commencement"),
            books_data.get("commencement_date"),
            tenancy.get("commencement"),
            tenancy.get("commencement_date"),
        )
        if value is not None
    ]
    normalized_commencements = {
        _normalized_date(value, name="books commencement") for value in commencement_values
    }
    if len(normalized_commencements) > 1:
        raise ValueError("books_data contains conflicting commencement values")

    direct_deposits = [
        books_data[key]
        for key in ("deposit_cents", "security_deposit_cents", "held_deposit_cents")
        if key in books_data and books_data[key] is not None
    ]
    normalized_deposits = {
        _cents(value, name="books deposit_cents") for value in direct_deposits
    }
    if len(normalized_deposits) > 1:
        raise ValueError("books_data contains conflicting deposit values")

    raw_charges = books_data.get("charges") or []
    if not isinstance(raw_charges, Sequence) or isinstance(raw_charges, (str, bytes, bytearray)):
        raise TypeError("books_data.charges must be a sequence")
    charges: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_charges):
        if not isinstance(raw, Mapping):
            raise TypeError(f"books_data.charges[{index}] must be a mapping")
        _unknown(raw, _CHARGE_KEYS, path=f"books_data.charges[{index}]")
        if "period" not in raw or "kind" not in raw or "amount_cents" not in raw:
            raise ValueError(f"books_data.charges[{index}] needs period, kind, and amount_cents")
        row_tenancy_id = raw.get("tenancy_id")
        if (
            snapshot_id is not None
            and row_tenancy_id is not None
            and str(row_tenancy_id).strip() != snapshot_id
        ):
            raise ValueError(
                f"books_data.charges[{index}].tenancy_id does not match the snapshot tenancy_id"
            )
        period, _ = _normalize_range(str(raw["period"]))
        amount = _cents(raw["amount_cents"], name=f"books_data.charges[{index}].amount_cents")
        charges.append({**dict(raw), "period": period, "kind": str(raw["kind"]).strip().casefold(), "amount_cents": amount})

    raw_holds = books_data.get("holds") or []
    if not isinstance(raw_holds, Sequence) or isinstance(raw_holds, (str, bytes, bytearray)):
        raise TypeError("books_data.holds must be a sequence")
    holds: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_holds):
        if not isinstance(raw, Mapping):
            raise TypeError(f"books_data.holds[{index}] must be a mapping")
        _unknown(raw, _HOLD_KEYS, path=f"books_data.holds[{index}]")
        if "amount_cents" not in raw:
            raise ValueError(f"books_data.holds[{index}] needs amount_cents")
        row_tenancy_id = raw.get("tenancy_id")
        if (
            snapshot_id is not None
            and row_tenancy_id is not None
            and str(row_tenancy_id).strip() != snapshot_id
        ):
            raise ValueError(
                f"books_data.holds[{index}].tenancy_id does not match the snapshot tenancy_id"
            )
        holds.append({**dict(raw), "amount_cents": _cents(raw["amount_cents"], name=f"books_data.holds[{index}].amount_cents")})

    deposit_cents = next(iter(normalized_deposits), None)
    deposit_source: Any = books_data.get("deposit_citation")
    if deposit_cents is None and holds:
        eligible = []
        for hold in holds:
            kind = str(hold.get("kind", hold.get("type", "deposit"))).strip().casefold()
            status = str(hold.get("status") or "held").strip().casefold()
            if kind in {"deposit", "security_deposit", "security deposit"} and status not in {
                "released", "returned", "refunded", "cancelled", "canceled"
            }:
                eligible.append(hold)
        if eligible:
            deposit_cents = sum(int(item["amount_cents"]) for item in eligible)
            deposit_source = [
                {
                    "hold_id": item.get("hold_id"),
                    "status": item.get("status"),
                    "source": item.get("source"),
                    "source_detail": _source_detail(item.get("source_detail")),
                    "doc_ref": item.get("doc_ref"),
                }
                for item in eligible
            ]

    return {
        "tenancy_id": str(snapshot_id) if snapshot_id is not None else tenancy_id,
        "tenancy": dict(tenancy),
        "commencement": next(iter(normalized_commencements), None),
        "commencement_citation": books_data.get("commencement_citation"),
        "deposit_cents": deposit_cents,
        "deposit_citation": deposit_source,
        "charges": charges,
        "holds": holds,
        "limitations": [],
    }


def _comparison_status(lease_value: Any, books_value: Any) -> str:
    if lease_value is None or books_value is None:
        return "not_comparable"
    return "match" if lease_value == books_value else "mismatch"


def _load_abstract_for_tenancy(
    tenancy_id: str,
    *,
    db_path: str | Path | None,
    store: BookStore | None,
) -> LeaseAbstract:
    tenancy, _ = _read_book_rows(
        tenancy_id,
        db_path=db_path,
        store=store,
    )
    lease_ref = tenancy.get("lease_ref")
    if not lease_ref:
        raise ValueError("tenancy has no lease_ref; lease facts cannot be reconstructed")
    document = read_lease(Path(str(lease_ref)).expanduser())
    abstract = abstract_lease(document.text)
    abstract.source_path = document.source_path
    abstract.deal_id = str(tenancy.get("deal_id") or "") or None
    return abstract


def lease_vs_books(
    tenancy_id: str | None,
    period_range: str | Sequence[str] | Mapping[str, str],
    lease_abstract: LeaseAbstract | Mapping[str, Any] | None = None,
    books_data: Mapping[str, Any] | None = None,
    *,
    db_path: str | Path | None = None,
    store: BookStore | None = None,
) -> dict[str, Any]:
    """Compare commencement, contractual rent, and deposit with read-only books.

    ``tenancy_id`` may be null when both ``lease_abstract`` and ``books_data``
    are supplied.  Supplied mappings are strict: unknown fields are rejected so
    misspelled financial inputs cannot disappear silently.
    """

    normalized_id = _text(tenancy_id, name="tenancy_id", nullable=True)
    start, end = _normalize_range(period_range)
    abstract = (
        _hydrate_abstract(lease_abstract)
        if lease_abstract is not None
        else _load_abstract_for_tenancy(normalized_id, db_path=db_path, store=store)
        if normalized_id is not None
        else None
    )
    if abstract is None:
        raise ValueError("provide tenancy_id or lease_abstract")
    snapshot = _books_snapshot(
        normalized_id,
        books_data,
        start=start,
        end=end,
        db_path=db_path,
        store=store,
    )

    commencement_claim = abstract.dates.commencement
    lease_commencement = (
        _normalized_date(commencement_claim.value, name="lease commencement")
        if commencement_claim.status != "missing"
        else None
    )
    commencement = {
        "field": "commencement",
        "status": _comparison_status(lease_commencement, snapshot["commencement"]),
        "lease": {
            "value": lease_commencement,
            "citation": _citation(commencement_claim, abstract.source_path),
        },
        "books": {
            "value": snapshot["commencement"],
            "citation": snapshot["commencement_citation"],
        },
    }

    range_start, range_end = _date_bounds(start, end)
    scheduled = rent_schedule(abstract, range_start, range_end)
    rent_charges: dict[str, list[dict[str, Any]]] = {}
    for charge in snapshot["charges"]:
        if str(charge.get("kind") or "").casefold() == "rent" and start <= str(charge.get("period")) <= end:
            rent_charges.setdefault(str(charge["period"]), []).append(charge)

    periods: list[dict[str, Any]] = []
    for row in scheduled:
        period = str(row["month"])
        charges = rent_charges.get(period, [])
        billed_cents = sum(int(charge["amount_cents"]) for charge in charges)
        expected_cents = (
            _dollars_to_cents(row["total_cash_rent"], name="scheduled rent")
            if row.get("status") == "calculated" and row.get("total_cash_rent") is not None
            else None
        )
        status = _comparison_status(expected_cents, billed_cents)
        periods.append(
            {
                "period": period,
                "status": status,
                "lease": {
                    "amount_cents": expected_cents,
                    "schedule_status": row.get("status"),
                    "missing_inputs": list(row.get("missing_inputs", [])),
                    "citation": {
                        "source_path": abstract.source_path,
                        "lease_quotes": list(row.get("source_quotes", [])),
                        "calculator": "cre_mcp.leases.schedule.rent_schedule",
                    },
                },
                "books": {
                    "amount_cents": billed_cents,
                    "charge_ids": [charge.get("charge_id") for charge in charges],
                    "citations": [
                        {
                            "charge_id": charge.get("charge_id"),
                            "source": charge.get("source"),
                            "source_detail": _source_detail(charge.get("source_detail")),
                        }
                        for charge in charges
                    ],
                },
                "delta_cents": None if expected_cents is None else billed_cents - expected_cents,
            }
        )
    comparable_periods = [item for item in periods if item["status"] != "not_comparable"]
    rent_status = (
        "mismatch"
        if any(item["status"] == "mismatch" for item in comparable_periods)
        else "match"
        if comparable_periods
        else "not_comparable"
    )
    rent = {
        "field": "rent",
        "status": rent_status,
        "lease": {
            "total_cents": (
                sum(int(item["lease"]["amount_cents"]) for item in comparable_periods)
                if comparable_periods
                else None
            ),
            "calculator": "cre_mcp.leases.schedule.rent_schedule",
            "source_path": abstract.source_path,
        },
        "books": {
            "total_billed_cents": sum(int(item["books"]["amount_cents"]) for item in periods),
            "source": "bk_charges read-only" if books_data is None else "caller-supplied books snapshot",
        },
        "periods": periods,
    }

    deposit_claim = abstract.security.deposit
    lease_deposit = (
        _dollars_to_cents(deposit_claim.value, name="lease deposit")
        if deposit_claim.status != "missing"
        else None
    )
    deposit = {
        "field": "deposit",
        "status": _comparison_status(lease_deposit, snapshot["deposit_cents"]),
        "lease": {
            "amount_cents": lease_deposit,
            "citation": _citation(deposit_claim, abstract.source_path),
        },
        "books": {
            "held_amount_cents": snapshot["deposit_cents"],
            "citation": snapshot["deposit_citation"],
        },
    }

    comparisons = [commencement, rent, deposit]
    return {
        "tenancy_id": snapshot["tenancy_id"] or normalized_id,
        "from_period": start,
        "to_period": end,
        "fields": {item["field"]: item for item in comparisons},
        "comparisons": comparisons,
        "mismatches": [item["field"] for item in comparisons if item["status"] == "mismatch"],
        "unavailable": [item["field"] for item in comparisons if item["status"] == "not_comparable"],
        "books_schema_limitations": snapshot["limitations"],
        "read_only": True,
    }


__all__ = ["lease_vs_books"]
