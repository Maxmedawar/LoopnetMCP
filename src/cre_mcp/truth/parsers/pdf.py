"""PDF parsing with page + table lineage.

Primary: pdfplumber (word boxes + ``extract_tables`` for gridded rent rolls/T12s).
Fallback: pypdf (fast plain text, no tables). If neither yields text the document
is flagged ``needs_ocr`` — we never auto-OCR money figures (too noisy) and never
silently return an empty parse.
"""

from __future__ import annotations

from cre_mcp.truth.parsers.base import Cell, Page, ParsedDoc, Table


def parse_pdf(data: bytes, sha256: str) -> ParsedDoc:
    try:
        doc = _parse_pdf_pdfplumber(data, sha256)
    except ImportError:
        doc = None
    if doc is None or not doc.full_text.strip():
        fallback = _parse_pdf_pypdf(data, sha256)
        if fallback is not None and fallback.full_text.strip():
            return fallback
        if doc is not None:
            doc.parse_status = "needs_ocr"
            doc.warnings.append("no extractable text; document likely scanned (needs OCR)")
            return doc
        if fallback is not None:
            fallback.parse_status = "needs_ocr"
            fallback.warnings.append("no extractable text; document likely scanned (needs OCR)")
            return fallback
        return ParsedDoc(
            sha256=sha256, ext="pdf", pages=[Page(1, "")], n_pages=1,
            parse_status="failed", warnings=["no PDF parser available"],
        )
    return doc


def _parse_pdf_pdfplumber(data: bytes, sha256: str) -> ParsedDoc:
    import io

    import pdfplumber  # lazy: part of the optional truth extra

    pages: list[Page] = []
    tables: list[Table] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for p_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append(Page(number=p_idx, text=text))
            for raw_table in page.extract_tables() or []:
                table = Table(page=p_idx)
                for r_idx, row in enumerate(raw_table, start=1):
                    cells: list[Cell] = []
                    for c_idx, value in enumerate(row, start=1):
                        cells.append(
                            Cell(
                                ref=f"p{p_idx}:r{r_idx}c{c_idx}",
                                value="" if value is None else str(value),
                                row=r_idx,
                                col=c_idx,
                                page=p_idx,
                            )
                        )
                    table.rows.append(cells)
                if table.rows:
                    tables.append(table)
    if not pages:
        pages = [Page(number=1, text="")]
    return ParsedDoc(
        sha256=sha256, ext="pdf", pages=pages, tables=tables, n_pages=len(pages)
    )


def _parse_pdf_pypdf(data: bytes, sha256: str) -> ParsedDoc | None:
    try:
        import io

        from pypdf import PdfReader  # lazy
    except ImportError:
        return None
    reader = PdfReader(io.BytesIO(data))
    pages = [
        Page(number=i, text=(page.extract_text() or ""))
        for i, page in enumerate(reader.pages, start=1)
    ]
    if not pages:
        pages = [Page(number=1, text="")]
    return ParsedDoc(sha256=sha256, ext="pdf", pages=pages, n_pages=len(pages))


__all__ = ["parse_pdf"]
