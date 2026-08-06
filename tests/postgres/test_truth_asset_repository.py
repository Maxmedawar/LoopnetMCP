from __future__ import annotations

import asyncio
import hashlib
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.access.context import TenantContext, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.domains import (
    AdmittedRequestUnavailable,
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
from cre_mcp.postgres.truth_assets import (
    PostgresTruthAssetRepository,
    TruthAssetUnavailable,
)
from cre_mcp.source_rights.attestations import (
    use_hosted_document_attestation_repository,
)
from cre_mcp.tools.truth_tools import ingest_document
from cre_mcp.truth.models import (
    DocKind,
    DocumentRecord,
    ExtractedFigure,
    ExtractionMethod,
    FieldClaim,
    Lineage,
)
from cre_mcp.truth.store import TruthStore, get_truth_store


def _admission(
    *,
    workspace_public_id: str = "ws_truth_a",
    actor_user_id: str | None = None,
    session_id: str | None = None,
    tool_name: str = "ingest_document",
) -> AdmissionOutcome:
    return AdmissionOutcome(
        invocation_id=str(uuid4()),
        request_correlation_id=str(uuid4()),
        workspace_public_id=workspace_public_id,
        actor_user_id=actor_user_id or str(uuid4()),
        session_id=session_id or str(uuid4()),
        tool_name=tool_name,
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


class _DealRepository:
    async def get_deal(self, deal_id: str):
        return None


class _DocumentRepository:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events

    def require(self, **kwargs):
        if self.events is not None:
            self.events.append("attest")
        return {"attested": True}


def _repositories(
    admission: AdmissionOutcome,
    truth_asset: object,
    *,
    document: object | None = None,
    deal: object | None = None,
) -> HostedRequestRepositories:
    marker = object()
    return HostedRequestRepositories(
        admission=admission,
        platform=marker,
        provider=marker,
        search=marker,
        deal=deal or marker,
        privacy=marker,
        job=marker,
        document=document or marker,
        truth_asset=truth_asset,
    )


def _seed_admission(admin_dsn: str, admission: AdmissionOutcome) -> str:
    workspace_id = str(uuid4())
    email = f"truth-{uuid4().hex}@example.test"
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) "
            "VALUES (%s,%s,'Truth Actor','active')",
            (admission.actor_user_id, email),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) "
            "VALUES (%s,%s,'Truth Workspace','active')",
            (workspace_id, admission.workspace_public_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'owner','active')",
            (workspace_id, admission.actor_user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.access_decision_audit("
            "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
            "session_correlation_hash,request_correlation_id,tool_name,decision,"
            "reason_code,safe_reason,args_hash,admission_binding_hash) VALUES ("
            "%s,'admission',true,%s,%s,"
            "pg_catalog.sha256(pg_catalog.convert_to(%s,'UTF8')),%s,%s,'allowed',"
            "'authority_admitted','request admitted by live authority',"
            "decode(repeat('51',32),'hex'),decode(repeat('52',32),'hex'))",
            (
                admission.invocation_id,
                workspace_id,
                admission.actor_user_id,
                admission.session_id,
                admission.request_correlation_id,
                admission.tool_name,
            ),
        )
    return workspace_id


def _seed_workspace_member_admission(
    admin_dsn: str,
    admission: AdmissionOutcome,
    workspace_id: str,
) -> None:
    email = f"truth-member-{uuid4().hex}@example.test"
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) "
            "VALUES (%s,%s,'Truth Member','active')",
            (admission.actor_user_id, email),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'member','active')",
            (workspace_id, admission.actor_user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.access_decision_audit("
            "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
            "session_correlation_hash,request_correlation_id,tool_name,decision,"
            "reason_code,safe_reason,args_hash,admission_binding_hash) VALUES ("
            "%s,'admission',true,%s,%s,"
            "pg_catalog.sha256(pg_catalog.convert_to(%s,'UTF8')),%s,%s,'allowed',"
            "'authority_admitted','request admitted by live authority',"
            "decode(repeat('61',32),'hex'),decode(repeat('62',32),'hex'))",
            (
                admission.invocation_id,
                workspace_id,
                admission.actor_user_id,
                admission.session_id,
                admission.request_correlation_id,
                admission.tool_name,
            ),
        )


def _database(app_dsn: str) -> PostgresDatabase:
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=2, runtime_mode="app")
    )
    database.open()
    return database


