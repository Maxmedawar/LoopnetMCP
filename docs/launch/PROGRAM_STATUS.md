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
- Production secrets: managed secret store of the deployment platform, injected
  at runtime through least-privilege service identity. A local `.env` is a
  development artifact holding disposable values only, never the production
  source of truth. Recorded 2026-08-06.

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
| Cloud integration phase | `integration/cloud-platform-launch` at `830c914`; certified OAuth, PostgreSQL, source rights, connection-only Clerk, internal Operations, Stripe test, and Skool lifecycle histories integrated; OAuth/JV repair, fail-closed hosted persistence, exact service roles, migration `0002`, and the one-snapshot OAuth authority repository committed; 4,568 repository tests passed |
| Customer MCP surface | Commit `802b16cec823f74fc41cab10cb4de9602d56fea7`; 274 internal capabilities retained, 253 exact actions grouped, 21 MCP capabilities internal-only, all 45 historical IDs reconciled; visible counts Local 8, National 10, Full 20, JV 14 as recorded then. Superseded: JV became 12 at Phase 5G (`49adb9e`) and 11 at the hosted withholding correction 2026-08-06 |
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
| 🟢 | Consolidated customer MCP surface | Hosted HTTP uses 20 coherent grouped facades with profile listings Local 8, National 10, Full 20, JV 14 as recorded then, JV now 11 after the hosted withholding correction 2026-08-06; all grouped actions resolve to exact server-owned capability IDs; internal services and 21 internal MCP capabilities remain unexposed; commit `802b16c`; 4,459 repository tests passed |
| 🟢 | Hosted OAuth PostgreSQL authority checkpoint | Exact 1,024-file candidate `2bf5a43d...`, migration checksum `3058382c...`, catalog fingerprint `40f025fc...`, 102 PostgreSQL tests, 4,568 repository tests, local image build and truth-import smoke, final wheel `324f777c...`, and two hash-stable independent approvals; committed as `830c914` |
| 🟡 | Clerk identity and connection flow | Implementation and local gates complete: official Clerk adapter, connection-only React screen, OAuth discovery/DCR/PKCE/revocation, live authority rechecks, and a real hosted MCP call. Phase 5I then closed a first-sign-in takeover: the adapter accepted an unverified Clerk primary email as the join key to a preprovisioned user. Integrated audit remains scheduled after Stripe and Skool per the founder-approved sequence, and a live Clerk test instance is still an unmet staging gate |
| 🟡 | Internal Operations Console | Implementation and local gates complete: separate React control ledger, pinned Reicon provenance, opaque Clerk operator sessions, live staff and JV separation, exact Origin and Host, CSRF, reasoned mutations, provider quarantine, source rights, health, and append-only audit. Integrated security and real-browser staging gates remain scheduled |
| 🔴 | Search and deal persistence | Tenant records, evidence, score versions, object-ID isolation, privacy behavior |
| 🔴 | Combined opportunity index | Server-side deduplication, provenance, staff-only access, pagination and conflict tests |
| 🔴 | Scheduled saved searches | Idempotent queue, current entitlement and territory checks, audit, internal status |
| 🟡 | Stripe test integration | Implementation and local gates complete: test-only credentials and mode enforcement, rotating signed webhooks, durable lifecycle journal, fixed-host GET-only complete-list reconciliation, atomic projection repair, active-session effects, and reasoned operator audit. Representative fixtures still require a real Stripe test-account staging proof; integrated audit remains scheduled after Skool |
| 🟡 | Skool reconciliation | Local gates complete: operator-only supported join tasks, exact member binding without implicit grant, rotating signed relay secrets, payload-free timestamped review receipts, stale and partial uncertainty, restrictive mismatch handling, manual revoke, OAuth invalidation, and internal Console controls. Private staging must prove the configured relay and operator runbook |
| 🔴 | Privacy and retention | Notice, export, correction, deletion, retention, processor propagation, audit |
| 🟢 | Source-rights controls | First replacement `e58c721...` was rejected and repaired. Exact replacement `4c33265...` fails closed on contradictory local/hosted policy and cleanly imports; 164 focused and 1,950 repository tests passed; two fresh reviewers approved the unchanged hash; committed as `3185ccb` |
| 🟡 | Production secret boundary | Phase 5J: every credential field is `SecretStr`, environment injection outranks the optional `.env`, rotation needs no rebuild, a missing secret fails closed, no serialization or route discloses a value, and `deploy/DEPLOY.md` records exact names and least-privilege consumers. No provider chosen; a live Clerk network smoke test is an external staging gate |
| 🔴 | Private staging | Reproducible package, TLS, migrations, workers, monitoring, backup and restore exercise, rollback |
| 🔴 | Integrated security audit | OAuth consent, public-client, route exposure, request-bound, browser-session, logout, and identity-wide JV findings repaired in `d82e600`; all public HTTP entrypoints fail closed through `5bcd5c0`; exact service roles, migration `0002`, and the one-snapshot OAuth authority repository are committed through `830c914`; PostgreSQL domain repositories, durable atomic admission/audit, jobs/privacy, and deployment correctness remain open blockers |
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
| 2026-08-04 | Exact hosted PostgreSQL service-role checkpoint | Add dormant no-login, no-inherit OAuth, provider-ingress, provider-reconciliation, worker, and scheduler roles; require one exact login membership; pin `search_path` before every shared preflight and restore it on pool reset; reject group ownership, direct ACLs, and default ACLs across the current database; extend catalog and clean-restore verification | First reviewer rejected the candidate for late/resettable `search_path`, unverified group-role ACLs, and stale restore inventory. A second reviewer found broader shared-preflight and cross-schema variants. All findings were repaired. Final independent revalidation found no remaining scope finding; 82 PostgreSQL and 4,548 repository tests passed; committed as `46e79a8` |
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

The active phase remains hosted persistence correctness. Commit `5bcd5c0`
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

Commit `46e79a8` establishes separate dormant OAuth, provider-ingress,
provider-reconciliation, worker, and scheduler database group roles. Migration
`0002` and commit `830c914` activate only the narrow OAuth function boundary.
The other service roles remain dormant. Exact login, object-authority, default
ACL, ownership, catalog, backup, and restore contracts fail closed.

## Reconciled persistence phase records (imported 2026-08-06)

The nine sections below were written on the control branch
`feature/final-launch-control` and were absent from this branch's ledger,
even though every commit they describe is in this branch's own history:
`ccc24a3`, `7be60ef`, `b58dfe0`, `aac18a8`, `fb505a3`, `7a03724`,
`cef768f`, `b0947d7`, and `49adb9e`. They are imported verbatim so the
canonical ledger records the work this branch actually contains.

Nothing else was taken from the control branch. Its dead-hosted-capability
inventory section is deliberately NOT imported: the
`Hosted withholding correction checkpoint 2026-08-05 to 2026-08-06` section
in this file supersedes it, and the control branch's issue ledger and
repository baseline predate the 2026-08-06 JV corrections recorded here.

No code was merged: this change touches `PROGRAM_STATUS.md` and nothing else
from that branch. An earlier draft of this paragraph said "the two branches
share no source file", which is false — they diverge across 149 files under
`src/` because the control branch sits at an older base. The operative claim is
the narrow one, and it is the one stated.

## Atomic PostgreSQL request admission completed 2026-08-04

The integration branch now contains the bounded atomic-admission foundation at
`ccc24a36f93a3dfa0c34f7363228b5c7febd3606`. The exact reviewed candidate was
`3851500191d4a6b7e1aa1fdae153fb033448068af7f92834b8892ec0393c5a7a`
across 1,030 tracked plus untracked non-ignored files.

Migration `0003` provides one atomic admission transaction and one bound final
audit function. It revalidates live OAuth and tenant authority, binds every
effective request and policy input, consumes approval and UTC quota together,
and writes a durable append-only audit. Legacy independently callable approval,
quota, and audit functions are unavailable to the admission role. Only a fresh,
non-replayed allow owns execution.

Two audit rounds found and repaired incomplete invocation binding, padded and
Unicode-whitespace quota drift, replay execution and finalization risk,
incomplete denial and UTC evidence, and invalid-Unicode error escape. The final
shared quota grammar is exactly `^[a-z][a-z0-9_]{0,63}$` with no stripping or
normalization in the repository, OAuth resolver, or SQL. Replayed and finalized
outcomes are rejected before final-audit database access.

Final gates are 42 atomic tests, 144 PostgreSQL 16.14 tests, and 4,610 complete
repository tests, plus compile, native backup and distinct-cluster restore,
readiness, immutable-`0002` upgrade, exact ACL, packaging, secret, diff, and
deterministic hash checks. Catalog fingerprint
`c93a3060257613ef34b13f9bd8d75c6784ff46f6df3e1bde5f5006bc8f13bffd`,
migration checksum
`34c363ef3cb1efad079a21140367d8d1e8dab8ca593784d8c995d9c0e82f4b6a`,
and wheel digest
`237252f4950b00cf0591430f4ad04b863a68154dbb92c9aa62bc66e288d6fd61`
were independently reproduced. Two fresh read-only reviewers approved the
unchanged final candidate with no finding.

The Codex Security preflight still could not inherit `PYTHON`, so the controller
did not repeat that loop and used the required fresh-reviewer fallback. No
interface file changed. No deployment, DNS, billing, paid resource, provider,
customer-data, or production action occurred.

Hosted HTTP remains fail-closed. The exact unfinished phase is hosted request
lifecycle wiring for the one-snapshot authority and atomic admission
repositories, followed by explicit request-scoped platform, provider, search,
deal, privacy, job, document, and truth-asset repositories without local-state
fallback. Private staging, final integrated security approval, readiness packet,
and founder-approved cutover remain red.

## Hosted request lifecycle wiring completed 2026-08-04

The integration branch now connects the certified one-snapshot OAuth authority
and atomic PostgreSQL admission repository to the real hosted MCP middleware.
The exact twice-reviewed candidate was
`15b00840e99dcbb37a6534a8b01b5b2272d2084509a15e21254cd76a8454b3e0`
across 1,033 tracked plus untracked non-ignored files. It was committed as
`7be60ef05d1aa245d4e03d4717460897261ff371` (`feat(hosting): wire atomic
request lifecycle`).

Hosted OAuth resolution, admission, and final recording run off the event loop.
Every call binds workspace, actor, OAuth session, MCP transport session, typed
JSON-RPC request ID, exact capability, and sanitized arguments before atomic
admission. Only a fresh, non-replayed, non-finalized allow owns execution.
Cancellation and failure paths record a bound failed final decision, and a
successful result is not released until result-territory and source-rights
checks pass and its successful final audit is durable. Hosted installation
requires explicit OAuth, admission, and audit authorities, rejects a local
registry, and restores the exact prior middleware and authentication state if
reconfiguration fails.

