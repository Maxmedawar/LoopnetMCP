"""Control-plane resource contracts and transactional failure behavior."""

from __future__ import annotations

import sqlite3

import pytest

from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository

from .admin_helpers import (
    VALID_REASON,
    api_client,
    audit_rows,
    config_for,
    provision_identity,
    provision_target,
    table_count,
)


async def _admin(config, name: str = "Controls Admin"):
    return await provision_identity(
        config,
        name,
        internal_role="platform_admin",
    )


@pytest.mark.parametrize(
    "reason_fields",
    [
        {},
        {"reason_code": "support_resolution"},
        {"reason_code": "support_resolution", "reason": "   "},
        {"reason_code": "invented_code", "reason": "Looks plausible but is invalid"},
    ],
)
async def test_missing_blank_or_invalid_reason_is_422_and_writes_nothing(
    tmp_path,
    reason_fields,
):
    config = config_for(tmp_path)
    actor = await _admin(config, f"Reason Admin {len(str(reason_fields))}")
    target = await provision_target(config, "Reason Target")
    before_audits = len(audit_rows(config.cache_db_path))

    async with api_client(config) as client:
        response = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/territories",
            headers=actor.headers,
            json={"name": "Should Not Exist", **reason_fields},
        )

    assert response.status_code == 422
    assert table_count(config.cache_db_path, "platform_territories") == 0
    assert len(audit_rows(config.cache_db_path)) == before_audits


async def test_admin_controls_cover_membership_grant_territory_and_account_state(
    tmp_path,
):
    config = config_for(tmp_path)
    actor = await _admin(config)
    target = await provision_target(config, "Managed Workspace")

    async with api_client(config) as client:
        membership = await client.patch(
            f"/v1/admin/workspaces/{target.workspace_id}"
            f"/memberships/{target.membership_id}",
            headers=actor.headers,
            json={"role": "admin", **VALID_REASON},
        )
        grant = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/grants",
            headers=actor.headers,
            json={
                "source": "manual",
                "external_ref": "manual-managed-workspace",
                "profile": "full_operator",
                "plan_key": "pro",
                **VALID_REASON,
            },
        )
        territory = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/territories",
            headers=actor.headers,
            json={
                "name": "Dallas retail",
                "state": "TX",
                "market": "Dallas",
                "asset_type": "retail",
                **VALID_REASON,
            },
        )
        account = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/account-state",
            headers=actor.headers,
            json={"state": "suspended", **VALID_REASON},
        )
        workspace = await client.get(
            f"/v1/admin/workspaces/{target.workspace_id}",
            headers=actor.headers,
        )

        grant_id = grant.json()["grant"]["id"]
        territory_id = territory.json()["territory"]["id"]
        revoked = await client.request(
            "DELETE",
            f"/v1/admin/workspaces/{target.workspace_id}/grants/{grant_id}",
            headers=actor.headers,
            json=VALID_REASON,
        )
        deleted = await client.request(
            "DELETE",
            f"/v1/admin/workspaces/{target.workspace_id}"
            f"/territories/{territory_id}",
            headers=actor.headers,
            json=VALID_REASON,
        )

    assert membership.status_code == 200
    assert membership.json()["membership"]["role"] == "admin"
    assert grant.status_code == 201
    assert grant.json()["grant"]["status"] == "active"
    assert territory.status_code == 201
    assert territory.json()["territory"]["state"] == "TX"
    assert account.status_code == 200
    assert account.json()["account"]["state"] == "suspended"
    assert workspace.status_code == 200
    assert workspace.json()["workspace"]["public_id"] == target.workspace_id
    assert workspace.json()["memberships"][0]["user"]["id"] == target.user_id
    assert workspace.json()["grants"][0]["external_ref"] == "manual-managed-workspace"
    assert workspace.json()["territories"][0]["name"] == "Dallas retail"
    assert revoked.status_code == 200
    assert revoked.json()["grant"]["status"] == "revoked"
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert len(audit_rows(config.cache_db_path)) == 6


