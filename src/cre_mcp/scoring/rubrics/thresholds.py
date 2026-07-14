"""Every tunable scoring threshold, weight, cutoff, and composition constant."""

NORMALIZED_MIN = 0.0
NORMALIZED_MAX = 1.0
SCORE_SCALE = 100.0
FULL_COVERAGE = 1.0
NO_COVERAGE = 0.0

COMPOSITION_WEIGHTS = {
    "strategy": 0.50,
    "core": 0.30,
    "market": 0.20,
}
DEFAULT_MARKET_WEIGHT = COMPOSITION_WEIGHTS["market"]

GRADE_CUTOFFS = (
    (90.0, "A"),
    (80.0, "A-/B+"),
    (70.0, "B"),
    (60.0, "C"),
    (50.0, "D"),
)
FAIL_GRADE = "F"
DISQUALIFIED_GRADE = "DQ"
NOT_RATED_GRADE = "NR"

# Trust gate: both headline strategy coverage and required-input confidence
# must clear these minimums before a letter grade is presented.
GATE_MIN_CONFIDENCE = 0.50
GATE_MIN_COVERAGE = 0.50
GATE_MISSING_SIGNAL_LIMIT = 3
GATE_MISSING_INPUT_GUIDANCE = {
    "tenant_credit_tier": "the executed lease, guaranty, and current tenant credit report",
    "lease_years_remaining": "the executed lease and all amendments",
    "rent_escalations": "the lease rent schedule and amendments",
    "nnn_purity": "the lease expense and maintenance clauses",
    "corporate_vs_franchisee": "the signed guaranty and tenant entity documents",
    "cap_rate_vs_band": "seller NOI support and verified market sale comps",
    "going_in_cap": "a current T-12, rent roll, and seller operating statements",
    "dscr_year1": "a lender term sheet plus verified NOI",
    "rent_gap_to_market": "the rent roll, lease files, and verified rent comps",
    "price_per_unit_vs_submarket": "verified sale comps and unit counts",
    "price_per_sf_vs_replacement": "verified sale comps and replacement-cost support",
    "traffic_count": "the nearest state DOT traffic-count station",
    "demographics_3mi": "a geocoded three-mile demographic report",
    "pedestrian_score_100m": "a site visit and pedestrian-count evidence",
    "street_level_frontage": "a survey, floor plan, and site inspection",
}
GATE_DEFAULT_MISSING_INPUT_GUIDANCE = (
    "the source documents, verified comps, and applicable lease or financial records"
)

NNN_BASE_WEIGHTS = {
    "tenant_credit_tier": 0.18,
    "lease_years_remaining": 0.14,
    "rent_escalations": 0.08,
    "cap_rate_vs_band": 0.10,
    "nnn_purity": 0.06,
    "corporate_vs_franchisee": 0.08,
    "traffic_count": 0.07,
    "demographics_3mi": 0.08,
    "visibility_corner": 0.05,
    "price_vs_replacement": 0.06,
    "residual_value_land": 0.05,
    "co_tenancy_quality": 0.05,
}
NNN_PARKING_WEIGHT = 0.04
NNN_EXISTING_WEIGHT_SCALE = 1.0 - NNN_PARKING_WEIGHT
NNN_WEIGHTS = {
    key: weight * NNN_EXISTING_WEIGHT_SCALE
    for key, weight in NNN_BASE_WEIGHTS.items()
} | {"parking_adequacy": NNN_PARKING_WEIGHT}

VAM_WEIGHTS = {
    "rent_gap_to_market": 0.15,
    "price_per_unit_vs_submarket": 0.10,
    "price_per_sf_vs_replacement": 0.08,
    "going_in_cap": 0.10,
    "stabilized_yoc": 0.12,
    "dscr_year1": 0.08,
    "submarket_job_growth_5yr": 0.08,
    "submarket_pop_growth_5yr": 0.06,
    "supply_pipeline": 0.08,
    "unit_mix_bias": 0.05,
    "capex_defensibility": 0.05,
    "1031_fit": 0.05,
}

LWL_WEIGHTS = {
    "pedestrian_score_100m": 0.18,
    "street_level_frontage": 0.12,
    "micro_location_rank": 0.14,
    "demand_generator_proximity": 0.10,
    "irreplaceability": 0.08,
    "size_sweet_spot": 0.05,
    "condo_hoa_health": 0.06,
    "income_upside_vs_current_rent": 0.08,
    "signage_visibility": 0.04,
    "path_of_growth_score": 0.07,
    "price_per_sf_vs_top_block": 0.05,
    "tax_incentive_layer": 0.03,
}

