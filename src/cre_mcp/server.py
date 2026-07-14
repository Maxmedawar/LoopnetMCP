"""CRE deal-intelligence MCP server."""

import logging
import sys

from fastmcp import FastMCP

from cre_mcp.tools import register_all
from cre_mcp.tools.deal_tools import analyze_deal, find_deals, find_distressed
from cre_mcp.tools.execution_tools import (
    draft_outreach,
    find_contact,
    financing_options,
    generate_loi,
    handle_counter,
    qualify_me,
    recommend_offer,
    size_debt,
)
from cre_mcp.tools.listing_tools import (
    get_market_overview,
    get_property_details,
    search_properties,
)
from cre_mcp.tools.market_tools import (
    compare_markets,
    get_comps,
    get_rent_comparables,
    market_intel,
)
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
        " Use get_rent_comparables for public ZORI, ACS, and HUD rent benchmarks."
        " Use get_comps for county-limited sale comps and labeled value estimates."
        " Use recommend_offer for an explained negotiation range and generate_loi"
        " for a non-binding attorney-review draft."
        " Use find_contact for source-labeled broker, owner, and public registry contacts,"
        " draft_outreach for deterministic first-touch coaching, and handle_counter"
        " for guarded counteroffer parsing and response coaching."
        " Use financing_options to screen lender types, qualify_me to test buyer cash and"
        " sponsor gates, and size_debt for FRED-anchored LTV/DSCR proceeds."
    ),
)
register_all(mcp)


if __name__ == "__main__":
    mcp.run(transport="stdio")


__all__ = [
    "analyze_deal",
    "compare_markets",
    "find_deals",
    "find_contact",
    "financing_options",
    "find_distressed",
    "get_market_overview",
    "get_comps",
    "get_property_details",
    "get_rent_comparables",
    "generate_loi",
    "draft_outreach",
    "handle_counter",
    "market_intel",
    "mcp",
    "owner_lookup",
    "qualify_me",
    "recommend_offer",
    "search_properties",
    "size_debt",
]
