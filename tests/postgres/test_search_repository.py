from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import psycopg
import pytest

from cre_mcp.access.context import TenantContext, local_context, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.domains import (
    AdmittedRequestUnavailable,
    HostedRequestRepositories,
    use_hosted_request_repositories,
)
from cre_mcp.postgres.migrations import MigrationRunner
from cre_mcp.postgres.pool import PostgresDatabase
from cre_mcp.postgres.searches import (
    PostgresSearchRepository,
    SearchPersistenceUnavailable,
)


def _admission(
    tool_name: str,
    *,
    workspace_public_id: str = "ws_search_a",
    actor_user_id: str | None = None,
    session_id: str | None = None,
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


def _repositories(
    admission: AdmissionOutcome,
    search: object,
) -> HostedRequestRepositories:
    marker = object()
    return HostedRequestRepositories(
        admission=admission,
        platform=marker,
        provider=marker,
        search=search,
        deal=marker,
        privacy=marker,
        job=marker,
        document=marker,
        truth_asset=marker,
    )


@contextmanager
def _active(repository: object, admission: AdmissionOutcome):
    with use_context(_context(admission)), use_hosted_request_repositories(
        _repositories(admission, repository)
    ):
        yield


def _database(app_dsn: str) -> PostgresDatabase:
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=4, runtime_mode="app")
    )
    database.open()
    return database


def _seed_workspace(
    admin_dsn: str,
    *,
    workspace_public_id: str,
    actor_ids: tuple[str, ...],
) -> str:
    workspace_id = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        for index, actor_id in enumerate(actor_ids):
            connection.execute(
                "INSERT INTO medawarcre.users(id,email,name,state) "
                "VALUES (%s,%s,%s,'active')",
                (
                    actor_id,
                    f"search-{uuid4().hex}@example.test",
                    f"Search Actor {index}",
                ),
            )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) "
            "VALUES (%s,%s,'Search Workspace','active')",
            (workspace_id, workspace_public_id),
        )
        for actor_id in actor_ids:
            connection.execute(
                "INSERT INTO medawarcre.memberships("
                "id,workspace_id,user_id,role,state) "
                "VALUES (%s,%s,%s,'member','active')",
                (str(uuid4()), workspace_id, actor_id),
            )
    return workspace_id


def _seed_admission(
    admin_dsn: str,
    workspace_id: str,
    admission: AdmissionOutcome,
) -> None:
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.access_decision_audit("
            "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
            "session_correlation_hash,request_correlation_id,tool_name,decision,"
            "reason_code,safe_reason,args_hash,admission_binding_hash) VALUES ("
            "%s,'admission',true,%s,%s,"
            "pg_catalog.sha256(pg_catalog.convert_to(%s,'UTF8')),%s,%s,'allowed',"
            "'authority_admitted','request admitted by live authority',"
            "decode(repeat('91',32),'hex'),decode(repeat('92',32),'hex'))",
            (
                admission.invocation_id,
                workspace_id,
                admission.actor_user_id,
                admission.session_id,
                admission.request_correlation_id,
                admission.tool_name,
            ),
        )


def _query(location: str = "Austin, TX") -> dict[str, object]:
    return {
        "location": location,
        "strategy": "nnn_retail",
        "property_type": "retail",
        "price_min": 1_000_000,
        "price_max": 4_000_000,
        "size_min": 5_000,
        "size_max": 30_000,
        "sources": ["crexi", "loopnet"],
    }


def _prepare(
    postgres_database: tuple[str, str, str],
    admissions: tuple[AdmissionOutcome, ...],
) -> tuple[str, str, PostgresDatabase]:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    workspace_id = _seed_workspace(
        admin_dsn,
        workspace_public_id=admissions[0].workspace_public_id,
        actor_ids=tuple(dict.fromkeys(item.actor_user_id for item in admissions)),
    )
    for admission in admissions:
        _seed_admission(admin_dsn, workspace_id, admission)
    return admin_dsn, workspace_id, _database(app_dsn)


def test_search_factory_uses_exact_hosted_port_and_keeps_local_sqlite(tmp_path) -> None:
    from cre_mcp.deals.store import DealStore, get_search_store

    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "local.db")
    with use_context(local_context()):
        local = get_search_store(config)
    assert isinstance(local, DealStore)

    admission = _admission("list_searches")
    hosted = object()
    forbidden = tmp_path / "forbidden.db"
    with _active(hosted, admission):
        assert get_search_store(config) is hosted
        with pytest.raises(AdmittedRequestUnavailable):
            DealStore(forbidden)
    assert not forbidden.exists()


