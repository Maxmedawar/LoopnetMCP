"""Calculate contractual monthly rent from a cited lease abstraction.

The calculator performs arithmetic, not data acquisition.  CPI index values and
tenant sales are caller inputs; when a cited formula needs an omitted input the
affected cash total is ``None`` and the missing input is named explicitly.
"""

from __future__ import annotations

import calendar
import math
from datetime import date, datetime, timedelta
from typing import Mapping

from cre_mcp.leases.models import CitedClaim, LeaseAbstract, RentPeriod


def _date(value: date | datetime | str, *, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO date") from exc
    raise ValueError(f"{name} must be a date, datetime, or ISO date string")


def _claim_date(claim: CitedClaim) -> date | None:
    if claim.status == "missing" or not isinstance(claim.value, str):
        return None
    try:
        return date.fromisoformat(claim.value)
    except ValueError:
        return None


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _month_end(value: date) -> date:
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def _proration(start: date, end: date, convention: str) -> float:
    if convention == "actual_days":
        return (end - start).days + 1
    if convention != "30_day":
        raise ValueError("proration_convention must be 'actual_days' or '30_day'")
    last_day = calendar.monthrange(end.year, end.month)[1]
    start_day = min(start.day, 30)
    end_day = 30 if end.day == last_day else min(end.day, 30)
    return max(0, end_day - start_day + 1)


def _month_denominator(month: date, convention: str) -> int:
    return calendar.monthrange(month.year, month.month)[1] if convention == "actual_days" else 30


def _period_bounds(
    abstract: LeaseAbstract,
    period: RentPeriod,
    total_periods: int,
) -> tuple[date, date] | None:
    start = _claim_date(period.start)
    end = _claim_date(period.end)
    if start is not None and end is not None and start <= end:
        return start, end
    if total_periods == 1:
        start = start or _claim_date(abstract.dates.commencement)
        end = end or _claim_date(abstract.dates.expiration)
        if start is not None and end is not None and start <= end:
            return start, end
    return None


def _monthly_amount(period: RentPeriod) -> float | None:
    if period.monthly.status != "missing":
        return _number("monthly rent", period.monthly.value)
    if period.annual.status != "missing":
        return _number("annual rent", period.annual.value) / 12.0
    return None


def _annual_amount(period: RentPeriod) -> float | None:
    if period.annual.status != "missing":
        return _number("annual rent", period.annual.value)
    monthly = _monthly_amount(period)
    return monthly * 12.0 if monthly is not None else None


def _index_date(key: object) -> date:
    if isinstance(key, datetime):
        return key.date()
    if isinstance(key, date):
        return key
    if isinstance(key, int):
        return date(key, 1, 1)
    if isinstance(key, str):
        if key.casefold() in {"base", "current"}:
            return date.min if key.casefold() == "base" else date.max
        if re_full_year(key):
            return date(int(key), 1, 1)
        try:
            return date.fromisoformat(key if len(key) != 7 else key + "-01")
        except ValueError as exc:
            raise ValueError("CPI/sales mapping keys must be dates, years, or ISO date strings") from exc
    raise ValueError("CPI/sales mapping keys must be dates, years, or ISO date strings")


def re_full_year(value: str) -> bool:
    return len(value) == 4 and value.isdigit()


def _indices(values: Mapping[object, float] | None) -> list[tuple[date, float]]:
    if values is None:
        return []
    normalized = [(_index_date(key), _number("CPI index", value)) for key, value in values.items()]
    if any(value <= 0 for _, value in normalized):
        raise ValueError("CPI index values must be positive")
    normalized.sort(key=lambda item: item[0])
    return normalized


def _cpi_factor(abstract: LeaseAbstract, when: date, values: list[tuple[date, float]]) -> float | None:
    if abstract.escalations.cpi_index.status == "missing":
        return 1.0
    if not values:
        return None
    base_value = values[0][1]
    available = [value for effective, value in values if effective <= when]
    current = values[-1][1] if values[-1][0] == date.max else (available[-1] if available else base_value)
    increase = current / base_value - 1.0
    if abstract.escalations.cpi_floor_pct.status != "missing":
        increase = max(increase, _number("CPI floor", abstract.escalations.cpi_floor_pct.value))
    if abstract.escalations.cpi_cap_pct.status != "missing":
        increase = min(increase, _number("CPI cap", abstract.escalations.cpi_cap_pct.value))
    return 1.0 + increase


def _sales_value(sales: float | Mapping[object, float] | None, month: date) -> float | None:
    if sales is None:
        return None
    if isinstance(sales, Mapping):
        exact: float | None = None
        annual: float | None = None
        for key, value in sales.items():
            number = _number("sales", value)
            if isinstance(key, int) or (isinstance(key, str) and re_full_year(key)):
                if int(key) == month.year:
                    annual = number
                continue
            effective = _index_date(key)
            if (effective.year, effective.month) == (month.year, month.month):
                exact = number
        return exact if exact is not None else annual
    return _number("sales", sales)


def _percentage_rent(
    abstract: LeaseAbstract,
    period: RentPeriod,
    month_sales: float | None,
    proration_factor: float,
) -> tuple[float | None, str | None]:
    if abstract.escalations.percentage_rent.status == "missing":
        return 0.0, None
    if month_sales is None:
        return None, "sales"
    if abstract.escalations.percentage_rate.status == "missing":
        return None, "percentage_rate"
    rate = _number("percentage rent rate", abstract.escalations.percentage_rate.value)
    if rate < 0:
        raise ValueError("percentage rent rate must be non-negative")
    breakpoint: float | None = None
    if abstract.escalations.percentage_breakpoint.status != "missing":
        breakpoint = _number("percentage rent breakpoint", abstract.escalations.percentage_breakpoint.value)
    elif (
        abstract.escalations.percentage_breakpoint_type.status != "missing"
        and abstract.escalations.percentage_breakpoint_type.value == "natural"
        and rate > 0
    ):
        annual = _annual_amount(period)
        breakpoint = annual / rate if annual is not None else None
    if breakpoint is None:
        return None, "percentage_breakpoint"
    monthly_breakpoint = breakpoint / 12.0
    return max(0.0, month_sales - monthly_breakpoint) * rate * proration_factor, None


def rent_schedule(
    abstract: LeaseAbstract,
    start: date | datetime | str,
    end: date | datetime | str,
    sales: float | Mapping[object, float] | None = None,
    cpi_values: Mapping[object, float] | None = None,
    proration_convention: str = "actual_days",
    *,
    convention: str | None = None,
) -> list[dict[str, object]]:
    """Calculate one row per calendar month, including partial-month rent.

    ``sales`` is a monthly sales amount or a mapping keyed by month/date.
    Percentage breakpoints are treated as annual and divided by twelve.  CPI
    mappings are ordered index observations; the earliest is the base index.
    """
    start_date = _date(start, name="start")
    end_date = _date(end, name="end")
    if start_date > end_date:
        raise ValueError("start must be on or before end")
    if convention is not None:
        proration_convention = convention
    if proration_convention not in {"actual_days", "30_day"}:
        raise ValueError("proration_convention must be 'actual_days' or '30_day'")
    indices = _indices(cpi_values)
    periods: list[tuple[RentPeriod, date, date]] = []
    for period in abstract.rent_schedule:
        bounds = _period_bounds(abstract, period, len(abstract.rent_schedule))
        if bounds is not None and _monthly_amount(period) is not None:
            periods.append((period, *bounds))

    rows: list[dict[str, object]] = []
    month = date(start_date.year, start_date.month, 1)
    while month <= end_date:
        month_last = _month_end(month)
        query_start = max(start_date, month)
        query_end = min(end_date, month_last)
        denominator = _month_denominator(month, proration_convention)
        base_total = 0.0
        pct_total = 0.0
        coverage = 0.0
        missing_inputs: set[str] = set()
        source_quotes: list[str] = []
        applicable = False

        for period, period_start, period_end in periods:
            overlap_start = max(query_start, period_start)
            overlap_end = min(query_end, period_end)
            if overlap_start > overlap_end:
                continue
            applicable = True
            factor = _proration(overlap_start, overlap_end, proration_convention) / denominator
            coverage += factor
            monthly = _monthly_amount(period)
            cpi = _cpi_factor(abstract, overlap_start, indices)
            if cpi is None:
                missing_inputs.add("cpi_values")
            elif monthly is not None:
                base_total += monthly * cpi * factor
            month_sales = _sales_value(sales, month)
            pct, missing = _percentage_rent(abstract, period, month_sales, factor)
            if missing:
                missing_inputs.add(missing)
            elif pct is not None:
                pct_total += pct
            source = period.monthly if period.monthly.status != "missing" else period.annual
            if source.quote and source.quote not in source_quotes:
                source_quotes.append(source.quote)

        if not applicable:
            status = "uncovered"
            base_value: float | None = None
            pct_value: float | None = None
            total: float | None = None
        elif missing_inputs:
            status = "missing_inputs"
            base_value = None if "cpi_values" in missing_inputs else round(base_total, 2)
            pct_value = None if {"sales", "percentage_rate", "percentage_breakpoint"} & missing_inputs else round(pct_total, 2)
            total = None
        else:
            status = "calculated"
            base_value = round(base_total, 2)
            pct_value = round(pct_total, 2)
            total = round(base_total + pct_total, 2)
        rows.append({
            "month": month.strftime("%Y-%m"),
            "period_start": query_start.isoformat(),
            "period_end": query_end.isoformat(),
            "proration_factor": round(min(1.0, coverage), 8),
            "base_rent": base_value,
            "percentage_rent": pct_value,
            "total_cash_rent": total,
            "status": status,
            "missing_inputs": sorted(missing_inputs),
            "source_quotes": source_quotes,
            "proration_convention": proration_convention,
        })
        month = _next_month(month)
    return rows


__all__ = ["rent_schedule"]
