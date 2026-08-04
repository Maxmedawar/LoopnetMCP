# Phase 3 atomic admission repository contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `2c307451b98a333a109d0e30bffa15978fa282d3`

## Outcome and boundary

This checkpoint replaces the three independently callable PostgreSQL admission
primitives with one request-admission transaction and one bound final-audit
operation. It also supplies the dedicated synchronous repository that a later
hosted middleware checkpoint will call through a worker thread.

The admission transaction is the only runtime operation allowed to mutate an
approval, mutate daily quota, or create an admission audit row. It revalidates
the current OAuth session, user, workspace, membership, account, entitlement,
plan, and territory snapshot before any state is consumed.

This checkpoint does not certify the hosted persistence bundle. Public HTTP
startup remains fail closed until middleware wiring and every request-scoped
domain repository required by the customer surface pass their own parity and
isolation gates.

## Canonical request binding

Approval binding uses only the arguments that survive server-side identity and
storage-path sanitization. The canonical value is strict JSON:

- mappings are exact dictionaries with non-empty string keys;
- arrays are exact lists;
- scalars are `null`, booleans, strings, finite JSON numbers, and integers;
- tuples, sets, bytes, custom mapping subclasses, non-string keys, non-finite
  numbers, and arbitrary object stringification are rejected;
- object keys are sorted, insignificant whitespace is omitted, non-ASCII text
  is encoded directly as UTF-8, and SHA-256 produces the 32-byte binding.

The server and the future operator approval issuer must use the same helper.
Raw arguments and raw approval tokens are never stored or written to audit.

## Atomic admission operation

`medawarcre.atomic_admit_tool_call` receives server-generated invocation and
request-correlation UUIDs plus the server-resolved workspace public ID, actor
UUID, OAuth session UUID, expected profile, expected plan, expected territory
array, exact capability ID, canonical argument hash, optional quota bucket,
approval requirement, and optional approval-token hash.

Under one PostgreSQL statement and transaction it:

1. resolves the exact live OAuth session and its workspace and actor binding;
2. applies the same current user, workspace, membership, account, grant, plan,
   provider-lease, and grant-precedence rules as OAuth authority resolution;
3. compares the live profile, plan, and ordered territory snapshot with the
   values used by request policy checks, denying authority drift;
4. locks and validates the exact unexpired, unrevoked, unspent approval when
   the capability requires one;
5. increments the UTC daily quota only if the live plan limit permits it;
6. consumes the approval only after quota admission succeeds;
7. writes exactly one append-only admission audit row with the canonical
   argument hash and a safe reason code;
8. returns a small typed decision without exposing database exception text.

No denial consumes approval or quota. Concurrent calls cannot spend one
approval twice or exceed a quota. Every effective request and policy input is
covered by a stored 32-byte admission-binding hash. Retrying the same invocation
with identical bindings returns the existing decision without consuming state
twice. Reusing an invocation with any different identity, authority, tool,
argument, quota, approval, or approval-token binding fails closed.

The return value marks a cached decision as `replayed` and reports whether a
final audit already exists. Only a fresh, non-replayed allow owns execution.
Middleware must never execute a replay, whether finalized or still unresolved;
until a durable result cache exists, it fails that retry closed. This execution
ownership rule prevents an idempotent admission lookup from becoming a second
tool execution.

An approval-required response uses its invocation UUID as the opaque approval
request ID. A later operator-control checkpoint may grant that same opaque
value by storing only its SHA-256 token hash with the exact audited subject,
session, tool, and argument bindings. This checkpoint does not add an operator
grant endpoint or pretend that an approval can yet be issued in hosted mode.

## Final decision audit

`medawarcre.record_tool_call_final` accepts only a server-held allowed admission
binding. It writes `succeeded` or `failed` with the same invocation, workspace,
actor, session correlation, request correlation, and tool. A final row cannot
exist without a matching allowed admission. Identical retries are idempotent;
conflicting retries fail closed. Audit rows remain append-only.

## Database authority

The `medawarcre_admission` group remains `NOLOGIN NOINHERIT`. Its exact object
authority becomes schema usage and EXECUTE on only:

- `atomic_admit_tool_call`;
- `record_tool_call_final`.

Runtime EXECUTE is revoked from `consume_tool_approval`,
`consume_daily_quota`, and `record_access_decision`. The repository preflight
validates the group role's exact function ACL as well as the login's membership
and privilege boundary. Pool reset performs `RESET ROLE`, pins `pg_catalog`,
and commits before reuse.

## Repository contract

`PostgresAdmissionRepository` has its own bounded pool and reads only
`MEDAWARCRE_ADMISSION_DATABASE_URL` plus the
`MEDAWARCRE_ADMISSION_POSTGRES_*` bounds. It never accepts the app, admin,
OAuth, migration, backup, provider, worker, or scheduler DSN as a substitute.

The repository hashes a raw approval token in memory, calls only the two fixed
functions, validates every returned field, redacts its DSN from `repr` and all
raised errors, and fails closed on role drift, pool failure, malformed database
output, or conflicting invocation reuse.

Daily quota keys are canonical only when they exactly match the bounded ASCII
identifier grammar `^[a-z][a-z0-9_]{0,63}$`. Neither authority resolution nor
admission strips or normalizes a key. A plan containing spaces, control
characters, Unicode whitespace, uppercase text, punctuation, or colliding
normalized forms is invalid rather than silently treated as an unlimited
missing bucket. Usage dates are derived explicitly in UTC.

The repository will submit a final audit only for the fresh execution owner.
It rejects both replayed and already-finalized outcomes before database access,
including an unresolved replay that otherwise appears allowed.

## Required evidence

- deterministic canonicalization and rejection tests;
- fresh migration and upgrade-from-`0002` tests;
- real PostgreSQL live-authority drift tests;
- approval mismatch, expiry, revocation, one-time, and concurrent-spend tests;
- quota zero, boundary, UTC, unlimited, and concurrent-limit tests;
- denial-no-mutation tests for every failure class;
- admission and final audit binding, idempotency, and append-only tests;
- exact login and group-function ACL drift tests;
- backup, clean restore, catalog fingerprint, readiness, compile, packaging,
  full repository, diff, and secret scans;
- two fresh read-only reviews of one unchanged candidate hash.

## Explicit non-scope

This checkpoint does not:

- enable hosted HTTP startup or replace the current fail-closed bundle builder;
- add an operator approval grant endpoint, approval UI, notification, or email;
- port search, deal, provider, job, privacy, document, or truth-asset state;
- change trusted local stdio behavior or its local approval workflow;
- dual write, shadow write, fall back to JSON, JSONL, SQLite, or local blobs;
- deploy, provision a database, change DNS, activate billing, spend money, or
  use customer data;
- claim private staging, integrated security, production readiness, or public
  launch approval.
