"""Consolidate title, legal-description, burden, and survey issue screens."""

from __future__ import annotations

import re
from typing import Any


_SEVERITY_ORDER = {
    "stop": 0,
    "fatal": 0,
    "blocking": 1,
    "blocker": 1,
    "critical": 1,
    "high": 2,
    "medium": 3,
    "moderate": 3,
    "review": 3,
    "low": 4,
    "routine": 4,
    "informational": 5,
    "info": 5,
    "unknown": 6,
}
_SOURCE_DEFAULTS = {
    "title_commitment": {
        "who": ["title company", "counsel"],
        "ask": "Ask the title company and counsel to identify the required response before closing.",
        "impact": "Title coverage or closing impact remains unknown until addressed.",
    },
    "encumbrances": {
        "who": ["title company", "counsel"],
        "ask": "Ask the title company and counsel to confirm payoff, release, priority, or other treatment.",
        "impact": "Closing or post-closing title impact remains unknown until addressed.",
    },
    "legal_comparison": {
        "who": ["surveyor", "counsel", "title company"],
        "ask": "Ask the surveyor, counsel, and title company to reconcile the cited descriptions.",
        "impact": "The property description and deal impact remain uncertain until reconciled.",
    },
    "recorded_burdens": {
        "who": ["counsel", "title company", "surveyor"],
        "ask": "Ask counsel to interpret the instrument and the title company/surveyor to confirm treatment and location.",
        "impact": "Effect on intended use, value, or coverage remains unknown until reviewed.",
    },
    "survey_review": {
        "who": ["surveyor", "title company", "counsel"],
        "ask": "Ask the surveyor and title company to reconcile the condition, with counsel review.",
        "impact": "Site-use, coverage, or closing impact remains unknown until reconciled.",
    },
}
_CANDIDATE_KEYS = {
    "title_commitment": (
        "issues",
        "requirements",
        "schedule_b_i_requirements",
        "schedule_b_i",
        "exceptions",
        "schedule_b_ii_exceptions",
        "schedule_b_ii",
        "gap_review",
        "gap_notes",
        "gap_note",
    ),
    "encumbrances": (
        "issues",
        "blocking",
        "blocking_items",
        "closing_blockers",
        "findings",
        "ride_through",
        "payoff_arrangement_gaps",
        "payoff_gaps",
        "priority_notes",
        "resolution_gaps",
    ),
    "legal_comparison": ("issues", "conflicts"),
    "recorded_burdens": ("issues", "findings", "burdens", "items"),
    "survey_review": (
        "issues",
        "unmatched_survey",
        "unmatched_exceptions",
        "unmatched_title_exceptions",
    ),
}


def _normalize_severity(value: Any, candidate: dict[str, Any] | None = None) -> str:
    if isinstance(value, str):
        lowered = value.strip().lower().replace("_", " ")
        for label in _SEVERITY_ORDER:
            if label in lowered:
                if label == "stop":
                    return "fatal"
                if label in {"blocker", "critical"}:
                    return "blocking"
                if label in {"moderate", "review"}:
                    return "medium"
                if label in {"routine", "informational", "info"}:
                    return "low"
                return label
    if isinstance(candidate, dict):
        if candidate.get("stop") is True:
            return "fatal"
        if candidate.get("blocks_closing") is True or candidate.get("blocking") is True:
            return "blocking"
    return "unknown"


