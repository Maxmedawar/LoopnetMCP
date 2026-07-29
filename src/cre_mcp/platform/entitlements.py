"""Commercial account and entitlement persistence."""
from __future__ import annotations
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from cre_mcp.access.profiles import Profile
from cre_mcp.platform.migrations import Migration, apply_migrations
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
DEFAULT_PROVIDER_GRANT_LEASE = timedelta(days=1)
ACCOUNT_TRANSITIONS = {
    "invited": frozenset({"registered", "verified", "active", "suspended", "canceled", "deleted"}),
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
    last_event_at: datetime | None
    created_at: datetime
    updated_at: datetime

@dataclass(frozen=True)
class AccessGrant:
    id: int
    workspace_id: int
    subject_user_id: int | None
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
    workspace_id: int | None
    provider: str
    event_id: str
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime
    created_at: datetime
    outcome: str
    reason_code: str | None
    normalized_data: dict[str, Any]

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
    outcome: str = "applied"
    reason_code: str | None = None
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
    last_event_at TEXT,
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
    occurred_at TEXT NOT NULL,
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


def _ordering_cutover(connection: sqlite3.Connection) -> None:
    subscription_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(platform_subscriptions)")
    }
    if "last_event_at" not in subscription_columns:
        connection.execute(
            "ALTER TABLE platform_subscriptions ADD COLUMN last_event_at TEXT"
        )
        connection.execute(
            "UPDATE platform_subscriptions SET last_event_at=updated_at "
            "WHERE last_event_at IS NULL"
        )

    event_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(platform_provider_events)")
    }
    if "occurred_at" not in event_columns:
        connection.execute(
            "ALTER TABLE platform_provider_events ADD COLUMN occurred_at TEXT"
        )
        connection.execute(
            "UPDATE platform_provider_events SET occurred_at=created_at "
            "WHERE occurred_at IS NULL"
        )


ENTITLEMENT_MIGRATIONS = (
    Migration(1, "provider event source ordering", _ordering_cutover),
)


PROVIDER_EVENT_OUTCOMES = (
    "received",
    "applied",
    "duplicate",
    "stale",
    "quarantined",
    "rejected",
    "unmapped",
    "malformed",
    "failure",
    "reconciled",
)


def _provider_sync_v1(connection: sqlite3.Connection) -> None:
    """Make unresolved provider receipts durable without retaining payloads."""
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(platform_provider_events)")
    }
    if "outcome" not in columns:
        legacy_sequence_row = connection.execute(
            """
            SELECT seq FROM sqlite_sequence
            WHERE name='platform_provider_events'
            """
        ).fetchone()
        legacy_sequence = (
            int(legacy_sequence_row[0])
            if legacy_sequence_row is not None
            else 0
        )
        legacy_max_id = int(
            connection.execute(
                "SELECT COALESCE(MAX(id),0) FROM platform_provider_events"
            ).fetchone()[0]
        )
        connection.execute(
            "DROP INDEX IF EXISTS idx_platform_provider_events_workspace"
        )
        connection.execute(
            """
            ALTER TABLE platform_provider_events
            RENAME TO platform_provider_events_legacy
            """
        )
        outcomes = _sql_choices(PROVIDER_EVENT_OUTCOMES)
        connection.execute(
            f"""
            CREATE TABLE platform_provider_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER,
                provider TEXT NOT NULL,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{{}}',
                normalized_data TEXT NOT NULL DEFAULT '{{}}',
                occurred_at TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT 'received',
                reason_code TEXT,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                replayed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(provider, event_id),
                FOREIGN KEY(workspace_id)
                    REFERENCES platform_workspaces(id) ON DELETE CASCADE,
                CHECK(provider IN ({_sql_choices(PROVIDERS)})),
                CHECK(outcome IN ({outcomes})),
                CHECK(duplicate_count >= 0)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO platform_provider_events(
                id,workspace_id,provider,event_id,event_type,payload,
                normalized_data,occurred_at,outcome,reason_code,
                duplicate_count,replayed_at,created_at,updated_at
            )
            SELECT
                id,workspace_id,provider,event_id,event_type,'{}','{}',
                occurred_at,'applied','legacy_import',0,NULL,
                created_at,created_at
            FROM platform_provider_events_legacy
            """
        )
        connection.execute("DROP TABLE platform_provider_events_legacy")
        sequence_high_water = max(legacy_sequence, legacy_max_id)
        sequence_row = connection.execute(
            """
            SELECT seq FROM sqlite_sequence
            WHERE name='platform_provider_events'
            """
        ).fetchone()
        if sequence_row is None:
            connection.execute(
                "INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)",
                ("platform_provider_events", sequence_high_water),
            )
        elif int(sequence_row[0]) < sequence_high_water:
            connection.execute(
                """
                UPDATE sqlite_sequence SET seq=?
                WHERE name='platform_provider_events'
                """,
                (sequence_high_water,),
            )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_provider_events_workspace
        ON platform_provider_events(workspace_id, provider, created_at, id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_provider_events_quarantine
        ON platform_provider_events(provider, outcome, id)
        """
    )
    outcomes = _sql_choices(PROVIDER_EVENT_OUTCOMES)
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS platform_provider_event_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_event_id INTEGER NOT NULL,
            outcome TEXT NOT NULL,
            reason_code TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(provider_event_id)
                REFERENCES platform_provider_events(id) ON DELETE CASCADE,
            CHECK(outcome IN ({outcomes}))
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_provider_event_attempts_event
        ON platform_provider_event_attempts(provider_event_id, id)
        """
    )


