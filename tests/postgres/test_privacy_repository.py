"""Privacy and retention, on both sides of the customer boundary.

Two claims are under test here and they pull in opposite directions.

The first is that the *request-scoped* repository refuses everything. That is
easy to satisfy and easy to fake: a class whose methods raise unconditionally
passes any refusal test ever written, and it is indistinguishable from one that
was simply never implemented. So the second claim is the one that carries the
weight — supply a tool mapping and the same code drives real SQL against the
real database end to end. Fail-closed and unimplemented look identical from
outside; ``test_the_refusal_is_the_empty_tool_map_and_not_absent_sql`` is what
separates them, and it is the reason the methods below are written rather than
stubbed.

Everything else concerns ``InternalPrivacyDesk``, which is how privacy requests
are actually processed at launch: internal staff, through the Operations
Console, never a customer portal.
"""

from __future__ import annotations

import ast
import json
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from cre_mcp.access.context import TenantContext, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.domains import (
    HostedRequestRepositories,
    use_hosted_request_repositories,
)
from cre_mcp.postgres.migrations import MigrationRunner, load_migrations
from cre_mcp.postgres.pool import PostgresDatabase
from cre_mcp.postgres.privacy import (
    STATUSES,
    TRANSITIONS,
    InternalPrivacyDesk,
    InternalPrivacyDeskUnavailable,
    PostgresPrivacyRepository,
    PrivacyPersistenceUnavailable,
    StaffActor,
)
from cre_mcp.postgres import privacy as privacy_module

OWNER = "owner"
ANALYST = "read_only_analyst"
REASON = "processing a subject access request"


# ---------------------------------------------------------------------------
# Harness.
# ---------------------------------------------------------------------------


def _admission(
    tool_name: str,
    *,
    workspace_public_id: str = "ws_privacy_a",
    actor_user_id: str | None = None,
    session_id: str | None = None,
) -> AdmissionOutcome:
    return AdmissionOutcome(
        invocation_id=str(uuid4()),
        request_correlation_id=str(uuid4()),
        workspace_public_id=workspace_public_id,
        actor_user_id=actor_user_id or str(uuid4()),
        session_id=session_id or str(uuid4()),
        tool_name=tool_name,
        decision="allowed",
        reason_code="authority_admitted",
        safe_reason="request admitted by live authority",
        replayed=False,
        finalized=False,
    )


def _context(admission: AdmissionOutcome) -> TenantContext:
    return TenantContext(
        workspace_id=admission.workspace_public_id,
        profile=Profile.FULL_OPERATOR,
        actor_id=admission.actor_user_id,
        session_id=admission.session_id,
    )


def _repositories(
    admission: AdmissionOutcome, privacy: object
) -> HostedRequestRepositories:
    marker = object()
    return HostedRequestRepositories(
        admission=admission,
        platform=marker,
        provider=marker,
        search=marker,
        deal=marker,
        privacy=privacy,
        job=marker,
        document=marker,
        truth_asset=marker,
    )


@contextmanager
def _active(repository: object, admission: AdmissionOutcome):
    """The most correct-looking scope a caller could possibly supply."""
    with use_context(_context(admission)), use_hosted_request_repositories(
        _repositories(admission, repository)
    ):
        yield


def _database(app_dsn: str) -> PostgresDatabase:
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=4, runtime_mode="app")
    )
    database.open()
    return database


def _seed_workspace(
    admin_dsn: str,
    *,
    workspace_public_id: str,
    actor_ids: tuple[str, ...],
) -> str:
    workspace_id = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        for index, actor_id in enumerate(actor_ids):
            connection.execute(
                "INSERT INTO medawarcre.users(id,email,name,state) "
                "VALUES (%s,%s,%s,'active')",
                (
                    actor_id,
                    f"privacy-{uuid4().hex}@example.test",
                    f"Privacy Subject {index}",
                ),
            )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) "
            "VALUES (%s,%s,'Privacy Workspace','active')",
            (workspace_id, workspace_public_id),
        )
        for actor_id in actor_ids:
            connection.execute(
                "INSERT INTO medawarcre.memberships("
                "id,workspace_id,user_id,role,state) "
                "VALUES (%s,%s,%s,'member','active')",
                (str(uuid4()), workspace_id, actor_id),
            )
    return workspace_id


