"""Red-first regressions for provider authority, leases, and containment."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError
from starlette.requests import Request

from cre_mcp.config import CreConfig
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.entitlements import (
    ENTITLEMENT_MIGRATIONS,
    PROVIDER_SYNC_MIGRATIONS,
    EntitlementStore,
    _ENTITLEMENT_SCHEMA,
)
from cre_mcp.platform.migrations import apply_migrations, current_version
from cre_mcp.platform.providers.reconciliation import _event
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.platform.schema import create_schema
from cre_mcp.server import create_http_app

from .provider_helpers import (
    NOW,
    api_client,
    json_bytes,
    provider_config,
    provider_events,
    signed_headers,
    skool_event,
    stripe_event,
)
from .test_authoritative_oauth import (
    _raw_initialized_session,
    _raw_mcp_request,
)


SCOPES = ("mcp:tools", "deals:read")
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
REASON_HEADERS = {
    "x-admin-reason-code": "support_resolution",
    "x-admin-reason": "Verified by the internal operations runbook.",
}


async def _post(config: CreConfig, provider: str, value: dict) -> httpx.Response:
    body = json_bytes(value)
    async with api_client(config) as client:
        return await client.post(
            f"/v1/webhooks/{provider}",
            content=body,
            headers=signed_headers(provider, body),
        )


async def _workspace_with_users(
    config: CreConfig,
    name: str,
    *,
    user_count: int = 1,
):
    repository = PlatformRepository(config.cache_db_path)
    for key in ("local", "national", "operator"):
        if not any(plan.key == key for plan in await repository.list_plans()):
            plan = await repository.create_plan(
                key,
                key.title(),
                daily_quotas={},
            )
            assert plan is not None
    workspace = await repository.create_workspace(name)
    assert workspace is not None
    users = []
    for index in range(user_count):
        user = await repository.create_user(
            f"{name.casefold().replace(' ', '-')}-{index}@example.test",
            f"{name} User {index}",
        )
        assert user is not None
        membership = await repository.add_membership(
            workspace.public_id,
            user.id,
            role="owner" if index == 0 else "member",
        )
        assert membership is not None
        users.append(user)
    return workspace, users


def _insert_mapping(
    path,
    *,
    workspace_id: int,
    subject_user_id: int,
    provider: str,
    external_account_id: str,
) -> None:
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(platform_external_accounts)"
            )
        }
        if "subject_user_id" in columns:
            connection.execute(
                """
                INSERT INTO platform_external_accounts(
                    workspace_id,subject_user_id,provider,external_account_id,
                    metadata,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    workspace_id,
                    subject_user_id,
                    provider,
                    external_account_id,
                    "{}",
                    now,
                    now,
                ),
            )
        else:
            connection.execute(
                """
                INSERT INTO platform_external_accounts(
                    workspace_id,provider,external_account_id,metadata,
                    created_at,updated_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    workspace_id,
                    provider,
                    external_account_id,
                    "{}",
                    now,
                    now,
                ),
            )


def _issue_tokens(config: CreConfig, workspace, users):
    auth = OAuthSessionStore(config.cache_db_path)
    client = auth.register_client("Provider security", (REDIRECT,), SCOPES)
    tokens = [
        auth.issue_session(
            workspace.public_id,
            user.id,
            client.client_id,
            scopes=SCOPES,
        )
        for user in users
    ]
    return auth, client, tokens


def _future_period() -> int:
    return int((datetime.now(UTC) + timedelta(days=30)).timestamp())


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_grant_lease_seconds", 0),
        ("provider_grant_lease_seconds", -1),
        ("provider_grant_lease_seconds", 604801),
    ],
)
def test_provider_lease_setting_is_server_owned_and_safely_bounded(
    tmp_path,
    field,
    value,
):
    with pytest.raises(ValidationError):
        provider_config(tmp_path, **{field: value})

    default = CreConfig(_env_file=None)
    assert 1 <= default.provider_grant_lease_seconds <= 604800


async def test_every_positive_provider_grant_has_a_bounded_end(tmp_path):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(config, "Bounded Grants")
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id="cus_bounded",
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="skool",
        external_account_id="member_bounded",
    )

    stripe = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_bounded",
            customer="cus_bounded",
            period_end=None,
        ),
    )
    skool = await _post(
        config,
        "skool",
        skool_event(
            "sk_bounded",
            event_type="member.added",
            member_id="member_bounded",
        ),
    )

    assert stripe.status_code == 200
    assert skool.status_code == 200
    with sqlite3.connect(config.cache_db_path) as connection:
        rows = connection.execute(
            """
            SELECT source,ends_at
            FROM platform_access_grants
            WHERE source IN ('stripe','skool')
            ORDER BY source
            """
        ).fetchall()
    assert rows
    assert all(row[1] is not None for row in rows)


async def test_expired_provider_lease_denies_v1_and_real_mcp_without_event(
    tmp_path,
):
    config = provider_config(tmp_path, provider_grant_lease_seconds=1)
    workspace, users = await _workspace_with_users(config, "Lease Expiry")
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id="cus_lease_expiry",
    )
    _, _, tokens = _issue_tokens(config, workspace, users)

    granted = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_lease_expiry",
            customer="cus_lease_expiry",
            period_end=None,
        ),
    )
    assert granted.status_code == 200
    await asyncio.sleep(1.1)

    app = create_http_app(config=config)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://lease.test",
        ) as client:
            api = await client.get(
                "/v1/deals",
                headers={"authorization": f"Bearer {tokens[0].access_token}"},
            )
            mcp = await _raw_mcp_request(
                client,
                tokens[0].access_token,
                method="initialize",
                request_id=1,
                params={
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "lease-test", "version": "1"},
                },
            )

    assert api.status_code == 403
    assert api.json()["error"]["code"] == "access_disabled"
    assert mcp.status_code == 403
    assert "mcp-session-id" not in mcp.headers


@pytest.mark.parametrize(
    "case",
    [
        "stripe_empty_price_cancel",
        "stripe_unmapped_price_pause",
        "stripe_plan_not_found_cancel",
        "skool_unmapped_level",
        "stripe_grace_period_payment_failure",
    ],
)
async def test_restrictive_event_never_preserves_existing_live_grant(
    tmp_path,
    case,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(config, f"Restrictive {case}")
    provider = "skool" if case == "skool_unmapped_level" else "stripe"
    external_id = "member_restrictive" if provider == "skool" else "cus_restrictive"
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider=provider,
        external_account_id=external_id,
    )

    if provider == "skool":
        bootstrap = await _post(
            config,
            "skool",
            skool_event(
                "sk_restrictive_start",
                event_type="member.added",
                member_id=external_id,
                created=100,
            ),
        )
        restrictive = skool_event(
            "sk_restrictive_loss",
            event_type="member.updated",
            member_id=external_id,
            level_id="free_or_unmapped",
            created=200,
        )
    else:
        bootstrap = await _post(
            config,
            "stripe",
            stripe_event(
                "evt_restrictive_start",
                customer=external_id,
                created=100,
                period_end=_future_period(),
            ),
        )
        if case == "stripe_empty_price_cancel":
            restrictive = stripe_event(
                "evt_restrictive_cancel",
                event_type="customer.subscription.deleted",
                customer=external_id,
                status="canceled",
                prices=(),
                created=200,
            )
        elif case == "stripe_unmapped_price_pause":
            restrictive = stripe_event(
                "evt_restrictive_pause",
                event_type="customer.subscription.paused",
                customer=external_id,
                status="active",
                prices=("retired_price",),
                created=200,
            )
        elif case == "stripe_plan_not_found_cancel":
            with sqlite3.connect(config.cache_db_path) as connection:
                connection.execute("DELETE FROM platform_plans WHERE key='local'")
            restrictive = stripe_event(
                "evt_restrictive_missing_plan",
                event_type="customer.subscription.deleted",
                customer=external_id,
                status="canceled",
                prices=("price_local",),
                created=200,
            )
        else:
            grace = await _post(
                config,
                "stripe",
                stripe_event(
                    "evt_restrictive_grace",
                    customer=external_id,
                    status="grace_period",
                    created=150,
                    period_end=_future_period(),
                ),
            )
            assert grace.status_code == 200
            restrictive = stripe_event(
                "evt_restrictive_failed",
                event_type="invoice.payment_failed",
                object_id="in_restrictive",
                customer=external_id,
                prices=(),
                created=200,
                extra_object={"subscription": "sub_1"},
            )

    assert bootstrap.status_code == 200
    response = await _post(config, provider, restrictive)
    assert response.status_code == 200
    with sqlite3.connect(config.cache_db_path) as connection:
        status = connection.execute(
            """
            SELECT status FROM platform_access_grants
            WHERE source=? ORDER BY id DESC LIMIT 1
            """,
            (provider,),
        ).fetchone()[0]
    assert status == "revoked"


@pytest.mark.parametrize(
    "event_type",
    ["member.canceled", "member.payment_failed", "member.banned"],
)
async def test_explicit_relay_restrictions_revoke_without_level_mapping(
    tmp_path,
    event_type,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        f"Relay {event_type}",
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="skool",
        external_account_id="member_explicit_restrict",
    )
    assert (
        await _post(
            config,
            "skool",
            skool_event(
                "sk_explicit_start",
                event_type="member.added",
                member_id="member_explicit_restrict",
                created=100,
            ),
        )
    ).status_code == 200

    response = await _post(
        config,
        "skool",
        skool_event(
            f"sk_{event_type}",
            event_type=event_type,
            member_id="member_explicit_restrict",
            community_id="unknown",
            level_id="unknown",
            created=200,
        ),
    )

    assert response.status_code == 200
    with sqlite3.connect(config.cache_db_path) as connection:
        status = connection.execute(
            "SELECT status FROM platform_access_grants WHERE source='skool'"
        ).fetchone()[0]
    assert status == "revoked"


async def test_deleted_stripe_event_revokes_before_optional_metadata_parsing(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Deleted Metadata",
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id="cus_deleted_metadata",
    )
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_deleted_metadata_start",
                customer="cus_deleted_metadata",
                created=100,
            ),
        )
    ).status_code == 200

    response = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_deleted_metadata",
            event_type="customer.subscription.deleted",
            customer="cus_deleted_metadata",
            created=200,
            extra_object={
                "status": None,
                "items": "not-an-item-list",
                "current_period_end": "not-a-timestamp",
            },
        ),
    )

    assert response.status_code == 200
    with sqlite3.connect(config.cache_db_path) as connection:
        status = connection.execute(
            "SELECT status FROM platform_access_grants WHERE source='stripe'"
        ).fetchone()[0]
    assert status == "revoked"


async def test_existing_skool_member_update_without_level_fails_closed(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Missing Relay Level",
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="skool",
        external_account_id="member_missing_level",
    )
    assert (
        await _post(
            config,
            "skool",
            skool_event(
                "sk_missing_level_start",
                event_type="member.added",
                member_id="member_missing_level",
                created=100,
            ),
        )
    ).status_code == 200

    response = await _post(
        config,
        "skool",
        skool_event(
            "sk_missing_level_loss",
            event_type="member.updated",
            created=200,
            extra={"member": {"id": "member_missing_level"}},
        ),
    )

    assert response.status_code == 200
    assert response.json()["reason_code"] == "loss_of_paid_level"
    with sqlite3.connect(config.cache_db_path) as connection:
        status = connection.execute(
            "SELECT status FROM platform_access_grants WHERE source='skool'"
        ).fetchone()[0]
    assert status == "revoked"


async def test_individual_provider_entitlement_does_not_cross_workspace_users(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Individual Authority",
        user_count=2,
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id="cus_individual",
    )
    auth, _, tokens = _issue_tokens(config, workspace, users)
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_individual_start",
                customer="cus_individual",
                created=100,
                period_end=_future_period(),
            ),
        )
    ).status_code == 200

    async with api_client(config) as client:
        paid = await client.get(
            "/v1/deals",
            headers={"authorization": f"Bearer {tokens[0].access_token}"},
        )
        unpaid = await client.get(
            "/v1/deals",
            headers={"authorization": f"Bearer {tokens[1].access_token}"},
        )
    assert paid.status_code == 200
    assert unpaid.status_code == 403

    canceled = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_individual_cancel",
            event_type="customer.subscription.deleted",
            customer="cus_individual",
            status="canceled",
            prices=(),
            created=200,
        ),
    )
    assert canceled.status_code == 200
    assert auth.validate_access(tokens[0].access_token) is None
    assert auth.validate_access(tokens[1].access_token) is not None


async def test_customer_entitlement_summary_is_subject_scoped_and_redacted(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Private Entitlement Summary",
        user_count=2,
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id="cus_private_summary",
    )
    _, _, tokens = _issue_tokens(config, workspace, users)
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_private_summary",
                object_id="sub_private_provider_id",
                customer="cus_private_summary",
                period_end=_future_period(),
            ),
        )
    ).status_code == 200

    async with api_client(config) as client:
        paid = await client.get(
            "/v1/entitlements",
            headers={"authorization": f"Bearer {tokens[0].access_token}"},
        )
        unpaid = await client.get(
            "/v1/entitlements",
            headers={"authorization": f"Bearer {tokens[1].access_token}"},
        )

    assert paid.status_code == 200
    assert unpaid.status_code == 200
    assert paid.json()["access_enabled"] is True
    assert unpaid.json()["access_enabled"] is False
    assert len(paid.json()["grants"]) == 1
    assert unpaid.json()["grants"] == []
    assert set(paid.json()["grants"][0]) == {
        "source",
        "profile",
        "plan_key",
        "status",
        "starts_at",
        "ends_at",
    }
    serialized = json.dumps(
        {"paid": paid.json(), "unpaid": unpaid.json()},
        sort_keys=True,
    )
    assert "sub_private_provider_id" not in serialized
    assert "cus_private_summary" not in serialized
    assert "subject_user_id" not in serialized
    assert '"external_ref"' not in serialized


async def test_provider_loss_revokes_open_mcp_api_refresh_and_pending_code(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(config, "Atomic OAuth Loss")
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id="cus_atomic_loss",
    )
    auth, client_registration, tokens = _issue_tokens(config, workspace, users)
    verifier = "v" * 43
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    pending_code = auth.create_auth_code(
        workspace.public_id,
        users[0].id,
        client_registration.client_id,
        REDIRECT,
        challenge,
        scopes=SCOPES,
    )
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_atomic_start",
                customer="cus_atomic_loss",
                created=100,
                period_end=_future_period(),
            ),
        )
    ).status_code == 200

    app = create_http_app(config=config)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://atomic.test",
        ) as request_client:
            session_id = await _raw_initialized_session(
                request_client,
                tokens[0].access_token,
            )
            before = await request_client.get(
                "/v1/deals",
                headers={"authorization": f"Bearer {tokens[0].access_token}"},
            )
            body = json_bytes(
                stripe_event(
                    "evt_atomic_cancel",
                    event_type="customer.subscription.deleted",
                    customer="cus_atomic_loss",
                    status="canceled",
                    prices=(),
                    created=200,
                )
            )
            canceled = await request_client.post(
                "/v1/webhooks/stripe",
                content=body,
                headers=signed_headers("stripe", body),
            )
            after_api = await request_client.get(
                "/v1/deals",
                headers={"authorization": f"Bearer {tokens[0].access_token}"},
            )
            after_mcp = await _raw_mcp_request(
                request_client,
                tokens[0].access_token,
                method="tools/list",
                request_id=2,
                params={},
                session_id=session_id,
            )

    assert before.status_code == 200
    assert canceled.status_code == 200
    assert after_api.status_code == 401
    assert after_mcp.status_code == 401
    assert (
        auth.refresh_session(
            tokens[0].refresh_token,
            client_id=client_registration.client_id,
        )
        is None
    )
    with pytest.raises(ValueError, match="invalid or expired authorization code"):
        auth.exchange_code(
            pending_code,
            client_registration.client_id,
            REDIRECT,
            verifier,
        )


async def test_oauth_revocation_failure_rolls_back_provider_loss_atomically(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(config, "OAuth Rollback")
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id="cus_oauth_rollback",
    )
    auth, _, tokens = _issue_tokens(config, workspace, users)
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_oauth_rollback_start",
                customer="cus_oauth_rollback",
                created=100,
                period_end=_future_period(),
            ),
        )
    ).status_code == 200
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_subject_oauth_revoke
            BEFORE UPDATE ON platform_oauth_sessions
            WHEN OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'injected oauth revocation failure');
            END
            """
        )

    canceled = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_oauth_rollback_cancel",
            event_type="customer.subscription.deleted",
            customer="cus_oauth_rollback",
            status="canceled",
            prices=(),
            created=200,
        ),
    )

    assert canceled.status_code == 202
    assert canceled.json()["outcome"] == "quarantined"
    with sqlite3.connect(config.cache_db_path) as connection:
        grant_status = connection.execute(
            "SELECT status FROM platform_access_grants WHERE source='stripe'"
        ).fetchone()[0]
    assert grant_status == "active"
    assert auth.validate_access(tokens[0].access_token) is not None


