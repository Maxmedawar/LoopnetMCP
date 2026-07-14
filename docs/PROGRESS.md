# BUILD PROGRESS — MedawarCRE Engine

Branch: `feature/cre-engine`. Director: Fable (Claude). Builder: Codex (gpt-5.6-sol xhigh).

Codex: append a dated entry at the end of each phase (status, what changed, `pytest` result).
Fable reviews independently after each phase before advancing.

| Phase | Title | Status | Tests |
|---|---|---|---|
| 1 | Foundation refactor | 🟢 complete | 167 passed, 1 warning |
| 2 | Source abstraction + LoopNet adapter | 🟢 complete | 178 passed, 1 warning |
| 3 | Crexi + multi-source search | 🟢 complete | 199 passed, 1 warning |
| 4 | Geo + market intelligence | 🟢 complete | 225 passed, 1 warning |
| 5 | Underwriting + scoring + flagship tools | 🟢 complete | 253 passed, 1 warning |
| 6 | Distressed sources | 🟢 complete | 285 passed, 1 warning |
| 7 | Owner/parcel enrichment | 🟢 complete | 304 passed, 1 warning |
| 8 | Attributes, traffic counts + rent comparables | 🟢 complete | 325 passed, 1 warning |
| 9 | Offer & LOI engine | 🟢 complete | 343 passed, 1 warning |
| 10 | Outreach & negotiation coach | 🟢 complete | 409 passed, 1 warning |
| 11 | Financing & qualification | 🟢 complete | 426 passed, 1 warning |
| 12 | Due-diligence tracker + closing coordinator | 🟢 complete | 442 passed, 1 warning |
| 13 | Pipeline / CRM + saved-search alerts | 🟢 complete | 454 passed, 1 warning |
| 14 | Listing intelligence + confidence gating | 🟢 complete | 352 passed, 1 warning |
| 15 | Free comps engine + AVM | 🟢 complete | 371 passed, 1 warning |
| 16 | Live-API hardening | 🟢 complete | 378 passed, 1 warning |
| 17 | Completeness hardening | 🟢 complete | 385 passed, 1 warning |
| 18 | Entity/structure engine + 1031 manager | 🟢 complete | 470 passed, 1 warning |
| 19 | Capital-raise suite + SEC guardrails | 🟢 complete | 491 passed, 1 warning |
| 20 | After-tax returns + operating playbook | 🟢 complete | 506 passed, 1 warning |
| 21 | Correctness hardening | 🟢 complete | 519 passed, 1 warning |
| 22 | Score backtest / calibration harness | 🟢 complete | 530 passed, 1 warning |
| 23 | Comps depth: opt-in paid providers + free counties | 🟢 complete | 543 passed, 1 warning |
| 24 | Hosting artifacts: Dockerized HTTP MCP + Cloudflare | 🟢 complete | 552 passed, 1 warning |
| **Overall** | **Full roadmap + correctness/comps/hosting punch list delivered** | **🟢 PUNCH LIST COMPLETE — FEATURE-COMPLETE + DEPLOYABLE — 45 tools** | **552 passed, 1 warning** |

## Log

- 2026-07-13 — Phase 1 foundation refactor complete.
  - Status: GREEN; package seams and all legacy behavior contracts verified.
  - Files changed: renamed `src/loopnet_mcp/` to `src/cre_mcp/`; split `models/`,
    `http/`, `cache/`, and `tools/`; added back-compat scraper/cache shims; renamed
    config and package metadata; updated source/test imports; added `tests/test_contract.py`.
  - Pytest: `======================= 167 passed, 1 warning in 20.19s ========================`
- 2026-07-13 — Phase 2 source abstraction and LoopNet adapter complete.
  - Status: GREEN; all three legacy tools now route through `SourceRegistry` and
    `LoopnetSource` while retaining their Phase 1 signatures, docstrings, and dict shapes.
  - Files changed: removed the dead `src/cre_mcp/cache.py`; added unified listing models
    and `sources/{base,registry,dedupe}.py`; moved LoopNet URLs/parsers under
    `sources/loopnet/`; added the LoopNet adapter and legacy-path shims; rewired tool
    internals and HTTP-boundary mocks; added `tests/sources/` coverage.
  - Pytest: `======================= 178 passed, 1 warning in 19.99s ========================`
- 2026-07-13 — Phase 3 Crexi source and multi-source search complete.
  - Status: GREEN; live Crexi search/detail shapes confirmed, default LoopNet tool
    contracts preserved, and explicit source selection returns fault-isolated unified results.
  - Files changed: implemented policy-driven JSON GET/POST, per-request cache TTLs,
    Cloudflare detection and in-page API fallback; added source toggles, the Crexi
    adapter/mappers/fixtures, current universal-search filter mapping, registry wiring,
    Crexi-preferred dedupe, rich multi-source tool output, and Phase 3 acceptance tests.
    The current Crexi UI uses `universal-search/v2/search`; legacy `assets/search`
    fixtures remain covered, and asset detail continues through `assets/{id}`.
  - Pytest: `======================= 199 passed, 1 warning in 21.25s ========================`
