"""CRE deal-intelligence MCP server."""

import logging
import sys

from fastmcp import FastMCP

from cre_mcp.tools import register_all
from cre_mcp.tools.listing_tools import (
    get_market_overview,
    get_property_details,
    search_properties,
)
from cre_mcp.tools.market_tools import compare_markets, market_intel

# Route ALL logging to stderr — stdout is reserved for MCP protocol messages.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

mcp = FastMCP(
    name="loopnet",
    instructions=(
        "CRE deal-intelligence server for commercial real estate listings and markets. "
        "Use search_properties to find listings by location and filters. "
        "Use get_property_details to get full details on a specific listing. "
        "Use get_market_overview for listing-derived market statistics. "
        "Use market_intel for government fundamentals and compare_markets to rank locations."
    ),
)
register_all(mcp)


if __name__ == "__main__":
    mcp.run(transport="stdio")


__all__ = [
    "get_market_overview",
    "get_property_details",
    "compare_markets",
    "market_intel",
    "mcp",
    "search_properties",
]
