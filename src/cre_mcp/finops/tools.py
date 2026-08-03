"""Plain financing-operations callables for later MCP registration.

This module deliberately has no FastMCP dependency or registration side effects.
Every public function contains failures at a stable ``{"error": ...}`` boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cre_mcp.access.context import current_context
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.access.result_models import RestrictedLenderMatchResult
from cre_mcp.config import CreConfig
from cre_mcp.source_rights.output import safe_error_message

from .assumable_detect import detect_assumable as _detect_assumable
from .cashneeds import cash_requirements as _cash_requirements
from .hedges import cap_cost_context as _cap_cost_context
from .lenders import match_lenders as _match_lenders
from .lenders import record_lender_profile as _record_lender_profile
from .notechain import reconcile_note_chain as _reconcile_note_chain
from .reporting import record_reporting_item as _record_reporting_item
from .reporting import reporting_calendar as _reporting_calendar
from .waivers import prepare_waiver_request as _prepare_waiver_request


logger = logging.getLogger(__name__)


def _restricted_projection_required() -> bool:
    context = current_context()
    return bool(
        context is not None
        and not context.trusted
        and context.profile in TERRITORY_LIMITED
    )


def _location_values(deal: Mapping[str, Any]) -> list[str]:
    supplied = [
        key
        for key in ("geography", "geographies", "market", "state")
        if deal.get(key) is not None
    ]
    if len(supplied) != 1:
        raise ValueError("exactly one lender geography alias is required")
    raw = deal[supplied[0]]
    values = raw if isinstance(raw, list) else [raw]
    if not values or not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError("lender geography values are malformed")
    normalized = [value.strip() for value in values]
    if len({value.casefold() for value in normalized}) != len(normalized):
        raise ValueError("lender geography values must be unique")
    return normalized


def _restricted_lender_match_projection(
    requested_deal: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    returned_deal = result.get("deal")
    raw_matches = result.get("matches")
    raw_ranked = result.get("ranked_lenders")
    raw_rubric = result.get("fit_rubric")
    if not isinstance(returned_deal, Mapping):
        raise ValueError("lender match result is missing its deal")
    if type(raw_matches) is not list or not all(
        isinstance(item, Mapping) for item in raw_matches
    ):
        raise ValueError("lender match rows are malformed")
    if raw_ranked is not None and raw_ranked != raw_matches:
        raise ValueError("lender match duplicate rankings disagree")
    if not isinstance(raw_rubric, Mapping):
        raise ValueError("lender match rubric is malformed")

    requested_locations = _location_values(requested_deal)
    returned_locations = returned_deal.get("geographies")
    if type(returned_locations) is not list or not all(
        isinstance(value, str) and value.strip() for value in returned_locations
    ):
        raise ValueError("lender match result locations are malformed")
    normalized_returned = [value.strip() for value in returned_locations]
    if [value.casefold() for value in requested_locations] != [
        value.casefold() for value in normalized_returned
    ]:
        raise ValueError("lender match result does not match the requested geography")

    matches: list[dict[str, Any]] = []
    for item in raw_matches:
        dimensions = item.get("fit_dimensions")
        if not isinstance(dimensions, Mapping):
            raise ValueError("lender match dimensions are malformed")
        safe_dimensions: dict[str, dict[str, Any]] = {}
        for name in ("size", "geography", "asset_type", "leverage"):
            dimension = dimensions.get(name)
            if not isinstance(dimension, Mapping):
                raise ValueError("lender match dimension is missing")
            safe_dimensions[name] = {
                "status": dimension.get("status"),
                "points": dimension.get("points"),
                "max_points": dimension.get("max_points"),
            }
        matches.append(
            {
                "lender_id": item.get("lender_id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "size_min_cents": item.get("size_min_cents", item.get("size_min")),
                "size_max_cents": item.get("size_max_cents", item.get("size_max")),
                "leverage_max": item.get("leverage_max"),
                "asset_types": item.get("asset_types"),
                "fit_score": item.get("fit_score"),
                "fit_score_max": item.get("fit_score_max"),
                "fit_status": item.get("fit_status"),
                "fit_dimensions": safe_dimensions,
                "last_confirmed": item.get("last_confirmed"),
                "is_stale": item.get("is_stale"),
                "days_since_confirmed": item.get("days_since_confirmed"),
                "fit_rank": item.get("fit_rank"),
            }
        )
    payload = {
        "as_of": result.get("as_of"),
        "stale_after_days": result.get("stale_after_days"),
        "deal": {
            "loan_amount_cents": returned_deal.get("loan_amount_cents"),
            "locations": [
                {"location": value} for value in normalized_returned
            ],
            "asset_types": returned_deal.get("asset_types"),
            "leverage": returned_deal.get("leverage"),
        },
        "lender_count": len(matches),
        "matches": matches,
        "fit_rubric": {
            "size": raw_rubric.get("size"),
            "geography": raw_rubric.get("geography"),
            "asset_type": raw_rubric.get("asset_type"),
            "leverage": raw_rubric.get("leverage"),
            "unknown_values_receive_neutral_partial_credit": raw_rubric.get(
                "unknown_values_receive_neutral_partial_credit"
            ),
        },
    }
    return RestrictedLenderMatchResult.model_validate(
        payload,
        strict=True,
    ).model_dump(mode="json")


def _error(tool_name: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = safe_error_message(message or exc.__class__.__name__)
    logger.error("%s error: %s", tool_name, message)
    return {"error": message}


def cash_requirements(
    horizon_days: int,
    inputs: Mapping[str, Any],
    *,
    as_of: Any = None,
) -> dict[str, Any]:
    """Build a penny-exact 30/60/90-day cash requirement schedule."""

    try:
        return _cash_requirements(horizon_days, inputs, as_of=as_of)
    except Exception as exc:
        return _error("cash_requirements", exc)


def detect_assumable(
    listing_or_om_text: str | Mapping[str, Any],
) -> dict[str, Any]:
    """Detect and cite existing-financing language without inferring consent."""

    try:
        return _detect_assumable(listing_or_om_text)
    except Exception as exc:
        return _error("detect_assumable", exc)


def record_lender_profile(
    profile_or_name: Mapping[str, Any] | str | None = None,
    type: str | None = None,
    geographies: Sequence[str] | str | None = None,
    asset_types: Sequence[str] | str | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    leverage_max: Any = None,
    rate_context: str | None = None,
    last_confirmed: Any = None,
    source: str | None = None,
    *,
    name: str | None = None,
    lender_type: str | None = None,
    size_min_cents: int | None = None,
    size_max_cents: int | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Accrue a sourced lender-appetite profile in the owned table."""

    try:
        return _record_lender_profile(
            profile_or_name,
            type,
            geographies,
            asset_types,
            size_min,
            size_max,
            leverage_max,
            rate_context,
            last_confirmed,
            source,
            name=name,
            lender_type=lender_type,
            size_min_cents=size_min_cents,
            size_max_cents=size_max_cents,
            db_path=db_path,
            config=config,
        )
    except Exception as exc:
        return _error("record_lender_profile", exc)


