"""Complete, explained, state-aware non-binding LOI drafting."""

import pytest

from cre_mcp.execution.loi import GENERAL_JURISDICTION_NOTE, generate_loi
from tests.scoring.builders import deal_context


def _context(state="TX"):
    ctx = deal_context(price=1_000_000, noi=65_000)
    ctx.listing.state = state
    return ctx


def test_loi_contains_every_material_term_note_flag_and_guardrail():
    result = generate_loi(
        _context(),
        {
            "price": 950_000,
            "buyer_entity": "Novice King Acquisitions LLC",
            "earnest_money_pct": 1.5,
            "dd_days": 25,
            "closing_days": 40,
            "state": "TX",
        },
    )

    assert result.price == 950_000
    assert result.earnest_money == 14_250
    assert result.dd_days == 25
    assert result.closing_days == 40
    for text in (
        "NON-BINDING LETTER OF INTENT",
        "Buyer and Seller",
        "Property",
        "Purchase Price",
        "Earnest Money",
        "Due Diligence",
        "Closing",
        "Financing",
        "As-Is",
        "Brokerage",
        "Confidentiality",
        "Expiration",
        "Non-Binding Effect",
    ):
        assert text in result.body_markdown
    expected_notes = {
        "parties",
        "property",
        "purchase_price",
        "earnest_money",
        "earnest_money_go_hard",
        "due_diligence",
        "closing",
        "contingencies",
        "financing_contingency",
        "as_is",
        "brokerage",
        "confidentiality",
        "expiration",
        "assignment",
        "default_remedies",
        "non_binding",
        "jurisdiction",
    }
    assert expected_notes <= set(result.term_notes)
    assert {
        "earnest_money_go_hard",
        "financing_contingency",
        "assignment",
        "default_and_remedies",
    } <= set(result.attorney_review_flags)
    assert "not legal or financial advice" in result.disclaimer
    assert result.body_markdown.rstrip().endswith(result.disclaimer)


@pytest.mark.parametrize("state", ["TX", "FL", "AZ", "NC", "CO", "CA"])
def test_loi_has_cautious_jurisdiction_variant(state):
    result = generate_loi(_context(state), {"price": 900_000, "state": state})

    assert f"jurisdiction_{state.casefold()}" in result.attorney_review_flags
    assert state in result.body_markdown or state == "CA"
    assert "counsel" in result.body_markdown.casefold()
    assert GENERAL_JURISDICTION_NOTE not in result.body_markdown


def test_loi_unknown_state_uses_general_local_counsel_fallback():
    result = generate_loi(_context("WA"), {"price": 900_000, "state": "WA"})

    assert GENERAL_JURISDICTION_NOTE in result.body_markdown
    assert "jurisdiction_wa" in result.attorney_review_flags


def test_financing_waiver_is_flagged_not_endorsed():
    result = generate_loi(
        _context(),
        {"price": 900_000, "financing_contingency": False},
    )

    assert "No financing contingency is proposed" in result.body_markdown
    assert "counsel must review this waiver" in result.body_markdown
    assert "financing_contingency" in result.attorney_review_flags
