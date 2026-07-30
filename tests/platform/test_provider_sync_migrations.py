"""Provider-sync fresh, upgrade, integrity, and repeat-init probes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.platform.entitlements import (
    ENTITLEMENT_MIGRATIONS,
    PROVIDER_SYNC_MIGRATIONS,
    EntitlementStore,
    _ENTITLEMENT_SCHEMA,
)
from cre_mcp.platform.migrations import apply_migrations, current_version
from cre_mcp.platform.providers.core import ProviderSyncService
from cre_mcp.platform.schema import SCHEMA, create_schema


def test_provider_sync_v4_fresh_schema_has_scopes_hashes_and_attempts(tmp_path):
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

    assert version == 5
    assert {"subject_user_id", "scope"} <= grant_columns
    assert event_columns["workspace_id"][3] == 0
    assert {
        "outcome",
        "reason_code",
        "normalized_data",
        "object_stream_hash",
        "restrictive_rank",
    } <= set(event_columns)
    assert "platform_provider_event_attempts" in tables
    assert "idx_platform_provider_event_stream_order" in indexes


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

    assert version == 5
    assert row["provider"] == "stripe"
    assert row["event_id"] == "evt_legacy"
    assert row["workspace_id"] == workspace_id
    assert row["payload"] == "{}"
    assert row["outcome"] == "quarantined"
    assert row["reason_code"] == "legacy_receipt_binding_untrusted"
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
        assert current_version(connection, "provider-sync") == 5
        assert connection.execute(
            """
            SELECT COUNT(*) FROM platform_schema_versions
            WHERE component='provider-sync'
            """
        ).fetchone()[0] == 5
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


def test_provider_sync_v3_backfills_scopes_and_fails_closed_ambiguity(tmp_path):
    path = tmp_path / "provider-v2-scope-upgrade.db"
    now = "2026-07-28T12:00:00+00:00"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        apply_migrations(connection, "entitlements", ENTITLEMENT_MIGRATIONS)
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS[:2],
        )
        for plan_key in ("local", "jv"):
            connection.execute(
                """
                INSERT INTO platform_plans(
                    key,name,daily_quotas,created_at,updated_at
                ) VALUES (?,?, '{}',?,?)
                """,
                (plan_key, plan_key.title(), now, now),
            )
        workspace_id = int(
            connection.execute(
                """
                INSERT INTO platform_workspaces(
                    public_id,name,created_at,updated_at
                ) VALUES ('ws-ambiguous-scope','Ambiguous Scope',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        user_ids = []
        for index in range(2):
            user_id = int(
                connection.execute(
                    """
                    INSERT INTO platform_users(email,name,created_at,updated_at)
                    VALUES (?,?,?,?) RETURNING id
                    """,
                    (
                        f"scope-{index}@example.test",
                        f"Scope {index}",
                        now,
                        now,
                    ),
                ).fetchone()[0]
            )
            user_ids.append(user_id)
            connection.execute(
                """
                INSERT INTO platform_memberships(
                    workspace_id,user_id,role,created_at,updated_at
                ) VALUES (?,?,'member',?,?)
                """,
                (workspace_id, user_id, now, now),
            )
        for source, external_ref, profile in (
            ("manual", "legacy-ambiguous-manual", "local_scout"),
            ("jv", "legacy-workspace-jv", "jv_partner"),
        ):
            connection.execute(
                """
                INSERT INTO platform_access_grants(
                    workspace_id,source,external_ref,profile,plan_key,status,
                    starts_at,ends_at,created_at,updated_at
                ) VALUES (?,?,?,?,?,'active',?,NULL,?,?)
                """,
                (
                    workspace_id,
                    source,
                    external_ref,
                    profile,
                    "jv" if source == "jv" else "local",
                    now,
                    now,
                    now,
                ),
            )
        no_survivor_workspace_id = int(
            connection.execute(
                """
                INSERT INTO platform_workspaces(
                    public_id,name,created_at,updated_at
                ) VALUES ('ws-no-scope-survivor','No Scope Survivor',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        no_survivor_user_ids = []
        for index in range(2):
            user_id = int(
                connection.execute(
                    """
                    INSERT INTO platform_users(email,name,created_at,updated_at)
                    VALUES (?,?,?,?) RETURNING id
                    """,
                    (
                        f"no-survivor-{index}@example.test",
                        f"No Survivor {index}",
                        now,
                        now,
                    ),
                ).fetchone()[0]
            )
            no_survivor_user_ids.append(user_id)
            connection.execute(
                """
                INSERT INTO platform_memberships(
                    workspace_id,user_id,role,created_at,updated_at
                ) VALUES (?,?,'member',?,?)
                """,
                (no_survivor_workspace_id, user_id, now, now),
            )
        connection.execute(
            """
            INSERT INTO platform_access_grants(
                workspace_id,source,external_ref,profile,plan_key,status,
                starts_at,ends_at,created_at,updated_at
            ) VALUES (
                ?,'promotion','legacy-ambiguous-promotion','local_scout',
                'local','active',?,NULL,?,?
            )
            """,
            (no_survivor_workspace_id, now, now, now),
        )
        connection.execute(
            """
            CREATE TABLE platform_oauth_sessions(
                id INTEGER PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                revoked_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        for index, user_id in enumerate(user_ids, start=1):
            connection.execute(
                """
                INSERT INTO platform_oauth_sessions(
                    id,workspace_id,user_id,revoked_at,updated_at
                ) VALUES (?,'ws-ambiguous-scope',?,NULL,?)
                """,
                (index, user_id, now),
            )
        for index, user_id in enumerate(no_survivor_user_ids, start=3):
            connection.execute(
                """
                INSERT INTO platform_oauth_sessions(
                    id,workspace_id,user_id,revoked_at,updated_at
                ) VALUES (?,'ws-no-scope-survivor',?,NULL,?)
                """,
                (index, user_id, now),
            )
        connection.execute(
            """
            INSERT INTO platform_provider_events(
                workspace_id,provider,event_id,event_type,payload,
                normalized_data,occurred_at,outcome,created_at,updated_at
            ) VALUES (
                ?,'stripe','evt-v2-backfill','customer.subscription.deleted',
                '{}',? ,?,'rejected',?,?
            )
            """,
            (
                workspace_id,
                json.dumps(
                    {
                        "provider": "stripe",
                        "event_id": "evt-v2-backfill",
                        "event_type": "customer.subscription.deleted",
                        "occurred_at": now,
                        "action": "cancel",
                        "external_object_id": "sub-v2-private",
                    },
                    sort_keys=True,
                ),
                now,
                now,
                now,
            ),
        )

    EntitlementStore(path)
    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        manual = connection.execute(
            """
            SELECT status,scope,subject_user_id
            FROM platform_access_grants
            WHERE external_ref='legacy-ambiguous-manual'
            """
        ).fetchone()
        jv = connection.execute(
            """
            SELECT status,scope,subject_user_id
            FROM platform_access_grants
            WHERE external_ref='legacy-workspace-jv'
            """
        ).fetchone()
        survivor_sessions = connection.execute(
            """
            SELECT revoked_at FROM platform_oauth_sessions
            WHERE workspace_id='ws-ambiguous-scope' ORDER BY id
            """
        ).fetchall()
        revoked_sessions = connection.execute(
            """
            SELECT revoked_at FROM platform_oauth_sessions
            WHERE workspace_id='ws-no-scope-survivor' ORDER BY id
            """
        ).fetchall()
        stream = connection.execute(
            """
            SELECT object_stream_hash,restrictive_rank,outcome,reason_code
            FROM platform_provider_events WHERE event_id='evt-v2-backfill'
            """
        ).fetchone()
        version = current_version(connection, "provider-sync")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert version == 5
    assert manual["status"] == "revoked"
    assert manual["scope"] == "subject"
    assert manual["subject_user_id"] is None
    assert all(row["revoked_at"] is None for row in survivor_sessions)
    assert all(row["revoked_at"] is not None for row in revoked_sessions)
    assert jv["status"] == "active"
    assert jv["scope"] == "workspace"
    assert jv["subject_user_id"] is None
    assert stream["object_stream_hash"] is None
    assert stream["restrictive_rank"] == 1
    assert stream["outcome"] == "quarantined"
    assert stream["reason_code"] == "legacy_receipt_binding_untrusted"
    assert foreign_keys == []


def test_provider_sync_v3_rejects_invalid_live_scope_invariants(tmp_path):
    path = tmp_path / "provider-v3-triggers.db"
    now = "2026-07-28T12:00:00+00:00"
    EntitlementStore(path)
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        connection.execute(
            """
            INSERT INTO platform_plans(
                key,name,daily_quotas,created_at,updated_at
            ) VALUES ('local','Local','{}',?,?)
            """,
            (now, now),
        )
        workspace_id = int(
            connection.execute(
                """
                INSERT INTO platform_workspaces(
                    public_id,name,created_at,updated_at
                ) VALUES ('ws-trigger-scope','Trigger Scope',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        user_id = int(
            connection.execute(
                """
                INSERT INTO platform_users(email,name,created_at,updated_at)
                VALUES ('trigger-scope@example.test','Trigger Scope',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO platform_memberships(
                workspace_id,user_id,role,created_at,updated_at
            ) VALUES (?,?,'owner',?,?)
            """,
            (workspace_id, user_id, now, now),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_access_grants(
                    workspace_id,subject_user_id,scope,source,external_ref,
                    profile,plan_key,status,starts_at,ends_at,created_at,updated_at
                ) VALUES (
                    ?,NULL,'workspace','manual','invalid-manual-workspace',
                    'local_scout','local','active',?,NULL,?,?
                )
                """,
                (workspace_id, now, now, now),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_access_grants(
                    workspace_id,subject_user_id,scope,source,external_ref,
                    profile,plan_key,status,starts_at,ends_at,created_at,updated_at
                ) VALUES (
                    ?,NULL,'subject','promotion','invalid-null-subject',
                    'local_scout','local','active',?,NULL,?,?
                )
                """,
                (workspace_id, now, now, now),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_access_grants(
                    workspace_id,subject_user_id,scope,source,external_ref,
                    profile,plan_key,status,starts_at,ends_at,created_at,updated_at
                ) VALUES (
                    ?,?,'workspace','jv','invalid-workspace-subject',
                    'jv_partner','local','active',?,NULL,?,?
                )
                """,
                (workspace_id, user_id, now, now, now),
            )


def test_provider_sync_v3_concurrent_initialization_is_idempotent(tmp_path):
    path = tmp_path / "provider-v3-concurrent.db"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        apply_migrations(connection, "entitlements", ENTITLEMENT_MIGRATIONS)
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS[:2],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(EntitlementStore, path) for _ in range(2)]
        for future in futures:
            future.result()

    with sqlite3.connect(path) as connection:
        assert current_version(connection, "provider-sync") == 5
        assert connection.execute(
            """
            SELECT COUNT(*) FROM platform_schema_versions
            WHERE component='provider-sync' AND version=5
            """
        ).fetchone()[0] == 1


def test_provider_sync_v3_failure_rolls_back_new_schema(tmp_path):
    path = tmp_path / "provider-v3-rollback.db"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        apply_migrations(connection, "entitlements", ENTITLEMENT_MIGRATIONS)
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS[:2],
        )

        def deny_index(action, _arg1, _arg2, _database, _source):
            if action == sqlite3.SQLITE_CREATE_INDEX:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_index)
        with pytest.raises(sqlite3.DatabaseError):
            apply_migrations(
                connection,
                "provider-sync",
                PROVIDER_SYNC_MIGRATIONS,
            )
        connection.set_authorizer(None)
        version = current_version(connection, "provider-sync")
        grant_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(platform_access_grants)"
            )
        }
        event_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(platform_provider_events)"
            )
        }

    assert version == 2
    assert "scope" not in grant_columns
    assert "object_stream_hash" not in event_columns


