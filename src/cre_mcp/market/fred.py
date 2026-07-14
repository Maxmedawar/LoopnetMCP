"""FRED interest-rate provider."""

from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import (
    AuthSpec,
    GovApiClient,
    MarketDataProvider,
    ProviderUnavailableError,
)
from cre_mcp.models.market import MetricSeries


class FredProvider(MarketDataProvider):
    """FRED series observations authenticated by API-key query parameter."""

    name = "fred"

    def __init__(
        self,
        client: GovApiClient | None = None,
        *,
        config: CreConfig | None = None,
        fetch: FetchClient | None = None,
    ):
        config = config or CreConfig()
        self._has_key = bool(
            client is not None or config.fred_api_key is not None
        )
        super().__init__(
            client
            or GovApiClient(
                fetch or get_fetch_client(),
                AuthSpec(
                    kind="query_param",
                    param_name="api_key",
                    secret=config.fred_api_key,
                ),
                "https://api.stlouisfed.org/fred",
            )
        )

    async def series(self, series_id: str) -> MetricSeries:
        """Return numeric observations for a FRED series."""
        if not self._has_key:
            raise ProviderUnavailableError("FRED API key is not configured")
        payload = await self.client.get(
            "series/observations",
            {"series_id": series_id, "file_type": "json", "sort_order": "asc"},
        )
        observations = payload.get("observations", []) if isinstance(payload, dict) else []
        points: list[tuple[str, float]] = []
        for row in observations:
            try:
                points.append((str(row["date"]), float(row["value"])))
            except (KeyError, TypeError, ValueError):
                continue
        return MetricSeries(points=points, unit="percent", source=f"FRED {series_id}")


FREDProvider = FredProvider