@pytest.mark.asyncio
async def test_detached_search_factory_cannot_fall_back_to_local_sqlite(tmp_path) -> None:
    from cre_mcp.deals.store import get_search_store

    admission = _admission("list_searches")
    hosted = object()
    started = asyncio.Event()
    inspect = asyncio.Event()
    forbidden = tmp_path / "detached-forbidden.db"
    config = CreConfig(_env_file=None, cache_db_path=forbidden)

    async def detached_lookup():
        started.set()
        await inspect.wait()
        return get_search_store(config)

    with _active(hosted, admission):
        task = asyncio.create_task(detached_lookup())
        await started.wait()
    inspect.set()
    with pytest.raises(
        AdmittedRequestUnavailable,
        match="^search persistence unavailable$",
    ):
        await task
    assert not forbidden.exists()


@pytest.mark.asyncio
async def test_saved_search_round_trip_uses_opaque_uuid_and_atomic_seen_claims(
    postgres_database: tuple[str, str, str],
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_search", actor_user_id=actor_id)
    listing = _admission("list_searches", actor_user_id=actor_id)
    checking = _admission("check_alerts", actor_user_id=actor_id)
    admin_dsn, workspace_id, database = _prepare(
        postgres_database,
        (save, listing, checking),
    )
    save_repository = PostgresSearchRepository(database, save)
    list_repository = PostgresSearchRepository(database, listing)
    check_repository = PostgresSearchRepository(database, checking)
    try:
        with _active(save_repository, save):
            search_id = await save_repository.save_search(
                "Austin NNN",
                _query(),
                75,
            )
        assert isinstance(search_id, str)
        assert str(UUID(search_id)) == search_id

        with _active(list_repository, listing):
            rows = await list_repository.list_searches()
        assert rows == [
            {
                "id": search_id,
                "name": "Austin NNN",
                "query": _query(),
                "min_score": 75.0,
                "created_at": rows[0]["created_at"],
                "seen_count": 0,
            }
        ]
        assert datetime.fromisoformat(rows[0]["created_at"]).tzinfo is not None

        with _active(check_repository, checking):
            assert await check_repository.get_search(search_id) == rows[0]
            assert await check_repository.seen_keys(search_id) == set()
            claimed = await check_repository.claim_unseen(
                search_id,
                ["loopnet:one", "crexi:two", "loopnet:one"],
            )
            replayed = await check_repository.claim_unseen(
                search_id,
                ["crexi:two", "loopnet:one"],
            )
            compatibility = await check_repository.record_seen(
                search_id,
                ["loopnet:three", "loopnet:three"],
            )
            seen = await check_repository.seen_keys(search_id)
        assert claimed == {"crexi:two", "loopnet:one"}
        assert replayed == set()
        assert compatibility == 1
        assert seen == {"crexi:two", "loopnet:one", "loopnet:three"}

        with _active(list_repository, listing):
            assert (await list_repository.list_searches())[0]["seen_count"] == 3

        with psycopg.connect(admin_dsn) as connection:
            assert connection.execute(
                "SELECT workspace_id::text,owner_user_id::text "
                "FROM medawarcre.saved_searches WHERE id=%s",
                (search_id,),
            ).fetchone() == (workspace_id, actor_id)
    finally:
        database.close()


@pytest.mark.asyncio
async def test_saved_searches_are_actor_owned_and_same_private_name_does_not_leak(
    postgres_database: tuple[str, str, str],
) -> None:
    actor_a = str(uuid4())
    actor_b = str(uuid4())
    save_a = _admission("save_search", actor_user_id=actor_a)
    save_b = _admission("save_search", actor_user_id=actor_b)
    list_a = _admission("list_searches", actor_user_id=actor_a)
    list_b = _admission("list_searches", actor_user_id=actor_b)
    check_b = _admission("check_alerts", actor_user_id=actor_b)
    _, _, database = _prepare(
        postgres_database,
        (save_a, save_b, list_a, list_b, check_b),
    )
    repositories = {
        item: PostgresSearchRepository(database, admission)
        for item, admission in (
            ("save_a", save_a),
            ("save_b", save_b),
            ("list_a", list_a),
            ("list_b", list_b),
            ("check_b", check_b),
        )
    }
    try:
        with _active(repositories["save_a"], save_a):
            id_a = await repositories["save_a"].save_search(
                "Private buy box", _query("Austin, TX"), 70
            )
        with _active(repositories["save_b"], save_b):
            id_b = await repositories["save_b"].save_search(
                "Private buy box", _query("Dallas, TX"), 80
            )
        assert id_a != id_b

        with _active(repositories["list_a"], list_a):
            rows_a = await repositories["list_a"].list_searches()
        with _active(repositories["list_b"], list_b):
            rows_b = await repositories["list_b"].list_searches()
        assert [row["id"] for row in rows_a] == [id_a]
        assert [row["id"] for row in rows_b] == [id_b]

        with _active(repositories["check_b"], check_b):
            assert await repositories["check_b"].get_search(id_a) is None
            assert await repositories["check_b"].seen_keys(id_a) == set()
            assert (
                await repositories["check_b"].claim_unseen(id_a, ["loopnet:secret"])
                == set()
            )
    finally:
        database.close()


@pytest.mark.asyncio
async def test_saved_search_uuid_cannot_cross_workspace_boundary(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    actor_a = str(uuid4())
    actor_b = str(uuid4())
    save_a = _admission(
        "save_search",
        workspace_public_id="ws_search_cross_a",
        actor_user_id=actor_a,
    )
    check_b = _admission(
        "check_alerts",
        workspace_public_id="ws_search_cross_b",
        actor_user_id=actor_b,
    )
    workspace_a = _seed_workspace(
        admin_dsn,
        workspace_public_id=save_a.workspace_public_id,
        actor_ids=(actor_a,),
    )
    workspace_b = _seed_workspace(
        admin_dsn,
        workspace_public_id=check_b.workspace_public_id,
        actor_ids=(actor_b,),
    )
    _seed_admission(admin_dsn, workspace_a, save_a)
    _seed_admission(admin_dsn, workspace_b, check_b)
    database = _database(app_dsn)
    save_repository = PostgresSearchRepository(database, save_a)
    check_repository = PostgresSearchRepository(database, check_b)
    try:
        with _active(save_repository, save_a):
            search_id = await save_repository.save_search(
                "Workspace private",
                _query(),
                70,
            )
        with _active(check_repository, check_b):
            assert await check_repository.get_search(search_id) is None
            assert await check_repository.seen_keys(search_id) == set()
            assert await check_repository.claim_unseen(
                search_id,
                ["loopnet:private"],
            ) == set()
    finally:
        database.close()


@pytest.mark.asyncio
async def test_search_repository_requires_exact_method_and_live_scope(
    postgres_database: tuple[str, str, str],
) -> None:
    admission = _admission("list_searches")
    _, _, database = _prepare(postgres_database, (admission,))
    repository = PostgresSearchRepository(database, admission)
    try:
        with pytest.raises(SearchPersistenceUnavailable):
            await repository.list_searches()

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
                with pytest.raises(
                    SearchPersistenceUnavailable,
                    match="^search persistence unavailable$",
                ):
                    await repository.list_searches()

        with _active(object(), admission):
            with pytest.raises(SearchPersistenceUnavailable):
                await repository.list_searches()

        with _active(repository, admission):
            assert await repository.list_searches() == []
            with pytest.raises(SearchPersistenceUnavailable):
                await repository.save_search("Wrong method", _query(), 50)
            with pytest.raises(SearchPersistenceUnavailable):
                await repository.get_search(str(uuid4()))
    finally:
        database.close()


@pytest.mark.asyncio
async def test_detached_task_cannot_retain_search_repository_lease(
    postgres_database: tuple[str, str, str],
) -> None:
    admission = _admission("list_searches")
    _, _, database = _prepare(postgres_database, (admission,))
    repository = PostgresSearchRepository(database, admission)
    started = asyncio.Event()
    inspect = asyncio.Event()

    async def detached_read():
        started.set()
        await inspect.wait()
        return await repository.list_searches()

    try:
        with _active(repository, admission):
            task = asyncio.create_task(detached_read())
            await started.wait()
        inspect.set()
        with pytest.raises(SearchPersistenceUnavailable):
            await task
    finally:
        database.close()


@pytest.mark.asyncio
async def test_inflight_search_read_cannot_return_after_lease_revocation(
    postgres_database: tuple[str, str, str],
) -> None:
    admission = _admission("list_searches")
    _, _, database = _prepare(postgres_database, (admission,))
    repository = PostgresSearchRepository(database, admission)
    authorized = threading.Event()
    release = threading.Event()

    def blocking_read():
        repository._require_active_scope("list_searches")
        authorized.set()
        assert release.wait(timeout=5)
        return []

    try:
        with (
            patch.object(repository, "_list_searches", side_effect=blocking_read),
            _active(repository, admission),
        ):
            task = asyncio.create_task(repository.list_searches())
            assert await asyncio.to_thread(authorized.wait, 2)
        release.set()
        with pytest.raises(
            SearchPersistenceUnavailable,
            match="^search persistence unavailable$",
        ):
            await task
    finally:
        release.set()
        database.close()


@pytest.mark.asyncio
async def test_seen_write_rolls_back_when_lease_is_revoked_before_commit(
    postgres_database: tuple[str, str, str],
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_search", actor_user_id=actor_id)
    checking = _admission("check_alerts", actor_user_id=actor_id)
    admin_dsn, _, database = _prepare(postgres_database, (save, checking))
    save_repository = PostgresSearchRepository(database, save)
    check_repository = PostgresSearchRepository(database, checking)
    with _active(save_repository, save):
        search_id = await save_repository.save_search("Lease", _query(), 60)

    original = check_repository._require_active_scope
    lock = threading.Lock()
    calls = 0
    before_commit = threading.Event()
    release = threading.Event()

    def blocking_scope(method: str):
        nonlocal calls
        with lock:
            calls += 1
            current = calls
        if current == 3:
            before_commit.set()
            assert release.wait(timeout=5)
        return original(method)

    try:
        with (
            patch.object(
                check_repository,
                "_require_active_scope",
                side_effect=blocking_scope,
            ),
            _active(check_repository, checking),
        ):
            task = asyncio.create_task(
                check_repository.claim_unseen(search_id, ["loopnet:revoked"])
            )
            assert await asyncio.to_thread(before_commit.wait, 2)
        release.set()
        with pytest.raises(SearchPersistenceUnavailable):
            await task

        with psycopg.connect(admin_dsn) as connection:
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.saved_search_seen_matches "
                "WHERE dedupe_key='loopnet:revoked'"
            ).fetchone() == (0,)
    finally:
        release.set()
        database.close()


@pytest.mark.asyncio
async def test_search_worker_finishes_before_cancellation_escapes(
    postgres_database: tuple[str, str, str],
) -> None:
    admission = _admission("list_searches")
    _, _, database = _prepare(postgres_database, (admission,))
    repository = PostgresSearchRepository(database, admission)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_read():
        started.set()
        assert release.wait(timeout=5)
        finished.set()
        return []

    try:
        with (
            patch.object(repository, "_list_searches", side_effect=blocking_read),
            _active(repository, admission),
        ):
            task = asyncio.create_task(repository.list_searches())
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
@pytest.mark.parametrize(
    ("name", "query", "score"),
    [
        (" ", _query(), 50),
        ("x" * 201, _query(), 50),
        ("Valid", {**_query(), "unexpected": True}, 50),
        ("Valid", {**_query(), "sources": ["loopnet", "loopnet"]}, 50),
        ("Valid", {**_query(), "price_min": 9, "price_max": 1}, 50),
        ("Valid", _query(), float("nan")),
        ("Valid", _query(), 101),
    ],
)
async def test_invalid_search_input_raises_only_fixed_error(
    postgres_database: tuple[str, str, str],
    name: str,
    query: dict[str, object],
    score: float,
) -> None:
    admission = _admission("save_search")
    _, _, database = _prepare(postgres_database, (admission,))
    repository = PostgresSearchRepository(database, admission)
    try:
        with _active(repository, admission):
            with pytest.raises(
                SearchPersistenceUnavailable,
                match="^search persistence unavailable$",
            ):
                await repository.save_search(name, query, score)
    finally:
        database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "keys",
    [["x" * 513], [f"loopnet:{index}" for index in range(501)]],
)
async def test_invalid_seen_claim_is_bounded_and_raises_only_fixed_error(
    postgres_database: tuple[str, str, str],
    keys: list[str],
) -> None:
    admission = _admission("check_alerts")
    _, _, database = _prepare(postgres_database, (admission,))
    repository = PostgresSearchRepository(database, admission)
    try:
        with _active(repository, admission):
            with pytest.raises(
                SearchPersistenceUnavailable,
                match="^search persistence unavailable$",
            ):
                await repository.claim_unseen(str(uuid4()), keys)
    finally:
        database.close()


@pytest.mark.asyncio
async def test_malformed_stored_search_row_fails_closed_with_fixed_error(
    postgres_database: tuple[str, str, str],
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_search", actor_user_id=actor_id)
    listing = _admission("list_searches", actor_user_id=actor_id)
    admin_dsn, _, database = _prepare(postgres_database, (save, listing))
    save_repository = PostgresSearchRepository(database, save)
    list_repository = PostgresSearchRepository(database, listing)
    try:
        with _active(save_repository, save):
            search_id = await save_repository.save_search("Corruptible", _query(), 70)
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.saved_searches "
                "SET query=jsonb_set(query,'{location}','1'::jsonb) WHERE id=%s",
                (search_id,),
            )
        with _active(list_repository, listing):
            with pytest.raises(
                SearchPersistenceUnavailable,
                match="^search persistence unavailable$",
            ):
                await list_repository.list_searches()
    finally:
        database.close()


@pytest.mark.asyncio
async def test_mismatched_projected_workspace_fails_closed_with_fixed_error(
    postgres_database: tuple[str, str, str],
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_search", actor_user_id=actor_id)
    listing = _admission("list_searches", actor_user_id=actor_id)
    _, _, database = _prepare(postgres_database, (save, listing))
    save_repository = PostgresSearchRepository(database, save)
    list_repository = PostgresSearchRepository(database, listing)
    try:
        with _active(save_repository, save):
            await save_repository.save_search("Projection", _query(), 70)
        mismatched_select = list_repository._search_select().replace(
            "workspace.public_id",
            "'ws_unrelated_projection'::text",
            1,
        )
        with (
            patch.object(
                list_repository,
                "_search_select",
                return_value=mismatched_select,
            ),
            _active(list_repository, listing),
        ):
            with pytest.raises(
                SearchPersistenceUnavailable,
                match="^search persistence unavailable$",
            ):
                await list_repository.list_searches()
    finally:
        database.close()


@pytest.mark.asyncio
async def test_mismatched_saved_workspace_projection_rolls_back_with_fixed_error(
    postgres_database: tuple[str, str, str],
) -> None:
    admission = _admission("save_search")
    admin_dsn, _, database = _prepare(postgres_database, (admission,))
    repository = PostgresSearchRepository(database, admission)

    class _Result:
        def fetchone(self):
            return (uuid4(), "ws_unrelated_projection", UUID(admission.actor_user_id))

    class _Connection:
        def execute(self, _statement, _parameters):
            return _Result()

    @contextmanager
    def mismatched_connection(_admission):
        yield _Connection()

    try:
        with (
            patch.object(
                database,
                "admitted_connection",
                side_effect=mismatched_connection,
            ),
            _active(repository, admission),
        ):
            with pytest.raises(
                SearchPersistenceUnavailable,
                match="^search persistence unavailable$",
            ):
                await repository.save_search("Projection", _query(), 70)
        with psycopg.connect(admin_dsn) as connection:
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.saved_searches"
            ).fetchone() == (0,)
    finally:
        database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["seen_keys", "claim_unseen"])
