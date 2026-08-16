# MedawarCRE production readiness

Written 2026-08-16 against `integration/cloud-platform-launch`. Every claim
below names the test that proves it, because a readiness packet whose claims
cannot be re-run is a summary of somebody's confidence rather than of the
system.

**Verdict: private staging is ready. Public production is not approved, and
four external credentials stand between here and it.**

## Re-run the whole thing in one command

```
zsh deploy/local_staging.sh          # PostgreSQL + migrations + hosted MCP
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests -q
```

Last run: `5,228 passed, 4 skipped`. Staging probe: migrations `1..13` applied,
hosted MCP healthy on `127.0.0.1:8791`, unauthenticated `initialize` refused
`401`, no local state file created, and the scheduled-search worker ticking
against the same database on its own admin connection.

## What is proven

| Claim | Proof |
| --- | --- |
| The hosted process boots on PostgreSQL and enforces OAuth | `tests/postgres/test_hosted_boot.py` |
| The twelve platform authority stores answer from PostgreSQL, with no SQLite file | `tests/postgres/test_platform_bridge_runtime.py` |
| A Skool member gets MCP access; ending it refuses the next call on an already-issued 12-hour token, `401 invalid_token` | `tests/postgres/test_skool_launch_gate.py` |
| A revoked member's *scheduled* work also stops — the projected grant carries the revocation | `tests/postgres/test_projection_is_a_projection.py` |
| The full Stripe test-mode lifecycle: signatures, replay, ordering, activation, upgrade, downgrade, failure, recovery, cancellation, period-end | `tests/postgres/test_stripe_lifecycle_postgres.py` |
| Two tenants share one server and never see each other's data; it survives a restart | `tests/postgres/test_hosted_staging_proof.py` |
| A customer cannot reach an internal route | same file |
| The Operations Console reads the real PostgreSQL rows | `tests/postgres/test_platform_bridge_runtime.py` |
| Scheduled saved searches run, with live entitlement and territory rechecks | `tests/postgres/test_worker_loop.py`, `tests/postgres/test_job_repository.py` |
| Staff can process privacy and retention requests | `tests/postgres/test_privacy_cli.py` |
| Backup, clean restore into a separate cluster, and the exact role contract | `tests/postgres/test_backup_restore.py` |
| Secrets are runtime-injected; no route or traceback emits one | `tests/platform/test_secret_boundary.py` |

## What is not done

### Needs a credential only Max can supply

1. **Clerk** — a real test-instance key. The adapter, the connection screen and
   the OAuth flow are built and tested; the browser journey has never been
   driven in an actual browser.
2. **Stripe** — a real test-account run. Everything is proven against
   representative fixtures with the real signing scheme; no live call has been
   made.
3. **Skool** — the configured relay and the operator runbook, exercised
   privately.
4. **Cloudflare** — create the tunnel, route the hostname, install the
   credentials file. `deploy/cloudflared-config.example.yml` is ready and inert;
   staging is `127.0.0.1:8791`, chosen because 8000 is held on this machine.

### Needs a decision, not a credential

5. **Public cutover.** Max's explicit approval, after reading this.

## Known limitations, stated because they will surprise someone

- **Period-end expiry is not a revocation.** A subscription past
  `current_period_end` loses its live grant and is denied `403` by the
  entitlement check, but its OAuth session is *not* revoked, so the bearer
  token stays a valid token until it expires on its own. Cancellation is
  different: it revokes the session and denies `401`. Both are asserted exactly.
- **Recovery after a failed payment needs a new token.** The payment failure
  takes the sessions with the grant; restoring the entitlement does not restore
  the session.
- **Admission is no longer an independent second opinion on authority.** It
  re-resolves from rows the identity projection writes, so it is a consistency
  check on projected values. The independent check is `AuthorityResolver`,
  live, against the platform stores, before admission is reached. This is
  recorded at the grant in `postgres/authority.py` and in migration `0013`.
- **`medawarcre_app` has read/write on all 31 `platform_*` tables, with no RLS
  on them.** That is the trust level the SQLite file gave those stores, carried
  forward deliberately. The one escalation path — writing
  `platform_internal_admins` — is revoked. Narrowing the rest is a real phase.
- **`BEGIN IMMEDIATE` maps to a transaction advisory lock**, so only statements
  that use it serialize against each other. SQLite locked every writer. No
  current store writes the same rows without it.
- **Delivery for scheduled searches is not built.** The job engine is complete
  and runs; notification is an explicit staging integration.
- **Two OAuth schemas exist.** `PostgresOAuthAuthorityRepository` and
  `medawarcre.oauth_sessions` are certified, tested, and *not* on the hosted
  path, because issuance writes `platform_oauth_sessions`. Unifying them is
  real work and is not done.

## Rollback

Migrations are numbered, checksummed, and applied under an advisory lock with
explicit dirty recovery (`medawarcre-postgres recover`). There is no down
migration by design. Rollback is restore-from-backup:

```
medawarcre-postgres backup /path/to/dump
medawarcre-postgres restore /path/to/dump /path/to/dump.manifest.json \
    --smoke-workspace-id ... --smoke-actor-user-id ... --smoke-other-workspace-id ...
```

`restore` verifies the restored catalog against the manifest fingerprint, the
exact table/column/function role contract, RLS coverage, and a tenant-isolation
smoke test before reporting success. It has caught three real defects in this
work, each time before anyone needed it in anger.

## First-user plan

1. Provision the workspace, member and territory through `PlatformRepository`.
2. Bind the Skool member with an operator join task, then a confirmed
   members review. Access arrives from the review, never from the join.
3. The customer signs in and authorizes; the browser surface is sign-in and MCP
   connection only. There is no portal.
4. Watch `medawarcre.access_audit_log` and `staff_audit_log` for the first
   session.
5. To end access: `manual_revoke`. The next protected call fails immediately.
