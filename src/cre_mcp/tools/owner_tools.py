"""MCP tool for public county parcel and owner enrichment."""

import logging

from cre_mcp.enrichment.owner import OwnerLookup

logger = logging.getLogger(__name__)
_lookup: OwnerLookup | None = None


def _engine() -> OwnerLookup:
    global _lookup
    if _lookup is None:
        _lookup = OwnerLookup()
    return _lookup


async def owner_lookup(
    address: str | None = None,
    apn: str | None = None,
    county: str | None = None,
) -> dict:
    """Look up public assessor parcel and owner data.

    Args:
        address: Site address. Include city/state or provide ``county`` separately.
        apn: County assessor parcel number (APN).
        county: County and state, such as ``Guilford County, NC``.

    Returns:
        A normalized OwnerRecord with its matching parcel, or an error dictionary.
    """
    logger.info(
        "owner_lookup called: address=%s apn=%s county=%s",
        address,
        apn,
        county,
    )
    try:
        owner = await _engine().lookup(address=address, apn=apn, county=county)
        if owner is None:
            return {"error": "No configured county parcel record found"}
        return owner.model_dump(mode="json")
    except Exception as exc:
        logger.error("owner_lookup error: %s", exc)
        return {"error": str(exc)}


__all__ = ["owner_lookup"]
