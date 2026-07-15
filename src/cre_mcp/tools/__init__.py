"""MCP tool registration."""

from typing import Any


def register_all(mcp: Any) -> None:
    """Register every tool module on the provided FastMCP application."""
    from cre_mcp.tools import (
        about_tools,
        arbitrage_tools,
        capital_tools,
        control_tools,
        deal_tools,
        decision_tools,
        eval_tools,
        execution_tools,
        ledger_tools,
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
    from cre_mcp.books import tools as book_tools
    from cre_mcp.command import tools as command_tools
    from cre_mcp.dataroom import tools as dataroom_tools
    from cre_mcp.debt import tools as debt_tools
    from cre_mcp.disposition import tools as disposition_tools
    from cre_mcp.envscreen import tools as envscreen_tools
    from cre_mcp.fund import tools as fund_tools
    from cre_mcp.leasing import tools as leasing_tools
    from cre_mcp.negotiation import tools as negotiation_tools
    from cre_mcp.obligations import tools as obligation_tools
    from cre_mcp.physical import tools as physical_tools
    from cre_mcp.verifyreg import tools as verifyreg_tools
    from cre_mcp.zoning import tools as zoning_tools
    from cre_mcp.leases import tools as lease_tools
    from cre_mcp.notes import tools as note_tools
    from cre_mcp.scenarios import tools as scenario_tools
    from cre_mcp.taxecon import tools as taxecon_tools

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
    mcp.tool()(pipeline_tools.assign_deal)
    mcp.tool()(pipeline_tools.unassigned_deals)
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
    mcp.tool()(about_tools.capabilities)
    mcp.tool()(about_tools.deal_assumptions)
    mcp.tool()(arbitrage_tools.analyze_master_lease)
    mcp.tool()(arbitrage_tools.find_arbitrage_opportunities)
    mcp.tool()(arbitrage_tools.draft_master_lease_proposal)
    mcp.tool()(arbitrage_tools.draft_subtenant_outreach)
    mcp.tool()(arbitrage_tools.master_lease_playbook)
    mcp.tool()(ledger_tools.record_lender_quote)
    mcp.tool()(ledger_tools.resolve_lender_quote)
    mcp.tool()(ledger_tools.record_defect_outcome)
    mcp.tool()(ledger_tools.counterparty_track_record)
    mcp.tool()(ledger_tools.lender_track_record)
    mcp.tool()(ledger_tools.defect_track_record)
    mcp.tool()(scenario_tools.stress_test_deal)
    mcp.tool()(scenario_tools.sensitivity_drivers)
    mcp.tool()(scenario_tools.breakeven_analysis)
    mcp.tool()(scenario_tools.model_lease_up)
    mcp.tool()(lease_tools.abstract_lease_document)
    mcp.tool()(lease_tools.lease_critical_dates)
    mcp.tool()(lease_tools.calc_rent_schedule)
    mcp.tool()(lease_tools.analyze_lease_recoveries)
    mcp.tool()(lease_tools.price_lease_option)
    mcp.tool()(taxecon_tools.estimate_tax_reassessment)
    mcp.tool()(taxecon_tools.audit_assessor_record)
    mcp.tool()(taxecon_tools.net_sale_proceeds)
    mcp.tool()(command_tools.morning_queue)
    mcp.tool()(command_tools.overnight_changes)
    mcp.tool()(command_tools.flag_unattended)
    mcp.tool()(command_tools.record_listing_snapshot)
    mcp.tool()(command_tools.stale_listing_signals)
    mcp.tool()(note_tools.estimate_foreclosure_timeline)
    mcp.tool()(note_tools.model_lien_waterfall)
    mcp.tool()(note_tools.price_note)
    mcp.tool()(note_tools.compare_note_workouts)
    mcp.tool()(debt_tools.compare_term_sheets)
    mcp.tool()(debt_tools.covenant_forecast)
    mcp.tool()(debt_tools.value_assumable_debt)
    mcp.tool()(debt_tools.compare_capital_paths)
    mcp.tool()(obligation_tools.extract_lease_restrictions)
    mcp.tool()(obligation_tools.detect_obligation_collisions)
    mcp.tool()(obligation_tools.screen_transfer_consents)
    mcp.tool()(obligation_tools.compare_estoppel_to_lease)
    mcp.tool()(dataroom_tools.init_data_room)
    mcp.tool()(dataroom_tools.data_room_index)
    mcp.tool()(dataroom_tools.update_data_room_item)
    mcp.tool()(dataroom_tools.init_transaction_plan)
    mcp.tool()(dataroom_tools.transaction_critical_path)
    mcp.tool()(dataroom_tools.closing_runway)
    mcp.tool()(zoning_tools.lookup_zoning)
    mcp.tool()(zoning_tools.nearby_permits)
    mcp.tool()(zoning_tools.zoning_code_link)
    mcp.tool()(envscreen_tools.environmental_screen)
    mcp.tool()(envscreen_tools.flood_zone)
    mcp.tool()(envscreen_tools.hazard_profile)
    mcp.tool()(verifyreg_tools.verify_license)
    mcp.tool()(verifyreg_tools.counterparty_screen)
    mcp.tool()(book_tools.setup_tenancy)
    mcp.tool()(book_tools.post_charges)
    mcp.tool()(book_tools.import_bank_transactions)
    mcp.tool()(book_tools.reconcile_rent_to_cash)
    mcp.tool()(book_tools.ar_aging)
    mcp.tool()(book_tools.audit_lease_billing)
    mcp.tool()(negotiation_tools.build_negotiation_plan)
    mcp.tool()(negotiation_tools.value_concession)
    mcp.tool()(negotiation_tools.detect_term_drift)
    mcp.tool()(negotiation_tools.record_negotiation_commitment)
    mcp.tool()(negotiation_tools.list_negotiation_commitments)
    mcp.tool()(negotiation_tools.record_term_approval)
    mcp.tool()(negotiation_tools.negotiation_approval_log)
    mcp.tool()(physical_tools.estimate_capex_from_findings)
    mcp.tool()(physical_tools.remaining_useful_life)
    mcp.tool()(physical_tools.vintage_risk_screen)
    mcp.tool()(physical_tools.ada_code_exposure)
    mcp.tool()(physical_tools.physical_risk_register)
    mcp.tool()(leasing_tools.tenant_sales_capacity)
    mcp.tool()(leasing_tools.compare_lease_proposals)
    mcp.tool()(leasing_tools.opening_critical_path)
    mcp.tool()(leasing_tools.record_tenant_signal)
    mcp.tool()(leasing_tools.tenant_watch_report)
    mcp.tool()(leasing_tools.tenant_prospect_list)
    mcp.tool()(fund_tools.compare_jv_structures)
    mcp.tool()(fund_tools.forecast_capital_calls)
    mcp.tool()(fund_tools.record_fund_mark)
    mcp.tool()(fund_tools.record_fund_flow)
    mcp.tool()(fund_tools.nav_report)
    mcp.tool()(fund_tools.check_mandate_limits)
    mcp.tool()(fund_tools.quarterly_investor_report)
    mcp.tool()(fund_tools.record_investor_touch)
    mcp.tool()(fund_tools.investor_engagement_report)
    mcp.tool()(disposition_tools.disposition_readiness)
    mcp.tool()(disposition_tools.record_buyer)
    mcp.tool()(disposition_tools.match_buyers)
    mcp.tool()(disposition_tools.record_bid)
    mcp.tool()(disposition_tools.normalize_bids)
    mcp.tool()(disposition_tools.design_sale_process)
    mcp.tool()(disposition_tools.compare_exit_paths)


__all__ = ["register_all"]
