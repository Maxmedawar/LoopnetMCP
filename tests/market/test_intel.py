"""MarketPack fault isolation, scoring, and keyless degradation tests."""

from types import SimpleNamespace

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.market.intel import MarketIntel, market_score
from cre_mcp.models import GeoLevel, GeoRef, MetricSeries, MetricValue


def _metric(value, unit="percent", source="fixture", as_of="2024"):
    return MetricValue(value=value, unit=unit, source=source, as_of=as_of)


class FakeCensus:
    async def acs5_profile(self, geo, year):
        if year >= 2024:
            return {
                "population": _metric(1_300_000, "people"),
                "median_hh_income": _metric(95_000, "USD/year"),
                "median_gross_rent": _metric(1_600, "USD/month"),
                "rental_vacancy": _metric(5.2),
                "renter_share": _metric(44.0),
            }
        return {
            "population": _metric(1_200_000, "people", as_of="2019"),
            "median_hh_income": _metric(78_000, "USD/year", as_of="2019"),
        }

    async def building_permits(self, geo, year):
        return _metric(12_500, "housing units")


class ErroringBls:
    async def qcew_employment(self, geo):
        raise RuntimeError("BLS unavailable")

    async def laus_unemployment(self, geo):
        return MetricSeries(points=[("2025-12", 3.4)], unit="percent", source="BLS")


class HistoricalBls:
    async def qcew_employment(self, geo):
        return MetricSeries(
            points=[
                ("2019-01", 757_902),
                ("2020-12", 771_513),
                ("2024-12", 914_757),
                ("2025-12", 939_358),
            ],
            unit="jobs",
            source="BLS QCEW",
        )

    async def laus_unemployment(self, geo):
        return MetricSeries(points=[("2025-12", 3.4)], unit="percent", source="BLS")


class MissingProvider:
    async def series(self, series_id):
        raise RuntimeError("missing key")

    async def fmr(self, geo, year):
        raise RuntimeError("missing key")

    async def regional(self, geo, table):
        raise RuntimeError("missing key")

    async def hpi_growth(self, geo):
        raise RuntimeError("unavailable")


class FakeIrs:
    async def net_migration(self, county_fips):
        return _metric(12_000, "people")


@pytest.fixture
def geo():
    return GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        cbsa="12420",
        name="Travis County, TX",
    )


@pytest.mark.asyncio
async def test_provider_failure_becomes_coverage_gap_not_exception(geo):
    missing = MissingProvider()
    intel = MarketIntel(
        census=FakeCensus(),
        bls=ErroringBls(),
        fred=missing,
        fhfa=missing,
        hud=missing,
        bea=missing,
        irs=FakeIrs(),
    )
    pack = await intel.get_market_pack(geo)

    assert pack.population.value == 1_300_000
    assert pack.unemployment_rate.value == 3.4
    assert pack.job_growth_1yr is None
    assert pack.coverage["job_growth_1yr"] is False
    assert pack.coverage["population"] is True
    assert pack.coverage["treasury_10yr"] is False
    score, confidence = market_score(pack)
    assert 0 < score <= 100
    assert 0 < confidence < 1


@pytest.mark.asyncio
async def test_no_api_keys_returns_partial_pack_without_raising(geo):
    missing = MissingProvider()
    intel = MarketIntel(
        CreConfig(
            census_api_key=None,
            bls_api_key=None,
            fred_api_key=None,
            hud_api_token=None,
            bea_api_key=None,
        ),
        census=FakeCensus(),
        bls=ErroringBls(),
        fred=missing,
        fhfa=missing,
        hud=missing,
        bea=missing,
        irs=FakeIrs(),
    )
    pack = await intel.get_market_pack(geo)
    coverage_ratio = sum(pack.coverage.values()) / len(pack.coverage)
    assert 0 < coverage_ratio < 1


@pytest.mark.asyncio
async def test_five_year_job_growth_uses_full_qcew_history(geo):
    missing = MissingProvider()
    intel = MarketIntel(
        census=FakeCensus(),
        bls=HistoricalBls(),
        fred=missing,
        fhfa=missing,
        hud=missing,
        bea=missing,
        irs=FakeIrs(),
    )

    pack = await intel.get_market_pack(geo)

    assert pack.job_growth_5yr is not None
    assert pack.job_growth_5yr.value == pytest.approx(4.0154, rel=1e-3)
    assert pack.coverage["job_growth_5yr"] is True
