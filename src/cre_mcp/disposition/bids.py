"""Bid outcome ledger and fully exposed certainty normalization.

``disp_bids`` is the only table this module owns.  The original headline price
remains immutable; later outcome prices and retrade events are recorded on the
same row so idempotent status updates do not inflate buyer history.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig

BID_STATUSES = frozenset(
    {"active", "retraded", "withdrawn", "selected", "closed"}
)

DEFAULT_FINANCING_RISK_WEIGHTS: dict[str, dict[str, float]] = {
    "cash": {"with_proof": 0.0, "without_proof": 0.0025},
    "seller_financing": {"with_proof": 0.005, "without_proof": 0.01},
    "assumed_debt": {"with_proof": 0.0075, "without_proof": 0.015},
    "conventional": {"with_proof": 0.01, "without_proof": 0.025},
    "bank": {"with_proof": 0.01, "without_proof": 0.025},
    "agency": {"with_proof": 0.01, "without_proof": 0.025},
    "bridge": {"with_proof": 0.015, "without_proof": 0.03},
    "debt_fund": {"with_proof": 0.015, "without_proof": 0.03},
    "hard_money": {"with_proof": 0.02, "without_proof": 0.035},
    "unknown": {"with_proof": 0.02, "without_proof": 0.035},
}

DEFAULT_CONTINGENCY_HAIRCUTS: dict[str, float] = {
    "financing": 0.01,
    "inspection": 0.005,
    "due_diligence": 0.0075,
    "appraisal": 0.0075,
    "sale_of_other_asset": 0.02,
    "zoning": 0.015,
    "lease": 0.01,
    "tenant": 0.01,
    "board_approval": 0.0075,
    "unknown": 0.005,
}

DISP_BIDS_SCHEMA_VERSION = 2
DISP_BIDS_SCHEMA_MIGRATION = (
    "v1 required deposit, diligence, closing, contingencies, financing, and "
    "received-at intelligence; v2 preserves rows and indexes while allowing "
    "those LOI-stage fields to remain honestly unknown"
)
DEFAULT_UNKNOWN_DD_DAYS = 60
DEFAULT_UNKNOWN_CLOSING_DAYS = 45

_TABLE_NAME = "disp_bids"
_MIGRATION_TABLE_NAME = "disp_bids_v2_migration"
_OPTIONAL_BID_COLUMNS = (
    "deposit",
    "dd_days",
    "closing_days",
    "contingencies",
    "financing",
    "received_at",
)
_BID_COLUMNS = (
    "bid_id, deal_id, buyer_id, price, deposit, dd_days, closing_days, "
    "contingencies, financing, received_at, status, final_price, "
    "retrade_count, retrade_history, status_changed_at"
)

_CREATE_TABLE = """
CREATE TABLE {table_name} (
    bid_id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    price REAL NOT NULL,
    deposit REAL,
    dd_days INTEGER,
    closing_days INTEGER,
    contingencies TEXT,
    financing TEXT,
    received_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    final_price REAL,
    retrade_count INTEGER NOT NULL DEFAULT 0,
    retrade_history TEXT NOT NULL DEFAULT '[]',
    status_changed_at TEXT NOT NULL,
    CHECK(price > 0),
    CHECK(deposit IS NULL OR deposit >= 0),
    CHECK(dd_days IS NULL OR dd_days >= 0),
    CHECK(closing_days IS NULL OR closing_days >= 0),
    CHECK(status IN ('active', 'retraded', 'withdrawn', 'selected', 'closed')),
    CHECK(final_price IS NULL OR final_price > 0),
    CHECK(retrade_count >= 0)
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_disp_bids_deal_status "
    "ON disp_bids(deal_id, status, received_at)",
    "CREATE INDEX IF NOT EXISTS idx_disp_bids_buyer "
    "ON disp_bids(buyer_id, received_at)",
)

_UNSET = object()
_TERMINAL_STATUSES = frozenset({"withdrawn", "closed"})
_ALLOWED_TRANSITIONS = {
    "active": BID_STATUSES,
    "retraded": frozenset({"retraded", "withdrawn", "selected", "closed"}),
    "selected": frozenset({"selected", "retraded", "withdrawn", "closed"}),
    "withdrawn": frozenset({"withdrawn"}),
    "closed": frozenset({"closed"}),
}


