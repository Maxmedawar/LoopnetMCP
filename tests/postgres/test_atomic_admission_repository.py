from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.access.arguments import (
    CanonicalArgumentsError,
    canonical_argument_bytes,
    canonical_argument_hash,
)
from cre_mcp.access.context import TenantContext
from cre_mcp.access.profiles import Profile
from cre_mcp.access.quota import is_canonical_quota_bucket
from cre_mcp.postgres.admission import (
    AdmissionUnavailable,
    PostgresAdmissionRepository,
)
from cre_mcp.postgres.authority import ADMISSION_FUNCTIONS
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.migrations import MigrationRunner, load_migrations
from cre_mcp.postgres.oauth_authority import _quotas
from cre_mcp.postgres.schema import EXPECTED_MIGRATION_VERSION


def _admission_dsn(app_dsn: str) -> str:
    return app_dsn.replace(
        "user=medawarcre_test_app", "user=medawarcre_test_admission"
    )


def _seed_authority(
    admin_dsn: str,
    *,
    quotas: str = '{"search":2}',
) -> tuple[dict[str, str], TenantContext]:
    now = datetime.now(UTC)
    ids = {
        "workspace_id": str(uuid4()),
        "workspace_public_id": f"ws_{uuid4().hex}",
        "user_id": str(uuid4()),
        "membership_id": str(uuid4()),
        "grant_id": str(uuid4()),
        "session_id": str(uuid4()),
        "plan_key": f"plan_{uuid4().hex}",
    }
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) "
            "VALUES (%s,%s,'Admission User','active')",
            (ids["user_id"], f"{uuid4().hex}@example.test"),
        )
        plan_id = connection.execute(
            "INSERT INTO medawarcre.plans(plan_key,name,daily_quotas,active) "
            "VALUES (%s,'Admission Plan',%s::jsonb,true) RETURNING id",
            (ids["plan_key"], quotas),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,plan_id,state) "
            "VALUES (%s,%s,'Admission Workspace',%s,'active')",
            (ids["workspace_id"], ids["workspace_public_id"], plan_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships"
            "(id,workspace_id,user_id,role,state) "
            "VALUES (%s,%s,%s,'owner','active')",
            (ids["membership_id"], ids["workspace_id"], ids["user_id"]),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspace_accounts(workspace_id,state) "
            "VALUES (%s,'active')",
            (ids["workspace_id"],),
        )
        connection.execute(
            "INSERT INTO medawarcre.access_grants"
            "(id,workspace_id,subject_user_id,scope,source,external_ref_hash,"
            "profile,plan_key,status,starts_at,ends_at) "
            "VALUES (%s,%s,%s,'subject','manual',%s,'full_operator',%s,"
            "'active',%s,%s)",
            (
                ids["grant_id"],
                ids["workspace_id"],
                ids["user_id"],
                hashlib.sha256(uuid4().bytes).digest(),
                ids["plan_key"],
                now - timedelta(minutes=5),
                now + timedelta(days=7),
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.territories(workspace_id,name,state_code) "
            "VALUES (%s,'California','CA')",
            (ids["workspace_id"],),
        )
        connection.execute(
            "INSERT INTO medawarcre.oauth_clients"
            "(client_id,name,redirect_uris,scopes,active) "
            "VALUES (%s,'Admission Client',ARRAY['https://client.example/cb'],"
            "ARRAY['mcp:tools'],true)",
            (f"client-{uuid4().hex}",),
        )
        client_id = connection.execute(
            "SELECT client_id FROM medawarcre.oauth_clients "
            "WHERE name='Admission Client' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO medawarcre.oauth_sessions"
            "(id,workspace_id,user_id,client_id,scopes,audience,resource,"
            "authority_version,access_hash,refresh_hash,access_expires_at,"
            "refresh_expires_at,refresh_family_expires_at) "
            "VALUES (%s,%s,%s,%s,ARRAY['mcp:tools'],'medawarcre-mcp',"
            "'https://mcp.medawarcre.com/mcp',1,%s,%s,%s,%s,%s)",
            (
                ids["session_id"],
                ids["workspace_id"],
                ids["user_id"],
                client_id,
                hashlib.sha256(uuid4().bytes).digest(),
                hashlib.sha256(uuid4().bytes).digest(),
                now + timedelta(minutes=15),
                now + timedelta(days=14),
                now + timedelta(days=30),
            ),
        )
    context = TenantContext(
        workspace_id=ids["workspace_public_id"],
        profile=Profile.FULL_OPERATOR,
        plan=ids["plan_key"],
        quota_limits={"search": 2},
        territories=("CA",),
        active=True,
        trusted=False,
        actor_id=ids["user_id"],
        session_id=ids["session_id"],
    )
    return ids, context


def _repository(admission_dsn: str) -> PostgresAdmissionRepository:
    repository = PostgresAdmissionRepository(
        PostgresSettings(
            dsn=admission_dsn,
            min_size=1,
            max_size=4,
            application_name="medawarcre-admission-test",
        )
    )
    repository.open(wait=True)
    return repository


def _grant(
    admin_dsn: str,
    ids: dict[str, str],
    *,
    token: str,
    tool_name: str,
    arguments: dict,
    expires_in: timedelta = timedelta(minutes=5),
) -> None:
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.tool_approvals("
            "approval_token_hash,workspace_id,subject_user_id,session_hash,"
            "tool_name,args_hash,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                hashlib.sha256(token.encode("utf-8")).digest(),
                ids["workspace_id"],
                ids["user_id"],
                hashlib.sha256(ids["session_id"].encode("ascii")).digest(),
                tool_name,
                canonical_argument_hash(arguments),
                datetime.now(UTC) + expires_in,
            ),
        )


