# MedawarCRE Final Launch Program Status

This is the visible issue ledger and command-evidence index for the final
launch program. A claim becomes green only after the relevant command evidence
and an independent audit are recorded here.

## Frozen founder decisions

- Customer browser experience: connection-only
- Customer portal or dashboard: absent
- Operations Console: internal-only
- Combined opportunity list: internal-only, approved, provenance-preserving
- Cross-customer model learning: disabled and deferred
- Human identity: provider abstraction with Clerk as the preferred production
  adapter
- Authorization authority: MedawarCRE live server state

## Repository baseline

| Item | Recorded truth |
| --- | --- |
| Control branch | `feature/final-launch-control` |
| Control base | `f36ef46fe44a21a50967227b476a771030c24816` |
| Strongest pushed spine | `feature/stripe-skool-sync` at `f36ef46` |
| OAuth certified phase | `88e3082109f80722e78d0712ed07028f050e015f` |
| OAuth certification candidate | Exact candidate `e96da4b8345099bb1bac64d5af54e397da8e7fcd0aee14d194a3abebfbc5ca65` passed both fresh read-only reviews unchanged and was committed as `88e3082109f80722e78d0712ed07028f050e015f` |
| Admin and JV APIs | `7cbb1ac1aed6e059ef7282ca0f6e45d4846eac07` |
| Provider sync base | `e647a48` plus replay-authority repair `f36ef46` |
| Customer portal commits | `8a44d4c`, `13abbf5`, local-only, superseded for product routing |
| PostgreSQL certified phase | Exact replacement candidate `f68a9a489602ef0b22614e899e5800820c0579e12002afce83c7aaa613f0e9e6` passed both fresh read-only reviews unchanged and was committed as `5089748aaa6f9f726db5801f866a130974d1eb89` |
| Source-rights certified phase | Exact replacement candidate `4c33265f12dec0927fb34a6c344158174ef5bb89f8bda2a2c3363fd873986f04` passed both fresh read-only reviews unchanged and was committed as `3185ccb595cf305f9c69f15ae2730f2d6fa75ee7` |
| Cloud integration phase | `integration/cloud-platform-launch` at `5bcd5c0`; certified OAuth, PostgreSQL, source rights, connection-only Clerk, internal Operations, Stripe test, and Skool lifecycle histories integrated; OAuth/JV audit repair and fail-closed hosted persistence boundary committed; 4,535 repository tests passed |
| Customer MCP surface | Commit `802b16cec823f74fc41cab10cb4de9602d56fea7`; 274 internal capabilities retained, 253 exact actions grouped, 21 MCP capabilities internal-only, all 45 historical IDs reconciled; visible counts Local 8, National 10, Full 20, JV 14 |
| SQLite dbops salvage | 4,513 uncommitted lines in the protected dbops worktree; not production DR |
| Protected backup | SHA-256 `8361a9db47bb4ea5276f009309cdc8b0401c0272dc4ae6b8711d9f4b0e489095`, read-only integrity `ok` |

## Issue ledger

| Status | Work item | Evidence needed to turn green |
| --- | --- | --- |
| 🟢 | No-customer-portal decision locked | Founder goal and this contract |
| 🟢 | Internal combined opportunity list approved | Founder goal and this contract |
| 🟢 | Global learning deferred | Founder goal and this contract |
| 🟢 | Secure multi-tenant foundation reported and recovered | Commit archaeology; independent integrated verification still tracked below |
| 🟢 | Exact profile counts re-derived | Local 103, national 115, full 274, JV 170 from the live matrix |
| 🟢 | OAuth live authority implementation recovered | Commit `49cab68`; 1,521-test verification and focused strict lifecycle verification |
| 🟢 | OAuth SSE warning ownership explained | Upstream-only reproduction plus JSON-response application path with owned-task teardown test |
| 🟢 | Provider replay-authority repair recovered | Pushed commit `f36ef46` |
| 🟢 | Admin and JV APIs recovered | Commit `7cbb1ac` |
| 🟢 | Hosted persistence authority inventory | Every SQLite, JSON, JSONL, and local-blob authority mapped to a PostgreSQL or object-storage seam |
| 🟢 | Superseded portal salvage boundary mapped | Reicon provenance, connection/privacy primitives, and tests isolated from forbidden customer dashboard code |
| 🟢 | OAuth launch certification | Exact candidate `e96da4b...` passed access, opposite-order, repository, packaging, lifecycle, capability-count, compile, and diff gates; two fresh read-only reviewers independently approved the unchanged hash; committed as `88e3082` |
| 🟢 | Production PostgreSQL and recovery | Candidate `2af2a907...` was rejected and repaired. Exact replacement `f68a9a4...` separates direct from inherited ownership; 69 PostgreSQL and 1,839 repository tests passed; two fresh reviewers approved the unchanged hash; committed as `5089748` |
| 🟢 | Launch integration branch | Certified OAuth `88e3082`, PostgreSQL `5089748`, and source rights `3185ccb` integrated as `0b5a87b`; shared enforcement-order regressions repaired; 4,444 repository tests passed |
| 🟢 | Consolidated customer MCP surface | Hosted HTTP uses 20 coherent grouped facades with profile listings Local 8, National 10, Full 20, JV 14; all grouped actions resolve to exact server-owned capability IDs; internal services and 21 internal MCP capabilities remain unexposed; commit `802b16c`; 4,459 repository tests passed |
| 🟡 | Clerk identity and connection flow | Implementation and local gates complete: official Clerk adapter, connection-only React screen, OAuth discovery/DCR/PKCE/revocation, live authority rechecks, and a real hosted MCP call. Integrated audit remains scheduled after Stripe and Skool per the founder-approved sequence |
| 🟡 | Internal Operations Console | Implementation and local gates complete: separate React control ledger, pinned Reicon provenance, opaque Clerk operator sessions, live staff and JV separation, exact Origin and Host, CSRF, reasoned mutations, provider quarantine, source rights, health, and append-only audit. Integrated security and real-browser staging gates remain scheduled |
| 🔴 | Search and deal persistence | Tenant records, evidence, score versions, object-ID isolation, privacy behavior |
| 🔴 | Combined opportunity index | Server-side deduplication, provenance, staff-only access, pagination and conflict tests |
| 🔴 | Scheduled saved searches | Idempotent queue, current entitlement and territory checks, audit, internal status |
| 🟡 | Stripe test integration | Implementation and local gates complete: test-only credentials and mode enforcement, rotating signed webhooks, durable lifecycle journal, fixed-host GET-only complete-list reconciliation, atomic projection repair, active-session effects, and reasoned operator audit. Representative fixtures still require a real Stripe test-account staging proof; integrated audit remains scheduled after Skool |
| 🟡 | Skool reconciliation | Local gates complete: operator-only supported join tasks, exact member binding without implicit grant, rotating signed relay secrets, payload-free timestamped review receipts, stale and partial uncertainty, restrictive mismatch handling, manual revoke, OAuth invalidation, and internal Console controls. Private staging must prove the configured relay and operator runbook |
| 🔴 | Privacy and retention | Notice, export, correction, deletion, retention, processor propagation, audit |
| 🟢 | Source-rights controls | First replacement `e58c721...` was rejected and repaired. Exact replacement `4c33265...` fails closed on contradictory local/hosted policy and cleanly imports; 164 focused and 1,950 repository tests passed; two fresh reviewers approved the unchanged hash; committed as `3185ccb` |
| 🔴 | Private staging | Reproducible package, TLS, migrations, workers, monitoring, backup and restore exercise, rollback |
| 🔴 | Integrated security audit | OAuth consent, public-client, route exposure, request-bound, browser-session, logout, and identity-wide JV findings repaired in `d82e600`; all public HTTP entrypoints now fail closed through `5bcd5c0` instead of constructing legacy persistence; PostgreSQL domain repositories, durable atomic admission/audit, jobs/privacy, and deployment correctness remain open blockers |
| 🔴 | Production-readiness packet | Exact hashes, artifacts, evidence, limitations, credentials, rollback, first-user plan |
| 🔴 | Public production cutover | Explicit founder approval after the readiness packet only |

No row may be deleted. Superseded work stays visible with its disposition.

## Stripe test integration evidence

- Repository gate: `4496 passed, 1 warning in 127.21s (0:02:07)`
- Platform gate: `402 passed, 1 warning in 21.61s`
- Operations Console: `8 passed`; production build completed; `npm audit`
  reported `found 0 vulnerabilities`
- Stripe access is disabled without an explicit `sk_test_` or `rk_test_` key.
  Live keys and live-mode webhook objects are rejected.
- Reconciliation reads only the fixed Stripe subscriptions endpoint, consumes
  every bounded page, validates the complete item-level price and period state,
  and commits projection repair plus the operator audit in one transaction.
- `customer.updated` and active-entitlement summary events are durable
  reconciliation signals only. They cannot grant access by themselves.
- Fixtures contain invented test identifiers and follow Stripe's documented
  list and subscription schemas. A real test-account capture remains a private
  staging gate.
- Official contract references: `https://docs.stripe.com/webhooks`,
  `https://docs.stripe.com/api/events/object`,
  `https://docs.stripe.com/api/subscriptions/list`, and
  `https://docs.stripe.com/api/subscriptions/object`.

