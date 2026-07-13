"""IRS SOI county migration bulk-data loader and provider."""

import asyncio
import csv
import io
import sqlite3
from pathlib import Path

from cre_mcp.config import CreConfig
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import AuthSpec, GovApiClient, MarketDataProvider
from cre_mcp.models.market import MetricValue


def _float(value: str | None) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


class IrsSoiProvider(MarketDataProvider):
    """Persistent access to normalized IRS SOI county migration bulk data."""

    name = "irs_soi"

    def __init__(
        self,
        client: GovApiClient | None = None,
        *,
        config: CreConfig | None = None,
        fetch: FetchClient | None = None,
        db_path: str | Path | None = None,
    ):
        config = config or CreConfig()
        self.db_path = Path(db_path or config.cache_db_path).expanduser()
        super().__init__(
            client
            or GovApiClient(
                fetch or get_fetch_client(),
                AuthSpec(kind="none"),
                "https://www.irs.gov/statistics/soi-tax-stats-migration-data",
            )
        )

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS soi_migration (
                county_fips TEXT NOT NULL,
                year TEXT NOT NULL,
                inflow_returns REAL NOT NULL,
                outflow_returns REAL NOT NULL,
                inflow_exemptions REAL NOT NULL,
                outflow_exemptions REAL NOT NULL,
                inflow_agi REAL NOT NULL,
                outflow_agi REAL NOT NULL,
                PRIMARY KEY (county_fips, year)
            )
            """
        )
        return connection

    def _load_csv(
        self,
        text: str,
        direction: str | None,
        year: str | None,
    ) -> int:
        reader = csv.DictReader(io.StringIO(text))
        rows = [
            {str(key).casefold(): value for key, value in row.items()}
            for row in reader
        ]
        fieldnames = [str(name).casefold() for name in (reader.fieldnames or [])]
        normalized = "county_fips" in fieldnames
        if not normalized and direction is None:
            if fieldnames and fieldnames[0] == "y2_statefips":
                direction = "inflow"
            elif fieldnames and fieldnames[0] == "y1_statefips":
                direction = "outflow"
        values = []
        if normalized:
            for row in rows:
                county = str(row.get("county_fips", "")).zfill(5)
                row_year = str(row.get("year", year or ""))
                if not county.strip("0") or not row_year:
                    continue
                values.append(
                    (
                        county,
                        row_year,
                        _float(row.get("inflow_returns")),
                        _float(row.get("outflow_returns")),
                        _float(row.get("inflow_exemptions")),
                        _float(row.get("outflow_exemptions")),
                        _float(row.get("inflow_agi")),
                        _float(row.get("outflow_agi")),
                    )
                )
        elif direction in {"inflow", "outflow"}:
            # Official IRS files contain a 96/000 total-migration row per county.
            target_prefix = "y2" if direction == "inflow" else "y1"
            other_prefix = "y1" if direction == "inflow" else "y2"
            for row in rows:
                if str(row.get(f"{other_prefix}_statefips", "")) != "96":
                    continue
                if str(row.get(f"{other_prefix}_countyfips", "")).zfill(3) != "000":
                    continue
                state = str(row.get(f"{target_prefix}_statefips", "")).zfill(2)
                county = str(row.get(f"{target_prefix}_countyfips", "")).zfill(3)
                if not state.strip("0") or county == "000":
                    continue
                inflow = direction == "inflow"
                values.append(
                    (
                        state + county,
                        year or "latest",
                        _float(row.get("n1")) if inflow else 0,
                        _float(row.get("n1")) if not inflow else 0,
                        _float(row.get("n2")) if inflow else 0,
                        _float(row.get("n2")) if not inflow else 0,
                        _float(row.get("agi")) if inflow else 0,
                        _float(row.get("agi")) if not inflow else 0,
                    )
                )
        else:
            raise ValueError("Could not determine whether IRS CSV is inflow or outflow")
        with self._connect() as connection:
            if normalized:
                connection.executemany(
                    """
                    INSERT INTO soi_migration VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(county_fips, year) DO UPDATE SET
                        inflow_returns=excluded.inflow_returns,
                        outflow_returns=excluded.outflow_returns,
                        inflow_exemptions=excluded.inflow_exemptions,
                        outflow_exemptions=excluded.outflow_exemptions,
                        inflow_agi=excluded.inflow_agi,
                        outflow_agi=excluded.outflow_agi
                    """,
                    values,
                )
            elif direction == "inflow":
                connection.executemany(
                    """
                    INSERT INTO soi_migration VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(county_fips, year) DO UPDATE SET
                        inflow_returns=excluded.inflow_returns,
                        inflow_exemptions=excluded.inflow_exemptions,
                        inflow_agi=excluded.inflow_agi
                    """,
                    values,
                )
            else:
                connection.executemany(
                    """
                    INSERT INTO soi_migration VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(county_fips, year) DO UPDATE SET
                        outflow_returns=excluded.outflow_returns,
                        outflow_exemptions=excluded.outflow_exemptions,
                        outflow_agi=excluded.outflow_agi
                    """,
                    values,
                )
        return len(values)

    async def load_csv(
        self,
        text: str,
        *,
        direction: str | None = None,
        year: str | None = None,
    ) -> int:
        """Load normalized or official IRS county inflow/outflow CSV data."""
        return await asyncio.to_thread(self._load_csv, text, direction, year)

    def _net_migration(self, county_fips: str) -> tuple[float, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT inflow_exemptions - outflow_exemptions, year
                   FROM soi_migration
                   WHERE county_fips = ?
                   ORDER BY year DESC
                   LIMIT 1""",
                (county_fips.zfill(5),),
            ).fetchone()
        return (float(row[0]), str(row[1])) if row else None

    async def net_migration(self, county_fips: str) -> MetricValue:
        """Return latest net exemptions, used as a people-migration proxy."""
        row = await asyncio.to_thread(self._net_migration, county_fips)
        return MetricValue(
            value=row[0] if row else None,
            unit="people",
            as_of=row[1] if row else None,
            source="IRS SOI County Migration",
        )


IRSSOIProvider = IrsSoiProvider