def _seed_admission(
    admin_dsn: str, workspace_id: str, admission: AdmissionOutcome
) -> None:
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.access_decision_audit("
            "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
            "session_correlation_hash,request_correlation_id,tool_name,decision,"
            "reason_code,safe_reason,args_hash,admission_binding_hash) VALUES ("
            "%s,'admission',true,%s,%s,"
            "pg_catalog.sha256(pg_catalog.convert_to(%s,'UTF8')),%s,%s,'allowed',"
            "'authority_admitted','request admitted by live authority',"
            "decode(repeat('91',32),'hex'),decode(repeat('92',32),'hex'))",
            (
                admission.invocation_id,
                workspace_id,
                admission.actor_user_id,
                admission.session_id,
                admission.request_correlation_id,
                admission.tool_name,
            ),
        )


def _seed_staff(admin_dsn: str) -> dict[str, str]:
    ids = {"owner": str(uuid4()), "analyst": str(uuid4())}
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name) VALUES "
            "(%s,%s,'Privacy Owner'),(%s,%s,'Privacy Analyst')",
            (
                ids["owner"],
                f"staff-owner-{uuid4().hex}@example.test",
                ids["analyst"],
                f"staff-analyst-{uuid4().hex}@example.test",
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.staff_roles(user_id,role,active) VALUES "
            "(%s,'owner',true),(%s,'read_only_analyst',true)",
            (ids["owner"], ids["analyst"]),
        )
    return ids


def _prepare(
    postgres_database: tuple[str, str, str],
    admissions: tuple[AdmissionOutcome, ...],
) -> tuple[str, str, PostgresDatabase]:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    workspace_id = _seed_workspace(
        admin_dsn,
        workspace_public_id=admissions[0].workspace_public_id,
        actor_ids=tuple(dict.fromkeys(item.actor_user_id for item in admissions)),
    )
    for admission in admissions:
        _seed_admission(admin_dsn, workspace_id, admission)
    return admin_dsn, workspace_id, _database(app_dsn)


def _desk(app_dsn: str) -> InternalPrivacyDesk:
    return InternalPrivacyDesk.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )


@pytest.fixture
def staffed(
    postgres_database: tuple[str, str, str],
) -> tuple[str, str, dict[str, str], InternalPrivacyDesk]:
    """A migrated database, one workspace with two members, and staff."""
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    subject = str(uuid4())
    other = str(uuid4())
    workspace_id = _seed_workspace(
        admin_dsn,
        workspace_public_id="ws_privacy_a",
        actor_ids=(subject, other),
    )
    ids = _seed_staff(admin_dsn)
    ids["subject"] = subject
    ids["other"] = other
    ids["workspace_id"] = workspace_id
    ids["workspace_public_id"] = "ws_privacy_a"
    desk = _desk(app_dsn)
    try:
        yield admin_dsn, app_dsn, ids, desk
    finally:
        desk.close()


def _owner(ids: dict[str, str]) -> StaffActor:
    return StaffActor(ids["owner"], OWNER, "privacy_request")


def _analyst(ids: dict[str, str]) -> StaffActor:
    return StaffActor(ids["analyst"], ANALYST, "privacy_request")


def _audit_rows(admin_dsn: str, **filters: object) -> list[tuple]:
    where = " AND ".join(f"{name}=%s" for name in filters) or "true"
    with psycopg.connect(admin_dsn) as connection:
        return connection.execute(
            "SELECT action,result,object_type,object_id,actor_role,reason "
            f"FROM medawarcre.staff_audit_log WHERE {where} "
            "ORDER BY occurred_at,id",
            tuple(filters.values()),
        ).fetchall()


# ---------------------------------------------------------------------------
# The request-scoped port: the empty tool map, and what it is not.
# ---------------------------------------------------------------------------


def test_the_customer_surface_declares_no_privacy_capability() -> None:
    """The empty tool map traced to its cause, not left as an assertion.

    ``_METHOD_TOOLS`` being empty is only defensible while the customer
    capability matrix genuinely names no privacy capability. If someone later
    adds one, this fails here rather than silently leaving a repository that
    refuses a capability the product now claims to offer.
    """
    matrix = (
        Path(__file__).resolve().parents[2]
        / "src" / "cre_mcp" / "access" / "capability_matrix.json"
    )
    text = json.dumps(json.loads(matrix.read_text())).casefold()
    for forbidden in ("privacy", "retention", "erasure", "data_export"):
        assert forbidden not in text, (
            f"the customer surface now names {forbidden!r}; "
            "_METHOD_TOOLS can no longer be empty by construction"
        )
    assert privacy_module._METHOD_TOOLS == {}


