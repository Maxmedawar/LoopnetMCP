"""Free and optional paid rent-comparable assembly."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
from datetime import UTC, datetime
from statistics import median
from typing import Any
from urllib.parse import urlencode

from cre_mcp.config import CreConfig
from cre_mcp.geo.resolver import STATE_FIPS
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import ProviderUnavailableError
from cre_mcp.market.census import CensusProvider
from cre_mcp.market.hud import HudProvider
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.market import (
    MarketPack,
    MetricValue,
    RentComparable,
    RentComps,
)

logger = logging.getLogger(__name__)

ZORI_ZIP_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zori/"
    "Zip_zori_uc_sfrcondomfr_sm_month.csv"
)
ZORI_METRO_URL = (
    "https://files.zillowstatic.com/research/public_csvs/zori/"
    "Metro_zori_uc_sfrcondomfr_sm_month.csv"
)
_STATE_BY_FIPS = {fips: state for state, fips in STATE_FIPS.items()}
_DATE_COLUMN = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")
_RENTCAST_PROPERTY_TYPES = {
    "single family": "Single Family",
    "single-family": "Single Family",
    "condo": "Condo",
    "townhouse": "Townhouse",
    "manufactured": "Manufactured",
    "multifamily": "Multi-Family",
    "multi-family": "Multi-Family",
    "apartment": "Apartment",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _available(metric: MetricValue | None) -> bool:
    return metric is not None and metric.value is not None


def _location_city(location: str, geo: GeoRef) -> str:
    candidate = location.split(",", 1)[0].strip()
    if re.fullmatch(r"\d{5}", candidate) or candidate.upper() in STATE_FIPS:
        candidate = geo.name.split(",", 1)[0].strip()
    return re.sub(r"\s+city$", "", candidate, flags=re.IGNORECASE)


class ZoriProvider:
    """Read Zillow's monthly public ZORI research CSV through FetchClient cache."""

    name = "zillow_zori"

    def __init__(self, fetch: FetchClient | None = None):
        self.fetch = fetch or get_fetch_client()

    @staticmethod
    def _matches(row: dict[str, str], geo: GeoRef, location: str) -> bool:
        if geo.zip:
            return row.get("RegionName") == geo.zip
        state = _STATE_BY_FIPS.get(geo.state_fips)
        city = _location_city(location, geo).casefold()
        region = str(row.get("RegionName", "")).casefold()
        return bool(
            city
            and (region == city or region.startswith(f"{city},"))
            and (not state or row.get("StateName") == state)
        )

    async def metrics(
        self,
        geo: GeoRef,
        location: str,
    ) -> tuple[MetricValue | None, MetricValue | None]:
        """Return the latest ZORI level and year-over-year change."""
        url = ZORI_ZIP_URL if geo.zip else ZORI_METRO_URL
        text = await self.fetch.get_text(url)
        row = next(
            (
                item
                for item in csv.DictReader(io.StringIO(text))
                if self._matches(item, geo, location)
            ),
            None,
        )
        if row is None:
            return None, None
        observations = sorted(
            (key, value)
            for key, raw in row.items()
            if _DATE_COLUMN.fullmatch(key) and (value := _number(raw)) is not None
        )
        if not observations:
            return None, None
        latest_date, latest_value = observations[-1]
        level = "ZIP" if geo.zip else "metro"
        zori = MetricValue(
            value=latest_value,
            unit="USD/month",
            as_of=latest_date,
            source=f"Zillow ZORI ({level})",
        )
        yoy = None
        if len(observations) >= 13 and observations[-13][1] > 0:
            yoy = MetricValue(
                value=100 * (latest_value / observations[-13][1] - 1),
                unit="percent YoY",
                as_of=latest_date,
                source=f"Zillow ZORI ({level})",
            )
        return zori, yoy


class RentCastProvider:
    """Optional RentCast rent AVM and active-listing comparable provider."""

    name = "rentcast"
    base_url = "https://api.rentcast.io/v1"

    def __init__(
        self,
        config: CreConfig | None = None,
        *,
        fetch: FetchClient | None = None,
    ):
        self.config = config or CreConfig()
        self.fetch = fetch or get_fetch_client()
        self._key = (
            self.config.rentcast_api_key.get_secret_value()
            if self.config.rentcast_api_key is not None
            else None
        )

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _headers(self) -> dict[str, str]:
        if not self._key:
            raise ProviderUnavailableError("RentCast API key is not configured")
        return {"X-Api-Key": self._key}

    async def comparables(
        self,
        location: str,
        geo: GeoRef,
        *,
        address: str | None = None,
        bedrooms: int | None = None,
        property_type: str | None = None,
    ) -> tuple[MetricValue | None, list[RentComparable]]:
        """Return RentCast's AVM when addressable, otherwise active rentals."""
        params: dict[str, Any] = {}
        if bedrooms is not None:
            params["bedrooms"] = bedrooms
        if property_type:
            params["propertyType"] = _RENTCAST_PROPERTY_TYPES.get(
                property_type.casefold().strip(),
                property_type,
            )
        if address:
            params["address"] = address
            params["compCount"] = 10
            path = "avm/rent/long-term"
        else:
            if geo.zip:
                params["zipCode"] = geo.zip
            else:
                parts = [part.strip() for part in location.rsplit(",", 1)]
                if len(parts) == 2:
                    params["city"], params["state"] = parts
                else:
                    raise ValueError("RentCast market lookup requires city/state or ZIP")
            params["limit"] = 25
            path = "listings/rental/long-term"
        payload = await self.fetch.get_json(
            f"{self.base_url}/{path}?{urlencode(params)}",
            headers=self._headers(),
        )
        if isinstance(payload, dict):
            rent = _number(payload.get("rent"))
            rows = payload.get("comparables")
        else:
            rent = None
            rows = payload
        comparables: list[RentComparable] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                price = _number(row.get("price") or row.get("rent"))
                if price is None:
                    continue
                comparable_bedrooms = _number(row.get("bedrooms"))
                comparables.append(
                    RentComparable(
                        source="RentCast",
                        rent=price,
                        location=row.get("formattedAddress"),
                        bedrooms=(
                            int(comparable_bedrooms)
                            if comparable_bedrooms is not None
                            else None
                        ),
                        property_type=row.get("propertyType"),
                        as_of=row.get("lastSeenDate") or row.get("listedDate"),
                    )
                )
        if rent is None and comparables:
            rent = median(item.rent for item in comparables)
        metric = (
            MetricValue(
                value=rent,
                unit="USD/month",
                source="RentCast rent estimate",
            )
            if rent is not None
            else None
        )
        return metric, comparables


