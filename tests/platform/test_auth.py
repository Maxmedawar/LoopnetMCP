"""OAuth storage tests for unbound clients and identity-linked token families."""

from __future__ import annotations

import base64
import hashlib
import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from cre_mcp.platform.auth import AuthenticatedSession, OAuthSessionStore

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 43


def make_store(tmp_path, **kwargs) -> OAuthSessionStore:
    path = tmp_path / "platform.db"
    store = OAuthSessionStore(path, **kwargs)
    now = "2026-07-28T12:00:00+00:00"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO platform_workspaces(public_id,name,created_at,updated_at)
            VALUES ('ws-1','Test Workspace',?,?)
            """,
            (now, now),
        )
        workspace_id = connection.execute(
            "SELECT id FROM platform_workspaces WHERE public_id='ws-1'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO platform_users(id,email,name,created_at,updated_at)
            VALUES (7,'user@example.test','User',?,?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_memberships
                (workspace_id,user_id,role,created_at,updated_at)
            VALUES (?,7,'owner',?,?)
            """,
            (workspace_id, now, now),
        )
    return store


def register(
    store: OAuthSessionStore,
    scopes: tuple[str, ...] = ("deals:read", "deals:write"),
):
    return store.register_client("Claude Desktop", (REDIRECT,), scopes)


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def test_store_initializes_schema_and_round_trips_an_unbound_client(tmp_path):
    store = make_store(tmp_path)
    created = register(store)

    fetched = OAuthSessionStore(tmp_path / "platform.db").get_client(created.client_id)

    assert fetched is not None
    assert fetched.client_id.startswith("mcr_client_")
    assert not hasattr(fetched, "workspace_id")
    assert fetched.redirect_uris == (REDIRECT,)
    assert fetched.scopes == ("deals:read", "deals:write")
    assert fetched.active is True
    assert store.get_client("mcr_client_unknown") is None


def test_register_client_rejects_bad_redirect_uris(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="redirect"):
        store.register_client("No URIs", (), ("deals:read",))
    with pytest.raises(ValueError, match="fragment"):
        store.register_client(
            "Fragment", ("https://claude.ai/cb#frag",), ("deals:read",)
        )
    with pytest.raises(ValueError, match="HTTPS"):
        store.register_client(
            "Plain HTTP", ("http://claude.ai/cb",), ("deals:read",)
        )


def test_issue_session_returns_credential_facts_without_authority_snapshots(tmp_path):
    store = make_store(tmp_path)
    client = register(store)

    tokens = store.issue_session(
        "ws-1", 7, client.client_id, scopes=("deals:read",)
    )
    session = store.validate_access(tokens.access_token)

    assert tokens.access_token.startswith("mcr_at_")
    assert tokens.refresh_token.startswith("mcr_rt_")
    assert tokens.access_expires_at < tokens.refresh_expires_at
    assert isinstance(session, AuthenticatedSession)
    assert session.session_id == tokens.session_id
    assert session.workspace_id == "ws-1"
    assert session.user_id == 7
    assert session.client_id == client.client_id
    assert session.scopes == ("deals:read",)
    assert {"profile", "plan", "territories"}.isdisjoint(vars(session))


def test_issue_session_rejects_unknown_client_identity_and_excess_scopes(tmp_path):
    store = make_store(tmp_path)
    client = register(store, scopes=("deals:read",))

    with pytest.raises(ValueError, match="client"):
        store.issue_session("ws-1", 7, "mcr_client_missing")
    with pytest.raises(ValueError, match="identity|membership"):
        store.issue_session("ws-1", 8, client.client_id)
    with pytest.raises(ValueError, match="scope"):
        store.issue_session(
            "ws-1", 7, client.client_id, scopes=("deals:write",)
        )