async def test_mismatched_seen_workspace_projection_fails_closed_with_fixed_error(
    postgres_database: tuple[str, str, str],
    operation: str,
) -> None:
    admission = _admission("check_alerts")
    _, _, database = _prepare(postgres_database, (admission,))
    repository = PostgresSearchRepository(database, admission)

    class _Result:
        def fetchall(self):
            return [
                (
                    "ws_unrelated_projection",
                    UUID(admission.actor_user_id),
                    "loopnet:projected",
                )
            ]

    class _Connection:
        def execute(self, _statement, _parameters):
            return _Result()

    @contextmanager
    def mismatched_connection(_admission):
        yield _Connection()

    try:
        with (
            patch.object(
                database,
                "admitted_connection",
                side_effect=mismatched_connection,
            ),
            _active(repository, admission),
        ):
            with pytest.raises(
                SearchPersistenceUnavailable,
                match="^search persistence unavailable$",
            ):
                if operation == "seen_keys":
                    await repository.seen_keys(str(uuid4()))
                else:
                    await repository.claim_unseen(
                        str(uuid4()),
                        ["loopnet:projected"],
                    )
    finally:
        database.close()


@pytest.mark.asyncio
async def test_seen_match_app_acl_is_select_and_insert_only(
    postgres_database: tuple[str, str, str],
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_search", actor_user_id=actor_id)
    checking = _admission("check_alerts", actor_user_id=actor_id)
    _, _, database = _prepare(postgres_database, (save, checking))
    save_repository = PostgresSearchRepository(database, save)
    check_repository = PostgresSearchRepository(database, checking)
    try:
        with _active(save_repository, save):
            search_id = await save_repository.save_search("ACL", _query(), None)
        with _active(check_repository, checking):
            assert await check_repository.claim_unseen(
                search_id, ["loopnet:locked"]
            ) == {"loopnet:locked"}
            with database.admitted_connection(checking) as connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(
                        "UPDATE medawarcre.saved_search_seen_matches "
                        "SET dedupe_key='loopnet:changed'"
                    )
        with _active(check_repository, checking):
            with database.admitted_connection(checking) as connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(
                        "DELETE FROM medawarcre.saved_search_seen_matches"
                    )
        with _active(save_repository, save):
            with database.admitted_connection(save) as connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(
                        "UPDATE medawarcre.saved_searches SET active=false"
                    )
        with _active(save_repository, save):
            with database.admitted_connection(save) as connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute("DELETE FROM medawarcre.saved_searches")
    finally:
        database.close()


@pytest.mark.asyncio
async def test_concurrent_seen_claim_returns_each_key_once_total(
    postgres_database: tuple[str, str, str],
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_search", actor_user_id=actor_id)
    checks = tuple(
        _admission("check_alerts", actor_user_id=actor_id) for _ in range(2)
    )
    _, _, database = _prepare(postgres_database, (save, *checks))
    save_repository = PostgresSearchRepository(database, save)
    repositories = tuple(PostgresSearchRepository(database, item) for item in checks)
    try:
        with _active(save_repository, save):
            search_id = await save_repository.save_search("Race", _query(), 50)

        async def claim(repository, admission):
            with _active(repository, admission):
                return await repository.claim_unseen(
                    search_id,
                    ["loopnet:one", "loopnet:two"],
                )

        first, second = await asyncio.gather(
            *(claim(repository, admission) for repository, admission in zip(repositories, checks))
        )
        assert first.isdisjoint(second)
        assert first | second == {"loopnet:one", "loopnet:two"}
    finally:
        database.close()


def _deal(source_id: str) -> dict[str, object]:
    return {
        "listing": {
            "source": "crexi",
            "source_id": source_id,
            "url": f"https://www.crexi.com/properties/{source_id}",
            "address": "100 Congress Ave",
            "city": "Austin",
            "state": "TX",
            "zip_code": "78701",
        },
        "scores": [
            {"strategy": "nnn_retail", "score": 85, "grade": "A"},
        ],
        "best_strategy": "nnn_retail",
    }


@pytest.mark.asyncio
async def test_check_alerts_accepts_hosted_uuid_and_emits_only_atomic_claims() -> None:
    from cre_mcp.tools import pipeline_tools

    search_id = str(uuid4())

    class AtomicSearchStore:
        def __init__(self) -> None:
            self.claimed: set[str] = set()

        async def get_search(self, selected_id: str):
            assert selected_id == search_id
            return {
                "id": search_id,
                "name": "Hosted UUID",
                "query": _query(),
                "min_score": 70,
                "created_at": datetime.now(UTC).isoformat(),
                "seen_count": len(self.claimed),
            }

        async def seen_keys(self, selected_id: str):
            assert selected_id == search_id
            return set(self.claimed)

        async def claim_unseen(self, selected_id: str, keys: list[str]):
            assert selected_id == search_id
            inserted = set(keys) - self.claimed
            self.claimed.update(inserted)
            return inserted

    store = AtomicSearchStore()
    found = AsyncMock(
        return_value={"deals": [_deal("one"), _deal("one")], "errors": {}}
    )
    with (
        patch.object(pipeline_tools, "get_search_store", return_value=store),
        patch.object(pipeline_tools, "find_deals", new=found),
    ):
        first = await pipeline_tools.check_alerts(search_id)
        second = await pipeline_tools.check_alerts(search_id)

    assert first["new_count"] == 1
    assert first["new_deals"][0]["saved_search_id"] == search_id
    assert second["new_count"] == 0
    assert second["new_deals"] == []
