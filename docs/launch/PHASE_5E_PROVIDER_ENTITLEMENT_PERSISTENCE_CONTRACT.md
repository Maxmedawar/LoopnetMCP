# Phase 5E hosted provider-entitlement persistence contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `7a03724e7ec39dd6d08bfe2d7ebc739bcbb898b6`

## Outcome and boundary

This slice replaces the hosted provider-domain marker with one narrow,
read-only PostgreSQL authority for the current admitted actor and workspace. It
returns a coherent entitlement snapshot containing tenant-visible subscription
projections, workspace grants, and grants belonging to the admitted actor.

The snapshot never exposes external subscription, customer, grant, account, or
event identifiers. It does not expose provider payloads, receipt hashes,
webhook journals, reconciliation attempts, or another actor's subject grant.

Trusted local provider ingress, reconciliation, administration, and test
workflows keep their existing process-level services. Hosted customer execution
cannot construct the local SQLite `EntitlementStore` or fall back to it after a
missing lease, malformed result, cancellation, or database failure.

## Exact request authority

`PostgresProviderRepository` is constructed from one app database and one exact
fresh allowed admission. Every operation requires that exact object to be the
provider port in the active aggregate repository lease. The active untrusted
`TenantContext` must match the admission workspace, actor, and OAuth session.

Every read uses `PostgresDatabase.admitted_connection`. PostgreSQL derives the
internal workspace UUID and actor UUID from the admitted invocation and
transaction-local RLS settings. The method accepts no workspace, actor,
provider, grant, subscription, or time selector.

A captured reference is invalid after the lease ends. A detached task cannot
retain provider authority or recover local SQLite state. Cancellation cannot
leave a database worker running after the request lease unwinds.

## Snapshot contract

One SQL statement returns a request-scope identity row and all visible
subscription and access-grant projections under one statement snapshot. The
scope row must match the admitted actor. Every data row must repeat the same
internal workspace and actor identifiers.

Subscriptions are ordered by provider and UUID. They include only provider,
status, plan key, current-period end, last-event time, and lifecycle timestamps.
Access grants are ordered by source, scope, and UUID. They include only visible
scope, source, profile, optional plan key, status, subject identity when scoped
to the current actor, lease bounds, and lifecycle timestamps.

The repository validates UUIDs, UTC timestamps, canonical providers, sources,
statuses, scopes, profiles, row shapes, scope/source invariants, provider lease
bounds, duplicate identifiers, and deterministic order. An empty entitlement
set is valid. A malformed, partial, duplicated, mismatched, or incoherent result
fails with only `provider persistence unavailable`.

## Database authority

The app role retains column-level SELECT only on declared safe projections of
`subscriptions` and `access_grants`. Existing RLS limits subscriptions to the
current workspace and grants to workspace scope or the current actor. The app
role has no provider-domain mutation authority and no access to external hashes,
provider events, external accounts, or reconciliation state. The backup role
retains read access.

No migration is required for this slice. Existing provider-ingress and
provider-reconciliation roles remain separate dormant service authorities.

## Required proof

Before commit, this phase requires:

- a missing-module RED test before implementation;
- native PostgreSQL complete, empty, deterministic, and one-statement coherence
  tests;
- current-actor, cross-actor, and cross-workspace RLS isolation tests;
- exact admission, active-port, actor, workspace, session, detached-reference,
  in-flight lease-revocation, and cancellation tests;
- exact untrusted context propagation during hosted repository binding, with
  local provider-store construction denied before any customer tool executes;
- malformed-row, fixed-error, sensitive-field, read-only ACL, backup, and no
  local-fallback tests;
- unchanged trusted-local provider behavior and customer surface counts;
- PostgreSQL, full repository, compile, dependency, diff, changed-file secret,
  package, production fail-closed, listener, and deterministic candidate gates;
- two fresh read-only reviews of one unchanged candidate hash.

## Explicit non-scope

This slice does not:

- ingest or acknowledge Stripe or Skool webhooks;
- reconcile provider events or mutate subscriptions, grants, or accounts;
- expose raw provider identifiers, hashes, payloads, event journals, attempts,
  or external accounts;
- merge customer request authority with provider-ingress or reconciliation
  service roles;
- change OAuth admission, entitlement selection, profile, plan, territory,
  quota, source-rights, or MCP surface semantics;
- return a production bundle from `build_postgres_hosted_persistence`;
- migrate protected local data or introduce aliases, dual writes, shadow writes,
  reverse synchronization, or fallback;
- deploy, provision infrastructure, change DNS, activate billing, spend money,
  or use customer data;
- claim private staging, integrated security, production readiness, or public
  launch approval.
