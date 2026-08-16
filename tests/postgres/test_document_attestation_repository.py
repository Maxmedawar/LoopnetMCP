from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.access.context import TenantContext, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.document_attestations import (
    PostgresDocumentAttestationRepository,
)
from cre_mcp.postgres.domains import (
    HostedRequestRepositories,
    use_hosted_request_repositories,
)
from cre_mcp.postgres.migrations import MigrationRunner, load_migrations
from cre_mcp.postgres.pool import PostgresDatabase
from cre_mcp.postgres.schema import (
    EXPECTED_MIGRATION_VERSION,
    EXPECTED_RLS_TABLES,
    EXPECTED_TABLES,
)
from cre_mcp.source_rights.attestations import (
    document_url_hash,
    require_external_document_attestation,
    use_hosted_document_attestation_repository,
)
from cre_mcp.source_rights.gate import SourceRightsDeniedError


def _admission(
    *,
    workspace_public_id: str = "ws_doc_a",
    actor_user_id: str | None = None,
    session_id: str | None = None,
) -> AdmissionOutcome:
    return AdmissionOutcome(
        invocation_id=str(uuid4()),
        request_correlation_id=str(uuid4()),
        workspace_public_id=workspace_public_id,
        actor_user_id=actor_user_id or str(uuid4()),
        session_id=session_id or str(uuid4()),
        tool_name="ingest_document",
        decision="allowed",
        reason_code="authority_admitted",
        safe_reason="request admitted by live authority",
        replayed=False,
        finalized=False,
    )


def _context(admission: AdmissionOutcome) -> TenantContext:
    return TenantContext(
        workspace_id=admission.workspace_public_id,
        profile=Profile.FULL_OPERATOR,
        actor_id=admission.actor_user_id,
        session_id=admission.session_id,
    )


def _repositories(
    admission: AdmissionOutcome,
    document: PostgresDocumentAttestationRepository,
) -> HostedRequestRepositories:
    marker = object()
    return HostedRequestRepositories(
        admission=admission,
        platform=marker,
        provider=marker,
        search=marker,
        deal=marker,
        privacy=marker,
        job=marker,
        document=document,
        truth_asset=marker,
    )


