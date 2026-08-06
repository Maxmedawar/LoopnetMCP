# Phase 5I Clerk identity verification contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `a828717` (hosted capability withholding correction)

## Why this slice exists

The Clerk-backed connection lifecycle is already implemented and locally gated.
This contract does not rebuild it. It records the lifecycle as it actually
exists in this repository, then closes the one boundary where that lifecycle
still trusts identity-provider metadata the end user can edit.

The founder decision is explicit: Clerk proves a human identity and nothing
else, and the server must never accept authority from user-editable
identity-provider metadata. The current adapter honours that for workspace,
plan, profile, role, territory, and entitlement — none of which it reads. It
does not honour it for the one Clerk field that is load-bearing: the primary
email address, which is the sole join key from a Clerk subject to a
preprovisioned MedawarCRE user.

## The lifecycle as built (evidence, not aspiration)

Recorded so a later reader can tell what this phase changed from what it
inherited. Every row below is present in the tree at base `a828717`.

| Lifecycle stage | Where it lives | Existing proof |
| --- | --- | --- |
| Provider abstraction | `HumanIdentityVerifier` Protocol, `cre_mcp/platform/connection.py` | `test_human_identity.py` |
| Fake/test provider | `FakeHumanIdentityVerifier`, same module | `test_fake_verifier_is_explicit_and_rejects_unknown_bearer` |
| Clerk adapter | `ClerkHumanIdentityVerifier`, same module | `test_clerk_adapter_uses_official_verifier_authorized_party_and_user_record`, `test_clerk_adapter_rejects_wrong_issuer` |
| First sign-in, subject mapping | `HumanIdentityStore.resolve_or_bind` | `test_verified_clerk_identity_binds_to_preprovisioned_user_without_plain_subject` |
| Duplicate / wrong subject | `UNIQUE(provider,subject_hash)`, `UNIQUE(provider,user_id)` | `test_unprovisioned_identity_and_second_subject_for_user_fail_closed` |
| Server-owned workspace selection | `PlatformApi._connection_state`, `_state_for_user` | `test_ambiguous_workspace_membership_does_not_issue_code`, `test_workspace_cannot_be_selected_through_http_or_mcp_input` |
| Consent and authorization | `confirm_browser_authorization` | `test_discovery_dynamic_registration_and_full_pkce_connection` |
| Code exchange, real MCP call | `oauth.create_auth_code`, hosted app | `test_clerk_connection_token_initializes_and_calls_real_hosted_mcp` |
| Replayed approval | `PendingAuthorizationStore.consume`, single-row `UPDATE` guard | `test_discovery_dynamic_registration_and_full_pkce_connection` replay assertion (400) |
| Browser session, CSRF, expiry | `BrowserSessionStore` | `test_browser_session_is_opaque_hashed_expiring_and_csrf_protected` |
| Logout / revocation | `browser_logout` | `test_browser_logout_preflight_and_response_support_connection_origin` |
| Suspended / cancelled account | `BLOCKED_ACCOUNT_STATES`, `_account_is_blocked` | `test_suspended_account_does_not_issue_code` |
| Removed membership, revoked session | `_state_for_user`, `BrowserSessionStore.validate` | `test_removed_membership_and_revoked_browser_session_fail_closed` |
| Revoked authority on next request | live authority re-derivation | `test_established_session_live_disable_remains_403`, `test_current_authority_disables_deal_vault_on_next_request` |
| Success / error / retry surface only | `web/connection/src/ConnectionScreen.tsx` | 5 Vitest cases; no dashboard, no Deal Vault route |

That inventory is the reason this phase is narrow. The lifecycle stages the
founder enumerated are built and pinned. What follows is the residue.

## The defect this slice closes

`ClerkHumanIdentityVerifier.verify_bearer` selects the Clerk user's primary
email address and returns it as `VerifiedHumanIdentity.email`.
`HumanIdentityStore.resolve_or_bind` then uses exactly that string —
`SELECT id FROM platform_users WHERE lower(email)=?` — to choose which
preprovisioned MedawarCRE user the Clerk subject becomes on first sign-in.

The adapter never inspects `EmailAddress.verification`. In the installed
`clerk-backend-api` the field is `Nullable[Verification]` and its `status` can
be `unverified`, `failed`, or `expired` as well as `verified`. An email address
a Clerk user has added but not proven ownership of is therefore accepted as an
identity claim with full binding authority.

