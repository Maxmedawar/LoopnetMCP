-- Bring every pre-existing listing up to the identity and shape the hosted
-- reader validates. A row stored before this migration may hold only the
-- '{}' default, and one row the reader cannot decode would otherwise deny the
-- whole workspace's deal list. Absent required fields are filled with the
-- authoritative column value or an empty string; no location is invented, so
-- such a deal stays outside every territory and is withheld from
-- territory-limited profiles rather than released.
UPDATE medawarcre.deals
SET listing = listing
    || jsonb_build_object('source', source, 'source_id', source_record_id)
    || CASE WHEN listing ? 'name' AND jsonb_typeof(listing->'name') = 'string'
            THEN '{}'::jsonb
            ELSE jsonb_build_object('name', COALESCE(title, 'Untitled listing')) END
    || CASE WHEN listing ? 'address' AND jsonb_typeof(listing->'address') = 'string'
            THEN '{}'::jsonb ELSE jsonb_build_object('address', '') END
    || CASE WHEN listing ? 'city' AND jsonb_typeof(listing->'city') = 'string'
            THEN '{}'::jsonb ELSE jsonb_build_object('city', '') END
    || CASE WHEN listing ? 'state' AND jsonb_typeof(listing->'state') = 'string'
            THEN '{}'::jsonb ELSE jsonb_build_object('state', '') END
    || CASE WHEN listing ? 'url' AND jsonb_typeof(listing->'url') = 'string'
            THEN '{}'::jsonb ELSE jsonb_build_object('url', '') END
WHERE jsonb_typeof(listing) = 'object';