def _seed(
    admin_dsn: str,
    admission: AdmissionOutcome,
    *,
    revoked: bool = False,
    expired: bool = False,
) -> tuple[str, str, str]:
    workspace_id = str(uuid4())
    other_workspace_id = str(uuid4())
    other_actor_id = str(uuid4())
    other_session_id = str(uuid4())
    attestation_id = f"srcatt_{uuid4().hex}"
    now = datetime.now(UTC)
    approved_at = now - timedelta(hours=2) if expired else now
    expires_at = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) VALUES "
            "(%s,'doc-a@example.test','Doc A','active'),"
            "(%s,'doc-b@example.test','Doc B','active')",
            (admission.actor_user_id, other_actor_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.oauth_clients("
            "client_id,name,redirect_uris,scopes,active) VALUES "
            "('doc-client','Document Client',ARRAY['https://client.example/cb'],"
            "ARRAY['mcp:tools'],true)"
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) VALUES "
            "(%s,%s,'Document A','active'),"
            "(%s,'ws_doc_b','Document B','active')",
            (workspace_id, admission.workspace_public_id, other_workspace_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'owner','active'),(%s,%s,'owner','active')",
            (
                workspace_id,
                admission.actor_user_id,
                other_workspace_id,
                other_actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.oauth_sessions("
            "id,workspace_id,user_id,client_id,scopes,audience,resource,"
            "authority_version,access_hash,refresh_hash,access_expires_at,"
            "refresh_expires_at,refresh_family_expires_at) VALUES "
            "(%s,%s,%s,'doc-client',ARRAY['mcp:tools'],'aud','resource',1,"
            "decode(repeat('11',32),'hex'),decode(repeat('12',32),'hex'),"
            "statement_timestamp()+interval '1 hour',"
            "statement_timestamp()+interval '2 hours',"
            "statement_timestamp()+interval '3 hours'),"
            "(%s,%s,%s,'doc-client',ARRAY['mcp:tools'],'aud','resource',1,"
            "decode(repeat('21',32),'hex'),decode(repeat('22',32),'hex'),"
            "statement_timestamp()+interval '1 hour',"
            "statement_timestamp()+interval '2 hours',"
            "statement_timestamp()+interval '3 hours')",
            (
                admission.session_id,
                workspace_id,
                admission.actor_user_id,
                other_session_id,
                other_workspace_id,
                other_actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.access_decision_audit("
            "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
            "session_correlation_hash,request_correlation_id,tool_name,decision,"
            "reason_code,safe_reason,args_hash,admission_binding_hash) VALUES ("
            "%s,'admission',true,%s,%s,"
            "pg_catalog.sha256(pg_catalog.convert_to(%s,'UTF8')),%s,%s,'allowed',"
            "'authority_admitted','request admitted by live authority',"
            "decode(repeat('31',32),'hex'),decode(repeat('32',32),'hex'))",
            (
                admission.invocation_id,
                workspace_id,
                admission.actor_user_id,
                admission.session_id,
                admission.request_correlation_id,
                admission.tool_name,
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.source_document_attestations("
            "attestation_id,workspace_id,actor_user_id,oauth_session_id,url_hash,"
            "evidence_url,evidence_hash,allowed_purposes,approved_by,approved_at,"
            "expires_at,revoked_at) VALUES ("
            "%s,%s,%s,%s,decode(%s,'hex'),'https://evidence.example/proof',"
            "decode(repeat('41',32),'hex'),ARRAY['retrieve','store'],%s,%s,%s,%s)",
            (
                attestation_id,
                workspace_id,
                admission.actor_user_id,
                admission.session_id,
                document_url_hash("https://documents.example/report.pdf?sig=exact"),
                admission.actor_user_id,
                approved_at,
                expires_at,
                now if revoked else None,
            ),
        )
    return workspace_id, other_workspace_id, attestation_id


def _database(app_dsn: str) -> PostgresDatabase:
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=2, runtime_mode="app")
    )
    database.open()
    return database


def test_migration_0005_adds_exact_session_bound_document_authority() -> None:
    migrations = load_migrations()
    # Extended deliberately from [1..9] at migrations 0010 (platform
    # authority), 0011 (access audit log) and 0012 (identity projection).
    # The literal is kept rather than derived so that adding a migration
    # cannot pass unnoticed -- which is the only reason this line exists.
    assert [migration.version for migration in migrations] == [
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14
    ]
    assert migrations[4].name == "document attestation authority"
    assert EXPECTED_MIGRATION_VERSION == 14
    assert "source_document_attestations" in EXPECTED_TABLES
    assert "source_document_attestations" in EXPECTED_RLS_TABLES


def test_document_attestation_requires_exact_active_scope_and_returns_parity_record(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _, _, attestation_id = _seed(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresDocumentAttestationRepository(database, admission)
    repositories = _repositories(admission, repository)
    context = _context(admission)
    try:
        with (
            use_context(context),
            use_hosted_request_repositories(repositories),
            use_hosted_document_attestation_repository(repository),
        ):
            record = repository.require(
                attestation_id=attestation_id,
                context=context,
                url="https://documents.example/report.pdf?sig=exact#ignored",
                purposes={"retrieve"},
            )
            bridged = require_external_document_attestation(
                "https://documents.example/report.pdf?sig=exact#ignored",
                attestation_id,
                purposes={"retrieve"},
            )
        assert record.attestation_id == attestation_id
        assert record.workspace_id == admission.workspace_public_id
        assert record.actor_id == admission.actor_user_id
        assert record.session_id == admission.session_id
        assert record.allowed_purposes == ("retrieve", "store")
        assert record.evidence_hash == "41" * 32
        assert bridged == record

        with pytest.raises(SourceRightsDeniedError, match="request scope"):
            repository.require(
                attestation_id=attestation_id,
                context=_context(admission),
                url="https://documents.example/report.pdf?sig=exact",
                purposes={"retrieve"},
            )
    finally:
        database.close()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"workspace_id": "ws_doc_b"}, "scope mismatch"),
        ({"actor_id": "00000000-0000-0000-0000-000000000001"}, "scope mismatch"),
        ({"session_id": "00000000-0000-0000-0000-000000000002"}, "scope mismatch"),
    ],
)
def test_document_attestation_rejects_context_authority_mismatch_before_database(
    postgres_database: tuple[str, str, str],
    mutation: dict[str, str],
    message: str,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _, _, attestation_id = _seed(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresDocumentAttestationRepository(database, admission)
    repositories = _repositories(admission, repository)
    mismatched = _context(admission).model_copy(update=mutation)
    try:
        with use_context(mismatched), use_hosted_request_repositories(repositories):
            with pytest.raises(SourceRightsDeniedError, match=message):
                repository.require(
                    attestation_id=attestation_id,
                    context=mismatched,
                    url="https://documents.example/report.pdf?sig=exact",
                    purposes={"retrieve"},
                )
    finally:
        database.close()


@pytest.mark.parametrize(
    ("revoked", "expired", "url", "purposes", "message"),
    [
        (True, False, "https://documents.example/report.pdf?sig=exact", {"retrieve"}, "missing or revoked"),
        (False, True, "https://documents.example/report.pdf?sig=exact", {"retrieve"}, "expired"),
        (False, False, "https://documents.example/report.pdf?sig=changed", {"retrieve"}, "scope mismatch"),
        (False, False, "https://documents.example/report.pdf?sig=exact", {"output"}, "lacks purpose"),
        (False, False, "https://documents.example/report.pdf?sig=exact", set(), "lacks purpose"),
    ],
)
def test_document_attestation_fails_closed_on_record_or_request_mismatch(
    postgres_database: tuple[str, str, str],
    revoked: bool,
    expired: bool,
    url: str,
    purposes: set[str],
    message: str,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _, _, attestation_id = _seed(
        admin_dsn,
        admission,
        revoked=revoked,
        expired=expired,
    )
    database = _database(app_dsn)
    repository = PostgresDocumentAttestationRepository(database, admission)
    repositories = _repositories(admission, repository)
    context = _context(admission)
    try:
        with use_context(context), use_hosted_request_repositories(
            repositories
        ):
            with pytest.raises(SourceRightsDeniedError, match=message):
                repository.require(
                    attestation_id=attestation_id,
                    context=context,
                    url=url,
                    purposes=purposes,
                )
    finally:
        database.close()


def test_document_rls_requires_oauth_session_and_app_cannot_mutate(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    workspace_id, _, _ = _seed(admin_dsn, admission)
    database = _database(app_dsn)
    try:
        with database.admitted_connection(admission) as connection:
            assert connection.execute(
                "SELECT current_setting('app.oauth_session_id')"
            ).fetchone() == (admission.session_id,)
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.source_document_attestations"
            ).fetchone() == (1,)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with connection.transaction():
                    connection.execute(
                        "DELETE FROM medawarcre.source_document_attestations"
                    )

        with psycopg.connect(app_dsn) as connection:
            connection.execute(
                "SELECT set_config('app.workspace_id',%s,true),"
                "set_config('app.actor_user_id',%s,true)",
                (workspace_id, admission.actor_user_id),
            )
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.source_document_attestations"
            ).fetchone() == (0,)
    finally:
        database.close()


def test_document_attestation_session_must_belong_to_exact_actor(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    workspace_id, _, _ = _seed(admin_dsn, admission)
    other_actor_id = str(uuid4())
    other_session_id = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) "
            "VALUES (%s,%s,'Other Session Actor','active')",
            (other_actor_id, f"{uuid4().hex}@example.test"),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'member','active')",
            (workspace_id, other_actor_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.oauth_sessions("
            "id,workspace_id,user_id,client_id,scopes,audience,resource,"
            "authority_version,access_hash,refresh_hash,access_expires_at,"
            "refresh_expires_at,refresh_family_expires_at) VALUES ("
            "%s,%s,%s,'doc-client',ARRAY['mcp:tools'],'aud','resource',1,"
            "decode(repeat('51',32),'hex'),decode(repeat('52',32),'hex'),"
            "statement_timestamp()+interval '1 hour',"
            "statement_timestamp()+interval '2 hours',"
            "statement_timestamp()+interval '3 hours')",
            (other_session_id, workspace_id, other_actor_id),
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with connection.transaction():
                connection.execute(
                    "INSERT INTO medawarcre.source_document_attestations("
                    "attestation_id,workspace_id,actor_user_id,oauth_session_id,"
                    "url_hash,evidence_url,evidence_hash,allowed_purposes,"
                    "approved_by,expires_at) VALUES ("
                    "%s,%s,%s,%s,decode(repeat('61',32),'hex'),"
                    "'https://evidence.example/proof',decode(repeat('62',32),'hex'),"
                    "ARRAY['retrieve'],%s,statement_timestamp()+interval '1 hour')",
                    (
                        f"srcatt_{uuid4().hex}",
                        workspace_id,
                        admission.actor_user_id,
                        other_session_id,
                        admission.actor_user_id,
                    ),
                )


def test_document_repository_database_failure_is_fixed_and_never_falls_back(
    postgres_database: tuple[str, str, str],
    tmp_path,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _, _, attestation_id = _seed(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresDocumentAttestationRepository(database, admission)
    repositories = _repositories(admission, repository)
    database.close()
    context = _context(admission)
    with use_context(context), use_hosted_request_repositories(
        repositories
    ):
        with pytest.raises(SourceRightsDeniedError, match="authority unavailable"):
            repository.require(
                attestation_id=attestation_id,
                context=context,
                url="https://documents.example/report.pdf?sig=exact",
                purposes={"retrieve"},
            )
    assert list(tmp_path.iterdir()) == []


def test_document_repository_rejects_different_repository_in_active_scope(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _, _, attestation_id = _seed(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresDocumentAttestationRepository(database, admission)
    other = PostgresDocumentAttestationRepository(database, replace(admission))
    repositories = _repositories(admission, other)
    context = _context(admission)
    try:
        with use_context(context), use_hosted_request_repositories(
            repositories
        ):
            with pytest.raises(SourceRightsDeniedError, match="request scope"):
                repository.require(
                    attestation_id=attestation_id,
                    context=context,
                    url="https://documents.example/report.pdf?sig=exact",
                    purposes={"retrieve"},
                )
    finally:
        database.close()
