"""Dual enforcement on the FastMCP server.

`on_list_tools` filters what a workspace can see; `on_call_tool` re-checks at
execution, sanitizes arguments, applies the approval gate, scopes storage to
the workspace for the duration of the call, and audits every decision.

Identity resolution is server-side only. The default resolver uses the HTTP
Authorization / X-API-Key header against the registry when a request context
exists, and falls back to the explicit trusted local workspace when there is
none (stdio). An injected resolver returning None models an unauthenticated
connection: nothing is visible, everything is denied.
"""

from collections.abc import Callable
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult

from cre_mcp.access.audit import AuditLog
from cre_mcp.access.capabilities import ToolCapability
from cre_mcp.access.context import TenantContext, local_context, use_context
from cre_mcp.access.engine import AccessEngine
from cre_mcp.access.registry import WorkspaceRegistry

UNAUTHENTICATED = "(unauthenticated)"

IdentityResolver = Callable[[MiddlewareContext], TenantContext | None]


def _default_resolver_for(registry: WorkspaceRegistry) -> IdentityResolver:
    def resolve(_context: MiddlewareContext) -> TenantContext | None:
        try:
            from fastmcp.server.dependencies import get_http_headers

            headers = get_http_headers()
        except Exception:
            headers = {}
        if not headers:
            # No HTTP request: stdio / in-process — the trusted local workspace.
            return local_context()
        authorization = headers.get("authorization", "")
        key = ""
        if authorization.lower().startswith("bearer "):
            key = authorization[7:].strip()
        if not key:
            key = headers.get("x-api-key", "").strip()
        return registry.resolve_key(key) if key else None

    return resolve


class AccessMiddleware(Middleware):
    def __init__(
        self,
        *,
        registry: WorkspaceRegistry,
        audit_log: AuditLog,
        identity_resolver: IdentityResolver | None = None,
        capabilities: dict[str, ToolCapability] | None = None,
    ) -> None:
        self.engine = AccessEngine(registry, capabilities)
        self.audit = audit_log
        self._resolve = identity_resolver or _default_resolver_for(registry)

    async def on_list_tools(self, context: MiddlewareContext, call_next) -> Any:
        ctx = self._resolve(context)
        tools = await call_next(context)
        visible = [
            tool
            for tool in tools
            if self.engine.check_tool(ctx, tool.name).outcome == "allowed"
        ]
        self.audit.record(
            workspace_id=ctx.workspace_id if ctx else UNAUTHENTICATED,
            tool="__list_tools__",
            decision="allowed" if ctx and ctx.active else "denied",
            reason=f"filtered {len(tools)}->{len(visible)}",
        )
        return visible

    async def on_call_tool(self, context: MiddlewareContext, call_next) -> ToolResult:
        ctx = self._resolve(context)
        tool_name = context.message.name
        args = context.message.arguments or {}
        decision, sanitized = self.engine.check_call(ctx, tool_name, args)
        workspace = ctx.workspace_id if ctx else UNAUTHENTICATED

        if decision.outcome == "denied":
            self.audit.record(
                workspace_id=workspace,
                tool=tool_name,
                decision="denied",
                reason=decision.reason,
            )
            raise ToolError(decision.reason)

        if decision.outcome == "approval_required":
            self.audit.record(
                workspace_id=workspace,
                tool=tool_name,
                decision="approval_required",
                reason=decision.reason,
            )
            return ToolResult(
                structured_content={
                    "approval_required": True,
                    "approval_id": decision.approval_id,
                    "tool": tool_name,
                    "message": decision.reason,
                }
            )

        context.message.arguments = sanitized
        with use_context(ctx):
            result = await call_next(context)
        self.audit.record(
            workspace_id=workspace,
            tool=tool_name,
            decision="allowed",
            reason=decision.reason,
        )
        return result


def install_access(
    mcp,
    *,
    registry: WorkspaceRegistry,
    audit_log: AuditLog,
    identity_resolver: IdentityResolver | None = None,
    capabilities: dict[str, ToolCapability] | None = None,
) -> Callable[[], None]:
    """Install access control on a FastMCP server; returns an uninstaller."""
    middleware = AccessMiddleware(
        registry=registry,
        audit_log=audit_log,
        identity_resolver=identity_resolver,
        capabilities=capabilities,
    )
    mcp.add_middleware(middleware)

    def uninstall() -> None:
        try:
            mcp.middleware.remove(middleware)
        except ValueError:
            pass

    return uninstall
