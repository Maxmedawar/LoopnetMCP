# Phase 2 PostgreSQL implementation contract

Status: implemented foundation under test, not production approval

Branch: `feature/production-postgresql`

Base: `289241601ed6aec9fd8999a7601a22a62d4b45e1`

## Outcome and boundary

Phase 2 establishes the PostgreSQL 16 persistence and recovery foundation for
the cloud service. It supplies bounded pools, immutable migrations, a native
launch schema, exact database privileges, row-level security, health checks,
and a native dump plus clean-restore exercise.

This is not a production cutover. Existing SQLite stores remain local
compatibility and archaeology inputs. They are not cloud authority, recovery
proof, or a substitute for PostgreSQL. The protected SQLite backup and the
dirty SQLite dbops worktree remain untouched.

The application remains the primary authorization authority. It must derive a
current subject, workspace, membership, entitlement, and operation decision
before opening an authorized transaction. PostgreSQL RLS is a second barrier
against missed tenant predicates.

## Role and login contract

All application object owners are no-login group roles. Deployment creates
separate login roles and secrets outside source control. A login receives
exactly one documented group membership. PostgreSQL 16 membership options are
part of the contract: `ADMIN FALSE` and `SET TRUE` for every login, with
`INHERIT TRUE` only for app, admin, and backup logins. Migration and admission
logins require `INHERIT FALSE` both on the login and its membership.

- `medawarcre_migration`: `NOLOGIN NOINHERIT`, owns the database schema and
  application objects, and is used only after an explicit `SET ROLE`.
- `medawarcre_app`: `NOLOGIN INHERIT`, receives the minimum tenant runtime
  table, column, sequence, and helper-function privileges.
- `medawarcre_admin`: `NOLOGIN INHERIT`, receives reason-gated console reads
  and a mutation subset. OAuth bearer hashes, authorization-code binding
  material, provider identifiers, provider projections, and approval hashes
  are excluded through column ACLs. Service-owned auth and provider tables are
  not admin-mutable. It is not a substitute for a dedicated OAuth, provider,
  or worker identity.
- `medawarcre_backup`: `NOLOGIN INHERIT BYPASSRLS`, receives SELECT-only dump
  access. The bypass exists only so a complete logical backup can be made.
- `medawarcre_admission`: `NOLOGIN NOINHERIT`, receives schema usage and
  EXECUTE only on the three admission functions. Its login must also be
  `NOINHERIT` and must explicitly `SET ROLE medawarcre_admission`.
- `medawarcre_oauth`, `medawarcre_provider_ingress`,
  `medawarcre_provider_reconcile`, `medawarcre_worker`, and
  `medawarcre_scheduler`: `NOLOGIN NOINHERIT` service boundaries. Their login
  roles must also be `NOINHERIT`, receive one exact membership, and explicitly
  `SET ROLE`. They intentionally receive no object privilege until a reviewed
  migration grants execution on their narrow service functions.

Every preflight rejects superusers, `BYPASSRLS`, cluster capabilities, unsafe
or extra transitive memberships, membership-option drift, direct database,
schema, relation, column, sequence, function, type, or default privileges,
direct ownership, effective database or schema creation, and group-role drift. The
migration preflight permits only the implicit `pg_database_owner` membership
that follows from its one migration-group membership. App, admin, backup, and
admission logins cannot be used as migration logins.

Customer roles receive no privilege on internal opportunity, staff-role,
admission control-plane, integration-control, or legacy-alias data.

## Runtime pools and transaction authority

Psycopg 3 uses a bounded `ConnectionPool`. Minimum size, maximum size, maximum
waiters, acquire timeout, lifetime, idle timeout, reconnect timeout, statement
timeout, lock timeout, and idle-transaction timeout are all validated. A zero
or negative waiter bound is invalid.

New connections set UTC, pin `search_path` to `pg_catalog`, and set the
configured timeouts. Every checkout is tested,
and stale connections are discarded. Authorization context is transaction
local:

- `app.workspace_id`
- `app.actor_user_id`
- `app.internal_role`
- `app.audit_reason`