async def test_same_subject_surviving_provider_grant_preserves_oauth(tmp_path):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(config, "Subject Survivor")
    for provider, external_id in (
        ("stripe", "cus_subject_survivor"),
        ("skool", "member_subject_survivor"),
    ):
        _insert_mapping(
            config.cache_db_path,
            workspace_id=workspace.id,
            subject_user_id=users[0].id,
            provider=provider,
            external_account_id=external_id,
        )
    auth, client_registration, tokens = _issue_tokens(config, workspace, users)
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_subject_survivor_stripe",
                customer="cus_subject_survivor",
                created=100,
                period_end=_future_period(),
            ),
        )
    ).status_code == 200
    assert (
        await _post(
            config,
            "skool",
            skool_event(
                "sk_subject_survivor",
                event_type="member.added",
                member_id="member_subject_survivor",
                created=100,
            ),
        )
    ).status_code == 200

    canceled = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_subject_survivor_cancel",
            event_type="customer.subscription.deleted",
            customer="cus_subject_survivor",
            status="canceled",
            prices=(),
            created=200,
        ),
    )

    assert canceled.status_code == 200
    assert auth.validate_access(tokens[0].access_token) is not None
    assert (
        auth.refresh_session(
            tokens[0].refresh_token,
            client_id=client_registration.client_id,
        )
        is not None
    )