The first frozen review candidate was rejected for missing stable logical
request identity and incomplete middleware rollback. Both defects were captured
as failing regressions and repaired. The next release review rejected the
repaired candidate because `capability_matrix.json` was absent from the wheel,
which made an isolated install load zero capabilities. Package data now includes
the matrix and a missing matrix fails closed. The rebuilt isolated wheel digest
is `4d3463905ffe0125ea5f70263dfa62a4823f4ccd201c1b7c2c780306d3d339b5`.
It loads 274 capabilities, 253 grouped customer actions, and 21 internal-only
capabilities with customer counts Local 8, National 10, Full Operator 20, and JV
Partner 14.

Final gates are 4,640 complete repository tests and 144 PostgreSQL 16.14 tests,
plus 81 focused lifecycle, surface, and package checks, compile, diff, changed-
file secret, UI-scope, and isolated-wheel checks. Two fresh read-only reviewers
independently reproduced the exact 1,033-file candidate, reran security,
authorization, isolation, replay, database, source-rights, package, surface, and
startup checks, and approved it with no finding.

`PYTHON` remained absent in Codex Security and both fresh reviewer shells. The
controller did not repeat the failed helper loop; every gate used the explicit
approved interpreter at `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`. No
interface file changed. No deployment, DNS, billing, paid resource, provider,
customer-data, or production action occurred.

Hosted HTTP remains intentionally fail-closed because the production persistence
builder still rejects the uncertified customer-domain layer. The exact next
phase is request-scoped PostgreSQL persistence for platform, provider, search,
deal, privacy, job, document, and truth-asset state with no SQLite, JSON, JSONL,
local-blob, dual-write, shadow-write, or fallback path. Private staging, the
final integrated security audit, readiness packet, and founder-approved public
cutover remain red.

## Request-scoped PostgreSQL domain authority completed 2026-08-04

The integration branch now contains the bounded Phase 5A authority substrate at
`b58dfe09da713642813f28ac928967ca408fbf53` (`feat(postgres): bind
request-scoped domain authority`). The exact twice-reviewed repaired candidate
was `073d42f3d4062d8a1421b0956b087f71c451e0d24c2791e26c5dca99c199b4c3`
across 1,037 tracked plus untracked non-ignored files.

Hosted requests now require one aggregate repository bundle containing explicit
platform, provider, search, deal, privacy, job, document, and truth-asset ports.
The bundle is available only inside the admitted request scope. Migration
`0004` binds the exact fresh allow to transaction-local RLS identity and uses a
shared transaction advisory lock to serialize binding against finalization.
Aggregate and document authority use revocable leases, so detached task copies
cannot retain authority after the request scope exits. The source-rights
document check receives the exact injected document repository during execution.

The first frozen candidate, `d33b7c9...`, was rejected by the independent
reviews. The findings were retained as regressions: a detached task could retain
raw aggregate authority, admission binding could race finalization, and the
document repository was not bridged into source-rights execution. The three
focused regressions first failed, then passed after the repair. A reverse-order
PostgreSQL race proves a binder waiting behind an uncommitted final decision
rechecks and rejects that finalized invocation. A separate detached-document
test proves document authority is also revoked.

Final gates are 122 focused lifecycle, OAuth, hosting, source-rights, and
PostgreSQL scope tests, 152 native PostgreSQL 16 tests, and 4,652 complete
repository tests, plus compile, diff, changed-file secret, UI-scope,
deterministic-wheel, and isolated-wheel checks. Catalog fingerprint
`dac27380da49dd88e8cebfeb656a12096e50a364fc9d099af23d6049218c8ab9`
and wheel digest
`f00794a22d6110671829dd7986eae30df5f10a4ba9375dcece8f02870a44d937`
were recorded. The isolated wheel loads 274 capabilities, 253 grouped customer
actions, and 21 internal-only capabilities with visible counts Local 8,
National 10, Full Operator 20, and JV Partner 14. Both fresh read-only reviewers
approved the unchanged final candidate with no remaining finding. The
post-commit lifecycle gate passed 30 tests and the code worktree is clean.

Codex Security still did not inherit `PYTHON` after restart. The controller did
not repeat the failed loop and used the explicit interpreter at
`/Users/maxmedawar/LoopnetMCP/.venv/bin/python` plus two fresh read-only
reviewers. No interface file changed. No deployment, DNS, billing, paid
resource, provider, customer-data, or production action occurred.

This checkpoint does not claim production domain parity. The production builder
still fails closed with `hosted PostgreSQL domain repositories are not yet
certified`. The exact next phase is implementing and certifying the eight real
PostgreSQL domain repositories behind these ports with no SQLite, JSON, JSONL,
local-blob, dual-write, shadow-write, or fallback path. Private staging, the
final integrated security audit, readiness packet, and founder-approved public
cutover remain red.

## PostgreSQL document-attestation read authority completed 2026-08-04

Phase 5B is certified and committed on `integration/cloud-platform-launch` as
`aac18a8ca6100a9f5c4a2beae8cc7ac7afb57c3b` (`feat(postgres): add document
attestation authority`). The exact twice-reviewed candidate was
`78fd0950367edc1d828fb9f0dae76b9797b3c75e35cf85fb5a03bd62e2e6cee7`
across 1,041 tracked plus untracked non-ignored files.

Migration `0005` adds a PostgreSQL document-rights record that stores the
attested URL only as a SHA-256 digest. It binds each record to one workspace,
actor, and exact OAuth session through native foreign keys. The app role has
read-only access under row-level security that requires all three current
request values. A same-workspace session belonging to another actor cannot be
attached to the record and cannot select it.

The repository accepts only the exact active document port, admission, and
server context. It uses the admitted PostgreSQL transaction, returns the
existing source-rights record contract, and fails closed on inactive scope,
database failure, missing or revoked records, expiry, malformed values, URL
digest mismatch, or insufficient purpose. The existing source-rights bridge
calls this repository in hosted execution. It never constructs or falls back
to the trusted-local SQLite authority.

The preserved RED was
`ModuleNotFoundError: No module named 'cre_mcp.postgres.document_attestations'`.
During controller review, a native adversarial test exposed that a workspace-only
session foreign key could attach another actor's session. The final migration
uses a three-column workspace, session, and actor constraint, and the attack is
now rejected by PostgreSQL.

Final evidence is 14 focused document-authority tests, 166 native PostgreSQL 16
tests, and 4,666 complete repository tests. The post-commit document and
source-rights selector passed 36 tests. Compile, dependency, diff, changed-content
secret, package-resource, isolated-wheel, customer-surface, and listener checks
passed. Catalog fingerprint
`e6240265c6f31b5c4cd8e4a7946c354c7a0b87182940db6780bf5694f06d3c50`,
migration digest
`89b5ab0672dc3f3b9cdeb72fa33582ef3506a41b91fd8dd5fb05baf191a5c83e`,
and fixed-epoch wheel digest
`21c714992435d7b05e0bcaa62cd218edf6c3df0f59ade09473e6af9d48af615c`
were recorded. The isolated wheel preserves 274 capabilities, 253 grouped
actions, 21 internal-only capabilities, and visible counts 8/10/20/14.

Two fresh read-only security and release-correctness reviewers independently
reproduced the candidate before and after review and approved it with no
finding. Their independent coverage included exact-session RLS probes, restore,
backup, catalog, source-rights, lifecycle, installed-wheel, surface, and
production fail-closed checks. No interface file changed, so the complete
anti-slop interface audit found no applicable UI defect.

No deployment, DNS, billing, paid resource, provider mutation, customer-data,
or production action occurred. Production hosted startup remains intentionally
blocked until the other seven repositories are certified and wired together.
Internal document approval and revocation also remain out of this slice. The
next bounded implementation phase is PostgreSQL truth-asset persistence for the
document pipeline. Platform, provider, search, deal, privacy, job, staging,
integrated security, readiness, and founder-approved cutover remain red.

## PostgreSQL truth-asset persistence completed 2026-08-04

Phase 5C is certified and committed on `integration/cloud-platform-launch` as
`fb505a39d2d1172938440103d8acf6ff323a69e0` (`feat(postgres): add truth asset
persistence`). The exact twice-reviewed repaired candidate was
`c670742f1c47397f8133071bac2ba551f2d4184502db1c68149c7e74a5285bcb`
across 1,045 tracked plus untracked non-ignored files.

Migration `0006` adds workspace-scoped raw document blobs, structured document
metadata, and claim lineage under PostgreSQL row-level security. PostgreSQL
checks every blob digest, rejects non-finite numeric and bounding-box values,
and cascades workspace deletion through the full blob, document, and claim
graph. The app role can insert raw blobs and read only their workspace and
digest keys. It cannot select raw document content. Backup and restore roles
retain their explicit least-authority contracts.

Hosted document ingestion now requires the exact active truth-asset repository,
admission, and workspace, actor, and OAuth-session binding. A detached task
cannot regain a trusted-local store after the request lease is revoked. Saves
are transactional and idempotent, mutable document metadata and claims are
replaced together, malformed stored values fail closed, and cancellation cannot
escape while a PostgreSQL worker remains active.

External document URLs still require attestation before retrieval and again at
the socket boundary. Retrieval pins the validated public DNS answer. It uses a
synchronous curl receipt callback with no producer queue, aborts with
`CURL_WRITEFUNC_ERROR` before an over-limit chunk enters retained body storage,
and does not let cancellation unwind the request or attestation lease while the
network worker remains active. Hosted local paths remain denied. Trusted local
stdio preserves its existing SQLite and filesystem behavior.

The preserved implementation RED was `ModuleNotFoundError: No module named
'cre_mcp.postgres.truth_assets'`. Initial independent reviews then found valid
detached fallback, unbounded URL buffering, worker cancellation, metadata
replacement, IPv6 canonicalization, workspace teardown, and non-finite numeric
gaps. Each finding was captured by a failing regression before repair. A second
security review found the intermediate curl stream queue and URL cancellation
gaps; receipt-callback and blocked-worker regressions failed first and then
passed after the final repair.

Final evidence is 45 focused source-rights and truth-asset tests, 185 native
PostgreSQL 16 tests, and 4,689 complete repository tests. The post-commit
focused gate passed 45 tests. Compile, dependency, diff, changed-file secret,
package-resource, isolated-wheel, production fail-closed, customer-surface, and
listener checks passed. Catalog fingerprint
`0a0dcb2208e81bea14780d2c386b077f8c35f139a3d1c6d83a69ee2f40ac98ef`,
migration digest
`3fbe32d39e7fde4347b9205eb831781158554a1f94b028841dcfda375ebd5ebd`,
and fixed-epoch wheel digest
`57d506b4963072926e08ee9366fd44efc57116ca5f9c04da7c66436a5fe23884`
were recorded. The isolated wheel contains the capability matrix, migration
`0006`, restore privileges, and the truth-asset repository. It preserves 274
capabilities, 253 grouped actions, 21 internal-only capabilities, and visible
counts Local 8, National 10, Full Operator 20, and JV Partner 14.