CORE_BASE_WEIGHTS = {
    "cap_rate_vs_treasury_spread": 0.15,
    "price_vs_avm": 0.12,
    "days_on_market": 0.06,
    "price_reduction_history": 0.05,
    "msa_job_growth_36mo": 0.08,
    "msa_population_growth_36mo": 0.06,
    "msa_median_hh_income": 0.05,
    "supply_pipeline_ratio": 0.06,
    "crime_index": 0.04,
    "flood_wildfire_risk": 0.05,
    "assessor_last_sale_delta": 0.06,
    "title_environmental_clean": 0.06,
    "debt_market_liquidity": 0.05,
    "path_of_progress_score": 0.07,
    "sanity_dscr": 0.04,
}
CORE_ENRICHMENT_SIGNAL_WEIGHT = 0.03
CORE_EXISTING_WEIGHT_SCALE = 1.0 - (2 * CORE_ENRICHMENT_SIGNAL_WEIGHT)
CORE_WEIGHTS = {
    key: weight * CORE_EXISTING_WEIGHT_SCALE
    for key, weight in CORE_BASE_WEIGHTS.items()
} | {
    "owner_absentee": CORE_ENRICHMENT_SIGNAL_WEIGHT,
    "owner_tenure_years": CORE_ENRICHMENT_SIGNAL_WEIGHT,
}

DISTRESSED_WEIGHTS = {
    "discount_to_upb": 0.15,
    "discount_to_bpo": 0.15,
    "ltv_at_entry": 0.10,
    "lien_position": 0.08,
    "judicial_vs_nonjudicial_state": 0.06,
    "borrower_engagement": 0.08,
    "collateral_quality_carryover": 0.15,
    "exit_optionality": 0.08,
    "1031_backfill_readiness": 0.06,
    "oz_qof_layer": 0.03,
    "sponsor_track_record": 0.06,
}

REQUIRED_SIGNALS = {
    "tenant_credit_tier",
    "lease_years_remaining",
    "rent_gap_to_market",
    "going_in_cap",
    "dscr_year1",
    "pedestrian_score_100m",
    "street_level_frontage",
}

