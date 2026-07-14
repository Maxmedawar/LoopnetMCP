"""State foreclosure timeline registry for preliminary distressed-note screening.

The registry deliberately contains only states for which a source note was prepared.
Unseeded states return ``UNKNOWN`` rather than borrowing a neighboring state's timing.
The month bands are planning observations, not statutory promises or legal opinions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

LAST_VERIFIED = "2026-07"
COUNSEL_VERIFICATION_FLAG = (
    "verify with licensed foreclosure counsel in the property state — timelines shift "
    "with courts and filings"
)
AUTOMATIC_STAY_WARNING = (
    "A bankruptcy petition generally triggers the 11 U.S.C. § 362 automatic stay and "
    "pauses foreclosure, sale, collection, and often possession activity. Stay duration is "
    "UNKNOWN without the chapter, docket, debtor/property facts, motions for relief, and court orders."
)

Process = Literal["judicial", "nonjudicial", "both"]
Confidence = Literal["high", "moderate", "low"]


@dataclass(frozen=True, slots=True)
class StateForeclosureTimeline:
    """One sourced state planning entry; legal details remain counsel questions."""

    state: str
    state_name: str
    process: Process
    uncontested_low_months: float
    uncontested_high_months: float
    redemption_period: str
    redemption_survives_sale: bool | None
    deficiency_judgment_allowed: bool | None
    deficiency_note: str
    eviction_low_months: float
    eviction_high_months: float
    source_note: str
    confidence: Confidence
    last_verified: str = LAST_VERIFIED
    professional_review_flag: str = COUNSEL_VERIFICATION_FLAG

    def to_dict(self) -> dict:
        data = asdict(self)
        data["uncontested_duration_months"] = _range(
            self.uncontested_low_months,
            self.uncontested_high_months,
        )
        data["typical_eviction_add_on_months"] = _range(
            self.eviction_low_months,
            self.eviction_high_months,
        )
        return data


def _range(low: float, high: float) -> dict[str, float]:
    return {"low": low, "base": (low + high) / 2.0, "high": high}


def _entry(
    state: str,
    state_name: str,
    process: Process,
    duration: tuple[float, float],
    redemption_period: str,
    redemption_survives_sale: bool | None,
    deficiency_judgment_allowed: bool | None,
    deficiency_note: str,
    eviction: tuple[float, float],
    source_note: str,
    confidence: Confidence = "moderate",
) -> StateForeclosureTimeline:
    return StateForeclosureTimeline(
        state=state,
        state_name=state_name,
        process=process,
        uncontested_low_months=duration[0],
        uncontested_high_months=duration[1],
        redemption_period=redemption_period,
        redemption_survives_sale=redemption_survives_sale,
        deficiency_judgment_allowed=deficiency_judgment_allowed,
        deficiency_note=deficiency_note,
        eviction_low_months=eviction[0],
        eviction_high_months=eviction[1],
        source_note=source_note,
        confidence=confidence,
    )


STATE_FORECLOSURE_REGISTRY: dict[str, StateForeclosureTimeline] = {
    "CA": _entry(
        "CA",
        "California",
        "nonjudicial",
        (4, 6),
        "No statutory redemption after a completed nonjudicial trustee sale; cure/reinstatement rights apply before sale.",
        False,
        False,
        "No deficiency after the modeled nonjudicial sale; California also protects qualifying purchase-money debt. Judicial and guaranty exceptions require counsel.",
        (0.5, 2),
        "Cal. Civ. Code §§ 2924, 2924c and Cal. Code Civ. Proc. §§ 580b, 580d; California Courts foreclosure/eviction self-help materials. The 4–6 month band is an uncontested planning range, not a statutory deadline.",
        "high",
    ),
    "TX": _entry(
        "TX",
        "Texas",
        "nonjudicial",
        (2, 3),
        "No general post-sale statutory redemption for an ordinary deed-of-trust foreclosure.",
        False,
        True,
        "A deficiency can be pursued subject to Tex. Prop. Code § 51.003 valuation and deadline rules; transaction-specific anti-deficiency issues require counsel.",
        (0.5, 2),
        "Tex. Prop. Code §§ 51.002 and 51.003. Nonjudicial sales are generally held on the first Tuesday of the month after required notices; the 2–3 month band assumes an uncontested, properly documented file.",
        "high",
    ),
    "FL": _entry(
        "FL",
        "Florida",
        "judicial",
        (8, 14),
        "Equitable right of redemption generally ends at the time fixed by judgment or filing of the certificate of sale; no general post-completion statutory period is assumed.",
        False,
        True,
        "Deficiency relief is discretionary and fact-dependent under Fla. Stat. § 702.06.",
        (1, 3),
        "Fla. Stat. chs. 45 and 702, including § 702.06; Florida Courts foreclosure materials. The 8–14 month band is an uncontested planning observation and can run longer by county.",
    ),
    "NY": _entry(
        "NY",
        "New York",
        "judicial",
        (24, 60),
        "Equitable redemption generally continues until the foreclosure sale; no general post-sale statutory redemption is assumed.",
        False,
        True,
        "Deficiency practice is governed by RPAPL § 1371 and strict timing/valuation rules.",
        (2, 8),
        "N.Y. RPAPL art. 13, including §§ 1304 and 1371, and New York Courts foreclosure resources. YEARS are common in planning; the 24–60 month band has LOW confidence because county court backlog, settlement conferences, service, and motion practice vary materially.",
        "low",
    ),
    "NJ": _entry(
        "NJ",
        "New Jersey",
        "judicial",
        (12, 30),
        "A limited post-sale redemption window may exist, commonly tied to the objection period and extended by certain filings; counsel must calculate it.",
        True,
        True,
        "New Jersey's Fair Foreclosure Act and deficiency procedures impose notices, deadlines, and fair-value issues.",
        (1, 4),
        "N.J.S.A. 2A:50-1 et seq. and New Jersey Judiciary foreclosure guidance. The 12–30 month band is a court-dependent uncontested planning range.",
        "low",
    ),
    "IL": _entry(
        "IL",
        "Illinois",
        "judicial",
        (10, 18),
        "Statutory redemption generally expires on the later of seven months after service or three months after judgment; it ordinarily expires before the sale.",
        False,
        True,
        "A personal deficiency may be available when pleaded and supported, subject to loan and borrower defenses.",
        (1, 3),
        "Illinois Mortgage Foreclosure Law, 735 ILCS 5/15-1101 et seq., especially 15-1603 and 15-1507. The 10–18 month band assumes an uncontested case.",
    ),
    "GA": _entry(
        "GA",
        "Georgia",
        "nonjudicial",
        (2, 4),
        "No general statutory redemption after a valid power-of-sale foreclosure.",
        False,
        True,
        "A deficiency generally requires timely judicial confirmation under O.C.G.A. § 44-14-161.",
        (0.5, 2),
        "O.C.G.A. §§ 44-14-160 through 44-14-162.4. The 2–4 month band assumes valid power-of-sale documents, uncontested notice, and available sale dates.",
        "high",
    ),
    "AZ": _entry(
        "AZ",
        "Arizona",
        "nonjudicial",
        (3, 5),
        "No statutory redemption after a trustee sale; judicial foreclosure has a different framework.",
        False,
        None,
        "Deficiency availability depends on property type/size/use, sale method, and A.R.S. § 33-814; it is intentionally not reduced to yes/no here.",
        (0.5, 2),
        "A.R.S. §§ 33-801 through 33-821, especially 33-807, 33-811 and 33-814. The 3–5 month band models an uncontested trustee sale.",
        "high",
    ),
    "NV": _entry(
        "NV",
        "Nevada",
        "nonjudicial",
        (4, 7),
        "No general post-trustee-sale redemption is assumed for the nonjudicial path.",
        False,
        True,
        "A deficiency can be constrained by NRS 40.455 et seq., fair-value limits, waivers, and timing.",
        (0.5, 2),
        "NRS 107.080 et seq. and NRS 40.455 et seq. The 4–7 month band assumes statutory notice/cure steps and no mediation, litigation, or bankruptcy delay.",
    ),
    "CO": _entry(
        "CO",
        "Colorado",
        "nonjudicial",
        (4, 7),
        "Cure/redemption rights are concentrated before sale; no general borrower post-sale redemption is assumed under the modeled public-trustee path.",
        False,
        True,
        "Deficiency availability and amount depend on bid, debt, guaranties, and fair-value defenses.",
        (0.5, 2),
        "Colo. Rev. Stat. title 38, art. 38 and C.R.C.P. 120. The public-trustee process includes limited court authorization; the 4–7 month band is an uncontested planning range.",
    ),
    "OH": _entry(
        "OH",
        "Ohio",
        "judicial",
        (9, 18),
        "The equitable right of redemption generally lasts until judicial confirmation, so it can survive the auction but not final confirmation.",
        True,
        True,
        "A deficiency may be available, subject to judgment, loan terms, statutes of limitation, and debtor protections.",
        (1, 4),
        "Ohio Rev. Code chs. 2323 and 2329 and county common-pleas foreclosure procedures. The 9–18 month band is a county-dependent uncontested planning range.",
        "low",
    ),
    "PA": _entry(
        "PA",
        "Pennsylvania",
        "judicial",
        (10, 24),
        "No general post-sheriff-sale statutory redemption is assumed for an ordinary mortgage foreclosure.",
        False,
        True,
        "The Deficiency Judgment Act, 42 Pa.C.S. § 8103, imposes fair-value and timing requirements.",
        (1, 4),
        "Pa. R.C.P. 1141–1164, Pennsylvania Act 6/Act 91 where applicable, and 42 Pa.C.S. § 8103. The 10–24 month band is an uncontested planning range with material county variation.",
        "low",
    ),
    "NC": _entry(
        "NC",
        "North Carolina",
        "nonjudicial",
        (3, 6),
        "No general borrower redemption after sale; the statutory upset-bid period is a sale-finality process, not assumed to be a redemption right.",
        False,
        True,
        "Deficiency rights can be affected by purchase-money rules, fair-value defenses, and loan facts.",
        (0.5, 2),
        "N.C. Gen. Stat. ch. 45, art. 2A, including the power-of-sale hearing and upset-bid process. The 3–6 month band assumes no injunction or bankruptcy.",
        "high",
    ),
    "TN": _entry(
        "TN",
        "Tennessee",
        "nonjudicial",
        (2, 4),
        "A statutory redemption right may last two years but is commonly waived in loan documents; never assume waiver or survival without document review.",
        True,
        True,
        "Deficiency claims are generally possible but require sale, notice, valuation, and document review.",
        (0.5, 2),
        "Tenn. Code Ann. §§ 35-5-101 et seq. and 66-8-101 et seq. The 2–4 month band models an uncontested power-of-sale process and excludes any unwaived redemption period.",
        "moderate",
    ),
    "WA": _entry(
        "WA",
        "Washington",
        "nonjudicial",
        (5, 8),
        "No statutory redemption after a completed nonjudicial trustee sale.",
        False,
        False,
        "Deficiency is generally barred after the modeled deed-of-trust trustee sale, subject to statutory commercial-guaranty and waste exceptions requiring counsel.",
        (0.5, 3),
        "Washington Deed of Trust Act, RCW 61.24, especially RCW 61.24.040 and .100. The 5–8 month band is an uncontested planning range.",
        "high",
    ),
}

STATE_NAME_TO_CODE = {
    entry.state_name.upper(): code for code, entry in STATE_FORECLOSURE_REGISTRY.items()
}


def _state_code(state: str) -> str:
    normalized = str(state or "").strip().upper()
    return STATE_NAME_TO_CODE.get(normalized, normalized)


def _stage_range(months: dict[str, float], share: float) -> dict[str, float]:
    return {key: round(value * share, 2) for key, value in months.items()}


def _add_ranges(
    left: dict[str, float],
    right: dict[str, float],
) -> dict[str, float]:
    return {key: round(left[key] + right[key], 2) for key in ("low", "base", "high")}


def estimate_timeline(
    state: str,
    contested: bool = False,
    bankruptcy_risk: bool | None = None,
) -> dict:
    """Estimate a sourced state range and expose every material uncertainty.

    ``months`` covers foreclosure through sale/confirmation but excludes eviction.
    ``total_to_possession_months`` adds the registry's separate eviction band. A
    bankruptcy delay is never converted into guessed months.
    """

    code = _state_code(state)
    entry = STATE_FORECLOSURE_REGISTRY.get(code)
    review_flags = [COUNSEL_VERIFICATION_FLAG]
    if entry is None:
        return {
            "status": "UNKNOWN",
            "state": code or "UNKNOWN",
            "process": "UNKNOWN",
            "months": {"low": "UNKNOWN", "base": "UNKNOWN", "high": "UNKNOWN"},
            "foreclosure_months": {"low": "UNKNOWN", "base": "UNKNOWN", "high": "UNKNOWN"},
            "total_to_possession_months": {
                "low": "UNKNOWN",
                "base": "UNKNOWN",
                "high": "UNKNOWN",
            },
            "stage_breakdown": [],
            "source_note": "UNKNOWN — no reviewed state entry is seeded in this registry.",
            "confidence": "unknown",
            "last_verified": LAST_VERIFIED,
            "bankruptcy_risk": bankruptcy_risk,
            "bankruptcy_delay_months": {
                "low": "UNKNOWN",
                "base": "UNKNOWN",
                "high": "UNKNOWN",
            },
            "bankruptcy_stay_warning": AUTOMATIC_STAY_WARNING,
            "professional_review_required": True,
            "professional_review_flags": review_flags,
        }

    foreclosure = _range(entry.uncontested_low_months, entry.uncontested_high_months)
    contested_addition = {"low": 0.0, "base": 0.0, "high": 0.0}
    if contested:
        contested_addition = (
            {"low": 6.0, "base": 12.0, "high": 24.0}
            if entry.process == "judicial"
            else {"low": 3.0, "base": 6.0, "high": 12.0}
        )
        foreclosure = _add_ranges(foreclosure, contested_addition)
        review_flags.append(
            "Contested-case increment is an explicit screening convention, not state law or a court forecast."
        )

    if entry.process == "judicial":
        stage_specs = (
            ("prefiling_notice_and_service", 0.15),
            ("pleadings_litigation_and_judgment", 0.65),
            ("sale_and_confirmation", 0.20),
        )
    else:
        stage_specs = (
            ("default_cure_and_statutory_notice", 0.55),
            ("sale_scheduling_and_publication", 0.30),
            ("sale_and_deed", 0.15),
        )

    uncontested = _range(entry.uncontested_low_months, entry.uncontested_high_months)
    stages = [
        {
            "stage": name,
            "months": _stage_range(uncontested, share),
            "basis": "allocated from the registry range for screening; actual sequencing may overlap",
            "professional_review_required": True,
        }
        for name, share in stage_specs
    ]
    if contested:
        stages.append(
            {
                "stage": "contested_motion_discovery_trial_delay",
                "months": contested_addition,
                "basis": "screening convention only; case-specific delay is not predictable from state alone",
                "professional_review_required": True,
            }
        )

    eviction = _range(entry.eviction_low_months, entry.eviction_high_months)
    stages.append(
        {
            "stage": "possession_and_eviction_add_on",
            "months": eviction,
            "included_in_foreclosure_months": False,
            "basis": "separate registry planning range; occupancy, lease, and local court facts control",
            "professional_review_required": True,
        }
    )
    total_to_possession = _add_ranges(foreclosure, eviction)

    if bankruptcy_risk is True:
        review_flags.append(
            "Bankruptcy risk identified: do not calendar a sale or possession date without bankruptcy counsel and docket review."
        )
    elif bankruptcy_risk is None:
        review_flags.append(
            "Bankruptcy risk was not provided; screen borrower/guarantors and check the live docket before action."
        )

    return {
        "status": "ESTIMATED_RANGE",
        "state": entry.state,
        "state_name": entry.state_name,
        "process": entry.process,
        "months": foreclosure,
        "foreclosure_months": foreclosure,
        "total_to_possession_months": total_to_possession,
        "typical_eviction_add_on_months": eviction,
        "stage_breakdown": stages,
        "redemption_period": entry.redemption_period,
        "redemption_survives_sale": entry.redemption_survives_sale,
        "deficiency_judgment_allowed": entry.deficiency_judgment_allowed,
        "deficiency_note": entry.deficiency_note,
        "source_note": entry.source_note,
        "confidence": entry.confidence,
        "last_verified": entry.last_verified,
        "contested": contested,
        "bankruptcy_risk": bankruptcy_risk,
        "bankruptcy_delay_months": {
            "low": "UNKNOWN",
            "base": "UNKNOWN",
            "high": "UNKNOWN",
        },
        "bankruptcy_stay_warning": AUTOMATIC_STAY_WARNING,
        "professional_review_required": True,
        "professional_review_flags": review_flags,
    }


__all__ = [
    "AUTOMATIC_STAY_WARNING",
    "COUNSEL_VERIFICATION_FLAG",
    "LAST_VERIFIED",
    "STATE_FORECLOSURE_REGISTRY",
    "StateForeclosureTimeline",
    "estimate_timeline",
]
