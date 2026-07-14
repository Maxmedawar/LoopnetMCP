"""MCP tool registration."""

from typing import Any


def register_all(mcp: Any) -> None:
    """Register every tool module on the provided FastMCP application."""
    from cre_mcp.tools import (
        deal_tools,
        execution_tools,
        listing_tools,
        market_tools,
        owner_tools,
        pipeline_tools,
    )

    mcp.tool()(listing_tools.search_properties)
    mcp.tool()(listing_tools.get_property_details)
    mcp.tool()(listing_tools.get_market_overview)
    mcp.tool()(market_tools.market_intel)
    mcp.tool()(market_tools.compare_markets)
    mcp.tool()(market_tools.get_rent_comparables)
    mcp.tool()(market_tools.get_comps)
    mcp.tool()(deal_tools.analyze_deal)
    mcp.tool()(deal_tools.find_deals)
    mcp.tool()(deal_tools.find_distressed)
    mcp.tool()(owner_tools.owner_lookup)
    mcp.tool()(execution_tools.recommend_offer)
    mcp.tool()(execution_tools.generate_loi)
    mcp.tool()(execution_tools.find_contact)
    mcp.tool()(execution_tools.draft_outreach)
    mcp.tool()(execution_tools.handle_counter)
    mcp.tool()(execution_tools.financing_options)
    mcp.tool()(execution_tools.qualify_me)
    mcp.tool()(execution_tools.size_debt)
    mcp.tool()(execution_tools.due_diligence_plan)
    mcp.tool()(execution_tools.closing_plan)
    mcp.tool()(execution_tools.save_deal)
    mcp.tool()(execution_tools.list_deals)
    mcp.tool()(pipeline_tools.add_to_pipeline)
    mcp.tool()(pipeline_tools.update_deal_stage)
    mcp.tool()(pipeline_tools.list_pipeline)
    mcp.tool()(pipeline_tools.save_search)
    mcp.tool()(pipeline_tools.list_searches)
    mcp.tool()(pipeline_tools.check_alerts)


__all__ = ["register_all"]
