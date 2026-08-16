"""The hosted job engine, against the real disposable cluster.

Two boundaries are pinned here and they are not the same boundary.

The first is the customer one. ``PostgresJobRepository`` fills
``HostedRequestRepositories.job``, and every one of its methods refuses today
because ``_METHOD_TOOLS`` is empty — no MCP capability schedules anything. The
test that matters most in this file is
``test_the_refusal_is_the_empty_tool_mapping_and_not_absent_sql``: it patches a
mapping in, grants the app role the privilege production deliberately withholds,
and drives the same SQL end to end against PostgreSQL. Without it, "fail closed"
and "never written" would look identical from outside, and a later capability
would be plugged into a port nobody had ever run.

The second is the internal one. ``InternalJobQueue`` and
``SavedSearchScheduler`` are not bundle fields and are not reachable from a
customer request; they run on the admin runtime, and the tests below pin the
lease, the retry bound, the reap, the deduplication window, and — the two the
launch turns on — the entitlement and territory rechecks that must read live
state and refuse terminally rather than retry into success.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.access.context import TenantContext, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.domains import HostedRequestRepositories, use_hosted_request_repositories
from cre_mcp.postgres.jobs import (
    InternalJobQueue,
    JobLeaseLost,
    JobPersistenceUnavailable,
    PostgresJobRepository,
    SavedSearchScheduler,
    WorkerIdentity,
    saved_search_idempotency_key,
)
from cre_mcp.postgres.migrations import MigrationRunner, load_migrations
from cre_mcp.postgres.pool import PostgresDatabase

_UNAVAILABLE = "job persistence unavailable"
_ADMIN_USER = "user=medawarcre_test_admin"
_APP_USER = "user=medawarcre_test_app"


# ---------------------------------------------------------------------------
# Fixture plumbing.
# ---------------------------------------------------------------------------


class World:
    """One migrated database with two workspaces, seeded and entitled."""

    def __init__(self, admin_dsn: str, app_dsn: str) -> None:
        self.admin_dsn = admin_dsn
        self.app_dsn = app_dsn
        self.staff_dsn = app_dsn.replace(_APP_USER, _ADMIN_USER)
        self.ids: dict[str, str] = {}

    @contextmanager
    def owner(self):
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            yield connection

    def identity(self, role: str = "owner") -> WorkerIdentity:
        return WorkerIdentity(
            actor_user_id=self.ids["staff_" + role],
            role=role,
            reason_code="scheduled_run",
            reason="scheduled saved-search run",
        )

    def queue(self, role: str = "owner") -> InternalJobQueue:
        return InternalJobQueue.for_dsn(self.staff_dsn, self.identity(role))

    def scheduler(self, queue: InternalJobQueue) -> SavedSearchScheduler:
        return SavedSearchScheduler(queue.database, queue)


def _seed(world: World) -> None:
    ids = world.ids
    ids.update(
        {
            "plan": str(uuid4()),
            "workspace_a": str(uuid4()),
            "workspace_b": str(uuid4()),
            "user_a": str(uuid4()),
            "user_b": str(uuid4()),
            "staff_owner": str(uuid4()),
            "staff_read_only_analyst": str(uuid4()),
            "search_a": str(uuid4()),
            "search_b": str(uuid4()),
        }
    )
    with world.owner() as connection:
        connection.execute(
            "INSERT INTO medawarcre.plans(id,plan_key,name,daily_quotas,active) "
            "VALUES (%s,'operator','Operator',"
            "'{\"search\": 500}'::jsonb,true)",
            (ids["plan"],),
        )
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) VALUES "
            "(%s,'a@example.test','A','active'),(%s,'b@example.test','B','active'),"
            "(%s,'staff@example.test','Staff','active'),"
            "(%s,'analyst@example.test','Analyst','active')",
            (
                ids["user_a"],
                ids["user_b"],
                ids["staff_owner"],
                ids["staff_read_only_analyst"],
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.staff_roles(user_id,role,active) VALUES "
            "(%s,'owner',true),(%s,'read_only_analyst',true)",
            (ids["staff_owner"], ids["staff_read_only_analyst"]),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,plan_id,state) "
            "VALUES (%s,'ws_job_a','Workspace A',%s,'active'),"
            "(%s,'ws_job_b','Workspace B',%s,'active')",
            (ids["workspace_a"], ids["plan"], ids["workspace_b"], ids["plan"]),
        )
        for workspace, user in (
            (ids["workspace_a"], ids["user_a"]),
            (ids["workspace_b"], ids["user_b"]),
        ):
            connection.execute(
                "INSERT INTO medawarcre.memberships("
                "workspace_id,user_id,role,state) VALUES (%s,%s,'owner','active')",
                (workspace, user),
            )
            connection.execute(
                "INSERT INTO medawarcre.workspace_accounts(workspace_id,state) "
                "VALUES (%s,'active')",
                (workspace,),
            )
            connection.execute(
                "INSERT INTO medawarcre.access_grants("
                "workspace_id,subject_user_id,scope,source,external_ref_hash,"
                "profile,plan_key,status,starts_at,ends_at) "
                "VALUES (%s,%s,'subject','manual',pg_catalog.sha256("
                "pg_catalog.convert_to(%s,'UTF8')),'full_operator','operator',"
                "'active',statement_timestamp() - interval '1 day',NULL)",
                (workspace, user, f"grant-{workspace}"),
            )
            connection.execute(
                "INSERT INTO medawarcre.territories("
                "workspace_id,name,state_code) VALUES (%s,'Texas','TX')",
                (workspace,),
            )
        # The platform authority, which is what the scheduler's entitlement
        # gate now reads. The certified rows above are the projection of these;
        # seeding only the copies made every gate answer
        # `workspace_not_admissible`, which is the gate working.
        connection.execute(
            "INSERT INTO medawarcre.platform_plans"
            "(key,name,daily_quotas,created_at,updated_at) "
            "VALUES ('operator','Operator','{\"search\": 500}',"
            "'2026-01-01','2026-01-01')"
        )
        connection.execute(
            "INSERT INTO medawarcre.platform_users"
            "(email,name,created_at,updated_at) VALUES "
            "('a@example.test','A','2026-01-01','2026-01-01'),"
            "('b@example.test','B','2026-01-01','2026-01-01')"
        )
        for public_id, email in (("ws_job_a", "a@example.test"),
                                 ("ws_job_b", "b@example.test")):
            connection.execute(
                "INSERT INTO medawarcre.platform_workspaces"
                "(public_id,name,plan_id,created_at,updated_at) SELECT %s,%s,"
                "plan.id,'2026-01-01','2026-01-01' FROM medawarcre.platform_plans "
                "plan WHERE plan.key='operator'",
                (public_id, f"Workspace {public_id[-1].upper()}"),
            )
            connection.execute(
                "INSERT INTO medawarcre.platform_memberships"
                "(workspace_id,user_id,role,created_at,updated_at) "
                "SELECT w.id,u.id,'owner','2026-01-01','2026-01-01' "
                "FROM medawarcre.platform_workspaces w, medawarcre.platform_users u "
                "WHERE w.public_id=%s AND u.email=%s",
                (public_id, email),
            )
            connection.execute(
                "INSERT INTO medawarcre.platform_accounts"
                "(workspace_id,state,updated_at) SELECT w.id,'active','2026-01-01' "
                "FROM medawarcre.platform_workspaces w WHERE w.public_id=%s",
                (public_id,),
            )
            connection.execute(
                "INSERT INTO medawarcre.platform_access_grants"
                "(workspace_id,subject_user_id,scope,source,external_ref,"
                "profile,plan_key,status,starts_at,ends_at,created_at,updated_at) "
                "SELECT w.id,u.id,'subject','manual',%s,'full_operator','operator',"
                "'active','2026-01-01T00:00:00+00:00',NULL,'2026-01-01','2026-01-01' "
                "FROM medawarcre.platform_workspaces w, medawarcre.platform_users u "
                "WHERE w.public_id=%s AND u.email=%s",
                (f"grant-{public_id}", public_id, email),
            )
            connection.execute(
                "INSERT INTO medawarcre.platform_territories"
                "(workspace_id,name,state,created_at,updated_at) "
                "SELECT w.id,'Texas','TX','2026-01-01','2026-01-01' "
                "FROM medawarcre.platform_workspaces w WHERE w.public_id=%s",
                (public_id,),
            )
        for search, workspace, user in (
            (ids["search_a"], ids["workspace_a"], ids["user_a"]),
            (ids["search_b"], ids["workspace_b"], ids["user_b"]),
        ):
            connection.execute(
                "INSERT INTO medawarcre.saved_searches("
                "id,workspace_id,owner_user_id,name,query,schedule,active) "
                "VALUES (%s,%s,%s,'Austin retail',"
                "jsonb_build_object('location','Austin, TX','strategy',"
                "'nnn_retail','property_type','retail','price_min',1000000,"
                "'price_max',4000000,'size_min',5000,'size_max',30000,"
                "'sources',jsonb_build_array('crexi')),'daily',true)",
                (search, workspace, user),
            )


@pytest.fixture
def world(postgres_database: tuple[str, str, str]) -> World:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    built = World(admin_dsn, app_dsn)
    _seed(built)
    return built


# ---------------------------------------------------------------------------
# The customer boundary.
# ---------------------------------------------------------------------------


def _admission(tool_name: str, workspace_public_id: str, actor_user_id: str) -> AdmissionOutcome:
    return AdmissionOutcome(
        invocation_id=str(uuid4()),
        request_correlation_id=str(uuid4()),
        workspace_public_id=workspace_public_id,
        actor_user_id=actor_user_id,
        session_id=str(uuid4()),
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
    admission: AdmissionOutcome, job: object
) -> HostedRequestRepositories:
    marker = object()
    return HostedRequestRepositories(
        admission=admission,
        platform=marker,
        provider=marker,
        search=marker,
        deal=marker,
        privacy=marker,
        job=job,
        document=marker,
        truth_asset=marker,
    )


@contextmanager
def _active(repository: object, admission: AdmissionOutcome):
    with use_context(_context(admission)), use_hosted_request_repositories(
        _repositories(admission, repository)
    ):
        yield


def _seed_admission(world: World, workspace_id: str, admission: AdmissionOutcome) -> None:
    with world.owner() as connection:
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


def _app_database(app_dsn: str) -> PostgresDatabase:
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=4, runtime_mode="app")
    )
    database.open()
    return database


@contextmanager
def _app_may_touch_jobs(world: World):
    """Lend ``medawarcre_app`` the privilege production withholds.

    Migration 0001 grants ``medawarcre.jobs`` to ``medawarcre_admin`` only, so
    the customer-scoped SQL below could not execute at all under the shipped
    grants. That is a real second layer of refusal and it is asserted on its own
    in ``test_the_customer_role_holds_no_privilege_on_the_job_relations``. Here
    it is lifted for the duration of one test so the *first* layer — the empty
    tool mapping — is what the assertion is actually measuring.
    """
    with world.owner() as connection:
        connection.execute(
            "GRANT SELECT, INSERT ON medawarcre.jobs TO medawarcre_app"
        )
    try:
        yield
    finally:
        with world.owner() as connection:
            connection.execute(
                "REVOKE SELECT, INSERT ON medawarcre.jobs FROM medawarcre_app"
            )


@pytest.mark.asyncio
async def test_every_request_scoped_job_method_refuses_with_one_opaque_message(
    world: World,
) -> None:
    """No capability maps to this domain, so every method refuses identically."""
    admission = _admission("check_alerts", "ws_job_a", world.ids["user_a"])
    _seed_admission(world, world.ids["workspace_a"], admission)
    database = _app_database(world.app_dsn)
    repository = PostgresJobRepository(database, admission)

    calls = (
        lambda: repository.list_jobs(),
        lambda: repository.enqueue_saved_search_run(
            world.ids["search_a"], idempotency_key="k"
        ),
    )

    # Inside a correct, live request scope. The mapping is the only thing that
    # refuses, and it refuses with one message that says nothing.
    with _active(repository, admission):
        for call in calls:
            with pytest.raises(JobPersistenceUnavailable) as raised:
                await call()
            assert str(raised.value) == _UNAVAILABLE

    # Outside any hosted scope at all.
    for call in calls:
        with pytest.raises(JobPersistenceUnavailable) as raised:
            await call()
        assert str(raised.value) == _UNAVAILABLE

    # Bound to a different repository object in the same bundle field.
    other = PostgresJobRepository(database, admission)
    with _active(other, admission):
        for call in calls:
            with pytest.raises(JobPersistenceUnavailable) as raised:
                await call()
            assert str(raised.value) == _UNAVAILABLE
    database.close()


@pytest.mark.asyncio
async def test_the_refusal_is_the_empty_tool_mapping_and_not_absent_sql(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch a mapping in and the same SQL runs end to end against PostgreSQL.

    This is the difference between "fail closed" and "unimplemented". Both look
    like ``JobPersistenceUnavailable`` from the caller's side; only one of them
    starts working the moment a capability exists.
    """
    from cre_mcp.postgres import jobs as jobs_module

    admission = _admission("check_alerts", "ws_job_a", world.ids["user_a"])
    _seed_admission(world, world.ids["workspace_a"], admission)
    second = _admission("check_alerts", "ws_job_a", world.ids["user_a"])
    _seed_admission(world, world.ids["workspace_a"], second)

    database = _app_database(world.app_dsn)
    repository = PostgresJobRepository(database, admission)

    # Unmapped: refused, with nothing written.
    with _active(repository, admission):
        with pytest.raises(JobPersistenceUnavailable):
            await repository.list_jobs()

    monkeypatch.setitem(
        jobs_module._METHOD_TOOLS, "list_jobs", frozenset({"check_alerts"})
    )
    monkeypatch.setitem(
        jobs_module._METHOD_TOOLS,
        "enqueue_saved_search_run",
        frozenset({"check_alerts"}),
    )

    with _app_may_touch_jobs(world):
        with _active(repository, admission):
            assert await repository.list_jobs() == []
            job_id = await repository.enqueue_saved_search_run(
                world.ids["search_a"], idempotency_key="proof-key"
            )
            listed = await repository.list_jobs()

        assert len(listed) == 1
        assert listed[0]["id"] == job_id
        assert listed[0]["kind"] == "saved_search"
        assert listed[0]["status"] == "queued"
        assert listed[0]["saved_search_id"] == world.ids["search_a"]

        # And it is idempotent on the way through the customer port too.
        other = PostgresJobRepository(database, second)
        with _active(other, second):
            assert (
                await other.enqueue_saved_search_run(
                    world.ids["search_a"], idempotency_key="proof-key"
                )
                == job_id
            )
            assert len(await other.list_jobs()) == 1

    # The row really is in the database, written by the app role.
    with world.owner() as connection:
        row = connection.execute(
            "SELECT workspace_id, kind, idempotency_key FROM medawarcre.jobs "
            "WHERE id=%s",
            (job_id,),
        ).fetchone()
    assert row == (
        __import__("uuid").UUID(world.ids["workspace_a"]),
        "saved_search",
        "proof-key",
    )
    database.close()


