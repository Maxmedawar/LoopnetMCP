"""Phase 5K: the internal-only combined opportunity index.

RED first. Every test here describes a requirement from
`docs/launch/PHASE_5K_INTERNAL_OPPORTUNITY_INDEX_CONTRACT.md` and fails until
the index exists.

The order is deliberate. The first three tests are the customer boundary, and
they are written first because the index is the one structure in this program
that deliberately spans tenants: if it leaks, it leaks everything at once. The
remaining tests are the retention, deduplication, conflict, filter, pagination
and deletion behaviour the contract requires.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.postgres.migrations import MigrationRunner, load_migrations

from cre_mcp.postgres.opportunity_index import (
    MAX_PAGE,
    InternalOpportunityIndex,
    OpportunityFilters,
    StaffRequest,
)


def _seed(connection: psycopg.Connection) -> dict[str, str]:
    """Two workspaces, two users, one staff analyst, one owner."""
    ids = {
        "workspace_a": str(uuid4()),
        "workspace_b": str(uuid4()),
        "user_a": str(uuid4()),
        "user_b": str(uuid4()),
        "analyst": str(uuid4()),
        "owner": str(uuid4()),
    }
    connection.execute("SET ROLE medawarcre_migration")
    connection.execute(
        "INSERT INTO medawarcre.users(id,email,name) VALUES "
        "(%s,'a@example.test','A'),(%s,'b@example.test','B'),"
        "(%s,'analyst@example.test','Analyst'),(%s,'owner@example.test','Owner')",
        (ids["user_a"], ids["user_b"], ids["analyst"], ids["owner"]),
    )
    connection.execute(
        "INSERT INTO medawarcre.workspaces(id,public_id,name) VALUES "
        "(%s,'ws_a','Workspace A'),(%s,'ws_b','Workspace B')",
        (ids["workspace_a"], ids["workspace_b"]),
    )
    connection.execute(
        "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
        "VALUES (%s,%s,'owner','active'),(%s,%s,'owner','active')",
        (ids["workspace_a"], ids["user_a"], ids["workspace_b"], ids["user_b"]),
    )
    connection.execute(
        "INSERT INTO medawarcre.staff_roles(user_id,role,active) VALUES "
        "(%s,'read_only_analyst',true),(%s,'owner',true)",
        (ids["analyst"], ids["owner"]),
    )
    return ids


def _deal(
    connection: psycopg.Connection,
    workspace: str,
    user: str,
    *,
    source_record_id: str,
    address: str,
    city: str,
    state: str,
    zip_code: str,
    stage: str = "lead",
    score: float | None = 82.5,
    property_type: str | None = None,
) -> str:
    deal_id = str(uuid4())
    connection.execute("SET ROLE medawarcre_migration")
    connection.execute(
        "INSERT INTO medawarcre.deals("
        "id,workspace_id,source,source_record_id,title,listing,stage,score,"
        "score_version,created_by_user_id,updated_by_user_id) "
        "VALUES (%s,%s,'fixture',%s,'A property',"
        "jsonb_build_object('source','fixture','source_id',%s::text,"
        "'name','A property','address',%s::text,'city',%s::text,"
        "'state',%s::text,'zip_code',%s::text,'url','',"
        "'property_type',%s::text),"
        "%s::text,%s::numeric,'score-v3',%s::uuid,%s::uuid)",
        (
            deal_id, workspace, source_record_id, source_record_id,
            address, city, state, zip_code, property_type,
            stage, score, user, user,
        ),
    )
    return deal_id


# --------------------------------------------------------------------------
# The customer boundary. These three come first on purpose.
# --------------------------------------------------------------------------


def test_the_customer_role_holds_no_privilege_on_any_index_relation(
    postgres_database: tuple[str, str, str],
) -> None:
    """A grant boundary before it is a policy boundary.

    `medawarcre_app` must be refused by PostgreSQL before row-level security is
    consulted, so a policy mistake cannot open the index on its own.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    with psycopg.connect(app_dsn) as connection:
        connection.execute(
            "SELECT set_config('app.workspace_id',%s,true),"
            "set_config('app.actor_user_id',%s,true)",
            (ids["workspace_a"], ids["user_a"]),
        )
        for relation in (
            "internal_opportunities",
            "internal_opportunity_sources",
            "internal_opportunity_reviews",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"SELECT * FROM medawarcre.{relation}")
            connection.rollback()
            connection.execute(
                "SELECT set_config('app.workspace_id',%s,true),"
                "set_config('app.actor_user_id',%s,true)",
                (ids["workspace_a"], ids["user_a"]),
            )


def test_the_index_is_not_reachable_from_a_hosted_request_scope() -> None:
    """It must not be a field on `HostedRequestRepositories`.

    Everything on that bundle is one capability away from a customer, because
    tool code reaches it through `current_hosted_request_repositories()`.
    """
    from cre_mcp.postgres.domains import (
        AdmittedRequestUnavailable,
        HostedRequestRepositories,
    )

    fields = {item.name for item in HostedRequestRepositories.__dataclass_fields__.values()}

    assert "opportunity_index" not in fields
    assert not any("opportunit" in name for name in fields)

    marker = object()
    bundle = HostedRequestRepositories.__new__(HostedRequestRepositories)
    for name in fields:
        object.__setattr__(bundle, name, marker)
    with pytest.raises(AdmittedRequestUnavailable):
        bundle.require("opportunity_index")


def test_no_customer_capability_can_name_the_index() -> None:
    """No module outside the internal path may import the index module.

    Written carefully, because the obvious version of this test is vacuous.
    Nothing imports the index yet, so `offenders` is empty and
    `all(... for ... in offenders)` passes without inspecting anything — the
    same shape as an `importorskip` that reports a green skip. So the detector
    is given a positive control it must flag, and the scan is required to have
    actually read the tree.
    """
    import ast
    from pathlib import Path

    def importers_of_index(text: str) -> bool:
        """True when this module source imports the index by any spelling."""
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [
                    getattr(node, "module", "") or "",
                    *[alias.name for alias in node.names],
                ]
                if any("opportunity_index" in name for name in names):
                    return True
        return False

    # Positive control: the detector must flag each spelling an importer could
    # realistically use. Without this, an empty offender list proves nothing.
    for spelling in (
        "from cre_mcp.postgres.opportunity_index import InternalOpportunityIndex",
        "import cre_mcp.postgres.opportunity_index",
        "from cre_mcp.postgres import opportunity_index",
        "import cre_mcp.postgres.opportunity_index as oi",
    ):
        assert importers_of_index(spelling), f"detector missed: {spelling}"
    # Negative control: a mention that is not an import must not be flagged.
    assert not importers_of_index('X = "opportunity_index"')

    source_root = Path(__file__).resolve().parents[2] / "src"
    scanned = 0
    offenders: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        if path.name == "opportunity_index.py":
            continue
        scanned += 1
        text = path.read_text()
        if "opportunity_index" not in text:
            continue
        if importers_of_index(text):
            offenders.append(str(path.relative_to(source_root)))

    # The scan must have actually read the source tree. A mistyped root would
    # otherwise yield zero offenders and a green test.
    assert scanned > 200, f"the scan only visited {scanned} modules"

    # Only the internal operations path may import it, and no customer tool.
    assert all(
        offender.startswith("cre_mcp/platform/") for offender in offenders
    ), f"the index is imported outside the internal path: {offenders}"


# --------------------------------------------------------------------------
# Staff access: role-limited, reason-coded, timestamped, audited.
# --------------------------------------------------------------------------


def test_a_read_without_a_reason_is_refused_and_writes_need_owner_or_admin(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )

    with pytest.raises(ValueError):
        StaffRequest(
            actor_user_id=ids["analyst"],
            role="read_only_analyst",
            reason_code="duplicate_review",
            reason="  ",
        )
    with pytest.raises(ValueError):
        StaffRequest(
            actor_user_id=ids["analyst"],
            role="not_a_role",
            reason_code="duplicate_review",
            reason="checking a duplicate",
        )

    analyst = StaffRequest(
        actor_user_id=ids["analyst"],
        role="read_only_analyst",
        reason_code="duplicate_review",
        reason="checking a duplicate",
    )
    # A read-only analyst may read and may not write.
    index.list_opportunities(analyst, limit=10)
    with pytest.raises(PermissionError):
        index.record_review(
            analyst, opportunity_id=str(uuid4()), verdict="dismiss"
        )


def test_every_staff_read_writes_exactly_one_audit_row_in_the_same_transaction(
    postgres_database: tuple[str, str, str],
) -> None:
    """A read whose audit row cannot be written must not return data."""
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    analyst = StaffRequest(
        actor_user_id=ids["analyst"],
        role="read_only_analyst",
        reason_code="pipeline_review",
        reason="weekly pipeline review",
    )

    index.list_opportunities(analyst, limit=10)

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        rows = connection.execute(
            "SELECT actor_user_id,actor_role,reason,reason_code,action,result "
            "FROM medawarcre.staff_audit_log ORDER BY occurred_at"
        ).fetchall()

    assert len(rows) == 1
    assert str(rows[0][0]) == ids["analyst"]
    assert rows[0][1] == "read_only_analyst"
    assert rows[0][3] == "pipeline_review"
    assert rows[0][5] in {"allowed", "succeeded"}


# --------------------------------------------------------------------------
# Aggregation, deduplication and provenance.
# --------------------------------------------------------------------------


def test_one_property_in_two_workspaces_becomes_one_entry_with_two_sources(
    postgres_database: tuple[str, str, str],
) -> None:
    """Deduplicate without erasing where each observation came from."""
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="analyzing", score=82.5,
        )
        # Same property, different workspace, differently spelled.
        _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-9", address="100 MAIN STREET", city="dallas",
            state="Texas", zip_code="75201-4444", stage="passed", score=41.0,
        )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="build the combined index",
    )
    index.ingest_workspace(owner, ids["workspace_a"])
    index.ingest_workspace(owner, ids["workspace_b"])

    page = index.list_opportunities(owner, limit=10)

    assert len(page.entries) == 1
    entry = page.entries[0]
    assert len(entry.sources) == 2
    by_workspace = {source.workspace_id: source for source in entry.sources}
    assert set(by_workspace) == {ids["workspace_a"], ids["workspace_b"]}

    # Every retention requirement, per contributing observation.
    for workspace, source in by_workspace.items():
        assert source.source_user_id
        assert source.source_deal_id
        assert source.source or source.source_record_id
        assert source.observed_property_identity
        assert source.score_version == "score-v3"
        assert source.access_class in {"private", "licensed", "public"}
        assert source.first_observed_at and source.last_observed_at

    # Neither workspace's score or stage was averaged away.
    assert {source.score for source in entry.sources} == {82.5, 41.0}
    assert {source.stage for source in entry.sources} == {"analyzing", "passed"}


def test_an_ambiguous_property_identity_is_rejected_and_counted(
    postgres_database: tuple[str, str, str],
) -> None:
    """Fail closed on identity the pinned authority cannot resolve.

    `Burbank, CA` does not converge to one Census place without a county or ZIP,
    so it must not silently become an entry.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="ambiguous", address="1 Elm St", city="Burbank",
            state="CA", zip_code="",
        )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="build the combined index",
    )

    summary = index.ingest_workspace(owner, ids["workspace_a"])

    assert summary.admitted == 0
    assert summary.rejected == 1
    assert index.list_opportunities(owner, limit=10).entries == ()


def test_conflicting_outcomes_are_reported_with_attribution_not_resolved(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        deal_a = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="closing",
        )
        deal_b = _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-9", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="passed",
        )
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.deal_outcomes("
            "workspace_id,deal_id,closed,purchase_price) "
            "VALUES (%s,%s,true,1000000),(%s,%s,false,NULL)",
            (ids["workspace_a"], deal_a, ids["workspace_b"], deal_b),
        )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="build the combined index",
    )
    index.ingest_workspace(owner, ids["workspace_a"])
    index.ingest_workspace(owner, ids["workspace_b"])

    entry = index.list_opportunities(owner, limit=10).entries[0]
    kinds = {conflict.kind for conflict in entry.conflicts}

    assert "outcome" in kinds
    outcome = next(c for c in entry.conflicts if c.kind == "outcome")
    assert {position.workspace_id for position in outcome.positions} == {
        ids["workspace_a"], ids["workspace_b"]
    }
    # The exact users, not merely non-empty ones. A reviewer substituted
    # workspace_id for source_user_id and this assertion — a truthiness check —
    # stayed green at every scope, so "every side attributed" was pinned as
    # "attributed to something" rather than "attributed to the right person".
    assert {position.source_user_id for position in outcome.positions} == {
        ids["user_a"], ids["user_b"]
    }
    assert all(
        position.source_user_id != position.workspace_id
        for position in outcome.positions
    )
    # The index states the disagreement; it does not pick a winner.
    assert not hasattr(entry, "resolved_outcome")


# --------------------------------------------------------------------------
# Query surface and deletion.
# --------------------------------------------------------------------------


def test_pagination_is_keyset_stable_and_filters_narrow_by_every_facet(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for index_number in range(7):
            _deal(
                connection, ids["workspace_a"], ids["user_a"],
                source_record_id=f"a-{index_number}",
                address=f"{100 + index_number} Main St", city="Dallas",
                state="TX", zip_code="75201",
                stage="analyzing" if index_number % 2 else "lead",
                score=50.0 + index_number,
            )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="pipeline_review", reason="paging the index",
    )
    index.ingest_workspace(owner, ids["workspace_a"])

    first = index.list_opportunities(owner, limit=3)
    second = index.list_opportunities(owner, limit=3, cursor=first.next_cursor)
    third = index.list_opportunities(owner, limit=3, cursor=second.next_cursor)

    seen = [e.opportunity_id for page in (first, second, third) for e in page.entries]
    assert len(seen) == 7
    assert len(set(seen)) == 7, "keyset pagination repeated or skipped an entry"
    assert third.next_cursor is None

    narrowed = index.list_opportunities(
        owner,
        filters=OpportunityFilters(
            market="dallas, tx",
            stage="analyzing",
            min_score=52.0,
            workspace_id=ids["workspace_a"],
            source_user_id=ids["user_a"],
        ),
        limit=50,
    )
    assert 0 < len(narrowed.entries) < 7
    for entry in narrowed.entries:
        assert any(source.stage == "analyzing" for source in entry.sources)


def test_each_declared_filter_facet_narrows_on_its_own(
    postgres_database: tuple[str, str, str],
) -> None:
    """Every contract filter is pinned separately, by an exact expected set.

    The conjunction above does not do this. Measured: making any one of
    ``market``, ``property_type``, ``min_score``, ``max_score``, ``outcome``,
    ``source_user_id`` or ``workspace_id`` silently ignored left the whole
    focused suite green — only ``stage`` was pinned. A filter that is quietly
    dropped returns rows the caller believes it excluded, which for a
    cross-tenant staff index means showing another workspace's observation to
    someone who asked not to see it. So each facet gets its own exact-set
    assertion, and an ignored predicate widens the set and fails.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        # Three observations chosen so that every facet splits them differently.
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", property_type="office",
            stage="lead", score=30.0,
        )
        closed = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-2", address="200 Main St", city="Dallas",
            state="TX", zip_code="75201", property_type="retail",
            stage="analyzing", score=90.0,
        )
        bad = _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-1", address="300 Congress Ave", city="Austin",
            state="TX", zip_code="78701", property_type="office",
            stage="closing", score=60.0,
        )
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.deal_outcomes("
            "workspace_id,deal_id,closed,went_bad,purchase_price) "
            "VALUES (%s,%s,true,false,1000000),(%s,%s,false,true,NULL)",
            (ids["workspace_a"], closed, ids["workspace_b"], bad),
        )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="pipeline_review", reason="pinning each filter facet",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])

        def addresses(**filters: object) -> set[str]:
            page = index.list_opportunities(
                owner, filters=OpportunityFilters(**filters), limit=50
            )
            return {entry.property_identity["address"] for entry in page.entries}

        every = {"100 MAIN ST", "200 MAIN ST", "300 CONGRESS AVE"}
        assert addresses() == every, "the fixture itself must be complete first"

        assert addresses(market="Dallas, TX") == {"100 MAIN ST", "200 MAIN ST"}
        assert addresses(property_type="office") == {
            "100 MAIN ST", "300 CONGRESS AVE"
        }
        assert addresses(min_score=60.0) == {"200 MAIN ST", "300 CONGRESS AVE"}
        assert addresses(max_score=60.0) == {"100 MAIN ST", "300 CONGRESS AVE"}
        assert addresses(stage="closing") == {"300 CONGRESS AVE"}
        assert addresses(outcome="closed") == {"200 MAIN ST"}
        assert addresses(source_user_id=ids["user_b"]) == {"300 CONGRESS AVE"}
        assert addresses(workspace_id=ids["workspace_a"]) == {
            "100 MAIN ST", "200 MAIN ST"
        }
    finally:
        index.close()


