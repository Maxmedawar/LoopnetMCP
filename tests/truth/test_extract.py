"""Extraction tests: recognized fields become cited claims with the right confidence."""

from cre_mcp.truth.extract import extract_claims
from cre_mcp.truth.models import DocKind
from cre_mcp.truth.parsers import parse_bytes

T12_CSV = (
    b"Line Item,Amount\n"
    b"Gross Potential Rent,250000\n"
    b"Vacancy Rate,5%\n"
    b"Other Income,8000\n"
    b"Management Fee,12000\n"
    b"Real Estate Taxes,18000\n"
    b"Total Operating Expenses,70000\n"
    b"Net Operating Income,180000\n"
    b'"Pro Forma Net Operating Income",300000\n'
)


def _claims():
    doc = parse_bytes(T12_CSV, ext_hint=".csv")
    return extract_claims(
        doc, document_id="sha-test", doc_kind=DocKind.T12, source_channel="uploaded",
        origin="statement.csv",
    )


def _by_field(claims, field):
    return [c for c in claims if c.field == field]


def test_extracts_core_statement_fields_with_lineage():
    claims = _claims()
    fields = {c.field for c in claims}
    assert {"gross_potential_rent", "operating_expenses", "noi", "real_estate_taxes"} <= fields

    noi = [c for c in _by_field(claims, "noi") if c.figure.value == 180000.0][0]
    assert noi.figure.confidence == 1.0  # csv cell
    assert noi.figure.lineage.cell == "B8"
    assert noi.figure.lineage.document_id == "sha-test"
    assert noi.figure.unit == "usd"


def test_percent_and_money_units_normalized():
    claims = _claims()
    vac = _by_field(claims, "vacancy_rate")[0]
    assert vac.figure.unit == "pct"
    assert abs(vac.figure.value - 0.05) < 1e-9

    gpr = [c for c in _by_field(claims, "gross_potential_rent")][0]
    assert gpr.figure.value == 250000.0


def test_proforma_is_flagged_and_penalized():
    claims = _claims()
    proforma = [c for c in _by_field(claims, "noi") if c.figure.value == 300000.0]
    assert proforma, "pro forma NOI should be extracted as its own claim"
    assert "proforma_not_actual" in proforma[0].flags
    assert proforma[0].figure.confidence == 0.5  # 1.0 * 0.5 penalty


def test_pdf_table_confidence_is_below_spreadsheet(monkeypatch):
    from cre_mcp.truth.parsers.base import Cell, ParsedDoc, Table

    table = Table(page=1, rows=[[
        Cell(ref="p1:r1c1", value="Net Operating Income", row=1, col=1, page=1),
        Cell(ref="p1:r1c2", value="$412,500", row=1, col=2, page=1),
    ]])
    doc = ParsedDoc(sha256="x", ext="pdf", tables=[table], n_pages=1)
    claims = extract_claims(doc, document_id="d", doc_kind=DocKind.OM)
    noi = _by_field(claims, "noi")[0]
    assert noi.figure.value == 412500.0
    assert noi.figure.confidence == 0.9  # pdf_table
    assert noi.figure.lineage.page == 1