ALTER TABLE medawarcre.deals
    ADD COLUMN accountability_owner text,
    ADD COLUMN created_by_user_id uuid,
    ADD COLUMN updated_by_user_id uuid,
    ADD COLUMN source_rights_id text,
    ADD COLUMN source_rights_verified_on date,
    ADD CONSTRAINT deals_created_by_membership_fkey
        FOREIGN KEY (workspace_id, created_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT deals_updated_by_membership_fkey
        FOREIGN KEY (workspace_id, updated_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT deals_source_text_check CHECK (
        length(source) BETWEEN 1 AND 64 AND source = btrim(source)
    ),
    ADD CONSTRAINT deals_source_record_text_check CHECK (
        length(source_record_id) BETWEEN 1 AND 512
        AND source_record_id = btrim(source_record_id)
    ),
    ADD CONSTRAINT deals_title_text_check CHECK (
        length(title) BETWEEN 1 AND 500 AND title = btrim(title)
    ),
    ADD CONSTRAINT deals_listing_size_check CHECK (
        octet_length(listing::text) <= 262144
    ),
    ADD CONSTRAINT deals_listing_identity_check CHECK (
        listing->>'source' = source
        AND listing->>'source_id' = source_record_id
    ),
    ADD CONSTRAINT deals_asking_price_finite_check CHECK (
        asking_price IS NULL OR (
            asking_price > 0
            AND asking_price::text NOT IN ('NaN', 'Infinity', '-Infinity')
        )
    ),
    ADD CONSTRAINT deals_score_finite_check CHECK (
        score IS NULL OR (
            score BETWEEN 0 AND 100
            AND score::text NOT IN ('NaN', 'Infinity', '-Infinity')
        )
    ),
    ADD CONSTRAINT deals_accountability_owner_check CHECK (
        accountability_owner IS NULL OR (
            length(accountability_owner) BETWEEN 1 AND 200
            AND accountability_owner = btrim(accountability_owner)
        )
    ),
    ADD CONSTRAINT deals_next_action_check CHECK (
        next_action IS NULL OR (
            length(next_action) BETWEEN 1 AND 1000
            AND next_action = btrim(next_action)
        )
    ),
    ADD CONSTRAINT deals_score_version_check CHECK (
        score_version IS NULL OR (
            length(score_version) BETWEEN 1 AND 64
            AND score_version = btrim(score_version)
        )
    ),
    ADD CONSTRAINT deals_grade_check CHECK (
        grade IS NULL OR (
            length(grade) BETWEEN 1 AND 64 AND grade = btrim(grade)
        )
    ),
    ADD CONSTRAINT deals_strategy_check CHECK (
        strategy IS NULL OR (
            length(strategy) BETWEEN 1 AND 128 AND strategy = btrim(strategy)
        )
    ),
    ADD CONSTRAINT deals_source_rights_id_check CHECK (
        source_rights_id IS NULL OR (
            length(source_rights_id) BETWEEN 1 AND 128
            AND source_rights_id = btrim(source_rights_id)
        )
    ),
    ADD CONSTRAINT deals_source_rights_evidence_check CHECK (
        (source_rights_id IS NULL) = (source_rights_verified_on IS NULL)
    );

ALTER TABLE medawarcre.deals
    ALTER CONSTRAINT deals_workspace_id_owner_user_id_fkey
        DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE medawarcre.deal_notes
    ALTER CONSTRAINT deal_notes_workspace_id_author_user_id_fkey
        DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE medawarcre.deal_notes
    ADD COLUMN stage text NOT NULL DEFAULT 'lead'
        CHECK (stage IN ('lead', 'analyzing', 'contacted', 'loi', 'under_contract',
                         'diligence', 'closing', 'owned', 'passed')),
    ADD CONSTRAINT deal_notes_body_size_check CHECK (
        length(body) BETWEEN 1 AND 8000 AND body = btrim(body)
    );

UPDATE medawarcre.deals
SET created_by_user_id = COALESCE(created_by_user_id, owner_user_id),
    updated_by_user_id = COALESCE(updated_by_user_id, owner_user_id),
    owner_user_id = NULL
WHERE owner_user_id IS NOT NULL;

ALTER TABLE medawarcre.deal_outcomes
    ADD COLUMN predicted_score numeric(10, 4),
    ADD COLUMN predicted_grade text,
    ADD COLUMN predicted_strategy text,
    ADD COLUMN created_by_user_id uuid,
    ADD COLUMN updated_by_user_id uuid,
    ADD CONSTRAINT deal_outcomes_created_by_membership_fkey
        FOREIGN KEY (workspace_id, created_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT deal_outcomes_updated_by_membership_fkey
        FOREIGN KEY (workspace_id, updated_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT deal_outcomes_predicted_score_finite_check CHECK (
        predicted_score IS NULL OR (
            predicted_score BETWEEN 0 AND 100
            AND predicted_score::text NOT IN ('NaN', 'Infinity', '-Infinity')
        )
    ),
    ADD CONSTRAINT deal_outcomes_realized_irr_finite_check CHECK (
        realized_irr IS NULL
        OR realized_irr::text NOT IN ('NaN', 'Infinity', '-Infinity')
    ),
    ADD CONSTRAINT deal_outcomes_purchase_price_finite_check CHECK (
        purchase_price IS NULL OR (
            purchase_price > 0
            AND purchase_price::text NOT IN ('NaN', 'Infinity', '-Infinity')
        )
    ),
    ADD CONSTRAINT deal_outcomes_closed_price_check CHECK (
        NOT closed OR purchase_price IS NOT NULL
    ),
    ADD CONSTRAINT deal_outcomes_hold_years_finite_check CHECK (
        realized_hold_years IS NULL OR (
            realized_hold_years > 0
            AND realized_hold_years::text NOT IN ('NaN', 'Infinity', '-Infinity')
        )
    ),
    ADD CONSTRAINT deal_outcomes_equity_multiple_finite_check CHECK (
        realized_equity_multiple IS NULL OR (
            realized_equity_multiple >= 0
            AND realized_equity_multiple::text NOT IN ('NaN', 'Infinity', '-Infinity')
        )
    ),
    ADD CONSTRAINT deal_outcomes_notes_check CHECK (
        notes IS NULL OR (
            length(notes) BETWEEN 1 AND 8000 AND notes = btrim(notes)
        )
    ),
    ADD CONSTRAINT deal_outcomes_predicted_grade_check CHECK (
        predicted_grade IS NULL OR (
            length(predicted_grade) BETWEEN 1 AND 64
            AND predicted_grade = btrim(predicted_grade)
        )
    ),
    ADD CONSTRAINT deal_outcomes_predicted_strategy_check CHECK (
        predicted_strategy IS NULL OR (
            length(predicted_strategy) BETWEEN 1 AND 128
            AND predicted_strategy = btrim(predicted_strategy)
        )
    );

ALTER TABLE medawarcre.deal_events
    ADD COLUMN author_user_id uuid,
    ADD COLUMN request_invocation_id uuid,
    ADD CONSTRAINT deal_events_author_membership_fkey
        FOREIGN KEY (workspace_id, author_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT deal_events_type_check CHECK (
        length(event_type) BETWEEN 1 AND 128 AND event_type = btrim(event_type)
    ),
    ADD CONSTRAINT deal_events_data_size_check CHECK (
        octet_length(event_data::text) <= 65536
    );
CREATE UNIQUE INDEX deal_events_request_invocation_idx
    ON medawarcre.deal_events(workspace_id, request_invocation_id)
    WHERE request_invocation_id IS NOT NULL;

CREATE TABLE medawarcre.deal_dd_items (
    workspace_id uuid NOT NULL,
    deal_id uuid NOT NULL,
    item_key text NOT NULL,
    item_data jsonb NOT NULL,
    status text NOT NULL
        CHECK (status IN ('not_started', 'in_progress', 'blocked', 'complete', 'waived')),
    deadline date NOT NULL,
    created_by_user_id uuid NOT NULL,
    updated_by_user_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (workspace_id, deal_id, item_key),
    FOREIGN KEY (workspace_id, deal_id)
        REFERENCES medawarcre.deals(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, created_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (workspace_id, updated_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (length(item_key) BETWEEN 1 AND 128 AND item_key = btrim(item_key)),
    CHECK (jsonb_typeof(item_data) = 'object'),
    CHECK (octet_length(item_data::text) <= 65536)
);
CREATE INDEX deal_dd_items_deadline_idx
    ON medawarcre.deal_dd_items(workspace_id, deal_id, deadline, item_key);

CREATE TABLE medawarcre.deal_ops_events (
    workspace_id uuid NOT NULL,
    deal_id uuid NOT NULL,
    event_key text NOT NULL,
    event_data jsonb NOT NULL,
    category text NOT NULL
        CHECK (category IN ('month_one', 'recurring', 'lease', 'nudge')),
    event_date date,
    status text NOT NULL
        CHECK (status IN ('not_started', 'in_progress', 'complete', 'waived')),
    created_by_user_id uuid NOT NULL,
    updated_by_user_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (workspace_id, deal_id, event_key),
    FOREIGN KEY (workspace_id, deal_id)
        REFERENCES medawarcre.deals(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, created_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (workspace_id, updated_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (length(event_key) BETWEEN 1 AND 128 AND event_key = btrim(event_key)),
    CHECK (jsonb_typeof(event_data) = 'object'),
    CHECK (octet_length(event_data::text) <= 65536)
);
CREATE INDEX deal_ops_events_date_idx
    ON medawarcre.deal_ops_events(workspace_id, deal_id, event_date, event_key);

CREATE TABLE medawarcre.deal_investors (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    name text NOT NULL,
    accredited boolean,
    accreditation_verified boolean NOT NULL DEFAULT false,
    relationship text NOT NULL CHECK (relationship IN ('preexisting', 'new')),
    contact jsonb,
    created_by_user_id uuid NOT NULL,
    updated_by_user_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    FOREIGN KEY (workspace_id, created_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (workspace_id, updated_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (length(name) BETWEEN 1 AND 300 AND name = btrim(name)),
    CHECK (NOT accreditation_verified OR accredited IS TRUE),
    CHECK (contact IS NULL OR jsonb_typeof(contact) IN ('object', 'string')),
    CHECK (contact IS NULL OR octet_length(contact::text) <= 16384),
    CHECK (
        contact IS NULL OR jsonb_typeof(contact) = 'object' OR (
            length(contact #>> '{}') BETWEEN 1 AND 8000
            AND contact #>> '{}' = btrim(contact #>> '{}')
        )
    )
);

CREATE TABLE medawarcre.deal_commitments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    deal_id uuid NOT NULL,
    investor_id uuid NOT NULL,
    amount numeric(19, 2) NOT NULL,
    created_by_user_id uuid NOT NULL,
    updated_by_user_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, deal_id, investor_id),
    FOREIGN KEY (workspace_id, deal_id)
        REFERENCES medawarcre.deals(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, investor_id)
        REFERENCES medawarcre.deal_investors(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, created_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (workspace_id, updated_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (amount > 0 AND amount::text NOT IN ('NaN', 'Infinity', '-Infinity'))
);

CREATE TABLE medawarcre.deal_exchanges (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    relinquished_deal_id uuid NOT NULL,
    relinquished_close_date date NOT NULL,
    identification_deadline date NOT NULL,
    exchange_deadline date NOT NULL,
    created_by_user_id uuid NOT NULL,
    updated_by_user_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, relinquished_deal_id, relinquished_close_date),
    FOREIGN KEY (workspace_id, relinquished_deal_id)
        REFERENCES medawarcre.deals(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, created_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (workspace_id, updated_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (identification_deadline = relinquished_close_date + 45),
    CHECK (exchange_deadline = relinquished_close_date + 180)
);

CREATE TABLE medawarcre.deal_exchange_replacements (
    workspace_id uuid NOT NULL,
    exchange_id uuid NOT NULL,
    deal_id uuid NOT NULL,
    value numeric(19, 2),
    identified_at date NOT NULL,
    created_by_user_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (workspace_id, exchange_id, deal_id),
    FOREIGN KEY (workspace_id, exchange_id)
        REFERENCES medawarcre.deal_exchanges(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, deal_id)
        REFERENCES medawarcre.deals(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, created_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (
        value IS NULL OR (
            value > 0 AND value::text NOT IN ('NaN', 'Infinity', '-Infinity')
        )
    )
);

CREATE TABLE medawarcre.deal_ic_decisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    deal_id uuid NOT NULL,
    system_verdict text,
    system_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    expert_verdict text,
    expert_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    agreed boolean,
    created_by_user_id uuid NOT NULL,
    request_invocation_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, request_invocation_id),
    FOREIGN KEY (workspace_id, deal_id)
        REFERENCES medawarcre.deals(workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, created_by_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (system_verdict IS NULL OR (
        length(system_verdict) BETWEEN 1 AND 128 AND system_verdict = btrim(system_verdict)
    )),
    CHECK (expert_verdict IS NULL OR (
        length(expert_verdict) BETWEEN 1 AND 128 AND expert_verdict = btrim(expert_verdict)
    )),
    CHECK (jsonb_typeof(system_data) = 'object'),
    CHECK (jsonb_typeof(expert_data) = 'object'),
    CHECK (octet_length(system_data::text) <= 65536),
    CHECK (octet_length(expert_data::text) <= 65536),
    CHECK (agreed IS NULL OR (system_verdict IS NOT NULL AND expert_verdict IS NOT NULL))
);

ALTER TABLE medawarcre.deal_dd_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE medawarcre.deal_ops_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE medawarcre.deal_investors ENABLE ROW LEVEL SECURITY;
ALTER TABLE medawarcre.deal_commitments ENABLE ROW LEVEL SECURITY;
ALTER TABLE medawarcre.deal_exchanges ENABLE ROW LEVEL SECURITY;
ALTER TABLE medawarcre.deal_exchange_replacements ENABLE ROW LEVEL SECURITY;
ALTER TABLE medawarcre.deal_ic_decisions ENABLE ROW LEVEL SECURITY;

DROP POLICY app_owned_deals_insert ON medawarcre.deals;
DROP POLICY app_owned_deals_update ON medawarcre.deals;
DROP POLICY app_owned_deals_delete ON medawarcre.deals;
CREATE POLICY app_workspace_deals_insert ON medawarcre.deals
    FOR INSERT TO medawarcre_app
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND owner_user_id IS NULL
        AND created_by_user_id = medawarcre.current_actor_user_id()
        AND updated_by_user_id = medawarcre.current_actor_user_id()
        AND source_rights_id IS NOT NULL
        AND source_rights_verified_on IS NOT NULL
    );
CREATE POLICY app_workspace_deals_update ON medawarcre.deals
    FOR UPDATE TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id())
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND owner_user_id IS NULL
        AND updated_by_user_id = medawarcre.current_actor_user_id()
        AND source_rights_id IS NOT NULL
        AND source_rights_verified_on IS NOT NULL
    );

DO $policies$
DECLARE
    relation_name text;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'deal_dd_items', 'deal_ops_events', 'deal_investors',
        'deal_commitments', 'deal_exchanges', 'deal_exchange_replacements',
        'deal_ic_decisions'
    ] LOOP
        EXECUTE format(
            'CREATE POLICY app_workspace_select ON medawarcre.%I '
            'FOR SELECT TO medawarcre_app '
            'USING (workspace_id = medawarcre.current_workspace_id())',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY internal_read ON medawarcre.%I '
            'FOR SELECT TO medawarcre_admin '
            'USING (medawarcre.internal_authorized())',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY internal_manage ON medawarcre.%I '
            'FOR ALL TO medawarcre_admin '
            'USING (medawarcre.internal_can_mutate()) '
            'WITH CHECK (medawarcre.internal_can_mutate())',
            relation_name
        );
    END LOOP;
END
$policies$;

CREATE POLICY app_workspace_insert ON medawarcre.deal_dd_items
    FOR INSERT TO medawarcre_app
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND created_by_user_id = medawarcre.current_actor_user_id()
        AND updated_by_user_id = medawarcre.current_actor_user_id()
    );
CREATE POLICY app_workspace_update ON medawarcre.deal_dd_items
    FOR UPDATE TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id())
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND updated_by_user_id = medawarcre.current_actor_user_id()
    );
CREATE POLICY app_workspace_delete ON medawarcre.deal_dd_items
    FOR DELETE TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id());

CREATE POLICY app_workspace_insert ON medawarcre.deal_ops_events
    FOR INSERT TO medawarcre_app
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND created_by_user_id = medawarcre.current_actor_user_id()
        AND updated_by_user_id = medawarcre.current_actor_user_id()
    );
CREATE POLICY app_workspace_update ON medawarcre.deal_ops_events
    FOR UPDATE TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id())
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND updated_by_user_id = medawarcre.current_actor_user_id()
    );
CREATE POLICY app_workspace_delete ON medawarcre.deal_ops_events
    FOR DELETE TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id());

DO $write_policies$
DECLARE
    relation_name text;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'deal_commitments', 'deal_exchanges'
    ] LOOP
        EXECUTE format(
            'CREATE POLICY app_workspace_insert ON medawarcre.%I '
            'FOR INSERT TO medawarcre_app '
            'WITH CHECK (workspace_id = medawarcre.current_workspace_id() '
            'AND created_by_user_id = medawarcre.current_actor_user_id() '
            'AND updated_by_user_id = medawarcre.current_actor_user_id())',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY app_workspace_update ON medawarcre.%I '
            'FOR UPDATE TO medawarcre_app '
            'USING (workspace_id = medawarcre.current_workspace_id()) '
            'WITH CHECK (workspace_id = medawarcre.current_workspace_id() '
            'AND updated_by_user_id = medawarcre.current_actor_user_id())',
            relation_name
        );
    END LOOP;
