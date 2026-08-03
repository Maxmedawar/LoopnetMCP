CREATE SCHEMA IF NOT EXISTS medawarcre AUTHORIZATION medawarcre_migration;

REVOKE ALL ON SCHEMA medawarcre FROM PUBLIC;
GRANT USAGE ON SCHEMA medawarcre
TO medawarcre_app, medawarcre_admin, medawarcre_backup, medawarcre_admission;

CREATE FUNCTION medawarcre.current_workspace_id()
RETURNS uuid
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $function$
BEGIN
    RETURN NULLIF(current_setting('app.workspace_id', true), '')::uuid;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
END
$function$;

CREATE FUNCTION medawarcre.current_actor_user_id()
RETURNS uuid
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $function$
BEGIN
    RETURN NULLIF(current_setting('app.actor_user_id', true), '')::uuid;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
END
$function$;

CREATE FUNCTION medawarcre.internal_authorized()
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
BEGIN
    RETURN COALESCE(current_setting('app.internal_role', true), '')
                   IN ('owner', 'admin', 'jv_operations', 'support',
                       'security_audit', 'read_only_analyst')
       AND length(btrim(COALESCE(current_setting('app.audit_reason', true), ''))) > 0
       AND EXISTS (
           SELECT 1
           FROM medawarcre.staff_roles staff_role
           WHERE staff_role.user_id = medawarcre.current_actor_user_id()
             AND staff_role.role = current_setting('app.internal_role', true)
             AND staff_role.active
       );
END
$function$;

CREATE FUNCTION medawarcre.internal_can_mutate()
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $function$
    SELECT medawarcre.internal_authorized()
       AND COALESCE(current_setting('app.internal_role', true), '')
               IN ('owner', 'admin')
$function$;

REVOKE ALL ON FUNCTION medawarcre.current_workspace_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION medawarcre.current_actor_user_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION medawarcre.internal_authorized() FROM PUBLIC;
REVOKE ALL ON FUNCTION medawarcre.internal_can_mutate() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION medawarcre.current_workspace_id() TO medawarcre_app, medawarcre_admin;
GRANT EXECUTE ON FUNCTION medawarcre.current_actor_user_id() TO medawarcre_app, medawarcre_admin;
GRANT EXECUTE ON FUNCTION medawarcre.internal_authorized() TO medawarcre_admin;
GRANT EXECUTE ON FUNCTION medawarcre.internal_can_mutate() TO medawarcre_admin;

CREATE TABLE medawarcre.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL,
    name text NOT NULL,
    state text NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'disabled', 'deletion_pending', 'deleted')),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (length(btrim(email)) > 3),
    CHECK (length(btrim(name)) > 0)
);
CREATE UNIQUE INDEX users_email_casefold_key ON medawarcre.users (lower(email));

CREATE TABLE medawarcre.human_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES medawarcre.users(id) ON DELETE CASCADE,
    provider text NOT NULL,
    subject_hash bytea NOT NULL,
    subject_hint text,
    verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (provider, subject_hash),
    CHECK (length(btrim(provider)) > 0),
    CHECK (octet_length(subject_hash) = 32)
);

CREATE TABLE medawarcre.plans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_key text NOT NULL UNIQUE,
    name text NOT NULL,
    monthly_price_usd numeric(19, 2),
    seat_limit integer,
    daily_quotas jsonb NOT NULL DEFAULT '{}'::jsonb,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (monthly_price_usd IS NULL OR monthly_price_usd >= 0),
    CHECK (seat_limit IS NULL OR seat_limit > 0),
    CHECK (jsonb_typeof(daily_quotas) = 'object')
);

CREATE TABLE medawarcre.workspaces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    public_id text NOT NULL UNIQUE,
    name text NOT NULL,
    slug text UNIQUE,
    plan_id uuid REFERENCES medawarcre.plans(id),
    state text NOT NULL DEFAULT 'registered'
        CHECK (state IN ('registered', 'active', 'past_due', 'suspended',
                         'deletion_pending', 'deleted')),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (length(btrim(public_id)) > 0),
    CHECK (length(btrim(name)) > 0)
);

CREATE TABLE medawarcre.memberships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES medawarcre.users(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer', 'jv_partner')),
    state text NOT NULL DEFAULT 'active'
        CHECK (state IN ('invited', 'active', 'suspended', 'removed')),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, user_id),
    UNIQUE (workspace_id, id)
);
CREATE INDEX memberships_workspace_state_idx
    ON medawarcre.memberships (workspace_id, state, user_id);

CREATE TABLE medawarcre.staff_roles (
    user_id uuid PRIMARY KEY REFERENCES medawarcre.users(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('owner', 'admin', 'jv_operations',
                                      'support', 'security_audit',
                                      'read_only_analyst')),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp()
);

CREATE TABLE medawarcre.territories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    name text NOT NULL,
    state_code text,
    market text,
    asset_type text,
    geometry jsonb,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, name),
    UNIQUE (workspace_id, id),
    CHECK (state_code IS NULL OR state_code ~ '^[A-Z]{2}$')
);

CREATE TABLE medawarcre.workspace_accounts (
    workspace_id uuid PRIMARY KEY REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    state text NOT NULL DEFAULT 'invited'
        CHECK (state IN ('invited', 'registered', 'verified', 'active', 'past_due',
                         'grace_period', 'suspended', 'under_review', 'canceled',
                         'deletion_pending', 'deleted')),
    reason_code text,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp()
);

CREATE TABLE medawarcre.connected_clients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    name text NOT NULL,
    client_type text NOT NULL,
    scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, name),
    UNIQUE (workspace_id, id),
    CHECK (length(btrim(name)) > 0),
    CHECK (length(btrim(client_type)) > 0)
);
CREATE INDEX connected_clients_workspace_status_idx
    ON medawarcre.connected_clients (workspace_id, status, created_at);

