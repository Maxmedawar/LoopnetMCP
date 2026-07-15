"""Durable control-period books for signed commercial master leases.

This module owns only the ``ml_positions`` and ``ml_flows`` tables.  Monetary
amounts are stored and calculated as integer cents.  A position status starts
with the core sandwich-risk exposure: master rent owed versus sublease cash
received, irrespective of whether the master rent has already been paid.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterator

from cre_mcp.config import CreConfig


FLOW_TYPES = frozenset(
    {
        "master_rent_due",
        "master_rent_paid",
        "sublease_billed",
        "sublease_received",
        "expense",
        "reserve_draw",
    }
)

_PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _text(value: Any, *, name: str, nullable: bool = False) -> str | None:
    if value is None:
        if nullable:
            return None
        raise ValueError(f"{name} is required")
    if not isinstance(value, (str, Path)):
        raise TypeError(f"{name} must be a string")
    normalized = str(value).strip()
    if not normalized:
        if nullable:
            return None
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _cents(value: Any, *, name: str, nullable: bool = False) -> int | None:
    """Validate lossless, non-negative integer cents without coercion."""

    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        qualifier = " or null" if nullable else ""
        raise ValueError(f"{name} must be a non-negative integer number of cents{qualifier}")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _period(value: Any) -> str:
    normalized = _text(value, name="period")
    assert isinstance(normalized, str)
    if not _PERIOD_PATTERN.fullmatch(normalized):
        raise ValueError("period must be YYYY-MM")
    return normalized


def _timestamp(value: Any = None) -> str:
    """Normalize a supplied start date/datetime, or return a UTC timestamp."""

    if value is None:
        return datetime.now(UTC).isoformat()
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("started_at cannot be blank")
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(
                    date.fromisoformat(normalized), datetime.min.time(), tzinfo=UTC
                )
            except ValueError as exc:
                raise ValueError("started_at must be an ISO date or datetime") from exc
    else:
        raise TypeError("started_at must be an ISO string, date, datetime, or null")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


class ControlBookStore:
    """Own signed master-lease positions and their monthly control flows."""

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
        """Open a transaction and initialize only this module's two tables."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ml_positions (
                position_id TEXT PRIMARY KEY,
                property TEXT NOT NULL,
                owner_name TEXT,
                master_rent_cents INTEGER NOT NULL,
                term_months INTEGER NOT NULL,
                security_cents INTEGER,
                reserves_cents INTEGER,
                started_at TEXT NOT NULL,
                CHECK(master_rent_cents >= 0),
                CHECK(term_months > 0),
                CHECK(security_cents IS NULL OR security_cents >= 0),
                CHECK(reserves_cents IS NULL OR reserves_cents >= 0)
            );

            CREATE TABLE IF NOT EXISTS ml_flows (
                position_id TEXT NOT NULL,
                period TEXT NOT NULL,
                type TEXT NOT NULL,
                cents INTEGER NOT NULL,
                note TEXT,
                FOREIGN KEY(position_id) REFERENCES ml_positions(position_id),
                CHECK(length(period) = 7 AND substr(period, 5, 1) = '-'),
                CHECK(type IN (
                    'master_rent_due', 'master_rent_paid',
                    'sublease_billed', 'sublease_received',
                    'expense', 'reserve_draw'
                )),
                CHECK(cents >= 0)
            );
            CREATE INDEX IF NOT EXISTS idx_ml_flows_position_period
                ON ml_flows(position_id, period, type);
            """
        )
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def open_position(
        self,
        *,
        property: str,
        master_rent_cents: int,
        term_months: int,
        owner_name: str | None = None,
        security_cents: int | None = None,
        reserves_cents: int | None = None,
        started_at: str | date | datetime | None = None,
        position_id: str | None = None,
    ) -> dict[str, Any]:
        """Open a signed position while preserving unknown optional inputs as NULL."""

        normalized_id = _text(position_id, name="position_id", nullable=True)
        normalized_id = normalized_id or f"mlp-{uuid.uuid4().hex}"
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO ml_positions(
                    position_id, property, owner_name, master_rent_cents,
                    term_months, security_cents, reserves_cents, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_id,
                    _text(property, name="property"),
                    _text(owner_name, name="owner_name", nullable=True),
                    _cents(master_rent_cents, name="master_rent_cents"),
                    _positive_int(term_months, name="term_months"),
                    _cents(security_cents, name="security_cents", nullable=True),
                    _cents(reserves_cents, name="reserves_cents", nullable=True),
                    _timestamp(started_at),
                ),
            )
            row = connection.execute(
                "SELECT * FROM ml_positions WHERE position_id=?", (normalized_id,)
            ).fetchone()
        if row is None:
            raise RuntimeError("position insert did not produce a durable row")
        return dict(row)

    def get_position(self, position_id: str) -> dict[str, Any]:
        """Return one position or raise for an unknown identifier."""

        normalized_id = _text(position_id, name="position_id")
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM ml_positions WHERE position_id=?", (normalized_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown master-lease position {normalized_id!r}")
        return dict(row)

    def record_flow(
        self,
        *,
        position_id: str,
        period: str,
        type: str,
        cents: int,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Append a control-period flow; multiple entries per type are allowed."""

        normalized_id = _text(position_id, name="position_id")
        normalized_period = _period(period)
        normalized_type = _text(type, name="type")
        assert isinstance(normalized_type, str)
        normalized_type = normalized_type.casefold()
        if normalized_type not in FLOW_TYPES:
            allowed = ", ".join(sorted(FLOW_TYPES))
            raise ValueError(f"type must be one of: {allowed}")
        normalized_note = _text(note, name="note", nullable=True)
        normalized_cents = _cents(cents, name="cents")
        with self.connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM ml_positions WHERE position_id=?", (normalized_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(f"unknown master-lease position {normalized_id!r}")
            connection.execute(
                """
                INSERT INTO ml_flows(position_id, period, type, cents, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    normalized_id,
                    normalized_period,
                    normalized_type,
                    normalized_cents,
                    normalized_note,
                ),
            )
        return {
            "position_id": normalized_id,
            "period": normalized_period,
            "type": normalized_type,
            "cents": normalized_cents,
            "note": normalized_note,
        }

    def position_status(self, position_id: str, period: str) -> dict[str, Any]:
        """Report current-period carry, collections, reserves, and break-even.

        ``sublease_received / sublease_billed`` is a cash-collection proxy requested
        by the operating checklist.  It is not physical occupancy and is intentionally
        not capped at 100%, because arrears and prepayments can make it exceed one.
        """

        normalized_id = _text(position_id, name="position_id")
        normalized_period = _period(period)
        with self.connection() as connection:
            position_row = connection.execute(
                "SELECT * FROM ml_positions WHERE position_id=?", (normalized_id,)
            ).fetchone()
            if position_row is None:
                raise KeyError(f"unknown master-lease position {normalized_id!r}")
            rows = connection.execute(
                """
                SELECT type, COUNT(*) AS entry_count, COALESCE(SUM(cents), 0) AS cents
                FROM ml_flows
                WHERE position_id=? AND period=?
                GROUP BY type
                """,
                (normalized_id, normalized_period),
            ).fetchall()
            cumulative_draw_row = connection.execute(
                """
                SELECT COALESCE(SUM(cents), 0) AS cents
                FROM ml_flows
                WHERE position_id=? AND period<=? AND type='reserve_draw'
                """,
                (normalized_id, normalized_period),
            ).fetchone()

        position = dict(position_row)
        totals = {flow_type: 0 for flow_type in FLOW_TYPES}
        counts = {flow_type: 0 for flow_type in FLOW_TYPES}
        for row in rows:
            totals[str(row["type"])] = int(row["cents"])
            counts[str(row["type"])] = int(row["entry_count"])

        if counts["master_rent_due"]:
            master_rent_owed = totals["master_rent_due"]
            rent_due_source = "recorded_master_rent_due_flows"
        else:
            master_rent_owed = int(position["master_rent_cents"])
            rent_due_source = "position_master_rent_fallback"

        master_rent_paid = totals["master_rent_paid"]
        billed = totals["sublease_billed"]
        received = totals["sublease_received"]
        expenses = totals["expense"]
        current_draw = totals["reserve_draw"]
        cumulative_draws = int(cumulative_draw_row["cents"])

        signed_rent_exposure = master_rent_owed - received
        uncovered_rent_exposure = max(0, signed_rent_exposure)
        burn = max(0, master_rent_owed + expenses - received)
        payment_gap = max(0, master_rent_owed - master_rent_paid)

        occupancy = received / billed if billed > 0 else None
        break_even = (master_rent_owed + expenses) / billed if billed > 0 else None

        security = position["security_cents"]
        stated_reserves = position["reserves_cents"]
        reserves_known = stated_reserves is not None
        if reserves_known:
            starting_operating_reserves = int(stated_reserves)
            reserve_balance = max(0, starting_operating_reserves - cumulative_draws)
            reserve_months = reserve_balance / burn if burn > 0 else None
        else:
            starting_operating_reserves = None
            reserve_balance = None
            reserve_months = None

        gaps: list[str] = []
        gaps.append(
            "physical_sublease_occupancy_unavailable; cash collection is shown as a proxy"
        )
        if billed <= 0:
            gaps.append("sublease_billed_missing_or_zero_for_occupancy_and_break_even")
        else:
            gaps.append(
                "full_occupancy_rent_capacity_unverified; break-even uses current billings as proxy"
            )
        if not reserves_known:
            gaps.append("reserves_unknown_for_reserve_runway")
        if burn == 0:
            gaps.append("reserve_months_not_finite_because_current_burn_is_zero")

        # Dict insertion order deliberately leads with rent owed versus rent received.
        return {
            "rent_owed_vs_received_exposure": {
                "master_rent_owed_cents": master_rent_owed,
                "sublease_received_cents": received,
                "signed_exposure_cents": signed_rent_exposure,
                "uncovered_exposure_cents": uncovered_rent_exposure,
                "net_rent_spread_cents": received - master_rent_owed,
                "formula": "master_rent_owed_cents - sublease_received_cents",
                "negative_carry_warning": (
                    "Master rent remains owed even when billed sublease rent is vacant, "
                    "uncollected, disputed, or subject to subtenant default."
                ),
            },
            "position_id": normalized_id,
            "period": normalized_period,
            "property": position["property"],
            "owner_name": position["owner_name"],
            "master_rent_owed_cents": master_rent_owed,
            "master_rent_due_source": rent_due_source,
            "master_rent_paid_cents": master_rent_paid,
            "master_rent_payment_gap_cents": payment_gap,
            "sublease_billed_cents": billed,
            "sublease_received_cents": received,
            "expense_cents": expenses,
            "reserve_draw_cents": current_draw,
            "rent_exposure_cents": uncovered_rent_exposure,
            "signed_rent_exposure_cents": signed_rent_exposure,
            "sublease_occupancy": occupancy,
            "cash_collection_proxy": occupancy,
            "physical_sublease_occupancy": None,
            "sublease_occupancy_formula": (
                "sublease_received_cents / sublease_billed_cents; cash-collection "
                "proxy, not physical occupancy"
            ),
            "negative_carry_burn_rate_cents": burn,
            "negative_carry_burn_formula": (
                "max(0, master_rent_owed_cents + expense_cents "
                "- sublease_received_cents)"
            ),
            "security_cents": security,
            "stated_reserves_cents": stated_reserves,
            "starting_operating_reserves_cents": starting_operating_reserves,
            "cumulative_reserve_draw_cents": cumulative_draws,
            "reserve_balance_cents": reserve_balance,
            "reserve_months_remaining": reserve_months,
            "reserve_runway_formula": (
                "max(0, reserves_cents - cumulative_reserve_draw_cents) "
                "/ negative_carry_burn_rate_cents"
            ),
            "reserve_availability_note": (
                "Security is owner-held collateral and is excluded from operating "
                "reserve runway unless release and availability are independently "
                "verified under the lease."
            ),
            "break_even_sublease_occupancy": break_even,
            "break_even_sublease_occupancy_formula": (
                "(master_rent_owed_cents + expense_cents) / sublease_billed_cents; "
                "not capped at 100%; current billed rent is a potential-rent proxy, "
                "not verified physical capacity"
            ),
            "flow_totals_cents": totals,
            "gaps": gaps,
        }


# A concise alias makes the store discoverable under either module terminology.
MLControlStore = ControlBookStore


def open_position(
    *,
    property: str,
    master_rent_cents: int,
    term_months: int,
    owner_name: str | None = None,
    security_cents: int | None = None,
    reserves_cents: int | None = None,
    started_at: str | date | datetime | None = None,
    position_id: str | None = None,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Open a position using a one-shot configurable store."""

    return ControlBookStore(db_path).open_position(
        property=property,
        master_rent_cents=master_rent_cents,
        term_months=term_months,
        owner_name=owner_name,
        security_cents=security_cents,
        reserves_cents=reserves_cents,
        started_at=started_at,
        position_id=position_id,
    )


def record_flow(
    *,
    position_id: str,
    period: str,
    type: str,
    cents: int,
    note: str | None = None,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Record a flow using a one-shot configurable store."""

    return ControlBookStore(db_path).record_flow(
        position_id=position_id,
        period=period,
        type=type,
        cents=cents,
        note=note,
    )


def position_status(
    position_id: str,
    period: str,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Calculate status using a one-shot configurable store."""

    return ControlBookStore(db_path).position_status(position_id, period)


__all__ = [
    "FLOW_TYPES",
    "ControlBookStore",
    "MLControlStore",
    "open_position",
    "record_flow",
    "position_status",
]
