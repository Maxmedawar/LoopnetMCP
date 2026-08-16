-- Phase 6D: four defects the 0013 repair introduced or left live.
--
-- A confirmatory review of 0013 ran the probes rather than reading the
-- migration, and found that fixing the projection's trust model had left four
-- smaller edges. Each is reproduced below as the sequence that breaks, because
-- three of the four fail closed and are therefore invisible except as an
-- outage.
--
-- The fifth thing that review found -- that a revoked member's entitlement
-- never reached the scheduler, because the projected copy is only refreshed by
-- a request the revocation prevents -- is NOT fixed here. It cannot be fixed in
-- the projection: the projection is not running. It is fixed in
-- `postgres/jobs.py`, whose entitlement gate now reads the platform relations
-- directly.

CREATE OR REPLACE FUNCTION medawarcre.project_platform_identity(
    p_workspace_id uuid,
    p_workspace_public_id text,
    p_user_id uuid,
    p_platform_user_id bigint
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, medawarcre
AS $function$
DECLARE
    source_workspace medawarcre.platform_workspaces%ROWTYPE;
    source_user medawarcre.platform_users%ROWTYPE;
    source_role text;
    source_plan_key text;
    resolved_plan uuid;
    resolved_workspace uuid;
BEGIN
    IF p_workspace_id IS NULL OR p_user_id IS NULL THEN
        RAISE EXCEPTION 'projection requires both identifiers'
            USING ERRCODE = 'null_value_not_allowed';
    END IF;

    SELECT * INTO source_workspace
      FROM medawarcre.platform_workspaces
     WHERE public_id = p_workspace_public_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'projection source workspace does not exist'
            USING ERRCODE = 'no_data_found';
    END IF;

    SELECT * INTO source_user
      FROM medawarcre.platform_users
     WHERE id = p_platform_user_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'projection source user does not exist'
            USING ERRCODE = 'no_data_found';
    END IF;

    SELECT membership.role INTO source_role
      FROM medawarcre.platform_memberships membership
     WHERE membership.workspace_id = source_workspace.id
       AND membership.user_id = p_platform_user_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'projection source membership does not exist'
            USING ERRCODE = 'no_data_found';
    END IF;
    IF source_role NOT IN ('owner', 'admin', 'member', 'viewer', 'jv_partner') THEN
        RAISE EXCEPTION 'projection source role has no certified equivalent'
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT plan.key INTO source_plan_key
      FROM medawarcre.platform_plans plan
     WHERE plan.id = source_workspace.plan_id;

    IF source_plan_key IS NOT NULL THEN
        BEGIN
            INSERT INTO medawarcre.plans (plan_key, name)
            VALUES (source_plan_key, initcap(source_plan_key))
            ON CONFLICT (plan_key) DO NOTHING;
        EXCEPTION WHEN unique_violation THEN
            NULL;
        END;
        SELECT plan.id INTO resolved_plan
          FROM medawarcre.plans plan
         WHERE plan.plan_key = source_plan_key;
    END IF;

    -- DEFECT 1: an email reassignment locked a user out permanently.
    --
    -- 0013 narrowed the arbiter to (id) and added `SET email = EXCLUDED.email`.
    -- `medawarcre.users` also carries `users_email_casefold_key`, so the
    -- supported sequence -- rename A off an address, give B that address --
    -- made every one of B's requests raise UniqueViolation until A happened to
    -- project first. Fail-closed, and a total lockout.
    --
    -- The email is now only taken when no other certified user holds it. A
    -- stale certified email is a cosmetic divergence; a lockout is an outage.
    BEGIN
        INSERT INTO medawarcre.users (id, email, name)
        VALUES (p_user_id, source_user.email, source_user.name)
        ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name,
                email = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM medawarcre.users other
                        WHERE lower(other.email) = lower(EXCLUDED.email)
                          AND other.id <> EXCLUDED.id
                    ) THEN medawarcre.users.email
                    ELSE EXCLUDED.email
                END,
                updated_at = statement_timestamp();
    EXCEPTION WHEN unique_violation THEN
        -- Another transaction inserted the same identity concurrently.
        NULL;
    END;

    -- DEFECT 2: concurrent cold start raised workspaces_pkey.
    --
    -- 0013's arbiter named (public_id) only, but the id is derived from the
    -- public id, so on two simultaneous first requests for a new workspace the
    -- primary key collides first and the conflict clause never applies. It
    -- reproduced on the first of eight concurrent rounds -- a cold-start-only
    -- flake, on the launch path.
    BEGIN
        INSERT INTO medawarcre.workspaces (id, public_id, name, plan_id, state)
        VALUES (p_workspace_id, source_workspace.public_id, source_workspace.name,
                resolved_plan, 'active')
        ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name,
                plan_id = EXCLUDED.plan_id,
                updated_at = statement_timestamp();
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;

    SELECT workspace.id INTO resolved_workspace
      FROM medawarcre.workspaces workspace
     WHERE workspace.public_id = source_workspace.public_id;
    IF resolved_workspace IS NULL THEN
        RAISE EXCEPTION 'workspace projection did not resolve'
            USING ERRCODE = 'no_data_found';
    END IF;

    BEGIN
        INSERT INTO medawarcre.memberships (workspace_id, user_id, role, state)
        VALUES (resolved_workspace, p_user_id, source_role, 'active')
        ON CONFLICT (workspace_id, user_id) DO UPDATE
            SET role = EXCLUDED.role,
                state = 'active',
                updated_at = statement_timestamp();
    EXCEPTION WHEN unique_violation THEN
        NULL;
    END;

    RETURN resolved_workspace;
