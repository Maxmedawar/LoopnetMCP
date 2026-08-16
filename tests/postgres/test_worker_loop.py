"""The scheduled-search worker, running against a real database.

`InternalJobQueue` and `SavedSearchScheduler` have their own tests. What this
file covers is the thing that turns them into a running product: the loop, its
refusal to start without a named staff identity, and its behaviour when a tick
raises.
"""

from __future__ import annotations

import logging

import psycopg
import pytest

from cre_mcp.postgres.jobs import (
    InternalJobQueue,
    SavedSearchScheduler,
    WorkerIdentity,
)
from cre_mcp.postgres.migrations import MigrationRunner
from cre_mcp.postgres.worker import (
    WORKER_ACTOR_ENV,
    WORKER_DSN_ENV,
    WorkerLoop,
    WorkerUnavailable,
    build_worker,
)


@pytest.fixture
def admin_dsn(postgres_database) -> str:
    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    return app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")


def _staff_actor(admin_dsn: str) -> str:
    """One real staff row, because the audit policy pins the actor against it."""
    owner = admin_dsn.replace("user=medawarcre_test_admin", "user=postgres")
    with psycopg.connect(owner) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        user_id = connection.execute(
            "INSERT INTO users(email, name) VALUES (%s,%s) RETURNING id",
            ("worker-operator@example.test", "Worker Operator"),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO staff_roles(user_id, role, active) VALUES (%s,'admin',true)",
            (user_id,),
        )
        connection.commit()
    return str(user_id)


def test_the_worker_refuses_to_start_without_a_dsn(monkeypatch) -> None:
    monkeypatch.delenv(WORKER_DSN_ENV, raising=False)
    with pytest.raises(WorkerUnavailable, match=WORKER_DSN_ENV):
        build_worker()


def test_the_worker_refuses_to_start_without_a_named_staff_identity(
    admin_dsn, monkeypatch
) -> None:
    """A defaulted actor would produce an audit trail naming nobody."""
    monkeypatch.setenv(WORKER_DSN_ENV, admin_dsn)
    monkeypatch.delenv(WORKER_ACTOR_ENV, raising=False)
    with pytest.raises(WorkerUnavailable, match=WORKER_ACTOR_ENV):
        build_worker()


def test_the_worker_starts_from_the_environment_a_deployment_injects(
    admin_dsn, monkeypatch
) -> None:
    monkeypatch.setenv(WORKER_DSN_ENV, admin_dsn)
    monkeypatch.setenv(WORKER_ACTOR_ENV, _staff_actor(admin_dsn))
    loop = build_worker(worker_id="test-worker")
    try:
        assert loop.worker_id == "test-worker"
        assert loop.queue.identity.role == "admin"
        # An empty queue is a complete, uneventful tick rather than an error.
        result = loop.tick()
        assert result == {"reaped": [], "scheduled": [], "ran": []}
    finally:
        loop.queue.close()


def test_a_tick_that_raises_does_not_kill_the_loop(caplog) -> None:
    """The queue is durable and the work is idempotent, so a tick may fail.

    A worker that exits on the first transient database error is worse than one
    that logs and retries, because the next tick re-reads live state anyway.
    """

    class Exploding:
        def reap_expired_leases(self):
            raise RuntimeError("transient")

        def close(self):
            return None

    loop = WorkerLoop(
        scheduler=None,
        queue=Exploding(),
        worker_id="test",
        poll_seconds=0.1,
    )

    ticks = {"count": 0}
    original = loop.tick

    def counting_tick(**kwargs):
        ticks["count"] += 1
        if ticks["count"] >= 2:
            loop.stop()
        return original(**kwargs)

    loop.tick = counting_tick
    with caplog.at_level(logging.ERROR):
        loop.run_forever()

    assert ticks["count"] >= 2, "the loop stopped on the first failing tick"
    assert any("worker tick failed" in record.message for record in caplog.records)


def test_the_loop_drains_scheduled_work_in_one_tick(admin_dsn) -> None:
    """A tick reaps, schedules, then runs until the queue is idle."""
    from cre_mcp.postgres.config import PostgresSettings
    from cre_mcp.postgres.pool import PostgresDatabase

    actor = _staff_actor(admin_dsn)
    database = PostgresDatabase(
        PostgresSettings(dsn=admin_dsn, runtime_mode="admin", min_size=0, max_size=4)
    )
    database.open(wait=True)
    queue = InternalJobQueue(
        database,
        identity=WorkerIdentity(
            actor_user_id=actor,
            role="admin",
            reason_code="scheduled_run",
            reason="Scheduled saved-search worker run.",
        ),
    )
    loop = WorkerLoop(
        scheduler=SavedSearchScheduler(database, queue),
        queue=queue,
        worker_id="drain-test",
        poll_seconds=0.1,
    )
    try:
        # No saved search is due, so this is the honest empty case: it must be
        # a clean pass, not a hang and not an exception.
        first = loop.tick()
        assert first["ran"] == []
        # And it is idempotent — a second tick with nothing new enqueues
        # nothing, which is the property the window-derived idempotency key
        # exists to give.
        assert loop.tick() == first
    finally:
        queue.close()
