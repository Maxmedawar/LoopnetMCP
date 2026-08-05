"""Request-scoped PostgreSQL provider entitlement projections."""

from __future__ import annotations

import asyncio
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import UUID

from psycopg.rows import dict_row

from cre_mcp.access.context import TenantContext, current_context
from cre_mcp.access.profiles import Profile
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.domains import (
    current_hosted_request_repositories,
    require_fresh_admission,
)
from cre_mcp.postgres.pool import PostgresDatabase

_UNAVAILABLE = "provider persistence unavailable"
_PROVIDERS = frozenset({"stripe", "skool"})
_SUBSCRIPTION_STATUSES = frozenset(
    {
        "trialing",
        "active",
        "past_due",
        "grace_period",
        "paused",
        "canceled",
        "unpaid",
        "incomplete",
    }
)
_GRANT_SCOPES = frozenset({"subject", "workspace"})
_GRANT_SOURCES = frozenset({"stripe", "skool", "manual", "jv", "promotion"})
_GRANT_STATUSES = frozenset(
    {"pending", "active", "overridden", "expiring", "expired", "revoked"}
)
_PROFILES = frozenset(profile.value for profile in Profile)

_ROW_FIELDS = frozenset(
    {
        "record_kind",
        "workspace_id",
        "actor_user_id",
        "id",
        "subject_user_id",
        "provider",
        "scope",
        "source",
        "profile",
        "plan_key",
        "status",
        "starts_at",
        "ends_at",
        "current_period_end",
        "last_event_at",
        "created_at",
        "updated_at",
    }
)

_PROVIDER_ENTITLEMENT_QUERY = """
WITH request_scope AS (
    SELECT medawarcre.current_workspace_id() AS workspace_id,
           medawarcre.current_actor_user_id() AS actor_user_id
), projected AS (
    SELECT 0 AS sort_kind,
           ''::text AS sort_source,
           'scope'::text AS record_kind,
           request_scope.workspace_id,
           request_scope.actor_user_id,
           NULL::uuid AS id,
           NULL::uuid AS subject_user_id,
           NULL::text AS provider,
           NULL::text AS scope,
           NULL::text AS source,
           NULL::text AS profile,
           NULL::text AS plan_key,
           NULL::text AS status,
           NULL::timestamptz AS starts_at,
           NULL::timestamptz AS ends_at,
           NULL::timestamptz AS current_period_end,
           NULL::timestamptz AS last_event_at,
           NULL::timestamptz AS created_at,
           NULL::timestamptz AS updated_at
    FROM request_scope

    UNION ALL

    SELECT 1,
           subscription.provider,
           'subscription'::text,
           request_scope.workspace_id,
           request_scope.actor_user_id,
           subscription.id,
           NULL::uuid,
           subscription.provider,
           NULL::text,
           NULL::text,
           NULL::text,
           subscription.plan_key,
           subscription.status,
           NULL::timestamptz,
           NULL::timestamptz,
           subscription.current_period_end,
           subscription.last_event_at,
           subscription.created_at,
           subscription.updated_at
    FROM request_scope
    JOIN medawarcre.subscriptions subscription
      ON subscription.workspace_id = request_scope.workspace_id

    UNION ALL

    SELECT 2,
           access_grant.source || ':' || access_grant.scope,
           'grant'::text,
           request_scope.workspace_id,
           request_scope.actor_user_id,
           access_grant.id,
           access_grant.subject_user_id,
           NULL::text,
           access_grant.scope,
           access_grant.source,
           access_grant.profile,
           access_grant.plan_key,
           access_grant.status,
           access_grant.starts_at,
           access_grant.ends_at,
           NULL::timestamptz,
           NULL::timestamptz,
           access_grant.created_at,
           access_grant.updated_at
    FROM request_scope
    JOIN medawarcre.access_grants access_grant
      ON access_grant.workspace_id = request_scope.workspace_id
     AND (
            access_grant.scope = 'workspace'
            OR access_grant.subject_user_id = request_scope.actor_user_id
         )
)
SELECT record_kind,
       workspace_id,
       actor_user_id,
       id,
       subject_user_id,
       provider,
       scope,
       source,
       profile,
       plan_key,
       status,
       starts_at,
       ends_at,
       current_period_end,
       last_event_at,
       created_at,
       updated_at
FROM projected
ORDER BY sort_kind, sort_source COLLATE "C", id NULLS FIRST
"""


