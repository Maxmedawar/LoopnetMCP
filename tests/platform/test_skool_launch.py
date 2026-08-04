"""Skool operator lifecycle, uncertainty, and revocation launch contract."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from cre_mcp.platform.admin import AdminConflictError
from cre_mcp.platform.api import starlette_app
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.providers.skool_lifecycle import SkoolLifecycleService
from cre_mcp.platform.repository import PlatformRepository

from .admin_helpers import _seed_internal_admin, audit_rows
from .provider_helpers import (
    SKOOL_SECRET,
    api_client,
    json_bytes,
    provider_config,
    seed_workspace,
    signed_headers,
    skool_event,
)


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
ROTATED_SECRET = "relay_test_skool_rotated"
REASON = {
    "reason_code": "entitlement_correction",
    "reason": "Verified against the internal Skool operations runbook.",
}


def _subject_id(path, workspace_row_id: int) -> int:
    with sqlite3.connect(path) as connection:
        return int(
            connection.execute(
                "SELECT user_id FROM platform_memberships WHERE workspace_id=?",
                (workspace_row_id,),
            ).fetchone()[0]
        )


def _grant_status(path, workspace_row_id: int) -> str | None:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT status FROM platform_access_grants
            WHERE workspace_id=? AND source='skool'
            ORDER BY id DESC LIMIT 1
            """,
            (workspace_row_id,),
        ).fetchone()
    return str(row[0]) if row is not None else None


async def _lifecycle(tmp_path, *, name: str = "Skool Target"):
    config = provider_config(
        tmp_path,
        skool_community_urls={
            "community_1": "https://www.skool.com/medawar-cre"
        },
    )
    starlette_app(config)
    workspace = await seed_workspace(config, name)
    subject_id = _subject_id(config.cache_db_path, workspace.id)
    _seed_internal_admin(
        config.cache_db_path,
        user_id=subject_id,
        role="platform_admin",
        active=True,
    )
    return config, workspace, subject_id, SkoolLifecycleService(config)


def _join_and_bind(
    service: SkoolLifecycleService,
    workspace_id: str,
    subject_id: int,
    member_id: str,
) -> int:
    task = service.create_join_task(
        workspace_id,
        actor_user_id=subject_id,
        subject_user_id=subject_id,
        tier="community_1:level_local",
        **REASON,
    )
    completed = service.complete_join_task(
        workspace_id,
        task["id"],
        actor_user_id=subject_id,
        external_member_id=member_id,
        completion_source="manual_admin_invite",
        **REASON,
    )
    return int(completed["task"]["external_mapping_id"])


def _artifact(
    member_id: str,
    *,
    observed_at: datetime = NOW,
    level_id: str = "level_local",
    status: str = "active",
    complete: bool = True,
    confidence: str = "confirmed",
):
    member = {"member_id": member_id, "status": status}
    if status == "active":
        member["level_id"] = level_id
    return {
        "community_id": "community_1",
        "source": "operator_members_review",
        "observed_at": observed_at.isoformat(),
        "confidence": confidence,
        "complete": complete,
        "members": [member],
    }


async def test_join_task_is_operator_bounded_and_cannot_grant(tmp_path):
    config, workspace, subject_id, service = await _lifecycle(tmp_path)

    task = service.create_join_task(
        workspace.public_id,
        actor_user_id=subject_id,
        subject_user_id=subject_id,
        tier="community_1:level_local",
        **REASON,
    )
    completed = service.complete_join_task(
        workspace.public_id,
        str(task["id"]),
        actor_user_id=subject_id,
        external_member_id="member_operator_join",
        completion_source="zapier_invite",
        **REASON,
    )

    assert task["community_url"] == "https://www.skool.com/medawar-cre"
    assert any("JOIN NOW" in step for step in task["operator_steps"])
    assert completed["grant_created"] is False
    assert "signed member event" in completed["next_gate"]
    assert _grant_status(config.cache_db_path, workspace.id) is None
    assert [row["action"] for row in audit_rows(config.cache_db_path)] == [
        "skool.join_task.create",
        "skool.join_task.complete",
    ]


