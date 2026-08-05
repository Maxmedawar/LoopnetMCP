"""Request-scoped PostgreSQL persistence for customer saved searches."""

from __future__ import annotations

import asyncio
import hmac
import json
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from cre_mcp.access.context import TenantContext, current_context
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.domains import (
    current_hosted_request_repositories,
    require_fresh_admission,
)
from cre_mcp.postgres.pool import PostgresDatabase

_UNAVAILABLE = "search persistence unavailable"
_QUERY_KEYS = frozenset(
    {
        "location",
        "strategy",
        "property_type",
        "price_min",
        "price_max",
        "size_min",
        "size_max",
        "sources",
    }
)
_METHOD_TOOLS = {
    "save_search": frozenset({"save_search"}),
    "list_searches": frozenset({"list_searches", "check_alerts"}),
    "get_search": frozenset({"check_alerts"}),
    "seen_keys": frozenset({"check_alerts"}),
    "claim_unseen": frozenset({"check_alerts"}),
}
_MAX_CLAIM_KEYS = 500


class SearchPersistenceUnavailable(RuntimeError):
    """The exact hosted search persistence boundary cannot complete safely."""


async def _finish_thread_before_cancellation(function: Any, *args: Any) -> Any:
    """Keep the synchronous database worker inside its request lease."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        try:
            task.result()
        except Exception:
            pass
        raise


def _uuid(value: object) -> str:
    if not isinstance(value, (str, UUID)):
        raise ValueError("invalid search identifier")
    try:
        selected = str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("invalid search identifier") from error
    if isinstance(value, str) and value != selected:
        raise ValueError("invalid search identifier")
    return selected


def _text(value: object, *, maximum: int, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value) > maximum
    ):
        raise ValueError("invalid search text")
    return value


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("invalid search range")
    return value


def _score(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("invalid search score")
    selected = float(value)
    if not math.isfinite(selected) or not 0 <= selected <= 100:
        raise ValueError("invalid search score")
    return selected


def _query(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _QUERY_KEYS:
        raise ValueError("invalid search query")
    location = _text(value["location"], maximum=500)
    strategy = _text(value["strategy"], maximum=128, nullable=True)
    property_type = _text(value["property_type"], maximum=128, nullable=True)
    price_min = _optional_integer(value["price_min"])
    price_max = _optional_integer(value["price_max"])
    size_min = _optional_integer(value["size_min"])
    size_max = _optional_integer(value["size_max"])
    if price_min is not None and price_max is not None and price_min > price_max:
        raise ValueError("invalid search range")
    if size_min is not None and size_max is not None and size_min > size_max:
        raise ValueError("invalid search range")
    raw_sources = value["sources"]
    if not isinstance(raw_sources, list) or not 1 <= len(raw_sources) <= 16:
        raise ValueError("invalid search sources")
    sources = [_text(item, maximum=64) for item in raw_sources]
    if len(set(sources)) != len(sources):
        raise ValueError("invalid search sources")
    normalized: dict[str, object] = {
        "location": location,
        "strategy": strategy,
        "property_type": property_type,
        "price_min": price_min,
        "price_max": price_max,
        "size_min": size_min,
        "size_max": size_max,
        "sources": sources,
    }
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 16_384:
        raise ValueError("invalid search query")
    return normalized


def _utc_text(value: object) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("invalid stored search timestamp")
    return value.astimezone(UTC).isoformat()


class PostgresSearchRepository:
    """Persist one actor's saved searches through one exact admission."""

    def __init__(
        self,
        database: PostgresDatabase,
        admission: AdmissionOutcome,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise TypeError("search repository requires PostgreSQL")
        self._database = database
        self._admission = require_fresh_admission(admission)

    def _require_active_scope(self, method: str) -> TenantContext:
        repositories = current_hosted_request_repositories()
        context = current_context()
        allowed_tools = _METHOD_TOOLS.get(method)
        if (
            repositories is None
            or repositories.admission is not self._admission
            or repositories.require("search") is not self
            or not isinstance(context, TenantContext)
            or context.trusted
            or not context.active
            or allowed_tools is None
            or self._admission.tool_name not in allowed_tools
        ):
            raise SearchPersistenceUnavailable(_UNAVAILABLE)
        comparisons = (
            (context.workspace_id, self._admission.workspace_public_id),
            (context.actor_id, self._admission.actor_user_id),
            (context.session_id, self._admission.session_id),
        )
        if any(
            not left
            or not right
            or not hmac.compare_digest(left, right)
            for left, right in comparisons
        ):
            raise SearchPersistenceUnavailable(_UNAVAILABLE)
        return context

    def _decode_row(self, row: object) -> dict[str, object]:
        if not isinstance(row, tuple) or len(row) != 8:
            raise ValueError("invalid stored search")
        search_id = _uuid(row[0])
        workspace_public_id = _text(row[1], maximum=256) or ""
        owner_id = _uuid(row[2])
        if (
            not hmac.compare_digest(
                workspace_public_id,
                self._admission.workspace_public_id,
            )
            or not hmac.compare_digest(owner_id, self._admission.actor_user_id)
        ):
            raise ValueError("invalid stored search")
        name = _text(row[3], maximum=200)
        query = _query(row[4])
        min_score = _score(row[5])
        created_at = _utc_text(row[6])
        seen_count = row[7]
        if type(seen_count) is not int or seen_count < 0:
            raise ValueError("invalid stored search")
        return {
            "id": search_id,
            "name": name,
            "query": query,
            "min_score": min_score,
            "created_at": created_at,
            "seen_count": seen_count,
        }

    def _save_search(
        self,
        name: str,
        query: dict[str, object],
        min_score: float | None,
    ) -> str:
        self._require_active_scope("save_search")
        selected_name = _text(name, maximum=200)
        selected_query = _query(query)
        selected_score = _score(min_score)
        with self._database.admitted_connection(self._admission) as connection:
            row = connection.execute(
                "WITH inserted AS (INSERT INTO medawarcre.saved_searches("
                "workspace_id,owner_user_id,name,query,min_score,schedule,active) "
                "VALUES (medawarcre.current_workspace_id(),"
                "medawarcre.current_actor_user_id(),%s,%s::jsonb,%s,NULL,true) "
                "RETURNING id,workspace_id,owner_user_id) "
                "SELECT inserted.id,workspace.public_id,inserted.owner_user_id "
                "FROM inserted JOIN medawarcre.workspaces workspace "
                "ON workspace.id=inserted.workspace_id",
                (
                    selected_name,
                    json.dumps(selected_query, allow_nan=False, separators=(",", ":")),
                    selected_score,
                ),
            ).fetchone()
            if not isinstance(row, tuple) or len(row) != 3:
                raise ValueError("invalid stored search")
            search_id = _uuid(row[0])
            workspace_public_id = _text(row[1], maximum=256) or ""
            if (
                not hmac.compare_digest(
                    workspace_public_id,
                    self._admission.workspace_public_id,
                )
                or not hmac.compare_digest(
                    _uuid(row[2]),
                    self._admission.actor_user_id,
                )
            ):
                raise ValueError("invalid stored search")
            self._require_active_scope("save_search")
        return search_id

    async def save_search(
        self,
        name: str,
        query: dict[str, object],
        min_score: float | None = None,
    ) -> str:
        """Persist one actor-private saved search and return its UUID."""
        try:
            self._require_active_scope("save_search")
            result = await _finish_thread_before_cancellation(
                self._save_search,
                name,
                query,
                min_score,
            )
            self._require_active_scope("save_search")
            return result
        except SearchPersistenceUnavailable:
            raise
        except Exception as error:
            raise SearchPersistenceUnavailable(_UNAVAILABLE) from error

    @staticmethod
    def _search_select() -> str:
        return (
            "SELECT search.id,workspace.public_id,search.owner_user_id,search.name,"
            "search.query,search.min_score,search.created_at,"
            "(SELECT count(*) FROM medawarcre.saved_search_seen_matches seen "
            "WHERE seen.workspace_id=search.workspace_id "
            "AND seen.saved_search_id=search.id) "
            "FROM medawarcre.saved_searches search "
            "JOIN medawarcre.workspaces workspace ON workspace.id=search.workspace_id "
        )

    def _get_search(self, search_id: str) -> dict[str, object] | None:
        self._require_active_scope("get_search")
        selected_id = _uuid(search_id)
        with self._database.admitted_connection(self._admission) as connection:
            row = connection.execute(
                self._search_select() + "WHERE search.id=%s",
                (selected_id,),
            ).fetchone()
            result = None if row is None else self._decode_row(row)
            self._require_active_scope("get_search")
        return result

    async def get_search(self, search_id: str) -> dict[str, object] | None:
        """Return one actor-owned saved search or no record."""
        try:
            self._require_active_scope("get_search")
            result = await _finish_thread_before_cancellation(
                self._get_search,
                search_id,
            )
            self._require_active_scope("get_search")
            return result
        except SearchPersistenceUnavailable:
            raise
        except Exception as error:
            raise SearchPersistenceUnavailable(_UNAVAILABLE) from error

    def _list_searches(self) -> list[dict[str, object]]:
        self._require_active_scope("list_searches")
        with self._database.admitted_connection(self._admission) as connection:
            rows = connection.execute(
                self._search_select() + "ORDER BY search.created_at,search.id"
            ).fetchall()
            result = [self._decode_row(row) for row in rows]
            self._require_active_scope("list_searches")
        return result

    async def list_searches(self) -> list[dict[str, object]]:
        """List the exact actor's saved searches."""
        try:
            self._require_active_scope("list_searches")
            result = await _finish_thread_before_cancellation(self._list_searches)
            self._require_active_scope("list_searches")
            return result
        except SearchPersistenceUnavailable:
            raise
        except Exception as error:
            raise SearchPersistenceUnavailable(_UNAVAILABLE) from error

    def _decode_claim_rows(
        self,
        rows: object,
        *,
        allowed_keys: set[str] | None = None,
    ) -> set[str]:
        if not isinstance(rows, list):
            raise ValueError("invalid stored search claims")
        result: set[str] = set()
        for row in rows:
            if not isinstance(row, tuple) or len(row) != 3:
                raise ValueError("invalid stored search claims")
            workspace_public_id = _text(row[0], maximum=256) or ""
            owner_id = _uuid(row[1])
            dedupe_key = _text(row[2], maximum=512) or ""
            if (
                not hmac.compare_digest(
                    workspace_public_id,
                    self._admission.workspace_public_id,
                )
                or not hmac.compare_digest(
                    owner_id,
                    self._admission.actor_user_id,
                )
                or (allowed_keys is not None and dedupe_key not in allowed_keys)
            ):
                raise ValueError("invalid stored search claims")
            result.add(dedupe_key)
        if len(result) != len(rows):
            raise ValueError("invalid stored search claims")
        return result

    def _seen_keys(self, search_id: str) -> set[str]:
        self._require_active_scope("seen_keys")
        selected_id = _uuid(search_id)
        with self._database.admitted_connection(self._admission) as connection:
            rows = connection.execute(
                "SELECT workspace.public_id,seen.owner_user_id,seen.dedupe_key "
                "FROM medawarcre.saved_search_seen_matches seen "
                "JOIN medawarcre.workspaces workspace "
                "ON workspace.id=seen.workspace_id "
                "WHERE seen.saved_search_id=%s "
                "ORDER BY seen.dedupe_key COLLATE \"C\"",
                (selected_id,),
            ).fetchall()
            result = self._decode_claim_rows(rows)
            self._require_active_scope("seen_keys")
        return result

    async def seen_keys(self, search_id: str) -> set[str]:
        """Return source-qualified keys already emitted for one search."""
        try:
            self._require_active_scope("seen_keys")
            result = await _finish_thread_before_cancellation(
                self._seen_keys,
                search_id,
            )
            self._require_active_scope("seen_keys")
            return result
        except SearchPersistenceUnavailable:
            raise
        except Exception as error:
            raise SearchPersistenceUnavailable(_UNAVAILABLE) from error

    @staticmethod
    def _claim_keys(keys: object) -> list[str]:
        if isinstance(keys, (str, bytes, bytearray)) or not isinstance(keys, list):
            raise ValueError("invalid search claims")
        if len(keys) > _MAX_CLAIM_KEYS:
            raise ValueError("invalid search claims")
        selected = sorted({_text(item, maximum=512) or "" for item in keys})
        return selected

    def _claim_unseen(self, search_id: str, keys: list[str]) -> set[str]:
        self._require_active_scope("claim_unseen")
        selected_id = _uuid(search_id)
        selected_keys = self._claim_keys(keys)
        if not selected_keys:
            self._require_active_scope("claim_unseen")
            return set()
        with self._database.admitted_connection(self._admission) as connection:
            rows = connection.execute(
                "WITH target AS ("
                "SELECT workspace_id,id,owner_user_id "
                "FROM medawarcre.saved_searches WHERE id=%s),"
                "input AS (SELECT DISTINCT unnest(%s::text[]) AS dedupe_key),"
                "claimed AS ("
                "INSERT INTO medawarcre.saved_search_seen_matches("
                "workspace_id,owner_user_id,saved_search_id,dedupe_key) "
                "SELECT target.workspace_id,target.owner_user_id,target.id,"
                "input.dedupe_key FROM target CROSS JOIN input "
                "ON CONFLICT DO NOTHING "
                "RETURNING workspace_id,owner_user_id,dedupe_key) "
                "SELECT workspace.public_id,claimed.owner_user_id,"
                "claimed.dedupe_key FROM claimed "
                "JOIN medawarcre.workspaces workspace "
                "ON workspace.id=claimed.workspace_id "
                "ORDER BY claimed.dedupe_key COLLATE \"C\"",
                (selected_id, selected_keys),
            ).fetchall()
            result = self._decode_claim_rows(
                rows,
                allowed_keys=set(selected_keys),
            )
            self._require_active_scope("claim_unseen")
        return result

    async def claim_unseen(self, search_id: str, keys: Iterable[str]) -> set[str]:
        """Atomically claim and return only keys first inserted by this call."""
        try:
            self._require_active_scope("claim_unseen")
            if isinstance(keys, (str, bytes, bytearray)):
                raise ValueError("invalid search claims")
            materialized = list(keys)
            result = await _finish_thread_before_cancellation(
                self._claim_unseen,
                search_id,
                materialized,
            )
            self._require_active_scope("claim_unseen")
            return result
        except SearchPersistenceUnavailable:
            raise
        except Exception as error:
            raise SearchPersistenceUnavailable(_UNAVAILABLE) from error

    async def record_seen(self, search_id: str, keys: Iterable[str]) -> int:
        """Compatibility wrapper returning how many keys this call claimed."""
        return len(await self.claim_unseen(search_id, keys))


__all__ = ["PostgresSearchRepository", "SearchPersistenceUnavailable"]