def test_canonical_arguments_are_strict_stable_utf8_json() -> None:
    left = {"z": [True, None, 1.25], "é": {"b": 2, "a": "東京"}}
    right = {"é": {"a": "東京", "b": 2}, "z": [True, None, 1.25]}
    assert canonical_argument_bytes(left) == canonical_argument_bytes(right)
    assert canonical_argument_bytes(left).decode("utf-8") == (
        '{"z":[true,null,1.25],"é":{"a":"東京","b":2}}'
    )
    assert len(canonical_argument_hash(left)) == 32

    class Dictionary(dict):
        pass

    for invalid in (
        {1: "non-string key"},
        {"": "empty key"},
        {"x": (1, 2)},
        {"x": {1, 2}},
        {"x": b"secret"},
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": "\ud800"},
        Dictionary(x=1),
    ):
        with pytest.raises(CanonicalArgumentsError):
            canonical_argument_bytes(invalid)


def test_malformed_database_output_fails_closed_without_leaking_parser_errors() -> None:
    bindings = {
        "invocation": str(uuid4()),
        "request_id": str(uuid4()),
        "workspace_public_id": "ws_test",
        "actor_id": str(uuid4()),
        "session_id": str(uuid4()),
        "tool_name": "search_properties",
    }
    base = {
        "decision": "denied",
        "reason_code": "approval_required",
        "safe_reason": "Approval is required.",
        "approval_request_id": "not-a-uuid",
        "quota_used": None,
        "replayed": False,
        "finalized": False,
    }
    with pytest.raises(AdmissionUnavailable, match="approval binding"):
        PostgresAdmissionRepository._outcome(base, **bindings)

    invalid_quota = {
        **base,
        "decision": "allowed",
        "reason_code": "allowed",
        "safe_reason": "Allowed.",
        "approval_request_id": None,
        "quota_used": "not-an-integer",
    }
    with pytest.raises(AdmissionUnavailable, match="quota result"):
        PostgresAdmissionRepository._outcome(invalid_quota, **bindings)

    invalid_replay = {
        **invalid_quota,
        "quota_used": None,
        "replayed": "false",
    }
    with pytest.raises(AdmissionUnavailable, match="replay state"):
        PostgresAdmissionRepository._outcome(invalid_replay, **bindings)


