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
| **Overall** | **Phases 1–17 delivered** | **🟢 EXECUTION / COACH LAYER COMPLETE — 29 tools** | **454 passed, 1 warning** |

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
