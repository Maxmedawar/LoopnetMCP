"""Make one platform identity admissible by the certified tenant schema.

The platform authority keys identity with bigints; atomic admission and every
request-scoped domain repository key it with uuids. `admit()` calls
`_uuid(context.actor_id)` on a value like `"41"` and raises before it reaches
the database, so every hosted tool call failed with "request admission is
unavailable" while authorization, entitlement and territory all worked
correctly one layer above.

This module closes that without giving the product a second authority. The
uuids are *derived*, not allocated: `uuid5` over one fixed namespace and the
platform key, so the same platform row always yields the same certified row and
no mapping table can drift. `medawarcre.project_platform_identity` (migration
0012) writes the minimum certified identity a request needs, and the admission
outcome is handed back carrying the platform's own identifiers, so the equality
checks the domain repositories make against `TenantContext` still hold.
"""

from __future__ import annotations

import dataclasses
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg

#: Fixed and never changed. Every derived identifier below is a function of it,
#: so moving it re-points every hosted request at a tenant that does not exist.
IDENTITY_NAMESPACE = uuid5(NAMESPACE_URL, "https://medawarcre.com/identity/v1")

_PLATFORM_TO_CERTIFIED_ROLE = {
    "owner": "owner",
    "admin": "admin",
    "member": "member",
    "viewer": "viewer",
    "jv_partner": "jv_partner",
}


class IdentityProjectionUnavailable(RuntimeError):
    """One platform identity could not be projected for this request."""


def workspace_uuid(public_id: str) -> UUID:
    """The certified uuid for one platform workspace public identifier."""
    normalized = (public_id or "").strip()
    if not normalized:
        raise IdentityProjectionUnavailable("workspace public id is required")
    return uuid5(IDENTITY_NAMESPACE, f"workspace/{normalized}")


def user_uuid(platform_user_id: Any) -> UUID:
    """The certified uuid for one platform user row identifier."""
    normalized = str(platform_user_id or "").strip()
    if not normalized:
        raise IdentityProjectionUnavailable("actor identifier is required")
    return uuid5(IDENTITY_NAMESPACE, f"user/{normalized}")


def session_uuid(platform_session_id: Any) -> UUID:
    """The certified uuid for one platform OAuth session identifier."""
    normalized = str(platform_session_id or "").strip()
    if not normalized:
        raise IdentityProjectionUnavailable("session identifier is required")
    return uuid5(IDENTITY_NAMESPACE, f"session/{normalized}")


def certified_role(platform_role: str) -> str:
    """Map a platform membership role, refusing rather than widening."""
    mapped = _PLATFORM_TO_CERTIFIED_ROLE.get((platform_role or "").strip())
    if mapped is None:
        raise IdentityProjectionUnavailable(
            "platform membership role has no certified equivalent"
        )
    return mapped


class PlatformIdentityProjection:
    """Project the platform's identity for one request, idempotently."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("a PostgreSQL DSN is required")
        self._dsn = dsn.strip()

    def ensure(
        self,
        *,
        workspace_public_id: str,
        workspace_name: str,
        plan_key: str | None,
        platform_user_id: Any,
        user_email: str,
        user_name: str,
        role: str,
    ) -> tuple[UUID, UUID]:
        """Return (workspace uuid, user uuid), creating certified rows if new."""
        target_workspace = workspace_uuid(workspace_public_id)
        target_user = user_uuid(platform_user_id)
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute("SET search_path TO pg_catalog")
                # The admission login is NOINHERIT by contract, so its group's
                # EXECUTE grant is not active until the role is assumed. Without
                # this the call fails InsufficientPrivilege and the request is
                # refused with a message that names neither the role nor the
                # function.
                connection.execute("SET ROLE medawarcre_admission")
                row = connection.execute(
                    "SELECT medawarcre.project_platform_identity("
                    "%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        target_workspace,
                        workspace_public_id.strip(),
                        (workspace_name or workspace_public_id).strip(),
                        plan_key,
                        target_user,
                        user_email,
                        user_name,
                        certified_role(role),
                    ),
                ).fetchone()
                connection.commit()
        except IdentityProjectionUnavailable:
            raise
        except psycopg.Error as error:
            # Not chained: a psycopg error can echo the DSN it could not parse.
            raise IdentityProjectionUnavailable(
                f"identity projection failed ({type(error).__name__})"
            ) from None
        if row is None or row[0] is None:
            raise IdentityProjectionUnavailable("identity projection returned no row")
        return UUID(str(row[0])), target_user


class ProjectingAdmissionRepository:
    """Admit a platform-identified request against the certified schema.

    Wraps `PostgresAdmissionRepository`. On the way in it projects identity and
    swaps the platform's bigint-shaped actor and session identifiers for their
    derived uuids. On the way out it restores the platform values, because the
    domain repositories compare the outcome against the live `TenantContext`
    with `hmac.compare_digest` — an outcome carrying uuids and a context
    carrying `"41"` would be refused by every one of them.
    """

    def __init__(self, inner: Any, projection: PlatformIdentityProjection) -> None:
        self._inner = inner
        self._projection = projection

    def admit(self, context: Any, tool_name: str, arguments: dict, **kwargs: Any):
        actor = getattr(context, "actor_id", "")
        session = getattr(context, "session_id", "")
        self._projection.ensure(
            workspace_public_id=getattr(context, "workspace_id", ""),
            workspace_name=getattr(context, "display_name", "") or "",
            plan_key=getattr(context, "plan", None),
            platform_user_id=actor,
            user_email=f"{user_uuid(actor)}@platform.medawarcre.invalid",
            user_name=f"platform-user-{actor}",
            role="owner" if getattr(context, "profile", "") else "member",
        )
        projected = context.model_copy(
            update={
                "actor_id": str(user_uuid(actor)),
                "session_id": str(session_uuid(session)),
            }
        )
        outcome = self._inner.admit(projected, tool_name, arguments, **kwargs)
        return dataclasses.replace(
            outcome,
            actor_user_id=str(actor),
            session_id=str(session),
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


__all__ = [
    "IDENTITY_NAMESPACE",
    "IdentityProjectionUnavailable",
    "PlatformIdentityProjection",
    "ProjectingAdmissionRepository",
    "certified_role",
    "session_uuid",
    "user_uuid",
    "workspace_uuid",
]
