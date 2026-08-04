"""Single live authorization source for hosted OAuth requests."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastmcp.server.auth import AccessToken, TokenVerifier

from cre_mcp.access.context import TenantContext
from cre_mcp.access.profiles import Profile
from cre_mcp.platform.auth import (
    DEFAULT_AUDIENCE,
    DEFAULT_REFRESH_FAMILY_MAX_AGE,
    DEFAULT_RESOURCE,
    AuthenticatedSession,
    OAuthSessionStore,
)
from cre_mcp.platform.entitlements import AccountRecord, EffectiveAccess

ACCESS_ENABLED_ACCOUNT_STATES = frozenset({"active", "past_due", "grace_period"})
_PROFILE_RANK = {
    Profile.FULL_OPERATOR: 4,
    Profile.NATIONAL_SCOUT: 3,
    Profile.LOCAL_SCOUT: 2,
    Profile.JV_PARTNER: 1,
}


def _parse(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_daily_quotas(value: object) -> dict[str, int] | None:
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError):
        return None
    if not isinstance(decoded, dict):
        return None
    quotas: dict[str, int] = {}
    for bucket, limit in decoded.items():
        if (
            not isinstance(bucket, str)
            or not bucket.strip()
            or type(limit) is not int
            or limit < 0
        ):
            return None
        quotas[bucket.strip()] = limit
    return quotas


@dataclass(frozen=True)
class WorkspaceAuthority:
    id: int
    public_id: str
    name: str
    plan_id: int | None


@dataclass(frozen=True)
class MembershipAuthority:
    id: int
    user_id: int
    role: str


@dataclass(frozen=True)
class InternalAdminAuthority:
    user_id: int
    role: str


@dataclass(frozen=True)
class AuthorityOutcome:
    session: AuthenticatedSession
    workspace: WorkspaceAuthority | None
    membership: MembershipAuthority | None
    account: AccountRecord | None
    effective_access: EffectiveAccess | None
    context: TenantContext | None
    reason: str | None
    internal_admin: InternalAdminAuthority | None = None
    jv_grant_present: bool = False

    @property
    def access_allowed(self) -> bool:
        return self.context is not None


class AuthorityResolver:
    """Validate a credential and derive current server-owned authority."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        audience: str = DEFAULT_AUDIENCE,
        resource: str = DEFAULT_RESOURCE,
        refresh_family_max_age: timedelta = DEFAULT_REFRESH_FAMILY_MAX_AGE,
    ) -> None:
        self.db_path = Path(db_path).expanduser()
        self.audience = audience
        self.resource = resource
        self.sessions = OAuthSessionStore(
            self.db_path,
            refresh_family_max_age=refresh_family_max_age,
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def resolve(self, bearer_token: str) -> AuthorityOutcome | None:
        session = self.sessions.validate_access(
            bearer_token,
            audience=self.audience,
            resource=self.resource,
        )
        if session is None:
            return None

        now = datetime.now(UTC)
        with self._connect() as connection:
            # A read transaction gives one coherent view of membership,
            # account, grant, and territory state for this request.
            connection.execute("BEGIN")
            identity = connection.execute(
                """
                SELECT
                    workspace.id AS workspace_row_id,
                    workspace.public_id,
                    workspace.name,
                    workspace.plan_id,
                    membership.id AS membership_id,
                    membership.user_id,
                    membership.role
                FROM platform_workspaces AS workspace
                JOIN platform_memberships AS membership
                  ON membership.workspace_id=workspace.id
                 AND membership.user_id=?
                WHERE workspace.public_id=?
                """,
                (session.user_id, session.workspace_id),
            ).fetchone()
            if identity is None:
                return AuthorityOutcome(
                    session, None, None, None, None, None, "membership_missing"
                )

            workspace = WorkspaceAuthority(
                id=int(identity["workspace_row_id"]),
                public_id=str(identity["public_id"]),
                name=str(identity["name"]),
                plan_id=(
                    int(identity["plan_id"])
                    if identity["plan_id"] is not None
                    else None
                ),
            )
            membership = MembershipAuthority(
                id=int(identity["membership_id"]),
                user_id=int(identity["user_id"]),
                role=str(identity["role"]),
            )
            internal_admin_row = connection.execute(
                """
                SELECT user_id,role
                FROM platform_internal_admins
                WHERE user_id=?
                  AND active=1
                  AND role IN ('platform_admin','support')
                """,
                (session.user_id,),
            ).fetchone()
            internal_admin = (
                InternalAdminAuthority(
                    user_id=int(internal_admin_row["user_id"]),
                    role=str(internal_admin_row["role"]),
                )
                if internal_admin_row is not None
                else None
            )
            jv_grant_present = (
                connection.execute(
                    """
                    SELECT 1
                    FROM platform_memberships AS membership
                    JOIN platform_access_grants AS grant
                      ON grant.workspace_id=membership.workspace_id
                    WHERE membership.user_id=?
                      AND grant.profile='jv_partner'
                      AND grant.status IN ('active','overridden','expiring')
                      AND grant.starts_at<=?
                      AND (grant.ends_at IS NULL OR grant.ends_at>?)
                      AND (
                          grant.scope='workspace'
                          OR grant.subject_user_id=membership.user_id
                      )
                    LIMIT 1
                    """,
                    (
                        session.user_id,
                        now.astimezone(UTC).isoformat(),
                        now.astimezone(UTC).isoformat(),
                    ),
                ).fetchone()
                is not None
            )
            account_row = connection.execute(
                "SELECT * FROM platform_accounts WHERE workspace_id=?",
                (workspace.id,),
            ).fetchone()
            account = (
                AccountRecord(
                    workspace_id=workspace.id,
                    state=str(account_row["state"]),
                    reason=account_row["reason"],
                    updated_at=_parse(str(account_row["updated_at"])),
                )
                if account_row is not None
                else None
            )
            grant_rows = connection.execute(
                """
                SELECT * FROM platform_access_grants
                WHERE workspace_id=?
                  AND status IN ('active','overridden','expiring')
                  AND (
                      scope='workspace'
                      OR (scope='subject' AND subject_user_id=?)
                  )
                """,
                (workspace.id, session.user_id),
            ).fetchall()
            valid_grants = [
                row
                for row in grant_rows
                if _parse(str(row["starts_at"])) <= now
                and (
                    row["ends_at"] is None
                    or _parse(str(row["ends_at"])) > now
                )
            ]

            effective_access = None
            quota_limits = None
            if valid_grants:
                selected = max(
                    valid_grants,
                    key=lambda row: (
                        _PROFILE_RANK[Profile(str(row["profile"]))],
                        _parse(str(row["updated_at"])),
                    ),
                )
                expiries = [
                    _parse(str(row["ends_at"]))
                    for row in valid_grants
                    if row["ends_at"] is not None
                ]
                effective_access = EffectiveAccess(
                    workspace_id=workspace.id,
                    profile=Profile(str(selected["profile"])),
                    plan_key=str(selected["plan_key"]),
                    grant_ids=tuple(int(row["id"]) for row in valid_grants),
                    sources=tuple(
                        dict.fromkeys(str(row["source"]) for row in valid_grants)
                    ),
                    expires_at=min(expiries) if expiries else None,
                )
                plan_row = connection.execute(
                    "SELECT daily_quotas FROM platform_plans WHERE key=?",
                    (effective_access.plan_key,),
                ).fetchone()
                if plan_row is not None:
                    quota_limits = _parse_daily_quotas(
                        plan_row["daily_quotas"]
                    )

            territory_rows = connection.execute(
                """
                SELECT name,state,market FROM platform_territories
                WHERE workspace_id=? ORDER BY id
                """,
                (workspace.id,),
            ).fetchall()

        if account is None:
            reason = "account_missing"
        elif account.state not in ACCESS_ENABLED_ACCOUNT_STATES:
            reason = f"account_{account.state}"
        elif effective_access is None:
            reason = "entitlement_missing_or_expired"
        elif quota_limits is None:
            reason = "plan_missing_or_invalid"
        else:
            reason = None

        context = None
        if reason is None and effective_access is not None:
            territory_values: list[str] = []
            for row in territory_rows:
                value = row["state"] or row["market"] or row["name"]
                normalized = str(value).strip()
                if normalized and normalized not in territory_values:
                    territory_values.append(normalized)
            context = TenantContext(
                workspace_id=workspace.public_id,
                profile=effective_access.profile,
                plan=effective_access.plan_key,
                quota_limits=quota_limits,
                territories=tuple(territory_values),
                active=True,
                trusted=False,
                display_name=workspace.name,
                actor_id=str(membership.user_id) if membership is not None else "",
                session_id=session.session_id,
            )

        return AuthorityOutcome(
            session=session,
            workspace=workspace,
            membership=membership,
            account=account,
            effective_access=effective_access,
            context=context,
            reason=reason,
            internal_admin=internal_admin,
            jv_grant_present=jv_grant_present,
        )


class AuthoritativeOAuthVerifier(TokenVerifier):
    """FastMCP bearer verifier that rejects before MCP session allocation."""

    def __init__(
        self,
        resolver: AuthorityResolver,
        *,
        required_scopes: tuple[str, ...] = ("mcp:tools",),
    ) -> None:
        # A protected-resource discovery endpoint is intentionally not
        # advertised until a real portal authorization server exists.
        super().__init__(base_url=None, required_scopes=list(required_scopes))
        self.resolver = resolver

    async def verify_token(self, token: str) -> AccessToken | None:
        outcome = self.resolver.resolve(token)
        if outcome is None:
            return None
        session = outcome.session
        scopes = list(session.scopes)
        claims: dict[str, object] = {"session_id": session.session_id}
        if outcome.access_allowed and outcome.context is not None:
            claims["tenant_context"] = outcome.context.model_dump(mode="json")
        else:
            # Keep valid credential identity distinct from authorization. By
            # withholding the mandatory MCP scope, FastMCP emits a standards-
            # consistent 403 before allocating an MCP transport session.
            scopes = [
                scope for scope in scopes if scope not in self.required_scopes
            ]
            claims["access_disabled_reason"] = outcome.reason
        return AccessToken(
            token=token,
            client_id=session.client_id,
            scopes=scopes,
            expires_at=int(session.access_expires_at.timestamp()),
            resource=session.resource,
            subject=str(session.user_id),
            claims=claims,
        )


__all__ = [
    "ACCESS_ENABLED_ACCOUNT_STATES",
    "AuthoritativeOAuthVerifier",
    "AuthorityOutcome",
    "AuthorityResolver",
    "InternalAdminAuthority",
    "MembershipAuthority",
    "WorkspaceAuthority",
]
