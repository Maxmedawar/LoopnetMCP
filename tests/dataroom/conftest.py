"""Fixtures that isolate data-room tables in a temporary cache database."""

from pathlib import Path

import pytest


@pytest.fixture
def dataroom_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "dataroom.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(path))
    return path
