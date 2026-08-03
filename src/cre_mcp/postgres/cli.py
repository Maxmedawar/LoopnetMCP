"""Operator CLI for migrations and verified PostgreSQL backup recovery."""

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
    raise CliConfigurationError("unsupported command")


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
