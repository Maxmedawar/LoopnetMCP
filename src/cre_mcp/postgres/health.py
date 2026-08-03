"""Secret-free PostgreSQL liveness and readiness diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from cre_mcp.postgres.migrations import Migration
from cre_mcp.postgres.pool import PostgresDatabase
from cre_mcp.postgres.schema import (
    EXPECTED_CATALOG_FINGERPRINT,
    EXPECTED_RLS_TABLES,
    EXPECTED_TABLES,
)


@dataclass(frozen=True)
class LivenessResult:
    ok: bool
    code: str


@dataclass(frozen=True)
class ReadinessResult:
    ok: bool
    code: str
    server_version: int | None = None
    applied_versions: tuple[int, ...] = ()
    dirty_versions: tuple[int, ...] = ()
    missing_tables: tuple[str, ...] = ()
    missing_rls: tuple[str, ...] = ()
    checksum_mismatches: tuple[int, ...] = ()
    invalid_foreign_keys: int = 0
    unexpected_versions: tuple[int, ...] = ()
    non_applied_versions: tuple[int, ...] = ()
    description_mismatches: tuple[int, ...] = ()
    unexpected_tables: tuple[str, ...] = ()
    unexpected_rls: tuple[str, ...] = ()
    schema_drift: bool = False


def check_liveness(database: PostgresDatabase) -> LivenessResult:
    try:
        ok = database.liveness_probe()
        return LivenessResult(ok, "ok" if ok else "unexpected")
    except Exception:
        return LivenessResult(False, "database_unavailable")


def check_readiness(
    database: PostgresDatabase,
    *,
    expected: Sequence[Migration],
) -> ReadinessResult:
    expected_by_version = {migration.version: migration for migration in expected}
    try:
        snapshot = database.readiness_snapshot()
    except Exception:
        return ReadinessResult(False, "database_unavailable")

    server_version = snapshot.server_version
    history = snapshot.history
    tables = snapshot.tables
    rls = snapshot.rls_tables
    invalid_foreign_keys = snapshot.invalid_foreign_keys
    actual_catalog_fingerprint = snapshot.catalog_fingerprint
    actual_versions = tuple(int(row[0]) for row in history)
    applied = tuple(int(row[0]) for row in history if row[3] == "applied")
    dirty = tuple(int(row[0]) for row in history if bool(row[4]))
    expected_versions = tuple(migration.version for migration in expected)
    unexpected_versions = tuple(
        version for version in actual_versions if version not in expected_by_version
    )
    non_applied_versions = tuple(
        int(row[0]) for row in history if row[3] != "applied"
    )
    mismatches = tuple(
        int(version)
        for version, _, checksum, _, _ in history
        if int(version) in expected_by_version
        and str(checksum) != expected_by_version[int(version)].checksum
    )
    description_mismatches = tuple(
        int(version)
        for version, description, _, _, _ in history
        if int(version) in expected_by_version
        and str(description) != expected_by_version[int(version)].name
    )
    missing_tables = tuple(sorted(EXPECTED_TABLES - tables))
    unexpected_tables = tuple(sorted(tables - EXPECTED_TABLES))
    missing_rls = tuple(sorted(EXPECTED_RLS_TABLES - rls))
    unexpected_rls = tuple(sorted(rls - EXPECTED_RLS_TABLES))
    schema_drift = actual_catalog_fingerprint != EXPECTED_CATALOG_FINGERPRINT
    ok = (
        server_version >= 160000
        and actual_versions == expected_versions
        and applied == expected_versions
        and not dirty
        and not unexpected_versions
        and not non_applied_versions
        and not mismatches
        and not description_mismatches
        and not missing_tables
        and not unexpected_tables
        and not missing_rls
        and not unexpected_rls
        and not schema_drift
        and invalid_foreign_keys == 0
    )
    return ReadinessResult(
        ok=ok,
        code="ok" if ok else "schema_not_ready",
        server_version=server_version,
        applied_versions=applied,
        dirty_versions=dirty,
        missing_tables=missing_tables,
        missing_rls=missing_rls,
        checksum_mismatches=mismatches,
        invalid_foreign_keys=invalid_foreign_keys,
        unexpected_versions=unexpected_versions,
        non_applied_versions=non_applied_versions,
        description_mismatches=description_mismatches,
        unexpected_tables=unexpected_tables,
        unexpected_rls=unexpected_rls,
        schema_drift=schema_drift,
    )


__all__ = [
    "LivenessResult",
    "ReadinessResult",
    "check_liveness",
    "check_readiness",
]
