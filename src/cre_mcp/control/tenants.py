"""Curated national-tenant criteria and deterministic site-matching helpers.

Published criteria are intentionally kept separate from industry estimates. A tenant
whose ``source`` is ``"industry-typical estimate"`` should be treated as a lead for
further underwriting, not as a statement made by the brand.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TenantCriteria(BaseModel):
    """Physical and demographic criteria commonly used to screen tenant sites."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    brand: str
    category: str
    complementary_categories: list[str] = Field(default_factory=list)
    competitor_brands: list[str] = Field(default_factory=list)
    min_traffic_aadt: int | None = Field(default=None, ge=0)
    min_population_3mi: int | None = Field(default=None, ge=0)
    min_median_household_income: int | None = Field(default=None, ge=0)
    parcel_acres_range: tuple[float, float] | None = None
    building_sqft_range: tuple[int, int] | None = None
    needs_drive_thru: bool = False
    min_parking_spaces: int | None = Field(default=None, ge=0)
    min_frontage_ft: int | None = Field(default=None, ge=0)
    typical_nnn_rent_psf: tuple[float, float] | None = None
    typical_lease_years: int | None = Field(default=None, ge=1)
    guaranty: Literal["corporate", "franchisee", "mixed"]
    expansion_mode: Literal["expanding", "steady", "contracting"]
    notes: str = ""
    source: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("brand", "category", "source")
    @classmethod
    def _require_text(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _validate_ranges(self) -> Self:
        for field_name in (
            "parcel_acres_range",
            "building_sqft_range",
            "typical_nnn_rent_psf",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            low, high = value
            if low < 0 or high < 0:
                raise ValueError(f"{field_name} values must be non-negative")
            if low > high:
                raise ValueError(f"{field_name} lower bound must not exceed upper bound")
        return self


ESTIMATE = "industry-typical estimate"


def _estimated(
    *,
    brand: str,
    category: str,
    complementary_categories: list[str],
    competitor_brands: list[str],
    min_traffic_aadt: int | None,
    min_population_3mi: int | None,
    min_median_household_income: int | None,
    parcel_acres_range: tuple[float, float] | None,
    building_sqft_range: tuple[int, int] | None,
    needs_drive_thru: bool,
    min_parking_spaces: int | None,
    min_frontage_ft: int | None,
    typical_nnn_rent_psf: tuple[float, float] | None,
    typical_lease_years: int | None,
    guaranty: Literal["corporate", "franchisee", "mixed"],
    expansion_mode: Literal["expanding", "steady", "contracting"],
    notes: str,
    confidence: float = 0.45,
) -> TenantCriteria:
    """Build a clearly labeled estimate without implying first-party sourcing."""

    return TenantCriteria(
        brand=brand,
        category=category,
        complementary_categories=complementary_categories,
        competitor_brands=competitor_brands,
        min_traffic_aadt=min_traffic_aadt,
        min_population_3mi=min_population_3mi,
        min_median_household_income=min_median_household_income,
        parcel_acres_range=parcel_acres_range,
        building_sqft_range=building_sqft_range,
        needs_drive_thru=needs_drive_thru,
        min_parking_spaces=min_parking_spaces,
        min_frontage_ft=min_frontage_ft,
        typical_nnn_rent_psf=typical_nnn_rent_psf,
        typical_lease_years=typical_lease_years,
        guaranty=guaranty,
        expansion_mode=expansion_mode,
        notes=notes,
        source=ESTIMATE,
        confidence=confidence,
    )


TENANTS: list[TenantCriteria] = [
    _estimated(
        brand="Starbucks",
        category="coffee",
        complementary_categories=["grocery", "fitness", "bank", "retail"],
        competitor_brands=["Dunkin'", "Dutch Bros Coffee"],
        min_traffic_aadt=20_000,
        min_population_3mi=30_000,
        min_median_household_income=55_000,
        parcel_acres_range=(0.5, 1.2),
        building_sqft_range=(1_800, 2_800),
        needs_drive_thru=True,
        min_parking_spaces=20,
        min_frontage_ft=100,
        typical_nnn_rent_psf=(28.0, 55.0),
        typical_lease_years=10,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="Drive-thru-oriented suburban prototype; urban cafe formats vary widely.",
    ),
    _estimated(
        brand="Dutch Bros Coffee",
        category="coffee",
        complementary_categories=["grocery", "fitness", "convenience", "retail"],
        competitor_brands=["Starbucks", "Dunkin'"],
        min_traffic_aadt=25_000,
        min_population_3mi=35_000,
        min_median_household_income=50_000,
        parcel_acres_range=(0.5, 1.0),
        building_sqft_range=(850, 1_300),
        needs_drive_thru=True,
        min_parking_spaces=12,
        min_frontage_ft=100,
        typical_nnn_rent_psf=(30.0, 50.0),
        typical_lease_years=15,
        guaranty="mixed",
        expansion_mode="expanding",
        notes="Small building with high-throughput drive-thru stacking.",
    ),
    _estimated(
        brand="Dunkin'",
        category="coffee",
        complementary_categories=["grocery", "convenience", "bank", "retail"],
        competitor_brands=["Starbucks", "Dutch Bros Coffee"],
        min_traffic_aadt=18_000,
        min_population_3mi=25_000,
        min_median_household_income=45_000,
        parcel_acres_range=(0.4, 1.0),
        building_sqft_range=(1_500, 2_500),
        needs_drive_thru=True,
        min_parking_spaces=18,
        min_frontage_ft=90,
        typical_nnn_rent_psf=(24.0, 45.0),
        typical_lease_years=10,
        guaranty="franchisee",
        expansion_mode="expanding",
        notes="Freestanding drive-thru format; franchise credit varies by operator.",
    ),
    _estimated(
        brand="Chick-fil-A",
        category="qsr",
        complementary_categories=["grocery", "retail", "fitness", "entertainment"],
        competitor_brands=["McDonald's", "Raising Cane's", "Popeyes"],
        min_traffic_aadt=25_000,
        min_population_3mi=40_000,
        min_median_household_income=55_000,
        parcel_acres_range=(1.2, 2.0),
        building_sqft_range=(4_000, 5_500),
        needs_drive_thru=True,
        min_parking_spaces=45,
        min_frontage_ft=150,
        typical_nnn_rent_psf=(30.0, 55.0),
        typical_lease_years=15,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="High-volume prototype needs substantial dual-lane stacking capacity.",
    ),
    TenantCriteria(
        brand="Panda Express",
        category="qsr",
        complementary_categories=["qsr", "fast_casual", "retail", "entertainment"],
        competitor_brands=["Pei Wei", "Chipotle"],
        min_traffic_aadt=25_000,
        parcel_acres_range=(0.9, 1.1),
        building_sqft_range=(2_400, 2_700),
        needs_drive_thru=True,
        min_parking_spaces=40,
        min_frontage_ft=30,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="First-party criteria call for 25K+ combined VPD and strongly prefer drive-thru.",
        source="https://www.pandaexpress.com/commercial-real-estate",
        confidence=0.95,
    ),
    _estimated(
        brand="Raising Cane's",
        category="qsr",
        complementary_categories=["grocery", "retail", "entertainment", "fitness"],
        competitor_brands=["Chick-fil-A", "Popeyes", "KFC"],
        min_traffic_aadt=25_000,
        min_population_3mi=45_000,
        min_median_household_income=55_000,
        parcel_acres_range=(1.0, 1.8),
        building_sqft_range=(2_800, 3_600),
        needs_drive_thru=True,
        min_parking_spaces=35,
        min_frontage_ft=130,
        typical_nnn_rent_psf=(30.0, 50.0),
        typical_lease_years=15,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="High-volume drive-thru format with long stacking requirement.",
    ),
    TenantCriteria(
        brand="Chipotle Mexican Grill",
        category="fast_casual",
        complementary_categories=["retail", "office", "university", "fitness"],
        competitor_brands=["QDOBA", "Moe's Southwest Grill"],
        building_sqft_range=(2_400, 2_400),
        needs_drive_thru=False,
        min_frontage_ft=38,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="First-party brochure prefers 2,400 SF and 38 feet of frontage; Chipotlane is preferred where feasible, not mandatory.",
        source="https://www.chipotle.com/content/dam/chipotle/pages/development-brochure/DevelopmentBrochure031025A3.pdf",
        confidence=0.95,
    ),
    _estimated(
        brand="Panera Bread",
        category="fast_casual",
        complementary_categories=["grocery", "retail", "office", "fitness"],
        competitor_brands=["Corner Bakery", "Starbucks"],
        min_traffic_aadt=20_000,
        min_population_3mi=35_000,
        min_median_household_income=60_000,
        parcel_acres_range=(0.8, 1.5),
        building_sqft_range=(3_800, 4_800),
        needs_drive_thru=True,
        min_parking_spaces=35,
        min_frontage_ft=120,
        typical_nnn_rent_psf=(22.0, 42.0),
        typical_lease_years=10,
        guaranty="mixed",
        expansion_mode="steady",
        notes="Modern suburban cafe prototype; drive-thru is strongly useful for new standalone sites.",
    ),
    _estimated(
        brand="Jersey Mike's Subs",
        category="fast_casual",
        complementary_categories=["grocery", "retail", "fitness", "office"],
        competitor_brands=["Subway", "Jimmy John's", "Firehouse Subs"],
        min_traffic_aadt=15_000,
        min_population_3mi=25_000,
        min_median_household_income=50_000,
        parcel_acres_range=None,
        building_sqft_range=(1_200, 2_000),
        needs_drive_thru=False,
        min_parking_spaces=15,
        min_frontage_ft=25,
        typical_nnn_rent_psf=(22.0, 40.0),
        typical_lease_years=10,
        guaranty="franchisee",
        expansion_mode="expanding",
        notes="Typically an inline or end-cap user; standalone conversion can work.",
    ),
    _estimated(
        brand="McDonald's",
        category="qsr",
        complementary_categories=["grocery", "retail", "convenience", "travel"],
        competitor_brands=["Burger King", "Wendy's", "Chick-fil-A"],
        min_traffic_aadt=20_000,
        min_population_3mi=25_000,
        min_median_household_income=40_000,
        parcel_acres_range=(1.0, 1.6),
        building_sqft_range=(3_500, 5_000),
        needs_drive_thru=True,
        min_parking_spaces=35,
        min_frontage_ft=140,
        typical_nnn_rent_psf=(25.0, 45.0),
        typical_lease_years=20,
        guaranty="mixed",
        expansion_mode="steady",
        notes="Traditional freestanding dual-drive-thru prototype.",
    ),
    _estimated(
        brand="Taco Bell",
        category="qsr",
        complementary_categories=["grocery", "retail", "convenience", "entertainment"],
        competitor_brands=["Del Taco", "Chipotle Mexican Grill", "QDOBA"],
        min_traffic_aadt=18_000,
        min_population_3mi=25_000,
        min_median_household_income=40_000,
        parcel_acres_range=(0.7, 1.2),
        building_sqft_range=(2_000, 2_800),
        needs_drive_thru=True,
        min_parking_spaces=25,
        min_frontage_ft=110,
        typical_nnn_rent_psf=(24.0, 42.0),
        typical_lease_years=15,
        guaranty="franchisee",
        expansion_mode="expanding",
        notes="Compact freestanding drive-thru; guaranty quality depends on franchise group.",
    ),
    _estimated(
        brand="Dollar General",
        category="dollar_store",
        complementary_categories=["grocery", "pharmacy", "auto_parts", "convenience"],
        competitor_brands=["Family Dollar", "Dollar Tree"],
        min_traffic_aadt=5_000,
        min_population_3mi=5_000,
        min_median_household_income=30_000,
        parcel_acres_range=(1.0, 1.8),
        building_sqft_range=(9_100, 12_500),
        needs_drive_thru=False,
        min_parking_spaces=30,
        min_frontage_ft=120,
        typical_nnn_rent_psf=(9.0, 16.0),
        typical_lease_years=15,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="Rural and exurban freestanding prototype; market-dependent formats vary.",
    ),
    TenantCriteria(
        brand="Dollar Tree",
        category="dollar_store",
        complementary_categories=["grocery", "pharmacy", "auto_parts", "retail"],
        competitor_brands=["Dollar General", "Family Dollar"],
        building_sqft_range=(8_000, 10_000),
        needs_drive_thru=False,
        guaranty="corporate",
        expansion_mode="steady",
        notes="First-party annual report gives 8,000-10,000 selling SF; standalone and shopping-center formats are used.",
        source="https://corporate.dollartree.com/_assets/_007157c37877b37a8fa7f09e9ee35c54/dollartreeinfo/db/893/7757/annual_report/849d12a0-8ee0-49b1-b4f3-6ad739f1b35d.pdf",
        confidence=0.85,
    ),
    TenantCriteria(
        brand="Family Dollar",
        category="dollar_store",
        complementary_categories=["grocery", "pharmacy", "auto_parts", "convenience"],
        competitor_brands=["Dollar General", "Dollar Tree"],
        building_sqft_range=(6_800, 11_000),
        needs_drive_thru=False,
        guaranty="corporate",
        expansion_mode="contracting",
        notes="Published requirements favor visible neighborhood sites with ample parking and low-to-middle-income demographics.",
        source="https://corporate.dollartree.com/_assets/_8deb7ef085561c72ca93127ea1a24df0/dollartreeinfo/files/pages/dollartreeinfo/db/1072/description/508_RealEstateRequirements23FamilyDollar.pdf",
        confidence=0.9,
    ),
    TenantCriteria(
        brand="O'Reilly Auto Parts",
        category="auto_parts",
        complementary_categories=["auto_service", "grocery", "dollar_store", "hardware"],
        competitor_brands=["AutoZone", "Advance Auto Parts", "NAPA Auto Parts"],
        parcel_acres_range=(0.69, 0.8),
        building_sqft_range=(6_800, 7_225),
        needs_drive_thru=False,
        min_parking_spaces=30,
        min_frontage_ft=60,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="First-party guidelines specify 30K-35K SF of land and 30-40 parking spaces.",
        source="https://corporate.oreillyauto.com/real-estate/",
        confidence=0.98,
    ),
    TenantCriteria(
        brand="AutoZone",
        category="auto_parts",
        complementary_categories=["auto_service", "grocery", "dollar_store", "hardware"],
        competitor_brands=["O'Reilly Auto Parts", "Advance Auto Parts", "NAPA Auto Parts"],
        needs_drive_thru=False,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="The company reports targeting high-visibility, high-traffic thoroughfares with access and parking; it does not publish numeric US thresholds.",
        source="https://www.sec.gov/Archives/edgar/data/866787/000110465925102611/azo-20250830x10k.htm",
        confidence=0.8,
    ),
    _estimated(
        brand="Advance Auto Parts",
        category="auto_parts",
        complementary_categories=["auto_service", "grocery", "dollar_store", "hardware"],
        competitor_brands=["AutoZone", "O'Reilly Auto Parts", "NAPA Auto Parts"],
        min_traffic_aadt=12_000,
        min_population_3mi=15_000,
        min_median_household_income=40_000,
        parcel_acres_range=(0.6, 1.0),
        building_sqft_range=(6_000, 8_000),
        needs_drive_thru=False,
        min_parking_spaces=25,
        min_frontage_ft=70,
        typical_nnn_rent_psf=(11.0, 19.0),
        typical_lease_years=10,
        guaranty="corporate",
        expansion_mode="contracting",
        notes="Freestanding auto-parts prototype; verify current market expansion appetite.",
    ),
    _estimated(
        brand="Take 5 Oil Change",
        category="auto_service",
        complementary_categories=["auto_parts", "car_wash", "convenience", "grocery"],
        competitor_brands=["Jiffy Lube", "Valvoline Instant Oil Change"],
        min_traffic_aadt=20_000,
        min_population_3mi=25_000,
        min_median_household_income=45_000,
        parcel_acres_range=(0.35, 0.75),
        building_sqft_range=(1_400, 2_200),
        needs_drive_thru=True,
        min_parking_spaces=8,
        min_frontage_ft=100,
        typical_nnn_rent_psf=(25.0, 45.0),
        typical_lease_years=15,
        guaranty="mixed",
        expansion_mode="expanding",
        notes="Drive-through service-bay format; zoning and curb-cut feasibility are critical.",
    ),
    TenantCriteria(
        brand="7-Eleven",
        category="convenience",
        complementary_categories=["auto_service", "qsr", "travel", "retail"],
        competitor_brands=["Circle K", "Wawa", "Speedway"],
        building_sqft_range=(1_400, 1_800),
        needs_drive_thru=False,
        guaranty="mixed",
        expansion_mode="expanding",
        notes="Published conversion criteria prefer 1,800 SF of selling space and consider a 1,400 SF minimum; fuel formats need much larger sites.",
        source="https://www.franchise.7-eleven.com/franchise/faq",
        confidence=0.85,
    ),
    _estimated(
        brand="Wawa",
        category="convenience",
        complementary_categories=["travel", "auto_service", "qsr", "retail"],
        competitor_brands=["7-Eleven", "Sheetz", "Royal Farms"],
        min_traffic_aadt=20_000,
        min_population_3mi=25_000,
        min_median_household_income=45_000,
        parcel_acres_range=(1.5, 2.5),
        building_sqft_range=(5_500, 6_500),
        needs_drive_thru=False,
        min_parking_spaces=45,
        min_frontage_ft=180,
        typical_nnn_rent_psf=(20.0, 38.0),
        typical_lease_years=15,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="Modern fuel-and-food prototype; non-fuel and drive-thru variants differ.",
    ),
    TenantCriteria(
        brand="Walgreens",
        category="pharmacy",
        complementary_categories=["grocery", "medical", "bank", "dollar_store"],
        competitor_brands=["CVS Pharmacy", "Rite Aid"],
        min_population_3mi=20_000,
        parcel_acres_range=(1.35, 1.4),
        building_sqft_range=(14_820, 14_820),
        needs_drive_thru=True,
        min_parking_spaces=50,
        guaranty="corporate",
        expansion_mode="contracting",
        notes="Published traditional prototype calls for roughly 60K SF of land at a signalized intersection.",
        source="https://www.walgreens.com/topic/help/companyhelp/real_estate.jsp?tier3Id=1445",
        confidence=0.95,
    ),
    _estimated(
        brand="CVS Pharmacy",
        category="pharmacy",
        complementary_categories=["grocery", "medical", "bank", "dollar_store"],
        competitor_brands=["Walgreens", "Rite Aid"],
        min_traffic_aadt=20_000,
        min_population_3mi=25_000,
        min_median_household_income=45_000,
        parcel_acres_range=(1.2, 1.8),
        building_sqft_range=(11_000, 15_000),
        needs_drive_thru=True,
        min_parking_spaces=45,
        min_frontage_ft=150,
        typical_nnn_rent_psf=(16.0, 30.0),
        typical_lease_years=20,
        guaranty="corporate",
        expansion_mode="contracting",
        notes="Traditional freestanding pharmacy prototype; small-format clinics vary.",
    ),
    _estimated(
        brand="Sherwin-Williams",
        category="home_improvement",
        complementary_categories=["hardware", "auto_parts", "grocery", "home_furnishings"],
        competitor_brands=["Benjamin Moore", "PPG Paints"],
        min_traffic_aadt=12_000,
        min_population_3mi=20_000,
        min_median_household_income=50_000,
        parcel_acres_range=(0.4, 1.0),
        building_sqft_range=(4_000, 6_500),
        needs_drive_thru=False,
        min_parking_spaces=18,
        min_frontage_ft=60,
        typical_nnn_rent_psf=(14.0, 24.0),
        typical_lease_years=10,
        guaranty="corporate",
        expansion_mode="steady",
        notes="Visible contractor-friendly location with loading access is preferred.",
    ),
    _estimated(
        brand="Aspen Dental",
        category="dental",
        complementary_categories=["medical", "grocery", "fitness", "retail"],
        competitor_brands=["Heartland Dental", "Pacific Dental Services"],
        min_traffic_aadt=18_000,
        min_population_3mi=35_000,
        min_median_household_income=45_000,
        parcel_acres_range=None,
        building_sqft_range=(3_000, 4_500),
        needs_drive_thru=False,
        min_parking_spaces=20,
        min_frontage_ft=40,
        typical_nnn_rent_psf=(25.0, 42.0),
        typical_lease_years=10,
        guaranty="mixed",
        expansion_mode="expanding",
        notes="End-cap or standalone medical-retail conversion with strong signage.",
    ),
    _estimated(
        brand="Verizon",
        category="telecom",
        complementary_categories=["grocery", "retail", "fitness", "bank"],
        competitor_brands=["T-Mobile", "AT&T"],
        min_traffic_aadt=20_000,
        min_population_3mi=35_000,
        min_median_household_income=60_000,
        parcel_acres_range=None,
        building_sqft_range=(1_800, 3_000),
        needs_drive_thru=False,
        min_parking_spaces=15,
        min_frontage_ft=30,
        typical_nnn_rent_psf=(28.0, 50.0),
        typical_lease_years=10,
        guaranty="mixed",
        expansion_mode="steady",
        notes="Dealer-operated stores may carry materially different credit from corporate stores.",
    ),
    _estimated(
        brand="T-Mobile",
        category="telecom",
        complementary_categories=["grocery", "retail", "fitness", "bank"],
        competitor_brands=["Verizon", "AT&T"],
        min_traffic_aadt=20_000,
        min_population_3mi=35_000,
        min_median_household_income=55_000,
        parcel_acres_range=None,
        building_sqft_range=(1_500, 2_800),
        needs_drive_thru=False,
        min_parking_spaces=15,
        min_frontage_ft=25,
        typical_nnn_rent_psf=(28.0, 50.0),
        typical_lease_years=10,
        guaranty="mixed",
        expansion_mode="steady",
        notes="Confirm whether the proposed tenant is corporate or an authorized retailer.",
    ),
    _estimated(
        brand="Crunch Fitness",
        category="fitness",
        complementary_categories=["grocery", "retail", "coffee", "medical"],
        competitor_brands=["Planet Fitness", "LA Fitness", "Anytime Fitness"],
        min_traffic_aadt=20_000,
        min_population_3mi=60_000,
        min_median_household_income=50_000,
        parcel_acres_range=None,
        building_sqft_range=(20_000, 40_000),
        needs_drive_thru=False,
        min_parking_spaces=100,
        min_frontage_ft=100,
        typical_nnn_rent_psf=(12.0, 22.0),
        typical_lease_years=10,
        guaranty="franchisee",
        expansion_mode="expanding",
        notes="Large-format adaptive-reuse candidate; parking and floor loading need review.",
    ),
    _estimated(
        brand="Planet Fitness",
        category="fitness",
        complementary_categories=["grocery", "retail", "coffee", "medical"],
        competitor_brands=["Crunch Fitness", "LA Fitness", "Anytime Fitness"],
        min_traffic_aadt=18_000,
        min_population_3mi=50_000,
        min_median_household_income=40_000,
        parcel_acres_range=None,
        building_sqft_range=(18_000, 30_000),
        needs_drive_thru=False,
        min_parking_spaces=90,
        min_frontage_ft=90,
        typical_nnn_rent_psf=(10.0, 18.0),
        typical_lease_years=10,
        guaranty="franchisee",
        expansion_mode="expanding",
        notes="Value fitness conversion user; franchisee credit and exclusives require review.",
    ),
    TenantCriteria(
        brand="ALDI",
        category="grocery",
        complementary_categories=["pharmacy", "fitness", "coffee", "auto_parts"],
        competitor_brands=["Lidl", "Walmart Neighborhood Market"],
        min_traffic_aadt=20_000,
        parcel_acres_range=(2.4, 2.6),
        building_sqft_range=(18_000, 18_000),
        needs_drive_thru=False,
        min_parking_spaces=85,
        min_frontage_ft=87,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="Published criteria call for a 2.5-acre pad, 18K SF building, 85 spaces, dense 3-mile population, and 20K+ VPD.",
        source="https://corporate.aldi.us/fileadmin/fm-dam/real_estates/ALDI_Real_Estate_Flyer_Master_4.10.15_-_FINAL.PDF",
        confidence=0.95,
    ),
    _estimated(
        brand="Chase Bank",
        category="bank",
        complementary_categories=["grocery", "coffee", "retail", "medical"],
        competitor_brands=["Bank of America", "Wells Fargo", "U.S. Bank"],
        min_traffic_aadt=20_000,
        min_population_3mi=40_000,
        min_median_household_income=65_000,
        parcel_acres_range=(0.5, 1.2),
        building_sqft_range=(2_500, 4_500),
        needs_drive_thru=False,
        min_parking_spaces=20,
        min_frontage_ft=100,
        typical_nnn_rent_psf=(28.0, 50.0),
        typical_lease_years=10,
        guaranty="corporate",
        expansion_mode="expanding",
        notes="Retail branch prototype; dense urban branches can use much smaller footprints.",
    ),
]


def _normalized(value: str) -> str:
    return value.strip().casefold()


def get_tenant(brand: str) -> TenantCriteria | None:
    """Return a tenant by case-insensitive brand name."""

    wanted = _normalized(brand)
    return next((tenant for tenant in TENANTS if _normalized(tenant.brand) == wanted), None)


def tenants_by_category(category: str) -> list[TenantCriteria]:
    """Return catalog entries in a category, matched case-insensitively."""

    wanted = _normalized(category)
    return [tenant for tenant in TENANTS if _normalized(tenant.category) == wanted]


def match_site(
    *,
    aadt: int | None,
    population_3mi: int | None,
    median_income: int | None,
    parcel_acres: float | None,
    building_sqft: int | None,
    has_drive_thru: bool | None,
    nearby_categories: list[str] | None = None,
) -> list[dict[str, object]]:
    """Rank tenants against supplied site facts without treating unknowns as failures."""

    nearby = {_normalized(category) for category in nearby_categories or []}
    ranked: list[dict[str, object]] = []

    for tenant in TENANTS:
        met: list[str] = []
        unmet: list[str] = []

        def check_minimum(
            label: str, site_value: int | None, minimum: int | None
        ) -> None:
            if site_value is None or minimum is None:
                return
            message = f"{label} {site_value:,} vs minimum {minimum:,}"
            (met if site_value >= minimum else unmet).append(message)

        def check_range(
            label: str,
            site_value: int | float | None,
            accepted: tuple[int, int] | tuple[float, float] | None,
        ) -> None:
            if site_value is None or accepted is None:
                return
            low, high = accepted
            message = f"{label} {site_value:g} vs range {low:g}-{high:g}"
            (met if low <= site_value <= high else unmet).append(message)

        check_minimum("AADT", aadt, tenant.min_traffic_aadt)
        check_minimum("3-mile population", population_3mi, tenant.min_population_3mi)
        check_minimum(
            "median household income",
            median_income,
            tenant.min_median_household_income,
        )
        check_range("parcel acres", parcel_acres, tenant.parcel_acres_range)
        check_range("building SF", building_sqft, tenant.building_sqft_range)

        if has_drive_thru is not None and tenant.needs_drive_thru:
            message = "required drive-thru is present"
            if has_drive_thru:
                met.append(message)
            else:
                unmet.append("required drive-thru is absent")

        evaluated = len(met) + len(unmet)
        fit_score = len(met) / evaluated if evaluated else 0.5
        adjustments: list[str] = []

        complementary = {
            _normalized(category) for category in tenant.complementary_categories
        }
        overlap = sorted(nearby & complementary)
        if overlap:
            bonus = min(0.15, 0.05 * len(overlap))
            fit_score += bonus
            adjustments.append(
                f"co-tenancy bonus for nearby {', '.join(overlap)}"
            )

        tenant_category = _normalized(tenant.category)
        if tenant_category in nearby:
            fit_score -= 0.1
            adjustments.append(f"competition penalty for nearby {tenant.category}")

        fit_score = round(max(0.0, min(1.0, fit_score)), 4)
        reason_parts: list[str] = []
        if met:
            reason_parts.append(f"Met {len(met)} evaluated criteria")
        if unmet:
            reason_parts.append(f"Missed {len(unmet)} evaluated criteria")
        if not met and not unmet:
            reason_parts.append("No supplied site facts matched a defined criterion")
        reason_parts.extend(adjustments)

        ranked.append(
            {
                "brand": tenant.brand,
                "fit_score": fit_score,
                "met": met,
                "unmet": unmet,
                "reasons": "; ".join(reason_parts) + ".",
            }
        )

    ranked.sort(
        key=lambda result: (
            -float(result["fit_score"]),
            -len(result["met"]),  # type: ignore[arg-type]
            str(result["brand"]).casefold(),
        )
    )
    return ranked
