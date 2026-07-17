"""Listing-derived and public-map property attributes."""

from pydantic import BaseModel


class DealAttributes(BaseModel):
    """Compact attributes surfaced with analyzed and ranked deals."""

    traffic_aadt: float | None = None
    drive_thru: bool | None = None
    parking: str | None = None
    size_sqft: float | None = None