def _asset(
    *,
    deal_id: str = "crexi:truth-1",
    blob: bytes = b"Line Item,Amount\nNet Operating Income,180000\n",
) -> tuple[DocumentRecord, bytes, list[FieldClaim]]:
    digest = hashlib.sha256(blob).hexdigest()
    origin = "https://documents.example/t12.csv"
    record = DocumentRecord(
        document_id=digest,
        deal_id=deal_id,
        doc_kind=DocKind.T12,
        source_channel="scraped",
        origin=origin,
        blob_path="",
        n_pages=None,
        parse_status="parsed",
        redactions=0,
        ingested_at=datetime.now(UTC).isoformat(),
    )

    def claim(
        field: str,
        value: float | str | None,
        *,
        subject: str | None = None,
        unit: str = "usd",
        page: int | None = None,
        cell: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        flags: list[str] | None = None,
    ) -> FieldClaim:
        return FieldClaim(
            field=field,
            subject=subject,
            figure=ExtractedFigure(
                value=value,
                unit=unit,
                confidence=0.875,
                lineage=Lineage(
                    document_id=digest,
                    doc_kind=DocKind.T12,
                    source_channel="scraped",
                    page=page,
                    cell=cell,
                    bbox=bbox,
                    raw_text=f"raw {field}",
                    extraction_method=(
                        ExtractionMethod.PDF_TABLE
                        if page is not None
                        else ExtractionMethod.CSV_CELL
                    ),
                    origin=origin,
                ),
            ),
            flags=flags or [],
        )

    return record, blob, [
        claim("noi", 180000.0, cell="Sheet1!B2", flags=["actual"]),
        claim("tenant_name", "North Star Market", subject="Suite 101", unit="text"),
        claim(
            "guarantor",
            None,
            subject="Suite 101",
            unit="text",
            page=2,
            bbox=(1.0, 2.0, 30.0, 40.0),
        ),
    ]


def test_migration_0006_adds_truth_asset_authority() -> None:
    migrations = load_migrations()
    assert [migration.version for migration in migrations] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert migrations[5].name == "truth asset persistence"
    assert EXPECTED_MIGRATION_VERSION == 8
    assert {
        "truth_document_blobs",
        "truth_documents",
        "truth_claims",
    } <= EXPECTED_TABLES
    assert {
        "truth_document_blobs",
        "truth_documents",
        "truth_claims",
    } <= EXPECTED_RLS_TABLES


def test_truth_store_factory_uses_exact_hosted_port_and_blocks_local_store(
    tmp_path,
) -> None:
    admission = _admission()
    hosted_truth_repository = object()
    repositories = _repositories(admission, hosted_truth_repository)

    assert isinstance(get_truth_store(), TruthStore)
    with use_hosted_request_repositories(repositories):
        assert get_truth_store() is hosted_truth_repository
        with pytest.raises(AdmittedRequestUnavailable):
            TruthStore(CreConfig(_env_file=None, cache_db_path=tmp_path / "forbidden.db"))
    assert not (tmp_path / "documents").exists()


