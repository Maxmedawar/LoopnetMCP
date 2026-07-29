"""Provider-neutral signed event journal and entitlement projection."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig, ProviderPlanMapping
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.entitlements import (
    ACCOUNT_STATES,
    EntitlementStore,
    _iso,
    _parse,
)


OPERATOR_ONLY_ACCOUNT_STATES = frozenset(
    {"suspended", "under_review", "deletion_pending", "deleted"}
)
LIVE_GRANT_STATUSES = frozenset({"active", "overridden", "expiring"})
RESTRICTIVE_ACTIONS = frozenset(
    {
        "remove",
        "cancel",
        "pause",
        "payment_failed",
        "banned",
        "loss_of_paid_level",
        "restrict",
    }
)
PROVIDER_SOURCES = frozenset({"stripe", "skool"})
logger = logging.getLogger(__name__)


class WebhookSignatureError(ValueError):
    pass


class WebhookTimestampError(ValueError):
    pass


class ProviderValidationError(ValueError):
    """A signed envelope is structurally invalid or unsupported."""

    def __init__(
        self,
        reason_code: str,
        *,
        event_id: str | None = None,
        event_type: str | None = None,
        occurred_at: datetime | None = None,
        durable: bool = False,
    ) -> None:
        super().__init__("provider event is invalid")
        self.reason_code = reason_code
        self.event_id = event_id
        self.event_type = event_type
        self.occurred_at = occurred_at
        self.durable = durable


class ReconciliationValidationError(ValueError):
    pass


class ReconciliationConflictError(ValueError):
    pass


class ReconciliationNotFoundError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _secret_bytes(secret: SecretStr) -> bytes:
    return secret.get_secret_value().encode("utf-8")


def verify_hmac_signature(
    raw_body: bytes,
    signature_header: str,
    secret: SecretStr,
    *,
    now: datetime | None = None,
) -> int:
    """Verify timestamp + period + exact body bytes using every v1 candidate."""
    timestamps: list[str] = []
    candidates: list[str] = []
    for component in signature_header.split(","):
        name, separator, value = component.strip().partition("=")
        if not separator:
            continue
        if name == "t":
            timestamps.append(value)
        elif name == "v1":
            if (
                len(value) != 64
                or not value.isascii()
                or any(
                    character not in "0123456789abcdefABCDEF"
                    for character in value
                )
            ):
                continue
            candidates.append(value.lower())
    if len(timestamps) != 1 or not candidates:
        raise WebhookSignatureError("invalid webhook signature")
    if not timestamps[0].isascii() or not timestamps[0].isdecimal():
        raise WebhookSignatureError("invalid webhook signature")
    try:
        timestamp = int(timestamps[0])
    except ValueError as exc:
        raise WebhookSignatureError("invalid webhook signature") from exc
    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current_timestamp = current.timestamp()
    if (
        timestamp < current_timestamp - 300
        or timestamp > current_timestamp + 300
    ):
        raise WebhookTimestampError("webhook timestamp is outside tolerance")
    signed = str(timestamp).encode("ascii") + b"." + raw_body
    expected = hmac.new(
        _secret_bytes(secret),
        signed,
        hashlib.sha256,
    ).hexdigest()
    matched = False
    for candidate in candidates:
        matched = hmac.compare_digest(expected, candidate) or matched
    if not matched:
        raise WebhookSignatureError("invalid webhook signature")
    return timestamp


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProviderValidationError("duplicate_json_key")
        value[key] = item
    return value


def _reject_json_constant(_: str) -> Any:
    raise ProviderValidationError("malformed_json")


def decode_json_object(raw_body: bytes) -> dict[str, Any]:
    try:
        text = raw_body.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProviderValidationError("malformed_json") from exc
    if not isinstance(value, dict):
        raise ProviderValidationError("invalid_envelope")
    return value


def salvage_leading_identity(
    raw_body: bytes,
) -> tuple[str, str, datetime] | None:
    """Recover identity only from one complete leading object plus bad trailer."""
    try:
        text = raw_body.decode("utf-8")
        decoder = json.JSONDecoder(
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
        value, end = decoder.raw_decode(text)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ProviderValidationError,
        RecursionError,
    ):
        return None
    if not isinstance(value, dict) or not text[end:].strip():
        return None
    event_id = value.get("id")
    event_type = value.get("type")
    created = value.get("created")
    if (
        not isinstance(event_id, str)
        or not event_id.strip()
        or not isinstance(event_type, str)
        or not event_type.strip()
        or isinstance(created, bool)
        or not isinstance(created, int)
    ):
        return None
    try:
        occurred_at = datetime.fromtimestamp(created, UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return (event_id.strip(), event_type.strip(), occurred_at)


@dataclass(frozen=True)
class NormalizedProviderEvent:
    provider: str
    event_id: str
    event_type: str
    occurred_at: datetime
    action: str
    external_account_id: str | None = None
    external_object_id: str | None = None
    subscription_status: str | None = None
    mapping_keys: tuple[str, ...] = ()
    current_period_end: datetime | None = None

    def stored_data(self) -> dict[str, Any]:
        value = asdict(self)
        value["occurred_at"] = self.occurred_at.isoformat()
        value["current_period_end"] = (
            self.current_period_end.isoformat()
            if self.current_period_end is not None
            else None
        )
        value["mapping_keys"] = list(self.mapping_keys)
        return value

    @classmethod
    def from_stored_data(cls, value: dict[str, Any]) -> "NormalizedProviderEvent":
        occurred_at = datetime.fromisoformat(str(value["occurred_at"]))
        period_raw = value.get("current_period_end")
        return cls(
            provider=str(value["provider"]),
            event_id=str(value["event_id"]),
            event_type=str(value["event_type"]),
            occurred_at=occurred_at,
            action=str(value["action"]),
            external_account_id=value.get("external_account_id"),
            external_object_id=value.get("external_object_id"),
            subscription_status=value.get("subscription_status"),
            mapping_keys=tuple(value.get("mapping_keys") or ()),
            current_period_end=(
                datetime.fromisoformat(str(period_raw))
                if period_raw is not None
                else None
            ),
        )


@dataclass(frozen=True)
class SyncResult:
    event_db_id: int
    event_id: str
    outcome: str
    reason_code: str | None = None
    workspace_id: int | None = None

    def public(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "accepted": True,
            "outcome": self.outcome,
            "event": {"id": self.event_db_id},
        }
        if self.reason_code is not None:
            value["reason_code"] = self.reason_code
        return value


class ProviderSyncService:
    """One-connection journal, mapping, projection, and replay service."""

    def __init__(self, config: CreConfig) -> None:
        self.config = config
        self.db_path = Path(config.cache_db_path).expanduser()
        self.entitlements = EntitlementStore(self.db_path)
        OAuthSessionStore(self.db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _attempt(
        connection: sqlite3.Connection,
        event_db_id: int,
        outcome: str,
        reason_code: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO platform_provider_event_attempts(
                provider_event_id,outcome,reason_code,created_at
            ) VALUES (?,?,?,?)
            """,
            (event_db_id, outcome, reason_code, _iso(_now())),
        )

    @staticmethod
    def _set_event(
        connection: sqlite3.Connection,
        event_db_id: int,
        *,
        outcome: str,
        reason_code: str | None,
        workspace_id: int | None = None,
        replayed: bool = False,
    ) -> None:
        now = _iso(_now())
        connection.execute(
            """
            UPDATE platform_provider_events
            SET outcome=?,reason_code=?,
                workspace_id=COALESCE(?,workspace_id),
                replayed_at=CASE WHEN ? THEN ? ELSE replayed_at END,
                updated_at=?
            WHERE id=?
            """,
            (
                outcome,
                reason_code,
                workspace_id,
                int(replayed),
                now,
                now,
                event_db_id,
            ),
        )

    def _quarantine(
        self,
        connection: sqlite3.Connection,
        event_db_id: int,
        event: NormalizedProviderEvent,
        reason_code: str,
        *,
        workspace_id: int | None = None,
        replay: bool = False,
        attempt_outcome: str | None = None,
    ) -> SyncResult:
        self._set_event(
            connection,
            event_db_id,
            outcome="quarantined",
            reason_code=reason_code,
            workspace_id=workspace_id,
            replayed=replay,
        )
        if attempt_outcome is None:
            attempt_outcome = (
                "unmapped"
                if reason_code.startswith("unmapped_")
                or reason_code == "plan_not_found"
                else "quarantined"
            )
        self._attempt(connection, event_db_id, attempt_outcome, reason_code)
        logger.warning(
            "provider_event_quarantined",
            extra={
                "provider": event.provider,
                "provider_event_db_id": event_db_id,
                "reason_code": reason_code,
                "workspace_id": workspace_id,
            },
        )
        return SyncResult(
            event_db_id,
            event.event_id,
            "quarantined",
            reason_code,
            workspace_id,
        )

    def _resolve_subject(
        self,
        connection: sqlite3.Connection,
        event: NormalizedProviderEvent,
    ) -> tuple[int, int] | None:
        if event.external_account_id is None:
            return None
        rows = connection.execute(
            """
            SELECT workspace_id,subject_user_id
            FROM platform_external_accounts
            WHERE provider=? AND external_account_id=?
            """,
            (event.provider, event.external_account_id),
        ).fetchall()
        if len(rows) != 1 or rows[0]["subject_user_id"] is None:
            return None
        workspace_id = int(rows[0]["workspace_id"])
        subject_user_id = int(rows[0]["subject_user_id"])
        membership = connection.execute(
            """
            SELECT 1 FROM platform_memberships
            WHERE workspace_id=? AND user_id=?
            """,
            (workspace_id, subject_user_id),
        ).fetchone()
        if membership is None:
            return None
        return workspace_id, subject_user_id

    def _mapping(
        self,
        event: NormalizedProviderEvent,
    ) -> tuple[ProviderPlanMapping | None, str | None]:
        if event.provider == "stripe":
            configured = self.config.stripe_price_mappings
        else:
            configured = self.config.skool_tier_mappings
        if not event.mapping_keys:
            return None, "unmapped_plan"
        mappings: list[ProviderPlanMapping] = []
        for key in dict.fromkeys(event.mapping_keys):
            mapping = configured.get(key)
            if mapping is None:
                return None, "unmapped_plan"
            mappings.append(mapping)
        identities = {
            (mapping.plan_key, mapping.profile.value)
            for mapping in mappings
        }
        if len(identities) != 1:
            return None, "conflicting_plan_mapping"
        return mappings[0], None

    @staticmethod
    def _account_state(
        connection: sqlite3.Connection,
        workspace_id: int,
    ) -> str | None:
        row = connection.execute(
            "SELECT state FROM platform_accounts WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        return str(row["state"]) if row is not None else None

    @staticmethod
    def _last_journal_event_at(
        connection: sqlite3.Connection,
        event_db_id: int,
        event: NormalizedProviderEvent,
    ) -> datetime | None:
        """Return the latest canonical receipt for this provider object stream."""
        if event.external_object_id is None:
            return None
        rows = connection.execute(
            """
            SELECT normalized_data,occurred_at
            FROM platform_provider_events
            WHERE provider=? AND id<>?
            """,
            (event.provider, event_db_id),
        ).fetchall()
        matching: list[datetime] = []
        for row in rows:
            normalized = json.loads(str(row["normalized_data"]))
            if (
                normalized
                and normalized.get("external_object_id")
                == event.external_object_id
            ):
                matching.append(_parse(row["occurred_at"]))
        return max(matching) if matching else None

    @staticmethod
    def _live_grant_exists(
        connection: sqlite3.Connection,
        workspace_id: int,
        *,
        at: datetime,
    ) -> bool:
        rows = connection.execute(
            """
            SELECT status,starts_at,ends_at
            FROM platform_access_grants
            WHERE workspace_id=?
            """,
            (workspace_id,),
        ).fetchall()
        for row in rows:
            if str(row["status"]) not in LIVE_GRANT_STATUSES:
                continue
            starts_at = _parse(row["starts_at"])
            ends_at = _parse(row["ends_at"])
            if starts_at <= at and (ends_at is None or ends_at > at):
                return True
        return False

    @staticmethod
    def _subject_live_grant_exists(
        connection: sqlite3.Connection,
        workspace_id: int,
        subject_user_id: int,
        *,
        at: datetime,
    ) -> bool:
        rows = connection.execute(
            """
            SELECT source,subject_user_id,status,starts_at,ends_at
            FROM platform_access_grants
            WHERE workspace_id=?
              AND (
                  source NOT IN ('stripe','skool')
                  OR subject_user_id=?
              )
            """,
            (workspace_id, subject_user_id),
        ).fetchall()
        for row in rows:
            if str(row["status"]) not in LIVE_GRANT_STATUSES:
                continue
            starts_at = _parse(row["starts_at"])
            ends_at = _parse(row["ends_at"])
            if starts_at <= at and (ends_at is None or ends_at > at):
                return True
        return False

    @staticmethod
    def _revoke_subject_oauth_tx(
        connection: sqlite3.Connection,
        workspace_id: int,
        subject_user_id: int,
        *,
        at: datetime,
    ) -> None:
        workspace = connection.execute(
            "SELECT public_id FROM platform_workspaces WHERE id=?",
            (workspace_id,),
        ).fetchone()
        if workspace is None:
            raise ReconciliationValidationError("workspace_not_found")
        now = _iso(at)
        workspace_public_id = str(workspace["public_id"])
        connection.execute(
            """
            UPDATE platform_oauth_sessions
            SET revoked_at=COALESCE(revoked_at,?),updated_at=?
            WHERE workspace_id=? AND user_id=?
            """,
            (now, now, workspace_public_id, subject_user_id),
        )
        connection.execute(
            """
            UPDATE platform_oauth_codes
            SET consumed_at=COALESCE(consumed_at,?)
            WHERE workspace_id=? AND user_id=?
            """,
            (now, workspace_public_id, subject_user_id),
        )

    def _set_derived_account(
        self,
        connection: sqlite3.Connection,
        workspace_id: int,
        desired: str,
    ) -> None:
        if desired not in ACCOUNT_STATES:
            raise ValueError("invalid account transition")
        current = connection.execute(
            "SELECT state,reason FROM platform_accounts WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        reason = (
            current["reason"]
            if current is not None and str(current["state"]) == desired
            else None
        )
        self.entitlements._set_account_tx(
            connection,
            workspace_id,
            desired,
            reason,
        )

    @staticmethod
    def _find_subscription(
        connection: sqlite3.Connection,
        event: NormalizedProviderEvent,
        workspace_id: int,
    ) -> sqlite3.Row | None:
        if event.external_object_id is None:
            return None
        return connection.execute(
            """
            SELECT * FROM platform_subscriptions
            WHERE provider=? AND external_subscription_id=?
            """,
            (event.provider, event.external_object_id),
        ).fetchone()

    def _projection_tx(
        self,
        connection: sqlite3.Connection,
        event: NormalizedProviderEvent,
        event_db_id: int,
        workspace_id: int,
        subject_user_id: int,
        mapping: ProviderPlanMapping | None,
    ) -> str:
        subscription = self._find_subscription(connection, event, workspace_id)
        if event.action == "payment_failed" and subscription is None:
            raise ReconciliationValidationError("subscription_not_found")
        if subscription is not None and int(subscription["workspace_id"]) != workspace_id:
            raise ReconciliationValidationError("conflicting_mapping")

        external_ref = (
            str(subscription["external_subscription_id"])
            if event.action == "payment_failed"
            else event.external_object_id
        )
        if external_ref is None:
            raise ReconciliationValidationError("missing_external_object")
        grant = connection.execute(
            """
            SELECT * FROM platform_access_grants
            WHERE source=? AND external_ref=?
            """,
            (event.provider, external_ref),
        ).fetchone()
        if grant is not None and int(grant["workspace_id"]) != workspace_id:
            raise ReconciliationValidationError("conflicting_mapping")
        if (
            grant is not None
            and (
                grant["subject_user_id"] is None
                or int(grant["subject_user_id"]) != subject_user_id
            )
        ):
            raise ReconciliationValidationError("conflicting_mapping")

        last_event_at = (
            _parse(subscription["last_event_at"])
            if subscription is not None
            else None
        )
        journal_event_at = self._last_journal_event_at(
            connection,
            event_db_id,
            event,
        )
        if journal_event_at is not None and (
            last_event_at is None or journal_event_at > last_event_at
        ):
            last_event_at = journal_event_at
        if last_event_at is not None and event.occurred_at < last_event_at:
            return "stale"

        removal = event.action in RESTRICTIVE_ACTIONS
        if event.action == "payment_failed":
            plan_key = str(subscription["plan_key"])
            if grant is None:
                raise ReconciliationValidationError("subscription_not_found")
            if str(grant["status"]) in {"expired", "revoked"}:
                return "rejected"
            profile = Profile(str(grant["profile"]))
            subscription_status = "unpaid"
            grant_status = "revoked"
            period_end = _parse(subscription["current_period_end"])
        elif removal:
            if subscription is None and grant is None:
                return "no_provider_state"
            plan_key = (
                str(subscription["plan_key"])
                if subscription is not None
                else str(grant["plan_key"])
                if grant is not None
                else ""
            )
            profile = (
                Profile(str(grant["profile"]))
                if grant is not None
                else Profile.LOCAL_SCOUT
            )
            subscription_status = "canceled"
            grant_status = "revoked"
            period_end = (
                _parse(subscription["current_period_end"])
                if subscription is not None
                else None
            )
        else:
            if mapping is None:
                raise ReconciliationValidationError("unmapped_plan")
            plan_key = mapping.plan_key
            profile = mapping.profile
            subscription_status = event.subscription_status or "active"
            grant_status = "active"
            period_end = event.current_period_end

        now = _now()
        now_iso = _iso(now)
        occurred_iso = _iso(event.occurred_at)
        period_iso = _iso(period_end)
        lease_end = now + timedelta(
            seconds=self.config.provider_grant_lease_seconds
        )
        grant_end = (
            min(lease_end, period_end)
            if event.provider == "stripe" and period_end is not None
            else lease_end
        )
        if grant_status == "revoked":
            grant_end = now
        grant_end_iso = _iso(grant_end)
        projection_mutated = False
        if subscription is None:
            if not removal:
                connection.execute(
                    """
                    INSERT INTO platform_subscriptions(
                        workspace_id,provider,external_subscription_id,
                        external_customer_id,status,plan_key,current_period_end,
                        last_event_at,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        workspace_id,
                        event.provider,
                        external_ref,
                        event.external_account_id,
                        subscription_status,
                        plan_key,
                        period_iso,
                        occurred_iso,
                        now_iso,
                        now_iso,
                    ),
                )
                projection_mutated = True
        else:
            if (
                str(subscription["status"]) != subscription_status
                or str(subscription["plan_key"]) != plan_key
                or _parse(subscription["current_period_end"]) != period_end
            ):
                projection_mutated = True
            connection.execute(
                """
                UPDATE platform_subscriptions
                SET status=?,plan_key=?,current_period_end=?,
                    last_event_at=?,updated_at=?
                WHERE id=?
                """,
                (
                    subscription_status,
                    plan_key,
                    period_iso,
                    occurred_iso,
                    now_iso,
                    subscription["id"],
                ),
            )
        if grant is None:
            if grant_status != "revoked":
                connection.execute(
                    """
                    INSERT INTO platform_access_grants(
                        workspace_id,subject_user_id,source,external_ref,
                        profile,plan_key,status,starts_at,ends_at,
                        created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        workspace_id,
                        subject_user_id,
                        event.provider,
                        external_ref,
                        profile.value,
                        plan_key,
                        grant_status,
                        now_iso,
                        grant_end_iso,
                        now_iso,
                        now_iso,
                    ),
                )
                projection_mutated = True
        else:
            if (
                str(grant["profile"]) != profile.value
                or str(grant["plan_key"]) != plan_key
                or str(grant["status"]) != grant_status
                or _parse(grant["ends_at"]) != grant_end
            ):
                projection_mutated = True
            connection.execute(
                """
                UPDATE platform_access_grants
                SET subject_user_id=?,profile=?,plan_key=?,status=?,
                    ends_at=?,updated_at=?
                WHERE id=? AND workspace_id=? AND source=?
                """,
                (
                    subject_user_id,
                    profile.value,
                    plan_key,
                    grant_status,
                    grant_end_iso,
                    now_iso,
                    grant["id"],
                    workspace_id,
                    event.provider,
                ),
            )

        if removal and not projection_mutated:
            return "no_provider_state"
        if grant_status == "revoked":
            if not self._subject_live_grant_exists(
                connection,
                workspace_id,
                subject_user_id,
                at=now,
            ):
                self._revoke_subject_oauth_tx(
                    connection,
                    workspace_id,
                    subject_user_id,
                    at=now,
                )
            desired = (
                "active"
                if self._live_grant_exists(connection, workspace_id, at=now)
                else "canceled"
            )
        else:
            desired = "active"
        current_state = self._account_state(connection, workspace_id)
        if current_state not in OPERATOR_ONLY_ACCOUNT_STATES:
            self._set_derived_account(connection, workspace_id, desired)
        return "applied"

    def _process_existing_tx(
        self,
        connection: sqlite3.Connection,
        event_db_id: int,
        event: NormalizedProviderEvent,
        *,
        replay: bool,
    ) -> SyncResult:
        if event.action in {"reject", "payment_succeeded"}:
            reason_code = (
                "non_restoring_event"
                if event.action == "payment_succeeded"
                else "unsupported_event_type"
            )
            self._set_event(
                connection,
                event_db_id,
                outcome="rejected",
                reason_code=reason_code,
                replayed=replay,
            )
            self._attempt(
                connection,
                event_db_id,
                "rejected",
                reason_code,
            )
            return SyncResult(
                event_db_id,
                event.event_id,
                "rejected",
                reason_code,
            )

        subject = self._resolve_subject(connection, event)
        if subject is None:
            return self._quarantine(
                connection,
                event_db_id,
                event,
                "unmapped_external_account",
                replay=replay,
            )
        workspace_id, subject_user_id = subject
        current_state = self._account_state(connection, workspace_id)
        if (
            current_state in OPERATOR_ONLY_ACCOUNT_STATES
            and event.action not in RESTRICTIVE_ACTIONS
        ):
            return self._quarantine(
                connection,
                event_db_id,
                event,
                "operator_state",
                workspace_id=workspace_id,
                replay=replay,
            )

        mapping: ProviderPlanMapping | None = None
        if event.action not in RESTRICTIVE_ACTIONS:
            mapping, mapping_error = self._mapping(event)
            if mapping_error is not None:
                provider_state = connection.execute(
                    """
                    SELECT 1 FROM platform_access_grants
                    WHERE workspace_id=? AND subject_user_id=? AND source=?
                      AND status IN ('active','overridden','expiring')
                    LIMIT 1
                    """,
                    (workspace_id, subject_user_id, event.provider),
                ).fetchone()
                if (
                    event.action == "membership_update"
                    and provider_state is not None
                ):
                    event = replace(event, action="loss_of_paid_level")
                else:
                    return self._quarantine(
                        connection,
                        event_db_id,
                        event,
                        mapping_error,
                        workspace_id=workspace_id,
                        replay=replay,
                    )
        if event.action not in RESTRICTIVE_ACTIONS:
            assert mapping is not None
            plan = connection.execute(
                "SELECT id FROM platform_plans WHERE key=?",
                (mapping.plan_key,),
            ).fetchone()
            if plan is None:
                provider_state = connection.execute(
                    """
                    SELECT 1 FROM platform_access_grants
                    WHERE workspace_id=? AND subject_user_id=? AND source=?
                      AND status IN ('active','overridden','expiring')
                    LIMIT 1
                    """,
                    (workspace_id, subject_user_id, event.provider),
                ).fetchone()
                if (
                    event.action == "membership_update"
                    and provider_state is not None
                ):
                    event = replace(event, action="loss_of_paid_level")
                    mapping = None
                else:
                    return self._quarantine(
                        connection,
                        event_db_id,
                        event,
                        "plan_not_found",
                        workspace_id=workspace_id,
                        replay=replay,
                    )

        if event.action != "payment_failed" and event.external_object_id is not None:
            subscription = connection.execute(
                """
                SELECT workspace_id FROM platform_subscriptions
                WHERE provider=? AND external_subscription_id=?
                """,
                (event.provider, event.external_object_id),
            ).fetchone()
            grant = connection.execute(
                """
                SELECT workspace_id FROM platform_access_grants
                WHERE source=? AND external_ref=?
                """,
                (event.provider, event.external_object_id),
            ).fetchone()
            if (
                subscription is not None
                and int(subscription["workspace_id"]) != workspace_id
            ) or (
                grant is not None
                and int(grant["workspace_id"]) != workspace_id
            ):
                return self._quarantine(
                    connection,
                    event_db_id,
                    event,
                    "conflicting_mapping",
                    workspace_id=workspace_id,
                    replay=replay,
                )

        connection.execute("SAVEPOINT provider_projection")
        try:
            projection_outcome = self._projection_tx(
                connection,
                event,
                event_db_id,
                workspace_id,
                subject_user_id,
                mapping,
            )
        except ReconciliationValidationError as exc:
            connection.execute("ROLLBACK TO provider_projection")
            connection.execute("RELEASE provider_projection")
            return self._quarantine(
                connection,
                event_db_id,
                event,
                str(exc),
                workspace_id=workspace_id,
                replay=replay,
            )
        except ValueError:
            connection.execute("ROLLBACK TO provider_projection")
            connection.execute("RELEASE provider_projection")
            return self._quarantine(
                connection,
                event_db_id,
                event,
                "invalid_transition",
                workspace_id=workspace_id,
                replay=replay,
            )
        except sqlite3.Error:
            connection.execute("ROLLBACK TO provider_projection")
            connection.execute("RELEASE provider_projection")
            return self._quarantine(
                connection,
                event_db_id,
                event,
                "projection_failure",
                workspace_id=workspace_id,
                replay=replay,
                attempt_outcome="failure",
            )
        else:
            connection.execute("RELEASE provider_projection")

        if projection_outcome == "stale":
            self._set_event(
                connection,
                event_db_id,
                outcome="stale",
                reason_code="older_source_event",
                workspace_id=workspace_id,
                replayed=replay,
            )
            self._attempt(
                connection,
                event_db_id,
                "stale",
                "older_source_event",
            )
            return SyncResult(
                event_db_id,
                event.event_id,
                "stale",
                "older_source_event",
                workspace_id,
            )
        if projection_outcome == "rejected":
            self._set_event(
                connection,
                event_db_id,
                outcome="rejected",
                reason_code="non_restrictive_event",
                workspace_id=workspace_id,
                replayed=replay,
            )
            self._attempt(
                connection,
                event_db_id,
                "rejected",
                "non_restrictive_event",
            )
            return SyncResult(
                event_db_id,
                event.event_id,
                "rejected",
                "non_restrictive_event",
                workspace_id,
            )
        if projection_outcome == "no_provider_state":
            self._set_event(
                connection,
                event_db_id,
                outcome="rejected",
                reason_code="no_provider_state",
                workspace_id=workspace_id,
                replayed=replay,
            )
            self._attempt(
                connection,
                event_db_id,
                "rejected",
                "no_provider_state",
            )
            return SyncResult(
                event_db_id,
                event.event_id,
                "rejected",
                "no_provider_state",
                workspace_id,
            )

        outcome = "reconciled" if replay else "applied"
        applied_reason = (
            "loss_of_paid_level"
            if event.action == "loss_of_paid_level"
            else "admin_replay"
            if replay
            else None
        )
        self._set_event(
            connection,
            event_db_id,
            outcome=outcome,
            reason_code=applied_reason,
            workspace_id=workspace_id,
            replayed=replay,
        )
        self._attempt(
            connection,
            event_db_id,
            outcome,
            applied_reason,
        )
        return SyncResult(
            event_db_id,
            event.event_id,
            outcome,
            applied_reason,
            workspace_id,
        )

    def ingest(self, event: NormalizedProviderEvent) -> SyncResult:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM platform_provider_events
                WHERE provider=? AND event_id=?
                """,
                (event.provider, event.event_id),
            ).fetchone()
            if existing is not None:
                event_db_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE platform_provider_events
                    SET duplicate_count=duplicate_count+1,updated_at=?
                    WHERE id=?
                    """,
                    (_iso(_now()), event_db_id),
                )
                self._attempt(
                    connection,
                    event_db_id,
                    "duplicate",
                    "duplicate_event",
                )
                connection.commit()
                return SyncResult(
                    event_db_id,
                    event.event_id,
                    "duplicate",
                    "duplicate_event",
                    (
                        int(existing["workspace_id"])
                        if existing["workspace_id"] is not None
                        else None
                    ),
                )
            now = _iso(_now())
            cursor = connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,reason_code,
                    duplicate_count,replayed_at,created_at,updated_at
                ) VALUES (NULL,?,?,?,?,?,?,'received',NULL,0,NULL,?,?)
                """,
                (
                    event.provider,
                    event.event_id,
                    event.event_type,
                    "{}",
                    json.dumps(
                        event.stored_data(),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    _iso(event.occurred_at),
                    now,
                    now,
                ),
            )
            result = self._process_existing_tx(
                connection,
                int(cursor.lastrowid),
                event,
                replay=False,
            )
            connection.commit()
            return result

    def record_malformed(
        self,
        provider: str,
        identity: tuple[str, str, datetime],
        reason_code: str = "malformed_json",
    ) -> SyncResult:
        event = NormalizedProviderEvent(
            provider=provider,
            event_id=identity[0],
            event_type=identity[1],
            occurred_at=identity[2],
            action="malformed",
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM platform_provider_events
                WHERE provider=? AND event_id=?
                """,
                (provider, event.event_id),
            ).fetchone()
            if existing is not None:
                event_db_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE platform_provider_events
                    SET duplicate_count=duplicate_count+1,updated_at=?
                    WHERE id=?
                    """,
                    (_iso(_now()), event_db_id),
                )
                self._attempt(
                    connection,
                    event_db_id,
                    "duplicate",
                    "duplicate_event",
                )
                connection.commit()
                return SyncResult(
                    event_db_id,
                    event.event_id,
                    "duplicate",
                    "duplicate_event",
                )
            now = _iso(_now())
            cursor = connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,reason_code,
                    duplicate_count,replayed_at,created_at,updated_at
                ) VALUES (NULL,?,?,?,?,?,?,'quarantined',?,
                          0,NULL,?,?)
                """,
                (
                    provider,
                    event.event_id,
                    event.event_type,
                    "{}",
                    "{}",
                    _iso(event.occurred_at),
                    reason_code,
                    now,
                    now,
                ),
            )
            self._attempt(
                connection,
                int(cursor.lastrowid),
                "malformed" if reason_code == "malformed_json" else "quarantined",
                reason_code,
            )
            logger.warning(
                "provider_event_quarantined",
                extra={
                    "provider": provider,
                    "provider_event_db_id": int(cursor.lastrowid),
                    "reason_code": reason_code,
                    "workspace_id": None,
                },
            )
            connection.commit()
            return SyncResult(
                int(cursor.lastrowid),
                event.event_id,
                "quarantined",
                reason_code,
            )

    def replay_tx(
        self,
        connection: sqlite3.Connection,
        provider_event_id: int,
    ) -> SyncResult:
        row = connection.execute(
            "SELECT * FROM platform_provider_events WHERE id=?",
            (provider_event_id,),
        ).fetchone()
        if row is None:
            raise ReconciliationNotFoundError("Provider event does not exist")
        if str(row["outcome"]) == "reconciled":
            return SyncResult(
                int(row["id"]),
                str(row["event_id"]),
                "reconciled",
                str(row["reason_code"]) if row["reason_code"] else None,
                int(row["workspace_id"]) if row["workspace_id"] else None,
            )
        if (
            str(row["outcome"]) == "rejected"
            and str(row["reason_code"]) == "no_provider_state"
            and row["replayed_at"] is not None
        ):
            return SyncResult(
                int(row["id"]),
                str(row["event_id"]),
                "rejected",
                "no_provider_state",
                int(row["workspace_id"]) if row["workspace_id"] else None,
            )
        if str(row["outcome"]) != "quarantined":
            raise ReconciliationConflictError(
                "Provider event is not eligible for replay"
            )
        data = json.loads(str(row["normalized_data"]))
        if not data:
            raise ReconciliationConflictError(
                "Provider event has no replayable normalized data"
            )
        event = NormalizedProviderEvent.from_stored_data(data)
        return self._process_existing_tx(
            connection,
            int(row["id"]),
            event,
            replay=True,
        )


def encode_cursor(event_id: int) -> str:
    raw = f"provider-event:{event_id}".encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None) -> int:
    if value is None:
        return 0
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding).decode("ascii")
        prefix, raw_id = decoded.split(":", 1)
        event_id = int(raw_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ReconciliationValidationError("cursor is invalid") from exc
    if prefix != "provider-event" or event_id < 0:
        raise ReconciliationValidationError("cursor is invalid")
    return event_id


__all__ = [
    "NormalizedProviderEvent",
    "ProviderSyncService",
    "ProviderValidationError",
    "ReconciliationConflictError",
    "ReconciliationNotFoundError",
    "ReconciliationValidationError",
    "SyncResult",
    "WebhookSignatureError",
    "WebhookTimestampError",
    "decode_cursor",
    "decode_json_object",
    "encode_cursor",
    "salvage_leading_identity",
    "verify_hmac_signature",
]
