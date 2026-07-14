"""Build an auditable critical-date calendar from cited lease clauses.

Relative notice rules are resolved only when both the rule and its anchor date
are available.  Unresolvable conditional dates are surfaced in ``unresolved``;
they are never replaced with assumed calendar values.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Any

from cre_mcp.leases.models import CitedClaim, LeaseAbstract, LeaseOption

_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "eighteen": 18, "twenty": 20, "thirty": 30,
}


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


def _subtract_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _number(raw: str) -> int | None:
    paren = re.search(r"\((\d+)\)", raw)
    if paren:
        return int(paren.group(1))
    digit = re.search(r"\d+", raw)
    if digit:
        return int(digit.group(0))
    return _WORDS.get(raw.strip().casefold())


def _relative_offsets(rule: str) -> tuple[tuple[str, int] | None, tuple[str, int] | None]:
    """Return exercise-open and exercise-close offsets from expiration."""
    tokens: list[tuple[str, int]] = []
    for match in re.finditer(
        r"(?P<n>[A-Za-z]+(?:\s*\(\d+\))?|\d+)\s+(?P<unit>months?|days?)\s+"
        r"(?:before|prior\s+to)",
        rule,
        re.I,
    ):
        number = _number(match.group("n"))
        if number is not None:
            tokens.append(("months" if match.group("unit").casefold().startswith("month") else "days", number))
    # In the common construction "not more than 12 months nor less than 6
    # months prior", the final "prior" grammatically applies to both numbers.
    if re.search(r"\b(?:before|prior\s+to)\b", rule, re.I):
        all_offsets: list[tuple[str, int]] = []
        for match in re.finditer(
            r"(?P<n>[A-Za-z]+(?:\s*\(\d+\))?|\d+)\s+(?P<unit>months?|days?)",
            rule,
            re.I,
        ):
            number = _number(match.group("n"))
            if number is not None:
                all_offsets.append((
                    "months" if match.group("unit").casefold().startswith("month") else "days",
                    number,
                ))
        if len(all_offsets) > len(tokens):
            tokens = all_offsets
    if not tokens:
        return None, None
    if len(tokens) == 1:
        return None, tokens[0]
    # Farther from expiration opens the window; nearer closes it.
    same_unit = {unit for unit, _ in tokens}
    if len(same_unit) == 1:
        unit = tokens[0][0]
        return (unit, max(n for _, n in tokens)), (unit, min(n for _, n in tokens))
    # Mixed-unit clauses are unusual; compare approximate days only to order,
    # while retaining each original unit for exact date arithmetic.
    ordered = sorted(tokens, key=lambda item: item[1] * (30 if item[0] == "months" else 1), reverse=True)
    return ordered[0], ordered[-1]


def _offset(anchor: date, spec: tuple[str, int]) -> date:
    unit, number = spec
    return _subtract_months(anchor, number) if unit == "months" else anchor - timedelta(days=number)


def _event(
    name: str,
    when: date,
    severity: str,
    claim: CitedClaim,
    as_of: date,
) -> dict[str, Any]:
    days = (when - as_of).days
    horizon = next((value for value in (90, 180, 365) if 0 <= days <= value), None)
    return {
        "event": name,
        "date": when.isoformat(),
        "severity": severity,
        "days_from_as_of": days,
        "horizon_days": horizon,
        "source": claim.source,
        "quote": claim.quote,
        "locator": claim.locator,
        "confidence": claim.confidence,
    }


def _option_events(
    option: LeaseOption,
    index: int,
    expiration: date | None,
    as_of: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    kind = option.option_type.value if option.option_type.status != "missing" else f"option_{index}"
    rule_claim = (
        option.notice_deadline_rule
        if option.notice_deadline_rule.status != "missing"
        else option.exercise_window
    )
    if rule_claim.status == "missing" or not isinstance(rule_claim.value, str):
        unresolved.append({"event": f"{kind}_exercise_window", "reason": "notice rule missing"})
        return events, unresolved

    explicit = re.search(r"\b\d{4}-\d{2}-\d{2}\b", rule_claim.value)
    if explicit:
        deadline = date.fromisoformat(explicit.group(0))
        events.append(_event(f"{kind}_notice_deadline", deadline, "value_destroying", rule_claim, as_of))
        return events, unresolved
    if expiration is None:
        unresolved.append({
            "event": f"{kind}_exercise_window",
            "reason": "expiration is missing or conditional",
            "rule": rule_claim.value,
            "source": rule_claim.source,
        })
        return events, unresolved

    open_spec, close_spec = _relative_offsets(rule_claim.value)
    if close_spec is None:
        unresolved.append({
            "event": f"{kind}_exercise_window",
            "reason": "relative notice offset not deterministically parseable",
            "rule": rule_claim.value,
            "source": rule_claim.source,
        })
        return events, unresolved
    close_date = _offset(expiration, close_spec)
    if open_spec is not None:
        events.append(_event(f"{kind}_exercise_window_open", _offset(expiration, open_spec), "value_destroying", rule_claim, as_of))
    else:
        unresolved.append({
            "event": f"{kind}_exercise_window_open",
            "reason": "rule states a deadline but no opening bound",
            "rule": rule_claim.value,
            "source": rule_claim.source,
        })
    events.append(_event(f"{kind}_exercise_window_close", close_date, "value_destroying", rule_claim, as_of))
    events.append(_event(f"{kind}_notice_deadline", close_date, "value_destroying", rule_claim, as_of))
    return events, unresolved


def critical_dates(abstract: LeaseAbstract, as_of: date | datetime | str) -> dict[str, Any]:
    """Return expiration, option/notice, and rent-step dates in three horizons."""
    as_of_date = _date(as_of, name="as_of")
    events: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    expiration = _claim_date(abstract.dates.expiration)
    if expiration is not None:
        events.append(_event("lease_expiration", expiration, "critical", abstract.dates.expiration, as_of_date))
    elif abstract.dates.expiration.status != "missing":
        unresolved.append({
            "event": "lease_expiration",
            "reason": "expiration is stated as a rule/reference, not a calendar date",
            "value": abstract.dates.expiration.value,
            "source": abstract.dates.expiration.source,
        })
    else:
        unresolved.append({"event": "lease_expiration", "reason": "expiration missing"})

    for index, option in enumerate(abstract.options, start=1):
        option_dates, option_unresolved = _option_events(option, index, expiration, as_of_date)
        events.extend(option_dates)
        unresolved.extend(option_unresolved)

    commencement = _claim_date(abstract.dates.commencement)
    seen_steps: set[date] = set()
    for period in abstract.rent_schedule:
        step = _claim_date(period.start)
        if step is None or step == commencement or step in seen_steps:
            continue
        seen_steps.add(step)
        claim = period.start
        events.append(_event("rent_step", step, "informational", claim, as_of_date))

    events.sort(key=lambda item: (item["date"], item["event"]))
    horizons = {
        str(days): [item for item in events if 0 <= item["days_from_as_of"] <= days]
        for days in (90, 180, 365)
    }
    return {
        "as_of": as_of_date.isoformat(),
        "dates": events,
        "horizons": horizons,
        "unresolved": unresolved,
    }


__all__ = ["critical_dates"]