END
$write_policies$;

CREATE POLICY app_workspace_insert ON medawarcre.deal_investors
    FOR INSERT TO medawarcre_app
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND created_by_user_id = medawarcre.current_actor_user_id()
        AND updated_by_user_id = medawarcre.current_actor_user_id()
    );

CREATE POLICY app_workspace_insert ON medawarcre.deal_exchange_replacements
    FOR INSERT TO medawarcre_app
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND created_by_user_id = medawarcre.current_actor_user_id()
    );

CREATE POLICY app_workspace_insert ON medawarcre.deal_ic_decisions
    FOR INSERT TO medawarcre_app
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND created_by_user_id = medawarcre.current_actor_user_id()
        AND request_invocation_id IS NOT NULL
    );

DROP POLICY tenant_access ON medawarcre.deal_outcomes;
CREATE POLICY app_workspace_select ON medawarcre.deal_outcomes
    FOR SELECT TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id());
CREATE POLICY app_workspace_insert ON medawarcre.deal_outcomes
    FOR INSERT TO medawarcre_app
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND created_by_user_id = medawarcre.current_actor_user_id()
        AND updated_by_user_id = medawarcre.current_actor_user_id()
    );
CREATE POLICY app_workspace_update ON medawarcre.deal_outcomes
    FOR UPDATE TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id())
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND updated_by_user_id = medawarcre.current_actor_user_id()
    );

