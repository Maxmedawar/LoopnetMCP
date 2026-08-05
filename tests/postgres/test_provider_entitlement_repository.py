from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.access.context import TenantContext, local_context, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.domains import (
    AdmittedRequestUnavailable,
    HostedRequestRepositories,
    use_hosted_request_repositories,
)
from cre_mcp.postgres.migrations import MigrationRunner
from cre_mcp.postgres.pool import PostgresDatabase
from cre_mcp.postgres.provider_entitlements import (
    PostgresProviderRepository,
    ProviderEntitlementSnapshot,
    ProviderPersistenceUnavailable,
)


def _admission(
    *,
    workspace_public_id: str = "ws_provider_a",
    actor_user_id: str | None = None,
    session_id: str | None = None,
) -> AdmissionOutcome:
    return AdmissionOutcome(
        invocation_id=str(uuid4()),
        request_correlation_id=str(uuid4()),
        workspace_public_id=workspace_public_id,
        actor_user_id=actor_user_id or str(uuid4()),
        session_id=session_id or str(uuid4()),
        tool_name="get_provider_entitlements",
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
    provider: object,
) -> HostedRequestRepositories:
    marker = object()
    return HostedRequestRepositories(
        admission=admission,
        platform=marker,
        provider=provider,
        search=marker,
        deal=marker,
        privacy=marker,
        job=marker,
        document=marker,
        truth_asset=marker,
    )


def _database(app_dsn: str) -> PostgresDatabase:
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=2, runtime_mode="app")
    )
    database.open()
    return database


def _hash() -> bytes:
    return uuid4().bytes + uuid4().bytes