async def test_every_request_scoped_method_refuses_with_the_opaque_message(
    postgres_database: tuple[str, str, str],
) -> None:
    """A correct-looking admission changes nothing, and nothing is written."""
    admission = _admission("save_search")
    admin_dsn, _workspace_id, database = _prepare(postgres_database, (admission,))
    repository = PostgresPrivacyRepository(database, admission)
    try:
        with _active(repository, admission):
            with pytest.raises(
                PrivacyPersistenceUnavailable,
                match="^privacy persistence unavailable$",
            ):
                await repository.submit_request("export", "please export my data")
            with pytest.raises(
                PrivacyPersistenceUnavailable,
                match="^privacy persistence unavailable$",
            ):
                await repository.list_requests()

        # Outside any scope, too.
        with pytest.raises(PrivacyPersistenceUnavailable):
            await repository.submit_request("access", None)
        with pytest.raises(PrivacyPersistenceUnavailable):
            await repository.list_requests()

        with psycopg.connect(admin_dsn) as connection:
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.privacy_requests"
            ).fetchone()[0] == 0
    finally:
        database.close()


async def test_the_refusal_is_the_empty_tool_map_and_not_absent_sql(
    postgres_database: tuple[str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supply a tool mapping and the identical code path writes and reads.

    Without this, ``PostgresPrivacyRepository`` and a class of two ``raise``
    statements are the same artefact. With it, the refusal is demonstrably
    caused by the mapping being empty: substitute a mapping and the SQL runs
    against the real database, under the real admission, through the same
    guard.
    """
    admission = _admission("save_search")
    admin_dsn, workspace_id, database = _prepare(postgres_database, (admission,))
    repository = PostgresPrivacyRepository(database, admission)
    try:
        with _active(repository, admission):
            with pytest.raises(PrivacyPersistenceUnavailable):
                await repository.list_requests()

        monkeypatch.setattr(
            privacy_module,
            "_METHOD_TOOLS",
            {
                "submit_request": frozenset({"save_search"}),
                "list_requests": frozenset({"save_search"}),
            },
        )
        with _active(repository, admission):
            request_id = await repository.submit_request(
                "export", "please export my data"
            )
            rows = await repository.list_requests()

        assert str(UUID(request_id)) == request_id
        assert [row["id"] for row in rows] == [request_id]
        assert rows[0]["kind"] == "export"
        assert rows[0]["status"] == "received"
        assert rows[0]["detail"] == "please export my data"

        # The row is genuinely in PostgreSQL, under the admitted workspace and
        # the admitted actor -- not a value the repository made up.
        with psycopg.connect(admin_dsn) as connection:
            assert connection.execute(
                "SELECT workspace_id::text,user_id::text,kind,status "
                "FROM medawarcre.privacy_requests WHERE id=%s",
                (request_id,),
            ).fetchone() == (
                workspace_id,
                admission.actor_user_id,
                "export",
                "received",
            )

        # And restoring the real (empty) mapping restores the refusal, so the
        # mapping is the only thing that moved.
        monkeypatch.undo()
        with _active(repository, admission):
            with pytest.raises(PrivacyPersistenceUnavailable):
                await repository.list_requests()
    finally:
        database.close()


async def test_the_request_scoped_port_refuses_a_mismatched_or_dead_scope(
    postgres_database: tuple[str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the mapping supplied, the *other* guards still hold.

    Otherwise the proof above would only show that the empty mapping is the
    single thing standing between a customer and this SQL.
    """
    admission = _admission("save_search")
    other = _admission("save_search")
    _admin_dsn, _workspace_id, database = _prepare(
        postgres_database, (admission, other)
    )
    repository = PostgresPrivacyRepository(database, admission)
    monkeypatch.setattr(
        privacy_module,
        "_METHOD_TOOLS",
        {"list_requests": frozenset({"save_search"})},
    )
    try:
        # No scope at all.
        with pytest.raises(PrivacyPersistenceUnavailable):
            await repository.list_requests()

        # A live scope carrying somebody else's admission.
        with _active(repository, other):
            with pytest.raises(PrivacyPersistenceUnavailable):
                await repository.list_requests()

        # A scope whose tenant context disagrees with the admission.
        mismatched = TenantContext(
            workspace_id=admission.workspace_public_id,
            profile=Profile.FULL_OPERATOR,
            actor_id=str(uuid4()),
            session_id=admission.session_id,
        )
        with use_context(mismatched), use_hosted_request_repositories(
            _repositories(admission, repository)
        ):
            with pytest.raises(PrivacyPersistenceUnavailable):
                await repository.list_requests()

        # A scope whose privacy slot is some other object.
        with use_context(_context(admission)), use_hosted_request_repositories(
            _repositories(admission, object())
        ):
            with pytest.raises(PrivacyPersistenceUnavailable):
                await repository.list_requests()

        # A scope that has already closed.
        with _active(repository, admission):
            pass
        with pytest.raises(PrivacyPersistenceUnavailable):
            await repository.list_requests()
    finally:
        database.close()


# ---------------------------------------------------------------------------
# The internal desk is not reachable from customer request scope.
# ---------------------------------------------------------------------------


def test_the_internal_desk_is_not_reachable_from_customer_request_scope() -> None:
    """Same rule the opportunity index carries, narrowed to the desk symbol.

    ``privacy.py`` deliberately holds both sides of this boundary, because the
    request-scoped port and the staff desk speak about the same two tables and
    splitting them would let the two drift. So the static rule cannot be "no
    module may import ``privacy``" -- the controller must import
    ``PostgresPrivacyRepository`` to fill the bundle field. It is instead: no
    module outside ``cre_mcp/platform/`` may name ``InternalPrivacyDesk``, and
    none may take the module whole, which would hand it the same reach by
    attribute access.
    """

    def reaches_the_desk(text: str) -> bool:
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                if any(
                    alias.name == "cre_mcp.postgres.privacy"
                    for alias in node.names
                ):
                    return True
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = {alias.name for alias in node.names}
                if (
                    module.endswith("postgres.privacy")
                    or (node.level and module == "privacy")
                ) and "InternalPrivacyDesk" in names:
                    return True
                if (
                    module in ("cre_mcp.postgres", "postgres")
                    and "privacy" in names
                ):
                    return True
        return False

    # Positive controls: each spelling that would actually reach the desk.
    for spelling in (
        "from cre_mcp.postgres.privacy import InternalPrivacyDesk",
        "import cre_mcp.postgres.privacy",
        "import cre_mcp.postgres.privacy as pd",
        "from cre_mcp.postgres import privacy",
        "from .privacy import InternalPrivacyDesk",
    ):
        assert reaches_the_desk(spelling), f"detector missed: {spelling}"
    # Negative controls: the bundle port is allowed everywhere, and a mention
    # is not an import.
    for allowed in (
        "from cre_mcp.postgres.privacy import PostgresPrivacyRepository",
        "from cre_mcp.postgres.privacy import PrivacyPersistenceUnavailable",
        'X = "InternalPrivacyDesk"',
    ):
        assert not reaches_the_desk(allowed), f"detector over-flagged: {allowed}"

    source_root = Path(__file__).resolve().parents[2] / "src"
    scanned = 0
    offenders: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        if path.name == "privacy.py":
            continue
        scanned += 1
        text = path.read_text()
        if "privacy" not in text:
            continue
        if reaches_the_desk(text):
            offenders.append(str(path.relative_to(source_root)))

    assert scanned > 200, f"the scan only visited {scanned} modules"
    assert all(
        offender.startswith("cre_mcp/platform/") for offender in offenders
    ), f"the privacy desk is reachable outside the internal path: {offenders}"


def test_the_desk_refuses_the_customer_runtime_pool(
    postgres_database: tuple[str, str, str],
) -> None:
    """The app pool is not a door into the desk, whatever the caller holds."""
    _admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    database = _database(app_dsn)
    try:
        with pytest.raises(InternalPrivacyDeskUnavailable):
            InternalPrivacyDesk(database)
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Staff processing.
# ---------------------------------------------------------------------------


def test_staff_submit_list_and_advance_are_the_processing_path(
    staffed: tuple[str, str, dict[str, str], InternalPrivacyDesk],
) -> None:
    admin_dsn, _app_dsn, ids, desk = staffed
    actor = _owner(ids)

    first = desk.submit(
        ids["workspace_public_id"], ids["subject"], "export",
        "subject asked by email", actor=actor, reason=REASON,
    )
    second = desk.submit(
        ids["workspace_public_id"], ids["other"], "delete",
        None, actor=actor, reason=REASON,
    )
    assert str(UUID(first)) == first
    assert first != second

    page = desk.list_requests(
        ids["workspace_public_id"], actor=actor, reason=REASON
    )
    # Newest first, and stable: (created_at DESC, id).
    assert [item.id for item in page] == [second, first]
    assert {item.status for item in page} == {"received"}
    assert page[1].kind == "export"
    assert page[1].detail == "subject asked by email"
    assert page[1].workspace_public_id == ids["workspace_public_id"]
    assert page[1].subject_user_id == ids["subject"]
    assert page[1].completed_at is None

    # Pagination is real, not decorative.
    assert [
        item.id
        for item in desk.list_requests(
            ids["workspace_public_id"], actor=actor, reason=REASON, limit=1
        )
    ] == [second]
    assert [
        item.id
        for item in desk.list_requests(
            ids["workspace_public_id"], actor=actor, reason=REASON,
            limit=1, offset=1,
        )
    ] == [first]

    for step in ("verified", "in_progress", "completed"):
        record = desk.advance(first, step, actor=actor, reason=REASON)
        assert record.status == step
    assert record.completed_at is not None

    # The status filter reads what advance wrote.
    assert [
        item.id
        for item in desk.list_requests(
            ids["workspace_public_id"], "completed", actor=actor, reason=REASON
        )
    ] == [first]
    assert [
        item.id
        for item in desk.list_requests(
            ids["workspace_public_id"], "received", actor=actor, reason=REASON
        )
    ] == [second]

    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT status,completed_at IS NOT NULL "
            "FROM medawarcre.privacy_requests WHERE id=%s",
            (first,),
        ).fetchone() == ("completed", True)


def test_every_illegal_status_transition_is_refused(
    staffed: tuple[str, str, dict[str, str], InternalPrivacyDesk],
) -> None:
    """The graph, exhaustively, in both directions.

    The table's CHECK bounds which statuses may *exist*; it says nothing about
    which orderings are legal, so without this a request could go straight from
    ``received`` to ``completed`` and skip verifying the person who asked.
    """
    admin_dsn, _app_dsn, ids, desk = staffed
    actor = _owner(ids)

    routes = {
        "received": (),
        "verified": ("verified",),
        "in_progress": ("verified", "in_progress"),
        "completed": ("verified", "in_progress", "completed"),
        "rejected": ("verified", "in_progress", "rejected"),
        "canceled": ("canceled",),
    }
    refused = 0
    for present, route in routes.items():
        request_id = desk.submit(
            ids["workspace_public_id"], ids["subject"], "access",
            None, actor=actor, reason=REASON,
        )
        for step in route:
            desk.advance(request_id, step, actor=actor, reason=REASON)

        for target in sorted(STATUSES):
            if target in TRANSITIONS[present]:
                continue
            with pytest.raises(ValueError, match="may not move from"):
                desk.advance(request_id, target, actor=actor, reason=REASON)
            refused += 1
            with psycopg.connect(admin_dsn) as connection:
                assert connection.execute(
                    "SELECT status FROM medawarcre.privacy_requests WHERE id=%s",
                    (request_id,),
                ).fetchone() == (present,)

    # The enumeration actually ran: 36 ordered pairs less the 7 legal ones.
    assert refused == len(STATUSES) ** 2 - sum(
        len(targets) for targets in TRANSITIONS.values()
    )
    assert refused == 29

    # A status outside the vocabulary is refused before it reaches SQL.
    request_id = desk.submit(
        ids["workspace_public_id"], ids["subject"], "access",
        None, actor=actor, reason=REASON,
    )
    with pytest.raises(ValueError, match="unsupported privacy request status"):
        desk.advance(request_id, "archived", actor=actor, reason=REASON)


def test_a_retention_action_is_written_and_linked_to_its_request(
    staffed: tuple[str, str, dict[str, str], InternalPrivacyDesk],
) -> None:
    admin_dsn, _app_dsn, ids, desk = staffed
    actor = _owner(ids)
    request_id = desk.submit(
        ids["workspace_public_id"], ids["subject"], "delete",
        None, actor=actor, reason=REASON,
    )
    desk.advance(request_id, "verified", actor=actor, reason=REASON)
    desk.advance(request_id, "in_progress", actor=actor, reason=REASON)

    retention_id = desk.record_retention_action(
        request_id, "deleted", "saved_search", str(uuid4()),
        "subject_erasure", {"rows": 3},
        actor=actor, reason=REASON,
    )
    kept = desk.record_retention_action(
        request_id, "retained", "deal", str(uuid4()),
        "legal_hold", {"basis": "contract"},
        actor=actor, reason=REASON,
    )

    actions = desk.retention_actions(request_id, actor=actor, reason=REASON)
    assert {item.id for item in actions} == {retention_id, kept}
    assert {item.action for item in actions} == {"deleted", "retained"}
    assert all(item.privacy_request_id == request_id for item in actions)
    assert all(item.subject_user_id == ids["subject"] for item in actions)
    assert all(item.workspace_id == ids["workspace_id"] for item in actions)
    assert {json.dumps(item.evidence, sort_keys=True) for item in actions} == {
        '{"rows": 3}', '{"basis": "contract"}',
    }

    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.retention_actions retention "
            "JOIN medawarcre.privacy_requests request "
            "ON request.workspace_id=retention.workspace_id "
            "AND request.id=retention.privacy_request_id "
            "WHERE request.id=%s",
            (request_id,),
        ).fetchone()[0] == 2

    # The action vocabulary is closed here as well as at the database.
    with pytest.raises(ValueError, match="unsupported retention action"):
        desk.record_retention_action(
            request_id, "shredded", "deal", str(uuid4()), "x", {},
            actor=actor, reason=REASON,
        )
    # And a retention action must name a request that exists.
    with pytest.raises(LookupError):
        desk.record_retention_action(
            str(uuid4()), "deleted", "deal", str(uuid4()), "x", {},
            actor=actor, reason=REASON,
        )


