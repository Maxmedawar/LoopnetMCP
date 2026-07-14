"""Coach-and-guardrail execution layer."""

from cre_mcp.execution.loi import generate_loi
from cre_mcp.execution.offer import recommend_offer

__all__ = ["generate_loi", "recommend_offer"]
