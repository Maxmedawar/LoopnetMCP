"""Platform schema-creation tests."""

import sqlite3

from cre_mcp.config import CreConfig
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.platform.schema import PLATFORM_TABLES, create_schema


def _table_names(path) -> set[str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {str(row[0]) for row in rows}


def test_create_schema_creates_every_platform_table(tmp_path):
    path = tmp_path / "platform.db"
    with sqlite3.connect(path) as connection:
        create_schema(connection)

    assert PLATFORM_TABLES <= _table_names(path)


def test_create_schema_is_idempotent(tmp_path):
    path = tmp_path / "platform.db"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        create_schema(connection)

    assert PLATFORM_TABLES <= _table_names(path)


async def test_repository_bootstraps_schema_on_first_use(tmp_path):
    path = tmp_path / "platform.db"
    repository = PlatformRepository(path)

    assert await repository.list_users() == []
    assert PLATFORM_TABLES <= _table_names(path)


def test_repository_accepts_config_positionally(tmp_path):
    config = CreConfig(cache_db_path=tmp_path / "configured.db")
    assert PlatformRepository(config).db_path == config.cache_db_path
