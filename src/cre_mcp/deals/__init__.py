"""Persistent deal workspace used by execution-layer workflows."""

from cre_mcp.deals.store import DealStore, get_deal_store

__all__ = ["DealStore", "get_deal_store"]
