"""HUD USPS ZIP-to-county and ZIP-to-CBSA crosswalk persistence."""

import asyncio
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from cre_mcp.access.context import resolve_runtime_config
from cre_mcp.config import CreConfig
from cre_mcp.geo.constants import ZIP_COUNTY_CBSA
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.market.base import AuthSpec, GovApiClient
from cre_mcp.source_rights.gate import require_url
from cre_mcp.source_rights.output import safe_error_message

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 120 * 24 * 60 * 60

STATIC_CROSSWALK: dict[str, tuple[str, str]] = ZIP_COUNTY_CBSA


def _secret_value(secret: SecretStr | str | None) -> str | None:
    return secret.get_secret_value() if isinstance(secret, SecretStr) else secret


class GeoCrosswalk:
    """Lazy, persistent HUD USPS crosswalk with a keyless static fallback."""

    def __init__(
        self,
        config: CreConfig | None = None,
        *,
        fetch: FetchClient | None = None,
        db_path: str | Path | None = None,
        hud_token: SecretStr | str | None = None,
    ):
        self.config = resolve_runtime_config(config)
        self.db_path = Path(db_path or self.config.cache_db_path).expanduser()
        token = hud_token if hud_token is not None else self.config.hud_api_token
        self._token = _secret_value(token)
        self.client = GovApiClient(
            fetch or get_fetch_client(),
            AuthSpec(kind="bearer", secret=self._token),
            "https://www.huduser.gov/hudapi/public",
        )

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS xwalk_zip_county (
                zip TEXT NOT NULL,
                county_fips TEXT NOT NULL,
                res_ratio REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (zip, county_fips)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS xwalk_zip_cbsa (
                zip TEXT NOT NULL,
                cbsa TEXT NOT NULL,
                res_ratio REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (zip, cbsa)
            )
            """
        )
        return connection

    def _lookup(self, table: str, value_column: str, zip_code: str) -> tuple[str, float] | None:
        with self._connect() as connection:
            row = connection.execute(
                f"""SELECT {value_column}, updated_at
                    FROM {table}
                    WHERE zip = ?
                    ORDER BY res_ratio DESC
                    LIMIT 1""",
                (zip_code,),
            ).fetchone()
        return (str(row[0]), float(row[1])) if row else None

    def _store(
        self,
        table: str,
        value_column: str,
        zip_code: str,
        rows: list[tuple[str, float]],
    ) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.execute(f"DELETE FROM {table} WHERE zip = ?", (zip_code,))
            connection.executemany(
                f"""INSERT INTO {table}(zip, {value_column}, res_ratio, updated_at)
                    VALUES (?, ?, ?, ?)""",
                [(zip_code, value, ratio, now) for value, ratio in rows],
            )

    def _delete(self, table: str, zip_code: str) -> None:
        with self._connect() as connection:
            connection.execute(f"DELETE FROM {table} WHERE zip = ?", (zip_code,))

    @staticmethod
    def _results(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        data = payload.get("data", payload)
        if isinstance(data, dict):
            data = data.get("results", data.get("data", []))
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    async def _refresh(
        self,
        zip_code: str,
        *,
        crosswalk_type: int,
        table: str,
        value_column: str,
        cache_ttl_seconds: int,
    ) -> str | None:
        try:
            payload = await self.client.get(
                "usps",
                {"type": crosswalk_type, "query": zip_code},
            )
            rows: list[tuple[str, float]] = []
            for item in self._results(payload):
                value = item.get("geoid") or item.get(value_column)
                if value is None:
                    continue
                ratio = item.get("res_ratio", item.get("resRatio", 0))
                try:
                    rows.append((str(value).zfill(5), float(ratio)))
                except (TypeError, ValueError):
                    logger.warning("Ignoring malformed HUD crosswalk row")
            if rows:
                if cache_ttl_seconds > 0:
                    await asyncio.to_thread(
                        self._store,
                        table,
                        value_column,
                        zip_code,
                        rows,
                    )
                return max(rows, key=lambda row: row[1])[0]
        except Exception as exc:
            logger.warning(
                "HUD crosswalk refresh failed for ZIP %s: %s",
                zip_code,
                safe_error_message(exc),
            )
        return None

    async def _resolve(
        self,
        zip_code: str,
        *,
        static_index: int,
        crosswalk_type: int,
        table: str,
        value_column: str,
    ) -> str | None:
        zip_code = zip_code.strip()
        fallback = STATIC_CROSSWALK.get(zip_code)
        if not self._token:
            return fallback[static_index] if fallback else None
        record = require_url(
            "https://www.huduser.gov/hudapi/public/usps",
            method="GET",
            config=self.config,
        )
        cache_ttl = (
            record.operating_policy.persistent_cache_ttl_seconds
            if record is not None
            else 0
        )
        cached = None
        if cache_ttl > 0:
            cached = await asyncio.to_thread(
                self._lookup, table, value_column, zip_code
            )
            if cached and time.time() - cached[1] < min(
                REFRESH_SECONDS,
                cache_ttl,
            ):
                return cached[0]
            if cached:
                await asyncio.to_thread(self._delete, table, zip_code)
                cached = None
        refreshed = await self._refresh(
            zip_code,
            crosswalk_type=crosswalk_type,
            table=table,
            value_column=value_column,
            cache_ttl_seconds=cache_ttl,
        )
        if refreshed:
            return refreshed
        return fallback[static_index] if fallback else None

    async def zip_to_county(self, zip_code: str) -> str | None:
        """Return the county with the highest residential ratio for a ZIP."""
        return await self._resolve(
            zip_code,
            static_index=0,
            crosswalk_type=2,
            table="xwalk_zip_county",
            value_column="county_fips",
        )

    async def zip_to_cbsa(self, zip_code: str) -> str | None:
        """Return the CBSA with the highest residential ratio for a ZIP."""
        return await self._resolve(
            zip_code,
            static_index=1,
            crosswalk_type=3,
            table="xwalk_zip_cbsa",
            value_column="cbsa",
        )