- 2026-07-13 — Phase 4 geo and market intelligence complete.
  - Status: GREEN; persistent government-data caching, keyless geo resolution,
    fault-isolated market coverage, scoring, comparison, and legacy contracts verified.
  - Files changed: added SQLite write-through caching and government host policies;
    added geo models, HUD USPS crosswalk persistence/static fallbacks, and Census
    resolution; added normalized market models, auth client, Census/BLS/FRED/HUD/BEA/IRS
    providers, MarketIntel/scoring, and `market_intel`/`compare_markets` tools; added
    captured/representative fixtures and Phase 4 acceptance tests under
    `tests/{cache,geo,market,tools}/`.
  - Pytest: `======================= 225 passed, 1 warning in 21.09s ========================`
- 2026-07-13 — Phase 5 underwriting, Medawar scoring, and flagship tools complete.
  - Status: GREEN; missing-data-aware underwriting and scoring, hard disqualifiers,
    market/core composition, confidence, narratives, ranking, and legacy contracts verified.
  - Files changed: added underwriting assumptions, pure metrics, and result models; added
    declarative scoring models, centralized thresholds, signal/disqualifier registries,
    core/NNN/value-add/location-retail rubrics, engine, and explanations; added deal models
    and registered `analyze_deal`/`find_deals`; added hand-computed metric tests, engine edge
    tests, nine golden deal snapshots with `--update-golden`, and mocked end-to-end tool tests.
  - Pytest: `======================= 253 passed, 1 warning in 21.30s ========================`
- 2026-07-13 — Phase 6 distressed sources, NDE rubric, and deal discovery complete.
  - Status: GREEN; live HUD REO, Auction.com, and three county ArcGIS feeds now
    flow through the shared source seam, partial-data distressed scoring, asset-score
    carryover, ranking, and the registered `find_distressed` tool.
  - Files changed: added the reusable ArcGIS paging helper, persistent ArcGIS and
    anti-bot Auction.com fetch policies, Imperva detection, HUD/Auction.com/county
    source adapters and live-captured fixtures, configured county geo fallbacks, the
    declarative A.4 distressed rubric/signals/disqualifiers, distressed asset routing,
    and Phase 6 HTTP/source/scoring/tool acceptance tests. Auction.com GraphQL and the
    Guilford NC, Yavapai AZ, and Douglas CO county schemas were confirmed live; no
    Phase 6 fixture is marked `# VERIFY`.
  - Pytest: `======================= 285 passed, 1 warning in 21.12s ========================`
- 2026-07-13 — Phase 7 owner and parcel enrichment complete; 7-phase build feature-complete.
  - Status: GREEN; county parcel resolution, persistent owner caching, parcel-aware scoring,
    non-fatal `analyze_deal` enrichment, and the ninth registered tool are verified.
  - Files changed: added enrichment models and the source-agnostic `ParcelProvider`; added the
    shared-ArcGIS-backed county provider, three-county registry, owner normalization/entity/
    absentee orchestration, and persistent cache; wired parcel/owner output and scoring signals
    into deals; added `owner_lookup` registration/export; added three live-captured parcel
    fixtures and Phase 7 provider/county/owner/tool/scoring acceptance tests. Guilford NC,
    Yavapai AZ, and Douglas CO assessor endpoints were all reconfirmed through live provider
    queries; no Phase 7 fixture is marked `# VERIFY`.
  - Pytest: `======================= 304 passed, 1 warning in 21.38s ========================`
- 2026-07-13 — Phase 8 attributes, traffic counts, and rent comparables complete.
  - Status: GREEN; ten registered tools, non-fatal public-data enrichment, newly activated
    traffic/visibility/parking/rent-gap signals, confidence-aware scoring, and legacy contracts
    are verified.
  - Files changed: extended the shared ArcGIS helper to preserve optional WGS84 geometry; added
    config-driven, persistently cached NC/AZ/CO/TX/FL/CA DOT AADT lookup; added listing-text and
    cached OpenStreetMap drive-thru/parking enrichment; added RentComps models, monthly persistent
    Zillow ZORI ZIP/metro ingestion, Census ACS/HUD bedroom-tier assembly, optional keyed RentCast,
    and the `get_rent_comparables` tool; wired compact deal attributes and Phase 8 signals; added
    live-captured traffic/ZORI/OSM fixtures and acceptance tests. All six DOT layers and both ZORI
    CSV endpoints were confirmed live. Only the paid-key RentCast fixture is marked `# VERIFY`.
  - Pytest: `325 passed, 1 warning in 23.46s`