@pytest.mark.asyncio
async def test_truth_asset_round_trip_is_structured_idempotent_and_replaces_claims(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    workspace_id = _seed_admission(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    repositories = _repositories(admission, repository)
    record, blob, claims = _asset()
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            repositories
        ):
            saved = await repository.save_document(record, blob, claims, ext="csv")
            repeated = await repository.save_document(record, blob, claims, ext="csv")
            documents = await repository.list_documents(record.deal_id)
            restored = await repository.get_claims(record.deal_id)

            replacement = [claims[0].model_copy(update={"flags": ["audited"]})]
            await repository.save_document(record, blob, replacement, ext="csv")
            replaced = await repository.get_claims(record.deal_id)

        assert saved == record
        assert repeated == record
        assert saved.blob_path == ""
        assert documents == [
            {
                "document_id": record.document_id,
                "doc_kind": record.doc_kind.value,
                "source_channel": record.source_channel,
                "origin": record.origin,
                "n_pages": record.n_pages,
                "parse_status": record.parse_status,
                "redactions": record.redactions,
                "ingested_at": record.ingested_at,
                "claim_count": len(claims),
            }
        ]
        assert restored == sorted(
            [claim.model_dump(mode="json") for claim in claims],
            key=lambda item: (item["field"], item["subject"] or ""),
        )
        assert replaced == [replacement[0].model_dump(mode="json")]

        with psycopg.connect(admin_dsn) as connection:
            counts = connection.execute(
                "SELECT "
                "(SELECT count(*) FROM medawarcre.truth_document_blobs),"
                "(SELECT count(*) FROM medawarcre.truth_documents),"
                "(SELECT count(*) FROM medawarcre.truth_claims)"
            ).fetchone()
            stored = connection.execute(
                "SELECT workspace_id,encode(document_id,'hex'),content "
                "FROM medawarcre.truth_document_blobs"
            ).fetchone()
        assert counts == (1, 1, 1)
        assert stored is not None
        assert (str(stored[0]), stored[1], stored[2]) == (
            workspace_id,
            record.document_id,
            blob,
        )
    finally:
        database.close()


@pytest.mark.asyncio
async def test_truth_asset_resave_keeps_document_and_claim_lineage_consistent(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_admission(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    record, blob, claims = _asset()
    replacement_record = record.model_copy(
        update={
            "doc_kind": DocKind.RENT_ROLL,
            "source_channel": "uploaded",
            "origin": "rent-roll.xlsx",
        }
    )
    replacement_claims = [
        claim.model_copy(
            update={
                "figure": claim.figure.model_copy(
                    update={
                        "lineage": claim.figure.lineage.model_copy(
                            update={
                                "doc_kind": DocKind.RENT_ROLL,
                                "source_channel": "uploaded",
                                "origin": "rent-roll.xlsx",
                            }
                        )
                    }
                )
            }
        )
        for claim in claims
    ]
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            await repository.save_document(record, blob, claims, ext="csv")
            await repository.save_document(
                replacement_record,
                blob,
                replacement_claims,
                ext="xlsx",
            )
            restored = await repository.get_claims(record.deal_id)

        with psycopg.connect(admin_dsn) as connection:
            metadata = connection.execute(
                "SELECT doc_kind,source_channel,origin,format "
                "FROM medawarcre.truth_documents"
            ).fetchone()
        assert metadata == (
            DocKind.RENT_ROLL.value,
            "uploaded",
            "rent-roll.xlsx",
            "xlsx",
        )
        assert {item["figure"]["lineage"]["source_channel"] for item in restored} == {
            "uploaded"
        }
        assert {item["figure"]["lineage"]["doc_kind"] for item in restored} == {
            DocKind.RENT_ROLL.value
        }
    finally:
        database.close()


def test_workspace_delete_cascades_through_truth_asset_graph(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn).apply()
    workspace_id = str(uuid4())
    blob = b"Line Item,Amount\nNOI,1\n"
    digest = hashlib.sha256(blob).digest()
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) "
            "VALUES (%s,%s,'Cascade Workspace','active')",
            (workspace_id, f"ws_cascade_{uuid4().hex}"),
        )
        connection.execute(
            "INSERT INTO medawarcre.truth_document_blobs("
            "workspace_id,document_id,content) VALUES (%s,%s,%s)",
            (workspace_id, digest, blob),
        )
        connection.execute(
            "INSERT INTO medawarcre.truth_documents("
            "workspace_id,deal_ref,document_id,doc_kind,source_channel,origin,"
            "format,n_pages,parse_status,redactions,ingested_at) VALUES ("
            "%s,'crexi:cascade',%s,'t12_operating_statement','scraped',"
            "'https://documents.example/t12.csv','csv',NULL,'parsed',0,"
            "statement_timestamp())",
            (workspace_id, digest),
        )
        connection.execute(
            "INSERT INTO medawarcre.truth_claims("
            "workspace_id,deal_ref,document_id,field,subject,value_kind,"
            "value_number,value_text,unit,confidence,lineage_doc_kind,"
            "lineage_source_channel,lineage_raw_text,extraction_method,"
            "lineage_origin) VALUES ("
            "%s,'crexi:cascade',%s,'noi','','number',1.0,NULL,'usd',0.8,"
            "'t12_operating_statement','scraped','NOI','csv_cell',"
            "'https://documents.example/t12.csv')",
            (workspace_id, digest),
        )
        connection.execute(
            "DELETE FROM medawarcre.workspaces WHERE id=%s",
            (workspace_id,),
        )
        counts = connection.execute(
            "SELECT "
            "(SELECT count(*) FROM medawarcre.truth_document_blobs),"
            "(SELECT count(*) FROM medawarcre.truth_documents),"
            "(SELECT count(*) FROM medawarcre.truth_claims)"
        ).fetchone()
    assert counts == (0, 0, 0)


@pytest.mark.asyncio
async def test_truth_assets_are_isolated_by_workspace_and_blob_dedupe_is_not_global(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    first = _admission(workspace_public_id="ws_truth_a")
    second = _admission(workspace_public_id="ws_truth_b")
    _seed_admission(admin_dsn, first)
    _seed_admission(admin_dsn, second)
    database = _database(app_dsn)
    first_repository = PostgresTruthAssetRepository(database, first)
    second_repository = PostgresTruthAssetRepository(database, second)
    record, blob, claims = _asset()
    other_deal = record.model_copy(update={"deal_id": "crexi:truth-2"})
    try:
        with use_context(_context(first)), use_hosted_request_repositories(
            _repositories(first, first_repository)
        ):
            await first_repository.save_document(record, blob, claims, ext="csv")
            await first_repository.save_document(other_deal, blob, claims, ext="csv")

        with use_context(_context(second)), use_hosted_request_repositories(
            _repositories(second, second_repository)
        ):
            assert await second_repository.list_documents(record.deal_id) == []
            assert await second_repository.get_claims(record.deal_id) == []
            await second_repository.save_document(record, blob, claims, ext="csv")
            assert len(await second_repository.list_documents(record.deal_id)) == 1

        with psycopg.connect(admin_dsn) as connection:
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.truth_document_blobs"
            ).fetchone() == (2,)
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.truth_documents"
            ).fetchone() == (3,)
    finally:
        database.close()


