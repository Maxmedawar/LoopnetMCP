"""Document Truth Engine.

Ingest hostile CRE deal documents (offering memoranda, rent rolls, T12s, leases),
extract line items with full source lineage + confidence, and (in later phases)
reconcile conflicts by source authority into a normalized NOI bridge.

Phase 25 surface: ingestion + deterministic extraction + persistence.
Nothing here trusts document text: every figure carries a citation, and document
content is treated as inert data that can never trigger a tool call.
"""

from cre_mcp.truth.models import (
    DocKind,
    ExtractedFigure,
    ExtractionMethod,
    FieldClaim,
    Lineage,
)

__all__ = [
    "DocKind",
    "ExtractionMethod",
    "Lineage",
    "ExtractedFigure",
    "FieldClaim",
]