class RentCompsService:
    """Assemble partial rent comps without allowing one provider to abort the pack."""

    def __init__(
        self,
        config: CreConfig | None = None,
        *,
        zori: ZoriProvider | None = None,
        census: CensusProvider | None = None,
        hud: HudProvider | None = None,
        rentcast: RentCastProvider | None = None,
    ):
        self.config = config or CreConfig()
        self.zori = zori or ZoriProvider()
        self.census = census or CensusProvider(config=self.config)
        self.hud = hud or HudProvider(config=self.config)
        self.rentcast = rentcast or RentCastProvider(config=self.config)

    async def _safe(self, label: str, operation: Any) -> Any | None:
        try:
            return await operation
        except Exception as exc:
            logger.warning("Rent provider %s unavailable: %s", label, exc)
            return None

    async def get_rent_comps(
        self,
        location: str,
        geo: GeoRef,
        *,
        bedrooms: int | None = None,
        property_type: str | None = None,
        address: str | None = None,
        market_pack: MarketPack | None = None,
    ) -> RentComps:
        """Return a coverage-aware blend of ZORI, ACS, HUD, and optional RentCast."""
        latest_year = datetime.now(UTC).year - 2
        zori_result, census_result, hud_result = await asyncio.gather(
            self._safe("zillow_zori", self.zori.metrics(geo, location)),
            self._safe(
                "census_acs",
                self.census.acs5_profile(geo, latest_year),
            )
            if market_pack is None
            else asyncio.sleep(0, result=None),
            self._safe("hud_fmr", self.hud.fmr_by_bedroom(geo, latest_year))
            if market_pack is None
            else asyncio.sleep(0, result=None),
        )
        zori, zori_yoy = (
            zori_result
            if isinstance(zori_result, tuple)
            else (None, None)
        )
        if market_pack is not None:
            median_gross_rent = market_pack.median_gross_rent
            fmr_by_bedroom = (
                {2: market_pack.fmr_2br} if _available(market_pack.fmr_2br) else {}
            )
        else:
            census_metrics = census_result if isinstance(census_result, dict) else {}
            median_gross_rent = census_metrics.get("median_gross_rent")
            fmr_by_bedroom = hud_result if isinstance(hud_result, dict) else {}

        rentcast_metric = None
        rentcast_comps: list[RentComparable] = []
        if self.rentcast.available:
            paid = await self._safe(
                "rentcast",
                self.rentcast.comparables(
                    location,
                    geo,
                    address=address,
                    bedrooms=bedrooms,
                    property_type=property_type,
                ),
            )
            if isinstance(paid, tuple):
                rentcast_metric, rentcast_comps = paid

        selected_fmr = fmr_by_bedroom.get(bedrooms) if bedrooms is not None else None
        market_rent = next(
            (
                metric
                for metric in (rentcast_metric, selected_fmr, zori, median_gross_rent)
                if _available(metric)
            ),
            None,
        )
        comparables = list(rentcast_comps)
        for label, metric in (
            ("Zillow ZORI", zori),
            ("Census ACS", median_gross_rent),
            ("HUD FMR", selected_fmr),
        ):
            if _available(metric):
                assert metric is not None and metric.value is not None
                comparables.append(
                    RentComparable(
                        source=label,
                        rent=metric.value,
                        location=location,
                        bedrooms=bedrooms if label == "HUD FMR" else None,
                        property_type=property_type,
                        as_of=metric.as_of,
                    )
                )
        coverage = {
            "zillow_zori": _available(zori),
            "census_acs": _available(median_gross_rent),
            "hud_fmr": bool(fmr_by_bedroom),
            "rentcast": _available(rentcast_metric) or bool(rentcast_comps),
        }
        sources = [name for name, present in coverage.items() if present]
        return RentComps(
            geo=geo,
            market_rent_estimate=market_rent,
            rent_index=zori,
            rent_trend_yoy=zori_yoy,
            median_gross_rent=median_gross_rent,
            fmr_by_bedroom=fmr_by_bedroom,
            comps=comparables,
            coverage=coverage,
            source=sources,
        )


__all__ = [
    "RentCastProvider",
    "RentCompsService",
    "ZORI_METRO_URL",
    "ZORI_ZIP_URL",
    "ZoriProvider",
]
