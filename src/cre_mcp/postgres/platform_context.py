"""Request-scoped PostgreSQL authority for the current platform context."""

from __future__ import annotations

import asyncio
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

from psycopg.rows import dict_row

from cre_mcp.access.context import TenantContext, current_context
from cre_mcp.access.quota import is_canonical_quota_bucket
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.domains import (
    current_hosted_request_repositories,
    require_fresh_admission,
)
from cre_mcp.postgres.pool import PostgresDatabase

_UNAVAILABLE = "platform-context persistence unavailable"
_USER_STATES = frozenset({"active", "disabled", "deletion_pending", "deleted"})
_WORKSPACE_STATES = frozenset(
    {
        "registered",
        "active",
        "past_due",
        "suspended",
        "deletion_pending",
        "deleted",
    }
)
_MEMBERSHIP_ROLES = frozenset(
    {"owner", "admin", "member", "viewer", "jv_partner"}
)
_ACCOUNT_STATES = frozenset(
    {
        "invited",
        "registered",
        "verified",
        "active",
        "past_due",
        "grace_period",
        "suspended",
        "under_review",
        "canceled",
        "deletion_pending",
        "deleted",
    }
)

_PLATFORM_CONTEXT_QUERY = """
SELECT
    actor.id AS user_id,
    actor.email AS user_email,
    actor.name AS user_name,
    actor.state AS user_state,
    actor.created_at AS user_created_at,
    actor.updated_at AS user_updated_at,
    workspace.id AS workspace_id,
    workspace.public_id AS workspace_public_id,
    workspace.name AS workspace_name,
    workspace.slug AS workspace_slug,
    workspace.state AS workspace_state,
    workspace.created_at AS workspace_created_at,
    workspace.updated_at AS workspace_updated_at,
    membership.id AS membership_id,
    membership.role AS membership_role,
    membership.state AS membership_state,
    membership.created_at AS membership_created_at,
    membership.updated_at AS membership_updated_at,
    account.state AS account_state,
    account.reason_code AS account_reason_code,
    account.created_at AS account_created_at,
    account.updated_at AS account_updated_at,
    plan.id AS plan_id,
    plan.plan_key AS plan_key,
    plan.name AS plan_name,
    plan.monthly_price_usd AS plan_monthly_price_usd,
    plan.seat_limit AS plan_seat_limit,
    plan.daily_quotas AS plan_daily_quotas,
    plan.active AS plan_active,
    plan.created_at AS plan_created_at,
    plan.updated_at AS plan_updated_at,
    territory.id AS territory_id,
    territory.workspace_id AS territory_workspace_id,
    territory.name AS territory_name,
    territory.state_code AS territory_state_code,
    territory.market AS territory_market,
    territory.asset_type AS territory_asset_type,
    territory.created_at AS territory_created_at,
    territory.updated_at AS territory_updated_at
FROM medawarcre.users actor
CROSS JOIN medawarcre.workspaces workspace
JOIN medawarcre.memberships membership
  ON membership.workspace_id = workspace.id
 AND membership.user_id = actor.id
 AND membership.state = 'active'
JOIN medawarcre.workspace_accounts account
  ON account.workspace_id = workspace.id
LEFT JOIN medawarcre.plans plan
  ON plan.id = workspace.plan_id
LEFT JOIN medawarcre.territories territory
  ON territory.workspace_id = workspace.id
WHERE actor.id = medawarcre.current_actor_user_id()
  AND workspace.id = medawarcre.current_workspace_id()
ORDER BY territory.name COLLATE "C" NULLS LAST, territory.id NULLS LAST
"""

_IDENTITY_FIELDS = (
    "user_id",
    "user_email",
    "user_name",
    "user_state",
    "user_created_at",
    "user_updated_at",
    "workspace_id",
    "workspace_public_id",
    "workspace_name",
    "workspace_slug",
    "workspace_state",
    "workspace_created_at",
    "workspace_updated_at",
    "membership_id",
    "membership_role",
    "membership_state",
    "membership_created_at",
    "membership_updated_at",
    "account_state",
    "account_reason_code",
    "account_created_at",
    "account_updated_at",
    "plan_id",
    "plan_key",
    "plan_name",
    "plan_monthly_price_usd",
    "plan_seat_limit",
    "plan_daily_quotas",
    "plan_active",
    "plan_created_at",
    "plan_updated_at",
)

_TERRITORY_FIELDS = (
    "territory_workspace_id",
    "territory_name",
    "territory_state_code",
    "territory_market",
    "territory_asset_type",
    "territory_created_at",
    "territory_updated_at",
)


