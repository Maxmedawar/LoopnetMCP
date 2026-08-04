# Final Launch Runtime Contract

Status: approved execution contract
Branch: `integration/cloud-platform-launch`
Base: `802b16cec823f74fc41cab10cb4de9602d56fea7`

## Outcome

Deliver a private-staging-ready MedawarCRE cloud runtime with:

- a Clerk-backed connection-only customer journey;
- an internal-only Operations Console;
- Stripe test-mode entitlement synchronization;
- Skool joining, reconciliation, uncertainty, and manual revocation;
- a repaired integrated security posture;
- reproducible private staging artifacts.

The final turn stops at the production approval gate. It does not deploy
publicly, change DNS, activate live billing, or expose real customer data.

## Frozen non-scope

- No customer dashboard, search page, deal portal, billing portal, pricing
  page, profile editor, or customer operations UI.
- No customer route exposes internal audit, provider, workspace, billing,
  source-rights, security, repair, or combined-opportunity controls.
- No old 45-tool server or old customer-portal branch becomes the product.
- No provider claim directly authorizes a request. MedawarCRE live state is
  the final authority.
- No Skool capability is claimed unless an official or directly observed
  contract proves it.
- No public deployment, DNS mutation, live Stripe object, or production secret
  creation occurs in this tranche.

## 1. Clerk connection-only journey

### Architecture

- Add a provider-neutral `HumanIdentityVerifier` protocol and deterministic
  fake implementation for tests.
- Add a Clerk implementation using the official Python SDK. Accept only Clerk
  session tokens, validate signature, lifetime, issuer, and the configured
  `azp` authorized-party allowlist, and reject pending or malformed sessions.
- Persist an exact `(provider, provider_subject) -> platform_user_id` identity
  link. Resolve active memberships and account state from MedawarCRE storage.
- Exchange a verified Clerk session token for an opaque, short-lived,
  HttpOnly, Secure, SameSite=Lax browser session. Store only a digest at rest.
- Bind browser sessions to a server-owned user and membership snapshot key.
  Every protected request re-reads current identity, membership, account, and
  internal role state. Browser sessions cannot choose a workspace authority.
- Expose OAuth 2.1 authorization, token, revocation, protected-resource
  metadata, and authorization-server metadata routes for MCP clients. Require
  PKCE S256 and registered redirects. Preserve refresh rotation and family
  revocation.
- Expose only `/connect` and its authentication callback/status endpoints to
  customers. The screen may sign in, explain requested access, connect the MCP
  client, show success or a precise repair instruction, and sign out.
- Connection pages never render customer deal, billing, profile, or account
  management content.

### Required tests

- Fake identity happy path and Clerk-shaped session verification.
- Invalid signature, issuer, expiry, `azp`, pending status, unknown identity,
  inactive membership, suspended account, revoked browser session, CSRF, open
  redirect, non-S256 PKCE, code reuse, and refresh-family replay denial.
- Exact end-to-end Clerk-session-to-OAuth-code-to-MCP-call flow.
- Workspace selection cannot be injected in query, form, token, or callback.
- Customer routes contain only connection content and never internal data.

## 2. Internal Operations Console

### Architecture

- Build a React application as a real operator artifact, not a marketing page.
  Use the pinned, verified `reicon@1.1.103` icon source only where an icon earns
  its place.
- Serve it from an independently configured internal origin or path that is
  disabled unless explicitly configured. Private network or Access policy is
  defense in depth, not the authorization mechanism.
- Require a live Clerk browser identity plus an active
  `platform_internal_admins` role on every request. Support may read approved
  views. Only platform admins may mutate.
- Use a cookie-authenticated BFF with CSRF protection. Do not place OAuth,
  Clerk, provider, or admin tokens in localStorage, URLs, or rendered markup.
- Provide bounded operational views for workspace lookup, current membership,
  plan/profile/territory/grants, account state, identity/provider mappings,
  provider event quarantine and replay, Skool reconciliation uncertainty,
  manual revocation, source-rights status, health, and append-only audit.
- Require a reason code and reason for every mutation. Display exact actor,
  target, before/after summary, and result from the server audit.
