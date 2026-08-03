"""Deterministic securities-document skeletons for attorney completion."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from cre_mcp.capital.guardrails import (
    ANTI_FRAUD_WARNING,
    reject_unsubstantiated_performance_claims,
)
from cre_mcp.execution.guardrails import capital_guardrail
from cre_mcp.models.capital import CapitalDraft
from cre_mcp.models.deals import DealContext

RISK_FACTORS = [
    "The investment is speculative and illiquid, with possible total loss of invested capital.",
    "Real-estate values, rents, occupancy, expenses, interest rates, financing, and exit liquidity may differ materially from assumptions.",
    "Leverage can magnify losses and may lead to foreclosure, capital calls, or loss of invested capital.",
    "The sponsor/manager may have conflicts involving fees, affiliates, allocation of opportunities, financing, and property management.",
    "Cash distributions, refinance proceeds, sale timing, and tax treatment are uncertain and may be suspended.",
    "Interests are restricted securities with no public market and limited transfer rights.",
    "Offering-exemption, bad-actor, broker-dealer, Investment Company Act, ERISA, tax, and state-law requirements require counsel review.",
]


def _mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


def _deal_terms(deal: DealContext | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(deal, DealContext):
        listing = deal.listing
        return {
            "deal_ref": f"{listing.source}:{listing.source_id}",
            "property_name": listing.name,
            "property_address": ", ".join(
                part
                for part in (listing.address, listing.city, listing.state, listing.zip_code)
                if part
            ),
            "property_type": listing.property_type,
            "asking_price": listing.price_usd,
            "noi": (
                deal.underwriting.noi
                if deal.underwriting is not None
                else listing.noi_usd
            ),
            "cap_rate_pct": listing.cap_rate_pct,
        }
    values = dict(deal)
    listing = values.get("listing")
    if isinstance(listing, Mapping):
        combined = {**dict(listing), **values}
    else:
        combined = values
    source = combined.get("source")
    source_id = combined.get("source_id")
    deal_ref = combined.get("deal_ref") or (
        f"{source}:{source_id}" if source and source_id else "UNASSIGNED DEAL"
    )
    return {
        "deal_ref": deal_ref,
        "property_name": combined.get("property_name") or combined.get("name"),
        "property_address": combined.get("property_address") or combined.get("address"),
        "property_type": combined.get("property_type"),
        "asking_price": combined.get("asking_price") or combined.get("price_usd") or combined.get("price"),
        "noi": combined.get("noi") or combined.get("noi_usd"),
        "cap_rate_pct": combined.get("cap_rate_pct") or combined.get("cap_rate"),
    }


def _draft_gate(document: str) -> str:
    return capital_guardrail(
        f"Do not circulate or rely on this {document} skeleton until counsel verifies every "
        "fact, omission, risk, exemption condition, filing, legend, and signature block."
    )


def draft_ppm(
    deal: DealContext | Mapping[str, Any],
    structure: Mapping[str, Any],
) -> CapitalDraft:
    """Produce a facts-only PPM skeleton with risks and attorney placeholders."""
    terms = _deal_terms(deal)
    offering = _mapping(structure)
    reject_unsubstantiated_performance_claims(terms, offering)
    issuer = str(offering.get("issuer_name") or "[ISSUER LEGAL NAME]")
    exemption = str(offering.get("exemption") or offering.get("mode") or "[506(b) OR 506(c)]")
    target_raise = offering.get("target_raise") or "[AMOUNT]"
    minimum = offering.get("minimum_investment") or "[AMOUNT]"
    pref = offering.get("pref", offering.get("preferred_return", "[RATE]"))
    promote = offering.get("gp_promote", offering.get("promote", "[RATE]"))
    body = f"""# DRAFT — ATTORNEY REVIEW REQUIRED

## PRIVATE PLACEMENT MEMORANDUM SKELETON

