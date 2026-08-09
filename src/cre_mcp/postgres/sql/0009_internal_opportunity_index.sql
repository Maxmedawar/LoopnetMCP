-- Phase 5K: the internal-only combined opportunity index.
--
-- The customer boundary here is a grant boundary before it is a policy
-- boundary: medawarcre_app receives no privilege on any relation below, so a
-- customer-role statement is refused by PostgreSQL before row-level security is
-- consulted. RLS is the second layer, and internal_authorized() — which
-- requires a live staff_roles row plus a non-blank audit reason — is the third.

-- One canonical entry per deduplicated property.
-- Deliberately no property_type column. This is the one table in the program
-- that outlives any single tenant: a workspace delete cannot remove a row
-- another workspace still contributes to, and an entry that has been reviewed
-- cannot be deleted at all. Round four moved the tenant's deal title off this
-- row and, in the same round, made property_type refresh onto it — so tenant
-- free text came straight back through a different column, this time writable
-- by the customer through its own deals.listing grant and surviving complete
-- erasure on an entry that stayed active and listed. property_type lives only
-- on the per-workspace source rows, which cascade away with the tenant record
-- that supplied them; the entry's value is derived from them at read time.
-- market and property_identity stay because they are derived from the
-- normalized key every contributor agrees on, not from a tenant's own words.
ALTER TABLE medawarcre.internal_opportunities
    ADD COLUMN property_identity jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN market text,
    ADD COLUMN merged_into_opportunity_id uuid
        REFERENCES medawarcre.internal_opportunities(id),
    ADD COLUMN first_observed_at timestamptz NOT NULL
        DEFAULT statement_timestamp(),
    ADD COLUMN last_observed_at timestamptz NOT NULL
        DEFAULT statement_timestamp();

ALTER TABLE medawarcre.internal_opportunities
    DROP CONSTRAINT internal_opportunities_status_check,
    ADD CONSTRAINT internal_opportunities_status_check CHECK (
        status IN ('active', 'suppressed', 'archived', 'merged')
    ),
    -- A merge is a link, never a collapse. What the superseded entry keeps is
    -- the link and its review history — NOT its source rows: the next ordinary
    -- re-ingest re-binds those to the canonical head, because a live
    -- observation belongs where staff can see it. An earlier version of this
    -- comment promised the source rows stayed attached "so the history of the
    -- mistake stays inspectable"; the contract retracted that and this file
    -- kept asserting it, which a reviewer caught. The merge stays inspectable
    -- through the retained link, the reviews, and the staff_audit_log row.
    -- A merged entry can still lose its last observation and be archived, and
    -- the duplicate relationship must survive that: the contract requires
    -- duplicate relationships be retained, so archival may not clear the link.
    -- Stated as two implications rather than an equivalence, because the
    -- equivalence made archiving a merged entry impossible.
    -- 'suppressed' is in the second set because a merge must not clear it.
    -- merge preserved only 'archived', and unmerge chose only between 'active'
    -- and 'archived', so a merge round-trip laundered a deliberately hidden
    -- entry back into the default staff listing — suppression being the only
    -- mechanism staff have for hiding one.
    ADD CONSTRAINT internal_opportunities_merge_check CHECK (
        (status <> 'merged' OR merged_into_opportunity_id IS NOT NULL)
        AND (merged_into_opportunity_id IS NULL
             OR status IN ('merged', 'archived', 'suppressed'))
    ),
    ADD CONSTRAINT internal_opportunities_no_self_merge_check CHECK (
        merged_into_opportunity_id IS NULL OR merged_into_opportunity_id <> id
    ),
    ADD CONSTRAINT internal_opportunities_observed_order_check CHECK (
        last_observed_at >= first_observed_at
    ),
    ADD CONSTRAINT internal_opportunities_canonical_key_check CHECK (
        length(canonical_key) BETWEEN 1 AND 512
        AND canonical_key = btrim(canonical_key)
    ),
    ADD CONSTRAINT internal_opportunities_identity_object_check CHECK (
        jsonb_typeof(property_identity) = 'object'
    ),
    ADD CONSTRAINT internal_opportunities_market_check CHECK (
        market IS NULL
        OR (length(market) BETWEEN 1 AND 200 AND market = btrim(market))
    );

