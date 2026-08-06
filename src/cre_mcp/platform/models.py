"""Typed immutable records returned by the platform repository."""
from __future__ import annotations

import unicodedata
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


def normalize_platform_email(value: str) -> str:
    """The one canonical form of `platform_users.email`.

    This lives here, next to the other domain constants, because it must be
    applied at *every* site that writes a platform login and at the single site
    that looks one up. Two independent reviews found the same defect twice: a
    read path and a write path that each normalized reasonably but differently,
    which silently locked the rightful owner out and handed their row to
    whoever controlled the address the other fold produced.

    `str.lower()` then NFC, so a composed and a decomposed spelling of the same
    address agree rather than becoming two people.

    `str.casefold()` is deliberately not used: it maps `ß` to `ss`, `ﬁ` to
    `fi`, and `ſ` to `s`, collapsing addresses that are separate mailboxes onto
    one row. `str.lower()` does none of that — it leaves all three alone — so
    it gives full case-insensitivity without merging distinct people.

    An ASCII-only fold was tried first and was wrong in the other direction: it
    left non-ASCII capitals alone, so an operator who typed `MÜLLER@corp.test`
    stored a row that the owner of `müller@corp.test` could never bind to. Case
    insensitivity has to cover the whole alphabet or it is not case
    insensitivity.

    `ς` is unified onto `σ`, and that single step is what makes the fold safe
    for Greek. `str.lower()` is not a per-code-point map: it implements
    Unicode's `Final_Sigma` context rule, so `Σ` becomes `ς` at a word boundary
    and `σ` elsewhere. Without the unification the key depended on where in the
    address the letter sat — `ΓΙΩΡΓΟΣ@CORP.TEST` folded to `γιωργος@…` while
    its owner's `γιωργοσ@…` folded to itself, locking the owner out and handing
    the row to whoever held the other spelling. `Σ` is the uppercase of both
    forms, so no fold of it can be correct without unifying them; `casefold()`
    does the same.

    Folding per code point to sidestep `Final_Sigma` was tried and is not kept:
    with the unification applied the two are the same function on every input,
    so the loop was an equivalent mutant whose comment claimed a safety it did
    not provide.
    """
    return unicodedata.normalize("NFC", value.strip().lower().replace("ς", "σ"))


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
    subject_user_id: int | None = None


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
