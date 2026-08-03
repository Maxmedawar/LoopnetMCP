"""Round-seven regressions for JV-visible store-backed property egress.

Every case crosses a real FastMCP ``Client`` and the production
``install_access`` middleware.  The tool callables are the production wrappers;
the one ``deal_timeline`` case additionally uses a real ``DealStore`` and its
persisted event JSON so the protocol regression cannot be reduced to a fake
return-value unit test.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from cre_mcp.access.engine import RESULT_TERRITORY_DENIAL
from cre_mcp.access.middleware import install_access
from cre_mcp.command import tools as command_tools
from cre_mcp.deals.store import DealStore
from cre_mcp.disposition import tools as disposition_tools
from cre_mcp.disposition.buyers import record_buyer as record_buyer_profile
from cre_mcp.finops import tools as finops_tools
from cre_mcp.finops.lenders import record_lender_profile as record_lender_appetite
from cre_mcp.ledger.models import ClaimOutcomeRecord
from cre_mcp.ledger.store import LedgerStore
from cre_mcp.models.listings import Listing
from cre_mcp.negotiation.commitments import CommitmentStore
from cre_mcp.relations import tools as relations_tools
from cre_mcp.tools import memory_tools


_MIAMI_PROPERTY = {
    "address": "90 Ocean Drive, Miami, FL 33101",
    "city": "Miami",
    "state": "FL",
    "zip_code": "33101",
}

_DALLAS_PROPERTY = {
    "address": "100 Main Street, Dallas, TX 75201",
    "city": "Dallas",
    "state": "TX",
    "zip_code": "75201",
}

_ROUND_SEVEN_TOOLS = (
    "overnight_changes",
    "stale_listing_signals",
    "match_buyers",
    "meeting_briefing",
    "deal_timeline",
    "counterparty_dossier",
    "match_lenders",
)


def _match_lenders_production_adapter(
    deal: dict[str, Any],
    *,
    as_of: str | None,
    stale_after_days: int,
) -> dict[str, Any]:
    """Expose the production wrapper without its server-owned storage knobs."""

    return finops_tools.match_lenders(
        deal,
        as_of=as_of,
        stale_after_days=stale_after_days,
    )


async def _meeting_briefing_production_adapter(
    counterparty: str,
    *,
    as_of: str,
    deal_id: str | None = None,
) -> dict[str, Any]:
    """Expose the production wrapper without server-owned storage parameters."""

    return await relations_tools.meeting_briefing(
        counterparty,
        deal_id,
        as_of=as_of,
    )


async def _counterparty_dossier_production_adapter(
    name: str,
    *,
    as_of: str,
) -> dict[str, Any]:
    """Expose the production wrapper without server-owned storage parameters."""

    return await relations_tools.counterparty_dossier(name, as_of=as_of)


async def _record_relation_deal(
    db_path: Path,
    *,
    source_id: str,
    property_record: dict[str, Any],
    counterparty: str = "Casey Broker",
    include_property_evidence: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Persist one relationship event through the owned DealStore."""

    store = DealStore(db_path)
    deal_id = await store.save_deal(
        Listing(
            source="fixture",
            source_id=source_id,
            name=f"Relationship fixture {source_id}",
            address=property_record.get("address"),
            city=property_record.get("city"),
            state=property_record.get("state"),
            zip_code=property_record.get("zip_code"),
            url=f"https://example.test/{source_id}",
        )
    )
    assert deal_id == f"fixture:{source_id}"
    detail: dict[str, Any] = {
        "counterparty": counterparty,
        "private_note": "must never leave the owned store",
        "negotiation_state": {
            "internal": "sensitive",
            "private_property": _MIAMI_PROPERTY,
        },
    }
    if include_property_evidence:
        detail["property"] = property_record
    event_id = await store.log_deal_event(deal_id, "broker_update", detail)
    assert event_id is not None
    return deal_id, detail


async def _corrupt_stored_deal_property(
    db_path: Path,
    deal_id: str,
    malformation: str,
) -> None:
    store = DealStore(db_path)
    deal = await store.get_deal(deal_id)
    assert deal is not None
    listing = dict(deal["listing"])
    if malformation == "missing-address":
        listing.pop("address")
    elif malformation == "missing-city":
        listing.pop("city")
    elif malformation == "missing-state":
        listing.pop("state")
    elif malformation == "null-address":
        listing["address"] = None
    elif malformation == "null-city":
        listing["city"] = None
    elif malformation == "null-state":
        listing["state"] = None
    elif malformation == "empty-crexi-address-city":
        listing["address"] = ""
        listing["city"] = ""
    elif malformation == "ambiguous-address":
        listing["address"] = (
            "100 Main Street, Dallas, TX 75201 and "
            "90 Ocean Drive, Miami, FL 33101"
        )
    else:  # pragma: no cover - the parameter matrix is release locked below
        raise AssertionError(f"unknown malformation fixture: {malformation}")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE deals SET listing_json = ? WHERE deal_id = ?",
            (json.dumps(listing), deal_id),
        )


