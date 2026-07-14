"""Read lease files as inert, sanitized text with stable text offsets.

HTML is parsed with the standard library rather than executed or rendered.
PDFs reuse the Document Truth Engine's deterministic parser.  Every format is
passed through the hostile-document sanitizer before clause extraction.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from cre_mcp.truth.parsers.pdf import parse_pdf
from cre_mcp.truth.sanitize import sanitize_text


@dataclass
class LeaseDocument:
    """Sanitized text and ingest facts needed by the honesty report."""

    text: str
    source_path: str
    format: str
    redactions: int = 0
    redacted_spans: list[str] = field(default_factory=list)
    parse_status: str = "parsed"
    warnings: list[str] = field(default_factory=list)


class _LeaseHTMLParser(HTMLParser):
    """Extract visible text while keeping deterministic output offsets."""

    _BLOCKS = {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
        "dt", "figcaption", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
        "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
    _IGNORED = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignore_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.casefold()
        if tag in self._IGNORED:
            self._ignore_depth += 1
        elif self._ignore_depth == 0 and tag in self._BLOCKS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self._IGNORED and self._ignore_depth:
            self._ignore_depth -= 1
        elif self._ignore_depth == 0 and tag in self._BLOCKS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignore_depth == 0:
            self._parts.append(data)

    @property
    def text(self) -> str:
        # Do not collapse whitespace here: extractor locators are offsets in
        # this exact returned string, and quotes remain literal substrings.
        return "".join(self._parts).replace("\r\n", "\n").replace("\r", "\n")


def _decode_text(data: bytes) -> str:
    """Decode common SEC/plain-text encodings without dropping bytes silently."""
    for encoding in ("utf-8-sig", "utf-8", "windows-1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_lease(path: str | Path) -> LeaseDocument:
    """Load and sanitize a .txt, .htm/.html, or .pdf lease document."""
    source = Path(path).expanduser()
    suffix = source.suffix.casefold()
    if suffix not in {".txt", ".htm", ".html", ".pdf"}:
        raise ValueError("lease reader supports only .txt, .htm/.html, and .pdf")
    data = source.read_bytes()
    warnings: list[str] = []
    parse_status = "parsed"

    if suffix == ".pdf":
        parsed = parse_pdf(data, hashlib.sha256(data).hexdigest())
        raw = parsed.full_text
        warnings.extend(parsed.warnings)
        parse_status = parsed.parse_status
        file_format = "pdf"
    elif suffix in {".htm", ".html"}:
        parser = _LeaseHTMLParser()
        parser.feed(_decode_text(data))
        parser.close()
        raw = parser.text
        file_format = "html"
    else:
        raw = _decode_text(data).replace("\r\n", "\n").replace("\r", "\n")
        file_format = "txt"

    sanitized = sanitize_text(raw)
    return LeaseDocument(
        text=sanitized.text,
        source_path=str(source),
        format=file_format,
        redactions=sanitized.redactions,
        redacted_spans=sanitized.redacted_spans,
        parse_status=parse_status,
        warnings=warnings,
    )


load_lease = read_lease
read_lease_document = read_lease


def read_lease_text(path: str | Path) -> str:
    """Convenience surface for callers that need only sanitized text."""
    return read_lease(path).text

__all__ = [
    "LeaseDocument", "read_lease", "load_lease", "read_lease_document",
    "read_lease_text",
]
