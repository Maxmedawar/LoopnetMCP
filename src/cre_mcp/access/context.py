"""Server-resolved tenant context.

A TenantContext is built exclusively from the server-side registry (or the
trusted local factory) — never from MCP arguments. The active context rides a
ContextVar so stores constructed during a tool call can resolve
workspace-scoped storage without threading parameters through 274 tools.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from cre_mcp.access.profiles import Profile

if TYPE_CHECKING:
    from cre_mcp.config import CreConfig

LOCAL_WORKSPACE_ID = "local"


class TenantContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: str
    profile: Profile
    plan: str = "standard"
    quota_limits: dict[str, int] = Field(default_factory=dict)
    territories: tuple[str, ...] = ()
    active: bool = True
    trusted: bool = False
    display_name: str = ""
    actor_id: str = ""
    session_id: str = ""
    # The platform authority's own keys for the same actor and session.
    #
    # On the hosted PostgreSQL backend `actor_id` and `session_id` carry the
    # derived certified uuids, because atomic admission parses them as uuids and
    # row-level security compares them. The identity projection still needs the
    # bigint and the session string, because they are how it finds the
    # `platform_*` rows it is allowed to copy — and being unable to find them is
    # what stops it projecting a tenant that does not exist.
    #
    # Empty on the local file-backed default, where `actor_id` is already the
    # platform key and nothing projects.
    platform_actor_id: str = ""
    platform_session_id: str = ""


_current: ContextVar[TenantContext | None] = ContextVar(
    "cre_access_context", default=None
)
_runtime_config: ContextVar[CreConfig | None] = ContextVar(
    "cre_runtime_config", default=None
)


def current_context() -> TenantContext | None:
    return _current.get()


def current_runtime_config() -> "CreConfig | None":
    """Return the server-owned config bound to the active tool request."""
    return _runtime_config.get()


def workspace_runtime_config(
    config: "CreConfig | None",
    ctx: TenantContext | None = None,
) -> "CreConfig | None":
    """Copy startup configuration onto the active workspace storage path.

    Hosted servers construct configuration before an authenticated request
    exists.  Binding that process-global object verbatim would therefore put
    every tenant on the same cache database.  Only the storage path varies;
    secrets, source toggles, and registry paths remain server-owned values.
    """
    selected_context = current_context() if ctx is None else ctx
    if config is None or selected_context is None or selected_context.trusted:
        return config
    from cre_mcp.access.storage import workspace_db_path

    scoped_path = workspace_db_path(selected_context, config.cache_db_path)
    if scoped_path == config.cache_db_path:
        return config
    return config.model_copy(update={"cache_db_path": scoped_path})


def resolve_runtime_config(config: "CreConfig | None" = None) -> "CreConfig":
    """Prefer the active server-owned config over stale or ambient settings.

    Egress-capable objects can outlive one request.  The request ContextVar is
    therefore authoritative even when a caller passes a config captured by a
    process-global service.  Outside a request, explicit configuration keeps
    its normal precedence and the environment remains the final fallback.
    """
    runtime = current_runtime_config()
    if runtime is not None:
        return runtime
    if config is not None:
        return config
    from cre_mcp.config import CreConfig

    return CreConfig()


@contextmanager
def use_context(ctx: TenantContext | None):
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


@contextmanager
def use_runtime_config(config: "CreConfig | None"):
    """Bind immutable server configuration to nested request boundaries."""
    scoped_config = workspace_runtime_config(config)
    token = _runtime_config.set(scoped_config)
    try:
        yield scoped_config
    finally:
        _runtime_config.reset(token)


def local_context() -> TenantContext:
    """The explicit trusted local workspace used by stdio mode."""
    return TenantContext(
        workspace_id=LOCAL_WORKSPACE_ID,
        profile=Profile.FULL_OPERATOR,
        trusted=True,
        display_name="Trusted local workspace",
    )
