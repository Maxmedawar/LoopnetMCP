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

#: The hosted platform authority tables, ported from the SQLite ``platform_*``
#: schema by migration 0010 so the hosted process can boot on PostgreSQL.
#:
#: They are deliberately kept out of the certified role model below. These are
#: the identity and authority stores that run *before* a workspace context
#: exists — sign-in, OAuth, session issue — so there is no ``app.workspace_id``
#: for row-level security to filter on, and no tenant grant shape for the
#: certified ``APP_*``/``ADMIN_*`` sets to describe. Their tenancy is enforced
#: in the store code, exactly as it was under SQLite; migration 0010 grants the
#: application role table privileges directly and enables no RLS on them.
PLATFORM_AUTHORITY_TABLES = frozenset(
    {
        "platform_access_grants",
        "platform_accounts",
        "platform_admin_audit",
        "platform_browser_sessions",
        "platform_connected_clients",
        "platform_consents",
        "platform_external_accounts",
        "platform_human_identities",
        "platform_integration_events",
        "platform_internal_admins",
        "platform_memberships",
        "platform_notes",
        "platform_oauth_authorization_requests",
        "platform_oauth_clients",
        "platform_oauth_codes",
        "platform_oauth_refresh_history",
        "platform_oauth_sessions",
        "platform_operator_sessions",
        "platform_outcomes",
        "platform_plans",
        "platform_privacy_requests",
        "platform_provider_event_attempts",
        "platform_provider_events",
        "platform_saved_deals",
        "platform_schema_versions",
        "platform_skool_join_tasks",
        "platform_skool_reconciliations",
        "platform_subscriptions",
        "platform_territories",
        "platform_users",
        "platform_workspaces",
    }
)

#: Platform authority tables the application role may fully mutate. It is the
#: whole set minus the append-only audit, which it may only read and append.
PLATFORM_APP_MUTABLE_TABLES = PLATFORM_AUTHORITY_TABLES - frozenset(
    {"platform_admin_audit"}
)

#: Platform-layer relations the application role may read and append but never
#: change or remove. Their triggers refuse UPDATE and DELETE as a second layer.
PLATFORM_APP_APPEND_ONLY_TABLES = frozenset({"platform_admin_audit"})

#: The durable access-decision audit sink (migration 0011). Not a tenant table:
#: its workspace column is the public identifier string, not a uuid, because
#: the ``AuditLog`` interface it implements has no uuid to offer.
AUDIT_SINK_TABLES = frozenset({"access_audit_log"})

#: Everything the certified Phase 2 role model describes. The ``APP_*`` and
#: ``ADMIN_*`` sets below derive from this, not from ``EXPECTED_TABLES``, so
#: adding a platform authority table does not silently widen a certified grant.
CERTIFIED_TABLES = GLOBAL_TABLES | TENANT_TABLES

EXPECTED_TABLES = CERTIFIED_TABLES | PLATFORM_AUTHORITY_TABLES | AUDIT_SINK_TABLES
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
ADMIN_READ_TABLES = CERTIFIED_TABLES - frozenset(ADMIN_COLUMN_READS)
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
    CERTIFIED_TABLES
    - MIGRATION_MANAGED_TABLES
    - CONTROL_PLANE_TABLES
    - SERVICE_OWNED_TABLES
    - IMMUTABLE_TABLES
)
EXPECTED_MIGRATION_VERSION = 12
SCHEMA_NAME = "medawarcre"

# Generated from ``catalog.catalog_fingerprint()`` on the reviewed PostgreSQL
# launch schema. Any schema migration must update this value deliberately.
# Moved at migrations 0010 (platform authority), 0011 (access audit log) and
# 0012 (identity projection). Superseded values, kept visible:
# e452f1486a6d2c22731b0f854498d9a4728a9375ac602a5ab217629265a1cbf6 (0009),
# 7a4c98bfa5d0e4c1df810091c6507a3b955860486a6d531dfd2e880dc49d7f56 (0011).
EXPECTED_CATALOG_FINGERPRINT = (
    "1b1474a0b1d5d693d1141a44dbb287ae26b607ace3d48e70a803789999dd6439"
)

__all__ = [
    "EXPECTED_MIGRATION_VERSION",
    "EXPECTED_CATALOG_FINGERPRINT",
    "AUDIT_SINK_TABLES",
    "CERTIFIED_TABLES",
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
    "PLATFORM_APP_APPEND_ONLY_TABLES",
    "PLATFORM_APP_MUTABLE_TABLES",
    "PLATFORM_AUTHORITY_TABLES",
    "SCHEMA_NAME",
    "SERVICE_OWNED_TABLES",
    "TENANT_TABLES",
]
