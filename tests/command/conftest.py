"""Fixtures for the isolated daily command-center tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.models import DDItem, Listing


def listing(source_id: str) -> Listing:
    return Listing(
        source="fixture",
        source_id=source_id,
        name=f"Command fixture {source_id}",
        address="100 Main St",
        city="Los Angeles",
        state="CA",
        property_type="retail",
        listing_type="for-sale",
        price_usd=2_000_000,
        url=f"https://example.test/{source_id}",
    )


def dd_item(key: str, deadline: date) -> DDItem:
    return DDItem(
        key=key,
        label=key.replace("_", " ").title(),
        why="The diligence gate can affect value and closing certainty.",
        what_clears_it="A documented satisfactory review.",
        what_should_make_you_terminate="An unresolved material defect.",
        who_to_hire="Qualified reviewer",
        due_offset_days=1,
        deadline=deadline,
    )


@pytest.fixture
def command_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "command.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(path))
    return path


@pytest.fixture
def fixed_store(command_db: Path, monkeypatch: pytest.MonkeyPatch) -> DealStore:
    monkeypatch.setattr(
        DealStore,
        "_now",
        staticmethod(lambda: "2026-07-13T00:00:00+00:00"),
    )
    return DealStore(command_db)