END
$function$;


CREATE OR REPLACE FUNCTION medawarcre.project_platform_authority(
    p_workspace_id uuid,
    p_workspace_public_id text,
    p_user_id uuid,
    p_platform_user_id bigint,
    p_session_id uuid,
    p_platform_session_id text,
    p_audience text,
    p_resource text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, medawarcre
AS $function$
DECLARE
    source_workspace_id bigint;
    source_session medawarcre.platform_oauth_sessions%ROWTYPE;
    source_account_state text;
    source_grant medawarcre.platform_access_grants%ROWTYPE;
    source_quotas jsonb;
    grant_ref bytea;
    session_access bytea;
    session_refresh bytea;
    session_expires timestamptz;
    session_revoked timestamptz;
    refresh_at timestamptz;
BEGIN
    SELECT id INTO source_workspace_id
      FROM medawarcre.platform_workspaces
     WHERE public_id = p_workspace_public_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'authority projection source workspace does not exist'
            USING ERRCODE = 'no_data_found';
    END IF;

    SELECT * INTO source_session
      FROM medawarcre.platform_oauth_sessions
     WHERE session_id = p_platform_session_id
       AND workspace_id = p_workspace_public_id
       AND user_id = p_platform_user_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'authority projection source session does not exist'
            USING ERRCODE = 'no_data_found';
    END IF;

    SELECT state INTO source_account_state
      FROM medawarcre.platform_accounts
     WHERE workspace_id = source_workspace_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'authority projection source account does not exist'
            USING ERRCODE = 'no_data_found';
    END IF;

    SELECT * INTO source_grant
      FROM medawarcre.platform_access_grants
     WHERE workspace_id = source_workspace_id
       AND subject_user_id = p_platform_user_id
       AND status IN ('active', 'overridden', 'expiring')
       AND (starts_at)::timestamptz <= statement_timestamp()
       AND (ends_at IS NULL OR (ends_at)::timestamptz > statement_timestamp())
     ORDER BY CASE profile
                  WHEN 'full_operator' THEN 4
                  WHEN 'national_scout' THEN 3
                  WHEN 'local_scout' THEN 2
                  WHEN 'jv_partner' THEN 1
                  ELSE 0
              END DESC,
              (updated_at)::timestamptz DESC,
              id DESC
     LIMIT 1;

    INSERT INTO medawarcre.workspace_accounts (workspace_id, state)
    VALUES (
        p_workspace_id,
        CASE WHEN source_account_state IN (
                 'active', 'past_due', 'grace_period', 'suspended',
                 'under_review', 'canceled', 'deletion_pending', 'deleted',
                 'invited', 'registered', 'verified')
             THEN source_account_state ELSE 'suspended' END
    )
    ON CONFLICT (workspace_id) DO UPDATE
        SET state = EXCLUDED.state, updated_at = statement_timestamp();

    INSERT INTO medawarcre.oauth_clients (client_id, name, redirect_uris, scopes)
    VALUES (source_session.client_id, source_session.client_id,
            ARRAY['https://projected.invalid/callback'],
            ARRAY['mcp:tools'])
    ON CONFLICT (client_id) DO NOTHING;

    session_access := sha256(convert_to('projected-access/' || p_session_id::text, 'UTF8'));
    session_refresh := sha256(convert_to('projected-refresh/' || p_session_id::text, 'UTF8'));

    -- DEFECT 3: two unvalidated text -> timestamptz casts.
    --
    -- These columns are text in the platform schema. 0013 cast them straight
    -- through. An unparseable value turned every request into an outage
    -- (InvalidDatetimeFormat), and a value that parses but predates year 1 --
    -- '0001-01-01 BC' does -- was written into the certified table, after which
    -- every psycopg read of medawarcre.oauth_sessions raised `timestamp too
    -- small`. One bad row, and the relation becomes unreadable.
    --
    -- Both now fail closed to "expired" and "revoked now" rather than to an
    -- error, and both are clamped away from the range psycopg cannot decode.
    BEGIN
        session_expires := (source_session.access_expires_at)::timestamptz;
    EXCEPTION WHEN others THEN
        session_expires := statement_timestamp() - interval '1 second';
    END;
    IF session_expires IS NULL OR session_expires < timestamptz '1900-01-01Z' THEN
        session_expires := statement_timestamp() - interval '1 second';
    END IF;

    IF source_session.revoked_at IS NULL THEN
        session_revoked := NULL;
    ELSE
        BEGIN
            session_revoked := (source_session.revoked_at)::timestamptz;
        EXCEPTION WHEN others THEN
            session_revoked := statement_timestamp();
        END;
        IF session_revoked IS NULL OR session_revoked < timestamptz '1900-01-01Z' THEN
            session_revoked := statement_timestamp();
        END IF;
    END IF;

    refresh_at := greatest(session_expires,
                           statement_timestamp() + interval '1 minute');

    INSERT INTO medawarcre.oauth_sessions (
        id, workspace_id, user_id, client_id, scopes, audience, resource,
        authority_version, access_hash, refresh_hash, access_expires_at,
        refresh_expires_at, refresh_family_expires_at, revoked_at
    )
    VALUES (
        p_session_id, p_workspace_id, p_user_id, source_session.client_id,
        ARRAY['mcp:tools'], p_audience, p_resource, 1,
        session_access, session_refresh,
        session_expires, refresh_at, refresh_at, session_revoked
    )
    ON CONFLICT (id) DO UPDATE SET
        audience = EXCLUDED.audience,
        resource = EXCLUDED.resource,
        access_expires_at = EXCLUDED.access_expires_at,
        refresh_expires_at = EXCLUDED.refresh_expires_at,
        refresh_family_expires_at = EXCLUDED.refresh_family_expires_at,
        revoked_at = EXCLUDED.revoked_at,
        updated_at = statement_timestamp();

    grant_ref := sha256(convert_to(
        'projected-grant/' || p_workspace_id::text || '/' || p_user_id::text,
        'UTF8'
    ));

    IF source_grant.id IS NULL THEN
        UPDATE medawarcre.access_grants
           SET status = 'revoked',
               ends_at = statement_timestamp(),
               updated_at = statement_timestamp()
         WHERE workspace_id = p_workspace_id
           AND subject_user_id = p_user_id
           AND source = 'manual'
           AND status <> 'revoked';
    ELSE
        SELECT (plan.daily_quotas)::jsonb INTO source_quotas
          FROM medawarcre.platform_plans plan
         WHERE plan.key = source_grant.plan_key;

        IF source_grant.plan_key IS NOT NULL THEN
            INSERT INTO medawarcre.plans (plan_key, name, daily_quotas)
            VALUES (source_grant.plan_key, initcap(source_grant.plan_key),
                    COALESCE(source_quotas, '{}'::jsonb))
            ON CONFLICT (plan_key) DO UPDATE
                SET daily_quotas = COALESCE(source_quotas, '{}'::jsonb),
                    active = true,
                    updated_at = statement_timestamp();
        END IF;

        INSERT INTO medawarcre.access_grants (
            workspace_id, subject_user_id, scope, source, external_ref_hash,
            profile, plan_key, status, starts_at, ends_at
        )
        VALUES (
            p_workspace_id, p_user_id, 'subject', 'manual', grant_ref,
            source_grant.profile, source_grant.plan_key, source_grant.status,
            (source_grant.starts_at)::timestamptz,
            (source_grant.ends_at)::timestamptz
        )
        ON CONFLICT (source, external_ref_hash) DO UPDATE SET
            profile = EXCLUDED.profile,
            plan_key = EXCLUDED.plan_key,
            status = EXCLUDED.status,
            starts_at = EXCLUDED.starts_at,
            ends_at = EXCLUDED.ends_at,
            updated_at = statement_timestamp();
    END IF;

    UPDATE medawarcre.access_grants
       SET status = 'revoked',
           ends_at = statement_timestamp(),
           updated_at = statement_timestamp()
     WHERE workspace_id = p_workspace_id
       AND subject_user_id = p_user_id
       AND source = 'manual'
       AND external_ref_hash <> grant_ref
       AND status <> 'revoked';

    -- DEFECT 4: territory ids were never corrected, so a workspace could be
    -- permanently denied.
    --
    -- The position index is baked into the first four bytes of the id, and
    -- admission rebuilds the array ordered by `min(territory.id::text)`. 0013
    -- (and 0012) inserted with ON CONFLICT DO NOTHING, so an id keeping a stale
    -- position survived. Probe: TX/NY/CA, remove TX, add FL -> resolver says
    -- ('NY','CA','FL') and the certified text order says ['NY','FL','CA'] ->
    -- `authority_changed`, on every retry, forever.
    --
    -- Replaced wholesale instead. There are no foreign keys onto
    -- medawarcre.territories, it is one transaction, and correctness here is
    -- worth more than the churn.
    --
    -- DEFECT 5, in the same statement: COALESCE where AuthorityResolver uses
    -- Python's `or`. An empty-string `state` is not NULL, so COALESCE returned
    -- it and the length filter then dropped the row -- while the resolver fell
    -- through to `market`. The two sets diverged and the workspace was denied.
    DELETE FROM medawarcre.territories WHERE workspace_id = p_workspace_id;

    INSERT INTO medawarcre.territories (id, workspace_id, name, state_code)
    SELECT (lpad(to_hex((ordered.position - 1)::int), 8, '0')
            || substr(md5(p_workspace_public_id || '/' || ordered.value), 9))::uuid,
           p_workspace_id,
           ordered.value,
           CASE WHEN ordered.value ~ '^[A-Z]{2}$' THEN ordered.value END
      FROM (
        SELECT grouped.value,
               row_number() OVER (ORDER BY grouped.first_id) AS position
          FROM (
            SELECT btrim(COALESCE(NULLIF(btrim(territory.state), ''),
                                  NULLIF(btrim(territory.market), ''),
                                  territory.name)) AS value,
                   min(territory.id) AS first_id
              FROM medawarcre.platform_territories territory
             WHERE territory.workspace_id = source_workspace_id
               AND length(btrim(COALESCE(NULLIF(btrim(territory.state), ''),
                                         NULLIF(btrim(territory.market), ''),
                                         territory.name))) > 0
             GROUP BY btrim(COALESCE(NULLIF(btrim(territory.state), ''),
                                     NULLIF(btrim(territory.market), ''),
                                     territory.name))
          ) grouped
      ) ordered;
END
$function$;
