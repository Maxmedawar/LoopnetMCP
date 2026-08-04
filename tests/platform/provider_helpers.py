"""Deterministic fixtures for offline provider-sync tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

import httpx

from cre_mcp.config import CreConfig
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository
from tests.hosted_helpers import create_testing_starlette_app

STRIPE_SECRET = "whsec_test_stripe_provider_sync"
SKOOL_SECRET = "relay_test_skool_provider_sync"
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def provider_config(tmp_path, **overrides: Any) -> CreConfig:
    values: dict[str, Any] = {
        "_env_file": None,
        "cache_db_path": tmp_path / "platform.db",
        "stripe_webhook_secret": STRIPE_SECRET,
        "skool_webhook_secret": SKOOL_SECRET,
        "provider_webhook_max_body_bytes": 64 * 1024,
        "stripe_price_mappings": {
            "price_local": {
                "plan_key": "local",
                "profile": "local_scout",
            },
            "price_national": {
                "plan_key": "national",
                "profile": "national_scout",
            },
            "price_operator": {
                "plan_key": "operator",
                "profile": "full_operator",
            },
        },
        "skool_tier_mappings": {
            "community_1:level_local": {
                "plan_key": "local",
                "profile": "local_scout",
            },
            "community_1:level_national": {
                "plan_key": "national",
                "profile": "national_scout",
            },
        },
    }
    values.update(overrides)
    config = CreConfig(**values)
    EntitlementStore(config.cache_db_path)
    return config


def api_client(config: CreConfig, *, app=None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=app
            or create_testing_starlette_app(
                config=config, include_uncertified_deal_routes=True
            )
        ),
        base_url="http://provider.test",
    )


def json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def signature(secret: str, body: bytes, timestamp: int | None = None) -> str:
    timestamp = (
        int(datetime.now(UTC).timestamp())
        if timestamp is None
        else timestamp
    )
    digest = hmac.new(
        secret.encode(),
        str(timestamp).encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def signed_headers(
    provider: str,
    body: bytes,
    *,
    secret: str | None = None,
    timestamp: int | None = None,
    signature_value: str | None = None,
) -> dict[str, str]:
    if provider == "stripe":
        secret = secret or STRIPE_SECRET
        header = "stripe-signature"
    else:
        secret = secret or SKOOL_SECRET
        header = "x-skool-signature"
    return {
        "content-type": "application/json",
        header: signature_value or signature(secret, body, timestamp),
    }


def stripe_event(
    event_id: str,
    *,
    event_type: str = "customer.subscription.updated",
    created: int | None = None,
    object_id: str = "sub_1",
    customer: str = "cus_1",
    status: str = "active",
    prices: tuple[str, ...] = ("price_local",),
    period_end: int | None = None,
    extra_object: dict[str, Any] | None = None,
    extra_envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    object_value: dict[str, Any] = {
        "id": object_id,
        "customer": customer,
        "status": status,
        "items": {
            "data": [
                {"price": {"id": price_id}, "quantity": 1}
                for price_id in prices
            ]
        },
        "current_period_end": period_end,
    }
    object_value.update(extra_object or {})
    result = {
        "id": event_id,
        "type": event_type,
        "created": int(NOW.timestamp()) if created is None else created,
        "livemode": False,
        "data": {"object": object_value},
    }
    result.update(extra_envelope or {})
    return result


def skool_event(
    event_id: str,
    *,
    event_type: str = "member.updated",
    created: int | None = None,
    member_id: str = "member_1",
    community_id: str = "community_1",
    level_id: str = "level_local",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "id": event_id,
        "type": event_type,
        "created": int(NOW.timestamp()) if created is None else created,
        "member": {
            "id": member_id,
            "community": {"id": community_id},
            "level": {"id": level_id},
        },
    }
    result.update(extra or {})
    return result


async def seed_workspace(
    config: CreConfig,
    name: str,
    *,
    stripe_customer: str | None = None,
    skool_member: str | None = None,
):
    repository = PlatformRepository(config.cache_db_path)
    for key in ("local", "national", "operator", "jv"):
        if not any(item.key == key for item in await repository.list_plans()):
            assert await repository.create_plan(key, key.title()) is not None
    workspace = await repository.create_workspace(name)
    assert workspace is not None
    subject = await repository.create_user(
        f"provider-subject-{workspace.id}@example.test",
        f"{name} Provider Subject",
    )
    assert subject is not None
    assert (
        await repository.add_membership(
            workspace.public_id,
            subject.id,
            role="owner",
        )
        is not None
    )
    now = NOW.isoformat()
    mappings = []
    if stripe_customer is not None:
        mappings.append(("stripe", stripe_customer))
    if skool_member is not None:
        mappings.append(("skool", skool_member))
    with sqlite3.connect(config.cache_db_path) as connection:
        for provider, external_id in mappings:
            connection.execute(
                """
                INSERT INTO platform_external_accounts(
                    workspace_id,subject_user_id,provider,external_account_id,
                    metadata,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    workspace.id,
                    subject.id,
                    provider,
                    external_id,
                    "{}",
                    now,
                    now,
                ),
            )
    return workspace


def projection(path) -> dict[str, list[tuple[Any, ...]]]:
    result: dict[str, list[tuple[Any, ...]]] = {}
    with sqlite3.connect(path) as connection:
        for table in (
            "platform_accounts",
            "platform_subscriptions",
            "platform_access_grants",
        ):
            rows = connection.execute(
                f"SELECT * FROM {table} ORDER BY 1"
            ).fetchall()
            result[table] = [tuple(row) for row in rows]
    return result


def provider_events(path) -> list[sqlite3.Row]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT * FROM platform_provider_events ORDER BY id"
        ).fetchall()


def provider_attempts(path) -> list[sqlite3.Row]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT * FROM platform_provider_event_attempts ORDER BY id"
        ).fetchall()