Two fresh read-only security and release-correctness reviewers independently
reproduced the candidate before and after review and approved it with no
finding. They verified receipt-time URL bounds, cancellation containment,
admission binding, RLS and ACL isolation, raw-content denial, transactions,
teardown, local parity, backup and restore, packaging, surfaces, and production
fail-closed behavior. PID 65710 remained untouched in
`/Users/maxmedawar/LoopnetMCP`, listening only on `127.0.0.1:8000`.

No interface file changed, so the complete anti-slop interface audit found no
applicable UI defect. No deployment, DNS, billing, paid resource, provider
mutation, customer-data, or production action occurred. Production hosted
startup remains intentionally blocked until the six remaining platform,
provider, search, deal, privacy, and job repositories are certified and wired
together. The exact next bounded slice is PostgreSQL platform-domain
persistence. Private staging, integrated security, readiness, and
founder-approved cutover remain red.

## PostgreSQL platform-context persistence completed 2026-08-04

Phase 5D is certified and committed on `integration/cloud-platform-launch` as
`7a03724e7ec39dd6d08bfe2d7ebc739bcbb898b6` (`feat(postgres): add platform
context persistence`). The exact repaired candidate was
`8e4c480c90b956f96d767b80c62e844a0c78b86ab394a99b15e47af6a2dba4bc`
across 1,048 tracked plus untracked non-ignored files.

The new read-only PostgreSQL port returns one current actor and workspace
context snapshot: actor, workspace, active membership, workspace account,
optional plan, and deterministically ordered territories. It accepts only its
exact fresh admission and active platform port, with matching workspace, actor,
and OAuth session. Every database access uses the admitted transaction and
transaction-local RLS. Hosted execution cannot construct or recover the local
SQLite repository, while trusted local stdio retains existing behavior.

The implementation began RED because
`cre_mcp.postgres.platform_context` did not exist. The first frozen candidate
`2306bbbf...` passed its test gates but both independent reviewers reproduced a
release-blocking integrity race: separate READ COMMITTED identity and territory
queries could return a mixed-time combination that never existed. A permanent
concurrent-commit regression failed with the old workspace name plus the new
territory set. The repair performs the complete read in one ordered SQL
statement, validates identical repeated identity projections, and rejects
malformed or non-ASCII state codes through the fixed unavailable error.

Final evidence is 15 focused Phase 5D tests, 200 native PostgreSQL 16 tests, and
4,704 complete repository tests. The post-commit focused gate passed 15 tests.
Compile, dependency, diff, changed-file secret, deterministic wheel, unpacked
wheel, production fail-closed, customer-surface, and listener checks passed.
The existing catalog fingerprint remains
`0a0dcb2208e81bea14780d2c386b077f8c35f139a3d1c6d83a69ee2f40ac98ef`.
The two fixed-epoch wheels were byte-identical at
`8b0aca23214a5f3ff4df57ae8fbb38490fc7b335f64a56d94e347dcd131a398f`.
The unpacked wheel contains the capability matrix, platform-context repository,
migration `0006`, restore privileges, and source-rights registry. It preserves
274 capabilities, 253 grouped actions, 21 internal-only capabilities, and
customer surfaces Local 8, National 10, Full Operator 20, and JV Partner 14.

Both first reviewers rejected only the mixed-time snapshot. After the repair,
two new read-only security and release-correctness reviewers independently
reproduced the exact final candidate before and after review and approved it
with no finding. They verified admission and lease binding, RLS and ACL
isolation, one-statement snapshot coherence, malformed-row fail-closure,
cancellation, no local fallback, source-rights non-regression, packaging, and
production fail-closed behavior.

Codex Security still did not inherit the requested `PYTHON` variable after the
restart, so the controller did not repeat that failed loop. Every Python gate
used `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`, and the authorized fresh
read-only reviewer fallback supplied the independent reviews. PID 65710 remained
untouched in `/Users/maxmedawar/LoopnetMCP`, listening only on
`127.0.0.1:8000`.

No interface file changed, so the complete anti-slop interface audit found no
applicable UI defect. No deployment, DNS, billing, paid resource, provider
mutation, customer-data, or production action occurred. Hosted production
remains intentionally fail closed. Five domain ports remain: provider, search,
deal, privacy, and job. The exact next bounded slice is PostgreSQL provider-domain
persistence. Private staging, integrated security, the readiness packet, and
founder-approved public cutover remain red.

## PostgreSQL provider-entitlement persistence completed 2026-08-04

Phase 5E is certified and committed on `integration/cloud-platform-launch` as
`cef768f26712212113f329019b6886ea49aec990` (`feat(postgres): add provider
entitlement persistence`). The exact repaired candidate was
`d8ebf294c7ef55e8321fded24df18850c5f4ee2fe1d5cbbee3c28d88100712dc`
across 1,051 tracked plus untracked non-ignored files.

The new request-scoped, read-only PostgreSQL port returns a safe provider
entitlement projection for the admitted actor and workspace: subscription state
and actor- or workspace-visible access grants in deterministic order. It does
not return external subscription, customer, grant, or account identifiers,
provider payloads, provider events, or provider attempts. Webhook ingress,
reconciliation, billing mutation, and provider-side writes remain separate and
out of scope.

The repository requires the exact admission object, exact active aggregate
`provider` lease, active untrusted request context, and matching workspace,
actor, and OAuth session. One SQL statement reads through the admitted
transaction and transaction-local RLS using `current_workspace_id()` and
`current_actor_user_id()`. Existing column grants and RLS policies enforce the
projection, so no migration was needed. Hosted failures use the fixed message
`provider persistence unavailable`; trusted local behavior remains unchanged.

The implementation began RED because
`cre_mcp.postgres.provider_entitlements` did not exist. The first frozen
candidate `c1344c3c...` passed its controller gates, but the first security
review rejected two medium release-correctness defects: an in-flight provider
worker result could return after aggregate lease revocation, and hosted
repository binding ran before `use_context(ctx)`, allowing a binder to construct
the local SQLite `EntitlementStore`.

Permanent regressions first reproduced six failures across provider,
platform-context, and truth-asset result-after-revocation paths plus hosted
provider-store construction. The repair rechecks exact active scope after
worker completion, including the adjacent platform and truth repositories;
truth writes also recheck inside the transaction before commit. Hosted binding
now runs under the exact request context, and `EntitlementStore` construction is
denied under an active hosted repository lease or any untrusted context. An
over-broad attempt to deny the legacy deal store during binding broke explicit
test-owned compatibility adapters and was fully reverted before freeze.

Final evidence is 299 focused and adjacent tests, 219 native PostgreSQL 16
tests, and 4,724 complete repository tests. The provider repository file passed
15 tests, and the post-commit lifecycle selector passed 20 tests. Compile,
dependency, diff, changed-file secret, dash, deterministic-wheel, unpacked-wheel,
production fail-closed, surface, migration, and listener checks passed. The
catalog fingerprint remains
`0a0dcb2208e81bea14780d2c386b077f8c35f139a3d1c6d83a69ee2f40ac98ef`.
The controller's fixed-epoch wheels were byte-identical at
`fa2288f55494be7d06062a4d87d0659293f02f3860def8d774c7b68ca579be8c`.
The unpacked wheel imports the provider repository, retains required access,
source-rights, and SQL assets, and preserves 274 capabilities, 253 grouped
actions, 21 internal-only capabilities, and customer surfaces Local 8,
National 10, Full Operator 20, and JV Partner 14.

Two fresh read-only security and release-correctness reviewers independently
reproduced the exact final candidate before and after review and approved it
with no finding. They verified the two prior repairs, admission and lifecycle
binding, RLS and ACL isolation, fixed errors, cancellation containment,
data minimization, no local fallback, source-rights non-regression, packaging,
test-only compatibility, and production fail-closed behavior.

Codex Security still did not inherit the requested `PYTHON` variable after the
restart, so the controller did not repeat that failed loop. Every Python gate
used `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`, and the authorized fresh
read-only reviewer fallback supplied equivalent independent coverage. PID 65710
remained untouched in `/Users/maxmedawar/LoopnetMCP`, listening only on
`127.0.0.1:8000`.

No interface file changed, so the complete anti-slop interface audit found no
applicable UI defect. No deployment, DNS, billing, paid resource, provider
mutation, customer-data, or production action occurred. Hosted production
remains intentionally fail closed. Four domain ports remain: search, deal,
privacy, and job. The exact next bounded slice is PostgreSQL search-domain
persistence. Private staging, integrated security, the readiness packet, and
founder-approved public cutover remain red.

## PostgreSQL search persistence completed 2026-08-05

Phase 5F is certified and committed on `integration/cloud-platform-launch` as
`b0947d724f734cebadc16ebacb27917de90acca6` (`feat(postgres): add search
persistence`). The exact repaired candidate was
`fde8de7f8019443a32a0253e4ec831f8df45fb17d459b4236f91f05eae0d3a8d`
across 1,055 tracked plus untracked non-ignored files.

The new request-scoped PostgreSQL port persists actor-private saved searches
and their seen-result ledger for the admitted workspace. It preserves opaque
UUID hosted identifiers and trusted-local integer compatibility, requires
exact workspace public-ID and actor projection matches, and keeps searches
private to the actor even inside JV workspaces. PostgreSQL application roles
receive only `SELECT` and `INSERT` on these relations. `claim_unseen` performs
one atomic claim so concurrent alert checks cannot release the same deal twice.

The implementation began RED because `cre_mcp.postgres.searches` did not
exist. The first frozen candidate was rejected by independent review for three
valid blockers: detached or revoked hosted scope could fall back to local
SQLite, projected workspace identity was parsed but not matched to admission,
and `check_alerts()` could claim an earlier search before a later stale
territory error discarded all output, permanently suppressing the deal.

Permanent regressions reproduced each defect before repair. Hosted search
construction now rejects every untrusted fallback and requires an active
search lease; repository operations bind and recheck the exact admitted actor,
workspace, OAuth session, and public workspace projection; and alert checking
completes territory preflight for every selected search before provider or
claim side effects. Runtime failure of one already-preflighted search remains
isolated from the others.

Final evidence is 27 search-repository tests, 246 native PostgreSQL 16 tests,
and 4,752 complete repository tests, with one categorized third-party Authlib
deprecation warning. The surface selection passed 15 tests and preserved
customer-visible tool counts Local 8, National 10, Full Operator 20, and JV
Partner 14. Compile, dependency, diff, changed-content credential, wheel,
migration, catalog, production fail-closed, and listener checks passed. The
catalog fingerprint is
`15215ce6ae3eabe2c8799eeef258a7d1cf896aa9e5a6d66d94f5cb4e163b6323`;
migration `0007_search_persistence.sql` is
`47eb926512f49e355e91f7f098a17b4f3b4831d35c4fda97b4a6f1b742eccffe`;
and the inspected wheel is
`3cde98ae2b79b3eac8e6f000d1a0b0d2a2b936b051b43be7799f62d9c6765919`.

