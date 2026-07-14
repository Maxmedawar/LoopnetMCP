"""Honest, coverage-aware value ranges from free county and fallback data."""

from __future__ import annotations

import math
from datetime import date
from statistics import median
from typing import Any

from cre_mcp.models.comps import SaleComp, ValueEstimate
from cre_mcp.models.listings import Listing
from cre_mcp.models.market import MarketPack
from cre_mcp.scoring.rubrics import thresholds as T


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _round_value(value: float) -> float:
    increment = T.AVM_PRICE_ROUNDING_INCREMENT
    return round(value / increment) * increment if value >= increment else round(value, 2)


def _years_since(value: str | None) -> float | None:
    if not value:
        return None
    try:
        observed = date.fromisoformat(value[:10])
    except ValueError:
        return None
    elapsed = (date.today() - observed).days / T.DAYS_PER_YEAR
    return max(0.0, min(elapsed, T.AVM_MAX_HPI_ADJUSTMENT_YEARS))


def _hpi_rate(market: MarketPack | None) -> float | None:
    metric = market.fhfa_hpi_growth_1yr if market else None
    value = _number(metric.value) if metric else None
    return value if value is not None and value > -100 else None


def _adjusted_price(
    comp: SaleComp,
    market: MarketPack | None,
) -> tuple[float, bool]:
    if comp.time_adjusted_price is not None and comp.time_adjusted_price > 0:
        return comp.time_adjusted_price, True
    rate = _hpi_rate(market)
    years = _years_since(comp.sale_date)
    if rate is None or years is None:
        return comp.sale_price, False
    return comp.sale_price * (1 + rate / 100) ** years, True


def _county_indications(
    subject: Listing,
    comps: list[SaleComp],
    market: MarketPack | None,
) -> tuple[list[float], bool, str] | None:
    multifamily = "multifamily" in (subject.property_type or "").casefold()
    indications: list[float] = []
    all_adjusted = True
    basis = "price/SF"
    for comp in comps:
        adjusted, was_adjusted = _adjusted_price(comp, market)
        if multifamily and subject.units and comp.units:
            indications.append(adjusted / comp.units * subject.units)
            basis = "price/unit"
        elif subject.size_sqft_num and comp.sqft:
            indications.append(adjusted / comp.sqft * subject.size_sqft_num)
        else:
            continue
        all_adjusted = all_adjusted and was_adjusted
    if len(indications) < T.SALE_COMP_MIN_COUNT:
        return None
    return indications, all_adjusted, basis


def _range_estimate(
    values: list[float],
) -> tuple[float, float, float, float]:
    low = _percentile(values, T.AVM_LOW_PERCENTILE)
    mid = median(values)
    high = _percentile(values, T.AVM_HIGH_PERCENTILE)
    error_band = (high - low) / (2 * mid) if mid > 0 else 0.0
    return (
        _round_value(low),
        _round_value(mid),
        _round_value(high),
        round(max(0.0, error_band), 4),
    )


def _county_estimate(
    subject: Listing,
    comps: list[SaleComp],
    market: MarketPack | None,
) -> ValueEstimate | None:
    result = _county_indications(subject, comps, market)
    if result is None:
        return None
    values, all_adjusted, basis = result
    low, mid, high, error_band = _range_estimate(values)
    confidence = min(
        T.AVM_COUNTY_MAX_CONFIDENCE,
        T.AVM_COUNTY_BASE_CONFIDENCE
        + max(0, len(values) - T.SALE_COMP_MIN_COUNT)
        * T.AVM_COUNTY_CONFIDENCE_PER_EXTRA_COMP,
    )
    if not all_adjusted:
        confidence -= T.AVM_NO_HPI_CONFIDENCE_PENALTY
    adjustment = (
        "FHFA's residential-market HPI proxy or county time-adjusted prices"
        if all_adjusted
        else "nominal sale prices because FHFA adjustment was unavailable"
    )
    return ValueEstimate(
        value=mid,
        low=low,
        mid=mid,
        high=high,
        method="county_comps",
        n_comps=len(values),
        confidence=round(max(0.0, confidence), 4),
        error_band=error_band,
        as_of=date.today().isoformat(),
        source=(
            f"County-limited public arm's-length candidates using {basis}; {adjustment}."
        ),
    )


