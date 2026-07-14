# MedawarCRE — Coverage Map (240 jobs-to-be-done vs the 74 shipped tools)

**Input:** GPT-5.6 Pro's 240-job CRE universe (24 categories × 10 jobs), 2026-07-14.
**Method:** GPT graded coverage from a *written description* of the 74 tools. This document
re-grades every job against the **actual code** on `feature/cre-engine` (74 tools, 617 tests).
Where my verified grade differs from GPT's, the row is marked **Δ** and the reason is given.

**Legend**
- `C` Covered — a shipped tool does the end job.
- `P` Partial — a real primitive exists; the complete auditable workflow does not.
- `M` Missing — nothing in the codebase does this.
- **Prove?** = can we verify a v1 LIVE today, per the project's hard rule (no mocked proof)?
  - `LIVE` — provable now with data we can reach (public/free/gov, portals, documents, our own DB).
  - `DOC` — provable as soon as Max supplies a real document (lease, T12, title, PCA, term sheet).
  - `BLOCKED` — needs data we do not have and cannot get today (general ledger, bank feeds,
    tenant ledgers, PM system, insurance loss runs, permissioned counterparty outcome history).
    Building these now = unverifiable software. Do not build blind.

**Verified tally:** 29 Covered · 46 Partial · 165 Missing.
(GPT said 30 / 42 / 168 — its grading was substantially accurate. The deltas below are the
places where it mattered.)

---

## The deltas that change the plan

| # | Job | GPT | Verified | Why it matters |
|---|-----|-----|----------|----------------|
| 46 | Stress test occupancy/rent/expense/rate/exit-cap | P | **M** | No scenario or sensitivity engine exists anywhere — only `break_even_occupancy` in `underwriting/metrics.py`. This is table-stakes and it is absent. GPT's "Partial" hid it. |
| 3 | Unowned / actionless deal detector | P | **M** | The `deals` table has a `stage` but **no owner, no next-action, no due-date, no SLA**. Nothing to detect against. Still a small build — it needs 3 columns first. |
| 34 | Drive-time / trade-area demographics | M | **P** | `trade_area_anchors` + `control/site_fit` already consume AADT + demographics + anchors. More is there than GPT knew. |
| 50 | Explain the 3 assumptions driving the return | M | **P** | `deal_assumptions` (Phase 31) already surfaces the assumption sheet. Needs sensitivity ranking on top — which is job 46. |
| 5 | Counterparty briefing before a call | M | **P** | `deal_timeline` + `find_contact` give deal history; the comms layer is what's missing. |
| 134 | Tenant prospect list from whitespace | M | **P** | The 30-tenant committed catalog + `match_tenants_to_site` exist; expansion/news signals don't. |
| 29 | Bank/servicer OREO exposure | M | **P** | `find_distressed` already pulls HUD REO live; call-report/criticized-exposure is the missing half. |
| 191 | Annual business plan | M | **P** | `operating_playbook` is a post-close runway — the skeleton of this job. |
| 227 | Net sale proceeds after debt/tax/fees | M | **P** | `after_tax_returns` + `calc_boot_basis` cover most of the math; the disposition wrapper is missing. |

**The single most important structural finding:** the Document Truth Engine extracts
**financial figures only** — `noi`, `opex`, `cap_rate`, `gpr`, `taxes`, `insurance`,
`reserves`, `vacancy_rate` (see `truth/extract.py`). It has **no clause layer**: no
commencement, expiration, option window, notice deadline, CPI/percentage rent, CAM/base-year,
exclusive, co-tenancy, go-dark, ROFR. Every one of categories 13 (lease admin), 8 (title/legal),
and most of 22 (control) is therefore genuinely greenfield. GPT is right that this is the wedge.

---

## Coverage by category

