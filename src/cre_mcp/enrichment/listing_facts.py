"""Deterministic, offline extraction of headline facts from listing prose."""

from __future__ import annotations

import re

from cre_mcp.models.enrichment import ListingFacts
from cre_mcp.models.listings import Listing
from cre_mcp.underwriting.metrics import TENANT_CREDIT_TABLE

# Keyword policy stays declarative so extraction behavior can be tuned without
# changing the routing algorithm. More specific strategies intentionally win.
STRATEGY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "nnn_retail": (
        "absolute nnn",
        "absolute-nnn",
        "absolute net",
        "triple net",
        "triple-net",
        "nnn lease",
        "nnn investment",
        "single tenant",
        "single-tenant",
        "net leased",
        "net-leased",
    ),
    "value_add_multifamily": (
        "multifamily",
        "multi-family",
        "apartment",
        "apartments",
        "apartment community",
        "apartment units",
        "value-add units",
    ),
    "location_retail": (
        "storefront",
        "street retail",
        "hard corner",
        "signalized corner",
        "retail condo",
        "ground-floor retail",
        "ground floor retail",
    ),
}

PROPERTY_TYPE_STRATEGIES = {
    "multifamily": "value_add_multifamily",
    "multi-family": "value_add_multifamily",
    "apartment": "value_add_multifamily",
    "apartments": "value_add_multifamily",
    "retail": "location_retail",
}

LEASE_YEAR_PATTERNS = (
    r"(?P<years>\d+(?:\.\d+)?)\s*(?:-|\s)?(?:year|yr)s?\b.{0,45}\blease\b",
    r"\blease\b.{0,45}?(?P<years>\d+(?:\.\d+)?)\s*(?:-|\s)?(?:year|yr)s?\b",
    r"(?P<years>\d+(?:\.\d+)?)\s*(?:year|yr)s?\s+(?:of\s+)?(?:term\s+)?remaining\b",
    r"(?:remaining\s+(?:lease\s+)?term|lease\s+term)\D{0,20}"
    r"(?P<years>\d+(?:\.\d+)?)\s*(?:year|yr)s?\b",
)

ANNUAL_ESCALATION_PATTERNS = (
    r"(?P<pct>\d+(?:\.\d+)?)\s*%\s*"
    r"(?:annual|annually|per\s+year|yearly)(?:\s+rent)?"
    r"(?:\s+(?:increase|increases|bump|bumps|escalation|escalations))?",
    r"(?:annual|yearly)(?:\s+rent)?\s+"
    r"(?:increase|increases|bump|bumps|escalation|escalations)"
    r"(?:\s+of)?\s*(?P<pct>\d+(?:\.\d+)?)\s*%",
)
PERIODIC_ESCALATION_PATTERN = (
    r"(?P<pct>\d+(?:\.\d+)?)\s*%\s*(?:increase|increases|bump|bumps|escalation|escalations)?"
    r"\s*(?:every|each)\s*(?P<years>\d+(?:\.\d+)?)\s*(?:year|yr)s?\b"
)
FLAT_RENT_KEYWORDS = (
    "flat rent",
    "flat lease",
    "no rent increases",
    "no rental increases",
    "no rent bumps",
)

PURITY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\babsolute(?:\s+|-)(?:nnn|triple[ -]net|net)\b", "absolute"),
    (r"\b(?:nnn|triple[ -]net)\b", "nnn"),
    (r"\b(?:nn|double[ -]net)\b", "nn"),
    (r"\b(?:modified\s+gross|full[ -]service\s+gross|gross\s+lease)\b", "gross"),
)

GUARANTY_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"\b(?:franchisee|franchise)[ -]?(?:guaranty|guarantee|guaranteed|operated)\b",
        "franchisee",
    ),
    (
        r"\b(?:corporate|investment[ -]grade)[ -]?(?:guaranty|guarantee|guaranteed)\b",
        "corporate",
    ),
)

TENANT_PATTERNS = (
    r"\b(?:leased\s+to|occupied\s+by)\s+"
    r"(?P<tenant>[A-Z0-9][A-Za-z0-9&'\u2019.\- ]{1,60}?)"
    r"(?=\s+(?:under|on|with|for)\b|[,.;]|$)",
    r"\btenant\s*(?:is|:)\s*"
    r"(?P<tenant>[A-Z0-9][A-Za-z0-9&'\u2019.\- ]{1,60}?)"
    r"(?=\s+(?:under|on|with|for)\b|[,.;]|$)",
)

