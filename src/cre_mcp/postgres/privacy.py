"""Privacy and retention persistence, on both sides of the customer boundary.

Two classes live here, and they are deliberately not symmetric.

``PostgresPrivacyRepository`` is the ``privacy`` field of
``HostedRequestRepositories`` — a request-scoped port bound to one exact
admission, built exactly like ``cre_mcp.postgres.searches``. Its
``_METHOD_TOOLS`` map is **empty**, and that is the design, not an omission:
``cre_mcp/access/capability_matrix.json`` declares no privacy, export, deletion
or retention capability anywhere in the customer surface, because customers get
connection-only browser access and no portal. A repository whose methods can
never be reached by any tool is the honest encoding of that decision, and the
guard refuses on the tool mapping rather than on missing SQL — the SQL is real,
and ``tests/postgres/test_privacy_repository.py`` proves it by supplying a tool
mapping and driving the same code end to end against the database. Fail-closed
and unimplemented look identical from the outside; that test is what tells them
apart, and it is why the methods are written rather than stubbed.

``InternalPrivacyDesk`` is how privacy requests are actually processed at
launch: internal staff, through the Operations Console. It is **not** a bundle
field, for the reason stated at the top of
``cre_mcp.postgres.opportunity_index`` — everything on the bundle is one
capability away from a customer. It reaches an ``admin``-runtime pool with an
internal ``AuthorityContext``, so it fails closed three ways: ``medawarcre_app``
cannot use the admin pool, the admin pool refuses tenant authority, and
``medawarcre.internal_authorized()`` requires a live staff role plus a non-blank
audit reason.

The desk does not import ``opportunity_index`` to reuse its ``_audit`` helper.
That helper is a private method of ``InternalOpportunityIndex``, and
``tests/postgres/test_opportunity_index.py`` pins a static rule that no module
outside ``cre_mcp/platform/`` may import that module at all — importing it from
here to save nine lines would break the index's own customer boundary. The audit
write below is the same shape, written locally on purpose.

**Audit ordering.** Every mutating method writes its ``staff_audit_log`` row
*first*, then performs the effect, inside one transaction. The row therefore
exists only if the whole action committed, which is what makes ``succeeded``
literally true, and it means an action whose audit row cannot be written never
reaches its effect at all. A privacy action that is not auditable must not
happen; ordering the audit first is how that is enforced rather than asserted.
"""

from __future__ import annotations

import asyncio
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg

from cre_mcp.access.context import TenantContext, current_context
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.domains import (
    current_hosted_request_repositories,
    require_fresh_admission,
)
from cre_mcp.postgres.pool import AuthorityContext, PostgresDatabase

_UNAVAILABLE = "privacy persistence unavailable"

#: The customer-reachable tool for each request-scoped method.
#:
#: Empty, and enumerated here rather than deleted, so the refusal has a single
#: named cause a test can substitute. There is no privacy, export, deletion or
#: retention capability in the customer surface, so no tool maps to any method
#: and every request-scoped call raises ``PrivacyPersistenceUnavailable``.
_METHOD_TOOLS: dict[str, frozenset[str]] = {}

KINDS = frozenset({"access", "export", "delete", "correct"})
STATUSES = frozenset(
    {"received", "verified", "in_progress", "completed", "rejected", "canceled"}
)
TERMINAL_STATUSES = frozenset({"completed", "rejected", "canceled"})
RETENTION_ACTIONS = frozenset(
    {"exported", "corrected", "deleted", "anonymized", "retained"}
)

#: The legal status graph, enforced here *and* by the table's CHECK vocabulary.
#:
#: The CHECK bounds which statuses may exist; it says nothing about which
#: orderings are legal, so a request could otherwise jump ``received`` straight
#: to ``completed`` and skip verification of the person asking.
TRANSITIONS: dict[str, frozenset[str]] = {
    "received": frozenset({"verified", "canceled"}),
    "verified": frozenset({"in_progress", "canceled"}),
    "in_progress": frozenset({"completed", "rejected", "canceled"}),
    "completed": frozenset(),
    "rejected": frozenset(),
    "canceled": frozenset(),
}

INTERNAL_ROLES = frozenset(
    {
        "owner",
        "admin",
        "jv_operations",
        "support",
        "security_audit",
        "read_only_analyst",
    }
)
MUTATING_ROLES = frozenset({"owner", "admin"})

