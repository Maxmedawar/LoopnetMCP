"""IRS SOI county migration bulk-data loader and provider."""

import asyncio
import csv
import io
import logging
import sqlite3
from pathlib import Path

from cre_mcp.access.context import current_runtime_config, resolve_runtime_config
from cre_mcp.config import CreConfig
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import AuthSpec, GovApiClient, MarketDataProvider
from cre_mcp.models.market import MetricValue
from cre_mcp.source_rights.gate import require_url
from cre_mcp.source_rights.output import safe_error_message

logger = logging.getLogger(__name__)

LATEST_MIGRATION_YEAR = "2022-2023"
COUNTY_INFLOW_URL = "https://www.irs.gov/pub/irs-soi/countyinflow2223.csv"
COUNTY_OUTFLOW_URL = "https://www.irs.gov/pub/irs-soi/countyoutflow2223.csv"


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
        config = resolve_runtime_config(config)
        self.config = config
        self.db_path = Path(db_path or config.cache_db_path).expanduser()
        self.fetch = fetch or (client.fetch if client is not None else get_fetch_client())
        self._load_lock = asyncio.Lock()
        super().__init__(
            client
            or GovApiClient(
                self.fetch,
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS soi_migration_meta (
                dataset TEXT PRIMARY KEY,
                loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        return connection

    def _authorized_cache_ttl(self) -> int:
        records = (
            require_url(COUNTY_INFLOW_URL, config=self.config),
            require_url(COUNTY_OUTFLOW_URL, config=self.config),
        )
        return min(
            int(record.operating_policy.persistent_cache_ttl_seconds)
            if record is not None
            else 0
            for record in records
        )

    def _dataset_loaded(self, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            return False
        with self._connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM soi_migration_meta
                   WHERE dataset = ?
                     AND loaded_at >= datetime('now', ?)""",
                (LATEST_MIGRATION_YEAR, f"-{ttl_seconds} seconds"),
            ).fetchone()
        return row is not None

    def _mark_dataset_loaded(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO soi_migration_meta(dataset) VALUES (?)",
                (LATEST_MIGRATION_YEAR,),
            )

    def _clear_stale_dataset(self) -> None:
        """Delete normalized rows once their authorized retention has expired."""
        with self._connect() as connection:
            connection.execute("DELETE FROM soi_migration")
            connection.execute(
                "DELETE FROM soi_migration_meta WHERE dataset = ?",
                (LATEST_MIGRATION_YEAR,),
            )

    def _load_csv(
        self,
        text: str,
        direction: str | None,
        year: str | None,
        persist: bool,
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
        if persist:
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
        runtime = current_runtime_config()
        if runtime is not None and runtime is not self.config:
            return await IrsSoiProvider(config=runtime).load_csv(
                text,
                direction=direction,
                year=year,
            )
        cache_ttl = self._authorized_cache_ttl()
        count = await asyncio.to_thread(
            self._load_csv,
            text,
            direction,
            year,
            cache_ttl > 0,
        )
        if count > 0 and cache_ttl > 0:
            await asyncio.to_thread(self._mark_dataset_loaded)
        return count

    async def _ensure_latest_loaded(self, cache_ttl: int) -> None:
        if await asyncio.to_thread(self._dataset_loaded, cache_ttl):
            return
        async with self._load_lock:
            if await asyncio.to_thread(self._dataset_loaded, cache_ttl):
                return
            await asyncio.to_thread(self._clear_stale_dataset)
            inflow, outflow = await asyncio.gather(
                self.fetch.get_text(COUNTY_INFLOW_URL),
                self.fetch.get_text(COUNTY_OUTFLOW_URL),
            )
            await self.load_csv(
                inflow,
                direction="inflow",
                year=LATEST_MIGRATION_YEAR,
            )
            await self.load_csv(
                outflow,
                direction="outflow",
                year=LATEST_MIGRATION_YEAR,
            )
            if cache_ttl > 0:
                await asyncio.to_thread(self._mark_dataset_loaded)

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
        runtime = current_runtime_config()
        if runtime is not None and runtime is not self.config:
            return await IrsSoiProvider(config=runtime).net_migration(county_fips)
        cache_ttl = self._authorized_cache_ttl()
        dataset_fresh = await asyncio.to_thread(self._dataset_loaded, cache_ttl)
        row = (
            await asyncio.to_thread(self._net_migration, county_fips)
            if dataset_fresh
            else None
        )
        if row is None and county_fips:
            try:
                await self._ensure_latest_loaded(cache_ttl)
                if cache_ttl > 0:
                    row = await asyncio.to_thread(self._net_migration, county_fips)
            except Exception as exc:
                logger.warning(
                    "IRS SOI migration data unavailable: %s",
                    safe_error_message(exc),
                )
        return MetricValue(
            value=row[0] if row else None,
            unit="people",
            as_of=row[1] if row else None,
            source="IRS SOI County Migration",
        )


IRSSOIProvider = IrsSoiProvider
