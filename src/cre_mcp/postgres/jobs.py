"""The hosted background job engine and its customer-facing boundary.

Two things live here, and the split is the point.

``PostgresJobRepository`` is the request-scoped port that fills
``HostedRequestRepositories.job``. It is reachable from a customer tool call, so
it is built exactly like ``postgres/searches.py``: one exact admission, the
``_require_active_scope`` guard, ``hmac.compare_digest`` against the admission on
every comparison, decode-and-verify on read, one opaque failure message.

Its ``_METHOD_TOOLS`` is **empty, deliberately**. There is no customer-facing MCP
capability for scheduling anything: ``src/cre_mcp/access/capability_matrix.json``
has ``check_alerts``, which is pull-only and on-demand, and nothing else touches
this domain. So every customer-request-scoped call raises
``JobPersistenceUnavailable`` — not because the SQL is missing, but because no
tool maps to it. The methods below are real and are exercised end to end in
``tests/postgres/test_job_repository.py``; the mapping is the only thing standing
between them and a caller, which is what "fail closed" means here as opposed to
"unimplemented".

There is a second, independent refusal underneath: ``medawarcre_app`` holds **no
grant at all** on ``medawarcre.jobs`` or ``medawarcre.job_attempts``. Migration
0001 grants both relations to ``medawarcre_admin`` only, and
``restore_privileges.sql`` agrees. So even a mapping mistake here would meet a
PostgreSQL privilege error before it met a row-level-security policy. That is
recorded rather than relied upon: a capability that is later added would need a
migration to grant the app role, and adding one is a decision, not an oversight.

``InternalJobQueue`` and ``SavedSearchScheduler`` are the real engine, and they
are deliberately **not** bundle fields — the same boundary
``postgres/opportunity_index.py`` draws. They run on the ``admin`` runtime with
an internal ``AuthorityContext``, which fails closed three ways: ``medawarcre_app``
holds no grant on these relations, the app pool refuses internal authority, and
``internal_authorized()`` requires a live staff role plus a non-blank audit
reason.

Delivery and notification are out of scope by instruction; the engine is complete
without them. ``SavedSearchScheduler.run_once`` performs the two rechecks the
launch requires and records the outcome, and hands off to an injected executor
when one is supplied.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import UUID

import psycopg

from cre_mcp.access.context import TenantContext, current_context
from cre_mcp.access.engine import location_value_within_territories
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.domains import (
    current_hosted_request_repositories,
    require_fresh_admission,
)
from cre_mcp.postgres.pool import INTERNAL_ROLES, AuthorityContext, PostgresDatabase

_UNAVAILABLE = "job persistence unavailable"

# Empty on purpose. See the module docstring: no customer-facing capability
# schedules anything today, so no tool may reach this domain. Adding a key here
# without a matching capability in `capability_matrix.json` would open a port
# that no access decision covers.
_METHOD_TOOLS: dict[str, frozenset[str]] = {}

JOB_KINDS = frozenset({"saved_search", "privacy", "provider_reconcile", "retention"})
JOB_STATUSES = frozenset(
    {"queued", "leased", "running", "succeeded", "failed", "canceled"}
)
MUTATING_ROLES = frozenset({"owner", "admin"})
REASON_CODES = frozenset(
    {
        "scheduled_run",
        "queue_maintenance",
        "pipeline_review",
        "incident_response",
        "retention",
    }
)

# The scheduling vocabulary. `saved_searches.schedule` is free text in the
# schema and nothing else in the program writes it, so this module is what
# gives it meaning. Each value names the window the deduplication key is
# derived from, which is the whole deduplication mechanism.
SCHEDULE_WINDOWS = ("hourly", "daily", "weekly")

_MAX_CLAIM = 100
_MAX_LEASE_SECONDS = 3_600
_BACKOFF_BASE_SECONDS = 30.0
_MAX_BACKOFF_SECONDS = 3_600.0

# The refusal vocabulary `run_once` records. Every one of these is a terminal
# `canceled`, never a retry: a job whose workspace lost entitlement between
# enqueue and run does not become entitled by being retried, and a job retried
# into success would be exactly the leak the recheck exists to prevent.
REFUSAL_CODES = frozenset(
    {
        "entitlement_missing_or_expired",
        "plan_missing_or_invalid",
        "territory_not_granted",
        "saved_search_missing",
        "saved_search_inactive",
        "workspace_not_admissible",
    }
)


class JobPersistenceUnavailable(RuntimeError):
    """The exact hosted job persistence boundary cannot complete safely."""


class InternalJobQueueUnavailable(RuntimeError):
    """The internal job queue boundary cannot complete safely."""


class JobLeaseLost(RuntimeError):
    """A worker tried to write a result it no longer holds the lease for."""


async def _finish_thread_before_cancellation(function: Any, *args: Any) -> Any:
    """Keep the synchronous database worker inside its request lease."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        try:
            task.result()
        except Exception:
            pass
        raise


def _uuid(value: object) -> str:
    if not isinstance(value, (str, UUID)):
        raise ValueError("invalid job identifier")
    try:
        selected = str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("invalid job identifier") from error
    if isinstance(value, str) and value != selected:
        raise ValueError("invalid job identifier")
    return selected


def _text(value: object, *, maximum: int, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value) > maximum
    ):
        raise ValueError("invalid job text")
    return value


