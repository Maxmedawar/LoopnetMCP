"""MCP boundaries for the Document Truth Engine (ingestion + extraction).

Ingest a real deal document — from an uploaded file path OR a scraped URL — parse
it, neutralize any injection attempts, classify it, extract every recognizable
figure with full source lineage, and persist it against a deal. Everything a
document asserts is a *claim* with a citation and a confidence; reconciliation
into a verified NOI bridge lands in Phase 26.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from cre_mcp.deals.store import get_deal_store
from cre_mcp.ledger.capture import capture_reconciliation
from cre_mcp.truth.classify import classify
from cre_mcp.truth.extract import extract_claims
from cre_mcp.truth.models import DocumentRecord, FieldClaim
from cre_mcp.truth.noi_bridge import build_bridge, build_report
from cre_mcp.truth.parsers import parse_bytes, sniff_ext
from cre_mcp.truth.reconcile import resolve
from cre_mcp.truth.sanitize import sanitize_text
from cre_mcp.truth.store import get_truth_store
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

MAX_BYTES = 50 * 1024 * 1024  # 50 MB hard cap on a single document
ALLOWED_EXT = {"pdf", "xlsx", "csv"}


def _fetch_bytes(url: str) -> bytes:
    """Download a scraped document body (Chrome-impersonating), honoring the cap."""
    from curl_cffi import requests as cffi

    resp = cffi.get(url, impersonate="chrome", timeout=45, allow_redirects=True)
    resp.raise_for_status()
    return resp.content


async def ingest_document(
    deal_id: str,
    path: str | None = None,
    url: str | None = None,
    doc_kind: str | None = None,
    source_channel: str | None = None,
) -> dict:
    """Ingest one deal document (uploaded file OR scraped URL) and extract its figures.

    Args:
        deal_id: Source-qualified deal identifier (e.g. "crexi:12345"). The deal
            need not exist yet; a warning is returned if it is not in the store.
        path: Absolute path to an uploaded .pdf/.xlsx/.csv file (uploaded channel).
        url: URL of a scraped document to download (scraped channel). Exactly one
            of path/url is required.
        doc_kind: Optional explicit document kind (offering_memorandum, rent_roll,
            t12_operating_statement, lease, ...). Auto-classified when omitted.
        source_channel: "uploaded" or "scraped"; inferred from path/url when omitted.

    Returns:
        A summary with the content-addressed document_id, classified kind, parse
        status, extracted-claim count + preview, and any injection redactions.
    """
    logger.info("ingest_document called: deal=%s path=%s url=%s", deal_id, path, url)
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        if bool(path) == bool(url):
            raise ValueError("provide exactly one of path or url")

        if path:
            file_path = Path(path).expanduser()
            if not file_path.is_file():
                raise ValueError(f"file not found: {path}")
            data = file_path.read_bytes()
            origin = file_path.name
            channel = (source_channel or "uploaded").strip()
            ext_hint = file_path.suffix
        else:
            data = await _to_thread_fetch(url)
            origin = url
            channel = (source_channel or "scraped").strip()
            ext_hint = Path(url.split("?")[0]).suffix  # type: ignore[union-attr]

        if not data:
            raise ValueError("document is empty")
        if len(data) > MAX_BYTES:
            raise ValueError(f"document exceeds {MAX_BYTES // (1024 * 1024)} MB limit")
        if channel not in {"uploaded", "scraped"}:
            raise ValueError("source_channel must be 'uploaded' or 'scraped'")

        ext = sniff_ext(data, ext_hint)
        sha256 = hashlib.sha256(data).hexdigest()
        parsed = parse_bytes(data, ext_hint=ext_hint)

        # Injection defense: measure/neutralize instruction-like content. Extraction
        # itself is deterministic (numbers), but we surface tampering as a red flag.
        sanitized = sanitize_text(parsed.full_text)
        suspicious = sanitized.redactions > 0

        kind = classify(parsed, origin=origin, declared=doc_kind)
        claims = extract_claims(
            parsed,
            document_id=sha256,
            doc_kind=kind,
            source_channel=channel,  # type: ignore[arg-type]
            origin=origin,
        )

        record = DocumentRecord(
            document_id=sha256,
            deal_id=deal_id.strip(),
            doc_kind=kind,
            source_channel=channel,  # type: ignore[arg-type]
            origin=origin,
            blob_path="",  # filled by the store
            n_pages=parsed.n_pages,
            parse_status=parsed.parse_status,
            redactions=sanitized.redactions,
            ingested_at=datetime.now(UTC).isoformat(),
        )

        store = get_truth_store()
        saved = await store.save_document(record, data, claims, ext=ext)
        if saved is None:
            raise RuntimeError("document persistence failed")

        deal = await get_deal_store().get_deal(deal_id.strip())
        warnings = list(parsed.warnings)
        if deal is None:
            warnings.append(
                "deal_id is not yet in the deal store — ingested anyway; save the "
                "listing to link it into analysis"
            )
        if suspicious:
            warnings.append(
                f"{sanitized.redactions} injection-like span(s) neutralized in this "
                "document — treat its text with suspicion"
            )
        if parsed.parse_status == "needs_ocr":
            warnings.append("no extractable text (likely scanned) — figures need manual entry or OCR")

        return {
            "status": "ingested",
            "deal_id": deal_id.strip(),
            "document_id": sha256,
            "doc_kind": kind.value,
            "source_channel": channel,
            "format": ext,
            "n_pages": parsed.n_pages,
            "parse_status": parsed.parse_status,
            "claim_count": len(claims),
            "redactions": sanitized.redactions,
            "suspicious": suspicious,
            "claims_preview": [
                {
                    "field": c.field,
                    "subject": c.subject,
                    "value": c.figure.value,
                    "unit": c.figure.unit,
                    "confidence": c.figure.confidence,
                    "page": c.figure.lineage.page,
                    "cell": c.figure.lineage.cell,
                    "flags": c.flags,
                    "raw_text": c.figure.lineage.raw_text,
                }
                for c in sorted(claims, key=lambda x: x.figure.confidence, reverse=True)[:20]
            ],
            "warnings": warnings,
            "note": (
                "Every figure is a CLAIM with a citation, not a verified fact. Run "
                "reconcile_deal_docs (Phase 26) to resolve conflicts by source authority."
            ),
        }
    except Exception as exc:
        logger.error("ingest_document error: %s", exc)
        return {"error": str(exc)}


async def _to_thread_fetch(url: str | None) -> bytes:
    import asyncio

    if not url:
        raise ValueError("url is required")
    return await asyncio.to_thread(_fetch_bytes, url)


async def list_deal_documents(deal_id: str) -> dict:
    """List every document ingested for a deal, with per-document claim counts.

    Args:
        deal_id: Source-qualified deal identifier.

    Returns:
        The ingested documents and the total number of extracted claims.
    """
    logger.info("list_deal_documents called: deal=%s", deal_id)
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        store = get_truth_store()
        documents = await store.list_documents(deal_id.strip())
        total_claims = sum(doc["claim_count"] for doc in documents)
        return {
            "deal_id": deal_id.strip(),
            "document_count": len(documents),
            "total_claims": total_claims,
            "documents": documents,
        }
    except Exception as exc:
        logger.error("list_deal_documents error: %s", exc)
        return {"error": str(exc)}


async def _load_claims(deal_id: str) -> list[FieldClaim]:
    rows = await get_truth_store().get_claims(deal_id)
    claims: list[FieldClaim] = []
    for row in rows:
        try:
            claims.append(FieldClaim.model_validate(row))
        except Exception as exc:  # skip a corrupt row rather than fail the whole deal
            logger.warning("skipping unparseable claim for %s: %s", deal_id, exc)
    return claims


async def _deal_price(deal_id: str) -> float | None:
    deal = await get_deal_store().get_deal(deal_id)
    if not deal:
        return None
    listing = deal.get("listing") or {}
    price = listing.get("price_usd")
    return float(price) if isinstance(price, (int, float)) else None


async def reconcile_deal_docs(deal_id: str, counterparty: str | None = None) -> dict:
    """Resolve every ingested claim to one value by SOURCE AUTHORITY.

    Ranks competing claims (executed lease > estoppel > bank > rent roll > T12 >
    OM > listing), surfaces material disagreements as conflicts that keep BOTH
    values for review, and flags pro-forma figures presented as in-place. It never
    averages conflicting facts.

    Every run also grades the counterparty-authored claims (listing/OM/seller rep)
    against the documents that outranked them and appends the results to the
    permanent claim ledger — hits and misses both. That evidence cannot be
    backfilled later; see counterparty_track_record to read it.

    Args:
        deal_id: Source-qualified deal identifier with ingested documents.
        counterparty: Optional broker/seller name to attribute graded claims to.

    Returns:
        The reconciliation: per-field resolved values with citations + confidence,
        every unresolved conflict, and how many claims were ledgered.
    """
    logger.info("reconcile_deal_docs called: deal=%s", deal_id)
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        claims = await _load_claims(deal_id.strip())
        if not claims:
            return {"deal_id": deal_id.strip(), "note": "no ingested claims — run ingest_document first",
                    "resolutions": [], "conflicts": []}
        recon = resolve(deal_id.strip(), claims)
        ledgered = await capture_reconciliation(
            recon,
            counterparty=(counterparty.strip() if counterparty else None),
            counterparty_role="broker" if counterparty else "unknown",
        )
        result = recon.model_dump(mode="json")
        result["claims_ledgered"] = ledgered
        return result
    except Exception as exc:
        logger.error("reconcile_deal_docs error: %s", exc)
        return {"error": str(exc)}


async def build_noi_bridge(deal_id: str, price: float | None = None) -> dict:
    """Restate NOI three ways: seller-stated -> verified -> lender-stressed.

    Every line is cited; the walk shows each dollar of movement between columns
    (pro-forma removed, components recomputed, lender floors applied). Uses the
    deal's asking price for implied cap rates when price is omitted.

    Args:
        deal_id: Source-qualified deal identifier with ingested documents.
        price: Optional purchase/asking price for implied cap rates.

    Returns:
        The NOI bridge (three columns + dollar walk + unresolved conflicts).
    """
    logger.info("build_noi_bridge called: deal=%s", deal_id)
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        claims = await _load_claims(deal_id.strip())
        if not claims:
            return {"deal_id": deal_id.strip(), "note": "no ingested claims — run ingest_document first"}
        recon = resolve(deal_id.strip(), claims)
        resolved_price = price if price is not None else await _deal_price(deal_id.strip())
        bridge = build_bridge(recon, price=resolved_price)
        return bridge.model_dump(mode="json")
    except Exception as exc:
        logger.error("build_noi_bridge error: %s", exc)
        return {"error": str(exc)}


async def deal_truth_report(deal_id: str, price: float | None = None) -> dict:
    """Produce the fatal-flaw / missing-document verdict for a deal.

    Combines reconciliation + the NOI bridge into an explicit proceed /
    proceed_with_conditions / re_trade / kill verdict: seller-vs-verified NOI gap,
    pro-forma-as-actual, material conflicts, and which documents are still missing.

    Args:
        deal_id: Source-qualified deal identifier with ingested documents.
        price: Optional purchase/asking price for implied cap rates.

    Returns:
        The fatal-flaw report plus the NOI bridge it was derived from.
    """
    logger.info("deal_truth_report called: deal=%s", deal_id)
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        claims = await _load_claims(deal_id.strip())
        if not claims:
            return {"deal_id": deal_id.strip(), "verdict": "insufficient_data",
                    "note": "no ingested claims — run ingest_document first"}
        recon = resolve(deal_id.strip(), claims)
        resolved_price = price if price is not None else await _deal_price(deal_id.strip())
        bridge = build_bridge(recon, price=resolved_price)
        report = build_report(recon, bridge)
        return {"report": report.model_dump(mode="json"), "noi_bridge": bridge.model_dump(mode="json")}
    except Exception as exc:
        logger.error("deal_truth_report error: %s", exc)
        return {"error": str(exc)}


__all__ = [
    "ingest_document",
    "list_deal_documents",
    "reconcile_deal_docs",
    "build_noi_bridge",
    "deal_truth_report",
]
