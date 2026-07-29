"""Typed immutable records returned by the platform repository."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

MEMBERSHIP_ROLES = ("owner", "admin", "member", "viewer")
INTERNAL_ADMIN_ROLES = ("platform_admin", "support")
ADMIN_REASON_CODES = (
    "initial_provisioning",
    "customer_request",
    "billing_correction",
    "entitlement_correction",
    "security_response",
    "support_resolution",
    "data_correction",
)
CLIENT_STATUSES = ("active", "revoked")
SAVED_DEAL_STAGES = (
    "watching", "analyzing", "pursuing", "under_contract", "closed", "passed"
)
CONSENT_TYPES = ("terms", "privacy", "marketing", "data_processing")
PRIVACY_REQUEST_KINDS = ("access", "export", "delete", "correct")
PRIVACY_REQUEST_STATUSES = ("received", "in_progress", "completed", "rejected")
PRIVACY_REQUEST_TRANSITIONS = {
    "received": frozenset({"in_progress", "completed", "rejected"}),
    "in_progress": frozenset({"completed", "rejected"}),
    "completed": frozenset(),
    "rejected": frozenset(),
}

class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

class User(Record):
    id: int
    email: str
    name: str
    created_at: datetime
    updated_at: datetime

class Plan(Record):
    id: int
    key: str
    name: str
    monthly_price_usd: float | None = None
    seat_limit: int | None = None
    daily_quotas: dict[str, int] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

class Workspace(Record):
    id: int
    public_id: str
    name: str
    slug: str | None = None
    plan_id: int | None = None
    created_at: datetime
    updated_at: datetime

class Membership(Record):
    id: int
    workspace_id: int
    user_id: int
    role: str
    created_at: datetime
    updated_at: datetime

class Territory(Record):
    id: int
    workspace_id: int
    name: str
    state: str | None = None
    market: str | None = None
    asset_type: str | None = None
    created_at: datetime
    updated_at: datetime

class ConnectedClient(Record):
    id: int
    workspace_id: int
    name: str
    client_type: str
    scopes: list[str]
    status: str
    created_at: datetime
    updated_at: datetime

class SavedDeal(Record):
    id: int
    workspace_id: int
    deal_ref: str
    title: str
    payload: dict
    stage: str
    created_at: datetime
    updated_at: datetime

class Note(Record):
    id: int
    workspace_id: int
    saved_deal_id: int
    author_user_id: int
    body: str
    created_at: datetime
    updated_at: datetime

class Outcome(Record):
    id: int
    workspace_id: int
    saved_deal_id: int
    closed: bool
    purchase_price: float | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

class ConsentRecord(Record):
    id: int
    workspace_id: int
    user_id: int
    consent_type: str
    granted: bool
    version: str
    created_at: datetime

class IntegrationEvent(Record):
    id: int
    workspace_id: int
    client_id: int | None = None
    event_type: str
    payload: dict
    created_at: datetime

class PrivacyRequest(Record):
    id: int
    workspace_id: int
    user_id: int
    kind: str
    status: str
    detail: str | None = None
    created_at: datetime
    updated_at: datetime


class InternalAdmin(Record):
    user_id: int
    role: str
    active: bool
    created_at: datetime
    updated_at: datetime


class ExternalAccount(Record):
    id: int
    workspace_id: int
    provider: str
    external_account_id: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AdminAudit(Record):
    id: int
    actor_user_id: int
    actor_role: str
    action: str
    workspace_id: int | None = None
    target_type: str
    target_id: str
    reason_code: str
    reason: str
    before_json: str
    after_json: str
    created_at: datetime