# ---------------------------------------------------------------------------
# Auditability: the row and the effect share one transaction.
# ---------------------------------------------------------------------------


def test_every_mutation_writes_exactly_one_audit_row(
    staffed: tuple[str, str, dict[str, str], InternalPrivacyDesk],
) -> None:
    admin_dsn, _app_dsn, ids, desk = staffed
    actor = _owner(ids)

    request_id = desk.submit(
        ids["workspace_public_id"], ids["subject"], "export",
        None, actor=actor, reason=REASON,
    )
    desk.advance(request_id, "verified", actor=actor, reason=REASON)
    desk.record_retention_action(
        request_id, "exported", "saved_search", str(uuid4()), "sar", {},
        actor=actor, reason=REASON,
    )
    desk.export_workspace_subject(
        ids["workspace_public_id"], ids["subject"], actor=actor, reason=REASON
    )
    desk.list_requests(ids["workspace_public_id"], actor=actor, reason=REASON)

    rows = _audit_rows(admin_dsn)
    assert [(row[0], row[1]) for row in rows] == [
        ("submit", "succeeded"),
        ("advance", "succeeded"),
        ("retain", "succeeded"),
        ("export", "succeeded"),
        ("list", "succeeded"),
    ]
    # Each row names the object it actually acted on.
    assert [row[2] for row in rows] == [
        "privacy_request", "privacy_request", "retention_action",
        "privacy_subject", "privacy_request_index",
    ]
    assert rows[0][3] == ids["subject"]
    assert rows[1][3] == request_id
    assert all(row[4] == OWNER and row[5] == REASON for row in rows)

    # Every row is linked to the workspace the action concerned.
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.staff_audit_log "
            "WHERE workspace_id=%s",
            (ids["workspace_id"],),
        ).fetchone()[0] == 5