async def test_confirmed_current_state_grants_without_storing_roster(tmp_path):
    config, workspace, subject_id, service = await _lifecycle(tmp_path)
    _join_and_bind(
        service,
        workspace.public_id,
        subject_id,
        "member_confirmed",
    )

    report = service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=subject_id,
        artifact=_artifact("member_confirmed"),
        now=NOW,
        **REASON,
    )

    assert report["certainty"] == "confirmed"
    assert report["mapped_member_count"] == 1
    assert report["unmapped_member_count"] == 0
    assert report["results"][0]["outcome"] == "applied"
    assert _grant_status(config.cache_db_path, workspace.id) == "active"
    with sqlite3.connect(config.cache_db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(platform_skool_reconciliations)"
            )
        }
        receipt = connection.execute(
            "SELECT artifact_hash FROM platform_skool_reconciliations"
        ).fetchone()[0]
    assert "members" not in columns
    assert str(receipt).startswith("sha256:")


@pytest.mark.parametrize(
    "artifact,reason_code",
    [
        (
            _artifact(
                "member_uncertain",
                observed_at=NOW - timedelta(days=2),
            ),
            "evidence_stale",
        ),
        (
            _artifact("member_uncertain", complete=False),
            "artifact_incomplete",
        ),
        (
            _artifact("member_uncertain", confidence="unverified"),
            "confidence_unverified",
        ),
    ],
)
async def test_uncertain_evidence_never_strengthens(
    tmp_path,
    artifact,
    reason_code,
):
    config, workspace, subject_id, service = await _lifecycle(tmp_path)
    _join_and_bind(
        service,
        workspace.public_id,
        subject_id,
        "member_uncertain",
    )

    report = service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=subject_id,
        artifact=artifact,
        now=NOW,
        **REASON,
    )

    assert report["certainty"] == "uncertain"
    assert report["reason_code"] == reason_code
    assert report["results"][0]["outcome"] == "not_applied"
    assert _grant_status(config.cache_db_path, workspace.id) is None


async def test_missing_member_and_tier_mismatch_revoke_instead_of_granting(
    tmp_path,
):
    config, workspace, subject_id, service = await _lifecycle(tmp_path)
    _join_and_bind(
        service,
        workspace.public_id,
        subject_id,
        "member_mismatch",
    )
    service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=subject_id,
        artifact=_artifact("member_mismatch"),
        now=NOW,
        **REASON,
    )
    assert _grant_status(config.cache_db_path, workspace.id) == "active"

    mismatch_time = NOW + timedelta(minutes=1)
    mismatch = service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=subject_id,
        artifact=_artifact(
            "member_mismatch",
            observed_at=mismatch_time,
            level_id="level_unmapped",
        ),
        now=mismatch_time,
        **REASON,
    )
    assert mismatch["certainty"] == "conflict"
    assert mismatch["results"][0]["outcome"] == "applied"
    assert _grant_status(config.cache_db_path, workspace.id) == "revoked"

    missing_time = NOW + timedelta(minutes=2)
    missing_artifact = _artifact(
        "member_mismatch",
        observed_at=missing_time,
    )
    missing_artifact["members"] = []
    missing = service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=subject_id,
        artifact=missing_artifact,
        now=missing_time,
        **REASON,
    )
    assert missing["certainty"] == "confirmed"
    assert missing["results"][0]["outcome"] in {"applied", "stale"}
    assert _grant_status(config.cache_db_path, workspace.id) == "revoked"