## Skool lifecycle evidence

- Repository gate: `4507 passed, 1 warning in 183.33s (0:03:03)`
- Platform gate: `413 passed, 1 warning in 42.62s`
- Operations Console: `10 passed`; production build completed; `npm audit`
  reported `found 0 vulnerabilities`
- Joining is deliberately operator-bounded. The system creates an audited task
  for Skool Admin Invite or Zapier Invite, then waits for the member to click
  JOIN NOW and for an operator to bind the exact member id.
- Completing a join task creates no grant. A signed event or a complete,
  current, confirmed member review remains the next authority gate.
- Reconciliation stores only a hash receipt and operational metadata. Stale,
  partial, provisional, or unverified reviews are visibly uncertain and cannot
  strengthen access.
- Missing members and restrictive statuses revoke. An unmapped tier is a
  conflict and revokes existing Skool authority rather than guessing a plan.
- Manual revocation removes Skool authority and invalidates the affected OAuth
  session and pending authorization codes in the same audited transaction.
- The Operations Console exposes join tasks, evidence age, certainty,
  discrepancies, conflicts, exact mappings, and reason-gated manual revocation.
- Official operating references:
  `https://help.skool.com/article/14-how-do-i-invite-members-to-my-community`,
  `https://help.skool.com/article/56-zapier-integration`, and
  `https://help.skool.com/article/141-how-to-remove-a-member`.

## Preserved red evidence

### Returned-result territory leakage

A real FastMCP call through the production access middleware used a Local Scout
grant restricted to Texas. The request was `search_properties(location="Houston,
TX")`. The tool returned both a Houston record and `200 Ocean Dr, Miami, FL
33139`; middleware released both records. This proves the current system checks
territory arguments but not returned property records.

Required repair: a capability-declared, fail-closed post-result policy that
validates all returned property locations for territory-limited profiles without
silently trusting a result shape it cannot inspect.

### Mixed asyncio lifecycle leak

OAuth-focused strict lifecycle tests pass. A separate mixed selection can leave
pytest-asyncio's replacement loop and socketpair descriptors open when a sync
entitlement test invokes `asyncio.run()` after an async test. The repair is to
convert those entitlement tests to native async tests, not to filter warnings or
cancel unrelated tasks.

### OAuth certification audit round one: changes required

The first independent audit rejected the initial Phase 1 implementation even
though its full suite passed 1,800 tests. The following findings remain part of
the permanent evidence trail until a repaired implementation passes a fresh
second audit:

- High: exact city and ZIP grants accepted same-state contradictory declared
  address fields.
- High: unchecked client-visible protocol channels could carry denied property
  data through result metadata, text-block metadata or extras, and duplicate
  JSON keys.
- Medium: structured and text representations were validated separately but
  were not required to be semantically identical.
- Medium: malformed content containers and deeply invalid JSON could bypass the
  ordinary generic denial audit through an internal exception.

The approved repair boundary remains narrow. It may derive claims only from the
declared `address`, `city`, `state`, and `zip_code` fields. It must not scan
arbitrary nested mappings or provider `raw` payloads. Hosted serialization of
provider `raw` data is tracked as a separate product-security decision.

### Hosted persistence cannot use a generic compatibility shim

Read-only call-site archaeology found four durable authority classes in the
current hosted runtime: central platform SQLite, per-workspace MCP SQLite,
mutable `registry.json` plus `audit.jsonl`, and local truth-document blobs. The
HTTP server currently constructs these concrete stores and registers the full
tool catalog. A PostgreSQL error or miss must never fall back to any of them.

The SQLite stores embed domain-specific DDL, SQL, identifiers, file paths, and
transaction behavior. Emulating `sqlite3.Connection`, translating arbitrary
SQLite SQL, or storing opaque database state in JSONB would erase launch
invariants and is rejected. Cloud integration instead requires an explicit
request-scoped persistence bundle with domain repositories. Local stdio keeps
its existing SQLite behavior. Each hosted persistent capability remains
fail-closed until its repository parity tests pass.

The minimum cloud order is:

1. Reject HTTP startup before opening a socket or creating local state unless a
   healthy PostgreSQL bundle is available.
2. Add narrow OAuth and provider bootstrap roles or fixed-search-path security
   functions because workspace identity is not known before token or provider
   binding resolution.
3. Resolve token, client, membership, account, grant, plan, territory, and
   staff authority from one database snapshot.
4. Atomically bind access admission to workspace, actor, OAuth session, tool,
   canonical argument hash, single-use approval, quota, and durable audit.
5. Port platform control, provider, search, deal, privacy, job, document, and
   remaining stateful tool domains behind explicit contracts. No dual write,
   shadow write, reverse sync, or fallback is permitted.

The current `TenantContext` has no authoritative actor or OAuth-session fields,
and file-backed approvals bind only workspace, tool, and argument hash. Those
are launch blockers because one workspace member could otherwise consume
another member's approval and creator/updater attribution would be unprovable.
The PostgreSQL foundation may supply the schema primitives, but Phase 3 must
perform the runtime rewiring and prove the actual restored service path.

### OAuth certification audit round two: changes required

The fresh second auditor rejected the repaired Phase 1 snapshot with two
additional high-severity result-disclosure paths:

- A punctuation-free earlier address claim such as `Miami FL 33139` or
  `Austin TX 73301` could be hidden before a safe `Dallas, TX 75201` tail. The
  parser collected only the comma-delimited tail, so Local Scout and JV Partner
  city or ZIP grants could release the contradictory record and log `allowed`.
- Result validation accepted a `ToolResult` subclass or an exact instance with
  a shadowing `to_mcp_result` attribute. FastMCP later invoked that unvalidated
  serializer and released a denied property even though middleware had checked
  safe attributes and recorded `allowed`.

Required repair: collect every recognizable state, city-state, ZIP, and ZIP+4
claim from capability-declared fields regardless of comma punctuation, and make
the eventual serialized result exactly the representation that was validated.
Nested undeclared data and provider `raw` remain outside the territory scanner.

### OAuth certification audit round three: changes required

A new read-only auditor rejected the second repaired snapshot after preserving
an identical tracked patch hash at audit start and finish. Its end-to-end matrix
released all 36 contradictory records across Local Scout and JV Partner,
`properties` and `listings`, semicolon, slash, and whitespace separators, and
exact city, ZIP, and ZIP+4 grant cases. Earlier `Austin TX 73301` or `Miami FL
33139` claims disappeared when a declared `Dallas` / `TX` / `75201` tail was
present, so middleware returned the record and recorded an ordinary `allowed`
event.

The same audit found that an exact `TextContent` object could be mutated from
the `text` discriminator to `image` after construction. Result extraction
checked the Python class and text body but not the discriminator, so the invalid
client-visible block passed validation and was returned with an `allowed` audit
event.

Two false-denial controls also became mandatory: `123 Oak Ct` must not treat the
street suffix as Connecticut, and `100 Main St Unit 33101` must not treat an
explicitly labeled unit number as a Florida ZIP. The repair must begin with the
full rejected matrix and these controls as red tests, then recognize and
reconcile every exact address claim without broad scanning or ordinary-address
false positives. A fourth fresh audit is required after the complete gate set.

### OAuth certification audit round four: changes required

After the third repair passed 1,959 tests, the controller and a new independent
auditor found the same remaining high-severity boundary. A state-only earlier
claim without a ZIP was still recognized only before a comma or the end of the
string. Semicolon, slash, and whitespace separators could therefore hide
`Miami FL` or `Austin TX` before a declared `Dallas TX 75201` tail.

The auditor reproduced the release through real FastMCP middleware in all 48
combinations of Local Scout and JV Partner, `properties` and `listings`, exact
Dallas city and `75201` ZIP grants, and the six contradictory addresses. Every
call returned the record and wrote an ordinary `allowed` event. This invalidates
the otherwise green suite and blocks a commit.

The next repair must preserve that full matrix as red evidence, reconcile
state-only address claims across the same separators, and add collision controls
so broader recognition does not reinterpret ordinary `in`, `or`, `Ct`, `NE`,
unit numbers, or street-name tokens as locations. Every full gate and another
brand-new audit remain mandatory.

### OAuth certification audit round five: changes required

A fifth independent protocol review rejected the next repaired snapshot even
though its existing focused selection passed 321 tests. The review exercised
the real FastMCP client, production access middleware, exact tool result, and
client-visible `CallToolResult` path.

The review reproduced all 24 expected denials across Local Scout and JV Partner
profiles and the declared `properties` and `listings` collections as releases.
It separately reproduced all 48 city, state, and ZIP expected denials as
releases across both profiles and both collection forms. Case variants, full
state names and codes, country suffixes, bare city-state claims, and bare ZIP
claims followed by a country suffix were not reconciled safely.

Required location fields that were omitted or null also reached the client. A
Crexi `map_asset`-shaped property with empty `address` and `city`, declared
Texas state, and Miami data only in undeclared text or raw fields was released.
At the same time, a valid country-text control without a state was denied. This
proves the current result contract is neither sufficiently typed nor safely
normalized.

