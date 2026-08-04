from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from cre_mcp.postgres.authority import (
    UnsafeDatabaseRoleError,
    assert_admission_session,
)
from cre_mcp.postgres.migrations import MigrationRunner, load_migrations
from cre_mcp.postgres.schema import EXPECTED_RLS_TABLES, EXPECTED_TABLES


def _seed_two_tenants(connection: psycopg.Connection) -> tuple[str, str, str, str]:
    workspace_a, workspace_b, user_a, user_b = (str(uuid4()) for _ in range(4))
    connection.execute("SET ROLE medawarcre_migration")
    connection.execute(
        "INSERT INTO medawarcre.users(id,email,name) VALUES "
        "(%s,'a@example.test','A'),(%s,'b@example.test','B')",
        (user_a, user_b),
    )
    connection.execute(
        "INSERT INTO medawarcre.workspaces(id,public_id,name) VALUES "
        "(%s,'ws_a','Workspace A'),(%s,'ws_b','Workspace B')",
        (workspace_a, workspace_b),
    )
    connection.execute(
        "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) VALUES "
        "(%s,%s,'owner','active'),(%s,%s,'owner','active')",
        (workspace_a, user_a, workspace_b, user_b),
    )
    connection.execute(
        "INSERT INTO medawarcre.staff_roles(user_id,role,active) "
        "VALUES (%s,'read_only_analyst',true)",
        (user_a,),
    )
    connection.execute(
        "INSERT INTO medawarcre.deals(id,workspace_id,source,source_record_id,title,stage) "
        "VALUES (%s,%s,'fixture','a-1','A Deal','lead'),"
        "(%s,%s,'fixture','b-1','B Deal','lead')",
        (str(uuid4()), workspace_a, str(uuid4()), workspace_b),
    )
    return workspace_a, workspace_b, user_a, user_b


def test_rls_and_composite_constraints_block_cross_tenant_access(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        workspace_a, workspace_b, user_a, _ = _seed_two_tenants(connection)

    with psycopg.connect(app_dsn) as connection:
        connection.execute(
            "SELECT set_config('app.workspace_id', %s, true), "
            "set_config('app.actor_user_id', %s, true)",
            (workspace_a, user_a),
        )
        assert connection.execute(
            "SELECT title FROM medawarcre.deals ORDER BY title"
        ).fetchall() == [("A Deal",)]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO medawarcre.deals"
                "(workspace_id,source,source_record_id,title,stage) "
                "VALUES (%s,'fixture','cross-tenant','Bad Deal','lead')",
                (workspace_b,),
            )
        connection.rollback()

    protected_control_tables = (
        "memberships",
        "workspace_accounts",
        "connected_clients",
        "integration_events",
        "subscriptions",
        "access_grants",
        "oauth_sessions",
        "oauth_codes",
        "oauth_refresh_history",
        "external_accounts",
        "provider_events",
        "provider_event_attempts",
        "retention_actions",
        "access_decision_audit",
        "tool_approvals",
        "daily_quota_usage",
        "legacy_id_aliases",
        "search_runs",
        "search_results",
        "jobs",
        "job_attempts",
        "skool_join_tasks",
        "skool_reconciliations",
    )
    for table in protected_control_tables:
        with psycopg.connect(app_dsn) as connection:
            connection.execute(
                "SELECT set_config('app.workspace_id', %s, true), "
                "set_config('app.actor_user_id', %s, true)",
                (workspace_a, user_a),
            )
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.memberships"
            ).fetchone()[0] == 1
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    sql.SQL("DELETE FROM medawarcre.{} WHERE workspace_id=%s").format(
                        sql.Identifier(table)
                    ),
                    (workspace_a,),
                )
            connection.rollback()

    for table in (
        "oauth_sessions",
        "oauth_codes",
        "oauth_refresh_history",
        "external_accounts",
        "connected_clients",
        "integration_events",
        "provider_events",
        "provider_event_attempts",
        "retention_actions",
        "access_decision_audit",
        "tool_approvals",
        "daily_quota_usage",
        "legacy_id_aliases",
        "jobs",
        "job_attempts",
        "browser_sessions",
        "operator_sessions",
        "oauth_authorization_requests",
        "skool_join_tasks",
        "skool_reconciliations",
    ):
        with psycopg.connect(app_dsn) as connection:
            connection.execute(
                "SELECT set_config('app.workspace_id', %s, true), "
                "set_config('app.actor_user_id', %s, true)",
                (workspace_a, user_a),
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    sql.SQL("SELECT * FROM medawarcre.{}").format(
                        sql.Identifier(table)
                    )
                )
            connection.rollback()

    with psycopg.connect(app_dsn) as connection:
        connection.execute(
            "SELECT set_config('app.workspace_id', %s, true), "
            "set_config('app.actor_user_id', %s, true)",
            (workspace_a, user_a),
        )
        assert connection.execute(
            "SELECT status FROM medawarcre.subscriptions"
        ).fetchall() == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT external_subscription_hash FROM medawarcre.subscriptions"
            )
        connection.rollback()
    with psycopg.connect(app_dsn) as connection:
        connection.execute(
            "SELECT set_config('app.workspace_id', %s, true), "
            "set_config('app.actor_user_id', %s, true)",
            (workspace_a, user_a),
        )
        assert connection.execute(
            "SELECT profile FROM medawarcre.access_grants"
        ).fetchall() == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT external_ref_hash FROM medawarcre.access_grants"
            )
        connection.rollback()

    with psycopg.connect(app_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT medawarcre.consume_daily_quota(%s,'find_deals',1,1)",
                (workspace_a,),
            )
        connection.rollback()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        deal_a = connection.execute(
            "SELECT id FROM medawarcre.deals WHERE workspace_id=%s", (workspace_a,)
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO medawarcre.deal_notes"
                "(workspace_id,deal_id,author_user_id,body) VALUES (%s,%s,%s,'bad')",
                (workspace_b, deal_a, user_a),
            )


