"""Clerk human identity, opaque browser sessions, and pending OAuth requests.

Clerk proves the person. This module deliberately does not accept workspace,
profile, plan, territory, entitlement, or quota authority from the browser.
Those facts stay server-owned and are resolved from live platform state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from cre_mcp.config import CreConfig
from cre_mcp.platform.schema import create_schema


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _secret(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class VerifiedHumanIdentity:
    provider: str
    subject: str
    email: str
    display_name: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.provider, self.subject, self.email, self.display_name)
        ):
            raise ValueError("verified human identity fields cannot be blank")


class HumanIdentityVerifier(Protocol):
    async def verify_bearer(self, token: str) -> VerifiedHumanIdentity | None:
        """Verify one short-lived provider bearer token."""


class FakeHumanIdentityVerifier:
    """Explicit deterministic verifier used only when injected by tests."""

    def __init__(self, identities: Mapping[str, VerifiedHumanIdentity]) -> None:
        self._identities = dict(identities)

    async def verify_bearer(self, token: str) -> VerifiedHumanIdentity | None:
        return self._identities.get(token)


class _BearerRequest:
    def __init__(self, token: str) -> None:
        self._headers = {"Authorization": f"Bearer {token}"}

    @property
    def headers(self) -> Mapping[str, str]:
        return self._headers


class ClerkHumanIdentityVerifier:
    """Verify Clerk session JWTs through Clerk's official Python SDK."""

    def __init__(self, config: CreConfig) -> None:
        if config.clerk_secret_key is None:
            raise ValueError("Clerk secret key is required")
        if not config.clerk_authorized_parties:
            raise ValueError("at least one Clerk authorized party is required")
        self.secret_key = config.clerk_secret_key.get_secret_value()
        self.authorized_parties = list(config.clerk_authorized_parties)
        self.issuer = config.clerk_issuer

    async def verify_bearer(self, token: str) -> VerifiedHumanIdentity | None:
        normalized = token.strip()
        if not normalized:
            return None
        try:
            from clerk_backend_api import Clerk
            from clerk_backend_api.security import AuthenticateRequestOptions

            async with Clerk(bearer_auth=self.secret_key) as clerk:
                state = await clerk.authenticate_request_async(
                    _BearerRequest(normalized),
                    AuthenticateRequestOptions(
                        secret_key=self.secret_key,
                        authorized_parties=self.authorized_parties,
                        accepts_token=["session_token"],
                    ),
                )
                payload = state.payload or {}
                subject = payload.get("sub")
                issuer = payload.get("iss")
                if not state.is_signed_in or not isinstance(subject, str):
                    return None
                if self.issuer is not None and not (
                    isinstance(issuer, str)
                    and hmac.compare_digest(issuer, self.issuer)
                ):
                    return None
                user = await clerk.users.get_async(user_id=subject)
        except Exception:
            # Identity provider failures are an authentication failure, never a
            # reason to accept an unverified browser identity.
            return None
        if user.banned or user.locked:
            return None
        primary = next(
            (
                email.email_address
                for email in user.email_addresses
                if email.id == user.primary_email_address_id
            ),
            None,
        )
        if not primary:
            return None
        name = " ".join(
            value.strip()
            for value in (user.first_name, user.last_name)
            if isinstance(value, str) and value.strip()
        )
        if not name:
            name = user.username or primary.split("@", 1)[0]
        return VerifiedHumanIdentity("clerk", subject, primary, name)


class _SqliteStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            create_schema(connection)
            with connection:
                yield connection
        finally:
            connection.close()


