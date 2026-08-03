from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from cre_mcp.postgres import backup as backup_module
from cre_mcp.postgres.authority import (
    UnsafeDatabaseRoleError,
    assert_admission_session,
)
from cre_mcp.postgres.backup import (
    BackupCommandError,
    BackupManifest,
    BackupVerificationError,
    _verify_exact_privileges,
    create_backup,
    restore_backup,
)
from cre_mcp.postgres.catalog import catalog_fingerprint
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.health import check_readiness
from cre_mcp.postgres.migrations import (
    MigrationRunner,
    UnsafeMigrationRoleError,
    assert_migration_session,
    load_migrations,
)
from cre_mcp.postgres.pool import PostgresDatabase, UnsafeRuntimeRoleError


def _database_name(dsn: str) -> str:
    with psycopg.connect(dsn) as connection:
        return str(connection.execute("SELECT current_database()").fetchone()[0])


def _create_app_login(admin_dsn: str) -> tuple[str, str]:
    role = f"medawarcre_audit_app_{uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN INHERIT").format(sql.Identifier(role))
        )
        connection.execute(
            sql.SQL("GRANT medawarcre_app TO {}").format(sql.Identifier(role))
        )
    return role, admin_dsn.replace("user=postgres", f"user={role}")


def test_bootstrap_logins_have_exact_pg16_membership_options(postgres_cluster) -> None:
    expected = {
        "medawarcre_test_migration": (
            "medawarcre_migration",
            False,
            False,
            True,
        ),
        "medawarcre_test_app": ("medawarcre_app", False, True, True),
        "medawarcre_test_admin": ("medawarcre_admin", False, True, True),
        "medawarcre_test_backup": ("medawarcre_backup", False, True, True),
        "medawarcre_test_admission": (
            "medawarcre_admission",
            False,
            False,
            True,
        ),
    }
    with psycopg.connect(postgres_cluster.dsn()) as connection:
        actual = {
            str(row[0]): tuple(row[1:])
            for row in connection.execute(
                "SELECT member.rolname,parent.rolname,membership.admin_option,"
                "membership.inherit_option,membership.set_option "
                "FROM pg_catalog.pg_auth_members membership "
                "JOIN pg_catalog.pg_roles member ON member.oid=membership.member "
                "JOIN pg_catalog.pg_roles parent ON parent.oid=membership.roleid "
                "WHERE member.rolname = ANY(%s) ORDER BY member.rolname",
                (list(expected),),
            )
        }
    assert actual == expected


@pytest.mark.parametrize(
    "membership_option",
    (
        "WITH ADMIN OPTION",
        "WITH INHERIT FALSE",
        "WITH SET FALSE",
    ),
)
def test_runtime_rejects_drifted_pg16_membership_options(
    postgres_database: tuple[str, str, str], membership_option: str
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    role = f"medawarcre_audit_membership_{uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN INHERIT").format(sql.Identifier(role))
        )
        connection.execute(
            sql.SQL("GRANT medawarcre_app TO {} {}").format(
                sql.Identifier(role), sql.SQL(membership_option)
            )
        )
    database = PostgresDatabase(
        PostgresSettings(
            dsn=admin_dsn.replace("user=postgres", f"user={role}"),
            min_size=0,
            max_size=1,
        )
    )
    try:
        with pytest.raises(UnsafeRuntimeRoleError, match="least-privilege"):
            database.open(wait=True)
    finally:
        database.close()


