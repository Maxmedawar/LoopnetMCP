"""Evidence-fit ranking for the next human to call.

The result is a transparent framing, never an instruction.  It ranks only names
already present in permissioned execution records and shows the convention behind
every point; it does not discover or enrich contacts from public databases.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DealStore
from cre_mcp.fund.engagement import engagement_report
from cre_mcp.ledger.store import LedgerStore
from cre_mcp.negotiation.commitments import CommitmentStore

from .dossier import (
    ANECDOTE_NOTE,
    _as_utc,
    _contains_name,
    _deal_history,
    _event_pairs,
    _parse_time,
    _required_text,
    _roles_from_event,
    _source_stores,
)


_NEED_ROLES = {
    "debt": frozenset({"lender", "mlo", "broker_dealer"}),
    "equity": frozenset({"investor", "adviser", "equity"}),
    "listing": frozenset({"broker", "seller", "real_estate"}),
    "tenant": frozenset({"tenant"}),
    "counsel": frozenset({"counsel", "attorney"}),
    "contractor": frozenset({"contractor", "vendor"}),
}


def _candidate_key(name: str) -> str:
    return " ".join(name.casefold().split())


def _candidate(
    candidates: dict[str, dict[str, Any]], name: Any
) -> dict[str, Any] | None:
    normalized = str(name).strip() if name is not None else ""
    if not normalized:
        return None
    key = _candidate_key(normalized)
    if key not in candidates:
        candidates[key] = {
            "name": normalized,
            "roles": set(),
            "claims": [],
            "quotes": [],
            "events": [],
            "investor_records": [],
            "engagement": None,
            "linked_deals": set(),
            "commitments": [],
            "source_counts": Counter(),
        }
    return candidates[key]


def _touch_count(candidate: Mapping[str, Any]) -> tuple[int, int, int]:
    event_touches = len(candidate["events"])
    ir_touches = 0
    engagement = candidate.get("engagement")
    if isinstance(engagement, Mapping):
        frequency = engagement.get("frequency")
        all_time = frequency.get("all_time") if isinstance(frequency, Mapping) else None
        if isinstance(all_time, Mapping) and isinstance(all_time.get("value"), int):
            ir_touches = int(all_time["value"])
    return event_touches + ir_touches, event_touches, ir_touches


def _last_recorded(candidate: Mapping[str, Any]) -> datetime | None:
    timestamps: list[datetime] = []
    for event in candidate["events"]:
        parsed = _parse_time(event.get("event_ts") or event.get("created_at"))
        if parsed is not None:
            timestamps.append(parsed)
    engagement = candidate.get("engagement")
    if isinstance(engagement, Mapping):
        parsed = _parse_time(engagement.get("last_touch_at"))
        if parsed is not None:
            timestamps.append(parsed)
    for commitment in candidate["commitments"]:
        parsed = _parse_time(commitment.get("made_at"))
        if parsed is not None:
            timestamps.append(parsed)
    for claim in candidate["claims"]:
        parsed = _parse_time(claim.recorded_at)
        if parsed is not None:
            timestamps.append(parsed)
    for quote in candidate["quotes"]:
        parsed = _parse_time(quote.quoted_at)
        if parsed is not None:
            timestamps.append(parsed)
    return max(timestamps) if timestamps else None


def _context_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, Mapping):
        for nested in value.values():
            values.extend(_context_values(nested))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            values.extend(_context_values(nested))
    elif value not in (None, "") and not isinstance(value, bool):
        normalized = str(value).strip().casefold()
        if len(normalized) >= 2:
            values.append(normalized)
    return values


def _context_matches(
    candidate: Mapping[str, Any],
    deal_context: Mapping[str, Any],
    deal_summaries: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    values = _context_values(deal_context)
    if not values:
        return []
    haystacks: list[str] = []
    for event in candidate["events"]:
        haystacks.append(str(event).casefold())
    for deal_id in candidate["linked_deals"]:
        summary = deal_summaries.get(str(deal_id))
        if summary is not None:
            haystacks.append(str(dict(summary)).casefold())
    return sorted({value for value in values if any(value in text for text in haystacks)})


def _relationship_label(touches: int) -> str:
    if touches == 0:
        return "no recorded touch history"
    if touches == 1:
        return "one recorded touch"
    if touches <= 4:
        return "some recorded touch history"
    return "repeated recorded touch history"


def _outcome_points(candidate: Mapping[str, Any]) -> tuple[int, dict[str, int]]:
    claims = candidate["claims"]
    quotes = candidate["quotes"]
    commitments = candidate["commitments"]
    corroborated = sum(claim.verdict == "corroborated" for claim in claims)
    overridden = sum(claim.verdict == "overridden" for claim in claims)
    closed = sum(quote.stage == "closed" for quote in quotes)
    died = sum(quote.stage == "died" for quote in quotes)
    adverse_retrades = sum(
        (quote.retrade_rate_bps is not None and quote.retrade_rate_bps > 0)
        or (
            quote.retrade_proceeds_pct is not None
            and quote.retrade_proceeds_pct < 0
        )
        for quote in quotes
    )
    kept = sum(
        item.get("made_by") == "them" and item.get("status") == "kept"
        for item in commitments
    )
    broken = sum(
        item.get("made_by") == "them" and item.get("status") == "broken"
        for item in commitments
    )
    points = (
        min(corroborated, 5) * 2
        - min(overridden, 5) * 3
        + min(closed, 2) * 8
        - min(died, 3) * 5
        - min(adverse_retrades, 3) * 3
        + min(kept, 3) * 4
        - min(broken, 3) * 6
    )
    return points, {
        "claims_corroborated": corroborated,
        "claims_overridden": overridden,
        "quotes_closed": closed,
        "quotes_died": died,
        "adverse_retrades": adverse_retrades,
        "commitments_kept_by_them": kept,
        "commitments_broken_by_them": broken,
    }


async def _recorded_candidates(
    *,
    db_path: str | Path | CreConfig | None,
    config: CreConfig | None,
    ledger_store: LedgerStore | None,
    deal_store: DealStore | None,
    as_of: datetime,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], Path]:
    path, ledger, deals = _source_stores(
        db_path, config, ledger_store, deal_store
    )
    candidates: dict[str, dict[str, Any]] = {}
    claims = await ledger.claims_for()
    for claim in claims:
        item = _candidate(candidates, claim.counterparty)
        if item is None:
            continue
        item["claims"].append(claim)
        item["linked_deals"].add(claim.deal_id)
        item["source_counts"]["claim_ledger"] += 1
        if claim.counterparty_role != "unknown":
            item["roles"].add(str(claim.counterparty_role))

    quotes = await ledger.quotes_for()
    for quote in quotes:
        item = _candidate(candidates, quote.lender)
        if item is None:
            continue
        item["quotes"].append(quote)
        item["linked_deals"].add(quote.deal_id)
        item["source_counts"]["quote_ledger"] += 1
        item["roles"].add("lender")

    deal_summaries, all_events = await _deal_history(deals)
    for event in all_events:
        for person, role in _event_pairs(event):
            item = _candidate(candidates, person)
            if item is None:
                continue
            item["linked_deals"].add(str(event["deal_id"]))
            if role != "unknown":
                item["roles"].add(role)
    for item in candidates.values():
        matching_events = [
            event for event in all_events if _contains_name(event, item["name"])
        ]
        item["events"].extend(matching_events)
        item["source_counts"]["deal_events"] += len(matching_events)
        item["linked_deals"].update(
            str(event["deal_id"]) for event in matching_events
        )
        for event in matching_events:
            item["roles"].update(_roles_from_event(event, item["name"]))

    investors = await deals.list_investors()
    for investor in investors:
        if not isinstance(investor, Mapping):
            continue
        item = _candidate(candidates, investor.get("name"))
        if item is None:
            continue
        item["roles"].add("investor")
        item["investor_records"].append(dict(investor))
        item["source_counts"]["investor_crm"] += 1
        raw_commitments = investor.get("commitments", [])
        if isinstance(raw_commitments, list):
            item["linked_deals"].update(
                str(commitment["deal_id"])
                for commitment in raw_commitments
                if isinstance(commitment, Mapping)
                and commitment.get("deal_id") not in (None, "")
            )

    try:
        ir_report = engagement_report(None, as_of=as_of, db_path=path)
    except Exception:
        ir_report = {"investors": []}
    raw_ir_investors = ir_report.get("investors", [])
    if isinstance(raw_ir_investors, list):
        for raw_investor in raw_ir_investors:
            if not isinstance(raw_investor, Mapping):
                continue
            item = _candidate(candidates, raw_investor.get("investor"))
            if item is None:
                continue
            item["roles"].add("investor")
            item["engagement"] = dict(raw_investor)
            evidence = raw_investor.get("evidence", [])
            item["source_counts"]["ir_touches"] += (
                len(evidence) if isinstance(evidence, list) else 0
            )

    commitment_store = CommitmentStore(path)
    for item in candidates.values():
        for deal_id in sorted(item["linked_deals"]):
            rows = commitment_store.list_commitments(str(deal_id))
            for row in rows:
                commitment = dict(row)
                commitment["deal_id"] = str(deal_id)
                item["commitments"].append(commitment)
        item["source_counts"]["neg_commitments"] += len(item["commitments"])
    return candidates, deal_summaries, path


async def who_to_call(
    need: Mapping[str, Any],
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
    ledger_store: LedgerStore | None = None,
    deal_store: DealStore | None = None,
    as_of: Any = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Rank recorded, role-matched humans/firms for a stated execution need."""

    if not isinstance(need, Mapping):
        raise TypeError("need must be an object with type and deal_context")
    need_type = _required_text(need.get("type"), "need.type").casefold()
    if need_type not in _NEED_ROLES:
        allowed = ", ".join(sorted(_NEED_ROLES))
        raise ValueError(f"need.type must be one of: {allowed}")
    raw_context = need.get("deal_context", {})
    if raw_context is None:
        raw_context = {}
    if not isinstance(raw_context, Mapping):
        raise TypeError("need.deal_context must be an object")
    deal_context = dict(raw_context)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError("limit must be an integer between 1 and 100")
    report_as_of = _as_utc(as_of)

    candidates, deal_summaries, _ = await _recorded_candidates(
        db_path=db_path,
        config=config,
        ledger_store=ledger_store,
        deal_store=deal_store,
        as_of=report_as_of,
    )
    expected_roles = _NEED_ROLES[need_type]
    ranked: list[dict[str, Any]] = []
    for candidate in candidates.values():
        roles = {str(role).casefold() for role in candidate["roles"]}
        role_matches = sorted(roles & expected_roles)
        if not role_matches:
            continue

        role_points = 50
        outcome_points, outcome_counts = _outcome_points(candidate)
        touches, event_touches, ir_touches = _touch_count(candidate)
        relationship_points = min(touches, 10) * 2
        last_recorded = _last_recorded(candidate)
        recency_days = None
        recency_points = 0
        if last_recorded is not None:
            recency_days = max((report_as_of - last_recorded).days, 0)
            if recency_days <= 30:
                recency_points = 20
            elif recency_days <= 90:
                recency_points = 15
            elif recency_days <= 365:
                recency_points = 10
            else:
                recency_points = 5
        context_matches = _context_matches(candidate, deal_context, deal_summaries)
        context_points = 10 if context_matches else 0
        score = (
            role_points
            + outcome_points
            + relationship_points
            + recency_points
            + context_points
        )
        tested_claims = (
            outcome_counts["claims_corroborated"]
            + outcome_counts["claims_overridden"]
        )
        resolved_quotes = (
            outcome_counts["quotes_closed"] + outcome_counts["quotes_died"]
        )
        resolved_commitments = (
            outcome_counts["commitments_kept_by_them"]
            + outcome_counts["commitments_broken_by_them"]
        )
        reasons = [
            f"Role fit: recorded as {', '.join(role_matches)} for a {need_type} need (+{role_points}).",
            (
                "Track record: "
                f"{tested_claims} tested claim(s), {resolved_quotes} resolved quote(s), "
                f"and {resolved_commitments} resolved deal-linked commitment(s) "
                f"({outcome_points:+d} points); sample sizes remain visible."
            ),
            (
                f"Recency: latest recorded interaction/evidence was {recency_days} day(s) "
                f"before as_of (+{recency_points})."
                if recency_days is not None
                else "Recency: no dated recorded evidence (+0)."
            ),
            (
                f"Relationship strength convention: {touches} recorded touch(es) "
                f"({event_touches} deal event(s), {ir_touches} governed IR touch(es)); "
                f"{_relationship_label(touches)} (+{relationship_points})."
            ),
        ]
        if deal_context:
            if context_matches:
                reasons.append(
                    "Deal-context fit: recorded history matched "
                    f"{', '.join(context_matches)} (+{context_points})."
                )
            else:
                reasons.append("Deal-context fit: no recorded context match (+0).")
        ranked.append(
            {
                "name": candidate["name"],
                "score": score,
                "roles_seen": sorted(roles),
                "reasons": reasons,
                "last_interaction": (
                    last_recorded.isoformat() if last_recorded is not None else None
                ),
                "relationship_strength": {
                    "label": _relationship_label(touches),
                    "touch_count": touches,
                    "deal_event_touches": event_touches,
                    "governed_ir_touches": ir_touches,
                },
                "evidence": {
                    "outcomes": outcome_counts,
                    "claim_sample_size": len(candidate["claims"]),
                    "quote_sample_size": len(candidate["quotes"]),
                    "commitment_sample_size": len(candidate["commitments"]),
                    "deal_event_sample_size": event_touches,
                    "ir_touch_sample_size": ir_touches,
                    "source_sample_sizes": dict(sorted(candidate["source_counts"].items())),
                    "linked_deal_ids": sorted(candidate["linked_deals"]),
                    "context_matches": context_matches,
                },
                "score_components": {
                    "role_fit": role_points,
                    "recorded_outcomes": outcome_points,
                    "recency": recency_points,
                    "relationship_touch_frequency": relationship_points,
                    "deal_context": context_points,
                },
            }
        )

    ranked.sort(
        key=lambda item: (
            -item["score"],
            item["last_interaction"] is None,
            -( _parse_time(item["last_interaction"]).timestamp() if item["last_interaction"] else 0),
            item["name"].casefold(),
        )
    )
    for index, candidate in enumerate(ranked[:limit], start=1):
        candidate["rank"] = index
    selected = ranked[:limit]
    status = "ranked_recorded_candidates" if selected else "no_recorded_candidates"
    return {
        "need": {"type": need_type, "deal_context": deal_context},
        "status": status,
        "candidates": selected,
        "message": (
            "No recorded candidates matched this need."
            if not selected
            else f"Ranked {len(selected)} recorded candidate(s) by the disclosed convention."
        ),
        "as_of": report_as_of.isoformat(),
        "framing": (
            "This is a ranked framing with reasons, never an instruction or recommendation "
            "to contact, retain, lend to, solicit, or transact with anyone. Confirm current "
            "fit, authority, conflicts, licensing, consent, and contact permissions."
        ),
        "methodology": {
            "role_fit_points": 50,
            "recency_points": {"0_30_days": 20, "31_90": 15, "91_365": 10, "older": 5},
            "relationship_points": "2 per named deal-event or governed IR touch, capped at 20",
            "context_points": "10 for any caller-supplied deal-context value found in linked records",
            "outcome_points": (
                "+2 corroborated claim (cap 5), -3 overridden claim (cap 5), +8 close "
                "(cap 2), -5 died quote (cap 3), -3 adverse retrade (cap 3), +4 kept "
                "commitment by them (cap 3), -6 broken commitment by them (cap 3)"
            ),
            "calibrated": False,
        },
        "honesty": ANECDOTE_NOTE,
    }


__all__ = ["who_to_call"]
