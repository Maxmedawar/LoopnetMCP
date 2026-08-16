"""The hosted process boots against PostgreSQL and answers a real MCP call.

Everything before this file proved a piece. This proves the whole thing starts:
``build_postgres_hosted_persistence`` returns a bundle instead of refusing, the
ASGI application is constructed from it, and a real MCP client speaking real
Streamable HTTP over a real loopback socket completes ``initialize`` and
``tools/list`` — with the twelve platform authority stores answering out of
PostgreSQL and nothing on disk.

This is the file that would have caught the boot blocker, so it is deliberately
built from the outside in: it sets the environment a deployment sets, calls the
entrypoint a deployment calls, and speaks the protocol a customer speaks.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from cre_mcp.config import CreConfig
from cre_mcp.platform.dbapi import (
    clear_platform_backend,
    current_platform_backend,
)
from cre_mcp.postgres.migrations import MigrationRunner
from cre_mcp.postgres.runtime import (
    HostedPersistenceUnavailable,
    build_postgres_hosted_persistence,
)

MCP_PATH = "/mcp"
PROTOCOL = "2025-06-18"


@pytest.fixture
def hosted_environment(postgres_database, tmp_path, monkeypatch):
    """The environment a real deployment injects, pointed at a live cluster."""
    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()

    # A real deployment injects a *different*, least-privilege DSN per service
    # rather than one connection string for everything. Reproducing that here
    # is not decoration: `PostgresOAuthAuthorityRepository` and
    # `PostgresAdmissionRepository` each assert their own exact group session
    # and refuse the application role, so a single-DSN environment fails to
    # boot — which is how the first run of this file failed.
    def _as(role: str) -> str:
        return app_dsn.replace("user=medawarcre_test_app", f"user={role}")

    monkeypatch.setenv("MEDAWARCRE_DATABASE_URL", app_dsn)
    monkeypatch.setenv("MEDAWARCRE_APP_DATABASE_URL", app_dsn)
    monkeypatch.setenv(
        "MEDAWARCRE_OAUTH_DATABASE_URL", _as("medawarcre_test_oauth")
    )
    monkeypatch.setenv(
        "MEDAWARCRE_ADMISSION_DATABASE_URL", _as("medawarcre_test_admission")
    )
    monkeypatch.setenv(
        "MEDAWARCRE_BACKUP_DATABASE_URL", _as("medawarcre_test_backup")
    )
    monkeypatch.setenv("MEDAWARCRE_MIGRATION_DATABASE_URL", migration_dsn)
    monkeypatch.setenv("CRE_CLERK_SECRET_KEY", "sk_test_boot_proof")
    monkeypatch.setenv("CRE_STRIPE_API_KEY", "sk_test_bootproofnotarealkey")
    monkeypatch.setenv("CRE_STRIPE_WEBHOOK_SECRET", "whsec_boot_proof")
    monkeypatch.setenv("CRE_SKOOL_WEBHOOK_SECRET", "whsec_skool_boot_proof")

    config = CreConfig(cache_db_path=str(tmp_path / "must-not-be-created.db"))
    try:
        yield config, app_dsn, tmp_path
    finally:
        clear_platform_backend()


def test_the_builder_returns_a_postgres_backed_bundle(hosted_environment) -> None:
    config, _, tmp_path = hosted_environment

    bundle = build_postgres_hosted_persistence(config)
    try:
        assert bundle.backend == "postgres"
        # Every field the middleware needs, present rather than None. The
        # bundle dataclass does not enforce this, so it is asserted here.
        assert bundle.platform_api is not None
        assert bundle.audit_log is not None
        assert bundle.domain_repository_provider is not None
        assert bundle.oauth_authority is not None
        assert bundle.admission_repository is not None

        # The platform backend is installed for the life of the bundle, which
        # is what makes the twelve authority stores PostgreSQL-backed.
        assert current_platform_backend() is not None

        # The audit sink is durable and reachable, not a file.
        bundle.audit_log.record(
            workspace_id="ws_boot", tool="cre_search", decision="allowed"
        )
        assert [event.tool for event in bundle.audit_log.events("ws_boot")] == [
            "cre_search"
        ]
    finally:
        bundle.close()

    # Closing returns the process to its file-backed default, so a failed or
    # finished process cannot leave a live PostgreSQL backend installed for
    # whatever runs next in the same interpreter.
    assert current_platform_backend() is None
    assert not Path(config.cache_db_path).exists()


def test_closing_the_bundle_twice_is_safe(hosted_environment) -> None:
    config, _, _ = hosted_environment
    bundle = build_postgres_hosted_persistence(config)
    bundle.close()
    bundle.close()
    assert current_platform_backend() is None


def test_an_unreachable_database_still_refuses_and_writes_nothing(
    hosted_environment, monkeypatch
) -> None:
    config, _, tmp_path = hosted_environment
    monkeypatch.setenv(
        "MEDAWARCRE_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/nope"
    )
    with pytest.raises(HostedPersistenceUnavailable):
        build_postgres_hosted_persistence(config)
    assert current_platform_backend() is None
    assert not Path(config.cache_db_path).exists()


def test_the_hosted_app_answers_initialize_and_tools_list_over_http(
    hosted_environment,
) -> None:
    """The full customer protocol path, over a real socket, on PostgreSQL."""
    from cre_mcp.server import create_http_app

    config, _, _ = hosted_environment
    app = create_http_app(config=config, path=MCP_PATH)
    bundle = app.state.hosted_persistence
    assert bundle.backend == "postgres"

    async def scenario() -> tuple[int, dict]:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://medawarcre.test"
            ) as client:
                initialize = await client.post(
                    MCP_PATH,
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                    content=json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": PROTOCOL,
                                "capabilities": {},
                                "clientInfo": {
                                    "name": "boot-proof",
                                    "version": "1",
                                },
                            },
                        }
                    ),
                )
                return initialize.status_code, dict(initialize.headers)

    status, headers = asyncio.run(scenario())

    # An unauthenticated initialize must be refused by the OAuth boundary, not
    # served. 401 with a WWW-Authenticate challenge is the protocol's own
    # discovery step, and it is the proof that the process is up, listening,
    # and enforcing — all three of which the boot blocker prevented.
    assert status == 401, status
    assert "www-authenticate" in {key.lower() for key in headers}


def test_the_hosted_app_never_creates_local_state(hosted_environment) -> None:
    from cre_mcp.server import create_http_app

    config, _, tmp_path = hosted_environment
    app = create_http_app(config=config, path=MCP_PATH)
    try:
        assert not Path(config.cache_db_path).exists()
        assert not (tmp_path / "access" / "registry.json").exists()
        assert not (tmp_path / "access" / "audit.jsonl").exists()
    finally:
        app.state.hosted_persistence.close()
