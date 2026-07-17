"""Append-only audit log for access decisions (JSONL, server-side)."""

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


class AuditEvent(BaseModel):
    ts: str
    workspace_id: str
    tool: str
    decision: str
    reason: str = ""


class AuditLog:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()

    def record(
        self, *, workspace_id: str, tool: str, decision: str, reason: str = ""
    ) -> AuditEvent:
        event = AuditEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            workspace_id=workspace_id,
            tool=tool,
            decision=decision,
            reason=reason,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        return event

    def events(self, workspace_id: str | None = None) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        found = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = AuditEvent.model_validate_json(line)
            if workspace_id is None or event.workspace_id == workspace_id:
                found.append(event)
        return found