CREATE TABLE medawarcre.integration_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    client_id uuid,
    event_type text NOT NULL,
    event_projection jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, client_id)
        REFERENCES medawarcre.connected_clients(workspace_id, id)
        ON DELETE SET NULL (client_id),
    CHECK (length(btrim(event_type)) > 0),
    CHECK (jsonb_typeof(event_projection) = 'object')
);
CREATE INDEX integration_events_workspace_time_idx
    ON medawarcre.integration_events (workspace_id, occurred_at DESC, id);

CREATE TABLE medawarcre.subscriptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    provider text NOT NULL,
    external_subscription_hash bytea NOT NULL,
    external_customer_hash bytea,
    status text NOT NULL CHECK (status IN ('trialing', 'active', 'past_due',
                                           'grace_period', 'paused', 'canceled',
                                           'unpaid', 'incomplete')),
    plan_key text NOT NULL,
    current_period_end timestamptz,
    last_event_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (provider, external_subscription_hash),
    UNIQUE (workspace_id, id),
    CHECK (octet_length(external_subscription_hash) = 32),
    CHECK (external_customer_hash IS NULL OR octet_length(external_customer_hash) = 32)
);
CREATE INDEX subscriptions_workspace_status_idx
    ON medawarcre.subscriptions (workspace_id, provider, status);

CREATE TABLE medawarcre.access_grants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    subject_user_id uuid,
    scope text NOT NULL CHECK (scope IN ('workspace', 'subject')),
    source text NOT NULL,
    external_ref_hash bytea NOT NULL,
    profile text NOT NULL CHECK (profile IN ('local_scout', 'national_scout',
                                             'full_operator', 'jv_partner')),
    plan_key text,
    status text NOT NULL CHECK (status IN ('pending', 'active', 'overridden',
                                           'expiring', 'expired', 'revoked')),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (source, external_ref_hash),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, subject_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id),
    CHECK ((scope = 'workspace' AND subject_user_id IS NULL)
        OR (scope = 'subject' AND subject_user_id IS NOT NULL)),
    CHECK (octet_length(external_ref_hash) = 32),
    CHECK (ends_at IS NULL OR ends_at > starts_at)
);
CREATE INDEX access_grants_workspace_subject_idx
    ON medawarcre.access_grants (workspace_id, subject_user_id, status, ends_at);

CREATE TABLE medawarcre.oauth_clients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id text NOT NULL UNIQUE,
    name text NOT NULL,
    redirect_uris text[] NOT NULL,
    scopes text[] NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (cardinality(redirect_uris) > 0),
    CHECK (cardinality(scopes) > 0)
);

CREATE TABLE medawarcre.oauth_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    user_id uuid NOT NULL,
    client_id text NOT NULL REFERENCES medawarcre.oauth_clients(client_id) ON DELETE CASCADE,
    scopes text[] NOT NULL,
    audience text NOT NULL,
    resource text NOT NULL,
    authority_version integer NOT NULL CHECK (authority_version > 0),
    access_hash bytea NOT NULL UNIQUE,
    refresh_hash bytea NOT NULL UNIQUE,
    access_expires_at timestamptz NOT NULL,
    refresh_expires_at timestamptz NOT NULL,
    refresh_family_expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id) ON DELETE CASCADE,
    CHECK (octet_length(access_hash) = 32),
    CHECK (octet_length(refresh_hash) = 32),
    CHECK (access_expires_at <= refresh_expires_at),
    CHECK (refresh_expires_at <= refresh_family_expires_at)
);
CREATE INDEX oauth_sessions_authority_idx
    ON medawarcre.oauth_sessions (workspace_id, user_id, revoked_at, refresh_expires_at);

CREATE TABLE medawarcre.oauth_codes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    user_id uuid NOT NULL,
    client_id text NOT NULL REFERENCES medawarcre.oauth_clients(client_id) ON DELETE CASCADE,
    session_id uuid,
    code_hash bytea NOT NULL UNIQUE,
    redirect_uri text NOT NULL,
    code_challenge text NOT NULL,
    code_challenge_method text NOT NULL DEFAULT 'S256' CHECK (code_challenge_method = 'S256'),
    scopes text[] NOT NULL,
    audience text NOT NULL,
    resource text NOT NULL,
    authority_version integer NOT NULL CHECK (authority_version > 0),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, session_id)
        REFERENCES medawarcre.oauth_sessions(workspace_id, id)
        ON DELETE SET NULL (session_id),
    CHECK (octet_length(code_hash) = 32)
);

CREATE TABLE medawarcre.oauth_refresh_history (
    workspace_id uuid NOT NULL,
    session_id uuid NOT NULL,
    token_hash bytea NOT NULL,
    rotated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (workspace_id, token_hash),
    FOREIGN KEY (workspace_id, session_id)
        REFERENCES medawarcre.oauth_sessions(workspace_id, id) ON DELETE CASCADE,
    CHECK (octet_length(token_hash) = 32)
);

