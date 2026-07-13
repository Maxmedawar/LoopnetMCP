"""Signal extraction and disqualifier predicate registries."""

from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from cre_mcp.enrichment.attributes import parking_ratio
from cre_mcp.enrichment.owner import is_absentee
from cre_mcp.models.deals import DealContext
from cre_mcp.scoring.rubrics import thresholds as T


def _number(ctx: DealContext, key: str) -> float | None:
    value = ctx.listing.raw.get(key)
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _text(ctx: DealContext, key: str) -> str | None:
    value = ctx.listing.raw.get(key)
    return str(value).casefold().strip() if value is not None else None


def _metric_value(metric: Any) -> float | None:
    value = getattr(metric, "value", None)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _category(ctx: DealContext, key: str, scores: dict[str, float]) -> float | None:
    value = _text(ctx, key)
    return scores.get(value) if value is not None else None


def _band_score(
    raw: float,
    bands: tuple[tuple[float | None, float], ...],
    *,
    higher_is_better: bool = True,
) -> float:
    for edge, value in bands:
        if edge is None:
            return value
        if (higher_is_better and raw < edge) or (
            not higher_is_better and raw <= edge
        ):
            return value
    return T.NORMALIZED_MIN


def _credit_rating(ctx: DealContext) -> str | None:
    if ctx.underwriting and ctx.underwriting.tenant_credit_tier:
        return ctx.underwriting.tenant_credit_tier.upper()
    rating = ctx.listing.raw.get("tenant_credit_rating")
    return str(rating).upper() if rating else None


def _credit_score(ctx: DealContext) -> float | None:
    rating = _credit_rating(ctx)
    if rating is None:
        return None
    if rating in T.CREDIT_RATING_SCORES:
        return T.CREDIT_RATING_SCORES[rating]
    if rating.startswith(("B", "C", "D")):
        return T.CREDIT_RATING_SCORES["BELOW"]
    return T.CREDIT_RATING_SCORES["UNRATED"]


def _cap_range(ctx: DealContext) -> tuple[float, float] | None:
    rating = _credit_rating(ctx)
    if rating is None:
        return None
    if rating.startswith(("AAA", "AA")):
        return T.NNN_CAP_RATE_RANGES["AAA_AA"]
    if rating.startswith("A"):
        return T.NNN_CAP_RATE_RANGES["A"]
    if rating.startswith("BBB"):
        return T.NNN_CAP_RATE_RANGES["BBB"]
    return T.NNN_CAP_RATE_RANGES["SUB_IG"]


def tenant_credit_tier(ctx: DealContext) -> float | None:
    return _credit_score(ctx)


def lease_years_remaining(ctx: DealContext) -> float | None:
    return _number(ctx, "lease_years_remaining")


def rent_escalations(ctx: DealContext) -> float | None:
    annual = _number(ctx, "rent_escalation_pct")
    five_year = _number(ctx, "rent_escalation_5yr_pct")
    if annual is not None and annual >= T.RENT_ESCALATION_ANNUAL_FULL_PCT:
        return T.RENT_ESCALATION_FULL_SCORE
    if five_year is not None and five_year >= T.RENT_ESCALATION_FIVE_YEAR_FULL_PCT:
        return T.RENT_ESCALATION_FULL_SCORE
    if annual is not None and annual >= T.RENT_ESCALATION_ANNUAL_GOOD_PCT:
        return T.RENT_ESCALATION_GOOD_SCORE
    if ctx.listing.raw.get("option_bumps") is True:
        return T.RENT_ESCALATION_OPTION_SCORE
    if annual is not None or five_year is not None:
        return T.RENT_ESCALATION_FLAT_SCORE
    return None


def cap_rate_vs_band(ctx: DealContext) -> float | None:
    cap = ctx.underwriting.cap_rate if ctx.underwriting else ctx.listing.cap_rate_pct
    band = _cap_range(ctx)
    if cap is None or band is None:
        return None
    low, high = band
    if cap >= high:
        return T.NNN_CAP_AT_OR_ABOVE_TOP_SCORE
    if cap >= low:
        return T.NNN_CAP_IN_BAND_SCORE
    if cap >= low - T.NNN_CAP_NEAR_BAND_GAP_PCT:
        return T.NNN_CAP_WITHIN_50_BPS_SCORE
    return T.NNN_CAP_TOO_LOW_SCORE