The next repair must first preserve the 24-case and 48-case protocol matrices,
the Crexi-shaped case, and every omitted/null case as permanent red tests. It
must then validate or intersect the requested search and independently validate
every returned property. Restricted profiles must fail closed on unknown,
ambiguous, incomplete, undeclared, or conflicting location data without using
arbitrary provider raw payloads as authority. Two new independent approvals are
required after all focused and repository-wide gates pass.

### OAuth certification audit round six: changes required

After preserving the fifth-review matrices and passing 2,342 repository tests,
a fresh neutral reviewer inspected a frozen OAuth snapshot through the real
FastMCP protocol path. Its independently computed composite fingerprint was
identical at review start and finish:
`0e27d093af6457f9717ca73a84209c5017b3d357d500e3776b2d2d0a2c4a94f9`.
The reviewer made no worktree edits.

The review rejected the snapshot with four reproducible findings:

- High: a Texas Local Scout could execute `owner_lookup` for
  `90 Ocean Drive, Miami, FL` when an in-scope `Harris County, TX` argument was
  supplied beside it. The numbered address was treated as unresolvable and
  ignored instead of intersected with the grant.
- High: a Texas result containing
  `33101; 100 Main St Dallas TX 75201` was released because the earlier Florida
  ZIP claim was not reconciled with the safe trailing claim.
- High: an exact `75202` ZIP grant released a record whose declared city was
  `Dallas TX 75201` and whose separate `zip_code` was `75202`; the ZIP embedded
  in the city field was discarded.
- Medium: a legitimate `100 Main Street, Washington, DC 20001` result was
  denied because the city name `Washington` was misread as the state of
  Washington.

Controller inspection added permanent contract cases for country-suffixed city
values that omit state, state-only and ZIP-only city values, present-but-empty
ZIP values, non-ASCII digit lookalikes, and labeled unit numbers followed by a
country suffix. The next repair begins with all reviewer and controller cases
as real-protocol red tests. The rejected review does not count toward the two
fresh approvals required on the final repaired hash.

### OAuth certification clean-context audit: changes required

The frozen candidate preserved the earlier round-six escapes and later
property-bearing egress inventory as real FastMCP client and
production-middleware regressions, but a genuinely clean-context audit found
additional release blockers. That hash is rejected and cannot be committed.

The candidate is frozen and uncommitted at composite tracked-plus-untracked
content hash
`764037631b70be2c394fa42e3a98d2b44ae99e93faa57e7f988f808a31c4437d`.
Controller verification on 2026-08-03 independently passed the permanent
24-case and 48-case protocol matrices and adjacent required-location cases
inside a 155-test selector, all 1,889 access tests, the strict three-test mixed
lifecycle gate, and all 3,600 repository tests. Only the categorized upstream
Authlib deprecation remains.

The clean audit reproduced a nested Miami, Florida property release for every
one of these Texas-restricted JV-visible tools through a real FastMCP client and
the production access middleware: `overnight_changes`,
`stale_listing_signals`, `match_buyers`, `meeting_briefing`, `deal_timeline`,
`counterparty_dossier`, and `match_lenders`. Each tool had no request territory
parameter and no result territory contract, so middleware released the payload
and recorded an `allowed` event. The strongest production implementation case
used `deal_timeline`, whose store persists arbitrary event detail JSON and
returns it verbatim.

The same audit reproduced a false denial for a complete canonical result under
an exact `Washington, DC` grant and request when the result used the
production-shaped split `address="100 Main Street"`, `city="Washington"`,
`state="DC"`, and `zip_code="20001"`. The parser misclassified the city as the
state of Washington and required the street-only address to repeat the city.
`New York, NY` and other municipality/state-name collisions share the defect.

The authority normalization review also found six exact, unambiguous place
names present in the pinned Census/postal data but rejected before tool
execution because the request parser forbids every digit in a city name:
`Route 7 Gateway, CT 06877`; `Kickapoo Site 1, KS 66439`; `Kickapoo Site 2, KS
66439`; `Kickapoo Site 5, KS 66439`; `Kickapoo Site 7, KS 66439`; and `Kickapoo
Site 6, KS 66527`. Real FastMCP calls with matching exact grants and requests
were denied before execution even though the checked-in authority recognized
each city/state/ZIP combination.

Tests-first repair evidence is now preserved. Before geography production
edits, the new real-protocol selector reported `16 failed, 1 passed`; after the
narrow authority fix it reports `17 passed`, and the combined relevant
territory selection reports `1,849 passed`. Before any seven-tool production
edit, the new store-workflow selector reported `7 failed, 1 passed`, with all
seven releases audited `allowed`. The store-workflow repair is still in
progress and has no green status. After adding exact-denial, positive-flow, and
malformed-carrier controls but before the tailored production repair, that
selector reports `28 failed, 8 passed`. Controller rerun of the locked priority
matrices now reports `125 passed`: the permanent 24 cross-profile/collection
cases, 48 exact state/city/ZIP cases, 48 required address/city/state
omitted-null-empty-type cases, and four real Crexi-mapping blank-location cases.
The first completed store-backed boundary, the production `deal_timeline`
wrapper using the actual `DealStore`, reports `8 passed, 32 deselected`; the
second, the production `match_buyers` wrapper using the owned buyer store,
reports `9 passed, 43 deselected` on approved Python 3.11.15, with all 50
disposition tests also green.
The third, the production `match_lenders` wrapper using the workspace-owned
lender database, reports `17 passed, 35 deselected`, with all 19 financing
operations tests green. The production `overnight_changes` and
`stale_listing_signals` wrappers now add actual SnapshotStore/DealStore
positive and denial paths; together they report `18 passed, 42 deselected`,
with all 10 command tests green. The two relation workflows remain in
progress, so this is not a phase approval.
An independent approved-Python selector covering normalized case, state
names/codes, country suffixes, ZIP/ZIP+4 equivalence, exact city/state pairs,
and incomplete or ambiguous city failures reports `120 passed`.
A separate read-only inventory confirmed the locked matrices are exact real
FastMCP client plus production-middleware tests, but also recorded two
pre-commit obligations: `tests/access/test_result_territory.py` is still an
untracked certification file and therefore is not permanent until included in
the eventual approved commit, and the phase specification cited the wrong
containing module. The specification citation and its stale approval language
are now corrected; inclusion of the untracked regression module remains a
commit-time gate. A separate 12-case real-protocol selector confirms that an
unknown supplied city/state/ZIP combination fails closed even under a valid
state grant.

A preliminary read-only location-contract QA then reproduced another request
escape through the real FastMCP client and installed middleware: list-valued
territory parameters silently discarded null, numeric, and whitespace-only
members, allowing a valid Dallas sibling to authorize and execute the call.
The exact two-profile protocol selector first reported `6 failed`. After the
request parser was changed to require a JSON list whose every member is a
nonblank string, the complete round-seven geography module reports `23 passed`;
the adjacent legacy territory selectors report `24 passed`. This finding is
preserved and OAuth remains yellow.

One earlier reported approval remains excluded because its reviewer
participated in rejected rounds. OAuth remains yellow and uncommitted until all
new findings are permanent real-protocol regressions, the repair is fully
gated, and two fresh independent reviews approve the new stable hash.

### OAuth round-seven controller reconciliation 2026-08-03: tree is RED

Independent read-only controller verification on 2026-08-03 contradicts the
green evidence recorded above. The recorded `4,112 passed` repository result is
not reproducible on the current tree. The same command, on the approved Python
3.11.15 interpreter with `-p no:cacheprovider` and an isolated `CRE_MCP_ROOT`,
now reports **52 failed and 4,078 passed**, reproduced twice at 97.36 and 91.76
seconds. Only the categorized third-party Authlib deprecation warning appears.

The failure set is not stable. It changes with test execution order:

| Selection | Result |
| --- | --- |
| Full repository | 52 failed, 4,078 passed |
| `tests/access` | 4 failed, 2,415 passed (a different set) |
| `test_result_territory.py` alone | 30 failed, 1,016 passed |
| `test_territory_release_regressions.py` alone | 8 failed, 763 passed |
| `test_territory_round7_market_binding.py` alone | 140 passed |
| `test_territory_round7_geo.py` alone | 2 failed, 263 passed |
| `test_territory.py` alone | 17 passed |
| `test_result_territory.py` then round-seven geography | 32 failed, 1,279 passed |
| `test_territory_round7_market_binding.py` then geography | 2 failed, 401 passed |

`test_market_intel_releases_exact_national_city_and_zip_georefs` passes all
eight cases when run alone and fails all eight inside the full repository run.
Adding more tests makes some failures disappear and others appear, so the
authorization outcome depends on module import order rather than on the request,
the grant, and the returned record alone. Failures surface through the
`unresolvable` branch of `access denied: tool result is outside or unresolvable
for this workspace's territory`.

Three defects are now recorded as the active blockers:

1. Territory enforcement is order dependent. This is an authorization defect,
   not only a test-isolation defect, because a load order can change whether a
   record is released. Consequently every previously recorded green number for
   this phase, including `4,112 passed`, `2,401 passed`, and the focused
   `132`/`389`/`406` results, is order conditional and is not valid release
   evidence.
2. A live release escape exists.
   `test_ambiguous_same_name_city_grant_fails_closed_before_release` is a
   fail-closed control. It passes in isolation and fails inside `tests/access`,
   so an ambiguous same-name city grant releases under some orders.
