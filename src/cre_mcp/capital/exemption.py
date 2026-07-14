"""Preliminary Regulation D solicitation and purchaser guardrails."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from cre_mcp.execution.guardrails import capital_guardrail
from cre_mcp.models.capital import ComplianceCheck

PUBLIC_ACTION_TERMS = (
    "advertise_publicly",
    "general_solicitation",
    "public website",
    "social media",
    "mass email",
    "newspaper",
    "radio",
    "television",
    "public seminar",
    "podcast",
)
PURCHASER_ACTION_TERMS = (
    "accept_investor",
    "accept_money",
    "accept_funds",
    "first_sale",
    "close_subscription",
    "sell_security",
)


def _mode(value: str) -> str:
    normalized = value.strip().casefold().replace("rule", "")
    normalized = normalized.replace("(", "").replace(")", "").replace("-", "")
    normalized = normalized.replace("_", "").replace(" ", "")
    if normalized not in {"506b", "506c"}:
        raise ValueError("mode must be 506b or 506c")
    return normalized


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "accredited", "verified"}:
            return True
        if normalized in {"false", "no", "0", "non-accredited", "unverified"}:
            return False
    return bool(value)


def _action_data(action: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(action, Mapping):
        data = dict(action)
        label = str(data.get("action") or data.get("type") or "screen_action").strip()
    else:
        data = {}
        label = str(action).strip()
    if not label:
        raise ValueError("action cannot be blank")
    normalized = label.casefold().replace("-", "_").replace(" ", "_")
    text = " ".join([normalized, *(str(value).casefold() for value in data.values())])
    action_tokens = set(filter(None, re.split(r"[^a-z0-9]+", normalized)))
    public = _optional_bool(data.get("general_solicitation"))
    if public is None:
        public = _optional_bool(data.get("public"))
    if public is None:
        public = any(term in text for term in PUBLIC_ACTION_TERMS)
    accepting = _optional_bool(data.get("accepting_money"))
    if accepting is None:
        accepting = any(term in text for term in PURCHASER_ACTION_TERMS) or (
            bool(
                action_tokens.intersection(
                    {"accept", "accepting", "close", "closing", "sell", "selling"}
                )
            )
            and bool(
                action_tokens.intersection(
                    {
                        "investor",
                        "purchaser",
                        "subscription",
                        "money",
                        "funds",
                        "security",
                        "sale",
                    }
                )
            )
        )

    accredited = _optional_bool(data.get("accredited"))
    if accredited is None and "non_accredited" in text:
        accredited = False
    elif accredited is None and "accredited" in text:
        accredited = True
    verified = _optional_bool(data.get("accreditation_verified"))
    unverified_markers = (
        "unverified",
        "not_verified",
        "without_verification",
        "pending_verification",
        "verification_pending",
        "self_certified",
        "self_certification",
    )
    if verified is None and any(marker in text for marker in unverified_markers):
        verified = False
    elif verified is None and "verified" in text:
        verified = True
    relationship = str(data.get("relationship") or "").strip().casefold() or None
    if relationship is None and "preexisting" in text:
        relationship = "preexisting"
    elif relationship is None and "new_relationship" in text:
        relationship = "new"
    count_value = data.get("non_accredited_count", 0)
    try:
        non_accredited_count = int(count_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("non_accredited_count must be an integer") from exc
    if non_accredited_count < 0:
        raise ValueError("non_accredited_count cannot be negative")
    return {
        "label": label,
        "public": bool(public),
        "accepting": bool(accepting),
        "accredited": accredited,
        "verified": bool(verified),
        "relationship": relationship,
        "non_accredited_count": non_accredited_count,
    }


def _result(
    allowed: bool,
    rule: str,
    why: str,
    remediation: list[str],
) -> ComplianceCheck:
    return ComplianceCheck(
        allowed=allowed,
        rule=rule,
        why=why,
        remediation=remediation,
        guardrail=capital_guardrail(
            "Have securities counsel document the chosen exemption, bad-actor review, "
            "offeree/purchaser file, disclosures, Form D timing, and every state notice before action."
        ),
    )


def check_solicitation(
    mode: str,
    action: str | Mapping[str, Any],
) -> ComplianceCheck:
    """Block clear 506(b)/(c) violations without blessing the offering."""
    selected_mode = _mode(mode)
    screened = _action_data(action)
    if selected_mode == "506b":
        rule = "Rule 506(b): no general solicitation; purchaser eligibility remains fact-specific"
        if screened["public"]:
            return _result(
                False,
                rule,
                f"BLOCKED: {screened['label']} is general/public solicitation, which Rule 506(b) prohibits.",
                [
                    "Stop the public communication and preserve what was published and when.",
                    "Ask securities counsel whether the offering path can still rely on 506(b) or must change before further offers.",
                    "Use only counsel-approved communications to a documented pre-existing substantive network.",
                ],
            )
        if screened["accepting"] and screened["accredited"] is False:
            if screened["relationship"] != "preexisting":
                return _result(
                    False,
                    rule,
                    "BLOCKED: a non-accredited purchaser without a documented pre-existing substantive relationship fails this conservative 506(b) gate.",
                    [
                        "Do not accept money or a subscription.",
                        "Have counsel determine sophistication and purchaser-representative requirements.",
                        "Prepare the enhanced Rule 502(b) disclosures and financial information required for non-accredited purchasers.",
                    ],
                )
            if screened["non_accredited_count"] >= 35:
                return _result(
                    False,
                    rule,
                    "BLOCKED: the offering has already reached the 35 non-accredited purchaser ceiling supplied to this check.",
                    [
                        "Do not accept this purchaser.",
                        "Have counsel audit the 90-day and integrated-offering purchaser count.",
                    ],
                )
        if screened["accepting"] and screened["accredited"] is None:
            return _result(
                False,
                rule,
                "BLOCKED: purchaser accredited/sophistication status is unknown, so the issuer cannot document a valid 506(b) sale.",
                [
                    "Complete a counsel-approved investor questionnaire and reasonable-belief review.",
                    "If non-accredited, document sophistication, relationship, count, and required disclosures before any sale.",
                ],
            )
        return _result(
            True,
            rule,
            "No clear 506(b) violation was detected from the supplied facts; this is only a preliminary gate, not approval to offer or sell.",
            [
                "Confirm there was no general solicitation and document each offeree relationship.",
                "For accredited purchasers, establish a reasonable belief from facts beyond a checked box alone.",
                "For any non-accredited purchaser, counsel must confirm sophistication, the 35-person limit, and Rule 502(b) disclosures.",
            ],
        )

    rule = "Rule 506(c): general solicitation permitted; every purchaser accredited and reasonably verified"
    if screened["accepting"] and screened["accredited"] is not True:
        return _result(
            False,
            rule,
            "BLOCKED: Rule 506(c) permits sales only to accredited investors; this purchaser is non-accredited or unassessed.",
            [
                "Do not accept the subscription or money.",
                "Confirm accredited status and retain counsel-approved verification evidence before a sale.",
            ],
        )
    if screened["accepting"] and screened["verified"] is not True:
        return _result(
            False,
            rule,
            "BLOCKED: accredited status has not been verified through reasonable steps; self-certification alone does not clear 506(c).",
            [
                "Do not accept the subscription or money.",
                "Use counsel-approved reasonable verification, such as qualifying records or a recent confirmation from an eligible licensed professional.",
            ],
        )
    return _result(
        True,
        rule,
        "No clear 506(c) violation was detected from the supplied facts; public solicitation may be possible, but no sale is approved.",
        [
            "Use only counsel-approved, balanced materials with no material omission or performance guarantee.",
            "Before every sale, document accredited status and reasonable verification for that purchaser.",
        ],
    )


__all__ = ["check_solicitation"]
