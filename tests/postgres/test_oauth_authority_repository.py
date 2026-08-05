from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.access.profiles import Profile
from cre_mcp.platform.auth import AUTHORITY_VERSION
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.migrations import MigrationRunner, load_migrations
from cre_mcp.postgres.oauth_authority import (
    OAuthAuthorityUnavailable,
    PostgresOAuthAuthorityRepository,
)
from cre_mcp.postgres.schema import (
    EXPECTED_MIGRATION_VERSION,
    EXPECTED_RLS_TABLES,
    EXPECTED_TABLES,
)


LIFECYCLE_TABLES = {
    "browser_sessions",
    "operator_sessions",
    "oauth_authorization_requests",
    "skool_join_tasks",
    "skool_reconciliations",
}


def _service_dsn(app_dsn: str, service: str) -> str:
    return app_dsn.replace(
        "user=medawarcre_test_app", f"user=medawarcre_test_{service}"
    )


def _seed_authority(
    admin_dsn: str,
    *,
    token: str = "mcre_access_authority_fixture",
) -> dict[str, str]:
    now = datetime.now(UTC)
    identifiers = {
        "workspace_id": str(uuid4()),
        "workspace_public_id": f"ws_{uuid4().hex}",
        "user_id": str(uuid4()),
        "membership_id": str(uuid4()),
        "plan_id": str(uuid4()),
        "grant_id": str(uuid4()),
        "session_id": str(uuid4()),
        "token": token,
    }
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) "
            "VALUES (%s,%s,'Authority User','active')",
            (identifiers["user_id"], f"{uuid4().hex}@example.test"),
        )
        connection.execute(
            "INSERT INTO medawarcre.plans(id,plan_key,name,daily_quotas,active) "
            "VALUES (%s,'operator','Operator',%s::jsonb,true)",
            (identifiers["plan_id"], '{"find_deals":25,"underwrite":4}'),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces"
            "(id,public_id,name,plan_id,state) VALUES (%s,%s,'Authority Workspace',%s,'active')",
            (
                identifiers["workspace_id"],
                identifiers["workspace_public_id"],
                identifiers["plan_id"],
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships"
            "(id,workspace_id,user_id,role,state) VALUES (%s,%s,%s,'owner','active')",
            (
                identifiers["membership_id"],
                identifiers["workspace_id"],
                identifiers["user_id"],
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspace_accounts(workspace_id,state) "
            "VALUES (%s,'active')",
            (identifiers["workspace_id"],),
        )
        connection.execute(
            "INSERT INTO medawarcre.access_grants"
            "(id,workspace_id,subject_user_id,scope,source,external_ref_hash,"
            "profile,plan_key,status,starts_at,ends_at) "
            "VALUES (%s,%s,%s,'subject','manual',%s,'full_operator','operator',"
            "'active',%s,%s)",
            (
                identifiers["grant_id"],
                identifiers["workspace_id"],
                identifiers["user_id"],
                hashlib.sha256(uuid4().bytes).digest(),
                now - timedelta(minutes=5),
                now + timedelta(days=7),
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.territories"
            "(workspace_id,name,state_code) VALUES (%s,'California','CA')",
            (identifiers["workspace_id"],),
        )
        connection.execute(
            "INSERT INTO medawarcre.staff_roles(user_id,role,active) "
            "VALUES (%s,'admin',true)",
            (identifiers["user_id"],),
        )
        connection.execute(
            "INSERT INTO medawarcre.oauth_clients"
            "(client_id,name,redirect_uris,scopes,active) "
            "VALUES ('test-client','Test Client',ARRAY['https://client.example/callback'],"
            "ARRAY['mcp:tools'],true)",
        )
        connection.execute(
            "INSERT INTO medawarcre.oauth_sessions"
            "(id,workspace_id,user_id,client_id,scopes,audience,resource,authority_version,"
            "access_hash,refresh_hash,access_expires_at,refresh_expires_at,"
            "refresh_family_expires_at) VALUES (%s,%s,%s,'test-client',ARRAY['mcp:tools'],"
            "'medawarcre-mcp','https://mcp.medawarcre.com/mcp',1,%s,%s,%s,%s,%s)",
            (
                identifiers["session_id"],
                identifiers["workspace_id"],
                identifiers["user_id"],
                hashlib.sha256(token.encode("utf-8")).digest(),
                hashlib.sha256(uuid4().bytes).digest(),
                now + timedelta(minutes=15),
                now + timedelta(days=14),
                now + timedelta(days=30),
            ),
        )
    return identifiers


def _repository(oauth_dsn: str) -> PostgresOAuthAuthorityRepository:
    repository = PostgresOAuthAuthorityRepository(
        PostgresSettings(
            dsn=oauth_dsn,
            min_size=1,
            max_size=2,
            application_name="medawarcre-oauth-test",
        )
    )
    repository.open(wait=True)
    return repository


def test_migration_0002_inventory_is_explicit() -> None:
    migrations = load_migrations()
    assert [migration.version for migration in migrations] == [1, 2, 3, 4, 5, 6]
    assert migrations[1].name == "hosted lifecycle and oauth authority"
    assert EXPECTED_MIGRATION_VERSION == 6
    assert LIFECYCLE_TABLES <= EXPECTED_TABLES
    assert LIFECYCLE_TABLES <= EXPECTED_RLS_TABLES
    assert "state text NOT NULL" in migrations[1].sql
    assert "state_hash bytea" not in migrations[1].sql
    assert "browser_sessions_one_live_per_user" in migrations[1].sql
    assert "access_grants_source_valid" in migrations[1].sql
    assert "access_grants_source_scope_valid" in migrations[1].sql
    assert "access_grants_provider_lease_required" in migrations[1].sql
    assert (
        f"oauth_session.authority_version = {AUTHORITY_VERSION}"
        in migrations[1].sql
    )


def test_lifecycle_tables_are_owned_rls_enabled_and_cross_tenant_safe(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        rows = connection.execute(
            "SELECT relation.relname,owner.rolname,relation.relrowsecurity,"
            "relation.relforcerowsecurity FROM pg_catalog.pg_class relation "
            "JOIN pg_catalog.pg_namespace namespace ON namespace.oid=relation.relnamespace "
            "JOIN pg_catalog.pg_roles owner ON owner.oid=relation.relowner "
            "WHERE namespace.nspname='medawarcre' AND relation.relname=ANY(%s) "
            "ORDER BY relation.relname",
            (sorted(LIFECYCLE_TABLES),),
        ).fetchall()
        assert rows == [
            (table, "medawarcre_migration", True, False)
            for table in sorted(LIFECYCLE_TABLES)
        ]


def test_skool_audit_actors_can_be_global_staff_without_tenant_membership(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    workspace_id = str(uuid4())
    subject_user_id = str(uuid4())
    actor_user_id = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name) VALUES "
            "(%s,%s,'Subject'),(%s,%s,'Platform Admin')",
            (
                subject_user_id,
                f"{uuid4().hex}@example.test",
                actor_user_id,
                f"{uuid4().hex}@example.test",
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.staff_roles(user_id,role,active) "
            "VALUES (%s,'admin',true)",
            (actor_user_id,),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name) "
            "VALUES (%s,%s,'Lifecycle Workspace')",
            (workspace_id, f"ws_{uuid4().hex}"),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'member','active')",
            (workspace_id, subject_user_id),
        )
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.memberships "
            "WHERE workspace_id=%s AND user_id=%s",
            (workspace_id, actor_user_id),
        ).fetchone() == (0,)
        connection.execute(
            "INSERT INTO medawarcre.skool_join_tasks("
            "workspace_id,subject_user_id,community_id,level_id,state,"
            "requested_by,completed_by,completion_source,completed_at) "
            "VALUES (%s,%s,'community','level','completed',%s,%s,"
            "'manual_admin_invite',statement_timestamp())",
            (workspace_id, subject_user_id, actor_user_id, actor_user_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.skool_reconciliations("
            "workspace_id,community_id,artifact_hash,source,observed_at,"
            "confidence,complete,certainty,reason_code,member_count,"
            "mapped_member_count,discrepancy_count,conflict_count,created_by) "
            "VALUES (%s,'community',%s,'operator_members_review',"
            "statement_timestamp(),'confirmed',true,'confirmed','matched',"
            "1,1,0,0,%s)",
            (workspace_id, hashlib.sha256(uuid4().bytes).digest(), actor_user_id),
        )

        nonmember_subject_id = str(uuid4())
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name) VALUES (%s,%s,'Nonmember')",
            (nonmember_subject_id, f"{uuid4().hex}@example.test"),
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO medawarcre.skool_join_tasks("
                "workspace_id,subject_user_id,community_id,level_id,"
                "requested_by) VALUES (%s,%s,'community','level',%s)",
                (workspace_id, nonmember_subject_id, actor_user_id),
            )


def test_oauth_role_has_only_schema_usage_and_authority_function(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    oauth_dsn = _service_dsn(app_dsn, "oauth")
    with psycopg.connect(oauth_dsn) as connection:
        connection.execute("SET ROLE medawarcre_oauth")
        assert connection.execute(
            "SELECT has_schema_privilege(current_user,'medawarcre','USAGE'),"
            "has_schema_privilege(current_user,'medawarcre','CREATE'),"
            "has_function_privilege(current_user,"
            "'medawarcre.resolve_oauth_authority(bytea,text,text)','EXECUTE')"
        ).fetchone() == (True, False, True)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT count(*) FROM medawarcre.oauth_sessions")
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT NOT EXISTS ("
            "SELECT 1 FROM pg_catalog.pg_proc procedure "
            "JOIN pg_catalog.pg_namespace namespace ON namespace.oid=procedure.pronamespace "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(procedure.proacl) acl "
            "WHERE namespace.nspname='medawarcre' "
            "AND procedure.proname='resolve_oauth_authority' "
            "AND acl.grantee=0 AND acl.privilege_type='EXECUTE')"
        ).fetchone() == (True,)
        for role in (
            "medawarcre_provider_ingress",
            "medawarcre_provider_reconcile",
            "medawarcre_worker",
            "medawarcre_scheduler",
        ):
            assert connection.execute(
                "SELECT has_schema_privilege(%s,'medawarcre','USAGE'),"
                "has_function_privilege(%s,"
                "'medawarcre.resolve_oauth_authority(bytea,text,text)','EXECUTE')",
                (role, role),
            ).fetchone() == (False, False)


def test_repository_resolves_one_live_authority_snapshot(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    fixture = _seed_authority(admin_dsn)
    repository = _repository(_service_dsn(app_dsn, "oauth"))
    try:
        outcome = repository.resolve(fixture["token"])
        assert outcome is not None
        assert outcome.reason is None
        assert outcome.access_allowed
        assert outcome.session.user_id == fixture["user_id"]
        assert outcome.session.session_id == fixture["session_id"]
        assert outcome.session.workspace_id == fixture["workspace_public_id"]
        assert outcome.context is not None
        assert outcome.context.workspace_id == fixture["workspace_public_id"]
        assert outcome.context.profile is Profile.FULL_OPERATOR
        assert outcome.context.plan == "operator"
        assert outcome.context.quota_limits == {"find_deals": 25, "underwrite": 4}
        assert outcome.context.territories == ("CA",)
        assert outcome.internal_admin is not None
        assert outcome.internal_admin.role == "platform_admin"
        assert not outcome.jv_grant_present

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.workspace_accounts SET state='suspended' "
                "WHERE workspace_id=%s",
                (fixture["workspace_id"],),
            )
        disabled = repository.resolve(fixture["token"])
        assert disabled is not None
        assert disabled.reason == "account_suspended"
        assert disabled.context is None

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.oauth_sessions SET revoked_at=statement_timestamp() "
                "WHERE id=%s",
                (fixture["session_id"],),
            )
        assert repository.resolve(fixture["token"]) is None
    finally:
        repository.close()


def test_repository_rejects_wrong_target_and_obsolete_authority_version(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    fixture = _seed_authority(admin_dsn)
    oauth_dsn = _service_dsn(app_dsn, "oauth")

    wrong_audience = PostgresOAuthAuthorityRepository(
        PostgresSettings(dsn=oauth_dsn, min_size=0, max_size=1),
        audience="wrong-audience",
    )
    wrong_resource = PostgresOAuthAuthorityRepository(
        PostgresSettings(dsn=oauth_dsn, min_size=0, max_size=1),
        resource="https://wrong.example/mcp",
    )
    repository = _repository(oauth_dsn)
    try:
        wrong_audience.open(wait=True)
        wrong_resource.open(wait=True)
        assert wrong_audience.resolve(fixture["token"]) is None
        assert wrong_resource.resolve(fixture["token"]) is None

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.oauth_sessions SET authority_version=%s "
                "WHERE id=%s",
                (AUTHORITY_VERSION + 1, fixture["session_id"]),
            )
        assert repository.resolve(fixture["token"]) is None
    finally:
        repository.close()
        wrong_audience.close()
        wrong_resource.close()


def test_repository_survives_restart_and_pins_pool_search_path(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    fixture = _seed_authority(admin_dsn)
    oauth_dsn = (
        _service_dsn(app_dsn, "oauth")
        + " options='-c search_path=public,pg_catalog'"
    )

    repository = _repository(oauth_dsn)
    try:
        assert repository.resolve(fixture["token"]) is not None
        with repository._pool.connection() as connection:
            assert connection.execute("SHOW search_path").fetchone() == (
                "pg_catalog",
            )
            assert connection.execute(
                "SELECT current_user=session_user"
            ).fetchone() == (True,)
    finally:
        repository.close()

    restarted = _repository(oauth_dsn)
    try:
        outcome = restarted.resolve(fixture["token"])
        assert outcome is not None
        assert outcome.context is not None
        assert outcome.context.workspace_id == fixture["workspace_public_id"]
    finally:
        restarted.close()


def test_repository_fails_closed_on_live_service_role_acl_drift(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    fixture = _seed_authority(admin_dsn)
    repository = _repository(_service_dsn(app_dsn, "oauth"))
    try:
        assert repository.resolve(fixture["token"]) is not None
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "GRANT SELECT ON medawarcre.oauth_sessions TO medawarcre_oauth"
            )
        with pytest.raises(OAuthAuthorityUnavailable, match="authority contract"):
            repository.resolve(fixture["token"])
    finally:
        repository.close()


def test_repository_fails_closed_on_service_role_default_acl_drift(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    fixture = _seed_authority(admin_dsn)
    repository = _repository(_service_dsn(app_dsn, "oauth"))
    try:
        assert repository.resolve(fixture["token"]) is not None
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "ALTER DEFAULT PRIVILEGES FOR ROLE medawarcre_migration "
                "IN SCHEMA medawarcre GRANT EXECUTE ON FUNCTIONS "
                "TO medawarcre_oauth"
            )
        with pytest.raises(OAuthAuthorityUnavailable, match="authority contract"):
            repository.resolve(fixture["token"])
    finally:
        repository.close()


def test_repository_reflects_live_authority_changes_on_the_next_call(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    fixture = _seed_authority(admin_dsn)
    repository = _repository(_service_dsn(app_dsn, "oauth"))
    try:
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.memberships SET state='suspended' "
                "WHERE id=%s",
                (fixture["membership_id"],),
            )
        suspended = repository.resolve(fixture["token"])
        assert suspended is not None
        assert suspended.reason == "membership_suspended"
        assert suspended.context is None

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.memberships SET state='active' WHERE id=%s",
                (fixture["membership_id"],),
            )
            connection.execute(
                "UPDATE medawarcre.access_grants "
                "SET profile='local_scout',updated_at=statement_timestamp() "
                "WHERE id=%s",
                (fixture["grant_id"],),
            )
            connection.execute(
                "UPDATE medawarcre.plans "
                "SET daily_quotas=%s::jsonb,updated_at=statement_timestamp() "
                "WHERE id=%s",
                ('{"find_deals":7}', fixture["plan_id"]),
            )
            connection.execute(
                "UPDATE medawarcre.territories "
                "SET state_code=NULL,market='  Dallas-Fort Worth  ' "
                "WHERE workspace_id=%s",
                (fixture["workspace_id"],),
            )
            connection.execute(
                "INSERT INTO medawarcre.territories"
                "(workspace_id,name,market) "
                "VALUES (%s,'Duplicate Market','Dallas-Fort Worth')",
                (fixture["workspace_id"],),
            )
            connection.execute(
                "UPDATE medawarcre.staff_roles SET active=false "
                "WHERE user_id=%s",
                (fixture["user_id"],),
            )
        changed = repository.resolve(fixture["token"])
        assert changed is not None
        assert changed.reason is None
        assert changed.context is not None
        assert changed.context.profile is Profile.LOCAL_SCOUT
        assert changed.context.quota_limits == {"find_deals": 7}
        assert changed.context.territories == ("Dallas-Fort Worth",)
        assert changed.internal_admin is None

        jv_workspace_id = str(uuid4())
        jv_membership_id = str(uuid4())
        jv_grant_id = str(uuid4())
        now = datetime.now(UTC)
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "INSERT INTO medawarcre.workspaces"
                "(id,public_id,name,plan_id,state) "
                "VALUES (%s,%s,'JV Workspace',%s,'active')",
                (jv_workspace_id, f"ws_{uuid4().hex}", fixture["plan_id"]),
            )
            connection.execute(
                "INSERT INTO medawarcre.memberships"
                "(id,workspace_id,user_id,role,state) "
                "VALUES (%s,%s,%s,'jv_partner','active')",
                (jv_membership_id, jv_workspace_id, fixture["user_id"]),
            )
            connection.execute(
                "INSERT INTO medawarcre.access_grants"
                "(id,workspace_id,subject_user_id,scope,source,"
                "external_ref_hash,profile,plan_key,status,starts_at,ends_at) "
                "VALUES (%s,%s,%s,'subject','jv',%s,'jv_partner','operator',"
                "'active',%s,%s)",
                (
                    jv_grant_id,
                    jv_workspace_id,
                    fixture["user_id"],
                    hashlib.sha256(uuid4().bytes).digest(),
                    now - timedelta(minutes=5),
                    now + timedelta(days=7),
                ),
            )
        jv_enabled = repository.resolve(fixture["token"])
        assert jv_enabled is not None
        assert jv_enabled.jv_grant_present

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.access_grants SET status='revoked' "
                "WHERE id=%s",
                (jv_grant_id,),
            )
            connection.execute(
                "UPDATE medawarcre.plans SET active=false WHERE id=%s",
                (fixture["plan_id"],),
            )
        invalid_plan = repository.resolve(fixture["token"])
        assert invalid_plan is not None
        assert invalid_plan.reason == "plan_missing_or_invalid"
        assert not invalid_plan.jv_grant_present
    finally:
        repository.close()


