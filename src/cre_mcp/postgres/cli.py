"""Operator CLI for migrations, backup recovery, and privacy processing."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg

from cre_mcp.postgres.backup import BackupError, create_backup, restore_backup
from cre_mcp.postgres.migrations import MigrationError, MigrationRunner

MIGRATION_DSN_ENV = "MEDAWARCRE_MIGRATION_DATABASE_URL"
APP_DSN_ENV = "MEDAWARCRE_APP_DATABASE_URL"
BACKUP_DSN_ENV = "MEDAWARCRE_BACKUP_DATABASE_URL"
#: Privacy processing runs as internal staff, on the admin runtime. It is a
#: separate credential from the request path on purpose, and it is the same one
#: the scheduled-search worker uses: nothing customer-facing should hold it.
ADMIN_DSN_ENV = "MEDAWARCRE_WORKER_DATABASE_URL"


class CliConfigurationError(ValueError):
    """An operator supplied an incomplete, secret-free command contract."""


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CliConfigurationError(f"required environment variable is missing: {name}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply the immutable migration plan")

    recover = commands.add_parser(
        "recover", help="clear one checksum-bound dirty migration"
    )
    recover.add_argument("version", type=int)
    recover.add_argument("--checksum", required=True)
    recover.add_argument("--reason", required=True)

    backup = commands.add_parser(
        "backup", help="create a native dump and exact manifest"
    )
    backup.add_argument("dump_path", type=Path)

    restore = commands.add_parser(
        "restore", help="restore and verify a clean distinct database"
    )
    restore.add_argument("dump_path", type=Path)
    restore.add_argument("manifest_path", type=Path)
    restore.add_argument("--smoke-workspace-id", required=True)
    restore.add_argument("--smoke-actor-user-id", required=True)
    restore.add_argument("--smoke-other-workspace-id", required=True)

    # Privacy processing. There is no customer portal and there will not be
    # one, so an access, export, correction or deletion request is opened and
    # driven by internal staff. These are the commands that do it.
    #
    # They are CLI commands rather than Operations Console routes for one
    # reason: the desk needs the `admin` runtime, and putting it behind a route
    # would mean the customer-facing server process holds an admin database
    # connection. That is a larger privilege increase than a console feature is
    # worth, and it is the same call the scheduled-search worker made.
    #
    # Every command below requires an actor and a reason, and every mutation
    # writes a `staff_audit_log` row in the same transaction as its effect. A
    # privacy action that cannot be attributed does not happen.
    privacy = commands.add_parser(
        "privacy", help="process a privacy or retention request as staff"
    )
    privacy_actions = privacy.add_subparsers(dest="privacy_command", required=True)

    def _staff(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--actor-user-id", required=True)
        sub.add_argument("--role", required=True)
        sub.add_argument("--reason", required=True)

    privacy_list = privacy_actions.add_parser("list", help="page through requests")
    privacy_list.add_argument("--workspace")
    privacy_list.add_argument("--status")
    privacy_list.add_argument("--limit", type=int, default=50)
    privacy_list.add_argument("--offset", type=int, default=0)
    _staff(privacy_list)

    privacy_submit = privacy_actions.add_parser(
        "submit", help="open a request on a subject's behalf"
    )
    privacy_submit.add_argument("--workspace", required=True)
    privacy_submit.add_argument("--subject-user-id", required=True)
    privacy_submit.add_argument(
        "--kind", required=True, choices=("access", "export", "delete", "correct")
    )
    privacy_submit.add_argument("--detail")
    _staff(privacy_submit)

    privacy_advance = privacy_actions.add_parser(
        "advance", help="move a request along the legal status graph"
    )
    privacy_advance.add_argument("request_id")
    privacy_advance.add_argument("--status", required=True)
    _staff(privacy_advance)

    privacy_export = privacy_actions.add_parser(
        "export", help="assemble one subject's data in one workspace"
    )
    privacy_export.add_argument("--workspace", required=True)
    privacy_export.add_argument("--subject-user-id", required=True)
    privacy_export.add_argument("--out", type=Path, required=True)
    _staff(privacy_export)
    return parser


def _emit(payload: dict[str, object], *, error: bool = False) -> None:
    print(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        file=sys.stderr if error else sys.stdout,
    )


def _run(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "migrate":
        applied = MigrationRunner(_required_environment(MIGRATION_DSN_ENV)).apply()
        return {"ok": True, "applied_versions": applied}
    if arguments.command == "recover":
        MigrationRunner(_required_environment(MIGRATION_DSN_ENV)).recover_failed(
            arguments.version,
            checksum=arguments.checksum,
            reason=arguments.reason,
        )
        return {"ok": True, "recovered_version": arguments.version}
    if arguments.command == "backup":
        manifest = create_backup(
            _required_environment(BACKUP_DSN_ENV), arguments.dump_path
        )
        return {"ok": True, "manifest_path": str(manifest)}
    if arguments.command == "restore":
        report = restore_backup(
            _required_environment(MIGRATION_DSN_ENV),
            arguments.dump_path,
            arguments.manifest_path,
            smoke_workspace_id=arguments.smoke_workspace_id,
            smoke_actor_user_id=arguments.smoke_actor_user_id,
            smoke_other_workspace_id=arguments.smoke_other_workspace_id,
            smoke_app_dsn=_required_environment(APP_DSN_ENV),
            smoke_backup_dsn=_required_environment(BACKUP_DSN_ENV),
        )
        return {
            "ok": report.ok,
            "read_write_smoke": report.read_write_smoke,
            "row_counts": report.row_counts,
            "tenant_isolation": report.tenant_isolation,
        }
    if arguments.command == "privacy":
        return _run_privacy(arguments)
    raise CliConfigurationError("unsupported command")


def _run_privacy(arguments: argparse.Namespace) -> dict[str, object]:
    from cre_mcp.postgres.privacy import InternalPrivacyDesk, StaffActor

    actor = StaffActor(
        actor_user_id=arguments.actor_user_id,
        role=arguments.role,
    )
    desk = InternalPrivacyDesk.for_dsn(_required_environment(ADMIN_DSN_ENV))
    try:
        if arguments.privacy_command == "list":
            records = desk.list_requests(
                arguments.workspace,
                arguments.status,
                actor=actor,
                reason=arguments.reason,
                limit=arguments.limit,
                offset=arguments.offset,
            )
            return {
                "ok": True,
                "requests": [
                    {
                        "id": record.id,
                        "workspace_public_id": record.workspace_public_id,
                        "kind": record.kind,
                        "status": record.status,
                    }
                    for record in records
                ],
            }
        if arguments.privacy_command == "submit":
            request_id = desk.submit(
                arguments.workspace,
                arguments.subject_user_id,
                arguments.kind,
                arguments.detail,
                actor=actor,
                reason=arguments.reason,
            )
            return {"ok": True, "request_id": request_id}
        if arguments.privacy_command == "advance":
            record = desk.advance(
                arguments.request_id,
                arguments.status,
                actor=actor,
                reason=arguments.reason,
            )
            return {"ok": True, "request_id": record.id, "status": record.status}
        if arguments.privacy_command == "export":
            payload = desk.export_workspace_subject(
                arguments.workspace,
                arguments.subject_user_id,
                actor=actor,
                reason=arguments.reason,
            )
            # Written to a file rather than stdout. An export is the one
            # command here whose output is the subject's personal data, and
            # stdout ends up in shell history, terminal scrollback and CI logs.
            arguments.out.write_text(
                json.dumps(payload, sort_keys=True, indent=2, default=str),
                encoding="utf-8",
            )
            arguments.out.chmod(0o600)
            return {"ok": True, "written": str(arguments.out)}
        raise CliConfigurationError("unsupported privacy command")
    finally:
        desk.close()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        _emit(_run(arguments))
        return 0
    except CliConfigurationError as error:
        _emit(
            {
                "ok": False,
                "code": "configuration_error",
                "detail": str(error),
            },
            error=True,
        )
    except MigrationError:
        _emit({"ok": False, "code": "migration_failed"}, error=True)
    except BackupError:
        _emit({"ok": False, "code": "backup_or_restore_failed"}, error=True)
    except ValueError:
        _emit({"ok": False, "code": "operator_input_invalid"}, error=True)
    except psycopg.Error:
        _emit({"ok": False, "code": "database_failed"}, error=True)
    except OSError:
        _emit({"ok": False, "code": "filesystem_failed"}, error=True)
    except Exception:
        _emit({"ok": False, "code": "unexpected_failure"}, error=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
