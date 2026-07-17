"""Deterministic sale-process framing, bid rules, gates, and timeline.

This module designs a planning template only.  It does not send marketing
materials, make a broker recommendation, create a binding auction, or replace a
counsel-reviewed process letter, confidentiality agreement, or purchase agreement.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

OBJECTIVE_NAMES = (
    "price_discovery",
    "speed",
    "certainty",
    "confidentiality",
    "seller_control",
    "low_process_cost",
)

DEFAULT_OBJECTIVE_WEIGHTS: dict[str, float] = {
    "price_discovery": 0.25,
    "speed": 0.15,
    "certainty": 0.25,
    "confidentiality": 0.15,
    "seller_control": 0.10,
    "low_process_cost": 0.10,
}

PROCESS_FIT: dict[str, dict[str, float]] = {
    "brokered": {
        "price_discovery": 0.85,
        "speed": 0.55,
        "certainty": 0.70,
        "confidentiality": 0.55,
        "seller_control": 0.60,
        "low_process_cost": 0.25,
    },
    "targeted": {
        "price_discovery": 0.55,
        "speed": 0.85,
        "certainty": 0.70,
        "confidentiality": 0.90,
        "seller_control": 0.90,
        "low_process_cost": 0.80,
    },
    "auction": {
        "price_discovery": 0.95,
        "speed": 0.70,
        "certainty": 0.60,
        "confidentiality": 0.35,
        "seller_control": 0.45,
        "low_process_cost": 0.20,
    },
}


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dict(dumped)
    data = getattr(value, "__dict__", None)
    if isinstance(data, Mapping):
        return dict(data)
    raise TypeError(f"{label} must be a mapping or mapping-like model")


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ValueError("target sale/closing date must be an ISO date") from exc


def _priority(value: Any, *, key: str) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        named = {
            "none": 0.0,
            "low": 0.25,
            "medium": 0.5,
            "moderate": 0.5,
            "high": 0.75,
            "critical": 1.0,
            "maximum": 1.0,
        }
        normalized = value.strip().casefold()
        if normalized in named:
            return named[normalized]
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"objective {key} must be 0..1 or low/medium/high/critical") from exc
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(f"objective {key} must be between 0 and 1")
    return result


def _objective_weights(objectives: Mapping[str, Any]) -> tuple[dict[str, float], list[str]]:
    aliases = {
        "price": "price_discovery",
        "maximize_price": "price_discovery",
        "pricing": "price_discovery",
        "close_speed": "speed",
        "execution_certainty": "certainty",
        "privacy": "confidentiality",
        "control": "seller_control",
        "cost": "low_process_cost",
        "minimize_cost": "low_process_cost",
    }
    supplied = objectives.get("weights", objectives.get("priority_weights", objectives))
    if not isinstance(supplied, Mapping):
        raise TypeError("objectives weights must be a mapping")
    raw: dict[str, float] = {}
    sources: list[str] = []
    for input_key, value in supplied.items():
        normalized_key = aliases.get(str(input_key).strip().casefold(), str(input_key).strip().casefold())
        if normalized_key in OBJECTIVE_NAMES:
            raw[normalized_key] = _priority(value, key=normalized_key)
            sources.append(f"{normalized_key} supplied as {value!r}")
    if not raw:
        return dict(DEFAULT_OBJECTIVE_WEIGHTS), ["No objective weights supplied; default balanced seller rubric used."]
    # Unmentioned objectives retain a small nonzero floor so a single priority
    # does not pretend the other execution dimensions disappear.
    combined = {
        key: raw.get(key, DEFAULT_OBJECTIVE_WEIGHTS[key] * 0.25)
        for key in OBJECTIVE_NAMES
    }
    total = sum(combined.values())
    if total <= 0:
        return dict(DEFAULT_OBJECTIVE_WEIGHTS), ["All supplied priorities were zero; default balanced seller rubric used."]
    return ({key: round(value / total, 6) for key, value in combined.items()}, sources)


def _process_options() -> dict[str, dict[str, Any]]:
    return {
        "brokered": {
            "label": "Broad brokered marketing",
            "framing": "Retain a broker to expose a governed offering to a broad qualified buyer universe.",
            "typical_timeline_weeks": {"low": 14, "high": 22},
            "tradeoffs": {
                "advantages": [
                    "Broad reach and broker-managed buyer follow-up",
                    "Stronger market feedback and price discovery than a narrow direct list",
                    "Useful coordination layer for tours, Q&A, and bid comparability",
                ],
                "costs_risks": [
                    "Broker fee and substantial owner/manager preparation time",
                    "More recipients increase confidentiality and rumor risk",
                    "Wide outreach does not guarantee competitive tension or closing certainty",
                ],
            },
            "best_fit": "A marketable asset where broad reach matters more than maximum privacy or lowest cost.",
        },
        "targeted": {
            "label": "Targeted / controlled buyer outreach",
            "framing": "Approach a prequalified, strategy-specific buyer list under staged access controls.",
            "typical_timeline_weeks": {"low": 8, "high": 16},
            "tradeoffs": {
                "advantages": [
                    "Higher confidentiality and seller control",
                    "Faster path when known buyers already fit check size, market, and asset type",
                    "Lower marketing cost and management disruption",
                ],
                "costs_risks": [
                    "Limited price discovery and fewer fallback bidders",
                    "A favored buyer may infer low competitive tension",
                    "Owner must govern outreach, conflicts, information parity, and follow-up",
                ],
            },
            "best_fit": "A privacy-sensitive situation with a credible short list and meaningful value placed on speed/control.",
        },
        "auction": {
            "label": "Structured auction",
            "framing": "Use fixed rounds, common data, deadlines, and best-and-final submissions to create comparable competition.",
            "typical_timeline_weeks": {"low": 12, "high": 20},
            "tradeoffs": {
                "advantages": [
                    "Strongest explicit competitive-tension and price-discovery posture",
                    "Common deadlines can expose certainty differences among bids",
                    "Creates disciplined fallbacks when multiple qualified bidders engage",
                ],
                "costs_risks": [
                    "Highest process cost, leak risk, and diligence burden",
                    "Rigid or artificial rules can repel strong buyers",
                    "Aggressive winning bids can create retrade risk; headline price is not certainty-adjusted proceeds",
                ],
            },
            "best_fit": "A broadly appealing asset with enough qualified demand to support real—not assumed—competition.",
        },
    }


def _score_processes(
    deal: Mapping[str, Any],
    objectives: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    weights, weight_sources = _objective_weights(objectives)
    adjustments: dict[str, list[dict[str, Any]]] = {key: [] for key in PROCESS_FIT}
    known_buyers = deal.get("known_buyer_count", deal.get("qualified_buyer_count"))
    try:
        known_buyers_number = int(known_buyers) if known_buyers is not None else None
    except (TypeError, ValueError):
        known_buyers_number = None
    if known_buyers_number is not None and known_buyers_number <= 10:
        adjustments["targeted"].append({"points": 5.0, "reason": "Known qualified buyer universe is ten or fewer."})
        adjustments["auction"].append({"points": -5.0, "reason": "A narrow stated buyer universe may not support a genuine auction."})
    if known_buyers_number is not None and known_buyers_number >= 20:
        adjustments["auction"].append({"points": 4.0, "reason": "Twenty or more stated qualified buyers can support competitive rounds."})
    if objectives.get("avoid_broker") is True:
        adjustments["brokered"].append({"points": -10.0, "reason": "Seller explicitly asked to avoid a broker."})
        adjustments["targeted"].append({"points": 4.0, "reason": "Targeted outreach aligns with an owner-directed process."})
    if objectives.get("broad_market_test") is True:
        adjustments["brokered"].append({"points": 5.0, "reason": "Seller explicitly requested a broad market test."})
        adjustments["auction"].append({"points": 5.0, "reason": "Structured rounds support the requested market test if demand exists."})
    if deal.get("confidentiality_sensitive") is True:
        adjustments["targeted"].append({"points": 5.0, "reason": "Deal is explicitly confidentiality-sensitive."})
        adjustments["auction"].append({"points": -6.0, "reason": "Broad auction exposure conflicts with stated confidentiality sensitivity."})

    scored: list[dict[str, Any]] = []
    for process_name, fit in PROCESS_FIT.items():
        components = {
            key: round(weights[key] * fit[key] * 100.0, 2)
            for key in OBJECTIVE_NAMES
        }
        base_score = sum(components.values())
        adjustment_total = sum(float(row["points"]) for row in adjustments[process_name])
        scored.append(
            {
                "process": process_name,
                "fit_score": round(max(0.0, min(100.0, base_score + adjustment_total)), 2),
                "base_weighted_score": round(base_score, 2),
                "component_points": components,
                "deal_adjustments": adjustments[process_name],
                "adjustment_points": adjustment_total,
            }
        )
    scored.sort(key=lambda row: (-float(row["fit_score"]), str(row["process"])))
    disclosure = {
        "objective_weights": weights,
        "objective_sources": weight_sources,
        "process_fit_factors": PROCESS_FIT,
        "formula": "100 * sum(objective_weight * process_fit_factor) + disclosed deal adjustments, clipped to 0..100",
        "interpretation": "Deterministic planning fit, not predicted price, probability of close, broker advice, or auction outcome.",
    }
    return scored, disclosure


def _confidentiality_tiers() -> list[dict[str, Any]]:
    return [
        {
            "tier": 0,
            "name": "anonymized teaser",
            "access_gate": "seller-approved recipient universe; no NDA required",
            "materials": ["general market", "asset type", "rounded size/economics", "process contact"],
            "excluded": ["property identity if sensitive", "tenant identities", "lease documents", "PII", "bank details"],
        },
        {
            "tier": 1,
            "name": "NDA marketing room",
            "access_gate": "executed counsel-approved NDA and identity/conflict check",
            "materials": ["identified OM", "summary rent roll", "summary historical operations", "tour protocol"],
            "excluded": ["unredacted leases", "tenant PII", "security data", "bank/tax identifiers"],
        },
        {
            "tier": 2,
            "name": "qualified diligence room",
            "access_gate": "NDA plus buyer identity, check-size fit, financing plan, and reasonable proof of funds/capital",
            "materials": ["redacted leases/amendments", "detailed financials", "title/survey/PCA/environmental", "governed Q&A"],
            "excluded": ["unnecessary PII", "credentials", "wire instructions", "privileged material"],
        },
        {
            "tier": 3,
            "name": "finalist / selected-buyer room",
            "access_gate": "credible complete bid or selection, enhanced NDA terms as counsel directs, need-to-know approval",
            "materials": ["remaining deal-critical sensitive records", "estoppel/SNDA status", "PSA/title cure workstream"],
            "excluded": ["privileged material unless counsel authorizes", "credentials", "email-only wire changes"],
        },
    ]


def _bid_round_rules() -> dict[str, Any]:
    return {
        "rounds": [
            {
                "round": 1,
                "name": "Indication of interest",
                "submission_requirements": [
                    "headline price or clearly bounded range",
                    "deposit amount and when it becomes non-refundable",
                    "diligence and closing days",
                    "financing type, financing contingency, and proof status",
                    "all contingencies, approvals, assumptions, and material markups",
                    "buyer entity, relevant closing experience, and conflicts",
                ],
                "access": "tiers 0-1",
                "advance_gate": "Strategy/check-size fit, credible capital plan, complete comparable terms, and no disqualifying conflict.",
            },
            {
                "round": 2,
                "name": "Shortlist diligence and revised bid",
                "submission_requirements": [
                    "single price",
                    "deposit at-risk schedule",
                    "requested exclusivity and PSA comments",
                    "confirmed diligence/closing calendar",
                    "specific remaining conditions and third-party approvals",
                    "financing evidence appropriate to stated capital structure",
                ],
                "access": "tier 2 after gate satisfaction",
                "advance_gate": "Credible diligence engagement, no material undisclosed conditions, and seller-approved normalized economics/certainty review.",
            },
            {
                "round": 3,
                "name": "Best and final",
                "submission_requirements": [
                    "best price and complete economic terms in the common bid form",
                    "expiration time and authority to sign",
                    "final financing and equity evidence status",
                    "final deposit, diligence, closing, contingency, and PSA exceptions",
                    "certification that no oral side terms are relied upon",
                ],
                "access": "tier 2; tier 3 only after finalist/selection approval",
                "advance_gate": "Certainty-adjusted comparison, reference/capital verification, conflicts review, and seller decision authority.",
            },
        ],
        "best_and_final_rules": [
            "Give finalists the same bid form, material Q&A, deadline, and stated assumptions.",
            "Normalize headline price for deposit risk, diligence carry, financing, contingencies, and retrade history using disclosed conventions.",
            "Do not claim another bid, price, deadline, or seller instruction unless accurate and authorized.",
            "No automatic winner: seller may accept, reject, clarify, pause, or end the process subject to counsel-approved language and applicable duties.",
            "Record deviations and late changes; do not silently improve one bidder's access or assumptions.",
        ],
        "process_letter": {
            "template_sections": [
                "non-binding process and seller reservation of rights",
                "submission deadline, channel, required form, and expiration",
                "data-room and site-access gates",
                "confidentiality and no-contact rules",
                "bid requirements and comparison convention",
                "seller clarification, modification, rejection, and termination rights",
                "no reliance; buyer diligence and authority statements",
            ],
            "professional_review_required": True,
            "professional_review_flag": (
                "CRE counsel must draft/review every process letter, NDA, bidder communication, "
                "reservation-of-rights clause, access rule, and award/termination notice before use."
            ),
            "not_legal_advice": True,
        },
    }


def _timeline(target: date | None) -> dict[str, Any]:
    stages = [
        ("readiness", -26, -20, "Approve objectives; resolve financial, lease, title/survey, physical, tax, and data-room blockers.", []),
        ("positioning", -20, -17, "Select process, pricing posture, buyer universe, confidentiality plan, and counsel-approved materials.", ["readiness"]),
        ("launch", -17, -13, "Release teaser/NDA/OM, qualify buyers, govern Q&A, and schedule tours.", ["positioning"]),
        ("round_1_ioi", -13, -11, "Receive complete IOIs and normalize price/certainty terms.", ["launch", "tier_1_access"]),
        ("shortlist_diligence", -11, -8, "Open tier 2 to qualified bidders; answer common Q&A and log exceptions.", ["round_1_ioi", "qualification_gate"]),
        ("best_and_final", -8, -7, "Receive common-form best-and-final bids and run certainty-adjusted comparison.", ["shortlist_diligence"]),
        ("selection_psa", -7, -5, "Select primary and backup; verify authority/capital; negotiate and execute PSA.", ["best_and_final", "seller_decision_authority", "counsel_review"]),
        ("contract_diligence_close", -5, 0, "Manage deposit, diligence, title cure, estoppels/consents, financing, closing documents, and backup posture.", ["selection_psa"]),
    ]
    rows: list[dict[str, Any]] = []
    for key, start_week, end_week, action, dependencies in stages:
        row: dict[str, Any] = {
            "stage": key,
            "start_week_relative_to_close": start_week,
            "end_week_relative_to_close": end_week,
            "action": action,
            "dependencies": dependencies,
        }
        if target is not None:
            row["start_date"] = (target + timedelta(weeks=start_week)).isoformat()
            row["end_date"] = (target + timedelta(weeks=end_week)).isoformat()
        rows.append(row)
    return {
        "target_close_date": target.isoformat() if target is not None else None,
        "total_planning_weeks": 26,
        "schedule_basis": (
            "Backward-planned seller convention from target close; stages can overlap only when "
            "their listed dependencies and access gates are satisfied. Replace with transaction-specific dates."
            if target is not None
            else "Relative weeks before an unsupplied target close; no calendar dates were invented."
        ),
        "stages": rows,
        "critical_dependencies": [
            "Readiness blockers before broad reliance on marketing materials",
            "Counsel-approved NDA/process/access documents before release",
            "Qualified capital and financing evidence before sensitive access",
            "Common material Q&A before bid deadlines",
            "Seller decision authority and conflict review before selection",
            "PSA, title cure, estoppels/consents, deposit, financing, and closing deliverables after selection",
        ],
    }


def design_sale_process(
    deal: Mapping[str, Any] | Any,
    objectives: Mapping[str, Any] | Any,
) -> dict[str, Any]:
    """Frame brokered, targeted, and auction paths and return governed rules."""

    deal_data = _mapping(deal, label="deal")
    objective_data = _mapping(objectives, label="objectives")
    target = _date(
        objective_data.get(
            "target_close_date",
            objective_data.get(
                "target_sale_date",
                deal_data.get("target_close_date", deal_data.get("target_sale_date")),
            ),
        )
    )
    options = _process_options()
    ranking, scoring = _score_processes(deal_data, objective_data)
    recommended = str(ranking[0]["process"])
    options_list = [
        {
            "process": process_name,
            **details,
            "fit": next(row for row in ranking if row["process"] == process_name),
        }
        for process_name, details in options.items()
    ]
    return {
        "deal": {
            "deal_id": deal_data.get("deal_id"),
            "price": deal_data.get("price", deal_data.get("expected_sale_price")),
            "type": deal_data.get("type", deal_data.get("deal_type", deal_data.get("asset_type"))),
            "market": deal_data.get("market"),
        },
        "recommended_process": recommended,
        "recommendation": {
            "process": recommended,
            "fit_score": ranking[0]["fit_score"],
            "reason": (
                "Highest deterministic fit under the disclosed objective weights and deal adjustments; "
                "confirm demand, conflicts, broker scope, authority, and legal process before launch."
            ),
            "not_an_outcome_prediction": True,
        },
        "process_options": options_list,
        "alternatives": options,
        "fit_ranking": ranking,
        "scoring_rubric": scoring,
        "bid_round_rules": _bid_round_rules(),
        "confidentiality_tiers": _confidentiality_tiers(),
        "timeline": _timeline(target),
        "governance": {
            "information_parity": "Material Q&A or corrections go to all similarly situated active bidders unless counsel documents a lawful reason otherwise.",
            "source_of_truth": "Use one version-controlled data room, Q&A log, bid form, access log, and bidder status record.",
            "wire_fraud_control": "Never rely on email-only wire changes; independently verify instructions through approved contacts.",
            "no_fake_competition": "Never invent bids, deadlines, participants, or seller authority to create pressure.",
            "decision_record": "Record seller objectives, comparisons, deviations, conflicts, authority, selection, backup, and reasons.",
        },
        "professional_review_required": True,
        "professional_review_flags": [
            "CRE counsel must approve process letters, NDAs, access/no-contact terms, bidder communications, and selection/termination notices.",
            "Counsel should review fair-dealing, licensing, agency, antitrust, confidentiality, privacy, privilege, and seller-authority issues for the facts and jurisdiction.",
            "CPA/tax counsel should review representations about seller proceeds, tax structure, or exchange timing; this process module does not calculate them.",
        ],
        "disclaimer": "Planning template only; not legal, brokerage, tax, accounting, securities, valuation, or transaction advice.",
    }


__all__ = [
    "DEFAULT_OBJECTIVE_WEIGHTS",
    "OBJECTIVE_NAMES",
    "PROCESS_FIT",
    "design_sale_process",
]
