# Stripe and Skool Provider Synchronization

Status: provider-neutral foundation repaired, production enablement blocked

Base: `7cbb1ac1aed6e059ef7282ca0f6e45d4846eac07`

This worktree contains a provider-neutral entitlement synchronization
foundation. It is not a production Skool churn integration. Do not commit,
push, deploy, enable either provider route, add credentials, poll a provider,
or contact an external system from this phase.

## Locked product authority

The `$197/month` `skool.com/cre` membership grants CRE MCP access to one
individual only while that individual is an active paying member.

- Durable authority is a server-owned `subject_user_id`.
- Email and client claims are never authority keys.
- Provider grants are filtered to the authenticated user.
- Provider, manual, and promotion grants are exact-subject authority.
- JV grants are workspace authority only when `scope=workspace` is explicitly
  requested. All other grants use `scope=subject`.
- A trusted cancellation, removal, ban, payment failure, pause, deleted
  subscription, or loss-of-paid-level signal revokes the provider grant
  immediately.
- Payment failure has no dunning or grace access.
- Restrictive events derive their target from the existing external-account,
  subscription, and grant state. They never require a current price or level
  mapping.
- Unknown positive plan metadata quarantines without granting.
- When a subject loses the final live applicable grant, the same
  `BEGIN IMMEDIATE` transaction revokes OAuth sessions, consumes pending
  authorization codes, and therefore invalidates access and refresh authority.
- Another live grant that applies to the exact subject preserves that
  subject's OAuth authority.

## Provider grant expiry

Every Stripe and Skool grant has a server-owned `ends_at`.

`provider_grant_lease_seconds`:

- defaults to 24 hours;
- must be from 1 second through 7 days;
- is not supplied by a webhook;
- supplies the Stripe fallback only when a trusted `current_period_end` is
  absent;
- bounds relay grants until another trusted positive reaffirmation.

For Stripe, a valid trusted `current_period_end` is authoritative and becomes
`ends_at`, even when it is longer than the fallback lease. Without that period,
Stripe falls back to the configured lease. Stripe `trialing` is non-granting
and cannot confer the paid entitlement. For the relay, `ends_at` is always the
lease end. Lease expiry denies CRE MCP and `/v1` without another event. A lease
is a stale-authority bound. It is not an instant cancellation feed and must
never be described as one.

## Trust boundary

The provider adapters only parse allowlisted data. Request data never selects a
workspace or user. Provider identity resolves through one exact server-owned
mapping:

```text
(provider, external_account_id) -> (workspace_id, subject_user_id)
```

Generic external-account CRUD accepts any normalized safe provider slug.
Provider synchronization is limited to `stripe` and `skool`, and those mappings
must identify an exact current workspace member. Ambiguous, missing, unbound,
or cross-workspace synchronization state fails closed.

The supported relay event types are:

- `member.added`
- `member.updated`
- `member.removed`
- `member.canceled`
- `member.payment_failed`
- `member.banned`

The final four restrictive meanings are mapping-free. `member.updated` with an
unmapped or non-entitled level revokes an existing linked member grant. The
same event without existing linked provider authority quarantines and grants
nothing.

Stripe deletion, pause, canceled, unpaid, past-due, grace-period, and invoice
payment-failure states are restrictive. Missing, retired, empty, or unmapped
prices cannot prevent revocation of existing linked authority.

## Webhook ingress

Routes:

- `POST /v1/webhooks/stripe`
- `POST /v1/webhooks/skool`

Both routes remain fixed 404 when their secret is unset. In particular,
`skool_webhook_secret` must remain unset outside isolated tests.

The public environment contract is documented with non-secret examples in
`.env.example`:

- `CRE_STRIPE_WEBHOOK_SECRET`
- `CRE_SKOOL_WEBHOOK_SECRET`, which remains unset
- `CRE_PROVIDER_WEBHOOK_MAX_BODY_BYTES`, from 1 through 65,536
- `CRE_PROVIDER_GRANT_LEASE_SECONDS`, from 1 through 604,800
- `CRE_STRIPE_PRICE_MAPPINGS`
- `CRE_SKOOL_TIER_MAPPINGS`

The HMAC covers:

```text
ASCII timestamp + "." + exact accepted request bytes
```

Ingress rules:

- reject invalid, zero, negative, or oversized `Content-Length` before reading;
- support legitimate streaming when the framework omits the header;
- count each streamed chunk before retaining it;
- stop once the cumulative byte limit would be exceeded;
- verify the signature over the exact bounded bytes;
- never log or persist raw bodies or secrets.

