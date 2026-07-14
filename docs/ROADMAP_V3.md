# MedawarCRE — ROADMAP V3 ("Truth · Control · Memory")

Source of this plan: GPT-5.6 Pro's hardest-honest strategic teardown
(`SecondBrain/wiki/memory/medawarcre/medawarcre-hardest-honest-strategic-evaluation.md`),
filtered for Max's actual use case: an **internal** deal-intelligence engine for his OrgOS
team + Cherif Medawar's acquisitions — NOT a commercial SaaS sold to strangers.

## The verdict we are building around

V1/V2 built **breadth** — 45 tools that *process* deals (search, calc, draft, checklist).
Processing is table stakes; it is not an edge. The edge is three things you cannot buy off a
shelf:

1. **TRUTH** — reconstruct what a deal *actually* is from the real documents (leases, T12,
   rent roll), not a score off a listing. Kills the "screening presented as underwriting"
   trap — the exact thing that gets a theory-only investor killed on deal one.
2. **CONTROL** — *manufacture* an off-market opportunity (Cherif's signature: control the
   property before you buy it, create value through the lease), not rank everyone's inventory.
3. **MEMORY** — a private deal graph that compounds every offer, rejection, and outcome into
   judgment (and finally calibrates the score).

Everything else is supporting infrastructure. **Stop expanding horizontally. Go deep on these
three.**

## What we DELIBERATELY drop from the teardown (commercial-product noise for us)