# Bands are (upper edge, normalized score). A None edge is the terminal band.
# For higher-is-better signals, an edge starts the next band at equality. For
# lower-is-better signals, the edge is inclusive in the current band.
SIGNAL_BANDS = {
    "lease_years_remaining": ((5.0, 0.0), (7.0, 0.15), (10.0, 0.40), (12.0, 0.70), (15.0, 0.85), (None, 1.0)),
    "traffic_count": ((10_000.0, 0.10), (15_000.0, 0.35), (20_000.0, 0.60), (30_000.0, 0.80), (None, 1.0)),
    "parking_adequacy": ((2.0, 0.10), (3.0, 0.40), (4.0, 0.70), (None, 1.0)),
    "price_vs_replacement": ((0.85, 1.0), (1.0, 0.75), (1.15, 0.40), (None, 0.10)),
    "residual_value_land": ((0.15, 0.10), (0.25, 0.40), (0.40, 0.70), (None, 1.0)),
    "co_tenancy_quality": ((1.0, 0.25), (3.0, 0.60), (None, 1.0)),
    "rent_gap_to_market": ((6.0, 0.15), (12.0, 0.50), (20.0, 0.80), (None, 1.0)),
    "price_per_unit_vs_submarket": ((0.80, 1.0), (0.95, 0.75), (1.10, 0.40), (None, 0.10)),
    "price_per_sf_vs_replacement": ((0.75, 1.0), (0.90, 0.75), (1.05, 0.40), (None, 0.10)),
    "going_in_cap": ((0.50, 0.0), (1.50, 0.35), (2.50, 0.70), (None, 1.0)),
    "stabilized_yoc": ((0.75, 0.10), (1.25, 0.40), (2.0, 0.70), (None, 1.0)),
    "dscr_year1": ((1.15, 0.0), (1.25, 0.40), (1.35, 0.75), (None, 1.0)),
    "submarket_job_growth_5yr": ((0.30, 0.10), (1.0, 0.40), (2.0, 0.75), (None, 1.0)),
    "submarket_pop_growth_5yr": ((0.0, 0.0), (0.75, 0.35), (1.50, 0.70), (None, 1.0)),
    "supply_pipeline": ((2.0, 1.0), (4.0, 0.70), (7.0, 0.35), (None, 0.05)),
    "pedestrian_score_100m": ((0.50, 0.10), (0.75, 0.40), (0.90, 0.80), (None, 1.0)),
    "micro_location_rank": ((5.0, 1.0), (15.0, 0.80), (30.0, 0.50), (None, 0.10)),
    "demand_generator_proximity": ((400.0, 1.0), (800.0, 0.70), (1_500.0, 0.35), (None, 0.05)),
    "income_upside_vs_current_rent": ((0.0, 0.10), (20.0, 0.40), (40.0, 0.75), (None, 1.0)),
    "price_per_sf_vs_top_block": ((0.85, 1.0), (1.0, 0.75), (1.15, 0.35), (None, 0.05)),
    "tax_incentive_layer": ((1.0, 0.30), (2.0, 0.70), (None, 1.0)),
    "cap_rate_vs_treasury_spread": ((0.0, 0.0), (100.0, 0.05), (200.0, 0.40), (300.0, 0.75), (None, 1.0)),
    "price_vs_avm": ((0.90, 1.0), (1.0, 0.75), (1.10, 0.35), (None, 0.05)),
    "msa_job_growth_36mo": ((0.0, 0.0), (3.0, 0.40), (6.0, 0.75), (None, 1.0)),
    "msa_population_growth_36mo": ((0.0, 0.0), (1.0, 0.35), (3.0, 0.70), (None, 1.0)),
    "msa_median_hh_income": ((0.75, 0.10), (0.90, 0.40), (1.10, 0.70), (None, 1.0)),
    "supply_pipeline_ratio": ((2.0, 1.0), (5.0, 0.70), (8.0, 0.35), (None, 0.05)),
    "assessor_last_sale_delta": ((1.15, 1.0), (1.35, 0.70), (1.75, 0.35), (None, 0.10)),
    "owner_tenure_years": ((3.0, 0.10), (7.0, 0.35), (12.0, 0.65), (20.0, 0.85), (None, 1.0)),
    "sanity_dscr": ((1.15, 0.0), (1.25, 0.45), (1.35, 0.80), (None, 1.0)),
    "discount_to_upb": ((0.55, 1.0), (0.70, 0.80), (0.85, 0.50), (None, 0.15)),
    "discount_to_bpo": ((0.60, 1.0), (0.75, 0.75), (0.90, 0.40), (None, 0.05)),
    "ltv_at_entry": ((0.55, 1.0), (0.65, 0.85), (0.75, 0.55), (None, 0.15)),
}

LOWER_IS_BETTER = {
    "price_vs_replacement",
    "price_per_unit_vs_submarket",
    "price_per_sf_vs_replacement",
    "supply_pipeline",
    "micro_location_rank",
    "demand_generator_proximity",
    "price_per_sf_vs_top_block",
    "price_vs_avm",
    "supply_pipeline_ratio",
    "assessor_last_sale_delta",
    "discount_to_upb",
    "discount_to_bpo",
    "ltv_at_entry",
}

# Number of leading bands whose upper edge is strict for signals that mix
# strict and inclusive ranges. The final numeric edge remains inclusive.
LOWER_EXCLUSIVE_EDGE_COUNTS = {
    "supply_pipeline": 2,
    "supply_pipeline_ratio": 2,
}

CREDIT_RATING_SCORES = {
    "AAA": 1.0,
    "AA+": 1.0,
    "AA": 1.0,
    "AA-": 1.0,
    "A+": 0.90,
    "A": 0.90,
    "A-": 0.90,
    "BBB+": 0.75,
    "BBB": 0.75,
    "BBB-": 0.60,
    "BB+": 0.35,
    "BB": 0.35,
    "BB-": 0.35,
    "UNRATED": 0.10,
    "BELOW": 0.10,
}
INVESTMENT_GRADE_MIN_SCORE = 0.60
SUB_INVESTMENT_GRADE_MAX_SCORE = 0.35

NNN_CAP_RATE_RANGES = {
    "AAA_AA": (4.5, 5.5),
    "A": (5.0, 6.0),
    "BBB": (5.5, 6.5),
    "SUB_IG": (6.5, 8.0),
}
NNN_CAP_IN_BAND_SCORE = 0.70
NNN_CAP_WITHIN_50_BPS_SCORE = 0.30
NNN_CAP_AT_OR_ABOVE_TOP_SCORE = 1.0
NNN_CAP_TOO_LOW_SCORE = 0.0
NNN_CAP_NEAR_BAND_GAP_PCT = 0.50
NNN_CAP_DISQUALIFIER_GAP_PCT = 1.50