def test_internal_index_has_no_customer_grant_and_admin_needs_reason(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        workspace_a, _, user_a, user_b = _seed_two_tenants(connection)
        connection.execute("SET ROLE medawarcre_migration")
        opportunity_id = str(uuid4())
        connection.execute(
            "INSERT INTO medawarcre.internal_opportunities"
            "(id,canonical_key,title,status) VALUES (%s,'fixture:1','Combined','active')",
            (opportunity_id,),
        )
        connection.execute(
            "INSERT INTO medawarcre.internal_opportunity_sources"
            "(workspace_id,opportunity_id,source,source_record_id,access_class,"
            "score_version,provenance) VALUES (%s,%s,'fixture','a-1','private',"
            "'score-v1','{}'::jsonb)",
            (workspace_a, opportunity_id),
        )

    with psycopg.connect(app_dsn) as connection:
        connection.execute(
            "SELECT set_config('app.workspace_id', %s, true), "
            "set_config('app.actor_user_id', %s, true)",
            (workspace_a, user_a),
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM medawarcre.internal_opportunities")

    admin_login_dsn = app_dsn.replace(
        "user=medawarcre_test_app", "user=medawarcre_test_admin"
    )
    with psycopg.connect(admin_login_dsn) as connection:
        connection.execute(
            "SELECT set_config('app.internal_role','read_only_analyst',true), "
            "set_config('app.actor_user_id',%s,true)",
            (user_a,),
        )
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.internal_opportunity_sources"
        ).fetchone()[0] == 0
        connection.execute(
            "SELECT set_config('app.audit_reason','duplicate review',true)"
        )
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.internal_opportunity_sources"
        ).fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO medawarcre.internal_opportunities"
                "(canonical_key,title,status) VALUES ('forbidden','No','active')"
            )
        connection.rollback()

    with psycopg.connect(admin_login_dsn) as connection:
        connection.execute(
            "SELECT set_config('app.internal_role','read_only_analyst',true), "
            "set_config('app.actor_user_id',%s,true), "
            "set_config('app.audit_reason','duplicate review',true)",
            (user_a,),
        )
        connection.execute(
            "INSERT INTO medawarcre.staff_audit_log"
            "(actor_user_id,actor_role,reason,reason_code,workspace_id,"
            "object_type,object_id,action,result) "
            "VALUES (%s,'read_only_analyst','duplicate review','inspection',%s,"
            "'internal_opportunity',%s,'inspect','succeeded')",
            (user_a, workspace_a, opportunity_id),
        )

    forged_rows = (
        (user_b, "read_only_analyst", "duplicate review"),
        (user_a, "support", "duplicate review"),
        (user_a, "read_only_analyst", "fabricated reason"),
    )
    for actor_user_id, actor_role, reason in forged_rows:
        with psycopg.connect(admin_login_dsn) as connection:
            connection.execute(
                "SELECT set_config('app.internal_role','read_only_analyst',true), "
                "set_config('app.actor_user_id',%s,true), "
                "set_config('app.audit_reason','duplicate review',true)",
                (user_a,),
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "INSERT INTO medawarcre.staff_audit_log"
                    "(actor_user_id,actor_role,reason,reason_code,workspace_id,"
                    "object_type,object_id,action,result) "
                    "VALUES (%s,%s,%s,'inspection',%s,'internal_opportunity',"
                    "%s,'inspect','denied')",
                    (
                        actor_user_id,
                        actor_role,
                        reason,
                        workspace_a,
                        opportunity_id,
                    ),
                )
            connection.rollback()

    owner_dsn = admin_login_dsn
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "UPDATE medawarcre.staff_roles SET role='owner' WHERE user_id=%s",
            (user_a,),
        )
    with psycopg.connect(owner_dsn) as connection:
        connection.execute(
            "SELECT set_config('app.internal_role','owner',true), "
            "set_config('app.actor_user_id',%s,true), "
            "set_config('app.audit_reason','authorized correction',true)",
            (user_a,),
        )
        connection.execute(
            "INSERT INTO medawarcre.internal_opportunities"
            "(canonical_key,title,status) VALUES ('owner-write','Yes','active')"
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "UPDATE medawarcre.staff_audit_log SET result='failed'"
            )

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.staff_audit_log"
        ).fetchone()[0] == 1
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE medawarcre.staff_audit_log SET result='failed'"
            )

    for internal_role in ("support", "owner"):
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.staff_roles SET role=%s WHERE user_id=%s",
                (internal_role, user_a),
            )
        with psycopg.connect(admin_login_dsn) as connection:
            connection.execute(
                "SELECT set_config('app.internal_role',%s,true), "
                "set_config('app.actor_user_id',%s,true), "
                "set_config('app.audit_reason','control-table proof',true)",
                (internal_role, user_a),
            )
            for statement in (
                "UPDATE medawarcre.schema_migrations SET state='pending'",
                "UPDATE medawarcre.plans SET active=false",
                "UPDATE medawarcre.oauth_clients SET active=false",
                "DELETE FROM medawarcre.access_decision_audit",
                "DELETE FROM medawarcre.tool_approvals",
                "DELETE FROM medawarcre.daily_quota_usage",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(statement)
                connection.rollback()
                connection.execute(
                    "SELECT set_config('app.internal_role',%s,true), "
                    "set_config('app.actor_user_id',%s,true), "
                    "set_config('app.audit_reason','control-table proof',true)",
                    (internal_role, user_a),
                )


def test_schema_uses_native_types_rls_and_validated_foreign_keys(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname='medawarcre'"
            )
        }
        assert EXPECTED_TABLES <= tables
        rls = {
            row[0]
            for row in connection.execute(
                "SELECT relname FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='medawarcre' AND c.relrowsecurity"
            )
        }
        assert rls == EXPECTED_RLS_TABLES
        invalid_foreign_keys = connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_constraint c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.connamespace "
            "WHERE n.nspname='medawarcre' AND c.contype='f' AND NOT c.convalidated"
        ).fetchone()[0]
        assert invalid_foreign_keys == 0
        types = dict(
            connection.execute(
                "SELECT column_name,data_type FROM information_schema.columns "
                "WHERE table_schema='medawarcre' AND table_name='deal_outcomes'"
            ).fetchall()
        )
        assert types["purchase_price"] == "numeric"
        assert types["created_at"] == "timestamp with time zone"