@pytest.mark.asyncio
async def test_truth_assets_are_workspace_shared_across_exact_actor_sessions(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    creator = _admission(workspace_public_id="ws_truth_shared")
    reader = _admission(
        workspace_public_id=creator.workspace_public_id,
        tool_name="list_deal_documents",
    )
    workspace_id = _seed_admission(admin_dsn, creator)
    _seed_workspace_member_admission(admin_dsn, reader, workspace_id)
    database = _database(app_dsn)
    creator_repository = PostgresTruthAssetRepository(database, creator)
    reader_repository = PostgresTruthAssetRepository(database, reader)
    record, blob, claims = _asset()
    try:
        with use_context(_context(creator)), use_hosted_request_repositories(
            _repositories(creator, creator_repository)
        ):
            await creator_repository.save_document(record, blob, claims, ext="csv")

        with use_context(_context(reader)), use_hosted_request_repositories(
            _repositories(reader, reader_repository)
        ):
            assert len(await reader_repository.list_documents(record.deal_id)) == 1
            assert len(await reader_repository.get_claims(record.deal_id)) == len(claims)
    finally:
        database.close()


@pytest.mark.asyncio
async def test_truth_repository_requires_exact_live_request_scope(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_admission(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    record, blob, claims = _asset()
    try:
        with pytest.raises(TruthAssetUnavailable, match="truth-asset persistence unavailable"):
            await repository.save_document(record, blob, claims, ext="csv")

        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(replace(admission), repository)
        ):
            with pytest.raises(TruthAssetUnavailable):
                await repository.list_documents(record.deal_id)

        repositories = _repositories(admission, repository)
        with use_context(_context(admission)), use_hosted_request_repositories(
            repositories
        ):
            assert await repository.list_documents(record.deal_id) == []

        with use_context(_context(admission)):
            with pytest.raises(TruthAssetUnavailable):
                await repository.get_claims(record.deal_id)
    finally:
        database.close()


@pytest.mark.asyncio
async def test_detached_task_cannot_retain_truth_asset_repository_lease(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission(tool_name="list_deal_documents")
    _seed_admission(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    started = asyncio.Event()
    inspect = asyncio.Event()

    async def detached_read() -> list[dict]:
        started.set()
        await inspect.wait()
        return await repository.list_documents("crexi:truth-1")

    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            task = asyncio.create_task(detached_read())
            await started.wait()
        inspect.set()
        with pytest.raises(TruthAssetUnavailable):
            await task
    finally:
        database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "list", "claims"])
async def test_inflight_truth_operation_cannot_return_after_lease_revocation(
    postgres_database: tuple[str, str, str],
    operation: str,
) -> None:
    _, _, app_dsn = postgres_database
    admission = _admission()
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    record, blob, claims = _asset()
    worker_authorized = threading.Event()
    release_worker = threading.Event()

    def blocking_operation(*_args):
        repository._require_active_scope()
        worker_authorized.set()
        assert release_worker.wait(timeout=5)
        return record if operation == "save" else []

    async def invoke():
        if operation == "save":
            return await repository.save_document(record, blob, claims, ext="csv")
        if operation == "list":
            return await repository.list_documents(record.deal_id)
        return await repository.get_claims(record.deal_id)

    implementation = {
        "save": "_save_document",
        "list": "_list_documents",
        "claims": "_get_claims",
    }[operation]
    try:
        with (
            patch.object(repository, implementation, side_effect=blocking_operation),
            use_context(_context(admission)),
            use_hosted_request_repositories(_repositories(admission, repository)),
        ):
            task = asyncio.create_task(invoke())
            assert await asyncio.to_thread(worker_authorized.wait, 2)
        release_worker.set()
        with pytest.raises(
            TruthAssetUnavailable,
            match="^truth-asset persistence unavailable$",
        ):
            await task
    finally:
        release_worker.set()
        database.close()


@pytest.mark.asyncio
async def test_detached_task_cannot_fall_back_to_local_truth_store(tmp_path) -> None:
    admission = _admission(tool_name="list_deal_documents")
    repository = object()
    started = asyncio.Event()
    inspect = asyncio.Event()
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "forbidden.db")

    async def detached_factory():
        started.set()
        await inspect.wait()
        return get_truth_store(config)

    with use_context(_context(admission)), use_hosted_request_repositories(
        _repositories(admission, repository)
    ):
        task = asyncio.create_task(detached_factory())
        await started.wait()
    inspect.set()

    with pytest.raises(AdmittedRequestUnavailable):
        await task
    assert not (tmp_path / "forbidden.db").exists()


@pytest.mark.asyncio
async def test_truth_repository_thread_finishes_before_cancellation_escapes(
    postgres_database: tuple[str, str, str],
) -> None:
    _, _, app_dsn = postgres_database
    admission = _admission()
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    record, blob, claims = _asset()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_save(*_args):
        started.set()
        assert release.wait(timeout=5)
        finished.set()
        return record

    try:
        with (
            patch.object(repository, "_save_document", side_effect=blocking_save),
            use_context(_context(admission)),
            use_hosted_request_repositories(_repositories(admission, repository)),
        ):
            task = asyncio.create_task(
                repository.save_document(record, blob, claims, ext="csv")
            )
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0.02)
            assert task.done() is False
            assert finished.is_set() is False
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert finished.is_set() is True
    finally:
        release.set()
        database.close()


