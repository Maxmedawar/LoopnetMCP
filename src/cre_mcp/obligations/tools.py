"""Unregistered, JSON-friendly plain functions for the obligation screens."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from cre_mcp.leases.reader import read_lease
from cre_mcp.obligations.collisions import detect_collisions
from cre_mcp.obligations.consent import screen_transfer_consents as _screen_transfer_consents
from cre_mcp.obligations.estoppels import compare_estoppel
from cre_mcp.obligations.restrictions import (
    RestrictionKind,
    RestrictionSet,
    extract_restrictions,
)

_RESTRICTION_CLAIM_FIELDS = (
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


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _path_or_text(value: str | Path) -> tuple[str, str | None, int]:
    if isinstance(value, Path):
        document = read_lease(value)
        return document.text, document.source_path, document.redactions
    if not isinstance(value, str):
        raise TypeError("path_or_text must be a path or string")
    # Avoid attempting filesystem operations on a full document string.
    if "\n" not in value and len(value) < 1024:
        try:
            candidate = Path(value).expanduser()
            if candidate.is_file():
                document = read_lease(candidate)
                return document.text, document.source_path, document.redactions
        except OSError:
            pass
    return value, None, 0


def extract_lease_restrictions(
    path_or_text: str | Path,
    kind: RestrictionKind = "lease",
) -> dict[str, Any]:
    """Load a file or raw text and return cited restrictions plus honest gaps."""
    text, source_path, reader_redactions = _path_or_text(path_or_text)
    restrictions = extract_restrictions(text, kind)
    payload = _serialize(restrictions)
    payload["source_path"] = source_path
    payload["honesty"] = {
        "posture": "deterministic cited extraction; silence remains missing",
        "missing_fields": list(restrictions.missing_fields),
        "sanitization_redactions": max(
            reader_redactions, restrictions.sanitization_redactions
        ),
        "limitations": [
            "No enforceability, priority, waiver, amendment, or legal conclusion is determined.",
            "Scanned-image quality, defined-term cross-references, exhibits, and indirect drafting may evade regex extraction.",
        ],
    }
    return payload


def _input_issue(index: int | None, entry: Any, reason: str) -> dict[str, Any]:
    source_label: str | None = None
    if isinstance(entry, Mapping):
        raw_label = entry.get("source_label", entry.get("source_path"))
        if raw_label is not None:
            source_label = str(raw_label)
    return {
        "index": index,
        "source_label": source_label,
        "reason": reason,
    }


def _serialized_restriction_error(entry: Mapping[str, Any]) -> str | None:
    required = {"kind", *_RESTRICTION_CLAIM_FIELDS}
    missing = sorted(required - set(entry))
    if missing:
        return "not a serialized RestrictionSet; missing structural keys: " + ", ".join(missing)
    if entry.get("kind") not in {"lease", "ccr"}:
        return "serialized RestrictionSet kind must be 'lease' or 'ccr'"
    for field_name in _RESTRICTION_CLAIM_FIELDS:
        raw_claims = entry.get(field_name)
        if not isinstance(raw_claims, list):
            return f"serialized RestrictionSet field {field_name!r} must be a JSON list"
        for claim_index, claim in enumerate(raw_claims):
            if not isinstance(claim, Mapping):
                return f"{field_name}[{claim_index}] must be a serialized CitedClaim object"
            if claim.get("status") not in {"stated", "inferred"}:
                return f"{field_name}[{claim_index}] must have stated or inferred status"
            if claim.get("value") is None:
                return f"{field_name}[{claim_index}] has no cited value"
            if not claim.get("quote") or not claim.get("locator"):
                return f"{field_name}[{claim_index}] must include quote and locator"
            confidence = claim.get("confidence")
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
                return f"{field_name}[{claim_index}] confidence must be numeric"
            if not 0.0 <= float(confidence) <= 1.0:
                return f"{field_name}[{claim_index}] confidence must be between 0 and 1"
    missing_fields = entry.get("missing_fields", [])
    if not isinstance(missing_fields, list):
        return "serialized RestrictionSet missing_fields must be a JSON list"
    redactions = entry.get("sanitization_redactions", 0)
    if not isinstance(redactions, int) or isinstance(redactions, bool) or redactions < 0:
        return "serialized RestrictionSet sanitization_redactions must be a nonnegative integer"
    return None


def _apply_source_label(restrictions: RestrictionSet, source_label: str) -> None:
    for field_name in _RESTRICTION_CLAIM_FIELDS:
        for claim in getattr(restrictions, field_name):
            claim.locator = f"{source_label} — {claim.locator}"


def _normalize_restriction_inputs(
    raw_entries: Any,
) -> tuple[list[RestrictionSet | Mapping[str, Any]], list[dict[str, Any]]]:
    normalized: list[RestrictionSet | Mapping[str, Any]] = []
    issues: list[dict[str, Any]] = []
    if raw_entries is None:
        return [], [_input_issue(None, None, "context.existing_restrictions is missing")]
    if not isinstance(raw_entries, (list, tuple)):
        return [], [
            _input_issue(
                None,
                raw_entries,
                "context.existing_restrictions must be a JSON list",
            )
        ]
    if not raw_entries:
        return [], [_input_issue(None, None, "context.existing_restrictions is empty")]

    for index, entry in enumerate(raw_entries):
        if isinstance(entry, RestrictionSet):
            normalized.append(entry)
            continue
        if not isinstance(entry, Mapping):
            issues.append(
                _input_issue(
                    index,
                    entry,
                    "entry must be a RestrictionSet, serialized RestrictionSet object, or raw text object",
                )
            )
            continue

        if "text" in entry:
            text = entry.get("text")
            if not isinstance(text, str) or not text.strip():
                issues.append(_input_issue(index, entry, "raw restriction entry text must be a nonempty string"))
                continue
            kind = entry.get("kind", "lease")
            if kind not in {"lease", "ccr"}:
                issues.append(_input_issue(index, entry, "raw restriction entry kind must be 'lease' or 'ccr'"))
                continue
            raw_label = entry.get("source_label")
            if raw_label is not None and (not isinstance(raw_label, str) or not raw_label.strip()):
                issues.append(_input_issue(index, entry, "raw restriction entry source_label must be a nonempty string when supplied"))
                continue
            restrictions = extract_restrictions(text, kind)
            if isinstance(raw_label, str):
                _apply_source_label(restrictions, raw_label.strip())
            normalized.append(restrictions)
            continue

        structural_error = _serialized_restriction_error(entry)
        if structural_error is not None:
            issues.append(_input_issue(index, entry, structural_error))
            continue
        normalized.append(entry)
    return normalized, issues


def _normalization_issue_payload(
    issues: list[dict[str, Any]],
    *,
    no_usable_inputs: bool,
) -> dict[str, Any]:
    if no_usable_inputs:
        return {
            "type": "input_error",
            "severity": "fatal",
            "input_error": (
                "Collision screen did not run because zero usable restriction sets remained "
                "after input normalization; do not treat this result as a clearance."
            ),
            "unusable_inputs": issues,
            "why": "A fatal-severity obligation check cannot pass on absent or unrecognized input.",
            "counsel_question": (
                "Obtain readable source documents or valid extracted restriction sets, then rerun "
                "the collision screen before counsel reviews the proposed use."
            ),
        }
    return {
        "type": "unusable_inputs",
        "severity": "material",
        "input_error": None,
        "unusable_inputs": issues,
        "why": (
            "Some restriction entries were not screened; collision findings are incomplete and "
            "must not be treated as a clearance."
        ),
        "counsel_question": (
            "Replace or correct every named unusable input, rerun the screen, and give complete "
            "source documents to CRE counsel."
        ),
    }


def detect_obligation_collisions(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return JSON-friendly collision flags without silently accepting bad inputs.

    Each ``existing_restrictions`` item may be an in-process RestrictionSet, a
    JSON-round-tripped RestrictionSet mapping, or a raw ``text`` mapping that is
    deterministically extracted before collision matching.
    """
    if not isinstance(context, Mapping):
        return [
            _normalization_issue_payload(
                [_input_issue(None, context, "context must be a JSON object")],
                no_usable_inputs=True,
            )
        ]
    normalized, issues = _normalize_restriction_inputs(
        context.get("existing_restrictions")
    )
    if not normalized:
        return [_normalization_issue_payload(issues, no_usable_inputs=True)]
    normalized_context = dict(context)
    normalized_context["existing_restrictions"] = normalized
    results = [_serialize(item) for item in detect_collisions(normalized_context)]
    if issues:
        results.append(_normalization_issue_payload(issues, no_usable_inputs=False))
    return results