RENT_ESCALATION_ANNUAL_FULL_PCT = 3.0
RENT_ESCALATION_ANNUAL_GOOD_PCT = 2.0
RENT_ESCALATION_FIVE_YEAR_FULL_PCT = 10.0
RENT_ESCALATION_FULL_SCORE = 1.0
RENT_ESCALATION_GOOD_SCORE = 0.85
RENT_ESCALATION_OPTION_SCORE = 0.60
RENT_ESCALATION_FLAT_SCORE = 0.15

NNN_PURITY_SCORES = {
    "absolute": 1.0,
    "absolute nnn": 1.0,
    "absolute-net": 1.0,
    "nnn": 0.90,
    "triple net": 0.90,
    "nn": 0.60,
    "double net": 0.60,
    "gross": 0.20,
    "modified gross": 0.20,
}
GUARANTY_SCORES = {
    "corporate": 0.70,
    "corporate investment grade": 1.0,
    "corporate ig": 1.0,
    "corporate sub-investment grade": 0.70,
    "corporate sub-ig": 0.70,
    "franchisee": 0.15,
    "single-unit franchisee": 0.15,
}
FRANCHISEE_SCALE_MIN_UNITS = 50.0
FRANCHISEE_SCALE_SCORE = 0.50

DEMOGRAPHIC_POP_BANDS = ((20_000.0, 0.10), (40_000.0, 0.40), (60_000.0, 0.70), (75_000.0, 0.85), (None, 1.0))
DEMOGRAPHIC_INCOME_BANDS = ((45_000.0, 0.20), (60_000.0, 0.50), (75_000.0, 0.80), (None, 1.0))
DEMOGRAPHIC_POP_WEIGHT = 0.50
DEMOGRAPHIC_INCOME_WEIGHT = 0.50
VISIBILITY_SCORES = {
    "signalized corner drive-thru": 1.0,
    "corner drive-thru": 1.0,
    "corner": 0.75,
    "drive-thru": 0.75,
    "outparcel": 0.50,
    "out-parcel": 0.50,
    "inline": 0.20,
    "in-line": 0.20,
}
DRIVE_THRU_VISIBILITY_SCORE = VISIBILITY_SCORES["drive-thru"]
PARKING_PRESENT_EQUIVALENT_RATIO = 2.0

UNIT_MIX_SCORES = {"workforce": 1.0, "b/c workforce": 1.0, "class a": 0.40}
CAPEX_QUALITY_SCORES = {"line-itemed bids": 1.0, "line-itemed": 1.0, "generic": 0.60, "missing": 0.10}
OWNERSHIP_SCORES = {"fee simple": 1.0, "tic": 0.60, "dst": 0.60}

FRONTAGE_SCORES = {"corner primary": 1.0, "mid-block primary": 0.75, "secondary": 0.40, "upstairs": 0.0, "basement": 0.0}
PRIMARY_CORNER_MIN_FRONTAGE_FT = 25.0
PRIMARY_MIDBLOCK_MIN_FRONTAGE_FT = 20.0
IRREPLACEABILITY_SCORES = {"historic_downzoned": 1.0, "scarce": 0.75, "standard": 0.30}
HOA_RESERVE_HEALTHY_PCT = 15.0
HOA_SCORES = {"healthy": 1.0, "adequate": 0.60, "underfunded": 0.15}
SIGNAGE_SCORES = {"full": 1.0, "restricted": 0.70, "blocked": 0.10}
PATH_GROWTH_SCORES = {"multiple": 1.0, "one": 0.60, "none": 0.25}
PATH_PROGRESS_SCORES = {"multiple": 1.0, "one": 0.70, "none": 0.30, "negative": 0.05}