DROP POLICY tenant_access ON medawarcre.deal_events;
CREATE POLICY app_workspace_select ON medawarcre.deal_events
    FOR SELECT TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id());
CREATE POLICY app_workspace_insert ON medawarcre.deal_events
    FOR INSERT TO medawarcre_app
    WITH CHECK (
        workspace_id = medawarcre.current_workspace_id()
        AND author_user_id = medawarcre.current_actor_user_id()
        AND request_invocation_id IS NOT NULL
    );

REVOKE ALL ON
    medawarcre.deal_dd_items,
    medawarcre.deal_ops_events,
    medawarcre.deal_investors,
    medawarcre.deal_commitments,
    medawarcre.deal_exchanges,
    medawarcre.deal_exchange_replacements,
    medawarcre.deal_ic_decisions
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth,
     medawarcre_provider_ingress, medawarcre_provider_reconcile,
     medawarcre_worker, medawarcre_scheduler;

REVOKE DELETE ON medawarcre.deals, medawarcre.deal_notes,
    medawarcre.deal_outcomes FROM medawarcre_app;
REVOKE UPDATE ON medawarcre.deal_notes FROM medawarcre_app;
REVOKE ALL ON medawarcre.deals, medawarcre.deal_notes,
    medawarcre.deal_outcomes, medawarcre.deal_events FROM medawarcre_app;

