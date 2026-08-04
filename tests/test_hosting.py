"""Phase 24 opt-in hosting and container artifact tests."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.http.browser import BrowserFetcher
from cre_mcp.http.fetch import FetchClient
from cre_mcp.platform.api import starlette_app
from cre_mcp.server import create_http_app, main, mcp, resolve_transport, run_server
from tests.hosted_helpers import (
    create_testing_http_app,
    make_testing_persistence_bundle,
)

ROOT = Path(__file__).resolve().parents[1]


def _config(**values) -> CreConfig:
    return CreConfig(_env_file=None, **values)


def test_stdio_is_the_default_transport(monkeypatch):
    monkeypatch.delenv("CRE_TRANSPORT", raising=False)
    monkeypatch.delenv("LOOPNET_TRANSPORT", raising=False)

    config = _config()

    assert config.transport == "stdio"
    assert resolve_transport(config) == "stdio"


def test_http_transport_resolves_from_environment_without_binding(monkeypatch):
    monkeypatch.setenv("CRE_TRANSPORT", "http")
    monkeypatch.setenv("CRE_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("CRE_HTTP_PORT", "8765")

    config = _config()

    assert resolve_transport(config) == "http"
    assert config.http_host == "127.0.0.1"
    assert config.http_port == 8765


def test_http_app_fails_closed_before_local_state_without_postgres(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("MEDAWARCRE_DATABASE_URL", raising=False)
    config = _config(cache_db_path=tmp_path / "must-not-exist.db")

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_http_app(config=config)

    assert not config.cache_db_path.exists()
    assert not (tmp_path / "access" / "registry.json").exists()
    assert not (tmp_path / "access" / "audit.jsonl").exists()


def test_standalone_http_fails_closed_before_local_state_without_postgres(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("MEDAWARCRE_DATABASE_URL", raising=False)
    config = _config(cache_db_path=tmp_path / "standalone-must-not-exist.db")

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        starlette_app(config=config)

    assert not config.cache_db_path.exists()


def test_internal_global_server_rejects_direct_http_app_construction():
    with pytest.raises(RuntimeError, match="stdio-only"):
        mcp.http_app()


def test_internal_global_server_rejects_direct_http_run():
    with pytest.raises(RuntimeError, match="stdio-only"):
        mcp.run(transport="http")


def test_internal_global_server_preserves_default_stdio_run():
    from fastmcp import FastMCP

    with patch.object(FastMCP, "run") as run:
        mcp.run()

    run.assert_called_once_with(transport=None, show_banner=True)


async def test_internal_global_server_rejects_async_http_run_paths():
    with pytest.raises(RuntimeError, match="stdio-only"):
        await mcp.run_async(transport="http")
    with pytest.raises(RuntimeError, match="stdio-only"):
        await mcp.run_http_async()


def test_http_app_constructs_at_mcp_path_without_binding(tmp_path):
    app = create_testing_http_app(
        config=_config(cache_db_path=tmp_path / "platform.db")
    )

    assert callable(app)
    assert any(getattr(route, "path", None) == "/mcp" for route in app.routes)


def test_http_app_serves_platform_routes_alongside_mcp(tmp_path):
    app = create_testing_http_app(
        config=_config(cache_db_path=tmp_path / "platform.db")
    )

    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/mcp" in paths
    assert "/v1/me" in paths
    assert "/v1/deals" not in paths
    assert "/v1/deals/{deal_id:int}" not in paths


async def test_http_app_closes_postgres_bundle_once_with_asgi_lifespan(tmp_path):
    config = _config(cache_db_path=tmp_path / "platform.db")
    seeded = make_testing_persistence_bundle(config)
    close = Mock()
    bundle = type(seeded)(
        platform_api=seeded.platform_api,
        access_registry=seeded.access_registry,
        audit_log=seeded.audit_log,
        close_callback=close,
    )
    with patch(
        "cre_mcp.postgres.runtime.build_postgres_hosted_persistence",
        return_value=bundle,
    ):
        app = create_http_app(config=config)

    async with app.router.lifespan_context(app):
        pass
    bundle.close()

    close.assert_called_once_with()


def test_http_app_closes_postgres_bundle_on_construction_failure(tmp_path):
    config = _config(cache_db_path=tmp_path / "platform.db")
    seeded = make_testing_persistence_bundle(config)
    close = Mock()
    bundle = type(seeded)(
        platform_api=seeded.platform_api,
        access_registry=seeded.access_registry,
        audit_log=seeded.audit_log,
        close_callback=close,
    )
    with patch(
        "cre_mcp.postgres.runtime.build_postgres_hosted_persistence",
        return_value=bundle,
    ), patch(
        "cre_mcp.server._build_hosted_customer_server",
        side_effect=RuntimeError("construction failed"),
    ), pytest.raises(RuntimeError, match="construction failed"):
        create_http_app(config=config)

    close.assert_called_once_with()


def test_public_standalone_app_cannot_mount_uncertified_deal_routes(tmp_path):
    config = _config(cache_db_path=tmp_path / "platform.db")

    with pytest.raises(TypeError, match="include_uncertified_deal_routes"):
        starlette_app(config=config, include_uncertified_deal_routes=True)


async def test_platform_routes_enforce_auth_through_the_composed_app(tmp_path):
    import httpx

    from cre_mcp.access.profiles import Profile
    from cre_mcp.platform.auth import OAuthSessionStore
    from cre_mcp.platform.repository import PlatformRepository

    config = _config(cache_db_path=tmp_path / "platform.db")
    app = create_testing_http_app(config=config)

    repo = PlatformRepository(config.cache_db_path)
    auth = OAuthSessionStore(config.cache_db_path)
    assert await repo.create_plan("pro", "Professional") is not None
    workspace = await repo.create_workspace("Acme CRE")
    user = await repo.create_user("owner@example.com", "Owner")
    assert workspace is not None and user is not None
    assert await repo.add_membership(workspace.public_id, user.id, role="owner")
    client = auth.register_client(
        "Claude",
        ("https://claude.ai/api/mcp/auth_callback",),
        ("deals:read",),
    )
    from cre_mcp.platform.entitlements import EntitlementStore

    EntitlementStore(config.cache_db_path).grant_access(
        workspace=workspace.public_id,
        source="manual",
        external_ref="hosting-grant",
        profile=Profile.FULL_OPERATOR,
        plan_key="pro",
        subject_user_id=user.id,
        scope="subject",
    )
    tokens = auth.issue_session(
        workspace.public_id,
        user.id,
        client.client_id,
        scopes=("deals:read",),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        unauthorized = await http.get("/v1/me")
        authorized = await http.get(
            "/v1/me", headers={"authorization": f"Bearer {tokens.access_token}"}
        )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["session"]["workspace_id"] == workspace.public_id


def test_run_server_keeps_stdio_call_shape_by_default(tmp_path):
    with patch("cre_mcp.server.mcp.run") as run:
        run_server(
            _config(transport="stdio", cache_db_path=tmp_path / "platform.db")
        )

    run.assert_called_once_with(transport="stdio")


def test_run_server_binds_configured_http_host_and_port(tmp_path):
    from fastmcp import FastMCP

    hosted = FastMCP(name="hosted-test")
    config = _config(
        transport="http",
        http_host="127.0.0.1",
        http_port=9123,
        cache_db_path=tmp_path / "platform.db",
    )
    bundle = make_testing_persistence_bundle(config)
    close = Mock()
    bundle.close_callback = close
    with patch(
        "cre_mcp.server._build_hosted_customer_server",
        return_value=hosted,
    ), patch(
        "cre_mcp.postgres.runtime.build_postgres_hosted_persistence",
        return_value=bundle,
    ), patch.object(hosted, "run") as run:
        run_server(config)

    run.assert_called_once_with(
        transport="http",
        host="127.0.0.1",
        port=9123,
        json_response=True,
    )
    close.assert_called_once_with()


def test_http_cli_flag_forces_http_without_binding():
    with patch("cre_mcp.server.run_server") as run:
        main(["--http"])

    run.assert_called_once_with(force_http=True)


def test_proxy_is_scoped_to_scraper_policies():
    config = _config(
        proxy_url="https://proxy-user:proxy-pass@example.test:8443",
        source_rights_enabled={
            "listing.loopnet": True,
            "market.census_acs": True,
        },
    )
    with patch("cre_mcp.http.fetch.AsyncSession") as session_class:
        client = FetchClient(config=config)
        client._get_client(client._policy_for_url("https://www.loopnet.com/search"))
        loopnet_kwargs = session_class.call_args.kwargs
        client._get_client(
            client._policy_for_url("https://api.census.gov/data/2024/acs/acs5")
        )
        census_kwargs = session_class.call_args.kwargs

    assert loopnet_kwargs["proxy"] == (
        "https://proxy-user:proxy-pass@example.test:8443"
    )
    assert loopnet_kwargs["allow_redirects"] is False
    assert "proxy" not in census_kwargs
    assert census_kwargs["allow_redirects"] is False


def test_browser_path_and_proxy_feed_nodriver_launch_options():
    fetcher = BrowserFetcher(
        _config(
            browser_path="/usr/bin/chromium",
            proxy_url="https://proxy.example.test:443",
        )
    )

    options = fetcher._launch_options()
    assert options["headless"] is True
    assert options["sandbox"] is False  # required for launchd/service startup
    assert options["browser_executable_path"] == "/usr/bin/chromium"
    # Sandbox-disabling flags must be present so Chromium starts as a service,
    # and the proxy arg is appended after them.
    assert "--no-sandbox" in options["browser_args"]
    assert "--disable-dev-shm-usage" in options["browser_args"]
    assert options["browser_args"][-1] == "--proxy-server=https://proxy.example.test:443"


def test_hosting_artifacts_are_present_and_keep_secrets_out_of_image():
    dockerfile = (ROOT / "Dockerfile").read_text()
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    tunnel = (ROOT / "deploy/cloudflared-config.example.yml").read_text()
    deploy = (ROOT / "deploy/DEPLOY.md").read_text()

    assert dockerfile.startswith("FROM python:3.11-slim")
    assert "CRE_TRANSPORT=http" in dockerfile
    assert "CRE_BROWSER_PATH=/usr/bin/chromium" in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert '["python", "-m", "cre_mcp", "--http"]' in dockerfile
    assert ".env" in dockerignore
    assert "service: http://cre-mcp:8000" in tunnel
    assert "service: http_status:404" in tunnel
    assert "Cloudflare Access" in deploy
    assert "claude mcp add --transport http" in deploy
    assert "CRE_PROXY_URL" in deploy
    assert "Max's steps" in deploy
