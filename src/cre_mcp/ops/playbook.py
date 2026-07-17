"""Asset-aware post-close operating calendar with durable reminders."""

from __future__ import annotations

import calendar
import logging
import math
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from cre_mcp.deals.store import DealStore, get_deal_store
from cre_mcp.execution.guardrails import execution_guardrail
from cre_mcp.models.deals import DealContext
from cre_mcp.models.ops import OperatingItem, OperatingPlaybook

logger = logging.getLogger(__name__)


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _add_months(value: date, months: int) -> date:
    total = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _ownership_start(ctx: DealContext, as_of: date | str | None) -> tuple[date, str]:
    raw = ctx.listing.raw
    for key in ("acquisition_date", "closing_date", "close_date", "placed_in_service_date"):
        parsed = _date(raw.get(key))
        if parsed is not None:
            return parsed, f"listing raw {key}"
    parsed_as_of = _date(as_of)
    if as_of is not None and parsed_as_of is None:
        raise ValueError("as_of must be YYYY-MM-DD")
    return parsed_as_of or date.today(), "generation date fallback; replace with actual closing date"


def _item(
    key: str,
    category: str,
    label: str,
    timing: str,
    why: str,
    action: str,
    owner: str,
    *,
    event_date: date | None,
    reminder_days_before: list[int],
    date_source: str,
) -> OperatingItem:
    return OperatingItem(
        key=key,
        category=category,  # type: ignore[arg-type]
        label=label,
        timing=timing,
        why=why,
        action=action,
        owner=owner,
        event_date=event_date,
        reminder_days_before=reminder_days_before,
        date_source=date_source,
    )


def _month_one(start: date, source: str) -> list[OperatingItem]:
    return [
        _item(
            "month1_rent_ach",
            "month_one",
            "Take control of rent collection and ACH",
            "Day 1",
            "Missing the first rent cycle creates avoidable cash and tenant confusion.",
            "Reconcile the rent roll to leases, issue counsel-approved payment instructions, test ACH, and prohibit email-only wire changes.",
            "Asset manager + property manager + bank",
            event_date=start,
            reminder_days_before=[0],
            date_source=source,
        ),
        _item(
            "month1_tenant_w9_estoppel",
            "month_one",
            "Collect tenant W-9s and hand estoppels into actuals",
            "Days 1–5",
            "Closing estoppels and lease abstracts must become the opening tenant ledger, not disappear into a folder.",
            "Collect current W-9/contact/remittance data; compare each estoppel, lease, deposit, CAM balance, and option to the opening ledger; escalate discrepancies to counsel.",
            "Property manager + bookkeeper + CRE attorney",
            event_date=start + timedelta(days=5),
            reminder_days_before=[3, 0],
            date_source=source,
        ),
        _item(
            "month1_bookkeeping",
            "month_one",
            "Open entity books and controls",
            "Week 1",
            "Clean entity-level books preserve lender reporting, partner reporting, tax basis, and fraud controls.",
            "Create the chart of accounts, opening balance sheet, capital/debt ledgers, approval limits, document retention, and monthly close checklist.",
            "Property accountant + CPA",
            event_date=start + timedelta(days=7),
            reminder_days_before=[3, 0],
            date_source=source,
        ),
        _item(
            "month1_insurance",
            "month_one",
            "Confirm insurance binder and final policy",
            "Days 1–10",
            "A binder can differ from the issued policy; lender, property, liability, flood/wind, loss-payee, and rent-loss requirements must match.",
            "Bind coverage before possession, then reconcile the issued policy, endorsements, deductibles, named insured, lender clauses, and claims contacts.",
            "CRE insurance broker + lender",
            event_date=start + timedelta(days=10),
            reminder_days_before=[5, 0],
            date_source=source,
        ),
        _item(
            "month1_owner_notice",
            "month_one",
            "Send notice-of-new-owner and notice-to-pay letters",
            "Day 1",
            "Tenants need authenticated ownership, management, emergency, payment, and legal-notice instructions without creating wire-fraud exposure.",
            "Have counsel/property management issue state- and lease-compliant notices with independently verifiable payment contacts.",
            "Property manager + CRE attorney",
            event_date=start,
            reminder_days_before=[0],
            date_source=source,
        ),
    ]


