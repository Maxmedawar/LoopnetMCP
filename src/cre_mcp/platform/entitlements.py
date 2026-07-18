"""Commercial account and entitlement persistence."""
from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from cre_mcp.access.profiles import Profile
from cre_mcp.platform.schema import create_schema
WorkspaceRef = int | str
ACCOUNT_STATES = (
    "invited", "registered", "verified", "active", "past_due",
    "grace_period", "suspended", "under_review", "canceled",
    "deletion_pending", "deleted",
)
GRANT_SOURCES = ("stripe", "skool", "manual", "jv", "promotion")
GRANT_STATUSES = ("pending", "active", "overridden", "expiring", "expired", "revoked")
SUBSCRIPTION_STATUSES = (
    "trialing", "active", "past_due", "grace_period",
    "paused", "canceled", "unpaid",
)
PROVIDERS = ("stripe", "skool")
ACCOUNT_TRANSITIONS = {
    "invited": frozenset({"registered", "verified", "active", "suspended", "deleted"}),
    "registered": frozenset({"verified", "active", "past_due", "suspended", "canceled", "deletion_pending", "deleted"}),
    "verified": frozenset({"active", "past_due", "suspended", "under_review", "canceled", "deletion_pending", "deleted"}),
    "active": frozenset({"past_due", "grace_period", "suspended", "under_review", "canceled", "deletion_pending", "deleted"}),
    "past_due": frozenset({"active", "grace_period", "suspended", "canceled", "deletion_pending", "deleted"}),
    "grace_period": frozenset({"active", "suspended", "canceled", "deletion_pending", "deleted"}),
    "suspended": frozenset({"active", "under_review", "canceled", "deletion_pending", "deleted"}),
    "under_review": frozenset({"active", "suspended", "canceled", "deletion_pending", "deleted"}),
    "canceled": frozenset({"active", "deletion_pending", "deleted"}),
    "deletion_pending": frozenset({"active", "deleted"}),
    "deleted": frozenset(),
}
def _now() -> datetime:
    return datetime.now(UTC)

def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None

