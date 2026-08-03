"""Build the NOI bridge and fatal-flaw report from a Reconciliation.

The bridge restates the same asset three ways — seller-stated -> verified ->
lender-stressed — and walks the dollar movement between them, every line cited.
The report turns unresolved conflicts, pro-forma-as-actual, seller overstatement,
and missing documents into an explicit proceed / conditions / re-trade / kill
verdict. Numbers here are honest: the lender column applies clearly-labeled
heuristic floors, and anything only an OM asserts is called out as unverified.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from cre_mcp.truth.models import DocKind
from cre_mcp.truth.reconcile import Conflict, Reconciliation

# Lender-style stress floors (labeled, not hidden).
_VACANCY_FLOOR = 0.05
_EXPENSE_RATIO_FLOOR = 0.35
_RESERVE_RATIO = 0.03

_SELLER_DOCS = {DocKind.OM, DocKind.T12, DocKind.RENT_ROLL, DocKind.LISTING}
_UNVERIFIED_DOCS = {DocKind.OM, DocKind.LISTING, DocKind.UNKNOWN}


class NOIColumn(BaseModel):
    label: str
    gpr: float | None = None
    vacancy_rate: float | None = None
    effective_gross_income: float | None = None
    total_opex: float | None = None
    noi: float | None = None
    cap_rate_at_ask: float | None = None
    confidence: float = 0.0
    method_notes: list[str] = Field(default_factory=list)


class NOIBridge(BaseModel):
    deal_id: str
    columns: dict[str, NOIColumn]
    noi_walk: list[dict] = Field(default_factory=list)
    overall_confidence: float = 0.0
    unresolved_conflicts: list[Conflict] = Field(default_factory=list)
    generated_at: str


class MissingDoc(BaseModel):
    doc_kind: str
    needed_for: str
    severity: Literal["blocker", "recommended"]


class FatalFlaw(BaseModel):
    code: str
    severity: Literal["fatal", "material", "warning"]
    noi_impact_usd: float | None = None
    explanation: str
    evidence: list[str] = Field(default_factory=list)


class FatalFlawReport(BaseModel):
    deal_id: str
    verdict: Literal["proceed", "proceed_with_conditions", "re_trade", "kill"]
    fatal_flaws: list[FatalFlaw]
    missing_documents: list[MissingDoc]
    unverified_fields: list[str]
    seller_to_verified_noi_delta: float | None
    documents_ingested: list[str]
    confidence: float
    summary: str


def _num(recon: Reconciliation, field: str):
    for r in recon.resolutions:
        if r.field == field and r.subject is None and isinstance(r.value, (int, float)):
            return r
    return None


def _v(recon: Reconciliation, field: str) -> float | None:
    r = _num(recon, field)
    return float(r.value) if r is not None else None


def _egi(gpr: float | None, vac: float | None, other: float | None) -> float | None:
    if gpr is None:
        return None
    return gpr * (1 - (vac or 0.0)) + (other or 0.0)


def _opex(recon: Reconciliation) -> float | None:
    total = _v(recon, "operating_expenses")
    if total is not None:
        return total
    parts = [
        _v(recon, "management_fee"),
        _v(recon, "real_estate_taxes"),
        _v(recon, "insurance"),
        _v(recon, "replacement_reserves"),
    ]
    present = [p for p in parts if p is not None]
    return sum(present) if present else None


def build_bridge(recon: Reconciliation, *, price: float | None = None) -> NOIBridge:
    gpr = _v(recon, "gross_potential_rent")
    vac = _v(recon, "vacancy_rate")
    other = _v(recon, "other_income")
    opex = _opex(recon)
    direct_noi = _num(recon, "noi")

    def cap(noi: float | None) -> float | None:
        if noi is None or not price:
            return None
        return round(noi / price, 4)

    # --- seller-stated: as presented (direct NOI if any, incl. pro forma) ---
    egi_s = _egi(gpr, vac, other)
    computed_s = (egi_s - opex) if (egi_s is not None and opex is not None) else None
    noi_s = direct_noi.value if direct_noi is not None else computed_s
    seller = NOIColumn(
        label="seller_stated", gpr=gpr, vacancy_rate=vac, effective_gross_income=egi_s,
        total_opex=opex, noi=noi_s, cap_rate_at_ask=cap(noi_s),
        confidence=round(min((r.confidence for r in recon.resolutions), default=0.0), 3),
        method_notes=["As presented by the seller's documents."],
    )

    # --- verified: recompute bottom-up; drop a pro-forma direct NOI ---
    proforma_noi = direct_noi is not None and direct_noi.conflict is not None and (
        direct_noi.conflict.rule == "proforma_as_actual"
    )
    noi_v = computed_s if computed_s is not None else (None if proforma_noi else noi_s)
    notes_v: list[str] = []
    if proforma_noi:
        notes_v.append("Seller's headline NOI was pro forma; recomputed from components.")
    if computed_s is None and noi_v is not None:
        notes_v.append("No rent/expense breakdown provided; using stated NOI unverified.")
    unverified = _unverified_fields(recon)
    if unverified:
        notes_v.append("Unverified (no source above an OM): " + ", ".join(unverified))
    verified = NOIColumn(
        label="verified", gpr=gpr, vacancy_rate=vac, effective_gross_income=egi_s,
        total_opex=opex, noi=noi_v, cap_rate_at_ask=cap(noi_v),
        confidence=_verified_confidence(recon), method_notes=notes_v or ["Bottom-up recompute."],
    )

    # --- lender: stress floors (labeled) ---
    vac_l = max(vac or 0.0, _VACANCY_FLOOR)
    egi_l = _egi(gpr, vac_l, other)
    opex_l = None
    if egi_l is not None:
        base = opex if opex is not None else 0.0
        floored = max(base, _EXPENSE_RATIO_FLOOR * egi_l)
        reserves_add = 0.0 if _v(recon, "replacement_reserves") else _RESERVE_RATIO * egi_l
        opex_l = floored + reserves_add
    noi_l = (egi_l - opex_l) if (egi_l is not None and opex_l is not None) else None
    lender = NOIColumn(
        label="lender", gpr=gpr, vacancy_rate=vac_l, effective_gross_income=egi_l,
        total_opex=opex_l, noi=noi_l, cap_rate_at_ask=cap(noi_l),
        confidence=round((verified.confidence or 0.0) * 0.9, 3),
        method_notes=[
            f"Lender-style floors: vacancy>={_VACANCY_FLOOR:.0%}, expense ratio"
            f">={_EXPENSE_RATIO_FLOOR:.0%}, reserves +{_RESERVE_RATIO:.0%} of EGI.",
        ],
    )

    walk = _noi_walk(seller, verified, lender, proforma_noi=proforma_noi)
    overall = round(min(seller.confidence, verified.confidence) if noi_v is not None else 0.0, 3)
    return NOIBridge(
        deal_id=recon.deal_id,
        columns={"seller_stated": seller, "verified": verified, "lender": lender},
        noi_walk=walk,
        overall_confidence=overall,
        unresolved_conflicts=[c for c in recon.conflicts if c.needs_human_review],
        generated_at=datetime.now(UTC).isoformat(),
    )


def _noi_walk(seller: NOIColumn, verified: NOIColumn, lender: NOIColumn, *, proforma_noi: bool) -> list[dict]:
    walk: list[dict] = []
    if seller.noi is not None and verified.noi is not None and seller.noi != verified.noi:
        walk.append({
            "step": "seller -> verified",
            "amount": round(verified.noi - seller.noi, 2),
            "reason": "Removed pro-forma headline; recomputed from cited components."
            if proforma_noi else "Recomputed from verified components.",
        })
    if verified.noi is not None and lender.noi is not None and verified.noi != lender.noi:
        walk.append({
            "step": "verified -> lender",
            "amount": round(lender.noi - verified.noi, 2),
            "reason": "Applied lender vacancy/expense/reserve floors.",
        })
    return walk


def _unverified_fields(recon: Reconciliation) -> list[str]:
    out = []
    for r in recon.resolutions:
        if r.lineage.doc_kind in _UNVERIFIED_DOCS and not r.corroborating_docs:
            out.append(r.field)
    return sorted(set(out))


def _verified_confidence(recon: Reconciliation) -> float:
    core = [r for r in recon.resolutions if r.field in {"noi", "gross_potential_rent", "operating_expenses"}]
    if not core:
        return 0.0
    return round(sum(r.confidence for r in core) / len(core), 3)


def build_report(recon: Reconciliation, bridge: NOIBridge) -> FatalFlawReport:
    flaws: list[FatalFlaw] = []

    seller_noi = bridge.columns["seller_stated"].noi
    verified_noi = bridge.columns["verified"].noi
    delta = None
    if seller_noi is not None and verified_noi is not None:
        delta = round(verified_noi - seller_noi, 2)
        if seller_noi > 0 and (seller_noi - verified_noi) / seller_noi > 0.10:
            flaws.append(FatalFlaw(
                code="SELLER_NOI_OVERSTATED",
                severity="material",
                noi_impact_usd=delta,
                explanation=f"Seller NOI {seller_noi:,.0f} exceeds verified {verified_noi:,.0f} "
                            f"by {(seller_noi - verified_noi) / seller_noi:.0%}.",
            ))

    for conflict in recon.conflicts:
        if conflict.rule == "proforma_as_actual":
            flaws.append(FatalFlaw(
                code="PROFORMA_AS_ACTUAL", severity="material",
                explanation=conflict.explanation, evidence=[conflict.field],
            ))
        elif conflict.severity == "material":
            flaws.append(FatalFlaw(
                code="MATERIAL_CONFLICT", severity="material",
                explanation=conflict.explanation, evidence=[conflict.field],
            ))

    present = set(recon.doc_kinds_present)
    missing: list[MissingDoc] = []
    if DocKind.LEASE.value not in present and DocKind.AMENDMENT.value not in present:
        missing.append(MissingDoc(doc_kind="lease", needed_for="verify base rent + guaranty", severity="blocker"))
    if DocKind.T12.value not in present:
        missing.append(MissingDoc(doc_kind="t12_operating_statement", needed_for="verify actual income/expenses", severity="blocker"))
    if DocKind.TAX_BILL.value not in present:
        missing.append(MissingDoc(doc_kind="tax_bill", needed_for="tax-reassessment-on-sale risk", severity="recommended"))
    if DocKind.ESTOPPEL.value not in present:
        missing.append(MissingDoc(doc_kind="estoppel_certificate", needed_for="tenant-certified lease terms", severity="recommended"))

    unverified = _unverified_fields(recon)
    verdict = _verdict(flaws, missing)
    confidence = bridge.overall_confidence
    summary = _summary(verdict, flaws, missing, delta)

    return FatalFlawReport(
        deal_id=recon.deal_id,
        verdict=verdict,
        fatal_flaws=flaws,
        missing_documents=missing,
        unverified_fields=unverified,
        seller_to_verified_noi_delta=delta,
        documents_ingested=recon.doc_kinds_present,
        confidence=confidence,
        summary=summary,
    )


def _verdict(flaws: list[FatalFlaw], missing: list[MissingDoc]) -> str:
    if any(f.severity == "fatal" for f in flaws):
        return "kill"
    if any(f.code == "SELLER_NOI_OVERSTATED" for f in flaws):
        return "re_trade"
    if any(f.severity == "material" for f in flaws) or any(m.severity == "blocker" for m in missing):
        return "proceed_with_conditions"
    return "proceed"


def _summary(verdict: str, flaws: list[FatalFlaw], missing: list[MissingDoc], delta: float | None) -> str:
    parts = [f"Verdict: {verdict}."]
    if flaws:
        parts.append(f"{len(flaws)} flaw(s): " + "; ".join(f.code for f in flaws) + ".")
    blockers = [m for m in missing if m.severity == "blocker"]
    if blockers:
        parts.append("Blocking docs missing: " + ", ".join(m.doc_kind for m in blockers) + ".")
    if delta is not None and delta < 0:
        parts.append(f"Verified NOI is {abs(delta):,.0f} below seller-stated.")
    return " ".join(parts)


__all__ = [
    "NOIColumn", "NOIBridge", "MissingDoc", "FatalFlaw", "FatalFlawReport",
    "build_bridge", "build_report",
]