LIEN_POSITION_SCORES = {
    "first": 1.0,
    "1st": 1.0,
    "wrap": 0.60,
    "second": 0.25,
    "2nd": 0.25,
    "third": 0.0,
    "3rd": 0.0,
    "third+": 0.0,
    "3rd+": 0.0,
}
JUDICIAL_PROCESS_SCORES = {
    "nonjudicial": 1.0,
    "non-judicial": 1.0,
    "judicial <9m": 0.70,
    "judicial 9-18m": 0.40,
    "judicial >18m": 0.10,
}
BORROWER_ENGAGEMENT_SCORES = {
    "paying": 1.0,
    "modifying": 1.0,
    "contact not paying": 0.60,
    "contacted not paying": 0.60,
    "litigious": 0.20,
}
BACKFILL_1031_SCORES = {
    "identified +15d": 1.0,
    "identified 15+d": 1.0,
    "identified <15d": 0.60,
    "not identified": 0.10,
}
DISTRESS_EXIT_OPTIONALITY_SCORES = {
    "reo": 0.75,
    "bank_owned": 0.75,
    "foreclosure": 0.40,
    "auction": 0.40,
    "tax_sale": 0.40,
}
DISTRESSED_EXIT_FULL_MIN_COUNT = 3.0
DISTRESSED_EXIT_GOOD_MIN_COUNT = 2.0
DISTRESSED_EXIT_SINGLE_MIN_COUNT = 1.0
DISTRESSED_EXIT_FULL_SCORE = 1.0
DISTRESSED_EXIT_GOOD_SCORE = 0.75
DISTRESSED_EXIT_SINGLE_SCORE = 0.40
DISTRESSED_BACKFILL_FULL_MIN_DAYS = 15.0
DISTRESSED_BACKFILL_FULL_SCORE = 1.0
DISTRESSED_BACKFILL_URGENT_SCORE = 0.60
DISTRESSED_BACKFILL_UNIDENTIFIED_SCORE = 0.10
DISTRESSED_OZ_QOF_SCORE = 1.0
DISTRESSED_OZ_ONLY_SCORE = 0.70
DISTRESSED_NO_OZ_SCORE = 0.40
DISTRESSED_SPONSOR_FULL_MIN_DEALS = 10.0
DISTRESSED_SPONSOR_GOOD_MIN_DEALS = 3.0
DISTRESSED_SPONSOR_FULL_MIN_DPI = 1.60
DISTRESSED_SPONSOR_FULL_SCORE = 1.0
DISTRESSED_SPONSOR_GOOD_SCORE = 0.65
DISTRESSED_SPONSOR_THIN_SCORE = 0.25
DISTRESSED_COLLATERAL_DQ_SCORE = 30.0
DISTRESSED_1031_CLOCK_DQ_DAYS = 10.0

DEMAND_GENERATOR_MIN_ANNUAL_VISITS = 500_000.0
DEMAND_GENERATOR_BELOW_MIN_DISTANCE_M = 1_500.000001

SIZE_SWEET_SPOT_MIN_SQFT = 1_300.0
SIZE_SWEET_SPOT_MAX_SQFT = 4_000.0
SIZE_ACCEPTABLE_MIN_SQFT = 800.0
SIZE_ACCEPTABLE_MAX_SQFT = 6_000.0
SIZE_SWEET_SPOT_SCORE = 1.0
SIZE_ACCEPTABLE_SCORE = 0.60
SIZE_OUTSIDE_SCORE = 0.20

DAYS_ON_MARKET_SHORT_MAX = 30.0
DAYS_ON_MARKET_OPTIMAL_MAX = 120.0
DAYS_ON_MARKET_EXTENDED_MAX = 240.0
DAYS_ON_MARKET_SHORT_SCORE = 0.70
DAYS_ON_MARKET_OPTIMAL_SCORE = 1.0
DAYS_ON_MARKET_EXTENDED_SCORE = 0.85
DAYS_ON_MARKET_STALE_SCORE = 0.50
PRICE_REDUCTION_NO_CUT_SCORE = 0.50
PRICE_REDUCTION_ONE_CUT_MIN_PCT = 5.0
PRICE_REDUCTION_ONE_CUT_SCORE = 0.80
PRICE_REDUCTION_MULTI_CUT_COUNT = 2
PRICE_REDUCTION_MULTI_CUT_MIN_PCT = 10.0
PRICE_REDUCTION_MULTI_CUT_SCORE = 1.0
CRIME_SCORES = {"bottom_quartile": 1.0, "below_median": 0.75, "above_median": 0.35, "top_quartile": 0.05}
HAZARD_SCORES = {"low": 1.0, "none": 1.0, "moderate": 0.60, "x-shaded": 0.60, "high": 0.20, "a": 0.20, "ae": 0.20, "extreme": 0.0, "v": 0.0}
TITLE_ENVIRONMENT_SCORES = {"clean": 1.0, "minor": 0.70, "open rec": 0.20}
DEBT_LIQUIDITY_SCORES = {"agency": 1.0, "cmbs": 0.75, "bridge": 0.40, "none": 0.10}

