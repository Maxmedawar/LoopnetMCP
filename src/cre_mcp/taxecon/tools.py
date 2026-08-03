"""Plain tax-economics adapters for later MCP registration by the director."""

from __future__ import annotations

from typing import Any

from cre_mcp.taxecon.assessor_audit import audit_assessor_record as _audit_assessor_record
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

    return _audit_assessor_record(record, stated_facts)


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