-- One row per contributing workspace observation. Deduplication merges these
-- under one opportunity; it never merges them into each other.
ALTER TABLE medawarcre.internal_opportunity_sources
    ADD COLUMN origin text NOT NULL DEFAULT 'deal',
    ADD COLUMN source_user_id uuid,
    ADD COLUMN source_saved_search_id uuid,
    ADD COLUMN source_search_result_id uuid,
    ADD COLUMN source_deal_id uuid,
    ADD COLUMN observed_property_identity jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN observed_market text,
    ADD COLUMN observed_property_type text,
    ADD COLUMN score numeric(10, 4),
    ADD COLUMN stage text,
    ADD COLUMN outcome text,
    ADD COLUMN source_observed_at timestamptz NOT NULL
        DEFAULT statement_timestamp();

ALTER TABLE medawarcre.internal_opportunity_sources
    ALTER COLUMN origin DROP DEFAULT,
    ALTER COLUMN observed_property_identity DROP DEFAULT,
    ADD CONSTRAINT internal_opportunity_sources_origin_check CHECK (
        origin IN ('search_result', 'deal')
    ),
    -- Exactly one tenant record backs an observation, and it is the one the
    -- origin names. Both null, or both set, is a provenance claim that cannot
    -- be checked.
    ADD CONSTRAINT internal_opportunity_sources_origin_binding_check CHECK (
        (origin = 'deal'
         AND source_deal_id IS NOT NULL
         AND source_search_result_id IS NULL)
        OR (origin = 'search_result'
            AND source_search_result_id IS NOT NULL
            AND source_deal_id IS NULL)
    ),
    ADD CONSTRAINT internal_opportunity_sources_identity_object_check CHECK (
        jsonb_typeof(observed_property_identity) = 'object'
    ),
    ADD CONSTRAINT internal_opportunity_sources_score_check CHECK (
        score IS NULL
        OR (score BETWEEN 0 AND 100
            AND score::text NOT IN ('NaN', 'Infinity', '-Infinity'))
    ),
    ADD CONSTRAINT internal_opportunity_sources_stage_check CHECK (
        stage IS NULL
        OR stage IN ('lead', 'analyzing', 'contacted', 'loi', 'under_contract',
                     'diligence', 'closing', 'owned', 'passed')
    ),
    ADD CONSTRAINT internal_opportunity_sources_outcome_check CHECK (
        outcome IS NULL
        OR outcome IN ('open', 'closed', 'passed', 'went_bad')
    ),
    -- DEFERRABLE INITIALLY DEFERRED to match the membership keys migration
    -- 0008 added on ``deals``. 0008 made those deferrable so that one
    -- offboarding transaction can delete a membership and the rows citing it
    -- together; an immediate key here would abort that same transaction at the
    -- membership DELETE, but only for workspaces staff had ingested — a
    -- deletion path whose success depended on whether the index had run.
    ADD CONSTRAINT internal_opportunity_sources_user_membership_fkey
        FOREIGN KEY (workspace_id, source_user_id)
        REFERENCES medawarcre.memberships(workspace_id, user_id)
        DEFERRABLE INITIALLY DEFERRED,
    -- Deletion of the tenant record removes the derived observation. The index
    -- is derived data; a privacy deletion must not outlive its subject.
    ADD CONSTRAINT internal_opportunity_sources_deal_fkey
        FOREIGN KEY (workspace_id, source_deal_id)
        REFERENCES medawarcre.deals(workspace_id, id) ON DELETE CASCADE,
    ADD CONSTRAINT internal_opportunity_sources_search_result_fkey
        FOREIGN KEY (workspace_id, source_search_result_id)
        REFERENCES medawarcre.search_results(workspace_id, id) ON DELETE CASCADE,
    -- SET NULL on the *saved-search column only*. Over a composite key
    -- PostgreSQL nulls every referencing column, including workspace_id, which
    -- is NOT NULL — so deleting a saved search would raise a raw
    -- NotNullViolation out of a cross-tenant table. Latent only because
    -- origin='search_result' is never written yet; the column is reachable.
    ADD CONSTRAINT internal_opportunity_sources_saved_search_fkey
        FOREIGN KEY (workspace_id, source_saved_search_id)
        REFERENCES medawarcre.saved_searches(workspace_id, id)
        ON DELETE SET NULL (source_saved_search_id);

