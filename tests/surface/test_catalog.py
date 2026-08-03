"""Release contracts for the 45-versus-274 customer-surface reconciliation."""

from cre_mcp.access.capabilities import CAPABILITIES
from cre_mcp.access.profiles import Profile
from cre_mcp.surface.catalog import (
    CAPABILITY_INVENTORY_SHA256,
    CUSTOMER_SURFACE,
    LEGACY_TOOL_IDS,
)


async def test_internal_and_hosted_tool_counts_are_distinct() -> None:
    from cre_mcp.server import _build_hosted_customer_server, mcp

    internal = await mcp.get_tools()
    hosted = await _build_hosted_customer_server().get_tools()

    assert len(internal) == 274
    assert len(hosted) == 20
    assert set(hosted) == set(CUSTOMER_SURFACE.tools)
    assert "search_properties" in internal
    assert "search_properties" not in hosted


def test_every_internal_capability_is_grouped_or_explicitly_internal() -> None:
    grouped = set(CUSTOMER_SURFACE.capability_to_tool)
    internal = set(CUSTOMER_SURFACE.internal_capabilities)

    assert grouped.isdisjoint(internal)
    assert grouped | internal == set(CAPABILITIES)
    assert len(grouped) == 253
    assert len(internal) == 21
    assert len(CAPABILITIES) == 274


def test_every_grouped_action_is_an_exact_server_owned_capability_id() -> None:
    for tool_name, spec in CUSTOMER_SURFACE.tools.items():
        assert spec.name == tool_name
        assert spec.capability_ids
        assert len(spec.capability_ids) == len(set(spec.capability_ids))
        assert set(spec.capability_ids) <= set(CAPABILITIES)
        assert all(
            CUSTOMER_SURFACE.capability_to_tool[action] == tool_name
            for action in spec.capability_ids
        )


def test_legacy_45_are_reconciled_without_reviving_the_old_server() -> None:
    report = CUSTOMER_SURFACE.reconciliation_report()

    assert len(LEGACY_TOOL_IDS) == 45
    assert len(set(LEGACY_TOOL_IDS)) == 45
    assert set(LEGACY_TOOL_IDS) <= set(CAPABILITIES)
    assert set(report["legacy_mapping"]) == set(LEGACY_TOOL_IDS)
    assert all(
        report["legacy_mapping"][action]
        == CUSTOMER_SURFACE.capability_to_tool[action]
        for action in LEGACY_TOOL_IDS
    )


def test_profile_surface_counts_are_release_locked() -> None:
    assert CUSTOMER_SURFACE.reconciliation_report()["profile_tool_counts"] == {
        Profile.LOCAL_SCOUT.value: 8,
        Profile.NATIONAL_SCOUT.value: 10,
        Profile.FULL_OPERATOR.value: 20,
        Profile.JV_PARTNER.value: 14,
    }


def test_internal_classes_and_inventory_fingerprint_are_release_locked() -> None:
    report = CUSTOMER_SURFACE.reconciliation_report()

    assert CAPABILITY_INVENTORY_SHA256 == (
        "3ef968d84b76ad8092cf6dd4ca2629924214ac6b1ae54a6d080afd17ad837d1f"
    )
    assert report["non_mcp_internal_classes"] == (
        "admin",
        "billing",
        "database",
        "security",
        "provider_repair",
    )
    assert report["capability_mapping"]["find_control_opportunities"] == "internal"
    assert report["capability_mapping"]["find_arbitrage_opportunities"] == "internal"
    assert report["capability_mapping"]["capabilities"] == "internal"


def test_unknown_and_cross_group_actions_fail_closed() -> None:
    assert CUSTOMER_SURFACE.resolve(
        "cre_discover",
        {"action": "unknown_action", "arguments": {}},
    ) is None
    assert CUSTOMER_SURFACE.resolve(
        "cre_discover",
        {"action": "generate_loi", "arguments": {}},
    ) is None
    assert CUSTOMER_SURFACE.resolve(
        "cre_discover",
        {"action": "find_control_opportunities", "arguments": {}},
    ) is None
    assert CUSTOMER_SURFACE.resolve(
        "cre_discover",
        {"action": "search_properties", "arguments": []},
    ) is None
