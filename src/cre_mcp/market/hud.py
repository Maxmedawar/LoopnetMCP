"""HUD USER Fair Market Rent and income-limit provider."""

from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import (
    AuthSpec,
    GovApiClient,
    MarketDataProvider,
    ProviderUnavailableError,
)
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.market import MetricValue


def _find_number(payload: Any, keys: tuple[str, ...]) -> float | None:
    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                try:
                    return float(str(payload[key]).replace(",", "").replace("$", ""))
                except (TypeError, ValueError):
                    pass
        for value in payload.values():
            found = _find_number(value, keys)
            if found is not None:
                return found
    return None


class HudProvider(MarketDataProvider):
    """HUD rent and income benchmarks."""

    name = "hud"

    def __init__(
        self,
        client: GovApiClient | None = None,
        *,
        config: CreConfig | None = None,
        fetch: FetchClient | None = None,
    ):
        config = config or CreConfig()
        self._has_key = bool(client is not None or config.hud_api_token is not None)
        super().__init__(
            client
            or GovApiClient(
                fetch or get_fetch_client(),
                AuthSpec(kind="bearer", secret=config.hud_api_token),
                "https://www.huduser.gov/hudapi/public",
            )
        )

    @staticmethod
    def _geo_id(geo: GeoRef) -> str:
        value = geo.cbsa or geo.county_fips or geo.zip
        if not value:
            raise ValueError("HUD lookup requires CBSA, county, or ZIP geography")
        return value

    async def fmr(self, geo: GeoRef, year: int) -> MetricValue:
        """Return HUD two-bedroom Fair Market Rent."""
        if not self._has_key:
            raise ProviderUnavailableError("HUD API token is not configured")
        payload = await self.client.get(
            f"fmr/data/{self._geo_id(geo)}", {"year": year}
        )
        value = _find_number(
            payload,
            ("Two-Bedroom", "two_bedroom", "fmr_2", "fmr2", "FMR_2"),
        )
        return MetricValue(
            value=value,
            unit="USD/month",
            as_of=str(year),
            source="HUD Fair Market Rents",
        )

    async def fmr_by_bedroom(
        self,
        geo: GeoRef,
        year: int,
    ) -> dict[int, MetricValue]:
        """Return every available HUD FMR bedroom tier from zero through four."""
        if not self._has_key:
            raise ProviderUnavailableError("HUD API token is not configured")
        payload = await self.client.get(
            f"fmr/data/{self._geo_id(geo)}", {"year": year}
        )
        keys = {
            0: ("Efficiency", "efficiency", "fmr_0", "fmr0", "FMR_0"),
            1: ("One-Bedroom", "one_bedroom", "fmr_1", "fmr1", "FMR_1"),
            2: ("Two-Bedroom", "two_bedroom", "fmr_2", "fmr2", "FMR_2"),
            3: ("Three-Bedroom", "three_bedroom", "fmr_3", "fmr3", "FMR_3"),
            4: ("Four-Bedroom", "four_bedroom", "fmr_4", "fmr4", "FMR_4"),
        }
        return {
            bedrooms: MetricValue(
                value=value,
                unit="USD/month",
                as_of=str(year),
                source="HUD Fair Market Rents",
            )
            for bedrooms, candidates in keys.items()
            if (value := _find_number(payload, candidates)) is not None
        }

    async def income_limits(self, geo: GeoRef, year: int) -> MetricValue:
        """Return HUD area median family income."""
        if not self._has_key:
            raise ProviderUnavailableError("HUD API token is not configured")
        payload = await self.client.get(
            f"il/data/{self._geo_id(geo)}", {"year": year}
        )
        value = _find_number(
            payload,
            ("median_income", "medianIncome", "Median Income", "median_family_income"),
        )
        return MetricValue(
            value=value,
            unit="USD/year",
            as_of=str(year),
            source="HUD Income Limits",
        )


HUDProvider = HudProvider
