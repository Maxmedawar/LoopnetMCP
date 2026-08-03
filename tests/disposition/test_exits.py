"""Exit-path comparison contracts: ranges, delegation, and counsel gates."""

from cre_mcp.disposition.exits import compare_exit_paths


def _path(result, name):
    return next(item for item in result["paths"] if item["path"] == name)


def _mandatory_disciplines(path):
    return {
        flag["discipline"]
        for flag in path["professional_flags"]
        if flag["mandatory"] is True
    }


def test_exit_paths_are_ranges_and_sale_math_delegates_to_taxecon():
    result = compare_exit_paths(
        {
            "price": 10_000_000,
            "loan_balance": 4_000_000,
            "prepay": {"type": "none"},
            "commission_pct": 0.05,
            "state": "CA",
            "other_costs": {"low": 75_000, "base": 125_000, "high": 200_000},
        },
        {"priority": "liquidity", "tax_basis": 3_000_000},
    )

    expected = {
        "direct_sale",
        "brokered_sale",
        "recap",
        "partial_sale",
        "1031_exchange",
        "upreit",
        "dst",
    }
    assert expected <= {item["path"] for item in result["paths"]}
    assert result["range_convention"]
    assert result["professional_review_required"] is True

    for item in result["paths"]:
        assert {"low", "high"} <= set(item["net_to_seller_range"])
        assert {"low", "high"} <= set(item["timing_months_range"])
        assert item["control_retained_range"]["unit"] == "percent"
        assert {"low", "high"} <= set(item["control_retained_range"])
        assert item["tax_character_notes"]
        assert item["liquidity"]

    for sale_path in ("direct_sale", "brokered_sale", "1031_exchange"):
        hook = _path(result, sale_path)["net_sale_proceeds_hook"]
        assert hook["module"] == "cre_mcp.taxecon"
        assert hook["function"] == "net_sale_proceeds"
        assert hook.get("result") or hook.get("envelope")


def test_dst_and_upreit_always_require_securities_and_tax_counsel():
    result = compare_exit_paths(
        {
            "price": 5_000_000,
            "loan_balance": 0,
            "prepay": {"type": "none"},
            "commission_pct": 0.04,
            "state": "TX",
        },
        {},
    )

    for name in ("dst", "upreit"):
        disciplines = _mandatory_disciplines(_path(result, name))
        assert {"securities_counsel", "tax_counsel"} <= disciplines