@pytest.mark.parametrize("declared", ["0", "-1", "not-an-integer"])
async def test_nonpositive_or_invalid_content_length_is_rejected_before_read(
    tmp_path,
    declared,
):
    from cre_mcp.platform.api import PlatformApi

    config = provider_config(tmp_path)
    body = json_bytes(stripe_event("evt_bad_length"))
    reads = 0

    async def receive():
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/webhooks/stripe",
            "raw_path": b"/v1/webhooks/stripe",
            "query_string": b"",
            "headers": [
                (b"content-length", declared.encode("ascii")),
                (
                    b"stripe-signature",
                    signed_headers("stripe", body)["stripe-signature"].encode(),
                ),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("provider.test", 80),
        },
        receive,
    )

    response = await PlatformApi(config).stripe_webhook(request)

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "invalid_content_length"
    assert reads == 0


async def test_missing_content_length_still_supports_bounded_streaming(tmp_path):
    from cre_mcp.platform.api import PlatformApi

    config = provider_config(tmp_path)
    body = json_bytes(stripe_event("evt_transfer_semantics"))
    chunks = [body[:11], body[11:]]
    reads = 0

    async def receive():
        nonlocal reads
        index = reads
        reads += 1
        return {
            "type": "http.request",
            "body": chunks[index],
            "more_body": index == 0,
        }

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/webhooks/stripe",
            "raw_path": b"/v1/webhooks/stripe",
            "query_string": b"",
            "headers": [
                (
                    b"stripe-signature",
                    signed_headers("stripe", body)["stripe-signature"].encode(),
                ),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("provider.test", 80),
        },
        receive,
    )

    response = await PlatformApi(config).stripe_webhook(request)

    assert response.status_code == 202
    assert reads == 2


