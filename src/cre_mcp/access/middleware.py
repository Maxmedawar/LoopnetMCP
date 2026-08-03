"""Dual enforcement on the FastMCP server.

`on_list_tools` filters what a workspace can see; `on_call_tool` re-checks at
execution, sanitizes arguments, applies the approval gate, scopes storage to
the workspace for the duration of the call, and audits every decision.

Identity resolution is server-side only. Hosted HTTP accepts only the
authoritative FastMCP access-token claim produced by the OAuth verifier.
Trusted-local identity exists only when the caller explicitly selects the
stdio runtime. Missing context and dependency failures always fail closed.
"""

import json
import math
from collections.abc import Callable, Mapping
from typing import Any, Literal

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent

from cre_mcp.access.audit import AuditLog
from cre_mcp.access.capabilities import ToolCapability
from cre_mcp.access.context import (
    TenantContext,
    local_context,
    use_context,
    use_runtime_config,
)
from cre_mcp.access.engine import AccessEngine, RESULT_TERRITORY_DENIAL
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.source_rights.gate import collect_authorized_sources
from cre_mcp.source_rights.output import safe_error_message, sanitize_tool_result

UNAUTHENTICATED = "(unauthenticated)"
MAX_RESULT_JSON_DEPTH = 64
_CANONICAL_TOOL_RESULT_FIELDS = frozenset(
    {"content", "structured_content", "meta"}
)
_CANONICAL_TOOL_RESULT_SERIALIZER = ToolResult.to_mcp_result

IdentityResolver = Callable[[MiddlewareContext], TenantContext | None]
ToolArgumentWrapper = Callable[[dict[str, Any]], dict[str, Any]]
ToolCallResolver = Callable[
    [str, Mapping[str, Any] | None],
    tuple[str, dict[str, Any], ToolArgumentWrapper] | None,
]
ToolVisibilityResolver = Callable[
    [TenantContext | None, str, AccessEngine],
    bool,
]


def _reject_json_constant(_value: str) -> None:
    """Reject the non-standard NaN and infinity tokens accepted by json."""
    raise ValueError("non-finite JSON constant")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build one JSON object while rejecting duplicate keys at any depth."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _is_strict_json_tree(root: object) -> bool:
    """Validate JSON value types, finite numbers, depth, and acyclicity."""
    stack: list[tuple[object, int]] = [(root, 1)]
    seen_containers: set[int] = set()
    while stack:
        value, depth = stack.pop()
        value_type = type(value)
        if value_type is dict:
            if depth > MAX_RESULT_JSON_DEPTH or id(value) in seen_containers:
                return False
            seen_containers.add(id(value))
            if any(type(key) is not str for key in value):
                return False
            stack.extend((item, depth + 1) for item in value.values())
        elif value_type is list:
            if depth > MAX_RESULT_JSON_DEPTH or id(value) in seen_containers:
                return False
            seen_containers.add(id(value))
            stack.extend((item, depth + 1) for item in value)
        elif value is None or value_type in (str, bool, int):
            continue
        elif value_type is float and math.isfinite(value):
            continue
        else:
            return False
    return True


def _strict_json_mapping(text: str) -> dict[str, object] | None:
    """Decode one client-visible JSON object with restrictive semantics."""
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None
    if type(decoded) is not dict or not _is_strict_json_tree(decoded):
        return None
    return decoded