Two fresh read-only security and release-correctness reviewers independently
reproduced the exact repaired candidate before and after review and approved it
unchanged with no release blocker. They covered repository authorization,
isolation, lifecycle, database and ACL behavior, source-rights interactions,
alert side-effect ordering, packaging, compatibility, and deployment
correctness.

Codex Security still did not inherit the requested `PYTHON` variable after the
restart, so the controller did not repeat the failed loop. Every Python gate
used `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`, and the authorized fresh
read-only reviewer fallback supplied equivalent independent coverage. PID
65710 remained untouched in `/Users/maxmedawar/LoopnetMCP`, listening only on
`127.0.0.1:8000`.

No interface file changed, so the complete anti-slop interface audit found no
applicable UI defect. No deployment, DNS, billing, paid resource, provider
mutation, customer-data, or production action occurred. Hosted production
remains intentionally fail closed. Three domain ports remain: deal, privacy,
and job. The exact next bounded slice is Phase 5G PostgreSQL deal persistence.
Private staging, integrated security, the readiness packet, and
founder-approved public cutover remain red.

## PostgreSQL deal persistence completed 2026-08-05

Phase 5G is certified and committed on `integration/cloud-platform-launch` as
`49adb9e` (`feat(postgres): add deal persistence`). The exact repaired
candidate was
`1baea746e8a62fc6aef27a974c3ac9278fcd2522a8fa4825bd2902198b2b70f8`
across 1,059 tracked plus untracked non-ignored files.

The new request-scoped PostgreSQL port persists the complete non-search
`DealStore` surface for the admitted workspace. Deals are collaborative
workspace state rather than actor-owned rows, so migration `0008` converts
`owner_user_id` into `created_by_user_id`/`updated_by_user_id` attribution and
narrows the application role to exact column-level ACLs across eleven
relations. Hosted investor, commitment, exchange, deal-event and IC identifiers
are opaque UUID strings while trusted-local integers are preserved. Diligence
and operating workflows use capability-level composite methods that refresh the
sanitized deal and replace the complete child plan in one admitted transaction,
and replacement identification serializes on the exchange row while enforcing
the day-45 and 3-property/200% rules before mutation.

This phase took four review rounds and rejected three candidates. Nine valid
defects were found and repaired, each reproduced as a failing regression first.
Three of them were defects in earlier repairs, which is the reason the round
count is recorded rather than smoothed over:

- the restore preflight reported an unsupported PostgreSQL target as a
  smoke-identity failure, masking the version error;
- `build_noi_bridge` and `deal_truth_report` broke trusted-local behaviour for
  a deal_id with ingested claims that was never saved, and for a saved listing
  with the blank address the Crexi mapper emits by design;
- `list_deal_documents` let a `jv_partner` confirm the existence of, and read
  the document origin for, a deal outside its territory;
- `trace_input_lineage` leaked the same way and is now withheld from
  `jv_partner`; it was found by writing the first leak's regression as a
  structural invariant rather than a single-case assertion;
- rows predating `0008` stayed visible but became permanently unstageable and
  unassignable, and one undecodable listing denied `list_deals` for an entire
  workspace;
- `title` and `asking_price` reached SQL CHECK constraints unvalidated, and a
  provider price at or above 1e17 overflowed `numeric(19, 2)` and permanently
  poisoned every hosted write for that listing;
- five `_METHOD_TOOLS` entries granted a method to a capability no production
  call graph invokes;
- multi-statement reads took a fresh snapshot per statement, contradicting the
  written transaction contract;
- `list_deal_documents` held `get_deal` authority with no matching projection
  branch, so the capability was denied on every `jv_partner` call including
  in-territory deals in its own workspace.

The last defect is the clearest lesson of the phase: it was introduced by the
repair for the first territory leak, it passed a full green suite, and it was
invisible to the new tests because they patched a local `DealStore` that always
returns a listing. Three separate rounds produced a defect that a fully green
suite concealed, so suite-green was not treated as evidence of correctness. The
final correctness reviewer mutation-tested all nine new pins plus four of its
own choosing and confirmed every one fails when the behaviour it claims to pin
is deleted.

Final evidence is 274 native PostgreSQL 16 tests and 4,785 complete repository
tests, with one categorized third-party Authlib deprecation warning. Compile,
dependency, diff, changed-content credential, wheel, migration, catalog,
production fail-closed, and listener checks passed.
`build_postgres_hosted_persistence` still raises `HostedPersistenceUnavailable`,
so hosted production remains intentionally fail closed. The catalog fingerprint
is `eae1d0da2d249c97b3007539d7935ec58e06bef45c00afa4b93f4f597f9c857d`;
migration `0008_deal_persistence.sql` is
`8a7440a3025af9f4cc3e68015476b0fc7135e7677b420afcb982adb9445f76a8`;
`0007_search_persistence.sql` is unchanged at
`47eb926512f49e355e91f7f098a17b4f3b4831d35c4fda97b4a6f1b742eccffe`;
and the inspected wheel is
`cb55bc67ffe2076290225b355abe925fadc2ab528677e9ac1d07669da2b76afb`.

One locked surface count changed under review. JV Partner drops from 14 visible
grouped tools and 170 capabilities to 12 and 165, withholding
`unassigned_deals`, `exchange_status`, `list_investors`, `ic_scorecard`, and
`trace_input_lineage`. Those five are locationless or unmodelled aggregate
surfaces: they return deal, investor, exchange, or claim identities with no
property location a territory policy can inspect, so a territory-limited JV
grant would learn of deals outside its territory. `list_deal_documents` was
bound rather than withheld, matching its two `deal_id` siblings. Every
remaining JV-visible deal capability carries a declared property reference and
a result territory contract, and a locked invariant now asserts that every
territory-limited capability taking a `deal_id` and reaching a certified hosted
port declares one. Local 8, National 10, and Full Operator 20 are unchanged,
all 274 internal capabilities are retained, and 253 exact actions remain
grouped.

Two fresh read-only reviewers independently reproduced the exact candidate
before and after review and approved it unchanged with no release blocker. They
covered projection-versus-authority pairing, territory enumeration by
independent call-graph analysis, method authority in both directions, the
numeric bounding and its effect on the 1031 rules, source-rights re-derivation,
transaction isolation, RLS and column ACLs, migration backfill safety,
atomicity, statutory boundaries, trusted-local parity, packaging, and recovery.

One finding is deliberately carried rather than repaired. Both reviewers
independently reproduced an unpoliced per-deal existence and content oracle
reachable by `jv_partner` through `counterparty_track_record`, `who_to_call`,
and `counterparty_dossier`, which read a workspace-scoped SQLite `LedgerStore`
that is not fail closed in hosted execution. It is present at the base commit
`b0947d7`, never touches the deal port this phase certifies, and falls under
the phase's explicit non-scope for separate local stores. It is recorded above
as an open red hosted-launch blocker. It also makes one sentence of the Phase 5G
contract inaccurate: separate file-backed modules do not all remain fail closed
in hosted execution, and that text must be corrected in the next slice.

Related, and recorded so it is not mistaken for coverage: this phase's
tightening of `DealStore.__init__` closes `counterparty_dossier`,
`meeting_briefing`, `overnight_changes`, `who_to_call`, `data_room_index`,
`transaction_critical_path`, and `closing_runway` for untrusted contexts. They
remain entitled and counted in the 165 but are denied on every hosted call, and
the round-seven store-workflow tests now bind a local `DealStore` as the hosted
deal port, so they can no longer be cited as evidence those capabilities work
in hosted execution.

No interface file changed, so the complete anti-slop interface audit found no
applicable UI defect. No deployment, DNS, billing, paid resource, provider
mutation, customer-data, or production action occurred. Nothing was pushed. Two
domain ports remain: privacy and job. The exact next bounded slice is Phase 5H
PostgreSQL privacy-domain persistence. Private staging, integrated security,
the readiness packet, and founder-approved public cutover remain red.

## One-snapshot PostgreSQL OAuth authority checkpoint 2026-08-04

Commit `830c91463ea5335f687b088f7bbb9f577e9aec03` adds migration
`0002_hosted_lifecycle_and_oauth_authority.sql`, a dedicated OAuth connection
pool, and one fixed statement that derives token, client, user, workspace,
membership, account, grant, plan, quota, territory, staff, and identity-wide JV
authority from one PostgreSQL snapshot. Raw bearer tokens are hashed before the
database call. The OAuth role has only schema usage and exact function execute
authority. Pool setup, checkout, reset, backup, restore, and catalog checks
reject authority drift.

The 1,024-file reviewed candidate was
`2bf5a43d0367cc087a85ae99f754e6c7dfd4d20a432dc9035f70b04a24b2fac5`.
Migration `0002` is
`3058382c0943220e19bfa6b7754cda09fe823e478dc86397f8283047cc309b8f`;
the PostgreSQL 16 catalog fingerprint is
`40f025fcf85251cf340428438c5e5ebf3b20462ea8ee59c5ac882f9a94e47eef`.
The final wheel is
`324f777c57694962146c18adfe919a1f8354d4dda8eaafe0b2af549447c3974d`.

Evidence:

- PostgreSQL 16.14: 102 passed. Complete repository: 4,568 passed in 170.04
  seconds. The only warning is the known third-party FastMCP/Authlib
  deprecation.
- Compile, dependency, server import, packaged migration, secret review, and
  diff checks passed.
- Local Docker build `medawarcre-oauth-review:local` succeeded as image
  `sha256:84872a140166765718c53ba32251996b54b609605d3ee28658f82ddd36b04e00`.
  It runs as `cremcp`; server, OpenPyXL 3.1.5, and PDFPlumber 0.11.10 imports
  passed inside the image.
- Two fresh read-only reviewers independently reproduced the candidate hash,
  migration, catalog, and wheel evidence and returned hash-stable approval.
- `printenv PYTHON` was still empty after the Codex restart. The controller did
  not repeat the failed Security-helper loop and used the required fresh
  read-only reviewer fallback.
- No interface file changed. The complete anti-slop recheck found no applicable
  UI defect.
- No deployment, DNS, billing, paid resource, provider mutation, customer-data
  access, or production action occurred.

This is not hosted-functionality approval. The exact unfinished checkpoint is
request-scoped domain repositories plus atomic approval, quota, and durable
decision audit. Jobs, privacy, provider service paths, container rollout,
migration operations, recovery, private staging, the final integrated audit,
readiness packet, and founder-approved cutover remain red.

## Hosted withholding correction checkpoint 2026-08-05 to 2026-08-06