class PlatformContextUnavailable(RuntimeError):
    """The exact hosted platform-context boundary cannot complete safely."""


@dataclass(frozen=True)
class PlatformActor:
    id: str
    email: str
    name: str
    state: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PlatformWorkspace:
    id: str
    public_id: str
    name: str
    slug: str | None
    state: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PlatformMembership:
    id: str
    role: str
    state: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PlatformAccount:
    state: str
    reason_code: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PlatformPlan:
    id: str
    key: str
    name: str
    monthly_price_usd: str | None
    seat_limit: int | None
    daily_quotas: dict[str, int]
    active: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PlatformTerritory:
    id: str
    name: str
    state: str | None
    market: str | None
    asset_type: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PlatformContextSnapshot:
    actor: PlatformActor
    workspace: PlatformWorkspace
    membership: PlatformMembership
    account: PlatformAccount
    plan: PlatformPlan | None
    territories: tuple[PlatformTerritory, ...]


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
        raise ValueError("invalid platform-context UUID") from error


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
        raise ValueError("invalid platform-context text")
    return value


def _enum(value: object, allowed: frozenset[str]) -> str:
    selected = _text(value, maximum=64)
    if selected not in allowed:
        raise ValueError("invalid platform-context state")
    return selected


def _utc_text(value: object) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("invalid platform-context timestamp")
    return value.astimezone(UTC).isoformat()


def _price_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("invalid platform-context price")
    try:
        selected = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError("invalid platform-context price") from error
    if not selected.is_finite() or selected < 0:
        raise ValueError("invalid platform-context price")
    rendered = format(selected, "f")
    if len(rendered) > 32:
        raise ValueError("invalid platform-context price")
    return rendered


