"""Explicit legacy persistence adapter for isolated hosted HTTP tests only."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from starlette.applications import Starlette

from cre_mcp.access.audit import AuditLog
from cre_mcp.access.engine import args_fingerprint
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DealStore
from cre_mcp.platform.api import PlatformApi, starlette_app
from cre_mcp.postgres.runtime import (
    HostedPersistenceBundle,
    bind_persistence_lifespan,
)
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.domains import HostedRequestRepositories
from cre_mcp.server import create_http_app


class TestingAdmissionRepository:
    """Legacy state adapter used only by isolated hosted HTTP tests."""

    __test__ = False

    def __init__(self, registry: WorkspaceRegistry, audit_log: AuditLog) -> None:
        self.registry = registry
        self.audit_log = audit_log
        self._approval_aliases: dict[str, str] = {}

    def admit(
        self,
        context,
        tool_name,
        arguments,
        *,
        quota_bucket,
        requires_approval,
        approval_token=None,
        invocation_id=None,
        request_correlation_id=None,
    ) -> AdmissionOutcome:
        invocation = str(invocation_id or uuid4())
        request_id = str(request_correlation_id or uuid4())
        fingerprint = args_fingerprint(arguments)
        decision = "allowed"
        reason_code = "authority_admitted"
        safe_reason = "request admitted by live authority"
        approval_id = None

        if requires_approval and approval_token is None:
            decision = "approval_required"
            reason_code = "approval_required"
            safe_reason = "sensitive action requires operator approval"
            registry_approval_id = self.registry.request_approval(
                context.workspace_id,
                tool_name,
                fingerprint,
            )
            approval_id = invocation
            self._approval_aliases[approval_id] = registry_approval_id

        if decision == "allowed" and quota_bucket is not None:
            limit = context.quota_limits.get(quota_bucket)
            if limit is not None and self.registry.usage_today(
                context.workspace_id,
                quota_bucket,
            ) >= limit:
                decision = "denied"
                reason_code = "quota_exceeded"
                safe_reason = "access denied: daily quota exceeded"
        if (
            decision == "allowed"
            and requires_approval
            and (
                not isinstance(approval_token, str)
                or approval_token not in self._approval_aliases
                or not self.registry.consume_approval(
                    self._approval_aliases[approval_token],
                    context.workspace_id,
                    tool_name,
                    fingerprint,
                )
            )
        ):
            decision = "denied"
            reason_code = "approval_invalid"
            safe_reason = "access denied: approval is unavailable or does not match"

        if decision == "allowed" and quota_bucket is not None:
            self.registry.record_usage(context.workspace_id, quota_bucket)

        self.audit_log.record(
            workspace_id=context.workspace_id,
            tool=tool_name,
            decision=decision,
            reason=safe_reason,
        )
        return AdmissionOutcome(
            invocation_id=invocation,
            request_correlation_id=request_id,
            workspace_public_id=context.workspace_id,
            actor_user_id=context.actor_id,
            session_id=context.session_id,
            tool_name=tool_name,
            decision=decision,
            reason_code=reason_code,
            safe_reason=safe_reason,
            approval_id=approval_id,
        )

    def record_final(
        self,
        admission,
        *,
        succeeded,
        reason_code,
        safe_reason,
    ) -> str:
        self.audit_log.record(
            workspace_id=admission.workspace_public_id,
            tool=admission.tool_name,
            decision="allowed" if succeeded else "denied",
            reason=safe_reason,
        )
        return str(uuid4())


class TestingDomainRepositoryProvider:
    """Explicit legacy adapters for isolated hosted protocol tests only."""

    __test__ = False

    def __init__(self, config: CreConfig, platform_api: PlatformApi) -> None:
        self.config = config
        self.platform_api = platform_api
        self.deal_store = DealStore(config=self.config)

    def bind(self, admission: AdmissionOutcome) -> HostedRequestRepositories:
        deal_store = self.deal_store
        marker = object()
        return HostedRequestRepositories(
            admission=admission,
            platform=self.platform_api.repository,
            provider=marker,
            search=deal_store,
            deal=deal_store,
            privacy=marker,
            job=marker,
            document=marker,
            truth_asset=marker,
        )


def make_testing_persistence_bundle(
    config: CreConfig,
    *,
    human_identity_verifier=None,
    stripe_reconciliation_service=None,
    skool_lifecycle_service=None,
) -> HostedPersistenceBundle:
    access_dir = config.cache_db_path.parent / "access"
    platform_api = PlatformApi(
        config,
        human_identity_verifier=human_identity_verifier,
        stripe_reconciliation_service=stripe_reconciliation_service,
        skool_lifecycle_service=skool_lifecycle_service,
    )
    registry = WorkspaceRegistry(
        config.access_registry_path or access_dir / "registry.json"
    )
    audit_log = AuditLog(
        config.access_audit_path or access_dir / "audit.jsonl"
    )
    return HostedPersistenceBundle(
        platform_api=platform_api,
        domain_repository_provider=TestingDomainRepositoryProvider(
            config,
            platform_api,
        ),
        oauth_authority=platform_api.authority,
        admission_repository=TestingAdmissionRepository(registry, audit_log),
        audit_log=audit_log,
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