def _provider_hash(provider: str, external_id: str) -> str:
    return hashlib.sha256(f"{provider}\0{external_id}".encode()).hexdigest()


def test_provider_sync_v4_fresh_schema_has_write_once_receipt_bindings(
    tmp_path,
):
    path = tmp_path / "provider-v4-fresh.db"

    EntitlementStore(path)
    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        event_columns = {
            str(row[1]): row
            for row in connection.execute(
                "PRAGMA table_info(platform_provider_events)"
            )
        }
        triggers = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='trigger' AND tbl_name='platform_provider_events'
                """
            )
        }
        indexes = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA index_list(platform_provider_events)"
            )
        }
        foreign_keys = {
            str(row[3]): (str(row[2]), str(row[6]))
            for row in connection.execute(
                "PRAGMA foreign_key_list(platform_provider_events)"
            )
        }
        version = current_version(connection, "provider-sync")
        version_rows = connection.execute(
            """
            SELECT COUNT(*) FROM platform_schema_versions
            WHERE component='provider-sync'
            """
        ).fetchone()[0]

    assert version == 5
    assert version_rows == 5
    assert {
        "canonical_action",
        "external_account_hash",
        "bound_subject_user_id",
        "bound_scope",
    } <= set(event_columns)
    assert event_columns["canonical_action"][3] == 0
    assert event_columns["external_account_hash"][3] == 0
    assert event_columns["bound_subject_user_id"][3] == 0
    assert event_columns["bound_scope"][3] == 0
    assert {
        "platform_provider_event_binding_insert",
        "platform_provider_event_binding_update",
        "platform_provider_event_binding_immutable",
    } <= triggers
    assert "idx_platform_provider_event_stream_order" in indexes
    assert foreign_keys["workspace_id"] == (
        "platform_workspaces",
        "CASCADE",
    )
    assert foreign_keys["bound_subject_user_id"] == (
        "platform_users",
        "NO ACTION",
    )


def test_provider_sync_v4_backfills_only_consistent_state_and_quarantines_legacy(
    tmp_path,
):
    path = tmp_path / "provider-v3-receipt-upgrade.db"
    now = "2026-07-28T12:00:00+00:00"
    account_id = "cus_v4_trusted_private"
    object_id = "sub_v4_trusted_private"
    forged_account_id = "cus_v4_forged_private"
    forged_object_id = "sub_v4_forged_private"
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        create_schema(connection)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        apply_migrations(connection, "entitlements", ENTITLEMENT_MIGRATIONS)
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS[:3],
        )
        connection.execute(
            """
            INSERT INTO platform_plans(
                key,name,daily_quotas,created_at,updated_at
            ) VALUES ('local','Local','{}',?,?)
            """,
            (now, now),
        )
        workspace_id = int(
            connection.execute(
                """
                INSERT INTO platform_workspaces(
                    public_id,name,created_at,updated_at
                ) VALUES ('ws-v4-backfill','V4 Backfill',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        subject_user_id = int(
            connection.execute(
                """
                INSERT INTO platform_users(email,name,created_at,updated_at)
                VALUES ('v4-backfill@example.test','V4 Backfill',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO platform_memberships(
                workspace_id,user_id,role,created_at,updated_at
            ) VALUES (?,?,'owner',?,?)
            """,
            (workspace_id, subject_user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_external_accounts(
                workspace_id,subject_user_id,provider,external_account_id,
                metadata,created_at,updated_at
            ) VALUES (?,?,'stripe',?,'{}',?,?)
            """,
            (workspace_id, subject_user_id, account_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_subscriptions(
                workspace_id,provider,external_subscription_id,
                external_customer_id,status,plan_key,current_period_end,
                last_event_at,created_at,updated_at
            ) VALUES (
                ?,'stripe',?,?,'active','local',NULL,?,?,?
            )
            """,
            (workspace_id, object_id, account_id, now, now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_access_grants(
                workspace_id,subject_user_id,scope,source,external_ref,
                profile,plan_key,status,starts_at,ends_at,created_at,updated_at
            ) VALUES (
                ?,?,'subject','stripe',?,'local_scout','local','active',
                ?,'2026-07-29T12:00:00+00:00',?,?
            )
            """,
            (workspace_id, subject_user_id, object_id, now, now, now),
        )
        trusted_normalized = json.dumps(
            {
                "provider": "stripe",
                "event_id": "evt_v4_trusted",
                "event_type": "customer.subscription.deleted",
                "occurred_at": now,
                "action": "pause",
                "external_account_id": forged_account_id,
                "external_object_id": forged_object_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        connection.execute(
            """
            INSERT INTO platform_provider_events(
                id,workspace_id,provider,event_id,event_type,payload,
                normalized_data,occurred_at,outcome,reason_code,
                duplicate_count,replayed_at,object_stream_hash,
                restrictive_rank,created_at,updated_at
            ) VALUES (
                41,?,'stripe','evt_v4_trusted',
                'customer.subscription.deleted','{}',?,?,
                'quarantined','projection_failure',0,NULL,?,1,?,?
            )
            """,
            (
                workspace_id,
                trusted_normalized,
                now,
                _provider_hash("stripe", object_id),
                now,
                now,
            ),
        )
        ambiguous_workspace_id = int(
            connection.execute(
                """
                INSERT INTO platform_workspaces(
                    public_id,name,created_at,updated_at
                ) VALUES ('ws-v4-ambiguous','V4 Ambiguous',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO platform_memberships(
                workspace_id,user_id,role,created_at,updated_at
            ) VALUES (?,?,'owner',?,?)
            """,
            (ambiguous_workspace_id, subject_user_id, now, now),
        )
        for suffix in ("a", "b"):
            legacy_account_id = f"cus_v4_legacy_private_{suffix}"
            legacy_object_id = f"sub_v4_legacy_private_{suffix}"
            connection.execute(
                """
                INSERT INTO platform_external_accounts(
                    workspace_id,subject_user_id,provider,external_account_id,
                    metadata,created_at,updated_at
                ) VALUES (?,?,'stripe',?,'{}',?,?)
                """,
                (
                    ambiguous_workspace_id,
                    subject_user_id,
                    legacy_account_id,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO platform_subscriptions(
                    workspace_id,provider,external_subscription_id,
                    external_customer_id,status,plan_key,current_period_end,
                    last_event_at,created_at,updated_at
                ) VALUES (
                    ?,'stripe',?,?,'active','local',NULL,?,?,?
                )
                """,
                (
                    ambiguous_workspace_id,
                    legacy_object_id,
                    legacy_account_id,
                    now,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO platform_access_grants(
                    workspace_id,subject_user_id,scope,source,external_ref,
                    profile,plan_key,status,starts_at,ends_at,created_at,
                    updated_at
                ) VALUES (
                    ?,?,'subject','stripe',?,'local_scout','local','active',
                    ?,'2026-07-29T12:00:00+00:00',?,?
                )
                """,
                (
                    ambiguous_workspace_id,
                    subject_user_id,
                    legacy_object_id,
                    now,
                    now,
                    now,
                ),
            )
        ambiguous_normalized = json.dumps(
            {
                "provider": "stripe",
                "event_id": "evt_v4_ambiguous",
                "event_type": "customer.subscription.deleted",
                "occurred_at": now,
                "action": "cancel",
                "external_account_id": "cus_v4_legacy_private_a",
                "external_object_id": "sub_v4_legacy_private_a",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        connection.execute(
            """
            INSERT INTO platform_provider_events(
                id,workspace_id,provider,event_id,event_type,payload,
                normalized_data,occurred_at,outcome,reason_code,
                duplicate_count,replayed_at,object_stream_hash,
                restrictive_rank,created_at,updated_at
            ) VALUES (
                42,?,'stripe','evt_v4_ambiguous',
                'customer.subscription.deleted','{}',?,?,
                'quarantined','projection_failure',0,NULL,?,1,?,?
            )
            """,
            (
                ambiguous_workspace_id,
                ambiguous_normalized,
                now,
                _provider_hash("stripe", "sub_v4_legacy_private_a"),
                now,
                now,
            ),
        )

        connection.commit()
        apply_migrations(connection, "provider-sync", PROVIDER_SYNC_MIGRATIONS)
        trusted = connection.execute(
            """
            SELECT * FROM platform_provider_events
            WHERE event_id='evt_v4_trusted'
            """
        ).fetchone()
        ambiguous = connection.execute(
            """
            SELECT * FROM platform_provider_events
            WHERE event_id='evt_v4_ambiguous'
            """
        ).fetchone()
        ambiguous_attempt = connection.execute(
            """
            SELECT outcome,reason_code
            FROM platform_provider_event_attempts
            WHERE provider_event_id=42 ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert trusted is not None
    assert trusted["canonical_action"] == "cancel"
    assert trusted["external_account_hash"] == _provider_hash(
        "stripe",
        account_id,
    )
    assert trusted["object_stream_hash"] == _provider_hash(
        "stripe",
        object_id,
    )
    assert trusted["workspace_id"] == workspace_id
    assert trusted["bound_subject_user_id"] == subject_user_id
    assert trusted["bound_scope"] == "subject"
    assert trusted["normalized_data"] == trusted_normalized
    assert forged_account_id not in trusted["external_account_hash"]
    assert forged_object_id not in trusted["object_stream_hash"]

    assert ambiguous is not None
    assert ambiguous["outcome"] == "quarantined"
    assert ambiguous["reason_code"] == "legacy_receipt_binding_untrusted"
    assert ambiguous["canonical_action"] == "cancel"
    assert ambiguous["external_account_hash"] is None
    assert ambiguous["object_stream_hash"] is None
    assert ambiguous["bound_subject_user_id"] is None
    assert ambiguous["bound_scope"] is None
    assert tuple(ambiguous_attempt) == (
        "quarantined",
        "legacy_receipt_binding_untrusted",
    )
    for private_value in (
        "cus_v4_legacy_private_a",
        "sub_v4_legacy_private_a",
        "cus_v4_legacy_private_b",
        "sub_v4_legacy_private_b",
    ):
        assert private_value not in str(ambiguous["reason_code"])
        assert private_value not in str(tuple(ambiguous_attempt))
    assert foreign_key_errors == []


def test_provider_sync_v4_quarantines_action_ambiguous_stripe_receipts(
    tmp_path,
):
    path = tmp_path / "provider-v3-ambiguous-actions.db"
    now = "2026-07-28T12:00:00+00:00"
    account_id = "cus_v4_action_private"
    object_id = "sub_v4_action_private"
    ambiguous_events = (
        ("evt_updated_positive_rank", "customer.subscription.updated", 0),
        ("evt_updated_restrictive_rank", "customer.subscription.updated", 1),
        (
            "evt_pending_applied",
            "customer.subscription.pending_update_applied",
            0,
        ),
        (
            "evt_pending_expired",
            "customer.subscription.pending_update_expired",
            1,
        ),
        ("evt_legacy_updated", "subscription.updated", 0),
    )
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        create_schema(connection)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        apply_migrations(connection, "entitlements", ENTITLEMENT_MIGRATIONS)
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS[:3],
        )
        connection.execute(
            """
            INSERT INTO platform_plans(
                key,name,daily_quotas,created_at,updated_at
            ) VALUES ('local','Local','{}',?,?)
            """,
            (now, now),
        )
        workspace_id = int(
            connection.execute(
                """
                INSERT INTO platform_workspaces(
                    public_id,name,created_at,updated_at
                ) VALUES ('ws-v4-action','V4 Action',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        subject_user_id = int(
            connection.execute(
                """
                INSERT INTO platform_users(email,name,created_at,updated_at)
                VALUES ('v4-action@example.test','V4 Action',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO platform_memberships(
                workspace_id,user_id,role,created_at,updated_at
            ) VALUES (?,?,'owner',?,?)
            """,
            (workspace_id, subject_user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_external_accounts(
                workspace_id,subject_user_id,provider,external_account_id,
                metadata,created_at,updated_at
            ) VALUES (?,?,'stripe',?,'{}',?,?)
            """,
            (workspace_id, subject_user_id, account_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_subscriptions(
                workspace_id,provider,external_subscription_id,
                external_customer_id,status,plan_key,current_period_end,
                last_event_at,created_at,updated_at
            ) VALUES (
                ?,'stripe',?,?,'active','local',NULL,?,?,?
            )
            """,
            (workspace_id, object_id, account_id, now, now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_access_grants(
                workspace_id,subject_user_id,scope,source,external_ref,
                profile,plan_key,status,starts_at,ends_at,created_at,
                updated_at
            ) VALUES (
                ?,?,'subject','stripe',?,'local_scout','local','active',
                ?,'2026-07-29T12:00:00+00:00',?,?
            )
            """,
            (workspace_id, subject_user_id, object_id, now, now, now),
        )
        for event_id, event_type, restrictive_rank in ambiguous_events:
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,reason_code,
                    duplicate_count,replayed_at,object_stream_hash,
                    restrictive_rank,created_at,updated_at
                ) VALUES (
                    ?,'stripe',?,?,'{}','{}',?,'quarantined',
                    'projection_failure',0,NULL,?,?,?,?
                )
                """,
                (
                    workspace_id,
                    event_id,
                    event_type,
                    now,
                    _provider_hash("stripe", object_id),
                    restrictive_rank,
                    now,
                    now,
                ),
            )
        connection.commit()

        apply_migrations(connection, "provider-sync", PROVIDER_SYNC_MIGRATIONS)
        receipts = connection.execute(
            """
            SELECT event_id,canonical_action,external_account_hash,
                   object_stream_hash,bound_subject_user_id,bound_scope,
                   restrictive_rank,outcome,reason_code
            FROM platform_provider_events
            ORDER BY id
            """
        ).fetchall()
        attempts = connection.execute(
            """
            SELECT COUNT(*) FROM platform_provider_event_attempts
            WHERE reason_code='legacy_receipt_binding_untrusted'
            """
        ).fetchone()[0]

    assert [row["event_id"] for row in receipts] == [
        event[0] for event in ambiguous_events
    ]
    assert attempts == len(ambiguous_events)
    for receipt in receipts:
        assert receipt["canonical_action"] is None
        assert receipt["external_account_hash"] is None
        assert receipt["object_stream_hash"] is None
        assert receipt["bound_subject_user_id"] is None
        assert receipt["bound_scope"] is None
        assert receipt["restrictive_rank"] == 0
        assert receipt["outcome"] == "quarantined"
        assert receipt["reason_code"] == "legacy_receipt_binding_untrusted"
        assert account_id not in receipt["reason_code"]
        assert object_id not in receipt["reason_code"]


def test_provider_sync_v4_receipt_bindings_are_write_once_but_operations_mutate(
    tmp_path,
):
    path = tmp_path / "provider-v4-write-once.db"
    now = "2026-07-28T12:00:00+00:00"
    EntitlementStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        workspace_id = int(
            connection.execute(
                """
                INSERT INTO platform_workspaces(
                    public_id,name,created_at,updated_at
                ) VALUES ('ws-v4-write-once','V4 Write Once',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        subject_user_id = int(
            connection.execute(
                """
                INSERT INTO platform_users(email,name,created_at,updated_at)
                VALUES ('v4-write-once@example.test','V4 Write Once',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO platform_memberships(
                workspace_id,user_id,role,created_at,updated_at
            ) VALUES (?,?,'owner',?,?)
            """,
            (workspace_id, subject_user_id, now, now),
        )
        event_id = int(
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,reason_code,
                    duplicate_count,replayed_at,object_stream_hash,
                    restrictive_rank,canonical_action,external_account_hash,
                    bound_subject_user_id,bound_scope,created_at,updated_at
                ) VALUES (
                    ?,'stripe','evt_v4_write_once',
                    'customer.subscription.deleted','{}','{}',?,
                    'quarantined','projection_failure',0,NULL,?,1,'cancel',?,
                    ?,'subject',?,?
                ) RETURNING id
                """,
                (
                    workspace_id,
                    now,
                    _provider_hash("stripe", "sub_v4_write_once"),
                    _provider_hash("stripe", "cus_v4_write_once"),
                    subject_user_id,
                    now,
                    now,
                ),
            ).fetchone()[0]
        )
        unbound_event_id = int(
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,reason_code,
                    duplicate_count,replayed_at,object_stream_hash,
                    restrictive_rank,canonical_action,external_account_hash,
                    bound_subject_user_id,bound_scope,created_at,updated_at
                ) VALUES (
                    ?,'stripe','evt_v4_unbound','unsupported','{}','{}',?,
                    'quarantined','unsupported_event_type',0,NULL,NULL,0,
                    'reject',NULL,NULL,NULL,?,?
                ) RETURNING id
                """,
                (workspace_id, now, now, now),
            ).fetchone()[0]
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM platform_users WHERE id=?",
                (subject_user_id,),
            )
        assert connection.execute(
            """
            SELECT COUNT(*) FROM platform_provider_events
            WHERE id=? AND bound_subject_user_id=?
            """,
            (event_id, subject_user_id),
        ).fetchone()[0] == 1
        for column, value in (
            ("workspace_id", workspace_id + 1),
            ("provider", "skool"),
            ("event_id", "evt_v4_changed"),
            ("event_type", "customer.subscription.paused"),
            ("occurred_at", "2030-01-01T00:00:00+00:00"),
            ("canonical_action", "pause"),
            ("external_account_hash", "a" * 64),
            ("object_stream_hash", "b" * 64),
            ("restrictive_rank", 0),
            ("bound_subject_user_id", subject_user_id + 1),
            ("bound_scope", "workspace"),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"""
                    UPDATE platform_provider_events SET {column}=?
                    WHERE id=?
                    """,
                    (value, event_id),
                )
        connection.execute(
            """
            DELETE FROM platform_memberships
            WHERE workspace_id=? AND user_id=?
            """,
            (workspace_id, subject_user_id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE platform_provider_events
                SET bound_subject_user_id=?,bound_scope='subject'
                WHERE id=?
                """,
                (subject_user_id, unbound_event_id),
            )
        connection.execute(
            """
            UPDATE platform_provider_events
            SET outcome='reconciled',reason_code='admin_replay',
                replayed_at=?,duplicate_count=duplicate_count+1,updated_at=?
            WHERE id=?
            """,
            (now, now, event_id),
        )
        operational = connection.execute(
            """
            SELECT outcome,reason_code,replayed_at,duplicate_count
            FROM platform_provider_events WHERE id=?
            """,
            (event_id,),
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,object_stream_hash,
                    restrictive_rank,canonical_action,external_account_hash,
                    bound_subject_user_id,bound_scope,created_at,updated_at
                ) VALUES (
                    ?,'stripe','evt_v4_bad_subject','unsupported','{}','{}',?,
                    'quarantined',NULL,0,'reject',NULL,999999,'subject',?,?
                )
                """,
                (workspace_id, now, now, now),
            )

    assert tuple(operational) == (
        "reconciled",
        "admin_replay",
        now,
        1,
    )


def _create_through_provider_sync_v4(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        create_schema(connection)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        apply_migrations(connection, "entitlements", ENTITLEMENT_MIGRATIONS)
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS[:4],
        )


def test_provider_sync_v5_fresh_schema_has_authority_bindings(tmp_path):
    path = tmp_path / "provider-v5-fresh.db"

    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        columns = {
            str(row[1]): row
            for row in connection.execute(
                "PRAGMA table_info(platform_provider_events)"
            )
        }
        triggers = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='trigger' AND tbl_name='platform_provider_events'
                """
            )
        }
        version = current_version(connection, "provider-sync")
        version_rows = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM platform_schema_versions
                WHERE component='provider-sync'
                """
            ).fetchone()[0]
        )

    assert version == 5
    assert version_rows == 5
    assert {
        "entitlement_input_hash",
        "bound_plan_key",
        "bound_profile",
    } <= set(columns)
    assert columns["entitlement_input_hash"][3] == 0
    assert columns["bound_plan_key"][3] == 0
    assert columns["bound_profile"][3] == 0
    assert {
        "platform_provider_event_entitlement_binding_insert",
        "platform_provider_event_entitlement_binding_update",
        "platform_provider_event_entitlement_binding_immutable",
    } <= triggers


def test_provider_sync_v5_hash_and_plan_profile_bindings_are_write_once(
    tmp_path,
):
    path = tmp_path / "provider-v5-write-once.db"
    now = "2026-07-28T12:00:00+00:00"
    valid_hash = "v1:" + ("a" * 64)
    EntitlementStore(path)

    with sqlite3.connect(path) as connection:
        workspace_id = int(
            connection.execute(
                """
                INSERT INTO platform_workspaces(
                    public_id,name,created_at,updated_at
                ) VALUES ('ws-v5-write-once','V5 Write Once',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        event_id = int(
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,reason_code,
                    duplicate_count,replayed_at,object_stream_hash,
                    restrictive_rank,canonical_action,external_account_hash,
                    bound_subject_user_id,bound_scope,
                    entitlement_input_hash,bound_plan_key,bound_profile,
                    created_at,updated_at
                ) VALUES (
                    ?,'stripe','evt_v5_write_once',
                    'customer.subscription.updated','{}','{}',?,
                    'quarantined','unmapped_plan',0,NULL,?,0,'subscription',?,
                    NULL,NULL,?,NULL,NULL,?,?
                ) RETURNING id
                """,
                (
                    workspace_id,
                    now,
                    _provider_hash("stripe", "sub_v5_write_once"),
                    _provider_hash("stripe", "cus_v5_write_once"),
                    valid_hash,
                    now,
                    now,
                ),
            ).fetchone()[0]
        )
        connection.execute(
            """
            UPDATE platform_provider_events
            SET normalized_data='{"retained":"mutable evidence"}'
            WHERE id=?
            """,
            (event_id,),
        )
        assert connection.execute(
            """
            SELECT normalized_data FROM platform_provider_events
            WHERE id=?
            """,
            (event_id,),
        ).fetchone()[0] == '{"retained":"mutable evidence"}'

        for changed_hash in (None, "v1:" + ("b" * 64)):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    UPDATE platform_provider_events
                    SET entitlement_input_hash=? WHERE id=?
                    """,
                    (changed_hash, event_id),
                )
        for assignments in (
            ("bound_plan_key='local'",),
            ("bound_profile='local_scout'",),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"""
                    UPDATE platform_provider_events SET {assignments[0]}
                    WHERE id=?
                    """,
                    (event_id,),
                )

        connection.execute(
            """
            UPDATE platform_provider_events
            SET bound_plan_key='local',bound_profile='local_scout'
            WHERE id=?
            """,
            (event_id,),
        )
        for assignment in (
            "bound_plan_key='operator'",
            "bound_profile='full_operator'",
            "bound_plan_key=NULL,bound_profile=NULL",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"""
                    UPDATE platform_provider_events SET {assignment}
                    WHERE id=?
                    """,
                    (event_id,),
                )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,object_stream_hash,
                    restrictive_rank,canonical_action,external_account_hash,
                    entitlement_input_hash,created_at,updated_at
                ) VALUES (
                    ?,'stripe','evt_v5_bad_hash',
                    'customer.subscription.updated','{}','{}',?,
                    'quarantined',?,0,'subscription',?,'v1:not-a-hash',?,?
                )
                """,
                (
                    workspace_id,
                    now,
                    _provider_hash("stripe", "sub_v5_bad_hash"),
                    _provider_hash("stripe", "cus_v5_bad_hash"),
                    now,
                    now,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,object_stream_hash,
                    restrictive_rank,canonical_action,external_account_hash,
                    entitlement_input_hash,bound_plan_key,bound_profile,
                    created_at,updated_at
                ) VALUES (
                    ?,'stripe','evt_v5_partial_pair',
                    'customer.subscription.updated','{}','{}',?,
                    'quarantined',?,0,'subscription',?,?,'local',NULL,?,?
                )
                """,
                (
                    workspace_id,
                    now,
                    _provider_hash("stripe", "sub_v5_partial_pair"),
                    _provider_hash("stripe", "cus_v5_partial_pair"),
                    valid_hash,
                    now,
                    now,
                ),
            )

        legacy_event_id = int(
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,object_stream_hash,
                    restrictive_rank,canonical_action,external_account_hash,
                    entitlement_input_hash,bound_plan_key,bound_profile,
                    created_at,updated_at
                ) VALUES (
                    ?,'stripe','evt_v5_null_hash',
                    'customer.subscription.updated','{}','{}',?,
                    'quarantined',?,0,'subscription',?,NULL,NULL,NULL,?,?
                ) RETURNING id
                """,
                (
                    workspace_id,
                    now,
                    _provider_hash("stripe", "sub_v5_null_hash"),
                    _provider_hash("stripe", "cus_v5_null_hash"),
                    now,
                    now,
                ),
            ).fetchone()[0]
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE platform_provider_events
                SET entitlement_input_hash=? WHERE id=?
                """,
                (valid_hash, legacy_event_id),
            )


def test_provider_sync_v5_failure_rolls_back_schema_and_preserves_receipt(
    tmp_path,
):
    path = tmp_path / "provider-v5-rollback.db"
    now = "2026-07-28T12:00:00+00:00"
    _create_through_provider_sync_v4(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO platform_provider_events(
                id,workspace_id,provider,event_id,event_type,payload,
                normalized_data,occurred_at,outcome,reason_code,
                duplicate_count,replayed_at,object_stream_hash,
                restrictive_rank,canonical_action,external_account_hash,
                bound_subject_user_id,bound_scope,created_at,updated_at
            ) VALUES (
                71,NULL,'stripe','evt_v5_rollback','unsupported','{}',
                '{"retained":"receipt"}',?,'quarantined',
                'unsupported_event_type',0,NULL,NULL,0,'reject',NULL,
                NULL,NULL,?,?
            )
            """,
            (now, now, now),
        )
        connection.commit()

        def deny_trigger(action, _arg1, _arg2, _database, _source):
            if action == sqlite3.SQLITE_CREATE_TRIGGER:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_trigger)
        with pytest.raises(sqlite3.DatabaseError):
            apply_migrations(
                connection,
                "provider-sync",
                PROVIDER_SYNC_MIGRATIONS,
            )
        connection.set_authorizer(None)
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(platform_provider_events)"
            )
        }
        receipt = connection.execute(
            """
            SELECT id,event_id,normalized_data
            FROM platform_provider_events WHERE id=71
            """
        ).fetchone()
        version = current_version(connection, "provider-sync")

    assert version == 4
    assert "entitlement_input_hash" not in columns
    assert "bound_plan_key" not in columns
    assert "bound_profile" not in columns
    assert tuple(receipt) == (
        71,
        "evt_v5_rollback",
        '{"retained":"receipt"}',
    )


def test_provider_sync_v5_legacy_policy_retains_evidence_and_restrictive_safety(
    tmp_path,
):
    path = tmp_path / "provider-v5-legacy-policy.db"
    now = "2026-07-28T12:00:00+00:00"
    positive_at = "2026-07-28T11:00:00+00:00"
    account_id = "cus_v5_legacy_private"
    object_id = "sub_v5_legacy_private"
    _create_through_provider_sync_v4(path)

    positive_normalized = json.dumps(
        {
            "provider": "stripe",
            "event_id": "evt_v5_legacy_positive",
            "event_type": "customer.subscription.updated",
            "occurred_at": positive_at,
            "action": "subscription",
            "external_account_id": account_id,
            "external_object_id": object_id,
            "subscription_status": "active",
            "mapping_keys": ["price_local"],
            "current_period_end": "2026-08-28T12:00:00+00:00",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    restrictive_normalized = json.dumps(
        {
            "provider": "stripe",
            "event_id": "evt_v5_legacy_cancel",
            "event_type": "customer.subscription.deleted",
            "occurred_at": now,
            "action": "cancel",
            "external_account_id": account_id,
            "external_object_id": object_id,
            "subscription_status": "canceled",
            "mapping_keys": [],
            "current_period_end": None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO platform_plans(
                key,name,daily_quotas,created_at,updated_at
            ) VALUES ('local','Local','{}',?,?)
            """,
            (now, now),
        )
        workspace_id = int(
            connection.execute(
                """
                INSERT INTO platform_workspaces(
                    public_id,name,created_at,updated_at
                ) VALUES ('ws-v5-legacy','V5 Legacy',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        subject_user_id = int(
            connection.execute(
                """
                INSERT INTO platform_users(email,name,created_at,updated_at)
                VALUES ('v5-legacy@example.test','V5 Legacy',?,?)
                RETURNING id
                """,
                (now, now),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO platform_memberships(
                workspace_id,user_id,role,created_at,updated_at
            ) VALUES (?,?,'owner',?,?)
            """,
            (workspace_id, subject_user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_external_accounts(
                workspace_id,subject_user_id,provider,external_account_id,
                metadata,created_at,updated_at
            ) VALUES (?,?,'stripe',?,'{}',?,?)
            """,
            (workspace_id, subject_user_id, account_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO platform_subscriptions(
                workspace_id,provider,external_subscription_id,
                external_customer_id,status,plan_key,current_period_end,
                last_event_at,created_at,updated_at
            ) VALUES (
                ?,'stripe',?,?,'active','local',
                '2026-08-28T12:00:00+00:00',?,?,?
            )
            """,
            (
                workspace_id,
                object_id,
                account_id,
                positive_at,
                positive_at,
                positive_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO platform_access_grants(
                workspace_id,subject_user_id,scope,source,external_ref,
                profile,plan_key,status,starts_at,ends_at,created_at,updated_at
            ) VALUES (
                ?,?,'subject','stripe',?,'local_scout','local','active',
                ?,'2026-08-28T12:00:00+00:00',?,?
            )
            """,
            (
                workspace_id,
                subject_user_id,
                object_id,
                positive_at,
                positive_at,
                positive_at,
            ),
        )
        for (
            event_db_id,
            event_id,
            event_type,
            normalized_data,
            occurred_at,
            action,
            rank,
        ) in (
            (
                81,
                "evt_v5_legacy_positive",
                "customer.subscription.updated",
                positive_normalized,
                positive_at,
                "subscription",
                0,
            ),
            (
                82,
                "evt_v5_legacy_cancel",
                "customer.subscription.deleted",
                restrictive_normalized,
                now,
                "cancel",
                1,
            ),
        ):
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    id,workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,reason_code,
                    duplicate_count,replayed_at,object_stream_hash,
                    restrictive_rank,canonical_action,external_account_hash,
                    bound_subject_user_id,bound_scope,created_at,updated_at
                ) VALUES (
                    ?,?,'stripe',?,?, '{}',?,?,'quarantined',
                    'projection_failure',0,NULL,?,?,?,?,?,'subject',?,?
                )
                """,
                (
                    event_db_id,
                    workspace_id,
                    event_id,
                    event_type,
                    normalized_data,
                    occurred_at,
                    _provider_hash("stripe", object_id),
                    rank,
                    action,
                    _provider_hash("stripe", account_id),
                    subject_user_id,
                    now,
                    now,
                ),
            )
        connection.commit()
        apply_migrations(
            connection,
            "provider-sync",
            PROVIDER_SYNC_MIGRATIONS,
        )
        migrated = connection.execute(
            """
            SELECT id,event_id,normalized_data,outcome,reason_code,
                   entitlement_input_hash,bound_plan_key,bound_profile
            FROM platform_provider_events ORDER BY id
            """
        ).fetchall()
        attempts = connection.execute(
            """
            SELECT provider_event_id,outcome,reason_code
            FROM platform_provider_event_attempts
            WHERE provider_event_id IN (81,82)
            ORDER BY id
            """
        ).fetchall()
        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

    assert [int(row["id"]) for row in migrated] == [81, 82]
    assert migrated[0]["normalized_data"] == positive_normalized
    assert migrated[1]["normalized_data"] == restrictive_normalized
    assert migrated[0]["outcome"] == "quarantined"
    assert (
        migrated[0]["reason_code"]
        == "legacy_receipt_binding_untrusted"
    )
    assert migrated[1]["reason_code"] == "projection_failure"
    assert migrated[0]["entitlement_input_hash"] is None
    safe_restrictive_canonical = json.dumps(
        {
            "action": "cancel",
            "current_period_end": None,
            "mapping_keys": [],
            "provider": "stripe",
            "subscription_status": None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    safe_restrictive_hash = "v1:" + hashlib.sha256(
        b"cre-provider-entitlement-input:v1\0"
        + safe_restrictive_canonical.encode("utf-8")
    ).hexdigest()
    assert migrated[1]["entitlement_input_hash"] == safe_restrictive_hash
    for row in migrated:
        assert row["bound_plan_key"] is None
        assert row["bound_profile"] is None
        immutable_text = "|".join(
            str(row[key])
            for key in (
                "entitlement_input_hash",
                "bound_plan_key",
                "bound_profile",
            )
        )
        assert account_id not in immutable_text
        assert object_id not in immutable_text
        assert "price_local" not in immutable_text
    assert tuple(attempts[-1]) == (
        81,
        "quarantined",
        "legacy_receipt_binding_untrusted",
    )
    assert foreign_key_errors == []
    assert integrity == "ok"

    config = CreConfig(
        _env_file=None,
        cache_db_path=path,
        stripe_price_mappings={
            "price_local": {
                "plan_key": "local",
                "profile": "local_scout",
            }
        },
    )
    service = ProviderSyncService(config)
    with service._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        replay = service.replay_tx(connection, 82)
        connection.commit()

    assert replay.outcome == "reconciled"
    with sqlite3.connect(path) as connection:
        subscription = connection.execute(
            """
            SELECT status FROM platform_subscriptions
            WHERE provider='stripe' AND external_subscription_id=?
            """,
            (object_id,),
        ).fetchone()
        grant = connection.execute(
            """
            SELECT status FROM platform_access_grants
            WHERE source='stripe' AND external_ref=?
            """,
            (object_id,),
        ).fetchone()
    assert tuple(subscription) == ("canceled",)
    assert tuple(grant) == ("revoked",)


def test_provider_sync_v5_concurrent_initialization_records_once(tmp_path):
    path = tmp_path / "provider-v5-concurrent.db"
    _create_through_provider_sync_v4(path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(EntitlementStore, path) for _ in range(2)]
        for future in futures:
            future.result()

    with sqlite3.connect(path) as connection:
        assert current_version(connection, "provider-sync") == 5
        assert int(
            connection.execute(
                """
                SELECT COUNT(*) FROM platform_schema_versions
                WHERE component='provider-sync' AND version=5
                """
            ).fetchone()[0]
        ) == 1
