"""Deterministic extraction: ParsedDoc -> list[FieldClaim] with lineage.

No model in the loop. Table cells and labeled statement lines are matched to
canonical fields by keyword, and every emitted figure keeps the exact cell/line
it was read from, a normalized value, a unit, and a confidence set by HOW it was
read (a spreadsheet cell is trusted more than a regex over marketing prose).
"""

from __future__ import annotations

import re

from cre_mcp.truth.models import (
    DocKind,
    ExtractedFigure,
    ExtractionMethod,
    FieldClaim,
    Lineage,
    SourceChannel,
    Unit,
)
from cre_mcp.truth.parsers.base import Cell, ParsedDoc, Table

# (canonical field, keyword tuple, unit). Order = priority (specific first).
_LABELS: tuple[tuple[str, tuple[str, ...], Unit], ...] = (
    ("noi", ("net operating income", "noi"), "usd"),
    ("effective_gross_income", ("effective gross income", "egi"), "usd"),
    ("gross_potential_rent", (
        "gross potential rent", "gross scheduled rent", "potential gross income",
        "scheduled gross income", "gross rental income", "gross potential income",
        "gross income", "gpr", "gsi",
    ), "usd"),
    ("management_fee", ("management fee", "property management", "management"), "usd"),
    ("replacement_reserves", ("replacement reserves", "capital reserves", "reserves"), "usd"),
    ("real_estate_taxes", (
        "real estate taxes", "real estate tax", "property taxes", "property tax", "taxes",
    ), "usd"),
    ("insurance", ("insurance",), "usd"),
    ("operating_expenses", (
        "total operating expenses", "operating expenses", "total expenses", "opex",
    ), "usd"),
    ("other_income", ("other income", "additional income", "ancillary income"), "usd"),
    ("vacancy_rate", (
        "vacancy rate", "vacancy factor", "economic vacancy", "physical vacancy",
    ), "pct"),
    ("cap_rate", ("cap rate", "capitalization rate"), "pct"),
    ("price", (
        "asking price", "list price", "purchase price", "offering price", "sale price",
    ), "usd"),
    ("rentable_sf", (
        "rentable square feet", "rentable sf", "net rentable area", "gross leasable area",
        "building size", "building sf", "total sf", "gla",
    ), "sqft"),
)

_PROFORMA = re.compile(r"\b(pro\s*forma|proforma|projected|stabilized|budgeted)\b", re.I)
_MONTHLY = re.compile(r"\b(per month|/mo\b|monthly)\b", re.I)

_MONEY = re.compile(r"\(?\$?\s*-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\(?\$?\s*-?\d+(?:\.\d{1,2})?\)?")
_PCT = re.compile(r"-?\d+(?:\.\d+)?\s*%")
_SF = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")


def _to_money(text: str) -> float | None:
    m = _MONEY.search(text)
    if not m:
        return None
    tok = m.group(0)
    neg = tok.strip().startswith("(") and tok.strip().endswith(")")
    tok = tok.replace("(", "").replace(")", "").replace("$", "").replace(",", "").strip()
    try:
        val = float(tok)
    except ValueError:
        return None
    return -val if neg else val


def _to_pct(text: str) -> float | None:
    m = _PCT.search(text)
    if not m:
        return None
    try:
        val = float(m.group(0).replace("%", "").strip())
    except ValueError:
        return None
    return val / 100.0 if val > 1 else val  # "5.25%" -> 0.0525; "0.0525" left as-is