| Cat | Category | C | P | M | Note |
|-----|----------|---|---|---|------|
| 1 | Daily command center | 1 | 5 | 4 | Substrate exists (`dd_items`, `deal_events`, `ic_decisions`); no queue/brief layer. |
| 2 | On-market sourcing | 2 | 5 | 3 | Search + score covered; **change detection** and DOM history absent. |
| 3 | Off-market & event sourcing | 3 | 3 | 4 | Motivation graph is a real asset. |
| 4 | Market & site intelligence | 1 | 4 | 5 | **Micro-location (frontage/access/visibility) missing** — expert-separator #4. |
| 5 | Core underwriting | 5 | 3 | 2 | Strongest category. But **no stress engine** (job 46). |
| 6 | Advanced valuation & tax | 0 | 0 | 10 | Entirely absent. Tax reassessment (51) is the cheapest, highest-frequency win. |
| 7 | Document truth & accounting | 3 | 3 | 4 | Financial truth strong; **ledger/GL truth impossible today (BLOCKED)**. |
| 8 | Title, legal & survey | 0 | 3 | 7 | **Obligation collisions** — expert-separator #5. Greenfield. |
| 9 | Zoning & entitlements | 0 | 0 | 10 | No zoning module exists. Free municipal data → LIVE-provable. |
| 10 | Development & construction | 0 | 0 | 10 | Entirely absent. Different product; defer. |
| 11 | Physical & environmental | 0 | 1 | 9 | `due_diligence_plan` is the only touchpoint. |
| 12 | Tax, insurance, utilities, compliance | 0 | 0 | 10 | Compliance calendar (120) pairs with the obligation graph. |
| 13 | **Lease abstraction & administration** | 0 | 1 | 9 | **The wedge.** Only parsers + lineage exist. |
| 14 | Leasing, tenant rep & retail | 3 | 3 | 4 | Control engine already strong here. |
| 15 | Property management | 0 | 0 | 10 | **All BLOCKED** — needs GL, bank, tenant ledgers, a PM system, real tenants. |
| 16 | Debt & lender execution | 1 | 1 | 8 | Screening covered; **matching + execution scoring** are the moat, and need outcome history. |
| 17 | Capital formation & IR | 2 | 3 | 5 | Securities gates + waterfall covered. |
| 18 | Negotiation, LOI & structure | 4 | 3 | 3 | Strong. Term-drift detection (176) is a cheap, high-value add. |
| 19 | Due diligence & closing | 3 | 4 | 3 | `dd_items` deadlines already persist — dependency tracker is close. |
| 20 | Asset management & repositioning | 1 | 2 | 7 | Mostly BLOCKED (needs operating actuals). |
| 21 | Distressed, notes & wholesale | 0 | 2 | 8 | Sourcing covered; note pricing/legal timelines absent. |
| 22 | Master lease & control | 4 | 1 | 5 | Economics + outreach covered; **consent/assignability (214) is a fatal-flaw gap.** |
| 23 | Disposition & 1031 | 1 | 4 | 5 | 1031 clock covered; sell-side process absent. |
| 24 | LP, appraisal & relationship | 0 | 2 | 8 | **Relationship moat — requires the recording layer first.** |

---

## The buildability filter (this is the correction to GPT's plan)

GPT's Top-20 is strategically right about *where the moat is* and **wrong about what we can
prove**. Five of its top-20 — **#10 (job 65, rent-to-cash), #11 (141, lease-to-billing),
#12 (142, CAM reconciliation), #13 (148, owner variance narrative), #14 (157, covenant
forecast)** — all require data Max does not have and cannot obtain today:

- a **general ledger** and chart of accounts
- **bank feeds** / deposit records
- **tenant ledgers** and A/R aging
- a **property-management system** (Yardi/AppFolio/Entrata)
- **actual tenants paying actual rent**

We would be writing a CAM reconciliation engine with no CAM ledger to reconcile. Every test
would be a fixture we invented. That is precisely the "screening presented as underwriting"
failure this project exists to kill — applied to ourselves. **Those five stay BLOCKED until
Max owns/manages an asset or a PM client shares a real ledger.**

