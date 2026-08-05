REVOKE ALL ON SCHEMA medawarcre
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth, medawarcre_provider_ingress,
     medawarcre_provider_reconcile, medawarcre_worker, medawarcre_scheduler;
GRANT USAGE ON SCHEMA medawarcre
TO medawarcre_app, medawarcre_admin, medawarcre_backup, medawarcre_admission,
   medawarcre_oauth;

REVOKE ALL ON ALL TABLES IN SCHEMA medawarcre
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth, medawarcre_provider_ingress,
     medawarcre_provider_reconcile, medawarcre_worker, medawarcre_scheduler;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA medawarcre
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth, medawarcre_provider_ingress,
     medawarcre_provider_reconcile, medawarcre_worker, medawarcre_scheduler;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA medawarcre
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth, medawarcre_provider_ingress,
     medawarcre_provider_reconcile, medawarcre_worker, medawarcre_scheduler;

GRANT SELECT ON medawarcre.schema_migrations,
                medawarcre.plans,
                medawarcre.oauth_clients,
                medawarcre.users,
                medawarcre.workspaces
TO medawarcre_app;
GRANT SELECT ON
    medawarcre.memberships,
    medawarcre.territories,
    medawarcre.workspace_accounts,
    medawarcre.saved_searches,
    medawarcre.search_runs,
    medawarcre.search_results,
    medawarcre.deal_outcomes,
    medawarcre.deal_events,
    medawarcre.consents,
    medawarcre.privacy_requests
TO medawarcre_app;
GRANT SELECT (
    id, workspace_id, provider, status, plan_key, current_period_end,
    last_event_at, created_at, updated_at
) ON medawarcre.subscriptions TO medawarcre_app;
GRANT SELECT (
    id, workspace_id, subject_user_id, scope, source, profile, plan_key,
    status, starts_at, ends_at, created_at, updated_at
) ON medawarcre.access_grants TO medawarcre_app;
GRANT SELECT (
    id, workspace_id, source, source_record_id, title, listing, asking_price,
    stage, score, score_version, grade, strategy, next_action, next_action_due,
    created_at, updated_at
) ON medawarcre.deals TO medawarcre_app;
GRANT SELECT (
    id, workspace_id, deal_id, body, created_at, updated_at
) ON medawarcre.deal_notes TO medawarcre_app;
GRANT INSERT, UPDATE, DELETE ON
    medawarcre.saved_searches,
    medawarcre.deals,
    medawarcre.deal_notes,
    medawarcre.deal_outcomes,
    medawarcre.consents,
    medawarcre.privacy_requests
TO medawarcre_app;

GRANT SELECT ON
    medawarcre.schema_migrations,
    medawarcre.users,
    medawarcre.plans,
    medawarcre.staff_roles,
    medawarcre.oauth_clients,
    medawarcre.internal_opportunities,
    medawarcre.legacy_id_aliases,
    medawarcre.workspaces,
    medawarcre.memberships,
    medawarcre.territories,
    medawarcre.workspace_accounts,
    medawarcre.connected_clients,
    medawarcre.provider_event_attempts,
    medawarcre.saved_searches,
    medawarcre.search_runs,
    medawarcre.search_results,
    medawarcre.deals,
    medawarcre.deal_notes,
    medawarcre.deal_outcomes,
    medawarcre.deal_events,
    medawarcre.internal_opportunity_sources,
    medawarcre.consents,
    medawarcre.privacy_requests,
    medawarcre.retention_actions,
    medawarcre.staff_audit_log,
    medawarcre.access_decision_audit,
    medawarcre.daily_quota_usage,
    medawarcre.jobs,
    medawarcre.job_attempts
