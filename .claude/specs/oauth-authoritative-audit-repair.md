# OAuth Authoritative Audit Repair

## Scope

This repair closes the accepted independent-audit findings without adding an
authorization server or changing the hosted authorization boundary.

Fix now:

- M1: give every refresh-token family an absolute lifetime that rotation cannot
  extend.
- M2: resolve OAuth plan quotas from live platform plan records on every
  request, with missing or malformed plans failing closed.
- L1: deterministically close SQLite connections owned by auth, authority, and
  entitlements.
- L2: authenticate the applicable client, redirect URI, and PKCE verifier
  before replay-triggered family revocation.
- I2: apply distinct provider events with equal source timestamps while keeping
  duplicate event IDs idempotent.
- Replace global coroutine-name cancellation in HTTP tests with resource- and
  task-identity ownership checks.
- Use Streamable HTTP JSON responses for ordinary request/response traffic and
  raw HTTP regression clients. This avoids creating the upstream SSE
  reader/watcher for calls that do not need streaming, while preserving MCP
  sessions and transport-level OAuth status codes.

Preserve:

- Established-session entitlement, account, or membership disable returns 403.
- Established-session token, session, or client revocation returns 401.
- Trusted-local authority exists only when stdio is explicitly selected.
- Hosted HTTP accepts only authoritative OAuth context.
- There is no public authorization, registration, or token endpoint.
- Dependencies and lockfiles do not change.

## Migrations

### OAuth schema version 2

Add `platform_oauth_sessions.refresh_family_expires_at TEXT NOT NULL`.

- Fresh families use the configured maximum age, whose security default is
  90 days.
- Existing version-1 families are backfilled deterministically to
  `created_at + 90 days`.
- Rotation caps each refresh-token expiry at the stored family deadline and
  never moves that deadline.
- Runtime uses the earlier of the stored deadline and the currently configured
  maximum measured from `created_at`, so configuration can shorten but cannot
  lengthen an existing family.
- Keep credential `AUTHORITY_VERSION` unchanged; this is an additive schema
  migration rather than a token-format cutover.

### Platform-core schema version 1

Add `platform_plans.daily_quotas TEXT NOT NULL DEFAULT '{}'`.

- Existing plan and workspace rows are preserved.
- `{}` is an explicit unlimited plan.
- Quotas are server-owned plan data, not copied from the JSON access registry.
- An entitlement whose selected `plan_key` has no live plan row, or whose plan
  quotas are malformed, receives no tenant context and fails with 403.

Before rollout, this query must return no rows:

```sql
SELECT DISTINCT grant.plan_key
FROM platform_access_grants AS grant
LEFT JOIN platform_plans AS plan ON plan.key = grant.plan_key
WHERE plan.id IS NULL;
```

Production quota values must be supplied in live `platform_plans` records.
The repair must not invent values or duplicate the JSON registry.

## Red evidence required before production changes

- M1: repeated rotations cross the original 90-day family boundary; the
  version-1 schema has no absolute deadline.
- M2: an OAuth `pro` grant is unlimited when `pro` is absent from the JSON
  registry; missing live plan data still authorizes.
- L1: repeated authority and entitlement resolutions grow the process FD count
  without calling `gc.collect()`.
- L2: a mismatched spent code or refresh token revokes the legitimate family.
- I2: a distinct second event with equal `occurred_at` is journaled but not
  applied.
- Teardown: global coroutine-name cleanup cancels an unowned same-named task.

Tests must be added and run red before production code is changed. Genuine
matching-client replay must remain family-revoking.

## Verification gates

All Python and pytest commands use:

```text
PYTHONPATH=/Users/maxmedawar/LoopnetMCP-oauth-authoritative/src
/Users/maxmedawar/LoopnetMCP/.venv/bin/python
/Users/maxmedawar/LoopnetMCP/.venv/bin/pytest
```

Required gates:

1. Narrow red selectors for all accepted findings.
2. Focused access, auth, migration, entitlement, HTTP, API, and hosting tests.
3. Fresh- and upgraded-schema migration tests.
4. Raw HTTP established-session 403 and 401 tests.
5. `PYTHONASYNCIODEBUG=1` with RuntimeWarning and ResourceWarning promoted to
   errors (including pytest's unraisable-exception wrapper), with no
   pending-task, unawaited-coroutine, unclosed-stream, unclosed-transport, or
   unclosed-socket output.
6. Compile all source with the approved interpreter.
7. Full pytest suite.
8. `git diff --check`.
9. Confirm dependency manifests and lockfiles are unchanged.
10. Confirm no public authorization/registration/token route was added, all
    live HTTP tests bind an ephemeral loopback port, and port 8000 is untouched.

Warnings and stderr must never be suppressed.

## Deferred findings

### M3

FastMCP Client 2.14.7 hanging after transport-level 401 or 403 remains an
upstream operational risk. Server semantics stay strict. Raw HTTP tests are the
authoritative regression proof. This repair does not update dependencies,
weaken status codes, or patch the client.

### L3

Membership role semantics remain deferred to the Internal admin/JV control API
phase because this phase has no defined role-to-action matrix or control
surface. That phase must begin with red tests proving:

- non-admin members cannot mutate workspace controls;
- JV partners cannot escape the defined JV control scope;
- live role changes apply without token refresh.

This repair does not invent role semantics or add permanent xfails.

## Delivery

The repair ends as an inspected, tested dirty worktree. It does not commit,
amend, push, merge, deploy, touch the original checkout, or interact with the
live port 8000 process. A later explicitly authorized turn may amend the single
phase commit only after a second independent recheck.
