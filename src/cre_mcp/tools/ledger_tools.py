"""MCP boundaries for the Recording Ledger — the un-backfillable evidence layer.

Claim capture happens automatically inside ``reconcile_deal_docs``; these tools
add the two ledgers that need human input (lender quotes, defect outcomes) and
the read-side track records. Every report is honestly labeled: below sample it
says "anecdote, not signal" instead of pretending a score.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from cre_mcp.ledger.models import DefectRecord, QuoteRecord
from cre_mcp.ledger.report import (
    counterparty_track_record as _counterparty_track_record,
)
from cre_mcp.ledger.report import (
    defect_outcome_stats as _defect_outcome_stats,
)
from cre_mcp.ledger.report import (
    lender_track_record as _lender_track_record,
)
from cre_mcp.ledger.store import get_ledger_store, new_id

logger = logging.getLogger(__name__)

_QUOTE_STAGES = {"quoted", "term_sheet", "committed", "closed", "died"}
_DEFECT_OUTCOMES = {"retrade", "kill", "cure", "absorbed", "no_impact"}


async def record_lender_quote(
    deal_id: str,
    lender: str,
    rate_pct: float | None = None,
    proceeds: float | None = None,
    ltv_pct: float | None = None,
    io_months: int | None = None,
    amort_years: int | None = None,
    recourse: str | None = None,
    prepay: str | None = None,
    notes: str | None = None,
) -> dict:
    """Record what a lender QUOTED on a deal, the day they quoted it.

    Quoted terms are not closed terms. This ledger accumulates the difference:
    when the loan later closes (or dies), call resolve_lender_quote and the
    retrade — rate drift in bps, proceeds cut in percent, days quote-to-close —
    is computed and kept forever. That history is what makes lender selection an
    evidence decision instead of a relationship guess. It cannot be backfilled.

    Args:
        deal_id: Deal the quote belongs to.
        lender: Lender name (used verbatim as the aggregation key).
        rate_pct: Quoted rate in percent (e.g. 6.75).
        proceeds: Quoted loan amount in dollars.
        ltv_pct: Quoted LTV in percent.
        io_months: Interest-only period, months.
        amort_years: Amortization, years.
        recourse: full / partial / non-recourse / bad-boy.
        prepay: Prepayment structure (yield maintenance, defeasance, stepdown...).
        notes: Free-form context (broker, program, conditions).

    Returns:
        The stored quote record with its quote_id (needed to resolve it later).
    """
    logger.info("record_lender_quote: deal=%s lender=%s", deal_id, lender)
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        if not lender or not lender.strip():
            raise ValueError("lender is required")
        rec = QuoteRecord(
            quote_id=new_id("qt"),
            deal_id=deal_id.strip(),
            lender=lender.strip(),
            rate_pct=rate_pct,
            proceeds=proceeds,
            ltv_pct=ltv_pct,
            io_months=io_months,
            amort_years=amort_years,
            recourse=recourse,
            prepay=prepay,
            notes=notes,
            quoted_at=datetime.now(UTC).isoformat(),
        )
        await get_ledger_store().record_quote(rec)
        return {
            "recorded": rec.model_dump(mode="json"),
            "next_step": "when this loan closes or dies, call resolve_lender_quote "
            f"with quote_id={rec.quote_id} and the FINAL terms",
        }
    except Exception as exc:
        logger.error("record_lender_quote error: %s", exc)
        return {"error": str(exc)}


async def resolve_lender_quote(
    quote_id: str,
    stage: str,
    final_rate_pct: float | None = None,
    final_proceeds: float | None = None,
    final_recourse: str | None = None,
) -> dict:
    """Record how a lender quote actually ENDED — closed terms or a dead deal.

    Computes the retrade against the stored quote: rate drift in bps, proceeds
    change in percent, and days quote-to-close. "closed" with no final terms is
    accepted but the retrade fields stay honestly None.

    Args:
        quote_id: The id returned by record_lender_quote.
        stage: closed | died | committed | term_sheet.
        final_rate_pct: Rate that actually closed, percent.
        final_proceeds: Proceeds that actually funded, dollars.
        final_recourse: Recourse as closed.

    Returns:
        The updated record including computed retrade deltas.
    """
    logger.info("resolve_lender_quote: %s -> %s", quote_id, stage)
    try:
        stage = (stage or "").strip().lower()
        if stage not in _QUOTE_STAGES - {"quoted"}:
            raise ValueError(f"stage must be one of {sorted(_QUOTE_STAGES - {'quoted'})}")
        updated = await get_ledger_store().resolve_quote(
            quote_id.strip(),
            stage=stage,
            final_rate_pct=final_rate_pct,
            final_proceeds=final_proceeds,
            final_recourse=final_recourse,
        )
        if updated is None:
            return {"error": f"no quote with quote_id {quote_id!r}"}
        return {"resolved": updated.model_dump(mode="json")}
    except Exception as exc:
        logger.error("resolve_lender_quote error: %s", exc)
        return {"error": str(exc)}


async def record_defect_outcome(
    deal_id: str,
    defect_type: str,
    description: str,
    severity: str = "material",
    discovered_stage: str = "diligence",
    discovered_by: str = "human",
    outcome: str | None = None,
    outcome_notes: str | None = None,
    dollar_impact: float | None = None,
    defect_id: str | None = None,
) -> dict:
    """Record a deal defect and, when known, what it actually did to the deal.

    Novices produce issue lists; experts know what each issue does to price and
    closing probability. This ledger builds that knowledge from lived outcomes:
    flag the defect when found (outcome omitted → stays open), then call again
    with defect_id + outcome once reality answers — retrade, kill, cure,
    absorbed, or no_impact — with the signed dollar impact when measurable.

    Args:
        deal_id: Deal the defect belongs to.
        defect_type: Short slug, e.g. noi_overstated, sf_mismatch, title_lien.
        description: What was found, concretely.
        severity: info | warning | material | fatal (truth-engine vocabulary).
        discovered_stage: screening | diligence | closing | post_close.
        discovered_by: Tool name or "human".
        outcome: retrade | kill | cure | absorbed | no_impact (omit while open).
        outcome_notes: How it played out.
        dollar_impact: Signed dollars (negative = cost / price reduction).
        defect_id: Pass an existing id to resolve a previously flagged defect.

    Returns:
        The stored/updated defect record.
    """
    logger.info("record_defect_outcome: deal=%s type=%s", deal_id, defect_type)
    try:
        store = get_ledger_store()
        if defect_id:
            if not outcome or outcome.strip().lower() not in _DEFECT_OUTCOMES:
                raise ValueError(
                    f"resolving needs outcome, one of {sorted(_DEFECT_OUTCOMES)}"
                )
            updated = await store.resolve_defect(
                defect_id.strip(),
                outcome=outcome.strip().lower(),
                outcome_notes=outcome_notes,
                dollar_impact=dollar_impact,
            )
            if updated is None:
                return {"error": f"no defect with defect_id {defect_id!r}"}
            return {"resolved": updated.model_dump(mode="json")}

        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        if not description or not description.strip():
            raise ValueError("description is required")
        rec = DefectRecord(
            defect_id=new_id("df"),
            deal_id=deal_id.strip(),
            defect_type=(defect_type or "unspecified").strip(),
            description=description.strip(),
            severity=severity,
            discovered_stage=discovered_stage,
            discovered_by=discovered_by,
            outcome=(outcome.strip().lower() if outcome else "open"),  # type: ignore[arg-type]
            outcome_notes=outcome_notes,
            dollar_impact=dollar_impact,
            flagged_at=datetime.now(UTC).isoformat(),
        )
        await store.record_defect(rec)
        return {
            "recorded": rec.model_dump(mode="json"),
            "next_step": "when reality answers, call again with this defect_id and "
            "the outcome (retrade/kill/cure/absorbed/no_impact) + dollar impact",
        }
    except Exception as exc:
        logger.error("record_defect_outcome error: %s", exc)
        return {"error": str(exc)}


async def counterparty_track_record(
    counterparty: str | None = None, deal_id: str | None = None
) -> dict:
    """Report a counterparty's claim accuracy from the automatic claim ledger.

    Every reconcile_deal_docs run grades listing/OM/seller claims against the
    documents that outrank them and records hits AND misses. This reads the
    accumulated record: accuracy rate, mean overstatement, worst fields. Below
    sample it says so — "anecdote, not signal" — instead of scoring.

    Args:
        counterparty: Broker/seller name as recorded (omit to filter by deal).
        deal_id: Restrict to one deal's claims.

    Returns:
        Track record with sample size and honesty labels.
    """
    logger.info(
        "counterparty_track_record: counterparty=%s deal=%s", counterparty, deal_id
    )
    try:
        if not counterparty and not deal_id:
            raise ValueError("pass counterparty and/or deal_id")
        record = await _counterparty_track_record(counterparty, deal_id=deal_id)
        return record.model_dump(mode="json")
    except Exception as exc:
        logger.error("counterparty_track_record error: %s", exc)
        return {"error": str(exc)}


async def lender_track_record(lender: str) -> dict:
    """Report a lender's quote-to-close history from the quote ledger.

    Close rate, mean retrade (bps and proceeds), mean days quote-to-close — the
    raw history behind lender execution scoring. No score is derived below
    sample; the honest report says what the data is.

    Args:
        lender: Lender name exactly as recorded in record_lender_quote.

    Returns:
        Aggregated quote-to-close history with honesty labels.
    """
    logger.info("lender_track_record: %s", lender)
    try:
        if not lender or not lender.strip():
            raise ValueError("lender is required")
        return await _lender_track_record(lender.strip())
    except Exception as exc:
        logger.error("lender_track_record error: %s", exc)
        return {"error": str(exc)}


async def defect_track_record() -> dict:
    """Report which flagged defect types actually cost money, from lived outcomes.

    Aggregates the defect ledger by type: how many flagged, how each resolved
    (retrade/kill/cure/absorbed/no_impact), total dollar impact. This is the
    feedback loop that turns screening flags into calibrated judgment.

    Returns:
        Per-defect-type outcome stats with sample-size honesty labels.
    """
    logger.info("defect_track_record called")
    try:
        return await _defect_outcome_stats()
    except Exception as exc:
        logger.error("defect_track_record error: %s", exc)
        return {"error": str(exc)}
