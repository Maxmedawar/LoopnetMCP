"""Capital attorney-draft and anti-fraud refusal tests."""

from datetime import date, timedelta

import pytest

from cre_mcp.capital.docs import draft_form_d, draft_ppm, draft_subscription


def test_ppm_is_draft_has_risks_gate_and_no_fabricated_guarantee():
    draft = draft_ppm(
        {
            "deal_ref": "fixture:deal",
            "name": "Congress Retail",
            "address": "100 Congress Ave, Austin, TX",
            "price": 2_500_000,
            "noi": 177_500,
        },
        {
            "issuer_name": "Congress Investors LLC",
            "exemption": "506b",
            "target_raise": 900_000,
            "pref": 8,
            "gp_promote": 20,
        },
    )
    text = draft.body_markdown.casefold()

    assert draft.status == "DRAFT — ATTORNEY REVIEW REQUIRED"
    assert text.startswith("# draft — attorney review required")
    assert "risk factors" in text
    assert "possible total loss" in text
    assert "hard gate" in text
    assert "securities attorney" in draft.guardrail
    assert "guaranteed return" not in text
    assert "no outcome is promised" in text


def test_subscription_is_draft_only_and_does_not_accept_money():
    draft = draft_subscription(
        {"name": "Congress Investors LLC"},
        {"exemption": "506c"},
        {"name": "Example Investor", "amount": 100_000},
    )

    assert draft.document_type == "SUBSCRIPTION"
    assert "does not accept a subscription" in draft.body_markdown
    assert "HARD GATE" in draft.body_markdown


def test_form_d_is_unfiled_draft_and_calculates_fifteen_day_date():
    first_sale = date(2026, 7, 13)
    draft = draft_form_d(
        {"name": "Congress Investors LLC", "state": "TX"},
        {
            "mode": "506c",
            "first_sale_date": first_sale.isoformat(),
            "target_raise": 1_000_000,
        },
    )

    assert draft.document_type == "FORM_D"
    assert draft.status.startswith("DRAFT")
    assert "NOT FILED" in draft.body_markdown
    assert draft.data["form_d_due_date_estimate"] == (
        first_sale + timedelta(days=15)
    ).isoformat()
    assert "blue-sky" in draft.guardrail


def test_docs_refuse_guaranteed_or_risk_free_claims():
    with pytest.raises(ValueError, match="performance guarantees"):
        draft_ppm(
            {"deal_ref": "fixture:deal"},
            {"issuer_name": "Test LLC", "guaranteed_return": "12%"},
        )
    with pytest.raises(ValueError, match="anti-fraud language"):
        draft_form_d(
            {"name": "Test LLC"},
            {"mode": "506b", "marketing_claim": "risk-free performance"},
        )
