"""Explicit legacy persistence adapter for isolated hosted HTTP tests only."""

from __future__ import annotations

from unittest.mock import patch

from starlette.applications import Starlette

from cre_mcp.access.audit import AuditLog
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.config import CreConfig
from cre_mcp.platform.api import PlatformApi, starlette_app
from cre_mcp.postgres.runtime import (
    HostedPersistenceBundle,
    bind_persistence_lifespan,
)
from cre_mcp.server import create_http_app


def make_testing_persistence_bundle(
    config: CreConfig,
    *,
    human_identity_verifier=None,
    stripe_reconciliation_service=None,
    skool_lifecycle_service=None,
) -> HostedPersistenceBundle:
    access_dir = config.cache_db_path.parent / "access"
    return HostedPersistenceBundle(
        platform_api=PlatformApi(
            config,
            human_identity_verifier=human_identity_verifier,
            stripe_reconciliation_service=stripe_reconciliation_service,
            skool_lifecycle_service=skool_lifecycle_service,
        ),
        access_registry=WorkspaceRegistry(
            config.access_registry_path or access_dir / "registry.json"
        ),
        audit_log=AuditLog(
            config.access_audit_path or access_dir / "audit.jsonl"
        ),
        backend="postgres",
    )


def create_testing_http_app(
    *,
    config: CreConfig,
    human_identity_verifier=None,
    stripe_reconciliation_service=None,
    skool_lifecycle_service=None,
):
    bundle = make_testing_persistence_bundle(
        config,
        human_identity_verifier=human_identity_verifier,
        stripe_reconciliation_service=stripe_reconciliation_service,
        skool_lifecycle_service=skool_lifecycle_service,
    )
    with patch(
        "cre_mcp.postgres.runtime.build_postgres_hosted_persistence",
        return_value=bundle,
    ):
        return create_http_app(config=config)


def create_testing_starlette_app(
    config: CreConfig,
    *,
    human_identity_verifier=None,
    stripe_reconciliation_service=None,
    skool_lifecycle_service=None,
    include_uncertified_deal_routes: bool = False,
):
    bundle = make_testing_persistence_bundle(
        config,
        human_identity_verifier=human_identity_verifier,
        stripe_reconciliation_service=stripe_reconciliation_service,
        skool_lifecycle_service=skool_lifecycle_service,
    )
    if include_uncertified_deal_routes:
        app = Starlette(
            routes=bundle.platform_api.routes(
                include_uncertified_deal_routes=True
            )
        )
        return bind_persistence_lifespan(app, bundle)
    with patch(
        "cre_mcp.postgres.runtime.build_postgres_hosted_persistence",
        return_value=bundle,
    ):
        return starlette_app(
            config=config,
        )


__all__ = [
    "create_testing_http_app",
    "create_testing_starlette_app",
    "make_testing_persistence_bundle",
]
