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
0012) writes the minimum certified identity and authority a request needs.

The derivation happens once, in `AuthorityResolver`, so the context, the
admission outcome, the row-level-security session variables and every domain
repository's equality check all read the same values. Translating at this
boundary instead satisfies admission and finalization and silently breaks RLS.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from cre_mcp.platform.auth import DEFAULT_AUDIENCE, DEFAULT_RESOURCE
from cre_mcp.platform.projected_ids import (
    IDENTITY_NAMESPACE,
    ProjectedIdentityError,
    session_uuid,
    territory_uuid,
    user_uuid,
    workspace_uuid,
)

_PLATFORM_TO_CERTIFIED_ROLE = {
    "owner": "owner",
    "admin": "admin",
    "member": "member",
    "viewer": "viewer",
    "jv_partner": "jv_partner",
}


class IdentityProjectionUnavailable(RuntimeError):
    """One platform identity could not be projected for this request."""


# The derivation helpers live in `cre_mcp.platform.projected_ids` so
# `platform/authority.py` can use them without importing this package, and they
# raise `ProjectedIdentityError` rather than the class above. Callers of this
# module should catch either, so it is re-exported by name rather than
# swallowed into one type that would hide which layer refused.


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

    def ensure_authority(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        session_id: UUID,
        client_id: str,
        scopes: tuple[str, ...],
        audience: str,
        resource: str,
        access_expires_at: Any,
        profile: str,
        plan_key: str | None,
        daily_quotas: dict[str, int] | None,
        territories: tuple[str, ...],
        workspace_public_id: str,
    ) -> None:
        """Project the authority rows admission's credential CTE reads."""
        territory_values = [
            value.strip() for value in territories if value and value.strip()
        ]
        territory_ids = [
            territory_uuid(workspace_public_id, index, value)
            for index, value in enumerate(territory_values)
        ]
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute("SET search_path TO pg_catalog")
                connection.execute("SET ROLE medawarcre_admission")
                connection.execute(
                    "SELECT medawarcre.project_platform_authority("
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        workspace_id,
                        user_id,
                        session_id,
                        client_id,
                        list(scopes) or ["mcp:tools"],
                        audience,
                        resource,
                        access_expires_at,
                        profile,
                        plan_key,
                        Jsonb(dict(daily_quotas or {})),
                        territory_ids,
                        territory_values,
                    ),
                )
                connection.commit()
        except IdentityProjectionUnavailable:
            raise
        except psycopg.Error as error:
            raise IdentityProjectionUnavailable(
                f"authority projection failed ({type(error).__name__})"
            ) from None


class ProjectingAdmissionRepository:
    """Admit a platform-identified request against the certified schema.

    Wraps `PostgresAdmissionRepository`. On the way in it projects identity and
    swaps the platform's bigint-shaped actor and session identifiers for their
    derived uuids. On the way out it restores the platform values, because the
    domain repositories compare the outcome against the live `TenantContext`
    with `hmac.compare_digest` — an outcome carrying uuids and a context
    carrying `"41"` would be refused by every one of them.
    """

    def __init__(
        self,
        inner: Any,
        projection: PlatformIdentityProjection,
        *,
        session_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self._inner = inner
        self._projection = projection
        self._session_ttl = session_ttl

    def admit(self, context: Any, tool_name: str, arguments: dict, **kwargs: Any):
        actor = getattr(context, "actor_id", "")
        session = getattr(context, "session_id", "")
        workspace_public_id = getattr(context, "workspace_id", "")
        workspace_id, projected_user = self._projection.ensure(
            workspace_public_id=workspace_public_id,
            workspace_name=getattr(context, "display_name", "") or "",
            plan_key=getattr(context, "plan", None),
            platform_user_id=actor,
            user_email=f"{user_uuid(actor)}@platform.medawarcre.invalid",
            user_name=f"platform-user-{actor}",
            role="owner" if getattr(context, "profile", "") else "member",
        )
        self._projection.ensure_authority(
            workspace_id=workspace_id,
            user_id=projected_user,
            session_id=session_uuid(session),
            client_id=f"projected-{session_uuid(session)}",
            scopes=("mcp:tools",),
            audience=self._audience(),
            resource=self._resource(),
            # The projected session must not outlive the live one by more than
            # the window this request needs. It is bounded rather than copied
            # because `TenantContext` carries no expiry -- the live session was
            # already validated by AuthorityResolver on this request, and the
            # next request revalidates it before reaching here.
            access_expires_at=datetime.now(UTC) + self._session_ttl,
            profile=getattr(context, "profile", ""),
            plan_key=getattr(context, "plan", None),
            daily_quotas=dict(getattr(context, "quota_limits", {}) or {}),
            territories=tuple(getattr(context, "territories", ()) or ()),
            workspace_public_id=workspace_public_id,
        )
        # No translation on the way in or out. `AuthorityResolver` already puts
        # the certified uuids in the context when the PostgreSQL backend is
        # installed, so the context, the admission outcome, the RLS session
        # variables and every domain repository's `compare_digest` check all
        # see the same values. An earlier version translated here instead and
        # restored the platform ids on the outcome; that satisfied admission
        # and finalization and silently broke row-level security, because
        # `admitted_connection` sets `app.actor_user_id` from the outcome.
        return self._inner.admit(context, tool_name, arguments, **kwargs)

    def _audience(self) -> str:
        # Admission passes its own configured constants as `p_expected_*` and
        # the CTE compares them to the session row, so the projection has to
        # match the *repository's* values, not whatever the platform session
        # happened to record.
        return getattr(self._inner, "audience", DEFAULT_AUDIENCE)

    def _resource(self) -> str:
        return getattr(self._inner, "resource", DEFAULT_RESOURCE)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


__all__ = [
    "IDENTITY_NAMESPACE",
    "IdentityProjectionUnavailable",
    "ProjectedIdentityError",
    "PlatformIdentityProjection",
    "ProjectingAdmissionRepository",
    "certified_role",
    "session_uuid",
    "user_uuid",
    "workspace_uuid",
]