def _record_snapshot_pair(
    db_path: Path,
    *,
    listing_key: str,
    property_record: dict[str, Any],
    first_captured_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Persist a deterministic price-change pair through the real SnapshotStore."""

    first_capture = first_captured_at or (datetime.now(UTC) - timedelta(hours=2))
    store = command_tools.SnapshotStore(db_path)
    common = {
        "listing_key": listing_key,
        "source": "fixture",
        "source_id": listing_key.removeprefix("fixture:"),
        "name": f"Snapshot {listing_key}",
        **property_record,
        "url": f"https://example.test/{listing_key.removeprefix('fixture:')}",
    }
    first = store.record_snapshot(
        {
            **common,
            "price": 2_000_000,
            "dom": 100,
            "captured_at": first_capture.isoformat(),
        }
    )
    second = store.record_snapshot(
        {
            **common,
            "price": 1_900_000,
            "dom": 101,
            "captured_at": (first_capture + timedelta(hours=1)).isoformat(),
        }
    )
    return first, second


async def test_match_lenders_real_geography_list_request_remains_available(
    registry,
    audit,
    identity,
    ctx_jv,
) -> None:
    """The real public list-valued geography shape must be validated, not removed."""

    identity["ctx"] = ctx_jv

    def match_lenders(
        deal: dict[str, Any],
        *,
        as_of: str | None = None,
        stale_after_days: int = 180,
    ) -> dict[str, Any]:
        del deal
        return {
            "as_of": as_of or "2026-08-03",
            "stale_after_days": stale_after_days,
            "deal": {
                "loan_amount_cents": 75_000_000,
                "locations": [
                    {"location": "Dallas, TX"},
                    {"location": "Austin, TX"},
                ],
                "asset_types": ["retail"],
                "leverage": 0.65,
            },
            "lender_count": 0,
            "matches": [],
            "fit_rubric": {
                "size": 40.0,
                "geography": 25.0,
                "asset_type": 25.0,
                "leverage": 10.0,
                "unknown_values_receive_neutral_partial_credit": True,
            },
        }

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="match_lenders",
        tool=match_lenders,
        arguments={
            "deal": {
                "loan_amount_cents": 75_000_000,
                "geographies": ["Dallas, TX", "Austin, TX"],
                "asset_type": "retail",
                "leverage": 0.65,
            },
            "as_of": "2026-08-03",
            "stale_after_days": 180,
        },
    )

    assert result.structured_content["deal"]["locations"] == [
        {"location": "Dallas, TX"},
        {"location": "Austin, TX"},
    ]


def test_round_seven_store_workflow_matrix_is_release_locked() -> None:
    """Keep all seven rejected capability-name reproductions permanent."""

    assert _ROUND_SEVEN_TOOLS == (
        "overnight_changes",
        "stale_listing_signals",
        "match_buyers",
        "meeting_briefing",
        "deal_timeline",
        "counterparty_dossier",
        "match_lenders",
    )
    assert len(_ROUND_SEVEN_TOOLS) == 7


async def _call_production_tool(
    registry,
    audit,
    identity,
    *,
    tool_name: str,
    tool: Callable[..., Any],
    arguments: dict[str, Any],
):
    app = FastMCP(name=f"round-seven-{tool_name}")
    app.tool(name=tool_name)(tool)
    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            return await client.call_tool(tool_name, arguments)
    finally:
        uninstall()


async def _assert_protocol_denial(
    registry,
    audit,
    identity,
    *,
    tool_name: str,
    tool: Callable[..., Any],
    arguments: dict[str, Any],
) -> None:
    """Require a denial and print the historical release if it recurs."""

    workspace = identity["ctx"].workspace_id
    before_events = [
        event for event in audit.events(workspace) if event.tool == tool_name
    ]
    try:
        released = await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            tool=tool,
            arguments=arguments,
        )
    except ToolError as exc:
        events = [
            event for event in audit.events(workspace) if event.tool == tool_name
        ]
        assert str(exc) == RESULT_TERRITORY_DENIAL
        assert len(events) == len(before_events) + 1
        assert events[-1].tool == tool_name
        assert events[-1].decision == "denied"
        assert events[-1].reason == RESULT_TERRITORY_DENIAL
        return

    events = [event for event in audit.events(workspace) if event.tool == tool_name]
    payload = released.structured_content
    rendered = json.dumps(payload, sort_keys=True)
    assert "Miami" in rendered
    assert "FL" in rendered
    assert len(events) == len(before_events) + 1
    assert events[-1].tool == tool_name
    assert events[-1].decision == "allowed"
    pytest.fail(
        f"{tool_name} released an out-of-territory Miami/FL carrier and audited "
        f"it allowed: payload={rendered}; audit={events[-1].model_dump()}"
    )


async def test_overnight_changes_real_snapshot_store_tx_projection_is_available(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """A real in-scope persisted price change survives the restricted projection."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    first, second = _record_snapshot_pair(
        workspace_path,
        listing_key="fixture:dallas-overnight",
        property_record=_DALLAS_PROPERTY,
    )

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="overnight_changes",
        tool=command_tools.overnight_changes,
        arguments={"since_hours": 24},
    )

    payload = result.structured_content
    assert len(payload["changes"]) == 1
    assert payload["changes"][0]["property"] == _DALLAS_PROPERTY
    assert payload["changes"][0]["from_snapshot_id"] == first["snapshot_id"]
    assert payload["changes"][0]["to_snapshot_id"] == second["snapshot_id"]
    assert payload["summary_counts"]["listing_changes"] == 1
    assert payload["summary_counts"]["price_changes"] == 1
    assert "note" not in payload
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "overnight_changes"
    ][-1]
    assert event.decision == "allowed"


async def test_overnight_changes_real_snapshot_store_miami_fails_closed(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Preserve the original store-backed Miami release as a protocol denial."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    _record_snapshot_pair(
        workspace_path,
        listing_key="fixture:miami-overnight",
        property_record=_MIAMI_PROPERTY,
    )

    await _assert_protocol_denial(
        registry,
        audit,
        identity,
        tool_name="overnight_changes",
        tool=command_tools.overnight_changes,
        arguments={"since_hours": 24},
    )


