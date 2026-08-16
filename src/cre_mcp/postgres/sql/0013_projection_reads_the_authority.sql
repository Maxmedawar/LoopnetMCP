-- Phase 6C: make the projection a projection.
--
-- An independent review found migration 0012's central claim false. Its header
-- said the function "can only insert rows that already exist in the platform
-- authority — the caller supplies values it read from there". It validated
-- argument *shape* and nothing else, so a hand-built TenantContext naming a
-- workspace that does not exist, with profile `full_operator` and a
-- quota of 999999, was projected into the certified schema and admitted:
--
--     decision='allowed'  reason_code='authority_admitted'
--     WORKSPACES: [('ws_fabricated_by_caller','Fabricated','active')]
--     GRANTS:     [('full_operator','operator','active',None)]
--
-- Not reachable over HTTP, because the context comes from AuthorityResolver.
-- But it made admission an echo of its caller rather than a check on it, and
-- it made three further defects possible, all of which this migration closes
-- with the same change:
--
--   * A denied admission left a complete projected tenant behind, because the
--     projection commits before `admit()` runs. It still commits first — it
--     has to, admission reads the rows — but it can now only write rows the
--     platform authority already holds, so what survives a denial is a copy of
--     real state rather than a fabrication.
--   * A revoked Skool member's scheduled jobs kept running. Nothing but the
--     projection writes `medawarcre.access_grants`, and it wrote
--     `status='active', ends_at=NULL` from the caller's profile. The
--     scheduler's documented "live entitlement recheck" therefore read a row
--     that only a request the revoked member can no longer make would refresh.
--     The grant is now copied from `platform_access_grants` with its real
--     status and end date, so a revoked grant projects as revoked.
--   * Every hosted user was written into `medawarcre.memberships` as `owner`,
--     because `TenantContext` carries no role and the caller passed
--     `"owner" if profile else "member"`. The role now comes from
--     `platform_memberships`.
--
-- The functions are replaced rather than patched, and their signatures change,
-- so `ADMISSION_FUNCTIONS` in `postgres/authority.py` moves with them. The old
-- signatures are dropped: leaving them callable would leave the defect
-- callable.

DROP FUNCTION medawarcre.project_platform_identity(
    uuid, text, text, text, uuid, text, text, text
);
DROP FUNCTION medawarcre.project_platform_authority(
    uuid, uuid, uuid, text, text[], text, text, timestamptz, text, text,
    jsonb, uuid[], text[]
);

