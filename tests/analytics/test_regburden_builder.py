"""Registry coverage, citations, UNKNOWN behavior, and energy cross-reference."""

from cre_mcp.analytics.regburden import (
    REGULATORY_BURDEN_REGISTRY,
    regulatory_burden,
)


def test_registry_has_twelve_cited_markets_with_snapshot_dates() -> None:
    assert len(REGULATORY_BURDEN_REGISTRY) == 12
    for record in REGULATORY_BURDEN_REGISTRY.values():
        assert record["last_verified"]
        assert record["sources"]
        assert all(source["citation"] for source in record["sources"])
        assert all(source["url"].startswith("https://") for source in record["sources"])
        assert record["eviction_process_speed"]["convention"] in {
            "SLOWER",
            "MODERATE",
            "FASTER",
        }


def test_known_market_cross_references_energy_registry_read_only() -> None:
    result = regulatory_burden(["NYC", "Austin, TX"])

    assert result["status"] == "REGISTRY_SCREEN"
    nyc = result["results"][0]
    cross_reference = nyc["building_performance_laws"]["cross_reference"]
    assert nyc["rent_control"]["presence"] == "PRESENT"
    assert cross_reference["status"] == "AVAILABLE"
    assert cross_reference["registry_key"] == "nyc"
    assert cross_reference["read_only"] is True
    assert "Local Law 97" in cross_reference["law"]
    assert "not measured durations" in result["methodology"]["eviction_speed"]


def test_unlisted_market_is_unknown_without_inference() -> None:
    result = regulatory_burden(["Boise, Idaho"])

    assert result["status"] == "PARTIAL_UNKNOWN"
    assert result["unknown_count"] == 1
    unknown = result["results"][0]
    assert unknown["status"] == "UNKNOWN"
    assert unknown["rent_control"]["presence"] == "UNKNOWN"
    assert unknown["eviction_process_speed"]["convention"] == "UNKNOWN"
    assert unknown["building_performance_laws"]["presence"] == "UNKNOWN"
    assert unknown["sources"] == []
    assert unknown["last_verified"] is None
    assert "no process-speed convention is inferred" in unknown[
        "eviction_process_speed"
    ]["basis"].lower()


def test_nullable_or_malformed_jurisdiction_input_is_contained() -> None:
    assert regulatory_burden(None) == {
        "error": "regulatory_burden: jurisdictions must be a sequence of jurisdiction names"
    }
    result = regulatory_burden(["NYC", None])  # type: ignore[list-item]
    assert result["error"].startswith("regulatory_burden:")
    assert "jurisdictions[1]" in result["error"]
