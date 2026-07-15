from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from cre_mcp.siteintel.employers import (
    CA_WARN_SOURCE_URL,
    TX_WARN_SOURCE_URL,
    employer_events,
    parse_tx_warn_rows,
)


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "siteintel"


def _tx_fixture() -> list[dict]:
    return json.loads((FIXTURE_DIR / "tx_warn_2026_sample.json").read_text())


def test_texas_parser_normalizes_captured_real_fixture() -> None:
    events = parse_tx_warn_rows(_tx_fixture(), "2026-06-13")

    assert len(events) == 2
    assert events[0] == {
        "employer": "KUEHNE + NAGEL (KN) 2026",
        "location": "Lewisville, Denton County, TX",
        "affected": 90,
        "effective_date": "2026-06-29",
        "source_url": TX_WARN_SOURCE_URL,
    }
    assert events[1]["employer"] == "JPMorgan Chase & Co."
    assert events[1]["affected"] == 244


async def test_texas_live_adapter_uses_fetch_client_contract_without_network() -> None:
    class FakeFetch:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def get_json(self, url: str) -> list[dict]:
            self.urls.append(url)
            return _tx_fixture()

    fetch = FakeFetch()
    result = await employer_events(
        "TX",
        "2026-06-13",
        fetch=fetch,  # type: ignore[arg-type]
        today=date(2026, 7, 14),
    )

    assert result["status"] == "OK"
    assert result["count"] == 2
    assert result["source_url"] == TX_WARN_SOURCE_URL
    assert result["source_retrieved_date"] == "2026-07-14"
    assert fetch.urls and "%24where=" in fetch.urls[0]


async def test_california_current_xlsx_is_honestly_live_unsupported() -> None:
    result = await employer_events(
        "California",
        "2026-01-01",
        today=date(2026, 7, 14),
    )

    assert result["status"] == "UNSUPPORTED"
    assert result["events"] == []
    assert result["source_url"] == CA_WARN_SOURCE_URL
    assert result["source_format"] == "XLSX"
    assert result["source_retrieved_date"] == "2026-07-14"
    assert "no binary response API" in result["reason"]


async def test_nullable_since_uses_explicit_calendar_year_convention() -> None:
    class FakeFetch:
        async def get_json(self, url: str) -> list[dict]:
            assert "2026-01-01" in url
            return []

    result = await employer_events(
        "TX",
        None,
        fetch=FakeFetch(),  # type: ignore[arg-type]
        today=date(2026, 7, 14),
    )

    assert result["status"] == "OK"
    assert result["since"] == "2026-01-01"
    assert "omitted since defaults" in result["since_convention"]
