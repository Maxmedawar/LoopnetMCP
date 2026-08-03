"""Tenant-aware access control for the hosted MCP server.

Spec: .claude/specs/tenant-access-control.md. Server-side identity only:
workspace, profile, plan, territory, and ownership come from the registry,
never from MCP arguments. Cloud mode default-denies unclassified tools; the
local stdio mode runs the same code path under a trusted local workspace.
"""

from cre_mcp.access.context import TenantContext, current_context, local_context, use_context
from cre_mcp.access.engine import AccessEngine, Decision
from cre_mcp.access.profiles import Profile
from cre_mcp.access.registry import WorkspaceRegistry


def __getattr__(name: str):
    """Load middleware exports lazily so lower-level gates can import context."""
    if name in {"AccessMiddleware", "install_access"}:
        from cre_mcp.access.middleware import AccessMiddleware, install_access

        value = {
            "AccessMiddleware": AccessMiddleware,
            "install_access": install_access,
        }[name]
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AccessEngine",
    "AccessMiddleware",
    "Decision",
    "Profile",
    "TenantContext",
    "WorkspaceRegistry",
    "current_context",
    "install_access",
    "local_context",
    "use_context",
]