def test_deleting_the_tenant_record_removes_its_contribution(
    postgres_database: tuple[str, str, str],
) -> None:
    """The index is derived data; tenant deletion propagates into it."""
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        deal_a = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )
        _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-9", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="privacy_request", reason="subject deletion",
    )
    index.ingest_workspace(owner, ids["workspace_a"])
    index.ingest_workspace(owner, ids["workspace_b"])
    assert len(index.list_opportunities(owner, limit=10).entries[0].sources) == 2

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "DELETE FROM medawarcre.deals WHERE workspace_id=%s AND id=%s",
            (ids["workspace_a"], deal_a),
        )

    remaining = index.list_opportunities(owner, limit=10).entries[0]
    assert len(remaining.sources) == 1
    assert remaining.sources[0].workspace_id == ids["workspace_b"]

    # Workspace deletion is a different story. Two foreign keys to `workspaces`
    # do not cascade — `staff_audit_log` and `access_decision_audit` — so a
    # workspace referenced by either cannot be deleted. Audit immutability and
    # tenant erasure conflict, and audit wins silently. This names the exact
    # constraint rather than accepting any ForeignKeyViolation, because an
    # earlier version accepted a bare violation and so could not have caught the
    # record's claim about *which* key was responsible being wrong.
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
            connection.execute(
                "DELETE FROM medawarcre.workspaces WHERE id=%s",
                (ids["workspace_a"],),
            )
        assert refused.value.diag.constraint_name in {
            "staff_audit_log_workspace_id_fkey",
            "access_decision_audit_workspace_id_fkey",
        }

    # And the entry whose last observation is gone is archived by trigger, so a
    # property address does not outlive the tenant record it came from.
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "DELETE FROM medawarcre.deals WHERE workspace_id=%s",
            (ids["workspace_b"],),
        )
    archived = index.list_opportunities(owner, limit=10)
    assert archived.entries == (), "a sourceless entry stayed in the listing"
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        statuses = [
            row[0]
            for row in connection.execute(
                "SELECT status FROM medawarcre.internal_opportunities"
            )
        ]
    assert statuses == ["archived"]


def test_review_history_is_append_only_and_survives_tenant_deletion(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="quality_audit", reason="reviewing a duplicate",
    )
    index.ingest_workspace(owner, ids["workspace_a"])
    entry = index.list_opportunities(owner, limit=10).entries[0]

    index.record_review(owner, opportunity_id=entry.opportunity_id, verdict="promote")
    detail = index.get_opportunity(owner, entry.opportunity_id)

    assert len(detail.reviews) == 1
    assert detail.reviews[0].verdict == "promote"
    assert detail.reviews[0].reviewer_user_id == ids["owner"]
    assert detail.reviews[0].reason_code == "quality_audit"

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE medawarcre.internal_opportunity_reviews SET verdict='dismiss'"
            )


def test_a_corrected_address_leaves_no_sourceless_entry_behind(
    postgres_database: tuple[str, str, str],
) -> None:
    """Re-binding moves an observation; it must not strand its old entry.

    Two reviewers found this: the re-bind is an UPDATE, and the archival trigger
    fired only `AFTER DELETE`, so correcting the address of a property's only
    observation left an `active` entry with zero sources — carrying a tenant's
    normalized address in a cross-tenant table nobody contributed to, and
    surviving deletion of every record it came from.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        deal_id = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="build the combined index",
    )
    index.ingest_workspace(owner, ids["workspace_a"])

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "UPDATE medawarcre.deals SET listing = "
            "listing || jsonb_build_object('address','250 Elm St') "
            "WHERE workspace_id=%s AND id=%s",
            (ids["workspace_a"], deal_id),
        )
    index.ingest_workspace(owner, ids["workspace_a"])

    listed = index.list_opportunities(owner, limit=10)
    assert [entry.property_identity["address"] for entry in listed.entries] == [
        "250 ELM ST"
    ], "the vacated entry is still in the default listing"
    assert all(entry.sources for entry in listed.entries)

    # And re-observing the original address brings it back, rather than the
    # archival being a one-way door that hides a live tenant record.
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "UPDATE medawarcre.deals SET listing = "
            "listing || jsonb_build_object('address','100 Main St') "
            "WHERE workspace_id=%s AND id=%s",
            (ids["workspace_a"], deal_id),
        )
    index.ingest_workspace(owner, ids["workspace_a"])

    restored = index.list_opportunities(owner, limit=10)
    assert [entry.property_identity["address"] for entry in restored.entries] == [
        "100 MAIN ST"
    ]


def test_a_merged_entry_is_archived_when_its_last_observation_goes(
    postgres_database: tuple[str, str, str],
) -> None:
    """The trigger narrowed to `status='active'`; the listing admits `merged`.

    So a merged entry whose tenant record was deleted stayed visible with zero
    contributors. `merge_opportunities` is a public method, so this was
    reachable.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for index_number, address in enumerate(("100 Main St", "200 Main St")):
            _deal(
                connection, ids["workspace_a"], ids["user_a"],
                source_record_id=f"a-{index_number}", address=address,
                city="Dallas", state="TX", zip_code="75201",
            )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="duplicate_review", reason="merging a duplicate",
    )
    index.ingest_workspace(owner, ids["workspace_a"])
    entries = index.list_opportunities(owner, limit=10).entries
    assert len(entries) == 2
    index.merge_opportunities(
        owner,
        opportunity_id=entries[0].opportunity_id,
        into_opportunity_id=entries[1].opportunity_id,
    )

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "DELETE FROM medawarcre.deals WHERE workspace_id=%s",
            (ids["workspace_a"],),
        )

    assert index.list_opportunities(owner, limit=10).entries == ()
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        statuses = sorted(
            row[0]
            for row in connection.execute(
                "SELECT status FROM medawarcre.internal_opportunities"
            )
        )
    assert statuses == ["archived", "archived"]


def test_an_observation_with_no_attributable_user_is_rejected(
    postgres_database: tuple[str, str, str],
) -> None:
    """`source_user_id` is nullable in the schema, so this guard is the only one.

    The record claimed it was pinned; a reviewer deleted `or created_by is None`
    and the whole PostgreSQL suite stayed green. `deals.created_by_user_id` is
    nullable, so a row predating the 0008 attribution upgrade would otherwise be
    admitted with a null source user — exactly the unattributable entry the
    contract says must be refused.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        deal_id = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "UPDATE medawarcre.deals SET created_by_user_id=NULL "
            "WHERE workspace_id=%s AND id=%s",
            (ids["workspace_a"], deal_id),
        )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="build the combined index",
    )

    summary = index.ingest_workspace(owner, ids["workspace_a"])

    assert summary.admitted == 0
    assert summary.rejected == 1
    assert index.list_opportunities(owner, limit=10).entries == ()


def test_a_merged_duplicate_survives_deletion_and_re_observation(
    postgres_database: tuple[str, str, str],
) -> None:
    """The merge link, archival and re-observation must not fight each other.

    Two reviewers found this independently. Archival keeps `merged_into` (the
    contract requires duplicate relationships be retained), and re-observation
    lifted `archived` back to `active` — producing `active` + a link, which the
    merge constraint forbids. The CHECK aborted the whole `ingest_workspace`
    transaction, so **no** deal in that workspace landed, and because any
    workspace observing that address hits the same row it was a cross-tenant
    denial with no public method to clear the link.

    Also pinned here: merging an entry that is already archived must not
    resurrect it into the staff listing with zero sources.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        first = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-2", address="200 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="duplicate_review", reason="merging a duplicate",
    )
    index.ingest_workspace(owner, ids["workspace_a"])
    by_address = {
        entry.property_identity["address"]: entry
        for entry in index.list_opportunities(owner, limit=10).entries
    }
    index.merge_opportunities(
        owner,
        opportunity_id=by_address["100 MAIN ST"].opportunity_id,
        into_opportunity_id=by_address["200 MAIN ST"].opportunity_id,
    )

    # Deleting the merged entry's last observation archives it, link retained.
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "DELETE FROM medawarcre.deals WHERE workspace_id=%s AND id=%s",
            (ids["workspace_a"], first),
        )

    # Re-observing that address must not abort the ingest, and must not revive
    # a merged duplicate as a live entry.
    with psycopg.connect(admin_dsn) as connection:
        _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )
        _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-2", address="900 Elm St", city="Dallas",
            state="TX", zip_code="75201",
        )

    summary = index.ingest_workspace(owner, ids["workspace_b"])

    assert summary.admitted == 2, "an unrelated workspace was denied ingestion"
    listed = {
        entry.property_identity["address"]
        for entry in index.list_opportunities(owner, limit=20).entries
    }
    assert "900 ELM ST" in listed
    assert "100 MAIN ST" not in listed, "a merged duplicate was revived"


def test_merging_a_missing_entry_is_refused_rather_than_audited_as_success(
    postgres_database: tuple[str, str, str],
) -> None:
    """A no-op that writes `result='succeeded'` makes the audit trail unreliable."""
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="duplicate_review", reason="merging a duplicate",
    )
    index.ingest_workspace(owner, ids["workspace_a"])
    real = index.list_opportunities(owner, limit=10).entries[0].opportunity_id

    with pytest.raises(LookupError):
        index.merge_opportunities(
            owner,
            opportunity_id="00000000-0000-0000-0000-000000000002",
            into_opportunity_id=real,
        )

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        merges = connection.execute(
            "SELECT result, count(*) FROM medawarcre.staff_audit_log "
            "WHERE action='merge' GROUP BY result"
        ).fetchall()
    # Refused, and recorded as refused. The earlier version of this test asked
    # for *no* audit row, which made a staff member probing for the existence of
    # an entry untraceable — the refusal is exactly what should be logged.
    assert merges == [("failed", 1)], (
        f"a merge that changed nothing was audited as {merges!r}"
    )


def test_the_keyset_index_matches_the_order_the_listing_uses() -> None:
    """A leading `status` column cannot serve the trailing ORDER BY.

    The query has no equality predicate on `status`, so btree could not deliver
    `created_at DESC, id DESC` and every page was a sequential scan plus sort —
    while the record claimed the index had been fixed. Pinned structurally
    because a plan assertion is brittle across planner versions and row counts.
    """
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[2]
        / "src" / "cre_mcp" / "postgres" / "sql"
        / "0009_internal_opportunity_index.sql"
    ).read_text()

    assert (
        "CREATE INDEX internal_opportunities_keyset_idx\n"
        "    ON medawarcre.internal_opportunities (created_at DESC, id DESC);"
    ) in sql


# --------------------------------------------------------------------------
# Round four. Every test below pins a defect two independent reviewers
# measured on the frozen candidate.
# --------------------------------------------------------------------------


def _index_for(app_dsn: str) -> InternalOpportunityIndex:
    return InternalOpportunityIndex.for_dsn(
        app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")
    )


def test_a_merge_cycle_cannot_be_constructed_and_a_merge_can_be_undone(
    postgres_database: tuple[str, str, str],
) -> None:
    """A→B then B→A used to hide both entries from staff permanently.

    Re-observation only lifts entries whose merge link is NULL and nothing ever
    cleared that link, so both entries left every default listing for good — and
    a third, uninvolved workspace that later observed the property was told
    `admitted=1` while its observation landed under an invisible entry.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-2", address="200 Elm St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="duplicate_review", reason="pinning the cycle",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        by_address = {
            entry.property_identity["address"]: entry.opportunity_id
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        a, b = by_address["100 MAIN ST"], by_address["200 ELM ST"]

        index.merge_opportunities(owner, opportunity_id=a, into_opportunity_id=b)

        # The closing half of the cycle must be refused, by name.
        with pytest.raises(ValueError, match="itself merged"):
            index.merge_opportunities(owner, opportunity_id=b, into_opportunity_id=a)

        listed = {
            entry.property_identity["address"]
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        assert listed == {"200 ELM ST"}, "the canonical entry must stay visible"

        # And the merge is reversible, so a wrong duplicate call is recoverable.
        index.unmerge_opportunity(owner, opportunity_id=a)
        restored = {
            entry.property_identity["address"]
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        assert restored == {"100 MAIN ST", "200 ELM ST"}

        with pytest.raises(LookupError):
            index.unmerge_opportunity(owner, opportunity_id=b)
    finally:
        index.close()


def test_the_database_refuses_a_merge_cycle_even_without_the_repository(
    postgres_database: tuple[str, str, str],
) -> None:
    """The repository check is convenience; the trigger is the guarantee."""
    admin_dsn, migration_dsn, _app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    first, second = str(uuid4()), str(uuid4())
    # autocommit, so a refused statement does not discard the fixture rows the
    # next assertion depends on.
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        for identifier, key in ((first, "k-1"), (second, "k-2")):
            connection.execute(
                "INSERT INTO medawarcre.internal_opportunities("
                "id,canonical_key,title,status,property_identity,normalized_facts) "
                "VALUES (%s,%s,'t','active','{}'::jsonb,'{}'::jsonb)",
                (identifier, key),
            )

        # A target that does not exist at all.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "UPDATE medawarcre.internal_opportunities "
                "SET status='merged', merged_into_opportunity_id=%s WHERE id=%s",
                (str(uuid4()), first),
            )

        connection.execute(
            "UPDATE medawarcre.internal_opportunities "
            "SET status='merged', merged_into_opportunity_id=%s WHERE id=%s",
            (second, first),
        )
        # ...and now the closing half of the cycle, straight at the database.
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE medawarcre.internal_opportunities "
                "SET status='merged', merged_into_opportunity_id=%s WHERE id=%s",
                (first, second),
            )
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.internal_opportunities "
            "WHERE merged_into_opportunity_id IS NOT NULL"
        ).fetchone()[0] == 1


def test_a_tenant_string_cannot_abort_the_whole_workspace_ingest(
    postgres_database: tuple[str, str, str],
) -> None:
    """One deal's `property_type` used to take down the entire ingest.

    `internal_opportunities_property_type_check` bounds the column, ingestion is
    one transaction per workspace, and nothing validated the tenant-supplied
    value — so an empty string from an ordinary provider scrape aborted every
    other deal in that workspace, permanently, with no audit row at all.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for number, property_type in enumerate(
            ("", "  Office  ", "x" * 200, "Retail")
        ):
            _deal(
                connection, ids["workspace_a"], ids["user_a"],
                source_record_id=f"a-{number}",
                address=f"{100 + number} Main St", city="Dallas",
                state="TX", zip_code="75201", property_type=property_type,
            )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the poison",
    )
    try:
        summary = index.ingest_workspace(owner, ids["workspace_a"])

        # Blank and untrimmed are normalized; only the over-long one is refused,
        # and it is counted rather than silently truncated.
        assert summary.admitted == 3
        assert summary.rejected == 1
        assert any("128" in reason for reason in summary.rejections)

        entries = {
            entry.property_identity["address"]: entry
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        assert set(entries) == {"100 MAIN ST", "101 MAIN ST", "103 MAIN ST"}
        blank = entries["100 MAIN ST"].sources[0]
        assert blank.observed_property_type is None
        assert entries["101 MAIN ST"].sources[0].observed_property_type == "Office"
    finally:
        index.close()


def test_a_failed_ingest_still_records_that_staff_attempted_it(
    postgres_database: tuple[str, str, str],
) -> None:
    """A rolled-back transaction takes its own audit row with it."""
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="ingesting a workspace that is gone",
    )
    try:
        with pytest.raises(LookupError):
            index.ingest_workspace(owner, str(uuid4()))
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        # No object_type filter: an `ingest` row now names `workspace`, which
        # is what its object_id refers to.
        rows = connection.execute(
            "SELECT action, result FROM medawarcre.staff_audit_log"
        ).fetchall()
    assert ("ingest", "failed") in rows


