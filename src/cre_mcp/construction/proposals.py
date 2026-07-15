"""Scope-first comparison of architect, engineer, GC, and CM proposals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


ALLOWED_ROLES = {"architect", "engineer", "gc", "cm"}
SCOPE_STATUSES = {"covered", "excluded", "silent"}


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _scope_text(value: Any, field: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("item", value.get("scope", value.get("description")))
    return _required_text(value, field)


def _scope_key(value: str) -> str:
    return " ".join(
        value.strip().lower().replace("_", " ").replace("-", " ").split()
    )


def _scope_list(value: Any, field: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a list")
    return [_scope_text(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{field} must be a finite {qualifier} number")
    return result


def _money_cents(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer number of cents")
    return value


def _first_present(source: Mapping[str, Any], names: Sequence[str]) -> tuple[Any, str | None]:
    for name in names:
        if name in source and source[name] is not None:
            return source[name], name
    return None, None


def _normalize_fee(fee_structure: Any, field: str) -> dict[str, Any]:
    if not isinstance(fee_structure, Mapping):
        return {
            "type": "unstructured",
            "normalized_fee_cents": None,
            "comparison_status": "not_normalizable",
            "basis": "fee_structure was not a structured dictionary",
        }

    raw_type = fee_structure.get("type", fee_structure.get("structure"))
    if raw_type is None:
        if any(key in fee_structure for key in ("fixed_cents", "amount_cents", "fee_cents")):
            raw_type = "fixed"
        elif any(key in fee_structure for key in ("percent", "percentage", "fee_pct")):
            raw_type = "percentage"
        elif "rate_cents" in fee_structure:
            raw_type = "hourly"
    if not isinstance(raw_type, str) or not raw_type.strip():
        return {
            "type": "unstructured",
            "normalized_fee_cents": None,
            "comparison_status": "not_normalizable",
            "basis": "fee type is missing",
        }
    fee_type = raw_type.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "lump_sum": "fixed",
        "flat": "fixed",
        "flat_fee": "fixed",
        "fixed_fee": "fixed",
        "percent_of_cost": "percentage",
        "percentage_of_cost": "percentage",
        "time_and_materials": "hourly",
        "t_and_m": "hourly",
        "not_to_exceed": "nte",
    }
    fee_type = aliases.get(fee_type, fee_type)

    if fee_type in {"fixed", "nte"}:
        amount, source_key = _first_present(
            fee_structure,
            ("amount_cents", "fixed_cents", "fee_cents", "not_to_exceed_cents"),
        )
        if amount is None:
            return {
                "type": fee_type,
                "normalized_fee_cents": None,
                "comparison_status": "not_normalizable",
                "basis": "structured fee has no integer-cent amount",
            }
        normalized = _money_cents(amount, f"{field}.{source_key}")
        return {
            "type": fee_type,
            "normalized_fee_cents": normalized,
            "comparison_status": "normalized",
            "basis": source_key,
        }

    if fee_type == "percentage":
        percent, percent_key = _first_present(
            fee_structure, ("percent", "percentage", "fee_pct")
        )
        cost_basis, basis_key = _first_present(
            fee_structure,
            ("cost_basis_cents", "basis_cents", "construction_cost_cents"),
        )
        if percent is None or cost_basis is None:
            return {
                "type": fee_type,
                "normalized_fee_cents": None,
                "comparison_status": "not_normalizable",
                "percent": None if percent is None else str(_decimal(percent, f"{field}.{percent_key}")),
                "basis": "percentage requires an explicit integer-cent cost basis",
            }
        pct = _decimal(percent, f"{field}.{percent_key}")
        basis_cents = _money_cents(cost_basis, f"{field}.{basis_key}")
        normalized = int(
            (Decimal(basis_cents) * pct / Decimal("100")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        return {
            "type": fee_type,
            "normalized_fee_cents": normalized,
            "comparison_status": "normalized",
            "percent": str(pct),
            "cost_basis_cents": basis_cents,
            "basis": f"{percent_key} of {basis_key}",
        }

    if fee_type == "hourly":
        rate, rate_key = _first_present(fee_structure, ("rate_cents", "hourly_rate_cents"))
        hours, hours_key = _first_present(fee_structure, ("hours", "estimated_hours"))
        if rate is None or hours is None:
            return {
                "type": fee_type,
                "normalized_fee_cents": None,
                "comparison_status": "not_normalizable",
                "basis": "hourly fee requires rate_cents and estimated hours",
            }
        rate_cents = _money_cents(rate, f"{field}.{rate_key}")
        hour_count = _decimal(hours, f"{field}.{hours_key}")
        normalized = int(
            (Decimal(rate_cents) * hour_count).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        return {
            "type": fee_type,
            "normalized_fee_cents": normalized,
            "comparison_status": "normalized_estimate",
            "rate_cents": rate_cents,
            "hours": str(hour_count),
            "basis": f"{rate_key} x {hours_key}",
        }

    return {
        "type": fee_type,
        "normalized_fee_cents": None,
        "comparison_status": "not_normalizable",
        "basis": "unsupported fee structure; compare commercial terms manually",
    }


def compare_proposals(
    proposals: Sequence[Mapping[str, Any]],
    required_scope: Sequence[Any],
) -> dict[str, Any]:
    """Compare proposal scope before price and flag silence as the highest risk.

    Scope status uses exact normalized labels only.  Assumptions are not treated
    as coverage, and a proposal's silence is never inferred to mean inclusion.
    """

    if isinstance(proposals, (str, bytes)) or not isinstance(proposals, Sequence):
        raise ValueError("proposals must be a list of dictionaries")
    required = _scope_list(required_scope, "required_scope")
    if not required:
        raise ValueError("required_scope must contain at least one item")
    required_by_key: dict[str, str] = {}
    for item in required:
        key = _scope_key(item)
        if key in required_by_key:
            raise ValueError(f"required_scope contains duplicate item {item!r}")
        required_by_key[key] = item

    normalized_proposals: list[dict[str, Any]] = []
    names: set[str] = set()
    risk_notes: list[dict[str, Any]] = []
    matrix_status: dict[str, dict[str, str]] = {
        key: {} for key in required_by_key
    }

    for index, raw in enumerate(proposals):
        if not isinstance(raw, Mapping):
            raise ValueError(f"proposals[{index}] must be a dictionary")
        firm = _required_text(raw.get("firm"), f"proposals[{index}].firm")
        firm_key = firm.casefold()
        if firm_key in names:
            raise ValueError(f"proposal firm names must be unique; duplicate {firm!r}")
        names.add(firm_key)
        role = _required_text(raw.get("role"), f"proposals[{index}].role").lower()
        if role not in ALLOWED_ROLES:
            raise ValueError(f"proposals[{index}].role must be one of {sorted(ALLOWED_ROLES)}")

        scope_items = _scope_list(raw.get("scope_items", []), f"proposals[{index}].scope_items")
        exclusions = _scope_list(raw.get("exclusions", []), f"proposals[{index}].exclusions")
        assumptions = _scope_list(raw.get("assumptions", []), f"proposals[{index}].assumptions")
        covered_keys = {_scope_key(item) for item in scope_items}
        excluded_keys = {_scope_key(item) for item in exclusions}
        conflicts = covered_keys & excluded_keys
        assessment: list[dict[str, str]] = []
        counts = {status: 0 for status in SCOPE_STATUSES}

        for scope_key, scope_item in required_by_key.items():
            if scope_key in excluded_keys:
                status = "excluded"
            elif scope_key in covered_keys:
                status = "covered"
            else:
                status = "silent"
            matrix_status[scope_key][firm] = status
            counts[status] += 1
            assessment.append({"scope_item": scope_item, "status": status})
            if status == "silent":
                risk_notes.append(
                    {
                        "firm": firm,
                        "role": role,
                        "scope_item": scope_item,
                        "severity": "critical",
                        "risk_type": "silent_required_scope",
                        "note": "SILENT: required scope is neither included nor excluded; obtain explicit written disposition.",
                    }
                )
            elif status == "excluded":
                risk_notes.append(
                    {
                        "firm": firm,
                        "role": role,
                        "scope_item": scope_item,
                        "severity": "high",
                        "risk_type": "excluded_required_scope",
                        "note": "Required scope is expressly excluded; assign and price it before award.",
                    }
                )
        for conflict in sorted(conflicts):
            risk_notes.append(
                {
                    "firm": firm,
                    "role": role,
                    "scope_item": required_by_key.get(conflict, conflict),
                    "severity": "critical",
                    "risk_type": "scope_conflict",
                    "note": "The same scope appears in both inclusions and exclusions; exclusion controls this comparison pending clarification.",
                }
            )

        fee = _normalize_fee(raw.get("fee_structure"), f"proposals[{index}].fee_structure")
        if fee["normalized_fee_cents"] is None:
            risk_notes.append(
                {
                    "firm": firm,
                    "role": role,
                    "scope_item": None,
                    "severity": "high",
                    "risk_type": "fee_not_normalizable",
                    "note": "Fee cannot be normalized from supplied terms; obtain an integer-cent fixed/NTE amount or an explicit basis.",
                }
            )
        for exclusion in exclusions:
            if _scope_key(exclusion) not in required_by_key:
                risk_notes.append(
                    {
                        "firm": firm,
                        "role": role,
                        "scope_item": exclusion,
                        "severity": "medium",
                        "risk_type": "other_exclusion",
                        "note": "Exclusion is outside the named baseline but may create an owner or coordination cost.",
                    }
                )
        for assumption in assumptions:
            risk_notes.append(
                {
                    "firm": firm,
                    "role": role,
                    "scope_item": None,
                    "severity": "medium",
                    "risk_type": "proposal_assumption",
                    "note": assumption,
                }
            )

        normalized_proposals.append(
            {
                "firm": firm,
                "role": role,
                "fee": fee,
                "scope_counts": counts,
                "scope_assessment": assessment,
                "scope_items": scope_items,
                "exclusions": exclusions,
                "assumptions": assumptions,
            }
        )

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    risk_notes.sort(key=lambda row: (severity_order[row["severity"]], row["firm"], str(row["scope_item"])))
    matrix = [
        {
            "scope_item": scope_item,
            "status_by_firm": matrix_status[key],
            "firms": matrix_status[key],
            "silent_firms": [
                firm for firm, status in matrix_status[key].items() if status == "silent"
            ],
        }
        for key, scope_item in required_by_key.items()
    ]
    fee_comparison = [
        {
            "firm": proposal["firm"],
            "role": proposal["role"],
            "normalized_fee_cents": proposal["fee"]["normalized_fee_cents"],
            "comparison_status": proposal["fee"]["comparison_status"],
            "fee_type": proposal["fee"]["type"],
        }
        for proposal in normalized_proposals
    ]
    fee_comparison.sort(
        key=lambda row: (
            row["normalized_fee_cents"] is None,
            row["normalized_fee_cents"] if row["normalized_fee_cents"] is not None else 0,
            row["firm"],
        )
    )
    roles_present = {proposal["role"] for proposal in normalized_proposals}

    return {
        "required_scope": list(required_by_key.values()),
        "scope_status_definitions": {
            "covered": "expressly listed in scope_items",
            "excluded": "expressly listed in exclusions; controls a conflicting inclusion",
            "silent": "neither included nor excluded; highest-risk status and not inferred as covered",
        },
        "scope_matrix": matrix,
        "scope_matrix_by_item": {
            row["scope_item"]: row["status_by_firm"] for row in matrix
        },
        "firms": normalized_proposals,
        "fee_comparison": fee_comparison,
        "risk_notes": risk_notes,
        "highest_risk": "SILENT required scope" if any(note["risk_type"] == "silent_required_scope" for note in risk_notes) else None,
        "professional_review_flags": [
            {"role": "architect", "status": "proposal_present" if "architect" in roles_present else "not_compared", "reason": "confirm design deliverables, phase coverage, and consultant coordination"},
            {"role": "engineer", "status": "proposal_present" if "engineer" in roles_present else "not_compared", "reason": "confirm discipline boundaries and delegated-design responsibilities"},
            {"role": "gc", "status": "proposal_present" if "gc" in roles_present else "not_compared", "reason": "confirm preconstruction/construction inclusions, general conditions, and buyout assumptions"},
            {"role": "inspector", "status": "not_field_verified", "reason": "proposal text is not inspection evidence or field verification"},
        ],
        "limitations": [
            "Exact normalized scope labels are compared; semantic equivalence is not inferred.",
            "Fees exclude unstructured reimbursables, escalation, and scope changes unless explicitly included in the supplied fee structure.",
            "Proposal statements are bidder-authored and not architect, engineer, GC, or inspector verified by this comparison.",
        ],
    }


__all__ = ["ALLOWED_ROLES", "SCOPE_STATUSES", "compare_proposals"]