@pytest.mark.parametrize(
    "grant_kind",
    (
        "database",
        "schema",
        "table",
        "column",
        "function",
        "sequence",
        "type",
        "default",
    ),
)
def test_runtime_preflight_rejects_direct_login_acl_without_readiness(
    postgres_database: tuple[str, str, str], grant_kind: str
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    role, unsafe_dsn = _create_app_login(admin_dsn)
    database_name = _database_name(admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        if grant_kind == "database":
            connection.execute(
                sql.SQL("GRANT CREATE ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name), sql.Identifier(role)
                )
            )
        elif grant_kind == "schema":
            connection.execute(
                sql.SQL("GRANT CREATE ON SCHEMA medawarcre TO {}").format(
                    sql.Identifier(role)
                )
            )
        elif grant_kind == "table":
            connection.execute(
                sql.SQL("GRANT SELECT ON medawarcre.provider_events TO {}").format(
                    sql.Identifier(role)
                )
            )
        elif grant_kind == "column":
            connection.execute(
                sql.SQL(
                    "GRANT SELECT (event_projection) "
                    "ON medawarcre.provider_events TO {}"
                ).format(sql.Identifier(role))
            )
        elif grant_kind == "function":
            connection.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION medawarcre.current_workspace_id() TO {}"
                ).format(sql.Identifier(role))
            )
        elif grant_kind == "sequence":
            connection.execute("CREATE SEQUENCE medawarcre.audit_direct_sequence")
            connection.execute(
                sql.SQL(
                    "GRANT USAGE ON SEQUENCE medawarcre.audit_direct_sequence TO {}"
                ).format(sql.Identifier(role))
            )
        elif grant_kind == "type":
            connection.execute(
                "CREATE TYPE medawarcre.audit_direct_type AS ENUM ('audit')"
            )
            connection.execute(
                sql.SQL("GRANT USAGE ON TYPE medawarcre.audit_direct_type TO {}").format(
                    sql.Identifier(role)
                )
            )
        else:
            connection.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA medawarcre "
                    "GRANT SELECT ON TABLES TO {}"
                ).format(sql.Identifier(role))
            )

    database = PostgresDatabase(
        PostgresSettings(dsn=unsafe_dsn, min_size=0, max_size=1)
    )
    try:
        with pytest.raises(UnsafeRuntimeRoleError, match="least-privilege"):
            database.open(wait=True)
    finally:
        database.close()