- 2026-07-13 — Phase 9 offer and LOI execution engine complete.
  - Status: GREEN; underwriting-grounded open/target/walk recommendations, motivation-aware
    negotiation buffers, confidence/caveats, complete explained non-binding LOI drafts, six
    state-specific closing notes plus the general fallback, and all 12 tools are verified.
  - Files changed: added execution models and the reusable draft-not-advice guardrail; added
    centralized offer/LOI policy constants, strategy-aware offer pricing and financing limits,
    jurisdiction-aware LOI generation, MCP execution tools, server registration/exports, and
    Phase 9 offer/LOI/tool acceptance tests; updated prior tool-count assertions to 12.
  - Pytest: `343 passed, 1 warning in 23.06s`
- 2026-07-13 — Phase 14 listing intelligence and confidence gating complete.
  - Status: GREEN; deterministic listing-prose extraction now routes lease-heavy deals to the
    correct strategy, extracted NNN facts feed existing signals, and low-evidence numeric scores
    are honestly surfaced as gated `NR` results with prioritized document/comps next steps.
  - Files changed: added `ListingFacts` and the offline `listing_facts` extractor; wired facts
    through deal contexts, routing, NNN signals, analysis/search output, and execution context;
    added tunable 50% confidence/coverage gates, `DealScore.gated`, actionable explanations,
    updated scoring goldens, and Phase 14 extraction/routing/gating regression tests.
  - Pytest: `352 passed, 1 warning in 26.39s`
- 2026-07-13 — Phase 15 free comps engine and AVM complete.
  - Status: GREEN; 13 registered tools, county-limited public sales, honestly labeled value
    ranges/fallbacks, confidence-discounted value signals, subject-sale anchoring, and legacy
    contracts are verified.
  - Files changed: added `SaleComp`/`ValueEstimate`, shared-ArcGIS county comp retrieval,
    Guilford/Yavapai sales schemas, the county-comps/FHFA/listing-context AVM cascade, a keyless
    persistent FHFA state-HPI provider, regional replacement-cost policy, value-aware deal and
    execution contexts, and the registered `get_comps` tool; extended parcel enrichment with
    fault-isolated latest-sale lookup; added live sales/FHFA fixtures and Phase 15 acceptance
    tests, and refreshed score goldens. Guilford NC and Yavapai AZ were confirmed live; Douglas
    CO remains deliberately unwired because no public sale-price layer was verified. No Phase 15
    fixture is marked `# VERIFY`.
  - Pytest: `371 passed, 1 warning in 23.09s`
- 2026-07-13 — Phase 16 live-API hardening complete.
  - Status: GREEN; keys load from `.env` without shell exports, Austin live market coverage rose
    from the Director's 53% baseline to 17/18 metrics (94.44%), and provider failures remain
    isolated coverage gaps.
  - Files changed: enabled pydantic-settings dotenv loading; corrected FRED `api_key` query auth,
    HUD metro/county entity formatting, and BEA Regional `Year=LAST5` parsing; replaced the broken
    Census permits endpoint with the official final annual county BPS file; added lazy persistent
    loading of official IRS SOI county inflow/outflow CSVs; added persistent host policies, fresh
    live fixtures/provenance notes, and provider/config regression tests. Census ACS/BPS, BLS,
    FRED DGS10/MORTGAGE30US/SOFR, HUD FMR/IL/crosswalk, BEA Regional, FHFA, and IRS SOI were
    verified live. HUD initially returned 401 while the new token propagated, then returned 200
    with the corrected Austin entity `METRO12420M12420`.
  - Pytest: `378 passed, 1 warning in 22.92s`
- 2026-07-13 — Phase 17 completeness hardening complete.
  - Status: GREEN; all 13 configured county parcel endpoints were verified live, the Austin
    deal now returns its real Travis County owner/parcel, Overpass form requests work against
    the primary endpoint, and live Austin market coverage is 18/18 metrics (100%).
  - Files changed: expanded the county parcel registry across Travis, Harris, Dallas, Bexar,
    Maricopa, Clark, Miami-Dade, Broward, Fulton, and Mecklenburg; added verified Maricopa and
    Clark spatial sales layers while retaining labeled fallbacks where no free sales layer was
    found; added Nevada and Georgia AADT layers; added cached form-encoded Overpass POST support,
    required headers, and Kumi fallback; corrected the BLS QCEW series to all-employment history;
    surfaced compact value provenance in `analyze_deal`/`get_comps`; refreshed live fixtures and
    added county, traffic, Overpass, QCEW-growth, and provenance tests.
  - Honest gaps: free spatial closed-sale coverage remains available only for Guilford, Yavapai,
    Maricopa, and Clark; other counties use explicit weaker/no-estimate AVM fallbacks. The Dallas
    parcel layer is live but its published tax snapshot is dated 2019. Kumi was configured as a
    non-fatal fallback but timed out in the lab; the primary Overpass endpoint returned live OSM
    data. Score/value backtesting remains future work and was intentionally out of Phase 17 scope.
  - Pytest: `385 passed, 1 warning in 21.62s`
