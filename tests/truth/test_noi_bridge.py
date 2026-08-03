"""NOI bridge + fatal-flaw verdict tests."""

from cre_mcp.truth.models import DocKind, ExtractedFigure, ExtractionMethod, FieldClaim, Lineage
from cre_mcp.truth.noi_bridge import build_bridge, build_report
from cre_mcp.truth.reconcile import resolve


def _claim(field, value, doc_kind, *, unit="usd", flags=None, doc_id="d"):
    return FieldClaim(
        field=field,
        figure=ExtractedFigure(
            value=value, unit=unit, confidence=1.0,
            lineage=Lineage(document_id=doc_id, doc_kind=doc_kind,
                            extraction_method=ExtractionMethod.PDF_TEXT_REGEX, raw_text=""),
        ),
        flags=flags or [],
    )


def test_proforma_om_deal_retrades_and_walks_noi_down():
    claims = [
        _claim("gross_potential_rent", 250000, DocKind.OM, doc_id="om"),
        _claim("operating_expenses", 70000, DocKind.OM, doc_id="om"),
        _claim("noi", 300000, DocKind.OM, flags=["proforma_not_actual"], doc_id="om"),
    ]
    recon = resolve("crexi:1", claims)
    bridge = build_bridge(recon, price=4_000_000)
    report = build_report(recon, bridge)

    assert bridge.columns["seller_stated"].noi == 300000  # what they pitched (pro forma)
    assert bridge.columns["verified"].noi == 180000  # recomputed 250k - 70k
    # NOI walked DOWN from seller to verified
    steps = {s["step"]: s["amount"] for s in bridge.noi_walk}
    assert steps["seller -> verified"] == -120000
    # lender column stresses further below verified
    assert bridge.columns["lender"].noi < 180000

    assert report.verdict == "re_trade"
    assert report.seller_to_verified_noi_delta == -120000
    codes = {f.code for f in report.fatal_flaws}
    assert "SELLER_NOI_OVERSTATED" in codes
    assert "PROFORMA_AS_ACTUAL" in codes
    missing = {m.doc_kind for m in report.missing_documents}
    assert {"lease", "t12_operating_statement"} <= missing


def test_clean_t12_deal_proceeds_with_conditions_when_lease_missing():
    claims = [
        _claim("gross_potential_rent", 250000, DocKind.T12, doc_id="t12"),
        _claim("operating_expenses", 70000, DocKind.T12, doc_id="t12"),
        _claim("noi", 180000, DocKind.T12, doc_id="t12"),
    ]
    recon = resolve("crexi:2", claims)
    bridge = build_bridge(recon, price=3_000_000)
    report = build_report(recon, bridge)

    assert bridge.columns["verified"].noi == 180000
    assert report.seller_to_verified_noi_delta == 0
    assert "SELLER_NOI_OVERSTATED" not in {f.code for f in report.fatal_flaws}
    # T12 present but no lease -> conditions, not a clean proceed
    assert report.verdict == "proceed_with_conditions"
    assert bridge.columns["verified"].cap_rate_at_ask == round(180000 / 3_000_000, 4)


def test_unverified_fields_called_out_for_om_only():
    claims = [_claim("noi", 180000, DocKind.OM, doc_id="om")]
    recon = resolve("crexi:3", claims)
    bridge = build_bridge(recon)
    assert any("Unverified" in note for note in bridge.columns["verified"].method_notes)
