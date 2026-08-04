"""Transactional, repeatable platform schema migration tests."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock


def test_legacy_oauth_schema_migrates_and_invalidates_old_sessions(tmp_path):
    from cre_mcp.platform.migrations import current_version

    path = tmp_path / "legacy.db"
    now = "2026-07-28T12:00:00+00:00"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE platform_workspaces (
                id INTEGER PRIMARY KEY,
                public_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                slug TEXT,
                plan_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO platform_workspaces
                (public_id,name,created_at,updated_at)
                VALUES ('ws-legacy','Legacy', '2026-07-28', '2026-07-28');
            CREATE TABLE platform_oauth_clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id TEXT NOT NULL,
                name TEXT NOT NULL,
                client_id TEXT NOT NULL UNIQUE,
                redirect_uris TEXT NOT NULL,
                scopes TEXT NOT NULL,
                active INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO platform_oauth_clients
                (workspace_id,name,client_id,redirect_uris,scopes,active,created_at,updated_at)
                VALUES ('ws-legacy','Claude','legacy-client','["https://example.test/cb"]',
                        '["mcp:tools"]',1,'2026-07-28','2026-07-28');
            CREATE TABLE platform_oauth_codes (
                id INTEGER PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE,
                workspace_id TEXT NOT NULL, user_id TEXT NOT NULL,
                client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL,
                code_challenge TEXT NOT NULL, profile TEXT NOT NULL,
                plan TEXT NOT NULL, territories TEXT NOT NULL,
                scopes TEXT NOT NULL, audience TEXT NOT NULL,
                expires_at TEXT NOT NULL, consumed_at TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE platform_oauth_sessions (
                session_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL, client_id TEXT NOT NULL,
                profile TEXT NOT NULL, plan TEXT NOT NULL,
                territories TEXT NOT NULL, scopes TEXT NOT NULL,
                audience TEXT NOT NULL, access_hash TEXT NOT NULL UNIQUE,
                refresh_hash TEXT NOT NULL UNIQUE, access_expires_at TEXT NOT NULL,
                refresh_expires_at TEXT NOT NULL, revoked_at TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO platform_oauth_sessions VALUES
                ('legacy-session','ws-legacy','7','legacy-client','full_operator',
                 'pro','["TX"]','["mcp:tools"]','medawarcre-mcp',
                 'legacy-access-hash','legacy-refresh-hash',
                 '2099-01-01','2099-01-01',NULL,'2026-07-28','2026-07-28');
            CREATE TABLE platform_oauth_refresh_history (
                token_hash TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                rotated_at TEXT NOT NULL
            );
            """
        )

    from cre_mcp.platform.auth import OAuthSessionStore

    store = OAuthSessionStore(path)
    assert store.get_client("legacy-client") is not None
    assert store.validate_access("legacy-raw-token") is None

    with sqlite3.connect(path) as connection:
        client_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(platform_oauth_clients)"
            )
        }
        sessions = connection.execute(
            "SELECT COUNT(*) FROM platform_oauth_sessions"
        ).fetchone()[0]
        version = current_version(connection, "oauth")

    assert "workspace_id" not in client_columns
    assert sessions == 0
    assert version >= 1

    OAuthSessionStore(path)
    with sqlite3.connect(path) as connection:
        assert current_version(connection, "oauth") == version


def test_migration_failure_rolls_back_the_whole_version(tmp_path):
    from cre_mcp.platform.migrations import Migration, apply_migrations

    path = tmp_path / "rollback.db"

    def fail(connection):
        connection.execute("CREATE TABLE should_roll_back(id INTEGER)")
        raise RuntimeError("injected migration failure")

    with sqlite3.connect(path, isolation_level=None) as connection:
        try:
            apply_migrations(
                connection,
                "rollback-test",
                (Migration(1, "fail atomically", fail),),
            )
        except RuntimeError as exc:
            assert str(exc) == "injected migration failure"
        else:
            raise AssertionError("migration unexpectedly succeeded")

        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name='should_roll_back'"
        ).fetchone()

    assert table is None


def test_concurrent_migration_callers_recheck_version_after_write_lock(
    tmp_path,
    monkeypatch,
):
    import cre_mcp.platform.migrations as migration_module

    path = tmp_path / "concurrent.db"
    component = "concurrent-test"
    with sqlite3.connect(path, isolation_level=None) as connection:
        assert migration_module.current_version(connection, component) == 0

    initial_reads = Barrier(2)
    read_lock = Lock()
    read_count = 0
    original_current_version = migration_module.current_version

    def synchronized_current_version(connection, requested_component):
        nonlocal read_count
        version = original_current_version(connection, requested_component)
        with read_lock:
            read_count += 1
            synchronize = read_count <= 2
        if synchronize:
            initial_reads.wait(timeout=5)
        return version

    monkeypatch.setattr(
        migration_module,
        "current_version",
        synchronized_current_version,
    )

    apply_lock = Lock()
    apply_count = 0

    def apply_once(connection):
        nonlocal apply_count
        with apply_lock:
            apply_count += 1
        connection.execute(
            "CREATE TABLE IF NOT EXISTS concurrent_payload(id INTEGER)"
        )

    migration = migration_module.Migration(1, "concurrent", apply_once)

    def migrate():
        with sqlite3.connect(
            path,
            isolation_level=None,
            timeout=10,
        ) as connection:
            return migration_module.apply_migrations(
                connection,
                component,
                (migration,),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: migrate(), range(2)))

    assert outcomes == [1, 1]
    assert apply_count == 1
    with sqlite3.connect(path) as connection:
        assert original_current_version(connection, component) == 1


