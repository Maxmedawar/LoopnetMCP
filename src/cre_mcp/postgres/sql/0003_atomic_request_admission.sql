ALTER TABLE medawarcre.access_decision_audit
    ADD COLUMN args_hash bytea,
    ADD COLUMN admission_binding_hash bytea,
    ADD CONSTRAINT access_decision_args_hash_valid
        CHECK (args_hash IS NULL OR octet_length(args_hash) = 32),
    ADD CONSTRAINT access_decision_binding_hash_valid
        CHECK (
            admission_binding_hash IS NULL
            OR octet_length(admission_binding_hash) = 32
        );

REVOKE EXECUTE ON FUNCTION medawarcre.consume_tool_approval(
    bytea, uuid, uuid, bytea, text, bytea
) FROM medawarcre_admission;
REVOKE EXECUTE ON FUNCTION medawarcre.consume_daily_quota(
    uuid, text, bigint, bigint
) FROM medawarcre_admission;
REVOKE EXECUTE ON FUNCTION medawarcre.record_access_decision(
    uuid, text, boolean, uuid, uuid, bytea, uuid, text, text, text, text
) FROM medawarcre_admission;

CREATE FUNCTION medawarcre.atomic_admit_tool_call(
    p_invocation_id uuid,
    p_request_correlation_id uuid,
    p_workspace_public_id text,
    p_actor_user_id uuid,
    p_session_id uuid,
    p_expected_audience text,
    p_expected_resource text,
    p_expected_profile text,
    p_expected_plan_key text,
    p_expected_territories text[],
    p_tool_name text,
    p_args_hash bytea,
    p_quota_bucket text,
    p_requires_approval boolean,
    p_approval_token_hash bytea
)
RETURNS TABLE (
    decision text,
    reason_code text,
    safe_reason text,
    approval_request_id uuid,
    quota_used bigint,
    replayed boolean,
    finalized boolean
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    v_workspace_id uuid;
    v_profile text;
    v_plan_key text;
    v_daily_quotas jsonb;
    v_territories text[];
    v_authority_reason text;
    v_session_hash bytea := pg_catalog.sha256(
        pg_catalog.convert_to(p_session_id::text, 'UTF8')
    );
    v_binding_hash bytea := pg_catalog.sha256(
        pg_catalog.convert_to(
            pg_catalog.jsonb_build_array(
                p_request_correlation_id,
                p_workspace_public_id,
                p_actor_user_id,
                p_session_id,
                p_expected_audience,
                p_expected_resource,
                p_expected_profile,
                p_expected_plan_key,
                p_expected_territories,
                p_tool_name,
                p_args_hash,
                p_quota_bucket,
                p_requires_approval,
                p_approval_token_hash
            )::text,
            'UTF8'
        )
    );
    v_authenticated boolean := false;
    v_approval_id uuid;
    v_quota_limit bigint;
    v_quota_value jsonb;
    v_existing record;
BEGIN
    SELECT audit.decision,
           audit.reason_code,
           audit.safe_reason,
           EXISTS (
               SELECT 1
               FROM medawarcre.access_decision_audit final
               WHERE final.invocation_id = audit.invocation_id
                 AND final.phase = 'final'
           ) AS finalized
      INTO v_existing
      FROM medawarcre.access_decision_audit audit
     WHERE audit.invocation_id = p_invocation_id
       AND audit.phase = 'admission'
       AND audit.admission_binding_hash = v_binding_hash;
    IF FOUND THEN
        decision := v_existing.decision;
        reason_code := v_existing.reason_code;
        safe_reason := v_existing.safe_reason;
        approval_request_id := CASE
            WHEN reason_code = 'approval_required' THEN p_invocation_id
            ELSE NULL
        END;
        quota_used := NULL;
        replayed := true;
        finalized := v_existing.finalized;
        RETURN NEXT;
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM medawarcre.access_decision_audit audit
        WHERE audit.invocation_id = p_invocation_id
          AND audit.phase = 'admission'
    ) THEN
        RETURN;
    END IF;

    WITH credential AS (
        SELECT oauth_session.workspace_id,
               workspace.state AS workspace_state,
               user_record.state AS user_state,
               membership.state AS membership_state,
               account.state AS account_state
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
        WHERE oauth_session.id = p_session_id
          AND workspace.public_id = p_workspace_public_id
          AND oauth_session.user_id = p_actor_user_id
          AND oauth_client.active
          AND oauth_session.revoked_at IS NULL
          AND oauth_session.authority_version = 1
          AND oauth_session.access_expires_at > statement_timestamp()
          AND oauth_session.audience = p_expected_audience
          AND oauth_session.resource = p_expected_resource
    ),
    selected_grant AS (
        SELECT access_grant.profile,
               access_grant.plan_key
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
                  AND access_grant.subject_user_id = p_actor_user_id
              )
          )
        ORDER BY CASE access_grant.profile
                     WHEN 'full_operator' THEN 4
                     WHEN 'national_scout' THEN 3
                     WHEN 'local_scout' THEN 2
                     WHEN 'jv_partner' THEN 1
                     ELSE 0
                 END DESC,
                 access_grant.updated_at DESC,
                 access_grant.id DESC
        LIMIT 1
    ),
    selected_plan AS (
        SELECT plan.plan_key,
               plan.daily_quotas,
               plan.active,
               NOT EXISTS (
                   SELECT 1
                   FROM pg_catalog.jsonb_each(plan.daily_quotas) quota
                   WHERE quota.key !~ '^[a-z][a-z0-9_]{0,63}$'
                      OR NOT CASE
                          WHEN pg_catalog.jsonb_typeof(quota.value) = 'number'
                           AND quota.value::text ~ '^(0|[1-9][0-9]*)$'
                          THEN quota.value::text::numeric
                               <= 9223372036854775807::numeric
                          ELSE false
                      END
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
    )
    SELECT credential.workspace_id,
           selected_grant.profile,
           selected_grant.plan_key,
           CASE WHEN selected_plan.plan_key IS NOT NULL
                     AND selected_plan.active
                     AND selected_plan.quotas_valid
                THEN selected_plan.daily_quotas
                ELSE NULL
           END,
           COALESCE(territory_summary.territories, ARRAY[]::text[]),
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
               WHEN selected_grant.profile IS NULL
                   THEN 'entitlement_missing_or_expired'
               WHEN selected_grant.plan_key IS NULL
                    OR selected_plan.plan_key IS NULL
                    OR NOT selected_plan.active
                    OR NOT selected_plan.quotas_valid
                   THEN 'plan_missing_or_invalid'
               ELSE NULL
           END
      INTO v_workspace_id,
           v_profile,
           v_plan_key,
           v_daily_quotas,
           v_territories,
           v_authority_reason
      FROM credential
      LEFT JOIN selected_grant ON true
      LEFT JOIN selected_plan ON true
      LEFT JOIN territory_summary ON true;

    v_authenticated := FOUND;
    decision := 'denied';
    approval_request_id := NULL;
    quota_used := NULL;
    replayed := false;
    finalized := false;

    IF NOT v_authenticated THEN
        reason_code := 'authority_missing';
        safe_reason := 'access denied: live session authority is unavailable';
    ELSIF p_invocation_id IS NULL
       OR p_request_correlation_id IS NULL
       OR length(btrim(COALESCE(p_tool_name, ''))) = 0
       OR length(btrim(COALESCE(p_expected_audience, ''))) = 0
       OR length(btrim(COALESCE(p_expected_resource, ''))) = 0
       OR octet_length(p_args_hash) IS DISTINCT FROM 32
       OR length(btrim(COALESCE(p_expected_profile, ''))) = 0
       OR length(btrim(COALESCE(p_expected_plan_key, ''))) = 0
       OR p_expected_territories IS NULL
       OR array_position(p_expected_territories, NULL) IS NOT NULL
       OR (p_quota_bucket IS NOT NULL
           AND p_quota_bucket !~ '^[a-z][a-z0-9_]{0,63}$')
       OR (p_approval_token_hash IS NOT NULL
           AND octet_length(p_approval_token_hash) <> 32)
       OR p_requires_approval IS NULL
       OR (NOT p_requires_approval AND p_approval_token_hash IS NOT NULL)
    THEN
        reason_code := 'request_binding_invalid';
        safe_reason := 'access denied: request binding is invalid';
    ELSIF v_authority_reason IS NOT NULL THEN
        reason_code := v_authority_reason;
        safe_reason := 'access denied: live authority is inactive';
    ELSIF v_profile IS DISTINCT FROM p_expected_profile
       OR v_plan_key IS DISTINCT FROM p_expected_plan_key
       OR v_territories IS DISTINCT FROM p_expected_territories
    THEN
        reason_code := 'authority_changed';
        safe_reason := 'access denied: live authority changed; authenticate again';
    ELSIF p_requires_approval AND p_approval_token_hash IS NULL THEN
        reason_code := 'approval_required';
        safe_reason := 'sensitive action requires operator approval';
        approval_request_id := p_invocation_id;
    ELSE
        IF p_requires_approval THEN
            SELECT approval.id
              INTO v_approval_id
              FROM medawarcre.tool_approvals approval
             WHERE approval.approval_token_hash = p_approval_token_hash
               AND approval.workspace_id = v_workspace_id
               AND approval.subject_user_id = p_actor_user_id
               AND approval.session_hash = v_session_hash
               AND approval.tool_name = p_tool_name
               AND approval.args_hash = p_args_hash
               AND approval.consumed_at IS NULL
               AND approval.revoked_at IS NULL
               AND approval.expires_at > statement_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                reason_code := 'approval_invalid';
                safe_reason := 'access denied: approval is unavailable or does not match';
            END IF;
        END IF;

        IF reason_code IS NULL AND p_quota_bucket IS NOT NULL THEN
            v_quota_value := v_daily_quotas -> p_quota_bucket;
            IF v_quota_value IS NOT NULL THEN
                v_quota_limit := v_quota_value::text::bigint;
            END IF;
            INSERT INTO medawarcre.daily_quota_usage(
                workspace_id, bucket, usage_date, used_count, updated_at
            )
            SELECT v_workspace_id,
                   p_quota_bucket,
                   (statement_timestamp() AT TIME ZONE 'UTC')::date,
                   1,
                   statement_timestamp()
             WHERE v_quota_limit IS NULL OR v_quota_limit >= 1
            ON CONFLICT (workspace_id, bucket, usage_date)
            DO UPDATE
               SET used_count = medawarcre.daily_quota_usage.used_count + 1,
                   updated_at = statement_timestamp()
             WHERE v_quota_limit IS NULL
                OR medawarcre.daily_quota_usage.used_count + 1 <= v_quota_limit
            RETURNING used_count INTO quota_used;
            IF NOT FOUND
               OR (v_quota_limit IS NOT NULL AND quota_used > v_quota_limit)
            THEN
                reason_code := 'quota_exceeded';
                safe_reason := 'access denied: daily quota exceeded';
                quota_used := NULL;
            END IF;
        END IF;

        IF reason_code IS NULL AND p_requires_approval THEN
            UPDATE medawarcre.tool_approvals approval
               SET consumed_at = statement_timestamp()
             WHERE approval.id = v_approval_id
               AND approval.consumed_at IS NULL;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING
                    ERRCODE = 'object_not_in_prerequisite_state',
                    MESSAGE = 'approval state changed during admission';
            END IF;
        END IF;

        IF reason_code IS NULL THEN
            decision := 'allowed';
            reason_code := 'authority_admitted';
            safe_reason := 'request admitted by live authority';
        END IF;
    END IF;

    INSERT INTO medawarcre.access_decision_audit(
        invocation_id,
        phase,
        authenticated,
        workspace_id,
        actor_user_id,
        session_correlation_hash,
        request_correlation_id,
        tool_name,
        decision,
        reason_code,
        safe_reason,
        args_hash,
        admission_binding_hash,
        occurred_at
    )
    VALUES (
        p_invocation_id,
        'admission',
        v_authenticated,
        CASE WHEN v_authenticated THEN v_workspace_id ELSE NULL END,
        CASE WHEN v_authenticated THEN p_actor_user_id ELSE NULL END,
        v_session_hash,
        p_request_correlation_id,
        p_tool_name,
        decision,
        reason_code,
        safe_reason,
        p_args_hash,
        v_binding_hash,
        statement_timestamp()
    );
    RETURN NEXT;
END
$function$;

REVOKE ALL ON FUNCTION medawarcre.atomic_admit_tool_call(
    uuid, uuid, text, uuid, uuid, text, text, text, text, text[], text,
    bytea, text, boolean, bytea
) FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
       medawarcre_admission, medawarcre_oauth,
       medawarcre_provider_ingress, medawarcre_provider_reconcile,
       medawarcre_worker, medawarcre_scheduler;

CREATE FUNCTION medawarcre.record_tool_call_final(
    p_invocation_id uuid,
    p_request_correlation_id uuid,
    p_workspace_public_id text,
    p_actor_user_id uuid,
    p_session_id uuid,
    p_tool_name text,
    p_succeeded boolean,
    p_reason_code text,
    p_safe_reason text
)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    v_id uuid;
    v_workspace_id uuid;
    v_session_hash bytea := pg_catalog.sha256(
        pg_catalog.convert_to(p_session_id::text, 'UTF8')
    );
    v_decision text := CASE WHEN p_succeeded THEN 'succeeded' ELSE 'failed' END;
BEGIN
    SELECT workspace.id
      INTO v_workspace_id
      FROM medawarcre.workspaces workspace
     WHERE workspace.public_id = p_workspace_public_id;
    IF NOT FOUND
       OR p_invocation_id IS NULL
       OR p_request_correlation_id IS NULL
       OR p_succeeded IS NULL
       OR length(btrim(COALESCE(p_tool_name, ''))) = 0
       OR length(btrim(COALESCE(p_reason_code, ''))) = 0
       OR length(btrim(COALESCE(p_safe_reason, ''))) = 0
    THEN
        RETURN NULL;
    END IF;

    INSERT INTO medawarcre.access_decision_audit(
        invocation_id, phase, authenticated, workspace_id, actor_user_id,
        session_correlation_hash, request_correlation_id, tool_name, decision,
        reason_code, safe_reason, occurred_at
    )
    SELECT p_invocation_id, 'final', true, v_workspace_id, p_actor_user_id,
           v_session_hash, p_request_correlation_id, p_tool_name, v_decision,
           p_reason_code, p_safe_reason, statement_timestamp()
     WHERE EXISTS (
        SELECT 1
        FROM medawarcre.access_decision_audit admission
        WHERE admission.invocation_id = p_invocation_id
          AND admission.phase = 'admission'
          AND admission.decision = 'allowed'
          AND admission.authenticated
          AND admission.workspace_id = v_workspace_id
          AND admission.actor_user_id = p_actor_user_id
          AND admission.session_correlation_hash = v_session_hash
          AND admission.request_correlation_id = p_request_correlation_id
          AND admission.tool_name = p_tool_name
    )
    ON CONFLICT (invocation_id, phase) DO NOTHING
    RETURNING id INTO v_id;
    IF v_id IS NOT NULL THEN
        RETURN v_id;
    END IF;
    SELECT final.id
      INTO v_id
      FROM medawarcre.access_decision_audit final
     WHERE final.invocation_id = p_invocation_id
       AND final.phase = 'final'
       AND final.decision = v_decision
       AND final.authenticated
       AND final.workspace_id = v_workspace_id
       AND final.actor_user_id = p_actor_user_id
       AND final.session_correlation_hash = v_session_hash
       AND final.request_correlation_id = p_request_correlation_id
       AND final.tool_name = p_tool_name
       AND final.reason_code = p_reason_code
       AND final.safe_reason = p_safe_reason;
    RETURN v_id;
END
$function$;

REVOKE ALL ON FUNCTION medawarcre.record_tool_call_final(
    uuid, uuid, text, uuid, uuid, text, boolean, text, text
) FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
       medawarcre_admission, medawarcre_oauth,
       medawarcre_provider_ingress, medawarcre_provider_reconcile,
       medawarcre_worker, medawarcre_scheduler;

GRANT EXECUTE ON FUNCTION medawarcre.atomic_admit_tool_call(
    uuid, uuid, text, uuid, uuid, text, text, text, text, text[], text,
    bytea, text, boolean, bytea
) TO medawarcre_admission;
GRANT EXECUTE ON FUNCTION medawarcre.record_tool_call_final(
    uuid, uuid, text, uuid, uuid, text, boolean, text, text
) TO medawarcre_admission;
