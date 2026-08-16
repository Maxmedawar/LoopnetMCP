"""The background worker that makes scheduled saved searches actually run.

`InternalJobQueue` and `SavedSearchScheduler` are complete: idempotent enqueue,
`SKIP LOCKED` claiming, lease expiry, backoff, terminal failure, and a live
entitlement and territory recheck before any work. What was missing is the
thing that turns them from a library into a running product — a loop.

It is deliberately a separate process from the hosted MCP server. The server
answers requests and must not spend its time leasing jobs; the worker holds an
`admin` runtime connection the server does not have and should not have. They
share only the database.

Delivery is out of scope and stays out: `run_once` takes an optional executor
and the default performs no external work, so this loop is complete and useful
without a notification integration. What it does today is real — it enqueues
due searches exactly once per window, claims them one at a time, rechecks live
entitlement and territory, and records every outcome in the staff audit log.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass
from typing import Any

from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.jobs import (
    InternalJobQueue,
    SavedSearchScheduler,
    WorkerIdentity,
)
from cre_mcp.postgres.pool import PostgresDatabase

logger = logging.getLogger(__name__)

#: The environment variable holding the worker's own least-privilege DSN. It is
#: separate from the application's on purpose: the worker needs the `admin`
#: runtime, and the hosted server must never hold one.
WORKER_DSN_ENV = "MEDAWARCRE_WORKER_DATABASE_URL"
WORKER_ACTOR_ENV = "MEDAWARCRE_WORKER_ACTOR_USER_ID"

DEFAULT_POLL_SECONDS = 15.0
DEFAULT_LEASE_SECONDS = 120.0


class WorkerUnavailable(RuntimeError):
    """The worker cannot start with the identity and connection it needs."""


@dataclass
class WorkerLoop:
    """One scheduling-and-running loop, stoppable and individually testable."""

    scheduler: SavedSearchScheduler
    queue: InternalJobQueue
    worker_id: str
    poll_seconds: float = DEFAULT_POLL_SECONDS
    lease_seconds: float = DEFAULT_LEASE_SECONDS
    _stopping: bool = False

    def stop(self) -> None:
        self._stopping = True

    def tick(self, *, executor: Any = None) -> dict[str, Any]:
        """One full pass: reap, schedule, then drain what is due.

        Reaping runs first. A worker that died holding leases has jobs that
        cannot be claimed until their lease expires, and doing this before
        claiming means a restarted worker picks up its own abandoned work
        rather than waiting a lease period to notice.
        """
        reaped = self.queue.reap_expired_leases()
        scheduled = self.scheduler.schedule_due()
        ran: list[str] = []
        while not self._stopping:
            outcome = self.scheduler.run_once(
                self.worker_id,
                lease_seconds=self.lease_seconds,
                executor=executor,
            )
            if outcome.outcome == "idle":
                break
            ran.append(f"{outcome.job_id}:{outcome.outcome}")
        return {
            "reaped": list(reaped),
            "scheduled": list(scheduled),
            "ran": ran,
        }

    def run_forever(self, *, executor: Any = None) -> None:
        while not self._stopping:
            try:
                result = self.tick(executor=executor)
            except Exception:
                # A worker that exits on the first transient database error is
                # worse than one that logs and retries: the queue is durable,
                # the work is idempotent, and the next tick re-reads live state
                # anyway. The traceback is logged; no payload is.
                logger.exception("worker tick failed; retrying after the poll interval")
                result = None
            if result and (result["ran"] or result["scheduled"] or result["reaped"]):
                logger.info(
                    "worker tick: reaped=%d scheduled=%d ran=%d",
                    len(result["reaped"]),
                    len(result["scheduled"]),
                    len(result["ran"]),
                )
            for _ in range(max(int(self.poll_seconds * 10), 1)):
                if self._stopping:
                    return
                time.sleep(0.1)


def build_worker(
    *,
    dsn: str | None = None,
    actor_user_id: str | None = None,
    worker_id: str | None = None,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
) -> WorkerLoop:
    """Construct the loop from the environment a deployment injects."""
    resolved_dsn = (dsn or os.environ.get(WORKER_DSN_ENV, "")).strip()
    if not resolved_dsn:
        raise WorkerUnavailable(
            f"the worker requires {WORKER_DSN_ENV}"
        )
    resolved_actor = (actor_user_id or os.environ.get(WORKER_ACTOR_ENV, "")).strip()
    if not resolved_actor:
        # Refused rather than defaulted. Every queue mutation writes a
        # staff_audit_log row pinned to this identity, and a worker that
        # invented one would produce an audit trail naming nobody.
        raise WorkerUnavailable(
            f"the worker requires {WORKER_ACTOR_ENV}, the staff identity its "
            "audit rows are attributed to"
        )
    identity = WorkerIdentity(
        actor_user_id=resolved_actor,
        role="admin",
        reason_code="scheduled_run",
        reason="Scheduled saved-search worker run.",
    )
    database = PostgresDatabase(
        PostgresSettings(
            dsn=resolved_dsn, runtime_mode="admin", min_size=0, max_size=4
        )
    )
    database.open(wait=True)
    queue = InternalJobQueue(database, identity=identity)
    scheduler = SavedSearchScheduler(database, queue)
    return WorkerLoop(
        scheduler=scheduler,
        queue=queue,
        worker_id=worker_id or f"worker-{os.getpid()}",
        poll_seconds=poll_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    """`python -m cre_mcp.postgres.worker` — run the loop until signalled."""
    logging.basicConfig(level=logging.INFO)
    try:
        loop = build_worker()
    except WorkerUnavailable as error:
        # The message names variables, never values.
        logger.error("%s", error)
        return 1
    except Exception as error:
        logger.error("worker could not start (%s)", type(error).__name__)
        return 1

    def _stop(signum, frame):  # pragma: no cover - signal path
        loop.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        loop.run_forever()
    finally:
        loop.queue.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_POLL_SECONDS",
    "WORKER_ACTOR_ENV",
    "WORKER_DSN_ENV",
    "WorkerLoop",
    "WorkerUnavailable",
    "build_worker",
    "main",
]