3. Deterministic false denials remain.
   `test_market_intel_releases_census_geocoder_city_name_shape` fails in
   isolation for both restricted profiles, and the round-six Washington, DC
   split-location control
   `test_exact_state_name_city_grant_releases_split_location_record[washington-dc-*]`
   still reproduces.

A structural gap is also recorded. `_geo_record_claims` in
`src/cre_mcp/access/engine.py` is documented as deriving claims only when every
populated GeoRef carrier reconciles, but it inspects only `level`,
`state_fips`, `name`, `county_fips`, `tract`, `cbsa`, and `zip`. There is no
declared-key allowlist, so any other populated key such as `zip_code`,
`place_fips`, `csa`, `county_name`, `state_name`, or `metro` is silently ignored
and cannot contradict a grant. Both of the two most recent reviewer findings
were this class. Enumerating carriers one reviewer at a time has now failed
seven rounds.

No candidate hash may be frozen and no reviewer may be commissioned until the
full suite is green and proven order stable across at least three independent
orderings. OAuth remains yellow and uncommitted. The PostgreSQL and
source-rights worktrees remain frozen and untouched.

### OAuth round-seven authority reconciliation 2026-08-03: focused gates GREEN, phase YELLOW

This checkpoint supersedes the active-defect description immediately above,
but it does not erase that rejected evidence. OAuth remains dirty,
uncommitted, and ineligible for review approval until the wider ordering,
repository, packaging, lifecycle, and exact-tree gates are complete.

The current repair replaces name-only city inference with pinned Census place,
county, ZCTA, tract, and CBSA relationships. Same-name city claims require one
surviving Census place after county and ZIP intersection. Exact assigned postal
localities that are not Census places, including Bronx and Staten Island, may
fall back only when an assigned city/ZIP pair and the ZIP's authoritative
county set converge. A real tract carrier must exist in the pinned Census tract
authority; a city-level result carrying any tract remains denied because the
available public relationships cannot prove tract-to-place containment.

The earlier GeoRef declared-key gap is now locked at the actual result boundary:
the closed typed result is recursively validated with unknown fields forbidden,
and six provider-shaped nested carrier aliases are permanent real FastMCP tests
for both restricted profiles. Postal fallback consistency is also permanent at
two protocol boundaries: ZIP-level market GeoRefs and county-contained rent
comparables for Bronx 10451 and Staten Island 10301. Ambiguous Burbank, Chevy
Chase, Pewaukee, and Superior grants remain pre-execution denials.

Current command evidence:

- the locked 24 cross-profile/collection, 48 exact state/city/ZIP, 48 required
  address/city/state malformation, and four real Crexi-shaped empty-location
  cases pass as one 125-test real FastMCP/middleware gate;
- `test_result_territory.py` passes 1,047 tests;
- `test_territory.py` plus `test_territory_round7_geo.py` pass 302 tests;
- release-regression plus portfolio-property modules pass 808 tests;
- all seven store-backed workflow regressions pass 86 tests;
- the expanded market/GeoRef module plus same-name ambiguity controls pass 169
  tests;
- deterministic rebuilds from the pinned official inputs are byte-identical:
  52,565 ZCTA/place rows at SHA-256
  `8a0d94a3743873cf2b9761c3aa79fa7884703903611f6f9163b758ddb0822476`,
  and 254,935 national relationship rows (`C=3,221`, `P=33,298`,
  `Z=46,777`, `T=169,733`, `B=1,906`) at SHA-256
  `ec28297f8f5bd29328c1cd696a7d007c3d80f083def465de3e6b017393e6b6e8`.

The earlier order-dependence finding is cleared by the 2,484-case access run,
both 2,283-case opposite-order runs, and the 4,195-case repository run recorded
below. Two fresh neutral reviewers independently repeated the gates, inspected
the full diff, reproduced the exact `e96da4b...` hash, and approved it with no
blocking finding. The exact candidate was committed as `88e3082`.

### Superseded portal branches: selective salvage only

Read-only archaeology confirmed backend tip `8a44d4c` and frontend tip
`13abbf5` must not be merged or cherry-picked wholesale. The frontend is native
DOM JavaScript with no React dependency, JSX, package lock, or React build. Its
customer Deals, Search, entitlements, saved-deal, and pseudo-router surfaces are
forbidden by the founder's connection-only decision.

Safe inputs are limited to:

- pinned `reicon@1.1.103` MIT provenance, tarball integrity, source digests, and
  digest tests as a pattern; the required React entry must be independently
  verified before use;
- exact redirect, PKCE, replay, live bearer, owned-session, and revocation
  invariants already rooted in the OAuth lineage;
- self-scoped consent and privacy queue primitives, after adding correction,
  fulfillment, processor propagation, evidence, and concurrency controls;
- internal role, reason, live recheck, append-only audit, rollback, route-shape,
  accessibility, reduced-motion, CSP, and browser-test patterns.

The inherited browser lacks real production authentication. Its tests inject a
bearer through loopback middleware while the UI sends only same-origin cookies.
The launch build therefore needs a real secure browser-session/BFF boundary with
CSRF controls. The internal console also needs a separately protected origin or
router, workforce identity, and network controls. Path hiding on the customer
application is insufficient. Host-derived absolute redirects are rejected
unless trusted-host validation is proven.

## Verified command evidence

