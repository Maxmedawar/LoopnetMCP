"""Deterministic, deal-specific first-touch outreach coaching."""

from __future__ import annotations

from typing import Literal

from cre_mcp.execution.contacts import find_contact
from cre_mcp.execution.guardrails import execution_guardrail
from cre_mcp.execution.offer import recommend_offer
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import ContactInfo, OutreachDraft

Channel = Literal["call", "email", "letter"]
Angle = Literal["buyer_direct", "via_broker", "absentee_owner", "off_market"]

_CHANNELS = {"call", "email", "letter"}
_ANGLES = {"buyer_direct", "via_broker", "absentee_owner", "off_market"}


def _currency(value: float | None) -> str:
    return f"${value:,.0f}" if value is not None else "a diligence-supported price"


def _property(ctx: DealContext) -> str:
    listing = ctx.listing
    return f"{listing.name} at {listing.address}, {listing.city}, {listing.state}"


def _default_angle(contact: ContactInfo) -> Angle:
    if contact.broker is not None:
        return "via_broker"
    if contact.owner_mailing:
        return "absentee_owner"
    return "buyer_direct"


def _recipient(contact: ContactInfo, angle: Angle) -> str:
    if angle == "via_broker" and contact.broker and contact.broker.name:
        return contact.broker.name
    if contact.owner_name:
        return contact.owner_name
    if contact.registered_agent:
        return contact.registered_agent.name
    return "Property owner or representative"


def _opener(ctx: DealContext, recipient: str, angle: Angle) -> str:
    property_label = _property(ctx)
    templates = {
        "buyer_direct": (
            f"Hello {recipient} — I am evaluating {property_label} as a direct buyer "
            "and wanted to start a straightforward conversation about fit and terms."
        ),
        "via_broker": (
            f"Hello {recipient} — I am reviewing your listing for {property_label} "
            "and would like to coordinate through you on diligence and seller priorities."
        ),
        "absentee_owner": (
            f"Hello {recipient} — public assessor records identify your ownership of "
            f"{property_label}. I am reaching out directly to ask whether a clean sale "
            "would be useful to you."
        ),
        "off_market": (
            f"Hello {recipient} — I am looking to acquire property in {ctx.listing.city} "
            f"and {property_label} fits the profile. I am asking privately whether you "
            "would consider an off-market conversation."
        ),
    }
    return templates[angle]


def _value_hook(ctx: DealContext, open_price: float | None, target_price: float | None) -> str:
    facts: list[str] = []
    if ctx.listing.noi_usd is not None:
        facts.append(f"reported NOI of ${ctx.listing.noi_usd:,.0f}")
    if ctx.facts and ctx.facts.lease_years_remaining is not None:
        facts.append(f"about {ctx.facts.lease_years_remaining:g} lease years remaining")
    if ctx.facts and ctx.facts.tenant_name:
        facts.append(f"the {ctx.facts.tenant_name} tenancy")
    if ctx.listing.size_sqft_num is not None:
        facts.append(f"roughly {ctx.listing.size_sqft_num:,.0f} square feet")
    basis = ", ".join(facts[:3]) or "the available listing and public-record facts"
    return (
        f"I have reviewed {basis}. Subject to leases, title, physical diligence, and "
        f"financing, my current conversation range opens near {_currency(open_price)} "
        f"and centers near {_currency(target_price)}; I am not asking anyone to rely on "
        "that range before the underlying records are confirmed."
    )


def _ask(ctx: DealContext, angle: Angle) -> str:
    if angle == "via_broker":
        return (
            "Could you share the current rent roll or lease, trailing operating facts, "
            "seller timing, and the process for submitting a non-binding indication?"
        )
    if angle == "off_market":
        return (
            "Would you be open to a brief confidential call to discuss timing, price "
            "expectations, and whether a direct transaction is worth exploring?"
        )
    return (
        "Would you be open to a 15-minute call to discuss the property's current "
        "operations, your timing, and a non-binding path to terms?"
    )


def _objections(target_price: float | None, walk_price: float | None) -> list[str]:
    return [
        (
            "If they say the price is too low: ‘I understand. My current target is "
            f"{_currency(target_price)}, with a modeled ceiling near {_currency(walk_price)} "
            "only if the NOI, leases, condition, and financing verify. What facts support "
            "the seller's number?’"
        ),
        (
            "If they want proof of seriousness: ‘I can provide buyer/entity details and "
            "coordinate lender evidence appropriate to the stage, after we confirm the "
            "basic economics and confidentiality expectations.’"
        ),
        (
            "If they demand speed or non-refundable money: ‘I can work toward an efficient "
            "timeline, but deposit risk follows completed title, lease, physical, and "
            "financing diligence—not day one.’"
        ),
    ]


def _render(
    channel: Channel,
    *,
    recipient: str,
    subject: str,
    opener: str,
    value_hook: str,
    ask: str,
    objection_lines: list[str],
    guardrail: str,
) -> str:
    if channel == "call":
        content = "\n\n".join(
            [
                f"CALL OPENER\n{opener}",
                f"VALUE HOOK\n{value_hook}",
                f"ASK\n{ask}",
                "OBJECTION COACHING\n" + "\n".join(f"- {line}" for line in objection_lines),
                "CLOSE\nThank you. I will summarize any next step in writing and keep it non-binding until reviewed.",
            ]
        )
    else:
        greeting = f"Dear {recipient},"
        signoff = "Sincerely,\n[Buyer name]\n[Buyer entity]\n[Phone] | [Email]"
        label = "EMAIL" if channel == "email" else "LETTER"
        content = "\n\n".join(
            [
                f"{label} SUBJECT: {subject}",
                greeting,
                opener,
                value_hook,
                ask,
                "If useful, I am happy to document the next step as a non-binding indication of interest.",
                signoff,
            ]
        )
    return f"{content}\n\n{guardrail}"


async def draft_outreach(
    ctx: DealContext,
    channel: Channel,
    angle: Angle | None = None,
    *,
    contact: ContactInfo | None = None,
) -> OutreachDraft:
    """Return a complete deterministic first-touch draft with novice guardrails."""
    if channel not in _CHANNELS:
        raise ValueError("channel must be one of: call, email, letter")
    contact = contact or await find_contact(ctx)
    selected_angle = angle or _default_angle(contact)
    if selected_angle not in _ANGLES:
        raise ValueError(
            "angle must be one of: buyer_direct, via_broker, absentee_owner, off_market"
        )
    recipient = _recipient(contact, selected_angle)
    offer = recommend_offer(ctx)
    opener = _opener(ctx, recipient, selected_angle)
    value_hook = _value_hook(ctx, offer.open_price, offer.target_price)
    ask = _ask(ctx, selected_angle)
    objections = _objections(offer.target_price, offer.walk_price)
    subject = f"Non-binding acquisition conversation — {ctx.listing.address}"
    guardrail = execution_guardrail(
        "confirm the recipient and contact details before outreach, personalize only "
        "claims you can substantiate, confirm financing next, and have CRE counsel "
        "review any proposed terms."
    )
    return OutreachDraft(
        deal_ref=f"{ctx.listing.source}:{ctx.listing.source_id}",
        channel=channel,
        angle=selected_angle,
        recipient=recipient,
        subject=None if channel == "call" else subject,
        opener=opener,
        value_hook=value_hook,
        ask=ask,
        objection_lines=objections,
        script=_render(
            channel,
            recipient=recipient,
            subject=subject,
            opener=opener,
            value_hook=value_hook,
            ask=ask,
            objection_lines=objections,
            guardrail=guardrail,
        ),
        guardrail=guardrail,
    )


__all__ = ["draft_outreach"]