NNN_MIN_LEASE_YEARS = 5.0
NNN_SINGLE_FRANCHISEE_MAX_CAP_PCT = 7.0
VAM_MIN_DSCR = 1.0
VAM_NEGATIVE_ABSORPTION_MAX = 0.0
VAM_PIPELINE_DISQUALIFIER_PCT = 7.0
VAM_DEFERRED_MAINTENANCE_PCT = 25.0
LWL_BOTTOM_QUARTILE_PERCENTILE = 0.25
LWL_SPECIAL_ASSESSMENT_PCT = 20.0
CORE_REQUIRED_FINANCIAL_MONTHS = 24.0
ASSESSOR_LAST_SALE_ANNUAL_INFLATION_RATE = 0.03
DAYS_PER_YEAR = 365.2425

SIGNAL_LABELS = {
    key: key.replace("_", " ").title()
    for key in set(NNN_WEIGHTS)
    | set(VAM_WEIGHTS)
    | set(LWL_WEIGHTS)
    | set(CORE_WEIGHTS)
    | set(DISTRESSED_WEIGHTS)
}

DISQUALIFIER_REASONS = {
    "nnn_short_lease_sub_ig": "Lease is under five years with no renewal option and sub-investment-grade credit.",
    "nnn_single_franchisee_low_cap": "Single-unit franchisee is offered below the minimum seven-percent cap rate.",
    "nnn_environmental_rec": "Environmental review contains an unresolved recognized environmental condition.",
    "nnn_cap_below_tier": "Cap rate is more than 150 basis points below the tenant-credit band.",
    "vam_dscr_below_one": "Year-one DSCR is below 1.0x.",
    "vam_negative_absorption_pipeline": "Negative absorption coincides with a supply pipeline above seven percent.",
    "vam_unpriced_deferred_maintenance": "Deferred maintenance exceeds 25 percent without priced capex.",
    "lwl_not_street_level": "Space is not street-level or lacks a ground-floor entrance.",
    "lwl_bottom_quartile_traffic": "Pedestrian activity is in the bottom quartile.",
    "lwl_special_assessment": "COA special assessment exceeds 20 percent.",
    "lwl_zoning_prohibits_retail": "Current zoning prohibits retail use.",
    "core_title_defect": "Seller cannot deliver clear, insurable title.",
    "core_uninsured_extreme_hazard": "V-zone or active-wildfire exposure lacks an insurance quote.",
    "core_missing_financials": "Seller cannot provide 24 months of financials or an estoppel.",
    "distressed_title_defect": "Title contains an incurable or uninsurable defect.",
    "distressed_junior_lien_default": "Junior lien is exposed to an uncured first-lien default.",
    "distressed_collateral_below_30": "Collateral quality score is below 30.",
    "distressed_1031_clock": "The 1031 clock is under ten days without a signed PSA.",
}


# FREE COMPS & VALUE-ANCHOR POLICY
SALE_COMP_MIN_COUNT = 3
SALE_COMP_QUERY_LIMIT = 250
SALE_COMP_RADIUS_MILES = 5.0
SALE_COMP_RADIUS_METERS = SALE_COMP_RADIUS_MILES * 1_609.344
SALE_COMP_MAX_AGE_YEARS = 5.0
SALE_COMP_MIN_SIZE_RATIO = 0.50
SALE_COMP_MAX_SIZE_RATIO = 2.00
AVM_LOW_PERCENTILE = 0.25
AVM_HIGH_PERCENTILE = 0.75
AVM_MAX_HPI_ADJUSTMENT_YEARS = 10.0
AVM_COUNTY_BASE_CONFIDENCE = 0.60
AVM_COUNTY_CONFIDENCE_PER_EXTRA_COMP = 0.04
AVM_COUNTY_MAX_CONFIDENCE = 0.85
AVM_NO_HPI_CONFIDENCE_PENALTY = 0.10
AVM_FHFA_TREND_CONFIDENCE = 0.35
AVM_FHFA_TREND_ERROR_BAND = 0.25
AVM_LISTING_CONTEXT_MIN_COUNT = 2
AVM_LISTING_CONTEXT_BASE_CONFIDENCE = 0.12
AVM_LISTING_CONTEXT_CONFIDENCE_PER_COMP = 0.02
AVM_LISTING_CONTEXT_MAX_CONFIDENCE = 0.25
AVM_PRICE_ROUNDING_INCREMENT = 1_000.0

