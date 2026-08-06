"""MCP boundaries for ownership structure and guarded 1031 management."""

from __future__ import annotations

import logging
import re

from cre_mcp.deals.store import DealStore, get_deal_store
from cre_mcp.models import Listing
from cre_mcp.structure.entity import recommend_structure as screen_structure
from cre_mcp.structure.exchange import (
    calc_boot_basis as calculate_boot_basis,
)
from cre_mcp.structure.exchange import (
    exchange_status as get_exchange_status,
)
from cre_mcp.structure.exchange import (
    identify_replacement as record_replacement,
)
from cre_mcp.structure.exchange import start_exchange as create_exchange
from cre_mcp.source_rights.output import safe_error_message, safe_source_reference
from cre_mcp.tools.deal_tools import analyze_deal

logger = logging.getLogger(__name__)


async def _ensure_saved_deal(
    value: str,
    source: str,
    store: DealStore,
) -> str:
    """Resolve an existing source:id or analyze and persist a URL/raw source id."""
    selected_source = source
    identifier = value
    saved_reference = (
        "://" not in value
        and re.fullmatch(r"[a-z0-9_]+:.+", value, re.IGNORECASE) is not None
    )
    if saved_reference and await store.get_deal(value) is not None:
        return value
    if saved_reference:
        selected_source, _, identifier = value.partition(":")
    analyzed = await analyze_deal(identifier, source=selected_source)
    if "error" in analyzed:
        raise ValueError(str(analyzed["error"]))
    listing = Listing.model_validate(analyzed.get("listing"))
    deal_id = await store.save_deal(listing)
    if deal_id is None:
        raise RuntimeError("deal could not be persisted; check the SQLite path and logs")
    return deal_id


async def recommend_structure(
    mode: str,
    investors: int = 0,
    passive: bool | None = None,
    state: str | None = None,
) -> dict:
    """Screen LLC, DST, TIC, and QOF fit with prominent tax/securities traps.

    Args:
        mode: One of solo, 1031, syndication, or oz.
        investors: Number of outside/co-investors; zero means the user alone.
        passive: Whether the user wants passive ownership/control.
        state: Optional property/formation-state context.

    Returns:
        StructureAdvice with alternatives, eligibility notes, traps, and counsel gate.
    """
    logger.info(
        "recommend_structure called: mode=%s investors=%s",
        safe_source_reference(mode),
        investors,
    )
    try:
        return screen_structure(
            {
                "mode": mode,
                "investors": investors,
                "passive": passive,
                "state": state,
            }
        ).model_dump(mode="json")
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("recommend_structure error: %s", message)
        return {"error": message}


async def start_exchange(
    deal_id: str,
    relinquished_close_date: str,
    source: str = "loopnet",
) -> dict:
    """Start and persist a guarded 45/180-day exchange clock.

    Args:
        deal_id: Saved source:source_id, listing URL, or raw source identifier.
        relinquished_close_date: Transfer/closing date as YYYY-MM-DD.
        source: Source used when deal_id is not already persisted.

    Returns:
        Exchange countdown with hard QI-before-closing and CPA/Form-8824 gates.
    """
    logger.info(
        "start_exchange called: deal=%s close=%s",
        safe_source_reference(deal_id),
        safe_source_reference(relinquished_close_date),
    )
    try:
        store = get_deal_store()
        saved_id = await _ensure_saved_deal(deal_id, source, store)
        return (
            await create_exchange(
                saved_id,
                relinquished_close_date,
                store=store,
            )
        ).model_dump(mode="json")
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("start_exchange error: %s", message)
        return {"error": message}


async def exchange_status(exchange_id: int | str) -> dict:
    """Return the current exchange clock, IDs, governing rule, and next action.

    Args:
        exchange_id: Persistent exchange identifier returned by start_exchange.

    Returns:
        Current Exchange state or an error dictionary.
    """
    logger.info("exchange_status called: exchange=%s", exchange_id)
    try:
        return (
            await get_exchange_status(exchange_id, store=get_deal_store())
        ).model_dump(mode="json")
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("exchange_status error: %s", message)
        return {"error": message}


async def identify_replacement(
    exchange_id: int | str,
    url_or_id: str,
    source: str = "loopnet",
) -> dict:
    """Persist a replacement candidate if the day-45 and ID-count/value rules permit it.

    Args:
        exchange_id: Persistent exchange identifier.
        url_or_id: Saved deal id, listing URL, or raw source identifier.
        source: Source used when the replacement is not already persisted.

    Returns:
        Updated Exchange status or an error dictionary.
    """
    logger.info(
        "identify_replacement called: exchange=%s listing=%s",
        exchange_id,
        safe_source_reference(url_or_id, source=source),
    )
    try:
        store = get_deal_store()
        deal_id = await _ensure_saved_deal(url_or_id, source, store)
        return (
            await record_replacement(exchange_id, deal_id, store=store)
        ).model_dump(mode="json")
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("identify_replacement error: %s", message)
        return {"error": message}


async def calc_boot_basis(
    relinquished_price: float,
    relinquished_adjusted_basis: float,
    replacement_price: float,
    relinquished_debt: float = 0,
    replacement_debt: float = 0,
) -> dict:
    """Estimate 1031 cash/debt boot and replacement carryover basis.

    Args:
        relinquished_price: Gross value/sale price of property given up.
        relinquished_adjusted_basis: Tax basis before the exchange.
        replacement_price: Gross value/purchase price of replacement property.
        relinquished_debt: Debt paid off or transferred with relinquished property.
        replacement_debt: Debt assumed/placed on replacement property.

    Returns:
        BootBasisResult with assumptions and mandatory CPA/Form-8824 gate.
    """
    logger.info("calc_boot_basis called")
    try:
        return calculate_boot_basis(
            {
                "sale_price": relinquished_price,
                "adjusted_basis": relinquished_adjusted_basis,
                "debt": relinquished_debt,
            },
            {
                "purchase_price": replacement_price,
                "debt": replacement_debt,
            },
        ).model_dump(mode="json")
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("calc_boot_basis error: %s", message)
        return {"error": message}


__all__ = [
    "calc_boot_basis",
    "exchange_status",
    "identify_replacement",
    "recommend_structure",
    "start_exchange",
]
