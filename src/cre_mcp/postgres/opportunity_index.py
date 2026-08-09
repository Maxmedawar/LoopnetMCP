"""The internal-only combined opportunity index.

Deliberately **not** a hosted domain repository. Every customer-reachable
persistence port in this program is a field on ``HostedRequestRepositories``,
which tool code reaches through ``current_hosted_request_repositories()``;
anything on that bundle is one capability away from a customer. This index spans
tenants by design, so it is reached only through an ``admin``-runtime pool with
an internal ``AuthorityContext`` — a path that fails closed three separate ways:
``medawarcre_app`` holds no grant on these relations, the app pool refuses
internal authority, and ``internal_authorized()`` requires a live staff role
plus a non-blank audit reason.

The canonical deduplication key reuses ``cre_mcp.access.territory`` rather than
introducing a second normalizer. The access engine already answers "where is
this property" from the same declared fields, using a pinned offline Census
authority; a second implementation would let "the same property" drift from
"where is this property" — two answers to adjacent questions, free to disagree.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from cre_mcp.access.territory import (
    canonicalize_location_text,
    city_claim_is_unambiguous,
    city_zip_pair_is_authoritative,
    normalize_city,
    normalize_state,
    normalize_zip,
)
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.pool import AuthorityContext, PostgresDatabase

INTERNAL_ROLES = frozenset(
    {
        "owner",
        "admin",
        "jv_operations",
        "support",
        "security_audit",
        "read_only_analyst",
    }
)
MUTATING_ROLES = frozenset({"owner", "admin"})
REASON_CODES = frozenset(
    {
        "duplicate_review",
        "pipeline_review",
        "quality_audit",
        "territory_review",
        "privacy_request",
        "ingestion",
    }
)
REVIEW_VERDICTS = frozenset(
    {
        "promote",
        "dismiss",
        "duplicate_confirmed",
        "duplicate_rejected",
        "needs_more_data",
    }
)
MAX_PAGE = 200
# Repository policy, not a database constraint. Migration 0009 originally
# carried internal_opportunities_property_type_check and this bound mirrored it;
# round five deleted that column from the shared entry, so nothing at the
# database bounds a property type any more and this is the only limit. Kept
# because ingestion is one transaction per workspace: the contract's answer to
# an observation the index cannot carry is to reject and count it, never to
# abort the batch.
MAX_PROPERTY_TYPE = 128
# The one tenant string that legitimately reaches the cross-tenant entry, so
# the one that has to be bounded there. 120 characters is longer than any real
# US street address and far shorter than the 88,011 a reviewer drove through it.
MAX_STREET = 120
# What each action's object_id actually names. It was the constant
# 'internal_opportunity' on every row, including `ingest`, whose object_id is a
# workspace uuid, and `list`, whose object_id is the literal
# 'internal_opportunity_index'. An audit row that misnames its object is the
# same category of defect as one that is missing.
_AUDIT_OBJECT_TYPES = {
    "ingest": "workspace",
    "list": "internal_opportunity_index",
}

_KEY_VERSION = "prop:v1"
_STREET_SUFFIXES = {
    "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "ROAD": "RD",
    "DRIVE": "DR", "LANE": "LN", "COURT": "CT", "PLACE": "PL",
    "TERRACE": "TER", "PARKWAY": "PKWY", "HIGHWAY": "HWY", "CIRCLE": "CIR",
    "SQUARE": "SQ", "TRAIL": "TRL", "NORTH": "N", "SOUTH": "S",
    "EAST": "E", "WEST": "W",
}


_TRANSIENT = (
    psycopg.errors.DeadlockDetected,
    psycopg.errors.SerializationFailure,
    psycopg.errors.LockNotAvailable,
    # Transient here specifically: it means a tenant record vanished between
    # this ingest reading `deals` and writing its observation. Re-reading is
    # the whole remedy.
    psycopg.errors.ForeignKeyViolation,
)


class InternalIndexUnavailable(RuntimeError):
    """The internal index boundary cannot complete safely."""


class _Refused(Exception):
    """An internal action refused inside its own transaction.

    Raising this rolls the transaction back — which is the point, since the
    action did not happen — and carries enough for the caller to write the
    audit row on a fresh connection before re-raising the real error. Auditing
    inside the doomed transaction is not an option: the row would roll back
    with it, which is exactly how five different existence probes came to be
    untraced.
    """

    def __init__(self, action: str, object_id: str, error: Exception) -> None:
        super().__init__(str(error))
        self.action = action
        self.object_id = object_id
        self.error = error


@dataclass(frozen=True)
class StaffRequest:
    """One reason-coded, role-limited internal action."""

    actor_user_id: str
    role: str
    reason_code: str
    reason: str

    def __post_init__(self) -> None:
        try:
            UUID(self.actor_user_id)
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("actor_user_id must be a UUID") from error
        if self.role not in INTERNAL_ROLES:
            raise ValueError(f"unsupported internal role: {self.role!r}")
        if self.reason_code not in REASON_CODES:
            raise ValueError(f"unsupported reason code: {self.reason_code!r}")
        if not isinstance(self.reason, str) or len(self.reason.strip()) < 3:
            raise ValueError("an internal action requires a stated reason")

    @property
    def may_mutate(self) -> bool:
        return self.role in MUTATING_ROLES


@dataclass(frozen=True)
class OpportunityFilters:
    market: str | None = None
    property_type: str | None = None
    min_score: float | None = None
    max_score: float | None = None
    stage: str | None = None
    outcome: str | None = None
    source_user_id: str | None = None
    workspace_id: str | None = None
    include_archived: bool = False

    def __post_init__(self) -> None:
        """Validate filter *values*, not only filter names.

        Being a frozen dataclass already rejects an unknown filter name. It did
        nothing about the value, so `workspace_id="not-a-uuid"` reached SQL and
        came back as a raw `InvalidTextRepresentation`, and `min_score="abc"`
        did the same. The contract promises arguments are validated before they
        reach SQL; a field name is only half of an argument.
        """
        for name in ("source_user_id", "workspace_id"):
            value = getattr(self, name)
            if value is None:
                continue
            try:
                UUID(str(value))
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(f"{name} must be a UUID") from error
        for name in ("min_score", "max_score"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
            # Finite, too. `inf` returned nothing, `-inf` returned everything
            # and `nan` returned nothing, each silently — no ValueError and no
            # database error, so a staff filter answered a question nobody
            # asked. `deals_score_finite_check` shows the schema already treats
            # non-finite numerics as a hazard.
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        for name in ("market", "property_type", "stage", "outcome"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be text")
        if not isinstance(self.include_archived, bool):
            raise ValueError("include_archived must be a boolean")


@dataclass(frozen=True)
class OpportunitySource:
    workspace_id: str
    workspace_public_id: str
    source_user_id: str
    origin: str
    source_deal_id: str | None
    source_search_result_id: str | None
    source_saved_search_id: str | None
    source: str
    source_record_id: str
    access_class: str
    score: float | None
    score_version: str
    stage: str | None
    outcome: str | None
    observed_property_identity: dict[str, Any]
    observed_market: str | None
    observed_property_type: str | None
    provenance: dict[str, Any]
    first_observed_at: datetime
    last_observed_at: datetime


@dataclass(frozen=True)
class ConflictPosition:
    workspace_id: str
    source_user_id: str
    value: str


@dataclass(frozen=True)
class OpportunityConflict:
    kind: str
    positions: tuple[ConflictPosition, ...]


@dataclass(frozen=True)
class OpportunityEntry:
    opportunity_id: str
    canonical_key: str
    title: str
    status: str
    market: str | None
    property_type: str | None
    property_identity: dict[str, Any]
    merged_into_opportunity_id: str | None
    first_observed_at: datetime
    last_observed_at: datetime
    sources: tuple[OpportunitySource, ...]
    conflicts: tuple[OpportunityConflict, ...]


@dataclass(frozen=True)
class OpportunityReview:
    id: str
    reviewer_user_id: str
    reviewer_role: str
    verdict: str
    reason_code: str
    reason: str
    note: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class OpportunityPage:
    entries: tuple[OpportunityEntry, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class OpportunityDetail:
    entry: OpportunityEntry
    reviews: tuple[OpportunityReview, ...]


@dataclass(frozen=True)
class IngestSummary:
    admitted: int
    rejected: int
    opportunities: int
    rejections: tuple[str, ...] = field(default=())


# ---------------------------------------------------------------------------
# Property identity. Declared fields only; never provider ``raw``.
# ---------------------------------------------------------------------------


def _normalized_street(value: str) -> str | None:
    """A narrow, punctuation- and accent-stable street key.

    Deliberately the same shape as ``normalize_city``: NFKD, strip combining
    marks, upper-case, punctuation to space, collapse whitespace. Then fold the
    fixed USPS suffix set, so "100 Main Street" and "100 MAIN ST" agree.

    Bounded, because this is the one tenant-supplied string that legitimately
    reaches the cross-tenant entry. It was unbounded: a reviewer put 88,011
    characters of tenant text through `listing.address` onto
    `internal_opportunities.title` and `property_identity`, admitted, on an
    entry that stayed active and outlived that tenant's erasure. A US street
    address is short; anything longer is not an address, and admitting it turns
    a property index into an arbitrary-text channel that tenant deletion cannot
    reach.
    """
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKD", canonicalize_location_text(value))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn").upper()
    text = re.sub(r"['’.,-]", " ", text)
    tokens = [_STREET_SUFFIXES.get(token, token) for token in text.split()]
    collapsed = " ".join(tokens).strip()
    if not collapsed or len(collapsed) > MAX_STREET:
        return None
    return collapsed


def canonical_property_key(identity: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Return ``(canonical_key, normalized_identity)`` or ``None``.

    ``None`` means the pinned authority cannot resolve this identity
    unambiguously. The caller rejects and counts it rather than guessing — an
    invented key would merge two different properties, which is worse than
    admitting nothing.
    """
    state = normalize_state(str(identity.get("state") or ""))
    city = normalize_city(str(identity.get("city") or ""))
    zip5 = normalize_zip(str(identity.get("zip_code") or ""))
    street = _normalized_street(str(identity.get("address") or ""))
    if not (state and city and street):
        return None

    # The city must resolve to one place. With a ZIP, city and ZIP must agree;
    # without one, the city must be unambiguous in that state on its own.
    if zip5:
        if not city_zip_pair_is_authoritative(f"{city},{state}", zip5):
            return None
    elif not city_claim_is_unambiguous(city, state):
        return None

    normalized = {
        "address": street,
        "city": city,
        "state": state,
        "zip_code": zip5 or "",
    }
    digest = hashlib.sha256(
        "\x1f".join(
            (normalized["state"], normalized["zip_code"],
             normalized["city"], normalized["address"])
        ).encode("utf-8")
    ).hexdigest()
    return f"{_KEY_VERSION}:{digest}", normalized


