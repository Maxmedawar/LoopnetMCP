"""Permissioned, evidence-first counterparty dossiers.

This module is deliberately an aggregator.  It reads the recording ledgers and
execution stores but owns no counterparty database and derives no hidden score.
Every source reports its own observed sample size so a few anecdotes cannot be
mistaken for a calibrated signal.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DealStore
from cre_mcp.fund.engagement import engagement_report
from cre_mcp.ledger.report import MIN_SAMPLE
from cre_mcp.ledger.store import LedgerStore
from cre_mcp.negotiation.commitments import CommitmentStore


ANECDOTE_NOTE = (
    "Recorded history is descriptive evidence, not a calibrated score or a claim "
    "about unobserved conduct. Small samples are anecdote, not signal."
)

_EVENT_NAME_KEYS = frozenset(
    {
        "counterparty",
        "counterparty_name",
        "name",
        "contact",
        "contact_name",
        "party",
        "broker",
        "seller",
        "lender",
        "investor",
        "tenant",
        "counsel",
        "attorney",
        "contractor",
        "vendor",
        "appraiser",
        "mlo",
    }
)
_DIRECT_ROLE_KEYS = frozenset(
    {
        "broker",
        "seller",
        "lender",
        "investor",
        "tenant",
        "counsel",
        "attorney",
        "contractor",
        "vendor",
        "appraiser",
        "mlo",
    }
)
_EVENT_ROLE_WORDS = (
    "broker",
    "seller",
    "lender",
    "investor",
    "tenant",
    "counsel",
    "attorney",
    "contractor",
    "appraiser",
    "mlo",
)


def _required_text(value: Any, label: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError(f"{label} cannot be blank")
    return normalized


def _as_utc(value: Any = None, *, label: str = "as_of") -> datetime:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        text = _required_text(value, label)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(
                    date.fromisoformat(text), datetime.min.time(), tzinfo=UTC
                )
            except ValueError as exc:
                raise ValueError(f"{label} must be an ISO date or datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return _as_utc(value, label="recorded timestamp")
    except (TypeError, ValueError):
        return None


def _sample_warning(sample_size: int, subject: str) -> str | None:
    if sample_size >= MIN_SAMPLE:
        return None
    return (
        f"only {sample_size} {subject} — this is anecdote, not signal "
        f"(need >= {MIN_SAMPLE})"
    )


def _name_pattern(name: str) -> re.Pattern[str]:
    escaped = re.escape(" ".join(name.casefold().split()))
    return re.compile(rf"(?<!\w){escaped}(?!\w)")


def _contains_name(value: Any, name: str) -> bool:
    pattern = _name_pattern(name)

    def search(item: Any) -> bool:
        if isinstance(item, Mapping):
            return any(search(key) or search(nested) for key, nested in item.items())
        if isinstance(item, (list, tuple, set, frozenset)):
            return any(search(nested) for nested in item)
        if item is None:
            return False
        normalized = " ".join(str(item).casefold().split())
        return bool(pattern.search(normalized))

    return search(value)


def _same_name(left: Any, right: str) -> bool:
    if left is None:
        return False
    return " ".join(str(left).casefold().split()) == " ".join(right.casefold().split())


def _resolve_path(
    db_path: str | Path | CreConfig | None,
    config: CreConfig | None,
    ledger_store: LedgerStore | None,
    deal_store: DealStore | None,
) -> Path:
    if isinstance(db_path, CreConfig):
        return Path(db_path.cache_db_path).expanduser()
    if db_path is not None:
        return Path(db_path).expanduser()
    if config is not None:
        return Path(config.cache_db_path).expanduser()
    if ledger_store is not None:
        return Path(ledger_store.db_path).expanduser()
    if deal_store is not None:
        return Path(deal_store.db_path).expanduser()
    return Path(CreConfig().cache_db_path).expanduser()


def _source_stores(
    db_path: str | Path | CreConfig | None,
    config: CreConfig | None,
    ledger_store: LedgerStore | None,
    deal_store: DealStore | None,
) -> tuple[Path, LedgerStore, DealStore]:
    path = _resolve_path(db_path, config, ledger_store, deal_store)
    return path, ledger_store or LedgerStore(path), deal_store or DealStore(path)


def _event_pairs(event: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Extract only explicitly labeled person/firm fields from an event payload."""

    detail = event.get("detail")
    if not isinstance(detail, Mapping):
        return []
    pairs: list[tuple[str, str]] = []
    explicit_role = detail.get("counterparty_role", detail.get("role"))
    normalized_role = (
        str(explicit_role).strip().casefold().replace(" ", "_")
        if explicit_role not in (None, "")
        else "unknown"
    )
    for raw_key, raw_value in detail.items():
        key = str(raw_key).strip().casefold()
        if key not in _EVENT_NAME_KEYS or raw_value in (None, ""):
            continue
        role = key if key in _DIRECT_ROLE_KEYS else normalized_role
        if role == "attorney":
            role = "counsel"
        if role == "vendor":
            role = "contractor"
        if isinstance(raw_value, str):
            pairs.append((raw_value.strip(), role))
        elif isinstance(raw_value, Mapping):
            nested_name = raw_value.get("name")
            if nested_name not in (None, ""):
                nested_role = raw_value.get("role", role)
                pairs.append(
                    (
                        str(nested_name).strip(),
                        str(nested_role).strip().casefold().replace(" ", "_"),
                    )
                )
    return [(person, role) for person, role in pairs if person]


