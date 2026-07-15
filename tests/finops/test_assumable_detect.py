"""Deterministic, cited detection tests for potentially assumable financing."""

from cre_mcp.finops.assumable_detect import detect_assumable


def test_assumable_detector_returns_cited_hits_and_debt_valuation_handoff():
    text = (
        "Investment Highlights\n"
        "Existing financing may be assumable, subject to lender approval. "
        "The existing loan bears interest at 3.75% through maturity. "
        "Contact the broker for the loan assumption package."
    )

    result = detect_assumable(text)

    assert result["detected"] is True
    assert result["flags"]
    assert len(result["cited_hits"]) >= 3
    for hit in result["cited_hits"]:
        citation = hit["citation"]
        assert hit["excerpt"]
        assert citation["start_char"] < citation["end_char"]
        assert citation["line"] >= 1
        assert hit["excerpt"] in text
    assert "value_assumable_debt" in str(result["handoff"])


def test_assumable_detector_does_not_treat_generic_new_debt_as_existing_financing():
    result = detect_assumable(
        "Buyer may arrange a new acquisition loan at prevailing market rates. "
        "No seller representations are made about financing."
    )

    assert result["detected"] is False
    assert result["flags"] == []
    assert result["cited_hits"] == []
