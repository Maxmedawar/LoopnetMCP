"""Request-scoped PostgreSQL persistence for the collaborative deal domain."""

from __future__ import annotations

import asyncio
import hmac
import json
import math
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Callable, TypeVar
from uuid import UUID

from cre_mcp.access.context import TenantContext, current_context, resolve_runtime_config
from cre_mcp.access.engine import structured_property_within_territories
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DD_STATUSES, OPS_STATUSES, PIPELINE_STAGE_SET, PIPELINE_STAGES
from cre_mcp.models.execution import DDItem
from cre_mcp.models.listings import Listing
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.domains import (
    current_hosted_request_repositories,
    require_fresh_admission,
)
from cre_mcp.postgres.pool import PostgresDatabase
from cre_mcp.source_rights.output import sanitize_listing, sanitize_payload
from cre_mcp.source_rights.gate import require_source

_UNAVAILABLE = "deal persistence unavailable"
_MAX_ROWS = 5_000
_OPS_CATEGORIES = frozenset({"month_one", "recurring", "lease", "nudge"})
# `numeric(19, 2)` holds 17 integer digits; anything at or beyond this
# overflows the column rather than storing.
_NUMERIC_19_2_LIMIT = 10.0 ** 17
_METHOD_TOOLS = {
    "save_deal": frozenset(
        {
            "save_deal",
            "start_exchange",
            "identify_replacement",
        }
    ),
    # Closed by default: a capability appears here only where its exact
    # production call graph reaches this method. Capabilities whose hosted path
    # takes a composite `*_result` branch are deliberately absent, so the
    # legacy scalar method stays unreachable rather than merely unused.
    "get_deal": frozenset(
        {
            "start_exchange",
            "identify_replacement",
            "ingest_document",
            "build_noi_bridge",
            "deal_truth_report",
            "deal_timeline",
            "list_deal_documents",
        }
    ),
    "record_outcome": frozenset({"record_deal_outcome"}),
    "get_outcomes": frozenset({"backtest_score"}),
    "replace_diligence": frozenset({"due_diligence_plan"}),
    "replace_operating": frozenset({"operating_playbook"}),
    "assign_deal": frozenset({"assign_deal"}),
    "unaccounted_deals": frozenset({"unassigned_deals"}),
    "add_to_pipeline_result": frozenset({"add_to_pipeline"}),
    "update_stage_result": frozenset({"update_deal_stage"}),
    "list_pipeline": frozenset({"list_pipeline"}),
    "list_deals": frozenset({"list_deals"}),
    "add_investor": frozenset({"add_investor"}),
    "list_investors": frozenset({"list_investors"}),
    "record_commitment": frozenset({"record_commitment"}),
    "create_exchange_result": frozenset({"start_exchange"}),
    "get_exchange_record": frozenset({"exchange_status"}),
    "identify_exchange_replacement_result": frozenset({"identify_replacement"}),
    "record_ic_decision": frozenset({"record_ic_decision"}),
    "log_deal_event": frozenset({"log_deal_event"}),
    "get_deal_timeline": frozenset({"deal_timeline"}),
    "ic_scorecard": frozenset({"ic_scorecard"}),
}

T = TypeVar("T")


class DealPersistenceUnavailable(RuntimeError):
    """The exact hosted deal persistence boundary cannot complete safely."""


class DealRuleViolation(ValueError):
    """A safe, authorized deal-domain rule rejected the requested mutation."""


async def _finish_thread_before_cancellation(function: Callable[..., T], *args: Any) -> T:
    """Keep the database worker inside the request lease until it stops."""
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


def _text(
    value: object,
    *,
    maximum: int,
    label: str,
    nullable: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value) > maximum
    ):
        raise ValueError(f"invalid {label}")
    return value


def _optional_text(value: object, *, maximum: int, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"invalid {label}")
    selected = value.strip()
    if not selected:
        return None
    return _text(selected, maximum=maximum, label=label)


def _uuid(value: object, *, label: str) -> str:
    if not isinstance(value, (str, UUID)):
        raise ValueError(f"invalid {label}")
    try:
        selected = str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(f"invalid {label}") from error
    if isinstance(value, str) and value != selected:
        raise ValueError(f"invalid {label}")
    return selected


def _number(
    value: object,
    *,
    label: str,
    nullable: bool = True,
    minimum: float | None = None,
    maximum: float | None = None,
    strictly_positive: bool = False,
) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"invalid {label}")
    selected = float(value)
    if not math.isfinite(selected):
        raise ValueError(f"invalid {label}")
    if strictly_positive and selected <= 0:
        raise ValueError(f"invalid {label}")
    if minimum is not None and selected < minimum:
        raise ValueError(f"invalid {label}")
    if maximum is not None and selected > maximum:
        raise ValueError(f"invalid {label}")
    return selected


def _boolean(value: object, *, label: str, nullable: bool = False) -> bool | None:
    if value is None and nullable:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"invalid {label}")
    return value


def _date(value: object, *, label: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if isinstance(value, datetime):
        raise ValueError(f"invalid {label}")
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or value != value.strip():
        raise ValueError(f"invalid {label}")
    try:
        selected = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"invalid {label}") from error
    if value != selected.isoformat():
        raise ValueError(f"invalid {label}")
    return value


def _timestamp(value: object, *, label: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"invalid {label}") from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"invalid {label}")
    if parsed.tzinfo is None:
        raise ValueError(f"invalid {label}")
    return parsed.astimezone(UTC).isoformat()


def _due_timestamp(value: object, *, label: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if isinstance(value, datetime):
        return _timestamp(value, label=label)
    if isinstance(value, date):
        selected = value
    elif isinstance(value, str) and value == value.strip():
        try:
            selected = date.fromisoformat(value)
        except ValueError:
            return _timestamp(value, label=label)
    else:
        raise ValueError(f"invalid {label}")
    return datetime.combine(selected, datetime.min.time(), tzinfo=UTC).isoformat()


def _json_object(value: object, *, maximum: int, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"invalid {label}")
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}") from error
    if len(encoded.encode("utf-8")) > maximum or not isinstance(decoded, dict):
        raise ValueError(f"invalid {label}")
    return decoded


def _denormalized_title(value: object) -> str:
    """Bound the write-only ``title`` column without rejecting the listing.

    ``title`` and ``asking_price`` are denormalized copies that the application
    role cannot select; every read projects the authoritative value out of the
    bounded listing JSON. Real source mappers emit names longer than the column
    bound, so this normalizes instead of aborting an otherwise valid save.
    """
    selected = value.strip() if isinstance(value, str) else ""
    return (selected[:500].strip() or "Untitled listing")