def nnn_purity(ctx: DealContext) -> float | None:
    return _category(ctx, "lease_type", T.NNN_PURITY_SCORES)


def corporate_vs_franchisee(ctx: DealContext) -> float | None:
    guaranty = _text(ctx, "guaranty_type")
    if guaranty in T.GUARANTY_SCORES:
        return T.GUARANTY_SCORES[guaranty]
    units = _number(ctx, "franchisee_units")
    if guaranty and "franchise" in guaranty and units is not None:
        if units >= T.FRANCHISEE_SCALE_MIN_UNITS:
            return T.FRANCHISEE_SCALE_SCORE
        return T.GUARANTY_SCORES["single-unit franchisee"]
    return None


def traffic_count(ctx: DealContext) -> float | None:
    direct = _number(ctx, "traffic_count")
    if direct is not None:
        return direct
    return ctx.attributes.traffic_aadt if ctx.attributes else None


def demographics_3mi(ctx: DealContext) -> float | None:
    population = _number(ctx, "population_3mi")
    income = _number(ctx, "median_income_3mi")
    if population is None or income is None:
        return None
    pop_score = _band_score(population, T.DEMOGRAPHIC_POP_BANDS)
    income_score = _band_score(income, T.DEMOGRAPHIC_INCOME_BANDS)
    return (
        pop_score * T.DEMOGRAPHIC_POP_WEIGHT
        + income_score * T.DEMOGRAPHIC_INCOME_WEIGHT
    )


def visibility_corner(ctx: DealContext) -> float | None:
    direct = _category(ctx, "visibility", T.VISIBILITY_SCORES)
    drive_thru = ctx.attributes.drive_thru if ctx.attributes else None
    if drive_thru is True:
        return max(direct or T.NORMALIZED_MIN, T.DRIVE_THRU_VISIBILITY_SCORE)
    return direct


def parking_adequacy(ctx: DealContext) -> float | None:
    direct = _number(ctx, "parking_ratio")
    if direct is not None:
        return direct
    if ctx.attributes is None:
        return None
    ratio = parking_ratio(ctx.attributes.parking, ctx.attributes.size_sqft)
    if ratio is not None:
        return ratio
    if ctx.attributes.parking:
        return T.PARKING_PRESENT_EQUIVALENT_RATIO
    return None


def price_vs_replacement(ctx: DealContext) -> float | None:
    return ctx.underwriting.price_vs_replacement if ctx.underwriting else None


def residual_value_land(ctx: DealContext) -> float | None:
    land = ctx.parcel.land_value if ctx.parcel else None
    if land is None:
        land = _number(ctx, "land_value")
    price = ctx.listing.price_usd
    return land / price if land is not None and price else None


def co_tenancy_quality(ctx: DealContext) -> float | None:
    return _number(ctx, "credit_anchors")


def rent_gap_to_market(ctx: DealContext) -> float | None:
    direct = _number(ctx, "rent_gap_pct")
    if direct is not None:
        return direct
    market_rent = (
        _metric_value(ctx.rent_comps.market_rent_estimate)
        if ctx.rent_comps
        else None
    )
    current_rent = next(
        (
            value
            for key in (
                "in_place_rent_monthly",
                "current_rent_monthly",
                "average_monthly_rent",
                "rent_per_unit",
                "current_rent",
                "asking_rent",
            )
            if (value := _number(ctx, key)) is not None
        ),
        None,
    )
    if market_rent is None or market_rent <= 0 or current_rent is None:
        return None
    return 100 * (market_rent - current_rent) / market_rent


def price_per_unit_vs_submarket(ctx: DealContext) -> float | None:
    benchmark = _number(ctx, "submarket_price_per_unit")
    actual = ctx.underwriting.price_per_unit if ctx.underwriting else None
    return actual / benchmark if actual is not None and benchmark else None


def price_per_sf_vs_replacement(ctx: DealContext) -> float | None:
    return ctx.underwriting.price_vs_replacement if ctx.underwriting else None


def going_in_cap(ctx: DealContext) -> float | None:
    cap = ctx.underwriting.cap_rate if ctx.underwriting else None
    treasury = _metric_value(ctx.market.treasury_10yr) if ctx.market else None
    return cap - treasury if cap is not None and treasury is not None else None


