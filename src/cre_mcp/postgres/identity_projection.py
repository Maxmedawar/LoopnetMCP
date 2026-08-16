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

from cre_mcp.platform.auth import DEFAULT_AUDIENCE, DEFAULT_RESOURCE
from cre_mcp.platform.projected_ids import (
    IDENTITY_NAMESPACE,
    ProjectedIdentityError,
    session_uuid,
    user_uuid,
    workspace_uuid,
)

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
    """Copy the platform authority's own rows into the certified schema.

    Every method takes identifiers and nothing else. The values -- workspace
    name, user email, membership role, account state, grant profile and plan,
    quota limits, territories -- are read from the `platform_*` relations
    inside the SECURITY DEFINER function, so a caller cannot supply them and a
    row the platform authority does not hold cannot be projected.

    That is a correction, not a design note. Migration 0012 accepted those
    values as arguments, and an independent review projected a workspace that
    did not exist, with `full_operator` and a quota of 999999, straight into
    the certified schema. Migration 0013 replaced both functions.
    """

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("a PostgreSQL DSN is required")
        self._dsn = dsn.strip()

    def _call(self, statement: str, parameters: tuple, *, label: str):
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute("SET search_path TO pg_catalog")
                # The admission login is NOINHERIT by contract, so its group's
                # EXECUTE grant is not active until the role is assumed.
                connection.execute("SET ROLE medawarcre_admission")
                row = connection.execute(statement, parameters).fetchone()
                connection.commit()
                return row
        except psycopg.Error as error:
            # Not chained: a psycopg error can echo the DSN it could not parse.
            raise IdentityProjectionUnavailable(
                f"{label} failed ({type(error).__name__})"
            ) from None

    def ensure(
        self,
        *,
        workspace_public_id: str,
        platform_user_id: Any,
    ) -> tuple[UUID, UUID]:
        """Return (workspace uuid, user uuid), refusing an unknown identity."""
        target_workspace = workspace_uuid(workspace_public_id)
        target_user = user_uuid(platform_user_id)
        row = self._call(
            "SELECT medawarcre.project_platform_identity(%s,%s,%s,%s)",
            (
                target_workspace,
                workspace_public_id.strip(),
                target_user,
                int(platform_user_id),
            ),
            label="identity projection",
        )
        if row is None or row[0] is None:
            raise IdentityProjectionUnavailable("identity projection returned no row")
        return UUID(str(row[0])), target_user

    def ensure_authority(
        self,
        *,
        workspace_id: UUID,
        workspace_public_id: str,
        user_id: UUID,
        platform_user_id: Any,
        session_id: UUID,
        platform_session_id: str,
        audience: str,
        resource: str,
    ) -> None:
        """Project the authority rows admission's credential CTE reads."""
        self._call(
            "SELECT medawarcre.project_platform_authority(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                workspace_id,
                workspace_public_id.strip(),
                user_id,
                int(platform_user_id),
                session_id,
                str(platform_session_id),
                audience,
                resource,
            ),
            label="authority projection",
        )


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
        actor = getattr(context, "platform_actor_id", "") or ""
        session = getattr(context, "platform_session_id", "") or ""
        workspace_public_id = getattr(context, "workspace_id", "")
        if not actor or not session:
            # The context did not come from AuthorityResolver on the hosted
            # backend. Refused rather than projected: the platform keys are how
            # the projection finds the rows it is allowed to copy, and without
            # them it would have nothing to check the caller against.
            raise IdentityProjectionUnavailable(
                "hosted admission requires a resolver-issued platform identity"
            )
        workspace_id, projected_user = self._projection.ensure(
            workspace_public_id=workspace_public_id,
            platform_user_id=actor,
        )
        self._projection.ensure_authority(
            workspace_id=workspace_id,
            workspace_public_id=workspace_public_id,
            user_id=projected_user,
            platform_user_id=actor,
            session_id=session_uuid(session),
            platform_session_id=session,
            audience=self._audience(),
            resource=self._resource(),
        )
        # No translation on the way in or out. `AuthorityResolver` already puts
        # the certified uuids in the context when the PostgreSQL backend is
        # installed, so the context, the admission outcome, the RLS session
        # variables and every domain repository's `compare_digest` check all
        # see the same values.
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
    "session_uuid",
    "user_uuid",
    "workspace_uuid",
]
