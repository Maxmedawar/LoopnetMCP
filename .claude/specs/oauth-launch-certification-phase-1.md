# OAuth Launch Certification Phase 1

Status: rejected round-seven candidate under repair; dirty and uncommitted.
The prior review approvals are invalidated. Two fresh independent read-only
approvals are required against one unchanged post-repair tree hash before the
phase may be committed.

Base: `289241601ed6aec9fd8999a7601a22a62d4b45e1`

## Goal

Close the deterministic launch-certification defects without changing product
authority or expanding the public surface:

1. Eliminate the mixed pytest-asyncio event-loop and socket leak caused by
   synchronous entitlement tests calling `asyncio.run()` after an async test.
2. Prevent a territory-limited workspace from receiving any out-of-territory
   property from a property-bearing tool, even when its request or opaque
   identifier appears authorized.
3. Preserve all reproduced territory escapes as protocol-level regressions:
   24 cross-profile/collection cases and 48 exact state/city/ZIP-grant cases.
4. Make requested and returned location handling typed, normalized, exact, and
   fail-closed, including incomplete Crexi-shaped records.

The work ends as an inspected, tested dirty worktree for independent read-only
audit. It does not self-approve or publish anything.

## Superseding user directive (2026-08-01)

The launch owner explicitly expanded the original `search_properties`-only
boundary after independent protocol review reproduced additional property
egress paths. The current authority is therefore broader than the original
draft below: every restricted-profile property request that carries a property
record must be validated before execution, and every returned property record
must be validated again before release. This expansion includes persisted deal,
pipeline, saved-search, alert, owner/parcel, comp, diligence, routing, and
prospecting results when they contain a property or authoritative location.

This is not a policy that rejects every geographic word in every tool. Caller
notes, legal prose, counterparty registry states, and other non-property text
remain outside Phase 1 unless a strict result DTO is already needed to close a
reproduced property/location carrier. Seven shared-store workflows with no
previously declared property anchor require typed, tool-specific request and
result contracts rather than a cosmetic output filter. Their round-seven
redesign is part of the current repair and is not represented as approved until
all seven paths pass the protocol regressions, full gates, and two fresh
reviews.

## Scope

### Entitlement test isolation

- Convert only the synchronous tests in
  `tests/platform/test_entitlements.py` that invoke `asyncio.run()` to native
  pytest-asyncio tests.
- Await the existing async setup operations directly.
- Preserve every entitlement assertion and production behavior.
- Keep deterministic red evidence showing the pre-change mixed-suite
  `ResourceWarning` and unclosed-loop failure under strict warning promotion.

### Post-result territory enforcement

- Extend `ToolCapability` with an explicit, machine-readable declaration of
  result collections and the exact location fields carried by each record.
- Declare the two legacy `search_properties` representations:
  - legacy result collection: `properties`;
  - aggregated result collection: `listings`;
  - exact record location fields: `address`, `city`, `state`, `zip_code`.
- After tool execution and before the allowed audit event, enforce the declared
  result policy for `local_scout` and `jv_partner` contexts.
- Apply the same typed, capability-declared boundary to every property-bearing
  tool included by the superseding directive. Current declarations cover
  listing/detail/market/comps/deal search, saved searches and alerts, stored
  deal and pipeline rows, owner parcels, contacts, after-tax subjects, control
  and arbitrage opportunities, assessor/appraisal inputs, tenant prospects,
  dedupe records, WARN locations, permit screens, routing, stalled projects,
  and portfolio-owner properties.
- A property-bearing caller collection uses a strict request record contract.
  If a public tool accepts more than one top-level representation, each allowed
  representation is an explicit alternative contract. Omitted, null, empty,
  ambiguous, extra-field, or unresolvable restricted inputs fail before tool
  execution. Trusted and unrestricted direct calls retain their public shapes.
- Validate every record in the one declared result collection that is present.
  Exactly one declared collection must be recognized in each released result
  representation. Empty recognized collections are valid.
- Validate the complete envelope and every record against the real strict
  `SearchResult`/`PropertySummary` or
  `AggregatedSearchResult`/`Listing` model. Reject unknown top-level fields,
  unknown record fields, both collections at once, and any missing or invalid
  typed field.
- Require non-empty string `address`, `city`, and `state` fields on every
  released record. `zip_code` is optional and may be absent or null, but when
  present it must be a valid string value.
- Bind the result envelope's `query_location` to the sanitized, already
  authorized request location using exact normalized state/city/ZIP semantics.
  A safe-looking record cannot authorize a mismatched envelope.
- Read only the exact top-level collections and exact record fields declared by
  the capability. Do not recursively scan arbitrary mappings, infer locations
  from unrelated strings, or inspect private/raw provider payloads.
