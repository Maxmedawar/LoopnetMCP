"""Fail-closed preliminary Regulation D action guardrails."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from cre_mcp.execution.guardrails import capital_guardrail
from cre_mcp.models.capital import ComplianceCheck

GENERAL_SOLICITATION_ACTION = "general_solicitation"
ACCEPT_INVESTOR_ACTION = "accept_investor"
PREPARE_DRAFT_ACTION = "prepare_draft"
PREPARE_FORM_D_ACTION = "prepare_form_d"

# An action can return allowed=True only if its normalized pair appears here and
# then clears the fact-specific gates below. Everything else fails closed.
PERMITTED_ACTION_PAIRS = frozenset(
    {
        ("506b", ACCEPT_INVESTOR_ACTION),
        ("506b", PREPARE_DRAFT_ACTION),
        ("506b", PREPARE_FORM_D_ACTION),
        ("506c", GENERAL_SOLICITATION_ACTION),
        ("506c", ACCEPT_INVESTOR_ACTION),
        ("506c", PREPARE_DRAFT_ACTION),
        ("506c", PREPARE_FORM_D_ACTION),
    }
)

GENERAL_SOLICITATION_ALIASES = frozenset(
    {
        "advertise",
        "advertising",
        "advertise_publicly",
        "general_advertising",
        "general_solicitation",
        "public_advertising",
        "public_solicitation",
        "solicit",
        "solicit_publicly",
    }
)
ACCEPT_INVESTOR_ALIASES = frozenset(
    {
        "accept",
        "accept_funds",
        "accept_investor",
        "accept_money",
        "accept_nonaccredited",
        "accept_subscription",
        "accept_unverified_accredited",
        "close_subscription",
        "first_sale",
        "onboard",
        "onboard_investor",
        "sell_security",
    }
)
ACCEPTANCE_VERBS = frozenset(
    {
        "accept",
        "accepting",
        "close",
        "closing",
        "onboard",
        "onboarding",
        "sell",
        "selling",
    }
)
ACCEPTANCE_NOUNS = frozenset(
    {
        "funds",
        "investment",
        "investor",
        "money",
        "purchaser",
        "sale",
        "security",
        "subscription",
    }
)
ACTION_FILLER_TOKENS = frozenset({"a", "all", "an", "for", "from", "the", "to", "with"})
INVESTOR_FACT_TOKENS = frozenset(
    {
        "accredited",
        "certification",
        "certified",
        "investors",
        "new",
        "non",
        "nonaccredited",
        "pending",
        "self",
        "status",
        "unknown",
        "unverified",
        "verification",
        "verified",
    }
)
PUBLIC_CHANNEL_TOKENS = frozenset(
    {
        "advertise",
        "advertising",
        "email",
        "general",
        "mass",
        "media",
        "newspaper",
        "podcast",
        "public",
        "publicly",
        "radio",
        "seminar",
        "social",
        "solicit",
        "solicitation",
        "soliciting",
        "television",
        "website",
    }
)
UNVERIFIED_MARKERS = (
    "unverified",
    "not_verified",
    "without_verification",
    "pending_verification",
    "verification_pending",
    "self_attested",
    "self_certified",
    "self_certification",
)
UNKNOWN_ACTION_REASON = (
    "BLOCKED: Not explicitly permitted — treat as prohibited until a securities "
    "attorney confirms."
)


def _mode(value: str) -> str:
    normalized = value.strip().casefold().replace("rule", "")
    normalized = normalized.replace("(", "").replace(")", "").replace("-", "")
    normalized = normalized.replace("_", "").replace(" ", "")
    if normalized not in {"506b", "506c"}:
        raise ValueError("mode must be 506b or 506c")
    return normalized


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = _slug(value)
        if normalized in {"true", "yes", "1", "accredited", "verified"}:
            return True
        if normalized in {
            "false",
            "no",
            "0",
            "nonaccredited",
            "non_accredited",
            "unverified",
            "not_verified",
            "unknown",
        }:
            return False if normalized != "unknown" else None
    return None


def _first_bool(data: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if key in data:
            return _optional_bool(data.get(key))
    return None


def _action_kind(normalized: str, tokens: set[str]) -> str | None:
    if normalized in {"prepare_draft", "prepare_private_draft"}:
        return PREPARE_DRAFT_ACTION
    if normalized in {"prepare_form_d", "prepare_form_d_data"}:
        return PREPARE_FORM_D_ACTION
    if normalized in ACCEPT_INVESTOR_ALIASES:
        return ACCEPT_INVESTOR_ACTION
    first_token = normalized.split("_", 1)[0]
    acceptance_vocabulary = (
        ACCEPTANCE_VERBS | ACCEPTANCE_NOUNS | ACTION_FILLER_TOKENS | INVESTOR_FACT_TOKENS
    )
    if (
        first_token in ACCEPTANCE_VERBS
        and tokens <= acceptance_vocabulary
        and (
            tokens.intersection(ACCEPTANCE_NOUNS)
            or tokens.intersection({"accredited", "nonaccredited", "unverified"})
        )
    ):
        return ACCEPT_INVESTOR_ACTION
    if normalized in GENERAL_SOLICITATION_ALIASES:
        return GENERAL_SOLICITATION_ACTION
    solicitation_vocabulary = (
        PUBLIC_CHANNEL_TOKENS | ACTION_FILLER_TOKENS | INVESTOR_FACT_TOKENS
    )
    if (
        first_token in {"advertise", "advertising", "solicit", "soliciting"}
        and tokens <= solicitation_vocabulary
    ):
        return GENERAL_SOLICITATION_ACTION
    return None


def _action_data(action: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(action, Mapping):
        data = dict(action)
        label = str(data.get("action") or data.get("type") or "").strip()
    else:
        data = {}
        label = str(action).strip()
    if not label:
        raise ValueError("action cannot be blank")

    normalized = _slug(label)
    tokens = set(filter(None, normalized.split("_")))
    action_kind = _action_kind(normalized, tokens)
    data_text = "_".join(_slug(value) for value in data.values())
    text = f"{normalized}_{data_text}"

    accredited = _first_bool(
        data,
        "accredited",
        "all_investors_accredited",
        "all_purchasers_accredited",
    )
    if accredited is None and any(
        marker in text
        for marker in ("nonaccredited", "non_accredited", "not_accredited")
    ):
        accredited = False
    elif accredited is None and "accredited" in text:
        accredited = True

    verified = _first_bool(
        data,
        "accreditation_verified",
        "verified",
        "all_accreditation_verified",
        "all_investors_verified",
        "all_purchasers_verified",
    )
    if verified is None and any(marker in text for marker in UNVERIFIED_MARKERS):
        verified = False
    elif verified is None and "verified" in text:
        verified = True

    relationship = _slug(data.get("relationship") or "") or None
    if relationship in {
        "existing",
        "pre_existing",
        "pre_existing_substantive",
        "preexisting_substantive",
    }:
        relationship = "preexisting"
    if relationship is None and any(
        marker in text
        for marker in ("preexisting", "pre_existing", "preexisting_substantive")
    ):
        relationship = "preexisting"
    elif relationship is None and any(
        marker in text for marker in ("new_relationship", "no_relationship")
    ):
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
        "action_kind": action_kind,
        "accredited": accredited,
        "verified": verified,
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
            "Have a securities attorney confirm this exact action and document the chosen "
            "exemption, bad-actor review, offeree/purchaser file, disclosures, Form D timing, "
            "and every state notice before action."
        ),
    )


def _default_deny(rule: str) -> ComplianceCheck:
    return _result(
        False,
        rule,
        UNKNOWN_ACTION_REASON,
        [
            "Do not solicit, onboard, accept a subscription, or accept money based on this result.",
            "Give the exact proposed communication or transaction to a securities attorney for written clearance.",
        ],
    )


def _allow_draft(rule: str, action_kind: str) -> ComplianceCheck:
    document = "Form D intake data" if action_kind == PREPARE_FORM_D_ACTION else "attorney draft"
    return _result(
        True,
        rule,
        f"Explicitly recognized preparation of {document} is permitted for counsel review; it does not authorize circulation, solicitation, a sale, or accepting money.",
        [
            "Keep the document stamped DRAFT and do not circulate it as offering material.",
            "Have securities counsel review and approve every fact, omission, exemption condition, filing, and use before further action.",
        ],
    )


def check_solicitation(
    mode: str,
    action: str | Mapping[str, Any],
) -> ComplianceCheck:
    """Fail closed unless a recognized Reg D action clears every supplied-fact gate."""
    selected_mode = _mode(mode)
    screened = _action_data(action)
    action_kind = screened["action_kind"]

    if selected_mode == "506b":
        rule = "Rule 506(b): no general solicitation; purchaser eligibility remains fact-specific"
        if action_kind == GENERAL_SOLICITATION_ACTION:
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
        if (selected_mode, action_kind) not in PERMITTED_ACTION_PAIRS:
            return _default_deny(rule)
        if action_kind in {PREPARE_DRAFT_ACTION, PREPARE_FORM_D_ACTION}:
            return _allow_draft(rule, action_kind)
        if screened["accredited"] is False:
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
        if screened["accredited"] is None:
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
            "Explicitly recognized 506(b) purchaser action cleared the supplied preliminary facts; this is not approval to offer, sell, or accept money.",
            [
                "Confirm there was no general solicitation and document the offeree relationship.",
                "For accredited purchasers, establish a reasonable belief from facts beyond a checked box alone.",
                "For any non-accredited purchaser, counsel must confirm sophistication, the 35-person limit, and Rule 502(b) disclosures.",
            ],
        )

    rule = "Rule 506(c): general solicitation permitted; every purchaser accredited and reasonably verified"
    if (selected_mode, action_kind) not in PERMITTED_ACTION_PAIRS:
        return _default_deny(rule)
    if action_kind in {PREPARE_DRAFT_ACTION, PREPARE_FORM_D_ACTION}:
        return _allow_draft(rule, action_kind)
    if action_kind == ACCEPT_INVESTOR_ACTION:
        if screened["accredited"] is not True:
            return _result(
                False,
                rule,
                "BLOCKED: Rule 506(c) permits sales only to accredited investors; this purchaser is non-accredited or unassessed.",
                [
                    "Do not accept the subscription or money.",
                    "Confirm accredited status and retain counsel-approved verification evidence before a sale.",
                ],
            )
        if screened["verified"] is not True:
            return _result(
                False,
                rule,
                "BLOCKED: accredited status has not been verified through reasonable steps; self-certification alone does not clear 506(c).",
                [
                    "Do not onboard the purchaser or accept the subscription or money.",
                    "Use counsel-approved reasonable verification, such as qualifying records or a recent confirmation from an eligible licensed professional.",
                ],
            )
        return _result(
            True,
            rule,
            "Explicitly recognized 506(c) purchaser action cleared supplied accredited-and-verified facts; this is not approval to sell or accept money.",
            [
                "Retain the counsel-approved evidence supporting reasonable verification for this purchaser.",
                "Complete bad-actor, disclosure, Form D, state notice, and subscription review before any sale.",
            ],
        )
    return _result(
        True,
        rule,
        "Explicitly recognized Rule 506(c) general solicitation may be possible, but no purchaser or sale is approved.",
        [
            "Use only counsel-approved, balanced materials with no material omission or performance guarantee.",
            "Before every sale, document accredited status and reasonable verification for that purchaser.",
        ],
    )


__all__ = ["PERMITTED_ACTION_PAIRS", "UNKNOWN_ACTION_REASON", "check_solicitation"]