-- Review history. Global rather than tenant-scoped: a review is a statement
-- about the combined entry by a named member of staff, citing no tenant
-- content, which is why it survives tenant deletion.
CREATE TABLE medawarcre.internal_opportunity_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id uuid NOT NULL
        REFERENCES medawarcre.internal_opportunities(id) ON DELETE CASCADE,
    reviewer_user_id uuid NOT NULL REFERENCES medawarcre.users(id),
    reviewer_role text NOT NULL CHECK (reviewer_role IN ('owner', 'admin',
                                                         'jv_operations', 'support',
                                                         'security_audit',
                                                         'read_only_analyst')),
    verdict text NOT NULL CHECK (verdict IN ('promote', 'dismiss',
                                             'duplicate_confirmed',
                                             'duplicate_rejected',
                                             'needs_more_data')),
    reason_code text NOT NULL,
    reason text NOT NULL,
    note text,
    occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CHECK (length(btrim(reason)) > 0),
    CHECK (length(btrim(reason_code)) > 0),
    CHECK (note IS NULL OR length(btrim(note)) > 0)
);

ALTER TABLE medawarcre.internal_opportunity_reviews
    ENABLE ROW LEVEL SECURITY;

CREATE POLICY internal_read ON medawarcre.internal_opportunity_reviews
    FOR SELECT TO medawarcre_admin
    USING (medawarcre.internal_authorized());

-- Written only as yourself, in your own role, with the reason you declared —
-- the same forgery guard staff_audit_log carries.
CREATE POLICY internal_insert ON medawarcre.internal_opportunity_reviews
    FOR INSERT TO medawarcre_admin
    WITH CHECK (
        medawarcre.internal_can_mutate()
        AND reviewer_user_id = medawarcre.current_actor_user_id()
        AND reviewer_role = current_setting('app.internal_role', true)
        AND reason = current_setting('app.audit_reason', true)
    );

CREATE TRIGGER internal_opportunity_reviews_no_update
BEFORE UPDATE ON medawarcre.internal_opportunity_reviews
FOR EACH ROW EXECUTE FUNCTION medawarcre.reject_audit_mutation();
CREATE TRIGGER internal_opportunity_reviews_no_delete
BEFORE DELETE ON medawarcre.internal_opportunity_reviews
FOR EACH ROW EXECUTE FUNCTION medawarcre.reject_audit_mutation();

-- Keyset pagination on a stable total order, and the declared filter facets.
-- Ordered by created_at, which is immutable: re-ingest bumps
-- last_observed_at, and paging on a key the writer moves can skip entries.
CREATE INDEX internal_opportunities_keyset_idx
    ON medawarcre.internal_opportunities (created_at DESC, id DESC);
-- An expression index, because the listing filters lower(o.market). The
-- plain (market, status) form left the leading column unusable and every
-- market filter on a sequential scan — the same defect the keyset index had
-- two rounds earlier, in an index rebuilt to fix something else.
CREATE INDEX internal_opportunities_market_idx
    ON medawarcre.internal_opportunities (lower(market), status);
CREATE INDEX internal_opportunity_sources_property_type_idx
    ON medawarcre.internal_opportunity_sources (observed_property_type);
CREATE INDEX internal_opportunity_sources_user_idx
    ON medawarcre.internal_opportunity_sources (source_user_id, workspace_id);
CREATE INDEX internal_opportunity_sources_facets_idx
    ON medawarcre.internal_opportunity_sources (opportunity_id, stage, outcome);
CREATE INDEX internal_opportunity_sources_score_idx
    ON medawarcre.internal_opportunity_sources (opportunity_id, score);
CREATE INDEX internal_opportunity_reviews_opportunity_idx
    ON medawarcre.internal_opportunity_reviews (opportunity_id, occurred_at DESC, id DESC);

REVOKE ALL ON medawarcre.internal_opportunity_reviews
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth,
     medawarcre_provider_ingress, medawarcre_provider_reconcile,
     medawarcre_worker, medawarcre_scheduler;

GRANT SELECT, INSERT ON medawarcre.internal_opportunity_reviews
TO medawarcre_admin;
GRANT SELECT ON medawarcre.internal_opportunity_reviews TO medawarcre_backup;

-- Restated rather than assumed: no customer role reaches any index relation.
REVOKE ALL ON medawarcre.internal_opportunities,
              medawarcre.internal_opportunity_sources