Fifteen capabilities were entitled, counted, and advertised by the hosted
grouped tools while every hosted call failed. They are now withheld from the
hosted surface and denied on a direct call. The contract is
`docs/launch/HOSTED_WITHHOLDING_CONTRACT.md`.

**Two successive inventories were incomplete.** The recorded seven were
`counterparty_dossier`, `meeting_briefing`, `who_to_call`, `overnight_changes`,
`data_room_index`, `transaction_critical_path`, and `closing_runway`. Review
round one rejected that candidate: seven more are dead for the same reason and
were still advertised — `init_data_room`, `update_data_room_item`,
`init_transaction_plan`, `morning_queue`, `flag_unattended`,
`record_listing_snapshot`, and `stale_listing_signals`. Review round two
rejected the resulting fourteen: the derivation behind it did not resolve
package `__init__.py` re-exports and so missed a fifteenth,
`closing_day_runbook`, which reaches the same `DependencyStore` through
`closing.command_center` and the `cre_mcp.dataroom` re-export.

How the set was established and what the suite guards are two different things,
and earlier drafts conflated them. **Established:** independent reviewers in
successive rounds bound a real `HostedRequestRepositories` — under which a
direct `DealStore(...)` raises while `get_deal_store()` returns the port — and
executed every grouped action. Each such repositories-bound run reproduced
exactly these fifteen, with no sixteenth and none of the fifteen alive; one also
re-seeded on `TruthStore`, `PlatformRepository`, and `EntitlementStore` and
found no additional dead grouped action. Which rounds those were is not restated
here: the review-history table below is the record, and earlier drafts of this
paragraph twice attributed the work to the wrong rounds. **Guarded:** a static AST derivation asserts
set equality with `HOSTED_WITHHELD_CAPABILITIES`, turning red in either
direction on any source change that moves it. It is a tripwire, not a proof.
The earlier claim that the set had been "derived two independent ways"
overstated the evidence and was withdrawn; the claim that the static pin
establishes completeness is likewise withdrawn.

The criterion is routing, not a store class. `DealStore.__init__` refuses every
hosted or untrusted context, so a capability is alive on hosted when it goes
through `get_deal_store`/`get_search_store` (which return the certified hosted
port) and dead when it constructs the store directly. An earlier draft
attributed `transaction_critical_path` and `closing_runway` to `DataRoomStore`;
they use `DependencyStore`, and because the reversal condition had been keyed to
the store name, that error could have re-advertised two still-dead actions. The
reversal condition is now keyed to the capability routing through a certified
port.

The original attempt was reverted because it withheld by emptying
`allowed_profiles`, which breaks the matrix well-formedness invariant and the
trusted local capability. This correction withholds at the hosted surface
instead, so entitlement, grouped classification, the locked counts, and trusted
local stdio are all untouched, and no per-capability internal-only mechanism was
needed.

Evidence:

- Worktree `/Users/maxmedawar/LoopnetMCP-cloud-integration`, branch
  `integration/cloud-platform-launch`, base `cd0f335`.
- Initial red: `ImportError: cannot import name 'HOSTED_WITHHELD_CAPABILITIES'
  from 'cre_mcp.surface.catalog'` before implementation.
- Files changed, ten in total: `src/cre_mcp/surface/catalog.py` and
  `src/cre_mcp/surface/server.py`; the JV count in
  `tests/surface/test_catalog.py` and `tests/surface/test_server.py`; new
  `tests/surface/test_hosted_withholding.py` and new
  `docs/launch/HOSTED_WITHHOLDING_CONTRACT.md`; and dated corrections to this
  ledger, `docs/launch/PHASE_5G_DEAL_PERSISTENCE_CONTRACT.md`,
  `.claude/specs/consolidated-customer-mcp-surface.md`, and
  `.claude/specs/oauth-launch-certification-phase-1.md`.
- Focused gate: 98 surface tests passed with 4 skips, the skips being the
  withheld capabilities not entitled to `jv_partner`. Local behaviour is
  unchanged: 169 passed from `pytest tests/relations tests/command tests/dataroom
  tests/closing tests/leaseops
  tests/access/test_territory_round7_store_workflows.py` — 83 from the five
  directories and 86 from that one territory file.
- Complete repository gate: 4,868 passed and 4 skipped, up from the 4,785
  baseline by exactly the new pins, with one categorized third-party Authlib
  deprecation and no regression. Wall time varies by run and machine load
  (187-236 seconds observed) and is not an evidential figure. The four skips
  are the withheld capabilities not entitled to `jv_partner`.
- Mutation evidence: emptying `HOSTED_WITHHELD_CAPABILITIES` entirely fails 62
  of the 83 pins in the withholding suite, including every parametrization of
  the end-to-end denial pin. Targeted mutations each fail their own pin —
  advertising withheld actions, resolving withheld actions, dropping each of
  the three import-time guards, and ignoring withholding in `visible_names`.
  The set-equality drift pin fails in BOTH directions: removing
  `closing_day_runbook` from the withheld map fails it, and adding the live,
  accessor-routed `unassigned_deals` to the map also fails it. That two-way failure is what guards against withholding a
  working capability; the runtime probe cannot, and is no longer claimed to.
- Surface gates: 274 internal capabilities, 253 grouped actions, 21
  internal-only, 15 hosted-withheld, 238 hosted-reachable, customer grouped-tool
  counts Local 8, National 10, Full Operator 20, and JV Partner 11, JV entitled
  capabilities 164, catalog fingerprint `84578ae71567ed18...` unchanged, and no
  withheld action reachable through any hosted path.
- **The JV grouped-tool count moves from 12 to 11 by founder decision on
  2026-08-06.** All four of `cre_close`'s JV-entitled actions are dead, so
  `cre_close` has never worked for `jv_partner` and the locked 12 was already
  overstating the working JV surface. Offered the choice between publishing 11
  working tools and holding 12 by continuing to advertise a capability that
  fails on every call, the founder chose 11. Local, National, and Full Operator
  counts are unchanged. The release-locked assertions in
  `tests/surface/test_catalog.py`, `tests/surface/test_server.py`, and the
  withholding suite were updated to 11 to match this decision.
- Static and packaging gates: source and tests compile, `git diff --check` is
  clean, the changed-content credential scan is clean, no port-8000 listener,
  and an isolated wheel builds and packages the capability matrix,
  the source-rights registry, the surface catalog, and all eight numbered
  migrations plus `restore_privileges.sql`. No wheel digest is recorded: the
  build is not byte-reproducible — the digest moved across three review rounds
  with no packaged source byte changed — so a digest here would assert a
  content property it does not have.
- Connection UI recheck: 5 Vitest cases passed, unchanged by this correction.
- Three fail-closed guards were added so a careless future edit fails at import:
  withholding a non-grouped capability is rejected, withholding a legacy tool id
  is rejected because the legacy reconciliation would still report it reachable,
  and withholding that would empty a grouped tool is rejected. A set-equality
  DRIFT pin against the statically derived set replaced a weaker per-module
  guard that review showed was evaded by aliased imports, attribute calls, and
  any module named `store.py`. That pin does NOT establish completeness — see
  the framing above; it turns red in either direction when a source change
  moves the derived set, which is a prompt to look, not a proof.
- No deployment, DNS, billing, provider mutation, or customer-data action
  occurred.

Review history. Every round in the table below was rejected on correctness, and
each found a real defect the previous round missed. No round after round two
found a defect in shipped `src/` behaviour: from round three onward the findings
were in this ledger, in the contract, or in the claims made for the tests —
though rounds four and five also drove repairs to the test-side derivation
itself. Counts are deliberately not restated in this sentence; the table is the
record, and restating them is what failed review in rounds seven and eight:

| Round | Correctness | Security | Rejected for |
| --- | --- | --- | --- |
| 1 | REJECTED | APPROVED | Wrong store named for two capabilities while the reversal condition keyed on that name; the seven-capability set was incomplete; the end-to-end denial pin was vacuous because the fixture internal server was empty |
| 2 | REJECTED | APPROVED | A fifteenth capability, `closing_day_runbook`, missed because the derivation did not resolve package `__init__` re-exports; the ledger asserted a completeness the evidence did not support; the "genuinely dead" pin could not distinguish dead from alive |
| 3 | REJECTED | APPROVED | The normative scope line of this contract and the pin file's module docstring still said "fourteen" while fifteen were withheld |
| 4 | REJECTED | APPROVED | The authoritative surface spec still release-locked JV Partner at 14; the internal-only rationale ("the affected modules also hold working capabilities") is false for `cre_mcp.command.tools` and `cre_mcp.dataroom.tools`, where every capability is withheld; the blind-spot disclosure was incomplete and mis-located, missing attribute-qualified calls at every propagation step |
| 5 | REJECTED | REJECTED (process) | The completeness pin's own docstring said a class is dead only via `__init__`, the opposite of the round-5 code, and the contract and ledger repeated it; the residual-limitation disclosure was again incomplete, missing subclassing, module-level name binding, module-scope construction, and the over-marking direction entirely |
| 6 | REJECTED | APPROVED | The evidence list reinstated the completeness claim the same section had withdrawn 72 lines earlier; the OAuth-certification JV amendment could not close arithmetically (170 − 1 ≠ 164) and erased five Phase 5G withholdings |
| 7 | REJECTED | APPROVED | The review-history summary line said "three rejected rounds … two of the three in the verification" while the table beneath it recorded six rejections, four of them verification or ledger defects |
| 8 | REJECTED | REJECTED | The summary sentence restated a count that drifted from the table again, one round after being fixed for exactly that; and the round-attribution self-correction contradicted the contract and this file, leaving three passages disagreeing on the runtime evidence |
| 9 | pending | pending | — |

Round five's security reviewer rejected on process, not on the code: the working
tree was edited while that review was in flight, so its start and end hashes
differed and no verdict could attach to a candidate. That was an operator error
— the correctness blockers were repaired without first waiting for the security
review to return. Its findings against the bytes it did read were folded in
anyway: it confirmed `src/` was comment-only versus the prior approved state,
that the reworded internal-only rationale is arithmetically right, that the
derivation terminates in three passes with bounded recursion and no side
effects, and that 16,275 hostile input shapes produced zero resolutions of a
withheld capability. It also demonstrated three further static evasions and a
silent alias-depth truncation, both now addressed: the truncation raises instead
of returning a partial resolution.

Round six was rejected for a claim that had been withdrawn elsewhere in the
same document and for an amendment whose arithmetic did not close. The JV
entitlement history was then verified directly from the capability matrix at
each commit: `88e3082` 170, `49adb9e` 165 (five withheld — `exchange_status`,
`ic_scorecard`, `list_investors`, `trace_input_lineage`, `unassigned_deals`),
`039cacf` 164 (one withheld — `counterparty_track_record`).

Round five stopped patching the disclosure and changed what is claimed: the
static derivation is now described as a drift tripwire that is unsound in both
directions, with completeness attributed to the runtime evidence instead. Three
rounds of incomplete blind-spot enumerations preceded that reframing.