The moat jobs (153 lender matching, 155 lender execution scoring, 237 broker credibility,
238/239 dossiers) have a different blocker: they need **permissioned outcome history that only
accrues through use**. You cannot build the scorer before you have recorded the outcomes.
**But you can build the recorder today, cheaply.** That is the unlock.

---

## Recommended build order (verified, provable, and moat-accretive)

### TIER 0 — The Recording Layer (build first; it is the only path to the network moats)
Everything GPT names as the true moat ("broker claimed X, diligence proved Y"; "lender quoted
X, closed Y") is a **data-capture problem before it is a scoring problem**. Cheap now,
impossible to backfill later. Every day we don't record is a day of moat we never get.

- **T0.1 — Claim-vs-truth ledger.** Extend the truth engine: when `reconcile_deal_docs`
  overrides an OM/seller claim, persist `(counterparty, claim, proven_value, delta, deal)`.
  We already compute this and throw it away.
- **T0.2 — Quote-vs-close ledger.** Persist lender term sheets and what actually closed.
- **T0.3 — Defect→outcome ledger.** Persist which flagged defect caused a retrade / kill /
  loss. `record_deal_outcome` exists; it does not capture defect attribution.
- Feeds jobs 155, 190, 226, 232, 237, 238, 239 later — and calibrates the Deal Score, which is
  still honestly UNCALIBRATED.

### TIER 1 — The Obligation Graph (the wedge; DOC-provable with one real lease)
- **T1.1 — Lease abstraction (job 121)** — clause taxonomy on top of the existing parsers +
  lineage. Economic fields + legal fields, every one source-cited.
- **T1.2 — Critical-date engine (job 122)** — options, notices, expirations, rent steps,
  terminations → `dd_items`-style deadlines. This is what makes the tool open every morning.
- **T1.3 — Obligation collision detector (job 127 + expert-separator #5)** — exclusives,
  co-tenancy, go-dark, ROFR/ROFO, radius. The thing that separates a novice from an expert.
- **T1.4 — Consent/assignability screen (job 214)** — due-on-sale, lender consent, subletting.
  **A live fatal-flaw gap in the master-lease product we already shipped.**

### TIER 2 — The Daily Command Center (LIVE-provable; substrate already in DealStore)
- **T2.1 — Owner / next-action / due-date columns on `deals`** (unblocks job 3)
- **T2.2 — Morning action queue (job 1)** ranked by dollar impact × urgency × close probability
- **T2.3 — Overnight change brief (job 2)** — needs **listing change detection** (price, status,
  OM, broker, DOM), which we do not have: `check_alerts` only emits never-before-seen matches.
  Also unlocks jobs 13, 14.
- **T2.4 — Transaction dependency & deadline tracker (job 184)** on `dd_items`.

### TIER 3 — Underwriting completeness (LIVE-provable; closes embarrassing table-stakes gaps)
- **T3.1 — Scenario / stress engine (job 46)** + sensitivity ranking → also completes job 50.
- **T3.2 — Acquisition tax-reassessment engine (job 51)** — assessor data is free and live;
  a frequent, material NOI miss. GPT's #19; I'd pull it up.
- **T3.3 — Data-room completeness index (job 182)** — `deal_truth_report` already knows what's
  missing; make it an assignable index.

### DEFERRED (right call, wrong time)
- Cat 15 (property management), jobs 65/141/142/148/157, cat 20 — **BLOCKED on data.**
- Cat 10 (development/construction) — a different product; no current use case.
- Cat 9 (zoning/entitlements) — free data, LIVE-provable, genuinely valuable, but 10 jobs of
  municipal-corpus work. Revisit after Tier 1-3.

---

## Honest note on what this cannot become

Categories 8, 9, 11, and much of 6 terminate in a **licensed professional** — attorney,
surveyor, environmental consultant, CPA, appraiser, insurance producer. The tool's honest
ceiling there is: *assemble the evidence, flag the issue, route it to the human, never opine.*
The `capabilities` tool and the authority matrix (Phase 31) already say this. Any build in
those categories must keep saying it.
