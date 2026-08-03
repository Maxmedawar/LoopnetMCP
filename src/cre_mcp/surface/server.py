"""Hosted grouped-tool server backed by the complete internal MCP catalog."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from cre_mcp.access.context import current_context

from .catalog import CUSTOMER_SURFACE, CustomerSurfaceCatalog, SurfaceToolSpec

_CUSTOMER_INSTRUCTIONS = (
    "MedawarCRE customer workspace. Each visible tool groups related actions. "
    "Pass an exact listed action and its arguments. The server enforces the "
    "underlying capability's current entitlement, quota, territory, source "
    "rights, approval requirement, result policy, and audit record."
)


def _tool_description(spec: SurfaceToolSpec) -> str:
    actions = ", ".join(spec.capability_ids)
    return f"{spec.description} Exact actions: {actions}."


def _make_dispatcher(
    spec: SurfaceToolSpec,
    *,
    internal_server: FastMCP,
    catalog: CustomerSurfaceCatalog,
):
    async def dispatch(
        action: str,
        arguments: dict[str, Any] | None = None,
    ):
        """Execute one exact server-owned capability through this grouped tool."""
        ctx = current_context()
        if ctx is None or ctx.trusted:
            raise ToolError("access denied: hosted customer context is required")
        resolved = catalog.resolve(
            spec.name,
            {"action": action, "arguments": arguments or {}},
        )
        if resolved is None:
            raise ToolError("access denied: grouped action is not available")
        capability_id, exact_arguments = resolved
        tools = await internal_server.get_tools()
        internal_tool = tools.get(capability_id)
        if internal_tool is None:
            raise ToolError("access denied: grouped action is unavailable")
        return await internal_tool.run(exact_arguments)

    dispatch.__name__ = spec.name
    dispatch.__doc__ = _tool_description(spec)
    return dispatch


def build_customer_server(
    internal_server: FastMCP,
    *,
    catalog: CustomerSurfaceCatalog = CUSTOMER_SURFACE,
) -> FastMCP:
    """Build the small hosted facade without mutating the internal server."""
    server = FastMCP(name="medawarcre", instructions=_CUSTOMER_INSTRUCTIONS)
    for spec in catalog.tools.values():
        server.tool(name=spec.name, description=_tool_description(spec))(
            _make_dispatcher(
                spec,
                internal_server=internal_server,
                catalog=catalog,
            )
        )
    return server


def resolve_surface_call(
    tool_name: str,
    arguments: Mapping[str, Any] | None,
    *,
    catalog: CustomerSurfaceCatalog = CUSTOMER_SURFACE,
):
    """Middleware adapter returning exact and rewrapped capability arguments."""
    resolved = catalog.resolve(tool_name, arguments)
    if resolved is None:
        return None
    capability_id, exact_arguments = resolved
    return (
        capability_id,
        exact_arguments,
        lambda sanitized: {
            "action": capability_id,
            "arguments": sanitized,
        },
    )


__all__ = ["build_customer_server", "resolve_surface_call"]