CREATE TABLE medawarcre.external_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    subject_user_id uuid NOT NULL,
    provider text NOT NULL,
    external_account_hash bytea NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (provider, external_account_hash),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, subject_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id) ON DELETE CASCADE,
    CHECK (octet_length(external_account_hash) = 32),
    CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE TABLE medawarcre.provider_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    external_account_id uuid,
    provider text NOT NULL,
    event_id_hash bytea NOT NULL,
    canonical_action text NOT NULL,
    outcome text NOT NULL DEFAULT 'received'
        CHECK (outcome IN ('received', 'applied', 'duplicate', 'stale',
                           'quarantined', 'rejected', 'unmapped', 'malformed',
                           'failure', 'reconciled')),
    reason_code text,
    object_stream_hash bytea,
    restrictive_rank smallint NOT NULL DEFAULT 0 CHECK (restrictive_rank >= 0),
    external_account_hash bytea,
    bound_subject_user_id uuid,
    bound_scope text CHECK (bound_scope IN ('subject', 'workspace')),
    entitlement_input_hash bytea,
    bound_plan_key text,
    bound_profile text CHECK (bound_profile IN ('local_scout', 'national_scout',
                                                 'full_operator', 'jv_partner')),
    mapping_provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    payload_fingerprint bytea NOT NULL,
    event_projection jsonb NOT NULL DEFAULT '{}'::jsonb,
    duplicate_count integer NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
    replayed_at timestamptz,
    occurred_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (provider, event_id_hash),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, external_account_id)
        REFERENCES medawarcre.external_accounts(workspace_id, id),
    CHECK (octet_length(event_id_hash) = 32),
    CHECK (object_stream_hash IS NULL OR octet_length(object_stream_hash) = 32),
    CHECK (external_account_hash IS NULL OR octet_length(external_account_hash) = 32),
    CHECK (entitlement_input_hash IS NULL OR octet_length(entitlement_input_hash) = 32),
    CHECK (octet_length(payload_fingerprint) = 32),
    CHECK (jsonb_typeof(event_projection) = 'object'),
    CHECK (jsonb_typeof(mapping_provenance) = 'object'),
    CHECK ((bound_subject_user_id IS NULL) = (bound_scope IS NULL)),
    CHECK ((bound_plan_key IS NULL) = (bound_profile IS NULL)),
    CHECK (workspace_id IS NOT NULL OR
           (external_account_id IS NULL AND bound_subject_user_id IS NULL)),
    CONSTRAINT provider_events_workspace_lifecycle_check CHECK (
        workspace_id IS NOT NULL OR (
            outcome IN ('unmapped', 'malformed')
            AND external_account_id IS NULL
            AND bound_subject_user_id IS NULL
            AND bound_scope IS NULL
            AND entitlement_input_hash IS NULL
            AND bound_plan_key IS NULL
            AND bound_profile IS NULL
        )
    ),
    FOREIGN KEY (workspace_id, bound_subject_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
);
CREATE INDEX provider_events_stream_idx
    ON medawarcre.provider_events (workspace_id, provider, object_stream_hash, occurred_at DESC);

CREATE TABLE medawarcre.provider_event_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid,
    provider_event_id uuid NOT NULL,
    outcome text NOT NULL
        CHECK (outcome IN ('received', 'applied', 'duplicate', 'stale',
                           'quarantined', 'rejected', 'unmapped', 'malformed',
                           'failure', 'reconciled')),
    reason_code text,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CONSTRAINT provider_event_attempts_workspace_lifecycle_check CHECK (
        workspace_id IS NOT NULL OR outcome IN ('unmapped', 'malformed')
    ),
    FOREIGN KEY (provider_event_id)
        REFERENCES medawarcre.provider_events(id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, provider_event_id)
        REFERENCES medawarcre.provider_events(workspace_id, id) ON DELETE CASCADE
);

CREATE TABLE medawarcre.saved_searches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    owner_user_id uuid NOT NULL,
    name text NOT NULL,
    query jsonb NOT NULL,
    min_score numeric(10, 4),
    schedule text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, name),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, owner_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id),
    CHECK (jsonb_typeof(query) = 'object')
);

CREATE TABLE medawarcre.search_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    saved_search_id uuid NOT NULL,
    requested_by_user_id uuid,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')),
    result_count integer NOT NULL DEFAULT 0 CHECK (result_count >= 0),
    failure_code text,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, saved_search_id)
        REFERENCES medawarcre.saved_searches(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, requested_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id),
    CHECK (completed_at IS NULL OR started_at IS NOT NULL),
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE medawarcre.search_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    search_run_id uuid NOT NULL,
    source text NOT NULL,
    source_record_id text NOT NULL,
    dedupe_key text NOT NULL,
    listing jsonb NOT NULL,
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, search_run_id, dedupe_key),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, search_run_id)
        REFERENCES medawarcre.search_runs(workspace_id, id) ON DELETE CASCADE,
    CHECK (jsonb_typeof(listing) = 'object')
);

CREATE TABLE medawarcre.deals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    source text NOT NULL,
    source_record_id text NOT NULL,
    title text NOT NULL,
    listing jsonb NOT NULL DEFAULT '{}'::jsonb,
    asking_price numeric(19, 2),
    stage text NOT NULL DEFAULT 'lead'
        CHECK (stage IN ('lead', 'analyzing', 'contacted', 'loi', 'under_contract',
                         'diligence', 'closing', 'owned', 'passed')),
    score numeric(10, 4),
    score_version text,
    grade text,
    strategy text,
    owner_user_id uuid,
    next_action text,
    next_action_due timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, source, source_record_id),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, owner_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id),
    CHECK (jsonb_typeof(listing) = 'object'),
    CHECK (asking_price IS NULL OR asking_price > 0)
);
CREATE INDEX deals_workspace_stage_idx
    ON medawarcre.deals (workspace_id, stage, updated_at DESC);

CREATE TABLE medawarcre.deal_notes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    deal_id uuid NOT NULL,
    author_user_id uuid NOT NULL,
    body text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    FOREIGN KEY (workspace_id, deal_id)
        REFERENCES medawarcre.deals(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, author_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id),
    CHECK (length(btrim(body)) > 0)
);