REPLACEMENT_COST_REGION_BY_STATE = {
    state: region
    for region, states in {
        "northeast": (
            "CT", "DE", "DC", "ME", "MD", "MA", "NH", "NJ", "NY", "PA",
            "RI", "VT",
        ),
        "south": (
            "AL", "AR", "FL", "GA", "KY", "LA", "MS", "NC", "OK", "SC",
            "TN", "TX", "VA", "WV",
        ),
        "midwest": (
            "IA", "IL", "IN", "KS", "MI", "MN", "MO", "ND", "NE", "OH",
            "SD", "WI",
        ),
        "west": (
            "AK", "AZ", "CA", "CO", "HI", "ID", "MT", "NM", "NV", "OR",
            "UT", "WA", "WY",
        ),
    }.items()
    for state in states
}
REPLACEMENT_COST_PER_SF_BY_REGION = {
    "national": {
        "retail": 240.0,
        "multifamily": 270.0,
        "office": 285.0,
        "industrial": 165.0,
        "hospitality": 300.0,
        "special-purpose": 280.0,
    },
    "northeast": {
        "retail": 285.0,
        "multifamily": 325.0,
        "office": 335.0,
        "industrial": 205.0,
        "hospitality": 350.0,
        "special-purpose": 325.0,
    },
    "south": {
        "retail": 220.0,
        "multifamily": 245.0,
        "office": 260.0,
        "industrial": 150.0,
        "hospitality": 275.0,
        "special-purpose": 255.0,
    },
    "midwest": {
        "retail": 230.0,
        "multifamily": 255.0,
        "office": 270.0,
        "industrial": 155.0,
        "hospitality": 285.0,
        "special-purpose": 265.0,
    },
    "west": {
        "retail": 270.0,
        "multifamily": 310.0,
        "office": 320.0,
        "industrial": 195.0,
        "hospitality": 335.0,
        "special-purpose": 310.0,
    },
}
REPLACEMENT_COST_ESTIMATE_CONFIDENCE = 0.35
AVM_RAW_SOURCE_CONFIDENCE = 1.0


# OFFER & LOI POLICY
# These values are deliberately centralized so the execution layer remains code
# while negotiation posture, buy-box thresholds, and default timelines remain data.
OFFER_TARGET_CAP_PCT_BY_STRATEGY = {
    "core": 7.00,
    "distressed": 9.00,
    "location_retail": 6.50,
    "nnn_retail": 6.50,
    "value_add_multifamily": 6.50,
}
OFFER_WALK_CAP_PCT_BY_STRATEGY = {
    "core": 6.00,
    "distressed": 7.50,
    "location_retail": 5.75,
    "nnn_retail": 5.75,
    "value_add_multifamily": 5.75,
}
OFFER_NNN_TARGET_BAND_POSITION = 0.50
OFFER_NNN_WALK_BAND_POSITION = 0.00
OFFER_TARGET_TREASURY_SPREAD_BPS = 250.0
OFFER_WALK_TREASURY_SPREAD_BPS = 150.0
OFFER_VAM_TARGET_YOC_PCT = 7.50
OFFER_VAM_WALK_YOC_PCT = 6.50
OFFER_OPEN_BUFFER_PCT = 0.03
OFFER_MOTIVATION_BUFFER_PER_SIGNAL_PCT = 0.015
OFFER_MAX_OPEN_BUFFER_PCT = 0.09
OFFER_MOTIVATION_LONG_TENURE_YEARS = 10.0
OFFER_MOTIVATION_DOM_DAYS = 120.0
OFFER_MOTIVATION_PRICE_CUT_COUNT = 1
OFFER_MISSING_NOI_TARGET_DISCOUNT_PCT = 0.03
OFFER_TARGET_MAX_ASK_MULTIPLIER = 1.00
OFFER_WALK_MAX_ASK_MULTIPLIER = 1.00
OFFER_COMP_TARGET_MAX_MULTIPLIER = 1.00
OFFER_COMP_WALK_MAX_MULTIPLIER = 1.05
OFFER_MIN_DSCR_BY_STRATEGY = {
    "core": 1.25,
    "distressed": 1.20,
    "location_retail": 1.25,
    "nnn_retail": 1.25,
    "value_add_multifamily": 1.25,
}
OFFER_TARGET_DSCR_HEADROOM_MULTIPLIER = 0.97
OFFER_TARGET_TO_WALK_MARGIN_PCT = 0.02
OFFER_PRICE_ROUNDING_INCREMENT = 1_000.0
OFFER_CONFIDENCE_WEIGHTS = {
    "ask_price": 0.15,
    "noi": 0.30,
    "underwriting": 0.15,
    "market_context": 0.10,
    "sale_comps": 0.30,
}
OFFER_EARNEST_MONEY_PCT_RANGE = (1.0, 2.0)
OFFER_DD_DAYS_RANGE = (21, 30)
OFFER_CLOSE_DAYS_RANGE = (30, 45)
LOI_DEFAULT_EARNEST_MONEY_PCT = 1.0
LOI_DEFAULT_DD_DAYS = 30
LOI_DEFAULT_CLOSING_DAYS = 45
LOI_DEFAULT_EXPIRATION_DAYS = 3

