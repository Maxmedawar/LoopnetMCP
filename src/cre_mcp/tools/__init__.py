"""MCP tool registration."""

from typing import Any


def register_all(mcp: Any) -> None:
    """Register every tool module on the provided FastMCP application."""
    from cre_mcp.tools import deal_tools, listing_tools, market_tools, owner_tools

    mcp.tool()(listing_tools.search_properties)
    mcp.tool()(listing_tools.get_property_details)
    mcp.tool()(listing_tools.get_market_overview)
    mcp.tool()(market_tools.market_intel)
    mcp.tool()(market_tools.compare_markets)
    mcp.tool()(deal_tools.analyze_deal)
    mcp.tool()(deal_tools.find_deals)
    mcp.tool()(deal_tools.find_distressed)
    mcp.tool()(owner_tools.owner_lookup)


__all__ = ["register_all"]
