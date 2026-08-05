from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastmcp import FastMCP

from cre_mcp.access.audit import AuditLog
from cre_mcp.access.context import TenantContext
from cre_mcp.access.middleware import AccessMiddleware
from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.platform.auth import AuthenticatedSession
from cre_mcp.platform.authority import AuthorityOutcome, AuthoritativeOAuthVerifier
from cre_mcp.server import install_access_control


class RecordingAuthority:
    def __init__(self, outcome=None, error=None) -> None:
        self.outcome = outcome
        self.error = error
        self.thread_id = None

    def resolve(self, _token):
        self.thread_id = threading.get_ident()
        if self.error is not None:
            raise self.error
        return self.outcome


def _outcome() -> AuthorityOutcome:
    workspace_id = "oauth-lifecycle"
    user_id = str(uuid4())
    session_id = str(uuid4())
    session = AuthenticatedSession(
        session_id=session_id,
        workspace_id=workspace_id,
        user_id=user_id,
        client_id="client-1",
        scopes=("mcp:tools",),
        audience="medawarcre-mcp",
        resource="https://medawarcre.com/mcp",
        access_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    context = TenantContext(
        workspace_id=workspace_id,
        profile=Profile.FULL_OPERATOR,
        plan="pro",
        actor_id=user_id,
        session_id=session_id,
    )
    return AuthorityOutcome(
        session=session,
        workspace=None,
        membership=None,
        account=None,
        effective_access=None,
        context=context,
        reason=None,
    )


async def test_authoritative_oauth_repository_runs_off_event_loop() -> None:
    authority = RecordingAuthority(_outcome())
    verifier = AuthoritativeOAuthVerifier(authority)
    event_loop_thread = threading.get_ident()

    token = await verifier.verify_token("opaque-token")

    assert token is not None
    assert authority.thread_id != event_loop_thread
    assert token.claims["tenant_context"]["workspace_id"] == "oauth-lifecycle"


async def test_authoritative_oauth_repository_failure_is_invalid_token() -> None:
    authority = RecordingAuthority(error=RuntimeError("database secret"))
    verifier = AuthoritativeOAuthVerifier(authority)

    assert await verifier.verify_token("opaque-token") is None


async def test_malformed_authority_outcome_is_invalid_token() -> None:
    authority = RecordingAuthority(object())
    verifier = AuthoritativeOAuthVerifier(authority)

    assert await verifier.verify_token("opaque-token") is None


def test_hosted_install_requires_explicit_oauth_and_admission(tmp_path) -> None:
    server = FastMCP(name="missing-hosted-authority")
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")

    with pytest.raises(RuntimeError, match="explicit PostgreSQL authority"):
        install_access_control(
            config,
            runtime_mode="http",
            server=server,
            platform_api=object(),
            audit_log=AuditLog(tmp_path / "audit.jsonl"),
        )


def test_hosted_install_requires_explicit_domain_repository_provider(
    tmp_path,
) -> None:
    server = FastMCP(name="missing-hosted-domain-provider")
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")

    with pytest.raises(RuntimeError, match="explicit PostgreSQL authority"):
        install_access_control(
            config,
            runtime_mode="http",
            server=server,
            platform_api=object(),
            audit_log=AuditLog(tmp_path / "audit.jsonl"),
            oauth_authority=RecordingAuthority(),
            admission_repository=object(),
        )


def test_hosted_install_uses_explicit_authorities_without_local_registry(
    tmp_path,
) -> None:
    server = FastMCP(name="explicit-hosted-authority")
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")
    authority = RecordingAuthority()
    admission = object()
    domain_provider = object()

    uninstall = install_access_control(
        config,
        runtime_mode="http",
        server=server,
        platform_api=object(),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        oauth_authority=authority,
        admission_repository=admission,
        domain_repository_provider=domain_provider,
    )
    try:
        middleware = next(
            item for item in server.middleware if isinstance(item, AccessMiddleware)
        )
        assert server.auth.resolver is authority
        assert middleware.engine.registry is None
        assert middleware._admission is admission
        assert middleware._domain_repositories is domain_provider
    finally:
        uninstall()


def test_hosted_install_rejects_local_registry(tmp_path) -> None:
    server = FastMCP(name="forbidden-hosted-registry")
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")

    with pytest.raises(RuntimeError, match="forbids a local access registry"):
        install_access_control(
            config,
            runtime_mode="http",
            server=server,
            platform_api=object(),
            access_registry=object(),
            audit_log=AuditLog(tmp_path / "audit.jsonl"),
            oauth_authority=RecordingAuthority(),
            admission_repository=object(),
            domain_repository_provider=object(),
        )


def test_failed_reconfiguration_preserves_installed_guard(tmp_path) -> None:
    server = FastMCP(name="preserved-access-guard")
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")
    uninstall = install_access_control(
        config,
        runtime_mode="stdio",
        server=server,
    )
    original = next(
        item for item in server.middleware if isinstance(item, AccessMiddleware)
    )
    try:
        with pytest.raises(RuntimeError, match="explicit PostgreSQL authority"):
            install_access_control(
                config,
                runtime_mode="http",
                server=server,
                platform_api=object(),
                audit_log=AuditLog(tmp_path / "audit.jsonl"),
            )
        assert original in server.middleware
    finally:
        uninstall()


def test_installation_failure_rolls_back_guard_and_auth(tmp_path, monkeypatch) -> None:
    server = FastMCP(name="rolled-back-access-guard")
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")
    uninstall = install_access_control(
        config,
        runtime_mode="stdio",
        server=server,
    )
    original_middleware = list(server.middleware)
    original_auth = server.auth

    def fail_install(_middleware):
        raise RuntimeError("injected middleware installation failure")

    monkeypatch.setattr(server, "add_middleware", fail_install)
    try:
        with pytest.raises(RuntimeError, match="injected middleware"):
            install_access_control(
                config,
                runtime_mode="http",
                server=server,
                platform_api=object(),
                audit_log=AuditLog(tmp_path / "audit.jsonl"),
                oauth_authority=RecordingAuthority(),
                admission_repository=object(),
                domain_repository_provider=object(),
            )
        assert server.middleware == original_middleware
        assert server.auth is original_auth
    finally:
        uninstall()
