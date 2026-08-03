"""OAuth client registration and opaque, revocable token-family storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from cre_mcp.platform.migrations import Migration, apply_migrations
from cre_mcp.platform.schema import create_schema

DEFAULT_AUDIENCE = "medawarcre-mcp"
DEFAULT_RESOURCE = "https://mcp.medawarcre.com/mcp"
AUTHORITY_VERSION = 1
DEFAULT_REFRESH_FAMILY_MAX_AGE = timedelta(days=90)

_PKCE_VALUE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_PKCE_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _secret(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def _pkce_matches(challenge: str, verifier: str) -> bool:
    if not _PKCE_VALUE.fullmatch(verifier):
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    actual = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(challenge, actual)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(connection, table):
        return set()
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _create_authoritative_oauth_tables(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_oauth_clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            client_id TEXT NOT NULL UNIQUE,
            redirect_uris TEXT NOT NULL,
            scopes TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK(active IN (0,1))
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_oauth_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code_hash TEXT NOT NULL UNIQUE,
            workspace_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            client_id TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            code_challenge TEXT NOT NULL,
            code_challenge_method TEXT NOT NULL,
            scopes TEXT NOT NULL,
            audience TEXT NOT NULL,
            resource TEXT NOT NULL,
            authority_version INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            session_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id)
                REFERENCES platform_workspaces(public_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE,
            FOREIGN KEY(client_id)
                REFERENCES platform_oauth_clients(client_id) ON DELETE CASCADE,
            FOREIGN KEY(session_id)
                REFERENCES platform_oauth_sessions(session_id) ON DELETE SET NULL,
            CHECK(code_challenge_method='S256')
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_oauth_sessions (
            session_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            client_id TEXT NOT NULL,
            scopes TEXT NOT NULL,
            audience TEXT NOT NULL,
            resource TEXT NOT NULL,
            authority_version INTEGER NOT NULL,
            access_hash TEXT NOT NULL UNIQUE,
            refresh_hash TEXT NOT NULL UNIQUE,
            access_expires_at TEXT NOT NULL,
            refresh_expires_at TEXT NOT NULL,
            refresh_family_expires_at TEXT NOT NULL,
            revoked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id)
                REFERENCES platform_workspaces(public_id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES platform_users(id) ON DELETE CASCADE,
            FOREIGN KEY(client_id)
                REFERENCES platform_oauth_clients(client_id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_platform_oauth_sessions_identity
        ON platform_oauth_sessions(workspace_id, user_id, revoked_at)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_oauth_refresh_history (
            token_hash TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            rotated_at TEXT NOT NULL,
            FOREIGN KEY(session_id)
                REFERENCES platform_oauth_sessions(session_id) ON DELETE CASCADE
        )
        """
    )


def _oauth_authoritative_cutover(connection: sqlite3.Connection) -> None:
    """Drop stale authority snapshots and unbind registered public clients."""
    legacy_client = (
        _table_exists(connection, "platform_oauth_clients")
        and "workspace_id" in _columns(connection, "platform_oauth_clients")
    )

    # Authorization material issued from caller-supplied authority snapshots
    # cannot be upgraded safely. The cutover invalidates all of it.
    connection.execute("DROP TABLE IF EXISTS platform_oauth_refresh_history")
    connection.execute("DROP TABLE IF EXISTS platform_oauth_codes")
    connection.execute("DROP TABLE IF EXISTS platform_oauth_sessions")

    if legacy_client:
        connection.execute(
            "ALTER TABLE platform_oauth_clients RENAME TO platform_oauth_clients_legacy"
        )
        _create_authoritative_oauth_tables(connection)
        connection.execute(
            """
            INSERT INTO platform_oauth_clients
                (id,name,client_id,redirect_uris,scopes,active,created_at,updated_at)
            SELECT id,name,client_id,redirect_uris,scopes,active,created_at,updated_at
            FROM platform_oauth_clients_legacy
            """
        )
        connection.execute("DROP TABLE platform_oauth_clients_legacy")
    else:
        _create_authoritative_oauth_tables(connection)


def _absolute_refresh_family_cutover(connection: sqlite3.Connection) -> None:
    columns = _columns(connection, "platform_oauth_sessions")
    if "refresh_family_expires_at" not in columns:
        connection.execute(
            "ALTER TABLE platform_oauth_sessions "
            "ADD COLUMN refresh_family_expires_at TEXT NOT NULL DEFAULT ''"
        )
    rows = connection.execute(
        """
        SELECT session_id,created_at
        FROM platform_oauth_sessions
        WHERE refresh_family_expires_at=''
        """
    ).fetchall()
    for row in rows:
        created_at = _parse(str(row["created_at"]))
        connection.execute(
            """
            UPDATE platform_oauth_sessions
            SET refresh_family_expires_at=?
            WHERE session_id=?
            """,
            (
                _iso(created_at + DEFAULT_REFRESH_FAMILY_MAX_AGE),
                row["session_id"],
            ),
        )


