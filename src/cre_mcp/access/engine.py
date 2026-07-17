"""The authorization engine.

Decision order (spec): active -> matrix (default-deny in cloud) -> profile ->
territory -> ownership -> quota -> approval. The engine never derives
identity from arguments; it strips identity-shaped and storage-path arguments
in cloud mode before the tool ever sees them.
"""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel

from cre_mcp.access.capabilities import CAPABILITIES, ToolCapability
from cre_mcp.access.context import TenantContext
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.access.territory import location_state, location_within

# Arguments a client might use to smuggle identity; server context always wins.
RESERVED_IDENTITY_ARGS = frozenset(
    {"workspace_id", "workspace", "role", "profile", "territory", "territories", "owner_workspace"}
)
# Arguments that would let a client choose storage locations.
STORAGE_ARGS = frozenset({"db_path", "watch_db_path"})
APPROVAL_ARG = "_approval_id"


class Decision(BaseModel):
    outcome: Literal["allowed", "denied", "approval_required"]
    reason: str = ""
    approval_id: str | None = None


def _denied(reason: str) -> Decision:
    return Decision(outcome="denied", reason=reason)


def args_fingerprint(args: dict) -> str:
    canonical = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _has_value(value: object) -> bool:
    """Whether a supplied argument counts as present for the approval gate.

    ``None``, an empty string, and empty containers read as absent; every
    other value — crucially numeric ``0`` and ``False`` — reads as present.
    (A plain ``not in (None, False, "")`` test wrongly drops ``0`` because
    ``0 == False`` in Python.)
    """
    if value is None:
        return False
    if isinstance(value, (str, bytes, list, tuple, set, dict)):
        return len(value) > 0
    return True


def _territory_values(value: object) -> tuple[str, ...]:
    """Normalize scalar and list-valued location arguments for enforcement."""
    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )
    return ()


class AccessEngine:
    def __init__(
        self,
        registry: WorkspaceRegistry,
        capabilities: dict[str, ToolCapability] | None = None,
    ) -> None:
        self.registry = registry
        self.capabilities = CAPABILITIES if capabilities is None else capabilities

    def _gate(self, ctx: TenantContext | None, tool_name: str) -> tuple[Decision, ToolCapability | None]:
        """Checks shared by listing and execution: identity, active, matrix, profile."""
        if ctx is None:
            return _denied("access denied: no authenticated workspace"), None
        if not ctx.active:
            return _denied("access denied: workspace access is inactive"), None
        if ctx.trusted:
            return Decision(outcome="allowed"), None
        cap = self.capabilities.get(tool_name)
        if cap is None:
            return _denied(f"access denied: unclassified tool {tool_name!r}"), None
        if ctx.profile.value not in cap.allowed_profiles:
            return _denied(
                f"access denied: profile {ctx.profile.value!r} may not use {tool_name!r}"
            ), cap
        return Decision(outcome="allowed"), cap

    def check_tool(self, ctx: TenantContext | None, tool_name: str) -> Decision:
        """Listing-level check (no arguments yet)."""
        decision, _cap = self._gate(ctx, tool_name)
        return decision

    def check_call(
        self, ctx: TenantContext | None, tool_name: str, args: dict | None
    ) -> tuple[Decision, dict]:
        """Execution-level check. Returns the decision and sanitized args."""
        args = dict(args or {})
        approval_id = args.pop(APPROVAL_ARG, None)

        decision, cap = self._gate(ctx, tool_name)
        if decision.outcome != "allowed":
            return decision, args
        if ctx.trusted:
            # Trusted local workspace: current behavior, including explicit
            # db_path arguments, is preserved.
            return decision, args

        fingerprint = args_fingerprint(args)
        # Identity-shaped names are stripped so a client can never smuggle
        # identity — EXCEPT where a tool legitimately declares one as a
        # business parameter (e.g. verify_license's `role`, set_buyer_profile's
        # `profile`). Storage-path args are always stripped in cloud mode.
        preserved = cap.preserve_params if cap is not None else ()
        sanitized = {
            key: value
            for key, value in args.items()
            if not (
                (key in RESERVED_IDENTITY_ARGS and key not in preserved)
                or key in STORAGE_ARGS
            )
        }

        if ctx.profile in TERRITORY_LIMITED and cap is not None:
            any_value = False
            has_in_scope_value = False
            for param in cap.territory_params:
                raw = sanitized.get(param)
                # Each item of a list-valued argument is an independent target,
                # so it must resolve inside the territory on its own — an
                # unresolvable list item (e.g. a bare city with no state) is
                # outside by definition and denied even beside an in-scope
                # sibling. A scalar argument that cannot be resolved at all is a
                # non-locating component (e.g. a street line) and is tolerated
                # so long as some other argument establishes the territory.
                is_collection = isinstance(raw, (list, tuple, set))
                for value in _territory_values(raw):
                    any_value = True
                    if location_within(value, ctx.territories):
                        has_in_scope_value = True
                    elif is_collection or location_state(value) is not None:
                        return _denied(
                            f"access denied: {value!r} is outside this workspace's territory"
                        ), sanitized
            if cap.territory_params and not any_value:
                return _denied(
                    "access denied: a resolvable territory argument is required"
                ), sanitized
            if any_value and not has_in_scope_value:
                return _denied(
                    "access denied: the supplied location could not be resolved to this workspace's territory"
                ), sanitized

        if cap is not None and cap.quota:
            limits = self.registry.plan_quotas(ctx.plan)
            limit = limits.get(cap.quota)
            if limit is not None and self.registry.usage_today(
                ctx.workspace_id, cap.quota
            ) >= limit:
                return _denied(
                    f"access denied: daily quota exceeded for {cap.quota!r}"
                ), sanitized

        is_sensitive = cap is not None and (
            cap.sensitive
            or any(_has_value(sanitized.get(p)) for p in cap.sensitive_params)
        )
        if is_sensitive:
            if approval_id is not None:
                if not self.registry.consume_approval(
                    approval_id, ctx.workspace_id, tool_name, fingerprint
                ):
                    return _denied(
                        "access denied: approval is missing, ungranted, spent, or does not match this call"
                    ), sanitized
            else:
                pending = self.registry.request_approval(
                    ctx.workspace_id, tool_name, fingerprint
                )
                return Decision(
                    outcome="approval_required",
                    reason=f"sensitive transaction action {tool_name!r} requires approval",
                    approval_id=pending,
                ), sanitized

        if cap is not None and cap.quota:
            self.registry.record_usage(ctx.workspace_id, cap.quota)
        return Decision(outcome="allowed"), sanitized
