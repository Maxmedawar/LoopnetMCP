"""Deterministic text signals for potentially assumable or existing financing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_TEXT_KEYS = ("text", "listing_or_om_text", "listing_text", "om_text")
_INPUT_KEYS = frozenset({*_TEXT_KEYS, "source", "source_label", "document_id"})
_PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("assumable", re.compile(r"\bassumable\b", re.IGNORECASE)),
    (
        "loan_assumption",
        re.compile(r"\bloan[\s-]+assumption\b", re.IGNORECASE),
    ),
    (
        "existing_financing",
        re.compile(r"\bexisting[\s-]+financing\b", re.IGNORECASE),
    ),
    (
        "seller_financing_available",
        re.compile(r"\bseller[\s-]+financing[\s-]+available\b", re.IGNORECASE),
    ),
)
_EXISTING_LOAN = re.compile(r"\bexisting[\s-]+loan\b", re.IGNORECASE)
_RATE = re.compile(
    r"(?<![\d.])(?:\d{1,2}(?:\.\d{1,4})?)\s*(?:%|percent\b)",
    re.IGNORECASE,
)
_RATE_PROXIMITY_CHARS = 120


def _unknown_keys(value: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    raw = [
        str(key)
        for key in value
        if not isinstance(key, str) or key not in _INPUT_KEYS
    ]
    return sorted(set(raw)), sorted({f"listing_or_om_text.{key}" for key in raw})


def _input(
    value: str | Mapping[str, Any],
) -> tuple[str, str, list[str], list[str]]:
    if isinstance(value, str):
        text = value
        source = "listing_or_om_text"
        unknown: list[str] = []
        unknown_paths: list[str] = []
    elif isinstance(value, Mapping):
        present = [key for key in _TEXT_KEYS if value.get(key) is not None]
        if not present:
            raise ValueError(
                "listing_or_om_text mapping requires text, listing_or_om_text, "
                "listing_text, or om_text"
            )
        text = str(value[present[0]])
        conflicting = {
            str(value[key]) for key in present if str(value[key]) != text
        }
        if conflicting:
            raise ValueError("conflicting text fields in listing_or_om_text mapping")
        source = str(
            value.get("source")
            or value.get("source_label")
            or value.get("document_id")
            or "listing_or_om_text"
        ).strip()
        source = source or "listing_or_om_text"
        unknown, unknown_paths = _unknown_keys(value)
    else:
        raise ValueError("listing_or_om_text must be text or a mapping containing text")
    if not text.strip():
        raise ValueError("listing_or_om_text cannot be blank")
    return text, source, unknown, unknown_paths


def _citation(
    text: str,
    source: str,
    *,
    start: int,
    end: int,
    flag: str,
    matched_text: str,
) -> dict[str, Any]:
    context_start = max(0, start - 80)
    context_end = min(len(text), end + 80)
    context = text[context_start:context_end].strip()
    excerpt = text[start:end]
    return {
        "flag": flag,
        "matched_text": matched_text,
        "offsets": {"start": start, "end": end},
        "citation": {
            "source": source,
            "start_char": start,
            "end_char": end,
            "line": text.count("\n", 0, start) + 1,
            "excerpt": context,
        },
        "excerpt": excerpt,
    }


def _rate_hits(text: str, source: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    rates = list(_RATE.finditer(text))
    for loan_match in _EXISTING_LOAN.finditer(text):
        for rate_match in rates:
            gap = max(
                loan_match.start() - rate_match.end(),
                rate_match.start() - loan_match.end(),
                0,
            )
            if gap > _RATE_PROXIMITY_CHARS:
                continue
            span = (
                min(loan_match.start(), rate_match.start()),
                max(loan_match.end(), rate_match.end()),
            )
            if span in seen:
                continue
            seen.add(span)
            hits.append(
                _citation(
                    text,
                    source,
                    start=span[0],
                    end=span[1],
                    flag="existing_loan_rate",
                    matched_text=text[span[0] : span[1]],
                )
            )
    return hits


def detect_assumable(
    listing_or_om_text: str | Mapping[str, Any],
) -> dict[str, Any]:
    """Return cited language hits without claiming that debt is assumable.

    This is a deterministic language screen.  It does not interpret loan
    documents, determine transferability, or presume lender consent.
    """

    text, source, unrecognized, unrecognized_paths = _input(listing_or_om_text)
    hits: list[dict[str, Any]] = []
    for flag, pattern in _PHRASES:
        for match in pattern.finditer(text):
            hits.append(
                _citation(
                    text,
                    source,
                    start=match.start(),
                    end=match.end(),
                    flag=flag,
                    matched_text=match.group(0),
                )
            )
    hits.extend(_rate_hits(text, source))
    hits.sort(
        key=lambda item: (
            int(item["citation"]["start_char"]),
            str(item["flag"]),
        )
    )
    flags = list(dict.fromkeys(str(hit["flag"]) for hit in hits))
    detected = bool(hits)
    return {
        "detected": detected,
        "assumable_signal": detected,
        "classification": (
            "potential_existing_or_assumable_financing_language"
            if detected
            else "no_assumable_or_existing_financing_language_detected"
        ),
        "flags": flags,
        "cited_hits": hits,
        "hits": hits,
        "hit_count": len(hits),
        "source": source,
        "handoff": {
            "function": "cre_mcp.debt.value_assumable_debt",
            "note": (
                "If verified loan terms, market debt terms, price, and hold period "
                "are available, hand off to debt.value_assumable_debt. Detection "
                "alone does not establish assumability or lender consent."
            ),
        },
        "caveat": (
            "Language screen only. Review the executed note and loan documents and "
            "confirm assumption conditions, fees, consent, and guarantor release "
            "with the lender and counsel."
        ),
        "unrecognized_inputs": sorted(set(unrecognized + unrecognized_paths)),
        "unrecognized_input_paths": unrecognized_paths,
    }


__all__ = ["detect_assumable"]