def _result_payloads(
    result: ToolResult,
) -> tuple[Mapping[str, object], ...] | None:
    """Extract every client-visible mapping representation, or fail closed."""
    try:
        if type(result) is not ToolResult:
            return None
        attributes = vars(result)
        if (
            type(attributes) is not dict
            or frozenset(attributes) != _CANONICAL_TOOL_RESULT_FIELDS
        ):
            return None
        serializer = getattr(result, "to_mcp_result", None)
        if (
            getattr(serializer, "__self__", None) is not result
            or getattr(serializer, "__func__", None)
            is not _CANONICAL_TOOL_RESULT_SERIALIZER
        ):
            return None
        if result.meta is not None:
            # A declared result contract does not authorize a second payload
            # in protocol metadata, including a falsey metadata mapping.
            return None
        if type(result.content) is not list:
            return None

        payloads: list[Mapping[str, object]] = []
        structured = result.structured_content
        if structured is not None:
            if type(structured) is not dict or not _is_strict_json_tree(structured):
                return None
            payloads.append(structured)

        for block in result.content:
            if type(block) is not TextContent:
                return None
            if type(block.type) is not str or block.type != "text":
                return None
            if block.meta is not None:
                return None
            extras = block.model_extra
            if type(extras) is not dict or extras:
                return None
            # Search results have no declared annotation channel. Rejecting
            # the entire field prevents both standard and extension metadata
            # from becoming an unvalidated client-visible side channel.
            if block.annotations is not None:
                return None
            if type(block.text) is not str:
                return None
            decoded = _strict_json_mapping(block.text)
            if decoded is None:
                return None
            payloads.append(decoded)

        return tuple(payloads) or None
    except (AttributeError, TypeError, ValueError, RecursionError, OverflowError):
        # Expected malformed-result failures are intentionally indistinguishable
        # from any other post-result territory denial at the protocol boundary.
        return None


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
        config: Any | None = None,
        tool_call_resolver: ToolCallResolver | None = None,
        tool_visibility_resolver: ToolVisibilityResolver | None = None,
    ) -> None:
        self.engine = AccessEngine(registry, capabilities)
        self.audit = audit_log
        self._resolve = identity_resolver or _default_resolver_for(runtime_mode)
        self._config = config
        self._resolve_tool_call = tool_call_resolver
        self._tool_is_visible = tool_visibility_resolver

    async def on_list_tools(self, context: MiddlewareContext, call_next) -> Any:
        ctx = self._resolve(context)
        tools = await call_next(context)
        if self._tool_is_visible is None:
            visible = [
                tool
                for tool in tools
                if self.engine.check_tool(ctx, tool.name).outcome == "allowed"
            ]
        else:
            visible = [
                tool
                for tool in tools
                if self._tool_is_visible(ctx, tool.name, self.engine)
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
        requested_tool = context.message.name
        tool_name = requested_tool
        args = context.message.arguments or {}
        wrap_arguments: ToolArgumentWrapper = lambda value: value
        if self._resolve_tool_call is not None:
            try:
                resolved_call = self._resolve_tool_call(requested_tool, args)
            except Exception:
                resolved_call = None
            if resolved_call is None:
                workspace = ctx.workspace_id if ctx else UNAUTHENTICATED
                reason = "access denied: grouped action is not available"
                self.audit.record(
                    workspace_id=workspace,
                    tool=requested_tool,
                    decision="denied",
                    reason=reason,
                )
                raise ToolError(reason)
            tool_name, args, wrap_arguments = resolved_call
        decision, sanitized = self.engine.check_call(ctx, tool_name, args)
        workspace = ctx.workspace_id if ctx else UNAUTHENTICATED
        safe_reason = safe_error_message(decision.reason, config=self._config)

        if decision.outcome == "denied":
            self.audit.record(
                workspace_id=workspace,
                tool=tool_name,
                decision="denied",
                reason=safe_reason,
            )
            raise ToolError(safe_reason)

        if decision.outcome == "approval_required":
            self.audit.record(
                workspace_id=workspace,
                tool=tool_name,
                decision="approval_required",
                reason=safe_reason,
            )
            approval_payload = {
                "approval_required": True,
                "approval_id": decision.approval_id,
                "tool": requested_tool,
                "message": safe_reason,
            }
            if requested_tool != tool_name:
                approval_payload["capability_id"] = tool_name
            return ToolResult(structured_content=approval_payload)

        context.message.arguments = wrap_arguments(sanitized)
        requires_result_check = self.engine.requires_result_territory_check(
            ctx,
            tool_name,
        )
        authorized_sources: dict[str, object] = {}
        try:
            with (
                use_context(ctx),
                use_runtime_config(self._config),
                collect_authorized_sources() as collected_sources,
            ):
                result = await call_next(context)
                authorized_sources = dict(collected_sources)
        except Exception as exc:
            if requires_result_check:
                # Provider and tool exceptions are client-visible output. A
                # restricted search cannot release their untyped messages because
                # those strings may contain property data outside the territory.
                self.audit.record(
                    workspace_id=workspace,
                    tool=tool_name,
                    decision="denied",
                    reason=RESULT_TERRITORY_DENIAL,
                )
                raise ToolError(RESULT_TERRITORY_DENIAL) from None
            if ctx is not None and ctx.trusted:
                raise
            raise ToolError(
                safe_error_message(exc, config=self._config)
            )
        if requires_result_check:
            result_decision = self.engine.check_result(
                ctx,
                tool_name,
                _result_payloads(result),
                sanitized,
            )
            if result_decision.outcome == "denied":
                self.audit.record(
                    workspace_id=workspace,
                    tool=tool_name,
                    decision="denied",
                    reason=result_decision.reason,
                )
                raise ToolError(result_decision.reason)
        try:
            with use_context(ctx), use_runtime_config(self._config):
                result = sanitize_tool_result(
                    result,
                    authorized_records=tuple(authorized_sources.values()),
                    config=self._config,
                )
        except Exception as exc:
            if requires_result_check:
                self.audit.record(
                    workspace_id=workspace,
                    tool=tool_name,
                    decision="denied",
                    reason=RESULT_TERRITORY_DENIAL,
                )
                raise ToolError(RESULT_TERRITORY_DENIAL) from None
            if ctx is not None and ctx.trusted:
                raise
            raise ToolError(
                safe_error_message(exc, config=self._config)
            ) from None
        self.audit.record(
            workspace_id=workspace,
            tool=tool_name,
            decision="allowed",
            reason=safe_reason,
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
    config: Any | None = None,
    tool_call_resolver: ToolCallResolver | None = None,
    tool_visibility_resolver: ToolVisibilityResolver | None = None,
) -> Callable[[], None]:
    """Install access control on a FastMCP server; returns an uninstaller."""
    middleware = AccessMiddleware(
        registry=registry,
        audit_log=audit_log,
        identity_resolver=identity_resolver,
        capabilities=capabilities,
        runtime_mode=runtime_mode,
        config=config,
        tool_call_resolver=tool_call_resolver,
        tool_visibility_resolver=tool_visibility_resolver,
    )
    mcp.add_middleware(middleware)

    def uninstall() -> None:
        try:
            mcp.middleware.remove(middleware)
        except ValueError:
            pass

    return uninstall