def test_approval_token_requires_valid_utf8_before_database_access() -> None:
    repository = PostgresAdmissionRepository(
        PostgresSettings(dsn="postgresql://unused.example/unused")
    )
    context = TenantContext(
        workspace_id="ws_test",
        profile=Profile.FULL_OPERATOR,
        plan="plan_test",
        quota_limits={},
        territories=("CA",),
        active=True,
        trusted=False,
        actor_id=str(uuid4()),
        session_id=str(uuid4()),
    )
    try:
        with pytest.raises(ValueError, match="valid UTF-8"):
            repository.admit(
                context,
                "generate_loi",
                {},
                quota_bucket=None,
                requires_approval=True,
                approval_token="\ud800",
            )
    finally:
        repository.close()


@pytest.mark.parametrize(
    "quota_bucket",
    [
        " search",
        "search ",
        "\tsearch",
        "search\n",
        "\N{NO-BREAK SPACE}search",
        "Search",
        "search-deals",
        "a" * 65,
    ],
)
def test_repository_rejects_noncanonical_quota_bucket_before_database_access(
    quota_bucket: str,
) -> None:
    repository = PostgresAdmissionRepository(
        PostgresSettings(dsn="postgresql://unused.example/unused")
    )
    context = TenantContext(
        workspace_id="ws_test",
        profile=Profile.FULL_OPERATOR,
        plan="plan_test",
        quota_limits={},
        territories=("CA",),
        active=True,
        trusted=False,
        actor_id=str(uuid4()),
        session_id=str(uuid4()),
    )
    try:
        with pytest.raises(ValueError, match="canonical identifier"):
            repository.admit(
                context,
                "search_properties",
                {},
                quota_bucket=quota_bucket,
                requires_approval=False,
            )
    finally:
        repository.close()


def test_oauth_and_admission_share_exact_quota_identifier_grammar() -> None:
    assert is_canonical_quota_bucket("search")
    assert is_canonical_quota_bucket("find_deals_2")
    assert _quotas({"search": 1, "find_deals_2": 0}) == {
        "search": 1,
        "find_deals_2": 0,
    }
    for invalid in (
        " search",
        "\tsearch",
        "search\n",
        "\N{NO-BREAK SPACE}search",
        "Search",
        "search-deals",
        "a" * 65,
    ):
        assert not is_canonical_quota_bucket(invalid)
        assert _quotas({invalid: 1}) is None


def test_migrations_through_0012_and_exact_admission_function_inventory() -> None:
    migrations = load_migrations()
    # Extended deliberately from [1..9] at migrations 0010 (platform
    # authority), 0011 (access audit log) and 0012 (identity projection).
    # The literal is kept rather than derived so that adding a migration
    # cannot pass unnoticed -- which is the only reason this line exists.
    assert [migration.version for migration in migrations] == [
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13
    ]
    assert migrations[2].name == "atomic request admission"
    assert migrations[3].name == "request scoped domain authority"
    assert EXPECTED_MIGRATION_VERSION == 13
    assert ADMISSION_FUNCTIONS == {
        (
            "atomic_admit_tool_call",
            "uuid, uuid, text, uuid, uuid, text, text, text, text, text[], text, bytea, text, boolean, bytea",
        ),
        (
            "record_tool_call_final",
            "uuid, uuid, text, uuid, uuid, text, boolean, text, text",
        ),
        # Migration 0012, added deliberately. The admission role must project
        # the platform authority's bigint-keyed identity into the certified
        # uuid-keyed tenant tables before it can admit a request at all. The
        # alternative was granting it INSERT on users, workspaces and
        # memberships, which would let any hosted request invent a tenant.
        (
            "project_platform_identity",
            "uuid, text, uuid, bigint",
        ),
        # Migration 0012, second half. Projects the session, account, grant,
        # plan quotas and territories that `atomic_admit_tool_call`'s credential
        # CTE reads and that nothing else writes. The trade it makes is recorded
        # in `postgres/authority.py` next to the same tuple.
        (
            "project_platform_authority",
            "uuid, text, uuid, bigint, uuid, text, text, text",
        ),
    }


def test_migrations_upgrade_immutable_0002(
    postgres_database: tuple[str, str, str],
) -> None:
    _, migration_dsn, _ = postgres_database
    migrations = load_migrations()
    assert MigrationRunner(migration_dsn, migrations[:2]).apply() == [1, 2]
    assert MigrationRunner(migration_dsn, migrations).apply() == [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]


