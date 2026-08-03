"""Price cited lease options against caller-supplied market ranges.

The engine does not source market data and does not manufacture missing option
terms.  Each economic line names its required inputs, its calculation basis,
and whether it is computable.  Decision frames always retain their drivers and
caveats; they are not legal conclusions or bare exercise verdicts.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, replace
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from cre_mcp.leases.dates import critical_dates
from cre_mcp.leases.models import CitedClaim, LeaseAbstract, LeaseOption


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
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


def _number(name: str, value: object, *, allow_negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (not allow_negative and result < 0):
        qualifier = "finite" if allow_negative else "finite and non-negative"
        raise ValueError(f"{name} must be {qualifier}")
    return result


def _range(
    market: Mapping[str, object],
    *keys: str,
) -> tuple[tuple[float, float] | None, list[str]]:
    key = next((candidate for candidate in keys if candidate in market), keys[0])
    if key not in market or market[key] is None:
        return None, [key]
    raw = market[key]
    if isinstance(raw, Mapping):
        low_raw = next((raw[k] for k in ("low", "min", "minimum") if k in raw), None)
        high_raw = next((raw[k] for k in ("high", "max", "maximum") if k in raw), None)
        if low_raw is None or high_raw is None:
            return None, [f"{key}.low", f"{key}.high"]
        low = _number(f"{key}.low", low_raw)
        high = _number(f"{key}.high", high_raw)
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        if len(raw) != 2:
            raise ValueError(f"{key} range must contain exactly two values")
        low = _number(f"{key}[0]", raw[0])
        high = _number(f"{key}[1]", raw[1])
    else:
        low = high = _number(key, raw)
    if low > high:
        raise ValueError(f"{key} range must be ordered low to high")
    return (low, high), []


def _claim_payload(claim: CitedClaim) -> dict[str, object]:
    return asdict(claim)


def _option_kind(option: LeaseOption) -> str:
    if option.option_type.status == "missing":
        return "unknown"
    return str(option.option_type.value).casefold().replace("-", "_")


def _options(value: object) -> tuple[list[LeaseOption], LeaseAbstract | None]:
    if isinstance(value, LeaseAbstract):
        return list(value.options), value
    if isinstance(value, LeaseOption):
        return [value], None
    if isinstance(value, Mapping):
        raw_options = value.get("options")
        if raw_options is None and isinstance(value.get("option"), LeaseOption):
            raw_options = [value["option"]]
        if isinstance(raw_options, Sequence) and not isinstance(raw_options, (str, bytes)):
            options = list(raw_options)
            if all(isinstance(option, LeaseOption) for option in options):
                return options, None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        options = list(value)
        if all(isinstance(option, LeaseOption) for option in options):
            return options, None
    raise TypeError("abstract_or_terms must be a LeaseAbstract, LeaseOption, or sequence of LeaseOption")


def _claim_text(claim: CitedClaim) -> str:
    if claim.status == "missing":
        return ""
    if isinstance(claim.value, str):
        return claim.value
    return claim.quote


def _word_number(raw: str) -> int | None:
    parenthetical = re.search(r"\((\d+)\)", raw)
    if parenthetical:
        return int(parenthetical.group(1))
    digit = re.search(r"\d+", raw)
    if digit:
        return int(digit.group(0))
    return _NUMBER_WORDS.get(raw.casefold().strip())


def _term_years(option: LeaseOption, market: Mapping[str, object]) -> tuple[float | None, str, list[str]]:
    value = option.rent_basis.value if option.rent_basis.status != "missing" else None
    if isinstance(value, Mapping):
        if value.get("term_years") is not None:
            return _number("option term_years", value["term_years"]), "cited option term_years", []
        if value.get("term_months") is not None:
            months = _number("option term_months", value["term_months"])
            return months / 12.0, "cited option term_months / 12", []
    text = " ".join(
        part
        for part in (
            _claim_text(option.rent_basis),
            _claim_text(option.exercise_window),
            option.rent_basis.quote,
        )
        if part
    )
    match = re.search(
        r"(?P<n>[A-Za-z]+(?:\s*\(\d+\))?|\d+)\s*[- ]?year(?:s|\s+term)?\b",
        text,
        re.I,
    )
    if match:
        number = _word_number(match.group("n"))
        if number is not None:
            return float(number), "term stated in cited option language", []
    if market.get("option_term_years") is not None:
        return (
            _number("option_term_years", market["option_term_years"]),
            "caller-provided option_term_years estimate",
            [],
        )
    return None, "", ["cited_option_term_years"]


def _rentable_sf(
    abstract: LeaseAbstract | None,
    option: LeaseOption,
    market: Mapping[str, object],
    kind: str,
) -> tuple[float | None, str, list[str]]:
    value = option.rent_basis.value if option.rent_basis.status != "missing" else None
    if isinstance(value, Mapping):
        option_key = "expansion_sf" if kind == "expand" else "rentable_sf"
        if value.get(option_key) is not None:
            return _number(option_key, value[option_key]), f"{option_key} in cited option terms", []
    if kind == "expand":
        if market.get("expansion_sf") is not None:
            return _number("expansion_sf", market["expansion_sf"]), "caller-provided expansion_sf estimate", []
        return None, "", ["expansion_sf"]
    if abstract is not None and abstract.premises.rentable_sf.status != "missing":
        return (
            _number("premises rentable_sf", abstract.premises.rentable_sf.value),
            "rentable_sf from cited lease premises",
            [],
        )
    if market.get("rentable_sf") is not None:
        return _number("rentable_sf", market["rentable_sf"]), "caller-provided rentable_sf estimate", []
    return None, "", ["rentable_sf"]


def _fixed_rent_from_text(text: str) -> tuple[float | None, float | None]:
    psf = re.search(
        r"\$\s*(?P<v>\d[\d,]*(?:\.\d+)?)\s*(?:per\s+|/\s*)"
        r"(?:rentable\s+)?(?:square\s+foot|sq\.?\s*ft\.?|rsf|psf)\b",
        text,
        re.I,
    ) or re.search(
        r"\$\s*(?P<v>\d[\d,]*(?:\.\d+)?)\s+(?:psf|rsf)\b",
        text,
        re.I,
    )
    annual = re.search(
        r"\$\s*(?P<v>\d[\d,]*(?:\.\d+)?)\s*(?:per\s+annum|annually|annual\s+rent)",
        text,
        re.I,
    )
    psf_value = float(psf.group("v").replace(",", "")) if psf else None
    annual_value = float(annual.group("v").replace(",", "")) if annual else None
    return psf_value, annual_value


def _rent_basis(
    option: LeaseOption,
    market: Mapping[str, object],
    market_rent: tuple[float, float] | None,
    sf: float | None,
) -> dict[str, object]:
    claim = option.rent_basis
    if claim.status == "missing":
        return {
            "status": "not_computable",
            "kind": None,
            "rent_psf_range": None,
            "basis": [],
            "missing_inputs": ["cited_option_rent_basis"],
            "claim": _claim_payload(claim),
        }
    value = claim.value
    text = _claim_text(claim)
    kind: str | None = None
    rent_range: tuple[float, float] | None = None
    missing: list[str] = []
    basis: list[str] = []

    if isinstance(value, Mapping):
        raw_kind = value.get("type", value.get("basis", value.get("kind")))
        if raw_kind is not None:
            normalized = str(raw_kind).casefold().replace("-", "_").replace(" ", "_")
            if normalized in {"fixed", "fixed_rent"}:
                kind = "fixed"
            elif normalized in {"fmv", "fair_market_value", "fair_market_rent", "market"}:
                kind = "fmv"
            elif normalized in {"cpi", "cpi_based"}:
                kind = "cpi"
        raw_psf = value.get("rent_psf", value.get("rate_psf", value.get("option_rent_psf")))
        if raw_psf is not None:
            fixed = _number("option rent_psf", raw_psf)
            rent_range = (fixed, fixed)
            kind = kind or "fixed"
            basis.append("fixed rent_psf in cited option terms")
        raw_annual = value.get("annual_rent")
        if raw_annual is not None:
            if sf is None or sf == 0:
                missing.append("rentable_sf_for_annual_option_rent")
            else:
                fixed = _number("option annual_rent", raw_annual) / sf
                rent_range = (fixed, fixed)
                kind = kind or "fixed"
                basis.append("cited annual option rent / rentable_sf")

    if kind is None:
        if re.search(r"\b(?:fair\s+market\s+(?:value|rent)|market\s+rent|then[- ]prevailing\s+rent|FMV)\b", text, re.I):
            kind = "fmv"
        elif re.search(r"\b(?:Consumer\s+Price\s+Index|CPI(?:-U|-W)?)\b", text, re.I):
            kind = "cpi"
        else:
            psf, annual = _fixed_rent_from_text(text)
            if psf is not None:
                kind = "fixed"
                rent_range = (psf, psf)
                basis.append("fixed per-square-foot rent parsed from cited option language")
            elif annual is not None:
                kind = "fixed"
                if sf is None or sf == 0:
                    missing.append("rentable_sf_for_annual_option_rent")
                else:
                    rent_range = (annual / sf, annual / sf)
                    basis.append("cited annual option rent / rentable_sf")
            else:
                multiple = re.search(
                    r"(?P<v>\d+(?:\.\d+)?)\s*%\s+of\s+(?:the\s+)?(?:then[- ]current|current|preceding)\s+(?:Base|Minimum)?\s*Rent",
                    text,
                    re.I,
                )
                if multiple:
                    kind = "fixed_multiplier"
                    if market.get("current_rent_psf") is None:
                        missing.append("current_rent_psf")
                    else:
                        current = _number("current_rent_psf", market["current_rent_psf"])
                        rate = float(multiple.group("v")) / 100.0
                        rent_range = (current * rate, current * rate)
                        basis.append("cited percentage × caller-provided current_rent_psf")

    if kind == "fmv":
        if market_rent is None:
            missing.append("market_rent_psf")
        else:
            rent_range = market_rent
            basis.append("FMV option basis uses caller-provided market_rent_psf range")
    elif kind == "cpi":
        growth, growth_missing = _range(market, "cpi_growth_pct")
        current_raw = market.get("current_rent_psf")
        years_raw = market.get("years_to_option")
        missing.extend(growth_missing)
        if current_raw is None:
            missing.append("current_rent_psf")
        if years_raw is None:
            missing.append("years_to_option")
        if not missing and growth is not None:
            current = _number("current_rent_psf", current_raw)
            years = _number("years_to_option", years_raw)
            rent_range = (
                current * ((1.0 + growth[0]) ** years),
                current * ((1.0 + growth[1]) ** years),
            )
            basis.append("current_rent_psf × (1 + supplied CPI growth)^years_to_option")

    if kind is None:
        missing.append("parseable_option_rent_basis")
    status = "computed" if rent_range is not None and not missing else "not_computable"
    return {
        "status": status,
        "kind": kind,
        "rent_psf_range": [round(rent_range[0], 4), round(rent_range[1], 4)] if rent_range else None,
        "basis": basis,
        "missing_inputs": sorted(set(missing)),
        "claim": _claim_payload(claim),
    }


def _line_missing(name: str, missing: list[str], basis: list[str] | None = None) -> dict[str, object]:
    return {
        "line": name,
        "status": "not_computable",
        "value_range": None,
        "kind": "estimate",
        "basis": basis or [],
        "missing_inputs": sorted(set(missing)),
    }


def _deadline(
    abstract: LeaseAbstract | None,
    option: LeaseOption,
    as_of: date,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if abstract is None:
        return {
            "status": "not_computable",
            "notice_deadline": None,
            "missing_inputs": ["lease_abstract_with_expiration"],
            "unresolved": [],
        }, []
    calendar = critical_dates(replace(abstract, options=[option]), as_of)
    events = [
        event for event in calendar["dates"]
        if str(event["event"]).endswith("notice_deadline")
    ]
    event = events[0] if events else None
    flags: list[dict[str, object]] = []
    if event is not None and int(event["days_from_as_of"]) < 0:
        flags.append({
            "issue": "cited option notice deadline is before as_of; availability requires counsel review",
            "review": "counsel",
            "deadline": event,
        })
    return {
        "status": "resolved" if event is not None else "not_computable",
        "notice_deadline": event,
        "missing_inputs": [] if event is not None else ["resolvable_notice_rule_and_expiration"],
        "unresolved": calendar["unresolved"],
    }, flags


def _current_rent_psf(abstract: LeaseAbstract | None, as_of: date) -> float | None:
    if abstract is None:
        return None
    for period in abstract.rent_schedule:
        if period.psf.status == "missing":
            continue
        start = None
        end = None
        if isinstance(period.start.value, str):
            try:
                start = date.fromisoformat(period.start.value)
            except ValueError:
                pass
        if isinstance(period.end.value, str):
            try:
                end = date.fromisoformat(period.end.value)
            except ValueError:
                pass
        if (start is None or start <= as_of) and (end is None or as_of <= end):
            return _number("current rent psf", period.psf.value)
    return None


def _termination_economics(
    option: LeaseOption,
    abstract: LeaseAbstract | None,
    market: Mapping[str, object],
    market_rent: tuple[float, float] | None,
    sf: float | None,
    as_of: date,
) -> tuple[dict[str, object], float | None, list[str]]:
    missing: list[str] = []
    current = _current_rent_psf(abstract, as_of)
    if market.get("current_rent_psf") is not None:
        current = _number("current_rent_psf", market["current_rent_psf"])
    if current is None:
        missing.append("current_rent_psf")
    if market_rent is None:
        missing.append("market_rent_psf")
    if sf is None:
        missing.append("rentable_sf")

    remaining: float | None = None
    if abstract is not None and isinstance(abstract.dates.expiration.value, str):
        try:
            expiration = date.fromisoformat(abstract.dates.expiration.value)
            remaining = max(0.0, (expiration - as_of).days / 365.25)
        except ValueError:
            pass
    if market.get("remaining_term_years") is not None:
        remaining = _number("remaining_term_years", market["remaining_term_years"])
    if remaining is None:
        missing.append("remaining_term_years_or_cited_expiration")

    fee = 0.0
    value = option.rent_basis.value if option.rent_basis.status != "missing" else None
    fee_is_stated = False
    if isinstance(value, Mapping) and value.get("termination_fee") is not None:
        fee = _number("termination_fee", value["termination_fee"])
        fee_is_stated = True
    else:
        fee_match = re.search(
            r"termination\s+fee[^$]{0,100}?\$\s*(?P<v>\d[\d,]*(?:\.\d+)?)",
            _claim_text(option.rent_basis),
            re.I,
        )
        if fee_match:
            fee = float(fee_match.group("v").replace(",", ""))
            fee_is_stated = True
    if not fee_is_stated:
        missing.append("cited_termination_fee_or_explicit_no_fee")

    if missing:
        return _line_missing(
            "rent_delta",
            missing,
            ["termination value compares avoided contract rent with replacement market rent and cited fee"],
        ), remaining, missing
    assert current is not None and market_rent is not None and sf is not None and remaining is not None
    low = (current - market_rent[1]) * sf * remaining - fee
    high = (current - market_rent[0]) * sf * remaining - fee
    return {
        "line": "rent_delta",
        "status": "computed",
        "value_range": [round(low, 2), round(high, 2)],
        "kind": "estimate",
        "basis": [
            "(current contract rent − replacement market rent) × rentable_sf × remaining term − cited termination fee"
        ],
        "missing_inputs": [],
    }, remaining, []


def _annuity_factor(rate: float, years: float) -> float:
    if rate == 0:
        return years
    return (1.0 - (1.0 + rate) ** (-years)) / rate


def _decision_frame(
    value_range: list[float] | None,
    economics: Mapping[str, dict[str, object]],
    deadline: Mapping[str, object],
    flags: list[dict[str, object]],
) -> dict[str, object]:
    drivers: list[dict[str, object]] = []
    for line in economics.values():
        drivers.append({
            "driver": line["line"],
            "status": line["status"],
            "value_range": line["value_range"],
            "basis": line["basis"],
            "missing_inputs": line["missing_inputs"],
        })
    drivers.append({
        "driver": "notice_deadline",
        "status": deadline["status"],
        "value": deadline["notice_deadline"],
        "missing_inputs": deadline["missing_inputs"],
    })
    passed = any("deadline is before" in str(flag.get("issue", "")) for flag in flags)
    if value_range is None:
        return {
            "status": "not_computable",
            "lean": None,
            "drivers": drivers,
            "caveats": ["No decision lean is produced until the core rent economics are computable."],
        }
    if passed:
        lean = "renegotiate"
        rationale = "Economics may favor exercise, but the calculated notice deadline has passed."
    elif value_range[0] > 0:
        lean = "exercise"
        rationale = "The complete modeled value range is positive for the option holder."
    elif value_range[1] < 0:
        lean = "let-expire"
        rationale = "The complete modeled value range is negative for the option holder."
    else:
        lean = "renegotiate"
        rationale = "The modeled range crosses zero, so price and execution terms drive the outcome."
    return {
        "status": "framed",
        "lean": lean,
        "rationale": rationale,
        "drivers": drivers,
        "caveats": [
            "This is an economic frame for the option holder, not a legal conclusion.",
            "Market, downtime, and TI/LC ranges are caller estimates, not lease facts.",
        ],
    }


def price_option_decision(
    abstract_or_terms: LeaseAbstract | LeaseOption | Sequence[LeaseOption] | Mapping[str, object],
    market: Mapping[str, object],
    as_of: date | datetime | str,
    discount_rate: float | None = None,
) -> dict[str, object]:
    """Compare each cited option with supplied market ranges.

    ``market_rent_psf``, ``downtime_months``, and ``tilc_psf`` accept either a
    two-item sequence or ``{"low": ..., "high": ...}``.  ``discount_rate`` may
    be supplied as a decimal keyword argument or as ``market["discount_rate"]``.
    Missing inputs make only the affected line not-computable; no zero defaults
    are introduced.
    """

    if not isinstance(market, Mapping):
        raise TypeError("market must be a mapping")
    as_of_date = _date(as_of, name="as_of")
    options, abstract = _options(abstract_or_terms)
    market_rent, market_rent_missing = _range(market, "market_rent_psf")
    downtime, downtime_missing = _range(market, "downtime_months")
    tilc, tilc_missing = _range(market, "tilc_psf", "ti_lc_psf")
    rate_raw = discount_rate if discount_rate is not None else market.get("discount_rate")
    rate = _number("discount_rate", rate_raw) if rate_raw is not None else None

    results: list[dict[str, object]] = []
    for index, option in enumerate(options, start=1):
        kind = _option_kind(option)
        sf, sf_basis, sf_missing = _rentable_sf(abstract, option, market, kind)
        term, term_basis, term_missing = _term_years(option, market)
        deadline, flags = _deadline(abstract, option, as_of_date)
        economics: dict[str, dict[str, object]] = {}
        rent_basis = _rent_basis(option, market, market_rent, sf)

        if kind == "terminate":
            rent_line, remaining, _ = _termination_economics(
                option, abstract, market, market_rent, sf, as_of_date
            )
            economics["rent_delta"] = rent_line
            term_for_costs = remaining
        elif kind in {"renew", "extend", "expand"}:
            missing = [*market_rent_missing, *sf_missing, *term_missing]
            missing.extend(rent_basis["missing_inputs"])
            if missing or market_rent is None or sf is None or term is None or rent_basis["rent_psf_range"] is None:
                economics["rent_delta"] = _line_missing(
                    "rent_delta",
                    missing,
                    [item for item in (sf_basis, term_basis) if item] + list(rent_basis["basis"]),
                )
            else:
                option_rent = rent_basis["rent_psf_range"]
                if rent_basis["kind"] == "fmv":
                    low = high = 0.0
                    basis = [
                        "FMV rent basis has no deterministic rent spread versus the same supplied market range"
                    ]
                else:
                    low = (market_rent[0] - option_rent[1]) * sf * term
                    high = (market_rent[1] - option_rent[0]) * sf * term
                    basis = [
                        "(market rent_psf − option rent_psf) × rentable_sf × option term"
                    ]
                economics["rent_delta"] = {
                    "line": "rent_delta",
                    "status": "computed",
                    "value_range": [round(low, 2), round(high, 2)],
                    "kind": "estimate",
                    "basis": basis + [sf_basis, term_basis] + list(rent_basis["basis"]),
                    "missing_inputs": [],
                }
            term_for_costs = term
        else:
            economics["rent_delta"] = _line_missing(
                "rent_delta",
                ["supported_option_type_renew_extend_terminate_expand"],
                [f"option type {kind!r} is not priced by this engine"],
            )
            term_for_costs = term
            flags.append({
                "issue": f"option type {kind!r} requires a separate valuation method",
                "review": "professional",
            })

        downtime_line_missing = [*market_rent_missing, *downtime_missing, *sf_missing]
        if downtime_line_missing or market_rent is None or downtime is None or sf is None:
            economics["downtime"] = _line_missing(
                "downtime", downtime_line_missing, [sf_basis] if sf_basis else []
            )
        else:
            low = market_rent[0] * sf * downtime[0] / 12.0
            high = market_rent[1] * sf * downtime[1] / 12.0
            if kind == "terminate":
                low, high = -high, -low
                direction = "termination/replacement incurs the supplied downtime rent-equivalent proxy"
            else:
                direction = "exercise avoids the supplied downtime rent-equivalent proxy"
            economics["downtime"] = {
                "line": "downtime",
                "status": "computed",
                "value_range": [round(low, 2), round(high, 2)],
                "kind": "estimate",
                "basis": [
                    "market rent_psf × rentable_sf × downtime_months / 12",
                    direction,
                    sf_basis,
                ],
                "missing_inputs": [],
            }

        tilc_line_missing = [*tilc_missing, *sf_missing]
        if tilc_line_missing or tilc is None or sf is None:
            economics["ti_lc"] = _line_missing(
                "ti_lc", tilc_line_missing, [sf_basis] if sf_basis else []
            )
        else:
            low = tilc[0] * sf
            high = tilc[1] * sf
            if kind == "terminate":
                low, high = -high, -low
                direction = "termination/replacement incurs supplied TI/LC"
            else:
                direction = "exercise avoids supplied TI/LC"
            economics["ti_lc"] = {
                "line": "ti_lc",
                "status": "computed",
                "value_range": [round(low, 2), round(high, 2)],
                "kind": "estimate",
                "basis": ["tilc_psf × rentable_sf", direction, sf_basis],
                "missing_inputs": [],
            }

        rent_value = economics["rent_delta"]["value_range"]
        option_value = list(rent_value) if isinstance(rent_value, list) else None
        complete = all(line["status"] == "computed" for line in economics.values())
        adjusted: list[float] | None = None
        if complete:
            adjusted = [
                round(sum(float(line["value_range"][bound]) for line in economics.values()), 2)
                for bound in (0, 1)
            ]

        pv_value: list[float] | None = None
        pv_adjusted: list[float] | None = None
        if rate is not None and option_value is not None and term_for_costs is not None and term_for_costs > 0:
            factor = _annuity_factor(rate, term_for_costs) / term_for_costs
            pv_value = [round(value * factor, 2) for value in option_value]
            if adjusted is not None:
                # Downtime and TI/LC are treated as immediate one-time amounts;
                # only the multi-year rent spread receives the annuity factor.
                other = [
                    sum(float(economics[name]["value_range"][bound]) for name in ("downtime", "ti_lc"))
                    for bound in (0, 1)
                ]
                pv_adjusted = [
                    round(pv_value[bound] + other[bound], 2) for bound in (0, 1)
                ]

        decision_value = adjusted if adjusted is not None else option_value
        frame = _decision_frame(decision_value, economics, deadline, flags)
        result_status = (
            "computed" if complete else ("partial" if any(line["status"] == "computed" for line in economics.values()) else "not_computable")
        )
        results.append({
            "option_index": index,
            "option_type": kind,
            "status": result_status,
            "option_type_claim": _claim_payload(option.option_type),
            "rent_basis": rent_basis,
            "rentable_sf": sf,
            "term_years": term,
            "economics": economics,
            "option_value_range": option_value,
            "adjusted_option_value_range": adjusted,
            "pv_option_value_range": pv_value,
            "pv_adjusted_option_value_range": pv_adjusted,
            "discount_rate": rate,
            "notice_deadline": deadline,
            "decision_frame": frame,
            "counsel_flags": flags,
            "professional_review_flags": flags,
        })

    return {
        "as_of": as_of_date.isoformat(),
        "perspective": "option_holder",
        "status": "computed" if results and all(result["status"] == "computed" for result in results) else (
            "not_computable" if not results or all(result["status"] == "not_computable" for result in results) else "partial"
        ),
        "options": results,
        "market_inputs": {
            "market_rent_psf": list(market_rent) if market_rent else None,
            "downtime_months": list(downtime) if downtime else None,
            "tilc_psf": list(tilc) if tilc else None,
            "discount_rate": rate,
        },
        "honesty": {
            "market_inputs_are_caller_estimates": True,
            "missing_inputs_are_not_zero_filled": True,
            "decision_frames_are_not_legal_conclusions": True,
        },
    }


__all__ = ["price_option_decision"]
