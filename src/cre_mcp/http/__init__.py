"""Shared HTTP fetching infrastructure."""

from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.http.policies import FetchPolicy, POLICY_REGISTRY

__all__ = ["FetchClient", "FetchPolicy", "POLICY_REGISTRY", "get_fetch_client"]