def _is_nnn(ctx: DealContext) -> bool:
    facts = ctx.facts
    if facts is not None and (
        facts.strategy_hint == "nnn_retail" or facts.nnn_purity in {"nn", "nnn", "absolute"}
    ):
        return True
    text = " ".join(
        str(value or "").casefold()
        for value in (ctx.listing.property_type, ctx.listing.description, *ctx.listing.highlights)
    )
    return "triple net" in text or "nnn" in text


def _recurring(ctx: DealContext, start: date, source: str) -> list[OperatingItem]:
    items = [
        _item(
            "recurring_tax_reassessment",
            "recurring",
            "Budget for post-sale property-tax REASSESSMENT",
            "First 30 days; then before every assessment/protest deadline",
            "A sale can reset taxable value and erase the seller's historical-tax assumption—the classic Sun Belt underwriting surprise.",
            "Obtain the assessor calendar, model tax at acquisition value, reserve the delta, calendar protest dates, and engage local tax counsel/consultant where material.",
            "Asset manager + property-tax consultant + CPA",
            event_date=start + timedelta(days=30),
            reminder_days_before=[14, 7, 0],
            date_source=source,
        ),
        _item(
            "recurring_insurance_renewal",
            "recurring",
            "Re-market and renew insurance",
            "Begin 90 days before annual renewal",
            "Carrier capacity, catastrophe pricing, valuations, exclusions, and lender requirements change annually.",
            "Update statement of values/loss runs, solicit terms, stress deductibles and rent-loss limits, and obtain lender approval before binding.",
            "CRE insurance broker + lender",
            event_date=_add_months(start, 9),
            reminder_days_before=[30, 14, 7],
            date_source=f"modeled from {source}; replace with actual policy expiration",
        ),
        _item(
            "recurring_monthly_close",
            "recurring",
            "Monthly books, bank reconciliation, and variance review",
            "Monthly by day 15",
            "Fast closes expose rent, expense, covenant, reserve, fraud, and collections problems while they are still fixable.",
            "Close books, reconcile cash/deposits/debt, compare actuals to budget and T-12, update DSCR, and send owner/lender reports.",
            "Property accountant + asset manager",
            event_date=start + timedelta(days=30),
            reminder_days_before=[5, 0],
            date_source=source,
        ),
    ]
    if _is_nnn(ctx):
        items.extend(
            [
                _item(
                    "recurring_nnn_cam",
                    "recurring",
                    "NNN CAM/reconciliation and notice watch",
                    "Monthly accrual; annual lease-calendar reconciliation",
                    "NNN labels do not eliminate caps, exclusions, audit rights, reconciliation deadlines, or landlord administration duties.",
                    "Abstract every CAM/tax/insurance clause, accrue recoveries, retain invoices, deliver budgets/reconciliations/notices on lease deadlines, and track caps/exclusions.",
                    "Property manager + lease accountant + CRE attorney",
                    event_date=_add_months(start, 11),
                    reminder_days_before=[60, 30, 14],
                    date_source=f"modeled annual cycle from {source}; verify each lease",
                ),
                _item(
                    "recurring_nnn_roof_structure",
                    "recurring",
                    "NNN roof/structure responsibility watch",
                    "Quarterly inspection and annual capital plan",
                    "Even absolute-NNN marketing can conflict with lease language, code duties, casualty obligations, or lender reserves.",
                    "Confirm the executed lease allocation, inspect roof/structure/parking systems, document tenant notices, and reserve any landlord responsibility.",
                    "Property manager + engineer + CRE attorney",
                    event_date=_add_months(start, 3),
                    reminder_days_before=[14, 7, 0],
                    date_source=source,
                ),
            ]
        )
    return items