def _to_sf(text: str) -> float | None:
    m = _SF.search(text.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _match_field(label: str) -> tuple[str, Unit] | None:
    low = label.lower()
    for field, keywords, unit in _LABELS:
        if any(kw in low for kw in keywords):
            return field, unit
    return None


def _confidence(method: ExtractionMethod, *, proforma: bool) -> float:
    base = {
        ExtractionMethod.XLSX_CELL: 1.0,
        ExtractionMethod.CSV_CELL: 1.0,
        ExtractionMethod.PDF_TABLE: 0.9,
        ExtractionMethod.PDF_TEXT_REGEX: 0.7,
        ExtractionMethod.LLM_ASSISTED: 0.3,
        ExtractionMethod.MANUAL: 1.0,
    }[method]
    return round(base * 0.5, 3) if proforma else base


def _normalize(unit: Unit, raw: str) -> tuple[float | None, Unit]:
    if unit == "pct":
        return _to_pct(raw), "pct"
    if unit == "sqft":
        return _to_sf(raw), "sqft"
    val = _to_money(raw)
    if val is not None and _MONTHLY.search(raw):
        return val, "usd_per_month"
    return val, unit


def _table_method(ext: str) -> ExtractionMethod:
    return {
        "xlsx": ExtractionMethod.XLSX_CELL,
        "csv": ExtractionMethod.CSV_CELL,
        "pdf": ExtractionMethod.PDF_TABLE,
    }.get(ext, ExtractionMethod.PDF_TABLE)


def _row_text(cells: list[Cell]) -> str:
    return " ".join(c.value for c in cells if c.value).strip()


def _last_value_cell(cells: list[Cell]) -> Cell | None:
    """The rightmost cell that parses as a number — the amount on a statement row."""
    for cell in reversed(cells):
        if _MONEY.search(cell.value) or _PCT.search(cell.value):
            return cell
    return None


def extract_claims(
    doc: ParsedDoc,
    *,
    document_id: str,
    doc_kind: DocKind,
    source_channel: SourceChannel = "uploaded",
    origin: str | None = None,
) -> list[FieldClaim]:
    """Extract every recognizable field claim from a parsed document."""
    claims: list[FieldClaim] = []
    method = _table_method(doc.ext)

    for table in doc.tables:
        claims.extend(
            _extract_from_table(
                table, method=method, document_id=document_id, doc_kind=doc_kind,
                source_channel=source_channel, origin=origin,
            )
        )

    claims.extend(
        _extract_from_text(
            doc, document_id=document_id, doc_kind=doc_kind,
            source_channel=source_channel, origin=origin,
        )
    )
    return _dedupe(claims)


def _extract_from_table(
    table: Table, *, method: ExtractionMethod, document_id: str, doc_kind: DocKind,
    source_channel: SourceChannel, origin: str | None,
) -> list[FieldClaim]:
    claims: list[FieldClaim] = []
    for cells in table.rows:
        if not cells:
            continue
        line = _row_text(cells)
        matched = _match_field(line)
        if matched is None:
            continue
        field, unit = matched
        value_cell = _last_value_cell(cells)
        if value_cell is None:
            continue
        value, out_unit = _normalize(unit, value_cell.value)
        if value is None:
            continue
        proforma = bool(_PROFORMA.search(line))
        conf = _confidence(method, proforma=proforma)
        lineage = Lineage(
            document_id=document_id, doc_kind=doc_kind, source_channel=source_channel,
            cell=value_cell.ref, page=value_cell.page, raw_text=line[:300],
            extraction_method=method, origin=origin,
        )
        flags = ["proforma_not_actual"] if proforma else []
        claims.append(
            FieldClaim(
                field=field,
                figure=ExtractedFigure(value=value, unit=out_unit, confidence=conf, lineage=lineage),
                flags=flags,
            )
        )
    return claims


def _extract_from_text(
    doc: ParsedDoc, *, document_id: str, doc_kind: DocKind,
    source_channel: SourceChannel, origin: str | None,
) -> list[FieldClaim]:
    claims: list[FieldClaim] = []
    for page in doc.pages:
        for line in page.text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            matched = _match_field(stripped)
            if matched is None:
                continue
            field, unit = matched
            value, out_unit = _normalize(unit, stripped)
            if value is None:
                continue
            proforma = bool(_PROFORMA.search(stripped))
            conf = _confidence(ExtractionMethod.PDF_TEXT_REGEX, proforma=proforma)
            lineage = Lineage(
                document_id=document_id, doc_kind=doc_kind, source_channel=source_channel,
                page=page.number, raw_text=stripped[:300],
                extraction_method=ExtractionMethod.PDF_TEXT_REGEX, origin=origin,
            )
            claims.append(
                FieldClaim(
                    field=field,
                    figure=ExtractedFigure(value=value, unit=out_unit, confidence=conf, lineage=lineage),
                    flags=["proforma_not_actual"] if proforma else [],
                )
            )
    return claims


def _dedupe(claims: list[FieldClaim]) -> list[FieldClaim]:
    """Keep the highest-confidence claim per (field, subject, value)."""
    best: dict[tuple[str, str | None, float | str | None], FieldClaim] = {}
    for claim in claims:
        key = (claim.field, claim.subject, claim.figure.value)
        current = best.get(key)
        if current is None or claim.figure.confidence > current.figure.confidence:
            best[key] = claim
    return list(best.values())


__all__ = ["extract_claims"]
