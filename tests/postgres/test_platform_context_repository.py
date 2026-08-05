from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.access.context import TenantContext, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.platform.repository import PlatformRepository, get_platform_repository
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.domains import (
    AdmittedRequestUnavailable,
    HostedRequestRepositories,
    use_hosted_request_repositories,
)
from cre_mcp.postgres.migrations import MigrationRunner
from cre_mcp.postgres.platform_context import (
    PlatformContextUnavailable,
    PlatformContextSnapshot,
    PostgresPlatformRepository,
)
from cre_mcp.postgres.pool import PostgresDatabase


def _admission(
    *,
    workspace_public_id: str = "ws_platform_a",
    actor_user_id: str | None = None,
    session_id: str | None = None,
) -> AdmissionOutcome:
    return AdmissionOutcome(
        invocation_id=str(uuid4()),
        request_correlation_id=str(uuid4()),
        workspace_public_id=workspace_public_id,
        actor_user_id=actor_user_id or str(uuid4()),
        session_id=session_id or str(uuid4()),
        tool_name="get_platform_context",
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
    platform: object,
) -> HostedRequestRepositories:
    marker = object()
    return HostedRequestRepositories(
        admission=admission,
        platform=platform,
        provider=marker,
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


def _seed_platform_context(
    admin_dsn: str,
    admission: AdmissionOutcome,
    *,
    include_plan: bool = True,
    include_account: bool = True,
    membership_state: str = "active",
) -> dict[str, object]:
    workspace_id = str(uuid4())
    membership_id = str(uuid4())
    plan_id = str(uuid4()) if include_plan else None
    territory_ids = (str(uuid4()), str(uuid4()))
    created_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    updated_at = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
    email = f"platform-{uuid4().hex}@example.test"
    slug = (
        "platform-workspace"
        if admission.workspace_public_id == "ws_platform_a"
        else f"{admission.workspace_public_id}-slug"
    )
    with psycopg.connect(admin_dsn) as connection:
        if plan_id is not None:
            connection.execute(
                "INSERT INTO medawarcre.plans("
                "id,plan_key,name,monthly_price_usd,seat_limit,daily_quotas,"
                "active,created_at,updated_at) VALUES ("
                "%s,'operator','Operator',149.50,7,%s::jsonb,true,%s,%s)",
                (plan_id, '{"search": 200, "ingest_document": 15}', created_at, updated_at),
            )
        connection.execute(
            "INSERT INTO medawarcre.users("
            "id,email,name,state,created_at,updated_at) "
            "VALUES (%s,%s,'Platform Actor','active',%s,%s)",
            (admission.actor_user_id, email, created_at, updated_at),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces("
            "id,public_id,name,slug,plan_id,state,created_at,updated_at) "
            "VALUES (%s,%s,'Platform Workspace',%s,%s,"
            "'active',%s,%s)",
            (
                workspace_id,
                admission.workspace_public_id,
                slug,
                plan_id,
                created_at,
                updated_at,
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships("
            "id,workspace_id,user_id,role,state,created_at,updated_at) "
            "VALUES (%s,%s,%s,'owner',%s,%s,%s)",
            (
                membership_id,
                workspace_id,
                admission.actor_user_id,
                membership_state,
                created_at,
                updated_at,
            ),
        )
        if include_account:
            connection.execute(
                "INSERT INTO medawarcre.workspace_accounts("
                "workspace_id,state,reason_code,created_at,updated_at) "
                "VALUES (%s,'active','provisioned',%s,%s)",
                (workspace_id, created_at, updated_at),
            )
        connection.execute(
            "INSERT INTO medawarcre.territories("
            "id,workspace_id,name,state_code,market,asset_type,created_at,updated_at) "
            "VALUES (%s,%s,'Seattle','WA','Puget Sound','industrial',%s,%s),"
            "(%s,%s,'Austin','TX','Central Texas','retail',%s,%s)",
            (
                territory_ids[0],
                workspace_id,
                created_at,
                updated_at,
                territory_ids[1],
                workspace_id,
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
            "decode(repeat('71',32),'hex'),decode(repeat('72',32),'hex'))",
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
        "membership_id": membership_id,
        "plan_id": plan_id,
        "territory_ids": territory_ids,
        "email": email,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def test_platform_repository_factory_uses_exact_hosted_port_and_blocks_sqlite(
    tmp_path,
) -> None:
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "forbidden.db")
    admission = _admission()
    hosted = object()

    assert isinstance(get_platform_repository(config), PlatformRepository)
    with use_context(_context(admission)), use_hosted_request_repositories(
        _repositories(admission, hosted)
    ):
        assert get_platform_repository(config) is hosted
        with pytest.raises(AdmittedRequestUnavailable):
            PlatformRepository(config)

    with use_context(_context(admission)):
        with pytest.raises(AdmittedRequestUnavailable):
            get_platform_repository(config)
        with pytest.raises(AdmittedRequestUnavailable):
            PlatformRepository(config)
    assert not config.cache_db_path.exists()


@pytest.mark.asyncio
async def test_platform_context_snapshot_is_complete_native_and_deterministic(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    seeded = _seed_platform_context(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresPlatformRepository(database, admission)
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            snapshot = await repository.get_snapshot()

        assert isinstance(snapshot, PlatformContextSnapshot)
        assert snapshot.actor.id == admission.actor_user_id
        assert snapshot.actor.email == seeded["email"]
        assert snapshot.actor.name == "Platform Actor"
        assert snapshot.actor.state == "active"
        assert snapshot.workspace.id == seeded["workspace_id"]
        assert snapshot.workspace.public_id == admission.workspace_public_id
        assert snapshot.workspace.slug == "platform-workspace"
        assert snapshot.workspace.state == "active"
        assert snapshot.membership.id == seeded["membership_id"]
        assert snapshot.membership.role == "owner"
        assert snapshot.membership.state == "active"
        assert snapshot.account.state == "active"
        assert snapshot.account.reason_code == "provisioned"
        assert snapshot.plan is not None
        assert snapshot.plan.id == seeded["plan_id"]
        assert snapshot.plan.key == "operator"
        assert snapshot.plan.monthly_price_usd == "149.50"
        assert snapshot.plan.seat_limit == 7
        assert snapshot.plan.daily_quotas == {
            "ingest_document": 15,
            "search": 200,
        }
        assert snapshot.plan.active is True
        assert [territory.name for territory in snapshot.territories] == [
            "Austin",
            "Seattle",
        ]
        assert [territory.id for territory in snapshot.territories] == [
            seeded["territory_ids"][1],
            seeded["territory_ids"][0],
        ]
        assert snapshot.actor.created_at == "2026-01-02T03:04:05+00:00"
        assert snapshot.workspace.updated_at == "2026-02-03T04:05:06+00:00"
        assert snapshot.territories[0].state == "TX"
    finally:
        database.close()


@pytest.mark.asyncio
async def test_platform_context_snapshot_cannot_mix_concurrent_commits(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    seeded = _seed_platform_context(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresPlatformRepository(database, admission)
    real_admitted_connection = database.admitted_connection
    update_committed = False

    def commit_update() -> None:
        nonlocal update_committed
        if update_committed:
            return
        update_committed = True
        with psycopg.connect(admin_dsn) as connection:
            connection.execute(
                "UPDATE medawarcre.workspaces "
                "SET name='Updated Platform Workspace',updated_at=now() "
                "WHERE id=%s",
                (seeded["workspace_id"],),
            )
            connection.execute(
                "INSERT INTO medawarcre.territories("
                "id,workspace_id,name,state_code,market,asset_type) "
                "VALUES (%s,%s,'Boston','MA','Greater Boston','office')",
                (str(uuid4()), seeded["workspace_id"]),
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

        observed = (
            snapshot.workspace.name,
            tuple(territory.name for territory in snapshot.territories),
        )
        assert observed in {
            ("Platform Workspace", ("Austin", "Seattle")),
            (
                "Updated Platform Workspace",
                ("Austin", "Boston", "Seattle"),
            ),
        }
    finally:
        database.close()


@pytest.mark.asyncio
async def test_platform_context_allows_an_absent_plan(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_platform_context(admin_dsn, admission, include_plan=False)
    database = _database(app_dsn)
    repository = PostgresPlatformRepository(database, admission)
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            snapshot = await repository.get_snapshot()
        assert snapshot.plan is None
    finally:
        database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("include_account", "membership_state"),
    [(False, "active"), (True, "suspended")],
)
async def test_missing_required_or_inactive_platform_scope_is_fixed_failure(
    postgres_database: tuple[str, str, str],
    include_account: bool,
    membership_state: str,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_platform_context(
        admin_dsn,
        admission,
        include_account=include_account,
        membership_state=membership_state,
    )
    database = _database(app_dsn)
    repository = PostgresPlatformRepository(database, admission)
    try:
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            with pytest.raises(
                PlatformContextUnavailable,
                match="^platform-context persistence unavailable$",
            ):
                await repository.get_snapshot()
    finally:
        database.close()


@pytest.mark.asyncio
async def test_platform_context_is_isolated_by_current_actor_and_workspace_rls(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    first = _admission(workspace_public_id="ws_platform_first")
    second = _admission(workspace_public_id="ws_platform_second")
    first_seed = _seed_platform_context(admin_dsn, first)
    _seed_platform_context(admin_dsn, second, include_plan=False)
    database = _database(app_dsn)
    repository = PostgresPlatformRepository(database, first)
    try:
        with use_context(_context(first)), use_hosted_request_repositories(
            _repositories(first, repository)
        ):
            snapshot = await repository.get_snapshot()
            with database.admitted_connection(first) as connection:
                counts = connection.execute(
                    "SELECT "
                    "(SELECT count(*) FROM medawarcre.users),"
                    "(SELECT count(*) FROM medawarcre.workspaces),"
                    "(SELECT count(*) FROM medawarcre.memberships),"
                    "(SELECT count(*) FROM medawarcre.workspace_accounts),"
                    "(SELECT count(*) FROM medawarcre.territories)"
                ).fetchone()

        assert snapshot.workspace.id == first_seed["workspace_id"]
        assert snapshot.actor.id == first.actor_user_id
        assert counts == (1, 1, 1, 1, 2)
    finally:
        database.close()


@pytest.mark.asyncio
async def test_platform_repository_requires_exact_live_request_scope(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_platform_context(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresPlatformRepository(database, admission)
    try:
        with pytest.raises(PlatformContextUnavailable):
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
                with pytest.raises(PlatformContextUnavailable):
                    await repository.get_snapshot()

        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(replace(admission), repository)
        ):
            with pytest.raises(PlatformContextUnavailable):
                await repository.get_snapshot()

        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, object())
        ):
            with pytest.raises(PlatformContextUnavailable):
                await repository.get_snapshot()

        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            assert (await repository.get_snapshot()).actor.id == admission.actor_user_id
    finally:
        database.close()


@pytest.mark.asyncio
async def test_detached_task_cannot_retain_platform_repository_lease(
    postgres_database: tuple[str, str, str],
) -> None:
    _, _, app_dsn = postgres_database
    admission = _admission()
    database = _database(app_dsn)
    repository = PostgresPlatformRepository(database, admission)
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
        with pytest.raises(PlatformContextUnavailable):
            await task
    finally:
        database.close()


@pytest.mark.asyncio
async def test_detached_task_cannot_fall_back_to_local_platform_repository(
    tmp_path,
) -> None:
    admission = _admission()
    started = asyncio.Event()
    inspect = asyncio.Event()
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "forbidden.db")

    async def detached_factory():
        started.set()
        await inspect.wait()
        return get_platform_repository(config)

    with use_context(_context(admission)), use_hosted_request_repositories(
        _repositories(admission, object())
    ):
        task = asyncio.create_task(detached_factory())
        await started.wait()
    inspect.set()

    with pytest.raises(AdmittedRequestUnavailable):
        await task
    assert not config.cache_db_path.exists()


@pytest.mark.asyncio
async def test_platform_repository_thread_finishes_before_cancellation_escapes(
    postgres_database: tuple[str, str, str],
) -> None:
    _, _, app_dsn = postgres_database
    admission = _admission()
    database = _database(app_dsn)
    repository = PostgresPlatformRepository(database, admission)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    expected = object()

    def blocking_read():
        started.set()
        assert release.wait(timeout=5)
        finished.set()
        return expected

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
@pytest.mark.parametrize("corruption", ["quota", "territory_state"])
async def test_malformed_platform_rows_raise_only_the_fixed_error(
    postgres_database: tuple[str, str, str],
    corruption: str,
) -> None:
    _, _, app_dsn = postgres_database
    admission = _admission()
    database = _database(app_dsn)
    repository = PostgresPlatformRepository(database, admission)
    timestamp = datetime.now(UTC)
    workspace_id = str(uuid4())
    identity = {
        "user_id": admission.actor_user_id,
        "user_email": "actor@example.test",
        "user_name": "Actor",
        "user_state": "active",
        "user_created_at": timestamp,
        "user_updated_at": timestamp,
        "workspace_id": workspace_id,
        "workspace_public_id": admission.workspace_public_id,
        "workspace_name": "Workspace",
        "workspace_slug": None,
        "workspace_state": "active",
        "workspace_created_at": timestamp,
        "workspace_updated_at": timestamp,
        "membership_id": str(uuid4()),
        "membership_role": "owner",
        "membership_state": "active",
        "membership_created_at": timestamp,
        "membership_updated_at": timestamp,
        "account_state": "active",
        "account_reason_code": None,
        "account_created_at": timestamp,
        "account_updated_at": timestamp,
        "plan_id": str(uuid4()),
        "plan_key": "operator",
        "plan_name": "Operator",
        "plan_monthly_price_usd": Decimal("10.00"),
        "plan_seat_limit": 2,
        "plan_daily_quotas": {"search": 1},
        "plan_active": True,
        "plan_created_at": timestamp,
        "plan_updated_at": timestamp,
        "territory_id": None,
        "territory_workspace_id": None,
        "territory_name": None,
        "territory_state_code": None,
        "territory_market": None,
        "territory_asset_type": None,
        "territory_created_at": None,
        "territory_updated_at": None,
    }
    if corruption == "quota":
        identity["plan_daily_quotas"] = {"Not Canonical": 1}
    else:
        identity.update(
            {
                "territory_id": str(uuid4()),
                "territory_workspace_id": workspace_id,
                "territory_name": "Malformed State",
                "territory_state_code": "ÅB",
                "territory_created_at": timestamp,
                "territory_updated_at": timestamp,
            }
        )
    executions = [SimpleNamespace(fetchall=lambda: [identity])]

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, *_args, **_kwargs):
            return executions.pop(0)

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
            with pytest.raises(PlatformContextUnavailable) as raised:
                await repository.get_snapshot()
        assert str(raised.value) == "platform-context persistence unavailable"
    finally:
        database.close()


@pytest.mark.asyncio
async def test_database_failure_is_fixed_error_without_local_fallback(
    postgres_database: tuple[str, str, str],
    tmp_path,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_platform_context(admin_dsn, admission)
    database = _database(app_dsn)
    repository = PostgresPlatformRepository(database, admission)
    database.close()

    with use_context(_context(admission)), use_hosted_request_repositories(
        _repositories(admission, repository)
    ):
        assert get_platform_repository() is repository
        with pytest.raises(PlatformContextUnavailable) as raised:
            await repository.get_snapshot()

    assert str(raised.value) == "platform-context persistence unavailable"
    assert not list(tmp_path.iterdir())


def test_platform_context_acl_is_read_only_and_backup_readable(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn).apply()
    tables = (
        "users",
        "plans",
        "workspaces",
        "memberships",
        "territories",
        "workspace_accounts",
    )
    with psycopg.connect(admin_dsn) as connection:
        for table in tables:
            qualified = f"medawarcre.{table}"
            row = connection.execute(
                "SELECT has_table_privilege('medawarcre_app',%s,'SELECT'),"
                "has_table_privilege('medawarcre_app',%s,'INSERT'),"
                "has_table_privilege('medawarcre_app',%s,'UPDATE'),"
                "has_table_privilege('medawarcre_app',%s,'DELETE'),"
                "has_table_privilege('medawarcre_backup',%s,'SELECT')",
                (qualified, qualified, qualified, qualified, qualified),
            ).fetchone()
            assert row == (True, False, False, False, True)
