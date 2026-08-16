"""Statement translation for the platform bridge, without a database.

These are the rules the bridge applies to every statement the twelve platform
stores emit. They are tested apart from PostgreSQL because a translation defect
and a schema defect fail the same way at the socket, and separating them is the
difference between a five-second answer and a five-minute one.
"""

from __future__ import annotations

import pytest

from cre_mcp.postgres.platform_bridge import (
    PLATFORM_WRITE_LOCK_ID,
    PlatformBridgeError,
    translate,
)


def test_question_marks_outside_literals_become_placeholders() -> None:
    plan = translate("SELECT * FROM platform_users WHERE email=? AND name=?")
    assert plan.kind == "run"
    assert plan.bound_sql.endswith("WHERE email=%s AND name=%s")


def test_question_mark_inside_a_literal_is_left_alone() -> None:
    plan = translate("SELECT * FROM platform_users WHERE name=? AND note='what?'")
    assert plan.bound_sql.count("%s") == 1
    assert "'what?'" in plan.bound_sql


def test_literal_percent_is_doubled_only_for_the_bound_form() -> None:
    plan = translate("SELECT * FROM platform_users WHERE email LIKE '%@x.com'")
    assert plan.bound_sql == "SELECT * FROM platform_users WHERE email LIKE '%%@x.com'"
    assert plan.unbound_sql == "SELECT * FROM platform_users WHERE email LIKE '%@x.com'"


def test_julianday_comparison_becomes_a_timestamp_cast() -> None:
    plan = translate(
        "SELECT 1 FROM platform_access_grants "
        "WHERE julianday(starts_at) <= julianday(?)"
    )
    assert "((starts_at)::timestamptz)" in plan.bound_sql
    assert "((%s)::timestamptz)" in plan.bound_sql
    assert "julianday" not in plan.bound_sql


def test_datetime_now_becomes_the_same_text_shape() -> None:
    plan = translate("UPDATE platform_accounts SET updated_at=datetime('now')")
    assert "to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')" in (
        plan.bound_sql
    )


def test_datetime_with_any_other_argument_refuses_to_guess() -> None:
    with pytest.raises(PlatformBridgeError):
        translate("SELECT datetime('now','+1 day')")


def test_begin_immediate_takes_the_transaction_write_lock() -> None:
    plan = translate("BEGIN IMMEDIATE")
    assert plan.kind == "lock"
    assert plan.bound_sql == (
        f"SELECT pg_advisory_xact_lock({PLATFORM_WRITE_LOCK_ID})"
    )


def test_plain_begin_is_a_no_op_because_a_transaction_is_already_open() -> None:
    assert translate("BEGIN").kind == "skip"


def test_pragmas_and_schema_statements_are_skipped() -> None:
    for statement in (
        "PRAGMA foreign_keys=ON",
        "PRAGMA busy_timeout=30000",
        "CREATE TABLE IF NOT EXISTS platform_users (id INTEGER)",
        "CREATE INDEX IF NOT EXISTS idx_x ON platform_users(id)",
        "ALTER TABLE platform_plans ADD COLUMN daily_quotas TEXT",
    ):
        assert translate(statement).kind == "skip", statement


def test_the_admin_callback_guard_becomes_a_transaction_local_flag() -> None:
    armed = translate(
        """
        CREATE TEMP TRIGGER admin_audit_callback_guard
        BEFORE INSERT ON platform_admin_audit
        BEGIN
            SELECT RAISE(ABORT, 'admin mutation callbacks cannot write audit rows');
        END
        """
    )
    assert armed.kind == "compat"
    assert "set_config('app.platform_admin_callback', 'on', true)" in armed.bound_sql

    disarmed = translate("DROP TRIGGER IF EXISTS admin_audit_callback_guard")
    assert disarmed.kind == "compat"
    assert "set_config('app.platform_admin_callback', 'off', true)" in (
        disarmed.bound_sql
    )


def test_the_guard_is_not_swallowed_by_the_generic_ddl_skip() -> None:
    # If the DDL skip ran first this security control would silently vanish,
    # and every test above would still pass.
    assert translate("DROP TRIGGER IF EXISTS admin_audit_callback_guard").kind != (
        "skip"
    )


def test_an_insert_records_its_target_table_for_lastrowid() -> None:
    plan = translate("INSERT INTO platform_users(email,name) VALUES (?,?)")
    assert plan.insert_table == "platform_users"
    assert plan.wants_identity is True


def test_an_insert_that_already_returns_is_left_alone() -> None:
    plan = translate("INSERT INTO platform_users(email) VALUES (?) RETURNING id")
    assert plan.wants_identity is False


def test_a_leading_comment_does_not_hide_the_keyword() -> None:
    plan = translate("-- pick the current grant\nSELECT 1 FROM platform_users")
    assert plan.kind == "run"


def test_a_question_mark_in_a_comment_is_not_a_placeholder() -> None:
    plan = translate("SELECT 1 -- is this a placeholder?\nFROM platform_users")
    assert "%s" not in plan.bound_sql


def test_reserved_words_used_as_aliases_are_quoted() -> None:
    plan = translate(
        "SELECT user.id FROM platform_memberships AS membership "
        "JOIN platform_users AS user ON user.id=membership.user_id"
    )
    assert 'AS "user"' in plan.bound_sql
    assert '"user".id' in plan.bound_sql
    # The non-reserved alias is left exactly as written.
    assert "AS membership" in plan.bound_sql
    assert "membership.user_id" in plan.bound_sql


def test_grant_is_quoted_too_because_postgresql_reserves_it() -> None:
    plan = translate(
        "SELECT grant.scope FROM platform_access_grants AS grant WHERE grant.id=?"
    )
    assert 'AS "grant"' in plan.bound_sql
    assert plan.bound_sql.count('"grant".') == 2
    assert plan.bound_sql.endswith("=%s")


def test_a_reserved_word_inside_a_literal_is_not_quoted() -> None:
    plan = translate("SELECT 1 FROM platform_users WHERE name='user.name'")
    assert "'user.name'" in plan.bound_sql
    assert '"user"' not in plan.bound_sql


def test_a_column_that_merely_starts_with_a_reserved_word_is_untouched() -> None:
    plan = translate("SELECT user_id, in_scope FROM platform_memberships")
    assert '"' not in plan.bound_sql


def test_an_integer_flag_in_a_case_when_becomes_an_explicit_comparison() -> None:
    plan = translate(
        "UPDATE platform_provider_events "
        "SET replayed_at=CASE WHEN ? THEN ? ELSE replayed_at END WHERE id=?"
    )
    # SQLite reads any non-zero number as true. PostgreSQL rejects the whole
    # statement with 'argument of CASE/WHEN must be type boolean'.
    assert "WHEN (%s)::int <> 0 THEN" in plan.bound_sql
    assert plan.bound_sql.count("%s") == 3
