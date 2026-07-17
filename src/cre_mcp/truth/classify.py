"""Detect what KIND of document we parsed (drives the authority ladder later).

Deterministic keyword matching over the filename/origin plus the first page of
text. Never guesses high-authority kinds (lease/estoppel) from weak signals — an
unrecognized document stays ``UNKNOWN`` so reconciliation treats it as lowest
authority rather than over-trusting it.
"""

from __future__ import annotations

import re

from cre_mcp.truth.models import DocKind
from cre_mcp.truth.parsers.base import ParsedDoc

# (DocKind, keyword patterns). Order matters: more specific kinds first.
_RULES: tuple[tuple[DocKind, tuple[str, ...]], ...] = (
    (DocKind.AMENDMENT, ("lease amendment", "amendment to lease", "first amendment", "amendment no")),
    (DocKind.ESTOPPEL, ("estoppel",)),
    (DocKind.RENT_ROLL, ("rent roll", "rentroll", "tenant roster", "rent schedule")),
    (DocKind.T12, ("t-12", "t12", "trailing 12", "trailing twelve", "operating statement",
                   "income statement", "profit and loss", "profit & loss", "p&l")),
    (DocKind.BANK_STMT, ("bank statement", "account statement", "general ledger")),
    (DocKind.TAX_BILL, ("property tax bill", "tax bill", "notice of assessed value",
                        "tax statement")),
    (DocKind.ASSESSOR, ("assessor", "parcel detail", "property record card")),
    (DocKind.APPRAISAL, ("appraisal report", "uniform appraisal", "restricted appraisal")),
    (DocKind.SURVEY, ("alta/nsps", "boundary survey", "land title survey")),
    (DocKind.LEASE, ("lease agreement", "commercial lease", "net lease", "triple net lease",
                     "nnn lease", "ground lease")),
    (DocKind.OM, ("offering memorandum", "offering memo", "investment offering",
                  "confidential offering", "marketing package", "om ")),
    (DocKind.LISTING, ("listing", "marketing flyer")),
)


def classify(doc: ParsedDoc, *, origin: str | None = None, declared: str | None = None) -> DocKind:
    """Return the most likely DocKind for a parsed document.

    ``declared`` (an explicit caller-provided kind) wins when valid; otherwise we
    match keywords over the filename/origin and the first ~2 pages of text.
    """
    if declared:
        try:
            return DocKind(declared.strip().lower())
        except ValueError:
            pass

    hay = " ".join(
        part.lower()
        for part in (
            origin or "",
            "\n".join(page.text for page in doc.pages[:2]),
        )
    )
    hay = re.sub(r"\s+", " ", hay)

    for kind, keywords in _RULES:
        if any(kw in hay for kw in keywords):
            return kind

    # Structural fallback: exported statements/rolls often lack a clean title.
    return _structural_kind(doc)


def _structural_kind(doc: ParsedDoc) -> DocKind:
    """Infer kind from the figures present when no title keyword matched."""
    text = re.sub(r"\s+", " ", doc.full_text.lower())
    has_noi = "net operating income" in text or re.search(r"\bnoi\b", text) is not None
    has_expenses = "operating expenses" in text or "total expenses" in text
    has_rent = "potential rent" in text or "gross rent" in text or "gross scheduled" in text

    # Rent roll: per-tenant rent lines (tenant/suite/unit + rent, usually with lease terms).
    tenant_like = "tenant" in text or "suite" in text or re.search(r"\bunit\b", text) is not None
    if tenant_like and "rent" in text and ("lease" in text or "expir" in text or "sq" in text):
        return DocKind.RENT_ROLL

    if has_noi and (has_expenses or has_rent):
        return DocKind.T12
    return DocKind.UNKNOWN


__all__ = ["classify"]