def _denormalized_price(value: object) -> float | None:
    """Return a strictly positive in-domain price, or NULL for anything else.

    Source mappers legitimately produce ``0``, occasionally negative values,
    and unbounded magnitudes parsed from provider text. The column requires
    ``> 0`` and is ``numeric(19, 2)``, so anything at or beyond its 17
    integer digits must become NULL rather than overflow and reject a listing
    the listing JSON still records exactly.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    selected = float(value)
    if not math.isfinite(selected) or not 0 < selected < _NUMERIC_19_2_LIMIT:
        return None
    return selected


def _deal_ref(value: object) -> tuple[str, str, str]:
    selected = _text(value, maximum=578, label="deal identifier") or ""
    source, separator, source_id = selected.partition(":")
    if not separator:
        raise ValueError("invalid deal identifier")
    source = _text(source, maximum=64, label="deal identifier") or ""
    source_id = _text(source_id, maximum=512, label="deal identifier") or ""
    return selected, source, source_id


def _stage(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid pipeline stage")
    selected = value.strip().casefold()
    if selected not in PIPELINE_STAGE_SET:
        raise ValueError(f"stage must be one of {', '.join(PIPELINE_STAGES)}")
    return selected


def _row_limit(rows: object, *, label: str) -> list[tuple[Any, ...]]:
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
        raise ValueError(f"invalid stored {label}")
    if any(not isinstance(row, tuple) for row in rows):
        raise ValueError(f"invalid stored {label}")
    return rows


class PostgresDealRepository:
    """Persist collaborative deal state through one exact admitted request."""

    def __init__(
        self,
        database: PostgresDatabase,
        admission: AdmissionOutcome,
        *,
        config: CreConfig | None = None,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise TypeError("deal repository requires PostgreSQL")
        self._database = database
        self._admission = require_fresh_admission(admission)
        self._config = resolve_runtime_config(config)

    def _require_active_scope(self, method: str) -> TenantContext:
        repositories = current_hosted_request_repositories()
        context = current_context()
        allowed_tools = _METHOD_TOOLS.get(method)
        if (
            repositories is None
            or repositories.admission is not self._admission
            or repositories.require("deal") is not self
            or not isinstance(context, TenantContext)
            or context.trusted
            or not context.active
            or allowed_tools is None
            or self._admission.tool_name not in allowed_tools
        ):
            raise DealPersistenceUnavailable(_UNAVAILABLE)
        comparisons = (
            (context.workspace_id, self._admission.workspace_public_id),
            (context.actor_id, self._admission.actor_user_id),
            (context.session_id, self._admission.session_id),
        )
        if any(
            not left or not right or not hmac.compare_digest(left, right)
            for left, right in comparisons
        ):
            raise DealPersistenceUnavailable(_UNAVAILABLE)
        return context

    def _workspace(self, value: object) -> str:
        selected = _text(value, maximum=256, label="stored workspace") or ""
        if not hmac.compare_digest(selected, self._admission.workspace_public_id):
            raise ValueError("invalid stored workspace")
        return selected

    def _authorized_deal_ref(self, value: object) -> tuple[str, str, str]:
        selected, source, source_id = _deal_ref(value)
        require_source(source, config=self._config)
        return selected, source, source_id

    def _rights_evidence(self, source: str) -> tuple[str, str]:
        """Return the live rights provenance to stamp on a mutating write.

        Every deal row must carry the provenance verified at write time, and
        RLS refuses an update that would leave it absent. Re-deriving it here
        keeps a row created before that rule — or by an administrator — usable
        without ever accepting a deal whose source is not currently authorized:
        `require_source` still raises when the live registry says no.
        """
        rights = require_source(source, config=self._config)
        if rights is None or rights.evidence_verified_on is None:
            raise ValueError("listing source has no verified hosted rights")
        return rights.source_id, rights.evidence_verified_on.isoformat()

    async def _call(self, method: str, function: Callable[..., T], *args: Any) -> T:
        try:
            self._require_active_scope(method)
            result = await _finish_thread_before_cancellation(function, *args)
            self._require_active_scope(method)
            return result
        except DealRuleViolation:
            raise
        except DealPersistenceUnavailable:
            raise
        except Exception as error:
            raise DealPersistenceUnavailable(_UNAVAILABLE) from error

    @staticmethod
    def _deal_lookup_sql(alias: str = "deal") -> str:
        return (
            f"FROM medawarcre.deals {alias} "
            f"JOIN medawarcre.workspaces workspace ON workspace.id={alias}.workspace_id "
            f"WHERE {alias}.source=%s AND {alias}.source_record_id=%s"
        )

    def _decode_listing(self, value: object, source: object, source_id: object) -> dict[str, Any]:
        selected_source = _text(source, maximum=64, label="stored source") or ""
        selected_source_id = _text(source_id, maximum=512, label="stored source record") or ""
        require_source(selected_source, config=self._config)
        payload = _json_object(value, maximum=262_144, label="stored listing")
        listing = Listing.model_validate(payload)
        if listing.source != selected_source or listing.source_id != selected_source_id:
            raise ValueError("invalid stored listing")
        return listing.model_dump(mode="json")

    def _decode_dd_row(self, row: tuple[Any, ...], *, expected_deal: str) -> dict[str, Any]:
        if len(row) != 7:
            raise ValueError("invalid stored diligence item")
        self._workspace(row[0])
        deal_id, _, _ = self._authorized_deal_ref(f"{row[1]}:{row[2]}")
        if not hmac.compare_digest(deal_id, expected_deal):
            raise ValueError("invalid stored diligence item")
        payload = _json_object(row[3], maximum=65_536, label="stored diligence item")
        payload["status"] = _text(row[4], maximum=32, label="stored diligence status")
        payload["deadline"] = _date(row[5], label="stored diligence deadline")
        if _text(row[6], maximum=128, label="stored diligence key") != payload.get("key"):
            raise ValueError("invalid stored diligence item")
        return DDItem.model_validate(payload).model_dump(mode="json")

    def _get_dd_rows(self, connection: Any, source: str, source_id: str) -> list[tuple[Any, ...]]:
        rows = connection.execute(
            "SELECT workspace.public_id,deal.source,deal.source_record_id,item.item_data,"
            "item.status,item.deadline,item.item_key "
            "FROM medawarcre.deal_dd_items item "
            "JOIN medawarcre.deals deal ON deal.workspace_id=item.workspace_id "
            "AND deal.id=item.deal_id "
            "JOIN medawarcre.workspaces workspace ON workspace.id=item.workspace_id "
            "WHERE deal.source=%s AND deal.source_record_id=%s "
            "ORDER BY item.deadline,item.item_key COLLATE \"C\"",
            (source, source_id),
        ).fetchall()
        return _row_limit(rows, label="diligence items")

    @staticmethod
    def _write_deal(
        connection: Any,
        listing: Listing,
        listing_payload: dict[str, Any],
        score: float | None,
        grade: str | None,
        strategy: str | None,
        stage: str | None,
        rights_source_id: str,
        rights_verified_on: str,
    ) -> tuple[Any, ...]:
        """Upsert without granting SELECT on private deal columns.

        PostgreSQL treats ``excluded.column`` references in ``ON CONFLICT DO
        UPDATE`` as reads of the target table.  A retrying update/insert/update
        sequence keeps the operation race-safe while preserving the app role's
        deliberately narrow column-level SELECT grant.
        """
        listing_json = json.dumps(
            listing_payload,
            allow_nan=False,
            separators=(",", ":"),
        )
        update_sql = (
            "UPDATE medawarcre.deals SET title=%s,listing=%s::jsonb,asking_price=%s,"
            "stage=COALESCE(%s,stage),score=COALESCE(%s,score),"
            "grade=COALESCE(%s,grade),strategy=COALESCE(%s,strategy),"
            "source_rights_id=%s,source_rights_verified_on=%s,"
            "updated_by_user_id=medawarcre.current_actor_user_id(),"
            "updated_at=statement_timestamp() "
            "WHERE source=%s AND source_record_id=%s "
            "RETURNING id,workspace_id,source,source_record_id"
        )
        update_parameters = (
            _denormalized_title(listing.name),
            listing_json,
            _denormalized_price(listing.price_usd),
            stage,
            score,
            grade,
            strategy,
            rights_source_id,
            rights_verified_on,
            listing.source,
            listing.source_id,
        )
        row = connection.execute(update_sql, update_parameters).fetchone()
        if row is None:
            row = connection.execute(
                "INSERT INTO medawarcre.deals("
                "workspace_id,source,source_record_id,title,listing,asking_price,"
                "stage,score,grade,strategy,source_rights_id,source_rights_verified_on,"
                "created_by_user_id,updated_by_user_id) VALUES ("
                "medawarcre.current_workspace_id(),%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,"
                "medawarcre.current_actor_user_id(),medawarcre.current_actor_user_id()) "
                "ON CONFLICT (workspace_id,source,source_record_id) DO NOTHING "
                "RETURNING id,workspace_id,source,source_record_id",
                (
                    listing.source,
                    listing.source_id,
                    _denormalized_title(listing.name),
                    listing_json,
                    _denormalized_price(listing.price_usd),
                    stage or "lead",
                    score,
                    grade,
                    strategy,
                    rights_source_id,
                    rights_verified_on,
                ),
            ).fetchone()
        if row is None:
            row = connection.execute(update_sql, update_parameters).fetchone()
        if not isinstance(row, tuple) or len(row) != 4:
            raise ValueError("invalid stored deal")
        return row

    def _save_deal(
        self,
        listing_payload: dict[str, Any],
        score: float | None,
        grade: str | None,
        strategy: str | None,
        rights_source_id: str,
        rights_verified_on: str,
    ) -> str:
        self._require_active_scope("save_deal")
        listing = Listing.model_validate(listing_payload)
        deal_id = f"{listing.source}:{listing.source_id}"
        with self._database.admitted_connection(self._admission) as connection:
            row = self._write_deal(
                connection,
                listing,
                listing_payload,
                score,
                grade,
                strategy,
                None,
                rights_source_id,
                rights_verified_on,
            )
            workspace = connection.execute(
                "SELECT public_id FROM medawarcre.workspaces WHERE id=%s",
                (row[1],),
            ).fetchone()
            if not isinstance(workspace, tuple) or len(workspace) != 1:
                raise ValueError("invalid stored deal")
            self._workspace(workspace[0])
            returned, _, _ = self._authorized_deal_ref(f"{row[2]}:{row[3]}")
            if not hmac.compare_digest(returned, deal_id):
                raise ValueError("invalid stored deal")
            self._require_active_scope("save_deal")
        return deal_id

    async def save_deal(
        self,
        listing: Listing,
        *,
        score: float | None = None,
        grade: str | None = None,
        strategy: str | None = None,
    ) -> str:
        """Save or refresh one source-qualified workspace deal."""
        if not isinstance(listing, Listing):
            raise ValueError("invalid listing")
        sanitized = sanitize_listing(listing, purpose="storage", config=self._config)
        rights = require_source(sanitized.source, config=self._config)
        if rights is None or rights.evidence_verified_on is None:
            raise ValueError("listing source has no verified hosted rights")
        _, _, _ = self._authorized_deal_ref(f"{sanitized.source}:{sanitized.source_id}")
        selected_score = _number(score, label="deal score", minimum=0, maximum=100)
        selected_grade = _optional_text(grade, maximum=64, label="deal grade")
        selected_strategy = _optional_text(strategy, maximum=128, label="deal strategy")
        payload = _json_object(
            sanitized.model_dump(mode="json"),
            maximum=262_144,
            label="listing",
        )
        return await self._call(
            "save_deal",
            self._save_deal,
            payload,
            selected_score,
            selected_grade,
            selected_strategy,
            rights.source_id,
            rights.evidence_verified_on.isoformat(),
        )

    def _notes(self, connection: Any, deal_uuid: object, deal_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT workspace.public_id,deal.source,deal.source_record_id,note.body,"
            "note.stage,note.created_at "
            "FROM medawarcre.deal_notes note "
            "JOIN medawarcre.deals deal ON deal.workspace_id=note.workspace_id "
            "AND deal.id=note.deal_id "
            "JOIN medawarcre.workspaces workspace ON workspace.id=note.workspace_id "
            "WHERE note.deal_id=%s ORDER BY note.created_at,note.id",
            (deal_uuid,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in _row_limit(rows, label="deal notes"):
            if len(row) != 6:
                raise ValueError("invalid stored deal note")
            self._workspace(row[0])
            parent, _, _ = self._authorized_deal_ref(f"{row[1]}:{row[2]}")
            if not hmac.compare_digest(parent, deal_id):
                raise ValueError("invalid stored deal note")
            result.append(
                {
                    "text": _text(row[3], maximum=8_000, label="stored deal note"),
                    "stage": _stage(row[4]),
                    "created_at": _timestamp(row[5], label="stored deal note timestamp"),
                }
            )
        return result

    def _get_deal(self, deal_id: str, source: str, source_id: str) -> dict[str, Any] | None:
        context = self._require_active_scope("get_deal")
        with self._database.admitted_connection(self._admission) as connection:
            row = connection.execute(
                "SELECT workspace.public_id,deal.source,deal.source_record_id,deal.listing "
                + self._deal_lookup_sql(),
                (source, source_id),
            ).fetchone()
            if row is None:
                result = None
            else:
                if not isinstance(row, tuple) or len(row) != 4:
                    raise ValueError("invalid stored deal")
                self._workspace(row[0])
                returned, _, _ = self._authorized_deal_ref(f"{row[1]}:{row[2]}")
                if not hmac.compare_digest(returned, deal_id):
                    raise ValueError("invalid stored deal")
                listing = self._decode_listing(row[3], row[1], row[2])
                if (
                    context.profile in TERRITORY_LIMITED
                    and not structured_property_within_territories(
                        listing,
                        context.territories,
                    )
                ):
                    raise DealPersistenceUnavailable(_UNAVAILABLE)
                tool = self._admission.tool_name
                if tool in {
                    "start_exchange",
                    "exchange_status",
                    "identify_replacement",
                    "build_noi_bridge",
                    "deal_truth_report",
                }:
                    projected = {
                        "price": listing.get("price"),
                        "price_usd": listing.get("price_usd"),
                        "address": listing.get("address"),
                        "city": listing.get("city"),
                        "state": listing.get("state"),
                        "zip_code": listing.get("zip_code"),
                    }
                    result = {"deal_id": returned, "listing": projected}
                elif tool in {"deal_timeline", "list_deal_documents"}:
                    # Location only: these capabilities need an authoritative
                    # `SubjectProperty` for the result territory policy and
                    # nothing more, so no price is projected.
                    projected = {
                        key: listing.get(key)
                        for key in ("address", "city", "state", "zip_code")
                    }
                    result = {"deal_id": returned, "listing": projected}
                else:
                    result = {"deal_id": returned}
            self._require_active_scope("get_deal")
        return sanitize_payload(result, config=self._config)

    async def get_deal(self, deal_id: str) -> dict[str, Any] | None:
        """Return one workspace deal and its current diligence plan."""
        selected, source, source_id = self._authorized_deal_ref(deal_id)
        return await self._call("get_deal", self._get_deal, selected, source, source_id)

    def _summary_rows(
        self,
        connection: Any,
        stage: str | None,
        restricted: bool,
        pipeline_order: bool,
    ) -> list[tuple[Any, ...]]:
        where = ""
        parameters: tuple[Any, ...] = ()
        if stage is not None:
            where = "WHERE deal.stage=%s"
            parameters = (stage,)
        order = " ".join(
            f"WHEN '{value}' THEN {index}" for index, value in enumerate(PIPELINE_STAGES)
        )
        listing_projection = (
            "jsonb_build_object('source',deal.source,'source_id',deal.source_record_id,"
            "'name',deal.listing->'name','address',deal.listing->'address',"
            "'city',deal.listing->'city','state',deal.listing->'state',"
            "'zip_code',deal.listing->'zip_code','price_usd',deal.listing->'price_usd',"
            "'url',deal.listing->'url')"
            if restricted
            else "deal.listing"
        )
        rows = connection.execute(
            "SELECT workspace.public_id,deal.id,deal.source,deal.source_record_id,"
            + listing_projection + ",deal.stage,deal.score,deal.grade,deal.strategy,"
            "deal.accountability_owner,deal.next_action,deal.next_action_due,"
            "deal.created_at,deal.updated_at,count(item.item_key),"
            "count(item.item_key) FILTER (WHERE item.status='complete') "
            "FROM medawarcre.deals deal "
            "JOIN medawarcre.workspaces workspace ON workspace.id=deal.workspace_id "
            "LEFT JOIN medawarcre.deal_dd_items item ON item.workspace_id=deal.workspace_id "
            "AND item.deal_id=deal.id "
            f"{where} GROUP BY workspace.public_id,deal.id "
            + (
                f"ORDER BY CASE deal.stage {order} ELSE 999 END,"
                "deal.updated_at DESC,deal.source COLLATE \"C\",deal.source_record_id COLLATE \"C\""
                if pipeline_order
                else "ORDER BY deal.updated_at DESC,deal.source COLLATE \"C\",deal.source_record_id COLLATE \"C\""
            ),
            parameters,
        ).fetchall()
        return _row_limit(rows, label="deals")

    def _decode_summary(
        self,
        connection: Any,
        row: tuple[Any, ...],
        *,
        include_notes: bool,
        restricted: bool,
    ) -> dict[str, Any]:
        if len(row) != 16:
            raise ValueError("invalid stored deal")
        self._workspace(row[0])
        deal_id, _, _ = self._authorized_deal_ref(f"{row[2]}:{row[3]}")
        if restricted:
            # The restricted projection is a strict subset of the stored
            # listing, so it must not be bounded tighter than the write path
            # accepts: a listing this repository already stored would otherwise
            # deny the whole workspace's list for territory-limited profiles.
            listing = _json_object(row[4], maximum=262_144, label="stored deal projection")
            if listing.get("source") != row[2] or listing.get("source_id") != row[3]:
                raise ValueError("invalid stored deal projection")
            require_source(str(row[2]), config=self._config)
            notes: list[dict[str, Any]] = []
        else:
            listing = self._decode_listing(row[4], row[2], row[3])
            notes = self._notes(connection, row[1], deal_id)
        total, complete = row[14], row[15]
        if type(total) is not int or type(complete) is not int or not 0 <= complete <= total:
            raise ValueError("invalid stored deal")
        result = {
            "deal_id": deal_id,
            "source": row[2],
            "source_id": row[3],
            "name": listing.get("name"),
            "address": listing.get("address"),
            "city": listing.get("city"),
            "state": listing.get("state"),
            "zip_code": listing.get("zip_code"),
            "price_usd": listing.get("price_usd"),
            "stage": _stage(row[5]),
            "score": _number(row[6], label="stored deal score", minimum=0, maximum=100),
            "grade": _optional_text(row[7], maximum=64, label="stored deal grade"),
            "strategy": _optional_text(row[8], maximum=128, label="stored deal strategy"),
            "last_note": notes[-1] if notes else None,
            "created_at": _timestamp(row[12], label="stored deal timestamp"),
            "updated_at": _timestamp(row[13], label="stored deal timestamp"),
            "dd_total": total,
            "dd_complete": complete,
        }
        if include_notes:
            result["url"] = listing.get("url")
            result["notes"] = notes
        return result

    def _list_summaries(self, method: str, stage: str | None, include_notes: bool) -> list[dict[str, Any]]:
        context = self._require_active_scope(method)
        restricted = context.profile in TERRITORY_LIMITED
        with self._database.admitted_connection(
            self._admission, snapshot=True
        ) as connection:
            result = []
            for row in self._summary_rows(
                connection,
                stage,
                restricted,
                method == "list_pipeline",
            ):
                decoded = self._decode_summary(
                    connection,
                    row,
                    include_notes=include_notes,
                    restricted=restricted,
                )
                if restricted and not structured_property_within_territories(
                    decoded,
                    context.territories,
                ):
                    continue
                result.append(decoded)
            self._require_active_scope(method)
        return sanitize_payload(result, config=self._config)

    async def list_deals(self) -> list[dict[str, Any]]:
        """Return compact workspace-deal summaries, newest first."""
        return await self._call("list_deals", self._list_summaries, "list_deals", None, False)

    async def list_pipeline(self, stage: str | None = None) -> list[dict[str, Any]]:
        """Return pipeline rows on the established deterministic stage order."""
        selected = _stage(stage) if stage is not None else None
        return await self._call(
            "list_pipeline",
            self._list_summaries,
            "list_pipeline",
            selected,
            True,
        )

    def _update_stage(
        self,
        deal_id: str,
        source: str,
        source_id: str,
        stage: str,
        note: str | None,
    ) -> bool:
        self._require_active_scope("update_stage")
        with self._database.admitted_connection(self._admission) as connection:
            rights_source_id, rights_verified_on = self._rights_evidence(source)
            row = connection.execute(
                "UPDATE medawarcre.deals SET stage=%s,"
                "source_rights_id=%s,source_rights_verified_on=%s,"
                "updated_by_user_id=medawarcre.current_actor_user_id(),"
                "updated_at=statement_timestamp() "
                "WHERE source=%s AND source_record_id=%s "
                "RETURNING id,workspace_id,source,source_record_id",
                (stage, rights_source_id, rights_verified_on, source, source_id),
            ).fetchone()
            if row is None:
                result = False
            else:
                if not isinstance(row, tuple) or len(row) != 4:
                    raise ValueError("invalid stored deal")
                returned, _, _ = self._authorized_deal_ref(f"{row[2]}:{row[3]}")
                if not hmac.compare_digest(returned, deal_id):
                    raise ValueError("invalid stored deal")
                if note is not None:
                    connection.execute(
                        "INSERT INTO medawarcre.deal_notes("
                        "workspace_id,deal_id,author_user_id,body,stage) "
                        "VALUES (%s,%s,medawarcre.current_actor_user_id(),%s,%s)",
                        (row[1], row[0], note, stage),
                    )
                result = True
            self._require_active_scope("update_stage")
        return result

    async def update_stage(self, deal_id: str, stage: str, note: str | None = None) -> bool:
        """Atomically move a deal and append its optional historic stage note."""
        selected_id, source, source_id = self._authorized_deal_ref(deal_id)
        selected_stage = _stage(stage)
        selected_note = _optional_text(note, maximum=8_000, label="deal note")
        return await self._call(
            "update_stage",
            self._update_stage,
            selected_id,
            source,
            source_id,
            selected_stage,
            selected_note,
        )

    def _pipeline_row(
        self,
        connection: Any,
        *,
        source: str,
        source_id: str,
        method: str,
    ) -> dict[str, Any]:
        context = self._require_active_scope(method)
        restricted = context.profile in TERRITORY_LIMITED
        for row in self._summary_rows(connection, None, restricted, True):
            if row[2] == source and row[3] == source_id:
                decoded = self._decode_summary(
                    connection,
                    row,
                    include_notes=True,
                    restricted=restricted,
                )
                if restricted and not structured_property_within_territories(
                    decoded,
                    context.territories,
                ):
                    raise DealPersistenceUnavailable(_UNAVAILABLE)
                return decoded
        raise ValueError("invalid stored deal")

    def _add_to_pipeline_result(
        self,
        listing_payload: dict[str, Any],
        score: float | None,
        grade: str | None,
        strategy: str | None,
        stage: str,
        note: str | None,
        rights_source_id: str,
        rights_verified_on: str,
    ) -> dict[str, Any]:
        method = "add_to_pipeline_result"
        self._require_active_scope(method)
        listing = Listing.model_validate(listing_payload)
        with self._database.admitted_connection(self._admission) as connection:
            row = self._write_deal(
                connection,
                listing,
                listing_payload,
                score,
                grade,
                strategy,
                stage,
                rights_source_id,
                rights_verified_on,
            )
            if note is not None:
                connection.execute(
                    "INSERT INTO medawarcre.deal_notes("
                    "workspace_id,deal_id,author_user_id,body,stage) "
                    "VALUES (%s,%s,medawarcre.current_actor_user_id(),%s,%s)",
                    (row[1], row[0], note, stage),
                )
            result = self._pipeline_row(
                connection,
                source=listing.source,
                source_id=listing.source_id,
                method=method,
            )
            self._require_active_scope(method)
        return result

    async def add_to_pipeline_result(
        self,
        listing: Listing,
        *,
        score: float | None = None,
        grade: str | None = None,
        strategy: str | None = None,
        stage: str = "lead",
        note: str | None = None,
    ) -> dict[str, Any]:
        """Atomically save, stage, annotate, and return one pipeline row."""
        if not isinstance(listing, Listing):
            raise ValueError("invalid listing")
        sanitized = sanitize_listing(listing, purpose="storage", config=self._config)
        rights = require_source(sanitized.source, config=self._config)
        if rights is None or rights.evidence_verified_on is None:
            raise ValueError("listing source has no verified hosted rights")
        payload = _json_object(
            sanitized.model_dump(mode="json"),
            maximum=262_144,
            label="listing",
        )
        return await self._call(
            "add_to_pipeline_result",
            self._add_to_pipeline_result,
            payload,
            _number(score, label="deal score", minimum=0, maximum=100),
            _optional_text(grade, maximum=64, label="deal grade"),
            _optional_text(strategy, maximum=128, label="deal strategy"),
            _stage(stage),
            _optional_text(note, maximum=8_000, label="deal note"),
            rights.source_id,
            rights.evidence_verified_on.isoformat(),
        )

    def _update_stage_result(
        self,
        source: str,
        source_id: str,
        stage: str,
        note: str | None,
    ) -> dict[str, Any] | None:
        method = "update_stage_result"
        self._require_active_scope(method)
        with self._database.admitted_connection(self._admission) as connection:
            rights_source_id, rights_verified_on = self._rights_evidence(source)
            row = connection.execute(
                "UPDATE medawarcre.deals SET stage=%s,"
                "source_rights_id=%s,source_rights_verified_on=%s,"
                "updated_by_user_id=medawarcre.current_actor_user_id(),"
                "updated_at=statement_timestamp() WHERE source=%s AND source_record_id=%s "
                "RETURNING id,workspace_id",
                (stage, rights_source_id, rights_verified_on, source, source_id),
            ).fetchone()
            if row is None:
                result = None
            else:
                if not isinstance(row, tuple) or len(row) != 2:
                    raise ValueError("invalid stored deal")
                if note is not None:
                    connection.execute(
                        "INSERT INTO medawarcre.deal_notes("
                        "workspace_id,deal_id,author_user_id,body,stage) "
                        "VALUES (%s,%s,medawarcre.current_actor_user_id(),%s,%s)",
                        (row[1], row[0], note, stage),
                    )
                result = self._pipeline_row(
                    connection,
                    source=source,
                    source_id=source_id,
                    method=method,
                )
            self._require_active_scope(method)
        return result

    async def update_stage_result(
        self,
        deal_id: str,
        stage: str,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        """Atomically move, annotate, and return one pipeline row."""
        _, source, source_id = self._authorized_deal_ref(deal_id)
        return await self._call(
            "update_stage_result",
            self._update_stage_result,
            source,
            source_id,
            _stage(stage),
            _optional_text(note, maximum=8_000, label="deal note"),
        )

    def _assign_deal(
        self,
        deal_id: str,
        source: str,
        source_id: str,
        owner: str | None,
        next_action: str | None,
        next_action_due: str | None,
        owner_supplied: bool,
        action_supplied: bool,
        due_supplied: bool,
    ) -> dict[str, Any] | None:
        self._require_active_scope("assign_deal")
        rights_source_id, rights_verified_on = self._rights_evidence(source)
        sets = [
            "updated_by_user_id=medawarcre.current_actor_user_id()",
            "updated_at=statement_timestamp()",
            "source_rights_id=%s",
            "source_rights_verified_on=%s",
        ]
        parameters: list[Any] = [rights_source_id, rights_verified_on]
        if owner_supplied:
            sets.append("accountability_owner=%s")
            parameters.append(owner)
        if action_supplied:
            sets.append("next_action=%s")
            parameters.append(next_action)
        if due_supplied:
            sets.append("next_action_due=%s")
            parameters.append(next_action_due)
        parameters.extend((source, source_id))
        with self._database.admitted_connection(self._admission) as connection:
            row = connection.execute(
                "UPDATE medawarcre.deals SET " + ",".join(sets) +
                " WHERE source=%s AND source_record_id=%s RETURNING id,workspace_id,"
                "source,source_record_id,stage,accountability_owner,next_action,"
                "next_action_due,updated_at",
                tuple(parameters),
            ).fetchone()
            if row is None:
                result = None
            else:
                if not isinstance(row, tuple) or len(row) != 9:
                    raise ValueError("invalid stored accountability")
                public = connection.execute(
                    "SELECT public_id FROM medawarcre.workspaces WHERE id=%s",
                    (row[1],),
                ).fetchone()
                if not isinstance(public, tuple) or len(public) != 1:
                    raise ValueError("invalid stored accountability")
                self._workspace(public[0])
                returned, _, _ = self._authorized_deal_ref(f"{row[2]}:{row[3]}")
                if not hmac.compare_digest(returned, deal_id):
                    raise ValueError("invalid stored accountability")
                result = {
                    "deal_id": returned,
                    "stage": _stage(row[4]),
                    "owner": _optional_text(row[5], maximum=200, label="stored accountability owner"),
                    "next_action": _optional_text(row[6], maximum=1_000, label="stored next action"),
                    "next_action_due": _timestamp(row[7], label="stored next action due", nullable=True),
                    "updated_at": _timestamp(row[8], label="stored accountability timestamp"),
                }
            self._require_active_scope("assign_deal")
        return result

    async def assign_deal(
        self,
        deal_id: str,
        *,
        owner: str | None = None,
        next_action: str | None = None,
        next_action_due: str | None = None,
    ) -> dict[str, Any] | None:
        """Set supplied accountability fields while retaining omitted fields."""
        selected_id, source, source_id = self._authorized_deal_ref(deal_id)
        selected_owner = _optional_text(owner, maximum=200, label="accountability owner")
        selected_action = _optional_text(next_action, maximum=1_000, label="next action")
        selected_due = _due_timestamp(
            next_action_due,
            label="next action due",
            nullable=True,
        )
        return await self._call(
            "assign_deal",
            self._assign_deal,
            selected_id,
            source,
            source_id,
            selected_owner,
            selected_action,
            selected_due,
            owner is not None,
            next_action is not None,
            next_action_due is not None,
        )

    def _unaccounted_deals(self) -> list[dict[str, Any]]:
        self._require_active_scope("unaccounted_deals")
        with self._database.admitted_connection(self._admission) as connection:
            rows = connection.execute(
                "SELECT workspace.public_id,deal.source,deal.source_record_id,deal.stage,"
                "deal.accountability_owner,deal.next_action,deal.next_action_due,deal.updated_at "
                "FROM medawarcre.deals deal JOIN medawarcre.workspaces workspace "
                "ON workspace.id=deal.workspace_id "
                "WHERE deal.stage NOT IN ('owned','passed') AND "
                "(deal.accountability_owner IS NULL OR deal.next_action IS NULL "
                "OR deal.next_action_due IS NULL) ORDER BY deal.updated_at DESC,"
                "deal.source COLLATE \"C\",deal.source_record_id COLLATE \"C\""
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in _row_limit(rows, label="accountability records"):
                if len(row) != 8:
                    raise ValueError("invalid stored accountability")
                self._workspace(row[0])
                deal_id, _, _ = self._authorized_deal_ref(f"{row[1]}:{row[2]}")
                record = {
                    "deal_id": deal_id,
                    "stage": _stage(row[3]),
                    "owner": _optional_text(row[4], maximum=200, label="stored accountability owner"),
                    "next_action": _optional_text(row[5], maximum=1_000, label="stored next action"),
                    "next_action_due": _timestamp(row[6], label="stored next action due", nullable=True),
                    "updated_at": _timestamp(row[7], label="stored accountability timestamp"),
                }
                record["missing"] = [
                    key for key in ("owner", "next_action", "next_action_due")
                    if record[key] is None
                ]
                result.append(record)
            self._require_active_scope("unaccounted_deals")
        return result

    async def unaccounted_deals(self) -> list[dict[str, Any]]:
        """Return active deals missing an accountability field."""
        return await self._call("unaccounted_deals", self._unaccounted_deals)

    @staticmethod
    def _write_dd_items(
        connection: Any,
        workspace_id: object,
        deal_uuid: object,
        items: list[dict[str, Any]],
    ) -> None:
        active_keys: list[str] = []
        for payload in items:
            item = DDItem.model_validate(payload)
            active_keys.append(item.key)
            connection.execute(
                "INSERT INTO medawarcre.deal_dd_items("
                "workspace_id,deal_id,item_key,item_data,status,deadline,"
                "created_by_user_id,updated_by_user_id) "
                "VALUES (%s,%s,%s,%s::jsonb,%s,%s,"
                "medawarcre.current_actor_user_id(),medawarcre.current_actor_user_id()) "
                "ON CONFLICT (workspace_id,deal_id,item_key) DO UPDATE SET "
                "item_data=excluded.item_data,deadline=excluded.deadline,"
                "updated_by_user_id=medawarcre.current_actor_user_id(),"
                "updated_at=statement_timestamp()",
                (
                    workspace_id,
                    deal_uuid,
                    item.key,
                    json.dumps(payload, allow_nan=False, separators=(",", ":")),
                    item.status,
                    item.deadline.isoformat(),
                ),
            )
        connection.execute(
            "DELETE FROM medawarcre.deal_dd_items "
            "WHERE workspace_id=%s AND deal_id=%s "
            "AND NOT (item_key=ANY(%s::text[]))"
            if active_keys
            else "DELETE FROM medawarcre.deal_dd_items WHERE workspace_id=%s AND deal_id=%s",
            (workspace_id, deal_uuid, active_keys)
            if active_keys
            else (workspace_id, deal_uuid),
        )

    @staticmethod
    def _dd_payloads(items: Iterable[DDItem]) -> list[dict[str, Any]]:
        if isinstance(items, (str, bytes, bytearray)):
            raise ValueError("invalid diligence items")
        materialized = list(items)
        if len(materialized) > 1_000 or any(
            not isinstance(item, DDItem) for item in materialized
        ):
            raise ValueError("invalid diligence items")
        keys = [item.key for item in materialized]
        if len(set(keys)) != len(keys):
            raise ValueError("invalid diligence items")
        return [
            _json_object(
                item.model_dump(mode="json"),
                maximum=65_536,
                label="diligence item",
            )
            for item in materialized
        ]

    def _save_dd_items(
        self,
        deal_id: str,
        source: str,
        source_id: str,
        items: list[dict[str, Any]],
    ) -> bool:
        self._require_active_scope("save_dd_items")
        with self._database.admitted_connection(self._admission) as connection:
            deal = connection.execute(
                "SELECT id,workspace_id FROM medawarcre.deals "
                "WHERE source=%s AND source_record_id=%s FOR UPDATE",
                (source, source_id),
            ).fetchone()
            if deal is None:
                result = False
            else:
                if not isinstance(deal, tuple) or len(deal) != 2:
                    raise ValueError("invalid stored deal")
                self._write_dd_items(connection, deal[1], deal[0], items)
                result = True
            self._require_active_scope("save_dd_items")
        return result

    async def save_dd_items(self, deal_id: str, items: Iterable[DDItem]) -> bool:
        """Replace a diligence plan atomically while retaining recorded statuses."""
        _, source, source_id = self._authorized_deal_ref(deal_id)
        payloads = self._dd_payloads(items)
        return await self._call(
            "save_dd_items",
            self._save_dd_items,
            deal_id,
            source,
            source_id,
            payloads,
        )

    def _replace_diligence(
        self,
        listing_payload: dict[str, Any],
        items: list[dict[str, Any]],
        rights_source_id: str,
        rights_verified_on: str,
    ) -> dict[str, Any]:
        method = "replace_diligence"
        self._require_active_scope(method)
        listing = Listing.model_validate(listing_payload)
        deal_id = f"{listing.source}:{listing.source_id}"
        with self._database.admitted_connection(self._admission) as connection:
            deal = self._write_deal(
                connection,
                listing,
                listing_payload,
                None,
                None,
                None,
                None,
                rights_source_id,
                rights_verified_on,
            )
            self._write_dd_items(connection, deal[1], deal[0], items)
            stored = [
                self._decode_dd_row(row, expected_deal=deal_id)
                for row in self._get_dd_rows(connection, listing.source, listing.source_id)
            ]
            self._require_active_scope(method)
        return {"deal_id": deal_id, "items": stored}

    async def replace_diligence(
        self,
        listing: Listing,
        items: Iterable[DDItem],
    ) -> dict[str, Any]:
        """Atomically save a listing and replace its diligence checklist."""
        if not isinstance(listing, Listing):
            raise ValueError("invalid listing")
        sanitized = sanitize_listing(listing, purpose="storage", config=self._config)
        rights = require_source(sanitized.source, config=self._config)
        if rights is None or rights.evidence_verified_on is None:
            raise ValueError("listing source has no verified hosted rights")
        payload = _json_object(
            sanitized.model_dump(mode="json"),
            maximum=262_144,
            label="listing",
        )
        return await self._call(
            "replace_diligence",
            self._replace_diligence,
            payload,
            self._dd_payloads(items),
            rights.source_id,
            rights.evidence_verified_on.isoformat(),
        )

    def _get_dd_items(self, deal_id: str, source: str, source_id: str) -> list[dict[str, Any]]:
        self._require_active_scope("get_dd_items")
        with self._database.admitted_connection(self._admission) as connection:
            result = [
                self._decode_dd_row(row, expected_deal=deal_id)
                for row in self._get_dd_rows(connection, source, source_id)
            ]
            self._require_active_scope("get_dd_items")
        return result

    async def get_dd_items(self, deal_id: str) -> list[dict[str, Any]]:
        """Return the current diligence rows in deadline order."""
        selected, source, source_id = self._authorized_deal_ref(deal_id)
        return await self._call("get_dd_items", self._get_dd_items, selected, source, source_id)

    @staticmethod
    def _ops_payload(value: object) -> dict[str, Any]:
        payload = _json_object(value, maximum=65_536, label="operating event")
        key = _text(payload.get("key"), maximum=128, label="operating event key")
        category = _text(payload.get("category"), maximum=32, label="operating event category")
        if category not in _OPS_CATEGORIES:
            raise ValueError("invalid operating event category")
        status = payload.get("status", "not_started")
        if status not in OPS_STATUSES:
            raise ValueError("invalid operating event status")
        event_date = _date(payload.get("event_date"), label="operating event date", nullable=True)
        payload["key"] = key
        payload["category"] = category
        payload["status"] = status
        payload["event_date"] = event_date
        return payload

    @staticmethod
    def _write_ops_events(
        connection: Any,
        workspace_id: object,
        deal_uuid: object,
        events: list[dict[str, Any]],
    ) -> None:
        keys: list[str] = []
        for event in events:
            keys.append(event["key"])
            connection.execute(
                "INSERT INTO medawarcre.deal_ops_events("
                "workspace_id,deal_id,event_key,event_data,category,event_date,status,"
                "created_by_user_id,updated_by_user_id) "
                "VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,"
                "medawarcre.current_actor_user_id(),medawarcre.current_actor_user_id()) "
                "ON CONFLICT (workspace_id,deal_id,event_key) DO UPDATE SET "
                "event_data=excluded.event_data,category=excluded.category,"
                "event_date=excluded.event_date,"
                "updated_by_user_id=medawarcre.current_actor_user_id(),"
                "updated_at=statement_timestamp()",
                (
                    workspace_id,
                    deal_uuid,
                    event["key"],
                    json.dumps(event, allow_nan=False, separators=(",", ":")),
                    event["category"],
                    event["event_date"],
                    event["status"],
                ),
            )
        connection.execute(
            "DELETE FROM medawarcre.deal_ops_events "
            "WHERE workspace_id=%s AND deal_id=%s "
            "AND NOT (event_key=ANY(%s::text[]))"
            if keys
            else "DELETE FROM medawarcre.deal_ops_events WHERE workspace_id=%s AND deal_id=%s",
            (workspace_id, deal_uuid, keys)
            if keys
            else (workspace_id, deal_uuid),
        )

    def _ops_payloads(
        self,
        events: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if isinstance(events, (str, bytes, bytearray)):
            raise ValueError("invalid operating events")
        materialized = [self._ops_payload(item) for item in events]
        if len(materialized) > 1_000:
            raise ValueError("invalid operating events")
        keys = [item["key"] for item in materialized]
        if len(set(keys)) != len(keys):
            raise ValueError("invalid operating events")
        return materialized

    def _save_ops_events(
        self,
        source: str,
        source_id: str,
        events: list[dict[str, Any]],
    ) -> bool:
        self._require_active_scope("save_ops_events")
        with self._database.admitted_connection(self._admission) as connection:
            deal = connection.execute(
                "SELECT id,workspace_id FROM medawarcre.deals "
                "WHERE source=%s AND source_record_id=%s FOR UPDATE",
                (source, source_id),
            ).fetchone()
            if deal is None:
                result = False
            else:
                if not isinstance(deal, tuple) or len(deal) != 2:
                    raise ValueError("invalid stored deal")
                self._write_ops_events(connection, deal[1], deal[0], events)
                result = True
            self._require_active_scope("save_ops_events")
        return result

    async def save_ops_events(
        self,
        deal_id: str,
        events: Iterable[dict[str, Any]],
    ) -> bool:
        """Replace an operating calendar atomically while retaining task status."""
        _, source, source_id = self._authorized_deal_ref(deal_id)
        materialized = self._ops_payloads(events)
        return await self._call(
            "save_ops_events",
            self._save_ops_events,
            source,
            source_id,
            materialized,
        )

    def _replace_operating(
        self,
        listing_payload: dict[str, Any],
        events: list[dict[str, Any]],
        rights_source_id: str,
        rights_verified_on: str,
    ) -> dict[str, str]:
        method = "replace_operating"
        self._require_active_scope(method)
        listing = Listing.model_validate(listing_payload)
        deal_id = f"{listing.source}:{listing.source_id}"
        with self._database.admitted_connection(self._admission) as connection:
            deal = self._write_deal(
                connection,
                listing,
                listing_payload,
                None,
                None,
                None,
                None,
                rights_source_id,
                rights_verified_on,
            )
            self._write_ops_events(connection, deal[1], deal[0], events)
            self._require_active_scope(method)
        return {"deal_id": deal_id}

    async def replace_operating(
        self,
        listing: Listing,
        events: Iterable[dict[str, Any]],
    ) -> dict[str, str]:
        """Atomically save a listing and replace its operating calendar."""
        if not isinstance(listing, Listing):
            raise ValueError("invalid listing")
        sanitized = sanitize_listing(listing, purpose="storage", config=self._config)
        rights = require_source(sanitized.source, config=self._config)
        if rights is None or rights.evidence_verified_on is None:
            raise ValueError("listing source has no verified hosted rights")
        payload = _json_object(
            sanitized.model_dump(mode="json"),
            maximum=262_144,
            label="listing",
        )
        return await self._call(
            "replace_operating",
            self._replace_operating,
            payload,
            self._ops_payloads(events),
            rights.source_id,
            rights.evidence_verified_on.isoformat(),
        )

    @staticmethod
    def _outcome(value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("invalid deal outcome")
        closed = _boolean(value.get("closed"), label="closed")
        purchase = _number(
            value.get("purchase_price"),
            label="purchase price",
            strictly_positive=value.get("purchase_price") is not None,
        )
        if closed and purchase is None:
            raise ValueError("purchase_price is required when closed=true")
        notes = _optional_text(value.get("notes"), maximum=8_000, label="outcome notes")
        return {
            "closed": closed,
            "purchase_price": purchase,
            "realized_hold_years": _number(
                value.get("realized_hold_years"),
                label="realized hold years",
                strictly_positive=value.get("realized_hold_years") is not None,
            ),
            "realized_irr": _number(value.get("realized_irr"), label="realized IRR"),
            "realized_equity_multiple": _number(
                value.get("realized_equity_multiple"),
                label="realized equity multiple",
                minimum=0,
            ),
            "went_bad": _boolean(value.get("went_bad"), label="went bad", nullable=True),
            "notes": notes,
        }

    def _decode_outcome(self, row: tuple[Any, ...]) -> dict[str, Any]:
        if len(row) != 15:
            raise ValueError("invalid stored deal outcome")
        self._workspace(row[0])
        deal_id, _, _ = self._authorized_deal_ref(f"{row[1]}:{row[2]}")
        closed = _boolean(row[3], label="stored outcome closed")
        purchase_price = _number(
            row[4],
            label="stored purchase price",
            strictly_positive=row[4] is not None,
        )
        if closed and purchase_price is None:
            raise ValueError("invalid stored deal outcome")
        return {
            "deal_id": deal_id,
            "source": row[1],
            "source_id": row[2],
            "closed": closed,
            "purchase_price": purchase_price,
            "realized_hold_years": _number(row[5], label="stored hold years", strictly_positive=row[5] is not None),
            "realized_irr": _number(row[6], label="stored realized IRR"),
            "realized_equity_multiple": _number(row[7], label="stored equity multiple", minimum=0),
            "went_bad": _boolean(row[8], label="stored went bad", nullable=True),
            "notes": _optional_text(row[9], maximum=8_000, label="stored outcome notes"),
            "predicted_score": _number(row[10], label="stored predicted score", minimum=0, maximum=100),
            "predicted_grade": _optional_text(row[11], maximum=64, label="stored predicted grade"),
            "predicted_strategy": _optional_text(row[12], maximum=128, label="stored predicted strategy"),
            "created_at": _timestamp(row[13], label="stored outcome timestamp"),
            "updated_at": _timestamp(row[14], label="stored outcome timestamp"),
        }

    @staticmethod
    def _outcome_select() -> str:
        return (
            "SELECT workspace.public_id,deal.source,deal.source_record_id,outcome.closed,"
            "outcome.purchase_price,outcome.realized_hold_years,outcome.realized_irr,"
            "outcome.realized_equity_multiple,outcome.went_bad,outcome.notes,"
            "outcome.predicted_score,outcome.predicted_grade,outcome.predicted_strategy,"
            "outcome.created_at,outcome.updated_at FROM medawarcre.deal_outcomes outcome "
            "JOIN medawarcre.deals deal ON deal.workspace_id=outcome.workspace_id "
            "AND deal.id=outcome.deal_id JOIN medawarcre.workspaces workspace "
            "ON workspace.id=outcome.workspace_id "
        )

    def _record_outcome(
        self,
        source: str,
        source_id: str,
        outcome: dict[str, Any],
        return_record: bool,
    ) -> bool | dict[str, Any] | None:
        self._require_active_scope("record_outcome")
        with self._database.admitted_connection(self._admission) as connection:
            deal = connection.execute(
                "SELECT id,workspace_id,score,grade,strategy FROM medawarcre.deals "
                "WHERE source=%s AND source_record_id=%s FOR UPDATE",
                (source, source_id),
            ).fetchone()
            if deal is None:
                result: bool | dict[str, Any] | None = None if return_record else False
            else:
                if not isinstance(deal, tuple) or len(deal) != 5:
                    raise ValueError("invalid stored deal")
                connection.execute(
                    "INSERT INTO medawarcre.deal_outcomes("
                    "workspace_id,deal_id,closed,purchase_price,realized_hold_years,"
                    "realized_irr,realized_equity_multiple,went_bad,notes,predicted_score,"
                    "predicted_grade,predicted_strategy,created_by_user_id,updated_by_user_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                    "medawarcre.current_actor_user_id(),medawarcre.current_actor_user_id()) "
                    "ON CONFLICT (workspace_id,deal_id) DO UPDATE SET "
                    "closed=excluded.closed,purchase_price=excluded.purchase_price,"
                    "realized_hold_years=excluded.realized_hold_years,"
                    "realized_irr=excluded.realized_irr,"
                    "realized_equity_multiple=excluded.realized_equity_multiple,"
                    "went_bad=excluded.went_bad,notes=excluded.notes,"
                    "updated_by_user_id=medawarcre.current_actor_user_id(),"
                    "updated_at=statement_timestamp()",
                    (
                        deal[1], deal[0], outcome["closed"], outcome["purchase_price"],
                        outcome["realized_hold_years"], outcome["realized_irr"],
                        outcome["realized_equity_multiple"], outcome["went_bad"],
                        outcome["notes"], deal[2], deal[3], deal[4],
                    ),
                )
                if return_record:
                    row = connection.execute(
                        self._outcome_select() +
                        "WHERE outcome.workspace_id=%s AND outcome.deal_id=%s",
                        (deal[1], deal[0]),
                    ).fetchone()
                    if not isinstance(row, tuple):
                        raise ValueError("invalid stored deal outcome")
                    result = self._decode_outcome(row)
                else:
                    result = True
            self._require_active_scope("record_outcome")
        return result

    async def record_outcome(self, deal_id: str, outcome: dict[str, Any]) -> bool:
        """Upsert a realized outcome while freezing its first score snapshot."""
        _, source, source_id = self._authorized_deal_ref(deal_id)
        selected = self._outcome(outcome)
        result = await self._call(
            "record_outcome",
            self._record_outcome,
            source,
            source_id,
            selected,
            False,
        )
        if not isinstance(result, bool):
            raise DealPersistenceUnavailable(_UNAVAILABLE)
        return result

    async def record_outcome_result(
        self,
        deal_id: str,
        outcome: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Atomically persist and return the exact outcome record."""
        _, source, source_id = self._authorized_deal_ref(deal_id)
        selected = self._outcome(outcome)
        result = await self._call(
            "record_outcome",
            self._record_outcome,
            source,
            source_id,
            selected,
            True,
        )
        if result is not None and not isinstance(result, dict):
            raise DealPersistenceUnavailable(_UNAVAILABLE)
        return result

    def _get_outcomes(self) -> list[dict[str, Any]]:
        self._require_active_scope("get_outcomes")
        with self._database.admitted_connection(self._admission) as connection:
            rows = connection.execute(
                self._outcome_select() +
                "ORDER BY outcome.updated_at DESC,deal.source COLLATE \"C\","
                "deal.source_record_id COLLATE \"C\""
            ).fetchall()
            result = [self._decode_outcome(row) for row in _row_limit(rows, label="deal outcomes")]
            self._require_active_scope("get_outcomes")
        return sanitize_payload(result, config=self._config)

    async def get_outcomes(self) -> list[dict[str, Any]]:
        """Return frozen prediction and outcome pairs for calibration."""
        return await self._call("get_outcomes", self._get_outcomes)

    @staticmethod
    def _investor_values(
        name: object,
        accredited: object,
        accreditation_verified: object,
        relationship: object,
        contact: object,
    ) -> tuple[str, bool | None, bool, str, dict[str, Any] | str | None]:
        selected_name = _text(name.strip() if isinstance(name, str) else name, maximum=300, label="investor name") or ""
        selected_accredited = _boolean(accredited, label="accredited", nullable=True)
        selected_verified = _boolean(accreditation_verified, label="accreditation verified")
        selected_relationship = _text(
            relationship.strip().casefold() if isinstance(relationship, str) else relationship,
            maximum=32,
            label="investor relationship",
        ) or ""
        if selected_relationship not in {"preexisting", "new"}:
            raise ValueError("relationship must be preexisting or new")
        if selected_verified and selected_accredited is not True:
            raise ValueError("accreditation_verified requires accredited=True")
        if contact is None:
            selected_contact = None
        elif isinstance(contact, str):
            selected_contact = _text(contact.strip(), maximum=8_000, label="investor contact")
        elif isinstance(contact, dict):
            selected_contact = _json_object(contact, maximum=16_384, label="investor contact")
        else:
            raise ValueError("invalid investor contact")
        return (
            selected_name,
            selected_accredited,
            bool(selected_verified),
            selected_relationship,
            selected_contact,
        )

    def _decode_commitment(self, row: tuple[Any, ...], *, expected_investor: str | None = None) -> dict[str, Any]:
        if len(row) != 8:
            raise ValueError("invalid stored commitment")
        self._workspace(row[0])
        commitment_id = _uuid(row[1], label="stored commitment identifier")
        deal_id, _, _ = self._authorized_deal_ref(f"{row[2]}:{row[3]}")
        investor_id = _uuid(row[4], label="stored investor identifier")
        if expected_investor is not None and not hmac.compare_digest(investor_id, expected_investor):
            raise ValueError("invalid stored commitment")
        amount = _number(row[5], label="stored commitment amount", nullable=False, strictly_positive=True)
        return {
            "commitment_id": commitment_id,
            "deal_id": deal_id,
            "investor_id": investor_id,
            "amount": amount,
            "created_at": _timestamp(row[6], label="stored commitment timestamp"),
            "updated_at": _timestamp(row[7], label="stored commitment timestamp"),
        }

    @staticmethod
    def _commitment_select() -> str:
        return (
            "SELECT workspace.public_id,commitment.id,deal.source,deal.source_record_id,"
            "commitment.investor_id,commitment.amount,commitment.created_at,"
            "commitment.updated_at "
            "FROM medawarcre.deal_commitments commitment "
            "JOIN medawarcre.deals deal ON deal.workspace_id=commitment.workspace_id "
            "AND deal.id=commitment.deal_id JOIN medawarcre.workspaces workspace "
            "ON workspace.id=commitment.workspace_id "
        )

    def _decode_investor(
        self,
        row: tuple[Any, ...],
        commitments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if len(row) != 9:
            raise ValueError("invalid stored investor")
        self._workspace(row[0])
        investor_id = _uuid(row[1], label="stored investor identifier")
        contact = row[6]
        if contact is not None:
            if isinstance(contact, dict):
                contact = _json_object(contact, maximum=16_384, label="stored investor contact")
            elif isinstance(contact, str):
                contact = _text(contact, maximum=8_000, label="stored investor contact")
            else:
                raise ValueError("invalid stored investor contact")
        accredited = _boolean(row[3], label="stored accredited", nullable=True)
        verified = _boolean(row[4], label="stored accreditation verified")
        relationship = _text(
            row[5],
            maximum=32,
            label="stored investor relationship",
        )
        if relationship not in {"preexisting", "new"}:
            raise ValueError("invalid stored investor relationship")
        if verified and accredited is not True:
            raise ValueError("invalid stored investor accreditation")
        return {
            "investor_id": investor_id,
            "name": _text(row[2], maximum=300, label="stored investor name"),
            "accredited": accredited,
            "accreditation_verified": verified,
            "relationship": relationship,
            "contact": contact,
            "created_at": _timestamp(row[7], label="stored investor timestamp"),
            "updated_at": _timestamp(row[8], label="stored investor timestamp"),
            "commitments": commitments,
            "total_commitments": sum(float(item["amount"]) for item in commitments),
        }

    @staticmethod
    def _investor_select() -> str:
        return (
            "SELECT workspace.public_id,investor.id,investor.name,investor.accredited,"
            "investor.accreditation_verified,investor.relationship,investor.contact,"
            "investor.created_at,investor.updated_at "
            "FROM medawarcre.deal_investors investor JOIN medawarcre.workspaces workspace "
            "ON workspace.id=investor.workspace_id "
        )

    def _investor_record(self, connection: Any, investor_id: str) -> dict[str, Any] | None:
        row = connection.execute(
            self._investor_select() + "WHERE investor.id=%s",
            (investor_id,),
        ).fetchone()
        if row is None:
            return None
        if not isinstance(row, tuple):
            raise ValueError("invalid stored investor")
        commitment_rows = connection.execute(
            self._commitment_select() +
            "WHERE commitment.investor_id=%s ORDER BY commitment.created_at,commitment.id",
            (investor_id,),
        ).fetchall()
        commitments = [
            self._decode_commitment(item, expected_investor=investor_id)
            for item in _row_limit(commitment_rows, label="commitments")
        ]
        return self._decode_investor(row, commitments)

    def _add_investor(
        self,
        values: tuple[str, bool | None, bool, str, dict[str, Any] | str | None],
        return_record: bool,
    ) -> str | dict[str, Any]:
        self._require_active_scope("add_investor")
        name, accredited, verified, relationship, contact = values
        contact_json = None if contact is None else json.dumps(contact, allow_nan=False, separators=(",", ":"))
        with self._database.admitted_connection(self._admission) as connection:
            row = connection.execute(
                "WITH inserted AS (INSERT INTO medawarcre.deal_investors("
                "workspace_id,name,accredited,accreditation_verified,relationship,contact,"
                "created_by_user_id,updated_by_user_id) VALUES ("
                "medawarcre.current_workspace_id(),%s,%s,%s,%s,%s::jsonb,"
                "medawarcre.current_actor_user_id(),medawarcre.current_actor_user_id()) "
                "RETURNING id,workspace_id) SELECT inserted.id,workspace.public_id "
                "FROM inserted JOIN medawarcre.workspaces workspace "
                "ON workspace.id=inserted.workspace_id",
                (name, accredited, verified, relationship, contact_json),
            ).fetchone()
            if not isinstance(row, tuple) or len(row) != 2:
                raise ValueError("invalid stored investor")
            investor_id = _uuid(row[0], label="stored investor identifier")
            self._workspace(row[1])
            result: str | dict[str, Any]
            if return_record:
                record = self._investor_record(connection, investor_id)
                if record is None:
                    raise ValueError("invalid stored investor")
                result = record
            else:
                result = investor_id
            self._require_active_scope("add_investor")
        return result

    async def add_investor(
        self,
        name: str,
        accredited: bool | None = None,
        accreditation_verified: bool = False,
        relationship: str = "new",
        contact: dict[str, Any] | str | None = None,
    ) -> str:
        """Create one workspace investor and return its opaque hosted UUID."""
        values = self._investor_values(name, accredited, accreditation_verified, relationship, contact)
        result = await self._call("add_investor", self._add_investor, values, False)
        if not isinstance(result, str):
            raise DealPersistenceUnavailable(_UNAVAILABLE)
        return result

    async def add_investor_result(
        self,
        name: str,
        accredited: bool | None = None,
        accreditation_verified: bool = False,
        relationship: str = "new",
        contact: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Atomically create and return one investor record."""
        values = self._investor_values(name, accredited, accreditation_verified, relationship, contact)
        result = await self._call("add_investor", self._add_investor, values, True)
        if not isinstance(result, dict):
            raise DealPersistenceUnavailable(_UNAVAILABLE)
        return result

    def _list_investors(self) -> list[dict[str, Any]]:
        self._require_active_scope("list_investors")
        with self._database.admitted_connection(
            self._admission, snapshot=True
        ) as connection:
            rows = connection.execute(
                self._investor_select() + "ORDER BY investor.created_at,investor.id"
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in _row_limit(rows, label="investors"):
                if len(row) != 9:
                    raise ValueError("invalid stored investor")
                investor_id = _uuid(row[1], label="stored investor identifier")
                record = self._investor_record(connection, investor_id)
                if record is None:
                    raise ValueError("invalid stored investor")
                result.append(record)
            self._require_active_scope("list_investors")
        return sanitize_payload(result, config=self._config)

    async def list_investors(self) -> list[dict[str, Any]]:
        """Return workspace investor CRM records and commitments."""
        return await self._call("list_investors", self._list_investors)

    def _get_investor(self, investor_id: str) -> dict[str, Any] | None:
        self._require_active_scope("get_investor")
        with self._database.admitted_connection(
            self._admission, snapshot=True
        ) as connection:
            result = self._investor_record(connection, investor_id)
            self._require_active_scope("get_investor")
        return sanitize_payload(result, config=self._config)

    async def get_investor(self, investor_id: str) -> dict[str, Any] | None:
        """Return one workspace investor and its commitments."""
        selected = _uuid(investor_id, label="investor identifier")
        return await self._call("get_investor", self._get_investor, selected)

    def _record_commitment(
        self,
        source: str,
        source_id: str,
        investor_id: str,
        amount: float,
        return_record: bool,
    ) -> str | dict[str, Any] | None:
        self._require_active_scope("record_commitment")
        with self._database.admitted_connection(self._admission) as connection:
            deal = connection.execute(
                "SELECT id,workspace_id FROM medawarcre.deals "
                "WHERE source=%s AND source_record_id=%s FOR UPDATE",
                (source, source_id),
            ).fetchone()
            investor = connection.execute(
                "SELECT id,workspace_id FROM medawarcre.deal_investors WHERE id=%s",
                (investor_id,),
            ).fetchone()
            if deal is None or investor is None:
                result: str | dict[str, Any] | None = None
            else:
                if (
                    not isinstance(deal, tuple) or len(deal) != 2
                    or not isinstance(investor, tuple) or len(investor) != 2
                    or deal[1] != investor[1]
                ):
                    raise ValueError("invalid stored commitment parent")
                row = connection.execute(
                    "INSERT INTO medawarcre.deal_commitments("
                    "workspace_id,deal_id,investor_id,amount,created_by_user_id,updated_by_user_id) "
                    "VALUES (%s,%s,%s,%s,medawarcre.current_actor_user_id(),"
                    "medawarcre.current_actor_user_id()) "
                    "ON CONFLICT (workspace_id,deal_id,investor_id) DO UPDATE SET "
                    "amount=excluded.amount,updated_by_user_id=medawarcre.current_actor_user_id(),"
                    "updated_at=statement_timestamp() RETURNING id",
                    (deal[1], deal[0], investor_id, amount),
                ).fetchone()
                if not isinstance(row, tuple) or len(row) != 1:
                    raise ValueError("invalid stored commitment")
                commitment_id = _uuid(row[0], label="stored commitment identifier")
                if return_record:
                    stored = connection.execute(
                        self._commitment_select() + "WHERE commitment.id=%s",
                        (commitment_id,),
                    ).fetchone()
                    if not isinstance(stored, tuple):
                        raise ValueError("invalid stored commitment")
                    result = self._decode_commitment(
                        stored,
                        expected_investor=investor_id,
                    )
                else:
                    result = commitment_id
            self._require_active_scope("record_commitment")
        return result

    async def record_commitment(self, deal_id: str, investor_id: str, amount: float) -> str | None:
        """Upsert one non-binding deal/investor indication."""
        _, source, source_id = self._authorized_deal_ref(deal_id)
        selected_investor = _uuid(investor_id, label="investor identifier")
        selected_amount = _number(amount, label="commitment amount", nullable=False, strictly_positive=True)
        result = await self._call(
            "record_commitment",
            self._record_commitment,
            source,
            source_id,
            selected_investor,
            selected_amount,
            False,
        )
        if result is not None and not isinstance(result, str):
            raise DealPersistenceUnavailable(_UNAVAILABLE)
        return result

    async def record_commitment_result(
        self,
        deal_id: str,
        investor_id: str,
        amount: float,
    ) -> dict[str, Any] | None:
        """Atomically validate parents, upsert, and return one indication."""
        _, source, source_id = self._authorized_deal_ref(deal_id)
        selected_investor = _uuid(investor_id, label="investor identifier")
        selected_amount = _number(amount, label="commitment amount", nullable=False, strictly_positive=True)
        result = await self._call(
            "record_commitment",
            self._record_commitment,
            source,
            source_id,
            selected_investor,
            selected_amount,
            True,
        )
        if result is not None and not isinstance(result, dict):
            raise DealPersistenceUnavailable(_UNAVAILABLE)
        return result

    def _get_commitment(self, commitment_id: str) -> dict[str, Any] | None:
        self._require_active_scope("get_commitment")
        with self._database.admitted_connection(self._admission) as connection:
            row = connection.execute(
                self._commitment_select() + "WHERE commitment.id=%s",
                (commitment_id,),
            ).fetchone()
            if row is None:
                result = None
            elif isinstance(row, tuple):
                result = self._decode_commitment(row)
            else:
                raise ValueError("invalid stored commitment")
            self._require_active_scope("get_commitment")
        return result

    async def get_commitment(self, commitment_id: str) -> dict[str, Any] | None:
        """Return one non-binding commitment by opaque hosted UUID."""
        selected = _uuid(commitment_id, label="commitment identifier")
        return await self._call("get_commitment", self._get_commitment, selected)

    @staticmethod
    def _exchange_dates(
        close_date: object,
        identification_deadline: object,
        exchange_deadline: object,
    ) -> tuple[str, str, str]:
        selected_close = _date(close_date, label="relinquished close date") or ""
        selected_identification = _date(identification_deadline, label="identification deadline") or ""
        selected_exchange = _date(exchange_deadline, label="exchange deadline") or ""
        if not selected_close <= selected_identification <= selected_exchange:
            raise ValueError("invalid exchange deadlines")
        return selected_close, selected_identification, selected_exchange

    def _decode_exchange(self, connection: Any, row: tuple[Any, ...]) -> dict[str, Any]:
        if len(row) != 10:
            raise ValueError("invalid stored exchange")
        self._workspace(row[0])
        exchange_id = _uuid(row[1], label="stored exchange identifier")
        require_source(str(row[2]), config=self._config)
        deal_id, _, _ = self._authorized_deal_ref(f"{row[2]}:{row[3]}")
        listing = self._decode_listing(row[4], row[2], row[3])
        close_date, identification_deadline, exchange_deadline = self._exchange_dates(
            row[5],
            row[6],
            row[7],
        )
        replacements = connection.execute(
            "SELECT workspace.public_id,exchange.id,deal.source,deal.source_record_id,"
            "replacement.value,replacement.identified_at "
            "FROM medawarcre.deal_exchange_replacements replacement "
            "JOIN medawarcre.deal_exchanges exchange "
            "ON exchange.workspace_id=replacement.workspace_id "
            "AND exchange.id=replacement.exchange_id "
            "JOIN medawarcre.deals deal ON deal.workspace_id=replacement.workspace_id "
            "AND deal.id=replacement.deal_id JOIN medawarcre.workspaces workspace "
            "ON workspace.id=replacement.workspace_id "
            "WHERE replacement.exchange_id=%s "
            "ORDER BY replacement.identified_at,deal.source COLLATE \"C\","
            "deal.source_record_id COLLATE \"C\"",
            (exchange_id,),
        ).fetchall()
        decoded: list[dict[str, Any]] = []
        for item in _row_limit(replacements, label="exchange replacements"):
            if len(item) != 6:
                raise ValueError("invalid stored exchange replacement")
            self._workspace(item[0])
            if not hmac.compare_digest(_uuid(item[1], label="stored exchange identifier"), exchange_id):
                raise ValueError("invalid stored exchange replacement")
            require_source(str(item[2]), config=self._config)
            replacement_id, _, _ = self._authorized_deal_ref(f"{item[2]}:{item[3]}")
            identified_at = _date(item[5], label="stored identification date")
            if identified_at is None or identified_at > identification_deadline:
                raise ValueError("invalid stored exchange replacement")
            decoded.append(
                {
                    "deal_id": replacement_id,
                    "value": _number(item[4], label="stored replacement value", strictly_positive=item[4] is not None),
                    "identified_at": identified_at,
                }
            )
        return {
            "exchange_id": exchange_id,
            "relinquished_deal_id": deal_id,
            "relinquished_close_date": close_date,
            "identification_deadline": identification_deadline,
            "exchange_deadline": exchange_deadline,
            "created_at": _timestamp(row[8], label="stored exchange timestamp"),
            "updated_at": _timestamp(row[9], label="stored exchange timestamp"),
            "relinquished_value": self._listing_value(listing),
            "replacements": decoded,
        }

    @staticmethod
    def _exchange_select() -> str:
        return (
            "SELECT workspace.public_id,exchange.id,deal.source,deal.source_record_id,"
            "deal.listing,"
            "exchange.relinquished_close_date,exchange.identification_deadline,"
            "exchange.exchange_deadline,exchange.created_at,exchange.updated_at "
            "FROM medawarcre.deal_exchanges exchange JOIN medawarcre.deals deal "
            "ON deal.workspace_id=exchange.workspace_id "
            "AND deal.id=exchange.relinquished_deal_id JOIN medawarcre.workspaces workspace "
            "ON workspace.id=exchange.workspace_id "
        )

    @staticmethod
    def _write_exchange(
        connection: Any,
        source: str,
        source_id: str,
        dates: tuple[str, str, str],
    ) -> str | None:
        close_date, identification_deadline, exchange_deadline = dates
        deal = connection.execute(
            "SELECT id,workspace_id FROM medawarcre.deals "
            "WHERE source=%s AND source_record_id=%s FOR UPDATE",
            (source, source_id),
        ).fetchone()
        if deal is None:
            return None
        if not isinstance(deal, tuple) or len(deal) != 2:
            raise ValueError("invalid stored deal")
        row = connection.execute(
            "INSERT INTO medawarcre.deal_exchanges("
            "workspace_id,relinquished_deal_id,relinquished_close_date,"
            "identification_deadline,exchange_deadline,created_by_user_id,"
            "updated_by_user_id) VALUES (%s,%s,%s,%s,%s,"
            "medawarcre.current_actor_user_id(),medawarcre.current_actor_user_id()) "
            "ON CONFLICT (workspace_id,relinquished_deal_id,relinquished_close_date) "
            "DO UPDATE SET identification_deadline=excluded.identification_deadline,"
            "exchange_deadline=excluded.exchange_deadline,"
            "updated_by_user_id=medawarcre.current_actor_user_id(),"
            "updated_at=statement_timestamp() RETURNING id",
            (deal[1], deal[0], close_date, identification_deadline, exchange_deadline),
        ).fetchone()
        if not isinstance(row, tuple) or len(row) != 1:
            raise ValueError("invalid stored exchange")
        return _uuid(row[0], label="stored exchange identifier")

    def _create_exchange(
        self,
        source: str,
        source_id: str,
        dates: tuple[str, str, str],
    ) -> str | None:
        self._require_active_scope("create_exchange")
        with self._database.admitted_connection(self._admission) as connection:
            result = self._write_exchange(connection, source, source_id, dates)
            self._require_active_scope("create_exchange")
        return result

    async def create_exchange(
        self,
        relinquished_deal_id: str,
        relinquished_close_date: str,
        identification_deadline: str,
        exchange_deadline: str,
    ) -> str | None:
        """Create or retrieve one exchange clock on its natural key."""
        _, source, source_id = self._authorized_deal_ref(relinquished_deal_id)
        dates = self._exchange_dates(
            relinquished_close_date,
            identification_deadline,
            exchange_deadline,
        )
        return await self._call("create_exchange", self._create_exchange, source, source_id, dates)

    def _create_exchange_result(
        self,
        source: str,
        source_id: str,
        dates: tuple[str, str, str],
    ) -> dict[str, Any] | None:
        method = "create_exchange_result"
        self._require_active_scope(method)
        with self._database.admitted_connection(self._admission) as connection:
            exchange_id = self._write_exchange(connection, source, source_id, dates)
            if exchange_id is None:
                result = None
            else:
                row = connection.execute(
                    self._exchange_select() + "WHERE exchange.id=%s",
                    (exchange_id,),
                ).fetchone()
                if not isinstance(row, tuple):
                    raise ValueError("invalid stored exchange")
                result = self._decode_exchange(connection, row)
            self._require_active_scope(method)
        return sanitize_payload(result, config=self._config)

    async def create_exchange_result(
        self,
        relinquished_deal_id: str,
        relinquished_close_date: str,
        identification_deadline: str,
        exchange_deadline: str,
    ) -> dict[str, Any] | None:
        """Atomically create and return one exchange clock."""
        _, source, source_id = self._authorized_deal_ref(relinquished_deal_id)
        dates = self._exchange_dates(
            relinquished_close_date,
            identification_deadline,
            exchange_deadline,
        )
        return await self._call(
            "create_exchange_result",
            self._create_exchange_result,
            source,
            source_id,
            dates,
        )

    def _get_exchange_record(self, exchange_id: str) -> dict[str, Any] | None:
        self._require_active_scope("get_exchange_record")
        with self._database.admitted_connection(
            self._admission, snapshot=True
        ) as connection:
            row = connection.execute(
                self._exchange_select() + "WHERE exchange.id=%s",
                (exchange_id,),
            ).fetchone()
            if row is None:
                result = None
            elif isinstance(row, tuple):
                result = self._decode_exchange(connection, row)
            else:
                raise ValueError("invalid stored exchange")
            self._require_active_scope("get_exchange_record")
        return sanitize_payload(result, config=self._config)

    async def get_exchange_record(self, exchange_id: str) -> dict[str, Any] | None:
        """Return one exchange and its ordered replacement list."""
        selected = _uuid(exchange_id, label="exchange identifier")
        return await self._call("get_exchange_record", self._get_exchange_record, selected)

    def _add_exchange_replacement(
        self,
        exchange_id: str,
        source: str,
        source_id: str,
        value: float | None,
        identified_at: str,
    ) -> bool:
        self._require_active_scope("add_exchange_replacement")
        with self._database.admitted_connection(self._admission) as connection:
            exchange = connection.execute(
                "SELECT id,workspace_id FROM medawarcre.deal_exchanges WHERE id=%s FOR UPDATE",
                (exchange_id,),
            ).fetchone()
            deal = connection.execute(
                "SELECT id,workspace_id FROM medawarcre.deals "
                "WHERE source=%s AND source_record_id=%s FOR UPDATE",
                (source, source_id),
            ).fetchone()
            if exchange is None or deal is None:
                result = False
            else:
                if (
                    not isinstance(exchange, tuple) or len(exchange) != 2
                    or not isinstance(deal, tuple) or len(deal) != 2
                    or exchange[1] != deal[1]
                ):
                    raise ValueError("invalid stored exchange replacement")
                connection.execute(
                    "INSERT INTO medawarcre.deal_exchange_replacements("
                    "workspace_id,exchange_id,deal_id,value,identified_at,created_by_user_id) "
                    "VALUES (%s,%s,%s,%s,%s,medawarcre.current_actor_user_id()) "
                    "ON CONFLICT (workspace_id,exchange_id,deal_id) DO UPDATE SET "
                    "value=COALESCE(excluded.value,medawarcre.deal_exchange_replacements.value)",
                    (exchange[1], exchange[0], deal[0], value, identified_at),
                )
                connection.execute(
                    "UPDATE medawarcre.deal_exchanges SET "
                    "updated_by_user_id=medawarcre.current_actor_user_id(),"
                    "updated_at=statement_timestamp() WHERE workspace_id=%s AND id=%s",
                    (exchange[1], exchange[0]),
                )
                result = True
            self._require_active_scope("add_exchange_replacement")
        return result

    async def add_exchange_replacement(
        self,
        exchange_id: str,
        deal_id: str,
        value: float | None,
        identified_at: str,
    ) -> bool:
        """Upsert one replacement candidate under an exchange row lock."""
        selected_exchange = _uuid(exchange_id, label="exchange identifier")
        _, source, source_id = self._authorized_deal_ref(deal_id)
        selected_value = _number(
            value,
            label="replacement value",
            strictly_positive=value is not None,
        )
        selected_date = _date(identified_at, label="identified at") or ""
        return await self._call(
            "add_exchange_replacement",
            self._add_exchange_replacement,
            selected_exchange,
            source,
            source_id,
            selected_value,
            selected_date,
        )

    @staticmethod
    def _listing_value(listing: dict[str, Any]) -> float | None:
        """Return the listing's fair-market value within the stored domain.

        The identification rules compare these figures and one of them is
        persisted to `deal_exchange_replacements.value numeric(19, 2)`, so an
        out-of-domain provider figure resolves to "no verified value" — which
        the 200% rule then treats as unverified — rather than overflowing.
        """
        numeric = listing.get("price_usd")
        if isinstance(numeric, (int, float, Decimal)) and not isinstance(numeric, bool):
            value = float(numeric)
            return value if math.isfinite(value) and 0 < value < _NUMERIC_19_2_LIMIT else None
        price = listing.get("price")
        if not isinstance(price, str):
            return None
        try:
            value = float(price.replace("$", "").replace(",", "").strip())
        except ValueError:
            return None
        return value if math.isfinite(value) and 0 < value < _NUMERIC_19_2_LIMIT else None

    def _identify_exchange_replacement_result(
        self,
        exchange_id: str,
        source: str,
        source_id: str,
        identified_at: str,
    ) -> dict[str, Any]:
        method = "identify_exchange_replacement_result"
        self._require_active_scope(method)
        with self._database.admitted_connection(self._admission) as connection:
            exchange = connection.execute(
                "SELECT id,workspace_id,relinquished_deal_id,identification_deadline "
                "FROM medawarcre.deal_exchanges WHERE id=%s FOR UPDATE",
                (exchange_id,),
            ).fetchone()
            if not isinstance(exchange, tuple) or len(exchange) != 4:
                raise ValueError(f"unknown exchange_id: {exchange_id}")
            deadline = _date(exchange[3], label="stored identification deadline") or ""
            if identified_at > deadline:
                raise DealRuleViolation(
                    f"identification is locked after day 45 ({deadline})"
                )
            replacement = connection.execute(
                "SELECT id,workspace_id,source,source_record_id,listing "
                "FROM medawarcre.deals WHERE source=%s AND source_record_id=%s FOR UPDATE",
                (source, source_id),
            ).fetchone()
            deal_id = f"{source}:{source_id}"
            if not isinstance(replacement, tuple) or len(replacement) != 5:
                raise ValueError(f"unknown replacement deal_id: {deal_id}")
            if replacement[1] != exchange[1]:
                raise ValueError("invalid stored exchange replacement")
            if replacement[0] == exchange[2]:
                raise DealRuleViolation(
                    "replacement deal cannot be the relinquished deal"
                )
            listing = self._decode_listing(replacement[4], replacement[2], replacement[3])
            candidate_value = self._listing_value(listing)
            existing = connection.execute(
                "SELECT deal_id,value FROM medawarcre.deal_exchange_replacements "
                "WHERE exchange_id=%s ORDER BY identified_at,deal_id",
                (exchange_id,),
            ).fetchall()
            existing_rows = _row_limit(existing, label="exchange replacements")
            already_identified = any(
                isinstance(item, tuple)
                and len(item) == 2
                and item[0] == replacement[0]
                for item in existing_rows
            )
            if not already_identified and len(existing_rows) + 1 > 3:
                relinquished = connection.execute(
                    "SELECT source,source_record_id,listing FROM medawarcre.deals WHERE id=%s",
                    (exchange[2],),
                ).fetchone()
                if not isinstance(relinquished, tuple) or len(relinquished) != 3:
                    raise ValueError("invalid stored relinquished deal")
                relinquished_listing = self._decode_listing(
                    relinquished[2],
                    relinquished[0],
                    relinquished[1],
                )
                relinquished_value = self._listing_value(relinquished_listing)
                values = [
                    _number(
                        item[1],
                        label="stored replacement value",
                        strictly_positive=item[1] is not None,
                    )
                    for item in existing_rows
                    if isinstance(item, tuple) and len(item) == 2
                ]
                values.append(candidate_value)
                if (
                    relinquished_value is None
                    or len(values) != len(existing_rows) + 1
                    or any(value is None for value in values)
                ):
                    raise DealRuleViolation(
                        "more than three properties requires verified FMV for the "
                        "relinquished and every replacement property to test the 200% rule"
                    )
                total = sum(float(value) for value in values if value is not None)
                limit = relinquished_value * 2.0
                if total > limit:
                    received_needed = total * 0.95
                    raise DealRuleViolation(
                        f"identification rejected: {len(values)} properties total "
                        f"${total:,.0f}, exceeding the 200% ceiling of ${limit:,.0f}. "
                        "The 95% rule would require actual receipt of at least "
                        f"${received_needed:,.0f} of identified FMV; this tracker will "
                        "not treat that narrow after-the-fact exception as pre-approved. "
                        "Ask the QI/tax attorney."
                    )
            if not already_identified:
                connection.execute(
                    "INSERT INTO medawarcre.deal_exchange_replacements("
                    "workspace_id,exchange_id,deal_id,value,identified_at,created_by_user_id) "
                    "VALUES (%s,%s,%s,%s,%s,medawarcre.current_actor_user_id())",
                    (
                        exchange[1],
                        exchange[0],
                        replacement[0],
                        candidate_value,
                        identified_at,
                    ),
                )
                connection.execute(
                    "UPDATE medawarcre.deal_exchanges SET "
                    "updated_by_user_id=medawarcre.current_actor_user_id(),"
                    "updated_at=statement_timestamp() WHERE id=%s",
                    (exchange_id,),
                )
            row = connection.execute(
                self._exchange_select() + "WHERE exchange.id=%s",
                (exchange_id,),
            ).fetchone()
            if not isinstance(row, tuple):
                raise ValueError("invalid stored exchange")
            result = self._decode_exchange(connection, row)
            self._require_active_scope(method)
        return sanitize_payload(result, config=self._config)

    async def identify_exchange_replacement_result(
        self,
        exchange_id: str,
        deal_id: str,
        identified_at: str,
    ) -> dict[str, Any]:
        """Lock, validate statutory rules, persist, and return a replacement."""
        selected_exchange = _uuid(exchange_id, label="exchange identifier")
        _, source, source_id = self._authorized_deal_ref(deal_id)
        selected_date = _date(identified_at, label="identified at") or ""
        return await self._call(
            "identify_exchange_replacement_result",
            self._identify_exchange_replacement_result,
            selected_exchange,
            source,
            source_id,
            selected_date,
        )

    @staticmethod
    def _verdict(value: object, *, label: str) -> str | None:
        return _optional_text(value, maximum=128, label=label)

    def _record_ic_decision(
        self,
        source: str,
        source_id: str,
        system_verdict: str | None,
        system: dict[str, Any],
        expert_verdict: str | None,
        expert: dict[str, Any],
    ) -> str | None:
        self._require_active_scope("record_ic_decision")
        agreed = (
            None
            if not system_verdict or not expert_verdict
            else system_verdict.casefold() == expert_verdict.casefold()
        )
        with self._database.admitted_connection(self._admission) as connection:
            deal = connection.execute(
                "SELECT id,workspace_id FROM medawarcre.deals "
                "WHERE source=%s AND source_record_id=%s FOR UPDATE",
                (source, source_id),
            ).fetchone()
            if deal is None:
                result = None
            else:
                if not isinstance(deal, tuple) or len(deal) != 2:
                    raise ValueError("invalid stored deal")
                row = connection.execute(
                    "WITH inserted AS (INSERT INTO medawarcre.deal_ic_decisions("
                    "workspace_id,deal_id,system_verdict,system_data,expert_verdict,"
                    "expert_data,agreed,created_by_user_id,request_invocation_id) "
                    "VALUES (%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,"
                    "medawarcre.current_actor_user_id(),%s) "
                    "ON CONFLICT (workspace_id,request_invocation_id) DO NOTHING RETURNING id) "
                    "SELECT id FROM inserted UNION ALL SELECT id FROM "
                    "medawarcre.deal_ic_decisions WHERE workspace_id=%s "
                    "AND request_invocation_id=%s LIMIT 1",
                    (
                        deal[1], deal[0], system_verdict,
                        json.dumps(system, allow_nan=False, separators=(",", ":")),
                        expert_verdict,
                        json.dumps(expert, allow_nan=False, separators=(",", ":")),
                        agreed,
                        self._admission.invocation_id,
                        deal[1],
                        self._admission.invocation_id,
                    ),
                ).fetchone()
                if not isinstance(row, tuple) or len(row) != 1:
                    raise ValueError("invalid stored IC decision")
                result = _uuid(row[0], label="stored IC decision identifier")
            self._require_active_scope("record_ic_decision")
        return result

    async def record_ic_decision(
        self,
        deal_id: str,
        *,
        system_verdict: str | None = None,
        system: dict[str, Any] | None = None,
        expert_verdict: str | None = None,
        expert: dict[str, Any] | None = None,
    ) -> str | None:
        """Idempotently append one shadow-IC decision for this invocation."""
        _, source, source_id = self._authorized_deal_ref(deal_id)
        selected_system_verdict = self._verdict(system_verdict, label="system verdict")
        selected_expert_verdict = self._verdict(expert_verdict, label="expert verdict")
        selected_system = _json_object(
            sanitize_payload(system or {}, purpose="storage", config=self._config),
            maximum=65_536,
            label="system decision",
        )
        selected_expert = _json_object(
            sanitize_payload(expert or {}, purpose="storage", config=self._config),
            maximum=65_536,
            label="expert decision",
        )
        return await self._call(
            "record_ic_decision",
            self._record_ic_decision,
            source,
            source_id,
            selected_system_verdict,
            selected_system,
            selected_expert_verdict,
            selected_expert,
        )

    def _log_deal_event(
        self,
        source: str,
        source_id: str,
        event_type: str,
        detail: dict[str, Any],
        occurred_at: str,
    ) -> str | None:
        self._require_active_scope("log_deal_event")
        with self._database.admitted_connection(self._admission) as connection:
            deal = connection.execute(
                "SELECT id,workspace_id FROM medawarcre.deals "
                "WHERE source=%s AND source_record_id=%s FOR UPDATE",
                (source, source_id),
            ).fetchone()
            if deal is None:
                result = None
            else:
                if not isinstance(deal, tuple) or len(deal) != 2:
                    raise ValueError("invalid stored deal")
                row = connection.execute(
                    "WITH inserted AS (INSERT INTO medawarcre.deal_events("
                    "workspace_id,deal_id,event_type,event_data,occurred_at,author_user_id,"
                    "request_invocation_id) VALUES (%s,%s,%s,%s::jsonb,%s,"
                    "medawarcre.current_actor_user_id(),%s) "
                    "ON CONFLICT (workspace_id,request_invocation_id) "
                    "WHERE request_invocation_id IS NOT NULL DO NOTHING RETURNING id) "
                    "SELECT id FROM inserted UNION ALL SELECT id FROM medawarcre.deal_events "
                    "WHERE workspace_id=%s AND request_invocation_id=%s LIMIT 1",
                    (
                        deal[1], deal[0], event_type,
                        json.dumps(detail, allow_nan=False, separators=(",", ":")),
                        occurred_at,
                        self._admission.invocation_id,
                        deal[1],
                        self._admission.invocation_id,
                    ),
                ).fetchone()
                if not isinstance(row, tuple) or len(row) != 1:
                    raise ValueError("invalid stored deal event")
                result = _uuid(row[0], label="stored deal event identifier")
            self._require_active_scope("log_deal_event")
        return result

    async def log_deal_event(
        self,
        deal_id: str,
        event_type: str,
        detail: dict[str, Any] | None = None,
        event_ts: str | None = None,
    ) -> str | None:
        """Idempotently append one event for this admitted invocation."""
        _, source, source_id = self._authorized_deal_ref(deal_id)
        selected_type = _text(event_type.strip() if isinstance(event_type, str) else event_type, maximum=128, label="event type") or ""
        selected_detail = _json_object(
            sanitize_payload(detail or {}, purpose="storage", config=self._config),
            maximum=65_536,
            label="event detail",
        )
        selected_ts = (
            datetime.now(UTC).isoformat()
            if event_ts is None
            else _timestamp(event_ts, label="event timestamp") or ""
        )
        return await self._call(
            "log_deal_event",
            self._log_deal_event,
            source,
            source_id,
            selected_type,
            selected_detail,
            selected_ts,
        )

    def _get_deal_timeline(
        self,
        deal_id: str,
        source: str,
        source_id: str,
    ) -> dict[str, Any]:
        self._require_active_scope("get_deal_timeline")
        with self._database.admitted_connection(
            self._admission, snapshot=True
        ) as connection:
            events = connection.execute(
                "SELECT workspace.public_id,deal.source,deal.source_record_id,event.event_type,"
                "event.event_data,event.occurred_at,event.created_at "
                "FROM medawarcre.deal_events event JOIN medawarcre.deals deal "
                "ON deal.workspace_id=event.workspace_id AND deal.id=event.deal_id "
                "JOIN medawarcre.workspaces workspace ON workspace.id=event.workspace_id "
                "WHERE deal.source=%s AND deal.source_record_id=%s "
                "ORDER BY event.occurred_at,event.id",
                (source, source_id),
            ).fetchall()
            decisions = connection.execute(
                "SELECT workspace.public_id,deal.source,deal.source_record_id,"
                "decision.system_verdict,decision.system_data,decision.expert_verdict,"
                "decision.expert_data,decision.agreed,decision.created_at "
                "FROM medawarcre.deal_ic_decisions decision JOIN medawarcre.deals deal "
                "ON deal.workspace_id=decision.workspace_id AND deal.id=decision.deal_id "
                "JOIN medawarcre.workspaces workspace ON workspace.id=decision.workspace_id "
                "WHERE deal.source=%s AND deal.source_record_id=%s "
                "ORDER BY decision.created_at,decision.id",
                (source, source_id),
            ).fetchall()
            event_result: list[dict[str, Any]] = []
            for row in _row_limit(events, label="deal events"):
                if len(row) != 7:
                    raise ValueError("invalid stored deal event")
                self._workspace(row[0])
                parent, _, _ = self._authorized_deal_ref(f"{row[1]}:{row[2]}")
                if not hmac.compare_digest(parent, deal_id):
                    raise ValueError("invalid stored deal event")
                event_result.append(
                    {
                        "event_type": _text(row[3], maximum=128, label="stored event type"),
                        "detail": _json_object(row[4], maximum=65_536, label="stored event detail"),
                        "event_ts": _timestamp(row[5], label="stored event timestamp"),
                        "created_at": _timestamp(row[6], label="stored event timestamp"),
                    }
                )
            decision_result: list[dict[str, Any]] = []
            for row in _row_limit(decisions, label="IC decisions"):
                if len(row) != 9:
                    raise ValueError("invalid stored IC decision")
                self._workspace(row[0])
                parent, _, _ = self._authorized_deal_ref(f"{row[1]}:{row[2]}")
                if not hmac.compare_digest(parent, deal_id):
                    raise ValueError("invalid stored IC decision")
                decision_result.append(
                    {
                        "system_verdict": self._verdict(row[3], label="stored system verdict"),
                        "system": _json_object(row[4], maximum=65_536, label="stored system decision"),
                        "expert_verdict": self._verdict(row[5], label="stored expert verdict"),
                        "expert": _json_object(row[6], maximum=65_536, label="stored expert decision"),
                        "agreed": _boolean(row[7], label="stored agreement", nullable=True),
                        "created_at": _timestamp(row[8], label="stored decision timestamp"),
                    }
                )
            result = {"deal_id": deal_id, "events": event_result, "ic_decisions": decision_result}
            self._require_active_scope("get_deal_timeline")
        return sanitize_payload(result, config=self._config)

    async def get_deal_timeline(self, deal_id: str) -> dict[str, Any]:
        """Return the ordered event and IC timeline for one workspace deal."""
        selected, source, source_id = self._authorized_deal_ref(deal_id)
        return await self._call(
            "get_deal_timeline",
            self._get_deal_timeline,
            selected,
            source,
            source_id,
        )

    def _ic_scorecard(self) -> dict[str, Any]:
        self._require_active_scope("ic_scorecard")
        with self._database.admitted_connection(self._admission) as connection:
            rows = connection.execute(
                "SELECT workspace.public_id,deal.source,deal.source_record_id,"
                "decision.system_verdict,decision.expert_verdict,"
                "decision.agreed,outcome.closed,outcome.went_bad "
                "FROM medawarcre.deal_ic_decisions decision "
                "JOIN medawarcre.workspaces workspace ON workspace.id=decision.workspace_id "
                "JOIN medawarcre.deals deal ON deal.workspace_id=decision.workspace_id "
                "AND deal.id=decision.deal_id "
                "LEFT JOIN medawarcre.deal_outcomes outcome "
                "ON outcome.workspace_id=decision.workspace_id AND outcome.deal_id=decision.deal_id "
                "WHERE decision.id IN (SELECT latest.id FROM ("
                "SELECT DISTINCT ON (workspace_id,deal_id) id FROM medawarcre.deal_ic_decisions "
                "ORDER BY workspace_id,deal_id,created_at DESC,id DESC) latest)"
            ).fetchall()
            selected = _row_limit(rows, label="IC scorecard")
            for row in selected:
                if len(row) != 8:
                    raise ValueError("invalid stored IC scorecard")
                self._workspace(row[0])
                self._authorized_deal_ref(f"{row[1]}:{row[2]}")
            with_expert = [row for row in selected if row[5] is not None]
            agreement = sum(1 for row in with_expert if row[5] is True)
            scored = 0
            correct = 0
            for row in selected:
                verdict = self._verdict(row[3], label="stored system verdict")
                _ = self._verdict(row[4], label="stored expert verdict")
                agreed = _boolean(row[5], label="stored agreement", nullable=True)
                closed = _boolean(row[6], label="stored outcome closed", nullable=True)
                went_bad = _boolean(row[7], label="stored went bad", nullable=True)
                if closed is None or verdict is None:
                    continue
                said_go = verdict.casefold() in {"proceed", "proceed_with_conditions"}
                good = closed and not bool(went_bad)
                scored += 1
                correct += int(said_go == good)
            result = {
                "total_ic_decisions": len(selected),
                "with_expert": len(with_expert),
                "system_expert_agreement_rate": round(agreement / len(with_expert), 3) if with_expert else None,
                "with_realized_outcome": scored,
                "system_accuracy_vs_outcome": round(correct / scored, 3) if scored else None,
                "caveat": (
                    "Shadow-IC accuracy is only meaningful with a real sample of closed "
                    "outcomes; treat small-n figures as directional, not validated."
                ),
            }
            self._require_active_scope("ic_scorecard")
        return result

    async def ic_scorecard(self) -> dict[str, Any]:
        """Return aggregate system/expert and realized-outcome calibration."""
        return await self._call("ic_scorecard", self._ic_scorecard)


__all__ = ["DealPersistenceUnavailable", "PostgresDealRepository"]