async def test_overnight_changes_mixed_store_rows_deny_the_whole_call(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """One TX row cannot make a sibling FL row releasable or filterable."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    _record_snapshot_pair(
        workspace_path,
        listing_key="fixture:dallas-mixed",
        property_record=_DALLAS_PROPERTY,
    )
    _record_snapshot_pair(
        workspace_path,
        listing_key="fixture:miami-mixed",
        property_record=_MIAMI_PROPERTY,
    )

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="overnight_changes",
            tool=command_tools.overnight_changes,
            arguments={"since_hours": 24},
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "overnight_changes"
    ][-1]
    assert event.decision == "denied"
    assert event.reason == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize(
    ("malformation", "property_record"),
    (
        ("missing-address", {"city": "Dallas", "state": "TX", "zip_code": "75201"}),
        (
            "null-city",
            {
                "address": "100 Main Street, Dallas, TX 75201",
                "city": None,
                "state": "TX",
                "zip_code": "75201",
            },
        ),
        (
            "empty-address-city",
            {"address": "", "city": "", "state": "TX", "zip_code": "75201"},
        ),
        (
            "ambiguous-address",
            {
                "address": (
                    "100 Main Street, Dallas, TX 75201 and "
                    "90 Ocean Drive, Miami, FL 33101"
                ),
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75201",
            },
        ),
    ),
)
async def test_overnight_changes_real_store_malformed_locations_fail_closed(
    malformation,
    property_record,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    _record_snapshot_pair(
        workspace_path,
        listing_key=f"fixture:overnight-{malformation}",
        property_record=property_record,
    )

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="overnight_changes",
            tool=command_tools.overnight_changes,
            arguments={"since_hours": 24},
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


async def test_overnight_changes_unknown_snapshot_anchor_is_result_denied(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Every returned snapshot ID and listing key must bind to the owned store."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    first, second = _record_snapshot_pair(
        workspace_path,
        listing_key="fixture:dallas-known",
        property_record=_DALLAS_PROPERTY,
    )
    monkeypatch.setattr(
        command_tools,
        "overnight_brief",
        lambda **_kwargs: {
            "as_of": datetime.now(UTC).isoformat(),
            "since": (datetime.now(UTC) - timedelta(hours=24)).isoformat(),
            "changes": [
                {
                    "listing_key": "fixture:dallas-unknown",
                    "event_type": "price_change",
                    "previous_captured_at": first["captured_at"],
                    "captured_at": second["captured_at"],
                    "from_snapshot_id": first["snapshot_id"],
                    "to_snapshot_id": second["snapshot_id"],
                    "direction": "decrease",
                    "pct_change": -5.0,
                }
            ],
            "approaching_deadlines": [],
            "needs_attention": [],
            "summary_counts": {"listing_changes": 1},
        },
    )

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="overnight_changes",
            tool=command_tools.overnight_changes,
            arguments={"since_hours": 24},
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


async def test_overnight_changes_full_operator_payload_is_unchanged(
    registry,
    audit,
    identity,
    ctx_op,
    monkeypatch,
) -> None:
    identity["ctx"] = ctx_op
    original = {
        "as_of": "2026-08-03T12:00:00+00:00",
        "since": "2026-08-02T12:00:00+00:00",
        "changes": [],
        "approaching_deadlines": [],
        "needs_attention": [],
        "summary_counts": {"listing_changes": 0},
        "private_marker": {"property": _MIAMI_PROPERTY},
    }
    monkeypatch.setattr(command_tools, "overnight_brief", lambda **_kwargs: original)

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="overnight_changes",
        tool=command_tools.overnight_changes,
        arguments={"since_hours": 24},
    )
    assert result.structured_content == original


async def test_stale_listing_signals_real_snapshot_store_tx_is_available(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    _record_snapshot_pair(
        workspace_path,
        listing_key="fixture:dallas-stale",
        property_record=_DALLAS_PROPERTY,
        first_captured_at=datetime.now(UTC) - timedelta(days=30),
    )

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="stale_listing_signals",
        tool=command_tools.stale_listing_signals,
        arguments={"listing_key": "fixture:dallas-stale"},
    )

    payload = result.structured_content
    assert payload["listing_key"] == "fixture:dallas-stale"
    assert payload["property"] == _DALLAS_PROPERTY
    assert payload["evidence"]["snapshot_count"] == 2
    assert "note" not in payload
    assert "label" not in payload["convention"]
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "stale_listing_signals"
    ][-1]
    assert event.decision == "allowed"


async def test_stale_listing_signals_real_snapshot_store_miami_fails_closed(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    _record_snapshot_pair(
        workspace_path,
        listing_key="fixture:miami-stale",
        property_record=_MIAMI_PROPERTY,
    )

    await _assert_protocol_denial(
        registry,
        audit,
        identity,
        tool_name="stale_listing_signals",
        tool=command_tools.stale_listing_signals,
        arguments={"listing_key": "fixture:miami-stale"},
    )


@pytest.mark.parametrize(
    ("malformation", "property_record"),
    (
        ("missing-city", {"address": "100 Main Street", "state": "TX"}),
        (
            "null-address",
            {"address": None, "city": "Dallas", "state": "TX", "zip_code": "75201"},
        ),
        (
            "empty-address-city",
            {"address": "", "city": "", "state": "TX", "zip_code": "75201"},
        ),
        (
            "ambiguous-address",
            {
                "address": (
                    "100 Main Street, Dallas, TX 75201 and "
                    "90 Ocean Drive, Miami, FL 33101"
                ),
                "city": "Dallas",
                "state": "TX",
                "zip_code": "75201",
            },
        ),
    ),
)
async def test_stale_listing_signals_real_store_malformed_locations_fail_closed(
    malformation,
    property_record,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    listing_key = f"fixture:stale-{malformation}"
    _record_snapshot_pair(
        workspace_path,
        listing_key=listing_key,
        property_record=property_record,
    )

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="stale_listing_signals",
            tool=command_tools.stale_listing_signals,
            arguments={"listing_key": listing_key},
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


async def test_stale_listing_signals_unknown_listing_key_is_result_denied(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    identity["ctx"] = ctx_jv
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(tmp_path / "cache.db"))

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="stale_listing_signals",
            tool=command_tools.stale_listing_signals,
            arguments={"listing_key": "fixture:unknown-stale"},
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


async def test_stale_listing_signals_result_key_mismatch_is_denied(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """The returned key must bind exactly to the requested store subject."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    _record_snapshot_pair(
        workspace_path,
        listing_key="fixture:dallas-stale-known",
        property_record=_DALLAS_PROPERTY,
    )
    original_infer = command_tools.infer_stale_listing_signals

    def mismatched_infer(snapshots):
        result = original_infer(snapshots)
        result["listing_key"] = "fixture:dallas-stale-other"
        return result

    monkeypatch.setattr(command_tools, "infer_stale_listing_signals", mismatched_infer)
    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="stale_listing_signals",
            tool=command_tools.stale_listing_signals,
            arguments={"listing_key": "fixture:dallas-stale-known"},
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


