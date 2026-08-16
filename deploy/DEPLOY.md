# MedawarCRE deployment

Status: **private staging is runnable; public production is not approved**

The current release truth is
[`docs/launch/PROGRAM_STATUS.md`](../docs/launch/PROGRAM_STATUS.md).

This file said "not runnable and not approved for public deployment" for as
long as `build_postgres_hosted_persistence` refused unconditionally. The first
half of that stopped being true when the platform authority port landed: the
hosted process boots against PostgreSQL, enforces OAuth, and serves MCP. The
second half has not changed and is not changed by this edit.

Do not change DNS, expose a public hostname, activate live billing, enable a
paid integration, or admit a real customer from this branch. Those require
Max's explicit approval after the production-readiness packet is complete.

## What works, and how to see it for yourself

One command brings up a disposable PostgreSQL, applies every migration, starts
the real hosted process on a dedicated loopback port, and asserts that an
unauthenticated request is refused and that no local state file is created:

```
zsh deploy/local_staging.sh          # exits when the probes pass
zsh deploy/local_staging.sh --hold   # leaves it running on 127.0.0.1:8791
```

It uses port **8791**, not 8000: an unrelated local service holds 8000 on the
build machine, and a cloudflared tunnel is already running there for other
services. Neither is touched.

Proven end to end, each by a test that drives the real ASGI app over a real
socket rather than a mock:

| Claim | Where |
| --- | --- |
| The process boots on PostgreSQL and enforces OAuth | `tests/postgres/test_hosted_boot.py` |
| A Skool member gets MCP access; ending the membership refuses the next call on an already-issued token | `tests/postgres/test_skool_launch_gate.py` |
| Two tenants share one server and never see each other's data; it survives a restart | `tests/postgres/test_hosted_staging_proof.py` |
| The twelve authority stores answer from PostgreSQL, and the Operations Console reads the same rows | `tests/postgres/test_platform_bridge_runtime.py` |
| Backup, clean restore into a separate cluster, and the exact role contract | `tests/postgres/test_backup_restore.py` |

## What is not done

External, needing a credential only Max can supply:

- **Clerk** — a real test-instance key. The browser sign-in journey has not been
  driven in an actual browser.
- **Stripe** — a real test-account proof of the webhook lifecycle.
- **Skool** — the configured relay and the operator runbook, proven privately.
- **Cloudflare** — create the tunnel, route the hostname, install the
  credentials file. `deploy/cloudflared-config.example.yml` is ready and inert.

Internal, still open:

- A final independent security review of the current tree.
- The production-readiness packet and Max's cutover approval.

## Running the background worker

Scheduled saved searches run in a **separate process** from the server. The
server must not spend its time leasing jobs, and the worker holds an `admin`
runtime connection the server does not have and should never have.

```
MEDAWARCRE_WORKER_DATABASE_URL=... \
MEDAWARCRE_WORKER_ACTOR_USER_ID=... \
python -m cre_mcp.postgres.worker
```

It refuses to start without either. The actor is not defaulted because every
queue mutation writes a `staff_audit_log` row pinned to that identity, and an
invented one would produce an audit trail naming nobody.

## Configuration boundary

`.env.example` documents local and disabled integration settings only. It is
not a production environment template, and the database variables are
deliberately absent from it: they are injected, and listing them in a file that
developers copy is how a development credential reaches staging. The table below
is the configuration reference.

The container's build runs a server-import smoke check. A successful image
build is not staging proof and is not deployment approval; `local_staging.sh`
is the former and only Max is the latter.

## Production secret handling

Founder decision, 2026-08-06: **a local `.env` file is never the production
source of truth for a real credential.** It is a development artifact holding
disposable development or test values, it is gitignored, and nothing in the
production architecture requires it to exist.

Production credentials live in the deployment platform's managed secret store
and reach the process through least-privilege service identity, environment
injection, or a secret mount. No provider is chosen yet — the repository locks
none, and choosing one is a separate approval — so this section states the
requirements the eventual provider must satisfy rather than naming it.

### How the application consumes them

`CreConfig` is a `pydantic-settings` model with `env_prefix="CRE_"`. Environment
variables outrank the optional `.env` file, so an injected secret cannot be
shadowed by a stale developer file, and the file may be absent entirely. Every
credential field is `SecretStr`, whose value is excluded from `repr`, `str`, and
serialization. `tests/platform/test_secret_boundary.py` pins all of this,
including that no registered route emits secret material.

