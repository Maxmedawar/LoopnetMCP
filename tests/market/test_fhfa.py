"""Keyless FHFA state HPI provider tests."""

from pathlib import Path

import pytest

from cre_mcp.market.fhfa import FhfaProvider, STATE_HPI_URL
from cre_mcp.models import GeoLevel, GeoRef

FIXTURES = Path(__file__).parents[1] / "fixtures" / "fhfa"


class FixtureFetch:
    def __init__(self):
        self.calls: list[str] = []

    async def get_text(self, url: str) -> str:
        self.calls.append(url)
        return (FIXTURES / "state_hpi_tx.csv").read_text()


@pytest.mark.asyncio
async def test_keyless_fhfa_state_growth_uses_latest_matching_quarter():
    fetch = FixtureFetch()
    provider = FhfaProvider(fetch=fetch)  # type: ignore[arg-type]
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name="Travis County, TX",
    )

    metric = await provider.hpi_growth(geo)

    assert metric is not None
    assert metric.value == pytest.approx((529.31 / 522.82 - 1) * 100)
    assert metric.as_of == "2026-Q1"
    assert "residential-market trend proxy" in metric.source
    assert fetch.calls == [STATE_HPI_URL]


@pytest.mark.asyncio
async def test_fhfa_unknown_state_is_coverage_gap_without_network():
    fetch = FixtureFetch()
    provider = FhfaProvider(fetch=fetch)  # type: ignore[arg-type]
    geo = GeoRef(level=GeoLevel.STATE, state_fips="99", name="Unknown")

    assert await provider.hpi_growth(geo) is None
    assert fetch.calls == []
