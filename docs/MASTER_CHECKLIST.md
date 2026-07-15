# MedawarCRE — MASTER CHECKLIST (Total-Coverage Program)

**Mandate (Max, 2026-07-14):** build ALL of it — GPT-5.6 Pro's 240-job universe plus the
verified findings in `docs/COVERAGE_MAP.md`. Internal tool for Max + Cherif Medawar.
Where a job needs ledgers/backends we don't have, **MedawarCRE becomes the system of
record** (its own rent ledger, CAM ledger, bank-import, obligation graph) — the MCP is the
front door to a whole internal backend. North star: the machine that lets a theory-first
investor operate like a 20-year expert.

**Status legend:** ✅ shipped & live-verified · 🔶 partial (primitive exists, workflow doesn't)
· ⬜ to build · 🔨 in build (wave dispatched)

**Verified coverage before this program: 30 ✅ / 47 🔶 / 163 ⬜** (definitive per-row count;
corrects the earlier 29/46/165 headline — see COVERAGE_MAP.md changelog).

**Build model:** Fable directs + integrates + verifies (runs the suite, reads real diffs; sole
approval authority). Codex (gpt-5.6-sol xhigh) sessions via Tandem on mini = builders, each
owning a DISJOINT new package: creates only its own files, NO git, NO pip, NO shared-file
edits, runs only its own tests. Fable wires `register_all` + deps + git + full-suite at
integration. Every wave verified LIVE (or against a REAL captured document), then committed
on `feature/cre-engine`.

---

## Already shipped (do not rebuild)

**Wave 1 SHIPPED 2026-07-14** (093f6f6..aebb6a7): ledger 6 · scenarios 4 · leases 3 · taxecon 3 · command 5 · notes 4 · debt 4 — 74 → 103 tools.
**Wave 2 SHIPPED 2026-07-14** (4c386d5..16c52e2): accountability (assign_deal/unassigned_deals) · obligations 4 (collisions, consent DEAL-KILLER screen, estoppels) · dataroom 6 (completeness index, critical path, closing runway) · recoveries + option econ 2 — **74 → 117 tools, 803 tests.** LoopNet 60s-hang fixed (0bf591d, live-proven 25 listings x2 @8.8s). Wave 3 SHIPPED (f2630b9..a882c3b): zoning (live CBD-DDB400 proof + Houston branch) · envscreen (61 live ship-channel hits) · verifyreg (live FINRA CRD 361) · books (system of record, penny-exact) · negotiation (drift catches dropped contingencies) — **74 → 138 tools, 924 tests.** Waves 4-6 SHIPPED (c45a94b..62aed8b): disposition · physical · leasing · fund · closing · mlops · valuation · siteintel · title · construction · assetmgmt · compliance · relations — **74 → 235 tools, 1208 tests.** W7 mop-up in build: leaseops (123/129/130/62/70), prospect (23/24/26/27/33/35). Genuinely blocked-on-Max/reality: 206 (PACER paid), 4-full (email integration creds), 89 (utility-capacity relationships), 84-85 (municipal precedent corpus), 29-full (call-report parsing deferred).

### The original 74

listing (3): search_properties · get_property_details · get_market_overview
market (4): market_intel · compare_markets · get_rent_comparables · get_comps
deal (3): analyze_deal · find_deals · find_distressed
owner (1): owner_lookup
execution (12): recommend_offer · generate_loi · find_contact · draft_outreach ·
handle_counter · financing_options · qualify_me · size_debt · due_diligence_plan ·
closing_plan · save_deal · list_deals
pipeline (6): add_to_pipeline · update_deal_stage · list_pipeline · save_search ·
list_searches · check_alerts
structure (5): recommend_structure · start_exchange · exchange_status ·
identify_replacement · calc_boot_basis
capital (7): add_investor · list_investors · record_commitment · check_solicitation ·
model_waterfall · draft_ppm · draft_form_d
ops (2): after_tax_returns · operating_playbook
eval (2): backtest_score · record_deal_outcome
truth (5): ingest_document · list_deal_documents · reconcile_deal_docs · build_noi_bridge ·
deal_truth_report
nearby (2): nearby_brands · trade_area_anchors
control (6): find_control_opportunities · match_tenants_to_site · evaluate_tenant_site_fit ·
model_lease_creation_spread · recommend_control_structure · build_tenant_pitch
motivation (3): owner_motivation · record_trigger_event · find_motivated_owners
memory (4): record_ic_decision · log_deal_event · deal_timeline · ic_scorecard
decision (2): set_buyer_profile · decision_frontier
about (2): capabilities · deal_assumptions
arbitrage (5): analyze_master_lease · find_arbitrage_opportunities ·
draft_master_lease_proposal · draft_subtenant_outreach · master_lease_playbook

---

## Wave plan (14 waves to total coverage)

| Wave | Theme | New package(s) | Jobs |
|------|-------|----------------|------|
| **W1** | Wedge + table-stakes: lease abstraction, stress engine, tax econ, recording ledger | `leases/` `scenarios/` `taxecon/` `ledger/` | 121 122 124 · 46 47↑ 48 49 50 · 51 111 227 · 3-substrate 18↑ 155-substrate 190-substrate |
| **W2** | Obligation graph II: recoveries, collisions, consent, estoppels, notices | `leases/` ext + `obligations/` | 62↑ 70↑ 75 123 125 126 127 128 129 130 214 |
| **W3** | Daily command center | `command/` | 1 2 3 5 6 7 9↑ 13 14 19 20 182 184 |
| **W4** | Internal ops backend (system of record): rent/tenant/CAM ledgers, bank import | `bookkeeping/` | 8 63 64 65 66 67 68 141 142 143 144 145 146 147 148 149 150 |
| **W5** | Debt & lender execution | `debt/` | 16↑ 17 53 152 153 154 155 156 157 158 159 160 |
| **W6** | Title, legal & survey | `title/` | 71 72 73 74 76 77 78 79 80 |
| **W7** | Physical, environmental, insurance, property tax, compliance | `physical/` `insurance/` | 101–110 112 113 114 115 116 117 118 119 120 |
| **W8** | Negotiation & closing depth | `negotiation/` ext | 173↑ 174↑ 175 176 177 179 180 183 185 186 187↑ 189 190 |
| **W9** | Asset management & disposition | `assetmgmt/` `disposition/` | 191 192 193 194 195 196 197↑ 198 199 221 222 223 224↑ 225 226↑ 228 229↑ |
| **W10** | Distressed, notes & wholesale | `notes/` | 201–210 |
| **W11** | Master-lease completion + retail/leasing depth | `arbitrage/` ext + `leasing/` | 25↑ 134 135 136 137↑ 138 139 140 213↑ 216 217 218 219 220 |
| **W12** | Capital/IR/LP + relationship & counterparty intelligence | `relationships/` `fund/` | 4 161↑ 163 165↑ 166 167 168 169 170 231↑ 232 233↑ 234 235 236 237 238 239 240 |
| **W13** | Market & site intelligence depth + zoning/entitlements | `siteintel/` `zoning/` | 12 23 24 26 27 28 29↑ 32 33 34↑ 35 36 37 38 39 40↑ 81–90 |
| **W14** | Development/construction + advanced valuation | `development/` `valuation/` | 91–100 52 54 55 56 57 58 59 60 |

↑ = completing an existing Partial. Waves are dependency-ordered: the obligation graph (W1-2)
feeds the command center (W3); the internal ledgers (W4) feed AM/disposition (W9); the W1
recording ledger accrues the outcome history that makes W12's scoring honest instead of fake.

---

## The 240 (per-job status)

### 1 · Daily command center
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 1 | Morning action queue ranked by $ impact, urgency, close prob | M | W3 | ✅ |
| 2 | Overnight change brief (listings, bids, docs, signals, deadlines) | M | W3 | ✅ |
| 3 | Flag deals with no owner, next action, or due date | M | W1→W3 | ✅ |
| 4 | Convert meeting/email/call commitments into tasks + deadlines | M | W12 | 🔶 |
| 5 | Counterparty briefing before a call | P | W3 | ✅ |
| 6 | Surface unanswered messages likely to stall a deal | M | W3 | 🔶 |
| 7 | Rank opportunities by expected value of the next hour | M | W3 | ✅ |
| 8 | Forecast 30/60/90-day cash requirements | M | W4 | ⬜ |
| 9 | Detect assumption drift across underwriting/IC/loan/investor docs | P | W3 | 🔶 |
| 10 | Record expert overrides + realized outcomes → calibration | C | — | ✅ |

### 2 · On-market sourcing
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 11 | Find LoopNet/Crexi listings matching a precise buy box | C | — | ✅ |
| 12 | Dedupe same property across brokers/portals w/ price history | P | W13 | ✅ |
| 13 | Alert on price, status, OM, broker, DOM changes | P | W3 | ✅ |
| 14 | Detect stale listings open to structure/speed/discount | M | W3 | ✅ |
| 15 | Rank new listings by fit, hidden upside, data confidence | C | — | ✅ |
| 16 | Compare ask vs debt-constrained value | P | W5 | 🔶 |
| 17 | Identify assumable/favorable existing financing | M | W5 | ⬜ |
| 18 | Extract broker claims from OM, mark verified/contradicted | P | W1 | 🔶 |
| 19 | Daily coverage report: searched/screened/rejected/untouched | M | W3 | ✅ |
| 20 | Route new listings by mandate, geography, capacity | M | W3 | 🔶 |

### 3 · Off-market & event sourcing
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 21 | Find off-market owners/parcels matching a thesis | C | — | ✅ |
| 22 | Rank owner motivation from trigger events | C | — | ✅ |
| 23 | Identify adjacent parcels for assemblage | M | W13 | ✅ |
| 24 | Find owner-occupied assets for sale-leaseback | M | W13 | ✅ |
| 25 | Identify dark stores / corporate closures | P | W11 | 🔶 |
| 26 | Find stalled entitled projects | M | W13 | ✅ |
| 27 | Find portfolio owners likely to sell a package | P | W13 | ✅ |
| 28 | Monitor permits/CO/demolition/planning filings | M | W13 | 🔶 |
| 29 | Find banks/servicers with OREO or criticized CRE exposure | P | W13 | 🔶 |
| 30 | Owner-specific outreach from identity + pain point | C | — | ✅ |

### 4 · Market & site intelligence
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 31 | Compare markets on Census/BLS/FRED/HUD/BEA | C | — | ✅ |
| 32 | Quantify inventory, pipeline, absorption, vacancy | P | W13 | ✅ |
| 33 | Achievable rent w/ size/condition/frontage adjustments | P | W13 | ✅ |
| 34 | Drive-time / trade-area demographics | P | W13 | 🔶 |
| 35 | Frontage, visibility, access, curb cuts, signals | M | W13 | 🔶 |
| 36 | Retail leakage / surplus / category demand | M | W13 | 🔶 |
| 37 | Track employers: openings, layoffs, relocations | M | W13 | 🔶 |
| 38 | Growth forecasts w/ confidence bands | M | W13 | ⬜ |
| 39 | Compare regulatory burden (rent control, eviction, …) | M | W13 | ⬜ |
| 40 | Market-entry memo: facts vs estimates vs questions | P | W13 | 🔶 |

### 5 · Core underwriting
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 41 | Cap rate, DSCR, CoC, IRR, equity multiple | C | — | ✅ |
| 42 | After-tax returns | C | — | ✅ |
| 43 | Medawar Deal Score w/ calibration warning | C | — | ✅ |
| 44 | Max offer price from returns + financing | C | — | ✅ |
| 45 | Buyer-specific decision frontier | C | — | ✅ |
| 46 | Stress test occupancy/rent/expense/rates/exit | **M** (GPT said P) | W1 | ✅ |
| 47 | Break-even occupancy, rent, NOI, exit price | P | W1 | ✅ |
| 48 | Model monthly lease-up, downtime, stabilization | M | W1 | ✅ |
| 49 | Base/downside/severe/lender cases from one model | P | W1 | ✅ |
| 50 | Explain the 3 assumptions driving the return | P | W1 | ✅ |

### 6 · Advanced valuation & tax economics
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 51 | Sale-triggered property-tax reassessment → NOI hit | M | W1 | ✅ |
| 52 | Insurance repricing, deductibles, BI gaps | M | W14 | ✅ |
| 53 | Value assumable below-market debt separately | M | W5 | ✅ |
| 54 | TI, LC, free rent, downtime, renewal prob by suite | M | W14 | ✅ |
| 55 | Cost seg, depreciation, passive-loss, recapture (CPA signoff) | M | W14 | ⬜ |
| 56 | Value fee/leasehold/ground-lease/air-rights separately | M | W14 | ✅ |
| 57 | Reconcile income/sales/cost approaches | M | W14 | ✅ |
| 58 | Forced-sale / liquidation value | M | W14 | ✅ |
| 59 | Incentive expiration + clawback modeling | M | W14 | ✅ |
| 60 | Risk-adjusted residual value (entitlement/construction) | M | W14 | ✅ |

### 7 · Document truth & accounting
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 61 | Ingest OM/rent roll/T12/leases → verified NOI | C | — | ✅ |
| 62 | Trace every input to exact page/row/cell | P | W2 | ✅ |
| 63 | Detect hidden rows, hardcodes, circular formulas | M | W4 | ⬜ |
| 64 | Rebuild T12 from GL, deposits, tenant ledgers | M | W4 | 🔶 |
| 65 | Reconcile scheduled rent → billed → cash → bad debt | M | W4 | ✅ |
| 66 | Normalize one-time/related-party/capitalized expenses | P | W4 | 🔶 |
| 67 | Detect deferred maintenance buried in repairs | M | W4 | ⬜ |
| 68 | Validate deposits, prepaid, receivables, payables | M | W4 | ⬜ |
| 69 | Seller→verified→lender NOI bridge + verdict | C | — | ✅ |
| 70 | Diligence request list ranked by valuation impact | P | W2 | ✅ |

### 8 · Title, legal & survey
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 71 | Parse title commitment → exceptions, cures, deadlines | M | W6 | ✅ |
| 72 | Liens, judgments, UCC, taxes blocking closing | P | W6 | ✅ |
| 73 | Deed/legal-description/title/survey/parcel conflicts | M | W6 | ✅ |
| 74 | Easements, REAs, use restrictions affecting value | M | W6 | ✅ |
| 75 | Abstract CC&Rs, exclusives, prohibited uses, co-tenancy | M | W2 | ✅ |
| 76 | ALTA survey vs title vs site plan | M | W6 | ✅ |
| 77 | Encroachments, setbacks, missing access | M | W6 | ✅ |
| 78 | Entity good standing, authority, AML/sanctions | P | W6 | 🔶 |
| 79 | Litigation/bankruptcy/dispute risk summary | P | W6 | 🔶 |
| 80 | Attorney issue list (no legal conclusions) | M | W6 | ✅ |

### 9 · Zoning & entitlements
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 81 | Current zoning, overlays, permitted uses, nonconforming | M | W13 | 🔶 |
| 82 | By-right vs conditional vs variance vs rezone | M | W13 | ⬜ |
| 83 | Max FAR, density, height, coverage, setbacks, parking | M | W13 | ⬜ |
| 84 | Nearby approval/denial precedents | M | W13 | 🔶 |
| 85 | Entitlement path, milestones, appeal risk, timeline | M | W13 | 🔶 |
| 86 | Parse staff reports/conditions → cost & schedule | M | W13 | 🔶 |
| 87 | Impact fees, exactions, inclusionary, permit fees | M | W13 | 🔶 |
| 88 | Subdivision, lot-line, assemblage, TDR, air rights | M | W13 | 🔶 |
| 89 | Utility capacity, allocations, moratoria | M | W13 | ⬜ |
| 90 | Entitlement-risk-adjusted land residual | M | W13 | ✅ |

### 10 · Development & construction
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 91 | Development budget from program + local costs | M | W14 | ✅ |
| 92 | Compare A/E/GC/consultant proposals | M | W14 | ✅ |
| 93 | Level trade bids, detect scope gaps | M | W14 | ✅ |
| 94 | Reconcile GMP to drawings/specs | M | W14 | ✅ |
| 95 | Forecast draws, interest reserve, cost-to-complete | M | W14 | ✅ |
| 96 | Audit pay apps vs progress, lien waivers, COs | M | W14 | ✅ |
| 97 | Track RFIs, submittals, lead times, critical path | M | W14 | ✅ |
| 98 | Model VE choices vs leasing/NOI/exit | M | W14 | ✅ |
| 99 | Verify percent complete from evidence | M | W14 | ✅ |
| 100 | Closeout docs/warranties/as-builts → operating system | M | W14 | ✅ |

### 11 · Physical & environmental diligence
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 101 | Inspection findings → yr-1/5/10 CapEx | M | W7 | ✅ |
| 102 | Remaining useful life per system | M | W7 | ✅ |
| 103 | Vintage/construction-type risk screen | M | W7 | ✅ |
| 104 | Detect unpermitted work | M | W7 | ✅ |
| 105 | ADA / fire-life-safety / code exposure | M | W7 | ✅ |
| 106 | Environmental database + site-history screen | M | W7 | ✅ |
| 107 | Phase II scope + remediation scenarios | M | W7 | ✅ |
| 108 | Asbestos/lead/mold/radon/UST screen | M | W7 | 🔶 |
| 109 | Flood/wildfire/wind/quake exposure → BI | M | W7 | 🔶 |
| 110 | Physical-risk register (facts vs estimates vs opinions) | M | W7 | ✅ |

### 12 · Tax, insurance, utilities & compliance
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 111 | Audit assessor record for errors/overvaluation | M | W1 | ✅ |
| 112 | Property-tax appeal package + deadlines | M | W7 | ✅ |
| 113 | Compare insurance quotes (limits, exclusions, carriers) | M | W7 | 🔶 |
| 114 | Detect coinsurance/ordinance/flood/BI coverage gaps | M | W7 | 🔶 |
| 115 | Track carrier appetite, renewals, nonrenewal risk | M | W7 | ✅ |
| 116 | Utility bill/tariff/demand-charge anomalies | M | W7 | ✅ |
| 117 | Underwrite solar/storage/EV/efficiency projects | M | W7 | 🔶 |
| 118 | Energy benchmarking/emissions obligations | M | W7 | ✅ |
| 119 | Retrofit cost / fines from performance standards | M | W7 | 🔶 |
| 120 | Compliance calendar (taxes, licenses, inspections, filings) | M | W7 | ✅ |

### 13 · Lease abstraction & administration  ← THE WEDGE
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 121 | Abstract every lease/amendment/guaranty to standard fields | P | W1 | ✅ |
| 122 | Critical-date calendar: options, notices, expirations, steps | M | W1 | ✅ |
| 123 | Reconcile lease vs amendments vs ledger vs rent roll | M | W2 | ✅ |
| 124 | Contractual rent schedules (CPI, %, caps, partial periods) | M | W1 | ✅ |
| 125 | Abstract CAM/tax/insurance recovery language | M | W2 | ✅ |
| 126 | Estoppels + SNDAs: track, compare, surface exceptions | M | W2 | ✅ |
| 127 | Detect exclusives, radius, co-tenancy, go-dark, ROFR/ROFO | M | W2 | ✅ |
| 128 | Price renewal/termination/expansion options vs market | M | W2 | ✅ |
| 129 | Track COIs, guaranties, security, LCs, default notices | M | W2 | ✅ |
| 130 | Obligation-specific notices routed to counsel | M | W2 | ✅ |

### 14 · Leasing, tenant rep & retail
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 131 | Match national-tenant criteria to vacant space | C | — | ✅ |
| 132 | Lease-creation spread + control economics | C | — | ✅ |
| 133 | Nearby-brand co-tenancy / cannibalization | C | — | ✅ |
| 134 | Tenant prospect list from whitespace + expansion signals | P | W11 | ✅ |
| 135 | Find CRE decision makers, franchisees, operators | M | W11 | ⬜ |
| 136 | Tenant sales capacity, OCR, breakpoint, sustainable rent | M | W11 | ✅ |
| 137 | Landlord/tenant site package, claims tied to evidence | P | W11 | 🔶 |
| 138 | Compare lease proposals on NPV/flex/credit/risk | M | W11 | ✅ |
| 139 | Permit→TI→open→rent-commencement critical path | M | W11 | ✅ |
| 140 | Monitor tenant credit, sales, closures, renewal prob | M | W11 | 🔶 |

### 15 · Property management (internal backend)
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 141 | Audit monthly rent billing vs lease terms | M | W4 | ✅ |
| 142 | CAM reconciliations + true-ups w/ audit backup | M | W4 | 🔶 |
| 143 | Delinquency patterns → collection/notice/escalation | M | W4 | 🔶 |
| 144 | Triage work orders (life safety, SLA, repeats, cost) | M | W4 | ⬜ |
| 145 | Preventive maintenance scheduling | M | W4 | ⬜ |
| 146 | Vendor pricing/quality/compliance comparison | M | W4 | ⬜ |
| 147 | Weekly cash collections/payables/reserves forecast | M | W4 | 🔶 |
| 148 | Monthly owner variance narrative | M | W4 | 🔶 |
| 149 | Recurring repairs → replace or root-cause | M | W4 | ⬜ |
| 150 | Coordinate unit/suite turns | M | W4 | ⬜ |

### 16 · Debt & lender execution
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 151 | Screen financing options + size debt | C | — | ✅ |
| 152 | Lender-ready package w/ source-traced underwriting | P | W5 | 🔶 |
| 153 | Match deal to lenders by live appetite | M | W5 | ⬜ |
| 154 | Compare term sheets (cost, recourse, covenants, prepay) | M | W5 | ✅ |
| 155 | Score lender execution: quote-to-close, retrades | M | W1-ledger→W5 | 🔶 |
| 156 | Rate caps, swaps, extensions, hedge renewal | M | W5 | ⬜ |
| 157 | Forecast covenant compliance, cash traps, triggers | M | W5 | ✅ |
| 158 | Assumption vs refi vs supplemental vs sale | M | W5 | ✅ |
| 159 | Waiver/extension/modification request prep | M | W5 | ⬜ |
| 160 | Track lender reporting obligations + draws | M | W5 | ⬜ |

### 17 · Capital formation, fund & IR
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 161 | Design stack: senior/mezz/pref/common/seller/earnout | P | W12 | 🔶 |
| 162 | Waterfall distributions + promote | C | — | ✅ |
| 163 | Compare JV structures (economics, control, downside) | M | W12 | ✅ |
| 164 | 506(b)/(c) gates + PPM/Form D drafts | C | — | ✅ |
| 165 | Track accreditation, KYC, subscriptions, side letters | P | W12 | 🔶 |
| 166 | Forecast capital calls, distributions, GP co-invest | M | W12 | ✅ |
| 167 | NAV, fees, realized/unrealized, attribution | M | W12 | ✅ |
| 168 | Monitor fund mandate/concentration/side-letter limits | M | W12 | ✅ |
| 169 | Quarterly investor reports from governed source data | M | W12 | ✅ |
| 170 | Investor engagement + re-up scoring | M | W12 | ✅ |

### 18 · Negotiation, LOI & structure
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 171 | Offer range + acquisition LOI | C | — | ✅ |
| 172 | Counter response + concession package | C | — | ✅ |
| 173 | Real-time price/structure/cash/timing tradeoffs | P | W8 | 🔶 |
| 174 | Infer counterparty priorities from conduct | P | W8 | 🔶 |
| 175 | Negotiation plan: anchor, sequencing, walk-away | M | W8 | ✅ |
| 176 | Term drift LOI→PSA/lease/loan/JV | M | W8 | ✅ |
| 177 | Verbal promises → document changes + follow-ups | M | W8 | ✅ |
| 178 | Recommend control structure | C | — | ✅ |
| 179 | Value each concession to both sides | M | W8 | ✅ |
| 180 | Approval log: who accepted nonstandard terms, why | M | W8 | ✅ |

### 19 · Due diligence & closing
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 181 | DD + closing plans tailored to the deal | C | — | ✅ |
| 182 | Data-room completeness index, assigned gaps | P | W3 | ✅ |
| 183 | Extract reps, covenants, CPs, post-closing obligations | M | W8 | ✅ |
| 184 | Track title/survey/financing/estoppel/consent deadlines | P | W3 | ✅ |
| 185 | Reconcile settlement-statement prorations | M | W8 | ✅ |
| 186 | Verify sources/uses, payoffs, wires (call-back controls) | M | W8 | ✅ |
| 187 | Track third-party reports, reliance, lender conditions | P | W8 | 🔶 |
| 188 | Verify buyer qualification, proof of funds, close prob | C | — | ✅ |
| 189 | Closing-day command center + post-closing calendar | M | W8 | ✅ |
| 190 | Failed-deal postmortem → screening changes | P | W8 | ✅ |

### 20 · Asset management & repositioning
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 191 | Annual business plan w/ owners, costs, milestones | P | W9 | ✅ |
| 192 | Rank initiatives by NPV, risk, time, bandwidth | M | W9 | ✅ |
| 193 | NOI forecast by tenant/unit + variance drivers | M | W9 | ✅ |
| 194 | Prioritize CapEx (safety, retention, return, saleability) | M | W9 | ✅ |
| 195 | Forecast-vs-actual for every initiative | M | W9 | ✅ |
| 196 | Detect underperforming assets/managers/vendors | M | W9 | ✅ |
| 197 | Hold / sell / refi / recap / invest-more | P | W9 | 🔶 |
| 198 | Marginal return on next dollar + month | M | W9 | ✅ |
| 199 | Portfolio watchlist: rollover, maturity, tax, credit | M | W9 | ✅ |
| 200 | Realized outcome vs thesis vs system verdict | C | — | ✅ |

### 21 · Distressed, notes & wholesale
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 201 | Price a note (collateral, liens, timeline, recovery) | M | W10 | ✅ |
| 202 | Reconcile note/mortgage/assignments/allonges chain | M | W10 | ⬜ |
| 203 | Lien priority + recovery waterfall | M | W10 | ✅ |
| 204 | Cure/mod/forbear/foreclose/DIL/sale/REO comparison | M | W10 | ✅ |
| 205 | Foreclosure/redemption/BK/eviction timelines by state | M | W10 | ✅ |
| 206 | Track bankruptcy dockets, stays, sale events | M | W10 | ⬜ |
| 207 | Guarantor collectibility + settlement leverage | M | W10 | ⬜ |
| 208 | Assignment / double-close spread underwriting | P | W10 | 🔶 |
| 209 | Cash-buyer list from proven acquisitions | M | W10 | 🔶 |
| 210 | Tax-sale redemption/quiet-title/possession risks | P | W10 | 🔶 |

### 22 · Master lease & control
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 211 | Master-lease P&L w/ negative carry + default exposure | C | — | ✅ |
| 212 | Owner + subtenant terms + one-call playbook | C | — | ✅ |
| 213 | Compare ML/mgmt/option/sandwich/seller-fi/purchase | P | W11 | 🔶 |
| 214 | Verify assignability, lender consent, due-on-sale | M | **W2** | ✅ ← fatal-flaw gap in shipped product |
| 215 | Match vacant space to subtenants + sequence outreach | C | — | ✅ |
| 216 | Track rent owed/received, deposits, reserves | M | W11 | ✅ |
| 217 | Model termination, casualty, co-tenancy, owner default | M | W11 | ✅ |
| 218 | Price option strike, extensions, control premium | M | W11 | ✅ |
| 219 | Detect subtenant breaches before owner default | M | W11 | ✅ |
| 220 | Package + value sale of a control position | M | W11 | ✅ |

### 23 · Disposition & 1031 recycling
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 221 | Disposition-readiness audit 6-12 mo before sale | M | W9 | ✅ |
| 222 | Buyer universe by strategy, check size, behavior | M | W9 | ✅ |
| 223 | Select/score brokers on comps, reach, accuracy | M | W9 | 🔶 |
| 224 | Evidence-backed OM + governed buyer Q&A | P | W9 | 🔶 |
| 225 | Pricing, bid rounds, access, best-and-final rules | M | W9 | ✅ |
| 226 | Normalize bids for certainty-adjusted proceeds | P | W9 | ✅ |
| 227 | Net sale proceeds after debt, prepay, taxes, fees | P | W1 | ✅ |
| 228 | Direct/brokered/auction/recap/UPREIT/DST comparison | M | W9 | ✅ |
| 229 | Replacement properties matching 1031 constraints | P | W9 | 🔶 |
| 230 | 45/180 clocks, ID rules, backups, sequence | C | — | ✅ |

### 24 · LP, appraisal & relationship intelligence
| # | Job | Grade | Wave | St |
|---|-----|-------|------|----|
| 231 | Independently re-underwrite a sponsor deal | P | W12 | 🔶 |
| 232 | Sponsor track record: realized vs projected | M | W12 | 🔶 |
| 233 | PPM/JV/OA economics + counsel flags | P | W12 | 🔶 |
| 234 | LP portfolio exposure look-through | M | W12 | ⬜ |
| 235 | Challenge an appraisal (comps, adjustments, cap) | M | W12 | ✅ |
| 236 | Reconsideration-of-value package | M | W12 | ✅ |
| 237 | Broker credibility from accuracy/retrades/closes | M | W1-ledger→W12 | 🔶 |
| 238 | Counterparty dossiers from permissioned history | M | W12 | ✅ |
| 239 | Recommend the best human to call now | M | W12 | ✅ |
| 240 | Verify licenses, registrations, disciplinary history | M | W12 | ✅ |

---

## Verification bar (every wave, before commit)
1. Full suite green (`pytest tests/ -q`) — no wave merges on its own tests alone.
2. LIVE or REAL-DOCUMENT proof, captured in the commit message (no mocked proof).
   Lease work proves against real executed leases (SEC EDGAR EX-10 exhibits, captured to
   `tests/fixtures/leases/` with CAPTURE_NOTES).
3. Honesty layer holds: every estimate labeled, every source cited, fatal flaws never
   hidden, authority matrix respected (professional-review flags on jobs GPT marked so).
4. Fable reads the real diff; the builder never approves its own work.
