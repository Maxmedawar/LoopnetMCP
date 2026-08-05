CREATE TABLE medawarcre.truth_document_blobs (
    workspace_id uuid NOT NULL
        REFERENCES medawarcre.workspaces(id) ON DELETE CASCADE,
    document_id bytea NOT NULL,
    content bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (workspace_id, document_id),
    CHECK (octet_length(document_id) = 32),
    CHECK (octet_length(content) BETWEEN 1 AND 52428800),
    CHECK (document_id = pg_catalog.sha256(content))
);

CREATE TABLE medawarcre.truth_documents (
    workspace_id uuid NOT NULL,
    deal_ref text NOT NULL,
    document_id bytea NOT NULL,
    doc_kind text NOT NULL,
    source_channel text NOT NULL,
    origin text,
    format text NOT NULL,
    n_pages integer,
    parse_status text NOT NULL,
    redactions integer NOT NULL DEFAULT 0,
    ingested_at timestamptz NOT NULL,
    PRIMARY KEY (workspace_id, deal_ref, document_id),
    FOREIGN KEY (workspace_id, document_id)
        REFERENCES medawarcre.truth_document_blobs(workspace_id, document_id)
        ON DELETE CASCADE,
    CHECK (
        length(deal_ref) BETWEEN 1 AND 512
        AND deal_ref = btrim(deal_ref)
    ),
    CHECK (octet_length(document_id) = 32),
    CHECK (doc_kind IN (
        'offering_memorandum', 'rent_roll', 't12_operating_statement',
        'lease', 'lease_amendment', 'estoppel_certificate', 'bank_statement',
        'tax_bill', 'appraisal', 'survey', 'assessor_record', 'listing_page',
        'unknown'
    )),
    CHECK (source_channel IN ('uploaded', 'scraped')),
    CHECK (origin IS NULL OR length(origin) <= 4096),
    CHECK (format IN ('pdf', 'xlsx', 'csv')),
    CHECK (n_pages IS NULL OR n_pages BETWEEN 1 AND 1000000),
    CHECK (parse_status IN ('parsed', 'needs_ocr', 'failed')),
    CHECK (redactions BETWEEN 0 AND 1000000)
);
CREATE INDEX truth_documents_deal_idx
    ON medawarcre.truth_documents(workspace_id, deal_ref, ingested_at DESC);

CREATE TABLE medawarcre.truth_claims (
    workspace_id uuid NOT NULL,
    deal_ref text NOT NULL,
    document_id bytea NOT NULL,
    field text NOT NULL,
    subject text NOT NULL DEFAULT '',
    value_kind text NOT NULL,
    value_number double precision,
    value_text text,
    unit text NOT NULL,
    confidence double precision NOT NULL,
    lineage_doc_kind text NOT NULL,
    lineage_source_channel text NOT NULL,
    lineage_page integer,
    lineage_cell text,
    lineage_bbox double precision[],
    lineage_raw_text text NOT NULL DEFAULT '',
    extraction_method text NOT NULL,
    lineage_origin text,
    flags text[] NOT NULL DEFAULT ARRAY[]::text[],
    PRIMARY KEY (workspace_id, deal_ref, document_id, field, subject),
    FOREIGN KEY (workspace_id, deal_ref, document_id)
        REFERENCES medawarcre.truth_documents(workspace_id, deal_ref, document_id)
        ON DELETE CASCADE,
    CHECK (
        length(deal_ref) BETWEEN 1 AND 512
        AND deal_ref = btrim(deal_ref)
    ),
    CHECK (octet_length(document_id) = 32),
    CHECK (length(field) BETWEEN 1 AND 128 AND field = btrim(field)),
    CHECK (length(subject) <= 512 AND subject = btrim(subject)),
    CHECK (value_kind IN ('null', 'number', 'text')),
    CHECK (
        (value_kind = 'null' AND value_number IS NULL AND value_text IS NULL)
        OR (value_kind = 'number' AND value_number IS NOT NULL AND value_text IS NULL)
        OR (value_kind = 'text' AND value_number IS NULL AND value_text IS NOT NULL)
    ),
    CHECK (
        value_number IS NULL
        OR value_number::text NOT IN ('NaN', 'Infinity', '-Infinity')
    ),
    CHECK (value_text IS NULL OR length(value_text) <= 16384),
    CHECK (unit IN (
        'usd', 'usd_per_year', 'usd_per_month', 'usd_per_sqft', 'sqft',
        'pct', 'count', 'date', 'text'
    )),
    CHECK (
        confidence BETWEEN 0.0 AND 1.0
        AND confidence::text NOT IN ('NaN', 'Infinity', '-Infinity')
    ),
    CHECK (lineage_doc_kind IN (
        'offering_memorandum', 'rent_roll', 't12_operating_statement',
        'lease', 'lease_amendment', 'estoppel_certificate', 'bank_statement',
        'tax_bill', 'appraisal', 'survey', 'assessor_record', 'listing_page',
        'unknown'
    )),
    CHECK (lineage_source_channel IN ('uploaded', 'scraped')),
    CHECK (lineage_page IS NULL OR lineage_page BETWEEN 1 AND 1000000),
    CHECK (lineage_cell IS NULL OR length(lineage_cell) <= 256),
    CHECK (
        lineage_bbox IS NULL
        OR (
            array_ndims(lineage_bbox) = 1
            AND cardinality(lineage_bbox) = 4
            AND array_lower(lineage_bbox, 1) = 1
            AND array_upper(lineage_bbox, 1) = 4
            AND array_position(lineage_bbox, NULL) IS NULL
            AND lineage_bbox[1]::text NOT IN ('NaN', 'Infinity', '-Infinity')
            AND lineage_bbox[2]::text NOT IN ('NaN', 'Infinity', '-Infinity')
            AND lineage_bbox[3]::text NOT IN ('NaN', 'Infinity', '-Infinity')
            AND lineage_bbox[4]::text NOT IN ('NaN', 'Infinity', '-Infinity')
        )
    ),
    CHECK (length(lineage_raw_text) <= 8192),
    CHECK (extraction_method IN (
        'xlsx_cell', 'csv_cell', 'pdf_table', 'pdf_text_regex',
        'llm_assisted', 'manual_entry'
    )),
    CHECK (lineage_origin IS NULL OR length(lineage_origin) <= 4096),
    CHECK (
        array_ndims(flags) = 1
        AND cardinality(flags) <= 32
        AND array_position(flags, NULL) IS NULL
        AND length(array_to_string(flags, '')) <= 4096
    )
);
CREATE INDEX truth_claims_deal_idx
    ON medawarcre.truth_claims(workspace_id, deal_ref, field);