async def test_quarantine_emits_safe_operator_visible_warning(tmp_path, caplog):
    config = provider_config(tmp_path)
    caplog.set_level(logging.WARNING)

    response = await _post(
        config,
        "stripe",
        stripe_event("evt_visible_quarantine", customer="cus_not_linked"),
    )

    assert response.status_code == 202
    assert response.json()["reason_code"] == "unmapped_external_account"
    assert "provider_event_quarantined" in caplog.text
    assert "cus_not_linked" not in caplog.text


async def test_reconciliation_reason_is_not_accepted_from_query_string(tmp_path):
    from .admin_helpers import VALID_REASON, provision_identity

    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        "Reason Header Admin",
        internal_role="platform_admin",
    )
    await _post(
        config,
        "stripe",
        stripe_event("evt_reason_header", customer="cus_reason_header"),
    )
    query_reason = (
        "provider=stripe&reason_code="
        f"{VALID_REASON['reason_code']}&reason={VALID_REASON['reason']}"
    )
    async with api_client(config) as client:
        leaked = await client.get(
            f"/v1/admin/provider-events/quarantine?{query_reason}",
            headers=admin.headers,
        )
        accepted = await client.get(
            "/v1/admin/provider-events/quarantine?provider=stripe",
            headers={**admin.headers, **REASON_HEADERS},
        )

    assert leaked.status_code == 422
    assert accepted.status_code == 200