| Date | Scope | Command summary | Result |
| --- | --- | --- | --- |
| 2026-08-01 | Capability matrix | Import production server and compare registered names to matrix | 274 registered, 274 classified, no missing or stale entries |
| 2026-08-01 | Profiles | Recompute allowed tools from the live matrix | Local 103; National 115; Full 274; JV 170 |
| 2026-08-01 | OAuth full suite | `PYTHONPATH=<oauth>/src ... python -m pytest -p no:cacheprovider -q` | 1,521 passed; one categorized third-party Authlib deprecation |
| 2026-08-01 | OAuth strict lifecycle | OAuth test file with asyncio debug and lifecycle warnings promoted | 35 passed; no pending application task |
| 2026-08-01 | OAuth focused repetition | Real HTTP initialize and cleanup selection repeated ten times | 20 total focused passes; no pending-task stderr |
| 2026-08-01 | OAuth audit round one | Independent result-policy and lifecycle review after 1,800 passing tests | Changes required: 2 high and 2 medium findings; no approval |
| 2026-08-01 | OAuth audit round two | Fresh read-only diff audit plus end-to-end adversarial serializer and hidden-location probes | Rejected: 2 high disclosure paths; checked-in focused selection was 87 passed |
| 2026-08-01 | OAuth audit round three | Fresh read-only stable-diff audit plus a 36-case middleware matrix and mutated discriminator probe | Rejected: 36/36 contradictory records released, invalid `TextContent` discriminator released, and 2 ordinary-address false denials; focused baseline was 111 passed |
| 2026-08-01 | OAuth audit round four | New independent FastMCP matrix after 1,959 green tests | Rejected: 48/48 state-only contradictory records released and audited as allowed across profile, collection, separator, and exact-grant variants |
| 2026-08-01 | OAuth audit round five | New independent real-FastMCP protocol matrices after a 321-test focused baseline | Rejected: 24/24 cross-profile/collection denials and 48/48 city/state/ZIP denials released; incomplete typed locations and a Crexi-shaped blank-location record also released |
| 2026-08-02 | OAuth audit round six | Fresh neutral stable-fingerprint diff review plus independent real-FastMCP probes after 2,342 green tests | Rejected: one multi-field request escape, two returned-location contradictions, and one Washington, DC false denial; no reviewer edits |
| 2026-08-03 | OAuth mandatory protocol confirmation | Root-run real FastMCP/middleware selector covering the permanent 24 and 48 matrices, required fields, Crexi blank locations, unknown envelopes, and refreshed-detail denial | 155 passed; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth access confirmation | `PYTHONPATH=<oauth-cert>/src ... python -m pytest -p no:cacheprovider -q tests/access` with isolated temporary root | 1,889 passed; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth strict lifecycle confirmation | Real HTTP OAuth test followed by two entitlement tests with asyncio debug and lifecycle warnings promoted | 3 passed; no unclosed loop, socket, transport, stream, task, or coroutine |
| 2026-08-03 | OAuth full-suite confirmation | `PYTHONPATH=<oauth-cert>/src ... python -m pytest -p no:cacheprovider -q` with isolated temporary root | 3,600 passed in 74.01 seconds; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth locked territory matrices | Approved Python 3.11.15 interpreter; real FastMCP client plus installed production middleware: count lock, 24 cross-profile/collection cases, 48 exact state/city/ZIP cases, 48 required-field cases, and four Crexi blank-location cases | 125 passed; one categorized third-party Authlib deprecation; OAuth remains yellow |
| 2026-08-03 | OAuth store workflow incremental boundary | Production `deal_timeline` wrapper with actual `DealStore`, in-scope and denied/malformed cases through FastMCP middleware | 8 passed, 32 deselected; one categorized third-party Authlib deprecation; six workflows remain |
| 2026-08-03 | OAuth buyer-match incremental boundary | Approved Python 3.11.15; production `match_buyers` wrapper with actual owned buyer store, nested request-location enforcement, typed release projection, and denied/malformed cases through FastMCP middleware | 9 passed, 43 deselected; all 50 disposition tests passed; one categorized third-party Authlib deprecation; five workflows remain at this checkpoint |
| 2026-08-03 | OAuth lender-match incremental boundary | Approved Python 3.11.15; production `match_lenders` wrapper with actual workspace-owned lender database, list-valued request intersection, closed result projection, whole-call mixed-location denial, and full-operator compatibility | 17 passed, 35 deselected; all 19 financing-operations tests passed; one categorized third-party Authlib deprecation; four workflows remain |
| 2026-08-03 | OAuth command-workflow incremental boundary | Approved Python 3.11.15; production `overnight_changes` and `stale_listing_signals` wrappers backed by actual SnapshotStore/DealStore records, mixed-result denial, malformed/unknown/key-mismatch denial, and full-operator compatibility | 18 passed, 42 deselected; all 10 command tests passed; one categorized third-party Authlib deprecation; two relation workflows remain |
| 2026-08-03 | OAuth normalization boundary | Approved Python 3.11.15 interpreter; real FastMCP/middleware selectors for case, state names/codes, country suffixes, ZIP/ZIP+4, exact city/state pairs, and unknown/ambiguous cities | 120 passed; one categorized third-party Authlib deprecation; OAuth remains yellow |
| 2026-08-03 | OAuth protocol regression inventory | Independent read-only count and helper-path inspection plus approved-Python reproduction | Exact 73-node count-plus-24-plus-48 selector and 72-node required-field/Crexi/optional-ZIP selector passed; test module remains untracked and spec citation must be corrected before freeze |
| 2026-08-03 | OAuth specification integrity | Correct stale module citation, rejected-candidate approval language, and unknown-combination policy; approved-Python state-grant regression selector | 12 passed for nonexistent supplied city/state/ZIP fail-closed behavior; regression module still must be included in the eventual commit; OAuth remains yellow |
| 2026-08-03 | OAuth strict location-array boundary | Preliminary QA real-FastMCP reproduction across Local Scout and JV Partner, followed by tests-first repair on approved Python 3.11.15 | RED: 6 failed because null, numeric, and blank members were discarded beside Dallas; GREEN: 23 round-seven geography tests and 24 adjacent territory tests passed; OAuth remains yellow |
| 2026-08-03 | OAuth seven store-backed workflow boundary | Approved Python 3.11.15; all seven rejected JV-visible workflows exercised through production-backed stores, tailored closed result projections, real FastMCP client, and installed middleware, followed by native relation tests | 108 passed: 86 store-workflow protocol cases plus 22 native relation tests; no generic transitional result DTO remains; broader OAuth phase remains yellow |
| 2026-08-03 | OAuth round-seven scalar and property geography boundary | Approved Python 3.11.15; real FastMCP/middleware matrix covering invalid collection members, unresolved compound tails, incomplete street/locality tails, strict parcel addresses, structured-address contradictions, empty owner parcels, county-FIPS conflicts, and valid unit formats | RED captured 24 valid-unit false denials; repair rerun is 195 passed with one categorized third-party Authlib deprecation; independent preflight is still expanding permanent escape coverage, so OAuth remains yellow |
| 2026-08-03 | OAuth market and GeoRef binding RED | Approved Python 3.11.15; tests-only real FastMCP/middleware matrix for exact request-to-GeoRef binding, GeoRef carrier reconciliation, every rent-comparable location, and exact compare-market multisets | 107 collected; RED is 68 failed and 39 passed after adding six independently reproduced carrier contradictions and four controls; no production change was made for this matrix at the checkpoint |
| 2026-08-03 | OAuth adjacent positive-control gate RED | Approved Python 3.11.15; combined `test_result_territory.py`, `test_territory_round7_geo.py`, and `test_territory_release_regressions.py` run against the current uncommitted tree | 2,006 passed and 6 failed: valid `NE`/`OR` directional-address requests and Denver county-comp controls are over-restricted; must be repaired without weakening fail-closed territory enforcement |
| 2026-08-03 | OAuth round-seven binding and typed-location repair | Approved Python 3.11.15; root and independent reruns of the expanded geography, exact market/result binding, and portfolio property-address modules through real FastMCP clients and installed production middleware | 406 passed; every earlier market escape is closed; explicit same-place `Dallas, TX: 75201` and `Dallas, TX zip 75201` controls pass under both restricted profiles; one categorized third-party Authlib deprecation; OAuth remains yellow |
| 2026-08-03 | OAuth portfolio property-address boundary | Approved Python 3.11.15; malformed request and returned addresses, empty owner-property collections, count consistency, and valid property anchors through FastMCP/middleware | 37 passed; typed owner properties are nonempty and every returned property carries a complete authoritative address; one categorized third-party Authlib deprecation; OAuth remains yellow |
| 2026-08-03 | OAuth capability-schema focused gate | Approved Python 3.11.15; capability coverage and declaration validation after adding typed result-location bindings | 11 passed; one categorized third-party Authlib deprecation; broader gates and independent approvals remain |
| 2026-08-03 | OAuth wider territory/profile gate RED | Approved Python 3.11.15; 16-file focused selection spanning result territory, release regressions, round-seven matrices, profiles, dual enforcement, server authority, relations, geo, and market tools | 2,396 passed and 12 failed: two production-emitted county GeoRefs used a city-shaped name, while ten pre-binding positive fixtures no longer provided exact request/result identity; OAuth remains yellow |
| 2026-08-03 | OAuth county-producer and stale-control repair | Approved Python 3.11.15; exact rerun of the prior failing analyze-deal, authoritative county, and property-bearing positive-control families through FastMCP/middleware | 42 passed and 1,775 deselected; the producer now emits a county-shaped authoritative name and controls use exact request/result levels with required rent-comparable locations; one categorized third-party Authlib deprecation; full focused rerun remains |
| 2026-08-03 | OAuth wider territory/profile gate GREEN | Approved Python 3.11.15; exact rerun of the 16-file result-territory, release-regression, round-seven, profile, dual-enforcement, server-authority, relations, geo, and market selection | 2,408 passed in 22.90 seconds; one categorized third-party Authlib deprecation; the earlier 12 failures are repaired without weakening exact binding; OAuth remains yellow pending access/full gates and two fresh approvals |
| 2026-08-03 | OAuth complete access gate GREEN | Approved Python 3.11.15; `pytest -p no:cacheprovider -q tests/access` with an isolated cache database | 2,381 passed in 22.39 seconds; one categorized third-party Authlib deprecation; OAuth remains yellow pending repository-wide and independent approval gates |
| 2026-08-03 | OAuth repository-wide gate GREEN | Approved Python 3.11.15; `pytest -p no:cacheprovider -q` with an isolated cache database after exact-binding and county-producer repairs | 4,092 passed in 87.46 seconds; one categorized third-party Authlib deprecation; this suite does not override later independent gaps and OAuth remains yellow |
| 2026-08-03 | OAuth national GeoRef authority gap RED | Independent read-only real FastMCP/middleware probes using exact request, grant, and returned identity | Dallas/75201 controls release, but exact Seattle and Los Angeles city GeoRefs and 98101/90001 ZIP GeoRefs are denied after execution because result reconciliation depends on 13-city and six-ZIP fallback tables; add permanent protocol regressions and authoritative national reconciliation before review |
| 2026-08-03 | OAuth national GeoRef regressions locked | Approved Python 3.11.15; permanent real FastMCP client plus production-middleware city/ZIP controls and same-state contradiction controls across both restricted profiles | RED: 8 exact Seattle/Los Angeles and 98101/90001 releases denied after execution; 8 wrong-county/CBSA contradictions already denied; full market-binding module baseline was 8 failed and 116 passed |
| 2026-08-03 | OAuth national relationship repair | Integrity-checked Census county, place/county, assigned ZCTA/county, and July 2023 county/CBSA authority; exact national release and contradiction selectors followed by full market-binding module | 16 targeted protocol cases passed; 124 market-binding cases passed; data artifact SHA-256 `9953a1130ec03c8d050cf85187fdf3a0eaf66a42a026bebcc49fdcb7207bd9db`; OAuth remains yellow |
| 2026-08-03 | OAuth national-normalization collision repair | Complete access gate found an independent-city grammar collision with unpunctuated `Kansas City MO` street tails; grammar narrowed while preserving county-equivalent identities and exact national controls | RED: 2 access failures; focused repair selector passed 21; complete access rerun passed 2,401 with one categorized third-party Authlib deprecation; OAuth remains yellow pending repository-wide and review gates |
| 2026-08-03 | OAuth post-national repository-wide gate GREEN | Approved Python 3.11.15; captured `PYTHONPATH=<oauth-cert>/src ... python -m pytest -q --disable-warnings` session after national authority and normalization-collision repair | Exit 0; 4,112 passed in 78.02 seconds; one categorized third-party Authlib deprecation; OAuth remains yellow pending two fresh independent approvals |
| 2026-08-03 | OAuth post-repair review candidate frozen | Deterministic SHA-256 over sorted tracked plus untracked non-ignored working files, executable bits, and bytes in `/Users/maxmedawar/LoopnetMCP-oauth-launch-cert` | `b443393d62e20acba8e77f539630524be2c7cfee2320bd4c49008a982494c3c3` across 932 files; dirty and uncommitted; two fresh neutral reviews commissioned against this exact hash |
| 2026-08-03 | OAuth final locked-priority gate | Approved Python 3.11.15; exact count-lock plus permanent 24 cross-profile/collection, 48 state/city/ZIP, 48 omitted/null/empty/non-string required-location, and four Crexi blank-location real FastMCP selectors | 125 passed in 1.34 seconds; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth final strict lifecycle gate | `PYTHONASYNCIODEBUG=1`; ResourceWarning and RuntimeWarning promoted for real HTTP OAuth initialize/list/call/close followed by two async entitlement tests | 3 passed in 1.49 seconds; no owned lifecycle warning; only categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth authority reproducibility and packaging gate | Re-download pinned Census sources, rebuild to temporary output, byte-compare artifact, build wheel without dependencies, inspect packaged authority files, recheck dependency/lock diff, capability counts, port 8000, compile, and diff whitespace | Rebuild byte-identical at `9953a113...`; all three gzip authorities plus attribution in wheel; no dependency or lock change; 274 capabilities and 103/115/274/170 profile counts unchanged; no port-8000 listener; compile and `git diff --check` pass |
| 2026-08-03 | OAuth frozen-candidate relation escape RED | Fresh neutral reviewer B, exact frozen hash `b443393d...`, real FastMCP client and installed production middleware, exact `00601` request/grant | A ZIP GeoRef named `Adjuntas, PR 00601` carrying Utuado county FIPS `72141` released under both restricted profiles even though authoritative Adjuntas city counties and ZIP counties had no common intersection with that carrier; frozen candidate rejected and review approvals invalidated |
| 2026-08-03 | OAuth city/ZIP/county intersection repair | Tests-first permanent GeoRef and county-sale property regressions through real FastMCP and production middleware across Local Scout and JV Partner; shared reconciliation repair | RED: 2 GeoRef and 2 returned-property releases; GREEN: all 4 exact cases pass and the complete round-seven market plus geography modules pass 389 tests; OAuth remains yellow pending diagnostic findings, full gates, a new hash, and two fresh reviews |
| 2026-08-03 | OAuth embedded GeoRef ZIP carrier RED | Fresh neutral reviewer A, real FastMCP client and installed production middleware, exact Dallas request/grant | A city GeoRef named `Dallas, TX 78701` released under both restricted profiles because its embedded Austin ZIP was discarded when the dedicated ZIP field was absent; current repair tree rejected and no approval permitted |
| 2026-08-03 | OAuth embedded GeoRef ZIP repair | Permanent contradictory and matching embedded-ZIP controls across Local Scout and JV Partner, with embedded name ZIP promoted into the shared carrier set before city/county/ZIP reconciliation | RED: 2 contradictory releases and 2 matching controls passed; GREEN: all 4 exact cases and all 132 round-seven market-binding tests pass; OAuth remains yellow pending remaining diagnostics, full gates, a new hash, and two fresh reviews |
| 2026-08-03 | OAuth controller repository-wide reverification RED | Independent read-only controller rerun of the recorded full-suite command on approved Python 3.11.15 with `-p no:cacheprovider` and an isolated `CRE_MCP_ROOT`, executed twice | 52 failed and 4,078 passed in 97.36 and 91.76 seconds; the recorded `4,112 passed` does not reproduce; only the categorized third-party Authlib deprecation appears; OAuth moved to RED |
| 2026-08-03 | OAuth order-dependence isolation matrix | Same interpreter and flags; each implicated access module run alone and in pairs to test outcome stability | `tests/access` 4 failed / 2,415 passed; `test_result_territory.py` alone 30 failed / 1,016 passed; `test_territory_release_regressions.py` alone 8 failed / 763 passed; `test_territory_round7_market_binding.py` alone 140 passed; `test_territory_round7_geo.py` alone 2 failed / 263 passed; `test_territory.py` alone 17 passed; result-territory then geography 32 failed / 1,279 passed; market-binding then geography 2 failed / 401 passed |
| 2026-08-03 | OAuth order-dependent authorization outcome | `test_market_intel_releases_exact_national_city_and_zip_georefs` run alone and inside the full repository suite | 8 passed alone and 8 failed in the full run; authorization outcome depends on module import order, so every prior green number for this phase is order conditional and is not release evidence |
| 2026-08-03 | OAuth fail-closed control escape RED | `test_ambiguous_same_name_city_grant_fails_closed_before_release` run alone and inside `tests/access` | Passes in isolation and fails inside the access suite; an ambiguous same-name city grant releases under some orders |
| 2026-08-03 | OAuth deterministic false denials RED | Isolated real-FastMCP reruns of the affected positive controls | `test_market_intel_releases_census_geocoder_city_name_shape` fails for both restricted profiles in isolation; the round-six `washington-dc` split-location control still reproduces |
| 2026-08-03 | OAuth GeoRef declared-key gap | Read-only inspection of `_geo_record_claims` in `src/cre_mcp/access/engine.py` | No declared-key allowlist exists; only `level`, `state_fips`, `name`, `county_fips`, `tract`, `cbsa`, and `zip` are inspected, so populated undeclared carriers such as `zip_code`, `place_fips`, `csa`, `county_name`, `state_name`, and `metro` cannot contradict a grant |
| 2026-08-03 | OAuth frozen-worktree confirmation | Read-only status of every MedawarCRE worktree plus listener check | oauth-cert 42 modified and 6 untracked paths; postgres 6 uncommitted paths; source-rights 114 uncommitted files, both left untouched; no listener on port 8000 |
| 2026-08-03 | OAuth locked priority protocol gate after authority repair | Approved Python 3.11.15; count lock plus permanent 24 cross-profile/collection, 48 exact state/city/ZIP, 48 required-field, and four real Crexi empty-location cases through real FastMCP and installed middleware | 125 passed in 1.95 seconds; one categorized third-party Authlib deprecation; OAuth remains yellow |
| 2026-08-03 | OAuth closed nested GeoRef carrier gate | Six provider-shaped undeclared location aliases injected inside an otherwise valid Dallas GeoRef across Local Scout and JV Partner, through real FastMCP and installed middleware | 13 passed including matrix cardinality; every alias denied after execution by the closed recursive result contract |
| 2026-08-03 | OAuth exact postal GeoRef and county-containment repair | Tests-first Bronx 10451 and Staten Island 10301 controls across ZIP-level market GeoRefs and county-contained rent comparables, both restricted profiles; same-name ambiguity controls included | RED: four market and four rent controls denied; GREEN: expanded market plus ambiguity selection passed 169; postal fallback is allowed only with exact assigned ZIP and authoritative county convergence |
| 2026-08-03 | OAuth focused post-authority corpus | Approved Python 3.11.15; typed results, place/GeoRef authority, release/portfolio regressions, and store-backed workflows run in four isolated commands | 1,047 + 302 + 808 + 86 passed; one categorized third-party Authlib deprecation per process; no focused failure |
| 2026-08-03 | OAuth Census authority deterministic rebuild | Pinned official county, place, ZCTA/county, ZCTA/tract, CBSA, and ZCTA/place inputs; approved builder scripts; temporary outputs byte-compared with checked-in gzip artifacts | 52,565 ZCTA/place rows, SHA-256 `8a0d94a3...`; 254,935 national rows (`C=3221`, `P=33298`, `Z=46777`, `T=169733`, `B=1906`), SHA-256 `ec28297f...`; both byte-identical and `gzip -t` clean |
| 2026-08-03 | OAuth complete access gate | Approved Python 3.11.15; isolated runtime root; cache provider disabled | 2,484 passed in 26.74 seconds; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth opposite-order stability gates | The four previously unstable territory modules run in both collection orders from separate isolated runtime roots | 2,283 passed in 31.14 seconds and 2,283 passed in 24.32 seconds; one categorized third-party Authlib deprecation per process |
| 2026-08-03 | OAuth repository-wide gate | Approved Python 3.11.15; isolated runtime root; cache provider disabled | 4,195 passed in 86.50 seconds; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth strict lifecycle gate | Asyncio debug enabled; ResourceWarning, RuntimeWarning, and pytest unraisable warnings promoted to errors | 4 passed in 1.56 seconds; no owned lifecycle warning; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth packaging and static gates | Compile source, diff whitespace, package-data-only manifest review, wheel inspection, authority gzip integrity, release-locked capability counts, and port 8000 check | Green; 274 capabilities; Local 103, National 115, Full 274, JV 170; no port-8000 listener; dependencies and lockfiles unchanged |
| 2026-08-03 | OAuth review candidate frozen | SHA-256 over sorted tracked plus untracked non-ignored files, framed by path length/path, executable or symlink mode, content length, and bytes | `e96da4b8345099bb1bac64d5af54e397da8e7fcd0aee14d194a3abebfbc5ca65` across 932 files; candidate worktree unchanged after freeze; two fresh neutral approvals required |
| 2026-08-03 | OAuth independent release review A | Fresh read-only exact-hash review; full diff, adversarial result-release probes, complete access, both opposite orders, lifecycle, repository, package, compile, capability, and integrity gates | APPROVED exact `e96da4b...`; 2,484 access, 2,283 plus 2,283 opposite-order, 4 lifecycle, and 4,195 repository tests passed; no blocking finding |
| 2026-08-03 | OAuth independent release review B | Fresh read-only exact-hash review; authoritative lifecycle, live entitlement and quota, migration, cleanup, complete repository, both opposite orders, package, compile, capability, and integrity gates | APPROVED exact `e96da4b...`; 4,195 repository, 4 lifecycle, and both 2,283 opposite-order runs passed; no blocking finding |
| 2026-08-03 | OAuth certification commit | Stage the unchanged twice-approved candidate, recheck staged diff, and commit one phase boundary | `88e3082109f80722e78d0712ed07028f050e015f` (`feat: certify authoritative OAuth territory enforcement`) |
| 2026-08-03 | PostgreSQL repaired candidate frozen | SHA-256 over sorted tracked plus untracked non-ignored files using the same path, mode, and content framing as OAuth | `2af2a9077a2f933110cf68b7386a0830ef814df327756420e82f38abf20c6388` across 940 files; 62 native PostgreSQL and 1,832 repository tests passed; compile, wheel SQL resource, secret-pattern, diff, and port checks green; two fresh neutral approvals required |
| 2026-08-03 | PostgreSQL independent reviews reject first candidate | Two fresh read-only release-correctness reviews of exact `2af2a907...` | Both reviewers found the same high-severity migration preflight gap: a relation directly owned by the migration login passed because direct and inherited ownership were conflated; candidate invalidated without commit |
| 2026-08-03 | PostgreSQL direct-ownership regression and repair | Minimal ordinary-table reproduction first captured RED; authority query then separated direct owner OIDs from effective group ownership | RED: relation case did not raise; GREEN: database, schema, relation, function, and type direct ownership rejected, pre-mutation database-owner rejection passed, and group-inherited ownership remained accepted |
| 2026-08-03 | PostgreSQL replacement gates | Sequential native PostgreSQL and repository suites plus compile, wheel-resource, secret-pattern, diff-whitespace, and port checks | 69 PostgreSQL tests passed in 22.37 seconds; 1,839 repository tests passed in 108.46 seconds; packaged SQL resources present; no secret-pattern hit or port-8000 listener |
| 2026-08-03 | PostgreSQL replacement candidate frozen | Deterministic SHA-256 over sorted tracked plus untracked non-ignored files with path, mode, length, and content framing | `f68a9a489602ef0b22614e899e5800820c0579e12002afce83c7aaa613f0e9e6` across 940 files; two fresh neutral approvals required |
| 2026-08-03 | PostgreSQL replacement independent review C | Fresh read-only exact-hash contract, authority, PG16, migration, RLS, recovery, package, and repository review | APPROVED exact `f68a9a4...`; 7 ownership regressions, 69 PostgreSQL tests, and 1,839 repository tests passed; no blocking finding or hash drift |
| 2026-08-03 | PostgreSQL replacement independent review D | Fresh read-only exact-hash static and isolated execution review | APPROVED exact `f68a9a4...`; deterministic hash reproduced across 940 paths; no candidate assertion failure or release blocker; environmental cluster restart failure did not alter the verdict |
| 2026-08-03 | PostgreSQL certification commit | Stage the unchanged twice-approved candidate, check the staged diff, and commit one phase boundary | `5089748aaa6f9f726db5801f866a130974d1eb89` (`feat: add certified PostgreSQL persistence foundation`); worktree clean |
| 2026-08-01 | PostgreSQL repair snapshot | Release-audit regressions, PostgreSQL selection, full repository, native restore/service smoke, compile, wheel, diff, secret, and artifact checks | 31 release regressions passed; 62 PostgreSQL tests passed; 1,832 full tests passed; first audit findings repaired; two fresh approvals still required |
| 2026-08-01 | Source-rights implementation snapshot | Source-rights selection, impacted selection, full repository, compile, diff, secret, artifact, and egress inventory checks | 64 source-rights tests passed; 1,946 full tests passed; independent egress inventory clear; two fresh release approvals still required |
| 2026-08-03 | Source-rights wheel registry RED and repair | Pre-review wheel inspection followed by a package-data regression and smallest `pyproject.toml` repair | RED: `cre_mcp/source_rights/registry.json` absent from wheel; GREEN: package-data test passed and rebuilt wheel contains the canonical registry |
| 2026-08-03 | Source-rights replacement gates | Sequential focused and repository suites plus compile, wheel, inventory, secret, diff, and port checks | 161 source-rights tests passed; 1,947 repository tests passed in 65.33 seconds; registry packaged; no secret-pattern hit or port-8000 listener |
| 2026-08-03 | Source-rights review candidate frozen | Deterministic SHA-256 over sorted tracked plus untracked non-ignored files with path, mode, length, and content framing | `e58c7215ce7a75c9d2f0740423be93753728864536585d634b7db8a54e158503` across 929 files; two fresh neutral approvals required |
| 2026-08-03 | Source-rights first candidate rejected | Two fresh read-only release-correctness reviews of exact `e58c721...` | Valid blockers: the registry admitted `hosted_cloud_allowed=true` with `trusted_local_only=true`, the hosted gate ignored the contradictory local-only flag, and a clean interpreter import of the gate cycled through eager access middleware; no approval or commit |
| 2026-08-03 | Source-rights fail-closed policy and import repair | Tests first at registry load, public hosted gate, and clean-interpreter import boundaries | RED: both contradictory-policy paths released and the clean import raised a partial-initialization `ImportError`; GREEN: schema rejects the contradiction, gate defense-in-depth denies it, and access middleware exports load lazily without breaking their public imports |
| 2026-08-03 | Source-rights repaired gates | Sequential source-rights and repository suites plus compile, wheel-resource, secret-pattern, diff-whitespace, and port checks | 164 source-rights tests passed in 4.30 seconds; 1,950 repository tests passed in 71.88 seconds; canonical registry and runtime modules are packaged; no secret-pattern hit or port-8000 listener |
| 2026-08-03 | Source-rights repaired candidate frozen | Deterministic SHA-256 over sorted tracked plus untracked non-ignored files with path, mode, length, and content framing | `4c33265f12dec0927fb34a6c344158174ef5bb89f8bda2a2c3363fd873986f04` across 929 files; two fresh neutral approvals required |
| 2026-08-03 | Source-rights repaired independent review C | Fresh read-only exact-hash contract, adversarial, full-suite, registry, gate-ordering, egress, output/storage, and packaging review | APPROVED exact `4c33265...`; 217 focused/adversarial and 1,950 repository tests passed; hash reproduced before and after; no release-correctness blocker |
| 2026-08-03 | Source-rights repaired independent review D | Fresh read-only exact-hash contract, focused, related, full-suite, wheel-install, secret, import, and static review | APPROVED exact `4c33265...`; 164 focused, 394 related, and 1,950 repository tests passed; hash reproduced before and after; no release-correctness blocker |
| 2026-08-03 | Source-rights certification commit | Stage the unchanged twice-approved candidate, check the staged diff, and commit one phase boundary | `3185ccb595cf305f9c69f15ae2730f2d6fa75ee7` (`feat: enforce certified source-rights controls`); worktree clean |
| 2026-08-03 | Certified cloud-platform integration | New `integration/cloud-platform-launch` worktree based on certified OAuth; cherry-pick certified PostgreSQL and source-rights commits; reconcile enforcement order at the shared middleware and internal snapshot projection seams; run the complete repository suite | `0b5a87b05901018ccadde6cf45eccdbd4c8e3e0a`; 4,444 passed in 144.38 seconds; one categorized third-party Authlib deprecation; worktree clean; no old 45-tool server implementation merged |
| 2026-08-03 | Consolidated customer MCP surface | Lock and export the full 45-versus-274 reconciliation; construct a separate hosted facade; preserve exact entitlement, quota, territory, source-rights, approval, result, and audit enforcement; verify real HTTP OAuth and full repository | `802b16cec823f74fc41cab10cb4de9602d56fea7`; 4,459 passed in 164.56 seconds; one categorized third-party Authlib deprecation; 253 grouped actions, 21 internal-only MCP capabilities, profile counts 8/10/20/14; no old server implementation imported and no deployment performed |
| 2026-08-04 | Integrated audit round one RED | Fresh independent authorization, database/isolation, provider/deployment, source-rights, and lifecycle review of integrated HEAD `4167d50` | Critical consentless OAuth code exfiltration; high uncertified hosted deal exposure, hosted SQLite authority, obsolete deployment path, approval/audit/jobs/privacy gaps; medium historical-JV, logout CORS, request exhaustion, and cookie-site findings; no public action performed |
| 2026-08-04 | OAuth/JV audit repair and second review | Tests-first exact-client DCR, explicit consent, exact Origin and Host, CSRF, one-time pending requests, public deal-route removal, streamed body caps, bounded/rate-limited public state, one-per-user browser sessions, identity-wide live JV separation, and retryable consent | Independent reviewer rejected two intermediate candidates, then approved the repaired candidate after adversarial concurrency and cross-workspace checks; 140 focused tests, 4,526 repository tests, 5 connection tests, 10 Operations tests, both builds and audits, compile, pip, secret-pattern, and diff gates passed; committed as `d82e600286682c70639c3130e4f96661d7085a3c` |
| 2026-08-01 | Protected backup | SQLite URI read-only integrity and FK checks | `integrity_check=ok`; zero FK violations; file unchanged |
| 2026-08-01 | Hosted persistence archaeology | Enumerate every direct SQLite connector plus JSON, JSONL, and blob authority from HTTP registration to storage | Generic compatibility shim rejected; explicit cloud persistence bundle and domain-port migration required |
| 2026-08-01 | Portal salvage archaeology | Inspect backend `8a44d4c` and frontend `13abbf5` with file-level provenance and route boundaries | No wholesale merge; React rebuild required; exact safe primitives and forbidden customer surfaces mapped |