def test_atomic_admission_revalidates_authority_and_mutates_nothing_on_denial(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn)
    repository = _repository(_admission_dsn(app_dsn))
    try:
        allowed = repository.admit(
            context,
            "list_deals",
            {},
            quota_bucket=None,
            requires_approval=False,
        )
        assert allowed.decision == "allowed"

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.territories SET state_code='TX',name='Texas' "
                "WHERE workspace_id=%s",
                (ids["workspace_id"],),
            )
        denied = repository.admit(
            context,
            "search_properties",
            {"location": "Los Angeles, CA"},
            quota_bucket="search",
            requires_approval=False,
        )
        assert denied.decision == "denied"
        assert denied.reason_code == "authority_changed"
    finally:
        repository.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.daily_quota_usage"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT decision,reason_code,args_hash IS NOT NULL "
            "FROM medawarcre.access_decision_audit "
            "WHERE invocation_id=%s",
            (denied.invocation_id,),
        ).fetchone() == ("denied", "authority_changed", True)


@pytest.mark.parametrize(
    ("authority_failure", "expected_reason"),
    (
        ("session_revoked", "authority_missing"),
        ("user_disabled", "user_disabled"),
        ("workspace_suspended", "workspace_suspended"),
        ("membership_suspended", "membership_suspended"),
        ("account_missing", "account_missing"),
        ("entitlement_revoked", "entitlement_missing_or_expired"),
        ("plan_inactive", "plan_missing_or_invalid"),
    ),
)
def test_every_live_authority_denial_class_consumes_no_approval_or_quota(
    postgres_database: tuple[str, str, str],
    authority_failure: str,
    expected_reason: str,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn)
    token = f"approval-{uuid4()}"
    arguments = {"deal_id": authority_failure}
    _grant(
        admin_dsn,
        ids,
        token=token,
        tool_name="generate_loi",
        arguments=arguments,
    )
    mutations = {
        "session_revoked": (
            "UPDATE medawarcre.oauth_sessions "
            "SET revoked_at=statement_timestamp() WHERE id=%s",
            ids["session_id"],
        ),
        "user_disabled": (
            "UPDATE medawarcre.users SET state='disabled' WHERE id=%s",
            ids["user_id"],
        ),
        "workspace_suspended": (
            "UPDATE medawarcre.workspaces SET state='suspended' WHERE id=%s",
            ids["workspace_id"],
        ),
        "membership_suspended": (
            "UPDATE medawarcre.memberships SET state='suspended' WHERE id=%s",
            ids["membership_id"],
        ),
        "account_missing": (
            "DELETE FROM medawarcre.workspace_accounts WHERE workspace_id=%s",
            ids["workspace_id"],
        ),
        "entitlement_revoked": (
            "UPDATE medawarcre.access_grants SET status='revoked' WHERE id=%s",
            ids["grant_id"],
        ),
        "plan_inactive": (
            "UPDATE medawarcre.plans SET active=false WHERE plan_key=%s",
            ids["plan_key"],
        ),
    }
    sql, value = mutations[authority_failure]
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(sql, (value,))

    repository = _repository(_admission_dsn(app_dsn))
    try:
        denied = repository.admit(
            context,
            "generate_loi",
            arguments,
            quota_bucket="search",
            requires_approval=True,
            approval_token=token,
        )
    finally:
        repository.close()
    assert denied.decision == "denied"
    assert denied.reason_code == expected_reason
    assert not denied.replayed
    assert not denied.finalized

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT consumed_at FROM medawarcre.tool_approvals"
        ).fetchone() == (None,)
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.daily_quota_usage"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT reason_code,args_hash IS NOT NULL,"
            "admission_binding_hash IS NOT NULL "
            "FROM medawarcre.access_decision_audit WHERE invocation_id=%s",
            (denied.invocation_id,),
        ).fetchone() == (expected_reason, True, True)


