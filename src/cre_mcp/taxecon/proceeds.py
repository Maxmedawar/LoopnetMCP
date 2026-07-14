"""Range-based seller net-sale-proceeds waterfall."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

from cre_mcp.taxecon.reassessment import LAST_VERIFIED, UNKNOWN, VERIFY_MESSAGE

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True, slots=True)
class StateTransferTaxRule:
    """State-level seller transfer-tax screen with explicit local gaps."""

    state: str
    rate: float | None
    rate_low: float | None
    rate_high: float | None
    calculation_method: str
    local_variation: str
    source_citation: str
    confidence: Confidence
    last_verified: str = LAST_VERIFIED

    @property
    def source_note(self) -> str:
        """Compatibility alias emphasizing that the citation is a screening note."""

        return self.source_citation

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["source_note"] = self.source_citation
        return result


TRANSFER_TAX_REGISTRY: dict[str, StateTransferTaxRule] = {
    "CA": StateTransferTaxRule(
        state="CA",
        rate=0.0011,
        rate_low=0.0011,
        rate_high=0.0011,
        calculation_method="$0.55 per $500 or fraction; modeled on gross price without debt allocation",
        local_variation=(
            "Cities may impose additional documentary/real-property transfer taxes, sometimes at "
            "materially higher graduated rates. No city add-on is guessed without a locality."
        ),
        source_citation=(
            "Cal. Rev. & Tax. Code §11911; California BOE Documentary Transfer Tax annotation: "
            "https://boe.ca.gov/proptaxes/pdf/200_0125.pdf"
        ),
        confidence="high",
    ),
    "TX": StateTransferTaxRule(
        state="TX",
        rate=0.0,
        rate_low=0.0,
        rate_high=0.0,
        calculation_method="no state or local fee-simple real-estate transfer tax modeled",
        local_variation="Recording, title, escrow, and other closing charges are not transfer tax and remain separate.",
        source_citation=(
            "Texas Constitution art. VIII §29 (transfer tax on fee-simple conveyance prohibited): "
            "https://comptroller.texas.gov/taxes/property-tax/docs/96-298-21.pdf"
        ),
        confidence="high",
    ),
    "FL": StateTransferTaxRule(
        state="FL",
        rate=0.0070,
        rate_low=0.0060,
        rate_high=0.0105,
        calculation_method=(
            "$0.70 per $100 generally; range includes Miami-Dade $0.60 rate and the $0.45 "
            "commercial surtax where applicable"
        ),
        local_variation=(
            "Miami-Dade applies a different base rate and surtax; all parties are statutorily liable "
            "even though the contract allocates payment. Documentary tax on debt is outside this deed line."
        ),
        source_citation=(
            "Fla. Stat. §§201.02, 201.031; Florida DOR Documentary Stamp Tax: "
            "https://floridarevenue.com/taxes/taxesfees/Pages/doc_stamp.aspx"
        ),
        confidence="high",
    ),
    "AZ": StateTransferTaxRule(
        state="AZ",
        rate=0.0,
        rate_low=0.0,
        rate_high=0.0,
        calculation_method="no ad-valorem real-estate transfer tax modeled",
        local_variation=(
            "Affidavit-of-property-value and recording fees can apply but are not a percentage transfer tax."
        ),
        source_citation=(
            "Arizona Constitution art. IX §24; A.R.S. §§11-1132 to 11-1137; Arizona DOR Property "
            "Tax FAQs: https://azdor.gov/business/property-tax/property-tax-faqs"
        ),
        confidence="medium",
    ),
    "NV": StateTransferTaxRule(
        state="NV",
        rate=0.0039,
        rate_low=0.0039,
        rate_high=0.0051,
        calculation_method=(
            "$1.95 per $500 or fraction statewide; upper case is Clark County's additional $0.60 per $500"
        ),
        local_variation="Washoe and Churchill add $0.10 per $500; Clark adds $0.60 per $500.",
        source_citation=(
            "Nev. Rev. Stat. §§375.023-.026; Nevada DOR Real Property Transfer Tax FAQ: "
            "https://tax.nv.gov/faqs/real-property-transfer-tax-faqs/"
        ),
        confidence="high",
    ),
    "CO": StateTransferTaxRule(
        state="CO",
        rate=0.0001,
        rate_low=0.0001,
        rate_high=0.0001,
        calculation_method="$0.01 per $100 documentary fee, before exemptions",
        local_variation=(
            "Some home-rule municipalities impose separate transfer taxes; none is guessed without the municipality."
        ),
        source_citation="Colo. Rev. Stat. §39-13-102 (documentary fee); verify local home-rule ordinances.",
        confidence="medium",
    ),
    "GA": StateTransferTaxRule(
        state="GA",
        rate=0.0010,
        rate_low=0.0010,
        rate_high=0.0010,
        calculation_method="$1 on first $1,000 plus $0.10 per additional $100 or fraction (rate approximation)",
        local_variation="Consideration, assumed debt, exemptions, and recording practice require the closing statement.",
        source_citation="O.C.G.A. §§48-6-1, 48-6-4; Georgia DOR Real Estate Transfer Tax rules.",
        confidence="medium",
    ),
    "NC": StateTransferTaxRule(
        state="NC",
        rate=0.0020,
        rate_low=0.0020,
        rate_high=0.0020,
        calculation_method="$1 per $500 or fraction excise tax",
        local_variation="Certain counties may have separate land-transfer taxes; none is guessed without county.",
        source_citation="N.C. Gen. Stat. §105-228.30 et seq. (excise tax on conveyances).",
        confidence="high",
    ),
    "TN": StateTransferTaxRule(
        state="TN",
        rate=0.0037,
        rate_low=0.0037,
        rate_high=0.0037,
        calculation_method="$0.37 per $100 or fraction realty transfer tax",
        local_variation="Tax base, exemptions, and recordation fees require register-of-deeds confirmation.",
        source_citation="Tenn. Code Ann. §67-4-409(a) (realty transfer tax).",
        confidence="high",
    ),
    "OH": StateTransferTaxRule(
        state="OH",
        rate=0.0010,
        rate_low=0.0010,
        rate_high=0.0040,
        calculation_method=(
            "statewide conveyance fee plus range for a county permissive transfer tax of up to $3 per $1,000"
        ),
        local_variation="County permissive tax must be verified; exemptions and statement-of-value rules apply.",
        source_citation="Ohio Rev. Code §§319.54(G)(3), 322.02 (conveyance fee and county tax).",
        confidence="medium",
    ),
    "IL": StateTransferTaxRule(
        state="IL",
        rate=0.0015,
        rate_low=0.0015,
        rate_high=0.0120,
        calculation_method=(
            "state $0.50 and county $0.25 per $500 base; upper screen includes Chicago-level local taxes"
        ),
        local_variation=(
            "Chicago and other municipalities can impose substantial additional taxes with buyer/seller allocation."
        ),
        source_citation=(
            "35 ILCS 200/31-10, 31-45; Illinois DOR PTAX-203 instructions; verify Cook County/Chicago ordinances."
        ),
        confidence="low",
    ),
    "NY": StateTransferTaxRule(
        state="NY",
        rate=0.0040,
        rate_low=0.0040,
        rate_high=0.03275,
        calculation_method=(
            "state rate is price-dependent; upper screen adds the NYC commercial RPTT without assuming locality"
        ),
        local_variation=(
            "New York City imposes a separate Real Property Transfer Tax. State and city commercial "
            "thresholds, entity transfers, consideration, and exemptions require tax counsel."
        ),
        source_citation=(
            "N.Y. Tax Law §1402; N.Y.C. Admin. Code §11-2102; NYS DTF Form TP-584 instructions."
        ),
        confidence="low",
    ),
    "WA": StateTransferTaxRule(
        state="WA",
        rate=None,
        rate_low=None,
        rate_high=None,
        calculation_method="graduated state REET by marginal sale-price bracket plus 0.25%-0.50% local REET screen",
        local_variation=(
            "Local rate depends on the location code; classified agricultural/timber land can use a different flat rate."
        ),
        source_citation=(
            "Wash. Rev. Code ch. 82.45; Washington DOR Real Estate Excise Tax: "
            "https://dor.wa.gov/taxes-rates/other-taxes/real-estate-excise-tax"
        ),
        confidence="high",
    ),
    "VA": StateTransferTaxRule(
        state="VA",
        rate=0.0010,
        rate_low=0.0010,
        rate_high=0.0025,
        calculation_method="state grantor tax with upper screen for the Northern Virginia regional grantor tax",
        local_variation=(
            "Northern Virginia regional taxes and local recordation charges vary; buyer recordation tax is not included."
        ),
        source_citation="Va. Code §§58.1-802, 58.1-802.3 (grantor and regional grantor taxes).",
        confidence="medium",
    ),
}

TRANSFER_TAX_RULES = TRANSFER_TAX_REGISTRY


def _number(value: Any, label: str, *, default: float | None = None) -> float:
    if value is None and default is not None:
        return default
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative number")
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative number") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a non-negative number")
    return number


def _pct(value: Any, label: str) -> float:
    number = _number(value, label)
    return number / 100 if number > 1 else number


def _range(low: float, base: float, high: float) -> dict[str, float]:
    ordered = sorted((low, base, high))
    return {"low": round(ordered[0], 2), "base": round(base, 2), "high": round(ordered[2], 2)}


def _unknown_range(reason: str) -> dict[str, str]:
    return {"low": UNKNOWN, "base": UNKNOWN, "high": UNKNOWN, "reason": reason}


def _amount_range(value: Any, label: str) -> dict[str, float]:
    if isinstance(value, dict):
        base = _number(value.get("base"), f"{label}.base")
        low = _number(value.get("low", base), f"{label}.low")
        high = _number(value.get("high", base), f"{label}.high")
        if not low <= base <= high:
            raise ValueError(f"{label} range must satisfy low <= base <= high")
        return _range(low, base, high)
    amount = _number(value, label, default=0.0)
    return _range(amount, amount, amount)


def _ceil_units(price: float, unit: float, tax_per_unit: float) -> float:
    return math.ceil(price / unit) * tax_per_unit if price > 0 else 0.0


def _wa_state_reet(price: float) -> float:
    """Apply Washington's published graduated state brackets marginally."""

    brackets = (
        (525_000.0, 0.0110),
        (1_525_000.0, 0.0128),
        (3_025_000.0, 0.0275),
        (math.inf, 0.0300),
    )
    prior = 0.0
    total = 0.0
    for ceiling, rate in brackets:
        taxable = min(price, ceiling) - prior
        if taxable > 0:
            total += taxable * rate
        if price <= ceiling:
            break
        prior = ceiling
    return total