CREATE TABLE medawarcre.deal_outcomes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    deal_id uuid NOT NULL,
    closed boolean NOT NULL,
    purchase_price numeric(19, 2),
    realized_hold_years numeric(8, 3),
    realized_irr numeric(10, 6),
    realized_equity_multiple numeric(12, 6),
    went_bad boolean,
    notes text,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, deal_id),
    FOREIGN KEY (workspace_id, deal_id)
        REFERENCES medawarcre.deals(workspace_id, id) ON DELETE CASCADE,
    CHECK (purchase_price IS NULL OR purchase_price > 0),
    CHECK (realized_hold_years IS NULL OR realized_hold_years > 0),
    CHECK (realized_equity_multiple IS NULL OR realized_equity_multiple >= 0)
);

CREATE TABLE medawarcre.deal_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    deal_id uuid NOT NULL,
    event_type text NOT NULL,
    event_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    FOREIGN KEY (workspace_id, deal_id)
        REFERENCES medawarcre.deals(workspace_id, id) ON DELETE CASCADE,
    CHECK (jsonb_typeof(event_data) = 'object')
);

CREATE TABLE medawarcre.internal_opportunities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_key text NOT NULL UNIQUE,
    title text NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'suppressed', 'archived')),
    normalized_facts jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (jsonb_typeof(normalized_facts) = 'object')
);

CREATE TABLE medawarcre.legacy_id_aliases (
    source_system text NOT NULL,
    entity_type text NOT NULL,
    legacy_id bigint NOT NULL,
    canonical_id uuid NOT NULL,
    workspace_id uuid REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (source_system, entity_type, legacy_id),
    UNIQUE (source_system, entity_type, canonical_id),
    CHECK (length(btrim(source_system)) > 0),
    CHECK (length(btrim(entity_type)) > 0),
    CHECK (legacy_id > 0)
);

CREATE TABLE medawarcre.internal_opportunity_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    opportunity_id uuid NOT NULL REFERENCES medawarcre.internal_opportunities(id) ON DELETE CASCADE,
    source text NOT NULL,
    source_record_id text NOT NULL,
    access_class text NOT NULL CHECK (access_class IN ('private', 'licensed', 'public')),
    score_version text NOT NULL,
    provenance jsonb NOT NULL,
    first_observed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    last_observed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, source, source_record_id),
    UNIQUE (workspace_id, id),
    CHECK (jsonb_typeof(provenance) = 'object'),
    CHECK (last_observed_at >= first_observed_at)
);
CREATE INDEX internal_opportunity_sources_opportunity_idx
    ON medawarcre.internal_opportunity_sources (opportunity_id, workspace_id);

CREATE TABLE medawarcre.consents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    user_id uuid NOT NULL,
    consent_type text NOT NULL CHECK (consent_type IN ('terms', 'privacy', 'marketing', 'data_processing')),
    granted boolean NOT NULL,
    version text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    FOREIGN KEY (workspace_id, user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id) ON DELETE CASCADE
);
CREATE INDEX consents_workspace_user_idx
    ON medawarcre.consents (workspace_id, user_id, consent_type, occurred_at DESC);

CREATE TABLE medawarcre.privacy_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    user_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('access', 'export', 'delete', 'correct')),
    status text NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'verified', 'in_progress', 'completed', 'rejected', 'canceled')),
    detail text,
    due_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id) ON DELETE CASCADE,
    CHECK (completed_at IS NULL OR status IN ('completed', 'rejected', 'canceled'))
);

CREATE TABLE medawarcre.retention_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    privacy_request_id uuid,
    subject_user_id uuid,
    action text NOT NULL CHECK (action IN ('exported', 'corrected', 'deleted', 'anonymized', 'retained')),
    object_type text NOT NULL,
    object_id text NOT NULL,
    reason_code text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    executed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    FOREIGN KEY (workspace_id, privacy_request_id)
        REFERENCES medawarcre.privacy_requests(workspace_id, id),
    FOREIGN KEY (workspace_id, subject_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id),
    CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE TABLE medawarcre.staff_audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id uuid NOT NULL REFERENCES medawarcre.users(id),
    actor_role text NOT NULL CHECK (actor_role IN ('owner', 'admin',
                                                   'jv_operations', 'support',
                                                   'security_audit',
                                                   'read_only_analyst')),
    reason text NOT NULL,
    reason_code text NOT NULL,
    workspace_id uuid REFERENCES medawarcre.workspaces(id),
    object_type text NOT NULL,
    object_id text NOT NULL,
    action text NOT NULL,
    result text NOT NULL CHECK (result IN ('allowed', 'denied', 'succeeded', 'failed')),
    before_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    after_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (length(btrim(reason)) > 0),
    CHECK (jsonb_typeof(before_data) = 'object'),
    CHECK (jsonb_typeof(after_data) = 'object')
);
CREATE INDEX staff_audit_workspace_time_idx
    ON medawarcre.staff_audit_log (workspace_id, occurred_at DESC, id);

CREATE TABLE medawarcre.access_decision_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invocation_id uuid NOT NULL,
    phase text NOT NULL CHECK (phase IN ('admission', 'final')),
    authenticated boolean NOT NULL,
    workspace_id uuid REFERENCES medawarcre.workspaces(id),
    actor_user_id uuid REFERENCES medawarcre.users(id),
    session_correlation_hash bytea,
    request_correlation_id uuid,
    tool_name text NOT NULL,
    decision text NOT NULL
        CHECK (decision IN ('allowed', 'denied', 'succeeded', 'failed')),
    reason_code text NOT NULL,
    safe_reason text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (invocation_id, phase),
    CHECK ((authenticated AND workspace_id IS NOT NULL AND actor_user_id IS NOT NULL)
        OR (NOT authenticated AND workspace_id IS NULL AND actor_user_id IS NULL)),
    CHECK (NOT authenticated OR session_correlation_hash IS NOT NULL),
    CHECK ((phase = 'admission' AND decision IN ('allowed', 'denied'))
        OR (phase = 'final' AND decision IN ('succeeded', 'failed'))),
    CHECK (session_correlation_hash IS NULL
        OR octet_length(session_correlation_hash) = 32),
    CHECK (length(btrim(tool_name)) > 0),
    CHECK (length(btrim(reason_code)) > 0),
    CHECK (length(btrim(safe_reason)) > 0)
);
CREATE INDEX access_decision_workspace_time_idx
    ON medawarcre.access_decision_audit (workspace_id, occurred_at DESC, id);
