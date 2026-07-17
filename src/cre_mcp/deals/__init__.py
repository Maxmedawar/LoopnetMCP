"""Persistent deal workspace used by execution-layer workflows."""

from cre_mcp.deals.store import PIPELINE_STAGES, DealStore, get_deal_store

__all__ = ["PIPELINE_STAGES", "DealStore", "get_deal_store"]
