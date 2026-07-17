"""Plain, unregistered boundaries for prospecting heuristics."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from cre_mcp.prospect.assemblage import adjacent_parcels as _adjacent_parcels
from cre_mcp.prospect.microlocation import micro_location_score as _micro_location_score
from cre_mcp.prospect.portfolio_sellers import portfolio_owner_scan as _portfolio_owner_scan
from cre_mcp.prospect.rent_adjust import adjust_rent_comp as _adjust_rent_comp
from cre_mcp.prospect.saleleaseback import (
    sale_leaseback_candidates as _sale_leaseback_candidates,
)
from cre_mcp.prospect.stalled import stalled_projects as _stalled_projects

logger = logging.getLogger(__name__)


async def find_adjacent_parcels(
    lat: float | None = None,
    lon: float | None = None,
    parcel_id: str | None = None,
    county: str | None = None,
) -> dict[str, Any]:
    """Return heuristic county parcel-envelope candidates or an error dictionary."""

    try:
        return await _adjacent_parcels(
            lat=lat,
            lon=lon,
            parcel_id=parcel_id,
            county=county,
        )
    except Exception as exc:
        logger.error("find_adjacent_parcels error: %s", exc)
        return {"error": str(exc)}


def sale_leaseback_candidates(
    records: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return transparent owner/business-name overlap candidates."""

    try:
        return _sale_leaseback_candidates(records)
    except Exception as exc:
        logger.error("sale_leaseback_candidates error: %s", exc)
        return {"error": str(exc)}


def stalled_project_signals(
    permits: Sequence[Mapping[str, Any] | None] | Mapping[str, Any] | None = None,
    min_age_days: int | None = 365,
    as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Return permit-inactivity signals or an error dictionary."""

    try:
        return _stalled_projects(
            permits,
            min_age_days=min_age_days,
            as_of=as_of,
        )
    except Exception as exc:
        logger.error("stalled_project_signals error: %s", exc)
        return {"error": str(exc)}


def portfolio_owner_scan(
    records: Sequence[Mapping[str, Any]] | None = None,
    min_properties: int = 2,
) -> dict[str, Any]:
    """Return normalized portfolio-owner groups or an error dictionary."""

    try:
        return _portfolio_owner_scan(records, min_properties=min_properties)
    except Exception as exc:
        logger.error("portfolio_owner_scan error: %s", exc)
        return {"error": str(exc)}


def adjust_rent_comp(
    comp: Mapping[str, Any] | None = None,
    subject: Mapping[str, Any] | None = None,
    adjustments: Mapping[str, Any] | None = None,
    as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Return a convention-based adjusted rent range or an error dictionary."""

    try:
        return _adjust_rent_comp(
            comp,
            subject,
            adjustments=adjustments,
            as_of=as_of,
        )
    except Exception as exc:
        logger.error("adjust_rent_comp error: %s", exc)
        return {"error": str(exc)}


def micro_location_score(
    site: Mapping[str, Any] | None = None,
    nearby_anchors: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return an uncalibrated, factor-weighted site score or an error dictionary."""

    try:
        return _micro_location_score(site, nearby_anchors=nearby_anchors)
    except Exception as exc:
        logger.error("micro_location_score error: %s", exc)
        return {"error": str(exc)}


__all__ = [
    "adjust_rent_comp",
    "find_adjacent_parcels",
    "micro_location_score",
    "portfolio_owner_scan",
    "sale_leaseback_candidates",
    "stalled_project_signals",
]
