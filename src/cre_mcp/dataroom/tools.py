"""Plain data-room functions for later FastMCP registration by the integrator."""

from __future__ import annotations

from typing import Any

from .dependencies import DependencyStore
from .index import DataRoomStore


def init_data_room(deal_id: str, deal_type: str) -> dict[str, Any]:
    """Initialize the declared deal-type document taxonomy."""

    return DataRoomStore().init_data_room(deal_id, deal_type)


def data_room_index(deal_id: str) -> dict[str, Any]:
    """Return the transparent, phase-gated completeness index."""

    return DataRoomStore().completeness_index(deal_id)


def update_data_room_item(
    deal_id: str,
    doc_key: str,
    status: str | None = None,
    assignee: str | None = None,
    due_date: Any = None,
) -> dict[str, Any]:
    """Update supplied workflow fields on one initialized taxonomy row."""

    updates: dict[str, Any] = {}
    if status is not None:
        updates["status"] = status
    if assignee is not None:
        updates["assignee"] = assignee
    if due_date is not None:
        updates["due_date"] = due_date
    store = DataRoomStore()
    try:
        return store.update_item(deal_id, doc_key, **updates)
    except KeyError:
        # MCP boundary: an unknown key must come back as a usable error,
        # not a raw exception — and it should teach the caller the valid keys.
        index = store.completeness_index(deal_id)
        known = [item.get("doc_key") for item in index.get("items", [])]
        return {
            "error": f"unknown data-room item {doc_key!r} for deal {deal_id!r}",
            "valid_doc_keys": known,
        }


def init_transaction_plan(
    deal_id: str,
    deal_type: str,
    closing_date: Any,
) -> dict[str, Any]:
    """Initialize a dated, convention-labeled transaction dependency plan."""

    return DependencyStore().init_transaction_plan(deal_id, deal_type, closing_date)


def transaction_critical_path(deal_id: str) -> dict[str, Any]:
    """Return graph order, due-task blockers, deadline slack, and SPOFs."""

    return DependencyStore().critical_path(deal_id)


def closing_runway(deal_id: str) -> dict[str, Any]:
    """Return the final-seven-days graph slice and blocking prerequisites."""

    return DependencyStore().closing_runway(deal_id)


__all__ = [
    "closing_runway",
    "data_room_index",
    "init_data_room",
    "init_transaction_plan",
    "transaction_critical_path",
    "update_data_room_item",
]