def transfer_tax_estimate(price: float, state: str) -> dict[str, Any]:
    """Return a sourced state transfer-tax range or an explicit unknown."""

    normalized_state = str(state or "").strip().upper()
    rule = TRANSFER_TAX_REGISTRY.get(normalized_state)
    if rule is None:
        reason = (
            f"No sourced transfer-tax rule is registered for {normalized_state or 'the supplied state'}. "
            "No zero or neighboring-state rate was assumed."
        )
        return {
            "status": UNKNOWN,
            "state": normalized_state or UNKNOWN,
            "amount": _unknown_range(reason),
            "rule": {
                "state": normalized_state or UNKNOWN,
                "rate": UNKNOWN,
                "source_citation": "No registry entry.",
                "confidence": "low",
                "last_verified": LAST_VERIFIED,
            },
            "caveats": [reason, VERIFY_MESSAGE],
            "professional_review_required": True,
            "professional_review_flag": True,
            "verify_with_county_assessor_or_tax_counsel_before_reliance": True,
            "verification_message": VERIFY_MESSAGE,
        }

    if normalized_state == "CA":
        base = _ceil_units(price, 500.0, 0.55)
        amounts = _range(base, base, base)
    elif normalized_state == "FL":
        amounts = _range(
            _ceil_units(price, 100.0, 0.60),
            _ceil_units(price, 100.0, 0.70),
            _ceil_units(price, 100.0, 1.05),
        )
    elif normalized_state == "NV":
        amounts = _range(
            _ceil_units(price, 500.0, 1.95),
            _ceil_units(price, 500.0, 1.95),
            _ceil_units(price, 500.0, 2.55),
        )
    elif normalized_state == "NY":
        state_rate = 0.0065 if price >= 2_000_000 else 0.0040
        city_rate = 0.02625 if price > 500_000 else 0.01425
        state_tax = price * state_rate
        amounts = _range(state_tax, state_tax, price * (state_rate + city_rate))
    elif normalized_state == "WA":
        state_tax = _wa_state_reet(price)
        amounts = _range(state_tax + price * 0.0025, state_tax + price * 0.0050, state_tax + price * 0.0050)
    else:
        assert rule.rate is not None and rule.rate_low is not None and rule.rate_high is not None
        amounts = _range(price * rule.rate_low, price * rule.rate, price * rule.rate_high)

    excluded = []
    if normalized_state in {"CA", "CO", "NC"}:
        excluded.append("Unspecified city/county transfer tax is excluded and remains an unquantified closing-cost risk.")
    return {
        "status": "ESTIMATE",
        "state": normalized_state,
        "amount": amounts,
        "rule": rule.to_dict(),
        "excluded_unknown_costs": excluded,
        "caveats": [rule.local_variation, VERIFY_MESSAGE],
        "professional_review_required": True,
        "professional_review_flag": True,
        "verify_with_county_assessor_or_tax_counsel_before_reliance": True,
        "verification_message": VERIFY_MESSAGE,
    }


