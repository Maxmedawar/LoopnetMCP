"""Stripe test-mode launch contract and read-only reconciliation."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cre_mcp.config import CreConfig
from cre_mcp.platform.admin import AdminValidationError
from cre_mcp.platform.providers.core import ProviderSyncService
from cre_mcp.platform.providers.stripe import (
    StripeProviderUnavailableError,
    StripeReadClient,
    StripeReconciliationService,
    StripeSubscriptionSnapshot,
    parse_stripe_event,
)

from .admin_helpers import _seed_internal_admin, audit_rows
from .provider_helpers import (
    STRIPE_SECRET,
    api_client,
    json_bytes,
    provider_config,
    provider_events,
    seed_workspace,
    signed_headers,
    stripe_event,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "stripe"
ROTATED_SECRET = "whsec_test_stripe_rotated"


class FakeStripeTransport:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = list(pages)
        self.calls: list[dict[str, Any]] = []

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "params": params, "headers": headers})
        if not self.pages:
            raise AssertionError("unexpected Stripe API request")
        return self.pages.pop(0)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


async def test_rotating_webhook_secrets_accept_old_and_new_only(tmp_path):
    config = provider_config(
        tmp_path,
        stripe_webhook_secrets=(STRIPE_SECRET, ROTATED_SECRET),
        stripe_webhook_secret=None,
    )
    body = json_bytes(stripe_event("evt_rotating_secret", customer="cus_unknown"))

    async with api_client(config) as client:
        old = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body, secret=STRIPE_SECRET),
        )
        duplicate = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body, secret=ROTATED_SECRET),
        )
        denied = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body, secret="whsec_retired"),
        )

    assert old.status_code == 202
    assert duplicate.status_code == 200
    assert duplicate.json()["outcome"] == "duplicate"
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "invalid_webhook_signature"


async def test_live_mode_event_is_quarantined_in_test_only_runtime(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Stripe Test Mode",
        stripe_customer="cus_test_mode",
    )
    event = stripe_event(
        "evt_live_mode_rejected",
        customer="cus_test_mode",
        extra_envelope={"livemode": True},
    )
    body = json_bytes(event)

    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body),
        )

    assert response.status_code == 202
    assert response.json()["reason_code"] == "stripe_mode_mismatch"
    with sqlite3.connect(config.cache_db_path) as connection:
        grant_count = connection.execute(
            "SELECT COUNT(*) FROM platform_access_grants WHERE workspace_id=?",
            (workspace.id,),
        ).fetchone()[0]
    assert grant_count == 0


async def test_supported_event_without_mode_is_quarantined(tmp_path):
    config = provider_config(tmp_path)
    event = stripe_event("evt_mode_missing")
    event.pop("livemode")
    body = json_bytes(event)

    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body),
        )

    assert response.status_code == 202
    assert response.json()["reason_code"] == "stripe_mode_missing"


@pytest.mark.parametrize(
    "event_type,object_value",
    [
        (
            "customer.updated",
            {"id": "cus_observed", "object": "customer", "deleted": False},
        ),
        (
            "entitlements.active_entitlement_summary.updated",
            {
                "object": "entitlements.active_entitlement_summary",
                "customer": "cus_observed",
                "active_entitlements": {"data": [], "has_more": False},
            },
        ),
    ],
)
async def test_customer_and_entitlement_events_are_journaled_but_never_grant(
    tmp_path,
    event_type,
    object_value,
):
    config = provider_config(tmp_path)
    envelope = stripe_event(
        f"evt_{event_type.replace('.', '_')}",
        event_type=event_type,
        customer="cus_observed",
        extra_envelope={"data": {"object": object_value}},
    )
    body = json_bytes(envelope)

    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body),
        )

    assert response.status_code == 200
    assert response.json()["outcome"] == "rejected"
    assert response.json()["reason_code"] == "reconciliation_signal_only"
    assert provider_events(config.cache_db_path)[0]["event_type"] == event_type
    with sqlite3.connect(config.cache_db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_access_grants"
        ).fetchone()[0] == 0


def test_stripe_api_key_is_test_only_and_optional(tmp_path):
    with pytest.raises(StripeProviderUnavailableError):
        StripeReadClient.from_config(provider_config(tmp_path))

    with pytest.raises(ValidationError, match="test-mode"):
        provider_config(tmp_path, stripe_api_key="sk_live_forbidden")


async def test_read_client_uses_get_only_and_exhausts_pagination(tmp_path):
    transport = FakeStripeTransport(
        [_fixture("subscriptions_page_1.json"), _fixture("subscriptions_page_2.json")]
    )
    config = provider_config(tmp_path, stripe_api_key="rk_test_read_only")
    client = StripeReadClient.from_config(config, transport=transport)

    subscriptions = await client.list_subscriptions("cus_reconcile")

    assert [item.subscription_id for item in subscriptions] == [
        "sub_reconcile_active",
        "sub_reconcile_canceled",
    ]
    assert len(transport.calls) == 2
    assert transport.calls[0]["url"] == "https://api.stripe.com/v1/subscriptions"
    assert transport.calls[0]["params"] == {
        "customer": "cus_reconcile",
        "status": "all",
        "limit": "100",
    }
    assert transport.calls[1]["params"]["starting_after"] == "sub_reconcile_active"
    assert all(call["headers"]["Stripe-Version"] == "2026-02-25.clover" for call in transport.calls)
    assert all(call["headers"]["Authorization"] == "Bearer rk_test_read_only" for call in transport.calls)


async def test_reconciliation_repairs_current_state_and_revokes_missing(
    tmp_path,
):
    config = provider_config(tmp_path, stripe_api_key="rk_test_read_only")
    workspace = await seed_workspace(
        config,
        "Stripe Reconciliation",
        stripe_customer="cus_reconcile",
    )
    sync = ProviderSyncService(config)
    existing = stripe_event(
        "evt_existing_local",
        object_id="sub_missing_from_stripe",
        customer="cus_reconcile",
        prices=("price_local",),
    )
    sync.ingest(parse_stripe_event(existing))

    with sqlite3.connect(config.cache_db_path) as connection:
        admin_user_id = connection.execute(
            "SELECT user_id FROM platform_memberships WHERE workspace_id=?",
            (workspace.id,),
        ).fetchone()[0]
    _seed_internal_admin(
        config.cache_db_path,
        user_id=admin_user_id,
        role="platform_admin",
        active=True,
    )

    transport = FakeStripeTransport([_fixture("subscriptions_reconcile.json")])
    reader = StripeReadClient.from_config(config, transport=transport)
    service = StripeReconciliationService(config, reader=reader)
    report = await service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=admin_user_id,
        reason_code="billing_correction",
        reason="Compared the complete Stripe test subscription list.",
        observed_at=datetime(2026, 8, 4, 18, 0, tzinfo=UTC),
    )

    assert report["provider"] == "stripe"
    assert report["complete"] is True
    assert report["discrepancy_count"] == 2
    assert {item["subscription_id"] for item in report["results"]} == {
        "sub_reconcile_active",
        "sub_missing_from_stripe",
    }
    with sqlite3.connect(config.cache_db_path) as connection:
        rows = connection.execute(
            """
            SELECT external_ref,status,profile FROM platform_access_grants
            WHERE workspace_id=? AND source='stripe' ORDER BY external_ref
            """,
            (workspace.id,),
        ).fetchall()
    assert rows == [
        ("sub_missing_from_stripe", "revoked", "local_scout"),
        ("sub_reconcile_active", "active", "national_scout"),
    ]
    assert audit_rows(config.cache_db_path)[-1]["action"] == "stripe.reconcile"


async def test_reconciliation_can_repair_same_provider_state_again(tmp_path):
    config = provider_config(tmp_path, stripe_api_key="rk_test_read_only")
    workspace = await seed_workspace(
        config,
        "Stripe Repeat Repair",
        stripe_customer="cus_reconcile",
    )
    with sqlite3.connect(config.cache_db_path) as connection:
        admin_user_id = connection.execute(
            "SELECT user_id FROM platform_memberships WHERE workspace_id=?",
            (workspace.id,),
        ).fetchone()[0]
    _seed_internal_admin(
        config.cache_db_path,
        user_id=admin_user_id,
        role="platform_admin",
        active=True,
    )

    first_reader = StripeReadClient.from_config(
        config,
        transport=FakeStripeTransport([_fixture("subscriptions_reconcile.json")]),
    )
    await StripeReconciliationService(
        config,
        reader=first_reader,
    ).reconcile_workspace(
        workspace.public_id,
        actor_user_id=admin_user_id,
        reason_code="billing_correction",
        reason="Applied the first complete Stripe test observation.",
        observed_at=datetime(2026, 8, 4, 18, 0, tzinfo=UTC),
    )
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            UPDATE platform_access_grants SET status='revoked'
            WHERE workspace_id=? AND source='stripe'
            """,
            (workspace.id,),
        )

    second_reader = StripeReadClient.from_config(
        config,
        transport=FakeStripeTransport([_fixture("subscriptions_reconcile.json")]),
    )
    report = await StripeReconciliationService(
        config,
        reader=second_reader,
    ).reconcile_workspace(
        workspace.public_id,
        actor_user_id=admin_user_id,
        reason_code="entitlement_correction",
        reason="Repaired drift from a later complete Stripe test observation.",
        observed_at=datetime(2026, 8, 4, 18, 5, tzinfo=UTC),
    )

    assert report["discrepancy_count"] == 1
    with sqlite3.connect(config.cache_db_path) as connection:
        status = connection.execute(
            """
            SELECT status FROM platform_access_grants
            WHERE workspace_id=? AND source='stripe'
            """,
            (workspace.id,),
        ).fetchone()[0]
    assert status == "active"


