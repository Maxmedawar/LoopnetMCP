"""RED characterization for the hosted source-rights boundary.

These tests intentionally target the required Phase 10 behavior before the
production controls exist. Keep them as regression coverage after GREEN.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from cre_mcp.access.context import TenantContext, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.cache import TTLCache
from cre_mcp.config import CreConfig
from cre_mcp.enrichment.nearby import nearby_brands
from cre_mcp.http.errors import FetchClientError
from cre_mcp.http.fetch import FetchClient
from cre_mcp.models import Listing, SourceCapabilities
from cre_mcp.sources.base import ListingSource, SearchQuery, SourceError
from cre_mcp.sources.registry import SourceRegistry
from cre_mcp.tools.truth_tools import ingest_document


def _hosted_context() -> TenantContext:
    return TenantContext(
        workspace_id="ws-source-rights",
        profile=Profile.FULL_OPERATOR,
        trusted=False,
        display_name="Hosted source-rights test",
    )


def _local_context() -> TenantContext:
    return TenantContext(
        workspace_id="local-source-rights",
        profile=Profile.FULL_OPERATOR,
        trusted=True,
        display_name="Explicit trusted-local source-rights test",
    )


class _UnclassifiedSource(ListingSource):
    name = "unclassified_fixture"
    capabilities = SourceCapabilities()

    async def search(self, query: SearchQuery) -> list[Listing]:
        return [
            Listing(
                source=self.name,
                source_id="native-1",
                name="Raw fixture",
                address="1 Main St",
                city="Austin",
                state="TX",
                url="https://unclassified.example/native-1",
                raw={"native_payload": {"secret_field": "must-not-escape"}},
            )
        ]

    async def get_detail(self, ref):  # pragma: no cover - not used here
        return (await self.search(SearchQuery(location="Austin, TX")))[0]


def test_listing_sources_are_disabled_by_default():
    config = CreConfig(_env_file=None)

    assert config.sources
    assert all(not toggle.enabled for toggle in config.sources.values())


def test_missing_listing_source_toggle_does_not_enable_source():
    registry = SourceRegistry(
        config=CreConfig(
            _env_file=None,
            sources={"crexi": {"enabled": False}},
        )
    )

    with pytest.raises(SourceError, match="Unknown listing source: loopnet"):
        registry.get("loopnet")


def test_unknown_host_has_no_hosted_fallback_policy():
    client = FetchClient(
        config=CreConfig(
            _env_file=None,
            transport="http",
            cache_db_path=":memory:",
        )
    )

    with use_context(_hosted_context()):
        with pytest.raises(FetchClientError, match="source-rights"):
            client._policy_for_url("https://unknown-source.invalid/data")


def test_fred_policy_cannot_cache_or_persist():
    client = FetchClient(
        config=CreConfig(
            _env_file=None,
            cache_db_path=":memory:",
            source_rights_enabled={"market.fred": True},
        )
    )
    with use_context(_local_context()):
        policy = client._policy_for_url(
            "https://api.stlouisfed.org/fred/series/observations"
        )

    assert policy.cache_ttl_seconds == 0
    assert policy.detail_cache_ttl_seconds in {None, 0}
    assert policy.persist is False


@pytest.mark.asyncio
async def test_hosted_registry_rejects_unclassified_source_and_raw_payload():
    with use_context(_hosted_context()):
        result = await SourceRegistry(sources=[_UnclassifiedSource()]).search_all(
            SearchQuery(location="Austin, TX")
        )

    assert result.listings == []
    assert "source-rights" in result.errors["unclassified_fixture"]


def test_cache_key_redacts_query_credentials():
    client = FetchClient(
        config=CreConfig(
            _env_file=None,
            cache_db_path=":memory:",
            source_rights_enabled={"market.census_acs": True},
        )
    )
    url = (
        "https://api.census.gov/data/2024/acs/acs5"
        "?get=NAME&key=super-secret-api-key&access_token=other-secret"
    )
    with use_context(_local_context()):
        policy = client._policy_for_url(url)
        key = client._cache_key(policy, "GET", url)

    assert "super-secret-api-key" not in key
    assert "other-secret" not in key
    assert "access_token" not in key


@pytest.mark.asyncio
async def test_hosted_rights_denial_happens_before_cache_lookup():
    cache = TTLCache()
    config = CreConfig(
        _env_file=None,
        transport="http",
        cache_db_path=":memory:",
    )
    client = FetchClient(config=config, cache=cache)
    url = "https://www.loopnet.com/search/commercial-real-estate/austin-tx/"

    with patch.object(
        cache,
        "get",
        side_effect=AssertionError("cache lookup must not run"),
    ) as cache_get:
        with use_context(_hosted_context()):
            with pytest.raises(FetchClientError, match="source-rights"):
                await client.get_text(url)

    cache_get.assert_not_called()


def test_direct_overpass_adapter_cannot_bypass_hosted_rights_gate():
    response = Mock(status_code=200)
    response.json.return_value = {
        "elements": [
            {
                "id": 1,
                "lat": 30.2672,
                "lon": -97.7431,
                "tags": {"brand": "Fixture", "amenity": "cafe"},
            }
        ]
    }
    with patch(
        "cre_mcp.enrichment.nearby.requests.post",
        return_value=response,
    ) as request:
        with use_context(_hosted_context()):
            result = nearby_brands(30.2672, -97.7431, radius_m=801)

    assert result == []
    request.assert_not_called()


@pytest.mark.asyncio
async def test_hosted_document_url_requires_server_attestation_before_download():
    download = AsyncMock(side_effect=AssertionError("network must not run"))
    with patch("cre_mcp.tools.truth_tools._to_thread_fetch", download):
        with use_context(_hosted_context()):
            result = await ingest_document(
                "crexi:fixture",
                url="https://documents.example/offering-memorandum.pdf",
            )

    assert "attestation" in result["error"].casefold()
    download.assert_not_awaited()
