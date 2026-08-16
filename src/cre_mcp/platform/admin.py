"""Internal control-plane persistence with mandatory atomic audit."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from cre_mcp.access.profiles import Profile
from cre_mcp.platform.entitlements import (
    ACCOUNT_STATES,
    ACCOUNT_TRANSITIONS,
    GRANT_SCOPES,
    GRANT_STATUSES,
    PROVIDERS,
    EntitlementStore,
)
from cre_mcp.platform.models import (
    ADMIN_REASON_CODES,
    MEMBERSHIP_ROLES,
    normalize_platform_email,
)
from cre_mcp.platform.schema import create_schema
from cre_mcp.platform.dbapi import platform_connection

ADMIN_SCOPE = "admin:controls"
ADMIN_GRANT_SOURCES = ("manual", "jv", "promotion")


class AdminControlError(Exception):
    """Base class for expected control-plane failures."""


class AdminValidationError(AdminControlError):
    pass


class AdminForbiddenError(AdminControlError):
    pass


class AdminNotFoundError(AdminControlError):
    pass


class AdminConflictError(AdminControlError):
    pass


class AdminAuditError(AdminControlError):
    pass


@dataclass(frozen=True)
class MutationResult:
    value: dict[str, Any]
    action: str
    workspace_id: int | None
    target_type: str
    target_id: str
    before: Any
    after: Any


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _required(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise AdminValidationError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise AdminValidationError(f"{label} cannot be blank")
    return normalized


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _required(value, label)


def _choice(value: Any, choices: tuple[str, ...], label: str) -> str:
    normalized = _required(value, label).casefold()
    if normalized not in choices:
        raise AdminValidationError(
            f"{label} must be one of {', '.join(choices)}"
        )
    return normalized


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AdminValidationError(f"{label} must be a positive integer")
    return value


def _provider_slug(value: Any) -> str:
    normalized = _required(value, "provider").casefold()
    if (
        len(normalized) > 64
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized) is None
    ):
        raise AdminValidationError("provider must be a safe normalized slug")
    return normalized


def validate_reason(reason_code: Any, reason: Any) -> tuple[str, str]:
    return (
        _choice(reason_code, ADMIN_REASON_CODES, "reason_code"),
        _required(reason, "reason"),
    )


def _datetime(value: Any, label: str) -> datetime | None:
    if value is None:
        return None
    raw = _required(value, label)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise AdminValidationError(f"{label} must be an ISO-8601 datetime") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _row(
    row: sqlite3.Row | None,
    *,
    json_fields: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if row is None:
        return None
    value = dict(row)
    for field in json_fields:
        value[field] = json.loads(str(value[field]))
    return value


class AdminControlStore:
    """The only write path for audited internal control-plane actions."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            create_schema(connection)
        # Admin controls reuse account and grant tables but never their
        # independent transaction methods.
        EntitlementStore(self.db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with platform_connection(
            self.db_path,
            timeout=30,
            transactional=False,
        ) as connection:
            yield connection

    @staticmethod
    def _workspace(
        connection: sqlite3.Connection,
        public_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM platform_workspaces WHERE public_id=?",
            (public_id.strip(),),
        ).fetchone()
        if row is None:
            raise AdminNotFoundError("Workspace does not exist")
        return row

    @staticmethod
    def _membership_with_user(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["membership_id"]),
            "workspace_id": int(row["workspace_id"]),
            "user_id": int(row["user_id"]),
            "role": str(row["role"]),
            "created_at": str(row["membership_created_at"]),
            "updated_at": str(row["membership_updated_at"]),
            "user": {
                "id": int(row["user_id"]),
                "email": str(row["email"]),
                "name": str(row["user_name"]),
                "created_at": str(row["user_created_at"]),
                "updated_at": str(row["user_updated_at"]),
            },
        }

    @staticmethod
    def _memberships(
        connection: sqlite3.Connection,
        workspace_id: int,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT
                membership.id AS membership_id,
                membership.workspace_id,
                membership.user_id,
                membership.role,
                membership.created_at AS membership_created_at,
                membership.updated_at AS membership_updated_at,
                user.email,
                user.name AS user_name,
                user.created_at AS user_created_at,
                user.updated_at AS user_updated_at
            FROM platform_memberships AS membership
            JOIN platform_users AS user ON user.id=membership.user_id
            WHERE membership.workspace_id=?
            ORDER BY membership.id
            """,
            (workspace_id,),
        ).fetchall()
        return [AdminControlStore._membership_with_user(row) for row in rows]

    @staticmethod
    def _external_accounts(
        connection: sqlite3.Connection,
        workspace_id: int,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT * FROM platform_external_accounts
            WHERE workspace_id=?
            ORDER BY id
            """,
            (workspace_id,),
        ).fetchall()
        return [_row(row, json_fields=("metadata",)) for row in rows]

    def _mutate(
        self,
        *,
        actor_user_id: int,
        reason_code: Any,
        reason: Any,
        operation: Callable[[sqlite3.Connection], MutationResult],
        conflict_message: str = "Admin mutation conflicts with existing data",
    ) -> dict[str, Any]:
        normalized_code, normalized_reason = validate_reason(reason_code, reason)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                actor = connection.execute(
                    """
                    SELECT user_id,role
                    FROM platform_internal_admins
                    WHERE user_id=? AND active=1
                    """,
                    (actor_user_id,),
                ).fetchone()
                if actor is None or str(actor["role"]) != "platform_admin":
                    raise AdminForbiddenError(
                        "Active platform_admin authority is required"
                    )
                connection.execute(
                    """
                    CREATE TEMP TRIGGER admin_audit_callback_guard
                    BEFORE INSERT ON platform_admin_audit
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'admin mutation callbacks cannot write audit rows'
                        );
                    END
                    """
                )
                try:
                    result = operation(connection)
                except sqlite3.IntegrityError as exc:
                    if "callbacks cannot write audit rows" in str(exc):
                        raise AdminAuditError from exc
                    raise AdminConflictError(conflict_message) from exc
                finally:
                    connection.execute(
                        "DROP TRIGGER IF EXISTS admin_audit_callback_guard"
                    )

                changes_before_audit = connection.total_changes
                try:
                    connection.execute(
                        """
                        INSERT INTO platform_admin_audit(
                            actor_user_id,actor_role,action,workspace_id,
                            target_type,target_id,reason_code,reason,
                            before_json,after_json,created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            int(actor["user_id"]),
                            str(actor["role"]),
                            result.action,
                            result.workspace_id,
                            result.target_type,
                            result.target_id,
                            normalized_code,
                            normalized_reason,
                            canonical_json(result.before),
                            canonical_json(result.after),
                            _iso(_now()),
                        ),
                    )
                except sqlite3.DatabaseError as exc:
                    raise AdminAuditError from exc
                if connection.total_changes != changes_before_audit + 1:
                    raise AdminAuditError
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
                return result.value

    def get_workspace(self, public_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            workspace = self._workspace(connection, public_id)
            workspace_id = int(workspace["id"])
            account = _row(
                connection.execute(
                    "SELECT * FROM platform_accounts WHERE workspace_id=?",
                    (workspace_id,),
                ).fetchone()
            )
            grants = [
                _row(row)
                for row in connection.execute(
                    """
                    SELECT * FROM platform_access_grants
                    WHERE workspace_id=? ORDER BY id
                    """,
                    (workspace_id,),
                ).fetchall()
            ]
            territories = [
                _row(row)
                for row in connection.execute(
                    """
                    SELECT * FROM platform_territories
                    WHERE workspace_id=? ORDER BY id
                    """,
                    (workspace_id,),
                ).fetchall()
            ]
            return {
                "workspace": _row(workspace),
                "account": account,
                "memberships": self._memberships(connection, workspace_id),
                "grants": grants,
                "territories": territories,
                "external_accounts": self._external_accounts(
                    connection,
                    workspace_id,
                ),
            }

    def get_jv_workspace(self, public_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            workspace = self._workspace(connection, public_id)
            workspace_id = int(workspace["id"])
            territories = [
                _row(row)
                for row in connection.execute(
                    """
                    SELECT * FROM platform_territories
                    WHERE workspace_id=? ORDER BY id
                    """,
                    (workspace_id,),
                ).fetchall()
            ]
            return {
                "workspace": _row(workspace),
                "territories": territories,
            }

    def list_members(self, public_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            workspace = self._workspace(connection, public_id)
            return self._memberships(connection, int(workspace["id"]))

    def list_external_accounts(self, public_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            workspace = self._workspace(connection, public_id)
            return self._external_accounts(connection, int(workspace["id"]))

    def provision_workspace(
        self,
        *,
        actor_user_id: int,
        name: Any,
        owner_email: Any,
        owner_name: Any,
        reason_code: Any,
        reason: Any,
        slug: Any = None,
        plan_id: Any = None,
        account_state: Any = "active",
    ) -> dict[str, Any]:
        workspace_name = _required(name, "workspace name")
        # The same canonical form the identity lookup uses. This was
        # `.casefold()`, which collapsed `ß` to `ss` and `ﬁ` to `fi`, so an
        # operator provisioning `Straße@corp.test` stored a row that only the
        # holder of `strasse@corp.test` could ever bind to.
        email = normalize_platform_email(_required(owner_email, "owner_email"))
        user_name = _required(owner_name, "owner_name")
        workspace_slug = _optional_text(slug, "slug")
        state = _choice(account_state, ACCOUNT_STATES, "account_state")
        if plan_id is not None and (
            isinstance(plan_id, bool) or not isinstance(plan_id, int) or plan_id < 1
        ):
            raise AdminValidationError("plan_id must be a positive integer")

        def operation(connection: sqlite3.Connection) -> MutationResult:
            if plan_id is not None and connection.execute(
                "SELECT 1 FROM platform_plans WHERE id=?",
                (plan_id,),
            ).fetchone() is None:
                raise AdminValidationError(
                    "plan_id does not reference an existing plan"
                )
            now = _iso(_now())
            public_id = "ws_" + secrets.token_urlsafe(18)
            cursor = connection.execute(
                """
                INSERT INTO platform_workspaces(
                    public_id,name,slug,plan_id,created_at,updated_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (public_id, workspace_name, workspace_slug, plan_id, now, now),
            )
            workspace_id = int(cursor.lastrowid)
            user_cursor = connection.execute(
                """
                INSERT INTO platform_users(email,name,created_at,updated_at)
                VALUES (?,?,?,?)
                """,
                (email, user_name, now, now),
            )
            user_id = int(user_cursor.lastrowid)
            membership_cursor = connection.execute(
                """
                INSERT INTO platform_memberships(
                    workspace_id,user_id,role,created_at,updated_at
                ) VALUES (?,?,'owner',?,?)
                """,
                (workspace_id, user_id, now, now),
            )
            membership_id = int(membership_cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO platform_accounts(workspace_id,state,reason,updated_at)
                VALUES (?,?,NULL,?)
                """,
                (workspace_id, state, now),
            )
            value = {
                "workspace": _row(
                    connection.execute(
                        "SELECT * FROM platform_workspaces WHERE id=?",
                        (workspace_id,),
                    ).fetchone()
                ),
                "owner": _row(
                    connection.execute(
                        "SELECT * FROM platform_users WHERE id=?",
                        (user_id,),
                    ).fetchone()
                ),
                "membership": _row(
                    connection.execute(
                        "SELECT * FROM platform_memberships WHERE id=?",
                        (membership_id,),
                    ).fetchone()
                ),
                "account": _row(
                    connection.execute(
                        "SELECT * FROM platform_accounts WHERE workspace_id=?",
                        (workspace_id,),
                    ).fetchone()
                ),
            }
            return MutationResult(
                value=value,
                action="workspace.provision",
                workspace_id=workspace_id,
                target_type="workspace",
                target_id=public_id,
                before=None,
                after=value,
            )

        return self._mutate(
            actor_user_id=actor_user_id,
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            conflict_message="Workspace slug or owner email already exists",
        )

    def update_membership_role(
        self,
        *,
        actor_user_id: int,
        public_id: str,
        membership_id: int,
        role: Any,
        reason_code: Any,
        reason: Any,
    ) -> dict[str, Any]:
        normalized_role = _choice(role, MEMBERSHIP_ROLES, "role")

        def operation(connection: sqlite3.Connection) -> MutationResult:
            workspace = self._workspace(connection, public_id)
            workspace_id = int(workspace["id"])
            before = _row(
                connection.execute(
                    """
                    SELECT * FROM platform_memberships
                    WHERE id=? AND workspace_id=?
                    """,
                    (membership_id, workspace_id),
                ).fetchone()
            )
            if before is None:
                raise AdminNotFoundError("Membership does not exist")
            connection.execute(
                """
                UPDATE platform_memberships
                SET role=?,updated_at=?
                WHERE id=? AND workspace_id=?
                """,
                (normalized_role, _iso(_now()), membership_id, workspace_id),
            )
            after = _row(
                connection.execute(
                    "SELECT * FROM platform_memberships WHERE id=?",
                    (membership_id,),
                ).fetchone()
            )
            return MutationResult(
                value={"membership": after},
                action="membership.role.update",
                workspace_id=workspace_id,
                target_type="membership",
                target_id=str(membership_id),
                before=before,
                after=after,
            )

        return self._mutate(
            actor_user_id=actor_user_id,
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            conflict_message="Membership role conflicts with existing data",
        )

    def create_grant(
        self,
        *,
        actor_user_id: int,
        public_id: str,
        source: Any,
        external_ref: Any,
        profile: Any,
        plan_key: Any,
        reason_code: Any,
        reason: Any,
        status: Any = "active",
        starts_at: Any = None,
        ends_at: Any = None,
        subject_user_id: Any = None,
        scope: Any = None,
    ) -> dict[str, Any]:
        normalized_source = _choice(
            source,
            ADMIN_GRANT_SOURCES,
            "source",
        )
        normalized_external_ref = _required(external_ref, "external_ref")
        try:
            normalized_profile = Profile(_required(profile, "profile")).value
        except ValueError as exc:
            raise AdminValidationError("profile is not recognized") from exc
        normalized_plan = _required(plan_key, "plan_key")
        normalized_status = _choice(status, GRANT_STATUSES, "status")
        normalized_scope = _choice(scope, GRANT_SCOPES, "scope")
        if normalized_scope == "workspace":
            if normalized_source != "jv":
                raise AdminValidationError(
                    "workspace scope is only valid for jv grants"
                )
            if subject_user_id is not None:
                raise AdminValidationError(
                    "workspace grant cannot identify a subject"
                )
            normalized_subject_user_id = None
        else:
            normalized_subject_user_id = _positive_int(
                subject_user_id,
                "subject_user_id",
            )
        start = _datetime(starts_at, "starts_at") or _now()
        end = _datetime(ends_at, "ends_at")
        if end is not None and end <= start:
            raise AdminValidationError("ends_at must be later than starts_at")

        def operation(connection: sqlite3.Connection) -> MutationResult:
            workspace = self._workspace(connection, public_id)
            workspace_id = int(workspace["id"])
            if normalized_subject_user_id is not None:
                membership = connection.execute(
                    """
                    SELECT 1 FROM platform_memberships
                    WHERE workspace_id=? AND user_id=?
                    """,
                    (workspace_id, normalized_subject_user_id),
                ).fetchone()
                if membership is None:
                    raise AdminValidationError(
                        "subject_user_id must identify a workspace member"
                    )
            now = _iso(_now())
            cursor = connection.execute(
                """
                INSERT INTO platform_access_grants(
                    workspace_id,subject_user_id,scope,source,external_ref,
                    profile,plan_key,status,starts_at,ends_at,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    workspace_id,
                    normalized_subject_user_id,
                    normalized_scope,
                    normalized_source,
                    normalized_external_ref,
                    normalized_profile,
                    normalized_plan,
                    normalized_status,
                    _iso(start),
                    _iso(end) if end is not None else None,
                    now,
                    now,
                ),
            )
            grant_id = int(cursor.lastrowid)
            after = _row(
                connection.execute(
                    "SELECT * FROM platform_access_grants WHERE id=?",
                    (grant_id,),
                ).fetchone()
            )
            return MutationResult(
                value={"grant": after},
                action="grant.create",
                workspace_id=workspace_id,
                target_type="grant",
                target_id=str(grant_id),
                before=None,
                after=after,
            )

        return self._mutate(
            actor_user_id=actor_user_id,
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            conflict_message="Access grant already exists",
        )

    def revoke_grant(
        self,
        *,
        actor_user_id: int,
        public_id: str,
        grant_id: int,
        reason_code: Any,
        reason: Any,
    ) -> dict[str, Any]:
        def operation(connection: sqlite3.Connection) -> MutationResult:
            workspace = self._workspace(connection, public_id)
            workspace_id = int(workspace["id"])
            before = _row(
                connection.execute(
                    """
                    SELECT * FROM platform_access_grants
                    WHERE id=? AND workspace_id=?
                    """,
                    (grant_id, workspace_id),
                ).fetchone()
            )
            if before is None:
                raise AdminNotFoundError("Grant does not exist")
            if before["status"] == "revoked":
                raise AdminConflictError("Grant is already revoked")
            connection.execute(
                """
                UPDATE platform_access_grants
                SET status='revoked',updated_at=?
                WHERE id=? AND workspace_id=?
                """,
                (_iso(_now()), grant_id, workspace_id),
            )
            after = _row(
                connection.execute(
                    "SELECT * FROM platform_access_grants WHERE id=?",
                    (grant_id,),
                ).fetchone()
            )
            return MutationResult(
                value={"grant": after},
                action="grant.revoke",
                workspace_id=workspace_id,
                target_type="grant",
                target_id=str(grant_id),
                before=before,
                after=after,
            )

        return self._mutate(
            actor_user_id=actor_user_id,
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            conflict_message="Grant revocation conflicts with existing data",
        )

    def create_territory(
        self,
        *,
        actor_user_id: int,
        public_id: str,
        name: Any,
        reason_code: Any,
        reason: Any,
        state: Any = None,
        market: Any = None,
        asset_type: Any = None,
    ) -> dict[str, Any]:
        territory_name = _required(name, "territory name")
        territory_state = _optional_text(state, "state")
        territory_market = _optional_text(market, "market")
        territory_asset = _optional_text(asset_type, "asset_type")

        def operation(connection: sqlite3.Connection) -> MutationResult:
            workspace = self._workspace(connection, public_id)
            workspace_id = int(workspace["id"])
            now = _iso(_now())
            cursor = connection.execute(
                """
                INSERT INTO platform_territories(
                    workspace_id,name,state,market,asset_type,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    workspace_id,
                    territory_name,
                    territory_state,
                    territory_market,
                    territory_asset,
                    now,
                    now,
                ),
            )
            territory_id = int(cursor.lastrowid)
            after = _row(
                connection.execute(
                    "SELECT * FROM platform_territories WHERE id=?",
                    (territory_id,),
                ).fetchone()
            )
            return MutationResult(
                value={"territory": after},
                action="territory.create",
                workspace_id=workspace_id,
                target_type="territory",
                target_id=str(territory_id),
                before=None,
                after=after,
            )

        return self._mutate(
            actor_user_id=actor_user_id,
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            conflict_message="Territory already exists in this workspace",
        )

    def delete_territory(
        self,
        *,
        actor_user_id: int,
        public_id: str,
        territory_id: int,
        reason_code: Any,
        reason: Any,
    ) -> dict[str, Any]:
        def operation(connection: sqlite3.Connection) -> MutationResult:
            workspace = self._workspace(connection, public_id)
            workspace_id = int(workspace["id"])
            before = _row(
                connection.execute(
                    """
                    SELECT * FROM platform_territories
                    WHERE id=? AND workspace_id=?
                    """,
                    (territory_id, workspace_id),
                ).fetchone()
            )
            if before is None:
                raise AdminNotFoundError("Territory does not exist")
            connection.execute(
                "DELETE FROM platform_territories WHERE id=? AND workspace_id=?",
                (territory_id, workspace_id),
            )
            return MutationResult(
                value={"deleted": True, "territory": before},
                action="territory.delete",
                workspace_id=workspace_id,
                target_type="territory",
                target_id=str(territory_id),
                before=before,
                after=None,
            )

        return self._mutate(
            actor_user_id=actor_user_id,
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            conflict_message="Territory deletion conflicts with existing data",
        )

    def create_external_account(
        self,
        *,
        actor_user_id: int,
        public_id: str,
        provider: Any,
        external_account_id: Any,
        subject_user_id: Any,
        reason_code: Any,
        reason: Any,
        metadata: Any = None,
    ) -> dict[str, Any]:
        normalized_provider = _provider_slug(provider)
        normalized_external_id = _required(
            external_account_id,
            "external_account_id",
        )
        if normalized_provider in PROVIDERS:
            normalized_subject_user_id = _positive_int(
                subject_user_id,
                "subject_user_id",
            )
        elif subject_user_id is None:
            normalized_subject_user_id = None
        else:
            normalized_subject_user_id = _positive_int(
                subject_user_id,
                "subject_user_id",
            )
        if metadata is None:
            normalized_metadata: dict[str, Any] = {}
        elif isinstance(metadata, dict):
            normalized_metadata = metadata
        else:
            raise AdminValidationError("metadata must be a JSON object")

        def operation(connection: sqlite3.Connection) -> MutationResult:
            workspace = self._workspace(connection, public_id)
            workspace_id = int(workspace["id"])
            if normalized_subject_user_id is not None:
                membership = connection.execute(
                    """
                    SELECT 1 FROM platform_memberships
                    WHERE workspace_id=? AND user_id=?
                    """,
                    (workspace_id, normalized_subject_user_id),
                ).fetchone()
                if membership is None:
                    raise AdminValidationError(
                        "subject_user_id must identify a workspace member"
                    )
            now = _iso(_now())
            cursor = connection.execute(
                """
                INSERT INTO platform_external_accounts(
                    workspace_id,subject_user_id,provider,external_account_id,
                    metadata,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    workspace_id,
                    normalized_subject_user_id,
                    normalized_provider,
                    normalized_external_id,
                    canonical_json(normalized_metadata),
                    now,
                    now,
                ),
            )
            mapping_id = int(cursor.lastrowid)
            after = _row(
                connection.execute(
                    "SELECT * FROM platform_external_accounts WHERE id=?",
                    (mapping_id,),
                ).fetchone(),
                json_fields=("metadata",),
            )
            return MutationResult(
                value={"external_account": after},
                action="external_account.create",
                workspace_id=workspace_id,
                target_type="external_account",
                target_id=str(mapping_id),
                before=None,
                after=after,
            )

        return self._mutate(
            actor_user_id=actor_user_id,
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            conflict_message="External account mapping already exists",
        )

    def delete_external_account(
        self,
        *,
        actor_user_id: int,
        public_id: str,
        mapping_id: int,
        reason_code: Any,
        reason: Any,
    ) -> dict[str, Any]:
        def operation(connection: sqlite3.Connection) -> MutationResult:
            workspace = self._workspace(connection, public_id)
            workspace_id = int(workspace["id"])
            before = _row(
                connection.execute(
                    """
                    SELECT * FROM platform_external_accounts
                    WHERE id=? AND workspace_id=?
                    """,
                    (mapping_id, workspace_id),
                ).fetchone(),
                json_fields=("metadata",),
            )
            if before is None:
                raise AdminNotFoundError("External account does not exist")
            connection.execute(
                """
                DELETE FROM platform_external_accounts
                WHERE id=? AND workspace_id=?
                """,
                (mapping_id, workspace_id),
            )
            return MutationResult(
                value={"deleted": True, "external_account": before},
                action="external_account.delete",
                workspace_id=workspace_id,
                target_type="external_account",
                target_id=str(mapping_id),
                before=before,
                after=None,
            )

        return self._mutate(
            actor_user_id=actor_user_id,
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            conflict_message="External account deletion conflicts with existing data",
        )

    def set_account_state(
        self,
        *,
        actor_user_id: int,
        public_id: str,
        state: Any,
        reason_code: Any,
        reason: Any,
    ) -> dict[str, Any]:
        normalized_state = _choice(state, ACCOUNT_STATES, "state")

        def operation(connection: sqlite3.Connection) -> MutationResult:
            workspace = self._workspace(connection, public_id)
            workspace_id = int(workspace["id"])
            before = _row(
                connection.execute(
                    "SELECT * FROM platform_accounts WHERE workspace_id=?",
                    (workspace_id,),
                ).fetchone()
            )
            current = (
                str(before["state"])
                if before is not None
                else ("invited" if normalized_state == "invited" else "registered")
            )
            if (
                normalized_state != current
                and normalized_state not in ACCOUNT_TRANSITIONS[current]
            ):
                raise AdminConflictError("Invalid account transition")
            now = _iso(_now())
            if before is None:
                connection.execute(
                    """
                    INSERT INTO platform_accounts(
                        workspace_id,state,reason,updated_at
                    ) VALUES (?,?,?,?)
                    """,
                    (workspace_id, normalized_state, _required(reason, "reason"), now),
                )
            else:
                connection.execute(
                    """
                    UPDATE platform_accounts
                    SET state=?,reason=?,updated_at=?
                    WHERE workspace_id=?
                    """,
                    (
                        normalized_state,
                        _required(reason, "reason"),
                        now,
                        workspace_id,
                    ),
                )
            after = _row(
                connection.execute(
                    "SELECT * FROM platform_accounts WHERE workspace_id=?",
                    (workspace_id,),
                ).fetchone()
            )
            return MutationResult(
                value={"account": after},
                action="account.state.update",
                workspace_id=workspace_id,
                target_type="account",
                target_id=str(workspace_id),
                before=before,
                after=after,
            )

        return self._mutate(
            actor_user_id=actor_user_id,
            reason_code=reason_code,
            reason=reason,
            operation=operation,
            conflict_message="Account state conflicts with existing data",
        )


__all__ = [
    "ADMIN_SCOPE",
    "AdminAuditError",
    "AdminConflictError",
    "AdminControlError",
    "AdminControlStore",
    "AdminForbiddenError",
    "AdminNotFoundError",
    "AdminValidationError",
    "canonical_json",
    "validate_reason",
]
