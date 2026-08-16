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
    medawarcre.saved_search_seen_matches,
    medawarcre.search_runs,
    medawarcre.search_results,
    medawarcre.consents,
    medawarcre.privacy_requests,
    medawarcre.source_document_attestations,
    medawarcre.truth_documents,
    medawarcre.truth_claims
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
    id, workspace_id, source, source_record_id, listing, stage, score, grade,
    strategy, accountability_owner, next_action, next_action_due,
    created_at, updated_at
) ON medawarcre.deals TO medawarcre_app;
GRANT INSERT (
    workspace_id, source, source_record_id, title, listing, asking_price,
    stage, score, grade, strategy, source_rights_id, source_rights_verified_on,
    created_by_user_id, updated_by_user_id
) ON medawarcre.deals TO medawarcre_app;
GRANT UPDATE (
    title, listing, asking_price, stage, score, grade, strategy,
    accountability_owner, next_action, next_action_due, source_rights_id,
    source_rights_verified_on, updated_by_user_id, updated_at
) ON medawarcre.deals TO medawarcre_app;
GRANT SELECT (
    id, workspace_id, deal_id, body, stage, created_at
) ON medawarcre.deal_notes TO medawarcre_app;
GRANT INSERT (workspace_id, deal_id, author_user_id, body, stage)
ON medawarcre.deal_notes TO medawarcre_app;
GRANT SELECT (
    workspace_id, deal_id, closed, purchase_price, realized_hold_years,
    realized_irr, realized_equity_multiple, went_bad, notes, predicted_score,
    predicted_grade, predicted_strategy, created_at, updated_at
) ON medawarcre.deal_outcomes TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, closed, purchase_price, realized_hold_years,
    realized_irr, realized_equity_multiple, went_bad, notes, predicted_score,
    predicted_grade, predicted_strategy, created_by_user_id, updated_by_user_id
) ON medawarcre.deal_outcomes TO medawarcre_app;
GRANT UPDATE (
    closed, purchase_price, realized_hold_years, realized_irr,
    realized_equity_multiple, went_bad, notes, updated_by_user_id, updated_at
) ON medawarcre.deal_outcomes TO medawarcre_app;
GRANT SELECT (
    id, workspace_id, deal_id, event_type, event_data, occurred_at, created_at,
    request_invocation_id
) ON medawarcre.deal_events TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, event_type, event_data, occurred_at,
    author_user_id, request_invocation_id
) ON medawarcre.deal_events TO medawarcre_app;
GRANT SELECT (workspace_id, deal_id, item_key, item_data, status, deadline)
ON medawarcre.deal_dd_items TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, item_key, item_data, status, deadline,
    created_by_user_id, updated_by_user_id
) ON medawarcre.deal_dd_items TO medawarcre_app;
GRANT UPDATE (item_data, deadline, updated_by_user_id, updated_at)
ON medawarcre.deal_dd_items TO medawarcre_app;
GRANT DELETE ON medawarcre.deal_dd_items TO medawarcre_app;
GRANT SELECT (
    workspace_id, deal_id, event_key, event_data, category, event_date, status
) ON medawarcre.deal_ops_events TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, event_key, event_data, category, event_date, status,
    created_by_user_id, updated_by_user_id
) ON medawarcre.deal_ops_events TO medawarcre_app;
GRANT UPDATE (event_data, category, event_date, updated_by_user_id, updated_at)
ON medawarcre.deal_ops_events TO medawarcre_app;
GRANT DELETE ON medawarcre.deal_ops_events TO medawarcre_app;
GRANT SELECT (
    id, workspace_id, name, accredited, accreditation_verified, relationship,
    contact, created_at, updated_at
) ON medawarcre.deal_investors TO medawarcre_app;
GRANT INSERT (
    workspace_id, name, accredited, accreditation_verified, relationship,
    contact, created_by_user_id, updated_by_user_id
) ON medawarcre.deal_investors TO medawarcre_app;
GRANT SELECT (
    id, workspace_id, deal_id, investor_id, amount, created_at, updated_at
) ON medawarcre.deal_commitments TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, investor_id, amount, created_by_user_id,
    updated_by_user_id
) ON medawarcre.deal_commitments TO medawarcre_app;
GRANT UPDATE (amount, updated_by_user_id, updated_at)
ON medawarcre.deal_commitments TO medawarcre_app;
GRANT SELECT (
    id, workspace_id, relinquished_deal_id, relinquished_close_date,
    identification_deadline, exchange_deadline, created_at, updated_at
) ON medawarcre.deal_exchanges TO medawarcre_app;
GRANT INSERT (
    workspace_id, relinquished_deal_id, relinquished_close_date,
    identification_deadline, exchange_deadline, created_by_user_id,
    updated_by_user_id
) ON medawarcre.deal_exchanges TO medawarcre_app;
GRANT UPDATE (
    identification_deadline, exchange_deadline, updated_by_user_id, updated_at
) ON medawarcre.deal_exchanges TO medawarcre_app;
GRANT SELECT (workspace_id, exchange_id, deal_id, value, identified_at)
ON medawarcre.deal_exchange_replacements TO medawarcre_app;
GRANT INSERT (
    workspace_id, exchange_id, deal_id, value, identified_at, created_by_user_id
) ON medawarcre.deal_exchange_replacements TO medawarcre_app;
GRANT SELECT (
    id, workspace_id, deal_id, system_verdict, system_data, expert_verdict,
    expert_data, agreed, created_at, request_invocation_id
) ON medawarcre.deal_ic_decisions TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, system_verdict, system_data, expert_verdict,
    expert_data, agreed, created_by_user_id, request_invocation_id
) ON medawarcre.deal_ic_decisions TO medawarcre_app;
GRANT INSERT, UPDATE, DELETE ON
    medawarcre.consents,
    medawarcre.privacy_requests
