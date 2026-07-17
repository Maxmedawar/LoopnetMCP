"""OAuth-ready client registry and revocable session storage."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from cre_mcp.access.context import TenantContext
from cre_mcp.access.profiles import Profile
from cre_mcp.platform.schema import create_schema

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
    try:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
    except UnicodeEncodeError:
        return False
    actual = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(challenge, actual)

@dataclass(frozen=True)
class ClientRegistration:
    id: int
    workspace_id: str
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
    session_id: str
    workspace_id: str
    user_id: str
    client_id: str
    profile: Profile
    plan: str
    territories: tuple[str, ...]
    scopes: tuple[str, ...]
    audience: str

_AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_oauth_clients (
 id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL,
 name TEXT NOT NULL, client_id TEXT NOT NULL UNIQUE,
 redirect_uris TEXT NOT NULL, scopes TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, CHECK(active IN (0,1)),
 FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(public_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_platform_oauth_clients_workspace
 ON platform_oauth_clients(workspace_id, active, created_at);
CREATE TABLE IF NOT EXISTS platform_oauth_codes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code_hash TEXT NOT NULL UNIQUE,
 workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, client_id TEXT NOT NULL,
 redirect_uri TEXT NOT NULL, code_challenge TEXT NOT NULL,
 profile TEXT NOT NULL, plan TEXT NOT NULL, territories TEXT NOT NULL,
 scopes TEXT NOT NULL, audience TEXT NOT NULL, expires_at TEXT NOT NULL,
 consumed_at TEXT, created_at TEXT NOT NULL,
 FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(public_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS platform_oauth_sessions (
 session_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL,
 client_id TEXT NOT NULL, profile TEXT NOT NULL, plan TEXT NOT NULL,
 territories TEXT NOT NULL, scopes TEXT NOT NULL, audience TEXT NOT NULL,
 access_hash TEXT NOT NULL UNIQUE, refresh_hash TEXT NOT NULL UNIQUE,
 access_expires_at TEXT NOT NULL, refresh_expires_at TEXT NOT NULL,
 revoked_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(workspace_id) REFERENCES platform_workspaces(public_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_platform_oauth_sessions_workspace
 ON platform_oauth_sessions(workspace_id, user_id, revoked_at);
CREATE TABLE IF NOT EXISTS platform_oauth_refresh_history (
 token_hash TEXT PRIMARY KEY, session_id TEXT NOT NULL, rotated_at TEXT NOT NULL,
 FOREIGN KEY(session_id) REFERENCES platform_oauth_sessions(session_id) ON DELETE CASCADE
);
"""

class OAuthSessionStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self._ensure_schema()
        self._ensure_auth_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            create_schema(connection)

    def _ensure_auth_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(_AUTH_SCHEMA)

    def _require_workspace(self, workspace_id: str) -> str:
        workspace_id = workspace_id.strip()
        if not workspace_id:
            raise ValueError("workspace_id is required")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM platform_workspaces WHERE public_id = ?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            raise ValueError("workspace does not exist")
        return workspace_id

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
        if parsed.scheme.lower() != "https" and not (parsed.scheme.lower() == "http" and loopback):
            raise ValueError("redirect URI must use HTTPS")
        return uri

    def register_client(
        self,
        workspace_id: str,
        name: str,
        redirect_uris: tuple[str, ...],
        scopes: tuple[str, ...],
    ) -> ClientRegistration:
        workspace_id = self._require_workspace(workspace_id)
        name = name.strip()
        if not workspace_id:
            raise ValueError("workspace_id is required")
        if not name:
            raise ValueError("client name is required")
        if not redirect_uris:
            raise ValueError("at least one redirect URI is required")
        redirects = tuple(dict.fromkeys(self._validate_redirect_uri(uri) for uri in redirect_uris))
        normalized_scopes = tuple(dict.fromkeys(scope.strip() for scope in scopes if scope.strip()))
        client_id = _secret("mcr_client_")
        now = _iso(_utc_now())
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO platform_oauth_clients
                (workspace_id,name,client_id,redirect_uris,scopes,active,created_at,updated_at)
                VALUES (?,?,?,?,?,1,?,?)""",
                (workspace_id, name, client_id, json.dumps(redirects),
                 json.dumps(normalized_scopes), now, now),
            )
            row_id = int(cursor.lastrowid)
        return ClientRegistration(row_id, workspace_id, name, client_id,
                                  redirects, normalized_scopes, True)

    def get_client(self, client_id: str) -> ClientRegistration | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_oauth_clients WHERE client_id=?", (client_id,)
            ).fetchone()
        if row is None:
            return None
        return ClientRegistration(
            int(row["id"]), str(row["workspace_id"]), str(row["name"]),
            str(row["client_id"]), tuple(json.loads(row["redirect_uris"])),
            tuple(json.loads(row["scopes"])), bool(row["active"]),
        )

    def _require_client(self, workspace_id: str, client_id: str) -> ClientRegistration:
        client = self.get_client(client_id)
        if client is None or not client.active or client.workspace_id != workspace_id:
            raise ValueError("invalid client for workspace")
        return client

    @staticmethod
    def _approved_scopes(client: ClientRegistration,
                         requested: tuple[str, ...]) -> tuple[str, ...]:
        scopes = tuple(dict.fromkeys(scope.strip() for scope in requested if scope.strip()))
        if not set(scopes).issubset(set(client.scopes)):
            raise ValueError("requested scope is not registered for client")
        return scopes

    def issue_session(
        self,
        workspace_id: str,
        user_id: str,
        client_id: str,
        profile: Profile,
        *,
        plan: str = "standard",
        territories: tuple[str, ...] = (),
        scopes: tuple[str, ...] = (),
        audience: str = "medawarcre-mcp",
        access_ttl: timedelta = timedelta(minutes=15),
        refresh_ttl: timedelta = timedelta(days=30),
    ) -> SessionTokens:
        client = self._require_client(workspace_id, client_id)
        approved_scopes = self._approved_scopes(client, scopes)
        session_id = _secret("mcr_sess_")
        access_token = _secret("mcr_at_")
        refresh_token = _secret("mcr_rt_")
        now = _utc_now()
        access_expires = now + access_ttl
        refresh_expires = now + refresh_ttl
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO platform_oauth_sessions
                (session_id,workspace_id,user_id,client_id,profile,plan,territories,
                 scopes,audience,access_hash,refresh_hash,access_expires_at,
                 refresh_expires_at,revoked_at,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)""",
                (session_id, workspace_id, user_id, client_id, profile.value, plan,
                 json.dumps(tuple(territories)), json.dumps(approved_scopes), audience,
                 _digest(access_token), _digest(refresh_token), _iso(access_expires),
                 _iso(refresh_expires), _iso(now), _iso(now)),
            )
        return SessionTokens(session_id, access_token, refresh_token,
                             access_expires, refresh_expires)

    def create_auth_code(
        self, workspace_id: str, user_id: str, client_id: str,
        redirect_uri: str, code_challenge: str, *, profile: Profile,
        plan: str = "standard", territories: tuple[str, ...] = (),
        scopes: tuple[str, ...] = (), audience: str = "medawarcre-mcp",
        ttl: timedelta = timedelta(minutes=10),
    ) -> str:
        client = self._require_client(workspace_id, client_id)
        if redirect_uri not in client.redirect_uris:
            raise ValueError("redirect URI is not registered for client")
        code_challenge = code_challenge.strip()
        if not code_challenge:
            raise ValueError("PKCE code challenge is required")
        approved_scopes = self._approved_scopes(client, scopes)
        code = _secret("mcr_code_")
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO platform_oauth_codes
                (code_hash,workspace_id,user_id,client_id,redirect_uri,code_challenge,
                 profile,plan,territories,scopes,audience,expires_at,consumed_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)""",
                (_digest(code), workspace_id, user_id, client_id, redirect_uri,
                 code_challenge, profile.value, plan, json.dumps(tuple(territories)),
                 json.dumps(approved_scopes), audience, _iso(now + ttl), _iso(now)),
            )
        return code

    def exchange_code(
        self, code: str, client_id: str, redirect_uri: str, code_verifier: str
    ) -> SessionTokens:
        code_hash = _digest(code)
        now = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_oauth_codes WHERE code_hash=?", (code_hash,)
            ).fetchone()
            if row is None or row["consumed_at"] is not None:
                raise ValueError("invalid or expired authorization code")
            if _parse(row["expires_at"]) <= now:
                raise ValueError("invalid or expired authorization code")
            if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
                raise ValueError("authorization code was issued to a different client or redirect")
            if not _pkce_matches(row["code_challenge"], code_verifier):
                raise ValueError("PKCE verification failed")
            connection.execute(
                "UPDATE platform_oauth_codes SET consumed_at=? WHERE code_hash=?",
                (_iso(now), code_hash),
            )
        return self.issue_session(
            str(row["workspace_id"]), str(row["user_id"]), str(row["client_id"]),
            Profile(row["profile"]), plan=str(row["plan"]),
            territories=tuple(json.loads(row["territories"])),
            scopes=tuple(json.loads(row["scopes"])), audience=str(row["audience"]),
        )

    def validate_access(self, access_token: str) -> AuthenticatedSession | None:
        now = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_oauth_sessions WHERE access_hash=?",
                (_digest(access_token),),
            ).fetchone()
        if row is None or row["revoked_at"] is not None:
            return None
        if _parse(row["access_expires_at"]) <= now:
            return None
        return AuthenticatedSession(
            str(row["session_id"]), str(row["workspace_id"]), str(row["user_id"]),
            str(row["client_id"]), Profile(row["profile"]), str(row["plan"]),
            tuple(json.loads(row["territories"])), tuple(json.loads(row["scopes"])),
            str(row["audience"]),
        )

    def context_for(self, access_token: str) -> TenantContext | None:
        session = self.validate_access(access_token)
        if session is None:
            return None
        return TenantContext(
            workspace_id=session.workspace_id, profile=session.profile,
            plan=session.plan, territories=session.territories,
        )

    def refresh_session(
        self,
        refresh_token: str,
        *,
        access_ttl: timedelta = timedelta(minutes=15),
        refresh_ttl: timedelta = timedelta(days=30),
    ) -> SessionTokens | None:
        token_hash = _digest(refresh_token)
        now = _utc_now()
        with self._connect() as connection:
            replayed = connection.execute(
                "SELECT session_id FROM platform_oauth_refresh_history WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
            if replayed is not None:
                connection.execute(
                    """UPDATE platform_oauth_sessions
                    SET revoked_at=COALESCE(revoked_at,?), updated_at=?
                    WHERE session_id=?""",
                    (_iso(now), _iso(now), replayed["session_id"]),
                )
                return None
            row = connection.execute(
                "SELECT * FROM platform_oauth_sessions WHERE refresh_hash=?",
                (token_hash,),
            ).fetchone()
            if row is None or row["revoked_at"] is not None:
                return None
            if _parse(row["refresh_expires_at"]) <= now:
                return None
            access_token = _secret("mcr_at_")
            new_refresh_token = _secret("mcr_rt_")
            access_expires = now + access_ttl
            refresh_expires = now + refresh_ttl
            connection.execute(
                """INSERT INTO platform_oauth_refresh_history
                (token_hash,session_id,rotated_at) VALUES (?,?,?)""",
                (token_hash, row["session_id"], _iso(now)),
            )
            connection.execute(
                """UPDATE platform_oauth_sessions
                SET access_hash=?, refresh_hash=?, access_expires_at=?,
                    refresh_expires_at=?, updated_at=?
                WHERE session_id=?""",
                (_digest(access_token), _digest(new_refresh_token),
                 _iso(access_expires), _iso(refresh_expires), _iso(now),
                 row["session_id"]),
            )
        return SessionTokens(str(row["session_id"]), access_token,
                             new_refresh_token, access_expires, refresh_expires)

    def revoke_session(self, session_id: str) -> bool:
        now = _iso(_utc_now())
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE platform_oauth_sessions SET revoked_at=?, updated_at=?
                WHERE session_id=? AND revoked_at IS NULL""",
                (now, now, session_id),
            )
        return cursor.rowcount > 0
