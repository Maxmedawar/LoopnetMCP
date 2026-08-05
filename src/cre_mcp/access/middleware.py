"""Dual enforcement on the FastMCP server.

`on_list_tools` filters what a workspace can see; `on_call_tool` re-checks at
execution, sanitizes arguments, applies the approval gate, scopes storage to
the workspace for the duration of the call, and audits every decision.

Identity resolution is server-side only. Hosted HTTP accepts only the
authoritative FastMCP access-token claim produced by the OAuth verifier.
Trusted-local identity exists only when the caller explicitly selects the
stdio runtime. Missing context and dependency failures always fail closed.
"""

import asyncio
import json
import math
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

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
from cre_mcp.access.engine import (
    APPROVAL_ARG,
    AccessEngine,
    RESULT_TERRITORY_DENIAL,
)
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.domains import (
    HostedRequestRepositories,
    require_fresh_admission,
    use_hosted_request_repositories,
)
from cre_mcp.source_rights.gate import collect_authorized_sources
from cre_mcp.source_rights.attestations import (
    use_hosted_document_attestation_repository,
)
from cre_mcp.source_rights.output import safe_error_message, sanitize_tool_result

UNAUTHENTICATED = "(unauthenticated)"
ADMISSION_UNAVAILABLE = "access denied: request admission is unavailable"
EXECUTION_OWNERSHIP_UNAVAILABLE = (
    "access denied: request execution ownership is unavailable"
)
FINALIZATION_UNAVAILABLE = "access denied: request finalization is unavailable"
AUDIT_UNAVAILABLE = "access denied: request audit is unavailable"
DOMAIN_PERSISTENCE_UNAVAILABLE = (
    "access denied: hosted persistence is unavailable"
)
HOSTED_TOOL_FAILED = "tool execution failed"
HOSTED_RESULT_RELEASE_DENIED = "tool result could not be released"
MAX_REQUEST_BINDING_BYTES = 2048
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
        registry: WorkspaceRegistry | None,
        audit_log: AuditLog,
        identity_resolver: IdentityResolver | None = None,
        capabilities: dict[str, ToolCapability] | None = None,
        runtime_mode: Literal["stdio", "http"] | None = None,
        config: Any | None = None,
        tool_call_resolver: ToolCallResolver | None = None,
        tool_visibility_resolver: ToolVisibilityResolver | None = None,
        admission_repository: Any | None = None,
        domain_repository_provider: Any | None = None,
    ) -> None:
        if runtime_mode == "http" and (
            admission_repository is None or domain_repository_provider is None
        ):
            raise ValueError(
                "hosted HTTP requires atomic admission and domain repositories"
            )
        if runtime_mode != "http" and (
            admission_repository is not None or domain_repository_provider is not None
        ):
            raise ValueError(
                "hosted admission and domain repositories are available only to HTTP"
            )
        if runtime_mode != "http" and registry is None:
            raise ValueError("local access control requires a workspace registry")
        self.engine = AccessEngine(registry, capabilities)
        self.audit = audit_log
        self._resolve = identity_resolver or _default_resolver_for(runtime_mode)
        self._config = config
        self._resolve_tool_call = tool_call_resolver
        self._tool_is_visible = tool_visibility_resolver
        self._admission = admission_repository
        self._domain_repositories = domain_repository_provider

    @staticmethod
    def _valid_admission_binding(
        admission: object,
        context: TenantContext,
        tool_name: str,
        invocation_id: str,
        request_correlation_id: str,
    ) -> bool:
        if not isinstance(admission, AdmissionOutcome):
            return False
        try:
            UUID(admission.invocation_id)
            UUID(admission.request_correlation_id)
        except (ValueError, TypeError, AttributeError):
            return False
        if (
            admission.workspace_public_id != context.workspace_id
            or admission.actor_user_id != context.actor_id
            or admission.session_id != context.session_id
            or admission.tool_name != tool_name
            or admission.invocation_id != invocation_id
            or admission.request_correlation_id != request_correlation_id
            or admission.decision
            not in {"allowed", "denied", "approval_required"}
            or type(admission.reason_code) is not str
            or not admission.reason_code.strip()
            or type(admission.safe_reason) is not str
            or not admission.safe_reason.strip()
            or type(admission.replayed) is not bool
            or type(admission.finalized) is not bool
        ):
            return False
        if admission.decision == "approval_required":
            return admission.approval_id == admission.invocation_id
        return admission.approval_id is None

    @staticmethod
    def _hosted_request_binding(
        middleware_context: MiddlewareContext,
        tenant_context: TenantContext,
    ) -> tuple[str, str]:
        fastmcp_context = middleware_context.fastmcp_context
        if fastmcp_context is None or fastmcp_context.request_context is None:
            raise ValueError("hosted request context is unavailable")
        request_id = fastmcp_context.request_context.request_id
        transport_session_id = fastmcp_context.session_id
        if type(request_id) not in {str, int}:
            raise ValueError("hosted request id is invalid")
        if (
            type(transport_session_id) is not str
            or not transport_session_id
        ):
            raise ValueError("hosted transport session is invalid")
        binding = json.dumps(
            [
                tenant_context.workspace_id,
                tenant_context.actor_id,
                tenant_context.session_id,
                transport_session_id,
                type(request_id).__name__,
                request_id,
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        if len(binding.encode("utf-8")) > MAX_REQUEST_BINDING_BYTES:
            raise ValueError("hosted request binding is too large")
        invocation_id = uuid5(
            NAMESPACE_URL,
            f"https://medawarcre.com/mcp/invocation/{binding}",
        )
        request_correlation_id = uuid5(
            NAMESPACE_URL,
            f"https://medawarcre.com/mcp/request/{binding}",
        )
        return str(invocation_id), str(request_correlation_id)

    async def _record_audit(
        self,
        *,
        workspace_id: str,
        tool: str,
        decision: str,
        reason: str,
    ) -> None:
        if self._admission is None:
            self.audit.record(
                workspace_id=workspace_id,
                tool=tool,
                decision=decision,
                reason=reason,
            )
            return
        try:
            await asyncio.to_thread(
                self.audit.record,
                workspace_id=workspace_id,
                tool=tool,
                decision=decision,
                reason=reason,
            )
        except Exception:
            raise ToolError(AUDIT_UNAVAILABLE) from None

    async def _record_hosted_final(
        self,
        admission: AdmissionOutcome,
        *,
        succeeded: bool,
        reason_code: str,
        safe_reason: str,
    ) -> None:
        try:
            final_id = await asyncio.to_thread(
                self._admission.record_final,
                admission,
                succeeded=succeeded,
                reason_code=reason_code,
                safe_reason=safe_reason,
            )
            UUID(final_id)
        except Exception:
            raise ToolError(FINALIZATION_UNAVAILABLE) from None

    async def _admit_hosted(
        self,
        context: TenantContext,
        tool_name: str,
        sanitized: dict[str, Any],
        *,
        quota_bucket: str | None,
        requires_approval: bool,
        approval_token: object,
        invocation_id: str,
        request_correlation_id: str,
    ) -> AdmissionOutcome:
        task = asyncio.create_task(
            asyncio.to_thread(
                self._admission.admit,
                context,
                tool_name,
                sanitized,
                quota_bucket=quota_bucket,
                requires_approval=requires_approval,
                approval_token=approval_token if requires_approval else None,
                invocation_id=invocation_id,
                request_correlation_id=request_correlation_id,
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                admission = await task
            except Exception:
                raise
            if (
                self._valid_admission_binding(
                    admission,
                    context,
                    tool_name,
                    invocation_id,
                    request_correlation_id,
                )
                and admission.decision == "allowed"
                and not admission.replayed
                and not admission.finalized
            ):
                try:
                    await self._record_hosted_final(
                        admission,
                        succeeded=False,
                        reason_code="request_cancelled",
                        safe_reason="request cancelled before execution",
                    )
                except ToolError:
                    pass
            raise

    async def _bind_hosted_repositories(
        self,
        admission: AdmissionOutcome,
        context: TenantContext,
    ) -> HostedRequestRepositories:
        def bind() -> HostedRequestRepositories:
            with use_context(context):
                return self._domain_repositories.bind(admission)

        task = asyncio.create_task(
            asyncio.to_thread(bind)
        )
        try:
            repositories = await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except Exception:
                pass
            raise
        if (
            not isinstance(repositories, HostedRequestRepositories)
            or repositories.admission is not admission
        ):
            raise ValueError("hosted domain provider returned a mismatched scope")
        require_fresh_admission(repositories.admission)
        return repositories

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
        await self._record_audit(
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
                await self._record_audit(
                    workspace_id=workspace,
                    tool=requested_tool,
                    decision="denied",
                    reason=reason,
                )
                raise ToolError(reason)
            tool_name, args, wrap_arguments = resolved_call
        approval_token = args.get(APPROVAL_ARG) if isinstance(args, dict) else None
        if self._admission is None:
            decision, sanitized = self.engine.check_call(ctx, tool_name, args)
        else:
            decision, sanitized = self.engine.check_call_policy(
                ctx,
                tool_name,
                args,
            )
        workspace = ctx.workspace_id if ctx else UNAUTHENTICATED
        safe_reason = safe_error_message(decision.reason, config=self._config)

        if decision.outcome == "denied":
            await self._record_audit(
                workspace_id=workspace,
                tool=tool_name,
                decision="denied",
                reason=safe_reason,
            )
            raise ToolError(safe_reason)

        if decision.outcome == "approval_required":
            await self._record_audit(
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

        admission = None
        hosted_repositories = None
        if self._admission is not None:
            if ctx is None or ctx.trusted:
                raise ToolError(ADMISSION_UNAVAILABLE)
            quota_bucket, requires_approval = (
                self.engine.call_admission_requirements(tool_name, sanitized)
            )
            try:
                invocation_id, request_correlation_id = (
                    self._hosted_request_binding(context, ctx)
                )
                admission = await self._admit_hosted(
                    ctx,
                    tool_name,
                    sanitized,
                    quota_bucket=quota_bucket,
                    requires_approval=requires_approval,
                    approval_token=approval_token,
                    invocation_id=invocation_id,
                    request_correlation_id=request_correlation_id,
                )
            except Exception:
                raise ToolError(ADMISSION_UNAVAILABLE) from None
            if not self._valid_admission_binding(
                admission,
                ctx,
                tool_name,
                invocation_id,
                request_correlation_id,
            ):
                raise ToolError(ADMISSION_UNAVAILABLE)
            try:
                safe_reason = safe_error_message(
                    admission.safe_reason,
                    config=self._config,
                )
            except Exception:
                if (
                    admission.decision == "allowed"
                    and not admission.replayed
                    and not admission.finalized
                ):
                    await self._record_hosted_final(
                        admission,
                        succeeded=False,
                        reason_code="request_setup_failed",
                        safe_reason="request setup failed closed",
                    )
                raise ToolError(ADMISSION_UNAVAILABLE) from None
            if admission.decision == "denied":
                raise ToolError(safe_reason)
            if admission.decision == "approval_required":
                approval_payload = {
                    "approval_required": True,
                    "approval_id": admission.approval_id,
                    "tool": requested_tool,
                    "message": safe_reason,
                }
                if requested_tool != tool_name:
                    approval_payload["capability_id"] = tool_name
                return ToolResult(structured_content=approval_payload)
            if admission.replayed or admission.finalized:
                raise ToolError(EXECUTION_OWNERSHIP_UNAVAILABLE)
            try:
                hosted_repositories = await self._bind_hosted_repositories(
                    admission,
                    ctx,
                )
            except asyncio.CancelledError:
                try:
                    await self._record_hosted_final(
                        admission,
                        succeeded=False,
                        reason_code="request_cancelled",
                        safe_reason="request cancelled before execution",
                    )
                except ToolError:
                    pass
                raise
            except Exception:
                await self._record_hosted_final(
                    admission,
                    succeeded=False,
                    reason_code="request_setup_failed",
                    safe_reason="hosted persistence setup failed closed",
                )
                raise ToolError(DOMAIN_PERSISTENCE_UNAVAILABLE) from None

        try:
            context.message.arguments = wrap_arguments(sanitized)
            requires_result_check = self.engine.requires_result_territory_check(
                ctx,
                tool_name,
            )
        except Exception:
            if admission is not None:
                await self._record_hosted_final(
                    admission,
                    succeeded=False,
                    reason_code="request_setup_failed",
                    safe_reason="request setup failed closed",
                )
            else:
                await self._record_audit(
                    workspace_id=workspace,
                    tool=tool_name,
                    decision="denied",
                    reason="access denied: request setup failed",
                )
            raise ToolError("access denied: request setup failed") from None
        authorized_sources: dict[str, object] = {}
        try:
            with (
                use_context(ctx),
                use_runtime_config(self._config),
                use_hosted_request_repositories(hosted_repositories)
                if hosted_repositories is not None
                else nullcontext(),
                use_hosted_document_attestation_repository(
                    hosted_repositories.require("document")
                )
                if hosted_repositories is not None
                else nullcontext(),
                collect_authorized_sources() as collected_sources,
            ):
                result = await call_next(context)
                authorized_sources = dict(collected_sources)
        except asyncio.CancelledError:
            if admission is not None:
                try:
                    await self._record_hosted_final(
                        admission,
                        succeeded=False,
                        reason_code="request_cancelled",
                        safe_reason="request cancelled before completion",
                    )
                except ToolError:
                    pass
            raise
        except Exception as exc:
            if requires_result_check:
                # Provider and tool exceptions are client-visible output. A
                # restricted search cannot release their untyped messages because
                # those strings may contain property data outside the territory.
                if admission is None:
                    await self._record_audit(
                        workspace_id=workspace,
                        tool=tool_name,
                        decision="denied",
                        reason=RESULT_TERRITORY_DENIAL,
                    )
                else:
                    await self._record_hosted_final(
                        admission,
                        succeeded=False,
                        reason_code="result_policy_denied",
                        safe_reason=RESULT_TERRITORY_DENIAL,
                    )
                raise ToolError(RESULT_TERRITORY_DENIAL) from None
            if ctx is not None and ctx.trusted:
                raise
            if admission is not None:
                failure_reason = HOSTED_TOOL_FAILED
                await self._record_hosted_final(
                    admission,
                    succeeded=False,
                    reason_code="tool_failed",
                    safe_reason=failure_reason,
                )
            else:
                failure_reason = safe_error_message(exc, config=self._config)
            raise ToolError(failure_reason) from None
        if requires_result_check:
            try:
                result_decision = self.engine.check_result(
                    ctx,
                    tool_name,
                    _result_payloads(result),
                    sanitized,
                )
            except Exception:
                if admission is None:
                    await self._record_audit(
                        workspace_id=workspace,
                        tool=tool_name,
                        decision="denied",
                        reason=RESULT_TERRITORY_DENIAL,
                    )
                else:
                    await self._record_hosted_final(
                        admission,
                        succeeded=False,
                        reason_code="result_policy_denied",
                        safe_reason=RESULT_TERRITORY_DENIAL,
                    )
                raise ToolError(RESULT_TERRITORY_DENIAL) from None
            if result_decision.outcome == "denied":
                if admission is None:
                    await self._record_audit(
                        workspace_id=workspace,
                        tool=tool_name,
                        decision="denied",
                        reason=result_decision.reason,
                    )
                else:
                    await self._record_hosted_final(
                        admission,
                        succeeded=False,
                        reason_code="result_policy_denied",
                        safe_reason=result_decision.reason,
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
                if admission is None:
                    await self._record_audit(
                        workspace_id=workspace,
                        tool=tool_name,
                        decision="denied",
                        reason=RESULT_TERRITORY_DENIAL,
                    )
                else:
                    await self._record_hosted_final(
                        admission,
                        succeeded=False,
                        reason_code="result_policy_denied",
                        safe_reason=RESULT_TERRITORY_DENIAL,
                    )
                raise ToolError(RESULT_TERRITORY_DENIAL) from None
            if ctx is not None and ctx.trusted:
                raise
            if admission is not None:
                failure_reason = HOSTED_RESULT_RELEASE_DENIED
                await self._record_hosted_final(
                    admission,
                    succeeded=False,
                    reason_code="source_rights_denied",
                    safe_reason=failure_reason,
                )
            else:
                failure_reason = safe_error_message(exc, config=self._config)
            raise ToolError(failure_reason) from None
        if admission is None:
            await self._record_audit(
                workspace_id=workspace,
                tool=tool_name,
                decision="allowed",
                reason=safe_reason,
            )
        else:
            await self._record_hosted_final(
                admission,
                succeeded=True,
                reason_code="tool_completed",
                safe_reason="request completed",
            )
        return result


def install_access(
    mcp,
    *,
    registry: WorkspaceRegistry | None,
    audit_log: AuditLog,
    identity_resolver: IdentityResolver | None = None,
    capabilities: dict[str, ToolCapability] | None = None,
    runtime_mode: Literal["stdio", "http"] | None = None,
    config: Any | None = None,
    tool_call_resolver: ToolCallResolver | None = None,
    tool_visibility_resolver: ToolVisibilityResolver | None = None,
    admission_repository: Any | None = None,
    domain_repository_provider: Any | None = None,
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
        admission_repository=admission_repository,
        domain_repository_provider=domain_repository_provider,
    )
    mcp.add_middleware(middleware)

    def uninstall() -> None:
        try:
            mcp.middleware.remove(middleware)
        except ValueError:
            pass

    return uninstall
