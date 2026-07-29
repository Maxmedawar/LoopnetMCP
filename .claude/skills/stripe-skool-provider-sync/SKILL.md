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
   provider-sync v2 migration, source-contained entitlement projection, webhook
   routes, and three audited reconciliation routes.
5. Re-run focused, regression, strict, full, compile, migration, privacy, diff,
   and boundary checks.
6. Review every changed file and re-read the supplied AGENTS.md before handoff.

## Non-negotiable invariants

- Signature covers timestamp plus exact raw bytes and uses
  `hmac.compare_digest`.
- Maximum body size is enforced before MAC.
- Secrets and raw payload are never persisted, logged, or echoed.
- Tenant and individual subject come only from audited external-account mapping.
- Provider grants have a bounded server-owned lease.
- Provider mapping has no permissive fallback and must name an existing plan.
- One provider mutates only its own subscription and grant rows.
- Provider code never writes operator-only account states.
- Restrictive events are mapping-free and payment failure revokes immediately.
- Final subject authority loss revokes OAuth sessions and pending codes in the
  same transaction.
- Cancellation is derived only when zero live workspace grants remain.
- New event journal and projection changes share one `BEGIN IMMEDIATE`.
- Duplicate and stale events make zero projection changes.
- Quarantine is accepted with 202 and is payload-free.
- Reconciliation is scoped, paged, reason-coded, audited, and offline.
- Webhooks need no bearer token. Reconciliation needs authoritative OAuth and
  live internal-admin authority.
- Skool production enablement remains blocked until a trustworthy restrictive
  and current-state source exists.