The consequence is a first-sign-in account takeover, bounded to MedawarCRE
users who have not yet signed in. Every user is in that state until their first
sign-in, so at launch the bound is the entire customer base. A Clerk account
holder who adds a preprovisioned customer's address, makes it primary without
completing verification, and signs in binds their own Clerk subject to that
customer's MedawarCRE user. From then on the binding is stable and correct by
subject, which makes the takeover durable rather than transient. Nothing later
in the chain catches it: `resolve_or_bind` is the only place email is consulted,
and every downstream check — workspace, plan, territory, entitlement — is
correctly derived from the MedawarCRE user, which by then is the wrong one.

Two adjacent fail-closed gaps are in scope because they are the same class of
omission in the same twelve lines:

- `user.deprovisioned` is not checked. `banned` and `locked` are. A
  SCIM-deprovisioned or enterprise-disabled Clerk user is a disabled account,
  and the lifecycle requires a disabled account to be terminal for protected
  MCP access.
- The fetched user record's `id` is not compared to the authenticated `sub`.
  The subject is what gets bound; the email and display name come from the
  fetched record. If those ever disagree, the server would bind one subject
  using another account's address.

## Scope widened after review — read this before the sections below

The first frozen candidate scoped this phase to one adapter method. Its
security review rejected that boundary as too narrow — the correctness review
approved it — and the rejection was right: the join key is not the adapter
alone, it is the adapter *and* the lookup that consumes it. The sections below
are written as amended.

What the reviews found, all repaired here:

- **Non-primary address could become the join key.** `EmailAddress.id` is
  `Optional[str]` and `User.primary_email_address_id` is `Nullable[str]`, so a
  record with both unset matched on `None == None` and promoted an address
  Clerk never designated primary. A stale but Clerk-verified secondary — an old
  employer address retained on a personal account — was a valid bind key.
- **The Python fold and the SQL fold were different functions.**
  `resolve_or_bind` normalized with `str.casefold()` and matched with SQLite
  `lower()`. `casefold()` maps `ß` to `ss` and `ﬁ` to `fi`; SQLite's `lower()`
  is ASCII-only. This cut both ways: a Clerk-verified `straße@corp.test`
  collapsed onto a preprovisioned `strasse@corp.test` row and bound to that
  person, and any row stored with a non-ASCII uppercase letter was permanently
  unreachable — a standing 403 for that customer. PostgreSQL's `lower()` *is*
  Unicode-aware, so the two backends did not even agree with each other.
- **`platform_users.email` is UNIQUE under BINARY collation**, so case-variant
  rows can coexist and an unordered `fetchone()` picked one by rowid.
- **`hmac.compare_digest` raises `TypeError` on non-ASCII** and the new subject
  check sat outside the provider `try`, so it could surface as a 500 rather
  than this module's single `None`. These are non-secret identifiers; constant
  time buys nothing and totality is worth more.
- **A whitespace-only address** reached `VerifiedHumanIdentity.__post_init__`
  and raised instead of refusing.
- **The two binding refusals carried distinct messages** that `api.py` echoes
  to the browser verbatim, enumerating which addresses are provisioned.
- **No test constructed a real SDK model**, so every pin ran against fakes.

## Required behaviour

`ClerkHumanIdentityVerifier.verify_bearer` returns `None` — an ordinary
authentication failure with no distinguishing message — when any of the
following holds. `None` is the adapter's only failure signal by design; the
browser receives `human_identity_invalid` and a retry, never a statement about
which condition failed.

1. The primary email address's `verification` is absent, is `None`, has no
   readable `status`, or has a `status` that is not exactly `verified`.
2. `user.deprovisioned` is true.
3. `user.banned` or `user.locked` is true. (Existing behaviour, re-pinned.)
4. The fetched user record carries an `id` that is not exactly the
   authenticated `sub`.
5. `primary_email_address_id` is absent, null, not a string, or blank; or no
   email address whose own `id` is a string equals it; or the matched address
   is absent, not a string, or blank after stripping.

The verified-status comparison normalizes an enum member to its value before
comparing, because the SDK types these as `str` enums and a future open-enum
change would otherwise silently compare an object to a string. Unknown or
unparseable status values fail closed.