- 2026-07-13 — Phase 10 outreach and negotiation coach complete.
  - Status: GREEN; all 16 tools are registered, free broker/owner/public-registry contact
    assembly is source-labeled and fault-isolated, every outreach channel/angle is a complete
    deterministic guarded draft, and counter coaching parses economics and term traps against
    the modeled target/walk price, cap-rate floor, and strategy DSCR threshold.
  - Files changed: added execution contact/outreach/counter models and services; added the
    per-state TX/AZ/NV/FL/GA public business-search registry, live Texas registered-agent and
    officer adapter, optional keyed RealEstateAPI v2 skip-trace boundary, persistent host
    policies, centralized counter thresholds, three MCP tools, exports/registration, real
    Texas fixtures, and Phase 10 acceptance tests. Crexi detail enrichment now recovers the
    marketing broker through its targeted universal-search ID record when detail omits it.
  - Live verification: the official Texas Comptroller/SOS-backed JSON service returned ELEGANT
    AUSTIN LLC's active registered agent and seven public officer rows. A real Crexi listing
    (`1749592`) returned broker Travis Crow / Cushman & Wakefield plus Travis County owner
    712 CONGRESS HOLDINGS LLC in one `find_contact` result. Arizona is a session-bound public
    portal, Nevada presented Incapsula, and Florida/Georgia presented Cloudflare; those four
    remain configured, logged, graceful automation gaps rather than brittle unverified scrapers.
  - Pytest: `409 passed, 1 warning in 21.75s`
- 2026-07-13 — Phase 11 financing and qualification complete.
  - Status: GREEN; all 19 tools are registered, asset-specific lender types are ranked with
    explicit ineligibility reasons, borrower cash/sponsor gates are visible and actionable,
    and loan proceeds are constrained by the lesser of LTV and DSCR with every assumption echoed.
  - Files changed: added financing/debt/qualification models and execution services; added a
    centralized financing policy block for lender-type eligibility, FRED spreads, LTV ranges,
    amortization/IO/recourse, debt scenarios, closing costs, reserves, net-worth, experience,
    and credit gates; added shared financing guardrails, three MCP tools, server registration/
    exports, Phase 11 math/eligibility/tool acceptance tests, and the Phase 10 deposit-price
    parser carry-over regression. No dependency was added.
  - Policy verification: official agency materials support the 5+ unit/stabilized screen and
    Freddie small-balance materials publish net worth equal to the loan plus nine months of
    principal-and-interest liquidity; 13 CFR 120.131 requires at least 51% operating-business
    occupancy in an existing SBA-financed building. These remain labeled typical screens, not
    commitments, and named-lender matching remains intentionally deferred.
  - Live verification: Crexi `2247699` used live FRED DGS10 4.56% plus the typical bank spread
    for a 7.56% modeled rate. DSCR bound proceeds at $1,349,525 against the $2,506,400 purchase,
    with $1,156,875 acquisition equity before costs/reserves. The same passive NNN investment
    explicitly returned SBA 504/7(a) as not eligible.
  - Pytest: `426 passed, 1 warning in 21.79s`
- 2026-07-13 — Phase 12 due-diligence tracker and closing coordinator complete.
  - Status: GREEN; durable deal/checklist state, asset-aware diligence clocks, state-routed
    professional closing roles, entity-before-lender sequencing, novice-readable clear/terminate
    gates, and the repeated wire-fraud stop protocol are verified.
  - Files changed: added the shared-database `DealStore` with isolated `deals`/`dd_items` tables,
    WAL-safe `asyncio.to_thread` operations, stable `source:source_id` keys, status preservation,
    and compact listing; added `DDItem`/`DDPlan` and `ClosingStep`/`ClosingPlan` models; added the
    core, retail/NNN, and multifamily diligence templates with back-solved deadlines; added the
    TX/AZ/CO/CA/FL/NV title-or-escrow routes, GA attorney-led and NC attorney-supervised routes,
    and GENERAL fallback; added four MCP tools plus store/diligence/closing/tool acceptance tests.
  - Live verification: Crexi `2247699` generated a persisted retail/NNN plan containing
    both Phase I and tenant estoppel/SNDA, and its Texas closing runway repeated the known-number
    wire verification protocol on the funding step. The FBI, Texas Department of Insurance,
    California DRE, North Carolina State Bar, and State Bar of Georgia guidance informed the
    cautious routing language; every output still requires local CRE counsel/professional review.
  - Tool-count note: Phase 11 had 19 tools and Phase 12 specifies four new named/registered tools,
    so preserving every approved tool produces 23. The phase document's stated total of 22 is an
    arithmetic conflict; no existing or required tool was removed to force that count.
  - Pytest: `442 passed, 1 warning in 21.75s`
