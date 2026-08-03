"""Account-layer persistence tests: users, plans, workspaces, memberships,
territories, and connected clients."""

import pytest

from cre_mcp.platform.repository import PlatformRepository


async def test_create_get_and_list_users_persist_across_instances(tmp_path):
    path = tmp_path / "platform.db"
    first = PlatformRepository(path)
    user = await first.create_user("max@efreedom.com", "Max Medawar")
    assert user is not None

    second = PlatformRepository(path)
    fetched = await second.get_user(user.id)
    listed = await second.list_users()

    assert fetched is not None
    assert fetched.email == "max@efreedom.com"
    assert fetched.name == "Max Medawar"
    assert [item.id for item in listed] == [user.id]


async def test_update_user_changes_fields_and_leaves_none_untouched(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    user = await repository.create_user("max@efreedom.com", "Max Medawar")
    assert user is not None

    updated = await repository.update_user(user.id, name="M. Medawar")

    assert updated is not None
    assert updated.name == "M. Medawar"
    assert updated.email == "max@efreedom.com"
    assert updated.updated_at >= user.updated_at
    assert await repository.update_user(999, name="Nobody") is None


async def test_blank_and_duplicate_user_emails_are_rejected(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    with pytest.raises(ValueError, match="email"):
        await repository.create_user("   ", "Blank Email")

    assert await repository.create_user("max@efreedom.com", "Max") is not None
    assert await repository.create_user("max@efreedom.com", "Again") is None


async def test_create_update_and_list_plans(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    plan = await repository.create_plan(
        "pro",
        "Professional",
        monthly_price_usd=99.0,
        seat_limit=5,
        daily_quotas={"search": 10},
    )
    assert plan is not None
    assert plan.key == "pro"
    assert plan.daily_quotas == {"search": 10}

    updated = await repository.update_plan(
        plan.id,
        monthly_price_usd=149.0,
        daily_quotas={"search": 25},
    )

    assert updated is not None
    assert updated.monthly_price_usd == 149.0
    assert updated.seat_limit == 5
    assert updated.daily_quotas == {"search": 25}
    assert [item.key for item in await repository.list_plans()] == ["pro"]
    assert await repository.get_plan(plan.id) is not None
    assert await repository.create_plan("pro", "Duplicate key") is None


@pytest.mark.parametrize(
    "daily_quotas",
    [
        {"search": -1},
        {"search": True},
        {"search": 1.5},
        {"": 1},
        [],
    ],
)
async def test_plan_daily_quota_validation(tmp_path, daily_quotas):
    repository = PlatformRepository(tmp_path / "platform.db")

    with pytest.raises(ValueError, match="quota"):
        await repository.create_plan(
            "invalid",
            "Invalid",
            daily_quotas=daily_quotas,
        )


async def test_workspace_creation_plan_assignment_and_rename(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    starter = await repository.create_plan("starter", "Starter")
    pro = await repository.create_plan("pro", "Professional")
    assert starter is not None and pro is not None

    workspace = await repository.create_workspace(
        "Medawar CRE", slug="medawar-cre", plan_id=starter.id
    )
    assert workspace is not None
    assert workspace.plan_id == starter.id

    upgraded = await repository.update_workspace(
        workspace.id, name="Medawar CRE HQ", plan_id=pro.id
    )

    assert upgraded is not None
    assert upgraded.name == "Medawar CRE HQ"
    assert upgraded.slug == "medawar-cre"
    assert upgraded.plan_id == pro.id
    assert [item.id for item in await repository.list_workspaces()] == [workspace.id]
    assert await repository.get_workspace(workspace.id) is not None


async def test_workspace_requires_known_plan_and_nonblank_name(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    with pytest.raises(ValueError, match="name"):
        await repository.create_workspace("   ")

    assert await repository.create_workspace("Orphaned", plan_id=999) is None


async def test_membership_lifecycle(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    user = await repository.create_user("max@efreedom.com", "Max")
    workspace = await repository.create_workspace("Medawar CRE")
    assert user is not None and workspace is not None

    membership = await repository.add_membership(workspace.id, user.id, role="owner")

    assert membership is not None
    assert membership.role == "owner"
    assert await repository.add_membership(workspace.id, user.id) is None

    promoted = await repository.update_membership_role(workspace.id, membership.id, "admin")

    assert promoted is not None
    assert promoted.role == "admin"
    roster = await repository.list_memberships(workspace.id)
    assert [item.user_id for item in roster] == [user.id]
    assert await repository.get_membership(workspace.id, membership.id) is not None


async def test_membership_rejects_bad_role_and_unknown_parents(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    user = await repository.create_user("max@efreedom.com", "Max")
    workspace = await repository.create_workspace("Medawar CRE")
    assert user is not None and workspace is not None

    with pytest.raises(ValueError, match="role must be one of"):
        await repository.add_membership(workspace.id, user.id, role="emperor")
    assert await repository.add_membership(999, user.id) is None
    assert await repository.add_membership(workspace.id, 999) is None


async def test_territory_claim_update_and_list(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace = await repository.create_workspace("Medawar CRE")
    assert workspace is not None

    territory = await repository.claim_territory(
        workspace.id,
        "Austin retail",
        state="TX",
        market="Austin",
        asset_type="retail",
    )

    assert territory is not None
    assert territory.state == "TX"

    updated = await repository.update_territory(workspace.id, territory.id, asset_type="mixed-use")

    assert updated is not None
    assert updated.asset_type == "mixed-use"
    assert updated.market == "Austin"
    listed = await repository.list_territories(workspace.id)
    assert [item.name for item in listed] == ["Austin retail"]
    assert await repository.get_territory(workspace.id, territory.id) is not None
    assert await repository.claim_territory(999, "Nowhere") is None


async def test_connected_client_scopes_round_trip_and_revocation(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace = await repository.create_workspace("Medawar CRE")
    assert workspace is not None

    client = await repository.connect_client(
        workspace.id,
        "Claude Desktop",
        "mcp",
        scopes=["deals:read", "deals:write"],
    )

    assert client is not None
    assert client.status == "active"
    assert client.scopes == ["deals:read", "deals:write"]

    revoked = await repository.update_client_status(workspace.id, client.id, "revoked")

    assert revoked is not None
    assert revoked.status == "revoked"
    listed = await repository.list_connected_clients(workspace.id)
    assert [item.name for item in listed] == ["Claude Desktop"]
    assert await repository.get_connected_client(workspace.id, client.id) is not None
    with pytest.raises(ValueError, match="status must be one of"):
        await repository.update_client_status(workspace.id, client.id, "paused")
    assert await repository.connect_client(999, "Orphan", "api") is None