def test_the_property_type_filter_sees_every_workspaces_answer(
    postgres_database: tuple[str, str, str],
) -> None:
    """The filter used to read one workspace's label off the shared row.

    Two workspaces can call the same building different things. Filtering the
    canonical row — written by whichever workspace observed it first and never
    refreshed — hid the second workspace's answer on the one structure in this
    program built to combine tenants.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", property_type="office",
        )
        _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", property_type="industrial",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the shared facet",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])

        def addresses(**filters: object) -> set[str]:
            page = index.list_opportunities(
                owner, filters=OpportunityFilters(**filters), limit=20
            )
            return {entry.property_identity["address"] for entry in page.entries}

        assert addresses() == {"100 MAIN ST"}
        assert addresses(property_type="office") == {"100 MAIN ST"}
        assert addresses(property_type="industrial") == {"100 MAIN ST"}, (
            "the second workspace's declared property type was invisible"
        )

        entry = index.list_opportunities(owner, limit=10).entries[0]
        conflict = next(c for c in entry.conflicts if c.kind == "property_type")
        assert {position.value for position in conflict.positions} == {
            "office", "industrial"
        }
        assert {position.workspace_id for position in conflict.positions} == {
            ids["workspace_a"], ids["workspace_b"]
        }
    finally:
        index.close()


def test_the_shared_entry_carries_no_tenant_free_text(
    postgres_database: tuple[str, str, str],
) -> None:
    """`internal_opportunities` outlives any one workspace, so it holds none.

    A reviewer deleted every source record and read the tenant's own deal title
    back out of the archived entry. The label is derived from the normalized
    address now; the tenant's words stay on source rows, which cascade away.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    secret = "Confidential off-market assemblage for Acme Holdings"
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        deal = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="700 Willow St", city="Sacramento",
            state="CA", zip_code="95814",
        )
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "UPDATE medawarcre.deals SET title=%s WHERE id=%s", (secret, deal)
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning tenant text",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        entry = index.list_opportunities(owner, limit=10).entries[0]
        assert secret not in entry.title
        assert entry.title == "700 Willow St, Sacramento, CA"
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "DELETE FROM medawarcre.deals WHERE workspace_id=%s",
            (ids["workspace_a"],),
        )
        surviving = connection.execute(
            "SELECT title::text || ' ' || property_identity::text "
            "FROM medawarcre.internal_opportunities"
        ).fetchall()
    assert surviving, "the archived entry should still exist"
    assert all(secret not in row[0] for row in surviving)


def test_offboarding_a_member_is_not_blocked_by_having_been_ingested(
    postgres_database: tuple[str, str, str],
) -> None:
    """0008 made the membership keys deferrable; 0009's must match.

    An immediate key here aborted the same offboarding transaction 0008 was
    designed to allow — but only for workspaces staff had ingested, so tenant
    deletion succeeded or failed depending on whether the index had run.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning offboarding",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "DELETE FROM medawarcre.memberships "
            "WHERE workspace_id=%s AND user_id=%s",
            (ids["workspace_a"], ids["user_a"]),
        )
        connection.execute(
            "DELETE FROM medawarcre.deals WHERE workspace_id=%s",
            (ids["workspace_a"],),
        )
        connection.commit()

    with psycopg.connect(admin_dsn) as connection:
        remaining = connection.execute(
            "SELECT count(*) FROM medawarcre.internal_opportunity_sources"
        ).fetchone()[0]
    assert remaining == 0


def test_filter_values_are_validated_before_they_reach_sql(
    postgres_database: tuple[str, str, str],
) -> None:
    """Being a frozen dataclass checks the name; it never checked the value."""
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    for kwargs in (
        {"workspace_id": "not-a-uuid"},
        {"source_user_id": "not-a-uuid"},
        {"min_score": "abc"},
        {"max_score": "abc"},
        {"market": 7},
        {"include_archived": "yes"},
    ):
        with pytest.raises(ValueError):
            OpportunityFilters(**kwargs)

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="pipeline_review", reason="reading an absent workspace",
    )
    try:
        # A workspace that does not exist is an empty page, not a crash — and
        # not an existence oracle built out of the audit row's foreign key.
        page = index.list_opportunities(
            owner,
            filters=OpportunityFilters(workspace_id=str(uuid4())),
            limit=10,
        )
        assert page.entries == ()
        with pytest.raises(LookupError):
            index.record_review(
                owner, opportunity_id=str(uuid4()), verdict="dismiss"
            )
        with pytest.raises(LookupError):
            index.merge_opportunities(
                owner,
                opportunity_id=str(uuid4()),
                into_opportunity_id=str(uuid4()),
            )
    finally:
        index.close()


def test_two_workspaces_ingesting_the_same_properties_do_not_deadlock(
    postgres_database: tuple[str, str, str],
) -> None:
    """Each workspace used to take the shared row locks in its own deal order.

    A reviewer measured deadlocks in 6 of 8 concurrent trials, with the loser's
    entire ingest aborting — one tenant's ingest destroyed by another's.
    Planning in canonical-key order gives the contended rows a total order.
    """
    import threading

    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    addresses = [f"{100 + n} Main St" for n in range(6)]
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for workspace, user, tag in (
            (ids["workspace_a"], ids["user_a"], "a"),
            (ids["workspace_b"], ids["user_b"], "b"),
        ):
            for number, address in enumerate(addresses):
                _deal(
                    connection, workspace, user,
                    source_record_id=f"{tag}-{number}", address=address,
                    city="Dallas", state="TX", zip_code="75201",
                )

    failures: list[BaseException] = []

    def ingest(workspace: str) -> None:
        index = _index_for(app_dsn)
        request = StaffRequest(
            actor_user_id=ids["owner"], role="owner",
            reason_code="ingestion", reason="concurrent ingest",
        )
        try:
            index.ingest_workspace(request, workspace)
        except BaseException as error:  # noqa: BLE001 - recorded, then asserted
            failures.append(error)
        finally:
            index.close()

    for _attempt in range(4):
        threads = [
            threading.Thread(target=ingest, args=(ids["workspace_a"],)),
            threading.Thread(target=ingest, args=(ids["workspace_b"],)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert not failures, f"concurrent ingest failed: {failures!r}"

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="pipeline_review", reason="checking the merged result",
    )
    try:
        entries = index.list_opportunities(owner, limit=50).entries
    finally:
        index.close()
    assert len(entries) == len(addresses)
    assert all(len(entry.sources) == 2 for entry in entries)


# --------------------------------------------------------------------------
# Round five. Every test below pins a defect two independent reviewers
# measured on the round-four candidate.
# --------------------------------------------------------------------------


def test_no_tenant_text_reaches_the_shared_entry_in_any_column(
    postgres_database: tuple[str, str, str],
) -> None:
    """Enumerated from the catalog, not hand-picked.

    The round-four version of this test planted the secret in `deals.title` —
    the one column that had just stopped being copied — and asserted over
    `title` and `property_identity` only. It never read `property_type`, which
    the same round had made refresh onto the shared row, so tenant free text was
    green the whole time. A reviewer wrote it through the customer's own
    `deals.listing` grant and read it back off an entry that was still active
    and still listed after the whole workspace was erased.

    So this reads **every** text and jsonb column `internal_opportunities` has,
    from `information_schema`, and needs no edit when a column is added.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    secret = "Acme Holdings LP - seller distressed, do not disclose"
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", property_type=secret[:120],
        )
        # A second workspace on the same property, so the entry survives
        # workspace A's erasure and stays in the default listing.
        _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", property_type="office",
        )
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "UPDATE medawarcre.deals SET title=%s WHERE workspace_id=%s",
            (secret, ids["workspace_a"]),
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning tenant text",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_b"])
        # A ingests last, so under refresh-on-conflict its string would win.
        index.ingest_workspace(owner, ids["workspace_a"])
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        columns = [
            name
            for (name,) in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='medawarcre' "
                "AND table_name='internal_opportunities' "
                "AND data_type IN ('text','character varying','jsonb','json') "
                "ORDER BY column_name"
            ).fetchall()
        ]
        assert len(columns) >= 4, f"the column scan found only {columns}"
        expression = " || ' ' || ".join(f"coalesce({c}::text,'')" for c in columns)
        before = connection.execute(
            f"SELECT {expression} FROM medawarcre.internal_opportunities"
        ).fetchall()
        assert before, "the entry should exist"
        # Positive control. Without it this test would also pass if the secret
        # had never been written anywhere — which is exactly how its round-four
        # ancestor stayed green while tenant text sat on the shared row.
        planted = connection.execute(
            "SELECT count(*) FROM medawarcre.internal_opportunity_sources "
            "WHERE observed_property_type LIKE %s "
            "   OR observed_property_identity::text LIKE %s",
            (f"%{secret[:40]}%", f"%{secret[:40]}%"),
        ).fetchone()[0]
        assert planted >= 1, (
            "the fixture never planted the secret, so this test proves nothing"
        )
        assert all(secret[:60] not in row[0] for row in before), (
            f"tenant text reached the shared entry: {before!r}"
        )

        # And it must not appear after workspace A is erased entirely.
        connection.execute(
            "DELETE FROM medawarcre.deals WHERE workspace_id=%s",
            (ids["workspace_a"],),
        )
        connection.execute(
            "DELETE FROM medawarcre.memberships WHERE workspace_id=%s",
            (ids["workspace_a"],),
        )
        after = connection.execute(
            f"SELECT {expression} FROM medawarcre.internal_opportunities"
        ).fetchall()
    assert all(secret[:60] not in row[0] for row in after), (
        f"tenant text survived erasure on the shared entry: {after!r}"
    )


def test_a_merge_chain_deeper_than_one_hop_is_refused(
    postgres_database: tuple[str, str, str],
) -> None:
    """C→A then A→B built a depth-2 chain with no concurrency at all.

    `require_canonical_merge_target` inspected only the target, never whether
    the entry being merged was itself somebody's target — so "what is C a
    duplicate of?" answered with a row that was itself merged.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for number, address in enumerate(
            ("100 Main St", "200 Elm St", "300 Oak Ave")
        ):
            _deal(
                connection, ids["workspace_a"], ids["user_a"],
                source_record_id=f"a-{number}", address=address, city="Dallas",
                state="TX", zip_code="75201",
            )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="duplicate_review", reason="pinning chain depth",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        by_address = {
            entry.property_identity["address"]: entry.opportunity_id
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        a = by_address["100 MAIN ST"]
        b = by_address["200 ELM ST"]
        c = by_address["300 OAK AVE"]

        index.merge_opportunities(owner, opportunity_id=c, into_opportunity_id=a)
        with pytest.raises(ValueError, match="itself a merge target"):
            index.merge_opportunities(
                owner, opportunity_id=a, into_opportunity_id=b
            )

        detail = index.get_opportunity(owner, c)
        head = index.get_opportunity(owner, detail.entry.merged_into_opportunity_id)
        assert head.entry.merged_into_opportunity_id is None, (
            "a duplicate pointed at an entry that was itself merged"
        )
    finally:
        index.close()


def test_the_database_refuses_a_deeper_chain_without_the_repository(
    postgres_database: tuple[str, str, str],
) -> None:
    """The repository check is convenience; the trigger is the guarantee."""
    admin_dsn, migration_dsn, _app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    first, second, third = str(uuid4()), str(uuid4()), str(uuid4())
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        for identifier, key in ((first, "k-1"), (second, "k-2"), (third, "k-3")):
            connection.execute(
                "INSERT INTO medawarcre.internal_opportunities("
                "id,canonical_key,title,status,property_identity,normalized_facts) "
                "VALUES (%s,%s,'t','active','{}'::jsonb,'{}'::jsonb)",
                (identifier, key),
            )
        connection.execute(
            "UPDATE medawarcre.internal_opportunities "
            "SET status='merged', merged_into_opportunity_id=%s WHERE id=%s",
            (first, third),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE medawarcre.internal_opportunities "
                "SET status='merged', merged_into_opportunity_id=%s WHERE id=%s",
                (second, first),
            )


def test_concurrent_merges_cannot_build_a_cycle(
    postgres_database: tuple[str, str, str],
) -> None:
    """The trigger's target lookup was an unlocked SELECT.

    Two concurrent merges each read the other's entry as still canonical and
    both committed: a reviewer built cycles in 34 of 40 trials. `FOR UPDATE`
    makes them serialize on the same rows.

    Sequenced explicitly rather than raced. A barrier-and-hope version of this
    test passed with `FOR UPDATE` removed — the window is small enough that the
    two transactions rarely interleave on their own, so the pin was decoration.
    Here T2's statement is *known* to begin before T1 commits, which is the
    exact interleaving the lock exists to handle.
    """
    import threading

    admin_dsn, migration_dsn, _app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    first, second = str(uuid4()), str(uuid4())
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        for identifier, key in ((first, "k-1"), (second, "k-2")):
            connection.execute(
                "INSERT INTO medawarcre.internal_opportunities("
                "id,canonical_key,title,status,property_identity,normalized_facts) "
                "VALUES (%s,%s,'t','active','{}'::jsonb,'{}'::jsonb)",
                (identifier, key),
            )

    second_started = threading.Event()
    outcome: dict[str, str] = {}

    def link(connection: psycopg.Connection, source: str, target: str) -> None:
        connection.execute(
            "UPDATE medawarcre.internal_opportunities "
            "SET status='merged', merged_into_opportunity_id=%s WHERE id=%s",
            (target, source),
        )

    def second_writer() -> None:
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            second_started.set()
            try:
                link(connection, second, first)
                connection.commit()
                outcome["second"] = "committed"
            except psycopg.Error as error:
                outcome["second"] = type(error).__name__

    with psycopg.connect(admin_dsn) as first_connection:
        first_connection.execute("SET ROLE medawarcre_migration")
        link(first_connection, first, second)
        worker = threading.Thread(target=second_writer)
        worker.start()
        # T2's statement is now in flight against a row T1 holds uncommitted.
        second_started.wait(timeout=5)
        import time

        time.sleep(0.5)
        first_connection.commit()
        worker.join(timeout=20)

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        links = dict(
            connection.execute(
                "SELECT id::text, merged_into_opportunity_id::text "
                "FROM medawarcre.internal_opportunities"
            ).fetchall()
        )
    cycles = [
        key for key, value in links.items()
        if value is not None and links.get(value) is not None
    ]
    assert not cycles, (
        f"a merge cycle was constructed: {links!r} outcome={outcome!r}"
    )


def test_a_rebind_cannot_deadlock_a_concurrent_workspaces_ingest(
    postgres_database: tuple[str, str, str],
) -> None:
    """The archival trigger locks the entry an observation moves *off*.

    That row is not in the planned canonical-key sequence, so two workspaces
    correcting addresses that swap entries walked the rows in opposite orders.
    Reviewers measured 3 aborted ingests in 10 trials and 29 in 30 — one
    tenant's ordinary address correction destroying another tenant's whole
    ingest. Pre-locking every involved entry in id order is what removes it.

    Widened deliberately, and the widening was measured rather than guessed.
    Two properties × 6 rounds passed with the pre-lock removed — it pinned
    nothing. Eight × 6 caught it 1 time in 3; eight × 30, 4 times in 5. Twenty
    properties × 30 rounds caught it **6 times in 6**, with 6 of 6 clean once
    the pre-lock was restored. That is the configuration below.

    It drives the un-retried path on purpose: `ingest_workspace` retries a
    deadlock three times, which is right for staff and would hide exactly what
    this test looks for.
    """
    import threading

    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    lower = [f"{300 + n} Main St" for n in range(20)]
    upper = [f"{500 + n} Main St" for n in range(20)]
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for number, address in enumerate(lower):
            _deal(
                connection, ids["workspace_a"], ids["user_a"],
                source_record_id=f"a-{number}", address=address, city="Dallas",
                state="TX", zip_code="75201",
            )
        for number, address in enumerate(upper):
            _deal(
                connection, ids["workspace_b"], ids["user_b"],
                source_record_id=f"b-{number}", address=address, city="Dallas",
                state="TX", zip_code="75201",
            )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="seeding before the correction",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])
    finally:
        index.close()

    # Each tenant corrects every address to the other's set: the re-bind that
    # fires the archival trigger on each entry being vacated.
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        for workspace, tag, addresses in (
            (ids["workspace_a"], "a", upper),
            (ids["workspace_b"], "b", lower),
        ):
            for number, address in enumerate(addresses):
                connection.execute(
                    "UPDATE medawarcre.deals SET listing = listing || "
                    "jsonb_build_object('address', %s::text) "
                    "WHERE workspace_id=%s AND source_record_id=%s",
                    (address, workspace, f"{tag}-{number}"),
                )

    failures: list[BaseException] = []
    barrier = threading.Barrier(2)

    def ingest(workspace: str) -> None:
        worker = _index_for(app_dsn)
        request = StaffRequest(
            actor_user_id=ids["owner"], role="owner",
            reason_code="ingestion", reason="concurrent corrected ingest",
        )
        try:
            barrier.wait(timeout=20)
            # The un-retried path on purpose. `ingest_workspace` retries a
            # deadlock up to three times, which is right for staff but would
            # hide the thing this test exists to detect: an earlier version
            # asserted on the retried outcome and passed with the lock ordering
            # removed entirely.
            worker._ingest_workspace(request, workspace)
        except BaseException as error:  # noqa: BLE001 - asserted below
            failures.append(error)
        finally:
            worker.close()

    for _attempt in range(30):
        barrier.reset()
        threads = [
            threading.Thread(target=ingest, args=(ids["workspace_a"],)),
            threading.Thread(target=ingest, args=(ids["workspace_b"],)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert not failures, f"a re-bind deadlocked a concurrent ingest: {failures!r}"


def test_a_live_observation_never_lands_on_an_invisible_entry(
    postgres_database: tuple[str, str, str],
) -> None:
    """Merged-then-archived entries used to swallow an uninvolved workspace.

    Staff merge A into B; A's tenant deletes its deal so the trigger archives A
    with the link retained; then an uninvolved workspace genuinely acquires A's
    property. It was reported `admitted=1` while its observation landed on an
    entry that appears in no default listing and matches no facet filter. The
    observation belongs to the entry staff said it is the same property as.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        doomed = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-2", address="900 Elm St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="duplicate_review", reason="pinning the invisible entry",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        by_address = {
            entry.property_identity["address"]: entry.opportunity_id
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        index.merge_opportunities(
            owner,
            opportunity_id=by_address["100 MAIN ST"],
            into_opportunity_id=by_address["900 ELM ST"],
        )

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "DELETE FROM medawarcre.deals WHERE id=%s", (doomed,)
            )
            _deal(
                connection, ids["workspace_b"], ids["user_b"],
                source_record_id="b-1", address="100 Main St", city="Dallas",
                state="TX", zip_code="75201", property_type="industrial",
            )

        summary = index.ingest_workspace(owner, ids["workspace_b"])
        assert summary.admitted == 1

        listed = index.list_opportunities(owner, limit=20).entries
        workspaces = {
            source.workspace_id for entry in listed for source in entry.sources
        }
        assert ids["workspace_b"] in workspaces, (
            "a live observation was filed under an entry staff cannot see"
        )
        narrowed = index.list_opportunities(
            owner,
            filters=OpportunityFilters(property_type="industrial"),
            limit=20,
        )
        assert narrowed.entries, "the live observation matched no facet filter"
    finally:
        index.close()


