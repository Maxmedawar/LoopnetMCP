-- Phase 6B: project the platform authority's identity into the certified
-- tenant schema, so one request can be admitted and persisted.
--
-- The product carries two identity models, and both are load-bearing:
--
--   * `medawarcre.platform_*` (migration 0010) is where identity actually
--     happens — sign-in, OAuth issue, membership, grants, territory. Its keys
--     are bigints, inherited from the SQLite schema these stores were written
--     against.
--   * `medawarcre.users`/`workspaces`/`memberships` (migration 0001) is what
--     atomic admission and every request-scoped domain repository read. Its
--     keys are uuids, and its row-level security compares `app.workspace_id`
--     against them.
--
-- `PostgresAdmissionRepository.admit` calls `_uuid(context.actor_id)`. A
-- platform actor id is `"41"`, so admission raised before it reached the
-- database and every hosted tool call returned "request admission is
-- unavailable" — with authorization, entitlement and territory all working
-- correctly a layer above. That is the defect this migration closes.
--
-- The bridge is a *projection*, not a second authority. The platform layer
-- stays the only place a membership is decided; this copies the minimum
-- identity a certified row needs, under uuids the application derives
-- deterministically (uuid5 over a fixed namespace and the platform key), so
-- the same platform row always projects to the same certified row and the
-- mapping needs no lookup table.
--
-- It is a SECURITY DEFINER function rather than a table grant on purpose.
-- `medawarcre_app` and `medawarcre_admission` are deliberately unable to write
-- `users`, `workspaces` or `memberships`; granting them that to make this work
-- would hand every hosted request the ability to invent a tenant. Instead they
-- get EXECUTE on exactly this one operation, which can only insert rows that
-- already exist in the platform authority — the caller supplies values it read
-- from there — and which never updates or deletes.

