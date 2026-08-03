"""Auditable tenant NOI paths and arithmetic forecast-to-actual attribution.

Money inputs and outputs are integer cents.  Rates may be decimals (``0.95``)
or percentages (``95``); the normalization convention is always returned with
the result.  Property books are consumed read-only: their scheduled tenant
charges are evidence for contract rent, but they are not mistaken for a full
operating-expense ledger.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from cre_mcp.books import BookStore


_RATE_KEYS = ("occupancy", "occupancy_rate")
_POTENTIAL_RENT_KEYS = (
    "potential_rent_cents",
    "gross_potential_rent_cents",
    "gpr_cents",
)
_OPEX_KEYS = ("opex_cents", "operating_expenses_cents", "expense_cents")
_OTHER_INCOME_KEYS = ("other_income_cents", "recoveries_cents")
_TIMING_KEYS = ("timing_cents", "timing_adjustment_cents")
_NOI_KEYS = ("noi_cents", "reported_noi_cents", "total_noi_cents")
_EXPECTED_OPERATING_KEYS = (
    "potential_rent_cents",
    "occupancy",
    "other_income_cents",
    "timing_cents",
    "opex_cents",
)
_REVENUE_SHAPED_PARTS = (
    "rent",
    "income",
    "gpr",
    "revenue",
    "vacanc",
    "occupanc",
)
_KNOWN_META_KEYS = {
    "actual_period",
    "as_of",
    "books_basis",
    "deal_id",
    "label",
    "note",
    "notes",
    "period",
    "source",
    "source_detail",
}
_LINE_AMOUNT_KEYS = {
    "actual_cents",
    "amount_cents",
    "budget_cents",
    "value_cents",
}
_LINE_ITEM_KEYS = _LINE_AMOUNT_KEYS | {
    "category",
    "description",
    "driver",
    "item",
    "line",
    "name",
    "noi_sign",
    "note",
    "notes",
    "period",
    "source",
    "source_detail",
}
_TENANCY_INPUT_KEYS = {
    "active",
    "annual_contract_rent_cents",
    "annual_market_rent_growth",
    "annual_opex_cents",
    "annual_rent_cents",
    "contract_rent_schedule",
    "deal_id",
    "downtime_months",
    "expense_ratio",
    "expiration",
    "id",
    "input_source",
    "lease_end",
    "lease_expiration",
    "lease_ref",
    "market_rent_cents_monthly",
    "market_rent_growth",
    "monthly_contract_rent_cents",
    "monthly_market_rent_cents",
    "monthly_opex_cents",
    "monthly_other_income_cents",
    "monthly_rent_cents",
    "name",
    "opex_cents_annual",
    "opex_cents_monthly",
    "opex_ratio",
    "other_income_cents_monthly",
    "other_income_schedule",
    "renewal_probability",
    "rent_cents",
    "rent_schedule",
    "retention_rate",
    "rollover_date",
    "rollover_downtime_months",
    "suite",
    "tenancy_id",
    "tenant",
    "tenant_id",
    "tenant_name",
    "unit",
    "unit_id",
}
_MARKET_ASSUMPTION_KEYS = {
    "annual_market_rent_growth",
    "as_of",
    "contract_rent_cents_by_unit",
    "deal_id",
    "downtime_months",
    "expense_ratio",
    "horizon_months",
    "market_rent_cents_by_unit",
    "market_rent_cents_monthly",
    "market_rent_growth",
    "monthly_market_rent_cents",
    "monthly_opex_cents",
    "monthly_other_income_cents",
    "months",
    "note",
    "notes",
    "opex_cents_by_unit",
    "opex_cents_monthly",
    "opex_ratio",
    "other_income_cents_by_unit",
    "other_income_cents_monthly",
    "period",
    "renewal_probability",
    "retention_rate",
    "rollover_downtime_months",
    "source",
    "start_period",
}
_SCHEDULE_META_KEYS = {"note", "notes", "source", "source_detail"}


def _cents(value: Any, *, name: str, non_negative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if non_negative and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _optional_cents(
    values: Mapping[str, Any], keys: Sequence[str], *, non_negative: bool = False
) -> int | None:
    for key in keys:
        if key in values and values[key] is not None:
            return _cents(values[key], name=key, non_negative=non_negative)
    return None


def _decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _rate(value: Any, *, name: str) -> Decimal:
    result = _decimal(value, name=name)
    if abs(result) > 1:
        result /= Decimal(100)
    if result < 0 or result > 1:
        raise ValueError(f"{name} must be between 0 and 1 (or 0 and 100 percent)")
    return result


def _growth_rate(value: Any, *, name: str) -> Decimal:
    result = _decimal(value, name=name)
    if abs(result) > 1:
        result /= Decimal(100)
    if result <= -1:
        raise ValueError(f"{name} must be greater than -100 percent")
    return result


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _first(values: Mapping[str, Any], keys: Sequence[str]) -> Any | None:
    for key in keys:
        if key in values and values[key] is not None:
            return values[key]
    return None


def _revenue_shaped(key: str) -> bool:
    normalized = key.casefold()
    return any(part in normalized for part in _REVENUE_SHAPED_PARTS)


def _explicit_line_unrecognized(
    raw_lines: Any, *, source: str
) -> list[tuple[str, str]]:
    unrecognized: list[tuple[str, str]] = []
    if isinstance(raw_lines, Mapping):
        for raw_name, raw_value in raw_lines.items():
            if not isinstance(raw_value, Mapping):
                continue
            prefix = f"{source}.lines.{raw_name}"
            for raw_key in raw_value:
                key = str(raw_key)
                if key not in _LINE_ITEM_KEYS:
                    unrecognized.append((f"{prefix}.{key}", key))
    elif isinstance(raw_lines, Sequence) and not isinstance(raw_lines, (str, bytes)):
        for index, raw_value in enumerate(raw_lines):
            if not isinstance(raw_value, Mapping):
                continue
            prefix = f"{source}.lines[{index}]"
            for raw_key in raw_value:
                key = str(raw_key)
                if key not in _LINE_ITEM_KEYS:
                    unrecognized.append((f"{prefix}.{key}", key))
    return unrecognized


def _nested_line_unrecognized(
    values: Mapping[str, Any], *, source: str, top_level: bool = True
) -> list[tuple[str, str]]:
    unrecognized: list[tuple[str, str]] = []
    for raw_key, value in values.items():
        key = str(raw_key)
        path = f"{source}.{key}"
        if key in _KNOWN_META_KEYS:
            continue
        if top_level and key in _NOI_KEYS:
            continue
        if isinstance(value, Mapping):
            unrecognized.extend(
                _nested_line_unrecognized(value, source=path, top_level=False)
            )
        elif key.endswith("_cents") and key not in _POTENTIAL_RENT_KEYS:
            continue
        else:
            unrecognized.append((path, key))
    return unrecognized


def _variance_unrecognized(
    values: Mapping[str, Any],
    *,
    source: str,
    operating_shape: bool,
    book_actuals_shape: bool = False,
) -> list[tuple[str, str]]:
    accepted_operating = set(
        _RATE_KEYS
        + _POTENTIAL_RENT_KEYS
        + _OPEX_KEYS
        + _OTHER_INCOME_KEYS
        + _TIMING_KEYS
        + _NOI_KEYS
    )
    if operating_shape:
        allowed = accepted_operating | _KNOWN_META_KEYS
        if book_actuals_shape:
            allowed.add("actual_opex_cents")
        return [
            (f"{source}.{raw_key}", str(raw_key))
            for raw_key in values
            if str(raw_key) not in allowed
        ]
    if "lines" in values:
        allowed = _NOI_KEYS + tuple(_KNOWN_META_KEYS) + ("lines",)
        if book_actuals_shape:
            allowed += ("actual_opex_cents",)
        unrecognized = [
            (f"{source}.{raw_key}", str(raw_key))
            for raw_key in values
            if str(raw_key) not in allowed
        ]
        unrecognized.extend(
            _explicit_line_unrecognized(values.get("lines"), source=source)
        )
        return unrecognized
    unrecognized = _nested_line_unrecognized(values, source=source)
    if book_actuals_shape:
        unrecognized = [
            item for item in unrecognized if item[1] != "actual_opex_cents"
        ]
    return unrecognized


def _unrecognized_names(items: Sequence[tuple[str, str]]) -> list[str]:
    return sorted({path for path, _key in items})


def _unrecognized_revenue_names(
    items: Sequence[tuple[str, str]],
) -> list[str]:
    return sorted({path for path, key in items if _revenue_shaped(key)})


def _unrecognized_revenue_result(
    items: Sequence[tuple[str, str]], *, context: str
) -> dict[str, Any]:
    unrecognized = _unrecognized_names(items)
    revenue_shaped = _unrecognized_revenue_names(items)
    expected = list(_EXPECTED_OPERATING_KEYS)
    message = (
        f"{context} is not computable because revenue-shaped inputs were not "
        f"consumed: {', '.join(revenue_shaped)}. Expected operating keys are "
        f"{', '.join(expected)}; alternatively use explicit lines with "
        "amount_cents, driver, and noi_sign."
    )
    return {
        "error": message,
        "not_computable": [message],
        "unrecognized_inputs": unrecognized,
        "expected_operating_keys": expected,
        "budget_noi_cents": None,
        "actual_noi_cents": None,
        "total_delta_cents": None,
        "drivers": None,
        "attribution": None,
        "lines": [],
        "decomposition_check": {
            "sum_driver_cents": None,
            "total_delta_cents": None,
            "difference_cents": None,
            "exact": False,
        },
    }


def _noi_input_unrecognized(
    tenancies: Sequence[Mapping[str, Any]], assumptions: Mapping[str, Any]
) -> list[tuple[str, str]]:
    unrecognized: list[tuple[str, str]] = []
    for raw_key in assumptions:
        key = str(raw_key)
        if key not in _MARKET_ASSUMPTION_KEYS:
            unrecognized.append((f"market_assumptions.{key}", key))
    for index, tenancy in enumerate(tenancies):
        for raw_key, value in tenancy.items():
            key = str(raw_key)
            if key not in _TENANCY_INPUT_KEYS:
                unrecognized.append((f"tenancies[{index}].{key}", key))
                continue
            if key not in {
                "contract_rent_schedule",
                "other_income_schedule",
                "rent_schedule",
            }:
                continue
            amount_keys = (
                {"amount_cents", "other_income_cents"}
                if key == "other_income_schedule"
                else {"amount_cents", "monthly_rent_cents", "rent_cents"}
            )
            if isinstance(value, Mapping):
                schedule_rows = list(value.items())
                for period, schedule_value in schedule_rows:
                    if not isinstance(schedule_value, Mapping):
                        continue
                    for raw_schedule_key in schedule_value:
                        schedule_key = str(raw_schedule_key)
                        if schedule_key not in amount_keys | _SCHEDULE_META_KEYS:
                            unrecognized.append(
                                (
                                    f"tenancies[{index}].{key}.{period}.{schedule_key}",
                                    schedule_key,
                                )
                            )
                continue
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                continue
            allowed_row_keys = amount_keys | _SCHEDULE_META_KEYS | {
                "month",
                "period",
                "start",
            }
            for row_index, schedule_value in enumerate(value):
                if not isinstance(schedule_value, Mapping):
                    continue
                for raw_schedule_key in schedule_value:
                    schedule_key = str(raw_schedule_key)
                    if schedule_key not in allowed_row_keys:
                        unrecognized.append(
                            (
                                f"tenancies[{index}].{key}[{row_index}].{schedule_key}",
                                schedule_key,
                            )
                        )
    return unrecognized


def _noi_unrecognized_revenue_result(
    items: Sequence[tuple[str, str]], *, deal_id: str | None, source: str
) -> dict[str, Any]:
    unrecognized = _unrecognized_names(items)
    revenue_shaped = _unrecognized_revenue_names(items)
    accepted = {
        "tenancy": sorted(_TENANCY_INPUT_KEYS),
        "market_assumptions": sorted(_MARKET_ASSUMPTION_KEYS),
    }
    message = (
        "tenant NOI forecast is not computable because revenue-shaped inputs "
        f"were not consumed: {', '.join(revenue_shaped)}. Use the accepted "
        "tenancy and market-assumption keys returned with this error."
    )
    return {
        "deal_id": deal_id,
        "source": source,
        "error": message,
        "not_computable": [message],
        "unrecognized_inputs": unrecognized,
        "accepted_input_keys": accepted,
        "per_tenant": [],
        "tenants": [],
        "portfolio_path": [],
    }


def _present(values: Mapping[str, Any], keys: Sequence[str]) -> bool:
    return any(key in values and values[key] is not None for key in keys)


def _noi_corrupting_revenue_names(
    items: Sequence[tuple[str, str]],
    tenancies: Sequence[Mapping[str, Any]],
    assumptions: Mapping[str, Any],
) -> list[str]:
    corrupting: list[str] = []
    for path, key in items:
        if not _revenue_shaped(key):
            continue
        normalized = key.casefold()
        if "vacanc" in normalized or "occupanc" in normalized:
            corrupting.append(path)
            continue
        values: Mapping[str, Any] = assumptions
        if path.startswith("tenancies["):
            raw_index = path[len("tenancies[") :].split("]", 1)[0]
            try:
                values = tenancies[int(raw_index)]
            except (ValueError, IndexError):
                corrupting.append(path)
                continue
        if "income" in normalized:
            has_equivalent = _present(
                values,
                (
                    "monthly_other_income_cents",
                    "other_income_cents_monthly",
                    "other_income_schedule",
                ),
            ) or _present(
                assumptions,
                (
                    "monthly_other_income_cents",
                    "other_income_cents_monthly",
                    "other_income_cents_by_unit",
                ),
            )
        elif "market" in normalized or "growth" in normalized:
            has_equivalent = _present(
                values,
                (
                    "annual_market_rent_growth",
                    "market_rent_cents_monthly",
                    "market_rent_growth",
                    "monthly_market_rent_cents",
                ),
            ) or _present(
                assumptions,
                (
                    "annual_market_rent_growth",
                    "market_rent_cents_by_unit",
                    "market_rent_cents_monthly",
                    "market_rent_growth",
                    "monthly_market_rent_cents",
                ),
            )
        elif "rent" in normalized:
            has_equivalent = _present(
                values,
                (
                    "annual_contract_rent_cents",
                    "annual_rent_cents",
                    "contract_rent_schedule",
                    "monthly_contract_rent_cents",
                    "monthly_rent_cents",
                    "rent_cents",
                    "rent_schedule",
                ),
            ) or _present(assumptions, ("contract_rent_cents_by_unit",))
        else:
            has_equivalent = False
        if not has_equivalent:
            corrupting.append(path)
    return sorted(set(corrupting))


def _normalize_period(value: Any, *, name: str) -> str:
    text = str(value).strip()
    if len(text) >= 7:
        text = text[:7]
    try:
        parsed = datetime.strptime(text, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM or an ISO date") from exc
    if parsed.strftime("%Y-%m") != text:
        raise ValueError(f"{name} must be YYYY-MM or an ISO date")
    return text


def _add_months(period: str, months: int) -> str:
    parsed = datetime.strptime(period, "%Y-%m")
    month_index = parsed.year * 12 + parsed.month - 1 + months
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


def _month_distance(start: str, end: str) -> int:
    first = datetime.strptime(start, "%Y-%m")
    last = datetime.strptime(end, "%Y-%m")
    return (last.year - first.year) * 12 + last.month - first.month


def _period_schedule(
    value: Any, *, amount_keys: Sequence[str], name: str
) -> dict[str, int]:
    if value is None:
        return {}
    rows: dict[str, int] = {}
    if isinstance(value, Mapping):
        for raw_period, raw_amount in value.items():
            period = _normalize_period(raw_period, name=f"{name} period")
            if isinstance(raw_amount, Mapping):
                amount = _optional_cents(raw_amount, amount_keys, non_negative=True)
                if amount is None:
                    raise ValueError(f"{name}[{period}] needs an integer-cent amount")
            else:
                amount = _cents(raw_amount, name=f"{name}[{period}]", non_negative=True)
            rows[period] = rows.get(period, 0) + amount
        return rows
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            if not isinstance(item, Mapping):
                raise ValueError(f"{name}[{index}] must be a mapping")
            raw_period = _first(item, ("period", "month", "start"))
            if raw_period is None:
                raise ValueError(f"{name}[{index}] needs period or month")
            period = _normalize_period(raw_period, name=f"{name}[{index}].period")
            amount = _optional_cents(item, amount_keys, non_negative=True)
            if amount is None:
                raise ValueError(f"{name}[{index}] needs an integer-cent amount")
            rows[period] = rows.get(period, 0) + amount
        return rows
    raise ValueError(f"{name} must be a period-to-cents mapping or a sequence")


def _books_tenancies(
    deal_id: str, db_path: str | Path | None
) -> list[dict[str, Any]]:
    books = BookStore(db_path)
    records = [
        row
        for row in books.list_tenancies(active_only=True)
        if str(row.get("deal_id")) == deal_id
    ]
    loaded: list[dict[str, Any]] = []
    for record in records:
        rent_by_period: dict[str, int] = {}
        income_by_period: dict[str, int] = {}
        for charge in books.list_charges(tenancy_id=str(record["tenancy_id"])):
            period = _normalize_period(charge["period"], name="book charge period")
            amount = _cents(
                charge["amount_cents"], name="book charge amount_cents", non_negative=True
            )
            if charge.get("kind") == "rent" and charge.get("source") == "schedule":
                rent_by_period[period] = rent_by_period.get(period, 0) + amount
            elif charge.get("kind") != "rent":
                income_by_period[period] = income_by_period.get(period, 0) + amount
        loaded.append(
            {
                **record,
                "contract_rent_schedule": rent_by_period,
                "other_income_schedule": income_by_period,
                "input_source": "cre_mcp.books scheduled charges (read-only)",
            }
        )
    return loaded


def _tenant_amount(
    tenant: Mapping[str, Any],
    assumptions: Mapping[str, Any],
    tenant_keys: Sequence[str],
    assumption_keys: Sequence[str],
    *,
    unit: str,
    name: str,
) -> int | None:
    amount = _optional_cents(tenant, tenant_keys, non_negative=True)
    if amount is not None:
        return amount
    per_unit = assumptions.get(f"{name}_by_unit")
    if isinstance(per_unit, Mapping) and unit in per_unit:
        return _cents(
            per_unit[unit], name=f"{name}_by_unit[{unit}]", non_negative=True
        )
    return _optional_cents(assumptions, assumption_keys, non_negative=True)


def _annual_to_monthly(tenant: Mapping[str, Any], keys: Sequence[str]) -> int | None:
    amount = _optional_cents(tenant, keys, non_negative=True)
    if amount is None:
        return None
    return _round_cents(Decimal(amount) / Decimal(12))


def _schedule_value(
    schedule: Mapping[str, int], period: str, *, carry_forward: bool
) -> tuple[int | None, str | None]:
    if period in schedule:
        return schedule[period], "contract schedule"
    if carry_forward:
        prior = [candidate for candidate in schedule if candidate <= period]
        if prior:
            source_period = max(prior)
            return schedule[source_period], f"CONVENTION — carry forward {source_period}"
    return None, None


def _tenant_path(
    tenant: Mapping[str, Any],
    assumptions: Mapping[str, Any],
    periods: Sequence[str],
    *,
    index: int,
) -> tuple[dict[str, Any], list[str]]:
    tenancy_id = str(
        _first(tenant, ("tenancy_id", "tenant_id", "id")) or f"tenant-{index + 1}"
    )
    tenant_name = str(
        _first(tenant, ("tenant_name", "tenant", "name")) or tenancy_id
    )
    unit = str(_first(tenant, ("unit", "suite", "unit_id")) or tenancy_id)
    gaps: list[str] = []

    rent_schedule = _period_schedule(
        tenant.get("contract_rent_schedule") or tenant.get("rent_schedule"),
        amount_keys=("rent_cents", "monthly_rent_cents", "amount_cents"),
        name=f"{tenancy_id}.contract_rent_schedule",
    )
    other_schedule = _period_schedule(
        tenant.get("other_income_schedule"),
        amount_keys=("other_income_cents", "amount_cents"),
        name=f"{tenancy_id}.other_income_schedule",
    )
    monthly_contract = _tenant_amount(
        tenant,
        assumptions,
        ("monthly_contract_rent_cents", "monthly_rent_cents", "rent_cents"),
        (),
        unit=unit,
        name="contract_rent_cents",
    )
    if monthly_contract is None:
        monthly_contract = _annual_to_monthly(
            tenant, ("annual_contract_rent_cents", "annual_rent_cents")
        )

    raw_expiration = _first(
        tenant, ("lease_expiration", "expiration", "lease_end", "rollover_date")
    )
    expiration = (
        _normalize_period(raw_expiration, name=f"{tenancy_id}.lease_expiration")
        if raw_expiration is not None
        else None
    )
    raw_downtime = _first(
        tenant, ("rollover_downtime_months", "downtime_months")
    )
    if raw_downtime is None:
        raw_downtime = _first(
            assumptions, ("rollover_downtime_months", "downtime_months")
        )
    downtime = 0 if raw_downtime is None else raw_downtime
    if isinstance(downtime, bool) or not isinstance(downtime, int) or downtime < 0:
        raise ValueError("rollover_downtime_months must be a non-negative integer")

    market_rent = _tenant_amount(
        tenant,
        assumptions,
        ("market_rent_cents_monthly", "monthly_market_rent_cents"),
        ("market_rent_cents_monthly", "monthly_market_rent_cents"),
        unit=unit,
        name="market_rent_cents",
    )
    if market_rent is None:
        market_rent = monthly_contract
    if market_rent is None and rent_schedule:
        market_rent = rent_schedule[max(rent_schedule)]

    raw_growth = _first(
        tenant, ("annual_market_rent_growth", "market_rent_growth")
    )
    if raw_growth is None:
        raw_growth = _first(
            assumptions, ("annual_market_rent_growth", "market_rent_growth")
        )
    growth = (
        Decimal(0)
        if raw_growth is None
        else _growth_rate(raw_growth, name="annual_market_rent_growth")
    )

    raw_probability = _first(tenant, ("renewal_probability", "retention_rate"))
    if raw_probability is None:
        raw_probability = _first(
            assumptions, ("renewal_probability", "retention_rate")
        )
    renewal_probability = (
        None
        if raw_probability is None
        else _rate(raw_probability, name="renewal_probability")
    )

    monthly_opex = _tenant_amount(
        tenant,
        assumptions,
        ("monthly_opex_cents", "opex_cents_monthly"),
        ("monthly_opex_cents", "opex_cents_monthly"),
        unit=unit,
        name="opex_cents",
    )
    if monthly_opex is None:
        monthly_opex = _annual_to_monthly(
            tenant, ("annual_opex_cents", "opex_cents_annual")
        )
    expense_ratio_raw = _first(tenant, ("expense_ratio", "opex_ratio"))
    if expense_ratio_raw is None:
        expense_ratio_raw = _first(assumptions, ("expense_ratio", "opex_ratio"))
    expense_ratio = (
        None
        if expense_ratio_raw is None
        else _rate(expense_ratio_raw, name="expense_ratio")
    )

    path: list[dict[str, Any]] = []
    for period in periods:
        in_rollover = expiration is not None and period > expiration
        rent_cents: int | None
        rent_basis: str
        contract_cents: int | None = None
        rollover_cents: int | None = None
        if not in_rollover:
            contract_cents, schedule_basis = _schedule_value(
                rent_schedule, period, carry_forward=True
            )
            if contract_cents is None:
                contract_cents = monthly_contract
                schedule_basis = (
                    "stated monthly contract rent"
                    if monthly_contract is not None
                    else None
                )
            rent_cents = contract_cents
            rent_basis = schedule_basis or "missing contract rent"
        else:
            assert expiration is not None
            months_after = _month_distance(expiration, period)
            annual_steps = max(0, months_after - downtime - 1) // 12
            grown_market = (
                None
                if market_rent is None
                else _round_cents(
                    Decimal(market_rent) * (Decimal(1) + growth) ** annual_steps
                )
            )
            new_lease_rent = 0 if months_after <= downtime else grown_market
            if renewal_probability is None:
                rollover_cents = new_lease_rent
                rent_cents = rollover_cents
                rent_basis = (
                    "CONVENTION — deterministic rollover to market rent after "
                    f"{downtime} downtime month(s)"
                )
            else:
                renewal_rent = monthly_contract
                if renewal_rent is None and rent_schedule:
                    renewal_rent = rent_schedule[max(rent_schedule)]
                if renewal_rent is None or new_lease_rent is None:
                    rollover_cents = None
                else:
                    rollover_cents = _round_cents(
                        renewal_probability * Decimal(renewal_rent)
                        + (Decimal(1) - renewal_probability)
                        * Decimal(new_lease_rent)
                    )
                rent_cents = rollover_cents
                rent_basis = (
                    "CONVENTION — probability-weighted renewal versus market "
                    "rollover; this is an expected-value screen, not a lease outcome"
                )

        other_income, other_basis = _schedule_value(
            other_schedule, period, carry_forward=False
        )
        if other_income is None:
            other_income = _tenant_amount(
                tenant,
                assumptions,
                ("monthly_other_income_cents", "other_income_cents_monthly"),
                ("monthly_other_income_cents", "other_income_cents_monthly"),
                unit=unit,
                name="other_income_cents",
            )
            other_basis = "stated recurring amount" if other_income is not None else None
        other_income = other_income or 0

        resolved_opex = monthly_opex
        opex_basis: str | None = "stated monthly allocation" if monthly_opex is not None else None
        if resolved_opex is None and expense_ratio is not None and rent_cents is not None:
            resolved_opex = _round_cents(
                Decimal(rent_cents + other_income) * expense_ratio
            )
            opex_basis = "CONVENTION — tenant revenue times stated expense ratio"
        noi = (
            rent_cents + other_income - resolved_opex
            if rent_cents is not None and resolved_opex is not None
            else None
        )
        path.append(
            {
                "period": period,
                "contract_rent_cents": contract_cents,
                "rollover_rent_cents": rollover_cents,
                "rent_cents": rent_cents,
                "other_income_cents": other_income,
                "opex_cents": resolved_opex,
                "noi_cents": noi,
                "rent_basis": rent_basis,
                "other_income_basis": other_basis or "none supplied; 0 cents",
                "opex_basis": opex_basis or "missing tenant-level opex allocation",
                "rollover_period": in_rollover,
            }
        )

    if not rent_schedule and monthly_contract is None:
        gaps.append(f"{tenancy_id}: contract rent is missing")
    if monthly_opex is None and expense_ratio is None:
        gaps.append(
            f"{tenancy_id}: tenant-level opex is missing; revenue is shown but NOI is null"
        )
    if expiration is None:
        gaps.append(
            f"{tenancy_id}: lease expiration is missing; no rollover month is inferred"
        )
    return (
        {
            "tenancy_id": tenancy_id,
            "tenant_name": tenant_name,
            "unit": unit,
            "lease_expiration": expiration,
            "path": path,
            "total_noi_cents": (
                sum(int(row["noi_cents"]) for row in path)
                if all(row["noi_cents"] is not None for row in path)
                else None
            ),
            "input_source": tenant.get("input_source", "structured input"),
        },
        gaps,
    )


def noi_by_tenant(
    deal_id: str | None = None,
    tenancies: Sequence[Mapping[str, Any]] | None = None,
    market_assumptions: Mapping[str, Any] | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a monthly tenant/unit NOI path with labeled rollover conventions.

    Structured tenancies take precedence.  When they are omitted, active
    tenancies and scheduled tenant charges are read from ``cre_mcp.books`` for
    ``deal_id``.  Tenant-level opex must be supplied as cents or as an explicit
    expense-ratio convention; missing opex leaves NOI null rather than implying
    zero expense.
    """

    assumptions = dict(market_assumptions or {})
    raw_start = _first(assumptions, ("start_period", "as_of"))
    start = (
        date.today().strftime("%Y-%m")
        if raw_start is None
        else _normalize_period(raw_start, name="start_period")
    )
    raw_months = _first(assumptions, ("months", "horizon_months"))
    months = 12 if raw_months is None else raw_months
    if isinstance(months, bool) or not isinstance(months, int) or months <= 0:
        raise ValueError("months must be a positive integer")
    periods = [_add_months(start, offset) for offset in range(months)]

    if tenancies is None:
        normalized_deal = "" if deal_id is None else str(deal_id).strip()
        if not normalized_deal:
            raise ValueError("deal_id is required when tenancies are omitted")
        supplied = _books_tenancies(normalized_deal, db_path)
        source = "cre_mcp.books (read-only)"
    else:
        if isinstance(tenancies, (str, bytes)):
            raise ValueError("tenancies must be a sequence of mappings")
        supplied = []
        for index, tenancy in enumerate(tenancies):
            if not isinstance(tenancy, Mapping):
                raise ValueError(f"tenancies[{index}] must be a mapping")
            supplied.append(dict(tenancy))
        source = "structured input"

    input_issues = _noi_input_unrecognized(supplied, assumptions)
    if _noi_corrupting_revenue_names(input_issues, supplied, assumptions):
        return _noi_unrecognized_revenue_result(
            input_issues, deal_id=deal_id, source=source
        )
    unrecognized_inputs = _unrecognized_names(input_issues)

    rows: list[dict[str, Any]] = []
    honest_gaps: list[str] = []
    for index, tenant in enumerate(supplied):
        row, gaps = _tenant_path(tenant, assumptions, periods, index=index)
        rows.append(row)
        honest_gaps.extend(gaps)
    if not rows:
        honest_gaps.append(
            "No tenancies were available; zero revenue or NOI is not inferred from an empty set."
        )

    portfolio_path: list[dict[str, Any]] = []
    for period_index, period in enumerate(periods):
        month_rows = [tenant["path"][period_index] for tenant in rows]
        portfolio_path.append(
            {
                "period": period,
                "rent_cents": sum(
                    int(row["rent_cents"] or 0) for row in month_rows
                ),
                "other_income_cents": sum(
                    int(row["other_income_cents"]) for row in month_rows
                ),
                "opex_cents": (
                    sum(int(row["opex_cents"]) for row in month_rows)
                    if month_rows
                    and all(row["opex_cents"] is not None for row in month_rows)
                    else None
                ),
                "noi_cents": (
                    sum(int(row["noi_cents"]) for row in month_rows)
                    if month_rows
                    and all(row["noi_cents"] is not None for row in month_rows)
                    else None
                ),
                "complete_tenant_count": sum(
                    row["noi_cents"] is not None for row in month_rows
                ),
                "tenant_count": len(month_rows),
            }
        )

    return {
        "deal_id": deal_id,
        "source": source,
        "unrecognized_inputs": unrecognized_inputs,
        "accepted_input_keys": {
            "tenancy": sorted(_TENANCY_INPUT_KEYS),
            "market_assumptions": sorted(_MARKET_ASSUMPTION_KEYS),
        },
        "from_period": periods[0],
        "to_period": periods[-1],
        "per_tenant": rows,
        "tenants": rows,
        "portfolio_path": portfolio_path,
        "assumptions": {
            "supplied": assumptions,
            "rate_normalization": (
                "Values from 0 through 1 are decimals; values over 1 through 100 "
                "are interpreted as percentages."
            ),
            "rollover_conventions": [
                "Contract schedule cents govern through the stated expiration month.",
                "Without a renewal probability, rollover is deterministically set to "
                "market rent after the supplied downtime; this is a convention.",
                "With a renewal probability, rent is a probability-weighted expected "
                "value, not a predicted tenant decision.",
                "Missing expiration never triggers an inferred rollover.",
                "Annual market-rent growth steps once per 12 full post-downtime months.",
            ],
        },
        "formula": (
            "tenant NOI cents = contract-or-labeled-rollover rent cents + other "
            "income cents - allocated opex cents"
        ),
        "honest_gaps": honest_gaps,
    }