TENANT_CONTEXT_WORDS = (
    "lease",
    "leased",
    "tenant",
    "store",
    "restaurant",
    "pharmacy",
)
AMBIGUOUS_TENANT_FOLLOWERS = {
    "target": ("cap", "price", "rent", "return", "score", "yield"),
}

GENERIC_TITLE_WORDS = {
    "absolute",
    "brand-new",
    "building",
    "commercial",
    "deal",
    "investment",
    "lease",
    "leased",
    "nnn",
    "offering",
    "property",
    "retail",
    "sale",
    "single-tenant",
    "triple-net",
}


def _prose(listing: Listing) -> str:
    values = [
        listing.name,
        listing.description,
        *listing.highlights,
        listing.property_type,
        listing.property_subtype,
    ]
    return " ".join(str(value).strip() for value in values if value).strip()


def _strategy(text: str, listing: Listing) -> str:
    normalized = text.casefold()
    for strategy, keywords in STRATEGY_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return strategy
    property_values = " ".join(
        value.casefold()
        for value in (listing.property_type, listing.property_subtype)
        if value
    )
    for property_keyword, strategy in PROPERTY_TYPE_STRATEGIES.items():
        if property_keyword in property_values:
            return strategy
    return "generic"


def _lease_years(text: str) -> float | None:
    for pattern in LEASE_YEAR_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group("years"))
    return None


def _rent_escalations(text: str) -> float | None:
    for pattern in ANNUAL_ESCALATION_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group("pct"))
    match = re.search(PERIODIC_ESCALATION_PATTERN, text, flags=re.IGNORECASE)
    if match:
        years = float(match.group("years"))
        return float(match.group("pct")) / years if years > 0 else None
    normalized = text.casefold()
    if any(keyword in normalized for keyword in FLAT_RENT_KEYWORDS):
        return 0.0
    return None


def _nnn_purity(text: str) -> str | None:
    for pattern, category in PURITY_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return category
    return None


def _guaranty(text: str) -> str | None:
    for pattern, category in GUARANTY_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return category
    return None


def _known_tenant(text: str, *, require_context: bool = False) -> str | None:
    for tenant in sorted(TENANT_CREDIT_TABLE, key=len, reverse=True):
        match = re.search(
            rf"(?<![\w-]){re.escape(tenant)}(?![\w-])",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            following = text[match.end() : match.end() + 24].casefold().lstrip(" -:|")
            blocked = AMBIGUOUS_TENANT_FOLLOWERS.get(tenant, ())
            if any(following.startswith(word) for word in blocked):
                continue
            if require_context:
                window = text[max(0, match.start() - 32) : match.end() + 32].casefold()
                if not any(word in window for word in TENANT_CONTEXT_WORDS):
                    continue
            return match.group(0).strip()
    return None


def _tenant_name(text: str, title: str) -> str | None:
    known = _known_tenant(title)
    if known:
        return known
    for pattern in TENANT_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group("tenant").strip(" -")
    known = _known_tenant(text, require_context=True)
    if known:
        return known
    candidate = re.split(r"\s+(?:\||-|\u2013|\u2014)\s+|:\s+", title, maxsplit=1)[0]
    words = {word.casefold().strip(".,()") for word in candidate.split()}
    if (
        0 < len(candidate.split()) <= 5
        and not words.intersection(GENERIC_TITLE_WORDS)
        and re.search(r"[A-Za-z]", candidate)
    ):
        return candidate.strip()
    return None


def extract_facts(listing: Listing) -> ListingFacts:
    """Extract routing and headline lease facts without network or model calls."""
    text = _prose(listing)
    return ListingFacts(
        strategy_hint=_strategy(text, listing),
        lease_years_remaining=_lease_years(text),
        rent_escalations=_rent_escalations(text),
        nnn_purity=_nnn_purity(text),
        tenant_name=_tenant_name(text, listing.name),
        guaranty=_guaranty(text),
    )


__all__ = [
    "FLAT_RENT_KEYWORDS",
    "GUARANTY_PATTERNS",
    "LEASE_YEAR_PATTERNS",
    "PROPERTY_TYPE_STRATEGIES",
    "PURITY_PATTERNS",
    "STRATEGY_KEYWORDS",
    "extract_facts",
]