- Design world: a precise surveyor's field ledger for real operational state.
  No generic SaaS hero, purple gradient, pill clutter, icon tiles, card lift,
  decorative glow, fake controls, or content-hidden entrance animation.

### Required tests

- Anonymous, customer, JV, inactive support, and removed admin denial.
- Support read and platform-admin mutation matrix.
- CSRF, Origin, Host, IDOR, reason, pagination, audit, and stale-role tests.
- Build, typecheck, unit, keyboard, reduced-motion, responsive, contrast, and
  real-browser control tests.
- Customer origin cannot fetch console HTML, assets, or APIs.

## 3. Stripe test integration

### Architecture

- Keep Stripe optional and disabled without test credentials.
- Verify `Stripe-Signature` over exact raw bytes with timestamp tolerance,
  multiple active secrets during rotation, bounded body size, duplicate-event
  handling, and durable ordering.
- Normalize supported customer, subscription, invoice, and entitlement events
  into the existing provider journal. Restrictive events may only weaken
  access. Stale or partial events never strengthen it.
- Map test price IDs to server-owned plans/profiles. Reconcile current customer
  subscriptions through a read-only Stripe API client only when a test key is
  configured. Cache no secret or raw provider payload.
- Surface provider state and discrepancies in the Operations Console. Manual
  repair remains reasoned and audited.
- Never create live Checkout, prices, products, or charges in this tranche.

### Required tests

- Official-shaped signed fixtures, raw-body mutation, timestamp, secret
  rotation, duplicate/reordered events, test/live-mode mismatch, unmapped
  price, payment failure, cancel, pause, resume, reconciliation, and active
  session revocation tests.

## 4. Skool joining, reconciliation, and manual revocation

### Architecture

- Treat Skool as a provider signal, never an authorization source.
- Joining uses only a proven supported action. If no supported write API exists,
  generate a bounded operator task and record completion evidence instead of
  automating an undocumented endpoint.
- Ingest a signed relay contract for observed member and payment events. Store
  payload-free receipts and normalized state only.
- Reconciliation requires a current-state artifact with source, observed time,
  and confidence. Missing or stale restrictive evidence marks the provider
  state uncertain and prevents it from strengthening access.
- Add an explicit, reasoned, audited manual revocation that immediately removes
  the Skool-derived grant and revokes affected OAuth sessions.
- Show join queue, reconciliation age, uncertainty, conflicts, and revocation
  results only in the Operations Console.

### Required tests

- Supported join task, signed event, stale evidence, missing member, canceled
  member, tier mismatch, mapping conflict, duplicate/reordered delivery,
  uncertainty, manual revoke, OAuth-session effect, and audit tests.

## 5. Integrated security audit

- Threat model customer connection, OAuth, Clerk, internal console, CSRF,
  tenancy, IDOR, PostgreSQL/RLS, provider ingress, reconciliation, manual
  override, source rights, territories, approvals, quota, audit, logs, browser
  storage, build artifacts, dependency integrity, and staging supply chain.
- Run static secret scanning, dependency audit, type/compile checks, focused
  adversarial tests, full Python and frontend suites, and live browser checks.
- Repair every valid critical or high issue and repeat the same reproducer.
- No public staging or production action is part of the audit.

## 6. Private staging

- Build reproducible backend and frontend artifacts with locked dependencies.
- Hosted startup fails closed unless PostgreSQL, migrations, source-rights,
  identity, and internal-origin configuration pass readiness checks.
- Use test/fake providers until the exact Clerk development, Stripe test, or
  Skool operator action is supplied out of band.
- Exercise migration, health, backup, clean restore, rollback, audit export,
  secret redaction, worker shutdown, and OAuth connection smoke tests.
- Bind privately. Do not change DNS or expose a public production hostname.

## Evidence and commits

Each section receives focused red tests, implementation, focused green tests,
related regressions, complete suite, compile/type/build checks, diff check, and
one intentional commit. Update `docs/launch/PROGRAM_STATUS.md` with exact hashes
and command summaries. Final evidence includes the private staging artifact
hashes and an explicit list of the founder-owned production actions still
blocked by approval.

## Final stop

When private staging and the final anti-slop, security, and release checks are
green, stop. Request one explicit approval for production launch. Do not infer
approval from prior phase acceptance.
