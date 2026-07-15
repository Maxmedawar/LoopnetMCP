"""Sale-process framing, access governance, and counsel-review contracts."""

import ast
import inspect

from cre_mcp.disposition.process import design_sale_process
from cre_mcp.disposition import tools


def test_sale_process_exposes_tradeoffs_rounds_gates_and_counsel_flag():
    result = design_sale_process(
        {
            "deal_id": "deal-process",
            "price": 12_000_000,
            "type": "industrial",
            "market": "Dallas",
            "known_buyer_count": 8,
            "confidentiality_sensitive": True,
        },
        {
            "confidentiality": "critical",
            "speed": "high",
            "certainty": "high",
            "target_close_date": "2027-03-31",
        },
    )

    options = {item["process"]: item for item in result["process_options"]}
    assert set(options) == {"brokered", "targeted", "auction"}
    for item in options.values():
        assert item["tradeoffs"]["advantages"]
        assert item["tradeoffs"]["costs_risks"]

    rules = result["bid_round_rules"]
    assert [item["round"] for item in rules["rounds"]] == [1, 2, 3]
    assert rules["rounds"][-1]["name"] == "Best and final"
    assert rules["best_and_final_rules"]
    assert rules["process_letter"]["professional_review_required"] is True
    assert "counsel" in rules["process_letter"]["professional_review_flag"].casefold()

    assert [tier["tier"] for tier in result["confidentiality_tiers"]] == [0, 1, 2, 3]
    assert all("access_gate" in tier for tier in result["confidentiality_tiers"])
    assert result["timeline"]["target_close_date"] == "2027-03-31"
    assert all("dependencies" in stage for stage in result["timeline"]["stages"])
    assert result["professional_review_required"] is True


def test_tools_surface_is_plain_callable_python_without_fastmcp_registration():
    names = {
        "disposition_readiness",
        "record_buyer",
        "match_buyers",
        "record_bid",
        "normalize_bids",
        "design_sale_process",
        "compare_exit_paths",
    }
    assert names == set(tools.__all__)
    assert all(callable(getattr(tools, name)) for name in names)

    tree = ast.parse(inspect.getsource(tools))
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any("fastmcp" in module.casefold() for module in imported_modules)
    assert not hasattr(tools, "mcp")