def _roles_from_event(event: Mapping[str, Any], name: str) -> set[str]:
    roles = {role for person, role in _event_pairs(event) if _same_name(person, name)}
    if _contains_name(event, name):
        event_type = str(event.get("event_type", "")).casefold()
        roles.update(role for role in _EVENT_ROLE_WORDS if role in event_type)
    roles.discard("unknown")
    return roles


def _roles_from_license(screen: Mapping[str, Any] | None) -> set[str]:
    if not screen:
        return set()
    mapping = {
        "brokercheck": "broker_dealer",
        "iapd": "adviser",
        "real_estate": "broker",
        "trec": "broker",
        "contractor": "contractor",
        "tdlr": "contractor",
        "appraiser": "appraiser",
        "asc": "appraiser",
        "nmls": "mlo",
    }
    roles: set[str] = set()
    sources = screen.get("sources")
    if isinstance(sources, Mapping):
        for source_name, raw_result in sources.items():
            if not isinstance(raw_result, Mapping) or not raw_result.get("candidates"):
                continue
            lowered = str(source_name).casefold()
            roles.update(role for token, role in mapping.items() if token in lowered)
    matches = screen.get("matches")
    if isinstance(matches, list):
        for match in matches:
            if not isinstance(match, Mapping):
                continue
            raw_role = match.get("role", match.get("type"))
            if raw_role not in (None, ""):
                roles.add(str(raw_role).strip().casefold().replace(" ", "_"))
    return roles


def _license_evidence(screen: Mapping[str, Any] | None) -> dict[str, Any]:
    if screen is None:
        return {
            "sample_size": 0,
            "status": "not_provided",
            "candidate_matches": [],
            "disciplinary_flags": [],
            "note": (
                "No cached or caller-supplied verifyreg output was provided; no live "
                "registry lookup was attempted."
            ),
        }
    sources = screen.get("sources")
    candidates: list[dict[str, Any]] = []
    if isinstance(sources, Mapping):
        for source_name, raw_result in sources.items():
            if not isinstance(raw_result, Mapping):
                continue
            raw_candidates = raw_result.get("candidates")
            if not isinstance(raw_candidates, list):
                continue
            for raw_candidate in raw_candidates:
                if isinstance(raw_candidate, Mapping):
                    candidates.append(
                        {"source": str(source_name), "candidate": dict(raw_candidate)}
                    )
    direct_matches = screen.get("matches")
    if isinstance(direct_matches, list):
        for raw_match in direct_matches:
            if isinstance(raw_match, Mapping):
                candidates.append(
                    {"source": "passed_screen", "candidate": dict(raw_match)}
                )
            else:
                candidates.append(
                    {"source": "passed_screen", "candidate": raw_match}
                )
    discipline = screen.get("disciplinary_summary")
    flags = discipline.get("flags", []) if isinstance(discipline, Mapping) else []
    return {
        "sample_size": len(candidates),
        "status": screen.get("status", "caller_supplied"),
        "candidate_matches": candidates,
        "matches": list(direct_matches) if isinstance(direct_matches, list) else [],
        "disciplinary_flags": list(flags) if isinstance(flags, list) else [],
        "identity_caveat": screen.get("identity_caveat"),
        "no_match_caveat": screen.get("no_match_caveat"),
        "details": screen.get("details"),
        "raw_screen": dict(screen),
        "note": (
            "Registry rows are candidate matches, not identity proof; compare legal "
            "name, license/CRD, firm, and location before relying on them."
        ),
    }


