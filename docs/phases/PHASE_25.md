# PHASE 25 — Document Truth Engine I: ingestion + extraction  ✅

First of the three deep systems from ROADMAP_V3 (Truth · Control · Memory). Turns
"score off a listing" into "verified figures from the real documents." Feeds Phase 26
(reconciliation → NOI bridge).

## Delivered
- `pyproject.toml` optional `truth` extra (pdfplumber / openpyxl / pypdf); parsers import
  lazily + fall back to stdlib so the server never hard-crashes without the extra.
- `src/cre_mcp/truth/`:
  - `models.py` — DocKind, ExtractionMethod, Lineage (document_id/page/cell/bbox/raw_text/
    method), ExtractedFigure, FieldClaim, DocumentRecord. Every number is a *claim* + citation.
  - `parsers/` — `base.py` (Cell/Table/Page/ParsedDoc), `spreadsheet.py` (openpyxl + stdlib
    zipfile fallback + csv), `pdf.py` (pdfplumber tables/text → pypdf → needs_ocr flag),
    `dispatch.py` (magic-byte sniffing, not the extension).
  - `sanitize.py` — hostile-document defense: NFKC-normalize, strip invisibles/bidi,
    redact injection/role-spoof/tool-call spans, and LOG the redaction (a document that
    tries to inject is itself a red flag surfaced, not hidden).
  - `classify.py` — DocKind by title keywords + a structural fallback (NOI + expenses ⇒
    operating statement; tenant+rent+lease ⇒ rent roll).
  - `extract.py` — deterministic (no model in the loop): table rows + labeled statement
    lines → canonical FieldClaims with normalized value/unit, confidence by method
    (xlsx/csv cell 1.0 · pdf table 0.9 · text regex 0.7 · llm 0.3; pro-forma ×0.5 + flag).
  - `store.py` — TruthStore: async façade over the shared cache DB (truth_documents,
    truth_claims), blobs content-addressed on disk (sha256 dedupe). Mirrors DealStore.
- `tools/truth_tools.py` — `ingest_document` (uploaded path OR scraped url — both, per Max)
  and `list_deal_documents`; registered in `register_all`. Tool count 45 → 47.

## Verified
- `pytest tests/truth/ -q` → 15 passed. Full suite (ex control/) → 567 passed.
- Live pre-work proofs: parsing libs confirmed installable; the stdlib xlsx/pdf floor works.
- Injection defense verified: "ignore previous instructions…" redacted, real $412,500 survives.

## Not yet (Phase 26+)
- Reconciliation by source authority, conflict detection, NOI bridge, fatal-flaw report.
- `FetchClient.get_bytes` (scraped-PDF now uses a direct curl_cffi download inside the tool).
- LLM-assisted prose extraction (behind the deterministic path, sandboxed, empty tool list).
