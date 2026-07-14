"""Cited estoppel-to-lease exception screening with SNDA presence tracking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping

from cre_mcp.leases.models import CitedClaim, LeaseAbstract

ExceptionSeverity = Literal["material", "warning"]


@dataclass(frozen=True)
class EstoppelException:
    field: str
    severity: ExceptionSeverity
    estoppel_value: Any
    lease_value: Any
    lease_side: CitedClaim
    why: str
    what_to_do: str

    @property
    def lease_quote(self) -> str:
        return self.lease_side.quote

    @property
    def lease_cite(self) -> str:
        return self.lease_side.locator


@dataclass
class SNDAPresence:
    lease_reference_present: bool | None = None
    lease_reference: CitedClaim = field(default_factory=lambda: CitedClaim.missing(source="lease"))
    estoppel_acknowledged: bool | None = None
    status: str = "unknown"


class EstoppelComparison(list[EstoppelException]):
    """A true exceptions list carrying honest gaps and SNDA tracking metadata."""

    def __init__(
        self,
        exceptions: Iterable[EstoppelException] = (),
        *,
        gaps: Iterable[str] = (),
        snda: SNDAPresence | None = None,
    ) -> None:
        super().__init__(exceptions)
        self.gaps = sorted(set(gaps))
        self.snda = snda or SNDAPresence()
        self.posture = (
            "Advisory comparison only; exceptions are document discrepancies for review, "
            "not legal conclusions, waivers, or confirmations."
        )

    @property
    def exceptions(self) -> list[EstoppelException]:
        return list(self)


def _coerce_claim(value: Any, *, source: str = "lease") -> CitedClaim:
    if isinstance(value, CitedClaim):
        return value
    if not isinstance(value, Mapping):
        return CitedClaim.missing(source=source)
    if "value" not in value:
        return CitedClaim.missing(source=source)
    status = str(value.get("status", "stated" if value.get("quote") and value.get("locator") else "missing"))
    if status == "missing" or value.get("value") is None:
        return CitedClaim.missing(source=str(value.get("source", source)))
    kwargs = {
        "quote": str(value.get("quote", ""))[:200],
        "locator": str(value.get("locator", "")),
        "confidence": float(value.get("confidence", 1.0)),
        "source": str(value.get("source", source)),
    }
    if not kwargs["quote"] or not kwargs["locator"]:
        return CitedClaim.missing(source=kwargs["source"])
    if status == "inferred":
        return CitedClaim.inferred(value.get("value"), **kwargs)
    return CitedClaim.stated(value.get("value"), **kwargs)


def _mapping_claim(terms: Mapping[str, Any], *paths: str) -> CitedClaim:
    for path in paths:
        current: Any = terms
        found = True
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                found = False
                break
            current = current[part]
        if found:
            claim = _coerce_claim(current)
            if claim.status != "missing":
                return claim
        citations = terms.get("citations")
        if isinstance(citations, Mapping) and path in citations:
            citation = citations[path]
            if isinstance(citation, Mapping):
                combined = dict(citation)
                combined.setdefault("value", current if found else terms.get(path))
                claim = _coerce_claim(combined)
                if claim.status != "missing":
                    return claim
    return CitedClaim.missing(source="lease")


def _fact_rent(facts: Mapping[str, Any]) -> tuple[Any, str | None]:
    rent = facts.get("rent")
    if isinstance(rent, Mapping):
        for basis in ("monthly", "annual", "base_rent", "amount"):
            if basis in rent:
                return rent[basis], basis
        if "value" in rent:
            return rent["value"], str(rent.get("basis")) if rent.get("basis") else None
    return rent, None


def _lease_rent_claim(source: LeaseAbstract | Mapping[str, Any], basis: str | None) -> tuple[CitedClaim, str | None]:
    if isinstance(source, LeaseAbstract):
        for row in source.rent_schedule:
            if basis == "annual" and row.annual.status != "missing":
                return row.annual, "annual"
            if basis in {"monthly", "base_rent", "amount", None} and row.monthly.status != "missing":
                return row.monthly, "monthly"
            if row.annual.status != "missing":
                return row.annual, "annual"
        return CitedClaim.missing(source="lease"), None
    paths: tuple[str, ...]
    if basis == "annual":
        paths = ("annual_rent", "rent.annual", "rent", "base_rent")
    else:
        paths = ("monthly_rent", "rent.monthly", "rent", "base_rent", "annual_rent")
    claim = _mapping_claim(source, *paths)
    inferred_basis = basis
    if inferred_basis is None:
        if any(path in source for path in ("monthly_rent",)):
            inferred_basis = "monthly"
        elif "annual_rent" in source:
            inferred_basis = "annual"
    return claim, inferred_basis


def _expiration_claim(source: LeaseAbstract | Mapping[str, Any]) -> CitedClaim:
    if isinstance(source, LeaseAbstract):
        return source.dates.expiration
    return _mapping_claim(source, "expiration", "dates.expiration", "lease_expiration")


def _options(source: LeaseAbstract | Mapping[str, Any]) -> tuple[set[str], CitedClaim]:
    if isinstance(source, LeaseAbstract):
        claims = [option.option_type for option in source.options if option.option_type.status != "missing"]
        return {_normalize_scalar(claim.value) for claim in claims}, (
            claims[0] if claims else CitedClaim.missing(source="lease")
        )
    claim = _mapping_claim(source, "options", "option_terms")
    if claim.status == "missing":
        return set(), claim
    value = claim.value
    if isinstance(value, Mapping):
        items = value.keys()
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = [value]
    return {_normalize_scalar(item) for item in items}, claim


def _normalize_scalar(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip().casefold())


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d[\d,]*(?:\.\d+)?", value.replace("$", ""))
        if match:
            try:
                return float(match.group(0).replace(",", ""))
            except ValueError:
                return None
    return None


def _different(left: Any, right: Any, *, money: bool = False) -> bool:
    if money:
        left_number, right_number = _number(left), _number(right)
        if left_number is not None and right_number is not None:
            return abs(left_number - right_number) > 0.01
    return _normalize_scalar(left) != _normalize_scalar(right)


def _add_mismatch(
    exceptions: list[EstoppelException],
    *,
    field_name: str,
    severity: ExceptionSeverity,
    estoppel_value: Any,
    lease_claim: CitedClaim,
    detail: str,
) -> None:
    # Every emitted mismatch must satisfy the lease-side citation invariant.
    if lease_claim.status == "missing" or not lease_claim.quote or not lease_claim.locator:
        return
    exceptions.append(
        EstoppelException(
            field=field_name,
            severity=severity,
            estoppel_value=estoppel_value,
            lease_value=lease_claim.value,
            lease_side=lease_claim,
            why=detail + " This is a comparison exception, not a legal conclusion.",
            what_to_do=(
                "Pause reliance on the inconsistent field; reconcile the complete effective lease, "
                "amendments, ledger/source records, and estoppel with property management and CRE counsel."
            ),
        )
    )


def _snda_presence(source: LeaseAbstract | Mapping[str, Any], facts: Mapping[str, Any]) -> SNDAPresence:
    if isinstance(source, Mapping):
        claim = _mapping_claim(source, "snda", "snda_reference", "snda_present")
        if claim.status != "missing":
            lease_present: bool | None = bool(claim.value)
        elif "snda_present" in source and isinstance(source.get("snda_present"), bool):
            lease_present = bool(source["snda_present"])
        else:
            lease_present = None
    else:
        claim = CitedClaim.missing(source="lease")
        lease_present = None
    estoppel_value = facts.get("snda_present", facts.get("snda_acknowledged"))
    acknowledged = bool(estoppel_value) if isinstance(estoppel_value, bool) else None
    if lease_present is None and acknowledged is None:
        status = "unknown_not_supplied"
    elif lease_present is True and acknowledged is True:
        status = "referenced_and_acknowledged"
    elif lease_present is True and acknowledged is not True:
        status = "lease_reference_not_acknowledged_in_estoppel_input"
    elif lease_present is False and acknowledged is True:
        status = "estoppel_mentions_snda_not_present_in_lease_terms_input"
    else:
        status = "no_snda_reported"
    return SNDAPresence(
        lease_reference_present=lease_present,
        lease_reference=claim,
        estoppel_acknowledged=acknowledged,
        status=status,
    )


def compare_estoppel(
    abstract_or_terms: LeaseAbstract | Mapping[str, Any],
    estoppel_facts: Mapping[str, Any],
) -> EstoppelComparison:
    """Return cited lease-side exceptions between lease terms and an estoppel."""
    if not isinstance(abstract_or_terms, (LeaseAbstract, Mapping)):
        raise TypeError("abstract_or_terms must be a LeaseAbstract or mapping")
    if not isinstance(estoppel_facts, Mapping):
        raise TypeError("estoppel_facts must be a mapping")

    exceptions: list[EstoppelException] = []
    gaps: list[str] = []

    estoppel_rent, rent_basis = _fact_rent(estoppel_facts)
    if estoppel_rent is None:
        gaps.append("estoppel_rent_missing")
    else:
        lease_rent, actual_basis = _lease_rent_claim(abstract_or_terms, rent_basis)
        if lease_rent.status == "missing":
            gaps.append("cited_lease_rent_missing")
        elif _different(estoppel_rent, lease_rent.value, money=True):
            _add_mismatch(
                exceptions,
                field_name="rent",
                severity="material",
                estoppel_value=estoppel_rent,
                lease_claim=lease_rent,
                detail=f"Estoppel rent differs from the cited lease-side {actual_basis or 'rent'} amount.",
            )

    estoppel_expiration = estoppel_facts.get("expiration")
    if estoppel_expiration is None:
        gaps.append("estoppel_expiration_missing")
    else:
        lease_expiration = _expiration_claim(abstract_or_terms)
        if lease_expiration.status == "missing":
            gaps.append("cited_lease_expiration_missing")
        elif _different(estoppel_expiration, lease_expiration.value):
            _add_mismatch(
                exceptions,
                field_name="expiration",
                severity="material",
                estoppel_value=estoppel_expiration,
                lease_claim=lease_expiration,
                detail="Estoppel expiration differs from the cited lease expiration.",
            )

    estoppel_options = estoppel_facts.get("options")
    if estoppel_options is None:
        gaps.append("estoppel_options_missing")
    else:
        if isinstance(estoppel_options, Mapping):
            estoppel_option_set = {_normalize_scalar(item) for item in estoppel_options.keys()}
        elif isinstance(estoppel_options, (list, tuple, set)):
            estoppel_option_set = {_normalize_scalar(item) for item in estoppel_options}
        else:
            estoppel_option_set = {_normalize_scalar(estoppel_options)}
        lease_option_set, option_claim = _options(abstract_or_terms)
        if option_claim.status == "missing" and estoppel_option_set:
            gaps.append("cited_lease_options_missing")
        elif estoppel_option_set != lease_option_set:
            _add_mismatch(
                exceptions,
                field_name="options",
                severity="material",
                estoppel_value=sorted(estoppel_option_set),
                lease_claim=option_claim,
                detail=f"Estoppel option list {sorted(estoppel_option_set)} differs from cited lease options {sorted(lease_option_set)}.",
            )

    comparable_fields = (
        ("defaults_claimed", ("defaults_claimed", "defaults"), "material"),
        ("amendments_listed", ("amendments_listed", "amendments"), "warning"),
    )
    for fact_name, lease_paths, severity in comparable_fields:
        fact_value = estoppel_facts.get(fact_name)
        if fact_value is None:
            gaps.append(f"estoppel_{fact_name}_missing")
            continue
        if isinstance(abstract_or_terms, LeaseAbstract):
            lease_claim = CitedClaim.missing(source="lease")
        else:
            lease_claim = _mapping_claim(abstract_or_terms, *lease_paths)
        if lease_claim.status == "missing":
            gaps.append(f"cited_lease_{fact_name}_missing")
        elif _different(fact_value, lease_claim.value):
            _add_mismatch(
                exceptions,
                field_name=fact_name,
                severity=severity,  # type: ignore[arg-type]
                estoppel_value=fact_value,
                lease_claim=lease_claim,
                detail=f"Estoppel {fact_name.replace('_', ' ')} differs from the cited lease-side term.",
            )

    snda = _snda_presence(abstract_or_terms, estoppel_facts)
    if snda.status == "unknown_not_supplied":
        gaps.append("snda_presence_not_supplied_on_either_side")
    elif snda.status in {
        "lease_reference_not_acknowledged_in_estoppel_input",
        "estoppel_mentions_snda_not_present_in_lease_terms_input",
    }:
        gaps.append(f"snda_{snda.status}")

    return EstoppelComparison(exceptions, gaps=gaps, snda=snda)


__all__ = [
    "ExceptionSeverity",
    "EstoppelException",
    "SNDAPresence",
    "EstoppelComparison",
    "compare_estoppel",
]