def test_oauth_v1_sessions_gain_a_backfilled_absolute_family_deadline(tmp_path):
    from cre_mcp.platform.auth import OAuthSessionStore
    from cre_mcp.platform.migrations import current_version

    path = tmp_path / "oauth-v1.db"
    created_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE platform_schema_versions (
                component TEXT NOT NULL,
                version INTEGER NOT NULL,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                PRIMARY KEY(component, version)
            );
            INSERT INTO platform_schema_versions
                (component,version,description,applied_at)
            VALUES ('oauth',1,'authoritative identity-linked OAuth sessions',
                    '2026-01-01T00:00:00+00:00');
            CREATE TABLE platform_oauth_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO platform_oauth_sessions(session_id,created_at) VALUES (?,?)",
            ("family-1", created_at.isoformat()),
        )

    OAuthSessionStore(path)

    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(platform_oauth_sessions)"
            )
        }
        deadline = connection.execute(
            """
            SELECT refresh_family_expires_at
            FROM platform_oauth_sessions
            WHERE session_id='family-1'
            """
        ).fetchone()[0]
        version = current_version(connection, "oauth")

    assert "refresh_family_expires_at" in columns
    assert datetime.fromisoformat(deadline) == created_at + timedelta(days=90)
    assert version == 2

    OAuthSessionStore(path)
    with sqlite3.connect(path) as connection:
        assert current_version(connection, "oauth") == 2
        assert (
            connection.execute(
                """
                SELECT refresh_family_expires_at
                FROM platform_oauth_sessions
                WHERE session_id='family-1'
                """
            ).fetchone()[0]
            == deadline
        )


def test_legacy_plan_schema_gains_daily_quotas_without_data_loss(tmp_path):
    from cre_mcp.platform.migrations import current_version
    from cre_mcp.platform.schema import create_schema

    path = tmp_path / "plans-v0.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE platform_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                monthly_price_usd REAL,
                seat_limit INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO platform_plans
                (key,name,monthly_price_usd,seat_limit,created_at,updated_at)
            VALUES ('pro','Professional',99,5,'2026-01-01','2026-01-01');
            """
        )
        create_schema(connection)

        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(platform_plans)")
        }
        plan = connection.execute(
            "SELECT key,name,daily_quotas FROM platform_plans WHERE key='pro'"
        ).fetchone()
        version = current_version(connection, "platform-core")

    assert "daily_quotas" in columns
    assert plan == ("pro", "Professional", "{}")
    assert version == 1

    with sqlite3.connect(path) as connection:
        create_schema(connection)
        assert current_version(connection, "platform-core") == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_plans WHERE key='pro'"
        ).fetchone()[0] == 1


def test_admin_controls_current_schema_is_fresh_additive_and_empty(tmp_path):
    from cre_mcp.platform.migrations import current_version
    from cre_mcp.platform.schema import create_schema

    path = tmp_path / "admin-controls-fresh.db"
    with sqlite3.connect(path) as connection:
        create_schema(connection)
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        version = current_version(connection, "admin-controls")

    assert version == 2
    assert {
        "platform_internal_admins",
        "platform_external_accounts",
        "platform_admin_audit",
        "platform_skool_join_tasks",
        "platform_skool_reconciliations",
    } <= names
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_internal_admins"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_external_accounts"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_admin_audit"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_skool_join_tasks"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM platform_skool_reconciliations"
        ).fetchone()[0] == 0


def test_admin_controls_upgrade_preserves_legacy_rows_without_backfill(
    tmp_path,
):
    from cre_mcp.platform.entitlements import _ENTITLEMENT_SCHEMA
    from cre_mcp.platform.migrations import current_version
    from cre_mcp.platform.schema import SCHEMA, create_schema

    path = tmp_path / "admin-controls-upgrade.db"
    now = "2026-07-28T12:00:00+00:00"
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.executescript(_ENTITLEMENT_SCHEMA)
        connection.execute(
            """
            INSERT INTO platform_workspaces(public_id,name,created_at,updated_at)
            VALUES ('ws-upgrade','Upgrade',?,?)
            """,
            (now, now),
        )
        workspace_id = connection.execute(
            "SELECT id FROM platform_workspaces WHERE public_id='ws-upgrade'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO platform_subscriptions(
                workspace_id,provider,external_subscription_id,
                external_customer_id,status,plan_key,current_period_end,
                last_event_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                workspace_id,
                "stripe",
                "sub_legacy",
                "cus_legacy",
                "active",
                "pro",
                None,
                now,
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO platform_access_grants(
                workspace_id,source,external_ref,profile,plan_key,status,
                starts_at,ends_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                workspace_id,
                "manual",
                "legacy-ref",
                "full_operator",
                "pro",
                "active",
                now,
                None,
                now,
                now,
            ),
        )
        create_schema(connection)
        version = current_version(connection, "admin-controls")
        subscription = connection.execute(
            """
            SELECT external_customer_id
            FROM platform_subscriptions
            WHERE external_subscription_id='sub_legacy'
            """
        ).fetchone()[0]
        grant = connection.execute(
            "SELECT external_ref FROM platform_access_grants WHERE source='manual'"
        ).fetchone()[0]
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "platform_internal_admins",
                "platform_external_accounts",
                "platform_admin_audit",
            )
        )

    assert version == 2
    assert subscription == "cus_legacy"
    assert grant == "legacy-ref"
    assert counts == (0, 0, 0)
