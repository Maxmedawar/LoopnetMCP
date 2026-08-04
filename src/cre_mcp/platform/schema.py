"""SQLite schema for the MedawarCRE multi-tenant platform layer."""
from __future__ import annotations

import sqlite3

from cre_mcp.platform.migrations import Migration, apply_migrations
from cre_mcp.platform.models import (
    ADMIN_REASON_CODES,
    CLIENT_STATUSES,
    CONSENT_TYPES,
    INTERNAL_ADMIN_ROLES,
    MEMBERSHIP_ROLES,
    PRIVACY_REQUEST_KINDS,
    PRIVACY_REQUEST_STATUSES,
    SAVED_DEAL_STAGES,
)


def _sql_choices(values: tuple[str, ...]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


PLATFORM_TABLES = frozenset(
    {
        "platform_users",
        "platform_plans",
        "platform_workspaces",
        "platform_memberships",
        "platform_territories",
        "platform_connected_clients",
        "platform_saved_deals",
        "platform_notes",
        "platform_outcomes",
        "platform_consents",
        "platform_integration_events",
        "platform_privacy_requests",
        "platform_internal_admins",
        "platform_external_accounts",
        "platform_admin_audit",
        "platform_human_identities",
        "platform_browser_sessions",
        "platform_operator_sessions",
        "platform_oauth_authorization_requests",
        "platform_skool_join_tasks",
        "platform_skool_reconciliations",
    }
)

_SCHEMA_TEMPLATE = """
CREATE TABLE IF NOT EXISTS platform_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    monthly_price_usd REAL,
    seat_limit INTEGER,
    daily_quotas TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(monthly_price_usd IS NULL OR monthly_price_usd >= 0),
    CHECK(seat_limit IS NULL OR seat_limit > 0)
);

CREATE TABLE IF NOT EXISTS platform_workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    plan_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(plan_id) REFERENCES platform_plans(id)
);

CREATE TABLE IF NOT EXISTS platform_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, user_id),
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE,
    CHECK(role IN (__MEMBERSHIP_ROLES__))
);
CREATE INDEX IF NOT EXISTS idx_platform_memberships_workspace
    ON platform_memberships(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS platform_territories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    state TEXT,
    market TEXT,
    asset_type TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, name),
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_platform_territories_workspace
    ON platform_territories(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS platform_connected_clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    client_type TEXT NOT NULL,
    scopes TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    CHECK(status IN (__CLIENT_STATUSES__))
);
CREATE INDEX IF NOT EXISTS idx_platform_connected_clients_workspace
    ON platform_connected_clients(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS platform_saved_deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    deal_ref TEXT NOT NULL,
    title TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    stage TEXT NOT NULL DEFAULT 'watching',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, deal_ref),
    UNIQUE(workspace_id, id),
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    CHECK(stage IN (__SAVED_DEAL_STAGES__))
);
CREATE INDEX IF NOT EXISTS idx_platform_saved_deals_stage
    ON platform_saved_deals(workspace_id, stage, updated_at);

CREATE TABLE IF NOT EXISTS platform_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    saved_deal_id INTEGER NOT NULL,
    author_user_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id, saved_deal_id)
        REFERENCES platform_saved_deals(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY(author_user_id) REFERENCES platform_users(id)
);
CREATE INDEX IF NOT EXISTS idx_platform_notes_deal
    ON platform_notes(workspace_id, saved_deal_id, created_at);

CREATE TABLE IF NOT EXISTS platform_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    saved_deal_id INTEGER NOT NULL,
    closed INTEGER NOT NULL,
    purchase_price REAL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workspace_id, saved_deal_id),
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(workspace_id, saved_deal_id)
        REFERENCES platform_saved_deals(workspace_id, id) ON DELETE CASCADE,
    CHECK(closed IN (0, 1)),
    CHECK(purchase_price IS NULL OR purchase_price > 0)
);

CREATE TABLE IF NOT EXISTS platform_consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    consent_type TEXT NOT NULL,
    granted INTEGER NOT NULL,
    version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE,
    CHECK(consent_type IN (__CONSENT_TYPES__)),
    CHECK(granted IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_platform_consents_user
    ON platform_consents(workspace_id, user_id, consent_type, created_at);

CREATE TABLE IF NOT EXISTS platform_integration_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    client_id INTEGER,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(client_id) REFERENCES platform_connected_clients(id)
);
CREATE INDEX IF NOT EXISTS idx_platform_integration_events_workspace
    ON platform_integration_events(workspace_id, event_type, created_at);

CREATE TABLE IF NOT EXISTS platform_privacy_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received',
    detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE,
    CHECK(kind IN (__PRIVACY_REQUEST_KINDS__)),
    CHECK(status IN (__PRIVACY_REQUEST_STATUSES__))
);
CREATE INDEX IF NOT EXISTS idx_platform_privacy_requests_workspace
    ON platform_privacy_requests(workspace_id, status, created_at);

CREATE TABLE IF NOT EXISTS platform_human_identities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    subject_hash TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, subject_hash),
    UNIQUE(provider, user_id),
    FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_platform_human_identities_user
    ON platform_human_identities(user_id);

CREATE TABLE IF NOT EXISTS platform_browser_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL,
    csrf_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_platform_browser_sessions_user
    ON platform_browser_sessions(user_id, revoked_at, expires_at);

CREATE TABLE IF NOT EXISTS platform_operator_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL,
    csrf_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_platform_operator_sessions_user
    ON platform_operator_sessions(user_id, revoked_at, expires_at);

CREATE TABLE IF NOT EXISTS platform_oauth_authorization_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_hash TEXT NOT NULL UNIQUE,
    client_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    state TEXT NOT NULL,
    scopes TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL,
    audience TEXT NOT NULL,
    resource TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(client_id)
        REFERENCES platform_oauth_clients(client_id) ON DELETE CASCADE,
    CHECK(code_challenge_method = 'S256')
);
"""

SCHEMA = (
    _SCHEMA_TEMPLATE
    .replace("__MEMBERSHIP_ROLES__", _sql_choices(MEMBERSHIP_ROLES))
    .replace("__CLIENT_STATUSES__", _sql_choices(CLIENT_STATUSES))
    .replace("__SAVED_DEAL_STAGES__", _sql_choices(SAVED_DEAL_STAGES))
    .replace("__CONSENT_TYPES__", _sql_choices(CONSENT_TYPES))
    .replace("__PRIVACY_REQUEST_KINDS__", _sql_choices(PRIVACY_REQUEST_KINDS))
    .replace("__PRIVACY_REQUEST_STATUSES__", _sql_choices(PRIVACY_REQUEST_STATUSES))
)


def _plan_daily_quotas_cutover(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(platform_plans)")
    }
    if "daily_quotas" not in columns:
        connection.execute(
            "ALTER TABLE platform_plans "
            "ADD COLUMN daily_quotas TEXT NOT NULL DEFAULT '{}'"
        )


PLATFORM_MIGRATIONS = (
    Migration(
        1,
        "server-owned daily plan quotas",
        _plan_daily_quotas_cutover,
    ),
)


def _admin_controls_v1(connection: sqlite3.Connection) -> None:
    internal_roles = _sql_choices(INTERNAL_ADMIN_ROLES)
    reason_codes = _sql_choices(ADMIN_REASON_CODES)
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS platform_internal_admins (
            user_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE,
            CHECK(role IN ({internal_roles})),
            CHECK(active IN (0,1))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_external_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            external_account_id TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(provider, external_account_id),
            FOREIGN KEY(workspace_id)
                REFERENCES platform_workspaces(id) ON DELETE CASCADE,
            CHECK(length(trim(provider)) > 0),
            CHECK(length(trim(external_account_id)) > 0)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_external_accounts_workspace
        ON platform_external_accounts(workspace_id, provider, id)
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS platform_admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_user_id INTEGER NOT NULL,
            actor_role TEXT NOT NULL,
            action TEXT NOT NULL,
            workspace_id INTEGER,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            reason TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(actor_user_id) REFERENCES platform_users(id),
            CHECK(actor_role IN ({internal_roles})),
            CHECK(reason_code IN ({reason_codes})),
            CHECK(length(trim(reason)) > 0)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_admin_audit_workspace
        ON platform_admin_audit(workspace_id, created_at, id)
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS platform_admin_audit_no_update
        BEFORE UPDATE ON platform_admin_audit
        BEGIN
            SELECT RAISE(ABORT, 'platform_admin_audit is append-only');
        END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS platform_admin_audit_no_delete
        BEFORE DELETE ON platform_admin_audit
        BEGIN
            SELECT RAISE(ABORT, 'platform_admin_audit is append-only');
        END
        """
    )


def _skool_lifecycle_v1(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_skool_join_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            subject_user_id INTEGER NOT NULL,
            community_id TEXT NOT NULL,
            level_id TEXT NOT NULL,
            state TEXT NOT NULL,
            requested_by INTEGER NOT NULL,
            completed_by INTEGER,
            completion_source TEXT,
            external_mapping_id INTEGER,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id)
                REFERENCES platform_workspaces(id) ON DELETE CASCADE,
            FOREIGN KEY(subject_user_id)
                REFERENCES platform_users(id) ON DELETE CASCADE,
            FOREIGN KEY(requested_by) REFERENCES platform_users(id),
            FOREIGN KEY(completed_by) REFERENCES platform_users(id),
            FOREIGN KEY(external_mapping_id)
                REFERENCES platform_external_accounts(id),
            CHECK(state IN ('pending','completed','canceled')),
            CHECK(completion_source IS NULL OR completion_source IN (
                'manual_admin_invite','zapier_invite'
            )),
            CHECK(length(trim(community_id)) > 0),
            CHECK(length(trim(level_id)) > 0)
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_platform_skool_join_tasks_pending
        ON platform_skool_join_tasks(
            workspace_id,subject_user_id,community_id,level_id
        )
        WHERE state='pending'
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_skool_join_tasks_workspace
        ON platform_skool_join_tasks(workspace_id,state,created_at,id)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_skool_reconciliations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id INTEGER NOT NULL,
            community_id TEXT NOT NULL,
            artifact_hash TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            confidence TEXT NOT NULL,
            complete INTEGER NOT NULL,
            certainty TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            member_count INTEGER NOT NULL,
            mapped_member_count INTEGER NOT NULL,
            discrepancy_count INTEGER NOT NULL,
            conflict_count INTEGER NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id)
                REFERENCES platform_workspaces(id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES platform_users(id),
            CHECK(source IN ('operator_members_review')),
            CHECK(confidence IN ('confirmed','provisional','unverified')),
            CHECK(complete IN (0,1)),
            CHECK(certainty IN ('confirmed','uncertain','conflict')),
            CHECK(member_count >= 0),
            CHECK(mapped_member_count >= 0),
            CHECK(discrepancy_count >= 0),
            CHECK(conflict_count >= 0)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_skool_reconciliations_workspace
        ON platform_skool_reconciliations(
            workspace_id,community_id,observed_at,id
        )
        """
    )


ADMIN_CONTROL_MIGRATIONS = (
    Migration(
        1,
        "internal admin authority, external mappings, and atomic audit",
        _admin_controls_v1,
    ),
    Migration(
        2,
        "payload-free Skool join and current-state evidence",
        _skool_lifecycle_v1,
    ),
)


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    apply_migrations(
        connection,
        "platform-core",
        PLATFORM_MIGRATIONS,
    )
    apply_migrations(
        connection,
        "admin-controls",
        ADMIN_CONTROL_MIGRATIONS,
    )


__all__ = [
    "ADMIN_CONTROL_MIGRATIONS",
    "PLATFORM_MIGRATIONS",
    "PLATFORM_TABLES",
    "SCHEMA",
    "create_schema",
]
