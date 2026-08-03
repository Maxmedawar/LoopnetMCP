"""Raw-body authentication and provider configuration boundaries."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr, ValidationError

from cre_mcp.config import CreConfig

from .provider_helpers import (
    NOW,
    STRIPE_SECRET,
    api_client,
    json_bytes,
    provider_config,
    signature,
    signed_headers,
    stripe_event,
)


def test_provider_secrets_are_secretstr_and_redacted(tmp_path):
    config = provider_config(tmp_path)

    assert isinstance(config.stripe_webhook_secret, SecretStr)
    assert isinstance(config.skool_webhook_secret, SecretStr)
    assert STRIPE_SECRET not in repr(config)
    assert STRIPE_SECRET not in str(config.model_dump())


def test_provider_mappings_parse_to_typed_profiles(tmp_path):
    config = provider_config(tmp_path)

    mapping = config.stripe_price_mappings["price_operator"]
    assert mapping.plan_key == "operator"
    assert mapping.profile.value == "full_operator"
    assert config.skool_tier_mappings[
        "community_1:level_local"
    ].profile.value == "local_scout"


@pytest.mark.parametrize(
    "field,value",
    [
        ("stripe_price_mappings", {"price": {"plan_key": "", "profile": "local_scout"}}),
        ("stripe_price_mappings", {"price": {"plan_key": "local", "profile": "root"}}),
        ("skool_tier_mappings", {"missing-delimiter": {"plan_key": "local", "profile": "local_scout"}}),
    ],
)
def test_invalid_mapping_configuration_fails_closed(tmp_path, field, value):
    with pytest.raises(ValidationError):
        provider_config(tmp_path, **{field: value})


def test_signature_verifier_uses_exact_raw_bytes_and_returns_timestamp():
    from cre_mcp.platform.providers.core import verify_hmac_signature

    body = b'{ "id" : "evt_exact", "amount" : 1 }\n'
    header = signature(STRIPE_SECRET, body, int(NOW.timestamp()))

    assert verify_hmac_signature(
        body,
        header,
        SecretStr(STRIPE_SECRET),
        now=NOW,
    ) == int(NOW.timestamp())
    with pytest.raises(ValueError, match="signature"):
        verify_hmac_signature(
            body.replace(b"1", b"2"),
            header,
            SecretStr(STRIPE_SECRET),
            now=NOW,
        )


def test_signature_verifier_checks_all_v1_values_with_compare_digest(monkeypatch):
    import cre_mcp.platform.providers.core as core

    body = b"{}"
    good = signature(STRIPE_SECRET, body, int(NOW.timestamp())).split("v1=", 1)[1]
    calls: list[tuple[str, str]] = []
    original = hmac.compare_digest

    def tracked(left, right):
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(core.hmac, "compare_digest", tracked)
    header = f"v1={'0' * 64},t={int(NOW.timestamp())},v1={good}"

    assert core.verify_hmac_signature(
        body,
        header,
        SecretStr(STRIPE_SECRET),
        now=NOW,
    ) == int(NOW.timestamp())
    assert len(calls) == 2


def test_signature_verifier_rejects_non_ascii_numeric_digest():
    from cre_mcp.platform.providers.core import (
        WebhookSignatureError,
        verify_hmac_signature,
    )

    header = f"t={int(NOW.timestamp())},v1={'١' * 64}"

    with pytest.raises(WebhookSignatureError, match="signature"):
        verify_hmac_signature(
            b"{}",
            header,
            SecretStr(STRIPE_SECRET),
            now=NOW,
        )


@pytest.mark.parametrize(
    "header",
    [
        "",
        "v1=" + "a" * 64,
        "t=not-an-int,v1=" + "a" * 64,
        "t=+1,v1=" + "a" * 64,
        "t=1",
        "t=1,v1=short",
        "t=1,v0=" + "a" * 64,
        "t=1,t=2,v1=" + "a" * 64,
        "t=" + "9" * 1000 + ",v1=" + "a" * 64,
    ],
)
def test_malformed_signature_headers_are_rejected(header):
    from cre_mcp.platform.providers.core import verify_hmac_signature

    with pytest.raises(ValueError):
        verify_hmac_signature(
            b"{}",
            header,
            SecretStr(STRIPE_SECRET),
            now=NOW,
        )


@pytest.mark.parametrize("delta", [-301, 301])
def test_signature_timestamp_outside_tolerance_is_rejected(delta):
    from cre_mcp.platform.providers.core import verify_hmac_signature

    timestamp = int((NOW + timedelta(seconds=delta)).timestamp())
    with pytest.raises(ValueError, match="timestamp"):
        verify_hmac_signature(
            b"{}",
            signature(STRIPE_SECRET, b"{}", timestamp),
            SecretStr(STRIPE_SECRET),
            now=NOW,
        )


@pytest.mark.parametrize("delta", [-300, 300])
def test_signature_timestamp_boundary_is_inclusive(delta):
    from cre_mcp.platform.providers.core import verify_hmac_signature

    timestamp = int((NOW + timedelta(seconds=delta)).timestamp())
    assert verify_hmac_signature(
        b"{}",
        signature(STRIPE_SECRET, b"{}", timestamp),
        SecretStr(STRIPE_SECRET),
        now=NOW,
    ) == timestamp


async def test_unconfigured_webhook_route_is_inert_404(tmp_path):
    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        stripe_webhook_secret=None,
    )
    body = b"not-json-and-not-signed"

    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "provider_not_configured"
    assert body.decode() not in response.text


async def test_webhook_requires_no_oauth_bearer(tmp_path):
    config = provider_config(tmp_path)
    event = stripe_event("evt_no_bearer", customer="unknown")
    body = json_bytes(event)

    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body),
        )

    assert response.status_code == 202
    assert response.json()["outcome"] in {"quarantined", "unmapped"}


async def test_altered_body_and_wrong_secret_are_rejected(tmp_path):
    config = provider_config(tmp_path)
    body = json_bytes(stripe_event("evt_tampered"))
    good_headers = signed_headers("stripe", body)
    wrong_headers = signed_headers("stripe", body, secret="wrong-secret")

    async with api_client(config) as client:
        altered = await client.post(
            "/v1/webhooks/stripe",
            content=body + b" ",
            headers=good_headers,
        )
        wrong = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=wrong_headers,
        )

    assert altered.status_code == 400
    assert wrong.status_code == 400
    assert altered.json()["error"]["code"] == "invalid_webhook_signature"
    assert wrong.json()["error"]["code"] == "invalid_webhook_signature"


async def test_multiple_stripe_v1_signatures_accept_any_valid_digest(tmp_path):
    config = provider_config(tmp_path)
    body = json_bytes(stripe_event("evt_multi_sig", customer="unknown"))
    good = signature(STRIPE_SECRET, body)
    timestamp = good.split(",", 1)[0]
    digest = good.rsplit("=", 1)[1]
    header = f"{timestamp},v1={'f' * 64},v1={digest.upper()}"

    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers(
                "stripe",
                body,
                signature_value=header,
            ),
        )

    assert response.status_code == 202


async def test_body_size_cap_is_enforced_before_hmac(tmp_path, monkeypatch):
    import cre_mcp.platform.providers.core as core

    config = provider_config(tmp_path, provider_webhook_max_body_bytes=32)
    body = b"{" + b"x" * 64 + b"}"
    headers = {
        **signed_headers("stripe", body),
        "content-length": str(len(body)),
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("HMAC must not run for an oversized body")

    monkeypatch.setattr(core.hmac, "new", forbidden)
    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=headers,
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "webhook_body_too_large"


async def test_signature_errors_never_echo_secret_or_digest(tmp_path):
    config = provider_config(tmp_path)
    body = b"{}"
    digest = hashlib.sha256(b"unique-digest").hexdigest()

    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers={
                "stripe-signature": (
                    f"t={int(datetime.now(UTC).timestamp())},v1={digest}"
                )
            },
        )

    text = response.text
    assert response.status_code == 400
    assert STRIPE_SECRET not in text
    assert digest not in text


async def test_chunked_body_stops_reading_immediately_above_cap(tmp_path):
    from starlette.requests import Request

    from cre_mcp.platform.api import PlatformApi

    config = provider_config(tmp_path, provider_webhook_max_body_bytes=32)
    chunks = [
        b"a" * 20,
        b"b" * 20,
        b"unread-unauthenticated-tail" * 128,
    ]
    reads: list[bytes] = []

    async def receive():
        index = len(reads)
        chunk = chunks[index]
        reads.append(chunk)
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
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
            "headers": [(b"stripe-signature", b"not-evaluated")],
            "client": ("127.0.0.1", 50000),
            "server": ("provider.test", 80),
        },
        receive,
    )

    response = await PlatformApi(config).stripe_webhook(request)

    assert response.status_code == 413
    assert reads == chunks[:2]