def test_the_customer_role_holds_no_privilege_on_the_job_relations(
    world: World,
) -> None:
    """A grant boundary before it is a policy boundary.

    Even if the tool mapping were opened by mistake, ``medawarcre_app`` would be
    refused by PostgreSQL before row-level security was consulted.
    """
    with psycopg.connect(world.app_dsn) as connection:
        for relation in ("jobs", "job_attempts"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                held = connection.execute(
                    "SELECT pg_catalog.has_table_privilege("
                    "'medawarcre_app', %s, %s)",
                    (f"medawarcre.{relation}", privilege),
                ).fetchone()[0]
                assert held is False, f"{relation}.{privilege}"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT count(*) FROM medawarcre.jobs")


def test_a_customer_role_cannot_read_another_workspaces_jobs(world: World) -> None:
    """Tenant isolation, under the grant the shipped schema does not make."""
    queue = world.queue()
    queue.enqueue(
        "ws_job_a", "saved_search", {}, idempotency_key="a-1",
        saved_search_id=world.ids["search_a"],
    )
    queue.enqueue(
        "ws_job_b", "saved_search", {}, idempotency_key="b-1",
        saved_search_id=world.ids["search_b"],
    )
    queue.close()

    with _app_may_touch_jobs(world), psycopg.connect(world.app_dsn) as connection:
        connection.execute(
            "SELECT pg_catalog.set_config('app.workspace_id',%s,false),"
            "pg_catalog.set_config('app.actor_user_id',%s,false)",
            (world.ids["workspace_a"], world.ids["user_a"]),
        )
        rows = connection.execute(
            "SELECT idempotency_key FROM medawarcre.jobs ORDER BY idempotency_key"
        ).fetchall()
        assert rows == [("a-1",)]

        # And the other tenant's row is not merely filtered out of a list; it
        # cannot be fetched by its own key either.
        assert (
            connection.execute(
                "SELECT count(*) FROM medawarcre.jobs WHERE idempotency_key='b-1'"
            ).fetchone()[0]
            == 0
        )


# ---------------------------------------------------------------------------
# The internal queue.
# ---------------------------------------------------------------------------


def test_enqueue_is_idempotent_under_a_repeated_key(world: World) -> None:
    """A repeated key returns the first job rather than raising or duplicating."""
    queue = world.queue()
    first = queue.enqueue(
        "ws_job_a", "saved_search", {"n": 1}, idempotency_key="dup",
        saved_search_id=world.ids["search_a"],
    )
    results: list[str] = []
    barrier = threading.Barrier(4)

    def again() -> None:
        worker = world.queue()
        try:
            barrier.wait(timeout=20)
            results.append(
                worker.enqueue(
                    "ws_job_a", "saved_search", {"n": 2}, idempotency_key="dup",
                    saved_search_id=world.ids["search_a"],
                ).id
            )
        finally:
            worker.close()

    threads = [threading.Thread(target=again) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert results == [first.id] * 4
    # The payload of the winner survives; a later call does not overwrite it.
    assert first.payload == {"n": 1}
    with world.owner() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM medawarcre.jobs WHERE idempotency_key='dup'"
            ).fetchone()[0]
            == 1
        )
    queue.close()