def _operating_inputs(values: Mapping[str, Any]) -> dict[str, Any] | None:
    potential = _optional_cents(values, _POTENTIAL_RENT_KEYS, non_negative=True)
    raw_occupancy = _first(values, _RATE_KEYS)
    opex = _optional_cents(values, _OPEX_KEYS, non_negative=True)
    if potential is None or raw_occupancy is None or opex is None:
        return None
    occupancy = _rate(raw_occupancy, name="occupancy")
    other_income = _optional_cents(values, _OTHER_INCOME_KEYS) or 0
    timing = _optional_cents(values, _TIMING_KEYS) or 0
    stated_noi = _optional_cents(values, _NOI_KEYS)
    effective_rent = _round_cents(Decimal(potential) * occupancy)
    calculated_noi = effective_rent + other_income + timing - opex
    return {
        "potential_rent_cents": potential,
        "occupancy": occupancy,
        "effective_rent_cents": effective_rent,
        "other_income_cents": other_income,
        "timing_cents": timing,
        "opex_cents": opex,
        "calculated_noi_cents": calculated_noi,
        "noi_cents": stated_noi if stated_noi is not None else calculated_noi,
        "stated_noi_cents": stated_noi,
    }


def _line_driver(name: str) -> str:
    normalized = name.casefold()
    if any(word in normalized for word in ("occup", "vacan", "bad_debt")):
        return "occupancy"
    if any(
        word in normalized
        for word in (
            "opex",
            "expense",
            "cost",
            "repair",
            "utility",
            "utilities",
            "tax",
            "insurance",
        )
    ):
        return "opex"
    if any(
        word in normalized
        for word in ("timing", "free_rent", "concession", "accrual", "one_time")
    ):
        return "timing"
    return "rate"


