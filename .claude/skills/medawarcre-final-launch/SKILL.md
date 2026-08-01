---
name: medawarcre-final-launch
description: Program contract for taking MedawarCRE from verified phase branches to a private, audited, production-ready cloud service.
---

# MedawarCRE Final Launch

Use this skill for every change in the final launch program. It converts the
founder's launch goal into one execution contract and prevents older customer
portal or broad CRE-roadmap documents from changing the launch sequence.

## Fixed control environment

- Control worktree: `/Users/maxmedawar/LoopnetMCP-final-launch`
- Control branch: `feature/final-launch-control`
- Control base: `f36ef46fe44a21a50967227b476a771030c24816`
- Python: `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`
- Source path: the active worktree's `src` directory
- Protected backup: `/Users/maxmedawar/MedawarCRE-backups/platform-before-oauth-authoritative-20260728-115649.sqlite3`
- Protected backup SHA-256: `8361a9db47bb4ea5276f009309cdc8b0401c0272dc4ae6b8711d9f4b0e489095`

Never edit or replace the protected backup. Never discard another worktree's
uncommitted files. Never claim evidence from one checkout while testing
another checkout.

## Current product decision

- The customer browser surface is connection-only.
- There is no customer dashboard or customer deal portal.
- The Operations Console is internal-only.
- Internal staff may use a combined, deduplicated opportunity list with full
  source-workspace provenance.
- Global cross-customer model learning is deferred and disabled.
- Clerk is the preferred human identity provider behind a provider-neutral
  adapter.
- MedawarCRE remains the final authorization authority for every MCP and API
  request.

## Launch authority model

The authority chain is:

1. The external identity provider proves a human identity.
2. MedawarCRE maps the provider subject to one internal user.
3. MedawarCRE resolves current account state and current memberships.
4. MedawarCRE resolves current plan, profile, territory, quota, grants, and
   provider signals.
5. The server issues and validates OAuth credentials without accepting a
   client-selected workspace.
6. Every protected request re-derives authority from current server state.
7. Tool execution applies exact matrix, territory, ownership, quota, and
   approval policy.
8. Territory-limited search tools validate both the request and returned
   records before releasing a result.

Stripe and Skool are signals. They never directly authorize a request.

## Required phase order

1. Certify OAuth and repair every lifecycle or access-policy gap.
2. Build and certify PostgreSQL, migrations, backup, clean restore, rollback,
   and tenant isolation.
3. Create the integration branch from independently verified phase commits.
4. Add provider-neutral human identity, fake test provider, Clerk adapter, and
   connection-only OAuth journey.
5. Build the React and Reicon internal Operations Console with server-enforced
   internal roles.
6. Complete tenant search/deal persistence, internal opportunity indexing, and
   bounded scheduled-search jobs.
7. Certify Stripe in test mode.
8. Certify Skool reconciliation only to the provider's proven capabilities.
9. Complete privacy, retention, export, correction, and deletion workflows.
10. Enforce a machine-readable, default-deny source-rights ledger.
11. Package and exercise private staging, recovery, monitoring, and rollback.
12. Run a fresh integrated security audit, repair all valid findings, and run a
    second independent audit.
13. Prepare the production-readiness packet. Public deployment, DNS, live
    payments, and real customer data require explicit final approval.

## Mandatory phase loop

For each phase:

1. Inspect current implementation, history, worktree state, and relevant notes.
2. Write a narrow implementation contract and explicit non-scope.
3. Add deterministic failing tests and record the exact red result.
4. Implement the smallest coherent solution.
5. Run focused tests, related regressions, the complete suite, compile checks,
   migration and integrity checks, and `git diff --check`.
6. Open a fresh, read-only independent audit that inspects the diff and reruns
   tests.
7. Fix every valid finding and rerun the same gates.
8. Open a second independent audit after repairs.
9. Commit one intentional phase boundary.
10. Update `docs/launch/PROGRAM_STATUS.md` and the canonical SecondBrain note,
    then reopen both and verify the recorded evidence.

No phase becomes green from a handoff claim, an isolated test, or builder
self-approval.

## Worktree rules

- One write-capable agent per worktree.
- Use a fresh worktree for each distinct phase.
- Keep audits read-only until findings return to the builder.
- Preserve local-only portal commits for selective archaeology only.
- Do not merge customer portal branches wholesale.
- Port useful internal APIs or UI primitives only after checking them against
  the current live-authority model.
- The dirty SQLite dbops worktree is evidence and salvage material. It is not a
  production PostgreSQL implementation and must remain untouched until its
  changes are safely captured.

## Non-negotiable security invariants

- Cloud authority is server-derived and default-deny.
- Static hosted registry keys are rejected.
- Trusted local behavior is stdio-only.
- Public clients do not select, claim, or persist a workspace authority.
- Disabled users, removed memberships, expired entitlements, and revoked
  grants fail closed on the next request.
- All tenant-owned records carry a tenant or workspace key and are protected by
  application authorization. PostgreSQL row-level security adds defense in
  depth where practical.
- Internal roles are independent of tenant membership and are checked on the
  server for every route and mutation.
- Every private-data inspection records actor, role, reason, workspace, object,
  time, action, and result.
- No silent impersonation exists.
- Provider webhook signatures cover exact raw bytes; replay and stale events
  cannot strengthen authority.
- Secrets, raw tokens, and raw provider payloads do not enter source control,
  logs, audit rows, URLs, or browser storage.
- Unapproved commercial sources remain disabled in cloud configuration.
- Global learning remains disabled and private data is excluded from future
  learning by default.

## Interface contract

The founder-supplied anti-slop design law is mandatory for every interface.
Before shipping UI, re-read it in full and perform the promised point-by-point
visual and functional review. In particular:

- Use React for the internal console and Reicon for earned icons.
- Create one product-specific signature and one cohesive visual world.
- Keep content visible by default; motion may never gate access to content.
- Avoid the default SaaS page skeleton, generic gradients, pill clutter,
  default icon tiles, decorative glows, hover lift, fake windows, and dead
  controls.
- Verify contrast, clipping, edge gutters, optical centering, responsive layout,
  comparison alignment, keyboard operation, focus states, reduced motion, and
  every live control with an actual browser click.
- Do not expose internal UI or internal index data on customer routes.

## Required final boundary

Build and verify everything possible with local fakes, test fixtures, and
sandbox providers. Ask for an external credential only when the exact adapter
is ready and no other work can proceed. Never ask for a secret in chat.

Do not perform public deployment, DNS cutover, live payment activation, or
exposure of real customer data. The last program state must be a complete
production-readiness packet followed by the founder's exact approval boundary.
