"""One-call, audit-oriented CAM true-up and owner reporting workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from cre_mcp.assetmgmt.noi_forecast import variance_explain
from cre_mcp.assetmgmt.tracker import initiative_tracker
from cre_mcp.books.billing import validate_period
from cre_mcp.books.recon import rent_to_cash
from cre_mcp.books.store import BookStore
from cre_mcp.leases.recoveries import (
    RecoveryTerms,
    estimate_recoverable,
    extract_recovery_terms,
)


_TENANCY_FIELDS = frozenset(
    {
        "tenancy_id", "deal_id", "tenant_name", "unit", "lease_ref", "active",
        "tenant_sf", "total_sf", "period", "estimated_billed_cents",
        "billed_cents", "cam_billed_cents", "charges", "recovery_terms",
        "lease_text", "actual_costs",
    }
)
_COST_FIELDS = frozenset({"cam", "cam_cents", "taxes", "insurance"})
_COST_DETAIL_FIELDS = frozenset(
    {
        "current", "amount", "cost", "base", "base_year", "prior", "previous",
        "prior_year", "years_elapsed", "years", "lease_years_elapsed",
        "occupancy_pct", "actual_occupancy_pct", "occupancy", "variable",
        "variable_cost", "variable_expenses", "already_grossed_up",
    }
)


def _message(exc: Exception) -> str:
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


def _text(value: Any, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} cannot be null")
    result = str(value).strip()
    if not result:
        raise ValueError(f"{name} cannot be blank")
    return result


def _cents(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _round_cents(value: Any, name: str) -> int:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{name} must be finite")
    return int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dollars_to_cents(value: Any, name: str) -> int:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return int((number * Decimal("100")).quantize(Decimal("1"), ROUND_HALF_UP))


def _rate(value: Any, name: str) -> Decimal:
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not rate.is_finite() or rate < 0 or rate > 100:
        raise ValueError(f"{name} must be between 0 and 1 or 0 and 100")
    if rate > 1:
        rate /= Decimal("100")
    return rate


def _source_tag(module: str, detail: str, **locator: Any) -> dict[str, Any]:
    return {"module": module, "detail": detail, "read_only": True, **locator}


def _terms(value: Any) -> RecoveryTerms:
    if isinstance(value, RecoveryTerms):
        return value
    if isinstance(value, str):
        return extract_recovery_terms(value)
    if isinstance(value, Mapping):
        unknown = sorted(set(value) - {"lease_text", "terms"})
        if unknown:
            raise ValueError("unrecognized recovery_terms fields: " + ", ".join(unknown))
        nested = value.get("terms")
        if isinstance(nested, RecoveryTerms):
            return nested
        lease_text = value.get("lease_text")
        if isinstance(lease_text, str):
            return extract_recovery_terms(lease_text)
    raise ValueError("recovery_terms must be RecoveryTerms, lease text, or a mapping with lease_text/terms")


def _costs(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("actual_costs must be a mapping")
    unknown = [f"actual_costs.{key}" for key in value if key not in _COST_FIELDS]
    for key, detail in value.items():
        if key in _COST_FIELDS and isinstance(detail, Mapping):
            unknown.extend(
                f"actual_costs.{key}.{field}"
                for field in detail
                if field not in _COST_DETAIL_FIELDS
            )
    if unknown:
        raise ValueError("unrecognized input fields: " + ", ".join(sorted(unknown)))
    result = dict(value)
    if "cam_cents" in result:
        if "cam" in result and result["cam"] != result["cam_cents"]:
            raise ValueError("actual_costs.cam and actual_costs.cam_cents conflict")
        result["cam"] = result.pop("cam_cents")
    if "cam" not in result:
        raise ValueError("actual_costs.cam or actual_costs.cam_cents is required")
    return result


def _structured_billed(
    tenancy: Mapping[str, Any], period: str | None, explicit: int | None
) -> tuple[int | None, list[dict[str, Any]], str]:
    for source, raw in (
        ("argument estimated_billed_cents", explicit),
        ("tenancy.estimated_billed_cents", tenancy.get("estimated_billed_cents")),
        ("tenancy.cam_billed_cents", tenancy.get("cam_billed_cents")),
        ("tenancy.billed_cents", tenancy.get("billed_cents")),
    ):
        if raw is not None:
            return _cents(raw, source), [], source
    raw_charges = tenancy.get("charges")
    if raw_charges is None:
        return None, [], "unavailable"
    if not isinstance(raw_charges, Sequence) or isinstance(raw_charges, (str, bytes)):
        raise ValueError("tenancy.charges must be a sequence")
    included: list[dict[str, Any]] = []
    total = 0
    for index, charge in enumerate(raw_charges):
        if not isinstance(charge, Mapping):
            raise ValueError(f"tenancy.charges[{index}] must be a mapping")
        unknown = sorted(set(charge) - {"charge_id", "kind", "period", "amount_cents"})
        if unknown:
            raise ValueError(
                f"unrecognized input fields: tenancy.charges[{index}]." + ", ".join(unknown)
            )
        if str(charge.get("kind", "")).casefold() != "cam":
            continue
        if period is not None and charge.get("period") != period:
            continue
        amount = _cents(charge.get("amount_cents"), f"tenancy.charges[{index}].amount_cents")
        total += amount
        included.append({"charge_id": charge.get("charge_id"), "amount_cents": amount})
    return total, included, "tenancy.charges CAM sum"


def _cam_true_up(
    tenancy: str | Mapping[str, Any] | None,
    recovery_terms: RecoveryTerms | str | Mapping[str, Any] | None,
    actual_costs: Mapping[str, Any] | None,
    period: str | None,
    estimated_billed_cents: int | None,
    tenant_sf: float | int | None,
    total_sf: float | int | None,
    db_path: str | Path | None,
) -> dict[str, Any]:
    if tenancy is None:
        raise ValueError("tenancy is required")
    books = BookStore(db_path)
    if isinstance(tenancy, str):
        record = books.get_tenancy(tenancy)
        unrecognized: list[str] = []
    elif isinstance(tenancy, Mapping):
        unknown = sorted(set(tenancy) - _TENANCY_FIELDS)
        unrecognized = [f"tenancy.{field}" for field in unknown]
        if unrecognized:
            return {
                "error": "unrecognized input fields",
                "unrecognized_inputs": unrecognized,
            }
        record = dict(tenancy)
    else:
        raise ValueError("tenancy must be a tenancy_id or structured mapping")

    normalized_period = period if period is not None else record.get("period")
    if normalized_period is not None:
        normalized_period = validate_period(str(normalized_period))
    raw_terms = recovery_terms
    if raw_terms is None:
        raw_terms = record.get("recovery_terms", record.get("lease_text"))
    raw_costs = actual_costs if actual_costs is not None else record.get("actual_costs")
    if not isinstance(raw_costs, Mapping):
        raise ValueError("actual_costs must be a mapping")
    unrecognized.extend(
        f"actual_costs.{key}" for key in raw_costs if key not in _COST_FIELDS
    )
    for key, detail in raw_costs.items():
        if key in _COST_FIELDS and isinstance(detail, Mapping):
            unrecognized.extend(
                f"actual_costs.{key}.{field}"
                for field in detail
                if field not in _COST_DETAIL_FIELDS
            )
    cost_unknown = sorted(
        value for value in set(unrecognized) if value.startswith("actual_costs.")
    )
    if cost_unknown:
        return {
            "error": "cam_true_up: unrecognized input fields: " + ", ".join(cost_unknown),
            "unrecognized_inputs": sorted(set(unrecognized)),
        }
    if "cam_cents" in raw_costs and "cam" in raw_costs:
        raise ValueError("supply actual_costs.cam or actual_costs.cam_cents, not both")
    if "cam_cents" in raw_costs:
        actual_cam_cents = _cents(raw_costs["cam_cents"], "actual_costs.cam_cents")
        lease_costs = {
            key: value for key, value in raw_costs.items()
            if key in {"taxes", "insurance"}
        }
        lease_costs["cam"] = float(Decimal(actual_cam_cents) / Decimal("100"))
    elif "cam" in raw_costs:
        raw_cam = raw_costs["cam"]
        if isinstance(raw_cam, Mapping):
            current = raw_cam.get("current", raw_cam.get("amount", raw_cam.get("cost")))
            if current is None:
                raise ValueError("actual_costs.cam.current is required")
            # Structured lease-recovery cost pools use integer cents at this
            # workflow boundary; translate their monetary leaves to the lease
            # module's documented dollar units.
            actual_cam_cents = _cents(current, "actual_costs.cam.current")
            converted_cam = dict(raw_cam)
            for money_key in (
                "current", "amount", "cost", "base", "base_year", "prior",
                "previous", "prior_year",
            ):
                if money_key in converted_cam and converted_cam[money_key] is not None:
                    converted_cam[money_key] = float(
                        Decimal(_cents(
                            converted_cam[money_key],
                            f"actual_costs.cam.{money_key}",
                        )) / Decimal("100")
                    )
            lease_costs = {
                key: value for key, value in raw_costs.items()
                if key in {"taxes", "insurance"}
            }
            lease_costs["cam"] = converted_cam
        else:
            actual_cam_cents = _dollars_to_cents(raw_cam, "actual_costs.cam")
            lease_costs = {
                key: value for key, value in raw_costs.items()
                if key in {"cam", "taxes", "insurance"}
            }
    else:
        raise ValueError("actual_costs.cam or actual_costs.cam_cents is required")
    resolved_tenant_sf = tenant_sf if tenant_sf is not None else record.get("tenant_sf")
    resolved_total_sf = total_sf if total_sf is not None else record.get("total_sf")
    billed, charge_trace, billed_source = _structured_billed(
        record, normalized_period, estimated_billed_cents
    )
    tenancy_id = record.get("tenancy_id")
    if billed is None and tenancy_id is not None:
        charges = books.list_charges(tenancy_id=str(tenancy_id), period=normalized_period)
        cam_charges = [charge for charge in charges if charge.get("kind") == "cam"]
        billed = sum(int(charge["amount_cents"]) for charge in cam_charges)
        charge_trace = [
            {"charge_id": charge["charge_id"], "amount_cents": charge["amount_cents"]}
            for charge in cam_charges
        ]
        billed_source = "cre_mcp.books.BookStore.list_charges read-only CAM sum"
    if billed is None:
        raise ValueError(
            "estimated_billed_cents, structured billed cents, or a tenancy_id books trace is required"
        )

    estimate: dict[str, Any] | None = None
    structured_fields = {
        "pro_rata_share", "admin_fee_pct", "cam_cap_pct", "cap_base_cents",
        "source", "lease_text", "terms",
    }
    if isinstance(raw_terms, Mapping) and raw_terms.get("pro_rata_share") is not None:
        unrecognized.extend(
            f"recovery_terms.{key}" for key in raw_terms if key not in structured_fields
        )
        share = _rate(raw_terms["pro_rata_share"], "recovery_terms.pro_rata_share")
        admin_rate = (
            Decimal("0") if raw_terms.get("admin_fee_pct") is None
            else _rate(raw_terms["admin_fee_pct"], "recovery_terms.admin_fee_pct")
        )
        tenant_share_cents = _round_cents(
            Decimal(actual_cam_cents) * share, "tenant CAM share"
        )
        admin_cents = _round_cents(
            Decimal(tenant_share_cents) * admin_rate, "CAM admin fee"
        )
        before_cap = tenant_share_cents + admin_cents
        cap_ceiling: int | None = None
        cap_rate: Decimal | None = None
        if raw_terms.get("cam_cap_pct") is not None:
            cap_rate = _rate(raw_terms["cam_cap_pct"], "recovery_terms.cam_cap_pct")
            cap_base = _cents(
                raw_terms.get("cap_base_cents"), "recovery_terms.cap_base_cents"
            )
            cap_ceiling = _round_cents(
                Decimal(cap_base) * (Decimal("1") + cap_rate), "CAM cap ceiling"
            )
        recovery_cents = min(before_cap, cap_ceiling) if cap_ceiling is not None else before_cap
        recovery_math = {
            "tenant_share_cents": tenant_share_cents,
            "admin_fee_cents": admin_cents,
            "recovery_before_cap_cents": before_cap,
            "cap_ceiling_cents": cap_ceiling,
            "cap_reduction_cents": before_cap - recovery_cents,
            "cam_cap_pct": None if cap_rate is None else float(cap_rate),
            "recovery_after_cap_cents": recovery_cents,
            "source": raw_terms.get("source") or "caller-supplied structured terms",
        }
        cap_eligible_cam_cents = actual_cam_cents
        cap_reduction_cents = before_cap - recovery_cents
        recovery_module = "cre_mcp.leases.recoveries structured-term hook"
    else:
        resolved_terms = _terms(raw_terms)
        estimate = estimate_recoverable(
            resolved_terms, lease_costs, resolved_tenant_sf, resolved_total_sf
        )
        cam = estimate["lines"]["cam"]
        recovery = cam.get("estimated_billing")
        if cam.get("status") != "estimated" or recovery is None:
            return {
                "status": "NOT_COMPUTABLE",
                "tenancy_id": tenancy_id,
                "period": normalized_period,
                "recoverable_after_cap_cents": None,
                "estimated_billed_cents": billed,
                "true_up_cents": None,
                "recovery_estimate": estimate,
                "audit_steps": [],
                "missing_inputs": cam.get("missing_inputs", []),
                "unrecognized_inputs": sorted(set(unrecognized)),
            }
        recovery_cents = _dollars_to_cents(recovery, "cam estimated billing")
        annual_cents = _dollars_to_cents(cam.get("annual_cost"), "cam annual cost")
        eligible_cents = _dollars_to_cents(cam.get("eligible_cost"), "cam eligible cost")
        recovery_math = {
            "tenant_share_cents": None,
            "admin_fee_cents": _dollars_to_cents(cam.get("admin_fee", 0), "cam admin fee"),
            "recovery_before_cap_cents": None,
            "cap_ceiling_cents": None,
            "cap_reduction_cents": annual_cents - eligible_cents,
            "recovery_after_cap_cents": recovery_cents,
            "lease_line": cam,
        }
        cap_eligible_cam_cents = eligible_cents
        cap_reduction_cents = annual_cents - eligible_cents
        recovery_module = "cre_mcp.leases.recoveries.estimate_recoverable"

    true_up = recovery_cents - billed
    status = "TENANT_OWES" if true_up > 0 else "TENANT_CREDIT" if true_up < 0 else "SETTLED"
    actual_source = _source_tag("caller", "actual_costs CAM pool")
    recovery_source = _source_tag(recovery_module, "lease-limited CAM recovery math")
    billed_tag = _source_tag("cre_mcp.books", billed_source, charge_trace=charge_trace)
    true_up_source = _source_tag("cre_mcp.analytics.workflows", "step 2 minus step 3")
    admin_cents = int(recovery_math.get("admin_fee_cents") or 0)
    base_recovery_cents = recovery_cents - admin_cents
    def audit_step(
        step: int,
        name: str,
        formula: str,
        result_cents: int | None,
        source: str,
        source_tag: Mapping[str, Any],
        **inputs: Any,
    ) -> dict[str, Any]:
        return {
            "step": step,
            "name": name,
            "label": name.replace("_", " "),
            "formula": formula,
            "result_cents": result_cents,
            "amount_cents": result_cents,
            "source": source,
            "source_tag": dict(source_tag),
            **inputs,
        }
    audit_steps = [
        audit_step(1, "actual_cam_pool", "caller-provided actual CAM cents", actual_cam_cents, "actual_costs.cam", actual_source),
        audit_step(
            2,
            "cap_test",
            "eligible CAM = lease-cap-limited CAM pool",
            cap_eligible_cam_cents,
            recovery_module,
            recovery_source,
            input_cents=actual_cam_cents,
            cap_reduction_cents=cap_reduction_cents,
            math=recovery_math,
        ),
        audit_step(3, "tenant_share", "eligible CAM × cited/derived pro-rata share", base_recovery_cents, recovery_module, recovery_source, tenant_share=recovery_math.get("tenant_share")),
        audit_step(4, "admin_fee", "cited administrative fee", admin_cents, recovery_module, recovery_source),
        audit_step(5, "actual_recovery", "tenant CAM share + administrative fee", recovery_cents, "steps 3-4", recovery_source),
        audit_step(6, "estimated_billed", "sum of CAM estimates billed", billed, billed_source, billed_tag, charge_trace=charge_trace),
        audit_step(7, "true_up", "actual_recovery_cents - estimated_billed_cents", true_up, "steps 5-6", true_up_source),
    ]
    return {
        "status": status,
        "tenancy_id": tenancy_id,
        "period": normalized_period,
        "actual_cam_cost_cents": actual_cam_cents,
        "cap_eligible_cam_cents": cap_eligible_cam_cents,
        "cap_reduction_cents": cap_reduction_cents,
        "actual_recovery_cents": recovery_cents,
        "recoverable_after_cap_cents": recovery_cents,
        "estimated_billed_cents": billed,
        "true_up_cents": true_up,
        "true_up_direction": "tenant owes landlord" if true_up > 0 else "credit/refund to tenant" if true_up < 0 else "none",
        "cap": {
            "ceiling_cents": recovery_math.get("cap_ceiling_cents"),
            "reduction_cents": recovery_math.get("cap_reduction_cents"),
            "recovery_before_cap_cents": recovery_math.get("recovery_before_cap_cents"),
            "recovery_after_cap_cents": recovery_cents,
        },
        "audit_steps": audit_steps,
        "recovery_estimate": estimate,
        "identity_check": {
            "formula": "true_up = recoverable_after_cap - estimated_billed",
            "left_side_cents": true_up,
            "right_side_cents": recovery_cents - billed,
            "exact": true_up == recovery_cents - billed,
        },
        "source_tags": {"recovery": recovery_source, "billed": billed_tag},
        "professional_review_flags": [] if estimate is None else estimate.get("professional_review_flags", []),
        "honest_gaps": ["Review cost classification, exclusions, cap mechanics, notices, and audit rights against the executed lease and invoices."],
        "unrecognized_inputs": sorted(set(unrecognized)),
    }


def cam_true_up(
    tenancy: str | Mapping[str, Any],
    recovery_terms: RecoveryTerms | str | Mapping[str, Any] | None = None,
    actual_costs: Mapping[str, Any] | None = None,
    period: str | None = None,
    estimated_billed_cents: int | None = None,
    tenant_sf: float | int | None = None,
    total_sf: float | int | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Reconcile actual lease-limited CAM recovery against estimated billings."""
    try:
        return _cam_true_up(tenancy, recovery_terms, actual_costs, period, estimated_billed_cents, tenant_sf, total_sf, db_path)
    except Exception as exc:
        return {"error": f"cam_true_up: {_message(exc) or exc.__class__.__name__}"}


