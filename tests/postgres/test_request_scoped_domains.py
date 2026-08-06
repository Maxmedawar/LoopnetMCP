from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.deals.store import DealStore, get_deal_store
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.domains import (
    AdmittedRequestUnavailable,
    HostedRequestRepositories,
    current_hosted_request_repositories,
    use_hosted_request_repositories,
)
from cre_mcp.postgres.migrations import MigrationRunner
from cre_mcp.postgres.pool import PostgresDatabase


def _admission(
    *,
    workspace_public_id: str = "ws_domain_a",
    actor_user_id: str | None = None,
    decision: str = "allowed",
    replayed: bool = False,
    finalized: bool = False,
) -> AdmissionOutcome:
    return AdmissionOutcome(
        invocation_id=str(uuid4()),
        request_correlation_id=str(uuid4()),
        workspace_public_id=workspace_public_id,
        actor_user_id=actor_user_id or str(uuid4()),
        session_id=str(uuid4()),
        tool_name="save_deal",
        decision=decision,
        reason_code=(
            "authority_admitted" if decision == "allowed" else "authority_missing"
        ),
        safe_reason=(
            "request admitted by live authority"
            if decision == "allowed"
            else "access denied"
        ),
        replayed=replayed,
        finalized=finalized,
    )


def _repositories(admission: AdmissionOutcome, marker: object | None = None):
    repository = marker or object()
    return HostedRequestRepositories(
        admission=admission,
        platform=repository,
        provider=repository,
        search=repository,
        deal=repository,
        privacy=repository,
        job=repository,
        document=repository,
        truth_asset=repository,
    )


def test_hosted_request_repositories_require_one_fresh_allowed_admission() -> None:
    admission = _admission()
    assert _repositories(admission).admission is admission

    for invalid in (
        replace(admission, decision="denied"),
        replace(admission, replayed=True),
        replace(admission, finalized=True),
        replace(admission, invocation_id="not-a-uuid"),
    ):
        with pytest.raises(AdmittedRequestUnavailable):
            _repositories(invalid)

    values = _repositories(admission).__dict__
    for field in (
        "platform",
        "provider",
        "search",
        "deal",
        "privacy",
        "job",
        "document",
        "truth_asset",
    ):
        with pytest.raises(AdmittedRequestUnavailable):
            HostedRequestRepositories(**{**values, field: None})


def test_hosted_repository_scope_is_exact_nested_and_reset() -> None:
    first = _repositories(_admission())
    second = _repositories(_admission(workspace_public_id="ws_domain_b"))
    assert current_hosted_request_repositories() is None
    with use_hosted_request_repositories(first):
        assert current_hosted_request_repositories() is first
        with use_hosted_request_repositories(second):
            assert current_hosted_request_repositories() is second
        assert current_hosted_request_repositories() is first
    assert current_hosted_request_repositories() is None


@pytest.mark.asyncio
async def test_detached_task_cannot_retain_repository_scope_after_owner_exits() -> None:
    repositories = _repositories(_admission())
    child_started = asyncio.Event()
    inspect_scope = asyncio.Event()

    async def detached_child():
        child_started.set()
        await inspect_scope.wait()
        return current_hosted_request_repositories()

    with use_hosted_request_repositories(repositories):
        task = asyncio.create_task(detached_child())
        await child_started.wait()
        assert current_hosted_request_repositories() is repositories

    assert current_hosted_request_repositories() is None
    inspect_scope.set()
    assert await task is None


def test_deal_store_factory_uses_injected_hosted_repository_and_blocks_local_store(
    tmp_path,
) -> None:
    admission = _admission()
    hosted_deal_repository = object()
    repositories = _repositories(admission, hosted_deal_repository)

    local = get_deal_store()
    assert isinstance(local, DealStore)
    with use_hosted_request_repositories(repositories):
        assert get_deal_store() is hosted_deal_repository
        with pytest.raises(AdmittedRequestUnavailable):
            DealStore(tmp_path / "forbidden-hosted.db")
    assert not (tmp_path / "forbidden-hosted.db").exists()