def _seed_provider_context(
    admin_dsn: str,
    admission: AdmissionOutcome,
    *,
    include_entitlements: bool = True,
) -> dict[str, object]:
    workspace_id = str(uuid4())
    other_workspace_id = str(uuid4())
    other_actor_id = str(uuid4())
    other_workspace_actor_id = str(uuid4())
    subscription_id = str(uuid4())
    workspace_grant_id = str(uuid4())
    actor_grant_id = str(uuid4())
    other_actor_grant_id = str(uuid4())
    created_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    updated_at = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
    period_end = datetime(2026, 4, 1, tzinfo=UTC)
    lease_end = datetime(2026, 3, 1, tzinfo=UTC)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) VALUES "
            "(%s,%s,'Provider Actor','active'),"
            "(%s,%s,'Other Actor','active'),"
            "(%s,%s,'Other Workspace Actor','active')",
            (
                admission.actor_user_id,
                f"provider-{uuid4().hex}@example.test",
                other_actor_id,
                f"other-{uuid4().hex}@example.test",
                other_workspace_actor_id,
                f"other-workspace-{uuid4().hex}@example.test",
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) VALUES "
            "(%s,%s,'Provider Workspace','active'),"
            "(%s,%s,'Other Provider Workspace','active')",
            (
                workspace_id,
                admission.workspace_public_id,
                other_workspace_id,
                f"ws_other_{uuid4().hex}",
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships("
            "id,workspace_id,user_id,role,state) VALUES "
            "(%s,%s,%s,'owner','active'),"
            "(%s,%s,%s,'member','active'),"
            "(%s,%s,%s,'owner','active')",
            (
                str(uuid4()),
                workspace_id,
                admission.actor_user_id,
                str(uuid4()),
                workspace_id,
                other_actor_id,
                str(uuid4()),
                other_workspace_id,
                other_workspace_actor_id,
            ),
        )
        if include_entitlements:
            connection.execute(
                "INSERT INTO medawarcre.subscriptions("
                "id,workspace_id,provider,external_subscription_hash,"
                "external_customer_hash,status,plan_key,current_period_end,"
                "last_event_at,created_at,updated_at) VALUES "
                "(%s,%s,'stripe',%s,%s,'active','operator',%s,%s,%s,%s),"
                "(%s,%s,'skool',%s,NULL,'paused','scout',NULL,%s,%s,%s)",
                (
                    subscription_id,
                    workspace_id,
                    _hash(),
                    _hash(),
                    period_end,
                    updated_at,
                    created_at,
                    updated_at,
                    str(uuid4()),
                    other_workspace_id,
                    _hash(),
                    updated_at,
                    created_at,
                    updated_at,
                ),
            )
            connection.execute(
                "INSERT INTO medawarcre.access_grants("
                "id,workspace_id,subject_user_id,scope,source,external_ref_hash,"
                "profile,plan_key,status,starts_at,ends_at,created_at,updated_at) "
                "VALUES "
                "(%s,%s,NULL,'workspace','jv',%s,'jv_partner','jv',"
                "'active',%s,NULL,%s,%s),"
                "(%s,%s,%s,'subject','stripe',%s,'full_operator','operator',"
                "'expiring',%s,%s,%s,%s),"
                "(%s,%s,%s,'subject','skool',%s,'national_scout','scout',"
                "'active',%s,%s,%s,%s),"
                "(%s,%s,%s,'subject','promotion',%s,'local_scout','scout',"
                "'active',%s,NULL,%s,%s)",
                (
                    workspace_grant_id,
                    workspace_id,
                    _hash(),
                    created_at,
                    created_at,
                    updated_at,
                    actor_grant_id,
                    workspace_id,
                    admission.actor_user_id,
                    _hash(),
                    created_at,
                    lease_end,
                    created_at,
                    updated_at,
                    other_actor_grant_id,
                    workspace_id,
                    other_actor_id,
                    _hash(),
                    created_at,
                    lease_end,
                    created_at,
                    updated_at,
                    str(uuid4()),
                    other_workspace_id,
                    other_workspace_actor_id,
                    _hash(),
                    created_at,
                    created_at,
                    updated_at,
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
            "decode(repeat('81',32),'hex'),decode(repeat('82',32),'hex'))",
            (
                admission.invocation_id,
                workspace_id,
                admission.actor_user_id,
                admission.session_id,
                admission.request_correlation_id,
                admission.tool_name,
            ),
        )
    return {
        "workspace_id": workspace_id,
        "other_workspace_id": other_workspace_id,
        "other_actor_id": other_actor_id,
        "subscription_id": subscription_id,
        "workspace_grant_id": workspace_grant_id,
        "actor_grant_id": actor_grant_id,
        "other_actor_grant_id": other_actor_grant_id,
    }


def test_local_entitlement_store_is_blocked_in_hosted_context_and_kept_locally(
    tmp_path,
) -> None:
    admission = _admission()
    forbidden = tmp_path / "forbidden.db"
    with use_context(_context(admission)):
        with pytest.raises(AdmittedRequestUnavailable):
            EntitlementStore(forbidden)
    assert not forbidden.exists()

    local = tmp_path / "local.db"
    with use_context(local_context()):
        assert EntitlementStore(local).db_path == local
    assert local.exists()


@pytest.mark.asyncio
async def test_provider_snapshot_is_complete_native_safe_and_deterministic(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    seeded = _seed_provider_context(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresProviderRepository(database, admission)
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            snapshot = await repository.get_snapshot()

        assert isinstance(snapshot, ProviderEntitlementSnapshot)
        assert snapshot.workspace_id == seeded["workspace_id"]
        assert snapshot.actor_user_id == admission.actor_user_id
        assert len(snapshot.subscriptions) == 1
        subscription = snapshot.subscriptions[0]
        assert subscription.id == seeded["subscription_id"]
        assert subscription.provider == "stripe"
        assert subscription.status == "active"
        assert subscription.plan_key == "operator"
        assert subscription.current_period_end == "2026-04-01T00:00:00+00:00"
        assert subscription.last_event_at == "2026-02-03T04:05:06+00:00"

        assert [grant.id for grant in snapshot.grants] == [
            seeded["workspace_grant_id"],
            seeded["actor_grant_id"],
        ]
        workspace_grant, actor_grant = snapshot.grants
        assert workspace_grant.scope == "workspace"
        assert workspace_grant.source == "jv"
        assert workspace_grant.subject_user_id is None
        assert workspace_grant.profile == Profile.JV_PARTNER
        assert workspace_grant.ends_at is None
        assert actor_grant.scope == "subject"
        assert actor_grant.source == "stripe"
        assert actor_grant.subject_user_id == admission.actor_user_id
        assert actor_grant.profile == Profile.FULL_OPERATOR
        assert actor_grant.ends_at == "2026-03-01T00:00:00+00:00"

        serialized = asdict(snapshot)
        rendered = repr(serialized)
        for forbidden in (
            "external_subscription",
            "external_customer",
            "external_ref",
            "payload",
            "provider_event",
        ):
            assert forbidden not in rendered
    finally:
        database.close()


@pytest.mark.asyncio
async def test_provider_snapshot_allows_no_visible_entitlements(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    seeded = _seed_provider_context(
        admin_dsn,
        admission,
        include_entitlements=False,
    )
    database = _database(app_dsn)
    repository = PostgresProviderRepository(database, admission)
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            snapshot = await repository.get_snapshot()
        assert snapshot.workspace_id == seeded["workspace_id"]
        assert snapshot.actor_user_id == admission.actor_user_id
        assert snapshot.subscriptions == ()
        assert snapshot.grants == ()
    finally:
        database.close()


@pytest.mark.asyncio
async def test_provider_snapshot_isolated_by_actor_and_workspace_rls(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    seeded = _seed_provider_context(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresProviderRepository(database, admission)
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            snapshot = await repository.get_snapshot()
            with database.admitted_connection(admission) as connection:
                counts = connection.execute(
                    "SELECT "
                    "(SELECT count(*) FROM medawarcre.subscriptions),"
                    "(SELECT count(*) FROM medawarcre.access_grants)"
                ).fetchone()
        assert counts == (1, 2)
        assert seeded["other_actor_grant_id"] not in {
            grant.id for grant in snapshot.grants
        }
        assert {grant.workspace_id for grant in snapshot.grants} == {
            seeded["workspace_id"]
        }
    finally:
        database.close()


@pytest.mark.asyncio
async def test_provider_snapshot_cannot_mix_concurrent_commits(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    seeded = _seed_provider_context(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresProviderRepository(database, admission)
    real_admitted_connection = database.admitted_connection
    update_committed = False

    def commit_update() -> None:
        nonlocal update_committed
        if update_committed:
            return
        update_committed = True
        with psycopg.connect(admin_dsn) as connection:
            connection.execute(
                "UPDATE medawarcre.subscriptions "
                "SET status='paused',updated_at=now() WHERE id=%s",
                (seeded["subscription_id"],),
            )
            connection.execute(
                "UPDATE medawarcre.access_grants "
                "SET status='revoked',updated_at=now() WHERE id=%s",
                (seeded["actor_grant_id"],),
            )

    class _CommitAfterFetchCursor:
        def __init__(self, cursor) -> None:
            self._cursor = cursor

        def __enter__(self):
            self._cursor.__enter__()
            return self

        def __exit__(self, *args):
            return self._cursor.__exit__(*args)

        def execute(self, *args, **kwargs):
            self._cursor.execute(*args, **kwargs)
            return self

        def fetchall(self):
            rows = self._cursor.fetchall()
            commit_update()
            return rows

    class _CommitAfterFetchConnection:
        def __init__(self, connection) -> None:
            self._connection = connection

        def cursor(self, **kwargs):
            return _CommitAfterFetchCursor(self._connection.cursor(**kwargs))

    @contextmanager
    def racing_connection(current_admission):
        with real_admitted_connection(current_admission) as connection:
            yield _CommitAfterFetchConnection(connection)

    try:
        with (
            patch.object(
                database,
                "admitted_connection",
                side_effect=racing_connection,
            ),
            use_context(_context(admission)),
            use_hosted_request_repositories(_repositories(admission, repository)),
        ):
            snapshot = await repository.get_snapshot()

        actor_grant = next(
            grant for grant in snapshot.grants if grant.id == seeded["actor_grant_id"]
        )
        observed = (snapshot.subscriptions[0].status, actor_grant.status)
        assert observed in {("active", "expiring"), ("paused", "revoked")}
    finally:
        database.close()


@pytest.mark.asyncio
async def test_provider_repository_requires_exact_live_request_scope(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_provider_context(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresProviderRepository(database, admission)
    try:
        with pytest.raises(ProviderPersistenceUnavailable):
            await repository.get_snapshot()

        mismatches = (
            _context(admission).model_copy(update={"workspace_id": "wrong"}),
            _context(admission).model_copy(update={"actor_id": str(uuid4())}),
            _context(admission).model_copy(update={"session_id": str(uuid4())}),
            _context(admission).model_copy(update={"active": False}),
        )
        for context in mismatches:
            with use_context(context), use_hosted_request_repositories(
                _repositories(admission, repository)
            ):
                with pytest.raises(ProviderPersistenceUnavailable):
                    await repository.get_snapshot()

        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(replace(admission), repository)
        ):
            with pytest.raises(ProviderPersistenceUnavailable):
                await repository.get_snapshot()

        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, object())
        ):
            with pytest.raises(ProviderPersistenceUnavailable):
                await repository.get_snapshot()

        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            snapshot = await repository.get_snapshot()
            assert snapshot.actor_user_id == admission.actor_user_id
    finally:
        database.close()


@pytest.mark.asyncio
async def test_detached_task_cannot_retain_provider_repository_lease(
    postgres_database: tuple[str, str, str],
) -> None:
    _, _, app_dsn = postgres_database
    admission = _admission()
    database = _database(app_dsn)
    repository = PostgresProviderRepository(database, admission)
    started = asyncio.Event()
    inspect = asyncio.Event()

    async def detached_read():
        started.set()
        await inspect.wait()
        return await repository.get_snapshot()

    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            task = asyncio.create_task(detached_read())
            await started.wait()
        inspect.set()
        with pytest.raises(ProviderPersistenceUnavailable):
            await task
    finally:
        database.close()


@pytest.mark.asyncio
async def test_inflight_provider_read_cannot_return_after_lease_revocation(
    postgres_database: tuple[str, str, str],
) -> None:
    _, _, app_dsn = postgres_database
    admission = _admission()
    database = _database(app_dsn)
    repository = PostgresProviderRepository(database, admission)
    worker_authorized = threading.Event()
    release_worker = threading.Event()
    escaped = ProviderEntitlementSnapshot(
        workspace_id=str(uuid4()),
        actor_user_id=admission.actor_user_id,
        subscriptions=(),
        grants=(),
    )

    def blocking_read():
        repository._require_active_scope()
        worker_authorized.set()
        assert release_worker.wait(timeout=5)
        return escaped

    try:
        with (
            patch.object(repository, "_get_snapshot", side_effect=blocking_read),
            use_context(_context(admission)),
            use_hosted_request_repositories(_repositories(admission, repository)),
        ):
            task = asyncio.create_task(repository.get_snapshot())
            assert await asyncio.to_thread(worker_authorized.wait, 2)
        release_worker.set()
        with pytest.raises(
            ProviderPersistenceUnavailable,
            match="^provider persistence unavailable$",
        ):
            await task
    finally:
        release_worker.set()
        database.close()


@pytest.mark.asyncio
async def test_provider_repository_thread_finishes_before_cancellation_escapes(
    postgres_database: tuple[str, str, str],
) -> None:
    _, _, app_dsn = postgres_database
    admission = _admission()
    database = _database(app_dsn)
    repository = PostgresProviderRepository(database, admission)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_read():
        started.set()
        assert release.wait(timeout=5)
        finished.set()
        return object()

    try:
        with (
            patch.object(repository, "_get_snapshot", side_effect=blocking_read),
            use_context(_context(admission)),
            use_hosted_request_repositories(_repositories(admission, repository)),
        ):
            task = asyncio.create_task(repository.get_snapshot())
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
@pytest.mark.parametrize("corruption", ["provider", "scope", "timestamp", "duplicate"])
async def test_malformed_provider_rows_raise_only_the_fixed_error(
    postgres_database: tuple[str, str, str],
    corruption: str,
) -> None:
    _, _, app_dsn = postgres_database
    admission = _admission()
    database = _database(app_dsn)
    repository = PostgresProviderRepository(database, admission)
    timestamp = datetime.now(UTC)
    workspace_id = str(uuid4())
    scope = {
        "record_kind": "scope",
        "workspace_id": workspace_id,
        "actor_user_id": admission.actor_user_id,
        "id": None,
        "subject_user_id": None,
        "provider": None,
        "scope": None,
        "source": None,
        "profile": None,
        "plan_key": None,
        "status": None,
        "starts_at": None,
        "ends_at": None,
        "current_period_end": None,
        "last_event_at": None,
        "created_at": None,
        "updated_at": None,
    }
    subscription = {
        **scope,
        "record_kind": "subscription",
        "id": str(uuid4()),
        "provider": "stripe",
        "plan_key": "operator",
        "status": "active",
        "current_period_end": timestamp,
        "last_event_at": timestamp,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    rows = [scope, subscription]
    if corruption == "provider":
        subscription["provider"] = "unknown"
    elif corruption == "scope":
        subscription["workspace_id"] = str(uuid4())
    elif corruption == "timestamp":
        subscription["updated_at"] = "not-a-timestamp"
    else:
        rows.append(dict(subscription))

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args, **_kwargs):
            return SimpleNamespace(fetchall=lambda: rows)

    connection = SimpleNamespace(cursor=lambda **_kwargs: _Cursor())

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
            with pytest.raises(ProviderPersistenceUnavailable) as raised:
                await repository.get_snapshot()
        assert str(raised.value) == "provider persistence unavailable"
    finally:
        database.close()


@pytest.mark.asyncio
async def test_provider_database_failure_is_fixed_without_sqlite_fallback(
    postgres_database: tuple[str, str, str],
    tmp_path,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_provider_context(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresProviderRepository(database, admission)
    database.close()

    with use_context(_context(admission)), use_hosted_request_repositories(
        _repositories(admission, repository)
    ):
        with pytest.raises(ProviderPersistenceUnavailable) as raised:
            await repository.get_snapshot()
        with pytest.raises(AdmittedRequestUnavailable):
            EntitlementStore(tmp_path / "forbidden.db")

    assert str(raised.value) == "provider persistence unavailable"
    assert not list(tmp_path.iterdir())


def test_provider_projection_acl_is_exact_read_only_and_backup_readable(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn).apply()
    allowed = {
        "subscriptions": {
            "id",
            "workspace_id",
            "provider",
            "status",
            "plan_key",
            "current_period_end",
            "last_event_at",
            "created_at",
            "updated_at",
        },
        "access_grants": {
            "id",
            "workspace_id",
            "subject_user_id",
            "scope",
            "source",
            "profile",
            "plan_key",
            "status",
            "starts_at",
            "ends_at",
            "created_at",
            "updated_at",
        },
    }
    blocked = {
        "subscriptions": {"external_subscription_hash", "external_customer_hash"},
        "access_grants": {"external_ref_hash"},
    }
    with psycopg.connect(admin_dsn) as connection:
        for table, columns in allowed.items():
            qualified = f"medawarcre.{table}"
            assert connection.execute(
                "SELECT has_table_privilege('medawarcre_app',%s,'INSERT'),"
                "has_table_privilege('medawarcre_app',%s,'UPDATE'),"
                "has_table_privilege('medawarcre_app',%s,'DELETE'),"
                "has_table_privilege('medawarcre_backup',%s,'SELECT')",
                (qualified, qualified, qualified, qualified),
            ).fetchone() == (False, False, False, True)
            for column in columns:
                assert connection.execute(
                    "SELECT has_column_privilege("
                    "'medawarcre_app',%s,%s,'SELECT')",
                    (qualified, column),
                ).fetchone()[0] is True
            for column in blocked[table]:
                assert connection.execute(
                    "SELECT has_column_privilege("
                    "'medawarcre_app',%s,%s,'SELECT')",
                    (qualified, column),
                ).fetchone()[0] is False

        for table in ("external_accounts", "provider_events", "provider_event_attempts"):
            assert connection.execute(
                "SELECT has_table_privilege("
                "'medawarcre_app',%s,'SELECT')",
                (f"medawarcre.{table}",),
            ).fetchone()[0] is False
