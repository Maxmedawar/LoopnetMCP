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
| **Overall** | **8-phase build** | **🟢 FEATURE-COMPLETE — 10 tools** | **325 passed, 1 warning** |

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