-- Identity: workspace, user and membership, every field read from the
-- platform authority and refused when it is not there.
CREATE FUNCTION medawarcre.project_platform_identity(
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

    -- The membership is the authorization fact, not a formality: no row means
    -- this actor is not a member of this workspace, and there is nothing to
    -- project.
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
        INSERT INTO medawarcre.plans (plan_key, name)
        VALUES (source_plan_key, initcap(source_plan_key))
        ON CONFLICT (plan_key) DO NOTHING;
        SELECT plan.id INTO resolved_plan
          FROM medawarcre.plans plan
         WHERE plan.plan_key = source_plan_key;
    END IF;

    INSERT INTO medawarcre.users (id, email, name)
    VALUES (p_user_id, source_user.email, source_user.name)
    ON CONFLICT (id) DO UPDATE
        SET email = EXCLUDED.email,
            name = EXCLUDED.name,
            updated_at = statement_timestamp();

    INSERT INTO medawarcre.workspaces (id, public_id, name, plan_id, state)
    VALUES (p_workspace_id, source_workspace.public_id, source_workspace.name,
            resolved_plan, 'active')
    ON CONFLICT (public_id) DO UPDATE
        -- 0012 used DO NOTHING here, so a workspace kept its first-projected
        -- plan forever. It is an upsert now for the same reason everything
        -- else here is: the certified row must equal the platform row, not
        -- whatever it equalled the first time anybody asked.
        SET name = EXCLUDED.name,
            plan_id = EXCLUDED.plan_id,
            updated_at = statement_timestamp();

    SELECT workspace.id INTO resolved_workspace
      FROM medawarcre.workspaces workspace
     WHERE workspace.public_id = source_workspace.public_id;

    INSERT INTO medawarcre.memberships (workspace_id, user_id, role, state)
    VALUES (resolved_workspace, p_user_id, source_role, 'active')
    ON CONFLICT (workspace_id, user_id) DO UPDATE
        SET role = EXCLUDED.role,
            state = 'active',
            updated_at = statement_timestamp();

    RETURN resolved_workspace;
END
$function$;

REVOKE ALL ON FUNCTION medawarcre.project_platform_identity(
    uuid, text, uuid, bigint
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION medawarcre.project_platform_identity(
    uuid, text, uuid, bigint
) TO medawarcre_admission, medawarcre_admin;


-- Authority: session, account, grant, plan quotas and territories, every one
-- copied from the platform relations rather than accepted from the caller.
CREATE FUNCTION medawarcre.project_platform_authority(
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

    -- The live grant, chosen the way the platform authority chooses it. If
    -- there is none the projection writes no grant and revokes what it wrote
    -- before, which is the whole point: a revoked member's projected
    -- entitlement must go away, including for the background worker, which
    -- reads this row rather than the platform one.
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
        -- Unconditional. 0012 only ever moved this toward 'active', which is a
        -- widening guard written backwards.
        SET state = EXCLUDED.state, updated_at = statement_timestamp();

    INSERT INTO medawarcre.oauth_clients (client_id, name, redirect_uris, scopes)
    VALUES (source_session.client_id, source_session.client_id,
            ARRAY['https://projected.invalid/callback'],
            ARRAY['mcp:tools'])
    ON CONFLICT (client_id) DO NOTHING;

    session_access := sha256(convert_to('projected-access/' || p_session_id::text, 'UTF8'));
    session_refresh := sha256(convert_to('projected-refresh/' || p_session_id::text, 'UTF8'));
    refresh_at := greatest(
        (source_session.access_expires_at)::timestamptz,
        statement_timestamp() + interval '1 minute'
    );

    INSERT INTO medawarcre.oauth_sessions (
        id, workspace_id, user_id, client_id, scopes, audience, resource,
        authority_version, access_hash, refresh_hash, access_expires_at,
        refresh_expires_at, refresh_family_expires_at, revoked_at
    )
    VALUES (
        p_session_id, p_workspace_id, p_user_id, source_session.client_id,
        ARRAY['mcp:tools'], p_audience, p_resource, 1,
        session_access, session_refresh,
        (source_session.access_expires_at)::timestamptz, refresh_at, refresh_at,
        (source_session.revoked_at)::timestamptz
    )
    ON CONFLICT (id) DO UPDATE SET
        audience = EXCLUDED.audience,
        resource = EXCLUDED.resource,
        access_expires_at = EXCLUDED.access_expires_at,
        refresh_expires_at = EXCLUDED.refresh_expires_at,
        refresh_family_expires_at = EXCLUDED.refresh_family_expires_at,
        -- Copied, not cleared. 0012 set this to NULL unconditionally, which
        -- un-revoked a revoked session on every request.
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
        SELECT plan.daily_quotas::jsonb INTO source_quotas
          FROM medawarcre.platform_plans plan
         WHERE plan.key = source_grant.plan_key;

        IF source_grant.plan_key IS NOT NULL THEN
            INSERT INTO medawarcre.plans (plan_key, name, daily_quotas)
            VALUES (source_grant.plan_key, initcap(source_grant.plan_key),
                    COALESCE(source_quotas, '{}'::jsonb))
            ON CONFLICT (plan_key) DO UPDATE
                -- Read from platform_plans, which is the same global row the
                -- platform authority reads. 0012 wrote it from a caller-supplied
                -- quota map, and plans are global — one workspace rewrote the
                -- quotas every other tenant on that plan_key is admitted against.
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

    -- Scoped to this projection's own rows. 0012 revoked every other grant for
    -- the subject regardless of source, which would silently revoke a jv,
    -- promotion or stripe grant written through the certified path.
    UPDATE medawarcre.access_grants
       SET status = 'revoked',
           ends_at = statement_timestamp(),
           updated_at = statement_timestamp()
     WHERE workspace_id = p_workspace_id
       AND subject_user_id = p_user_id
       AND source = 'manual'
       AND external_ref_hash <> grant_ref
       AND status <> 'revoked';

    -- Territories, deduplicated and ordered exactly as AuthorityResolver does
    -- it: COALESCE(state, market, name), grouped by value, ordered by the
    -- lowest platform row id. The certified id carries that index in its first
    -- four bytes, because atomic_admit_tool_call rebuilds the array ordered by
    -- `min(territory.id::text)` and compares it to the context's order.
    DELETE FROM medawarcre.territories
     WHERE workspace_id = p_workspace_id
       AND name NOT IN (
           SELECT btrim(COALESCE(territory.state, territory.market, territory.name))
             FROM medawarcre.platform_territories territory
            WHERE territory.workspace_id = source_workspace_id
              AND length(btrim(COALESCE(territory.state, territory.market,
                                        territory.name))) > 0
       );

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
            SELECT btrim(COALESCE(territory.state, territory.market,
                                  territory.name)) AS value,
                   min(territory.id) AS first_id
              FROM medawarcre.platform_territories territory
             WHERE territory.workspace_id = source_workspace_id
               AND length(btrim(COALESCE(territory.state, territory.market,
                                         territory.name))) > 0
             GROUP BY btrim(COALESCE(territory.state, territory.market,
                                     territory.name))
          ) grouped
      ) ordered
    ON CONFLICT (workspace_id, name) DO NOTHING;
END
$function$;

REVOKE ALL ON FUNCTION medawarcre.project_platform_authority(
    uuid, text, uuid, bigint, uuid, text, text, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION medawarcre.project_platform_authority(
    uuid, text, uuid, bigint, uuid, text, text, text
) TO medawarcre_admission, medawarcre_admin;


-- The privilege-escalation vector the same review confirmed: medawarcre_app,
-- the customer-serving role, could write itself a platform_internal_admins row
-- and become the exact identity AdminControlStore._mutate checks before
-- permitting workspace, grant and territory mutation.
--
-- The rest of the platform grants stay as they are. Those stores need
-- read/write on their own tables, which is what the SQLite file gave them, and
-- narrowing that is a real phase rather than a line. This one is different: no
-- store writes this table on a request path, so revoking write costs nothing
-- and closes the escalation.
REVOKE INSERT, UPDATE, DELETE ON medawarcre.platform_internal_admins
    FROM medawarcre_app;