def _line_sign(name: str, item: Mapping[str, Any] | None = None) -> int:
    if item is not None and "noi_sign" in item:
        raw = item["noi_sign"]
        if raw not in (-1, 1):
            raise ValueError(f"{name}.noi_sign must be -1 or 1")
        return int(raw)
    return -1 if _line_driver(name) == "opex" else 1


def _line_items(values: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_lines = values.get("lines")
    result: dict[str, dict[str, Any]] = {}
    if isinstance(raw_lines, Mapping):
        for raw_name, raw_value in raw_lines.items():
            name = str(raw_name)
            if isinstance(raw_value, Mapping):
                amount = _optional_cents(
                    raw_value,
                    ("amount_cents", "value_cents", "budget_cents", "actual_cents"),
                )
                if amount is None:
                    raise ValueError(f"lines[{name}] needs an integer-cent amount")
                driver = str(raw_value.get("driver") or _line_driver(name)).casefold()
                sign = _line_sign(name, raw_value)
            else:
                amount = _cents(raw_value, name=f"lines[{name}]")
                driver = _line_driver(name)
                sign = _line_sign(name)
            result[name] = {"amount_cents": amount, "driver": driver, "sign": sign}
        return result
    if isinstance(raw_lines, Sequence) and not isinstance(raw_lines, (str, bytes)):
        for index, item in enumerate(raw_lines):
            if not isinstance(item, Mapping):
                raise ValueError(f"lines[{index}] must be a mapping")
            raw_name = _first(item, ("line", "name", "item", "category"))
            if raw_name is None:
                raise ValueError(f"lines[{index}] needs line or name")
            name = str(raw_name)
            amount = _optional_cents(
                item,
                ("amount_cents", "value_cents", "budget_cents", "actual_cents"),
            )
            if amount is None:
                raise ValueError(f"lines[{index}] needs an integer-cent amount")
            result[name] = {
                "amount_cents": amount,
                "driver": str(item.get("driver") or _line_driver(name)).casefold(),
                "sign": _line_sign(name, item),
            }
        return result

    def collect(prefix: str, nested: Mapping[str, Any]) -> None:
        for key, value in nested.items():
            if key in _NOI_KEYS or key in _RATE_KEYS or key in _POTENTIAL_RENT_KEYS:
                continue
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, Mapping):
                collect(name, value)
            elif str(key).endswith("_cents") and value is not None:
                result[name] = {
                    "amount_cents": _cents(value, name=name),
                    "driver": _line_driver(name),
                    "sign": _line_sign(name),
                }

    collect("", values)
    return result