- From only the declared `address`, `city`, `state`, and `zip_code` fields,
  derive exact normalized state, city/state, and five-digit ZIP claims. A
  ZIP+4 record claim is normalized to its first five digits. A granted
  five-digit ZIP therefore matches the same ZIP+4 delivery area.
- Treat every ASCII five-digit ZIP or ZIP+4 token in a declared location field
  as authoritative unless it is explicitly labeled as an apartment, building,
  floor, lot, suite, or unit number. Reject non-ASCII decimal lookalikes and
  invisible Unicode format controls instead of letting them split a claim.
- Treat full state-name tokens as authoritative independently of a fixed
  separator list. Preserve disambiguated city-name and street-name collisions
  such as Washington, DC; Kansas City, MO; Texas Avenue; and New York Avenue.
- Reject a record when its declared fields make conflicting state,
  city/state, or five-digit ZIP claims, including contradictions that remain
  inside one state. Collect every recognizable exact claim within the declared
  address string as well, including state, city/state, ZIP, and ZIP+4 forms that
  omit comma punctuation, so an earlier claim cannot be hidden by a safe
  trailing address suffix. If punctuation-free text cannot be reconciled with
  the declared city, fail the record closed rather than guessing. A bare or
  unparseable street line is supporting data only: it neither establishes scope
  nor overrides consistent explicit claims.
- Release a record only when at least one consistent exact claim matches a
  granted state, city/state, or five-digit ZIP. Do not use `Listing.raw`, URLs,
  names, descriptions, or arbitrary nested strings as territory evidence.
- Treat absent collections, non-list collections, non-mapping records, missing
  or unresolvable record location, unsupported content blocks, invalid JSON,
  and any other unknown declared-result shape as denied.
- Handle every client-visible FastMCP `ToolResult` representation before
  release. The top-level object must be an exact `ToolResult` using the original
  FastMCP serializer and only its canonical `content`, `structured_content`, and
  `meta` instance fields; subclasses and instance-level serializer shadows fail
  closed. Top-level `meta` must be exactly `None`. `content` must be a list of
  `TextContent` blocks. Every block must have `meta is None`, no Pydantic model
  extras, and no annotations. This phase does not authorize result metadata or
  annotations for property search.
- Parse each text block as strict JSON. Reject duplicate keys at any object
  depth, `NaN`, positive or negative infinity, non-mapping roots, unsupported
  JSON types, and structures deeper than 64 container levels. Parser,
  recursion, and structural failures all become the same generic denial.
- Validate `structured_content` when present and every decoded text mapping.
  Every representation must be type-sensitively semantically identical before
  territory validation. Key order may differ; `1`, `1.0`, and `true` are not
  interchangeable. A safe representation cannot authorize a different text
  representation.
- On result denial, emit one ordinary denied audit event with a generic reason
  and raise `ToolError`. Do not return the result and do not place an address,
  listing payload, or other result data in the exception or audit log.
- Treat a provider/tool exception from restricted property search as another
  untyped client-visible result channel. Replace its message with the same
  generic denied result and audit reason; preserve original exception behavior
  for unrestricted profiles and tools without a result policy.

### Request-time territory normalization

- Intersect the requested search with the server-derived grants before tool
  execution. A denied request must not execute the tool.
- Normalize case, USPS state codes and full state names, recognized US country
  suffixes, five-digit ZIP and ZIP+4, and exact city/state forms.
- Use explicit authority data for exact city/ZIP combinations and the USPS
  Fishers Island `06390` New York exception. If a request supplies a city or ZIP
  combination, an unknown or ambiguous combination fails closed for every
  restricted profile, including when the workspace also has a state grant. A
  valid state-only request remains a state-only request.
- Preserve grant specificity: a city grant cannot be broadened to its state, a
  ZIP grant cannot be broadened to its city or state, and a bare city or other
  ambiguous string fails closed.

## Preserved invariants

- Hosted identity, profile, plan, workspace, and territory remain
  server-derived.
- Request-time territory checks remain in force.
- Trusted stdio/local calls remain unrestricted by this result policy.
- `national_scout` and `full_operator` result behavior remains unchanged.
- Non-property tools without an explicit result-territory declaration remain
  unchanged. A missing declaration is never authority to release a property.
- Capability visibility, profile permissions, quotas, approvals, ownership,
  and registered tool counts remain unchanged.
- Legacy `properties` and aggregated `listings` responses remain supported.
- Denied result data is never exposed through the client, exception, or audit.

## Explicit non-scope

- No public deployment, provider call, credential use, or persistent port.
- No OAuth route, token, claim, session, registration, or authorization-server
  changes.
- No database migration or stored entitlement mutation.
- No expansion of request-time territory authority or grant specificity.
- No global policy that treats every arbitrary geographic string as a property.
- No global recursive result scanner, heuristic address discovery, or filtering
  that silently drops only offending records.
