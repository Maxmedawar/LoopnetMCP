"""Honest self-description tools (Phase 31)."""

from __future__ import annotations

import logging

from cre_mcp.positioning import (
    AUTHORITY_MATRIX,
    CAPABILITIES,
    STANDARD_DISCLAIMER,
    assumptions_sheet,
)
from cre_mcp.source_rights.output import safe_error_message

logger = logging.getLogger(__name__)


async def capabilities() -> dict:
    """State honestly what this engine can and cannot do, plus who may act.

    Returns the capability list, the honest promise (and the promise it will NOT
    make), the action authority matrix (AI may research/draft/recommend but never
    send, commit, or wire without human approval), and the standard disclaimer.
    Use this when a user asks "what can this do" or before relying on any output.
    """
    logger.info("capabilities called")
    return {
        "capabilities": CAPABILITIES,
        "authority_matrix": AUTHORITY_MATRIX,
        "disclaimer": STANDARD_DISCLAIMER,
        "positioning": (
            "Screen deals in seconds; build a VERIFIED underwriting as the real documents "
            "arrive. Market data gives direction and a range — verify rents with lease comps "
            "and rates with executable lender quotes. A score never hides a fatal flaw, an "
            "unverified source, or a buyer mismatch."
        ),
    }


async def deal_assumptions(inputs: dict | None = None) -> dict:
    """Return the assumption sheet behind a decision so nothing hides behind a number.

    Args:
        inputs: The drivers used (purchase_price, noi, noi_basis, vacancy_rate,
            cap_rate, financing_rate, ltv, hold_years, exit_cap, source_quality, ...).

    Returns:
        One row per driver with its value and source-quality label; unknown drivers
        are listed as unknown rather than silently defaulted, plus the disclaimer.
    """
    logger.info("deal_assumptions called")
    try:
        return {
            "assumptions": assumptions_sheet(inputs or {}),
            "disclaimer": STANDARD_DISCLAIMER,
        }
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("deal_assumptions error: %s", message)
        return {"error": message}


__all__ = ["capabilities", "deal_assumptions"]