def _raw_value(subject: Listing, *keys: str) -> float | None:
    return next(
        (
            value
            for key in keys
            if (value := _number(subject.raw.get(key))) is not None and value > 0
        ),
        None,
    )


def _fhfa_estimate(
    subject: Listing,
    market: MarketPack | None,
) -> ValueEstimate | None:
    last_sale = _raw_value(subject, "last_sale_price", "prior_sale_price")
    raw_date = subject.raw.get("last_sale_date") or subject.raw.get("prior_sale_date")
    years = _years_since(str(raw_date)) if raw_date else None
    rate = _hpi_rate(market)
    if last_sale is None or years is None or rate is None:
        return None
    mid = _round_value(last_sale * (1 + rate / 100) ** years)
    error = T.AVM_FHFA_TREND_ERROR_BAND
    low = _round_value(mid * (1 - error))
    high = _round_value(mid * (1 + error))
    return ValueEstimate(
        value=mid,
        low=low,
        mid=mid,
        high=high,
        method="fhfa_trend",
        confidence=T.AVM_FHFA_TREND_CONFIDENCE,
        error_band=error,
        as_of=date.today().isoformat(),
        source=(
            "Weaker nationwide fallback: subject's prior sale trended by FHFA's "
            "residential-market one-year HPI proxy; not a property-level appraisal."
        ),
    )


def _listing_prices(subject: Listing) -> list[float]:
    prices: list[float] = []
    rows: list[Any] = []
    for key in (
        "listing_context_prices",
        "asking_price_comps",
        "comparable_listings",
    ):
        value = subject.raw.get(key)
        if isinstance(value, list):
            rows.extend(value)
    for row in rows:
        if isinstance(row, dict):
            price = _number(
                row.get("price_usd") or row.get("asking_price") or row.get("price")
            )
            size = _number(row.get("size_sqft_num") or row.get("size_sqft"))
            units = _number(row.get("units"))
            if price and subject.units and units:
                price = price / units * subject.units
            elif price and subject.size_sqft_num and size:
                price = price / size * subject.size_sqft_num
        else:
            price = _number(row)
        if price is not None and price > 0:
            prices.append(price)
    return prices


def _listing_estimate(subject: Listing) -> ValueEstimate | None:
    prices = _listing_prices(subject)
    if len(prices) < T.AVM_LISTING_CONTEXT_MIN_COUNT:
        return None
    low, mid, high, error_band = _range_estimate(prices)
    confidence = min(
        T.AVM_LISTING_CONTEXT_MAX_CONFIDENCE,
        T.AVM_LISTING_CONTEXT_BASE_CONFIDENCE
        + len(prices) * T.AVM_LISTING_CONTEXT_CONFIDENCE_PER_COMP,
    )
    return ValueEstimate(
        value=mid,
        low=low,
        mid=mid,
        high=high,
        method="listing_context",
        n_comps=len(prices),
        confidence=round(confidence, 4),
        error_band=error_band,
        as_of=date.today().isoformat(),
        source=(
            "Weak asking-price context from scraped comparable listings, not closed "
            "sales; free county sales coverage was insufficient."
        ),
    )


def estimate_value(
    subject: Listing,
    comps: list[SaleComp],
    market: MarketPack | None,
) -> ValueEstimate:
    """Estimate value through county comps, then explicitly weaker fallbacks."""
    return (
        _county_estimate(subject, comps, market)
        or _fhfa_estimate(subject, market)
        or _listing_estimate(subject)
        or ValueEstimate(
            value=None,
            method="none",
            confidence=0.0,
            as_of=date.today().isoformat(),
            source=(
                "No usable county sale comps, FHFA-trendable prior sale, or scraped "
                "asking-price context was available."
            ),
        )
    )


__all__ = ["estimate_value"]
