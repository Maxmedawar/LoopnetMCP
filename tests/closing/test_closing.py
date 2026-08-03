"""Adversarial contract tests for closing execution and its tool boundary."""

from __future__ import annotations

import inspect

import pytest
from fastmcp.tools import Tool

from cre_mcp.closing import command_center, tools
from cre_mcp.closing.funding import verify_funding_package
from cre_mcp.closing.obligations_extract import extract_contract_obligations
from cre_mcp.closing.postmortem import deal_postmortem
from cre_mcp.closing.settlement import reconcile_settlement


WIRE_WARNING = "human call-back verification required — wire fraud is unrecoverable"


def test_proration_math_is_penny_exact_and_convention_is_measurable():
    statement = {
        "closing_date": "2026-07-15",
        "line_items": [
            {"id": "rent-a", "category": "rent", "amount_cents": 167_671}
        ],
    }
    expected = {
        "rent_roll": [
            {"id": "rent-a", "tenant": "A", "monthly_rent_cents": 300_000}
        ]
    }

    actual_365 = reconcile_settlement(statement, expected, "365", "buyer")
    actual_360 = reconcile_settlement(statement, expected, "360", "buyer")

    assert "error" not in actual_365
    assert "error" not in actual_360
    rent_365 = actual_365["expected_lines"][0]
    rent_360 = actual_360["expected_lines"][0]
    assert rent_365["owned_days"] == 17
    assert rent_365["denominator_days"] == 365
    assert rent_365["expected_amount_cents"] == 167_671
    assert rent_365["per_diem_exact"] == "3600000/365"
    assert rent_360["denominator_days"] == 360
    assert rent_360["expected_amount_cents"] == 170_000
    assert rent_360["expected_amount_cents"] - rent_365["expected_amount_cents"] == 2_329
    assert "3600000" in rent_365["arithmetic"]
    assert "17" in rent_365["arithmetic"]


def _funding_fixture(*, verified: bool, source_cents: int = 10_001):
    sources_uses = {
        "closing_date": "2026-07-15",
        "sources": [{"name": "loan", "amount_cents": source_cents}],
        "uses": [{"name": "purchase", "amount_cents": 10_000}],
    }
    payoff_letters = [
        {"holder": "Bank", "amount_cents": 5_000, "good_through": "2026-07-15"}
    ]
    wires = [
        {
            "recipient": "Title",
            "bank": "Bank",
            "account_last4": "1234",
            "amount_cents": 5_000,
            "instruction_source": "title portal",
            "verified_by_callback": verified,
        }
    ]
    return sources_uses, payoff_letters, wires


def test_sources_and_uses_one_cent_imbalance_is_not_rounded_away():
    result = verify_funding_package(*_funding_fixture(verified=True))

    assert result["sources_uses"]["sources_total_cents"] == 10_001
    assert result["sources_uses"]["uses_total_cents"] == 10_000
    assert result["sources_uses"]["delta_cents"] == 1
    assert result["sources_uses"]["balanced"] is False
    assert result["ok"] is False


def test_every_unverified_wire_is_a_hard_flag_and_never_self_verifies():
    result = verify_funding_package(*_funding_fixture(verified=False, source_cents=10_000))

    assert result["wire_checks"][0]["verified_by_callback"] is False
    assert result["ok"] is False
    assert WIRE_WARNING in str(result["hard_flags"])


def test_psa_representation_is_quoted_and_located_for_counsel():
    psa = """PURCHASE AND SALE AGREEMENT
Section 6.1 Seller Representations. Seller represents and warrants that no litigation is pending against the Property. This representation shall survive Closing for twelve (12) months.
Section 8.1 Covenants. Seller shall operate the Property in the ordinary course until Closing.
Section 9.1 Conditions Precedent. Buyer's obligation to close is conditioned on delivery of a clean title policy by Closing.
Section 12.4 Post-Closing. Seller shall deliver the security deposit ledger to Buyer within 5 days after Closing.
"""

    result = extract_contract_obligations(psa, "psa")

    assert result["counsel_review_required"] is True
    assert result["counsel_flag"]
    representations = result["representations_and_warranties"]
    assert representations
    cited = next(item for item in representations if "litigation" in item["quote"].lower())
    assert "Seller represents and warrants" in cited["quote"]
    assert cited["locator"]
    assert cited["party"] == "Seller"
    assert cited["survival"] is not None
    for field in ("quote", "locator", "party", "deadline_rule", "survival"):
        assert field in cited
    condition = next(
        item
        for item in result["conditions_precedent"]
        if "conditioned on" in item["quote"].lower()
    )
    assert condition["party"] == "Buyer"
    assert condition["deadline_rule"] == "by Closing"