def stabilized_yoc(ctx: DealContext) -> float | None:
    stabilized_noi = _number(ctx, "stabilized_noi")
    capex = _number(ctx, "renovation_capex")
    price = ctx.listing.price_usd
    going_cap = ctx.underwriting.cap_rate if ctx.underwriting else None
    if stabilized_noi is None or capex is None or price is None or going_cap is None:
        return None
    basis = price + capex
    if basis <= 0:
        return None
    return 100 * stabilized_noi / basis - going_cap


def dscr_year1(ctx: DealContext) -> float | None:
    return ctx.underwriting.dscr if ctx.underwriting else None


def submarket_job_growth_5yr(ctx: DealContext) -> float | None:
    return _metric_value(ctx.market.job_growth_5yr) if ctx.market else None


def submarket_pop_growth_5yr(ctx: DealContext) -> float | None:
    return _metric_value(ctx.market.pop_growth_5yr) if ctx.market else None


def supply_pipeline(ctx: DealContext) -> float | None:
    return _number(ctx, "supply_pipeline_pct")


def unit_mix_bias(ctx: DealContext) -> float | None:
    return _category(ctx, "unit_mix", T.UNIT_MIX_SCORES)


def capex_defensibility(ctx: DealContext) -> float | None:
    return _category(ctx, "capex_quality", T.CAPEX_QUALITY_SCORES)


def one_zero_three_one_fit(ctx: DealContext) -> float | None:
    ownership = _category(ctx, "ownership_structure", T.OWNERSHIP_SCORES)
    if ownership is None:
        return None
    if _text(ctx, "ownership_structure") == "fee simple":
        return ownership if ctx.listing.raw.get("owner_occupied") is False else None
    return ownership


def pedestrian_score_100m(ctx: DealContext) -> float | None:
    return _number(ctx, "pedestrian_percentile")


def street_level_frontage(ctx: DealContext) -> float | None:
    frontage_type = _text(ctx, "frontage_type")
    frontage_ft = _number(ctx, "frontage_ft")
    if frontage_type == "corner primary" and frontage_ft is not None:
        return T.FRONTAGE_SCORES[frontage_type] if frontage_ft >= T.PRIMARY_CORNER_MIN_FRONTAGE_FT else T.FRONTAGE_SCORES["secondary"]
    if frontage_type == "mid-block primary" and frontage_ft is not None:
        return T.FRONTAGE_SCORES[frontage_type] if frontage_ft >= T.PRIMARY_MIDBLOCK_MIN_FRONTAGE_FT else T.FRONTAGE_SCORES["secondary"]
    return T.FRONTAGE_SCORES.get(frontage_type) if frontage_type else None


def micro_location_rank(ctx: DealContext) -> float | None:
    return _number(ctx, "micro_location_percentile")


def demand_generator_proximity(ctx: DealContext) -> float | None:
    visits = _number(ctx, "demand_generator_annual_visits")
    distance = _number(ctx, "demand_generator_distance_m")
    if visits is None or distance is None:
        return None
    if visits < T.DEMAND_GENERATOR_MIN_ANNUAL_VISITS:
        return T.DEMAND_GENERATOR_BELOW_MIN_DISTANCE_M
    return distance


def irreplaceability(ctx: DealContext) -> float | None:
    historic = ctx.listing.raw.get("historic") is True
    downzoned = ctx.listing.raw.get("downzoned") is True
    built_out = ctx.listing.raw.get("built_out") is True
    if historic and downzoned:
        return T.IRREPLACEABILITY_SCORES["historic_downzoned"]
    if historic or downzoned or built_out:
        return T.IRREPLACEABILITY_SCORES["scarce"]
    if any(key in ctx.listing.raw for key in ("historic", "downzoned", "built_out")):
        return T.IRREPLACEABILITY_SCORES["standard"]
    return None


def size_sweet_spot(ctx: DealContext) -> float | None:
    size = ctx.listing.size_sqft_num
    if size is None:
        return None
    if T.SIZE_SWEET_SPOT_MIN_SQFT <= size <= T.SIZE_SWEET_SPOT_MAX_SQFT:
        return T.SIZE_SWEET_SPOT_SCORE
    if (
        T.SIZE_ACCEPTABLE_MIN_SQFT <= size < T.SIZE_SWEET_SPOT_MIN_SQFT
        or T.SIZE_SWEET_SPOT_MAX_SQFT < size <= T.SIZE_ACCEPTABLE_MAX_SQFT
    ):
        return T.SIZE_ACCEPTABLE_SCORE
    return T.SIZE_OUTSIDE_SCORE