## Clerk connection-only checkpoint 2026-08-04

The browser surface contains only sign-in, connection status, precise safe
failure guidance, and the OAuth resume action. It has no customer dashboard,
deal, billing, profile, or settings surface. Clerk proves a person, while
MedawarCRE binds only a preprovisioned identity and re-reads membership and
account state before issuing an authorization code. Suspended workspaces,
removed memberships, ambiguous memberships, revoked browser sessions, CSRF
failures, non-S256 challenges, injected authority selectors, invalid redirects,
replayed grants, and stale entitlement state fail closed.

The standalone Clerk credential is intentionally absent. The adapter was
verified through the official SDK boundary using a deterministic provider fake,
and no development secret is required until private staging. The integrated
security audit and fresh post-repair review remain deliberately later in the
founder-approved launch sequence, so this row remains yellow rather than making
an unsupported release claim.

Evidence:

- Worktree `/Users/maxmedawar/LoopnetMCP-cloud-integration`, branch
  `integration/cloud-platform-launch`, base `802b16cec823f74fc41cab10cb4de9602d56fea7`.
- Initial red: the focused identity tests failed to import
  `cre_mcp.platform.connection` before implementation.
- Focused backend gate: 67 passed, followed by a final 58-test OAuth, identity,
  schema, and configuration recheck after bounding OAuth state input. Both runs
  carried one categorized third-party Authlib deprecation.