def test_runbook_orders_execution_and_gives_every_item_owner_and_blocking_status(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        command_center,
        "dataroom_closing_runway",
        lambda deal_id: {
            "deal_id": deal_id,
            "initialized": True,
            "tasks": [
                {
                    "task_key": "final_title",
                    "label": "Review final title",
                    "owner": "counsel",
                    "status": "complete",
                    "deadline": "2026-07-15",
                }
            ],
            "blocking_prerequisites": [],
        },
    )
    funding = {
        "ok": False,
        "status": "blocked",
        "hard_flags": [WIRE_WARNING],
    }
    obligations = {
        "post_closing_obligations": [
            {
                "obligation": "Deliver tenant notices",
                "quote": "Buyer shall deliver tenant notices within 5 days after Closing.",
                "locator": "Section 12.4, line 4",
                "party": "Buyer",
                "deadline_rule": "within 5 days after Closing",
                "survival": None,
            }
        ]
    }

    result = command_center.closing_day("deal-1", "2026-07-15", funding, obligations)

    assert "error" not in result
    phases = [item["phase"] for item in result["runbook"]]
    assert phases.index("funding") < phases.index("signature")
    assert phases.index("signature") < phases.index("notary") < phases.index("recording")
    assert phases.index("recording") < phases.index("post_closing")
    assert [item["order"] for item in result["runbook"]] == list(
        range(1, len(result["runbook"]) + 1)
    )
    assert all("owner" in item and "blocking_status" in item for item in result["runbook"])
    assert "funding:verification_checklist" in result["blocking_items"]
    assert result["wire_control"] == WIRE_WARNING
    assert result["post_closing_obligation_calendar"][0]["party"] == "Buyer"


def test_postmortem_is_structured_and_labels_screening_links_as_hypotheses(tmp_path):
    result = deal_postmortem(
        "deal-died",
        [
            {"date": "2026-06-01", "event": "LOI signed"},
            {"date": "2026-06-20", "event": "Loan proceeds reduced"},
        ],
        {"status": "died", "why": "financing retrade"},
        {"changes": [{"term": "loan_proceeds", "from": 8_000_000, "to": 7_000_000}]},
        tmp_path / "ledger.sqlite3",
    )

    expected_keys = {
        "deal_id",
        "outcome",
        "timeline",
        "defect_ledger_evidence",
        "screening_signal_hypotheses",
        "loi_to_close_changes",
        "lessons",
        "screening_recommendations",
        "honesty",
    }
    assert expected_keys <= result.keys()
    assert result["outcome"]["status"] == "died"
    assert result["loi_to_close_changes"][0]["term"] == "loan_proceeds"
    assert "hypoth" in str(result["honesty"]).lower()
    assert isinstance(result["screening_recommendations"], list)


def test_plain_tools_have_explicit_signatures_and_never_leak_exceptions(
    monkeypatch: pytest.MonkeyPatch,
):
    forbidden = {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    for name in tools.__all__:
        function = getattr(tools, name)
        assert not [
            parameter.name
            for parameter in inspect.signature(function).parameters.values()
            if parameter.kind in forbidden
        ]
        assert Tool.from_function(function).name == name

    def explode(*args, **kwargs):
        raise RuntimeError("controlled boundary failure")

    monkeypatch.setattr(tools, "_extract_contract_obligations", explode)
    monkeypatch.setattr(tools, "_reconcile_settlement", explode)
    monkeypatch.setattr(tools, "_verify_funding_package", explode)
    monkeypatch.setattr(tools, "_closing_day", explode)
    monkeypatch.setattr(tools, "_deal_postmortem", explode)

    results = [
        tools.extract_contract_obligations("text", "psa"),
        tools.reconcile_settlement({}, {}),
        tools.verify_funding_package({}, [], []),
        tools.closing_day_runbook("deal", "2026-07-15"),
        tools.record_deal_postmortem("deal", [], {"status": "died", "why": "unknown"}),
    ]
    assert all(result == {"error": "controlled boundary failure"} for result in results)
