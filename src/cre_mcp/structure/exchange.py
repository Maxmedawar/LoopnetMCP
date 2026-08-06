"""Persistent, clock-aware 1031 exchange manager and boot/basis estimator."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from cre_mcp.deals.store import get_deal_store
from cre_mcp.execution.guardrails import structure_guardrail
from cre_mcp.models.structure import BootBasisResult, Exchange, ExchangeReplacement

IDENTIFICATION_DAYS = 45
EXCHANGE_DAYS = 180
THREE_PROPERTY_LIMIT = 3
TWO_HUNDRED_PERCENT = 2.0
NINETY_FIVE_PERCENT = 0.95

QI_BEFORE_CLOSING_GATE = (
    "HARD GATE — Engage a Qualified Intermediary BEFORE the relinquished property closes — "
    "if you touch or control the proceeds, the exchange is dead. Have the QI execute the "
    "written exchange agreement before closing."
)
CPA_FORM_8824_GATE = (
    "HARD GATE — A CPA must file Form 8824 and confirm adjusted basis, depreciation, debt, "
    "boot, related-party rules, and the actual tax-return deadline."
)
DEADLINE_CAVEAT = (
    "The displayed 180-day date is the statutory outside date. The actual receipt deadline "
    "is the EARLIER of that date or the due date (including extensions) of the federal return "
    "for the transfer year; confirm and calendar it with the QI and CPA."
)
EXCHANGE_DISCLAIMER = structure_guardrail(
    "This tracker is not a qualified intermediary, tax return, identification notice, or legal "
    "opinion. The QI, CPA, and exchange attorney must approve every irreversible step."
)


def _date(value: date | str, label: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)") from exc


def _today(value: date | str | None) -> date:
    return date.today() if value is None else _date(value, "as_of")


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _deal_value(record: dict[str, Any] | None) -> float | None:
    if record is None:
        return None
    listing = record.get("listing")
    if not isinstance(listing, dict):
        return None
    for key in ("price_usd", "price"):
        value = _number(listing.get(key))
        if value is not None and value > 0:
            return value
    return None


def _rule_status(
    replacements: list[ExchangeReplacement],
    relinquished_value: float | None,
) -> str:
    count = len(replacements)
    if count <= THREE_PROPERTY_LIMIT:
        return (
            f"3-property rule: {count}/{THREE_PROPERTY_LIMIT} identified; FMV is unrestricted "
            "under this rule. A signed, unambiguous identification must reach the permitted "
            "recipient by day 45."
        )
    total = sum(item.value or 0.0 for item in replacements)
    limit = (relinquished_value or 0.0) * TWO_HUNDRED_PERCENT
    return (
        f"200% rule: {count} properties with aggregate identified FMV ${total:,.0f} versus "
        f"the ${limit:,.0f} ceiling. The 95% rule is only a narrow actual-receipt exception "
        "requiring receipt of at least 95% of all identified FMV by the exchange deadline."
    )


async def _exchange_from_record(
    record: dict[str, Any],
    *,
    store: Any,
    as_of: date,
) -> Exchange:
    close_date = _date(record["relinquished_close_date"], "relinquished_close_date")
    identification_deadline = _date(record["identification_deadline"], "identification_deadline")
    exchange_deadline = _date(record["exchange_deadline"], "exchange_deadline")
    replacements = [
        ExchangeReplacement.model_validate(item)
        for item in record.get("replacements", [])
    ]
    identification_locked = as_of > identification_deadline
    if as_of < close_date:
        status = "planned"
        next_action = (
            "Engage and contract with the QI before closing; confirm taxpayer/title identity, "
            "then prepare the written exchange and assignment documents."
        )
    elif not identification_locked:
        status = "identification_open"
        next_action = (
            "Deliver a signed, unambiguous replacement-property identification to the QI or "
            "another permitted recipient before the day-45 deadline; do not send it only to yourself."
        )
    elif as_of <= exchange_deadline:
        status = "identification_locked"
        next_action = (
            "The identification list is locked. Close on qualifying identified property before "
            "the earlier controlling receipt deadline and give the full file to the CPA."
        )
    else:
        status = "expired"
        next_action = (
            "The statutory exchange date has passed. Do not assume deferral; have the QI and CPA "
            "determine what qualified and report the transaction."
        )
    if "relinquished_value" in record:
        relinquished_value = _number(record.get("relinquished_value"))
    else:
        relinquished = await store.get_deal(str(record["relinquished_deal_id"]))
        relinquished_value = _deal_value(relinquished)
    return Exchange(
        exchange_id=record["exchange_id"],
        relinquished_deal_id=str(record["relinquished_deal_id"]),
        relinquished_close_date=close_date,
        identification_deadline=identification_deadline,
        exchange_deadline=exchange_deadline,
        days_to_identification_deadline=max((identification_deadline - as_of).days, 0),
        days_to_exchange_deadline=max((exchange_deadline - as_of).days, 0),
        identification_locked=identification_locked,
        status=status,
        replacements=replacements,
        identification_rule_status=_rule_status(replacements, relinquished_value),
        next_action=next_action,
        deadline_caveat=DEADLINE_CAVEAT,
        qi_gate=QI_BEFORE_CLOSING_GATE,
        cpa_gate=CPA_FORM_8824_GATE,
        disclaimer=EXCHANGE_DISCLAIMER,
    )


async def start_exchange(
    relinquished_deal_id: str,
    relinquished_close_date: date | str,
    *,
    store: Any | None = None,
    as_of: date | str | None = None,
) -> Exchange:
    """Persist a 45/180-day exchange clock for an already-saved relinquished deal."""
    active_store = store or get_deal_store()
    close_date = _date(relinquished_close_date, "relinquished_close_date")
    identification_deadline = close_date + timedelta(days=IDENTIFICATION_DAYS)
    exchange_deadline = close_date + timedelta(days=EXCHANGE_DAYS)
    create_result = getattr(active_store, "create_exchange_result", None)
    if callable(create_result):
        record = await create_result(
            relinquished_deal_id,
            close_date.isoformat(),
            identification_deadline.isoformat(),
            exchange_deadline.isoformat(),
        )
        if record is None:
            raise ValueError(f"unknown relinquished deal_id: {relinquished_deal_id}")
    else:
        if await active_store.get_deal(relinquished_deal_id) is None:
            raise ValueError(f"unknown relinquished deal_id: {relinquished_deal_id}")
        exchange_id = await active_store.create_exchange(
            relinquished_deal_id,
            close_date.isoformat(),
            identification_deadline.isoformat(),
            exchange_deadline.isoformat(),
        )
        if exchange_id is None:
            raise RuntimeError("exchange could not be persisted")
        record = await active_store.get_exchange_record(exchange_id)
        if record is None:
            raise RuntimeError("persisted exchange could not be read")
    return await _exchange_from_record(record, store=active_store, as_of=_today(as_of))


async def exchange_status(
    exchange_id: int | str,
    *,
    store: Any | None = None,
    as_of: date | str | None = None,
) -> Exchange:
    """Return current countdown, locked/open state, IDs, gates, and next action."""
    active_store = store or get_deal_store()
    record = await active_store.get_exchange_record(exchange_id)
    if record is None:
        raise ValueError(f"unknown exchange_id: {exchange_id}")
    return await _exchange_from_record(record, store=active_store, as_of=_today(as_of))


async def identify_replacement(
    exchange_id: int | str,
    deal_id: str,
    *,
    store: Any | None = None,
    as_of: date | str | None = None,
) -> Exchange:
    """Add a candidate only while the ID window/rule set can be verified."""
    active_store = store or get_deal_store()
    current_date = _today(as_of)
    identify_result = getattr(
        active_store,
        "identify_exchange_replacement_result",
        None,
    )
    if callable(identify_result):
        record = await identify_result(
            exchange_id,
            deal_id,
            current_date.isoformat(),
        )
        return await _exchange_from_record(
            record,
            store=active_store,
            as_of=current_date,
        )
    record = await active_store.get_exchange_record(exchange_id)
    if record is None:
        raise ValueError(f"unknown exchange_id: {exchange_id}")
    identification_deadline = _date(record["identification_deadline"], "identification_deadline")
    if current_date > identification_deadline:
        raise ValueError(
            f"identification is locked after day 45 ({identification_deadline.isoformat()})"
        )
    if deal_id == record["relinquished_deal_id"]:
        raise ValueError("replacement deal cannot be the relinquished deal")
    replacement = await active_store.get_deal(deal_id)
    if replacement is None:
        raise ValueError(f"unknown replacement deal_id: {deal_id}")
    existing = {
        str(item["deal_id"])
        for item in record.get("replacements", [])
        if isinstance(item, dict)
    }
    if deal_id in existing:
        return await exchange_status(
            exchange_id,
            store=active_store,
            as_of=current_date,
        )

    current = [
        ExchangeReplacement.model_validate(item)
        for item in record.get("replacements", [])
    ]
    candidate = ExchangeReplacement(
        deal_id=deal_id,
        value=_deal_value(replacement),
        identified_at=current_date,
    )
    proposed = [*current, candidate]
    if len(proposed) > THREE_PROPERTY_LIMIT:
        relinquished = await active_store.get_deal(str(record["relinquished_deal_id"]))
        relinquished_value = _deal_value(relinquished)
        values = [item.value for item in proposed]
        if relinquished_value is None or any(value is None for value in values):
            raise ValueError(
                "more than three properties requires verified FMV for the relinquished and every "
                "replacement property to test the 200% rule"
            )
        total = sum(float(value) for value in values if value is not None)
        limit = relinquished_value * TWO_HUNDRED_PERCENT
        if total > limit:
            received_needed = total * NINETY_FIVE_PERCENT
            raise ValueError(
                f"identification rejected: {len(proposed)} properties total ${total:,.0f}, "
                f"exceeding the 200% ceiling of ${limit:,.0f}. The 95% rule would require actual "
                f"receipt of at least ${received_needed:,.0f} of identified FMV; this tracker will "
                "not treat that narrow after-the-fact exception as pre-approved. Ask the QI/tax attorney."
            )
    if not await active_store.add_exchange_replacement(
        exchange_id,
        deal_id,
        candidate.value,
        current_date.isoformat(),
    ):
        raise RuntimeError("replacement identification could not be persisted")
    return await exchange_status(exchange_id, store=active_store, as_of=current_date)


def _required_amount(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
    label: str,
) -> float:
    for key in keys:
        if key in values and (number := _number(values[key])) is not None:
            if number < 0:
                raise ValueError(f"{label} cannot be negative")
            return number
    raise ValueError(f"{label} is required")


def _optional_amount(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
    label: str,
) -> float:
    for key in keys:
        if key in values and values[key] is not None:
            number = _number(values[key])
            if number is None or number < 0:
                raise ValueError(f"{label} must be a non-negative number")
            return number
    return 0.0


def _money(value: float) -> float:
    return round(max(value, 0.0), 2)


def calc_boot_basis(
    relinquished: Mapping[str, Any],
    replacement: Mapping[str, Any],
) -> BootBasisResult:
    """Estimate cash/debt boot and replacement basis under explicit simplifications."""
    relinquished_price = _required_amount(
        relinquished,
        ("sale_price", "price", "value", "fair_market_value"),
        "relinquished price",
    )
    relinquished_basis = _required_amount(
        relinquished,
        ("adjusted_basis", "basis"),
        "relinquished adjusted basis",
    )
    relinquished_debt = _optional_amount(
        relinquished,
        ("debt", "mortgage", "loan_balance"),
        "relinquished debt",
    )
    replacement_price = _required_amount(
        replacement,
        ("purchase_price", "price", "value", "fair_market_value"),
        "replacement price",
    )
    replacement_debt = _optional_amount(
        replacement,
        ("debt", "mortgage", "loan_balance"),
        "replacement debt",
    )
    if relinquished_basis > relinquished_price:
        realized_gain = 0.0
    else:
        realized_gain = relinquished_price - relinquished_basis
    relinquished_equity = relinquished_price - relinquished_debt
    replacement_equity = replacement_price - replacement_debt
    cash_boot = max(relinquished_equity - replacement_equity, 0.0)
    additional_cash = max(replacement_equity - relinquished_equity, 0.0)
    debt_boot = max(
        relinquished_debt - replacement_debt - additional_cash,
        0.0,
    )
    estimated_boot = cash_boot + debt_boot
    taxable_boot = min(estimated_boot, realized_gain)
    deferred_gain = max(realized_gain - taxable_boot, 0.0)
    carryover_basis = max(replacement_price - deferred_gain, 0.0)
    return BootBasisResult(
        relinquished_price=_money(relinquished_price),
        relinquished_adjusted_basis=_money(relinquished_basis),
        relinquished_debt=_money(relinquished_debt),
        replacement_price=_money(replacement_price),
        replacement_debt=_money(replacement_debt),
        relinquished_equity=round(relinquished_equity, 2),
        replacement_equity=round(replacement_equity, 2),
        realized_gain=_money(realized_gain),
        cash_boot=_money(cash_boot),
        debt_boot=_money(debt_boot),
        estimated_boot=_money(estimated_boot),
        estimated_taxable_boot=_money(taxable_boot),
        taxable_boot_flag=taxable_boot > 0,
        deferred_gain=_money(deferred_gain),
        estimated_carryover_basis=_money(carryover_basis),
        replacement_value_test_passed=replacement_price >= relinquished_price,
        debt_replaced_or_cash_offset_test_passed=(
            replacement_debt + additional_cash >= relinquished_debt
        ),
        assumptions=[
            "No selling costs, exchange expenses, non-real-property consideration, depreciation recapture, or related-party adjustments are modeled.",
            "Cash boot estimates unreinvested net equity; debt boot estimates net liability relief not offset by additional cash invested.",
            "Recognized taxable boot is capped at modeled realized gain; actual Form 8824 treatment can differ.",
            "Estimated carryover basis equals replacement price minus modeled deferred gain.",
        ],
        qi_gate=QI_BEFORE_CLOSING_GATE,
        cpa_gate=CPA_FORM_8824_GATE,
        disclaimer=EXCHANGE_DISCLAIMER,
    )


__all__ = [
    "CPA_FORM_8824_GATE",
    "DEADLINE_CAVEAT",
    "EXCHANGE_DAYS",
    "IDENTIFICATION_DAYS",
    "NINETY_FIVE_PERCENT",
    "QI_BEFORE_CLOSING_GATE",
    "THREE_PROPERTY_LIMIT",
    "TWO_HUNDRED_PERCENT",
    "calc_boot_basis",
    "exchange_status",
    "identify_replacement",
    "start_exchange",
]