**Issuer:** {issuer}
**Proposed exemption:** Regulation D Rule {exemption} — counsel must select and document
**Deal reference:** {terms['deal_ref']}
**Property:** {terms['property_name'] or '[PROPERTY]'}, {terms['property_address'] or '[ADDRESS]'}
**Property type:** {terms['property_type'] or '[TYPE]'}

## Offering terms — unverified draft

- Target raise: {target_raise}
- Minimum subscription: {minimum}
- Preferred-return scenario: {pref}
- GP promote/carry scenario: {promote}
- Transferability: restricted securities; no public market is assumed
- Use of proceeds: acquisition, closing costs, reserves, financing costs, and disclosed fees — complete schedule required

## Property and underwriting facts to verify

- Asking/acquisition price: {terms['asking_price']}
- Current NOI input: {terms['noi']}
- Current cap-rate input: {terms['cap_rate_pct']}
- Attach source documents, underwriting, debt terms, environmental/property reports, leases, and all material updates.

## Distribution waterfall

Insert the attorney- and CPA-approved operating agreement waterfall. Every preferred return,
IRR, equity multiple, sale value, refinance, and distribution is a scenario dependent on actual
performance and available cash; no outcome is promised.

## Risk factors

{chr(10).join(f'- {item}' for item in RISK_FACTORS)}

## Conflicts, fees, and compensation

Disclose every sponsor/manager/acquisition/disposition/refinance/property-management/financing
fee, affiliate relationship, promote, reimbursement, co-investment, and allocation conflict.

## Investor suitability and subscription process

Counsel must supply the chosen-exemption questionnaire, investor representations, verification
steps where applicable, bad-actor questionnaires, AML/source-of-funds process, signatures, and
state legends. No subscription or funds may be accepted before the hard gate is cleared.

## Securities, tax, and filing notices

Interests have not been registered. Counsel must determine exemption availability, Form D timing,
state blue-sky notices/fees, transfer restrictions, broker-dealer issues, and required legends.
A CPA/tax attorney must review entity, allocations, basis, depreciation, UBTI/ECI, and reporting.

## HARD GATE

{_draft_gate('PPM')}
"""
    return CapitalDraft(
        document_type="PPM",
        title=f"DRAFT PPM — {issuer}",
        body_markdown=body,
        data={"deal": terms, "offering": offering},
        risk_factors=list(RISK_FACTORS),
        anti_fraud_warning=ANTI_FRAUD_WARNING,
        guardrail=_draft_gate("PPM"),
    )


def draft_subscription(
    issuer: Mapping[str, Any],
    offering: Mapping[str, Any],
    investor: Mapping[str, Any] | None = None,
) -> CapitalDraft:
    """Produce a subscription-agreement/questionnaire skeleton for counsel."""
    issuer_data = _mapping(issuer)
    offering_data = _mapping(offering)
    investor_data = _mapping(investor)
    reject_unsubstantiated_performance_claims(issuer_data, offering_data, investor_data)
    issuer_name = str(issuer_data.get("name") or "[ISSUER LEGAL NAME]")
    body = f"""# DRAFT — ATTORNEY REVIEW REQUIRED

## SUBSCRIPTION AGREEMENT + INVESTOR QUESTIONNAIRE SKELETON

**Issuer:** {issuer_name}
**Investor:** {investor_data.get('name') or '[INVESTOR LEGAL NAME]'}
**Proposed subscription:** {investor_data.get('amount') or '[AMOUNT]'}

Counsel must insert the securities description, price, acceptance mechanics, escrow/funding
instructions, representations, restricted-security legend, indemnities, transfer limits,
governing law, e-signature terms, and complete accredited/sophistication questionnaire.

The investor must acknowledge receipt and review of final disclosure documents, material risks,
fees/conflicts, illiquidity, possible total loss, lack of any promised outcome, and opportunity
to ask questions. The issuer must separately document the selected exemption's eligibility and
verification standard. This draft does not accept a subscription or authorize receipt of funds.