CREATE INDEX access_decision_request_idx
    ON medawarcre.access_decision_audit (request_correlation_id)
    WHERE request_correlation_id IS NOT NULL;

CREATE TABLE medawarcre.tool_approvals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_token_hash bytea NOT NULL UNIQUE,
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    subject_user_id uuid NOT NULL,
    session_hash bytea NOT NULL,
    tool_name text NOT NULL,
    args_hash bytea NOT NULL,
    request_correlation_id uuid,
    issued_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    revoked_at timestamptz,
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, subject_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id) ON DELETE CASCADE,
    CHECK (octet_length(approval_token_hash) = 32),
    CHECK (octet_length(session_hash) = 32),
    CHECK (octet_length(args_hash) = 32),
    CHECK (length(btrim(tool_name)) > 0),
    CHECK (expires_at > issued_at),
    CHECK (consumed_at IS NULL OR consumed_at >= issued_at),
    CHECK (revoked_at IS NULL OR revoked_at >= issued_at),
    CHECK (consumed_at IS NULL OR revoked_at IS NULL)
);
CREATE INDEX tool_approvals_subject_expiry_idx
    ON medawarcre.tool_approvals
       (workspace_id, subject_user_id, expires_at, consumed_at, revoked_at);

CREATE TABLE medawarcre.daily_quota_usage (
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    bucket text NOT NULL,
    usage_date date NOT NULL,
    used_count bigint NOT NULL DEFAULT 0 CHECK (used_count >= 0),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (workspace_id, bucket, usage_date),
    CHECK (length(btrim(bucket)) > 0)
);

CREATE FUNCTION medawarcre.reject_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $function$
BEGIN
    RAISE EXCEPTION 'audit and alias records are append-only' USING ERRCODE = '55000';
END
$function$;
REVOKE ALL ON FUNCTION medawarcre.reject_audit_mutation() FROM PUBLIC;

CREATE TRIGGER staff_audit_log_no_update
BEFORE UPDATE ON medawarcre.staff_audit_log
FOR EACH ROW EXECUTE FUNCTION medawarcre.reject_audit_mutation();
CREATE TRIGGER staff_audit_log_no_delete
BEFORE DELETE ON medawarcre.staff_audit_log
FOR EACH ROW EXECUTE FUNCTION medawarcre.reject_audit_mutation();
CREATE TRIGGER access_decision_audit_no_update
BEFORE UPDATE ON medawarcre.access_decision_audit
FOR EACH ROW EXECUTE FUNCTION medawarcre.reject_audit_mutation();
CREATE TRIGGER access_decision_audit_no_delete
BEFORE DELETE ON medawarcre.access_decision_audit
FOR EACH ROW EXECUTE FUNCTION medawarcre.reject_audit_mutation();
CREATE TRIGGER legacy_id_aliases_no_update
BEFORE UPDATE ON medawarcre.legacy_id_aliases
FOR EACH ROW EXECUTE FUNCTION medawarcre.reject_audit_mutation();
CREATE TRIGGER legacy_id_aliases_no_delete
BEFORE DELETE ON medawarcre.legacy_id_aliases
FOR EACH ROW EXECUTE FUNCTION medawarcre.reject_audit_mutation();

CREATE FUNCTION medawarcre.reject_provider_event_binding_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $function$
BEGIN
    IF NEW.provider IS DISTINCT FROM OLD.provider
       OR NEW.event_id_hash IS DISTINCT FROM OLD.event_id_hash
       OR NEW.canonical_action IS DISTINCT FROM OLD.canonical_action
       OR NEW.payload_fingerprint IS DISTINCT FROM OLD.payload_fingerprint
       OR NEW.event_projection IS DISTINCT FROM OLD.event_projection
       OR NEW.mapping_provenance IS DISTINCT FROM OLD.mapping_provenance
       OR NEW.occurred_at IS DISTINCT FROM OLD.occurred_at
       OR NEW.restrictive_rank IS DISTINCT FROM OLD.restrictive_rank
       OR (OLD.workspace_id IS NOT NULL
           AND NEW.workspace_id IS DISTINCT FROM OLD.workspace_id)
       OR (OLD.external_account_id IS NOT NULL
           AND NEW.external_account_id IS DISTINCT FROM OLD.external_account_id)
       OR (OLD.object_stream_hash IS NOT NULL
           AND NEW.object_stream_hash IS DISTINCT FROM OLD.object_stream_hash)
       OR (OLD.external_account_hash IS NOT NULL
           AND NEW.external_account_hash IS DISTINCT FROM OLD.external_account_hash)
       OR (OLD.bound_subject_user_id IS NOT NULL
           AND NEW.bound_subject_user_id IS DISTINCT FROM OLD.bound_subject_user_id)
       OR (OLD.bound_scope IS NOT NULL
           AND NEW.bound_scope IS DISTINCT FROM OLD.bound_scope)
       OR (OLD.entitlement_input_hash IS NOT NULL
           AND NEW.entitlement_input_hash IS DISTINCT FROM OLD.entitlement_input_hash)
       OR (OLD.bound_plan_key IS NOT NULL
           AND NEW.bound_plan_key IS DISTINCT FROM OLD.bound_plan_key)
       OR (OLD.bound_profile IS NOT NULL
           AND NEW.bound_profile IS DISTINCT FROM OLD.bound_profile)
    THEN
        RAISE EXCEPTION 'provider receipt replay binding is immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION medawarcre.reject_provider_event_binding_mutation()
