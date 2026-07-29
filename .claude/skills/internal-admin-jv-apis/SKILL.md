---
name: internal-admin-jv-apis
description: Implementation contract for the MedawarCRE internal admin and JV API phase.
---

# Internal Admin and JV API Phase

## Fixed environment

- Worktree: `/Users/maxmedawar/LoopnetMCP-admin-jv`
- Branch: `feature/internal-admin-jv-apis`
- Base: `49cab683f0c5effd47f70d1a476a4b7c3de2bb22`
- Python: `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`
- `PYTHONPATH`: `/Users/maxmedawar/LoopnetMCP-admin-jv/src`

Never commit, push, merge, deploy, edit another checkout, or interact with port
8000.

## Architecture

Follow `.claude/specs/internal-admin-jv-apis.md` as the source of truth.

- Internal admins are user-scoped live server authority, separate from tenant
  membership, grants, tokens, and `TenantContext`.
- `support` reads. `platform_admin` mutates.
- `admin:controls` is required and never sufficient by itself.
- JV reads use only live token-bound workspace authority.
- All admin mutations use one `BEGIN IMMEDIATE` transaction that re-resolves
  the actor, mutates, snapshots, and appends exactly one audit row.
- Audit rows are append-only and canonical.
- Migration component `admin-controls` starts at version 1 and is additive.
- External accounts are provider-neutral mappings.
- Existing subscription and grant provider reference columns do not change.

## Execution phases

### Phase 1: inspect and specify

- Record branch, base, worktree status, prohibited checkout tracked status, and
  port 8000 PID/cwd.
- Map the current schema, migration runner, authority resolver, OAuth session
  store, repository, entitlements, API route registration, and tests.
- Run the existing platform/access/hosting/config baseline.
- Write the design before test or production changes.

### Phase 2: deterministic red tests

- Add admin authority and support read-only tests.
- Add admin mutation and reason validation tests.
- Add JV scope and same-session live role tests.
- Add audit atomicity, canonical snapshot, and actor-source tests.
- Add external mapping conflict tests.
- Add fresh and upgrade migration tests.
- Run the focused suite and save exact collection and failure evidence.

### Phase 3: minimal implementation

- Add typed constants and records.
- Add the version 1 additive migration and append-only triggers.
- Add the modular admin transaction store.
- Extend live authority with an independent internal-admin result.
- Add admin and JV handlers without bloating the existing customer API.
- Register the small approved route surface.

### Phase 4: verification and audit

- Re-run the exact red command until green.
- Run platform/access/hosting/config regressions.
- Run strict asyncio and warning-as-error checks.
- Run full pytest and compileall.
- Inspect `git diff --check`, dependency files, branch, HEAD, status, prohibited
  checkout tracked state, and port 8000 PID/cwd.
- Re-read the supplied AGENTS.md law point by point and fix every applicable
  issue before handoff.

## Required handoff evidence

- Exact red failures and command.
- Files changed.
- Focused, regression, strict, and full test counts.
- Compile and diff checks.
- Architecture deviations with reasons.
- Residual risks and explicit deferrals.
- Confirmation that no commit or external mutation occurred.