TO medawarcre_admin;
GRANT SELECT (
    id, user_id, provider, subject_hint, verified_at, created_at, updated_at
) ON medawarcre.human_identities TO medawarcre_admin;
GRANT SELECT (
    id, workspace_id, provider, status, plan_key, current_period_end,
    last_event_at, created_at, updated_at
) ON medawarcre.subscriptions TO medawarcre_admin;
GRANT SELECT (
    id, workspace_id, subject_user_id, scope, source, profile, plan_key,
    status, starts_at, ends_at, created_at, updated_at
) ON medawarcre.access_grants TO medawarcre_admin;
GRANT SELECT (
    id, workspace_id, user_id, client_id, scopes, audience, resource,
    authority_version, access_expires_at, refresh_expires_at,
    refresh_family_expires_at, revoked_at, created_at, updated_at
) ON medawarcre.oauth_sessions TO medawarcre_admin;
GRANT SELECT (
    id, workspace_id, user_id, client_id, session_id, redirect_uri, scopes,
    audience, resource, authority_version, expires_at, consumed_at, created_at
) ON medawarcre.oauth_codes TO medawarcre_admin;
GRANT SELECT (
    workspace_id, session_id, rotated_at
) ON medawarcre.oauth_refresh_history TO medawarcre_admin;
GRANT SELECT (
    id, workspace_id, subject_user_id, provider, created_at, updated_at
) ON medawarcre.external_accounts TO medawarcre_admin;
GRANT SELECT (
    id, workspace_id, provider, canonical_action, outcome, reason_code,
    duplicate_count, replayed_at, occurred_at, created_at, updated_at
) ON medawarcre.provider_events TO medawarcre_admin;
GRANT SELECT (
    id, workspace_id, client_id, event_type, occurred_at, created_at
) ON medawarcre.integration_events TO medawarcre_admin;
GRANT SELECT (
    id, workspace_id, subject_user_id, tool_name, request_correlation_id,
    issued_at, expires_at, consumed_at, revoked_at
) ON medawarcre.tool_approvals TO medawarcre_admin;
GRANT SELECT (
    id, user_id, expires_at, revoked_at, created_at, updated_at
) ON medawarcre.browser_sessions TO medawarcre_admin;
GRANT SELECT (
    id, user_id, expires_at, revoked_at, created_at, updated_at
) ON medawarcre.operator_sessions TO medawarcre_admin;
GRANT SELECT (
    id, client_id, redirect_uri, scopes, audience, resource,
    expires_at, consumed_at, created_at
) ON medawarcre.oauth_authorization_requests TO medawarcre_admin;
GRANT SELECT ON medawarcre.skool_join_tasks TO medawarcre_admin;
GRANT SELECT (
    id, workspace_id, community_id, source, observed_at, confidence,
    complete, certainty, reason_code, member_count, mapped_member_count,
    discrepancy_count, conflict_count, created_by, created_at
) ON medawarcre.skool_reconciliations TO medawarcre_admin;
GRANT INSERT, UPDATE, DELETE ON
    medawarcre.users,
    medawarcre.workspaces,
    medawarcre.memberships,
    medawarcre.staff_roles,
    medawarcre.territories,
    medawarcre.workspace_accounts,
    medawarcre.connected_clients,
    medawarcre.saved_searches,
    medawarcre.search_runs,
    medawarcre.search_results,
    medawarcre.deals,
    medawarcre.deal_notes,
    medawarcre.deal_outcomes,
    medawarcre.deal_events,
    medawarcre.internal_opportunities,
    medawarcre.internal_opportunity_sources,
    medawarcre.consents,
    medawarcre.privacy_requests,
    medawarcre.retention_actions,
    medawarcre.jobs,
    medawarcre.job_attempts
TO medawarcre_admin;
GRANT INSERT ON medawarcre.staff_audit_log TO medawarcre_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA medawarcre TO medawarcre_backup;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA medawarcre
TO medawarcre_app, medawarcre_admin;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA medawarcre TO medawarcre_backup;

GRANT EXECUTE ON FUNCTION medawarcre.current_workspace_id()
TO medawarcre_app, medawarcre_admin;
GRANT EXECUTE ON FUNCTION medawarcre.current_actor_user_id()
TO medawarcre_app, medawarcre_admin;
GRANT EXECUTE ON FUNCTION medawarcre.internal_authorized() TO medawarcre_admin;
GRANT EXECUTE ON FUNCTION medawarcre.internal_can_mutate() TO medawarcre_admin;
GRANT EXECUTE ON FUNCTION medawarcre.atomic_admit_tool_call(
    uuid, uuid, text, uuid, uuid, text, text, text, text, text[], text,
    bytea, text, boolean, bytea
) TO medawarcre_admission;
GRANT EXECUTE ON FUNCTION medawarcre.record_tool_call_final(
    uuid, uuid, text, uuid, uuid, text, boolean, text, text
) TO medawarcre_admission;
GRANT EXECUTE ON FUNCTION medawarcre.bind_admitted_request(
    uuid, uuid, text, uuid, uuid, text
) TO medawarcre_app;
GRANT EXECUTE ON FUNCTION medawarcre.resolve_oauth_authority(
    bytea, text, text
) TO medawarcre_oauth;

ALTER DEFAULT PRIVILEGES FOR ROLE medawarcre_migration IN SCHEMA medawarcre
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE medawarcre_migration IN SCHEMA medawarcre
    GRANT SELECT ON TABLES TO medawarcre_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE medawarcre_migration IN SCHEMA medawarcre
    REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE medawarcre_migration IN SCHEMA medawarcre
    GRANT SELECT ON SEQUENCES TO medawarcre_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE medawarcre_migration
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE medawarcre_migration
    REVOKE USAGE ON TYPES FROM PUBLIC;