FROM PUBLIC;

CREATE TRIGGER provider_events_binding_immutable
BEFORE UPDATE ON medawarcre.provider_events
FOR EACH ROW EXECUTE FUNCTION medawarcre.reject_provider_event_binding_mutation();

CREATE FUNCTION medawarcre.enforce_provider_event_attempt_binding()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $function$
DECLARE
    event_workspace_id uuid;
BEGIN
    SELECT provider_event.workspace_id
      INTO event_workspace_id
      FROM medawarcre.provider_events provider_event
     WHERE provider_event.id = NEW.provider_event_id
     FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'provider event attempt references a missing event'
            USING ERRCODE = '23503';
    END IF;
    IF NEW.workspace_id IS DISTINCT FROM event_workspace_id THEN
        RAISE EXCEPTION 'provider event attempt workspace binding differs from its event'
            USING ERRCODE = '23503';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION medawarcre.enforce_provider_event_attempt_binding()
FROM PUBLIC;

CREATE TRIGGER provider_event_attempts_binding_exact
BEFORE INSERT OR UPDATE ON medawarcre.provider_event_attempts
FOR EACH ROW EXECUTE FUNCTION medawarcre.enforce_provider_event_attempt_binding();

CREATE FUNCTION medawarcre.propagate_provider_event_workspace_binding()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
BEGIN
    IF OLD.workspace_id IS NULL AND NEW.workspace_id IS NOT NULL THEN
        UPDATE medawarcre.provider_event_attempts
           SET workspace_id = NEW.workspace_id
         WHERE provider_event_id = NEW.id
           AND workspace_id IS NULL;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION medawarcre.propagate_provider_event_workspace_binding()
FROM PUBLIC;

CREATE TRIGGER provider_events_workspace_binding_propagated
AFTER UPDATE OF workspace_id ON medawarcre.provider_events
FOR EACH ROW EXECUTE FUNCTION medawarcre.propagate_provider_event_workspace_binding();

CREATE FUNCTION medawarcre.consume_tool_approval(
    p_approval_token_hash bytea,
    p_workspace_id uuid,
    p_subject_user_id uuid,
    p_session_hash bytea,
    p_tool_name text,
    p_args_hash bytea
)
RETURNS uuid
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    UPDATE medawarcre.tool_approvals
       SET consumed_at = statement_timestamp()
     WHERE approval_token_hash = p_approval_token_hash
       AND workspace_id = p_workspace_id
       AND subject_user_id = p_subject_user_id
       AND session_hash = p_session_hash
       AND tool_name = p_tool_name
       AND args_hash = p_args_hash
       AND consumed_at IS NULL
       AND revoked_at IS NULL
       AND expires_at > statement_timestamp()
       AND octet_length(p_approval_token_hash) = 32
       AND octet_length(p_session_hash) = 32
       AND octet_length(p_args_hash) = 32
    RETURNING id
$function$;
REVOKE ALL ON FUNCTION medawarcre.consume_tool_approval(
    bytea, uuid, uuid, bytea, text, bytea
) FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup;

CREATE FUNCTION medawarcre.consume_daily_quota(
    p_workspace_id uuid,
    p_bucket text,
    p_amount bigint,
    p_limit bigint
)
RETURNS bigint
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    INSERT INTO medawarcre.daily_quota_usage(
        workspace_id, bucket, usage_date, used_count, updated_at
    )
    SELECT p_workspace_id, p_bucket,
           (statement_timestamp() AT TIME ZONE 'UTC')::date,
           p_amount, statement_timestamp()
     WHERE p_amount > 0 AND p_limit >= p_amount AND length(btrim(p_bucket)) > 0
    ON CONFLICT (workspace_id, bucket, usage_date)
    DO UPDATE
       SET used_count = medawarcre.daily_quota_usage.used_count + EXCLUDED.used_count,
           updated_at = statement_timestamp()
     WHERE medawarcre.daily_quota_usage.used_count + EXCLUDED.used_count <= p_limit
    RETURNING used_count
$function$;
REVOKE ALL ON FUNCTION medawarcre.consume_daily_quota(
    uuid, text, bigint, bigint
) FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup;

CREATE FUNCTION medawarcre.record_access_decision(
    p_invocation_id uuid,
    p_phase text,
    p_authenticated boolean,
    p_workspace_id uuid,
    p_actor_user_id uuid,
    p_session_correlation_hash bytea,
    p_request_correlation_id uuid,
    p_tool_name text,
    p_decision text,
    p_reason_code text,
    p_safe_reason text
)
RETURNS uuid
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    INSERT INTO medawarcre.access_decision_audit(
        invocation_id, phase, authenticated, workspace_id, actor_user_id,
        session_correlation_hash, request_correlation_id, tool_name, decision,
        reason_code, safe_reason, occurred_at
    )
    SELECT p_invocation_id, p_phase, p_authenticated, p_workspace_id,
           p_actor_user_id, p_session_correlation_hash,
           p_request_correlation_id, p_tool_name, p_decision,
           p_reason_code, p_safe_reason, statement_timestamp()
     WHERE p_phase = 'admission'
        OR (p_phase = 'final' AND EXISTS (
            SELECT 1
            FROM medawarcre.access_decision_audit admission
            WHERE admission.invocation_id = p_invocation_id
              AND admission.phase = 'admission'
              AND admission.decision = 'allowed'
              AND admission.authenticated = p_authenticated
              AND admission.workspace_id IS NOT DISTINCT FROM p_workspace_id
              AND admission.actor_user_id IS NOT DISTINCT FROM p_actor_user_id
              AND admission.session_correlation_hash
                    IS NOT DISTINCT FROM p_session_correlation_hash
              AND admission.request_correlation_id
                    IS NOT DISTINCT FROM p_request_correlation_id
              AND admission.tool_name = p_tool_name
        ))
    RETURNING id
