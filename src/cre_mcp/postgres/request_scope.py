"""Bind every certified domain repository to one exact hosted admission.

``AccessMiddleware`` holds a provider and calls ``bind(admission)`` once per
admitted tool call. What comes back is the frozen ``HostedRequestRepositories``
bundle, whose ``__post_init__`` refuses a missing port — so this is the single
place that decides which domains a hosted process can serve, and it cannot
half-answer.

Construction is per request rather than per process on purpose. Each repository
holds its admission and re-derives authority from it on every method; a
long-lived instance would have to be re-pointed at a new admission, and a
re-pointable object is one that can be pointed at the wrong one.
"""

from __future__ import annotations

from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.deals import PostgresDealRepository
from cre_mcp.postgres.document_attestations import (
    PostgresDocumentAttestationRepository,
)
from cre_mcp.postgres.domains import (
    AdmittedRequestUnavailable,
    HostedRequestRepositories,
    require_fresh_admission,
)
from cre_mcp.postgres.jobs import PostgresJobRepository
from cre_mcp.postgres.platform_context import PostgresPlatformRepository
from cre_mcp.postgres.pool import PostgresDatabase
from cre_mcp.postgres.privacy import PostgresPrivacyRepository
from cre_mcp.postgres.provider_entitlements import PostgresProviderRepository
from cre_mcp.postgres.searches import PostgresSearchRepository
from cre_mcp.postgres.truth_assets import PostgresTruthAssetRepository


class HostedDomainRepositoryProvider:
    """Construct one complete request-scoped repository bundle."""

    def __init__(
        self,
        database: PostgresDatabase,
        *,
        config: CreConfig | None = None,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise TypeError("hosted domain repositories require PostgreSQL")
        self._database = database
        self._config = config

    def bind(self, admission: Any) -> HostedRequestRepositories:
        """Return every domain port bound to one fresh allowed admission."""
        validated: AdmissionOutcome = require_fresh_admission(admission)
        try:
            return HostedRequestRepositories(
                admission=validated,
                platform=PostgresPlatformRepository(self._database, validated),
                provider=PostgresProviderRepository(self._database, validated),
                search=PostgresSearchRepository(self._database, validated),
                deal=PostgresDealRepository(
                    self._database, validated, config=self._config
                ),
                privacy=PostgresPrivacyRepository(self._database, validated),
                job=PostgresJobRepository(self._database, validated),
                document=PostgresDocumentAttestationRepository(
                    self._database, validated
                ),
                truth_asset=PostgresTruthAssetRepository(
                    self._database, validated
                ),
            )
        except AdmittedRequestUnavailable:
            raise
        except Exception as error:
            # The bundle is all-or-nothing. A partially constructed scope that
            # reached tool code would be indistinguishable from a complete one
            # right up to the first call on the port that failed to build.
            raise AdmittedRequestUnavailable(
                "hosted domain repositories could not be bound to this request"
            ) from error


__all__ = ["HostedDomainRepositoryProvider"]