async def test_stale_listing_signals_full_operator_payload_is_unchanged(
    registry,
    audit,
    identity,
    ctx_op,
    monkeypatch,
) -> None:
    identity["ctx"] = ctx_op
    original = {
        "listing_key": "fixture:miami-full",
        "negotiability_signal": "none",
        "heuristic_score": 0,
        "evidence": {"snapshot_count": 1},
        "convention": {"label": "original"},
        "thin_data": True,
        "private_marker": {"property": _MIAMI_PROPERTY},
    }
    monkeypatch.setattr(
        command_tools.SnapshotStore,
        "list_snapshots",
        lambda _self, _listing_key: [{"listing_key": "fixture:miami-full"}],
    )
    monkeypatch.setattr(
        command_tools,
        "infer_stale_listing_signals",
        lambda _snapshots: original,
    )

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="stale_listing_signals",
        tool=command_tools.stale_listing_signals,
        arguments={"listing_key": "fixture:miami-full"},
    )
    assert result.structured_content == original


async def test_match_buyers_real_public_tx_projection_remains_available(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Exercise the production wrapper, public deal shape, and owned buyer store."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    record_buyer_profile(
        {
            "buyer_id": "buyer-dallas-1",
            "name": "Dallas Test Capital",
            "type": "institutional",
            "check_size_min": 500_000,
            "check_size_max": 5_000_000,
            "geographies": ["Dallas, TX"],
            "asset_types": ["retail"],
            "financing_style": "all_cash",
            "source": "fixture",
            "notes": "must remain private",
        },
        db_path=workspace_path,
    )

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="match_buyers",
        tool=disposition_tools.match_buyers,
        arguments={
            "deal": {
                "price": 1_000_000,
                "type": "retail",
                "market": "Dallas, TX",
            }
        },
    )

    payload = result.structured_content
    assert payload["deal"]["market"] == "Dallas, TX"
    assert payload["buyer_count"] == 1
    assert payload["matches"][0]["buyer_id"] == "buyer-dallas-1"
    assert payload["matches"][0]["fit_rank"] == 1
    assert "geographies" not in payload["matches"][0]
    assert "notes" not in payload["matches"][0]
    assert "ranked_buyers" not in payload
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "match_buyers"
    ][-1]
    assert event.decision == "allowed"


@pytest.mark.parametrize(
    "deal",
    (
        {"price": 1_000_000, "type": "retail"},
        {"price": 1_000_000, "type": "retail", "market": None},
        {
            "price": 1_000_000,
            "type": "retail",
            "market": "Dallas, TX and Miami, FL",
        },
        {"price": 1_000_000, "type": "retail", "market": "Miami, FL"},
    ),
)
async def test_match_buyers_required_request_market_fails_closed(
    deal,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
) -> None:
    """Missing, null, ambiguous, and out-of-scope public requests never execute."""

    identity["ctx"] = ctx_jv
    monkeypatch.setattr(
        disposition_tools,
        "_match_buyers",
        lambda _deal: pytest.fail("request denial must happen before tool execution"),
    )
    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="match_buyers",
            tool=disposition_tools.match_buyers,
            arguments={"deal": deal},
        )
    expected = (
        "access denied: a property request is outside or unresolvable "
        "for this workspace's territory"
    )
    assert str(caught.value) == expected
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "match_buyers"
    ][-1]
    assert event.decision == "denied"
    assert event.reason == expected


@pytest.mark.parametrize("malformation", ("missing", "null", "ambiguous"))
async def test_match_buyers_malformed_returned_market_is_result_denied(
    malformation,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
) -> None:
    identity["ctx"] = ctx_jv
    returned_deal: dict[str, Any] = {
        "price": 1_000_000,
        "type": "retail",
        "market": "Dallas, TX",
    }
    if malformation == "missing":
        returned_deal.pop("market")
    elif malformation == "null":
        returned_deal["market"] = None
    else:
        returned_deal["market"] = "Dallas, TX and Miami, FL"
    monkeypatch.setattr(
        disposition_tools,
        "_match_buyers",
        lambda _deal: {
            "deal": returned_deal,
            "buyer_count": 0,
            "matches": [],
            "ranked_buyers": [],
            "fit_rubric": {
                "check_size": 50.0,
                "unknown_check_size_neutral_credit": 20.0,
                "asset_type": 25.0,
                "geography": 25.0,
                "unrecorded_preference_neutral_credit": 10.0,
                "behavioral_history_weight": 0.0,
            },
        },
    )
    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="match_buyers",
            tool=disposition_tools.match_buyers,
            arguments={
                "deal": {
                    "price": 1_000_000,
                    "type": "retail",
                    "market": "Dallas, TX",
                }
            },
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "match_buyers"
    ][-1]
    assert event.decision == "denied"
    assert event.reason == RESULT_TERRITORY_DENIAL


async def test_match_lenders_real_public_tx_projection_remains_available(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Exercise the production wrapper, public list shape, and owned lender store."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    recorded = record_lender_appetite(
        {
            "name": "Dallas Test Bank",
            "type": "bank",
            "geographies": ["Dallas, TX"],
            "asset_types": ["retail"],
            "size_min": 50_000_000,
            "size_max": 100_000_000,
            "leverage_max": 0.7,
            "rate_context": "private lender call notes",
            "last_confirmed": "2026-07-31",
            "source": "private fixture",
        },
        db_path=workspace_path,
    )
    assert recorded["record_status"] == "created"

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="match_lenders",
        tool=_match_lenders_production_adapter,
        arguments={
            "deal": {
                "loan_amount_cents": 75_000_000,
                "geographies": ["Dallas, TX", "Austin, TX"],
                "asset_type": "retail",
                "leverage": 0.65,
            },
            "as_of": "2026-08-03",
            "stale_after_days": 180,
        },
    )

    payload = result.structured_content
    assert payload["deal"]["locations"] == [
        {"location": "Dallas, TX"},
        {"location": "Austin, TX"},
    ]
    assert payload["lender_count"] == 1
    assert payload["matches"][0]["name"] == "Dallas Test Bank"
    assert payload["matches"][0]["fit_rank"] == 1
    assert "geographies" not in payload["matches"][0]
    assert "rate_context" not in payload["matches"][0]
    assert "source" not in payload["matches"][0]
    assert "reasons" not in payload["matches"][0]
    assert "ranked_lenders" not in payload
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "match_lenders"
    ][-1]
    assert event.decision == "allowed"


