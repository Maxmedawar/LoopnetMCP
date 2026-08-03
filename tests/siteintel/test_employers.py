from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from cre_mcp.access.context import TenantContext, local_context, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.siteintel import tools as siteintel_tools
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


def test_texas_parser_preserves_canonical_county_only_rows() -> None:
    rows = _tx_fixture()
    rows[0]["city_name"] = ""

    events = parse_tx_warn_rows(rows, "2026-06-13")

    assert len(events) == 2
    assert "Collin County, TX" in {event["location"] for event in events}


async def test_warn_tool_projects_only_restricted_profiles(monkeypatch) -> None:
    payload = {
        "status": "OK",
        "state": "TX",
        "since": "2026-01-01",
        "count": 2,
        "events": [
            {
                "employer": "Complete City",
                "location": "Lewisville, Denton County, TX",
                "affected": 10,
                "effective_date": "2026-07-01",
                "source_url": TX_WARN_SOURCE_URL,
            },
            {
                "employer": "County Only",
                "location": "Denton County, TX",
                "affected": 20,
                "effective_date": "2026-07-02",
                "source_url": TX_WARN_SOURCE_URL,
            },
        ],
    }

    async def fake_events(state, since):
        del state, since
        return payload

    monkeypatch.setattr(siteintel_tools, "_employer_events", fake_events)
    restricted = TenantContext(
        workspace_id="restricted-warn",
        profile=Profile.LOCAL_SCOUT,
        territories=("TX",),
    )
    with use_context(restricted):
        projected = await siteintel_tools.employer_warn_events("TX")
    with use_context(local_context()):
        trusted = await siteintel_tools.employer_warn_events("TX")

    assert projected["count"] == 2
    assert projected["events"][0]["location"] == "Lewisville, TX"
    assert projected["events"][0]["county"] is None
    assert projected["events"][1]["location"] == "TX"
    assert projected["events"][1]["county"] is None
    assert trusted == payload


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
