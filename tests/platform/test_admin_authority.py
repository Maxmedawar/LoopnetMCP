"""Live, separate authority tests for the internal control plane."""

from __future__ import annotations

import sqlite3

import pytest

from cre_mcp.platform.repository import PlatformRepository

from .admin_helpers import (
    ADMIN_SCOPE,
    VALID_REASON,
    api_client,
    config_for,
    provision_identity,
    provision_target,
)


def _provision_body(name: str) -> dict:
    return {
        "name": name,
        "owner_email": f"{name.casefold().replace(' ', '-')}@example.test",
        "owner_name": f"{name} Owner",
        **VALID_REASON,
    }


@pytest.mark.parametrize("membership_role", ["owner", "admin", "member", "viewer"])
async def test_tenant_roles_with_admin_scope_cannot_mutate_controls(
    tmp_path,
    membership_role,
):
    config = config_for(tmp_path)
    identity = await provision_identity(
        config,
        f"Ordinary {membership_role}",
        membership_role=membership_role,
        scopes=(ADMIN_SCOPE,),
    )

    async with api_client(config) as client:
        response = await client.post(
            "/v1/admin/workspaces",
            headers=identity.headers,
            json=_provision_body(f"Blocked {membership_role}"),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_support_is_read_only(tmp_path):
    config = config_for(tmp_path)
    support = await provision_identity(
        config,
        "Support Reader",
        internal_role="support",
    )
    target = await provision_target(config, "Support Target")

    async with api_client(config) as client:
        read = await client.get(
            f"/v1/admin/workspaces/{target.workspace_id}",
            headers=support.headers,
        )
        write = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/territories",
            headers=support.headers,
            json={"name": "Blocked", **VALID_REASON},
        )

    assert read.status_code == 200
    assert read.json()["workspace"]["public_id"] == target.workspace_id
    assert write.status_code == 403
    assert write.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize(
    ("internal_role", "active", "scopes"),
    [
        ("platform_admin", False, (ADMIN_SCOPE,)),
        ("platform_admin", True, ()),
        (None, True, (ADMIN_SCOPE,)),
    ],
)
async def test_missing_inactive_or_unscoped_internal_authority_fails_closed(
    tmp_path,
    internal_role,
    active,
    scopes,
):
    config = config_for(tmp_path)
    identity = await provision_identity(
        config,
        f"Denied {internal_role} {active} {len(scopes)}",
        internal_role=internal_role,
        internal_active=active,
        scopes=scopes,
    )

    async with api_client(config) as client:
        response = await client.post(
            "/v1/admin/workspaces",
            headers=identity.headers,
            json=_provision_body("Denied Provisioning"),
        )

    assert response.status_code == 403


async def test_only_active_platform_admin_with_scope_can_mutate(tmp_path):
    config = config_for(tmp_path)
    identity = await provision_identity(
        config,
        "Platform Administrator",
        internal_role="platform_admin",
    )

    async with api_client(config) as client:
        response = await client.post(
            "/v1/admin/workspaces",
            headers=identity.headers,
            json=_provision_body("Provisioned Tenant"),
        )

    assert response.status_code == 201
    assert response.json()["workspace"]["name"] == "Provisioned Tenant"
    assert response.json()["membership"]["role"] == "owner"
    assert response.json()["account"]["state"] == "active"


async def test_unknown_internal_role_fails_closed_for_reads_and_mutations(tmp_path):
    config = config_for(tmp_path)
    identity = await provision_identity(
        config,
        "Unknown Internal Role",
        internal_role="platform_admin",
    )
    target = await provision_target(config, "Unknown Role Target")
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(
            "UPDATE platform_internal_admins SET role='unknown' WHERE user_id=?",
            (identity.user_id,),
        )

    async with api_client(config) as client:
        read = await client.get(
            f"/v1/admin/workspaces/{target.workspace_id}",
            headers=identity.headers,
        )
        mutation = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/territories",
            headers=identity.headers,
            json={"name": "Must Not Exist", **VALID_REASON},
        )

    assert read.status_code == 403
    assert mutation.status_code == 403


async def test_membership_role_change_is_live_on_same_oauth_session(tmp_path):
    config = config_for(tmp_path)
    actor = await provision_identity(
        config,
        "Live Role Admin",
        internal_role="platform_admin",
    )
    target = await provision_target(config, "Live Role Target", role="owner")

    async with api_client(config) as client:
        before = await client.get("/v1/me", headers=target.headers)
        changed = await client.patch(
            f"/v1/admin/workspaces/{target.workspace_id}"
            f"/memberships/{target.membership_id}",
            headers=actor.headers,
            json={"role": "viewer", **VALID_REASON},
        )
        after = await client.get("/v1/me", headers=target.headers)

    assert before.status_code == 200
    assert before.json()["membership"]["role"] == "owner"
    assert changed.status_code == 200
    assert changed.json()["membership"]["role"] == "viewer"
    assert after.status_code == 200
    assert after.json()["session"]["session_id"] == before.json()["session"]["session_id"]
    assert after.json()["membership"]["role"] == "viewer"

    repository = PlatformRepository(config.cache_db_path)
    membership = await repository.get_membership(
        target.workspace_id,
        target.membership_id,
    )
    assert membership is not None and membership.role == "viewer"