def _param_number(params: dict[str, Any], keys: tuple[str, ...]) -> tuple[float | None, str | None]:
    for key in keys:
        if key in params and params[key] is not None:
            return _number(params[key], key), key
    return None, None


def estimate_prepay_penalty(loan_balance: float, prepay: dict[str, Any] | None) -> dict[str, Any]:
    """Estimate a prepayment penalty without treating an estimate as a payoff quote."""

    selected = prepay or {"type": "none", "params": {}}
    kind = str(selected.get("type", "none")).strip().casefold()
    params_raw = selected.get("params", {})
    if not isinstance(params_raw, dict):
        raise ValueError("prepay.params must be a dictionary")
    params = params_raw
    common = {
        "type": kind,
        "lender_payoff_quote_required": kind != "none",
        "caveats": [
            "This is a screening estimate, not a lender payoff statement; legal documents control.",
            VERIFY_MESSAGE,
        ],
        "professional_review_required": True,
        "professional_review_flag": True,
        "verify_with_county_assessor_or_tax_counsel_before_reliance": True,
        "verification_message": VERIFY_MESSAGE,
    }

    if kind == "none":
        return {
            **common,
            "status": "ESTIMATE",
            "amount": _range(0.0, 0.0, 0.0),
            "method": "No contractual prepayment penalty supplied.",
            "missing_inputs": [],
        }

    if kind == "stepdown":
        raw_pct, pct_key = _param_number(
            params,
            ("penalty_pct", "stepdown_pct", "current_step_pct", "current_pct", "pct"),
        )
        if raw_pct is None:
            reason = "Current contractual stepdown percentage is required."
            return {
                **common,
                "status": "NOT_COMPUTABLE",
                "amount": _unknown_range(reason),
                "method": "not computed",
                "missing_inputs": ["penalty_pct"],
            }
        rate = raw_pct / 100 if raw_pct > 1 else raw_pct
        amount = loan_balance * rate
        return {
            **common,
            "status": "ESTIMATE",
            "amount": _range(amount, amount, amount),
            "method": f"loan balance × {pct_key} ({rate:.4%})",
            "rate": rate,
            "missing_inputs": [],
        }

    if kind == "yield_maintenance":
        note_raw, note_key = _param_number(
            params,
            ("note_rate", "note_rate_pct", "contract_rate", "coupon_rate", "loan_rate", "interest_rate"),
        )
        reinvest_raw, reinvest_key = _param_number(
            params,
            ("reinvestment_rate", "treasury_rate", "treasury_rate_pct", "replacement_rate", "market_rate"),
        )
        years, years_key = _param_number(
            params,
            ("remaining_years", "remaining_term_years", "term_remaining_years"),
        )
        if years is None:
            months, months_key = _param_number(params, ("remaining_months", "term_remaining_months"))
            if months is not None:
                years, years_key = months / 12, months_key
        missing = []
        if note_raw is None:
            missing.append("note_rate")
        if reinvest_raw is None:
            missing.append("reinvestment_rate/treasury_rate")
        if years is None:
            missing.append("remaining_years or remaining_months")
        if missing:
            reason = "Yield-maintenance rate and remaining-term inputs are required; no penalty was guessed."
            return {
                **common,
                "status": "NOT_COMPUTABLE",
                "amount": _unknown_range(reason),
                "method": "not computed",
                "missing_inputs": missing,
            }
        assert note_raw is not None and reinvest_raw is not None and years is not None
        note_rate = note_raw / 100 if note_raw > 1 else note_raw
        reinvest_rate = reinvest_raw / 100 if reinvest_raw > 1 else reinvest_raw
        low = loan_balance * max(note_rate - (reinvest_rate + 0.0025), 0.0) * years
        base = loan_balance * max(note_rate - reinvest_rate, 0.0) * years
        high = loan_balance * max(note_rate - max(reinvest_rate - 0.0025, 0.0), 0.0) * years
        return {
            **common,
            "status": "ESTIMATE",
            "amount": _range(low, base, high),
            "method": (
                "Simplified interest-only rate-differential screen: balance × max(note rate − "
                "reinvestment rate, 0) × remaining years; low/high shift reinvestment rate ±25 bps. "
                "It does not reproduce the note's PV formula, amortization, minimum penalty, or treasury date."
            ),
            "inputs_used": {
                note_key or "note_rate": note_rate,
                reinvest_key or "reinvestment_rate": reinvest_rate,
                years_key or "remaining_years": years,
            },
            "missing_inputs": [],
        }

    if kind == "defeasance":
        if isinstance(params.get("cost_range"), dict):
            amounts = _amount_range(params["cost_range"], "prepay.params.cost_range")
            method = "Caller-supplied defeasance cost range; obtain a live securities-basket/servicer quote."
        else:
            estimate, estimate_key = _param_number(
                params,
                (
                    "estimated_cost",
                    "estimated_penalty",
                    "defeasance_cost",
                    "securities_cost_plus_fees",
                    "quote",
                ),
            )
            if estimate is None:
                pct_raw, pct_key = _param_number(params, ("penalty_pct", "estimated_pct"))
                if pct_raw is None:
                    reason = (
                        "Defeasance requires a current securities-basket/servicer cost estimate or "
                        "caller-supplied percentage; no cost was guessed."
                    )
                    return {
                        **common,
                        "status": "NOT_COMPUTABLE",
                        "amount": _unknown_range(reason),
                        "method": "not computed",
                        "missing_inputs": ["estimated_cost, cost_range, or penalty_pct"],
                    }
                rate = pct_raw / 100 if pct_raw > 1 else pct_raw
                estimate = loan_balance * rate
                estimate_key = pct_key
            amounts = _range(estimate * 0.90, estimate, estimate * 1.10)
            method = (
                f"{estimate_key} supplied by caller, screened at ±10%; actual securities prices, "
                "yield curve, legal/servicer fees, and timing require a live quote."
            )
        return {
            **common,
            "status": "ESTIMATE",
            "amount": amounts,
            "method": method,
            "missing_inputs": [],
        }

    reason = f"Unsupported prepayment type {kind!r}; supported types are yield_maintenance, defeasance, stepdown, none."
    return {
        **common,
        "status": UNKNOWN,
        "amount": _unknown_range(reason),
        "method": "not computed",
        "missing_inputs": ["supported prepay.type"],
    }