def _payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("invalid job payload")
    for key in value:
        if not isinstance(key, str):
            raise ValueError("invalid job payload")
    encoded = json.dumps(
        value, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if len(encoded) > 16_384:
        raise ValueError("invalid job payload")
    return json.loads(encoded.decode("utf-8"))


def _positive_integer(value: object, *, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("invalid job bound")
    return value


def _seconds(value: object, *, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid job interval")
    selected = float(value)
    if not math.isfinite(selected) or not 0 < selected <= maximum:
        raise ValueError("invalid job interval")
    return selected


def _moment(value: object, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("invalid job timestamp")
    return value.astimezone(UTC)


def _utc_text(value: object) -> str:
    moment = _moment(value)
    assert moment is not None
    return moment.isoformat()


def _nullable_utc_text(value: object) -> str | None:
    return None if value is None else _utc_text(value)


@dataclass(frozen=True)
class WorkerIdentity:
    """The reason-coded staff identity one internal queue operation runs under.

    ``InternalJobQueue`` needs this because the admin pool refuses a connection
    without an internal ``AuthorityContext``, and ``staff_audit_log``'s insert
    policy pins the row's ``actor_user_id``, ``actor_role`` and ``reason``
    against the same three settings. Making it explicit and required is what
    keeps the queue from acquiring an ambient identity nobody chose.
    """

    actor_user_id: str
    role: str
    reason_code: str
    reason: str

    def __post_init__(self) -> None:
        try:
            UUID(self.actor_user_id)
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("actor_user_id must be a UUID") from error
        if self.role not in INTERNAL_ROLES:
            raise ValueError(f"unsupported internal role: {self.role!r}")
        if self.reason_code not in REASON_CODES:
            raise ValueError(f"unsupported reason code: {self.reason_code!r}")
        if not isinstance(self.reason, str) or len(self.reason.strip()) < 3:
            raise ValueError("an internal job action requires a stated reason")

    @property
    def may_mutate(self) -> bool:
        return self.role in MUTATING_ROLES


@dataclass(frozen=True)
class JobRecord:
    """One row of ``medawarcre.jobs``, decoded and bounds-checked."""

    id: str
    workspace_id: str
    workspace_public_id: str
    saved_search_id: str | None
    kind: str
    payload: dict[str, Any]
    status: str
    idempotency_key: str
    attempt_count: int
    max_attempts: int
    next_run_at: str
    leased_until: str | None
    last_error_code: str | None
    created_at: str


@dataclass(frozen=True)
class QueueStatus:
    """What the internal Operations Console shows about the queue."""

    counts: dict[str, int]
    oldest_queued_age_seconds: float | None


@dataclass(frozen=True)
class Entitlement:
    """The workspace's live entitlement and territory grant, read at run time."""

    profile: str | None
    plan_key: str | None
    territories: tuple[str, ...]
    denial_reason: str | None

    @property
    def entitled(self) -> bool:
        return self.denial_reason is None


@dataclass(frozen=True)
class RunOutcome:
    """What one ``run_once`` call did."""

    job_id: str | None
    workspace_public_id: str | None
    saved_search_id: str | None
    outcome: str
    reason_code: str | None


_JOB_COLUMNS = (
    "job.id,workspace.id,workspace.public_id,job.saved_search_id,job.kind,"
    "job.payload,job.status,job.idempotency_key,job.attempt_count,"
    "job.max_attempts,job.next_run_at,job.leased_until,job.last_error_code,"
    "job.created_at"
)


def _decode_job(row: object) -> JobRecord:
    if not isinstance(row, tuple) or len(row) != 14:
        raise ValueError("invalid stored job")
    kind = _text(row[4], maximum=64) or ""
    status = _text(row[6], maximum=32) or ""
    if kind not in JOB_KINDS or status not in JOB_STATUSES:
        raise ValueError("invalid stored job")
    attempt_count = row[8]
    max_attempts = row[9]
    if (
        type(attempt_count) is not int
        or type(max_attempts) is not int
        or attempt_count < 0
        or max_attempts < 1
    ):
        raise ValueError("invalid stored job")
    return JobRecord(
        id=_uuid(row[0]),
        workspace_id=_uuid(row[1]),
        workspace_public_id=_text(row[2], maximum=256) or "",
        saved_search_id=None if row[3] is None else _uuid(row[3]),
        kind=kind,
        payload=_payload(row[5] if row[5] is not None else {}),
        status=status,
        idempotency_key=_text(row[7], maximum=512) or "",
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        next_run_at=_utc_text(row[10]),
        leased_until=_nullable_utc_text(row[11]),
        last_error_code=_text(row[12], maximum=128, nullable=True),
        created_at=_utc_text(row[13]),
    )


# ---------------------------------------------------------------------------
# The request-scoped bundle port.
# ---------------------------------------------------------------------------


class PostgresJobRepository:
    """Bind one actor's job reads and writes to one exact admission.

    Every method refuses today, because ``_METHOD_TOOLS`` is empty and no MCP
    capability schedules work. The SQL underneath is real, so the day a
    scheduling capability is designed, this port is the thing it plugs into
    rather than the thing it has to be written from scratch.
    """

    def __init__(
        self,
        database: PostgresDatabase,
        admission: AdmissionOutcome,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise TypeError("job repository requires PostgreSQL")
        self._database = database
        self._admission = require_fresh_admission(admission)

    def _require_active_scope(self, method: str) -> TenantContext:
        repositories = current_hosted_request_repositories()
        context = current_context()
        allowed_tools = _METHOD_TOOLS.get(method)
        if (
            repositories is None
            or repositories.admission is not self._admission
            or repositories.require("job") is not self
            or not isinstance(context, TenantContext)
            or context.trusted
            or not context.active
            or allowed_tools is None
            or self._admission.tool_name not in allowed_tools
        ):
            raise JobPersistenceUnavailable(_UNAVAILABLE)
        comparisons = (
            (context.workspace_id, self._admission.workspace_public_id),
            (context.actor_id, self._admission.actor_user_id),
            (context.session_id, self._admission.session_id),
        )
        if any(
            not left or not right or not hmac.compare_digest(left, right)
            for left, right in comparisons
        ):
            raise JobPersistenceUnavailable(_UNAVAILABLE)
        return context

    def _decode_row(self, row: object) -> dict[str, object]:
        record = _decode_job(row)
        if not hmac.compare_digest(
            record.workspace_public_id,
            self._admission.workspace_public_id,
        ):
            raise ValueError("invalid stored job")
        return {
            "id": record.id,
            "kind": record.kind,
            "status": record.status,
            "saved_search_id": record.saved_search_id,
            "attempt_count": record.attempt_count,
            "max_attempts": record.max_attempts,
            "next_run_at": record.next_run_at,
            "last_error_code": record.last_error_code,
            "created_at": record.created_at,
        }

    @staticmethod
    def _job_select() -> str:
        return (
            f"SELECT {_JOB_COLUMNS} FROM medawarcre.jobs job "
            "JOIN medawarcre.workspaces workspace ON workspace.id=job.workspace_id "
        )

    def _enqueue_saved_search_run(
        self,
        saved_search_id: str,
        idempotency_key: str,
    ) -> str:
        self._require_active_scope("enqueue_saved_search_run")
        selected_search = _uuid(saved_search_id)
        selected_key = _text(idempotency_key, maximum=512) or ""
        with self._database.admitted_connection(self._admission) as connection:
            connection.execute(
                "INSERT INTO medawarcre.jobs("
                "workspace_id,saved_search_id,kind,payload,idempotency_key,"
                "max_attempts,next_run_at) "
                "SELECT medawarcre.current_workspace_id(),search.id,"
                "'saved_search','{}'::jsonb,%s,5,statement_timestamp() "
                "FROM medawarcre.saved_searches search "
                "WHERE search.id=%s AND search.active "
                "ON CONFLICT (workspace_id, idempotency_key) DO NOTHING",
                (selected_key, selected_search),
            )
            row = connection.execute(
                self._job_select()
                + "WHERE job.workspace_id=medawarcre.current_workspace_id() "
                "AND job.idempotency_key=%s",
                (selected_key,),
            ).fetchone()
            if row is None:
                raise ValueError("invalid stored job")
            decoded = self._decode_row(row)
            self._require_active_scope("enqueue_saved_search_run")
        return str(decoded["id"])

    async def enqueue_saved_search_run(
        self,
        saved_search_id: str,
        *,
        idempotency_key: str,
    ) -> str:
        """Queue one run of one actor-owned saved search, idempotently."""
        try:
            self._require_active_scope("enqueue_saved_search_run")
            result = await _finish_thread_before_cancellation(
                self._enqueue_saved_search_run,
                saved_search_id,
                idempotency_key,
            )
            self._require_active_scope("enqueue_saved_search_run")
            return result
        except JobPersistenceUnavailable:
            raise
        except Exception as error:
            raise JobPersistenceUnavailable(_UNAVAILABLE) from error

    def _list_jobs(self) -> list[dict[str, object]]:
        self._require_active_scope("list_jobs")
        with self._database.admitted_connection(self._admission) as connection:
            rows = connection.execute(
                self._job_select()
                + "WHERE job.workspace_id=medawarcre.current_workspace_id() "
                "ORDER BY job.created_at,job.id"
            ).fetchall()
            result = [self._decode_row(row) for row in rows]
            self._require_active_scope("list_jobs")
        return result

    async def list_jobs(self) -> list[dict[str, object]]:
        """List this workspace's jobs, newest binding last."""
        try:
            self._require_active_scope("list_jobs")
            result = await _finish_thread_before_cancellation(self._list_jobs)
            self._require_active_scope("list_jobs")
            return result
        except JobPersistenceUnavailable:
            raise
        except Exception as error:
            raise JobPersistenceUnavailable(_UNAVAILABLE) from error


# ---------------------------------------------------------------------------
# The internal queue. Not a bundle field; not reachable from request scope.
# ---------------------------------------------------------------------------


class InternalJobQueue:
    """Staff-operated, reason-coded, audited background job queue.

    ``identity`` is keyword-only and required. The positional signature is the
    one the launch specified — ``(self, database)`` — but the admin pool refuses
    a connection without an internal ``AuthorityContext``, and inventing a
    default one inside this class would give the queue an actor nobody chose.
    """

    def __init__(
        self,
        database: PostgresDatabase,
        *,
        identity: WorkerIdentity,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise InternalJobQueueUnavailable("the job queue requires PostgreSQL")
        if database.settings.runtime_mode != "admin":
            raise InternalJobQueueUnavailable(
                "the internal job queue requires the admin runtime"
            )
        if not isinstance(identity, WorkerIdentity):
            raise InternalJobQueueUnavailable(
                "the internal job queue requires a staff identity"
            )
        self._database = database
        self._identity = identity

    @classmethod
    def for_dsn(cls, dsn: str, identity: WorkerIdentity) -> "InternalJobQueue":
        database = PostgresDatabase(
            PostgresSettings(dsn=dsn, runtime_mode="admin", min_size=0, max_size=4)
        )
        database.open(wait=True)
        return cls(database, identity=identity)

    def close(self) -> None:
        self._database.close()

    @property
    def identity(self) -> WorkerIdentity:
        return self._identity

    @property
    def database(self) -> PostgresDatabase:
        return self._database

    # -- internals ---------------------------------------------------------

    def authority(self) -> AuthorityContext:
        """The internal authority every queue statement runs under."""
        return AuthorityContext.internal(
            self._identity.actor_user_id,
            self._identity.role,
            self._identity.reason,
        )

    def _context(self) -> AuthorityContext:
        return self.authority()

    def _require_mutation(self) -> None:
        if not self._identity.may_mutate:
            raise PermissionError(
                f"role {self._identity.role!r} may read the job queue "
                "but not change it"
            )

    def audit(
        self,
        connection: psycopg.Connection,
        *,
        action: str,
        object_type: str,
        object_id: str,
        result: str,
        after: dict[str, Any] | None = None,
    ) -> None:
        """Write one ``staff_audit_log`` row in the caller's transaction.

        ``workspace_id`` is deliberately left NULL and the workspace carried in
        ``after_data`` instead. ``staff_audit_log.workspace_id`` is a foreign key
        with no ``ON DELETE`` action, so linking it makes the workspace
        permanently undeletable — a customer's erasure request would be blocked
        by the record of a scheduled job that ran against them. The internal
        opportunity index reached the same conclusion for the same reason.
        """
        connection.execute(
            "INSERT INTO medawarcre.staff_audit_log("
            "actor_user_id,actor_role,reason,reason_code,workspace_id,"
            "object_type,object_id,action,result,after_data) "
            "VALUES (%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s::jsonb)",
            (
                self._identity.actor_user_id,
                self._identity.role,
                self._identity.reason,
                self._identity.reason_code,
                object_type,
                object_id,
                action,
                result,
                json.dumps(after or {}, allow_nan=False, separators=(",", ":")),
            ),
        )

    # -- enqueue -----------------------------------------------------------

    def enqueue(
        self,
        workspace_public_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        max_attempts: int = 5,
        next_run_at: datetime | None = None,
        saved_search_id: str | None = None,
    ) -> JobRecord:
        """Queue one job, or return the one this key already queued.

        Idempotent on ``(workspace_id, idempotency_key)``, which the schema
        already declares unique. ``ON CONFLICT DO NOTHING`` followed by a read in
        the same transaction is what makes a concurrent second call return the
        first call's row rather than raising: under READ COMMITTED the loser of
        the race blocks on the winner's speculative index entry, and by the time
        the follow-up select runs the winner has committed.
        """
        self._require_mutation()
        selected_public = _text(workspace_public_id, maximum=256)
        selected_kind = _text(kind, maximum=64)
        if selected_kind not in JOB_KINDS:
            raise ValueError(f"unsupported job kind: {kind!r}")
        selected_payload = _payload(payload)
        selected_key = _text(idempotency_key, maximum=512)
        selected_max = _positive_integer(max_attempts, maximum=100)
        selected_moment = _moment(next_run_at, nullable=True)
        selected_search = None if saved_search_id is None else _uuid(saved_search_id)
        with self._database.connection(self._context()) as connection:
            connection.execute(
                "INSERT INTO medawarcre.jobs("
                "workspace_id,saved_search_id,kind,payload,idempotency_key,"
                "max_attempts,next_run_at) "
                "SELECT workspace.id,%s,%s,%s::jsonb,%s,%s,"
                "COALESCE(%s::timestamptz,statement_timestamp()) "
                "FROM medawarcre.workspaces workspace "
                "WHERE workspace.public_id=%s "
                "ON CONFLICT (workspace_id, idempotency_key) DO NOTHING",
                (
                    selected_search,
                    selected_kind,
                    json.dumps(
                        selected_payload, allow_nan=False, separators=(",", ":")
                    ),
                    selected_key,
                    selected_max,
                    selected_moment,
                    selected_public,
                ),
            )
            row = connection.execute(
                f"SELECT {_JOB_COLUMNS} FROM medawarcre.jobs job "
                "JOIN medawarcre.workspaces workspace "
                "ON workspace.id=job.workspace_id "
                "WHERE workspace.public_id=%s AND job.idempotency_key=%s",
                (selected_public, selected_key),
            ).fetchone()
            if row is None:
                raise LookupError("no such workspace")
            return _decode_job(row)

    # -- claim -------------------------------------------------------------

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: float,
        limit: int = 1,
        now: datetime | None = None,
        kind: str | None = None,
    ) -> tuple[JobRecord, ...]:
        """Atomically lease due queued jobs, one attempt row per lease.

        ``FOR UPDATE SKIP LOCKED`` over ``jobs_claim_idx`` is what makes two
        workers claiming at the same instant return disjoint sets: the loser does
        not block and does not see the row, it simply takes the next one.

        ``attempt_count < max_attempts`` is part of the candidate predicate, not
        only of ``fail``. A job returned to ``queued`` by ``reap_expired_leases``
        would otherwise be claimable forever, since nothing on the reap path
        consults the attempt bound.
        """
        self._require_mutation()
        selected_worker = _text(worker_id, maximum=128)
        selected_lease = _seconds(lease_seconds, maximum=_MAX_LEASE_SECONDS)
        selected_limit = _positive_integer(limit, maximum=_MAX_CLAIM)
        selected_now = _moment(now, nullable=True)
        selected_kind = None if kind is None else _text(kind, maximum=64)
        if selected_kind is not None and selected_kind not in JOB_KINDS:
            raise ValueError(f"unsupported job kind: {kind!r}")
        with self._database.connection(self._context()) as connection:
            # Every column the caller receives comes out of the `leased` CTE's
            # RETURNING, never out of a fresh read of `medawarcre.jobs`. All
            # CTEs share the statement's snapshot, so re-reading the table here
            # would hand back the pre-claim row: status 'queued' and the
            # un-incremented attempt count, on a job this call just leased.
            rows = connection.execute(
                "WITH moment AS ("
                "  SELECT COALESCE(%s::timestamptz,statement_timestamp()) AS now"
                "),"
                "candidate AS ("
                "  SELECT job.id FROM medawarcre.jobs job, moment"
                "  WHERE job.status='queued'"
                "    AND job.next_run_at <= moment.now"
                "    AND job.attempt_count < job.max_attempts"
                "    AND (%s::text IS NULL OR job.kind = %s)"
                "  ORDER BY job.next_run_at, job.created_at"
                "  LIMIT %s"
                "  FOR UPDATE SKIP LOCKED"
                "),"
                "leased AS ("
                "  UPDATE medawarcre.jobs job"
                "  SET status='leased',"
                "      lease_owner=%s,"
                "      leased_until=moment.now + make_interval(secs => %s),"
                "      attempt_count=job.attempt_count+1,"
                "      updated_at=statement_timestamp()"
                "  FROM candidate, moment"
                "  WHERE job.id=candidate.id"
                "  RETURNING job.id, job.workspace_id, job.saved_search_id,"
                "            job.kind, job.payload, job.status,"
                "            job.idempotency_key, job.attempt_count,"
                "            job.max_attempts, job.next_run_at,"
                "            job.leased_until, job.last_error_code,"
                "            job.created_at"
                "),"
                "attempt AS ("
                "  INSERT INTO medawarcre.job_attempts("
                "    workspace_id,job_id,attempt_number,worker_id,status)"
                "  SELECT leased.workspace_id, leased.id, leased.attempt_count,"
                "         %s, 'running' FROM leased"
                "  RETURNING job_id"
                ") "
                "SELECT leased.id, workspace.id, workspace.public_id,"
                " leased.saved_search_id, leased.kind, leased.payload,"
                " leased.status, leased.idempotency_key, leased.attempt_count,"
                " leased.max_attempts, leased.next_run_at, leased.leased_until,"
                " leased.last_error_code, leased.created_at "
                "FROM leased JOIN medawarcre.workspaces workspace "
                "ON workspace.id=leased.workspace_id "
                "WHERE leased.id IN (SELECT job_id FROM attempt) "
                "ORDER BY leased.id",
                (
                    selected_now,
                    selected_kind,
                    selected_kind,
                    selected_limit,
                    selected_worker,
                    selected_lease,
                    selected_worker,
                ),
            ).fetchall()
            return tuple(_decode_job(row) for row in rows)

    # -- terminal transitions ---------------------------------------------

    def _release(
        self,
        connection: psycopg.Connection,
        statement: str,
        parameters: tuple[Any, ...],
    ) -> tuple[Any, ...]:
        row = connection.execute(statement, parameters).fetchone()
        if row is None:
            # The lease is gone: expired, reaped, or held by another worker.
            # Raising here rolls the transaction back, so a worker whose lease
            # expired writes nothing at all rather than a stale result.
            raise JobLeaseLost("the job lease is no longer held by this worker")
        return row

    def _close_attempt(
        self,
        connection: psycopg.Connection,
        *,
        workspace_id: str,
        job_id: str,
        attempt_number: int,
        status: str,
        error_code: str | None,
        now: datetime | None,
    ) -> None:
        row = connection.execute(
            # GREATEST, not the supplied clock. `job_attempts` carries
            # `completed_at >= started_at`, and `started_at` is the real
            # statement clock from the claim. A caller supplying its own `now`
            # — every scheduler run does, and so does every test that moves time
            # — would otherwise abort the whole transition on a check violation
            # whenever its clock trailed the claim by so much as a microsecond.
            "UPDATE medawarcre.job_attempts "
            "SET status=%s, error_code=%s,"
            " completed_at=GREATEST(started_at,"
            "  COALESCE(%s::timestamptz,statement_timestamp())) "
            "WHERE workspace_id=%s AND job_id=%s AND attempt_number=%s "
            "AND status='running' RETURNING id",
            (status, error_code, now, workspace_id, job_id, attempt_number),
        ).fetchone()
        if row is None:
            raise JobLeaseLost("the job attempt is no longer open")

    def complete(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: datetime | None = None,
        hook: Callable[[psycopg.Connection], None] | None = None,
    ) -> None:
        """Record success, only while this worker still holds a live lease.

        ``hook`` runs inside the same transaction as the transition, which is
        how the scheduler's audit row commits or rolls back with the state
        change it describes rather than beside it.
        """
        self._require_mutation()
        selected_job = _uuid(job_id)
        selected_worker = _text(worker_id, maximum=128)
        selected_now = _moment(now, nullable=True)
        with self._database.connection(self._context()) as connection:
            row = self._release(
                connection,
                "UPDATE medawarcre.jobs "
                "SET status='succeeded', lease_owner=NULL, leased_until=NULL,"
                " updated_at=statement_timestamp() "
                "WHERE id=%s AND status='leased' AND lease_owner=%s "
                "AND leased_until > COALESCE(%s::timestamptz,statement_timestamp()) "
                "RETURNING workspace_id, attempt_count",
                (selected_job, selected_worker, selected_now),
            )
            self._close_attempt(
                connection,
                workspace_id=str(row[0]),
                job_id=selected_job,
                attempt_number=int(row[1]),
                status="succeeded",
                error_code=None,
                now=selected_now,
            )
            if hook is not None:
                hook(connection)

    def fail(
        self,
        job_id: str,
        worker_id: str,
        error_code: str,
        *,
        now: datetime | None = None,
        hook: Callable[[psycopg.Connection], None] | None = None,
    ) -> JobRecord:
        """Record failure: re-queue with backoff, or go terminal at the limit."""
        self._require_mutation()
        selected_job = _uuid(job_id)
        selected_worker = _text(worker_id, maximum=128)
        selected_code = _text(error_code, maximum=128)
        selected_now = _moment(now, nullable=True)
        with self._database.connection(self._context()) as connection:
            row = self._release(
                connection,
                "WITH moment AS ("
                "  SELECT COALESCE(%s::timestamptz,statement_timestamp()) AS now"
                ") "
                "UPDATE medawarcre.jobs job "
                "SET status=CASE WHEN job.attempt_count < job.max_attempts "
                "  THEN 'queued' ELSE 'failed' END,"
                " lease_owner=NULL, leased_until=NULL, last_error_code=%s,"
                " next_run_at=CASE WHEN job.attempt_count < job.max_attempts "
                "  THEN moment.now + make_interval(secs => LEAST(%s,"
                "    %s * power(2, job.attempt_count - 1)::double precision)) "
                "  ELSE job.next_run_at END,"
                " updated_at=statement_timestamp() "
                "FROM moment "
                "WHERE job.id=%s AND job.status='leased' AND job.lease_owner=%s "
                "AND job.leased_until > moment.now "
                "RETURNING job.workspace_id, job.attempt_count",
                (
                    selected_now,
                    selected_code,
                    _MAX_BACKOFF_SECONDS,
                    _BACKOFF_BASE_SECONDS,
                    selected_job,
                    selected_worker,
                ),
            )
            self._close_attempt(
                connection,
                workspace_id=str(row[0]),
                job_id=selected_job,
                attempt_number=int(row[1]),
                status="failed",
                error_code=selected_code,
                now=selected_now,
            )
            if hook is not None:
                hook(connection)
            return _decode_job(
                connection.execute(
                    f"SELECT {_JOB_COLUMNS} FROM medawarcre.jobs job "
                    "JOIN medawarcre.workspaces workspace "
                    "ON workspace.id=job.workspace_id WHERE job.id=%s",
                    (selected_job,),
                ).fetchone()
            )

    def refuse(
        self,
        job_id: str,
        worker_id: str,
        reason_code: str,
        *,
        now: datetime | None = None,
        hook: Callable[[psycopg.Connection], None] | None = None,
    ) -> None:
        """Close a job the gates refused: terminal ``canceled``, never retried.

        A refusal is not a failure. Re-queuing it would ask the same question
        again and, if the answer ever changed, run work the caller was not
        entitled to when the job was enqueued *and* was not entitled to when the
        recheck refused it. ``canceled`` is the schema's word for "this will not
        run", and the reason lands on ``last_error_code``.
        """
        self._require_mutation()
        if reason_code not in REFUSAL_CODES:
            raise ValueError(f"unsupported refusal code: {reason_code!r}")
        selected_job = _uuid(job_id)
        selected_worker = _text(worker_id, maximum=128)
        selected_now = _moment(now, nullable=True)
        with self._database.connection(self._context()) as connection:
            row = self._release(
                connection,
                "UPDATE medawarcre.jobs "
                "SET status='canceled', lease_owner=NULL, leased_until=NULL,"
                " last_error_code=%s, updated_at=statement_timestamp() "
                "WHERE id=%s AND status='leased' AND lease_owner=%s "
                "AND leased_until > COALESCE(%s::timestamptz,statement_timestamp()) "
                "RETURNING workspace_id, attempt_count",
                (reason_code, selected_job, selected_worker, selected_now),
            )
            self._close_attempt(
                connection,
                workspace_id=str(row[0]),
                job_id=selected_job,
                attempt_number=int(row[1]),
                status="failed",
                error_code=reason_code,
                now=selected_now,
            )
            if hook is not None:
                hook(connection)

    # -- maintenance -------------------------------------------------------

    def reap_expired_leases(self, now: datetime | None = None) -> tuple[str, ...]:
        """Return leased jobs whose lease has passed and abandon their attempt."""
        self._require_mutation()
        selected_now = _moment(now, nullable=True)
        with self._database.connection(self._context()) as connection:
            rows = connection.execute(
                "WITH moment AS ("
                "  SELECT COALESCE(%s::timestamptz,statement_timestamp()) AS now"
                "),"
                "expired AS ("
                "  UPDATE medawarcre.jobs job"
                "  SET status='queued', lease_owner=NULL, leased_until=NULL,"
                "      updated_at=statement_timestamp()"
                "  FROM moment"
                "  WHERE job.status='leased' AND job.leased_until <= moment.now"
                "  RETURNING job.id, job.workspace_id, job.attempt_count"
                "),"
                "abandoned AS ("
                "  UPDATE medawarcre.job_attempts attempt"
                "  SET status='abandoned',"
                "      completed_at=GREATEST(attempt.started_at, moment.now)"
                "  FROM expired, moment"
                "  WHERE attempt.workspace_id=expired.workspace_id"
                "    AND attempt.job_id=expired.id"
                "    AND attempt.attempt_number=expired.attempt_count"
                "    AND attempt.status='running'"
                "  RETURNING attempt.job_id"
                ") "
                "SELECT expired.id FROM expired ORDER BY expired.id",
                (selected_now,),
            ).fetchall()
            return tuple(_uuid(row[0]) for row in rows)

    def status(self, workspace_public_id: str | None = None) -> QueueStatus:
        """Counts by status plus the oldest queued age, for the console."""
        selected_public = (
            None
            if workspace_public_id is None
            else _text(workspace_public_id, maximum=256)
        )
        with self._database.connection(self._context()) as connection:
            rows = connection.execute(
                "SELECT job.status, count(*) FROM medawarcre.jobs job "
                "JOIN medawarcre.workspaces workspace "
                "ON workspace.id=job.workspace_id "
                "WHERE (%s::text IS NULL OR workspace.public_id=%s) "
                "GROUP BY job.status ORDER BY job.status COLLATE \"C\"",
                (selected_public, selected_public),
            ).fetchall()
            oldest = connection.execute(
                "SELECT EXTRACT(EPOCH FROM "
                "(statement_timestamp() - min(job.created_at)))::double precision "
                "FROM medawarcre.jobs job "
                "JOIN medawarcre.workspaces workspace "
                "ON workspace.id=job.workspace_id "
                "WHERE job.status='queued' "
                "AND (%s::text IS NULL OR workspace.public_id=%s)",
                (selected_public, selected_public),
            ).fetchone()
        counts = {status: 0 for status in sorted(JOB_STATUSES)}
        for row in rows:
            name = _text(row[0], maximum=32) or ""
            if name not in JOB_STATUSES or type(row[1]) is not int:
                raise ValueError("invalid stored job")
            counts[name] = row[1]
        age = None if oldest is None or oldest[0] is None else float(oldest[0])
        return QueueStatus(counts=counts, oldest_queued_age_seconds=age)


# ---------------------------------------------------------------------------
# The scheduler.
# ---------------------------------------------------------------------------


def _window_start(moment: datetime, schedule: str) -> datetime:
    """The start of the scheduling window ``moment`` falls in.

    This is the deduplication mechanism. Two ``schedule_due`` calls inside one
    window derive the same key, meet the unique index on
    ``(workspace_id, idempotency_key)``, and enqueue nothing the second time.
    """
    aligned = moment.astimezone(UTC)
    if schedule == "hourly":
        return aligned.replace(minute=0, second=0, microsecond=0)
    if schedule == "daily":
        return aligned.replace(hour=0, minute=0, second=0, microsecond=0)
    if schedule == "weekly":
        midnight = aligned.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(days=midnight.weekday())
    raise ValueError(f"unsupported schedule: {schedule!r}")


def saved_search_idempotency_key(saved_search_id: str, window: datetime) -> str:
    """The key that makes one saved search produce one job per window."""
    return f"saved_search:{_uuid(saved_search_id)}:{window.isoformat()}"


_ENTITLEMENT_QUERY = """
WITH target AS (
    SELECT workspace.id AS workspace_id,
           workspace.state AS workspace_state,
           membership.state AS membership_state,
           user_record.state AS user_state,
           account.state AS account_state
    FROM medawarcre.workspaces workspace
    JOIN medawarcre.memberships membership
      ON membership.workspace_id = workspace.id
     AND membership.user_id = %(actor)s
    JOIN medawarcre.users user_record
      ON user_record.id = membership.user_id
    LEFT JOIN medawarcre.workspace_accounts account
      ON account.workspace_id = workspace.id
    WHERE workspace.id = %(workspace)s
),
valid_grant AS (
    SELECT access_grant.id,
           access_grant.profile,
           access_grant.plan_key,
           access_grant.updated_at,
           CASE access_grant.profile
               WHEN 'full_operator' THEN 4
               WHEN 'national_scout' THEN 3
               WHEN 'local_scout' THEN 2
               WHEN 'jv_partner' THEN 1
               ELSE 0
           END AS profile_rank
    FROM medawarcre.access_grants access_grant
    JOIN target ON target.workspace_id = access_grant.workspace_id
    WHERE access_grant.status IN ('active', 'overridden', 'expiring')
      AND access_grant.source IN ('stripe', 'skool', 'manual', 'jv', 'promotion')
      AND access_grant.starts_at <= %(now)s
      AND (access_grant.ends_at IS NULL OR access_grant.ends_at > %(now)s)
      AND (access_grant.source NOT IN ('stripe', 'skool')
           OR access_grant.ends_at IS NOT NULL)
      AND ((access_grant.scope = 'workspace'
            AND access_grant.source = 'jv'
            AND access_grant.subject_user_id IS NULL)
        OR (access_grant.scope = 'subject'
            AND access_grant.subject_user_id = %(actor)s))
),
selected_grant AS (
    SELECT valid_grant.*
    FROM valid_grant
    ORDER BY valid_grant.profile_rank DESC,
             valid_grant.updated_at DESC,
             valid_grant.id DESC
    LIMIT 1
),
selected_plan AS (
    SELECT plan.id,
           plan.active,
           NOT EXISTS (
               SELECT 1
               FROM pg_catalog.jsonb_each(plan.daily_quotas) quota
               WHERE length(btrim(quota.key)) = 0
                  OR pg_catalog.jsonb_typeof(quota.value) <> 'number'
                  OR quota.value::text !~ '^(0|[1-9][0-9]*)$'
           ) AS quotas_valid
    FROM selected_grant
    LEFT JOIN medawarcre.plans plan
      ON plan.plan_key = selected_grant.plan_key
),
territory_summary AS (
    SELECT array_agg(territory_value.value ORDER BY territory_value.first_id)
               AS territories
    FROM (
        SELECT btrim(COALESCE(territory.state_code,
                              territory.market,
                              territory.name)) AS value,
               min(territory.id::text) AS first_id
        FROM medawarcre.territories territory
        JOIN target ON target.workspace_id = territory.workspace_id
        WHERE length(btrim(COALESCE(territory.state_code,
                                    territory.market,
                                    territory.name))) > 0
        GROUP BY btrim(COALESCE(territory.state_code,
                                territory.market,
                                territory.name))
    ) territory_value
)
SELECT selected_grant.profile,
       selected_grant.plan_key,
       COALESCE(territory_summary.territories, ARRAY[]::text[]),
       CASE
           WHEN target.user_state <> 'active'
               THEN 'workspace_not_admissible'
           WHEN target.workspace_state NOT IN ('active', 'past_due')
               THEN 'workspace_not_admissible'
           WHEN target.membership_state <> 'active'
               THEN 'workspace_not_admissible'
           WHEN target.account_state IS NULL
               THEN 'workspace_not_admissible'
           WHEN target.account_state NOT IN
                ('active', 'past_due', 'grace_period')
               THEN 'workspace_not_admissible'
           WHEN selected_grant.id IS NULL
               THEN 'entitlement_missing_or_expired'
           WHEN selected_grant.plan_key IS NULL
                OR selected_plan.id IS NULL
                OR NOT selected_plan.active
                OR NOT selected_plan.quotas_valid
               THEN 'plan_missing_or_invalid'
           ELSE NULL
       END AS denial_reason
FROM target
LEFT JOIN selected_grant ON true
LEFT JOIN selected_plan ON true
LEFT JOIN territory_summary ON true
"""


class SavedSearchScheduler:
    """Turn due saved searches into jobs, and run one job at a time.

    The entitlement and territory rechecks are the reason this class exists at
    all. A job carries whatever the workspace was entitled to when it was
    enqueued, and that value is worthless by the time a worker picks it up: a
    subscription lapses, a grant is revoked, a territory is narrowed. Both
    rechecks read the **live** row, and both refuse terminally.
    """

    def __init__(
        self,
        database: PostgresDatabase,
        queue: InternalJobQueue,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise InternalJobQueueUnavailable("the scheduler requires PostgreSQL")
        if database.settings.runtime_mode != "admin":
            raise InternalJobQueueUnavailable(
                "the saved-search scheduler requires the admin runtime"
            )
        if not isinstance(queue, InternalJobQueue):
            raise InternalJobQueueUnavailable(
                "the saved-search scheduler requires the internal queue"
            )
        self._database = database
        self._queue = queue

    # -- entitlement and territory, read live ------------------------------

    def entitlement(
        self,
        connection: psycopg.Connection,
        *,
        workspace_id: str,
        actor_user_id: str,
        now: datetime | None = None,
    ) -> Entitlement:
        """Resolve the workspace's current entitlement and territory grant.

        The predicates are lifted from
        ``medawarcre.resolve_bearer_authority`` in migration 0002 — the same
        grant statuses, the same sources, the same profile ranking, the same
        plan validity, the same territory projection. That function is keyed on
        a bearer token hash, and a background job has no bearer token, so the
        rules are re-expressed against ``(workspace, owner)`` rather than
        re-invented: a job must not be able to run under a laxer rule than a
        live request would get.
        """
        row = connection.execute(
            _ENTITLEMENT_QUERY,
            {
                "workspace": workspace_id,
                "actor": actor_user_id,
                "now": _moment(now, nullable=True) or datetime.now(UTC),
            },
        ).fetchone()
        if row is None:
            return Entitlement(
                profile=None,
                plan_key=None,
                territories=(),
                denial_reason="workspace_not_admissible",
            )
        territories = tuple(
            str(item) for item in (row[2] or ()) if isinstance(item, str)
        )
        return Entitlement(
            profile=None if row[0] is None else str(row[0]),
            plan_key=None if row[1] is None else str(row[1]),
            territories=territories,
            denial_reason=None if row[3] is None else str(row[3]),
        )

    # -- scheduling --------------------------------------------------------

    def schedule_due(self, now: datetime | None = None) -> tuple[str, ...]:
        """Enqueue one job per due saved search per window; return the job ids.

        Running this twice inside one window enqueues nothing the second time,
        because the key is derived from the window rather than from the clock.
        """
        moment = _moment(now, nullable=True) or datetime.now(UTC)
        with self._database.connection(self._queue.authority()) as connection:
            rows = connection.execute(
                "SELECT search.id, workspace.public_id, search.schedule "
                "FROM medawarcre.saved_searches search "
                "JOIN medawarcre.workspaces workspace "
                "ON workspace.id=search.workspace_id "
                "WHERE search.active AND search.schedule IS NOT NULL "
                "AND btrim(search.schedule) = ANY(%s) "
                "ORDER BY search.id",
                (list(SCHEDULE_WINDOWS),),
            ).fetchall()
        scheduled: list[str] = []
        for row in rows:
            saved_search_id = _uuid(row[0])
            workspace_public_id = _text(row[1], maximum=256) or ""
            schedule = (_text(row[2], maximum=64) or "").strip()
            window = _window_start(moment, schedule)
            record = self._queue.enqueue(
                workspace_public_id,
                "saved_search",
                {"saved_search_id": saved_search_id, "window": window.isoformat()},
                idempotency_key=saved_search_idempotency_key(
                    saved_search_id, window
                ),
                saved_search_id=saved_search_id,
                next_run_at=moment,
            )
            scheduled.append(record.id)
        return tuple(scheduled)

    # -- execution ---------------------------------------------------------

    def run_once(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 120.0,
        now: datetime | None = None,
        executor: Callable[[JobRecord, Entitlement], str] | None = None,
    ) -> RunOutcome:
        """Claim one job, recheck the gates, then run or refuse it.

        Order matters: both rechecks happen *before* any work, and either one
        failing closes the job as a refusal with a reason code. Nothing is
        retried into success and nothing is dropped silently — every path here
        writes exactly one ``staff_audit_log`` row.

        ``executor`` is where the actual saved-search run would go. Delivery and
        notification are an explicit staging integration and out of scope, so the
        default performs no external work; the engine is complete without it.
        """
        moment = _moment(now, nullable=True) or datetime.now(UTC)
        claimed = self._queue.claim(
            worker_id,
            lease_seconds=lease_seconds,
            limit=1,
            now=moment,
            kind="saved_search",
        )
        if not claimed:
            return RunOutcome(
                job_id=None,
                workspace_public_id=None,
                saved_search_id=None,
                outcome="idle",
                reason_code=None,
            )
        job = claimed[0]
        refusal = self._gate(job, moment)
        if isinstance(refusal, str):
            self._queue.refuse(
                job.id,
                worker_id,
                refusal,
                now=moment,
                hook=self._audit(job, result="denied", reason_code=refusal),
            )
            return RunOutcome(
                job_id=job.id,
                workspace_public_id=job.workspace_public_id,
                saved_search_id=job.saved_search_id,
                outcome="refused",
                reason_code=refusal,
            )
        try:
            reason_code = (
                "executed"
                if executor is None
                else _text(executor(job, refusal), maximum=128)
            )
        except Exception:
            self._queue.fail(
                job.id,
                worker_id,
                "execution_failed",
                now=moment,
                hook=self._audit(
                    job, result="failed", reason_code="execution_failed"
                ),
            )
            raise
        self._queue.complete(
            job.id,
            worker_id,
            now=moment,
            hook=self._audit(job, result="succeeded", reason_code=reason_code),
        )
        return RunOutcome(
            job_id=job.id,
            workspace_public_id=job.workspace_public_id,
            saved_search_id=job.saved_search_id,
            outcome="executed",
            reason_code=reason_code,
        )

    def _gate(self, job: JobRecord, moment: datetime) -> str | Entitlement:
        """Return a refusal code, or the live entitlement that permits the run."""
        with self._database.connection(self._queue.authority()) as connection:
            search = connection.execute(
                "SELECT search.owner_user_id, search.query, search.active "
                "FROM medawarcre.saved_searches search "
                "WHERE search.workspace_id=%s AND search.id=%s",
                (job.workspace_id, job.saved_search_id),
            ).fetchone()
            if search is None:
                return "saved_search_missing"
            if not search[2]:
                return "saved_search_inactive"
            entitlement = self.entitlement(
                connection,
                workspace_id=job.workspace_id,
                actor_user_id=_uuid(search[0]),
                now=moment,
            )
        if entitlement.denial_reason is not None:
            return entitlement.denial_reason
        query = search[1] if isinstance(search[1], dict) else {}
        location = query.get("location")
        # The access engine's own authority, over `cre_mcp.access.territory`.
        # Its docstring names "a persisted alert" as the case it exists for:
        # a service-layer workflow that does not pass back through FastMCP
        # middleware. That is exactly this. A second normalizer here would let
        # "may this workspace see this place" drift between the live request
        # path and the scheduled one.
        if not location_value_within_territories(
            location, entitlement.territories
        ):
            return "territory_not_granted"
        return entitlement

    def _audit(
        self,
        job: JobRecord,
        *,
        result: str,
        reason_code: str | None,
    ) -> Callable[[psycopg.Connection], None]:
        """Build the audit write for one run, to run inside its transaction."""

        def write(connection: psycopg.Connection) -> None:
            self._queue.audit(
                connection,
                action="run_job",
                object_type="job",
                object_id=job.id,
                result=result,
                after={
                    "workspace_public_id": job.workspace_public_id,
                    "kind": job.kind,
                    "saved_search_id": job.saved_search_id,
                    "attempt": job.attempt_count,
                    "reason_code": reason_code,
                },
            )

        return write


__all__ = [
    "Entitlement",
    "InternalJobQueue",
    "InternalJobQueueUnavailable",
    "JobLeaseLost",
    "JobPersistenceUnavailable",
    "JobRecord",
    "JOB_KINDS",
    "JOB_STATUSES",
    "PostgresJobRepository",
    "QueueStatus",
    "REASON_CODES",
    "REFUSAL_CODES",
    "RunOutcome",
    "SCHEDULE_WINDOWS",
    "SavedSearchScheduler",
    "WorkerIdentity",
    "saved_search_idempotency_key",
]
