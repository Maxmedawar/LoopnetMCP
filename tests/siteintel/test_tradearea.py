from __future__ import annotations

from cre_mcp.siteintel import tradearea


def test_trade_area_uses_conventional_rings_and_osm_anchors(monkeypatch) -> None:
    calls: list[tuple[float, float, int]] = []

    def fake_anchors(lat: float, lon: float, radius_m: int = 800) -> dict:
        calls.append((lat, lon, radius_m))
        return {
            "anchor_count": 2,
            "complementary": [{"brand": "Target"}, {"brand": "Costco"}],
            "competitors": [],
            "brands": ["Target", "Costco"],
            "summary": "Target, Costco within 8047m",
        }

    monkeypatch.setattr(tradearea, "trade_area_anchors", fake_anchors)
    result = tradearea.trade_area(
        32.7767,
        -96.797,
        population=120_000,
        median_household_income=82_500,
    )

    assert "error" not in result
    assert [ring["radius_miles"] for ring in result["rings"]] == [1, 3, 5]
    assert calls == [(32.7767, -96.797, 8047)]
    assert result["osm_anchors"]["anchor_count"] == 2
    assert result["demographic_inputs"]["population"] == 120_000
    assert result["convention_label"] == (
        "rings are a convention; drive-time isochrones need a routing engine — flagged gap"
    )
    assert "Census enrichment" in result["demographic_hook"]["reference"]


def test_trade_area_validation_stays_at_error_boundary(monkeypatch) -> None:
    def no_call(lat: float, lon: float, radius_m: int = 800) -> dict:
        raise AssertionError("invalid coordinates must not perform enrichment")

    monkeypatch.setattr(tradearea, "trade_area_anchors", no_call)

    assert "error" in tradearea.trade_area(91, -96.0)
    assert "error" in tradearea.trade_area(32.0, -181)
    assert tradearea.trade_area(32.0, -96.0, mode="drive_time") == {
        "error": "mode must be 'rings'"
    }


def test_trade_area_wraps_anchor_enrichment_failure(monkeypatch) -> None:
    def broken(lat: float, lon: float, radius_m: int = 800) -> dict:
        raise RuntimeError("OSM unavailable")

    monkeypatch.setattr(tradearea, "trade_area_anchors", broken)
    assert tradearea.trade_area(32.0, -96.0) == {"error": "OSM unavailable"}
