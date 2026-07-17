"""Transparent, assessor-record sale-leaseback candidate heuristics.

This module deliberately does not claim that matching names prove occupancy or
sale intent.  It only identifies records that may warrant direct diligence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
import unicodedata
from typing import Any


TOKEN_OVERLAP_THRESHOLD = 0.5
_RECOGNIZED_FIELDS = frozenset(
    {"owner_name", "business_name", "use", "assessed_value", "sf"}
)
_ENTITY_TOKENS = frozenset(
    {
        "co",
        "company",
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "llc",
        "llp",
        "lp",
        "ltd",
        "limited",
        "plc",
    }
)


def _name_tokens(value: object) -> list[str]:
    """Return meaningful comparison tokens, excluding entity-form suffixes."""

    if value is None:
        return []
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    # Treat punctuated legal forms (for example, L.L.C.) as one token.
    text = re.sub(r"\bl[\W_]*l[\W_]*c\b", " llc ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bl[\W_]*l[\W_]*p\b", " llp ", text, flags=re.IGNORECASE)
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    return sorted({token for token in tokens if token not in _ENTITY_TOKENS})


def _records_or_empty(records: Sequence[Mapping[str, Any]] | None) -> Sequence[Mapping[str, Any]]:
    if records is None:
        return ()
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise ValueError("records must be a sequence of mappings or null")
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"records[{index}] must be a mapping")
    return records


def sale_leaseback_candidates(
    records: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Screen records for a possible owner-occupier name match.

    The overlap coefficient is ``common tokens / smaller token-set size``.
    A score at or above :data:`TOKEN_OVERLAP_THRESHOLD` is returned as a
    candidate.  It is an inference only; it is not evidence of occupancy,
    willingness to sell, credit, or the feasibility of a leaseback.
    """

    source_records = _records_or_empty(records)
    candidates: list[dict[str, Any]] = []
    assessments: list[dict[str, Any]] = []
    all_unrecognized: set[str] = set()

    for index, record in enumerate(source_records):
        owner_tokens = _name_tokens(record.get("owner_name"))
        business_tokens = _name_tokens(record.get("business_name"))
        common_tokens = sorted(set(owner_tokens).intersection(business_tokens))
        denominator = min(len(owner_tokens), len(business_tokens))
        overlap = len(common_tokens) / denominator if denominator else 0.0
        is_candidate = bool(denominator and overlap >= TOKEN_OVERLAP_THRESHOLD)
        unrecognized = sorted(set(record).difference(_RECOGNIZED_FIELDS))
        all_unrecognized.update(unrecognized)

        if not owner_tokens:
            reason = "No usable owner-name tokens; the heuristic could not be applied."
        elif not business_tokens:
            reason = "No usable business-name tokens; the heuristic could not be applied."
        elif is_candidate:
            reason = (
                "Owner and business names share "
                f"{len(common_tokens)} token(s), meeting the {TOKEN_OVERLAP_THRESHOLD:.2f} "
                "overlap-coefficient convention."
            )
        else:
            reason = (
                "Owner/business token overlap is below the "
                f"{TOKEN_OVERLAP_THRESHOLD:.2f} convention threshold."
            )

        assessment: dict[str, Any] = {
            "record_index": index,
            "owner_name": record.get("owner_name"),
            "business_name": record.get("business_name"),
            "use": record.get("use"),
            "assessed_value": record.get("assessed_value"),
            "sf": record.get("sf"),
            "is_candidate": is_candidate,
            "signal_label": "HEURISTIC INFERENCE" if is_candidate else "HEURISTIC SCREEN",
            "basis": {
                "method": "owner/business normalized-token overlap coefficient",
                "owner_tokens": owner_tokens,
                "business_tokens": business_tokens,
                "common_tokens": common_tokens,
                "overlap_coefficient": round(overlap, 4),
                "threshold": TOKEN_OVERLAP_THRESHOLD,
            },
            "why": reason,
            "unrecognized_fields": unrecognized,
        }
        assessments.append(assessment)
        if is_candidate:
            candidate = dict(assessment)
            candidate["inference"] = (
                "Name similarity suggests possible owner occupancy; it does not establish "
                "occupancy or owner intent."
            )
            candidate["diligence"] = "verify occupancy and financials directly"
            candidates.append(candidate)

    return {
        "methodology": {
            "label": "HEURISTIC; owner-occupancy is an inference",
            "basis": "normalized owner-name and business-name token overlap",
            "overlap_coefficient": "shared token count / smaller token-set size",
            "threshold": TOKEN_OVERLAP_THRESHOLD,
        },
        "record_count": len(source_records),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "assessments": assessments,
        "unrecognized_input_fields": sorted(all_unrecognized),
        "diligence": "verify occupancy and financials directly",
    }


__all__ = ["TOKEN_OVERLAP_THRESHOLD", "sale_leaseback_candidates"]
