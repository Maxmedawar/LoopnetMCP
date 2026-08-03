"""Durable lender-appetite profiles and transparent attribute-fit ranking."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig


DEFAULT_STALE_AFTER_DAYS = 180
EXECUTION_HISTORY_NOTE = (
    "Appetite fit is not execution history. Review lender_track_record for observed "
    "quotes, retrades, responsiveness, and closes before selecting a lender."
)

_PROFILE_KEYS = frozenset(
    {
        "name",
        "type",
        "lender_type",
        "geographies",
        "asset_types",
        "size_min",
        "size_min_cents",
        "loan_size_min_cents",
        "size_max",
        "size_max_cents",
        "loan_size_max_cents",
        "leverage_max",
        "max_leverage",
        "max_ltv",
        "ltv_max",
        "rate_context",
        "last_confirmed",
        "confirmed_at",
        "source",
        "source_label",
    }
)
_DEAL_KEYS = frozenset(
    {
        "deal",
        "deal_id",
        "name",
        "loan_amount_cents",
        "size_cents",
        "requested_loan_cents",
        "debt_cents",
        "geography",
        "geographies",
        "market",
        "state",
        "asset_type",
        "type",
        "leverage",
        "ltv",
        "leverage_pct",
        "rate_context",
        "index",
        "term_years",
        "recourse",
    }
)


def _resolve_db_path(
    db_path: str | Path | CreConfig | None,
    config: CreConfig | None,
) -> Path:
    if isinstance(db_path, CreConfig):
        resolved = db_path.cache_db_path
    else:
        resolved = db_path or (config or CreConfig()).cache_db_path
    return Path(resolved).expanduser()


@contextmanager
def _connection(
    db_path: str | Path | CreConfig | None,
    config: CreConfig | None,
) -> Iterator[sqlite3.Connection]:
    path = _resolve_db_path(db_path, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS fo_lenders (
            lender_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            type TEXT NOT NULL,
            geographies TEXT NOT NULL DEFAULT '[]',
            asset_types TEXT NOT NULL DEFAULT '[]',
            size_min INTEGER,
            size_max INTEGER,
            leverage_max REAL,
            rate_context TEXT,
            last_confirmed TEXT,
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(length(trim(name)) > 0),
            CHECK(length(trim(type)) > 0),
            CHECK(size_min IS NULL OR size_min >= 0),
            CHECK(size_max IS NULL OR size_max >= 0),
            CHECK(size_max IS NULL OR size_min IS NULL OR size_max >= size_min),
            CHECK(leverage_max IS NULL OR (leverage_max >= 0 AND leverage_max <= 1))
        );
        CREATE INDEX IF NOT EXISTS idx_fo_lenders_appetite
            ON fo_lenders(type, size_min, size_max, leverage_max);
        CREATE INDEX IF NOT EXISTS idx_fo_lenders_confirmed
            ON fo_lenders(last_confirmed, name);
        """
    )
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _text(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        if nullable:
            return None
        raise ValueError(f"{label} cannot be blank")
    return normalized


def _cents(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer number of cents")
    if value < 0:
        raise ValueError(f"{label} must be nonnegative")
    return value


def _optional_cents(value: Any, label: str) -> int | None:
    return None if value is None else _cents(value, label)


def _leverage(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a decimal or percentage")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a decimal or percentage") from exc
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    if result > 1:
        result /= Decimal(100)
    if result < 0 or result > 1:
        raise ValueError(f"{label} must be between 0 and 1 (or 0 and 100 percent)")
    return float(result)


def _optional_leverage(value: Any, label: str) -> float | None:
    return None if value is None else _leverage(value, label)


def _as_date(value: Any, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{label} cannot be blank")
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO date or datetime") from exc


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
        normalized = _text(item, label)
        assert normalized is not None
        key = normalized.casefold()
        if key not in seen:
            result.append(normalized)
            seen.add(key)
    return result


def _json_list(value: Any) -> list[str]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in decoded] if isinstance(decoded, list) else []


def _unknown(
    value: Mapping[str, Any], allowed: frozenset[str], *, path: str
) -> tuple[list[str], list[str]]:
    raw = [str(key) for key in value if not isinstance(key, str) or key not in allowed]
    return sorted(set(raw)), sorted({f"{path}.{key}" for key in raw})


def _choose(
    explicit: Any,
    supplied: Mapping[str, Any],
    *keys: str,
) -> Any:
    if explicit is not None:
        return explicit
    for key in keys:
        if key in supplied:
            return supplied[key]
    return None


def _row_result(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["geographies"] = _json_list(result["geographies"])
    result["asset_types"] = _json_list(result["asset_types"])
    result["size_min_cents"] = result["size_min"]
    result["size_max_cents"] = result["size_max"]
    result["source_ref"] = {"table": "fo_lenders", "id": result["lender_id"]}
    return result


def record_lender_profile(
    profile_or_name: Mapping[str, Any] | str | None = None,
    type: str | None = None,
    geographies: Sequence[str] | str | None = None,
    asset_types: Sequence[str] | str | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    leverage_max: Any = None,
    rate_context: str | None = None,
    last_confirmed: Any = None,
    source: str | None = None,
    *,
    name: str | None = None,
    lender_type: str | None = None,
    size_min_cents: int | None = None,
    size_max_cents: int | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Create or refresh one lender profile without fabricating unknown appetite."""

    if isinstance(profile_or_name, Mapping):
        supplied = dict(profile_or_name)
        positional_name = None
    elif isinstance(profile_or_name, str):
        supplied = {}
        positional_name = profile_or_name
    elif profile_or_name is None:
        supplied = {}
        positional_name = None
    else:
        raise ValueError("profile_or_name must be a lender name or profile mapping")
    unrecognized, unrecognized_paths = _unknown(
        supplied, _PROFILE_KEYS, path="profile"
    )

    normalized_name = _text(
        _choose(name or positional_name, supplied, "name"), "name"
    )
    raw_type = _choose(lender_type or type, supplied, "type", "lender_type")
    normalized_type = _text(raw_type, "type")
    minimum = _optional_cents(
        _choose(
            size_min_cents if size_min_cents is not None else size_min,
            supplied,
            "size_min",
            "size_min_cents",
            "loan_size_min_cents",
        ),
        "size_min",
    )
    maximum = _optional_cents(
        _choose(
            size_max_cents if size_max_cents is not None else size_max,
            supplied,
            "size_max",
            "size_max_cents",
            "loan_size_max_cents",
        ),
        "size_max",
    )
    if minimum is not None and maximum is not None and maximum < minimum:
        raise ValueError("size_max must be at least size_min")
    geography_values = _string_list(
        _choose(geographies, supplied, "geographies"), "geographies"
    )
    asset_values = _string_list(
        _choose(asset_types, supplied, "asset_types"), "asset_types"
    )
    maximum_leverage = _optional_leverage(
        _choose(
            leverage_max,
            supplied,
            "leverage_max",
            "max_leverage",
            "max_ltv",
            "ltv_max",
        ),
        "leverage_max",
    )
    normalized_rate = _text(
        _choose(rate_context, supplied, "rate_context"),
        "rate_context",
        nullable=True,
    )
    raw_confirmed = _choose(
        last_confirmed, supplied, "last_confirmed", "confirmed_at"
    )
    confirmed = (
        None if raw_confirmed is None else _as_date(raw_confirmed, "last_confirmed").isoformat()
    )
    normalized_source = _text(
        _choose(source, supplied, "source", "source_label"),
        "source",
        nullable=True,
    )
    now = datetime.now(UTC).isoformat()

    with _connection(db_path, config) as connection:
        existing = connection.execute(
            "SELECT lender_id, created_at FROM fo_lenders WHERE name=? COLLATE NOCASE",
            (normalized_name,),
        ).fetchone()
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO fo_lenders(
                    name, type, geographies, asset_types, size_min, size_max,
                    leverage_max, rate_context, last_confirmed, source,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_name,
                    normalized_type,
                    json.dumps(geography_values, separators=(",", ":")),
                    json.dumps(asset_values, separators=(",", ":")),
                    minimum,
                    maximum,
                    maximum_leverage,
                    normalized_rate,
                    confirmed,
                    normalized_source,
                    now,
                    now,
                ),
            )
            lender_id = int(cursor.lastrowid)
            status = "created"
        else:
            lender_id = int(existing["lender_id"])
            connection.execute(
                """
                UPDATE fo_lenders
                SET name=?, type=?, geographies=?, asset_types=?, size_min=?,
                    size_max=?, leverage_max=?, rate_context=?, last_confirmed=?,
                    source=?, updated_at=?
                WHERE lender_id=?
                """,
                (
                    normalized_name,
                    normalized_type,
                    json.dumps(geography_values, separators=(",", ":")),
                    json.dumps(asset_values, separators=(",", ":")),
                    minimum,
                    maximum,
                    maximum_leverage,
                    normalized_rate,
                    confirmed,
                    normalized_source,
                    now,
                    lender_id,
                ),
            )
            status = "updated"
        row = connection.execute(
            "SELECT * FROM fo_lenders WHERE lender_id=?", (lender_id,)
        ).fetchone()
        assert row is not None
        result = _row_result(row)
    result.update(
        {
            "record_status": status,
            "source_warning": (
                None
                if normalized_source is not None
                else "source is not recorded; verify this appetite directly with the lender"
            ),
            "unrecognized_inputs": unrecognized,
            "unrecognized_input_paths": unrecognized_paths,
        }
    )
    return result


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _geography_matches(deal_values: list[str], lender_values: list[str]) -> bool:
    national = {"all", "any", "national", "nationwide", "united_states", "us", "usa"}
    for lender_value in lender_values:
        lender_slug = _slug(lender_value)
        if lender_slug in national:
            return True
        lender_tokens = set(lender_slug.split("_"))
        for deal_value in deal_values:
            deal_slug = _slug(deal_value)
            deal_tokens = set(deal_slug.split("_"))
            if (
                lender_slug == deal_slug
                or lender_slug in deal_slug
                or deal_slug in lender_slug
                or (lender_tokens and lender_tokens <= deal_tokens)
                or (deal_tokens and deal_tokens <= lender_tokens)
            ):
                return True
    return False


def _asset_matches(deal_values: list[str], lender_values: list[str]) -> bool:
    broad = {"all", "any", "commercial_real_estate", "cre"}
    deal_slugs = {_slug(value) for value in deal_values}
    for lender_value in lender_values:
        lender_slug = _slug(lender_value)
        if lender_slug in broad or lender_slug in deal_slugs:
            return True
    return False


def _deal_list(deal: Mapping[str, Any], *keys: str) -> list[str]:
    result: list[str] = []
    for key in keys:
        if deal.get(key) is None:
            continue
        result.extend(_string_list(deal[key], f"deal.{key}"))
    seen: set[str] = set()
    unique: list[str] = []
    for value in result:
        folded = value.casefold()
        if folded not in seen:
            unique.append(value)
            seen.add(folded)
    return unique


def _deal_scalar(deal: Mapping[str, Any], label: str, *keys: str) -> Any:
    supplied = [(key, deal[key]) for key in keys if deal.get(key) is not None]
    if not supplied:
        return None
    first = supplied[0][1]
    if any(value != first for _, value in supplied[1:]):
        names = ", ".join(key for key, _ in supplied)
        raise ValueError(f"conflicting {label} inputs: {names}")
    return first


def _staleness(
    last_confirmed: str | None,
    as_of: date,
    stale_after_days: int,
) -> dict[str, Any]:
    if last_confirmed is None:
        return {
            "is_stale": None,
            "days_since_confirmed": None,
            "staleness_warning": (
                "Appetite freshness is unknown because last_confirmed is not recorded."
            ),
        }
    confirmed = _as_date(last_confirmed, "last_confirmed")
    age = (as_of - confirmed).days
    if age < 0:
        warning = (
            f"last_confirmed {confirmed.isoformat()} is {-age} days after as_of; "
            "verify the confirmation date"
        )
        is_stale: bool | None = None
    elif age > stale_after_days:
        warning = (
            f"Stale appetite: last confirmed {age} days ago, beyond the "
            f"{stale_after_days}-day convention; reconfirm directly with the lender."
        )
        is_stale = True
    else:
        warning = None
        is_stale = False
    return {
        "is_stale": is_stale,
        "days_since_confirmed": age,
        "staleness_warning": warning,
    }


def match_lenders(
    deal: Mapping[str, Any],
    *,
    as_of: Any = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Fit-rank recorded appetite; never treat the rank as execution evidence."""

    if not isinstance(deal, Mapping):
        raise ValueError("deal must be a mapping")
    if isinstance(stale_after_days, bool) or not isinstance(stale_after_days, int):
        raise ValueError("stale_after_days must be an integer")
    if stale_after_days < 0:
        raise ValueError("stale_after_days must be nonnegative")
    anchor = _as_date(as_of if as_of is not None else datetime.now(UTC).date(), "as_of")
    unrecognized, unrecognized_paths = _unknown(deal, _DEAL_KEYS, path="deal")

    raw_amount = _deal_scalar(
        deal,
        "loan amount",
        "loan_amount_cents",
        "size_cents",
        "requested_loan_cents",
        "debt_cents",
    )
    loan_amount = (
        None if raw_amount is None else _cents(raw_amount, "deal.loan_amount_cents")
    )
    geographies = _deal_list(deal, "geography", "geographies", "market", "state")
    asset_types = _deal_list(deal, "asset_type", "type")
    raw_leverage = _deal_scalar(
        deal, "leverage", "leverage", "ltv", "leverage_pct"
    )
    requested_leverage = (
        None if raw_leverage is None else _leverage(raw_leverage, "deal.leverage")
    )

    matches: list[dict[str, Any]] = []
    with _connection(db_path, config) as connection:
        rows = connection.execute(
            "SELECT * FROM fo_lenders ORDER BY name COLLATE NOCASE, lender_id"
        ).fetchall()
    for row in rows:
        lender = _row_result(row)
        reasons: list[str] = []
        dimensions: dict[str, dict[str, Any]] = {}

        minimum = lender["size_min"]
        maximum = lender["size_max"]
        if loan_amount is None:
            size_status, size_points = "deal_input_unknown", 20.0
            size_reason = "deal loan amount is unrecorded; size fit is unknown"
        elif minimum is None and maximum is None:
            size_status, size_points = "appetite_unknown", 20.0
            size_reason = "lender size minimum and maximum are unrecorded"
        elif minimum is not None and loan_amount < int(minimum):
            size_status, size_points = "no_fit", 0.0
            size_reason = (
                f"loan_amount_cents {loan_amount} is below recorded minimum {minimum}"
            )
        elif maximum is not None and loan_amount > int(maximum):
            size_status, size_points = "no_fit", 0.0
            size_reason = (
                f"loan_amount_cents {loan_amount} exceeds recorded maximum {maximum}"
            )
        elif minimum is None or maximum is None:
            size_status, size_points = "partial_appetite", 30.0
            size_reason = (
                "loan amount satisfies the recorded bound, but the other size bound "
                "is unknown"
            )
        else:
            size_status, size_points = "fit", 40.0
            size_reason = "loan amount is within the recorded lender size range"
        reasons.append(size_reason)
        dimensions["size"] = {
            "status": size_status,
            "points": size_points,
            "max_points": 40.0,
            "reason": size_reason,
        }

        lender_geographies = lender["geographies"]
        if not geographies:
            geography_status, geography_points = "deal_input_unknown", 12.5
            geography_reason = "deal geography is unrecorded; geography fit is unknown"
        elif not lender_geographies:
            geography_status, geography_points = "appetite_unknown", 12.5
            geography_reason = "lender geographies are unrecorded"
        elif _geography_matches(geographies, lender_geographies):
            geography_status, geography_points = "fit", 25.0
            geography_reason = "deal geography matches recorded lender appetite"
        else:
            geography_status, geography_points = "no_fit", 0.0
            geography_reason = "deal geography is outside recorded lender appetite"
        reasons.append(geography_reason)
        dimensions["geography"] = {
            "status": geography_status,
            "points": geography_points,
            "max_points": 25.0,
            "reason": geography_reason,
        }

        lender_assets = lender["asset_types"]
        if not asset_types:
            asset_status, asset_points = "deal_input_unknown", 12.5
            asset_reason = "deal asset type is unrecorded; asset fit is unknown"
        elif not lender_assets:
            asset_status, asset_points = "appetite_unknown", 12.5
            asset_reason = "lender asset types are unrecorded"
        elif _asset_matches(asset_types, lender_assets):
            asset_status, asset_points = "fit", 25.0
            asset_reason = "deal asset type matches recorded lender appetite"
        else:
            asset_status, asset_points = "no_fit", 0.0
            asset_reason = "deal asset type is outside recorded lender appetite"
        reasons.append(asset_reason)
        dimensions["asset_type"] = {
            "status": asset_status,
            "points": asset_points,
            "max_points": 25.0,
            "reason": asset_reason,
        }

        lender_leverage = lender["leverage_max"]
        if requested_leverage is None:
            leverage_status, leverage_points = "deal_input_unknown", 5.0
            leverage_reason = "deal leverage is unrecorded; leverage fit is unknown"
        elif lender_leverage is None:
            leverage_status, leverage_points = "appetite_unknown", 5.0
            leverage_reason = "lender leverage maximum is unrecorded"
        elif requested_leverage <= float(lender_leverage):
            leverage_status, leverage_points = "fit", 10.0
            leverage_reason = "requested leverage is within the recorded maximum"
        else:
            leverage_status, leverage_points = "no_fit", 0.0
            leverage_reason = "requested leverage exceeds the recorded maximum"
        reasons.append(leverage_reason)
        dimensions["leverage"] = {
            "status": leverage_status,
            "points": leverage_points,
            "max_points": 10.0,
            "reason": leverage_reason,
        }

        statuses = {str(item["status"]) for item in dimensions.values()}
        if statuses == {"fit"}:
            fit_status = "fit"
        elif "no_fit" in statuses:
            fit_status = "partial_fit"
        else:
            fit_status = "fit_unknown"
        lender.update(
            {
                "fit_score": round(sum(float(item["points"]) for item in dimensions.values()), 6),
                "fit_score_max": 100.0,
                "fit_status": fit_status,
                "fit_dimensions": dimensions,
                "reasons": reasons,
                "fit_reasons": reasons,
                "execution_history_note": EXECUTION_HISTORY_NOTE,
                **_staleness(lender["last_confirmed"], anchor, stale_after_days),
            }
        )
        matches.append(lender)

    matches.sort(
        key=lambda item: (-float(item["fit_score"]), str(item["name"]).casefold())
    )
    for rank, lender in enumerate(matches, start=1):
        lender["fit_rank"] = rank
    staleness_warnings = [
        {"lender_id": item["lender_id"], "name": item["name"], "warning": item["staleness_warning"]}
        for item in matches
        if item["staleness_warning"] is not None
    ]
    return {
        "as_of": anchor.isoformat(),
        "stale_after_days": stale_after_days,
        "deal": {
            "loan_amount_cents": loan_amount,
            "geographies": geographies,
            "asset_types": asset_types,
            "leverage": requested_leverage,
        },
        "lender_count": len(matches),
        "matches": matches,
        "ranked_lenders": matches,
        "staleness_warnings": staleness_warnings,
        "fit_rubric": {
            "size": 40.0,
            "geography": 25.0,
            "asset_type": 25.0,
            "leverage": 10.0,
            "unknown_values_receive_neutral_partial_credit": True,
        },
        "execution_history_note": EXECUTION_HISTORY_NOTE,
        "lender_track_record_pointer": "lender_track_record",
        "honesty_note": (
            "Rank reflects recorded appetite attributes only. It is not a quote, "
            "approval, rate indication, or prediction of execution."
        ),
        "unrecognized_inputs": unrecognized,
        "unrecognized_input_paths": unrecognized_paths,
    }


__all__ = [
    "DEFAULT_STALE_AFTER_DAYS",
    "EXECUTION_HISTORY_NOTE",
    "match_lenders",
    "record_lender_profile",
]