def _market(normalized: dict[str, Any]) -> str:
    return f"{normalized['city'].title()}, {normalized['state']}"


def _entry_title(normalized: dict[str, Any]) -> str:
    """The shared entry's label, derived — never the tenant's own words.

    `internal_opportunities` is the one cross-tenant table in this program, and
    a workspace delete cannot remove a row another workspace still contributes
    to. Copying `deals.title` into it put tenant free text somewhere tenant
    erasure could not reach: a reviewer deleted every source record and read
    "Confidential off-market assemblage for Acme Holdings" back out of the
    archived entry. Deriving the label from the normalized address keeps the
    tenant's own words in `observed_property_identity` on the source rows,
    which cascade away with the tenant record that supplied them.
    """
    address = normalized["address"].title()
    return f"{address}, {_market(normalized)}"


def _derived_property_type(sources: Any) -> str | None:
    """The entry's property type, derived from its contributing observations.

    Not stored. `internal_opportunities` outlives any single tenant, so a
    tenant-supplied string on that row survives an erasure it should not — and
    round four's refresh-on-conflict made the *last* ingesting workspace's words
    win, which a customer could steer through its own `deals.listing` grant.
    Deriving it here means it disappears exactly when the source rows do.

    ``None`` whenever the observations do not agree on one value — which is
    *not* the same condition as a reported conflict, and the difference is
    visible to staff. Two workspaces each holding {office, retail} agree, so no
    conflict is reported, and the label is still blank because there is no one
    value to show. A single workspace holding both is the same. So a blank label
    with an empty conflict tuple is a real state, and it means "the observations
    name more than one type", not "nothing was declared".

    An earlier version of this docstring said ``None`` meant the workspaces
    disagree and that the conflict report names both sides. A reviewer measured
    both shapes above and found the label blank with no conflict; the contract
    already stated this correctly and the docstring did not.
    """
    declared = {
        source.observed_property_type
        for source in sources
        if source.observed_property_type is not None
    }
    return declared.pop() if len(declared) == 1 else None