$function$;
REVOKE ALL ON FUNCTION medawarcre.record_access_decision(
    uuid, text, boolean, uuid, uuid, bytea, uuid, text, text, text, text
) FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup;

CREATE TABLE medawarcre.jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    saved_search_id uuid,
    kind text NOT NULL CHECK (kind IN ('saved_search', 'privacy', 'provider_reconcile', 'retention')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'leased', 'running', 'succeeded', 'failed', 'canceled')),
    idempotency_key text NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL CHECK (max_attempts > 0),
    next_run_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    lease_owner text,
    leased_until timestamptz,
    last_error_code text,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, idempotency_key),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, saved_search_id)
        REFERENCES medawarcre.saved_searches(workspace_id, id) ON DELETE CASCADE,
    CHECK (jsonb_typeof(payload) = 'object'),
    CHECK (length(btrim(idempotency_key)) > 0),
    CHECK ((lease_owner IS NULL) = (leased_until IS NULL))
);
CREATE INDEX jobs_claim_idx
    ON medawarcre.jobs (status, next_run_at, created_at)
    WHERE status = 'queued';

CREATE TABLE medawarcre.job_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    job_id uuid NOT NULL,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    worker_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'abandoned')),
    error_code text,
    started_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, job_id, attempt_number),
    FOREIGN KEY (workspace_id, job_id)
        REFERENCES medawarcre.jobs(workspace_id, id) ON DELETE CASCADE,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

DO $rls$
DECLARE
    relation_name text;
    tenant_relations constant text[] := ARRAY[
        'memberships', 'territories', 'workspace_accounts', 'subscriptions',
        'access_grants', 'oauth_sessions', 'oauth_codes', 'oauth_refresh_history',
        'external_accounts', 'provider_events', 'provider_event_attempts',
        'saved_searches', 'search_runs', 'search_results', 'deals', 'deal_notes',
        'deal_outcomes', 'deal_events', 'consents', 'privacy_requests',
        'retention_actions', 'jobs', 'job_attempts'
    ];
    admin_only_relations constant text[] := ARRAY[
        'connected_clients', 'integration_events',
        'internal_opportunity_sources', 'staff_audit_log',
        'access_decision_audit', 'tool_approvals', 'daily_quota_usage',
        'legacy_id_aliases'
    ];
    global_internal_relations constant text[] := ARRAY[
        'users', 'human_identities', 'staff_roles', 'internal_opportunities'
    ];
    all_internal_relations text[];
BEGIN
    ALTER TABLE medawarcre.users ENABLE ROW LEVEL SECURITY;
    CREATE POLICY app_actor_user ON medawarcre.users
        FOR SELECT TO medawarcre_app
        USING (id = medawarcre.current_actor_user_id());

    ALTER TABLE medawarcre.workspaces ENABLE ROW LEVEL SECURITY;
    CREATE POLICY tenant_workspaces ON medawarcre.workspaces
        FOR SELECT TO medawarcre_app
        USING (id = medawarcre.current_workspace_id());

    FOREACH relation_name IN ARRAY tenant_relations LOOP
        EXECUTE format('ALTER TABLE medawarcre.%I ENABLE ROW LEVEL SECURITY', relation_name);
        IF relation_name NOT IN (
            'memberships', 'access_grants', 'saved_searches', 'search_runs',
            'search_results', 'deals', 'deal_notes', 'consents',
            'privacy_requests'
        ) THEN
            EXECUTE format(
                'CREATE POLICY tenant_access ON medawarcre.%I '
                'FOR ALL TO medawarcre_app '
                'USING (workspace_id = medawarcre.current_workspace_id()) '
                'WITH CHECK (workspace_id = medawarcre.current_workspace_id())',
                relation_name
            );
        END IF;
    END LOOP;

    FOREACH relation_name IN ARRAY admin_only_relations LOOP
        EXECUTE format('ALTER TABLE medawarcre.%I ENABLE ROW LEVEL SECURITY', relation_name);
    END LOOP;
    FOREACH relation_name IN ARRAY global_internal_relations LOOP
        EXECUTE format('ALTER TABLE medawarcre.%I ENABLE ROW LEVEL SECURITY', relation_name);
    END LOOP;

    all_internal_relations := global_internal_relations
        || ARRAY['workspaces']
        || tenant_relations
        || admin_only_relations;
    FOREACH relation_name IN ARRAY all_internal_relations LOOP
        EXECUTE format(
            'CREATE POLICY internal_read ON medawarcre.%I '
            'FOR SELECT TO medawarcre_admin '
            'USING (medawarcre.internal_authorized())',
            relation_name
        );
        IF relation_name = 'staff_audit_log' THEN
            EXECUTE format(
                'CREATE POLICY internal_audit_insert ON medawarcre.%I '
                'FOR INSERT TO medawarcre_admin '
                'WITH CHECK (medawarcre.internal_authorized() '
                'AND actor_user_id = medawarcre.current_actor_user_id() '
                'AND actor_role = current_setting(''app.internal_role'', true) '
                'AND reason = current_setting(''app.audit_reason'', true))',
                relation_name
            );
        ELSIF relation_name NOT IN (
            'access_decision_audit', 'legacy_id_aliases',
            'tool_approvals', 'daily_quota_usage', 'human_identities',
            'integration_events', 'subscriptions', 'access_grants',
            'oauth_sessions', 'oauth_codes', 'oauth_refresh_history',
            'external_accounts', 'provider_events', 'provider_event_attempts'
        ) THEN
            EXECUTE format(
                'CREATE POLICY internal_insert ON medawarcre.%I '
                'FOR INSERT TO medawarcre_admin '
                'WITH CHECK (medawarcre.internal_can_mutate())',
                relation_name
            );
            EXECUTE format(
                'CREATE POLICY internal_update ON medawarcre.%I '
                'FOR UPDATE TO medawarcre_admin '
                'USING (medawarcre.internal_can_mutate()) '
                'WITH CHECK (medawarcre.internal_can_mutate())',
                relation_name
            );
            EXECUTE format(
                'CREATE POLICY internal_delete ON medawarcre.%I '
                'FOR DELETE TO medawarcre_admin '
                'USING (medawarcre.internal_can_mutate())',
                relation_name
            );
        END IF;
    END LOOP;