def _explicit_option_dates(raw: Mapping[str, Any]) -> list[tuple[str, date]]:
    candidates = raw.get("lease_option_deadlines", raw.get("option_deadlines", []))
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        candidates = [candidates]
    parsed: list[tuple[str, date]] = []
    for index, item in enumerate(candidates, start=1):
        if isinstance(item, Mapping):
            event_date = _date(item.get("date") or item.get("deadline"))
            label = str(item.get("label") or item.get("option") or f"Lease option {index}")
        else:
            event_date = _date(item)
            label = f"Lease option {index}"
        if event_date is not None:
            parsed.append((label, event_date))
    single = _date(raw.get("option_deadline"))
    if single is not None:
        parsed.append(("Lease option deadline", single))
    return parsed


def _critical_dates(ctx: DealContext, start: date, source: str) -> list[OperatingItem]:
    raw = ctx.listing.raw
    facts = ctx.facts
    items: list[OperatingItem] = []
    expiration = _date(raw.get("lease_expiration_date") or raw.get("lease_expiration"))
    expiration_source = "listing lease_expiration_date"
    years_remaining = facts.lease_years_remaining if facts is not None else None
    if years_remaining is None and ctx.underwriting is not None:
        years_remaining = ctx.underwriting.walt
    if expiration is None and years_remaining is not None and years_remaining > 0:
        expiration = _add_months(start, round(years_remaining * 12))
        expiration_source = (
            f"modeled from {years_remaining:g} years remaining and {source}; verify executed lease"
        )
    if expiration is not None:
        items.append(
            _item(
                "lease_expiration",
                "lease",
                "Lease expiration / WALT endpoint",
                expiration.isoformat(),
                "Lease rollover can dominate value, financing, tenant leverage, and exit timing.",
                "Verify the executed lease, amendments, commencement certificate, options, notice addresses, and exact expiration; begin renewal/re-tenant planning early.",
                "Asset manager + leasing broker + CRE attorney",
                event_date=expiration,
                reminder_days_before=[730, 545, 365, 180, 90],
                date_source=expiration_source,
            )
        )

    option_dates = _explicit_option_dates(raw)
    if not option_dates and expiration is not None:
        option_dates = [("Modeled renewal/option decision window", _add_months(expiration, -12))]
    for index, (label, event_date) in enumerate(option_dates, start=1):
        items.append(
            _item(
                f"lease_option_{index}",
                "lease",
                label,
                event_date.isoformat(),
                "Missed notice windows can eliminate renewal/termination/purchase rights or change negotiating leverage.",
                "Confirm the actual option holder, conditions, notice form/address, deadline, and delivery proof from the executed lease; this modeled date is not legal notice.",
                "Asset manager + CRE attorney",
                event_date=event_date,
                reminder_days_before=[180, 120, 90, 60, 30],
                date_source=(
                    "listing-provided option date"
                    if _explicit_option_dates(raw)
                    else f"modeled 12 months before expiration; verify lease"
                ),
            )
        )

    escalation = facts.rent_escalations if facts is not None else None
    if escalation is not None and escalation > 0:
        first = _date(raw.get("next_rent_escalation_date")) or _add_months(start, 12)
        count = min(max(math.ceil(years_remaining or 5), 1), 10)
        for index in range(count):
            event_date = _add_months(first, index * 12)
            if expiration is not None and event_date >= expiration:
                break
            items.append(
                _item(
                    f"lease_escalation_{index + 1}",
                    "lease",
                    f"Apply/verify modeled {escalation:g}% rent escalation",
                    event_date.isoformat(),
                    "A missed contractual bump directly reduces NOI, value, recoveries, and lender reporting.",
                    "Verify the lease's exact amount, frequency, base, rounding, notice/invoice requirements, and effective date before changing rent.",
                    "Property manager + lease accountant",
                    event_date=event_date,
                    reminder_days_before=[60, 30, 14, 0],
                    date_source=(
                        "listing next_rent_escalation_date"
                        if _date(raw.get("next_rent_escalation_date")) is not None
                        else f"modeled annual anniversary from {source}; verify lease"
                    ),
                )
            )
    return items