def match_lenders(
    deal: Mapping[str, Any],
    *,
    as_of: Any = None,
    stale_after_days: int = 180,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Rank stored appetite fit while keeping stale data visibly qualified."""

    try:
        result = _match_lenders(
            deal,
            as_of=as_of,
            stale_after_days=stale_after_days,
            db_path=db_path,
            config=config,
        )
        if _restricted_projection_required():
            return _restricted_lender_match_projection(deal, result)
        return result
    except Exception as exc:
        return _error("match_lenders", exc)


def cap_cost_context(
    loan: Mapping[str, Any],
    cap: Mapping[str, Any],
) -> dict[str, Any]:
    """Return an illustrative convention range and penny-exact escrow math."""

    try:
        return _cap_cost_context(loan, cap)
    except Exception as exc:
        return _error("cap_cost_context", exc)


def prepare_waiver_request(
    loan: Mapping[str, Any],
    covenant_results: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ask: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble a factual waiver/extension/modification request for review."""

    try:
        return _prepare_waiver_request(loan, covenant_results, ask)
    except Exception as exc:
        return _error("prepare_waiver_request", exc)


def record_reporting_item(
    loan: str,
    item: str,
    frequency: str | None,
    next_due: Any,
    recipient: str | None = None,
    status: str | None = "pending",
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Record one lender-reporting obligation in the owned table."""

    try:
        return _record_reporting_item(
            loan,
            item,
            frequency,
            next_due,
            recipient,
            status,
            db_path,
        )
    except Exception as exc:
        return _error("record_reporting_item", exc)


def record_reporting(
    loan: str,
    item: str,
    frequency: str | None,
    next_due: Any,
    recipient: str | None = None,
    status: str | None = "pending",
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Compatibility alias for :func:`record_reporting_item`."""

    return record_reporting_item(
        loan,
        item,
        frequency,
        next_due,
        recipient,
        status,
        db_path,
    )


def reporting_calendar(
    days: int = 60,
    db_path: str | Path | CreConfig | None = None,
    as_of: Any = None,
    loan: str | None = None,
) -> dict[str, Any]:
    """List lender deliverables due in the inclusive forward window."""

    try:
        return _reporting_calendar(days, db_path, as_of, loan)
    except Exception as exc:
        return _error("reporting_calendar", exc)


def reconcile_note_chain(
    docs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Walk note and mortgage transfers and flag continuity defects for counsel."""

    try:
        return _reconcile_note_chain(docs)
    except Exception as exc:
        return _error("reconcile_note_chain", exc)


__all__ = [
    "cap_cost_context",
    "cash_requirements",
    "detect_assumable",
    "match_lenders",
    "prepare_waiver_request",
    "reconcile_note_chain",
    "record_lender_profile",
    "record_reporting",
    "record_reporting_item",
    "reporting_calendar",
]
