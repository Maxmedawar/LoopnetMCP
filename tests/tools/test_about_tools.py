"""Phase 31 honesty-layer tests."""

import pytest

from cre_mcp.tools.about_tools import capabilities, deal_assumptions


@pytest.mark.asyncio
async def test_capabilities_is_honest():
    result = await capabilities()
    assert "can" in result["capabilities"] and "cannot" in result["capabilities"]
    # It must NOT promise replacing the reps, and MUST refuse to wire funds.
    assert "veteran" in result["capabilities"]["not_a_promise"].lower()
    assert "NEVER" in result["authority_matrix"]["commit_funds_or_wire"]
    assert any("liquidity" in c.lower() for c in result["capabilities"]["cannot"])
    assert "UNCALIBRATED" in result["disclaimer"]


@pytest.mark.asyncio
async def test_assumptions_sheet_marks_unknowns():
    result = await deal_assumptions({"purchase_price": 2_000_000, "noi": 120_000, "noi_basis": "verified"})
    rows = {r["driver"]: r for r in result["assumptions"]}
    assert rows["purchase_price"]["value"] == 2_000_000
    assert rows["purchase_price"]["source"] == "provided"
    # A driver not supplied is surfaced as unknown, never silently defaulted.
    assert rows["exit_cap"]["value"] is None
    assert rows["exit_cap"]["source"] == "unknown"
