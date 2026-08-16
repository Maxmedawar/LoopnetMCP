"""Audited, payload-free access to durable provider reconciliation state."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cre_mcp.platform.admin import (
    AdminAuditError,
    AdminForbiddenError,
    AdminNotFoundError,
    AdminValidationError,
    canonical_json,
    validate_reason,
)
from cre_mcp.platform.providers.core import (
    ProviderSyncService,
    ReconciliationConflictError,
    ReconciliationNotFoundError,
    ReconciliationValidationError,
    SyncResult,
    decode_cursor,
    encode_cursor,
)
from cre_mcp.platform.dbapi import platform_connection


PROVIDERS = frozenset({"stripe", "skool"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_provider(value: Any) -> str:
    if not isinstance(value, str) or value not in PROVIDERS:
        raise AdminValidationError("provider must be stripe or skool")
    return value


def _page_limit(value: Any) -> int:
    if isinstance(value, bool):
        raise AdminValidationError("limit must be an integer from 1 to 1000")
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise AdminValidationError(
            "limit must be an integer from 1 to 1000"
        ) from exc
    if limit < 1 or limit > 1000:
        raise AdminValidationError("limit must be an integer from 1 to 1000")
    return limit


def _event(row: sqlite3.Row) -> dict[str, Any]:
    """Return only reconciliation metadata, never normalized provider fields."""
    return {
        "id": int(row["id"]),
        "provider": str(row["provider"]),
        "event_type": str(row["event_type"]),
        "outcome": str(row["outcome"]),
        "reason_code": (
            str(row["reason_code"]) if row["reason_code"] is not None else None
        ),
        "occurred_at": str(row["occurred_at"]),
        "duplicate_count": int(row["duplicate_count"]),
        "replayed_at": (
            str(row["replayed_at"])
            if row["replayed_at"] is not None
            else None
        ),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


class ProviderReconciliationStore:
    """Reason-coded reconciliation reads and idempotent selected replay."""

    def __init__(self, db_path: str | Path, sync: ProviderSyncService) -> None:
        self.db_path = Path(db_path).expanduser()
        self.sync = sync

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with platform_connection(
            self.db_path,
            timeout=30,
            transactional=False,
        ) as connection:
            yield connection

    @staticmethod
    def _actor(
        connection: sqlite3.Connection,
        actor_user_id: int,
        *,
        mutate: bool,
    ) -> sqlite3.Row:
        actor = connection.execute(
            """
            SELECT user_id,role
            FROM platform_internal_admins
            WHERE user_id=? AND active=1
            """,
            (actor_user_id,),
        ).fetchone()
        allowed = {"platform_admin"} if mutate else {"platform_admin", "support"}
        if actor is None or str(actor["role"]) not in allowed:
            raise AdminForbiddenError("Active internal operator authority is required")
        return actor

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        actor: sqlite3.Row,
        *,
        action: str,
        workspace_id: int | None,
        target_type: str,
        target_id: str,
        reason_code: str,
        reason: str,
        before: Any,
        after: Any,
    ) -> None:
        changes_before = connection.total_changes
        try:
            connection.execute(
                """
                INSERT INTO platform_admin_audit(
                    actor_user_id,actor_role,action,workspace_id,
                    target_type,target_id,reason_code,reason,
                    before_json,after_json,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    int(actor["user_id"]),
                    str(actor["role"]),
                    action,
                    workspace_id,
                    target_type,
                    target_id,
                    reason_code,
                    reason,
                    canonical_json(before),
                    canonical_json(after),
                    _now(),
                ),
            )
        except sqlite3.DatabaseError as exc:
            raise AdminAuditError from exc
        if connection.total_changes != changes_before + 1:
            raise AdminAuditError

    def quarantine_queue(
        self,
        *,
        actor_user_id: int,
        provider: Any,
        limit: Any,
        cursor: str | None,
        reason_code: Any,
        reason: Any,
    ) -> dict[str, Any]:
        normalized_provider = _required_provider(provider)
        normalized_limit = _page_limit(limit)
        normalized_code, normalized_reason = validate_reason(reason_code, reason)
        try:
            after_id = decode_cursor(cursor)
        except ReconciliationValidationError as exc:
            raise AdminValidationError(str(exc)) from exc
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                actor = self._actor(
                    connection,
                    actor_user_id,
                    mutate=False,
                )
                rows = connection.execute(
                    """
                    SELECT * FROM platform_provider_events
                    WHERE provider=? AND outcome='quarantined' AND id>?
                    ORDER BY id LIMIT ?
                    """,
                    (normalized_provider, after_id, normalized_limit + 1),
                ).fetchall()
                visible = rows[:normalized_limit]
                events = [_event(row) for row in visible]
                next_cursor = (
                    encode_cursor(int(visible[-1]["id"]))
                    if len(rows) > normalized_limit and visible
                    else None
                )
                self._audit(
                    connection,
                    actor,
                    action="provider_event.quarantine_list",
                    workspace_id=None,
                    target_type="provider_event_queue",
                    target_id=normalized_provider,
                    reason_code=normalized_code,
                    reason=normalized_reason,
                    before=None,
                    after={
                        "provider": normalized_provider,
                        "event_ids": [item["id"] for item in events],
                    },
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()
            return {"events": events, "next_cursor": next_cursor}

    def workspace_events(
        self,
        *,
        actor_user_id: int,
        workspace_public_id: str,
        provider: Any,
        limit: Any,
        cursor: str | None,
        reason_code: Any,
        reason: Any,
    ) -> dict[str, Any]:
        normalized_provider = (
            None if provider in (None, "") else _required_provider(provider)
        )
        normalized_limit = _page_limit(limit)
        normalized_code, normalized_reason = validate_reason(reason_code, reason)
        try:
            after_id = decode_cursor(cursor)
        except ReconciliationValidationError as exc:
            raise AdminValidationError(str(exc)) from exc
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                actor = self._actor(
                    connection,
                    actor_user_id,
                    mutate=False,
                )
                workspace = connection.execute(
                    "SELECT id FROM platform_workspaces WHERE public_id=?",
                    (workspace_public_id,),
                ).fetchone()
                if workspace is None:
                    raise AdminNotFoundError("Workspace does not exist")
                workspace_id = int(workspace["id"])
                clauses = ["workspace_id=?", "id>?"]
                parameters: list[Any] = [workspace_id, after_id]
                if normalized_provider is not None:
                    clauses.append("provider=?")
                    parameters.append(normalized_provider)
                parameters.append(normalized_limit + 1)
                rows = connection.execute(
                    f"""
                    SELECT * FROM platform_provider_events
                    WHERE {' AND '.join(clauses)}
                    ORDER BY id LIMIT ?
                    """,
                    parameters,
                ).fetchall()
                visible = rows[:normalized_limit]
                events = [_event(row) for row in visible]
                next_cursor = (
                    encode_cursor(int(visible[-1]["id"]))
                    if len(rows) > normalized_limit and visible
                    else None
                )
                self._audit(
                    connection,
                    actor,
                    action="provider_event.workspace_list",
                    workspace_id=workspace_id,
                    target_type="workspace_provider_events",
                    target_id=workspace_public_id,
                    reason_code=normalized_code,
                    reason=normalized_reason,
                    before=None,
                    after={
                        "provider": normalized_provider,
                        "event_ids": [item["id"] for item in events],
                    },
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()
            return {"events": events, "next_cursor": next_cursor}

    def replay(
        self,
        *,
        actor_user_id: int,
        provider_event_id: int,
        reason_code: Any,
        reason: Any,
    ) -> dict[str, Any]:
        normalized_code, normalized_reason = validate_reason(reason_code, reason)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                actor = self._actor(connection, actor_user_id, mutate=True)
                before_row = connection.execute(
                    "SELECT * FROM platform_provider_events WHERE id=?",
                    (provider_event_id,),
                ).fetchone()
                if before_row is None:
                    raise ReconciliationNotFoundError(
                        "Provider event does not exist"
                    )
                before = _event(before_row)
                result: SyncResult = self.sync.replay_tx(
                    connection,
                    provider_event_id,
                )
                after_row = connection.execute(
                    "SELECT * FROM platform_provider_events WHERE id=?",
                    (provider_event_id,),
                ).fetchone()
                assert after_row is not None
                after = _event(after_row)
                self._audit(
                    connection,
                    actor,
                    action="provider_event.replay",
                    workspace_id=result.workspace_id,
                    target_type="provider_event",
                    target_id=str(provider_event_id),
                    reason_code=normalized_code,
                    reason=normalized_reason,
                    before=before,
                    after=after,
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()
            return {
                "accepted": True,
                "outcome": result.outcome,
                "reason_code": result.reason_code,
                "event": after,
            }


__all__ = ["ProviderReconciliationStore", "PROVIDERS"]
