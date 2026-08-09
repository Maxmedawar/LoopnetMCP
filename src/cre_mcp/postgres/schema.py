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
        "browser_sessions",
        "operator_sessions",
        "oauth_authorization_requests",
        "internal_opportunities",
        "internal_opportunity_reviews",
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
        "source_document_attestations",
        "truth_document_blobs",
        "truth_documents",
        "truth_claims",
        "skool_join_tasks",
        "skool_reconciliations",
        "external_accounts",
        "provider_events",
        "provider_event_attempts",
        "saved_searches",
        "saved_search_seen_matches",
        "search_runs",
        "search_results",
        "deals",
        "deal_notes",
        "deal_outcomes",
        "deal_events",
        "deal_dd_items",
        "deal_ops_events",
        "deal_investors",
        "deal_commitments",
        "deal_exchanges",
        "deal_exchange_replacements",
        "deal_ic_decisions",
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
        "browser_sessions",
        "operator_sessions",
        "oauth_authorization_requests",
        "internal_opportunities",
        "internal_opportunity_reviews",
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
        "saved_search_seen_matches",
        "search_runs",
        "search_results",
        "consents",
        "privacy_requests",
        "source_document_attestations",
        "truth_documents",
        "truth_claims",
    }
)
APP_COLUMN_READS = {
    "truth_document_blobs": frozenset({"workspace_id", "document_id"}),
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
            "listing",
            "stage",
            "score",
            "grade",
            "strategy",
            "accountability_owner",
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
            "stage",
            "created_at",
        }
    ),
    "deal_outcomes": frozenset(
        {
            "workspace_id",
            "deal_id",
            "closed",
            "purchase_price",
            "realized_hold_years",
            "realized_irr",
            "realized_equity_multiple",
            "went_bad",
            "notes",
            "predicted_score",
            "predicted_grade",
            "predicted_strategy",
            "created_at",
            "updated_at",
        }
    ),
    "deal_events": frozenset(
        {
            "id",
            "workspace_id",
            "deal_id",
            "event_type",
            "event_data",
            "occurred_at",
            "created_at",
            "request_invocation_id",
        }
    ),
    "deal_dd_items": frozenset(
        {"workspace_id", "deal_id", "item_key", "item_data", "status", "deadline"}
    ),
    "deal_ops_events": frozenset(
        {
            "workspace_id",
            "deal_id",
            "event_key",
            "event_data",
            "category",
            "event_date",
            "status",
        }
    ),
    "deal_investors": frozenset(
        {
            "id",
            "workspace_id",
            "name",
            "accredited",
            "accreditation_verified",
            "relationship",
            "contact",
            "created_at",
            "updated_at",
        }
    ),
    "deal_commitments": frozenset(
        {
            "id",
            "workspace_id",
            "deal_id",
            "investor_id",
            "amount",
            "created_at",
            "updated_at",
        }
    ),
    "deal_exchanges": frozenset(
        {
            "id",
            "workspace_id",
            "relinquished_deal_id",
            "relinquished_close_date",
            "identification_deadline",
            "exchange_deadline",
            "created_at",
            "updated_at",
        }
    ),
    "deal_exchange_replacements": frozenset(
        {"workspace_id", "exchange_id", "deal_id", "value", "identified_at"}
    ),
    "deal_ic_decisions": frozenset(
        {
            "id",
            "workspace_id",
            "deal_id",
            "system_verdict",
            "system_data",
            "expert_verdict",
            "expert_data",
            "agreed",
            "created_at",
            "request_invocation_id",
        }
    ),
}
APP_WRITE_TABLES = frozenset(
    {
        "consents",
        "privacy_requests",
        "truth_documents",
        "truth_claims",
    }
)
APP_INSERT_ONLY_TABLES = frozenset(
    {"truth_document_blobs", "saved_searches", "saved_search_seen_matches"}
)
APP_COLUMN_INSERTS = {
    "deals": frozenset(
        {
            "workspace_id", "source", "source_record_id", "title", "listing",
            "asking_price", "stage", "score", "grade", "strategy", "source_rights_id",
            "source_rights_verified_on", "created_by_user_id", "updated_by_user_id",
        }
    ),
    "deal_notes": frozenset(
        {"workspace_id", "deal_id", "author_user_id", "body", "stage"}
    ),
    "deal_outcomes": frozenset(
        {
            "workspace_id", "deal_id", "closed", "purchase_price",
            "realized_hold_years", "realized_irr", "realized_equity_multiple",
            "went_bad", "notes", "predicted_score", "predicted_grade",
            "predicted_strategy", "created_by_user_id", "updated_by_user_id",
        }
    ),
    "deal_events": frozenset(
        {
            "workspace_id", "deal_id", "event_type", "event_data", "occurred_at",
            "author_user_id", "request_invocation_id",
        }
    ),
    "deal_dd_items": frozenset(
        {
            "workspace_id", "deal_id", "item_key", "item_data", "status",
            "deadline", "created_by_user_id", "updated_by_user_id",
        }
    ),
    "deal_ops_events": frozenset(
        {
            "workspace_id", "deal_id", "event_key", "event_data", "category",
            "event_date", "status", "created_by_user_id", "updated_by_user_id",
        }
    ),
    "deal_investors": frozenset(
        {
            "workspace_id", "name", "accredited", "accreditation_verified",
            "relationship", "contact", "created_by_user_id", "updated_by_user_id",
        }
    ),
    "deal_commitments": frozenset(
        {
            "workspace_id", "deal_id", "investor_id", "amount",
            "created_by_user_id", "updated_by_user_id",
        }
    ),
    "deal_exchanges": frozenset(
        {
            "workspace_id", "relinquished_deal_id", "relinquished_close_date",
            "identification_deadline", "exchange_deadline", "created_by_user_id",
            "updated_by_user_id",
        }
    ),
    "deal_exchange_replacements": frozenset(
        {
            "workspace_id", "exchange_id", "deal_id", "value", "identified_at",
            "created_by_user_id",
        }
    ),
    "deal_ic_decisions": frozenset(
        {
            "workspace_id", "deal_id", "system_verdict", "system_data",
            "expert_verdict", "expert_data", "agreed", "created_by_user_id",
            "request_invocation_id",
        }
    ),
}
APP_COLUMN_UPDATES = {
    "deals": frozenset(
        {
            "title", "listing", "asking_price", "stage", "score", "grade",
            "strategy", "accountability_owner", "next_action", "next_action_due",
            "source_rights_id", "source_rights_verified_on", "updated_by_user_id",
            "updated_at",
        }
    ),
    "deal_outcomes": frozenset(
        {
            "closed", "purchase_price", "realized_hold_years", "realized_irr",
            "realized_equity_multiple", "went_bad", "notes", "updated_by_user_id",
            "updated_at",
        }
    ),
    "deal_dd_items": frozenset(
        {"item_data", "deadline", "updated_by_user_id", "updated_at"}
    ),
    "deal_ops_events": frozenset(
        {"event_data", "category", "event_date", "updated_by_user_id", "updated_at"}
    ),
    "deal_commitments": frozenset({"amount", "updated_by_user_id", "updated_at"}),
    "deal_exchanges": frozenset(
        {"identification_deadline", "exchange_deadline", "updated_by_user_id", "updated_at"}
    ),
}
APP_DELETE_TABLES = frozenset({"deal_dd_items", "deal_ops_events"})
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
    "browser_sessions": frozenset(
        {
            "id",
            "user_id",
            "expires_at",
            "revoked_at",
            "created_at",
            "updated_at",
        }
    ),
    "operator_sessions": frozenset(
        {
            "id",
            "user_id",
            "expires_at",
            "revoked_at",
            "created_at",
            "updated_at",
        }
    ),
    "oauth_authorization_requests": frozenset(
        {
            "id",
            "client_id",
            "redirect_uri",
            "scopes",
            "audience",
            "resource",
            "expires_at",
            "consumed_at",
            "created_at",
        }
    ),
    "skool_reconciliations": frozenset(
        {
            "id",
            "workspace_id",
            "community_id",
            "source",
            "observed_at",
            "confidence",
            "complete",
            "certainty",
            "reason_code",
            "member_count",
            "mapped_member_count",
            "discrepancy_count",
            "conflict_count",
            "created_by",
            "created_at",
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
        "browser_sessions",
        "operator_sessions",
        "oauth_authorization_requests",
        "external_accounts",
        "provider_events",
        "provider_event_attempts",
        "skool_join_tasks",
        "skool_reconciliations",
        "source_document_attestations",
    }
)
IMMUTABLE_TABLES = frozenset(
    {
        "staff_audit_log",
        "access_decision_audit",
        "legacy_id_aliases",
        "internal_opportunity_reviews",
    }
)
ADMIN_INSERT_ONLY_TABLES = frozenset(
    {"staff_audit_log", "internal_opportunity_reviews"}
)
ADMIN_MUTATION_TABLES = (
    EXPECTED_TABLES
    - MIGRATION_MANAGED_TABLES
    - CONTROL_PLANE_TABLES
    - SERVICE_OWNED_TABLES
    - IMMUTABLE_TABLES
)
EXPECTED_MIGRATION_VERSION = 9
SCHEMA_NAME = "medawarcre"

# Generated from ``catalog.catalog_fingerprint()`` on the reviewed PostgreSQL
# 16 launch schema. Any schema migration must update this value deliberately.
EXPECTED_CATALOG_FINGERPRINT = (
    "e452f1486a6d2c22731b0f854498d9a4728a9375ac602a5ab217629265a1cbf6"
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
    "APP_COLUMN_INSERTS",
    "APP_COLUMN_UPDATES",
    "APP_DELETE_TABLES",
    "APP_TENANT_READ_TABLES",
    "APP_WRITE_TABLES",
    "APP_INSERT_ONLY_TABLES",
    "CONTROL_PLANE_TABLES",
    "IMMUTABLE_TABLES",
    "MIGRATION_MANAGED_TABLES",
    "SCHEMA_NAME",
    "SERVICE_OWNED_TABLES",
    "TENANT_TABLES",
]
