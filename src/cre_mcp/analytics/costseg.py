"""Cost-segregation and depreciation preview with exposed tax conventions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any


FILING_REQUIREMENT = "engineering-based cost-seg study + CPA required for filing"
BONUS_WARNING = (
    "Bonus-depreciation law changes over time; bonus_rate is caller-supplied INPUT "
    "and is not inferred from the current year."
)

# IRS Publication 946, Appendix A, Table A-1.  These are percentages under GDS
# and the half-year convention.  Storing the published values (rather than
# recomputing a declining-balance switch) makes every preview year auditable.
MACRS_HALF_YEAR_RATES: dict[str, tuple[float, ...]] = {
    "5yr": (0.20, 0.32, 0.192, 0.1152, 0.1152, 0.0576),
    "7yr": (0.1429, 0.2449, 0.1749, 0.1249, 0.0893, 0.0892, 0.0893, 0.0446),
    "15yr": (
        0.05,
        0.095,
        0.0855,
        0.077,
        0.0693,
        0.0623,
        0.059,
        0.059,
        0.0591,
        0.059,
        0.0591,
        0.059,
        0.0591,
        0.059,
        0.0591,
        0.0295,
    ),
}

# Nonresidential real property is *not* half-year property.  With no
# placed-in-service month in this preview's interface, the exposed profile uses
# July as a screening assumption from IRS Publication 946 Table A-7a.  The final
# year is the complement required to recover exactly 100% of basis.
_MID_MONTH_JULY_FIRST = 0.01177
_MID_MONTH_ANNUAL = 0.02564
_MID_MONTH_JULY_LAST = round(
    1.0 - _MID_MONTH_JULY_FIRST - (38 * _MID_MONTH_ANNUAL), 5
)
MACRS_39_YEAR_JULY_RATES: tuple[float, ...] = (
    _MID_MONTH_JULY_FIRST,
    *(_MID_MONTH_ANNUAL for _ in range(38)),
    _MID_MONTH_JULY_LAST,
)

MACRS_TABLES: dict[str, dict[str, Any]] = {
    "5yr": {
        "rates": MACRS_HALF_YEAR_RATES["5yr"],
        "method": "GDS 200% declining balance, half-year convention",
        "citation": "IRS Publication 946, Appendix A, Table A-1, 5-year column",
        "bonus_eligible_screen": True,
    },
    "7yr": {
        "rates": MACRS_HALF_YEAR_RATES["7yr"],
        "method": "GDS 200% declining balance, half-year convention",
        "citation": "IRS Publication 946, Appendix A, Table A-1, 7-year column",
        "bonus_eligible_screen": True,
    },
    "15yr": {
        "rates": MACRS_HALF_YEAR_RATES["15yr"],
        "method": "GDS 150% declining balance, half-year convention",
        "citation": "IRS Publication 946, Appendix A, Table A-1, 15-year column",
        "bonus_eligible_screen": True,
    },
    "39yr": {
        "rates": MACRS_39_YEAR_JULY_RATES,
        "method": "GDS straight line, mid-month convention; July screening assumption",
        "citation": "IRS Publication 946, Appendix A, Table A-7a, 39-year nonresidential real property",
        "bonus_eligible_screen": False,
    },
}

# These are transparent screening allocations, not empirical findings and not a
# substitute for an engineer's quantity takeoff.  Percentages allocate the
# building/depreciable basis after land, and sum to 100% in every profile.
ASSET_TYPE_PROFILES: dict[str, tuple[dict[str, Any], ...]] = {
    "commercial_generic": (
        {"class": "5yr", "pct": 15.0},
        {"class": "7yr", "pct": 5.0},
        {"class": "15yr", "pct": 10.0},
        {"class": "39yr", "pct": 70.0},
    ),
    "retail": (
        {"class": "5yr", "pct": 20.0},
        {"class": "7yr", "pct": 5.0},
        {"class": "15yr", "pct": 15.0},
        {"class": "39yr", "pct": 60.0},
    ),
    "office": (
        {"class": "5yr", "pct": 15.0},
        {"class": "7yr", "pct": 5.0},
        {"class": "15yr", "pct": 10.0},
        {"class": "39yr", "pct": 70.0},
    ),
    "industrial": (
        {"class": "5yr", "pct": 10.0},
        {"class": "7yr", "pct": 5.0},
        {"class": "15yr", "pct": 10.0},
        {"class": "39yr", "pct": 75.0},
    ),
    "self_storage": (
        {"class": "5yr", "pct": 10.0},
        {"class": "7yr", "pct": 5.0},
        {"class": "15yr", "pct": 20.0},
        {"class": "39yr", "pct": 65.0},
    ),
}


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if value is None or isinstance(value, bool):
        qualifier = "positive " if positive else "non-negative "
        raise ValueError(f"{label} must be a finite {qualifier}number")
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        qualifier = "positive " if positive else "non-negative "
        raise ValueError(f"{label} must be a finite {qualifier}number")
    return number


def _rate(value: Any, label: str) -> tuple[float, str]:
    number = _number(value, label)
    if number > 100:
        raise ValueError(f"{label} must be from 0 to 1 or from 0 to 100")
    if number > 1:
        return number / 100.0, "percentage points"
    return number, "decimal fraction"


def _normalized_asset_type(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _allocation_rows(
    components: Sequence[Mapping[str, Any]] | None,
    asset_type: str | None,
) -> tuple[list[dict[str, Any]], str, str | None, list[str]]:
    if components is not None and asset_type is not None:
        raise ValueError("supply components or asset_type, not both")
    if components is None:
        if asset_type is None or not str(asset_type).strip():
            raise ValueError("components or asset_type is required")
        profile = _normalized_asset_type(str(asset_type))
        if profile not in ASSET_TYPE_PROFILES:
            raise ValueError(
                f"asset_type is unrecognized; choose one of {sorted(ASSET_TYPE_PROFILES)}"
            )
        source_rows: Sequence[Mapping[str, Any]] = ASSET_TYPE_PROFILES[profile]
        input_mode = "screening_profile"
    else:
        if isinstance(components, (str, bytes, Mapping)):
            raise ValueError("components must be a sequence of mappings")
        source_rows = components
        profile = None
        input_mode = "caller_components"
    if not source_rows:
        raise ValueError("components must contain at least one allocation")

    allowed = {"class", "pct"}
    unrecognized: list[str] = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(source_rows):
        if not isinstance(item, Mapping):
            raise ValueError(f"components[{index}] must be a mapping")
        unrecognized.extend(
            f"components[{index}].{key}" for key in item if key not in allowed
        )
        class_name = str(item.get("class") or "").strip().lower().replace(" ", "")
        if class_name not in MACRS_TABLES:
            raise ValueError(
                f"components[{index}].class must be one of {sorted(MACRS_TABLES)}"
            )
        if class_name in seen:
            raise ValueError(f"components contains duplicate class {class_name!r}")
        seen.add(class_name)
        pct, convention = _rate(item.get("pct"), f"components[{index}].pct")
        rows.append(
            {
                "class": class_name,
                "pct": pct,
                "pct_input_convention": convention,
            }
        )
    total = sum(row["pct"] for row in rows)
    if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-8):
        raise ValueError(
            f"component pct allocations must sum to 100% of depreciable basis; got {total:.6%}"
        )
    return rows, input_mode, profile, unrecognized


def _component_schedule(
    basis: float,
    class_name: str,
    bonus_rate: float,
    apply_bonus: bool,
) -> tuple[list[dict[str, Any]], float]:
    table = MACRS_TABLES[class_name]
    eligible = bool(table["bonus_eligible_screen"])
    applied_rate = bonus_rate if apply_bonus and eligible else 0.0
    bonus_amount = round(basis * applied_rate, 2)
    remaining_after_bonus = round(basis - bonus_amount, 2)

    regular_amounts = [
        round(remaining_after_bonus * rate, 2) for rate in table["rates"]
    ]
    # Published table rounding can differ by a few basis points; anchor the last
    # tax year to the caller's actual allocated basis, penny exactly.
    if regular_amounts:
        regular_amounts[-1] = round(
            remaining_after_bonus - sum(regular_amounts[:-1]), 2
        )

    schedule: list[dict[str, Any]] = []
    cumulative = 0.0
    for year, (rate, regular) in enumerate(
        zip(table["rates"], regular_amounts, strict=True), start=1
    ):
        bonus = bonus_amount if year == 1 else 0.0
        total = round(bonus + regular, 2)
        cumulative = round(cumulative + total, 2)
        schedule.append(
            {
                "year": year,
                "macrs_rate": rate,
                "bonus_depreciation": bonus,
                "regular_macrs_depreciation": regular,
                "total_depreciation": total,
                "cumulative_depreciation": cumulative,
                "remaining_basis": round(max(0.0, basis - cumulative), 2),
            }
        )
    return schedule, applied_rate


def _cost_seg_preview(
    purchase_price: Any,
    land_pct: Any,
    components: Sequence[Mapping[str, Any]] | None = None,
    asset_type: str | None = None,
    bonus_rate: Any = 0.0,
    apply_bonus: bool = False,
) -> dict[str, Any]:
    price = _number(purchase_price, "purchase_price", positive=True)
    land_rate, land_convention = _rate(land_pct, "land_pct")
    if land_rate >= 1:
        raise ValueError("land_pct must be less than 100%")
    if not isinstance(apply_bonus, bool):
        raise ValueError("apply_bonus must be true or false")
    normalized_bonus, bonus_convention = _rate(bonus_rate, "bonus_rate")
    allocations, input_mode, profile, unrecognized = _allocation_rows(
        components, asset_type
    )

    land_basis = round(price * land_rate, 2)
    depreciable_basis = round(price - land_basis, 2)
    allocated_bases = [
        round(depreciable_basis * row["pct"], 2) for row in allocations
    ]
    allocated_bases[-1] = round(
        depreciable_basis - sum(allocated_bases[:-1]), 2
    )

    component_results: list[dict[str, Any]] = []
    for allocation, basis in zip(allocations, allocated_bases, strict=True):
        class_name = allocation["class"]
        schedule, applied_rate = _component_schedule(
            basis, class_name, normalized_bonus, apply_bonus
        )
        table = MACRS_TABLES[class_name]
        component_results.append(
            {
                **allocation,
                "basis": basis,
                "method": table["method"],
                "citation": table["citation"],
                "macrs_rates": list(table["rates"]),
                "bonus_eligible_screen": table["bonus_eligible_screen"],
                "bonus_rate_applied": applied_rate,
                "schedule": schedule,
            }
        )

    max_years = max(len(item["schedule"]) for item in component_results)
    yearly_schedule: list[dict[str, Any]] = []
    cumulative = 0.0
    for year in range(1, max_years + 1):
        by_class: dict[str, float] = {}
        for item in component_results:
            amount = (
                item["schedule"][year - 1]["total_depreciation"]
                if year <= len(item["schedule"])
                else 0.0
            )
            by_class[item["class"]] = amount
        depreciation = round(sum(by_class.values()), 2)
        cumulative = round(cumulative + depreciation, 2)
        yearly_schedule.append(
            {
                "year": year,
                "depreciation": depreciation,
                "total_depreciation": depreciation,
                "by_class": by_class,
                "cumulative_depreciation": cumulative,
                "remaining_depreciable_basis": round(
                    max(0.0, depreciable_basis - cumulative), 2
                ),
            }
        )

    warnings = [
        FILING_REQUIREMENT,
        BONUS_WARNING,
        (
            "Asset-type profiles are exposed screening conventions, not measured "
            "allocations; replace them with an engineering study before filing."
        ),
        (
            "39-year nonresidential real property uses the mid-month convention, "
            "not half-year; this preview assumes July because no service month is supplied."
        ),
        (
            "Eligibility for bonus depreciation, listed property limits, passive-loss "
            "limits, elections, recapture, and tax basis require CPA review."
        ),
    ]
    if not apply_bonus and normalized_bonus:
        warnings.append("bonus_rate was supplied but not applied because apply_bonus is false.")

    return {
        "status": "PREVIEW_NOT_TAX_ADVICE",
        "purchase_price": round(price, 2),
        "land_pct": land_rate,
        "land_pct_input_convention": land_convention,
        "land_basis": land_basis,
        "depreciable_basis": depreciable_basis,
        "allocation_basis": "depreciable purchase-price basis after land",
        "input_mode": input_mode,
        "asset_type_profile": profile,
        "available_asset_type_profiles": {
            name: [dict(item) for item in rows]
            for name, rows in ASSET_TYPE_PROFILES.items()
        },
        "components": component_results,
        "schedule": yearly_schedule,
        "yearly_schedule": yearly_schedule,
        "depreciation_schedule": yearly_schedule,
        "apply_bonus": apply_bonus,
        "bonus_rate": normalized_bonus,
        "bonus": {
            "apply_bonus": apply_bonus,
            "input_rate": normalized_bonus,
            "input_convention": bonus_convention,
            "law_sensitive_input": True,
        },
        "apply_bonus": apply_bonus,
        "bonus_rate": normalized_bonus,
        "macrs_sources": [
            {
                "classes": ["5yr", "7yr", "15yr"],
                "convention": "half-year",
                "citation": "IRS Publication 946, Appendix A, Table A-1",
                "url": "https://www.irs.gov/publications/p946",
            },
            {
                "classes": ["39yr"],
                "convention": "mid-month; July screening assumption",
                "citation": "IRS Publication 946, Appendix A, Table A-7a",
                "url": "https://www.irs.gov/publications/p946",
            },
        ],
        "filing_requirement": FILING_REQUIREMENT,
        "warnings": warnings,
        "after_tax_hook": {
            "module": "cre_mcp.ops.after_tax_returns",
            "status": "DELEGATED_NOT_CALCULATED",
            "note": (
                "Pass the reviewed depreciation schedule and taxpayer-specific "
                "assumptions to ops.after_tax_returns; this preview does not compute after-tax returns."
            ),
        },
        "unrecognized_inputs": unrecognized,
    }


def cost_seg_preview(
    purchase_price: Any,
    land_pct: Any,
    components: Sequence[Mapping[str, Any]] | None = None,
    asset_type: str | None = None,
    bonus_rate: Any = 0.0,
    apply_bonus: bool = False,
) -> dict[str, Any]:
    """Return a transparent depreciation preview with a stable error boundary."""

    try:
        return _cost_seg_preview(
            purchase_price,
            land_pct,
            components,
            asset_type,
            bonus_rate,
            apply_bonus,
        )
    except Exception as exc:
        message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
        return {"error": message or exc.__class__.__name__}


__all__ = [
    "ASSET_TYPE_PROFILES",
    "BONUS_WARNING",
    "FILING_REQUIREMENT",
    "MACRS_HALF_YEAR_RATES",
    "MACRS_TABLES",
    "cost_seg_preview",
]
