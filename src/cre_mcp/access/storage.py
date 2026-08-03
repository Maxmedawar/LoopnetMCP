"""Workspace-scoped storage resolution.

The whole persistence layer funnels through CreConfig.cache_db_path, so
scoping storage to a workspace is a path decision: cloud workspaces get
<cache root>/workspaces/<workspace_id>/<db name>; the trusted local workspace
keeps the legacy path untouched, which preserves every existing local record
without any data migration.
"""

from pathlib import Path

from cre_mcp.access.context import TenantContext

WORKSPACES_DIRNAME = "workspaces"


def workspace_db_path(ctx: TenantContext | None, base: Path) -> Path:
    if ctx is None or ctx.trusted:
        return base
    base = Path(base).expanduser()
    # Idempotence: never nest a workspace path inside itself.
    if base.parent.name == ctx.workspace_id and base.parent.parent.name == WORKSPACES_DIRNAME:
        return base
    if "/" in ctx.workspace_id or "\\" in ctx.workspace_id or ".." in ctx.workspace_id:
        raise ValueError(f"unsafe workspace id: {ctx.workspace_id!r}")
    return base.parent / WORKSPACES_DIRNAME / ctx.workspace_id / base.name