def test_a_merge_round_trip_does_not_unhide_a_suppressed_entry(
    postgres_database: tuple[str, str, str],
) -> None:
    """Suppression is the only way staff can hide an entry.

    Merge preserved only `archived` and unmerge chose only between `active` and
    `archived`, so a merge followed by an unmerge silently cleared it.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for number, address in enumerate(("100 Main St", "200 Elm St")):
            _deal(
                connection, ids["workspace_a"], ids["user_a"],
                source_record_id=f"a-{number}", address=address, city="Dallas",
                state="TX", zip_code="75201",
            )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="quality_audit", reason="pinning suppression",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        by_address = {
            entry.property_identity["address"]: entry.opportunity_id
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        hidden, other = by_address["100 MAIN ST"], by_address["200 ELM ST"]
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.internal_opportunities "
                "SET status='suppressed' WHERE id=%s",
                (hidden,),
            )

        index.merge_opportunities(
            owner, opportunity_id=hidden, into_opportunity_id=other
        )
        index.unmerge_opportunity(owner, opportunity_id=hidden)

        visible = {
            entry.opportunity_id
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        assert hidden not in visible, (
            "a merge round-trip returned a suppressed entry to the listing"
        )
    finally:
        index.close()


def test_every_refused_internal_action_is_audited(
    postgres_database: tuple[str, str, str],
) -> None:
    """A refusal is exactly what you want in the log.

    `_require_mutation` raised before opening a transaction, so a
    `read_only_analyst` attempting four mutations produced four
    `PermissionError`s and zero audit rows. And five existence probes raised
    `LookupError` from inside a transaction that then rolled its own audit row
    back, so staff could test for the existence of an entry untraced.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    index = _index_for(app_dsn)
    analyst = StaffRequest(
        actor_user_id=ids["analyst"], role="read_only_analyst",
        reason_code="quality_audit", reason="attempting a mutation",
    )
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="quality_audit", reason="probing for existence",
    )
    absent = str(uuid4())
    try:
        for call in (
            lambda: index.ingest_workspace(analyst, ids["workspace_a"]),
            lambda: index.record_review(
                analyst, opportunity_id=absent, verdict="dismiss"
            ),
            lambda: index.merge_opportunities(
                analyst, opportunity_id=absent, into_opportunity_id=str(uuid4())
            ),
            lambda: index.unmerge_opportunity(analyst, opportunity_id=absent),
        ):
            with pytest.raises(PermissionError):
                call()

        for call in (
            lambda: index.get_opportunity(owner, absent),
            lambda: index.record_review(
                owner, opportunity_id=absent, verdict="dismiss"
            ),
            lambda: index.merge_opportunities(
                owner, opportunity_id=absent, into_opportunity_id=str(uuid4())
            ),
            lambda: index.unmerge_opportunity(owner, opportunity_id=absent),
        ):
            with pytest.raises(LookupError):
                call()
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        rows = dict(
            connection.execute(
                # No object_type filter: `ingest` rows now name `workspace`,
                # which is what their object_id actually refers to.
                "SELECT result, count(*) FROM medawarcre.staff_audit_log "
                "GROUP BY result"
            ).fetchall()
        )
    assert rows.get("denied") == 4, f"role refusals were not audited: {rows!r}"
    assert rows.get("failed") == 4, f"existence probes were not audited: {rows!r}"


def test_an_entry_never_claims_an_older_observation_than_its_own_sources(
    postgres_database: tuple[str, str, str],
) -> None:
    """`statement_timestamp()` advances between the two upserts.

    The entry statement always ran first, so the entry's `last_observed_at`
    trailed its own newest source row's — by under a millisecond in the quiet
    case and by over three seconds under lock contention.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for number in range(3):
            _deal(
                connection, ids["workspace_a"], ids["user_a"],
                source_record_id=f"a-{number}",
                address=f"{100 + number} Main St", city="Dallas",
                state="TX", zip_code="75201",
            )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the clock",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_a"])
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        lagging = connection.execute(
            "SELECT o.id::text, o.last_observed_at, max(s.last_observed_at) "
            "FROM medawarcre.internal_opportunities o "
            "JOIN medawarcre.internal_opportunity_sources s "
            "  ON s.opportunity_id = o.id "
            "GROUP BY o.id, o.last_observed_at "
            "HAVING o.last_observed_at < max(s.last_observed_at)"
        ).fetchall()
    assert not lagging, f"an entry trails its own newest source: {lagging!r}"


# --------------------------------------------------------------------------
# Round six. Two reviewers ran 34 and 13 mutations against the round-five tree
# and found eight repairs with no pin at all. Each test below is one of them,
# or one of the defects they found.
# --------------------------------------------------------------------------


def test_a_tenant_cannot_put_unbounded_text_on_the_shared_entry(
    postgres_database: tuple[str, str, str],
) -> None:
    """`listing.address` is the one tenant string that reaches the shared row.

    It was unbounded: a reviewer drove 88,011 characters through it onto
    `internal_opportunities.title` and `property_identity`, admitted, on an
    entry that stayed `active` and outlived that tenant's erasure. The
    round-five pin missed it by planting its secret in `deals.title` and
    `listing.property_type` — the two channels already closed — while leaving
    `listing.address` clean.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    secret = "ACME HOLDINGS LP SELLER DISTRESSED DO NOT DISCLOSE"
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1",
            address=f"{secret} {'X' * 90} 100 Main St",
            city="Dallas", state="TX", zip_code="75201",
        )
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-2", address="200 Elm St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the address channel",
    )
    try:
        summary = index.ingest_workspace(owner, ids["workspace_a"])
        # Rejected and counted, exactly like an over-long property type — never
        # admitted, and never an abort of the whole workspace.
        assert summary.admitted == 1
        assert summary.rejected == 1
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        columns = [
            name
            for (name,) in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='medawarcre' "
                "AND table_name='internal_opportunities' "
                "AND data_type IN ('text','character varying','jsonb','json')"
            ).fetchall()
        ]
        expression = " || ' ' || ".join(f"coalesce({c}::text,'')" for c in columns)
        rows = connection.execute(
            f"SELECT {expression}, length({expression}) "
            "FROM medawarcre.internal_opportunities"
        ).fetchall()
    assert rows, "the surviving entry should exist"
    assert all(secret not in row[0] for row in rows), (
        f"tenant text reached the shared entry: {rows!r}"
    )
    assert all(row[1] < 4000 for row in rows), (
        f"the shared entry carries an unbounded tenant string: {rows!r}"
    )


def test_the_entry_property_type_is_derived_and_reports_disagreement_as_none(
    postgres_database: tuple[str, str, str],
) -> None:
    """Round five's headline repair had no test reading it at all.

    `grep '.property_type'` over this file returned nothing, so mutating
    `_derived_property_type` to return `None` always — or to pick a winner when
    workspaces disagree — left the whole suite green.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", property_type="office",
        )
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-2", address="200 Elm St", city="Dallas",
            state="TX", zip_code="75201", property_type="retail",
        )
        _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", property_type="industrial",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the derived value",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])
        by_address = {
            entry.property_identity["address"]: entry
            for entry in index.list_opportunities(owner, limit=10).entries
        }

        # One contributor: the entry reports it.
        assert by_address["200 ELM ST"].property_type == "retail"
        # Two contributors that disagree: None, and a named conflict instead.
        shared = by_address["100 MAIN ST"]
        assert shared.property_type is None, (
            "the entry picked a winner where the workspaces disagree"
        )
        conflict = next(c for c in shared.conflicts if c.kind == "property_type")
        assert {p.value for p in conflict.positions} == {"office", "industrial"}

        # And the same through get_opportunity, which builds the entry
        # separately.
        detail = index.get_opportunity(owner, by_address["200 ELM ST"].opportunity_id)
        assert detail.entry.property_type == "retail"
    finally:
        index.close()


def test_the_ingest_prelock_orders_by_id_and_follows_merge_links() -> None:
    """Read from the module source, because the order is the whole argument.

    `ORDER BY id` is what makes the pre-lock a *total* order; a reviewer removed
    it, kept `FOR UPDATE`, and every test stayed green. And the locked set has
    to be closed under merge links: an observation whose matched entry is merged
    files under the head, and the foreign key takes `FOR KEY SHARE` on that head
    — a row neither obvious set contains.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "src" / "cre_mcp" / "postgres" / "opportunity_index.py"
    ).read_text()

    prelock = source[source.index('"WITH touched AS ("'):]
    prelock = prelock[: prelock.index(").fetchall()")]
    assert '"ORDER BY id FOR UPDATE"' in prelock, (
        "the ingest pre-lock no longer takes rows in a total order"
    )
    assert "merged_into_opportunity_id FROM touched" in prelock, (
        "the pre-lock no longer follows merge links to the canonical head"
    )


def test_a_transient_deadlock_is_retried_rather_than_surfaced(
    postgres_database: tuple[str, str, str],
) -> None:
    """The retry had no pin: `attempts = 3` → `1` left all 310 tests green.

    Driven by making the first attempt fail and counting that the call still
    succeeds, so the pin is the retry itself rather than a race.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the retry",
    )
    attempts: list[int] = []
    real = index._ingest_workspace

    def flaky(request: StaffRequest, workspace_id: str) -> object:
        attempts.append(1)
        if len(attempts) == 1:
            raise psycopg.errors.DeadlockDetected("induced")
        return real(request, workspace_id)

    try:
        index._ingest_workspace = flaky  # type: ignore[method-assign]
        summary = index.ingest_workspace(owner, ids["workspace_a"])
        assert len(attempts) == 2, "a transient deadlock was not retried"
        assert summary.admitted == 1

        # A persistent deadlock still gives up, and is audited as failed.
        attempts.clear()

        def always(request: StaffRequest, workspace_id: str) -> object:
            attempts.append(1)
            raise psycopg.errors.DeadlockDetected("induced")

        index._ingest_workspace = always  # type: ignore[method-assign]
        with pytest.raises(psycopg.errors.DeadlockDetected):
            index.ingest_workspace(owner, ids["workspace_a"])
        assert len(attempts) == 3, "the retry bound is not three attempts"
    finally:
        index._ingest_workspace = real  # type: ignore[method-assign]
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        results = dict(
            connection.execute(
                "SELECT result, count(*) FROM medawarcre.staff_audit_log "
                "WHERE action='ingest' GROUP BY result"
            ).fetchall()
        )
    assert results.get("failed") == 1, f"the exhausted retry was not audited: {results}"


def test_a_failed_ingest_does_not_block_deleting_the_workspace(
    postgres_database: tuple[str, str, str],
) -> None:
    """An ingest that did not happen must not create an erasure blocker.

    `_audit_out_of_band` tries the linked row first, so a failure on an
    *existing* workspace wrote a non-NULL `staff_audit_log.workspace_id` and
    made that workspace permanently undeletable — exactly as a successful
    ingest does. Both round-six reviewers found it; the round-five test never
    read `workspace_id` at all.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="a failure on a real workspace",
    )
    real = index._ingest_workspace
    try:
        def always(request: StaffRequest, workspace_id: str) -> object:
            raise psycopg.errors.DeadlockDetected("induced")

        index._ingest_workspace = always  # type: ignore[method-assign]
        with pytest.raises(psycopg.errors.DeadlockDetected):
            index.ingest_workspace(owner, ids["workspace_a"])
    finally:
        index._ingest_workspace = real  # type: ignore[method-assign]
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        rows = connection.execute(
            "SELECT action, result, workspace_id, object_id "
            "FROM medawarcre.staff_audit_log WHERE action='ingest'"
        ).fetchall()
        assert rows, "the failed ingest was not audited at all"
        for _action, result, workspace_id, object_id in rows:
            assert result == "failed"
            assert workspace_id is None, (
                "a failed ingest linked the workspace and blocked its deletion"
            )
            # Not lost: the workspace is still identified on the row.
            assert str(object_id) == ids["workspace_a"]
        # And the workspace really is still deletable.
        connection.execute(
            "DELETE FROM medawarcre.memberships WHERE workspace_id=%s",
            (ids["workspace_a"],),
        )
        connection.execute(
            "DELETE FROM medawarcre.workspaces WHERE id=%s",
            (ids["workspace_a"],),
        )
        connection.commit()


def test_merge_takes_its_two_rows_in_the_same_order_ingest_does() -> None:
    """A total order is only total if every writer uses it.

    Merge locked the target first and then updated the source, so whenever
    `source.id < target.id` it walked the same pair opposite to the ingest
    pre-lock and two ordinary public calls deadlocked.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "src" / "cre_mcp" / "postgres" / "opportunity_index.py"
    ).read_text()
    body = source[source.index("    def merge_opportunities("):]
    body = body[: body.index("    def unmerge_opportunity(")]

    lock = body.index("ORDER BY id FOR UPDATE")
    inspect = body.index("SELECT merged_into_opportunity_id")
    update = body.index("UPDATE medawarcre.internal_opportunities")
    assert lock < inspect < update, (
        "merge inspects or writes before taking both rows in id order"
    )


def test_the_canonical_head_is_lifted_out_of_archived_on_re_observation(
    postgres_database: tuple[str, str, str],
) -> None:
    """Half of the canonical-filing repair had no pin.

    A reviewer removed the lift and the whole suite stayed green: an
    observation filed under a head that had itself been archived would have
    stayed invisible, which is the defect the repair exists to prevent.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        superseded = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )
        head = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-2", address="900 Elm St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="duplicate_review", reason="pinning the head lift",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        by_address = {
            entry.property_identity["address"]: entry.opportunity_id
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        index.merge_opportunities(
            owner,
            opportunity_id=by_address["100 MAIN ST"],
            into_opportunity_id=by_address["900 ELM ST"],
        )

        # Both tenant records go, so the head archives too.
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "DELETE FROM medawarcre.deals WHERE id = ANY(%s)",
                ([superseded, head],),
            )
        assert index.list_opportunities(owner, limit=10).entries == ()

        # A different workspace now genuinely acquires the merged property.
        with psycopg.connect(admin_dsn) as connection:
            _deal(
                connection, ids["workspace_b"], ids["user_b"],
                source_record_id="b-1", address="100 Main St", city="Dallas",
                state="TX", zip_code="75201",
            )
        index.ingest_workspace(owner, ids["workspace_b"])

        listed = index.list_opportunities(owner, limit=10).entries
        assert listed, "the canonical head was never lifted out of archived"
        assert any(
            source.workspace_id == ids["workspace_b"]
            for entry in listed for source in entry.sources
        )
    finally:
        index.close()