def test_internal_authority_requires_a_live_exact_staff_role(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        _, _, user_a, user_b = _seed_two_tenants(connection)
    admin_login_dsn = app_dsn.replace(
        "user=medawarcre_test_app", "user=medawarcre_test_admin"
    )

    def authorized(actor: str, role: str) -> bool:
        with psycopg.connect(admin_login_dsn) as connection:
            connection.execute(
                "SELECT set_config('app.internal_role',%s,true),"
                "set_config('app.actor_user_id',%s,true),"
                "set_config('app.audit_reason','live role proof',true)",
                (role, actor),
            )
            return bool(
                connection.execute(
                    "SELECT medawarcre.internal_authorized()"
                ).fetchone()[0]
            )

    assert authorized(user_a, "read_only_analyst") is True
    assert authorized(user_a, "support") is False
    assert authorized(user_b, "read_only_analyst") is False

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "UPDATE medawarcre.staff_roles SET active=false WHERE user_id=%s",
            (user_a,),
        )
    assert authorized(user_a, "read_only_analyst") is False

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "UPDATE medawarcre.staff_roles SET active=true,role='support' "
            "WHERE user_id=%s",
            (user_a,),
        )
    assert authorized(user_a, "read_only_analyst") is False
    assert authorized(user_a, "support") is True


