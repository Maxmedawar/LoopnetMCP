"""Dual enforcement on the FastMCP server.

`on_list_tools` filters what a workspace can see; `on_call_tool` re-checks at
execution, sanitizes arguments, applies the approval gate, scopes storage to
the workspace for the duration of the call, and audits every decision.

Identity resolution is server-side only. Hosted HTTP accepts only the
authoritative FastMCP access-token claim produced by the OAuth verifier.
Trusted-local identity exists only when the caller explicitly selects the
stdio runtime. Missing context and dependency failures always fail closed.
"""

from collections.abc import Callable
from typing import Any, Literal

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


def _default_resolver_for(
    runtime_mode: Literal["stdio", "http"] | None,
) -> IdentityResolver:
    def resolve(_context: MiddlewareContext) -> TenantContext | None:
        if runtime_mode == "stdio":
            return local_context()
        if runtime_mode != "http":
            return None
        try:
            from fastmcp.server.dependencies import get_access_token

            access_token = get_access_token()
        except Exception:
            return None
        if access_token is None:
            return None
        claims = getattr(access_token, "claims", {})
        raw_context = claims.get("tenant_context") if isinstance(claims, dict) else None
        if not isinstance(raw_context, dict):
            return None
        try:
            context = TenantContext.model_validate(raw_context)
        except Exception:
            return None
        return context if not context.trusted else None

    return resolve


class AccessMiddleware(Middleware):
    def __init__(
        self,
        *,
        registry: WorkspaceRegistry,
        audit_log: AuditLog,
        identity_resolver: IdentityResolver | None = None,
        capabilities: dict[str, ToolCapability] | None = None,
        runtime_mode: Literal["stdio", "http"] | None = None,
    ) -> None:
        self.engine = AccessEngine(registry, capabilities)
        self.audit = audit_log
        self._resolve = identity_resolver or _default_resolver_for(runtime_mode)

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
    runtime_mode: Literal["stdio", "http"] | None = None,
) -> Callable[[], None]:
    """Install access control on a FastMCP server; returns an uninstaller."""
    middleware = AccessMiddleware(
        registry=registry,
        audit_log=audit_log,
        identity_resolver=identity_resolver,
        capabilities=capabilities,
        runtime_mode=runtime_mode,
    )
    mcp.add_middleware(middleware)

    def uninstall() -> None:
        try:
            mcp.middleware.remove(middleware)
        except ValueError:
            pass

    return uninstall
