# PHASE 30 — Deal Graph / Memory + Shadow-IC + buyer-specific Decision Engine  ✅

The MEMORY system (third of Truth · Control · Memory) plus the buyer-specific decision layer.
GPT-5.6's teardown: "there is no universally best deal" and "capture the system's call vs the
expert's vs the outcome" — the compounding loop that eventually calibrates the score.

## 30b — Deal-graph memory + Shadow-IC  (Fable, commit 428dbea)
DealStore gains `ic_decisions` + `deal_events` tables.
- `record_ic_decision` — logs the system's verdict and (optionally) the expert's; `agreed`
  computed. The SHADOW: the system commits its call independent of the expert's.
- `log_deal_event` / `deal_timeline` — append-only per-deal event log (offer, counter,
  lender_quote, diligence_finding, …) = the deal-graph view of one deal.
- `ic_scorecard` — joins IC calls to realized outcomes: system-vs-expert agreement rate +
  system-vs-outcome accuracy, both n-gated with an explicit "small-n is directional" caveat.
Tools: record_ic_decision, log_deal_event, deal_timeline, ic_scorecard (61 → 65). 3 tests.

## 30a — Buyer-specific Decision Engine  (Codex, isolated `decision/` package)
Replaces "static 0–100 score = truth" with a **decision frontier** for THIS buyer.
- `BuyerProfile` — cash/reserves/liquidity/net-worth/guaranty, return req, hold pref, recourse
  tolerance, operating capability, tax-deferral need, closing track record, … all optional
  (missing = literal "unknown", never a silent failure).
- `decision_frontier(deal, buyer, structures)` — per candidate structure (all_cash /
  conventional_75ltv / seller_finance / master_lease / option_then_lease / jv_preferred_equity):
  cash needed, expected + downside return, acceptance / financing / close probability,
  buyer_fit (+reasons), combined score. Leads with any fatal flaws; never recommends pursuit
  over a fatal flaw. Carries an UNCALIBRATED caveat.
Tools: set_buyer_profile, decision_frontier (65 → 67).

## Verified
Full suite green at each integration (30b: 600). Decision engine verified on integration.

## Note
Frontier probabilities are honest heuristics with missing inputs left "unknown" — not
fabricated precision. The score becomes a real edge only as `record_ic_decision` +
`record_deal_outcome` accumulate (Phase 22 calibration harness consumes them).
