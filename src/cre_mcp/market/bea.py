"""BEA Regional economic-series provider."""

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
from cre_mcp.models.market import MetricSeries


class BeaProvider(MarketDataProvider):
    """BEA county/CBSA GDP and personal-income series."""

    name = "bea"

    def __init__(
        self,
        client: GovApiClient | None = None,
        *,
        config: CreConfig | None = None,
        fetch: FetchClient | None = None,
    ):
        config = config or CreConfig()
        self._has_key = bool(client is not None or config.bea_api_key is not None)
        super().__init__(
            client
            or GovApiClient(
                fetch or get_fetch_client(),
                AuthSpec(
                    kind="query_param",
                    param_name="UserID",
                    secret=config.bea_api_key,
                ),
                "https://apps.bea.gov/api/data/",
            )
        )

    async def regional(self, geo: GeoRef, table: str) -> MetricSeries:
        """Return one BEA Regional table as a normalized numeric series."""
        if not self._has_key:
            raise ProviderUnavailableError("BEA API key is not configured")
        geo_fips = geo.county_fips or geo.cbsa or geo.state_fips
        payload = await self.client.get(
            "",
            {
                "method": "GetData",
                "datasetname": "Regional",
                "TableName": table,
                "LineCode": 1,
                "GeoFIPS": geo_fips,
                "Year": "X",
                "ResultFormat": "JSON",
            },
        )
        try:
            rows = payload["BEAAPI"]["Results"]["Data"]
        except (KeyError, TypeError) as exc:
            raise ValueError("BEA response did not contain Regional data") from exc
        points: list[tuple[str, float]] = []
        unit = "USD thousands"
        for row in rows if isinstance(rows, list) else []:
            try:
                value = float(str(row["DataValue"]).replace(",", ""))
                points.append((str(row["TimePeriod"]), value))
                unit = str(row.get("CL_UNIT") or unit)
            except (KeyError, TypeError, ValueError):
                continue
        points.sort(key=lambda point: point[0])
        return MetricSeries(points=points, unit=unit, source=f"BEA Regional {table}")


BEAProvider = BeaProvider
