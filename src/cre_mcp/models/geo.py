"""Normalized geographic identifiers used by market-data providers."""

from enum import Enum

from pydantic import BaseModel


class GeoLevel(str, Enum):
    """Supported geographic levels."""

    STATE = "state"
    COUNTY = "county"
    CITY = "city"
    ZIP = "zip"
    CBSA = "cbsa"
    TRACT = "tract"


class GeoRef(BaseModel):
    """Canonical geographic reference shared across government datasets."""

    level: GeoLevel
    state_fips: str
    county_fips: str | None = None
    cbsa: str | None = None
    zip: str | None = None
    tract: str | None = None
    name: str

