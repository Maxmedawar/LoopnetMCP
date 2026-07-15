from __future__ import annotations

from datetime import date

from cre_mcp.siteintel.supply import SUPPLY_TYPE_MAPPINGS, supply_pipeline


async def test_supply_filters_and_aggregates_mapped_permit_types() -> None:
    calls: list[tuple[float, float, str, int]] = []

    async def fake_permits(
        lat: float,
        lon: float,
        city: str,
        since_days: int,
        *,
        fetch: object = None,
    ) -> dict:
        calls.append((lat, lon, city, since_days))
        return {
            "status": "OK",
            "radius_m": 500,
            "source_endpoint": "https://data.austintexas.gov/resource/3syk-w9eu.json",
            "permits": [
                {
                    "permit_type": "New Construction",
                    "issue_date": "2026-05-02T00:00:00.000",
                    "total_new_addition_sqft": "12,000",
                },
                {
                    "work_class": "Commercial Remodel",
                    "issue_date": "2026-05-19T00:00:00.000",
                    "remodel_total_sqft": "3,500",
                },
                {
                    "permit_type": "Electrical",
                    "issue_date": "2026-06-01T00:00:00.000",
                },
            ],
        }

    result = await supply_pipeline(
        "Austin",
        365,
        permit_fetcher=fake_permits,
        today=date(2026, 7, 14),
    )

    assert result["status"] == "OK"
    assert calls == [(30.2672, -97.7431, "Austin, TX", 365)]
    assert result["count"] == 2
    assert result["periods"] == [
        {
            "period": "2026-05",
            "permit_count": 2,
            "new_construction": 1,
            "major_renovation": 1,
            "reported_size_sf": 15_500.0,
            "size_records": 2,
        }
    ]
    assert result["totals"]["reported_size_sf"] == 15_500.0
    assert result["source"]["retrieved_date"] == "2026-07-14"
    assert "permits != deliveries" in result["honesty"]
    assert "500 m radius" in result["spatial_convention"]["label"]


def test_supply_mapping_table_is_exposed_and_uses_area_fields_only() -> None:
    assert set(SUPPLY_TYPE_MAPPINGS) == {
        "austin",
        "chicago",
        "san_francisco",
        "los_angeles",
        "seattle",
    }
    assert SUPPLY_TYPE_MAPPINGS["austin"]["dataset_id"] == "3syk-w9eu"
    for mapping in SUPPLY_TYPE_MAPPINGS.values():
        assert mapping["new_construction"]
        assert mapping["major_renovation"]
        assert mapping["size_unit"] == "square_feet"
        assert all(
            token not in field.casefold()
            for field in mapping["size_fields"]
            for token in ("cost", "valuation", "units")
        )


async def test_unsupported_supply_city_is_honest_and_exposes_all_mappings() -> None:
    result = await supply_pipeline("Portland, OR", 365)

    assert result["status"] == "UNSUPPORTED"
    assert result["count"] == 0
    assert set(result["mapping_table"]) == set(SUPPLY_TYPE_MAPPINGS)
    assert result["honesty"] == "permits != deliveries"

