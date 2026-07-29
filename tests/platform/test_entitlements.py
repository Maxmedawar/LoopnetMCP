"""Commercial account, subscription, and entitlement synchronization tests."""

from datetime import UTC, datetime, timedelta

import pytest

from cre_mcp.access.profiles import Profile
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository


async def _workspace(path):
    repository = PlatformRepository(path)
    workspace = await repository.create_workspace("Medawar CRE")
    assert workspace is not None
    user = await repository.create_user(
        f"provider-{workspace.id}@example.test",
        "Provider Subject",
    )
    assert user is not None
    membership = await repository.add_membership(
        workspace.public_id,
        user.id,
        role="owner",
    )
    assert membership is not None
    return workspace


def test_stripe_activation_is_idempotent_and_grants_access(tmp_path):
    path = tmp_path / "platform.db"
    workspace = __import__("asyncio").run(_workspace(path))
    store = EntitlementStore(path)

    first = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_001",
        event_type="customer.subscription.created",
        workspace=workspace.public_id,
        external_subscription_id="sub_001",
        external_customer_id="cus_001",
        subscription_status="active",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
        payload={"livemode": False},
    )
    replay = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_001",
        event_type="customer.subscription.created",
        workspace=workspace.public_id,
        external_subscription_id="sub_001",
        subscription_status="canceled",
        plan_key="wrong",
        profile=Profile.LOCAL_SCOUT,
    )

    assert first.processed is True
    assert replay.processed is False
    assert store.get_account(workspace.public_id).state == "active"
    assert store.get_subscription(workspace.public_id, "stripe", "sub_001").status == "active"
    effective = store.effective_access(workspace.public_id)
    assert effective is not None
    assert effective.profile is Profile.FULL_OPERATOR
    assert effective.plan_key == "operator"
    assert len(store.list_events(workspace.public_id)) == 1
    assert len(store.list_grants(workspace.public_id)) == 1


def test_subscription_upgrade_downgrade_and_cancel(tmp_path):
    path = tmp_path / "platform.db"
    workspace = __import__("asyncio").run(_workspace(path))
    store = EntitlementStore(path)

    store.apply_subscription_event(
        provider="stripe",
        event_id="evt_full",
        event_type="subscription.updated",
        workspace=workspace.id,
        external_subscription_id="sub_1",
        subscription_status="active",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
    )
    store.apply_subscription_event(
        provider="stripe",
        event_id="evt_down",
        event_type="subscription.updated",
        workspace=workspace.id,
        external_subscription_id="sub_1",
        subscription_status="active",
        plan_key="national",
        profile=Profile.NATIONAL_SCOUT,
    )
    assert store.effective_access(workspace.id).profile is Profile.NATIONAL_SCOUT

    store.apply_subscription_event(
        provider="stripe",
        event_id="evt_cancel",
        event_type="subscription.deleted",
        workspace=workspace.id,
        external_subscription_id="sub_1",
        subscription_status="canceled",
        plan_key="national",
        profile=Profile.NATIONAL_SCOUT,
    )
    assert store.get_account(workspace.id).state == "canceled"
    assert store.effective_access(workspace.id) is None
    assert store.list_grants(workspace.id)[0].status == "revoked"


def test_skool_join_leave_and_duplicate_event(tmp_path):
    path = tmp_path / "platform.db"
    workspace = __import__("asyncio").run(_workspace(path))
    store = EntitlementStore(path)

    joined = store.apply_subscription_event(
        provider="skool",
        event_id="skool_join_1",
        event_type="membership.joined",
        workspace=workspace.public_id,
        external_subscription_id="member_1",
        subscription_status="active",
        plan_key="local-scout",
        profile=Profile.LOCAL_SCOUT,
    )
    duplicate = store.apply_subscription_event(
        provider="skool",
        event_id="skool_join_1",
        event_type="membership.joined",
        workspace=workspace.public_id,
        external_subscription_id="member_1",
        subscription_status="active",
        plan_key="local-scout",
        profile=Profile.LOCAL_SCOUT,
    )
    left = store.apply_subscription_event(
        provider="skool",
        event_id="skool_leave_1",
        event_type="membership.left",
        workspace=workspace.public_id,
        external_subscription_id="member_1",
        subscription_status="canceled",
        plan_key="local-scout",
        profile=Profile.LOCAL_SCOUT,
    )

    assert joined.processed is True
    assert duplicate.processed is False
    assert left.processed is True
    assert store.effective_access(workspace.public_id) is None


