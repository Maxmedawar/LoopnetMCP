"""Plain (unregistered) callable surfaces for the distressed-note engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.notes.pricing import price_note as _price_note
from cre_mcp.notes.strategies import compare_workouts as _compare_workouts
from cre_mcp.notes.timelines import (
    COUNSEL_VERIFICATION_FLAG,
    estimate_timeline as _estimate_timeline,
)
from cre_mcp.notes.waterfall import lien_recovery_waterfall as _lien_recovery_waterfall
from cre_mcp.positioning import AUTHORITY_MATRIX, STANDARD_DISCLAIMER


def _sheet(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "driver": key,
            "value": value,
            "source": "provided_unverified" if value is not None else "unknown",
        }
        for key, value in values.items()
    ]


def _surface(result: dict, inputs: Mapping[str, Any]) -> dict:
    surfaced = dict(result)
    surfaced.setdefault("assumption_sheet", _sheet(inputs))
    surfaced["tool_assumption_sheet"] = _sheet(inputs)
    surfaced["authority"] = {
        "calculate": AUTHORITY_MATRIX["calculate"],
        "recommend": AUTHORITY_MATRIX["recommend"],
        "commit_funds_or_wire": AUTHORITY_MATRIX["commit_funds_or_wire"],
    }
    surfaced["disclaimer"] = STANDARD_DISCLAIMER
    surfaced["professional_review_required"] = True
    flags = list(surfaced.get("professional_review_flags", []))
    if COUNSEL_VERIFICATION_FLAG not in flags:
        flags.insert(0, COUNSEL_VERIFICATION_FLAG)
    surfaced["professional_review_flags"] = flags
    return surfaced


def estimate_foreclosure_timeline(
    state: str,
    contested: bool = False,
    bankruptcy_risk: bool | None = None,
) -> dict:
    """Return a sourced state timeline range without registering an MCP tool."""

    inputs = {
        "state": state,
        "contested": contested,
        "bankruptcy_risk": bankruptcy_risk,
    }
    return _surface(
        _estimate_timeline(
            state=state,
            contested=contested,
            bankruptcy_risk=bankruptcy_risk,
        ),
        inputs,
    )


def model_lien_waterfall(
    collateral_value_range: Any,
    marketing_discount: Any,
    liens: Sequence[Mapping[str, Any]],
    costs: Mapping[str, Any] | None,
) -> dict:
    """Return exact caller-ordered lien recoveries under three scenarios."""

    inputs = {
        "collateral_value_range": collateral_value_range,
        "marketing_discount": marketing_discount,
        "liens": list(liens),
        "costs": dict(costs or {}),
    }
    return _surface(_lien_recovery_waterfall(**inputs), inputs)


def price_note(
    upb: Any,
    rate: Any,
    payment_history: Mapping[str, Any],
    collateral_value_range: Any,
    state: str,
    lien_position: Any,
    costs: Mapping[str, Any] | None,
    target_yield_range: Any,
    *,
    path_probabilities: Mapping[str, Any] | None = None,
) -> dict:
    """Return performing or expected-path note price bands without tool registration."""

    inputs = {
        "upb": upb,
        "rate": rate,
        "payment_history": dict(payment_history),
        "collateral_value_range": collateral_value_range,
        "state": state,
        "lien_position": lien_position,
        "costs": dict(costs or {}),
        "target_yield_range": target_yield_range,
        "path_probabilities": dict(path_probabilities) if path_probabilities else None,
    }
    result = _price_note(
        upb=upb,
        rate=rate,
        payment_history=payment_history,
        collateral_value_range=collateral_value_range,
        state=state,
        lien_position=lien_position,
        costs=costs,
        target_yield_range=target_yield_range,
        path_probabilities=path_probabilities,
    )
    return _surface(result, inputs)


def compare_note_workouts(
    note_facts: Mapping[str, Any],
    borrower_posture: Mapping[str, Any] | None = None,
) -> dict:
    """Return the seven-path workout table without making or executing a decision."""

    inputs = {
        "note_facts": dict(note_facts),
        "borrower_posture": dict(borrower_posture or {}),
    }
    return _surface(
        _compare_workouts(note_facts=note_facts, borrower_posture=borrower_posture),
        inputs,
    )


__all__ = [
    "compare_note_workouts",
    "estimate_foreclosure_timeline",
    "model_lien_waterfall",
    "price_note",
]