GRANT SELECT (
    id, workspace_id, source, source_record_id, listing, stage, score, grade,
    strategy, accountability_owner, next_action, next_action_due,
    created_at, updated_at
) ON medawarcre.deals TO medawarcre_app;
GRANT INSERT (
    workspace_id, source, source_record_id, title, listing, asking_price,
    stage, score, grade, strategy, source_rights_id, source_rights_verified_on,
    created_by_user_id, updated_by_user_id
) ON medawarcre.deals TO medawarcre_app;
GRANT UPDATE (
    title, listing, asking_price, stage, score, grade, strategy,
    accountability_owner, next_action, next_action_due, source_rights_id,
    source_rights_verified_on, updated_by_user_id, updated_at
) ON medawarcre.deals TO medawarcre_app;

GRANT SELECT (id, workspace_id, deal_id, body, stage, created_at)
ON medawarcre.deal_notes TO medawarcre_app;
GRANT INSERT (workspace_id, deal_id, author_user_id, body, stage)
ON medawarcre.deal_notes TO medawarcre_app;

GRANT SELECT (
    workspace_id, deal_id, closed, purchase_price, realized_hold_years,
    realized_irr, realized_equity_multiple, went_bad, notes, predicted_score,
    predicted_grade, predicted_strategy, created_at, updated_at
) ON medawarcre.deal_outcomes TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, closed, purchase_price, realized_hold_years,
    realized_irr, realized_equity_multiple, went_bad, notes, predicted_score,
    predicted_grade, predicted_strategy, created_by_user_id, updated_by_user_id
) ON medawarcre.deal_outcomes TO medawarcre_app;
GRANT UPDATE (
    closed, purchase_price, realized_hold_years, realized_irr,
    realized_equity_multiple, went_bad, notes, updated_by_user_id, updated_at
) ON medawarcre.deal_outcomes TO medawarcre_app;