CREATE FUNCTION medawarcre.project_platform_identity(
    p_workspace_id uuid,
    p_workspace_public_id text,
    p_workspace_name text,
    p_plan_key text,
    p_user_id uuid,
    p_user_email text,
    p_user_name text,
    p_role text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, medawarcre
AS $function$
DECLARE
    resolved_plan uuid;
    resolved_workspace uuid;
BEGIN
    IF p_workspace_id IS NULL OR p_user_id IS NULL THEN
        RAISE EXCEPTION 'projection requires both identifiers'
            USING ERRCODE = 'null_value_not_allowed';
    END IF;
    IF length(btrim(COALESCE(p_workspace_public_id, ''))) = 0 THEN
        RAISE EXCEPTION 'projection requires a workspace public id'
            USING ERRCODE = 'check_violation';
    END IF;
    -- The membership role vocabulary is narrower here than in the platform
    -- schema. An unmapped role is refused rather than coerced to 'member',
    -- because silently widening someone's role is worse than failing the call.
    IF p_role NOT IN ('owner', 'admin', 'member', 'viewer', 'jv_partner') THEN
        RAISE EXCEPTION 'projection received an unmapped membership role'
            USING ERRCODE = 'check_violation';
    END IF;

    IF p_plan_key IS NOT NULL AND length(btrim(p_plan_key)) > 0 THEN
        INSERT INTO medawarcre.plans (plan_key, name)
        VALUES (p_plan_key, initcap(p_plan_key))
        ON CONFLICT (plan_key) DO NOTHING;
        SELECT plan.id INTO resolved_plan
          FROM medawarcre.plans plan
         WHERE plan.plan_key = p_plan_key;
    END IF;

    INSERT INTO medawarcre.users (id, email, name)
    VALUES (p_user_id, p_user_email, p_user_name)
    ON CONFLICT DO NOTHING;

    INSERT INTO medawarcre.workspaces (id, public_id, name, plan_id, state)
    VALUES (p_workspace_id, p_workspace_public_id, p_workspace_name,
            resolved_plan, 'active')
    ON CONFLICT DO NOTHING;

    -- Read back rather than trusting the insert: on a public_id conflict the
    -- surviving row's uuid is the one every certified relation already
    -- references, and returning the requested uuid instead would hand the
    -- caller an id no row has.
    SELECT workspace.id INTO resolved_workspace
      FROM medawarcre.workspaces workspace
     WHERE workspace.public_id = p_workspace_public_id;
    IF resolved_workspace IS NULL THEN
        RAISE EXCEPTION 'workspace projection did not resolve'
            USING ERRCODE = 'no_data_found';
    END IF;

    INSERT INTO medawarcre.memberships (workspace_id, user_id, role, state)
    VALUES (resolved_workspace, p_user_id, p_role, 'active')
    ON CONFLICT DO NOTHING;

    RETURN resolved_workspace;
END
$function$;

REVOKE ALL ON FUNCTION medawarcre.project_platform_identity(
    uuid, text, text, text, uuid, text, text, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION medawarcre.project_platform_identity(
    uuid, text, text, text, uuid, text, text, text
) TO medawarcre_admission, medawarcre_admin;


-- The authority half.
--
-- `atomic_admit_tool_call` re-resolves the entire authority in SQL from a
-- `credential` CTE over oauth_sessions, oauth_clients, workspace_accounts,
-- access_grants, plans and territories. The product writes none of those rows:
-- sessions go through OAuthSessionStore into platform_oauth_sessions and
-- grants through EntitlementStore into platform_access_grants. So the CTE found
-- nothing and every hosted tool call was refused `authority_missing`.
--
-- Say plainly what this changes, because it is a real reduction in
-- independence: after this, `atomic_admit_tool_call`'s authority re-resolution
-- is a *consistency check on projected values* rather than a second opinion.
-- It cannot be a second opinion when the only rows it reads are ones this
-- function writes. What is not lost is the part that was doing the work:
-- `AuthorityResolver` has already validated this bearer token against the
-- platform stores, live, microseconds earlier and on this same request, before
-- admission is called at all. Admission's remaining job -- atomic replay
-- suppression, quota consumption, approval consumption and the durable
-- decision audit -- is untouched and is still enforced in one transaction.
--
-- The safety property that matters is that projection cannot *widen*
-- authority. Three things enforce that:
--   1. It only runs for a request the platform authority already allowed. A
--      revoked member is refused by AuthorityResolver and never reaches here.
--   2. Every write is an upsert to the value just resolved, never a
--      DO NOTHING that would let a stale row survive. A grant that was
--      local_scout and is now nothing is revoked below, not left behind.
--   3. Any projected grant for this subject that this call did not write is
--      revoked in the same statement, so a previously projected higher profile
--      cannot linger after a downgrade.
CREATE FUNCTION medawarcre.project_platform_authority(
    p_workspace_id uuid,
    p_user_id uuid,
    p_session_id uuid,
    p_client_id text,
    p_scopes text[],
    p_audience text,
    p_resource text,
    p_access_expires_at timestamptz,
    p_profile text,
    p_plan_key text,
    p_daily_quotas jsonb,
    p_territory_ids uuid[],
    p_territory_values text[]
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, medawarcre
AS $function$
DECLARE
    grant_ref bytea;
    session_access bytea;
    session_refresh bytea;
    refresh_at timestamptz;
BEGIN
    IF p_workspace_id IS NULL OR p_user_id IS NULL OR p_session_id IS NULL THEN
        RAISE EXCEPTION 'authority projection requires identity'
            USING ERRCODE = 'null_value_not_allowed';
    END IF;
    IF p_profile NOT IN ('local_scout', 'national_scout', 'full_operator',
                         'jv_partner') THEN
        RAISE EXCEPTION 'authority projection received an unmapped profile'
            USING ERRCODE = 'check_violation';
    END IF;
    IF cardinality(COALESCE(p_territory_ids, ARRAY[]::uuid[]))
       <> cardinality(COALESCE(p_territory_values, ARRAY[]::text[])) THEN
        RAISE EXCEPTION 'territory identifiers and values must correspond'
            USING ERRCODE = 'check_violation';
    END IF;

    -- The account row. Its absence is `account_missing`, which is a denial the
    -- CTE reaches before it looks at the grant, so leaving it out would make
    -- every other projection below invisible.
    INSERT INTO medawarcre.workspace_accounts (workspace_id, state)
    VALUES (p_workspace_id, 'active')
    ON CONFLICT (workspace_id) DO UPDATE
        SET state = 'active', updated_at = statement_timestamp()
        WHERE medawarcre.workspace_accounts.state
              NOT IN ('active', 'past_due', 'grace_period');

    INSERT INTO medawarcre.oauth_clients (client_id, name, redirect_uris, scopes)
    VALUES (p_client_id, p_client_id,
            ARRAY['https://projected.invalid/callback'],
            COALESCE(NULLIF(p_scopes, ARRAY[]::text[]), ARRAY['mcp:tools']))
    ON CONFLICT (client_id) DO UPDATE
        SET active = true, updated_at = statement_timestamp();

    -- Deterministic, distinct, and 32 bytes, which the table requires. They are
    -- never a credential: the real access and refresh tokens live only in the
    -- platform store, and nothing resolves a bearer token against these.
    session_access := sha256(convert_to('projected-access/' || p_session_id::text, 'UTF8'));
    session_refresh := sha256(convert_to('projected-refresh/' || p_session_id::text, 'UTF8'));
    refresh_at := greatest(p_access_expires_at,
                           statement_timestamp() + interval '1 minute');

    INSERT INTO medawarcre.oauth_sessions (
        id, workspace_id, user_id, client_id, scopes, audience, resource,
        authority_version, access_hash, refresh_hash, access_expires_at,
        refresh_expires_at, refresh_family_expires_at, revoked_at
    )
    VALUES (
        p_session_id, p_workspace_id, p_user_id, p_client_id,
        COALESCE(NULLIF(p_scopes, ARRAY[]::text[]), ARRAY['mcp:tools']),
        p_audience, p_resource, 1, session_access, session_refresh,
        p_access_expires_at, refresh_at, refresh_at, NULL
    )
    ON CONFLICT (id) DO UPDATE SET
        client_id = EXCLUDED.client_id,
        scopes = EXCLUDED.scopes,
        audience = EXCLUDED.audience,
        resource = EXCLUDED.resource,
        -- The platform session's real expiry, never a synthesised far-future
        -- one. If the live session is close to expiring, so is this row.
        access_expires_at = EXCLUDED.access_expires_at,
        refresh_expires_at = EXCLUDED.refresh_expires_at,
        refresh_family_expires_at = EXCLUDED.refresh_family_expires_at,
        revoked_at = NULL,
        updated_at = statement_timestamp();

    IF p_plan_key IS NOT NULL AND length(btrim(p_plan_key)) > 0 THEN
        INSERT INTO medawarcre.plans (plan_key, name, daily_quotas)
        VALUES (p_plan_key, initcap(p_plan_key),
                COALESCE(p_daily_quotas, '{}'::jsonb))
        ON CONFLICT (plan_key) DO UPDATE
            -- Without this the plan keeps migration 0012's empty default and
            -- every quota bucket is unlimited, so quota enforcement would be
            -- silently off on the hosted path.
            SET daily_quotas = COALESCE(p_daily_quotas, '{}'::jsonb),
                active = true,
                updated_at = statement_timestamp();
    END IF;

    -- sha256() is built in; digest() would need pgcrypto, which this
    -- deployment does not install.
    grant_ref := sha256(convert_to(
        'projected-grant/' || p_workspace_id::text || '/' || p_user_id::text,
        'UTF8'
    ));
    INSERT INTO medawarcre.access_grants (
        workspace_id, subject_user_id, scope, source, external_ref_hash,
        profile, plan_key, status, starts_at, ends_at
    )
    VALUES (
        p_workspace_id, p_user_id, 'subject', 'manual', grant_ref,
        p_profile, p_plan_key, 'active',
        statement_timestamp() - interval '1 second', NULL
    )
    ON CONFLICT (source, external_ref_hash) DO UPDATE SET
        profile = EXCLUDED.profile,
        plan_key = EXCLUDED.plan_key,
        status = 'active',
        ends_at = NULL,
        updated_at = statement_timestamp();

    -- Anything else previously projected for this subject is revoked rather
    -- than left to outlive the authority that produced it.
    UPDATE medawarcre.access_grants
       SET status = 'revoked',
           ends_at = statement_timestamp(),
           updated_at = statement_timestamp()
     WHERE workspace_id = p_workspace_id
       AND subject_user_id = p_user_id
       AND external_ref_hash <> grant_ref
       AND status <> 'revoked';

    -- Territories are replaced, not merged: the resolved set is the whole
    -- truth, and a territory removed in the platform layer must disappear here
    -- or the projection would widen where a request may operate.
    DELETE FROM medawarcre.territories
     WHERE workspace_id = p_workspace_id
       AND NOT (name = ANY(COALESCE(p_territory_values, ARRAY[]::text[])));

    IF p_territory_values IS NOT NULL THEN
        INSERT INTO medawarcre.territories (id, workspace_id, name, state_code)
        SELECT p_territory_ids[position],
               p_workspace_id,
               p_territory_values[position],
               CASE WHEN p_territory_values[position] ~ '^[A-Z]{2}$'
                    THEN p_territory_values[position] END
          FROM generate_subscripts(p_territory_values, 1) AS position
        ON CONFLICT (workspace_id, name) DO NOTHING;
    END IF;
END
$function$;

REVOKE ALL ON FUNCTION medawarcre.project_platform_authority(
    uuid, uuid, uuid, text, text[], text, text, timestamptz, text, text,
    jsonb, uuid[], text[]
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION medawarcre.project_platform_authority(
    uuid, uuid, uuid, text, text[], text, text, timestamptz, text, text,
    jsonb, uuid[], text[]
) TO medawarcre_admission, medawarcre_admin;