Pool reset clears every key. Missing or malformed tenant context matches no
tenant row. The public general connection API rejects missing context before a
checkout, so neither app nor admin callers can issue contextless arbitrary SQL.
An app pool rejects internal authority. An admin pool accepts only internal
authority with an exact role and a non-empty reason. Health uses two fixed,
read-only probe methods that accept no caller-supplied SQL and expose no pooled
connection.

Internal policy checks are live, not assertions from the caller. The actor must
have one active matching row in `staff_roles`. The exact staff vocabulary is
`owner`, `admin`, `jv_operations`, `support`, `security_audit`, and
`read_only_analyst`.

## Migration protocol

Ordered SQL resources are the source of truth. Version, description, and
SHA-256 are immutable. One database-local advisory lock serializes ledger
creation, validation, application, and explicit recovery.

Before DDL, a committed ledger row marks a migration running and dirty. The
DDL and transition to applied then share one transaction. PostgreSQL
transactional DDL prevents a partial success. A failed or disconnected attempt
leaves a durable dirty row and blocks every later run.

Recovery requires the failed version, its exact checksum, and an operator
reason. Applied checksum drift, description drift, version gaps, unexpected
versions, non-applied rows, or dirty rows fail closed. There are no automatic
down migrations.

The repository has no released PostgreSQL schema and this branch has not been
applied to external infrastructure. For that reason, the Phase 2 launch schema
is folded into fresh migration `0001_authoritative_cloud.sql`. Once any shared
or production-like database applies it, the file becomes immutable and every
change must be a new migration.

## Launch schema

The schema uses UUID, `timestamptz`, `date`, `jsonb`, `text[]`, `bytea`, and
bounded `numeric` types. Money does not use floating point. Tenant child rows
use composite foreign keys containing `workspace_id` so a foreign identifier
cannot silently cross tenants.

The schema covers:

- identity and tenancy: `users`, `human_identities`, `workspaces`,
  `memberships`, `staff_roles`, and `territories`;
- account and entitlement: `workspace_accounts`, `plans`, `subscriptions`,
  and `access_grants`, including invited, grace, unpaid, override, expiring,
  expired, and revoked launch states;
- OAuth persistence: `oauth_clients`, `oauth_codes`, `oauth_sessions`, and
  `oauth_refresh_history`, with only hashes stored for bearer material;
- provider persistence: `external_accounts`, `provider_events`, and
  `provider_event_attempts`;
- customer integrations: `connected_clients` and `integration_events`;
- search and deal state: `saved_searches`, `search_runs`, `search_results`,
  `deals`, `deal_notes`, `deal_outcomes`, and `deal_events`;
- the internal combined index: `internal_opportunities` and
  `internal_opportunity_sources`, retaining workspace, source record, access
  class, scoring version, observation time, and provenance;
- privacy: `consents`, `privacy_requests`, and `retention_actions`;
- staff and access accountability: `staff_audit_log` and
  `access_decision_audit`;
- admission control: `tool_approvals` and `daily_quota_usage`;
- legacy compatibility: append-only `legacy_id_aliases`;
- work execution: `jobs` and `job_attempts`, including workspace-scoped
  idempotency, lease, retry, and attempt uniqueness. Every launch job kind
  (`saved_search`, `privacy`, `provider_reconcile`, and `retention`) requires a
  non-empty idempotency key, and `(workspace_id, idempotency_key)` is unique.

Provider receipts accept nullable workspace bindings only for unmapped or
malformed events. A nullable attempt must point to a nullable event, and a
tenant-bound attempt must carry the same workspace as its event. When a
previously unmapped event is bound, its attempt rows receive that exact binding
in the same transaction. They store sanitized projections and hashes, never raw bearer secrets.
The exact outcomes are `received`, `applied`, `duplicate`, `stale`,
`quarantined`, `rejected`, `unmapped`, `malformed`, `failure`, and
`reconciled`. Duplicate count, replay time, restrictive ordering rank, external
account and stream hashes, subject and scope binding, entitlement input hash,
plan and profile output, and mapping provenance preserve reconciliation proof.

## Admission control and audit

