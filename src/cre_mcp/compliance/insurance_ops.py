"""Persist structured insurance inputs and surface renewal operations signals.

The table is an owner-entered structured-input v1 record. It is not an insurer
or broker feed, a bound-coverage record, or a prediction of renewal action.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any

from cre_mcp.config import CreConfig


CLAIMS_FREQUENCY_CONVENTION = (
    "Elevated-frequency triage signal when at least 2 stored claims with loss dates "
    "fall in the 1,095 days ending as_of. This is an internal convention, not a "
    "carrier underwriting rule or nonrenewal prediction."
)
CARRIER_CONCENTRATION_CONVENTION = (
    "Carrier premium concentration is flagged when one carrier represents at least "
    "50% of premium cents for policies unexpired as_of. It measures entered premium, "
    "not exposure, limits, carrier solvency, or market capacity."
)
STRUCTURED_INPUT_LIMIT = (
    "Structured-input v1 only; obtain current policy documents and insurer/broker "
    "loss runs. Broker/carrier feeds are not connected."
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ins_policies (
    asset TEXT NOT NULL,
    carrier TEXT NOT NULL,
    line TEXT NOT NULL,
    premium_cents INTEGER NOT NULL,
    expiry TEXT NOT NULL,
    claims_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY(asset, carrier, line),
    CHECK(premium_cents >= 0)
);
CREATE INDEX IF NOT EXISTS idx_ins_policies_expiry
    ON ins_policies(expiry, asset, carrier, line);
"""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if str(number) != str(value).strip() and not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def _date(value: Any, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _optional_date(value: Any, name: str) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _date(value, name).isoformat()


def _normalize_claim(claim: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(claim, Mapping):
        raise TypeError("claim must be a mapping")
    normalized = dict(claim)
    raw_loss_date = claim.get(
        "loss_date", claim.get("date", claim.get("occurred_on"))
    )
    normalized["loss_date"] = _optional_date(raw_loss_date, "claim.loss_date")

    amount_key = next(
        (key for key in ("incurred_cents", "amount_cents", "paid_cents") if key in claim),
        None,
    )
    if amount_key is not None and claim.get(amount_key) is not None:
        normalized[amount_key] = _integer(claim.get(amount_key), f"claim.{amount_key}")
    if "status" in normalized and normalized["status"] is not None:
        normalized["status"] = _text(str(normalized["status"]), "claim.status")
    try:
        json.dumps(normalized, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("claim values must be JSON serializable") from exc
    return normalized


def _normalize_claims(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("claims must be a sequence of mappings or null")
    return [_normalize_claim(claim) for claim in value]


class InsuranceOpsStore:
    """Own only the ``ins_policies`` table in the configured SQLite database."""

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

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(_SCHEMA)
        return connection

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["claims"] = json.loads(result["claims_json"])
        return result

    def record_policy(
        self,
        asset: str | Mapping[str, Any],
        carrier: str | None = None,
        line: str | None = None,
        premium_cents: int | None = None,
        expiry: Any = None,
        claims: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Upsert a policy identity; omitted claims preserve an existing loss history."""

        if isinstance(asset, Mapping):
            policy = asset
            raw_asset = policy.get("asset")
            carrier = policy.get("carrier")
            line = policy.get("line")
            premium_cents = policy.get("premium_cents")
            expiry = policy.get("expiry")
            if "claims" in policy:
                claims = policy.get("claims")
            elif "claims_json" in policy:
                raw_claims = policy.get("claims_json")
                if isinstance(raw_claims, str):
                    try:
                        claims = json.loads(raw_claims)
                    except json.JSONDecodeError as exc:
                        raise ValueError("claims_json must encode a JSON list") from exc
                else:
                    claims = raw_claims
            asset = raw_asset

        normalized_asset = _text(asset, "asset")
        normalized_carrier = _text(carrier, "carrier")
        normalized_line = _text(line, "line")
        normalized_premium = _integer(premium_cents, "premium_cents")
        normalized_expiry = _date(expiry, "expiry").isoformat()
        normalized_claims = _normalize_claims(claims) if claims is not None else None

        with self._connect() as connection:
            current = connection.execute(
                "SELECT claims_json FROM ins_policies WHERE asset=? AND carrier=? AND line=?",
                (normalized_asset, normalized_carrier, normalized_line),
            ).fetchone()
            claims_json = (
                json.dumps(normalized_claims, sort_keys=True, separators=(",", ":"))
                if normalized_claims is not None
                else (current["claims_json"] if current is not None else "[]")
            )
            connection.execute(
                """
                INSERT INTO ins_policies(
                    asset, carrier, line, premium_cents, expiry, claims_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset, carrier, line) DO UPDATE SET
                    premium_cents=excluded.premium_cents,
                    expiry=excluded.expiry,
                    claims_json=excluded.claims_json
                """,
                (
                    normalized_asset,
                    normalized_carrier,
                    normalized_line,
                    normalized_premium,
                    normalized_expiry,
                    claims_json,
                ),
            )
            row = connection.execute(
                "SELECT * FROM ins_policies WHERE asset=? AND carrier=? AND line=?",
                (normalized_asset, normalized_carrier, normalized_line),
            ).fetchone()
        result = self._row(row)
        result["input_status"] = STRUCTURED_INPUT_LIMIT
        return result

    def record_claim(
        self,
        asset: str,
        carrier: str,
        line: str,
        claim: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one structured claim to an existing policy."""

        normalized_asset = _text(asset, "asset")
        normalized_carrier = _text(carrier, "carrier")
        normalized_line = _text(line, "line")
        normalized_claim = _normalize_claim(claim)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ins_policies WHERE asset=? AND carrier=? AND line=?",
                (normalized_asset, normalized_carrier, normalized_line),
            ).fetchone()
            if row is None:
                raise KeyError(
                    f"policy not found for {normalized_asset}/{normalized_carrier}/{normalized_line}"
                )
            claims = json.loads(row["claims_json"])
            claims.append(normalized_claim)
            connection.execute(
                """
                UPDATE ins_policies SET claims_json=?
                WHERE asset=? AND carrier=? AND line=?
                """,
                (
                    json.dumps(claims, sort_keys=True, separators=(",", ":")),
                    normalized_asset,
                    normalized_carrier,
                    normalized_line,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM ins_policies WHERE asset=? AND carrier=? AND line=?",
                (normalized_asset, normalized_carrier, normalized_line),
            ).fetchone()
        result = self._row(updated)
        result["recorded_claim"] = normalized_claim
        result["input_status"] = STRUCTURED_INPUT_LIMIT
        return result

    def renewal_radar(
        self,
        days: int = 120,
        *,
        as_of: Any = None,
    ) -> dict[str, Any]:
        """Return policies expiring from ``as_of`` through the inclusive horizon."""

        horizon_days = _integer(days, "days")
        as_of_date = _date(as_of, "as_of") if as_of is not None else date.today()
        horizon = as_of_date + timedelta(days=horizon_days)
        with self._connect() as connection:
            renewal_rows = connection.execute(
                """
                SELECT * FROM ins_policies
                WHERE expiry >= ? AND expiry <= ?
                ORDER BY expiry, asset COLLATE NOCASE, line COLLATE NOCASE, carrier COLLATE NOCASE
                """,
                (as_of_date.isoformat(), horizon.isoformat()),
            ).fetchall()
            active_rows = connection.execute(
                """
                SELECT * FROM ins_policies WHERE expiry >= ?
                ORDER BY carrier COLLATE NOCASE, asset COLLATE NOCASE, line COLLATE NOCASE
                """,
                (as_of_date.isoformat(),),
            ).fetchall()

        renewals: list[dict[str, Any]] = []
        for row in renewal_rows:
            policy = self._row(row)
            expiry_date = date.fromisoformat(policy["expiry"])
            loss_run = _loss_run_summary(policy["claims"], as_of_date)
            policy["days_to_expiry"] = (expiry_date - as_of_date).days
            policy["loss_run_summary"] = loss_run
            policy["nonrenewal_risk_note"] = _nonrenewal_note(loss_run)
            renewals.append(policy)

        concentration = _carrier_concentration(active_rows)
        return {
            "as_of": as_of_date.isoformat(),
            "days": horizon_days,
            "window_end": horizon.isoformat(),
            "window_convention": "expiry is between as_of and window_end, inclusive",
            "renewal_count": len(renewals),
            "renewals": renewals,
            "policies": renewals,
            "claims_frequency_convention": CLAIMS_FREQUENCY_CONVENTION,
            "carrier_concentration": concentration,
            "carrier_concentration_note": concentration["note"],
            "input_status": STRUCTURED_INPUT_LIMIT,
        }


def _claim_amount(claim: Mapping[str, Any]) -> int:
    for key in ("incurred_cents", "amount_cents", "paid_cents"):
        value = claim.get(key)
        if value is not None:
            return _integer(value, f"claim.{key}")
    return 0


def _loss_run_summary(claims: Sequence[Mapping[str, Any]], as_of: date) -> dict[str, Any]:
    window_start = as_of - timedelta(days=1095)
    dated: list[tuple[date, Mapping[str, Any]]] = []
    undated = 0
    for claim in claims:
        raw_date = claim.get("loss_date")
        if raw_date is None:
            undated += 1
            continue
        dated.append((_date(raw_date, "claim.loss_date"), claim))
    recent = [claim for loss_date, claim in dated if window_start <= loss_date <= as_of]
    open_claims = sum(
        str(claim.get("status", "")).strip().casefold()
        not in {"", "closed", "resolved", "settled", "denied"}
        for claim in claims
    )
    recent_count = len(recent)
    if recent_count >= 2:
        frequency_signal = "ELEVATED"
    elif not dated and undated:
        frequency_signal = "UNKNOWN"
    else:
        frequency_signal = "NO_ELEVATED_SIGNAL"
    return {
        "stored_claim_count": len(claims),
        "total_incurred_or_amount_cents": sum(_claim_amount(claim) for claim in claims),
        "open_claim_count": open_claims,
        "dated_claims_in_trailing_1095_days": recent_count,
        "undated_claim_count": undated,
        "most_recent_loss_date": max((item[0] for item in dated), default=None).isoformat()
        if dated
        else None,
        "frequency_signal": frequency_signal,
        "convention": CLAIMS_FREQUENCY_CONVENTION,
        "source_limit": "stored structured claims; not a verified insurer loss run",
    }


def _nonrenewal_note(loss_run: Mapping[str, Any]) -> str:
    signal = loss_run["frequency_signal"]
    if signal == "ELEVATED":
        return (
            "Internal elevated-frequency signal: request verified loss runs and broker "
            "renewal strategy early. This does not predict carrier nonrenewal."
        )
    if signal == "UNKNOWN":
        return (
            "Claim frequency is UNKNOWN because stored claims lack loss dates; obtain a "
            "verified loss run. No carrier action is inferred."
        )
    return (
        "No elevated frequency signal under the stated convention; this is not assurance "
        "of renewal and does not replace broker/carrier underwriting review."
    )


def _carrier_concentration(rows: Sequence[sqlite3.Row]) -> dict[str, Any]:
    by_carrier: dict[str, int] = {}
    for row in rows:
        carrier = str(row["carrier"])
        by_carrier[carrier] = by_carrier.get(carrier, 0) + int(row["premium_cents"])
    total = sum(by_carrier.values())
    shares = [
        {
            "carrier": carrier,
            "premium_cents": premium,
            "premium_share": round(premium / total, 6) if total else None,
            "flagged": premium / total >= 0.5 if total else None,
        }
        for carrier, premium in sorted(
            by_carrier.items(), key=lambda item: (-item[1], item[0].casefold())
        )
    ]
    flagged = [item["carrier"] for item in shares if item["flagged"]]
    if not rows:
        note = "UNKNOWN — no policies unexpired as_of are stored."
    elif total == 0:
        note = "UNKNOWN — active entered premium totals zero, so premium shares cannot be computed."
    elif flagged:
        note = (
            f"Premium concentration convention flagged: {', '.join(flagged)} represents "
            "at least 50% of entered premium cents."
        )
    else:
        note = "No carrier reaches the 50% entered-premium concentration convention."
    return {
        "active_policy_count": len(rows),
        "active_premium_cents": total,
        "by_carrier": shares,
        "flagged_carriers": flagged,
        "note": note,
        "convention": CARRIER_CONCENTRATION_CONVENTION,
    }


def record_policy(
    asset: str | Mapping[str, Any],
    carrier: str | None = None,
    line: str | None = None,
    premium_cents: int | None = None,
    expiry: Any = None,
    claims: Sequence[Mapping[str, Any]] | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    return InsuranceOpsStore(db_path, config=config).record_policy(
        asset, carrier, line, premium_cents, expiry, claims
    )


def record_claim(
    asset: str,
    carrier: str,
    line: str,
    claim: Mapping[str, Any],
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    return InsuranceOpsStore(db_path, config=config).record_claim(
        asset, carrier, line, claim
    )


def renewal_radar(
    days: int = 120,
    *,
    as_of: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    return InsuranceOpsStore(db_path, config=config).renewal_radar(days, as_of=as_of)


__all__ = [
    "CARRIER_CONCENTRATION_CONVENTION",
    "CLAIMS_FREQUENCY_CONVENTION",
    "InsuranceOpsStore",
    "STRUCTURED_INPUT_LIMIT",
    "record_claim",
    "record_policy",
    "renewal_radar",
]
