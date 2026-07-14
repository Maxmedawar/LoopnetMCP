"""Plain-English, jurisdiction-aware non-binding LOI drafting."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping

from cre_mcp.execution.guardrails import execution_guardrail
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import LoiDraft, OfferRecommendation
from cre_mcp.scoring.rubrics import thresholds as T

JURISDICTION_NOTES = {
    "TX": (
        "Texas deals commonly use a title company as escrow and closing agent. "
        "Earnest money, title-objection deadlines, and closing instructions are negotiated; "
        "confirm this commercial structure with Texas CRE counsel."
    ),
    "FL": (
        "Florida closings may use an attorney or licensed title/settlement agent. "
        "Name the deposit holder and confirm escrow, title, and document-preparation roles "
        "with Florida CRE counsel."
    ),
    "AZ": (
        "Arizona transactions commonly move through title and escrow settlement. "
        "Deposit release instructions and diligence deadlines are negotiated; confirm local "
        "commercial custom with Arizona CRE counsel."
    ),
    "NC": (
        "North Carolina gives licensed attorneys a central role in legal closing functions. "
        "Engage North Carolina CRE counsel early to settle title, documents, escrow, and "
        "closing responsibilities."
    ),
    "CO": (
        "Colorado transactions commonly use a title company to hold earnest money and "
        "perform closing services, though attorneys may also participate. Confirm the chosen "
        "settlement provider and deposit instructions with Colorado CRE counsel."
    ),
    "CA": (
        "California transactions commonly use neutral escrow and title providers. Escrow "
        "instructions, deposit release, title review, and closing conditions should be "
        "coordinated with California CRE counsel."
    ),
}
GENERAL_JURISDICTION_NOTE = (
    "GENERAL — local closing and deposit practices were not selected. Confirm the escrow "
    "holder, attorney/title roles, deposit custom, and required forms with local CRE counsel."
)


def _terms(offer_terms: Mapping[str, Any] | OfferRecommendation) -> dict[str, Any]:
    if isinstance(offer_terms, OfferRecommendation):
        return {
            "price": offer_terms.target_price,
            "recommendation": offer_terms.model_dump(mode="python"),
        }
    return dict(offer_terms)


def _positive_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive number") from exc
    if number <= 0:
        raise ValueError(f"{label} must be a positive number")
    return number


def _positive_days(value: Any, label: str) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive whole number") from exc
    if days <= 0:
        raise ValueError(f"{label} must be a positive whole number")
    return days


def _money(value: float) -> str:
    return f"${value:,.0f}"


def generate_loi(
    ctx: DealContext,
    offer_terms: Mapping[str, Any] | OfferRecommendation,
) -> LoiDraft:
    """Draft and explain a non-binding LOI, preserving attorney-review gates."""
    terms = _terms(offer_terms)
    fallback_price = ctx.listing.price_usd
    price = _positive_number(terms.get("price", fallback_price), "price")
    buyer_entity = str(
        terms.get("buyer_entity") or "Buyer entity to be formed or designated"
    ).strip()
    if not buyer_entity:
        raise ValueError("buyer_entity cannot be blank")
    earnest_pct = _positive_number(
        terms.get("earnest_money_pct", T.LOI_DEFAULT_EARNEST_MONEY_PCT),
        "earnest_money_pct",
    )
    earnest_money = _positive_number(
        terms.get("earnest_money", price * earnest_pct / 100),
        "earnest_money",
    )
    dd_days = _positive_days(
        terms.get("dd_days", T.LOI_DEFAULT_DD_DAYS),
        "dd_days",
    )
    closing_days = _positive_days(
        terms.get("closing_days", T.LOI_DEFAULT_CLOSING_DAYS),
        "closing_days",
    )
    expiration_days = _positive_days(
        terms.get("expiration_days", T.LOI_DEFAULT_EXPIRATION_DAYS),
        "expiration_days",
    )
    state = (
        str(terms.get("state") or ctx.listing.state or "GENERAL").upper().strip()
    )
    jurisdiction_note = JURISDICTION_NOTES.get(state, GENERAL_JURISDICTION_NOTE)
    seller_name = str(terms.get("seller_name") or "Seller of record").strip()
    brokerage = str(
        terms.get("brokerage")
        or "Each party is responsible for commissions owed under its separate agreements."
    ).strip()
    financing_contingency = bool(terms.get("financing_contingency", True))
    assignment_allowed = bool(terms.get("assignment_allowed", True))
    go_hard_after_dd = bool(terms.get("earnest_money_goes_hard_after_dd", True))
    confidentiality = bool(terms.get("confidentiality", True))

    supplied_contingencies = terms.get("contingencies")
    if supplied_contingencies is None:
        contingencies = [
            (
                "Satisfactory physical, environmental, zoning, lease, financial, "
                "and title diligence"
            ),
            "Buyer approval of survey and title commitment",
            (
                "Negotiation and execution of a mutually acceptable purchase and "
                "sale agreement"
            ),
        ]
    elif isinstance(supplied_contingencies, (list, tuple)):
        contingencies = [
            str(item).strip() for item in supplied_contingencies if str(item).strip()
        ]
    else:
        raise ValueError("contingencies must be a list of terms")
    if financing_contingency:
        contingencies.append(
            "Buyer obtaining written financing approval on terms acceptable to Buyer"
        )
    financing_text = (
        "This proposal is contingent on Buyer obtaining written financing approval on "
        "terms acceptable to Buyer before the deposit becomes non-refundable."
        if financing_contingency
        else (
            "No financing contingency is proposed; counsel must review this waiver "
            "and its deposit risk."
        )
    )
    go_hard_text = (
        "The deposit is proposed as refundable during due diligence and non-refundable "
        "after that period, except for written title, casualty, condemnation, seller-default, "
        "and surviving contingency protections in the purchase agreement."
        if go_hard_after_dd
        else (
            "The deposit is proposed as refundable until closing, subject to the "
            "purchase agreement."
        )
    )
    assignment_text = (
        "Buyer may assign the purchase agreement to an affiliated entity or acquisition SPV "
        "without releasing the original Buyer unless the definitive agreement says otherwise."
        if assignment_allowed
        else (
            "No assignment right is proposed; any later assignment requires Seller's "
            "written consent."
        )
    )
    confidentiality_text = (
        "The parties propose keeping non-public deal terms and diligence materials confidential, "
        "subject to disclosures to lenders, investors, advisers, and as required by law."
        if confidentiality
        else "No separate confidentiality provision is proposed in this draft."
    )
    expiration = date.today() + timedelta(days=expiration_days)
    property_description = ", ".join(
        value
        for value in (
            ctx.listing.address,
            ctx.listing.city,
            ctx.listing.state,
            ctx.listing.zip_code,
        )
        if value
    )
    deal_ref = f"{ctx.listing.source}:{ctx.listing.source_id}"
    disclaimer = execution_guardrail(
        "have local CRE counsel revise this LOI, then obtain written lender feedback "
        "before signing."
    )

    term_notes = {
        "parties": (
            "Names who is proposing to buy and who owns the property; verify exact "
            "legal names before signing."
        ),
        "property": (
            "Defines the real estate and should ultimately include every parcel, "
            "easement, and included asset."
        ),
        "purchase_price": (
            "States the proposed price, not the final cash needed after deposits, "
            "costs, prorations, and financing."
        ),
        "earnest_money": (
            "Shows seriousness and becomes money at risk only under the definitive "
            "agreement's release rules."
        ),
        "earnest_money_go_hard": (
            "Going hard means refund rights narrow; counsel must make every surviving "
            "exit right explicit."
        ),
        "due_diligence": (
            "This is the buyer's investigation clock for documents, property "
            "condition, title, zoning, and environmental risk."
        ),
        "closing": (
            "Sets the proposed time from diligence completion to funding and deed "
            "transfer."
        ),
        "contingencies": (
            "These are conditions that must be preserved in the purchase agreement "
            "before the buyer is obligated to close."
        ),
        "financing_contingency": (
            "Keeps lender failure from automatically becoming the buyer's deposit "
            "loss unless deliberately waived."
        ),
        "as_is": (
            "As-is shifts condition risk to the buyer, making inspection rights and "
            "seller representations especially important."
        ),
        "brokerage": (
            "Allocates commission responsibility and avoids accidentally promising a "
            "commission twice."
        ),
        "confidentiality": (
            "Controls who may receive sensitive deal and property information; "
            "counsel should define exceptions."
        ),
        "expiration": (
            "Creates a deadline for this proposal so it does not remain open "
            "indefinitely."
        ),
        "assignment": (
            "Determines whether the buyer may move the contract into its acquisition "
            "entity or another party."
        ),
        "default_remedies": (
            "Remedies are intentionally deferred to the purchase agreement because "
            "they determine damages and termination rights."
        ),
        "non_binding": (
            "The LOI is a negotiating outline only; no purchase obligation arises "
            "until a definitive agreement is signed."
        ),
        "jurisdiction": (
            "Local closing, escrow, title, and legal-practice customs vary, so local "
            "counsel must confirm the process."
        ),
    }
    attorney_review_flags = [
        "earnest_money_go_hard",
        "financing_contingency",
        "assignment",
        "as_is_and_diligence",
        "confidentiality",
        "default_and_remedies",
        f"jurisdiction_{state.casefold()}",
    ]
    body = f"""# NON-BINDING LETTER OF INTENT

