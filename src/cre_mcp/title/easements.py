"""Cited screening of recorded easements, REAs, and restrictions.

The severity labels in this module are disclosed diligence conventions, not
opinions about enforceability, title, or legal effect.  Counsel reviews every
item, and spatial conclusions remain with the surveyor.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.obligations import extract_restrictions
from cre_mcp.truth.sanitize import sanitize_text


_KINDS = {"easement", "rea", "restriction"}
_RESTRICTION_FIELDS = (
    "exclusive_uses",
    "prohibited_uses",
    "radius_restrictions",
    "cotenancy_conditions",
    "continuous_operation_requirements",
    "go_dark_rights",
    "rofr_rofo_rights",
    "assignment_subletting_clauses",
    "use_clauses",
)
_SCOPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("access", re.compile(r"\b(?:access|ingress|egress)\b", re.I)),
    ("utility", re.compile(r"\b(?:utilit(?:y|ies)|electric|gas|water|sewer|telecom)\b", re.I)),
    ("parking", re.compile(r"\bpark(?:ing)?\b", re.I)),
    ("drainage", re.compile(r"\b(?:drainage|stormwater|retention)\b", re.I)),
    ("maintenance", re.compile(r"\bmaint(?:ain|enance|repair)\b", re.I)),
    ("cost_sharing", re.compile(r"\b(?:cost shar|pro rata|reimburse|assessment)\w*\b", re.I)),
    ("use_restriction", re.compile(r"\b(?:prohibit|restrict|shall not be used|permitted use)\w*\b", re.I)),
)
_PAD_RE = re.compile(r"\b(?:building\s+pad|buildable\s+area|proposed\s+building)\b", re.I)
_CROSS_RE = re.compile(r"\b(?:through|across|cross(?:es|ing)?|travers(?:e|es|ing)|within|over)\b", re.I)
_EDGE_RE = re.compile(
    r"\b(?:along|at|within)\s+(?:the\s+)?(?:north|south|east|west)?\s*"
    r"(?:edge|boundary|perimeter|property line)\b",
    re.I,
)

_CONVENTIONS = {
    "access_through_building_pad": (
        "FATAL SCREENING CONVENTION: express access language in the same clause as "
        "crossing/through language and a building-pad reference is a fatal diligence flag "
        "until the surveyor and counsel reconcile it. This is not a legal conclusion."
    ),
    "utility_at_edge": (
        "ROUTINE SCREENING CONVENTION: express utility language at a stated site edge, "
        "boundary, perimeter, or property line is treated as routine unless the survey, "
        "width, relocation rights, or intended improvements show a conflict."
    ),
    "intended_use_restriction_overlap": (
        "HIGH SCREENING CONVENTION: a meaningful intended-use term also appears in a "
        "prohibited-use claim extracted and cited by cre_mcp.obligations. This is a text "
        "overlap flag for counsel, not a conclusion that the restriction applies or is enforceable."
    ),
    "other_recorded_burden": (
        "UNRESOLVED SCREENING CONVENTION: other recorded burdens remain open diligence "
        "issues; text alone does not establish location, enforceability, or value impact."
    ),
}

_OVERLAP_STOPWORDS = {
    "and",
    "are",
    "building",
    "commercial",
    "construct",
    "construction",
    "develop",
    "development",
    "for",
    "from",
    "intended",
    "only",
    "portion",
    "premises",
    "property",
    "proposed",
    "shall",
    "site",
    "the",
    "this",
    "use",
    "used",
    "with",
}

_DISCLAIMER = (
    "Diligence issue list only; no finding is a legal conclusion. Counsel must review every "
    "recorded burden, and a surveyor must confirm any spatial effect."
)


def _intended_use_text(value: Any) -> tuple[str | None, int]:
    if value is None:
        return None, 0
    if isinstance(value, str):
        if not value.strip():
            return None, 0
        sanitized = sanitize_text(value)
        return sanitized.text.strip() or None, sanitized.redactions
    if isinstance(value, Mapping):
        try:
            serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("intended_use must contain JSON-serializable values") from exc
        sanitized = sanitize_text(serialized)
        return sanitized.text, sanitized.redactions
    raise ValueError("intended_use must be a string, object, or null")


def _clause(text: str, start: int, end: int) -> tuple[str, int, int]:
    left_candidates = [text.rfind(mark, 0, start) for mark in (".", ";", "\n")]
    left = max(left_candidates) + 1
    right_candidates = [position for mark in (".", ";", "\n") if (position := text.find(mark, end)) >= 0]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    quote = text[left:right].strip()
    quote_start = left
    while quote_start < right and text[quote_start].isspace():
        quote_start += 1
    if len(quote) > 200:
        quote = quote[:200]
        right = quote_start + 200
    return quote, quote_start, right


def _evidence(text: str, match: re.Match[str] | None, index: int) -> dict[str, str]:
    if match is None:
        start, end = 0, min(len(text), 200)
        quote = text[start:end].strip()
    else:
        quote, start, end = _clause(text, match.start(), match.end())
    line = text.count("\n", 0, start) + 1
    return {
        "quote": quote,
        "locator": f"items[{index}].text line {line}, chars {start}-{end}",
    }


def _claim_payload(claim: Any, index: int) -> dict[str, Any]:
    locator = claim.locator
    if locator:
        locator = f"items[{index}].text; {locator}"
    return {
        "value": claim.value,
        "quote": claim.quote,
        "locator": locator,
        "confidence": claim.confidence,
        "status": claim.status,
        "source": claim.source,
    }


def _restriction_payload(text: str, kind: str, index: int) -> dict[str, Any] | None:
    if kind not in {"rea", "restriction"}:
        return None
    extracted = extract_restrictions(text, "ccr")
    claims = {
        field_name: [
            _claim_payload(claim, index)
            for claim in getattr(extracted, field_name)
        ]
        for field_name in _RESTRICTION_FIELDS
    }
    return {
        "extraction_owner": "cre_mcp.obligations.extract_restrictions",
        "kind": "ccr",
        "claims": claims,
        "missing_fields": list(extracted.missing_fields),
        "sanitization_redactions": extracted.sanitization_redactions,
    }


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) >= 3 and token not in _OVERLAP_STOPWORDS
    }


def _intended_use_overlap(
    intended_use: str | None, restriction_payload: dict[str, Any] | None
) -> tuple[list[str], list[dict[str, Any]]]:
    """Compare only against obligations-owned prohibited-use extraction."""
    if intended_use is None or restriction_payload is None:
        return [], []
    intended_tokens = _meaningful_tokens(intended_use)
    if not intended_tokens:
        return [], []
    overlap: set[str] = set()
    evidence: list[dict[str, Any]] = []
    for claim in restriction_payload["claims"]["prohibited_uses"]:
        shared = intended_tokens & _meaningful_tokens(claim["quote"])
        if not shared:
            continue
        overlap.update(shared)
        evidence.append(
            {
                "quote": claim["quote"],
                "locator": claim["locator"],
                "overlap_terms": sorted(shared),
            }
        )
    return sorted(overlap), evidence


def _scope_matches(text: str) -> list[tuple[str, re.Match[str]]]:
    found: list[tuple[str, re.Match[str]]] = []
    for scope, pattern in _SCOPE_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            found.append((scope, match))
    return found


def _classification(text: str, scopes: list[tuple[str, re.Match[str]]]) -> tuple[str, str, bool, re.Match[str] | None]:
    access_match = next((match for scope, match in scopes if scope == "access"), None)
    utility_match = next((match for scope, match in scopes if scope == "utility"), None)

    if access_match is not None:
        clause_text, _, _ = _clause(text, access_match.start(), access_match.end())
        if _PAD_RE.search(clause_text) and _CROSS_RE.search(clause_text):
            return "access_through_building_pad", "fatal", True, access_match
    if utility_match is not None:
        clause_text, _, _ = _clause(text, utility_match.start(), utility_match.end())
        if _EDGE_RE.search(clause_text):
            return "utility_at_edge", "routine", False, utility_match
    first_match = scopes[0][1] if scopes else None
    return "other_recorded_burden", "medium", False, first_match


def _impact(classification: str) -> str:
    if classification == "access_through_building_pad":
        return (
            "Potential site-plan and developable-area impact: the cited clause expressly places "
            "access through/across a building pad. Confirm plotting and legal effect; this screen "
            "does not decide whether the intended use is prohibited or impossible."
        )
    if classification == "utility_at_edge":
        return (
            "Conventionally routine location based only on the cited edge/boundary language. "
            "Value impact remains unknown until width, facilities, relocation rights, and the site "
            "plan are confirmed."
        )
    if classification == "intended_use_restriction_overlap":
        return (
            "The cited prohibited-use text shares meaningful terms with the stated intended use. "
            "Counsel must determine scope, applicability, enforceability, and remedies; this "
            "deterministic text screen does not make those determinations."
        )
    return (
        "Value impact is unknown from recorded text alone; location, benefited/burdened parties, "
        "duration, remedies, and intended-use interaction require professional review."
    )


def _what_to_ask(classification: str) -> str:
    if classification == "access_through_building_pad":
        return (
            "Ask the surveyor to plot the easement against the building pad; ask the title company "
            "for the complete instrument and available deletion/endorsement options; ask counsel "
            "to assess the instrument and possible resolution."
        )
    if classification == "utility_at_edge":
        return (
            "Ask the surveyor to confirm location and width, the title company for the complete "
            "instrument, and counsel whether facilities or relocation terms affect the intended use."
        )
    if classification == "intended_use_restriction_overlap":
        return (
            "Ask the title company for the complete recorded instrument and available deletion or "
            "endorsement options, and ask counsel whether the cited prohibited-use clause affects "
            "the specifically stated intended use. Ask the surveyor to plot any spatial component."
        )
    return (
        "Ask the title company for the complete instrument, the surveyor to plot spatial terms, "
        "and counsel to assess scope, enforceability, remedies, and intended-use interaction."
    )


def _burden(entry: Mapping[str, Any], index: int, intended_use: str | None) -> dict[str, Any]:
    kind = entry.get("kind")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise ValueError(f"items[{index}].kind must be easement, rea, or restriction")
    raw_text = entry.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError(f"items[{index}].text must be a nonempty string")

    sanitized = sanitize_text(raw_text)
    text = sanitized.text
    scopes = _scope_matches(text)
    classification, severity, fatal_flag, match = _classification(text, scopes)
    evidence = _evidence(text, match, index)
    restriction_extraction = _restriction_payload(text, kind, index)
    overlap_terms, overlap_evidence = _intended_use_overlap(intended_use, restriction_extraction)
    # A second text overlap may increase review intensity, but it must never
    # hide or downgrade the disclosed fatal spatial convention.
    overlap_applied = bool(overlap_terms and severity != "fatal")
    if overlap_applied:
        classification = "intended_use_restriction_overlap"
        severity = "high"
        fatal_flag = False

    return {
        "item_index": index,
        "kind": kind,
        "issue_type": classification,
        "severity": severity,
        "fatal_flag": fatal_flag,
        "burden_scope": [scope for scope, _ in scopes],
        "summary": (
            "Recorded burden requires counsel review under the disclosed "
            f"{classification.replace('_', ' ')} screening convention."
        ),
        "evidence": overlap_evidence if overlap_applied else [evidence],
        "value_impact": _impact(classification),
        "route_to": ["title company", "counsel", "surveyor"],
        "what_to_ask": _what_to_ask(classification),
        "deal_impact_if_unresolved": _impact(classification),
        "convention_key": classification,
        "convention": _CONVENTIONS[classification],
        "restriction_extraction": restriction_extraction,
        "intended_use_overlap_terms": overlap_terms,
        "sanitization_redactions": sanitized.redactions,
        "legal_conclusion": None,
    }


def assess_recorded_burdens(
    items: Sequence[Mapping[str, Any]], intended_use: Any
) -> dict[str, Any]:
    """Screen recorded burdens and expose all deterministic severity conventions."""
    try:
        if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
            raise ValueError("items must be a list of burden objects")
        intended, intended_redactions = _intended_use_text(intended_use)
        burdens: list[dict[str, Any]] = []
        for index, entry in enumerate(items):
            if not isinstance(entry, Mapping):
                raise ValueError(f"items[{index}] must be an object")
            burdens.append(_burden(entry, index, intended))

        missing_fields: list[dict[str, Any]] = []
        if not burdens:
            missing_fields.append(
                {
                    "field": "items",
                    "value": None,
                    "impact": (
                        "No recorded burden items were supplied; an empty screen is not evidence "
                        "that no easements, REAs, or restrictions exist."
                    ),
                }
            )
        if intended is None:
            missing_fields.append(
                {
                    "field": "intended_use",
                    "value": None,
                    "impact": "Intended-use interaction was not screened; obtain the intended use.",
                }
            )
        for burden in burdens:
            if not burden["burden_scope"]:
                missing_fields.append(
                    {
                        "item_index": burden["item_index"],
                        "field": "burden_scope",
                        "value": None,
                        "impact": "No supported scope category was extracted; review the cited text.",
                    }
                )

        return {
            "intended_use": intended,
            "burdens": burdens,
            "issues": list(burdens),
            "conventions": dict(_CONVENTIONS),
            "missing_fields": missing_fields,
            "sanitization_redactions": intended_redactions
            + sum(item["sanitization_redactions"] for item in burdens),
            "disclaimer": _DISCLAIMER,
        }
    except Exception as exc:
        return {"error": str(exc)}


__all__ = ["assess_recorded_burdens"]
