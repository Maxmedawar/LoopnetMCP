"""Adversarial RED tests for registry and secret-boundary hardening."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from curl_cffi.requests import RequestsError
from fastmcp.tools.tool import ToolResult

from cre_mcp.access.context import (
    TenantContext,
    current_context,
    use_context,
    use_runtime_config,
)
from cre_mcp.access.profiles import Profile
from cre_mcp.command.snapshots import SnapshotStore
from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DealStore, get_deal_store
from cre_mcp.enrichment import nearby as nearby_module
from cre_mcp.enrichment.owner import OwnerLookup
from cre_mcp.enrichment.providers.attom import AttomProvider
from cre_mcp.enrichment.providers.regrid import RegridProvider
from cre_mcp.enrichment.traffic import TrafficProvider
from cre_mcp.execution.contacts import RealEstateApiSkiptraceProvider
from cre_mcp.geo.crosswalk import GeoCrosswalk
from cre_mcp.geo import resolver as geo_resolver_module
from cre_mcp.geo.resolver import GeoResolver
from cre_mcp.http.errors import FetchClientError
from cre_mcp.http.browser import BrowserFetcher as SharedBrowserFetcher
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.http.policies import FetchPolicy
from cre_mcp.market.irs_soi import IrsSoiProvider
from cre_mcp.models import (
    AggregatedSearchResult,
    Deal,
    GeoLevel,
    GeoRef,
    Listing,
    OwnerRecord,
)
from cre_mcp.platform.repository import PlatformRepository, get_platform_repository
from cre_mcp.source_rights.gate import (
    SourceRightsDeniedError,
    collect_authorized_sources,
    require_source,
    require_url,
)
from cre_mcp.source_rights.output import (
    redact_credentials,
    redact_url,
    safe_error_message,
    sanitize_payload,
    sanitize_tool_result,
)
from cre_mcp.source_rights.registry import (
    DEFAULT_REGISTRY_PATH,
    SourceRightsRegistry,
    SourceRightsRegistryError,
)
from cre_mcp.scraper.browser import (
    BrowserFetchError,
    BrowserFetcher as LoopnetBrowserFetcher,
)
from cre_mcp.scraper.client import LoopnetClient, get_client
from cre_mcp.sources.base import SearchQuery, SourceError
from cre_mcp.sources.registry import SourceRegistry
from cre_mcp.tools.deal_tools import analyze_deal, find_deals
from cre_mcp.tools import deal_tools as deal_tools_module
from cre_mcp.tools import market_tools as market_tools_module
from cre_mcp.tools import owner_tools as owner_tools_module
from cre_mcp.tools.control_tools import find_control_opportunities
from cre_mcp.tools.listing_tools import get_property_details, search_properties
from cre_mcp.tools.truth_tools import _to_thread_fetch


def _catalog() -> dict:
    return json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))


def _write_catalog(tmp_path, catalog: dict):
    path = tmp_path / "source-rights.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


def test_source_rights_registry_is_declared_as_package_data():
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    pyproject = pyproject_path.read_text(encoding="utf-8")

    assert "[tool.setuptools.package-data]" in pyproject
    assert '"cre_mcp.source_rights" = ["registry.json"]' in pyproject


def test_source_rights_gate_imports_in_clean_interpreter():
    repository_root = Path(__file__).parents[2]
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        item
        for item in (str(repository_root / "src"), existing_pythonpath)
        if item
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import cre_mcp.source_rights.gate; print('ok')",
        ],
        cwd=repository_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_redact_url_strips_userinfo_fragment_and_configured_secret_values():
    redacted = redact_url(
        "https://api-user:api-pass@example.test/data"
        "?customer_ref=configured-secret&safe=visible#private-fragment",
        secret_values=("configured-secret",),
    )

    assert "api-user" not in redacted
    assert "api-pass" not in redacted
    assert "configured-secret" not in redacted
    assert "private-fragment" not in redacted
    assert redacted == "https://example.test/data?safe=visible"


def test_redact_url_never_retains_configured_secret_in_path():
    secret = "configured-path-secret-2ca7"

    redacted = redact_url(
        f"https://example.test/v1/{secret}/asset?view=full",
        secret_values=(secret,),
    )

    assert secret not in redacted


def test_recursive_redaction_is_cycle_depth_and_custom_secret_safe():
    payload: dict[str, object] = {
        "opaque_header": "Bearer configured-secret",
        "levels": {},
    }
    payload["self"] = payload
    cursor = payload["levels"]
    assert isinstance(cursor, dict)
    for index in range(20):
        child: dict[str, object] = {"index": index}
        cursor["next"] = child
        cursor = child

    redacted = redact_credentials(
        payload,
        secret_values=("configured-secret",),
        max_depth=6,
    )

    assert redacted["opaque_header"] == "[redacted]"
    assert redacted["self"] == "[circular]"
    assert "configured-secret" not in repr(redacted)
    assert "[max-depth]" in repr(redacted)


def test_registry_rejects_duplicate_url_rules_at_startup(tmp_path):
    catalog = _catalog()
    duplicate = dict(catalog["sources"][0])
    duplicate["source_id"] = "test.duplicate-url-rule"
    duplicate["adapter_names"] = []
    duplicate["adapter_paths"] = ["tests.duplicate"]
    catalog["sources"].append(duplicate)

    with pytest.raises(SourceRightsRegistryError, match="duplicate.*URL rule"):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


def test_registry_rejects_source_id_and_adapter_name_collision(tmp_path):
    catalog = _catalog()
    first = catalog["sources"][0]
    duplicate = dict(catalog["sources"][1])
    duplicate["source_id"] = "test.adapter-owner"
    duplicate["adapter_names"] = [first["source_id"]]
    duplicate["adapter_paths"] = ["tests.adapter_owner"]
    duplicate["url_rules"] = []
    duplicate["egress_managed_by"] = "tests"
    catalog["sources"].append(duplicate)

    with pytest.raises(SourceRightsRegistryError, match="source_id.*adapter|adapter.*source_id"):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


@pytest.mark.parametrize("alias", ["/api/%78", "/api/./x"])
def test_registry_rejects_canonically_duplicate_url_rules_at_startup(
    tmp_path,
    alias,
):
    catalog = _catalog()
    first = catalog["sources"][0]
    first["url_rules"] = [
        {"host": "canonical.example.test", "path_prefix": "/api/x"}
    ]
    duplicate = dict(first)
    duplicate["source_id"] = "test.canonical-duplicate"
    duplicate["adapter_names"] = []
    duplicate["adapter_paths"] = ["tests.canonical_duplicate"]
    duplicate["url_rules"] = [
        {"host": "canonical.example.test", "path_prefix": alias}
    ]
    catalog["sources"].append(duplicate)

    with pytest.raises(SourceRightsRegistryError, match="duplicate.*URL rule"):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


def test_direct_egress_and_configured_listing_adapters_are_catalogued():
    registry = SourceRightsRegistry()
    adapter_paths = {
        path
        for record in registry.records
        for path in record.adapter_paths
    }
    adapter_names = {
        name
        for record in registry.records
        for name in record.adapter_names
    }

    assert {
        "cre_mcp.enrichment.nearby",
        "cre_mcp.http.browser",
        "cre_mcp.scraper.browser",
        "cre_mcp.tools.truth_tools",
    }.issubset(adapter_paths)
    assert set(CreConfig(_env_file=None).sources).issubset(adapter_names)


def test_registry_resolves_only_uniquely_owned_adapter_paths():
    registry = SourceRightsRegistry()

    assert (
        registry.for_adapter("cre_mcp.comps.records:04013").source_id
        == "sales.maricopa_04013"
    )
    assert registry.for_adapter("cre_mcp.http.browser") is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner", "   "),
        ("dataset", ""),
        ("method", "\t"),
        ("robots_policy", ""),
        ("api_policy", " "),
    ],
)
def test_registry_rejects_blank_critical_strings(tmp_path, field, value):
    catalog = _catalog()
    catalog["sources"][0][field] = value

    with pytest.raises(SourceRightsRegistryError, match="schema is invalid"):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


def test_registry_rejects_unverified_or_non_https_evidence(tmp_path):
    catalog = _catalog()
    record = catalog["sources"][0]
    record["evidence_status"] = "approved"
    record["evidence_verified_on"] = None
    record["official_evidence_urls"] = ["http://example.test/terms"]

    with pytest.raises(SourceRightsRegistryError, match="schema is invalid"):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


def test_registry_rejects_hosted_record_marked_trusted_local_only(tmp_path):
    catalog = _catalog()
    record = catalog["sources"][0]
    record.update(
        {
            "rights_state": "CONDITIONAL",
            "hosted_cloud_allowed": True,
            "trusted_local_only": True,
            "official_evidence_urls": ["https://example.test/terms"],
            "evidence_verified_on": "2026-08-03",
            "evidence_status": "approved",
            "required_proofs": [],
        }
    )

    with pytest.raises(SourceRightsRegistryError, match="schema is invalid"):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


def test_hosted_gate_rejects_trusted_local_only_record_defense_in_depth():
    registry = SourceRightsRegistry()
    base_record = registry.get("listing.crexi")
    assert base_record is not None
    contradictory_record = base_record.model_copy(
        update={"hosted_cloud_allowed": True, "trusted_local_only": True}
    )
    mocked_registry = Mock()
    mocked_registry.for_adapter.return_value = contradictory_record
    config = CreConfig(
        _env_file=None,
        transport="http",
        source_rights_enabled={"listing.crexi": True},
    )

    with (
        patch(
            "cre_mcp.source_rights.gate.get_rights_registry",
            return_value=mocked_registry,
        ),
        pytest.raises(SourceRightsDeniedError, match="trusted-local-only"),
    ):
        require_source("crexi", config=config)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda catalog: catalog.update({"unexpected": True}), "root keys"),
        (lambda catalog: catalog.update({"schema_version": 2}), "schema version"),
        (lambda catalog: catalog["sources"].append("not-an-object"), "source entries"),
    ],
)
def test_registry_rejects_noncanonical_root_shapes(tmp_path, mutation, message):
    catalog = _catalog()
    mutation(catalog)

    with pytest.raises(SourceRightsRegistryError, match=message):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_status", "maybe"),
        ("adapter_paths", ["  "]),
        (
            "official_evidence_urls",
            ["https://evidence-user:evidence-pass@example.test/terms#private"],
        ),
    ],
)
def test_registry_rejects_boundary_values_that_are_not_machine_verifiable(
    tmp_path,
    field,
    value,
):
    catalog = _catalog()
    catalog["sources"][0][field] = value

    with pytest.raises(SourceRightsRegistryError, match="schema is invalid"):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


def test_registry_rejects_nonfinite_operating_delay(tmp_path):
    catalog = _catalog()
    catalog["sources"][0]["operating_policy"] = {"delay_seconds": float("inf")}

    with pytest.raises(SourceRightsRegistryError, match="schema is invalid"):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


def test_registry_rejects_cache_retention_without_raw_storage_rights(tmp_path):
    catalog = _catalog()
    catalog["sources"][0]["operating_policy"] = {
        "memory_cache_ttl_seconds": 60,
        "raw_retention_ttl_seconds": 60,
    }

    with pytest.raises(SourceRightsRegistryError, match="schema is invalid"):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


@pytest.mark.parametrize("source_id", ["documents.external_url", "employment.bls_ce_embedded"])
def test_non_egress_records_cannot_gain_url_authority(tmp_path, source_id):
    catalog = _catalog()
    record = next(
        item for item in catalog["sources"] if item["source_id"] == source_id
    )
    record["url_rules"] = [
        {"host": "authority-escalation.example.test", "path_prefix": "/"}
    ]

    with pytest.raises(SourceRightsRegistryError, match="schema is invalid"):
        SourceRightsRegistry(_write_catalog(tmp_path, catalog))


def test_unknown_trusted_local_host_uses_conservative_fixed_policy():
    client = FetchClient(
        config=CreConfig(
            _env_file=None,
            request_delay_seconds=0,
            max_concurrent_requests=9,
            source_rights_enabled={"unclassified.network": True},
            cache_db_path=":memory:",
        )
    )

    policy = client._policy_for_url("https://unknown-source.invalid/data")

    assert policy.delay_seconds > 0
    assert policy.max_concurrency == 1
    assert policy.cache_ttl_seconds == 0
    assert policy.persistent_cache_ttl_seconds == 0
    assert policy.persist is False
    assert client._semaphore_for(policy.host)._value == 1


@pytest.mark.parametrize("configured", [None, False])
def test_trusted_local_known_source_requires_explicit_true_toggle(configured):
    toggles = {} if configured is None else {"market.census_acs": configured}
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled=toggles,
    )

    with pytest.raises(SourceRightsDeniedError, match="explicitly enabled"):
        require_url(
            "https://api.census.gov/data/2024/acs/acs5?get=NAME",
            config=config,
        )


def test_unclassified_route_on_registered_host_cannot_use_unknown_toggle():
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"unclassified.network": True},
    )

    with pytest.raises(SourceRightsDeniedError, match="registered host"):
        require_url(
            "https://api.census.gov/not-a-registered-dataset",
            config=config,
        )


@pytest.mark.parametrize(
    ("url", "method", "toggle"),
    [
        (
            "https://api.census.gov/data/../unapproved-route",
            "GET",
            "market.census_acs",
        ),
        (
            "https://api.realestateapi.com/v2/SkipTraceEvil",
            "POST",
            "commercial.realestateapi_skiptrace",
        ),
    ],
)
def test_url_rules_reject_dot_segment_and_sibling_prefix_bypasses(
    url,
    method,
    toggle,
):
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={toggle: True},
    )
    local = TenantContext(
        workspace_id="canonical-url-rules",
        profile=Profile.FULL_OPERATOR,
        trusted=True,
    )

    with use_context(local):
        with pytest.raises(SourceRightsDeniedError, match="unclassified"):
            require_url(url, method=method, config=config)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.census.gov:444/data/2024/acs/acs5?get=NAME",
        "https://user:secret@api.census.gov/data/2024/acs/acs5?get=NAME",
    ],
)
def test_registered_url_rules_reject_unsafe_authorities(url):
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={
            "market.census_acs": True,
            "unclassified.network": True,
        },
    )

    with pytest.raises(SourceRightsDeniedError, match="invalid URL"):
        require_url(url, config=config)


def test_registered_url_rules_accept_explicit_default_port():
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"market.census_acs": True},
    )

    assert require_url(
        "https://api.census.gov:443/data/2024/acs/acs5?get=NAME",
        config=config,
    ).source_id == "market.census_acs"


def test_invalid_registry_cannot_fail_open_in_trusted_local_mode(tmp_path):
    invalid_registry = tmp_path / "invalid-source-rights.json"
    invalid_registry.write_text("{}", encoding="utf-8")
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_registry_path=invalid_registry,
        source_rights_enabled={"unclassified.network": True},
    )

    with pytest.raises(SourceRightsDeniedError, match="registry unavailable"):
        require_url("https://unknown-source.invalid/data", config=config)


def test_trusted_local_source_true_toggle_allows_registered_boundary():
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={
            "market.census_acs": True,
            "osm.overpass": True,
        },
    )

    assert require_url(
        "https://api.census.gov/data/2024/acs/acs5?get=NAME",
        config=config,
    ).source_id == "market.census_acs"
    assert require_source("overpass", config=config).source_id == "osm.overpass"


def test_browser_warmup_host_is_part_of_the_exact_source_record():
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"listing.crexi": True},
    )

    assert require_url(
        "https://www.crexi.com/",
        config=config,
    ).source_id == "listing.crexi"


def test_link_only_source_cannot_be_reclassified_as_automated_fetch():
    config = CreConfig(_env_file=None, transport="stdio")

    with pytest.raises(SourceRightsDeniedError, match="link-only"):
        require_url(
            "https://www.sec.gov/Archives/edgar/data/1/filing.txt",
            config=config,
        )


def test_link_only_source_cannot_authorize_an_adapter():
    config = CreConfig(_env_file=None, transport="stdio")

    with pytest.raises(SourceRightsDeniedError, match="link-only"):
        require_source("regulatory.sec_edgar", config=config)


def test_registry_operating_policy_overrides_legacy_host_cache_defaults():
    legacy = FetchPolicy(
        host="api.crexi.com",
        delay_seconds=0,
        max_concurrency=8,
        cache_ttl_seconds=3_600,
        persistent_cache_ttl_seconds=3_600,
        persist=True,
    )
    client = FetchClient(
        config=CreConfig(
            _env_file=None,
            transport="stdio",
            request_delay_seconds=0,
            source_rights_enabled={"listing.crexi": True},
            cache_db_path=":memory:",
        ),
        policies={legacy.host: legacy},
    )

    policy = client._policy_for_url("https://api.crexi.com/assets/search")

    assert policy.delay_seconds == 1.0
    assert policy.max_concurrency == 1
    assert policy.cache_ttl_seconds == 0
    assert policy.detail_cache_ttl_seconds == 0
    assert policy.persist is False
    assert client._semaphore_for(policy.host)._value == 1


def test_missing_context_and_runtime_proof_denies_direct_and_url_boundaries():
    with use_context(None):
        with pytest.raises(SourceRightsDeniedError, match="runtime proof"):
            require_source("overpass")
        with pytest.raises(SourceRightsDeniedError, match="runtime proof"):
            require_url("https://overpass-api.de/api/interpreter", method="POST")


def test_missing_context_sanitizes_raw_output():
    listing = Listing(
        source="crexi",
        source_id="raw-boundary",
        name="Raw boundary",
        address="1 Main St",
        city="Austin",
        state="TX",
        url="https://example.test/property?key=secret",
        raw={"native": "must-not-survive"},
    )

    from cre_mcp.source_rights.output import sanitize_listing

    with use_context(None):
        sanitized = sanitize_listing(listing)

    assert sanitized.raw == {}
    assert "secret" not in sanitized.url


@pytest.mark.asyncio
async def test_missing_context_sanitizes_raw_deal_persistence(tmp_path):
    listing = Listing(
        source="crexi",
        source_id="raw-persistence",
        name="Raw persistence",
        address="1 Main St",
        city="Austin",
        state="TX",
        url="https://example.test/property?token=secret",
        raw={"native": "must-not-persist"},
    )
    store = DealStore(tmp_path / "deals.db")

    with use_context(None):
        deal_id = await store.save_deal(listing)
    local = TenantContext(
        workspace_id="local-source-rights-persistence",
        profile=Profile.FULL_OPERATOR,
        trusted=True,
        display_name="Trusted local persistence fixture",
    )
    with use_context(local):
        stored = await store.get_deal(deal_id)
    with use_context(None):
        hosted = await store.get_deal(deal_id)

    assert stored["listing"]["raw"] == {}
    assert "secret" not in stored["listing"]["url"]
    assert "raw" not in hosted["listing"]


@pytest.mark.asyncio
async def test_hosted_legacy_deal_read_sanitizes_nested_source_payload(tmp_path):
    listing = Listing(
        source="crexi",
        source_id="legacy-raw-output",
        name="Legacy raw output",
        address="1 Main St",
        city="Austin",
        state="TX",
        url="https://example.test/property?token=legacy-secret",
        raw={"native": {"must_not_escape": True}},
    )
    store = DealStore(tmp_path / "legacy-deals.db")
    local = TenantContext(
        workspace_id="local-source-rights-output",
        profile=Profile.FULL_OPERATOR,
        trusted=True,
        display_name="Trusted local output fixture",
    )

    with use_context(local):
        deal_id = await store.save_deal(listing)
    with use_context(None):
        stored = await store.get_deal(deal_id)

    assert "raw" not in stored["listing"]
    assert "legacy-secret" not in stored["listing"]["url"]


@pytest.mark.asyncio
async def test_hosted_ranked_deal_output_recursively_strips_source_payloads():
    listing = Listing(
        source="crexi",
        source_id="nested-raw-output",
        name="Nested raw output",
        address="1 Main St",
        city="Austin",
        state="TX",
        url="https://example.test/property?api_key=ranked-secret",
        raw={"native": {"must_not_escape": True}},
    )
    aggregated = AggregatedSearchResult(
        query_location="Austin, TX",
        listings=[listing],
        per_source_counts={"crexi": 1},
    )

    with patch(
        "cre_mcp.tools.deal_tools.registry.search_all",
        new=AsyncMock(return_value=aggregated),
    ), patch(
        "cre_mcp.tools.deal_tools._market_for",
        new=AsyncMock(return_value=(None, None)),
    ), patch(
        "cre_mcp.tools.deal_tools._deal",
        side_effect=lambda item, *_args, **_kwargs: Deal(listing=item),
    ), use_context(None):
        result = await find_deals("Austin, TX", sources=["crexi"])

    returned = result["deals"][0]["listing"]
    assert "raw" not in returned
    assert "ranked-secret" not in returned["url"]


def test_hosted_output_redacts_registry_specific_query_credentials():
    payload = {
        "source": "market.bea_regional",
        "source_url": (
            "https://apps.bea.gov/api/data/?UserID=bea-secret"
            "&method=GetData&TableName=SAGDP1"
        ),
    }

    with use_context(None):
        sanitized = sanitize_payload(payload)

    assert "bea-secret" not in sanitized["source_url"]
    assert "UserID" not in sanitized["source_url"]
    assert "TableName=SAGDP1" in sanitized["source_url"]


def test_hosted_output_uses_custom_registry_credentials(tmp_path):
    catalog = _catalog()
    record = next(
        item for item in catalog["sources"] if item["source_id"] == "listing.crexi"
    )
    record["query_credentials"] = ["sig"]
    config = CreConfig(
        _env_file=None,
        source_rights_registry_path=_write_catalog(tmp_path, catalog),
    )
    payload = {
        "source": "crexi",
        "url": "https://api.crexi.com/assets/search?sig=custom-secret&size=10",
    }

    with use_context(None):
        sanitized = sanitize_payload(payload, config=config)

    assert "custom-secret" not in sanitized["url"]
    assert "sig" not in sanitized["url"]
    assert "size=10" in sanitized["url"]


def test_runtime_bound_custom_registry_reaches_output_sanitizer(tmp_path):
    catalog = _catalog()
    record = next(
        item for item in catalog["sources"] if item["source_id"] == "listing.crexi"
    )
    record["query_credentials"] = ["signature"]
    config = CreConfig(
        _env_file=None,
        source_rights_registry_path=_write_catalog(tmp_path, catalog),
    )

    with use_context(None), use_runtime_config(config):
        sanitized = sanitize_payload(
            {
                "source": "crexi",
                "url": "https://api.crexi.com/assets/search?signature=runtime-secret",
            }
        )

    assert "runtime-secret" not in sanitized["url"]


@pytest.mark.parametrize(
    ("purpose", "flag", "allowance"),
    [
        ("output", "raw_output_allowed", "redistribution"),
        ("storage", "raw_storage_allowed", "raw_retention"),
    ],
)
def test_hosted_raw_payload_honors_explicit_registry_allowance(
    tmp_path,
    purpose,
    flag,
    allowance,
):
    catalog = _catalog()
    record = next(
        item for item in catalog["sources"] if item["source_id"] == "listing.crexi"
    )
    record[flag] = True
    record.setdefault("allowances", {})[allowance] = True
    config = CreConfig(
        _env_file=None,
        source_rights_registry_path=_write_catalog(tmp_path, catalog),
    )

    with use_context(None):
        sanitized = sanitize_payload(
            {
                "source": "crexi",
                "raw": {
                    "native": "explicitly-allowed",
                    "api_key": "must-still-be-redacted",
                },
            },
            config=config,
            purpose=purpose,
        )

    assert sanitized["raw"] == {"native": "explicitly-allowed"}


def test_explicitly_allowed_raw_payload_remains_json_safe_and_secret_free(tmp_path):
    secret = "configured-raw-object-secret-902b"
    catalog = _catalog()
    record = next(
        item for item in catalog["sources"] if item["source_id"] == "listing.crexi"
    )
    record["raw_output_allowed"] = True
    record.setdefault("allowances", {})["redistribution"] = True
    config = CreConfig(
        _env_file=None,
        census_api_key=secret,
        source_rights_registry_path=_write_catalog(tmp_path, catalog),
    )

    class SecretBearingObject:
        def __repr__(self) -> str:
            return f"SecretBearingObject({secret})"

    with use_context(None):
        sanitized = sanitize_payload(
            {
                "source": "crexi",
                "url": "https://api.crexi.com/assets/1",
                "raw": {
                    "bytes": secret.encode(),
                    "set": {secret, "safe"},
                    "object": SecretBearingObject(),
                },
            },
            config=config,
        )

    serialized = json.dumps(sanitized)
    assert secret not in serialized
    assert sanitized["raw"]["object"]["type"].endswith("SecretBearingObject")


def test_hosted_output_attaches_registry_disclosures(tmp_path):
    catalog = _catalog()
    record = next(
        item for item in catalog["sources"] if item["source_id"] == "listing.crexi"
    )
    record["disclosures"] = {
        "attribution": ["Required source attribution"],
        "disclaimer": ["Required source disclaimer"],
        "delivery_proven": True,
    }
    config = CreConfig(
        _env_file=None,
        source_rights_registry_path=_write_catalog(tmp_path, catalog),
    )

    with use_context(None):
        sanitized = sanitize_payload(
            {"source": "crexi", "value": 1},
            config=config,
        )

    assert sanitized["source_rights"]["attribution"] == [
        "Required source attribution"
    ]
    assert sanitized["source_rights"]["disclaimer"] == [
        "Required source disclaimer"
    ]


def test_request_collector_preserves_disclosures_after_internal_model_loss(tmp_path):
    catalog = _catalog()
    record = next(
        item for item in catalog["sources"] if item["source_id"] == "listing.crexi"
    )
    record.update(
        {
            "rights_state": "CONDITIONAL",
            "hosted_cloud_allowed": True,
            "trusted_local_only": False,
            "official_evidence_urls": ["https://www.crexi.com/terms"],
            "evidence_verified_on": "2026-08-01",
            "evidence_status": "approved",
            "required_proofs": [],
            "disclosures": {
                "attribution": ["Required source attribution"],
                "disclaimer": ["Required source disclaimer"],
                "delivery_proven": True,
            },
        }
    )
    config = CreConfig(
        _env_file=None,
        transport="http",
        source_rights_registry_path=_write_catalog(tmp_path, catalog),
        source_rights_enabled={"listing.crexi": True},
    )
    hosted = TenantContext(
        workspace_id="disclosure-delivery",
        profile=Profile.FULL_OPERATOR,
        trusted=False,
    )

    with (
        use_context(hosted),
        use_runtime_config(config),
        collect_authorized_sources() as authorized,
    ):
        require_source("crexi")
        result = sanitize_tool_result(
            ToolResult(
                structured_content={
                    "normalized": True,
                    "raw": {"authorization": "Bearer must-not-escape"},
                }
            ),
            authorized_records=tuple(authorized.values()),
            config=config,
        )

    assert result.structured_content["normalized"] is True
    assert "raw" not in result.structured_content
    assert result.structured_content["source_rights"]["attribution"] == [
        "Required source attribution"
    ]
    assert result.structured_content["source_rights"]["disclaimer"] == [
        "Required source disclaimer"
    ]


def test_unclassified_nested_url_drops_all_query_parameters():
    secret = "unclassified-cdn-signature-77ad"
    payload = {
        "source": "crexi",
        "url": "https://api.crexi.com/assets/1",
        "image_url": (
            "https://unregistered-cdn.invalid/photo.jpg"
            f"?Signature={secret}&Expires=9999999999"
        ),
    }

    with use_context(None):
        sanitized = sanitize_payload(payload)

    assert sanitized["image_url"] == "https://unregistered-cdn.invalid/photo.jpg"
    assert secret not in json.dumps(sanitized)


def test_hosted_output_redacts_url_shaped_source_and_deal_ids():
    secret = "identifier-secret-7d6e"
    url = f"https://www.crexi.com/properties/123?api_key={secret}"
    payload = {
        "deal_id": f"crexi:{url}",
        "listing": {
            "source": "crexi",
            "source_id": url,
            "url": url,
        },
    }

    with use_context(None):
        sanitized = sanitize_payload(payload)

    assert secret not in json.dumps(sanitized)


def test_hosted_output_redacts_credential_urls_inside_collections():
    secret = "image-url-secret-5a1c"
    payload = {
        "source": "crexi",
        "images": [
            f"https://api.crexi.com/assets/photo?api_key={secret}&size=large"
        ],
    }

    with use_context(None):
        sanitized = sanitize_payload(payload)

    assert secret not in json.dumps(sanitized)
    assert "size=large" in sanitized["images"][0]


@pytest.mark.parametrize(
    ("source", "credential_name"),
    [
        ("market.bea_regional", "UserID"),
        ("crexi", "key"),
    ],
)
def test_hosted_output_inherits_source_credentials_into_nested_metadata(
    source,
    credential_name,
):
    payload = {
        "source": source,
        "request": {
            credential_name: "nested-provider-secret",
            "method": "GetData",
        },
    }

    with use_context(None):
        sanitized = sanitize_payload(payload)

    assert credential_name not in sanitized["request"]
    assert sanitized["request"]["method"] == "GetData"


def test_hosted_output_redacts_credentials_embedded_in_mapping_keys():
    secret = "mapping-key-secret-608d"
    payload = {
        "source": "market.bea_regional",
        "errors": {
            (
                "detail:market.bea_regional:"
                f"https://apps.bea.gov/api/data?UserID={secret}&method=GetData"
            ): "failed",
        },
    }

    with use_context(None):
        sanitized = sanitize_payload(payload)

    assert secret not in json.dumps(sanitized)


def test_hosted_output_redacts_custom_credentials_in_composite_references(tmp_path):
    catalog = _catalog()
    record = next(
        item for item in catalog["sources"] if item["source_id"] == "listing.crexi"
    )
    record["query_credentials"] = ["sig"]
    config = CreConfig(
        _env_file=None,
        source_rights_registry_path=_write_catalog(tmp_path, catalog),
    )
    secret = "composite-reference-secret-73c4"
    payload = {
        "source": "crexi",
        "source_id": (
            "crexi:https://api.crexi.com/assets/1"
            f"?sig={secret}&view=full"
        ),
        "error": f"provider rejected sig={secret}",
    }

    with use_context(None):
        sanitized = sanitize_payload(payload, config=config)

    assert secret not in json.dumps(sanitized)
    assert "view=full" in sanitized["source_id"]


@pytest.mark.asyncio
async def test_registry_keeps_transient_raw_for_internal_derivation():
    listing = Listing(
        source="loopnet",
        source_id="internal-raw",
        name="Internal derivation",
        address="1 Main St",
        city="Austin",
        state="TX",
        url="https://www.loopnet.com/Listing/internal-raw/",
        raw={"loopnet_search": {"total_results": 57, "has_next_page": True}},
    )
    source = Mock(name="loopnet-source")
    source.name = "loopnet"
    source.search = AsyncMock(return_value=[listing])
    registry = SourceRegistry(
        config=CreConfig(_env_file=None),
        sources=[source],
    )

    with patch("cre_mcp.sources.registry.require_source"), use_context(None):
        result = await registry.search_all(SearchQuery(location="Austin, TX"))

    assert result.listings[0].raw["loopnet_search"]["total_results"] == 57


@pytest.mark.asyncio
async def test_listing_tool_never_logs_or_returns_url_credentials(caplog):
    secret = "listing-tool-secret-4f3a"
    source = Mock()
    source.get_detail = AsyncMock(
        side_effect=SourceError("crexi", "fixture detail failure")
    )
    caplog.set_level("INFO")

    with patch(
        "cre_mcp.tools.listing_tools.registry.get_authorized",
        return_value=source,
    ), use_context(None):
        result = await get_property_details(
            f"https://www.crexi.com/properties/123?api_key={secret}"
        )

    assert secret not in caplog.text
    assert secret not in json.dumps(result)


@pytest.mark.asyncio
async def test_listing_search_error_never_logs_or_returns_url_credentials(caplog):
    secret = "listing-search-secret-e4c9"
    error = (
        "provider failure at "
        f"https://www.loopnet.com/search?api_key={secret}"
    )
    aggregated = AggregatedSearchResult(
        query_location="Austin, TX",
        listings=[],
        errors={"loopnet": error},
    )
    caplog.set_level("ERROR")

    with patch(
        "cre_mcp.tools.listing_tools.registry.search_all",
        new=AsyncMock(return_value=aggregated),
    ), use_context(None):
        result = await search_properties("Austin, TX")

    assert secret not in caplog.text
    assert secret not in json.dumps(result)


@pytest.mark.asyncio
async def test_listing_search_input_never_logs_url_credentials(caplog):
    secret = "listing-input-secret-52fa"
    location = f"https://api.mapbox.com/geocoding/v5/x?access_token={secret}"
    aggregated = AggregatedSearchResult(
        query_location=location,
        listings=[],
    )
    caplog.set_level("INFO")

    with patch(
        "cre_mcp.tools.listing_tools.registry.search_all",
        new=AsyncMock(return_value=aggregated),
    ), use_context(None):
        result = await search_properties(location)

    assert secret not in caplog.text
    assert secret not in json.dumps(result)


@pytest.mark.asyncio
async def test_deal_tool_never_logs_url_credentials(caplog):
    secret = "deal-tool-secret-9c2d"
    caplog.set_level("INFO")

    with patch(
        "cre_mcp.tools.deal_tools.registry.get_authorized",
        side_effect=ValueError("fixture source failure"),
    ), use_context(None):
        result = await analyze_deal(
            f"https://www.crexi.com/properties/123?api_key={secret}",
            source="crexi",
        )

    assert secret not in caplog.text
    assert secret not in json.dumps(result)


@pytest.mark.asyncio
async def test_deal_store_failure_log_never_exposes_url_credentials(tmp_path, caplog):
    secret = "deal-store-secret-71bf"
    url = f"https://www.crexi.com/properties/123?api_key={secret}"
    listing = Listing(
        source="crexi",
        source_id=url,
        name="Store failure boundary",
        address="1 Main St",
        city="Austin",
        state="TX",
        url=url,
    )
    store = DealStore(tmp_path / "failure-log.db")
    store._save_deal = Mock(
        side_effect=RuntimeError(f"fixture failed while handling {url}")
    )
    caplog.set_level("ERROR")

    with use_context(None):
        assert await store.save_deal(listing) is None

    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_deal_store_uses_custom_registry_for_failure_logs(tmp_path, caplog):
    catalog = _catalog()
    record = next(
        item for item in catalog["sources"] if item["source_id"] == "listing.crexi"
    )
    record["query_credentials"] = ["sig"]
    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "custom-log.db",
        source_rights_registry_path=_write_catalog(tmp_path, catalog),
    )
    secret = "custom-store-log-secret-a318"
    url = f"https://api.crexi.com/assets/1?sig={secret}"
    listing = Listing(
        source="crexi",
        source_id=f"crexi:{url}",
        name="Custom store failure",
        address="1 Main St",
        city="Austin",
        state="TX",
        url=url,
    )
    store = DealStore(config=config)
    store._save_deal = Mock(
        side_effect=RuntimeError(f"provider rejected sig={secret}")
    )
    caplog.set_level("ERROR")

    with use_context(None):
        assert await store.save_deal(listing) is None

    assert secret not in caplog.text


def test_exported_store_factories_preserve_runtime_bound_config(tmp_path):
    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "runtime-bound.db",
    )

    with use_runtime_config(config):
        deal_store = get_deal_store()
        platform_repository = get_platform_repository()

    assert deal_store._config is config
    assert platform_repository._config is config


def test_shared_http_factories_preserve_runtime_bound_config(tmp_path):
    stale = CreConfig(_env_file=None, cache_db_path=tmp_path / "stale.db")
    runtime = CreConfig(_env_file=None, cache_db_path=tmp_path / "runtime.db")

    with patch("cre_mcp.http.fetch._singleton", FetchClient(stale)), patch(
        "cre_mcp.scraper.client._singleton",
        LoopnetClient(stale),
    ), use_runtime_config(runtime):
        shared = get_fetch_client()
        loopnet = get_client()

    assert shared._config is runtime
    assert loopnet._config is runtime


def test_skiptrace_provider_prefers_server_runtime_credentials(tmp_path):
    stale = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "stale-skiptrace.db",
        skiptrace_api_key="stale-skiptrace-secret",
    )
    runtime = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "runtime-skiptrace.db",
        skiptrace_api_key="runtime-skiptrace-secret",
    )

    with use_runtime_config(runtime):
        provider = RealEstateApiSkiptraceProvider(stale)

    assert provider.config is runtime
    assert (
        provider.config.skiptrace_api_key.get_secret_value()
        == "runtime-skiptrace-secret"
    )


def test_long_lived_tool_services_rebind_to_each_runtime_config(tmp_path):
    first = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "first-services.db",
        census_api_key="first-census-secret",
        rentcast_api_key="first-rentcast-secret",
        attom_api_key="first-attom-secret",
    )
    second = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "second-services.db",
        census_api_key="second-census-secret",
        rentcast_api_key="second-rentcast-secret",
        attom_api_key="second-attom-secret",
    )

    with patch.object(market_tools_module, "_intel", None), patch.object(
        market_tools_module, "_rent_comps", None
    ), patch.object(market_tools_module, "_owner_lookup", None), patch.object(
        deal_tools_module, "_market_intel", None
    ), patch.object(deal_tools_module, "_rent_comps", None), patch.object(
        deal_tools_module, "_owner_lookup", None
    ), patch.object(owner_tools_module, "_lookup", None):
        with use_runtime_config(first):
            first_instances = (
                market_tools_module._engine(),
                market_tools_module._rent_engine(),
                market_tools_module._owner_engine(),
                deal_tools_module._market_engine(),
                deal_tools_module._rent_engine(),
                deal_tools_module._owner_engine(),
                owner_tools_module._engine(),
            )
        with use_runtime_config(second):
            second_instances = (
                market_tools_module._engine(),
                market_tools_module._rent_engine(),
                market_tools_module._owner_engine(),
                deal_tools_module._market_engine(),
                deal_tools_module._rent_engine(),
                deal_tools_module._owner_engine(),
                owner_tools_module._engine(),
            )

    assert all(
        before is not after
        for before, after in zip(first_instances, second_instances, strict=True)
    )
    assert all(instance.config is second for instance in second_instances)
    assert (
        second_instances[0].census.client.auth.secret_value()
        == "second-census-secret"
    )
    assert second_instances[1].rentcast._key == "second-rentcast-secret"
    assert (
        second_instances[2].config.attom_api_key.get_secret_value()
        == "second-attom-secret"
    )


@pytest.mark.asyncio
async def test_module_geo_resolver_rebinds_to_each_runtime_config(tmp_path):
    first = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "first-geo.db",
        hud_api_token="first-hud-secret",
    )
    second = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "second-geo.db",
        hud_api_token="second-hud-secret",
    )
    first_resolver = Mock()
    first_resolver.resolve = AsyncMock(return_value="first")
    second_resolver = Mock()
    second_resolver.resolve = AsyncMock(return_value="second")

    with patch.object(geo_resolver_module, "_resolver", None), patch.object(
        geo_resolver_module,
        "GeoResolver",
        side_effect=(first_resolver, second_resolver),
    ) as resolver_factory:
        with use_runtime_config(first):
            assert await geo_resolver_module.resolve("Austin, TX") == "first"
        with use_runtime_config(second):
            assert await geo_resolver_module.resolve("Austin, TX") == "second"

    assert resolver_factory.call_args_list == [
        call(first),
        call(second),
    ]


def _cache_boundary_context() -> TenantContext:
    return TenantContext(
        workspace_id="source-cache-boundary",
        profile=Profile.FULL_OPERATOR,
        trusted=True,
    )


@pytest.mark.asyncio
async def test_census_geo_cache_cannot_bypass_runtime_rights_gate(tmp_path):
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=tmp_path / "geo-cache.db",
        source_rights_enabled={"market.census_geocoder": False},
    )
    cache = SQLiteCache(config.cache_db_path)
    location = "1 Main St, Unmapped, TX"
    cached_geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name=location,
    )
    await cache.set(
        f"geo:v1:{location.casefold()}",
        cached_geo.model_dump(mode="json"),
        ttl_seconds=3600,
    )
    resolver = GeoResolver(config, cache=cache)

    with use_context(_cache_boundary_context()), use_runtime_config(config):
        with pytest.raises(SourceRightsDeniedError):
            await resolver.resolve(location)


@pytest.mark.asyncio
async def test_hud_crosswalk_cache_cannot_bypass_runtime_rights_gate(tmp_path):
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=tmp_path / "crosswalk-cache.db",
        hud_api_token="configured-hud-token",
        source_rights_enabled={"geo.hud_usps_crosswalk": False},
    )
    crosswalk = GeoCrosswalk(config, hud_token="configured-hud-token")
    crosswalk._store(
        "xwalk_zip_county",
        "county_fips",
        "99999",
        [("48453", 1.0)],
    )

    with use_context(_cache_boundary_context()), use_runtime_config(config):
        with pytest.raises(SourceRightsDeniedError):
            await crosswalk.zip_to_county("99999")


@pytest.mark.asyncio
async def test_owner_cache_cannot_bypass_county_runtime_rights_gate(tmp_path):
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=tmp_path / "owner-cache.db",
        source_rights_enabled={"parcel.guilford_37081": False},
    )
    cache = SQLiteCache(config.cache_db_path)
    lookup = OwnerLookup(config, cache=cache)
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="37",
        county_fips="37081",
        name="Guilford County, NC",
    )
    address = "100 Main St, Greensboro, NC"
    cache_key = lookup._cache_key(address, None, "37081", "free")
    owner = OwnerRecord(
        name="Cached Owner LLC",
        normalized_name="CACHED OWNER LLC",
        entity_type="llc",
    )
    await cache.set(cache_key, owner.model_dump(mode="json"), ttl_seconds=3600)

    with use_context(_cache_boundary_context()), use_runtime_config(config):
        with pytest.raises(SourceRightsDeniedError):
            await lookup.lookup(address=address, geo=geo)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", [AttomProvider, RegridProvider])
async def test_paid_provider_cache_cannot_bypass_runtime_rights_gate(
    tmp_path,
    provider_type,
):
    source_id = (
        "commercial.attom" if provider_type is AttomProvider else "commercial.regrid"
    )
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=tmp_path / f"{provider_type.__name__}.db",
        attom_api_key="configured-attom-key",
        regrid_api_key="configured-regrid-key",
        source_rights_enabled={source_id: False},
    )
    cache = SQLiteCache(config.cache_db_path)
    provider = provider_type(config, cache=cache)
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name="Travis County, TX",
    )
    address = "100 Main St, Austin, TX"
    cache_key = (
        provider._cache_key("parcel", address, None, geo.county_fips)
        if provider_type is AttomProvider
        else provider._cache_key(address, None, geo.county_fips)
    )
    await cache.set(cache_key, {"missing": True}, ttl_seconds=3600)

    with use_context(_cache_boundary_context()), use_runtime_config(config):
        with pytest.raises(SourceRightsDeniedError):
            await provider.lookup(address, None, geo)


@pytest.mark.asyncio
async def test_traffic_cache_cannot_bypass_runtime_rights_gate(tmp_path):
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=tmp_path / "traffic-cache.db",
        source_rights_enabled={"traffic.txdot": False},
    )
    cache = SQLiteCache(config.cache_db_path)
    provider = TrafficProvider("TX", cache=cache, config=config)
    lat, lon, radius = 30.2182, -97.6833, 250
    cache_key = f"traffic:v1:TX:{lat:.5f}:{lon:.5f}:{radius}"
    await cache.set(
        cache_key,
        {
            "found": True,
            "metric": {
                "value": 42_000,
                "unit": "vehicles/day",
                "source": "TX DOT AADT",
            },
        },
        ttl_seconds=3600,
    )

    with use_context(_cache_boundary_context()), use_runtime_config(config):
        with pytest.raises(SourceRightsDeniedError):
            await provider.nearest_aadt(lat, lon, radius_m=radius)


@pytest.mark.asyncio
async def test_irs_soi_normalized_cache_cannot_bypass_runtime_rights_gate(tmp_path):
    db_path = tmp_path / "irs-soi-cache.db"
    provider = IrsSoiProvider(
        config=CreConfig(_env_file=None, transport="stdio", cache_db_path=db_path),
        db_path=db_path,
    )
    provider._load_csv(
        "county_fips,year,inflow_returns,outflow_returns,inflow_exemptions,"
        "outflow_exemptions,inflow_agi,outflow_agi\n"
        "48453,2022-2023,100,80,220,175,5000,4200\n",
        None,
        None,
        True,
    )
    denied = CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=db_path,
        source_rights_enabled={"market.irs_soi_migration": False},
    )

    with use_context(_cache_boundary_context()), use_runtime_config(denied):
        with pytest.raises(SourceRightsDeniedError):
            await provider.net_migration("48453")


def test_zero_registry_memory_ttl_disables_nearby_source_cache():
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"osm.overpass": True},
    )
    response = Mock(status_code=200)
    response.json.return_value = {
        "elements": [
            {
                "id": 1,
                "lat": 30.2183,
                "lon": -97.6832,
                "tags": {"brand": "Fixture Market", "shop": "supermarket"},
            }
        ]
    }

    with patch.object(nearby_module, "_CACHE", {}), patch.object(
        nearby_module.requests,
        "post",
        return_value=response,
    ) as post, use_context(_cache_boundary_context()), use_runtime_config(config):
        first = nearby_module.nearby_brands(30.2182, -97.6833)
        second = nearby_module.nearby_brands(30.2182, -97.6833)

    assert first == second
    assert post.call_count == 2


def test_long_lived_fetch_client_delegates_cache_boundary_to_runtime_config(tmp_path):
    runtime_secret = "runtime-cache-secret-174c"
    stale = FetchClient(
        CreConfig(
            _env_file=None,
            cache_db_path=tmp_path / "stale-client.db",
            source_rights_enabled={"market.census_acs": True},
        )
    )
    runtime = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "runtime-client.db",
        census_api_key=runtime_secret,
        source_rights_enabled={"market.census_acs": True},
    )
    local = TenantContext(
        workspace_id="runtime-config-cache",
        profile=Profile.FULL_OPERATOR,
        trusted=True,
    )
    url = (
        "https://api.census.gov/data/2024/acs/acs5"
        f"?customer_ref={runtime_secret}&get=NAME"
    )

    with patch("cre_mcp.http.fetch._singleton", None), use_context(
        local
    ), use_runtime_config(runtime):
        delegate = stale._runtime_bound_client()
        policy = stale._policy_for_url(url)
        key = stale._cache_key(policy, "GET", url)

    assert delegate._config is runtime
    assert runtime_secret not in key


def test_fetch_cache_key_partitions_current_rights_retention_policy():
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=":memory:",
        source_rights_enabled={"unclassified.network": True},
    )
    client = FetchClient(config=config)
    url = "https://policy-partition.invalid/data"
    long_policy = FetchPolicy(
        host="policy-partition.invalid",
        cache_namespace="policy-partition",
        cache_ttl_seconds=86_400,
        persistent_cache_ttl_seconds=86_400,
        persist=True,
    )
    tightened_policy = FetchPolicy(
        host="policy-partition.invalid",
        cache_namespace="policy-partition",
        cache_ttl_seconds=60,
        persistent_cache_ttl_seconds=60,
        persist=True,
    )

    with use_context(_cache_boundary_context()), use_runtime_config(config):
        long_key = client._cache_key(long_policy, "GET", url)
        tightened_key = client._cache_key(tightened_policy, "GET", url)

    assert long_key != tightened_key


def test_runtime_config_overrides_stale_explicit_gate_config():
    stale = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"market.census_acs": True},
    )
    runtime = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"market.census_acs": False},
    )
    local = TenantContext(
        workspace_id="runtime-config-gate",
        profile=Profile.FULL_OPERATOR,
        trusted=True,
    )

    with use_context(local), use_runtime_config(runtime):
        with pytest.raises(SourceRightsDeniedError, match="explicitly enabled"):
            require_url(
                "https://api.census.gov/data/2024/acs/acs5?get=NAME",
                config=stale,
            )


def test_source_registry_authorized_detail_uses_runtime_source_toggle():
    registry = SourceRegistry(
        config=CreConfig(
            _env_file=None,
            transport="stdio",
            sources={"crexi": {"enabled": False}},
        )
    )
    runtime = CreConfig(
        _env_file=None,
        transport="stdio",
        sources={"crexi": {"enabled": True}},
        source_rights_enabled={"listing.crexi": True},
    )
    local = TenantContext(
        workspace_id="runtime-config-source-registry",
        profile=Profile.FULL_OPERATOR,
        trusted=True,
    )

    with use_context(local), use_runtime_config(runtime):
        source = registry.get_authorized("crexi")

    assert source.name == "crexi"


def test_safe_error_message_redacts_non_url_credential_diagnostics():
    message = (
        "Authorization: Bearer header-secret; "
        "api_key=query-secret; client_secret=client-secret"
    )

    sanitized = safe_error_message(message)

    for secret in ("header-secret", "query-secret", "client-secret"):
        assert secret not in sanitized


def test_safe_error_message_redacts_configured_secret_outside_url():
    secret = "configured-diagnostic-secret"
    config = CreConfig(_env_file=None, census_api_key=secret)

    sanitized = safe_error_message(
        f"provider rejected opaque customer reference {secret}",
        config=config,
    )

    assert secret not in sanitized


@pytest.mark.asyncio
async def test_control_tool_error_redacts_credential_diagnostics():
    secret = "control-error-secret-1ad7"

    with use_context(None):
        result = await find_control_opportunities(
            [{"Authorization": f"Bearer {secret}"}]
        )

    assert secret not in json.dumps(result)


def test_hosted_snapshot_persistence_and_output_strip_source_raw(tmp_path):
    secret = "snapshot-secret-2d41"
    store = SnapshotStore(tmp_path / "snapshots.db")
    listing = {
        "source": "crexi",
        "source_id": "snapshot-1",
        "url": f"https://api.crexi.com/assets/1?api_key={secret}&view=full",
        "raw": {"native": "must-not-persist"},
        "price_usd": 1_250_000,
    }

    with use_context(None):
        recorded = store.record_snapshot(listing)
        listed = store.list_snapshots("crexi:snapshot-1")

    with sqlite3.connect(store.db_path) as connection:
        persisted = connection.execute(
            "SELECT raw_json FROM listing_snapshots"
        ).fetchone()[0]

    assert "raw" not in recorded
    assert "raw" not in listed[0]
    assert "must-not-persist" not in persisted
    assert secret not in persisted
    assert "view=full" in persisted


@pytest.mark.asyncio
async def test_hosted_platform_deal_persistence_and_output_strip_source_raw(tmp_path):
    secret = "platform-deal-secret-8a13"
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace = await repository.create_workspace("Source Rights Platform")
    assert workspace is not None
    payload = {
        "listing": {
            "source": "crexi",
            "source_id": "platform-1",
            "url": f"https://api.crexi.com/assets/1?api_key={secret}&view=full",
            "raw": {"native": "must-not-persist"},
        }
    }

    with use_context(None):
        saved = await repository.save_deal(
            workspace.id,
            "crexi:platform-1",
            "Platform source boundary",
            payload=payload,
        )
        listed = await repository.list_saved_deals(workspace.id)

    assert saved is not None
    with sqlite3.connect(repository.db_path) as connection:
        persisted = connection.execute(
            "SELECT payload FROM platform_saved_deals WHERE id = ?",
            (saved.id,),
        ).fetchone()[0]

    assert "raw" not in saved.payload["listing"]
    assert "raw" not in listed[0].payload["listing"]
    assert "must-not-persist" not in persisted
    assert secret not in persisted
    assert "view=full" in persisted


@pytest.mark.asyncio
async def test_hosted_deal_event_persistence_strips_nested_source_payload(tmp_path):
    listing = Listing(
        source="crexi",
        source_id="event-raw-persistence",
        name="Event raw persistence",
        address="1 Main St",
        city="Austin",
        state="TX",
        url="https://example.test/property",
    )
    store = DealStore(tmp_path / "event-deals.db")
    local = TenantContext(
        workspace_id="local-source-rights-event",
        profile=Profile.FULL_OPERATOR,
        trusted=True,
        display_name="Trusted local event fixture",
    )

    with use_context(local):
        deal_id = await store.save_deal(listing)
    with use_context(None):
        await store.log_deal_event(
            deal_id,
            "listing_refresh",
            {"listing": {"raw": {"native": "must-not-persist"}}},
        )
    with use_context(local):
        timeline = await store.get_deal_timeline(deal_id)

    assert "raw" not in timeline["events"][0]["detail"]["listing"]


@pytest.mark.asyncio
async def test_threaded_document_fetch_preserves_hosted_context():
    context = TenantContext(
        workspace_id="ws-thread",
        profile=Profile.FULL_OPERATOR,
        trusted=False,
        actor_id="actor-thread",
        session_id="session-thread",
    )

    def observe_context(url, attestation_id):
        active = current_context()
        assert active is not None
        assert active.workspace_id == context.workspace_id
        assert attestation_id == "srcatt_fixture"
        return b"ok"

    with patch("cre_mcp.tools.truth_tools._fetch_bytes", side_effect=observe_context):
        with use_context(context):
            result = await _to_thread_fetch(
                "https://documents.example/report.pdf",
                "srcatt_fixture",
            )

    assert result == b"ok"


@pytest.mark.asyncio
async def test_request_exception_never_exposes_or_chains_source_secret():
    secret = "request-secret-8cc1"
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        census_api_key=secret,
        cache_db_path=":memory:",
        source_rights_enabled={"market.census_acs": True},
    )
    policy = FetchPolicy(
        host="api.census.gov",
        max_retries=1,
        cache_ttl_seconds=0,
    )
    client = FetchClient(config=config, policies={policy.host: policy})
    session = Mock()
    session.get = AsyncMock(
        side_effect=RequestsError(
            f"transport failed at https://api.census.gov/data?opaque={secret}"
        )
    )
    client._get_client = Mock(return_value=session)

    with pytest.raises(FetchClientError) as captured:
        await client.get_text(
            f"https://api.census.gov/data/2024/acs/acs5?customer_ref={secret}"
        )

    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.asyncio
async def test_http_redirect_is_not_followed_in_trusted_local_mode():
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=":memory:",
        source_rights_enabled={"market.census_acs": True},
    )
    policy = FetchPolicy(
        host="api.census.gov",
        max_retries=1,
        cache_ttl_seconds=0,
    )
    client = FetchClient(config=config, policies={policy.host: policy})
    session = Mock()
    session.get = AsyncMock(return_value=Mock(status_code=302, text=""))
    client._get_client = Mock(return_value=session)

    with pytest.raises(FetchClientError, match="Unexpected status 302"):
        await client.get_text(
            "https://api.census.gov/data/2024/acs/acs5?get=NAME"
        )

    session.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_json_error_redacts_configured_secret_value():
    secret = "json-secret-bc20"
    client = FetchClient(
        config=CreConfig(
            _env_file=None,
            census_api_key=secret,
            cache_db_path=":memory:",
            source_rights_enabled={"market.census_acs": True},
        )
    )
    client._request_text = AsyncMock(return_value="not-json")

    with pytest.raises(FetchClientError) as captured:
        await client.get_json(
            f"https://api.census.gov/data?customer_ref={secret}"
        )

    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None


def test_error_redaction_uses_registry_specific_credential_names():
    secret = "registry-specific-user-id-12d8"
    client = FetchClient(
        config=CreConfig(
            _env_file=None,
            transport="stdio",
            source_rights_enabled={"market.bea_regional": True},
            cache_db_path=":memory:",
        )
    )
    url = f"https://apps.bea.gov/api/data/?UserID={secret}&method=GetData"

    with pytest.raises(FetchClientError) as captured:
        client._decode_json("not-json", url)

    assert secret not in str(captured.value)
    assert "UserID" not in str(captured.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@[::1/data",
        "https://user:secret@example.test:invalid/data",
    ],
)
def test_malformed_url_diagnostics_do_not_leak_userinfo(url):
    client = FetchClient(config=CreConfig(_env_file=None, cache_db_path=":memory:"))

    with pytest.raises(FetchClientError) as captured:
        client._policy_for_url(url)

    assert "user" not in str(captured.value)
    assert "secret" not in str(captured.value)


def test_loopnet_compatibility_cache_key_cannot_bypass_secret_redaction():
    secret = "compat-secret-5c9d"
    client = LoopnetClient(
        config=CreConfig(
            _env_file=None,
            stripe_webhook_secret=secret,
            cache_db_path=":memory:",
            source_rights_enabled={"listing.loopnet": True},
        )
    )
    url = (
        "https://www.loopnet.com/search"
        f"?customer_ref={secret}&key=query-secret#private"
    )
    policy = client._policy_for_url(url)

    cache_key = client._cache_key(policy, "GET", url)

    for forbidden in (
        secret,
        "query-secret",
        "private",
    ):
        assert forbidden not in cache_key


@pytest.mark.asyncio
async def test_loopnet_browser_exception_is_generic_and_unchained():
    secret = "browser-secret-c31f"
    client = LoopnetClient(
        config=CreConfig(
            _env_file=None,
            browser_enabled=True,
            cache_db_path=":memory:",
            source_rights_enabled={"listing.loopnet": True},
        )
    )
    browser = AsyncMock()
    browser.fetch.side_effect = BrowserFetchError(
        f"browser failed with cookie={secret}"
    )
    client._browser_fetcher = browser
    url = "https://www.loopnet.com/search"
    policy = client._policy_for_url(url)

    with pytest.raises(FetchClientError) as captured:
        await client._fetch_with_browser(url, policy)

    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.asyncio
async def test_shared_browser_warmup_log_never_exposes_url_credentials(caplog):
    secret = "browser-warmup-secret-7ac4"
    browser = AsyncMock()
    guard_tab = Mock()
    guard_tab.add_handler = Mock()
    guard_tab.send = AsyncMock()
    browser.tabs = [guard_tab]
    browser.get.side_effect = RuntimeError(f"navigation failed with {secret}")
    fetcher = SharedBrowserFetcher(
        CreConfig(
            _env_file=None,
            transport="stdio",
            source_rights_enabled={"unclassified.network": True},
        )
    )
    fetcher._browser = browser

    await fetcher._warmup(f"https://example.test/?token={secret}")

    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_shared_browser_invalid_result_has_no_secret_bearing_cause():
    secret = "browser-result-secret-f4d3"
    page = AsyncMock()
    page.evaluate.return_value = f"not-json-{secret}"
    page.close = AsyncMock()
    page.add_handler = Mock()
    page.send = AsyncMock()
    browser = AsyncMock()
    browser.tabs = [page]
    browser.get.return_value = page
    fetcher = SharedBrowserFetcher(
        CreConfig(
            _env_file=None,
            transport="stdio",
            source_rights_enabled={"listing.crexi": True},
        )
    )
    fetcher._browser = browser

    with pytest.raises(BrowserFetchError) as captured:
        await fetcher.fetch_api(
            "https://api.crexi.com/assets/search",
            method="POST",
        )

    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.asyncio
async def test_shared_browser_fetch_gates_before_browser_launch():
    fetcher = SharedBrowserFetcher(
        CreConfig(
            _env_file=None,
            transport="http",
            source_rights_enabled={"listing.loopnet": True},
        )
    )
    fetcher._ensure_browser = AsyncMock()

    with pytest.raises(BrowserFetchError, match="source-rights denied"):
        await fetcher.fetch("https://www.loopnet.com/search")

    fetcher._ensure_browser.assert_not_called()


@pytest.mark.asyncio
async def test_loopnet_browser_fetch_gates_before_browser_attempt():
    fetcher = LoopnetBrowserFetcher(
        CreConfig(
            _env_file=None,
            transport="http",
            source_rights_enabled={"listing.loopnet": True},
        )
    )
    fetcher._fetch_once = AsyncMock(return_value="must-not-fetch")

    with pytest.raises(BrowserFetchError, match="source-rights denied"):
        await fetcher.fetch("https://www.loopnet.com/search")

    fetcher._fetch_once.assert_not_called()


def test_cache_key_removes_configured_secret_from_url_headers_and_body():
    secret = "tenant-specific-value-7b2b"
    client = FetchClient(
        config=CreConfig(
            _env_file=None,
            census_api_key=secret,
            cache_db_path=":memory:",
            source_rights_enabled={"market.census_acs": True},
        )
    )
    url = (
        "https://api.census.gov/data/2024/acs/acs5"
        f"?customer_ref={secret}&get=NAME"
    )
    policy = client._policy_for_url(url)

    key = client._cache_key(
        policy,
        "GET",
        url,
        body={"opaque": secret, "safe": "value"},
        headers={"X-Tenant-Ref": secret, "Accept": "application/json"},
    )

    assert secret not in key
    assert "X-Tenant-Ref" not in key
    assert key != client._cache_key(
        policy,
        "GET",
        url,
        body={"opaque": secret, "safe": "value"},
        headers={"X-Tenant-Ref": secret, "Accept": "text/plain"},
    )


def test_redacted_cache_keys_still_partition_distinct_credentials():
    client = FetchClient(
        config=CreConfig(
            _env_file=None,
            cache_db_path=":memory:",
            source_rights_enabled={"market.census_acs": True},
        )
    )
    first_url = "https://api.census.gov/data/2024/acs/acs5?get=NAME&key=alpha"
    second_url = "https://api.census.gov/data/2024/acs/acs5?get=NAME&key=beta"
    policy = client._policy_for_url(first_url)

    first = client._cache_key(policy, "GET", first_url)
    second = client._cache_key(policy, "GET", second_url)

    assert first != second
    assert "alpha" not in first
    assert "beta" not in second