def test_source_observed_at_records_the_latest_read_not_the_first(
    postgres_database: tuple[str, str, str],
) -> None:
    """Half of the clock repair had no pin either."""
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the source clock",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            first = connection.execute(
                "SELECT source_observed_at "
                "FROM medawarcre.internal_opportunity_sources"
            ).fetchone()[0]
        index.ingest_workspace(owner, ids["workspace_a"])
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            second = connection.execute(
                "SELECT source_observed_at "
                "FROM medawarcre.internal_opportunity_sources"
            ).fetchone()[0]
    finally:
        index.close()

    assert second > first, (
        "source_observed_at still records only the first read"
    )


def test_the_declared_facet_indexes_can_serve_the_queries_that_use_them(
    postgres_database: tuple[str, str, str],
) -> None:
    """An index whose leading column the predicate never matches serves nothing.

    The market index was rebuilt as `(market, status)` while the listing filters
    `lower(o.market)`, so every market filter was a sequential scan — the same
    defect the keyset index had two rounds earlier, in an index rebuilt to fix
    something else. And the per-source property_type index a reviewer dropped
    left the whole focused suite green.
    """
    admin_dsn, migration_dsn, _app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        definitions = dict(
            connection.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='medawarcre' "
                "AND tablename IN ('internal_opportunities',"
                "                  'internal_opportunity_sources')"
            ).fetchall()
        )

    market = definitions["internal_opportunities_market_idx"]
    assert "lower(market)" in market, (
        f"the market index cannot serve lower(market): {market}"
    )
    assert "internal_opportunity_sources_property_type_idx" in definitions
    assert "observed_property_type" in (
        definitions["internal_opportunity_sources_property_type_idx"]
    )


def test_deleting_a_saved_search_does_not_null_the_workspace_key(
    postgres_database: tuple[str, str, str],
) -> None:
    """`ON DELETE SET NULL` over a composite nulls every referencing column.

    Including `workspace_id NOT NULL`, so a tenant deleting a saved search got a
    raw NotNullViolation out of a cross-tenant table. Exercised through a
    deal-origin observation that merely *cites* the saved search it came from,
    which isolates this foreign key: a search-result-origin row is deleted by
    the cascade through `search_runs` before this key is ever consulted.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        deal = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )
        connection.execute("SET ROLE medawarcre_migration")
        saved = str(uuid4())
        connection.execute(
            "INSERT INTO medawarcre.saved_searches("
            "id,workspace_id,owner_user_id,name,query) "
            "VALUES (%s,%s,%s,'a search','{}'::jsonb)",
            (saved, ids["workspace_a"], ids["user_a"]),
        )
        connection.commit()

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the saved-search key",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        # The observation cites the saved search it originated from.
        connection.execute(
            "UPDATE medawarcre.internal_opportunity_sources "
            "SET source_saved_search_id=%s WHERE source_deal_id=%s",
            (saved, deal),
        )
        connection.commit()
        connection.execute(
            "DELETE FROM medawarcre.saved_searches WHERE id=%s", (saved,)
        )
        remaining = connection.execute(
            "SELECT workspace_id, source_saved_search_id, source_deal_id "
            "FROM medawarcre.internal_opportunity_sources"
        ).fetchall()
    assert remaining, "the observation should survive the saved search"
    assert remaining[0][0] is not None, "workspace_id was nulled"
    assert remaining[0][1] is None, "the saved-search link was not cleared"
    assert remaining[0][2] is not None, "the deal link was nulled too"


def test_a_mutation_aborted_by_a_lock_is_still_audited(
    postgres_database: tuple[str, str, str],
) -> None:
    """`_Refused` covered the checks; it never covered the transaction dying.

    A deadlocked `merge_opportunities` wrote no audit row at all, because the
    audit insert lives inside the doomed transaction — the same untraced-action
    class round five closed for role denials and missing objects, left standing
    for aborts. Driven here with a held row lock and a short `lock_timeout`,
    which is deterministic where a deadlock race is not.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for number, address in enumerate(("100 Main St", "200 Elm St")):
            _deal(
                connection, ids["workspace_a"], ids["user_a"],
                source_record_id=f"a-{number}", address=address, city="Dallas",
                state="TX", zip_code="75201",
            )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="duplicate_review", reason="pinning the aborted audit",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        entries = [
            entry.opportunity_id
            for entry in index.list_opportunities(owner, limit=10).entries
        ]
    finally:
        index.close()

    with psycopg.connect(admin_dsn, autocommit=True) as setup:
        setup.execute(
            "ALTER ROLE medawarcre_test_admin SET lock_timeout = '400ms'"
        )
    try:
        blocker = psycopg.connect(admin_dsn)
        blocker.execute("SET ROLE medawarcre_migration")
        blocker.execute(
            "SELECT id FROM medawarcre.internal_opportunities "
            "WHERE id = ANY(%s) FOR UPDATE",
            (entries,),
        )
        # The lock is held, uncommitted, while the merge tries to take it.
        index = _index_for(app_dsn)
        try:
            with pytest.raises(psycopg.Error):
                index.merge_opportunities(
                    owner,
                    opportunity_id=entries[0],
                    into_opportunity_id=entries[1],
                )
        finally:
            index.close()
            blocker.rollback()
            blocker.close()
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as teardown:
            teardown.execute(
                "ALTER ROLE medawarcre_test_admin RESET lock_timeout"
            )

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        merges = connection.execute(
            "SELECT result FROM medawarcre.staff_audit_log WHERE action='merge'"
        ).fetchall()
    assert merges == [("failed",)], (
        f"an aborted merge left the audit trail saying nothing: {merges!r}"
    )


# --------------------------------------------------------------------------
# Round seven. Two reviewers chose 114 and 41 mutations of their own and found
# these unpinned — including guards a previous round's record called verified.
# --------------------------------------------------------------------------


def test_the_listing_order_and_the_keyset_index_are_read_from_the_same_pair() -> None:
    """The round-five test read only the SQL, while its name claimed both.

    Its docstring said it "reads the index definition and the listing's `ORDER
    BY` and requires them to agree". It read one. Reverting the listing to
    `last_observed_at` — the mutable key whose use the record calls the cause of
    skipped pages — left all 47 focused and 274 other PostgreSQL tests green.
    Fifth appearance of this phase's signature shape, in a test written to close
    the fourth.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    module = (root / "src" / "cre_mcp" / "postgres" / "opportunity_index.py").read_text()
    sql = (
        root / "src" / "cre_mcp" / "postgres" / "sql"
        / "0009_internal_opportunity_index.sql"
    ).read_text()

    assert '" ORDER BY o.created_at DESC, o.id DESC LIMIT %s"' in module, (
        "the listing no longer pages on the immutable created_at order"
    )
    assert (
        "CREATE INDEX internal_opportunities_keyset_idx\n"
        "    ON medawarcre.internal_opportunities (created_at DESC, id DESC);"
    ) in sql
    # And the cursor must be encoded from the same column it orders by.
    assert "_encode_cursor(visible[-1][9]" in module


def test_both_conflict_upserts_use_the_shared_transaction_clock() -> None:
    """Each clause needs its own pin.

    The round-five test only fails when *both* are reverted, so mutating the
    entry clause alone left all 47 green — and a reviewer measured that mutant
    aborting a whole workspace ingest in 1 of 20 concurrent trials, which is the
    `observed_order_check` class this phase has hit three times.
    """
    from pathlib import Path

    module = (
        Path(__file__).resolve().parents[2]
        / "src" / "cre_mcp" / "postgres" / "opportunity_index.py"
    ).read_text()

    def sql_only(fragment: str) -> str:
        """Just the SQL literals — comments quote the old function by name."""
        return "\n".join(
            line for line in fragment.splitlines()
            if line.lstrip().startswith('"')
        )

    entry = sql_only(
        module[module.index('"ON CONFLICT (canonical_key) DO UPDATE SET "'):
               module.index('"RETURNING id, merged_into_opportunity_id"')]
    )
    # No wall clock anywhere in either upsert, and the monotonic guard intact.
    assert "statement_timestamp()" not in entry, (
        "the entry upsert reverted to the per-statement clock"
    )
    assert "GREATEST(" in entry and "transaction_timestamp()" in entry

    source = sql_only(
        module[module.index('"ON CONFLICT (workspace_id, source, source_record_id) "'):
               module.index("admitted += 1")]
    )
    assert "statement_timestamp()" not in source, (
        "the source upsert reverted to the per-statement clock"
    )
    assert source.count("GREATEST(") == 2, (
        "a source clock lost its monotonic guard"
    )


def test_the_ingest_plans_in_canonical_key_order() -> None:
    """Deleting `planned.sort` left the whole suite green.

    Two ingests creating the same two new keys in opposite orders each hold one
    speculative unique-index entry and wait on the other — a cycle the pre-lock
    cannot prevent, because neither row exists yet to be locked. The retry masks
    it, which is why it went unnoticed.
    """
    from pathlib import Path

    module = (
        Path(__file__).resolve().parents[2]
        / "src" / "cre_mcp" / "postgres" / "opportunity_index.py"
    ).read_text()
    body = module[module.index("    def _ingest_workspace("):]
    body = body[: body.index("    # -- reads ")]
    assert "planned.sort(key=lambda item: (item[0], item[1]))" in body
    assert body.index("planned.sort(") < body.index("WITH touched AS"), (
        "the plan is sorted after the rows are locked, which orders nothing"
    )


def test_every_contract_retention_item_survives_a_re_ingest(
    postgres_database: tuple[str, str, str],
) -> None:
    """Four retention items had no test at all.

    A reviewer blanked `provenance`, flipped `access_class` to `'public'`, and
    dropped the `score`/`stage`/`outcome` refresh from the source upsert — all
    321 PostgreSQL tests stayed green in each case. Retention items 6, 7, 8, 9
    and 11 are contract requirements; staleness in them means staff reading
    pipeline state that stopped being true.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        deal = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", property_type="office",
            stage="lead", score=30.0,
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning retention",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        first = index.list_opportunities(owner, limit=5).entries[0].sources[0]
        # 9: provenance names the exact tenant row.
        assert first.provenance.get("deal_id") == str(deal), first.provenance
        assert first.provenance.get("kind") == "deal"
        # 11: access class is the fail-safe value, not the permissive one.
        assert first.access_class == "private"
        # 6, 7, 8 as first observed.
        assert first.score == 30.0
        assert first.stage == "lead"
        assert first.outcome is None

        # The tenant advances the deal and records an outcome.
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.deals SET stage='closing', score=88.0, "
                "listing = listing || jsonb_build_object("
                "'property_type','industrial','address','101 Main St') "
                "WHERE id=%s",
                (deal,),
            )
            connection.execute(
                "INSERT INTO medawarcre.deal_outcomes("
                "workspace_id,deal_id,closed,went_bad,purchase_price) "
                "VALUES (%s,%s,false,true,NULL)",
                (ids["workspace_a"], deal),
            )

        index.ingest_workspace(owner, ids["workspace_a"])
        entries = index.list_opportunities(owner, limit=10).entries
        live = next(
            entry for entry in entries
            if entry.property_identity["address"] == "101 MAIN ST"
        )
        second = live.sources[0]
        # 6, 7, 8 refreshed — not frozen at first observation.
        assert second.score == 88.0, "score never refreshed"
        assert second.stage == "closing", "stage never refreshed"
        assert second.outcome == "went_bad", "outcome never refreshed"
        # The observed identity and type follow the correction too.
        assert second.observed_property_type == "industrial"
        assert second.observed_property_identity["address"] == "101 Main St"
        assert second.observed_market == "Dallas, TX"
    finally:
        index.close()


def test_a_passed_stage_derives_an_outcome_when_the_tenant_recorded_none(
    postgres_database: tuple[str, str, str],
) -> None:
    """`stage == 'passed'` implies an outcome; nothing pinned the derivation."""
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="passed",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the derivation",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        source = index.list_opportunities(owner, limit=5).entries[0].sources[0]
    finally:
        index.close()
    assert source.outcome == "passed"


def test_unmerging_a_sourceless_entry_archives_it_rather_than_reviving_it(
    postgres_database: tuple[str, str, str],
) -> None:
    """The contract says `archived` when there is no observation; nothing pinned it."""
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        doomed = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-2", address="900 Elm St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="duplicate_review", reason="pinning unmerge status",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        by_address = {
            entry.property_identity["address"]: entry.opportunity_id
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        superseded = by_address["100 MAIN ST"]
        index.merge_opportunities(
            owner, opportunity_id=superseded,
            into_opportunity_id=by_address["900 ELM ST"],
        )
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "DELETE FROM medawarcre.deals WHERE id=%s", (doomed,)
            )
        index.unmerge_opportunity(owner, opportunity_id=superseded)
        detail = index.get_opportunity(owner, superseded)
    finally:
        index.close()

    assert detail.entry.sources == ()
    assert detail.entry.status == "archived", (
        "unmerge revived an entry with no contributing observation"
    )


def test_the_index_refuses_a_non_admin_runtime(
    postgres_database: tuple[str, str, str],
) -> None:
    """One of the module docstring's own three fail-closed guards.

    Deleting the `runtime_mode != "admin"` check made `InternalIndexUnavailable`
    unraisable and left the whole suite green.
    """
    from cre_mcp.postgres.config import PostgresSettings
    from cre_mcp.postgres.opportunity_index import InternalIndexUnavailable
    from cre_mcp.postgres.pool import PostgresDatabase

    _admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=0, max_size=1)
    )
    try:
        assert database.settings.runtime_mode == "app"
        with pytest.raises(InternalIndexUnavailable):
            InternalOpportunityIndex(database)
    finally:
        database.close()


# --------------------------------------------------------------------------
# Round eight. Both reviewers found that round seven's read-audit repair was
# recorded as landed and was not in the code — the edit script raised before
# writing, and nothing in 5,093 tests noticed. These are the pins that would
# have.
# --------------------------------------------------------------------------


def _lock_out(admin_dsn: str) -> psycopg.Connection:
    """Hold the entry table so the next index call fails on the lock."""
    blocker = psycopg.connect(admin_dsn)
    blocker.execute("SET ROLE medawarcre_migration")
    blocker.execute(
        "LOCK TABLE medawarcre.internal_opportunities IN ACCESS EXCLUSIVE MODE"
    )
    return blocker


def test_every_internal_action_including_reads_is_audited_when_it_aborts(
    postgres_database: tuple[str, str, str],
) -> None:
    """The contract says *every read and every mutation*, and it meant it.

    Round seven wrapped the mutations, recorded that it had wrapped the reads
    too, and had not. Under an identical induced failure, merge/review/ingest
    each wrote one `failed` row and `list`/`inspect` wrote none — for three
    consecutive rounds this record declared the untraced-action class closed.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="quality_audit", reason="auditing an aborted action",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        target = index.list_opportunities(owner, limit=5).entries[0].opportunity_id
    finally:
        index.close()

    with psycopg.connect(admin_dsn, autocommit=True) as setup:
        setup.execute(
            "ALTER ROLE medawarcre_test_admin SET lock_timeout = '400ms'"
        )
    blocker = _lock_out(admin_dsn)
    index = _index_for(app_dsn)
    try:
        for call in (
            lambda: index.list_opportunities(owner, limit=5),
            lambda: index.get_opportunity(owner, target),
            lambda: index.record_review(
                owner, opportunity_id=target, verdict="dismiss"
            ),
            lambda: index.merge_opportunities(
                owner, opportunity_id=target, into_opportunity_id=str(uuid4())
            ),
            lambda: index.unmerge_opportunity(owner, opportunity_id=target),
        ):
            with pytest.raises(psycopg.Error):
                call()
    finally:
        index.close()
        blocker.rollback()
        blocker.close()
        with psycopg.connect(admin_dsn, autocommit=True) as teardown:
            teardown.execute(
                "ALTER ROLE medawarcre_test_admin RESET lock_timeout"
            )

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        failed = {
            action
            for (action,) in connection.execute(
                "SELECT DISTINCT action FROM medawarcre.staff_audit_log "
                "WHERE result='failed'"
            ).fetchall()
        }
    assert failed == {"list", "inspect", "review", "merge", "unmerge"}, (
        f"an aborted internal action left no trace: {failed!r}"
    )


def test_an_owner_is_audited_for_a_bad_argument_exactly_as_an_analyst_is(
    postgres_database: tuple[str, str, str],
) -> None:
    """The verdict and self-merge checks sat outside the audit guard.

    So the *less* privileged attempt left a record and the more privileged one
    left none — an asymmetry pointing the wrong way for an audit trail.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="quality_audit", reason="a deliberately bad argument",
    )
    same = str(uuid4())
    try:
        with pytest.raises(ValueError):
            index.record_review(owner, opportunity_id=same, verdict="perhaps")
        with pytest.raises(ValueError):
            index.merge_opportunities(
                owner, opportunity_id=same, into_opportunity_id=same
            )
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        rows = sorted(
            connection.execute(
                "SELECT action, result FROM medawarcre.staff_audit_log"
            ).fetchall()
        )
    assert rows == [("merge", "failed"), ("review", "failed")], (
        f"an owner's invalid call was not audited: {rows!r}"
    )