@pytest.mark.parametrize(
    "workspace_state",
    ("suspended", "deletion_pending", "deleted"),
)
def test_repository_denies_terminal_workspace_state_on_the_next_call(
    postgres_database: tuple[str, str, str],
    workspace_state: str,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    fixture = _seed_authority(admin_dsn)
    repository = _repository(_service_dsn(app_dsn, "oauth"))
    try:
        initial = repository.resolve(fixture["token"])
        assert initial is not None
        assert initial.access_allowed

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.workspaces SET state=%s WHERE id=%s",
                (workspace_state, fixture["workspace_id"]),
            )
        denied = repository.resolve(fixture["token"])
        assert denied is not None
        assert denied.reason == f"workspace_{workspace_state}"
        assert denied.context is None
        assert not denied.access_allowed
    finally:
        repository.close()


@pytest.mark.parametrize(
    ("source", "scope", "subject", "leased"),
    (
        ("forged", "subject", True, True),
        ("manual", "workspace", False, True),
        ("stripe", "workspace", False, False),
        ("skool", "subject", True, False),
    ),
)
def test_migration_rejects_structurally_invalid_access_grants(
    postgres_database: tuple[str, str, str],
    source: str,
    scope: str,
    subject: bool,
    leased: bool,
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    fixture = _seed_authority(admin_dsn)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO medawarcre.access_grants("
                "workspace_id,subject_user_id,scope,source,external_ref_hash,"
                "profile,plan_key,status,starts_at,ends_at) "
                "VALUES (%s,%s,%s,%s,%s,'full_operator','operator','active',"
                "statement_timestamp(),"
                "CASE WHEN %s THEN statement_timestamp()+interval '1 day' END)",
                (
                    fixture["workspace_id"],
                    fixture["user_id"] if subject else None,
                    scope,
                    source,
                    hashlib.sha256(uuid4().bytes).digest(),
                    leased,
                ),
            )


def test_resolver_ignores_malformed_provider_grant_under_catalog_drift(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    fixture = _seed_authority(admin_dsn)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "UPDATE medawarcre.access_grants SET status='revoked' WHERE id=%s",
            (fixture["grant_id"],),
        )
        connection.execute(
            "ALTER TABLE medawarcre.access_grants "
            "DROP CONSTRAINT access_grants_source_scope_valid, "
            "DROP CONSTRAINT access_grants_provider_lease_required"
        )
        connection.execute(
            "INSERT INTO medawarcre.access_grants("
            "workspace_id,scope,source,external_ref_hash,profile,plan_key,status,"
            "starts_at) VALUES (%s,'workspace','stripe',%s,'jv_partner',"
            "'operator','active',statement_timestamp())",
            (
                fixture["workspace_id"],
                hashlib.sha256(uuid4().bytes).digest(),
            ),
        )

    repository = _repository(_service_dsn(app_dsn, "oauth"))
    try:
        outcome = repository.resolve(fixture["token"])
        assert outcome is not None
        assert outcome.reason == "entitlement_missing_or_expired"
        assert outcome.context is None
        assert not outcome.access_allowed
        assert not outcome.jv_grant_present
    finally:
        repository.close()


def test_repository_rejects_wrong_service_login_before_query(
    postgres_database: tuple[str, str, str],
) -> None:
    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    repository = PostgresOAuthAuthorityRepository(
        PostgresSettings(
            dsn=_service_dsn(app_dsn, "worker"),
            min_size=0,
            max_size=1,
        )
    )
    try:
        with pytest.raises(OAuthAuthorityUnavailable, match="authority contract"):
            repository.open(wait=True)
    finally:
        repository.close()


def test_repository_uses_distinct_redacted_environment_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "MEDAWARCRE_OAUTH_DATABASE_URL",
        "postgresql://oauth:never-print-this@database.invalid/medawarcre",
    )
    repository = PostgresOAuthAuthorityRepository.from_env()
    rendered = repr(repository)
    assert "never-print-this" not in rendered
    assert "database.invalid" not in rendered
    assert "MEDAWARCRE_OAUTH_DATABASE_URL" not in rendered
