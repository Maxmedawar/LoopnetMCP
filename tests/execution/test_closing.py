"""Closing-runway sequencing, state routing, and wire safety tests."""

from cre_mcp.execution.closing import WIRE_FRAUD_WARNING, closing_plan
from tests.scoring.builders import deal_context


def test_entity_setup_is_sequenced_before_lender_package():
    plan = closing_plan(deal_context())
    titles = [step.title.casefold() for step in plan.steps]
    lender_index = next(index for index, title in enumerate(titles) if "lender" in title)

    for required in ("acquisition entity", "form", "ein", "operating agreement", "bank account"):
        assert next(index for index, title in enumerate(titles) if required in title) < lender_index
    assert "same taxpayer" in plan.steps[0].detail
    assert "qualified intermediary" in plan.steps[0].who.casefold()


def test_wire_fraud_warning_is_loud_and_repeated_on_funding_step():
    plan = closing_plan(deal_context())
    funding = next(step for step in plan.steps if "funding" in step.title.casefold())

    assert plan.wire_fraud_warning == WIRE_FRAUD_WARNING
    assert plan.wire_fraud_warning.startswith("WIRE-FRAUD STOP")
    assert WIRE_FRAUD_WARNING in funding.detail
    assert WIRE_FRAUD_WARNING in funding.gate
    assert "known, independently verified phone number" in plan.wire_fraud_warning
    assert any("wire" in flag.casefold() for flag in plan.red_flags)


def test_attorney_vs_title_routing_is_state_aware_with_general_fallback():
    ga = closing_plan(deal_context(), state="GA")
    nc = closing_plan(deal_context(), state="NC")
    tx = closing_plan(deal_context(), state="TX")
    unknown = closing_plan(deal_context(), state="Ontario")

    assert ga.closing_mode == "attorney-led"
    assert "Georgia closing attorney" in ga.steps[6].who
    assert nc.closing_mode == "attorney-supervised"
    assert "North Carolina" in nc.steps[6].who
    assert "title/escrow" in tx.closing_mode
    assert unknown.state == "GENERAL"
    assert "Local CRE attorney" in unknown.steps[6].who
    assert all(step.who and step.gate for step in ga.steps)


def test_full_state_name_is_normalized_for_novice_input():
    plan = closing_plan(deal_context(), state="North Carolina")
    assert plan.state == "NC"
    assert plan.closing_mode == "attorney-supervised"