The whole user-record examination runs inside the provider `try`, so an
unexpected record shape is a denial rather than an unhandled error at the call
site. The subject comparison is plain equality, not `hmac.compare_digest`.

`platform_users.email` has one canonical form,
`normalize_platform_email` in `cre_mcp/platform/models.py`: strip, then
`str.lower()`, then unify `ς` onto `σ`, then NFC — each step for a reason given
below. It is applied at **every** site that writes a platform
login — `AdminControlStore.provision_workspace`,
`PlatformRepository.create_user`, and `PlatformRepository.update_user` — and at
the single site that looks one up.

`HumanIdentityStore.resolve_or_bind` additionally:

6. Normalizes the verified address with that same function.
7. Matches by **exact equality** against the stored canonical value, not
   `lower(email)`, so no SQL engine's case rules enter the decision. A row left
   in some other form is unreachable rather than matched approximately.
8. Requires exactly one row. Zero or more than one is a refusal.
9. Raises one identical message for every binding refusal, so the text `api.py`
   echoes to the browser cannot enumerate provisioned addresses.

`str.casefold()` is deliberately not used anywhere in this path: it maps `ß` to
`ss`, `ﬁ` to `fi`, and `ſ` to `s`, collapsing separate mailboxes onto one row.
Lowering leaves all three alone, so it gives case-insensitivity across the
whole alphabet without merging distinct people.

`ς` is then unified onto `σ`, and that one step is what makes the fold safe for
Greek. `str.lower()` implements Unicode's `Final_Sigma` context rule, so it is
not a per-code-point map and the key would otherwise depend on where in the
address the letter sat. `Σ` is the uppercase of both sigma forms, so unifying
them is the only way `Σ` can fold at all; `casefold()` does the same.

Folding per code point to sidestep `Final_Sigma` was tried and removed: with
the unification applied the two are the same function on every input, so the
loop was an equivalent mutant carrying a comment that claimed a safety it did
not provide. Two reviews independently measured zero differences.

Verification is over **strings**, not code points. A per-code-point sweep is
structurally blind to context rules like `Final_Sigma` — that blindness is
precisely how the sigma defect survived a round of review that reported a clean
code-point sweep. The form is idempotent and NFC-stable over every code point,
and produces no collision group beyond ordinary case, final-sigma equivalence,
and Unicode canonical equivalence.

It is **not** invariant under `.upper()`, for exactly 100 code points, and
cannot be: `'ß'.upper()` is `'SS'`, and this contract requires `ß` not to fold
onto `ss`. Uppercasing is not injective, so no fold that keeps `ß`, `ﬁ`, `ſ`,
and `µ` distinct can also round-trip through their uppercase forms. An earlier
draft asserted `.upper()` agreement alongside the requirement that contradicts
it.

The practical consequence is narrow and worth stating exactly, because an
earlier draft called it a false denial and it is not only that. An operator who
provisions `USSV@CORP.TEST` stores `ussv@corp.test`. The owner of
`ußv@corp.test` cannot reach that row — the denial — and the holder of
`ussv@corp.test`, a different live mailbox, can. At base `casefold()` landed
both spellings on `ussv@corp.test` unconditionally, so the candidate strictly
reduces the set of inputs that misdirect: it now requires the operator to type
the expanded spelling, where before it happened either way.

One axis is worse rather than better, and saying only "strictly reduces" would
hide it. At base the rightful `ß` owner could also reach that row, so the
misdirection was a race the owner would usually win. Here the `ss` holder is
the *only* possible binder. Conditional on the vulnerable input, misdirection
goes from likely-lost-race to certain. Treating `ß` and `ss` as separate
mailboxes is correct — they are — but the residual is a misdirected bind, not
merely a lockout.

### Why requirement 6 is stated as "every site"

The first repair changed only the reader. Both round-two reviews independently
found that `provision_workspace` still stored `.casefold()`, so the two folds
disagreed by construction on exactly the character class this contract names.
An operator provisioning `Straße@corp.test` wrote a row that only the holder of
`strasse@corp.test` could ever bind to, and the rightful owner was locked out
permanently — the original cross-account bind, unfixed and relocated, plus a
regression against the base commit.

