"""Document parsers: bytes -> ParsedDoc (text pages + coordinate-tagged tables).

The only third-party surface in the Truth Engine lives here. Every parser
degrades gracefully: if the optional ``truth`` extra (pdfplumber/openpyxl/pypdf)
is not installed, parsers fall back to a stdlib path so ``ingest_document`` never
hard-crashes the server.
"""

from cre_mcp.truth.parsers.base import Cell, Page, ParsedDoc, Table
from cre_mcp.truth.parsers.dispatch import parse_bytes, sniff_ext

__all__ = ["Cell", "Page", "Table", "ParsedDoc", "parse_bytes", "sniff_ext"]