def test_a_vanished_tenant_deal_is_retried_rather_than_losing_the_batch(
    postgres_database: tuple[str, str, str],
) -> None:
    """The foreign-key half of `_TRANSIENT` was verified by nothing.

    Removing `ForeignKeyViolation` from the retry set survived at every scope —
    focused, all of `tests/postgres`, and the whole repository — while the
    defect it fixes loses an entire workspace's ingest at 6–14 in 30 trials.
    The neighbouring `attempts` bound *is* pinned, which is what made the gap
    easy to miss: the retry looked covered.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for number in range(4):
            _deal(
                connection, ids["workspace_a"], ids["user_a"],
                source_record_id=f"a-{number}",
                address=f"{100 + number} Main St", city="Dallas",
                state="TX", zip_code="75201",
            )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the vanished-deal retry",
    )
    attempts: list[int] = []
    real = index._ingest_workspace

    def flaky(request: StaffRequest, workspace_id: str) -> object:
        attempts.append(1)
        if len(attempts) == 1:
            raise psycopg.errors.ForeignKeyViolation(
                'insert or update on table "internal_opportunity_sources" '
                'violates foreign key constraint '
                '"internal_opportunity_sources_deal_fkey"'
            )
        return real(request, workspace_id)

    try:
        index._ingest_workspace = flaky  # type: ignore[method-assign]
        summary = index.ingest_workspace(owner, ids["workspace_a"])
    finally:
        index._ingest_workspace = real  # type: ignore[method-assign]
        index.close()

    assert len(attempts) == 2, (
        "a tenant deleting its own deal mid-ingest still loses the whole batch"
    )
    assert summary.admitted == 4


def test_the_customer_role_holds_no_privilege_of_any_kind(
    postgres_database: tuple[str, str, str],
) -> None:
    """The layer-one pin probed `SELECT` and was titled "no privilege".

    Granting INSERT, UPDATE and DELETE on the one deliberately cross-tenant
    table to `medawarcre_app` passed every gate this repository has. That is the
    first and most-relied-on layer of the boundary — "a grant boundary before it
    is a policy boundary, so a policy mistake cannot open the index on its own".
    """
    admin_dsn, migration_dsn, _app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    relations = (
        "internal_opportunities",
        "internal_opportunity_sources",
        "internal_opportunity_reviews",
    )
    privileges = (
        "SELECT", "INSERT", "UPDATE", "DELETE",
        "TRUNCATE", "REFERENCES", "TRIGGER",
    )
    customer_roles = (
        "medawarcre_app", "medawarcre_oauth", "medawarcre_admission",
        "medawarcre_provider_ingress", "medawarcre_provider_reconcile",
        "medawarcre_worker", "medawarcre_scheduler",
    )
    granted: list[tuple[str, str, str]] = []
    with psycopg.connect(admin_dsn) as connection:
        columns = {
            relation: [
                name
                for (name,) in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='medawarcre' AND table_name=%s",
                    (relation,),
                ).fetchall()
            ]
            for relation in relations
        }
        for role in customer_roles:
            for relation in relations:
                for privilege in privileges:
                    if connection.execute(
                        "SELECT has_table_privilege(%s, %s, %s)",
                        (role, f"medawarcre.{relation}", privilege),
                    ).fetchone()[0]:
                        granted.append((role, relation, privilege))
                # Column grants too. `has_table_privilege` cannot see them, and
                # they are the dominant idiom in this schema — 45 in
                # `restore_privileges.sql` alone. A reviewer granted
                # `SELECT (canonical_key, title, market, status)` to
                # `medawarcre_app` and all 147 table-level probes passed.
                for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                    for column in columns[relation]:
                        if connection.execute(
                            "SELECT has_column_privilege(%s, %s, %s, %s)",
                            (role, f"medawarcre.{relation}", column, privilege),
                        ).fetchone()[0]:
                            granted.append(
                                (role, f"{relation}.{column}", privilege)
                            )
    assert granted == [], (
        f"a customer-reachable role holds privilege on the index: {granted!r}"
    )


# --------------------------------------------------------------------------
# Round nine. Layer two of the customer boundary had no test at all, and the
# read path kept the audit gap round eight closed for the mutations.
# --------------------------------------------------------------------------


def test_the_runtime_pool_refuses_authority_of_the_wrong_kind(
    postgres_database: tuple[str, str, str],
) -> None:
    """Layer two of the boundary, which 5,097 tests did not defend.

    The contract names exactly two independent fail-closed mechanisms and this
    is the second: an `app` pool must refuse internal authority so the customer
    pool cannot borrow staff authority even with a correct role string. A
    reviewer replaced the guard with `pass` and the focused suite, all of
    `tests/postgres`, and the whole repository stayed green —
    `AuthorityContext.internal` is constructed nowhere else in `tests/`.

    The mirror branch is pinned here too: an `admin` pool must refuse a tenant
    context, or a staff pool would execute a customer's authority.
    """
    from cre_mcp.postgres.config import PostgresSettings
    from cre_mcp.postgres.pool import AuthorityContext, PostgresDatabase

    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    internal = AuthorityContext.internal(ids["owner"], "owner", "a stated reason")
    tenant = AuthorityContext.tenant(ids["workspace_a"], ids["user_a"])

    app_pool = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=0, max_size=1)
    )
    admin_pool = PostgresDatabase(
        PostgresSettings(
            dsn=app_dsn.replace(
                "user=medawarcre_test_app", "user=medawarcre_test_admin"
            ),
            runtime_mode="admin", min_size=0, max_size=1,
        )
    )
    try:
        app_pool.open(wait=True)
        admin_pool.open(wait=True)

        with pytest.raises(ValueError, match="cannot accept internal authority"):
            with app_pool.connection(internal):
                pass
        with pytest.raises(ValueError, match="requires internal authority"):
            with admin_pool.connection(tenant):
                pass
        # And the contextless branches, so the four are pinned together.
        with pytest.raises(ValueError, match="requires tenant authority"):
            with app_pool.connection(None):
                pass
        with pytest.raises(ValueError, match="requires internal authority"):
            with admin_pool.connection(None):
                pass

        # The authority object itself refuses a role outside the vocabulary and
        # a blank reason — both unpinned, both named by the contract.
        with pytest.raises(ValueError):
            AuthorityContext.internal(ids["owner"], "emperor", "a stated reason")
        with pytest.raises(ValueError):
            AuthorityContext.internal(ids["owner"], "owner", "   ")
    finally:
        app_pool.close()
        admin_pool.close()


def test_a_read_refused_for_a_bad_argument_is_audited_like_a_refused_mutation(
    postgres_database: tuple[str, str, str],
) -> None:
    """Round eight fixed the mutations and left the read path's own checks.

    `record_review` and `merge_opportunities` validate inside their guards and
    each write one `failed` row; `list_opportunities` validated `limit` and
    `cursor` above its guard, so the index refused those calls without
    recording them. A reviewer measured 96 unrecorded refusals across 1,500
    randomized staff steps — the only invariant that run violated.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="pipeline_review", reason="a deliberately bad argument",
    )
    try:
        for call in (
            lambda: index.list_opportunities(owner, limit=0),
            lambda: index.list_opportunities(owner, limit=MAX_PAGE + 1),
            lambda: index.list_opportunities(owner, limit="5"),  # type: ignore[arg-type]
            lambda: index.list_opportunities(owner, cursor="not-a-cursor"),
        ):
            with pytest.raises(ValueError):
                call()
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        rows = connection.execute(
            "SELECT action, result, count(*) FROM medawarcre.staff_audit_log "
            "GROUP BY action, result"
        ).fetchall()
    assert rows == [("list", "failed", 4)], (
        f"a read refused for a bad argument was not audited: {rows!r}"
    )


def test_a_workspace_filtered_read_links_the_workspace_it_named(
    postgres_database: tuple[str, str, str],
) -> None:
    """The positive half of the six-times-rewritten claim had no pin.

    Mutating the audit link to `None` survived 63 focused and 337 PostgreSQL
    tests while turning a workspace that should be undeletable into a deletable
    one — silently falsifying "two distinct index actions write a non-NULL
    workspace_id". The negative branch was pinned; this one was not.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="pipeline_review", reason="a workspace-filtered read",
    )
    try:
        index.list_opportunities(
            owner,
            filters=OpportunityFilters(workspace_id=ids["workspace_a"]),
            limit=10,
        )
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        rows = connection.execute(
            "SELECT action, result, workspace_id::text "
            "FROM medawarcre.staff_audit_log"
        ).fetchall()
        assert rows == [("list", "succeeded", ids["workspace_a"])], (
            f"the filtered read did not link the workspace it named: {rows!r}"
        )
        # And the consequence the record states: that link blocks erasure.
        connection.execute(
            "DELETE FROM medawarcre.memberships WHERE workspace_id=%s",
            (ids["workspace_a"],),
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "DELETE FROM medawarcre.workspaces WHERE id=%s",
                (ids["workspace_a"],),
            )


def test_each_audit_row_names_the_kind_of_object_its_id_refers_to(
    postgres_database: tuple[str, str, str],
) -> None:
    """`object_type` was the constant `'internal_opportunity'` on every row.

    Including `ingest`, whose `object_id` is a workspace uuid, and `list`, whose
    `object_id` is the literal `'internal_opportunity_index'`. An audit row that
    misnames its object is the same category of defect as one that is missing.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the object type",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        entry = index.list_opportunities(owner, limit=5).entries[0]
        index.get_opportunity(owner, entry.opportunity_id)
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        rows = dict(
            connection.execute(
                "SELECT action, object_type FROM medawarcre.staff_audit_log"
            ).fetchall()
        )
    assert rows == {
        "ingest": "workspace",
        "list": "internal_opportunity_index",
        "inspect": "internal_opportunity",
    }, f"an audit row misnames the object it refers to: {rows!r}"


def test_the_pool_scrubs_and_scopes_the_authority_context(
    postgres_database: tuple[str, str, str],
) -> None:
    """Four `pool.py` guards that nothing observed, at any scope.

    The record claimed a round-nine test pinned all five survivors; it drives
    six things and `_reset` is not one of them — deleting the `_CONTEXT_KEYS`
    loop left 5,099 tests green. Three more went with it: `set_config`'s
    transaction scope, the tenant-context workspace requirement, and the rule
    that an audit reason requires an internal role. And
    `test_pool_context_is_transaction_local_and_readiness_is_strict` is named
    for transaction-locality and never observes it.

    None is a live leak — a reviewer tried to compose the first two into one and
    could not, because `bind_admitted_request` re-sets the tenant keys and
    blanks the internal ones transaction-locally. They are defence in depth, and
    defence in depth that no test observes is indistinguishable from none.
    """
    from cre_mcp.postgres.config import PostgresSettings
    from cre_mcp.postgres.pool import _CONTEXT_KEYS, AuthorityContext, PostgresDatabase

    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    # The authority object refuses two shapes that would otherwise reach SQL.
    #
    # Both assertions carry `match=`, and that is the point. The first was
    # written as `AuthorityContext.tenant(None, ...)` under a bare
    # `pytest.raises(ValueError)` — but `tenant()` does `cls(str(workspace_id),
    # ...)`, so `None` becomes the string "None" and dies in the UUID check,
    # never reaching the guard this line names. Both round-eleven reviewers
    # found it, and mutating that guard to `pass` survived every scope.
    #
    # The lesson is narrower than "run the mutation first", which I had already
    # adopted: a mutation matrix of indistinguishable assertions can look
    # complete while measuring one guard twice. `ValueError` alone cannot tell
    # two guards apart.
    with pytest.raises(ValueError, match="tenant context requires workspace_id"):
        AuthorityContext(
            workspace_id=None, actor_user_id=ids["user_a"],
            internal_role=None, audit_reason=None,
        )
    with pytest.raises(ValueError, match="workspace_id must be a UUID"):
        AuthorityContext.tenant(None, ids["user_a"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="audit_reason requires an internal role"):
        AuthorityContext(
            workspace_id=ids["workspace_a"], actor_user_id=ids["user_a"],
            internal_role=None, audit_reason="a reason with no internal role",
        )

    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=1)
    )
    try:
        database.open(wait=True)
        with database.connection(
            AuthorityContext.tenant(ids["workspace_a"], ids["user_a"])
        ) as connection:
            inside = connection.execute(
                "SELECT current_setting('app.workspace_id', true)"
            ).fetchone()[0]
        assert inside == ids["workspace_a"]

        # The context must not outlive its transaction, and the pool must
        # scrub every key before handing the connection back. One connection
        # in the pool, so this is the same physical session.
        with database.connection(
            AuthorityContext.tenant(ids["workspace_b"], ids["user_b"])
        ) as connection:
            leaked = connection.execute(
                "SELECT %s::text, current_setting('app.workspace_id', true)",
                (ids["workspace_b"],),
            ).fetchone()
        assert leaked[1] == ids["workspace_b"], "the second context did not apply"

        # The pooled connection is scrubbed before it is handed back.
        with database._pool.connection() as raw:
            for key in _CONTEXT_KEYS:
                value = raw.execute(
                    "SELECT current_setting(%s, true)", (key,)
                ).fetchone()[0]
                assert value in (None, ""), (
                    f"{key} survived on the pooled connection as {value!r}"
                )
    finally:
        database.close()

    # `_reset` and the transaction scope of `set_config` are pinned
    # **behaviourally**, one each, below.
    #
    # I had recorded that they could not be — that being redundant defences,
    # each masks the other's absence, so neither is observable alone. A
    # round-eleven reviewer disproved it by isolating one layer at a time,
    # which is the same method this phase already uses on the customer
    # boundary, and built both pins. The claim was wrong and the source-reading
    # assertions it justified are gone.
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=1)
    )
    try:
        database.open(wait=True)
        # Scrub, isolated from scope: set the keys at SESSION scope on a
        # borrowed connection, hand it back, borrow it again. Transaction scope
        # cannot mask this, because nothing here is in a transaction.
        with database._pool.connection() as raw:
            for key in _CONTEXT_KEYS:
                raw.execute("SELECT set_config(%s, 'leaked', false)", (key,))
        with database._pool.connection() as raw:
            for key in _CONTEXT_KEYS:
                assert raw.execute(
                    "SELECT current_setting(%s, true)", (key,)
                ).fetchone()[0] in (None, ""), (
                    f"{key} survived a pooled connection being handed back"
                )
    finally:
        database.close()

    # Scope, isolated from scrub: a pool whose _reset does not scrub. If the
    # context were session-scoped it would now outlive its transaction.
    class Unscrubbed(PostgresDatabase):
        @staticmethod
        def _reset(connection: psycopg.Connection) -> None:
            connection.execute("SET search_path TO pg_catalog")
            connection.commit()

    database = Unscrubbed(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=1)
    )
    try:
        database.open(wait=True)
        with database.connection(
            AuthorityContext.tenant(ids["workspace_a"], ids["user_a"])
        ):
            pass
        with database._pool.connection() as raw:
            for key in _CONTEXT_KEYS:
                assert raw.execute(
                    "SELECT current_setting(%s, true)", (key,)
                ).fetchone()[0] in (None, ""), (
                    f"{key} outlived the transaction that set it"
                )
    finally:
        database.close()