def _book_actual_lines(
    deal_id: str, period: str | None, db_path: str | Path | None
) -> tuple[dict[str, Any], list[str]]:
    books = BookStore(db_path)
    tenancies = {
        str(row["tenancy_id"])
        for row in books.list_tenancies()
        if str(row.get("deal_id")) == deal_id
    }
    charges = [
        row
        for row in books.list_charges(period=period)
        if str(row.get("tenancy_id")) in tenancies
    ]
    by_kind: dict[str, int] = {}
    for charge in charges:
        kind = str(charge.get("kind") or "other")
        by_kind[kind] = by_kind.get(kind, 0) + _cents(
            charge["amount_cents"], name="book charge amount_cents", non_negative=True
        )
    lines = [
        {
            "line": f"billed_{kind}",
            "amount_cents": amount,
            "driver": "rate",
            "noi_sign": 1,
        }
        for kind, amount in sorted(by_kind.items())
    ]
    return (
        {"lines": lines, "period": period, "books_basis": "billed tenant charges"},
        [
            "cre_mcp.books contains tenant billings and receipts, not operating "
            "expenses; books-only data cannot establish actual NOI."
        ],
    )


def _not_computable_variance(
    budget: Mapping[str, Any],
    actual_book_lines: Mapping[str, Any],
    gaps: list[str],
    unrecognized_inputs: Sequence[str],
) -> dict[str, Any]:
    return {
        "budget_noi_cents": _optional_cents(budget, _NOI_KEYS),
        "actual_noi_cents": None,
        "total_delta_cents": None,
        "drivers": None,
        "attribution": None,
        "lines": [],
        "decomposition_check": {
            "sum_driver_cents": None,
            "total_delta_cents": None,
            "difference_cents": None,
            "exact": False,
        },
        "book_actuals_observed": dict(actual_book_lines),
        "formula": (
            "NOI variance requires actual income minus actual operating expenses; "
            "missing actual opex is never assumed to be zero."
        ),
        "not_computable": gaps,
        "honest_gaps": gaps,
        "unrecognized_inputs": list(unrecognized_inputs),
    }