FROM medawarcre_app, medawarcre_oauth, medawarcre_admission,
     medawarcre_provider_ingress, medawarcre_provider_reconcile,
     medawarcre_worker, medawarcre_scheduler;

-- An entry whose last contributing observation is gone is archived, so tenant
-- deletion propagates into the derived index rather than leaving a normalized
-- property address visible in a cross-tenant table that no workspace
-- contributes to. A trigger rather than repository code, because the deletion
-- that strands the entry happens in the tenant's own tables and cascades here
-- without the index being called at all.
CREATE FUNCTION medawarcre.archive_sourceless_opportunity()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $function$
BEGIN
    UPDATE medawarcre.internal_opportunities opportunity
    SET status = 'archived', updated_at = statement_timestamp()
    WHERE opportunity.id = OLD.opportunity_id
      AND opportunity.status IN ('active', 'merged')
      AND NOT EXISTS (
          SELECT 1 FROM medawarcre.internal_opportunity_sources remaining
          WHERE remaining.opportunity_id = OLD.opportunity_id
      );
    RETURN NULL;
END
$function$;
REVOKE ALL ON FUNCTION medawarcre.archive_sourceless_opportunity() FROM PUBLIC;

-- DELETE *and* the re-bind UPDATE: correcting an address moves the last
-- observation off its old entry without deleting anything, which left a
-- sourceless entry carrying a tenant's normalized address in the listing.
CREATE TRIGGER internal_opportunity_sources_archive_orphan
AFTER DELETE OR UPDATE OF opportunity_id
ON medawarcre.internal_opportunity_sources
FOR EACH ROW EXECUTE FUNCTION medawarcre.archive_sourceless_opportunity();

-- A merge target must itself be canonical. Enforced here because a CHECK
-- cannot see another row.
--
-- Without this, A->B followed by B->A is accepted and both entries leave every
-- default listing permanently: re-observation only lifts entries whose merge
-- link is NULL, and nothing in the product ever cleared that link. A third,
-- entirely uninvolved workspace that later observed the same property was
-- reported ``admitted=1`` while its observation landed under an invisible
-- entry. Requiring the target to be canonical makes a cycle of any length
-- unconstructible and caps chains at depth one, so "what is this a duplicate
-- of" always has an answer a human can reach.
-- Two conditions, and the target lookup must LOCK the target.
--
-- An unlocked SELECT here was not enough: two concurrent merges each read the
-- other's entry as still canonical and both committed, building a cycle in 34
-- of 40 trials through the public repository call. FOR UPDATE makes A->B and
-- B->A serialize on the same two rows, so the second one either sees the link
-- or deadlocks — a clean abort instead of a silent cycle.
--
-- And inspecting only the target was not enough either: C->A followed by A->B
-- built a depth-2 chain with no concurrency at all, because nothing asked
-- whether the entry being merged was itself somebody's target. "What is C a
-- duplicate of?" then answered with a row that was itself merged. The
-- dependents check closes that, and because both statements take the target's
-- lock, the concurrent interleaving of the same two calls serializes too.
CREATE FUNCTION medawarcre.require_canonical_merge_target()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $function$
DECLARE
    target_link uuid;
    target_found boolean;
    dependent uuid;
BEGIN
    IF NEW.merged_into_opportunity_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT target.merged_into_opportunity_id, true
      INTO target_link, target_found
      FROM medawarcre.internal_opportunities target
     WHERE target.id = NEW.merged_into_opportunity_id
       FOR UPDATE;
    IF NOT COALESCE(target_found, false) THEN
        RAISE EXCEPTION
            'merge target does not exist'
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF target_link IS NOT NULL THEN
        RAISE EXCEPTION
            'merge target is itself merged; merge into the canonical entry'
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT dependent_entry.id INTO dependent
      FROM medawarcre.internal_opportunities dependent_entry
     WHERE dependent_entry.merged_into_opportunity_id = NEW.id
     LIMIT 1;
    IF dependent IS NOT NULL THEN
        RAISE EXCEPTION
            'this entry is itself a merge target; merge its duplicates first'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION medawarcre.require_canonical_merge_target() FROM PUBLIC;

CREATE TRIGGER internal_opportunities_canonical_merge_target
BEFORE INSERT OR UPDATE OF merged_into_opportunity_id
ON medawarcre.internal_opportunities
FOR EACH ROW EXECUTE FUNCTION medawarcre.require_canonical_merge_target();