Round four also drove a code repair rather than a disclosure: the completeness
derivation now resolves attribute calls qualified by a module alias and walks
every method of a class, closing three evasions demonstrated by mutation — an
attribute construction making a live capability dead, a module-alias call to a
dead function, and a store constructed lazily outside `__init__`. The derived
set is unchanged at fifteen.

Round-three security additionally verified the change is purely restrictive by
rebuilding the catalog at zero, fourteen, and fifteen withheld and diffing every
observable surface: no profile gains a tool, an action, or a resolvable pair,
and roughly 26,800 hostile input shapes produced zero resolutions of a withheld
capability. Reviewers in that round also reproduced the set of fifteen by
methods stronger than the shipped derivation and confirmed no sixteenth and no
wrongly-withheld live capability; the repositories-bound method is described
once above rather than re-attributed per round.

Known limitations, disclosed rather than implied away and recorded as
known-so-far rather than exhaustive. The static drift detector resolves import
aliases, package `__init__` re-exports, attribute calls qualified by a module
alias, and every method of a class — so a class is marked dead when any method
reaches a dead callee, not only `__init__`. It can MISS a `DealStore` subclass,
the class bound to a module-level name and called through it, a construction at
module scope, a call whose qualifier is not a known module alias when the
attribute name is not bound in that module, and any callee that is itself a
`Call` or `Subscript` node (`getattr(...)()`, dict dispatch). A fully-dotted
`cre_mcp.deals.store.DealStore()` after a plain dotted import is missed too,
but by the module-scope fallback rather than that family: its callee is an
`Attribute` whose value is itself an `Attribute`. It can OVER-MARK through the same
fallback, which matches by attribute name, and through whole-class walking.
None is exercised by shipping code: nine construction sites, all bare-name,
seven in module-level functions and two in `__init__`, and no subclass.
Promoting the repositories-bound runtime derivation to a second pin removes all
of these and is the recommended follow-up. Note for anyone repeating a
reference-taint (bytecode) derivation: it over-reports `add_to_pipeline`,
`due_diligence_plan`, and `operating_playbook`. All three are alive — they route
store access through `get_deal_store()` and touch `DealStore` only via the
staticmethods `_validate_stage`/`deal_id_for` and a type annotation, none of
which is a construction.

This corrects a surface defect only. It certifies no store and re-routes no
capability. Removing an entry from `HOSTED_WITHHELD_CAPABILITIES` requires that
the capability actually route through a certified hosted port, under the same
review ceremony; certifying a store class is not by itself sufficient.

## Phase 5I Clerk identity verification 2026-08-06

Contract: `docs/launch/PHASE_5I_CLERK_IDENTITY_VERIFICATION_CONTRACT.md`.

Worktree `/Users/maxmedawar/LoopnetMCP-cloud-integration`, branch
`integration/cloud-platform-launch`, base `a828717`.

### What was wrong

`ClerkHumanIdentityVerifier.verify_bearer` returned the Clerk user's primary
email address without ever inspecting `EmailAddress.verification`.
`HumanIdentityStore.resolve_or_bind` then used exactly that string to pick which
preprovisioned MedawarCRE user a Clerk subject becomes on first sign-in.

In the installed `clerk-backend-api`, `verification` is `Nullable[Verification]`
and its `status` can be `unverified`, `failed`, or `expired`. An address a Clerk
account holder had added but not proven ownership of therefore carried full
binding authority. The result is a first-sign-in account takeover against any
MedawarCRE user who has not yet signed in — at launch, all of them. Once bound,
the mapping is stable by subject, so the takeover is durable rather than
transient, and every downstream check is correct while resolving the wrong user.

This is the exact class the founder decision forbids: authority taken from
user-editable identity-provider metadata.

Two adjacent omissions in the same twelve lines are closed with it:
`user.deprovisioned` was not refused although `banned` and `locked` were, and
the fetched record's `id` was never compared to the authenticated `sub`.

### Round one, and why it was not enough

The first frozen candidate `ccc3d015...` scoped the repair to the adapter
alone. Two fresh independent read-only reviews audited that exact hash and
reported the same value at start and finish; neither modified the tree.

Correctness **APPROVED**: it reproduced the red state, every number, the
mutation table line for line, confirmed the fixture change weakened no
assertion, and verified the nine imported ledger sections are byte-identical to
the control branch with all nine commits confirmed ancestors of HEAD.

Security **CHANGES REQUIRED**, and correctly so. The adapter was hardened while
the lookup that consumes its output was left alone, and that is where the
remaining defects were. Findings, all repaired in round two:

| # | Severity | Defect |
| --- | --- | --- |
| 1 | Medium | `EmailAddress.id` and `primary_email_address_id` are both optional; an unset pair matched on `None == None` and promoted a non-primary address |
| 2 | Medium | `str.casefold()` in Python against SQLite `lower()` in SQL — `straße@corp.test` bound to a stored `strasse@corp.test` row, and non-ASCII uppercase rows were permanently unreachable |
| 3 | Low | `hmac.compare_digest` raises on non-ASCII and sat outside the provider `try`, so a 500 instead of `None` |
| 4 | Low | A whitespace-only address raised out of the dataclass |
| 5 | Low | Two distinct binding-refusal messages, echoed to the browser, enumerated provisioned addresses |
| 6 | Low | No pin constructed a real `clerk_backend_api` model |

Finding 2 is the one worth remembering. It was a genuine cross-account bind
*and* a permanent lockout, in the same two lines, and both directions came from
assuming two functions named "lowercase" are the same function. Round one's
contract had listed `HumanIdentityStore` as non-scope; that boundary was wrong,
because the join key is the adapter and the lookup together.

### Round two, and the defect that survived it

Candidate `2e1881be...` was frozen and audited by two fresh reviewers, both
reporting the same hash at start and finish and neither touching the tree.

**Both rejected it, and both found the same defect independently.** The round-one
repair had hardened the reader while `AdminControlStore.provision_workspace`
— the internal Operations Console provisioning path — still stored
`owner_email.casefold()`. The two folds then disagreed by construction on
exactly the character class the contract named:

```
operator provisions 'Straße@corp.test'  ->  row stored as 'strasse@corp.test'
holder of 'strasse@corp.test'           ->  BINDS to that row
holder of 'Straße@corp.test' (rightful) ->  DENIED, permanently
```

So the cross-account bind was not closed, it was relocated from the read fold
to the write fold — and a regression was added, because at base `a828717` the
rightful owner did resolve. The contract's own claims that the change
"collapses nothing" and was "read-path only" were false at the system level.

Additional findings, all repaired: `user.id` was compared without the
`isinstance` guard applied to `email.id`; the predicate's docstring claimed
Clerk proof stronger than `verification_admin` actually establishes; no
Unicode normalization meant an NFD address from the provider could never reach
an NFC row; and two statements in this ledger were wrong — see below.

The lesson is the one the reviews stated: a normalization applied at one end of
a join key is not a normalization. The repair therefore defines one canonical
form for the column in `cre_mcp/platform/models.py` and applies it at all three
write sites and the read, matching by exact equality so no SQL engine's case
rules participate.

### Evidence

- Round-one red, new pins only: **12 failed, 4 passed**. The four passes are the
  two positive controls and the already-refused `banned` and `locked` siblings.
- Round-two red, repair pins only: **7 failed, 17 passed**. The real-SDK-model
  pin passed on arrival, confirming the predicate already handled genuine
  models rather than only fakes.
- Round-ten green: **97 passed** across the new module and the existing
  `test_human_identity.py`.
- Focused regression: `tests/platform tests/surface
  tests/access/test_profiles_matrix.py` — **636 passed, 4 skipped** (546 at
  base; 562, 572, 580, 584, 585, 595, 596, 608, and 621 at rounds one through
  nine).
- Complete repository gate: **4,958 passed, 4 skipped**, one categorized
  third-party Authlib deprecation. The re-verified base measured **4,868
  passed, 4 skipped** on the same interpreter, so the delta is exactly the 90
  pins this phase adds and nothing regressed — including no fallout from
  normalizing every write site.
- Connection UI recheck: **5 Vitest cases passed**, unchanged.

### Round three, and the fold that was wrong in the other direction

Candidate `f521306a...` was audited by two fresh reviewers, hash stable at both
ends, neither touching the tree. Correctness **APPROVED** with no code defect,
reproducing every number and the round-three mutation table exactly. Security
**REJECTED** it, and was right again.

The round-two repair had replaced `casefold()` with an ASCII-only fold,
reasoning that it could not collapse anything. It cannot — but it also folds
only `A`–`Z`, so every other capital survives:

```
operator types 'MÜLLER@corp.test'  ->  stored 'mÜller@corp.test'
Clerk reports  'müller@corp.test'  ->  key    'müller@corp.test'   REFUSED
base a828717                                                       BOUND
```

Same for `JOSÉ@`, `ИВАН@`, `ΑΝΝΑ@`. A false denial and a regression, from a
fold that was case-insensitive for some customers and not others. `str.lower()`
is the correct answer and was available the whole time: it does **not** collapse
`ß`, `ﬁ`, or `ſ` — only `casefold()` does — so it gives case-insensitivity
across the whole alphabet while keeping separate mailboxes separate. Verified
over every Unicode code point: idempotent, NFC-stable, no collision group
beyond ordinary case and canonical equivalence. It also makes the application
form agree with PostgreSQL's `lower(email)` index, which the ASCII fold did
not — two rows legal in SQLite that one PostgreSQL unique index could not hold.

The pin that should have caught this existed and passed, because it used the
same string on both sides of the write and the read and so could not observe a
case difference. The pins now differ deliberately between what the operator
types and what the provider reports. A pin for `update_user`, the one write
site left unpinned, was added in the same round.

### Round four

Candidate `793da460...` was audited by two fresh reviewers, hash stable at both
ends, neither touching the tree.

Security **APPROVED**. It could not construct any Clerk response shape yielding
an identity for an unproven address, swept all 1,114,112 code points plus
64,414 multi-character sequences against the canonical form for collisions and
idempotence, and loaded 1,109,579 canonical values into a real PostgreSQL 16
cluster across three collations to check the unique index agrees. All four
previously rejected defects confirmed closed rather than relocated.

Correctness **REJECTED**, on documentation only — no code defect, every number
and the round-four mutation table reproduced exactly. The blocking finding was
that this ledger still contained the sentence "every guard is now individually
falsifiable" six lines after the paragraph retracting it, and that a *second*
guard was in the same undisclosed position. That is the same standard the three
prior rounds were rejected on, applied to the document rather than the code.

Round five is that repair: the sentence is deleted, the second guard is pinned
instead of excused, three code comments that justified a design with a fact
this commit invalidated are corrected, and the contract's overstatement about
pre-existing rows is narrowed to match the ledger.