- 2026-07-13 — Phase 13 pipeline/CRM and saved-search alerts complete; Execution layer complete.
  - Status: GREEN; durable pipeline stages/notes/score snapshots, source-qualified dedupe,
    migration-safe Phase 12 database upgrades, persisted buy-boxes, per-search seen-match memory,
    and new-only on-demand alert checks are verified. The full offer → LOI → outreach/negotiation
    → financing → diligence → closing → pipeline/alerts Execution/Coach layer is now complete.
  - Files changed: extended `DealStore` with all nine pipeline stages, timestamped note history,
    score/grade/strategy snapshots, stage filtering, `saved_searches`/`seen_matches`, idempotent
    seen recording, and legacy-schema migration; added six pipeline/alert MCP tools with grouped
    pipeline output, buy-box validation, score-floor enforcement, per-search fault isolation, and
    explicit pull-only disclosure; added pipeline migration/dedupe/persistence, saved-search
    replay, error isolation, tool-boundary, and registration acceptance tests.
  - Live verification: real Crexi deal `2247699` persisted with its score, moved from `analyzing`
    to `contacted`, and retained its latest note. A temporary Austin retail/Crexi saved search
    returned 50 scored new matches on its first pull and zero on the immediate replay, proving
    `seen_matches` suppression. Phase 13 adds six named tools to the prior 23, yielding 29; the
    phase document's `~28` target is approximate and no required/existing tool was removed.
  - Hosting boundary: `check_alerts` is deliberately on-demand and runs only when called. True
    proactive scheduled or push alerts require deploying the always-on hosted service with a
    cron/scheduler; the local MCP process cannot initiate checks while it is not running.
  - Pytest: `454 passed, 1 warning in 21.51s`
- 2026-07-13 — Phase 18 entity/structure engine and 1031 manager complete.
  - Status: GREEN; deterministic LLC/DST/TIC/QOF screening, prominent taxpayer/title and
    securities traps, durable exchange clocks/replacement lists, identification-rule stops,
    boot/basis estimates, professional gates, and all 34 registered tools are verified.
  - Files changed: added structure intent/advice, exchange/replacement, and boot/basis models;
    added deterministic entity selection with SMLLC, DST, TIC, QOF, partnership-interest,
    same-taxpayer-title, and SEC/Phase-19 guidance; extended the shared SQLite `DealStore` with
    exchange and replacement-identification tables; added the 45/180-day manager, 3-property/
    200%/95% controls, and simplified boot/carryover-basis estimator; added five MCP tools,
    shared structure guardrails, exports/registration, and Phase 18 acceptance tests.
  - Rule verification: IRS Form 8824 instructions and Publication 544 support the 45-day
    identification, earlier-of-180-days-or-return-due-date receipt deadline, qualified-
    intermediary safe harbor, 3-property/200%/95% framework, excluded partnership interests,
    and Form 8824 reporting. Revenue Ruling 2004-86 and Revenue Procedure 2002-22 inform the
    carefully qualified DST/TIC notes; IRS QOF guidance and SEC offering-path guidance inform
    the Opportunity Zone and capital-raise gates. Outputs remain educational screens/estimates,
    never legal, tax, securities, or investment advice.
  - Live-ish verification: a persisted August 1, 2026 relinquished close returned September 15,
    2026 and January 28, 2027 deadlines. Syndication intent triggered both the SEC/Phase-19 gate
    and the loud `1031-INELIGIBLE` multi-member LLC/partnership-interest trap. Every exchange
    result repeats the QI-before-closing/proceeds stop and CPA/Form-8824 gate.
  - Deviation: none. Safety behavior: the engine deliberately rejects an over-200% fourth
    identification instead of presuming the narrow 95% actual-receipt exception will later
    rescue it; a QI/tax attorney must approve that exceptional path.
  - Pytest: `470 passed, 1 warning in 21.79s`
