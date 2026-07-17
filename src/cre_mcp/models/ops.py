"""Post-close operating calendar models."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


OpsCategory = Literal["month_one", "recurring", "lease", "nudge"]
OpsStatus = Literal["not_started", "in_progress", "complete", "waived"]


class OperatingItem(BaseModel):
    """One dated or recurring ownership task with an explicit reason and owner."""

    key: str
    category: OpsCategory
    label: str
    timing: str
    why: str
    action: str
    owner: str
    event_date: date | None = None
    reminder_days_before: list[int] = Field(default_factory=list)
    date_source: str
    status: OpsStatus = "not_started"


class OperatingPlaybook(BaseModel):
    """Month-one, recurring, lease-critical, and strategic ownership runway."""

    deal_id: str
    deal_ref: str
    property_name: str
    ownership_start: date
    month_one: list[OperatingItem] = Field(default_factory=list)
    recurring: list[OperatingItem] = Field(default_factory=list)
    critical_dates: list[OperatingItem] = Field(default_factory=list)
    nudges: list[OperatingItem] = Field(default_factory=list)
    persistence_status: Literal["saved", "unavailable"]
    guardrail: str


__all__ = [
    "OperatingItem",
    "OperatingPlaybook",
    "OpsCategory",
    "OpsStatus",
]