def test_approval_and_quota_are_consumed_together_only_once(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn, quotas='{"search":1}')
    arguments = {"deal_id": "deal-1"}
    token = f"approval-{uuid4()}"
    _grant(
        admin_dsn,
        ids,
        token=token,
        tool_name="generate_loi",
        arguments=arguments,
    )
    repository = _repository(_admission_dsn(app_dsn))
    try:
        first = repository.admit(
            context,
            "generate_loi",
            arguments,
            quota_bucket="search",
            requires_approval=True,
            approval_token=token,
        )
        second = repository.admit(
            context,
            "generate_loi",
            arguments,
            quota_bucket="search",
            requires_approval=True,
            approval_token=token,
        )
    finally:
        repository.close()
    assert first.decision == "allowed"
    assert first.quota_used == 1
    assert second.decision == "denied"
    assert second.reason_code in {"approval_invalid", "quota_exceeded"}

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT used_count FROM medawarcre.daily_quota_usage "
            "WHERE workspace_id=%s AND bucket='search'",
            (ids["workspace_id"],),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.tool_approvals "
            "WHERE consumed_at IS NOT NULL"
        ).fetchone() == (1,)


def test_approval_request_id_can_be_granted_with_the_exact_audited_binding(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn)
    arguments = {"deal_id": "deal-pending"}
    repository = _repository(_admission_dsn(app_dsn))
    try:
        pending = repository.admit(
            context,
            "generate_loi",
            arguments,
            quota_bucket=None,
            requires_approval=True,
        )
        assert pending.decision == "approval_required"
        assert pending.approval_id == pending.invocation_id
        _grant(
            admin_dsn,
            ids,
            token=pending.approval_id,
            tool_name="generate_loi",
            arguments=arguments,
        )
        allowed = repository.admit(
            context,
            "generate_loi",
            arguments,
            quota_bucket=None,
            requires_approval=True,
            approval_token=pending.approval_id,
        )
        assert allowed.decision == "allowed"
    finally:
        repository.close()


def test_approval_mismatch_and_zero_quota_leave_approval_unspent(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn, quotas='{"search":0}')
    token = f"approval-{uuid4()}"
    bound_arguments = {"deal_id": "bound"}
    _grant(
        admin_dsn,
        ids,
        token=token,
        tool_name="generate_loi",
        arguments=bound_arguments,
    )
    repository = _repository(_admission_dsn(app_dsn))
    try:
        mismatch = repository.admit(
            context,
            "generate_loi",
            {"deal_id": "different"},
            quota_bucket="search",
            requires_approval=True,
            approval_token=token,
        )
        assert mismatch.reason_code == "approval_invalid"
        quota_denial = repository.admit(
            context,
            "generate_loi",
            bound_arguments,
            quota_bucket="search",
            requires_approval=True,
            approval_token=token,
        )
        assert quota_denial.reason_code == "quota_exceeded"
    finally:
        repository.close()
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT consumed_at FROM medawarcre.tool_approvals"
        ).fetchone() == (None,)
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.daily_quota_usage"
        ).fetchone() == (0,)


@pytest.mark.parametrize("lifecycle", ("expired", "revoked"))
def test_expired_and_revoked_approvals_fail_without_quota_mutation(
    postgres_database: tuple[str, str, str],
    lifecycle: str,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn)
    token = f"approval-{uuid4()}"
    arguments = {"deal_id": lifecycle}
    _grant(
        admin_dsn,
        ids,
        token=token,
        tool_name="generate_loi",
        arguments=arguments,
    )
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        if lifecycle == "expired":
            connection.execute(
                "UPDATE medawarcre.tool_approvals "
                "SET issued_at=statement_timestamp()-interval '10 minutes',"
                "expires_at=statement_timestamp()-interval '5 minutes'"
            )
        else:
            connection.execute(
                "UPDATE medawarcre.tool_approvals "
                "SET revoked_at=statement_timestamp()"
            )
    repository = _repository(_admission_dsn(app_dsn))
    try:
        denied = repository.admit(
            context,
            "generate_loi",
            arguments,
            quota_bucket="search",
            requires_approval=True,
            approval_token=token,
        )
    finally:
        repository.close()
    assert denied.reason_code == "approval_invalid"
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT consumed_at FROM medawarcre.tool_approvals"
        ).fetchone() == (None,)
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.daily_quota_usage"
        ).fetchone() == (0,)


