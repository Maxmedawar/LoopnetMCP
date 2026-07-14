"""Cross-document obligation collision screening.

The synonym table below is a deliberately small screening convention, not an
industry taxonomy or legal interpretation.  Exact/synonym matches are marked
``confirmed_overlap``; broader family resemblance is never cleared silently and
is returned as ``possible_conflict`` for counsel to interpret against the full
documents, amendments, recorded priority, and deal facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from cre_mcp.leases.models import CitedClaim
from cre_mcp.obligations.restrictions import RestrictionSet

CollisionType = Literal[
    "exclusive_use_conflict",
    "prohibited_use",
    "radius_violation",
    "cotenancy_risk",
    "rofr_blocks_deal",
    "assignment_blocked",
]
CollisionSeverity = Literal["fatal", "material", "warning"]
MatchStatus = Literal["confirmed_overlap", "possible_conflict"]

# CONVENTION: a small, transparent synonym map for first-pass CRE use screens.
# Absence from this table never proves that two uses do not overlap.
USE_CATEGORY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "coffee_shop": ("coffee", "coffee shop", "coffeehouse", "cafe", "café", "espresso"),
    "pizza_restaurant": ("pizza", "pizzeria", "pizza restaurant", "italian restaurant"),
    "fitness": ("fitness", "gym", "health club", "workout", "exercise studio"),
    "pharmacy": ("pharmacy", "drugstore", "drug store", "apothecary"),
    "grocery": ("grocery", "grocery store", "supermarket", "food market"),
    "convenience_store": ("convenience store", "corner store", "mini mart", "minimart"),
    "liquor_store": ("liquor", "liquor store", "package store", "wine shop"),
    "cannabis": ("cannabis", "marijuana", "dispensary"),
    "salon": ("salon", "hair salon", "barber", "barbershop", "nail salon"),
    "bank": ("bank", "credit union", "financial institution"),
}

_FAMILY_TERMS: dict[str, tuple[str, ...]] = {
    "food_service": (
        "restaurant", "food", "dining", "cafe", "coffee", "pizza", "bakery",
        "pastry", "prepared food", "beverage", "espresso", "italian",
    ),
    "health_fitness": ("fitness", "gym", "exercise", "workout", "wellness", "health club"),
    "medical_retail": ("pharmacy", "drugstore", "medical", "clinic", "health"),
    "general_retail": ("retail", "store", "shop", "merchandise", "market"),
}

_STOPWORDS = {
    "a", "an", "and", "any", "as", "at", "be", "business", "by", "center",
    "for", "from", "in", "including", "is", "landlord", "lease", "of", "or",
    "other", "premises", "property", "sale", "shall", "shopping", "space", "tenant",
    "the", "to", "use", "used", "uses", "with",
}


@dataclass(frozen=True)
class CollisionSide:
    """One quoted side of a possible cross-document conflict."""

    quote: str
    cite: str
    source: str
    status: str


@dataclass(frozen=True)
class Collision:
    """Advisory collision flag; deliberately not a legal conclusion."""

    type: CollisionType
    severity: CollisionSeverity
    side_a: CollisionSide
    side_b: CollisionSide
    why: str
    counsel_question: str
    match_status: MatchStatus


def _claim_from(value: Any, *, source: str = "base") -> CitedClaim:
    if isinstance(value, CitedClaim):
        return value
    if isinstance(value, Mapping):
        status = str(value.get("status", "missing"))
        if status == "stated":
            return CitedClaim.stated(
                value.get("value"),
                quote=str(value.get("quote", ""))[:200],
                locator=str(value.get("locator", "")),
                confidence=float(value.get("confidence", 0.0)),
                source=str(value.get("source", source)),
            )
        if status == "inferred":
            return CitedClaim.inferred(
                value.get("value"),
                quote=str(value.get("quote", ""))[:200],
                locator=str(value.get("locator", "")),
                confidence=float(value.get("confidence", 0.0)),
                source=str(value.get("source", source)),
            )
    return CitedClaim.missing(source=source)


def _restriction_sets(values: Sequence[Any]) -> list[RestrictionSet]:
    results: list[RestrictionSet] = []
    claim_fields = (
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
    for value in values:
        if isinstance(value, RestrictionSet):
            results.append(value)
            continue
        if not isinstance(value, Mapping):
            raise TypeError("existing_restrictions must contain RestrictionSet or mapping values")
        kind = str(value.get("kind", "lease"))
        if kind not in {"lease", "ccr"}:
            raise ValueError("restriction kind must be lease or ccr")
        kwargs: dict[str, Any] = {"kind": kind}
        for name in claim_fields:
            kwargs[name] = [_claim_from(item, source=kind) for item in value.get(name, [])]
        kwargs["missing_fields"] = list(value.get("missing_fields", []))
        kwargs["sanitization_redactions"] = int(value.get("sanitization_redactions", 0))
        results.append(RestrictionSet(**kwargs))
    return results


def _normalize(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).casefold()).strip()


def _contains(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize(phrase)
    return bool(re.search(rf"(?:^|\s){re.escape(normalized_phrase)}(?:$|\s)", text))


def _categories(text: str) -> set[str]:
    normalized = _normalize(text)
    return {
        category
        for category, synonyms in USE_CATEGORY_SYNONYMS.items()
        if any(_contains(normalized, synonym) for synonym in synonyms)
    }


def _families(text: str) -> set[str]:
    normalized = _normalize(text)
    return {
        family
        for family, terms in _FAMILY_TERMS.items()
        if any(_contains(normalized, term) for term in terms)
    }


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _normalize(text).split()
        if len(token) >= 4 and token not in _STOPWORDS
    }


def _overlap(restriction_text: str, proposed_text: str) -> MatchStatus | None:
    left_categories = _categories(restriction_text)
    right_categories = _categories(proposed_text)
    if left_categories & right_categories:
        return "confirmed_overlap"

    left_tokens = _tokens(restriction_text)
    right_tokens = _tokens(proposed_text)
    if left_tokens & right_tokens:
        return "confirmed_overlap"

    left_families = _families(restriction_text)
    right_families = _families(proposed_text)
    if left_families & right_families:
        # A blanket restaurant restriction is broad enough for a deterministic
        # screen; narrower neighboring food uses stay possible, not cleared.
        if re.search(r"\b(?:any|all)\s+restaurants?\b|\brestaurant\s+use\b", restriction_text, re.I):
            return "confirmed_overlap"
        return "possible_conflict"
    return None


def _claim_text(claim: CitedClaim, keys: tuple[str, ...]) -> str:
    value = claim.value
    if isinstance(value, Mapping):
        pieces = [str(value.get(key, "")) for key in keys]
        return " ".join(piece for piece in pieces if piece).strip() or claim.quote
    return str(value or claim.quote)


def _side(claim: CitedClaim) -> CollisionSide:
    return CollisionSide(
        quote=claim.quote,
        cite=claim.locator,
        source=claim.source,
        status=claim.status,
    )


def _structured_claim(value: Any, *, locator: str, quote: str | None = None) -> CitedClaim:
    rendered = str(quote if quote is not None else value).strip() or "structured input supplied"
    return CitedClaim.stated(
        value,
        quote=rendered[:200],
        locator=locator,
        confidence=1.0,
        source="structured_input",
    )


def _proposed_claim(proposed: Mapping[str, Any]) -> CitedClaim:
    quote = " | ".join(
        str(proposed.get(key, "")).strip()
        for key in ("tenant_name", "category", "use_description")
        if str(proposed.get(key, "")).strip()
    )
    return _structured_claim(dict(proposed), locator="proposed use input", quote=quote)


def _collision(
    collision_type: CollisionType,
    claim: CitedClaim,
    proposed_claim: CitedClaim,
    status: MatchStatus,
    *,
    confirmed_severity: CollisionSeverity,
    why: str,
    question: str,
) -> Collision:
    severity: CollisionSeverity = confirmed_severity if status == "confirmed_overlap" else "material"
    prefix = "possible_conflict: " if status == "possible_conflict" else "screened overlap: "
    return Collision(
        type=collision_type,
        severity=severity,
        side_a=_side(claim),
        side_b=_side(proposed_claim),
        why=prefix + why + " This flag is not a legal conclusion.",
        counsel_question=f"Ask CRE counsel: {question}",
        match_status=status,
    )


def _portfolio_evidence(site: Mapping[str, Any]) -> CitedClaim:
    quote = " | ".join(f"{key}={value}" for key, value in site.items())
    return _structured_claim(dict(site), locator="portfolio_sites input", quote=quote)


def detect_collisions(context: Mapping[str, Any]) -> list[Collision]:
    """Flag cited restriction/proposal collisions without making legal conclusions."""
    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping")
    proposed = context.get("proposed")
    if not isinstance(proposed, Mapping):
        raise ValueError("context.proposed must be a mapping")
    restrictions = _restriction_sets(list(context.get("existing_restrictions", [])))
    proposed_claim = _proposed_claim(proposed)
    proposed_text = " ".join(
        str(proposed.get(key, "")) for key in ("use_description", "category")
    ).strip()
    collisions: list[Collision] = []

    for restriction_set in restrictions:
        for claim in restriction_set.exclusive_uses:
            scope = _claim_text(claim, ("scope",))
            status = _overlap(scope, proposed_text)
            if status:
                collisions.append(
                    _collision(
                        "exclusive_use_conflict",
                        claim,
                        proposed_claim,
                        status,
                        confirmed_severity="fatal",
                        why="The proposed use overlaps or may overlap a cited exclusive-use scope",
                        question=(
                            "Does the cited exclusive bind this space and proposed use after reviewing "
                            "defined terms, exceptions, amendments, waivers, and recorded documents?"
                        ),
                    )
                )

        for claim in restriction_set.prohibited_uses:
            scope = _claim_text(claim, ("uses", "scope"))
            status = _overlap(scope, proposed_text)
            if status:
                collisions.append(
                    _collision(
                        "prohibited_use",
                        claim,
                        proposed_claim,
                        status,
                        confirmed_severity="fatal",
                        why="The proposed use overlaps or may overlap cited prohibited-use language",
                        question=(
                            "Does the prohibition apply to this parcel, premises, tenant, and proposed "
                            "operations, and is any consent, exception, amendment, or waiver effective?"
                        ),
                    )
                )

        for claim in restriction_set.radius_restrictions:
            value = claim.value if isinstance(claim.value, Mapping) else {}
            if not value.get("restricted", True):
                continue
            radius = value.get("radius_miles")
            if not isinstance(radius, (int, float)):
                continue
            for raw_site in context.get("portfolio_sites", []) or []:
                if not isinstance(raw_site, Mapping):
                    continue
                distance = raw_site.get("distance_miles", raw_site.get("distance_to_proposed_miles"))
                if not isinstance(distance, (int, float)) or float(distance) > float(radius):
                    continue
                holder = _normalize(value.get("holder", ""))
                tenant = _normalize(proposed.get("tenant_name", ""))
                holder_is_generic = not holder or "not named" in holder or holder == "tenant"
                if tenant and holder and not holder_is_generic and tenant not in holder and holder not in tenant:
                    continue
                site_text = " ".join(
                    str(raw_site.get(key, "")) for key in ("use_description", "category")
                )
                use_status = _overlap(str(value.get("scope", "")), site_text or proposed_text)
                status: MatchStatus = "confirmed_overlap" if use_status == "confirmed_overlap" and not holder_is_generic else "possible_conflict"
                collisions.append(
                    _collision(
                        "radius_violation",
                        claim,
                        _portfolio_evidence(raw_site),
                        status,
                        confirmed_severity="fatal",
                        why=f"A supplied portfolio-site distance ({distance} miles) is within the cited {radius}-mile radius",
                        question=(
                            "Does the radius covenant apply to this tenant, affiliate, use, measurement "
                            "method, and site, and what consent or remedy language governs?"
                        ),
                    )
                )

        for claim in restriction_set.cotenancy_conditions:
            value = claim.value if isinstance(claim.value, Mapping) else {}
            anchors = {_normalize(item) for item in value.get("named_anchors", [])}
            threshold = value.get("occupancy_threshold_pct")
            confirmed = False
            evidence = proposed_claim
            for raw_site in context.get("portfolio_sites", []) or []:
                if not isinstance(raw_site, Mapping):
                    continue
                site_anchor = _normalize(raw_site.get("anchor_name", raw_site.get("name", "")))
                if anchors and site_anchor in anchors and raw_site.get("is_open") is False:
                    confirmed = True
                    evidence = _portfolio_evidence(raw_site)
                    break
                occupancy = raw_site.get("occupancy_pct")
                if isinstance(threshold, (int, float)) and isinstance(occupancy, (int, float)) and float(occupancy) < float(threshold):
                    confirmed = True
                    evidence = _portfolio_evidence(raw_site)
                    break
            status = "confirmed_overlap" if confirmed else "possible_conflict"
            collisions.append(
                _collision(
                    "cotenancy_risk",
                    claim,
                    evidence,
                    status,
                    confirmed_severity="material",
                    why="The cited co-tenancy condition or remedy may be affected; current anchor and occupancy facts are required",
                    question=(
                        "Are every named-anchor, occupancy, cure-period, replacement-tenant, and remedy "
                        "condition satisfied immediately before and after the proposed deal?"
                    ),
                )
            )

        for claim in restriction_set.rofr_rofo_rights:
            value = claim.value if isinstance(claim.value, Mapping) else {}
            scope = str(value.get("scope", "unknown"))
            deal_scope = str(proposed.get("deal_scope", "space"))
            if scope == "whole_property" and deal_scope not in {"whole_property", "sale", "unknown"}:
                continue
            collisions.append(
                _collision(
                    "rofr_blocks_deal",
                    claim,
                    proposed_claim,
                    "possible_conflict",
                    confirmed_severity="material",
                    why="A cited first-refusal/first-offer right may condition deal sequencing for the stated scope",
                    question=(
                        "Is this transaction within the right's defined scope, and have notice, offer, "
                        "matching, waiver, expiration, and amendment requirements been satisfied?"
                    ),
                )
            )

        intended = str(proposed.get("intended", proposed.get("transaction_type", ""))).casefold()
        if intended in {"assignment", "sublease", "master_lease", "transfer_of_control"}:
            for claim in restriction_set.assignment_subletting_clauses:
                value = claim.value if isinstance(claim.value, Mapping) else {}
                if value.get("standard") != "prohibited":
                    continue
                applies = set(value.get("applies_to", []))
                caught = intended in applies
                if intended == "master_lease":
                    caught = bool(applies & {"assignment", "sublease"}) or not applies
                if not caught and applies:
                    continue
                collisions.append(
                    _collision(
                        "assignment_blocked",
                        claim,
                        proposed_claim,
                        "confirmed_overlap",
                        confirmed_severity="fatal",
                        why=f"The intended {intended} encounters cited absolute transfer-prohibition language",
                        question=(
                            "Does counsel agree the intended structure is an assignment, sublease, or "
                            "other transfer under the complete lease and amendments, and is consent or "
                            "a restructuring path available?"
                        ),
                    )
                )

    unique: list[Collision] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in collisions:
        key = (item.type, item.side_a.cite, item.side_b.cite, item.match_status)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


__all__ = [
    "CollisionType",
    "CollisionSeverity",
    "MatchStatus",
    "CollisionSide",
    "Collision",
    "USE_CATEGORY_SYNONYMS",
    "detect_collisions",
]
