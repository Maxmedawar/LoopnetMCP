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

# Route ALL logging to stderr — stdout is reserved for MCP protocol messages.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

mcp = FastMCP(
    name="loopnet",
    instructions=(
        "Loopnet MCP server for searching commercial real estate listings. "
        "Use search_properties to find listings by location and filters. "
        "Use get_property_details to get full details on a specific listing. "
        "Use get_market_overview for aggregate market statistics."
    ),
)
register_all(mcp)


if __name__ == "__main__":
    mcp.run(transport="stdio")


__all__ = [
    "get_market_overview",
    "get_property_details",
    "mcp",
    "search_properties",
]
