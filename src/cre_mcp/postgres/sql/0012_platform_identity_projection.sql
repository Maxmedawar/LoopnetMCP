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
