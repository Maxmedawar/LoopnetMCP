# MedawarCRE deployment is launch-blocked

Status: **not runnable and not approved for public deployment**

The current release truth is
[`docs/launch/PROGRAM_STATUS.md`](../docs/launch/PROGRAM_STATUS.md). This file
is a safety marker, not a deployment guide. Historical hosting instructions
remain available in Git history and must not be followed.

Do not provision a public host, create a tunnel, change DNS, configure a public
hostname, activate billing, enable a paid integration, or expose customer data
from this branch. Those actions require Max's explicit approval after the
production-readiness packet is complete.

## Why startup is intentionally blocked

Hosted HTTP no longer has a compatibility persistence path. The production
constructor requires a healthy PostgreSQL 16 runtime and then deliberately
rejects startup because the complete request-scoped domain repository bundle is
not yet certified. It must fail before binding a socket or creating local
state.

Migration `0002` and the narrow OAuth authority repository are one bounded
checkpoint. They do not make the HTTP service launchable. The repository still
needs all of the following before a deploy procedure can exist:

1. request-scoped domain repositories with no local or file-backed fallback;
2. atomic approval, quota, and durable decision-audit admission;
3. provider ingress and reconciliation repositories with exact service roles;
4. worker and scheduler claim, lease, retry, and recovery paths;
5. privacy and retention processors;
6. a reviewed container and immutable migration procedure;
7. backup, restore, and point-in-time recovery evidence;
8. private-staging boot, browser, authorization, isolation, and lifecycle proof;
9. a final independent security audit and production-readiness packet;
10. Max's explicit cutover approval.

## Configuration boundary

`.env.example` documents local and disabled integration settings only. It is
not a production environment template. Database variables will be added there
only when their consuming hosted paths are launch-certified. Do not infer a
supported deployment configuration from source-level repository constructors.

The container may be built locally for artifact verification. Its build runs a
server-import smoke check, but its HTTP command is expected to fail closed until
the domain bundle checkpoint is complete. A successful image build is not
staging proof and is not deployment approval.

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

## Allowed work before approval

- run trusted local stdio workflows;
- run unit, integration, packaging, and disposable PostgreSQL tests;
- inspect image contents and perform local build-time import checks;
- update the launch ledger with reproducible command evidence;
- prepare a private-staging plan without provisioning external resources.

If a later certified phase replaces this marker with an executable runbook, the
runbook must name exact image digests, database roles, environment variables,
migration and rollback commands, secret sources, health checks, restore proof,
ingress controls, monitoring, and the founder approval step.
Until then, there is no supported deployment command.
