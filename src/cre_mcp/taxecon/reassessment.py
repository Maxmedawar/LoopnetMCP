"""State-aware, range-based property-tax reassessment screening.

The registry is deliberately small.  An unlisted state is never inferred from a
neighboring jurisdiction and produces an explicit ``UNKNOWN`` result instead.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

ReassessmentMode = Literal[
    "full_reset_to_price",
    "periodic_reappraisal_no_sale_trigger",
    "cap_reset_on_sale",
    "unknown",
]
Confidence = Literal["high", "medium", "low"]

LAST_VERIFIED = "2026-07"
UNKNOWN = "UNKNOWN"
VERIFY_MESSAGE = "Verify with the county assessor / tax counsel before reliance."


@dataclass(frozen=True, slots=True)
class StateReassessmentRule:
    """A sourced state-level screening rule, not a parcel-level tax opinion."""

    state: str
    reassessment_on_sale: ReassessmentMode
    annual_increase_cap_pct: float | None
    annual_increase_cap_scope: str
    local_variation: str
    source_citation: str
    confidence: Confidence
    last_verified: str = LAST_VERIFIED
    indicative_effective_tax_rate_range: tuple[float, float, float] | None = None

    @property
    def source_note(self) -> str:
        """Compatibility alias emphasizing that the citation is a screening note."""

        return self.source_citation

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        # The plural alias makes the output read naturally while keeping a
        # convenient scalar field for callers that consume the dataclass.
        result["annual_increase_caps"] = {
            "pct": self.annual_increase_cap_pct,
            "scope": self.annual_increase_cap_scope,
        }
        result["source_note"] = self.source_citation
        return result


STATE_RULES_REGISTRY: dict[str, StateReassessmentRule] = {
    "CA": StateReassessmentRule(
        state="CA",
        reassessment_on_sale="full_reset_to_price",
        annual_increase_cap_pct=2.0,
        annual_increase_cap_scope=(
            "Prop 13 factored base-year value; the enrolled value is generally the lower of "
            "that value or current market value. Decline-in-value recoveries can rise faster."
        ),
        local_variation=(
            "County assessors decide whether a legal-entity or deed transfer is a change in "
            "ownership. The 1% general levy is supplemented by voter-approved debt and local charges."
        ),
        source_citation=(
            "California Constitution art. XIII A; California BOE, Change in Ownership FAQ and "
            "Revenue & Taxation Code §§50, 51, 110, 110.1: "
            "https://www.boe.ca.gov/proptaxes/faqs/changeinownership.htm"
        ),
        confidence="high",
        indicative_effective_tax_rate_range=(0.0100, 0.0110, 0.0125),
    ),
    "TX": StateReassessmentRule(
        state="TX",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=None,
        annual_increase_cap_scope=(
            "No general permanent commercial cap. A temporary circuit-breaker limitation applies "
            "to qualifying non-homestead real property below the statutory value ceiling through "
            "2026; verify eligibility and expiration rather than treating it as a durable cap."
        ),
        local_variation=(
            "Each county appraisal district (CAD) appraises market value as of January 1 and must "
            "reappraise at least every three years. A sale is market evidence, not an automatic "
            "purchase-price reset; taxing-unit rates vary materially."
        ),
        source_citation=(
            "Texas Tax Code §§23.01, 23.231, 25.18; Texas Comptroller, Valuing Property: "
            "https://comptroller.texas.gov/taxes/property-tax/valuing-property.php"
        ),
        confidence="high",
    ),
    "FL": StateReassessmentRule(
        state="FL",
        reassessment_on_sale="cap_reset_on_sale",
        annual_increase_cap_pct=10.0,
        annual_increase_cap_scope=(
            "Non-homestead assessment limitation for non-school levies; school assessments are "
            "not protected by the 10% cap. The limitation is removed after a qualifying ownership change."
        ),
        local_variation=(
            "The county property appraiser determines just value and whether a transfer resets the "
            "cap; exemptions, school millage, special districts, and entity-control transfers matter."
        ),
        source_citation=(
            "Florida Constitution art. VII §4(g)-(h); Fla. Stat. §§193.1554-.1555; Florida DOR "
            "Non-Homestead Assessment Limitation guidance: "
            "https://floridarevenue.com/property/Documents/2024NALnonhomesteadedits.pdf"
        ),
        confidence="high",
    ),
    "AZ": StateReassessmentRule(
        state="AZ",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=5.0,
        annual_increase_cap_scope=(
            "Limited Property Value generally cannot grow more than 5% annually, subject to "
            "statutory Rule B calculations and exclusions; Full Cash Value is a separate measure."
        ),
        local_variation=(
            "County assessors set Full Cash Value and Limited Property Value; classification ratios "
            "and overlapping tax jurisdictions make a simple purchase-price tax estimate unsafe."
        ),
        source_citation=(
            "Arizona Constitution art. IX §18; A.R.S. §§42-11001, 42-13301; Arizona DOR Property "
            "Tax FAQs: https://azdor.gov/business/property-tax/property-tax-faqs"
        ),
        confidence="medium",
    ),
    "NV": StateReassessmentRule(
        state="NV",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=8.0,
        annual_increase_cap_scope=(
            "Property-tax abatement generally limits annual tax increases on commercial and other "
            "non-qualifying property to 8%; it is a tax-bill abatement, not a market-value cap."
        ),
        local_variation=(
            "County assessors reappraise land and improvements under Nevada taxable-value rules; "
            "the 35% assessment ratio, depreciation, and abatement calculation require the parcel record."
        ),
        source_citation=(
            "Nevada Revised Statutes §§361.227, 361.4722-.4724; Nevada Department of Taxation, "
            "Property Tax Publications: https://tax.nv.gov/local-government/property-tax/"
        ),
        confidence="medium",
    ),
    "CO": StateReassessmentRule(
        state="CO",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=None,
        annual_increase_cap_scope=(
            "No single statewide commercial parcel assessment-growth cap is modeled; temporary "
            "legislative value adjustments and assessment rates can change by tax year."
        ),
        local_variation=(
            "County assessors revalue real property on the statutory cycle using the applicable "
            "base period; local mill levies and special districts drive the bill."
        ),
        source_citation=(
            "Colorado Constitution art. X §3; C.R.S. §§39-1-103, 39-1-104; Colorado Division of "
            "Property Taxation: https://cdola.colorado.gov/property-taxation"
        ),
        confidence="medium",
    ),
    "GA": StateReassessmentRule(
        state="GA",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=None,
        annual_increase_cap_scope="No statewide commercial annual assessment-growth cap is modeled.",
        local_variation=(
            "County boards review fair market value annually; most property is assessed at 40% of "
            "fair market value and local millage varies. A sale is evidence, not a mechanical reset rule."
        ),
        source_citation=(
            "O.C.G.A. §§48-5-2, 48-5-6, 48-5-7; Georgia DOR Property Tax FAQ: "
            "https://dor.georgia.gov/property-tax-real-and-personal-property-faq"
        ),
        confidence="medium",
    ),
    "NC": StateReassessmentRule(
        state="NC",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=None,
        annual_increase_cap_scope="No statewide commercial annual assessment-growth cap is modeled.",
        local_variation=(
            "Counties must reappraise at least every eight years and may use shorter cycles; between "
            "cycles, statutory limits govern parcel changes. County, municipal, and district rates vary."
        ),
        source_citation=(
            "N.C. Gen. Stat. §§105-286, 105-287; NCDOR, Types of Property to be Taxed: "
            "https://www.ncdor.gov/taxes-forms/property-tax/types-property-be-taxed"
        ),
        confidence="high",
    ),
    "TN": StateReassessmentRule(
        state="TN",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=None,
        annual_increase_cap_scope="No statewide commercial annual assessment-growth cap is modeled.",
        local_variation=(
            "Every county follows a four-, five-, or six-year reappraisal cycle; commercial and "
            "industrial real property has a statutory classification ratio and local tax rate."
        ),
        source_citation=(
            "Tenn. Code Ann. §§67-5-601, 67-5-1601; Tennessee Comptroller, Understanding Property "
            "Assessments: https://comptroller.tn.gov/office-functions/pa/property-taxes/understanding-tennessee-property-assessments.html"
        ),
        confidence="high",
    ),
    "OH": StateReassessmentRule(
        state="OH",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=None,
        annual_increase_cap_scope="No statewide commercial annual assessment-growth cap is modeled.",
        local_variation=(
            "County auditors perform sexennial reappraisals with triennial updates. A recent arm's-"
            "length sale can be strong value evidence, but is not encoded as an automatic sale reset."
        ),
        source_citation=(
            "Ohio Rev. Code §§5713.01, 5715.33; Ohio Department of Taxation, Real Property Tax: "
            "https://tax.ohio.gov/help-center/faqs/real-property-tax-general/real-property-tax--general"
        ),
        confidence="medium",
    ),
    "IL": StateReassessmentRule(
        state="IL",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=None,
        annual_increase_cap_scope=(
            "No statewide commercial annual assessment-growth cap is modeled; equalization and "
            "local assessment practices can materially change effective assessed value."
        ),
        local_variation=(
            "Cook County uses a distinct classification and level-of-assessment system and a "
            "triennial cycle; other counties generally use the statewide one-third framework."
        ),
        source_citation=(
            "35 ILCS 200/9-145, 9-205; Illinois Department of Revenue FY 2026 Property Tax Study "
            "(Cook County classification chart): "
            "https://tax.illinois.gov/research/publications/localgovernment/ptax-1500.html"
        ),
        confidence="low",
    ),
    "NY": StateReassessmentRule(
        state="NY",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=None,
        annual_increase_cap_scope=(
            "No single statewide commercial annual cap is modeled. New York City/Nassau Class 4 "
            "transition assessments can phase certain increases over five years."
        ),
        local_variation=(
            "Assessment frequency and level are local. New York City has a four-class system; Class "
            "4 commercial assessment, transition values, and tax rates cannot be inferred from sale price."
        ),
        source_citation=(
            "N.Y. Real Property Tax Law §§305, 1802, 1805; NYS DTF Reassessment Resources: "
            "https://www.tax.ny.gov/research/property/assess/reassess.htm"
        ),
        confidence="low",
    ),
    "WA": StateReassessmentRule(
        state="WA",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=None,
        annual_increase_cap_scope=(
            "The constitutional/statutory levy limits constrain taxing-district levies, not an "
            "individual commercial parcel's market-value increase."
        ),
        local_variation=(
            "County assessors value property at true and fair value on regular revaluation cycles; "
            "local levies and levy limits do not translate to a parcel-level cap."
        ),
        source_citation=(
            "Wash. Rev. Code §§84.40.020, 84.41.030; Washington DOR Property Tax: "
            "https://dor.wa.gov/taxes-rates/property-tax"
        ),
        confidence="medium",
    ),
    "VA": StateReassessmentRule(
        state="VA",
        reassessment_on_sale="periodic_reappraisal_no_sale_trigger",
        annual_increase_cap_pct=None,
        annual_increase_cap_scope="No statewide commercial annual assessment-growth cap is modeled.",
        local_variation=(
            "Cities and counties assess and tax real estate; reassessment timing and rates are local, "
            "often annual or biennial in larger jurisdictions."
        ),
        source_citation=(
            "Va. Code §§58.1-3201, 58.1-3252, 58.1-3330; Virginia Tax legislative summary 24-65: "
            "https://www.tax.virginia.gov/laws-rules-decisions/legislative-summaries/24-65"
        ),
        confidence="medium",
    ),
}

# Short alias for callers that prefer the conventional registry name.
STATE_RULES = STATE_RULES_REGISTRY


def _number(value: Any, label: str, *, required: bool = False) -> float | None:
    if value is None and not required:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative number")
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative number") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a non-negative number")
    return number


def _money_range(low: float, base: float, high: float) -> dict[str, float]:
    return {"low": round(low, 2), "base": round(base, 2), "high": round(high, 2)}


def _unknown_range(reason: str) -> dict[str, str]:
    return {"low": UNKNOWN, "base": UNKNOWN, "high": UNKNOWN, "reason": reason}


def _assumptions(
    purchase_price: float | None,
    asking_price: float | None,
    current_assessed_value: float | None,
    current_annual_taxes: float | None,
    state: str,
    county: str | None,
) -> list[dict[str, Any]]:
    values = {
        "purchase_price": purchase_price,
        "asking_price": asking_price,
        "current_assessed_value": current_assessed_value,
        "current_annual_taxes": current_annual_taxes,
        "state": state,
        "county": county,
    }
    return [
        {
            "driver": key,
            "value": value,
            "source": "provided" if value is not None else "unknown",
        }
        for key, value in values.items()
    ]


def _unknown_state_result(
    state: str,
    *,
    purchase_price: float | None,
    asking_price: float | None,
    current_assessed_value: float | None,
    current_annual_taxes: float | None,
    county: str | None,
) -> dict[str, Any]:
    reason = (
        f"No sourced reassessment rule is registered for {state or 'the supplied state'}. "
        "No value or tax rate was guessed; obtain the parcel-specific rule and millage from the county assessor."
    )
    return {
        "status": UNKNOWN,
        "state": state or UNKNOWN,
        "county": county,
        "state_rule": {
            "state": state or UNKNOWN,
            "reassessment_on_sale": "unknown",
            "source_citation": "No registry entry.",
            "confidence": "low",
            "last_verified": LAST_VERIFIED,
        },
        "projected_assessed_value": _unknown_range(reason),
        "projected_annual_taxes": _unknown_range(reason),
        "annual_noi_delta": _unknown_range(reason),
        "projected_taxes": _unknown_range(reason),
        "noi_delta": _unknown_range(reason),
        "method": "not computed — unregistered state",
        "caveats": [reason, VERIFY_MESSAGE],
        "assumption_sheet": _assumptions(
            purchase_price,
            asking_price,
            current_assessed_value,
            current_annual_taxes,
            state,
            county,
        ),
        "professional_review_required": True,
        "professional_review_flag": True,
        "verify_with_county_assessor_or_tax_counsel_before_reliance": True,
        "verification_message": VERIFY_MESSAGE,
    }


def estimate_reassessment(
    purchase_price: float | None,
    current_assessed_value: float | None,
    current_annual_taxes: float | None,
    state: str,
    county: str | None = None,
    *,
    asking_price: float | None = None,
) -> dict[str, Any]:
    """Estimate first-year assessment, tax, and NOI effects without inventing rules.

    For periodic-reappraisal states, the current record is carried forward only as
    a neutral placeholder.  It is never reset to purchase price.  For sale-reset
    states, a supplied purchase price is the base value; an asking price is used
    only when purchase price is unavailable and receives a visibly wider band.
    """

    normalized_state = str(state or "").strip().upper()
    price = _number(purchase_price, "purchase_price")
    asking = _number(asking_price, "asking_price")
    assessed = _number(current_assessed_value, "current_assessed_value")
    taxes = _number(current_annual_taxes, "current_annual_taxes")
    rule = STATE_RULES_REGISTRY.get(normalized_state)
    if rule is None:
        return _unknown_state_result(
            normalized_state,
            purchase_price=price,
            asking_price=asking,
            current_assessed_value=assessed,
            current_annual_taxes=taxes,
            county=county,
        )

    caveats = [rule.local_variation, rule.annual_increase_cap_scope, VERIFY_MESSAGE]
    implied_millage = taxes / assessed if taxes is not None and assessed and assessed > 0 else None
    rate_range: tuple[float, float, float] | None = None
    if implied_millage is not None:
        rate_range = (implied_millage, implied_millage, implied_millage)
        tax_method = (
            f"Current-record implied effective rate {implied_millage:.6f} "
            "(current annual taxes / current assessed value), held constant conditionally."
        )
    elif rule.indicative_effective_tax_rate_range is not None:
        rate_range = rule.indicative_effective_tax_rate_range
        tax_method = (
            "State-level indicative effective-rate band used because a parcel millage was not supplied; "
            "replace with the county, city, school, and special-district rate."
        )
        caveats.append("Indicative state rate band is a screening fallback, not parcel millage.")
    else:
        tax_method = "Not computed because no current-record millage can be derived."

    if rule.reassessment_on_sale == "periodic_reappraisal_no_sale_trigger":
        status = "NO_SALE_TRIGGER"
        assessed_range = (
            _money_range(assessed, assessed, assessed)
            if assessed is not None
            else _unknown_range("Current assessed value is required for a carry-forward placeholder.")
        )
        if taxes is not None:
            tax_range: dict[str, Any] = _money_range(taxes, taxes, taxes)
            noi_range: dict[str, Any] = _money_range(0.0, 0.0, 0.0)
        elif assessed is not None and rate_range is not None:
            low_rate, base_rate, high_rate = rate_range
            tax_range = _money_range(
                assessed * low_rate,
                assessed * base_rate,
                assessed * high_rate,
            )
            noi_range = _unknown_range(
                "Current annual taxes are required to calculate the change in NOI."
            )
        else:
            tax_range = _unknown_range(
                "Current annual taxes or a derivable parcel millage is required."
            )
            noi_range = _unknown_range(
                "Current annual taxes and projected taxes are required to calculate NOI change."
            )
        value_method = (
            "No price-based reset modeled. Current assessment carried forward as a conditional "
            "placeholder; the next county/CAD market reappraisal remains unquantified."
        )
        caveats.append(
            "The zero modeled delta is not a forecast: the next periodic county/CAD reappraisal can "
            "materially change assessed value and tax even though the sale itself is not the trigger."
        )
    else:
        status = "ESTIMATE"
        anchor = price if price is not None else asking
        if anchor is None:
            reason = (
                "Purchase price is unknown and no asking price was supplied; the post-transfer just "
                "value cannot be estimated without inventing a value."
            )
            assessed_range = _unknown_range(reason)
            tax_range = _unknown_range(reason)
            noi_range = _unknown_range(reason)
            value_method = "not computed — purchase price and asking price are unknown"
            caveats.append(reason)
        else:
            if price is None:
                low_value, base_value, high_value = anchor * 0.90, anchor, anchor * 1.10
                value_method = (
                    "Purchase price unavailable; asking price used as an unverified market proxy with "
                    "a ±10% screening band. This is not an assessor conclusion."
                )
                caveats.append(
                    "Asking price is not transaction consideration or appraised just value; replace it at closing."
                )
            elif rule.reassessment_on_sale == "full_reset_to_price":
                low_value = base_value = high_value = anchor
                value_method = (
                    "Purchase price used for the new base-year value, conditional on an arm's-length "
                    "full ownership change and no exclusion or assessor evidence of different market value."
                )
            else:
                low_value, base_value, high_value = anchor * 0.95, anchor, anchor * 1.05
                value_method = (
                    "Purchase price anchors post-transfer just value; ±5% reflects county appraisal "
                    "judgment and the difference between consideration and just value."
                )
            assessed_range = _money_range(low_value, base_value, high_value)
            if rate_range is None:
                reason = (
                    "Projected assessment is shown, but taxes are UNKNOWN because no parcel millage "
                    "was derivable and no honest state screening band is registered."
                )
                tax_range = _unknown_range(reason)
                noi_range = _unknown_range(reason)
                caveats.append(reason)
            else:
                low_rate, base_rate, high_rate = rate_range
                low_tax = low_value * low_rate
                base_tax = base_value * base_rate
                high_tax = high_value * high_rate
                tax_range = _money_range(low_tax, base_tax, high_tax)
                if taxes is None:
                    noi_range = _unknown_range(
                        "Current annual taxes are required to calculate the change in NOI."
                    )
                else:
                    # Low NOI is the downside case (highest projected tax).
                    noi_range = _money_range(
                        taxes - high_tax,
                        taxes - base_tax,
                        taxes - low_tax,
                    )

    result = {
        "status": status,
        "state": normalized_state,
        "county": county,
        "state_rule": rule.to_dict(),
        "projected_assessed_value": assessed_range,
        "projected_annual_taxes": tax_range,
        "annual_noi_delta": noi_range,
        "annual_noi_delta_sign_convention": (
            "Current annual taxes minus projected annual taxes; a negative value is an NOI reduction."
        ),
        "implied_millage": round(implied_millage, 8) if implied_millage is not None else None,
        "method": {"assessed_value": value_method, "taxes": tax_method},
        "caveats": caveats,
        "assumption_sheet": _assumptions(
            price,
            asking,
            assessed,
            taxes,
            normalized_state,
            county,
        ),
        "professional_review_required": True,
        "professional_review_flag": True,
        "verify_with_county_assessor_or_tax_counsel_before_reliance": True,
        "verification_message": VERIFY_MESSAGE,
    }
    result["projected_taxes"] = result["projected_annual_taxes"]
    result["noi_delta"] = result["annual_noi_delta"]
    return result


__all__ = [
    "LAST_VERIFIED",
    "STATE_RULES",
    "STATE_RULES_REGISTRY",
    "StateReassessmentRule",
    "estimate_reassessment",
]
