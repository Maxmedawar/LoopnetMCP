"""MCP boundaries for the Document Truth Engine (ingestion + extraction).

Ingest a real deal document — from an uploaded file path OR a scraped URL — parse
it, neutralize any injection attempts, classify it, extract every recognizable
figure with full source lineage, and persist it against a deal. Everything a
document asserts is a *claim* with a citation and a confidence; reconciliation
into a verified NOI bridge lands in Phase 26.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import math
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from cre_mcp.access.context import current_context
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.deals.store import get_deal_store
from cre_mcp.ledger.capture import capture_reconciliation
from cre_mcp.source_rights.attestations import (
    DOCUMENT_PURPOSES,
    require_external_document_attestation,
)
from cre_mcp.source_rights.gate import SourceRightsDeniedError
from cre_mcp.source_rights.output import safe_error_message, safe_source_reference
from cre_mcp.truth.classify import classify
from cre_mcp.truth.extract import extract_claims
from cre_mcp.truth.models import DocumentRecord, FieldClaim
from cre_mcp.truth.noi_bridge import build_bridge, build_report
from cre_mcp.truth.parsers import parse_bytes, sniff_ext
from cre_mcp.truth.reconcile import resolve
from cre_mcp.truth.sanitize import sanitize_text
from cre_mcp.truth.store import get_truth_store

logger = logging.getLogger(__name__)


def _restricted_projection_required() -> bool:
    context = current_context()
    return bool(
        context is not None
        and not context.trusted
        and context.profile in TERRITORY_LIMITED
    )

MAX_BYTES = 50 * 1024 * 1024  # 50 MB hard cap on a single document
ALLOWED_EXT = {"pdf", "xlsx", "csv"}


@dataclass(frozen=True)
class _ResolvedDocumentTarget:
    host: str
    port: int
    address: str

    @property
    def curl_resolve_entry(self) -> str:
        address = f"[{self.address}]" if ":" in self.address else self.address
        return f"{self.host}:{self.port}:{address}"


def _resolve_public_document_target(url: str) -> _ResolvedDocumentTarget:
    """Resolve once, reject every non-global answer, and return a pinnable target."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port or 443
    except (TypeError, ValueError):
        raise SourceRightsDeniedError(
            "source-rights denied: document target must be public HTTPS"
        ) from None
    normalized_host = (host or "").casefold().rstrip(".")
    if (
        parsed.scheme.casefold() != "https"
        or not normalized_host
        or normalized_host == "localhost"
        or normalized_host.endswith(".localhost")
        or normalized_host.endswith(".local")
        or normalized_host == "metadata.google.internal"
    ):
        raise SourceRightsDeniedError(
            "source-rights denied: document target must be public HTTPS"
        )
    try:
        answers = socket.getaddrinfo(
            normalized_host,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        addresses = {
            str(ipaddress.ip_address(answer[4][0]))
            for answer in answers
        }
    except (OSError, ValueError):
        raise SourceRightsDeniedError(
            "source-rights denied: document target must be public HTTPS"
        ) from None
    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise SourceRightsDeniedError(
            "source-rights denied: document target must be public HTTPS"
        )
    address = sorted(
        addresses,
        key=lambda value: (ipaddress.ip_address(value).version, value),
    )[0]
    return _ResolvedDocumentTarget(normalized_host, port, address)


def _document_origin(url: str) -> str:
    """Return a lineage-safe origin without userinfo, query, or fragment."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or "external-document"
        port = parsed.port
    except (TypeError, ValueError):
        return "external-document"
    netloc = host.casefold().rstrip(".")
    if ":" in netloc:
        netloc = f"[{netloc}]"
    if port is not None and not (parsed.scheme == "https" and port == 443):
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme.casefold(), netloc, parsed.path, "", ""))


def _fetch_bytes(url: str, rights_attestation_id: str | None = None) -> bytes:
    """Download a scraped document body with a receipt-time memory cap."""
    from curl_cffi import requests as cffi
    from curl_cffi.const import CurlOpt
    from curl_cffi.curl import CURL_WRITEFUNC_ERROR

    # The worker thread re-checks the exact workspace/actor/session/url binding at
    # the socket boundary. asyncio.to_thread propagates the active ContextVar.
    require_external_document_attestation(
        url,
        rights_attestation_id,
        purposes=DOCUMENT_PURPOSES,
    )
    target = _resolve_public_document_target(url)
    body = bytearray()

    def receive(chunk: bytes) -> int:
        # curl invokes this synchronously from its receive loop. Its explicit error
        # sentinel aborts before the rejected chunk enters retained body storage,
        # unlike curl_cffi's stream mode and its unbounded producer queue.
        if not isinstance(chunk, bytes) or len(body) + len(chunk) > MAX_BYTES:
            return CURL_WRITEFUNC_ERROR
        body.extend(chunk)
        return len(chunk)

    try:
        with cffi.Session(
            curl_options={CurlOpt.RESOLVE: [target.curl_resolve_entry]},
            trust_env=False,
            allow_redirects=False,
        ) as session:
            resp = session.get(
                url,
                impersonate="chrome",
                timeout=45,
                allow_redirects=False,
                content_callback=receive,
            )
            if 300 <= resp.status_code < 400:
                raise SourceRightsDeniedError(
                    "source-rights denied: external document redirect requires a new attestation"
                )
            resp.raise_for_status()
            return bytes(body)
    except SourceRightsDeniedError:
        raise
    except Exception:
        raise RuntimeError("external document retrieval failed") from None


async def ingest_document(
    deal_id: str,
    path: str | None = None,
    url: str | None = None,
    doc_kind: str | None = None,
    source_channel: str | None = None,
    rights_attestation_id: str | None = None,
    upload_binding_id: str | None = None,
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
    logger.info(
        "ingest_document called: deal=%s path_supplied=%s url_supplied=%s",
        safe_source_reference(deal_id),
        bool(path),
        bool(url),
    )
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        if bool(path) == bool(url):
            raise ValueError("provide exactly one of path or url")

        if path and source_channel not in {None, "uploaded"}:
            raise ValueError("source_channel must be 'uploaded' for a path")
        if url and source_channel not in {None, "scraped"}:
            raise ValueError("source_channel must be 'scraped' for a URL")

        if path:
            from cre_mcp.source_rights.gate import is_hosted_execution

            if is_hosted_execution():
                raise SourceRightsDeniedError(
                    "source-rights denied: hosted path ingestion requires a "
                    "server-owned upload binding and durable upload repository"
                )
            file_path = Path(path).expanduser()
            if not file_path.is_file():
                raise ValueError(f"file not found: {path}")
            data = file_path.read_bytes()
            origin = file_path.name
            channel = "uploaded"
            ext_hint = file_path.suffix
        else:
            require_external_document_attestation(
                url,  # type: ignore[arg-type]
                rights_attestation_id,
                purposes=DOCUMENT_PURPOSES,
            )
            data = await _to_thread_fetch(url, rights_attestation_id)
            origin = _document_origin(url)  # type: ignore[arg-type]
            channel = "scraped"
            ext_hint = Path(url.split("?")[0]).suffix  # type: ignore[union-attr]

        if not data:
            raise ValueError("document is empty")
        if len(data) > MAX_BYTES:
            raise ValueError(f"document exceeds {MAX_BYTES // (1024 * 1024)} MB limit")
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
        logger.error("ingest_document failed: category=%s", type(exc).__name__)
        if isinstance(exc, SourceRightsDeniedError):
            message = safe_error_message(exc)
        elif isinstance(exc, ValueError) and str(exc).startswith(
            ("deal_id", "provide exactly", "source_channel")
        ):
            message = safe_error_message(exc)
        elif url:
            message = "external document ingestion failed"
        else:
            message = safe_error_message(exc)
        return {"error": message}


async def _to_thread_fetch(
    url: str | None,
    rights_attestation_id: str | None = None,
) -> bytes:
    import asyncio

    if not url:
        raise ValueError("url is required")
    worker = asyncio.create_task(
        asyncio.to_thread(_fetch_bytes, url, rights_attestation_id)
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
        try:
            worker.result()
        except Exception:
            pass
        raise


async def list_deal_documents(deal_id: str) -> dict:
    """List every document ingested for a deal, with per-document claim counts.

    Args:
        deal_id: Source-qualified deal identifier.

    Returns:
        The ingested documents and the total number of extracted claims.
    """
    logger.info(
        "list_deal_documents called: deal=%s",
        safe_source_reference(deal_id),
    )
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        # Resolve and territory-gate the deal before any document is read, so a
        # request outside the caller's territory never materializes document
        # metadata — `origin` routinely names the market the document covers.
        property_record: dict[str, str | None] | None = None
        if _restricted_projection_required():
            _, property_record = await _deal_context(deal_id.strip())
        store = get_truth_store()
        documents = await store.list_documents(deal_id.strip())
        total_claims = sum(doc["claim_count"] for doc in documents)
        result = {
            "deal_id": deal_id.strip(),
            "document_count": len(documents),
            "total_claims": total_claims,
            "documents": documents,
        }
        if property_record is not None:
            result["property"] = property_record
        return result
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("list_deal_documents error: %s", message)
        return {"error": message}


async def _load_claims(deal_id: str) -> list[FieldClaim]:
    rows = await get_truth_store().get_claims(deal_id)
    claims: list[FieldClaim] = []
    for row in rows:
        try:
            claims.append(FieldClaim.model_validate(row))
        except Exception as exc:  # skip a corrupt row rather than fail the whole deal
            logger.warning(
                "skipping unparseable claim for %s: %s",
                safe_source_reference(deal_id),
                safe_error_message(exc),
            )
    return claims


async def _deal_context(
    deal_id: str,
) -> tuple[float | None, dict[str, str | None] | None]:
    """Resolve the stored price and, for restricted profiles, the location.

    The authoritative ``property`` record exists so a territory-limited profile
    can be policed on the record this tool returns, so it is required — and
    fails closed — only when that policy actually runs.  Trusted local and
    full-operator callers keep the historic tolerant behaviour: an unsaved
    deal_id or a listing with no usable address still yields a bridge, exactly
    as it did before this projection existed.
    """
    restricted = _restricted_projection_required()
    deal = await get_deal_store().get_deal(deal_id)
    if not deal:
        if restricted:
            raise ValueError(f"unknown deal_id: {deal_id}")
        return None, None
    listing = deal.get("listing") or {}
    if not isinstance(listing, dict):
        if restricted:
            raise ValueError("stored deal listing is invalid")
        return None, None
    property_record: dict[str, str | None] | None = None
    if restricted:
        property_record = {}
        for key in ("address", "city", "state"):
            value = listing.get(key)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError("stored deal location is invalid")
            property_record[key] = value
        zip_code = listing.get("zip_code")
        if zip_code is not None and (
            not isinstance(zip_code, str)
            or not zip_code.strip()
            or zip_code != zip_code.strip()
        ):
            raise ValueError("stored deal location is invalid")
        property_record["zip_code"] = zip_code
    price = listing.get("price_usd")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return None, property_record
    selected_price = float(price)
    return (
        selected_price if math.isfinite(selected_price) and selected_price > 0 else None,
        property_record,
    )


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
    logger.info(
        "reconcile_deal_docs called: deal=%s",
        safe_source_reference(deal_id),
    )
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
        message = safe_error_message(exc)
        logger.error("reconcile_deal_docs error: %s", message)
        return {"error": message}


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
    logger.info(
        "build_noi_bridge called: deal=%s",
        safe_source_reference(deal_id),
    )
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        stored_price, property_record = await _deal_context(deal_id.strip())
        claims = await _load_claims(deal_id.strip())
        if not claims:
            insufficient = {
                "deal_id": deal_id.strip(),
                "note": "no ingested claims — run ingest_document first",
            }
            if property_record is not None:
                insufficient["property"] = property_record
            return insufficient
        recon = resolve(deal_id.strip(), claims)
        resolved_price = price if price is not None else stored_price
        bridge = build_bridge(recon, price=resolved_price)
        result = bridge.model_dump(mode="json")
        if property_record is not None:
            result["property"] = property_record
        return result
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("build_noi_bridge error: %s", message)
        return {"error": message}


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
    logger.info(
        "deal_truth_report called: deal=%s",
        safe_source_reference(deal_id),
    )
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        stored_price, property_record = await _deal_context(deal_id.strip())
        claims = await _load_claims(deal_id.strip())
        if not claims:
            insufficient = {
                "deal_id": deal_id.strip(),
                "verdict": "insufficient_data",
                "note": "no ingested claims — run ingest_document first",
            }
            if property_record is not None:
                insufficient["property"] = property_record
            return insufficient
        recon = resolve(deal_id.strip(), claims)
        resolved_price = price if price is not None else stored_price
        bridge = build_bridge(recon, price=resolved_price)
        report = build_report(recon, bridge)
        result = {
            "report": report.model_dump(mode="json"),
            "noi_bridge": bridge.model_dump(mode="json"),
        }
        if property_record is not None:
            result["property"] = property_record
        return result
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("deal_truth_report error: %s", message)
        return {"error": message}


__all__ = [
    "ingest_document",
    "list_deal_documents",
    "reconcile_deal_docs",
    "build_noi_bridge",
    "deal_truth_report",
]
