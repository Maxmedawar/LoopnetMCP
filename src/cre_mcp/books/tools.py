"""Plain property-books functions for later FastMCP registration."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bankimport import import_bank_csv, match_receipts
from .billing import (
    MANUAL_KINDS,
    lease_to_billing_audit,
    post_manual_charge,
    post_scheduled_charges,
    validate_period,
)
from .recon import ar_aging as build_ar_aging
from .recon import rent_to_cash
from .store import BookStore

logger = logging.getLogger(__name__)

_MANUAL_CHARGE_SHAPE = (
    "manual_charges items must include period, kind, author, and either "
    "amount (dollars) or amount_cents (integer cents)"
)


def _error(tool_name: str, exc: Exception) -> dict[str, str]:
    """Turn all implementation failures into a stable MCP-friendly result."""

    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = message or exc.__class__.__name__
    logger.error("%s error: %s", tool_name, message)
    return {"error": message}


def _dollars_to_cents(value: Any) -> int:
    """Convert a client-facing dollar value with decimal, never float, math."""

    if isinstance(value, bool):
        raise ValueError("amount (dollars) must be a finite numeric value")
    try:
        dollars = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount (dollars) must be a finite numeric value") from exc
    if not dollars.is_finite():
        raise ValueError("amount (dollars) must be a finite numeric value")
    return int(
        (dollars * Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def _manual_amount_cents(item: Mapping[str, Any]) -> int:
    """Resolve either supported money shape and prove dual inputs agree."""

    has_dollars = "amount" in item
    has_cents = "amount_cents" in item
    if not has_dollars and not has_cents:
        raise ValueError(_MANUAL_CHARGE_SHAPE)

    cents: int | None = None
    if has_cents:
        raw_cents = item["amount_cents"]
        if isinstance(raw_cents, bool) or not isinstance(raw_cents, int):
            raise ValueError(
                "amount_cents must be an integer number of cents; "
                f"expected shape: {_MANUAL_CHARGE_SHAPE}"
            )
        cents = raw_cents

    dollar_cents = _dollars_to_cents(item["amount"]) if has_dollars else None
    if cents is not None and dollar_cents is not None and cents != dollar_cents:
        raise ValueError(
            "amount and amount_cents are inconsistent "
            f"({dollar_cents} cents != {cents} cents); expected shape: "
            f"{_MANUAL_CHARGE_SHAPE}"
        )
    resolved = cents if cents is not None else dollar_cents
    assert resolved is not None
    if resolved < 0:
        raise ValueError("manual charge amount must be non-negative")
    return resolved


def _normalize_manual_charges(
    manual_charges: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Validate the whole manual batch before any scheduled line is written."""

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(manual_charges or ()):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"manual_charges[{index}] must be a mapping; expected shape: "
                f"{_MANUAL_CHARGE_SHAPE}"
            )
        missing = [
            field
            for field in ("period", "kind", "author")
            if field not in item
        ]
        if missing:
            raise ValueError(
                f"manual_charges[{index}] missing {', '.join(missing)}; "
                f"expected shape: {_MANUAL_CHARGE_SHAPE}"
            )
        period = validate_period(str(item["period"]))
        kind = str(item["kind"]).strip().casefold()
        if kind not in MANUAL_KINDS:
            raise ValueError(
                "manual kind must be cam, tax, ins, or other; "
                "rent comes from the lease schedule"
            )
        raw_author = item["author"]
        author = "" if raw_author is None else str(raw_author).strip()
        if not author:
            raise ValueError("manual charge author cannot be blank")
        normalized.append(
            {
                "period": period,
                "kind": kind,
                "amount_cents": _manual_amount_cents(item),
                "author": author,
                "source_detail": item.get("source_detail"),
                "charge_id": item.get("charge_id"),
            }
        )
    return normalized


def setup_tenancy(
    deal_id: str,
    unit: str,
    tenant_name: str,
    lease_ref: str | Path | None = None,
    active: bool = True,
    tenancy_id: str | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create one durable tenancy book record."""

    try:
        return BookStore(db_path).setup_tenancy(
            deal_id=deal_id,
            unit=unit,
            tenant_name=tenant_name,
            lease_ref=lease_ref,
            active=active,
            tenancy_id=tenancy_id,
        )
    except Exception as exc:
        return _error("setup_tenancy", exc)


def post_charges(
    tenancy_id: str,
    from_period: str,
    to_period: str | None = None,
    manual_charges: Sequence[Mapping[str, Any]] | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Post lease rent for a range plus any explicitly authored manual charges."""

    try:
        # Preflight the complete batch so a malformed manual line cannot leave
        # behind only the scheduled half of the requested posting operation.
        normalized_manual = _normalize_manual_charges(manual_charges)
        store = BookStore(db_path)
        tenancy = store.get_tenancy(tenancy_id)
        scheduled: dict[str, Any]
        if tenancy.get("lease_ref"):
            scheduled = post_scheduled_charges(
                tenancy,
                (from_period, to_period or from_period),
                store=store,
            )
        else:
            scheduled = {
                "tenancy_id": tenancy_id,
                "from_period": from_period,
                "to_period": to_period or from_period,
                "posted": [],
                "already_posted": [],
                "gaps": [
                    {
                        "reason": (
                            "No lease_ref exists; scheduled rent was not inferred."
                        )
                    }
                ],
            }
        manual_results: list[dict[str, Any]] = []
        for item in normalized_manual:
            manual_results.append(
                post_manual_charge(
                    tenancy_id,
                    item["period"],
                    item["kind"],
                    item["amount_cents"],
                    author=item["author"],
                    source_detail=item["source_detail"],
                    charge_id=item["charge_id"],
                    store=store,
                )
            )
        return {"scheduled": scheduled, "manual": manual_results}
    except Exception as exc:
        return _error("post_charges", exc)


def import_bank_transactions(
    path: str | Path,
    mapping: Mapping[str, Any],
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Import bank deposits as unmatched candidate receipts."""

    try:
        return import_bank_csv(path, mapping, db_path=db_path)
    except Exception as exc:
        return _error("import_bank_transactions", exc)


def reconcile_rent_to_cash(
    period: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply the conservative matcher, then produce the rent-to-cash bridge."""

    try:
        store = BookStore(db_path)
        matching = match_receipts(period, store=store)
        reconciliation = rent_to_cash(period, store=store)
        reconciliation["receipt_matching"] = matching
        return reconciliation
    except Exception as exc:
        return _error("reconcile_rent_to_cash", exc)


def ar_aging(
    as_of: Any = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return convention-labeled unpaid-charge aging."""

    try:
        return build_ar_aging(as_of, db_path=db_path)
    except Exception as exc:
        return _error("ar_aging", exc)


def audit_lease_billing(
    tenancy_id: str,
    from_period: str,
    to_period: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compare posted rent with recomputed, lease-cited monthly rent."""

    try:
        return lease_to_billing_audit(
            tenancy_id,
            (from_period, to_period),
            db_path=db_path,
        )
    except Exception as exc:
        return _error("audit_lease_billing", exc)


__all__ = [
    "ar_aging",
    "audit_lease_billing",
    "import_bank_transactions",
    "post_charges",
    "reconcile_rent_to_cash",
    "setup_tenancy",
]
