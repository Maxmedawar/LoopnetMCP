"""Keyless FHFA house-price trend provider."""

import csv
import io
import math

from cre_mcp.geo.constants import STATE_FIPS
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.market import MetricValue

STATE_HPI_URL = (
    "https://www.fhfa.gov/hpi/download/quarterly_datasets/hpi_at_state.csv"
)
_STATE_BY_FIPS = {fips: abbreviation for abbreviation, fips in STATE_FIPS.items()}


class FhfaProvider:
    """Read FHFA's public quarterly state All-Transactions HPI dataset."""

    name = "fhfa"

    def __init__(self, fetch: FetchClient | None = None):
        self.fetch = fetch or get_fetch_client()

    async def hpi_growth(self, geo: GeoRef) -> MetricValue | None:
        """Return the latest year-over-year state HPI change without an API key."""
        state = _STATE_BY_FIPS.get(geo.state_fips)
        if state is None:
            return None
        payload = await self.fetch.get_text(STATE_HPI_URL)
        points: list[tuple[int, int, float]] = []
        for row in csv.reader(io.StringIO(payload)):
            if len(row) < 4 or row[0].strip().upper() != state:
                continue
            try:
                points.append((int(row[1]), int(row[2]), float(row[3])))
            except (TypeError, ValueError):
                continue
        points.sort()
        if len(points) < 2:
            return None
        latest_year, latest_quarter, latest_index = points[-1]
        prior = next(
            (
                index
                for year, quarter, index in reversed(points[:-1])
                if (year, quarter) == (latest_year - 1, latest_quarter)
            ),
            None,
        )
        if prior is None or prior <= 0 or latest_index <= 0:
            return None
        growth = (math.pow(latest_index / prior, 1.0) - 1) * 100
        return MetricValue(
            value=growth,
            unit="percent year-over-year",
            as_of=f"{latest_year}-Q{latest_quarter}",
            source=(
                "FHFA All-Transactions HPI, state series "
                "(public residential-market trend proxy)"
            ),
        )


FHFAProvider = FhfaProvider
