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

NNN_WEIGHTS = {
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

CORE_WEIGHTS = {
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
    "sanity_dscr": ((1.15, 0.0), (1.25, 0.45), (1.35, 0.80), (None, 1.0)),
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
    "absolute nnn": 1.0,
    "absolute-net": 1.0,
    "nnn": 0.90,
    "triple net": 0.90,
    "nn": 0.60,
    "double net": 0.60,
    "modified gross": 0.20,
}
GUARANTY_SCORES = {
    "corporate investment grade": 1.0,
    "corporate ig": 1.0,
    "corporate sub-investment grade": 0.70,
    "corporate sub-ig": 0.70,
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

SIGNAL_LABELS = {key: key.replace("_", " ").title() for key in set(NNN_WEIGHTS) | set(VAM_WEIGHTS) | set(LWL_WEIGHTS) | set(CORE_WEIGHTS)}

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
}
