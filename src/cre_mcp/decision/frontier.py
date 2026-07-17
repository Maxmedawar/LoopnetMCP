"""Buyer-specific structure frontier for commercial-real-estate decisions.

The calculations here are deliberately screening-level. They compare structures
against known buyer constraints and leave buyer-dependent metrics unknown when
the required fact was not supplied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from cre_mcp.decision.profile import BuyerProfile, normalize_buyer

Unknown = Literal["unknown"]
Metric = float | Unknown

UNKNOWN: Unknown = "unknown"
DEFAULT_STRUCTURES = [
    "all_cash",
    "conventional_75ltv",
    "seller_finance",
    "master_lease",
    "option_then_lease",
    "jv_preferred_equity",
]


@dataclass(frozen=True)
class _StructureTerms:
    cash_fraction: float
    debt_fraction: float
    interest_rate: float | None
    amortization_years: int | None
    recourse: Literal["none", "partial", "full"]
    acceptance_base: float
    owns_at_close: bool
    cash_basis: str


_TERMS: dict[str, _StructureTerms] = {
    "all_cash": _StructureTerms(
        1.00, 0.00, None, None, "none", 0.92, True, "100% of stated price"
    ),
    "conventional_75ltv": _StructureTerms(
        0.25, 0.75, 0.07, 25, "full", 0.76, True, "25% equity; 75% LTV"
    ),
    "seller_finance": _StructureTerms(
        0.10, 0.90, 0.06, 30, "partial", 0.46, True, "screening estimate: 10% down"
    ),
    "master_lease": _StructureTerms(
        0.02,
        0.00,
        None,
        None,
        "partial",
        0.40,
        False,
        "screening estimate: deposit/startup cash equal to 2% of price",
    ),
    "option_then_lease": _StructureTerms(
        0.01,
        0.00,
        None,
        None,
        "none",
        0.44,
        False,
        "screening estimate: option consideration equal to 1% of price",
    ),
    "jv_preferred_equity": _StructureTerms(
        0.075,
        0.75,
        0.07,
        25,
        "partial",
        0.34,
        True,
        "screening estimate: buyer funds 30% of the 25% equity requirement",
    ),
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _probability(value: float) -> float:
    return round(_clamp(value), 2)


def _ratio(value: float | None) -> Metric:
    return UNKNOWN if value is None or not math.isfinite(value) else round(value, 3)


def _money(value: float | None) -> float | Unknown:
    return UNKNOWN if value is None or not math.isfinite(value) else round(value, 2)


def _as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1]
        if not cleaned:
            return None
        value = cleaned
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _deal_number(deal: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        number = _as_number(deal.get(key))
        if number is not None:
            return number
    return None


def _positive_deal_number(deal: dict[str, Any], *keys: str) -> float | None:
    number = _deal_number(deal, *keys)
    return number if number is not None and number > 0 else None


def _cap_decimal(value: Any) -> float | None:
    cap = _as_number(value)
    if cap is None or cap <= 0:
        return None
    return cap / 100 if cap > 1 else cap


def _deal_cap(deal: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        cap = _cap_decimal(deal.get(key))
        if cap is not None:
            return cap
    return None


def _noi_and_source(deal: dict[str, Any]) -> tuple[float | None, str]:
    for key in ("verified_noi", "verified_noi_usd"):
        value = _as_number(deal.get(key))
        if value is not None:
            return value, key

    verified = deal.get("verified")
    if isinstance(verified, dict):
        for key in ("noi", "noi_usd"):
            value = _as_number(verified.get(key))
            if value is not None:
                return value, f"verified.{key}"

    verified_marker = deal.get("noi_verified")
    if not isinstance(verified_marker, bool):
        verified_value = _as_number(verified_marker)
        if verified_value is not None:
            return verified_value, "noi_verified"

    for key in ("noi", "noi_usd"):
        value = _as_number(deal.get(key))
        if value is not None:
            source = f"verified {key}" if verified_marker is True else key
            return value, source
    return None, UNKNOWN


def _annual_debt_service(debt: float, rate: float, amortization_years: int) -> float:
    periods = amortization_years * 12
    monthly_rate = rate / 12
    if monthly_rate == 0:
        return debt / amortization_years
    monthly_payment = debt * monthly_rate / (1 - (1 + monthly_rate) ** -periods)
    return monthly_payment * 12


def _loan_balance(
    debt: float, rate: float, amortization_years: int, elapsed_years: int
) -> float:
    total_periods = amortization_years * 12
    elapsed_periods = min(elapsed_years * 12, total_periods)
    if elapsed_periods >= total_periods:
        return 0.0
    monthly_rate = rate / 12
    if monthly_rate == 0:
        return debt * (total_periods - elapsed_periods) / total_periods
    payment = debt * monthly_rate / (1 - (1 + monthly_rate) ** -total_periods)
    return debt * (1 + monthly_rate) ** elapsed_periods - payment * (
        ((1 + monthly_rate) ** elapsed_periods - 1) / monthly_rate
    )


def _irr(cash_flows: list[float]) -> float | None:
    if len(cash_flows) < 2 or not any(value < 0 for value in cash_flows):
        return None
    if not any(value > 0 for value in cash_flows):
        return None

    def npv(rate: float) -> float:
        return sum(value / ((1 + rate) ** period) for period, value in enumerate(cash_flows))

    low, high = -0.9999, 10.0
    low_value, high_value = npv(low), npv(high)
    while low_value * high_value > 0 and high < 1_000_000:
        high *= 10
        high_value = npv(high)
    if low_value * high_value > 0:
        return None
    for _ in range(160):
        midpoint = (low + high) / 2
        midpoint_value = npv(midpoint)
        if abs(midpoint_value) < 1e-8:
            return midpoint
        if low_value * midpoint_value <= 0:
            high = midpoint
        else:
            low = midpoint
            low_value = midpoint_value
    return (low + high) / 2


def _debt_service_and_dscr(
    terms: _StructureTerms, debt: float | None, noi: float | None
) -> tuple[float | None, float | None]:
    if debt is None or debt == 0 or terms.interest_rate is None or terms.amortization_years is None:
        return None, None
    service = _annual_debt_service(debt, terms.interest_rate, terms.amortization_years)
    return service, noi / service if noi is not None and service else None


def _return_metrics(
    *,
    structure: str,
    terms: _StructureTerms,
    cash_needed: float | None,
    debt: float | None,
    noi: float | None,
    exit_cap: float | None,
    hold_years: int | None,
    annual_debt_service: float | None,
) -> tuple[dict[str, Any], dict[str, Any], float | None]:
    expected: dict[str, Any] = {
        "cash_on_cash": UNKNOWN,
        "levered_irr": UNKNOWN,
        "hold_years": hold_years if hold_years is not None else UNKNOWN,
        "units": "decimal",
    }
    downside: dict[str, Any] = {
        "cash_on_cash": UNKNOWN,
        "levered_irr": UNKNOWN,
        "hold_years": hold_years if hold_years is not None else UNKNOWN,
        "stress": {"noi_change": -0.10, "exit_cap_change_bps": 75},
        "units": "decimal",
    }

    if not terms.owns_at_close or structure == "jv_preferred_equity":
        return expected, downside, cash_needed
    if cash_needed is None or cash_needed <= 0 or noi is None:
        return expected, downside, None

    debt_service = annual_debt_service or 0.0
    expected["cash_on_cash"] = _ratio((noi - debt_service) / cash_needed)
    stressed_noi = noi * 0.90
    downside["cash_on_cash"] = _ratio((stressed_noi - debt_service) / cash_needed)

    if hold_years is None or hold_years <= 0 or exit_cap is None:
        return expected, downside, None

    remaining_debt = 0.0
    if debt and terms.interest_rate is not None and terms.amortization_years is not None:
        remaining_debt = _loan_balance(
            debt, terms.interest_rate, terms.amortization_years, hold_years
        )
    base_exit_equity = noi / exit_cap - remaining_debt
    stressed_exit_equity = stressed_noi / (exit_cap + 0.0075) - remaining_debt
    annual_cash_flow = noi - debt_service
    stressed_annual_cash_flow = stressed_noi - debt_service
    expected_flows = [-cash_needed] + [annual_cash_flow] * max(0, hold_years - 1)
    expected_flows.append(annual_cash_flow + base_exit_equity)
    downside_flows = [-cash_needed] + [stressed_annual_cash_flow] * max(0, hold_years - 1)
    downside_flows.append(stressed_annual_cash_flow + stressed_exit_equity)
    expected["levered_irr"] = _ratio(_irr(expected_flows))
    downside["levered_irr"] = _ratio(_irr(downside_flows))
    estimated_loss = max(0.0, -sum(downside_flows))
    return expected, downside, estimated_loss


def _seller_motivation(deal: dict[str, Any]) -> int:
    value = deal.get("seller_motivation", deal.get("seller_motivated"))
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, str):
        normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized in {"high", "strong", "motivated", "very_motivated"}:
            return 1
        if normalized in {"low", "weak", "unmotivated"}:
            return -1
    number = _as_number(value)
    if number is not None:
        if number <= 1:
            return 1 if number >= 0.67 else -1 if number < 0.34 else 0
        return 1 if number >= 7 else -1 if number < 4 else 0
    return 0


def _acceptance_probability(
    structure: str, terms: _StructureTerms, deal: dict[str, Any]
) -> float:
    probability = terms.acceptance_base
    motivation = _seller_motivation(deal)
    creative = {
        "seller_finance",
        "master_lease",
        "option_then_lease",
        "jv_preferred_equity",
    }
    if motivation > 0:
        probability += 0.18 if structure == "seller_finance" else 0.10 if structure in creative else 0.02
    elif motivation < 0 and structure in creative:
        probability -= 0.14
    if deal.get("quick_close") is True:
        probability += 0.05 if structure in {"all_cash", "conventional_75ltv"} else 0.02
    return _probability(probability)


def _financing_probability(
    structure: str,
    dscr: float | None,
    profile: BuyerProfile,
    terms: _StructureTerms,
) -> Metric:
    if structure == "all_cash":
        return 1.0
    if structure in {"master_lease", "option_then_lease"}:
        base = 0.88 if structure == "master_lease" else 0.84
        if profile.recourse_tolerance == "none" and terms.recourse != "none":
            base -= 0.25
        return _probability(base)
    if dscr is None:
        return UNKNOWN
    if dscr >= 1.50:
        probability = 0.90
    elif dscr >= 1.25:
        probability = 0.80
    elif dscr >= 1.10:
        probability = 0.60
    elif dscr >= 1.00:
        probability = 0.40
    else:
        probability = 0.20

    tolerance = profile.recourse_tolerance
    recourse_order = {"none": 0, "partial": 1, "full": 2}
    if tolerance is not None and recourse_order[terms.recourse] > recourse_order[tolerance]:
        probability -= 0.30 if tolerance == "none" else 0.15
    if structure == "seller_finance":
        probability += 0.05
    return _probability(probability)


def _close_probability(
    financing_probability: Metric, profile: BuyerProfile
) -> Metric:
    if financing_probability == UNKNOWN or profile.closing_track_record is None:
        return UNKNOWN
    track = {"none": 0.42, "some": 0.70, "strong": 0.90}[
        profile.closing_track_record
    ]
    return _probability(0.65 * financing_probability + 0.35 * track)


def _distributions_available(
    structure: str,
    deal: dict[str, Any],
    noi: float | None,
    annual_debt_service: float | None,
) -> bool | Unknown:
    explicit = deal.get("current_distributions_available")
    if isinstance(explicit, bool):
        return explicit
    if structure == "option_then_lease":
        return False
    if structure == "master_lease":
        structure_value = deal.get("master_lease_distributions_available")
        return structure_value if isinstance(structure_value, bool) else UNKNOWN
    if noi is None:
        return UNKNOWN
    return noi - (annual_debt_service or 0.0) > 0


def _buyer_fit(
    *,
    structure: str,
    terms: _StructureTerms,
    profile: BuyerProfile,
    deal: dict[str, Any],
    cash_needed: float | None,
    debt: float | None,
    expected_return: dict[str, Any],
    distributions_available: bool | Unknown,
    estimated_downside_loss: float | None,
) -> tuple[bool, str, list[str], dict[str, str]]:
    checks: dict[str, str] = {}
    reasons: list[str] = []

    def record(name: str, status: str, reason: str) -> None:
        checks[name] = status
        reasons.append(reason)

    if cash_needed is None:
        record("cash", UNKNOWN, "Cash need is unknown because price is missing.")
    elif profile.cash_available is None:
        record("cash", UNKNOWN, "Buyer cash available is unknown.")
    elif cash_needed > profile.cash_available:
        record(
            "cash",
            "mismatch",
            f"Cash need ${cash_needed:,.0f} exceeds available cash ${profile.cash_available:,.0f}.",
        )
    elif (
        profile.reserves_required is not None
        and cash_needed + profile.reserves_required > profile.cash_available
    ):
        record(
            "cash",
            "mismatch",
            "Cash need plus required reserves exceeds available cash.",
        )
    else:
        record("cash", "fit", "Cash need fits the stated available cash.")

    if profile.liquidity_after_close is not None and profile.reserves_required is not None:
        if profile.liquidity_after_close < profile.reserves_required:
            record("liquidity", "mismatch", "Post-close liquidity is below required reserves.")
        else:
            record("liquidity", "fit", "Post-close liquidity covers required reserves.")

    if profile.recourse_tolerance is None:
        record("recourse", UNKNOWN, "Buyer recourse tolerance is unknown.")
    else:
        order = {"none": 0, "partial": 1, "full": 2}
        if order[terms.recourse] > order[profile.recourse_tolerance]:
            record(
                "recourse",
                "mismatch",
                f"{terms.recourse.title()} recourse exceeds buyer tolerance of {profile.recourse_tolerance}.",
            )
        else:
            record("recourse", "fit", "Recourse is within the stated tolerance.")

    deal_hold = _deal_number(deal, "target_hold_years", "business_plan_hold_years")
    if profile.hold_pref_years is None or deal_hold is None:
        record("hold", UNKNOWN, "Hold-period match is unknown.")
    elif abs(profile.hold_pref_years - deal_hold) > 2:
        record("hold", "mismatch", "Deal hold plan is more than two years from buyer preference.")
    else:
        record("hold", "fit", "Deal hold plan matches the buyer preference.")

    if profile.needs_current_distributions is True:
        if distributions_available == UNKNOWN:
            record("distributions", UNKNOWN, "Current distributions are unknown.")
        elif not distributions_available:
            record("distributions", "mismatch", "Structure does not provide current distributions.")
        else:
            record("distributions", "fit", "Structure supports current distributions.")

    if profile.return_requirement_irr is not None:
        irr = expected_return["levered_irr"]
        if isinstance(irr, float):
            if irr < profile.return_requirement_irr:
                record("return", "mismatch", "Modeled IRR proxy is below the buyer requirement.")
            else:
                record("return", "fit", "Modeled IRR proxy meets the buyer requirement.")
        else:
            record("return", UNKNOWN, "IRR fit is unknown for this structure or hold period.")

    if profile.max_acceptable_loss is not None:
        if estimated_downside_loss is None:
            record("downside", UNKNOWN, "Estimated downside loss is unknown.")
        elif estimated_downside_loss > profile.max_acceptable_loss:
            record("downside", "mismatch", "Estimated downside loss exceeds buyer tolerance.")
        else:
            record("downside", "fit", "Estimated downside loss is within buyer tolerance.")

    required_capability = {
        "all_cash": "passive",
        "conventional_75ltv": "passive",
        "seller_finance": "passive",
        "master_lease": "light",
        "option_then_lease": "light",
        "jv_preferred_equity": "light",
    }[structure]
    if profile.operating_capability is not None:
        capability_order = {"passive": 0, "light": 1, "heavy": 2}
        if capability_order[profile.operating_capability] < capability_order[required_capability]:
            record("operations", "mismatch", f"Structure requires {required_capability} operating capability.")
        else:
            record("operations", "fit", "Operating capability fits the structure.")

    if structure == "jv_preferred_equity" and profile.can_raise_equity is not None:
        if profile.can_raise_equity:
            record("equity_raise", "fit", "Buyer can raise outside equity.")
        else:
            record("equity_raise", "mismatch", "JV structure requires equity-raising capability.")

    if profile.guaranty_capacity is not None and debt and terms.recourse != "none":
        if profile.guaranty_capacity < debt:
            record("guaranty", "mismatch", "Stated guaranty capacity is below modeled debt.")
        else:
            record("guaranty", "fit", "Stated guaranty capacity covers modeled debt.")

    if deal.get("construction_required") is True and profile.construction_experience is not None:
        if profile.construction_experience:
            record("construction", "fit", "Buyer has construction experience.")
        else:
            record("construction", "mismatch", "Business plan requires construction experience.")

    if deal.get("requires_local_partner") is True and profile.local_partner is not None:
        if profile.local_partner:
            record("local_partner", "fit", "Buyer has a local partner.")
        else:
            record("local_partner", "mismatch", "Deal requires a local partner.")

    if profile.tax_deferral_need is True:
        if structure in {"master_lease", "option_then_lease"}:
            record("tax_deferral", "mismatch", "Control without a current acquisition may not satisfy tax-deferral timing.")
        else:
            record("tax_deferral", "fit", "Structure provides a current acquisition path, subject to tax advice.")

    fit = not any(status == "mismatch" for status in checks.values())
    if all(status == UNKNOWN for status in checks.values()):
        status = UNKNOWN
    elif any(item == UNKNOWN for item in checks.values()):
        status = "partial" if fit else "mismatch"
    else:
        status = "fit" if fit else "mismatch"
    return fit, status, reasons, checks


def _score(
    *,
    acceptance_probability: float,
    financing_probability: Metric,
    close_probability: Metric,
    checks: dict[str, str],
    expected_return: dict[str, Any],
    profile: BuyerProfile,
    estimated_downside_loss: float | None,
    buyer_fit: bool,
) -> tuple[float, list[str]]:
    weighted = acceptance_probability * 0.30
    used_weight = 0.30
    basis = ["seller acceptance heuristic"]

    if isinstance(financing_probability, float):
        weighted += financing_probability * 0.20
        used_weight += 0.20
        basis.append("financing feasibility")
    if isinstance(close_probability, float):
        weighted += close_probability * 0.20
        used_weight += 0.20
        basis.append("buyer closing record")

    known_checks = [value for value in checks.values() if value != UNKNOWN]
    if known_checks:
        constraint_score = sum(value == "fit" for value in known_checks) / len(known_checks)
        weighted += constraint_score * 0.30
        used_weight += 0.30
        basis.append("known buyer constraints")

    irr = expected_return["levered_irr"]
    if isinstance(irr, float) and profile.return_requirement_irr is not None:
        return_fit = _clamp(0.50 + (irr - profile.return_requirement_irr) * 4)
        weighted += return_fit * 0.15
        used_weight += 0.15
        basis.append("IRR requirement")

    if estimated_downside_loss is not None and profile.max_acceptable_loss is not None:
        if profile.max_acceptable_loss == 0:
            downside_fit = 1.0 if estimated_downside_loss == 0 else 0.0
        else:
            downside_fit = _clamp(1 - estimated_downside_loss / profile.max_acceptable_loss)
        weighted += downside_fit * 0.10
        used_weight += 0.10
        basis.append("loss tolerance")

    raw_score = weighted / used_weight
    evidence_coverage = used_weight / 1.25
    raw_score *= 0.75 + 0.25 * evidence_coverage
    if not buyer_fit:
        raw_score *= 0.45
    return round(_clamp(raw_score), 2), basis


def _recommendation(frontier: list[dict[str, Any]], fatal_flaws: Any) -> str:
    if fatal_flaws:
        flaws = ", ".join(str(flaw) for flaw in fatal_flaws)
        return f"{flaws} — fatal flaw(s); do not pursue a structure until resolved."
    best = frontier[0]
    basis = best["price_basis"]
    basis_text = f"${basis:,.0f}" if isinstance(basis, float) else UNKNOWN
    if best["buyer_fit"]:
        why = "best aligns known buyer constraints with execution probability"
    else:
        why = "highest screened alternative, but stated buyer mismatches remain"
    return f"Pursue {best['structure']} at {basis_text}: {why}."


def decision_frontier(
    deal: dict[str, Any],
    buyer: dict[str, Any],
    structures: list[str] | None = None,
) -> dict[str, Any]:
    """Build a buyer-specific, structure-by-structure decision frontier."""

    if not isinstance(deal, dict):
        raise TypeError("deal must be a dict")
    if not isinstance(buyer, dict):
        raise TypeError("buyer must be a dict")
    profile = normalize_buyer(buyer)
    candidates = list(structures) if structures is not None else list(DEFAULT_STRUCTURES)
    unknown_structures = [name for name in candidates if name not in _TERMS]
    if unknown_structures:
        raise ValueError(f"unknown structure(s): {', '.join(unknown_structures)}")
    if not candidates:
        raise ValueError("at least one structure is required")

    price = _positive_deal_number(deal, "price", "price_usd")
    noi, noi_source = _noi_and_source(deal)
    exit_cap = _deal_cap(deal, "market_cap_rate", "cap_rate")
    hold_years = profile.hold_pref_years if profile.hold_pref_years and profile.hold_pref_years > 0 else None
    rows: list[dict[str, Any]] = []
    mismatches: list[str] = []

    for order, structure in enumerate(candidates):
        terms = _TERMS[structure]
        cash_needed = price * terms.cash_fraction if price is not None else None
        debt = price * terms.debt_fraction if price is not None else None
        debt_service, dscr = _debt_service_and_dscr(terms, debt, noi)
        expected, downside, downside_loss = _return_metrics(
            structure=structure,
            terms=terms,
            cash_needed=cash_needed,
            debt=debt,
            noi=noi,
            exit_cap=exit_cap,
            hold_years=hold_years,
            annual_debt_service=debt_service,
        )
        acceptance = _acceptance_probability(structure, terms, deal)
        financing = _financing_probability(structure, dscr, profile, terms)
        close = _close_probability(financing, profile)
        distributions = _distributions_available(structure, deal, noi, debt_service)
        buyer_fit, fit_status, fit_reasons, fit_checks = _buyer_fit(
            structure=structure,
            terms=terms,
            profile=profile,
            deal=deal,
            cash_needed=cash_needed,
            debt=debt,
            expected_return=expected,
            distributions_available=distributions,
            estimated_downside_loss=downside_loss,
        )
        score, score_basis = _score(
            acceptance_probability=acceptance,
            financing_probability=financing,
            close_probability=close,
            checks=fit_checks,
            expected_return=expected,
            profile=profile,
            estimated_downside_loss=downside_loss,
            buyer_fit=buyer_fit,
        )
        for reason, check in zip(fit_reasons, fit_checks.values(), strict=True):
            if check == "mismatch":
                item = f"{structure}: {reason}"
                if item not in mismatches:
                    mismatches.append(item)

        rows.append(
            {
                "structure": structure,
                "price_basis": _money(price),
                "cash_needed": _money(cash_needed),
                "cash_needed_basis": terms.cash_basis,
                "debt": _money(debt),
                "recourse": terms.recourse,
                "noi_used": _money(noi),
                "noi_source": noi_source,
                "dscr": _ratio(dscr),
                "expected_return": expected,
                "downside_return": downside,
                "estimated_downside_loss": _money(downside_loss),
                "acceptance_probability": acceptance,
                "financing_probability": financing,
                "close_probability": close,
                "distributions_available": distributions,
                "buyer_fit": buyer_fit,
                "buyer_fit_status": fit_status,
                "buyer_fit_reasons": fit_reasons,
                "buyer_fit_checks": fit_checks,
                "score": score,
                "score_basis": score_basis,
                "_order": order,
            }
        )

    rows.sort(key=lambda row: (-row["score"], row["_order"]))
    for row in rows:
        del row["_order"]
    fatal_flaws = deal.get("fatal_flaws", [])
    return {
        "frontier": rows,
        "recommendation": _recommendation(rows, fatal_flaws),
        "buyer_mismatches": mismatches,
        "fatal_flaws_passthrough": fatal_flaws,
        "caveats": ["UNCALIBRATED screening aid; verify with your lender/attorney."],
    }


__all__ = ["DEFAULT_STRUCTURES", "decision_frontier"]