async def test_reconciliation_aborts_if_customer_mapping_changes_during_read(
    tmp_path,
):
    config = provider_config(tmp_path, stripe_api_key="rk_test_read_only")
    workspace = await seed_workspace(
        config,
        "Stripe Mapping Race",
        stripe_customer="cus_reconcile",
    )
    with sqlite3.connect(config.cache_db_path) as connection:
        admin_user_id = connection.execute(
            "SELECT user_id FROM platform_memberships WHERE workspace_id=?",
            (workspace.id,),
        ).fetchone()[0]
    _seed_internal_admin(
        config.cache_db_path,
        user_id=admin_user_id,
        role="platform_admin",
        active=True,
    )

    class MappingChangingReader:
        async def list_subscriptions(self, customer_id: str):
            assert customer_id == "cus_reconcile"
            with sqlite3.connect(config.cache_db_path) as connection:
                connection.execute(
                    """
                    UPDATE platform_external_accounts
                    SET external_account_id='cus_changed'
                    WHERE workspace_id=? AND provider='stripe'
                    """,
                    (workspace.id,),
                )
            return (
                StripeSubscriptionSnapshot(
                    "sub_race",
                    "cus_reconcile",
                    "active",
                    ("price_local",),
                    None,
                ),
            )

    with pytest.raises(
        AdminValidationError,
        match="changed during reconciliation",
    ):
        await StripeReconciliationService(
            config,
            reader=MappingChangingReader(),
        ).reconcile_workspace(
            workspace.public_id,
            actor_user_id=admin_user_id,
            reason_code="billing_correction",
            reason="A racing customer mapping must stop reconciliation.",
        )
    with sqlite3.connect(config.cache_db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_access_grants WHERE workspace_id=?",
            (workspace.id,),
        ).fetchone()[0] == 0