def test_admission_role_exposes_only_atomic_admission_operations(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    admission_dsn = app_dsn.replace(
        "user=medawarcre_test_app", "user=medawarcre_test_admission"
    )
    with psycopg.connect(admission_dsn) as connection:
        assert_admission_session(connection)
        connection.execute("SET ROLE medawarcre_admission")
        assert connection.execute(
            "SELECT session_user,current_user"
        ).fetchone() == (
            "medawarcre_test_admission",
            "medawarcre_admission",
        )
        for signature in (
            "medawarcre.consume_tool_approval(bytea,uuid,uuid,bytea,text,bytea)",
            "medawarcre.consume_daily_quota(uuid,text,bigint,bigint)",
            "medawarcre.record_access_decision(uuid,text,boolean,uuid,uuid,bytea,uuid,text,text,text,text)",
        ):
            assert connection.execute(
                "SELECT pg_catalog.has_function_privilege(current_user,%s,'EXECUTE')",
                (signature,),
            ).fetchone() == (False,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM medawarcre.tool_approvals")
        connection.rollback()

    with psycopg.connect(admin_dsn) as connection:
        with pytest.raises(UnsafeDatabaseRoleError):
            assert_admission_session(connection)

    inherited_login = f"medawarcre_test_admission_inherit_{uuid4().hex[:8]}"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN INHERIT").format(
                sql.Identifier(inherited_login)
            )
        )
        connection.execute(
            sql.SQL("GRANT medawarcre_admission TO {}").format(
                sql.Identifier(inherited_login)
            )
        )
    inherited_dsn = admin_dsn.replace("user=postgres", f"user={inherited_login}")
    with psycopg.connect(inherited_dsn) as connection:
        with pytest.raises(UnsafeDatabaseRoleError):
            assert_admission_session(connection)


def test_access_decision_audit_is_bound_two_phase_and_append_only(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        workspace_id, _, user_id, _ = _seed_two_tenants(connection)
        connection.execute("SET ROLE medawarcre_migration")
        admission_id = connection.execute(
            "INSERT INTO medawarcre.access_decision_audit("
            "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
            "session_correlation_hash,request_correlation_id,tool_name,decision,"
            "reason_code,safe_reason,args_hash) "
            "VALUES (%s,'admission',true,%s,%s,%s,%s,'find_deals','denied',"
            "'test_denial','test denial',%s) RETURNING id",
            (str(uuid4()), workspace_id, user_id, b"c" * 32, str(uuid4()), b"a" * 32),
        ).fetchone()[0]
        connection.commit()
        connection.execute("SET ROLE medawarcre_migration")
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE medawarcre.access_decision_audit "
                "SET safe_reason='rewritten' WHERE id=%s",
                (admission_id,),
            )
        connection.rollback()
        connection.execute("SET ROLE medawarcre_migration")
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "DELETE FROM medawarcre.access_decision_audit WHERE id=%s",
                (admission_id,),
            )