async def test_external_account_provider_accepts_safe_provider_neutral_slug(
    tmp_path,
):
    from .admin_helpers import VALID_REASON, provision_identity, provision_target

    config = provider_config(tmp_path)
    actor = await provision_identity(
        config,
        "Provider Neutral Admin",
        internal_role="platform_admin",
    )
    target = await provision_target(config, "Provider Neutral Target")

    async with api_client(config) as client:
        response = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/external-accounts",
            headers=actor.headers,
            json={
                "provider": "attacker-controlled-provider",
                "external_account_id": "external-1",
                **VALID_REASON,
            },
        )

    assert response.status_code == 201
    assert response.json()["external_account"]["provider"] == (
        "attacker-controlled-provider"
    )
    assert response.json()["external_account"]["subject_user_id"] is None


def test_reconciliation_event_exposes_replay_and_duplicate_metadata(tmp_path):
    config = provider_config(tmp_path)
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(
            """
            INSERT INTO platform_provider_events(
                workspace_id,provider,event_id,event_type,payload,
                normalized_data,occurred_at,outcome,reason_code,
                duplicate_count,replayed_at,created_at,updated_at
            ) VALUES (
                NULL,'stripe','evt_metadata','unsupported','{}','{}',?,
                'quarantined','unmapped_external_account',3,?,?,?
            )
            """,
            (now, now, now, now),
        )
        row = connection.execute(
            "SELECT * FROM platform_provider_events WHERE id=?",
            (cursor.lastrowid,),
        ).fetchone()

    value = _event(row)
    assert value["duplicate_count"] == 3
    assert value["replayed_at"] == now


