from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from cre_mcp.postgres.backup import (
    BackupError,
    BackupVerificationError,
    _assert_bootstrap_roles,
    _verify_restored_database,
    create_backup,
    load_manifest,
    restore_backup,
)
from cre_mcp.postgres.authority import SERVICE_ROLES
from cre_mcp.postgres.migrations import MigrationRunner, load_migrations


def test_restore_preflight_rejects_service_group_role_drift(
    distinct_postgres_cluster,
) -> None:
    service_role = SERVICE_ROLES["oauth"]
    with psycopg.connect(distinct_postgres_cluster.dsn(), autocommit=True) as connection:
        _assert_bootstrap_roles(connection)
        connection.execute(
            sql.SQL("ALTER ROLE {} CREATEDB").format(sql.Identifier(service_role))
        )
        try:
            with pytest.raises(BackupVerificationError, match="bootstrap"):
                _assert_bootstrap_roles(connection)
        finally:
            connection.execute(
                sql.SQL("ALTER ROLE {} NOCREATEDB").format(
                    sql.Identifier(service_role)
                )
            )


def test_restore_preflight_rejects_service_authority_outside_app_schema(
    distinct_postgres_cluster,
) -> None:
    service_role = SERVICE_ROLES["oauth"]
    with psycopg.connect(distinct_postgres_cluster.dsn(), autocommit=True) as connection:
        _assert_bootstrap_roles(connection)
        connection.execute(
            sql.SQL("CREATE SCHEMA service_owned AUTHORIZATION {}").format(
                sql.Identifier(service_role)
            )
        )
        try:
            with pytest.raises(BackupVerificationError, match="authority"):
                _assert_bootstrap_roles(connection)
        finally:
            connection.execute("DROP SCHEMA service_owned")


