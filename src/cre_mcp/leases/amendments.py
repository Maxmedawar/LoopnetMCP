"""Apply lease amendments without losing field-level provenance.

Only positively cited amendment claims override the base abstraction.  Silence
in an amendment never erases a base field, and every replacement claim is
retagged ``amendment_N`` so the effective result remains auditable.
"""

from __future__ import annotations

import copy
from dataclasses import fields, is_dataclass
from typing import Any

from cre_mcp.leases.abstract import abstract_lease
from cre_mcp.leases.models import CitedClaim, LeaseAbstract, LeaseOption


def _retag(value: Any, source: str) -> Any:
    if isinstance(value, CitedClaim):
        value.source = source
        return value
    if isinstance(value, list):
        for item in value:
            _retag(item, source)
        return value
    if is_dataclass(value):
        for item in fields(value):
            _retag(getattr(value, item.name), source)
    return value


def _merge_dataclass(base: Any, amendment: Any) -> None:
    for item in fields(base):
        name = item.name
        if name in {
            "source_path", "deal_id", "sanitization_redactions", "amendment_count"
        }:
            continue
        current = getattr(base, name)
        replacement = getattr(amendment, name)
        if isinstance(current, CitedClaim):
            if replacement.status != "missing":
                setattr(base, name, copy.deepcopy(replacement))
        elif is_dataclass(current):
            _merge_dataclass(current, replacement)
        elif isinstance(current, list) and replacement:
            if name == "rent_schedule":
                # A stated amendment rent table supersedes the effective table;
                # mixing old and new rows would fabricate an overlap rule.
                setattr(base, name, copy.deepcopy(replacement))
            elif name == "options":
                _merge_options(current, replacement)
            else:
                # Requirements/cures are cumulative unless an amendment says
                # otherwise; deterministic extraction cannot infer deletion.
                current.extend(copy.deepcopy(replacement))


def _merge_options(base: list[LeaseOption], amendments: list[LeaseOption]) -> None:
    for option in amendments:
        kind = option.option_type.value
        index = next(
            (
                i for i, existing in enumerate(base)
                if existing.option_type.status != "missing"
                and existing.option_type.value == kind
            ),
            None,
        )
        if index is None:
            base.append(copy.deepcopy(option))
        else:
            merged = copy.deepcopy(base[index])
            _merge_dataclass(merged, option)
            base[index] = merged


def apply_amendments(base: LeaseAbstract, amendments: list[str]) -> LeaseAbstract:
    """Return a copied effective abstract after applying amendments in order."""
    effective = copy.deepcopy(base)
    _retag(effective, "base")
    redactions = effective.sanitization_redactions
    for number, text in enumerate(amendments, start=1):
        amendment = abstract_lease(text)
        source = f"amendment_{number}"
        _retag(amendment, source)
        _merge_dataclass(effective, amendment)
        redactions += amendment.sanitization_redactions
    effective.amendment_count = len(amendments)
    effective.sanitization_redactions = redactions
    return effective


__all__ = ["apply_amendments"]
