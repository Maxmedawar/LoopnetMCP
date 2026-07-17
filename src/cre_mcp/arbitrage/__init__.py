"""Master-lease arbitrage analysis and outreach helpers."""

from cre_mcp.arbitrage.economics import master_lease_arbitrage
from cre_mcp.arbitrage.finder import find_arbitrage_opportunities
from cre_mcp.arbitrage.proposals import (
    draft_master_lease_proposal,
    draft_subtenant_outreach,
)

__all__ = [
    "draft_master_lease_proposal",
    "draft_subtenant_outreach",
    "find_arbitrage_opportunities",
    "master_lease_arbitrage",
]