def test_app_identity_rows_are_actor_owned_while_deal_content_is_shared(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        workspace_id, _, actor_id, _ = _seed_two_tenants(connection)
        connection.execute("SET ROLE medawarcre_migration")
        peer_id = str(uuid4())
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name) "
            "VALUES (%s,'peer@example.test','Peer')",
            (peer_id,),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'member','active')",
            (workspace_id, peer_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.access_grants("
            "workspace_id,subject_user_id,scope,source,external_ref_hash,profile,"
            "status,starts_at) VALUES "
            "(%s,NULL,'workspace','jv',%s,'full_operator','active',"
            "statement_timestamp()),"
            "(%s,%s,'subject','manual',%s,'local_scout','active',"
            "statement_timestamp()),"
            "(%s,%s,'subject','manual',%s,'local_scout','active',"
            "statement_timestamp())",
            (
                workspace_id,
                b"w" * 32,
                workspace_id,
                actor_id,
                b"a" * 32,
                workspace_id,
                peer_id,
                b"p" * 32,
            ),
        )
        actor_search = connection.execute(
            "INSERT INTO medawarcre.saved_searches("
            "workspace_id,owner_user_id,name,query) "
            "VALUES (%s,%s,'Actor search','{}') RETURNING id",
            (workspace_id, actor_id),
        ).fetchone()[0]
        peer_search = connection.execute(
            "INSERT INTO medawarcre.saved_searches("
            "workspace_id,owner_user_id,name,query) "
            "VALUES (%s,%s,'Peer search','{}') RETURNING id",
            (workspace_id, peer_id),
        ).fetchone()[0]
        actor_run = connection.execute(
            "INSERT INTO medawarcre.search_runs("
            "workspace_id,saved_search_id,requested_by_user_id,status) "
            "VALUES (%s,%s,%s,'succeeded') RETURNING id",
            (workspace_id, actor_search, actor_id),
        ).fetchone()[0]
        peer_run = connection.execute(
            "INSERT INTO medawarcre.search_runs("
            "workspace_id,saved_search_id,requested_by_user_id,status) "
            "VALUES (%s,%s,%s,'succeeded') RETURNING id",
            (workspace_id, peer_search, peer_id),
        ).fetchone()[0]
        for run_id, source_id in ((actor_run, "actor"), (peer_run, "peer")):
            connection.execute(
                "INSERT INTO medawarcre.search_results("
                "workspace_id,search_run_id,source,source_record_id,dedupe_key,"
                "listing,observed_at) VALUES (%s,%s,'fixture',%s,%s,'{}',"
                "statement_timestamp())",
                (workspace_id, run_id, source_id, source_id),
            )
        connection.execute(
            "INSERT INTO medawarcre.consents("
            "workspace_id,user_id,consent_type,granted,version) VALUES "
            "(%s,%s,'terms',true,'v1'),(%s,%s,'terms',true,'v1')",
            (workspace_id, actor_id, workspace_id, peer_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.privacy_requests(workspace_id,user_id,kind) "
            "VALUES (%s,%s,'access'),(%s,%s,'access')",
            (workspace_id, actor_id, workspace_id, peer_id),
        )
        shared_deal = connection.execute(
            "INSERT INTO medawarcre.deals("
            "workspace_id,source,source_record_id,title,stage,owner_user_id) "
            "VALUES (%s,'fixture','shared','Shared deal','lead',%s) RETURNING id",
            (workspace_id, peer_id),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO medawarcre.deal_notes("
            "workspace_id,deal_id,author_user_id,body) "
            "VALUES (%s,%s,%s,'Workspace-visible note')",
            (workspace_id, shared_deal, peer_id),
        )

    def app_connection() -> psycopg.Connection:
        connection = psycopg.connect(app_dsn)
        connection.execute(
            "SELECT set_config('app.workspace_id',%s,true),"
            "set_config('app.actor_user_id',%s,true)",
            (workspace_id, actor_id),
        )
        return connection

    with app_connection() as connection:
        assert connection.execute(
            "SELECT user_id::text FROM medawarcre.memberships"
        ).fetchall() == [(actor_id,)]
        assert connection.execute(
            "SELECT subject_user_id::text FROM medawarcre.access_grants "
            "ORDER BY subject_user_id NULLS FIRST"
        ).fetchall() == [(None,), (actor_id,)]
        assert connection.execute(
            "SELECT owner_user_id::text FROM medawarcre.saved_searches"
        ).fetchall() == [(actor_id,)]
        assert connection.execute(
            "SELECT id FROM medawarcre.search_runs"
        ).fetchall() == [(actor_run,)]
        assert connection.execute(
            "SELECT source_record_id FROM medawarcre.search_results"
        ).fetchall() == [("actor",)]
        assert connection.execute(
            "SELECT user_id::text FROM medawarcre.consents"
        ).fetchall() == [(actor_id,)]
        assert connection.execute(
            "SELECT user_id::text FROM medawarcre.privacy_requests"
        ).fetchall() == [(actor_id,)]
        assert connection.execute(
            "SELECT title FROM medawarcre.deals WHERE id=%s", (shared_deal,)
        ).fetchone() == ("Shared deal",)
        assert connection.execute(
            "SELECT body FROM medawarcre.deal_notes WHERE deal_id=%s", (shared_deal,)
        ).fetchone() == ("Workspace-visible note",)

    for private_column, table in (
        ("owner_user_id", "deals"),
        ("author_user_id", "deal_notes"),
    ):
        with app_connection() as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    sql.SQL("SELECT {} FROM medawarcre.{}").format(
                        sql.Identifier(private_column), sql.Identifier(table)
                    )
                )

    with app_connection() as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO medawarcre.deals("
                "workspace_id,source,source_record_id,title,stage,owner_user_id) "
                "VALUES (%s,'fixture','forged-owner','No','lead',%s)",
                (workspace_id, peer_id),
            )
    with app_connection() as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO medawarcre.deal_notes("
                "workspace_id,deal_id,author_user_id,body) "
                "VALUES (%s,%s,%s,'Forged author')",
                (workspace_id, shared_deal, peer_id),
            )


def test_admin_console_cannot_read_or_mutate_auth_and_provider_secrets(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        workspace_id, _, actor_id, _ = _seed_two_tenants(connection)
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.oauth_clients("
            "client_id,name,redirect_uris,scopes) "
            "VALUES ('phase2-client','Phase 2',ARRAY['https://example.test/cb'],"
            "ARRAY['read'])"
        )
        session_id = connection.execute(
            "INSERT INTO medawarcre.oauth_sessions("
            "workspace_id,user_id,client_id,scopes,audience,resource,"
            "authority_version,access_hash,refresh_hash,access_expires_at,"
            "refresh_expires_at,refresh_family_expires_at) VALUES "
            "(%s,%s,'phase2-client',ARRAY['read'],'api','mcp',1,%s,%s,"
            "statement_timestamp()+interval '5 minutes',"
            "statement_timestamp()+interval '1 day',"
            "statement_timestamp()+interval '30 days') RETURNING id",
            (workspace_id, actor_id, b"a" * 32, b"r" * 32),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO medawarcre.oauth_codes("
            "workspace_id,user_id,client_id,session_id,code_hash,redirect_uri,"
            "code_challenge,scopes,audience,resource,authority_version,expires_at) "
            "VALUES (%s,%s,'phase2-client',%s,%s,'https://example.test/cb',"
            "'challenge',ARRAY['read'],'api','mcp',1,"
            "statement_timestamp()+interval '5 minutes')",
            (workspace_id, actor_id, session_id, b"c" * 32),
        )
        connection.execute(
            "INSERT INTO medawarcre.oauth_refresh_history("
            "workspace_id,session_id,token_hash) VALUES (%s,%s,%s)",
            (workspace_id, session_id, b"h" * 32),
        )
        connection.execute(
            "INSERT INTO medawarcre.human_identities("
            "user_id,provider,subject_hash,subject_hint) "
            "VALUES (%s,'oidc',%s,'actor')",
            (actor_id, b"i" * 32),
        )
        connection.execute(
            "INSERT INTO medawarcre.subscriptions("
            "workspace_id,provider,external_subscription_hash,"
            "external_customer_hash,status,plan_key,last_event_at) "
            "VALUES (%s,'stripe',%s,%s,'active','founder',statement_timestamp())",
            (workspace_id, b"s" * 32, b"u" * 32),
        )
        connection.execute(
            "INSERT INTO medawarcre.access_grants("
            "workspace_id,subject_user_id,scope,source,external_ref_hash,profile,"
            "status,starts_at,ends_at) "
            "VALUES (%s,%s,'subject','stripe',%s,'full_operator','active',"
            "statement_timestamp(),statement_timestamp()+interval '1 day')",
            (workspace_id, actor_id, b"g" * 32),
        )
        external_account_id = connection.execute(
            "INSERT INTO medawarcre.external_accounts("
            "workspace_id,subject_user_id,provider,external_account_hash,metadata) "
            "VALUES (%s,%s,'stripe',%s,'{\"private\":true}') RETURNING id",
            (workspace_id, actor_id, b"e" * 32),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO medawarcre.provider_events("
            "workspace_id,external_account_id,provider,event_id_hash,"
            "canonical_action,outcome,external_account_hash,bound_subject_user_id,"
            "bound_scope,entitlement_input_hash,bound_plan_key,bound_profile,"
            "mapping_provenance,payload_fingerprint,event_projection,occurred_at) "
            "VALUES (%s,%s,'stripe',%s,'subscription.updated','applied',%s,%s,"
            "'subject',%s,'founder','full_operator','{\"mapper\":\"v1\"}',%s,"
            "'{\"private\":true}',statement_timestamp())",
            (
                workspace_id,
                external_account_id,
                b"v" * 32,
                b"e" * 32,
                actor_id,
                b"n" * 32,
                b"f" * 32,
            ),
        )
        client_id = connection.execute(
            "INSERT INTO medawarcre.connected_clients("
            "workspace_id,name,client_type) VALUES (%s,'Fixture','crm') RETURNING id",
            (workspace_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO medawarcre.integration_events("
            "workspace_id,client_id,event_type,event_projection) "
            "VALUES (%s,%s,'sync','{\"private\":true}')",
            (workspace_id, client_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.tool_approvals("
            "approval_token_hash,workspace_id,subject_user_id,session_hash,"
            "tool_name,args_hash,expires_at) VALUES (%s,%s,%s,%s,'find_deals',%s,"
            "statement_timestamp()+interval '5 minutes')",
            (b"t" * 32, workspace_id, actor_id, b"z" * 32, b"x" * 32),
        )

    admin_login_dsn = app_dsn.replace(
        "user=medawarcre_test_app", "user=medawarcre_test_admin"
    )
    private_reads = (
        "SELECT subject_hash FROM medawarcre.human_identities",
        "SELECT external_subscription_hash FROM medawarcre.subscriptions",
        "SELECT external_ref_hash FROM medawarcre.access_grants",
        "SELECT access_hash,refresh_hash FROM medawarcre.oauth_sessions",
        "SELECT code_hash,code_challenge FROM medawarcre.oauth_codes",
        "SELECT token_hash FROM medawarcre.oauth_refresh_history",
        "SELECT external_account_hash,metadata FROM medawarcre.external_accounts",
        "SELECT event_id_hash,mapping_provenance,event_projection "
        "FROM medawarcre.provider_events",
        "SELECT event_projection FROM medawarcre.integration_events",
        "SELECT approval_token_hash,session_hash,args_hash "
        "FROM medawarcre.tool_approvals",
    )
    for internal_role in (
        "owner",
        "admin",
        "jv_operations",
        "support",
        "security_audit",
        "read_only_analyst",
    ):
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.staff_roles SET role=%s WHERE user_id=%s",
                (internal_role, actor_id),
            )
        with psycopg.connect(admin_login_dsn) as connection:
            connection.execute(
                "SELECT set_config('app.internal_role',%s,true),"
                "set_config('app.actor_user_id',%s,true),"
                "set_config('app.audit_reason','safe console review',true)",
                (internal_role, actor_id),
            )
            assert connection.execute(
                "SELECT id,client_id,revoked_at FROM medawarcre.oauth_sessions"
            ).fetchall() == [(session_id, "phase2-client", None)]
            assert connection.execute(
                "SELECT provider,canonical_action,outcome "
                "FROM medawarcre.provider_events"
            ).fetchall() == [("stripe", "subscription.updated", "applied")]
            for statement in private_reads:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with connection.transaction():
                        connection.execute(statement)
            if internal_role in {"owner", "admin"}:
                for statement in (
                    "UPDATE medawarcre.oauth_sessions "
                    "SET refresh_hash=decode(repeat('00',32),'hex')",
                    "UPDATE medawarcre.provider_events "
                    "SET event_projection='{}'::jsonb",
                ):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        with connection.transaction():
                            connection.execute(statement)


def test_provider_receipts_aliases_and_jobs_preserve_launch_invariants(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        workspace_id, _, _, _ = _seed_two_tenants(connection)
        event_id = connection.execute(
            "INSERT INTO medawarcre.provider_events("
            "workspace_id,provider,event_id_hash,canonical_action,outcome,"
            "payload_fingerprint,occurred_at,mapping_provenance) "
            "VALUES (NULL,'stripe',%s,'unknown','unmapped',%s,"
            "statement_timestamp(),'{\"mapper\":\"unmapped-v1\"}'::jsonb) RETURNING id",
            (b"e" * 32, b"p" * 32),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO medawarcre.provider_event_attempts("
            "workspace_id,provider_event_id,outcome,reason_code) "
            "VALUES (NULL,%s,'unmapped','no_workspace_binding')",
            (event_id,),
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE medawarcre.provider_events "
                "SET mapping_provenance='{\"mapper\":\"rewritten\"}'::jsonb "
                "WHERE id=%s",
                (event_id,),
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO medawarcre.provider_event_attempts("
                "workspace_id,provider_event_id,outcome) "
                "VALUES (%s,%s,'applied')",
                (workspace_id, event_id),
            )
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                "INSERT INTO medawarcre.provider_events("
                "provider,event_id_hash,canonical_action,outcome,"
                "payload_fingerprint,occurred_at) "
                    "VALUES ('stripe',%s,'unknown','unmapped',%s,"
                "statement_timestamp())",
                (b"e" * 32, b"q" * 32),
            )

        alias_id = str(uuid4())
        connection.execute(
            "INSERT INTO medawarcre.legacy_id_aliases("
            "source_system,entity_type,legacy_id,canonical_id,workspace_id) "
            "VALUES ('sqlite','deal',41,%s,%s)",
            (alias_id, workspace_id),
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE medawarcre.legacy_id_aliases SET legacy_id=42 "
                "WHERE source_system='sqlite' AND entity_type='deal' AND legacy_id=41"
            )

        connection.execute(
            "INSERT INTO medawarcre.jobs("
            "workspace_id,kind,payload,status,idempotency_key,max_attempts) "
            "VALUES (%s,'saved_search','{}','queued','search:2026-08-01',3)",
            (workspace_id,),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                "INSERT INTO medawarcre.jobs("
                "workspace_id,kind,payload,status,idempotency_key,max_attempts) "
                "VALUES (%s,'saved_search','{}','queued','search:2026-08-01',3)",
                (workspace_id,),
            )
        with pytest.raises(psycopg.errors.NotNullViolation):
            connection.execute(
                "INSERT INTO medawarcre.jobs("
                "workspace_id,kind,payload,status,max_attempts) "
                "VALUES (%s,'provider_reconcile','{}','queued',3)",
                (workspace_id,),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO medawarcre.jobs("
                "workspace_id,kind,payload,status,idempotency_key,max_attempts) "
                "VALUES (%s,'retention','{}','queued','   ',3)",
                (workspace_id,),
            )

        provider_constraint = " ".join(
            str(row[0])
            for row in connection.execute(
                "SELECT pg_get_constraintdef(constraint_record.oid) "
                "FROM pg_catalog.pg_constraint constraint_record "
                "JOIN pg_catalog.pg_class relation "
                "ON relation.oid=constraint_record.conrelid "
                "JOIN pg_catalog.pg_namespace namespace "
                "ON namespace.oid=relation.relnamespace "
                "WHERE namespace.nspname='medawarcre' "
                "AND relation.relname='provider_events' "
                "AND constraint_record.contype='c'"
            )
        )
        for outcome in (
            "received",
            "applied",
            "duplicate",
            "stale",
            "quarantined",
            "rejected",
            "unmapped",
            "malformed",
            "failure",
            "reconciled",
        ):
            assert outcome in provider_constraint