**Date:** {date.today().isoformat()}<br>
**To:** {seller_name}<br>
**From:** {buyer_entity}<br>
**Re:** Proposed acquisition of {property_description}

This non-binding Letter of Intent ("LOI") summarizes proposed business terms for discussion. Except for any provision that local counsel expressly rewrites as binding and the parties separately execute, this draft creates no duty to buy, sell, negotiate, or continue negotiations.

## Proposed Terms

1. **Buyer and Seller.** Buyer is **{buyer_entity}**. Seller is **{seller_name}**, subject to confirmation of the record owner and signing authority.
2. **Property.** The proposed acquisition is **{property_description}**, together with the land, improvements, appurtenant rights, leases, contracts, and other assets identified in a definitive purchase and sale agreement.
3. **Purchase Price.** **{_money(price)}**, payable at closing from the earnest-money credit, Buyer equity, and any lender proceeds.
4. **Earnest Money.** **{_money(earnest_money)}** ({earnest_pct:.2f}% of price), deposited with the escrow holder named in the definitive agreement. {go_hard_text}
5. **Due Diligence.** Buyer receives **{dd_days} days** after receipt of a complete diligence package and mutual execution of the purchase agreement to approve or reject the property in Buyer's discretion.
6. **Closing.** Closing is proposed within **{closing_days} days** after the due-diligence period ends, subject to satisfaction of the written closing conditions.
7. **Contingencies.** {"; ".join(contingencies)}.
8. **Financing.** {financing_text}
9. **Condition / As-Is.** The definitive agreement may provide for an as-is acquisition after diligence, subject to negotiated seller representations, title obligations, casualty and condemnation rights, and express surviving remedies.
10. **Assignment.** {assignment_text}
11. **Brokerage.** {brokerage}
12. **Confidentiality.** {confidentiality_text}
13. **Default and Remedies.** No default remedy is created by this non-binding draft. Deposit release, termination, specific-performance, damages, and liability limits must be negotiated in the definitive agreement and reviewed by counsel.
14. **Jurisdiction / Closing Custom.** {jurisdiction_note}
15. **Expiration.** This proposal expires at 5:00 p.m. local property time on **{expiration.isoformat()}** unless extended in a writing signed by Buyer.

## Non-Binding Effect

This LOI is only a basis for preparing a definitive purchase and sale agreement. Neither party is bound to the transaction unless and until that agreement is negotiated, approved, signed, and delivered by both parties.

## Acknowledgment for Negotiation Purposes Only

Buyer: ______________________________  Date: ______________<br>
Seller: _____________________________  Date: ______________

> **Guardrail:** {disclaimer}
"""
    return LoiDraft(
        deal_ref=deal_ref,
        buyer_entity=buyer_entity,
        price=price,
        earnest_money=earnest_money,
        dd_days=dd_days,
        closing_days=closing_days,
        contingencies=contingencies,
        body_markdown=body,
        term_notes=term_notes,
        attorney_review_flags=attorney_review_flags,
        disclaimer=disclaimer,
    )


__all__ = [
    "GENERAL_JURISDICTION_NOTE",
    "JURISDICTION_NOTES",
    "generate_loi",
]