def _nudges(ctx: DealContext, start: date, source: str) -> list[OperatingItem]:
    hold_years = 5
    if ctx.underwriting is not None:
        raw_hold = ctx.underwriting.assumptions_used.get("hold_years")
        if isinstance(raw_hold, Mapping) and raw_hold.get("value") is not None:
            try:
                hold_years = max(int(raw_hold["value"]), 1)
            except (TypeError, ValueError):
                pass
    refi_month = min(36, max(12, hold_years * 12 - 24))
    exit_prep_month = max(12, hold_years * 12 - 18)
    return [
        _item(
            "nudge_refi",
            "nudge",
            "Refinance window: rerun DSCR, rates, value, and reserves",
            f"Month {refi_month}",
            "A refi should be driven by value, DSCR, prepayment, maturity, tax, and reinvestment—not a rate headline.",
            "Refresh market_intel, NOI/T-12, appraisal/comps, size_debt, lender terms, prepayment costs, and partner/tax consequences before proceeding.",
            "Asset manager + lender + CPA",
            event_date=_add_months(start, refi_month),
            reminder_days_before=[180, 120, 90],
            date_source=f"modeled from a {hold_years}-year ownership scenario and {source}",
        ),
        _item(
            "nudge_exit_1031",
            "nudge",
            "Start exit/1031 decision before the clock owns you",
            f"Month {exit_prep_month}",
            "Brokerage, lease strategy, capital work, QI selection, taxpayer/title continuity, and replacement sourcing need lead time.",
            "Run analyze_deal/get_comps for current value; consult CPA/attorney/QI before marketing; then call find_deals with the replacement buy-box—never touch sale proceeds.",
            "Owner + broker + CPA + CRE attorney + QI",
            event_date=_add_months(start, exit_prep_month),
            reminder_days_before=[365, 270, 180, 90],
            date_source=f"modeled 18 months before year-{hold_years} exit; replace with actual plan",
        ),
        _item(
            "nudge_next_deal",
            "nudge",
            "Refresh the next-deal buy box",
            "Quarterly and before any refinance/exit",
            "The current asset's actual performance should improve the next acquisition criteria.",
            "Update saved searches and run find_deals using actual cash flow, lender capacity, geography, lease risk, and strategy learned from this asset.",
            "Owner + acquisitions lead",
            event_date=_add_months(start, 3),
            reminder_days_before=[14, 7, 0],
            date_source=source,
        ),
    ]


async def operating_playbook(
    ctx: DealContext,
    *,
    store: DealStore | None = None,
    as_of: date | str | None = None,
) -> OperatingPlaybook:
    """Generate and persist the post-close calendar for one analyzed property."""
    active_store = store or get_deal_store()
    deal_id = DealStore.deal_id_for(ctx.listing)
    if await active_store.get_deal(deal_id) is None:
        saved_id = await active_store.save_deal(ctx.listing)
        if saved_id is not None:
            deal_id = saved_id
    start, start_source = _ownership_start(ctx, as_of)
    month_one = _month_one(start, start_source)
    recurring = _recurring(ctx, start, start_source)
    critical_dates = _critical_dates(ctx, start, start_source)
    nudges = _nudges(ctx, start, start_source)
    all_events = [*month_one, *recurring, *critical_dates, *nudges]
    persisted = await active_store.save_ops_events(
        deal_id,
        [item.model_dump(mode="json") for item in all_events],
    )
    return OperatingPlaybook(
        deal_id=deal_id,
        deal_ref=f"{ctx.listing.source}:{ctx.listing.source_id}",
        property_name=ctx.listing.name,
        ownership_start=start,
        month_one=month_one,
        recurring=recurring,
        critical_dates=critical_dates,
        nudges=nudges,
        persistence_status="saved" if persisted else "unavailable",
        guardrail=execution_guardrail(
            "This calendar is a starting control system, not the lease, tax calendar, legal "
            "notice, accounting policy, or insurance advice. Replace modeled dates with executed "
            "documents and have the property manager, CRE attorney, CPA, lender, and insurance "
            "broker own their respective deadlines."
        ),
    )


__all__ = ["operating_playbook"]
