"""Audited Skool join tasks, current-state evidence, and manual revocation."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.platform.admin import (
    AdminAuditError,
    AdminConflictError,
    AdminForbiddenError,
    AdminNotFoundError,
    AdminValidationError,
    canonical_json,
    validate_reason,
)
from cre_mcp.platform.providers.core import (
    NormalizedProviderEvent,
    ProviderSyncService,
)
from cre_mcp.platform.dbapi import platform_connection


JOIN_COMPLETION_SOURCES = frozenset({"manual_admin_invite", "zapier_invite"})
RECONCILIATION_SOURCES = frozenset({"operator_members_review"})
RECONCILIATION_CONFIDENCE = frozenset(
    {"confirmed", "provisional", "unverified"}
)
MEMBER_STATES = frozenset(
    {"active", "canceled", "removed", "banned", "payment_failed"}
)
RESTRICTIVE_ACTIONS = {
    "canceled": "cancel",
    "removed": "remove",
    "banned": "banned",
    "payment_failed": "payment_failed",
}
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}\Z")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _safe_id(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise AdminValidationError(f"{label} must be a string")
    normalized = value.strip()
    if _SAFE_ID.fullmatch(normalized) is None:
        raise AdminValidationError(f"{label} must be a safe provider identifier")
    return normalized


def _choice(value: Any, allowed: frozenset[str], label: str) -> str:
    if not isinstance(value, str):
        raise AdminValidationError(f"{label} must be a string")
    normalized = value.strip().casefold()
    if normalized not in allowed:
        raise AdminValidationError(
            f"{label} must be one of {', '.join(sorted(allowed))}"
        )
    return normalized


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AdminValidationError(f"{label} must be a positive integer")
    return value


def _observed_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise AdminValidationError("observed_at must be an ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdminValidationError(
            "observed_at must be an ISO-8601 datetime"
        ) from exc
    if parsed.tzinfo is None:
        raise AdminValidationError("observed_at must include a timezone")
    return parsed.astimezone(UTC)


class SkoolLifecycleService:
    """Skool is evidence only; MedawarCRE state remains authorization authority."""

    def __init__(
        self,
        config: CreConfig,
        *,
        sync: ProviderSyncService | None = None,
    ) -> None:
        self.config = config
        self.db_path = Path(config.cache_db_path).expanduser()
        self.sync = sync or ProviderSyncService(config)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with platform_connection(
            self.db_path,
            timeout=30,
            transactional=False,
        ) as connection:
            yield connection

    @staticmethod
    def _actor(
        connection: sqlite3.Connection,
        actor_user_id: int,
        *,
        mutate: bool,
    ) -> sqlite3.Row:
        actor = connection.execute(
            """
            SELECT user_id,role FROM platform_internal_admins
            WHERE user_id=? AND active=1
            """,
            (actor_user_id,),
        ).fetchone()
        allowed = {"platform_admin"} if mutate else {"platform_admin", "support"}
        if actor is None or str(actor["role"]) not in allowed:
            raise AdminForbiddenError(
                "Active internal operator authority is required"
            )
        return actor

    @staticmethod
    def _workspace(
        connection: sqlite3.Connection,
        workspace_public_id: str,
    ) -> sqlite3.Row:
        workspace = connection.execute(
            "SELECT id,public_id FROM platform_workspaces WHERE public_id=?",
            (workspace_public_id.strip(),),
        ).fetchone()
        if workspace is None:
            raise AdminNotFoundError("Workspace does not exist")
        return workspace

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        actor: sqlite3.Row,
        *,
        action: str,
        workspace_id: int,
        target_type: str,
        target_id: str,
        reason_code: str,
        reason: str,
        before: Any,
        after: Any,
    ) -> None:
        changes_before = connection.total_changes
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
                    action,
                    workspace_id,
                    target_type,
                    target_id,
                    reason_code,
                    reason,
                    canonical_json(before),
                    canonical_json(after),
                    _iso(_now()),
                ),
            )
        except sqlite3.DatabaseError as exc:
            raise AdminAuditError from exc
        if connection.total_changes != changes_before + 1:
            raise AdminAuditError

    def _tier(self, value: Any) -> tuple[str, str, str]:
        if not isinstance(value, str):
            raise AdminValidationError("tier must be <community_id>:<level_id>")
        community, separator, level = value.strip().partition(":")
        if not separator:
            raise AdminValidationError("tier must be <community_id>:<level_id>")
        community_id = _safe_id(community, "community_id")
        level_id = _safe_id(level, "level_id")
        key = f"{community_id}:{level_id}"
        if key not in self.config.skool_tier_mappings:
            raise AdminValidationError("tier is not mapped to a server-owned plan")
        return community_id, level_id, key

    @staticmethod
    def _task(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "workspace_id": int(row["workspace_id"]),
            "subject_user_id": int(row["subject_user_id"]),
            "member_name": str(row["member_name"]),
            "invite_email": str(row["invite_email"]),
            "community_id": str(row["community_id"]),
            "level_id": str(row["level_id"]),
            "tier": f"{row['community_id']}:{row['level_id']}",
            "state": str(row["state"]),
            "completion_source": (
                str(row["completion_source"])
                if row["completion_source"] is not None
                else None
            ),
            "external_mapping_id": (
                int(row["external_mapping_id"])
                if row["external_mapping_id"] is not None
                else None
            ),
            "completed_at": (
                str(row["completed_at"])
                if row["completed_at"] is not None
                else None
            ),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _task_row(
        connection: sqlite3.Connection,
        task_id: int,
        workspace_id: int,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT task.*,user.email AS invite_email,user.name AS member_name
            FROM platform_skool_join_tasks AS task
            JOIN platform_users AS user ON user.id=task.subject_user_id
            WHERE task.id=? AND task.workspace_id=?
            """,
            (task_id, workspace_id),
        ).fetchone()

    def create_join_task(
        self,
        workspace_public_id: str,
        *,
        actor_user_id: int,
        subject_user_id: Any,
        tier: Any,
        reason_code: Any,
        reason: Any,
    ) -> dict[str, Any]:
        subject_id = _positive_int(subject_user_id, "subject_user_id")
        community_id, level_id, tier_key = self._tier(tier)
        normalized_code, normalized_reason = validate_reason(reason_code, reason)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                actor = self._actor(connection, actor_user_id, mutate=True)
                workspace = self._workspace(connection, workspace_public_id)
                workspace_id = int(workspace["id"])
                membership = connection.execute(
                    """
                    SELECT 1 FROM platform_memberships
                    WHERE workspace_id=? AND user_id=?
                    """,
                    (workspace_id, subject_id),
                ).fetchone()
                if membership is None:
                    raise AdminValidationError(
                        "subject_user_id must identify a workspace member"
                    )
                now = _iso(_now())
                try:
                    cursor = connection.execute(
                        """
                        INSERT INTO platform_skool_join_tasks(
                            workspace_id,subject_user_id,community_id,level_id,
                            state,requested_by,created_at,updated_at
                        ) VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            workspace_id,
                            subject_id,
                            community_id,
                            level_id,
                            "pending",
                            actor_user_id,
                            now,
                            now,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise AdminConflictError(
                        "An equivalent Skool join task is already pending"
                    ) from exc
                task_id = int(cursor.lastrowid)
                row = self._task_row(connection, task_id, workspace_id)
                assert row is not None
                task = self._task(row)
                task["community_url"] = self.config.skool_community_urls.get(
                    community_id
                )
                task["operator_steps"] = [
                    "Use Skool Admin Invite or the configured Zapier Invite action.",
                    "Do not call an undocumented Skool endpoint.",
                    "Wait until the member clicks JOIN NOW and the member id is visible.",
                    "Complete this task with that exact member id, then reconcile current state.",
                ]
                self._audit(
                    connection,
                    actor,
                    action="skool.join_task.create",
                    workspace_id=workspace_id,
                    target_type="skool_join_task",
                    target_id=str(task_id),
                    reason_code=normalized_code,
                    reason=normalized_reason,
                    before=None,
                    after={
                        "task_id": task_id,
                        "subject_user_id": subject_id,
                        "tier": tier_key,
                        "state": "pending",
                    },
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()
            return task

    def complete_join_task(
        self,
        workspace_public_id: str,
        task_id: Any,
        *,
        actor_user_id: int,
        external_member_id: Any,
        completion_source: Any,
        reason_code: Any,
        reason: Any,
    ) -> dict[str, Any]:
        normalized_task_id = _positive_int(task_id, "task_id")
        member_id = _safe_id(external_member_id, "external_member_id")
        source = _choice(
            completion_source,
            JOIN_COMPLETION_SOURCES,
            "completion_source",
        )
        normalized_code, normalized_reason = validate_reason(reason_code, reason)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                actor = self._actor(connection, actor_user_id, mutate=True)
                workspace = self._workspace(connection, workspace_public_id)
                workspace_id = int(workspace["id"])
                task_row = self._task_row(
                    connection,
                    normalized_task_id,
                    workspace_id,
                )
                if task_row is None:
                    raise AdminNotFoundError("Skool join task does not exist")
                if str(task_row["state"]) != "pending":
                    raise AdminConflictError("Skool join task is not pending")
                existing = connection.execute(
                    """
                    SELECT id,workspace_id,subject_user_id,metadata
                    FROM platform_external_accounts
                    WHERE provider='skool' AND external_account_id=?
                    """,
                    (member_id,),
                ).fetchone()
                if existing is not None and (
                    int(existing["workspace_id"]) != workspace_id
                    or int(existing["subject_user_id"])
                    != int(task_row["subject_user_id"])
                ):
                    raise AdminConflictError(
                        "Skool member id is already bound to another authority"
                    )
                now = _iso(_now())
                if existing is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO platform_external_accounts(
                            workspace_id,subject_user_id,provider,
                            external_account_id,metadata,created_at,updated_at
                        ) VALUES (?,?,?,?,?,?,?)
                        """,
                        (
                            workspace_id,
                            int(task_row["subject_user_id"]),
                            "skool",
                            member_id,
                            canonical_json(
                                {
                                    "community_id": str(task_row["community_id"]),
                                    "join_task_id": normalized_task_id,
                                    "level_id": str(task_row["level_id"]),
                                }
                            ),
                            now,
                            now,
                        ),
                    )
                    mapping_id = int(cursor.lastrowid)
                else:
                    mapping_id = int(existing["id"])
                    existing_community = self._community_for_mapping(
                        existing["metadata"]
                    )
                    if existing_community not in {
                        None,
                        str(task_row["community_id"]),
                    }:
                        raise AdminConflictError(
                            "Skool member id is bound to another community"
                        )
                    connection.execute(
                        """
                        UPDATE platform_external_accounts
                        SET metadata=?,updated_at=?
                        WHERE id=? AND workspace_id=?
                        """,
                        (
                            canonical_json(
                                {
                                    "community_id": str(task_row["community_id"]),
                                    "join_task_id": normalized_task_id,
                                    "level_id": str(task_row["level_id"]),
                                }
                            ),
                            now,
                            mapping_id,
                            workspace_id,
                        ),
                    )
                connection.execute(
                    """
                    UPDATE platform_skool_join_tasks
                    SET state='completed',completed_by=?,completion_source=?,
                        external_mapping_id=?,completed_at=?,updated_at=?
                    WHERE id=? AND workspace_id=?
                    """,
                    (
                        actor_user_id,
                        source,
                        mapping_id,
                        now,
                        now,
                        normalized_task_id,
                        workspace_id,
                    ),
                )
                completed = self._task_row(
                    connection,
                    normalized_task_id,
                    workspace_id,
                )
                assert completed is not None
                task = self._task(completed)
                self._audit(
                    connection,
                    actor,
                    action="skool.join_task.complete",
                    workspace_id=workspace_id,
                    target_type="skool_join_task",
                    target_id=str(normalized_task_id),
                    reason_code=normalized_code,
                    reason=normalized_reason,
                    before={"state": "pending"},
                    after={
                        "state": "completed",
                        "external_mapping_id": mapping_id,
                        "completion_source": source,
                    },
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()
            return {
                "task": task,
                "grant_created": False,
                "next_gate": (
                    "A signed member event or confirmed current-state review is "
                    "required before access can be granted."
                ),
            }

    def _community_for_mapping(self, metadata_raw: Any) -> str | None:
        try:
            metadata = json.loads(str(metadata_raw))
        except (TypeError, ValueError):
            return None
        community = (
            metadata.get("community_id")
            if isinstance(metadata, dict)
            else None
        )
        if isinstance(community, str) and _SAFE_ID.fullmatch(community.strip()):
            return community.strip()
        communities = {
            key.partition(":")[0] for key in self.config.skool_tier_mappings
        }
        return next(iter(communities)) if len(communities) == 1 else None

    @staticmethod
    def _normalize_members(value: Any) -> tuple[dict[str, str], ...]:
        if not isinstance(value, list):
            raise AdminValidationError("members must be a JSON array")
        if len(value) > 10_000:
            raise AdminValidationError("members cannot exceed 10000 entries")
        members: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                raise AdminValidationError("each member must be a JSON object")
            member_id = _safe_id(item.get("member_id"), "member_id")
            if member_id in seen:
                raise AdminValidationError("member ids must be unique")
            seen.add(member_id)
            status = _choice(item.get("status"), MEMBER_STATES, "status")
            normalized = {"member_id": member_id, "status": status}
            if status == "active":
                normalized["level_id"] = _safe_id(item.get("level_id"), "level_id")
            members.append(normalized)
        return tuple(sorted(members, key=lambda item: item["member_id"]))

    def _artifact(
        self,
        value: Any,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise AdminValidationError("artifact must be a JSON object")
        community_id = _safe_id(value.get("community_id"), "community_id")
        source = _choice(value.get("source"), RECONCILIATION_SOURCES, "source")
        confidence = _choice(
            value.get("confidence"),
            RECONCILIATION_CONFIDENCE,
            "confidence",
        )
        complete = value.get("complete")
        if not isinstance(complete, bool):
            raise AdminValidationError("complete must be true or false")
        observed = _observed_at(value.get("observed_at"))
        if observed > now + timedelta(minutes=5):
            raise AdminValidationError("observed_at cannot be in the future")
        members = self._normalize_members(value.get("members"))
        age_seconds = max(0, int((now - observed).total_seconds()))
        current = age_seconds <= self.config.skool_reconciliation_max_age_seconds
        can_strengthen = complete and current and confidence == "confirmed"
        if not complete:
            reason_code = "artifact_incomplete"
        elif not current:
            reason_code = "evidence_stale"
        elif confidence != "confirmed":
            reason_code = "confidence_unverified"
        else:
            reason_code = "confirmed_current_state"
        normalized = {
            "community_id": community_id,
            "source": source,
            "observed_at": _iso(observed),
            "confidence": confidence,
            "complete": complete,
            "members": list(members),
        }
        digest = hashlib.sha256(
            (
                "medawarcre.skool.current-state.v1\0"
                + canonical_json(normalized)
            ).encode("utf-8")
        ).hexdigest()
        return {
            **normalized,
            "members": members,
            "artifact_hash": f"sha256:{digest}",
            "age_seconds": age_seconds,
            "current": current,
            "can_strengthen": can_strengthen,
            "reason_code": reason_code,
        }

    @staticmethod
    def _event_id(
        artifact_hash: str,
        mapping_id: int,
        action: str,
    ) -> str:
        digest = hashlib.sha256(
            f"{artifact_hash}\0{mapping_id}\0{action}".encode("utf-8")
        ).hexdigest()
        return f"skool_reconcile_{digest}"

    def reconcile_workspace(
        self,
        workspace_public_id: str,
        *,
        actor_user_id: int,
        artifact: Any,
        reason_code: Any,
        reason: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        operation_time = (now or _now()).astimezone(UTC)
        normalized = self._artifact(artifact, now=operation_time)
        normalized_code, normalized_reason = validate_reason(reason_code, reason)
        members = {item["member_id"]: item for item in normalized["members"]}
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                actor = self._actor(connection, actor_user_id, mutate=True)
                workspace = self._workspace(connection, workspace_public_id)
                workspace_id = int(workspace["id"])
                duplicate = connection.execute(
                    """
                    SELECT id FROM platform_skool_reconciliations
                    WHERE artifact_hash=?
                    """,
                    (normalized["artifact_hash"],),
                ).fetchone()
                if duplicate is not None:
                    raise AdminConflictError(
                        "This Skool current-state artifact was already reconciled"
                    )
                all_mappings = connection.execute(
                    """
                    SELECT account.id,account.external_account_id,
                           account.subject_user_id,account.metadata,
                           grant.status AS grant_status,
                           grant.plan_key AS grant_plan_key,
                           grant.profile AS grant_profile
                    FROM platform_external_accounts AS account
                    LEFT JOIN platform_access_grants AS grant
                      ON grant.workspace_id=account.workspace_id
                     AND grant.source='skool'
                     AND grant.external_ref=account.external_account_id
                    WHERE account.workspace_id=? AND account.provider='skool'
                    ORDER BY account.id
                    """,
                    (workspace_id,),
                ).fetchall()
                mappings = [
                    row
                    for row in all_mappings
                    if self._community_for_mapping(row["metadata"])
                    == normalized["community_id"]
                ]
                if not mappings:
                    raise AdminValidationError(
                        "No exact Skool member mappings exist for this community"
                    )

                results: list[dict[str, Any]] = []
                discrepancy_count = 0
                conflict_count = 0
                mapped_ids = {str(row["external_account_id"]) for row in mappings}
                unmapped_member_count = len(set(members).difference(mapped_ids))
                discrepancy_count += unmapped_member_count
                conflict_count += unmapped_member_count
                for row in mappings:
                    member_id = str(row["external_account_id"])
                    member = members.get(member_id)
                    event: NormalizedProviderEvent | None = None
                    tier_mismatch = False
                    if member is None:
                        if normalized["can_strengthen"]:
                            event = NormalizedProviderEvent(
                                provider="skool",
                                event_id=self._event_id(
                                    normalized["artifact_hash"],
                                    int(row["id"]),
                                    "remove",
                                ),
                                event_type="skool.reconciliation.missing",
                                occurred_at=_observed_at(normalized["observed_at"]),
                                action="remove",
                                external_account_id=member_id,
                                external_object_id=member_id,
                                subscription_status="canceled",
                            )
                    elif member["status"] == "active":
                        tier_key = (
                            f"{normalized['community_id']}:{member['level_id']}"
                        )
                        tier_mismatch = (
                            tier_key not in self.config.skool_tier_mappings
                        )
                        if normalized["can_strengthen"]:
                            event = NormalizedProviderEvent(
                                provider="skool",
                                event_id=self._event_id(
                                    normalized["artifact_hash"],
                                    int(row["id"]),
                                    (
                                        "remove_tier_mismatch"
                                        if tier_mismatch
                                        else "membership_update"
                                    ),
                                ),
                                event_type=(
                                    "skool.reconciliation.tier_mismatch"
                                    if tier_mismatch
                                    else "skool.reconciliation.member"
                                ),
                                occurred_at=_observed_at(normalized["observed_at"]),
                                action=(
                                    "remove"
                                    if tier_mismatch
                                    else "membership_update"
                                ),
                                external_account_id=member_id,
                                external_object_id=member_id,
                                subscription_status=(
                                    "canceled" if tier_mismatch else "active"
                                ),
                                mapping_keys=(() if tier_mismatch else (tier_key,)),
                            )
                    elif normalized["can_strengthen"]:
                        action = RESTRICTIVE_ACTIONS[member["status"]]
                        event = NormalizedProviderEvent(
                            provider="skool",
                            event_id=self._event_id(
                                normalized["artifact_hash"],
                                int(row["id"]),
                                action,
                            ),
                            event_type=f"skool.reconciliation.{member['status']}",
                            occurred_at=_observed_at(normalized["observed_at"]),
                            action=action,
                            external_account_id=member_id,
                            external_object_id=member_id,
                            subscription_status="canceled",
                        )

                    if event is None:
                        discrepancy_count += 1
                        results.append(
                            {
                                "external_mapping_id": int(row["id"]),
                                "outcome": "not_applied",
                                "reason_code": normalized["reason_code"],
                            }
                        )
                        continue
                    if tier_mismatch:
                        conflict_count += 1
                    if (
                        member is None
                        or member["status"] != "active"
                        or str(row["grant_status"] or "") != "active"
                        or tier_mismatch
                    ):
                        discrepancy_count += 1
                    result = self.sync.ingest_tx(connection, event)
                    if result.outcome == "quarantined":
                        conflict_count += 1
                    results.append(
                        {
                            "external_mapping_id": int(row["id"]),
                            "outcome": result.outcome,
                            "reason_code": result.reason_code,
                        }
                    )

                if not normalized["can_strengthen"]:
                    certainty = "uncertain"
                    final_reason = normalized["reason_code"]
                elif conflict_count:
                    certainty = "conflict"
                    final_reason = "mapping_conflict"
                else:
                    certainty = "confirmed"
                    final_reason = "confirmed_current_state"
                member_count = len(normalized["members"])
                mapped_member_count = len(mapped_ids.intersection(members))
                cursor = connection.execute(
                    """
                    INSERT INTO platform_skool_reconciliations(
                        workspace_id,community_id,artifact_hash,source,
                        observed_at,confidence,complete,certainty,reason_code,
                        member_count,mapped_member_count,discrepancy_count,
                        conflict_count,created_by,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        workspace_id,
                        normalized["community_id"],
                        normalized["artifact_hash"],
                        normalized["source"],
                        normalized["observed_at"],
                        normalized["confidence"],
                        int(normalized["complete"]),
                        certainty,
                        final_reason,
                        member_count,
                        mapped_member_count,
                        discrepancy_count,
                        conflict_count,
                        actor_user_id,
                        _iso(operation_time),
                    ),
                )
                reconciliation_id = int(cursor.lastrowid)
                report = {
                    "id": reconciliation_id,
                    "provider": "skool",
                    "community_id": normalized["community_id"],
                    "source": normalized["source"],
                    "observed_at": normalized["observed_at"],
                    "age_seconds": normalized["age_seconds"],
                    "confidence": normalized["confidence"],
                    "complete": normalized["complete"],
                    "certainty": certainty,
                    "reason_code": final_reason,
                    "member_count": member_count,
                    "mapped_member_count": mapped_member_count,
                    "unmapped_member_count": unmapped_member_count,
                    "discrepancy_count": discrepancy_count,
                    "conflict_count": conflict_count,
                    "results": results,
                }
                self._audit(
                    connection,
                    actor,
                    action="skool.reconcile",
                    workspace_id=workspace_id,
                    target_type="skool_current_state",
                    target_id=str(reconciliation_id),
                    reason_code=normalized_code,
                    reason=normalized_reason,
                    before=None,
                    after={
                        key: value
                        for key, value in report.items()
                        if key != "results"
                    },
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()
            return report

    def manual_revoke(
        self,
        workspace_public_id: str,
        mapping_id: Any,
        *,
        actor_user_id: int,
        reason_code: Any,
        reason: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_mapping_id = _positive_int(mapping_id, "mapping_id")
        normalized_code, normalized_reason = validate_reason(reason_code, reason)
        operation_time = (now or _now()).astimezone(UTC)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                actor = self._actor(connection, actor_user_id, mutate=True)
                workspace = self._workspace(connection, workspace_public_id)
                workspace_id = int(workspace["id"])
                mapping = connection.execute(
                    """
                    SELECT id,external_account_id,subject_user_id
                    FROM platform_external_accounts
                    WHERE id=? AND workspace_id=? AND provider='skool'
                    """,
                    (normalized_mapping_id, workspace_id),
                ).fetchone()
                if mapping is None:
                    raise AdminNotFoundError("Skool member mapping does not exist")
                subject_user_id = int(mapping["subject_user_id"])
                workspace_public = str(workspace["public_id"])
                active_sessions_before = connection.execute(
                    """
                    SELECT COUNT(*) FROM platform_oauth_sessions
                    WHERE workspace_id=? AND user_id=? AND revoked_at IS NULL
                    """,
                    (workspace_public, subject_user_id),
                ).fetchone()[0]
                codes_before = connection.execute(
                    """
                    SELECT COUNT(*) FROM platform_oauth_codes
                    WHERE workspace_id=? AND user_id=? AND consumed_at IS NULL
                    """,
                    (workspace_public, subject_user_id),
                ).fetchone()[0]
                before_grant = connection.execute(
                    """
                    SELECT status,plan_key,profile,ends_at
                    FROM platform_access_grants
                    WHERE workspace_id=? AND source='skool' AND external_ref=?
                    """,
                    (workspace_id, str(mapping["external_account_id"])),
                ).fetchone()
                state = {
                    "actor_user_id": actor_user_id,
                    "mapping_id": normalized_mapping_id,
                    "observed_at": _iso(operation_time),
                    "reason_code": normalized_code,
                }
                digest = hashlib.sha256(
                    canonical_json(state).encode("utf-8")
                ).hexdigest()
                event = NormalizedProviderEvent(
                    provider="skool",
                    event_id=f"skool_manual_revoke_{digest}",
                    event_type="skool.manual_revocation",
                    occurred_at=operation_time,
                    action="remove",
                    external_account_id=str(mapping["external_account_id"]),
                    external_object_id=str(mapping["external_account_id"]),
                    subscription_status="canceled",
                )
                result = self.sync.ingest_tx(connection, event)
                active_sessions_after = connection.execute(
                    """
                    SELECT COUNT(*) FROM platform_oauth_sessions
                    WHERE workspace_id=? AND user_id=? AND revoked_at IS NULL
                    """,
                    (workspace_public, subject_user_id),
                ).fetchone()[0]
                codes_after = connection.execute(
                    """
                    SELECT COUNT(*) FROM platform_oauth_codes
                    WHERE workspace_id=? AND user_id=? AND consumed_at IS NULL
                    """,
                    (workspace_public, subject_user_id),
                ).fetchone()[0]
                grant_after = connection.execute(
                    """
                    SELECT status,plan_key,profile,ends_at
                    FROM platform_access_grants
                    WHERE workspace_id=? AND source='skool' AND external_ref=?
                    """,
                    (workspace_id, str(mapping["external_account_id"])),
                ).fetchone()
                report = {
                    "provider": "skool",
                    "external_mapping_id": normalized_mapping_id,
                    "outcome": result.outcome,
                    "reason_code": result.reason_code,
                    "grant_status": (
                        str(grant_after["status"])
                        if grant_after is not None
                        else "absent"
                    ),
                    "oauth_sessions_revoked": int(active_sessions_before)
                    - int(active_sessions_after),
                    "pending_codes_consumed": int(codes_before) - int(codes_after),
                    "observed_at": _iso(operation_time),
                }
                self._audit(
                    connection,
                    actor,
                    action="skool.manual_revoke",
                    workspace_id=workspace_id,
                    target_type="skool_member_mapping",
                    target_id=str(normalized_mapping_id),
                    reason_code=normalized_code,
                    reason=normalized_reason,
                    before={
                        "grant": dict(before_grant) if before_grant else None,
                        "active_oauth_sessions": int(active_sessions_before),
                        "pending_oauth_codes": int(codes_before),
                    },
                    after={
                        "grant": dict(grant_after) if grant_after else None,
                        **report,
                    },
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()
            return report

    def status(
        self,
        workspace_public_id: str,
        *,
        actor_user_id: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        operation_time = (now or _now()).astimezone(UTC)
        with self._connect() as connection:
            self._actor(connection, actor_user_id, mutate=False)
            workspace = self._workspace(connection, workspace_public_id)
            workspace_id = int(workspace["id"])
            task_rows = connection.execute(
                """
                SELECT task.*,user.email AS invite_email,user.name AS member_name
                FROM platform_skool_join_tasks AS task
                JOIN platform_users AS user ON user.id=task.subject_user_id
                WHERE task.workspace_id=?
                ORDER BY task.created_at DESC,task.id DESC
                LIMIT 100
                """,
                (workspace_id,),
            ).fetchall()
            mapping_rows = connection.execute(
                """
                SELECT account.id,account.external_account_id,
                       account.subject_user_id,account.metadata,
                       user.email,user.name,
                       grant.status AS grant_status,
                       grant.plan_key AS grant_plan_key,
                       grant.profile AS grant_profile,
                       grant.ends_at AS grant_ends_at
                FROM platform_external_accounts AS account
                JOIN platform_users AS user ON user.id=account.subject_user_id
                LEFT JOIN platform_access_grants AS grant
                  ON grant.workspace_id=account.workspace_id
                 AND grant.source='skool'
                 AND grant.external_ref=account.external_account_id
                WHERE account.workspace_id=? AND account.provider='skool'
                ORDER BY account.id
                """,
                (workspace_id,),
            ).fetchall()
            latest = connection.execute(
                """
                SELECT * FROM platform_skool_reconciliations
                WHERE workspace_id=?
                ORDER BY observed_at DESC,id DESC LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
            if latest is None:
                reconciliation = {
                    "certainty": "uncertain",
                    "reason_code": "no_current_state_artifact",
                    "observed_at": None,
                    "age_seconds": None,
                    "stale": True,
                }
            else:
                observed = _observed_at(str(latest["observed_at"]))
                age_seconds = max(0, int((operation_time - observed).total_seconds()))
                stale = age_seconds > self.config.skool_reconciliation_max_age_seconds
                stored_certainty = str(latest["certainty"])
                reconciliation = {
                    "id": int(latest["id"]),
                    "community_id": str(latest["community_id"]),
                    "source": str(latest["source"]),
                    "observed_at": str(latest["observed_at"]),
                    "confidence": str(latest["confidence"]),
                    "complete": bool(latest["complete"]),
                    "certainty": "uncertain" if stale else stored_certainty,
                    "reason_code": (
                        "evidence_stale" if stale else str(latest["reason_code"])
                    ),
                    "age_seconds": age_seconds,
                    "stale": stale,
                    "member_count": int(latest["member_count"]),
                    "mapped_member_count": int(latest["mapped_member_count"]),
                    "discrepancy_count": int(latest["discrepancy_count"]),
                    "conflict_count": int(latest["conflict_count"]),
                }
            tiers = [
                {
                    "tier": key,
                    "community_id": key.partition(":")[0],
                    "level_id": key.partition(":")[2],
                    "plan_key": mapping.plan_key,
                    "profile": mapping.profile.value,
                    "community_url": self.config.skool_community_urls.get(
                        key.partition(":")[0]
                    ),
                }
                for key, mapping in sorted(self.config.skool_tier_mappings.items())
            ]
            mappings = [
                {
                    "id": int(row["id"]),
                    "external_member_id": str(row["external_account_id"]),
                    "subject_user_id": int(row["subject_user_id"]),
                    "member_name": str(row["name"]),
                    "member_email": str(row["email"]),
                    "community_id": self._community_for_mapping(row["metadata"]),
                    "grant_status": (
                        str(row["grant_status"])
                        if row["grant_status"] is not None
                        else "absent"
                    ),
                    "plan_key": (
                        str(row["grant_plan_key"])
                        if row["grant_plan_key"] is not None
                        else None
                    ),
                    "profile": (
                        str(row["grant_profile"])
                        if row["grant_profile"] is not None
                        else None
                    ),
                    "grant_ends_at": (
                        str(row["grant_ends_at"])
                        if row["grant_ends_at"] is not None
                        else None
                    ),
                }
                for row in mapping_rows
            ]
            return {
                "provider": "skool",
                "automation": "operator_task_only",
                "official_constraint": (
                    "No documented Skool member-removal or current-roster API is "
                    "called. Joining uses Admin Invite or Zapier Invite."
                ),
                "reconciliation": reconciliation,
                "join_tasks": [self._task(row) for row in task_rows],
                "mappings": mappings,
                "available_tiers": tiers,
            }


__all__ = [
    "JOIN_COMPLETION_SOURCES",
    "MEMBER_STATES",
    "RECONCILIATION_CONFIDENCE",
    "RECONCILIATION_SOURCES",
    "SkoolLifecycleService",
]
