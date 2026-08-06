# Phase 5G hosted deal persistence contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `b0947d724f734cebadc16ebacb27917de90acca6`

## Outcome and boundary

This slice replaces the hosted deal-domain marker with one request-scoped
PostgreSQL authority for the complete non-search `DealStore` surface used by
customer capabilities. It covers the shared deal workspace, pipeline notes and
accountability, diligence checklists, operating events, realized outcomes,
investor CRM and non-binding commitments, 1031 exchange records, and deal-event
plus shadow-IC memory.

Every hosted customer path that uses this surface must receive the injected
deal repository. It cannot construct the combined local SQLite `DealStore`,
reach the dedicated search port, or recover a process-global store. Trusted
local stdio retains the existing SQLite schema, integer identifiers, and result
behavior.

This slice does not claim parity for separate file-backed modules that do not
use `DealStore`. Correction, recorded after review: those modules do **not**
all remain fail closed in hosted execution. A module that constructs
`DealStore` does, because its constructor refuses an untrusted context, but
`LedgerStore`, `SnapshotStore`, and `DataRoomStore` resolve a workspace-scoped
path and answer normally. That is why `counterparty_track_record` was a live
territory oracle for `jv_partner` and had to be withheld separately, and why
seven capabilities that reach those stores are entitled but dead in hosted
execution. Both are tracked in the launch ledger and must be resolved before
hosted launch.

## Exact request and method authority

`PostgresDealRepository` is constructed from one app database and one exact
fresh allowed admission. Every method requires that exact object to be the deal
port in the active aggregate repository lease. The active untrusted
`TenantContext` must match the admission workspace public ID, actor UUID, and
OAuth session UUID. A captured reference becomes invalid when the lease exits;
detached tasks cannot regain either PostgreSQL or SQLite authority.

Method authority is capability-specific and closed by default:

- `save_deal`: `save_deal`, `add_to_pipeline`, `due_diligence_plan`,
  `operating_playbook`, `start_exchange`, and `identify_replacement`;
- `get_deal`: `start_exchange`, `identify_replacement`, `ingest_document`,
  `build_noi_bridge`, `deal_truth_report`, `deal_timeline`, and
  `list_deal_documents`, each of which must also receive a projection branch
  sufficient for what it does with the result;
- pipeline writes and reads: only `add_to_pipeline`, `update_deal_stage`,
  `assign_deal`, `unassigned_deals`, `list_pipeline`, and `list_deals` as
  required by their exact production call graphs;
- the composite diligence replacement method: only `due_diligence_plan`;
- the composite operating-calendar replacement method: only
  `operating_playbook`;
- outcome methods: only `record_deal_outcome`, with read-only outcome access
  also allowed to `backtest_score` and `ic_scorecard` where required;
- investor and commitment methods: only `add_investor`, `list_investors`, and
  `record_commitment` as required by their exact production call graphs;
- exchange methods: only `start_exchange`, `exchange_status`, and
  `identify_replacement` as required by their exact production call graphs;
- memory methods: only `record_ic_decision`, `log_deal_event`, `deal_timeline`,
  and `ic_scorecard` as required by their exact production call graphs.

An admission for one capability cannot call a method not required by that
capability. Every database operation uses `PostgresDatabase.admitted_connection`.
Hosted diligence and operating workflows use capability-level composite methods
that save the sanitized deal and replace the complete child plan in one admitted
transaction. Hosted exchange creation returns its stored clock in the creating
transaction, and replacement identification locks the exchange while enforcing
the day-45 and 3-property/200% rules before mutation.
Reads recheck exact active authority after their statements and after worker
completion. Writes recheck inside the transaction after DML and before commit.
Cancellation waits for the synchronous database worker before the request
lease can unwind. Missing, stale, mismatched, malformed, revoked, or unavailable
authority fails with only `deal persistence unavailable`; it is never converted
to an empty hosted success or local fallback.

## Workspace and actor semantics

Deals and their subordinate records are collaborative workspace state. Any
active admitted workspace member with an entitled exact capability may read the
workspace records permitted by that capability. The repository never accepts a
workspace selector or an actor-attribution selector from a method argument.
PostgreSQL derives both from the admitted transaction and RLS.

Creator or author identity is recorded where the schema supports human-authored
notes, investor records, exchange actions, outcomes, events, and IC decisions.
Actor attribution must match `current_actor_user_id()` and may not be forged.
An accountability owner label is workspace content, not an authority selector;
it cannot alter RLS, membership, or actor attribution.

Every returned row repeats or joins the authoritative workspace public ID. The
repository validates that projection against the admission before releasing
the row. Nested records must carry the same workspace and parent deal identity.
Cross-workspace object identifiers return no record and never disclose whether
the object exists.

## Identifiers and compatibility

The public deal identifier remains the established source-qualified
`source:source_record_id` value. It is immutable, unique only inside one
workspace, and resolved together with transaction-local RLS. The internal deal
primary key remains a PostgreSQL UUID and is never exposed or accepted as a
customer selector.

New hosted investor, commitment, exchange, deal-event, and IC-decision
identifiers are opaque canonical UUID strings. Customer input and result models
accept hosted UUID strings while preserving trusted-local integers. No global
integer sequence, cross-workspace alias, enumeration path, or local-to-hosted
identifier translation is introduced.

## Data, source-rights, and transaction contract