def _provider_sync_v2(connection: sqlite3.Connection) -> None:
    """Bind provider authority to one server-owned user and bound its lifetime."""
    grant_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(platform_access_grants)")
    }
    if "subject_user_id" not in grant_columns:
        connection.execute(
            """
            ALTER TABLE platform_access_grants
            ADD COLUMN subject_user_id INTEGER
                REFERENCES platform_users(id) ON DELETE CASCADE
            """
        )

    mapping_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(platform_external_accounts)"
        )
    }
    if "subject_user_id" not in mapping_columns:
        connection.execute(
            """
            ALTER TABLE platform_external_accounts
            ADD COLUMN subject_user_id INTEGER
                REFERENCES platform_users(id) ON DELETE CASCADE
            """
        )

    now = _now()
    lease_end = _iso(now + DEFAULT_PROVIDER_GRANT_LEASE)
    now_iso = _iso(now)
    connection.execute(
        """
        UPDATE platform_external_accounts
        SET subject_user_id=(
            SELECT MIN(m.user_id)
            FROM platform_memberships AS m
            WHERE m.workspace_id=platform_external_accounts.workspace_id
            HAVING COUNT(*)=1
        )
        WHERE provider IN ('stripe','skool')
          AND subject_user_id IS NULL
        """
    )
    connection.execute(
        """
        UPDATE platform_access_grants
        SET subject_user_id=(
            SELECT MIN(m.user_id)
            FROM platform_memberships AS m
            WHERE m.workspace_id=platform_access_grants.workspace_id
            HAVING COUNT(*)=1
        )
        WHERE source IN ('stripe','skool')
          AND subject_user_id IS NULL
        """
    )
    connection.execute(
        """
        UPDATE platform_access_grants
        SET ends_at=?,updated_at=?
        WHERE source IN ('stripe','skool')
          AND (
              ends_at IS NULL
              OR julianday(ends_at) > julianday(?)
          )
        """,
        (lease_end, now_iso, lease_end),
    )
    affected = connection.execute(
        """
        SELECT DISTINCT grant.workspace_id,grant.subject_user_id
        FROM platform_access_grants AS grant
        LEFT JOIN platform_subscriptions AS subscription
          ON subscription.workspace_id=grant.workspace_id
         AND subscription.provider=grant.source
         AND subscription.external_subscription_id=grant.external_ref
        WHERE grant.source IN ('stripe','skool')
          AND grant.status IN ('pending','active','overridden','expiring')
          AND (
              grant.subject_user_id IS NULL
              OR subscription.status IN (
                  'past_due','grace_period','paused','canceled','unpaid'
              )
          )
        """
    ).fetchall()
    affected_workspace_ids = sorted(
        {int(row["workspace_id"]) for row in affected}
    )
    connection.execute(
        """
        UPDATE platform_access_grants
        SET status='revoked',ends_at=?,updated_at=?
        WHERE source IN ('stripe','skool')
          AND status IN ('pending','active','overridden','expiring')
          AND EXISTS (
              SELECT 1 FROM platform_subscriptions AS subscription
              WHERE subscription.workspace_id=
                    platform_access_grants.workspace_id
                AND subscription.provider=platform_access_grants.source
                AND subscription.external_subscription_id=
                    platform_access_grants.external_ref
                AND subscription.status IN (
                    'past_due','grace_period','paused','canceled','unpaid'
                )
          )
        """,
        (now_iso, now_iso),
    )
    connection.execute(
        """
        UPDATE platform_access_grants
        SET status='revoked',ends_at=?,updated_at=?
        WHERE source IN ('stripe','skool')
          AND subject_user_id IS NULL
          AND status IN ('pending','active','overridden','expiring')
        """,
        (now_iso, now_iso),
    )
    oauth_tables = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table'
              AND name IN ('platform_oauth_sessions','platform_oauth_codes')
            """
        )
    }
    for affected_row in affected:
        workspace_id = int(affected_row["workspace_id"])
        if affected_row["subject_user_id"] is None:
            subject_rows = connection.execute(
                """
                SELECT user_id FROM platform_memberships
                WHERE workspace_id=?
                """,
                (workspace_id,),
            ).fetchall()
            subject_ids = [int(row["user_id"]) for row in subject_rows]
        else:
            subject_ids = [int(affected_row["subject_user_id"])]
        workspace = connection.execute(
            "SELECT public_id FROM platform_workspaces WHERE id=?",
            (workspace_id,),
        ).fetchone()
        if workspace is None:
            continue
        workspace_public_id = str(workspace["public_id"])
        for subject_id in subject_ids:
            live = connection.execute(
                """
                SELECT 1 FROM platform_access_grants
                WHERE workspace_id=?
                  AND status IN ('active','overridden','expiring')
                  AND julianday(starts_at) <= julianday(?)
                  AND (
                      ends_at IS NULL
                      OR julianday(ends_at) > julianday(?)
                  )
                  AND (
                      source NOT IN ('stripe','skool')
                      OR subject_user_id=?
                  )
                LIMIT 1
                """,
                (workspace_id, now_iso, now_iso, subject_id),
            ).fetchone()
            if live is not None:
                continue
            if "platform_oauth_sessions" in oauth_tables:
                connection.execute(
                    """
                    UPDATE platform_oauth_sessions
                    SET revoked_at=COALESCE(revoked_at,?),updated_at=?
                    WHERE workspace_id=? AND user_id=?
                    """,
                    (
                        now_iso,
                        now_iso,
                        workspace_public_id,
                        subject_id,
                    ),
                )
            if "platform_oauth_codes" in oauth_tables:
                connection.execute(
                    """
                    UPDATE platform_oauth_codes
                    SET consumed_at=COALESCE(consumed_at,?)
                    WHERE workspace_id=? AND user_id=?
                    """,
                    (now_iso, workspace_public_id, subject_id),
                )
    for workspace_id in affected_workspace_ids:
        account = connection.execute(
            """
            SELECT state,reason FROM platform_accounts
            WHERE workspace_id=?
            """,
            (workspace_id,),
        ).fetchone()
        if (
            account is not None
            and str(account["state"]) in {
                "suspended",
                "under_review",
                "deletion_pending",
                "deleted",
            }
        ):
            continue
        live_grant = connection.execute(
            """
            SELECT 1 FROM platform_access_grants
            WHERE workspace_id=?
              AND status IN ('active','overridden','expiring')
              AND julianday(starts_at) <= julianday(?)
              AND (
                  ends_at IS NULL
                  OR julianday(ends_at) > julianday(?)
              )
            LIMIT 1
            """,
            (workspace_id, now_iso, now_iso),
        ).fetchone()
        derived_state = "active" if live_grant is not None else "canceled"
        if account is None:
            connection.execute(
                """
                INSERT INTO platform_accounts(
                    workspace_id,state,reason,updated_at
                ) VALUES (?,?,NULL,?)
                """,
                (workspace_id, derived_state, now_iso),
            )
        elif str(account["state"]) != derived_state:
            connection.execute(
                """
                UPDATE platform_accounts
                SET state=?,reason=NULL,updated_at=?
                WHERE workspace_id=?
                """,
                (derived_state, now_iso, workspace_id),
            )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_provider_grants_subject
        ON platform_access_grants(
            workspace_id,subject_user_id,source,status,ends_at
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_external_accounts_subject
        ON platform_external_accounts(
            workspace_id,subject_user_id,provider,id
        )
        """
    )
    for statement in (
        """
        CREATE TRIGGER IF NOT EXISTS platform_provider_grant_subject_insert
        BEFORE INSERT ON platform_access_grants
        WHEN NEW.source IN ('stripe','skool')
        BEGIN
            SELECT CASE
                WHEN NEW.subject_user_id IS NULL OR NEW.ends_at IS NULL
                THEN RAISE(ABORT, 'provider grant requires subject and lease')
            END;
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM platform_memberships
                    WHERE workspace_id=NEW.workspace_id
                      AND user_id=NEW.subject_user_id
                )
                THEN RAISE(ABORT, 'provider subject is not a workspace member')
            END;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS platform_provider_grant_subject_update
        BEFORE UPDATE OF workspace_id,subject_user_id,source,ends_at
            ON platform_access_grants
        WHEN NEW.source IN ('stripe','skool')
        BEGIN
            SELECT CASE
                WHEN NEW.subject_user_id IS NULL OR NEW.ends_at IS NULL
                THEN RAISE(ABORT, 'provider grant requires subject and lease')
            END;
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM platform_memberships
                    WHERE workspace_id=NEW.workspace_id
                      AND user_id=NEW.subject_user_id
                )
                THEN RAISE(ABORT, 'provider subject is not a workspace member')
            END;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS platform_provider_mapping_subject_insert
        BEFORE INSERT ON platform_external_accounts
        WHEN NEW.provider IN ('stripe','skool')
        BEGIN
            SELECT CASE
                WHEN NEW.subject_user_id IS NULL
                THEN RAISE(ABORT, 'provider mapping requires subject')
            END;
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM platform_memberships
                    WHERE workspace_id=NEW.workspace_id
                      AND user_id=NEW.subject_user_id
                )
                THEN RAISE(ABORT, 'provider subject is not a workspace member')
            END;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS platform_provider_mapping_subject_update
        BEFORE UPDATE OF workspace_id,subject_user_id,provider
            ON platform_external_accounts
        WHEN NEW.provider IN ('stripe','skool')
        BEGIN
            SELECT CASE
                WHEN NEW.subject_user_id IS NULL
                THEN RAISE(ABORT, 'provider mapping requires subject')
            END;
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM platform_memberships
                    WHERE workspace_id=NEW.workspace_id
                      AND user_id=NEW.subject_user_id
                )
                THEN RAISE(ABORT, 'provider subject is not a workspace member')
            END;
        END
        """,
    ):
        connection.execute(statement)


