"""Range-based reconciliation of the three conventional valuation approaches.

The module deliberately keeps the income, sales-comparison, and cost indications
separate.  A caller can request weighted arithmetic by supplying weights, but the
model never invents weights or treats arithmetic as a substitute for explaining
why the approaches differ.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


DISCLAIMER = (
    "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
)


def _number(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    cleaned: Any = value
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1]
    try:
        number = float(cleaned)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _range(value: Any, label: str, *, nonnegative: bool = True) -> tuple[float, float]:
    """Normalize a scalar or explicit two-endpoint range without widening it."""

    if isinstance(value, Mapping):
        nested_key = next(
            (key for key in ("range", "value_range") if key in value), None
        )
        if nested_key is not None:
            return _range(value[nested_key], f"{label}.{nested_key}", nonnegative=nonnegative)
        low_key = next(
            (key for key in ("low", "min", "minimum") if key in value), None
        )
        high_key = next(
            (key for key in ("high", "max", "maximum") if key in value), None
        )
        if low_key is None or high_key is None:
            raise ValueError(f"{label} range must include low and high")
        low = _number(value[low_key], f"{label}.{low_key}")
        high = _number(value[high_key], f"{label}.{high_key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
        if len(values) != 2:
            raise ValueError(f"{label} range must contain exactly two values")
        low = _number(values[0], f"{label}[0]")
        high = _number(values[1], f"{label}[1]")
    else:
        low = high = _number(value, label)
    if low > high:
        raise ValueError(f"{label} range must be ordered low to high")
    if nonnegative and low < 0:
        raise ValueError(f"{label} must be non-negative")
    return low, high


def _rate_range(value: Any, label: str) -> tuple[float, float]:
    low, high = _range(value, label)
    low = low / 100 if low > 1 else low
    high = high / 100 if high > 1 else high
    if low <= 0 or high > 1:
        raise ValueError(f"{label} must be a positive decimal or percent no greater than 100%")
    return low, high


def _as_range(low: float, high: float) -> dict[str, float]:
    return {"low": low, "high": high}


def _weight_key(raw: Any) -> str | None:
    key = str(raw).strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "income": "income",
        "income_approach": "income",
        "sales": "sales_comparison",
        "sales_comps": "sales_comparison",
        "sales_comparison": "sales_comparison",
        "sales_comparison_approach": "sales_comparison",
        "cost": "cost",
        "cost_approach": "cost",
    }
    return aliases.get(key)


def _normalize_weights(weights: Any) -> tuple[dict[str, float], dict[str, float]]:
    if not isinstance(weights, Mapping):
        raise ValueError("weights must be a mapping of approach names to stated weights")
    raw_weights = {"income": 0.0, "sales_comparison": 0.0, "cost": 0.0}
    seen: set[str] = set()
    for raw_key, raw_value in weights.items():
        key = _weight_key(raw_key)
        if key is None:
            raise ValueError(f"weights contains an unknown approach: {raw_key}")
        if key in seen:
            raise ValueError(f"weights contains duplicate aliases for {key}")
        seen.add(key)
        value = _number(raw_value, f"weights.{raw_key}")
        if value < 0:
            raise ValueError("weights must be non-negative")
        raw_weights[key] = value
    total = sum(raw_weights.values())
    if total <= 0:
        raise ValueError("at least one user-supplied weight must be positive")
    return raw_weights, {key: value / total for key, value in raw_weights.items()}


def _directional_explanations(
    income_range: tuple[float, float],
    sales_range: tuple[float, float] | None,
    cost_range: tuple[float, float],
) -> list[dict[str, str]]:
    explanations: list[dict[str, str]] = []
    income_center = sum(income_range) / 2
    cost_center = sum(cost_range) / 2

    if sales_range is not None:
        sales_center = sum(sales_range) / 2
        if income_center < sales_center:
            explanations.append(
                {
                    "rule": "income_below_sales",
                    "explanation": (
                        "The income approach central indication is below the sales-comparison "
                        "central indication. "
                        "Investigate below-market leases, in-place NOI or occupancy, and "
                        "cap-rate assumptions; this is a diligence explanation, not a "
                        "basis for averaging the approaches."
                    ),
                }
            )
        elif income_center > sales_center:
            explanations.append(
                {
                    "rule": "sales_below_income",
                    "explanation": (
                        "The sales-comparison central indication is below the income approach "
                        "central indication. "
                        "Investigate whether the subject has superior in-place income, the "
                        "comparables need property-rights or condition adjustments, or the "
                        "income cap-rate assumption is too aggressive."
                    ),
                }
            )
        else:
            explanations.append(
                {
                    "rule": "income_sales_centers_equal",
                    "explanation": (
                        "The income and sales-comparison central indications coincide, but "
                        "their underlying lease, NOI, cap-rate, and comparability assumptions "
                        "still require separate support."
                    ),
                }
            )

        if sales_center < cost_center:
            explanations.append(
                {
                    "rule": "sales_below_cost",
                    "explanation": (
                        "The sales-comparison central indication is below the cost-approach "
                        "central indication. "
                        "Investigate functional or economic obsolescence and the land or "
                        "replacement-cost basis; cost does not establish what market buyers "
                        "will pay."
                    ),
                }
            )
        elif sales_center > cost_center:
            explanations.append(
                {
                    "rule": "cost_below_sales",
                    "explanation": (
                        "The cost-approach central indication is below the sales-comparison "
                        "central indication. "
                        "Investigate land scarcity, entrepreneurial incentive, depreciation, "
                        "and whether the comparables reflect income or location premiums."
                    ),
                }
            )
        else:
            explanations.append(
                {
                    "rule": "sales_cost_centers_equal",
                    "explanation": (
                        "The sales-comparison and cost central indications coincide, but land, "
                        "replacement cost, depreciation, and comp adjustments remain distinct "
                        "assumptions requiring support."
                    ),
                }
            )

    if income_center < cost_center:
        explanations.append(
            {
                "rule": "income_below_cost",
                "explanation": (
                    "The income indication is below cost, which can reflect lease economics, "
                    "occupancy, functional or economic obsolescence, or unsupported cost inputs."
                ),
            }
        )
    elif income_center > cost_center:
        explanations.append(
            {
                "rule": "cost_below_income",
                "explanation": (
                    "The cost indication is below income, which can reflect land scarcity, "
                    "profitable in-place leases, understated replacement cost, or excess income "
                    "that may not persist."
                ),
            }
        )
    return explanations


def reconcile_approaches(
    income: Mapping[str, Any],
    sales_comps: Sequence[Mapping[str, Any]],
    cost: Mapping[str, Any],
    subject_sf: Any | None = None,
    weights: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return separate approach ranges and an explanation-led reconciliation.

    Cap rates accept either decimals (``0.06``) or percentages (``6``/``"6%"``).
    Weighting is performed only when ``weights`` is explicitly supplied by the caller.
    Malformed inputs are returned at the public boundary as ``{"error": ...}``.
    """

    try:
        if not isinstance(income, Mapping):
            raise ValueError("income must be a mapping containing noi and cap_range")
        if "noi" not in income:
            raise ValueError("income.noi is required")
        if "cap_range" not in income:
            raise ValueError("income.cap_range is required")
        noi_low, noi_high = _range(income["noi"], "income.noi")
        cap_low, cap_high = _rate_range(income["cap_range"], "income.cap_range")
        income_values = (noi_low / cap_high, noi_high / cap_low)

        if not isinstance(sales_comps, Sequence) or isinstance(sales_comps, (str, bytes)):
            raise ValueError("sales_comps must be a non-empty sequence of mappings")
        if not sales_comps:
            raise ValueError("sales_comps must contain at least one price_psf indication")
        comp_rows: list[dict[str, Any]] = []
        comp_lows: list[float] = []
        comp_highs: list[float] = []
        for index, comp in enumerate(sales_comps):
            if not isinstance(comp, Mapping):
                raise ValueError(f"sales_comps[{index}] must be a mapping")
            key = "price_psf" if "price_psf" in comp else "price_per_sf"
            if key not in comp:
                raise ValueError(f"sales_comps[{index}].price_psf is required")
            low, high = _range(comp[key], f"sales_comps[{index}].{key}")
            comp_lows.append(low)
            comp_highs.append(high)
            comp_rows.append({"index": index, "price_per_sf_range": _as_range(low, high)})
        price_psf_range = (min(comp_lows), max(comp_highs))

        sf: float | None = None
        sf_source: str | None = None
        sales_values: tuple[float, float] | None = None
        sf_input = subject_sf
        if sf_input is not None:
            sf_source = "subject_sf argument"
        else:
            for container_name, container in (("income", income), ("cost", cost)):
                if not isinstance(container, Mapping):
                    continue
                for key in ("subject_sf", "rentable_sf", "sf"):
                    if container.get(key) is not None:
                        sf_input = container[key]
                        sf_source = f"{container_name}.{key}"
                        break
                if sf_input is not None:
                    break
        if sf_input is not None:
            sf = _number(sf_input, "subject_sf")
            if sf <= 0:
                raise ValueError("subject_sf must be positive when supplied")
            sales_values = (price_psf_range[0] * sf, price_psf_range[1] * sf)

        if not isinstance(cost, Mapping):
            raise ValueError("cost must be a mapping containing land, replacement, and depreciation")
        missing_cost = [key for key in ("land", "replacement", "depreciation") if key not in cost]
        if missing_cost:
            raise ValueError("cost is missing required input(s): " + ", ".join(missing_cost))
        land = _range(cost["land"], "cost.land")
        replacement = _range(cost["replacement"], "cost.replacement")
        depreciation = _range(cost["depreciation"], "cost.depreciation")
        cost_values = (
            land[0] + replacement[0] - depreciation[1],
            land[1] + replacement[1] - depreciation[0],
        )
        if cost_values[0] > cost_values[1]:
            raise ValueError("cost inputs do not produce an ordered value range")

        approaches: dict[str, dict[str, Any]] = {
            "income": {
                "value_range": _as_range(*income_values),
                "noi_range": _as_range(noi_low, noi_high),
                "cap_rate_range": _as_range(cap_low, cap_high),
                "method": "low NOI / high cap through high NOI / low cap",
            },
            "sales_comparison": {
                "value_range": _as_range(*sales_values) if sales_values is not None else None,
                "price_per_sf_range": _as_range(*price_psf_range),
                "subject_sf": sf,
                "subject_sf_source": sf_source,
                "comp_indications": comp_rows,
                "method": (
                    "observed price/SF envelope multiplied by caller-supplied subject_sf"
                    if sf is not None
                    else "price/SF envelope only; no property total is fabricated without subject_sf"
                ),
            },
            "cost": {
                "value_range": _as_range(*cost_values),
                "land_range": _as_range(*land),
                "replacement_range": _as_range(*replacement),
                "depreciation_range": _as_range(*depreciation),
                "method": "land + replacement cost - depreciation",
            },
        }

        explanations = _directional_explanations(
            income_values, sales_values, cost_values
        )
        reconciliation: dict[str, Any] = {
            "method": "explain_divergence_no_automatic_average",
            "weighted_value_range": None,
            "weights": None,
            "statement": (
                "Approach divergence is explained, not averaged. No weighting was "
                "performed because the model does not recommend valuation weights."
            ),
        }
        if weights is not None:
            raw_weights, normalized = _normalize_weights(weights)
            value_ranges = {
                "income": income_values,
                "sales_comparison": sales_values,
                "cost": cost_values,
            }
            unavailable = [
                key for key, weight in normalized.items()
                if weight > 0 and value_ranges[key] is None
            ]
            if unavailable:
                raise ValueError(
                    "positive weight cannot be applied without a total value for: "
                    + ", ".join(unavailable)
                    + "; supply subject_sf for sales comparison"
                )
            weighted_low = sum(
                normalized[key] * value_ranges[key][0]  # type: ignore[index]
                for key in normalized
                if normalized[key] > 0
            )
            weighted_high = sum(
                normalized[key] * value_ranges[key][1]  # type: ignore[index]
                for key in normalized
                if normalized[key] > 0
            )
            reconciliation = {
                "method": "user_directed_weighted_range",
                "weighted_value_range": _as_range(weighted_low, weighted_high),
                "weights": {
                    "supplied": raw_weights,
                    "normalized": normalized,
                    "source": "user choice; not a system recommendation",
                },
                "statement": (
                    "Weighted endpoint arithmetic is shown only because the user supplied "
                    "the weights. The weights are user choices, not a system recommendation; "
                    "the divergence explanations remain controlling context."
                ),
            }

        return {
            "approaches": approaches,
            "divergence_explanations": explanations,
            "divergence_comparison_basis": (
                "Range central indications select directional explanations only; they are "
                "not averaged into a value conclusion."
            ),
            "reconciliation": reconciliation,
            "disclaimer": DISCLAIMER,
        }
    except Exception as exc:  # Public analytical boundary: never leak malformed-input errors.
        return {"error": str(exc)}