class ProviderPersistenceUnavailable(RuntimeError):
    """The exact hosted provider projection cannot complete safely."""


@dataclass(frozen=True)
class ProviderSubscription:
    id: str
    workspace_id: str
    provider: str
    status: str
    plan_key: str
    current_period_end: str | None
    last_event_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ProviderAccessGrant:
    id: str
    workspace_id: str
    subject_user_id: str | None
    scope: str
    source: str
    profile: Profile
    plan_key: str | None
    status: str
    starts_at: str
    ends_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ProviderEntitlementSnapshot:
    workspace_id: str
    actor_user_id: str
    subscriptions: tuple[ProviderSubscription, ...]
    grants: tuple[ProviderAccessGrant, ...]


async def _finish_thread_before_cancellation(function: Any, *args: Any) -> Any:
    """Keep a worker inside its request lease before cancellation escapes."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        try:
            task.result()
        except Exception:
            pass
        raise


def _uuid_text(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("invalid provider UUID") from error


def _text(
    value: object,
    *,
    maximum: int,
    nullable: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value) > maximum
    ):
        raise ValueError("invalid provider text")
    return value


def _enum(value: object, allowed: frozenset[str]) -> str:
    selected = _text(value, maximum=64)
    if selected not in allowed:
        raise ValueError("invalid provider enum")
    return selected


def _utc_text(value: object) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("invalid provider timestamp")
    return value.astimezone(UTC).isoformat()


def _nullable_utc_text(value: object) -> str | None:
    return None if value is None else _utc_text(value)


def _require_shape(row: Mapping[str, object]) -> None:
    if frozenset(row) != _ROW_FIELDS:
        raise ValueError("invalid provider row shape")


def _subscription(
    row: Mapping[str, object],
    *,
    workspace_id: str,
) -> ProviderSubscription:
    if any(
        row[name] is not None
        for name in (
            "subject_user_id",
            "scope",
            "source",
            "profile",
            "starts_at",
            "ends_at",
        )
    ):
        raise ValueError("invalid provider subscription projection")
    return ProviderSubscription(
        id=_uuid_text(row["id"]),
        workspace_id=workspace_id,
        provider=_enum(row["provider"], _PROVIDERS),
        status=_enum(row["status"], _SUBSCRIPTION_STATUSES),
        plan_key=_text(row["plan_key"], maximum=128) or "",
        current_period_end=_nullable_utc_text(row["current_period_end"]),
        last_event_at=_utc_text(row["last_event_at"]),
        created_at=_utc_text(row["created_at"]),
        updated_at=_utc_text(row["updated_at"]),
    )


def _grant(
    row: Mapping[str, object],
    *,
    workspace_id: str,
    actor_user_id: str,
) -> ProviderAccessGrant:
    if any(
        row[name] is not None
        for name in ("provider", "current_period_end", "last_event_at")
    ):
        raise ValueError("invalid provider grant projection")
    scope = _enum(row["scope"], _GRANT_SCOPES)
    source = _enum(row["source"], _GRANT_SOURCES)
    subject_user_id = (
        None
        if row["subject_user_id"] is None
        else _uuid_text(row["subject_user_id"])
    )
    if scope == "workspace":
        if source != "jv" or subject_user_id is not None:
            raise ValueError("invalid workspace provider grant")
    elif subject_user_id != actor_user_id:
        raise ValueError("invalid subject provider grant")
    starts_at = _utc_text(row["starts_at"])
    ends_at = _nullable_utc_text(row["ends_at"])
    if ends_at is not None:
        starts_value = datetime.fromisoformat(starts_at)
        ends_value = datetime.fromisoformat(ends_at)
        if ends_value <= starts_value:
            raise ValueError("invalid provider grant lease")
    elif source in _PROVIDERS:
        raise ValueError("invalid provider grant lease")
    return ProviderAccessGrant(
        id=_uuid_text(row["id"]),
        workspace_id=workspace_id,
        subject_user_id=subject_user_id,
        scope=scope,
        source=source,
        profile=Profile(_enum(row["profile"], _PROFILES)),
        plan_key=_text(row["plan_key"], maximum=128, nullable=True),
        status=_enum(row["status"], _GRANT_STATUSES),
        starts_at=starts_at,
        ends_at=ends_at,
        created_at=_utc_text(row["created_at"]),
        updated_at=_utc_text(row["updated_at"]),
    )


def _snapshot(
    rows: list[Mapping[str, object]],
    admission: AdmissionOutcome,
) -> ProviderEntitlementSnapshot:
    if not rows:
        raise ValueError("missing provider request scope")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("invalid provider row")
        _require_shape(row)

    scope_row = rows[0]
    if scope_row["record_kind"] != "scope" or any(
        scope_row[name] is not None
        for name in _ROW_FIELDS
        if name not in {"record_kind", "workspace_id", "actor_user_id"}
    ):
        raise ValueError("invalid provider request scope")
    workspace_id = _uuid_text(scope_row["workspace_id"])
    actor_user_id = _uuid_text(scope_row["actor_user_id"])
    if actor_user_id != _uuid_text(admission.actor_user_id):
        raise ValueError("provider admission mismatch")

    subscriptions: list[ProviderSubscription] = []
    grants: list[ProviderAccessGrant] = []
    seen_ids: set[str] = set()
    kinds: list[str] = []
    for row in rows[1:]:
        record_kind = _text(row["record_kind"], maximum=32) or ""
        kinds.append(record_kind)
        if (
            _uuid_text(row["workspace_id"]) != workspace_id
            or _uuid_text(row["actor_user_id"]) != actor_user_id
        ):
            raise ValueError("provider request scope mismatch")
        if record_kind == "subscription":
            item: ProviderSubscription | ProviderAccessGrant = _subscription(
                row,
                workspace_id=workspace_id,
            )
            subscriptions.append(item)
        elif record_kind == "grant":
            item = _grant(
                row,
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )
            grants.append(item)
        else:
            raise ValueError("invalid provider record kind")
        if item.id in seen_ids:
            raise ValueError("duplicate provider identifier")
        seen_ids.add(item.id)

    expected_kinds = ["subscription"] * len(subscriptions) + ["grant"] * len(grants)
    if kinds != expected_kinds:
        raise ValueError("invalid provider record order")
    if subscriptions != sorted(
        subscriptions,
        key=lambda item: (item.provider, item.id),
    ):
        raise ValueError("non-deterministic provider subscription order")
    if grants != sorted(
        grants,
        key=lambda item: (item.source, item.scope, item.id),
    ):
        raise ValueError("non-deterministic provider grant order")

    return ProviderEntitlementSnapshot(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        subscriptions=tuple(subscriptions),
        grants=tuple(grants),
    )


class PostgresProviderRepository:
    """Read safe provider entitlement projections for one exact request."""

    def __init__(
        self,
        database: PostgresDatabase,
        admission: AdmissionOutcome,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise TypeError("provider repository requires PostgreSQL")
        self._database = database
        self._admission = require_fresh_admission(admission)

    def _require_active_scope(self) -> TenantContext:
        repositories = current_hosted_request_repositories()
        context = current_context()
        if (
            repositories is None
            or repositories.admission is not self._admission
            or repositories.require("provider") is not self
            or not isinstance(context, TenantContext)
            or context.trusted
            or not context.active
        ):
            raise ProviderPersistenceUnavailable(_UNAVAILABLE)
        comparisons = (
            (context.workspace_id, self._admission.workspace_public_id),
            (context.actor_id, self._admission.actor_user_id),
            (context.session_id, self._admission.session_id),
        )
        if any(
            not left
            or not right
            or not hmac.compare_digest(left, right)
            for left, right in comparisons
        ):
            raise ProviderPersistenceUnavailable(_UNAVAILABLE)
        return context

    def _get_snapshot(self) -> ProviderEntitlementSnapshot:
        self._require_active_scope()
        with self._database.admitted_connection(self._admission) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(_PROVIDER_ENTITLEMENT_QUERY).fetchall()
        self._require_active_scope()
        return _snapshot(rows, self._admission)

    async def get_snapshot(self) -> ProviderEntitlementSnapshot:
        """Return one coherent safe projection for the exact active request."""
        try:
            self._require_active_scope()
            result = await _finish_thread_before_cancellation(self._get_snapshot)
            self._require_active_scope()
            if not isinstance(result, ProviderEntitlementSnapshot):
                raise ValueError("invalid provider result")
            return result
        except asyncio.CancelledError:
            raise
        except ProviderPersistenceUnavailable:
            raise
        except Exception as error:
            raise ProviderPersistenceUnavailable(_UNAVAILABLE) from error


__all__ = [
    "PostgresProviderRepository",
    "ProviderAccessGrant",
    "ProviderEntitlementSnapshot",
    "ProviderPersistenceUnavailable",
    "ProviderSubscription",
]
