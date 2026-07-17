"""Assessor-record comparison tests."""

from cre_mcp.taxecon.assessor_audit import audit_assessor_record


def test_owner_record_shape_surfaces_overassessment_and_classification_signals():
    record = {
        "name": "Example Owner LLC",
        "parcels": [
            {
                "assessed_value": 3_000_000,
                "building_sqft": 20_000,
                "units": 12,
                "year_built": 2015,
                "use_code": "office",
            }
        ],
    }
    stated = {
        "building_sqft": 18_000,
        "units": 10,
        "year_built": 1998,
        "property_type": "industrial",
        "assessed_value_psf_comps": {"low": 90, "base": 110, "high": 125},
    }

    result = audit_assessor_record(record, stated)
    by_field = {item["field"]: item for item in result["discrepancies"]}

    assert result["record_shape"] == "owner_record.parcels[0]"
    assert by_field["building_sqft"]["appeal_signal"] is True
    assert by_field["units"]["appeal_signal"] is True
    assert by_field["year_built"]["appeal_signal"] is True
    assert by_field["use_code"]["appeal_signal"] is True
    assert by_field["assessed_value_psf"]["appeal_signal"] is True
    assert result["assessor_implied_value_psf"] == 150
    assert result["professional_review_required"] is True


def test_lower_assessor_square_footage_warns_of_future_increase_not_appeal_win():
    result = audit_assessor_record(
        {"assessed_value": 1_000_000, "building_sqft": 9_000},
        {"building_sqft": 10_000},
    )

    item = result["discrepancies"][0]
    assert item["field"] == "building_sqft"
    assert item["appeal_signal"] is False
    assert "future increase" in item["direction_of_tax_impact"]