def _create_connection_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS platform_human_identities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            subject_hash TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(provider,subject_hash),
            UNIQUE(provider,user_id),
            FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_platform_human_identities_user
            ON platform_human_identities(user_id);

        CREATE TABLE IF NOT EXISTS platform_browser_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            csrf_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_platform_browser_sessions_user
            ON platform_browser_sessions(user_id,revoked_at,expires_at);

        CREATE TABLE IF NOT EXISTS platform_oauth_authorization_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_hash TEXT NOT NULL UNIQUE,
            client_id TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            state TEXT NOT NULL,
            scopes TEXT NOT NULL,
            code_challenge TEXT NOT NULL,
            code_challenge_method TEXT NOT NULL,
            audience TEXT NOT NULL,
            resource TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(client_id)
                REFERENCES platform_oauth_clients(client_id) ON DELETE CASCADE,
            CHECK(code_challenge_method='S256')
        );
        """
    )


class HumanIdentityStore(_SqliteStore):
    def __init__(self, db_path: str | Path) -> None:
        super().__init__(db_path)
        with self._connect() as connection:
            _create_connection_tables(connection)

    def resolve_or_bind(self, identity: VerifiedHumanIdentity) -> int:
        provider = identity.provider.strip().casefold()
        subject_hash = _digest(identity.subject)
        email = identity.email.strip().casefold()
        now = _iso(_now())
        with self._connect() as connection:
            _create_connection_tables(connection)
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT user_id FROM platform_human_identities
                WHERE provider=? AND subject_hash=?
                """,
                (provider, subject_hash),
            ).fetchone()
            if existing is not None:
                return int(existing["user_id"])
            user = connection.execute(
                "SELECT id FROM platform_users WHERE lower(email)=?",
                (email,),
            ).fetchone()
            if user is None:
                raise ValueError("verified identity is not preprovisioned")
            user_id = int(user["id"])
            linked = connection.execute(
                """
                SELECT 1 FROM platform_human_identities
                WHERE provider=? AND user_id=?
                """,
                (provider, user_id),
            ).fetchone()
            if linked is not None:
                raise ValueError("platform user is already linked to another identity")
            connection.execute(
                """
                INSERT INTO platform_human_identities
                    (provider,subject_hash,user_id,created_at,updated_at)
                VALUES (?,?,?,?,?)
                """,
                (provider, subject_hash, user_id, now, now),
            )
            return user_id


@dataclass(frozen=True)
class IssuedBrowserSession:
    token: str
    csrf_token: str
    user_id: int
    expires_at: datetime


@dataclass(frozen=True)
class BrowserSession:
    user_id: int
    expires_at: datetime


class BrowserSessionStore(_SqliteStore):
    def __init__(
        self,
        db_path: str | Path,
        *,
        ttl: timedelta = timedelta(minutes=30),
        global_limit: int = 10000,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("browser session TTL must be positive")
        if global_limit < 1:
            raise ValueError("browser session global limit must be positive")
        super().__init__(db_path)
        self.ttl = ttl
        self.global_limit = global_limit
        with self._connect() as connection:
            _create_connection_tables(connection)

    def issue(self, user_id: int) -> IssuedBrowserSession:
        token = _secret("mcr_browser_")
        csrf = _secret("mcr_csrf_")
        now = _now()
        expires = now + self.ttl
        with self._connect() as connection:
            _create_connection_tables(connection)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM platform_browser_sessions
                WHERE expires_at<=? OR revoked_at IS NOT NULL OR user_id=?
                """,
                (_iso(now), user_id),
            )
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM platform_browser_sessions"
                ).fetchone()[0]
            )
            if count >= self.global_limit:
                raise ValueError("browser session capacity reached")
            connection.execute(
                """
                INSERT INTO platform_browser_sessions
                    (token_hash,user_id,csrf_hash,expires_at,revoked_at,
                     created_at,updated_at)
                VALUES (?,?,?,?,NULL,?,?)
                """,
                (_digest(token), user_id, _digest(csrf), _iso(expires), _iso(now), _iso(now)),
            )
        return IssuedBrowserSession(token, csrf, user_id, expires)

    def validate(self, token: str) -> BrowserSession | None:
        with self._connect() as connection:
            _create_connection_tables(connection)
            row = connection.execute(
                """
                SELECT user_id,expires_at FROM platform_browser_sessions
                WHERE token_hash=? AND revoked_at IS NULL
                """,
                (_digest(token),),
            ).fetchone()
        if row is None:
            return None
        expires = _parse(str(row["expires_at"]))
        if expires <= _now():
            return None
        return BrowserSession(int(row["user_id"]), expires)

    def validate_csrf(self, token: str, csrf_token: str) -> bool:
        if self.validate(token) is None:
            return False
        with self._connect() as connection:
            row = connection.execute(
                "SELECT csrf_hash FROM platform_browser_sessions WHERE token_hash=?",
                (_digest(token),),
            ).fetchone()
        return row is not None and hmac.compare_digest(
            str(row["csrf_hash"]), _digest(csrf_token)
        )

    def revoke(self, token: str) -> bool:
        now = _iso(_now())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE platform_browser_sessions SET revoked_at=?,updated_at=?
                WHERE token_hash=? AND revoked_at IS NULL
                """,
                (now, now, _digest(token)),
            )
        return cursor.rowcount == 1


@dataclass(frozen=True)
class PendingAuthorization:
    client_id: str
    redirect_uri: str
    state: str
    scopes: tuple[str, ...]
    code_challenge: str
    code_challenge_method: str
    audience: str
    resource: str


