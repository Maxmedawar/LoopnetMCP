"""Transparent CapEx prioritization with a hard life-safety gate."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


CATEGORIES = frozenset(
    {"safety", "compliance", "retention", "return", "saleability"}
)
MANDATORY_CATEGORIES = frozenset({"safety", "compliance"})
PRIORITY_CONVENTION = (
    "Every safety or compliance request precedes every discretionary request, "
    "regardless of cost, urgency, or calculated return. Mandatory items are "
    "ordered by urgency; discretionary items are ordered by simple annual "
    "impact divided by cost, then urgency. This is a screening convention, not "
    "a substitute for engineering, legal, or insurance review."
)


def _cents(value: Any, *, name: str, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    return value


def _urgency(value: Any) -> tuple[float, str]:
    if isinstance(value, bool):
        raise ValueError("urgency must be a number or low/medium/high/critical")
    if isinstance(value, (int, float)):
        return float(value), str(value)
    normalized = str(value or "").strip().casefold()
    levels = {"low": 1.0, "medium": 2.0, "high": 3.0, "critical": 4.0}
    if normalized not in levels:
        raise ValueError("urgency must be a number or low/medium/high/critical")
    return levels[normalized], normalized


def _impact(value: Any, index: int) -> tuple[int | None, str]:
    if value is None:
        return None, "not supplied"
    if isinstance(value, Mapping):
        for key in (
            "annual_noi_cents",
            "expected_noi_delta_cents",
            "risk_avoided_cents_annual",
            "impact_cents",
        ):
            if key in value:
                amount = _cents(
                    value[key],
                    name=f"requests[{index}].noi_or_risk_impact.{key}",
                    nullable=True,
                )
                return amount, key
        raise ValueError(
            f"requests[{index}].noi_or_risk_impact mapping needs an integer-cents impact field"
        )
    amount = _cents(
        value,
        name=f"requests[{index}].noi_or_risk_impact",
        nullable=True,
    )
    return amount, "caller-supplied annual NOI or risk impact cents"


def prioritize_capex(
    requests: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Rank CapEx while making the mandatory safety/compliance gate explicit."""

    if isinstance(requests, (str, bytes)) or not isinstance(requests, Sequence):
        raise ValueError("requests must be a sequence of request mappings")
    matrix: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        if not isinstance(request, Mapping):
            raise ValueError(f"requests[{index}] must be a mapping")
        item = str(request.get("item") or "").strip()
        if not item:
            raise ValueError(f"requests[{index}].item cannot be blank")
        category = str(request.get("category") or "").strip().casefold()
        if category not in CATEGORIES:
            raise ValueError(
                f"requests[{index}].category must be one of: "
                + ", ".join(sorted(CATEGORIES))
            )
        cost = _cents(request.get("cost_cents"), name=f"requests[{index}].cost_cents")
        assert cost is not None
        if cost < 0:
            raise ValueError(f"requests[{index}].cost_cents must be non-negative")
        urgency_score, urgency_label = _urgency(request.get("urgency"))
        impact, impact_basis = _impact(request.get("noi_or_risk_impact"), index)
        simple_return = None if impact is None or cost == 0 else impact / cost
        payback_months = (
            None
            if impact is None or impact <= 0
            else 0.0
            if cost == 0
            else 12 * cost / impact
        )
        mandatory = category in MANDATORY_CATEGORIES
        matrix.append(
            {
                "item": item,
                "category": category,
                "mandatory_gate": mandatory,
                "cost_cents": cost,
                "annual_noi_or_risk_impact_cents": impact,
                "impact_basis": impact_basis,
                "urgency": urgency_label,
                "urgency_score": urgency_score,
                "simple_annual_return": simple_return,
                "simple_payback_months": payback_months,
                "net_first_year_impact_after_cost_cents": (
                    impact - cost if impact is not None else None
                ),
                "recommendation_basis": (
                    "non-negotiable safety/compliance gate; return is disclosed but cannot demote it"
                    if mandatory
                    else "discretionary ranking by calculated simple annual return, then urgency"
                ),
                "input_position": index,
            }
        )

    def sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        if row["mandatory_gate"]:
            return (0, -float(row["urgency_score"]), int(row["input_position"]))
        calculated_return = row["simple_annual_return"]
        return (
            1,
            calculated_return is None,
            -float(calculated_return) if calculated_return is not None else 0.0,
            -float(row["urgency_score"]),
            int(row["input_position"]),
        )

    matrix.sort(key=sort_key)
    for rank, row in enumerate(matrix, start=1):
        row["rank"] = rank
        return_text = (
            "not computable because impact was not supplied"
            if row["simple_annual_return"] is None
            else f"{float(row['simple_annual_return']):.6f} annual impact per cost cent"
        )
        row["recommendation"] = (
            f"Rank {rank}: cost {row['cost_cents']} cents; annual NOI/risk impact "
            f"{row['annual_noi_or_risk_impact_cents']} cents; return {return_text}. "
            f"Mandatory gate={row['mandatory_gate']}."
        )
        row.pop("input_position")
    mandatory_count = sum(int(row["mandatory_gate"]) for row in matrix)
    return {
        "ranked_requests": matrix,
        "matrix": matrix,
        "mandatory_count": mandatory_count,
        "ordering_convention": PRIORITY_CONVENTION,
        "return_formula": {
            "simple_annual_return": "annual_noi_or_risk_impact_cents / cost_cents",
            "simple_payback_months": (
                "12 * cost_cents / annual_noi_or_risk_impact_cents"
            ),
            "zero_cost": "return is undefined; positive impact has zero-month payback",
        },
        "honest_gaps": [
            "Risk impact and NOI impact are caller estimates and are not treated as equivalent observed cash flows.",
            "No useful-life, tax, financing, or multi-year DCF assumptions were supplied, so return math is a one-year screen.",
        ],
    }


__all__ = ["CATEGORIES", "MANDATORY_CATEGORIES", "prioritize_capex"]