def _seed_restore_fixture(admin_dsn: str) -> tuple[str, str, str]:
    workspace_id, other_workspace_id, user_id, other_user_id = (
        str(uuid4()) for _ in range(4)
    )
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name) VALUES "
            "(%s,'restore@example.test','Restore'),"
            "(%s,'other-restore@example.test','Other Restore')",
            (user_id, other_user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name) VALUES "
            "(%s,'ws_restore','Restore'),(%s,'ws_other_restore','Other Restore')",
            (workspace_id, other_workspace_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'owner','active'),(%s,%s,'owner','active')",
            (workspace_id, user_id, other_workspace_id, other_user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.jobs("
            "workspace_id,kind,payload,status,idempotency_key,max_attempts) "
            "VALUES (%s,'saved_search','{}','queued','restore:initial',3)",
            (workspace_id,),
        )
    return workspace_id, user_id, other_workspace_id


def test_native_dump_clean_restore_and_service_smoke(
    postgres_cluster,
    distinct_postgres_cluster,
    tmp_path: Path,
) -> None:
    source_admin, source_migration, source_app = postgres_cluster.create_database(
        "backup_source"
    )
    target_admin = distinct_postgres_cluster.create_admin_database("backup_target")
    MigrationRunner(source_migration, load_migrations()).apply()
    workspace_id, user_id, other_workspace_id = _seed_restore_fixture(source_admin)
    source_backup = source_admin.replace(
        "user=postgres", "user=medawarcre_test_backup"
    )
    dump_path = tmp_path / "phase2.dump"

    with (
        psycopg.connect(source_admin) as source_connection,
        psycopg.connect(target_admin) as target_connection,
    ):
        assert source_connection.execute(
            "SHOW data_directory"
        ).fetchone() != target_connection.execute("SHOW data_directory").fetchone()
        assert target_connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_roles "
            "WHERE rolname LIKE 'medawarcre_test_%'"
        ).fetchone()[0] == 0

    distinct_postgres_cluster.sql(
        "CREATE ROLE phase2_restore_login LOGIN NOINHERIT; "
        "GRANT medawarcre_migration TO phase2_restore_login "
        "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE; "
        "CREATE ROLE phase2_restore_app LOGIN; "
        "GRANT medawarcre_app TO phase2_restore_app "
        "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE; "
        "CREATE ROLE phase2_restore_backup LOGIN; "
        "GRANT medawarcre_backup TO phase2_restore_backup "
        "WITH ADMIN FALSE, INHERIT TRUE, SET TRUE;"
    )
    target_restore = target_admin.replace("user=postgres", "user=phase2_restore_login")
    target_app = target_admin.replace("user=postgres", "user=phase2_restore_app")
    target_backup = target_admin.replace(
        "user=postgres", "user=phase2_restore_backup"
    )

    with psycopg.connect(source_backup, autocommit=True) as connection:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE medawarcre_backup")
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.jobs"
            ).fetchone()[0] == 1
        forbidden = (
            (
                "INSERT INTO medawarcre.jobs"
                "(workspace_id,kind,payload,status,idempotency_key,max_attempts) "
                "VALUES (%s,'saved_search','{}'::jsonb,'queued','forbidden',1)",
                (workspace_id,),
            ),
            ("UPDATE medawarcre.jobs SET status='failed'", ()),
            ("DELETE FROM medawarcre.jobs", ()),
            ("CREATE TABLE medawarcre.backup_forbidden(id integer)", ()),
        )
        for statement, parameters in forbidden:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with connection.transaction():
                    connection.execute("SET LOCAL ROLE medawarcre_backup")
                    connection.execute(statement, parameters)

    def commit_after_snapshot_export() -> None:
        with psycopg.connect(source_admin) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "INSERT INTO medawarcre.jobs"
                "(workspace_id,kind,payload,status,idempotency_key,max_attempts) "
                "VALUES (%s,'saved_search','{}'::jsonb,'queued','after-snapshot',1)",
                (workspace_id,),
            )

    manifest_path = create_backup(
        source_backup,
        dump_path,
        _snapshot_ready=commit_after_snapshot_export,
    )
    manifest = load_manifest(manifest_path)
    assert manifest.dump_sha256
    assert manifest.row_counts["jobs"] == 1
    assert dump_path.stat().st_mode & 0o777 == 0o600
    assert manifest_path.stat().st_mode & 0o777 == 0o600

    report = restore_backup(
        target_restore,
        dump_path,
        manifest_path,
        smoke_workspace_id=workspace_id,
        smoke_actor_user_id=user_id,
        smoke_other_workspace_id=other_workspace_id,
        smoke_app_dsn=target_app,
        smoke_backup_dsn=target_backup,
    )
    assert report.ok is True
    assert report.row_counts == manifest.row_counts
    assert report.tenant_isolation is True
    assert report.read_write_smoke is True

    wrong_app_admin = distinct_postgres_cluster.create_admin_database(
        "wrong_app_target"
    )
    wrong_app_restore = wrong_app_admin.replace(
        "user=postgres", "user=phase2_restore_login"
    )
    wrong_app_backup = wrong_app_admin.replace(
        "user=postgres", "user=phase2_restore_backup"
    )
    with pytest.raises(BackupVerificationError, match="bound"):
        restore_backup(
            wrong_app_restore,
            dump_path,
            manifest_path,
            smoke_workspace_id=workspace_id,
            smoke_actor_user_id=user_id,
            smoke_other_workspace_id=other_workspace_id,
            smoke_app_dsn=source_app,
            smoke_backup_dsn=wrong_app_backup,
        )

    wrong_backup_admin = distinct_postgres_cluster.create_admin_database(
        "wrong_backup_target"
    )
    wrong_backup_restore = wrong_backup_admin.replace(
        "user=postgres", "user=phase2_restore_login"
    )
    wrong_backup_app = wrong_backup_admin.replace(
        "user=postgres", "user=phase2_restore_app"
    )
    with pytest.raises(BackupVerificationError, match="bound"):
        restore_backup(
            wrong_backup_restore,
            dump_path,
            manifest_path,
            smoke_workspace_id=workspace_id,
            smoke_actor_user_id=user_id,
            smoke_other_workspace_id=other_workspace_id,
            smoke_app_dsn=wrong_backup_app,
            smoke_backup_dsn=source_backup,
        )

    assert MigrationRunner(target_restore, load_migrations()).apply() == []
    with (
        psycopg.connect(source_admin) as source_connection,
        psycopg.connect(target_admin) as connection,
    ):
        assert source_connection.execute(
            "SELECT count(*) FROM medawarcre.jobs"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.jobs"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT owner.rolname FROM pg_catalog.pg_namespace namespace "
            "JOIN pg_catalog.pg_roles owner ON owner.oid=namespace.nspowner "
            "WHERE namespace.nspname='medawarcre'"
        ).fetchone()[0] == "medawarcre_migration"
        assert connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_class relation "
            "JOIN pg_catalog.pg_namespace namespace "
            "ON namespace.oid=relation.relnamespace "
            "JOIN pg_catalog.pg_roles owner ON owner.oid=relation.relowner "
            "WHERE namespace.nspname='medawarcre' "
            "AND relation.relkind IN ('r','p') "
            "AND owner.rolname<>'medawarcre_migration'"
        ).fetchone()[0] == 0

    with psycopg.connect(target_admin, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute("ALTER TABLE medawarcre.users DISABLE ROW LEVEL SECURITY")
    with pytest.raises(BackupVerificationError, match="RLS"):
        _verify_restored_database(target_restore, manifest)
    with psycopg.connect(target_admin, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute("ALTER TABLE medawarcre.users ENABLE ROW LEVEL SECURITY")
    assert _verify_restored_database(target_restore, manifest) == manifest.row_counts


def test_restore_rejects_non_clean_target_and_tampered_dump(
    postgres_cluster,
    tmp_path: Path,
) -> None:
    source_admin, source_migration, _ = postgres_cluster.create_database("reject_source")
    target_admin, target_restore, _ = postgres_cluster.create_database("reject_target")
    MigrationRunner(source_migration, load_migrations()).apply()
    source_backup = source_admin.replace(
        "user=postgres", "user=medawarcre_test_backup"
    )
    dump_path = tmp_path / "reject.dump"

    dangerous_group = f"medawarcre_backup_danger_{uuid4().hex[:8]}"
    postgres_cluster.sql(
        f'CREATE ROLE "{dangerous_group}" NOLOGIN CREATEROLE; '
        f'GRANT "{dangerous_group}" TO medawarcre_backup;'
    )
    unsafe_dump = tmp_path / "unsafe.dump"
    try:
        with pytest.raises(BackupVerificationError, match="authority"):
            create_backup(source_backup, unsafe_dump)
    finally:
        postgres_cluster.sql(
            f'REVOKE "{dangerous_group}" FROM medawarcre_backup;'
        )
    assert not unsafe_dump.exists()
    assert not Path(str(unsafe_dump) + ".manifest.json").exists()

    manifest_path = create_backup(source_backup, dump_path)

    with psycopg.connect(source_admin, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute("DROP INDEX medawarcre.deals_workspace_stage_idx")
    drifted_dump = tmp_path / "drifted.dump"
    with pytest.raises(BackupVerificationError, match="catalog"):
        create_backup(source_backup, drifted_dump)
    assert not drifted_dump.exists()
    assert not Path(str(drifted_dump) + ".manifest.json").exists()
    with psycopg.connect(source_admin, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "CREATE INDEX deals_workspace_stage_idx ON medawarcre.deals "
            "(workspace_id,stage,updated_at DESC)"
        )

    stranded_dump = tmp_path / "stranded.dump"

    def fail_between_publications() -> None:
        raise RuntimeError("injected publication failure")

    with pytest.raises(RuntimeError, match="injected publication failure"):
        create_backup(
            source_backup,
            stranded_dump,
            _after_dump_publish=fail_between_publications,
        )
    assert not stranded_dump.exists()
    assert not Path(str(stranded_dump) + ".manifest.json").exists()

    existing_dump = tmp_path / "existing.dump"
    existing_dump.write_bytes(b"preserve-me")
    with pytest.raises(BackupError, match="already exists"):
        create_backup(source_backup, existing_dump)
    assert existing_dump.read_bytes() == b"preserve-me"

    with psycopg.connect(target_admin) as connection:
        connection.execute("CREATE TABLE public.not_clean(id integer)")
    with pytest.raises(BackupVerificationError, match="clean"):
        restore_backup(target_restore, dump_path, manifest_path)

    tampered = tmp_path / "tampered.dump"
    tampered.write_bytes(dump_path.read_bytes() + b"tamper")
    copied_manifest = tmp_path / "tampered.dump.manifest.json"
    copied_manifest.write_text(
        json.dumps(load_manifest(manifest_path).to_dict()), encoding="utf-8"
    )
    _, clean_restore, _ = postgres_cluster.create_database("tamper_target")
    with pytest.raises(BackupVerificationError, match="SHA-256"):
        restore_backup(clean_restore, tampered, copied_manifest)
