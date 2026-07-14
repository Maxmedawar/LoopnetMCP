"""MCP tool registration."""

from typing import Any


def register_all(mcp: Any) -> None:
    """Register every tool module on the provided FastMCP application."""
    from cre_mcp.tools import (
        arbitrage_tools,
        capital_tools,
        control_tools,
        deal_tools,
        decision_tools,
        eval_tools,
        execution_tools,
        listing_tools,
        market_tools,
        memory_tools,
        motivation_tools,
        nearby_tools,
        ops_tools,
        owner_tools,
        pipeline_tools,
        structure_tools,
        truth_tools,
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
    mcp.tool()(structure_tools.recommend_structure)
    mcp.tool()(structure_tools.start_exchange)
    mcp.tool()(structure_tools.exchange_status)
    mcp.tool()(structure_tools.identify_replacement)
    mcp.tool()(structure_tools.calc_boot_basis)
    mcp.tool()(capital_tools.add_investor)
    mcp.tool()(capital_tools.list_investors)
    mcp.tool()(capital_tools.record_commitment)
    mcp.tool()(capital_tools.check_solicitation)
    mcp.tool()(capital_tools.model_waterfall)
    mcp.tool()(capital_tools.draft_ppm)
    mcp.tool()(capital_tools.draft_form_d)
    mcp.tool()(ops_tools.after_tax_returns)
    mcp.tool()(ops_tools.operating_playbook)
    mcp.tool()(eval_tools.backtest_score)
    mcp.tool()(eval_tools.record_deal_outcome)
    mcp.tool()(truth_tools.ingest_document)
    mcp.tool()(truth_tools.list_deal_documents)
    mcp.tool()(truth_tools.reconcile_deal_docs)
    mcp.tool()(truth_tools.build_noi_bridge)
    mcp.tool()(truth_tools.deal_truth_report)
    mcp.tool()(nearby_tools.nearby_brands)
    mcp.tool()(nearby_tools.trade_area_anchors)
    mcp.tool()(control_tools.find_control_opportunities)
    mcp.tool()(control_tools.match_tenants_to_site)
    mcp.tool()(control_tools.evaluate_tenant_site_fit)
    mcp.tool()(control_tools.model_lease_creation_spread)
    mcp.tool()(control_tools.recommend_control_structure)
    mcp.tool()(control_tools.build_tenant_pitch)
    mcp.tool()(motivation_tools.owner_motivation)
    mcp.tool()(motivation_tools.record_trigger_event)
    mcp.tool()(motivation_tools.find_motivated_owners)
    mcp.tool()(memory_tools.record_ic_decision)
    mcp.tool()(memory_tools.log_deal_event)
    mcp.tool()(memory_tools.deal_timeline)
    mcp.tool()(memory_tools.ic_scorecard)
    mcp.tool()(decision_tools.set_buyer_profile)
    mcp.tool()(decision_tools.decision_frontier)
    mcp.tool()(arbitrage_tools.analyze_master_lease)
    mcp.tool()(arbitrage_tools.find_arbitrage_opportunities)
    mcp.tool()(arbitrage_tools.draft_master_lease_proposal)
    mcp.tool()(arbitrage_tools.draft_subtenant_outreach)
    mcp.tool()(arbitrage_tools.master_lease_playbook)


__all__ = ["register_all"]