def _bounded_property_type(value: Any) -> tuple[str | None, str | None]:
    """Return ``(property_type, rejection_reason)``.

    Tenant-supplied and unvalidated upstream — `Listing.property_type` is a
    bare `str | None`, and the Crexi mapper emits an unbounded
    `", ".join(types)`. Blank and untrimmed values are normalized because they
    carry no information; an over-long one is rejected rather than truncated,
    since a silently shortened type would make the `property_type` filter
    answer for a value the tenant never declared.
    """
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"property_type is {type(value).__name__}, not text"
    trimmed = value.strip()
    if not trimmed:
        return None, None
    if len(trimmed) > MAX_PROPERTY_TYPE:
        return None, (
            f"property_type is {len(trimmed)} characters, "
            f"over the {MAX_PROPERTY_TYPE} the index stores"
        )
    return trimmed, None


# ---------------------------------------------------------------------------


class InternalOpportunityIndex:
    """Staff-only, reason-coded, audited access to the combined index."""

    def __init__(self, database: PostgresDatabase) -> None:
        if database.settings.runtime_mode != "admin":
            raise InternalIndexUnavailable(
                "the internal opportunity index requires the admin runtime"
            )
        self._database = database

    @classmethod
    def for_dsn(cls, dsn: str) -> "InternalOpportunityIndex":
        database = PostgresDatabase(
            PostgresSettings(dsn=dsn, runtime_mode="admin", min_size=0, max_size=4)
        )
        database.open(wait=True)
        return cls(database)

    def close(self) -> None:
        self._database.close()

    # -- internals ---------------------------------------------------------

    def _context(self, request: StaffRequest) -> AuthorityContext:
        return AuthorityContext.internal(
            request.actor_user_id, request.role, request.reason
        )

    def _audit(
        self,
        connection: psycopg.Connection,
        request: StaffRequest,
        *,
        action: str,
        object_id: str,
        result: str,
        workspace_id: str | None = None,
    ) -> None:
        """One audit row, in the same transaction as the work it describes.

        A read whose audit row cannot be written does not return data, because
        the insert and the select share this transaction.
        """
        connection.execute(
            "INSERT INTO medawarcre.staff_audit_log("
            "actor_user_id,actor_role,reason,reason_code,workspace_id,"
            "object_type,object_id,action,result) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                request.actor_user_id, request.role, request.reason,
                request.reason_code, workspace_id,
                _AUDIT_OBJECT_TYPES.get(action, "internal_opportunity"),
                object_id, action, result,
            ),
        )

    def _require_mutation(
        self, request: StaffRequest, *, action: str, object_id: str
    ) -> None:
        """Refuse a mutation the role may not perform — and record the refusal.

        This raised before writing anything, so a `read_only_analyst` attempting
        four different mutations produced four `PermissionError`s and zero audit
        rows. The contract requires every mutation to write exactly one row
        carrying its result, and `denied` is in the result vocabulary precisely
        for this. An attempted privilege escalation is the case you least want
        missing from the log.
        """
        if request.may_mutate:
            return
        self._audit_out_of_band(
            request, action=action, object_id=object_id, result="denied"
        )
        raise PermissionError(
            f"role {request.role!r} may read the internal index but not change it"
        )

    # -- ingestion ---------------------------------------------------------

    def ingest_workspace(
        self, request: StaffRequest, workspace_id: str
    ) -> IngestSummary:
        """Aggregate one workspace's deals into the combined index.

        Server-side by construction: the console never reads a tenant database,
        it calls this. Tenant boundaries survive — each observation becomes its
        own source row carrying the workspace it came from.
        """
        self._require_mutation(request, action="ingest", object_id=workspace_id)
        # A bounded retry on the whole transient set, not one member of it.
        #
        # Catching only DeadlockDetected was too narrow. An ordinary tenant
        # deleting one of its own deals between this ingest's SELECT and its
        # source INSERT raises ForeignKeyViolation, which was not retried, so
        # the entire workspace's batch was lost — a reviewer measured 6 and 14
        # in 30 trials through two ordinary public calls. That is transient in
        # exactly the sense that matters: the retry re-reads `deals`, and the
        # deleted row is simply not there the second time. The record used to
        # say the retry meant "a staff batch survives"; it did not, it failed
        # through a different door at a comparable rate.
        attempts = 3
        for attempt in range(attempts):
            try:
                return self._ingest_workspace(request, workspace_id)
            except _TRANSIENT:
                if attempt + 1 < attempts:
                    continue
                self._audit_ingest_failure(request, workspace_id)
                raise
            except Exception:
                self._audit_ingest_failure(request, workspace_id)
                raise
        raise AssertionError("unreachable")

    def _record_refusal(self, request: StaffRequest, refusal: _Refused) -> None:
        """Audit a refused action, then raise what actually went wrong."""
        self._audit_out_of_band(
            request, action=refusal.action, object_id=refusal.object_id,
            result="failed",
        )
        raise refusal.error from None

    @contextmanager
    def _audited_action(
        self, request: StaffRequest, *, action: str, object_id: str
    ) -> Iterator[None]:
        """Audit every way an internal action can fail, not only the refusals.

        `_Refused` covered the checks this code makes. It did not cover the
        transaction aborting underneath them: a deadlocked `merge_opportunities`
        left **no audit row at all**, because the audit insert lives inside the
        doomed transaction.

        Named `action`, not `mutation`, because round six applied it to
        mutations only and a reviewer then measured the reads: under an
        identical induced failure, merge, review and ingest each wrote one
        `failed` row and `list_opportunities` and `get_opportunity` wrote none.
        The contract says every read *and* every mutation writes exactly one row
        carrying its result, and this record had already twice declared the
        untraced-action class closed.
        """
        try:
            yield
        except _Refused as refusal:
            self._record_refusal(request, refusal)
        except Exception:
            self._audit_out_of_band(
                request, action=action, object_id=object_id, result="failed",
            )
            raise

    def _audit_ingest_failure(
        self, request: StaffRequest, workspace_id: str
    ) -> None:
        """Record that staff attempted an ingest that did not complete.

        One transaction per workspace means an abort rolls the audit row back
        with the work, so a failed ingest left no trace at all. Written on its
        own connection for exactly that reason, and only once the retries are
        exhausted, so a deadlock that succeeded on the next attempt is not
        recorded as a failure that did not happen.
        """
        # Deliberately unlinked. Passing the workspace here wrote a non-NULL
        # staff_audit_log.workspace_id whenever the workspace existed — the
        # NULL fallback only fires when the foreign key is itself what failed —
        # so an ingest that *did not happen* made that workspace permanently
        # undeletable, exactly as a successful one does. The workspace id is
        # still on the row, in object_id, so nothing is lost from the record.
        self._audit_out_of_band(
            request, action="ingest", object_id=workspace_id, result="failed",
        )

    def _audit_out_of_band(
        self,
        request: StaffRequest,
        *,
        action: str,
        object_id: str,
        result: str,
    ) -> None:
        """Write one **unlinked** audit row on its own connection.

        Used where the work itself has failed or been refused, so there is no
        surviving transaction to carry the row: an aborted action rolls its own
        audit insert back with it, and a role refusal never opens one.

        Unlinked deliberately, and no longer optional. An earlier version took a
        `workspace_id` and tried the linked row first, falling back to NULL only
        when that insert itself raised — so an action that *did not happen*
        made the workspace permanently undeletable exactly as a successful one
        does. Every caller now omits it, and the workspace is still identified
        on the row through `object_id`. A reviewer found the parameter had
        become unreachable dead code whose docstring still described it as live.
        """
        try:
            with self._database.connection(self._context(request)) as connection:
                self._audit(
                    connection, request, action=action, object_id=object_id,
                    result=result,
                )
        except Exception:
            # Never let the audit of a failure replace the failure itself.
            return

    def _ingest_workspace(
        self, request: StaffRequest, workspace_id: str
    ) -> IngestSummary:
        admitted = rejected = 0
        rejections: list[str] = []
        opportunities: set[str] = set()

        with self._database.connection(self._context(request)) as connection:
            if connection.execute(
                "SELECT 1 FROM medawarcre.workspaces WHERE id=%s",
                (workspace_id,),
            ).fetchone() is None:
                raise LookupError("no such workspace")

            deals = connection.execute(
                "SELECT id, source, source_record_id, title, listing, stage, "
                "score, score_version, created_by_user_id "
                "FROM medawarcre.deals WHERE workspace_id=%s ORDER BY id",
                (workspace_id,),
            ).fetchall()

            # Resolve every identity before touching the index, then work in
            # canonical-key order. Two workspaces observing the same properties
            # took the ON CONFLICT row locks in each workspace's own deal-id
            # order, which is effectively random relative to the other's: a
            # reviewer measured deadlocks in 6 of 8 concurrent trials, and the
            # loser's entire ingest aborted. A total order on the contended
            # rows is what removes the cycle.
            planned: list[tuple[Any, ...]] = []
            for row in deals:
                (deal_id, source, source_record_id, _title, listing, stage,
                 score, score_version, created_by) = row
                identity = listing if isinstance(listing, dict) else {}
                resolved = canonical_property_key(identity)
                if resolved is None or created_by is None:
                    rejected += 1
                    rejections.append(str(deal_id))
                    continue
                property_type, refusal = _bounded_property_type(
                    identity.get("property_type")
                )
                if refusal is not None:
                    rejected += 1
                    rejections.append(f"{deal_id}: {refusal}")
                    continue
                canonical_key, normalized = resolved
                planned.append(
                    (canonical_key, str(deal_id), deal_id, source,
                     source_record_id, identity, stage, score, score_version,
                     created_by, normalized, property_type)
                )
            planned.sort(key=lambda item: (item[0], item[1]))

            # Lock every *existing* entry this ingest can touch, in id order,
            # before writing anything.
            #
            # Ordering the upserts by canonical key was not sufficient. The
            # source upsert's re-bind fires
            # internal_opportunity_sources_archive_orphan, whose UPDATE locks
            # the row the observation is moving *off* — an entry that is not in
            # the planned sequence at all and whose key can sort earlier. Two
            # workspaces correcting addresses that swap entries then walked the
            # rows in opposite orders: one reviewer measured 3 aborted ingests
            # in 10 trials, another 29 in 30, in both cases one tenant's
            # correction destroying an unrelated tenant's whole ingest.
            #
            # id is a total order both transactions agree on, and it covers the
            # trigger's row because that row is one this workspace's existing
            # sources point at.
            #
            # Entries created *inside* this transaction are ordered by
            # `planned.sort` above, not by this lock. An earlier version of this
            # comment claimed they "cannot deadlock: a concurrent insert of the
            # same canonical key blocks on the unique index, which is a single
            # wait, not a cycle". That is true of one key and false of two: two
            # ingests creating K1 and K2 in opposite orders each hold one
            # speculative unique-index entry and wait on the other. A reviewer
            # deleted `planned.sort` and the entire suite stayed green, which is
            # why the sort is pinned separately below.
            # The set is closed under "rows this ingest will actually touch",
            # which means following merge links. An observation whose matched
            # entry is merged files under the head, and the foreign key on
            # internal_opportunity_sources.opportunity_id then takes FOR KEY
            # SHARE on that head — a row in neither of the two obvious sets and
            # free to sort before them. Both round-six reviewers measured it:
            # 13 aborted ingests in 30 rounds, and a deterministic deadlock
            # sequenced through pg_stat_activity.
            connection.execute(
                "WITH touched AS ("
                "  SELECT id, merged_into_opportunity_id "
                "  FROM medawarcre.internal_opportunities "
                "  WHERE canonical_key = ANY(%s) OR id IN ("
                "    SELECT opportunity_id "
                "    FROM medawarcre.internal_opportunity_sources "
                "    WHERE workspace_id = %s)"
                ") "
                "SELECT id FROM medawarcre.internal_opportunities "
                "WHERE id IN (SELECT id FROM touched) "
                "   OR id IN (SELECT merged_into_opportunity_id FROM touched "
                "             WHERE merged_into_opportunity_id IS NOT NULL) "
                "ORDER BY id FOR UPDATE",
                ([item[0] for item in planned], workspace_id),
            ).fetchall()

            for (canonical_key, _sort_id, deal_id, source, source_record_id,
                 identity, stage, score, score_version, created_by,
                 normalized, property_type) in planned:
                outcome_row = connection.execute(
                    "SELECT closed, went_bad FROM medawarcre.deal_outcomes "
                    "WHERE workspace_id=%s AND deal_id=%s",
                    (workspace_id, deal_id),
                ).fetchone()
                if outcome_row is None:
                    outcome = None
                elif outcome_row[1]:
                    outcome = "went_bad"
                elif outcome_row[0]:
                    outcome = "closed"
                else:
                    outcome = "open"
                if stage == "passed":
                    outcome = outcome or "passed"

                matched_id = connection.execute(
                    "INSERT INTO medawarcre.internal_opportunities("
                    "canonical_key,title,status,property_identity,market,"
                    "normalized_facts) "
                    "VALUES (%s,%s,'active',%s::jsonb,%s,'{}'::jsonb) "
                    "ON CONFLICT (canonical_key) DO UPDATE SET "
                    # GREATEST, not the bare clock. statement_timestamp() is
                    # the real time this statement began, so a transaction that
                    # blocked on another's row lock applies a timestamp from
                    # *before* the winner inserted the row — and
                    # internal_opportunities_observed_order_check then aborts
                    # the whole workspace ingest. transaction_timestamp() is
                    # constant across the transaction, so the entry and the
                    # source row written just below agree exactly rather than
                    # the entry trailing its own newest source.
                    "last_observed_at=GREATEST("
                    "internal_opportunities.first_observed_at,"
                    "internal_opportunities.last_observed_at,"
                    "transaction_timestamp()),"
                    # A property observed again returns to the listing.
                    # Archived-only, so a merge link is never undone here.
                    "status=CASE WHEN internal_opportunities.status="
                    "'archived' AND "
                    "internal_opportunities.merged_into_opportunity_id "
                    "IS NULL THEN 'active' "
                    "ELSE internal_opportunities.status END,"
                    # Refreshed, not write-once. These were set by whichever
                    # workspace observed the property first and never updated,
                    # so a corrected identity never reached the entry. All three
                    # are derived from the same normalized key every contributor
                    # agrees on, so refreshing them cannot express one
                    # workspace's view over another's. property_type is
                    # deliberately absent — see migration 0009.
                    "title=EXCLUDED.title,"
                    "property_identity=EXCLUDED.property_identity,"
                    "market=EXCLUDED.market,"
                    "updated_at=transaction_timestamp() "
                    "RETURNING id, merged_into_opportunity_id",
                    (
                        canonical_key, _entry_title(normalized),
                        json.dumps(normalized),
                        _market(normalized),
                    ),
                ).fetchone()

                # File the observation under the canonical entry.
                #
                # When staff have merged this property into another, the
                # observation belongs to the entry staff said it is the same
                # property as. Attaching it to the superseded entry instead made
                # a live tenant record invisible: a reviewer merged A into B, A's
                # tenant deleted its deal so the trigger archived A with its link
                # retained, and then an uninvolved workspace genuinely acquired
                # A's property — `admitted=1`, and the observation landed on an
                # archived entry that appears in no default listing and matches
                # no facet filter. Chains are capped at depth one, so one hop is
                # the whole resolution.
                opportunity_id = matched_id[1] or matched_id[0]
                if matched_id[1] is not None:
                    connection.execute(
                        "UPDATE medawarcre.internal_opportunities "
                        "SET status='active', updated_at=transaction_timestamp() "
                        "WHERE id=%s AND status='archived' "
                        "AND merged_into_opportunity_id IS NULL",
                        (opportunity_id,),
                    )
                opportunities.add(str(opportunity_id))

                connection.execute(
                    "INSERT INTO medawarcre.internal_opportunity_sources("
                    "workspace_id,opportunity_id,source,source_record_id,"
                    "access_class,score_version,provenance,origin,source_user_id,"
                    "source_deal_id,observed_property_identity,observed_market,"
                    "observed_property_type,score,stage,outcome,source_observed_at) "
                    "VALUES (%s,%s,%s,%s,'private',%s,%s::jsonb,'deal',%s,%s,%s::jsonb,%s,%s,"
                    "%s,%s,%s,statement_timestamp()) "
                    "ON CONFLICT (workspace_id, source, source_record_id) "
                    # Same monotonic clock as the entry above: this row carries
                    # the identical last >= first constraint, and the shared
                    # transaction_timestamp() is what makes the two agree.
                    "DO UPDATE SET last_observed_at=GREATEST("
                    "internal_opportunity_sources.first_observed_at,"
                    "internal_opportunity_sources.last_observed_at,"
                    "transaction_timestamp()),"
                    # Refreshed too. It recorded only the first read, so it
                    # duplicated first_observed_at and never said when the index
                    # last looked at this tenant record.
                    "source_observed_at=GREATEST("
                    "internal_opportunity_sources.source_observed_at,"
                    "transaction_timestamp()),"
                    "score=EXCLUDED.score,stage=EXCLUDED.stage,"
                    "outcome=EXCLUDED.outcome,"
                    # re-bind: a corrected address must move the
                    # observation to the property it now names.
                    "opportunity_id=EXCLUDED.opportunity_id,"
                    "observed_property_identity="
                    "EXCLUDED.observed_property_identity,"
                    "observed_market=EXCLUDED.observed_market,"
                    "observed_property_type=EXCLUDED.observed_property_type,"
                    # The same transaction clock as every other column here.
                    "updated_at=transaction_timestamp()",
                    (
                        workspace_id, opportunity_id, source, source_record_id,
                        score_version or "unversioned",
                        json.dumps({"kind": "deal", "deal_id": str(deal_id)}),
                        created_by, deal_id, json.dumps(dict(identity)),
                        _market(normalized), property_type,
                        score, stage, outcome,
                    ),
                )
                admitted += 1

            self._audit(
                connection, request,
                action="ingest", object_id=workspace_id,
                result="succeeded", workspace_id=workspace_id,
            )

        return IngestSummary(
            admitted=admitted,
            rejected=rejected,
            opportunities=len(opportunities),
            rejections=tuple(rejections),
        )

    # -- reads -------------------------------------------------------------

    def _load(
        self,
        connection: psycopg.Connection,
        opportunity_ids: list[str],
    ) -> dict[str, list[OpportunitySource]]:
        if not opportunity_ids:
            return {}
        rows = connection.execute(
            "SELECT s.opportunity_id, s.workspace_id, w.public_id, s.source_user_id,"
            " s.origin, s.source_deal_id, s.source_search_result_id,"
            " s.source_saved_search_id, s.source, s.source_record_id,"
            " s.access_class, s.score, s.score_version, s.stage, s.outcome,"
            " s.observed_property_identity, s.observed_market,"
            " s.observed_property_type, s.provenance, s.first_observed_at,"
            " s.last_observed_at "
            "FROM medawarcre.internal_opportunity_sources s "
            "JOIN medawarcre.workspaces w ON w.id = s.workspace_id "
            "WHERE s.opportunity_id = ANY(%s) "
            "ORDER BY s.opportunity_id, s.workspace_id",
            (opportunity_ids,),
        ).fetchall()
        grouped: dict[str, list[OpportunitySource]] = {}
        for row in rows:
            grouped.setdefault(str(row[0]), []).append(
                OpportunitySource(
                    workspace_id=str(row[1]), workspace_public_id=row[2],
                    source_user_id=str(row[3]), origin=row[4],
                    source_deal_id=str(row[5]) if row[5] else None,
                    source_search_result_id=str(row[6]) if row[6] else None,
                    source_saved_search_id=str(row[7]) if row[7] else None,
                    source=row[8], source_record_id=row[9], access_class=row[10],
                    score=float(row[11]) if row[11] is not None else None,
                    score_version=row[12], stage=row[13], outcome=row[14],
                    observed_property_identity=row[15] or {},
                    observed_market=row[16], observed_property_type=row[17],
                    provenance=row[18] or {},
                    first_observed_at=row[19], last_observed_at=row[20],
                )
            )
        return grouped

    @staticmethod
    def _conflicts(sources: list[OpportunitySource]) -> tuple[OpportunityConflict, ...]:
        """Describe disagreement between **workspaces**; never resolve it.

        The index states that the workspaces disagree and who holds which
        position. Picking a winner would erase the fact a human needs.

        Partitioned by workspace, not by source row. `deals` is unique on
        `(workspace_id, source, source_record_id)`, so one tenant saving one
        building from two providers is a designed-for path — and partitioning by
        row reported that tenant as disagreeing with *itself*, naming the same
        workspace and the same user on both sides of a "conflict", and blanking
        the entry's property type. A reviewer also showed the two-workspace
        case, where both tenants' current view agreed and the index still
        reported three cross-tenant conflicts.

        A tenant contradicting itself is a data-quality signal, and a real one,
        but it is not what this method is for and the index does not surface it
        today. That limit is stated in the contract rather than folded silently
        into the cross-tenant report.
        """
        conflicts: list[OpportunityConflict] = []

        def cross_workspace(positions: list[ConflictPosition]) -> bool:
            """Do two workspaces hold *different* views?

            Counting distinct values and distinct workspaces separately is not
            the same question, and answering the easier one was wrong: two
            tenants who each saved the building from the same two providers hold
            identical `{office, retail}` views, satisfy both counts, and were
            reported as three cross-tenant conflicts. Compare the value *sets*
            per workspace instead — identical sets are agreement, however many
            rows each side has.
            """
            by_workspace: dict[str, set[str]] = {}
            for position in positions:
                by_workspace.setdefault(position.workspace_id, set()).add(
                    position.value
                )
            return len({frozenset(values) for values in by_workspace.values()}) > 1

        for kind, getter in (
            ("outcome", lambda s: s.outcome),
            ("stage", lambda s: s.stage),
            # Two workspaces can legitimately call the same building different
            # things. That is a disagreement to report with both sides named,
            # not something for the entry's label to settle silently.
            ("property_type", lambda s: s.observed_property_type),
        ):
            positions = [
                ConflictPosition(s.workspace_id, s.source_user_id, str(getter(s)))
                for s in sources
                if getter(s) is not None
            ]
            if cross_workspace(positions):
                conflicts.append(OpportunityConflict(kind, tuple(positions)))

        scored = [s for s in sources if s.score is not None]
        if scored:
            # Compare each workspace's score *range* with each other's, the
            # numeric analogue of comparing value sets above.
            #
            # Two earlier attempts were both wrong. `max − min` over every row
            # let one tenant's own 10-vs-45 split supply the magnitude while a
            # second workspace merely had to exist. Taking the widest pair
            # *across* workspaces then reported two tenants who both hold
            # {41, 88} as disagreeing, by comparing one side's 41 with the
            # other's 88 — a pairing that is not a disagreement at all.
            #
            # Workspaces agree when their ranges coincide within tolerance.
            ranges: dict[str, tuple[float, float]] = {}
            for source in scored:
                low, high = ranges.get(
                    source.workspace_id, (source.score, source.score)
                )
                ranges[source.workspace_id] = (
                    min(low, source.score), max(high, source.score)
                )
            spread = max(
                (
                    max(abs(low - other_low), abs(high - other_high))
                    for low, high in ranges.values()
                    for other_low, other_high in ranges.values()
                ),
                default=0.0,
            )
            if spread > 20.0:
                conflicts.append(
                    OpportunityConflict(
                        "score",
                        tuple(
                            ConflictPosition(
                                s.workspace_id, s.source_user_id, f"{s.score:.4g}"
                            )
                            for s in scored
                        ),
                    )
                )
        return tuple(conflicts)

    def list_opportunities(
        self,
        request: StaffRequest,
        *,
        filters: OpportunityFilters | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> OpportunityPage:
        # The guard closes before the page is assembled, so the read's own
        # audit row cannot be joined by a second one. It used to span the whole
        # call: the success row commits with the transaction, and anything
        # raising during entry construction afterwards made the guard add a
        # `failed` row alongside it — two rows for one read, against a contract
        # that says exactly one. Both round-ten reviewers found it
        # independently, neither could trigger it with data, and
        # `get_opportunity` never had it because it already closed its guard
        # first. This is that shape.
        with self._audited_action(
            request, action="list", object_id="internal_opportunity_index"
        ):
            visible, rows, sources, limit = self._list_opportunities(
                request, filters=filters, limit=limit, cursor=cursor
            )
        return self._assemble_page(visible, rows, sources, limit)

    @staticmethod
    def _assemble_page(
        visible: list[Any], rows: list[Any],
        sources: dict[str, list[OpportunitySource]], limit: int,
    ) -> OpportunityPage:
        entries = tuple(
            OpportunityEntry(
                opportunity_id=str(row[0]), canonical_key=row[1], title=row[2],
                status=row[3], market=row[4],
                property_type=_derived_property_type(
                    sources.get(str(row[0]), ())
                ),
                property_identity=row[5] or {},
                merged_into_opportunity_id=str(row[6]) if row[6] else None,
                first_observed_at=row[7], last_observed_at=row[8],
                sources=tuple(sources.get(str(row[0]), ())),
                conflicts=InternalOpportunityIndex._conflicts(
                    list(sources.get(str(row[0]), ()))
                ),
            )
            for row in visible
        )
        next_cursor = (
            _encode_cursor(visible[-1][9], str(visible[-1][0]))
            if len(rows) > limit and visible
            else None
        )
        return OpportunityPage(entries=entries, next_cursor=next_cursor)

    def _list_opportunities(
        self,
        request: StaffRequest,
        *,
        filters: OpportunityFilters | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Any], list[Any], dict[str, list[OpportunitySource]], int]:
        # Argument validation lives inside the caller's guard, so a refused
        # read is recorded exactly as a refused mutation is. Round eight moved
        # the verdict and self-merge checks inside their guards for this reason
        # and left the read path's own checks above it: a reviewer measured 96
        # unrecorded refusals across 1,500 randomized staff steps, and it was
        # the only invariant that run violated.
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        if not 1 <= limit <= MAX_PAGE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE}")
        filters = filters or OpportunityFilters()

        where = ["(%s OR o.status = 'active')"]
        params: list[Any] = [filters.include_archived]
        if filters.market:
            where.append("lower(o.market) = lower(%s)")
            params.append(filters.market)
        source_predicates: list[str] = []
        source_params: list[Any] = []
        # property_type reads the per-workspace observation, like every other
        # facet except market. It used to filter the canonical row, which one
        # workspace wrote and no later observation refreshed — so on the one
        # structure built to combine tenants, a second workspace declaring the
        # same building industrial was invisible to a staff filter for
        # industrial. market stays on the canonical row because it is derived
        # from the normalized key every contributor agrees on by construction.
        for column, value in (
            ("s.observed_property_type", filters.property_type),
            ("s.stage", filters.stage),
            ("s.outcome", filters.outcome),
            ("s.source_user_id", filters.source_user_id),
            ("s.workspace_id", filters.workspace_id),
        ):
            if value is not None:
                source_predicates.append(f"{column} = %s")
                source_params.append(value)
        if filters.min_score is not None:
            source_predicates.append("s.score >= %s")
            source_params.append(filters.min_score)
        if filters.max_score is not None:
            source_predicates.append("s.score <= %s")
            source_params.append(filters.max_score)
        if source_predicates:
            where.append(
                "EXISTS (SELECT 1 FROM medawarcre.internal_opportunity_sources s "
                "WHERE s.opportunity_id = o.id AND "
                + " AND ".join(source_predicates) + ")"
            )
            params.extend(source_params)
        if cursor:
            observed, identifier = _decode_cursor(cursor)
            where.append("(o.created_at, o.id) < (%s, %s)")
            params.extend([observed, identifier])

        statement = (
            "SELECT o.id,o.canonical_key,o.title,o.status,o.market,"
            "o.property_identity,o.merged_into_opportunity_id,"
            "o.first_observed_at,o.last_observed_at,o.created_at "
            "FROM medawarcre.internal_opportunities o WHERE "
            + " AND ".join(where)
            + " ORDER BY o.created_at DESC, o.id DESC LIMIT %s"
        )
        params.append(min(limit, MAX_PAGE) + 1)

        with self._database.connection(self._context(request)) as connection:
            # The audit row carries a foreign key to workspaces, so filtering a
            # read by a workspace that does not exist used to raise
            # ForeignKeyViolation from the *audit insert* rather than return an
            # empty page — a crash where emptiness is the right answer, and an
            # existence oracle, since the exception distinguished a real
            # workspace from an absent one. Resolve it first and audit the read
            # without a workspace link when there is nothing to link to.
            audit_workspace = filters.workspace_id
            if audit_workspace is not None and connection.execute(
                "SELECT 1 FROM medawarcre.workspaces WHERE id=%s",
                (audit_workspace,),
            ).fetchone() is None:
                audit_workspace = None
            rows = connection.execute(statement, params).fetchall()
            visible = rows[:limit]
            sources = self._load(connection, [str(row[0]) for row in visible])
            self._audit(
                connection, request,
                action="list", object_id="internal_opportunity_index",
                result="succeeded",
                workspace_id=audit_workspace,
            )

        return visible, rows, sources, limit

    def get_opportunity(
        self, request: StaffRequest, opportunity_id: str
    ) -> OpportunityDetail:
        with self._audited_action(
            request, action="inspect", object_id=str(opportunity_id)
        ), self._database.connection(self._context(request)) as connection:
                row = connection.execute(
                    "SELECT id,canonical_key,title,status,market,"
                    "property_identity,merged_into_opportunity_id,"
                    "first_observed_at,last_observed_at "
                    "FROM medawarcre.internal_opportunities WHERE id=%s",
                    (opportunity_id,),
                ).fetchone()
                if row is None:
                    raise _Refused(
                        "inspect", str(opportunity_id),
                        LookupError("no such internal opportunity"),
                    )
                sources = self._load(
                    connection, [str(row[0])]
                ).get(str(row[0]), [])
                reviews = connection.execute(
                    "SELECT id,reviewer_user_id,reviewer_role,verdict,"
                    "reason_code,reason,note,occurred_at "
                    "FROM medawarcre.internal_opportunity_reviews "
                    "WHERE opportunity_id=%s ORDER BY occurred_at, id",
                    (opportunity_id,),
                ).fetchall()
                self._audit(
                    connection, request, action="inspect",
                    object_id=str(opportunity_id), result="succeeded",
                )

        entry = OpportunityEntry(
            opportunity_id=str(row[0]), canonical_key=row[1], title=row[2],
            status=row[3], market=row[4],
            property_type=_derived_property_type(sources),
            property_identity=row[5] or {},
            merged_into_opportunity_id=str(row[6]) if row[6] else None,
            first_observed_at=row[7], last_observed_at=row[8],
            sources=tuple(sources), conflicts=self._conflicts(list(sources)),
        )
        return OpportunityDetail(
            entry=entry,
            reviews=tuple(
                OpportunityReview(
                    id=str(item[0]), reviewer_user_id=str(item[1]),
                    reviewer_role=item[2], verdict=item[3], reason_code=item[4],
                    reason=item[5], note=item[6], occurred_at=item[7],
                )
                for item in reviews
            ),
        )

    # -- mutations ---------------------------------------------------------

    def record_review(
        self,
        request: StaffRequest,
        *,
        opportunity_id: str,
        verdict: str,
        note: str | None = None,
    ) -> str:
        self._require_mutation(
            request, action="review", object_id=str(opportunity_id)
        )
        with self._audited_action(
            request, action="review", object_id=str(opportunity_id)
        ):
            # Inside the guard. Validating above it meant an *analyst*
            # attempting this call was audited `denied` while an **owner**
            # supplying an invalid verdict was audited nowhere — the less
            # privileged attempt leaving a record and the more privileged one
            # leaving none.
            if verdict not in REVIEW_VERDICTS:
                raise ValueError(f"unsupported verdict: {verdict!r}")
            with self._database.connection(self._context(request)) as connection:
                if connection.execute(
                    "SELECT 1 FROM medawarcre.internal_opportunities WHERE id=%s",
                    (opportunity_id,),
                ).fetchone() is None:
                    # Otherwise the foreign key surfaces as a raw psycopg error.
                    raise _Refused(
                        "review", str(opportunity_id),
                        LookupError("no such internal opportunity"),
                    )
                review_id = connection.execute(
                    "INSERT INTO medawarcre.internal_opportunity_reviews("
                    "opportunity_id,reviewer_user_id,reviewer_role,verdict,"
                    "reason_code,reason,note) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                    "RETURNING id",
                    (
                        opportunity_id, request.actor_user_id, request.role,
                        verdict, request.reason_code, request.reason, note,
                    ),
                ).fetchone()[0]
                self._audit(
                    connection, request, action="review",
                    object_id=str(opportunity_id), result="succeeded",
                )
        return str(review_id)

    def merge_opportunities(
        self, request: StaffRequest, *, opportunity_id: str, into_opportunity_id: str
    ) -> None:
        """Link two entries as duplicates without collapsing either.

        The target must itself be canonical. A→B followed by B→A used to be
        accepted and removed both entries from every default listing
        permanently, because re-observation only lifts entries whose merge link
        is NULL and nothing ever cleared that link — a third, uninvolved
        workspace observing the same property was told ``admitted=1`` while its
        observation landed somewhere staff could not see. Migration 0009
        enforces the same rule with a trigger; this raises the readable error.
        """
        self._require_mutation(
            request, action="merge", object_id=str(opportunity_id)
        )
        with self._audited_action(
            request, action="merge", object_id=str(opportunity_id)
        ):
            # Inside the guard, for the same reason as the verdict check above.
            if opportunity_id == into_opportunity_id:
                raise ValueError("an opportunity cannot be merged into itself")
            with self._database.connection(self._context(request)) as connection:
                # Both rows, in id order, before either is inspected.
                #
                # Merge used to lock the target first and then update the
                # source. Ingest pre-locks in id order, so whenever
                # source.id < target.id the two walked the same pair in
                # opposite directions and two ordinary public calls deadlocked.
                # "A total order" is only total if every writer uses it.
                connection.execute(
                    "SELECT id FROM medawarcre.internal_opportunities "
                    "WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                    ([opportunity_id, into_opportunity_id],),
                ).fetchall()
                target = connection.execute(
                    "SELECT merged_into_opportunity_id "
                    "FROM medawarcre.internal_opportunities WHERE id=%s",
                    (into_opportunity_id,),
                ).fetchone()
                if target is None:
                    raise _Refused(
                        "merge", str(opportunity_id),
                        LookupError("no such internal opportunity: merge target"),
                    )
                if target[0] is not None:
                    raise _Refused(
                        "merge", str(opportunity_id),
                        ValueError(
                            "the merge target is itself merged; "
                            "merge into the canonical entry instead"
                        ),
                    )
                if connection.execute(
                    "SELECT 1 FROM medawarcre.internal_opportunities "
                    "WHERE merged_into_opportunity_id=%s",
                    (opportunity_id,),
                ).fetchone() is not None:
                    # Depth-one chains only. Without this, C->A then A->B
                    # answered "what is C a duplicate of?" with a row that was
                    # itself merged.
                    raise _Refused(
                        "merge", str(opportunity_id),
                        ValueError(
                            "this entry is itself a merge target; "
                            "merge its duplicates first"
                        ),
                    )
                merged = connection.execute(
                    "UPDATE medawarcre.internal_opportunities "
                    # 'suppressed' is preserved too. Merge kept only 'archived',
                    # and unmerge chose only between 'active' and 'archived', so
                    # a merge round-trip laundered a deliberately hidden entry
                    # back into the default staff listing.
                    "SET status=CASE WHEN status IN ('archived','suppressed') "
                    "THEN status ELSE 'merged' END,"
                    "merged_into_opportunity_id=%s,"
                    "updated_at=statement_timestamp() WHERE id=%s",
                    (into_opportunity_id, opportunity_id),
                )
                if merged.rowcount != 1:
                    raise _Refused(
                        "merge", str(opportunity_id),
                        LookupError("no such internal opportunity"),
                    )
                self._audit(
                    connection, request, action="merge",
                    object_id=str(opportunity_id), result="succeeded",
                )

    def unmerge_opportunity(
        self, request: StaffRequest, *, opportunity_id: str
    ) -> None:
        """Undo a merge link, so a wrong duplicate call is recoverable.

        Merge was otherwise a one-way door — the same defect shape the archival
        repair had. Without this, an entry that was merged and then lost its
        last observation stayed out of the default listing even when a new
        workspace genuinely acquired the property, because the re-observation
        lift refuses linked entries and nothing could clear the link.

        The entry returns to ``active`` if it still has a contributing
        observation and to ``archived`` if it does not, which is the same rule
        the archival trigger applies.
        """
        self._require_mutation(
            request, action="unmerge", object_id=str(opportunity_id)
        )
        with self._audited_action(
            request, action="unmerge", object_id=str(opportunity_id)
        ):
            with self._database.connection(self._context(request)) as connection:
                unmerged = connection.execute(
                    "UPDATE medawarcre.internal_opportunities o "
                    "SET merged_into_opportunity_id=NULL,"
                    "status=CASE WHEN o.status='suppressed' THEN 'suppressed' "
                    "WHEN EXISTS ("
                    "  SELECT 1 FROM medawarcre.internal_opportunity_sources s "
                    "  WHERE s.opportunity_id = o.id) THEN 'active' "
                    "ELSE 'archived' END,"
                    "updated_at=statement_timestamp() "
                    "WHERE o.id=%s AND o.merged_into_opportunity_id IS NOT NULL",
                    (opportunity_id,),
                )
                if unmerged.rowcount != 1:
                    raise _Refused(
                        "unmerge", str(opportunity_id),
                        LookupError("no such merged internal opportunity"),
                    )
                self._audit(
                    connection, request, action="unmerge",
                    object_id=str(opportunity_id), result="succeeded",
                )


def _encode_cursor(observed: datetime, identifier: str) -> str:
    return f"{observed.isoformat()}|{identifier}"


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        observed, identifier = cursor.split("|", 1)
        return datetime.fromisoformat(observed), str(UUID(identifier))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("invalid pagination cursor") from error


__all__ = [
    "ConflictPosition",
    "IngestSummary",
    "InternalIndexUnavailable",
    "InternalOpportunityIndex",
    "OpportunityConflict",
    "OpportunityDetail",
    "OpportunityEntry",
    "OpportunityFilters",
    "OpportunityPage",
    "OpportunityReview",
    "OpportunitySource",
    "MAX_PAGE",
    "MAX_PROPERTY_TYPE",
    "REASON_CODES",
    "REVIEW_VERDICTS",
    "StaffRequest",
    "canonical_property_key",
]
