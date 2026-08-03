"""Canonical inventory for the Phase 2 PostgreSQL schema."""

from __future__ import annotations

GLOBAL_TABLES = frozenset(
    {
        "schema_migrations",
        "users",
        "human_identities",
        "plans",
        "staff_roles",
        "oauth_clients",
        "internal_opportunities",
        "legacy_id_aliases",
    }
)

TENANT_TABLES = frozenset(
    {
        "workspaces",
        "memberships",
        "territories",
        "workspace_accounts",
        "connected_clients",
        "integration_events",
        "subscriptions",
        "access_grants",
        "oauth_sessions",
        "oauth_codes",
        "oauth_refresh_history",
        "external_accounts",
        "provider_events",
        "provider_event_attempts",
        "saved_searches",
        "search_runs",
        "search_results",
        "deals",
        "deal_notes",
        "deal_outcomes",
        "deal_events",
        "internal_opportunity_sources",
        "consents",
        "privacy_requests",
        "retention_actions",
        "staff_audit_log",
        "access_decision_audit",
        "tool_approvals",
        "daily_quota_usage",
        "jobs",
        "job_attempts",
    }
)

EXPECTED_TABLES = GLOBAL_TABLES | TENANT_TABLES
EXPECTED_RLS_TABLES = TENANT_TABLES | frozenset(
    {
        "users",
        "human_identities",
        "staff_roles",
        "internal_opportunities",
        "legacy_id_aliases",
    }
)
MIGRATION_MANAGED_TABLES = frozenset(
    {"schema_migrations", "plans", "oauth_clients"}
)
APP_TENANT_READ_TABLES = frozenset(
    {
        "memberships",
        "territories",
        "workspace_accounts",
        "saved_searches",
        "search_runs",
        "search_results",
        "deal_outcomes",
        "deal_events",
        "consents",
        "privacy_requests",
    }
)
APP_COLUMN_READS = {
    "subscriptions": frozenset(
        {
            "id",
            "workspace_id",
            "provider",
            "status",
            "plan_key",
            "current_period_end",
            "last_event_at",
            "created_at",
            "updated_at",
        }
    ),
    "access_grants": frozenset(
        {
            "id",
            "workspace_id",
            "subject_user_id",
            "scope",
            "source",
            "profile",
            "plan_key",
            "status",
            "starts_at",
            "ends_at",
            "created_at",
            "updated_at",
        }
    ),
    "deals": frozenset(
        {
            "id",
            "workspace_id",
            "source",
            "source_record_id",
            "title",
            "listing",
            "asking_price",
            "stage",
            "score",
            "score_version",
            "grade",
            "strategy",
            "next_action",
            "next_action_due",
            "created_at",
            "updated_at",
        }
    ),
    "deal_notes": frozenset(
        {
            "id",
            "workspace_id",
            "deal_id",
            "body",
            "created_at",
            "updated_at",
        }
    ),
}
APP_WRITE_TABLES = frozenset(
    {
        "saved_searches",
        "deals",
        "deal_notes",
        "deal_outcomes",
        "consents",
        "privacy_requests",
    }
)
APP_READ_TABLES = APP_TENANT_READ_TABLES | frozenset(
    {"schema_migrations", "plans", "oauth_clients", "users", "workspaces"}
)
CONTROL_PLANE_TABLES = frozenset(
    {"access_decision_audit", "tool_approvals", "daily_quota_usage"}
)
ADMIN_COLUMN_READS = {
    "human_identities": frozenset(
        {
            "id",
            "user_id",
            "provider",
            "subject_hint",
            "verified_at",
            "created_at",
            "updated_at",
        }
    ),
    "subscriptions": APP_COLUMN_READS["subscriptions"],
    "access_grants": APP_COLUMN_READS["access_grants"],
    "oauth_sessions": frozenset(
        {
            "id",
            "workspace_id",
            "user_id",
            "client_id",
            "scopes",
            "audience",
            "resource",
            "authority_version",
            "access_expires_at",
            "refresh_expires_at",
            "refresh_family_expires_at",
            "revoked_at",
            "created_at",
            "updated_at",
        }
    ),
    "oauth_codes": frozenset(
        {
            "id",
            "workspace_id",
            "user_id",
            "client_id",
            "session_id",
            "redirect_uri",
            "scopes",
            "audience",
            "resource",
            "authority_version",
            "expires_at",
            "consumed_at",
            "created_at",
        }
    ),
    "oauth_refresh_history": frozenset(
        {"workspace_id", "session_id", "rotated_at"}
    ),
    "external_accounts": frozenset(
        {
            "id",
            "workspace_id",
            "subject_user_id",
            "provider",
            "created_at",
            "updated_at",
        }
    ),
    "provider_events": frozenset(
        {
            "id",
            "workspace_id",
            "provider",
            "canonical_action",
            "outcome",
            "reason_code",
            "duplicate_count",
            "replayed_at",
            "occurred_at",
            "created_at",
            "updated_at",
        }
    ),
    "integration_events": frozenset(
        {
            "id",
            "workspace_id",
            "client_id",
            "event_type",
            "occurred_at",
            "created_at",
        }
    ),
    "tool_approvals": frozenset(
        {
            "id",
            "workspace_id",
            "subject_user_id",
            "tool_name",
            "request_correlation_id",
            "issued_at",
            "expires_at",
            "consumed_at",
            "revoked_at",
        }
    ),
}
ADMIN_READ_TABLES = EXPECTED_TABLES - frozenset(ADMIN_COLUMN_READS)
SERVICE_OWNED_TABLES = frozenset(
    {
        "human_identities",
        "integration_events",
        "subscriptions",
        "access_grants",
        "oauth_sessions",
        "oauth_codes",
        "oauth_refresh_history",
        "external_accounts",
        "provider_events",
        "provider_event_attempts",
    }
)
IMMUTABLE_TABLES = frozenset(
    {"staff_audit_log", "access_decision_audit", "legacy_id_aliases"}
)
ADMIN_INSERT_ONLY_TABLES = frozenset({"staff_audit_log"})
ADMIN_MUTATION_TABLES = (
    EXPECTED_TABLES
    - MIGRATION_MANAGED_TABLES
    - CONTROL_PLANE_TABLES
    - SERVICE_OWNED_TABLES
    - IMMUTABLE_TABLES
)
EXPECTED_MIGRATION_VERSION = 1
SCHEMA_NAME = "medawarcre"

# Generated from ``catalog.catalog_fingerprint()`` on the reviewed PostgreSQL
# 16 launch schema. Any schema migration must update this value deliberately.
EXPECTED_CATALOG_FINGERPRINT = (
    "9b37f7be63bb844354a1d7c6d39318abe703aaa33286bce5edd25ffcca9f7b0c"
)

__all__ = [
    "EXPECTED_MIGRATION_VERSION",
    "EXPECTED_CATALOG_FINGERPRINT",
    "EXPECTED_RLS_TABLES",
    "EXPECTED_TABLES",
    "GLOBAL_TABLES",
    "ADMIN_MUTATION_TABLES",
    "ADMIN_INSERT_ONLY_TABLES",
    "ADMIN_COLUMN_READS",
    "ADMIN_READ_TABLES",
    "APP_READ_TABLES",
    "APP_COLUMN_READS",
    "APP_TENANT_READ_TABLES",
    "APP_WRITE_TABLES",
    "CONTROL_PLANE_TABLES",
    "IMMUTABLE_TABLES",
    "MIGRATION_MANAGED_TABLES",
    "SCHEMA_NAME",
    "SERVICE_OWNED_TABLES",
    "TENANT_TABLES",
]
