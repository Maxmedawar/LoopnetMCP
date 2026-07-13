"""CRE deal-intelligence MCP server."""

import logging
import sys

from fastmcp import FastMCP

from cre_mcp.tools import register_all
from cre_mcp.tools.deal_tools import analyze_deal, find_deals, find_distressed
from cre_mcp.tools.listing_tools import (
    get_market_overview,
    get_property_details,
    search_properties,
)
from cre_mcp.tools.market_tools import compare_markets, market_intel
from cre_mcp.tools.owner_tools import owner_lookup

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
        " Use analyze_deal for deep underwriting, find_deals for scored deal discovery,"
        " and find_distressed for REO, auction, foreclosure, and tax-sale opportunities."
        " Use owner_lookup for public assessor parcel and owner enrichment."
    ),
)
register_all(mcp)


if __name__ == "__main__":
    mcp.run(transport="stdio")


__all__ = [
    "analyze_deal",
    "compare_markets",
    "find_deals",
    "find_distressed",
    "get_market_overview",
    "get_property_details",
    "market_intel",
    "mcp",
    "owner_lookup",
    "search_properties",
]