@pytest.mark.parametrize(
    "deal",
    (
        {"loan_amount_cents": 75_000_000, "asset_type": "retail"},
        {
            "loan_amount_cents": 75_000_000,
            "asset_type": "retail",
            "geography": None,
        },
        {
            "loan_amount_cents": 75_000_000,
            "asset_type": "retail",
            "geographies": [],
        },
        {
            "loan_amount_cents": 75_000_000,
            "asset_type": "retail",
            "geography": "Dallas, TX and Miami, FL",
        },
        {
            "loan_amount_cents": 75_000_000,
            "asset_type": "retail",
            "geographies": ["Dallas, TX", "Miami, FL"],
        },
        {
            "loan_amount_cents": 75_000_000,
            "asset_type": "retail",
            "geography": "Dallas, TX",
            "state": "TX",
        },
        {
            "loan_amount_cents": 75_000_000,
            "asset_type": "retail",
            "geography": "somewhere nearby",
        },
    ),
)
async def test_match_lenders_required_request_geography_fails_closed(
    deal,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
) -> None:
    """Every required geography shape is validated before lender matching."""

    identity["ctx"] = ctx_jv
    monkeypatch.setattr(
        finops_tools,
        "_match_lenders",
        lambda *_args, **_kwargs: pytest.fail(
            "request denial must happen before tool execution"
        ),
    )
    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="match_lenders",
            tool=_match_lenders_production_adapter,
            arguments={
                "deal": deal,
                "as_of": "2026-08-03",
                "stale_after_days": 180,
            },
        )
    expected = (
        "access denied: a property request is outside or unresolvable "
        "for this workspace's territory"
    )
    assert str(caught.value) == expected
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "match_lenders"
    ][-1]
    assert event.decision == "denied"
    assert event.reason == expected


@pytest.mark.parametrize(
    "returned_geographies",
    (
        pytest.param("missing", id="missing"),
        pytest.param(None, id="null"),
        pytest.param([], id="empty"),
        pytest.param(["Dallas, TX and Miami, FL"], id="ambiguous"),
        pytest.param(["Dallas, TX", "Miami, FL"], id="mixed-territory"),
    ),
)
async def test_match_lenders_malformed_returned_geographies_are_result_denied(
    returned_geographies,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
) -> None:
    identity["ctx"] = ctx_jv
    returned_deal: dict[str, Any] = {
        "loan_amount_cents": 75_000_000,
        "asset_types": ["retail"],
        "leverage": 0.65,
    }
    if returned_geographies != "missing":
        returned_deal["geographies"] = returned_geographies
    monkeypatch.setattr(
        finops_tools,
        "_match_lenders",
        lambda *_args, **_kwargs: {
            "as_of": "2026-08-03",
            "stale_after_days": 180,
            "deal": returned_deal,
            "lender_count": 0,
            "matches": [],
            "ranked_lenders": [],
            "fit_rubric": {
                "size": 40.0,
                "geography": 25.0,
                "asset_type": 25.0,
                "leverage": 10.0,
                "unknown_values_receive_neutral_partial_credit": True,
            },
        },
    )

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="match_lenders",
            tool=_match_lenders_production_adapter,
            arguments={
                "deal": {
                    "loan_amount_cents": 75_000_000,
                    "geography": "Dallas, TX",
                    "asset_type": "retail",
                    "leverage": 0.65,
                },
                "as_of": "2026-08-03",
                "stale_after_days": 180,
            },
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "match_lenders"
    ][-1]
    assert event.decision == "denied"
    assert event.reason == RESULT_TERRITORY_DENIAL


async def test_match_lenders_mixed_result_rows_deny_the_whole_protocol_call(
    registry,
    audit,
    identity,
    ctx_jv,
) -> None:
    """The result engine must reject a mixed TX/FL list, never filter it."""

    identity["ctx"] = ctx_jv

    def match_lenders(
        deal: dict[str, Any],
        *,
        as_of: str | None = None,
        stale_after_days: int = 180,
    ) -> dict[str, Any]:
        del deal
        return {
            "as_of": as_of or "2026-08-03",
            "stale_after_days": stale_after_days,
            "deal": {
                "loan_amount_cents": 75_000_000,
                "locations": [
                    {"location": "Dallas, TX"},
                    {"location": "Miami, FL"},
                ],
                "asset_types": ["retail"],
                "leverage": 0.65,
            },
            "lender_count": 0,
            "matches": [],
            "fit_rubric": {
                "size": 40.0,
                "geography": 25.0,
                "asset_type": 25.0,
                "leverage": 10.0,
                "unknown_values_receive_neutral_partial_credit": True,
            },
        }

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="match_lenders",
            tool=match_lenders,
            arguments={
                "deal": {
                    "loan_amount_cents": 75_000_000,
                    "geographies": ["Dallas, TX"],
                    "asset_type": "retail",
                    "leverage": 0.65,
                },
                "as_of": "2026-08-03",
                "stale_after_days": 180,
            },
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "match_lenders"
    ][-1]
    assert event.decision == "denied"
    assert event.reason == RESULT_TERRITORY_DENIAL


async def test_match_lenders_full_operator_payload_is_unchanged(
    registry,
    audit,
    identity,
    ctx_op,
    monkeypatch,
) -> None:
    """Restricted projection must never alter the full-operator contract."""

    identity["ctx"] = ctx_op
    original = {
        "as_of": "2026-08-03",
        "stale_after_days": 180,
        "deal": {"geographies": ["Miami, FL"]},
        "lender_count": 0,
        "matches": [],
        "ranked_lenders": [],
        "private_marker": {"property": _MIAMI_PROPERTY},
    }
    monkeypatch.setattr(
        finops_tools,
        "_match_lenders",
        lambda *_args, **_kwargs: original,
    )

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="match_lenders",
        tool=_match_lenders_production_adapter,
        arguments={
            "deal": {"geography": "Miami, FL"},
            "as_of": "2026-08-03",
            "stale_after_days": 180,
        },
    )
    assert result.structured_content == original


