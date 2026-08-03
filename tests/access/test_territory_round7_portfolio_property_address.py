"""Protocol regressions for portfolio property-address territory anchors.

Every behavior crosses a real FastMCP ``Client`` boundary and the production
``install_access`` middleware path.  Synthetic inputs and results are built
through the same closed Pydantic contracts declared by the capability matrix.
"""

from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from cre_mcp.access.engine import RESULT_TERRITORY_DENIAL
from cre_mcp.access.middleware import install_access
from cre_mcp.access.result_models import (
    PortfolioInputRecord,
    PortfolioMethodology,
    PortfolioOwner,
    PortfolioOwnerScanResult,
    PortfolioProfile,
    PortfolioProperty,
)


_RESTRICTED_CONTEXT_FIXTURES = ("ctx_loc", "ctx_jv")

_REQUEST_PROPERTY_TERRITORY_DENIAL = (
    "access denied: a property request is outside or unresolvable for this "
    "workspace's territory"
)

_REQUEST_PROPERTY_ADDRESS_FAILURES = (
    ("TX", "portfolio-request-state-only"),
    ("Dallas, TX", "portfolio-request-city-state-only"),
    ("75201", "portfolio-request-zip-only"),
    ("100 Main Street, TX", "portfolio-request-street-state-only"),
    ("100 Main Street, 75201", "portfolio-request-street-zip-only"),
    (
        "Miami & 100 Main Street, Dallas, TX 75201",
        "portfolio-request-leading-junk",
    ),
)

_RESULT_PROPERTY_ADDRESS_FAILURES = (
    ("TX", "portfolio-result-state-only"),
    ("Dallas, TX", "portfolio-result-city-state-only"),
    ("75201", "portfolio-result-zip-only"),
    ("100 Main Street, TX", "portfolio-result-street-state-only"),
    ("100 Main Street, 75201", "portfolio-result-street-zip-only"),
    (
        "Miami & 100 Main Street, Dallas, TX 75201",
        "portfolio-result-leading-junk",
    ),
)

_REQUEST_PROPERTY_ADDRESS_CONTROLS = (
    (
        "100 Main Street, Dallas, TX 75201",
        "portfolio-request-control-full-address",
    ),
    (
        "100 NE 2nd Avenue Suite 200, Dallas, Texas 75201 USA",
        "portfolio-request-control-normalized-address",
    ),
)

_RESULT_PROPERTY_ADDRESS_CONTROLS = (
    (
        "100 Main Street, Dallas, TX 75201",
        "portfolio-result-control-full-address",
    ),
    (
        "100 NE 2nd Avenue Suite 200, Dallas, Texas 75201 USA",
        "portfolio-result-control-normalized-address",
    ),
)

_SAFE_REQUEST_ADDRESS = "100 Main Street, Dallas, TX 75201"


def _input_record(address: str) -> dict[str, Any]:
    return PortfolioInputRecord(
        owner_name="Synthetic Portfolio Owner LLC",
        business_name="Synthetic Portfolio Owner",
        use="industrial",
        sf=10_000,
        address=address,
        property_id="synthetic-property-1",
    ).model_dump(mode="json", exclude_none=True)


