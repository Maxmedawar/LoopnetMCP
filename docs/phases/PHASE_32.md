# PHASE 32 — Master-Lease Arbitrage  ✅  (Max's "sidequest, done properly")

Commercial rental arbitrage as a first-class flow: sign a MASTER LEASE on a space, sublease it
to a real business tenant, keep the spread. Built for the autonomous-agent use case
(MedawarCRE MCP = brains, an Email MCP = hands, a routine agent = the loop). Codex-built in an
isolated `arbitrage/` package, Fable-verified + integrated.

## Delivered
- `arbitrage/economics.py::master_lease_arbitrage` — the true P&L: gross sublease income, total
  cost (master rent + mgmt + amortized TI/free-rent + other), net cash flow, margin, **rent
  coverage**, **breakeven occupancy**, and — non-negotiable honesty — **negative_carry_exposure**
  (the master rent you owe even if the sublease sits empty) + risk_flags (thin_coverage,
  fragile_occupancy, negative_carry, personal_guarantee_amplifies_loss) + a year-by-year
  projection with dual escalations. Verified exact: 60k master / 2000sf / $45psf @95% →
  $85,500 gross, $21,225 net, 1.425 coverage, $60k carry exposure.
- `arbitrage/finder.py::find_arbitrage_opportunities` — ranks for-lease spaces where achievable
  sublease rate beats the master rate; drops/counts non-positive spreads.
- `arbitrage/proposals.py` — `draft_master_lease_proposal` (owner pitch: guaranteed rent,
  hands-off, asks for sublet/assignment rights) + `draft_subtenant_outreach` (tenant email
  weaving in cars/day, foot traffic, parking, size, amenities, price+term, and nearby brands).
- `tools/arbitrage_tools.py` — analyze_master_lease, find_arbitrage_opportunities,
  draft_master_lease_proposal, draft_subtenant_outreach, and **master_lease_playbook** (one call:
  economics + ranked candidate franchises w/ corporate-vs-franchisee guaranty tier + owner
  proposal + sample tenant email). 67 → 72 tools.

## Verified
5 new tests; full suite **610 passed**. Isolation held (only `arbitrage/` touched).

## Honest framing
Arbitrage is a real business, not free money: the tool leads with negative-carry exposure and
coverage so the operator goes in eyes open. The MCP provides the analysis + drafts; sending is
the agent's Email MCP; tenant-fit judgment is the LLM's.