def test_runtime_preflight_rejects_explicit_public_acl_without_readiness(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    _, unsafe_dsn = _create_app_login(admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "GRANT SELECT ON medawarcre.provider_events TO PUBLIC"
        )

    database = PostgresDatabase(
        PostgresSettings(dsn=unsafe_dsn, min_size=0, max_size=1)
    )
    try:
        with pytest.raises(UnsafeRuntimeRoleError, match="least-privilege"):
            database.open(wait=True)
    finally:
        database.close()


def test_admission_preflight_rejects_direct_function_acl(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    admission_dsn = app_dsn.replace(
        "user=medawarcre_test_app", "user=medawarcre_test_admission"
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "GRANT EXECUTE ON FUNCTION medawarcre.current_workspace_id() "
            "TO medawarcre_test_admission"
        )
    with psycopg.connect(admission_dsn) as connection:
        with pytest.raises(UnsafeDatabaseRoleError, match="authority contract"):
            assert_admission_session(connection)


def test_migration_preflight_rejects_direct_database_acl_before_schema_mutation(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    database_name = _database_name(admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL(
                "GRANT CREATE ON DATABASE {} TO medawarcre_test_migration"
            ).format(sql.Identifier(database_name))
        )
    with pytest.raises(UnsafeMigrationRoleError, match="authority contract"):
        MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT to_regnamespace('medawarcre')"
        ).fetchone() == (None,)


def test_migration_preflight_rejects_direct_database_ownership_before_schema_mutation(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    database_name = _database_name(admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO medawarcre_test_migration").format(
                sql.Identifier(database_name)
            )
        )
    with pytest.raises(UnsafeMigrationRoleError, match="authority contract"):
        MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT to_regnamespace('medawarcre')"
        ).fetchone() == (None,)


def test_migration_preflight_accepts_group_inherited_ownership(
    postgres_database: tuple[str, str, str],
) -> None:
    _, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(migration_dsn) as connection:
        assert_migration_session(connection)


@pytest.mark.parametrize(
    "object_kind",
    ("database", "schema", "relation", "function", "type"),
)
def test_migration_preflight_rejects_direct_login_ownership(
    postgres_database: tuple[str, str, str], object_kind: str
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    database_name = _database_name(admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        if object_kind == "relation":
            connection.execute(
                "CREATE TABLE medawarcre.audit_direct_login_owned(id integer)"
            )
        elif object_kind == "function":
            connection.execute(
                "CREATE FUNCTION medawarcre.audit_direct_login_owned() "
                "RETURNS integer LANGUAGE sql AS 'SELECT 1'"
            )
            connection.execute(
                "REVOKE ALL ON FUNCTION medawarcre.audit_direct_login_owned() "
                "FROM PUBLIC"
            )
        elif object_kind == "type":
            connection.execute(
                "CREATE TYPE medawarcre.audit_direct_login_owned "
                "AS ENUM ('audit')"
            )
            connection.execute(
                "REVOKE ALL ON TYPE medawarcre.audit_direct_login_owned FROM PUBLIC"
            )
        if object_kind == "database":
            connection.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO medawarcre_test_migration").format(
                    sql.Identifier(database_name)
                )
            )
        elif object_kind == "schema":
            connection.execute(
                "ALTER SCHEMA medawarcre OWNER TO medawarcre_test_migration"
            )
        elif object_kind == "relation":
            connection.execute(
                "ALTER TABLE medawarcre.audit_direct_login_owned "
                "OWNER TO medawarcre_test_migration"
            )
        elif object_kind == "function":
            connection.execute(
                "ALTER FUNCTION medawarcre.audit_direct_login_owned() "
                "OWNER TO medawarcre_test_migration"
            )
        else:
            connection.execute(
                "ALTER TYPE medawarcre.audit_direct_login_owned "
                "OWNER TO medawarcre_test_migration"
            )

    with psycopg.connect(migration_dsn) as connection:
        with pytest.raises(UnsafeMigrationRoleError, match="authority contract"):
            assert_migration_session(connection)


@pytest.mark.parametrize("outcome", ("applied", "duplicate", "stale", "reconciled"))
def test_provider_event_rejects_workspace_free_mapped_lifecycle_outcomes(
    postgres_database: tuple[str, str, str], outcome: str
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO medawarcre.provider_events("
                "workspace_id,provider,event_id_hash,canonical_action,outcome,"
                "payload_fingerprint,occurred_at,mapping_provenance) "
                "VALUES (NULL,'stripe',%s,'subscription.updated',%s,%s,"
                "statement_timestamp(),'{\"mapper\":\"v1\"}'::jsonb)",
                (bytes.fromhex(uuid4().hex * 2), outcome, bytes.fromhex(uuid4().hex * 2)),
            )


def test_workspace_free_provider_evidence_is_limited_to_unmapped_or_malformed(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        for outcome in ("unmapped", "malformed"):
            event_id = connection.execute(
                "INSERT INTO medawarcre.provider_events("
                "workspace_id,provider,event_id_hash,canonical_action,outcome,"
                "payload_fingerprint,occurred_at,mapping_provenance) "
                "VALUES (NULL,'stripe',%s,'unknown',%s,%s,statement_timestamp(),"
                "'{\"mapper\":\"evidence-v1\"}'::jsonb) RETURNING id",
                (bytes.fromhex(uuid4().hex * 2), outcome, bytes.fromhex(uuid4().hex * 2)),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO medawarcre.provider_event_attempts("
                "workspace_id,provider_event_id,outcome,reason_code) "
                "VALUES (NULL,%s,%s,'no_workspace_binding')",
                (event_id, outcome),
            )


def test_workspace_free_attempt_cannot_reference_workspace_mapped_event(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    workspace_id = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name) "
            "VALUES (%s,%s,'Audit Workspace')",
            (workspace_id, f"ws_audit_{uuid4().hex[:12]}"),
        )
        event_id = connection.execute(
            "INSERT INTO medawarcre.provider_events("
            "workspace_id,provider,event_id_hash,canonical_action,outcome,"
            "payload_fingerprint,occurred_at,mapping_provenance) "
            "VALUES (%s,'stripe',%s,'subscription.updated','applied',%s,"
            "statement_timestamp(),'{\"mapper\":\"v1\"}'::jsonb) RETURNING id",
            (workspace_id, bytes.fromhex(uuid4().hex * 2), bytes.fromhex(uuid4().hex * 2)),
        ).fetchone()[0]
        with pytest.raises((psycopg.errors.ForeignKeyViolation, psycopg.errors.CheckViolation)):
            connection.execute(
                "INSERT INTO medawarcre.provider_event_attempts("
                "workspace_id,provider_event_id,outcome,reason_code) "
                "VALUES (NULL,%s,'applied','incorrect_null_binding')",
                (event_id,),
            )


def test_mapping_an_event_propagates_the_exact_attempt_workspace_binding(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    workspace_id = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name) "
            "VALUES (%s,%s,'Mapped Workspace')",
            (workspace_id, f"ws_mapped_{uuid4().hex[:12]}"),
        )
        event_id = connection.execute(
            "INSERT INTO medawarcre.provider_events("
            "workspace_id,provider,event_id_hash,canonical_action,outcome,"
            "payload_fingerprint,occurred_at) "
            "VALUES (NULL,'stripe',%s,'unknown','unmapped',%s,"
            "statement_timestamp()) RETURNING id",
            (bytes.fromhex(uuid4().hex * 2), bytes.fromhex(uuid4().hex * 2)),
        ).fetchone()[0]
        attempt_id = connection.execute(
            "INSERT INTO medawarcre.provider_event_attempts("
            "workspace_id,provider_event_id,outcome) "
            "VALUES (NULL,%s,'unmapped') RETURNING id",
            (event_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE medawarcre.provider_events "
            "SET workspace_id=%s,outcome='applied' WHERE id=%s",
            (workspace_id, event_id),
        )
        assert connection.execute(
            "SELECT workspace_id FROM medawarcre.provider_event_attempts WHERE id=%s",
            (attempt_id,),
        ).fetchone() == (UUID(workspace_id),)


def test_default_acl_drift_changes_fingerprint_readiness_and_restore_verification(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    migrations = load_migrations()
    MigrationRunner(migration_dsn, migrations).apply()
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=1)
    )
    database.open(wait=True)
    try:
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            baseline = catalog_fingerprint(connection)
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA medawarcre "
                "GRANT EXECUTE ON FUNCTIONS TO PUBLIC"
            )
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            assert catalog_fingerprint(connection) != baseline
            with pytest.raises(BackupVerificationError, match="privilege"):
                _verify_exact_privileges(connection)
        readiness = check_readiness(database, expected=migrations)
        assert readiness.ok is False
        assert readiness.schema_drift is True
    finally:
        database.close()


def test_database_acl_and_group_role_drift_change_release_fingerprint(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    database_name = _database_name(admin_dsn)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        baseline = catalog_fingerprint(connection)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("GRANT CREATE ON DATABASE {} TO medawarcre_app").format(
                sql.Identifier(database_name)
            )
        )
    try:
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            assert catalog_fingerprint(connection) != baseline
            with pytest.raises(BackupVerificationError, match="privilege"):
                _verify_exact_privileges(connection)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("REVOKE CREATE ON DATABASE {} FROM medawarcre_app").format(
                    sql.Identifier(database_name)
                )
            )
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        reset = catalog_fingerprint(connection)
    assert reset == baseline
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("ALTER ROLE medawarcre_app CREATEDB")
    try:
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            assert catalog_fingerprint(connection) != reset
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute("ALTER ROLE medawarcre_app NOCREATEDB")


