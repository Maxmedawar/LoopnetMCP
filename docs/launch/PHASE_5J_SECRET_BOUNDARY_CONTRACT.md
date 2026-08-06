# Phase 5J production secret boundary contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `e78d390` (Clerk lifecycle pins)

## Founder decision this implements

A local `.env` file is never the production source of truth for a real Clerk,
Stripe, Skool, or database credential. Recorded 2026-08-06.

- Local development may use only disposable development or test credentials, in
  a gitignored local `.env`.
- Production secrets live in the deployment platform's managed secret store.
- Production services receive them at runtime through least-privilege service
  identity, environment injection, or secret mounting.
- No browser, frontend, MCP client, public endpoint, repository file, image,
  log, URL, or customer can retrieve them.
- No API endpoint returns a secret. There is no such route and none may be
  added.
- Rotation must not require a code change or an application rebuild.
- Development, test, staging, and production credentials are separate.
- Secret values stay out of Git, tests, fixtures, logs, docs, SecondBrain, and
  chat.

## What the repository already provides

Recorded from evidence so this phase does not rebuild what exists.

`CreConfig` is a `pydantic-settings` model with `env_prefix="CRE_"` and
`env_file=".env"`. In that library environment variables take precedence over
the file, so managed-secret injection already outranks any local file, and the
file is optional. Every credential field is already typed `SecretStr`, whose
`repr` is `**********` and which refuses to serialize its value by default.

So the production consumption path is already environment injection. This phase
does not introduce a new mechanism; it makes the guarantees explicit, proves
them, and writes down the operational contract that has so far only been
implicit.

## Required behaviour

1. **Every secret-shaped configuration field is `SecretStr`.** A field whose
   name contains `secret`, `key`, `token`, `password`, `credential`, or `dsn`
   holds either `SecretStr` or a container of `SecretStr`. This is enforced by
   a test that enumerates the model, so a future plaintext credential field
   fails rather than being noticed by a reviewer.
2. **`.env` is not required.** With no `.env` present, configuration loads from
   the process environment alone.
3. **Environment injection wins.** When both are present, the environment
   variable is used, so a managed store cannot be silently overridden by a
   stale developer file.
4. **Rotation needs no code change or rebuild.** A new process with a changed
   environment variable observes the new value; nothing is captured at import
   time.
5. **A missing production secret fails closed.** Hosted identity verification
   is unavailable rather than degraded: the connection route answers
   `503 human_identity_unconfigured` and no anonymous or partial identity is
   ever produced.
6. **Secrets never appear in serialization.** `repr`, `str`, `model_dump()`,
   and JSON dumps of the configuration contain no secret value.
7. **Secrets never appear in errors.** Nothing raised by configuration or by
   the identity adapter carries a secret value in its message or arguments.
8. **No route returns a secret.** No registered HTTP route emits secret
   material in any response, and there is no route whose purpose is to return
   configuration.

## Explicit non-scope

- No cloud provider is chosen or provisioned. The repository locks none today,
  and the founder decision explicitly defers that.
- No paid infrastructure, no deployment, no DNS, no billing.
- No change to the OAuth model, the capability surface, the locked visible
  counts, or any PostgreSQL repository.
- No new dependency, migration, or schema change.
- The existing `.env` in this worktree stays a local development artifact. It
  is gitignored, and nothing in the production architecture requires it.

## What this contract does not claim

It does not claim the application has been run against a managed secret store.
No provider is selected, so there is nothing to run against. What is proven is
the property that matters for that later step: configuration is consumed from
the process environment, the file is optional and outranked, and every
credential is masked at every boundary that could otherwise disclose it.

It also does not claim the Clerk adapter has spoken to a live Clerk instance.
That remains an external staging integration gate, recorded as such rather than
blocking local engineering.