ALTER TABLE medawarcre.truth_document_blobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE medawarcre.truth_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE medawarcre.truth_claims ENABLE ROW LEVEL SECURITY;

CREATE POLICY app_insert_workspace_truth_blobs
    ON medawarcre.truth_document_blobs
    FOR INSERT TO medawarcre_app
    WITH CHECK (workspace_id = medawarcre.current_workspace_id());
CREATE POLICY app_read_workspace_truth_blob_keys
    ON medawarcre.truth_document_blobs
    FOR SELECT TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id());
CREATE POLICY internal_read
    ON medawarcre.truth_document_blobs
    FOR SELECT TO medawarcre_admin
    USING (medawarcre.internal_authorized());
CREATE POLICY internal_manage
    ON medawarcre.truth_document_blobs
    FOR ALL TO medawarcre_admin
    USING (medawarcre.internal_can_mutate())
    WITH CHECK (medawarcre.internal_can_mutate());

CREATE POLICY app_workspace_truth_documents
    ON medawarcre.truth_documents
    FOR ALL TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id())
    WITH CHECK (workspace_id = medawarcre.current_workspace_id());
CREATE POLICY internal_read
    ON medawarcre.truth_documents
    FOR SELECT TO medawarcre_admin
    USING (medawarcre.internal_authorized());
CREATE POLICY internal_manage
    ON medawarcre.truth_documents
    FOR ALL TO medawarcre_admin
    USING (medawarcre.internal_can_mutate())
    WITH CHECK (medawarcre.internal_can_mutate());

CREATE POLICY app_workspace_truth_claims
    ON medawarcre.truth_claims
    FOR ALL TO medawarcre_app
    USING (workspace_id = medawarcre.current_workspace_id())
    WITH CHECK (workspace_id = medawarcre.current_workspace_id());
CREATE POLICY internal_read
    ON medawarcre.truth_claims
    FOR SELECT TO medawarcre_admin
    USING (medawarcre.internal_authorized());
CREATE POLICY internal_manage
    ON medawarcre.truth_claims
    FOR ALL TO medawarcre_admin
    USING (medawarcre.internal_can_mutate())
    WITH CHECK (medawarcre.internal_can_mutate());

REVOKE ALL ON
    medawarcre.truth_document_blobs,
    medawarcre.truth_documents,
    medawarcre.truth_claims
FROM PUBLIC, medawarcre_app, medawarcre_admin, medawarcre_backup,
     medawarcre_admission, medawarcre_oauth,
     medawarcre_provider_ingress, medawarcre_provider_reconcile,
     medawarcre_worker, medawarcre_scheduler;

GRANT SELECT (workspace_id, document_id), INSERT
ON medawarcre.truth_document_blobs TO medawarcre_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON
    medawarcre.truth_documents,
    medawarcre.truth_claims
TO medawarcre_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON
    medawarcre.truth_document_blobs,
    medawarcre.truth_documents,
    medawarcre.truth_claims
TO medawarcre_admin;
GRANT SELECT ON
    medawarcre.truth_document_blobs,
    medawarcre.truth_documents,
    medawarcre.truth_claims
TO medawarcre_backup;
