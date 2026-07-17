from cre_mcp.control.tenants import TENANTS, TenantCriteria, get_tenant, match_site


def test_catalog_is_substantial_and_valid() -> None:
    assert len(TENANTS) >= 25
    assert len({tenant.brand.casefold() for tenant in TENANTS}) == len(TENANTS)
    for tenant in TENANTS:
        assert isinstance(tenant, TenantCriteria)
        assert tenant.source
        assert 0.0 <= tenant.confidence <= 1.0
        TenantCriteria.model_validate(tenant.model_dump())


def test_get_tenant_is_case_insensitive() -> None:
    tenant = get_tenant("  sTaRbUcKs  ")
    assert tenant is not None
    assert tenant.brand == "Starbucks"


def test_drive_thru_high_traffic_site_favors_coffee_or_qsr() -> None:
    matches = match_site(
        aadt=48_000,
        population_3mi=75_000,
        median_income=82_000,
        parcel_acres=1.0,
        building_sqft=2_500,
        has_drive_thru=True,
        nearby_categories=["grocery", "retail"],
    )
    leading_brands = {result["brand"] for result in matches[:5]}
    assert leading_brands & {
        "Starbucks",
        "Dutch Bros Coffee",
        "Dunkin'",
        "Panda Express",
        "Taco Bell",
    }


def test_low_traffic_lower_income_site_favors_dollar_store() -> None:
    matches = match_site(
        aadt=7_500,
        population_3mi=8_000,
        median_income=36_000,
        parcel_acres=1.3,
        building_sqft=10_000,
        has_drive_thru=False,
        nearby_categories=["grocery"],
    )
    dollar_store_positions = [
        index
        for index, result in enumerate(matches)
        if result["brand"] in {"Dollar General", "Dollar Tree", "Family Dollar"}
    ]
    assert min(dollar_store_positions) < 5


def test_all_unknown_inputs_do_not_crash_or_fail_tenants() -> None:
    matches = match_site(
        aadt=None,
        population_3mi=None,
        median_income=None,
        parcel_acres=None,
        building_sqft=None,
        has_drive_thru=None,
    )
    assert len(matches) == len(TENANTS)
    assert all(result["met"] == [] for result in matches)
    assert all(result["unmet"] == [] for result in matches)
    assert all(0.0 <= result["fit_score"] <= 1.0 for result in matches)
