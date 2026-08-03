"""Parse artifacts shared by every document parser.

These are internal, non-persisted dataclasses (fast, no validation overhead).
The persisted, validated surface is ``truth.models`` (FieldClaim / Lineage).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Cell:
    """One spreadsheet/table cell that remembers where it came from."""

    ref: str  # "D2" or "Sheet1!D2"
    value: str  # raw string value (numbers kept as text until extraction normalizes)
    row: int  # 1-based
    col: int  # 1-based
    sheet: str | None = None
    page: int | None = None  # for PDF-derived tables


@dataclass
class Table:
    """A grid of cells, each carrying its own coordinate/lineage."""

    rows: list[list[Cell]] = field(default_factory=list)
    sheet: str | None = None
    page: int | None = None

    def iter_cells(self):  # pragma: no cover - trivial
        for row in self.rows:
            yield from row


@dataclass
class Page:
    """One page of extracted text (PDF page, or a synthetic page for sheets)."""

    number: int  # 1-based
    text: str


@dataclass
class ParsedDoc:
    """The normalized result of parsing one document's bytes."""

    sha256: str
    ext: str  # "pdf" | "xlsx" | "csv"
    pages: list[Page] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    n_pages: int = 0
    parse_status: str = "parsed"  # parsed | needs_ocr | failed
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """All page text joined — used for classification and prose regex."""
        return "\n".join(page.text for page in self.pages)


__all__ = ["Cell", "Table", "Page", "ParsedDoc"]
