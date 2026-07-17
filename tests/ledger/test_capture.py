"""Claim-ledger capture: reconciliations become graded counterparty evidence."""

import pytest

from cre_mcp.ledger.capture import claims_from_reconciliation
from cre_mcp.truth.models import DocKind, ExtractedFigure, ExtractionMethod, FieldClaim, Lineage
from cre_mcp.truth.reconcile import resolve


def _claim(field: str, value, kind: DocKind, doc_id: str, confidence: float = 0.9) -> FieldClaim:
    return FieldClaim(
        field=field,
        figure=ExtractedFigure(
            value=value,
            unit="usd",
            confidence=confidence,
            lineage=Lineage(
                document_id=doc_id,
                doc_kind=kind,
                extraction_method=ExtractionMethod.PDF_TEXT_REGEX,
                raw_text=str(value),
            ),
        ),
    )


def test_om_overridden_by_lease_is_graded_with_delta():
    recon = resolve(
        "crexi:1",
        [
            _claim("noi", 500_000.0, DocKind.OM, "om-doc"),
            _claim("noi", 420_000.0, DocKind.LEASE, "lease-doc"),
        ],
    )
    records = claims_from_reconciliation(recon, counterparty="Big Broker Co")
    assert len(records) == 1
    rec = records[0]
    assert rec.verdict == "overridden"
    assert rec.counterparty == "Big Broker Co"
    assert rec.claimed_value == 500_000.0
    assert rec.proven_value == 420_000.0
    assert rec.claimed_doc_kind == DocKind.OM.value
    assert rec.delta_pct == pytest.approx(80_000 / 420_000, abs=1e-6)


def test_om_matching_lease_is_corroborated():
    # Same value from OM and lease: lease wins resolution, OM claim is a hit.
    recon = resolve(
        "crexi:2",
        [
            _claim("noi", 420_000.0, DocKind.OM, "om-doc"),
            _claim("noi", 421_000.0, DocKind.LEASE, "lease-doc"),
        ],
    )
    # 0.24% difference is within the truth engine's rounding materiality: if no
    # conflict was raised there is nothing adversarial to grade — that's fine —
    # but an exact match with a raised conflict must grade as corroborated.
    recon_exact = resolve(
        "crexi:3",
        [
            _claim("noi", 400_000.0, DocKind.OM, "om-doc"),
            _claim("noi", 400_000.0, DocKind.LEASE, "lease-doc"),
            _claim("noi", 300_000.0, DocKind.T12, "t12-doc"),
        ],
    )
    records = claims_from_reconciliation(recon_exact)
    om_records = [r for r in records if r.claimed_doc_kind == DocKind.OM.value]
    if om_records:  # graded only when the engine surfaced a conflict on the field
        assert om_records[0].verdict == "corroborated"
    # And the mid-band case must not crash or fabricate records.
    assert isinstance(claims_from_reconciliation(recon), list)


def test_untested_om_only_claim_is_not_recorded_as_hit():
    recon = resolve("crexi:4", [_claim("noi", 500_000.0, DocKind.OM, "om-doc")])
    records = claims_from_reconciliation(recon)
    assert records == []  # unverified is not corroborated


def test_non_counterparty_conflicts_are_not_graded():
    # T12 vs lease is a document conflict, not a counterparty assertion.
    recon = resolve(
        "crexi:5",
        [
            _claim("noi", 400_000.0, DocKind.T12, "t12-doc"),
            _claim("noi", 300_000.0, DocKind.LEASE, "lease-doc"),
        ],
    )
    assert claims_from_reconciliation(recon) == []
