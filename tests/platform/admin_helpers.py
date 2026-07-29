"""Out-of-band setup helpers for internal-admin and JV API tests."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import httpx

from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.platform.api import starlette_app
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository

ADMIN_SCOPE = "admin:controls"
REDIRECT = "https://internal.medawarcre.test/oauth/callback"
VALID_REASON = {
    "reason_code": "support_resolution",
    "reason": "Verified by the internal operations runbook.",
}


@dataclass(frozen=True)
class ApiIdentity:
    workspace_id: str
    workspace_row_id: int
    user_id: int
    membership_id: int
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}"}


def config_for(tmp_path) -> CreConfig:
    return CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")


def api_client(config: CreConfig) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=starlette_app(config)),
        base_url="http://platform.test",
    )


def _seed_internal_admin(
    path,
    *,
    user_id: int,
    role: str,
    active: bool,
) -> None:
    """Seed authority out of band, as production bootstrap is intentionally absent.

    The test-owned CREATE keeps pre-implementation tests collectable and lets
    route behavior fail red rather than failing during fixture setup. Production
    migrations create the same table before this INSERT in the implemented phase.
    """
    now = "2026-07-28T12:00:00+00:00"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_internal_admins (
                user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE,
                CHECK(role IN ('platform_admin','support')),
                CHECK(active IN (0,1))
            )
            """
        )
        connection.execute(
            """
            INSERT INTO platform_internal_admins
                (user_id,role,active,created_at,updated_at)
            VALUES (?,?,?,?,?)
            """,
            (user_id, role, int(active), now, now),
        )


async def provision_identity(
    config: CreConfig,
    name: str,
    *,
    membership_role: str = "owner",
    internal_role: str | None = None,
    internal_active: bool = True,
    scopes: tuple[str, ...] = (ADMIN_SCOPE,),
    profile: Profile | None = None,
    territory_state: str | None = None,
) -> ApiIdentity:
    repository = PlatformRepository(config.cache_db_path)
    entitlements = EntitlementStore(config.cache_db_path)
    auth = OAuthSessionStore(config.cache_db_path)

    workspace = await repository.create_workspace(name)
    user = await repository.create_user(
        f"{name.casefold().replace(' ', '-')}@example.test",
        name,
    )
    assert workspace is not None and user is not None
    membership = await repository.add_membership(
        workspace.public_id,
        user.id,
        role=membership_role,
    )
    assert membership is not None

    if territory_state is not None:
        territory = await repository.claim_territory(
            workspace.public_id,
            f"{territory_state} territory",
            state=territory_state,
        )
        assert territory is not None

    if profile is not None:
        plan_key = "partner" if profile is Profile.JV_PARTNER else "pro"
        plans = await repository.list_plans()
        if not any(plan.key == plan_key for plan in plans):
            plan = await repository.create_plan(
                plan_key,
                plan_key.title(),
                daily_quotas={},
            )
            assert plan is not None
        entitlements.grant_access(
            workspace=workspace.public_id,
            source="jv" if profile is Profile.JV_PARTNER else "manual",
            external_ref=f"profile-{workspace.public_id}",
            profile=profile,
            plan_key=plan_key,
        )

    if internal_role is not None:
        _seed_internal_admin(
            config.cache_db_path,
            user_id=user.id,
            role=internal_role,
            active=internal_active,
        )

    client = auth.register_client(f"{name} client", (REDIRECT,), scopes)
    tokens = auth.issue_session(
        workspace.public_id,
        user.id,
        client.client_id,
        scopes=scopes,
    )
    return ApiIdentity(
        workspace_id=workspace.public_id,
        workspace_row_id=workspace.id,
        user_id=user.id,
        membership_id=membership.id,
        token=tokens.access_token,
    )


async def provision_target(
    config: CreConfig,
    name: str,
    *,
    role: str = "owner",
) -> ApiIdentity:
    return await provision_identity(
        config,
        name,
        membership_role=role,
        scopes=(),
    )


def table_count(path, table: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def audit_rows(path) -> list[sqlite3.Row]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(
                "SELECT * FROM platform_admin_audit ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
