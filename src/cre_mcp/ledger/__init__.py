"""The Recording Ledger — MedawarCRE's un-backfillable memory of who told the truth.

Three append-only ledgers that turn every deal into proprietary execution data:

- **Claim ledger** — what a counterparty (broker/seller/OM) claimed vs what the
  document reconciliation proved. Captured automatically on every
  ``reconcile_deal_docs`` run: hits AND misses, because a track record needs both.
- **Quote ledger** — what a lender quoted vs what actually closed (rate, proceeds,
  recourse), the raw material for execution scoring (quote-to-close, retrades).
- **Defect ledger** — which flagged defect later caused a retrade, kill, cure, or
  absorbed loss, attributing outcomes to the screening signals that saw them coming.

None of this can be backfilled: a claim not recorded on the day it was reconciled is
gone. Scoring/analytics live in :mod:`cre_mcp.ledger.report` and stay honestly
labeled UNCALIBRATED until enough outcomes accrue.
"""

from cre_mcp.ledger.store import LedgerStore, get_ledger_store

__all__ = ["LedgerStore", "get_ledger_store"]
