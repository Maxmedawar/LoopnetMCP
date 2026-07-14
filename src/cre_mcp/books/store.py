"""Durable property-book records in the shared CRE cache database.

Only ``bk_*`` tables are owned here.  Dollar values are never persisted: every
amount is an integer number of cents and every source-bearing row retains the
trace needed to audit it.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from cre_mcp.config import CreConfig

CHARGE_KINDS = frozenset({"rent", "cam", "tax", "ins", "other"})
CHARGE_SOURCES = frozenset({"schedule", "manual"})
RECEIPT_STATUSES = frozenset({"matched", "partial", "unmatched"})


def utc_now() -> str:
    """Return a stable, timezone-explicit creation timestamp."""

    return datetime.now(UTC).isoformat()


def require_cents(value: Any, *, name: str = "amount_cents") -> int:
    """Reject floats and other lossy money representations."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _text(value: Any, *, name: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    normalized = str(value).strip()
    if not normalized:
        if nullable:
            return None
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class BookStore:
    """Own the tenancy, charge, receipt, and bank-import books."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        if isinstance(db_path, CreConfig):
            resolved = db_path.cache_db_path
        else:
            resolved = db_path or (config or CreConfig()).cache_db_path
        self.db_path = Path(resolved).expanduser()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Open one transactional connection and initialize only owned tables."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS bk_tenancies (
                tenancy_id TEXT PRIMARY KEY,
                deal_id TEXT NOT NULL,
                unit TEXT NOT NULL,
                tenant_name TEXT NOT NULL,
                lease_ref TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                CHECK(active IN (0, 1))
            );
            CREATE INDEX IF NOT EXISTS idx_bk_tenancies_deal
                ON bk_tenancies(deal_id, active, unit);

            CREATE TABLE IF NOT EXISTS bk_charges (
                charge_id TEXT PRIMARY KEY,
                tenancy_id TEXT NOT NULL,
                period TEXT NOT NULL,
                kind TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_detail TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(tenancy_id) REFERENCES bk_tenancies(tenancy_id),
                CHECK(length(period) = 7 AND substr(period, 5, 1) = '-'),
                CHECK(kind IN ('rent', 'cam', 'tax', 'ins', 'other')),
                CHECK(amount_cents >= 0),
                CHECK(source IN ('schedule', 'manual'))
            );
            CREATE INDEX IF NOT EXISTS idx_bk_charges_period
                ON bk_charges(period, tenancy_id, source, kind);

            CREATE TABLE IF NOT EXISTS bk_imports (
                import_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                imported_at TEXT NOT NULL,
                mapping_json TEXT NOT NULL,
                CHECK(row_count >= 0)
            );

            CREATE TABLE IF NOT EXISTS bk_receipts (
                receipt_id TEXT PRIMARY KEY,
                tenancy_id TEXT,
                date TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                payer_hint TEXT NOT NULL,
                method TEXT NOT NULL,
                import_id TEXT,
                matched_charge_ids TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'unmatched',
                FOREIGN KEY(tenancy_id) REFERENCES bk_tenancies(tenancy_id),
                FOREIGN KEY(import_id) REFERENCES bk_imports(import_id),
                CHECK(amount_cents > 0),
                CHECK(status IN ('matched', 'partial', 'unmatched'))
            );
            CREATE INDEX IF NOT EXISTS idx_bk_receipts_date
                ON bk_receipts(date, status, tenancy_id);
            CREATE INDEX IF NOT EXISTS idx_bk_receipts_import
                ON bk_receipts(import_id, receipt_id);
            """
        )
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def setup_tenancy(
        self,
        *,
        deal_id: str,
        unit: str,
        tenant_name: str,
        lease_ref: str | Path | None = None,
        active: bool = True,
        tenancy_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_id = _text(tenancy_id, name="tenancy_id", nullable=True)
        normalized_id = normalized_id or f"bkt-{uuid.uuid4().hex}"
        normalized_lease = _text(lease_ref, name="lease_ref", nullable=True)
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO bk_tenancies(
                    tenancy_id, deal_id, unit, tenant_name, lease_ref, active
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_id,
                    _text(deal_id, name="deal_id"),
                    _text(unit, name="unit"),
                    _text(tenant_name, name="tenant_name"),
                    normalized_lease,
                    int(bool(active)),
                ),
            )
            row = connection.execute(
                "SELECT * FROM bk_tenancies WHERE tenancy_id=?", (normalized_id,)
            ).fetchone()
        result = dict(row)
        result["active"] = bool(result["active"])
        return result

    def get_tenancy(self, tenancy_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM bk_tenancies WHERE tenancy_id=?",
                (_text(tenancy_id, name="tenancy_id"),),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown tenancy {tenancy_id!r}")
        result = dict(row)
        result["active"] = bool(result["active"])
        return result

    def list_tenancies(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE active=1" if active_only else ""
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM bk_tenancies {where} ORDER BY tenant_name, tenancy_id"
            ).fetchall()
        results = [dict(row) for row in rows]
        for result in results:
            result["active"] = bool(result["active"])
        return results

    def add_charge(
        self,
        *,
        tenancy_id: str,
        period: str,
        kind: str,
        amount_cents: int,
        source: str,
        source_detail: str | Mapping[str, Any],
        charge_id: str | None = None,
        created_at: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        normalized_kind = str(kind).strip().casefold()
        normalized_source = str(source).strip().casefold()
        if normalized_kind not in CHARGE_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(CHARGE_KINDS))}")
        if normalized_source not in CHARGE_SOURCES:
            raise ValueError(
                f"source must be one of: {', '.join(sorted(CHARGE_SOURCES))}"
            )
        detail = (
            json.dumps(source_detail, sort_keys=True, separators=(",", ":"))
            if isinstance(source_detail, Mapping)
            else _text(source_detail, name="source_detail")
        )
        normalized_id = _text(charge_id, name="charge_id", nullable=True)
        normalized_id = normalized_id or f"bkc-{uuid.uuid4().hex}"
        with self.connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO bk_charges(
                    charge_id, tenancy_id, period, kind, amount_cents,
                    source, source_detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_id,
                    _text(tenancy_id, name="tenancy_id"),
                    period,
                    normalized_kind,
                    require_cents(amount_cents),
                    normalized_source,
                    detail,
                    created_at or utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM bk_charges WHERE charge_id=?", (normalized_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("charge insert did not produce a durable row")
        return dict(row), bool(cursor.rowcount)

    def list_charges(
        self,
        *,
        tenancy_id: str | None = None,
        period: str | None = None,
        from_period: str | None = None,
        to_period: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if tenancy_id is not None:
            clauses.append("tenancy_id=?")
            values.append(tenancy_id)
        if period is not None:
            clauses.append("period=?")
            values.append(period)
        if from_period is not None:
            clauses.append("period>=?")
            values.append(from_period)
        if to_period is not None:
            clauses.append("period<=?")
            values.append(to_period)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM bk_charges {where}
                ORDER BY period, tenancy_id, kind, charge_id
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def create_import(
        self,
        *,
        import_id: str,
        filename: str,
        row_count: int,
        mapping: Mapping[str, Any],
        imported_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        mapping_json = json.dumps(mapping, sort_keys=True, separators=(",", ":"))

        def insert(target: sqlite3.Connection) -> bool:
            cursor = target.execute(
                """
                INSERT OR IGNORE INTO bk_imports(
                    import_id, filename, row_count, imported_at, mapping_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _text(import_id, name="import_id"),
                    _text(filename, name="filename"),
                    require_cents(row_count, name="row_count"),
                    imported_at or utc_now(),
                    mapping_json,
                ),
            )
            return bool(cursor.rowcount)

        if connection is not None:
            return insert(connection)
        with self.connection() as target:
            return insert(target)

    def add_receipt(
        self,
        *,
        receipt_id: str,
        date: str,
        amount_cents: int,
        payer_hint: str,
        method: str,
        import_id: str | None,
        tenancy_id: str | None = None,
        matched_charge_ids: Sequence[str] = (),
        status: str = "unmatched",
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        normalized_status = str(status).strip().casefold()
        if normalized_status not in RECEIPT_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(sorted(RECEIPT_STATUSES))}"
            )
        amount = require_cents(amount_cents)
        if amount == 0:
            raise ValueError("receipt amount_cents must be positive")
        charge_json = json.dumps(list(matched_charge_ids), separators=(",", ":"))

        def insert(target: sqlite3.Connection) -> bool:
            cursor = target.execute(
                """
                INSERT OR IGNORE INTO bk_receipts(
                    receipt_id, tenancy_id, date, amount_cents, payer_hint,
                    method, import_id, matched_charge_ids, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _text(receipt_id, name="receipt_id"),
                    _text(tenancy_id, name="tenancy_id", nullable=True),
                    date,
                    amount,
                    str(payer_hint).strip(),
                    _text(method, name="method"),
                    _text(import_id, name="import_id", nullable=True),
                    charge_json,
                    normalized_status,
                ),
            )
            return bool(cursor.rowcount)

        if connection is not None:
            return insert(connection)
        with self.connection() as target:
            return insert(target)

    def list_receipts(
        self,
        *,
        period: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if period is not None:
            clauses.append("substr(date, 1, 7)=?")
            values.append(period)
        if status is not None:
            clauses.append("status=?")
            values.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM bk_receipts {where} ORDER BY date, receipt_id",
                values,
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            result = dict(row)
            try:
                result["matched_charge_ids"] = json.loads(
                    result["matched_charge_ids"] or "[]"
                )
            except (TypeError, json.JSONDecodeError):
                result["matched_charge_ids"] = []
            results.append(result)
        return results

    def update_receipt_match(
        self,
        receipt_id: str,
        *,
        tenancy_id: str | None,
        matched_charge_ids: Sequence[str],
        status: str,
    ) -> dict[str, Any]:
        normalized_status = str(status).strip().casefold()
        if normalized_status not in RECEIPT_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(sorted(RECEIPT_STATUSES))}"
            )
        with self.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE bk_receipts
                SET tenancy_id=?, matched_charge_ids=?, status=?
                WHERE receipt_id=?
                """,
                (
                    tenancy_id,
                    json.dumps(list(matched_charge_ids), separators=(",", ":")),
                    normalized_status,
                    receipt_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM bk_receipts WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
        if not cursor.rowcount or row is None:
            raise KeyError(f"unknown receipt {receipt_id!r}")
        result = dict(row)
        result["matched_charge_ids"] = json.loads(result["matched_charge_ids"])
        return result


__all__ = [
    "BookStore",
    "CHARGE_KINDS",
    "CHARGE_SOURCES",
    "RECEIPT_STATUSES",
    "require_cents",
    "utc_now",
]
