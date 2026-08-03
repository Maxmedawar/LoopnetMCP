"""Fault-isolated assembly and scoring of cross-provider market intelligence."""

import asyncio
import logging
import math
from datetime import UTC, datetime
from typing import Any, Awaitable

from cre_mcp.access.context import resolve_runtime_config
from cre_mcp.config import CreConfig
from cre_mcp.market.bea import BeaProvider
from cre_mcp.market.bls import BlsProvider
from cre_mcp.market.census import CensusProvider
from cre_mcp.market.fred import FredProvider
from cre_mcp.market.fhfa import FhfaProvider
from cre_mcp.market.hud import HudProvider
from cre_mcp.market.irs_soi import IrsSoiProvider
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.market import (
    MARKET_METRIC_FIELDS,
    MarketPack,
    MetricSeries,
    MetricValue,
)
from cre_mcp.source_rights.output import safe_error_message

logger = logging.getLogger(__name__)


def _available(metric: MetricValue | None) -> bool:
    return metric is not None and metric.value is not None


def _growth_value(
    current: MetricValue | None,
    prior: MetricValue | None,
    *,
    years: int,
    source: str,
) -> MetricValue | None:
    if not _available(current) or not _available(prior):
        return None
    assert current is not None and current.value is not None
    assert prior is not None and prior.value is not None
    if current.value <= 0 or prior.value <= 0:
        return None
    value = (math.pow(current.value / prior.value, 1 / years) - 1) * 100
    return MetricValue(
        value=value,
        unit="percent CAGR",
        as_of=current.as_of,
        source=source,
    )


def _series_latest(series: MetricSeries | None, source: str) -> MetricValue | None:
    if series is None or not series.points:
        return None
    date, value = series.points[-1]
    return MetricValue(value=value, unit=series.unit, as_of=date, source=source)


def _series_growth(
    series: MetricSeries | None,
    years: int,
    source: str,
) -> MetricValue | None:
    if series is None or len(series.points) < 2:
        return None
    last_date, last_value = series.points[-1]
    try:
        last_year = int(last_date[:4])
    except ValueError:
        return None
    target_year = last_year - years
    candidates = [point for point in series.points[:-1] if int(point[0][:4]) <= target_year]
    if not candidates:
        candidates = [series.points[0]] if years == 1 else []
    if not candidates:
        return None
    _, prior_value = candidates[-1]
    if prior_value <= 0 or last_value <= 0:
        return None
    value = (math.pow(last_value / prior_value, 1 / years) - 1) * 100
    return MetricValue(
        value=value,
        unit="percent CAGR",
        as_of=last_date,
        source=source,
    )