# COUNTEROFFER COACH POLICY
COUNTER_MAX_EARNEST_MONEY_PCT = OFFER_EARNEST_MONEY_PCT_RANGE[1]
COUNTER_MIN_DD_DAYS = OFFER_DD_DAYS_RANGE[0]
COUNTER_MIN_CLOSE_DAYS = OFFER_CLOSE_DAYS_RANGE[0]
COUNTER_ACCEPT_PRICE_TOLERANCE_PCT = 0.01
COUNTER_PRICE_ROUNDING_INCREMENT = OFFER_PRICE_ROUNDING_INCREMENT
COUNTER_MIN_PLAUSIBLE_PRICE = 100_000.0

# FINANCING & BORROWER-QUALIFICATION POLICY
# These are typical screening assumptions, not lender quotes or program promises.
FINANCING_MIN_AGENCY_UNITS = 5
FINANCING_STABILIZED_OCCUPANCY_PCT = 85.0
FINANCING_CMBS_MIN_VALUE = 2_000_000.0
FINANCING_SBA_EXISTING_OWNER_OCCUPANCY_PCT = 51.0
FINANCING_FALLBACK_RATE_PCT = {
    "treasury_10yr": 4.50,
    "sofr": 4.35,
}
FINANCING_OPTION_LTV_RANGE_PCT = {
    "agency": (65.0, 80.0),
    "bank": (60.0, 75.0),
    "cmbs": (65.0, 75.0),
    "bridge": (60.0, 75.0),
    "sba": (80.0, 90.0),
}
FINANCING_OPTION_RATE_ANCHOR = {
    "agency": "treasury_10yr",
    "bank": "treasury_10yr",
    "cmbs": "treasury_10yr",
    "bridge": "sofr",
    "sba": "treasury_10yr",
}
FINANCING_OPTION_SPREAD_BPS = {
    "agency": 200.0,
    "bank": 300.0,
    "cmbs": 225.0,
    "bridge": 400.0,
    "sba": 350.0,
}
FINANCING_OPTION_AMORT_YEARS = {
    "agency": 30,
    "bank": 25,
    "cmbs": 30,
    "bridge": 30,
    "sba": 25,
}
FINANCING_OPTION_IO_AVAILABLE = {
    "agency": True,
    "bank": False,
    "cmbs": True,
    "bridge": True,
    "sba": False,
}
FINANCING_OPTION_RECOURSE = {
    "agency": "typically non-recourse with standard carve-outs",
    "bank": "typically full or partial recourse",
    "cmbs": "typically non-recourse with standard carve-outs",
    "bridge": "varies; completion and carry guarantees are common",
    "sba": "personal guarantees and available collateral are typically required",
}
FINANCING_DEBT_SCENARIOS = {
    "agency": {
        "ltv": 0.75,
        "rate_anchor": "treasury_10yr",
        "spread_bps": 200.0,
        "amort_years": 30,
        "interest_only": False,
        "min_dscr": 1.25,
    },
    "bank": {
        "ltv": 0.65,
        "rate_anchor": "treasury_10yr",
        "spread_bps": 300.0,
        "amort_years": 25,
        "interest_only": False,
        "min_dscr": 1.25,
    },
    "bridge": {
        "ltv": 0.70,
        "rate_anchor": "sofr",
        "spread_bps": 400.0,
        "amort_years": 30,
        "interest_only": True,
        "min_dscr": 1.10,
    },
}
QUALIFY_CLOSING_COST_PCT = 0.03
QUALIFY_RESERVE_MONTHS = 9
QUALIFY_NET_WORTH_LOAN_RATIO = {
    "agency": 1.00,
    "bank": 0.50,
    "bridge": 0.50,
}
QUALIFY_MIN_EXPERIENCE_DEALS = {
    "agency": 2,
    "bank": 0,
    "bridge": 1,
}
QUALIFY_CREDIT_TIER_RANK = {
    "poor": 0,
    "fair": 1,
    "good": 2,
    "very_good": 3,
    "excellent": 4,
}
QUALIFY_MIN_CREDIT_TIER = {
    "agency": "good",
    "bank": "fair",
    "bridge": "fair",
}
