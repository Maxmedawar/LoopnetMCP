# Phase 4 hosted request lifecycle contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `ccc24a36f93a3dfa0c34f7363228b5c7febd3606`

## Outcome and boundary

This checkpoint connects the one-snapshot OAuth authority repository and the
atomic admission repository to the hosted MCP request lifecycle. It does not
construct the production hosted persistence bundle. Hosted HTTP startup remains
fail closed until every request-scoped customer-domain repository is certified.

Trusted local stdio keeps its existing registry, approval, quota, and audit
behavior. Hosted HTTP receives every authority explicitly from its persistence
bundle and never constructs a JSON, JSONL, SQLite, or local-blob fallback.

## OAuth verification

The hosted token verifier calls the synchronous authority repository through a
worker thread so PostgreSQL pool acquisition and query execution cannot block
the event loop. Invalid tokens, inactive live authority, repository failure, and
malformed outcomes fail closed without exposing database errors.

Only a current allowed authority outcome adds the server-owned tenant context to
FastMCP claims. Disabled authority keeps credential identity separate from MCP
authorization by withholding the mandatory MCP scope.

## Policy and admission order

One hosted tool call follows this exact order:

1. resolve the current server-owned tenant context from verified OAuth claims;
2. resolve a grouped customer action to its exact internal capability;
3. run default-deny profile, request-territory, ownership-shape, and argument
   sanitization checks without mutating approval, quota, or audit state;
4. remove `_approval_id`, identity-shaped arguments, and storage-path arguments;
5. derive stable invocation and correlation UUIDs from the authenticated OAuth
   session, MCP transport session, and MCP JSON-RPC request ID;
6. submit only that stable request binding, the exact capability ID, and
   sanitized arguments to atomic admission through a worker thread;
7. execute only a fresh, non-replayed, non-finalized `allowed` admission;
8. enforce post-result territory and source-rights output controls;
9. record one bound final decision through a worker thread before releasing a
   successful result.

The local access engine retains its stateful `check_call` entry point. A new
policy-only entry point shares the same gates and sanitization so hosted code
cannot accidentally call local approval or quota mutations.

## Failure and replay behavior

Admission denial and approval-required outcomes are already durably audited by
the atomic database operation. Middleware does not duplicate them into a second
audit sink. An allowed replay never executes, including an unresolved replay.

Tool failure, result-territory denial, and source-rights output failure record a
bound failed final decision before returning a safe error. A successful tool
result is withheld until its bound successful final decision is durable. If
admission or finalization is unavailable, the request fails closed with a fixed
safe message and no result is released.

Pre-admission policy denials and tool-list summaries continue through the
explicit audit authority supplied by the bundle. The production bundle cannot
be certified until that authority is PostgreSQL-backed together with the
remaining domain repositories.

## Required evidence

- RED tests for policy-only checks that do not mutate local quota or approval;
- hosted admission tests for sanitization, quota and approval metadata, denial,
  approval-required, replay, tool failure, and finalization failure;
- proof that successful output is released only after successful finalization;
- proof that duplicate delivery of one MCP request reuses the same atomic
  binding and cannot execute twice;
- proof that OAuth, admission, and finalization calls run outside the event-loop
  thread;
- proof that hosted installation requires explicit OAuth, admission, and audit
  authorities and has no local registry fallback;
- unchanged local stdio approval, quota, territory, source-rights, and audit
  behavior;
- focused, PostgreSQL, full-repository, compile, packaging, diff, and secret
  gates;
- two fresh read-only reviews of one unchanged candidate hash.

## Explicit non-scope

This checkpoint does not:

- enable `build_postgres_hosted_persistence` to return a bundle;
- add an operator approval grant endpoint, UI, notification, or email;
- port platform, provider, search, deal, job, privacy, document, or truth-asset
  state;
- permit dual writes, shadow writes, or local persistence fallback in hosted
  mode;
- deploy, provision infrastructure, change DNS, activate billing, spend money,
  or use customer data;
- claim private staging, integrated security, production readiness, or public
  launch approval.
