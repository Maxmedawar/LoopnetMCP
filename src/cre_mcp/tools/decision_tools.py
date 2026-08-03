"""Async MCP-facing wrappers for buyer-specific decision analysis."""

from typing import Any

from cre_mcp.decision.frontier import decision_frontier as _build_decision_frontier
from cre_mcp.decision.profile import normalize_buyer


async def set_buyer_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a buyer profile without persisting it.

    Args:
        profile: Buyer attributes (cash_available, reserves_required, net_worth,
            guaranty_capacity, return_requirement_irr, hold_pref_years,
            recourse_tolerance, operating_capability, ...). Missing fields are
            treated as unknown, never as failures.

    Returns:
        The normalized buyer profile for use with decision_frontier.
    """
    try:
        normalized = normalize_buyer(profile or {})
        return {"buyer_profile": normalized.model_dump()}
    except Exception as exc:
        return {"error": str(exc)}


async def decision_frontier(
    deal: dict[str, Any],
    buyer: dict[str, Any],
    structures: list[str] | None = None,
) -> dict[str, Any]:
    """Return the buyer-specific decision frontier for a deal."""

    try:
        return _build_decision_frontier(deal, buyer, structures)
    except Exception as exc:
        return {"error": str(exc)}


__all__ = ["decision_frontier", "set_buyer_profile"]