def _text_value(candidate: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _summary(candidate: Any) -> str | None:
    if isinstance(candidate, str):
        return candidate.strip() or None
    if not isinstance(candidate, dict):
        return None
    direct = _text_value(
        candidate,
        (
            "summary",
            "issue",
            "finding",
            "description",
            "title",
            "message",
            "reason",
            "note",
            "gap_note",
            "text",
            "quote",
        ),
    )
    if direct:
        return direct
    citation = candidate.get("citation")
    if isinstance(citation, dict):
        quote = citation.get("quote")
        if isinstance(quote, str) and quote.strip():
            return quote.strip()
    evidence = candidate.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                quote = item.get("quote")
                if isinstance(quote, str) and quote.strip():
                    return quote.strip()
    if isinstance(evidence, dict):
        quote = evidence.get("quote")
        if isinstance(quote, str) and quote.strip():
            return quote.strip()
    return None


def _who(candidate: dict[str, Any], source: str) -> list[str]:
    raw = candidate.get("who")
    if raw is None:
        raw = candidate.get("route_to")
    if raw is None:
        raw = candidate.get("who_must_act")
    values: list[str] = []
    if isinstance(raw, str):
        for part in re.split(r"[,;/]|\band\b", raw, flags=re.IGNORECASE):
            if part.strip():
                values.append(part.strip().lower())
    elif isinstance(raw, list):
        values.extend(str(item).strip().lower() for item in raw if str(item).strip())
    aliases = {
        "title co": "title company",
        "title co.": "title company",
        "attorney": "counsel",
        "lawyer": "counsel",
    }
    normalized: list[str] = []
    for value in values or _SOURCE_DEFAULTS[source]["who"]:
        mapped = aliases.get(value, value)
        if mapped not in normalized:
            normalized.append(mapped)
    return normalized


def _citation_from_dict(value: dict[str, Any]) -> dict[str, str] | None:
    quote = value.get("quote")
    locator = value.get("locator")
    if isinstance(quote, str) and quote.strip() and isinstance(locator, str) and locator.strip():
        return {"quote": quote.strip(), "locator": locator.strip()}
    return None


def _citations(candidate: Any, fallback_summary: str, path: str) -> list[dict[str, str]]:
    if not isinstance(candidate, dict):
        return [{"quote": fallback_summary, "locator": path}]
    found: list[dict[str, str]] = []
    raw_many = candidate.get("citations")
    if isinstance(raw_many, list):
        for raw in raw_many:
            if isinstance(raw, dict):
                citation = _citation_from_dict(raw)
                if citation:
                    found.append(citation)
    raw_one = candidate.get("citation")
    if isinstance(raw_one, dict):
        citation = _citation_from_dict(raw_one)
        if citation:
            found.append(citation)
    evidence = candidate.get("evidence")
    if isinstance(evidence, list):
        for raw in evidence:
            if isinstance(raw, dict):
                citation = _citation_from_dict(raw)
                if citation:
                    found.append(citation)
    if isinstance(evidence, dict):
        citation = _citation_from_dict(evidence)
        if citation:
            found.append(citation)
    quote = candidate.get("source_quote") or candidate.get("quote")
    locator = candidate.get("source_locator") or candidate.get("locator")
    if isinstance(quote, str) and quote.strip() and isinstance(locator, str) and locator.strip():
        found.append({"quote": quote.strip(), "locator": locator.strip()})
    if not found:
        found.append({"quote": fallback_summary, "locator": path})
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for citation in found:
        key = (citation["quote"], citation["locator"])
        if key not in seen:
            seen.add(key)
            unique.append(citation)
    return unique


def _list_entries(value: Any, path: str) -> list[tuple[Any, str]]:
    if isinstance(value, list):
        return [(entry, f"{path}[{index}]") for index, entry in enumerate(value)]
    if isinstance(value, (str, dict)):
        return [(value, path)]
    return []


def _candidate_entries(output: Any, source: str) -> list[tuple[Any, str]]:
    if isinstance(output, list):
        return _list_entries(output, source)
    if not isinstance(output, dict):
        return []
    entries: list[tuple[Any, str]] = []
    used_ids: set[int] = set()

    # Prefer an explicit issues array.  The survey screen, in particular,
    # repeats its unmatched findings in convenience arrays.
    issues = output.get("issues")
    if isinstance(issues, list):
        entries.extend(_list_entries(issues, f"{source}.issues"))
        used_ids.add(id(issues))
        if source == "survey_review":
            return entries

    for key in _CANDIDATE_KEYS[source]:
        if source == "title_commitment" and key in {"gap_notes", "gap_note"} and output.get("gap_review") is not None:
            continue
        value = output.get(key)
        if value is None or id(value) in used_ids:
            continue
        used_ids.add(id(value))
        if isinstance(value, dict):
            nested_found = False
            for nested_key in ("items", "requirements", "exceptions", "findings", "issues"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    entries.extend(_list_entries(nested, f"{source}.{key}.{nested_key}"))
                    nested_found = True
            if not nested_found and _summary(value):
                entries.append((value, f"{source}.{key}"))
        else:
            entries.extend(_list_entries(value, f"{source}.{key}"))
    return entries


def _canonical_text(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.lower())
    ignored = {"a", "an", "the", "reported", "identified", "issue", "matter"}
    return " ".join(word for word in words if word not in ignored)


def _word_set(value: str) -> set[str]:
    return set(_canonical_text(value).split())


def _same_issue(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_key = left.get("dedupe_key")
    right_key = right.get("dedupe_key")
    if left_key and right_key and left_key == right_key:
        return True
    left_summary = _canonical_text(left["summary"])
    right_summary = _canonical_text(right["summary"])
    left_quotes = {_canonical_text(item["quote"]) for item in left["citations"]}
    right_quotes = {_canonical_text(item["quote"]) for item in right["citations"]}
    shared_evidence = bool(left_quotes & right_quotes)
    if left_summary and left_summary == right_summary:
        return shared_evidence
    left_words = _word_set(left["summary"])
    right_words = _word_set(right["summary"])
    if not left_words or not right_words:
        return False
    overlap = len(left_words & right_words) / len(left_words | right_words)
    if overlap < 0.8:
        return False
    return shared_evidence


def _make_issue(candidate: Any, source: str, path: str) -> dict[str, Any] | None:
    summary = _summary(candidate)
    if summary is None:
        return None
    data = candidate if isinstance(candidate, dict) else {}
    severity = _normalize_severity(
        data.get("severity") or data.get("risk") or data.get("deal_impact"), data
    )
    ask = _text_value(
        data,
        (
            "what_to_ask",
            "ask",
            "guidance",
            "title_company_guidance",
            "typical_cure_note",
            "recommended_action",
            "next_step",
            "action",
        ),
    ) or _SOURCE_DEFAULTS[source]["ask"]
    impact = _text_value(
        data,
        (
            "deal_impact_if_unresolved",
            "impact_if_unresolved",
            "unresolved_impact",
            "deal_impact",
            "impact",
        ),
    ) or _SOURCE_DEFAULTS[source]["impact"]
    issue_code = _text_value(
        data, ("issue_code", "issue_type", "code", "category", "classification", "kind")
    )
    dedupe_key = _text_value(data, ("dedupe_key",))
    return {
        "issue_code": issue_code,
        "severity": severity,
        "summary": summary,
        "who": _who(data, source),
        "what_to_ask": ask,
        "deal_impact_if_unresolved": impact,
        "citations": _citations(candidate, summary, path),
        "sources": [source],
        "dedupe_key": _canonical_text(dedupe_key) if dedupe_key else None,
        "legal_conclusion": None,
    }


def _merge_issue(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    if _SEVERITY_ORDER.get(incoming["severity"], 6) < _SEVERITY_ORDER.get(existing["severity"], 6):
        existing["severity"] = incoming["severity"]
    for who in incoming["who"]:
        if who not in existing["who"]:
            existing["who"].append(who)
    for source in incoming["sources"]:
        if source not in existing["sources"]:
            existing["sources"].append(source)
    seen = {(entry["quote"], entry["locator"]) for entry in existing["citations"]}
    for citation in incoming["citations"]:
        key = (citation["quote"], citation["locator"])
        if key not in seen:
            seen.add(key)
            existing["citations"].append(citation)
    if existing.get("issue_code") is None and incoming.get("issue_code"):
        existing["issue_code"] = incoming["issue_code"]


def _attorney_issue_list(
    deal_id: str | None = None,
    title_commitment: dict[str, Any] | list[Any] | None = None,
    encumbrances: dict[str, Any] | list[Any] | None = None,
    legal_comparison: dict[str, Any] | list[Any] | None = None,
    recorded_burdens: dict[str, Any] | list[Any] | None = None,
    survey_review: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    """Build a cited, deduplicated, severity-sorted professional issue list.

    All six arguments may be supplied positionally.  Missing output is reported
    as missing rather than interpreted as a clean result.
    """
    if deal_id is not None and not isinstance(deal_id, str):
        return {"error": "deal_id must be a string or null"}
    supplied = {
        "title_commitment": title_commitment,
        "encumbrances": encumbrances,
        "legal_comparison": legal_comparison,
        "recorded_burdens": recorded_burdens,
        "survey_review": survey_review,
    }
    for source, output in supplied.items():
        if output is not None and not isinstance(output, (dict, list)):
            return {"error": f"{source} must be an object, list, or null"}

    missing_inputs: list[str] = []
    source_errors: list[dict[str, str]] = []
    consolidated: list[dict[str, Any]] = []
    for source, output in supplied.items():
        if output is None:
            missing_inputs.append(f"{source} was not provided; silence is not a clear result")
            continue
        if isinstance(output, dict) and "error" in output:
            source_errors.append({"source": source, "error": str(output["error"])})
            missing_inputs.append(f"{source} returned an error and could not be consolidated")
            continue
        for candidate, path in _candidate_entries(output, source):
            issue = _make_issue(candidate, source, path)
            if issue is None:
                continue
            duplicate = next((item for item in consolidated if _same_issue(item, issue)), None)
            if duplicate is None:
                consolidated.append(issue)
            else:
                _merge_issue(duplicate, issue)

    consolidated.sort(
        key=lambda issue: (
            _SEVERITY_ORDER.get(issue["severity"], 6),
            _canonical_text(issue["summary"]),
            issue["citations"][0]["locator"],
        )
    )
    for rank, issue in enumerate(consolidated, start=1):
        issue["rank"] = rank

    return {
        "deal_id": deal_id.strip() if isinstance(deal_id, str) and deal_id.strip() else None,
        "purpose": "issue routing to title company, counsel, and surveyor; no legal conclusions",
        "issues": consolidated,
        "issue_count": len(consolidated),
        "missing_inputs": missing_inputs,
        "source_errors": source_errors,
        "severity_convention": ["fatal", "blocking", "high", "medium", "low", "unknown"],
        "disclaimer": (
            "This deterministic screen does not state a legal conclusion or resolve any conflict. "
            "The cited issues must be evaluated by the identified professionals."
        ),
    }


def attorney_issue_list(
    deal_id: str | None = None,
    title_commitment: dict[str, Any] | list[Any] | None = None,
    encumbrances: dict[str, Any] | list[Any] | None = None,
    legal_comparison: dict[str, Any] | list[Any] | None = None,
    recorded_burdens: dict[str, Any] | list[Any] | None = None,
    survey_review: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    """Public error boundary for consolidated issue-list generation."""
    try:
        return _attorney_issue_list(
            deal_id,
            title_commitment,
            encumbrances,
            legal_comparison,
            recorded_burdens,
            survey_review,
        )
    except Exception as exc:  # Boundary contract: tools return data, not exceptions.
        return {"error": f"issue-list consolidation failed: {exc}"}


__all__ = ["attorney_issue_list"]