def test_a_mutation_that_fails_leaves_no_audit_row(
    staffed: tuple[str, str, dict[str, str], InternalPrivacyDesk],
) -> None:
    """The audit row is written first, and dies with the transaction.

    ``submit`` deliberately does not pre-check membership -- the composite
    foreign key already refuses a non-member, and probing first would make this
    call a membership oracle. So a subject who is not a member of the named
    workspace fails inside the transaction, *after* the audit row was inserted.
    If the two were not one transaction, the audit row would survive an action
    that did not happen.
    """
    admin_dsn, app_dsn, ids, desk = staffed
    actor = _owner(ids)

    stranger = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name) VALUES (%s,%s,'Stranger')",
            (stranger, f"stranger-{uuid4().hex}@example.test"),
        )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        desk.submit(
            ids["workspace_public_id"], stranger, "delete",
            None, actor=actor, reason=REASON,
        )

    assert _audit_rows(admin_dsn) == []
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.privacy_requests"
        ).fetchone()[0] == 0


def test_a_mutation_whose_audit_row_cannot_be_written_does_not_happen(
    staffed: tuple[str, str, dict[str, str], InternalPrivacyDesk],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other direction: no audit, no effect.

    A privacy action that cannot be recorded must not occur, so the failure has
    to travel outward rather than being swallowed and the write proceeding.
    """
    admin_dsn, _app_dsn, ids, desk = staffed
    actor = _owner(ids)

    def unwritable_audit(self, connection, actor, reason, **_: object) -> None:
        connection.execute(
            "INSERT INTO medawarcre.staff_audit_log("
            "actor_user_id,actor_role,reason,reason_code,object_type,object_id,"
            "action,result) VALUES (%s,'emperor',%s,'privacy_request',"
            "'privacy_request','x','submit','succeeded')",
            (actor.actor_user_id, reason),
        )

    # The forgery guard on `internal_audit_insert` fires before the role CHECK
    # does, so this arrives as InsufficientPrivilege rather than
    # CheckViolation. Either way the audit insert fails inside the transaction.
    monkeypatch.setattr(InternalPrivacyDesk, "_audit", unwritable_audit)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        desk.submit(
            ids["workspace_public_id"], ids["subject"], "access",
            None, actor=actor, reason=REASON,
        )

    monkeypatch.undo()
    assert _audit_rows(admin_dsn) == []
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.privacy_requests"
        ).fetchone()[0] == 0


def test_a_reading_role_is_refused_and_the_refusal_is_recorded(
    staffed: tuple[str, str, dict[str, str], InternalPrivacyDesk],
) -> None:
    admin_dsn, _app_dsn, ids, desk = staffed
    owner, analyst = _owner(ids), _analyst(ids)
    request_id = desk.submit(
        ids["workspace_public_id"], ids["subject"], "access",
        None, actor=owner, reason=REASON,
    )

    with pytest.raises(PermissionError):
        desk.submit(
            ids["workspace_public_id"], ids["subject"], "delete",
            None, actor=analyst, reason=REASON,
        )
    with pytest.raises(PermissionError):
        desk.advance(request_id, "verified", actor=analyst, reason=REASON)
    with pytest.raises(PermissionError):
        desk.record_retention_action(
            request_id, "deleted", "deal", str(uuid4()), "x", {},
            actor=analyst, reason=REASON,
        )

    # An attempted escalation is the case you least want missing from the log.
    denied = [row for row in _audit_rows(admin_dsn) if row[1] == "denied"]
    assert [row[0] for row in denied] == ["submit", "advance", "retain"]
    assert all(row[4] == ANALYST for row in denied)

    # The reading role may still read.
    assert [
        item.id
        for item in desk.list_requests(
            ids["workspace_public_id"], actor=analyst, reason=REASON
        )
    ] == [request_id]

    # A blank reason is not a reason, whatever the role.
    for reason in ("", "   ", "no"):
        with pytest.raises(ValueError, match="stated reason"):
            desk.list_requests(
                ids["workspace_public_id"], actor=owner, reason=reason
            )


# ---------------------------------------------------------------------------
# The customer role at the database.
# ---------------------------------------------------------------------------


def test_the_customer_role_cannot_reach_another_workspaces_privacy_data(
    postgres_database: tuple[str, str, str],
) -> None:
    """Grants first, then row-level security -- both, not either.

    ``retention_actions`` carries no grant to ``medawarcre_app`` at all, so a
    policy mistake there could not open it on its own. ``privacy_requests`` is
    granted, so the policy is what has to hold, and it is checked against a
    second workspace's real row.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    subject_a, other_a, subject_b = str(uuid4()), str(uuid4()), str(uuid4())
    workspace_a = _seed_workspace(
        admin_dsn, workspace_public_id="ws_priv_a", actor_ids=(subject_a, other_a)
    )
    workspace_b = _seed_workspace(
        admin_dsn, workspace_public_id="ws_priv_b", actor_ids=(subject_b,)
    )
    ids = _seed_staff(admin_dsn)
    desk = _desk(app_dsn)
    try:
        actor = _owner(ids)
        mine = desk.submit(
            "ws_priv_a", subject_a, "access", None, actor=actor, reason=REASON
        )
        neighbour = desk.submit(
            "ws_priv_a", other_a, "access", None, actor=actor, reason=REASON
        )
        theirs = desk.submit(
            "ws_priv_b", subject_b, "delete", None, actor=actor, reason=REASON
        )
        desk.record_retention_action(
            theirs, "deleted", "deal", str(uuid4()), "erasure", {},
            actor=actor, reason=REASON,
        )
    finally:
        desk.close()

    with psycopg.connect(app_dsn, autocommit=True) as connection:
        connection.execute(
            "SELECT set_config('app.workspace_id',%s,false),"
            "set_config('app.actor_user_id',%s,false)",
            (workspace_a, subject_a),
        )
        visible = [
            str(row[0])
            for row in connection.execute(
                "SELECT id FROM medawarcre.privacy_requests"
            ).fetchall()
        ]
        assert visible == [mine]

        # Naming the other workspace's row by its exact id does not reveal it.
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.privacy_requests WHERE id=%s",
            (theirs,),
        ).fetchone()[0] == 0
        # Nor does another member's row inside the same workspace.
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.privacy_requests WHERE id=%s",
            (neighbour,),
        ).fetchone()[0] == 0

        # Claiming to be the other workspace is not a way in either: the
        # membership foreign key means the claim has to be true to select a row,
        # and the actor is still this actor.
        connection.execute(
            "SELECT set_config('app.workspace_id',%s,false)", (workspace_b,)
        )
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.privacy_requests"
        ).fetchone()[0] == 0

    # Retention evidence and the staff log are refused before any policy runs.
    with psycopg.connect(app_dsn) as connection:
        connection.execute(
            "SELECT set_config('app.workspace_id',%s,false),"
            "set_config('app.actor_user_id',%s,false)",
            (workspace_a, subject_a),
        )
        for relation in ("retention_actions", "staff_audit_log"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"SELECT * FROM medawarcre.{relation}")
            connection.rollback()