Rotation therefore requires no code change and no rebuild: replace the value in
the managed store and restart the process. Nothing is captured at import time.

### Required secret names and their least-privilege consumers

| Variable | Consumer | Scope it needs |
| --- | --- | --- |
| `CRE_CLERK_SECRET_KEY` | `ClerkHumanIdentityVerifier`, hosted HTTP only | Clerk Backend API: verify a session token and read one user record. Nothing else. |
| `CRE_CLERK_PUBLISHABLE_KEY` | connection browser bundle | Public by design; not a secret. |
| `CRE_STRIPE_API_KEY` | `StripeReconciliationService` | Read-only on subscriptions. Test-mode key only until live billing is separately approved. |
| `CRE_STRIPE_WEBHOOK_SECRET` / `_SECRETS` | webhook signature verification | Verification only; rotating set supported. |
| `CRE_SKOOL_WEBHOOK_SECRET` / `_SECRETS` | Skool relay verification | Verification only; rotating set supported. |

The PostgreSQL credentials are separate connection strings rather than one
shared superuser, so a compromise of the request path cannot migrate the schema
or read the OAuth tables. Each logs in as a distinct login role that is a member
of exactly one of the roles in `deploy/postgres/bootstrap_roles.sql`.

The serving process **refuses to start** without the first three. It reports the
missing variable names before it opens a connection or binds a socket, so a
deployment misconfiguration stops at the boundary rather than surfacing later as
a connection error whose real cause is an absent credential.

| Variable | Consumer | Scope it needs |
| --- | --- | --- |
| `MEDAWARCRE_DATABASE_URL` | hosted request path | Member of `medawarcre_app`. No DDL, no reach into OAuth or provider secrets. |
| `MEDAWARCRE_OAUTH_DATABASE_URL` | OAuth authority pool | Member of `medawarcre_oauth` only. Execute on the fixed authority function; no deal, search, or provider tables. |
| `MEDAWARCRE_ADMISSION_DATABASE_URL` | admission and decision audit | Member of `medawarcre_admission` only. Append-only on the decision audit. |
| `MEDAWARCRE_MIGRATION_DATABASE_URL` | `medawarcre-postgres migrate` | The only credential carrying DDL. Injected for the duration of the command; it must be absent from the serving process. |
| `MEDAWARCRE_BACKUP_DATABASE_URL` | backup, restore, release check | Member of `medawarcre_backup` only. Read and restore; no application writes. |
| `MEDAWARCRE_APP_DATABASE_URL` | release smoke check | Member of `medawarcre_app` only; the same underlying role as the request path, rotated with it. |
| `MEDAWARCRE_WORKER_DATABASE_URL` | `python -m cre_mcp.postgres.worker` | Member of `medawarcre_admin`. The serving process must not hold this. |
| `MEDAWARCRE_WORKER_ACTOR_USER_ID` | the same worker | Not a secret. The staff user every worker audit row is attributed to; a real `medawarcre.staff_roles` row must exist for it. |

The last three are operator credentials. They are injected for the duration of
one command and are not part of the running service's environment.

Provider data-source keys (`CRE_CENSUS_API_KEY`, `CRE_BLS_API_KEY`,
`CRE_FRED_API_KEY`, `CRE_HUD_API_TOKEN`, `CRE_BEA_API_KEY`,
`CRE_RENTCAST_API_KEY`, `CRE_SKIPTRACE_API_KEY`, `CRE_ATTOM_API_KEY`,
`CRE_REGRID_API_KEY`, `CRE_SOCRATA_APP_TOKEN`) follow the same rules and remain
subject to the source-rights registry regardless of whether a key is present.

### Rules the deployment must satisfy

- Separate credentials per environment: development, test, staging, production.
  A development Clerk instance key must never appear in staging or production.
- No secret in Git, a container image, a build argument, a log line, an error
  message, a URL, a fixture, the launch ledger, SecondBrain, or chat.
- No API endpoint returns a secret, and none may be added.
- The process may spawn no untrusted subprocess from a request path: a child
  inherits the environment, which is the injection channel.
- A secret that has ever been transmitted outside the managed store is rotated,
  not reused.

## The line that has not moved

Private staging on this machine, with test data and no real customer, is
allowed and is what `local_staging.sh` does. Everything past that boundary --
provisioning a public host, creating the tunnel, routing DNS, activating live
billing, admitting a real customer -- requires Max's explicit approval after
the production-readiness packet, and there is no supported public deployment
command until he gives it.