def test_missing_plan_quota_is_unlimited_but_usage_remains_durable(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn, quotas="{}")
    repository = _repository(_admission_dsn(app_dsn))
    try:
        outcomes = [
            repository.admit(
                context,
                "search_properties",
                {"location": f"Los Angeles, CA {index}"},
                quota_bucket="search",
                requires_approval=False,
            )
            for index in range(3)
        ]
    finally:
        repository.close()
    assert [outcome.decision for outcome in outcomes] == ["allowed"] * 3
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT used_count FROM medawarcre.daily_quota_usage "
            "WHERE workspace_id=%s AND bucket='search'",
            (ids["workspace_id"],),
        ).fetchone() == (3,)


@pytest.mark.parametrize(
    "quotas",
    [
        json.dumps({" search ": 0}),
        json.dumps({"\tsearch": 0}),
        json.dumps({"search\n": 0}),
        json.dumps({"\N{NO-BREAK SPACE}search": 0}, ensure_ascii=False),
        json.dumps({"Search": 0}),
        json.dumps({"search-deals": 0}),
        json.dumps({"search": 1, "\tsearch": 0}),
    ],
)
def test_noncanonical_quota_key_invalidates_plan_instead_of_becoming_unlimited(
    postgres_database: tuple[str, str, str],
    quotas: str,
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn, quotas=quotas)
    repository = _repository(_admission_dsn(app_dsn))
    try:
        denied = repository.admit(
            context,
            "search_properties",
            {"location": "Los Angeles, CA"},
            quota_bucket="search",
            requires_approval=False,
        )
    finally:
        repository.close()
    assert denied.decision == "denied"
    assert denied.reason_code == "plan_missing_or_invalid"
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.daily_quota_usage "
            "WHERE workspace_id=%s",
            (ids["workspace_id"],),
        ).fetchone() == (0,)


def test_quota_usage_date_is_utc_even_when_session_timezone_crosses_date(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn, quotas='{"search":1}')
    timezone_name = (
        "Pacific/Kiritimati" if datetime.now(UTC).hour >= 10 else "Pacific/Pago_Pago"
    )
    invocation_id = str(uuid4())
    request_id = str(uuid4())
    with psycopg.connect(_admission_dsn(app_dsn)) as connection:
        connection.execute(
            "SELECT pg_catalog.set_config('TimeZone', %s, false)",
            (timezone_name,),
        )
        local_date, utc_date = connection.execute(
            "SELECT current_date,"
            "(statement_timestamp() AT TIME ZONE 'UTC')::date"
        ).fetchone()
        assert local_date != utc_date
        connection.execute("SET ROLE medawarcre_admission")
        outcome = connection.execute(
            "SELECT * FROM medawarcre.atomic_admit_tool_call("
            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                invocation_id,
                request_id,
                context.workspace_id,
                context.actor_id,
                context.session_id,
                "medawarcre-mcp",
                "https://mcp.medawarcre.com/mcp",
                context.profile.value,
                context.plan,
                list(context.territories),
                "search_properties",
                canonical_argument_hash({"location": "Los Angeles, CA"}),
                "search",
                False,
                None,
            ),
        ).fetchone()
        assert outcome[0] == "allowed"
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT usage_date,used_count FROM medawarcre.daily_quota_usage "
            "WHERE workspace_id=%s AND bucket='search'",
            (ids["workspace_id"],),
        ).fetchone() == (utc_date, 1)


def test_concurrent_quota_admission_never_exceeds_live_limit(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn, quotas='{"search":2}')
    admission_dsn = _admission_dsn(app_dsn)

    def admit(index: int) -> str:
        repository = _repository(admission_dsn)
        try:
            return repository.admit(
                context,
                "search_properties",
                {"location": f"Los Angeles, CA #{index}"},
                quota_bucket="search",
                requires_approval=False,
            ).decision
        finally:
            repository.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        decisions = list(executor.map(admit, range(4)))
    assert decisions.count("allowed") == 2
    assert decisions.count("denied") == 2
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT used_count FROM medawarcre.daily_quota_usage "
            "WHERE workspace_id=%s AND bucket='search'",
            (ids["workspace_id"],),
        ).fetchone() == (2,)


