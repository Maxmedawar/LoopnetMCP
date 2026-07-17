"""Buyer facts used to personalize a decision frontier."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class BuyerProfile(BaseModel):
    """Known buyer constraints; ``None`` always means not yet known."""

    model_config = ConfigDict(extra="ignore")

    cash_available: float | None = None
    reserves_required: float | None = None
    liquidity_after_close: float | None = None
    net_worth: float | None = None
    guaranty_capacity: float | None = None

    return_requirement_irr: float | None = None
    max_acceptable_loss: float | None = None
    hold_pref_years: int | None = None

    needs_current_distributions: bool | None = None
    recourse_tolerance: Literal["none", "partial", "full"] | None = None
    can_raise_equity: bool | None = None
    operating_capability: Literal["passive", "light", "heavy"] | None = None
    construction_experience: bool | None = None
    tax_deferral_need: bool | None = None
    closing_track_record: Literal["none", "some", "strong"] | None = None
    local_partner: bool | None = None
    geographic_focus: str | None = None
    portfolio_concentration: str | None = None


def normalize_buyer(data: dict[str, Any]) -> BuyerProfile:
    """Normalize a partial buyer mapping without inventing missing facts."""

    return BuyerProfile.model_validate(data)


__all__ = ["BuyerProfile", "normalize_buyer"]