## Durable state and containment

Provider-sync migration version 2:

- retains the payload-free event journal and attempts;
- adds `subject_user_id` to external mappings and grants;
- bounds existing provider grants;
- infers a legacy subject only for a workspace with exactly one membership;
- revokes ambiguous live legacy provider grants;
- enforces subject membership and non-null provider grant leases with database
  triggers.

Provider-sync migration version 3:

- adds authoritative grant `scope`;
- backfills provider grants as subject-scoped and JV grants as workspace-scoped;
- infers legacy manual or promotion subject authority only for exactly one
  active member and otherwise revokes it;
- revokes affected OAuth authority when no valid scoped survivor exists;
- adds privacy-safe SHA-256 object-stream hashes and restrictive rank;
- indexes `(provider, object_stream_hash, occurred_at, restrictive_rank, id)`;
- enforces source, scope, subject, lease, and membership invariants with
  database triggers.

Provider-sync migration version 4:

- adds exact canonical action and a provider-domain-separated external-account
  hash to each receipt;
- binds the existing private object-stream hash with workspace, subject, and
  scope as one write-once replay identity;
- backfills only from deterministic event semantics and one unique, consistent
  subscription, grant, account-mapping, and membership state;
- treats Stripe update, pending-update, and legacy `subscription.updated`
  receipts as action-ambiguous regardless of legacy restrictive rank;
- never uses mutable normalized JSON as migration authority;
- quarantines incomplete or ambiguous legacy receipts with
  `legacy_receipt_binding_untrusted`;
- enforces binding shape, membership, hash form, and non-null immutability with
  database triggers;
- validates membership on initial subject binding without blocking later
  operational evidence updates after legitimate membership removal;
- retains a bound receipt when its user is deleted by using a non-cascading
  subject foreign key.

Provider-sync migration version 5:

- adds `entitlement_input_hash`, `bound_plan_key`, and `bound_profile`;
- computes a `v1:` domain-separated SHA-256 binding over the exact provider,
  canonical action, subscription status, ordered mapping selectors, and
  canonical UTC paid-through value;
- makes the input hash fully immutable, including NULL-to-value changes;
- permits only one paired NULL-to-value bind for plan and profile, then makes
  both values immutable;
- creates new receipt bindings from the trusted in-memory event and
  server-owned configuration, never by rereading stored normalized JSON;
- retains writable normalized evidence while requiring exact hash agreement
  before any positive replay resolution;
- quarantines unverifiable positive legacy receipts durably with
  `legacy_receipt_binding_untrusted`;
- assigns only fully v4-bound restrictive legacy receipts a safe
  state-derived restrictive hash built without normalized JSON;
- preserves state-derived restrictive replay without allowing selector,
  status, plan, profile, or paid-through evidence to extend authority;
- validates hash form, paired target shape, profile values, and write-once
  behavior with database triggers.

Provider events mutate only their own source rows. They cannot modify another
provider, manual, JV, or promotion grant. Provider projection never overwrites
operator-only account states. Restrictive projection still revokes provider and
OAuth authority while preserving the operator state.

Each new receipt, provider projection, final event outcome, final-subject check,
OAuth session revocation, and pending-code consumption runs on one connection
inside one `BEGIN IMMEDIATE`. Stream order is the durable tuple
`(occurred_at, restrictive_rank)`, so a restrictive event wins an equal-time
tie in either delivery order. Lookup uses the indexed SHA-256 stream hash and
never stores the raw external object id in the key or index.

Restrictive SQLite projection failures retry synchronously at most three times.
Each attempt has its own savepoint and rollback and records durable attempt
evidence. Exhaustion quarantines the receipt, emits
`provider_restrictive_retry_exhausted`, and permits later audited replay.
Duplicate receipts increment `duplicate_count`; replay updates `replayed_at`;
neither exposes normalized provider identifiers.

Replay passes three fail-closed gates. Before resolution, reconstructed event
material must match provider, event id, event type, timestamp, exact action,
restrictive rank, account hash, object hash, and the v1 entitlement-input hash.
After trusted resolution, workspace, subject, and scope must match their stored
bindings. Before projection, the server-resolved plan and profile must match
their paired write-once binding. A legitimately unresolved receipt may bind
workspace authority once, and an originally unmapped selector may bind its
newly configured plan/profile pair once. Any disagreement produces durable
`receipt_binding_mismatch` quarantine and cannot redirect, strengthen, or
extend projection.