def test_two_workers_claiming_concurrently_get_disjoint_jobs(world: World) -> None:
    """``SKIP LOCKED``: neither blocks, and neither sees the other's job."""
    queue = world.queue()
    for index in range(8):
        queue.enqueue(
            "ws_job_a", "saved_search", {}, idempotency_key=f"c-{index}",
            saved_search_id=world.ids["search_a"],
        )

    claimed: list[set[str]] = []
    barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        own = world.queue()
        try:
            barrier.wait(timeout=20)
            claimed.append(
                {job.id for job in own.claim(name, lease_seconds=60, limit=8)}
            )
        finally:
            own.close()

    threads = [
        threading.Thread(target=worker, args=(f"worker-{index}",))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(claimed) == 2
    assert not claimed[0] & claimed[1]
    assert len(claimed[0] | claimed[1]) == 8

    # Every claim opened exactly one attempt row, numbered by attempt_count.
    with world.owner() as connection:
        rows = connection.execute(
            "SELECT count(*), count(DISTINCT job_id), min(attempt_number), "
            "max(attempt_number) FROM medawarcre.job_attempts "
            "WHERE status='running'"
        ).fetchone()
    assert rows == (8, 8, 1, 1)
    queue.close()


def test_a_claim_skips_a_row_another_transaction_holds_rather_than_blocking(
    world: World,
) -> None:
    """The direct ``SKIP LOCKED`` proof: an uncommitted lock is stepped over.

    Without ``SKIP LOCKED`` this claim would wait on the open transaction and
    die on the pool's five-second ``lock_timeout``, so the assertion is that it
    returns the *other* job promptly.
    """
    queue = world.queue()
    first = queue.enqueue(
        "ws_job_a", "saved_search", {}, idempotency_key="skip-1",
        saved_search_id=world.ids["search_a"],
        next_run_at=datetime.now(UTC) - timedelta(minutes=2),
    )
    second = queue.enqueue(
        "ws_job_a", "saved_search", {}, idempotency_key="skip-2",
        saved_search_id=world.ids["search_a"],
        next_run_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    holder = psycopg.connect(world.admin_dsn)
    try:
        holder.execute("SET ROLE medawarcre_migration")
        holder.execute(
            "SELECT id FROM medawarcre.jobs WHERE id=%s FOR UPDATE", (first.id,)
        ).fetchall()
        leased = queue.claim("skipper", lease_seconds=60, limit=1)
        assert [job.id for job in leased] == [second.id]
    finally:
        holder.rollback()
        holder.close()
    queue.close()


def test_an_expired_lease_cannot_complete_or_fail_a_job(world: World) -> None:
    """A worker whose lease ran out is refused, not allowed to write stale work."""
    queue = world.queue()
    queue.enqueue(
        "ws_job_a", "saved_search", {}, idempotency_key="lease",
        saved_search_id=world.ids["search_a"],
    )
    start = datetime.now(UTC)
    job = queue.claim("slow", lease_seconds=1, limit=1, now=start)[0]
    later = start + timedelta(seconds=30)

    with pytest.raises(JobLeaseLost):
        queue.complete(job.id, "slow", now=later)
    with pytest.raises(JobLeaseLost):
        queue.fail(job.id, "slow", "boom", now=later)
    # Nor may a different worker finish someone else's live lease.
    with pytest.raises(JobLeaseLost):
        queue.complete(job.id, "thief", now=start)

    with world.owner() as connection:
        assert connection.execute(
            "SELECT status, lease_owner FROM medawarcre.jobs WHERE id=%s",
            (job.id,),
        ).fetchone() == ("leased", "slow")
        assert connection.execute(
            "SELECT status FROM medawarcre.job_attempts WHERE job_id=%s",
            (job.id,),
        ).fetchall() == [("running",)]
    queue.close()


def test_failure_retries_with_backoff_up_to_max_attempts_then_fails(
    world: World,
) -> None:
    """Three attempts, growing backoff between them, then terminal ``failed``."""
    queue = world.queue()
    queue.enqueue(
        "ws_job_a", "saved_search", {}, idempotency_key="retry", max_attempts=3,
        saved_search_id=world.ids["search_a"],
    )
    moment = datetime.now(UTC)
    delays: list[float] = []
    for attempt in range(1, 4):
        claimed = queue.claim("retrier", lease_seconds=60, limit=1, now=moment)
        assert [job.attempt_count for job in claimed] == [attempt]
        record = queue.fail(claimed[0].id, "retrier", "boom", now=moment)
        assert record.last_error_code == "boom"
        if attempt < 3:
            assert record.status == "queued"
            delays.append(
                (
                    datetime.fromisoformat(record.next_run_at) - moment
                ).total_seconds()
            )
            moment = datetime.fromisoformat(record.next_run_at)
        else:
            assert record.status == "failed"

    assert delays == [30.0, 60.0]
    # At the bound the job is terminal, and a claim will not pick it up again.
    assert queue.claim("retrier", lease_seconds=60, limit=5, now=moment) == ()
    with world.owner() as connection:
        assert connection.execute(
            "SELECT attempt_number, status, error_code "
            "FROM medawarcre.job_attempts ORDER BY attempt_number"
        ).fetchall() == [
            (1, "failed", "boom"),
            (2, "failed", "boom"),
            (3, "failed", "boom"),
        ]
    queue.close()


def test_reap_expired_leases_requeues_and_abandons_the_attempt(world: World) -> None:
    queue = world.queue()
    queue.enqueue(
        "ws_job_a", "saved_search", {}, idempotency_key="reap",
        saved_search_id=world.ids["search_a"],
    )
    start = datetime.now(UTC)
    job = queue.claim("vanished", lease_seconds=5, limit=1, now=start)[0]

    assert queue.reap_expired_leases(now=start + timedelta(seconds=1)) == ()
    assert queue.reap_expired_leases(now=start + timedelta(seconds=30)) == (job.id,)

    with world.owner() as connection:
        assert connection.execute(
            "SELECT status, lease_owner, leased_until FROM medawarcre.jobs "
            "WHERE id=%s",
            (job.id,),
        ).fetchone() == ("queued", None, None)
        attempt = connection.execute(
            "SELECT attempt_number, status, completed_at IS NOT NULL "
            "FROM medawarcre.job_attempts WHERE job_id=%s",
            (job.id,),
        ).fetchall()
    assert attempt == [(1, "abandoned", True)]

    # It is claimable again, and the reaped attempt does not buy a free retry:
    # attempt_count was already spent, so the bound still holds.
    again = queue.claim("second", lease_seconds=60, limit=1, now=start)
    assert [job.attempt_count for job in again] == [2]
    queue.close()


def test_queue_status_reports_counts_and_the_oldest_queued_age(world: World) -> None:
    queue = world.queue()
    for index in range(3):
        queue.enqueue(
            "ws_job_a", "saved_search", {}, idempotency_key=f"s-{index}",
            saved_search_id=world.ids["search_a"],
        )
    queue.enqueue(
        "ws_job_b", "saved_search", {}, idempotency_key="s-b",
        saved_search_id=world.ids["search_b"],
    )
    queue.claim("counter", lease_seconds=60, limit=1)

    everything = queue.status()
    assert everything.counts["queued"] == 3
    assert everything.counts["leased"] == 1
    assert everything.oldest_queued_age_seconds is not None
    assert everything.oldest_queued_age_seconds >= 0

    only_b = queue.status("ws_job_b")
    assert only_b.counts["queued"] == 1
    assert only_b.counts["leased"] == 0
    queue.close()


def test_a_read_only_analyst_may_see_the_queue_but_not_change_it(
    world: World,
) -> None:
    queue = world.queue("read_only_analyst")
    assert queue.status().counts["queued"] == 0
    with pytest.raises(PermissionError):
        queue.enqueue(
            "ws_job_a", "saved_search", {}, idempotency_key="denied",
            saved_search_id=world.ids["search_a"],
        )
    with pytest.raises(PermissionError):
        queue.claim("analyst", lease_seconds=60)
    queue.close()


# ---------------------------------------------------------------------------
# The scheduler.
# ---------------------------------------------------------------------------


def test_two_schedule_due_calls_in_one_window_enqueue_one_job(world: World) -> None:
    """The window-derived key is the deduplication mechanism."""
    queue = world.queue()
    scheduler = world.scheduler(queue)
    moment = datetime(2026, 8, 16, 9, 30, tzinfo=UTC)

    first = scheduler.schedule_due(now=moment)
    second = scheduler.schedule_due(now=moment + timedelta(hours=6))
    assert len(first) == 2  # one per seeded workspace
    assert second == first

    with world.owner() as connection:
        assert (
            connection.execute("SELECT count(*) FROM medawarcre.jobs").fetchone()[0]
            == 2
        )
        keys = connection.execute(
            "SELECT idempotency_key FROM medawarcre.jobs ORDER BY idempotency_key"
        ).fetchall()
    window = datetime(2026, 8, 16, tzinfo=UTC)
    assert sorted(key for (key,) in keys) == sorted(
        saved_search_idempotency_key(world.ids[name], window)
        for name in ("search_a", "search_b")
    )

    # The next window is a different key, so the search runs again.
    third = scheduler.schedule_due(now=moment + timedelta(days=1))
    assert not set(third) & set(first)
    queue.close()


def test_a_workspace_that_lost_entitlement_is_refused_and_not_retried(
    world: World,
) -> None:
    """The recheck reads the live grant, never the one captured at enqueue."""
    queue = world.queue()
    scheduler = world.scheduler(queue)
    moment = datetime.now(UTC)
    scheduler.schedule_due(now=moment)

    # Entitled at enqueue; revoked before the worker gets there.
    with world.owner() as connection:
        connection.execute(
            "UPDATE medawarcre.platform_access_grants SET status='revoked' "
            "WHERE workspace_id=(SELECT id FROM medawarcre.platform_workspaces "
            "WHERE public_id=%s)",
            ("ws_job_a",),
        )

    outcomes = [
        scheduler.run_once("runner", now=moment + timedelta(seconds=1)),
        scheduler.run_once("runner", now=moment + timedelta(seconds=2)),
    ]
    by_workspace = {outcome.workspace_public_id: outcome for outcome in outcomes}
    refused = by_workspace["ws_job_a"]
    assert refused.outcome == "refused"
    assert refused.reason_code == "entitlement_missing_or_expired"
    # The other workspace is untouched by its neighbour's lapse.
    assert by_workspace["ws_job_b"].outcome == "executed"

    with world.owner() as connection:
        assert connection.execute(
            "SELECT status, last_error_code FROM medawarcre.jobs WHERE id=%s",
            (refused.job_id,),
        ).fetchone() == ("canceled", "entitlement_missing_or_expired")

    # Terminal: no worker picks it up again, so it cannot be retried into
    # success once the grant is restored.
    with world.owner() as connection:
        connection.execute(
            "UPDATE medawarcre.platform_access_grants SET status='active' "
            "WHERE workspace_id=(SELECT id FROM medawarcre.platform_workspaces "
            "WHERE public_id=%s)",
            ("ws_job_a",),
        )
    assert (
        scheduler.run_once("runner", now=moment + timedelta(minutes=5)).outcome
        == "idle"
    )

    # And the refusal is on the record.
    with world.owner() as connection:
        rows = connection.execute(
            "SELECT action, result, after_data->>'reason_code' "
            "FROM medawarcre.staff_audit_log WHERE object_id=%s",
            (refused.job_id,),
        ).fetchall()
    assert rows == [("run_job", "denied", "entitlement_missing_or_expired")]
    queue.close()


def test_a_search_outside_the_current_territory_is_refused(world: World) -> None:
    """Territory is rechecked with the access engine's own authority."""
    queue = world.queue()
    scheduler = world.scheduler(queue)
    moment = datetime.now(UTC)
    scheduler.schedule_due(now=moment)

    with world.owner() as connection:
        connection.execute(
            "UPDATE medawarcre.platform_territories SET state='CA', "
            "name='California' "
            "WHERE workspace_id=(SELECT id FROM medawarcre.platform_workspaces "
            "WHERE public_id=%s)",
            ("ws_job_a",),
        )

    outcomes = [
        scheduler.run_once("runner", now=moment + timedelta(seconds=1)),
        scheduler.run_once("runner", now=moment + timedelta(seconds=2)),
    ]
    by_workspace = {outcome.workspace_public_id: outcome for outcome in outcomes}
    assert by_workspace["ws_job_a"].outcome == "refused"
    assert by_workspace["ws_job_a"].reason_code == "territory_not_granted"
    assert by_workspace["ws_job_b"].outcome == "executed"

    with world.owner() as connection:
        assert connection.execute(
            "SELECT status, last_error_code FROM medawarcre.jobs WHERE id=%s",
            (by_workspace["ws_job_a"].job_id,),
        ).fetchone() == ("canceled", "territory_not_granted")
    queue.close()


def test_an_entitled_run_executes_once_and_is_audited(world: World) -> None:
    queue = world.queue()
    scheduler = world.scheduler(queue)
    moment = datetime.now(UTC)
    scheduler.schedule_due(now=moment)

    seen: list[tuple[str, tuple[str, ...]]] = []

    def executor(job, entitlement) -> str:
        seen.append((job.workspace_public_id, entitlement.territories))
        return "ran"

    outcome = scheduler.run_once(
        "runner", now=moment + timedelta(seconds=1), executor=executor
    )
    assert outcome.outcome == "executed"
    assert outcome.reason_code == "ran"
    assert seen == [(outcome.workspace_public_id, ("TX",))]

    with world.owner() as connection:
        assert connection.execute(
            "SELECT status FROM medawarcre.jobs WHERE id=%s", (outcome.job_id,)
        ).fetchone() == ("succeeded",)
        assert connection.execute(
            "SELECT attempt_number, status FROM medawarcre.job_attempts "
            "WHERE job_id=%s",
            (outcome.job_id,),
        ).fetchall() == [(1, "succeeded")]
        audit = connection.execute(
            "SELECT actor_role, reason_code, result, workspace_id, "
            "after_data->>'workspace_public_id' "
            "FROM medawarcre.staff_audit_log WHERE object_id=%s",
            (outcome.job_id,),
        ).fetchall()
    # workspace_id is deliberately NULL: linking it would make the workspace
    # undeletable on the strength of a job having run against it.
    assert audit == [
        ("owner", "scheduled_run", "succeeded", None, outcome.workspace_public_id)
    ]
    queue.close()


def test_a_deactivated_saved_search_is_refused_rather_than_run(world: World) -> None:
    queue = world.queue()
    scheduler = world.scheduler(queue)
    moment = datetime.now(UTC)
    scheduler.schedule_due(now=moment)

    with world.owner() as connection:
        connection.execute(
            "UPDATE medawarcre.saved_searches SET active=false WHERE id=%s",
            (world.ids["search_a"],),
        )

    outcomes = [
        scheduler.run_once("runner", now=moment + timedelta(seconds=1)),
        scheduler.run_once("runner", now=moment + timedelta(seconds=2)),
    ]
    by_workspace = {outcome.workspace_public_id: outcome for outcome in outcomes}
    assert by_workspace["ws_job_a"].reason_code == "saved_search_inactive"
    assert by_workspace["ws_job_b"].outcome == "executed"
    queue.close()