- 2026-07-13 — Phase 19 capital-raise suite and SEC guardrails complete.
  - Status: GREEN; durable investor/commitment CRM, preliminary 506(b)/(c) action blockers,
    transparent LP/GP waterfall scenarios, attorney-ready PPM/subscription/Form D skeletons,
    anti-fraud refusals, mandatory counsel gates, and all 41 registered tools are verified.
  - Files changed: added capital CRM/compliance/waterfall/document models; extended the shared
    SQLite `DealStore` with investor and idempotent deal-commitment tables; added the common
    securities hard gate and recursive promised/guaranteed/risk-free claim refusal; added Reg D
    action checks, preferred return/return-of-capital/catch-up/promote/tiered-split modeling,
    DRAFT PPM/subscription/Form D generators, seven MCP tools, exports/registration, and Phase 19
    store/service/tool acceptance tests. No dependency was added.
  - Rule verification: current SEC small-business guidance confirms that 506(b) prohibits general
    solicitation and permits no more than 35 sophisticated non-accredited purchasers with enhanced
    disclosures; 506(c) permits broad solicitation only when every purchaser is accredited and
    the issuer takes reasonable verification steps. Both paths require Form D within 15 days after
    first sale, may require state notice filings/fees, remain subject to anti-fraud rules, and need
    bad-actor review. The engine treats a 506(b) checked box as no substitute for the issuer's
    reasonable-belief facts, while correctly not imposing the distinct 506(c) verification test.
  - Live-ish verification: `check_solicitation("506b", "advertise_publicly")` and a 506(c)
    accredited-but-unverified acceptance both returned `allowed=false`. Real Crexi deal `2247699`
    produced a five-year explicit-input scenario with 10.292502% LP IRR, 1.518519x LP equity
    multiple, and $121,717.49 modeled GP promote; output labeled every return as a scenario,
    echoed assumptions/debt provenance, and repeated the securities-attorney hard gate.
  - Anti-fraud verification: `guaranteed_return` and risk-free/promised-performance inputs are
    refused before modeling or drafting. PPM/Form D outputs are stamped `DRAFT — ATTORNEY REVIEW
    REQUIRED`, never accept funds or establish an exemption, and require securities counsel before
    solicitation or money plus Form D/state blue-sky work. Deviation: none.
  - Pytest: `491 passed, 1 warning in 22.12s`
- 2026-07-13 — Phase 20 after-tax returns and operating playbook complete; full roadmap complete.
  - Status: GREEN; the Execution/Coach, Trust, and Structure/Scale layers are all delivered.
    All 43 tools are registered, and the engine now carries a deal from sourcing and evidence-
    gated scoring through execution, structure/capital, after-tax modeling, and operations.
  - Files changed: added transparent `AfterTaxResult`/depreciation models and deterministic
    residential/commercial improvement-basis schedules; added optional simplified 5/7/15-year
    cost-seg/bonus scenarios, annual tax shields, debt-aware pre-/after-tax cash flows, 25%
    unrecaptured-§1250 treatment, capital-gain decomposition, IRR/equity multiples, assumptions,
    and the mandatory CPA/cost-seg-study gate. Added asset-aware `OperatingPlaybook` models and
    month-one, recurring, lease-critical, refi/1031/next-deal calendars; extended `DealStore`
    with durable reminders and retained statuses; added and registered `after_tax_returns` and
    `operating_playbook`; added Phase 20 math, persistence, boundary, and registration tests.
  - Required Phase 19 fix: normalized natural-language purchaser actions so 506(c) now blocks
    accepting an unverified, pending-verification, or merely self-certified accredited investor.
    The verified-accreditation rule and securities-attorney gate remain mandatory.
  - Rule verification: current IRS guidance supports excluding land, 27.5-year residential and
    39-year nonresidential recovery periods, and a maximum 25% rate for unrecaptured §1250 gain.
    Bonus eligibility, placed-in-service timing, MACRS conventions, passive-loss use, basis,
    §1245/§1250 treatment, and state/NIIT effects remain explicitly outside the estimate and must
    be confirmed by a CPA; cost segregation requires a qualified study.
  - Live verification: real priced Crexi deal `2247699` modeled a $2,506,400 purchase at 7.037273%
    pre-tax IRR versus 5.477289% after-tax IRR and exposed the 25% §1250 rate plus CPA gate. Its
    persisted operating playbook returned five month-one actions, the loud post-sale property-tax
    `REASSESSMENT` warning, five recurring controls, six lease critical dates, and three nudges.
  - Honest remaining future work: nationwide closed-sale comparable coverage requires a paid
    source; Medawar Deal Score/value outputs still need outcome-based backtesting; reliable
    production operation against Cloudflare/anti-bot listing sources requires hosted browser/
    proxy infrastructure and monitoring. Unpriced deals remain intentionally unavailable to the
    after-tax model until a purchase-price assumption is supplied.
  - Deviation: none. The model adds a conservative, explicit §1245 recapture line for accelerated
    cost-seg components rather than incorrectly treating every accelerated dollar as §1250 gain.
  - Pytest: `506 passed, 1 warning in 21.91s`
