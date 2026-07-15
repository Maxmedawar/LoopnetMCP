"""Transparent fee-simple and partial-property-interest value splits."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


DISCLAIMER = "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
SUPPORTED_INTERESTS = {"fee_simple", "leased_fee", "leasehold", "ground_lease", "air_rights"}


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _range(value: Any, label: str, *, nonnegative: bool = True) -> tuple[float, float]:
    if isinstance(value, Mapping):
        if "low" not in value or "high" not in value:
            raise ValueError(f"{label} range must contain low and high")
        low = _number(value["low"], f"{label}.low")
        high = _number(value["high"], f"{label}.high")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) != 2:
            raise ValueError(f"{label} range must contain exactly two values")
        low = _number(value[0], f"{label}[0]")
        high = _number(value[1], f"{label}[1]")
    else:
        low = high = _number(value, label)
    if low > high:
        raise ValueError(f"{label}.low cannot exceed {label}.high")
    if nonnegative and low < 0:
        raise ValueError(f"{label} cannot be negative")
    return low, high


def _as_range(values: tuple[float, float]) -> dict[str, float]:
    return {"low": values[0], "high": values[1]}


def _subtract(left: tuple[float, float], right: tuple[float, float]) -> tuple[float, float]:
    return left[0] - right[1], left[1] - right[0]


def _add(left: tuple[float, float], right: tuple[float, float]) -> tuple[float, float]:
    return left[0] + right[0], left[1] + right[1]


def _multiply_positive(values: tuple[float, float], factor: float) -> tuple[float, float]:
    products = (values[0] * factor, values[1] * factor)
    return min(products), max(products)


def _annuity_factor(rate: float, years: float) -> float:
    if years == 0:
        return 0.0
    if rate == 0:
        return years
    return (1.0 - (1.0 + rate) ** (-years)) / rate


def _terms_mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("terms must be a mapping")
    return value


def _term(terms: Mapping[str, Any], names: tuple[str, ...], label: str) -> Any:
    for name in names:
        if name in terms:
            return terms[name]
    raise ValueError(f"terms missing {label}")


def _rate(terms: Mapping[str, Any], supplied_rate: Any) -> float:
    raw = supplied_rate
    if raw is None:
        raw = _term(terms, ("discount_rate", "rate"), "discount_rate")
    rate = _number(raw, "discount_rate")
    if rate > 1:
        if rate > 100:
            raise ValueError("discount_rate cannot exceed 100%")
        rate /= 100
    if rate < 0:
        raise ValueError("discount_rate cannot be negative")
    return rate


def _remaining_term(terms: Mapping[str, Any]) -> float:
    years = _number(
        _term(terms, ("remaining_term", "remaining_term_years"), "remaining_term"),
        "terms.remaining_term",
    )
    if years < 0:
        raise ValueError("terms.remaining_term cannot be negative")
    return years


def _base_output(
    interest: str,
    property_range: tuple[float, float],
    selected_range: tuple[float, float] | None,
    method: str,
) -> dict[str, Any]:
    return {
        "status": "analytical_estimate" if selected_range is not None else "requires_additional_analysis",
        "disclaimer": DISCLAIMER,
        "interest": interest,
        "property_value_range": _as_range(property_range),
        "interest_value_range": _as_range(selected_range) if selected_range is not None else None,
        "selected_interest_value_range": _as_range(selected_range) if selected_range is not None else None,
        "method": method,
    }


def _leased_interest_output(
    property_range: tuple[float, float],
    interest: str,
    terms: Mapping[str, Any],
    discount_rate: Any,
) -> dict[str, Any]:
    contract = _range(
        _term(terms, ("contract_rent", "annual_contract_rent"), "contract_rent"),
        "terms.contract_rent",
    )
    market = _range(
        _term(terms, ("market_rent", "annual_market_rent"), "market_rent"),
        "terms.market_rent",
    )
    years = _remaining_term(terms)
    rate = _rate(terms, discount_rate)
    factor = _annuity_factor(rate, years)

    # The tenant's leasehold is signed: below-market rent is positive and
    # above-market rent is negative.  The leased fee is the residual, ensuring
    # fee simple = leased fee + leasehold for point inputs.
    annual_differential = _subtract(market, contract)
    differential_pv = _multiply_positive(annual_differential, factor)
    leasehold = differential_pv
    leased_fee = _subtract(property_range, leasehold)
    selected = leased_fee if interest == "leased_fee" else leasehold
    output = _base_output(
        interest,
        property_range,
        selected,
        "Annual end-of-period level annuity PV of market rent minus contract rent.",
    )
    output.update(
        {
            "fee_simple_value_range": _as_range(property_range),
            "leased_fee_value_range": _as_range(leased_fee),
            "leasehold_value_range": _as_range(leasehold),
            "annual_contract_rent_range": _as_range(contract),
            "annual_market_rent_range": _as_range(market),
            "annual_rent_differential_range": _as_range(annual_differential),
            "rent_differential_pv_range": _as_range(differential_pv),
            "discount_rate": rate,
            "remaining_term_years": years,
            "annuity_factor": factor,
            "calculation": {
                "formula": "PV differential = (market annual rent - contract annual rent) * annuity factor",
                "annuity_factor_formula": (
                    "(1 - (1 + discount_rate)^(-remaining_term_years)) / discount_rate; "
                    "remaining_term_years when discount_rate is zero"
                ),
                "leased_fee_formula": "fee-simple property value - signed leasehold PV",
            },
            "sign_convention": (
                "Positive leasehold value means contract rent is below market (tenant benefit); "
                "negative leasehold value means contract rent is above market."
            ),
            "reconciliation": {
                "identity": "fee simple = leased fee + signed leasehold",
                "interval_sum_range": _as_range(_add(leased_fee, leasehold)),
                "point_input_check": (
                    leased_fee[0] + leasehold[0]
                    if property_range[0] == property_range[1]
                    and leased_fee[0] == leased_fee[1]
                    and leasehold[0] == leasehold[1]
                    else None
                ),
            },
        }
    )
    warnings: list[str] = []
    if leased_fee[0] < 0:
        warnings.append(
            "The supplied fee-simple value and rent differential produce a negative leased-fee bound; "
            "verify that value and rent inputs share a consistent basis."
        )
    if market[0] != market[1] or contract[0] != contract[1] or property_range[0] != property_range[1]:
        warnings.append(
            "Interval arithmetic preserves uncertainty; arbitrary low-plus-low component endpoints need not "
            "equal the fee-simple low endpoint, although the signed point-value identity is unchanged."
        )
    output["warnings"] = warnings
    return output


def _ground_lease_output(
    property_range: tuple[float, float],
    terms: Mapping[str, Any],
    discount_rate: Any,
) -> dict[str, Any]:
    annual_ground_rent = _range(
        _term(terms, ("contract_rent", "ground_rent", "annual_contract_rent"), "contract_rent"),
        "terms.contract_rent",
    )
    reversion = _range(_term(terms, ("reversion", "reversion_value"), "reversion"), "terms.reversion")
    years = _remaining_term(terms)
    rate = _rate(terms, discount_rate)
    factor = _annuity_factor(rate, years)
    rent_stream_pv = _multiply_positive(annual_ground_rent, factor)
    reversion_factor = (1.0 + rate) ** (-years)
    reversion_pv = _multiply_positive(reversion, reversion_factor)
    ground_lease = _add(rent_stream_pv, reversion_pv)
    output = _base_output(
        "ground_lease",
        property_range,
        ground_lease,
        "Ground-lessor value from annual ground-rent annuity plus discounted reversion.",
    )
    output.update(
        {
            "ground_lease_value_range": _as_range(ground_lease),
            "annual_ground_rent_range": _as_range(annual_ground_rent),
            "rent_stream_pv_range": _as_range(rent_stream_pv),
            "reversion_value_range": _as_range(reversion),
            "reversion_pv_range": _as_range(reversion_pv),
            "discount_rate": rate,
            "remaining_term_years": years,
            "annuity_factor": factor,
            "reversion_discount_factor": reversion_factor,
            "calculation": {
                "formula": "ground-lease value = annual contract ground rent * annuity factor + reversion / (1 + rate)^term",
                "cash_flow_timing": "annual rent is modeled at each year-end; reversion is modeled at term-end",
            },
            "scope_note": (
                "This is the ground lessor's stated cash-flow interest. Ground-lessee improvements, reset "
                "clauses, credit risk, taxes, and condemnation provisions require separate analysis."
            ),
        }
    )
    return output


def value_interest_split(
    property_value: Mapping[str, Any] | Sequence[float] | float,
    interest: str,
    terms: Mapping[str, Any] | None,
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Value a stated property interest without implying an appraisal conclusion.

    Contract and market rent inputs are annual dollars.  The supplied discount
    rate accepts a decimal or percentage and can instead be provided in
    ``terms`` as ``discount_rate`` (or ``rate``).
    """
    try:
        property_range = _range(property_value, "property_value")
        if not isinstance(interest, str):
            raise ValueError("interest must be a string")
        normalized_interest = interest.strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized_interest not in SUPPORTED_INTERESTS:
            raise ValueError(
                "interest must be fee_simple, leased_fee, leasehold, ground_lease, or air_rights"
            )
        normalized_terms = _terms_mapping(terms)

        if normalized_interest == "fee_simple":
            output = _base_output(
                normalized_interest,
                property_range,
                property_range,
                "Supplied fee-simple property value range; no partial-interest allocation applied.",
            )
            output["fee_simple_value_range"] = _as_range(property_range)
            return output

        if normalized_interest in {"leased_fee", "leasehold"}:
            return _leased_interest_output(
                property_range,
                normalized_interest,
                normalized_terms,
                discount_rate,
            )

        if normalized_interest == "ground_lease":
            return _ground_lease_output(property_range, normalized_terms, discount_rate)

        output = _base_output(
            "air_rights",
            property_range,
            None,
            "No air-rights value is inferred from the fee-simple property value alone.",
        )
        output.update(
            {
                "analysis_requirement": "requires zoning transfer analysis — see zoning tools",
                "honest_gap": (
                    "Transferable development rights, sending/receiving-site eligibility, unused development "
                    "capacity, legal encumbrances, and local approval have not been established."
                ),
            }
        )
        return output
    except (TypeError, ValueError, OverflowError) as exc:
        return {"error": f"value_interest_split: {exc}"}
    except Exception as exc:  # Boundary guarantee for hostile mapping/sequence implementations.
        return {"error": f"value_interest_split: invalid input ({exc})"}
