"""Structured term-sheet comparison with visible objectives and caveats.

Version 1 intentionally accepts structured terms.  It does not parse PDFs or
attempt to infer terms that a lender did not quote.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable, Mapping

from cre_mcp.underwriting.metrics import annual_debt_service, dscr


QUOTED_TERMS_WARNING = (
    "quoted terms are not closed terms. Closed-vs-quoted history lives in the "
    "lender ledger; use tool lender_track_record."
)
STRUCTURED_INPUT_SCOPE = (
    "v1 takes structured term-sheet inputs; PDF term-sheet parsing is not included."
)
NOT_COMPUTABLE = "not_computable"


@dataclass(slots=True)
class TermSheet:
    """A lender quote supplied as structured input.

    Rates may be a fixed numeric rate or a mapping containing an index value
    and spread, for example ``{"index": "SOFR", "index_rate": 0.05,
    "spread_bps": 250}``.  Optional fields default to ``None`` only so a
    comparison can report the exact missing input; ``None`` is never modeled
    as zero.
    """

    lender: str | None = None
    proceeds: float | None = None
    rate: float | Mapping[str, Any] | None = None
    io_months: int | None = None
    amort_years: int | None = None
    term_years: float | None = None
    origination_fee_pct: float | None = None
    exit_fee_pct: float | None = None
    other_fees: float | Mapping[str, Any] | list[Any] | None = None
    recourse: str | None = None
    covenants: Mapping[str, Any] | None = None
    prepay: Mapping[str, Any] | None = None
    extension_options: list[Any] | Mapping[str, Any] | int | None = None
    rate_cap_required: bool | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TermSheet":
        """Build from a mapping while ignoring unrelated source metadata."""
        names = cls.__dataclass_fields__.keys()
        return cls(**{name: value.get(name) for name in names})


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rate_decimal(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    number = number / 100 if number > 1 else number
    return number if 0 <= number < 1 else None


def _ratio_decimal(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    number = number / 100 if number > 1 else number
    return number if 0 <= number <= 1 else None


def _fee_pct_decimal(value: Any) -> float | None:
    """Normalize typical fee decimals or percentage-point quotes.

    Values above 10% are treated as percentage points because quoted CRE loan
    fees commonly arrive as ``0.5`` or ``1`` while decimal inputs commonly
    arrive as ``0.005`` or ``0.01``.
    """
    number = _number(value)
    if number is None:
        return None
    number = number / 100 if number > 0.10 else number
    return number if 0 <= number <= 1 else None


def _resolve_rate(
    raw_rate: float | Mapping[str, Any] | None,
) -> tuple[float | None, dict[str, Any], list[str]]:
    """Resolve a fixed or index-plus-spread quote without sourcing an index."""
    if isinstance(raw_rate, Mapping):
        rate_type = str(raw_rate.get("type", "")).casefold()
        index_name = raw_rate.get("index") or raw_rate.get("index_name")
        is_floating = bool(index_name) or rate_type in {"floating", "variable", "index"}
        if not is_floating:
            fixed = _rate_decimal(
                raw_rate.get(
                    "rate",
                    raw_rate.get("value", raw_rate.get("fixed_rate", raw_rate.get("fixed"))),
                )
            )
            missing = [] if fixed is not None else ["rate.fixed_rate"]
            return fixed, {"type": "fixed", "rate": fixed}, missing

        index_rate = _rate_decimal(
            raw_rate.get("index_rate", raw_rate.get("index_value", raw_rate.get("base_rate")))
        )
        spread_bps = _number(raw_rate.get("spread_bps"))
        if spread_bps is None:
            raw_spread = _number(raw_rate.get("spread"))
            if raw_spread is None:
                spread = None
            elif raw_spread >= 100:
                spread = raw_spread / 10_000
            else:
                spread = _rate_decimal(raw_spread)
        else:
            spread = spread_bps / 10_000
        missing: list[str] = []
        if index_rate is None:
            missing.append("rate.index_rate")
        if spread is None:
            missing.append("rate.spread_bps")
        resolved = index_rate + spread if index_rate is not None and spread is not None else None
        return resolved, {
            "type": "floating",
            "index": index_name,
            "index_rate": index_rate,
            "spread": spread,
            "resolved_rate": resolved,
            "basis": "caller-supplied index value plus caller-supplied spread",
        }, missing

    fixed = _rate_decimal(raw_rate)
    missing = [] if fixed is not None else ["rate"]
    return fixed, {"type": "fixed", "rate": fixed}, missing


def _fee_amount(value: Any) -> float | None:
    """Sum an explicitly supplied fee amount, fee mapping, or fee list."""
    direct = _number(value)
    if direct is not None:
        return direct if direct >= 0 else None
    if isinstance(value, Mapping):
        values = [_number(item) for item in value.values()]
        if any(item is None or item < 0 for item in values):
            return None
        return sum(item for item in values if item is not None)
    if isinstance(value, list):
        total = 0.0
        for item in value:
            amount = _number(item.get("amount")) if isinstance(item, Mapping) else _number(item)
            if amount is None or amount < 0:
                return None
            total += amount
        return total
    return None


def _reserve_total(covenants: Mapping[str, Any] | None) -> tuple[float | None, list[str]]:
    if not isinstance(covenants, Mapping):
        return None, ["covenants.reserves"]
    reserves = covenants.get("reserves")
    if not isinstance(reserves, Mapping):
        return None, ["covenants.reserves"]
    required = ("ti_lc", "capex", "tax_insurance")
    missing = [f"covenants.reserves.{name}" for name in required if _number(reserves.get(name)) is None]
    if missing:
        return None, missing
    amounts = [float(reserves[name]) for name in required]
    if any(amount < 0 for amount in amounts):
        return None, ["covenants.reserves (non-negative amounts required)"]
    holdbacks = covenants.get("holdbacks")
    if holdbacks is not None:
        holdback_amount = _fee_amount(holdbacks)
        if holdback_amount is None:
            return None, ["covenants.holdbacks"]
        amounts.append(holdback_amount)
    return sum(amounts), []


def _debt_service_values(
    proceeds: float | None,
    rate: float | None,
    io_months: int | None,
    amort_years: int | None,
) -> tuple[float | None, float | None, list[str]]:
    """Return year-one blended and post-IO annual debt service."""
    missing: list[str] = []
    if proceeds is None or proceeds <= 0:
        missing.append("proceeds")
    if rate is None:
        missing.append("rate")
    if io_months is None or io_months < 0:
        missing.append("io_months")
    if amort_years is None or amort_years <= 0:
        missing.append("amort_years")
    if missing:
        return None, None, missing
    assert proceeds is not None and rate is not None and io_months is not None
    assert amort_years is not None
    amortizing = annual_debt_service(proceeds, rate, amort_years)
    if amortizing is None:
        return None, None, ["rate/amort_years combination"]
    io_in_year_one = min(io_months, 12)
    year_one = proceeds * rate * (io_in_year_one / 12) + amortizing * (
        (12 - io_in_year_one) / 12
    )
    return year_one, amortizing, []


def _deal_noi(deal: Mapping[str, Any]) -> tuple[float | None, float | None, list[str]]:
    year_one = _number(deal.get("noi"))
    exit_assumptions = deal.get("exit_assumptions")
    stabilized = _number(deal.get("stabilized_noi"))
    if stabilized is None and isinstance(exit_assumptions, Mapping):
        stabilized = _number(exit_assumptions.get("stabilized_noi"))
    missing: list[str] = []
    if year_one is None:
        missing.append("deal.noi")
    if stabilized is None:
        missing.append("deal.exit_assumptions.stabilized_noi")
    return year_one, stabilized, missing


def _prepay_score(prepay: Mapping[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    prepay_type = str(prepay.get("type", "")).casefold() if isinstance(prepay, Mapping) else ""
    points = {
        "open": 40.0,
        "stepdown": 28.0,
        "defeasance": 12.0,
        "yield_maintenance": 5.0,
    }.get(prepay_type)
    return points, {
        "score": points,
        "maximum": 40.0,
        "input": prepay_type or None,
        "formula": "open=40; stepdown=28; defeasance=12; yield_maintenance=5",
        "status": "computed" if points is not None else NOT_COMPUTABLE,
    }


def _extension_score(options: Any) -> tuple[float | None, dict[str, Any]]:
    if isinstance(options, int) and not isinstance(options, bool) and options >= 0:
        count = options
    elif isinstance(options, list):
        count = len(options)
    elif isinstance(options, Mapping):
        raw_count = _number(options.get("count"))
        count = int(raw_count) if raw_count is not None and raw_count >= 0 else None
    else:
        count = None
    score = min(count * 5.0, 20.0) if count is not None else None
    return score, {
        "score": score,
        "maximum": 20.0,
        "option_count": count,
        "formula": "5 points per stated extension option, capped at 20",
        "status": "computed" if score is not None else NOT_COMPUTABLE,
    }


def _covenant_score(
    covenants: Mapping[str, Any] | None,
    year_one_dscr: float | None,
    current_ltv: float | None,
) -> tuple[float | None, dict[str, Any]]:
    min_dscr = _number(covenants.get("min_dscr")) if isinstance(covenants, Mapping) else None
    max_ltv = _ratio_decimal(covenants.get("max_ltv")) if isinstance(covenants, Mapping) else None
    if min_dscr is None or min_dscr <= 0 or max_ltv is None or max_ltv <= 0:
        return None, {
            "score": None,
            "maximum": 40.0,
            "formula": (
                "20*clamp((year_1_DSCR/min_DSCR-1)/0.25,0,1) + "
                "20*clamp((max_LTV-current_LTV)/0.15,0,1)"
            ),
            "status": NOT_COMPUTABLE,
            "missing_inputs": [
                name
                for name, value in (
                    ("covenants.min_dscr", min_dscr),
                    ("covenants.max_ltv", max_ltv),
                    ("year_1_dscr", year_one_dscr),
                    ("current_ltv", current_ltv),
                )
                if value is None
            ],
        }
    if year_one_dscr is None or current_ltv is None:
        return None, {
            "score": None,
            "maximum": 40.0,
            "formula": (
                "20*clamp((year_1_DSCR/min_DSCR-1)/0.25,0,1) + "
                "20*clamp((max_LTV-current_LTV)/0.15,0,1)"
            ),
            "status": NOT_COMPUTABLE,
            "missing_inputs": [
                name
                for name, value in (("year_1_dscr", year_one_dscr), ("current_ltv", current_ltv))
                if value is None
            ],
        }
    dscr_points = 20 * max(0.0, min((year_one_dscr / min_dscr - 1) / 0.25, 1.0))
    ltv_points = 20 * max(0.0, min((max_ltv - current_ltv) / 0.15, 1.0))
    return dscr_points + ltv_points, {
        "score": dscr_points + ltv_points,
        "maximum": 40.0,
        "dscr_headroom_points": dscr_points,
        "ltv_headroom_points": ltv_points,
        "formula": (
            "20*clamp((year_1_DSCR/min_DSCR-1)/0.25,0,1) + "
            "20*clamp((max_LTV-current_LTV)/0.15,0,1)"
        ),
        "status": "computed",
    }


def _rank(
    rows: list[dict[str, Any]],
    metric: str,
    *,
    reverse: bool,
    objective: str,
) -> dict[str, Any]:
    computable = [row for row in rows if _number(row.get(metric)) is not None]
    computable.sort(key=lambda row: float(row[metric]), reverse=reverse)
    ranked = [
        {"rank": rank, "lender": row["lender"], "value": row[metric]}
        for rank, row in enumerate(computable, start=1)
    ]
    unavailable = [row["lender"] for row in rows if _number(row.get(metric)) is None]
    return {
        "objective": objective,
        "metric": metric,
        "direction": "highest" if reverse else "lowest",
        "ranked": ranked,
        "winner": ranked[0]["lender"] if ranked else None,
        "not_computable": unavailable,
        "warning": QUOTED_TERMS_WARNING,
    }


def _risk_notes(
    sheet: TermSheet,
    rate_details: Mapping[str, Any],
) -> list[str]:
    notes: list[str] = []
    recourse = (sheet.recourse or "").casefold()
    if not recourse:
        notes.append("Recourse is missing; guaranty exposure is not computable.")
    elif recourse not in {"non", "nonrecourse", "non-recourse"}:
        notes.append(f"Recourse exposure is quoted as {sheet.recourse}; confirm carveouts and caps.")
    else:
        notes.append("Nonrecourse is quoted; confirm bad-boy carveouts and any springing recourse.")
    covenants = sheet.covenants if isinstance(sheet.covenants, Mapping) else {}
    if covenants.get("cash_sweep_trigger") is not None:
        notes.append(f"Cash sweep/trap trigger is stated as {covenants['cash_sweep_trigger']}.")
    else:
        notes.append("Cash sweep/trap trigger is missing and therefore not assessed.")
    if rate_details.get("type") == "floating":
        if sheet.rate_cap_required is True:
            notes.append("Floating-rate cap is required; cap premium and renewal cost were not supplied.")
        elif sheet.rate_cap_required is False:
            notes.append("Floating rate is quoted without a required cap; index increases remain exposed.")
        else:
            notes.append("Floating-rate cap requirement/cost is missing; rate-cap exposure is not computable.")
    return notes


def _compare_one(sheet: TermSheet, deal: Mapping[str, Any]) -> dict[str, Any]:
    proceeds = _number(sheet.proceeds)
    rate, rate_details, rate_missing = _resolve_rate(sheet.rate)
    year_one_noi, stabilized_noi, noi_missing = _deal_noi(deal)
    year_one_ds, stabilized_ds, debt_service_missing = _debt_service_values(
        proceeds, rate, sheet.io_months, sheet.amort_years
    )
    year_one_dscr = dscr(year_one_noi, year_one_ds)
    stabilized_dscr = dscr(stabilized_noi, stabilized_ds)
    price = _number(deal.get("price"))
    current_ltv = proceeds / price if proceeds is not None and price is not None and price > 0 else None

    origination_pct = _fee_pct_decimal(sheet.origination_fee_pct)
    exit_pct = _fee_pct_decimal(sheet.exit_fee_pct)
    other_fees = _fee_amount(sheet.other_fees)
    term_years = _number(sheet.term_years)
    cost_missing = list(rate_missing)
    for name, value in (
        ("proceeds", proceeds),
        ("term_years", term_years),
        ("origination_fee_pct", origination_pct),
        ("exit_fee_pct", exit_pct),
        ("other_fees", other_fees),
    ):
        if value is None or (name in {"proceeds", "term_years"} and value <= 0):
            cost_missing.append(name)
    if not cost_missing and rate is not None and proceeds is not None and term_years is not None:
        fee_dollars = proceeds * (origination_pct + exit_pct) + other_fees  # type: ignore[operator]
        annualized_fee_rate = fee_dollars / proceeds / term_years
        all_in_cost = rate + annualized_fee_rate
    else:
        fee_dollars = None
        annualized_fee_rate = None
        all_in_cost = None

    reserve_total, reserve_missing = _reserve_total(sheet.covenants)
    net_proceeds = proceeds - reserve_total if proceeds is not None and reserve_total is not None else None
    prepay_score, prepay_details = _prepay_score(sheet.prepay)
    extension_score, extension_details = _extension_score(sheet.extension_options)
    covenant_score, covenant_details = _covenant_score(sheet.covenants, year_one_dscr, current_ltv)
    flexibility = (
        prepay_score + extension_score + covenant_score
        if prepay_score is not None and extension_score is not None and covenant_score is not None
        else None
    )
    flex_missing: list[str] = []
    if prepay_score is None:
        flex_missing.append("prepay.type")
    if extension_score is None:
        flex_missing.append("extension_options")
    if covenant_score is None:
        flex_missing.extend(covenant_details.get("missing_inputs", ["covenant headroom inputs"]))

    missing_inputs = sorted(
        set(
            cost_missing
            + noi_missing
            + debt_service_missing
            + reserve_missing
            + flex_missing
            + ([] if price is not None and price > 0 else ["deal.price"])
        )
    )
    return {
        "lender": sheet.lender or "unnamed lender",
        "status": "computed" if not missing_inputs else "partially_computable",
        "projection_label": (
            "Projection — year-1 and stabilized results use only the stated NOI and loan "
            "assumptions shown below; they are not observed future performance."
        ),
        "warning": QUOTED_TERMS_WARNING,
        "scope": STRUCTURED_INPUT_SCOPE,
        "all_in_cost": all_in_cost,
        "all_in_cost_pct": all_in_cost * 100 if all_in_cost is not None else None,
        "all_in_cost_detail": {
            "note_rate": rate,
            "fee_dollars": fee_dollars,
            "annualized_fee_rate": annualized_fee_rate,
            "formula": "note rate + (origination fee + exit fee + other stated fees) / proceeds / term years",
            "status": "computed" if all_in_cost is not None else NOT_COMPUTABLE,
            "missing_inputs": sorted(set(cost_missing)),
        },
        "rate": rate_details,
        "year_1_debt_service": year_one_ds,
        "stabilized_debt_service": stabilized_ds,
        "year_1_dscr": year_one_dscr,
        "stabilized_dscr": stabilized_dscr,
        "year_1_debt_yield": year_one_noi / proceeds if year_one_noi is not None and proceeds else None,
        "stabilized_debt_yield": stabilized_noi / proceeds if stabilized_noi is not None and proceeds else None,
        "year_1_cash_after_debt_service": (
            year_one_noi - year_one_ds
            if year_one_noi is not None and year_one_ds is not None
            else None
        ),
        "stabilized_cash_after_debt_service": (
            stabilized_noi - stabilized_ds
            if stabilized_noi is not None and stabilized_ds is not None
            else None
        ),
        "proceeds": proceeds,
        "stated_reserves_holdbacks": reserve_total,
        "proceeds_net_of_stated_reserves_holdbacks": net_proceeds,
        "net_proceeds_status": "computed" if net_proceeds is not None else NOT_COMPUTABLE,
        "current_ltv": current_ltv,
        "flexibility_score": flexibility,
        "flexibility_score_detail": {
            "score": flexibility,
            "maximum": 100.0,
            "prepayment": prepay_details,
            "extensions": extension_details,
            "covenant_headroom": covenant_details,
            "formula": "prepayment openness (40) + extension options (20) + covenant headroom (40)",
            "status": "computed" if flexibility is not None else NOT_COMPUTABLE,
            "missing_inputs": sorted(set(flex_missing)),
        },
        "risk_notes": _risk_notes(sheet, rate_details),
        "missing_inputs": missing_inputs,
        "assumptions": {
            "stabilized_period": "first recurring post-IO amortizing year",
            "fee_treatment": "all stated fees amortized over quoted term; no tax effects or fee financing",
            "floating_rate": "uses only the caller-supplied index value; no forward curve",
            "reserves": "only stated reserve/holdback amounts are deducted",
        },
        "structured_input": asdict(sheet),
    }


def compare_term_sheets(
    sheets: Iterable[TermSheet | Mapping[str, Any]],
    deal: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare lender quotes and rank each explicitly stated objective separately."""
    normalized = [
        sheet if isinstance(sheet, TermSheet) else TermSheet.from_mapping(sheet)
        for sheet in sheets
    ]
    rows = [_compare_one(sheet, deal) for sheet in normalized]
    return {
        "status": "computed" if rows else NOT_COMPUTABLE,
        "projection_label": (
            "Projection — year-1 and stabilized results use only the stated NOI and loan "
            "assumptions; they are not observed future performance."
        ),
        "warning": QUOTED_TERMS_WARNING,
        "lender_ledger_pointer": "lender_track_record",
        "scope": STRUCTURED_INPUT_SCOPE,
        "comparisons": rows,
        "ranked_verdicts": {
            "max_proceeds": _rank(
                rows,
                "proceeds_net_of_stated_reserves_holdbacks",
                reverse=True,
                objective="maximize net stated proceeds",
            ),
            "min_cost": _rank(
                rows,
                "all_in_cost",
                reverse=False,
                objective="minimize fee-adjusted annual borrowing cost",
            ),
            "max_flexibility": _rank(
                rows,
                "flexibility_score",
                reverse=True,
                objective="maximize disclosed flexibility score",
            ),
        },
        "overall_ranking": None,
        "ranking_note": "No hidden composite ranking is applied; select the stated objective.",
        "assumption_sheet": {
            "deal_inputs": dict(deal),
            "stabilized_period": "first recurring post-IO amortizing year",
            "fee_amortization_period": "quoted term_years",
            "unmodeled": [
                "PDF extraction",
                "forward index curves",
                "rate-cap premiums unless supplied as an other fee",
                "tax effects",
                "lender retrades and closing probability",
            ],
        },
    }


__all__ = [
    "NOT_COMPUTABLE",
    "QUOTED_TERMS_WARNING",
    "STRUCTURED_INPUT_SCOPE",
    "TermSheet",
    "compare_term_sheets",
]
