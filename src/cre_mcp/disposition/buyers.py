"""Durable buyer universe and transparent, non-predictive fit matching.

The buyer table lives in the shared CRE cache database, but this module owns and
creates only ``disp_buyers``.  Bid history is read from ``disp_bids`` when that
table exists; it is never fabricated from buyer attributes.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig

BUYER_TYPES = frozenset(
    {"institutional", "private", "1031", "owner_user", "syndicator"}
)
NO_HISTORY_NOTE = (
    "no behavioral history yet — accrues via record_bid outcomes"
)
OBSERVED_HISTORY_NOTE = (
    "Observed bid outcomes only; no predictive behavioral score is inferred."
)

DISP_BUYERS_SCHEMA_VERSION = 2
DISP_BUYERS_SCHEMA_MIGRATION = (
    "v1 required both check-size bounds; v2 preserves rows while making each "
    "bound independently nullable for honest unknown buyer intelligence"
)
_TABLE_NAME = "disp_buyers"
_MIGRATION_TABLE_NAME = "disp_buyers_v2_migration"
_CHECK_SIZE_MAX_POINTS = 50.0
_UNKNOWN_CHECK_SIZE_CREDIT = 20.0

_CREATE_TABLE = """
CREATE TABLE {table_name} (
    buyer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    check_size_min REAL,
    check_size_max REAL,
    geographies TEXT NOT NULL DEFAULT '[]',
    asset_types TEXT NOT NULL DEFAULT '[]',
    financing_style TEXT,
    source TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    CHECK(type IN ('institutional', 'private', '1031', 'owner_user', 'syndicator')),
    CHECK(check_size_min IS NULL OR check_size_min >= 0),
    CHECK(check_size_max IS NULL OR check_size_max >= 0),
    CHECK(check_size_max IS NULL OR check_size_min IS NULL OR check_size_max >= check_size_min)
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_disp_buyers_type_size
    ON disp_buyers(type, check_size_min, check_size_max)
"""

_BUYER_COLUMNS = (
    "buyer_id, name, type, check_size_min, check_size_max, geographies, "
    "asset_types, financing_style, source, notes, created_at"
)


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
    """Create schema v2 or migrate the owned v1 table without global metadata.

    Schema state is identified from ``disp_buyers`` itself rather than the
    database-wide ``PRAGMA user_version``, because the cache database is shared
    with stores owned by other modules.  The migration is serialized and
    transactional, copies every v1 row, and recreates only this module's index.
    """

    connection.execute("BEGIN IMMEDIATE")
    schema_result = "v2_current"
    try:
        columns = connection.execute(
            "PRAGMA table_info(disp_buyers)"
        ).fetchall()
        if not columns:
            connection.execute(_CREATE_TABLE.format(table_name=_TABLE_NAME))
            schema_result = "v2_created"
        else:
            by_name = {str(column["name"]): column for column in columns}
            missing = {
                "check_size_min",
                "check_size_max",
            } - set(by_name)
            if missing:
                names = ", ".join(sorted(missing))
                raise RuntimeError(
                    f"disp_buyers has an unsupported schema; missing columns: {names}"
                )
            legacy_not_null = any(
                bool(by_name[name]["notnull"])
                for name in ("check_size_min", "check_size_max")
            )
            if legacy_not_null:
                connection.execute(
                    f"DROP TABLE IF EXISTS {_MIGRATION_TABLE_NAME}"
                )
                connection.execute(
                    _CREATE_TABLE.format(table_name=_MIGRATION_TABLE_NAME)
                )
                connection.execute(
                    f"INSERT INTO {_MIGRATION_TABLE_NAME} ({_BUYER_COLUMNS}) "
                    f"SELECT {_BUYER_COLUMNS} FROM {_TABLE_NAME}"
                )
                connection.execute("DROP INDEX IF EXISTS idx_disp_buyers_type_size")
                connection.execute(f"DROP TABLE {_TABLE_NAME}")
                connection.execute(
                    f"ALTER TABLE {_MIGRATION_TABLE_NAME} RENAME TO {_TABLE_NAME}"
                )
                schema_result = "v1_rows_preserved_and_migrated_to_v2"
        connection.execute(_CREATE_INDEX)
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
        return schema_result


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _clean_text(value: Any, label: str, *, required: bool = False) -> str | None:
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


def _optional_number(value: Any, label: str) -> float | None:
    """Validate a known numeric value while preserving honest unknowns."""

    if value is None:
        return None
    return _number(value, label)


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values: Sequence[Any] = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = value
    else:
        raise ValueError(f"{label} must be a string or sequence of strings")
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        cleaned = _clean_text(item, label, required=True)
        assert cleaned is not None
        folded = cleaned.casefold()
        if folded not in seen:
            result.append(cleaned)
            seen.add(folded)
    return result


def _json_list(raw: Any) -> list[str]:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _behavior(
    connection: sqlite3.Connection,
    buyer_id: str,
) -> dict[str, Any]:
    """Return observed counts only, preserving an explicit empty-history state."""

    row: sqlite3.Row | None = None
    if _table_exists(connection, "disp_bids"):
        columns = {
            str(column["name"])
            for column in connection.execute("PRAGMA table_info(disp_bids)").fetchall()
        }
        retrades = (
            "COALESCE(SUM(retrade_count), 0)"
            if "retrade_count" in columns
            else "COALESCE(SUM(CASE WHEN status='retraded' THEN 1 ELSE 0 END), 0)"
        )
        row = connection.execute(
            f"""
            SELECT COUNT(*) AS bids_made,
                   {retrades} AS retrades,
                   COALESCE(SUM(CASE WHEN status='closed' THEN 1 ELSE 0 END), 0) AS closes
            FROM disp_bids
            WHERE buyer_id=?
            """,
            (buyer_id,),
        ).fetchone()
    bids_made = int(row["bids_made"]) if row is not None else 0
    retrade_count = int(row["retrades"]) if row is not None else 0
    close_count = int(row["closes"]) if row is not None else 0
    empty = bids_made == 0
    return {
        "bids_made": bids_made,
        "retrades": retrade_count,
        "closes": close_count,
        "behavioral_history_status": "empty" if empty else "observed",
        "behavioral_score": None,
        "behavior_note": NO_HISTORY_NOTE if empty else OBSERVED_HISTORY_NOTE,
        "behavior_ledger": {
            "source": "disp_bids",
            "existing_pattern": (
                "cre_mcp.ledger quote_ledger/claim_ledger outcome ledgers"
            ),
            "read_only_aggregate": True,
            "persisted_buyer_counters": False,
        },
    }


def _buyer_from_row(
    row: sqlite3.Row,
    connection: sqlite3.Connection,
) -> dict[str, Any]:
    buyer = dict(row)
    buyer["geographies"] = _json_list(buyer["geographies"])
    buyer["asset_types"] = _json_list(buyer["asset_types"])
    buyer.update(_behavior(connection, str(buyer["buyer_id"])))
    return buyer


def record_buyer(
    buyer: Mapping[str, Any] | None = None,
    *,
    buyer_id: str | None = None,
    name: str | None = None,
    buyer_type: str | None = None,
    type: str | None = None,
    check_size_min: Any = None,
    check_size_max: Any = None,
    geographies: Any = None,
    asset_types: Any = None,
    financing_style: str | None = None,
    source: str | None = None,
    notes: str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Persist one buyer from a mapping or equivalent keyword fields.

    The function intentionally does not assign a behavioral score.  Observed bid,
    retrade, and close counts are derived from ``disp_bids`` at read time.
    """

    supplied = dict(buyer or {})

    def choose(keyword: Any, key: str, *aliases: str) -> Any:
        if keyword is not None:
            return keyword
        for candidate in (key, *aliases):
            if candidate in supplied:
                return supplied[candidate]
        return None

    normalized_id = _clean_text(
        choose(buyer_id, "buyer_id"), "buyer_id"
    ) or f"buyer_{uuid.uuid4().hex}"
    normalized_name = _clean_text(choose(name, "name"), "name", required=True)
    raw_type = choose(buyer_type or type, "type", "buyer_type")
    normalized_type = str(raw_type or "").strip().casefold().replace("-", "_")
    if normalized_type not in BUYER_TYPES:
        allowed = ", ".join(sorted(BUYER_TYPES))
        raise ValueError(f"type must be one of: {allowed}")
    minimum = _optional_number(
        choose(check_size_min, "check_size_min"), "check_size_min"
    )
    maximum = _optional_number(
        choose(check_size_max, "check_size_max"), "check_size_max"
    )
    if minimum is not None and minimum < 0:
        raise ValueError("check_size_min cannot be negative")
    if maximum is not None and maximum < 0:
        raise ValueError("check_size_max cannot be negative")
    if minimum is not None and maximum is not None and maximum < minimum:
        raise ValueError("check_size_max must be at least check_size_min")
    geography_values = _string_list(
        choose(geographies, "geographies"), "geographies"
    )
    asset_type_values = _string_list(
        choose(asset_types, "asset_types"), "asset_types"
    )
    normalized_financing = _clean_text(
        choose(financing_style, "financing_style"), "financing_style"
    )
    normalized_source = _clean_text(choose(source, "source"), "source")
    normalized_notes = _clean_text(choose(notes, "notes"), "notes")
    created_at = _clean_text(supplied.get("created_at"), "created_at") or _now()

    with _connect(db_path, config) as connection:
        try:
            connection.execute(
                """
                INSERT INTO disp_buyers(
                    buyer_id, name, type, check_size_min, check_size_max,
                    geographies, asset_types, financing_style, source, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_id,
                    normalized_name,
                    normalized_type,
                    minimum,
                    maximum,
                    json.dumps(geography_values, separators=(",", ":")),
                    json.dumps(asset_type_values, separators=(",", ":")),
                    normalized_financing,
                    normalized_source,
                    normalized_notes,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"buyer_id already exists: {normalized_id}") from exc
        row = connection.execute(
            "SELECT * FROM disp_buyers WHERE buyer_id=?", (normalized_id,)
        ).fetchone()
        assert row is not None
        return _buyer_from_row(row, connection)


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _geography_matches(market: str, preferences: list[str]) -> bool:
    market_slug = _slug(market)
    market_tokens = set(market_slug.split("_"))
    for preference in preferences:
        preference_slug = _slug(preference)
        if preference_slug in {"all", "any", "national", "nationwide", "united_states"}:
            return True
        preference_tokens = set(preference_slug.split("_"))
        if (
            preference_slug == market_slug
            or preference_slug in market_slug
            or market_slug in preference_slug
            or (preference_tokens and preference_tokens <= market_tokens)
        ):
            return True
    return False


def match_buyers(
    deal: Mapping[str, Any],
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Rank the recorded buyer universe against price, asset type, and market.

    Fit points are attribute matching only.  Observed behavior is shown beside
    the result but is not converted into a score or used to alter rank.
    """

    if not isinstance(deal, Mapping):
        raise ValueError("deal must be a mapping")
    price = _number(deal.get("price"), "deal.price")
    if price <= 0:
        raise ValueError("deal.price must be positive")
    deal_type = _clean_text(deal.get("type"), "deal.type", required=True)
    market = _clean_text(deal.get("market"), "deal.market", required=True)
    assert deal_type is not None and market is not None

    matches: list[dict[str, Any]] = []
    with _connect(db_path, config) as connection:
        rows = connection.execute(
            "SELECT * FROM disp_buyers ORDER BY created_at, buyer_id"
        ).fetchall()
        for row in rows:
            result = _buyer_from_row(row, connection)
            reasons: list[str] = []
            score = 0.0
            minimum_raw = result["check_size_min"]
            maximum_raw = result["check_size_max"]
            minimum = float(minimum_raw) if minimum_raw is not None else None
            maximum = float(maximum_raw) if maximum_raw is not None else None
            check_size_reason: str
            if minimum is None or maximum is None:
                check_size_fit = "fit_unknown"
                check_size_points = _UNKNOWN_CHECK_SIZE_CREDIT
                unknown_bounds = []
                if minimum is None:
                    unknown_bounds.append("minimum")
                if maximum is None:
                    unknown_bounds.append("maximum")
                unknown_label = " and ".join(unknown_bounds)
                check_size_reason = (
                    f"check size fit is unknown because the {unknown_label} bound "
                    f"is not recorded; neutral credit {_UNKNOWN_CHECK_SIZE_CREDIT:.0f}/"
                    f"{_CHECK_SIZE_MAX_POINTS:.0f} (not assumed fit)"
                )
            elif minimum <= price <= maximum:
                check_size_fit = "fit"
                check_size_points = _CHECK_SIZE_MAX_POINTS
                check_size_reason = (
                    f"price ${price:,.0f} is within the ${minimum:,.0f}–${maximum:,.0f} check-size range"
                )
            elif price < minimum:
                proximity = price / minimum if minimum else 1.0
                check_size_fit = "no_fit"
                check_size_points = round(
                    20.0 * max(0.0, min(proximity, 1.0)), 6
                )
                check_size_reason = (
                    f"price ${price:,.0f} is below the ${minimum:,.0f} minimum check size"
                )
            else:
                assert maximum is not None
                proximity = maximum / price if price else 0.0
                check_size_fit = "no_fit"
                check_size_points = round(
                    20.0 * max(0.0, min(proximity, 1.0)), 6
                )
                check_size_reason = (
                    f"price ${price:,.0f} exceeds the ${maximum:,.0f} maximum check size"
                )
            score += check_size_points
            reasons.append(check_size_reason)

            preferences = result["asset_types"]
            asset_fit = not preferences or _slug(deal_type) in {
                _slug(value) for value in preferences
            }
            if not preferences:
                asset_points = 10.0
                asset_status = "fit_unknown"
                asset_reason = (
                    "asset-type preference is unrecorded (neutral, not assumed fit)"
                )
            elif asset_fit:
                asset_points = 25.0
                asset_status = "fit"
                asset_reason = f"asset type {deal_type!r} matches recorded strategy"
            else:
                asset_points = 0.0
                asset_status = "no_fit"
                asset_reason = f"asset type {deal_type!r} is outside recorded strategy"
            score += asset_points
            reasons.append(asset_reason)

            geographies = result["geographies"]
            geography_fit = not geographies or _geography_matches(market, geographies)
            if not geographies:
                geography_points = 10.0
                geography_status = "fit_unknown"
                geography_reason = (
                    "geography preference is unrecorded (neutral, not assumed fit)"
                )
            elif geography_fit:
                geography_points = 25.0
                geography_status = "fit"
                geography_reason = f"market {market!r} matches recorded geography"
            else:
                geography_points = 0.0
                geography_status = "no_fit"
                geography_reason = f"market {market!r} is outside recorded geography"
            score += geography_points
            reasons.append(geography_reason)

            if check_size_fit == "fit_unknown" and asset_fit and geography_fit:
                aggregate_fit_status = "fit_unknown"
            elif check_size_fit == "fit" and asset_fit and geography_fit:
                aggregate_fit_status = "fit"
            else:
                aggregate_fit_status = "partial_fit"

            result.update(
                {
                    "fit_score": round(score, 6),
                    "fit_score_max": 100.0,
                    "fit_status": aggregate_fit_status,
                    "check_size_fit": check_size_fit,
                    "fit_dimensions": {
                        "check_size": {
                            "status": check_size_fit,
                            "points": check_size_points,
                            "max_points": _CHECK_SIZE_MAX_POINTS,
                            "reason": check_size_reason,
                        },
                        "asset_type": {
                            "status": asset_status,
                            "points": asset_points,
                            "max_points": 25.0,
                            "reason": asset_reason,
                        },
                        "geography": {
                            "status": geography_status,
                            "points": geography_points,
                            "max_points": 25.0,
                            "reason": geography_reason,
                        },
                    },
                    "fit_reasons": reasons,
                    "behavior_used_in_fit_score": False,
                }
            )
            matches.append(result)

    matches.sort(
        key=lambda item: (-float(item["fit_score"]), str(item["name"]).casefold())
    )
    for rank, result in enumerate(matches, start=1):
        result["fit_rank"] = rank
    return {
        "deal": {"price": price, "type": deal_type, "market": market},
        "buyer_count": len(matches),
        "matches": matches,
        "ranked_buyers": matches,
        "fit_rubric": {
            "check_size": _CHECK_SIZE_MAX_POINTS,
            "unknown_check_size_neutral_credit": _UNKNOWN_CHECK_SIZE_CREDIT,
            "check_size_unknown_neutral_credit": _UNKNOWN_CHECK_SIZE_CREDIT,
            "check_size_unknown_status": "fit_unknown",
            "check_size_unknown_convention": (
                "If either check-size bound is unknown, award neutral 20/50 credit; "
                "never infer no-fit or full fit from a partial or absent range."
            ),
            "asset_type": 25.0,
            "geography": 25.0,
            "unrecorded_preference_neutral_credit": 10.0,
            "behavioral_history_weight": 0.0,
        },
        "behavior_convention": (
            "Only recorded disp_bids outcomes populate bids_made, retrades, and closes; "
            "behavior never changes the attribute-fit rank and no predictive score is fabricated."
        ),
        "behavior_ledger": {
            "source": "disp_bids",
            "existing_pattern": (
                "cre_mcp.ledger quote_ledger/claim_ledger outcome ledgers"
            ),
            "read_only_aggregate": True,
            "persisted_buyer_counters": False,
        },
    }


__all__ = [
    "BUYER_TYPES",
    "DISP_BUYERS_SCHEMA_MIGRATION",
    "DISP_BUYERS_SCHEMA_VERSION",
    "NO_HISTORY_NOTE",
    "match_buyers",
    "record_buyer",
]