def test_manual_and_jv_grants_expire_and_revoke(tmp_path):
    path = tmp_path / "platform.db"
    workspace = __import__("asyncio").run(_workspace(path))
    store = EntitlementStore(path)
    now = datetime.now(UTC)

    expired = store.grant_access(
        workspace=workspace.id,
        source="promotion",
        external_ref="promo-old",
        profile=Profile.FULL_OPERATOR,
        plan_key="operator",
        ends_at=now - timedelta(seconds=1),
    )
    jv = store.grant_access(
        workspace=workspace.id,
        source="jv",
        external_ref="jv-7",
        profile=Profile.JV_PARTNER,
        plan_key="jv",
    )
    assert expired.status == "active"
    assert store.effective_access(workspace.id).profile is Profile.JV_PARTNER

    manual = store.grant_access(
        workspace=workspace.id,
        source="manual",
        external_ref="manual-1",
        profile=Profile.FULL_OPERATOR,
        plan_key="operator",
    )
    assert store.effective_access(workspace.id).profile is Profile.FULL_OPERATOR
    assert store.revoke_grant(workspace.id, manual.id).status == "revoked"
    assert store.effective_access(workspace.id).profile is Profile.JV_PARTNER
    assert store.revoke_grant(workspace.id, jv.id).status == "revoked"
    assert store.effective_access(workspace.id) is None


def test_payment_failure_is_terminal_without_dunning_access(tmp_path):
    path = tmp_path / "platform.db"
    workspace = __import__("asyncio").run(_workspace(path))
    store = EntitlementStore(path)
    period_end = datetime.now(UTC) + timedelta(days=3)

    store.apply_subscription_event(
        provider="stripe",
        event_id="evt_past_due",
        event_type="invoice.payment_failed",
        workspace=workspace.public_id,
        external_subscription_id="sub_due",
        subscription_status="past_due",
        plan_key="national",
        profile=Profile.NATIONAL_SCOUT,
        current_period_end=period_end,
    )
    assert store.get_account(workspace.id).state == "canceled"
    assert store.list_grants(workspace.id)[0].status == "revoked"
    assert store.effective_access(workspace.id) is None

    store.set_account_state(workspace.id, "deleted", reason="privacy deletion complete")
    with pytest.raises(ValueError, match="transition"):
        store.set_account_state(workspace.id, "active")


def test_unknown_workspace_and_cross_tenant_grant_access_are_denied(tmp_path):
    path = tmp_path / "platform.db"
    first = __import__("asyncio").run(_workspace(path))
    repository = PlatformRepository(path)
    second = __import__("asyncio").run(repository.create_workspace("Other CRE"))
    assert second is not None
    store = EntitlementStore(path)

    grant = store.grant_access(
        workspace=first.id,
        source="manual",
        external_ref="manual-cross",
        profile=Profile.LOCAL_SCOUT,
        plan_key="local",
    )
    assert store.get_grant(second.id, grant.id) is None
    assert store.revoke_grant(second.id, grant.id) is None
    with pytest.raises(ValueError, match="workspace"):
        store.grant_access(
            workspace="ws-does-not-exist",
            source="manual",
            external_ref="missing",
            profile=Profile.LOCAL_SCOUT,
            plan_key="local",
        )


def test_late_provider_event_is_journaled_without_reopening_canceled_account(tmp_path):
    path = tmp_path / "platform.db"
    workspace = __import__("asyncio").run(_workspace(path))
    store = EntitlementStore(path)

    store.apply_subscription_event(
        provider="stripe",
        event_id="evt_active_first",
        event_type="subscription.updated",
        workspace=workspace.id,
        external_subscription_id="sub_late",
        subscription_status="active",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
    )
    store.apply_subscription_event(
        provider="stripe",
        event_id="evt_cancel_second",
        event_type="subscription.deleted",
        workspace=workspace.id,
        external_subscription_id="sub_late",
        subscription_status="canceled",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
    )
    late = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_paused_late",
        event_type="subscription.updated",
        workspace=workspace.id,
        external_subscription_id="sub_late",
        subscription_status="paused",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
    )
    replay = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_paused_late",
        event_type="subscription.updated",
        workspace=workspace.id,
        external_subscription_id="sub_late",
        subscription_status="paused",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
    )

    assert late.processed is True
    assert replay.processed is False
    assert store.get_account(workspace.id).state == "canceled"
    assert len(store.list_events(workspace.id)) == 3
    assert store.effective_access(workspace.id) is None