def test_concurrent_approval_admission_spends_one_token_once(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    ids, context = _seed_authority(admin_dsn)
    token = f"approval-{uuid4()}"
    arguments = {"deal_id": "one-spend"}
    _grant(
        admin_dsn,
        ids,
        token=token,
        tool_name="generate_loi",
        arguments=arguments,
    )
    admission_dsn = _admission_dsn(app_dsn)

    def admit(_: int) -> str:
        repository = _repository(admission_dsn)
        try:
            return repository.admit(
                context,
                "generate_loi",
                arguments,
                quota_bucket=None,
                requires_approval=True,
                approval_token=token,
            ).decision
        finally:
            repository.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        decisions = list(executor.map(admit, range(4)))
    assert decisions.count("allowed") == 1
    assert decisions.count("denied") == 3
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.tool_approvals "
            "WHERE consumed_at IS NOT NULL"
        ).fetchone() == (1,)


def test_invocation_reuse_binds_every_effective_admission_input(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    _, context = _seed_authority(admin_dsn)
    invocation_id = str(uuid4())
    request_id = str(uuid4())
    repository = _repository(_admission_dsn(app_dsn))
    try:
        first = repository.admit(
            context,
            "list_deals",
            {},
            quota_bucket=None,
            requires_approval=False,
            invocation_id=invocation_id,
            request_correlation_id=request_id,
        )
        assert first.decision == "allowed"

        conflicting_calls = (
            lambda: repository.admit(
                context,
                "list_deals",
                {},
                quota_bucket="search",
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            ),
            lambda: repository.admit(
                context,
                "list_deals",
                {},
                quota_bucket=None,
                requires_approval=True,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            ),
            lambda: repository.admit(
                context.model_copy(update={"profile": Profile.NATIONAL_SCOUT}),
                "list_deals",
                {},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            ),
            lambda: repository.admit(
                context.model_copy(update={"plan": "plan_changed"}),
                "list_deals",
                {},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            ),
            lambda: repository.admit(
                context.model_copy(update={"territories": ("TX",)}),
                "list_deals",
                {},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            ),
            lambda: repository.admit(
                context.model_copy(update={"workspace_id": "ws_changed"}),
                "list_deals",
                {},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            ),
            lambda: repository.admit(
                context.model_copy(update={"actor_id": str(uuid4())}),
                "list_deals",
                {},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            ),
            lambda: repository.admit(
                context.model_copy(update={"session_id": str(uuid4())}),
                "list_deals",
                {},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            ),
            lambda: repository.admit(
                context,
                "search_properties",
                {},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            ),
            lambda: repository.admit(
                context,
                "list_deals",
                {"changed": True},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            ),
            lambda: repository.admit(
                context,
                "list_deals",
                {},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=str(uuid4()),
            ),
        )
        for conflicting_call in conflicting_calls:
            with pytest.raises(AdmissionUnavailable, match="binding"):
                conflicting_call()

        original_audience = repository.audience
        repository.audience = "changed-audience"
        with pytest.raises(AdmissionUnavailable, match="binding"):
            repository.admit(
                context,
                "list_deals",
                {},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            )
        repository.audience = original_audience

        original_resource = repository.resource
        repository.resource = "https://changed.example/mcp"
        with pytest.raises(AdmissionUnavailable, match="binding"):
            repository.admit(
                context,
                "list_deals",
                {},
                quota_bucket=None,
                requires_approval=False,
                invocation_id=invocation_id,
                request_correlation_id=request_id,
            )
        repository.resource = original_resource

        pending_invocation = str(uuid4())
        pending_request = str(uuid4())
        pending = repository.admit(
            context,
            "generate_loi",
            {"deal_id": "pending-binding"},
            quota_bucket=None,
            requires_approval=True,
            invocation_id=pending_invocation,
            request_correlation_id=pending_request,
        )
        assert pending.decision == "approval_required"
        with pytest.raises(AdmissionUnavailable, match="binding"):
            repository.admit(
                context,
                "generate_loi",
                {"deal_id": "pending-binding"},
                quota_bucket=None,
                requires_approval=True,
                approval_token="different-token",
                invocation_id=pending_invocation,
                request_correlation_id=pending_request,
            )
    finally:
        repository.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.daily_quota_usage"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*),count(admission_binding_hash) "
            "FROM medawarcre.access_decision_audit WHERE phase='admission'"
        ).fetchone() == (2, 2)


