from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from cre_mcp.postgres import cli
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.migrations import load_migrations
from cre_mcp.postgres.pool import INTERNAL_ROLES
from cre_mcp.postgres.authority import ADMISSION_ROLE, SERVICE_ROLES
from cre_mcp.postgres.schema import (
    AUDIT_SINK_TABLES,
    CERTIFIED_TABLES,
    EXPECTED_CATALOG_FINGERPRINT,
    EXPECTED_RLS_TABLES,
    EXPECTED_TABLES,
    PLATFORM_AUTHORITY_TABLES,
    TENANT_TABLES,
)


def test_production_migration_inventory_is_contiguous_and_stable() -> None:
    migrations = load_migrations()
    assert [migration.version for migration in migrations] == list(
        range(1, len(migrations) + 1)
    )
    assert migrations
    assert all(len(migration.checksum) == 64 for migration in migrations)
    assert all(migration.sql.strip().endswith(";") for migration in migrations)


def test_launch_schema_inventory_covers_every_required_domain() -> None:
    required = {
        "users",
        "human_identities",
        "workspaces",
        "memberships",
        "workspace_accounts",
        "connected_clients",
        "integration_events",
        "subscriptions",
        "access_grants",
        "oauth_clients",
        "oauth_codes",
        "oauth_sessions",
        "oauth_refresh_history",
        "external_accounts",
        "provider_events",
        "provider_event_attempts",
        "saved_searches",
        "saved_search_seen_matches",
        "search_runs",
        "search_results",
        "deals",
        "internal_opportunities",
        "internal_opportunity_sources",
        "consents",
        "privacy_requests",
        "retention_actions",
        "staff_audit_log",
        "access_decision_audit",
        "tool_approvals",
        "daily_quota_usage",
        "legacy_id_aliases",
        "jobs",
        "job_attempts",
    }
    assert required <= EXPECTED_TABLES
    assert required - {
        "users",
        "human_identities",
        "oauth_clients",
        "internal_opportunities",
        "legacy_id_aliases",
    } <= TENANT_TABLES
    # Every certified relation carries row-level security except the three that
    # hold no tenant data. The exception list is written out rather than
    # widened, because "everything except a set that grows quietly" is not an
    # invariant. Two sets are excluded by name and for stated reasons:
    #
    #   PLATFORM_AUTHORITY_TABLES — the sign-in/OAuth/session stores, which run
    #   before a workspace context exists, so there is no ``app.workspace_id``
    #   for a policy to read. Their tenancy is enforced in the store code, and
    #   migration 0010 enables no RLS on them.
    #
    #   AUDIT_SINK_TABLES — access_audit_log, whose workspace column is the
    #   public identifier string rather than the uuid every RLS policy compares.
    assert EXPECTED_RLS_TABLES == CERTIFIED_TABLES - {
        "schema_migrations",
        "plans",
        "oauth_clients",
    }
    assert not (PLATFORM_AUTHORITY_TABLES & EXPECTED_RLS_TABLES)
    assert not (AUDIT_SINK_TABLES & EXPECTED_RLS_TABLES)
    assert (
        EXPECTED_TABLES
        == CERTIFIED_TABLES | PLATFORM_AUTHORITY_TABLES | AUDIT_SINK_TABLES
    )
    assert ADMISSION_ROLE == "medawarcre_admission"
    assert set(SERVICE_ROLES.values()) == {
        "medawarcre_oauth",
        "medawarcre_provider_ingress",
        "medawarcre_provider_reconcile",
        "medawarcre_worker",
        "medawarcre_scheduler",
    }
    assert len(EXPECTED_CATALOG_FINGERPRINT) == 64


def test_internal_role_and_audit_result_vocabularies_are_exact() -> None:
    assert INTERNAL_ROLES == {
        "owner",
        "admin",
        "jv_operations",
        "support",
        "security_audit",
        "read_only_analyst",
    }
    migration_sql = load_migrations()[0].sql
    assert "result text NOT NULL" in migration_sql
    assert "('allowed', 'denied', 'succeeded', 'failed')" in migration_sql


def test_settings_validate_bounds_and_hide_connection_secrets() -> None:
    settings = PostgresSettings(
        dsn="postgresql://phase2:do-not-print@localhost/medawarcre",
        min_size=1,
        max_size=4,
    )
    rendered = repr(settings)
    assert "do-not-print" not in rendered
    assert "phase2" not in rendered
    assert "localhost" not in rendered
    assert settings.min_size == 1
    assert settings.max_size == 4

    with pytest.raises(ValueError, match="max_size"):
        PostgresSettings(dsn="postgresql://localhost/db", min_size=5, max_size=2)
    with pytest.raises(ValueError, match="database DSN"):
        PostgresSettings(dsn="   ")
    with pytest.raises(ValueError, match="max_waiting"):
        PostgresSettings(dsn="postgresql://localhost/db", max_waiting=0)


def test_contract_document_declares_phase_boundary() -> None:
    contract = (
        Path(__file__).parents[2]
        / "docs"
        / "launch"
        / "PHASE_2_POSTGRESQL_CONTRACT.md"
    ).read_text(encoding="utf-8")
    assert "Explicit non-scope" in contract
    assert "does not" in contract
    assert "protected SQLite backup" in contract
    assert "customer roles receive no privilege" in contract.casefold()
    assert contract.count("[PHASE 3 LAUNCH BLOCKER]") >= 7


def test_operator_cli_reads_dsns_only_from_environment_and_redacts_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_dsn = "postgresql://operator:never-print-this@database.invalid/launch"
    observed: list[str] = []

    class SuccessfulRunner:
        def __init__(self, dsn: str) -> None:
            observed.append(dsn)

        def apply(self) -> list[int]:
            return [1]

    monkeypatch.setenv(cli.MIGRATION_DSN_ENV, secret_dsn)
    monkeypatch.setattr(cli, "MigrationRunner", SuccessfulRunner)
    assert cli.main(["migrate"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == '{"applied_versions":[1],"ok":true}\n'
    assert observed == [secret_dsn]
    assert "never-print-this" not in captured.out

    class FailingRunner:
        def __init__(self, dsn: str) -> None:
            observed.append(dsn)

        def apply(self) -> list[int]:
            raise psycopg.OperationalError("never-print-this")

    monkeypatch.setattr(cli, "MigrationRunner", FailingRunner)
    assert cli.main(["migrate"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == '{"code":"database_failed","ok":false}\n'
    assert "never-print-this" not in captured.err

    class InvalidInputRunner:
        def __init__(self, dsn: str) -> None:
            observed.append(dsn)

        def apply(self) -> list[int]:
            raise ValueError("never-print-this")

    monkeypatch.setattr(cli, "MigrationRunner", InvalidInputRunner)
    assert cli.main(["migrate"]) == 1
    captured = capsys.readouterr()
    assert captured.err == '{"code":"operator_input_invalid","ok":false}\n'
    assert "never-print-this" not in captured.err

    class UnexpectedRunner:
        def __init__(self, dsn: str) -> None:
            observed.append(dsn)

        def apply(self) -> list[int]:
            raise RuntimeError("never-print-this")

    monkeypatch.setattr(cli, "MigrationRunner", UnexpectedRunner)
    assert cli.main(["migrate"]) == 1
    captured = capsys.readouterr()
    assert captured.err == '{"code":"unexpected_failure","ok":false}\n'
    assert "never-print-this" not in captured.err
