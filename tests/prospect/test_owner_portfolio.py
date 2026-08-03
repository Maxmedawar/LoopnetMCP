from cre_mcp.prospect.portfolio_sellers import portfolio_owner_scan
from cre_mcp.prospect.saleleaseback import sale_leaseback_candidates


def test_sale_leaseback_token_overlap_positive_and_negative_cases():
    result = sale_leaseback_candidates(
        [
            {
                "owner_name": "Acme Foods, LLC",
                "business_name": "Acme Foods Market",
                "use": "retail",
                "assessed_value": 2_000_000,
                "sf": 12_000,
            },
            {
                "owner_name": "North River Holdings LLC",
                "business_name": "Acme Foods Market",
                "use": "retail",
                "assessed_value": 2_500_000,
                "sf": 13_000,
            },
        ]
    )

    assert result["candidate_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["record_index"] == 0
    assert candidate["basis"]["common_tokens"] == ["acme", "foods"]
    assert candidate["basis"]["overlap_coefficient"] == 1.0
    assert candidate["signal_label"] == "HEURISTIC INFERENCE"
    assert candidate["diligence"] == "verify occupancy and financials directly"
    assert result["assessments"][1]["is_candidate"] is False


def test_sale_leaseback_nullable_names_and_unknown_fields_are_visible():
    result = sale_leaseback_candidates(
        [{"owner_name": None, "business_name": None, "sf": None, "source_row": "A-1"}]
    )

    assert result["candidate_count"] == 0
    assert result["assessments"][0]["basis"]["overlap_coefficient"] == 0.0
    assert result["unrecognized_input_fields"] == ["source_row"]
    assert result["assessments"][0]["unrecognized_fields"] == ["source_row"]


def test_portfolio_groups_normalized_owner_variants_and_applies_minimum():
    result = portfolio_owner_scan(
        [
            {"owner_name": "Café Plaza, L.L.C.", "property_id": "1", "use": "retail", "sf": 10_000},
            {"owner_name": "CAFE PLAZA LLC", "property_id": "2", "use": "retail", "sf": 11_000},
            {"owner_name": "Solo Owner LP", "property_id": "3", "use": "office", "sf": 8_000},
        ],
        min_properties=2,
    )

    assert result["owner_group_count"] == 1
    owner = result["owners"][0]
    assert owner["normalized_owner_name"] == "cafe plaza"
    assert owner["property_count"] == 2
    assert owner["profile"]["use_counts"] == {"retail": 2}
    assert "not a calibrated seller signal" not in owner["dispersion_note"]
    assert "fewer than two usable coordinates" in owner["dispersion_note"]


def test_portfolio_flags_type_and_far_size_outliers_with_exposed_basis():
    result = portfolio_owner_scan(
        [
            {"owner_name": "Example Owner LLC", "property_id": "1", "use": "retail", "sf": 10_000},
            {"owner_name": "Example Owner Inc.", "property_id": "2", "use": "retail", "sf": 11_000},
            {"owner_name": "Example Owner LP", "property_id": "3", "use": "industrial", "sf": 80_000},
        ]
    )

    owner = result["owners"][0]
    outlier = next(item for item in owner["properties"] if item["property_id"] == "3")
    assert owner["profile"]["modal_use_for_outlier_test"] == "retail"
    assert owner["profile"]["median_sf"] == 11_000
    assert owner["profile"]["size_ratio_outlier_threshold"] == 3.0
    assert outlier["noncore_outlier_flag"] is True
    assert outlier["signal_label"] == "HEURISTIC INFERENCE"
    assert any("differs from the modal use" in basis for basis in outlier["basis"])
    assert any("portfolio median" in basis for basis in outlier["basis"])
    assert "does not establish noncore status or intent to sell" in outlier["inference_caution"]


def test_portfolio_nullable_input_skips_missing_owner_and_surfaces_unknown_fields():
    empty = portfolio_owner_scan(None, min_properties=1)
    assert empty["record_count"] == 0

    result = portfolio_owner_scan(
        [{"owner_name": None, "sf": None, "county_code": "06037"}], min_properties=1
    )
    assert result["owner_group_count"] == 0
    assert result["skipped_records"][0]["reason"] == "missing or unusable owner_name"
    assert result["unrecognized_input_fields"] == ["county_code"]
