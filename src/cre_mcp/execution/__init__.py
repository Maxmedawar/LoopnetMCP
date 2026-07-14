"""Coach-and-guardrail execution layer."""

from cre_mcp.execution.contacts import find_contact
from cre_mcp.execution.loi import generate_loi
from cre_mcp.execution.negotiate import handle_counter
from cre_mcp.execution.offer import recommend_offer
from cre_mcp.execution.outreach import draft_outreach

__all__ = [
    "draft_outreach",
    "find_contact",
    "generate_loi",
    "handle_counter",
    "recommend_offer",
]