# ---------------------------------------------------------------------------
# Export.
# ---------------------------------------------------------------------------


def _seed_subject_data(
    admin_dsn: str, workspace_id: str, user_id: str, marker: str
) -> None:
    """One row in each tenant relation that actually carries a subject link."""
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.consents("
            "workspace_id,user_id,consent_type,granted,version) "
            "VALUES (%s,%s,'privacy',true,%s)",
            (workspace_id, user_id, f"v1-{marker}"),
        )
        connection.execute(
            "INSERT INTO medawarcre.saved_searches("
            "workspace_id,owner_user_id,name,query) "
            "VALUES (%s,%s,%s,jsonb_build_object('location',%s::text))",
            (workspace_id, user_id, f"search-{marker}", marker),
        )
        deal_id = str(uuid4())
        connection.execute(
            "INSERT INTO medawarcre.deals("
            "id,workspace_id,source,source_record_id,title,listing,stage,"
            "created_by_user_id,updated_by_user_id) "
            "VALUES (%s,%s,'fixture',%s,%s,"
            "jsonb_build_object('source','fixture','source_id',%s::text,"
            "'url',''),'lead',%s,%s)",
            (
                deal_id, workspace_id, f"rec-{marker}", f"deal-{marker}",
                f"rec-{marker}", user_id, user_id,
            ),
        )
        connection.execute(
            "INSERT INTO medawarcre.deal_notes("
            "workspace_id,deal_id,author_user_id,body) VALUES (%s,%s,%s,%s)",
            (workspace_id, deal_id, user_id, f"note-{marker}"),
        )


