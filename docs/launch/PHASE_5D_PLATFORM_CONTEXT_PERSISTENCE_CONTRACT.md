# Phase 5D hosted platform-context persistence contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `fb505a39d2d1172938440103d8acf6ff323a69e0`

## Outcome and boundary

This slice replaces the hosted platform domain marker with a narrow PostgreSQL
read authority for the current admitted actor and workspace. It exposes one
coherent platform-context snapshot containing the actor, workspace, active
membership, workspace account, optional workspace plan, and workspace
territories. It does not expose another actor or workspace.

Trusted local stdio keeps `PlatformRepository` and its existing SQLite
behavior. Hosted execution cannot construct that local repository or fall back
to it after a missing lease, missing row, malformed result, or database error.

This request-scoped port does not replace the process-level OAuth authority,
connection routes, internal administration, provider synchronization, search,
deal, privacy, or job repositories. Those authorities retain separate contracts
and remain fail closed or uncertified as recorded in the program ledger.

## Exact request authority

`PostgresPlatformRepository` is constructed from one app database and one exact
fresh allowed admission. Every operation requires that exact object to be the
platform port in the active aggregate repository lease. The active untrusted
`TenantContext` must match the admission workspace, actor, and OAuth session.

Every database read uses `PostgresDatabase.admitted_connection`. PostgreSQL
derives the internal workspace UUID and actor UUID from the admitted invocation
and transaction-local RLS settings. Method arguments cannot choose a workspace,
actor, membership, plan, or territory.

A captured repository reference is invalid after the lease ends. A detached
task retaining an untrusted context cannot construct or recover the local
SQLite repository. Cancellation cannot leave a database worker running after
the request lease unwinds.

## Snapshot contract

The snapshot is all-or-nothing for the actor, workspace, active membership, and
workspace account. Their identifiers and state must match the admitted request.
The workspace plan may be absent. If present, its key, name, price, seat limit,
and quota object must be valid. Territories are workspace-shared, ordered
deterministically, and contain only canonical identifiers and declared fields.

UUIDs remain native string identifiers. No global integer compatibility alias
is introduced. Timestamps are normalized to UTC ISO 8601 strings. Daily quota
keys use the existing canonical quota grammar and limits are non-negative
integers. Numeric plan prices must be finite and non-negative.

Any missing required row, duplicate cardinality, malformed UUID, invalid state,
invalid quota, invalid timestamp, unexpected type, inactive scope, or database
failure raises the same fixed platform-context unavailable error. Reads never
convert a failure into an empty or partial success.

## Database and privilege contract

The repository uses only existing certified schema and RLS boundaries:

- `users`: current actor only;
- `workspaces`: current workspace only;
- `memberships`: current actor in the current workspace only;
- `workspace_accounts`: current workspace only;
- `plans`: migration-managed read-only catalog;
- `territories`: current workspace only.

The app role receives no new mutation privilege. Existing backup and restore
contracts remain unchanged. The production builder remains fail closed until
all remaining hosted domain repositories are certified and wired together.

## Required evidence

- RED import and behavior tests before implementation;
- exact active-port, admission, actor, workspace, and session binding tests;
- native PostgreSQL current-actor and cross-workspace RLS isolation tests;
- complete snapshot, optional-plan, deterministic-territory, and malformed-read
  tests;
- detached-reference, detached-factory, cancellation, fixed-error, and no-local-
  fallback tests;
- unchanged trusted-local platform behavior and customer surface counts;
- PostgreSQL, full repository, compile, dependency, diff, changed-file secret,
  package, production fail-closed, listener, and deterministic candidate gates;
- two fresh read-only reviews of one unchanged candidate hash.

## Explicit non-scope

This slice does not:

- mutate users, workspaces, memberships, accounts, plans, or territories;
- port connected-client or integration-event control-plane mutations;
- port provider, search, deal, privacy, or job state;
- change OAuth, entitlement, profile, territory, or MCP surface semantics;
- return a production bundle from `build_postgres_hosted_persistence`;
- migrate protected local data or introduce aliases, dual writes, shadow writes,
  reverse synchronization, or fallback;
- deploy, provision infrastructure, change DNS, activate billing, spend money,
  or use customer data;
- claim private staging, integrated security, production readiness, or public
  launch approval.
