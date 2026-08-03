# PHASES 27–29 — Nearby-Brand · Control Engine · Motivation Graph  ✅

Built in PARALLEL by three Codex (gpt-5.6-sol xhigh) sessions on `mini`, each in strict
file isolation (disjoint new packages, no shared-file edits, no git). Fable verified every
one (ran their tests, spot-checked the algorithms) and wired them into `register_all`.
Tool count 50 → 61.

## Phase 27 — Nearby-Brand / Co-tenancy engine  (Max's requested feature)
`enrichment/nearby.py` + `tools/nearby_tools.py`. Live-verified OSM Overpass (free, no key)
across mirrors [overpass-api.de, lz4, private.coffee] with a User-Agent + retry + in-memory
TTL cache; `nearby_brands(lat,lon,radius)` → branded POIs with haversine distances;
`classify_anchor` (complementary traffic-driver vs competitor vs neutral); `trade_area_anchors`
→ a co-tenancy summary ("Starbucks, Chase within 800m") for tenant pitches + scoring.
Tools: `nearby_brands`, `trade_area_anchors`. 6 tests.

## Phase 28 — Control Engine  (Cherif's wedge, on the Phase-28-groundwork catalog)
`control/{site_fit,vacant,spread,structures,pitch}.py` + `tools/control_tools.py`.
- `match_tenants_to_site` / `evaluate_tenant_site_fit` — rank the 30-tenant catalog against a site.
- `detect_vacant` — heuristic vacant/2nd-gen/dark-box screen from listing signals.
- `model_lease_creation_spread` — value_leased = rent·sf/cap; net spread after TI, LC, carry,
  and an execution-risk haircut; return-on-control. (Verified: 30·2500/0.065 = 1,153,846.)
- `recommend_control_structure` — ranks option / master-lease / seller-finance / extended-close /
  assignment / ground-lease by nonrefundable exposure, seller problem solved, execution probability.
- `build_tenant_pitch` — plain-English outreach citing traffic + passed-in nearby anchors.
- `find_control_opportunities` — combines vacant + fit + spread over a listing set.
Tools: 6. 5 tests.

## Phase 29 — Motivation Graph  (off-market)
`graph/motivation.py` + `tools/motivation_tools.py`. `MotivationSignal` (trigger, evidence,
severity, freshness) → `score_motivation` → engagement-probability (saturating, freshness-
decayed — many weak signals never beat one strong) + inferred seller priorities
(debt_release/speed/certainty/tax_timing/confidentiality/price) + honest caveats
("engagement != a transaction; verify"). NOT a static distress score. Tools:
`owner_motivation`, `record_trigger_event`, `find_motivated_owners`. 5 tests.
Honest gap noted in-module: free county tax/lien/foreclosure/probate feeds get wired later;
CMBS special-servicing is paid.

## Verified
Full integrated suite: **597 passed**. 61 tools registered (contract count tests updated 50→61).
