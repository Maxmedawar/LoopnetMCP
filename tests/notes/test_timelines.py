from cre_mcp.notes.timelines import (
    COUNSEL_VERIFICATION_FLAG,
    LAST_VERIFIED,
    STATE_FORECLOSURE_REGISTRY,
    estimate_timeline,
)


def test_every_registry_entry_carries_mandated_honesty_metadata():
    assert len(STATE_FORECLOSURE_REGISTRY) == 15
    for entry in STATE_FORECLOSURE_REGISTRY.values():
        assert entry.source_note
        assert entry.confidence in {"high", "moderate", "low"}
        assert entry.last_verified == LAST_VERIFIED == "2026-07"
        assert entry.professional_review_flag == COUNSEL_VERIFICATION_FLAG


def test_unknown_state_is_explicit_unknown_and_never_borrows_timing():
    result = estimate_timeline("MA")

    assert result["status"] == "UNKNOWN"
    assert result["months"] == {
        "low": "UNKNOWN",
        "base": "UNKNOWN",
        "high": "UNKNOWN",
    }
    assert result["source_note"].startswith("UNKNOWN")
    assert result["professional_review_required"] is True


def test_new_york_is_years_low_confidence_and_bankruptcy_delay_is_unknown():
    result = estimate_timeline("New York", bankruptcy_risk=True)

    assert result["state"] == "NY"
    assert result["months"]["low"] >= 24
    assert result["confidence"] == "low"
    assert "YEARS" in result["source_note"]
    assert result["bankruptcy_delay_months"]["base"] == "UNKNOWN"
    assert "automatic stay" in result["bankruptcy_stay_warning"]