def test_package_metadata_honestly_requires_python_311() -> None:
    root = Path(__file__).parents[2]
    assert 'requires-python = ">=3.11"' in (root / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "Python 3.11+" in (root / "README.md").read_text(encoding="utf-8")


def test_backup_early_command_failure_leaves_no_mode_0600_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "missing-command.dump"

    def unavailable(_: str) -> str:
        raise BackupCommandError("required PostgreSQL command is unavailable: pg_dump")

    monkeypatch.setattr(backup_module, "_native_program", unavailable)
    with pytest.raises(BackupCommandError, match="unavailable"):
        create_backup("dbname=not-opened", destination)
    assert tuple(tmp_path.iterdir()) == ()


def test_backup_version_failure_and_unsafe_preflight_create_no_temp_files(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    backup_dsn = app_dsn.replace(
        "user=medawarcre_test_app", "user=medawarcre_test_backup"
    )
    monkeypatch.setattr(backup_module, "_native_program", lambda _: "/bin/false")

    def version_failure(_: str) -> str:
        raise BackupCommandError("PostgreSQL command version check failed")

    monkeypatch.setattr(backup_module, "_native_version", version_failure)
    with pytest.raises(BackupCommandError, match="version"):
        create_backup(backup_dsn, tmp_path / "version.dump")
    assert tuple(tmp_path.iterdir()) == ()

    monkeypatch.setattr(
        backup_module,
        "_native_version",
        lambda _: "pg_dump (PostgreSQL) 15.13",
    )
    with pytest.raises(BackupCommandError, match="PostgreSQL 16"):
        create_backup(backup_dsn, tmp_path / "unsupported-version.dump")
    assert tuple(tmp_path.iterdir()) == ()

    monkeypatch.undo()
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "GRANT SELECT ON medawarcre.provider_events "
            "TO medawarcre_test_backup"
        )
    with pytest.raises(BackupVerificationError, match="authority"):
        create_backup(backup_dsn, tmp_path / "preflight.dump")
    assert tuple(tmp_path.iterdir()) == ()


def test_secure_default_privileges_cover_future_functions_and_types(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "CREATE FUNCTION medawarcre.audit_future_function() RETURNS integer "
            "LANGUAGE sql AS 'SELECT 1'"
        )
        connection.execute(
            "CREATE TYPE medawarcre.audit_future_type AS ENUM ('future')"
        )
        public_execute = connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_proc procedure "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE("
            "procedure.proacl,pg_catalog.acldefault('f',procedure.proowner))) acl "
            "WHERE procedure.oid='medawarcre.audit_future_function()'::regprocedure "
            "AND acl.grantee=0 AND acl.privilege_type='EXECUTE'"
        ).fetchone()[0]
        app_type_usage = connection.execute(
            "SELECT has_type_privilege('medawarcre_test_app',"
            "'medawarcre.audit_future_type','USAGE')"
        ).fetchone()[0]
    assert public_execute == 0
    assert app_type_usage is False


