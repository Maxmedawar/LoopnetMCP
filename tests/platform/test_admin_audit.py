"""Canonical, append-only, same-transaction internal admin audit tests."""

from __future__ import annotations

import json
import sqlite3

import pytest

from cre_mcp.platform.admin import AdminAuditError, AdminControlStore

from .admin_helpers import (
    VALID_REASON,
    api_client,
    audit_rows,
    config_for,
    provision_identity,
    provision_target,
)


async def test_audit_actor_and_canonical_snapshots_come_from_live_authority(tmp_path):
    config = config_for(tmp_path)
    actor = await provision_identity(
        config,
        "Audit Actor",
        internal_role="platform_admin",
    )
    target = await provision_target(config, "Audit Target")

    async with api_client(config) as client:
        response = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/territories",
            headers=actor.headers,
            json={
                "name": "Austin industrial",
                "state": "TX",
                "actor_user_id": 999999,
                "actor_role": "support",
                **VALID_REASON,
            },
        )

    assert response.status_code == 201
    rows = audit_rows(config.cache_db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_user_id"] == actor.user_id
    assert row["actor_role"] == "platform_admin"
    assert row["workspace_id"] == target.workspace_row_id
    assert row["action"] == "territory.create"
    assert row["target_type"] == "territory"
    assert row["target_id"] == str(response.json()["territory"]["id"])
    assert row["reason_code"] == VALID_REASON["reason_code"]
    assert row["reason"] == VALID_REASON["reason"]
    assert row["before_json"] == "null"
    assert row["after_json"] == json.dumps(
        response.json()["territory"],
        sort_keys=True,
        separators=(",", ":"),
    )


async def test_update_audit_has_before_and_after_snapshots(tmp_path):
    config = config_for(tmp_path)
    actor = await provision_identity(
        config,
        "Snapshot Actor",
        internal_role="platform_admin",
    )
    target = await provision_target(config, "Snapshot Target")

    async with api_client(config) as client:
        response = await client.patch(
            f"/v1/admin/workspaces/{target.workspace_id}"
            f"/memberships/{target.membership_id}",
            headers=actor.headers,
            json={"role": "viewer", **VALID_REASON},
        )

    assert response.status_code == 200
    row = audit_rows(config.cache_db_path)[0]
    before = json.loads(row["before_json"])
    after = json.loads(row["after_json"])
    assert before["role"] == "owner"
    assert after["role"] == "viewer"
    assert before["id"] == after["id"] == target.membership_id
    assert row["action"] == "membership.role.update"


async def test_audit_rows_are_sqlite_append_only(tmp_path):
    config = config_for(tmp_path)
    actor = await provision_identity(
        config,
        "Append Only Actor",
        internal_role="platform_admin",
    )
    target = await provision_target(config, "Append Only Target")

    async with api_client(config) as client:
        created = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/territories",
            headers=actor.headers,
            json={"name": "Immutable", **VALID_REASON},
        )
    assert created.status_code == 201
    audit_id = audit_rows(config.cache_db_path)[0]["id"]

    with sqlite3.connect(config.cache_db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append"):
            connection.execute(
                "UPDATE platform_admin_audit SET reason='tampered' WHERE id=?",
                (audit_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append"):
            connection.execute(
                "DELETE FROM platform_admin_audit WHERE id=?",
                (audit_id,),
            )


async def test_audit_insert_failure_rolls_back_mutation(tmp_path):
    config = config_for(tmp_path)
    actor = await provision_identity(
        config,
        "Audit Failure Actor",
        internal_role="platform_admin",
    )
    target = await provision_target(config, "Audit Failure Target")
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_admin_audit_insert
            BEFORE INSERT ON platform_admin_audit
            BEGIN
                SELECT RAISE(ABORT, 'injected audit failure');
            END
            """
        )

    async with api_client(config) as client:
        response = await client.post(
            f"/v1/admin/workspaces/{target.workspace_id}/territories",
            headers=actor.headers,
            json={"name": "Must Roll Back", **VALID_REASON},
        )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "admin_audit_failed",
            "message": "Admin mutation could not be audited",
        }
    }
    with sqlite3.connect(config.cache_db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_territories WHERE name='Must Roll Back'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_admin_audit"
        ).fetchone()[0] == 0


async def test_mutation_callback_cannot_inject_an_extra_audit_row(tmp_path):
    config = config_for(tmp_path)
    actor = await provision_identity(
        config,
        "Audit Injection Actor",
        internal_role="platform_admin",
    )
    store = AdminControlStore(config.cache_db_path)

    def inject_audit(connection):
        connection.execute(
            """
            INSERT INTO platform_admin_audit(
                actor_user_id,actor_role,action,workspace_id,
                target_type,target_id,reason_code,reason,
                before_json,after_json,created_at
            ) VALUES (?,?,'injected',NULL,'test','test',?,?,'null','null',?)
            """,
            (
                actor.user_id,
                "platform_admin",
                VALID_REASON["reason_code"],
                VALID_REASON["reason"],
                "2026-07-28T12:00:00+00:00",
            ),
        )
        raise AssertionError("The callback audit insert should be blocked")

    with pytest.raises(AdminAuditError):
        store._mutate(
            actor_user_id=actor.user_id,
            reason_code=VALID_REASON["reason_code"],
            reason=VALID_REASON["reason"],
            operation=inject_audit,
        )

    assert audit_rows(config.cache_db_path) == []