def _resolve_db_path(
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> Path:
    if isinstance(db_path, CreConfig):
        resolved = db_path.cache_db_path
    else:
        resolved = db_path or (config or CreConfig()).cache_db_path
    return Path(resolved).expanduser()


def _connect(
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> sqlite3.Connection:
    path = _resolve_db_path(db_path, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    try:
        _ensure_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> str:
    """Create/migrate only ``disp_bids`` without shared schema metadata.

    The shared cache database's ``user_version`` belongs to no single module,
    so schema state is inferred from this owned table.  Rebuilding is performed
    in one immediate transaction; all rows and every explicit index attached to
    ``disp_bids`` are recreated, while unrelated tables are untouched.
    """

    connection.execute("BEGIN IMMEDIATE")
    schema_result = "v2_current"
    try:
        columns = connection.execute("PRAGMA table_info(disp_bids)").fetchall()
        if not columns:
            connection.execute(_CREATE_TABLE.format(table_name=_TABLE_NAME))
            schema_result = "v2_created"
        else:
            by_name = {str(column["name"]): column for column in columns}
            required_columns = {
                column.strip().split()[0]
                for column in _BID_COLUMNS.split(",")
            }
            missing = required_columns - set(by_name)
            if missing:
                names = ", ".join(sorted(missing))
                raise RuntimeError(
                    f"disp_bids has an unsupported schema; missing columns: {names}"
                )
            legacy_not_null = any(
                bool(by_name[name]["notnull"]) for name in _OPTIONAL_BID_COLUMNS
            )
            if legacy_not_null:
                explicit_indexes = [
                    str(row["sql"])
                    for row in connection.execute(
                        """
                        SELECT sql
                        FROM sqlite_master
                        WHERE type='index' AND tbl_name=? AND sql IS NOT NULL
                        ORDER BY name
                        """,
                        (_TABLE_NAME,),
                    ).fetchall()
                ]
                connection.execute(f"DROP TABLE IF EXISTS {_MIGRATION_TABLE_NAME}")
                connection.execute(
                    _CREATE_TABLE.format(table_name=_MIGRATION_TABLE_NAME)
                )
                connection.execute(
                    f"INSERT INTO {_MIGRATION_TABLE_NAME} ({_BID_COLUMNS}) "
                    f"SELECT {_BID_COLUMNS} FROM {_TABLE_NAME}"
                )
                connection.execute(f"DROP TABLE {_TABLE_NAME}")
                connection.execute(
                    f"ALTER TABLE {_MIGRATION_TABLE_NAME} RENAME TO {_TABLE_NAME}"
                )
                for index_sql in explicit_indexes:
                    connection.execute(index_sql)
                schema_result = "v1_rows_and_indexes_preserved_and_migrated_to_v2"
        for index_sql in _CREATE_INDEXES:
            connection.execute(index_sql)
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
        return schema_result


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp(value: Any, label: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{label} cannot be blank")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO date or datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _optional_timestamp(value: Any, label: str) -> str | None:
    """Validate a reported timestamp while preserving an omitted timestamp."""

    if value is None:
        return None
    return _timestamp(value, label)


def _text(value: Any, label: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{label} is required")
        return None
    result = str(value).strip()
    if not result:
        if required:
            raise ValueError(f"{label} cannot be blank")
        return None
    return result


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _whole_number(value: Any, label: str) -> int:
    number = _number(value, label)
    if not number.is_integer():
        raise ValueError(f"{label} must be a whole number")
    return int(number)


def _optional_number(value: Any, label: str) -> float | None:
    """Validate reported numeric intelligence while preserving unknowns."""

    if value is None:
        return None
    return _number(value, label)


def _optional_whole_number(value: Any, label: str) -> int | None:
    """Validate reported integral intelligence while preserving unknowns."""

    if value is None:
        return None
    return _whole_number(value, label)


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _json_value(value: Any, label: str, *, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (Mapping, list, tuple)):
        return dict(value) if isinstance(value, Mapping) else list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return text
        return decoded
    raise ValueError(f"{label} must be JSON-compatible")


def _decode_json(value: Any, default: Any) -> Any:
    if value is None:
        return None
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _json_storage(value: Any) -> str | None:
    """Encode known JSON intelligence; SQL NULL means genuinely unknown."""

    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"))


def _retrade_math(price: float, final_price: float | None) -> dict[str, Any]:
    if final_price is None:
        return {
            "retrade_delta_dollars": None,
            "retrade_delta_pct": None,
            "retrade": None,
        }
    delta = final_price - price
    pct = delta / price
    return {
        "retrade_delta_dollars": round(delta, 2),
        "retrade_delta_pct": round(pct, 8),
        "retrade": {
            "original_price": price,
            "final_price": final_price,
            "dollar_change_final_minus_original": round(delta, 2),
            "percent_change_final_minus_original": round(pct, 8),
            "price_reduction": round(price - final_price, 2),
            "price_reduction_pct": round((price - final_price) / price, 8),
        },
    }


def _bid_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["contingencies"] = _decode_json(result["contingencies"], [])
    result["financing"] = _decode_json(result["financing"], {})
    result["retrade_history"] = _decode_json(result["retrade_history"], [])
    result["received_at_status"] = (
        "known" if result["received_at"] is not None else "unknown"
    )
    result["received_at_source"] = (
        "reported" if result["received_at"] is not None else "unknown"
    )
    result["received_at_value_source"] = (
        "recorded_bid_input"
        if result["received_at"] is not None
        else "status_changed_at_sort_fallback"
    )
    result.update(
        _retrade_math(float(result["price"]), result.get("final_price"))
    )
    return result


def _status(value: Any) -> str:
    normalized = _slug(value)
    if normalized not in BID_STATUSES:
        allowed = ", ".join(sorted(BID_STATUSES))
        raise ValueError(f"status must be one of: {allowed}")
    return normalized


def record_bid(
    bid: Mapping[str, Any] | None = None,
    *,
    bid_id: str | None = None,
    deal_id: str | None = None,
    buyer_id: str | None = None,
    price: Any = None,
    deposit: Any = None,
    dd_days: Any = None,
    closing_days: Any = None,
    contingencies: Any = None,
    financing: Any = None,
    received_at: Any = None,
    status: str | None = None,
    final_price: Any = _UNSET,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Insert a bid or idempotently patch its status/final outcome.

    Supplying an existing ``bid_id`` updates that row.  ``price`` is the immutable
    headline bid; changed economics belong in ``final_price`` so retrade math and
    history remain auditable.
    """

    supplied = dict(bid or {})

    def chosen(keyword: Any, key: str) -> Any:
        return keyword if keyword is not None else supplied.get(key)

    normalized_bid_id = _text(chosen(bid_id, "bid_id"), "bid_id")
    if normalized_bid_id is None:
        normalized_bid_id = f"bid_{uuid.uuid4().hex}"

    with _connect(db_path, config) as connection:
        existing = connection.execute(
            "SELECT * FROM disp_bids WHERE bid_id=?", (normalized_bid_id,)
        ).fetchone()
        now = _now()
        if existing is None:
            normalized_deal_id = _text(
                chosen(deal_id, "deal_id"), "deal_id", required=True
            )
            normalized_buyer_id = _text(
                chosen(buyer_id, "buyer_id"), "buyer_id", required=True
            )
            headline = _number(chosen(price, "price"), "price")
            deposit_amount = _optional_number(
                chosen(deposit, "deposit"), "deposit"
            )
            diligence_days = _optional_whole_number(
                chosen(dd_days, "dd_days"), "dd_days"
            )
            close_days = _optional_whole_number(
                chosen(closing_days, "closing_days"), "closing_days"
            )
            if headline <= 0:
                raise ValueError("price must be positive")
            if deposit_amount is not None and deposit_amount < 0:
                raise ValueError("deposit cannot be negative")
            if (diligence_days is not None and diligence_days < 0) or (
                close_days is not None and close_days < 0
            ):
                raise ValueError("dd_days and closing_days cannot be negative")
            raw_contingencies = chosen(contingencies, "contingencies")
            contingency_value = (
                None
                if raw_contingencies is None
                else _json_value(
                    raw_contingencies, "contingencies", default=None
                )
            )
            raw_financing = chosen(financing, "financing")
            financing_value = (
                None
                if raw_financing is None
                else _json_value(raw_financing, "financing", default=None)
            )
            received = _optional_timestamp(
                chosen(received_at, "received_at"), "received_at"
            )
            normalized_status = _status(chosen(status, "status") or "active")
            raw_final = (
                supplied.get("final_price", _UNSET)
                if final_price is _UNSET
                else final_price
            )
            outcome_price = (
                None if raw_final in (_UNSET, None) else _number(raw_final, "final_price")
            )
            if outcome_price is not None and outcome_price <= 0:
                raise ValueError("final_price must be positive")
            history: list[dict[str, Any]] = []
            if normalized_status == "retraded" or (
                outcome_price is not None and not math.isclose(outcome_price, headline)
            ):
                history.append(
                    {
                        "from_price": headline,
                        "to_price": outcome_price,
                        "to_price_status": (
                            "known" if outcome_price is not None else "unknown"
                        ),
                        "to_price_source": (
                            "recorded_final_price"
                            if outcome_price is not None
                            else "not_reported"
                        ),
                        "note": (
                            "Revised price was recorded with this event."
                            if outcome_price is not None
                            else "Retrade observed; revised price is unknown until reported."
                        ),
                        "recorded_at": now,
                        "trigger": (
                            "status_retraded"
                            if normalized_status == "retraded"
                            else "final_price_change"
                        ),
                    }
                )
            connection.execute(
                """
                INSERT INTO disp_bids(
                    bid_id, deal_id, buyer_id, price, deposit, dd_days,
                    closing_days, contingencies, financing, received_at, status,
                    final_price, retrade_count, retrade_history, status_changed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_bid_id,
                    normalized_deal_id,
                    normalized_buyer_id,
                    headline,
                    deposit_amount,
                    diligence_days,
                    close_days,
                    _json_storage(contingency_value),
                    _json_storage(financing_value),
                    received,
                    normalized_status,
                    outcome_price,
                    len(history),
                    json.dumps(history, separators=(",", ":")),
                    now,
                ),
            )
            previous_status = None
            retrade_recorded = bool(history)
        else:
            previous = _bid_from_row(existing)
            previous_status = str(previous["status"])
            if previous_status in _TERMINAL_STATUSES:
                # Terminal rows accept only an exact repeated outcome call.
                requested_status = _status(chosen(status, "status") or previous_status)
                raw_final = (
                    supplied.get("final_price", _UNSET)
                    if final_price is _UNSET
                    else final_price
                )
                requested_final = (
                    previous["final_price"]
                    if raw_final is _UNSET
                    else (
                        None
                        if raw_final is None
                        else _number(raw_final, "final_price")
                    )
                )
                if requested_status != previous_status or requested_final != previous["final_price"]:
                    raise ValueError(f"status {previous_status!r} is terminal")
            requested_deal = chosen(deal_id, "deal_id")
            requested_buyer = chosen(buyer_id, "buyer_id")
            if requested_deal is not None and str(requested_deal).strip() != previous["deal_id"]:
                raise ValueError("deal_id cannot change for an existing bid")
            if requested_buyer is not None and str(requested_buyer).strip() != previous["buyer_id"]:
                raise ValueError("buyer_id cannot change for an existing bid")
            requested_price = chosen(price, "price")
            if requested_price is not None and not math.isclose(
                _number(requested_price, "price"), float(previous["price"])
            ):
                raise ValueError("headline price is immutable; use final_price for a retrade")

            normalized_status = _status(chosen(status, "status") or previous_status)
            if normalized_status not in _ALLOWED_TRANSITIONS[previous_status]:
                raise ValueError(
                    f"invalid bid status transition: {previous_status} -> {normalized_status}"
                )
            raw_final = (
                supplied.get("final_price", _UNSET)
                if final_price is _UNSET
                else final_price
            )
            if raw_final is _UNSET:
                outcome_price = previous["final_price"]
            elif raw_final is None:
                outcome_price = None
            else:
                outcome_price = _number(raw_final, "final_price")
                if outcome_price <= 0:
                    raise ValueError("final_price must be positive")
            if previous["final_price"] is not None and outcome_price is None:
                raise ValueError("final_price cannot be cleared after an outcome is recorded")

            deposit_amount = (
                previous["deposit"]
                if chosen(deposit, "deposit") is None
                else _number(chosen(deposit, "deposit"), "deposit")
            )
            diligence_days = (
                previous["dd_days"]
                if chosen(dd_days, "dd_days") is None
                else _whole_number(chosen(dd_days, "dd_days"), "dd_days")
            )
            close_days = (
                previous["closing_days"]
                if chosen(closing_days, "closing_days") is None
                else _whole_number(chosen(closing_days, "closing_days"), "closing_days")
            )
            if (
                (deposit_amount is not None and deposit_amount < 0)
                or (diligence_days is not None and diligence_days < 0)
                or (close_days is not None and close_days < 0)
            ):
                raise ValueError("deposit, dd_days, and closing_days cannot be negative")
            contingency_value = (
                previous["contingencies"]
                if chosen(contingencies, "contingencies") is None
                else _json_value(
                    chosen(contingencies, "contingencies"),
                    "contingencies",
                    default=None,
                )
            )
            financing_value = (
                previous["financing"]
                if chosen(financing, "financing") is None
                else _json_value(
                    chosen(financing, "financing"),
                    "financing",
                    default=None,
                )
            )
            requested_received_at = chosen(received_at, "received_at")
            received = (
                previous["received_at"]
                if requested_received_at is None
                else _timestamp(requested_received_at, "received_at")
            )
            history = list(previous["retrade_history"])
            previous_effective_price = (
                previous["final_price"]
                if previous["final_price"] is not None
                else previous["price"]
            )
            price_changed = outcome_price is not None and not math.isclose(
                outcome_price, float(previous_effective_price)
            )
            entering_retrade = normalized_status == "retraded" and previous_status != "retraded"
            resolving_unknown_retrade = (
                previous_status == "retraded"
                and previous["final_price"] is None
                and outcome_price is not None
                and bool(history)
                and history[-1].get("trigger") == "status_retraded"
                and history[-1].get("to_price") is None
            )
            if resolving_unknown_retrade:
                history[-1] = {
                    **history[-1],
                    "to_price": outcome_price,
                    "to_price_status": "known",
                    "to_price_source": "later_reported_resolution",
                    "note": (
                        "Unknown revised price was resolved for the existing retrade event; "
                        "no additional retrade was counted."
                    ),
                    "price_resolved_at": now,
                }
            retrade_recorded = (
                entering_retrade or price_changed
            ) and not resolving_unknown_retrade
            if retrade_recorded:
                from_price = (
                    previous["final_price"]
                    if previous["final_price"] is not None
                    else previous["price"]
                )
                history.append(
                    {
                        "from_price": from_price,
                        "to_price": outcome_price,
                        "to_price_status": (
                            "known" if outcome_price is not None else "unknown"
                        ),
                        "to_price_source": (
                            "recorded_final_price"
                            if outcome_price is not None
                            else "not_reported"
                        ),
                        "note": (
                            "Revised price was recorded with this event."
                            if outcome_price is not None
                            else "Retrade observed; revised price is unknown until reported."
                        ),
                        "recorded_at": now,
                        "trigger": (
                            "status_retraded" if entering_retrade else "final_price_change"
                        ),
                    }
                )
            status_changed_at = (
                now if normalized_status != previous_status else previous["status_changed_at"]
            )
            connection.execute(
                """
                UPDATE disp_bids
                SET deposit=?, dd_days=?, closing_days=?, contingencies=?, financing=?,
                    received_at=?, status=?, final_price=?, retrade_count=?, retrade_history=?,
                    status_changed_at=?
                WHERE bid_id=?
                """,
                (
                    deposit_amount,
                    diligence_days,
                    close_days,
                    _json_storage(contingency_value),
                    _json_storage(financing_value),
                    received,
                    normalized_status,
                    outcome_price,
                    len(history),
                    json.dumps(history, separators=(",", ":")),
                    status_changed_at,
                    normalized_bid_id,
                ),
            )

        fresh = connection.execute(
            "SELECT * FROM disp_bids WHERE bid_id=?", (normalized_bid_id,)
        ).fetchone()
        assert fresh is not None
        result = _bid_from_row(fresh)
        result["outcome_transition"] = {
            "from_status": previous_status,
            "to_status": result["status"],
            "status_changed": previous_status != result["status"],
            "retrade_recorded": retrade_recorded,
            "retrade_price_resolved": (
                resolving_unknown_retrade if existing is not None else False
            ),
        }
        # Read-only aggregate over this module's bid ledger; buyer rows are not
        # incremented and exact repeated updates therefore cannot double-count.
        try:
            from .buyers import _behavior

            result["buyer_behavior"] = _behavior(connection, str(result["buyer_id"]))
        except (ImportError, sqlite3.DatabaseError):
            result["buyer_behavior"] = None
        return result


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "y",
        "verified",
        "provided",
    }


def _rate(value: Any, label: str) -> float:
    rate = _number(value, label)
    if rate < 0:
        raise ValueError(f"{label} cannot be negative")
    if rate > 1:
        rate /= 100.0
    return rate


def _financing_weights(
    overrides: Mapping[str, Any] | None,
) -> dict[str, dict[str, float]]:
    result = {key: dict(value) for key, value in DEFAULT_FINANCING_RISK_WEIGHTS.items()}
    if overrides is None:
        return result
    for raw_type, raw_weights in overrides.items():
        financing_type = _slug(raw_type)
        if isinstance(raw_weights, Mapping):
            base = dict(result.get(financing_type, result["unknown"]))
            if "with_proof" in raw_weights:
                base["with_proof"] = _rate(
                    raw_weights["with_proof"],
                    f"financing_risk_weights.{raw_type}.with_proof",
                )
            if "without_proof" in raw_weights:
                base["without_proof"] = _rate(
                    raw_weights["without_proof"],
                    f"financing_risk_weights.{raw_type}.without_proof",
                )
            result[financing_type] = base
        else:
            weight = _rate(raw_weights, f"financing_risk_weights.{raw_type}")
            result[financing_type] = {
                "with_proof": weight,
                "without_proof": weight,
            }
    return result


def _contingency_weights(
    overrides: Mapping[str, Any] | None,
) -> dict[str, float]:
    result = dict(DEFAULT_CONTINGENCY_HAIRCUTS)
    if overrides:
        for key, value in overrides.items():
            result[_slug(key)] = _rate(value, f"contingency_haircuts.{key}")
    return result


def _financing_terms(value: Any) -> tuple[str, bool]:
    if isinstance(value, Mapping):
        raw_type = value.get("type", value.get("financing_type", "unknown"))
        proof = any(
            _truthy(value.get(key))
            for key in ("proof", "proof_of_funds", "preapproval", "commitment")
        )
    else:
        raw_type = value or "unknown"
        proof = False
    financing_type = _slug(raw_type)
    aliases = {
        "all_cash": "cash",
        "cash_offer": "cash",
        "seller": "seller_financing",
        "seller_finance": "seller_financing",
        "assumption": "assumed_debt",
        "loan_assumption": "assumed_debt",
        "traditional": "conventional",
        "conventional_loan": "conventional",
        "bank_loan": "bank",
        "agency_debt": "agency",
        "bridge_loan": "bridge",
        "debt_fund_loan": "debt_fund",
    }
    return aliases.get(financing_type, financing_type or "unknown"), proof


_CONTINGENCY_META_KEYS = frozenset(
    {
        "deposit_at_risk",
        "deposit_nonrefundable",
        "deposit_refundable",
        "notes",
        "none",
        "clean",
    }
)


def _contingency_names(value: Any) -> list[str]:
    raw: list[Any] = []
    if value is None:
        return []
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        raw = list(value)
    elif isinstance(value, Mapping):
        if "items" in value and isinstance(value["items"], Sequence):
            raw.extend(value["items"])
        elif "type" in value:
            raw.append(value["type"])
        raw.extend(
            key
            for key, enabled in value.items()
            if key not in {"items", "type"} | _CONTINGENCY_META_KEYS and _truthy(enabled)
        )
    result: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            item = item.get("type", item.get("name", "unknown"))
        slug = _slug(item)
        if slug and slug not in {"none", "no_contingencies", "clean"} and slug not in result:
            result.append(slug)
    return result


def _contingency_category(name: str, weights: Mapping[str, float]) -> str:
    if name in weights:
        return name
    if "financ" in name or "loan" in name:
        return "financing"
    if "inspect" in name or "physical" in name:
        return "inspection"
    if name in {"dd", "diligence"} or "due_diligence" in name:
        return "due_diligence"
    if "apprais" in name or "valuation" in name:
        return "appraisal"
    if "sale" in name or "exchange" in name:
        return "sale_of_other_asset"
    if "zon" in name or "entitle" in name:
        return "zoning"
    if "lease" in name:
        return "lease"
    if "tenant" in name or "estoppel" in name:
        return "tenant"
    if "board" in name or "committee" in name:
        return "board_approval"
    return "unknown"


def _deposit_at_risk(
    deposit: float | None, contingencies: Any
) -> tuple[float, str]:
    if deposit is None:
        return (
            0.0,
            "unknown deposit: weakest credit convention",
        )
    if isinstance(contingencies, Mapping):
        if "deposit_at_risk" in contingencies:
            amount = _number(contingencies["deposit_at_risk"], "deposit_at_risk")
            return max(0.0, min(amount, deposit)), "caller-supplied deposit_at_risk"
        if "deposit_nonrefundable" in contingencies:
            value = contingencies["deposit_nonrefundable"]
            if isinstance(value, bool):
                return (deposit if value else 0.0), "deposit_nonrefundable flag"
            amount = _number(value, "deposit_nonrefundable")
            return max(0.0, min(amount, deposit)), "caller-supplied nonrefundable amount"
        if _truthy(contingencies.get("deposit_refundable")):
            return 0.0, "deposit marked refundable"
    return deposit, "screening convention: stated deposit treated as at risk"


def normalize_bids(
    deal_id: str,
    *,
    carry_cost_per_day: Any = 0.0,
    deposit_credit_rate: Any = 0.10,
    financing_risk_weights: Mapping[str, Any] | None = None,
    contingency_haircuts: Mapping[str, Any] | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Rank bids by a disclosed, caller-adjustable certainty convention.

    ``adjusted_price`` is a comparison metric, not a valuation or prediction:
    headline price + recorded retrade + deposit credit - diligence carry cost -
    financing haircut - contingency haircuts.
    """

    normalized_deal_id = _text(deal_id, "deal_id", required=True)
    assert normalized_deal_id is not None
    daily_carry = _number(carry_cost_per_day, "carry_cost_per_day")
    if daily_carry < 0:
        raise ValueError("carry_cost_per_day cannot be negative")
    deposit_rate = _rate(deposit_credit_rate, "deposit_credit_rate")
    financing_weights = _financing_weights(financing_risk_weights)
    contingency_weights = _contingency_weights(contingency_haircuts)

    ranked: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    with _connect(db_path, config) as connection:
        rows = connection.execute(
            """
            SELECT * FROM disp_bids
            WHERE deal_id=?
            ORDER BY COALESCE(received_at, status_changed_at), bid_id
            """,
            (normalized_deal_id,),
        ).fetchall()
        for row in rows:
            bid = _bid_from_row(row)
            if bid["status"] == "withdrawn":
                excluded.append(
                    {
                        "bid_id": bid["bid_id"],
                        "status": "withdrawn",
                        "reason": "withdrawn bids are not currently actionable",
                    }
                )
                continue
            headline = float(bid["price"])
            effective = (
                float(bid["final_price"])
                if bid["final_price"] is not None
                else headline
            )
            unknown_field_notes: list[str] = []
            stated_deposit = (
                None if bid["deposit"] is None else float(bid["deposit"])
            )
            at_risk, at_risk_source = _deposit_at_risk(
                stated_deposit, bid["contingencies"]
            )
            deposit_source = (
                "unknown_convention"
                if stated_deposit is None
                else "recorded_bid_input"
            )
            if stated_deposit is None:
                unknown_field_notes.append(
                    "deposit is unknown; weakest deposit credit is applied using $0 at risk"
                )
            deposit_credit = at_risk * deposit_rate
            stated_dd_days = (
                None if bid["dd_days"] is None else int(bid["dd_days"])
            )
            dd_days_used = (
                DEFAULT_UNKNOWN_DD_DAYS
                if stated_dd_days is None
                else stated_dd_days
            )
            dd_source = (
                "unknown_convention"
                if stated_dd_days is None
                else "recorded_bid_input"
            )
            if stated_dd_days is None:
                unknown_field_notes.append(
                    f"dd_days is unknown; normalization uses the disclosed {DEFAULT_UNKNOWN_DD_DAYS}-day convention"
                )
            stated_closing_days = (
                None
                if bid["closing_days"] is None
                else int(bid["closing_days"])
            )
            closing_days_used = (
                DEFAULT_UNKNOWN_CLOSING_DAYS
                if stated_closing_days is None
                else stated_closing_days
            )
            closing_source = (
                "unknown_convention"
                if stated_closing_days is None
                else "recorded_bid_input"
            )
            if stated_closing_days is None:
                unknown_field_notes.append(
                    f"closing_days is unknown; normalization uses the disclosed {DEFAULT_UNKNOWN_CLOSING_DAYS}-day convention"
                )
            dd_carry_haircut = dd_days_used * daily_carry
            closing_carry_haircut = closing_days_used * daily_carry
            financing_type, has_proof = _financing_terms(bid["financing"])
            selected_weights = financing_weights.get(financing_type, financing_weights["unknown"])
            proof_key = "with_proof" if has_proof else "without_proof"
            financing_rate = selected_weights[proof_key]
            financing_haircut = effective * financing_rate
            financing_source = (
                "unknown_convention"
                if bid["financing"] is None
                else "recorded_bid_input"
            )
            if bid["financing"] is None:
                unknown_field_notes.append(
                    "financing is unknown; the disclosed unknown/without-proof risk weight is applied"
                )

            contingency_components: list[dict[str, Any]] = []
            contingency_rate = 0.0
            contingency_names = _contingency_names(bid["contingencies"])
            contingency_source = "recorded_bid_input"
            if bid["contingencies"] is None:
                contingency_names = ["unknown"]
                contingency_source = "unknown_convention"
                unknown_field_notes.append(
                    "contingencies are unknown; one disclosed unknown-contingency haircut is applied"
                )
            for name in contingency_names:
                category = _contingency_category(name, contingency_weights)
                rate = contingency_weights.get(category, contingency_weights["unknown"])
                contingency_components.append(
                    {
                        "contingency": name,
                        "category": category,
                        "rate": rate,
                    }
                )
                contingency_rate += rate
            contingency_haircut = effective * contingency_rate
            if bid["received_at"] is None:
                unknown_field_notes.append(
                    "received_at is unknown; status_changed_at is the deterministic sort fallback"
                )
            retrade_change = effective - headline
            adjustments = [
                {
                    "kind": "retrade_price_change",
                    "amount": round(retrade_change, 2),
                    "formula": "effective_price - headline_price",
                    "inputs": {
                        "headline_price": headline,
                        "effective_price": effective,
                    },
                },
                {
                    # The kind names the economic fact being credited; the
                    # signed amount remains present even when the fact is zero.
                    "kind": "deposit_at_risk_credit",
                    "amount": round(deposit_credit, 2),
                    "formula": "deposit_at_risk * deposit_credit_rate",
                    "inputs": {
                        "stated_deposit": stated_deposit,
                        "deposit_at_risk": at_risk,
                        "deposit_at_risk_source": at_risk_source,
                        "deposit_credit_rate": deposit_rate,
                        "value_source": deposit_source,
                    },
                },
                {
                    "kind": "dd_carry_cost",
                    "amount": round(-dd_carry_haircut, 2),
                    "formula": "-(dd_days_used * carry_cost_per_day)",
                    "inputs": {
                        "stated_dd_days": stated_dd_days,
                        "dd_days_used": dd_days_used,
                        "carry_cost_per_day": daily_carry,
                        "value_source": dd_source,
                        "note": (
                            f"Unknown DD period uses the disclosed {DEFAULT_UNKNOWN_DD_DAYS}-day convention."
                            if stated_dd_days is None
                            else "DD period comes from the recorded bid."
                        ),
                    },
                },
                {
                    "kind": "closing_carry_cost",
                    "amount": round(-closing_carry_haircut, 2),
                    "formula": "-(closing_days_used * carry_cost_per_day)",
                    "inputs": {
                        "stated_closing_days": stated_closing_days,
                        "closing_days_used": closing_days_used,
                        "carry_cost_per_day": daily_carry,
                        "value_source": closing_source,
                        "note": (
                            f"Unknown closing period uses the disclosed {DEFAULT_UNKNOWN_CLOSING_DAYS}-day convention."
                            if stated_closing_days is None
                            else "Closing period comes from the recorded bid."
                        ),
                    },
                },
                {
                    "kind": "financing_risk_haircut",
                    "amount": round(-financing_haircut, 2),
                    "formula": "-(effective_price * selected_financing_risk_weight)",
                    "inputs": {
                        "financing_type": financing_type,
                        "proof": has_proof,
                        "proof_bucket": proof_key,
                        "selected_financing_risk_weight": financing_rate,
                        "value_source": financing_source,
                        "note": (
                            "Unknown financing uses the disclosed unknown/without-proof weight."
                            if bid["financing"] is None
                            else "Financing type and proof status come from the recorded bid."
                        ),
                    },
                },
                {
                    "kind": "contingency_haircut",
                    "amount": round(-contingency_haircut, 2),
                    "formula": "-(effective_price * sum(contingency_haircut_rates))",
                    "inputs": {
                        "total_contingency_haircut_rate": contingency_rate,
                        "components": contingency_components,
                        "value_source": contingency_source,
                        "note": (
                            "Unknown contingencies receive one disclosed unknown-category haircut."
                            if bid["contingencies"] is None
                            else "Contingencies come from the recorded bid; an empty list is treated as explicitly clean."
                        ),
                    },
                },
            ]
            adjusted = headline + sum(float(item["amount"]) for item in adjustments)
            bid.update(
                {
                    "headline_price": headline,
                    "effective_price": effective,
                    "adjusted_price": round(adjusted, 2),
                    "certainty_adjusted_price": round(adjusted, 2),
                    "adjustments": adjustments,
                    "total_adjustment": round(adjusted - headline, 2),
                    "unknown_field_notes": unknown_field_notes,
                    "dd_days_used": dd_days_used,
                    "closing_days_used": closing_days_used,
                    "received_at_sort_value": (
                        bid["received_at"] or bid["status_changed_at"]
                    ),
                }
            )
            ranked.append(bid)

    ranked.sort(
        key=lambda item: (
            -float(item["adjusted_price"]),
            -float(item["deposit"] or 0.0),
            int(item["dd_days_used"]),
            int(item["closing_days_used"]),
            str(item["received_at_sort_value"]),
            str(item["bid_id"]),
        )
    )
    for rank, bid in enumerate(ranked, start=1):
        bid["certainty_rank"] = rank

    return {
        "deal_id": normalized_deal_id,
        "status": "ok" if ranked else "empty",
        "ranked_bids": ranked,
        "bids": ranked,
        "excluded_bids": excluded,
        "weights": {
            "carry_cost_per_day": daily_carry,
            "deposit_credit_rate": deposit_rate,
            "unknown_deposit_at_risk": 0.0,
            "unknown_dd_days_default": DEFAULT_UNKNOWN_DD_DAYS,
            "unknown_closing_days_default": DEFAULT_UNKNOWN_CLOSING_DAYS,
            "financing_risk_weights": financing_weights,
            "contingency_haircuts": contingency_weights,
        },
        "formula": (
            "adjusted_price = headline_price + (effective_price - headline_price) "
            "+ deposit_at_risk * deposit_credit_rate "
            "- dd_days_used * carry_cost_per_day "
            "- closing_days_used * carry_cost_per_day "
            "- effective_price * financing_risk_weight "
            "- effective_price * sum(contingency_haircut_rates)"
        ),
        "conventions": [
            "This is a transparent screening comparison, not predicted proceeds or a valuation.",
            "A stated deposit is treated as at risk unless contingencies explicitly mark it refundable or supply an at-risk amount.",
            "An unknown deposit receives the weakest credit: $0 treated as at risk.",
            f"Unknown dd_days uses {DEFAULT_UNKNOWN_DD_DAYS} days and unknown closing_days uses {DEFAULT_UNKNOWN_CLOSING_DAYS} days; both carry-cost adjustments are shown separately.",
            "Financing proof changes the disclosed type-specific haircut; absent proof is assigned the without-proof weight.",
            "Unknown financing uses the disclosed unknown/without-proof haircut.",
            "Unknown contingencies receive one disclosed unknown haircut; rates add without a hidden cap.",
            "Unknown received_at values use status_changed_at only as a deterministic sort fallback.",
            "Withdrawn bids are disclosed separately and excluded from the actionable rank.",
        ],
    }


__all__ = [
    "BID_STATUSES",
    "DEFAULT_UNKNOWN_CLOSING_DAYS",
    "DEFAULT_UNKNOWN_DD_DAYS",
    "DEFAULT_CONTINGENCY_HAIRCUTS",
    "DEFAULT_FINANCING_RISK_WEIGHTS",
    "DISP_BIDS_SCHEMA_MIGRATION",
    "DISP_BIDS_SCHEMA_VERSION",
    "normalize_bids",
    "record_bid",
]