def _line(name: str, direction: str, amount: dict[str, Any], status: str = "ESTIMATE") -> dict[str, Any]:
    return {"line_item": name, "direction": direction, "amount": amount, "status": status}


def _is_numeric_range(value: dict[str, Any]) -> bool:
    return all(isinstance(value.get(key), (int, float)) for key in ("low", "base", "high"))


def _net_range(lines: list[dict[str, Any]]) -> dict[str, Any]:
    unknown_lines = [line["line_item"] for line in lines if not _is_numeric_range(line["amount"])]
    if unknown_lines:
        return _unknown_range(
            "Net proceeds cannot be computed while these line items are unknown: " + ", ".join(unknown_lines)
        )
    net_low = 0.0
    net_base = 0.0
    net_high = 0.0
    for line in lines:
        amount = line["amount"]
        if line["direction"] == "credit":
            net_low += amount["low"]
            net_base += amount["base"]
            net_high += amount["high"]
        else:
            net_low -= amount["high"]
            net_base -= amount["base"]
            net_high -= amount["low"]
    return _range(net_low, net_base, net_high)


def net_sale_proceeds(
    price: float,
    loan_balance: float,
    prepay: dict[str, Any] | None,
    commission_pct: float,
    state: str,
    other_costs: float | dict[str, Any] = 0.0,
    credits: float | dict[str, Any] = 0.0,
    reserves_released: float | dict[str, Any] = 0.0,
    *,
    tax_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the seller waterfall and a low/base/high net-proceeds range."""

    sale_price = _number(price, "price")
    balance = _number(loan_balance, "loan_balance")
    commission_rate = _pct(commission_pct, "commission_pct")
    if commission_rate > 1:
        raise ValueError("commission_pct cannot exceed 100%")
    normalized_state = str(state or "").strip().upper()

    commission = _range(
        sale_price * commission_rate,
        sale_price * commission_rate,
        sale_price * commission_rate,
    )
    transfer = transfer_tax_estimate(sale_price, normalized_state)
    penalty = estimate_prepay_penalty(balance, prepay)
    costs = _amount_range(other_costs, "other_costs")
    credit_amounts = _amount_range(credits, "credits")
    released = _amount_range(reserves_released, "reserves_released")

    lines = [
        _line("gross_sale_price", "credit", _range(sale_price, sale_price, sale_price)),
        _line("broker_commission", "debit", commission),
        _line("transfer_tax", "debit", transfer["amount"], transfer["status"]),
        _line("loan_payoff", "debit", _range(balance, balance, balance)),
        _line("prepayment_penalty", "debit", penalty["amount"], penalty["status"]),
        _line("other_seller_costs", "debit", costs),
        _line("credits_to_seller", "credit", credit_amounts),
        _line("reserves_released", "credit", released),
    ]
    net = _net_range(lines)
    status = "ESTIMATE" if _is_numeric_range(net) else UNKNOWN
    after_tax_hook = None
    if tax_profile is not None:
        after_tax_hook = {
            "status": "DELEGATED_NOT_CALCULATED",
            "module": "cre_mcp.ops.after_tax_returns",
            "message": (
                "After-tax proceeds are intentionally not reimplemented here. Pass the seller tax "
                "profile and this pre-tax waterfall to cre_mcp.ops.after_tax_returns."
            ),
            "tax_profile_received": True,
        }

    return {
        "status": status,
        "state": normalized_state,
        "waterfall": lines,
        "line_items": lines,
        "transfer_tax": transfer,
        "prepayment_penalty": penalty,
        "net_proceeds": net,
        "net_proceeds_range_semantics": (
            "Low net subtracts high costs and adds low credits; high net subtracts low costs and adds high credits."
        ),
        "after_tax_hook": after_tax_hook,
        "assumption_sheet": [
            {"driver": "price", "value": sale_price, "source": "provided"},
            {"driver": "loan_balance", "value": balance, "source": "provided"},
            {"driver": "commission_pct", "value": commission_rate, "source": "provided"},
            {"driver": "state", "value": normalized_state, "source": "provided"},
            {"driver": "prepay", "value": prepay, "source": "provided" if prepay is not None else "default_none"},
            {"driver": "other_costs", "value": other_costs, "source": "provided"},
            {"driver": "credits", "value": credits, "source": "provided"},
            {"driver": "reserves_released", "value": reserves_released, "source": "provided"},
        ],
        "caveats": [
            "This is a pre-tax seller closing screen, not a settlement statement or lender payoff quote.",
            "Title, escrow, recording, legal, repair/proration, and local transfer costs belong in other_costs unless explicitly modeled.",
            VERIFY_MESSAGE,
        ],
        "professional_review_required": True,
        "professional_review_flag": True,
        "verify_with_county_assessor_or_tax_counsel_before_reliance": True,
        "verification_message": VERIFY_MESSAGE,
    }


__all__ = [
    "TRANSFER_TAX_REGISTRY",
    "TRANSFER_TAX_RULES",
    "StateTransferTaxRule",
    "estimate_prepay_penalty",
    "net_sale_proceeds",
    "transfer_tax_estimate",
]