## HARD GATE

{_draft_gate('subscription agreement')}
"""
    return CapitalDraft(
        document_type="SUBSCRIPTION",
        title=f"DRAFT Subscription — {issuer_name}",
        body_markdown=body,
        data={"issuer": issuer_data, "offering": offering_data, "investor": investor_data},
        risk_factors=list(RISK_FACTORS),
        anti_fraud_warning=ANTI_FRAUD_WARNING,
        guardrail=_draft_gate("subscription agreement"),
    )


def draft_form_d(
    issuer: Mapping[str, Any],
    offering: Mapping[str, Any],
) -> CapitalDraft:
    """Produce a Form D intake data set, not an EDGAR filing."""
    issuer_data = _mapping(issuer)
    offering_data = _mapping(offering)
    reject_unsubstantiated_performance_claims(issuer_data, offering_data)
    issuer_name = str(issuer_data.get("name") or "[ISSUER LEGAL NAME]")
    first_sale = offering_data.get("first_sale_date")
    deadline = None
    if first_sale:
        try:
            first_sale_date = date.fromisoformat(str(first_sale))
        except ValueError as exc:
            raise ValueError("first_sale_date must be YYYY-MM-DD") from exc
        deadline = (first_sale_date + timedelta(days=15)).isoformat()
    data = {
        "issuer_name": issuer_name,
        "issuer_jurisdiction": issuer_data.get("jurisdiction") or issuer_data.get("state"),
        "issuer_address": issuer_data.get("address"),
        "year_of_incorporation": issuer_data.get("year_of_incorporation"),
        "entity_type": issuer_data.get("entity_type"),
        "related_persons": issuer_data.get("related_persons", []),
        "industry_group": offering_data.get("industry_group", "Commercial Real Estate"),
        "exemption": offering_data.get("exemption") or offering_data.get("mode"),
        "first_sale_date": first_sale,
        "form_d_due_date_estimate": deadline,
        "duration_over_one_year": offering_data.get("duration_over_one_year"),
        "security_type": offering_data.get("security_type", "LLC membership interests"),
        "minimum_investment": offering_data.get("minimum_investment"),
        "total_offering_amount": offering_data.get("total_offering_amount") or offering_data.get("target_raise"),
        "amount_sold": offering_data.get("amount_sold", 0),
        "remaining_to_be_sold": offering_data.get("remaining_to_be_sold"),
        "investor_counts": offering_data.get("investor_counts", {}),
        "sales_compensation": offering_data.get("sales_compensation", []),
        "use_of_proceeds": offering_data.get("use_of_proceeds"),
    }
    body = f"""# DRAFT — ATTORNEY REVIEW REQUIRED

## FORM D INTAKE DATA SET — NOT FILED

**Issuer:** {issuer_name}
**Proposed exemption:** {data['exemption'] or '[506(b) OR 506(c)]'}
**First sale date:** {first_sale or '[NOT YET OCCURRED]'}
**Estimated federal notice due date:** {deadline or '[15 DAYS AFTER FIRST SALE — COUNSEL TO CALENDAR]'}

This is only an organizer for counsel and the EDGAR filer. It is not Form D, has not been filed,
does not establish an exemption, and does not replace state blue-sky notices or fees. Counsel must
verify every issuer, related-person, offering, investor, compensation, proceeds, and first-sale item.

## HARD GATE

{_draft_gate('Form D data set')}
"""
    return CapitalDraft(
        document_type="FORM_D",
        title=f"DRAFT Form D Intake — {issuer_name}",
        body_markdown=body,
        data=data,
        risk_factors=[],
        anti_fraud_warning=ANTI_FRAUD_WARNING,
        guardrail=_draft_gate("Form D data set"),
    )


__all__ = ["RISK_FACTORS", "draft_form_d", "draft_ppm", "draft_subscription"]
