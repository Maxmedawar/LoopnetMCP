"""Track-record aggregation over the ledgers — honestly labeled, never oversold.

Small samples are the norm early; every report carries ``sample_size`` and a
warning below :data:`MIN_SAMPLE`. These reports become the substrate for lender
execution scoring (job 155) and broker credibility (job 237) — but the scoring
itself stays out until the sample supports it.
"""

from __future__ import annotations

from collections import defaultdict

from cre_mcp.ledger.models import CounterpartyTrackRecord
from cre_mcp.ledger.store import LedgerStore, get_ledger_store

MIN_SAMPLE = 10  # below this, any rate is anecdote, not signal


async def counterparty_track_record(
    counterparty: str | None = None,
    *,
    deal_id: str | None = None,
    store: LedgerStore | None = None,
) -> CounterpartyTrackRecord:
    """Aggregate claim accuracy for one counterparty (or one deal)."""
    store = store or get_ledger_store()
    claims = await store.claims_for(counterparty=counterparty, deal_id=deal_id)

    corroborated = [c for c in claims if c.verdict == "corroborated"]
    overridden = [c for c in claims if c.verdict == "overridden"]
    tested = len(corroborated) + len(overridden)

    deltas = [c.delta_pct for c in overridden if c.delta_pct is not None]
    by_field: dict[str, list[float]] = defaultdict(list)
    field_counts: dict[str, int] = defaultdict(int)
    for c in overridden:
        field_counts[c.field] += 1
        if c.delta_pct is not None:
            by_field[c.field].append(c.delta_pct)

    worst = sorted(
        (
            {
                "field": field,
                "overridden": count,
                "mean_delta_pct": (
                    round(sum(by_field[field]) / len(by_field[field]), 4)
                    if by_field[field]
                    else None
                ),
            }
            for field, count in field_counts.items()
        ),
        key=lambda row: row["overridden"],
        reverse=True,
    )[:5]

    return CounterpartyTrackRecord(
        counterparty=counterparty,
        deals=len({c.deal_id for c in claims}),
        claims_total=len(claims),
        claims_corroborated=len(corroborated),
        claims_overridden=len(overridden),
        accuracy_rate=round(len(corroborated) / tested, 4) if tested else None,
        mean_overstatement_pct=(
            round(sum(deltas) / len(deltas), 4) if deltas else None
        ),
        worst_fields=worst,
        sample_warning=(
            f"only {tested} tested claims — this is anecdote, not signal "
            f"(need >= {MIN_SAMPLE})"
            if tested < MIN_SAMPLE
            else None
        ),
    )


async def lender_track_record(
    lender: str, *, store: LedgerStore | None = None
) -> dict:
    """Quote-to-close summary for one lender. Raw material for execution scoring."""
    store = store or get_ledger_store()
    quotes = await store.quotes_for(lender=lender)
    closed = [q for q in quotes if q.stage == "closed"]
    died = [q for q in quotes if q.stage == "died"]
    retrades_rate = [q.retrade_rate_bps for q in closed if q.retrade_rate_bps is not None]
    retrades_proceeds = [
        q.retrade_proceeds_pct for q in closed if q.retrade_proceeds_pct is not None
    ]
    days = [q.days_quote_to_close for q in closed if q.days_quote_to_close is not None]
    resolved = len(closed) + len(died)
    return {
        "lender": lender,
        "quotes_total": len(quotes),
        "closed": len(closed),
        "died": len(died),
        "open": len(quotes) - resolved,
        "close_rate": round(len(closed) / resolved, 4) if resolved else None,
        "mean_retrade_rate_bps": (
            round(sum(retrades_rate) / len(retrades_rate), 1) if retrades_rate else None
        ),
        "mean_retrade_proceeds_pct": (
            round(sum(retrades_proceeds) / len(retrades_proceeds), 4)
            if retrades_proceeds
            else None
        ),
        "mean_days_quote_to_close": round(sum(days) / len(days)) if days else None,
        "sample_warning": (
            f"only {resolved} resolved quotes — anecdote, not signal (need >= {MIN_SAMPLE})"
            if resolved < MIN_SAMPLE
            else None
        ),
        "honesty": "raw history, UNCALIBRATED — no execution score is derived below sample",
    }


async def defect_outcome_stats(*, store: LedgerStore | None = None) -> dict:
    """Which defect types actually cost money — feeds screening calibration."""
    store = store or get_ledger_store()
    defects = await store.defects_for()
    by_type: dict[str, dict] = {}
    for d in defects:
        row = by_type.setdefault(
            d.defect_type,
            {"flagged": 0, "retrade": 0, "kill": 0, "cure": 0, "absorbed": 0,
             "no_impact": 0, "open": 0, "dollar_impact_total": 0.0},
        )
        row["flagged"] += 1
        row[d.outcome] = row.get(d.outcome, 0) + 1
        if d.dollar_impact is not None:
            row["dollar_impact_total"] += d.dollar_impact
    resolved = sum(1 for d in defects if d.outcome != "open")
    return {
        "defects_total": len(defects),
        "resolved": resolved,
        "by_type": by_type,
        "sample_warning": (
            f"only {resolved} resolved defects — anecdote, not signal (need >= {MIN_SAMPLE})"
            if resolved < MIN_SAMPLE
            else None
        ),
    }
