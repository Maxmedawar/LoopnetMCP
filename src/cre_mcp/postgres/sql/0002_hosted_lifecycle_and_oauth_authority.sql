CREATE TABLE medawarcre.browser_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash bytea NOT NULL UNIQUE,
    user_id uuid NOT NULL REFERENCES medawarcre.users(id) ON DELETE CASCADE,
    csrf_hash bytea NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (octet_length(token_hash) = 32),
    CHECK (octet_length(csrf_hash) = 32),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE INDEX browser_sessions_user_idx
    ON medawarcre.browser_sessions (user_id, revoked_at, expires_at);
CREATE UNIQUE INDEX browser_sessions_one_live_per_user
    ON medawarcre.browser_sessions (user_id)
    WHERE revoked_at IS NULL;

CREATE TABLE medawarcre.operator_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash bytea NOT NULL UNIQUE,
    user_id uuid NOT NULL REFERENCES medawarcre.users(id) ON DELETE CASCADE,
    csrf_hash bytea NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (octet_length(token_hash) = 32),
    CHECK (octet_length(csrf_hash) = 32),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE INDEX operator_sessions_user_idx
    ON medawarcre.operator_sessions (user_id, revoked_at, expires_at);

CREATE TABLE medawarcre.oauth_authorization_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_hash bytea NOT NULL UNIQUE,
    client_id text NOT NULL
        REFERENCES medawarcre.oauth_clients(client_id) ON DELETE CASCADE,
    redirect_uri text NOT NULL,
    state text NOT NULL,
    scopes text[] NOT NULL,
    code_challenge text NOT NULL,
    code_challenge_method text NOT NULL DEFAULT 'S256'
        CHECK (code_challenge_method = 'S256'),
    audience text NOT NULL,
    resource text NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (octet_length(request_hash) = 32),
    CHECK (length(btrim(state)) BETWEEN 1 AND 512),
    CHECK (cardinality(scopes) > 0),
    CHECK (length(btrim(redirect_uri)) > 0),
    CHECK (length(btrim(code_challenge)) > 0),
    CHECK (length(btrim(audience)) > 0),
    CHECK (length(btrim(resource)) > 0),
    CHECK (consumed_at IS NULL OR consumed_at >= created_at)
);
CREATE INDEX oauth_authorization_requests_expiry_idx
    ON medawarcre.oauth_authorization_requests (expires_at, consumed_at);

CREATE TABLE medawarcre.skool_join_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL
        REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    subject_user_id uuid NOT NULL,
    community_id text NOT NULL,
    level_id text NOT NULL,
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'completed', 'canceled')),
    requested_by uuid NOT NULL,
    completed_by uuid,
    completion_source text
        CHECK (completion_source IS NULL OR completion_source IN (
            'manual_admin_invite', 'zapier_invite'
        )),
    external_mapping_id uuid,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, subject_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        ON DELETE CASCADE,
    FOREIGN KEY (requested_by)
        REFERENCES medawarcre.users(id),
    FOREIGN KEY (completed_by)
        REFERENCES medawarcre.users(id),
    FOREIGN KEY (workspace_id, external_mapping_id)
        REFERENCES medawarcre.external_accounts(workspace_id, id),
    CHECK (length(btrim(community_id)) > 0),
    CHECK (length(btrim(level_id)) > 0),
    CHECK (
        (state = 'completed'
         AND completed_by IS NOT NULL
         AND completion_source IS NOT NULL
         AND completed_at IS NOT NULL)
        OR
        (state <> 'completed'
         AND completed_by IS NULL
         AND completion_source IS NULL
         AND completed_at IS NULL)
    )
);
CREATE UNIQUE INDEX skool_join_tasks_pending_key
    ON medawarcre.skool_join_tasks (
        workspace_id, subject_user_id, community_id, level_id
    )
    WHERE state = 'pending';
CREATE INDEX skool_join_tasks_workspace_idx
    ON medawarcre.skool_join_tasks (workspace_id, state, created_at, id);

