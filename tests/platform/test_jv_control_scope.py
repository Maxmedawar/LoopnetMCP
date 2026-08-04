"""JV reads remain bound to live token authority and never reach admin controls."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from cre_mcp.access.profiles import Profile
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository

from .admin_helpers import (
    ADMIN_SCOPE,
    VALID_REASON,
    api_client,
    audit_rows,
    config_for,
    provision_identity,
    provision_target,
)


async def test_jv_workspace_and_members_are_live_and_workspace_scoped(tmp_path):
    config = config_for(tmp_path)
    jv = await provision_identity(
        config,
        "JV Partner",
        scopes=(ADMIN_SCOPE,),
        profile=Profile.JV_PARTNER,
        territory_state="TX",
    )
    repository = PlatformRepository(config.cache_db_path)
    colleague = await repository.create_user("colleague@jv.test", "JV Colleague")
    assert colleague is not None
    colleague_membership = await repository.add_membership(
        jv.workspace_id,
        colleague.id,
        role="member",
    )
    assert colleague_membership is not None

    other = await provision_target(config, "Other Tenant")
    other_territory = await repository.claim_territory(
        other.workspace_id,
        "California territory",
        state="CA",
    )
    assert other_territory is not None

    async with api_client(config) as client:
        workspace = await client.get("/v1/jv/workspace", headers=jv.headers)
        members = await client.get("/v1/jv/members", headers=jv.headers)
        admin = await client.get(
            f"/v1/admin/workspaces/{other.workspace_id}",
            headers=jv.headers,
        )

    assert workspace.status_code == 200
    assert workspace.json()["workspace"]["public_id"] == jv.workspace_id
    assert {item["state"] for item in workspace.json()["territories"]} == {"TX"}
    assert other_territory.id not in {
        item["id"] for item in workspace.json()["territories"]
    }
    assert members.status_code == 200
    assert {item["user"]["id"] for item in members.json()["members"]} == {
        jv.user_id,
        colleague.id,
    }
    assert other.user_id not in {
        item["user"]["id"] for item in members.json()["members"]
    }
    assert admin.status_code == 403


@pytest.mark.parametrize("selector", ["workspace_id", "role", "profile", "territory"])
async def test_jv_client_selectors_are_rejected_without_widening_authority(
    tmp_path,
    selector,
):
    config = config_for(tmp_path)
    jv = await provision_identity(
        config,
        f"JV Selector {selector}",
        profile=Profile.JV_PARTNER,
        territory_state="TX",
    )
    other = await provision_target(config, f"Other {selector}")

    async with api_client(config) as client:
        response = await client.get(
            "/v1/jv/workspace",
            headers=jv.headers,
            params={selector: other.workspace_id},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_scope_selector"


async def test_non_jv_profile_cannot_use_jv_surface(tmp_path):
    config = config_for(tmp_path)
    operator = await provision_identity(
        config,
        "Full Operator",
        profile=Profile.FULL_OPERATOR,
    )

    async with api_client(config) as client:
        workspace = await client.get("/v1/jv/workspace", headers=operator.headers)
        members = await client.get("/v1/jv/members", headers=operator.headers)

    assert workspace.status_code == 403
    assert members.status_code == 403


@pytest.mark.parametrize(
    ("partner_grant_state", "expected_status"),
    [
        ("live", 403),
        ("revoked", 200),
        ("expired", 200),
        ("outranked", 403),
    ],
)
async def test_only_current_jv_authority_blocks_dual_seeded_admin_identity(
    tmp_path,
    partner_grant_state,
    expected_status,
):
    config = config_for(tmp_path)
    jv = await provision_identity(
        config,
        f"Dual Seeded JV {partner_grant_state}",
        internal_role="platform_admin",
        scopes=(ADMIN_SCOPE,),
        profile=Profile.JV_PARTNER,
    )
    target = await provision_target(
        config,
        f"Dual Seeded Target {partner_grant_state}",
    )
    entitlements = EntitlementStore(config.cache_db_path)
    entitlements.set_account_state(
        target.workspace_id,
        "active",
        reason="Regression test baseline",
    )

    if partner_grant_state == "revoked":
        with sqlite3.connect(config.cache_db_path) as connection:
            connection.execute(
                """
                UPDATE platform_access_grants
                SET status='revoked'
                WHERE workspace_id=? AND profile='jv_partner'
                """,
                (jv.workspace_row_id,),
            )
    elif partner_grant_state == "expired":
        with sqlite3.connect(config.cache_db_path) as connection:
            connection.execute(
                """
                UPDATE platform_access_grants
                SET ends_at=?
                WHERE workspace_id=? AND profile='jv_partner'
                """,
                (
                    (datetime.now(UTC) - timedelta(days=1)).isoformat(),
                    jv.workspace_row_id,
                ),
            )
    elif partner_grant_state == "outranked":
        repository = PlatformRepository(config.cache_db_path)
        plan = await repository.create_plan("pro", "Pro", daily_quotas={})
        assert plan is not None
        entitlements.grant_access(
            workspace=jv.workspace_id,
            source="manual",
            external_ref=f"operator-{jv.workspace_id}",
            profile=Profile.FULL_OPERATOR,
            plan_key="pro",
            subject_user_id=jv.user_id,
            scope="subject",
        )

    async with api_client(config) as client:
        read = await client.get(
            f"/v1/admin/workspaces/{target.workspace_id}",
            headers=jv.headers,
        )
        mutation = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/account-state",
            headers=jv.headers,
            json={
                "state": "suspended",
                **VALID_REASON,
            },
        )

    assert read.status_code == expected_status
    assert mutation.status_code == expected_status
    account = entitlements.get_account(target.workspace_id)
    assert account is not None
    if expected_status == 403:
        assert account.state == "active"
        assert audit_rows(config.cache_db_path) == []
    else:
        assert account.state == "suspended"
        assert audit_rows(config.cache_db_path)