def test_provider_sync_v2_fails_closed_legacy_unbound_provider_grant(tmp_path):
    path = tmp_path / "provider-v1.db"
    now = "2026-07-28T12:00:00+00:00"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        apply_migrations(
            connection,
            "entitlements",
            ENTITLEMENT_MIGRATIONS,
        )
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS[:1],
        )
        connection.execute(
            """
            INSERT INTO platform_plans(
                key,name,daily_quotas,created_at,updated_at
            ) VALUES ('local','Local','{}',?,?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_workspaces(public_id,name,created_at,updated_at)
            VALUES ('ws-legacy-provider','Legacy Provider',?,?)
            """,
            (now, now),
        )
        workspace_id = int(
            connection.execute(
                """
                SELECT id FROM platform_workspaces
                WHERE public_id='ws-legacy-provider'
                """
            ).fetchone()[0]
        )
        for index in range(2):
            cursor = connection.execute(
                """
                INSERT INTO platform_users(email,name,created_at,updated_at)
                VALUES (?,?,?,?)
                """,
                (f"legacy-{index}@example.test", f"Legacy {index}", now, now),
            )
            connection.execute(
                """
                INSERT INTO platform_memberships(
                    workspace_id,user_id,role,created_at,updated_at
                ) VALUES (?,?,?,?,?)
                """,
                (workspace_id, cursor.lastrowid, "member", now, now),
            )
        connection.execute(
            """
            INSERT INTO platform_accounts(workspace_id,state,reason,updated_at)
            VALUES (?,'active','legacy provider access',?)
            """,
            (workspace_id, now),
        )
        connection.execute(
            """
            INSERT INTO platform_access_grants(
                workspace_id,source,external_ref,profile,plan_key,status,
                starts_at,ends_at,created_at,updated_at
            ) VALUES (?,'skool','legacy-member','local_scout','local','active',
                      ?,NULL,?,?)
            """,
            (workspace_id, now, now, now),
        )

    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        grant = connection.execute(
            """
            SELECT * FROM platform_access_grants
            WHERE external_ref='legacy-member'
            """
        ).fetchone()
        grant_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(platform_access_grants)"
            )
        }
        mapping_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(platform_external_accounts)"
            )
        }
        version = current_version(connection, "provider-sync")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        account = connection.execute(
            """
            SELECT state,reason FROM platform_accounts
            WHERE workspace_id=?
            """,
            (workspace_id,),
        ).fetchone()

    assert version == 5
    assert "subject_user_id" in grant_columns
    assert "scope" in grant_columns
    assert "subject_user_id" in mapping_columns
    assert grant["status"] == "revoked"
    assert grant["ends_at"] is not None
    assert grant["subject_user_id"] is None
    assert grant["scope"] == "subject"
    assert account["state"] == "canceled"
    assert account["reason"] is None
    assert foreign_keys == []
    assert integrity == "ok"


