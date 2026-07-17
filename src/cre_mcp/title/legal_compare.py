"""Deterministic comparison of legal-description source data.

This module is a diligence screen.  It deliberately does not decide which
description controls, whether a discrepancy is legally material, or how a
description should be corrected.  Every detected mismatch is routed to a
surveyor and counsel with the source values that caused the flag.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from cre_mcp.truth.sanitize import sanitize_text


_SOURCE_TYPES = {"deed", "title", "survey", "assessor"}
_HASH_RE = re.compile(r"^(?:(sha(?:1|224|256|384|512)|md5):)?([0-9a-fA-F]{32,128})$")
_ACREAGE_RE = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:acres?|ac\.?)(?=\s|$|[,;)])", re.I)
_LOT_BLOCK_RE = re.compile(
    r"\blots?\s+([A-Za-z0-9-]+)(?:\s+(?:and|&)\s+([A-Za-z0-9-]+))?"
    r"\s*(?:,|in)?\s*(?:of\s+)?block\s+([A-Za-z0-9-]+)\b",
    re.I,
)

_DISCLAIMER = (
    "Diligence issue list only; this comparison states no legal conclusion and "
    "does not determine which legal description is correct. Route every mismatch "
    "to the surveyor and counsel."
)


def _normalize_description(value: str) -> str:
    """Normalize presentation noise without rewriting directional calls."""
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _description_fingerprint(value: str) -> tuple[str, str, str]:
    compact = value.strip()
    hash_match = _HASH_RE.fullmatch(compact)
    if hash_match:
        digest = hash_match.group(2).lower()
        inferred_algorithms = {
            32: "md5",
            40: "sha1",
            56: "sha224",
            64: "sha256",
            96: "sha384",
            128: "sha512",
        }
        algorithm = (
            hash_match.group(1) or inferred_algorithms.get(len(digest), "provided")
        ).lower()
        return f"{algorithm}:{digest}", "provided_hash", compact

    normalized = _normalize_description(compact)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}", "normalized_text_hash", normalized


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("acreage must be numeric or null")
    try:
        parsed = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("acreage must be numeric or null") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("acreage must be a finite nonnegative number or null")
    return parsed.normalize()


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _line_locator(text: str, start: int, end: int, prefix: str) -> str:
    line = text.count("\n", 0, start) + 1
    return f"{prefix} line {line}, chars {start}-{end}"


def _quote_span(text: str, start: int, end: int, *, radius: int = 70) -> tuple[str, int, int]:
    span_start = max(0, start - radius)
    span_end = min(len(text), end + radius)
    quote = text[span_start:span_end].strip()
    if len(quote) > 200:
        quote = quote[:200]
        span_end = min(span_end, span_start + 200)
    return quote, span_start, span_end


def _extract_acreage(text: str, prefix: str) -> tuple[Decimal | None, dict[str, str] | None]:
    matches = list(_ACREAGE_RE.finditer(text))
    parsed: list[tuple[Decimal, re.Match[str]]] = []
    for match in matches:
        try:
            parsed.append((Decimal(match.group(1).replace(",", "")).normalize(), match))
        except InvalidOperation:
            continue
    values = {value for value, _ in parsed}
    if len(values) != 1:
        return None, None
    value, match = parsed[0]
    quote, start, end = _quote_span(text, match.start(), match.end())
    return value, {"quote": quote, "locator": _line_locator(text, start, end, prefix)}


def _normalize_lot_block(value: str) -> str:
    return _normalize_description(value)


def _extract_lot_block(text: str, prefix: str) -> tuple[str | None, dict[str, str] | None]:
    matches = list(_LOT_BLOCK_RE.finditer(text))
    values: list[tuple[str, re.Match[str]]] = []
    for match in matches:
        lots = [match.group(1)]
        if match.group(2):
            lots.append(match.group(2))
        normalized = "lots " + " and ".join(part.casefold() for part in lots)
        normalized += f" block {match.group(3).casefold()}"
        values.append((normalized, match))
    distinct = {value for value, _ in values}
    if len(distinct) != 1:
        return None, None
    value, match = values[0]
    quote, start, end = _quote_span(text, match.start(), match.end())
    return value, {"quote": quote, "locator": _line_locator(text, start, end, prefix)}


def _structured_evidence(value: Any, locator: str) -> dict[str, str]:
    return {"quote": str(value)[:200], "locator": locator}


def _source_record(entry: Mapping[str, Any], index: int) -> dict[str, Any]:
    source = entry.get("source")
    if not isinstance(source, str) or source not in _SOURCE_TYPES:
        raise ValueError(
            f"sources[{index}].source must be one of deed, title, survey, or assessor"
        )
    raw_description = entry.get("text_or_hash")
    if not isinstance(raw_description, str) or not raw_description.strip():
        raise ValueError(f"sources[{index}].text_or_hash must be a nonempty string")

    sanitized = sanitize_text(raw_description)
    text = sanitized.text
    fingerprint, fingerprint_basis, normalized_text = _description_fingerprint(text)
    prefix = f"sources[{index}].text_or_hash"
    description_evidence = {
        "quote": text.strip()[:200],
        "locator": _line_locator(text, 0, min(len(text), 200), prefix),
    }

    acreage = _decimal(entry.get("acreage"))
    acreage_basis: str | None = None
    acreage_evidence: dict[str, str] | None = None
    if acreage is not None:
        acreage_basis = "structured_field"
        acreage_evidence = _structured_evidence(entry.get("acreage"), f"sources[{index}].acreage")
    else:
        acreage, acreage_evidence = _extract_acreage(text, prefix)
        if acreage is not None:
            acreage_basis = "document_text"

    raw_lot_block = entry.get("lot_block")
    if raw_lot_block is not None and (not isinstance(raw_lot_block, str) or not raw_lot_block.strip()):
        raise ValueError(f"sources[{index}].lot_block must be a nonempty string or null")
    lot_block: str | None = None
    lot_block_basis: str | None = None
    lot_block_evidence: dict[str, str] | None = None
    if isinstance(raw_lot_block, str):
        lot_block = _normalize_lot_block(raw_lot_block)
        lot_block_basis = "structured_field"
        lot_block_evidence = _structured_evidence(raw_lot_block, f"sources[{index}].lot_block")
    else:
        lot_block, lot_block_evidence = _extract_lot_block(text, prefix)
        if lot_block is not None:
            lot_block_basis = "document_text"

    missing_fields: list[str] = []
    if acreage is None:
        missing_fields.append("acreage")
    if lot_block is None:
        missing_fields.append("lot_block")

    return {
        "index": index,
        "source": source,
        "description_hash": fingerprint,
        "description_hash_basis": fingerprint_basis,
        "normalized_text": normalized_text if fingerprint_basis == "normalized_text_hash" else None,
        "acreage": _decimal_text(acreage) if acreage is not None else None,
        "acreage_basis": acreage_basis,
        "lot_block": lot_block,
        "lot_block_basis": lot_block_basis,
        "evidence": {
            "description": description_evidence,
            "acreage": acreage_evidence,
            "lot_block": lot_block_evidence,
        },
        "missing_fields": missing_fields,
        "sanitization_redactions": sanitized.redactions,
    }


def _conflict(
    issue_type: str,
    summary: str,
    records: list[dict[str, Any]],
    value_key: str,
    evidence_key: str,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    for record in records:
        cited = record["evidence"][evidence_key]
        if cited is None:
            continue
        evidence.append(
            {
                "source": record["source"],
                "source_index": record["index"],
                "value": record[value_key],
                "quote": cited["quote"],
                "locator": cited["locator"],
            }
        )
    return {
        "issue_type": issue_type,
        "severity": "high",
        "summary": summary,
        "evidence": evidence,
        "route_to": ["surveyor", "counsel"],
        "what_to_ask": (
            "Ask the surveyor to reconcile the cited source descriptions and ask counsel "
            "what corrective or closing documentation, if any, is appropriate."
        ),
        "deal_impact_if_unresolved": (
            "Property identity, insured parcel scope, acreage, or planned-site assumptions may "
            "remain uncertain; the screen does not determine materiality."
        ),
        "legal_conclusion": None,
    }


def compare_legal_descriptions(sources: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare cited legal-description fields without choosing a controlling source.

    Unknown optional fields remain ``None`` and are listed under ``missing_fields``.
    Any known mismatch is flagged; no tolerance or legal-materiality threshold is
    silently applied.
    """
    try:
        if isinstance(sources, (str, bytes)) or not isinstance(sources, Sequence):
            raise ValueError("sources must be a list of source objects")
        if not sources:
            raise ValueError("sources must contain at least one source object")
        records: list[dict[str, Any]] = []
        for index, entry in enumerate(sources):
            if not isinstance(entry, Mapping):
                raise ValueError(f"sources[{index}] must be an object")
            records.append(_source_record(entry, index))

        conflicts: list[dict[str, Any]] = []
        comparison_specs = (
            (
                "acreage_mismatch",
                "Known acreage values differ across legal-description sources.",
                "acreage",
                "acreage",
            ),
            (
                "lot_block_mismatch",
                "Known lot/block references differ across legal-description sources.",
                "lot_block",
                "lot_block",
            ),
            (
                "legal_description_hash_mismatch",
                "Normalized legal-description text hashes differ across sources.",
                "description_hash",
                "description",
            ),
        )
        for issue_type, summary, value_key, evidence_key in comparison_specs:
            known = [record for record in records if record[value_key] is not None]
            if len(known) >= 2 and len({record[value_key] for record in known}) > 1:
                conflicts.append(_conflict(issue_type, summary, known, value_key, evidence_key))

        missing_fields = [
            {
                "source": record["source"],
                "source_index": record["index"],
                "fields": list(record["missing_fields"]),
            }
            for record in records
            if record["missing_fields"]
        ]
        comparison_gaps: list[dict[str, Any]] = []
        if len(records) < 2:
            comparison_gaps.append(
                {
                    "field": "comparison_peer_source",
                    "value": None,
                    "impact": (
                        "Only one legal-description source was supplied; absence of a conflict "
                        "is not evidence that deed, title, survey, and assessor sources agree."
                    ),
                }
            )
        return {
            "sources": records,
            "conflicts": conflicts,
            "missing_fields": missing_fields,
            "comparison_gaps": comparison_gaps,
            "sanitization_redactions": sum(record["sanitization_redactions"] for record in records),
            "comparison_convention": (
                "Any mismatch among known normalized values is flagged; no legal-materiality "
                "threshold and no acreage tolerance is applied."
            ),
            "disclaimer": _DISCLAIMER,
        }
    except Exception as exc:
        return {"error": str(exc)}


__all__ = ["compare_legal_descriptions"]
