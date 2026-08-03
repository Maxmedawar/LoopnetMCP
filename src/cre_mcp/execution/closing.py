"""Deterministic, state-routed commercial real-estate closing coordinator."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cre_mcp.execution.guardrails import execution_guardrail
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import ClosingPlan, ClosingStep


@dataclass(frozen=True)
class ClosingStateRule:
    mode: str
    coordinator: str
    note: str


# Routing aids only. Local counsel must confirm the rule and commercial-deal practice.
CLOSING_STATE_RULES: dict[str, ClosingStateRule] = {
    "GA": ClosingStateRule(
        "attorney-led",
        "Georgia closing attorney and title insurer",
        "Georgia treats real-estate closing as legal work; retain Georgia closing counsel to control the process and funds.",
    ),
    "NC": ClosingStateRule(
        "attorney-supervised",
        "North Carolina CRE attorney and title insurer",
        "North Carolina reserves core title, document, and legal closing work to licensed counsel; have North Carolina counsel supervise the closing path.",
    ),
    "TX": ClosingStateRule(
        "title/escrow-led with buyer counsel",
        "Texas-licensed title agent/escrow officer and buyer's CRE attorney",
        "Texas commonly closes through a licensed title agent and escrow officer; buyer's CRE counsel should independently clear legal and title issues.",
    ),
    "AZ": ClosingStateRule(
        "title/escrow-led with buyer counsel",
        "Arizona title/escrow officer and buyer's CRE attorney",
        "Arizona commonly uses title/escrow; retain Arizona CRE counsel for entity, contract, title-exception, and lease advice.",
    ),
    "CO": ClosingStateRule(
        "title/escrow-led with buyer counsel",
        "Colorado title/escrow officer and buyer's CRE attorney",
        "Colorado commonly uses title/escrow; commercial documents, title exceptions, and entity decisions still need Colorado counsel.",
    ),
    "CA": ClosingStateRule(
        "escrow/title-led with buyer counsel",
        "California-licensed escrow/title officer and buyer's CRE attorney",
        "California commonly uses licensed or controlled escrow providers; buyer's California CRE counsel should clear legal and title issues.",
    ),
    "FL": ClosingStateRule(
        "title-agent/attorney coordinated",
        "Florida title agent and buyer's Florida CRE attorney",
        "Florida closings may be coordinated by a title agent or attorney; use independent Florida CRE counsel for buyer-side legal review.",
    ),
    "NV": ClosingStateRule(
        "title/escrow-led with buyer counsel",
        "Nevada title/escrow officer and buyer's CRE attorney",
        "Nevada commonly uses title/escrow; have Nevada CRE counsel confirm legal documents, title exceptions, and entity authority.",
    ),
    "GENERAL": ClosingStateRule(
        "local practice must be confirmed",
        "Local CRE attorney and licensed title/escrow provider",
        "Closing roles vary by state and transaction; local CRE counsel must confirm who may prepare documents, clear title, hold funds, and close.",
    ),
}


WIRE_FRAUD_WARNING = (
    "WIRE-FRAUD STOP: NEVER rely on emailed wire instructions or an emailed change. "
    "Before sending any funds, call the title/escrow/closing attorney using a known, "
    "independently verified phone number and read back the receiving bank, account name, "
    "routing number, and account number. Expect NO last-minute wire changes; stop and "
    "re-verify any change or urgency."
)

STATE_NAME_TO_CODE = {
    "ARIZONA": "AZ",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "NEVADA": "NV",
    "NORTHCAROLINA": "NC",
    "TEXAS": "TX",
}


def _state_code(value: str | None) -> str:
    code = re.sub(r"[^A-Za-z]", "", value or "").upper()
    if len(code) == 2:
        return code
    return STATE_NAME_TO_CODE.get(code, "GENERAL")


def closing_plan(ctx: DealContext, state: str | None = None) -> ClosingPlan:
    """Return an ordered entity-to-funding runway for professional review."""
    state_code = _state_code(state or ctx.listing.state)
    rule = CLOSING_STATE_RULES.get(state_code, CLOSING_STATE_RULES["GENERAL"])
    property_state = state_code if state_code != "GENERAL" else "the property's state"
    deal_ref = f"{ctx.listing.source}:{ctx.listing.source_id}"

    steps = [
        ClosingStep(
            order=1,
            title="Choose the acquisition entity and tax path",
            detail=(
                f"Ask counsel whether to form the acquisition LLC in {property_state}; a property-state LLC "
                "often avoids foreign registration, but liability, lender, investor, and tax facts control. "
                "If this is a 1031 exchange, have the qualified intermediary and tax counsel confirm that the "
                "same taxpayer—or a permitted disregarded entity—will acquire title before documents are signed."
            ),
            who="CRE attorney, CPA/tax counsel, and qualified intermediary (before sale/closing if 1031)",
            gate="Written entity/tax/title path approved before forming the borrower or signing lender documents.",
        ),
        ClosingStep(
            order=2,
            title="Form and authorize the acquisition LLC",
            detail=(
                f"File the LLC in {property_state} or follow counsel's alternate structure; obtain a certificate "
                "of good standing and written authority for the signer and transaction."
            ),
            who="CRE attorney or supervised entity service",
            gate="Exact legal name, state, ownership, signer authority, and title vesting match the approved structure.",
        ),
        ClosingStep(
            order=3,
            title="Obtain EIN and tax records",
            detail="Obtain the entity EIN directly from the IRS and give the lender/title team the matching legal-name record.",
            who="Buyer with CPA or tax counsel",
            gate="EIN confirmation name matches formation and proposed vesting exactly.",
        ),
        ClosingStep(
            order=4,
            title="Execute the operating agreement and resolutions",
            detail="Document ownership, capital calls, management, guarantees, signing authority, distributions, and acquisition/loan approval.",
            who="CRE/entity attorney",
            gate="All members approve final economics and authorized signers before lender/entity diligence.",
        ),
        ClosingStep(
            order=5,
            title="Open and season the entity bank account",
            detail="Open an account in the exact acquiring entity name; document equity sources and avoid mixing personal or unrelated funds.",
            who="Buyer, bank, CPA, and lender source-of-funds reviewer",
            gate="Account ownership and equity trail are accepted by lender and closing coordinator.",
        ),
        ClosingStep(
            order=6,
            title="Submit the final entity package to the lender",
            detail="Deliver formation, good standing, EIN, operating agreement, resolutions, ownership, guarantees, insurance, and verified equity trail.",
            who="Lender/loan officer, lender counsel, and buyer's CRE attorney",
            gate="Lender confirms borrower/guarantor approval, final proceeds, conditions, reserves, and closing authorization in writing.",
        ),
        ClosingStep(
            order=7,
            title="Open title/escrow and clear closing authority",
            detail=(
                f"{rule.note} Review the commitment, survey, entity vesting, payoff/release, taxes, liens, "
                "recording requirements, gap coverage, and every exception; do not treat a title policy as legal advice."
            ),
            who=rule.coordinator,
            gate="Counsel/title confirms acceptable insurable title, authority, releases, and good-funds procedure.",
        ),
        ClosingStep(
            order=8,
            title="Bind property and liability insurance",
            detail="Bind coverage effective at the required risk-transfer time with lender clauses, limits, deductibles, and lease requirements satisfied.",
            who="CRE insurance broker and lender insurance reviewer",
            gate="Binder, paid receipt, and endorsements are accepted by lender and counsel before funding.",
        ),
        ClosingStep(
            order=9,
            title="Finalize estoppels, SNDAs, and lease assignment",
            detail="Reconfirm required tenant estoppels/SNDAs and execute assignment/assumption of leases, deposits, contracts, warranties, and records.",
            who="CRE attorney, lender counsel, seller, and property manager",
            gate="Required tenant documents match diligence and all transferable rights/deposits are scheduled.",
        ),
        ClosingStep(
            order=10,
            title="Walk the settlement statement line by line",
            detail=(
                "Compare the draft ALTA/HUD-1-style settlement statement to the contract and lender closing disclosure: "
                "price, loan, earnest credit, title/recording, taxes, rent, CAM, security deposits, utilities, "
                "commissions, lender fees, reserves, credits, payoffs, and cash required."
            ),
            who="Buyer's CRE attorney, title/escrow/closing attorney, CPA, and lender",
            gate="Buyer independently approves documented prorations, credits, fees, payoffs, reserves, and final cash-to-close.",
        ),
        ClosingStep(
            order=11,
            title="Funding: stop and verify every wire",
            detail=f"{WIRE_FRAUD_WARNING} Repeat the callback immediately before initiating the wire and preserve the verification record.",
            who="Buyer principal and known title/escrow/closing-attorney contact; bank fraud team if anything changes",
            gate=f"NO FUNDS MOVE until this protocol is completed: {WIRE_FRAUD_WARNING}",
        ),
        ClosingStep(
            order=12,
            title="Confirm recording and authorized disbursement",
            detail="Do not assume funding equals ownership. Obtain confirmation that deed/security instruments recorded and funds were released under approved instructions.",
            who=rule.coordinator,
            gate="Recording numbers, final title-policy path, disbursement confirmation, and complete signed closing set are received.",
        ),
        ClosingStep(
            order=13,
            title="Send tenant notice-to-pay and complete handoff",
            detail="After counsel confirms closing, send attorney-approved ownership/payment notices; transfer deposits, keys, systems, contracts, records, tax calendars, and emergency contacts.",
            who="CRE attorney, buyer, and property manager",
            gate="No payment instruction is sent before title/closing confirmation; tenant ledger and deposit balances match the settlement statement.",
        ),
    ]
    return ClosingPlan(
        deal_ref=deal_ref,
        state=state_code,
        closing_mode=rule.mode,
        state_note=rule.note,
        steps=steps,
        wire_fraud_warning=WIRE_FRAUD_WARNING,
        red_flags=[
            "Entity, EIN, signer, borrower, or deed vesting names do not match.",
            "1031 taxpayer/title path was changed without qualified-intermediary and tax-counsel approval.",
            "Unresolved title/survey exception, lien, payoff, or recording condition remains at funding.",
            "Required estoppel, SNDA, lease assignment, insurance binder, or lender condition is missing.",
            "Settlement prorations, deposits, credits, reserves, or cash-to-close do not reconcile.",
            "Any emailed, urgent, or last-minute wire instruction/change that has not passed known-number callback verification.",
        ],
        guardrail=execution_guardrail(
            "Have local CRE counsel and the licensed closing/title/escrow professional confirm this "
            "state's rules, calendar every gate, and authorize documents and funding."
        ),
    )


__all__ = [
    "CLOSING_STATE_RULES",
    "WIRE_FRAUD_WARNING",
    "STATE_NAME_TO_CODE",
    "ClosingStateRule",
    "closing_plan",
]
