# Phase 5 request-scoped domain persistence contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `7be60ef05d1aa245d4e03d4717460897261ff371`

## Outcome and boundary

This phase replaces hosted customer-domain file state with explicit PostgreSQL
repositories. The first independently certifiable slice establishes the
request-scoped authority boundary shared by every later domain port. Production
hosted startup remains fail closed until platform, provider, search, deal,
privacy, job, document, and truth-asset repositories all pass parity and
isolation tests.

Trusted local stdio keeps its existing SQLite, JSON, JSONL, and local-blob
behavior. Hosted HTTP cannot construct those stores, translate their SQL, or
fall back to them after a PostgreSQL error or miss.

## Exact request binding

One hosted domain scope is created only after policy checks and one fresh atomic
`allowed` admission. It is bound to the exact invocation UUID, request UUID,
workspace public ID, actor UUID, OAuth session UUID, and internal capability ID.
Replayed, finalized, denied, malformed, or mismatched admissions cannot create a
domain scope.

The PostgreSQL app transaction resolves its internal workspace UUID only through
a fixed-search-path security-definer function that proves the same admission
row. The function must also prove that no final row exists, then set
transaction-local RLS workspace and actor values. Public workspace input,
ambient configuration, MCP arguments, and repository method parameters never
select tenant authority.

Domain binding and final-audit insertion take the same transaction-level
advisory lock derived from the invocation UUID. A final audit therefore cannot
commit while an admitted domain transaction remains active, and a binding that
waits behind finalization must recheck and reject the committed final row.

## Hosted repository injection

Hosted middleware requires one explicit domain provider in addition to OAuth,
admission, audit, and platform services. The provider receives the exact fresh
admission off the event-loop thread and must return all eight named domain
repositories bound to that admission. The scope is visible only during tool
execution and is reset on success, denial, exception, and cancellation. Scope
leases are actively revoked on exit so a detached asyncio task cannot retain a
copied ContextVar authority. The document port is also bound into the existing
source-rights attestation scope for exactly the same revocable lifetime.

Factories used by hosted tools resolve only the injected repository. Direct
construction of a local persistent store during an active hosted domain scope
fails closed. Missing repositories and provider failures produce one fixed safe
error and a bound failed final audit. They do not create local directories or
files.

## Transaction and failure requirements

Every PostgreSQL repository operation uses the admitted request connection
boundary and PostgreSQL RLS. A binding miss, database error, malformed result,
or unavailable repository raises a fixed persistence error. No hosted
repository converts a failure to an empty success, retries through a local
store, dual writes, shadow writes, or reverse synchronizes file state.

Later domain slices must preserve each public tool result contract while using
native PostgreSQL identifiers internally. Any compatibility identifier must be
explicit, workspace-scoped, immutable, and tested. Opaque SQLite state in JSONB
is prohibited.

## Required evidence for this authority slice

- RED tests for missing hosted provider, missing repository, replayed admission,
  finalized admission, direct local-store construction, and context leakage;
- native PostgreSQL tests proving exact admission binding, RLS isolation,
  final-row rejection, wrong-field rejection, role grants, and pool reset;
- proof that provider binding runs off the event loop and only around execution;
- unchanged trusted-local behavior and unchanged customer tool counts;
- migration, catalog fingerprint, restore privilege, backup and restore,
  package, compile, diff, secret, and full-repository gates;
- two fresh read-only reviews of one unchanged candidate hash.

## Explicit non-scope

This first slice does not:

- return a production bundle from `build_postgres_hosted_persistence`;
- claim parity for any of the eight customer-domain repositories;
- change the public MCP tool surface or customer entitlement counts;
- migrate or copy protected local data;
- permit SQLite, JSON, JSONL, local-blob, dual-write, shadow-write, reverse-sync,
  or fallback behavior in hosted execution;
- deploy, provision infrastructure, change DNS, activate billing, spend money,
  or use customer data;
- claim private staging, integrated security, production readiness, or public
  launch approval.
