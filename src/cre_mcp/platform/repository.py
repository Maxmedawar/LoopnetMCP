"""SQLite persistence for the multi-tenant platform layer.

Mirrors the ``DealStore`` conventions: a synchronous core dispatched through
``asyncio.to_thread``, validation errors raised as ``ValueError``, and database
failures logged and reported as ``None``/empty results rather than raised.
Unknown parent rows surface as ``None`` via the enforced foreign keys.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

from pydantic import BaseModel

from cre_mcp.access.context import current_context, current_runtime_config
from cre_mcp.config import CreConfig
from cre_mcp.platform.models import (
    CLIENT_STATUSES,
    CONSENT_TYPES,
    MEMBERSHIP_ROLES,
    PRIVACY_REQUEST_KINDS,
    PRIVACY_REQUEST_STATUSES,
    PRIVACY_REQUEST_TRANSITIONS,
    SAVED_DEAL_STAGES,
    ConnectedClient,
    ConsentRecord,
    IntegrationEvent,
    Membership,
    Note,
    Outcome,
    Plan,
    PrivacyRequest,
    SavedDeal,
    Territory,
    User,
    Workspace,
)
from cre_mcp.platform.schema import create_schema
from cre_mcp.source_rights.output import safe_error_message, sanitize_payload

logger = logging.getLogger(__name__)

T = TypeVar("T")
WorkspaceRef = int | str

# table -> (record model, JSON-encoded columns to decode on read)
_TABLE_MODELS: dict[str, tuple[type[BaseModel], tuple[str, ...]]] = {
    "platform_users": (User, ()),
    "platform_plans": (Plan, ("daily_quotas",)),
    "platform_workspaces": (Workspace, ()),
    "platform_memberships": (Membership, ()),
    "platform_territories": (Territory, ()),
    "platform_connected_clients": (ConnectedClient, ("scopes",)),
    "platform_saved_deals": (SavedDeal, ("payload",)),
    "platform_notes": (Note, ()),
    "platform_outcomes": (Outcome, ()),
    "platform_consents": (ConsentRecord, ()),
    "platform_integration_events": (IntegrationEvent, ("payload",)),
    "platform_privacy_requests": (PrivacyRequest, ()),
}


def _require(value: str | None, label: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError(f"{label} cannot be blank")
    return normalized


def _one_of(value: str | None, allowed: Iterable[str], label: str) -> str:
    choices = tuple(allowed)
    normalized = (value or "").strip().casefold()
    if normalized not in choices:
        raise ValueError(f"{label} must be one of {', '.join(choices)}")
    return normalized


def _encode(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), default=str)


def _daily_quotas(value: dict[str, int]) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("daily quotas must be an object")
    normalized: dict[str, int] = {}
    for raw_bucket, raw_limit in value.items():
        bucket = _require(raw_bucket, "quota bucket")
        if type(raw_limit) is not int or raw_limit < 0:
            raise ValueError(
                f"quota limit for {bucket!r} must be a non-negative integer"
            )
        normalized[bucket] = raw_limit
    return normalized


class PlatformRepository:
    """Async façade over the ``platform_*`` tables in the shared cache DB."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        from cre_mcp.postgres.domains import (
            AdmittedRequestUnavailable,
            current_hosted_request_repositories,
        )

        context = current_context()
        if current_hosted_request_repositories() is not None or (
            context is not None and not context.trusted
        ):
            raise AdmittedRequestUnavailable(
                "hosted platform persistence cannot construct a local repository"
            )
        if isinstance(db_path, CreConfig):
            selected_config = db_path
        else:
            selected_config = config or current_runtime_config() or CreConfig()
        self._config = selected_config
        resolved = (
            selected_config.cache_db_path
            if isinstance(db_path, CreConfig)
            else db_path or selected_config.cache_db_path
        )
        self.db_path = Path(resolved).expanduser()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            create_schema(connection)
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    # --- generic row plumbing -------------------------------------------------

    @staticmethod
    def _to_model(table: str, row: sqlite3.Row) -> Any:
        model, json_fields = _TABLE_MODELS[table]
        data = dict(row)
        for field in json_fields:
            data[field] = json.loads(str(data[field]))
        return model(**data)

    def _insert_row(self, table: str, data: dict[str, Any]) -> Any:
        columns = ", ".join(data)
        placeholders = ", ".join("?" for _ in data)
        with self._connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO {table}({columns}) VALUES ({placeholders})",
                tuple(data.values()),
            )
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._to_model(table, row)

    def _get_row(self, table: str, row_id: int) -> Any | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ?",
                (row_id,),
            ).fetchone()
        return self._to_model(table, row) if row is not None else None

    def _list_rows(
        self,
        table: str,
        *,
        where: str = "",
        params: tuple[Any, ...] = (),
        order: str = "created_at, id",
    ) -> list[Any]:
        clause = f" WHERE {where}" if where else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {table}{clause} ORDER BY {order}",
                params,
            ).fetchall()
        return [self._to_model(table, row) for row in rows]

    def _resolve_workspace_id(self, workspace: WorkspaceRef) -> int | None:
        with self._connect() as connection:
            if isinstance(workspace, bool):
                return None
            if isinstance(workspace, int):
                row = connection.execute(
                    "SELECT id FROM platform_workspaces WHERE id = ?", (workspace,)
                ).fetchone()
            else:
                public_id = str(workspace).strip()
                if not public_id:
                    return None
                row = connection.execute(
                    "SELECT id FROM platform_workspaces WHERE public_id = ?", (public_id,)
                ).fetchone()
        return int(row["id"]) if row is not None else None

    def _get_scoped_row(
        self, table: str, workspace: WorkspaceRef, row_id: int
    ) -> Any | None:
        workspace_id = self._resolve_workspace_id(workspace)
        if workspace_id is None:
            return None
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ? AND workspace_id = ?",
                (row_id, workspace_id),
            ).fetchone()
        return self._to_model(table, row) if row is not None else None

    def _update_row(self, table: str, row_id: int, fields: dict[str, Any]) -> Any | None:
        """Update a global/admin row; an empty patch leaves timestamps unchanged."""
        if not fields:
            return self._get_row(table, row_id)
        assignments = ", ".join([f"{name} = ?" for name in fields] + ["updated_at = ?"])
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?",
                (*fields.values(), self._now(), row_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ?", (row_id,)
            ).fetchone()
        return self._to_model(table, row) if row is not None else None

    def _update_scoped_row(
        self,
        table: str,
        workspace: WorkspaceRef,
        row_id: int,
        fields: dict[str, Any],
    ) -> Any | None:
        workspace_id = self._resolve_workspace_id(workspace)
        if workspace_id is None:
            return None
        if not fields:
            return self._get_scoped_row(table, workspace_id, row_id)
        assignments = ", ".join([f"{name} = ?" for name in fields] + ["updated_at = ?"])
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ? AND workspace_id = ?",
                (*fields.values(), self._now(), row_id, workspace_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ? AND workspace_id = ?",
                (row_id, workspace_id),
            ).fetchone()
        return self._to_model(table, row) if row is not None else None

    def _user_belongs_to_workspace(self, workspace_id: int, user_id: int) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM platform_memberships WHERE workspace_id = ? AND user_id = ?",
                (workspace_id, user_id),
            ).fetchone()
        return row is not None

    async def _run(self, label: str, func: Callable[..., T], *args: Any) -> T | None:
        """Return None only for expected integrity conflicts; propagate operational failures."""
        try:
            return await asyncio.to_thread(func, *args)
        except sqlite3.IntegrityError as exc:
            logger.info(
                "%s rejected by database integrity rules: %s",
                safe_error_message(label, config=self._config),
                safe_error_message(exc, config=self._config),
            )
            return None

    async def _run_list(
        self, label: str, func: Callable[..., list[T]], *args: Any
    ) -> list[T]:
        result = await self._run(label, func, *args)
        return result if result is not None else []

    def _timestamps(self) -> dict[str, str]:
        now = self._now()
        return {"created_at": now, "updated_at": now}

    # --- users ----------------------------------------------------------------

    async def create_user(self, email: str, name: str) -> User | None:
        """Persist a platform login; a duplicate email reports None."""
        data = {
            "email": _require(email, "user email"),
            "name": _require(name, "user name"),
            **self._timestamps(),
        }
        return await self._run("user create", self._insert_row, "platform_users", data)

    async def get_user(self, user_id: int) -> User | None:
        """Return one user by identifier."""
        return await self._run("user read", self._get_row, "platform_users", user_id)

    async def list_users(self) -> list[User]:
        """Return every user, oldest first."""
        return await self._run_list("user list", self._list_rows, "platform_users")

    async def update_user(
        self,
        user_id: int,
        *,
        email: str | None = None,
        name: str | None = None,
    ) -> User | None:
        """Change user fields; None leaves a field unchanged."""
        fields: dict[str, Any] = {}
        if email is not None:
            fields["email"] = _require(email, "user email")
        if name is not None:
            fields["name"] = _require(name, "user name")
        return await self._run(
            "user update", self._update_row, "platform_users", user_id, fields
        )

    # --- plans ----------------------------------------------------------------

    async def create_plan(
        self,
        key: str,
        name: str,
        *,
        monthly_price_usd: float | None = None,
        seat_limit: int | None = None,
        daily_quotas: dict[str, int] | None = None,
    ) -> Plan | None:
        """Persist a subscription tier; a duplicate key reports None."""
        data = {
            "key": _require(key, "plan key"),
            "name": _require(name, "plan name"),
            "monthly_price_usd": monthly_price_usd,
            "seat_limit": seat_limit,
            "daily_quotas": _encode(
                _daily_quotas({} if daily_quotas is None else daily_quotas)
            ),
            **self._timestamps(),
        }
        return await self._run("plan create", self._insert_row, "platform_plans", data)

    async def get_plan(self, plan_id: int) -> Plan | None:
        """Return one plan by identifier."""
        return await self._run("plan read", self._get_row, "platform_plans", plan_id)

    async def list_plans(self) -> list[Plan]:
        """Return every plan, oldest first."""
        return await self._run_list("plan list", self._list_rows, "platform_plans")

    async def update_plan(
        self,
        plan_id: int,
        *,
        name: str | None = None,
        monthly_price_usd: float | None = None,
        seat_limit: int | None = None,
        daily_quotas: dict[str, int] | None = None,
    ) -> Plan | None:
        """Change plan fields; None leaves a field unchanged."""
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = _require(name, "plan name")
        if monthly_price_usd is not None:
            fields["monthly_price_usd"] = monthly_price_usd
        if seat_limit is not None:
            fields["seat_limit"] = seat_limit
        if daily_quotas is not None:
            fields["daily_quotas"] = _encode(_daily_quotas(daily_quotas))
        return await self._run(
            "plan update", self._update_row, "platform_plans", plan_id, fields
        )

    # --- workspaces -----------------------------------------------------------

    async def create_workspace(
        self,
        name: str,
        *,
        slug: str | None = None,
        plan_id: int | None = None,
    ) -> Workspace | None:
        """Persist a tenant; an unknown plan or duplicate slug reports None."""
        data = {
            "public_id": "ws_" + secrets.token_urlsafe(18),
            "name": _require(name, "workspace name"),
            "slug": slug.strip() if slug is not None else None,
            "plan_id": plan_id,
            **self._timestamps(),
        }
        return await self._run(
            "workspace create", self._insert_row, "platform_workspaces", data
        )

    async def get_workspace(self, workspace: WorkspaceRef) -> Workspace | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        return await self._run(
            "workspace read", self._get_row, "platform_workspaces", workspace_id
        )

    async def get_workspace_by_public_id(self, public_id: str) -> Workspace | None:
        return await self.get_workspace(public_id)

    async def list_workspaces(self) -> list[Workspace]:
        """Return every workspace, oldest first."""
        return await self._run_list(
            "workspace list", self._list_rows, "platform_workspaces"
        )

    async def update_workspace(
        self,
        workspace: WorkspaceRef,
        *,
        name: str | None = None,
        slug: str | None = None,
        plan_id: int | None = None,
    ) -> Workspace | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = _require(name, "workspace name")
        if slug is not None:
            fields["slug"] = slug.strip()
        if plan_id is not None:
            fields["plan_id"] = plan_id
        return await self._run(
            "workspace update", self._update_row,
            "platform_workspaces", workspace_id, fields
        )


    # --- memberships ----------------------------------------------------------

    async def add_membership(
        self,
        workspace: WorkspaceRef,
        user_id: int,
        role: str = "member",
    ) -> Membership | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        data = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "role": _one_of(role, MEMBERSHIP_ROLES, "role"),
            **self._timestamps(),
        }
        return await self._run(
            "membership create", self._insert_row, "platform_memberships", data
        )


    async def get_membership(
        self, workspace: WorkspaceRef, membership_id: int
    ) -> Membership | None:
        return await self._run(
            "membership read", self._get_scoped_row,
            "platform_memberships", workspace, membership_id
        )

    async def list_memberships(self, workspace: WorkspaceRef) -> list[Membership]:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return []
        return await self._run_list(
            "membership list",
            lambda: self._list_rows(
                "platform_memberships",
                where="workspace_id = ?",
                params=(workspace_id,),
            ),
        )


    async def update_membership_role(
        self, workspace: WorkspaceRef, membership_id: int, role: str
    ) -> Membership | None:
        fields = {"role": _one_of(role, MEMBERSHIP_ROLES, "role")}
        return await self._run(
            "membership update", self._update_scoped_row,
            "platform_memberships", workspace, membership_id, fields
        )


    # --- territories ----------------------------------------------------------

    async def claim_territory(
        self,
        workspace: WorkspaceRef,
        name: str,
        *,
        state: str | None = None,
        market: str | None = None,
        asset_type: str | None = None,
    ) -> Territory | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        data = {
            "workspace_id": workspace_id,
            "name": _require(name, "territory name"),
            "state": state,
            "market": market,
            "asset_type": asset_type,
            **self._timestamps(),
        }
        return await self._run(
            "territory create", self._insert_row, "platform_territories", data
        )


    async def get_territory(
        self, workspace: WorkspaceRef, territory_id: int
    ) -> Territory | None:
        return await self._run(
            "territory read", self._get_scoped_row,
            "platform_territories", workspace, territory_id
        )

    async def list_territories(self, workspace: WorkspaceRef) -> list[Territory]:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return []
        return await self._run_list(
            "territory list",
            lambda: self._list_rows(
                "platform_territories",
                where="workspace_id = ?",
                params=(workspace_id,),
            ),
        )


    async def update_territory(
        self,
        workspace: WorkspaceRef,
        territory_id: int,
        *,
        name: str | None = None,
        state: str | None = None,
        market: str | None = None,
        asset_type: str | None = None,
    ) -> Territory | None:
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = _require(name, "territory name")
        if state is not None:
            fields["state"] = state
        if market is not None:
            fields["market"] = market
        if asset_type is not None:
            fields["asset_type"] = asset_type
        return await self._run(
            "territory update", self._update_scoped_row,
            "platform_territories", workspace, territory_id, fields
        )


    # --- connected clients ----------------------------------------------------

    async def connect_client(
        self,
        workspace: WorkspaceRef,
        name: str,
        client_type: str,
        *,
        scopes: Iterable[str] = (),
    ) -> ConnectedClient | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        data = {
            "workspace_id": workspace_id,
            "name": _require(name, "client name"),
            "client_type": _require(client_type, "client_type"),
            "scopes": _encode([_require(scope, "scope") for scope in scopes]),
            "status": "active",
            **self._timestamps(),
        }
        return await self._run(
            "client create", self._insert_row, "platform_connected_clients", data
        )


    async def get_connected_client(
        self, workspace: WorkspaceRef, client_id: int
    ) -> ConnectedClient | None:
        return await self._run(
            "client read", self._get_scoped_row,
            "platform_connected_clients", workspace, client_id
        )

    async def list_connected_clients(
        self, workspace: WorkspaceRef
    ) -> list[ConnectedClient]:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return []
        return await self._run_list(
            "client list",
            lambda: self._list_rows(
                "platform_connected_clients",
                where="workspace_id = ?",
                params=(workspace_id,),
            ),
        )


    async def update_client_status(
        self, workspace: WorkspaceRef, client_id: int, status: str
    ) -> ConnectedClient | None:
        fields = {"status": _one_of(status, CLIENT_STATUSES, "status")}
        return await self._run(
            "client update", self._update_scoped_row,
            "platform_connected_clients", workspace, client_id, fields
        )


    # --- saved deals ----------------------------------------------------------

    def _save_deal(
        self,
        workspace_id: int,
        deal_ref: str,
        title: str,
        payload: dict[str, Any] | None,
        stage: str | None,
    ) -> SavedDeal:
        now = self._now()
        stored_payload = sanitize_payload(
            payload or {},
            purpose="storage",
            config=self._config,
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, stage FROM platform_saved_deals "
                "WHERE workspace_id = ? AND deal_ref = ?",
                (workspace_id, deal_ref),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO platform_saved_deals(
                        workspace_id, deal_ref, title, payload, stage,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        workspace_id,
                        deal_ref,
                        title,
                        _encode(stored_payload),
                        stage or "watching",
                        now,
                        now,
                    ),
                )
            else:
                fields = ["title = ?", "payload = ?", "updated_at = ?"]
                values: list[Any] = [title, _encode(stored_payload), now]
                if stage is not None:
                    fields.append("stage = ?")
                    values.append(stage)
                connection.execute(
                    f"UPDATE platform_saved_deals SET {', '.join(fields)} "
                    "WHERE workspace_id = ? AND deal_ref = ?",
                    (*values, workspace_id, deal_ref),
                )
            row = connection.execute(
                "SELECT * FROM platform_saved_deals "
                "WHERE workspace_id = ? AND deal_ref = ?",
                (workspace_id, deal_ref),
            ).fetchone()
        return self._sanitize_saved_deal(
            self._to_model("platform_saved_deals", row)
        )

    def _sanitize_saved_deal(self, deal: SavedDeal) -> SavedDeal:
        return deal.model_copy(
            update={
                "payload": sanitize_payload(
                    deal.payload,
                    config=self._config,
                )
            }
        )

    async def save_deal(
        self,
        workspace: WorkspaceRef,
        deal_ref: str,
        title: str,
        *,
        payload: dict[str, Any] | None = None,
        stage: str | None = None,
    ) -> SavedDeal | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        normalized_stage = (
            _one_of(stage, SAVED_DEAL_STAGES, "stage") if stage is not None else None
        )
        return await self._run(
            "saved-deal upsert",
            self._save_deal,
            workspace_id,
            safe_error_message(
                _require(deal_ref, "deal_ref"),
                config=self._config,
            ),
            safe_error_message(
                _require(title, "deal title"),
                config=self._config,
            ),
            payload,
            normalized_stage,
        )

    async def get_saved_deal(
        self, workspace: WorkspaceRef, saved_deal_id: int
    ) -> SavedDeal | None:
        deal = await self._run(
            "saved-deal read", self._get_scoped_row,
            "platform_saved_deals", workspace, saved_deal_id
        )
        return self._sanitize_saved_deal(deal) if deal is not None else None

    async def list_saved_deals(
        self,
        workspace: WorkspaceRef,
        *,
        stage: str | None = None,
    ) -> list[SavedDeal]:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return []
        where = "workspace_id = ?"
        params: tuple[Any, ...] = (workspace_id,)
        if stage is not None:
            where += " AND stage = ?"
            params = (*params, _one_of(stage, SAVED_DEAL_STAGES, "stage"))
        deals = await self._run_list(
            "saved-deal list",
            lambda: self._list_rows(
                "platform_saved_deals",
                where=where,
                params=params,
                order="updated_at DESC, id",
            ),
        )
        return [self._sanitize_saved_deal(deal) for deal in deals]

    async def update_saved_deal(
        self,
        workspace: WorkspaceRef,
        saved_deal_id: int,
        *,
        title: str | None = None,
        payload: dict[str, Any] | None = None,
        stage: str | None = None,
    ) -> SavedDeal | None:
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = safe_error_message(
                _require(title, "deal title"),
                config=self._config,
            )
        if payload is not None:
            fields["payload"] = _encode(
                sanitize_payload(
                    payload,
                    purpose="storage",
                    config=self._config,
                )
            )
        if stage is not None:
            fields["stage"] = _one_of(stage, SAVED_DEAL_STAGES, "stage")
        deal = await self._run(
            "saved-deal update", self._update_scoped_row,
            "platform_saved_deals", workspace, saved_deal_id, fields
        )
        return self._sanitize_saved_deal(deal) if deal is not None else None

    # --- notes ----------------------------------------------------------------

    async def add_note(
        self,
        workspace: WorkspaceRef,
        saved_deal_id: int,
        author_user_id: int,
        body: str,
    ) -> Note | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        data = {
            "workspace_id": workspace_id,
            "saved_deal_id": saved_deal_id,
            "author_user_id": author_user_id,
            "body": _require(body, "note body"),
            **self._timestamps(),
        }
        return await self._run("note create", self._insert_row, "platform_notes", data)

    async def get_note(
        self, workspace: WorkspaceRef, note_id: int
    ) -> Note | None:
        return await self._run(
            "note read", self._get_scoped_row,
            "platform_notes", workspace, note_id
        )

    async def list_notes(
        self, workspace: WorkspaceRef, saved_deal_id: int
    ) -> list[Note]:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return []
        return await self._run_list(
            "note list",
            lambda: self._list_rows(
                "platform_notes",
                where="workspace_id = ? AND saved_deal_id = ?",
                params=(workspace_id, saved_deal_id),
            ),
        )

    async def update_note(
        self, workspace: WorkspaceRef, note_id: int, body: str
    ) -> Note | None:
        fields = {"body": _require(body, "note body")}
        return await self._run(
            "note update", self._update_scoped_row,
            "platform_notes", workspace, note_id, fields
        )

    def _record_outcome(
        self,
        workspace_id: int,
        saved_deal_id: int,
        closed: bool,
        purchase_price: float | None,
        notes: str | None,
    ) -> Outcome:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO platform_outcomes(
                    workspace_id, saved_deal_id, closed, purchase_price, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, saved_deal_id) DO UPDATE SET
                    closed = excluded.closed,
                    purchase_price = excluded.purchase_price,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at""",
                (
                    workspace_id,
                    saved_deal_id,
                    int(closed),
                    purchase_price,
                    notes,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM platform_outcomes "
                "WHERE workspace_id = ? AND saved_deal_id = ?",
                (workspace_id, saved_deal_id),
            ).fetchone()
        return self._to_model("platform_outcomes", row)

    async def record_outcome(
        self,
        workspace: WorkspaceRef,
        saved_deal_id: int,
        *,
        closed: bool,
        purchase_price: float | None = None,
        notes: str | None = None,
    ) -> Outcome | None:
        if not isinstance(closed, bool):
            raise ValueError("closed must be true or false")
        if closed and purchase_price is None:
            raise ValueError("purchase_price is required when closed=true")
        if purchase_price is not None and (
            isinstance(purchase_price, bool)
            or not math.isfinite(float(purchase_price))
            or float(purchase_price) <= 0
        ):
            raise ValueError("purchase_price must be greater than zero")
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        return await self._run(
            "outcome upsert",
            self._record_outcome,
            workspace_id,
            saved_deal_id,
            closed,
            purchase_price,
            notes,
        )

    def _get_outcome(self, workspace_id: int, saved_deal_id: int) -> Outcome | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM platform_outcomes "
                "WHERE workspace_id = ? AND saved_deal_id = ?",
                (workspace_id, saved_deal_id),
            ).fetchone()
        return self._to_model("platform_outcomes", row) if row is not None else None

    async def get_outcome(
        self, workspace: WorkspaceRef, saved_deal_id: int
    ) -> Outcome | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        return await self._run(
            "outcome read", self._get_outcome, workspace_id, saved_deal_id
        )

    async def list_outcomes(self, workspace: WorkspaceRef) -> list[Outcome]:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return []
        return await self._run_list(
            "outcome list",
            lambda: self._list_rows(
                "platform_outcomes",
                where="workspace_id = ?",
                params=(workspace_id,),
                order="updated_at DESC, id",
            ),
        )

    # --- consent records ------------------------------------------------------

    async def record_consent(
        self,
        workspace: WorkspaceRef,
        user_id: int,
        consent_type: str,
        *,
        granted: bool,
        version: str,
    ) -> ConsentRecord | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None or not await asyncio.to_thread(
            self._user_belongs_to_workspace, workspace_id, user_id
        ):
            return None
        data = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "consent_type": _one_of(consent_type, CONSENT_TYPES, "consent_type"),
            "granted": int(bool(granted)),
            "version": _require(version, "consent version"),
            "created_at": self._now(),
        }
        return await self._run(
            "consent create", self._insert_row, "platform_consents", data
        )

    async def get_consent(
        self, workspace: WorkspaceRef, consent_id: int
    ) -> ConsentRecord | None:
        return await self._run(
            "consent read", self._get_scoped_row,
            "platform_consents", workspace, consent_id
        )

    async def list_consents(
        self, workspace: WorkspaceRef, user_id: int
    ) -> list[ConsentRecord]:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return []
        return await self._run_list(
            "consent list",
            lambda: self._list_rows(
                "platform_consents",
                where="workspace_id = ? AND user_id = ?",
                params=(workspace_id, user_id),
            ),
        )

    def _latest_consent(
        self, workspace_id: int, user_id: int, consent_type: str
    ) -> ConsentRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM platform_consents
                WHERE workspace_id = ? AND user_id = ? AND consent_type = ?
                ORDER BY created_at DESC, id DESC LIMIT 1""",
                (workspace_id, user_id, consent_type),
            ).fetchone()
        return self._to_model("platform_consents", row) if row is not None else None

    async def latest_consent(
        self, workspace: WorkspaceRef, user_id: int, consent_type: str
    ) -> ConsentRecord | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        normalized = _one_of(consent_type, CONSENT_TYPES, "consent_type")
        return await self._run(
            "consent latest", self._latest_consent,
            workspace_id, user_id, normalized
        )

    async def log_integration_event(
        self,
        workspace: WorkspaceRef,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
        client_id: int | None = None,
    ) -> IntegrationEvent | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return None
        if client_id is not None and await asyncio.to_thread(
            self._get_scoped_row,
            "platform_connected_clients",
            workspace_id,
            client_id,
        ) is None:
            return None
        data = {
            "workspace_id": workspace_id,
            "client_id": client_id,
            "event_type": _require(event_type, "event_type"),
            "payload": _encode(payload or {}),
            "created_at": self._now(),
        }
        return await self._run(
            "integration-event create",
            self._insert_row,
            "platform_integration_events",
            data,
        )

    async def get_integration_event(
        self, workspace: WorkspaceRef, event_id: int
    ) -> IntegrationEvent | None:
        return await self._run(
            "integration-event read", self._get_scoped_row,
            "platform_integration_events", workspace, event_id
        )

    async def list_integration_events(
        self,
        workspace: WorkspaceRef,
        *,
        event_type: str | None = None,
    ) -> list[IntegrationEvent]:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return []
        where = "workspace_id = ?"
        params: tuple[Any, ...] = (workspace_id,)
        if event_type is not None:
            where += " AND event_type = ?"
            params = (*params, _require(event_type, "event_type"))
        return await self._run_list(
            "integration-event list",
            lambda: self._list_rows(
                "platform_integration_events", where=where, params=params
            ),
        )

    async def open_privacy_request(
        self,
        workspace: WorkspaceRef,
        user_id: int,
        kind: str,
        *,
        detail: str | None = None,
    ) -> PrivacyRequest | None:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None or not await asyncio.to_thread(
            self._user_belongs_to_workspace, workspace_id, user_id
        ):
            return None
        data = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "kind": _one_of(kind, PRIVACY_REQUEST_KINDS, "kind"),
            "status": "received",
            "detail": detail,
            **self._timestamps(),
        }
        return await self._run(
            "privacy-request create",
            self._insert_row,
            "platform_privacy_requests",
            data,
        )

    async def get_privacy_request(
        self, workspace: WorkspaceRef, request_id: int
    ) -> PrivacyRequest | None:
        return await self._run(
            "privacy-request read", self._get_scoped_row,
            "platform_privacy_requests", workspace, request_id
        )

    async def list_privacy_requests(
        self, workspace: WorkspaceRef, *, status: str | None = None
    ) -> list[PrivacyRequest]:
        workspace_id = await asyncio.to_thread(self._resolve_workspace_id, workspace)
        if workspace_id is None:
            return []
        where = "workspace_id = ?"
        params: tuple[Any, ...] = (workspace_id,)
        if status is not None:
            where += " AND status = ?"
            params = (*params, _one_of(status, PRIVACY_REQUEST_STATUSES, "status"))
        return await self._run_list(
            "privacy-request list",
            lambda: self._list_rows(
                "platform_privacy_requests", where=where, params=params
            ),
        )

    async def update_privacy_request(
        self, workspace: WorkspaceRef, request_id: int, status: str
    ) -> PrivacyRequest | None:
        normalized = _one_of(status, PRIVACY_REQUEST_STATUSES, "status")
        current = await asyncio.to_thread(
            self._get_scoped_row,
            "platform_privacy_requests",
            workspace,
            request_id,
        )
        if current is None:
            return None
        if normalized == current.status:
            return current
        allowed = PRIVACY_REQUEST_TRANSITIONS[current.status]
        if normalized not in allowed:
            raise ValueError(
                f"privacy request transition {current.status} -> {normalized} is not allowed"
            )
        return await self._run(
            "privacy-request update", self._update_scoped_row,
            "platform_privacy_requests", workspace, request_id,
            {"status": normalized},
        )


def get_platform_repository(config: CreConfig | None = None) -> Any:
    """Build a repository façade over the configured shared database."""
    from cre_mcp.postgres.domains import (
        AdmittedRequestUnavailable,
        current_hosted_request_repositories,
    )

    hosted = current_hosted_request_repositories()
    if hosted is not None:
        return hosted.require("platform")
    context = current_context()
    if context is not None and not context.trusted:
        raise AdmittedRequestUnavailable(
            "hosted platform persistence cannot construct a local repository"
        )
    return PlatformRepository(config=config)


__all__ = ["PlatformRepository", "get_platform_repository"]
