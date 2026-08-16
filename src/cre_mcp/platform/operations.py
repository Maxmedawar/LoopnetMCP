"""Internal Operations Console sessions and bounded read models.

The console is a browser BFF, not another OAuth client. Clerk proves a person,
then live MedawarCRE operator state authorizes every request. Provider identity,
tenant membership, and client-supplied selectors never grant staff authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.schema import create_schema
from cre_mcp.platform.dbapi import platform_connection


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


def _limit(value: Any, *, maximum: int = 50) -> int:
    if isinstance(value, bool):
        raise ValueError(f"limit must be an integer from 1 to {maximum}")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"limit must be an integer from 1 to {maximum}") from exc
    if normalized < 1 or normalized > maximum:
        raise ValueError(f"limit must be an integer from 1 to {maximum}")
    return normalized


def _cursor(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        raise ValueError("cursor must be a non-negative integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("cursor must be a non-negative integer") from exc
    if normalized < 0:
        raise ValueError("cursor must be a non-negative integer")
    return normalized


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class _Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            create_schema(connection)
        EntitlementStore(self.db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with platform_connection(
            self.db_path,
            timeout=30,
            transactional=False,
        ) as connection:
            yield connection


@dataclass(frozen=True)
class IssuedOperatorSession:
    token: str
    csrf_token: str
    user_id: int
    expires_at: datetime


@dataclass(frozen=True)
class OperatorSession:
    user_id: int
    expires_at: datetime


class OperatorSessionStore(_Store):
    """Opaque, short-lived staff sessions with only digests at rest."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        ttl: timedelta = timedelta(minutes=30),
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("operator session TTL must be positive")
        self.ttl = ttl
        super().__init__(db_path)

    def issue(self, user_id: int) -> IssuedOperatorSession:
        token = _secret("mcr_ops_")
        csrf = _secret("mcr_ops_csrf_")
        now = _now()
        expires = now + self.ttl
        with self._connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO platform_operator_sessions(
                    token_hash,user_id,csrf_hash,expires_at,revoked_at,
                    created_at,updated_at
                ) VALUES (?,?,?,?,NULL,?,?)
                """,
                (
                    _digest(token),
                    user_id,
                    _digest(csrf),
                    _iso(expires),
                    _iso(now),
                    _iso(now),
                ),
            )
        return IssuedOperatorSession(token, csrf, user_id, expires)

    def validate(self, token: str) -> OperatorSession | None:
        if not token:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id,expires_at FROM platform_operator_sessions
                WHERE token_hash=? AND revoked_at IS NULL
                """,
                (_digest(token),),
            ).fetchone()
        if row is None:
            return None
        expires = _parse(str(row["expires_at"]))
        if expires <= _now():
            return None
        return OperatorSession(int(row["user_id"]), expires)

    def validate_csrf(self, token: str, csrf_token: str) -> bool:
        if not csrf_token or self.validate(token) is None:
            return False
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT csrf_hash FROM platform_operator_sessions
                WHERE token_hash=? AND revoked_at IS NULL
                """,
                (_digest(token),),
            ).fetchone()
        return row is not None and hmac.compare_digest(
            str(row["csrf_hash"]), _digest(csrf_token)
        )

    def revoke(self, token: str) -> bool:
        now = _iso(_now())
        with self._connect() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE platform_operator_sessions
                SET revoked_at=?,updated_at=?
                WHERE token_hash=? AND revoked_at IS NULL
                """,
                (now, now, _digest(token)),
            )
        return cursor.rowcount == 1