CREATE TABLE medawarcre.skool_reconciliations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL
        REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    community_id text NOT NULL,
    artifact_hash bytea NOT NULL UNIQUE,
    source text NOT NULL CHECK (source = 'operator_members_review'),
    observed_at timestamptz NOT NULL,
    confidence text NOT NULL
        CHECK (confidence IN ('confirmed', 'provisional', 'unverified')),
    complete boolean NOT NULL,
    certainty text NOT NULL
        CHECK (certainty IN ('confirmed', 'uncertain', 'conflict')),
    reason_code text NOT NULL,
    member_count integer NOT NULL CHECK (member_count >= 0),
    mapped_member_count integer NOT NULL CHECK (mapped_member_count >= 0),
    discrepancy_count integer NOT NULL CHECK (discrepancy_count >= 0),
    conflict_count integer NOT NULL CHECK (conflict_count >= 0),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (created_by)
        REFERENCES medawarcre.users(id),
    CHECK (octet_length(artifact_hash) = 32),
    CHECK (length(btrim(community_id)) > 0),
    CHECK (length(btrim(reason_code)) > 0),
    CHECK (mapped_member_count <= member_count)
);
CREATE INDEX skool_reconciliations_workspace_idx
    ON medawarcre.skool_reconciliations (
        workspace_id, community_id, observed_at DESC, id
    );

ALTER TABLE medawarcre.access_grants
    ADD CONSTRAINT access_grants_source_valid
    CHECK (source IN ('stripe', 'skool', 'manual', 'jv', 'promotion')),
    ADD CONSTRAINT access_grants_source_scope_valid
    CHECK (scope = 'subject' OR (scope = 'workspace' AND source = 'jv')),
    ADD CONSTRAINT access_grants_provider_lease_required
    CHECK (source NOT IN ('stripe', 'skool') OR ends_at IS NOT NULL);

DO $rls$
DECLARE
    relation_name text;
    global_relations constant text[] := ARRAY[
        'browser_sessions',
        'operator_sessions',
        'oauth_authorization_requests'
    ];
    tenant_relations constant text[] := ARRAY[
        'skool_join_tasks',
        'skool_reconciliations'
    ];
BEGIN
    FOREACH relation_name IN ARRAY global_relations || tenant_relations LOOP
        EXECUTE format(
            'ALTER TABLE medawarcre.%I ENABLE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY internal_read ON medawarcre.%I '
            'FOR SELECT TO medawarcre_admin '
            'USING (medawarcre.internal_authorized())',
            relation_name
        );
    END LOOP;
END
$rls$;

