"""Typed models for extracted document figures and their source lineage.

Every number the engine reads is a *claim* — a value plus a citation and a
confidence — never a bare fact. Reconciliation (Phase 26) resolves competing
claims by source authority; nothing here averages or trusts blindly.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class DocKind(str, Enum):
    """The kind of deal document a figure was read from.

    Ordering is not authority — authority lives in ``reconcile.SOURCE_AUTHORITY``
    (Phase 26) so an executed lease outranks a marketing OM regardless of enum order.
    """

    OM = "offering_memorandum"
    RENT_ROLL = "rent_roll"
    T12 = "t12_operating_statement"
    LEASE = "lease"
    AMENDMENT = "lease_amendment"
    ESTOPPEL = "estoppel_certificate"
    BANK_STMT = "bank_statement"
    TAX_BILL = "tax_bill"
    APPRAISAL = "appraisal"
    SURVEY = "survey"
    ASSESSOR = "assessor_record"
    LISTING = "listing_page"
    UNKNOWN = "unknown"


class ExtractionMethod(str, Enum):
    """How a figure was pulled out of a document (drives the confidence floor)."""

    XLSX_CELL = "xlsx_cell"
    CSV_CELL = "csv_cell"
    PDF_TABLE = "pdf_table"
    PDF_TEXT_REGEX = "pdf_text_regex"
    LLM_ASSISTED = "llm_assisted"
    MANUAL = "manual_entry"


Unit = Literal[
    "usd",
    "usd_per_year",
    "usd_per_month",
    "usd_per_sqft",
    "sqft",
    "pct",
    "count",
    "date",
    "text",
]

SourceChannel = Literal["uploaded", "scraped"]


class Lineage(BaseModel):
    """Where exactly a figure came from — the citation behind every number."""

    document_id: str
    doc_kind: DocKind
    source_channel: SourceChannel = "uploaded"
    page: int | None = None  # PDF page, 1-based
    cell: str | None = None  # spreadsheet ref, e.g. "Sheet1!D2"
    bbox: tuple[float, float, float, float] | None = None  # pdf word box
    raw_text: str = ""  # the exact text we read the value from
    extraction_method: ExtractionMethod
    origin: str | None = None  # filename or source URL


class ExtractedFigure(BaseModel):
    """A single value with its unit, parser confidence, and citation."""

    value: float | str | None
    unit: Unit = "usd"
    confidence: float = Field(ge=0.0, le=1.0)
    lineage: Lineage


class FieldClaim(BaseModel):
    """One canonical field asserted by ONE document (pre-reconciliation)."""

    field: str  # canonical: noi, gross_potential_rent, base_rent, operating_expenses,
    #             vacancy_rate, other_income, rentable_sf, tenant_name, guarantor, ...
    subject: str | None = None  # optional line subject, e.g. "Suite 101"
    figure: ExtractedFigure
    flags: list[str] = Field(default_factory=list)  # e.g. proforma_not_actual, includes_nonrecurring


class DocumentRecord(BaseModel):
    """A persisted, content-addressed source document for a deal."""

    document_id: str  # sha256 of the raw bytes
    deal_id: str
    doc_kind: DocKind
    source_channel: SourceChannel
    origin: str | None = None  # filename or URL
    blob_path: str
    n_pages: int | None = None
    parse_status: Literal["parsed", "needs_ocr", "failed"] = "parsed"
    redactions: int = 0  # injection-like spans neutralized on ingest
    ingested_at: str


__all__ = [
    "DocKind",
    "ExtractionMethod",
    "Unit",
    "SourceChannel",
    "Lineage",
    "ExtractedFigure",
    "FieldClaim",
    "DocumentRecord",
]
