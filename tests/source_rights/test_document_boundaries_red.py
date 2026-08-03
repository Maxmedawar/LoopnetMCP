"""RED tests for document authority, storage, and SSRF boundaries."""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from cre_mcp.access.context import (
    TenantContext,
    local_context,
    use_context,
    use_runtime_config,
)
from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.platform.auth import AuthenticatedSession
from cre_mcp.platform.authority import AuthorityOutcome, InternalAdminAuthority
from cre_mcp.source_rights.attestations import (
    DOCUMENT_PURPOSES,
    DocumentAttestationStore,
    document_url_hash,
    issue_document_admin_authority,
    require_external_document_attestation,
)
from cre_mcp.source_rights.gate import SourceRightsDeniedError
from cre_mcp.tools.truth_tools import _fetch_bytes, ingest_document


def _hosted() -> TenantContext:
    return TenantContext(
        workspace_id="ws-doc-hosted",
        profile=Profile.FULL_OPERATOR,
        trusted=False,
        actor_id="actor-doc",
        session_id="session-doc",
    )


def _admin_authority():
    session = AuthenticatedSession(
        session_id="admin-session",
        workspace_id="ws-admin",
        user_id=7,
        client_id="admin-client",
        scopes=("admin",),
        audience="test",
        resource="test",
        access_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    outcome = AuthorityOutcome(
        session=session,
        workspace=None,
        membership=None,
        account=None,
        effective_access=None,
        context=None,
        reason=None,
        internal_admin=InternalAdminAuthority(
            user_id=session.user_id,
            role="platform_admin",
        ),
    )
    return issue_document_admin_authority(outcome)


def test_hosted_attestation_never_creates_local_sqlite_authority(tmp_path):
    path = tmp_path / "hosted-attestations.db"
    config = CreConfig(
        _env_file=None,
        transport="http",
        source_rights_attestations_path=path,
    )

    with use_context(_hosted()):
        with pytest.raises(SourceRightsDeniedError, match="durable repository"):
            require_external_document_attestation(
                "https://documents.example/report.pdf",
                "srcatt_missing",
                config=config,
            )

    assert not path.exists()


def test_document_hash_binds_exact_signed_query_order_token_and_userinfo():
    urls = (
        "https://alice:one@documents.example/report.pdf?x=1&token=alpha",
        "https://alice:two@documents.example/report.pdf?x=1&token=alpha",
        "https://alice:one@documents.example/report.pdf?x=1&token=beta",
        "https://alice:one@documents.example/report.pdf?token=alpha&x=1",
    )

    assert len({document_url_hash(url) for url in urls}) == len(urls)


def test_document_attestation_cannot_reclassify_known_prohibited_source():
    config = CreConfig(_env_file=None, transport="http")
    with patch(
        "cre_mcp.source_rights.attestations.DocumentAttestationStore",
        side_effect=AssertionError("attestation repository must not override registry"),
    ) as repository:
        with use_context(_hosted()):
            with pytest.raises(SourceRightsDeniedError, match="listing.loopnet"):
                require_external_document_attestation(
                    "https://www.loopnet.com/search/commercial-real-estate/",
                    "srcatt_fixture",
                    config=config,
                )

    repository.assert_not_called()


def test_external_document_cannot_reclassify_unregistered_route_on_known_host():
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"documents.external_url": True},
    )

    with use_context(local_context()):
        with pytest.raises(SourceRightsDeniedError, match="registered source host"):
            require_external_document_attestation(
                "https://api.census.gov/not-a-registered-dataset/report.pdf",
                None,
                config=config,
            )


def test_document_attestation_prefers_server_runtime_registry(tmp_path):
    stale = CreConfig(
        _env_file=None,
        transport="http",
        source_rights_registry_path=tmp_path / "stale.json",
    )
    runtime = CreConfig(
        _env_file=None,
        transport="http",
        source_rights_registry_path=tmp_path / "runtime.json",
    )
    classified = SimpleNamespace(source_id="listing.loopnet")
    registry = Mock()
    registry.for_url.return_value = classified

    with patch(
        "cre_mcp.source_rights.attestations.get_rights_registry",
        return_value=registry,
    ) as registry_factory, use_context(_hosted()), use_runtime_config(runtime):
        with pytest.raises(SourceRightsDeniedError, match="listing.loopnet"):
            require_external_document_attestation(
                "https://www.loopnet.com/property/1",
                "srcatt_fixture",
                config=stale,
            )

    registry_factory.assert_called_once_with(runtime.source_rights_registry_path)


def test_trusted_local_external_document_requires_explicit_source_toggle():
    url = "https://documents.example/report.pdf"
    disabled = CreConfig(_env_file=None, transport="stdio")
    enabled = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"documents.external_url": True},
    )

    with use_context(local_context()):
        with pytest.raises(SourceRightsDeniedError, match="explicitly enabled"):
            require_external_document_attestation(url, None, config=disabled)
        assert require_external_document_attestation(url, None, config=enabled) is None


def test_local_attestation_approval_requires_live_server_admin_authority(tmp_path):
    with use_context(local_context()):
        store = DocumentAttestationStore(tmp_path / "local-attestations.db")
        with pytest.raises(SourceRightsDeniedError, match="admin authority"):
            store.approve(
                workspace_id="local",
                actor_id="local-actor",
                session_id="local-session",
                url="https://documents.example/report.pdf",
                evidence_url="https://documents.example/rights-proof",
                evidence_hash="a" * 64,
                allowed_purposes=DOCUMENT_PURPOSES,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                admin_authority=None,
            )


