"""OAuth session-store tests: client registry, PKCE code flow, sessions,
refresh rotation with replay detection, and revocation."""

import base64
import sqlite3
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from cre_mcp.access.context import TenantContext
from cre_mcp.access.profiles import Profile
from cre_mcp.platform.auth import AuthenticatedSession, OAuthSessionStore

REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def make_store(tmp_path) -> OAuthSessionStore:
    path = tmp_path / "platform.db"
    store = OAuthSessionStore(path)
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO platform_workspaces(
                public_id, name, created_at, updated_at
            ) VALUES (?, ?, ?, ?)""",
            ("ws-1", "Test Workspace", now, now),
        )
    return store


def register(store: OAuthSessionStore, scopes=("deals:read", "deals:write")):
    return store.register_client("ws-1", "Claude Desktop", (REDIRECT,), scopes)


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# --- schema + client registry -------------------------------------------------


def test_store_initializes_schema_and_round_trips_a_client(tmp_path):
    store = make_store(tmp_path)
    created = register(store)

    fetched = OAuthSessionStore(tmp_path / "platform.db").get_client(created.client_id)

    assert fetched is not None
    assert fetched.client_id.startswith("mcr_client_")
    assert fetched.workspace_id == "ws-1"
    assert fetched.redirect_uris == (REDIRECT,)
    assert fetched.scopes == ("deals:read", "deals:write")
    assert fetched.active is True
    assert store.get_client("mcr_client_unknown") is None


def test_register_client_rejects_bad_redirect_uris(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="redirect"):
        store.register_client("ws-1", "No URIs", (), ("deals:read",))
    with pytest.raises(ValueError, match="fragment"):
        store.register_client(
            "ws-1", "Fragment", ("https://claude.ai/cb#frag",), ("deals:read",)
        )
    with pytest.raises(ValueError, match="HTTPS"):
        store.register_client(
            "ws-1", "Plain HTTP", ("http://claude.ai/cb",), ("deals:read",)
        )


# --- session issuance + access validation ------------------------------------


def test_issue_session_returns_tokens_that_validate(tmp_path):
    store = make_store(tmp_path)
    client = register(store)

    tokens = store.issue_session(
        "ws-1",
        "user-7",
        client.client_id,
        Profile.FULL_OPERATOR,
        plan="pro",
        territories=("TX", "OK"),
        scopes=("deals:read",),
    )

    assert tokens.access_token.startswith("mcr_at_")
    assert tokens.refresh_token.startswith("mcr_rt_")
    assert tokens.access_expires_at < tokens.refresh_expires_at

    session = store.validate_access(tokens.access_token)
    assert isinstance(session, AuthenticatedSession)
    assert session.session_id == tokens.session_id
    assert session.workspace_id == "ws-1"
    assert session.user_id == "user-7"
    assert session.client_id == client.client_id
    assert session.profile is Profile.FULL_OPERATOR
    assert session.plan == "pro"
    assert session.territories == ("TX", "OK")
    assert session.scopes == ("deals:read",)
    assert session.audience == "medawarcre-mcp"


def test_issue_session_rejects_unknown_client_and_excess_scopes(tmp_path):
    store = make_store(tmp_path)
    client = register(store, scopes=("deals:read",))

    with pytest.raises(ValueError, match="client"):
        store.issue_session("ws-1", "user-7", "mcr_client_missing", Profile.JV_PARTNER)
    with pytest.raises(ValueError, match="client"):
        store.issue_session("ws-2", "user-7", client.client_id, Profile.JV_PARTNER)
    with pytest.raises(ValueError, match="scope"):
        store.issue_session(
            "ws-1",
            "user-7",
            client.client_id,
            Profile.JV_PARTNER,
            scopes=("deals:write",),
        )


def test_validate_access_rejects_unknown_and_expired_tokens(tmp_path):
    store = make_store(tmp_path)
    client = register(store)

    assert store.validate_access("mcr_at_not_a_real_token") is None

    expired = store.issue_session(
        "ws-1",
        "user-7",
        client.client_id,
        Profile.LOCAL_SCOUT,
        access_ttl=timedelta(seconds=-1),
    )
    assert store.validate_access(expired.access_token) is None


def test_context_for_bridges_a_session_into_tenant_context(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    tokens = store.issue_session(
        "ws-1",
        "user-7",
        client.client_id,
        Profile.JV_PARTNER,
        plan="pro",
        territories=("TX",),
    )

    context = store.context_for(tokens.access_token)

    assert isinstance(context, TenantContext)
    assert context.workspace_id == "ws-1"
    assert context.profile is Profile.JV_PARTNER
    assert context.plan == "pro"
    assert context.territories == ("TX",)
    assert context.trusted is False
    assert store.context_for("mcr_at_bogus") is None


# --- authorization-code flow (PKCE S256) -------------------------------------


def test_auth_code_exchange_issues_a_working_session(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    verifier = "wallaby-verifier-string-of-sufficient-length"

    code = store.create_auth_code(
        "ws-1",
        "user-7",
        client.client_id,
        REDIRECT,
        challenge_for(verifier),
        profile=Profile.NATIONAL_SCOUT,
        plan="pro",
        territories=("TX",),
        scopes=("deals:read",),
    )
    assert code.startswith("mcr_code_")

    tokens = store.exchange_code(code, client.client_id, REDIRECT, verifier)
    session = store.validate_access(tokens.access_token)

    assert session is not None
    assert session.user_id == "user-7"
    assert session.profile is Profile.NATIONAL_SCOUT
    assert session.plan == "pro"
    assert session.territories == ("TX",)
    assert session.scopes == ("deals:read",)


def test_create_auth_code_rejects_unregistered_redirect(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    with pytest.raises(ValueError, match="redirect"):
        store.create_auth_code(
            "ws-1",
            "user-7",
            client.client_id,
            "https://evil.example/callback",
            challenge_for("verifier"),
            profile=Profile.LOCAL_SCOUT,
        )


def test_create_auth_code_requires_a_pkce_challenge(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    with pytest.raises(ValueError, match="challenge"):
        store.create_auth_code(
            "ws-1",
            "user-7",
            client.client_id,
            REDIRECT,
            "   ",
            profile=Profile.LOCAL_SCOUT,
        )


def test_exchange_rejects_a_wrong_pkce_verifier(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    code = store.create_auth_code(
        "ws-1",
        "user-7",
        client.client_id,
        REDIRECT,
        challenge_for("right-verifier"),
        profile=Profile.LOCAL_SCOUT,
    )
    with pytest.raises(ValueError, match="PKCE"):
        store.exchange_code(code, client.client_id, REDIRECT, "wrong-verifier")


def test_exchange_rejects_a_reused_code(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    verifier = "single-use-verifier"
    code = store.create_auth_code(
        "ws-1",
        "user-7",
        client.client_id,
        REDIRECT,
        challenge_for(verifier),
        profile=Profile.LOCAL_SCOUT,
    )

    store.exchange_code(code, client.client_id, REDIRECT, verifier)

    with pytest.raises(ValueError, match="code"):
        store.exchange_code(code, client.client_id, REDIRECT, verifier)


def test_exchange_rejects_an_expired_code(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    verifier = "expired-verifier"
    code = store.create_auth_code(
        "ws-1",
        "user-7",
        client.client_id,
        REDIRECT,
        challenge_for(verifier),
        profile=Profile.LOCAL_SCOUT,
        ttl=timedelta(seconds=-1),
    )
    with pytest.raises(ValueError, match="code"):
        store.exchange_code(code, client.client_id, REDIRECT, verifier)


def test_exchange_rejects_a_mismatched_client_or_redirect(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    other = store.register_client(
        "ws-1", "Other Client", ("https://other.example/cb",), ("deals:read",)
    )
    verifier = "mismatch-verifier"
    code = store.create_auth_code(
        "ws-1",
        "user-7",
        client.client_id,
        REDIRECT,
        challenge_for(verifier),
        profile=Profile.LOCAL_SCOUT,
    )
    with pytest.raises(ValueError, match="client"):
        store.exchange_code(code, other.client_id, REDIRECT, verifier)
    with pytest.raises(ValueError, match="client"):
        store.exchange_code(
            code, client.client_id, "https://other.example/cb", verifier
        )


# --- refresh rotation + replay detection -------------------------------------


def test_refresh_rotates_tokens_and_retires_the_old_pair(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    first = store.issue_session("ws-1", "user-7", client.client_id, Profile.FULL_OPERATOR)

    second = store.refresh_session(first.refresh_token)

    assert second is not None
    assert second.session_id == first.session_id
    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token
    assert store.validate_access(second.access_token) is not None
    assert store.validate_access(first.access_token) is None


def test_refresh_replay_compromises_the_whole_family(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    first = store.issue_session("ws-1", "user-7", client.client_id, Profile.FULL_OPERATOR)
    second = store.refresh_session(first.refresh_token)
    assert second is not None

    # An attacker replays the already-rotated refresh token.
    assert store.refresh_session(first.refresh_token) is None

    # The legitimate holder's tokens are dead too: the family is burned.
    assert store.refresh_session(second.refresh_token) is None
    assert store.validate_access(second.access_token) is None


def test_refresh_rejects_unknown_and_expired_tokens(tmp_path):
    store = make_store(tmp_path)
    client = register(store)

    assert store.refresh_session("mcr_rt_not_a_real_token") is None

    expired = store.issue_session(
        "ws-1",
        "user-7",
        client.client_id,
        Profile.LOCAL_SCOUT,
        refresh_ttl=timedelta(seconds=-1),
    )
    assert store.refresh_session(expired.refresh_token) is None


# --- revocation ---------------------------------------------------------------


def test_revoke_session_kills_access_and_refresh(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    tokens = store.issue_session("ws-1", "user-7", client.client_id, Profile.FULL_OPERATOR)

    assert store.revoke_session(tokens.session_id) is True
    assert store.validate_access(tokens.access_token) is None
    assert store.refresh_session(tokens.refresh_token) is None
    assert store.revoke_session("mcr_sess_unknown") is False


def test_register_client_rejects_unknown_workspace(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="workspace"):
        store.register_client(
            "ws-invented", "Unknown Tenant", (REDIRECT,), ("deals:read",)
        )
