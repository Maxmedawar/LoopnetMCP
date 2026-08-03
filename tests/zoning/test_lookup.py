"""Lookup orchestration and explicit honesty-path tests."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.zoning.lookup import zoning_at
from cre_mcp.zoning.tools import zoning_code_link
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_lookup_normalizes_fixture_and_does_not_invent_code_attributes():
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads(
        load_fixture("zoning/austin_zoning.json")
    )

    result = await zoning_at(30.256, -97.763, "Austin, TX", fetch=fetch)

    assert result["status"] == "OK"
    assert result["district"] == "GR-V"
    assert result["source_endpoint"].endswith("Zoning_1/MapServer/0")
    assert result["source_layer"] == "0 — Zoning"
    assert result["sources"][0]["effective_date"] is None
    assert result["sources"][0]["ordinance"] is None
    assert result["code_link"].startswith("https://library.municode.com/")
    assert result["development_standards"] == {
        "far": None,
        "height": None,
        "setbacks": None,
        "parking": None,
        "permitted_uses": None,
        "reason": (
            "These rules are in the governing zoning code, not the zoning "
            "polygon response. Read the cited code library; no standards are "
            "inferred."
        ),
    }


@pytest.mark.asyncio
async def test_phoenix_lookup_queries_and_cites_overlay_layer():
    fetch = AsyncMock()
    fetch.get_json.side_effect = [
        {
            "features": [
                {
                    "attributes": {
                        "ZONING": "DTC",
                        "ORD_NUM": "G-7000",
                        "DATE_APPRO": "2025-01-02",
                    }
                }
            ]
        },
        {
            "features": [
                {
                    "attributes": {
                        "NAME": "Downtown Code",
                        "REGULATORY": "Regulatory overlay",
                    }
                }
            ]
        },
    ]

    with patch("cre_mcp.zoning.lookup.asyncio.sleep", new_callable=AsyncMock):
        result = await zoning_at(
            33.4484,
            -112.074,
            "Phoenix, AZ",
            fetch=fetch,
        )

    assert result["district"] == "DTC"
    assert result["ordinance"] == "G-7000"
    assert result["effective_date"] == "2025-01-02"
    assert result["overlays"][0]["name"] == "Downtown Code"
    assert result["overlays"][0]["source_layer"].startswith(
        "0 — Zoning Overlays"
    )
    assert fetch.get_json.await_count == 2


@pytest.mark.asyncio
async def test_houston_returns_no_zoning_explanation_without_http():
    fetch = AsyncMock()

    result = await zoning_at(29.7604, -95.3698, "Houston, TX", fetch=fetch)

    assert result["status"] == "SUPPORTED_NO_ZONING"
    assert result["has_zoning"] is False
    assert "no municipal zoning" in result["description"].casefold()
    assert "chapter 42" in result["description"].casefold()
    assert "deed restrictions" in result["description"].casefold()
    assert result["source_layer"].startswith("No zoning layer")
    assert "CH42" in result["code_link"]
    fetch.get_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_jurisdiction_is_explicitly_unsupported_without_guessing():
    fetch = AsyncMock()

    result = await zoning_at(35.0, -100.0, "Imaginary, TX", fetch=fetch)

    assert result["status"] == "UNSUPPORTED"
    assert result["has_zoning"] is None
    assert result["district"] is None
    assert result["sources"] == []
    assert "ArcGIS Hub" in result["discovery_hint"]
    assert "later phase" in result["discovery_hint"]
    fetch.get_json.assert_not_awaited()


def test_code_link_returns_human_library_and_no_unverified_guess():
    assert zoning_code_link("GA", "Atlanta") == (
        "https://library.municode.com/ga/atlanta/codes/code_of_ordinances"
    )
    assert zoning_code_link("XX", "Imaginary") is None
