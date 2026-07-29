"""Dual route mounting and inert stdio registration."""

from __future__ import annotations

import httpx

from cre_mcp.platform.api import PLATFORM_ROUTE_SPECS, starlette_app
from cre_mcp.server import create_http_app, mcp

from .provider_helpers import (
    json_bytes,
    provider_config,
    signed_headers,
    stripe_event,
)

EXPECTED_PROVIDER_ROUTES = {
    "/v1/webhooks/stripe",
    "/v1/webhooks/skool",
    "/v1/admin/provider-events/quarantine",
    "/v1/admin/provider-events/{provider_event_id:int}/replay",
    "/v1/admin/workspaces/{workspace_id}/provider-events",
}


def test_provider_routes_are_in_single_route_registry_and_stdio_server(tmp_path):
    registry = {path for path, _, _ in PLATFORM_ROUTE_SPECS}
    server_paths = {
        getattr(route, "path", None)
        for route in mcp._additional_http_routes
    }

    assert EXPECTED_PROVIDER_ROUTES <= registry
    assert EXPECTED_PROVIDER_ROUTES <= server_paths


def test_provider_routes_mount_on_standalone_and_fastmcp_apps(tmp_path):
    config = provider_config(tmp_path)
    standalone_paths = {
        getattr(route, "path", None)
        for route in starlette_app(config).routes
    }
    fastmcp_paths = {
        getattr(route, "path", None)
        for route in create_http_app(config=config).routes
    }

    assert EXPECTED_PROVIDER_ROUTES <= standalone_paths
    assert EXPECTED_PROVIDER_ROUTES <= fastmcp_paths
    assert "/mcp" in fastmcp_paths


async def test_signed_webhook_behaves_the_same_on_both_mounts(tmp_path):
    for index, app_factory in enumerate(
        (
            lambda config: starlette_app(config),
            lambda config: create_http_app(config=config),
        )
    ):
        config = provider_config(
            tmp_path,
            cache_db_path=tmp_path / f"mount-{index}.db",
        )
        app = app_factory(config)
        body = json_bytes(
            stripe_event(f"evt_mount_{index}", customer=f"cus_mount_{index}")
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://mount.test",
        ) as client:
            response = await client.post(
                "/v1/webhooks/stripe",
                content=body,
                headers=signed_headers("stripe", body),
            )

        assert response.status_code == 202
        assert response.json()["outcome"] == "quarantined"