def _portfolio_result(
    addresses: list[str],
    *,
    include_owner_without_properties: bool = False,
) -> dict[str, Any]:
    properties = [
        PortfolioProperty(
            record_index=index,
            address=address,
            property_id=f"synthetic-property-{index + 1}",
            use="industrial",
            sf=10_000,
            size_to_median_ratio=1.0,
            noncore_outlier_flag=False,
            signal_label="HEURISTIC SCREEN",
            basis=["within the synthetic type and size profile"],
            inference_caution="Synthetic protocol fixture; no seller intent inferred.",
        )
        for index, address in enumerate(addresses)
    ]
    owner = PortfolioOwner(
        normalized_owner_name="SYNTHETIC PORTFOLIO OWNER",
        owner_name_variants=["Synthetic Portfolio Owner LLC"],
        property_count=max(1, len(addresses)),
        signal_label="HEURISTIC PORTFOLIO GROUP",
        grouping_basis="synthetic normalized owner fixture",
        profile=PortfolioProfile(
            use_counts={"industrial": max(1, len(addresses))},
            modal_use_for_outlier_test=None,
            median_sf=10_000.0,
            usable_size_count=max(1, len(addresses)),
            size_ratio_outlier_threshold=3.0,
        ),
        dispersion_note="Synthetic fixture with no coordinate claims.",
        noncore_outlier_count=0,
        properties=properties,
        seller_intent_caution="Synthetic protocol fixture; no seller intent inferred.",
    )
    result = PortfolioOwnerScanResult(
        methodology=PortfolioMethodology(
            label="HEURISTIC synthetic protocol fixture",
            minimum_properties=1,
            type_outlier_convention="synthetic protocol fixture",
            size_outlier_convention="synthetic protocol fixture",
        ),
        record_count=max(1, len(addresses)),
        owner_group_count=1,
        owners=[owner],
    )
    payload = result.model_dump(mode="json")
    if include_owner_without_properties:
        # Start from a fully typed envelope, then reproduce the one malformed
        # wildcard member that the protocol boundary must reject.
        payload["owners"][0]["properties"] = []
    return payload


async def _call_portfolio_owner_scan(
    registry,
    audit,
    identity,
    *,
    request_address: str,
    result_addresses: list[str],
    include_owner_without_properties: bool = False,
    executions: list[int] | None = None,
):
    if executions is None:
        executions = [0]
    payload = _portfolio_result(
        result_addresses,
        include_owner_without_properties=include_owner_without_properties,
    )
    app = FastMCP(name="territory-round-seven-portfolio-property-address")

    @app.tool
    async def portfolio_owner_scan(
        records: list[PortfolioInputRecord],
        min_properties: int = 1,
    ) -> dict[str, Any]:
        del records, min_properties
        executions[0] += 1
        return payload

    uninstall = install_access(
        app,
        registry=registry,
        audit_log=audit,
        identity_resolver=lambda _mctx: identity["ctx"],
    )
    try:
        async with Client(app) as client:
            result = await client.call_tool(
                "portfolio_owner_scan",
                {
                    "records": [_input_record(request_address)],
                    "min_properties": 1,
                },
            )
    finally:
        uninstall()
    return result, executions