def condo_hoa_health(ctx: DealContext) -> float | None:
    status = _text(ctx, "hoa_status")
    reserves = _number(ctx, "hoa_reserves_pct")
    litigation = ctx.listing.raw.get("hoa_litigation")
    retail_friendly = ctx.listing.raw.get("hoa_retail_friendly")
    if reserves is not None and litigation is False and retail_friendly is True:
        if reserves >= T.HOA_RESERVE_HEALTHY_PCT:
            return T.HOA_SCORES["healthy"]
    return T.HOA_SCORES.get(status) if status else None


def income_upside_vs_current_rent(ctx: DealContext) -> float | None:
    return _number(ctx, "income_upside_pct")


def signage_visibility(ctx: DealContext) -> float | None:
    return _category(ctx, "signage", T.SIGNAGE_SCORES)


def path_of_growth_score(ctx: DealContext) -> float | None:
    return _category(ctx, "path_of_growth", T.PATH_GROWTH_SCORES)


def price_per_sf_vs_top_block(ctx: DealContext) -> float | None:
    benchmark = _number(ctx, "top_block_price_per_sf")
    actual = ctx.underwriting.price_per_sf if ctx.underwriting else None
    return actual / benchmark if actual is not None and benchmark else None


def tax_incentive_layer(ctx: DealContext) -> float | None:
    return _number(ctx, "tax_incentive_layers")


def cap_rate_vs_treasury_spread(ctx: DealContext) -> float | None:
    cap = ctx.underwriting.cap_rate if ctx.underwriting else None
    treasury = _metric_value(ctx.market.treasury_10yr) if ctx.market else None
    return (cap - treasury) * 100 if cap is not None and treasury is not None else None


def price_vs_avm(ctx: DealContext) -> float | None:
    avm = _number(ctx, "avm")
    return ctx.listing.price_usd / avm if ctx.listing.price_usd is not None and avm else None


def days_on_market(ctx: DealContext) -> float | None:
    days = _number(ctx, "days_on_market")
    if days is None:
        return None
    if days < T.DAYS_ON_MARKET_SHORT_MAX:
        return T.DAYS_ON_MARKET_SHORT_SCORE
    if days < T.DAYS_ON_MARKET_OPTIMAL_MAX:
        return T.DAYS_ON_MARKET_OPTIMAL_SCORE
    if days <= T.DAYS_ON_MARKET_EXTENDED_MAX:
        return T.DAYS_ON_MARKET_EXTENDED_SCORE
    return T.DAYS_ON_MARKET_STALE_SCORE


def price_reduction_history(ctx: DealContext) -> float | None:
    reductions = ctx.listing.raw.get("price_reductions")
    if reductions is None:
        return None
    if not isinstance(reductions, list):
        return None
    percentages: list[float] = []
    for reduction in reductions:
        value = reduction.get("percent") if isinstance(reduction, dict) else reduction
        try:
            percentages.append(float(value))
        except (TypeError, ValueError):
            continue
    if len(percentages) >= T.PRICE_REDUCTION_MULTI_CUT_COUNT and sum(percentages) >= T.PRICE_REDUCTION_MULTI_CUT_MIN_PCT:
        return T.PRICE_REDUCTION_MULTI_CUT_SCORE
    if percentages and max(percentages) >= T.PRICE_REDUCTION_ONE_CUT_MIN_PCT:
        return T.PRICE_REDUCTION_ONE_CUT_SCORE
    return T.PRICE_REDUCTION_NO_CUT_SCORE


def msa_job_growth_36mo(ctx: DealContext) -> float | None:
    return _number(ctx, "job_growth_36mo_pct")


def msa_population_growth_36mo(ctx: DealContext) -> float | None:
    return _number(ctx, "population_growth_36mo_pct")


def msa_median_hh_income(ctx: DealContext) -> float | None:
    income = _metric_value(ctx.market.median_hh_income) if ctx.market else None
    us_income = _number(ctx, "us_median_hh_income")
    return income / us_income if income is not None and us_income else None


def supply_pipeline_ratio(ctx: DealContext) -> float | None:
    direct = _number(ctx, "supply_pipeline_pct")
    if direct is not None:
        return direct
    permits = _metric_value(ctx.market.permits_trailing_12m) if ctx.market else None
    stock = _number(ctx, "housing_stock_units")
    return 100 * permits / stock if permits is not None and stock else None


