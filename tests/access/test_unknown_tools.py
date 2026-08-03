"""Coverage 7: unclassified tools are denied in cloud mode, and the
capability matrix must cover every registered tool exactly."""

import pytest
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from tests.access.helpers import call_data, tool_names


async def test_unclassified_tool_is_hidden_in_cloud(mini_mcp, identity, ctx_op):
    identity["ctx"] = ctx_op
    assert "totally_unclassified_tool" not in await tool_names(mini_mcp)


async def test_unclassified_tool_call_is_denied_in_cloud(
    mini_mcp, identity, ctx_op
):
    identity["ctx"] = ctx_op
    with pytest.raises(ToolError, match="denied|unclassified"):
        await call_data(mini_mcp, "totally_unclassified_tool")


async def test_matrix_covers_every_registered_tool_exactly():
    from cre_mcp.access.capabilities import CAPABILITIES
    from cre_mcp.server import mcp

    registered = set((await mcp.get_tools()).keys())
    classified = set(CAPABILITIES)
    missing = sorted(registered - classified)
    stale = sorted(classified - registered)
    assert not missing, f"unclassified registered tools: {missing[:10]}..."
    assert not stale, f"matrix entries for unregistered tools: {stale[:10]}..."


async def test_matrix_entries_are_well_formed_and_machine_readable():
    from cre_mcp.access.capabilities import CAPABILITIES, export_matrix
    from cre_mcp.access.profiles import Profile
    from cre_mcp.server import mcp

    tools = await mcp.get_tools()
    matrix = export_matrix()
    valid_profiles = {p.value for p in Profile}
    for name, cap in CAPABILITIES.items():
        assert cap.allowed_profiles, f"{name}: no profile may use the tool"
        assert len(cap.allowed_profiles) == len(set(cap.allowed_profiles)), name
        assert set(cap.allowed_profiles) <= valid_profiles, name
        assert "full_operator" in cap.allowed_profiles, name
        if cap.sensitive or cap.sensitive_params:
            assert cap.approval, f"{name}: sensitive without approval class"
        assert cap.module == tools[name].fn.__module__, f"{name}: stale module"
        # Declared param names must exist on the tool's actual schema, so the
        # matrix cannot silently drift from real signatures.
        schema_props = set(
            (tools[name].parameters or {}).get("properties", {})
        )
        assert set(cap.territory_params) <= schema_props, name
        assert set(cap.property_reference_params) <= schema_props, name
        assert set(cap.sensitive_params) <= schema_props, name
        assert set(cap.preserve_params) <= schema_props, name
        for request_record in cap.request_territory_records:
            root_param = request_record.path.split(".", 1)[0].removesuffix("[]")
            assert root_param in schema_props, (
                f"{name}: request territory path does not name a real parameter"
            )
        for contract in cap.result_territory_contracts:
            if contract.request_location_param is not None:
                assert contract.request_location_param in schema_props, name
        entry = matrix[name]
        for key in (
            "allowed_profiles",
            "sensitive",
            "sensitive_params",
            "territory_params",
            "property_reference_params",
            "request_territory_records",
            "result_territory_contracts",
            "preserve_params",
            "ownership_relevant",
            "quota",
            "approval",
        ):
            assert key in entry, f"{name} export missing {key}"


def test_search_result_territory_contract_has_both_closed_envelopes():
    from cre_mcp.access.capabilities import CAPABILITIES, export_matrix

    contracts = CAPABILITIES["search_properties"].result_territory_contracts
    assert {contract.envelope_model for contract in contracts} == {
        "SearchResult",
        "AggregatedSearchResult",
    }
    assert {record.path for contract in contracts for record in contract.records} == {
        "properties[]",
        "listings[]",
    }
    assert all(
        record.location_fields == ("address", "city", "state", "zip_code")
        for contract in contracts
        for record in contract.records
    )
    assert len(export_matrix()["search_properties"]["result_territory_contracts"]) == 2


@pytest.mark.parametrize(
    "declaration",
    [
        {
            "path": "",
            "model": "PropertySummary",
            "location_mode": "structured_property",
            "location_fields": ["state"],
        },
        {
            "path": "properties[]",
            "model": "",
            "location_mode": "structured_property",
            "location_fields": ["state"],
        },
        {
            "path": "properties[]",
            "model": "PropertySummary",
            "location_mode": "structured_property",
            "location_fields": [],
        },
        {
            "path": "properties[]",
            "model": "PropertySummary",
            "location_mode": "structured_property",
            "location_fields": ["state", "state"],
        },
        {
            "path": "properties[]",
            "model": "PropertySummary",
            "location_mode": "structured_property",
            "location_fields": ["state"],
            "unknown": True,
        },
    ],
)
def test_result_territory_record_schema_rejects_ambiguous_declarations(
    declaration,
):
    from cre_mcp.access.capabilities import ResultTerritoryRecord

    with pytest.raises(ValidationError):
        ResultTerritoryRecord.model_validate(declaration)


def test_tool_capability_rejects_duplicate_result_contract_models():
    from cre_mcp.access.capabilities import ToolCapability

    record = {
        "path": "properties[]",
        "model": "PropertySummary",
        "location_mode": "structured_property",
        "location_fields": ("address", "city", "state", "zip_code"),
    }
    with pytest.raises(ValidationError, match="models must be unique"):
        ToolCapability(
            tool="search_properties",
            allowed_profiles=("local_scout",),
            result_territory_contracts=(
                {
                    "envelope_model": "SearchResult",
                    "records": (record,),
                },
                {
                    "envelope_model": "SearchResult",
                    "records": (record,),
                },
            ),
        )