def test_document_admin_authority_rejects_forged_duck_typed_outcome():
    forged = SimpleNamespace(
        internal_admin=SimpleNamespace(user_id=7, role="platform_admin"),
        session=SimpleNamespace(
            session_id="forged-session",
            access_expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )

    with pytest.raises(SourceRightsDeniedError, match="admin authority"):
        issue_document_admin_authority(forged)


def test_in_memory_attestation_store_enforces_scope_purpose_and_revoke():
    context = TenantContext(
        workspace_id="local-docs",
        profile=Profile.FULL_OPERATOR,
        trusted=True,
        actor_id="actor-local",
        session_id="session-local",
    )
    url = "https://documents.example/report.pdf?signature=exact"

    with use_context(context):
        store = DocumentAttestationStore(":memory:")
        record = store.approve(
            workspace_id=context.workspace_id,
            actor_id=context.actor_id,
            session_id=context.session_id,
            url=url,
            evidence_url="https://documents.example/rights-proof",
            evidence_hash="a" * 64,
            allowed_purposes={"retrieve", "store"},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            admin_authority=_admin_authority(),
        )
        assert store.require(
            attestation_id=record.attestation_id,
            context=context,
            url=url,
            purposes={"retrieve"},
        ) == record
        with pytest.raises(SourceRightsDeniedError, match="lacks purpose"):
            store.require(
                attestation_id=record.attestation_id,
                context=context,
                url=url,
                purposes={"output"},
            )
        store.revoke(
            record.attestation_id,
            admin_authority=_admin_authority(),
        )
        with pytest.raises(SourceRightsDeniedError, match="missing or revoked"):
            store.require(
                attestation_id=record.attestation_id,
                context=context,
                url=url,
                purposes={"retrieve"},
            )


@pytest.mark.asyncio
async def test_hosted_path_ingestion_denies_before_server_filesystem_access():
    with patch.object(
        Path,
        "is_file",
        side_effect=AssertionError("filesystem must not be inspected"),
    ) as is_file:
        with use_context(_hosted()):
            result = await ingest_document(
                "crexi:fixture",
                path="/etc/passwd",
            )

    assert "upload binding" in result["error"].casefold()
    is_file.assert_not_called()


@pytest.mark.asyncio
async def test_source_channel_cannot_override_path_or_url_channel(tmp_path):
    document = tmp_path / "statement.csv"
    document.write_text("Line Item,Amount\nNOI,1\n", encoding="utf-8")

    with use_context(local_context()):
        path_result = await ingest_document(
            "crexi:fixture",
            path=str(document),
            source_channel="scraped",
        )
        url_result = await ingest_document(
            "crexi:fixture",
            url="https://documents.example/report.pdf",
            source_channel="uploaded",
        )

    assert "source_channel" in path_result["error"]
    assert "source_channel" in url_result["error"]


@pytest.mark.asyncio
async def test_remote_ingestion_error_never_echoes_signed_url(caplog):
    secret = "signed-secret-e4d7"
    url = f"https://documents.example/report.pdf?signature={secret}"
    download = AsyncMock(side_effect=RuntimeError(f"failed at {url}"))

    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"documents.external_url": True},
    )
    with patch("cre_mcp.tools.truth_tools._to_thread_fetch", download):
        with use_context(local_context()), use_runtime_config(config):
            result = await ingest_document("crexi:fixture", url=url)

    assert secret not in result["error"]
    assert secret not in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/report.pdf",
        "http://[::1]/report.pdf",
        "http://10.0.0.4/report.pdf",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://localhost/report.pdf",
    ],
)
def test_document_socket_boundary_blocks_nonpublic_targets(url):
    from cre_mcp.tools.truth_tools import _resolve_public_document_target

    with pytest.raises(SourceRightsDeniedError, match="public HTTPS"):
        _resolve_public_document_target(url)


def test_document_socket_boundary_rejects_any_private_dns_answer():
    from cre_mcp.tools.truth_tools import _resolve_public_document_target

    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.9", 443)),
    ]
    with patch("cre_mcp.tools.truth_tools.socket.getaddrinfo", return_value=answers):
        with pytest.raises(SourceRightsDeniedError, match="public HTTPS"):
            _resolve_public_document_target("https://documents.example/report.pdf")


def test_document_fetch_without_runtime_context_denies_before_dns():
    with patch(
        "cre_mcp.tools.truth_tools.socket.getaddrinfo",
        side_effect=AssertionError("DNS must not run without runtime proof"),
    ) as getaddrinfo:
        with use_context(None):
            with pytest.raises(SourceRightsDeniedError, match="context is missing"):
                _fetch_bytes("https://documents.example/report.pdf")

    getaddrinfo.assert_not_called()


def test_document_fetch_pins_the_validated_dns_answer():
    response = Mock(status_code=200, content=b"document")
    response.raise_for_status.return_value = None
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.return_value = response
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ]

    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"documents.external_url": True},
    )
    with patch("cre_mcp.tools.truth_tools.socket.getaddrinfo", return_value=answers), \
         patch("curl_cffi.requests.Session", return_value=session) as session_class:
        with use_context(local_context()), use_runtime_config(config):
            assert _fetch_bytes("https://documents.example/report.pdf") == b"document"

    options = session_class.call_args.kwargs["curl_options"]
    assert any("93.184.216.34" in str(value) for value in options.values())
    session.get.assert_called_once()


def test_attestation_revoke_requires_live_server_admin_authority(tmp_path):
    with use_context(local_context()):
        store = DocumentAttestationStore(tmp_path / "local-attestations.db")
        with pytest.raises(SourceRightsDeniedError, match="admin authority"):
            store.revoke("srcatt_fixture", admin_authority=None)