def _seed_bound_request(
    admin_dsn: str,
    admission: AdmissionOutcome,
) -> tuple[str, str]:
    workspace_id = str(uuid4())
    other_workspace_id = str(uuid4())
    other_actor_id = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) VALUES "
            "(%s,'domain-a@example.test','Domain A','active'),"
            "(%s,'domain-b@example.test','Domain B','active')",
            (admission.actor_user_id, other_actor_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) VALUES "
            "(%s,%s,'Domain A','active'),"
            "(%s,'ws_domain_b','Domain B','active')",
            (workspace_id, admission.workspace_public_id, other_workspace_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'owner','active'),(%s,%s,'owner','active')",
            (
                workspace_id,
                admission.actor_user_id,
                other_workspace_id,
                other_actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.deals("
            "workspace_id,source,source_record_id,title,listing,stage) VALUES "
            "(%s,'test','a','Visible',%s::jsonb,'lead'),"
            "(%s,'test','b','Hidden',%s::jsonb,'lead')",
            (
                workspace_id,
                '{"source":"test","source_id":"a","name":"Visible"}',
                other_workspace_id,
                '{"source":"test","source_id":"b","name":"Hidden"}',
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.access_decision_audit("
            "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
            "session_correlation_hash,request_correlation_id,tool_name,decision,"
            "reason_code,safe_reason,args_hash,admission_binding_hash) VALUES ("
            "%s,'admission',true,%s,%s,"
            "pg_catalog.sha256(pg_catalog.convert_to(%s,'UTF8')),%s,%s,'allowed',"
            "'authority_admitted','request admitted by live authority',"
            "decode(repeat('11',32),'hex'),decode(repeat('22',32),'hex'))",
            (
                admission.invocation_id,
                workspace_id,
                admission.actor_user_id,
                admission.session_id,
                admission.request_correlation_id,
                admission.tool_name,
            ),
        )
    return workspace_id, other_workspace_id


def test_admitted_connection_derives_rls_only_from_exact_unfinalized_admission(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    workspace_id, _ = _seed_bound_request(admin_dsn, admission)
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=2, runtime_mode="app")
    )
    database.open()
    try:
        with database.admitted_connection(admission) as connection:
            assert connection.execute(
                "SELECT current_setting('app.workspace_id'),"
                "current_setting('app.actor_user_id')"
            ).fetchone() == (workspace_id, admission.actor_user_id)
            assert connection.execute(
                "SELECT listing->>'name' FROM medawarcre.deals "
                "ORDER BY listing->>'name'"
            ).fetchall() == [("Visible",)]

        for invalid in (
            replace(admission, request_correlation_id=str(uuid4())),
            replace(admission, workspace_public_id="ws_domain_b"),
            replace(admission, actor_user_id=str(uuid4())),
            replace(admission, session_id=str(uuid4())),
            replace(admission, tool_name="list_deals"),
            replace(admission, replayed=True),
            replace(admission, finalized=True),
        ):
            with pytest.raises(AdmittedRequestUnavailable):
                with database.admitted_connection(invalid):
                    pass

        with psycopg.connect(admin_dsn) as connection:
            connection.execute(
                "INSERT INTO medawarcre.access_decision_audit("
                "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
                "session_correlation_hash,request_correlation_id,tool_name,decision,"
                "reason_code,safe_reason) SELECT "
                "invocation_id,'final',authenticated,workspace_id,actor_user_id,"
                "session_correlation_hash,request_correlation_id,tool_name,'succeeded',"
                "'tool_completed','request completed' "
                "FROM medawarcre.access_decision_audit "
                "WHERE invocation_id=%s AND phase='admission'",
                (admission.invocation_id,),
            )
        with pytest.raises(AdmittedRequestUnavailable):
            with database.admitted_connection(admission):
                pass
    finally:
        database.close()


def test_finalization_cannot_commit_while_admitted_transaction_is_active(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_bound_request(admin_dsn, admission)
    admission_dsn = app_dsn.replace(
        "user=medawarcre_test_app",
        "user=medawarcre_test_admission",
    )
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=1, runtime_mode="app")
    )
    database.open()
    final_query = (
        "SELECT medawarcre.record_tool_call_final("
        "%s,%s,%s,%s,%s,%s,true,'tool_completed','request completed')"
    )
    parameters = (
        admission.invocation_id,
        admission.request_correlation_id,
        admission.workspace_public_id,
        admission.actor_user_id,
        admission.session_id,
        admission.tool_name,
    )
    try:
        with database.admitted_connection(admission):
            with psycopg.connect(admission_dsn) as connection:
                connection.execute("SET LOCAL ROLE medawarcre_admission")
                connection.execute("SET LOCAL lock_timeout='250ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    connection.execute(final_query, parameters).fetchone()

        with psycopg.connect(admission_dsn) as connection:
            connection.execute("SET LOCAL ROLE medawarcre_admission")
            assert connection.execute(final_query, parameters).fetchone()[0] is not None
    finally:
        database.close()


def test_binding_waiting_on_finalization_rechecks_the_committed_final_row(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission = _admission()
    _seed_bound_request(admin_dsn, admission)
    admission_dsn = app_dsn.replace(
        "user=medawarcre_test_app",
        "user=medawarcre_test_admission",
    )
    database = PostgresDatabase(
        PostgresSettings(
            dsn=app_dsn,
            min_size=1,
            max_size=1,
            runtime_mode="app",
            application_name="phase5-bind-after-final",
        )
    )
    database.open()
    final_connection = psycopg.connect(admission_dsn)
    try:
        final_connection.execute("SET LOCAL ROLE medawarcre_admission")
        final_id = final_connection.execute(
            "SELECT medawarcre.record_tool_call_final("
            "%s,%s,%s,%s,%s,%s,true,'tool_completed','request completed')",
            (
                admission.invocation_id,
                admission.request_correlation_id,
                admission.workspace_public_id,
                admission.actor_user_id,
                admission.session_id,
                admission.tool_name,
            ),
        ).fetchone()[0]
        assert final_id is not None

        def attempt_binding() -> bool:
            with database.admitted_connection(admission):
                return True

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(attempt_binding)
            deadline = time.monotonic() + 3
            waiting = False
            with psycopg.connect(admin_dsn, autocommit=True) as observer:
                while time.monotonic() < deadline:
                    waiting = bool(
                        observer.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_stat_activity "
                            "WHERE application_name='phase5-bind-after-final' "
                            "AND wait_event_type='Lock')"
                        ).fetchone()[0]
                    )
                    if waiting:
                        break
                    time.sleep(0.01)
            assert waiting
            final_connection.commit()
            with pytest.raises(AdmittedRequestUnavailable):
                future.result(timeout=3)
    finally:
        final_connection.close()
        database.close()


def test_domain_binding_function_has_only_the_reviewed_app_grant(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn).apply()
    identity = (
        "medawarcre.bind_admitted_request("
        "uuid,uuid,text,uuid,uuid,text)"
    )
    with psycopg.connect(admin_dsn) as connection:
        grants = connection.execute(
            "SELECT grantee.rolname FROM pg_catalog.pg_proc function "
            "JOIN pg_catalog.pg_namespace namespace "
            "ON namespace.oid=function.pronamespace "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(function.proacl) acl "
            "JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee "
            "WHERE function.oid=pg_catalog.to_regprocedure(%s) "
            "AND acl.privilege_type='EXECUTE' ORDER BY grantee.rolname",
            (identity,),
        ).fetchall()
    assert grants == [("medawarcre_app",), ("medawarcre_migration",)]