class MarketIntel:
    """Gather independent providers without allowing one failure to abort the pack."""

    def __init__(
        self,
        config: CreConfig | None = None,
        *,
        census: CensusProvider | None = None,
        bls: BlsProvider | None = None,
        fred: FredProvider | None = None,
        fhfa: FhfaProvider | None = None,
        hud: HudProvider | None = None,
        bea: BeaProvider | None = None,
        irs: IrsSoiProvider | None = None,
    ):
        self.config = resolve_runtime_config(config)
        self.census = census or CensusProvider(config=self.config)
        self.bls = bls or BlsProvider(config=self.config)
        self.fred = fred or FredProvider(config=self.config)
        self.fhfa = fhfa or FhfaProvider()
        self.hud = hud or HudProvider(config=self.config)
        self.bea = bea or BeaProvider(config=self.config)
        self.irs = irs or IrsSoiProvider(config=self.config)

    async def _safe(self, label: str, operation: Awaitable[Any]) -> Any | None:
        try:
            return await operation
        except Exception as exc:
            logger.warning(
                "Market provider operation %s unavailable: %s",
                label,
                safe_error_message(exc),
            )
            return None

    async def get_market_pack(self, geo: GeoRef) -> MarketPack:
        """Assemble a partial MarketPack, recording coverage for every metric."""
        latest_year = datetime.now(UTC).year - 2
        labels = (
            "census_current",
            "census_prior",
            "census_permits",
            "bls_qcew",
            "bls_laus",
            "fred_treasury",
            "fred_mortgage",
            "fred_sofr",
            "fhfa_hpi",
            "hud_fmr",
            "bea_gdp",
            "irs_migration",
        )
        operations = (
            self.census.acs5_profile(geo, latest_year),
            self.census.acs5_profile(geo, latest_year - 5),
            self.census.building_permits(geo, latest_year),
            self.bls.qcew_employment(geo),
            self.bls.laus_unemployment(geo),
            self.fred.series("DGS10"),
            self.fred.series("MORTGAGE30US"),
            self.fred.series("SOFR"),
            self.fhfa.hpi_growth(geo),
            self.hud.fmr(geo, latest_year),
            self.bea.regional(geo, "CAGDP1"),
            self.irs.net_migration(geo.county_fips or ""),
        )
        results = await asyncio.gather(
            *(self._safe(label, operation) for label, operation in zip(labels, operations, strict=True))
        )
        data = dict(zip(labels, results, strict=True))

        current = data["census_current"] if isinstance(data["census_current"], dict) else {}
        prior = data["census_prior"] if isinstance(data["census_prior"], dict) else {}
        qcew = data["bls_qcew"] if isinstance(data["bls_qcew"], MetricSeries) else None
        laus = data["bls_laus"] if isinstance(data["bls_laus"], MetricSeries) else None
        gdp = data["bea_gdp"] if isinstance(data["bea_gdp"], MetricSeries) else None

        values: dict[str, MetricValue | None] = {
            "population": current.get("population"),
            "pop_growth_5yr": _growth_value(
                current.get("population"),
                prior.get("population"),
                years=5,
                source="Census ACS 5-year",
            ),
            "median_hh_income": current.get("median_hh_income"),
            "income_growth": _growth_value(
                current.get("median_hh_income"),
                prior.get("median_hh_income"),
                years=5,
                source="Census ACS 5-year",
            ),
            "job_growth_1yr": _series_growth(qcew, 1, "BLS QCEW"),
            "job_growth_5yr": _series_growth(qcew, 5, "BLS QCEW"),
            "unemployment_rate": _series_latest(laus, "BLS LAUS"),
            "net_migration": data["irs_migration"] if isinstance(data["irs_migration"], MetricValue) else None,
            "fmr_2br": data["hud_fmr"] if isinstance(data["hud_fmr"], MetricValue) else None,
            "median_gross_rent": current.get("median_gross_rent"),
            "rental_vacancy": current.get("rental_vacancy"),
            "renter_share": current.get("renter_share"),
            "permits_trailing_12m": data["census_permits"] if isinstance(data["census_permits"], MetricValue) else None,
            "county_gdp_growth": _series_growth(gdp, 1, "BEA Regional CAGDP1"),
            "treasury_10yr": _series_latest(
                data["fred_treasury"] if isinstance(data["fred_treasury"], MetricSeries) else None,
                "FRED DGS10",
            ),
            "mortgage_rate": _series_latest(
                data["fred_mortgage"] if isinstance(data["fred_mortgage"], MetricSeries) else None,
                "FRED MORTGAGE30US",
            ),
            "sofr": _series_latest(
                data["fred_sofr"] if isinstance(data["fred_sofr"], MetricSeries) else None,
                "FRED SOFR",
            ),
            "fhfa_hpi_growth_1yr": (
                data["fhfa_hpi"]
                if isinstance(data["fhfa_hpi"], MetricValue)
                else None
            ),
        }
        coverage = {name: _available(values.get(name)) for name in MARKET_METRIC_FIELDS}
        return MarketPack(geo=geo, **values, coverage=coverage)


def _piecewise(value: float, bands: tuple[tuple[float, float], ...]) -> float:
    for threshold, score in bands:
        if value < threshold:
            return score
    return bands[-1][1]


def market_score(pack: MarketPack) -> tuple[float, float]:
    """Score the covered market subset and return score plus coverage confidence."""
    population = pack.population.value if _available(pack.population) else None  # type: ignore[union-attr]
    raw: dict[str, tuple[MetricValue | None, float, Any]] = {
        "job_growth_5yr": (
            pack.job_growth_5yr,
            0.30,
            lambda value: _piecewise(value, ((0.3, 0.1), (1.0, 0.4), (2.0, 0.75), (float("inf"), 1.0))),
        ),
        "pop_growth_5yr": (
            pack.pop_growth_5yr,
            0.22,
            lambda value: _piecewise(value, ((0.0, 0.0), (0.75, 0.35), (1.5, 0.7), (float("inf"), 1.0))),
        ),
        "median_hh_income": (
            pack.median_hh_income,
            0.18,
            lambda value: max(0.1, min(1.0, (value - 35_000) / 50_000)),
        ),
        "net_migration": (
            pack.net_migration,
            0.15,
            lambda value: max(0.0, min(1.0, 0.5 + value / max(population or 100_000, 1) * 50)),
        ),
        "permits_trailing_12m": (
            pack.permits_trailing_12m,
            0.15,
            lambda value: max(0.1, min(1.0, 0.25 + value / max(population or 100_000, 1) * 75)),
        ),
    }
    covered = [entry for entry in raw.values() if _available(entry[0])]
    confidence = len(covered) / len(raw)
    if not covered:
        return 0.0, 0.0
    weight_total = sum(weight for _, weight, _ in covered)
    weighted = sum(
        scorer(metric.value) * weight  # type: ignore[union-attr]
        for metric, weight, scorer in covered
    )
    return round(100 * weighted / weight_total, 2), round(confidence, 2)
