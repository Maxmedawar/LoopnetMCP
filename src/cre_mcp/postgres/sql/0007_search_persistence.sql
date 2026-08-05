ALTER TABLE medawarcre.saved_searches
    DROP CONSTRAINT saved_searches_workspace_id_name_key;

ALTER TABLE medawarcre.saved_searches
    ADD CONSTRAINT saved_searches_workspace_owner_name_key
        UNIQUE (workspace_id, owner_user_id, name),
    ADD CONSTRAINT saved_searches_workspace_id_owner_key
        UNIQUE (workspace_id, id, owner_user_id),
    ADD CONSTRAINT saved_searches_name_check CHECK (
        length(name) BETWEEN 1 AND 200
        AND name = btrim(name)
    ),
    ADD CONSTRAINT saved_searches_min_score_check CHECK (
        min_score IS NULL
        OR (
            min_score BETWEEN 0 AND 100
            AND min_score::text NOT IN ('NaN', 'Infinity', '-Infinity')
        )
    );

DROP POLICY app_owned_saved_searches ON medawarcre.saved_searches;
CREATE POLICY app_owned_saved_searches_select
    ON medawarcre.saved_searches
    FOR SELECT TO medawarcre_app
    USING (
        workspace_id = medawarcre.current_workspace_id()
        AND owner_user_id = medawarcre.current_actor_user_id()
    );
CREATE POLICY app_owned_saved_searches_insert
    ON medawarcre.saved_searches
    FOR INSERT TO medawarcre_app
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND owner_user_id = medawarcre.current_actor_user_id()
    );

REVOKE UPDATE, DELETE ON medawarcre.saved_searches FROM medawarcre_app;

CREATE TABLE medawarcre.saved_search_seen_matches (
    workspace_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    saved_search_id uuid NOT NULL,
    dedupe_key text NOT NULL,
    first_seen timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (workspace_id, saved_search_id, dedupe_key),
    FOREIGN KEY (workspace_id, saved_search_id, owner_user_id)
        REFERENCES medawarcre.saved_searches(workspace_id, id, owner_user_id)
        ON DELETE CASCADE,
    CHECK (
        length(dedupe_key) BETWEEN 1 AND 512
        AND dedupe_key = btrim(dedupe_key)
    )
);

ALTER TABLE medawarcre.saved_search_seen_matches ENABLE ROW LEVEL SECURITY;

CREATE POLICY app_owned_saved_search_seen_matches_select
    ON medawarcre.saved_search_seen_matches
    FOR SELECT TO medawarcre_app
    USING (
        workspace_id = medawarcre.current_workspace_id()
        AND owner_user_id = medawarcre.current_actor_user_id()
    );

CREATE POLICY app_owned_saved_search_seen_matches_insert
    ON medawarcre.saved_search_seen_matches
    FOR INSERT TO medawarcre_app
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND owner_user_id = medawarcre.current_actor_user_id()
    );

CREATE POLICY internal_read
    ON medawarcre.saved_search_seen_matches
    FOR SELECT TO medawarcre_admin
    USING (medawarcre.internal_authorized());

CREATE POLICY internal_manage
    ON medawarcre.saved_search_seen_matches
    FOR ALL TO medawarcre_admin
    USING (medawarcre.internal_can_mutate())
    WITH CHECK (medawarcre.internal_can_mutate());

REVOKE ALL ON medawarcre.saved_search_seen_matches
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth,
     medawarcre_provider_ingress, medawarcre_provider_reconcile,
     medawarcre_worker, medawarcre_scheduler;

GRANT SELECT, INSERT ON medawarcre.saved_search_seen_matches
TO medawarcre_app;
GRANT SELECT, INSERT, UPDATE, DELETE
ON medawarcre.saved_search_seen_matches TO medawarcre_admin;
GRANT SELECT ON medawarcre.saved_search_seen_matches
TO medawarcre_backup;