Raw DML on `tool_approvals`, `daily_quota_usage`, and
`access_decision_audit` is denied to app, admin, backup, and admission roles.
Only the admission group can execute these `SECURITY DEFINER` functions:

- `consume_tool_approval`: atomically consumes one unexpired approval only
  when workspace, subject, session hash, tool name, argument hash, and token
  hash all match. PostgreSQL server time controls expiry. Raw approval tokens
  are never stored.
- `consume_daily_quota`: atomically increments a workspace and bucket counter
  only while the limit holds. PostgreSQL derives the date in UTC, so callers
  cannot select a different quota day.
- `record_access_decision`: records append-only admission and final decisions
  using server timestamps. A final row requires an earlier allowed admission
  row with the same invocation, authentication state, workspace, subject,
  session hash, request correlation, and tool.

Unique keys and update statements provide the concurrency boundary. Tests race
multiple real PostgreSQL sessions and prove one-time approval consumption and
quota enforcement.

Audit and alias triggers reject update and delete even for their owner. Staff
audit insertion additionally binds actor, role, and reason to the live
transaction context.

## RLS, catalog, and readiness

RLS is enabled on the exact reviewed set: every application table except
`schema_migrations`, `plans`, and `oauth_clients`. This includes global identity
and internal tables, not only tenant tables. Generic tenant policies are used
only for deliberately workspace-shared objects. Identity and object ownership
are explicit:

- a customer sees only their own `users` and `memberships` rows;
- workspace grants and the actor's subject grant are visible, but another
  subject's `access_grants` row is not;
- saved searches, search runs, search results, consents, and privacy requests
  are actor-owned;
- deal content and note bodies are deliberate workspace-shared collaboration
  records, while `deals.owner_user_id` and `deal_notes.author_user_id` are not
  customer-readable. A customer can create or mutate only an unowned or
  self-owned deal and only their own notes;
- OAuth sessions, codes, refresh history, external accounts, provider receipts,
  and job rows receive no customer ACL. Their user references use composite
  workspace-membership foreign keys and cannot cross a tenant boundary.

Internal reads require live staff authorization. The admin console has safe
metadata column grants on auth and provider tables, but cannot select credential
hashes, private mapping/projection data, or approval hashes. The mutation set
additionally requires owner or admin and excludes service-owned auth/provider
tables entirely. The backup role is the narrow, documented exception: it needs
complete SELECT access to produce a restorable archive and cannot mutate data.

Readiness verifies PostgreSQL 16 or newer, exact migration history, no dirty
row, exact table inventory, exact RLS inventory, validated foreign keys, and a
canonical SHA-256 catalog fingerprint. The fingerprint covers columns, native
types, defaults, nullability, constraints, indexes, policies, triggers,
functions, owners, contract group-role attributes and memberships, the current
database ACL, future-object default ACLs, user-defined types, sequences, and
schema, table, column, and function ACLs. A dropped index, missing policy,
extra RLS flag, altered function, default privilege change, database grant, or
role drift makes readiness false.

Diagnostics return stable codes and structural facts only. They never return a
DSN, password, token, SQL parameter, or provider payload.

## Native backup and clean restore

Backup uses a dedicated exact-authority login and native `pg_dump` custom
format. Metadata and the dump share one exported repeatable-read snapshot. The
manifest records format version, UTC timestamp, dump SHA-256 and size, tool and
server versions, migration checksums and descriptions, the catalog fingerprint,
exact table inventory, and exact row counts.

Native command discovery, version checks, PostgreSQL 16 source validation, and
the dedicated backup-login preflight all run before a temporary file is made.
Temporary files are mode `0600` and fsynced. Publication uses same-directory
hard links with no-replace semantics, followed by directory fsync. If either
member of the dump-manifest pair cannot publish, only files whose inode was
published by this run are removed. Existing destinations are never overwritten.

Restore accepts only a distinct clean migration-owned PostgreSQL 16-or-newer
database. It rejects a pre-16 or malformed source-version manifest and verifies
the archive and manifest before native `pg_restore --single-transaction` with no
owner or ACL replay, then reapplies the exact privilege contract. Verification
checks tables, row counts, ledger, foreign keys, exact RLS, active triggers,
owners, functions, group roles, database ACLs, future-object default ACLs, all
relevant object ACLs, and the canonical fingerprint.

