"""Transparent retail sales-capacity and sustainable-rent conventions.

This module is an initial screening aid, not a forecast of a particular tenant's
sales or a representation that a tenant will accept a rent.  All benchmark
numbers below are category conventions and must be replaced with tenant-reported
sales, an FDD, or another tenant-specific source before an investment decision.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from numbers import Real
from typing import Any


CONVENTION_NOTE = "category convention, verify w/ tenant-reported sales"

# These ranges deliberately remain a compact, auditable table.  They synthesize
# common U.S. retail-leasing screening practice rather than claiming to reproduce
# a proprietary survey or a statement from any particular tenant.
CATEGORY_CONVENTIONS: dict[str, dict[str, Any]] = {
    "grocery": {
        "sales_psf": (450.0, 750.0),
        "healthy_ocr": (0.02, 0.04),
        "percentage_rent_rate": (0.01, 0.025),
        "sources": (
            "ICSC retail sales-productivity and occupancy-cost survey conventions",
            "Public grocer filings and U.S. grocery leasing practice (category synthesis)",
        ),
        "label": CONVENTION_NOTE,
    },
    "qsr": {
        "sales_psf": (500.0, 900.0),
        "healthy_ocr": (0.06, 0.10),
        "percentage_rent_rate": (0.04, 0.07),
        "sources": (
            "Franchise FDD average-unit-volume disclosures (category synthesis)",
            "ICSC restaurant occupancy-cost convention ranges",
        ),
        "label": CONVENTION_NOTE,
    },
    "coffee": {
        "sales_psf": (550.0, 1_000.0),
        "healthy_ocr": (0.08, 0.12),
        "percentage_rent_rate": (0.05, 0.08),
        "sources": (
            "Public coffee-chain filings and franchise FDD disclosures (category synthesis)",
            "U.S. retail leasing occupancy-cost conventions",
        ),
        "label": CONVENTION_NOTE,
    },
    "fitness": {
        "sales_psf": (120.0, 260.0),
        "healthy_ocr": (0.10, 0.16),
        "percentage_rent_rate": (0.06, 0.10),
        "sources": (
            "Public fitness-club filings and industry unit-economics conventions",
            "U.S. retail leasing occupancy-cost conventions",
        ),
        "label": CONVENTION_NOTE,
    },
    "pharmacy": {
        "sales_psf": (300.0, 650.0),
        "healthy_ocr": (0.025, 0.05),
        "percentage_rent_rate": (0.02, 0.04),
        "sources": (
            "Public drugstore filings and retail sales-productivity conventions",
            "ICSC occupancy-cost convention ranges",
        ),
        "label": CONVENTION_NOTE,
    },
    "dollar": {
        "sales_psf": (180.0, 300.0),
        "healthy_ocr": (0.04, 0.07),
        "percentage_rent_rate": (0.03, 0.05),
        "sources": (
            "Public dollar-store filings and retail sales-productivity conventions",
            "U.S. net-lease occupancy-cost conventions",
        ),
        "label": CONVENTION_NOTE,
    },
    "sit-down": {
        "sales_psf": (350.0, 700.0),
        "healthy_ocr": (0.06, 0.10),
        "percentage_rent_rate": (0.04, 0.07),
        "sources": (
            "National Restaurant Association operating conventions and public filings (category synthesis)",
            "ICSC restaurant occupancy-cost convention ranges",
        ),
        "label": CONVENTION_NOTE,
    },
    "soft goods": {
        "sales_psf": (250.0, 550.0),
        "healthy_ocr": (0.08, 0.13),
        "percentage_rent_rate": (0.05, 0.08),
        "sources": (
            "Public apparel/specialty-retail filings and sales-productivity conventions",
            "ICSC occupancy-cost convention ranges",
        ),
        "label": CONVENTION_NOTE,
    },
}


_CATEGORY_ALIASES = {
    "grocery store": "grocery",
    "grocer": "grocery",
    "supermarket": "grocery",
    "quick service": "qsr",
    "quick service restaurant": "qsr",
    "fast food": "qsr",
    "fast casual": "qsr",
    "cafe": "coffee",
    "coffee shop": "coffee",
    "gym": "fitness",
    "health club": "fitness",
    "drugstore": "pharmacy",
    "drug store": "pharmacy",
    "dollar store": "dollar",
    "discount variety": "dollar",
    "sit down": "sit-down",
    "full service restaurant": "sit-down",
    "casual dining": "sit-down",
    "restaurant": "sit-down",
    "soft good": "soft goods",
    "apparel": "soft goods",
    "clothing": "soft goods",
    "specialty retail": "soft goods",
}


def _normalized_category(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("category must be a non-empty string")
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    normalized = _CATEGORY_ALIASES.get(normalized, normalized)
    if normalized not in CATEGORY_CONVENTIONS:
        supported = ", ".join(CATEGORY_CONVENTIONS)
        raise ValueError(f"unsupported category {value!r}; supported categories: {supported}")
    return normalized


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def _optional_nonnegative(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite non-negative number when provided")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a finite non-negative number when provided")
    return number


def _positive(value: Any, name: str) -> float:
    number = _optional_nonnegative(value, name)
    if number is None or number <= 0:
        raise ValueError(f"{name} must be a finite number greater than zero")
    return number


def _range(
    low: float,
    high: float,
    *,
    unit: str,
    derived: bool = False,
) -> dict[str, Any]:
    return {
        "low": round(low, 2),
        "high": round(high, 2),
        "unit": unit,
        "basis": "derived from category conventions" if derived else "category convention",
        "source_note": CONVENTION_NOTE,
    }


def tenant_sales_capacity(
    category: str,
    trade_area: Mapping[str, Any],
    unit: Mapping[str, Any],
) -> dict[str, Any]:
    """Screen sales capacity, occupancy cost, rent, and percentage breakpoint.

    ``trade_area`` accepts optional ``population``, ``median_income``, and
    ``traffic_aadt`` values.  Those facts are retained as caller-provided context
    but do not silently modify the category convention.  ``unit`` must contain a
    positive ``sf`` value.

    The sustainable-rent outer range is calculated as::

        low sales/sf * sf * low healthy OCR
        high sales/sf * sf * high healthy OCR

    With no negotiated base rent or percentage rate in the input, the natural
    breakpoint is necessarily illustrative.  Its outer range uses the category
    percentage-rent convention and the calculated sustainable base-rent range.
    """

    normalized = _normalized_category(category)
    trade_area_map = _mapping(trade_area, "trade_area")
    unit_map = _mapping(unit, "unit")
    sf = _positive(unit_map.get("sf"), "unit.sf")

    context = {
        "population": _optional_nonnegative(
            trade_area_map.get("population"), "trade_area.population"
        ),
        "median_income": _optional_nonnegative(
            trade_area_map.get("median_income"), "trade_area.median_income"
        ),
        "traffic_aadt": _optional_nonnegative(
            trade_area_map.get("traffic_aadt"), "trade_area.traffic_aadt"
        ),
    }

    convention = CATEGORY_CONVENTIONS[normalized]
    sales_low, sales_high = convention["sales_psf"]
    ocr_low, ocr_high = convention["healthy_ocr"]
    percentage_low, percentage_high = convention["percentage_rent_rate"]

    annual_sales_low = sales_low * sf
    annual_sales_high = sales_high * sf
    annual_rent_low = annual_sales_low * ocr_low
    annual_rent_high = annual_sales_high * ocr_high
    rent_psf_low = sales_low * ocr_low
    rent_psf_high = sales_high * ocr_high

    # For ranges A=[a,b] and B=[c,d], the complete possible range of A/B is
    # [a/d, b/c] because all values are positive.
    breakpoint_low = annual_rent_low / percentage_high
    breakpoint_high = annual_rent_high / percentage_low

    return {
        "category": normalized,
        "requested_category": category,
        "unit_sf": sf,
        "convention_label": CONVENTION_NOTE,
        "forecast_status": "screening convention; not a tenant-specific sales forecast",
        "sales_psf_range": _range(sales_low, sales_high, unit="USD/sf/year"),
        "annual_sales_range": _range(
            annual_sales_low, annual_sales_high, unit="USD/year", derived=True
        ),
        "occupancy_cost_ratio_band": _range(
            ocr_low, ocr_high, unit="ratio of gross sales"
        ),
        "sustainable_rent_psf_range": _range(
            rent_psf_low, rent_psf_high, unit="USD/sf/year", derived=True
        ),
        "sustainable_annual_rent_range": _range(
            annual_rent_low, annual_rent_high, unit="USD/year", derived=True
        ),
        "percentage_rent_rate_band": _range(
            percentage_low, percentage_high, unit="ratio of gross sales"
        ),
        "natural_percentage_rent_breakpoint_range": {
            **_range(
                breakpoint_low, breakpoint_high, unit="USD annual gross sales", derived=True
            ),
            "formula": "annual base rent / percentage-rent rate",
            "range_method": (
                "outer range: sustainable rent low / percentage-rate high through "
                "sustainable rent high / percentage-rate low"
            ),
            "caveat": (
                "Illustrative only: a lease-specific natural breakpoint requires the "
                "negotiated annual base rent and percentage-rent rate."
            ),
        },
        "calculations": {
            "annual_sales": "sales_per_sf * unit_sf",
            "sustainable_annual_rent": "annual_sales * healthy_occupancy_cost_ratio",
            "sustainable_rent_psf": "sales_per_sf * healthy_occupancy_cost_ratio",
            "natural_breakpoint": "annual_base_rent / percentage_rent_rate",
        },
        "trade_area_context": {
            **context,
            "provenance": "caller-provided",
            "used_in_arithmetic": False,
            "note": (
                "Provided demographics and traffic are screening context only; no hidden "
                "uplift or haircut is applied without tenant-specific calibration."
            ),
        },
        "sources": list(convention["sources"]),
        "source_note": CONVENTION_NOTE,
        "decision_caveat": (
            "This result does not assert that a tenant will achieve these sales, pay this "
            "rent, or sign a lease."
        ),
    }


__all__ = ["CATEGORY_CONVENTIONS", "CONVENTION_NOTE", "tenant_sales_capacity"]