def variance_explain(
    budget: Mapping[str, Any],
    actuals: Mapping[str, Any] | None = None,
    *,
    deal_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Explain actual-minus-budget NOI using penny-exact arithmetic.

    The preferred shape supplies potential rent cents, occupancy, other income
    cents, timing cents, and opex cents for both budget and actual.  It uses a
    two-step occupancy/rate bridge.  Arbitrary ``lines`` shapes are also
    supported; each line may declare ``driver`` and ``noi_sign``.
    """

    if not isinstance(budget, Mapping):
        raise ValueError("budget must be a mapping")
    book_actuals_shape = actuals is None
    if actuals is None:
        normalized_deal = str(deal_id or budget.get("deal_id") or "").strip()
        if not normalized_deal:
            raise ValueError("deal_id is required when actuals are omitted")
        raw_period = budget.get("actual_period") or budget.get("period")
        period = (
            None
            if raw_period is None
            else _normalize_period(raw_period, name="actual_period")
        )
        book_actuals, book_gaps = _book_actual_lines(normalized_deal, period, db_path)
        budget_preview = _operating_inputs(budget)
        preview_issues = _variance_unrecognized(
            budget,
            source="budget",
            operating_shape=budget_preview is not None,
            book_actuals_shape=True,
        )
        if _unrecognized_revenue_names(preview_issues):
            return _unrecognized_revenue_result(
                preview_issues, context="NOI variance"
            )
        actual_opex = budget.get("actual_opex_cents")
        if actual_opex is None:
            return _not_computable_variance(
                budget,
                book_actuals,
                book_gaps,
                _unrecognized_names(preview_issues),
            )
        actual_opex_cents = _cents(
            actual_opex, name="actual_opex_cents", non_negative=True
        )
        book_lines = list(book_actuals["lines"])
        book_lines.append(
            {
                "line": "actual_opex",
                "amount_cents": actual_opex_cents,
                "driver": "opex",
                "noi_sign": -1,
            }
        )
        actuals = {"lines": book_lines}
    elif not isinstance(actuals, Mapping):
        raise ValueError("actuals must be a mapping or null")

    budget_operating = _operating_inputs(budget)
    actual_operating = _operating_inputs(actuals)
    operating_shape = budget_operating is not None and actual_operating is not None
    input_issues = _variance_unrecognized(
        budget,
        source="budget",
        operating_shape=operating_shape,
        book_actuals_shape=book_actuals_shape,
    )
    input_issues.extend(
        _variance_unrecognized(
            actuals, source="actuals", operating_shape=operating_shape
        )
    )
    if _unrecognized_revenue_names(input_issues):
        return _unrecognized_revenue_result(input_issues, context="NOI variance")
    unrecognized_inputs = _unrecognized_names(input_issues)
    if budget_operating is not None and actual_operating is not None:
        intermediate_rent = _round_cents(
            Decimal(budget_operating["potential_rent_cents"])
            * actual_operating["occupancy"]
        )
        occupancy_delta = intermediate_rent - budget_operating["effective_rent_cents"]
        rate_delta = (
            actual_operating["effective_rent_cents"]
            - intermediate_rent
            + actual_operating["other_income_cents"]
            - budget_operating["other_income_cents"]
        )
        opex_delta = (
            budget_operating["opex_cents"] - actual_operating["opex_cents"]
        )
        raw_timing_delta = (
            actual_operating["timing_cents"] - budget_operating["timing_cents"]
        )
        budget_noi = int(budget_operating["noi_cents"])
        actual_noi = int(actual_operating["noi_cents"])
        total_delta = actual_noi - budget_noi
        pre_residual = occupancy_delta + rate_delta + opex_delta + raw_timing_delta
        reporting_residual = total_delta - pre_residual
        timing_delta = raw_timing_delta + reporting_residual
        drivers = {
            "occupancy_cents": occupancy_delta,
            "rate_cents": rate_delta,
            "opex_cents": opex_delta,
            "timing_cents": timing_delta,
        }
        lines = [
            {
                "line": "occupancy",
                "driver": "occupancy",
                "noi_delta_cents": occupancy_delta,
                "formula": (
                    "round(budget potential rent * actual occupancy) - "
                    "round(budget potential rent * budget occupancy)"
                ),
                "numbers": {
                    "budget_potential_rent_cents": budget_operating[
                        "potential_rent_cents"
                    ],
                    "budget_occupancy": str(budget_operating["occupancy"]),
                    "actual_occupancy": str(actual_operating["occupancy"]),
                    "intermediate_rent_cents": intermediate_rent,
                },
            },
            {
                "line": "rate_and_other_income",
                "driver": "rate",
                "noi_delta_cents": rate_delta,
                "formula": (
                    "actual effective rent - intermediate rent + actual other "
                    "income - budget other income"
                ),
                "numbers": {
                    "actual_effective_rent_cents": actual_operating[
                        "effective_rent_cents"
                    ],
                    "intermediate_rent_cents": intermediate_rent,
                    "budget_other_income_cents": budget_operating[
                        "other_income_cents"
                    ],
                    "actual_other_income_cents": actual_operating[
                        "other_income_cents"
                    ],
                },
            },
            {
                "line": "opex",
                "driver": "opex",
                "noi_delta_cents": opex_delta,
                "formula": "budget opex - actual opex",
                "numbers": {
                    "budget_opex_cents": budget_operating["opex_cents"],
                    "actual_opex_cents": actual_operating["opex_cents"],
                },
            },
            {
                "line": "timing_and_reconciliation",
                "driver": "timing",
                "noi_delta_cents": timing_delta,
                "formula": (
                    "actual timing - budget timing + stated-NOI reporting residual"
                ),
                "numbers": {
                    "raw_timing_delta_cents": raw_timing_delta,
                    "reporting_residual_cents": reporting_residual,
                },
            },
        ]
        sum_drivers = sum(drivers.values())
        return {
            "budget_noi_cents": budget_noi,
            "actual_noi_cents": actual_noi,
            "total_delta_cents": total_delta,
            "drivers": drivers,
            "attribution": drivers,
            "lines": lines,
            "decomposition_check": {
                "sum_driver_cents": sum_drivers,
                "total_delta_cents": total_delta,
                "difference_cents": total_delta - sum_drivers,
                "exact": sum_drivers == total_delta,
            },
            "formula": (
                "actual NOI - budget NOI = occupancy + rate/other-income + "
                "opex + timing; expense increases reduce NOI"
            ),
            "conventions": [
                "Occupancy is bridged first at budget potential rent; rate is bridged second.",
                "Other-income variance is grouped with the rate/income driver.",
                "Any difference between stated NOI and component NOI is shown inside "
                "timing as a reporting residual so the bridge remains penny-exact.",
            ],
            "honest_gaps": [],
            "unrecognized_inputs": unrecognized_inputs,
        }

    budget_lines = _line_items(budget)
    actual_lines = _line_items(actuals)
    if not budget_lines and not actual_lines:
        raise ValueError(
            "budget and actuals need complete operating inputs or integer-cent lines"
        )
    lines: list[dict[str, Any]] = []
    drivers = {
        "occupancy_cents": 0,
        "rate_cents": 0,
        "opex_cents": 0,
        "timing_cents": 0,
    }
    for name in sorted(set(budget_lines) | set(actual_lines)):
        budget_line = budget_lines.get(name)
        actual_line = actual_lines.get(name)
        metadata = actual_line or budget_line
        assert metadata is not None
        driver = str(metadata["driver"]).casefold()
        if driver not in {"occupancy", "rate", "opex", "timing"}:
            raise ValueError(f"line {name!r} driver must be occupancy, rate, opex, or timing")
        sign = int(metadata["sign"])
        budget_amount = int(budget_line["amount_cents"]) if budget_line else 0
        actual_amount = int(actual_line["amount_cents"]) if actual_line else 0
        noi_delta = sign * (actual_amount - budget_amount)
        drivers[f"{driver}_cents"] += noi_delta
        lines.append(
            {
                "line": name,
                "driver": driver,
                "budget_cents": budget_amount,
                "actual_cents": actual_amount,
                "noi_sign": sign,
                "noi_delta_cents": noi_delta,
                "formula": "noi_sign * (actual cents - budget cents)",
            }
        )

    computed_budget_noi = sum(
        int(item["sign"]) * int(item["amount_cents"])
        for item in budget_lines.values()
    )
    computed_actual_noi = sum(
        int(item["sign"]) * int(item["amount_cents"])
        for item in actual_lines.values()
    )
    budget_noi = _optional_cents(budget, _NOI_KEYS)
    actual_noi = _optional_cents(actuals, _NOI_KEYS)
    budget_noi = computed_budget_noi if budget_noi is None else budget_noi
    actual_noi = computed_actual_noi if actual_noi is None else actual_noi
    total_delta = actual_noi - budget_noi
    pre_residual = sum(drivers.values())
    reporting_residual = total_delta - pre_residual
    if reporting_residual:
        drivers["timing_cents"] += reporting_residual
        lines.append(
            {
                "line": "stated_noi_reconciliation",
                "driver": "timing",
                "budget_cents": computed_budget_noi,
                "actual_cents": computed_actual_noi,
                "noi_sign": 1,
                "noi_delta_cents": reporting_residual,
                "formula": "stated NOI delta - sum of supplied line deltas",
            }
        )
    sum_drivers = sum(drivers.values())
    return {
        "budget_noi_cents": budget_noi,
        "actual_noi_cents": actual_noi,
        "total_delta_cents": total_delta,
        "drivers": drivers,
        "attribution": drivers,
        "lines": lines,
        "decomposition_check": {
            "sum_driver_cents": sum_drivers,
            "total_delta_cents": total_delta,
            "difference_cents": total_delta - sum_drivers,
            "exact": sum_drivers == total_delta,
        },
        "formula": (
            "each line NOI delta = sign * (actual cents - budget cents); "
            "total = occupancy + rate + opex + timing"
        ),
        "conventions": [
            "Expense-like line names default to NOI sign -1; other lines default to +1.",
            "A line may override classification with driver and sign with noi_sign.",
            "Missing counterpart lines are arithmetic zeros and remain visible in output.",
        ],
        "honest_gaps": [],
        "unrecognized_inputs": unrecognized_inputs,
    }


__all__ = ["noi_by_tenant", "variance_explain"]