MAX_PAGE = 200
MAX_DETAIL = 8_000

# What each action's audit row actually names. Mirrors the same correction made
# in the opportunity index: an audit row that misnames its object is the same
# category of defect as one that is missing.
_AUDIT_OBJECT_TYPES = {
    "submit": "privacy_request",
    "advance": "privacy_request",
    "retain": "retention_action",
    "list": "privacy_request_index",
    "export": "privacy_subject",
}


class PrivacyPersistenceUnavailable(RuntimeError):
    """The exact hosted privacy persistence boundary cannot complete safely."""


class InternalPrivacyDeskUnavailable(RuntimeError):
    """The internal privacy desk boundary cannot complete safely."""


# ---------------------------------------------------------------------------
# Shared validation.
# ---------------------------------------------------------------------------


def _uuid(value: object) -> str:
    if not isinstance(value, (str, UUID)):
        raise ValueError("invalid privacy identifier")
    try:
        selected = str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("invalid privacy identifier") from error
    if isinstance(value, str) and value != selected:
        raise ValueError("invalid privacy identifier")
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
        raise ValueError("invalid privacy text")
    return value


def _utc_text(value: object) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("invalid stored privacy timestamp")
    return value.astimezone(UTC).isoformat()


def _member(value: object, allowed: frozenset[str], what: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"unsupported {what}: {value!r}")
    return value


