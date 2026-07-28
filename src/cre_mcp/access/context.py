"""Server-resolved tenant context.

A TenantContext is built exclusively from the server-side registry (or the
trusted local factory) — never from MCP arguments. The active context rides a
ContextVar so stores constructed during a tool call can resolve
workspace-scoped storage without threading parameters through 274 tools.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, ConfigDict, Field

from cre_mcp.access.profiles import Profile

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


_current: ContextVar[TenantContext | None] = ContextVar(
    "cre_access_context", default=None
)


def current_context() -> TenantContext | None:
    return _current.get()


@contextmanager
def use_context(ctx: TenantContext | None):
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def local_context() -> TenantContext:
    """The explicit trusted local workspace used by stdio mode."""
    return TenantContext(
        workspace_id=LOCAL_WORKSPACE_ID,
        profile=Profile.FULL_OPERATOR,
        trusted=True,
        display_name="Trusted local workspace",
    )
