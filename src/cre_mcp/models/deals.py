"""Deal scoring input and output models."""

from pydantic import BaseModel, Field

from cre_mcp.models.attributes import DealAttributes
from cre_mcp.models.enrichment import OwnerRecord, ParcelRecord
from cre_mcp.models.listings import Listing
from cre_mcp.models.market import MarketPack, RentComps
from cre_mcp.models.scoring import DealScore
from cre_mcp.models.underwriting import UnderwritingResult


class DealContext(BaseModel):
    listing: Listing
    market: MarketPack | None = None
    parcel: ParcelRecord | None = None
    attributes: DealAttributes | None = None
    rent_comps: RentComps | None = None
    underwriting: UnderwritingResult | None = None


class Deal(BaseModel):
    listing: Listing
    market_pack: MarketPack | None = None
    parcel: ParcelRecord | None = None
    owner: OwnerRecord | None = None
    attributes: DealAttributes | None = None
    rent_comps: RentComps | None = None
    underwriting: UnderwritingResult | None = None
    scores: list[DealScore] = Field(default_factory=list)
    best_strategy: str | None = None