def _assert_post_result_denial(audit, identity, caught) -> None:
    assert str(caught.value) == RESULT_TERRITORY_DENIAL
    event = audit.events(identity["ctx"].workspace_id)[-1]
    assert event.tool == "portfolio_owner_scan"
    assert event.decision == "denied"
    assert event.reason == RESULT_TERRITORY_DENIAL


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "request_address",
    [
        pytest.param(address, id=case_id)
        for address, case_id in _REQUEST_PROPERTY_ADDRESS_FAILURES
    ],
)
async def test_portfolio_request_rejects_incomplete_or_compound_property_address(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    request_address,
):
    """Every request record needs one complete, unambiguous property address."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    with pytest.raises(ToolError) as caught:
        await _call_portfolio_owner_scan(
            registry,
            audit,
            identity,
            request_address=request_address,
            result_addresses=[_SAFE_REQUEST_ADDRESS],
            executions=executions,
        )

    assert str(caught.value) == _REQUEST_PROPERTY_TERRITORY_DENIAL
    event = audit.events(identity["ctx"].workspace_id)[-1]
    assert event.tool == "portfolio_owner_scan"
    assert event.decision == "denied"
    assert event.reason == _REQUEST_PROPERTY_TERRITORY_DENIAL
    assert executions == [0]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "result_address",
    [
        pytest.param(address, id=case_id)
        for address, case_id in _RESULT_PROPERTY_ADDRESS_FAILURES
    ],
)
async def test_portfolio_result_rejects_incomplete_or_compound_property_address(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    result_address,
):
    """Every returned owner property needs one complete, unambiguous address."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    with pytest.raises(ToolError) as caught:
        await _call_portfolio_owner_scan(
            registry,
            audit,
            identity,
            request_address=_SAFE_REQUEST_ADDRESS,
            result_addresses=[result_address],
            executions=executions,
        )

    _assert_post_result_denial(audit, identity, caught)
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "request_address",
    [
        pytest.param(address, id=case_id)
        for address, case_id in _REQUEST_PROPERTY_ADDRESS_CONTROLS
    ],
)
async def test_portfolio_request_releases_complete_property_address_control(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    request_address,
):
    """Complete request addresses survive strict property-address validation."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    result, executions = await _call_portfolio_owner_scan(
        registry,
        audit,
        identity,
        request_address=request_address,
        result_addresses=[_SAFE_REQUEST_ADDRESS],
    )

    assert executions == [1]
    assert result.data["owners"][0]["properties"][0]["address"] == _SAFE_REQUEST_ADDRESS


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
@pytest.mark.parametrize(
    "result_address",
    [
        pytest.param(address, id=case_id)
        for address, case_id in _RESULT_PROPERTY_ADDRESS_CONTROLS
    ],
)
async def test_portfolio_result_releases_complete_property_address_control(
    request,
    registry,
    audit,
    identity,
    context_fixture,
    result_address,
):
    """Complete returned addresses remain releasable after fail-closed checks."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    result, executions = await _call_portfolio_owner_scan(
        registry,
        audit,
        identity,
        request_address=_SAFE_REQUEST_ADDRESS,
        result_addresses=[result_address],
    )

    assert executions == [1]
    assert result.data["owners"][0]["properties"][0]["address"] == result_address


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
async def test_portfolio_result_rejects_owner_without_any_property_location_anchor(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """An owner identity cannot escape through an empty wildcard property path."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    executions = [0]
    with pytest.raises(ToolError) as caught:
        await _call_portfolio_owner_scan(
            registry,
            audit,
            identity,
            request_address=_SAFE_REQUEST_ADDRESS,
            result_addresses=[_SAFE_REQUEST_ADDRESS],
            include_owner_without_properties=True,
            executions=executions,
        )

    _assert_post_result_denial(audit, identity, caught)
    assert executions == [1]


@pytest.mark.parametrize("context_fixture", _RESTRICTED_CONTEXT_FIXTURES)
async def test_portfolio_result_releases_owner_with_nonempty_property_location_anchor(
    request,
    registry,
    audit,
    identity,
    context_fixture,
):
    """The matched nonempty owner-property control still releases."""

    identity["ctx"] = request.getfixturevalue(context_fixture)
    result, executions = await _call_portfolio_owner_scan(
        registry,
        audit,
        identity,
        request_address=_SAFE_REQUEST_ADDRESS,
        result_addresses=[_SAFE_REQUEST_ADDRESS],
    )

    assert executions == [1]
    assert result.data["owners"][0]["properties"][0]["address"] == _SAFE_REQUEST_ADDRESS


def test_portfolio_property_address_protocol_case_count_is_release_locked() -> None:
    matrices = (
        ("request-failure", _REQUEST_PROPERTY_ADDRESS_FAILURES),
        ("result-failure", _RESULT_PROPERTY_ADDRESS_FAILURES),
        ("request-control", _REQUEST_PROPERTY_ADDRESS_CONTROLS),
        ("result-control", _RESULT_PROPERTY_ADDRESS_CONTROLS),
    )
    case_ids = [case_id for _, matrix in matrices for _, case_id in matrix]
    payload_signatures = [
        (family, address)
        for family, matrix in matrices
        for address, _ in matrix
    ]

    assert len(_REQUEST_PROPERTY_ADDRESS_FAILURES) == 6
    assert len(_RESULT_PROPERTY_ADDRESS_FAILURES) == 6
    assert len(_REQUEST_PROPERTY_ADDRESS_CONTROLS) == 2
    assert len(_RESULT_PROPERTY_ADDRESS_CONTROLS) == 2
    assert len(case_ids) == len(set(case_ids))
    assert len(payload_signatures) == len(set(payload_signatures))

    behavior_cases = len(_RESTRICTED_CONTEXT_FIXTURES) * (
        len(_REQUEST_PROPERTY_ADDRESS_FAILURES)
        + len(_RESULT_PROPERTY_ADDRESS_FAILURES)
        + len(_REQUEST_PROPERTY_ADDRESS_CONTROLS)
        + len(_RESULT_PROPERTY_ADDRESS_CONTROLS)
        + 2  # Empty-owner denial and its nonempty matched control.
    )
    assert behavior_cases == 36