OAUTH_MIGRATIONS = (
    Migration(
        AUTHORITY_VERSION,
        "authoritative identity-linked OAuth sessions",
        _oauth_authoritative_cutover,
    ),
    Migration(
        2,
        "absolute refresh-token family lifetime",
        _absolute_refresh_family_cutover,
    ),
)


@dataclass(frozen=True)
class ClientRegistration:
    id: int
    name: str
    client_id: str
    redirect_uris: tuple[str, ...]
    scopes: tuple[str, ...]
    active: bool


@dataclass(frozen=True)
class SessionTokens:
    session_id: str
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


@dataclass(frozen=True)
class AuthenticatedSession:
    """Credential facts only. Authorization is deliberately absent."""

    session_id: str
    workspace_id: str
    user_id: int
    client_id: str
    scopes: tuple[str, ...]
    audience: str
    resource: str
    access_expires_at: datetime


class OAuthSessionStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        refresh_family_max_age: timedelta = DEFAULT_REFRESH_FAMILY_MAX_AGE,
    ) -> None:
        if refresh_family_max_age <= timedelta(0):
            raise ValueError("refresh family maximum age must be positive")
        self.db_path = Path(db_path).expanduser()
        self.refresh_family_max_age = refresh_family_max_age
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            create_schema(connection)
            apply_migrations(connection, "oauth", OAUTH_MIGRATIONS)

    @staticmethod
    def _validate_redirect_uri(uri: str) -> str:
        uri = uri.strip()
        if not uri:
            raise ValueError("at least one redirect URI is required")
        parsed = urlsplit(uri)
        if parsed.fragment:
            raise ValueError("redirect URI fragments are not allowed")
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("redirect URI must be absolute")
        host = (parsed.hostname or "").lower()
        loopback = host in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme.lower() != "https" and not (
            parsed.scheme.lower() == "http" and loopback
        ):
            raise ValueError("redirect URI must use HTTPS")
        return uri

    @staticmethod
    def _client(row: sqlite3.Row | None) -> ClientRegistration | None:
        if row is None:
            return None
        return ClientRegistration(
            id=int(row["id"]),
            name=str(row["name"]),
            client_id=str(row["client_id"]),
            redirect_uris=tuple(json.loads(row["redirect_uris"])),
            scopes=tuple(json.loads(row["scopes"])),
            active=bool(row["active"]),
        )

    @staticmethod
    def _session(row: sqlite3.Row) -> AuthenticatedSession:
        return AuthenticatedSession(
            session_id=str(row["session_id"]),
            workspace_id=str(row["workspace_id"]),
            user_id=int(row["user_id"]),
            client_id=str(row["client_id"]),
            scopes=tuple(json.loads(row["scopes"])),
            audience=str(row["audience"]),
            resource=str(row["resource"]),
            access_expires_at=_parse(str(row["access_expires_at"])),
        )

    def register_client(
        self,
        name: str,
        redirect_uris: tuple[str, ...],
        scopes: tuple[str, ...],
    ) -> ClientRegistration:
        name = name.strip()
        if not name:
            raise ValueError("client name is required")
        if not redirect_uris:
            raise ValueError("at least one redirect URI is required")
        redirects = tuple(
            dict.fromkeys(self._validate_redirect_uri(uri) for uri in redirect_uris)
        )
        normalized_scopes = tuple(
            dict.fromkeys(scope.strip() for scope in scopes if scope.strip())
        )
        client_id = _secret("mcr_client_")
        now = _iso(_utc_now())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO platform_oauth_clients
                    (name,client_id,redirect_uris,scopes,active,created_at,updated_at)
                VALUES (?,?,?,?,1,?,?)
                """,
                (
                    name,
                    client_id,
                    json.dumps(redirects),
                    json.dumps(normalized_scopes),
                    now,
                    now,
                ),
            )
            row_id = int(cursor.lastrowid)
        return ClientRegistration(
            row_id, name, client_id, redirects, normalized_scopes, True
        )

    def get_client(self, client_id: str) -> ClientRegistration | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_oauth_clients WHERE client_id=?",
                (client_id,),
            ).fetchone()
        return self._client(row)

    @staticmethod
    def _require_client_tx(
        connection: sqlite3.Connection, client_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM platform_oauth_clients WHERE client_id=? AND active=1",
            (client_id,),
        ).fetchone()
        if row is None:
            raise ValueError("invalid OAuth client")
        return row

    @staticmethod
    def _require_identity_tx(
        connection: sqlite3.Connection, workspace_id: str, user_id: int
    ) -> None:
        if isinstance(user_id, bool) or not isinstance(user_id, int):
            raise ValueError("authenticated identity must be a platform user")
        row = connection.execute(
            """
            SELECT 1
            FROM platform_workspaces AS workspace
            JOIN platform_memberships AS membership
              ON membership.workspace_id=workspace.id
             AND membership.user_id=?
            JOIN platform_users AS user ON user.id=membership.user_id
            WHERE workspace.public_id=?
            """,
            (user_id, workspace_id.strip()),
        ).fetchone()
        if row is None:
            raise ValueError("authenticated identity has no active membership")

    @staticmethod
    def _approved_scopes(
        client: sqlite3.Row, requested: tuple[str, ...]
    ) -> tuple[str, ...]:
        scopes = tuple(
            dict.fromkeys(scope.strip() for scope in requested if scope.strip())
        )
        registered = set(json.loads(client["scopes"]))
        if not set(scopes).issubset(registered):
            raise ValueError("requested scope is not registered for client")
        return scopes

    @staticmethod
    def _authority_target(audience: str, resource: str) -> tuple[str, str]:
        audience = audience.strip()
        resource = resource.strip()
        if not audience:
            raise ValueError("token audience is required")
        if not resource:
            raise ValueError("token resource is required")
        return audience, resource

    def _issue_session_tx(
        self,
        connection: sqlite3.Connection,
        *,
        workspace_id: str,
        user_id: int,
        client_id: str,
        scopes: tuple[str, ...],
        audience: str,
        resource: str,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
    ) -> SessionTokens:
        client = OAuthSessionStore._require_client_tx(connection, client_id)
        OAuthSessionStore._require_identity_tx(connection, workspace_id, user_id)
        approved_scopes = OAuthSessionStore._approved_scopes(client, scopes)
        audience, resource = OAuthSessionStore._authority_target(audience, resource)
        session_id = _secret("mcr_sess_")
        access_token = _secret("mcr_at_")
        refresh_token = _secret("mcr_rt_")
        now = _utc_now()
        access_expires = now + access_ttl
        refresh_family_expires = now + self.refresh_family_max_age
        refresh_expires = min(now + refresh_ttl, refresh_family_expires)
        connection.execute(
            """
            INSERT INTO platform_oauth_sessions
                (session_id,workspace_id,user_id,client_id,scopes,audience,resource,
                 authority_version,access_hash,refresh_hash,access_expires_at,
                 refresh_expires_at,refresh_family_expires_at,revoked_at,
                 created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)
            """,
            (
                session_id,
                workspace_id,
                user_id,
                client_id,
                json.dumps(approved_scopes),
                audience,
                resource,
                AUTHORITY_VERSION,
                _digest(access_token),
                _digest(refresh_token),
                _iso(access_expires),
                _iso(refresh_expires),
                _iso(refresh_family_expires),
                _iso(now),
                _iso(now),
            ),
        )
        return SessionTokens(
            session_id,
            access_token,
            refresh_token,
            access_expires,
            refresh_expires,
        )

    def issue_session(
        self,
        workspace_id: str,
        user_id: int,
        client_id: str,
        *,
        scopes: tuple[str, ...] = (),
        audience: str = DEFAULT_AUDIENCE,
        resource: str = DEFAULT_RESOURCE,
        access_ttl: timedelta = timedelta(minutes=15),
        refresh_ttl: timedelta = timedelta(days=30),
    ) -> SessionTokens:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._issue_session_tx(
                connection,
                workspace_id=workspace_id,
                user_id=user_id,
                client_id=client_id,
                scopes=scopes,
                audience=audience,
                resource=resource,
                access_ttl=access_ttl,
                refresh_ttl=refresh_ttl,
            )

    def create_auth_code(
        self,
        workspace_id: str,
        user_id: int,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        *,
        code_challenge_method: str = "S256",
        scopes: tuple[str, ...] = (),
        audience: str = DEFAULT_AUDIENCE,
        resource: str = DEFAULT_RESOURCE,
        ttl: timedelta = timedelta(minutes=10),
    ) -> str:
        if code_challenge_method != "S256":
            raise ValueError("PKCE code challenge method must be S256")
        code_challenge = code_challenge.strip()
        if not _PKCE_CHALLENGE.fullmatch(code_challenge):
            raise ValueError("PKCE S256 code challenge is invalid")
        audience, resource = self._authority_target(audience, resource)
        code = _secret("mcr_code_")
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            client = self._require_client_tx(connection, client_id)
            self._require_identity_tx(connection, workspace_id, user_id)
            if redirect_uri not in tuple(json.loads(client["redirect_uris"])):
                raise ValueError("redirect URI is not registered for client")
            approved_scopes = self._approved_scopes(client, scopes)
            connection.execute(
                """
                INSERT INTO platform_oauth_codes
                    (code_hash,workspace_id,user_id,client_id,redirect_uri,
                     code_challenge,code_challenge_method,scopes,audience,resource,
                     authority_version,expires_at,consumed_at,session_id,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?)
                """,
                (
                    _digest(code),
                    workspace_id,
                    user_id,
                    client_id,
                    redirect_uri,
                    code_challenge,
                    code_challenge_method,
                    json.dumps(approved_scopes),
                    audience,
                    resource,
                    AUTHORITY_VERSION,
                    _iso(now + ttl),
                    _iso(now),
                ),
            )
        return code

    def exchange_code(
        self,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> SessionTokens:
        code_hash = _digest(code)
        now = _utc_now()
        replayed = False
        tokens: SessionTokens | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM platform_oauth_codes WHERE code_hash=?",
                (code_hash,),
            ).fetchone()
            if row is None:
                raise ValueError("invalid or expired authorization code")
            if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
                raise ValueError(
                    "authorization code was issued to a different client or redirect"
                )
            if row["code_challenge_method"] != "S256" or not _pkce_matches(
                str(row["code_challenge"]), code_verifier
            ):
                raise ValueError("PKCE verification failed")
            if row["consumed_at"] is not None:
                if row["session_id"] is not None:
                    now_iso = _iso(now)
                    connection.execute(
                        """
                        UPDATE platform_oauth_sessions
                        SET revoked_at=COALESCE(revoked_at,?),updated_at=?
                        WHERE session_id=?
                        """,
                        (now_iso, now_iso, row["session_id"]),
                    )
                replayed = True
            elif (
                int(row["authority_version"]) != AUTHORITY_VERSION
                or _parse(str(row["expires_at"])) <= now
            ):
                raise ValueError("invalid or expired authorization code")
            if replayed:
                # Exit the transaction normally so family revocation commits.
                pass
            else:
                tokens = self._issue_session_tx(
                    connection,
                    workspace_id=str(row["workspace_id"]),
                    user_id=int(row["user_id"]),
                    client_id=str(row["client_id"]),
                    scopes=tuple(json.loads(row["scopes"])),
                    audience=str(row["audience"]),
                    resource=str(row["resource"]),
                    access_ttl=timedelta(minutes=15),
                    refresh_ttl=timedelta(days=30),
                )
                updated = connection.execute(
                    """
                    UPDATE platform_oauth_codes SET consumed_at=?,session_id=?
                    WHERE code_hash=? AND consumed_at IS NULL
                    """,
                    (_iso(now), tokens.session_id, code_hash),
                )
                if updated.rowcount != 1:
                    raise ValueError("invalid or expired authorization code")
        if replayed or tokens is None:
            raise ValueError("invalid or expired authorization code")
        return tokens

    def validate_access(
        self,
        access_token: str,
        *,
        audience: str = DEFAULT_AUDIENCE,
        resource: str = DEFAULT_RESOURCE,
    ) -> AuthenticatedSession | None:
        now = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT session.*
                FROM platform_oauth_sessions AS session
                JOIN platform_oauth_clients AS client
                  ON client.client_id=session.client_id
                WHERE session.access_hash=? AND client.active=1
                """,
                (_digest(access_token),),
            ).fetchone()
        if (
            row is None
            or row["revoked_at"] is not None
            or int(row["authority_version"]) != AUTHORITY_VERSION
            or _parse(str(row["access_expires_at"])) <= now
            or not hmac.compare_digest(str(row["audience"]), audience)
            or not hmac.compare_digest(str(row["resource"]), resource)
        ):
            return None
        return self._session(row)

    def refresh_session(
        self,
        refresh_token: str,
        *,
        client_id: str,
        access_ttl: timedelta = timedelta(minutes=15),
        refresh_ttl: timedelta = timedelta(days=30),
    ) -> SessionTokens | None:
        token_hash = _digest(refresh_token)
        now = _utc_now()
        now_iso = _iso(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replayed = connection.execute(
                """
                SELECT history.session_id,session.client_id
                FROM platform_oauth_refresh_history AS history
                JOIN platform_oauth_sessions AS session
                  ON session.session_id=history.session_id
                WHERE history.token_hash=?
                """,
                (token_hash,),
            ).fetchone()
            if replayed is not None:
                if not hmac.compare_digest(
                    str(replayed["client_id"]),
                    client_id,
                ):
                    return None
                connection.execute(
                    """
                    UPDATE platform_oauth_sessions
                    SET revoked_at=COALESCE(revoked_at,?),updated_at=?
                    WHERE session_id=?
                    """,
                    (now_iso, now_iso, replayed["session_id"]),
                )
                return None

            row = connection.execute(
                """
                SELECT session.*
                FROM platform_oauth_sessions AS session
                JOIN platform_oauth_clients AS client
                  ON client.client_id=session.client_id
                WHERE session.refresh_hash=?
                  AND session.client_id=?
                  AND client.active=1
                """,
                (token_hash, client_id),
            ).fetchone()
            try:
                stored_family_expires = (
                    _parse(str(row["refresh_family_expires_at"]))
                    if row is not None
                    else None
                )
                configured_family_expires = (
                    _parse(str(row["created_at"])) + self.refresh_family_max_age
                    if row is not None
                    else None
                )
                family_expires = (
                    min(stored_family_expires, configured_family_expires)
                    if stored_family_expires is not None
                    and configured_family_expires is not None
                    else None
                )
            except (TypeError, ValueError):
                family_expires = None
            if (
                row is None
                or row["revoked_at"] is not None
                or int(row["authority_version"]) != AUTHORITY_VERSION
                or _parse(str(row["refresh_expires_at"])) <= now
                or family_expires is None
                or family_expires <= now
            ):
                return None
            try:
                self._require_identity_tx(
                    connection, str(row["workspace_id"]), int(row["user_id"])
                )
            except ValueError:
                connection.execute(
                    """
                    UPDATE platform_oauth_sessions SET revoked_at=?,updated_at=?
                    WHERE session_id=?
                    """,
                    (now_iso, now_iso, row["session_id"]),
                )
                return None

            access_token = _secret("mcr_at_")
            new_refresh_token = _secret("mcr_rt_")
            access_expires = now + access_ttl
            refresh_expires = min(now + refresh_ttl, family_expires)
            connection.execute(
                """
                INSERT INTO platform_oauth_refresh_history
                    (token_hash,session_id,rotated_at) VALUES (?,?,?)
                """,
                (token_hash, row["session_id"], now_iso),
            )
            connection.execute(
                """
                UPDATE platform_oauth_sessions
                SET access_hash=?,refresh_hash=?,access_expires_at=?,
                    refresh_expires_at=?,updated_at=?
                WHERE session_id=?
                """,
                (
                    _digest(access_token),
                    _digest(new_refresh_token),
                    _iso(access_expires),
                    _iso(refresh_expires),
                    now_iso,
                    row["session_id"],
                ),
            )
            return SessionTokens(
                str(row["session_id"]),
                access_token,
                new_refresh_token,
                access_expires,
                refresh_expires,
            )

    def revoke_client(self, client_id: str) -> bool:
        now = _iso(_utc_now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE platform_oauth_clients SET active=0,updated_at=?
                WHERE client_id=? AND active=1
                """,
                (now, client_id),
            )
            if cursor.rowcount == 0:
                return False
            connection.execute(
                """
                UPDATE platform_oauth_sessions
                SET revoked_at=COALESCE(revoked_at,?),updated_at=?
                WHERE client_id=?
                """,
                (now, now, client_id),
            )
            connection.execute(
                """
                UPDATE platform_oauth_codes SET consumed_at=COALESCE(consumed_at,?)
                WHERE client_id=?
                """,
                (now, client_id),
            )
            return True

    def revoke_session(self, session_id: str) -> bool:
        now = _iso(_utc_now())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE platform_oauth_sessions SET revoked_at=?,updated_at=?
                WHERE session_id=? AND revoked_at IS NULL
                """,
                (now, now, session_id),
            )
        return cursor.rowcount > 0


__all__ = [
    "AUTHORITY_VERSION",
    "DEFAULT_AUDIENCE",
    "DEFAULT_RESOURCE",
    "AuthenticatedSession",
    "ClientRegistration",
    "OAuthSessionStore",
    "SessionTokens",
]
