"""FastMCP registration and defensive wrapper contracts.

These tests exercise the director-facing functions rather than the lower-level
module APIs.  The wrappers must remain explicit, registration-safe, and unable
to leak raw implementation exceptions across the tool boundary.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from fastmcp.tools import Tool

from cre_mcp.disposition import tools


EXPECTED_RECORD_BUYER_PARAMETERS = [
    "name",
    "buyer_type",
    "check_size_min",
    "check_size_max",
    "geographies",
    "asset_types",
    "financing_style",
    "source",
    "notes",
    "buyer_id",
]

EXPECTED_RECORD_BID_PARAMETERS = [
    "deal_id",
    "buyer_id",
    "price",
    "deposit",
    "dd_days",
    "closing_days",
    "contingencies",
    "financing",
    "bid_id",
    "received_at",
    "status",
    "final_price",
]


def test_every_exported_tool_has_explicit_fastmcp_safe_signature():
    """FastMCP rejects either variadic parameter kind during registration."""

    forbidden = {
        inspect.Parameter.VAR_KEYWORD,
        inspect.Parameter.VAR_POSITIONAL,
    }
    assert tools.__all__
    for name in tools.__all__:
        function = getattr(tools, name)
        signature = inspect.signature(function)
        assert not [
            parameter.name
            for parameter in signature.parameters.values()
            if parameter.kind in forbidden
        ], f"{name}{signature} exposes a FastMCP-incompatible variadic parameter"

        registered = Tool.from_function(function)
        assert registered.name == name


def test_record_function_signatures_are_stable_and_explicit():
    assert list(inspect.signature(tools.record_buyer).parameters) == (
        EXPECTED_RECORD_BUYER_PARAMETERS
    )
    assert list(inspect.signature(tools.record_bid).parameters) == (
        EXPECTED_RECORD_BID_PARAMETERS
    )

    buyer_parameters = inspect.signature(tools.record_buyer).parameters
    bid_parameters = inspect.signature(tools.record_bid).parameters
    assert buyer_parameters["name"].default is inspect.Parameter.empty
    assert buyer_parameters["buyer_type"].default is inspect.Parameter.empty
    assert bid_parameters["deal_id"].default is inspect.Parameter.empty
    assert bid_parameters["buyer_id"].default is inspect.Parameter.empty
    assert bid_parameters["price"].default is inspect.Parameter.empty


def test_record_buyer_delegates_each_explicit_field(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    def fake_record_buyer(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"buyer_id": "buyer-explicit", "name": kwargs["name"]}

    monkeypatch.setattr(tools, "_record_buyer", fake_record_buyer)
    result = tools.record_buyer(
        "Explicit Capital",
        "institutional",
        1_000_000,
        10_000_000,
        ["Los Angeles"],
        ["industrial"],
        "cash",
        "relationship",
        "Known buyer",
        "buyer-explicit",
    )

    assert result == {"buyer_id": "buyer-explicit", "name": "Explicit Capital"}
    assert captured == {
        "name": "Explicit Capital",
        "buyer_type": "institutional",
        "check_size_min": 1_000_000,
        "check_size_max": 10_000_000,
        "geographies": ["Los Angeles"],
        "asset_types": ["industrial"],
        "financing_style": "cash",
        "source": "relationship",
        "notes": "Known buyer",
        "buyer_id": "buyer-explicit",
    }


def test_record_bid_delegates_each_explicit_field(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    def fake_record_bid(bid: dict[str, Any]) -> dict[str, Any]:
        captured.update(bid)
        return {"bid_id": "bid-explicit", "status": bid["status"]}

    monkeypatch.setattr(tools, "_record_bid", fake_record_bid)
    result = tools.record_bid(
        "deal-explicit",
        "buyer-explicit",
        8_000_000,
        250_000,
        30,
        25,
        ["inspection"],
        {"type": "bank", "proof": True},
        "bid-explicit",
        "2026-07-14T12:00:00+00:00",
        "retraded",
        7_700_000,
    )

    assert result == {"bid_id": "bid-explicit", "status": "retraded"}
    assert captured == {
        "deal_id": "deal-explicit",
        "buyer_id": "buyer-explicit",
        "price": 8_000_000,
        "deposit": 250_000,
        "dd_days": 30,
        "closing_days": 25,
        "contingencies": ["inspection"],
        "financing": {"type": "bank", "proof": True},
        "bid_id": "bid-explicit",
        "received_at": "2026-07-14T12:00:00+00:00",
        "status": "retraded",
        "final_price": 7_700_000,
    }


@pytest.mark.parametrize(
    ("function", "args"),
    [
        (tools.disposition_readiness, ("", "not-a-deal-type", "not-a-date")),
        (tools.record_buyer, ("", "not-a-buyer-type")),
        (tools.match_buyers, ({},)),
        (tools.record_bid, ("", "", -1)),
        (tools.normalize_bids, ("",)),
        (tools.design_sale_process, (None, None)),
        (tools.compare_exit_paths, ({},)),
    ],
    ids=lambda value: getattr(value, "__name__", None),
)
def test_every_wrapper_returns_error_envelope_for_invalid_input(function, args):
    result = function(*args)

    assert isinstance(result, dict)
    assert isinstance(result.get("error"), str)
    assert result["error"].strip()


def test_public_record_wrappers_persist_and_track_retrade(disposition_db):
    buyer = tools.record_buyer(
        "Outcome Capital",
        "private",
        1_000_000,
        12_000_000,
        ["Denver"],
        ["office"],
        "bank",
        "relationship",
        "Registration-path fixture",
        "buyer-tool-outcome",
    )
    assert "error" not in buyer

    created = tools.record_bid(
        "deal-tool-outcome",
        "buyer-tool-outcome",
        8_000_000,
        200_000,
        30,
        30,
        [],
        {"type": "bank", "proof": True},
        "bid-tool-outcome",
        "2026-07-14T12:00:00+00:00",
        "active",
    )
    assert "error" not in created
    assert created["retrade_count"] == 0

    retraded = tools.record_bid(
        "deal-tool-outcome",
        "buyer-tool-outcome",
        8_000_000,
        bid_id="bid-tool-outcome",
        status="retraded",
        final_price=7_600_000,
    )
    assert "error" not in retraded
    assert retraded["status"] == "retraded"
    assert retraded["retrade_count"] == 1
    assert retraded["retrade_delta_dollars"] == -400_000

    matched = tools.match_buyers(
        {"price": 8_000_000, "type": "office", "market": "Denver"}
    )
    assert "error" not in matched
    history = matched["matches"][0]
    assert history["bids_made"] == 1
    assert history["retrades"] == 1
