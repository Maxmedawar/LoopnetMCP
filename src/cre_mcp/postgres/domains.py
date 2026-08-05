"""Exact request scope for hosted customer-domain repositories."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from typing import Any
from uuid import UUID

from cre_mcp.postgres.admission import AdmissionOutcome


class AdmittedRequestUnavailable(RuntimeError):
    """A fresh, exactly bound hosted domain request is unavailable."""


def require_fresh_admission(admission: object) -> AdmissionOutcome:
    """Return one validated fresh allow or reject the domain boundary."""
    if not isinstance(admission, AdmissionOutcome):
        raise AdmittedRequestUnavailable(
            "hosted domain persistence requires an exact admission"
        )
    try:
        UUID(admission.invocation_id)
        UUID(admission.request_correlation_id)
    except (ValueError, TypeError, AttributeError) as error:
        raise AdmittedRequestUnavailable(
            "hosted domain persistence admission is malformed"
        ) from error
    if (
        admission.decision != "allowed"
        or admission.replayed
        or admission.finalized
        or not admission.workspace_public_id.strip()
        or not admission.actor_user_id.strip()
        or not admission.session_id.strip()
        or not admission.tool_name.strip()
        or admission.approval_id is not None
        or not admission.reason_code.strip()
        or not admission.safe_reason.strip()
    ):
        raise AdmittedRequestUnavailable(
            "hosted domain persistence requires a fresh allowed admission"
        )
    return admission


@dataclass(frozen=True)
class HostedRequestRepositories:
    """All hosted domain ports bound to one exact request admission."""

    admission: AdmissionOutcome
    platform: Any
    provider: Any
    search: Any
    deal: Any
    privacy: Any
    job: Any
    document: Any
    truth_asset: Any

    def __post_init__(self) -> None:
        require_fresh_admission(self.admission)
        for item in fields(self):
            if item.name != "admission" and getattr(self, item.name) is None:
                raise AdmittedRequestUnavailable(
                    f"hosted domain repository is unavailable: {item.name}"
                )

    def require(self, domain: str) -> Any:
        """Return one named domain without permitting dynamic fallback."""
        if domain not in {
            "platform",
            "provider",
            "search",
            "deal",
            "privacy",
            "job",
            "document",
            "truth_asset",
        }:
            raise AdmittedRequestUnavailable("unknown hosted domain repository")
        repository = getattr(self, domain)
        if repository is None:
            raise AdmittedRequestUnavailable(
                f"hosted domain repository is unavailable: {domain}"
            )
        return repository


@dataclass
class _RepositoryLease:
    repositories: HostedRequestRepositories
    active: bool = True


_current: ContextVar[_RepositoryLease | None] = ContextVar(
    "cre_hosted_request_repositories",
    default=None,
)


def current_hosted_request_repositories() -> HostedRequestRepositories | None:
    """Return the active hosted repository scope, if this is a hosted call."""
    lease = _current.get()
    if lease is None or not lease.active:
        return None
    return lease.repositories


@contextmanager
def use_hosted_request_repositories(repositories: HostedRequestRepositories):
    """Bind all domain repositories for the duration of one tool execution."""
    if not isinstance(repositories, HostedRequestRepositories):
        raise AdmittedRequestUnavailable(
            "hosted domain repository provider returned an invalid scope"
        )
    require_fresh_admission(repositories.admission)
    lease = _RepositoryLease(repositories)
    token = _current.set(lease)
    try:
        yield repositories
    finally:
        lease.active = False
        _current.reset(token)


__all__ = [
    "AdmittedRequestUnavailable",
    "HostedRequestRepositories",
    "current_hosted_request_repositories",
    "require_fresh_admission",
    "use_hosted_request_repositories",
]