def screen_transfer_consents(
    docs: Mapping[str, Any] | None = None,
    lease_text: str | None = None,
    loan_terms: Mapping[str, Any] | None = None,
    intended: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-friendly consent screen from a mapping or explicit inputs.

    (FastMCP rejects **kwargs tools, so the keyword surface is explicit:
    lease_text / loan_terms / intended merge over the optional docs mapping.)
    """
    explicit = {
        key: value
        for key, value in (
            ("lease_text", lease_text),
            ("loan_terms", loan_terms),
            ("intended", intended),
        )
        if value is not None
    }
    if docs is not None and explicit:
        merged = dict(docs)
        merged.update(explicit)
        inputs: Mapping[str, Any] = merged
    elif docs is not None:
        inputs = docs
    else:
        inputs = explicit
    screen = _screen_transfer_consents(inputs)
    payload = _serialize(screen)
    payload["honesty"] = {
        "posture": screen.posture,
        "gaps": list(screen.gaps),
        "timing_notes_are_conventions": True,
        "legal_review_required": True,
    }
    return payload


def compare_estoppel_to_lease(
    abstract_or_terms: Any,
    estoppel_facts: Mapping[str, Any],
) -> dict[str, Any]:
    """Return JSON-friendly cited estoppel exceptions and SNDA tracking."""
    comparison = compare_estoppel(abstract_or_terms, estoppel_facts)
    return {
        "exceptions": [_serialize(item) for item in comparison],
        "exception_count": len(comparison),
        "snda": _serialize(comparison.snda),
        "honesty": {
            "posture": comparison.posture,
            "gaps": list(comparison.gaps),
            "lease_side_citation_required_for_every_exception": True,
            "legal_review_required": True,
        },
    }


__all__ = [
    "extract_lease_restrictions",
    "detect_obligation_collisions",
    "screen_transfer_consents",
    "compare_estoppel_to_lease",
]
