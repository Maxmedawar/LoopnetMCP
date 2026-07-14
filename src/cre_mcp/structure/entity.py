"""Deterministic entity and ownership-vehicle screening with hard legal gates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cre_mcp.execution.guardrails import structure_guardrail
from cre_mcp.models.structure import StructureAdvice, StructureIntent

PARTNERSHIP_INTEREST_TRAP = (
    "1031-INELIGIBLE TRAP — A membership interest in a multi-member LLC or partnership "
    "is not qualifying real property for a §1031 exchange. The taxpayer must exchange "
    "direct real property (including through a properly disregarded single-member entity), "
    "a qualifying DST interest, or another interest tax counsel confirms is real property."
)
SAME_TAXPAYER_TRAP = (
    "SAME-TAXPAYER-TITLE TRAP — The same federal taxpayer that relinquishes the old real "
    "property generally must acquire the replacement property. Do not change owners, admit "
    "members, or change entity tax classification mid-exchange without QI and tax-counsel approval."
)
SEC_TRAP = (
    "SEC GATE — Pooling outside investor money or selling LLC/TIC/DST/QOF interests can be "
    "an offer or sale of securities. Do not solicit, accept subscriptions, or take investor "
    "funds until securities counsel selects and documents a registration exemption; continue "
    "through the Phase 19 capital-raise controls."
)

STRUCTURE_DISCLAIMER = (
    "This is a deterministic educational structure screen, not legal, tax, securities, or "
    "investment advice. Entity classification and eligibility depend on documents and facts "
    "this tool cannot verify."
)


def _intent(value: Mapping[str, Any] | StructureIntent) -> StructureIntent:
    return value if isinstance(value, StructureIntent) else StructureIntent.model_validate(value)


def recommend_structure(
    intent: Mapping[str, Any] | StructureIntent,
) -> StructureAdvice:
    """Screen LLC/DST/TIC/QOF fit while making disqualifying traps unmissable."""
    selected = _intent(intent)
    has_external_investors = selected.investors > 0

    if selected.mode == "oz":
        recommended = "QOF"
        rationale = (
            "The stated goal is an Opportunity Zone investment. A qualifying equity investment "
            "through a properly operated QOF is the relevant vehicle, subject to the 180-day gain "
            "investment window, QOZ-property tests, annual compliance, and a long hold."
        )
        alternatives = [
            "LLC — ordinary direct ownership, but not itself a QOF benefit",
            "DST — passive §1031 replacement, not an Opportunity Zone substitute",
        ]
    elif selected.mode == "syndication":
        recommended = "LLC"
        rationale = (
            "A manager-managed multi-member LLC commonly centralizes title, governance, and "
            "investor economics for a syndication, but its membership interests are securities "
            "and are not §1031 replacement real property for the members."
        )
        alternatives = [
            "TIC — direct co-ownership with limited centralized control and materially more administration",
            "DST — sponsor-controlled passive fractional replacement where the offering and trust qualify",
        ]
    elif selected.mode == "1031" and selected.passive is True:
        recommended = "DST"
        rationale = (
            "The goal is passive §1031 replacement ownership. A DST matching Revenue Ruling "
            "2004-86 can be treated as an interest in real property, but the investor gives up "
            "operating control and must diligence sponsor, debt, fees, and trust restrictions."
        )
        alternatives = [
            "LLC — direct title through the same taxpayer's disregarded SMLLC",
            "TIC — direct undivided co-ownership with voting and administration limits",
        ]
    elif selected.mode == "1031" and has_external_investors:
        recommended = "TIC"
        rationale = (
            "Multiple taxpayers seeking separate §1031 treatment generally need direct undivided "
            "real-property interests rather than interests in one partnership. A TIC can fit, but "
            "the deed, co-ownership agreement, voting, transfer, debt, and operating facts require "
            "specialized tax and real-estate counsel."
        )
        alternatives = [
            "DST — passive sponsor-controlled replacement if each investor independently qualifies",
            "LLC — only for direct title by the exchanging taxpayer through a disregarded SMLLC, not a multi-member interest",
        ]
    else:
        recommended = "LLC"
        rationale = (
            "Direct ownership through a properly formed single-purpose LLC is the simplest fit. "
            "For §1031, a single-member LLC can be disregarded for federal income tax purposes, "
            "but the regarded owner and title path must remain consistent with the exchanging taxpayer."
        )
        alternatives = [
            "DST — passive fractional replacement with no investor management control",
            "TIC — direct undivided co-ownership when multiple taxpayers must hold real property separately",
        ]

    state_note = (
        f"Have {selected.state.upper()} counsel confirm formation, foreign registration, title, and liability rules."
        if selected.state
        else "Have property-state counsel choose formation/registration and title details."
    )
    eligibility_notes = {
        "LLC": (
            "Eligible for direct real-property ownership. For §1031, a disregarded SMLLC owned by "
            "the same taxpayer can preserve the taxpayer identity; a multi-member LLC membership "
            "interest is 1031-INELIGIBLE."
        ),
        "DST": (
            "Potentially §1031-eligible only when the trust and interest fit Revenue Ruling "
            "2004-86 and current law. Passive investor: no operating control, new capital calls, "
            "or easy exit; sponsor/offering/financing diligence is essential."
        ),
        "TIC": (
            "Potentially §1031-eligible as direct undivided real-property co-ownership. Revenue "
            "Procedure 2002-22 describes ruling conditions, not a blanket safe harbor; partnership-like "
            "operations can destroy the intended treatment."
        ),
        "QOF": (
            "Opportunity Zone vehicle, not a §1031 replacement shortcut. A qualifying gain must be "
            "timely invested for QOF equity; after at least 10 years a qualifying investment may elect "
            "a fair-market-value basis adjustment on disposition. Confirm current transition rules."
        ),
    }
    traps = [PARTNERSHIP_INTEREST_TRAP, SAME_TAXPAYER_TRAP]
    if selected.mode == "syndication" or has_external_investors:
        traps.append(SEC_TRAP)

    gates = [
        "A real-estate/entity attorney must approve the operating/title documents.",
        "A CPA/tax attorney must confirm federal taxpayer classification and the modeled tax result.",
    ]
    if selected.mode == "1031":
        gates.insert(
            0,
            "Engage a Qualified Intermediary before the relinquished property closes and before anyone can touch proceeds.",
        )
    if selected.mode == "syndication" or has_external_investors:
        gates.append(
            "A securities attorney must approve the offering path before any solicitation or investor money."
        )
    if selected.mode == "oz":
        gates.append(
            "Opportunity Zone tax counsel must confirm eligible gain, timing, QOF/QOZ tests, filings, and the 10-year election."
        )

    return StructureAdvice(
        intent=selected,
        recommended=recommended,
        rationale=rationale,
        alternatives=alternatives,
        eligibility_notes=eligibility_notes,
        traps=traps,
        authorities=[
            "IRC §1031 and IRS Form 8824 instructions (real property, excluded partnership interests, 45/180-day rules)",
            "IRS Revenue Ruling 2004-86 (specified DST interest treated as real property)",
            "IRS Revenue Procedure 2002-22 (TIC ruling-request conditions)",
            "IRC §1400Z-2 and IRS Opportunity Zone guidance (qualifying QOF investment and 10-year election)",
            "Securities Act of 1933 / SEC exempt-offering guidance (registration or valid exemption required)",
        ],
        counsel_gate=structure_guardrail("HARD GATE: " + " ".join(gates)),
        disclaimer=f"{STRUCTURE_DISCLAIMER} {state_note}",
    )


__all__ = [
    "PARTNERSHIP_INTEREST_TRAP",
    "SAME_TAXPAYER_TRAP",
    "SEC_TRAP",
    "STRUCTURE_DISCLAIMER",
    "recommend_structure",
]