- Complete repository gate: 4,475 passed in 121.14 seconds with the same
  categorized warning.
- Connection UI: 4 Vitest cases passed; TypeScript and production Vite build
  succeeded; npm audit reported zero vulnerabilities.
- Static gates: source and tests compile, `pip check` is clean, and
  `git diff --check` is clean.
- Real hosted proof: fake verified Clerk session to preprovisioned identity,
  opaque browser session, dynamic client registration, S256 code exchange,
  OAuth token, MCP initialize, and authorized `cre_pipeline.list_searches` call.
- Exact phase commit is recorded by the following program checkpoint because a
  Git commit cannot contain its own content-derived hash.
- Canonical SecondBrain note was not present on the local filesystem or an
  available connector. This ledger is the reopened canonical repository record;
  the missing external note remains an evidence limitation, not a release claim.
- Fresh integrated security review remains scheduled in the founder-approved
  audit step. No public deployment, DNS, billing, or customer data action ran.

## Internal Operations Console checkpoint 2026-08-04

The Operations Console is a separate, internal-only React application. It is
not served by the customer connection origin and contains no customer portal,
deal, pricing, billing, or account-management surface. Clerk proves the staff
identity once; MedawarCRE exchanges that proof for an opaque, short-lived,
HttpOnly, Secure, SameSite=Strict operator cookie. Only token and CSRF digests
are stored. Every request then re-reads the server-owned internal role. Support
is read-only, platform administrators may perform reasoned mutations, and any
identity with a live JV grant is denied even if it also appears in the internal
operator table.

