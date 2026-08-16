"""Deterministic certified identifiers for platform-keyed identity.

The platform authority keys identity with bigints; the certified tenant schema
keys it with uuids, and row-level security compares those uuids. Somewhere the
two have to meet, and the only place that can be is where the hosted
``TenantContext`` is built — before admission parses it, before
``admitted_connection`` sets ``app.actor_user_id``, and before any domain
repository compares the context against the admission it was bound to. Anything
later has to translate in one direction and back, and each translation is a
place for the two to disagree.

The identifiers are derived rather than allocated — ``uuid5`` over one fixed
namespace and the platform key — so the same platform row always yields the
same certified row and no mapping table exists to drift.

This module holds only the derivation, with no imports beyond the standard
library, so both ``cre_mcp.platform.authority`` and ``cre_mcp.postgres`` can use
it without either importing the other.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

#: Fixed and never changed. Every derived identifier is a function of it, so
#: moving it re-points every hosted request at a tenant that does not exist.
IDENTITY_NAMESPACE = uuid5(NAMESPACE_URL, "https://medawarcre.com/identity/v1")


class ProjectedIdentityError(ValueError):
    """A platform identifier could not be given a certified equivalent."""


def _existing(value: object) -> UUID | None:
    """Return ``value`` as a uuid if it already is one.

    Derivation has to be idempotent: the context is built once and read many
    times, and a second application would silently produce a different tenant.
    """
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def workspace_uuid(public_id: str) -> UUID:
    normalized = str(public_id or "").strip()
    if not normalized:
        raise ProjectedIdentityError("workspace public id is required")
    return uuid5(IDENTITY_NAMESPACE, f"workspace/{normalized}")


def user_uuid(platform_user_id: object) -> UUID:
    existing = _existing(platform_user_id)
    if existing is not None:
        return existing
    normalized = str(platform_user_id or "").strip()
    if not normalized:
        raise ProjectedIdentityError("actor identifier is required")
    return uuid5(IDENTITY_NAMESPACE, f"user/{normalized}")


def session_uuid(platform_session_id: object) -> UUID:
    existing = _existing(platform_session_id)
    if existing is not None:
        return existing
    normalized = str(platform_session_id or "").strip()
    if not normalized:
        raise ProjectedIdentityError("session identifier is required")
    return uuid5(IDENTITY_NAMESPACE, f"session/{normalized}")


__all__ = [
    "IDENTITY_NAMESPACE",
    "ProjectedIdentityError",
    "session_uuid",
    "user_uuid",
    "workspace_uuid",
]
