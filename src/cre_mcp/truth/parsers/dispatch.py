"""Route raw bytes to the right parser by sniffing magic bytes, not the extension.

An attacker (or a mislabeled upload) controls the filename; they do not control
the leading bytes, so we sniff ``%PDF`` / the zip signature and only trust the
declared extension as a tiebreaker.
"""

from __future__ import annotations

import hashlib
import io
import zipfile

from cre_mcp.truth.parsers.base import ParsedDoc
from cre_mcp.truth.parsers.pdf import parse_pdf
from cre_mcp.truth.parsers.spreadsheet import parse_csv, parse_xlsx

_ALLOWED = {"pdf", "xlsx", "csv"}


def sniff_ext(data: bytes, hint: str | None = None) -> str:
    """Return one of pdf|xlsx|csv from magic bytes, falling back to the hint."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        # Zip container: xlsx if it carries the OOXML spreadsheet parts.
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
            if any(n.startswith("xl/") for n in names):
                return "xlsx"
        except zipfile.BadZipFile:
            pass
    normalized = (hint or "").lower().lstrip(".")
    if normalized in _ALLOWED:
        return normalized
    # Default: treat as CSV/plaintext (safe — it is parsed as inert rows).
    return "csv"


def parse_bytes(data: bytes, *, ext_hint: str | None = None) -> ParsedDoc:
    """Content-hash then parse raw document bytes into a ParsedDoc."""
    sha256 = hashlib.sha256(data).hexdigest()
    ext = sniff_ext(data, ext_hint)
    if ext == "pdf":
        return parse_pdf(data, sha256)
    if ext == "xlsx":
        return parse_xlsx(data, sha256)
    return parse_csv(data, sha256)


__all__ = ["parse_bytes", "sniff_ext"]