PROVIDER_SYNC_MIGRATIONS = (
    Migration(
        1,
        "payload-free unresolved provider journal and outcomes",
        _provider_sync_v1,
    ),
    Migration(
        2,
        "individual provider subjects and bounded provider leases",
        _provider_sync_v2,
    ),
)

class EntitlementStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            create_schema(connection)
            connection.executescript(_ENTITLEMENT_SCHEMA)
            apply_migrations(
                connection,
                "entitlements",
                ENTITLEMENT_MIGRATIONS,
            )
            apply_migrations(
                connection,
                "provider-sync",
                PROVIDER_SYNC_MIGRATIONS,
            )

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
            last_event_at=_parse(row["last_event_at"]),
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
            subject_user_id=(
                int(row["subject_user_id"])
                if "subject_user_id" in row.keys()
                and row["subject_user_id"] is not None
                else None
            ),
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
            workspace_id=(
                int(row["workspace_id"])
                if row["workspace_id"] is not None
                else None
            ),
            provider=str(row["provider"]),
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            payload=json.loads(row["payload"]),
            occurred_at=_parse(row["occurred_at"]),
            created_at=_parse(row["created_at"]),
            outcome=str(row["outcome"]),
            reason_code=row["reason_code"],
            normalized_data=json.loads(row["normalized_data"]),
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

    def _set_derived_account_tx(
        self,
        connection: sqlite3.Connection,
        workspace_id: int,
        state: str,
    ) -> AccountRecord:
        current = connection.execute(
            "SELECT state,reason FROM platform_accounts WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        reason = (
            current["reason"]
            if current is not None and str(current["state"]) == state
            else None
        )
        return self._set_account_tx(
            connection,
            workspace_id,
            state,
            reason,
        )

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
        subject_user_id: int | None = None,
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
            if source in PROVIDERS:
                if subject_user_id is None:
                    subjects = connection.execute(
                        """
                        SELECT user_id FROM platform_memberships
                        WHERE workspace_id=? ORDER BY user_id
                        """,
                        (workspace_id,),
                    ).fetchall()
                    if len(subjects) != 1:
                        raise ValueError(
                            "provider grant requires an individual subject"
                        )
                    subject_user_id = int(subjects[0]["user_id"])
                membership = connection.execute(
                    """
                    SELECT 1 FROM platform_memberships
                    WHERE workspace_id=? AND user_id=?
                    """,
                    (workspace_id, subject_user_id),
                ).fetchone()
                if membership is None:
                    raise ValueError(
                        "provider subject is not a workspace member"
                    )
                if ends_at is None:
                    ends_at = now + DEFAULT_PROVIDER_GRANT_LEASE
            existing = connection.execute(
                "SELECT * FROM platform_access_grants WHERE source=? AND external_ref=?",
                (source, external_ref),
            ).fetchone()
            if existing is not None and int(existing["workspace_id"]) != workspace_id:
                raise ValueError("grant belongs to a different workspace")
            if existing is None:
                connection.execute(
                    "INSERT INTO platform_access_grants(workspace_id,subject_user_id,source,external_ref,profile,plan_key,status,starts_at,ends_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (workspace_id, subject_user_id, source, external_ref, profile.value, plan_key, "active", _iso(starts_at), _iso(ends_at), _iso(now), _iso(now)),
                )
            else:
                connection.execute(
                    "UPDATE platform_access_grants SET subject_user_id=?,profile=?,plan_key=?,status=?,starts_at=?,ends_at=?,updated_at=? WHERE id=? AND workspace_id=?",
                    (subject_user_id, profile.value, plan_key, "active", _iso(starts_at), _iso(ends_at), _iso(now), existing["id"], workspace_id),
                )
            self._set_derived_account_tx(connection, workspace_id, "active")
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
        occurred_at: datetime | None = None,
        subject_user_id: int | None = None,
    ) -> EventResult:
        """Apply the legacy synchronous provider-event compatibility path.

        ``payload`` remains accepted for existing callers but is deliberately
        ignored. Provider event storage is payload-free by contract.
        """
        workspace_id = self._resolve_workspace(workspace)
        provider = _choice(provider, PROVIDERS, "provider")
        event_id = _required(event_id, "event_id")
        event_type = _required(event_type, "event_type")
        external_subscription_id = _required(external_subscription_id, "external_subscription_id")
        subscription_status = _choice(subscription_status, SUBSCRIPTION_STATUSES, "subscription status")
        plan_key = _required(plan_key, "plan_key")
        profile = Profile(profile)
        now = _now()
        occurred_at = occurred_at or now
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        else:
            occurred_at = occurred_at.astimezone(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if subject_user_id is None:
                subjects = connection.execute(
                    """
                    SELECT user_id FROM platform_memberships
                    WHERE workspace_id=? ORDER BY user_id
                    """,
                    (workspace_id,),
                ).fetchall()
                if len(subjects) != 1:
                    raise ValueError(
                        "provider event requires an individual subject"
                    )
                subject_user_id = int(subjects[0]["user_id"])
            membership = connection.execute(
                """
                SELECT 1 FROM platform_memberships
                WHERE workspace_id=? AND user_id=?
                """,
                (workspace_id, subject_user_id),
            ).fetchone()
            if membership is None:
                raise ValueError("provider subject is not a workspace member")
            prior_event = connection.execute(
                "SELECT * FROM platform_provider_events WHERE provider=? AND event_id=?",
                (provider, event_id),
            ).fetchone()
            if prior_event is not None:
                if (
                    prior_event["workspace_id"] is None
                    or int(prior_event["workspace_id"]) != workspace_id
                ):
                    raise ValueError("provider event belongs to a different workspace")
                connection.execute(
                    """
                    UPDATE platform_provider_events
                    SET duplicate_count=duplicate_count+1,updated_at=?
                    WHERE id=?
                    """,
                    (_iso(now), prior_event["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO platform_provider_event_attempts(
                        provider_event_id,outcome,reason_code,created_at
                    ) VALUES (?,'duplicate','duplicate_event',?)
                    """,
                    (prior_event["id"], _iso(now)),
                )
                subscription = connection.execute("SELECT * FROM platform_subscriptions WHERE workspace_id=? AND provider=? AND external_subscription_id=?", (workspace_id, provider, external_subscription_id)).fetchone()
                grant = connection.execute("SELECT * FROM platform_access_grants WHERE workspace_id=? AND source=? AND external_ref=?", (workspace_id, provider, external_subscription_id)).fetchone()
                return EventResult(
                    False,
                    self._event(prior_event),
                    self._subscription(subscription),
                    self._grant(grant),
                    "duplicate",
                    "duplicate_event",
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
            if (
                grant is not None
                and (
                    grant["subject_user_id"] is None
                    or int(grant["subject_user_id"]) != subject_user_id
                )
            ):
                raise ValueError("grant belongs to a different subject")
            now_iso = _iso(now)
            occurred_at_iso = _iso(occurred_at)
            connection.execute(
                """
                INSERT INTO platform_provider_events
                    (workspace_id,provider,event_id,event_type,payload,
                     normalized_data,occurred_at,outcome,reason_code,
                     duplicate_count,replayed_at,created_at,updated_at)
                VALUES (?,?,?,?,'{}','{}',?,'received',NULL,0,NULL,?,?)
                """,
                (
                    workspace_id,
                    provider,
                    event_id,
                    event_type,
                    occurred_at_iso,
                    now_iso,
                    now_iso,
                ),
            )
            event_row = connection.execute(
                """
                SELECT * FROM platform_provider_events
                WHERE provider=? AND event_id=?
                """,
                (provider, event_id),
            ).fetchone()
            last_event_at = (
                _parse(subscription["last_event_at"])
                if subscription is not None
                else None
            )
            if last_event_at is not None and occurred_at < last_event_at:
                connection.execute(
                    """
                    UPDATE platform_provider_events
                    SET outcome='stale',reason_code='older_source_event',
                        updated_at=?
                    WHERE id=?
                    """,
                    (now_iso, event_row["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO platform_provider_event_attempts(
                        provider_event_id,outcome,reason_code,created_at
                    ) VALUES (?,'stale','older_source_event',?)
                    """,
                    (event_row["id"], now_iso),
                )
                event_row = connection.execute(
                    "SELECT * FROM platform_provider_events WHERE id=?",
                    (event_row["id"],),
                ).fetchone()
                return EventResult(
                    False,
                    self._event(event_row),
                    self._subscription(subscription),
                    self._grant(grant),
                    "stale",
                    "older_source_event",
                )
            account = connection.execute(
                "SELECT state FROM platform_accounts WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
            restrictive = subscription_status not in {"active", "trialing"}
            if (
                not restrictive
                and account is not None
                and str(account["state"]) in {
                "suspended",
                "under_review",
                "deletion_pending",
                "deleted",
                }
            ):
                connection.execute(
                    """
                    UPDATE platform_provider_events
                    SET outcome='quarantined',reason_code='operator_state',
                        updated_at=?
                    WHERE id=?
                    """,
                    (now_iso, event_row["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO platform_provider_event_attempts(
                        provider_event_id,outcome,reason_code,created_at
                    ) VALUES (?,'quarantined','operator_state',?)
                    """,
                    (event_row["id"], now_iso),
                )
                event_row = connection.execute(
                    "SELECT * FROM platform_provider_events WHERE id=?",
                    (event_row["id"],),
                ).fetchone()
                return EventResult(
                    False,
                    self._event(event_row),
                    self._subscription(subscription),
                    self._grant(grant),
                    "quarantined",
                    "operator_state",
                )
            if subscription_status in {"active", "trialing"}:
                grant_status = "active"
            else:
                grant_status = "revoked"
            period_end_iso = _iso(current_period_end)
            lease_end = now + DEFAULT_PROVIDER_GRANT_LEASE
            grant_end = (
                min(lease_end, current_period_end)
                if provider == "stripe" and current_period_end is not None
                else lease_end
            )
            if grant_status == "revoked":
                grant_end = now
            grant_end_iso = _iso(grant_end)
            connection.execute("SAVEPOINT provider_projection")
            try:
                if subscription is None:
                    connection.execute(
                        "INSERT INTO platform_subscriptions(workspace_id,provider,external_subscription_id,external_customer_id,status,plan_key,current_period_end,last_event_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (workspace_id, provider, external_subscription_id, external_customer_id, subscription_status, plan_key, period_end_iso, occurred_at_iso, now_iso, now_iso),
                    )
                else:
                    connection.execute(
                        "UPDATE platform_subscriptions SET status=?,plan_key=?,external_customer_id=COALESCE(?,external_customer_id),current_period_end=?,last_event_at=?,updated_at=? WHERE id=?",
                        (subscription_status, plan_key, external_customer_id, period_end_iso, occurred_at_iso, now_iso, subscription["id"]),
                    )
                if grant is None:
                    connection.execute(
                        "INSERT INTO platform_access_grants(workspace_id,subject_user_id,source,external_ref,profile,plan_key,status,starts_at,ends_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (workspace_id, subject_user_id, provider, external_subscription_id, profile.value, plan_key, grant_status, now_iso, grant_end_iso, now_iso, now_iso),
                    )
                else:
                    connection.execute(
                        "UPDATE platform_access_grants SET subject_user_id=?,profile=?,plan_key=?,status=?,ends_at=?,updated_at=? WHERE id=? AND workspace_id=? AND source=?",
                        (subject_user_id, profile.value, plan_key, grant_status, grant_end_iso, now_iso, grant["id"], workspace_id, provider),
                    )
                if grant_status == "revoked":
                    live_grants = connection.execute(
                        """
                        SELECT status,starts_at,ends_at
                        FROM platform_access_grants
                        WHERE workspace_id=?
                        """,
                        (workspace_id,),
                    ).fetchall()
                    has_live_grant = any(
                        str(item["status"]) in {"active", "overridden", "expiring"}
                        and _parse(item["starts_at"]) <= now
                        and (
                            item["ends_at"] is None
                            or _parse(item["ends_at"]) > now
                        )
                        for item in live_grants
                    )
                    account_state = "active" if has_live_grant else "canceled"
                else:
                    account_state = "active"
                if grant_status == "revoked":
                    subject_rows = connection.execute(
                        """
                        SELECT status,starts_at,ends_at
                        FROM platform_access_grants
                        WHERE workspace_id=?
                          AND (
                              source NOT IN ('stripe','skool')
                              OR subject_user_id=?
                          )
                        """,
                        (workspace_id, subject_user_id),
                    ).fetchall()
                    subject_has_live_grant = any(
                        str(item["status"])
                        in {"active", "overridden", "expiring"}
                        and _parse(item["starts_at"]) <= now
                        and (
                            item["ends_at"] is None
                            or _parse(item["ends_at"]) > now
                        )
                        for item in subject_rows
                    )
                    if not subject_has_live_grant:
                        oauth_tables = {
                            str(item[0])
                            for item in connection.execute(
                                """
                                SELECT name FROM sqlite_master
                                WHERE type='table'
                                  AND name IN (
                                      'platform_oauth_sessions',
                                      'platform_oauth_codes'
                                  )
                                """
                            )
                        }
                        workspace_row = connection.execute(
                            """
                            SELECT public_id FROM platform_workspaces
                            WHERE id=?
                            """,
                            (workspace_id,),
                        ).fetchone()
                        assert workspace_row is not None
                        workspace_public_id = str(workspace_row["public_id"])
                        if "platform_oauth_sessions" in oauth_tables:
                            connection.execute(
                                """
                                UPDATE platform_oauth_sessions
                                SET revoked_at=COALESCE(revoked_at,?),
                                    updated_at=?
                                WHERE workspace_id=? AND user_id=?
                                """,
                                (
                                    now_iso,
                                    now_iso,
                                    workspace_public_id,
                                    subject_user_id,
                                ),
                            )
                        if "platform_oauth_codes" in oauth_tables:
                            connection.execute(
                                """
                                UPDATE platform_oauth_codes
                                SET consumed_at=COALESCE(consumed_at,?)
                                WHERE workspace_id=? AND user_id=?
                                """,
                                (
                                    now_iso,
                                    workspace_public_id,
                                    subject_user_id,
                                ),
                            )
                if (
                    account is None
                    or str(account["state"])
                    not in {
                        "suspended",
                        "under_review",
                        "deletion_pending",
                        "deleted",
                    }
                ):
                    self._set_derived_account_tx(
                        connection,
                        workspace_id,
                        account_state,
                    )
            except (ValueError, sqlite3.Error) as exc:
                connection.execute("ROLLBACK TO provider_projection")
                connection.execute("RELEASE provider_projection")
                reason_code = (
                    "invalid_transition"
                    if isinstance(exc, ValueError)
                    else "projection_failure"
                )
                attempt_outcome = (
                    "quarantined"
                    if isinstance(exc, ValueError)
                    else "failure"
                )
                connection.execute(
                    """
                    UPDATE platform_provider_events
                    SET outcome='quarantined',reason_code=?,updated_at=?
                    WHERE id=?
                    """,
                    (reason_code, now_iso, event_row["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO platform_provider_event_attempts(
                        provider_event_id,outcome,reason_code,created_at
                    ) VALUES (?,?,?,?)
                    """,
                    (event_row["id"], attempt_outcome, reason_code, now_iso),
                )
                event_row = connection.execute(
                    "SELECT * FROM platform_provider_events WHERE id=?",
                    (event_row["id"],),
                ).fetchone()
                return EventResult(
                    False,
                    self._event(event_row),
                    self._subscription(subscription),
                    self._grant(grant),
                    "quarantined",
                    reason_code,
                )
            else:
                connection.execute("RELEASE provider_projection")
            connection.execute(
                """
                UPDATE platform_provider_events
                SET outcome='applied',reason_code=NULL,updated_at=?
                WHERE id=?
                """,
                (now_iso, event_row["id"]),
            )
            connection.execute(
                """
                INSERT INTO platform_provider_event_attempts(
                    provider_event_id,outcome,reason_code,created_at
                ) VALUES (?,'applied',NULL,?)
                """,
                (event_row["id"], now_iso),
            )
            event_row = connection.execute(
                "SELECT * FROM platform_provider_events WHERE id=?",
                (event_row["id"],),
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
            "applied",
        )