@pytest.mark.parametrize(
    ("pg_dump_version", "server_version"),
    (
        ("pg_dump (PostgreSQL) 15.13", "16.14"),
        ("pg_dump (PostgreSQL) 16.14", "15.13"),
    ),
)
def test_restore_rejects_manifest_from_pre16_postgresql(
    tmp_path: Path, pg_dump_version: str, server_version: str
) -> None:
    archive = tmp_path / "pre16.dump"
    archive.write_bytes(b"archive")
    payload = BackupManifest(
        format_version=1,
        created_at="2026-08-01T00:00:00Z",
        dump_sha256=hashlib.sha256(b"archive").hexdigest(),
        dump_size=len(b"archive"),
        pg_dump_version=pg_dump_version,
        server_version=server_version,
        schema_fingerprint="0" * 64,
        migration_checksums={},
        migration_descriptions={},
        tables=(),
        row_counts={},
    ).to_dict()
    manifest_path = tmp_path / "pre16.dump.manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BackupVerificationError, match="PostgreSQL 16"):
        restore_backup("dbname=must_not_be_opened", archive, manifest_path)


def test_restore_rejects_pre16_target_before_native_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "target-pre16.dump"
    archive.write_bytes(b"archive")
    manifest = BackupManifest(
        format_version=1,
        created_at="2026-08-01T00:00:00Z",
        dump_sha256=hashlib.sha256(b"archive").hexdigest(),
        dump_size=len(b"archive"),
        pg_dump_version="pg_dump (PostgreSQL) 16.14",
        server_version="16.14",
        schema_fingerprint="0" * 64,
        migration_checksums={},
        migration_descriptions={},
        tables=(),
        row_counts={},
    )

    class FakeConnection:
        info = SimpleNamespace(server_version=150013)

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(backup_module, "load_manifest", lambda _: manifest)
    monkeypatch.setattr(backup_module, "_verify_manifest_contract", lambda _: None)
    monkeypatch.setattr(backup_module.psycopg, "connect", lambda *_, **__: FakeConnection())
    monkeypatch.setattr(backup_module, "_assert_restore_session", lambda _: None)
    monkeypatch.setattr(backup_module, "_assert_bootstrap_roles", lambda _: None)
    monkeypatch.setattr(backup_module, "_assert_clean_target", lambda _: None)

    def native_restore_must_not_run(_: str) -> str:
        raise AssertionError("native restore ran against an unsupported target")

    monkeypatch.setattr(backup_module, "_native_program", native_restore_must_not_run)
    with pytest.raises(BackupVerificationError, match="PostgreSQL 16"):
        restore_backup("dbname=pre16", archive, tmp_path / "ignored.json")
