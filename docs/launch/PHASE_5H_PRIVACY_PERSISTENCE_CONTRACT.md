# Phase 5H hosted privacy persistence contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `49adb9e` (Phase 5G deal persistence)

## Outcome and boundary

This slice replaces the hosted privacy-domain marker with one request-scoped
PostgreSQL authority for the consent and privacy-request record surface the
platform repository exposes: `record_consent`, `get_consent`, `list_consents`,
`latest_consent`, `open_privacy_request`, `get_privacy_request`,
`list_privacy_requests`, and `update_privacy_request`.

Every hosted path that uses this surface must receive the injected privacy
repository. It cannot construct the combined local SQLite `PlatformRepository`,
reach another domain port, or recover a process-global store. Trusted local
stdio retains the existing SQLite schema, integer identifiers, and result
behavior.

This slice persists the **record** of consent and of a privacy request. It does
not implement the fulfilment behaviour those records describe. Export,
correction, deletion, retention sweeps, and processor propagation remain the
separate open privacy-and-retention work item and stay fail closed.

## Actor semantics — the material difference from Phase 5G

Deal records are collaborative workspace state. Privacy records are **not**.
A consent is a statement by one identified person, and a privacy request is a
request about one identified person's own data. Both are actor-private:

- a member may read and write only their own consents and their own privacy
  requests;
- no customer capability may enumerate another member's consents or requests,
  or learn that one exists, even inside a shared JV workspace;
- workspace membership alone never confers read access to another member's
  record;
- staff or internal review of another person's request is an internal-only
  authority and is out of this slice's customer surface entirely.

The repository never accepts a workspace, actor, or subject selector from a
method argument. PostgreSQL derives all three from the admitted transaction and
RLS. Every returned row repeats or joins the authoritative workspace public ID
and the actor UUID, and both are validated against the admission before the row
is released. A cross-actor or cross-workspace identifier returns no record and
never discloses whether the object exists.

## Exact request and method authority

`PostgresPrivacyRepository` is constructed from one app database and one exact
fresh allowed admission. Every method requires that exact object to be the
privacy port in the active aggregate repository lease, and the active untrusted
`TenantContext` must match the admission workspace public ID, actor UUID, and
OAuth session UUID. A captured reference becomes invalid when the lease exits.

Method authority is capability-specific and closed by default, and — per the
Phase 5G finding that a granted method with no matching projection is a silent
break — **every capability granted a method must also be proven to receive a
result it can actually use.** A locked test must enumerate the authority map
and assert each entry against a real hosted call, not a local-store fake.

Reads recheck exact active authority after their statements and after worker
completion. Writes recheck inside the transaction after DML and before commit.
Cancellation waits for the synchronous database worker before the request lease
can unwind. Missing, stale, mismatched, malformed, revoked, or unavailable
authority fails with only `privacy persistence unavailable`; it is never
converted to an empty hosted success or a local fallback.

## Data and transaction contract

Consent is append-only evidence. A recorded consent is never updated or
deleted by any application path; a withdrawal is a new row with `granted`
false, and `latest_consent` resolves the current position by ordering. The
application role therefore receives no UPDATE or DELETE privilege on
`consents`.

A privacy request is a small state machine over `received`, `verified`,
`in_progress`, `completed`, `rejected`, and `canceled`. Only the transitions
the product actually supports may be accepted; `completed_at` may be set only
with a terminal status, and a terminal request may not be reopened. Status
changes and their timestamps are one transaction.

`consent_type`, `kind`, `status`, versions, and detail text are strictly typed,
bounded, and validated again on read. Malformed timestamps, invalid enum
values, oversized content, and inconsistent actor or workspace projections fail
closed. Multi-statement reads run at REPEATABLE READ so they return one
coherent snapshot; lock-and-mutate writes stay at READ COMMITTED.

## Database authority and migration

Migration `0009` must narrow or extend `consents`, `privacy_requests`, and
`retention_actions` without weakening workspace RLS, and must add actor-scoped
RLS so a member cannot read another member's rows. Application-role privileges
are limited to the exact columns and operations the repository needs, with no
UPDATE or DELETE on `consents`. Every relation keeps workspace teardown
behaviour and explicit backup and reasoned-admin authority.

Any row predating `0009` must remain readable and usable afterwards, or be
provably absent. Phase 5G shipped a migration that left legacy rows visible but
permanently unwritable, and a second where one undecodable row denied an entire
workspace's list; both are prohibited outcomes here.

## Required proof

Before commit, this phase requires:

- a missing-module RED test before implementation;
- native PostgreSQL parity tests for every privacy method reached by a
  customer or internal capability;
- exact admission, method, port, workspace, actor, OAuth session, detached
  reference, in-flight revocation, cancellation, and pre-commit rollback tests;
- **cross-actor isolation inside one shared workspace** — the central property
  of this domain — including direct-object-ID probes proving non-disclosure;
- append-only consent proof, including that no application path can update or
  delete a consent row, enforced by ACL and not only by code;
- privacy-request state-machine tests covering every accepted transition, every
  rejected transition, terminal immutability, and `completed_at` coupling;
- bounded and malformed input and stored-row tests on both write and read;
- fixed-error and no-local-fallback tests for both accessor and constructor;
- ACL, RLS, migration-upgrade, backup, restore, workspace teardown, and catalog
  fingerprint checks;
- unchanged trusted-local behaviour and production fail-closed behaviour;
- an authority-to-result lock proving every granted capability receives a
  usable result through the real hosted port;
- **mutation evidence**: every new pin must be shown to fail when the behaviour
  it claims to pin is deleted. A green suite is not accepted as proof. Phase 5G
  produced three defects that a fully green suite concealed;
- PostgreSQL, full repository, compile, dependency, diff, changed-content
  credential, package, listener, and deterministic candidate gates;
- two fresh read-only reviews of one unchanged candidate hash.

## Explicit non-scope

This slice does not:

- implement export, correction, deletion, retention execution, or processor
  propagation;
- add or change customer-visible MCP capabilities, profiles, or counts;
- build the internal staff review surface for another person's request;
- certify separate local stores merely because they reference a user ID;
- repair the open LedgerStore-backed JV territory blocker, which is tracked
  separately and must be fixed before hosted launch;
- return a production bundle from `build_postgres_hosted_persistence`;
- migrate protected local data or introduce aliases, dual writes, shadow
  writes, reverse synchronization, or fallback;
- deploy, provision infrastructure, change DNS, activate billing, spend money,
  or use customer data;
- claim private staging, integrated security, production readiness, or public
  launch approval.