Mutable `normalized_data` is retained as evidence. It is never independent
authority. Editing a selector, subscription status, or paid-through value
without the impossible corresponding immutable hash update causes replay to
fail closed. A trusted configuration remap cannot change an already-bound
plan/profile pair.

Quarantine remains durable and payload-free. Each quarantine emits the safe
structured warning `provider_event_quarantined` with provider, internal event
row id, reason code, and optional workspace id only.

## Reconciliation

The reconciliation routes require OAuth, live internal-admin authority,
allowlisted reason codes, and a nonblank reason.

- GET reasons are supplied in `X-Admin-Reason-Code` and `X-Admin-Reason`
  headers, not URLs.
- List operations use `BEGIN IMMEDIATE`, serialize with concurrent writers, and
  write their audit entry in the same transaction as the scoped read.
- Replay uses `BEGIN IMMEDIATE`.
- Responses expose safe event metadata, including duplicate count and replay
  time, but never raw payload, normalized provider identity, email, or secrets.

## Skool limitation and production status

The official documented Skool Zapier surface described for this phase exposes
new paid member polling at roughly 10 to 15 minutes. It does not provide a
trusted cancellation, removal, ban, payment-failure, or current-roster feed.
Skool cancellation can retain community access until the billing-cycle end.

The signed relay and current-member source expected by this adapter are
external dependencies and are not built here. Therefore instant Skool churn is
not production-ready. The lease only limits stale authority after its bounded
interval. It cannot satisfy immediate revocation by itself.

Do not scrape Skool. Do not use member email as authority. Do not assume Skool
payouts in Stripe represent individual member subscriptions.

Direct billing through the product's own Stripe account is the only currently
documented route in scope that can provide immediate revocation end to end.

See `docs/provider-sync-limitations.md` for the operator-facing statement.

## Required verification

Before any foundation-only handoff:

1. Preserve a tests-only red run against unchanged production code.
2. Run the focused provider and security regressions.
3. Run platform, access, OAuth, admin, hosting, config, and server slices.
4. Run changed surfaces with strict asyncio and resource-warning gates.
5. Exercise migration upgrade and rollback, foreign keys, and integrity.
6. Run the full repository suite and `compileall`.
7. Run `git diff --check`, dependency diff, status, secret and raw-body scans.
8. Confirm HEAD remains the base commit and PID 2370 still belongs to the
   original checkout without contacting its port.
9. Re-read the supplied anti-slop instructions point by point.

## Preserved verification evidence

The inherited checkpoint reported 26 focused security regressions passing and
12 broader provider failures. Those 12 failures were resolved during the
concurrent repair pass before the final matrix.

Additional red-first evidence preserved during stabilization:

- three targeted failures exposed first-seen restrictive ordering and
  same-state operator-reason loss in both compatibility paths;
- one customer-summary failure exposed cross-subject provider-grant metadata;
- a read-only audit reproduced older activation after a newer pre-mapping
  restrictive receipt;
- a direct verifier probe reproduced a Unicode digest `TypeError`;
- the v2 account-projection upgrade probe failed once while the other three
  migration cases passed.

Final green evidence:

- 34 focused provider security regressions;
- 145 provider tests, including 145 with runtime, resource, and unraisable
  warnings promoted to errors;
- 389 platform, access, hosting, and config tests plus 7 server tests;
- 29 migration, rollback, and lifecycle probes;
- 6 privacy probes;
- 1,712 full-repository tests;
- `compileall`, `git diff --check`, dependency integrity, offline boundary,
  privacy, logging, and secret-pattern checks.

The only emitted warning is the known third-party FastMCP/Authlib deprecation.

No passing test result removes the Skool source limitation. Production remains
disabled until a trustworthy restrictive and current-state source exists and is
integrated end to end.

## Defensive receipt binding verification

Red-first evidence for migration v4 and replay binding:

- four of five initial replay binding probes failed against unchanged
  production behavior, while the older-restrictive-after-newer-positive
  preservation probe was already green as expected;
- all three initial v4 schema and migration probes failed before v4 existed;
- the added Stripe legacy action-ambiguity probe failed because three rank-zero
  update receipts were incorrectly bound as `subscription`.

Final green evidence for this repair:

- 19 focused migration and receipt-binding tests pass with warnings promoted to
  errors after filtering only the known third-party Authlib deprecation;
- 204 provider, reconciliation, migration, OAuth, and legacy entitlement tests
  pass;
- 190 provider-focused tests pass under strict asyncio, resource, unraisable,
  and warning handling;
- 1,758 repository tests pass;
- compile, diff, dependency, privacy, migration, foreign-key, integrity, and
  protected-process audits pass.