@pytest.mark.parametrize(
    "starting_state,survivor_source,expected_state,expected_reason",
    [
        ("active", "manual", "canceled", None),
        ("active", "jv", "active", "retained active note"),
        ("suspended", None, "suspended", "operator hold"),
    ],
)
def test_provider_sync_v2_rederives_affected_account_safely(
    tmp_path,
    starting_state,
    survivor_source,
    expected_state,
    expected_reason,
):
    path = tmp_path / f"provider-v1-account-{starting_state}-{survivor_source}.db"
    now = "2026-07-28T12:00:00+00:00"
    reason = (
        "operator hold"
        if starting_state == "suspended"
        else "retained active note"
    )
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        apply_migrations(connection, "entitlements", ENTITLEMENT_MIGRATIONS)
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS[:1],
        )
        connection.execute(
            """
            INSERT INTO platform_plans(
                key,name,daily_quotas,created_at,updated_at
            ) VALUES ('local','Local','{}',?,?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_workspaces(public_id,name,created_at,updated_at)
            VALUES ('ws-account-derive','Account Derive',?,?)
            """,
            (now, now),
        )
        workspace_id = int(
            connection.execute(
                """
                SELECT id FROM platform_workspaces
                WHERE public_id='ws-account-derive'
                """
            ).fetchone()[0]
        )
        for index in range(2):
            user_id = connection.execute(
                """
                INSERT INTO platform_users(email,name,created_at,updated_at)
                VALUES (?,?,?,?)
                """,
                (
                    f"account-derive-{index}@example.test",
                    f"Account Derive {index}",
                    now,
                    now,
                ),
            ).lastrowid
            connection.execute(
                """
                INSERT INTO platform_memberships(
                    workspace_id,user_id,role,created_at,updated_at
                ) VALUES (?,?, 'member',?,?)
                """,
                (workspace_id, user_id, now, now),
            )
        connection.execute(
            """
            INSERT INTO platform_accounts(workspace_id,state,reason,updated_at)
            VALUES (?,?,?,?)
            """,
            (workspace_id, starting_state, reason, now),
        )
        connection.execute(
            """
            INSERT INTO platform_access_grants(
                workspace_id,source,external_ref,profile,plan_key,status,
                starts_at,ends_at,created_at,updated_at
            ) VALUES (
                ?,'skool','legacy-provider','local_scout','local','active',
                ?,NULL,?,?
            )
            """,
            (workspace_id, now, now, now),
        )
        if survivor_source is not None:
            profile = (
                "jv_partner"
                if survivor_source == "jv"
                else "local_scout"
            )
            connection.execute(
                """
                INSERT INTO platform_access_grants(
                    workspace_id,source,external_ref,profile,plan_key,status,
                    starts_at,ends_at,created_at,updated_at
                ) VALUES (?,?,?,?,?,'active',?,NULL,?,?)
                """,
                (
                    workspace_id,
                    survivor_source,
                    f"{survivor_source}-survivor",
                    profile,
                    "local",
                    now,
                    now,
                    now,
                ),
            )

    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        account = connection.execute(
            """
            SELECT state,reason FROM platform_accounts
            WHERE workspace_id=?
            """,
            (workspace_id,),
        ).fetchone()
        provider_grant = connection.execute(
            """
            SELECT status FROM platform_access_grants
            WHERE source='skool'
            """
        ).fetchone()

    assert provider_grant["status"] == "revoked"
    assert account["state"] == expected_state
    assert account["reason"] == expected_reason


