"""The durable access-decision audit sink for the hosted process.

``AccessMiddleware`` treats a failed audit write as a refusal, not a warning:
the tool call fails closed with ``AUDIT_UNAVAILABLE``. That makes this the one
component whose unavailability stops the product, which is the correct trade
and also the reason it gets a real relation instead of a file.

The interface is exactly ``cre_mcp.access.audit.AuditLog``'s — ``record`` and
``events`` — so the middleware cannot tell which one it is holding, and the
local stdio product keeps its JSONL file untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime

from cre_mcp.access.audit import AuditEvent


class PostgresAccessAuditLog:
    """Append-only access-decision audit backed by PostgreSQL."""

    def __init__(self, backend) -> None:
        if backend is None:
            raise ValueError("a platform backend is required")
        self._backend = backend

    def record(
        self,
        *,
        workspace_id: str,
        tool: str,
        decision: str,
        reason: str = "",
    ) -> AuditEvent:
        event = AuditEvent(
            ts=datetime.now(UTC).isoformat(),
            workspace_id=workspace_id,
            tool=tool,
            decision=decision,
            reason=reason,
        )
        with self._backend.connect(transactional=True) as connection:
            connection.execute(
                """
                INSERT INTO access_audit_log(
                    event_ts, workspace_public_id, tool, decision, reason
                ) VALUES (?,?,?,?,?)
                """,
                (event.ts, event.workspace_id, event.tool, event.decision, event.reason),
            )
        return event

    def events(self, workspace_id: str | None = None) -> list[AuditEvent]:
        with self._backend.connect(transactional=False) as connection:
            if workspace_id is None:
                rows = connection.execute(
                    "SELECT event_ts, workspace_public_id, tool, decision, reason "
                    "FROM access_audit_log ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT event_ts, workspace_public_id, tool, decision, reason "
                    "FROM access_audit_log WHERE workspace_public_id=? ORDER BY id",
                    (workspace_id,),
                ).fetchall()
        return [
            AuditEvent(
                ts=str(row["event_ts"]),
                workspace_id=str(row["workspace_public_id"]),
                tool=str(row["tool"]),
                decision=str(row["decision"]),
                reason="" if row["reason"] is None else str(row["reason"]),
            )
            for row in rows
        ]


__all__ = ["PostgresAccessAuditLog"]