def _parse(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized

def _choice(value: str, values: tuple[str, ...], label: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in values:
        raise ValueError(f"{label} must be one of {', '.join(values)}")
    return normalized
@dataclass(frozen=True)
class AccountRecord:
    workspace_id: int
    state: str
    reason: str | None
    updated_at: datetime

@dataclass(frozen=True)
class SubscriptionRecord:
    id: int
    workspace_id: int
    provider: str
    external_subscription_id: str
    external_customer_id: str | None
    status: str
    plan_key: str
    current_period_end: datetime | None
    created_at: datetime
    updated_at: datetime

@dataclass(frozen=True)
class AccessGrant:
    id: int
    workspace_id: int
    source: str
    external_ref: str
    profile: Profile
    plan_key: str
    status: str
    starts_at: datetime
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime
@dataclass(frozen=True)
class ProviderEvent:
    id: int
    workspace_id: int
    provider: str
    event_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime

@dataclass(frozen=True)
class EffectiveAccess:
    workspace_id: int
    profile: Profile
    plan_key: str
    grant_ids: tuple[int, ...]
    sources: tuple[str, ...]
    expires_at: datetime | None

@dataclass(frozen=True)
class EventResult:
    processed: bool
    event: ProviderEvent
    subscription: SubscriptionRecord | None
    grant: AccessGrant | None
def _sql_choices(values: tuple[str, ...]) -> str:
    return ", ".join("'" + item.replace("'", "''") + "'" for item in values)

_ENTITLEMENT_TEMPLATE = """
CREATE TABLE IF NOT EXISTS platform_accounts (
    workspace_id INTEGER PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'registered',
    reason TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    CHECK(state IN (__ACCOUNT_STATES__))
);

CREATE TABLE IF NOT EXISTS platform_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    external_subscription_id TEXT NOT NULL,
    external_customer_id TEXT,
    status TEXT NOT NULL,
    plan_key TEXT NOT NULL,
    current_period_end TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, external_subscription_id),
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    CHECK(provider IN (__PROVIDERS__)),
    CHECK(status IN (__SUBSCRIPTION_STATUSES__))
);
CREATE INDEX IF NOT EXISTS idx_platform_subscriptions_workspace
    ON platform_subscriptions(workspace_id, provider, status);

CREATE TABLE IF NOT EXISTS platform_access_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    profile TEXT NOT NULL,
    plan_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    starts_at TEXT NOT NULL,
    ends_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, external_ref),
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    CHECK(source IN (__GRANT_SOURCES__)),
    CHECK(profile IN ('local_scout', 'national_scout', 'full_operator', 'jv_partner')),
    CHECK(status IN (__GRANT_STATUSES__))
);
CREATE INDEX IF NOT EXISTS idx_platform_grants_workspace
    ON platform_access_grants(workspace_id, status, ends_at);

CREATE TABLE IF NOT EXISTS platform_provider_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(provider, event_id),
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    CHECK(provider IN (__PROVIDERS__))
);
CREATE INDEX IF NOT EXISTS idx_platform_provider_events_workspace
    ON platform_provider_events(workspace_id, provider, created_at);
"""

_ENTITLEMENT_SCHEMA = (
    _ENTITLEMENT_TEMPLATE
    .replace("__ACCOUNT_STATES__", _sql_choices(ACCOUNT_STATES))
    .replace("__PROVIDERS__", _sql_choices(PROVIDERS))
    .replace("__SUBSCRIPTION_STATUSES__", _sql_choices(SUBSCRIPTION_STATUSES))
    .replace("__GRANT_SOURCES__", _sql_choices(GRANT_SOURCES))
    .replace("__GRANT_STATUSES__", _sql_choices(GRANT_STATUSES))
)

class EntitlementStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            create_schema(connection)
            connection.executescript(_ENTITLEMENT_SCHEMA)

    def _resolve_workspace(self, workspace: WorkspaceRef) -> int:
        if isinstance(workspace, bool):
            raise ValueError("workspace does not exist")
        with self._connect() as connection:
            if isinstance(workspace, int):
                row = connection.execute(
                    "SELECT id FROM platform_workspaces WHERE id=?", (workspace,)
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT id FROM platform_workspaces WHERE public_id=?",
                    (str(workspace).strip(),),
                ).fetchone()
        if row is None:
            raise ValueError("workspace does not exist")
        return int(row["id"])

    @staticmethod
    def _account(row: sqlite3.Row | None) -> AccountRecord | None:
        if row is None:
            return None
        return AccountRecord(
            workspace_id=int(row["workspace_id"]),
            state=str(row["state"]),
            reason=row["reason"],
            updated_at=_parse(row["updated_at"]),
        )

    @staticmethod
    def _subscription(row: sqlite3.Row | None) -> SubscriptionRecord | None:
        if row is None:
            return None
        return SubscriptionRecord(
            id=int(row["id"]),
            workspace_id=int(row["workspace_id"]),
            provider=str(row["provider"]),
            external_subscription_id=str(row["external_subscription_id"]),
            external_customer_id=row["external_customer_id"],
            status=str(row["status"]),
            plan_key=str(row["plan_key"]),
            current_period_end=_parse(row["current_period_end"]),
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
        )

    @staticmethod
    def _grant(row: sqlite3.Row | None) -> AccessGrant | None:
        if row is None:
            return None
        return AccessGrant(
            id=int(row["id"]),
            workspace_id=int(row["workspace_id"]),
            source=str(row["source"]),
            external_ref=str(row["external_ref"]),
            profile=Profile(str(row["profile"])),
            plan_key=str(row["plan_key"]),
            status=str(row["status"]),
            starts_at=_parse(row["starts_at"]),
            ends_at=_parse(row["ends_at"]),
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> ProviderEvent:
        return ProviderEvent(
            id=int(row["id"]),
            workspace_id=int(row["workspace_id"]),
            provider=str(row["provider"]),
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            payload=json.loads(row["payload"]),
            created_at=_parse(row["created_at"]),
        )

    def get_account(self, workspace: WorkspaceRef) -> AccountRecord | None:
        workspace_id = self._resolve_workspace(workspace)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_accounts WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
        return self._account(row)

    def _set_account_tx(
        self,
        connection: sqlite3.Connection,
        workspace_id: int,
        state: str,
        reason: str | None,
    ) -> AccountRecord:
        state = _choice(state, ACCOUNT_STATES, "account state")
        row = connection.execute(
            "SELECT * FROM platform_accounts WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        current = str(row["state"]) if row is not None else ("invited" if state == "invited" else "registered")
        if state != current and state not in ACCOUNT_TRANSITIONS[current]:
            raise ValueError("invalid account transition")
        now = _iso(_now())
        if row is None:
            connection.execute(
                "INSERT INTO platform_accounts(workspace_id,state,reason,updated_at) VALUES (?,?,?,?)",
                (workspace_id, state, reason, now),
            )
        else:
            connection.execute(
                "UPDATE platform_accounts SET state=?,reason=?,updated_at=? WHERE workspace_id=?",
                (state, reason, now, workspace_id),
            )
        return AccountRecord(workspace_id, state, reason, _parse(now))

    def set_account_state(
        self, workspace: WorkspaceRef, state: str, *, reason: str | None = None
    ) -> AccountRecord:
        workspace_id = self._resolve_workspace(workspace)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._set_account_tx(connection, workspace_id, state, reason)

    def grant_access(
        self,
        *,
        workspace: WorkspaceRef,
        source: str,
        external_ref: str,
        profile: Profile,
        plan_key: str,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
    ) -> AccessGrant:
        workspace_id = self._resolve_workspace(workspace)
        source = _choice(source, GRANT_SOURCES, "grant source")
        external_ref = _required(external_ref, "external_ref")
        profile = Profile(profile)
        plan_key = _required(plan_key, "plan_key")
        starts_at = starts_at or _now()
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM platform_access_grants WHERE source=? AND external_ref=?",
                (source, external_ref),
            ).fetchone()
            if existing is not None and int(existing["workspace_id"]) != workspace_id:
                raise ValueError("grant belongs to a different workspace")
            if existing is None:
                connection.execute(
                    "INSERT INTO platform_access_grants(workspace_id,source,external_ref,profile,plan_key,status,starts_at,ends_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (workspace_id, source, external_ref, profile.value, plan_key, "active", _iso(starts_at), _iso(ends_at), _iso(now), _iso(now)),
                )
            else:
                connection.execute(
                    "UPDATE platform_access_grants SET profile=?,plan_key=?,status=?,starts_at=?,ends_at=?,updated_at=? WHERE id=? AND workspace_id=?",
                    (profile.value, plan_key, "active", _iso(starts_at), _iso(ends_at), _iso(now), existing["id"], workspace_id),
                )
            self._set_account_tx(connection, workspace_id, "active", None)
            row = connection.execute(
                "SELECT * FROM platform_access_grants WHERE source=? AND external_ref=?",
                (source, external_ref),
            ).fetchone()
        return self._grant(row)

    def get_grant(self, workspace: WorkspaceRef, grant_id: int) -> AccessGrant | None:
        workspace_id = self._resolve_workspace(workspace)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_access_grants WHERE id=? AND workspace_id=?",
                (grant_id, workspace_id),
            ).fetchone()
        return self._grant(row)

    def list_grants(self, workspace: WorkspaceRef) -> list[AccessGrant]:
        workspace_id = self._resolve_workspace(workspace)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM platform_access_grants WHERE workspace_id=? ORDER BY id",
                (workspace_id,),
            ).fetchall()
        return [self._grant(row) for row in rows]

    def revoke_grant(
        self, workspace: WorkspaceRef, grant_id: int
    ) -> AccessGrant | None:
        workspace_id = self._resolve_workspace(workspace)
        now = _iso(_now())
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE platform_access_grants SET status='revoked',updated_at=? WHERE id=? AND workspace_id=?",
                (now, grant_id, workspace_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM platform_access_grants WHERE id=? AND workspace_id=?",
                (grant_id, workspace_id),
            ).fetchone()
        return self._grant(row)

    def effective_access(
        self, workspace: WorkspaceRef, *, at: datetime | None = None
    ) -> EffectiveAccess | None:
        workspace_id = self._resolve_workspace(workspace)
        at = at or _now()
        account = self.get_account(workspace_id)
        if account is not None and account.state in {
            "suspended", "under_review", "canceled", "deletion_pending", "deleted"
        }:
            return None
        grants = [
            grant for grant in self.list_grants(workspace_id)
            if grant.status in {"active", "overridden", "expiring"}
            and grant.starts_at <= at
            and (grant.ends_at is None or grant.ends_at > at)
        ]
        if not grants:
            return None
        rank = {
            Profile.FULL_OPERATOR: 4,
            Profile.NATIONAL_SCOUT: 3,
            Profile.LOCAL_SCOUT: 2,
            Profile.JV_PARTNER: 1,
        }
        selected = max(grants, key=lambda item: (rank[item.profile], item.updated_at))
        expiries = [item.ends_at for item in grants if item.ends_at is not None]
        return EffectiveAccess(
            workspace_id=workspace_id,
            profile=selected.profile,
            plan_key=selected.plan_key,
            grant_ids=tuple(item.id for item in grants),
            sources=tuple(dict.fromkeys(item.source for item in grants)),
            expires_at=min(expiries) if expiries else None,
        )

    def get_subscription(
        self, workspace: WorkspaceRef, provider: str, external_subscription_id: str
    ) -> SubscriptionRecord | None:
        workspace_id = self._resolve_workspace(workspace)
        provider = _choice(provider, PROVIDERS, "provider")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_subscriptions WHERE workspace_id=? AND provider=? AND external_subscription_id=?",
                (workspace_id, provider, external_subscription_id),
            ).fetchone()
        return self._subscription(row)

    def list_events(self, workspace: WorkspaceRef) -> list[ProviderEvent]:
        workspace_id = self._resolve_workspace(workspace)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM platform_provider_events WHERE workspace_id=? ORDER BY id",
                (workspace_id,),
            ).fetchall()
        return [self._event(row) for row in rows]

    def apply_subscription_event(
        self,
        *,
        provider: str,
        event_id: str,
        event_type: str,
        workspace: WorkspaceRef,
        external_subscription_id: str,
        subscription_status: str,
        plan_key: str,
        profile: Profile,
        external_customer_id: str | None = None,
        current_period_end: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> EventResult:
        workspace_id = self._resolve_workspace(workspace)
        provider = _choice(provider, PROVIDERS, "provider")
        event_id = _required(event_id, "event_id")
        event_type = _required(event_type, "event_type")
        external_subscription_id = _required(external_subscription_id, "external_subscription_id")
        subscription_status = _choice(subscription_status, SUBSCRIPTION_STATUSES, "subscription status")
        plan_key = _required(plan_key, "plan_key")
        profile = Profile(profile)
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior_event = connection.execute(
                "SELECT * FROM platform_provider_events WHERE provider=? AND event_id=?",
                (provider, event_id),
            ).fetchone()
            if prior_event is not None:
                if int(prior_event["workspace_id"]) != workspace_id:
                    raise ValueError("provider event belongs to a different workspace")
                subscription = connection.execute("SELECT * FROM platform_subscriptions WHERE workspace_id=? AND provider=? AND external_subscription_id=?", (workspace_id, provider, external_subscription_id)).fetchone()
                grant = connection.execute("SELECT * FROM platform_access_grants WHERE workspace_id=? AND source=? AND external_ref=?", (workspace_id, provider, external_subscription_id)).fetchone()
                return EventResult(
                    False,
                    self._event(prior_event),
                    self._subscription(subscription),
                    self._grant(grant),
                )
            subscription = connection.execute(
                "SELECT * FROM platform_subscriptions WHERE provider=? AND external_subscription_id=?",
                (provider, external_subscription_id),
            ).fetchone()
            if subscription is not None and int(subscription["workspace_id"]) != workspace_id:
                raise ValueError("subscription belongs to a different workspace")
            grant = connection.execute("SELECT * FROM platform_access_grants WHERE source=? AND external_ref=?", (provider, external_subscription_id)).fetchone()
            if grant is not None and int(grant["workspace_id"]) != workspace_id:
                raise ValueError("grant belongs to a different workspace")
            if subscription_status in {"active", "trialing"}:
                grant_status, account_state = "active", "active"
            elif subscription_status == "past_due":
                grant_status, account_state = "expiring", "past_due"
            elif subscription_status == "grace_period":
                grant_status, account_state = "expiring", "grace_period"
            elif subscription_status == "paused":
                grant_status, account_state = "revoked", "suspended"
            else:  # canceled, unpaid
                grant_status, account_state = "revoked", "canceled"
            now_iso = _iso(now)
            period_end_iso = _iso(current_period_end)
            if subscription is None:
                connection.execute(
                    "INSERT INTO platform_subscriptions(workspace_id,provider,external_subscription_id,external_customer_id,status,plan_key,current_period_end,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (workspace_id, provider, external_subscription_id, external_customer_id, subscription_status, plan_key, period_end_iso, now_iso, now_iso),
                )
            else:
                connection.execute(
                    "UPDATE platform_subscriptions SET status=?,plan_key=?,external_customer_id=COALESCE(?,external_customer_id),current_period_end=?,updated_at=? WHERE id=?",
                    (subscription_status, plan_key, external_customer_id, period_end_iso, now_iso, subscription["id"]),
                )
            if grant is None:
                connection.execute(
                    "INSERT INTO platform_access_grants(workspace_id,source,external_ref,profile,plan_key,status,starts_at,ends_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (workspace_id, provider, external_subscription_id, profile.value, plan_key, grant_status, now_iso, period_end_iso, now_iso, now_iso),
                )
            else:
                connection.execute(
                    "UPDATE platform_access_grants SET profile=?,plan_key=?,status=?,ends_at=?,updated_at=? WHERE id=?",
                    (profile.value, plan_key, grant_status, period_end_iso, now_iso, grant["id"]),
                )
            try:
                self._set_account_tx(connection, workspace_id, account_state, None)
            except ValueError as exc:
                if str(exc) != "invalid account transition":
                    raise
            connection.execute(
                "INSERT INTO platform_provider_events(workspace_id,provider,event_id,event_type,payload,created_at) VALUES (?,?,?,?,?,?)",
                (workspace_id, provider, event_id, event_type, json.dumps(payload or {}, separators=(",", ":"), default=str), now_iso),
            )
            event_row = connection.execute(
                "SELECT * FROM platform_provider_events WHERE provider=? AND event_id=?",
                (provider, event_id),
            ).fetchone()
            subscription_row = connection.execute(
                "SELECT * FROM platform_subscriptions WHERE provider=? AND external_subscription_id=?",
                (provider, external_subscription_id),
            ).fetchone()
            grant_row = connection.execute(
                "SELECT * FROM platform_access_grants WHERE source=? AND external_ref=?",
                (provider, external_subscription_id),
            ).fetchone()
        return EventResult(
            True,
            self._event(event_row),
            self._subscription(subscription_row),
            self._grant(grant_row),
        )