### Round five, and the sigma regression

Candidate `7c13c810...` was audited by two fresh reviewers, hash stable, tree
untouched. Both rejected it.

Security found a **HIGH**: `str.lower()` is not a per-code-point map. It
implements Unicode's `Final_Sigma` rule, so `Σ` lowercases to `ς` at a word
boundary and `σ` elsewhere:

```
operator types  'ΓΙΩΡΓΟΣ@CORP.TEST'  ->  stored 'γιωργος@corp.test'  (ς)
owner's Clerk address 'γιωργοσ@…' (σ) ->  REFUSED, permanently
holder of 'γιωργος@…' (ς)             ->  BOUND to the owner's row
```

Worse in kind than the ASCII-fold defect it replaced: that one produced an
unreachable row, this one keyed the row to a **different live mailbox**. And a
regression against base, where `casefold()` mapped both sigma forms to `σ` and
matched the owner correctly. The repair folds per code point and unifies `ς`
onto `σ`, which is what `casefold()` did and the only way `Σ` can fold at all.

The pin that should have caught it existed: the parameterized case table had a
Greek name in it — `ΑΝΝΑ`, the one Greek name containing no sigma. The table
now carries `ΓΙΩΡΓΟΣ` and `ΟΔΥΣΣΕΥΣ` in both spellings.

Correctness rejected the same candidate on documentation, and its finding is
the more useful one: the replacement sentence "one guard is not individually
falsifiable" was itself false — three further guards and two claimed properties
survived deletion with the whole suite green. That is the third consecutive
round rejected for a claim about coverage rather than for the coverage itself.

### Four false statements in this ledger, corrected

Recorded rather than quietly edited, because each was caught by review and not
by me:

- "The two branches share no source file" was false; they diverge across 149
  files under `src/` because the control branch sits at an older base. The
  import paragraph now states the narrow, true claim instead.
- The round-one mutation row read "Verification predicate always returns true",
  but a literal `return True` on the whole predicate kills 10 pins, not 9. The
  mutation actually run neutered the status comparison while leaving the
  null-`verification` guard in place. The row is relabelled to what was run.
- "Every guard is now individually falsifiable" was false: the `len(matches)
  != 1` arm is unreachable on SQLite and kills nothing. It is now recorded as
  an unfalsifiable-but-correct guard instead of counted as covered.
- That same sentence then survived in a second place in this section, after
  being recorded as retracted — and a second guard, the `.value` normalization
  in `_clerk_email_is_verified`, turned out to be unfalsifiable too, with the
  existing enum pin's docstring claiming the opposite. The sentence is deleted
  and that guard is now pinned with a non-`str` enum.

Every mutation table before round ten was measured against a candidate that
was superseded and never committed, so none of them is reproducible against the
committed tree. They are kept because they record what was found and when. An
earlier version of this note scoped the disclaimer to rounds one and two, which
implied the later ones were re-runnable; they are not, and an earlier version
also referred to "their tables" for rounds that have none.

### Mutation evidence

Each guard broken in place against a working-copy snapshot, with a green
control before and after every set. Tables appear newest first.

Round ten, control 97 passed:

| Mutation | Result |
| --- | --- |
| NFC applied before the fold rather than after | 15 failed |

Round nine, control 82 passed:

| Mutation | Result |
| --- | --- |
| `deprovisioned` `getattr` default dropped | 1 failed |
| `email.id ==` becomes `is` | 1 failed |
| `record_id !=` becomes `is not` | 1 failed |
| Canonical form uses NFD | 1 failed |
| Canonical form uses `.strip(" ")` | 4 failed |
| `getattr(email, "verification", …)` becomes attribute access | 1 failed |
| `getattr(user, "id", …)` becomes attribute access | 1 failed |
| `getattr(user, "primary_email_address_id", …)` becomes attribute access | 1 failed |
| `getattr(primary_email, "email_address", …)` becomes attribute access | 1 failed |

Round eight, control 69 passed:

| Mutation | Result |
| --- | --- |
| Canonical form uses NFKC | 3 failed |
| Canonical form drops `.strip()` | 1 failed |
| `create_user` reverts to `casefold()` | 6 failed |
| `update_user` reverts to `casefold()` | 2 failed |
| Primary-address scan truncated to the first entry | 1 failed |
| Final-sigma unification dropped | 3 failed |
| `isinstance(status, str)` dropped | 1 failed |
| `isinstance(primary_id, str)` dropped | 1 failed |
| `isinstance(primary, str)` dropped | 1 failed |
| Connection route forwards `str(exc)` again | 1 failed |
| Operations route forwards `str(exc)` again | 1 failed |
| `_identity_from_user` hoisted out of the `try` | 1 failed |
| `getattr(status, "value", status)` dropped | 1 failed |

The round-six version of this table carried a row labelled "whole-string
`lower()` restored", scored at 3 failed. That label was wrong: reverting only
the loop while keeping the unification kills nothing — the 3 failures came from
reverting the whole canonical form, which drops the unification too. The row is
gone along with the loop, and the unification carries the 3.

There is no round-five table. Round five added one pin and changed
documentation; it introduced no guard to mutate.

Rounds one through nine were measured against candidates that were superseded
and never committed, with controls of 23, 33, 41, 45, 46, 56, 57, 69 and 82
against the committed tree's 97. Rounds one to four, eight and nine have tables;
five, six and seven are narrated without one. Those tables record what was found
and when, and none of them is re-runnable against the committed tree — the round
nine table sits above this line and is no more reproducible than the ones below
it. Its "canonical form uses NFD" row, for instance, measures 16 rather than 1
against the committed tree, because round ten added pins that mutation also
kills.

Round one, control 23 passed:

| Mutation | Result |
| --- | --- |
| Status comparison always returns true (null-verification guard retained) | 9 failed |
| Status comparison becomes case-insensitive | 1 failed |
| Any verified address rescues the primary | 1 failed |
| `deprovisioned` no longer refused | 1 failed |
| Record-id/subject binding dropped | 1 failed |
| Null verification treated as verified | 1 failed |

Round two, control 33 passed:

| Mutation | Result |
| --- | --- |
| Fold reverts to `casefold()` | 2 failed |
| Ambiguous candidate set accepted | 1 failed |
| `primary_email_address_id` guard dropped | 1 failed |
| `email.id` string guard dropped | 1 failed |
| Subject check reverts to `compare_digest` | 1 failed |
| Blank-address guard weakened to falsiness | 1 failed |
| Distinct refusal messages restored | 2 failed |

Round three, control 41 passed:

| Mutation | Result |
| --- | --- |
| `provision_workspace` reverts to `casefold()` | 5 failed |
| `create_user` drops normalization | 1 failed |
| Canonical form drops NFC | 1 failed |
| Canonical form uses `casefold()` | 1 failed |
| `user.id` isinstance guard dropped | 1 failed |
| Lookup reverts to `lower(email)` | 1 failed |

The lookup mutation survived its first run: with every write canonical,
SQLite's ASCII-only `lower()` is indistinguishable from exact equality, so the
change is unobservable on this backend. Rather than report it as covered, a pin
was added for the property exact equality actually buys — a row written in some
other form is unreachable rather than matched approximately, which is what
keeps PostgreSQL's Unicode-aware `lower()` from changing the answer at cutover.

Round four, control 45 passed:

| Mutation | Result |
| --- | --- |
| Canonical form reverts to the ASCII-only fold | 5 failed |
| Canonical form uses `casefold()` | 1 failed |
| Canonical form drops NFC | 1 failed |
| `update_user` drops normalization | 1 failed |
| `provision_workspace` reverts to `casefold()` | 4 failed |
| `create_user` drops normalization | 2 failed |

These mutations survive with the whole suite green. They are listed, not
counted — six consecutive rounds were rejected for a false claim about
coverage, never for the coverage itself, and twice the false claim was the
sentence written to replace the previous false claim.

| Survivor | Why it cannot fail |
| --- | --- |
| `len(matches) != 1` → `if not matches` | `platform_users.email` is UNIQUE and every writer stores the canonical form, so an exact-equality select returns at most one row on SQLite |
| `primary = primary.strip()` removed | the canonical form strips, so only the returned dataclass field would carry padding |
| `if verification is None: return False` removed | `getattr(None, "status", None)` already fails the `isinstance` check below it |
| `primary_email is None or` removed | `_clerk_email_is_verified(None)` already returns `False` |
| `bool(...)` around `deprovisioned` removed | truthiness is what the `or` chain already evaluates; the `getattr` default in the same expression is the half that carries a claim, and it is pinned |

All are kept. The first is real defence for a backend without that constraint;
the rest are ordinary defensive clarity, and unlike the per-code-point loop
deleted in round seven, none carries a comment claiming a safety it does not
provide. That distinction is the standard: delete a guard that misdirects the
next reader, keep one that merely restates a guarantee, and say which it is.

An earlier version of this table listed five and was short by six. Those six
are now pinned rather than listed, because each had an observable consequence:
dropping the `getattr(user, "deprovisioned", False)` default denies every
record from an SDK predating the field; comparing either identifier with `is`
instead of `==` refuses every production sign-in while passing tests that reuse
one interned literal on both sides; `NFD` instead of `NFC` changes the stored
form; `.strip(" ")` leaves tab and newline padding; and plain attribute access
instead of `getattr` turns an absent SDK field into an error. Writing that last
pin found a real gap — `primary_email.email_address` had no `getattr` guard, so
an absent address raised instead of refusing, contradicting requirement 5. The
guard is now there.

The guards below were in that position across rounds five through nine and are
pinned rather than excused, each found by review rather than by the builder.
The list is deliberately not summarised by a count; count the rows.

| Guard | Pin that now kills it |
| --- | --- |
| `getattr(status, "value", status)` | a plain `enum.Enum` status, which fails `isinstance(x, str)` |
| `isinstance(status, str)` | a status object whose `__eq__` answers true |
| `isinstance(primary_id, str)` | a truthy `primary_email_address_id` that compares equal to anything |
| `isinstance(primary, str)` | a non-string address, through the direct call |
| the connection route's fixed error body | an HTTP POST to `/v1/browser/session` asserting the store's text is not forwarded |
| the operations route's fixed error body | the same assertion against `/v1/operations/session` |
| `_identity_from_user` inside the provider `try` | a record whose attribute access raises |
| NFC rather than NFKC | `ﬁnance`/`finance`, `ſam`/`sam`, `µicro`/`μicro` as separate people |
| `create_user` and `update_user` normalization | collapse-sensitive, NFD, and sigma-bearing addresses driven through each |
| the canonical form's `.strip()` | padded addresses using space, tab, newline, and CRLF |
| the primary-address scan | a primary sitting at index 1 |
| the `getattr(user, "deprovisioned", False)` default | a record with the attribute deleted |
| `==` rather than `is` on both identifiers | identifiers built at runtime, so the two sides are different objects |
| NFC rather than NFD | the stored bytes asserted composed |
| `getattr` on five optional SDK fields | each field deleted, through the direct call |
| NFC applied after the fold, not before | Greek capitals with a combining mark, where composing first leaves the result un-composed |

