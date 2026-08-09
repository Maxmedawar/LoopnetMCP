"""Behavioural pins for the internal opportunity index's *database* guards.

Round seven's finding, and the reason this file exists: every CHECK constraint,
every row-level-security policy, and half the merge trigger on the Phase 5K
relations were "verified" only by `EXPECTED_CATALOG_FINGERPRINT`. A reviewer
demonstrated the consequence end to end — delete an implication from
`internal_opportunities_merge_check`, recompute the fingerprint, patch the
constant, and all 321 PostgreSQL tests pass.

A fingerprint is a **drift detector**: it tells you the schema changed without
your noticing. It is not a **behaviour pin**: it says nothing about what the
schema does, and it is refreshed as routine — seven times in this phase. Treating
one as the other is how the reviews RLS layer, the merge-target-is-merged check,
and eleven CHECK constraints came to be covered by nothing.

Each test below states a rule in the form "the database refuses this", so
reverting the guard fails the test rather than merely moving a hash.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from cre_mcp.postgres.migrations import MigrationRunner, load_migrations


def _entry(connection: psycopg.Connection, key: str, **columns: object) -> str:
    identifier = str(uuid4())
    fields = {"status": "active", **columns}
    assignments = "".join(f",{name}" for name in fields)
    placeholders = "".join(",%s" for _ in fields)
    connection.execute(
        f"INSERT INTO medawarcre.internal_opportunities("
        f"id,canonical_key,title,property_identity,normalized_facts{assignments}) "
        f"VALUES (%s,%s,'t','{{}}'::jsonb,'{{}}'::jsonb{placeholders})",
        (identifier, key, *fields.values()),
    )
    return identifier


@pytest.fixture
def migrated(postgres_database: tuple[str, str, str]) -> tuple[str, str]:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    return admin_dsn, app_dsn


# --------------------------------------------------------------------------
# CHECK constraints on the entry.
# --------------------------------------------------------------------------


def test_the_entry_check_constraints_refuse_what_they_declare(
    migrated: tuple[str, str],
) -> None:
    admin_dsn, _ = migrated
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        canonical = _entry(connection, "k-canonical")

        # merged implies a link...
        with pytest.raises(psycopg.errors.CheckViolation):
            _entry(connection, "k-1", status="merged")
        # ...and a link implies one of the three statuses that may carry it.
        with pytest.raises(psycopg.errors.CheckViolation):
            _entry(
                connection, "k-2", status="active",
                merged_into_opportunity_id=canonical,
            )
        # Each status that may carry a link is genuinely accepted, so the rule
        # above is not passing merely because everything is refused.
        for index, status in enumerate(("merged", "archived", "suppressed")):
            _entry(
                connection, f"k-ok-{index}", status=status,
                merged_into_opportunity_id=canonical,
            )

        # No self-merge.
        orphan = _entry(connection, "k-self")
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE medawarcre.internal_opportunities "
                "SET status='merged', merged_into_opportunity_id=id WHERE id=%s",
                (orphan,),
            )

        # last_observed_at may not precede first_observed_at.
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE medawarcre.internal_opportunities "
                "SET last_observed_at = first_observed_at - interval '1 second' "
                "WHERE id=%s",
                (canonical,),
            )

        # canonical_key is bounded and trimmed.
        with pytest.raises(psycopg.errors.CheckViolation):
            _entry(connection, " untrimmed ")
        with pytest.raises(psycopg.errors.CheckViolation):
            _entry(connection, "x" * 513)

        # market is bounded and trimmed.
        with pytest.raises(psycopg.errors.CheckViolation):
            _entry(connection, "k-mkt-1", market=" untrimmed ")
        with pytest.raises(psycopg.errors.CheckViolation):
            _entry(connection, "k-mkt-2", market="x" * 201)

        # property_identity must be an object.
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE medawarcre.internal_opportunities "
                "SET property_identity='[]'::jsonb WHERE id=%s",
                (canonical,),
            )

        # The status vocabulary is closed.
        with pytest.raises(psycopg.errors.CheckViolation):
            _entry(connection, "k-status", status="deleted")


def test_the_source_check_constraints_refuse_what_they_declare(
    postgres_database: tuple[str, str, str],
) -> None:
    from tests.postgres.test_opportunity_index import _deal, _seed

    admin_dsn, migration_dsn, _app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        ids = _seed(connection)
        deal = _deal(
            connection, ids["workspace_a"], ids["user_a"],
            source_record_id="a-1", address="100 Main St", city="Dallas",
            state="TX", zip_code="75201",
        )
        connection.execute("SET ROLE medawarcre_migration")
        entry = _entry(connection, "k-src")

        def source(**columns: object) -> None:
            fields = {
                "workspace_id": ids["workspace_a"],
                "opportunity_id": entry,
                "source": "fixture",
                "source_record_id": str(uuid4()),
                "access_class": "private",
                "score_version": "v1",
                "provenance": "{}",
                "origin": "deal",
                "source_deal_id": deal,
                "observed_property_identity": "{}",
                **columns,
            }
            names = ",".join(fields)
            marks = ",".join(
                "%s::jsonb" if name in ("provenance", "observed_property_identity")
                else "%s"
                for name in fields
            )
            connection.execute(
                f"INSERT INTO medawarcre.internal_opportunity_sources("
                f"{names},source_observed_at) "
                f"VALUES ({marks},statement_timestamp())",
                tuple(fields.values()),
            )

        source()  # the control: an ordinary row is accepted

        with pytest.raises(psycopg.errors.CheckViolation):
            source(origin="imagined")
        # origin must bind to the record it names, both directions.
        with pytest.raises(psycopg.errors.CheckViolation):
            source(origin="deal", source_deal_id=None)
        with pytest.raises(psycopg.errors.CheckViolation):
            source(origin="search_result", source_deal_id=deal)
        with pytest.raises(psycopg.errors.CheckViolation):
            source(observed_property_identity="[]")
        with pytest.raises(psycopg.errors.CheckViolation):
            source(score=101)
        with pytest.raises(psycopg.errors.CheckViolation):
            source(score=-1)
        with pytest.raises(psycopg.errors.CheckViolation):
            source(stage="imagined")
        with pytest.raises(psycopg.errors.CheckViolation):
            source(outcome="imagined")
        with pytest.raises(psycopg.errors.CheckViolation):
            source(access_class="secret")


# --------------------------------------------------------------------------
# The merge trigger. Both branches, at the database, without the repository.
# --------------------------------------------------------------------------


def test_the_merge_trigger_refuses_a_merged_target_and_a_missing_one(
    migrated: tuple[str, str],
) -> None:
    """The target-is-merged branch was pinned only by the fingerprint.

    That is the half of the round-five chain repair that stops "what is this a
    duplicate of?" from answering with a row that is itself merged.
    """
    admin_dsn, _ = migrated
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        head = _entry(connection, "k-head")
        middle = _entry(connection, "k-middle")
        tail = _entry(connection, "k-tail")

        connection.execute(
            "UPDATE medawarcre.internal_opportunities "
            "SET status='merged', merged_into_opportunity_id=%s WHERE id=%s",
            (head, middle),
        )

        # The target is itself merged.
        with pytest.raises(psycopg.errors.CheckViolation, match="itself merged"):
            connection.execute(
                "UPDATE medawarcre.internal_opportunities "
                "SET status='merged', merged_into_opportunity_id=%s WHERE id=%s",
                (middle, tail),
            )
        # The entry is itself a target.
        with pytest.raises(
            psycopg.errors.CheckViolation, match="itself a merge target"
        ):
            connection.execute(
                "UPDATE medawarcre.internal_opportunities "
                "SET status='merged', merged_into_opportunity_id=%s WHERE id=%s",
                (tail, head),
            )
        # The target does not exist.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "UPDATE medawarcre.internal_opportunities "
                "SET status='merged', merged_into_opportunity_id=%s WHERE id=%s",
                (str(uuid4()), tail),
            )


# --------------------------------------------------------------------------
# Row-level security on the review history — layer three for that relation.
# --------------------------------------------------------------------------


def _internal(
    connection: psycopg.Connection, actor: str, role: str, reason: str
) -> None:
    # Session scope, not transaction scope. The repository sets these
    # transaction-locally; here the probes run statement by statement, and a
    # transaction-local setting under autocommit is discarded before the next
    # statement can see it — which makes every probe look like a refusal.
    connection.execute(
        "SELECT set_config('app.actor_user_id',%s,false),"
        "set_config('app.internal_role',%s,false),"
        "set_config('app.audit_reason',%s,false)",
        (actor, role, reason),
    )


def test_review_row_level_security_is_enforced_not_merely_declared(
    postgres_database: tuple[str, str, str],
) -> None:
    """No test observed these policies; only the fingerprint did.

    They are the third layer of the three-layer boundary for
    `internal_opportunity_reviews`, and they carry the forgery guard that stops
    a member of staff writing a review as somebody else.
    """
    from tests.postgres.test_opportunity_index import _seed

    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        ids = _seed(connection)
        connection.execute("SET ROLE medawarcre_migration")
        entry = _entry(connection, "k-review")

    admin = app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admin")

    def insert(
        connection: psycopg.Connection, *, reviewer: str, role: str, reason: str
    ) -> None:
        connection.execute(
            "INSERT INTO medawarcre.internal_opportunity_reviews("
            "opportunity_id,reviewer_user_id,reviewer_role,verdict,"
            "reason_code,reason) VALUES (%s,%s,%s,'dismiss','quality_audit',%s)",
            (entry, reviewer, role, reason),
        )

    # An owner writing as themselves, with their own reason, is accepted.
    with psycopg.connect(admin, autocommit=True) as connection:
        _internal(connection, ids["owner"], "owner", "a stated reason")
        insert(
            connection, reviewer=ids["owner"], role="owner",
            reason="a stated reason",
        )

    # The forgery guard: reviewer, role and reason must each be your own.
    with psycopg.connect(admin) as connection:
        _internal(connection, ids["owner"], "owner", "a stated reason")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            insert(
                connection, reviewer=ids["analyst"], role="owner",
                reason="a stated reason",
            )
        connection.rollback()
        _internal(connection, ids["owner"], "owner", "a stated reason")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            insert(
                connection, reviewer=ids["owner"], role="admin",
                reason="a stated reason",
            )
        connection.rollback()
        _internal(connection, ids["owner"], "owner", "a stated reason")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            insert(
                connection, reviewer=ids["owner"], role="owner",
                reason="a different reason than declared",
            )

    # internal_can_mutate(): a reading role may not write a review.
    with psycopg.connect(admin) as connection:
        _internal(connection, ids["analyst"], "read_only_analyst", "reading")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            insert(
                connection, reviewer=ids["analyst"], role="read_only_analyst",
                reason="reading",
            )

    # internal_authorized(): the read policy, in both directions.
    with psycopg.connect(admin, autocommit=True) as connection:
        _internal(connection, ids["owner"], "owner", "a stated reason")
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.internal_opportunity_reviews"
        ).fetchone()[0] == 1
        # A blank reason is not a reason.
        _internal(connection, ids["owner"], "owner", "   ")
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.internal_opportunity_reviews"
        ).fetchone()[0] == 0
        # A role the actor does not hold is not a role.
        _internal(connection, ids["owner"], "support", "a stated reason")
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.internal_opportunity_reviews"
        ).fetchone()[0] == 0
        # A deactivated staff row fails closed on the next statement.
        connection.execute("RESET ROLE")

    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "UPDATE medawarcre.staff_roles SET active=false WHERE user_id=%s",
            (ids["owner"],),
        )
    with psycopg.connect(admin, autocommit=True) as connection:
        _internal(connection, ids["owner"], "owner", "a stated reason")
        assert connection.execute(
            "SELECT count(*) FROM medawarcre.internal_opportunity_reviews"
        ).fetchone()[0] == 0


def test_the_review_vocabularies_and_non_blank_rules_are_enforced(
    postgres_database: tuple[str, str, str],
) -> None:
    from tests.postgres.test_opportunity_index import _seed

    admin_dsn, migration_dsn, _app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        ids = _seed(connection)
        connection.execute("SET ROLE medawarcre_migration")
        entry = _entry(connection, "k-vocab")

        def review(**columns: object) -> None:
            fields = {
                "opportunity_id": entry,
                "reviewer_user_id": ids["owner"],
                "reviewer_role": "owner",
                "verdict": "dismiss",
                "reason_code": "quality_audit",
                "reason": "a stated reason",
                **columns,
            }
            names = ",".join(fields)
            marks = ",".join("%s" for _ in fields)
            connection.execute(
                f"INSERT INTO medawarcre.internal_opportunity_reviews({names}) "
                f"VALUES ({marks})",
                tuple(fields.values()),
            )

        review()  # control

        with pytest.raises(psycopg.errors.CheckViolation):
            review(reviewer_role="emperor")
        with pytest.raises(psycopg.errors.CheckViolation):
            review(verdict="maybe")
        with pytest.raises(psycopg.errors.CheckViolation):
            review(reason="   ")
        with pytest.raises(psycopg.errors.CheckViolation):
            review(reason_code="   ")
        with pytest.raises(psycopg.errors.CheckViolation):
            review(note="   ")