GRANT SELECT (
    id, workspace_id, deal_id, event_type, event_data, occurred_at, created_at,
    request_invocation_id
) ON medawarcre.deal_events TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, event_type, event_data, occurred_at,
    author_user_id, request_invocation_id
) ON medawarcre.deal_events TO medawarcre_app;

GRANT SELECT (workspace_id, deal_id, item_key, item_data, status, deadline)
ON medawarcre.deal_dd_items TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, item_key, item_data, status, deadline,
    created_by_user_id, updated_by_user_id
) ON medawarcre.deal_dd_items TO medawarcre_app;
GRANT UPDATE (item_data, deadline, updated_by_user_id, updated_at)
ON medawarcre.deal_dd_items TO medawarcre_app;
GRANT DELETE ON medawarcre.deal_dd_items TO medawarcre_app;

GRANT SELECT (
    workspace_id, deal_id, event_key, event_data, category, event_date, status
) ON medawarcre.deal_ops_events TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, event_key, event_data, category, event_date, status,
    created_by_user_id, updated_by_user_id
) ON medawarcre.deal_ops_events TO medawarcre_app;
GRANT UPDATE (event_data, category, event_date, updated_by_user_id, updated_at)
ON medawarcre.deal_ops_events TO medawarcre_app;
GRANT DELETE ON medawarcre.deal_ops_events TO medawarcre_app;