class PendingAuthorizationStore(_SqliteStore):
    def __init__(
        self,
        db_path: str | Path,
        *,
        per_client_limit: int = 32,
        global_limit: int = 1024,
    ) -> None:
        if per_client_limit < 1 or global_limit < 1:
            raise ValueError("pending authorization limits must be positive")
        super().__init__(db_path)
        self.per_client_limit = per_client_limit
        self.global_limit = global_limit
        with self._connect() as connection:
            _create_connection_tables(connection)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> PendingAuthorization:
        return PendingAuthorization(
            client_id=str(row["client_id"]),
            redirect_uri=str(row["redirect_uri"]),
            state=str(row["state"]),
            scopes=tuple(json.loads(str(row["scopes"]))),
            code_challenge=str(row["code_challenge"]),
            code_challenge_method=str(row["code_challenge_method"]),
            audience=str(row["audience"]),
            resource=str(row["resource"]),
        )

    def issue(self, authorization: PendingAuthorization) -> str:
        handle = _secret("mcr_req_")
        now = _now()
        with self._connect() as connection:
            _create_connection_tables(connection)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM platform_oauth_authorization_requests
                WHERE expires_at<=?
                """,
                (_iso(now),),
            )
            global_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM platform_oauth_authorization_requests
                    WHERE consumed_at IS NULL
                    """
                ).fetchone()[0]
            )
            client_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM platform_oauth_authorization_requests
                    WHERE client_id=? AND consumed_at IS NULL
                    """,
                    (authorization.client_id,),
                ).fetchone()[0]
            )
            if (
                global_count >= self.global_limit
                or client_count >= self.per_client_limit
            ):
                raise ValueError("pending authorization capacity reached")
            connection.execute(
                """
                INSERT INTO platform_oauth_authorization_requests
                    (request_hash,client_id,redirect_uri,state,scopes,
                     code_challenge,code_challenge_method,audience,resource,
                     expires_at,consumed_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?)
                """,
                (
                    _digest(handle),
                    authorization.client_id,
                    authorization.redirect_uri,
                    authorization.state,
                    json.dumps(authorization.scopes),
                    authorization.code_challenge,
                    authorization.code_challenge_method,
                    authorization.audience,
                    authorization.resource,
                    _iso(now + timedelta(minutes=10)),
                    _iso(now),
                ),
            )
        return handle

    def get(self, handle: str) -> PendingAuthorization | None:
        now = _now()
        with self._connect() as connection:
            _create_connection_tables(connection)
            connection.execute(
                """
                DELETE FROM platform_oauth_authorization_requests
                WHERE expires_at<=?
                """,
                (_iso(now),),
            )
            row = connection.execute(
                """
                SELECT * FROM platform_oauth_authorization_requests
                WHERE request_hash=? AND consumed_at IS NULL
                """,
                (_digest(handle),),
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def consume(self, handle: str) -> PendingAuthorization | None:
        now = _now()
        with self._connect() as connection:
            _create_connection_tables(connection)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM platform_oauth_authorization_requests
                WHERE expires_at<=?
                """,
                (_iso(now),),
            )
            row = connection.execute(
                """
                SELECT * FROM platform_oauth_authorization_requests
                WHERE request_hash=? AND consumed_at IS NULL
                """,
                (_digest(handle),),
            ).fetchone()
            if row is None or _parse(str(row["expires_at"])) <= now:
                return None
            updated = connection.execute(
                """
                UPDATE platform_oauth_authorization_requests SET consumed_at=?
                WHERE id=? AND consumed_at IS NULL
                """,
                (_iso(now), row["id"]),
            )
            if updated.rowcount != 1:
                return None
            return self._from_row(row)

    def restore(self, handle: str) -> bool:
        """Restore a consumed request after authorization-code creation fails."""
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE platform_oauth_authorization_requests
                SET consumed_at=NULL
                WHERE request_hash=? AND consumed_at IS NOT NULL AND expires_at>?
                """,
                (_digest(handle), _iso(now)),
            )
        return updated.rowcount == 1


__all__ = [
    "BrowserSession",
    "BrowserSessionStore",
    "ClerkHumanIdentityVerifier",
    "FakeHumanIdentityVerifier",
    "HumanIdentityStore",
    "HumanIdentityVerifier",
    "IssuedBrowserSession",
    "PendingAuthorization",
    "PendingAuthorizationStore",
    "VerifiedHumanIdentity",
]
