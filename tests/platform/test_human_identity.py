"""Human identity and browser-session boundaries for the connection flow."""

from __future__ import annotations

import hashlib
import sqlite3
from types import SimpleNamespace

from cre_mcp.config import CreConfig
from cre_mcp.platform.connection import (
    BrowserSessionStore,
    ClerkHumanIdentityVerifier,
    FakeHumanIdentityVerifier,
    HumanIdentityStore,
    VerifiedHumanIdentity,
)
from cre_mcp.platform.repository import PlatformRepository


async def test_verified_clerk_identity_binds_to_preprovisioned_user_without_plain_subject(
    tmp_path,
):
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")
    repository = PlatformRepository(config)
    user = await repository.create_user("buyer@example.test", "Buyer")
    assert user is not None
    identity = VerifiedHumanIdentity(
        provider="clerk",
        subject="user_clerk_secret_subject",
        email="BUYER@example.test",
        display_name="Buyer Updated",
    )

    store = HumanIdentityStore(config.cache_db_path)
    resolved = store.resolve_or_bind(identity)

    assert resolved == user.id
    with sqlite3.connect(config.cache_db_path) as connection:
        row = connection.execute(
            "SELECT provider,subject_hash,user_id FROM platform_human_identities"
        ).fetchone()
    assert row == (
        "clerk",
        hashlib.sha256(identity.subject.encode()).hexdigest(),
        user.id,
    )
    assert identity.subject not in config.cache_db_path.read_bytes().decode(
        "utf-8", errors="ignore"
    )


async def test_unprovisioned_identity_and_second_subject_for_user_fail_closed(tmp_path):
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")
    repository = PlatformRepository(config)
    user = await repository.create_user("buyer@example.test", "Buyer")
    assert user is not None
    store = HumanIdentityStore(config.cache_db_path)
    store.resolve_or_bind(
        VerifiedHumanIdentity("clerk", "subject-one", "buyer@example.test", "Buyer")
    )

    for identity in (
        VerifiedHumanIdentity("clerk", "subject-two", "buyer@example.test", "Buyer"),
        VerifiedHumanIdentity("clerk", "unknown", "missing@example.test", "Missing"),
    ):
        try:
            store.resolve_or_bind(identity)
        except ValueError as exc:
            assert "preprovisioned" in str(exc) or "already linked" in str(exc)
        else:  # pragma: no cover - assertion branch
            raise AssertionError("identity binding must fail closed")


async def test_browser_session_is_opaque_hashed_expiring_and_csrf_protected(tmp_path):
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")
    repository = PlatformRepository(config)
    user = await repository.create_user("buyer@example.test", "Buyer")
    assert user is not None
    sessions = BrowserSessionStore(config.cache_db_path)

    issued = sessions.issue(user.id)
    resolved = sessions.validate(issued.token)

    assert resolved is not None
    assert resolved.user_id == user.id
    assert sessions.validate_csrf(issued.token, issued.csrf_token)
    assert not sessions.validate_csrf(issued.token, "wrong")
    with sqlite3.connect(config.cache_db_path) as connection:
        row = connection.execute(
            "SELECT token_hash,csrf_hash FROM platform_browser_sessions"
        ).fetchone()
    assert row == (
        hashlib.sha256(issued.token.encode()).hexdigest(),
        hashlib.sha256(issued.csrf_token.encode()).hexdigest(),
    )


async def test_browser_sessions_are_one_per_user_and_globally_bounded(tmp_path):
    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "platform.db")
    repository = PlatformRepository(config)
    first_user = await repository.create_user("first@example.test", "First")
    second_user = await repository.create_user("second@example.test", "Second")
    assert first_user is not None and second_user is not None
    sessions = BrowserSessionStore(config.cache_db_path, global_limit=1)

    first = sessions.issue(first_user.id)
    replacement = sessions.issue(first_user.id)

    assert sessions.validate(first.token) is None
    assert sessions.validate(replacement.token) is not None
    with sqlite3.connect(config.cache_db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_browser_sessions"
        ).fetchone()[0] == 1

    try:
        sessions.issue(second_user.id)
    except ValueError as exc:
        assert "capacity" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("browser session capacity must fail closed")


async def test_fake_verifier_is_explicit_and_rejects_unknown_bearer():
    identity = VerifiedHumanIdentity(
        "clerk", "subject", "buyer@example.test", "Buyer"
    )
    verifier = FakeHumanIdentityVerifier({"good": identity})

    assert await verifier.verify_bearer("good") == identity
    assert await verifier.verify_bearer("bad") is None


async def test_clerk_adapter_uses_official_verifier_authorized_party_and_user_record(
    tmp_path, monkeypatch
):
    captured = {}

    class FakeClerk:
        def __init__(self, *, bearer_auth):
            captured["secret"] = bearer_auth
            self.users = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def authenticate_request_async(self, request, options):
            captured["authorization"] = request.headers["Authorization"]
            captured["authorized_parties"] = options.authorized_parties
            captured["accepts_token"] = options.accepts_token
            return SimpleNamespace(
                is_signed_in=True,
                payload={
                    "sub": "user_clerk_1",
                    "iss": "https://clerk.example.test",
                },
            )

        async def get_async(self, *, user_id):
            captured["user_id"] = user_id
            return SimpleNamespace(
                banned=False,
                locked=False,
                primary_email_address_id="email_primary",
                email_addresses=[
                    SimpleNamespace(
                        id="email_primary", email_address="buyer@example.test"
                    )
                ],
                first_name="Ada",
                last_name="Buyer",
                username=None,
            )

    import clerk_backend_api

    monkeypatch.setattr(clerk_backend_api, "Clerk", FakeClerk)
    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        human_identity_provider="clerk",
        clerk_secret_key="clerk-test-key",
        clerk_authorized_parties=("https://connect.example.test",),
        clerk_issuer="https://clerk.example.test",
    )

    identity = await ClerkHumanIdentityVerifier(config).verify_bearer("jwt")

    assert identity == VerifiedHumanIdentity(
        "clerk", "user_clerk_1", "buyer@example.test", "Ada Buyer"
    )
    assert captured == {
        "secret": "clerk-test-key",
        "authorization": "Bearer jwt",
        "authorized_parties": ["https://connect.example.test"],
        "accepts_token": ["session_token"],
        "user_id": "user_clerk_1",
    }


async def test_clerk_adapter_rejects_wrong_issuer(tmp_path, monkeypatch):
    class WrongIssuerClerk:
        def __init__(self, **_kwargs):
            self.users = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def authenticate_request_async(self, _request, _options):
            return SimpleNamespace(
                is_signed_in=True,
                payload={"sub": "user_1", "iss": "https://attacker.example"},
            )

    import clerk_backend_api

    monkeypatch.setattr(clerk_backend_api, "Clerk", WrongIssuerClerk)
    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        clerk_secret_key="clerk-test-key",
        clerk_authorized_parties=("https://connect.example.test",),
        clerk_issuer="https://clerk.example.test",
    )

    assert await ClerkHumanIdentityVerifier(config).verify_bearer("jwt") is None