async def test_meeting_briefing_real_owned_store_tx_projection_is_available(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Release only safe deal, event, and commitment metadata from owned rows."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    deal_id, _detail = await _record_relation_deal(
        workspace_path,
        source_id="dallas-meeting",
        property_record=_DALLAS_PROPERTY,
    )
    commitment = CommitmentStore(workspace_path).record_commitment_note(
        deal_id,
        "Private closing deliverable",
        "them",
        due="2026-08-01",
        source="call",
        made_at="2026-07-31T12:00:00+00:00",
    )

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="meeting_briefing",
        tool=_meeting_briefing_production_adapter,
        arguments={
            "counterparty": "Casey Broker",
            "deal_id": deal_id,
            "as_of": "2026-08-03T12:00:00+00:00",
        },
    )

    payload = result.structured_content
    assert payload["counterparty"] == "Casey Broker"
    assert payload["deal_id"] == deal_id
    assert payload["deals"] == [
        {
            "deal_id": deal_id,
            "property": _DALLAS_PROPERTY,
            "stage": "lead",
            "score": None,
            "updated_at": payload["deals"][0]["updated_at"],
        }
    ]
    assert payload["status"] == "active_open_items"
    assert payload["event_count"] == 1
    assert payload["events"][0]["deal_id"] == deal_id
    assert payload["commitment_count"] == 1
    assert payload["overdue_count"] == 1
    assert payload["commitments"] == [
        {
            "commitment_id": commitment["id"],
            "deal_id": deal_id,
            "made_by": "them",
            "status": "open",
            "due": "2026-08-01",
            "overdue": True,
        }
    ]
    rendered = json.dumps(payload, sort_keys=True)
    assert "Private closing deliverable" not in rendered
    assert "private_note" not in rendered
    assert "negotiation_state" not in rendered
    assert "Miami" not in rendered
    assert "detail" not in payload["events"][0]


async def test_counterparty_dossier_real_owned_store_tx_projection_is_available(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Bind explicit event property evidence to the same owned Dallas deal."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    deal_id, _detail = await _record_relation_deal(
        workspace_path,
        source_id="dallas-dossier",
        property_record=_DALLAS_PROPERTY,
    )

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="counterparty_dossier",
        tool=_counterparty_dossier_production_adapter,
        arguments={
            "name": "Casey Broker",
            "as_of": "2026-08-03T12:00:00+00:00",
        },
    )

    payload = result.structured_content
    assert payload["who"] == "Casey Broker"
    assert payload["deals"][0]["deal_id"] == deal_id
    assert payload["deals"][0]["property"] == _DALLAS_PROPERTY
    assert payload["evidence_properties"] == [
        {"deal_id": deal_id, "property": _DALLAS_PROPERTY}
    ]
    assert payload["event_count"] == 1
    assert payload["events"][0]["deal_id"] == deal_id
    rendered = json.dumps(payload, sort_keys=True)
    assert "private_note" not in rendered
    assert "negotiation_state" not in rendered
    assert "Miami" not in rendered
    assert "evidence_summary" not in payload
    assert "roles_seen" not in payload


@pytest.mark.parametrize("tool_name", ("meeting_briefing", "counterparty_dossier"))
async def test_relation_real_owned_store_miami_subject_fails_closed(
    tool_name,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Keep both original relation-tool Miami carriers as protocol denials."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    deal_id, _detail = await _record_relation_deal(
        workspace_path,
        source_id=f"miami-{tool_name}",
        property_record=_MIAMI_PROPERTY,
    )
    if tool_name == "meeting_briefing":
        tool = _meeting_briefing_production_adapter
        arguments = {
            "counterparty": "Casey Broker",
            "deal_id": deal_id,
            "as_of": "2026-08-03T12:00:00+00:00",
        }
    else:
        tool = _counterparty_dossier_production_adapter
        arguments = {
            "name": "Casey Broker",
            "as_of": "2026-08-03T12:00:00+00:00",
        }

    await _assert_protocol_denial(
        registry,
        audit,
        identity,
        tool_name=tool_name,
        tool=tool,
        arguments=arguments,
    )