END
$rls$;

CREATE POLICY app_actor_membership ON medawarcre.memberships
    FOR SELECT TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND user_id = medawarcre.current_actor_user_id());

CREATE POLICY app_visible_access_grants ON medawarcre.access_grants
    FOR SELECT TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND (scope = 'workspace'
            OR subject_user_id = medawarcre.current_actor_user_id()));

CREATE POLICY app_owned_saved_searches ON medawarcre.saved_searches
    FOR ALL TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND owner_user_id = medawarcre.current_actor_user_id())
    WITH CHECK (workspace_id = medawarcre.current_workspace_id()
       AND owner_user_id = medawarcre.current_actor_user_id());

CREATE POLICY app_owned_search_runs ON medawarcre.search_runs
    FOR SELECT TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND EXISTS (
           SELECT 1
           FROM medawarcre.saved_searches saved_search
           WHERE saved_search.workspace_id = search_runs.workspace_id
             AND saved_search.id = search_runs.saved_search_id
             AND saved_search.owner_user_id = medawarcre.current_actor_user_id()
       ));

CREATE POLICY app_owned_search_results ON medawarcre.search_results
    FOR SELECT TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND EXISTS (
           SELECT 1
           FROM medawarcre.search_runs search_run
           WHERE search_run.workspace_id = search_results.workspace_id
             AND search_run.id = search_results.search_run_id
       ));

CREATE POLICY app_shared_deals_select ON medawarcre.deals
    FOR SELECT TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id());
CREATE POLICY app_owned_deals_insert ON medawarcre.deals
    FOR INSERT TO medawarcre_app
    WITH CHECK (workspace_id = medawarcre.current_workspace_id()
       AND (owner_user_id IS NULL
            OR owner_user_id = medawarcre.current_actor_user_id()));
CREATE POLICY app_owned_deals_update ON medawarcre.deals
    FOR UPDATE TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND (owner_user_id IS NULL
            OR owner_user_id = medawarcre.current_actor_user_id()))
    WITH CHECK (workspace_id = medawarcre.current_workspace_id()
       AND (owner_user_id IS NULL
            OR owner_user_id = medawarcre.current_actor_user_id()));
CREATE POLICY app_owned_deals_delete ON medawarcre.deals
    FOR DELETE TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND (owner_user_id IS NULL
            OR owner_user_id = medawarcre.current_actor_user_id()));

CREATE POLICY app_shared_deal_notes_select ON medawarcre.deal_notes
    FOR SELECT TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id());
CREATE POLICY app_owned_deal_notes_insert ON medawarcre.deal_notes
    FOR INSERT TO medawarcre_app
    WITH CHECK (workspace_id = medawarcre.current_workspace_id()
       AND author_user_id = medawarcre.current_actor_user_id());
CREATE POLICY app_owned_deal_notes_update ON medawarcre.deal_notes
    FOR UPDATE TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND author_user_id = medawarcre.current_actor_user_id())
    WITH CHECK (workspace_id = medawarcre.current_workspace_id()
       AND author_user_id = medawarcre.current_actor_user_id());
CREATE POLICY app_owned_deal_notes_delete ON medawarcre.deal_notes
    FOR DELETE TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND author_user_id = medawarcre.current_actor_user_id());

CREATE POLICY app_owned_consents ON medawarcre.consents
    FOR ALL TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND user_id = medawarcre.current_actor_user_id())
    WITH CHECK (workspace_id = medawarcre.current_workspace_id()
       AND user_id = medawarcre.current_actor_user_id());

CREATE POLICY app_owned_privacy_requests ON medawarcre.privacy_requests
    FOR ALL TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id()
       AND user_id = medawarcre.current_actor_user_id())
    WITH CHECK (workspace_id = medawarcre.current_workspace_id()
       AND user_id = medawarcre.current_actor_user_id());

REVOKE ALL ON SCHEMA medawarcre
FROM medawarcre_app, medawarcre_admin, medawarcre_backup, medawarcre_admission;
REVOKE ALL ON ALL TABLES IN SCHEMA medawarcre
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup, medawarcre_admission;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA medawarcre
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup, medawarcre_admission;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA medawarcre
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup, medawarcre_admission;
GRANT USAGE ON SCHEMA medawarcre
TO medawarcre_app, medawarcre_admin, medawarcre_backup, medawarcre_admission;

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
GRANT EXECUTE ON FUNCTION medawarcre.consume_tool_approval(
    bytea, uuid, uuid, bytea, text, bytea
) TO medawarcre_admission;
GRANT EXECUTE ON FUNCTION medawarcre.consume_daily_quota(
    uuid, text, bigint, bigint
) TO medawarcre_admission;
GRANT EXECUTE ON FUNCTION medawarcre.record_access_decision(
    uuid, text, boolean, uuid, uuid, bytea, uuid, text, text, text, text
) TO medawarcre_admission;

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