async def test_path_workspace_is_authoritative_for_membership_mutation(tmp_path):
    config = config_for(tmp_path)
    actor = await _admin(config)
    first = await provision_target(config, "First Workspace")
    second = await provision_target(config, "Second Workspace")

    async with api_client(config) as client:
        response = await client.patch(
            f"/v1/admin/workspaces/{second.workspace_id}"
            f"/memberships/{first.membership_id}",
            headers=actor.headers,
            json={"role": "viewer", **VALID_REASON},
        )

    assert response.status_code == 404
    repository = PlatformRepository(config.cache_db_path)
    unchanged = await repository.get_membership(
        first.workspace_id,
        first.membership_id,
    )
    assert unchanged is not None and unchanged.role == "owner"
    assert audit_rows(config.cache_db_path) == []


async def test_failed_mutation_writes_no_audit(tmp_path):
    config = config_for(tmp_path)
    actor = await _admin(config)
    target = await provision_target(config, "Conflict Target")

    async with api_client(config) as client:
        first = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/territories",
            headers=actor.headers,
            json={"name": "Unique territory", **VALID_REASON},
        )
        before = len(audit_rows(config.cache_db_path))
        duplicate = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/territories",
            headers=actor.headers,
            json={"name": "Unique territory", **VALID_REASON},
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "error": {
            "code": "conflict",
            "message": "Territory already exists in this workspace",
        }
    }
    assert len(audit_rows(config.cache_db_path)) == before
    assert table_count(config.cache_db_path, "platform_territories") == 1


async def test_trusted_provisioning_is_atomic_on_owner_conflict(tmp_path):
    config = config_for(tmp_path)
    actor = await _admin(config)
    existing = await provision_target(config, "Existing Owner")
    repository = PlatformRepository(config.cache_db_path)
    user = await repository.get_user(existing.user_id)
    assert user is not None
    workspaces_before = table_count(config.cache_db_path, "platform_workspaces")
    users_before = table_count(config.cache_db_path, "platform_users")
    audits_before = len(audit_rows(config.cache_db_path))

    async with api_client(config) as client:
        response = await client.post(
            "/v1/admin/workspaces",
            headers=actor.headers,
            json={
                "name": "Must Roll Back",
                "slug": "must-roll-back",
                "owner_email": user.email,
                "owner_name": "Duplicate Owner",
                **VALID_REASON,
            },
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "conflict",
            "message": "Workspace slug or owner email already exists",
        }
    }
    assert table_count(config.cache_db_path, "platform_workspaces") == workspaces_before
    assert table_count(config.cache_db_path, "platform_users") == users_before
    assert len(audit_rows(config.cache_db_path)) == audits_before
    with sqlite3.connect(config.cache_db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_workspaces WHERE slug='must-roll-back'"
        ).fetchone()[0] == 0


async def test_provisioning_rejects_missing_plan_before_any_insert(tmp_path):
    config = config_for(tmp_path)
    actor = await _admin(config)
    workspaces_before = table_count(config.cache_db_path, "platform_workspaces")
    users_before = table_count(config.cache_db_path, "platform_users")

    async with api_client(config) as client:
        response = await client.post(
            "/v1/admin/workspaces",
            headers=actor.headers,
            json={
                "name": "Missing Plan Tenant",
                "slug": "missing-plan-tenant",
                "plan_id": 999_999,
                "owner_email": "owner@missing-plan.test",
                "owner_name": "Missing Plan Owner",
                **VALID_REASON,
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "plan_id does not reference an existing plan",
        }
    }
    assert table_count(config.cache_db_path, "platform_workspaces") == workspaces_before
    assert table_count(config.cache_db_path, "platform_users") == users_before
    assert audit_rows(config.cache_db_path) == []


async def test_successful_provisioning_creates_one_complete_tenant_and_audit(tmp_path):
    config = config_for(tmp_path)
    actor = await _admin(config)

    async with api_client(config) as client:
        response = await client.post(
            "/v1/admin/workspaces",
            headers=actor.headers,
            json={
                "name": "Atomic Tenant",
                "slug": "atomic-tenant",
                "owner_email": "owner@atomic.test",
                "owner_name": "Atomic Owner",
                "account_state": "active",
                "reason_code": "initial_provisioning",
                "reason": "Signed customer order received.",
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["workspace"]["slug"] == "atomic-tenant"
    assert payload["owner"]["email"] == "owner@atomic.test"
    assert payload["membership"]["role"] == "owner"
    assert payload["account"]["state"] == "active"
    assert len(audit_rows(config.cache_db_path)) == 1

    entitlements = EntitlementStore(config.cache_db_path)
    account = entitlements.get_account(payload["workspace"]["public_id"])
    assert account is not None and account.state == "active"