@pytest.mark.asyncio
async def test_digest_and_lineage_mismatch_fail_before_any_mutation(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_admission(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    repositories = _repositories(admission, repository)
    record, blob, claims = _asset()
    wrong_record = record.model_copy(update={"document_id": "0" * 64})
    wrong_claim = claims[0].model_copy(
        update={
            "figure": claims[0].figure.model_copy(
                update={
                    "lineage": claims[0].figure.lineage.model_copy(
                        update={"document_id": "f" * 64}
                    )
                }
            )
        }
    )
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            repositories
        ):
            with pytest.raises(TruthAssetUnavailable):
                await repository.save_document(wrong_record, blob, claims, ext="csv")
            with pytest.raises(TruthAssetUnavailable):
                await repository.save_document(record, blob, [wrong_claim], ext="csv")

        with psycopg.connect(admin_dsn) as connection:
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.truth_document_blobs"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.truth_documents"
            ).fetchone() == (0,)
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            workspace_id = connection.execute(
                "SELECT id FROM medawarcre.workspaces WHERE public_id=%s",
                (admission.workspace_public_id,),
            ).fetchone()[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "INSERT INTO medawarcre.truth_document_blobs("
                    "workspace_id,document_id,content) VALUES ("
                    "%s,decode(repeat('00',32),'hex'),%s)",
                    (workspace_id, blob),
                )
    finally:
        database.close()


