"""Honest positioning: what this engine is, what it is not, and who may act.

Phase 31. GPT-5.6's teardown warned that the danger is a novice trusting a number
as if it were validated truth. This module centralizes the honest framing so every
surface can speak the same way: an evidence-backed process that knows where expert
judgment is required — never a replacement for capital, relationships, or reps.
"""

from __future__ import annotations

from typing import Any

# What the engine genuinely can and cannot do (used by the `capabilities` tool).
CAPABILITIES: dict[str, Any] = {
    "can": [
        "Screen deals fast from listings and public data",
        "Reconstruct verified NOI from real documents and flag where the seller overstated it",
        "Run underwriting math (cap, DSCR, cash-on-cash, IRR, after-tax) with echoed assumptions",
        "Manufacture off-market opportunities (control/lease-creation, master-lease arbitrage)",
        "Rank tenant fit, model spreads, and draft owner + tenant outreach",
        "Score off-market owner motivation from real trigger events",
        "Produce a buyer-specific decision frontier and a go/no-go verdict",
        "Enforce a disciplined process and catch obvious, expensive mistakes",
    ],
    "cannot": [
        "Provide liquidity, net worth, or guaranty capacity",
        "Provide reputation, relationships, or a closing track record",
        "Replace field judgment, local knowledge, or a site visit",
        "Give a validated probability of success until real closed-deal outcomes calibrate it",
        "Replace a securities attorney, CPA, QI, lender, or licensed broker/appraiser",
    ],
    "honest_promise": (
        "A newer investor can run a disciplined, evidence-backed acquisition process and "
        "bring experts a complete, sourced file — recognizing where expert judgment is required."
    ),
    "not_a_promise": (
        "It does NOT let anyone operate like a 20-year veteran or close without the reps. "
        "A veteran is a network, a balance sheet, pattern recognition, and scars."
    ),
}

# Who is allowed to take each class of action. "Human in the loop" is too vague;
# this is the explicit authority matrix.
AUTHORITY_MATRIX: dict[str, str] = {
    "research": "AI may do autonomously",
    "calculate": "AI may do autonomously",
    "draft": "AI may draft (LOI, PPM, outreach, proposals) — draft only, never send",
    "recommend": "AI may recommend a verdict/structure — advisory, not a decision",
    "send_outreach": "requires explicit human approval before anything is sent",
    "submit_offer_or_loi": "requires explicit human approval",
    "raise_capital": "requires securities-counsel review AND human approval",
    "commit_funds_or_wire": "AI may NEVER do this under any circumstances",
}

STANDARD_DISCLAIMER = (
    "Advisory screening/analysis, not investment, legal, or tax advice. Figures are only as "
    "good as their sources; unverified inputs and fatal flaws are surfaced, not hidden. The "
    "Deal Score is UNCALIBRATED until real closed-deal outcomes accrue. Route legal, tax, "
    "securities, lending, and appraisal decisions to the accountable licensed professional."
)


def assumptions_sheet(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Surface the assumptions driving a result so nothing is hidden behind a number.

    Returns one row per known driver with its value and a source-quality label
    ("provided", "verified", "estimated", "default", "unknown"). Missing drivers are
    listed as unknown rather than silently defaulted.
    """
    drivers = [
        "purchase_price", "noi_basis", "noi", "vacancy_rate", "cap_rate", "market_cap_rate",
        "rent_psf", "financing_rate", "ltv", "hold_years", "exit_cap", "reserves", "source_quality",
    ]
    sheet: list[dict[str, Any]] = []
    for key in drivers:
        if key in inputs and inputs[key] is not None:
            sheet.append({"driver": key, "value": inputs[key], "source": inputs.get(f"{key}_source", "provided")})
        else:
            sheet.append({"driver": key, "value": None, "source": "unknown"})
    return sheet


__all__ = ["CAPABILITIES", "AUTHORITY_MATRIX", "STANDARD_DISCLAIMER", "assumptions_sheet"]