async def test_duplicate_and_reordered_artifacts_are_same_receipt(tmp_path):
    config, workspace, subject_id, service = await _lifecycle(tmp_path)
    repository = PlatformRepository(config)
    second = await repository.create_user(
        "second-skool-member@example.test",
        "Second Skool Member",
    )
    assert second is not None
    assert await repository.add_membership(workspace.public_id, second.id, "member")
    _join_and_bind(
        service,
        workspace.public_id,
        subject_id,
        "member_first",
    )
    task = service.create_join_task(
        workspace.public_id,
        actor_user_id=subject_id,
        subject_user_id=second.id,
        tier="community_1:level_national",
        **REASON,
    )
    service.complete_join_task(
        workspace.public_id,
        task["id"],
        actor_user_id=subject_id,
        external_member_id="member_second",
        completion_source="manual_admin_invite",
        **REASON,
    )
    artifact = _artifact("member_first")
    artifact["members"].append(
        {
            "member_id": "member_second",
            "status": "active",
            "level_id": "level_national",
        }
    )
    service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=subject_id,
        artifact=artifact,
        now=NOW,
        **REASON,
    )
    artifact["members"].reverse()

    with pytest.raises(AdminConflictError, match="already reconciled"):
        service.reconcile_workspace(
            workspace.public_id,
            actor_user_id=subject_id,
            artifact=artifact,
            now=NOW,
            **REASON,
        )


async def test_mapping_conflict_is_fail_closed(tmp_path):
    config, workspace, subject_id, service = await _lifecycle(tmp_path)
    repository = PlatformRepository(config)
    second = await repository.create_user(
        "conflicting-skool-member@example.test",
        "Conflicting Skool Member",
    )
    assert second is not None
    assert await repository.add_membership(workspace.public_id, second.id, "member")
    _join_and_bind(
        service,
        workspace.public_id,
        subject_id,
        "member_bound_once",
    )
    task = service.create_join_task(
        workspace.public_id,
        actor_user_id=subject_id,
        subject_user_id=second.id,
        tier="community_1:level_local",
        **REASON,
    )

    with pytest.raises(AdminConflictError, match="another authority"):
        service.complete_join_task(
            workspace.public_id,
            task["id"],
            actor_user_id=subject_id,
            external_member_id="member_bound_once",
            completion_source="manual_admin_invite",
            **REASON,
        )


async def test_manual_revoke_removes_grant_and_oauth_session(tmp_path):
    config, workspace, subject_id, service = await _lifecycle(tmp_path)
    mapping_id = _join_and_bind(
        service,
        workspace.public_id,
        subject_id,
        "member_manual_revoke",
    )
    service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=subject_id,
        artifact=_artifact("member_manual_revoke"),
        now=NOW,
        **REASON,
    )
    auth = OAuthSessionStore(config.cache_db_path)
    client = auth.register_client(
        "Skool revocation client",
        ("https://client.example.test/callback",),
        (),
    )
    tokens = auth.issue_session(
        workspace.public_id,
        subject_id,
        client.client_id,
    )
    assert auth.validate_access(tokens.access_token) is not None

    report = service.manual_revoke(
        workspace.public_id,
        str(mapping_id),
        actor_user_id=subject_id,
        now=NOW + timedelta(minutes=1),
        **REASON,
    )

    assert report["grant_status"] == "revoked"
    assert report["oauth_sessions_revoked"] == 1
    assert auth.validate_access(tokens.access_token) is None
    assert audit_rows(config.cache_db_path)[-1]["action"] == "skool.manual_revoke"


async def test_skool_rotating_relay_secrets_accept_current_and_rotating(tmp_path):
    config = provider_config(
        tmp_path,
        skool_webhook_secret=None,
        skool_webhook_secrets=(SKOOL_SECRET, ROTATED_SECRET),
    )
    body = json_bytes(
        skool_event("skool_rotating_secret", member_id="member_unknown")
    )

    async with api_client(config) as client:
        current = await client.post(
            "/v1/webhooks/skool",
            content=body,
            headers=signed_headers("skool", body, secret=SKOOL_SECRET),
        )
        duplicate = await client.post(
            "/v1/webhooks/skool",
            content=body,
            headers=signed_headers("skool", body, secret=ROTATED_SECRET),
        )
        denied = await client.post(
            "/v1/webhooks/skool",
            content=body,
            headers=signed_headers("skool", body, secret="retired_relay"),
        )

    assert current.status_code == 202
    assert duplicate.status_code == 200
    assert duplicate.json()["outcome"] == "duplicate"
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "invalid_webhook_signature"
