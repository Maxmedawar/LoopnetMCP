"""Unregistered plain-function surfaces for the lease engine.

The director can wire these functions into FastMCP.  They return JSON-friendly
dictionaries with an explicit honesty block rather than hiding sparse coverage
or required calculation inputs.
"""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from cre_mcp.leases.abstract import abstract_lease
from cre_mcp.leases.dates import critical_dates
from cre_mcp.leases.models import CitedClaim, LeaseAbstract
from cre_mcp.leases.reader import read_lease
from cre_mcp.leases.schedule import rent_schedule


def _walk_claims(value: Any, path: str = "") -> list[tuple[str, CitedClaim]]:
    found: list[tuple[str, CitedClaim]] = []
    if isinstance(value, CitedClaim):
        found.append((path, value))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_walk_claims(item, f"{path}[{index}]"))
    elif is_dataclass(value):
        for item in fields(value):
            if item.name in {
                "source_path", "deal_id", "sanitization_redactions", "amendment_count"
            }:
                continue
            child = f"{path}.{item.name}" if path else item.name
            found.extend(_walk_claims(getattr(value, item.name), child))
    return found


def _empty_lists(value: Any, path: str = "") -> list[str]:
    empty: list[str] = []
    if isinstance(value, list):
        if not value:
            empty.append(path)
        else:
            for index, item in enumerate(value):
                empty.extend(_empty_lists(item, f"{path}[{index}]"))
    elif is_dataclass(value) and not isinstance(value, CitedClaim):
        for item in fields(value):
            if item.name in {
                "source_path", "deal_id", "sanitization_redactions", "amendment_count"
            }:
                continue
            child = f"{path}.{item.name}" if path else item.name
            empty.extend(_empty_lists(getattr(value, item.name), child))
    return empty


def _honesty(abstract: LeaseAbstract, *, calculation_gaps: list[str] | None = None) -> dict[str, Any]:
    claims = _walk_claims(abstract)
    stated = [(path, claim) for path, claim in claims if claim.status == "stated"]
    inferred = [(path, claim) for path, claim in claims if claim.status == "inferred"]
    missing = [(path, claim) for path, claim in claims if claim.status == "missing"]
    empty_lists = _empty_lists(abstract)
    positive = stated + inferred
    confidences = [claim.confidence for _, claim in positive]
    return {
        "posture": "deterministic extraction; document silence remains missing",
        "found_fields": [path for path, _ in positive],
        "missing_fields": [path for path, _ in missing] + empty_lists,
        "stated_count": len(stated),
        "inferred_count": len(inferred),
        "missing_count": len(missing) + len(empty_lists),
        "confidence_summary": {
            "average": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
            "minimum": round(min(confidences), 3) if confidences else 0.0,
            "maximum": round(max(confidences), 3) if confidences else 0.0,
        },
        "sanitization_redactions": abstract.sanitization_redactions,
        "calculation_gaps": sorted(set(calculation_gaps or [])),
        "limitations": [
            "No legal conclusion is made from extracted lease language.",
            "Conditional dates remain unresolved until their triggering facts are supplied.",
            "CPI and percentage-rent totals require caller-provided indices and sales.",
        ],
    }


def _load(path: str | Path, *, deal_id: str | None = None) -> LeaseAbstract:
    document = read_lease(path)
    abstract = abstract_lease(document.text)
    abstract.source_path = document.source_path
    abstract.deal_id = deal_id
    abstract.sanitization_redactions = document.redactions
    return abstract


def abstract_lease_document(path: str | Path, deal_id: str | None = None) -> dict[str, Any]:
    """Read and abstract one lease document into a JSON-friendly dictionary."""
    abstract = _load(path, deal_id=deal_id)
    payload = asdict(abstract)
    payload["honesty"] = _honesty(abstract)
    return payload


def lease_critical_dates(
    document: LeaseAbstract | str | Path,
    as_of: date | datetime | str,
    *,
    deal_id: str | None = None,
) -> dict[str, Any]:
    """Return the horizon calendar for an abstract or a lease path."""
    abstract = document if isinstance(document, LeaseAbstract) else _load(document, deal_id=deal_id)
    payload = critical_dates(abstract, as_of)
    payload["honesty"] = _honesty(
        abstract,
        calculation_gaps=[item["reason"] for item in payload["unresolved"]],
    )
    return payload


def calc_rent_schedule(
    document: LeaseAbstract | str | Path,
    start: date | datetime | str,
    end: date | datetime | str,
    sales: float | Mapping[object, float] | None = None,
    cpi_values: Mapping[object, float] | None = None,
    proration_convention: str = "actual_days",
    *,
    deal_id: str | None = None,
) -> dict[str, Any]:
    """Return monthly contractual rent plus missing-input disclosure."""
    abstract = document if isinstance(document, LeaseAbstract) else _load(document, deal_id=deal_id)
    rows = rent_schedule(
        abstract,
        start,
        end,
        sales=sales,
        cpi_values=cpi_values,
        proration_convention=proration_convention,
    )
    gaps = [str(gap) for row in rows for gap in row["missing_inputs"]]
    if any(row["status"] == "uncovered" for row in rows):
        gaps.append("rent_period_coverage")
    return {
        "deal_id": abstract.deal_id,
        "start": str(start),
        "end": str(end),
        "schedule": rows,
        "honesty": _honesty(abstract, calculation_gaps=gaps),
    }


__all__ = ["abstract_lease_document", "lease_critical_dates", "calc_rent_schedule"]
