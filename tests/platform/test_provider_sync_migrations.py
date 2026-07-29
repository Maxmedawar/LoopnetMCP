"""Provider-sync fresh, upgrade, integrity, and repeat-init probes."""

from __future__ import annotations

import sqlite3

from cre_mcp.platform.entitlements import EntitlementStore, _ENTITLEMENT_SCHEMA
from cre_mcp.platform.migrations import current_version
from cre_mcp.platform.schema import SCHEMA


def test_provider_sync_v2_fresh_schema_has_subjects_and_attempts(tmp_path):
    path = tmp_path / "fresh.db"

    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        event_columns = {
            row[1]: row
            for row in connection.execute(
                "PRAGMA table_info(platform_provider_events)"
            )
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list(platform_provider_events)"
            )
        }
        version = current_version(connection, "provider-sync")
        grant_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(platform_access_grants)"
            )
        }

    assert version == 2
    assert "subject_user_id" in grant_columns
    assert event_columns["workspace_id"][3] == 0
    assert {"outcome", "reason_code", "normalized_data"} <= set(event_columns)
    assert "platform_provider_event_attempts" in tables
    assert any("provider" in name or "sqlite_autoindex" in name for name in indexes)


def test_provider_sync_v2_upgrades_real_base_schema_without_identity_loss(tmp_path):
    path = tmp_path / "base-v0.db"
    now = "2026-07-28T12:00:00+00:00"
    raw_pii = '{"email":"legacy-private@example.test","raw":"legacy-body"}'
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        connection.execute(
            """
            INSERT INTO platform_workspaces(public_id,name,created_at,updated_at)
            VALUES ('ws-provider-base','Provider Base',?,?)
            """,
            (now, now),
        )
        workspace_id = connection.execute(
            "SELECT id FROM platform_workspaces WHERE public_id='ws-provider-base'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO platform_provider_events(
                id,workspace_id,provider,event_id,event_type,payload,
                occurred_at,created_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                41,
                workspace_id,
                "stripe",
                "evt_legacy",
                "customer.subscription.updated",
                raw_pii,
                now,
                now,
            ),
        )

    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM platform_provider_events WHERE id=41"
        ).fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        version = current_version(connection, "provider-sync")
        dump = "\n".join(connection.iterdump())

    assert version == 2
    assert row["provider"] == "stripe"
    assert row["event_id"] == "evt_legacy"
    assert row["workspace_id"] == workspace_id
    assert row["payload"] == "{}"
    assert row["outcome"] == "applied"
    assert "legacy-private@example.test" not in dump
    assert "legacy-body" not in dump
    assert foreign_keys == []
    assert integrity == "ok"


def test_provider_sync_repeat_initialization_is_idempotent(tmp_path):
    path = tmp_path / "repeat.db"

    EntitlementStore(path)
    EntitlementStore(path)
    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        assert current_version(connection, "provider-sync") == 2
        assert connection.execute(
            """
            SELECT COUNT(*) FROM platform_schema_versions
            WHERE component='provider-sync'
            """
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_provider_events"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_provider_event_attempts"
        ).fetchone()[0] == 0


def test_provider_sync_v1_preserves_deleted_legacy_sequence_high_water(tmp_path):
    path = tmp_path / "base-sequence-v0.db"
    now = "2026-07-28T12:00:00+00:00"
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        connection.execute(
            """
            INSERT INTO platform_workspaces(public_id,name,created_at,updated_at)
            VALUES ('ws-provider-sequence','Provider Sequence',?,?)
            """,
            (now, now),
        )
        workspace_id = connection.execute(
            "SELECT id FROM platform_workspaces WHERE public_id='ws-provider-sequence'"
        ).fetchone()[0]
        for event_id in (41, 99):
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    id,workspace_id,provider,event_id,event_type,payload,
                    occurred_at,created_at
                ) VALUES (?,?,?,?,?,'{}',?,?)
                """,
                (
                    event_id,
                    workspace_id,
                    "stripe",
                    f"evt_legacy_{event_id}",
                    "customer.subscription.updated",
                    now,
                    now,
                ),
            )
        connection.execute(
            "DELETE FROM platform_provider_events WHERE id=99"
        )
        assert connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='platform_provider_events'"
        ).fetchone()[0] == 99

    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO platform_provider_events(
                workspace_id,provider,event_id,event_type,payload,
                normalized_data,occurred_at,outcome,created_at,updated_at
            ) VALUES (?,'stripe','evt_after_upgrade','unsupported','{}','{}',
                      ?,'rejected',?,?)
            """,
            (workspace_id, now, now, now),
        )

    assert cursor.lastrowid == 100
