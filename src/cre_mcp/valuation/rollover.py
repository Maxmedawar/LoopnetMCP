"""Probability-weighted suite rollover costs and rental NOI paths.

The model is deliberately transparent: its renewal probabilities and leasing-cost
conventions are screening assumptions, not tenant-level forecasts.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any, Mapping, Sequence


DISCLAIMER = "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"

DEFAULT_RENEWAL_PROBABILITIES: dict[str, float] = {
    "office": 0.65,
    "retail": 0.70,
    "industrial": 0.75,
    "medical_office": 0.70,
    "multifamily": 0.50,
    "other": 0.65,
}


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


def _as_range(low: float, high: float) -> dict[str, float]:
    return {"low": low, "high": high}


def _probability(value: Any, label: str) -> float:
    probability = _number(value, label)
    if probability > 1:
        if probability > 100:
            raise ValueError(f"{label} cannot exceed 100%")
        probability /= 100
    if not 0 <= probability <= 1:
        raise ValueError(f"{label} must be between 0 and 1 or 0% and 100%")
    return probability


def _probability_range(value: Any, label: str) -> tuple[float, float]:
    low, high = _range(value, label)
    normalized = (
        _probability(low, f"{label}.low"),
        _probability(high, f"{label}.high"),
    )
    if normalized[0] > normalized[1]:
        raise ValueError(f"{label} mixes incompatible decimal and percent endpoints")
    return normalized


def _analysis_date(value: Any) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("analysis_date must be an ISO date (YYYY-MM-DD)") from exc
    raise ValueError("analysis_date must be an ISO date (YYYY-MM-DD) or date object")


def _expiry_hold_month(value: Any, start: date) -> tuple[int, str]:
    """Return a one-based hold month and the parsing convention used."""
    if isinstance(value, bool):
        raise ValueError("expiry must be an ISO date, four-digit year, or hold month")
    if isinstance(value, (int, float)):
        numeric = _number(value, "expiry")
        if not numeric.is_integer():
            raise ValueError("numeric expiry must be a whole hold month or four-digit year")
        integer = int(numeric)
        if 1900 <= integer <= 2200:
            expiry_date = date(integer, 12, 31)
            months = (expiry_date.year - start.year) * 12 + expiry_date.month - start.month + 1
            return max(1, months), "four-digit year treated as December 31 of that year"
        if integer < 1:
            raise ValueError("hold-month expiry must be at least 1")
        return integer, "numeric expiry treated as one-based hold month"
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        months = (value.year - start.year) * 12 + value.month - start.month + 1
        return max(1, months), "date mapped to its one-based hold month"
    if not isinstance(value, str):
        raise ValueError("expiry must be an ISO date, four-digit year, or hold month")
    cleaned = value.strip()
    if re.fullmatch(r"\d{4}", cleaned):
        return _expiry_hold_month(int(cleaned), start)
    hold_match = re.fullmatch(r"(?:hold[ _-]?month|month)\s*[:#-]?\s*(\d+)", cleaned, re.IGNORECASE)
    if hold_match:
        return int(hold_match.group(1)), "labeled expiry treated as one-based hold month"
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError("expiry must be an ISO date, four-digit year, or hold month") from exc
    return _expiry_hold_month(parsed, start)


def _field(suite: Mapping[str, Any], names: tuple[str, ...], label: str) -> Any:
    for name in names:
        if name in suite:
            return suite[name]
    raise ValueError(f"missing {label}")


def _tenant_key(value: Any) -> str:
    cleaned = str(value if value is not None else "other").strip().casefold()
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return cleaned or "other"


def _probability_conventions(value: Any) -> dict[str, float]:
    conventions = dict(DEFAULT_RENEWAL_PROBABILITIES)
    if value is None:
        return conventions
    if not isinstance(value, Mapping):
        raise ValueError("renewal_probability_conventions must be a mapping")
    for raw_key, raw_probability in value.items():
        key = _tenant_key(raw_key)
        probability = _probability(
            raw_probability, f"renewal_probability_conventions.{key}"
        )
        conventions[key] = probability
    return conventions


def _vacant_fraction(month_after_rollover: int, downtime_months: float) -> float:
    """Fraction of a modeled month vacant for a non-renewing tenant."""
    return min(1.0, max(0.0, downtime_months - month_after_rollover))


def suite_rollover_model(
    suites: Sequence[Mapping[str, Any]],
    hold_years: float = 5,
    analysis_date: str | date | datetime | None = None,
    renewal_probability_conventions: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Model suite-level expected rollover costs and blended rental NOI.

    ``current_rent_psf`` and ``market_rent_psf`` are annual rents.  A suite can
    override its tenant-type convention with ``renewal_prob``.  No operating
    expense inputs are present, so the annual path is explicitly a rental-NOI
    proxy rather than a full property NOI forecast.
    """
    try:
        if isinstance(suites, (str, bytes, bytearray)) or not isinstance(suites, Sequence):
            raise ValueError("suites must be a sequence of suite mappings")
        if not suites:
            raise ValueError("suites must contain at least one suite")
        years = _number(hold_years, "hold_years")
        if years <= 0:
            raise ValueError("hold_years must be greater than zero")
        hold_months = int(math.ceil(years * 12.0 - 1e-12))
        start = _analysis_date(analysis_date)
        conventions = _probability_conventions(renewal_probability_conventions)

        rows: list[dict[str, Any]] = []
        monthly_low = [0.0 for _ in range(hold_months)]
        monthly_high = [0.0 for _ in range(hold_months)]
        total_sf = 0.0
        total_cost_low = 0.0
        total_cost_high = 0.0
        hold_cost_low = 0.0
        hold_cost_high = 0.0
        sf_downtime_low = 0.0
        sf_downtime_high = 0.0
        hold_sf_downtime_low = 0.0
        hold_sf_downtime_high = 0.0

        for index, raw_suite in enumerate(suites):
            if not isinstance(raw_suite, Mapping):
                raise ValueError(f"suites[{index}] must be a mapping")
            suite = raw_suite
            label = str(suite.get("id", suite.get("suite", index + 1)))
            sf = _number(_field(suite, ("sf",), f"suites[{index}].sf"), f"suites[{index}].sf")
            if sf <= 0:
                raise ValueError(f"suites[{index}].sf must be greater than zero")
            current = _range(
                _field(suite, ("current_rent_psf",), f"suites[{index}].current_rent_psf"),
                f"suites[{index}].current_rent_psf",
            )
            market = _range(
                _field(suite, ("market_rent_psf",), f"suites[{index}].market_rent_psf"),
                f"suites[{index}].market_rent_psf",
            )
            downtime = _range(
                _field(suite, ("months_downtime",), f"suites[{index}].months_downtime"),
                f"suites[{index}].months_downtime",
            )
            ti_new = _range(
                _field(suite, ("ti_new_psf", "ti_new"), f"suites[{index}].ti_new_psf"),
                f"suites[{index}].ti_new_psf",
            )
            ti_renew = _range(
                _field(suite, ("ti_renew_psf", "ti_renew"), f"suites[{index}].ti_renew_psf"),
                f"suites[{index}].ti_renew_psf",
            )
            lc = _probability_range(
                _field(suite, ("lc_pct",), f"suites[{index}].lc_pct"),
                f"suites[{index}].lc_pct",
            )

            tenant_type = _tenant_key(suite.get("tenant_type", "other"))
            if "renewal_prob" in suite:
                probability = _probability(
                    suite["renewal_prob"], f"suites[{index}].renewal_prob"
                )
                probability_source = "suite input"
            else:
                probability = conventions.get(tenant_type, conventions["other"])
                probability_source = f"{tenant_type} tenant-type convention"
            expiry_value = _field(suite, ("expiry", "expiry_date", "expiry_month"), f"suites[{index}].expiry")
            rollover_month, expiry_convention = _expiry_hold_month(expiry_value, start)
            within_hold = rollover_month <= hold_months
            nonrenewal = 1.0 - probability

            renewal_ti = (probability * sf * ti_renew[0], probability * sf * ti_renew[1])
            new_ti = (nonrenewal * sf * ti_new[0], nonrenewal * sf * ti_new[1])
            annual_market = (sf * market[0], sf * market[1])
            expected_lc = (
                nonrenewal * annual_market[0] * lc[0],
                nonrenewal * annual_market[1] * lc[1],
            )
            downtime_loss = (
                nonrenewal * annual_market[0] * downtime[0] / 12.0,
                nonrenewal * annual_market[1] * downtime[1] / 12.0,
            )
            expected_downtime = (nonrenewal * downtime[0], nonrenewal * downtime[1])
            expected_cost = (
                renewal_ti[0] + new_ti[0] + expected_lc[0] + downtime_loss[0],
                renewal_ti[1] + new_ti[1] + expected_lc[1] + downtime_loss[1],
            )

            for hold_month_index in range(hold_months):
                one_based_month = hold_month_index + 1
                if one_based_month < rollover_month:
                    monthly_low[hold_month_index] += sf * current[0] / 12.0
                    monthly_high[hold_month_index] += sf * current[1] / 12.0
                    continue
                month_after = one_based_month - rollover_month
                low_vacancy = _vacant_fraction(month_after, downtime[1])
                high_vacancy = _vacant_fraction(month_after, downtime[0])
                monthly_low[hold_month_index] += (
                    annual_market[0] * (1.0 - nonrenewal * low_vacancy) / 12.0
                )
                monthly_high[hold_month_index] += (
                    annual_market[1] * (1.0 - nonrenewal * high_vacancy) / 12.0
                )

            row = {
                "suite": label,
                "sf": sf,
                "tenant_type": tenant_type,
                "renewal_probability": probability,
                "renewal_probability_source": probability_source,
                "rollover_hold_month": rollover_month,
                "expiry_convention": expiry_convention,
                "within_hold": within_hold,
                "annual_current_rent": _as_range(sf * current[0], sf * current[1]),
                "annual_market_rent": _as_range(*annual_market),
                "expected_downtime_months": _as_range(*expected_downtime),
                "weighted_downtime_months": _as_range(*expected_downtime),
                "expected_rollover_cost": _as_range(*expected_cost),
                "expected_rollover_cost_range": _as_range(*expected_cost),
                "expected_cost_components": {
                    "renewal_ti": _as_range(*renewal_ti),
                    "new_tenant_ti": _as_range(*new_ti),
                    "new_tenant_lc": _as_range(*expected_lc),
                    "rent_lost_to_downtime": _as_range(*downtime_loss),
                },
            }
            rows.append(row)
            total_sf += sf
            total_cost_low += expected_cost[0]
            total_cost_high += expected_cost[1]
            sf_downtime_low += sf * expected_downtime[0]
            sf_downtime_high += sf * expected_downtime[1]
            if within_hold:
                hold_cost_low += expected_cost[0]
                hold_cost_high += expected_cost[1]
                hold_sf_downtime_low += sf * expected_downtime[0]
                hold_sf_downtime_high += sf * expected_downtime[1]

        annual_path: list[dict[str, Any]] = []
        for year_index, start_month in enumerate(range(0, hold_months, 12), start=1):
            stop_month = min(start_month + 12, hold_months)
            annual_path.append(
                {
                    "hold_year": year_index,
                    "months_modeled": stop_month - start_month,
                    "blended_noi": _as_range(
                        sum(monthly_low[start_month:stop_month]),
                        sum(monthly_high[start_month:stop_month]),
                    ),
                }
            )

        portfolio = {
            "total_sf": total_sf,
            "expected_rollover_cost_all_suites": _as_range(total_cost_low, total_cost_high),
            "expected_rollover_cost_within_hold": _as_range(hold_cost_low, hold_cost_high),
            "sf_weighted_expected_downtime_months": _as_range(
                sf_downtime_low / total_sf,
                sf_downtime_high / total_sf,
            ),
            "sf_weighted_expected_downtime_months_within_hold": _as_range(
                hold_sf_downtime_low / total_sf,
                hold_sf_downtime_high / total_sf,
            ),
        }
        portfolio["weighted_downtime_months"] = portfolio[
            "sf_weighted_expected_downtime_months"
        ]
        return {
            "status": "analytical_estimate",
            "disclaimer": DISCLAIMER,
            "analysis_date": start.isoformat(),
            "hold_years": years,
            "hold_months": hold_months,
            "suites": rows,
            "portfolio": portfolio,
            "annual_blended_noi_path": annual_path,
            "blended_noi_path": annual_path,
            "conventions": {
                "renewal_probabilities_by_tenant_type": conventions,
                "renewal_probability_note": (
                    "User-supplied suite renewal_prob overrides the tenant-type convention; "
                    "these are conventions, not predictions."
                ),
                "rent_basis": "current and market rent PSF are annual amounts",
                "downtime": (
                    "Only the non-renewal branch incurs downtime; fractional months are prorated "
                    "in the monthly path."
                ),
                "leasing_commission": (
                    "lc_pct is a decimal applied to one year of market rent because no new-lease "
                    "term was supplied."
                ),
                "rollover_cost": (
                    "P(renew)*renewal TI + P(new)*(new TI + first-year-rent LC + market-rent downtime)."
                ),
                "noi_path": (
                    "Rent-only blended NOI proxy: current rent before rollover and probability-weighted "
                    "market rent/downtime after rollover; operating expenses are not supplied."
                ),
            },
        }
    except (TypeError, ValueError, OverflowError) as exc:
        return {"error": f"suite_rollover_model: {exc}"}
    except Exception as exc:  # Boundary guarantee for hostile mapping/sequence implementations.
        return {"error": f"suite_rollover_model: invalid input ({exc})"}