def crime_index(ctx: DealContext) -> float | None:
    return _category(ctx, "crime_quartile", T.CRIME_SCORES)


def flood_wildfire_risk(ctx: DealContext) -> float | None:
    return _category(ctx, "hazard_risk", T.HAZARD_SCORES)


def assessor_last_sale_delta(ctx: DealContext) -> float | None:
    parcel_sale = ctx.parcel.last_sale_price if ctx.parcel else None
    last_sale = parcel_sale if parcel_sale is not None else _number(ctx, "last_sale_price")
    if ctx.listing.price_usd is None or not last_sale:
        return None
    sale_date = ctx.parcel.last_sale_date if ctx.parcel else None
    if sale_date is None:
        raw_date = ctx.listing.raw.get("last_sale_date")
        sale_date = str(raw_date) if raw_date not in (None, "") else None
    years = _years_since(sale_date)
    if years is None:
        return ctx.listing.price_usd / last_sale if parcel_sale is None else None
    adjusted_sale = last_sale * (
        (1 + T.ASSESSOR_LAST_SALE_ANNUAL_INFLATION_RATE) ** years
    )
    return ctx.listing.price_usd / adjusted_sale if adjusted_sale > 0 else None


def _date_value(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    try:
        if text.isdigit():
            timestamp = float(text)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except (OSError, OverflowError, ValueError):
        for fmt in ("%m/%d/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _years_since(value: str | None) -> float | None:
    parsed = _date_value(value)
    if parsed is None or parsed > date.today():
        return None
    return (date.today() - parsed).days / T.DAYS_PER_YEAR


def owner_absentee(ctx: DealContext) -> float | None:
    if ctx.parcel is None:
        return None
    absentee = is_absentee(ctx.parcel)
    return float(absentee) if absentee is not None else None


def owner_tenure_years(ctx: DealContext) -> float | None:
    return _years_since(ctx.parcel.last_sale_date) if ctx.parcel else None


def title_environmental_clean(ctx: DealContext) -> float | None:
    return _category(ctx, "title_environmental_status", T.TITLE_ENVIRONMENT_SCORES)


def debt_market_liquidity(ctx: DealContext) -> float | None:
    return _category(ctx, "debt_liquidity", T.DEBT_LIQUIDITY_SCORES)


def path_of_progress_score(ctx: DealContext) -> float | None:
    return _category(ctx, "path_of_progress", T.PATH_PROGRESS_SCORES)


def sanity_dscr(ctx: DealContext) -> float | None:
    return ctx.underwriting.dscr if ctx.underwriting else None


def _distressed_value(ctx: DealContext) -> float | None:
    for key in ("bpo", "avm", "assessed_value"):
        value = _number(ctx, key)
        if value is not None and value > 0:
            return value
    return None


def discount_to_upb(ctx: DealContext) -> float | None:
    direct = _number(ctx, "discount_to_upb")
    if direct is not None:
        return direct
    upb = _number(ctx, "upb")
    return (
        ctx.listing.price_usd / upb
        if ctx.listing.price_usd is not None and upb
        else None
    )


def discount_to_bpo(ctx: DealContext) -> float | None:
    direct = _number(ctx, "discount_to_bpo")
    if direct is not None:
        return direct
    value = _distressed_value(ctx)
    return (
        ctx.listing.price_usd / value
        if ctx.listing.price_usd is not None and value
        else None
    )


def ltv_at_entry(ctx: DealContext) -> float | None:
    direct = _number(ctx, "ltv_at_entry")
    if direct is not None:
        return direct
    value = _distressed_value(ctx)
    basis = _number(ctx, "entry_basis")
    if basis is None:
        basis = ctx.listing.price_usd
    return basis / value if basis is not None and value else None


def lien_position(ctx: DealContext) -> float | None:
    return _category(ctx, "lien_position", T.LIEN_POSITION_SCORES)


def judicial_vs_nonjudicial_state(ctx: DealContext) -> float | None:
    return _category(ctx, "foreclosure_process", T.JUDICIAL_PROCESS_SCORES)


def borrower_engagement(ctx: DealContext) -> float | None:
    return _category(ctx, "borrower_engagement", T.BORROWER_ENGAGEMENT_SCORES)


def collateral_quality_carryover(ctx: DealContext) -> float | None:
    value = _number(ctx, "collateral_score")
    if value is None:
        return None
    return value / T.SCORE_SCALE if value > T.NORMALIZED_MAX else value


def exit_optionality(ctx: DealContext) -> float | None:
    exits = _number(ctx, "underwritten_exit_count")
    if exits is not None:
        if (
            exits >= T.DISTRESSED_EXIT_FULL_MIN_COUNT
            and ctx.listing.raw.get("exit_irr_underwritten") is True
        ):
            return T.DISTRESSED_EXIT_FULL_SCORE
        if exits >= T.DISTRESSED_EXIT_GOOD_MIN_COUNT:
            return T.DISTRESSED_EXIT_GOOD_SCORE
        if exits >= T.DISTRESSED_EXIT_SINGLE_MIN_COUNT:
            return T.DISTRESSED_EXIT_SINGLE_SCORE
        return T.NORMALIZED_MIN
    distress_type = (ctx.listing.distress_type or "").casefold()
    return T.DISTRESS_EXIT_OPTIONALITY_SCORES.get(distress_type) or None


def one_zero_three_one_backfill_readiness(ctx: DealContext) -> float | None:
    category = _text(ctx, "1031_backfill_status")
    if category:
        return T.BACKFILL_1031_SCORES.get(category)
    identified = ctx.listing.raw.get("1031_replacement_identified")
    days = _number(ctx, "1031_days_remaining")
    if identified is True and days is not None:
        return (
            T.DISTRESSED_BACKFILL_FULL_SCORE
            if days >= T.DISTRESSED_BACKFILL_FULL_MIN_DAYS
            else T.DISTRESSED_BACKFILL_URGENT_SCORE
        )
    if identified is False:
        return T.DISTRESSED_BACKFILL_UNIDENTIFIED_SCORE
    return None


def oz_qof_layer(ctx: DealContext) -> float | None:
    oz = ctx.listing.raw.get("opportunity_zone")
    if oz is None:
        oz = ctx.listing.raw.get("isInOpportunityZone")
    qof = ctx.listing.raw.get("qof_layer")
    if oz is True and qof is True:
        return T.DISTRESSED_OZ_QOF_SCORE
    if oz is True:
        return T.DISTRESSED_OZ_ONLY_SCORE
    if oz is False:
        return T.DISTRESSED_NO_OZ_SCORE
    return None


def sponsor_track_record(ctx: DealContext) -> float | None:
    deals = _number(ctx, "sponsor_deals")
    dpi = _number(ctx, "sponsor_dpi")
    if deals is None:
        return None
    if (
        deals >= T.DISTRESSED_SPONSOR_FULL_MIN_DEALS
        and dpi is not None
        and dpi >= T.DISTRESSED_SPONSOR_FULL_MIN_DPI
    ):
        return T.DISTRESSED_SPONSOR_FULL_SCORE
    if deals >= T.DISTRESSED_SPONSOR_GOOD_MIN_DEALS:
        return T.DISTRESSED_SPONSOR_GOOD_SCORE
    return T.DISTRESSED_SPONSOR_THIN_SCORE


def _nnn_short_lease_sub_ig(ctx: DealContext) -> bool:
    years = lease_years_remaining(ctx)
    credit = _credit_score(ctx)
    options = ctx.listing.raw.get("renewal_options")
    return bool(years is not None and years < T.NNN_MIN_LEASE_YEARS and options is False and credit is not None and credit <= T.SUB_INVESTMENT_GRADE_MAX_SCORE)


def _nnn_single_franchisee_low_cap(ctx: DealContext) -> bool:
    guaranty = _text(ctx, "guaranty_type")
    cap = ctx.underwriting.cap_rate if ctx.underwriting else ctx.listing.cap_rate_pct
    return bool(guaranty == "single-unit franchisee" and cap is not None and cap < T.NNN_SINGLE_FRANCHISEE_MAX_CAP_PCT)


def _nnn_environmental_rec(ctx: DealContext) -> bool:
    return _text(ctx, "environmental_status") == "unresolved rec"


def _nnn_cap_below_tier(ctx: DealContext) -> bool:
    band = _cap_range(ctx)
    cap = ctx.underwriting.cap_rate if ctx.underwriting else ctx.listing.cap_rate_pct
    return bool(band is not None and cap is not None and cap < band[0] - T.NNN_CAP_DISQUALIFIER_GAP_PCT)


def _vam_dscr_below_one(ctx: DealContext) -> bool:
    value = ctx.underwriting.dscr if ctx.underwriting else None
    return bool(value is not None and value < T.VAM_MIN_DSCR)


def _vam_negative_absorption_pipeline(ctx: DealContext) -> bool:
    absorption = _number(ctx, "absorption_pct")
    pipeline = _number(ctx, "supply_pipeline_pct")
    return bool(absorption is not None and pipeline is not None and absorption < T.VAM_NEGATIVE_ABSORPTION_MAX and pipeline > T.VAM_PIPELINE_DISQUALIFIER_PCT)


def _vam_unpriced_deferred_maintenance(ctx: DealContext) -> bool:
    deferred = _number(ctx, "deferred_maintenance_pct")
    priced = ctx.listing.raw.get("capex_priced")
    return bool(deferred is not None and deferred > T.VAM_DEFERRED_MAINTENANCE_PCT and priced is False)


def _lwl_not_street_level(ctx: DealContext) -> bool:
    return ctx.listing.raw.get("street_level") is False or ctx.listing.raw.get("ground_floor_entrance") is False


def _lwl_bottom_quartile_traffic(ctx: DealContext) -> bool:
    value = pedestrian_score_100m(ctx)
    return bool(value is not None and value < T.LWL_BOTTOM_QUARTILE_PERCENTILE)


def _lwl_special_assessment(ctx: DealContext) -> bool:
    value = _number(ctx, "special_assessment_pct")
    return bool(value is not None and value > T.LWL_SPECIAL_ASSESSMENT_PCT)


def _lwl_zoning_prohibits_retail(ctx: DealContext) -> bool:
    return ctx.listing.raw.get("zoning_allows_retail") is False


def _core_title_defect(ctx: DealContext) -> bool:
    return ctx.listing.raw.get("title_clear") is False


def _core_uninsured_extreme_hazard(ctx: DealContext) -> bool:
    hazard = _text(ctx, "hazard_risk")
    active_wildfire = ctx.listing.raw.get("active_wildfire") is True
    insurance = ctx.listing.raw.get("insurance_quote")
    return bool((hazard in {"v", "v-zone", "extreme"} or active_wildfire) and insurance is False)


def _core_missing_financials(ctx: DealContext) -> bool:
    can_provide = ctx.listing.raw.get("seller_can_provide_financials")
    months = _number(ctx, "seller_financial_months")
    estoppel = ctx.listing.raw.get("estoppel_available")
    return bool(can_provide is False or (months is not None and months < T.CORE_REQUIRED_FINANCIAL_MONTHS and estoppel is False))


def _distressed_title_defect(ctx: DealContext) -> bool:
    return (
        ctx.listing.raw.get("title_clear") is False
        or ctx.listing.raw.get("title_defect") is True
    )


def _distressed_junior_lien_default(ctx: DealContext) -> bool:
    position = _text(ctx, "lien_position")
    junior = position in {"second", "2nd", "third", "3rd", "third+", "3rd+"}
    return bool(
        junior
        and ctx.listing.raw.get("first_lien_default") is True
        and ctx.listing.raw.get("first_lien_cure") is not True
    )


def _distressed_collateral_below_30(ctx: DealContext) -> bool:
    value = _number(ctx, "collateral_score")
    if value is not None and value <= T.NORMALIZED_MAX:
        value *= T.SCORE_SCALE
    return bool(value is not None and value < T.DISTRESSED_COLLATERAL_DQ_SCORE)


def _distressed_1031_clock(ctx: DealContext) -> bool:
    days = _number(ctx, "1031_days_remaining")
    return bool(
        days is not None
        and days < T.DISTRESSED_1031_CLOCK_DQ_DAYS
        and ctx.listing.raw.get("signed_psa") is not True
    )


SIGNAL_EXTRACTORS: dict[str, Callable[[DealContext], float | None]] = {
    "tenant_credit_tier": tenant_credit_tier,
    "lease_years_remaining": lease_years_remaining,
    "rent_escalations": rent_escalations,
    "cap_rate_vs_band": cap_rate_vs_band,
    "nnn_purity": nnn_purity,
    "corporate_vs_franchisee": corporate_vs_franchisee,
    "traffic_count": traffic_count,
    "demographics_3mi": demographics_3mi,
    "visibility_corner": visibility_corner,
    "parking_adequacy": parking_adequacy,
    "price_vs_replacement": price_vs_replacement,
    "residual_value_land": residual_value_land,
    "co_tenancy_quality": co_tenancy_quality,
    "rent_gap_to_market": rent_gap_to_market,
    "price_per_unit_vs_submarket": price_per_unit_vs_submarket,
    "price_per_sf_vs_replacement": price_per_sf_vs_replacement,
    "going_in_cap": going_in_cap,
    "stabilized_yoc": stabilized_yoc,
    "dscr_year1": dscr_year1,
    "submarket_job_growth_5yr": submarket_job_growth_5yr,
    "submarket_pop_growth_5yr": submarket_pop_growth_5yr,
    "supply_pipeline": supply_pipeline,
    "unit_mix_bias": unit_mix_bias,
    "capex_defensibility": capex_defensibility,
    "1031_fit": one_zero_three_one_fit,
    "pedestrian_score_100m": pedestrian_score_100m,
    "street_level_frontage": street_level_frontage,
    "micro_location_rank": micro_location_rank,
    "demand_generator_proximity": demand_generator_proximity,
    "irreplaceability": irreplaceability,
    "size_sweet_spot": size_sweet_spot,
    "condo_hoa_health": condo_hoa_health,
    "income_upside_vs_current_rent": income_upside_vs_current_rent,
    "signage_visibility": signage_visibility,
    "path_of_growth_score": path_of_growth_score,
    "price_per_sf_vs_top_block": price_per_sf_vs_top_block,
    "tax_incentive_layer": tax_incentive_layer,
    "cap_rate_vs_treasury_spread": cap_rate_vs_treasury_spread,
    "price_vs_avm": price_vs_avm,
    "days_on_market": days_on_market,
    "price_reduction_history": price_reduction_history,
    "msa_job_growth_36mo": msa_job_growth_36mo,
    "msa_population_growth_36mo": msa_population_growth_36mo,
    "msa_median_hh_income": msa_median_hh_income,
    "supply_pipeline_ratio": supply_pipeline_ratio,
    "crime_index": crime_index,
    "flood_wildfire_risk": flood_wildfire_risk,
    "assessor_last_sale_delta": assessor_last_sale_delta,
    "owner_absentee": owner_absentee,
    "owner_tenure_years": owner_tenure_years,
    "title_environmental_clean": title_environmental_clean,
    "debt_market_liquidity": debt_market_liquidity,
    "path_of_progress_score": path_of_progress_score,
    "sanity_dscr": sanity_dscr,
    "discount_to_upb": discount_to_upb,
    "discount_to_bpo": discount_to_bpo,
    "ltv_at_entry": ltv_at_entry,
    "lien_position": lien_position,
    "judicial_vs_nonjudicial_state": judicial_vs_nonjudicial_state,
    "borrower_engagement": borrower_engagement,
    "collateral_quality_carryover": collateral_quality_carryover,
    "exit_optionality": exit_optionality,
    "1031_backfill_readiness": one_zero_three_one_backfill_readiness,
    "oz_qof_layer": oz_qof_layer,
    "sponsor_track_record": sponsor_track_record,
}

DISQUALIFIER_PREDICATES: dict[str, Callable[[DealContext], bool]] = {
    "nnn_short_lease_sub_ig": _nnn_short_lease_sub_ig,
    "nnn_single_franchisee_low_cap": _nnn_single_franchisee_low_cap,
    "nnn_environmental_rec": _nnn_environmental_rec,
    "nnn_cap_below_tier": _nnn_cap_below_tier,
    "vam_dscr_below_one": _vam_dscr_below_one,
    "vam_negative_absorption_pipeline": _vam_negative_absorption_pipeline,
    "vam_unpriced_deferred_maintenance": _vam_unpriced_deferred_maintenance,
    "lwl_not_street_level": _lwl_not_street_level,
    "lwl_bottom_quartile_traffic": _lwl_bottom_quartile_traffic,
    "lwl_special_assessment": _lwl_special_assessment,
    "lwl_zoning_prohibits_retail": _lwl_zoning_prohibits_retail,
    "core_title_defect": _core_title_defect,
    "core_uninsured_extreme_hazard": _core_uninsured_extreme_hazard,
    "core_missing_financials": _core_missing_financials,
    "distressed_title_defect": _distressed_title_defect,
    "distressed_junior_lien_default": _distressed_junior_lien_default,
    "distressed_collateral_below_30": _distressed_collateral_below_30,
    "distressed_1031_clock": _distressed_1031_clock,
}