@pytest.mark.parametrize("tool_name", ("meeting_briefing", "counterparty_dossier"))
async def test_relation_mixed_tx_and_fl_store_rows_deny_the_whole_call(
    tool_name,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """A Dallas sibling never permits filtering or releasing a Miami sibling."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    await _record_relation_deal(
        workspace_path,
        source_id=f"dallas-mixed-{tool_name}",
        property_record=_DALLAS_PROPERTY,
    )
    await _record_relation_deal(
        workspace_path,
        source_id=f"miami-mixed-{tool_name}",
        property_record=_MIAMI_PROPERTY,
    )
    if tool_name == "meeting_briefing":
        tool = _meeting_briefing_production_adapter
        arguments = {
            "counterparty": "Casey Broker",
            "as_of": "2026-08-03T12:00:00+00:00",
        }
    else:
        tool = _counterparty_dossier_production_adapter
        arguments = {
            "name": "Casey Broker",
            "as_of": "2026-08-03T12:00:00+00:00",
        }

    await _assert_protocol_denial(
        registry,
        audit,
        identity,
        tool_name=tool_name,
        tool=tool,
        arguments=arguments,
    )


@pytest.mark.parametrize("tool_name", ("meeting_briefing", "counterparty_dossier"))
@pytest.mark.parametrize(
    "malformation",
    (
        "missing-address",
        "missing-city",
        "missing-state",
        "null-address",
        "null-city",
        "null-state",
        "empty-crexi-address-city",
        "ambiguous-address",
    ),
)
async def test_relation_owned_store_incomplete_locations_fail_closed(
    tool_name,
    malformation,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Omitted, null, Crexi-empty, and ambiguous store subjects are denied."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    deal_id, _detail = await _record_relation_deal(
        workspace_path,
        source_id=f"{tool_name}-{malformation}",
        property_record=_DALLAS_PROPERTY,
    )
    await _corrupt_stored_deal_property(workspace_path, deal_id, malformation)
    if tool_name == "meeting_briefing":
        tool = _meeting_briefing_production_adapter
        arguments = {
            "counterparty": "Casey Broker",
            "deal_id": deal_id,
            "as_of": "2026-08-03T12:00:00+00:00",
        }
    else:
        tool = _counterparty_dossier_production_adapter
        arguments = {
            "name": "Casey Broker",
            "as_of": "2026-08-03T12:00:00+00:00",
        }

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            tool=tool,
            arguments=arguments,
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize(
    "property_evidence",
    (
        {"city": "Dallas", "state": "TX", "zip_code": "75201"},
        {
            "address": "100 Main Street, Dallas, TX 75201",
            "city": None,
            "state": "TX",
            "zip_code": "75201",
        },
        {"address": "", "city": "", "state": "TX", "zip_code": "75201"},
        {
            "address": (
                "100 Main Street, Dallas, TX 75201 and "
                "90 Ocean Drive, Miami, FL 33101"
            ),
            "city": "Dallas",
            "state": "TX",
            "zip_code": "75201",
        },
        _MIAMI_PROPERTY,
    ),
)
async def test_dossier_explicit_event_property_evidence_fails_closed_when_unbound(
    property_evidence,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """A known event property path must be complete and match its deal row."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    store = DealStore(workspace_path)
    deal_id = await store.save_deal(
        Listing(
            source="fixture",
            source_id="dossier-unbound-evidence",
            name="Dossier evidence fixture",
            **_DALLAS_PROPERTY,
            url="https://example.test/dossier-unbound-evidence",
        )
    )
    assert deal_id is not None
    await store.log_deal_event(
        deal_id,
        "broker_update",
        {"counterparty": "Casey Broker", "property": property_evidence},
    )

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="counterparty_dossier",
            tool=_counterparty_dossier_production_adapter,
            arguments={
                "name": "Casey Broker",
                "as_of": "2026-08-03T12:00:00+00:00",
            },
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


async def test_meeting_briefing_unknown_requested_deal_anchor_fails_closed(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    identity["ctx"] = ctx_jv
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(tmp_path / "cache.db"))
    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="meeting_briefing",
            tool=_meeting_briefing_production_adapter,
            arguments={
                "counterparty": "Casey Broker",
                "deal_id": "fixture:unknown-meeting",
                "as_of": "2026-08-03T12:00:00+00:00",
            },
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


async def test_counterparty_dossier_unknown_ledger_deal_anchor_fails_closed(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """A real ledger reference cannot manufacture a nonexistent deal subject."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    written = await LedgerStore(workspace_path).record_claims(
        [
            ClaimOutcomeRecord(
                deal_id="fixture:unknown-dossier",
                field="noi",
                subject="Unknown property",
                counterparty="Casey Broker",
                counterparty_role="broker",
                claimed_value=100,
                claimed_doc_kind="listing",
                proven_value=90,
                proven_doc_kind="t12",
                verdict="overridden",
                recorded_at="2026-08-01T12:00:00+00:00",
            )
        ]
    )
    assert written == 1

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="counterparty_dossier",
            tool=_counterparty_dossier_production_adapter,
            arguments={
                "name": "Casey Broker",
                "as_of": "2026-08-03T12:00:00+00:00",
            },
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("tool_name", ("meeting_briefing", "counterparty_dossier"))
async def test_relation_no_owned_subject_history_fails_closed(
    tool_name,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Restricted relationship output needs at least one owned property subject."""

    identity["ctx"] = ctx_jv
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(tmp_path / "cache.db"))
    if tool_name == "meeting_briefing":
        tool = _meeting_briefing_production_adapter
        arguments = {
            "counterparty": "Casey Broker",
            "as_of": "2026-08-03T12:00:00+00:00",
        }
    else:
        tool = _counterparty_dossier_production_adapter
        arguments = {
            "name": "Casey Broker",
            "as_of": "2026-08-03T12:00:00+00:00",
        }
    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            tool=tool,
            arguments=arguments,
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize(
    ("tool_name", "mutation"),
    (
        ("meeting_briefing", "name"),
        ("meeting_briefing", "deal"),
        ("meeting_briefing", "context"),
        ("counterparty_dossier", "name"),
        ("counterparty_dossier", "event"),
    ),
)
async def test_relation_result_identity_and_owned_rows_bind_exactly(
    tool_name,
    mutation,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Request names, deal IDs, summaries, and events may not be substituted."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    deal_id, _detail = await _record_relation_deal(
        workspace_path,
        source_id=f"binding-{tool_name}-{mutation}",
        property_record=_DALLAS_PROPERTY,
    )

    if tool_name == "meeting_briefing":
        original = relations_tools._meeting_briefing

        async def altered_meeting(*args, **kwargs):
            payload = await original(*args, **kwargs)
            if mutation == "name":
                payload["counterparty"] = "Different Broker"
            elif mutation == "deal":
                payload["deal_id"] = "fixture:substituted"
            else:
                payload["deal_context"][0]["stage"] = "owned"
            return payload

        monkeypatch.setattr(relations_tools, "_meeting_briefing", altered_meeting)
        tool = _meeting_briefing_production_adapter
        arguments = {
            "counterparty": "Casey Broker",
            "deal_id": deal_id,
            "as_of": "2026-08-03T12:00:00+00:00",
        }
    else:
        original = relations_tools._counterparty_dossier

        async def altered_dossier(*args, **kwargs):
            payload = await original(*args, **kwargs)
            if mutation == "name":
                payload["who"] = "Different Broker"
            else:
                payload["evidence_summary"]["deal_events"]["records"][0][
                    "event_ts"
                ] = "2026-01-01T00:00:00+00:00"
            return payload

        monkeypatch.setattr(relations_tools, "_counterparty_dossier", altered_dossier)
        tool = _counterparty_dossier_production_adapter
        arguments = {
            "name": "Casey Broker",
            "as_of": "2026-08-03T12:00:00+00:00",
        }

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name=tool_name,
            tool=tool,
            arguments=arguments,
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL


async def test_meeting_briefing_full_operator_payload_is_unchanged(
    registry,
    audit,
    identity,
    ctx_op,
    monkeypatch,
) -> None:
    identity["ctx"] = ctx_op
    original = {
        "counterparty": "Casey Broker",
        "deal_scope": ["fixture:miami-full"],
        "private_marker": {"property": _MIAMI_PROPERTY},
    }

    async def original_meeting(*_args, **_kwargs):
        return original

    monkeypatch.setattr(relations_tools, "_meeting_briefing", original_meeting)
    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="meeting_briefing",
        tool=_meeting_briefing_production_adapter,
        arguments={
            "counterparty": "Casey Broker",
            "deal_id": "fixture:miami-full",
            "as_of": "2026-08-03T12:00:00+00:00",
        },
    )
    assert result.structured_content == original


