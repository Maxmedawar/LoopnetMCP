---
name: stripe-skool-provider-sync
description: Implementation contract for the Stripe and Skool synchronization phase.
---

# Stripe and Skool Synchronization Phase

## Fixed environment

- Worktree: `/Users/maxmedawar/LoopnetMCP-provider-sync`
- Branch: `feature/stripe-skool-sync`
- Base: `7cbb1ac1aed6e059ef7282ca0f6e45d4846eac07`
- Python: `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`
- Pytest: `/Users/maxmedawar/LoopnetMCP/.venv/bin/pytest`
- `PYTHONPATH`: `/Users/maxmedawar/LoopnetMCP-provider-sync/src`

Never commit, push, merge, deploy, call providers, add SDKs, bind a port, edit
another checkout, or interact with port 8000 or PID 2370.

## Source of truth

Follow `.claude/specs/stripe-skool-provider-sync.md` and the user's approved
plan. Preserve unrelated user changes.

## Required execution

1. Inspect current instructions and implementation.
2. Run the existing focused baseline.
3. Add adversarial tests only and preserve exact red evidence.
4. Implement the smallest provider-neutral core, Stripe and Skool adapters,
   provider-sync migrations through v5, source-contained entitlement
   projection, webhook routes, and three audited reconciliation routes.
5. Re-run focused, regression, strict, full, compile, migration, privacy, diff,
   and boundary checks.
6. Review every changed file and re-read the supplied AGENTS.md before handoff.

## Defensive replay receipt binding repair

Provider-sync migration version 4 adds write-once canonical receipt bindings:

- exact canonical action;
- provider-domain-separated external-account SHA-256 hash;
- existing provider-domain-separated external-object stream hash;
- workspace id, subject user id, and scope.

Replay validation has two fail-closed gates. Before resolution or projection,
reconstructed replay material must match the canonical provider, event
identity, timestamp, action, restrictive rank, account hash, and object hash.
After trusted resolution and before projection, the resolved workspace,
subject, and scope must match the stored bindings, or guarded NULL-to-value
updates must bind a legitimately unresolved receipt exactly once.

Canonical bindings may never change once non-null. Operational receipt fields
remain mutable. Legacy backfill may use deterministic event semantics and
unique, consistent subscription, grant, and external-account state only. It
must never derive authority from normalized JSON. Incomplete or ambiguous
legacy bindings are quarantined with a durable operator-visible reason.
Membership is validated when subject authority is first bound. Later
operational updates to an already-bound historical receipt must remain durable
after legitimate membership removal, while a new binding to a removed subject
must still fail.

Required focused regressions cover exact restrictive action mismatch,
same-workspace account redirection, subject or scope disagreement, stale older
restrictive replay after a newer positive generation, untrustworthy legacy
receipts, and valid fully bound replay. Rejections must prove zero projection
or OAuth mutation, unchanged canonical bindings, durable attempt and audit
evidence, and absence of raw provider identifiers from logs and audits.

## Entitlement-capable replay input repair

Provider-sync migration version 5 adds a versioned, domain-separated SHA-256
binding over the exact provider, action, subscription status, selector sequence,
and canonical UTC paid-through value used by replay. The hash is privacy-safe
and immutable, including NULL-to-value changes. `normalized_data` remains
writable evidence, but replay recomputes the hash before resolution and never
uses mismatched or missing positive authority input.

New receipts bind an internally resolved `(plan_key, profile)` pair from the
trusted in-memory event and server configuration. A receipt whose original
selector was not configured may bind the pair once after that selector is
legitimately configured. The pair is then immutable. A later trusted-config
remap of the same selector fails closed with `receipt_binding_mismatch`.

Migration never derives a positive entitlement binding from normalized JSON.
Unverifiable positive legacy receipts remain durably quarantined with
`legacy_receipt_binding_untrusted`. A fully v4-bound restrictive receipt gets
only a state-derived restrictive input hash computed from immutable receipt
state. That compatibility path cannot use selector, status, profile, plan, or
paid-through evidence to strengthen or extend authority.

Required regressions cover poisoned unknown selectors, lower-tier upgrades,
paid-through extension, same-selector configuration remap, legitimate one-time
mapping bind, strict hash immutability, paired target binding, writable
normalized evidence, migration rollback and concurrency, legacy policy,
privacy, and receipt retention.

## Non-negotiable invariants

- Signature covers timestamp plus exact raw bytes and uses
  `hmac.compare_digest`.
- Maximum body size is enforced before MAC.
- Secrets and raw payload are never persisted, logged, or echoed.
- Tenant and individual subject come only from audited external-account mapping.
- Stripe grants use a trusted current period as authoritative and fall back to
  the bounded server lease only when it is absent. Skool grants use the lease.
- Stripe trialing is non-granting.
- Provider, manual, and promotion grants are exact-subject. Only an explicitly
  workspace-scoped JV grant is workspace authority.
- Provider mapping has no permissive fallback and must name an existing plan.
- Editable replay evidence may never select, strengthen, or extend authority.
- Every entitlement-capable replay input must match its immutable v1 hash.
- Resolved plan and profile are a paired write-once receipt binding.
- One provider mutates only its own subscription and grant rows.
- Provider code never writes operator-only account states.
- Restrictive events are mapping-free and payment failure revokes immediately.
- Final subject authority loss revokes OAuth sessions and pending codes in the
  same transaction.
- Cancellation is derived only when zero live workspace grants remain.
- New event journal and projection changes share one `BEGIN IMMEDIATE`.
- Durable order uses `(occurred_at, restrictive_rank)` and restrictive wins an
  equal-time tie.
- Provider stream lookup uses a private SHA-256 key and an indexed query.
- Restrictive SQLite projection failures retry three times with durable attempt
  evidence before alertable quarantine.
- Duplicate and stale events make zero projection changes.
- Quarantine is accepted with 202 and is payload-free.
- Reconciliation is scoped, paged, reason-coded, audited, and offline.
- Audited reconciliation lists use `BEGIN IMMEDIATE`.
- Webhooks need no bearer token. Reconciliation needs authoritative OAuth and
  live internal-admin authority.
- Skool production enablement remains blocked until a trustworthy restrictive
  and current-state source exists.
