"""Deterministic, cited extraction of closing-related contract obligations.

This is a targeted legal-language screen, not a substitute for counsel.  It
returns only clauses found in the supplied text, preserves the quoted source,
and reports silence as missing rather than inferring that an obligation exists.
"""

from __future__ import annotations

import re
from typing import Any


_KINDS = {"psa", "loan", "jv"}
_CATEGORIES = (
    "representations_and_warranties",
    "covenants",
    "conditions_precedent",
    "post_closing_obligations",
)

_REPRESENTATION = re.compile(
    r"\b(?:represents?\s+and\s+warrants?|represents?|warrants?|"
    r"representations?\s+and\s+warrant(?:y|ies))\b",
    re.IGNORECASE,
)
_COVENANT = re.compile(
    r"\b(?:covenants?|undertakes?|agrees?)\b|\bshall\b",
    re.IGNORECASE,
)
_CONDITION = re.compile(
    r"\b(?:condition(?:s)?\s+precedent|condition(?:s)?\s+(?:to|of)\s+closing|"
    r"condition(?:s)?\s+to\s+(?:the\s+)?(?:obligation|funding|advance)|"
    r"conditioned\s+(?:on|upon)|conditional\s+upon|contingent\s+(?:on|upon)|"
    r"subject\s+to\s+(?:the\s+)?satisfaction|as\s+a\s+condition\s+to)\b",
    re.IGNORECASE,
)
_POST_CLOSING = re.compile(
    r"\b(?:post[- ]closing|after\s+(?:the\s+)?closing|following\s+(?:the\s+)?closing|"
    r"subsequent\s+to\s+(?:the\s+)?closing|from\s+and\s+after\s+(?:the\s+)?closing)\b",
    re.IGNORECASE,
)
_SURVIVAL = re.compile(
    r"\b(?:shall\s+)?surviv(?:e|es|ing|al)\b[^.;!?]{0,140}",
    re.IGNORECASE,
)
_DEADLINE = re.compile(
    r"\b(?:on\s+or\s+before|no\s+later\s+than|not\s+less\s+than|at\s+least|"
    r"within|prior\s+to|before|after|following|by|upon)\b\s+[^,;.!?]{1,100}",
    re.IGNORECASE,
)
_PARTY = re.compile(
    r"\b(Seller|Buyer|Purchaser|Borrower|Lender|Administrative\s+Agent|Agent|"
    r"Guarantor|Company|Manager|Managing\s+Member|Member|Sponsor|Investor|"
    r"Joint\s+Venture|JV|Tenant|Landlord)\b",
    re.IGNORECASE,
)
_POSSESSIVE_PARTY = re.compile(
    r"\b(Seller|Buyer|Purchaser|Borrower|Lender|Guarantor|Company|Manager|"
    r"Managing\s+Member|Member|Sponsor|Investor|Tenant|Landlord)(?:'s|s')\s+"
    r"(?:obligation|condition|representation|warrant)",
    re.IGNORECASE,
)
_SECTION = re.compile(
    r"\b(?:Section|Article)\s+[A-Za-z0-9][A-Za-z0-9.()_-]*|§\s*[A-Za-z0-9.()_-]+",
    re.IGNORECASE,
)


def _clauses(text: str) -> list[tuple[str, int, int]]:
    """Return source-preserving sentence/semicolon clauses and offsets."""

    clauses: list[tuple[str, int, int]] = []
    # Legal prose commonly uses semicolons as operative clause boundaries.  A
    # period between digits is retained so dollar amounts and section numbers do
    # not create misleading excerpts.
    pattern = re.compile(r".*?(?:;|[!?]|(?<!\d)\.(?!\d)|$)", re.DOTALL)
    for match in pattern.finditer(text):
        raw = match.group(0)
        if not raw:
            continue
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        quote = raw.strip()
        if quote:
            clauses.append((quote, match.start() + leading, match.start() + trailing))
    return clauses


def _locator(text: str, start: int) -> str:
    sections = [match for match in _SECTION.finditer(text, 0, start + 1)]
    if sections:
        return sections[-1].group(0).strip()
    return f"line {text.count(chr(10), 0, start) + 1}"


def _party_for(quote: str, trigger: re.Pattern[str]) -> str | None:
    trigger_match = trigger.search(quote)
    prefix = quote[: trigger_match.start()] if trigger_match else quote
    parties = list(_PARTY.finditer(prefix))
    if parties:
        return parties[-1].group(1)
    possessive = _POSSESSIVE_PARTY.search(quote)
    return possessive.group(1) if possessive else None