async def _deal_history(
    deal_store: DealStore,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    deals = await deal_store.list_deals()
    summaries = {
        str(deal["deal_id"]): deal
        for deal in deals
        if isinstance(deal, Mapping) and deal.get("deal_id") not in (None, "")
    }
    events: list[dict[str, Any]] = []
    for deal_id in summaries:
        timeline = await deal_store.get_deal_timeline(deal_id)
        raw_events = timeline.get("events", []) if isinstance(timeline, Mapping) else []
        if not isinstance(raw_events, list):
            continue
        for raw_event in raw_events:
            if not isinstance(raw_event, Mapping):
                continue
            event = dict(raw_event)
            event["deal_id"] = deal_id
            events.append(event)
    return summaries, events


def _claim_track(claims: list[Any], name: str) -> dict[str, Any]:
    corroborated = [claim for claim in claims if claim.verdict == "corroborated"]
    overridden = [claim for claim in claims if claim.verdict == "overridden"]
    tested = len(corroborated) + len(overridden)
    deltas = [
        claim.delta_pct
        for claim in overridden
        if claim.delta_pct is not None
    ]
    field_counts: Counter[str] = Counter(claim.field for claim in overridden)
    field_deltas: dict[str, list[float]] = defaultdict(list)
    for claim in overridden:
        if claim.delta_pct is not None:
            field_deltas[claim.field].append(float(claim.delta_pct))
    worst_fields = []
    for field, count in field_counts.most_common(5):
        values = field_deltas[field]
        worst_fields.append(
            {
                "field": field,
                "overridden": count,
                "mean_delta_pct": round(sum(values) / len(values), 4) if values else None,
            }
        )
    return {
        "counterparty": name,
        "sample_size": len(claims),
        "tested_sample_size": tested,
        "deals": len({claim.deal_id for claim in claims}),
        "claims_total": len(claims),
        "claims_corroborated": len(corroborated),
        "claims_overridden": len(overridden),
        "accuracy_rate": round(len(corroborated) / tested, 4) if tested else None,
        "mean_overstatement_pct": round(sum(deltas) / len(deltas), 4) if deltas else None,
        "worst_fields": worst_fields,
        "sample_warning": _sample_warning(tested, "tested claims"),
    }


def _quote_track(quotes: list[Any], name: str) -> dict[str, Any]:
    closed = [quote for quote in quotes if quote.stage == "closed"]
    died = [quote for quote in quotes if quote.stage == "died"]
    resolved = len(closed) + len(died)
    rate_retrades = [
        quote.retrade_rate_bps
        for quote in closed
        if quote.retrade_rate_bps is not None
    ]
    proceeds_retrades = [
        quote.retrade_proceeds_pct
        for quote in closed
        if quote.retrade_proceeds_pct is not None
    ]
    days = [
        quote.days_quote_to_close
        for quote in closed
        if quote.days_quote_to_close is not None
    ]
    return {
        "lender": name,
        "sample_size": len(quotes),
        "resolved_sample_size": resolved,
        "quotes_total": len(quotes),
        "closed": len(closed),
        "died": len(died),
        "open": len(quotes) - resolved,
        "close_rate": round(len(closed) / resolved, 4) if resolved else None,
        "mean_retrade_rate_bps": (
            round(sum(rate_retrades) / len(rate_retrades), 1)
            if rate_retrades
            else None
        ),
        "mean_retrade_proceeds_pct": (
            round(sum(proceeds_retrades) / len(proceeds_retrades), 4)
            if proceeds_retrades
            else None
        ),
        "mean_days_quote_to_close": round(sum(days) / len(days)) if days else None,
        "sample_warning": _sample_warning(resolved, "resolved quotes"),
        "honesty": "raw history, UNCALIBRATED — no execution score is inferred",
    }


def _commitment_evidence(commitments: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(str(item.get("status", "unknown")) for item in commitments)
    by_made_by = Counter(str(item.get("made_by", "unknown")) for item in commitments)
    return {
        "sample_size": len(commitments),
        "status_counts": dict(sorted(statuses.items())),
        "open": statuses.get("open", 0),
        "kept": statuses.get("kept", 0),
        "broken": statuses.get("broken", 0),
        "superseded": statuses.get("superseded", 0),
        "made_by_counts": dict(sorted(by_made_by.items())),
        "kept_by_them": sum(
            item.get("made_by") == "them" and item.get("status") == "kept"
            for item in commitments
        ),
        "broken_by_them": sum(
            item.get("made_by") == "them" and item.get("status") == "broken"
            for item in commitments
        ),
        "records": commitments,
        "sample_warning": _sample_warning(len(commitments), "deal-linked commitments"),
        "attribution_note": (
            "neg_commitments records parties only as us/them. 'Them' is associated "
            "with this dossier only on independently linked deals and is not named-party proof."
        ),
    }


async def _collect_evidence(
    name: str,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
    ledger_store: LedgerStore | None = None,
    deal_store: DealStore | None = None,
    license_screen: Mapping[str, Any] | None = None,
    as_of: Any = None,
) -> dict[str, Any]:
    normalized_name = _required_text(name, "name")
    report_as_of = _as_utc(as_of)
    path, ledger, deals = _source_stores(
        db_path, config, ledger_store, deal_store
    )

    all_claims = await ledger.claims_for()
    claims = [
        claim for claim in all_claims if _same_name(claim.counterparty, normalized_name)
    ]
    all_quotes = await ledger.quotes_for()
    quotes = [quote for quote in all_quotes if _same_name(quote.lender, normalized_name)]
    all_defects = await ledger.defects_for()
    defects = [
        defect
        for defect in all_defects
        if _same_name(defect.discovered_by, normalized_name)
        or _contains_name(
            {
                "description": defect.description,
                "outcome_notes": defect.outcome_notes,
            },
            normalized_name,
        )
    ]

    deal_summaries, all_events = await _deal_history(deals)
    matching_events = [
        event for event in all_events if _contains_name(event, normalized_name)
    ]
    linked_deal_ids = {
        claim.deal_id for claim in claims
    } | {quote.deal_id for quote in quotes} | {defect.deal_id for defect in defects} | {
        str(event["deal_id"]) for event in matching_events
    }

    investors = await deals.list_investors()
    matching_investors = [
        investor
        for investor in investors
        if isinstance(investor, Mapping) and _same_name(investor.get("name"), normalized_name)
    ]
    for investor in matching_investors:
        raw_commitments = investor.get("commitments", [])
        if isinstance(raw_commitments, list):
            linked_deal_ids.update(
                str(item["deal_id"])
                for item in raw_commitments
                if isinstance(item, Mapping) and item.get("deal_id") not in (None, "")
            )

    commitments: list[dict[str, Any]] = []
    commitment_store = CommitmentStore(path)
    for deal_id in sorted(linked_deal_ids):
        for raw_commitment in commitment_store.list_commitments(deal_id):
            commitment = dict(raw_commitment)
            commitment["deal_id"] = deal_id
            commitments.append(commitment)

    engagement: dict[str, Any] | None = None
    engagement_error: str | None = None
    try:
        report = engagement_report(
            normalized_name,
            as_of=report_as_of,
            db_path=path,
        )
        raw_investors = report.get("investors", [])
        if isinstance(raw_investors, list) and raw_investors:
            first = raw_investors[0]
            if isinstance(first, Mapping):
                engagement = dict(first)
    except Exception as exc:
        engagement_error = str(exc)

    roles = {
        str(claim.counterparty_role)
        for claim in claims
        if str(claim.counterparty_role) != "unknown"
    }
    if quotes:
        roles.add("lender")
    if matching_investors or engagement is not None:
        roles.add("investor")
    for event in matching_events:
        roles.update(_roles_from_event(event, normalized_name))
    roles.update(_roles_from_license(license_screen))

    return {
        "name": normalized_name,
        "as_of": report_as_of,
        "path": path,
        "claims": claims,
        "quotes": quotes,
        "defects": defects,
        "events": matching_events,
        "all_events": all_events,
        "deal_summaries": deal_summaries,
        "linked_deal_ids": sorted(linked_deal_ids),
        "commitments": commitments,
        "investors": matching_investors,
        "engagement": engagement,
        "engagement_error": engagement_error,
        "license": _license_evidence(license_screen),
        "roles": sorted(roles),
        "ledger_store": ledger,
        "deal_store": deals,
    }


def _last_interaction(evidence: Mapping[str, Any]) -> str | None:
    timestamps: list[datetime] = []
    for event in evidence["events"]:
        parsed = _parse_time(event.get("event_ts") or event.get("created_at"))
        if parsed is not None:
            timestamps.append(parsed)
    for commitment in evidence["commitments"]:
        parsed = _parse_time(commitment.get("made_at"))
        if parsed is not None:
            timestamps.append(parsed)
    engagement = evidence.get("engagement")
    if isinstance(engagement, Mapping):
        parsed = _parse_time(engagement.get("last_touch_at"))
        if parsed is not None:
            timestamps.append(parsed)
    return max(timestamps).isoformat() if timestamps else None


def _red_flags(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    claims = evidence["claims"]
    overridden = [claim for claim in claims if claim.verdict == "overridden"]
    if overridden:
        flags.append(
            {
                "source": "claim_ledger",
                "kind": "overridden_claims",
                "count": len(overridden),
                "note": "Recorded assertions were overridden by higher-authority evidence.",
            }
        )
    quotes = evidence["quotes"]
    died = [quote for quote in quotes if quote.stage == "died"]
    if died:
        flags.append(
            {
                "source": "quote_ledger",
                "kind": "quotes_died",
                "count": len(died),
                "note": "Recorded quotes ended without a close.",
            }
        )
    adverse_retrades = [
        quote
        for quote in quotes
        if (quote.retrade_rate_bps is not None and quote.retrade_rate_bps > 0)
        or (
            quote.retrade_proceeds_pct is not None
            and quote.retrade_proceeds_pct < 0
        )
    ]
    if adverse_retrades:
        flags.append(
            {
                "source": "quote_ledger",
                "kind": "adverse_retrades",
                "count": len(adverse_retrades),
                "note": "Closed quote records include worse rate or proceeds than quoted.",
            }
        )
    broken = [
        item
        for item in evidence["commitments"]
        if item.get("made_by") == "them" and item.get("status") == "broken"
    ]
    if broken:
        flags.append(
            {
                "source": "neg_commitments",
                "kind": "broken_commitments_by_them",
                "count": len(broken),
                "note": "Deal-linked commitments made by 'them' are marked broken.",
            }
        )
    serious_defects = [
        defect
        for defect in evidence["defects"]
        if defect.severity in {"material", "fatal"}
        or defect.outcome in {"retrade", "kill"}
    ]
    if serious_defects:
        flags.append(
            {
                "source": "defect_ledger",
                "kind": "material_or_outcome_defects",
                "count": len(serious_defects),
                "note": "Attributed defects include material/fatal severity or retrade/kill outcomes.",
            }
        )
    license_evidence = evidence["license"]
    discipline_flags = license_evidence.get("disciplinary_flags", [])
    if discipline_flags:
        flags.append(
            {
                "source": "verifyreg",
                "kind": "registry_flags_for_candidate_matches",
                "count": len(discipline_flags),
                "records": discipline_flags,
                "note": "Candidate registry flags require identity confirmation and primary-source review.",
            }
        )
    return flags


async def counterparty_dossier(
    name: str,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
    ledger_store: LedgerStore | None = None,
    deal_store: DealStore | None = None,
    license_screen: Mapping[str, Any] | None = None,
    verifyreg_output: Mapping[str, Any] | None = None,
    as_of: Any = None,
) -> dict[str, Any]:
    """Assemble recorded evidence about a counterparty without external lookup.

    ``license_screen`` and ``verifyreg_output`` are aliases for caller-supplied or
    cached verifyreg evidence.  Supplying both is rejected so provenance stays
    unambiguous.
    """

    if license_screen is not None and verifyreg_output is not None:
        raise ValueError("provide license_screen or verifyreg_output, not both")
    selected_screen = license_screen if license_screen is not None else verifyreg_output
    evidence = await _collect_evidence(
        name,
        db_path=db_path,
        config=config,
        ledger_store=ledger_store,
        deal_store=deal_store,
        license_screen=selected_screen,
        as_of=as_of,
    )
    claims = evidence["claims"]
    quotes = evidence["quotes"]
    defects = evidence["defects"]
    events = sorted(
        evidence["events"],
        key=lambda event: (
            _parse_time(event.get("event_ts") or event.get("created_at"))
            or datetime.min.replace(tzinfo=UTC)
        ),
    )
    engagement = evidence.get("engagement")
    touch_count = 0
    if isinstance(engagement, Mapping):
        frequency = engagement.get("frequency")
        all_time = frequency.get("all_time") if isinstance(frequency, Mapping) else None
        if isinstance(all_time, Mapping) and isinstance(all_time.get("value"), int):
            touch_count = int(all_time["value"])

    defect_records = [defect.model_dump(mode="json") for defect in defects]
    license_evidence = evidence["license"]
    source_summary = {
        "claim_track_record": _claim_track(claims, evidence["name"]),
        "lender_quote_history": _quote_track(quotes, evidence["name"]),
        "commitments": _commitment_evidence(evidence["commitments"]),
        "deal_events": {
            "sample_size": len(events),
            "deal_sample_size": len({event["deal_id"] for event in events}),
            "records": events,
            "sample_warning": _sample_warning(len(events), "named deal events"),
        },
        "license_screen": license_evidence,
        "license_screens": license_evidence,
        "defects": {
            "sample_size": len(defects),
            "records": defect_records,
            "sample_warning": _sample_warning(len(defects), "attributed defects"),
            "attribution_note": (
                "Included only when discovered_by matched the name or the defect text "
                "explicitly mentioned it; textual attribution still requires human review."
            ),
        },
        "ir_touches": {
            "sample_size": touch_count,
            "report": engagement,
            "sample_warning": _sample_warning(touch_count, "governed IR touches"),
            "error": evidence.get("engagement_error"),
            "note": "Activity frequency is not investor intent or a re-up prediction.",
        },
    }
    return {
        "who": evidence["name"],
        "roles_seen": evidence["roles"],
        "evidence_summary": source_summary,
        "red_flags": _red_flags(evidence),
        "last_interaction": _last_interaction(evidence),
        "linked_deal_ids": evidence["linked_deal_ids"],
        "as_of": evidence["as_of"].isoformat(),
        "honesty": ANECDOTE_NOTE,
        "scope": (
            "Permissioned records in the configured shared database plus explicitly "
            "supplied registry output; no public contact database and no live lookup."
        ),
    }


__all__ = ["counterparty_dossier"]