def _figure(value: Any, unit: str, source_tag: Mapping[str, Any]) -> dict[str, Any]:
    tag = dict(source_tag)
    source_label = f"{tag['module']} read-only — {tag['detail']}"
    return {"value": value, "unit": unit, "source_tag": tag, "source": source_label}


def _owner_report(
    period: str | None,
    deal_id: str | None,
    budget: Mapping[str, Any] | None,
    actuals: Mapping[str, Any] | None,
    initiative_actuals: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    db_path: str | Path | None,
) -> dict[str, Any]:
    if period is None:
        raise ValueError("period is required")
    if deal_id is None:
        raise ValueError("deal_id is required")
    normalized_period = validate_period(_text(period, "period"))
    normalized_deal = _text(deal_id, "deal_id")
    if budget is not None and not isinstance(budget, Mapping):
        raise ValueError("budget must be a mapping or null")
    books = BookStore(db_path)
    tenancy_ids = {
        str(row["tenancy_id"])
        for row in books.list_tenancies()
        if str(row.get("deal_id")) == normalized_deal
    }
    reconciliation = rent_to_cash(normalized_period, store=books)
    tenancy_rows = [row for row in reconciliation["tenancies"] if str(row["tenancy_id"]) in tenancy_ids]
    books_source = _source_tag(
        "cre_mcp.books.recon.rent_to_cash",
        "deal-filtered tenancy rows from read-only books reconciliation",
        period=normalized_period,
        deal_id=normalized_deal,
        tenancy_ids=sorted(tenancy_ids),
    )
    collection_values = {
        key: sum(int(row[key]) for row in tenancy_rows)
        for key in ("scheduled_cents", "billed_cents", "collected_cents", "outstanding_cents")
    }
    collections: dict[str, Any] = {
        "status": "AVAILABLE" if tenancy_ids else "NOT_AVAILABLE",
        "source_tag": dict(books_source),
        "figures": {
            key: _figure(value, "cents", books_source)
            for key, value in collection_values.items()
        },
        "integrity_gap_count": _figure(
            len(reconciliation.get("integrity_gaps", [])), "count", books_source
        ),
        "tenancy_count": _figure(len(tenancy_ids), "count", books_source),
        "tenancy_ids": sorted(tenancy_ids),
    }
    books_label = f"{books_source['module']} read-only — {books_source['detail']}"
    collections["source"] = books_label

    variance_source = _source_tag(
        "cre_mcp.assetmgmt.variance_explain",
        "actual-minus-budget NOI decomposition",
        period=normalized_period,
        deal_id=normalized_deal,
    )
    if budget is None:
        variance: dict[str, Any] = {
            "status": "NOT_AVAILABLE",
            "source_tag": dict(variance_source),
            "figures": {
                key: _figure(None, "cents", variance_source)
                for key in ("budget_noi_cents", "actual_noi_cents", "total_delta_cents")
            },
            "drivers": {},
            "reason": "budget was not supplied; no variance is inferred",
            "unrecognized_inputs": [],
        }
    else:
        try:
            if actuals is not None and not isinstance(actuals, Mapping):
                raise ValueError("actuals must be a mapping or null")
            raw_variance = variance_explain(budget, actuals, deal_id=normalized_deal, db_path=db_path)
            variance = {
                "status": "AVAILABLE",
                "source_tag": dict(variance_source),
                "figures": {
                    key: _figure(raw_variance.get(key), "cents", variance_source)
                    for key in ("budget_noi_cents", "actual_noi_cents", "total_delta_cents")
                },
                "drivers": {
                    str(key): _figure(value, "cents", variance_source)
                    for key, value in (raw_variance.get("drivers") or {}).items()
                },
                "decomposition_exact": _figure(
                    (raw_variance.get("decomposition_check") or {}).get("exact"),
                    "boolean",
                    variance_source,
                ),
                "unrecognized_inputs": list(raw_variance.get("unrecognized_inputs", [])),
                "honest_gaps": list(raw_variance.get("honest_gaps", [])),
            }
        except Exception as exc:
            variance = {
                "status": "NOT_AVAILABLE",
                "source_tag": dict(variance_source),
                "figures": {},
                "drivers": {},
                "reason": _message(exc),
                "unrecognized_inputs": [],
            }
    variance_label = f"{variance_source['module']} read-only — {variance_source['detail']}"
    variance["source"] = variance_label

    initiative_source = _source_tag(
        "cre_mcp.assetmgmt.initiative_tracker",
        "initiative baselines and structured/read-only actuals",
        period=normalized_period,
        deal_id=normalized_deal,
    )
    try:
        raw_initiatives = initiative_tracker(
            normalized_deal, initiative_actuals, normalized_period, normalized_period, None, db_path=db_path
        )
        tracked = raw_initiatives.get("initiatives", raw_initiatives.get("tracked", []))
        items: list[dict[str, Any]] = []
        for row in tracked:
            row_figures = {
                key: _figure(row.get(key), "cents", initiative_source)
                for key in (
                    "forecast_cost_cents", "actual_cost_cents", "cost_delta_cents",
                    "forecast_noi_impact_cents", "actual_noi_impact_cents",
                    "noi_delta_cents", "net_performance_delta_cents",
                )
            }
            items.append(
                {
                    "initiative": row.get("initiative"),
                    "status": row.get("status"),
                    "owner": row.get("owner"),
                    "source_tag": dict(initiative_source),
                    "figures": row_figures,
                    **row_figures,
                }
            )
        status_counts: dict[str, int] = {}
        for item in items:
            label = str(item.get("status") or "unknown")
            status_counts[label] = status_counts.get(label, 0) + 1
        initiatives: dict[str, Any] = {
            "status": raw_initiatives.get("overall_status", "not_assessable"),
            "source_tag": dict(initiative_source),
            "figures": {
                "initiative_count": _figure(len(items), "count", initiative_source),
                **{
                    f"{key}_count": _figure(value, "count", initiative_source)
                    for key, value in sorted(status_counts.items())
                },
            },
            "items": items,
            "honest_gaps": list(raw_initiatives.get("honest_gaps", [])),
            "unmatched_actual_initiatives": list(raw_initiatives.get("unmatched_actual_initiatives", [])),
        }
    except Exception as exc:
        initiatives = {
            "status": "not_assessable",
            "source_tag": dict(initiative_source),
            "figures": {"initiative_count": _figure(0, "count", initiative_source)},
            "items": [],
            "reason": _message(exc),
        }
    initiative_label = f"{initiative_source['module']} read-only — {initiative_source['detail']}"
    initiatives["source"] = initiative_label

    report_source = _source_tag(
        "cre_mcp.analytics.workflows.owner_report",
        "composition of three read-only source-tagged sections",
        period=normalized_period,
        deal_id=normalized_deal,
    )
    return {
        "status": "OWNER_REPORT",
        "status_source_tag": report_source,
        "period": normalized_period,
        "deal_id": normalized_deal,
        "variance": variance,
        "collections": collections,
        "initiatives": initiatives,
        "source_tags": [books_source, variance_source, initiative_source],
        "source_registry": {
            "collections": books_label,
            "variance": variance_label,
            "initiatives": initiative_label,
        },
        "source_tagging": (
            "Every monetary, count, boolean, and status figure has an explicit "
            "read-only source tag."
        ),
        "unrecognized_inputs": sorted(set(variance.get("unrecognized_inputs", []))),
        "honest_gaps": sorted(set(
            list(variance.get("honest_gaps", []))
            + list(initiatives.get("honest_gaps", []))
        )),
    }


def owner_report(
    period: str,
    deal_id: str,
    budget: Mapping[str, Any] | None = None,
    actuals: Mapping[str, Any] | None = None,
    initiative_actuals: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compose variance, collections, and initiative status with source tags."""
    try:
        return _owner_report(period, deal_id, budget, actuals, initiative_actuals, db_path)
    except Exception as exc:
        return {"error": f"owner_report: {_message(exc) or exc.__class__.__name__}"}


__all__ = ["cam_true_up", "owner_report"]
