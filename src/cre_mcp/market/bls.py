"""BLS QCEW employment and LAUS unemployment provider."""

from datetime import UTC, datetime
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import AuthSpec, GovApiClient, MarketDataProvider
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.market import MetricSeries


def _period_date(year: str, period: str) -> str:
    if period.startswith("M") and period[1:].isdigit():
        return f"{year}-{period[1:]}"
    if period.startswith("Q") and period[1:].isdigit():
        return f"{year}-{period}"
    return year


def _series(payload: Any, unit: str, source: str) -> MetricSeries:
    try:
        data = payload["Results"]["series"][0]["data"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("BLS response did not contain a series") from exc
    points: list[tuple[str, float]] = []
    for row in data:
        try:
            value = float(str(row["value"]).replace(",", ""))
        except (KeyError, TypeError, ValueError):
            continue
        points.append((_period_date(str(row["year"]), str(row["period"])), value))
    points.sort(key=lambda point: point[0])
    return MetricSeries(points=points, unit=unit, source=source)


class BlsProvider(MarketDataProvider):
    """County-level employment and unemployment series."""

    name = "bls"

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
                    kind="body_field",
                    param_name="registrationkey",
                    secret=config.bls_api_key,
                ),
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            )
        )

    @staticmethod
    def _years() -> tuple[str, str]:
        end = datetime.now(UTC).year
        # Include a full five-year comparison even when the current year's
        # QCEW release has not begun yet.
        return str(end - 7), str(end)

    async def laus_unemployment(self, geo: GeoRef) -> MetricSeries:
        """Return the BLS LAUS county unemployment-rate series."""
        if not geo.county_fips:
            raise ValueError("LAUS unemployment requires a county FIPS")
        start, end = self._years()
        payload = await self.client.post(
            "",
            {
                "seriesid": [f"LAUCN{geo.county_fips}0000000003"],
                "startyear": start,
                "endyear": end,
            },
        )
        return _series(payload, "percent", "BLS LAUS")

    async def qcew_employment(self, geo: GeoRef) -> MetricSeries:
        """Return the BLS QCEW county employment series."""
        if not geo.county_fips:
            raise ValueError("QCEW employment requires a county FIPS")
        start, end = self._years()
        payload = await self.client.post(
            "",
            {
                # ENU + county + datatype=1 (all employees), size=0,
                # ownership=0 (all), industry=10 (total, all industries).
                "seriesid": [f"ENU{geo.county_fips}10010"],
                "startyear": start,
                "endyear": end,
            },
        )
        return _series(payload, "jobs", "BLS QCEW")


BLSProvider = BlsProvider
