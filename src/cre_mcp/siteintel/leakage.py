"""Directional retail gap notes from transparent demand/supply conventions.

The calculation here is a screening signal.  It uses BLS Consumer Expenditure
shares as a spending-potential convention and OSM place counts as a supply
proxy.  It is not a substitute for measured retail sales or paid consumer-spend
data.
"""

from __future__ import annotations

import math
import re
from typing import Any

BLS_CEX_SOURCE: dict[str, str] = {
    "publisher": "U.S. Bureau of Labor Statistics",
    "dataset": "Consumer Expenditure Surveys, 2024",
    "table": "Tables A and B, all consumer units",
    "release_date": "2025-12-19",
    "source_url": "https://www.bls.gov/news.release/cesan.nr0.htm",
    "convention_note": (
        "National all-consumer-unit expenditure shares are screening conventions, "
        "not local category demand estimates."
    ),
}

# Table B supplies major-category shares.  Food subcategory shares are derived
# from the Table A dollar means divided by its $78,535 total annual expenditure.
BLS_CEX_CATEGORY_SHARES: dict[str, float] = {
    "food": 0.1290,
    "food_at_home": 0.0793,
    "food_away_from_home": 0.0502,
    "alcoholic_beverages": 0.0080,
    "apparel_and_services": 0.0250,
    "entertainment": 0.0460,
    "personal_care": 0.0120,
}

CATEGORY_ALIASES: dict[str, str] = {
    "apparel": "apparel_and_services",
    "clothing": "apparel_and_services",
    "grocery": "food_at_home",
    "groceries": "food_at_home",
    "restaurant": "food_away_from_home",
    "restaurants": "food_away_from_home",
    "dining": "food_away_from_home",
    "personal_care_products_and_services": "personal_care",
}

SUPPLY_PROXY_CONVENTION: dict[str, Any] = {
    "annual_capacity_per_osm_location": 5_000_000.0,
    "units": "screening dollars per counted OSM location",
    "note": (
        "A fixed per-location capacity is an explicit comparison heuristic, not "
        "observed store sales; callers may provide annual_capacity_per_anchor in "
        "the trade-area input."
    ),
}

HONESTY_LABEL = (
    "direction not dollars — paid consumer-spend data would be needed for magnitude"
)


def _normalized_category(category: object) -> str:
    if not isinstance(category, str) or not category.strip():
        raise ValueError("category must be a non-empty string")
    normalized = re.sub(r"[^a-z0-9]+", "_", category.casefold()).strip("_")
    return CATEGORY_ALIASES.get(normalized, normalized)


def _finite_nonnegative(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative finite number")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative finite number") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a non-negative finite number")
    return number


def _demographic_value(trade_area: dict[str, Any], *names: str) -> object:
    for name in names:
        if name in trade_area and trade_area[name] is not None:
            return trade_area[name]
    demographics = trade_area.get("demographic_inputs")
    if isinstance(demographics, dict):
        for name in names:
            if name in demographics and demographics[name] is not None:
                return demographics[name]
    raise ValueError(f"trade_area must include {names[0]}")


def _mapping_count(mapping: object, category: str) -> object | None:
    if not isinstance(mapping, dict):
        return None
    for raw_category, value in mapping.items():
        try:
            if _normalized_category(raw_category) == category:
                return value
        except ValueError:
            continue
    return None


def _anchor_count(trade_area: dict[str, Any], category: str) -> float:
    for key in ("osm_anchor_counts", "category_anchor_counts"):
        count = _mapping_count(trade_area.get(key), category)
        if count is not None:
            return _finite_nonnegative(count, f"{key}[{category!r}]")

    for key in ("osm_anchor_count", "anchor_count"):
        if trade_area.get(key) is not None:
            return _finite_nonnegative(trade_area[key], key)

    osm = trade_area.get("osm_anchors")
    if isinstance(osm, dict):
        count = _mapping_count(osm.get("category_anchor_counts"), category)
        if count is not None:
            return _finite_nonnegative(count, f"category_anchor_counts[{category!r}]")
        if osm.get("anchor_count") is not None:
            return _finite_nonnegative(osm["anchor_count"], "osm_anchors.anchor_count")

    raise ValueError(
        "trade_area must include an OSM anchor count or category anchor-count mapping"
    )


def retail_gap_note(trade_area: dict[str, Any], category: str) -> dict[str, Any]:
    """Return a leakage/surplus *direction* for one retail category.

    Demand convention: ``population × income × BLS CE share``.
    Supply convention: ``OSM anchor count × heuristic annual capacity``.
    Only the sign of that comparison is reported as a conclusion.
    """
    try:
        if not isinstance(trade_area, dict):
            raise ValueError("trade_area must be a dictionary")
        normalized_category = _normalized_category(category)
        if normalized_category not in BLS_CEX_CATEGORY_SHARES:
            supported = ", ".join(sorted(BLS_CEX_CATEGORY_SHARES))
            raise ValueError(
                f"unsupported category {category!r}; supported categories: {supported}"
            )

        population = _finite_nonnegative(
            _demographic_value(trade_area, "population"), "population"
        )
        income = _finite_nonnegative(
            _demographic_value(
                trade_area, "median_household_income", "income", "per_capita_income"
            ),
            "income",
        )
        anchors = _anchor_count(trade_area, normalized_category)
        capacity_value = trade_area.get(
            "annual_capacity_per_anchor",
            SUPPLY_PROXY_CONVENTION["annual_capacity_per_osm_location"],
        )
        capacity = _finite_nonnegative(
            capacity_value, "annual_capacity_per_anchor"
        )
        if capacity == 0:
            raise ValueError("annual_capacity_per_anchor must be greater than zero")

        share = BLS_CEX_CATEGORY_SHARES[normalized_category]
        spending_potential = population * income * share
        supply_proxy = anchors * capacity
        if math.isclose(spending_potential, supply_proxy, rel_tol=1e-12, abs_tol=0.01):
            direction = "balanced"
        elif spending_potential > supply_proxy:
            direction = "leakage"
        else:
            direction = "surplus"

        return {
            "category": normalized_category,
            "direction": direction,
            "honesty_label": HONESTY_LABEL,
            "demand_convention": {
                "formula": "population × income × BLS CEX category share",
                "population": population,
                "income": income,
                "category_share": share,
                "spending_potential_proxy": round(spending_potential, 2),
            },
            "existing_supply_proxy": {
                "measure": "OpenStreetMap anchor count",
                "osm_anchor_count": anchors,
                "annual_capacity_per_anchor": capacity,
                "capacity_proxy": round(supply_proxy, 2),
            },
            "source": dict(BLS_CEX_SOURCE),
            "notes": [
                BLS_CEX_SOURCE["convention_note"],
                SUPPLY_PROXY_CONVENTION["note"],
                "OSM counts can omit unbranded, closed, new, or unmapped locations.",
                HONESTY_LABEL,
            ],
        }
    except Exception as exc:
        return {"error": str(exc)}


__all__ = [
    "BLS_CEX_CATEGORY_SHARES",
    "BLS_CEX_SOURCE",
    "CATEGORY_ALIASES",
    "HONESTY_LABEL",
    "SUPPLY_PROXY_CONVENTION",
    "retail_gap_note",
]
