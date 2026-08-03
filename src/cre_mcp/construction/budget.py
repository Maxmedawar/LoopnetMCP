"""Transparent convention-based development budgets.

The rates in this module are planning conventions, not bids.  They are public
so callers can audit (and, where appropriate, replace) every assumption before
using an estimate.  All returned monetary amounts are integer cents.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


CONVENTION_LABEL = "convention until bid"

# Rates are deliberately broad national planning ranges in cents per stated
# unit.  They are not claims about a particular market, site, or design.
HARD_COST_CONVENTIONS: dict[str, dict[str, Any]] = {
    "multifamily": {
        "low_cents_per_unit": 18_000_000,
        "high_cents_per_unit": 32_000_000,
        "unit": "dwelling_unit",
        "description": "Ground-up multifamily vertical construction",
    },
    "hotel": {
        "low_cents_per_unit": 22_000_000,
        "high_cents_per_unit": 45_000_000,
        "unit": "key",
        "description": "Ground-up select/full-service hotel construction",
    },
    "office": {
        "low_cents_per_unit": 25_000,
        "high_cents_per_unit": 50_000,
        "unit": "building_sf",
        "description": "Ground-up office shell and ordinary core",
    },
    "medical_office": {
        "low_cents_per_unit": 32_000,
        "high_cents_per_unit": 65_000,
        "unit": "building_sf",
        "description": "Ground-up medical-office shell and ordinary core",
    },
    "retail": {
        "low_cents_per_unit": 16_000,
        "high_cents_per_unit": 32_000,
        "unit": "building_sf",
        "description": "Ground-up retail shell and ordinary site integration",
    },
    "industrial": {
        "low_cents_per_unit": 9_000,
        "high_cents_per_unit": 18_000,
        "unit": "building_sf",
        "description": "Ground-up warehouse/light-industrial shell",
    },
    "self_storage": {
        "low_cents_per_unit": 7_000,
        "high_cents_per_unit": 15_000,
        "unit": "building_sf",
        "description": "Ground-up self-storage construction",
    },
    "mixed_use": {
        "low_cents_per_unit": 24_000,
        "high_cents_per_unit": 48_000,
        "unit": "building_sf",
        "description": "Blended mixed-use planning allowance",
    },
}

QUALITY_FACTOR_CONVENTIONS: dict[str, dict[str, str]] = {
    "economy": {"low": "0.85", "high": "0.95"},
    "standard": {"low": "1.00", "high": "1.00"},
    "premium": {"low": "1.15", "high": "1.35"},
    "luxury": {"low": "1.45", "high": "1.85"},
}

SITEWORK_PERCENT_CONVENTIONS: dict[str, dict[str, str]] = {
    "simple": {"low_pct": "4", "high_pct": "7"},
    "greenfield": {"low_pct": "5", "high_pct": "9"},
    "average": {"low_pct": "7", "high_pct": "12"},
    "infill": {"low_pct": "10", "high_pct": "18"},
    "constrained": {"low_pct": "15", "high_pct": "28"},
    "brownfield": {"low_pct": "20", "high_pct": "40"},
}

SOFT_COST_PERCENT_CONVENTIONS: dict[str, dict[str, str]] = {
    "architecture_and_engineering": {"low_pct": "6", "high_pct": "11"},
    "permits_and_impact_fees": {"low_pct": "2", "high_pct": "7"},
    "legal_insurance_and_financing": {"low_pct": "3", "high_pct": "7"},
    "developer_and_project_management": {"low_pct": "3", "high_pct": "6"},
}

CONTINGENCY_PERCENT_CONVENTIONS: dict[str, dict[str, str]] = {
    "construction_contingency": {"low_pct": "5", "high_pct": "10"},
}

# A single exposed table is convenient for API discovery and audit exports.
DEVELOPMENT_COST_CONVENTIONS: dict[str, Any] = {
    "hard_costs": HARD_COST_CONVENTIONS,
    "quality_factors": QUALITY_FACTOR_CONVENTIONS,
    "sitework_percent_of_vertical_hard_cost": SITEWORK_PERCENT_CONVENTIONS,
    "soft_cost_percent_of_total_hard_cost": SOFT_COST_PERCENT_CONVENTIONS,
    "contingency_percent_of_total_hard_cost": CONTINGENCY_PERCENT_CONVENTIONS,
    "currency": "USD cents",
    "status": CONVENTION_LABEL,
}
COST_CONVENTION_TABLE = DEVELOPMENT_COST_CONVENTIONS

_USE_ALIASES = {
    "apartments": "multifamily",
    "apartment": "multifamily",
    "multi_family": "multifamily",
    "multi_family_residential": "multifamily",
    "warehouse": "industrial",
    "logistics": "industrial",
    "medical": "medical_office",
    "mob": "medical_office",
    "storage": "self_storage",
    "mixed": "mixed_use",
}
_QUALITY_ALIASES = {
    "basic": "economy",
    "mid": "standard",
    "mid_market": "standard",
    "class_b": "standard",
    "high": "premium",
    "class_a": "premium",
}
_SITE_ALIASES = {
    "level": "simple",
    "urban": "constrained",
    "urban_infill": "infill",
    "complex": "constrained",
    "typical": "average",
}


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{field} must be a finite {qualifier} number")
    return result


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _slug(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _factor_range(local_factor: float | Mapping[str, Any] | None) -> tuple[Decimal, Decimal]:
    if local_factor is None:
        return Decimal("1"), Decimal("1")
    if isinstance(local_factor, Mapping):
        low = _decimal(local_factor.get("low"), "local_factor.low", positive=True)
        high = _decimal(local_factor.get("high"), "local_factor.high", positive=True)
    else:
        low = high = _decimal(local_factor, "local_factor", positive=True)
    if low > high:
        raise ValueError("local_factor.low cannot exceed local_factor.high")
    return low, high


def _site_assumption(site: Any) -> tuple[str, int | None, dict[str, str]]:
    explicit_cents: int | None = None
    if isinstance(site, Mapping):
        raw_category = site.get("category", site.get("condition", site.get("type")))
        if "sitework_cents" in site and site["sitework_cents"] is not None:
            raw_cents = site["sitework_cents"]
            if isinstance(raw_cents, bool) or not isinstance(raw_cents, int) or raw_cents < 0:
                raise ValueError(
                    "program.site.sitework_cents must be non-negative integer cents"
                )
            explicit_cents = raw_cents
    else:
        raw_category = site
    category = _slug(raw_category, "program.site")
    category = _SITE_ALIASES.get(category, category)
    if category not in SITEWORK_PERCENT_CONVENTIONS:
        raise ValueError(
            "program.site must be one of "
            f"{sorted(SITEWORK_PERCENT_CONVENTIONS)}"
        )
    return category, explicit_cents, SITEWORK_PERCENT_CONVENTIONS[category]


def _percent_line(
    item: str,
    category: str,
    basis_low_cents: int,
    basis_high_cents: int,
    low_pct: Decimal,
    high_pct: Decimal,
) -> dict[str, Any]:
    return {
        "item": item,
        "category": category,
        "basis": "percentage of total hard cost",
        "low_pct": str(low_pct),
        "high_pct": str(high_pct),
        "low_cents": _cents(Decimal(basis_low_cents) * low_pct / Decimal("100")),
        "high_cents": _cents(Decimal(basis_high_cents) * high_pct / Decimal("100")),
        "evidence_tag": CONVENTION_LABEL,
    }


def development_budget(
    program: Mapping[str, Any],
    local_factor: float | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a line-item development budget range from exposed conventions.

    ``sf_or_units`` follows the matched use's displayed unit.  ``escalation_pct``
    is an explicit user input, not a hidden forecast; when omitted, escalation
    is zero and the output flags the missing forecast assumption.
    """

    if not isinstance(program, Mapping):
        raise ValueError("program must be a dictionary")
    use = _slug(program.get("use"), "program.use")
    use = _USE_ALIASES.get(use, use)
    if use not in HARD_COST_CONVENTIONS:
        raise ValueError(f"program.use must be one of {sorted(HARD_COST_CONVENTIONS)}")
    quantity = _decimal(program.get("sf_or_units"), "program.sf_or_units", positive=True)
    hard_convention = HARD_COST_CONVENTIONS[use]
    if hard_convention["unit"] in {"dwelling_unit", "key"} and quantity != quantity.to_integral_value():
        raise ValueError(f"program.sf_or_units must be a whole {hard_convention['unit']} count")

    quality = _slug(program.get("quality"), "program.quality")
    quality = _QUALITY_ALIASES.get(quality, quality)
    if quality not in QUALITY_FACTOR_CONVENTIONS:
        raise ValueError(
            f"program.quality must be one of {sorted(QUALITY_FACTOR_CONVENTIONS)}"
        )
    site_category, sitework_cents, site_range = _site_assumption(program.get("site"))
    local_low, local_high = _factor_range(local_factor)
    quality_low = Decimal(QUALITY_FACTOR_CONVENTIONS[quality]["low"])
    quality_high = Decimal(QUALITY_FACTOR_CONVENTIONS[quality]["high"])

    vertical_low = _cents(
        quantity
        * Decimal(hard_convention["low_cents_per_unit"])
        * quality_low
        * local_low
    )
    vertical_high = _cents(
        quantity
        * Decimal(hard_convention["high_cents_per_unit"])
        * quality_high
        * local_high
    )
    vertical_line = {
        "item": "vertical_hard_cost",
        "category": "hard_cost",
        "basis": f"{hard_convention['unit']} x exposed hard-cost rate x quality x local factor",
        "quantity": int(quantity) if quantity == quantity.to_integral_value() else str(quantity),
        "quantity_unit": hard_convention["unit"],
        "rate_low_cents": hard_convention["low_cents_per_unit"],
        "rate_high_cents": hard_convention["high_cents_per_unit"],
        "low_cents": vertical_low,
        "high_cents": vertical_high,
        "evidence_tag": CONVENTION_LABEL,
    }

    if sitework_cents is None:
        site_low_pct = Decimal(site_range["low_pct"])
        site_high_pct = Decimal(site_range["high_pct"])
        site_low = _cents(Decimal(vertical_low) * site_low_pct / Decimal("100"))
        site_high = _cents(Decimal(vertical_high) * site_high_pct / Decimal("100"))
        site_basis = "site category convention as percentage of vertical hard cost"
        site_tag = CONVENTION_LABEL
    else:
        site_low_pct = site_high_pct = Decimal("0")
        site_low = site_high = sitework_cents
        site_basis = "user-supplied sitework amount; source not independently verified"
        site_tag = "user input; not bid-verified"
    site_line = {
        "item": "sitework",
        "category": "hard_cost",
        "basis": site_basis,
        "site_category": site_category,
        "low_pct": str(site_low_pct),
        "high_pct": str(site_high_pct),
        "low_cents": site_low,
        "high_cents": site_high,
        "evidence_tag": site_tag,
    }

    hard_low = vertical_low + site_low
    hard_high = vertical_high + site_high
    soft_lines: list[dict[str, Any]] = []
    for item, rates in SOFT_COST_PERCENT_CONVENTIONS.items():
        soft_lines.append(
            _percent_line(
                item,
                "soft_cost",
                hard_low,
                hard_high,
                Decimal(rates["low_pct"]),
                Decimal(rates["high_pct"]),
            )
        )

    contingency_rates = CONTINGENCY_PERCENT_CONVENTIONS["construction_contingency"]
    contingency_line = _percent_line(
        "construction_contingency",
        "contingency",
        hard_low,
        hard_high,
        Decimal(contingency_rates["low_pct"]),
        Decimal(contingency_rates["high_pct"]),
    )

    escalation_supplied = program.get("escalation_pct") is not None
    escalation_pct = _decimal(
        program.get("escalation_pct", 0), "program.escalation_pct"
    )
    escalation_low = _cents(Decimal(hard_low) * escalation_pct / Decimal("100"))
    escalation_high = _cents(Decimal(hard_high) * escalation_pct / Decimal("100"))
    escalation_line = {
        "item": "escalation",
        "category": "escalation",
        "basis": "user-supplied percentage of total hard cost",
        "escalation_pct": str(escalation_pct),
        "low_cents": escalation_low,
        "high_cents": escalation_high,
        "evidence_tag": (
            "user input; not market-verified"
            if escalation_supplied
            else "zero placeholder; escalation input not supplied"
        ),
    }

    lines = [vertical_line, site_line, *soft_lines, contingency_line, escalation_line]
    soft_low = sum(line["low_cents"] for line in soft_lines)
    soft_high = sum(line["high_cents"] for line in soft_lines)
    contingency_low = contingency_line["low_cents"]
    contingency_high = contingency_line["high_cents"]
    total_low = hard_low + soft_low + contingency_low + escalation_low
    total_high = hard_high + soft_high + contingency_high + escalation_high

    limitations = [
        "Rates are national planning conventions and remain convention until bid.",
        "Land, acquisition, demolition, environmental remediation, tenant improvements, taxes, and operating deficits are excluded unless represented by the displayed lines.",
        "Scope, constructability, quantities, phasing, procurement, and local labor/material conditions are not field verified.",
    ]
    if not escalation_supplied:
        limitations.append("Escalation is a zero placeholder because no escalation_pct was supplied.")

    return {
        "convention_label": CONVENTION_LABEL,
        "estimate_status": CONVENTION_LABEL,
        "convention_table_key": use,
        "program": {
            "use": use,
            "sf_or_units": int(quantity) if quantity == quantity.to_integral_value() else str(quantity),
            "quantity_unit": hard_convention["unit"],
            "quality": quality,
            "site": site_category,
            "escalation_pct": str(escalation_pct),
            "escalation_supplied": escalation_supplied,
        },
        "factors": {
            "quality": {"low": str(quality_low), "high": str(quality_high)},
            "local": {"low": str(local_low), "high": str(local_high)},
        },
        "line_items": lines,
        "totals": {
            "hard_cost_low_cents": hard_low,
            "hard_cost_high_cents": hard_high,
            "soft_cost_low_cents": soft_low,
            "soft_cost_high_cents": soft_high,
            "contingency_low_cents": contingency_low,
            "contingency_high_cents": contingency_high,
            "escalation_low_cents": escalation_low,
            "escalation_high_cents": escalation_high,
            "development_budget_low_cents": total_low,
            "development_budget_high_cents": total_high,
            "low_cents": total_low,
            "high_cents": total_high,
        },
        "total_low_cents": total_low,
        "total_high_cents": total_high,
        "budget_range_cents": {"low_cents": total_low, "high_cents": total_high},
        "professional_review_flags": [
            {"role": "architect", "status": "required", "reason": "validate program, quality, design scope, and soft-cost assumptions"},
            {"role": "engineer", "status": "required", "reason": "validate site, utilities, structure, and discipline scope"},
            {"role": "gc", "status": "required", "reason": "replace planning conventions with current local trade bids"},
            {"role": "inspector", "status": "not_field_verified", "reason": "output contains no inspection or field-completion evidence"},
        ],
        "limitations": limitations,
    }


__all__ = [
    "CONVENTION_LABEL",
    "CONTINGENCY_PERCENT_CONVENTIONS",
    "COST_CONVENTION_TABLE",
    "DEVELOPMENT_COST_CONVENTIONS",
    "HARD_COST_CONVENTIONS",
    "QUALITY_FACTOR_CONVENTIONS",
    "SITEWORK_PERCENT_CONVENTIONS",
    "SOFT_COST_PERCENT_CONVENTIONS",
    "development_budget",
]