def test_a_read_writes_exactly_one_audit_row_even_if_assembly_fails(
    postgres_database: tuple[str, str, str],
) -> None:
    """The guard used to span page assembly, so one read could write two rows.

    The success row commits with the transaction; anything raising afterwards
    made the guard add a `failed` row beside it. Both round-ten reviewers found
    it independently and neither could trigger it with data — it is a structural
    asymmetry the round-nine wrapper introduced, against a contract that says
    exactly one row. `get_opportunity` never had it, because it already closed
    its guard before assembling its result.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the single audit row",
    )
    # Captured from __dict__ so it restores as a *staticmethod*. Reassigning
    # the bound function turns it into an instance method and every later test
    # in the session gets `self` passed as `sources`.
    original = InternalOpportunityIndex.__dict__["_conflicts"]
    try:
        index.ingest_workspace(owner, ids["workspace_a"])

        def explode(sources: object) -> tuple[()]:
            raise RuntimeError("induced failure during page assembly")

        InternalOpportunityIndex._conflicts = staticmethod(explode)  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            index.list_opportunities(owner, limit=5)
    finally:
        InternalOpportunityIndex._conflicts = original  # type: ignore[assignment]
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        listed = connection.execute(
            "SELECT result, count(*) FROM medawarcre.staff_audit_log "
            "WHERE action='list' GROUP BY result"
        ).fetchall()
    assert listed == [("succeeded", 1)], (
        f"one read wrote more than one audit row: {listed!r}"
    )


def test_only_owner_and_admin_may_mutate_the_index(
    postgres_database: tuple[str, str, str],
) -> None:
    """Widening `MUTATING_ROLES` survived every scope a reviewer tried.

    It fails closed at layer three — the RLS `WITH CHECK` refuses the write —
    but the audited result degrades from `denied` to `failed`, so the log stops
    distinguishing "this role may not do that" from "the database refused".
    `internal_can_mutate()` narrows writes to `owner` and `admin`; the
    repository is meant to say so first.
    """
    from cre_mcp.postgres.opportunity_index import INTERNAL_ROLES, MUTATING_ROLES

    assert MUTATING_ROLES == {"owner", "admin"}
    reading_only = INTERNAL_ROLES - MUTATING_ROLES
    assert reading_only == {
        "jv_operations", "support", "security_audit", "read_only_analyst"
    }

    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    # staff_roles is keyed on user_id alone — one role per person — so each
    # reading role needs its own member of staff.
    staff: dict[str, str] = {}
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        connection.execute("SET ROLE medawarcre_migration")
        for role in sorted(reading_only):
            actor = str(uuid4())
            staff[role] = actor
            connection.execute(
                "INSERT INTO medawarcre.users(id,email,name) VALUES (%s,%s,%s)",
                (actor, f"{role}@example.test", role),
            )
            connection.execute(
                "INSERT INTO medawarcre.staff_roles(user_id,role,active) "
                "VALUES (%s,%s,true)",
                (actor, role),
            )
        connection.commit()

    index = _index_for(app_dsn)
    try:
        for role in sorted(reading_only):
            request = StaffRequest(
                actor_user_id=staff[role], role=role,
                reason_code="quality_audit", reason=f"attempting as {role}",
            )
            # Refused by the repository, and refused as *denied* — not as a
            # database failure that happens to have the same outcome.
            with pytest.raises(PermissionError):
                index.ingest_workspace(request, ids["workspace_a"])
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        results = connection.execute(
            "SELECT DISTINCT result FROM medawarcre.staff_audit_log "
            "WHERE action='ingest'"
        ).fetchall()
    assert results == [("denied",)], (
        f"a read-only role's refusal was not recorded as denied: {results!r}"
    )


def test_a_cursor_that_is_not_a_uuid_is_refused_before_it_reaches_sql(
    postgres_database: tuple[str, str, str],
) -> None:
    """The coarse split is pinned; the `UUID()` half was not.

    `…|not-a-uuid` reached SQL as a raw `InvalidTextRepresentation`, which the
    contract forbids: filter arguments are validated before they reach SQL, both
    the name and the value.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="pipeline_review", reason="a malformed cursor",
    )
    try:
        for cursor in (
            "2026-08-08T00:00:00+00:00|not-a-uuid",
            "2026-08-08T00:00:00+00:00|",
            "not-a-timestamp|00000000-0000-0000-0000-000000000001",
        ):
            with pytest.raises(ValueError, match="invalid pagination cursor"):
                index.list_opportunities(owner, limit=5, cursor=cursor)
    finally:
        index.close()


def test_every_member_of_the_transient_retry_set_is_pinned(
    postgres_database: tuple[str, str, str],
) -> None:
    """`LockNotAvailable` was in `_TRANSIENT` and verified by nothing.

    `attempts` and `ForeignKeyViolation` were each pinned, so the retry looked
    covered — the same shape that hid the foreign-key gap two rounds ago. A
    `lock_timeout` of 5,000ms is the shipped default, so this member is reachable
    in production, and the contract requires ingestion to retry rather than
    surface a lock cycle to staff.
    """
    from cre_mcp.postgres.opportunity_index import _TRANSIENT

    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning every transient member",
    )
    real = index._ingest_workspace
    try:
        for error in (
            psycopg.errors.DeadlockDetected,
            psycopg.errors.SerializationFailure,
            psycopg.errors.LockNotAvailable,
            psycopg.errors.ForeignKeyViolation,
        ):
            assert error in _TRANSIENT, f"{error.__name__} left the retry set"
            attempts: list[int] = []

            def flaky(
                request: StaffRequest, workspace_id: str, _raise: type = error
            ) -> object:
                attempts.append(1)
                if len(attempts) == 1:
                    raise _raise("induced")
                return real(request, workspace_id)

            index._ingest_workspace = flaky  # type: ignore[method-assign]
            summary = index.ingest_workspace(owner, ids["workspace_a"])
            assert len(attempts) == 2, (
                f"{error.__name__} was not retried; a whole batch is lost"
            )
            assert summary.admitted == 1
    finally:
        index._ingest_workspace = real  # type: ignore[method-assign]
        index.close()


def test_a_score_conflict_attributes_the_users_who_hold_each_position(
    postgres_database: tuple[str, str, str],
) -> None:
    """`_conflicts` builds positions in two places; only one was read.

    Round ten fixed the truthiness check on the shared outcome/stage/
    property_type loop. The score branch has its own `ConflictPosition`
    literal, and substituting `workspace_id` for `source_user_id` there survived
    every scope — so "every side attributed" was still half unmeasured.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", score=10.0,
        )
        _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", score=95.0,
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning score attribution",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])
        entry = index.list_opportunities(owner, limit=5).entries[0]
    finally:
        index.close()

    score = next(c for c in entry.conflicts if c.kind == "score")
    assert {position.source_user_id for position in score.positions} == {
        ids["user_a"], ids["user_b"]
    }, "the score conflict does not name the users who hold each position"
    assert {position.value for position in score.positions} == {"10", "95"}
    assert all(
        position.source_user_id != position.workspace_id
        for position in score.positions
    )


def test_filter_scores_must_be_finite(
    postgres_database: tuple[str, str, str],
) -> None:
    """`inf` returned nothing, `-inf` everything and `nan` nothing, silently.

    No `ValueError` and no database error — a staff filter answering a question
    nobody asked. `deals_score_finite_check` shows the schema already treats
    non-finite numerics as a hazard.
    """
    for value in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueError, match="finite"):
            OpportunityFilters(min_score=value)
        with pytest.raises(ValueError, match="finite"):
            OpportunityFilters(max_score=value)
    # Ordinary bounds still pass.
    assert OpportunityFilters(min_score=0, max_score=100).max_score == 100


def test_one_workspace_disagreeing_with_itself_is_not_a_cross_tenant_conflict(
    postgres_database: tuple[str, str, str],
) -> None:
    """`_conflicts` partitioned by source row, so a tenant fought itself.

    `deals` is unique on `(workspace_id, source, source_record_id)`, so one
    tenant saving one building from two providers is the designed-for path. It
    produced a full conflict report naming the same workspace and the same user
    on both sides — `distinct workspaces holding positions: 1` — against a
    contract clause that says "the index states that **the workspaces**
    disagree and who holds which position".
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for provider, stage, score, kind in (
            ("loopnet", "lead", 41.0, "mixed_use"),
            ("crexi", "closing", 88.0, "office"),
        ):
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "INSERT INTO medawarcre.deals("
                "workspace_id,source,source_record_id,title,listing,stage,score,"
                "score_version,created_by_user_id,updated_by_user_id) "
                "VALUES (%s,%s,'r-1','A property',"
                "jsonb_build_object('source',%s::text,'source_id','r-1',"
                "'name','A property','address','100 Main St','city','Dallas',"
                "'state','TX','zip_code','75201','url','',"
                "'property_type',%s::text),"
                "%s::text,%s::numeric,'score-v3',%s::uuid,%s::uuid)",
                (
                    ids["workspace_a"], provider, provider, kind, stage, score,
                    ids["user_a"], ids["user_a"],
                ),
            )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="one tenant, two providers",
    )
    try:
        summary = index.ingest_workspace(owner, ids["workspace_a"])
        assert summary.admitted == 2
        entry = index.list_opportunities(owner, limit=5).entries[0]
    finally:
        index.close()

    assert len(entry.sources) == 2
    assert len({source.workspace_id for source in entry.sources}) == 1
    assert entry.conflicts == (), (
        f"one workspace was reported as disagreeing with itself: "
        f"{entry.conflicts!r}"
    )
    # Blank label, empty conflict tuple — the contract states this shape
    # explicitly and nothing asserted it.
    assert entry.property_type is None


def test_a_stage_conflict_between_workspaces_is_reported(
    postgres_database: tuple[str, str, str],
) -> None:
    """The stage half of conflict detection was unpinned.

    Two reviewers measured `if False` on the shared loop surviving for stage
    while score was killed, so the carried-list entry naming both was wrong in
    one direction.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="lead", score=50.0,
        )
        _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="closing", score=55.0,
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning stage conflicts",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])
        entry = index.list_opportunities(owner, limit=5).entries[0]
    finally:
        index.close()

    stage = next(c for c in entry.conflicts if c.kind == "stage")
    assert {position.value for position in stage.positions} == {"lead", "closing"}
    assert {position.workspace_id for position in stage.positions} == {
        ids["workspace_a"], ids["workspace_b"]
    }
    # Scores 50 and 55 are inside the 20-point tolerance, so no score conflict.
    assert not any(c.kind == "score" for c in entry.conflicts)


def test_every_audit_row_identifies_the_object_it_acted_on(
    postgres_database: tuple[str, str, str],
) -> None:
    """`object_id` was read by exactly one assertion, for one of eleven shapes.

    The contract enumerates object id alongside object type. Round nine repaired
    `object_type`, which had been a constant for nine rounds because nothing
    read it — and the repair's own test is named "the kind of object its id
    refers to" while reading only the type. Six independent mutations replacing
    `object_id` with a constant survived every scope.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for number, address in enumerate(("100 Main St", "200 Elm St")):
            _deal(
                connection, ids["workspace_a"], ids["user_a"],
                source_record_id=f"a-{number}", address=address, city="Dallas",
                state="TX", zip_code="75201",
            )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="duplicate_review", reason="pinning object ids",
    )
    analyst = StaffRequest(
        actor_user_id=ids["analyst"], role="read_only_analyst",
        reason_code="quality_audit", reason="a refused mutation",
    )
    absent = str(uuid4())
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        by_address = {
            entry.property_identity["address"]: entry.opportunity_id
            for entry in index.list_opportunities(owner, limit=10).entries
        }
        superseded, head = by_address["100 MAIN ST"], by_address["200 ELM ST"]

        index.get_opportunity(owner, superseded)
        index.record_review(owner, opportunity_id=superseded, verdict="dismiss")
        index.merge_opportunities(
            owner, opportunity_id=superseded, into_opportunity_id=head
        )
        index.unmerge_opportunity(owner, opportunity_id=superseded)
        with pytest.raises(LookupError):
            index.get_opportunity(owner, absent)
        with pytest.raises(PermissionError):
            index.ingest_workspace(analyst, ids["workspace_a"])
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        rows = connection.execute(
            "SELECT action, result, object_type, object_id "
            "FROM medawarcre.staff_audit_log ORDER BY action, result"
        ).fetchall()

    seen = {(action, result): (kind, str(oid)) for action, result, kind, oid in rows}
    # Every entry-scoped action names the entry it acted on, not a constant.
    for action in ("inspect", "review", "merge", "unmerge"):
        kind, oid = seen[(action, "succeeded")]
        assert kind == "internal_opportunity"
        assert oid == superseded, f"{action} named {oid}, not the entry"
    # An ingest names its workspace; a denied ingest names it too.
    assert seen[("ingest", "succeeded")] == ("workspace", ids["workspace_a"])
    assert seen[("ingest", "denied")] == ("workspace", ids["workspace_a"])
    # A refused inspect names the id that was probed for.
    assert seen[("inspect", "failed")] == ("internal_opportunity", absent)
    # And a listing names the index rather than any one entry.
    assert seen[("list", "succeeded")] == (
        "internal_opportunity_index", "internal_opportunity_index"
    )


def test_a_multi_facet_filter_is_answered_by_one_source_row(
    postgres_database: tuple[str, str, str],
) -> None:
    """The combined `EXISTS` is the per-source AND semantics, and was unpinned.

    Splitting it into one `EXISTS` per predicate survives all focused tests and
    changes answers — `workspace A AND stage=loi` goes from 0 entries to 1 when
    no single row in A is at that stage. That is exactly the cross-tenant
    confusion the filter clause exists to prevent.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        # Every facet carries a distinguishing value, so the AND is exercised
        # across all seven. An earlier version set no `property_type` and made
        # no `deal_outcomes` row, so those two were never combined with
        # anything — the pin was written to the reproduction it came from
        # rather than to the rule, and splitting either out of the combined
        # EXISTS survived all 5,115 tests.
        a_deal = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="lead", score=10.0,
            property_type="office",
        )
        b_deal = _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="loi", score=90.0,
            property_type="retail",
        )
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.deal_outcomes("
            "workspace_id,deal_id,closed,went_bad,purchase_price) "
            "VALUES (%s,%s,false,true,NULL),(%s,%s,true,false,1000000)",
            (ids["workspace_a"], a_deal, ids["workspace_b"], b_deal),
        )
        # A *second member* of workspace A, with a row that differs from the
        # first member's on stage and score.
        #
        # Without this, `source_user_id` and `workspace_id` select identical
        # rows in every database fixture in this phase — `_seed` gives each
        # workspace one member and all 83 deal call sites pair
        # `workspace_a↔user_a`. Round fourteen found that correlation hiding a
        # `_conflicts` defect and it was broken only in the pure-Python tests;
        # both round-fifteen reviewers then found the filter path still blind,
        # so splitting `source_user_id` out of the shared EXISTS survived all
        # 359 PostgreSQL tests.
        second_member = str(uuid4())
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name) "
            "VALUES (%s,'second@example.test','Second')",
            (second_member,),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'member','active')",
            (ids["workspace_a"], second_member),
        )
        connection.commit()
        _deal(
            connection, ids["workspace_a"], second_member,
            source_record_id="a-2", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="closing", score=70.0,
            property_type="industrial",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="pipeline_review", reason="pinning per-source semantics",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])

        def count(**filters: object) -> int:
            return len(
                index.list_opportunities(
                    owner, filters=OpportunityFilters(**filters), limit=20
                ).entries
            )

        # One entry, two sources. Each facet alone matches.
        assert count(workspace_id=ids["workspace_a"]) == 1
        assert count(stage="loi") == 1
        assert count(min_score=50.0) == 1
        # Combined, they must be satisfied by the SAME source row. Workspace A's
        # only row is at `lead` with score 10, so these are all empty.
        assert count(workspace_id=ids["workspace_a"], stage="loi") == 0, (
            "the facets were matched against different source rows"
        )
        # Workspace A now has two rows — user_a at 10 and second_member at 70 —
        # so this combination is genuinely satisfied by the second member's row.
        assert count(workspace_id=ids["workspace_a"], min_score=50.0) == 1
        # And one no row in A satisfies.
        assert count(workspace_id=ids["workspace_a"], min_score=80.0) == 0
        assert count(stage="lead", min_score=50.0) == 0
        # And workspace B's row satisfies both together.
        assert count(workspace_id=ids["workspace_b"], stage="loi") == 1

        # The two facets the earlier fixture could not reach. A's row is
        # office/lead/10/went_bad; B's is retail/loi/90/closed. Every
        # cross-pairing must be empty.
        assert count(property_type="office") == 1
        assert count(outcome="went_bad") == 1
        assert count(property_type="office", stage="loi") == 0, (
            "property_type was matched against a different source row"
        )
        assert count(property_type="retail", stage="lead") == 0
        assert count(outcome="went_bad", stage="loi") == 0, (
            "outcome was matched against a different source row"
        )
        assert count(outcome="closed", stage="lead") == 0
        assert count(property_type="office", outcome="closed") == 0
        assert count(property_type="office", min_score=50.0) == 0
        assert count(outcome="went_bad", workspace_id=ids["workspace_b"]) == 0
        # And each row satisfies its own combination.
        assert count(property_type="office", stage="lead", outcome="went_bad") == 1
        assert count(property_type="retail", stage="loi", outcome="closed") == 1

        # The last two facets, which no fixture could previously distinguish.
        # Workspace A now has two members: user_a at lead/10/office and
        # `second_member` at closing/70/industrial.
        assert count(source_user_id=ids["user_a"]) == 1
        assert count(source_user_id=second_member) == 1
        assert count(source_user_id=ids["user_a"], stage="closing") == 0, (
            "source_user_id was matched against a different source row"
        )
        assert count(source_user_id=second_member, stage="lead") == 0
        assert count(source_user_id=ids["user_a"], min_score=50.0) == 0
        assert count(source_user_id=ids["user_a"], stage="lead") == 1

        # max_score, which appeared in this test not at all.
        assert count(max_score=20.0) == 1
        assert count(max_score=20.0, stage="closing") == 0, (
            "max_score was matched against a different source row"
        )
        assert count(max_score=20.0, stage="loi") == 0
        assert count(max_score=20.0, property_type="industrial") == 0
        assert count(max_score=20.0, stage="lead") == 1
        assert count(min_score=60.0, max_score=80.0, stage="closing") == 1
        assert count(min_score=60.0, max_score=80.0, stage="loi") == 0
    finally:
        index.close()


def _multi_provider_deal(
    connection: psycopg.Connection, workspace: str, user: str, *,
    provider: str, address: str, stage: str, score: float, property_type: str,
) -> None:
    """One building saved from a named provider — the ordinary tenant path.

    `deals` is unique on `(workspace_id, source, source_record_id)`, so the same
    property arriving from two providers is two rows in one workspace.
    """
    connection.execute("SET ROLE medawarcre_migration")
    connection.execute(
        "INSERT INTO medawarcre.deals("
        "workspace_id,source,source_record_id,title,listing,stage,score,"
        "score_version,created_by_user_id,updated_by_user_id) "
        "VALUES (%s,%s,'r-1','A property',"
        "jsonb_build_object('source',%s::text,'source_id','r-1',"
        "'name','A property','address',%s::text,'city','Dallas',"
        "'state','TX','zip_code','75201','url','',"
        "'property_type',%s::text),"
        "%s::text,%s::numeric,'score-v3',%s::uuid,%s::uuid)",
        (
            workspace, provider, provider, address, property_type,
            stage, score, user, user,
        ),
    )


def test_two_workspaces_holding_identical_views_are_not_in_conflict(
    postgres_database: tuple[str, str, str],
) -> None:
    """Counting distinct values and distinct workspaces is the wrong question.

    Round twelve's repair required "more than one value AND more than one
    workspace", which two tenants who each saved the building from the same two
    providers satisfy while agreeing exactly. Both round-thirteen reviewers
    measured three cross-tenant conflicts on identical views.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for workspace, user in (
            (ids["workspace_a"], ids["user_a"]),
            (ids["workspace_b"], ids["user_b"]),
        ):
            for provider, stage, score, kind in (
                ("loopnet", "closing", 41.0, "office"),
                ("crexi", "lead", 88.0, "retail"),
            ):
                _multi_provider_deal(
                    connection, workspace, user, provider=provider,
                    address="100 Main St", stage=stage, score=score,
                    property_type=kind,
                )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="identical views",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])
        entry = index.list_opportunities(owner, limit=5).entries[0]
    finally:
        index.close()

    assert len(entry.sources) == 4
    assert len({source.workspace_id for source in entry.sources}) == 2
    assert entry.conflicts == (), (
        f"two workspaces holding identical views were reported as "
        f"disagreeing: {entry.conflicts!r}"
    )
    # The state the contract and the docstring describe, which no test read:
    # agreement, and still no single label, because the observations name two
    # types. Returning either one would be the smoothing the contract forbids.
    assert entry.property_type is None, (
        "a label was picked although the observations name two types"
    )