Deal listing writes use the existing source-rights storage sanitizer before
SQL. Every listing-bearing read reauthorizes the stored source against the live
rights registry before releasing content or a source-derived record. Each deal
stores the rights source ID and evidence-verification date used at write time;
that provenance is evidence, not a substitute for live reauthorization. Stored
listing JSON must be one bounded object matching its source and
source record columns. Source, record ID, title, stage, score, grade, strategy,
accountability fields, notes, timestamps, and all nested records are strictly
typed, bounded, finite where numeric, and validated again on read. Non-finite
numbers, unexpected JSON shapes, malformed timestamps, invalid enum values,
oversized content, or inconsistent parent projections fail closed.

Saving a known source record refreshes its sanitized listing and optional score
snapshot without resetting stage, notes, accountability, or child records.
Pipeline stage changes and optional note insertion are one transaction. Hosted
deal-plan replacement is capability-atomic: the deal refresh and all diligence
or operating child writes commit together. Existing statuses are retained, and
stale rows are removed only if the complete replacement succeeds. Outcome writes
freeze the original prediction on first
insert and never overwrite that frozen snapshot. Commitment and exchange
replacement writes are idempotent on their documented natural keys.
Replacement identification serializes concurrent writers on the exchange row
and applies the deadline and value/count rule set inside that same transaction.

No method partially commits before it knows that every input and returned
projection is valid. Multi-statement reads run at REPEATABLE READ so they
return one coherent transaction snapshot; the lock-and-mutate write paths stay
at READ COMMITTED because they take a row lock, wait for the current writer,
and must evaluate their rules against the committed result rather than fail
serialization. `title` and `asking_price` are write-only denormalized columns
the application role cannot select, so they are bounded and normalized on write
rather than rejecting a listing every read would still project correctly from
the listing JSON. Repository failures do not retry through another backend, dual write,
shadow write, reverse synchronize, or expose raw SQL or database details.

## Database authority and migration

Migration `0008` must leave every row that predates it readable and mutable:
listings are upgraded to the identity and shape the hosted reader validates
without inventing a location, and a mutating write re-derives source-rights
provenance from the live registry so a row created before that rule is healed
rather than becoming a permanently unusable but visible trap. It must add the
missing normalized deal-domain relations and constraints for diligence, operating events, investors, commitments, exchanges,
exchange replacements, and IC decisions, plus any bounded accountability and
frozen-prediction fields needed for parity. Existing deal, note, outcome, and
event relations must be narrowed or extended without weakening workspace RLS.

Application-role privileges are limited to the exact columns and operations the
repository needs. Workspace and actor identity columns cannot be selected or
mutated except where a safe projection is explicitly required for validation.
Every new table has enabled workspace RLS, exact composite parent foreign keys,
workspace teardown behavior, and explicit backup and reasoned-admin authority.
The migration owner intentionally bypasses RLS for schema migration, native
restore, and controlled seed operations; the runtime app role does not own these
tables and is constrained by both RLS and exact column-level ACLs. The app role
has no sequence dependency because all hosted public IDs are UUIDs.

## Required proof

Before commit, this phase requires:

- a missing-module RED test before implementation;
- native PostgreSQL parity tests for every non-search async `DealStore` method
  reached by customer capabilities;
- source-qualified deal-ID and opaque hosted UUID compatibility tests;
- exact admission, method, port, workspace, actor, OAuth session, detached
  reference, in-flight revocation, cancellation, and pre-commit rollback tests;
- cross-workspace, same-source-record, nested-parent, and direct-object-ID
  isolation tests, including a shared-workspace multi-actor collaboration case;
- source-rights sanitization and bounded/malformed input and stored-row tests;
- atomic stage-plus-note, plan replacement, frozen prediction, commitment,
  exchange, and concurrent-update tests;
- fixed-error and no-local-fallback tests for both accessor and constructor;
- ACL, RLS, migration-upgrade, backup, restore, workspace teardown, and catalog
  fingerprint checks;
- unchanged trusted-local behavior and production fail-closed behavior;
- territory-safe result projections, including withholding `unassigned_deals`,
  `exchange_status`, `list_investors`, `ic_scorecard`, and `trace_input_lineage`
  from `jv_partner` until those surfaces have a provable territory model, and
  binding `list_deal_documents` to a declared property reference and result
  contract as its two `deal_id` siblings already are;
- a locked invariant that every capability visible to a territory-limited
  profile which takes a `deal_id` and reaches a certified hosted persistence
  port declares a result territory contract;
- customer grouped-tool counts Local 8, National 10, Full Operator 20, and JV
  Partner 12, with all 274 internal capabilities retained and 165 of them
  entitled to `jv_partner`;
- PostgreSQL, full repository, compile, dependency, diff, changed-content
  credential, package, listener, and deterministic candidate gates;
- two fresh read-only reviews of one unchanged candidate hash.

## Explicit non-scope

This slice does not:

- persist saved searches, search runs, search results, or scheduled jobs;
- implement privacy exports, correction, deletion, retention, or processor
  propagation;
- certify separate local stores merely because they reference a deal ID;
- build the internal combined opportunity index;
- change OAuth, entitlement, quota, source-rights, approval, or grouped MCP
  definitions beyond the five explicit fail-closed JV capability removals and
  the one `list_deal_documents` territory binding described above;
- return a production bundle from `build_postgres_hosted_persistence`;
- migrate protected local data or introduce aliases, dual writes, shadow writes,
  reverse synchronization, or fallback;
- deploy, provision infrastructure, change DNS, activate billing, spend money,
  or use customer data;
- claim private staging, integrated security, production readiness, or public
  launch approval.
