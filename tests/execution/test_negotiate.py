"""Counter parsing, underwriting gates, go-hard traps, and response coaching."""

from cre_mcp.execution.negotiate import handle_counter
from tests.scoring.builders import deal_context


def _ctx():
    return deal_context(
        price=1_100_000,
        noi=70_000,
        raw={
            "strategy": "nnn_retail",
            "tenant_credit_rating": "BBB",
            "lease_years_remaining": 12,
        },
    )


def test_parses_counter_and_flags_day_one_go_hard_first_timer_trap():
    result = handle_counter(
        _ctx(),
        "Seller counters at $1.2M with $50k earnest, 10 days DD, close in "
        "30 days. Deposit goes hard day one and there is no financing contingency.",
    )

    assert "$1,200,000" in result.read
    assert "$50,000" in result.read
    assert "10 days" in result.read
    assert result.verdict == "walk"
    assert any("Day-one" in flag for flag in result.red_flags)
    assert any("Financing contingency" in flag for flag in result.red_flags)
    assert any("Earnest money" in flag for flag in result.red_flags)
    assert result.reply_template.endswith(result.reply_template.split("\n\n")[-1])
    assert "CRE attorney" in result.reply_template


def test_counter_near_target_with_protected_terms_can_be_accepted():
    baseline = handle_counter(_ctx(), "Please confirm a written counter.")
    assert baseline.verdict == "hold"

    result = handle_counter(
        _ctx(),
        "Purchase price $950,000; 1% earnest money; 30-day due diligence; "
        "45-day closing; subject to financing contingency.",
    )
    assert result.verdict == "accept"
    assert not any("Day-one" in flag for flag in result.red_flags)
    assert result.suggested_counter["financing_contingency"].startswith("retain")


def test_missing_price_holds_for_complete_written_terms():
    result = handle_counter(
        _ctx(),
        "Seller wants a quick close and will send pricing later.",
    )
    assert result.verdict == "hold"
    assert result.suggested_counter["price"] is None
    assert "complete written counter" in result.reply_template
