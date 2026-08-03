"""Plain analytics function boundaries; intentionally not FastMCP-registered."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cre_mcp.source_rights.output import safe_error_message

from .costseg import cost_seg_preview as _cost_seg_preview
from .envelope import zoning_envelope as _zoning_envelope
from .lp_exposure import lp_portfolio_exposure as _lp_portfolio_exposure
from .model_forensics import audit_seller_model as _audit_seller_model
from .regburden import regulatory_burden as _regulatory_burden
from .trends import trend_bands as _trend_bands
from .workflows import cam_true_up as _cam_true_up
from .workflows import owner_report as _owner_report


def _error(name: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    return {
        "error": safe_error_message(
            f"{name}: {message or exc.__class__.__name__}"
        )
    }


def audit_seller_model(xlsx_path: str | Path | None) -> dict[str, Any]:
    try:
        return _audit_seller_model(xlsx_path)
    except Exception as exc:
        return _error("audit_seller_model", exc)


def cost_seg_preview(
    purchase_price: Any,
    land_pct: Any,
    components: Sequence[Mapping[str, Any]] | None = None,
    asset_type: str | None = None,
    bonus_rate: Any = 0.0,
    apply_bonus: bool = False,
) -> dict[str, Any]:
    try:
        return _cost_seg_preview(
            purchase_price, land_pct, components, asset_type, bonus_rate, apply_bonus
        )
    except Exception as exc:
        return _error("cost_seg_preview", exc)


def trend_bands(
    series: Sequence[Mapping[str, Any]] | None,
    horizon: int | None,
) -> dict[str, Any]:
    try:
        return _trend_bands(series, horizon)
    except Exception as exc:
        return _error("trend_bands", exc)


def regulatory_burden(jurisdictions: Sequence[str] | None) -> dict[str, Any]:
    try:
        return _regulatory_burden(jurisdictions)
    except Exception as exc:
        return _error("regulatory_burden", exc)


def zoning_envelope(code_params: Mapping[str, Any] | None) -> dict[str, Any]:
    try:
        return _zoning_envelope(code_params)
    except Exception as exc:
        return _error("zoning_envelope", exc)


def lp_portfolio_exposure(
    positions: Sequence[Mapping[str, Any]] | None,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return _lp_portfolio_exposure(positions, thresholds)
    except Exception as exc:
        return _error("lp_portfolio_exposure", exc)


def cam_true_up(
    tenancy: str | Mapping[str, Any],
    recovery_terms: Any = None,
    actual_costs: Mapping[str, Any] | None = None,
    period: str | None = None,
    estimated_billed_cents: int | None = None,
    tenant_sf: float | int | None = None,
    total_sf: float | int | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        return _cam_true_up(
            tenancy,
            recovery_terms,
            actual_costs,
            period,
            estimated_billed_cents,
            tenant_sf,
            total_sf,
            db_path,
        )
    except Exception as exc:
        return _error("cam_true_up", exc)


def owner_report(
    period: str,
    deal_id: str,
    budget: Mapping[str, Any] | None = None,
    actuals: Mapping[str, Any] | None = None,
    initiative_actuals: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        return _owner_report(
            period, deal_id, budget, actuals, initiative_actuals, db_path
        )
    except Exception as exc:
        return _error("owner_report", exc)


__all__ = [
    "audit_seller_model",
    "cam_true_up",
    "cost_seg_preview",
    "lp_portfolio_exposure",
    "owner_report",
    "regulatory_burden",
    "trend_bands",
    "zoning_envelope",
]