The server exposes bounded workspace lookup and details, membership and grant
state, territory and provider mappings, account state, payload-free provider
quarantine and replay, source-rights state, runtime health, and append-only
audit. Exact Origin and Host checks, credentialed CORS, CSRF, target ownership,
reason codes, and reason text gate mutations. Provider payloads and credentials
are never returned to the browser.

Evidence:

- Worktree `/Users/maxmedawar/LoopnetMCP-cloud-integration`, branch
  `integration/cloud-platform-launch`, base
  `103d08e3d1b2066d13ead198e70d15c109308d9d`.
- Backend authorization and BFF gate: 9 Operations Console tests; related
  operations, admin, OAuth, source-rights, schema, and configuration gate:
  57 passed with one categorized third-party Authlib deprecation.
- Complete repository gate: 4,485 passed in 132.09 seconds with the same
  categorized warning.
- Operations application gate: 7 Vitest cases passed; TypeScript and production
  Vite build succeeded; npm audit reported zero vulnerabilities.
- Dependency provenance: `reicon@1.1.103` is locked with its npm integrity and
  MIT upstream commit in `web/operations/REICON_PROVENANCE.md`.
- Static gates: source and tests compile, `pip check` is clean, and
  `git diff --check` is clean.
- Anti-slop review: the surveyor field-ledger world uses one restrained
  warm-charcoal palette, a custom populated survey plat, a treated section
  index, sharp chamfered geometry, native controls, and specific operational
  data. It has no purple gradient, generic hero, pill clutter, icon tiles,
  decorative glow, card lift, fake controls, hidden entrance content, or hover
  movement. Responsive and reduced-motion rules are present. A real contrast
  defect found during review was repaired: placeholder text now measures
  5.13:1 against its field.
- The in-app Browser runtime reported no available browser instance, so a real
  pointer, keyboard, zoom, and viewport pass was not fabricated. That check is
  retained as a private-staging gate, and this row remains yellow pending the
  integrated audit.
- No public deployment, DNS, billing, or real customer-data action ran.
- The exact phase commit is recorded by the following program checkpoint because
  a Git commit cannot contain its own content-derived hash.

## Integrated audit repair checkpoint 2026-08-04

The first full-system audit is complete but the integrated audit phase remains
red. The OAuth, connection, hosted-route, logout, request-exhaustion, and JV
separation findings are repaired and independently cleared in `d82e600`. Public
registration now maps only an exact server-owned client shape, advertises only
`mcp:tools`, and cannot expose uncertified deal routes. A passive GET cannot
issue a code. The connection screen presents client, destination, workspace,
and access before an exact-origin, exact-host, CSRF-protected POST consumes a
single pending request.

Public request bodies are streamed under pre-append byte caps. Registration is
deduplicated under an immediate transaction. Registration, authorization,
token, revocation, and Clerk exchange have source-scoped process limits, while
private-edge limits remain mandatory. Pending and browser-session stores are
transactionally bounded; browser sessions are one per user. Cross-host browser
cookies deliberately use `SameSite=None; Secure` under the existing Origin,
Host, and CSRF checks. A failed authorization-code write restores the explicit
consent request for retry. Any identity holding a live JV grant in any workspace
is denied internal-admin authority; revoked, future, and expired grants do not
create a permanent block.

Evidence:

- Repair commit: `d82e600286682c70639c3130e4f96661d7085a3c` on
  `integration/cloud-platform-launch`.
- Final focused security gate: 140 passed with one categorized third-party
  Authlib deprecation.
- Final repository gate: 4,526 passed in 204.82 seconds with the same warning.
- Connection application: 5 Vitest cases, production build, and zero npm audit
  findings. Operations application: 10 Vitest cases, production build, and
  zero npm audit findings.
- Source and tests compile; `pip check`, secret-pattern review,
  `git diff --check`, and staged diff checks passed.
- The required embedded browser runtime exposed no `eb_*` tools. No external
  browser substitute was used. DOM interactions were clicked in Vitest; real
  pointer, keyboard, zoom, and viewport proof remains a private-staging gate.
- No deployment, DNS, billing, provider mutation, customer-data access, or
  production action occurred.

The next active phase is hosted persistence correctness. Commit `5bcd5c0`
establishes the first fail-closed boundary: `create_http_app`, `run_server`, the
standalone Starlette factory, and the exported global MCP catalog cannot bind a
public HTTP surface through SQLite, JSON, or JSONL. They require the PostgreSQL
builder, verify pool and schema readiness, and currently reject startup after
that check because the hosted domain repositories are not yet certified. Legacy
persistence can enter HTTP tests only through a test-owned patched builder.

That boundary passed 4,535 repository tests in 194.11 seconds with the one
categorized third-party Authlib deprecation, plus compile, dependency, secret,
and diff checks. A fresh read-only reviewer found and drove closure of bundle
lifecycle leaks, uncertified standalone deal-route mounting, the raw internal
MCP HTTP bypass, and default stdio compatibility, then approved the unchanged
boundary as safe to commit. It does not certify hosted functionality.

PostgreSQL OAuth/provider bootstrap, request-scoped repositories, atomic
approval, quota, and durable audit, then jobs, privacy, container, migration,
recovery, and private-staging proof remain release blockers. The integrated
audit row cannot turn green until those paths are repaired and receive a fresh
full-system review.

## Phase evidence template

For each phase, append:

- Worktree, branch, base, and final commit
- Narrow contract and explicit non-scope
- Exact red command and failure
- Files changed
- Focused and regression commands with counts
- Full-suite command with count and warning classification
- Compile, diff, migration, integrity, and security checks
- First independent audit findings
- Repairs and their regression tests
- Second independent audit verdict
- SecondBrain note URI or path and reopen verification
- Residual limitations and the next active phase
