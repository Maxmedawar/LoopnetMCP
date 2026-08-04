"""Native PostgreSQL backup, manifest, and clean-restore verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from cre_mcp.postgres.authority import (
    ADMISSION_ROLE,
    SERVICE_FUNCTIONS_BY_ROLE,
    SERVICE_ROLES,
    UnsafeDatabaseRoleError,
    assert_exact_group_session,
    assert_group_has_exact_object_authority,
    assert_group_has_no_object_authority,
)
from cre_mcp.postgres.catalog import catalog_fingerprint
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.migrations import (
    UnsafeMigrationRoleError,
    assert_migration_session,
    load_migrations,
)
from cre_mcp.postgres.pool import AuthorityContext, PostgresDatabase
from cre_mcp.postgres.schema import (
    ADMIN_COLUMN_READS,
    ADMIN_MUTATION_TABLES,
    ADMIN_INSERT_ONLY_TABLES,
    ADMIN_READ_TABLES,
    APP_COLUMN_READS,
    APP_READ_TABLES,
    APP_WRITE_TABLES,
    EXPECTED_CATALOG_FINGERPRINT,
    EXPECTED_RLS_TABLES,
    EXPECTED_TABLES,
    SCHEMA_NAME,
)

BACKUP_ROLE = "medawarcre_backup"
MIGRATION_ROLE = "medawarcre_migration"
MANIFEST_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_POSTGRES_VERSION = re.compile(
    r"^(?:(?:pg_dump|pg_restore) \(PostgreSQL\) )?"
    r"(?P<major>[0-9]+)(?:\.[0-9]+)*(?:\s.*)?$"
)
_MINIMUM_SERVER_VERSION = 160000
_SERVICE_ROLE_NAMES = tuple(SERVICE_ROLES.values())
_RUNTIME_ROLE_NAMES = (
    "medawarcre_app",
    "medawarcre_admin",
    BACKUP_ROLE,
    ADMISSION_ROLE,
    *_SERVICE_ROLE_NAMES,
)


class BackupError(RuntimeError):
    """Base class for redaction-safe backup failures."""


class BackupCommandError(BackupError):
    """A native PostgreSQL command did not complete successfully."""


class BackupVerificationError(BackupError):
    """An archive, manifest, authority, or restored target failed closed."""


@dataclass(frozen=True)
class BackupManifest:
    format_version: int
    created_at: str
    dump_sha256: str
    dump_size: int
    pg_dump_version: str
    server_version: str
    schema_fingerprint: str
    migration_checksums: dict[str, str]
    migration_descriptions: dict[str, str]
    tables: tuple[str, ...]
    row_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "created_at": self.created_at,
            "dump_sha256": self.dump_sha256,
            "dump_size": self.dump_size,
            "pg_dump_version": self.pg_dump_version,
            "server_version": self.server_version,
            "schema_fingerprint": self.schema_fingerprint,
            "migration_checksums": dict(sorted(self.migration_checksums.items())),
            "migration_descriptions": dict(
                sorted(self.migration_descriptions.items())
            ),
            "tables": list(self.tables),
            "row_counts": dict(sorted(self.row_counts.items())),
        }


@dataclass(frozen=True)
class RestoreReport:
    ok: bool
    row_counts: dict[str, int]
    tenant_isolation: bool
    read_write_smoke: bool


@dataclass(frozen=True)
class _SnapshotMetadata:
    created_at: str
    server_version: str
    schema_fingerprint: str
    migration_checksums: dict[str, str]
    migration_descriptions: dict[str, str]
    tables: tuple[str, ...]
    row_counts: dict[str, int]


def _postgres_major(version: str, field: str) -> int:
    match = _POSTGRES_VERSION.fullmatch(version.strip())
    if match is None:
        raise BackupVerificationError(f"{field} is not a recognized PostgreSQL version")
    return int(match.group("major"))


def _assert_manifest_postgres16(manifest: BackupManifest) -> None:
    if (
        _postgres_major(manifest.server_version, "manifest server version") < 16
        or _postgres_major(manifest.pg_dump_version, "manifest pg_dump version") < 16
    ):
        raise BackupVerificationError(
            "backup manifest requires PostgreSQL 16 or newer"
        )


def _assert_native_postgres16(version: str, command: str) -> None:
    try:
        major = _postgres_major(version, f"{command} version")
    except BackupVerificationError as error:
        raise BackupCommandError(
            "PostgreSQL command version is unsupported"
        ) from error
    if major < 16:
        raise BackupCommandError(
            "PostgreSQL 16 or newer native commands are required"
        )


def _assert_connection_postgres16(connection: psycopg.Connection, context: str) -> None:
    if int(connection.info.server_version) < _MINIMUM_SERVER_VERSION:
        raise BackupVerificationError(f"{context} requires PostgreSQL 16 or newer")


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise BackupVerificationError(f"manifest field {name} is invalid")
    return value


def _string_map(payload: Mapping[str, Any], name: str) -> dict[str, str]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise BackupVerificationError(f"manifest field {name} is invalid")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise BackupVerificationError(f"manifest field {name} is invalid")
        result[key] = item
    return result


def _manifest_from_dict(payload: Mapping[str, Any]) -> BackupManifest:
    required = {
        "format_version",
        "created_at",
        "dump_sha256",
        "dump_size",
        "pg_dump_version",
        "server_version",
        "schema_fingerprint",
        "migration_checksums",
        "migration_descriptions",
        "tables",
        "row_counts",
    }
    if set(payload) != required:
        raise BackupVerificationError("manifest fields do not match version 1")
    format_version = payload.get("format_version")
    dump_size = payload.get("dump_size")
    if type(format_version) is not int or format_version != MANIFEST_VERSION:
        raise BackupVerificationError("manifest version is unsupported")
    if type(dump_size) is not int or dump_size < 0:
        raise BackupVerificationError("manifest dump size is invalid")
    created_at = _required_string(payload, "created_at")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise BackupVerificationError("manifest timestamp is invalid") from error
    dump_sha256 = _required_string(payload, "dump_sha256")
    if _SHA256.fullmatch(dump_sha256) is None:
        raise BackupVerificationError("manifest SHA-256 is invalid")
    schema_fingerprint = _required_string(payload, "schema_fingerprint")
    if _SHA256.fullmatch(schema_fingerprint) is None:
        raise BackupVerificationError("manifest schema fingerprint is invalid")
    table_value = payload.get("tables")
    if not isinstance(table_value, list) or not all(
        isinstance(item, str) and _NAME.fullmatch(item) for item in table_value
    ):
        raise BackupVerificationError("manifest table inventory is invalid")
    tables = tuple(table_value)
    if tables != tuple(sorted(set(tables))):
        raise BackupVerificationError("manifest table inventory is not canonical")
    row_value = payload.get("row_counts")
    if not isinstance(row_value, dict):
        raise BackupVerificationError("manifest row counts are invalid")
    row_counts: dict[str, int] = {}
    for table, count in row_value.items():
        if not isinstance(table, str) or type(count) is not int or count < 0:
            raise BackupVerificationError("manifest row counts are invalid")
        row_counts[table] = count
    if set(row_counts) != set(tables):
        raise BackupVerificationError("manifest row counts do not match its tables")
    migration_checksums = _string_map(payload, "migration_checksums")
    migration_descriptions = _string_map(payload, "migration_descriptions")
    if set(migration_checksums) != set(migration_descriptions) or not all(
        key.isdecimal() and _SHA256.fullmatch(value)
        for key, value in migration_checksums.items()
    ):
        raise BackupVerificationError("manifest migration inventory is invalid")
    manifest = BackupManifest(
        format_version=format_version,
        created_at=created_at,
        dump_sha256=dump_sha256,
        dump_size=dump_size,
        pg_dump_version=_required_string(payload, "pg_dump_version"),
        server_version=_required_string(payload, "server_version"),
        schema_fingerprint=schema_fingerprint,
        migration_checksums=migration_checksums,
        migration_descriptions=migration_descriptions,
        tables=tables,
        row_counts=row_counts,
    )
    _assert_manifest_postgres16(manifest)
    return manifest


def load_manifest(path: str | Path) -> BackupManifest:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BackupVerificationError("backup manifest cannot be read") from error
    if not isinstance(payload, dict):
        raise BackupVerificationError("backup manifest must be a JSON object")
    return _manifest_from_dict(payload)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _native_program(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise BackupCommandError(f"required PostgreSQL command is unavailable: {name}")
    return path


def _native_version(program: str) -> str:
    result = subprocess.run(
        [program, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BackupCommandError("PostgreSQL command version check failed")
    return result.stdout.strip()


def _command_connection(dsn: str) -> tuple[str, dict[str, str]]:
    try:
        parameters = conninfo_to_dict(dsn)
        password = parameters.pop("password", None)
        ssl_password = parameters.pop("sslpassword", None)
        safe_connection = make_conninfo(**parameters)
    except Exception as error:
        raise BackupError("database connection configuration is invalid") from error
    environment = os.environ.copy()
    environment.pop("PGPASSWORD", None)
    environment.pop("PGSSLPASSWORD", None)
    environment.pop("PGOPTIONS", None)
    if password is not None:
        environment["PGPASSWORD"] = password
    if ssl_password is not None:
        environment["PGSSLPASSWORD"] = ssl_password
    environment["LC_ALL"] = "C"
    return safe_connection, environment


def _run_native(arguments: list[str], environment: Mapping[str, str]) -> None:
    result = subprocess.run(
        arguments,
        env=dict(environment),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        program = Path(arguments[0]).name
        raise BackupCommandError(
            f"{program} failed with exit code {result.returncode}"
        )


def _assert_backup_session(connection: psycopg.Connection) -> None:
    try:
        assert_exact_group_session(
            connection,
            BACKUP_ROLE,
            login_inherits=True,
            group_inherits=True,
            group_bypasses_rls=True,
        )
    except UnsafeDatabaseRoleError as error:
        raise BackupVerificationError(
            "backup login violates the dedicated SELECT-only authority contract"
        ) from error


def _assert_restore_session(connection: psycopg.Connection) -> None:
    try:
        assert_migration_session(connection)
    except UnsafeMigrationRoleError as error:
        raise BackupVerificationError(
            "restore login violates the dedicated migration authority contract"
        ) from error


def _current_contract() -> tuple[dict[str, str], dict[str, str]]:
    migrations = load_migrations()
    return (
        {str(item.version): item.checksum for item in migrations},
        {str(item.version): item.name for item in migrations},
    )


def _collect_snapshot(connection: psycopg.Connection) -> _SnapshotMetadata:
    _assert_connection_postgres16(connection, "backup source")
    tables = tuple(
        sorted(
            str(row[0])
            for row in connection.execute(
                "SELECT c.relname FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=%s AND c.relkind IN ('r','p')",
                (SCHEMA_NAME,),
            )
        )
    )
    if set(tables) != EXPECTED_TABLES:
        raise BackupVerificationError(
            "source schema table inventory does not match the release contract"
        )
    migration_rows = connection.execute(
        "SELECT version,description,checksum,state,dirty "
        "FROM medawarcre.schema_migrations ORDER BY version"
    ).fetchall()
    checksums = {str(row[0]): str(row[2]) for row in migration_rows}
    descriptions = {str(row[0]): str(row[1]) for row in migration_rows}
    expected_checksums, expected_descriptions = _current_contract()
    if (
        checksums != expected_checksums
        or descriptions != expected_descriptions
        or any(row[3] != "applied" or bool(row[4]) for row in migration_rows)
    ):
        raise BackupVerificationError(
            "source migration history does not match the release contract"
        )
    row_counts = {
        table: int(
            connection.execute(
                sql.SQL("SELECT count(*) FROM {}.{}").format(
                    sql.Identifier(SCHEMA_NAME), sql.Identifier(table)
                )
            ).fetchone()[0]
        )
        for table in tables
    }
    timestamp = connection.execute("SELECT transaction_timestamp()").fetchone()[0]
    schema_fingerprint = catalog_fingerprint(connection)
    if schema_fingerprint != EXPECTED_CATALOG_FINGERPRINT:
        raise BackupVerificationError(
            "source catalog differs from the reviewed release contract"
        )
    return _SnapshotMetadata(
        created_at=timestamp.isoformat().replace("+00:00", "Z"),
        server_version=str(connection.execute("SHOW server_version").fetchone()[0]),
        schema_fingerprint=schema_fingerprint,
        migration_checksums=checksums,
        migration_descriptions=descriptions,
        tables=tables,
        row_counts=row_counts,
    )


def _temporary_path(destination: Path) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.fchmod(descriptor, 0o600)
    os.close(descriptor)
    return Path(raw_path)


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_no_replace(source: Path, destination: Path) -> tuple[int, int]:
    os.link(source, destination, follow_symlinks=False)
    published = destination.lstat()
    return published.st_dev, published.st_ino


def _remove_if_published(
    destination: Path, identity: tuple[int, int] | None
) -> None:
    if identity is None:
        return
    try:
        current = destination.lstat()
    except FileNotFoundError:
        return
    if (current.st_dev, current.st_ino) == identity:
        destination.unlink()


def create_backup(
    dsn: str,
    dump_path: str | Path,
    *,
    _snapshot_ready: Callable[[], None] | None = None,
    _after_dump_publish: Callable[[], None] | None = None,
) -> Path:
    """Create one immutable archive and manifest from the same MVCC snapshot."""
    destination = Path(dump_path)
    manifest_path = destination.with_name(destination.name + ".manifest.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or manifest_path.exists():
        raise BackupError("backup destination already exists")
    pg_dump = _native_program("pg_dump")
    pg_dump_version = _native_version(pg_dump)
    _assert_native_postgres16(pg_dump_version, "pg_dump")
    safe_connection, environment = _command_connection(dsn)
    dump_temp: Path | None = None
    manifest_temp: Path | None = None
    published_dump: tuple[int, int] | None = None
    published_manifest: tuple[int, int] | None = None
    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            _assert_backup_session(connection)
            _assert_connection_postgres16(connection, "backup source")
            dump_temp = _temporary_path(destination)
            manifest_temp = _temporary_path(manifest_path)
            with connection.transaction():
                connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                connection.execute("SET LOCAL ROLE medawarcre_backup")
                snapshot_id = str(
                    connection.execute("SELECT pg_export_snapshot()").fetchone()[0]
                )
                if _snapshot_ready is not None:
                    _snapshot_ready()
                metadata = _collect_snapshot(connection)
                _run_native(
                    [
                        pg_dump,
                        "--format=custom",
                        "--no-owner",
                        "--no-acl",
                        "--schema=medawarcre",
                        f"--snapshot={snapshot_id}",
                        f"--role={BACKUP_ROLE}",
                        "--file",
                        str(dump_temp),
                        "--dbname",
                        safe_connection,
                    ],
                    environment,
                )
        os.chmod(dump_temp, 0o600)
        _fsync_file(dump_temp)
        manifest = BackupManifest(
            format_version=MANIFEST_VERSION,
            created_at=metadata.created_at,
            dump_sha256=_sha256(dump_temp),
            dump_size=dump_temp.stat().st_size,
            pg_dump_version=pg_dump_version,
            server_version=metadata.server_version,
            schema_fingerprint=metadata.schema_fingerprint,
            migration_checksums=metadata.migration_checksums,
            migration_descriptions=metadata.migration_descriptions,
            tables=metadata.tables,
            row_counts=metadata.row_counts,
        )
        with manifest_temp.open("w", encoding="utf-8") as handle:
            json.dump(manifest.to_dict(), handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(manifest_temp, 0o600)
        published_dump = _publish_no_replace(dump_temp, destination)
        if _after_dump_publish is not None:
            _after_dump_publish()
        published_manifest = _publish_no_replace(manifest_temp, manifest_path)
        _fsync_directory(destination.parent)
        dump_temp.unlink()
        manifest_temp.unlink()
        _fsync_directory(destination.parent)
    except BaseException as error:
        _remove_if_published(manifest_path, published_manifest)
        _remove_if_published(destination, published_dump)
        if dump_temp is not None:
            dump_temp.unlink(missing_ok=True)
        if manifest_temp is not None:
            manifest_temp.unlink(missing_ok=True)
        if isinstance(error, FileExistsError):
            raise BackupError("backup destination already exists") from error
        raise
    return manifest_path


def _verify_manifest_contract(manifest: BackupManifest) -> None:
    _assert_manifest_postgres16(manifest)
    expected_checksums, expected_descriptions = _current_contract()
    if (
        set(manifest.tables) != EXPECTED_TABLES
        or manifest.migration_checksums != expected_checksums
        or manifest.migration_descriptions != expected_descriptions
        or manifest.schema_fingerprint != EXPECTED_CATALOG_FINGERPRINT
    ):
        raise BackupVerificationError(
            "backup manifest does not match the release schema contract"
        )


def _assert_clean_target(connection: psycopg.Connection) -> None:
    database_owner = connection.execute(
        "SELECT owner.rolname FROM pg_catalog.pg_database database "
        "JOIN pg_catalog.pg_roles owner ON owner.oid=database.datdba "
        "WHERE database.datname=current_database()"
    ).fetchone()[0]
    medawarcre_schema = bool(
        connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname=%s)",
            (SCHEMA_NAME,),
        ).fetchone()[0]
    )
    user_relations = int(
        connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_class relation "
            "JOIN pg_catalog.pg_namespace namespace ON namespace.oid=relation.relnamespace "
            "WHERE namespace.nspname NOT IN ('pg_catalog','information_schema') "
            "AND namespace.nspname NOT LIKE 'pg_toast%%' "
            "AND relation.relkind IN ('r','p','S','v','m','f')"
        ).fetchone()[0]
    )
    if database_owner != MIGRATION_ROLE or medawarcre_schema or user_relations:
        raise BackupVerificationError(
            "restore target is not a distinct clean migration-owned database"
        )


def _assert_bootstrap_roles(
    connection: psycopg.Connection,
    *,
    provisioned: bool = False,
) -> None:
    connection.execute("SET search_path TO pg_catalog")
    rows = {
        str(row[0]): tuple(row[1:])
        for row in connection.execute(
            "SELECT rolname,rolcanlogin,rolinherit,rolsuper,rolbypassrls,rolcreatedb,"
            "rolcreaterole,rolreplication FROM pg_catalog.pg_roles "
            "WHERE rolname = ANY(%s)",
            (
                [
                    MIGRATION_ROLE,
                    "medawarcre_app",
                    "medawarcre_admin",
                    BACKUP_ROLE,
                    ADMISSION_ROLE,
                    *_SERVICE_ROLE_NAMES,
                ],
            ),
        )
    }
    expected = {
        MIGRATION_ROLE: (False, False, False, False, False, False, False),
        "medawarcre_app": (False, True, False, False, False, False, False),
        "medawarcre_admin": (False, True, False, False, False, False, False),
        BACKUP_ROLE: (False, True, False, True, False, False, False),
        ADMISSION_ROLE: (False, False, False, False, False, False, False),
        **{
            role: (False, False, False, False, False, False, False)
            for role in _SERVICE_ROLE_NAMES
        },
    }
    if rows != expected:
        raise BackupVerificationError("target role bootstrap contract is invalid")
    memberships = connection.execute(
        "SELECT member.rolname,parent.rolname,membership.admin_option,"
        "membership.inherit_option,membership.set_option "
        "FROM pg_catalog.pg_auth_members membership "
        "JOIN pg_catalog.pg_roles member ON member.oid=membership.member "
        "JOIN pg_catalog.pg_roles parent ON parent.oid=membership.roleid "
        "WHERE member.rolname = ANY(%s) ORDER BY member.rolname,parent.rolname",
        (list(expected),),
    ).fetchall()
    if memberships:
        raise BackupVerificationError(
            "target group roles have unauthorized parent memberships"
        )
    try:
        for role in _SERVICE_ROLE_NAMES:
            if provisioned:
                assert_group_has_exact_object_authority(connection, role)
            else:
                assert_group_has_no_object_authority(connection, role)
    except UnsafeDatabaseRoleError as error:
        raise BackupVerificationError(
            "target service role bootstrap authority is invalid"
        ) from error


def _apply_restore_privileges(dsn: str) -> None:
    statement = (
        files("cre_mcp.postgres")
        .joinpath("sql")
        .joinpath("restore_privileges.sql")
        .read_text(encoding="utf-8")
    )
    with psycopg.connect(dsn) as connection:
        _assert_restore_session(connection)
        _assert_connection_postgres16(connection, "restore target")
        connection.execute("SET LOCAL ROLE medawarcre_migration")
        connection.execute(statement)


def _table_inventory(connection: psycopg.Connection) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(row[0])
            for row in connection.execute(
                "SELECT c.relname FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=%s AND c.relkind IN ('r','p')",
                (SCHEMA_NAME,),
            )
        )
    )


def _verify_exact_privileges(connection: psycopg.Connection) -> None:
    _assert_bootstrap_roles(connection, provisioned=True)
    database_row = connection.execute(
        "SELECT owner.rolname,database.datacl IS NULL "
        "FROM pg_catalog.pg_database database "
        "JOIN pg_catalog.pg_roles owner ON owner.oid=database.datdba "
        "WHERE database.datname=current_database()"
    ).fetchone()
    if database_row != (MIGRATION_ROLE, True):
        raise BackupVerificationError(
            "restored database privileges do not match the exact role contract"
        )

    default_acl_rows = {
        tuple(row)
        for row in connection.execute(
            "SELECT owner.rolname,COALESCE(namespace.nspname,''),"
            "default_acl.defaclobjtype,grantor.rolname,"
            "CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,"
            "acl.privilege_type,acl.is_grantable "
            "FROM pg_catalog.pg_default_acl default_acl "
            "JOIN pg_catalog.pg_roles owner ON owner.oid=default_acl.defaclrole "
            "LEFT JOIN pg_catalog.pg_namespace namespace "
            "ON namespace.oid=default_acl.defaclnamespace "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) acl "
            "JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor "
            "LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee "
            "WHERE owner.rolname = ANY(%s) OR namespace.nspname=%s",
            (
                [
                    MIGRATION_ROLE,
                    "medawarcre_app",
                    "medawarcre_admin",
                    BACKUP_ROLE,
                    ADMISSION_ROLE,
                    *_SERVICE_ROLE_NAMES,
                ],
                SCHEMA_NAME,
            ),
        ).fetchall()
    }
    expected_default_acl_rows = {
        (
            MIGRATION_ROLE,
            SCHEMA_NAME,
            "r",
            MIGRATION_ROLE,
            BACKUP_ROLE,
            "SELECT",
            False,
        ),
        (
            MIGRATION_ROLE,
            SCHEMA_NAME,
            "S",
            MIGRATION_ROLE,
            BACKUP_ROLE,
            "SELECT",
            False,
        ),
        (
            MIGRATION_ROLE,
            "",
            "f",
            MIGRATION_ROLE,
            MIGRATION_ROLE,
            "EXECUTE",
            False,
        ),
        (
            MIGRATION_ROLE,
            "",
            "T",
            MIGRATION_ROLE,
            MIGRATION_ROLE,
            "USAGE",
            False,
        ),
    }
    if default_acl_rows != expected_default_acl_rows:
        raise BackupVerificationError(
            "restored default privileges do not match the exact role contract"
        )

    for table in EXPECTED_TABLES:
        qualified = f"{SCHEMA_NAME}.{table}"
        expected_by_role = {
            "medawarcre_app": (
                table in APP_READ_TABLES,
                table in APP_WRITE_TABLES,
                table in APP_WRITE_TABLES,
                table in APP_WRITE_TABLES,
            ),
            "medawarcre_admin": (
                table in ADMIN_READ_TABLES,
                table in ADMIN_MUTATION_TABLES
                or table in ADMIN_INSERT_ONLY_TABLES,
                table in ADMIN_MUTATION_TABLES,
                table in ADMIN_MUTATION_TABLES,
            ),
            BACKUP_ROLE: (True, False, False, False),
            ADMISSION_ROLE: (False, False, False, False),
            **{
                role: (False, False, False, False)
                for role in _SERVICE_ROLE_NAMES
            },
        }
        for role, expected in expected_by_role.items():
            actual = tuple(
                bool(
                    connection.execute(
                        "SELECT has_table_privilege(%s,%s,%s)",
                        (role, qualified, privilege),
                    ).fetchone()[0]
                )
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
            )
            if actual != expected:
                raise BackupVerificationError(
                    "restored table privileges do not match the exact role contract"
                )
            column_rows = connection.execute(
                "SELECT column_name,"
                "has_column_privilege(%s,%s,column_name,'SELECT'),"
                "has_column_privilege(%s,%s,column_name,'INSERT'),"
                "has_column_privilege(%s,%s,column_name,'UPDATE') "
                "FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                (
                    role,
                    qualified,
                    role,
                    qualified,
                    role,
                    qualified,
                    SCHEMA_NAME,
                    table,
                ),
            ).fetchall()
            for column_name, can_select, can_insert, can_update in column_rows:
                expected_select = role == "medawarcre_app" and (
                    table in APP_READ_TABLES
                    or str(column_name)
                    in APP_COLUMN_READS.get(table, frozenset())
                )
                if role == "medawarcre_admin":
                    expected_select = (
                        table in ADMIN_READ_TABLES
                        or str(column_name)
                        in ADMIN_COLUMN_READS.get(table, frozenset())
                    )
                if role == BACKUP_ROLE:
                    expected_select = True
                expected_insert = (
                    table in APP_WRITE_TABLES
                    if role == "medawarcre_app"
                    else role == "medawarcre_admin"
                    and (
                        table in ADMIN_MUTATION_TABLES
                        or table in ADMIN_INSERT_ONLY_TABLES
                    )
                )
                expected_update = (
                    table in APP_WRITE_TABLES
                    if role == "medawarcre_app"
                    else role == "medawarcre_admin"
                    and table in ADMIN_MUTATION_TABLES
                )
                if (
                    bool(can_select) != expected_select
                    or bool(can_insert) != expected_insert
                    or bool(can_update) != expected_update
                ):
                    raise BackupVerificationError(
                        "restored column privileges do not match the exact role contract"
                    )
    for role in _RUNTIME_ROLE_NAMES:
        usage, create = connection.execute(
            "SELECT has_schema_privilege(%s,%s,'USAGE'),"
            "has_schema_privilege(%s,%s,'CREATE')",
            (role, SCHEMA_NAME, role, SCHEMA_NAME),
        ).fetchone()
        expected_usage = (
            role not in _SERVICE_ROLE_NAMES
            or bool(SERVICE_FUNCTIONS_BY_ROLE[role])
        )
        if bool(usage) != expected_usage or create:
            raise BackupVerificationError(
                "restored schema privileges do not match the exact role contract"
            )
    public_function_execute = int(
        connection.execute(
            "SELECT count(*) FROM pg_catalog.pg_proc procedure "
            "JOIN pg_catalog.pg_namespace namespace ON namespace.oid=procedure.pronamespace "
            "CROSS JOIN LATERAL aclexplode(COALESCE(procedure.proacl, "
            "acldefault('f',procedure.proowner))) acl "
            "WHERE namespace.nspname=%s AND acl.grantee=0 "
            "AND acl.privilege_type='EXECUTE'",
            (SCHEMA_NAME,),
        ).fetchone()[0]
    )
    if public_function_execute:
        raise BackupVerificationError("restored functions expose PUBLIC execution")
    functions = {
        (str(row[0]), str(row[1]))
        for row in connection.execute(
            "SELECT procedure.proname,"
            "pg_catalog.oidvectortypes(procedure.proargtypes) "
            "FROM pg_catalog.pg_proc procedure "
            "JOIN pg_catalog.pg_namespace namespace "
            "ON namespace.oid=procedure.pronamespace "
            "WHERE namespace.nspname=%s",
            (SCHEMA_NAME,),
        )
    }
    function_contract = {
        ("current_workspace_id", ""): {"medawarcre_app", "medawarcre_admin"},
        ("current_actor_user_id", ""): {"medawarcre_app", "medawarcre_admin"},
        ("internal_authorized", ""): {"medawarcre_admin"},
        ("internal_can_mutate", ""): {"medawarcre_admin"},
        ("reject_audit_mutation", ""): set(),
        ("reject_provider_event_binding_mutation", ""): set(),
        ("enforce_provider_event_attempt_binding", ""): set(),
        ("propagate_provider_event_workspace_binding", ""): set(),
        (
            "consume_tool_approval",
            "bytea, uuid, uuid, bytea, text, bytea",
        ): set(),
        (
            "consume_daily_quota",
            "uuid, text, bigint, bigint",
        ): set(),
        (
            "record_access_decision",
            "uuid, text, boolean, uuid, uuid, bytea, uuid, text, text, text, text",
        ): set(),
        (
            "atomic_admit_tool_call",
            "uuid, uuid, text, uuid, uuid, text, text, text, text, text[], text, bytea, text, boolean, bytea",
        ): {ADMISSION_ROLE},
        (
            "record_tool_call_final",
            "uuid, uuid, text, uuid, uuid, text, boolean, text, text",
        ): {ADMISSION_ROLE},
        (
            "resolve_oauth_authority",
            "bytea, text, text",
        ): {SERVICE_ROLES["oauth"]},
    }
    if functions != set(function_contract):
        raise BackupVerificationError(
            "restored function inventory differs from the release contract"
        )
    for (function_name, argument_types), allowed_roles in function_contract.items():
        signature = f"{SCHEMA_NAME}.{function_name}({argument_types})"
        for role in _RUNTIME_ROLE_NAMES:
            allowed = bool(
                connection.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')",
                    (role, signature),
                ).fetchone()[0]
            )
            if allowed != (role in allowed_roles):
                raise BackupVerificationError(
                    "restored function privileges do not match the exact role contract"
                )


def _verify_restored_database(
    dsn: str, manifest: BackupManifest
) -> dict[str, int]:
    with psycopg.connect(dsn) as connection:
        _assert_restore_session(connection)
        _assert_connection_postgres16(connection, "restored database")
        connection.execute("SET LOCAL ROLE medawarcre_migration")
        tables = _table_inventory(connection)
        if tables != manifest.tables:
            raise BackupVerificationError(
                "restored table inventory differs from the manifest"
            )
        row_counts = {
            table: int(
                connection.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(SCHEMA_NAME), sql.Identifier(table)
                    )
                ).fetchone()[0]
            )
            for table in tables
        }
        if row_counts != manifest.row_counts:
            raise BackupVerificationError(
                "restored row counts differ from the manifest"
            )
        migrations = connection.execute(
            "SELECT version,description,checksum,state,dirty "
            "FROM medawarcre.schema_migrations ORDER BY version"
        ).fetchall()
        if (
            {str(row[0]): str(row[2]) for row in migrations}
            != manifest.migration_checksums
            or {str(row[0]): str(row[1]) for row in migrations}
            != manifest.migration_descriptions
            or any(row[3] != "applied" or bool(row[4]) for row in migrations)
        ):
            raise BackupVerificationError(
                "restored migration ledger differs from the manifest"
            )
        invalid_foreign_keys = int(
            connection.execute(
                "SELECT count(*) FROM pg_catalog.pg_constraint con "
                "JOIN pg_catalog.pg_namespace namespace "
                "ON namespace.oid=con.connamespace "
                "WHERE namespace.nspname=%s AND con.contype='f' "
                "AND NOT con.convalidated",
                (SCHEMA_NAME,),
            ).fetchone()[0]
        )
        rls_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT relation.relname FROM pg_catalog.pg_class relation "
                "JOIN pg_catalog.pg_namespace namespace "
                "ON namespace.oid=relation.relnamespace "
                "WHERE namespace.nspname=%s AND relation.relrowsecurity",
                (SCHEMA_NAME,),
            )
        }
        disabled_triggers = int(
            connection.execute(
                "SELECT count(*) FROM pg_catalog.pg_trigger trg "
                "JOIN pg_catalog.pg_class relation ON relation.oid=trg.tgrelid "
                "JOIN pg_catalog.pg_namespace namespace "
                "ON namespace.oid=relation.relnamespace "
                "WHERE namespace.nspname=%s AND NOT trg.tgisinternal "
                "AND trg.tgenabled='D'",
                (SCHEMA_NAME,),
            ).fetchone()[0]
        )
        schema_owner = connection.execute(
            "SELECT owner.rolname FROM pg_catalog.pg_namespace namespace "
            "JOIN pg_catalog.pg_roles owner ON owner.oid=namespace.nspowner "
            "WHERE namespace.nspname=%s",
            (SCHEMA_NAME,),
        ).fetchone()[0]
        non_migration_tables = int(
            connection.execute(
                "SELECT count(*) FROM pg_catalog.pg_class relation "
                "JOIN pg_catalog.pg_namespace namespace "
                "ON namespace.oid=relation.relnamespace "
                "JOIN pg_catalog.pg_roles owner ON owner.oid=relation.relowner "
                "WHERE namespace.nspname=%s AND relation.relkind IN ('r','p') "
                "AND owner.rolname<>%s",
                (SCHEMA_NAME, MIGRATION_ROLE),
            ).fetchone()[0]
        )
        if (
            invalid_foreign_keys
            or rls_tables != EXPECTED_RLS_TABLES
            or disabled_triggers
            or schema_owner != MIGRATION_ROLE
            or non_migration_tables
            or catalog_fingerprint(connection) != manifest.schema_fingerprint
            or manifest.schema_fingerprint != EXPECTED_CATALOG_FINGERPRINT
        ):
            raise BackupVerificationError(
                "restored constraints, RLS, triggers, or ownership are invalid"
            )
        _verify_exact_privileges(connection)
    return row_counts


def _uuid_text(value: str, name: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise BackupVerificationError(f"{name} must be a UUID") from error


def _install_smoke_binding(dsn: str, nonce: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        _assert_restore_session(connection)
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "CREATE TABLE medawarcre.restore_smoke_binding ("
            "singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),"
            "nonce text NOT NULL CHECK (length(nonce)=64))"
        )
        connection.execute(
            "REVOKE ALL ON medawarcre.restore_smoke_binding FROM PUBLIC, "
            "medawarcre_app, medawarcre_admin, medawarcre_backup, "
            "medawarcre_admission, medawarcre_oauth, "
            "medawarcre_provider_ingress, medawarcre_provider_reconcile, "
            "medawarcre_worker, medawarcre_scheduler"
        )
        connection.execute(
            "GRANT SELECT ON medawarcre.restore_smoke_binding "
            "TO medawarcre_app, medawarcre_backup"
        )
        connection.execute(
            "INSERT INTO medawarcre.restore_smoke_binding(singleton,nonce) "
            "VALUES (true,%s)",
            (nonce,),
        )


def _remove_smoke_binding(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        _assert_restore_session(connection)
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute("DROP TABLE IF EXISTS medawarcre.restore_smoke_binding")


def _read_smoke_binding(connection: psycopg.Connection, service: str) -> str:
    try:
        row = connection.execute(
            "SELECT nonce FROM medawarcre.restore_smoke_binding "
            "WHERE singleton"
        ).fetchone()
    except psycopg.Error as error:
        raise BackupVerificationError(
            f"{service} smoke identity is not bound to the restored database"
        ) from error
    if row is None:
        raise BackupVerificationError(
            f"{service} smoke identity is not bound to the restored database"
        )
    return str(row[0])


def _app_service_smoke(
    app_dsn: str,
    workspace_id: str,
    actor_user_id: str,
    other_workspace_id: str,
    nonce: str,
) -> None:
    database = PostgresDatabase(
        PostgresSettings(
            dsn=app_dsn,
            min_size=1,
            max_size=1,
            acquire_timeout=5,
            application_name="medawarcre-restore-smoke",
        )
    )
    database.open(wait=True)
    try:
        context = AuthorityContext.tenant(workspace_id, actor_user_id)
        with database.connection(context) as connection:
            with connection.transaction(force_rollback=True):
                bound_nonce = _read_smoke_binding(connection, "app")
                if bound_nonce != nonce:
                    raise BackupVerificationError(
                        "app smoke identity is not bound to the restored database"
                    )
                own = int(
                    connection.execute(
                        "SELECT count(*) FROM medawarcre.workspaces WHERE id=%s",
                        (workspace_id,),
                    ).fetchone()[0]
                )
                other = int(
                    connection.execute(
                        "SELECT count(*) FROM medawarcre.workspaces WHERE id=%s",
                        (other_workspace_id,),
                    ).fetchone()[0]
                )
                inserted = connection.execute(
                    "INSERT INTO medawarcre.deals"
                    "(workspace_id,source,source_record_id,title,stage) "
                    "VALUES (%s,'restore_smoke','own','Smoke Deal','lead') "
                    "RETURNING id",
                    (workspace_id,),
                ).fetchone()
                if own != 1 or other != 0 or inserted is None:
                    raise BackupVerificationError(
                        "restored app read/write smoke failed"
                    )
                blocked = False
                try:
                    with connection.transaction():
                        connection.execute(
                            "INSERT INTO medawarcre.deals"
                            "(workspace_id,source,source_record_id,title,stage) "
                            "VALUES (%s,'restore_smoke','cross','Bad Deal','lead')",
                            (other_workspace_id,),
                        )
                except psycopg.errors.InsufficientPrivilege:
                    blocked = True
                if not blocked:
                    raise BackupVerificationError(
                        "restored app cross-tenant write was not blocked"
                    )
    finally:
        database.close()


def _backup_service_smoke(
    backup_dsn: str, manifest: BackupManifest, nonce: str
) -> None:
    with psycopg.connect(backup_dsn, autocommit=True) as connection:
        _assert_backup_session(connection)
        with connection.transaction(force_rollback=True):
            connection.execute("SET LOCAL ROLE medawarcre_backup")
            bound_nonce = _read_smoke_binding(connection, "backup")
            if bound_nonce != nonce:
                raise BackupVerificationError(
                    "backup smoke identity is not bound to the restored database"
                )
            observed = {
                table: int(
                    connection.execute(
                        sql.SQL("SELECT count(*) FROM {}.{}").format(
                            sql.Identifier(SCHEMA_NAME), sql.Identifier(table)
                        )
                    ).fetchone()[0]
                )
                for table in manifest.tables
            }
            if observed != manifest.row_counts:
                raise BackupVerificationError(
                    "restored backup identity cannot read the complete archive"
                )
            blocked = False
            try:
                with connection.transaction():
                    connection.execute(
                        "INSERT INTO medawarcre.jobs"
                        "(workspace_id,kind,payload,status,idempotency_key,max_attempts) "
                        "VALUES (gen_random_uuid(),'saved_search','{}'::jsonb,'queued',"
                        "'restore:forbidden',1)"
                    )
            except psycopg.errors.InsufficientPrivilege:
                blocked = True
            if not blocked:
                raise BackupVerificationError(
                    "restored backup identity has mutation privilege"
                )


def restore_backup(
    dsn: str,
    dump_path: str | Path,
    manifest_path: str | Path,
    *,
    smoke_workspace_id: str | None = None,
    smoke_actor_user_id: str | None = None,
    smoke_other_workspace_id: str | None = None,
    smoke_app_dsn: str | None = None,
    smoke_backup_dsn: str | None = None,
) -> RestoreReport:
    """Restore into an empty database and fail unless every proof passes."""
    archive = Path(dump_path)
    manifest = load_manifest(manifest_path)
    try:
        size = archive.stat().st_size
        checksum = _sha256(archive)
    except OSError as error:
        raise BackupVerificationError("backup archive cannot be read") from error
    if size != manifest.dump_size or checksum != manifest.dump_sha256:
        raise BackupVerificationError("backup archive SHA-256 or size is invalid")
    _verify_manifest_contract(manifest)
    with psycopg.connect(dsn, autocommit=True) as connection:
        _assert_restore_session(connection)
        _assert_connection_postgres16(connection, "restore target")
        _assert_bootstrap_roles(connection)
        _assert_clean_target(connection)
    pg_restore = _native_program("pg_restore")
    _assert_native_postgres16(_native_version(pg_restore), "pg_restore")
    safe_connection, environment = _command_connection(dsn)
    _run_native(
        [
            pg_restore,
            "--format=custom",
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-acl",
            f"--role={MIGRATION_ROLE}",
            "--dbname",
            safe_connection,
            str(archive),
        ],
        environment,
    )
    _apply_restore_privileges(dsn)
    row_counts = _verify_restored_database(dsn, manifest)
    smoke_values = (
        smoke_workspace_id,
        smoke_actor_user_id,
        smoke_other_workspace_id,
        smoke_app_dsn,
        smoke_backup_dsn,
    )
    if any(value is None for value in smoke_values):
        raise BackupVerificationError(
            "dedicated app and backup service smoke identities are required"
        )
    workspace_id = _uuid_text(str(smoke_workspace_id), "smoke_workspace_id")
    actor_user_id = _uuid_text(
        str(smoke_actor_user_id), "smoke_actor_user_id"
    )
    other_workspace_id = _uuid_text(
        str(smoke_other_workspace_id), "smoke_other_workspace_id"
    )
    nonce = secrets.token_hex(32)
    _install_smoke_binding(dsn, nonce)
    try:
        try:
            _app_service_smoke(
                str(smoke_app_dsn),
                workspace_id,
                actor_user_id,
                other_workspace_id,
                nonce,
            )
            _backup_service_smoke(str(smoke_backup_dsn), manifest, nonce)
        except BackupVerificationError:
            raise
        except Exception as error:
            raise BackupVerificationError("restored service smoke failed") from error
    finally:
        _remove_smoke_binding(dsn)
    verified_again = _verify_restored_database(dsn, manifest)
    if verified_again != row_counts:
        raise BackupVerificationError("rollback-only service smoke changed restored data")
    return RestoreReport(
        ok=True,
        row_counts=row_counts,
        tenant_isolation=True,
        read_write_smoke=True,
    )


__all__ = [
    "BackupCommandError",
    "BackupError",
    "BackupManifest",
    "BackupVerificationError",
    "RestoreReport",
    "create_backup",
    "load_manifest",
    "restore_backup",
]