- 2026-07-14 — Phase 21 correctness hardening complete.
  - Status: GREEN; all 43 tools remain registered, securities actions now fail closed, and the
    documented after-tax return keys are populated on priced deals with positive NOI and a
    modeled sale. The full roadmap remains complete with the safety/trust punch list closed.
  - Securities fix: replaced the prior "no clear violation" fallback with an explicit normalized
    `(mode, action)` allowlist and the default-deny reason `Not explicitly permitted — treat as
    prohibited until a securities attorney confirms`. Rule 506(b) public solicitation remains
    blocked; 506(b) non-accredited purchasers without a documented pre-existing substantive
    relationship remain blocked; Rule 506(c) purchaser acceptance/onboarding now requires both
    accredited status and reasonable verification. Unknown strings, including strings that only
    contain an allowed keyword, remain blocked. Known attorney-draft preparation is explicitly
    allowlisted but cannot authorize circulation, solicitation, a sale, or accepting money.
  - Tax output fix: added canonical `pre_tax_irr`, `after_tax_irr`, `depreciation_annual`, and
    `recapture_1250` fields to `AfterTaxResult` and the MCP dict while retaining the detailed
    schedule, unrecaptured-§1250 gain/rate/tax fields, and backward-compatible `*_irr_pct` keys.
    `depreciation_annual` is the first modeled year's total depreciation; `recapture_1250` is the
    modeled federal tax on unrecaptured §1250 gain, both explicitly documented in the schema.
  - Live verification: `check_solicitation("506c", "accept_unverified_accredited")` and an
    unknown `launch_the_moon_campaign` action both returned `allowed=false` with the securities-
    attorney gate; verified 506(c) advertising returned `allowed=true` without approving any
    purchaser or sale; 506(b) general solicitation returned `allowed=false`. Real priced Crexi
    deal `2247699` returned `pre_tax_irr=7.037273`, `after_tax_irr=5.477289`,
    `depreciation_annual=$51,413.33`, and `recapture_1250=$64,266.67` on a $2,506,400 purchase.
  - Rule verification: current SEC guidance confirms that Rule 506(c)'s reasonable-verification
    requirement is independent of merely being accredited and that Rule 506(b) prohibits general
    solicitation. Every result remains a preliminary action gate, never an exemption opinion.
  - Deviation: none. No dependencies or tools were added.
  - Pytest: `519 passed, 1 warning in 21.75s`
- 2026-07-14 — Phase 22 score backtest and calibration harness complete.
  - Status: GREEN; all 45 tools are registered, realized outcomes can accumulate durably, score
    ordering/calibration can be measured from user outcomes or a supplied CSV, and every score is
    explicitly `UNCALIBRATED` by default instead of implying a validated success probability.
  - Files changed: extended `DealStore` with a foreign-keyed `outcomes` table and async
    `record_outcome`/`get_outcomes` methods; each outcome freezes the deal's predicted score,
    grade, and strategy while storing close status, actual price, optional hold/IRR/equity-
    multiple, went-bad label, notes, and timestamps. Added typed calibration report/grade-band
    models, process-safe calibration disclosure status, stdlib CSV ingestion, grade calibration
    curves, grade hit rates, Brier loss, tie-aware Spearman rank discrimination, and 95% Wilson
    good-rate intervals. Added `record_deal_outcome` and `backtest_score` tools plus persistence,
    math, random/non-monotonic, tool-boundary, registration, and score-disclosure tests.
  - Calibration gate: `calibrated=true` requires at least 100 labeled outcomes, at least three
    populated score/grade buckets, monotonically improving realized good rates, Spearman
    discrimination of at least 0.10, and at least a 10-point good-rate spread. These additional
    discrimination/separation checks deliberately prevent a flat random curve from passing merely
    because equal rates are technically non-decreasing. Brier loss treats score/100 as a candidate
    probability only for diagnosis and says plainly that the score is not yet a validated
    probability. Realized-good labels may be supplied directly or derived from realized IRR using
    an explicit 8% threshold; unlabeled/invalid rows are excluded and counted.
  - Disclosure behavior: `DealScore`, `analyze_deal`, `find_deals`, and distressed deal output now
    expose `calibrated`/`score_calibrated` flags and the constant line `Confidence is UNCALIBRATED
    — this score is a screening signal, not a validated probability of success. It has not yet
    been backtested against realized outcomes.` A passing `backtest_score` removes the disclaimer
    for subsequent scores in the running server. A restart conservatively restores it until the
    backtest is rerun, preventing stale calibration from silently suppressing the warning.
  - Verification: a 150-row synthetic set produced A/B/C realized hit rates of 90%/70%/30%,
    Spearman discrimination `0.508304`, Brier loss `0.201667`, a monotonic curve, and
    `calibrated=true`; a large non-monotonic random-like set remained uncalibrated. Real Crexi deal
    `2247699` returned `calibrated=false` with the exact disclaimer in both its DealScore and
    analysis-level metadata. No synthetic outcome was written to the user's real DealStore.
  - Honest path forward: a licensed historical CRE-outcomes dataset or a sufficiently large,
    representative set of the user's own closed-deal outcomes is still required to validate and
    keep monitoring the score. Passing the mechanical gate does not establish causation,
    transportability to other strategies/markets, or immunity from drift.
  - Deviation: none. No dependency was added.
  - Pytest: `530 passed, 1 warning in 22.47s`
