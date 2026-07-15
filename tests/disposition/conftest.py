"""Isolated SQLite configuration for disposition-engine tests."""

from pathlib import Path

import pytest


@pytest.fixture
def disposition_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "disposition.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(path))
    return path