CREATE FUNCTION medawarcre.resolve_oauth_authority(
    access_token_hash bytea,
    expected_audience text,
    expected_resource text
)
RETURNS TABLE (
    session_id uuid,
    workspace_id uuid,
    workspace_public_id text,
    user_id uuid,
    client_id text,
    scopes text[],
    audience text,
    resource text,
    access_expires_at timestamptz,
    workspace_name text,
    workspace_state text,
    workspace_plan_id uuid,
    membership_id uuid,
    membership_role text,
    account_state text,
    account_reason_code text,
    account_updated_at timestamptz,
    profile text,
    plan_key text,
    grant_ids uuid[],
    grant_sources text[],
    grant_expires_at timestamptz,
    quota_limits jsonb,
    territories text[],
    internal_admin_role text,
    jv_grant_present boolean,
    denial_reason text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
    WITH credential AS (
        SELECT oauth_session.id AS session_id,
               oauth_session.workspace_id,
               workspace.public_id AS workspace_public_id,
               oauth_session.user_id,
               oauth_session.client_id,
               oauth_session.scopes,
               oauth_session.audience,
               oauth_session.resource,
               oauth_session.access_expires_at,
               workspace.name AS workspace_name,
               workspace.state AS workspace_state,
               workspace.plan_id AS workspace_plan_id,
               user_record.state AS user_state,
               membership.id AS membership_id,
               membership.role AS membership_role,
               membership.state AS membership_state,
               account.state AS account_state,
               account.reason_code AS account_reason_code,
               account.updated_at AS account_updated_at
        FROM medawarcre.oauth_sessions oauth_session
        JOIN medawarcre.oauth_clients oauth_client
          ON oauth_client.client_id = oauth_session.client_id
        JOIN medawarcre.workspaces workspace
          ON workspace.id = oauth_session.workspace_id
        JOIN medawarcre.users user_record
          ON user_record.id = oauth_session.user_id
        JOIN medawarcre.memberships membership
          ON membership.workspace_id = oauth_session.workspace_id
         AND membership.user_id = oauth_session.user_id
        LEFT JOIN medawarcre.workspace_accounts account
          ON account.workspace_id = oauth_session.workspace_id
        WHERE oauth_session.access_hash = access_token_hash
          AND oauth_client.active
          AND oauth_session.revoked_at IS NULL
          AND oauth_session.authority_version = 1
          AND oauth_session.access_expires_at > statement_timestamp()
          AND oauth_session.audience = expected_audience
          AND oauth_session.resource = expected_resource
    ),
    valid_grant AS (
        SELECT access_grant.id,
               access_grant.source,
               access_grant.profile,
               access_grant.plan_key,
               access_grant.ends_at,
               access_grant.updated_at,
               CASE access_grant.profile
                   WHEN 'full_operator' THEN 4
                   WHEN 'national_scout' THEN 3
                   WHEN 'local_scout' THEN 2
                   WHEN 'jv_partner' THEN 1
                   ELSE 0
               END AS profile_rank
        FROM medawarcre.access_grants access_grant
        JOIN credential
          ON credential.workspace_id = access_grant.workspace_id
        WHERE access_grant.status IN ('active', 'overridden', 'expiring')
          AND access_grant.source IN (
              'stripe', 'skool', 'manual', 'jv', 'promotion'
          )
          AND access_grant.starts_at <= statement_timestamp()
          AND (access_grant.ends_at IS NULL
               OR access_grant.ends_at > statement_timestamp())
          AND (
              access_grant.source NOT IN ('stripe', 'skool')
              OR access_grant.ends_at IS NOT NULL
          )
          AND (
              (
                  access_grant.scope = 'workspace'
                  AND access_grant.source = 'jv'
                  AND access_grant.subject_user_id IS NULL
              )
              OR (
                  access_grant.scope = 'subject'
                  AND access_grant.subject_user_id = credential.user_id
              )
          )
    ),
    selected_grant AS (
        SELECT valid_grant.*
        FROM valid_grant
        ORDER BY valid_grant.profile_rank DESC,
                 valid_grant.updated_at DESC,
                 valid_grant.id DESC
        LIMIT 1
    ),
    grant_summary AS (
        SELECT array_agg(valid_grant.id ORDER BY valid_grant.id) AS grant_ids,
               array_agg(DISTINCT valid_grant.source
                         ORDER BY valid_grant.source) AS grant_sources,
               min(valid_grant.ends_at) AS grant_expires_at
        FROM valid_grant
    ),
    selected_plan AS (
        SELECT plan.id,
               plan.plan_key,
               plan.daily_quotas,
               plan.active,
               NOT EXISTS (
                   SELECT 1
                   FROM pg_catalog.jsonb_each(plan.daily_quotas) quota
                   WHERE length(btrim(quota.key)) = 0
                      OR pg_catalog.jsonb_typeof(quota.value) <> 'number'
                      OR quota.value::text !~ '^(0|[1-9][0-9]*)$'
               ) AS quotas_valid
        FROM selected_grant
        LEFT JOIN medawarcre.plans plan
          ON plan.plan_key = selected_grant.plan_key
    ),
    territory_summary AS (
        SELECT array_agg(territory_value.value
                         ORDER BY territory_value.first_id) AS territories
        FROM (
            SELECT btrim(COALESCE(territory.state_code,
                                  territory.market,
                                  territory.name)) AS value,
                   min(territory.id::text) AS first_id
            FROM medawarcre.territories territory
            JOIN credential
              ON credential.workspace_id = territory.workspace_id
            WHERE length(btrim(COALESCE(territory.state_code,
                                        territory.market,
                                        territory.name))) > 0
            GROUP BY btrim(COALESCE(territory.state_code,
                                    territory.market,
                                    territory.name))
        ) territory_value
    ),
    staff_authority AS (
        SELECT CASE staff_role.role
                   WHEN 'owner' THEN 'platform_admin'
                   WHEN 'admin' THEN 'platform_admin'
                   WHEN 'support' THEN 'support'
                   ELSE NULL
               END AS internal_admin_role
        FROM medawarcre.staff_roles staff_role
        JOIN credential ON credential.user_id = staff_role.user_id
        WHERE staff_role.active
          AND staff_role.role IN ('owner', 'admin', 'support')
    ),
    jv_authority AS (
        SELECT EXISTS (
            SELECT 1
            FROM medawarcre.memberships actor_membership
            JOIN medawarcre.access_grants jv_grant
              ON jv_grant.workspace_id = actor_membership.workspace_id
            JOIN credential
              ON credential.user_id = actor_membership.user_id
            WHERE actor_membership.state = 'active'
              AND jv_grant.profile = 'jv_partner'
              AND jv_grant.status IN ('active', 'overridden', 'expiring')
              AND jv_grant.source IN (
                  'stripe', 'skool', 'manual', 'jv', 'promotion'
              )
              AND jv_grant.starts_at <= statement_timestamp()
              AND (jv_grant.ends_at IS NULL
                   OR jv_grant.ends_at > statement_timestamp())
              AND (
                  jv_grant.source NOT IN ('stripe', 'skool')
                  OR jv_grant.ends_at IS NOT NULL
              )
              AND (
                  (
                      jv_grant.scope = 'workspace'
                      AND jv_grant.source = 'jv'
                      AND jv_grant.subject_user_id IS NULL
                  )
                  OR (
                      jv_grant.scope = 'subject'
                      AND jv_grant.subject_user_id = actor_membership.user_id
                  )
              )
        ) AS present
    )
    SELECT credential.session_id,
           credential.workspace_id,
           credential.workspace_public_id,
           credential.user_id,
           credential.client_id,
           credential.scopes,
           credential.audience,
           credential.resource,
           credential.access_expires_at,
           credential.workspace_name,
           credential.workspace_state,
           credential.workspace_plan_id,
           credential.membership_id,
           credential.membership_role,
           credential.account_state,
           credential.account_reason_code,
           credential.account_updated_at,
           selected_grant.profile,
           selected_grant.plan_key,
           COALESCE(grant_summary.grant_ids, ARRAY[]::uuid[]),
           COALESCE(grant_summary.grant_sources, ARRAY[]::text[]),
           grant_summary.grant_expires_at,
           CASE WHEN selected_plan.id IS NOT NULL
                     AND selected_plan.active
                     AND selected_plan.quotas_valid
                THEN selected_plan.daily_quotas
                ELSE NULL
           END,
           COALESCE(territory_summary.territories, ARRAY[]::text[]),
           staff_authority.internal_admin_role,
           COALESCE(jv_authority.present, false),
           CASE
               WHEN credential.user_state <> 'active'
                   THEN 'user_' || credential.user_state
               WHEN credential.workspace_state NOT IN ('active', 'past_due')
                   THEN 'workspace_' || credential.workspace_state
               WHEN credential.membership_state <> 'active'
                   THEN 'membership_' || credential.membership_state
               WHEN credential.account_state IS NULL
                   THEN 'account_missing'
               WHEN credential.account_state NOT IN (
                   'active', 'past_due', 'grace_period'
               )
                   THEN 'account_' || credential.account_state
               WHEN selected_grant.id IS NULL
                   THEN 'entitlement_missing_or_expired'
               WHEN selected_grant.plan_key IS NULL
                    OR selected_plan.id IS NULL
                    OR NOT selected_plan.active
                    OR NOT selected_plan.quotas_valid
                   THEN 'plan_missing_or_invalid'
               ELSE NULL
           END
    FROM credential
    LEFT JOIN selected_grant ON true
    LEFT JOIN grant_summary ON true
    LEFT JOIN selected_plan ON true
    LEFT JOIN territory_summary ON true
    LEFT JOIN staff_authority ON true
    LEFT JOIN jv_authority ON true
$function$;

REVOKE ALL ON medawarcre.browser_sessions,
              medawarcre.operator_sessions,
              medawarcre.oauth_authorization_requests,
              medawarcre.skool_join_tasks,
              medawarcre.skool_reconciliations
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_admission,
     medawarcre_oauth, medawarcre_provider_ingress,
     medawarcre_provider_reconcile, medawarcre_worker, medawarcre_scheduler;
GRANT SELECT ON medawarcre.browser_sessions,
                medawarcre.operator_sessions,
                medawarcre.oauth_authorization_requests,
                medawarcre.skool_join_tasks,
                medawarcre.skool_reconciliations
TO medawarcre_backup;

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

REVOKE ALL ON FUNCTION medawarcre.resolve_oauth_authority(bytea, text, text)
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth, medawarcre_provider_ingress,
     medawarcre_provider_reconcile, medawarcre_worker, medawarcre_scheduler;
GRANT USAGE ON SCHEMA medawarcre TO medawarcre_oauth;
GRANT EXECUTE ON FUNCTION medawarcre.resolve_oauth_authority(bytea, text, text)
TO medawarcre_oauth;