def test_a_score_conflict_measures_the_gap_between_workspaces(
    postgres_database: tuple[str, str, str],
) -> None:
    """The score branch got a presence gate, not a between-workspace measure.

    Gating on "more than one workspace exists" and then measuring `max − min`
    over every row let one tenant's own split supply the magnitude. Here the
    worst cross-workspace gap is 15 against a 20-point tolerance, while
    workspace A contradicts itself by 30.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for provider, score in (("loopnet", 10.0), ("crexi", 40.0)):
            _multi_provider_deal(
                connection, ids["workspace_a"], ids["user_a"],
                provider=provider, address="100 Main St", stage="lead",
                score=score, property_type="office",
            )
        _multi_provider_deal(
            connection, ids["workspace_b"], ids["user_b"],
            provider="loopnet", address="100 Main St", stage="lead",
            score=25.0, property_type="office",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="within-workspace spread",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])
        entry = index.list_opportunities(owner, limit=5).entries[0]
    finally:
        index.close()

    assert not any(c.kind == "score" for c in entry.conflicts), (
        "a within-workspace spread was reported as workspaces disagreeing: "
        f"{entry.conflicts!r}"
    )


def test_get_opportunity_reports_the_same_conflicts_the_listing_does(
    postgres_database: tuple[str, str, str],
) -> None:
    """`detail.entry.conflicts` was read by no test at any scope.

    Returning `()` from `get_opportunity` survived everything, and that is the
    single-entry read staff use to inspect one property — the place conflict
    reporting matters most.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="lead", score=10.0,
            property_type="office",
        )
        _deal(
            connection, ids["workspace_b"], ids["user_b"],
            source_record_id="b-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201", stage="closing", score=90.0,
            property_type="industrial",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="genuine disagreement",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])
        listed = index.list_opportunities(owner, limit=5).entries[0]
        detail = index.get_opportunity(owner, listed.opportunity_id)
    finally:
        index.close()

    # Genuine cross-workspace disagreement on all three kinds.
    kinds = {conflict.kind for conflict in listed.conflicts}
    assert kinds == {"stage", "property_type", "score"}, kinds
    assert {c.kind for c in detail.entry.conflicts} == kinds, (
        "get_opportunity does not report the conflicts the listing does"
    )
    for kind in kinds:
        listed_positions = {
            (p.workspace_id, p.source_user_id, p.value)
            for c in listed.conflicts if c.kind == kind for p in c.positions
        }
        detail_positions = {
            (p.workspace_id, p.source_user_id, p.value)
            for c in detail.entry.conflicts if c.kind == kind for p in c.positions
        }
        assert listed_positions == detail_positions
        assert len({w for w, _u, _v in listed_positions}) == 2


# --------------------------------------------------------------------------
# Round fourteen. `_conflicts` is exercised directly here: eight mutations of
# it survived every scope, because the rule is about *which* values are
# compared and *how* the ends combine, and no database fixture in this phase
# distinguishes those choices.
# --------------------------------------------------------------------------


def _source(
    workspace: str, user: str, *,
    stage: str | None = None, outcome: str | None = None,
    property_type: str | None = None, score: float | None = None,
) -> object:
    """A minimal OpportunitySource for exercising `_conflicts` directly."""
    from cre_mcp.postgres.opportunity_index import OpportunitySource

    return OpportunitySource(
        workspace_id=workspace, workspace_public_id=f"ws_{workspace}",
        source_user_id=user, origin="deal", source_deal_id=str(uuid4()),
        source_search_result_id=None, source_saved_search_id=None,
        source="fixture", source_record_id=str(uuid4()), access_class="private",
        score=score, score_version="v1", stage=stage, outcome=outcome,
        observed_property_identity={}, observed_market="Dallas, TX",
        observed_property_type=property_type, provenance={},
        first_observed_at=datetime.now(timezone.utc),
        last_observed_at=datetime.now(timezone.utc),
    )


def _kinds(sources: list[object]) -> set[str]:
    return {c.kind for c in InternalOpportunityIndex._conflicts(sources)}


def test_conflicts_partition_by_workspace_and_not_by_user() -> None:
    """Every fixture in this phase correlates workspace with user exactly.

    `_seed` inserts one membership per workspace and all 83 deal call sites
    pair `workspace_a↔user_a`, so partitioning by `source_user_id` instead of
    `workspace_id` survived every scope — a structural blind spot in the
    fixtures, not a missing assertion. One workspace with two members is what
    tells the two rules apart.
    """
    two_members = [
        _source("ws-A", "user-1", stage="lead", score=10.0, outcome="open",
                property_type="office"),
        _source("ws-A", "user-2", stage="closing", score=95.0, outcome="closed",
                property_type="retail"),
    ]
    assert _kinds(two_members) == set(), (
        "one workspace with two members was reported as a cross-tenant conflict"
    )

    # The same values split across two workspaces *is* a conflict.
    two_workspaces = [
        _source("ws-A", "user-1", stage="lead", score=10.0, outcome="open",
                property_type="office"),
        _source("ws-B", "user-2", stage="closing", score=95.0, outcome="closed",
                property_type="retail"),
    ]
    assert _kinds(two_workspaces) == {"stage", "score", "outcome", "property_type"}


def test_a_score_conflict_compares_both_ends_of_each_workspace_range() -> None:
    """Which ends are compared, and how they combine, was unpinned entirely.

    Four mutations survived every scope: taking `min` instead of `max` of the
    two end-differences, comparing only high ends, comparing only low ends, and
    building the high end with `min()`. Each hides a real 40-to-50-point
    cross-workspace disagreement.
    """
    # A 50-point gap that only the *high* ends reveal.
    high_end_gap = [
        _source("ws-A", "user-1", score=50.0),
        _source("ws-B", "user-2", score=50.0),
        _source("ws-B", "user-2", score=100.0),
    ]
    assert "score" in _kinds(high_end_gap), "a 50-point high-end gap was hidden"

    # A 40-point gap that only the *low* ends reveal.
    low_end_gap = [
        _source("ws-A", "user-1", score=0.0),
        _source("ws-A", "user-1", score=60.0),
        _source("ws-B", "user-2", score=40.0),
        _source("ws-B", "user-2", score=60.0),
    ]
    assert "score" in _kinds(low_end_gap), "a 40-point low-end gap was hidden"

    # And one that only the high ends reveal, with the low ends identical.
    other_end = [
        _source("ws-A", "user-1", score=40.0),
        _source("ws-A", "user-1", score=100.0),
        _source("ws-B", "user-2", score=40.0),
        _source("ws-B", "user-2", score=60.0),
    ]
    assert "score" in _kinds(other_end), "a 40-point gap at one end was hidden"

    # Ranges that coincide within tolerance are agreement, however wide.
    agreeing = [
        _source("ws-A", "user-1", score=10.0),
        _source("ws-A", "user-1", score=90.0),
        _source("ws-B", "user-2", score=15.0),
        _source("ws-B", "user-2", score=95.0),
    ]
    assert "score" not in _kinds(agreeing)


def test_the_score_tolerance_boundary_is_exclusive() -> None:
    """`> 20.0` versus `>= 20.0` survived every scope.

    The contract says scores that differ *beyond* a fixed tolerance, so exactly
    at the tolerance is agreement.
    """
    exactly_at = [
        _source("ws-A", "user-1", score=0.0),
        _source("ws-B", "user-2", score=20.0),
    ]
    assert "score" not in _kinds(exactly_at), (
        "a gap exactly at the tolerance was reported as a conflict"
    )
    just_beyond = [
        _source("ws-A", "user-1", score=0.0),
        _source("ws-B", "user-2", score=20.01),
    ]
    assert "score" in _kinds(just_beyond)


def test_a_workspace_that_declared_nothing_is_not_a_position() -> None:
    """Dropping the `is not None` filter fabricates a conflict from absence.

    A workspace that never declared an outcome became a position with the
    literal value `'None'`, against a rule that requires two workspaces whose
    *views* differ.
    """
    one_declared = [
        _source("ws-A", "user-1", outcome="closed"),
        _source("ws-B", "user-2", outcome=None),
    ]
    assert "outcome" not in _kinds(one_declared), (
        "a workspace that declared nothing was treated as disagreeing"
    )
    # Two workspaces that both declared, differently, is a conflict.
    both_declared = [
        _source("ws-A", "user-1", outcome="closed"),
        _source("ws-B", "user-2", outcome="went_bad"),
    ]
    assert "outcome" in _kinds(both_declared)


def test_a_declared_type_survives_a_workspace_that_declared_none() -> None:
    """The absence filter in `_derived_property_type` was unpinned.

    One workspace declares a type and another declares nothing is the commonest
    real shape, since `Listing.property_type` is `str | None`. Deleting the
    `is not None` filter turned that into a blank label — and made the docstring
    corrected the round before false, since it says a blank label means the
    observations name more than one type, not that one named nothing.
    """
    from cre_mcp.postgres.opportunity_index import _derived_property_type

    one_declared = [
        _source("ws-A", "user-1", property_type="office"),
        _source("ws-B", "user-2", property_type=None),
    ]
    assert _derived_property_type(one_declared) == "office", (
        "a workspace declaring nothing erased another workspace's declared type"
    )
    assert _derived_property_type(
        [_source("ws-A", "user-1", property_type=None)]
    ) is None
    assert _derived_property_type([
        _source("ws-A", "user-1", property_type="office"),
        _source("ws-B", "user-2", property_type="retail"),
    ]) is None


def test_conflict_positions_are_per_observation_not_per_workspace(
    postgres_database: tuple[str, str, str],
) -> None:
    """The contract says one workspace may legitimately appear on two sides.

    Collapsing positions to one per workspace survived every scope. The conflict
    is *between* workspaces; the positions show every observation behind it, and
    a workspace holding two values shows twice.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        for provider, kind in (("loopnet", "office"), ("crexi", "retail")):
            _multi_provider_deal(
                connection, ids["workspace_a"], ids["user_a"],
                provider=provider, address="100 Main St", stage="lead",
                score=50.0, property_type=kind,
            )
        _multi_provider_deal(
            connection, ids["workspace_b"], ids["user_b"],
            provider="loopnet", address="100 Main St", stage="lead",
            score=50.0, property_type="industrial",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="per-observation positions",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
        index.ingest_workspace(owner, ids["workspace_b"])
        entry = index.list_opportunities(owner, limit=5).entries[0]
    finally:
        index.close()

    conflict = next(c for c in entry.conflicts if c.kind == "property_type")
    assert len(conflict.positions) == 3, (
        f"positions were collapsed per workspace: {conflict.positions!r}"
    )
    from collections import Counter

    per_workspace = Counter(p.workspace_id for p in conflict.positions)
    assert per_workspace[ids["workspace_a"]] == 2, (
        "the workspace holding two values appears only once"
    )
    assert {p.value for p in conflict.positions} == {
        "office", "retail", "industrial"
    }


def test_an_observation_points_back_at_the_tenant_row_it_came_from(
    postgres_database: tuple[str, str, str],
) -> None:
    """`(source, source_record_id)` transposed still joins to nothing.

    The only assertion touching them was `assert source.source or
    source.source_record_id` — a truthiness OR that a transposition satisfies on
    both halves. `(workspace_id, source, source_record_id)` is the unique key of
    both `deals` and `internal_opportunity_sources`, so a transposition is
    self-consistent: dedup and re-ingest keep working while no observation can
    be traced to the record it came from. Retention item 9.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn) as connection:
        ids = _seed(connection)
        _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )

    index = _index_for(app_dsn)
    owner = StaffRequest(
        actor_user_id=ids["owner"], role="owner",
        reason_code="ingestion", reason="pinning the provenance pointer",
    )
    try:
        index.ingest_workspace(owner, ids["workspace_a"])
    finally:
        index.close()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        joined = connection.execute(
            "SELECT s.source, s.source_record_id, d.source, d.source_record_id "
            "FROM medawarcre.internal_opportunity_sources s "
            "JOIN medawarcre.deals d "
            "  ON d.workspace_id = s.workspace_id "
            " AND d.source = s.source "
            " AND d.source_record_id = s.source_record_id"
        ).fetchall()
    assert len(joined) == 1, (
        "no index observation joins back to the tenant record it cites"
    )
    assert joined[0][0] == "fixture" and joined[0][1] == "a-1"
    assert joined[0][:2] == joined[0][2:]


def test_the_keyset_cursor_orders_on_the_whole_key() -> None:
    """The contract requires a *total* order; only half of it was pinned.

    Dropping the tie-breaking `id` from the cursor comparison survives every
    scope. Two entries created in the same statement share `created_at`, so
    without the tie-break a page boundary between them skips or repeats one.
    """
    from pathlib import Path

    module = (
        Path(__file__).resolve().parents[2]
        / "src" / "cre_mcp" / "postgres" / "opportunity_index.py"
    ).read_text()
    assert '"(o.created_at, o.id) < (%s, %s)"' in module, (
        "the keyset cursor no longer compares the whole ordering key"
    )
    assert '" ORDER BY o.created_at DESC, o.id DESC LIMIT %s"' in module
