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
    deal_id, replacement_deal_id, investor_id, exchange_id = (
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
        connection.execute(
            "INSERT INTO medawarcre.deals("
            "id,workspace_id,source,source_record_id,title,listing,asking_price,"
            "stage,score,score_version,grade,strategy,created_by_user_id,"
            "updated_by_user_id,source_rights_id,source_rights_verified_on) VALUES "
            "(%s,%s,'crexi','restore-primary','Restore Primary',"
            "'{\"source\":\"crexi\",\"source_id\":\"restore-primary\","
            "\"address\":\"100 Main Street\",\"city\":\"Los Angeles\","
            "\"state\":\"CA\",\"zip_code\":\"90001\"}'::jsonb,"
            "2500000,'diligence',88,'restore-v1','A','nnn_retail',%s,%s,"
            "'listing.crexi','2026-08-01'),"
            "(%s,%s,'crexi','restore-replacement','Restore Replacement',"
            "'{\"source\":\"crexi\",\"source_id\":\"restore-replacement\","
            "\"address\":\"200 Main Street\",\"city\":\"Los Angeles\","
            "\"state\":\"CA\",\"zip_code\":\"90002\"}'::jsonb,"
            "2850000,'analyzing',82,'restore-v1','B','exchange_replacement',%s,%s,"
            "'listing.crexi','2026-08-01')",
            (
                deal_id,
                workspace_id,
                user_id,
                user_id,
                replacement_deal_id,
                workspace_id,
                user_id,
                user_id,
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_notes("
            "workspace_id,deal_id,author_user_id,body,stage) "
            "VALUES (%s,%s,%s,'Restore note','diligence')",
            (workspace_id, deal_id, user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_outcomes("
            "workspace_id,deal_id,closed,purchase_price,realized_hold_years,"
            "realized_irr,realized_equity_multiple,went_bad,notes,predicted_score,"
            "predicted_grade,predicted_strategy,created_by_user_id,updated_by_user_id) "
            "VALUES (%s,%s,true,2400000,5,0.18,1.9,false,'Restore outcome',"
            "88,'A','nnn_retail',%s,%s)",
            (workspace_id, deal_id, user_id, user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_events("
            "workspace_id,deal_id,event_type,event_data,occurred_at,author_user_id,"
            "request_invocation_id) VALUES "
            "(%s,%s,'inspection_complete','{\"result\":\"clear\"}'::jsonb,"
            "'2026-08-10T12:00:00Z',%s,%s)",
            (workspace_id, deal_id, user_id, str(uuid4())),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_dd_items("
            "workspace_id,deal_id,item_key,item_data,status,deadline,"
            "created_by_user_id,updated_by_user_id) VALUES "
            "(%s,%s,'title','{\"label\":\"Title review\"}'::jsonb,"
            "'complete','2026-08-20',%s,%s)",
            (workspace_id, deal_id, user_id, user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_ops_events("
            "workspace_id,deal_id,event_key,event_data,category,event_date,status,"
            "created_by_user_id,updated_by_user_id) VALUES "
            "(%s,%s,'month-one','{\"label\":\"Tenant handoff\"}'::jsonb,"
            "'month_one','2026-09-01','not_started',%s,%s)",
            (workspace_id, deal_id, user_id, user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_investors("
            "id,workspace_id,name,accredited,accreditation_verified,relationship,"
            "contact,created_by_user_id,updated_by_user_id) VALUES "
            "(%s,%s,'Restore Investor',true,true,'preexisting',"
            "'{\"email\":\"investor@example.test\"}'::jsonb,%s,%s)",
            (investor_id, workspace_id, user_id, user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_commitments("
            "workspace_id,deal_id,investor_id,amount,created_by_user_id,"
            "updated_by_user_id) VALUES (%s,%s,%s,500000,%s,%s)",
            (workspace_id, deal_id, investor_id, user_id, user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_exchanges("
            "id,workspace_id,relinquished_deal_id,relinquished_close_date,"
            "identification_deadline,exchange_deadline,created_by_user_id,"
            "updated_by_user_id) VALUES "
            "(%s,%s,%s,'2026-08-01','2026-09-15','2027-01-28',%s,%s)",
            (exchange_id, workspace_id, deal_id, user_id, user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_exchange_replacements("
            "workspace_id,exchange_id,deal_id,value,identified_at,created_by_user_id) "
            "VALUES (%s,%s,%s,2850000,'2026-08-10',%s)",
            (workspace_id, exchange_id, replacement_deal_id, user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_ic_decisions("
            "workspace_id,deal_id,system_verdict,system_data,expert_verdict,"
            "expert_data,agreed,created_by_user_id,request_invocation_id) VALUES "
            "(%s,%s,'proceed','{\"score\":88}'::jsonb,'proceed',"
            "'{\"reviewer\":\"operator\"}'::jsonb,true,%s,%s)",
            (workspace_id, deal_id, user_id, str(uuid4())),
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
    assert manifest.row_counts["deals"] == 2
    for relation_name in (
        "deal_notes",
        "deal_outcomes",
        "deal_events",
        "deal_dd_items",
        "deal_ops_events",
        "deal_investors",
        "deal_commitments",
        "deal_exchanges",
        "deal_exchange_replacements",
        "deal_ic_decisions",
    ):
        assert manifest.row_counts[relation_name] == 1
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
        restored_graph = connection.execute(
            "SELECT d.source_record_id,n.body,o.purchase_price::text,e.event_type,"
            "dd.item_key,ops.event_key,i.name,c.amount::text,x.relinquished_close_date::text,"
            "r.value::text,ic.system_verdict "
            "FROM medawarcre.deals d "
            "JOIN medawarcre.deal_notes n ON n.workspace_id=d.workspace_id "
            "AND n.deal_id=d.id "
            "JOIN medawarcre.deal_outcomes o ON o.workspace_id=d.workspace_id "
            "AND o.deal_id=d.id "
            "JOIN medawarcre.deal_events e ON e.workspace_id=d.workspace_id "
            "AND e.deal_id=d.id "
            "JOIN medawarcre.deal_dd_items dd ON dd.workspace_id=d.workspace_id "
            "AND dd.deal_id=d.id "
            "JOIN medawarcre.deal_ops_events ops ON ops.workspace_id=d.workspace_id "
            "AND ops.deal_id=d.id "
            "JOIN medawarcre.deal_commitments c ON c.workspace_id=d.workspace_id "
            "AND c.deal_id=d.id "
            "JOIN medawarcre.deal_investors i ON i.workspace_id=c.workspace_id "
            "AND i.id=c.investor_id "
            "JOIN medawarcre.deal_exchanges x ON x.workspace_id=d.workspace_id "
            "AND x.relinquished_deal_id=d.id "
            "JOIN medawarcre.deal_exchange_replacements r "
            "ON r.workspace_id=x.workspace_id AND r.exchange_id=x.id "
            "JOIN medawarcre.deal_ic_decisions ic ON ic.workspace_id=d.workspace_id "
            "AND ic.deal_id=d.id "
            "WHERE d.source_record_id='restore-primary'"
        ).fetchone()
        assert restored_graph == (
            "restore-primary",
            "Restore note",
            "2400000.00",
            "inspection_complete",
            "title",
            "month-one",
            "Restore Investor",
            "500000.00",
            "2026-08-01",
            "2850000.00",
            "proceed",
        )

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

    missing_admin, missing_restore, _ = postgres_cluster.create_database(
        "missing_smoke_target"
    )
    with pytest.raises(BackupVerificationError, match="smoke identities"):
        restore_backup(missing_restore, dump_path, manifest_path)
    with psycopg.connect(missing_admin) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_namespace WHERE nspname='medawarcre'"
        ).fetchone()[0] == 0

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
        restore_backup(
            target_restore,
            dump_path,
            manifest_path,
            smoke_workspace_id=str(uuid4()),
            smoke_actor_user_id=str(uuid4()),
            smoke_other_workspace_id=str(uuid4()),
            smoke_app_dsn=target_restore,
            smoke_backup_dsn=target_restore,
        )

    tampered = tmp_path / "tampered.dump"
    tampered.write_bytes(dump_path.read_bytes() + b"tamper")
    copied_manifest = tmp_path / "tampered.dump.manifest.json"
    copied_manifest.write_text(
        json.dumps(load_manifest(manifest_path).to_dict()), encoding="utf-8"
    )
    _, clean_restore, _ = postgres_cluster.create_database("tamper_target")
    with pytest.raises(BackupVerificationError, match="SHA-256"):
        restore_backup(clean_restore, tampered, copied_manifest)
