CREATE FUNCTION medawarcre.bind_admitted_request(
    p_invocation_id uuid,
    p_request_correlation_id uuid,
    p_workspace_public_id text,
    p_actor_user_id uuid,
    p_session_id uuid,
    p_tool_name text
)
RETURNS TABLE (
    bound_workspace_id uuid,
    bound_actor_user_id uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    v_workspace_id uuid;
    v_session_hash bytea := pg_catalog.sha256(
        pg_catalog.convert_to(p_session_id::text, 'UTF8')
    );
BEGIN
    IF p_invocation_id IS NULL
       OR p_request_correlation_id IS NULL
       OR p_actor_user_id IS NULL
       OR p_session_id IS NULL
       OR length(btrim(COALESCE(p_workspace_public_id, ''))) = 0
       OR length(btrim(COALESCE(p_tool_name, ''))) = 0
    THEN
        RETURN;
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(p_invocation_id::text, 708905167)
    );

    SELECT admission.workspace_id
      INTO v_workspace_id
      FROM medawarcre.access_decision_audit admission
      JOIN medawarcre.workspaces workspace
        ON workspace.id = admission.workspace_id
     WHERE admission.invocation_id = p_invocation_id
       AND admission.phase = 'admission'
       AND admission.authenticated
       AND admission.decision = 'allowed'
       AND admission.reason_code = 'authority_admitted'
       AND admission.args_hash IS NOT NULL
       AND admission.admission_binding_hash IS NOT NULL
       AND admission.request_correlation_id = p_request_correlation_id
       AND workspace.public_id = p_workspace_public_id
       AND admission.actor_user_id = p_actor_user_id
       AND admission.session_correlation_hash = v_session_hash
       AND admission.tool_name = p_tool_name
       AND NOT EXISTS (
           SELECT 1
             FROM medawarcre.access_decision_audit final
            WHERE final.invocation_id = admission.invocation_id
              AND final.phase = 'final'
       );
    IF NOT FOUND THEN
        RETURN;
    END IF;

    PERFORM pg_catalog.set_config(
        'app.workspace_id', v_workspace_id::text, true
    );
    PERFORM pg_catalog.set_config(
        'app.actor_user_id', p_actor_user_id::text, true
    );
    PERFORM pg_catalog.set_config('app.internal_role', '', true);
    PERFORM pg_catalog.set_config('app.audit_reason', '', true);

    RETURN QUERY SELECT v_workspace_id, p_actor_user_id;
END
$function$;

REVOKE ALL ON FUNCTION medawarcre.bind_admitted_request(
    uuid, uuid, text, uuid, uuid, text
) FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
       medawarcre_admission, medawarcre_oauth,
       medawarcre_provider_ingress, medawarcre_provider_reconcile,
       medawarcre_worker, medawarcre_scheduler;

GRANT EXECUTE ON FUNCTION medawarcre.bind_admitted_request(
    uuid, uuid, text, uuid, uuid, text
) TO medawarcre_app;

CREATE OR REPLACE FUNCTION medawarcre.record_tool_call_final(
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
    IF p_invocation_id IS NULL
       OR p_request_correlation_id IS NULL
       OR p_actor_user_id IS NULL
       OR p_session_id IS NULL
       OR length(btrim(COALESCE(p_workspace_public_id, ''))) = 0
       OR length(btrim(COALESCE(p_tool_name, ''))) = 0
       OR p_succeeded IS NULL
       OR length(btrim(COALESCE(p_reason_code, ''))) = 0
       OR length(btrim(COALESCE(p_safe_reason, ''))) = 0
    THEN
        RETURN NULL;
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(p_invocation_id::text, 708905167)
    );

    SELECT workspace.id
      INTO v_workspace_id
      FROM medawarcre.workspaces workspace
     WHERE workspace.public_id = p_workspace_public_id;
    IF NOT FOUND THEN
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
