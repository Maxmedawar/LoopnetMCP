"""Plain tax-economics adapters for later MCP registration by the director."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.access.context import current_context
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.access.territory import canonical_permit_property
from cre_mcp.taxecon.assessor_audit import (
    audit_assessor_record as _audit_assessor_record,
)
from cre_mcp.taxecon.proceeds import net_sale_proceeds as _net_sale_proceeds
from cre_mcp.taxecon.reassessment import estimate_reassessment


def estimate_tax_reassessment(
    purchase_price: float | None,
    current_assessed_value: float | None,
    current_annual_taxes: float | None,
    state: str,
    county: str | None = None,
    *,
    asking_price: float | None = None,
) -> dict[str, Any]:
    """Plain-function adapter for the property-tax reassessment screen."""

    return estimate_reassessment(
        purchase_price,
        current_assessed_value,
        current_annual_taxes,
        state,
        county,
        asking_price=asking_price,
    )


def audit_assessor_record(
    record: dict[str, Any],
    stated_facts: dict[str, Any],
) -> dict[str, Any]:
    """Plain-function adapter for assessor/listing fact reconciliation."""

    result = _audit_assessor_record(record, stated_facts)
    tenant = current_context()
    if (
        tenant is not None
        and not tenant.trusted
        and tenant.profile in TERRITORY_LIMITED
    ):
        subject_record: Mapping[str, Any] = record
        parcels = record.get("parcels")
        if isinstance(parcels, Sequence) and not isinstance(parcels, (str, bytes)):
            subject_record = next(
                (item for item in parcels if isinstance(item, Mapping)),
                record,
            )
        elif isinstance(record.get("parcel"), Mapping):
            subject_record = record["parcel"]
        subject = canonical_permit_property(subject_record)
        result["subject_property"] = {
            "address": subject.get("address") if subject is not None else None,
            "city": subject.get("city") if subject is not None else None,
            "state": subject.get("state") if subject is not None else None,
            "zip_code": subject.get("zip_code") if subject is not None else None,
        }
        result["assumption_sheet"] = []
        for collection in ("discrepancies", "appeal_signals"):
            for row in result.get(collection, []):
                if not isinstance(row, dict):
                    continue
                for field in ("assessor_value", "stated_value"):
                    value = row.get(field)
                    if type(value) not in (int, float, bool, type(None)):
                        row[field] = None
    return result


def net_sale_proceeds(
    price: float,
    loan_balance: float,
    prepay: dict[str, Any] | None,
    commission_pct: float,
    state: str,
    other_costs: float | dict[str, Any] = 0.0,
    credits: float | dict[str, Any] = 0.0,
    reserves_released: float | dict[str, Any] = 0.0,
    *,
    tax_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plain-function adapter for the seller proceeds waterfall."""

    return _net_sale_proceeds(
        price,
        loan_balance,
        prepay,
        commission_pct,
        state,
        other_costs,
        credits,
        reserves_released,
        tax_profile=tax_profile,
    )


__all__ = ["audit_assessor_record", "estimate_tax_reassessment", "net_sale_proceeds"]