def test_admission_retry_and_final_audit_are_idempotent_and_bound(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    _, context = _seed_authority(admin_dsn)
    invocation_id = str(uuid4())
    request_id = str(uuid4())
    repository = _repository(_admission_dsn(app_dsn))
    try:
        first = repository.admit(
            context,
            "list_deals",
            {},
            quota_bucket=None,
            requires_approval=False,
            invocation_id=invocation_id,
            request_correlation_id=request_id,
        )
        retry = repository.admit(
            context,
            "list_deals",
            {},
            quota_bucket=None,
            requires_approval=False,
            invocation_id=invocation_id,
            request_correlation_id=request_id,
        )
        assert not first.replayed
        assert not first.finalized
        assert retry.decision == first.decision
        assert retry.reason_code == first.reason_code
        assert retry.replayed
        assert not retry.finalized
        with pytest.raises(ValueError, match="fresh execution owner"):
            repository.record_final(
                retry,
                succeeded=True,
                reason_code="completed",
                safe_reason="replay must not finalize",
            )
        final = repository.record_final(
            first,
            succeeded=True,
            reason_code="completed",
            safe_reason="tool call completed",
        )
        assert repository.record_final(
            first,
            succeeded=True,
            reason_code="completed",
            safe_reason="tool call completed",
        ) == final
        completed_retry = repository.admit(
            context,
            "list_deals",
            {},
            quota_bucket=None,
            requires_approval=False,
            invocation_id=invocation_id,
            request_correlation_id=request_id,
        )
        assert completed_retry.decision == "allowed"
        assert completed_retry.replayed
        assert completed_retry.finalized
        with pytest.raises(ValueError, match="fresh execution owner"):
            repository.record_final(
                completed_retry,
                succeeded=True,
                reason_code="completed",
                safe_reason="finalized replay must not finalize",
            )
        with pytest.raises(AdmissionUnavailable):
            repository.record_final(
                first,
                succeeded=False,
                reason_code="failed",
                safe_reason="conflicting final state",
            )
    finally:
        repository.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        assert connection.execute(
            "SELECT phase,decision FROM medawarcre.access_decision_audit "
            "WHERE invocation_id=%s ORDER BY occurred_at",
            (invocation_id,),
        ).fetchall() == [("admission", "allowed"), ("final", "succeeded")]


def test_admission_login_has_only_new_function_authority(
    postgres_database: tuple[str, str, str],
) -> None:
    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(_admission_dsn(app_dsn)) as connection:
        connection.execute("SET ROLE medawarcre_admission")
        for old_call in (
            "SELECT medawarcre.consume_tool_approval(NULL,NULL,NULL,NULL,NULL,NULL)",
            "SELECT medawarcre.consume_daily_quota(NULL,NULL,NULL,NULL)",
            "SELECT medawarcre.record_access_decision(NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(old_call)
            connection.rollback()
            connection.execute("SET ROLE medawarcre_admission")


def test_repository_rejects_admission_group_acl_drift_and_redacts_dsn(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    admission_dsn = _admission_dsn(app_dsn)
    repository = PostgresAdmissionRepository(
        PostgresSettings(dsn=admission_dsn, min_size=1, max_size=1)
    )
    assert admission_dsn not in repr(repository)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "GRANT EXECUTE ON FUNCTION medawarcre.consume_daily_quota("
            "uuid,text,bigint,bigint) TO medawarcre_admission"
        )
    with pytest.raises(AdmissionUnavailable, match="authority contract") as failure:
        repository.open(wait=True)
    assert admission_dsn not in str(failure.value)