- No territory inspection of `Listing.raw` or other arbitrary nested payloads.
  Whole-result structural validation and representation equality are integrity
  checks, not location discovery.
- No dependency, lockfile, UI, documentation-site, or environment contract
  changes. The one packaging addition is the pinned, derived Census 2020
  ZCTA-place authority supplement used to resolve shared-ZIP municipalities;
  its source, hashes, transform, license status, and limitations are recorded
  beside the artifact.
- No changes to unrelated `asyncio.run()` uses outside the offending
  entitlement test module.
- No commit, amend, push, merge, deploy, or self-approval.

## Required red evidence

Before implementation:

1. Run one pytest-asyncio OAuth test followed by at least two synchronous
   entitlement tests under `PYTHONASYNCIODEBUG=1`, with `RuntimeWarning`,
   `ResourceWarning`, and `pytest.PytestUnraisableExceptionWarning` promoted to
   errors. The sequence must fail with the unclosed replacement loop/socket
   evidence.
2. Add a middleware-level test whose Local Scout request is in Texas while the
   fake `search_properties` result contains a Florida property. The unmodified
   implementation must return the property, proving post-result leakage.
3. Add exact matrix/schema tests for the declared collections and record fields,
   plus fail-closed shape and profile-bypass coverage. These tests must fail
   before production code changes.
4. For the first independent-audit repair, add deterministic red coverage for
   same-state city and ZIP contradictions across both result collections and
   both limited profiles; multiple recognizable claims hidden inside one
   declared address, including punctuation-free city/state, state-only, and
   ZIP+4 forms separated by whitespace or punctuation, including commas,
   semicolons, slashes, spaced hyphens, pipes, parentheses, brackets, colons,
   and backslashes; ordinary street suffix, directional,
   labeled-unit, lowercase or uppercase preposition, and conjunction controls;
   ambiguous bare uppercase `IN`/`OR` street-tail tokens are treated as prose
   unless a preceding city candidate or state-plus-ZIP claim disambiguates
   them; top-level `ToolResult` serializer
   overrides; mutated content discriminators; falsey top-level metadata; block
   metadata, annotation extras, and model extras; duplicate keys at multiple
   depths; non-finite and over-deep JSON; safe-but-different representations;
   and malformed content container denial with exactly one payload-free audit
   event.
5. Preserve the exact fifth-review reproductions through `FastMCP` `Client`,
   access middleware, `ToolResult`, and protocol parsing. Before repair the
   exact 24-plus-48 selector produced `72 failed, 1 passed`; the broader
   required-location/Crexi/normalization selector produced
   `112 failed, 46 passed`; and the result-query binding selector produced
   `12 failed`.
6. Preserve subsequent independent protocol reproductions before repair:
   delimiter-independent ASCII ZIP forms (`30 failed`), Unicode format-control
   splits (`18 failed`, with six accented-city controls passing), non-empty
   aggregate provider-error maps (`4 failed`), ambiguous street suffixes
   misread as state codes (`24 failed`), full state names hidden by provider
   prose (`24 failed`), and restricted provider exceptions exposing their
   message (`2 failed`).
7. Preserve the final review reproduction for `find_deals(deep=True)`: an
   in-scope initial row whose provider-refreshed detail moves out of scope must
   be rejected through the real protocol before the refreshed row can affect
   valuation, reranking, selection, error aggregation, or fallback. Cover both
   restricted profiles.

## Verification gates

All commands use the certification worktree source and approved interpreter:

```text
PYTHONPATH=/Users/maxmedawar/LoopnetMCP-oauth-launch-cert/src
/Users/maxmedawar/LoopnetMCP/.venv/bin/python
/Users/maxmedawar/LoopnetMCP/.venv/bin/pytest
```

Required gates:

1. Focused green selectors for entitlement mixed-loop isolation and all new
   result-territory tests.
2. Existing access-control and territory suites.
3. OAuth, entitlement, platform, API, and HTTP regression suites relevant to
   the changed enforcement path.
4. The mixed async/entitlement selector under strict warning promotion, with no
   unclosed loop, socket, transport, stream, task, or unawaited coroutine.
5. Full pytest suite with warnings visible.
6. Compile all source and tests with the approved interpreter.
7. `git diff --check` and complete diff inspection.
8. Confirm dependency declarations and lockfiles are unchanged. Inspect the
   sole `pyproject.toml` change separately: it must only package the pinned
   authority artifacts described above and must not add a dependency.
9. Confirm registered capability count and per-profile visible counts are
   unchanged from the baseline: 274 total, 103 Local Scout, 115 National
   Scout, 274 Full Operator, and 170 JV Partner.
10. Confirm no persistent listener was created and port 8000 was untouched.

## Current verification evidence