One further guard was not pinned but deleted. The per-code-point lowering loop was an
equivalent mutant: with the `ς → σ` unification applied it computes the same
value as whole-string `str.lower()` on every input, so it could not fail, and
its comment credited it with closing the sigma defect that the unification
actually closes. Two reviews measured zero differences independently.

The two error bodies were one row in an earlier version of this table, and that
row was false: only the connection route was pinned, and reverting the
operations route to `str(exc)` left the entire repository green. They are two
rows now because they are two code paths.

Round eight is the sharpest instance of the same pattern. The parameterized
write/read table carried eleven rows, and its docstring said every row differed
between the typed and the reported spelling — the repair round six had made.
Two rows, `ﬁnance` and `ſam`, still passed the identical string on both sides.
Those were two of the three addresses whose non-collapse nothing else pinned —
the third being the micro sign, which `casefold()` and NFKC both map to `μ` —
so switching the canonical form from NFC to NFKC passed all 4,918 tests and
would have restored the cross-account bind for ligature, long-s, and
micro-sign addresses. A docstring asserting a property of a table is not a
check that the table has it.

Round nine found the same shape one layer down: a comment on the last two rows
of that table claimed they discriminated the final-sigma unification, and they
do not — without it both sides fold to the same value and meet anyway. The
rows above them are what pins the unification. The comment now says so, and
the rows are kept as positive controls.

The history of this claim is the part worth keeping. "Every guard is now
individually falsifiable" was asserted, then recorded as retracted while the
assertion itself still stood a few paragraphs below — the document claiming and
disclaiming the same thing at once. It was then replaced with "one guard is not
falsifiable", which was also false: three more guards and two claimed
properties survived deletion. The lesson is that a summary count is the wrong
shape for this evidence. The table above names each guard and the pin that
kills it, so a future reader checks entries rather than trusting an adjective.

Three of the round-two seven survived their first run. `primary_email_address_id` and
`email.id` masked each other, and the try/except masked the blank-address
guard, so all three passed while proving nothing. Rather than report six of
seven, pins were added that isolate each: a blank id on both sides, an object
whose `__eq__` answers true to everything, and a direct call to
`_identity_from_user` that bypasses the try.

Two harness defects are recorded because both produced plausible numbers that
were wrong. The first restored from git `HEAD` instead of the working copy,
silently reverting the implementation so every run after the first measured the
unfixed tree. The second passed a two-path test selector through an unquoted
zsh variable, which does not word-split, so pytest received one nonexistent
path and reported "no tests ran" — read as a result rather than as a broken
harness, that would have been seven fabricated survivals. A mutation number is
only meaningful next to a green control that used the identical command.

### Test-side corrections, disclosed

Two changes were made to the pre-existing `test_human_identity.py`, not one. An
earlier version of this section listed only the first and presented itself as
complete.

The first: in
`test_clerk_adapter_uses_official_verifier_authorized_party_and_user_record`,
the substituted Clerk user object had no `id`, no `deprovisioned`, and no
`verification` on its email address. The real SDK model carries all three, so
that fixture could not have exercised any of these boundaries. It is now shaped
after the installed model — a fixture becoming faithful, not an assertion being
relaxed; the test's expectations are unchanged.

The second: the assertion on the binding-refusal message changed from
`"preprovisioned" in str(exc) or "already linked" in str(exc)` to exact
equality with `_IDENTITY_NOT_BINDABLE`. That is a strengthening — the old form
accepted either of two texts, the new one accepts exactly one — and it was
required because collapsing the two messages is what closes the enumeration
oracle. It is disclosed because a reader auditing which assertions moved should
find both here, not one.

### Unchanged invariants, re-derived rather than asserted

274 total capabilities, 253 grouped actions, 21 internal-only, 15
hosted-withheld, 238 hosted-reachable; catalog fingerprint `84578ae71567ed18`;
visible tools Local 8, National 10, Full Operator 20, JV Partner 11. Source and
tests compile, `git diff --check` is clean, the changed-content credential scan
is clean, no port-8000 listener, no migration or dependency change, and an
isolated wheel packages the capability matrix, the source-rights registry, the
surface catalog, and all eight numbered migrations plus `restore_privileges.sql`.

### Lifecycle matrix follow-up 2026-08-06

The Phase 5I contract's lifecycle inventory said the founder's enumerated flows
were already covered by existing tests. Auditing that claim rather than
restating it found four enumerated flows with no store-level pin at all:
a stale consent handle, concurrent approval of one handle, replay after
consumption, and reconnect after session revocation. Four pins were added
(`4,958` to `4,962`).

What they pin, stated precisely because measuring it changed the answer:

- **Single-use consent is pinned.** The replay pin fails when the
  `consumed_at IS NULL` select filter and the single-row UPDATE guard are
  removed *together*. Each alone is masked by the other — defence in depth,
  and neither is individually falsifiable.
- **Concurrency is documented, not pinned.** Eight threads racing one handle
  produce exactly one authorization, but removing `BEGIN IMMEDIATE`, or the
  UPDATE guard, or both, leaves the test green: SQLite serializes writers on
  its own. The test asserts the property; it does not establish that the
  locking is what provides it. The test comment says so.
- **Stale rejection is documented, not pinned.** `consume` deletes expired rows
  before selecting, so the explicit expiry comparison is unreachable — an
  equivalent mutant.
- **Reconnect after revocation is pinned** by behaviour: a revoked token stays
  dead and the next sign-in issues a different token and CSRF pair.

Recorded this way because the alternative — writing four tests and calling four
guards covered — is precisely the error that rejected five earlier rounds.

### Open items this phase records but does not close

- No unbind path exists: there is no `DELETE FROM platform_human_identities`
  anywhere in `src/`, so a wrong binding is permanent short of deleting the
  user and cascading away their data.
- `medawarcre.human_identities` in PostgreSQL lacks the
  `UNIQUE (provider, user_id)` the SQLite table has, and
  `0001_authoritative_cloud.sql` indexes `lower(email)` under a Unicode-aware
  `lower()`. Both are unreachable today — there is no PostgreSQL identity
  binding code — and both are blockers for the hosted identity cutover.
- A `platform_users` row written before this change is unreachable by design
  **only if its stored value is not already the canonical form**. Pure-ASCII
  addresses written by the old `provision_workspace` path were `.casefold()`ed,
  which is byte-identical to the new form, so those rows are unaffected. Rows
  carrying a casefold-collapsing or non-ASCII-capital character must be
  re-keyed in private staging before first production use. An earlier version
  of this line said every prior row was unreachable, which overstated it.
- The Clerk instance's verify-at-sign-up setting and its enabled
  social/enterprise connection set are now load-bearing deployment decisions.

### Boundary

No deployment, DNS change, billing activation, provider mutation, or
customer-data action occurred. No real Clerk credential was used or requested;
the adapter is proven against the official SDK's types through a substituted
client, and a live Clerk test instance remains the next external blocker for
this thread.

## Phase 5J production secret boundary 2026-08-06

Contract: `docs/launch/PHASE_5J_SECRET_BOUNDARY_CONTRACT.md`. Base `e78d390`.

Founder decision, recorded above: a local `.env` is never the production source
of truth for a real Clerk, Stripe, Skool, or database credential.

### What this phase found

The mechanism the decision requires already existed and was never stated or
proven. `CreConfig` is a `pydantic-settings` model with `env_prefix="CRE_"`, so
environment variables already outrank the optional `.env` file — which is
exactly the managed-secret injection path — and every credential field was
already `SecretStr`. This phase did not build machinery. It made the guarantees
explicit, pinned them, and wrote the operational contract.

Fifteen pins were added, thirteen of which passed on arrival. That is the
honest shape of it: the properties held, nothing established that they held,
and nothing would have caught a regression.

The two that failed were both in the pins themselves. The type sweep flagged
`oauth_token_rate_limit_per_minute` — an `int` matching the `token` marker, a
rate limit rather than a credential, now an audited exemption with its reason.
And the exemption-rot check caught that two of the four exemption names I had
written did not exist on the model at all, which is the failure mode that check
exists for: a stale exemption silently excuses whatever later reuses the name.

### Evidence

Secret-boundary module 15 passed. Repository gate 4,977 passed, 4 skipped, up
from 4,962 by exactly these fifteen. Both mutations kill: typing
`clerk_secret_key` as `str` errors the whole module, and typing
`stripe_api_key` as `str` fails five pins.

Every credential field is `SecretStr`; the only non-secret name match is the
rate limit. `.env` is untracked, gitignored, and not required — configuration
loads from the process environment alone, and an injected value beats a stale
file. No `repr`, `str`, or JSON dump discloses a value; no raised error carries
one; a missing Clerk secret answers `503 human_identity_unconfigured` rather
than degrading; and a sweep of every registered route found none emitting
secret material.

### An unprovenanced module, read and deleted

An untracked `src/cre_mcp/platform/secrets.py` appeared in the worktree during
this session. I did not write it; the likeliest origin is a review agent
writing into the repository despite read-only instructions. It is recorded
because an unexplained source file in a security phase is exactly the thing
that should never be quietly absorbed.

It was read in full rather than deleted on sight, because it implemented the
requested boundary competently: provider-neutral, no new dependency, names-only
so no value could be logged or raised, and resolved at call time so rotation
needs no rebuild. Its PostgreSQL variable names check out against the code.

It was deleted anyway, for a specific reason: `CRE_STRIPE_ENABLED` and
`CRE_SKOOL_ENABLED`, the flags its conditional logic gates the Stripe and Skool
credentials behind, **do not exist in this codebase**. Nothing reads them. So
those secrets would never have been treated as required, silently, while the
module read as though it checked them. It was also entirely unused — no import,
no test.

Plausible and wrong is worse than absent. The boundary the founder decision
asks for already exists in `pydantic-settings` environment precedence, is now
proven by fifteen pins, and its inventory lives in `deploy/DEPLOY.md` as a
table a reader can check against the model. Every name in that table was
verified present on `CreConfig`; none is invented.

### External staging integration gate

A real Clerk network smoke test is the only unverified item in the identity
thread and is recorded as an external gate rather than a blocker. The secret
Max supplied was rejected by Clerk's own API as invalid — verified not to be a
transcription fault: 50 characters, correct prefix, no whitespace, no non-ASCII,
and the publishable key decodes to exactly the configured issuer host. A
development-instance key is needed to close it. Local engineering does not wait
on it.

### Boundary

No provider chosen, no infrastructure provisioned, no deployment, no DNS, no
billing, no spend. Tests and documentation only; no source change.

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