async def test_counterparty_dossier_full_operator_payload_is_unchanged(
    registry,
    audit,
    identity,
    ctx_op,
    monkeypatch,
) -> None:
    identity["ctx"] = ctx_op
    original = {
        "who": "Casey Broker",
        "linked_deal_ids": ["fixture:miami-full"],
        "private_marker": {"property": _MIAMI_PROPERTY},
    }

    async def original_dossier(*_args, **_kwargs):
        return original

    monkeypatch.setattr(relations_tools, "_counterparty_dossier", original_dossier)
    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="counterparty_dossier",
        tool=_counterparty_dossier_production_adapter,
        arguments={
            "name": "Casey Broker",
            "as_of": "2026-08-03T12:00:00+00:00",
        },
    )
    assert result.structured_content == original


async def test_deal_timeline_real_store_event_property_fails_closed(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Exercise production DealStore persistence and memory tool egress."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    store = DealStore(workspace_path)
    listing = Listing(
        source="fixture",
        source_id="miami-1",
        name="Miami escape fixture",
        address=_MIAMI_PROPERTY["address"],
        city=_MIAMI_PROPERTY["city"],
        state=_MIAMI_PROPERTY["state"],
        zip_code=_MIAMI_PROPERTY["zip_code"],
        url="https://example.test/miami-1",
    )
    deal_id = await store.save_deal(listing)
    assert deal_id == "fixture:miami-1"
    event_id = await store.log_deal_event(
        deal_id,
        "broker_update",
        {"counterparty": "Casey Broker", "property": _MIAMI_PROPERTY},
    )
    assert event_id is not None

    await _assert_protocol_denial(
        registry,
        audit,
        identity,
        tool_name="deal_timeline",
        tool=memory_tools.deal_timeline,
        arguments={"deal_id": deal_id},
    )


async def test_deal_timeline_real_store_tx_projection_remains_available(
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Keep safe timeline metadata while dropping arbitrary persisted detail JSON."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    store = DealStore(workspace_path)
    deal_id = await store.save_deal(
        Listing(
            source="fixture",
            source_id="dallas-1",
            name="Dallas in-scope fixture",
            address=_DALLAS_PROPERTY["address"],
            city=_DALLAS_PROPERTY["city"],
            state=_DALLAS_PROPERTY["state"],
            zip_code=_DALLAS_PROPERTY["zip_code"],
            url="https://example.test/dallas-1",
        )
    )
    await store.log_deal_event(
        deal_id,
        "broker_update",
        {"property": _MIAMI_PROPERTY, "note": "must not leave the store"},
    )

    result = await _call_production_tool(
        registry,
        audit,
        identity,
        tool_name="deal_timeline",
        tool=memory_tools.deal_timeline,
        arguments={"deal_id": deal_id},
    )

    payload = result.structured_content
    assert payload["deal_id"] == deal_id
    assert payload["property"] == _DALLAS_PROPERTY
    assert payload["event_count"] == 1
    assert payload["events"][0]["event_type"] == "broker_update"
    assert "detail" not in payload["events"][0]
    assert "Miami" not in json.dumps(payload, sort_keys=True)
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "deal_timeline"
    ][-1]
    assert event.decision == "allowed"


@pytest.mark.parametrize("malformation", ("missing", "null", "ambiguous"))
async def test_deal_timeline_real_store_malformed_property_fails_closed(
    malformation,
    registry,
    audit,
    identity,
    ctx_jv,
    monkeypatch,
    tmp_path,
) -> None:
    """Stored empty, null, and multi-territory subjects are protocol denials."""

    identity["ctx"] = ctx_jv
    base_path = tmp_path / "cache.db"
    monkeypatch.setenv("CRE_CACHE_DB_PATH", str(base_path))
    workspace_path = base_path.parent / "workspaces" / ctx_jv.workspace_id / base_path.name
    store = DealStore(workspace_path)
    deal_id = await store.save_deal(
        Listing(
            source="fixture",
            source_id=f"malformed-{malformation}",
            name="Malformed location fixture",
            address=_DALLAS_PROPERTY["address"],
            city=_DALLAS_PROPERTY["city"],
            state=_DALLAS_PROPERTY["state"],
            zip_code=_DALLAS_PROPERTY["zip_code"],
            url=f"https://example.test/malformed-{malformation}",
        )
    )
    stored = (await store.get_deal(deal_id))["listing"]
    if malformation == "missing":
        stored.pop("address")
    elif malformation == "null":
        stored["city"] = None
    else:
        stored["address"] = (
            "90 Ocean Drive, Miami, FL 33101 and "
            "100 Main Street, Dallas, TX 75201"
        )
    with sqlite3.connect(workspace_path) as connection:
        connection.execute(
            "UPDATE deals SET listing_json = ? WHERE deal_id = ?",
            (json.dumps(stored), deal_id),
        )

    with pytest.raises(ToolError) as caught:
        await _call_production_tool(
            registry,
            audit,
            identity,
            tool_name="deal_timeline",
            tool=memory_tools.deal_timeline,
            arguments={"deal_id": deal_id},
        )
    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    event = [
        item
        for item in audit.events(ctx_jv.workspace_id)
        if item.tool == "deal_timeline"
    ][-1]
    assert event.decision == "denied"
    assert event.reason == RESULT_TERRITORY_DENIAL