TO medawarcre_app;
GRANT INSERT ON
    medawarcre.saved_searches,
    medawarcre.saved_search_seen_matches
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
    medawarcre.saved_search_seen_matches,
    medawarcre.search_runs,
    medawarcre.search_results,
    medawarcre.deals,
    medawarcre.deal_notes,
    medawarcre.deal_outcomes,
    medawarcre.deal_events,
    medawarcre.deal_dd_items,
    medawarcre.deal_ops_events,
    medawarcre.deal_investors,
    medawarcre.deal_commitments,
    medawarcre.deal_exchanges,
    medawarcre.deal_exchange_replacements,
    medawarcre.deal_ic_decisions,
    medawarcre.internal_opportunity_sources,
    medawarcre.internal_opportunity_reviews,
    medawarcre.consents,
    medawarcre.privacy_requests,
    medawarcre.retention_actions,
    medawarcre.staff_audit_log,
    medawarcre.access_decision_audit,
    medawarcre.daily_quota_usage,
    medawarcre.jobs,
    medawarcre.job_attempts,
    medawarcre.source_document_attestations,
    medawarcre.truth_document_blobs,
    medawarcre.truth_documents,
    medawarcre.truth_claims
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
    medawarcre.saved_search_seen_matches,
    medawarcre.search_runs,
    medawarcre.search_results,
    medawarcre.deals,
    medawarcre.deal_notes,
    medawarcre.deal_outcomes,
    medawarcre.deal_events,
    medawarcre.deal_dd_items,
    medawarcre.deal_ops_events,
    medawarcre.deal_investors,
    medawarcre.deal_commitments,
    medawarcre.deal_exchanges,
    medawarcre.deal_exchange_replacements,
    medawarcre.deal_ic_decisions,
    medawarcre.internal_opportunities,
    medawarcre.internal_opportunity_sources,
    medawarcre.consents,
    medawarcre.privacy_requests,
    medawarcre.retention_actions,
    medawarcre.jobs,
    medawarcre.job_attempts,
    medawarcre.truth_document_blobs,
    medawarcre.truth_documents,
    medawarcre.truth_claims
TO medawarcre_admin;
GRANT SELECT (workspace_id, document_id), INSERT
ON medawarcre.truth_document_blobs TO medawarcre_app;
GRANT INSERT, UPDATE, DELETE ON
    medawarcre.truth_documents,
    medawarcre.truth_claims
TO medawarcre_app;
GRANT INSERT ON medawarcre.staff_audit_log TO medawarcre_admin;
-- Append-only, like the staff audit log: SELECT and INSERT only, and the
-- table's triggers reject UPDATE and DELETE.
GRANT INSERT ON medawarcre.internal_opportunity_reviews TO medawarcre_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA medawarcre TO medawarcre_backup;
-- No sequence grant to the application or admin roles. Before migration 0010
-- the schema had no sequences at all -- every key was a uuid -- so this line
-- was a no-op that happened to match. 0010 and 0011 introduced twenty-seven
-- IDENTITY sequences, which PostgreSQL drives internally and which therefore
-- need no USAGE grant; re-granting them here made the restored catalog differ
-- from the source it was dumped from, and the fingerprint check caught it.
-- The backup role's SELECT below is kept because ALTER DEFAULT PRIVILEGES
-- already gives new sequences exactly that, so the two agree.
GRANT SELECT ON ALL SEQUENCES IN SCHEMA medawarcre TO medawarcre_backup;

GRANT EXECUTE ON FUNCTION medawarcre.current_workspace_id()
TO medawarcre_app, medawarcre_admin;
GRANT EXECUTE ON FUNCTION medawarcre.current_actor_user_id()
TO medawarcre_app, medawarcre_admin;
GRANT EXECUTE ON FUNCTION medawarcre.current_oauth_session_id()
TO medawarcre_app;
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


-- Migrations 0010 (platform authority), 0011 (access audit log) and 0012
-- (identity projection), copied verbatim from those files rather than
-- retyped.
--
-- This file REVOKEs everything in the schema and then re-grants an enumerated
-- set, so an object it does not name comes back from a restore with no
-- privileges at all -- and the restored catalog fingerprint stops matching the
-- manifest, which is how the omission was found rather than discovered in a
-- recovery. Any future migration that grants must add its grants here too.

