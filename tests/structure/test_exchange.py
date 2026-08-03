"""1031 clock, identification-rule, persistence, and boot tests."""

from datetime import date, timedelta

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.structure.exchange import (
    CPA_FORM_8824_GATE,
    QI_BEFORE_CLOSING_GATE,
    calc_boot_basis,
    exchange_status,
    identify_replacement,
    start_exchange,
)
from tests.scoring.builders import deal_context


async def _save(store: DealStore, source_id: str, price: float):
    listing = deal_context(source_id=source_id, price=price).listing
    deal_id = await store.save_deal(listing)
    assert deal_id is not None
    return deal_id


@pytest.mark.asyncio
async def test_start_exchange_calculates_45_180_clocks_and_persists(tmp_path):
    path = tmp_path / "exchange.db"
    store = DealStore(path)
    deal_id = await _save(store, "relinquished", 1_000_000)
    close = date(2026, 1, 1)

    started = await start_exchange(deal_id, close, store=store, as_of=close)
    reopened = await exchange_status(
        started.exchange_id,
        store=DealStore(path),
        as_of=close,
    )

    assert started.identification_deadline == date(2026, 2, 15)
    assert started.exchange_deadline == date(2026, 6, 30)
    assert started.days_to_identification_deadline == 45
    assert started.days_to_exchange_deadline == 180
    assert reopened.exchange_id == started.exchange_id
    assert reopened.status == "identification_open"
    assert "EARLIER" in reopened.deadline_caveat
    assert QI_BEFORE_CLOSING_GATE == reopened.qi_gate
    assert "BEFORE the relinquished property closes" in reopened.qi_gate
    assert CPA_FORM_8824_GATE == reopened.cpa_gate
    assert "Form 8824" in reopened.cpa_gate


@pytest.mark.asyncio
async def test_three_property_is_unrestricted_but_fourth_must_pass_200_percent(tmp_path):
    store = DealStore(tmp_path / "exchange.db")
    relinquished = await _save(store, "rel", 1_000_000)
    replacements = [
        await _save(store, "one", 700_000),
        await _save(store, "two", 700_000),
        await _save(store, "three", 700_000),
        await _save(store, "four", 100_000),
    ]
    close = date(2026, 1, 1)
    exchange = await start_exchange(relinquished, close, store=store, as_of=close)
    for deal_id in replacements[:3]:
        exchange = await identify_replacement(
            exchange.exchange_id,
            deal_id,
            store=store,
            as_of=close + timedelta(days=10),
        )

    assert len(exchange.replacements) == 3
    assert "3-property rule: 3/3" in exchange.identification_rule_status
    with pytest.raises(ValueError, match="exceeding the 200% ceiling") as raised:
        await identify_replacement(
            exchange.exchange_id,
            replacements[3],
            store=store,
            as_of=close + timedelta(days=10),
        )
    assert "95% rule" in str(raised.value)
    assert len((await exchange_status(exchange.exchange_id, store=store, as_of=close)).replacements) == 3


@pytest.mark.asyncio
async def test_more_than_three_is_allowed_when_aggregate_is_under_200_percent(tmp_path):
    store = DealStore(tmp_path / "exchange.db")
    relinquished = await _save(store, "rel", 1_000_000)
    replacements = [await _save(store, f"r{index}", 400_000) for index in range(4)]
    close = date(2026, 1, 1)
    exchange = await start_exchange(relinquished, close, store=store, as_of=close)
    for deal_id in replacements:
        exchange = await identify_replacement(
            exchange.exchange_id,
            deal_id,
            store=store,
            as_of=close + timedelta(days=20),
        )

    assert len(exchange.replacements) == 4
    assert "200% rule" in exchange.identification_rule_status
    assert "$1,600,000" in exchange.identification_rule_status


@pytest.mark.asyncio
async def test_identification_locks_after_day_45(tmp_path):
    store = DealStore(tmp_path / "exchange.db")
    relinquished = await _save(store, "rel", 1_000_000)
    replacement = await _save(store, "replacement", 1_100_000)
    close = date(2026, 1, 1)
    exchange = await start_exchange(relinquished, close, store=store, as_of=close)

    with pytest.raises(ValueError, match="locked after day 45"):
        await identify_replacement(
            exchange.exchange_id,
            replacement,
            store=store,
            as_of=close + timedelta(days=46),
        )
    locked = await exchange_status(
        exchange.exchange_id,
        store=store,
        as_of=close + timedelta(days=46),
    )
    assert locked.identification_locked is True
    assert locked.status == "identification_locked"


def test_boot_and_carryover_basis_when_replacement_is_smaller():
    result = calc_boot_basis(
        {"sale_price": 1_000_000, "adjusted_basis": 400_000, "debt": 400_000},
        {"purchase_price": 800_000, "debt": 300_000},
    )

    assert result.cash_boot == 100_000
    assert result.debt_boot == 100_000
    assert result.estimated_boot == 200_000
    assert result.estimated_taxable_boot == 200_000
    assert result.taxable_boot_flag is True
    assert result.deferred_gain == 400_000
    assert result.estimated_carryover_basis == 400_000
    assert result.replacement_value_test_passed is False
    assert result.debt_replaced_or_cash_offset_test_passed is False
    assert "CPA must file Form 8824" in result.cpa_gate


def test_trade_up_with_debt_and_cash_offset_has_no_boot():
    result = calc_boot_basis(
        {"sale_price": 1_000_000, "adjusted_basis": 400_000, "debt": 400_000},
        {"purchase_price": 1_200_000, "debt": 300_000},
    )

    assert result.estimated_boot == 0
    assert result.taxable_boot_flag is False
    assert result.estimated_carryover_basis == 600_000
    assert result.replacement_value_test_passed is True
    assert result.debt_replaced_or_cash_offset_test_passed is True
