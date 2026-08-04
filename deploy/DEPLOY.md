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