The earlier `764037631b70be2c394fa42e3a98d2b44ae99e93faa57e7f988f808a31c4437d`
dirty-tree candidate produced `1889` passing access tests and `3600` passing
repository tests, but a clean-context review then reproduced seven undeclared
store-backed release paths plus location-normalization defects. That candidate
is rejected. Its green commands are historical diagnostics only and are not
release evidence for the current tree.

Round-seven evidence on the active uncommitted repair, using the approved
Python 3.11.15 interpreter:

- `tests/access/test_result_territory.py` is the permanent real-FastMCP test
  module containing the 24 cross-profile/collection cases, the 48 exact
  state/city/ZIP cases, 48 omitted/null/blank/non-string required-field cases,
  four Crexi-mapped empty-address/city cases, and 20 optional-ZIP contract
  cases. Its count lock also proves the matrix case names, payloads, contexts,
  collections, and grants are unique.
- Count lock plus the 24 and 48 matrices: `73 passed`.
- Required-field, Crexi, and optional-ZIP selectors: `72 passed`.
- Count lock plus 24, 48, required-field, and Crexi selectors: `125 passed`.
- Round-seven city/state collision, numeric-place, and strict list-valued
  request regressions: `23 passed`. The six collection cases prove that a
  valid Dallas sibling cannot hide a null, non-string, or blank location for
  either restricted profile; the exact pre-repair selector was `6 failed`.
- Case, state name/code, country suffix, ZIP/ZIP+4, city/state, and
  unknown/ambiguous normalization selectors: `120 passed`. An additional
  state-grant selector confirms nonexistent supplied city/state/ZIP
  combinations fail closed: `12 passed`.
- All seven store-backed boundaries have focused real-protocol evidence. The
  production stores feed tailored closed result DTOs, and the combined store
  workflow plus native relation selector reports `108 passed`.
- Exact request/result GeoRef binding, every returned rent comparable, exact
  compare-market multisets, county producers, and typed portfolio property
  addresses pass the expanded round-seven focused gates.
- A permanent national GeoRef matrix first reproduced eight post-execution
  false denials for exact Seattle/Los Angeles city results and 98101/90001 ZIP
  results across both restricted profiles. All eight same-state wrong-county
  and wrong-CBSA controls denied. The repair replaces small release allowlists
  with an integrity-checked national Census relationship artifact. The 16-case
  focused selector and all 124 market-binding tests now pass.
- The complete access suite reports `2,484 passed` after separately preserving
  and repairing an independent-city grammar collision with an unpunctuated
  Kansas City street address.
- Both previously unstable four-module orders report `2,283 passed`, including
  result territory, round-seven geography, release regressions, and market
  binding in opposite collection orders.
- The current repository-wide suite reports `4,195 passed` in 86.50 seconds
  with one categorized third-party Authlib deprecation warning.
- The strict HTTP OAuth and native entitlement lifecycle selection reports
  `4 passed` with ResourceWarning, RuntimeWarning, and pytest unraisable
  warnings promoted to errors.
- The release lock still reports 274 classified capabilities with profile
  counts Local 103, National 115, Full 274, and JV 170. **Superseded for JV,
  in two steps.** Phase 5G (`49adb9e`) withheld five capabilities from
  `jv_partner` — `exchange_status`, `ic_scorecard`, `list_investors`,
  `trace_input_lineage`, and `unassigned_deals` — taking 170 to 165. The
  ledger-backed oracle repair (`039cacf`) then withheld
  `counterparty_track_record`, taking 165 to 164. Local, National, and Full
  remain exact. This line records the evidence as captured at the time; the
  live authority is `CAPABILITIES`.
- Source and test compilation, builder invocation, artifact SHA-256
  values `8a0d94a3743873cf2b9761c3aa79fa7884703903611f6f9163b758ddb0822476`
  and `ec28297f8f5bd29328c1cd696a7d007c3d80f083def465de3e6b017393e6b6e8`,
  wheel inclusion of all three compressed authority files plus attribution,
  and `git diff --check` pass. The only pyproject change adds package data;
  dependencies and lockfiles are unchanged.

The regression and authority files remain untracked only because the entire
phase must stay uncommitted through final review. They must be included in the
eventual reviewed commit. OAuth remains yellow until two fresh independent
reviews approve one unchanged documented candidate hash.

## Independent final reviews

There are no valid approvals for the current round-seven tree. Every approval
from an earlier tree was invalidated by a later reproducible release defect.
After all seven store-backed boundaries are repaired and all exact-tree gates
are green, two fresh reviewers must independently inspect the same documented
candidate hash using neutral release-correctness wording. Any valid finding
invalidates both reviews, requires a permanent regression and repair, and
restarts both reviews from a new hash.

## Delivery

The phase may be staged and committed only after the permanent regression files
are included, the final evidence above is refreshed, both fresh reviewers
approve one unchanged candidate hash, and the staged diff is rechecked. No
commit, push, merge, deploy, or external activation is authorized before those
conditions are met.
