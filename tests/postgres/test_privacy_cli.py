"""Processing a privacy request the way staff actually will.

There is no customer portal and there will not be one, so an access, export,
correction or deletion request is opened and driven by internal staff. These
are the commands that do it, and this is the proof they work against a real
database rather than a description of them.
"""

from __future__ import annotations

import json

import psycopg
import pytest

from cre_mcp.postgres import cli
from cre_mcp.postgres.migrations import MigrationRunner


@pytest.fixture
def desk_environment(postgres_database, monkeypatch):
    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admin_dsn = app_dsn.replace(
        "user=medawarcre_test_app", "user=medawarcre_test_admin"
    )
    monkeypatch.setenv(cli.ADMIN_DSN_ENV, admin_dsn)
    return admin_dsn


def _seed(admin_dsn: str) -> tuple[str, str, str]:
    """One staff operator, one workspace, one member — as the cluster owner."""
    owner = admin_dsn.replace("user=medawarcre_test_admin", "user=postgres")
    with psycopg.connect(owner) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        operator = connection.execute(
            "INSERT INTO users(email,name) VALUES (%s,%s) RETURNING id",
            ("privacy-operator@example.test", "Privacy Operator"),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO staff_roles(user_id,role,active) VALUES (%s,'admin',true)",
            (operator,),
        )
        subject = connection.execute(
            "INSERT INTO users(email,name) VALUES (%s,%s) RETURNING id",
            ("privacy-subject@example.test", "Privacy Subject"),
        ).fetchone()[0]
        workspace = connection.execute(
            "INSERT INTO workspaces(public_id,name,state) "
            "VALUES (%s,%s,'active') RETURNING id, public_id",
            ("ws_privacy_cli", "Privacy Tenant"),
        ).fetchone()
        connection.execute(
            "INSERT INTO memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'owner','active')",
            (workspace[0], subject),
        )
        connection.commit()
    return str(operator), str(subject), str(workspace[1])


def _audit_rows(admin_dsn: str) -> list[tuple]:
    owner = admin_dsn.replace("user=medawarcre_test_admin", "user=postgres")
    with psycopg.connect(owner) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        return connection.execute(
            "SELECT action, result FROM staff_audit_log ORDER BY occurred_at, id"
        ).fetchall()


def test_a_privacy_request_is_opened_advanced_and_exported(
    desk_environment, capsys, tmp_path
) -> None:
    operator, subject, workspace = _seed(desk_environment)
    common = [
        "--actor-user-id",
        operator,
        "--role",
        "admin",
        "--reason",
        "Subject emailed a verified deletion request.",
    ]

    assert (
        cli.main(
            [
                "privacy",
                "submit",
                "--workspace",
                workspace,
                "--subject-user-id",
                subject,
                "--kind",
                "export",
                *common,
            ]
        )
        == 0
    )
    submitted = json.loads(capsys.readouterr().out)
    assert submitted["ok"] is True
    request_id = submitted["request_id"]

    assert cli.main(["privacy", "list", "--workspace", workspace, *common]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [item["status"] for item in listed["requests"]] == ["received"]
    assert listed["requests"][0]["kind"] == "export"

    for status in ("verified", "in_progress", "completed"):
        assert (
            cli.main(["privacy", "advance", request_id, "--status", status, *common])
            == 0
        )
        moved = json.loads(capsys.readouterr().out)
        assert moved["status"] == status

    out = tmp_path / "subject-export.json"
    assert (
        cli.main(
            [
                "privacy",
                "export",
                "--workspace",
                workspace,
                "--subject-user-id",
                subject,
                "--out",
                str(out),
                *common,
            ]
        )
        == 0
    )
    written = json.loads(capsys.readouterr().out)
    assert written["ok"] is True

    payload = json.loads(out.read_text())
    assert payload["memberships"]
    # The export is the one command whose output is the subject's personal
    # data, so it goes to a file rather than stdout -- stdout ends up in shell
    # history, terminal scrollback and CI logs -- and the file is not readable
    # by anyone else on the box.
    assert out.stat().st_mode & 0o777 == 0o600
    assert "privacy-subject@example.test" not in capsys.readouterr().out

    # Every mutation is attributable. A privacy action that leaves no trace is
    # the failure mode this whole path exists to avoid.
    actions = [row[0] for row in _audit_rows(desk_environment)]
    assert any("submit" in action for action in actions)
    assert any("advance" in action for action in actions)


def test_an_illegal_status_transition_is_refused_and_still_audited(
    desk_environment, capsys
) -> None:
    operator, subject, workspace = _seed(desk_environment)
    common = [
        "--actor-user-id",
        operator,
        "--role",
        "admin",
        "--reason",
        "Subject emailed a verified deletion request.",
    ]
    cli.main(
        [
            "privacy",
            "submit",
            "--workspace",
            workspace,
            "--subject-user-id",
            subject,
            "--kind",
            "delete",
            *common,
        ]
    )
    request_id = json.loads(capsys.readouterr().out)["request_id"]

    # received -> completed skips verification. Refused, not coerced.
    assert (
        cli.main(["privacy", "advance", request_id, "--status", "completed", *common])
        != 0
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["ok"] is False

    denied = [row for row in _audit_rows(desk_environment) if row[1] == "denied"]
    assert denied, "a refused privacy action must still leave an audit row"


def test_a_non_uuid_actor_is_refused_before_any_connection(
    desk_environment, capsys
) -> None:
    assert (
        cli.main(
            [
                "privacy",
                "list",
                "--actor-user-id",
                "not-a-uuid",
                "--role",
                "admin",
                "--reason",
                "Attempted with an unattributable actor.",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().err)["code"] == "operator_input_invalid"


def test_a_read_only_role_cannot_mutate(desk_environment, capsys) -> None:
    operator, subject, workspace = _seed(desk_environment)
    assert (
        cli.main(
            [
                "privacy",
                "submit",
                "--workspace",
                workspace,
                "--subject-user-id",
                subject,
                "--kind",
                "delete",
                "--actor-user-id",
                operator,
                "--role",
                "read_only_analyst",
                "--reason",
                "Attempted a mutation from a read-only role.",
            ]
        )
        != 0
    )
    assert capsys.readouterr().out == ""