- Data-licensing/scraping-ToS "not shippable" matrix — matters only if reselling data. Internal
  tool → free-first is fine. (Still: don't expose the server publicly.)
- Multi-tenant security (OAuth, org isolation, data-broker law, TCPA/CAN-SPAM) — SaaS-for-
  strangers concerns. Not our use case yet. **KEEP the one internal-relevant piece:**
  prompt-injection defense, because an uploaded/scraped OM is hostile input.

## Verified facts (live, this session — prove-don't-guess)

- **Nearby-brand data:** OSM Overpass, FREE, no key. Live proof: 40 branded POIs within 400m of
  30.2672,-97.7431 (Starbucks/Chipotle/Chase/Subway/Sweetgreen…). Needs a User-Agent header +
  retry across mirrors (overpass-api.de, lz4.overpass-api.de, overpass.private.coffee) + hard
  caching; public instance intermittently 504s under load. Query: `nwr(around:R,lat,lon)["brand"];`
  returns `brand`/`name` + category (`shop`/`amenity`/`cuisine`).
- **Doc-parsing stack:** pdfplumber / pypdf / openpyxl / pandas are NOT installed in the venv →
  add as deps in Phase 25. Network reaches gov + OSM fine (not Akamai listing sites).

---

## The phases (each independently shippable + tested; free-first preserved)

### PHASE 25 — Document Truth Engine I: ingestion + extraction
Add parsing deps (pdfplumber, pypdf, openpyxl). New `src/cre_mcp/truth/` package:
`models.py` (`ExtractedFigure{value, label, source_doc, page_or_cell, method, confidence,
raw_text}`), `parsers/{pdf,xlsx,csv}.py`, `extract.py`, `guard.py` (injection defense: doc
text is DATA-ONLY, never triggers tools; strip/flag instruction-like content). Ingest OM /
rent roll / T12 from an **uploaded path** first; **scraped path** reuses `http/fetch.py` to
pull listing-attached PDFs (both, per Max). Persist to DealStore (new `documents`/`figures`
tables). Tools: `ingest_document`, `list_deal_documents`.

### PHASE 26 — Document Truth Engine II: reconciliation + NOI bridge
`reconcile.py` with the source hierarchy (executed lease+amendments > estoppel > bank/
accounting > rent roll > T12 > seller rep > OM > listing) and conflict detection (OM rent ≠
lease rent; non-recurring income in "NOI"; missing mgmt/reserves/tax-reassessment/insurance;
brand-vs-guarantor mismatch; SF differs across lease/assessor/survey). **Never silently
average conflicting facts.** `noi_bridge.py`: seller NOI → verified → stabilized → lender →
buyer-underwritten, every line sourced. Fatal-flaw + missing-document report. Tools:
`reconcile_deal_docs`, `build_noi_bridge`, `deal_truth_report`.

### PHASE 27 — Nearby-Brand / Co-tenancy Engine  (Max's requested feature)
`enrichment/nearby.py`: OSM Overpass through FetchClient (UA + mirror retry + cache). Classify
each POI as **complementary anchor** (traffic-driver: coffee, grocery, big-box, pharmacy) vs
**competitor** (same category) vs neutral, with distance. Feeds a co-tenancy scoring signal +
the tenant-pitch generator ("Starbucks + Chase within 400m"). Tools: `nearby_brands`,
`trade_area_anchors`.

### PHASE 28 — Control Engine  (the dealmaking wedge — Cherif's move)
`src/cre_mcp/control/`: `tenants.py` (curated catalog of ~25-30 national tenants + published/
known site criteria as free first-party data), `site_fit.py` (match a property to tenant
criteria using existing traffic AADT + demographics + parcel + nearby-anchors), `vacant.py`
(vacant/underused standalone detection from listing status/DOM + OSM `disused=`/`vacant=` +
tenant-closure triggers), `spread.py` (lease-creation spread: value_vacant vs value_leased −
TI − LC − carry − vacancy period − execution-risk haircut → net spread + return-on-control),
`structures.py` (option / master-lease / seller-finance / extended-close / assignment, each
with nonrefundable exposure + seller-problem-solved + execution-probability). Tools:
`find_control_opportunities`, `match_tenants_to_site`, `evaluate_tenant_site_fit`,
`model_lease_creation_spread`, `recommend_control_structure`, `build_tenant_pitch`.

### PHASE 29 — Motivation Graph (off-market signals)
Extend `sources/distressed/` + new `graph/` sketch. `MotivationSignal{owner/property,
trigger_type, evidence(source+date+url), severity, freshness}` → engagement-probability +
inferred seller priorities (certainty/speed/tax-timing/debt-release/confidentiality), missing-
data-aware, honestly labeled. Free county tax-delinquency/lien/foreclosure/probate/UCC where
reachable; **honest gaps** where only paid exists (CMBS special-servicing = paid). Tools:
`find_motivated_owners`, `owner_motivation`, `record_trigger_event`. NOT a static distress score.

### PHASE 30 — Deal Graph / Memory + Shadow-IC + buyer-specific Decision Engine
Deal Graph (entities/events/outcomes) persisted in DealStore. Shadow-IC capture: system
decision recorded BEFORE the expert's, then expert decision, then realized outcome → feeds the
existing calibration harness. Buyer profile + **Decision Engine**: replace static score-as-
truth with a buyer-specific **decision frontier** (structure × price × cash × expected return ×
downside × acceptance-prob × close-prob). Medawar Score stays as an *explanatory summary*
behind verified/unverified facts + fatal flaws. Tools: `set_buyer_profile`, `decision_frontier`,
`record_ic_decision`, `deal_graph_query`.

### PHASE 31 — Honesty & positioning hardening
Reword outputs per the teardown: "screen in seconds; build verified underwriting as docs
arrive"; rents → "market direction + range, verify with lease comps"; rates → "benchmark +
preliminary sizing, then executable quotes." A score must never hide a fatal flaw, unverified
source, buyer-mismatch, or low financing/execution probability. Enforce the source hierarchy on
conflicts (no silent averaging). Surface an **assumption sheet** before any decision. Encode an
**authority matrix** (research / calculate / draft / recommend / send-after-approval / never-
commit — never autonomous wires or sends). Remove the "become a king without the reps" promise.

---

## Honest north star (what this can and cannot do)

It CAN let a theory-first investor run a disciplined, evidence-backed, source-linked
acquisition process, catch fatal flaws before the deposit, manufacture off-market opportunities,
and bring experts a complete file. It CANNOT supply liquidity, guaranty capacity, reputation,
relationships, field judgment, or scars. We build the honest version and say so in the product.

## Build model
Fable directs + integrates + verifies (runs pytest, reads committed code — same machine).
Codex (gpt-5.6-sol xhigh) via Tandem builds the heavy modules; Fable builds/patches directly
where faster. Every phase verified LIVE, not just against fixtures. Branch `feature/cre-engine`.
