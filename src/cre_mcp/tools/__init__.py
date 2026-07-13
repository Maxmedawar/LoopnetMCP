"""MCP tool registration."""

from typing import Any


def register_all(mcp: Any) -> None:
    """Register every tool module on the provided FastMCP application."""
    from cre_mcp.tools import listing_tools

    mcp.tool()(listing_tools.search_properties)
    mcp.tool()(listing_tools.get_property_details)
    mcp.tool()(listing_tools.get_market_overview)


__all__ = ["register_all"]
