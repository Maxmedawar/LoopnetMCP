# Phase 5F hosted search persistence contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `cef768f26712212113f329019b6886ea49aec990`

## Outcome and boundary

This slice replaces the hosted search-domain marker with one request-scoped
PostgreSQL authority for customer saved searches and on-demand new-match
suppression. The hosted search port supports creating, reading, and listing the
current actor's saved searches, reading their seen keys, and atomically claiming
new seen keys. It does not persist deals or run scheduled searches.

Hosted saved-search tools use a dedicated search accessor. They cannot reach the
combined local SQLite `DealStore`, the hosted deal port, or a process-global
fallback. Trusted local stdio retains the existing SQLite store and integer
identifiers.

Hosted saved-search identifiers are native opaque UUID strings. No global
integer alias, enumeration sequence, cross-tenant lookup, or local-to-hosted
identifier translation is introduced. Customer result models accept both local
integers and hosted UUID strings without changing the visible tool or action
count.

## Exact request authority

`PostgresSearchRepository` is constructed from one app database and one exact
fresh allowed admission. Every operation requires that exact object to be the
search port in the active aggregate repository lease. The active untrusted
`TenantContext` must match the admission workspace, actor, and OAuth session.

Method authority is narrow. `save_search` requires a `save_search` admission.
`list_searches` accepts `list_searches` or `check_alerts`. `get_search`,
`seen_keys`, `claim_unseen`, and compatibility `record_seen` require
`check_alerts`. An admission for another capability cannot be repurposed.

Every database operation uses `PostgresDatabase.admitted_connection`.
PostgreSQL derives the internal workspace and actor UUIDs from the admitted
invocation and transaction-local RLS. Callers cannot supply an owner or
workspace. A captured reference is invalid after the lease ends. Detached tasks
cannot retain authority. Cancellation waits for the database worker before it
can unwind the request lease.

Writes recheck the exact active scope inside the transaction after DML and
before commit. Reads recheck after their statement and after worker completion.
Missing, stale, mismatched, revoked, malformed, or unavailable authority fails
with only `search persistence unavailable`.

## Saved-search and seen-match contract

A saved search contains one trimmed bounded name, one exact bounded query
object, an optional finite score from 0 through 100, active state, and UTC
lifecycle timestamps. The hosted query shape is limited to location, strategy,
property type, price and size bounds, and a nonempty ordered list of source IDs.
Unexpected keys, invalid scalar types, duplicate sources, invalid ranges,
non-finite numbers, oversized content, or malformed database rows fail closed.

Listings are deterministic by creation time and UUID. Each projected row repeats
the RLS-derived workspace and owner identities, which must match the admission.
Reads return no schedule value and cannot observe another actor's search, run,
result, or seen key.

Seen keys are trimmed, unique, bounded source-qualified strings. `claim_unseen`
inserts a materialized bounded set with `ON CONFLICT DO NOTHING` and returns only
the keys inserted by that transaction. Concurrent on-demand checks therefore
cannot emit the same key twice. The legacy `record_seen` count remains available
for local and internal compatibility, but the customer tool emits only keys
returned by the atomic claim.

Before any provider execution or seen-key claim, `check_alerts` preflights the
complete selected saved-search set, including every territory boundary. A stale
later search therefore cannot discard an earlier result after its key was
claimed. Runtime failures are isolated to their search and cannot erase results
already returned for another search.

## Database authority and migration

Migration `0007` adds `saved_search_seen_matches`, including workspace, owner,
saved-search, and dedupe-key integrity. Actor-owned RLS permits the app role to
select and insert only its own rows. The app role cannot update or delete the
ledger. Backup read authority and reasoned internal administration are retained.

The migration also narrows saved-search app authority to actor-owned select and
insert. The app role has neither policy nor table privilege to update or delete
saved searches because this slice exposes no such lifecycle operation.

The migration replaces workspace-wide saved-search name uniqueness with
workspace-and-owner uniqueness. Two actors in one workspace may use the same
private name, so a unique violation cannot reveal another actor's saved-search
name. It adds saved-search data checks and a composite owner key used by the
seen-match foreign key.

Existing `search_runs` and `search_results` remain worker-owned and read-only to
the app role under actor-owned RLS. This phase grants no customer write access to
those tables and does not activate worker or scheduler service roles.

## Required proof

Before commit, this phase requires:

- a missing-module RED test before implementation;
- native PostgreSQL create, get, list, deterministic order, opaque UUID, and
  atomic seen-claim tests;
- current-actor, cross-actor, cross-workspace, same-private-name, and object-ID
  isolation tests;
- exact admission, method, port, workspace, actor, session, detached-reference,
  in-flight lease-revocation, cancellation, and pre-commit rollback tests;
- malformed input and row, duplicate and oversized key, fixed-error, ACL,
  migration, backup, restore, and no-local-fallback tests;
- concurrent claim tests proving one total emission per dedupe key;
- hosted UUID tool compatibility and unchanged trusted-local integer behavior;
- unchanged source-rights, territory, customer surface, and production
  fail-closed behavior;
- PostgreSQL, full repository, compile, dependency, diff, changed-file secret,
  package, listener, and deterministic candidate gates;
- two fresh read-only reviews of one unchanged candidate hash.

## Explicit non-scope

This slice does not:

- schedule or execute background searches, create jobs, or activate workers;
- let the app role write `search_runs` or `search_results`;
- persist, mutate, score, assign, or expose deals, notes, outcomes, or events;
- build the internal combined opportunity index;
- change OAuth, entitlement, profile, quota, territory, source-rights, approval,
  or grouped MCP surface semantics;
- return a production bundle from `build_postgres_hosted_persistence`;
- migrate protected local data or introduce aliases, dual writes, shadow writes,
  reverse synchronization, or fallback;
- deploy, provision infrastructure, change DNS, activate billing, spend money,
  or use customer data;
- claim private staging, integrated security, production readiness, or public
  launch approval.