def test_validate_access_rejects_unknown_expired_and_misdirected_tokens(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    assert store.validate_access("mcr_at_not_a_real_token") is None

    expired = store.issue_session(
        "ws-1",
        7,
        client.client_id,
        access_ttl=timedelta(seconds=-1),
    )
    assert store.validate_access(expired.access_token) is None

    wrong_target = store.issue_session(
        "ws-1",
        7,
        client.client_id,
        audience="other-service",
        resource="https://other.example/mcp",
    )
    assert store.validate_access(wrong_target.access_token) is None


def test_auth_code_exchange_issues_a_working_session(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    code = store.create_auth_code(
        "ws-1",
        7,
        client.client_id,
        REDIRECT,
        challenge_for(VERIFIER),
        scopes=("deals:read",),
    )

    tokens = store.exchange_code(code, client.client_id, REDIRECT, VERIFIER)
    session = store.validate_access(tokens.access_token)

    assert code.startswith("mcr_code_")
    assert session is not None
    assert session.user_id == 7
    assert session.scopes == ("deals:read",)


def test_create_auth_code_enforces_exact_redirect_and_s256_challenge(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    with pytest.raises(ValueError, match="redirect"):
        store.create_auth_code(
            "ws-1",
            7,
            client.client_id,
            "https://evil.example/callback",
            challenge_for(VERIFIER),
        )
    with pytest.raises(ValueError, match="challenge"):
        store.create_auth_code(
            "ws-1", 7, client.client_id, REDIRECT, "short"
        )
    with pytest.raises(ValueError, match="S256"):
        store.create_auth_code(
            "ws-1",
            7,
            client.client_id,
            REDIRECT,
            challenge_for(VERIFIER),
            code_challenge_method="plain",
        )


def test_exchange_rejects_wrong_verifier_replay_and_expiry(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    wrong_code = store.create_auth_code(
        "ws-1", 7, client.client_id, REDIRECT, challenge_for(VERIFIER)
    )
    with pytest.raises(ValueError, match="PKCE"):
        store.exchange_code(wrong_code, client.client_id, REDIRECT, "w" * 43)

    single_use = store.create_auth_code(
        "ws-1", 7, client.client_id, REDIRECT, challenge_for(VERIFIER)
    )
    issued = store.exchange_code(single_use, client.client_id, REDIRECT, VERIFIER)
    assert store.validate_access(issued.access_token) is not None
    with pytest.raises(ValueError, match="code"):
        store.exchange_code(single_use, client.client_id, REDIRECT, VERIFIER)
    assert store.validate_access(issued.access_token) is None

    expired = store.create_auth_code(
        "ws-1",
        7,
        client.client_id,
        REDIRECT,
        challenge_for(VERIFIER),
        ttl=timedelta(seconds=-1),
    )
    with pytest.raises(ValueError, match="code"):
        store.exchange_code(expired, client.client_id, REDIRECT, VERIFIER)


def test_exchange_rejects_mismatched_client_or_redirect(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    other = store.register_client(
        "Other Client", ("https://other.example/cb",), ("deals:read",)
    )
    code = store.create_auth_code(
        "ws-1", 7, client.client_id, REDIRECT, challenge_for(VERIFIER)
    )
    with pytest.raises(ValueError, match="client"):
        store.exchange_code(code, other.client_id, REDIRECT, VERIFIER)
    with pytest.raises(ValueError, match="client"):
        store.exchange_code(
            code, client.client_id, "https://other.example/cb", VERIFIER
        )


def test_refresh_rotates_tokens_and_retires_the_old_pair(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    first = store.issue_session("ws-1", 7, client.client_id)

    second = store.refresh_session(
        first.refresh_token,
        client_id=client.client_id,
    )

    assert second is not None
    assert second.session_id == first.session_id
    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token
    assert store.validate_access(second.access_token) is not None
    assert store.validate_access(first.access_token) is None


def test_refresh_replay_compromises_the_whole_family(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    first = store.issue_session("ws-1", 7, client.client_id)
    second = store.refresh_session(
        first.refresh_token,
        client_id=client.client_id,
    )
    assert second is not None

    assert (
        store.refresh_session(
            first.refresh_token,
            client_id=client.client_id,
        )
        is None
    )
    assert (
        store.refresh_session(
            second.refresh_token,
            client_id=client.client_id,
        )
        is None
    )
    assert store.validate_access(second.access_token) is None


def test_refresh_family_deadline_cannot_move_across_rotations(
    tmp_path, monkeypatch
):
    import cre_mcp.platform.auth as auth_module

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(auth_module, "_utc_now", lambda: now)
    store = make_store(
        tmp_path,
        refresh_family_max_age=timedelta(days=90),
    )
    client = register(store)
    current = store.issue_session("ws-1", 7, client.client_id)
    family_deadline = now + timedelta(days=90)

    for elapsed_days in (29, 58, 87):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC) + timedelta(
            days=elapsed_days
        )
        current = store.refresh_session(
            current.refresh_token,
            client_id=client.client_id,
        )
        assert current is not None
        assert current.refresh_expires_at <= family_deadline

    now = family_deadline
    assert (
        store.refresh_session(
            current.refresh_token,
            client_id=client.client_id,
        )
        is None
    )


@pytest.mark.parametrize("mismatch", ["client", "redirect", "verifier"])
def test_spent_code_mismatch_cannot_revoke_legitimate_family(
    tmp_path, mismatch
):
    store = make_store(tmp_path)
    client = register(store)
    other = store.register_client(
        "Other Client",
        ("https://other.example/cb",),
        ("deals:read", "deals:write"),
    )
    code = store.create_auth_code(
        "ws-1", 7, client.client_id, REDIRECT, challenge_for(VERIFIER)
    )
    issued = store.exchange_code(code, client.client_id, REDIRECT, VERIFIER)

    replay_client = other.client_id if mismatch == "client" else client.client_id
    replay_redirect = (
        "https://other.example/cb" if mismatch == "redirect" else REDIRECT
    )
    replay_verifier = "w" * 43 if mismatch == "verifier" else VERIFIER
    with pytest.raises(ValueError, match="code|client|redirect|PKCE"):
        store.exchange_code(
            code,
            replay_client,
            replay_redirect,
            replay_verifier,
        )

    assert store.validate_access(issued.access_token) is not None


def test_spent_refresh_replay_requires_matching_client(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    other = store.register_client(
        "Other Client",
        ("https://other.example/cb",),
        ("deals:read", "deals:write"),
    )
    first = store.issue_session("ws-1", 7, client.client_id)
    second = store.refresh_session(
        first.refresh_token,
        client_id=client.client_id,
    )
    assert second is not None

    assert (
        store.refresh_session(
            first.refresh_token,
            client_id=other.client_id,
        )
        is None
    )
    assert store.validate_access(second.access_token) is not None

    assert (
        store.refresh_session(
            first.refresh_token,
            client_id=client.client_id,
        )
        is None
    )
    assert store.validate_access(second.access_token) is None


def test_refresh_rejects_unknown_expired_and_removed_identity(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    assert (
        store.refresh_session(
            "mcr_rt_not_a_real_token",
            client_id=client.client_id,
        )
        is None
    )

    expired = store.issue_session(
        "ws-1",
        7,
        client.client_id,
        refresh_ttl=timedelta(seconds=-1),
    )
    assert (
        store.refresh_session(
            expired.refresh_token,
            client_id=client.client_id,
        )
        is None
    )

    removed = store.issue_session("ws-1", 7, client.client_id)
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("DELETE FROM platform_memberships")
    assert (
        store.refresh_session(
            removed.refresh_token,
            client_id=client.client_id,
        )
        is None
    )


def test_revoke_session_kills_access_and_refresh(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    tokens = store.issue_session("ws-1", 7, client.client_id)

    assert store.revoke_session(tokens.session_id) is True
    assert store.validate_access(tokens.access_token) is None
    assert (
        store.refresh_session(
            tokens.refresh_token,
            client_id=client.client_id,
        )
        is None
    )
    assert store.revoke_session("mcr_sess_unknown") is False


def test_client_deactivation_invalidates_sessions_and_pending_codes(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    tokens = store.issue_session("ws-1", 7, client.client_id)
    code = store.create_auth_code(
        "ws-1", 7, client.client_id, REDIRECT, challenge_for(VERIFIER)
    )

    assert store.revoke_client(client.client_id) is True
    assert store.get_client(client.client_id).active is False
    assert store.validate_access(tokens.access_token) is None
    assert (
        store.refresh_session(
            tokens.refresh_token,
            client_id=client.client_id,
        )
        is None
    )
    with pytest.raises(ValueError, match="code|client"):
        store.exchange_code(code, client.client_id, REDIRECT, VERIFIER)
    assert store.revoke_client(client.client_id) is False


def test_single_use_code_has_one_winner_under_concurrency(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    code = store.create_auth_code(
        "ws-1", 7, client.client_id, REDIRECT, challenge_for(VERIFIER)
    )
    barrier = Barrier(2)

    def exchange_once():
        barrier.wait()
        try:
            return store.exchange_code(
                code, client.client_id, REDIRECT, VERIFIER
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: exchange_once(), range(2)))

    assert sum(result is not None for result in results) == 1
    winner = next(result for result in results if result is not None)
    assert store.validate_access(winner.access_token) is None


def test_concurrent_refresh_has_no_uncaught_integrity_error_or_duplicate_family(
    tmp_path,
):
    store = make_store(tmp_path)
    client = register(store)
    first = store.issue_session("ws-1", 7, client.client_id)
    barrier = Barrier(2)

    def refresh_once():
        barrier.wait()
        try:
            return store.refresh_session(
                first.refresh_token,
                client_id=client.client_id,
            )
        except Exception as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: refresh_once(), range(2)))

    assert not [result for result in results if isinstance(result, Exception)]
    continuations = [result for result in results if result is not None]
    assert len(continuations) == 1
    with sqlite3.connect(store.db_path) as connection:
        live_families = connection.execute(
            "SELECT COUNT(*) FROM platform_oauth_sessions WHERE revoked_at IS NULL"
        ).fetchone()[0]
        rotated = connection.execute(
            "SELECT COUNT(*) FROM platform_oauth_refresh_history"
        ).fetchone()[0]
    assert live_families == 0
    assert rotated == 1


def test_pkce_contract_explicitly_requires_s256(tmp_path):
    store = make_store(tmp_path)
    client = register(store)
    parameters = inspect.signature(store.create_auth_code).parameters

    assert "code_challenge_method" in parameters
    with pytest.raises(ValueError, match="S256"):
        store.create_auth_code(
            "ws-1",
            7,
            client.client_id,
            REDIRECT,
            challenge_for(VERIFIER),
            code_challenge_method="plain",
            scopes=("deals:read",),
        )