def test_invited_account_state_is_reachable_for_a_new_workspace(tmp_path):
    path = tmp_path / "platform.db"
    workspace = __import__("asyncio").run(_workspace(path))
    store = EntitlementStore(path)

    invited = store.set_account_state(workspace.id, "invited")
    assert invited.state == "invited"
    assert store.set_account_state(workspace.id, "active").state == "active"


def test_stale_active_provider_event_cannot_reopen_newer_canceled_state(tmp_path):
    path = tmp_path / "platform.db"
    workspace = __import__("asyncio").run(_workspace(path))
    store = EntitlementStore(path)
    newer = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    older = newer - timedelta(hours=1)

    store.apply_subscription_event(
        provider="stripe",
        event_id="evt_cancel_newer",
        event_type="customer.subscription.deleted",
        workspace=workspace.id,
        external_subscription_id="sub_ordered",
        subscription_status="canceled",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
        occurred_at=newer,
    )
    stale = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_active_older",
        event_type="customer.subscription.updated",
        workspace=workspace.id,
        external_subscription_id="sub_ordered",
        subscription_status="active",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
        occurred_at=older,
    )

    assert stale.processed is False
    assert store.get_subscription(
        workspace.id, "stripe", "sub_ordered"
    ).status == "canceled"
    assert store.get_account(workspace.id).state == "canceled"
    assert store.effective_access(workspace.id) is None
    assert len(store.list_events(workspace.id)) == 2


def test_distinct_events_with_equal_source_timestamp_are_both_applied(tmp_path):
    path = tmp_path / "platform.db"
    workspace = __import__("asyncio").run(_workspace(path))
    store = EntitlementStore(path)
    occurred_at = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)

    first = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_equal_active",
        event_type="customer.subscription.updated",
        workspace=workspace.id,
        external_subscription_id="sub_equal",
        subscription_status="active",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
        occurred_at=occurred_at,
    )
    second = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_equal_canceled",
        event_type="customer.subscription.deleted",
        workspace=workspace.id,
        external_subscription_id="sub_equal",
        subscription_status="canceled",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
        occurred_at=occurred_at,
    )
    duplicate = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_equal_canceled",
        event_type="customer.subscription.deleted",
        workspace=workspace.id,
        external_subscription_id="sub_equal",
        subscription_status="active",
        plan_key="wrong",
        profile=Profile.LOCAL_SCOUT,
        occurred_at=occurred_at,
    )

    assert first.processed is True
    assert second.processed is True
    assert duplicate.processed is False
    assert store.get_subscription(
        workspace.id,
        "stripe",
        "sub_equal",
    ).status == "canceled"
    assert len(store.list_events(workspace.id)) == 2


@pytest.mark.parametrize("compatibility_path", ["grant", "event"])
def test_provider_compatibility_path_preserves_same_state_operator_reason(
    tmp_path,
    compatibility_path,
):
    path = tmp_path / "platform.db"
    workspace = __import__("asyncio").run(_workspace(path))
    store = EntitlementStore(path)
    store.set_account_state(
        workspace.id,
        "active",
        reason="operator-authored note",
    )

    if compatibility_path == "grant":
        store.grant_access(
            workspace=workspace.id,
            source="stripe",
            external_ref="sub_reason",
            profile=Profile.LOCAL_SCOUT,
            plan_key="local",
        )
    else:
        store.apply_subscription_event(
            provider="stripe",
            event_id="evt_reason",
            event_type="customer.subscription.updated",
            workspace=workspace.id,
            external_subscription_id="sub_reason",
            subscription_status="active",
            plan_key="local",
            profile=Profile.LOCAL_SCOUT,
        )

    account = store.get_account(workspace.id)
    assert account is not None
    assert account.state == "active"
    assert account.reason == "operator-authored note"