That is the reason the requirement is written as a property of the column
rather than of a function: a normalization that is not applied at every write
is not a normalization.

### Why the fold is `str.lower()` and not an ASCII-only one

The repair above first used an ASCII-only fold, reasoning that it could not
collapse anything. A third security review rejected that too, and correctly:
it folds `A`–`Z` and leaves every other capital alone, so an operator typing
`MÜLLER@corp.test` stored `mÜller@corp.test`, which the owner whose Clerk
address reads `müller@corp.test` can never match. Same for `JOSÉ@`, `ИВАН@`,
`ΑΝΝΑ@`. All four bound correctly at base `a828717` and were refused — a false
denial and a regression, from a fold that was case-insensitive for some
customers and not others.

`str.lower()` was the answer the whole time. The pin that should have caught
this existed but compared the same string on both sides of the write and the
read, so it could not observe a case difference. The pins now differ
deliberately between what the operator types and what the provider reports.

## Explicit non-scope

This slice changes one adapter method, the lookup that consumes its output, and
the three sites that write `platform_users.email`. It does not touch:

- the OAuth authority model, token lifetime, PKCE, DCR, or revocation;
- `BrowserSessionStore` or `PendingAuthorizationStore`;
- the `platform_users` schema — the canonical form is enforced in application
  code, and no DDL or migration changes;
- workspace, membership, plan, profile, territory, entitlement, or quota
  resolution;
- the hosted fail-closed posture or any PostgreSQL repository;
- the capability matrix, the hosted surface, or the locked visible counts of
  274 / 253 / 21 / 15 / 238 and Local 8, National 10, Full Operator 20,
  JV Partner 11;
- the connection browser surface, which already renders only sign-in, consent,
  success, error, retry, hold, and revoke.

No migration, no schema change, no new dependency, no configuration key.

The commit does carry two documentation changes beyond this slice, both in
`PROGRAM_STATUS.md` and both described there: the nine imported persistence
phase records, and a rewrite of the Clerk row in the **issue ledger** table.
They are named here so the contract's scope and the commit's contents agree.

It also changes two error bodies in `cre_mcp/platform/api.py` from `str(exc)`
to a fixed literal, so the store's uniform refusal message cannot become an
address-enumeration oracle if a future refusal there becomes more specific.
A third body under the same `identity_not_provisioned` code — "Platform user no
longer exists" — is deliberately left distinct: it is reachable only *after* a
successful bind, so it discloses nothing about an address the caller has not
already proved control of, and it is worth keeping for diagnosis.

## What this contract does not claim

It does not claim the Clerk adapter is now exhaustively correct against Clerk's
API. It closes three specific omissions found by reading the installed SDK's
model fields against the adapter's twelve-line user-record handling. Fields
deliberately left unread — `public_metadata`, `unsafe_metadata`,
`external_id`, `organization_memberships`, `saml_accounts` — stay unread, and
that is the point: MedawarCRE derives authority from its own state, so an
unread Clerk field is the safe default rather than a gap.

It also does not claim a real Clerk credential has exercised this path. The
adapter is proven against the official SDK's types through a substituted
client, plus one pin that round-trips a genuine
`clerk_backend_api.models.User`. A live Clerk test instance remains a private
staging gate, and it is the next external blocker for this thread.

Residual items, disclosed rather than closed:

- **Existing non-canonical rows.** No migration ships because nothing is
  deployed and hosted production is fail closed, so there is no production
  data. A row written before this change is unreachable **only if its stored
  value is not already the canonical form**. For a pure-ASCII address the old
  `casefold()` output is byte-identical to the new form, so those rows are
  unaffected; the ones that move are addresses carrying a casefold-collapsing
  character (`ß`, `ſ`, `µ`, ligatures) and rows written with mixed case through
  `create_user`. Measured precisely: 1,436 code points satisfy
  `normalize_platform_email(ch) != ch.casefold()`, of which 29 are whitespace
  or control characters removed by `.strip()` rather than fold differences, so
  1,407 are genuine. An earlier draft gave 1,437 without saying what it
  counted, which made it unreproducible — a reviewer tried nine readings and
  matched none of them.

  The corollary matters more than the lockout: for such a pre-existing row the
  cross-account bind is **not** retired. Only new provisions are written
  correctly. Re-keying those rows is a private-staging step that must precede
  first production use, and it is a security step, not tidying.
