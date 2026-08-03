"""Plain leasing tool boundaries for later registration by the MCP director."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from os import PathLike
from typing import Any, Callable

from .capacity import tenant_sales_capacity as _tenant_sales_capacity
from .opening import opening_critical_path as _opening_critical_path
from .proposals import compare_lease_proposals as _compare_lease_proposals
from .prospects import tenant_prospect_list as _tenant_prospect_list
from .watch import record_tenant_signal as _record_tenant_signal
from .watch import tenant_watch_report as _tenant_watch_report


def _boundary(function: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        return {"error": str(exc)}


def tenant_sales_capacity(
    category: str,
    trade_area: Mapping[str, Any],
    unit: Mapping[str, Any],
) -> dict[str, Any]:
    """Return capacity conventions or an error object; this is not registered."""

    return _boundary(_tenant_sales_capacity, category, trade_area, unit)


def compare_lease_proposals(
    proposals: Sequence[Mapping[str, Any]],
    space: Mapping[str, Any],
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Compare proposal objectives or return an error object; this is not registered."""

    if discount_rate is None:
        return _boundary(_compare_lease_proposals, proposals, space)
    return _boundary(_compare_lease_proposals, proposals, space, discount_rate)


def opening_critical_path(
    lease_milestones: Mapping[str, Any],
    jurisdiction_note: str | None = None,
) -> dict[str, Any]:
    """Return the opening schedule or an error object; this is not registered."""

    return _boundary(_opening_critical_path, lease_milestones, jurisdiction_note)


def record_tenant_signal(
    tenant_name: str,
    category: str,
    signal_type: str,
    severity: str,
    note: str,
    recorded_at: Any = None,
    *,
    db_path: str | PathLike[str] | None = None,
) -> dict[str, Any]:
    """Persist a leasing-watch input or return an error object; this is not registered."""

    return _boundary(
        _record_tenant_signal,
        tenant_name,
        category,
        signal_type,
        severity,
        note,
        recorded_at,
        db_path=db_path,
    )


def tenant_watch_report(
    tenant: str,
    *,
    db_path: str | PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return signal history and framing or an error object; this is not registered."""

    return _boundary(_tenant_watch_report, tenant, db_path=db_path)


def tenant_prospect_list(
    site: Mapping[str, Any],
    existing_cotenancy: Sequence[str | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return catalog prospects or an error object; this is not registered."""

    return _boundary(_tenant_prospect_list, site, existing_cotenancy)


__all__ = [
    "compare_lease_proposals",
    "opening_critical_path",
    "record_tenant_signal",
    "tenant_prospect_list",
    "tenant_sales_capacity",
    "tenant_watch_report",
]
