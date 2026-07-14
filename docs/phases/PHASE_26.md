# PHASE 26 — Document Truth Engine II: reconciliation + NOI bridge  ✅

Completes the Truth system. Turns Phase-25 cited claims into ONE verified answer and a
go/no-go verdict — the piece that catches an OM lying about NOI before the deposit goes hard.

## Delivered
- `truth/reconcile.py` — `SOURCE_AUTHORITY` ladder (amendment > lease > estoppel > bank >
  tax bill > assessor > appraisal > rent roll > T12 > OM > listing). `resolve()` groups claims
  per (field, subject), ranks by authority→confidence, picks a winner, and:
  - surfaces material disagreements as `Conflict`s that keep BOTH values, `needs_human_review`,
    and **never average** (rule `source_disagreement`);
  - flags pro-forma-as-actual (rule `proforma_as_actual`);
  - bumps confidence when an independent source corroborates within 2%.
- `truth/noi_bridge.py` — `build_bridge()` restates NOI three ways with cited lines +
  method notes + a dollar **NOI walk**: seller-stated (as pitched, pro forma allowed) →
  verified (bottom-up recompute, pro-forma dropped, OM-only fields called out) → lender
  (labeled floors: vacancy ≥5%, expense ratio ≥35%, +3% reserves). `build_report()` →
  `FatalFlawReport` with an explicit verdict: SELLER_NOI_OVERSTATED (>10% gap) → re_trade;
  material conflict / blocking missing doc → proceed_with_conditions; pro-forma-as-actual +
  missing lease/T12/tax-bill/estoppel surfaced.
- `tools/truth_tools.py` — `reconcile_deal_docs`, `build_noi_bridge` (pulls the deal's asking
  price for implied cap rates), `deal_truth_report`. Computed fresh from stored claims (no new
  tables). Tool count 47 → 50.

## Verified
- `pytest tests/truth/ -q` → 24 passed (15 P25 + 9 P26). Full suite (ex Codex in-flight) 581.
- Golden case: a pro-forma OM (headline NOI 300k, components imply 180k) → verified NOI 180k,
  NOI walk −120k, verdict **re_trade**, flags SELLER_NOI_OVERSTATED + PROFORMA_AS_ACTUAL,
  missing lease + T12 flagged. A clean T12 deal with no lease → proceed_with_conditions.

## Not yet
- Line-item rent-roll extraction (per-tenant base_rent) → richer cross-doc detectors
  (OM-rent-vs-lease-rent, brand-vs-guarantor, SF mismatch, tax-reassessment) — future.
- Feeding the verified column into `underwrite_listing` for a full verified underwrite.