REVOKE ALL ON FUNCTION medawarcre.platform_admin_audit_append_only()
    FROM PUBLIC;

REVOKE ALL ON FUNCTION medawarcre.platform_grant_scope_binding() FROM PUBLIC;

REVOKE ALL ON FUNCTION medawarcre.platform_subject_grants_membership_delete()
    FROM PUBLIC;

REVOKE ALL ON FUNCTION medawarcre.platform_provider_mapping_subject_binding()
    FROM PUBLIC;

REVOKE ALL ON FUNCTION medawarcre.platform_provider_event_binding_insert()
    FROM PUBLIC;

REVOKE ALL ON FUNCTION medawarcre.platform_provider_event_binding_update()
    FROM PUBLIC;

REVOKE ALL ON FUNCTION medawarcre.platform_provider_event_binding_immutable()
    FROM PUBLIC;

REVOKE ALL ON FUNCTION
    medawarcre.platform_provider_event_entitlement_binding() FROM PUBLIC;

REVOKE ALL ON FUNCTION
    medawarcre.platform_provider_event_entitlement_binding_immutable()
    FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    medawarcre.platform_schema_versions,
    medawarcre.platform_users,
    medawarcre.platform_plans,
    medawarcre.platform_workspaces,
    medawarcre.platform_memberships,
    medawarcre.platform_territories,
    medawarcre.platform_connected_clients,
    medawarcre.platform_saved_deals,
    medawarcre.platform_notes,
    medawarcre.platform_outcomes,
    medawarcre.platform_consents,
    medawarcre.platform_integration_events,
    medawarcre.platform_privacy_requests,
    medawarcre.platform_human_identities,
    medawarcre.platform_browser_sessions,
    medawarcre.platform_operator_sessions,
    medawarcre.platform_oauth_clients,
    medawarcre.platform_oauth_sessions,
    medawarcre.platform_oauth_codes,
    medawarcre.platform_oauth_refresh_history,
    medawarcre.platform_oauth_authorization_requests,
    medawarcre.platform_internal_admins,
    medawarcre.platform_external_accounts,
    medawarcre.platform_skool_join_tasks,
    medawarcre.platform_skool_reconciliations,
    medawarcre.platform_accounts,
    medawarcre.platform_subscriptions,
    medawarcre.platform_access_grants,
    medawarcre.platform_provider_events,
    medawarcre.platform_provider_event_attempts
TO medawarcre_app;

GRANT SELECT, INSERT ON medawarcre.platform_admin_audit TO medawarcre_app;

GRANT SELECT ON
    medawarcre.platform_schema_versions,
    medawarcre.platform_users,
    medawarcre.platform_plans,
    medawarcre.platform_workspaces,
    medawarcre.platform_memberships,
    medawarcre.platform_territories,
    medawarcre.platform_connected_clients,
    medawarcre.platform_saved_deals,
    medawarcre.platform_notes,
    medawarcre.platform_outcomes,
    medawarcre.platform_consents,
    medawarcre.platform_integration_events,
    medawarcre.platform_privacy_requests,
    medawarcre.platform_human_identities,
    medawarcre.platform_browser_sessions,
    medawarcre.platform_operator_sessions,
    medawarcre.platform_oauth_clients,
    medawarcre.platform_oauth_sessions,
    medawarcre.platform_oauth_codes,
    medawarcre.platform_oauth_refresh_history,
    medawarcre.platform_oauth_authorization_requests,
    medawarcre.platform_internal_admins,
    medawarcre.platform_external_accounts,
    medawarcre.platform_admin_audit,
    medawarcre.platform_skool_join_tasks,
    medawarcre.platform_skool_reconciliations,
    medawarcre.platform_accounts,
    medawarcre.platform_subscriptions,
    medawarcre.platform_access_grants,
    medawarcre.platform_provider_events,
    medawarcre.platform_provider_event_attempts
TO medawarcre_admin, medawarcre_backup;

REVOKE ALL ON FUNCTION medawarcre.access_audit_log_append_only() FROM PUBLIC;

REVOKE ALL ON medawarcre.access_audit_log FROM PUBLIC;

GRANT SELECT, INSERT ON medawarcre.access_audit_log TO medawarcre_app;

GRANT SELECT ON medawarcre.access_audit_log TO medawarcre_admin, medawarcre_backup;

REVOKE ALL ON FUNCTION medawarcre.project_platform_identity(
    uuid, text, uuid, bigint
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION medawarcre.project_platform_identity(
    uuid, text, uuid, bigint
) TO medawarcre_admission, medawarcre_admin;

REVOKE ALL ON FUNCTION medawarcre.project_platform_authority(
    uuid, text, uuid, bigint, uuid, text, text, text
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION medawarcre.project_platform_authority(
    uuid, text, uuid, bigint, uuid, text, text, text
) TO medawarcre_admission, medawarcre_admin;

REVOKE INSERT, UPDATE, DELETE ON medawarcre.platform_internal_admins
    FROM medawarcre_app;

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
