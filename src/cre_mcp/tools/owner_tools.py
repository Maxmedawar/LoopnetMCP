"""MCP tool for public county parcel and owner enrichment."""

import logging

from cre_mcp.access.context import current_context, current_runtime_config
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.enrichment.owner import OwnerLookup
from cre_mcp.models import OwnerRecord
from cre_mcp.source_rights.output import (
    safe_error_message,
    safe_source_reference,
    sanitize_payload,
)

logger = logging.getLogger(__name__)
_lookup: OwnerLookup | None = None


def _engine() -> OwnerLookup:
    global _lookup
    runtime = current_runtime_config()
    if runtime is not None:
        return OwnerLookup(runtime)
    if _lookup is None:
        _lookup = OwnerLookup()
    return _lookup


def _restricted_owner_projection(owner: OwnerRecord) -> OwnerRecord:
    """Remove opaque provider blobs only at a limited-profile boundary."""
    context = current_context()
    if (
        context is None
        or context.trusted
        or context.profile not in TERRITORY_LIMITED
    ):
        return owner
    return owner.model_copy(
        update={
            "mailing_address": None,
            "parcels": [
                parcel.model_copy(
                    update={
                        "owner_mailing_address": None,
                        "lat": None,
                        "lon": None,
                        "raw": {},
                    }
                )
                for parcel in owner.parcels
            ]
        }
    )


async def owner_lookup(
    address: str | None = None,
    apn: str | None = None,
    county: str | None = None,
) -> dict:
    """Look up free-first parcel and owner data with opt-in paid fallback.

    Args:
        address: Site address. Include city/state or provide ``county`` separately.
        apn: County assessor parcel number (APN).
        county: County and state, such as ``Guilford County, NC``.

    Returns:
        A normalized OwnerRecord with its matching parcel, or an error dictionary.
        ATTOM/Regrid are called only when explicitly keyed and public coverage misses.
    """
    logger.info(
        "owner_lookup called: address=%s apn=%s county=%s",
        safe_source_reference(address or ""),
        safe_source_reference(apn or ""),
        safe_source_reference(county or ""),
    )
    try:
        owner = await _engine().lookup(address=address, apn=apn, county=county)
        if owner is None:
            return {"error": "No parcel record found in the enabled provider chain"}
        return sanitize_payload(
            _restricted_owner_projection(owner).model_dump(mode="json")
        )
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("owner_lookup error: %s", message)
        return {"error": message}


__all__ = ["owner_lookup"]