@pytest.mark.asyncio
async def test_database_rejects_non_finite_truth_numbers_and_boxes(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_admission(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    record, blob, claims = _asset()
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            await repository.save_document(record, blob, claims, ext="csv")

        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "UPDATE medawarcre.truth_claims "
                    "SET value_number='NaN'::double precision "
                    "WHERE value_kind='number'"
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "UPDATE medawarcre.truth_claims SET lineage_bbox="
                    "ARRAY[1.0,2.0,'Infinity'::double precision,4.0] "
                    "WHERE lineage_bbox IS NOT NULL"
                )
    finally:
        database.close()


@pytest.mark.asyncio
async def test_non_finite_stored_claim_fails_with_fixed_unavailable_error(
    postgres_database: tuple[str, str, str],
) -> None:
    _, _, app_dsn = postgres_database
    admission = _admission(tool_name="get_deal_claims")
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    record, _, _ = _asset()
    row = (
        bytes.fromhex(record.document_id),
        "noi",
        "",
        "number",
        float("nan"),
        None,
        "usd",
        0.8,
        DocKind.T12.value,
        "scraped",
        1,
        None,
        [1.0, 2.0, 3.0, 4.0],
        "NOI",
        ExtractionMethod.PDF_TABLE.value,
        record.origin,
        [],
    )
    connection = SimpleNamespace(
        execute=lambda *_args, **_kwargs: SimpleNamespace(fetchall=lambda: [row])
    )

    @contextmanager
    def corrupted_connection(_admission):
        yield connection

    try:
        with (
            patch.object(
                database,
                "admitted_connection",
                side_effect=corrupted_connection,
            ),
            use_context(_context(admission)),
            use_hosted_request_repositories(_repositories(admission, repository)),
        ):
            with pytest.raises(
                TruthAssetUnavailable,
                match="truth-asset persistence unavailable",
            ):
                await repository.get_claims(record.deal_id)
    finally:
        database.close()


@pytest.mark.asyncio
async def test_claim_failure_rolls_back_blob_document_and_claims(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_admission(admin_dsn, admission)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "CREATE FUNCTION medawarcre.reject_test_claim() RETURNS trigger "
            "LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION 'forced'; END$$"
        )
        connection.execute(
            "CREATE TRIGGER reject_test_claim BEFORE INSERT ON medawarcre.truth_claims "
            "FOR EACH ROW EXECUTE FUNCTION medawarcre.reject_test_claim()"
        )
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    record, blob, claims = _asset()
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            with pytest.raises(
                TruthAssetUnavailable,
                match="truth-asset persistence unavailable",
            ):
                await repository.save_document(record, blob, claims, ext="csv")

        with psycopg.connect(admin_dsn) as connection:
            assert connection.execute(
                "SELECT "
                "(SELECT count(*) FROM medawarcre.truth_document_blobs),"
                "(SELECT count(*) FROM medawarcre.truth_documents),"
                "(SELECT count(*) FROM medawarcre.truth_claims)"
            ).fetchone() == (0, 0, 0)
    finally:
        database.close()


@pytest.mark.asyncio
async def test_database_failure_is_fixed_error_not_empty_success_or_local_fallback(
    postgres_database: tuple[str, str, str],
    tmp_path,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_admission(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    repositories = _repositories(admission, repository)
    database.close()

    with use_context(_context(admission)), use_hosted_request_repositories(
        repositories
    ):
        assert get_truth_store() is repository
        with pytest.raises(TruthAssetUnavailable) as listed:
            await repository.list_documents("crexi:truth-1")
        with pytest.raises(TruthAssetUnavailable) as claims:
            await repository.get_claims("crexi:truth-1")

    assert str(listed.value) == "truth-asset persistence unavailable"
    assert str(claims.value) == "truth-asset persistence unavailable"
    assert not list(tmp_path.iterdir())


def test_truth_asset_acl_denies_blob_reads_and_other_roles_mutation(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn).apply()
    with psycopg.connect(admin_dsn) as connection:
        app_blob = connection.execute(
            "SELECT has_table_privilege('medawarcre_app',"
            "'medawarcre.truth_document_blobs','SELECT'),"
            "has_table_privilege('medawarcre_app',"
            "'medawarcre.truth_document_blobs','INSERT'),"
            "has_table_privilege('medawarcre_app',"
            "'medawarcre.truth_document_blobs','UPDATE'),"
            "has_table_privilege('medawarcre_app',"
            "'medawarcre.truth_document_blobs','DELETE')"
        ).fetchone()
        app_documents = connection.execute(
            "SELECT has_table_privilege('medawarcre_app',"
            "'medawarcre.truth_documents','SELECT,INSERT,UPDATE'),"
            "has_table_privilege('medawarcre_app',"
            "'medawarcre.truth_claims','SELECT,INSERT,UPDATE,DELETE')"
        ).fetchone()
        prohibited = connection.execute(
            "SELECT has_table_privilege('medawarcre_provider_ingress',"
            "'medawarcre.truth_documents','INSERT'),"
            "has_table_privilege('medawarcre_worker',"
            "'medawarcre.truth_claims','SELECT')"
        ).fetchone()
    assert app_blob == (False, True, False, False)
    assert app_documents == (True, True)
    assert prohibited == (False, False)


@pytest.mark.asyncio
async def test_hosted_url_pipeline_attests_before_fetch_and_persists_to_postgres(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_admission(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    events: list[str] = []
    document_repository = _DocumentRepository(events)
    repositories = _repositories(
        admission,
        repository,
        document=document_repository,
        deal=_DealRepository(),
    )

    async def download(url: str, attestation_id: str | None) -> bytes:
        events.append("fetch")
        return b"Line Item,Amount\nNet Operating Income,180000\n"

    try:
        with (
            patch(
                "cre_mcp.tools.truth_tools._to_thread_fetch",
                new=AsyncMock(side_effect=download),
            ),
            use_context(_context(admission)),
            use_hosted_request_repositories(repositories),
            use_hosted_document_attestation_repository(document_repository),
        ):
            result = await ingest_document(
                "crexi:truth-hosted",
                url="https://documents.example/t12.csv?signature=secret",
                rights_attestation_id="srcatt_" + "1" * 32,
            )

        assert events == ["attest", "fetch"]
        assert result["status"] == "ingested"
        assert result["source_channel"] == "scraped"
        assert result["format"] == "csv"
        assert "signature" not in str(result)
        with psycopg.connect(admin_dsn) as connection:
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.truth_document_blobs"
            ).fetchone() == (1,)
    finally:
        database.close()


@pytest.mark.asyncio
async def test_hosted_oversized_url_failure_persists_no_truth_asset(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_admission(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresTruthAssetRepository(database, admission)
    document_repository = _DocumentRepository()
    repositories = _repositories(
        admission,
        repository,
        document=document_repository,
        deal=_DealRepository(),
    )
    try:
        with (
            patch(
                "cre_mcp.tools.truth_tools._to_thread_fetch",
                new=AsyncMock(
                    side_effect=RuntimeError("external document retrieval failed")
                ),
            ),
            use_context(_context(admission)),
            use_hosted_request_repositories(repositories),
            use_hosted_document_attestation_repository(document_repository),
        ):
            result = await ingest_document(
                "crexi:truth-oversized",
                url="https://documents.example/oversized.pdf",
                rights_attestation_id="srcatt_" + "2" * 32,
            )

        assert result == {"error": "external document ingestion failed"}
        with psycopg.connect(admin_dsn) as connection:
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.truth_document_blobs"
            ).fetchone() == (0,)
    finally:
        database.close()
