"""Census ACS and building-permits provider."""

import logging
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import AuthSpec, GovApiClient, MarketDataProvider
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.market import MetricValue

logger = logging.getLogger(__name__)

ACS_VARIABLES = {
    "population": "B01003_001E",
    "median_hh_income": "B19013_001E",
    "median_gross_rent": "B25064_001E",
    "vacant_for_rent": "B25004_002E",
    "renter_occupied": "B25003_003E",
    "occupied_housing": "B25003_001E",
}


def _number(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return None if result < -1_000_000 else result


def _geo_params(geo: GeoRef) -> dict[str, str]:
    if geo.county_fips:
        return {
            "for": f"county:{geo.county_fips[-3:]}",
            "in": f"state:{geo.state_fips}",
        }
    if geo.zip:
        return {"for": f"zip code tabulation area:{geo.zip}"}
    return {"for": f"state:{geo.state_fips}"}


class CensusProvider(MarketDataProvider):
    """Normalized annual Census ACS metrics."""

    name = "census"

    def __init__(
        self,
        client: GovApiClient | None = None,
        *,
        config: CreConfig | None = None,
        fetch: FetchClient | None = None,
    ):
        config = config or CreConfig()
        super().__init__(
            client
            or GovApiClient(
                fetch or get_fetch_client(),
                AuthSpec(
                    kind="query_param",
                    param_name="key",
                    secret=config.census_api_key,
                ),
                "https://api.census.gov/data",
            )
        )

    async def acs5_profile(
        self,
        geo: GeoRef,
        year: int,
    ) -> dict[str, MetricValue]:
        """Fetch core population, income, rent, vacancy, and tenure metrics."""
        variable_names = list(ACS_VARIABLES.values())
        params = {"get": ",".join(["NAME", *variable_names]), **_geo_params(geo)}
        payload = await self.client.get(f"{year}/acs/acs5", params)
        if not isinstance(payload, list) or len(payload) < 2:
            raise ValueError("Census ACS response did not contain a data row")
        headers = payload[0]
        values = payload[1]
        row = dict(zip(headers, values, strict=False))

        population = _number(row.get(ACS_VARIABLES["population"]))
        income = _number(row.get(ACS_VARIABLES["median_hh_income"]))
        rent = _number(row.get(ACS_VARIABLES["median_gross_rent"]))
        vacant = _number(row.get(ACS_VARIABLES["vacant_for_rent"]))
        renters = _number(row.get(ACS_VARIABLES["renter_occupied"]))
        occupied = _number(row.get(ACS_VARIABLES["occupied_housing"]))
        rental_vacancy = (
            100 * vacant / (vacant + renters)
            if vacant is not None and renters is not None and vacant + renters > 0
            else None
        )
        renter_share = (
            100 * renters / occupied
            if renters is not None and occupied is not None and occupied > 0
            else None
        )
        as_of = str(year)
        return {
            "population": MetricValue(
                value=population, unit="people", as_of=as_of, source="Census ACS 5-year"
            ),
            "median_hh_income": MetricValue(
                value=income, unit="USD/year", as_of=as_of, source="Census ACS 5-year"
            ),
            "median_gross_rent": MetricValue(
                value=rent, unit="USD/month", as_of=as_of, source="Census ACS 5-year"
            ),
            "rental_vacancy": MetricValue(
                value=rental_vacancy, unit="percent", as_of=as_of, source="Census ACS 5-year"
            ),
            "renter_share": MetricValue(
                value=renter_share, unit="percent", as_of=as_of, source="Census ACS 5-year"
            ),
        }

    async def building_permits(
        self,
        geo: GeoRef,
        year: int,
    ) -> MetricValue:
        """Return summed permits from the Census BPS time-series helper."""
        params = {
            "get": "PERIOD,PERMITS",
            "time": f"from {year}-01 to {year}-12",
            **_geo_params(geo),
        }
        payload = await self.client.get("timeseries/eits/bp", params)
        if not isinstance(payload, list) or len(payload) < 2:
            raise ValueError("Census BPS response did not contain permit rows")
        headers = payload[0]
        total = 0.0
        latest: str | None = None
        found = False
        for values in payload[1:]:
            row = dict(zip(headers, values, strict=False))
            permits = _number(row.get("PERMITS"))
            if permits is not None:
                total += permits
                found = True
            latest = max(latest or "", str(row.get("PERIOD", ""))) or latest
        return MetricValue(
            value=total if found else None,
            unit="housing units",
            as_of=latest or str(year),
            source="Census Building Permits Survey",
        )

