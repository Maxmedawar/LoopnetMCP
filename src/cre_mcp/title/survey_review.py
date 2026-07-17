"""Deterministic survey-to-title exception screening.

The output is an issue-routing aid only.  It does not determine ownership,
priority, insurability, or any other legal conclusion.
"""

from __future__ import annotations

import re
from typing import Any

from cre_mcp.truth.sanitize import sanitize_text


_ALLOWED_SURVEY_TYPES = {"encroachment", "setback", "access", "utility", "flood"}
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "property",
    "the",
    "to",
    "with",
}
_TOKEN_EQUIVALENTS = {
    "easterly": "east",
    "eastern": "east",
    "westerly": "west",
    "western": "west",
    "northerly": "north",
    "northern": "north",
    "southerly": "south",
    "southern": "south",
    "utilities": "utility",
    "ingress": "access",
    "egress": "access",
    "rightofway": "access",
    "row": "access",
    "feet": "foot",
    "ft": "foot",
}
_DIRECTIONS = {"north", "south", "east", "west"}


def _citation(quote: str, locator: str) -> dict[str, str]:
    return {"quote": quote, "locator": locator}


def _exception_text(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if not isinstance(item, dict):
        return None
    for key in ("text", "description", "quote", "raw_text", "exception"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    citation = item.get("citation")
    if isinstance(citation, dict):
        quote = citation.get("quote")
        if isinstance(quote, str) and quote.strip():
            return quote.strip()
    citations = item.get("citations")
    if isinstance(citations, list):
        for entry in citations:
            if isinstance(entry, dict) and isinstance(entry.get("quote"), str):
                if entry["quote"].strip():
                    return entry["quote"].strip()
    return None


def _exception_locator(item: Any, index: int) -> str:
    fallback = f"title_exceptions[{index}]"
    if not isinstance(item, dict):
        return fallback
    locator = item.get("locator")
    if isinstance(locator, str) and locator.strip():
        return locator.strip()
    citation = item.get("citation")
    if isinstance(citation, dict) and isinstance(citation.get("locator"), str):
        return citation["locator"].strip() or fallback
    citations = item.get("citations")
    if isinstance(citations, list):
        for entry in citations:
            if isinstance(entry, dict) and isinstance(entry.get("locator"), str):
                if entry["locator"].strip():
                    return entry["locator"].strip()
    return fallback


def _extract_exception_list(value: Any) -> list[Any] | None:
    """Accept a direct list or the common shapes emitted by commitment parsers."""
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return None
    for key in (
        "schedule_b_ii_exceptions",
        "schedule_b_ii",
        "exceptions",
        "title_exceptions",
    ):
        candidate = value.get(key)
        if isinstance(candidate, list):
            return candidate
        if isinstance(candidate, dict):
            for nested_key in ("exceptions", "items"):
                nested = candidate.get(nested_key)
                if isinstance(nested, list):
                    return nested
    schedule_b = value.get("schedule_b")
    if isinstance(schedule_b, dict):
        for key in ("ii", "schedule_b_ii", "exceptions"):
            candidate = schedule_b.get(key)
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, dict) and isinstance(candidate.get("items"), list):
                return candidate["items"]
    return None


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[a-z0-9]+", text.lower().replace("right-of-way", "rightofway"))
    normalized = {_TOKEN_EQUIVALENTS.get(token, token) for token in raw}
    return {token for token in normalized if token not in _STOP_WORDS and len(token) > 1}


def _document_references(text: str) -> set[str]:
    return {
        match.group(1).replace("-", "").lower()
        for match in re.finditer(
            r"(?:instrument|document|recording|rec(?:orded)?)[\s#:.-]*([a-z0-9-]{4,})",
            text,
            re.IGNORECASE,
        )
    }


def _exception_kind(item: Any, text: str) -> str | None:
    if isinstance(item, dict):
        for key in ("classification", "category", "kind", "type"):
            value = item.get(key)
            if isinstance(value, str):
                candidate = value.strip().lower().replace("_", " ")
                if candidate:
                    if "encroach" in candidate:
                        return "encroachment"
                    if "setback" in candidate:
                        return "setback"
                    if "access" in candidate or "easement" in candidate:
                        if "utility" not in candidate:
                            return "access"
                    if "utility" in candidate:
                        return "utility"
                    if "flood" in candidate:
                        return "flood"
    lowered = text.lower()
    if "encroach" in lowered:
        return "encroachment"
    if "setback" in lowered or "building line" in lowered:
        return "setback"
    if "utility" in lowered:
        return "utility"
    if "flood" in lowered:
        return "flood"
    if any(term in lowered for term in ("access", "ingress", "egress", "right-of-way")):
        return "access"
    return None


def _match_score(
    survey_type: str,
    survey_text: str,
    exception: Any,
    exception_text: str,
) -> tuple[int, str | None]:
    survey_refs = _document_references(survey_text)
    exception_refs = _document_references(exception_text)
    common_refs = survey_refs & exception_refs
    if common_refs:
        return 100 + len(common_refs), "same recorded-document reference"

    survey_tokens = _tokens(survey_text)
    exception_tokens = _tokens(exception_text)
    shared = survey_tokens & exception_tokens
    if not shared:
        return 0, None

    exception_kind = _exception_kind(exception, exception_text)
    kind_match = exception_kind == survey_type
    direction_match = bool((survey_tokens & _DIRECTIONS) & (exception_tokens & _DIRECTIONS))
    survey_numbers = {token for token in survey_tokens if token.isdigit()}
    exception_numbers = {token for token in exception_tokens if token.isdigit()}
    number_match = bool(survey_numbers & exception_numbers)

    # Require a matter-type match plus one identifying detail, or substantial
    # textual overlap.  This avoids matching every item merely on "easement."
    identifying_shared = shared - {"easement", "line", "boundary", "foot"}
    substantial_overlap = len(identifying_shared) >= 2
    if not substantial_overlap and not (kind_match and (direction_match or number_match)):
        return 0, None
    score = len(shared) * 5 + len(identifying_shared) * 3
    if kind_match:
        score += 20
    if direction_match:
        score += 6
    if number_match:
        score += 6
    basis = "matter type and shared details" if kind_match else "shared descriptive details"
    return score, basis


def _encroachment_convention(description: str, direction: str | None) -> tuple[str, str]:
    text = f"{description} {direction or ''}".lower()
    if any(term in text for term in ("blocks access", "blocks ingress", "no legal access")):
        return "fatal", "screening convention: encroachment described as blocking site access"
    if any(term in text for term in ("building", "structure", "foundation", "building pad")):
        return "high", "screening convention: building/structure or building-pad encroachment"
    if any(term in text for term in ("fence", "landscap", "hedge", "minor")):
        return "low", "screening convention: fence/landscaping or expressly minor encroachment"
    if any(term in text for term in ("onto", "over boundary", "across boundary", "offsite", "off-site")):
        return "high", "screening convention: boundary-crossing encroachment"
    return "medium", "screening convention: encroachment extent is not established"


def _survey_severity(item: dict[str, Any], site_plan_intent: str | None) -> tuple[str, str]:
    survey_type = item["type"]
    description = item["description"]
    if survey_type == "encroachment":
        severity, reason = _encroachment_convention(description, item.get("direction"))
    elif survey_type == "access":
        severity, reason = "high", "screening convention: access matters can affect intended site use"
    elif survey_type in {"setback", "flood"}:
        severity, reason = "medium", f"screening convention: {survey_type} matter requires professional review"
    else:
        severity, reason = "low", "screening convention: utility matter with no stated site-plan conflict"

    if isinstance(site_plan_intent, str) and site_plan_intent.strip():
        intent_tokens = _tokens(site_plan_intent)
        item_tokens = _tokens(description)
        if len(intent_tokens & item_tokens) >= 2 and severity in {"low", "medium"}:
            return "high", "screening convention: description overlaps stated site-plan intent"
    return severity, reason


def _issue(
    *,
    code: str,
    severity: str,
    summary: str,
    who: list[str],
    what_to_ask: str,
    impact: str,
    citations: list[dict[str, str]],
    convention: str,
) -> dict[str, Any]:
    return {
        "issue_code": code,
        "severity": severity,
        "summary": summary,
        "who": who,
        "what_to_ask": what_to_ask,
        "deal_impact_if_unresolved": impact,
        "citations": citations,
        "screening_convention": convention,
        "legal_conclusion": None,
    }


def _survey_vs_title(
    survey_items: list[dict[str, Any]],
    title_exceptions: list[Any] | dict[str, Any],
    site_plan_intent: str | None = None,
) -> dict[str, Any]:
    """Reconcile reported survey matters with title exceptions.

    Matching is a deterministic text-screening convention, not a conclusion
    that an exception legally covers a survey condition.
    """
    if not isinstance(survey_items, list):
        return {"error": "survey_items must be a list"}
    exceptions = _extract_exception_list(title_exceptions)
    if exceptions is None:
        return {"error": "title_exceptions must be a list or contain an exception list"}
    if site_plan_intent is not None and not isinstance(site_plan_intent, str):
        return {"error": "site_plan_intent must be a string or null"}

    redaction_count = 0
    sanitized_intent: str | None = None
    if isinstance(site_plan_intent, str):
        intent_result = sanitize_text(site_plan_intent)
        redaction_count += intent_result.redactions
        sanitized_intent = intent_result.text.strip() or None

    normalized_survey: list[dict[str, Any]] = []
    for index, item in enumerate(survey_items):
        if not isinstance(item, dict):
            return {"error": f"survey_items[{index}] must be an object"}
        survey_type = item.get("type")
        description = item.get("description")
        direction = item.get("direction")
        if not isinstance(survey_type, str) or survey_type.lower() not in _ALLOWED_SURVEY_TYPES:
            return {
                "error": (
                    f"survey_items[{index}].type must be one of: "
                    + ", ".join(sorted(_ALLOWED_SURVEY_TYPES))
                )
            }
        if not isinstance(description, str) or not description.strip():
            return {"error": f"survey_items[{index}].description must be a non-empty string"}
        if direction is not None and not isinstance(direction, str):
            return {"error": f"survey_items[{index}].direction must be a string or null"}
        description_result = sanitize_text(description)
        redaction_count += description_result.redactions
        sanitized_description = description_result.text.strip()
        if not sanitized_description:
            return {"error": f"survey_items[{index}].description is empty after sanitization"}
        sanitized_direction = None
        if isinstance(direction, str) and direction.strip():
            direction_result = sanitize_text(direction)
            redaction_count += direction_result.redactions
            sanitized_direction = direction_result.text.strip() or None
        normalized_survey.append(
            {
                "type": survey_type.lower(),
                "description": sanitized_description,
                "direction": sanitized_direction,
                "source_index": index,
            }
        )

    normalized_exceptions: list[dict[str, Any]] = []
    for index, item in enumerate(exceptions):
        text = _exception_text(item)
        if text is None:
            return {"error": f"title_exceptions[{index}] must contain non-empty exception text"}
        text_result = sanitize_text(text)
        redaction_count += text_result.redactions
        sanitized_text = text_result.text.strip()
        if not sanitized_text:
            return {"error": f"title_exceptions[{index}] is empty after sanitization"}
        normalized_exceptions.append(
            {
                "text": sanitized_text,
                "locator": _exception_locator(item, index),
                "source_index": index,
                "raw": item,
            }
        )

    candidates: list[tuple[int, int, int, str]] = []
    for survey_index, survey_item in enumerate(normalized_survey):
        survey_text = " ".join(
            part
            for part in (
                survey_item["type"],
                survey_item["description"],
                survey_item["direction"],
            )
            if part
        )
        for exception_index, exception in enumerate(normalized_exceptions):
            score, basis = _match_score(
                survey_item["type"], survey_text, exception["raw"], exception["text"]
            )
            if score and basis:
                candidates.append((score, survey_index, exception_index, basis))

    # Highest-confidence one-to-one reconciliation.  Index tie-breakers make
    # the output stable across runs.
    candidates.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    used_survey: set[int] = set()
    used_exceptions: set[int] = set()
    selected: list[tuple[int, int, int, str]] = []
    for candidate in candidates:
        _, survey_index, exception_index, _ = candidate
        if survey_index in used_survey or exception_index in used_exceptions:
            continue
        used_survey.add(survey_index)
        used_exceptions.add(exception_index)
        selected.append(candidate)
    selected.sort(key=lambda entry: entry[1])

    matched: list[dict[str, Any]] = []
    for score, survey_index, exception_index, basis in selected:
        survey_item = normalized_survey[survey_index]
        exception = normalized_exceptions[exception_index]
        matched.append(
            {
                "status": "matched_for_screening",
                "survey_index": survey_item["source_index"],
                "title_exception_index": exception["source_index"],
                "survey_type": survey_item["type"],
                "match_basis": basis,
                "match_score": score,
                "citations": [
                    _citation(
                        survey_item["description"],
                        f"survey_items[{survey_item['source_index']}].description",
                    ),
                    _citation(exception["text"], exception["locator"]),
                ],
                "caution": "Text match only; ask title company and surveyor to confirm treatment.",
                "legal_conclusion": None,
            }
        )

    issues: list[dict[str, Any]] = []
    unmatched_survey: list[dict[str, Any]] = []
    for index, item in enumerate(normalized_survey):
        severity, convention = _survey_severity(item, sanitized_intent)
        if index not in used_survey:
            finding = _issue(
                code="survey_matter_not_in_title",
                severity=severity,
                summary=f"Survey {item['type']} matter has no text-matched title exception",
                who=["title company", "counsel", "surveyor"],
                what_to_ask=(
                    "Ask the surveyor to identify the condition and the title company to confirm "
                    "whether it should be excepted, insured, endorsed, or otherwise addressed."
                ),
                impact="Coverage, use, or closing impact is unknown until the professionals reconcile it.",
                citations=[
                    _citation(
                        item["description"],
                        f"survey_items[{item['source_index']}].description",
                    )
                ],
                convention=convention,
            )
            finding["status"] = "new_issue"
            finding["survey_index"] = item["source_index"]
            unmatched_survey.append(finding)
            issues.append(finding)
        elif item["type"] == "encroachment" and severity in {"fatal", "high"}:
            # A title match does not eliminate the physical-use concern.
            finding = _issue(
                code="encroachment_professional_review",
                severity=severity,
                summary="Reported encroachment remains a physical-site issue despite a text match",
                who=["counsel", "surveyor", "title company"],
                what_to_ask="Ask the surveyor to quantify it and counsel/title company to identify available treatment.",
                impact="Site use, improvements, access, or closing could be affected; impact is not determined here.",
                citations=[
                    _citation(
                        item["description"],
                        f"survey_items[{item['source_index']}].description",
                    )
                ],
                convention=convention,
            )
            issues.append(finding)

    unmatched_exceptions: list[dict[str, Any]] = []
    for index, exception in enumerate(normalized_exceptions):
        if index in used_exceptions:
            continue
        finding = _issue(
            code="title_exception_not_plotted",
            severity="medium",
            summary="Title exception was not text-matched to a plotted survey matter",
            who=["surveyor", "title company", "counsel"],
            what_to_ask="Ask the surveyor whether the exception is plottable and, if so, to plot or explain it.",
            impact="The exception's location and effect on the site or intended use remain unknown.",
            citations=[_citation(exception["text"], exception["locator"])],
            convention="screening convention: every unmatched title exception is treated as not plotted",
        )
        finding["status"] = "not_plotted_ask_surveyor"
        finding["title_exception_index"] = exception["source_index"]
        unmatched_exceptions.append(finding)
        issues.append(finding)

    missing: list[str] = []
    if not normalized_survey:
        missing.append("survey matters were not provided; silence does not establish a clear survey")
    if not normalized_exceptions:
        missing.append("title exceptions were not provided; silence does not establish clear title")
    if sanitized_intent is None:
        missing.append("site_plan_intent is unknown")

    severity_order = {"fatal": 0, "blocking": 1, "high": 2, "medium": 3, "low": 4}
    issues.sort(
        key=lambda issue: (
            severity_order.get(str(issue.get("severity", "")).lower(), 5),
            str(issue.get("issue_code", "")),
            issue["citations"][0]["locator"],
        )
    )
    return {
        "purpose": "issue routing to title company, counsel, and surveyor; no legal conclusion",
        "matched": matched,
        "unmatched_survey": unmatched_survey,
        "unmatched_exceptions": unmatched_exceptions,
        "unmatched_title_exceptions": unmatched_exceptions,
        "issues": issues,
        "missing_inputs": missing,
        "site_plan_intent": sanitized_intent,
        "redaction_count": redaction_count,
        "conventions": {
            "matching": "deterministic text similarity; a match is not a coverage or legal determination",
            "encroachment": {
                "fatal": "description states that access is blocked",
                "high": "building/structure/pad or boundary-crossing description",
                "low": "fence/landscaping or expressly minor description",
                "medium": "extent not established",
            },
        },
    }


def survey_vs_title(
    survey_items: list[dict[str, Any]],
    title_exceptions: list[Any] | dict[str, Any],
    site_plan_intent: str | None = None,
) -> dict[str, Any]:
    """Public error boundary for :func:`_survey_vs_title`."""
    try:
        return _survey_vs_title(survey_items, title_exceptions, site_plan_intent)
    except Exception as exc:  # Boundary contract: tools return data, not exceptions.
        return {"error": f"survey/title screening failed: {exc}"}


__all__ = ["survey_vs_title"]
