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
- Existing workspace-wide manual, JV, and promotion grants remain
  workspace-scoped.
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

## Bounded provider leases

Every Stripe and Skool grant has a server-owned `ends_at`.

`provider_grant_lease_seconds`:

- defaults to 24 hours;
- must be from 1 second through 7 days;
- is not supplied by a webhook;
- bounds Stripe grants together with `current_period_end`;
- bounds relay grants until another trusted positive reaffirmation.

For Stripe, `ends_at` is the earlier of the provider period end and the server
lease. For the relay, it is the lease end. Lease expiry denies CRE MCP and
`/v1` without another event. A lease is a stale-authority bound. It is not an
instant cancellation feed and must never be described as one.

## Trust boundary

The provider adapters only parse allowlisted data. Request data never selects a
workspace or user. Provider identity resolves through one exact server-owned
mapping:

```text
(provider, external_account_id) -> (workspace_id, subject_user_id)
```

Provider values are limited to `stripe` and `skool`. A subject must be a current
member of the mapped workspace. Ambiguous, missing, unbound, or cross-workspace
state fails closed.

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

Provider events mutate only their own source rows. They cannot modify another
provider, manual, JV, or promotion grant. Provider projection never overwrites
operator-only account states. Restrictive projection still revokes provider and
OAuth authority while preserving the operator state.

Each new receipt, provider projection, final event outcome, final-subject check,
OAuth session revocation, and pending-code consumption runs on one connection
inside one `BEGIN IMMEDIATE`. A savepoint permits a safe payload-free quarantine
when projection fails. Duplicate receipts increment `duplicate_count`; replay
updates `replayed_at`; neither exposes normalized provider identifiers.

Quarantine remains durable and payload-free. Each quarantine emits the safe
structured warning `provider_event_quarantined` with provider, internal event
row id, reason code, and optional workspace id only.

## Reconciliation

The reconciliation routes require OAuth, live internal-admin authority,
allowlisted reason codes, and a nonblank reason.

- GET reasons are supplied in `X-Admin-Reason-Code` and `X-Admin-Reason`
  headers, not URLs.
- List operations use deferred `BEGIN` transactions and write their audit entry
  only after the scoped read.
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
