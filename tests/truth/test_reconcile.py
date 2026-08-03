"""Reconciliation tests: authority wins, conflicts kept, nothing averaged."""

from cre_mcp.truth.models import DocKind, ExtractedFigure, ExtractionMethod, FieldClaim, Lineage
from cre_mcp.truth.reconcile import resolve


def _claim(field, value, doc_kind, *, conf=1.0, flags=None, doc_id="d", method=ExtractionMethod.XLSX_CELL):
    return FieldClaim(
        field=field,
        figure=ExtractedFigure(
            value=value, unit="usd", confidence=conf,
            lineage=Lineage(document_id=doc_id, doc_kind=doc_kind, extraction_method=method, raw_text=""),
        ),
        flags=flags or [],
    )


def _res(recon, field):
    return next(r for r in recon.resolutions if r.field == field)


def test_higher_authority_wins_and_conflict_is_kept_not_averaged():
    claims = [
        _claim("noi", 200000, DocKind.T12, doc_id="t12"),
        _claim("noi", 150000, DocKind.OM, doc_id="om"),
    ]
    recon = resolve("x:1", claims)
    noi = _res(recon, "noi")
    assert noi.value == 200000  # T12 (authority 50) beats OM (30)
    assert noi.value != 175000  # NOT the average
    assert noi.conflict is not None
    assert noi.conflict.rule == "source_disagreement"
    assert noi.conflict.severity == "material"  # 25% gap
    assert noi.conflict.resolved_value == 200000
    assert len(noi.conflict.claims) == 2  # both values retained for review
    assert noi.conflict.needs_human_review is True


def test_corroboration_bumps_confidence_without_conflict():
    claims = [
        _claim("gross_potential_rent", 250000, DocKind.RENT_ROLL, conf=0.9, doc_id="rr"),
        _claim("gross_potential_rent", 251000, DocKind.T12, conf=0.9, doc_id="t12"),  # within 2%
    ]
    recon = resolve("x:1", claims)
    gpr = _res(recon, "gross_potential_rent")
    assert gpr.conflict is None
    assert gpr.corroborating_docs  # the other doc corroborates
    assert gpr.confidence > 0.9


def test_proforma_headline_flagged_material():
    claims = [_claim("noi", 300000, DocKind.OM, flags=["proforma_not_actual"], doc_id="om")]
    recon = resolve("x:1", claims)
    noi = _res(recon, "noi")
    assert noi.conflict is not None
    assert noi.conflict.rule == "proforma_as_actual"
    assert noi.conflict.severity == "material"


def test_single_agreeing_source_has_no_conflict():
    claims = [_claim("operating_expenses", 70000, DocKind.T12, doc_id="t12")]
    recon = resolve("x:1", claims)
    assert _res(recon, "operating_expenses").conflict is None
    assert recon.conflicts == []
