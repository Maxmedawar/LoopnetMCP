"""Honesty, source priority, link-out, and plain-tool tests."""

from unittest.mock import AsyncMock

import pytest

from cre_mcp.verifyreg import registry
from cre_mcp.verifyreg import tools as verify_tools


@pytest.mark.asyncio
async def test_no_match_is_not_reported_as_unlicensed(monkeypatch):
    monkeypatch.setattr(registry, "search_brokercheck_individuals", AsyncMock(return_value=[]))
    monkeypatch.setattr(registry, "search_brokercheck_firms", AsyncMock(return_value=[]))

    result = await registry.verify_counterparty(
        "A Name Variant", "NY", roles=["broker_dealer"]
    )

    assert result["sources"]["finra_brokercheck_individual"]["status"] == "no_match"
    assert "does not mean unlicensed" in result["no_match_caveat"]
    assert "spelling" in result["no_match_caveat"]
    assert result["identity_caveat"]["candidate_matches_only"] is True
    assert result["identity_caveat"]["same_name_collisions_possible"] is True


@pytest.mark.asyncio
async def test_undocumented_source_failure_stays_error_not_no_match(monkeypatch):
    monkeypatch.setattr(
        registry,
        "search_brokercheck_individuals",
        AsyncMock(side_effect=RuntimeError("schema drift")),
    )
    monkeypatch.setattr(registry, "search_brokercheck_firms", AsyncMock(return_value=[]))

    result = await registry.verify_counterparty("Smith", roles=["broker_dealer"])

    source = result["sources"]["finra_brokercheck_individual"]
    assert source["status"] == "error"
    assert "failed closed" in source["note"].lower()
    assert "undocumented" in source["fragility_note"].lower()


def test_nmls_detail_deep_links_require_an_id_and_support_entity_type():
    assert registry.nmls_deep_link("NMLS ID 123456") == (
        "https://www.nmlsconsumeraccess.org/EntityDetails.aspx/INDIVIDUAL/123456"
    )
    assert registry.nmls_deep_link("987654", "company").endswith("/COMPANY/987654")
    assert registry.nmls_deep_link("Jane Smith") == "https://www.nmlsconsumeraccess.org/"


@pytest.mark.asyncio
async def test_mlo_is_explicitly_nmls_link_out_only():
    result = await registry.verify_counterparty("NMLS 123456", "CA", roles=["mlo"])

    source = result["sources"]["nmls_consumer_access"]
    assert source["status"] == "not_queryable"
    assert source["deep_link"].endswith("/INDIVIDUAL/123456")
    assert "no free public api" in source["note"].lower()
    assert "scraping" in source["note"].lower()
    assert "paid" in source["note"].lower()


@pytest.mark.asyncio
async def test_appraiser_is_explicit_asc_link_out():
    result = await registry.verify_counterparty("Jane Smith", "CO", roles=["appraiser"])

    source = result["sources"]["asc_national_registry"]
    assert source["status"] == "not_queryable"
    assert source["deep_link"] == "https://www.asc.gov/appraiser/advanced"
    assert "not an official rest/json api" in source["note"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "role", "source_name", "url_part"),
    [
        ("GA", "real_estate", "ga_grec", "grec.state.ga.us"),
        ("NC", "real_estate", "nc_ncrec", "ncrec.gov"),
        ("GA", "contractor", "ga_contractors", "verify.sos.ga.gov"),
        ("NC", "contractor", "nc_contractors", "nclbgc.org"),
    ],
)
async def test_ga_nc_web_only_sources_are_honest_link_outs(
    state, role, source_name, url_part
):
    result = await registry.verify_counterparty("Jane Smith", state, roles=[role])

    source = result["sources"][source_name]
    assert source["status"] == "not_queryable"
    assert url_part in source["deep_link"]
    assert "web" in source["note"].lower()


@pytest.mark.asyncio
async def test_texas_real_estate_uses_trec_lookup_and_doc_pointer():
    result = await registry.verify_counterparty("Jane Smith", "TX", roles=["real_estate"])

    source = result["sources"]["tx_trec"]
    assert source["status"] == "not_queryable"
    assert "license-holder-search" in source["deep_link"]
    assert "high-value-data-sets" in source["documentation_url"]


@pytest.mark.asyncio
async def test_disclosure_flag_is_summarized_without_inventing_count(monkeypatch):
    monkeypatch.setattr(
        registry,
        "search_brokercheck_individuals",
        AsyncMock(
            return_value=[
                {
                    "crd": "2796112",
                    "name": "JOHN WESLEY SMITH",
                    "firm": "CAPITAL ONE SECURITIES, INC.",
                    "exams": [],
                    "states": [],
                    "disclosure_count": None,
                    "disclosure_flag": "Y",
                    "bc_url": "https://example.invalid/profile",
                }
            ]
        ),
    )
    monkeypatch.setattr(registry, "search_brokercheck_firms", AsyncMock(return_value=[]))

    result = await registry.verify_counterparty("John Smith", roles=["broker_dealer"])

    flag = result["disciplinary_summary"]["flags"][0]
    assert flag["disclosure_count"] is None
    assert "exact count" in flag["note"]
    assert "not disciplinary history" in result["disciplinary_summary"]["note"]


@pytest.mark.asyncio
async def test_non_active_current_status_is_flagged_but_not_called_full_history(monkeypatch):
    monkeypatch.setattr(
        registry,
        "search_co_real_estate",
        AsyncMock(
            return_value=[
                {
                    "license_no": "RE-1",
                    "type": "Broker",
                    "status": "Revoked",
                    "expiry": None,
                    "source": "CO DORA 4zse-6bnw",
                    "name": "Jane Smith",
                }
            ]
        ),
    )

    result = await registry.verify_counterparty("Jane Smith", "CO", roles=["real_estate"])

    flag = result["disciplinary_summary"]["flags"][0]
    assert flag["kind"] == "current_status_flag"
    assert flag["status"] == "Revoked"
    assert "reinstatement" in result["disciplinary_summary"]["note"]


@pytest.mark.asyncio
async def test_priority_order_is_finra_iapd_asc_state_contractor_then_nmls(monkeypatch):
    for name in (
        "search_brokercheck_individuals",
        "search_brokercheck_firms",
        "search_iapd_individuals",
        "search_iapd_firms",
        "search_co_real_estate",
        "search_co_all_professions",
    ):
        monkeypatch.setattr(registry, name, AsyncMock(return_value=[]))

    result = await registry.verify_counterparty("Jane Smith", "CO")

    assert list(result["sources"]) == [
        "finra_brokercheck_individual",
        "finra_brokercheck_firm",
        "sec_iapd_individual",
        "sec_iapd_firm",
        "asc_national_registry",
        "co_dora_real_estate",
        "co_dora_all_professions",
        "nmls_consumer_access",
    ]


@pytest.mark.asyncio
async def test_plain_tool_functions_delegate_without_fastmcp_registration(monkeypatch):
    delegate = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(verify_tools, "verify_counterparty", delegate)

    assert await verify_tools.verify_license("Jane", "CO", "real_estate") == {"ok": True}
    delegate.assert_awaited_once_with("Jane", "CO", roles=["real_estate"])
    assert not hasattr(verify_tools.verify_license, "tool")