- **PostgreSQL alignment**, verified rather than argued. A review loaded
  1,109,579 distinct canonical values into a real PostgreSQL 16 cluster: under
  the `C` collation the repo's own disposable clusters use, `lower(v) == v` for
  every value with zero index collisions; under ICU, 55 values diverge, all of
  them Unicode 15/16 case pairs the Python 3.11 runtime does not know. Every
  divergence is in the over-strict direction — the index would reject a second
  row, never merge two people into one identity.
  `0001_authoritative_cloud.sql` indexes `lower(email)`. Because the stored
  value is now itself `lower()`-folded, `lower(stored) == stored` and the index
  agrees with the application form. Under the earlier ASCII-only fold it did
  not: `mÜller@corp.test` and `müller@corp.test` were two legal SQLite rows
  that one PostgreSQL unique index could not hold, so the cutover would have
  failed or dropped a row. Matching by exact equality against a canonical
  stored value is what keeps the engines from disagreeing about who binds.
- **PostgreSQL is missing `UNIQUE (provider, user_id)`** on
  `medawarcre.human_identities`, which the SQLite table has. Unreachable today
  for the same reason, and a required blocker for the hosted identity cutover
  rather than for this slice.
- **No unbind path exists.** There is no `DELETE FROM
  platform_human_identities` anywhere in `src/`, so a wrong binding is
  permanent short of deleting the user row and cascading away their data. This
  is an operational gap, recorded as an open item, and the uniform refusal
  message plus the absence of logging makes it harder to diagnose.
- **`update_user` can change an email without revoking the binding**, so a
  re-keyed row would keep its old Clerk subject. It has no production caller
  today, and the pin added here only covers the normalization, not revocation.
- **The fold is bounded by the runtime's Unicode tables.** CPython 3.11 carries
  Unicode 14, so 55 characters added in Unicode 15 and 16 are not case-folded
  — the same class as the ASCII-fold defect, confined to Georgian Mtavruli,
  Garay, and rare Latin phonetic letters that no mail transfer agent accepts.
  Inherent to doing case folding in the application; recorded, not actionable.
- **Stored addresses are now folded, so display changes.** The Operations
  Console listing and Skool invite targets show the canonical lowercase form
  rather than the casing an operator typed. Cosmetic, but visible.
- **`verification_admin` counts as verified**, so anyone holding the Clerk
  instance secret key can mark an address verified through the Backend API.
  That is the intended trust boundary and the predicate's docstring now says so
  rather than claiming the account holder personally proved the address.
- **Every enabled Clerk social/enterprise connection is a path in**, because a
  `from_oauth` verification is accepted and email is the sole join key. The set
  of enabled connections is a deployment decision that belongs in the staging
  runbook alongside the verify-at-sign-up toggle.
- **Clerk's "sign in as user" impersonation is not detected.** The adapter
  reads only `sub` and `iss` from the session token, so a session minted by
  impersonation authenticates as the customer. Same instance-admin trust
  boundary as `verification_admin`, but a distinct mechanism, and unlike that
  one it also works against customers who have already bound. It belongs in
  the runbook; refusing tokens carrying an `act` claim is the obvious control
  if that trust is ever narrowed.
- **Both routes bind on first touch, before the authority check.** The
  operations route calls `resolve_or_bind` before verifying operator
  authority, exactly as the connection route does, so a first touch of either
  endpoint by any Clerk identity whose verified primary matches a provisioned
  row creates the permanent binding. With no unbind path, an accidental or
  hostile first touch is irreversible.

Two further items, both raised by review and both outside a code change:

- The Clerk instance's **verify-email-at-sign-up** policy is now load-bearing.
  If that toggle is off in the live instance, every customer is refused with
  `human_identity_invalid`. This is a deployment check, not a code defect, and
  it belongs in the private-staging runbook.
- A Clerk-side ban does **not** revoke already-issued MedawarCRE browser
  sessions or MCP tokens; nothing re-calls Clerk after issuance. MedawarCRE
  membership and entitlement are the live revocation channel, which is
  consistent with "Clerk proves a human and nothing else" — but it is written
  down here so nobody bans a user in Clerk and assumes their access ended.