def _deadline_for(quote: str) -> str | None:
    match = _DEADLINE.search(quote)
    return match.group(0).strip() if match else None


def _survival_for(quote: str) -> str | None:
    match = _SURVIVAL.search(quote)
    return match.group(0).strip() if match else None


def _obligation_text(quote: str, trigger: re.Pattern[str]) -> str:
    match = trigger.search(quote)
    if not match:
        return quote
    operative = quote[match.end() :].strip(" :,-")
    return operative or quote


def _item(
    *,
    category: str,
    quote: str,
    locator: str,
    party: str | None,
    deadline_rule: str | None,
    survival: str | None,
    trigger: re.Pattern[str],
) -> dict[str, Any]:
    return {
        "category": category,
        "obligation": _obligation_text(quote, trigger),
        "quote": quote,
        "locator": locator,
        "party": party,
        "deadline_rule": deadline_rule,
        "survival": survival,
    }


def extract_contract_obligations(text: str, kind: str) -> dict[str, Any]:
    """Extract cited obligations from a PSA, loan agreement, or JV agreement.

    The extractor deliberately uses a finite legal-language vocabulary. Unknown
    party, deadline, and survival terms remain ``None``; an absent category is
    listed in ``missing``.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    normalized_kind = str(kind).strip().casefold()
    if normalized_kind not in _KINDS:
        raise ValueError("kind must be one of: psa, loan, jv")

    result: dict[str, Any] = {category: [] for category in _CATEGORIES}
    clauses = _clauses(text)

    # Standalone survival provisions are applied only when their language names
    # representations/warranties; this avoids inventing survival for unrelated
    # indemnities or covenants.
    survival_rules: list[tuple[str, str | None]] = []
    for quote, _, _ in clauses:
        if _SURVIVAL.search(quote) and re.search(
            r"\brepresentations?|\bwarrant(?:y|ies)", quote, re.IGNORECASE
        ):
            survival_rules.append((_survival_for(quote) or quote, _party_for(quote, _REPRESENTATION)))

    for quote, start, _ in clauses:
        locator = _locator(text, start)
        deadline = _deadline_for(quote)

        # A clause whose operative function is only to state survival enriches
        # the representation it references instead of becoming a duplicate rep.
        is_survival_only = bool(
            _SURVIVAL.search(quote)
            and re.search(r"\brepresentations?|\bwarrant(?:y|ies)", quote, re.IGNORECASE)
            and not re.search(r"\brepresents?\s+(?:and\s+warrants?\s+)?that\b", quote, re.IGNORECASE)
        )
        if _REPRESENTATION.search(quote) and not is_survival_only:
            party = _party_for(quote, _REPRESENTATION)
            survival = _survival_for(quote)
            if survival is None:
                applicable = [rule for rule, rule_party in survival_rules if rule_party in (None, party)]
                survival = applicable[0] if applicable else None
            result["representations_and_warranties"].append(
                _item(
                    category="representations_and_warranties",
                    quote=quote,
                    locator=locator,
                    party=party,
                    deadline_rule=deadline,
                    survival=survival,
                    trigger=_REPRESENTATION,
                )
            )

        if _CONDITION.search(quote):
            result["conditions_precedent"].append(
                _item(
                    category="conditions_precedent",
                    quote=quote,
                    locator=locator,
                    party=_party_for(quote, _CONDITION),
                    deadline_rule=deadline,
                    survival=_survival_for(quote),
                    trigger=_CONDITION,
                )
            )
        elif _POST_CLOSING.search(quote) and _COVENANT.search(quote):
            result["post_closing_obligations"].append(
                _item(
                    category="post_closing_obligations",
                    quote=quote,
                    locator=locator,
                    party=_party_for(quote, _COVENANT),
                    deadline_rule=deadline,
                    survival=_survival_for(quote),
                    trigger=_COVENANT,
                )
            )
        elif _COVENANT.search(quote) and not is_survival_only and not _REPRESENTATION.search(quote):
            result["covenants"].append(
                _item(
                    category="covenants",
                    quote=quote,
                    locator=locator,
                    party=_party_for(quote, _COVENANT),
                    deadline_rule=deadline,
                    survival=_survival_for(quote),
                    trigger=_COVENANT,
                )
            )

    result.update(
        {
            "kind": normalized_kind,
            "missing": [category for category in _CATEGORIES if not result[category]],
            "counsel_review_required": True,
            "counsel_flag": (
                "COUNSEL REVIEW REQUIRED: deterministic clause extraction is not a legal "
                "opinion; confirm scope, defined terms, exceptions, remedies, and enforceability."
            ),
        }
    )
    return result


__all__ = ["extract_contract_obligations"]