class OperationsReadStore(_Store):
    """Bounded, payload-free read models for the internal console."""

    def live_operator(self, user_id: int) -> dict[str, Any] | None:
        now = _iso(_now())
        with self._connect() as connection:
            operator = connection.execute(
                """
                SELECT user.id AS user_id,user.email,user.name,admin.role
                FROM platform_internal_admins AS admin
                JOIN platform_users AS user ON user.id=admin.user_id
                WHERE admin.user_id=? AND admin.active=1
                  AND admin.role IN ('platform_admin','support')
                """,
                (user_id,),
            ).fetchone()
            if operator is None:
                return None
            jv = connection.execute(
                """
                SELECT 1
                FROM platform_memberships AS membership
                JOIN platform_access_grants AS grant
                  ON grant.workspace_id=membership.workspace_id
                WHERE membership.user_id=?
                  AND grant.profile='jv_partner'
                  AND grant.status IN ('active','overridden','expiring')
                  AND grant.starts_at<=?
                  AND (grant.ends_at IS NULL OR grant.ends_at>?)
                  AND (
                    grant.scope='workspace'
                    OR grant.subject_user_id=membership.user_id
                  )
                LIMIT 1
                """,
                (user_id, now, now),
            ).fetchone()
        value = dict(operator)
        value["jv_grant_present"] = jv is not None
        return value

    def search_workspaces(
        self,
        query: Any,
        *,
        limit: Any = 25,
        cursor: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(query, str):
            raise ValueError("q must be a string")
        normalized = query.strip()
        if len(normalized) < 2 or len(normalized) > 128:
            raise ValueError("q must contain 2 to 128 characters")
        page_limit = _limit(limit)
        after_id = _cursor(cursor)
        escaped = (
            normalized.casefold()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    workspace.id,
                    workspace.public_id,
                    workspace.name,
                    workspace.slug,
                    workspace.plan_id,
                    account.state AS account_state,
                    COUNT(DISTINCT membership.id) AS membership_count,
                    COUNT(DISTINCT grant.id) AS grant_count,
                    COUNT(DISTINCT territory.id) AS territory_count
                FROM platform_workspaces AS workspace
                LEFT JOIN platform_accounts AS account
                  ON account.workspace_id=workspace.id
                LEFT JOIN platform_memberships AS membership
                  ON membership.workspace_id=workspace.id
                LEFT JOIN platform_users AS user
                  ON user.id=membership.user_id
                LEFT JOIN platform_access_grants AS grant
                  ON grant.workspace_id=workspace.id
                LEFT JOIN platform_territories AS territory
                  ON territory.workspace_id=workspace.id
                WHERE workspace.id>?
                  AND (
                    lower(workspace.public_id) LIKE ? ESCAPE '\\'
                    OR lower(workspace.name) LIKE ? ESCAPE '\\'
                    OR lower(COALESCE(workspace.slug,'')) LIKE ? ESCAPE '\\'
                    OR lower(COALESCE(user.email,'')) LIKE ? ESCAPE '\\'
                  )
                -- account.state is listed explicitly. SQLite lets a bare
                -- column ride along with a GROUP BY and picks an arbitrary row
                -- from the group; PostgreSQL rejects the query unless the
                -- column is grouped or aggregated, and only extends that
                -- courtesy to columns functionally dependent on a grouped
                -- primary key -- which workspace.* are and account.state is
                -- not. There is at most one account per workspace, so adding
                -- it changes no result in either engine.
                GROUP BY workspace.id, account.state
                ORDER BY workspace.id
                LIMIT ?
                """,
                (after_id, pattern, pattern, pattern, pattern, page_limit + 1),
            ).fetchall()
        visible = rows[:page_limit]
        return {
            "workspaces": [dict(row) for row in visible],
            "next_cursor": (
                str(visible[-1]["id"])
                if len(rows) > page_limit and visible
                else None
            ),
        }

    def list_audit(
        self,
        *,
        workspace_public_id: str | None = None,
        limit: Any = 50,
        cursor: Any = None,
    ) -> dict[str, Any]:
        page_limit = _limit(limit, maximum=100)
        after_id = _cursor(cursor)
        parameters: list[Any] = [after_id]
        workspace_clause = ""
        with self._connect() as connection:
            if workspace_public_id:
                workspace = connection.execute(
                    "SELECT id FROM platform_workspaces WHERE public_id=?",
                    (workspace_public_id.strip(),),
                ).fetchone()
                if workspace is None:
                    raise LookupError("Workspace does not exist")
                workspace_clause = "AND audit.workspace_id=?"
                parameters.append(int(workspace["id"]))
            parameters.append(page_limit + 1)
            rows = connection.execute(
                f"""
                SELECT audit.*,user.email AS actor_email,user.name AS actor_name,
                       workspace.public_id AS workspace_public_id
                FROM platform_admin_audit AS audit
                JOIN platform_users AS user ON user.id=audit.actor_user_id
                LEFT JOIN platform_workspaces AS workspace
                  ON workspace.id=audit.workspace_id
                WHERE audit.id>? {workspace_clause}
                ORDER BY audit.id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        visible = rows[:page_limit]
        events: list[dict[str, Any]] = []
        for row in visible:
            item = dict(row)
            item["before"] = json.loads(str(item.pop("before_json")))
            item["after"] = json.loads(str(item.pop("after_json")))
            events.append(item)
        return {
            "events": events,
            "next_cursor": (
                str(visible[-1]["id"])
                if len(rows) > page_limit and visible
                else None
            ),
        }

    def health(self) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()
            quarantined = connection.execute(
                """
                SELECT COUNT(*) FROM platform_provider_events
                WHERE outcome='quarantined'
                """
            ).fetchone()
            workspaces = connection.execute(
                "SELECT COUNT(*) FROM platform_workspaces"
            ).fetchone()
        return {
            "status": "ready",
            "database": "reachable",
            "workspaces": int(workspaces[0]),
            "quarantined_provider_events": int(quarantined[0]),
        }


__all__ = [
    "IssuedOperatorSession",
    "OperationsReadStore",
    "OperatorSession",
    "OperatorSessionStore",
]