def _quotas(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("invalid platform-context quotas")
    parsed: dict[str, int] = {}
    for bucket, limit in value.items():
        if (
            not is_canonical_quota_bucket(bucket)
            or type(limit) is not int
            or limit < 0
        ):
            raise ValueError("invalid platform-context quotas")
        parsed[bucket] = limit
    return dict(sorted(parsed.items()))


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise ValueError("invalid platform-context seat limit")
    return value


def _required_bool(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("invalid platform-context boolean")
    return value


def _plan(row: Mapping[str, object]) -> PlatformPlan | None:
    if row["plan_id"] is None:
        if any(
            row[name] is not None
            for name in (
                "plan_key",
                "plan_name",
                "plan_monthly_price_usd",
                "plan_seat_limit",
                "plan_daily_quotas",
                "plan_active",
                "plan_created_at",
                "plan_updated_at",
            )
        ):
            raise ValueError("invalid absent platform-context plan")
        return None
    return PlatformPlan(
        id=_uuid_text(row["plan_id"]),
        key=_text(row["plan_key"], maximum=128) or "",
        name=_text(row["plan_name"], maximum=512) or "",
        monthly_price_usd=_price_text(row["plan_monthly_price_usd"]),
        seat_limit=_optional_positive_int(row["plan_seat_limit"]),
        daily_quotas=_quotas(row["plan_daily_quotas"]),
        active=_required_bool(row["plan_active"]),
        created_at=_utc_text(row["plan_created_at"]),
        updated_at=_utc_text(row["plan_updated_at"]),
    )


def _snapshot(
    rows: list[Mapping[str, object]],
    admission: AdmissionOutcome,
) -> PlatformContextSnapshot:
    if not rows:
        raise ValueError("invalid platform-context cardinality")
    row = rows[0]
    for candidate in rows[1:]:
        if any(candidate[name] != row[name] for name in _IDENTITY_FIELDS):
            raise ValueError("incoherent platform-context identity")

    actor_id = _uuid_text(row["user_id"])
    workspace_id = _uuid_text(row["workspace_id"])
    workspace_public_id = _text(row["workspace_public_id"], maximum=256) or ""
    if (
        actor_id != admission.actor_user_id
        or workspace_public_id != admission.workspace_public_id
    ):
        raise ValueError("platform-context admission mismatch")
    email = _text(row["user_email"], maximum=320) or ""
    if "@" not in email or any(character.isspace() for character in email):
        raise ValueError("invalid platform-context email")

    territories: list[PlatformTerritory] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for territory_row in rows:
        territory_id_value = territory_row["territory_id"]
        if territory_id_value is None:
            if any(territory_row[name] is not None for name in _TERRITORY_FIELDS):
                raise ValueError("invalid absent platform-context territory")
            continue
        if _uuid_text(territory_row["territory_workspace_id"]) != workspace_id:
            raise ValueError("platform-context territory mismatch")
        territory_id = _uuid_text(territory_id_value)
        name = _text(territory_row["territory_name"], maximum=512) or ""
        if territory_id in seen_ids or name in seen_names:
            raise ValueError("duplicate platform-context territory")
        seen_ids.add(territory_id)
        seen_names.add(name)
        state = _text(
            territory_row["territory_state_code"],
            maximum=2,
            nullable=True,
        )
        if state is not None and (
            len(state) != 2
            or not state.isascii()
            or not state.isalpha()
            or not state.isupper()
        ):
            raise ValueError("invalid platform-context territory state")
        territories.append(
            PlatformTerritory(
                id=territory_id,
                name=name,
                state=state,
                market=_text(
                    territory_row["territory_market"],
                    maximum=512,
                    nullable=True,
                ),
                asset_type=_text(
                    territory_row["territory_asset_type"],
                    maximum=256,
                    nullable=True,
                ),
                created_at=_utc_text(territory_row["territory_created_at"]),
                updated_at=_utc_text(territory_row["territory_updated_at"]),
            )
        )
    if territories != sorted(territories, key=lambda item: (item.name, item.id)):
        raise ValueError("non-deterministic platform-context territory order")

    return PlatformContextSnapshot(
        actor=PlatformActor(
            id=actor_id,
            email=email,
            name=_text(row["user_name"], maximum=512) or "",
            state=_enum(row["user_state"], _USER_STATES),
            created_at=_utc_text(row["user_created_at"]),
            updated_at=_utc_text(row["user_updated_at"]),
        ),
        workspace=PlatformWorkspace(
            id=workspace_id,
            public_id=workspace_public_id,
            name=_text(row["workspace_name"], maximum=512) or "",
            slug=_text(row["workspace_slug"], maximum=256, nullable=True),
            state=_enum(row["workspace_state"], _WORKSPACE_STATES),
            created_at=_utc_text(row["workspace_created_at"]),
            updated_at=_utc_text(row["workspace_updated_at"]),
        ),
        membership=PlatformMembership(
            id=_uuid_text(row["membership_id"]),
            role=_enum(row["membership_role"], _MEMBERSHIP_ROLES),
            state=_enum(row["membership_state"], frozenset({"active"})),
            created_at=_utc_text(row["membership_created_at"]),
            updated_at=_utc_text(row["membership_updated_at"]),
        ),
        account=PlatformAccount(
            state=_enum(row["account_state"], _ACCOUNT_STATES),
            reason_code=_text(
                row["account_reason_code"],
                maximum=256,
                nullable=True,
            ),
            created_at=_utc_text(row["account_created_at"]),
            updated_at=_utc_text(row["account_updated_at"]),
        ),
        plan=_plan(row),
        territories=tuple(territories),
    )


class PostgresPlatformRepository:
    """Read the current admitted actor and workspace platform snapshot."""

    def __init__(
        self,
        database: PostgresDatabase,
        admission: AdmissionOutcome,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise TypeError("platform-context repository requires PostgreSQL")
        self._database = database
        self._admission = require_fresh_admission(admission)

    def _require_active_scope(self) -> TenantContext:
        repositories = current_hosted_request_repositories()
        context = current_context()
        if (
            repositories is None
            or repositories.admission is not self._admission
            or repositories.require("platform") is not self
            or not isinstance(context, TenantContext)
            or context.trusted
            or not context.active
        ):
            raise PlatformContextUnavailable(_UNAVAILABLE)
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
            raise PlatformContextUnavailable(_UNAVAILABLE)
        return context

    def _get_snapshot(self) -> PlatformContextSnapshot:
        self._require_active_scope()
        with self._database.admitted_connection(self._admission) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(_PLATFORM_CONTEXT_QUERY).fetchall()
        self._require_active_scope()
        return _snapshot(rows, self._admission)

    async def get_snapshot(self) -> PlatformContextSnapshot:
        """Return one all-or-nothing snapshot for the exact active request."""
        try:
            self._require_active_scope()
            result = await _finish_thread_before_cancellation(self._get_snapshot)
            self._require_active_scope()
            if not isinstance(result, PlatformContextSnapshot):
                raise ValueError("invalid platform-context result")
            return result
        except asyncio.CancelledError:
            raise
        except PlatformContextUnavailable:
            raise
        except Exception as error:
            raise PlatformContextUnavailable(_UNAVAILABLE) from error


__all__ = [
    "PlatformAccount",
    "PlatformActor",
    "PlatformContextSnapshot",
    "PlatformContextUnavailable",
    "PlatformMembership",
    "PlatformPlan",
    "PlatformTerritory",
    "PlatformWorkspace",
    "PostgresPlatformRepository",
]