def _json_safe(value: Any) -> Any:
    """Render one stored column as something ``json.dumps`` accepts.

    An export is handed to a person, and eventually to a file. Leaving
    ``datetime`` and ``Decimal`` in it makes the payload look fine in Python and
    fail at the moment it is written out, which is the worst place to discover
    it.
    """
    if isinstance(value, datetime):
        return _utc_text(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


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


# ---------------------------------------------------------------------------
# The request-scoped bundle port.
# ---------------------------------------------------------------------------


class PostgresPrivacyRepository:
    """One actor's own privacy requests, through one exact admission.

    Every method refuses today, because ``_METHOD_TOOLS`` is empty and no
    customer capability names any of them. The SQL below is nonetheless the real
    SQL: the guard is what refuses, and it can be shown to be the only thing
    refusing.
    """

    def __init__(
        self,
        database: PostgresDatabase,
        admission: AdmissionOutcome,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise TypeError("privacy repository requires PostgreSQL")
        self._database = database
        self._admission = require_fresh_admission(admission)

    def _require_active_scope(self, method: str) -> TenantContext:
        repositories = current_hosted_request_repositories()
        context = current_context()
        allowed_tools = _METHOD_TOOLS.get(method)
        if (
            repositories is None
            or repositories.admission is not self._admission
            or repositories.require("privacy") is not self
            or not isinstance(context, TenantContext)
            or context.trusted
            or not context.active
            or allowed_tools is None
            or self._admission.tool_name not in allowed_tools
        ):
            raise PrivacyPersistenceUnavailable(_UNAVAILABLE)
        comparisons = (
            (context.workspace_id, self._admission.workspace_public_id),
            (context.actor_id, self._admission.actor_user_id),
            (context.session_id, self._admission.session_id),
        )
        if any(
            not left or not right or not hmac.compare_digest(left, right)
            for left, right in comparisons
        ):
            raise PrivacyPersistenceUnavailable(_UNAVAILABLE)
        return context

    def _verify_ownership(
        self, workspace_public_id: object, subject_user_id: object
    ) -> None:
        """Re-verify on read, against the admission rather than the query."""
        public_id = _text(workspace_public_id, maximum=256) or ""
        subject = _uuid(subject_user_id)
        if not hmac.compare_digest(
            public_id, self._admission.workspace_public_id
        ) or not hmac.compare_digest(subject, self._admission.actor_user_id):
            raise ValueError("invalid stored privacy request")

    def _decode_row(self, row: object) -> dict[str, object]:
        if not isinstance(row, tuple) or len(row) != 7:
            raise ValueError("invalid stored privacy request")
        request_id = _uuid(row[0])
        self._verify_ownership(row[1], row[2])
        return {
            "id": request_id,
            "kind": _member(row[3], KINDS, "privacy request kind"),
            "status": _member(row[4], STATUSES, "privacy request status"),
            "detail": _text(row[5], maximum=MAX_DETAIL, nullable=True),
            "created_at": _utc_text(row[6]),
        }

    def _submit_request(self, kind: str, detail: str | None) -> str:
        self._require_active_scope("submit_request")
        selected_kind = _member(kind, KINDS, "privacy request kind")
        selected_detail = _text(detail, maximum=MAX_DETAIL, nullable=True)
        with self._database.admitted_connection(self._admission) as connection:
            row = connection.execute(
                "WITH inserted AS (INSERT INTO medawarcre.privacy_requests("
                "workspace_id,user_id,kind,detail) "
                "VALUES (medawarcre.current_workspace_id(),"
                "medawarcre.current_actor_user_id(),%s,%s) "
                "RETURNING id,workspace_id,user_id) "
                "SELECT inserted.id,workspace.public_id,inserted.user_id "
                "FROM inserted JOIN medawarcre.workspaces workspace "
                "ON workspace.id=inserted.workspace_id",
                (selected_kind, selected_detail),
            ).fetchone()
            if not isinstance(row, tuple) or len(row) != 3:
                raise ValueError("invalid stored privacy request")
            request_id = _uuid(row[0])
            self._verify_ownership(row[1], row[2])
            self._require_active_scope("submit_request")
        return request_id

    async def submit_request(self, kind: str, detail: str | None = None) -> str:
        """Record one actor-private privacy request and return its UUID."""
        try:
            self._require_active_scope("submit_request")
            result = await _finish_thread_before_cancellation(
                self._submit_request, kind, detail
            )
            self._require_active_scope("submit_request")
            return result
        except PrivacyPersistenceUnavailable:
            raise
        except Exception as error:
            raise PrivacyPersistenceUnavailable(_UNAVAILABLE) from error

    def _list_requests(self) -> list[dict[str, object]]:
        self._require_active_scope("list_requests")
        with self._database.admitted_connection(self._admission) as connection:
            rows = connection.execute(
                "SELECT request.id,workspace.public_id,request.user_id,"
                "request.kind,request.status,request.detail,request.created_at "
                "FROM medawarcre.privacy_requests request "
                "JOIN medawarcre.workspaces workspace "
                "ON workspace.id=request.workspace_id "
                "ORDER BY request.created_at DESC,request.id"
            ).fetchall()
            result = [self._decode_row(row) for row in rows]
            self._require_active_scope("list_requests")
        return result

    async def list_requests(self) -> list[dict[str, object]]:
        """List the exact actor's own privacy requests, newest first."""
        try:
            self._require_active_scope("list_requests")
            result = await _finish_thread_before_cancellation(self._list_requests)
            self._require_active_scope("list_requests")
            return result
        except PrivacyPersistenceUnavailable:
            raise
        except Exception as error:
            raise PrivacyPersistenceUnavailable(_UNAVAILABLE) from error


# ---------------------------------------------------------------------------
# The internal, staff-side desk.
# ---------------------------------------------------------------------------


class _RefusedTransition(RuntimeError):
    """An illegal status change, refused inside its own transaction.

    Raising this rolls the transaction back, which is the point: the change did
    not happen. ``advance`` catches it outside the transaction and writes the
    ``denied`` audit row on a fresh connection, because a row written inside the
    doomed transaction would roll back with it.
    """

    def __init__(
        self, present: str, requested: str, request_id: str, workspace_id: str
    ) -> None:
        super().__init__(
            f"a privacy request may not move from {present!r} to {requested!r}"
        )
        self.present = present
        self.requested = requested
        self.request_id = request_id
        self.workspace_id = workspace_id


@dataclass(frozen=True)
class StaffActor:
    """One reason-coded, role-limited member of internal staff."""

    actor_user_id: str
    role: str
    reason_code: str = "privacy_request"

    def __post_init__(self) -> None:
        try:
            UUID(self.actor_user_id)
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("actor_user_id must be a UUID") from error
        if not isinstance(self.role, str):
            raise ValueError("an internal action requires a role")
        normalized = self.role.strip().casefold()
        if normalized not in INTERNAL_ROLES:
            raise ValueError(f"unsupported internal role: {self.role!r}")
        object.__setattr__(self, "role", normalized)
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ValueError("an internal action requires a reason code")
        object.__setattr__(self, "reason_code", self.reason_code.strip())

    @property
    def may_mutate(self) -> bool:
        return self.role in MUTATING_ROLES


@dataclass(frozen=True)
class PrivacyRequest:
    """One privacy request as internal staff see it."""

    id: str
    workspace_id: str
    workspace_public_id: str
    subject_user_id: str
    kind: str
    status: str
    detail: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class RetentionAction:
    """One recorded disposition of one object under one privacy request."""

    id: str
    workspace_id: str
    privacy_request_id: str
    subject_user_id: str | None
    action: str
    object_type: str
    object_id: str
    reason_code: str
    evidence: dict[str, Any]
    executed_at: datetime


class InternalPrivacyDesk:
    """Staff-only, reason-coded, audited processing of privacy requests."""

    def __init__(self, database: PostgresDatabase) -> None:
        if database.settings.runtime_mode != "admin":
            raise InternalPrivacyDeskUnavailable(
                "the internal privacy desk requires the admin runtime"
            )
        self._database = database

    @classmethod
    def for_dsn(cls, dsn: str) -> "InternalPrivacyDesk":
        database = PostgresDatabase(
            PostgresSettings(dsn=dsn, runtime_mode="admin", min_size=0, max_size=4)
        )
        database.open(wait=True)
        return cls(database)

    def close(self) -> None:
        self._database.close()

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _reason(reason: object) -> str:
        if not isinstance(reason, str) or len(reason.strip()) < 3:
            raise ValueError("a privacy action requires a stated reason")
        return reason.strip()

    @staticmethod
    def _actor(actor: object) -> StaffActor:
        if not isinstance(actor, StaffActor):
            raise ValueError("a privacy action requires a staff actor")
        return actor

    def _context(self, actor: StaffActor, reason: str) -> AuthorityContext:
        return AuthorityContext.internal(actor.actor_user_id, actor.role, reason)

    def _audit(
        self,
        connection: psycopg.Connection,
        actor: StaffActor,
        reason: str,
        *,
        action: str,
        object_id: str,
        result: str,
        workspace_id: str | None = None,
    ) -> None:
        """One audit row, in the same transaction as the work it describes.

        Written *before* the effect. It survives only if the transaction
        commits, so ``succeeded`` stays true, and an audit row that cannot be
        written stops the effect from being attempted at all.
        """
        connection.execute(
            "INSERT INTO medawarcre.staff_audit_log("
            "actor_user_id,actor_role,reason,reason_code,workspace_id,"
            "object_type,object_id,action,result) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                actor.actor_user_id,
                actor.role,
                reason,
                actor.reason_code,
                workspace_id,
                _AUDIT_OBJECT_TYPES.get(action, "privacy_request"),
                object_id,
                action,
                result,
            ),
        )

    def _audit_out_of_band(
        self,
        actor: StaffActor,
        reason: str,
        *,
        action: str,
        object_id: str,
        result: str,
    ) -> None:
        """Write one unlinked audit row on its own connection.

        Used only where the action is refused before it opens a transaction, so
        there is no surviving transaction to carry the row. Unlinked on purpose:
        a refused action must not pin a workspace through the audit log's
        foreign key the way a completed one does.
        """
        try:
            with self._database.connection(
                self._context(actor, reason)
            ) as connection:
                self._audit(
                    connection,
                    actor,
                    reason,
                    action=action,
                    object_id=object_id,
                    result=result,
                )
        except Exception:
            # Never let the audit of a refusal replace the refusal itself.
            return

    def _require_mutation(
        self, actor: StaffActor, reason: str, *, action: str, object_id: str
    ) -> None:
        if actor.may_mutate:
            return
        self._audit_out_of_band(
            actor, reason, action=action, object_id=object_id, result="denied"
        )
        raise PermissionError(
            f"role {actor.role!r} may read privacy requests but not change them"
        )

    @staticmethod
    def _resolve_workspace(
        connection: psycopg.Connection, workspace_public_id: str
    ) -> str:
        row = connection.execute(
            "SELECT id FROM medawarcre.workspaces WHERE public_id=%s",
            (workspace_public_id,),
        ).fetchone()
        if row is None:
            raise LookupError("no such workspace")
        return str(row[0])

    @staticmethod
    def _record(row: tuple[Any, ...]) -> PrivacyRequest:
        return PrivacyRequest(
            id=str(row[0]),
            workspace_id=str(row[1]),
            workspace_public_id=row[2],
            subject_user_id=str(row[3]),
            kind=row[4],
            status=row[5],
            detail=row[6],
            created_at=row[7],
            updated_at=row[8],
            completed_at=row[9],
        )

    _SELECT = (
        "SELECT request.id,request.workspace_id,workspace.public_id,"
        "request.user_id,request.kind,request.status,request.detail,"
        "request.created_at,request.updated_at,request.completed_at "
        "FROM medawarcre.privacy_requests request "
        "JOIN medawarcre.workspaces workspace "
        "ON workspace.id=request.workspace_id "
    )

    # -- mutations ---------------------------------------------------------

    def submit(
        self,
        workspace_public_id: str,
        subject_user_id: str,
        kind: str,
        detail: str | None = None,
        *,
        actor: StaffActor,
        reason: str,
    ) -> str:
        """Open one privacy request on a subject's behalf and return its id."""
        selected_actor = self._actor(actor)
        selected_reason = self._reason(reason)
        self._require_mutation(
            selected_actor,
            selected_reason,
            action="submit",
            object_id=str(workspace_public_id),
        )
        public_id = _text(workspace_public_id, maximum=256)
        subject = _uuid(subject_user_id)
        selected_kind = _member(kind, KINDS, "privacy request kind")
        selected_detail = _text(detail, maximum=MAX_DETAIL, nullable=True)
        with self._database.connection(
            self._context(selected_actor, selected_reason)
        ) as connection:
            workspace_id = self._resolve_workspace(connection, public_id or "")
            self._audit(
                connection,
                selected_actor,
                selected_reason,
                action="submit",
                object_id=subject,
                result="succeeded",
                workspace_id=workspace_id,
            )
            # Membership is not pre-checked. The composite foreign key on
            # (workspace_id, user_id) already refuses a non-member, and probing
            # for the row first would turn this call into a membership oracle
            # for any workspace whose public id staff can guess.
            request_id = connection.execute(
                "INSERT INTO medawarcre.privacy_requests("
                "workspace_id,user_id,kind,detail) VALUES (%s,%s,%s,%s) "
                "RETURNING id",
                (workspace_id, subject, selected_kind, selected_detail),
            ).fetchone()[0]
        return str(request_id)

    def advance(
        self,
        request_id: str,
        new_status: str,
        *,
        actor: StaffActor,
        reason: str,
    ) -> PrivacyRequest:
        """Move one request along the legal status graph, or refuse.

        The refusal is caught out here, outside the transaction, because the
        transaction it was raised in has already rolled back — a ``denied``
        audit row written inside it would roll back with it, which is exactly
        how a refused privacy action comes to leave no trace.
        """
        selected_actor = self._actor(actor)
        selected_reason = self._reason(reason)
        selected_id = _uuid(request_id)
        try:
            return self._advance(
                selected_actor, selected_reason, selected_id, new_status
            )
        except _RefusedTransition as refusal:
            self._audit_out_of_band(
                selected_actor,
                selected_reason,
                action="advance",
                object_id=refusal.request_id,
                result="denied",
            )
            raise ValueError(str(refusal)) from None

    def _advance(
        self,
        actor: StaffActor,
        reason: str,
        request_id: str,
        new_status: str,
    ) -> PrivacyRequest:
        self._require_mutation(
            actor, reason, action="advance", object_id=request_id
        )
        status = _member(new_status, STATUSES, "privacy request status")
        with self._database.connection(self._context(actor, reason)) as connection:
            current = connection.execute(
                "SELECT workspace_id,status FROM medawarcre.privacy_requests "
                "WHERE id=%s FOR UPDATE",
                (request_id,),
            ).fetchone()
            if current is None:
                raise LookupError("no such privacy request")
            workspace_id, present = str(current[0]), str(current[1])
            if status not in TRANSITIONS.get(present, frozenset()):
                raise _RefusedTransition(present, status, request_id, workspace_id)
            self._audit(
                connection,
                actor,
                reason,
                action="advance",
                object_id=request_id,
                result="succeeded",
                workspace_id=workspace_id,
            )
            connection.execute(
                "UPDATE medawarcre.privacy_requests SET status=%s,"
                "completed_at=CASE WHEN %s THEN statement_timestamp() "
                "ELSE completed_at END,"
                "updated_at=statement_timestamp() WHERE id=%s",
                (status, status in TERMINAL_STATUSES, request_id),
            )
            row = connection.execute(
                self._SELECT + "WHERE request.id=%s", (request_id,)
            ).fetchone()
        return self._record(row)

    def record_retention_action(
        self,
        request_id: str,
        action: str,
        object_type: str,
        object_id: str,
        reason_code: str,
        evidence: dict[str, Any] | None = None,
        *,
        actor: StaffActor,
        reason: str,
    ) -> str:
        """Record what was actually done to one object under one request."""
        selected_actor = self._actor(actor)
        selected_reason = self._reason(reason)
        selected_request = _uuid(request_id)
        self._require_mutation(
            selected_actor,
            selected_reason,
            action="retain",
            object_id=selected_request,
        )
        selected_action = _member(action, RETENTION_ACTIONS, "retention action")
        selected_object_type = _text(object_type, maximum=128)
        selected_object_id = _text(object_id, maximum=512)
        selected_reason_code = _text(reason_code, maximum=128)
        if evidence is None:
            evidence = {}
        if not isinstance(evidence, dict):
            raise ValueError("retention evidence must be an object")
        encoded = json.dumps(evidence, allow_nan=False, separators=(",", ":"))
        with self._database.connection(
            self._context(selected_actor, selected_reason)
        ) as connection:
            current = connection.execute(
                "SELECT workspace_id,user_id FROM medawarcre.privacy_requests "
                "WHERE id=%s",
                (selected_request,),
            ).fetchone()
            if current is None:
                raise LookupError("no such privacy request")
            workspace_id, subject = str(current[0]), str(current[1])
            self._audit(
                connection,
                selected_actor,
                selected_reason,
                action="retain",
                object_id=selected_object_id or "",
                result="succeeded",
                workspace_id=workspace_id,
            )
            retention_id = connection.execute(
                "INSERT INTO medawarcre.retention_actions("
                "workspace_id,privacy_request_id,subject_user_id,action,"
                "object_type,object_id,reason_code,evidence) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING id",
                (
                    workspace_id,
                    selected_request,
                    subject,
                    selected_action,
                    selected_object_type,
                    selected_object_id,
                    selected_reason_code,
                    encoded,
                ),
            ).fetchone()[0]
        return str(retention_id)

    # -- reads -------------------------------------------------------------

    def list_requests(
        self,
        workspace_public_id: str | None = None,
        status: str | None = None,
        *,
        actor: StaffActor,
        reason: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PrivacyRequest, ...]:
        """One page of requests, newest first, ordered by (created_at, id)."""
        selected_actor = self._actor(actor)
        selected_reason = self._reason(reason)
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if not 1 <= limit <= MAX_PAGE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE}")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        public_id = _text(workspace_public_id, maximum=256, nullable=True)
        selected_status = (
            None
            if status is None
            else _member(status, STATUSES, "privacy request status")
        )
        where: list[str] = []
        params: list[Any] = []
        with self._database.connection(
            self._context(selected_actor, selected_reason)
        ) as connection:
            workspace_id = (
                None
                if public_id is None
                else self._resolve_workspace(connection, public_id)
            )
            if workspace_id is not None:
                where.append("request.workspace_id=%s")
                params.append(workspace_id)
            if selected_status is not None:
                where.append("request.status=%s")
                params.append(selected_status)
            self._audit(
                connection,
                selected_actor,
                selected_reason,
                action="list",
                object_id="privacy_request_index",
                result="succeeded",
                workspace_id=workspace_id,
            )
            statement = (
                self._SELECT
                + ("WHERE " + " AND ".join(where) + " " if where else "")
                + "ORDER BY request.created_at DESC,request.id "
                "LIMIT %s OFFSET %s"
            )
            rows = connection.execute(
                statement, (*params, limit, offset)
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    def retention_actions(
        self, request_id: str, *, actor: StaffActor, reason: str
    ) -> tuple[RetentionAction, ...]:
        """Every recorded disposition linked to one privacy request."""
        selected_actor = self._actor(actor)
        selected_reason = self._reason(reason)
        selected_request = _uuid(request_id)
        with self._database.connection(
            self._context(selected_actor, selected_reason)
        ) as connection:
            rows = connection.execute(
                "SELECT id,workspace_id,privacy_request_id,subject_user_id,"
                "action,object_type,object_id,reason_code,evidence,executed_at "
                "FROM medawarcre.retention_actions WHERE privacy_request_id=%s "
                "ORDER BY executed_at,id",
                (selected_request,),
            ).fetchall()
        return tuple(
            RetentionAction(
                id=str(row[0]),
                workspace_id=str(row[1]),
                privacy_request_id=str(row[2]),
                subject_user_id=None if row[3] is None else str(row[3]),
                action=row[4],
                object_type=row[5],
                object_id=row[6],
                reason_code=row[7],
                evidence=row[8] or {},
                executed_at=row[9],
            )
            for row in rows
        )

    def export_workspace_subject(
        self,
        workspace_public_id: str,
        subject_user_id: str,
        *,
        actor: StaffActor,
        reason: str,
    ) -> dict[str, Any]:
        """Assemble one subject's data in one workspace, as a plain dict.

        Exactly the tenant relations that actually carry a per-subject link:
        memberships, consents, saved searches, deals, deal notes and the
        subject's own privacy requests. Nothing is invented, and nothing is
        gathered across workspaces — a person is a member of each workspace
        separately, and an export that crossed that line would answer a question
        the request did not ask.
        """
        selected_actor = self._actor(actor)
        selected_reason = self._reason(reason)
        public_id = _text(workspace_public_id, maximum=256) or ""
        subject = _uuid(subject_user_id)
        with self._database.connection(
            self._context(selected_actor, selected_reason)
        ) as connection:
            workspace_id = self._resolve_workspace(connection, public_id)
            self._audit(
                connection,
                selected_actor,
                selected_reason,
                action="export",
                object_id=subject,
                result="succeeded",
                workspace_id=workspace_id,
            )
            sections = {
                "memberships": (
                    "SELECT id,role,state,created_at,updated_at "
                    "FROM medawarcre.memberships "
                    "WHERE workspace_id=%s AND user_id=%s ORDER BY id",
                    ("id", "role", "state", "created_at", "updated_at"),
                ),
                "consents": (
                    "SELECT id,consent_type,granted,version,occurred_at "
                    "FROM medawarcre.consents "
                    "WHERE workspace_id=%s AND user_id=%s "
                    "ORDER BY occurred_at,id",
                    ("id", "consent_type", "granted", "version", "occurred_at"),
                ),
                "saved_searches": (
                    "SELECT id,name,query,min_score,active,created_at "
                    "FROM medawarcre.saved_searches "
                    "WHERE workspace_id=%s AND owner_user_id=%s ORDER BY id",
                    ("id", "name", "query", "min_score", "active", "created_at"),
                ),
                "deals": (
                    "SELECT id,source,source_record_id,title,listing,stage,"
                    "score,created_at FROM medawarcre.deals "
                    "WHERE workspace_id=%s AND created_by_user_id=%s ORDER BY id",
                    (
                        "id", "source", "source_record_id", "title", "listing",
                        "stage", "score", "created_at",
                    ),
                ),
                "deal_notes": (
                    "SELECT id,deal_id,body,stage,created_at "
                    "FROM medawarcre.deal_notes "
                    "WHERE workspace_id=%s AND author_user_id=%s ORDER BY id",
                    ("id", "deal_id", "body", "stage", "created_at"),
                ),
                "privacy_requests": (
                    "SELECT id,kind,status,detail,created_at,completed_at "
                    "FROM medawarcre.privacy_requests "
                    "WHERE workspace_id=%s AND user_id=%s ORDER BY id",
                    ("id", "kind", "status", "detail", "created_at", "completed_at"),
                ),
            }
            payload: dict[str, Any] = {
                "workspace_public_id": public_id,
                "subject_user_id": subject,
                "generated_at": _utc_text(
                    connection.execute(
                        "SELECT statement_timestamp()"
                    ).fetchone()[0]
                ),
            }
            for name, (statement, columns) in sections.items():
                rows = connection.execute(
                    statement, (workspace_id, subject)
                ).fetchall()
                payload[name] = [
                    {
                        column: _json_safe(value)
                        for column, value in zip(columns, row, strict=True)
                    }
                    for row in rows
                ]
        return payload


__all__ = [
    "INTERNAL_ROLES",
    "KINDS",
    "MAX_PAGE",
    "MUTATING_ROLES",
    "RETENTION_ACTIONS",
    "STATUSES",
    "TERMINAL_STATUSES",
    "TRANSITIONS",
    "InternalPrivacyDesk",
    "InternalPrivacyDeskUnavailable",
    "PostgresPrivacyRepository",
    "PrivacyPersistenceUnavailable",
    "PrivacyRequest",
    "RetentionAction",
    "StaffActor",
]
