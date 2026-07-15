"""Transparent, penny-rounded pricing frames for control purchase options."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite
from typing import Any


_CENT = Decimal("1")


def _mapping(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _integer(name: str, value: Any, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _first_value(source: Mapping[str, Any], keys: Sequence[str]) -> tuple[Any, str | None]:
    for key in keys:
        if source.get(key) is not None:
            return source[key], key
    return None, None


def _optional_nonnegative_cents(
    source: Mapping[str, Any], keys: Sequence[str]
) -> tuple[int | None, str | None]:
    value, key = _first_value(source, keys)
    if key is None:
        return None, None
    return _integer(key, value, minimum=0), key


def _date(name: str, value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _range_values(raw: Any, name: str) -> tuple[int, int]:
    if isinstance(raw, Mapping):
        low = next(
            (
                raw.get(key)
                for key in ("low_cents", "low", "min_cents", "min")
                if raw.get(key) is not None
            ),
            None,
        )
        high = next(
            (
                raw.get(key)
                for key in ("high_cents", "high", "max_cents", "max")
                if raw.get(key) is not None
            ),
            None,
        )
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) == 2:
        low, high = raw
    else:
        raise ValueError(f"{name} must be a two-item sequence or low/high mapping")
    low_cents = _integer(f"{name}.low", low, minimum=0)
    high_cents = _integer(f"{name}.high", high, minimum=0)
    if low_cents > high_cents:
        raise ValueError(f"{name}.low cannot exceed high")
    return low_cents, high_cents


def _market_value_range(market: Mapping[str, Any]) -> tuple[int, int, str]:
    raw, key = _first_value(
        market, ("value_range_now_cents", "value_range_now", "value_range")
    )
    if key is not None:
        low, high = _range_values(raw, f"market.{key}")
        return low, high, key
    low, low_key = _first_value(market, ("value_low_cents", "low_value_cents"))
    high, high_key = _first_value(market, ("value_high_cents", "high_value_cents"))
    if low_key is None or high_key is None:
        raise ValueError(
            "market.value_range_now_cents or market.value_range_now is required"
        )
    low_cents = _integer(f"market.{low_key}", low, minimum=0)
    high_cents = _integer(f"market.{high_key}", high, minimum=0)
    if low_cents > high_cents:
        raise ValueError(f"market.{low_key} cannot exceed {high_key}")
    return low_cents, high_cents, f"{low_key}/{high_key}"


def _decimal_rate(name: str, value: Any, *, percentage: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise ValueError(f"{name} must be a finite numeric growth rate")
    if isinstance(value, float) and not isfinite(value):
        raise ValueError(f"{name} must be a finite numeric growth rate")
    try:
        rendered = str(value).strip()
        if not rendered:
            raise InvalidOperation
        rate = Decimal(rendered)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite numeric growth rate") from exc
    if not rate.is_finite():
        raise ValueError(f"{name} must be a finite numeric growth rate")
    if percentage:
        rate /= Decimal(100)
    if rate <= Decimal("-1"):
        raise ValueError(f"{name} must be greater than -1")
    return rate


def _rate_from_mapping(raw: Mapping[str, Any], name: str) -> Decimal:
    for key in ("annual_growth_rate", "growth_rate", "rate"):
        if raw.get(key) is not None:
            return _decimal_rate(f"{name}.{key}", raw[key])
    for key in ("annual_growth_pct", "growth_pct", "pct"):
        if raw.get(key) is not None:
            return _decimal_rate(f"{name}.{key}", raw[key], percentage=True)
    raise ValueError(f"{name} must include an annual growth rate")


def _growth_scenarios(market: Mapping[str, Any]) -> list[tuple[str, Decimal]]:
    raw = market.get("growth_scenarios")
    if raw is None:
        return [("flat", Decimal(0))]
    parsed: list[tuple[str, Decimal]] = []
    if isinstance(raw, Mapping):
        if any(
            raw.get(key) is not None
            for key in (
                "annual_growth_rate",
                "growth_rate",
                "rate",
                "annual_growth_pct",
                "growth_pct",
                "pct",
            )
        ):
            label = str(raw.get("name", "scenario")).strip()
            if not label:
                raise ValueError("market.growth_scenarios.name must not be empty")
            parsed.append((label, _rate_from_mapping(raw, "market.growth_scenarios")))
        else:
            for label_raw, value in raw.items():
                label = str(label_raw).strip()
                if not label:
                    raise ValueError("growth scenario names must not be empty")
                if isinstance(value, Mapping):
                    rate = _rate_from_mapping(value, f"market.growth_scenarios.{label}")
                else:
                    rate = _decimal_rate(f"market.growth_scenarios.{label}", value)
                parsed.append((label, rate))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for index, value in enumerate(raw):
            if isinstance(value, Mapping):
                label = str(value.get("name", value.get("scenario", f"scenario_{index + 1}"))).strip()
                if not label:
                    raise ValueError(f"market.growth_scenarios[{index}].name must not be empty")
                rate = _rate_from_mapping(value, f"market.growth_scenarios[{index}]")
            else:
                label = f"scenario_{index + 1}"
                rate = _decimal_rate(f"market.growth_scenarios[{index}]", value)
            parsed.append((label, rate))
    else:
        raise TypeError("market.growth_scenarios must be a mapping, list, or null")
    if not parsed:
        raise ValueError("market.growth_scenarios cannot be empty")
    labels = [label for label, _ in parsed]
    if len(labels) != len(set(labels)):
        raise ValueError("growth scenario names must be unique")
    return parsed


def _years_between(as_of: date, exercise_date: date) -> Decimal:
    days = max((exercise_date - as_of).days, 0)
    return Decimal(days) / Decimal(365)


def _project_cents(value_cents: int, rate: Decimal, years: Decimal) -> int:
    factor = (Decimal(1) + rate) ** years
    return int((Decimal(value_cents) * factor).quantize(_CENT, rounding=ROUND_HALF_UP))


def _window_value(
    *,
    label: str,
    exercise_date: date,
    as_of: date,
    low_now: int,
    high_now: int,
    strike: int,
    growth_rate: Decimal,
) -> dict[str, Any]:
    years = _years_between(as_of, exercise_date)
    low_value = _project_cents(low_now, growth_rate, years)
    high_value = _project_cents(high_now, growth_rate, years)
    intrinsic_low = max(low_value - strike, 0)
    intrinsic_high = max(high_value - strike, 0)
    return {
        "window": label,
        "date": exercise_date.isoformat(),
        "years_from_as_of_decimal": format(years, "f"),
        "projected_market_value_range_cents": {
            "low": low_value,
            "high": high_value,
        },
        "strike_cents": strike,
        "intrinsic_value_range_cents": {
            "low": intrinsic_low,
            "high": intrinsic_high,
        },
        "intrinsic_value_low_cents": intrinsic_low,
        "intrinsic_value_high_cents": intrinsic_high,
    }


def _normalize_extension_terms(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    values = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else [raw]
    normalized: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if isinstance(value, bool):
            raise ValueError(f"option.extension_terms[{index}] has an invalid boolean value")
        if isinstance(value, int):
            if value <= 0:
                raise ValueError(f"option.extension_terms[{index}] months must be positive")
            normalized.append({"months": value})
        elif isinstance(value, str):
            if not value.strip():
                raise ValueError(f"option.extension_terms[{index}] must not be empty")
            normalized.append({"description": value.strip()})
        elif isinstance(value, Mapping):
            item = dict(value)
            if not item:
                raise ValueError(f"option.extension_terms[{index}] cannot be empty")
            normalized.append(item)
        else:
            raise TypeError(
                f"option.extension_terms[{index}] must be months, text, or a mapping"
            )
    return normalized


def _position_exposure(position: Mapping[str, Any]) -> dict[str, Any]:
    owed, _ = _optional_nonnegative_cents(
        position,
        ("master_rent_owed_cents", "master_rent_cents", "monthly_master_rent_cents"),
    )
    received, _ = _optional_nonnegative_cents(
        position, ("sublease_received_cents", "monthly_sublease_received_cents")
    )
    expense, _ = _optional_nonnegative_cents(
        position,
        ("expense_cents", "monthly_expense_cents", "monthly_operating_expense_cents"),
    )
    full_obligation = owed + (expense or 0) if owed is not None else None
    negative_carry = (
        max(full_obligation - received, 0)
        if full_obligation is not None and received is not None
        else None
    )
    return {
        "master_rent_owed_cents": owed,
        "monthly_master_rent_owed_cents": owed,
        "expense_cents": expense,
        "monthly_expense_cents": expense,
        "full_monthly_cash_obligation_cents": full_obligation,
        "monthly_sublease_rent_received_cents": received,
        "monthly_negative_carry_cents": negative_carry,
        "warning": (
            "Option value does not fund master-rent shortfalls. Master rent remains owed "
            "when sublease cash is not received."
        ),
    }


def _annual_net_spread(position: Mapping[str, Any]) -> tuple[int | None, str]:
    explicit, key = _first_value(
        position, ("net_annual_spread_cents", "annual_net_spread_cents")
    )
    if key is not None:
        return _integer(f"position_economics.{key}", explicit), "caller-supplied annual net spread"
    owed, _ = _optional_nonnegative_cents(
        position,
        ("master_rent_owed_cents", "master_rent_cents", "monthly_master_rent_cents"),
    )
    received, _ = _optional_nonnegative_cents(
        position, ("sublease_received_cents", "monthly_sublease_received_cents")
    )
    expense, expense_key = _optional_nonnegative_cents(
        position,
        ("expense_cents", "monthly_operating_expense_cents", "monthly_expense_cents"),
    )
    if owed is None or received is None:
        return None, "not calculated; monthly owed and received inputs are incomplete"
    return (
        (received - owed - (expense or 0)) * 12,
        "12 × (monthly sublease cash received − master rent owed − monthly operating expense)"
        + ("" if expense_key is not None else "; expense assumed zero"),
    )


def _remaining_term(position: Mapping[str, Any]) -> tuple[int | None, str]:
    if position.get("remaining_term_months") is not None:
        return (
            _integer(
                "position_economics.remaining_term_months",
                position["remaining_term_months"],
                minimum=0,
            ),
            "caller-supplied remaining_term_months",
        )
    if position.get("term_months") is not None:
        return (
            _integer(
                "position_economics.term_months",
                position["term_months"],
                minimum=0,
            ),
            "original term_months fallback; elapsed term was not derived",
        )
    return None, "remaining term unavailable"


def price_control_option(
    option: Mapping[str, Any],
    market: Mapping[str, Any],
    position_economics: Mapping[str, Any],
) -> dict[str, Any]:
    """Price current and exercise-window intrinsic value without inventing a premium.

    ``strike`` is supported as an integer-cent alias for ``strike_cents``.  Market
    ranges supplied under ``value_range_now`` are likewise interpreted as cents;
    callers should prefer the explicitly named ``*_cents`` fields.
    """

    option = _mapping("option", option)
    market = _mapping("market", market)
    position = _mapping("position_economics", position_economics)

    strike_raw, strike_key = _first_value(option, ("strike_cents", "strike"))
    if strike_key is None:
        raise ValueError("option.strike_cents or option.strike is required")
    strike = _integer(f"option.{strike_key}", strike_raw, minimum=0)
    low_now, high_now, market_range_key = _market_value_range(market)

    from_raw, _ = _first_value(option, ("exercisable_from",))
    until_raw, _ = _first_value(option, ("exercisable_until",))
    if from_raw is None or until_raw is None:
        raise ValueError("option.exercisable_from and exercisable_until are required")
    exercisable_from = _date("option.exercisable_from", from_raw)
    exercisable_until = _date("option.exercisable_until", until_raw)
    if exercisable_from > exercisable_until:
        raise ValueError("option.exercisable_from cannot be after exercisable_until")
    as_of_raw = market.get("as_of", position.get("as_of"))
    as_of = date.today() if as_of_raw is None else _date("market.as_of", as_of_raw)
    extensions = _normalize_extension_terms(option.get("extension_terms"))

    intrinsic_low_now = max(low_now - strike, 0)
    intrinsic_high_now = max(high_now - strike, 0)
    growth_scenarios = _growth_scenarios(market)
    scenario_values: list[dict[str, Any]] = []
    for name, rate in growth_scenarios:
        at_from = _window_value(
            label="exercisable_from",
            exercise_date=exercisable_from,
            as_of=as_of,
            low_now=low_now,
            high_now=high_now,
            strike=strike,
            growth_rate=rate,
        )
        at_until = _window_value(
            label="exercisable_until",
            exercise_date=exercisable_until,
            as_of=as_of,
            low_now=low_now,
            high_now=high_now,
            strike=strike,
            growth_rate=rate,
        )
        scenario_values.append(
            {
                "scenario": name,
                "annual_growth_rate": float(rate),
                "annual_growth_rate_decimal": format(rate, "f"),
                "at_exercisable_from": at_from,
                "at_exercisable_until": at_until,
                "exercise_windows": [at_from, at_until],
            }
        )

    annual_spread, spread_convention = _annual_net_spread(position)
    remaining_months, remaining_term_basis = _remaining_term(position)
    exposure = _position_exposure(position)
    expired = as_of > exercisable_until
    not_yet_exercisable = as_of < exercisable_from
    if expired:
        currently_exercisable_value: dict[str, int] | None = {"low": 0, "high": 0}
        exercise_availability = (
            "expired_under_stated_unextended_window; exercisable value set to zero "
            "pending counsel review of extensions, waiver, and enforceability"
        )
    elif not_yet_exercisable:
        currently_exercisable_value = None
        exercise_availability = "not_yet_exercisable; no time value is priced"
    else:
        currently_exercisable_value = {
            "low": intrinsic_low_now,
            "high": intrinsic_high_now,
        }
        exercise_availability = "within_stated_exercise_window"

    decision_framing = {
        "hold": {
            "frame": (
                "Retain contractual control and operating spread while preserving the "
                "exercise decision, subject to ongoing negative carry and expiry."
            ),
            "modeled_annual_net_spread_cents": annual_spread,
            "spread_convention": spread_convention,
        },
        "exercise": {
            "frame": (
                "Compare window-specific intrinsic range with acquisition capital, debt, "
                "closing costs, condition, and post-close operating value."
            ),
            "hypothetical_current_intrinsic_value_range_cents": {
                "low": intrinsic_low_now,
                "high": intrinsic_high_now,
            },
            "currently_exercisable_option_value_range_cents": currently_exercisable_value,
            "exercise_availability": exercise_availability,
            "warning": (
                "Positive hypothetical intrinsic value alone does not establish a live, "
                "financeable, or prudent right to exercise."
            ),
        },
        "sell": {
            "frame": (
                "A sale may monetize documented spread and optionality only if the option, "
                "master lease, and related rights can be transferred with required consents."
            ),
            "warning": (
                "No assignability, consent, buyer demand, execution cost, or sale price is "
                "assumed; run the obligations consent screen and obtain counsel review."
            ),
        },
        "drivers": [
            {
                "driver": "market_value_vs_strike",
                "value": {
                    "market_value_range_now_cents": {"low": low_now, "high": high_now},
                    "strike_cents": strike,
                },
            },
            {"driver": "growth_scenarios", "value": [row[0] for row in growth_scenarios]},
            {"driver": "annual_net_operating_spread_cents", "value": annual_spread},
            {"driver": "remaining_control_term_months", "value": remaining_months},
            {"driver": "remaining_control_term_basis", "value": remaining_term_basis},
            {"driver": "extension_terms", "value": extensions},
            {"driver": "financing_closing_and_condition_costs", "value": "not supplied or deducted"},
        ],
    }

    return {
        "rent_owed_vs_received_exposure": exposure,
        "intrinsic_value_range_now_cents": {
            "low": intrinsic_low_now,
            "high": intrinsic_high_now,
        },
        "intrinsic_value_now_status": (
            "hypothetical market-minus-strike math; the stated option window is expired"
            if expired
            else "market-minus-strike intrinsic math; excludes time value and execution costs"
        ),
        "currently_exercisable_option_value_range_cents": currently_exercisable_value,
        "exercise_availability": exercise_availability,
        "intrinsic_value_low_now_cents": intrinsic_low_now,
        "intrinsic_value_high_now_cents": intrinsic_high_now,
        "strike_cents": strike,
        "market_value_range_now_cents": {"low": low_now, "high": high_now},
        "exercise_window": {
            "exercisable_from": exercisable_from.isoformat(),
            "exercisable_until": exercisable_until.isoformat(),
            "as_of": as_of.isoformat(),
            "expired_as_of": expired,
            "not_yet_exercisable_as_of": not_yet_exercisable,
        },
        "extension_terms": extensions,
        "scenario_values": scenario_values,
        "decision_framing": decision_framing,
        "assumptions": {
            "strike_units": "integer cents; strike alias is also interpreted as cents",
            "market_value_units": "integer cents",
            "market_value_source_field": market_range_key,
            "strike_is_fixed": True,
            "growth_method": (
                "Caller-supplied annual compound growth from as_of to each window; "
                "365-day year; cents rounded half up."
            ),
            "transaction_costs_deducted": False,
            "taxes_deducted": False,
            "financing_deducted": False,
            "extension_value_modeled": False,
            "remaining_term_basis": remaining_term_basis,
        },
        "control_premium_note": (
            "A control premium may reflect timing discretion, extension rights, operating "
            "control, transferability, and scarcity, but it is not independently priced here. "
            "Do not add an unsupported premium to intrinsic value."
        ),
        "counsel_flag": True,
        "counsel_note": (
            "Counsel must confirm option validity, exercise mechanics, deadlines, extensions, "
            "recording, transfer restrictions, consents, and conflicts with the master lease."
        ),
        "posture": (
            "Scenario ranges, not an appraisal, fairness opinion, legal conclusion, or "
            "recommendation to hold, exercise, finance, or sell."
        ),
    }


__all__ = ["price_control_option"]