- 2026-07-14 — Phase 23 comps depth complete.
  - Status: GREEN; all 45 tools remain registered. Nationwide ATTOM parcel/owner/comps/AVM
    and Regrid parcel/owner adapters are available only when their optional pay-per-use keys are
    configured. With neither key present, owner and comps behavior remains exactly free-only.
  - Paid provider seam: added the shared `CompsProvider` protocol, ATTOM and Regrid adapters,
    defensive mappings, persistent normalized-result caches, explicit `attom`/`regrid` method
    labels, provider-unavailable key gates, and optional `SecretStr` settings plus opt-in signup
    notes. `OwnerLookup` and `get_comps` always try free county data first; they consider a paid
    call only when free coverage is absent or weak and the corresponding key is present. No paid
    provider is instantiated without a key, so the engine cannot auto-charge. Representative
    ATTOM/Regrid fixtures remain marked `# VERIFY` pending access to paid credentials.
  - Free live coverage: verified and wired King County WA (`53033`) three-year parcel sales,
    Wake County NC (`37183`) parcel sales, and Franklin County OH (`39049`) valid sales through
    the existing shared ArcGIS path. Production mapping checks returned normalized, nearby,
    arm's-length-filtered records for all three counties, with source, price, date, coordinates,
    and available building facts preserved.
  - Honest gaps: Hillsborough County FL was not wired because its county endpoint presents a TLS
    chain rejected by the application HTTP stack and the statewide spatial fallback timed out;
    TLS verification was not weakened. Salt Lake County UT's responsive public parcel layer does
    not expose closed-sale price/date fields, so it remains a clearly labeled AVM fallback rather
    than being misrepresented as a closed-sale source.
  - Verification: no ATTOM or Regrid key was present, and the configured paid-provider count was
    zero. Tests cover keyless `ProviderUnavailable`, free-first preference, weak/empty free
    fallback only when a key is set, paid mapping/cache behavior, the three new live county field
    maps, and unchanged no-key tool output.
  - Deviation: none. Candidate counties without a reliable free closed-sale layer remain honest
    gaps. No dependency or tool was added.
  - Pytest: `543 passed, 1 warning in 22.07s`
- 2026-07-14 — Phase 24 hosting artifacts complete; build punch list complete.
  - Status: GREEN; all 45 tools remain registered. The engine is feature-complete and now ships
    an opt-in remote hosting path while preserving the original stdio contract as the default.
  - Transport: added `CRE_TRANSPORT`, `CRE_HTTP_HOST`, and `CRE_HTTP_PORT` configuration plus a
    `--http` CLI override. No flag and no HTTP environment opt-in still call FastMCP with exactly
    `transport="stdio"`; HTTP mode binds the configured host/port and exposes Streamable HTTP at
    `/mcp`. `create_http_app()` constructs the ASGI application without binding for deployment
    integration and verification.
  - Browser/proxy hosting seam: added optional `CRE_BROWSER_PATH` and `CRE_PROXY_URL` settings.
    The installed Chromium path feeds the existing nodriver browser fallback. The proxy remains
    off by default and is scoped only to the LoopNet, Crexi, and Auction.com scraper policies;
    government, county, and market-data traffic remains direct. Proxy credentials are held as a
    secret and are not logged or placed in the image.
  - Artifacts: added a Python 3.11 slim `Dockerfile` with system Chromium/headless libraries, a
    non-root runtime user, persistent-cache location, HTTP defaults, exposed port 8000, and the
    module HTTP command; added `.dockerignore` coverage for `.env`, virtualenvs, caches, and local
    databases. Added `deploy/cloudflared-config.example.yml` with container ingress and the
    required 404 catch-all. Added `deploy/DEPLOY.md` covering image build/run, server-only env
    secrets, durable SQLite volume, tunnel/DNS, Cloudflare Access/Managed OAuth or service-token
    protection, Claude Code registration/login, operational checks, optional pay-per-GB
    residential proxy, and usage-based Cloudflare Containers as a pure-CF alternative.
  - Verification: `cre_mcp.server` imports cleanly; its HTTP entrypoint constructs a
    `StarletteWithLifespan` at `/mcp`; focused tests prove environment and CLI HTTP selection
    without binding, configured host/port dispatch, unchanged stdio dispatch, scraper-only proxy
    use, Chromium launch configuration, and hosting artifact/security invariants. Per the phase,
    no Docker build or external Cloudflare deployment was required or performed in-lab.
  - Genuine remaining Max steps: provision the Docker host or Cloudflare Container; create the
    Cloudflare tunnel, hostname, credentials, server-side secrets, and Access policy; optionally
    configure paid API keys and a cost-capped residential proxy; complete the Cloudflare Access
    login from Claude on the MacBook; obtain securities-attorney review before any real capital
    raise; and keep collecting representative realized outcomes because scores remain
    `UNCALIBRATED` until the calibration gate passes.
  - Deviation: none. No Python dependency or MCP tool was added; stdio remains the default.
  - Pytest: `552 passed, 1 warning in 21.90s`