GRANT SELECT (
    id, workspace_id, name, accredited, accreditation_verified, relationship,
    contact, created_at, updated_at
) ON medawarcre.deal_investors TO medawarcre_app;
GRANT INSERT (
    workspace_id, name, accredited, accreditation_verified, relationship,
    contact, created_by_user_id, updated_by_user_id
) ON medawarcre.deal_investors TO medawarcre_app;

GRANT SELECT (
    id, workspace_id, deal_id, investor_id, amount, created_at, updated_at
) ON medawarcre.deal_commitments TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, investor_id, amount, created_by_user_id,
    updated_by_user_id
) ON medawarcre.deal_commitments TO medawarcre_app;
GRANT UPDATE (amount, updated_by_user_id, updated_at)
ON medawarcre.deal_commitments TO medawarcre_app;

GRANT SELECT (
    id, workspace_id, relinquished_deal_id, relinquished_close_date,
    identification_deadline, exchange_deadline, created_at, updated_at
) ON medawarcre.deal_exchanges TO medawarcre_app;
GRANT INSERT (
    workspace_id, relinquished_deal_id, relinquished_close_date,
    identification_deadline, exchange_deadline, created_by_user_id,
    updated_by_user_id
) ON medawarcre.deal_exchanges TO medawarcre_app;
GRANT UPDATE (
    identification_deadline, exchange_deadline, updated_by_user_id, updated_at
) ON medawarcre.deal_exchanges TO medawarcre_app;

GRANT SELECT (workspace_id, exchange_id, deal_id, value, identified_at)
ON medawarcre.deal_exchange_replacements TO medawarcre_app;
GRANT INSERT (
    workspace_id, exchange_id, deal_id, value, identified_at, created_by_user_id
) ON medawarcre.deal_exchange_replacements TO medawarcre_app;

GRANT SELECT (
    id, workspace_id, deal_id, system_verdict, system_data, expert_verdict,
    expert_data, agreed, created_at, request_invocation_id
) ON medawarcre.deal_ic_decisions TO medawarcre_app;
GRANT INSERT (
    workspace_id, deal_id, system_verdict, system_data, expert_verdict,
    expert_data, agreed, created_by_user_id, request_invocation_id
) ON medawarcre.deal_ic_decisions TO medawarcre_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    medawarcre.deal_dd_items,
    medawarcre.deal_ops_events,
    medawarcre.deal_investors,
    medawarcre.deal_commitments,
    medawarcre.deal_exchanges,
    medawarcre.deal_exchange_replacements,
    medawarcre.deal_ic_decisions
TO medawarcre_admin;

GRANT SELECT ON
    medawarcre.deal_dd_items,
    medawarcre.deal_ops_events,
    medawarcre.deal_investors,
    medawarcre.deal_commitments,
    medawarcre.deal_exchanges,
    medawarcre.deal_exchange_replacements,
    medawarcre.deal_ic_decisions
TO medawarcre_backup;
