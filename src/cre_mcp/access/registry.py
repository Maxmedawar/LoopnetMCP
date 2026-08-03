"""Server-side workspace registry: grants, plans, approvals, quota usage.

The registry file is server-owned truth. API keys are stored as SHA-256
digests; a key resolves to a TenantContext or nothing. Nothing in this module
is reachable from MCP tool arguments.
"""

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cre_mcp.access.context import TenantContext
from cre_mcp.access.profiles import Profile

_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _utc_today() -> str:
    """Quota windows key off the UTC calendar day, matching the audit log."""
    return datetime.now(UTC).date().isoformat()


class WorkspaceRegistry:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        self._mtime: int | None = None
        # Written on first mutation only, so constructing a registry
        # (e.g. building the HTTP app in tests) leaves no files behind.
        self._data = {"plans": {"standard": {}}, "grants": {}, "approvals": {}, "usage": {}}
        self._reload()

    def _reload(self) -> None:
        """Re-read server-owned truth when the file changed under us.

        The registry file is the source of truth and is mutated out-of-band by
        admin tooling (provisioning keys, granting approvals). A long-lived
        server must see those writes without a restart, and read-modify-write
        mutations must start from current on-disk state rather than a stale
        startup snapshot. Single-writer assumption still holds — this closes
        the "invisible until restart" gap, not full multi-writer concurrency.
        """
        try:
            mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            return
        if mtime == self._mtime:
            return
        self._data = json.loads(self.path.read_text(encoding="utf-8"))
        self._mtime = mtime

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=1), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
        try:
            self._mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            self._mtime = None

    # -- plans ------------------------------------------------------------
    def add_plan(self, name: str, quotas: dict[str, int]) -> None:
        self._reload()
        self._data["plans"][name] = dict(quotas)
        self._save()

    def plan_quotas(self, plan: str) -> dict[str, int]:
        self._reload()
        return dict(self._data["plans"].get(plan, {}))

    # -- grants -----------------------------------------------------------
    def add_grant(
        self,
        key: str,
        workspace_id: str,
        profile: Profile,
        *,
        plan: str = "standard",
        territories: tuple[str, ...] = (),
        active: bool = True,
        display_name: str = "",
    ) -> None:
        if not _WORKSPACE_ID_RE.match(workspace_id):
            raise ValueError(f"invalid workspace id: {workspace_id!r}")
        self._reload()
        self._data["grants"][_digest(key)] = {
            "workspace_id": workspace_id,
            "profile": Profile(profile).value,
            "plan": plan,
            "territories": list(territories),
            "active": bool(active),
            "display_name": display_name,
        }
        self._save()

    def resolve_key(self, key: str) -> TenantContext | None:
        self._reload()
        grant = self._data["grants"].get(_digest(key)) if key else None
        if grant is None:
            return None
        return TenantContext(
            workspace_id=grant["workspace_id"],
            profile=Profile(grant["profile"]),
            plan=grant["plan"],
            quota_limits=self.plan_quotas(grant["plan"]),
            territories=tuple(grant["territories"]),
            active=grant["active"],
            trusted=False,
            display_name=grant.get("display_name", ""),
            actor_id=f"key:{_digest(key)}",
            session_id=f"key:{_digest(key)}",
        )

    # -- approvals --------------------------------------------------------
    def request_approval(self, workspace_id: str, tool: str, args_hash: str) -> str:
        self._reload()
        approval_id = f"ap-{uuid.uuid4().hex}"
        self._data["approvals"][approval_id] = {
            "workspace_id": workspace_id,
            "tool": tool,
            "args_hash": args_hash,
            "granted": False,
            "used": False,
        }
        self._save()
        return approval_id

    def grant_approval(self, approval_id: str) -> None:
        self._reload()
        record = self._data["approvals"].get(approval_id)
        if record is None:
            raise KeyError(f"unknown approval: {approval_id}")
        record["granted"] = True
        self._save()

    def consume_approval(
        self, approval_id: str, workspace_id: str, tool: str, args_hash: str
    ) -> bool:
        self._reload()
        record = self._data["approvals"].get(approval_id)
        if (
            record is None
            or not record["granted"]
            or record["used"]
            or record["workspace_id"] != workspace_id
            or record["tool"] != tool
            or record["args_hash"] != args_hash
        ):
            return False
        record["used"] = True
        self._save()
        return True

    # -- quota usage ------------------------------------------------------
    def record_usage(self, workspace_id: str, bucket: str) -> None:
        self._reload()
        today = _utc_today()
        usage = self._data["usage"]
        # Only today's counters are ever read, so drop every prior-day key on
        # write; otherwise the file grows without bound on a busy server.
        for stale in [k for k in usage if not k.endswith(f":{today}")]:
            del usage[stale]
        key = f"{workspace_id}:{bucket}:{today}"
        usage[key] = usage.get(key, 0) + 1
        self._save()

    def usage_today(self, workspace_id: str, bucket: str) -> int:
        self._reload()
        key = f"{workspace_id}:{bucket}:{_utc_today()}"
        return self._data["usage"].get(key, 0)
