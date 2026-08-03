"""Targeted, honest screening for drift from structured agreed terms.

This module deliberately does not claim to parse an entire PSA, lease, loan
agreement, or JV agreement.  It searches for a small set of business terms by
label, preserves the exact draft excerpt it relied on, and treats absence as a
review item rather than proof that a provision has been omitted intentionally.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any


_MONEY = re.compile(
    r"\$?\s*\d(?:[\d,]*\d)?(?:\.\d+)?\s*(?:million|thousand|[mk])?\b",
    re.IGNORECASE,
)
_DAYS = re.compile(
    r"\b\d{1,4}\s*\)?\s*(?:business|calendar)?\s*days?\b", re.IGNORECASE
)

_TERM_LABELS: dict[str, tuple[str, ...]] = {
    "price": ("purchase price", "total consideration", "sale price"),
    "purchase_price": ("purchase price", "total consideration", "sale price"),
    "deposit": ("earnest money", "good faith deposit", "deposit", "emd"),
    "earnest_money": ("earnest money", "good faith deposit", "deposit", "emd"),
    "dd_days": (
        "due diligence period",
        "due diligence",
        "inspection period",
        "feasibility period",
    ),
    "due_diligence_days": (
        "due diligence period",
        "due diligence",
        "inspection period",
        "feasibility period",
    ),
    "closing_days": ("closing period", "closing date", "closing"),
}

_CONTINGENCY_ALIASES: dict[str, tuple[str, ...]] = {
    "financing": ("financing", "loan commitment", "mortgage contingency"),
    "finance": ("financing", "loan commitment", "mortgage contingency"),
    "inspection": ("inspection", "due diligence", "feasibility"),
    "due diligence": ("due diligence", "inspection", "feasibility"),
    "appraisal": ("appraisal", "appraised value"),
    "title": ("title", "title commitment", "title objection"),
    "environmental": ("environmental", "phase i", "hazardous materials"),
    "zoning": ("zoning", "land use", "entitlement"),
}

_PROTECTIVE_LANGUAGE = re.compile(
    r"\b(contingenc(?:y|ies)|contingent|condition(?:ed)?|subject\s+to|"
    r"(?:may|right\s+to)\s+(?:terminate|cancel)|satisf(?:y|ied|actory)|"
    r"objection|due\s+diligence|inspection\s+period)\b",
    re.IGNORECASE,
)
_WAIVER_LANGUAGE = re.compile(
    r"\b(waiv(?:e|ed|er|es|ing)|unconditional|non[- ]?contingent|"
    r"not\s+(?:contingent|conditioned)\s+(?:on|upon)|not\s+subject\s+to|"
    r"no\s+(?:financing|inspection|appraisal|title|environmental|zoning)"
    r"\s+contingenc(?:y|ies)|"
    r"no\s+right\s+to\s+(?:terminate|cancel)[^.]{0,100}|"
    r"(?:financing|inspection|appraisal|title|environmental|zoning)[^.]{0,100}"
    r"(?:shall|will|does|is|may)\s+not\s+(?:be\s+)?(?:a\s+)?"
    r"(?:condition|contingent|contingenc(?:y|ies)|permit|allow)|"
    r"without\s+(?:an?\s+|any\s+)?(?:financing|inspection|appraisal|title|"
    r"environmental|zoning)[^.]{0,50}(?:contingenc|condition|protection))\b",
    re.IGNORECASE,
)


def _agreed_quote(term: str, value: Any) -> str:
    """Quote the structured v1 representation without inventing LOI prose."""

    return json.dumps({term: value}, sort_keys=True, default=str, ensure_ascii=False)


def _clause_candidates(text: str, labels: Sequence[str]) -> list[tuple[str, int]]:
    """Return exact sentence/line excerpts containing a targeted label."""

    candidates: list[tuple[str, int]] = []
    # A period between digits is part of a decimal, not a clause boundary. Newlines
    # remain inside an excerpt because legal prose is commonly hard-wrapped mid-sentence.
    for match in re.finditer(r".*?(?:\.(?!\d)|$)", text, re.DOTALL):
        raw = match.group(0)
        clause = raw.strip()
        if not clause:
            continue
        lowered = clause.casefold()
        positions = [lowered.find(label.casefold()) for label in labels]
        positions = [position for position in positions if position >= 0]
        if positions:
            candidates.append((clause, min(positions)))
    return candidates


def _number(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, Mapping):
        for key in ("amount", "value", "days"):
            if key in raw:
                return _number(raw[key])
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if math.isfinite(value) else None
    text = str(raw).strip().casefold().replace("$", "").replace(",", "")
    multiplier = 1.0
    if text.endswith("million"):
        multiplier, text = 1_000_000.0, text[: -len("million")]
    elif text.endswith("thousand"):
        multiplier, text = 1_000.0, text[: -len("thousand")]
    elif text.endswith("m"):
        multiplier, text = 1_000_000.0, text[:-1]
    elif text.endswith("k"):
        multiplier, text = 1_000.0, text[:-1]
    text = re.sub(
        r"\s*\)?\s*(?:business|calendar)?\s*days?\s*$", "", text
    ).strip()
    try:
        value = float(text) * multiplier
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _nearest_value(
    candidates: Sequence[tuple[str, int]], token_pattern: re.Pattern[str]
) -> tuple[str, float] | None:
    ranked: list[tuple[int, int, int, int, str, float]] = []
    for order, (clause, label_position) in enumerate(candidates):
        for token in token_pattern.finditer(clause):
            value = _number(token.group(0))
            if value is None:
                continue
            distance = min(abs(token.start() - label_position), abs(token.end() - label_position))
            raw_token = token.group(0).casefold()
            currency_rank = (
                0
                if token_pattern is _MONEY
                and (
                    "$" in raw_token
                    or "," in raw_token
                    or re.search(r"\b(?:million|thousand|[mk])\b", raw_token)
                )
                else 1
            )
            after_label_rank = 0 if token.start() >= label_position else 1
            ranked.append(
                (currency_rank, after_label_rank, distance, order, clause, value)
            )
    if not ranked:
        return None
    _, _, _, _, clause, value = min(
        ranked, key=lambda item: (item[0], item[1], item[2], item[3])
    )
    return clause, value


def _generic_result(term: str, agreed: Any, draft_text: str) -> dict[str, Any]:
    labels = _TERM_LABELS.get(term, (term.replace("_", " "),))
    candidates = _clause_candidates(draft_text, labels)
    agreed_numeric = _number(agreed)
    token_pattern = _DAYS if term.endswith("_days") else _MONEY
    found = _nearest_value(candidates, token_pattern) if agreed_numeric is not None else None

    if agreed_numeric is not None:
        if found is None:
            return _silent(term, agreed)
        draft_quote, draft_value = found
        matched = math.isclose(agreed_numeric, draft_value, rel_tol=0.0, abs_tol=0.01)
    else:
        if not candidates:
            return _silent(term, agreed)
        draft_quote = candidates[0][0]
        normalized_agreed = str(agreed).strip().casefold()
        matched = bool(normalized_agreed and normalized_agreed in draft_quote.casefold())
        draft_value = agreed if matched else "different_or_not_expressly_located"

    return {
        "term": term,
        "status": "matched" if matched else "changed",
        "agreed_value": agreed,
        "draft_value": draft_value,
        "agreed_quote": _agreed_quote(term, agreed),
        "agreed_quote_source": "structured_agreed_terms_v1",
        "draft_quote": draft_quote,
        "severity": "none" if matched else _changed_severity(term),
        "review_note": (
            "Targeted label and value matched; counsel should still confirm operative effect."
            if matched
            else "Targeted draft value differs from the structured agreed value."
        ),
    }


def _changed_severity(term: str) -> str:
    if term.startswith("contingency:"):
        return "fatal"
    if term in {
        "price",
        "purchase_price",
        "deposit",
        "earnest_money",
        "dd_days",
        "due_diligence_days",
        "closing_days",
    }:
        return "material"
    return "warning"


def _silent(term: str, agreed: Any, *, severity: str | None = None) -> dict[str, Any]:
    return {
        "term": term,
        "status": "silent",
        "agreed_value": agreed,
        "draft_value": None,
        "agreed_quote": _agreed_quote(term, agreed),
        "agreed_quote_source": "structured_agreed_terms_v1",
        "draft_quote": None,
        "draft_evidence": "No targeted term match was found in the supplied draft text.",
        "severity": severity or _changed_severity(term),
        "review_note": (
            "Silence is not harmless: integration language or the missing operative clause "
            "can eliminate the agreed business protection. Route to counsel."
        ),
    }


def _contingency_result(contingency: Any, draft_text: str) -> dict[str, Any]:
    agreed = str(contingency).strip()
    normalized = agreed.casefold()
    term = f"contingency:{normalized or 'blank'}"
    labels = _CONTINGENCY_ALIASES.get(normalized, (normalized,))
    labels = tuple(label for label in labels if label)
    candidates = _clause_candidates(draft_text, labels)
    if not candidates:
        return _silent(term, agreed, severity="fatal")

    # Prefer excerpts with operative protection/waiver language over incidental mentions.
    draft_quote = next(
        (
            clause
            for clause, _ in candidates
            if _PROTECTIVE_LANGUAGE.search(clause) or _WAIVER_LANGUAGE.search(clause)
        ),
        candidates[0][0],
    )
    waived = bool(_WAIVER_LANGUAGE.search(draft_quote))
    protected = bool(_PROTECTIVE_LANGUAGE.search(draft_quote)) and not waived
    status = "matched" if protected else "changed"
    return {
        "term": term,
        "status": status,
        "agreed_value": agreed,
        "draft_value": agreed if protected else (
            "expressly_waived" if waived else "mentioned_without_express_protection"
        ),
        "agreed_quote": _agreed_quote("contingencies", [agreed]),
        "agreed_quote_source": "structured_agreed_terms_v1",
        "draft_quote": draft_quote,
        "severity": "none" if protected else "fatal",
        "review_note": (
            "Targeted excerpt contains operative protective language."
            if protected
            else "The draft waives or does not expressly preserve this agreed contingency."
        ),
    }


def detect_term_drift(
    agreed_terms: Mapping[str, Any], draft_text: str
) -> dict[str, Any]:
    """Screen structured LOI terms against targeted excerpts in a later draft.

    ``agreed_terms`` is the structured v1 source.  Its JSON fragment is returned
    as the agreed-version quote; the function never fabricates original LOI prose.
    ``draft_quote`` is always an exact excerpt of ``draft_text`` when a match was
    found.  This is a screening aid for counsel, not a legal interpretation.
    """

    if not isinstance(agreed_terms, Mapping):
        raise TypeError("agreed_terms must be a mapping of structured LOI terms")
    if not isinstance(draft_text, str) or not draft_text.strip():
        raise ValueError("draft_text must be nonblank text")

    term_results: list[dict[str, Any]] = []
    for term, agreed in agreed_terms.items():
        if term == "contingencies":
            if isinstance(agreed, str) or not isinstance(agreed, Sequence):
                raise TypeError("contingencies must be a list of structured terms")
            term_results.extend(_contingency_result(value, draft_text) for value in agreed)
        else:
            term_results.append(_generic_result(str(term), agreed, draft_text))

    counts = {status: 0 for status in ("matched", "changed", "silent")}
    for result in term_results:
        counts[result["status"]] += 1
    highest_severity = next(
        (
            severity
            for severity in ("fatal", "material", "warning", "none")
            if any(result["severity"] == severity for result in term_results)
        ),
        "none",
    )
    return {
        "input_contract": "structured_agreed_terms_v1",
        "term_results": term_results,
        "terms": term_results,
        "summary": {**counts, "highest_severity": highest_severity},
        "counsel_routing_note": (
            "Route every changed or silent term to transaction counsel before signature; "
            "a silent contingency is treated as fatal until counsel confirms the operative text."
        ),
        "scope_limit": (
            "Targeted business-term pattern screen only. Full-PSA/lease/loan/JV parsing, "
            "defined-term resolution, cross-reference analysis, party/beneficiary scope, "
            "and legal conclusions are not attempted."
        ),
    }


__all__ = ["detect_term_drift"]