def test_provider_sync_v2_revokes_legacy_dunning_grant(tmp_path):
    path = tmp_path / "provider-v1-past-due.db"
    now = "2026-07-28T12:00:00+00:00"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        apply_migrations(connection, "entitlements", ENTITLEMENT_MIGRATIONS)
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS[:1],
        )
        connection.execute(
            """
            INSERT INTO platform_workspaces(public_id,name,created_at,updated_at)
            VALUES ('ws-legacy-dunning','Legacy Dunning',?,?)
            """,
            (now, now),
        )
        workspace_id = int(connection.execute(
            "SELECT id FROM platform_workspaces WHERE public_id='ws-legacy-dunning'"
        ).fetchone()[0])
        user_id = int(connection.execute(
            """
            INSERT INTO platform_users(email,name,created_at,updated_at)
            VALUES ('legacy-dunning@example.test','Legacy Dunning',?,?)
            RETURNING id
            """,
            (now, now),
        ).fetchone()[0])
        connection.execute(
            """
            INSERT INTO platform_memberships(
                workspace_id,user_id,role,created_at,updated_at
            ) VALUES (?,?, 'owner',?,?)
            """,
            (workspace_id, user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_subscriptions(
                workspace_id,provider,external_subscription_id,
                external_customer_id,status,plan_key,current_period_end,
                last_event_at,created_at,updated_at
            ) VALUES (
                ?,'stripe','sub-legacy-dunning','cus-legacy-dunning',
                'past_due','local',NULL,?,?,?
            )
            """,
            (workspace_id, now, now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_access_grants(
                workspace_id,source,external_ref,profile,plan_key,status,
                starts_at,ends_at,created_at,updated_at
            ) VALUES (
                ?,'stripe','sub-legacy-dunning','local_scout','local',
                'expiring',?,NULL,?,?
            )
            """,
            (workspace_id, now, now, now),
        )

    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        grant = connection.execute(
            """
            SELECT status,ends_at,subject_user_id,scope
            FROM platform_access_grants
            WHERE external_ref='sub-legacy-dunning'
            """
        ).fetchone()
    assert grant["status"] == "revoked"
    assert grant["ends_at"] is not None
    assert grant["subject_user_id"] == user_id
    assert grant["scope"] == "subject"


def test_provider_sync_v2_migration_failure_rolls_back_schema(tmp_path):
    path = tmp_path / "provider-v2-rollback.db"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        apply_migrations(connection, "entitlements", ENTITLEMENT_MIGRATIONS)
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS[:1],
        )

        def deny_trigger(action, _arg1, _arg2, _database, _source):
            if action == sqlite3.SQLITE_CREATE_TRIGGER:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_trigger)
        with pytest.raises(sqlite3.DatabaseError):
            apply_migrations(
                connection,
                "provider-sync",
                PROVIDER_SYNC_MIGRATIONS,
            )
        connection.set_authorizer(None)
        version = current_version(connection, "provider-sync")
        grant_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(platform_access_grants)"
            )
        }
        mapping_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(platform_external_accounts)"
            )
        }

    assert version == 1
    assert "subject_user_id" not in grant_columns
    assert "subject_user_id" not in mapping_columns