A temporary nonce table binds dedicated app and backup smoke logins to the
restored target. App smoke proves own-tenant read and write plus cross-tenant
denial. Backup smoke proves complete reads and mutation denial. Both run with
rollback-only data changes. The binding table is removed, and the complete
catalog and row-count verification runs again.

The operator CLI accepts DSNs only through environment variables. Its JSON
results and errors never interpolate database exception text or connection
strings.

## Exact Phase 3 launch blockers

- [PHASE 3 LAUNCH BLOCKER] Provision a dedicated OAuth and authentication
  bootstrap group role, login, pool, narrow functions, ACL tests, and rotation
  procedure. Neither app nor admin may stand in for it.
- [PHASE 3 LAUNCH BLOCKER] Provision dedicated provider-ingress and provider-
  reconciliation group roles, logins, pools, narrow functions, ACL tests, and
  replay operations. Neither app nor admin may stand in for them.
- [PHASE 3 LAUNCH BLOCKER] Provision distinct cross-tenant worker and scheduler
  roles, pools, claim functions, lease recovery rules, and ACL tests. The admin
  role is not an implicit worker identity.
- [PHASE 3 LAUNCH BLOCKER] Replace every authoritative OAuth, provider,
  entitlement, access registry, audit JSONL, and cloud persistence call site
  with the reviewed PostgreSQL repositories and admission functions.
- [PHASE 3 LAUNCH BLOCKER] Boot the real service and all required endpoints
  against a restored PostgreSQL target using only their dedicated service
  logins. The Phase 2 synthetic smoke is necessary but does not prove this.
- [PHASE 3 LAUNCH BLOCKER] Prove worker restart and lease recovery on restored
  PostgreSQL, including no duplicate execution for idempotent jobs.
- [PHASE 3 LAUNCH BLOCKER] Provision and exercise base backups plus continuous
  WAL archiving, retention, restore points, and target-time recovery. No RPO or
  RTO is claimed until timed infrastructure evidence exists.
- [PHASE 3 LAUNCH BLOCKER] Define the supported legacy API version, implement
  alias lookup at that boundary, and document the expiry or removal policy.
- [PHASE 3 LAUNCH BLOCKER] Complete provider-specific OAuth bootstrap,
  signature verification, event mapping, test-mode reconciliation, and
  restrictive stale-event behavior with real provider fixtures.

## Explicit non-scope

Phase 2 does not:

- modify the protected SQLite backup, import real customer data, or change the
  dirty SQLite dbops worktree;
- claim that production services, OAuth, providers, admission middleware, or
  workers currently use PostgreSQL;
- remove trusted local stdio SQLite compatibility;
- build the customer connection page, Operations Console, provider adapters,
  full privacy processors, or public deployment;
- expose internal opportunities through customer APIs or MCP tools;
- enable global learning or place private data in a training path;
- provision a cloud database, object store, WAL archive, monitoring service,
  DNS, production secret, or paid resource;
- choose production retention, certify PITR, claim an RPO or RTO, perform a
  destructive rollback, or authorize production cutover.

The package runtime floor is Python 3.11. The repository uses `datetime.UTC`
across production modules, so advertising Python 3.10 would be false.

## Required audit proof

Before this foundation can be handed to the next phase, retain evidence for:

1. real disposable PostgreSQL migration, dirty recovery, checksum, gap,
   concurrent runner, and unsafe-login rejection tests;
2. real RLS, composite-key, live staff-role, exact privilege, approval race,
   quota race, audit linkage, alias immutability, and job-idempotency tests;
3. stale pooled-connection recovery and exact catalog-drift readiness tests;
4. native backup and restore into a second cluster, plus bound app and backup
   smoke identities and post-smoke re-verification;
5. focused tests, related regressions, full suite, compile checks,
   `git diff --check`, source scans, secret scans, and artifact cleanup;
6. a fresh read-only implementation audit, repairs, and a second independent
   audit before any commit, deployment, or green launch status.
