CREATE FUNCTION medawarcre.current_oauth_session_id()
RETURNS uuid
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $function$
BEGIN
    RETURN NULLIF(current_setting('app.oauth_session_id', true), '')::uuid;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
END
$function$;

REVOKE ALL ON FUNCTION medawarcre.current_oauth_session_id()
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth,
     medawarcre_provider_ingress, medawarcre_provider_reconcile,
     medawarcre_worker, medawarcre_scheduler;
GRANT EXECUTE ON FUNCTION medawarcre.current_oauth_session_id()
TO medawarcre_app;

ALTER TABLE medawarcre.oauth_sessions
    ADD CONSTRAINT oauth_sessions_workspace_id_id_user_id_key
    UNIQUE (workspace_id, id, user_id);

CREATE TABLE medawarcre.source_document_attestations (
    attestation_id text PRIMARY KEY,
    workspace_id uuid NOT NULL,
    actor_user_id uuid NOT NULL,
    oauth_session_id uuid NOT NULL,
    url_hash bytea NOT NULL,
    evidence_url text NOT NULL,
    evidence_hash bytea NOT NULL,
    allowed_purposes text[] NOT NULL,
    approved_by uuid NOT NULL REFERENCES medawarcre.users(id),
    approved_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    FOREIGN KEY (workspace_id, actor_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, oauth_session_id, actor_user_id)
        REFERENCES medawarcre.oauth_sessions(workspace_id, id, user_id)
        ON DELETE CASCADE,
    CHECK (attestation_id ~ '^srcatt_[0-9a-f]{32}$'),
    CHECK (octet_length(url_hash) = 32),
    CHECK (octet_length(evidence_hash) = 32),
    CHECK (evidence_url ~ '^https://[^/@[:space:]]+(:[0-9]+)?(/|$)'),
    CHECK (array_ndims(allowed_purposes) = 1),
    CHECK (array_position(allowed_purposes, NULL) IS NULL),
    CHECK (cardinality(allowed_purposes) BETWEEN 1 AND 4),
    CHECK (allowed_purposes <@ ARRAY['retrieve','store','derive','output']::text[]),
    CHECK (
        cardinality(allowed_purposes) =
        (CASE WHEN array_position(allowed_purposes, 'retrieve') IS NULL THEN 0 ELSE 1 END) +
        (CASE WHEN array_position(allowed_purposes, 'store') IS NULL THEN 0 ELSE 1 END) +
        (CASE WHEN array_position(allowed_purposes, 'derive') IS NULL THEN 0 ELSE 1 END) +
        (CASE WHEN array_position(allowed_purposes, 'output') IS NULL THEN 0 ELSE 1 END)
    ),
    CHECK (expires_at > approved_at),
    CHECK (revoked_at IS NULL OR revoked_at >= approved_at)
);
CREATE INDEX source_document_attestations_scope_idx
    ON medawarcre.source_document_attestations (
        workspace_id, actor_user_id, oauth_session_id, expires_at
    );

ALTER TABLE medawarcre.source_document_attestations ENABLE ROW LEVEL SECURITY;
CREATE POLICY app_bound_document_attestations
    ON medawarcre.source_document_attestations
    FOR SELECT TO medawarcre_app
    USING (
        workspace_id = medawarcre.current_workspace_id()
        AND actor_user_id = medawarcre.current_actor_user_id()
        AND oauth_session_id = medawarcre.current_oauth_session_id()
    );
CREATE POLICY internal_read
    ON medawarcre.source_document_attestations
    FOR SELECT TO medawarcre_admin
    USING (medawarcre.internal_authorized());

REVOKE ALL ON medawarcre.source_document_attestations
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth,
     medawarcre_provider_ingress, medawarcre_provider_reconcile,
     medawarcre_worker, medawarcre_scheduler;
GRANT SELECT ON medawarcre.source_document_attestations
TO medawarcre_app, medawarcre_admin, medawarcre_backup;

CREATE OR REPLACE FUNCTION medawarcre.bind_admitted_request(
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
    PERFORM pg_catalog.set_config(
        'app.oauth_session_id', p_session_id::text, true
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