def test_export_returns_only_the_named_subject_in_the_named_workspace(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    subject, neighbour, stranger = str(uuid4()), str(uuid4()), str(uuid4())
    workspace_a = _seed_workspace(
        admin_dsn, workspace_public_id="ws_export_a",
        actor_ids=(subject, neighbour),
    )
    workspace_b = _seed_workspace(
        admin_dsn, workspace_public_id="ws_export_b", actor_ids=(stranger,)
    )
    _seed_subject_data(admin_dsn, workspace_a, subject, "mine")
    _seed_subject_data(admin_dsn, workspace_a, neighbour, "neighbour")
    _seed_subject_data(admin_dsn, workspace_b, stranger, "theirs")
    ids = _seed_staff(admin_dsn)
    desk = _desk(app_dsn)
    try:
        actor = _owner(ids)
        request_id = desk.submit(
            "ws_export_a", subject, "export", None, actor=actor, reason=REASON
        )
        desk.submit(
            "ws_export_b", stranger, "export", None, actor=actor, reason=REASON
        )

        payload = desk.export_workspace_subject(
            "ws_export_a", subject, actor=actor, reason=REASON
        )
    finally:
        desk.close()

    assert payload["workspace_public_id"] == "ws_export_a"
    assert payload["subject_user_id"] == subject
    assert set(payload) == {
        "workspace_public_id", "subject_user_id", "generated_at",
        "memberships", "consents", "saved_searches", "deals", "deal_notes",
        "privacy_requests",
    }

    assert len(payload["memberships"]) == 1
    assert payload["consents"] == [
        {
            "id": payload["consents"][0]["id"],
            "consent_type": "privacy",
            "granted": True,
            "version": "v1-mine",
            "occurred_at": payload["consents"][0]["occurred_at"],
        }
    ]
    assert [item["name"] for item in payload["saved_searches"]] == ["search-mine"]
    assert [item["title"] for item in payload["deals"]] == ["deal-mine"]
    assert [item["body"] for item in payload["deal_notes"]] == ["note-mine"]
    assert [item["id"] for item in payload["privacy_requests"]] == [request_id]

    # Nothing from the neighbour, and nothing from the other workspace.
    rendered = json.dumps(payload)
    for foreign in ("neighbour", "theirs", stranger, neighbour, workspace_b):
        assert foreign not in rendered, f"the export leaked {foreign!r}"

    # The payload is genuinely serialisable -- no datetimes or Decimals left.
    assert json.loads(rendered)["subject_user_id"] == subject
