"""One-at-a-time sensitivity rankings for scenario-model outputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.scenarios._common import HONESTY_LABEL, as_number, normalized_assumptions
from cre_mcp.scenarios.engine import stress_test

EVIDENCE_BY_DRIVER = {
    "rent": "lease comps + executed-lease audit",
    "occupancy": "rent roll, lease expirations, and tenant interviews",
    "opex": "T12 vs GL, tax reassessment check",
    "interest_rate": "live quotes, not benchmarks",
    "rate": "live quotes, not benchmarks",
    "exit_cap": "recent sale comps, debt-market direction",
    "hold_years": "business-plan milestones and buyer-pool evidence",
    "sale_timing": "broker feedback, buyer pipeline, and closing calendar",
}


def _bounds(span: Any) -> tuple[float, float]:
    if isinstance(span, Mapping):
        low = as_number(span.get("low"))
        high = as_number(span.get("high"))
        if low is None or high is None:
            raise ValueError("span mappings require finite low and high values")
        return low, high
    if isinstance(span, Sequence) and not isinstance(span, (str, bytes)):
        if len(span) != 2:
            raise ValueError("span sequences must contain exactly [low, high]")
        low, high = as_number(span[0]), as_number(span[1])
        if low is None or high is None:
            raise ValueError("span bounds must be finite numbers")
        return low, high
    width = as_number(span)
    if width is None or width < 0:
        raise ValueError("scalar spans must be finite non-negative numbers")
    return -width, width


def _custom_case(deal_inputs: dict[str, Any], driver: str, value: float) -> dict[str, Any]:
    result = stress_test(deal_inputs, {driver: value})
    return result["scenarios"]["custom"]


def _delta(value: float | None, base: float | None) -> float | None:
    return value - base if value is not None and base is not None else None


def _magnitude(*values: float | None) -> float | None:
    known = [abs(value) for value in values if value is not None]
    return max(known) if known else None


def tornado(deal_inputs: dict[str, Any], spans: Mapping[str, Any]) -> dict[str, Any]:
    """Sweep one driver at a time and rank by maximum absolute IRR change.

    A scalar span becomes symmetric ``[-span, +span]``. A two-item sequence or
    ``{"low": ..., "high": ...}`` supplies explicit shock deltas. Values retain
    the stress engine's units: relative rent/opex changes, decimal-point
    occupancy/rate/cap changes, years for hold and months for sale timing.
    These are caller-selected sensitivity CONVENTIONS, not forecasts.
    """
    if not isinstance(deal_inputs, dict):
        raise TypeError("deal_inputs must be a dict")
    if not isinstance(spans, Mapping):
        raise TypeError("spans must be a mapping of driver names to bounds")

    base = stress_test(deal_inputs, "base")["scenarios"]["base"]
    drivers: list[dict[str, Any]] = []
    for driver, raw_span in spans.items():
        low_shock, high_shock = _bounds(raw_span)
        low_case = _custom_case(deal_inputs, str(driver), low_shock)
        high_case = _custom_case(deal_inputs, str(driver), high_shock)
        low_irr_delta = _delta(low_case["irr"], base["irr"])
        high_irr_delta = _delta(high_case["irr"], base["irr"])
        low_dscr_delta = _delta(low_case["dscr"], base["dscr"])
        high_dscr_delta = _delta(high_case["dscr"], base["dscr"])
        evidence = EVIDENCE_BY_DRIVER.get(
            str(driver), "direct source documents and current third-party evidence"
        )
        drivers.append(
            {
                "driver": str(driver),
                "low_shock": low_shock,
                "high_shock": high_shock,
                "base_irr": base["irr"],
                "low_irr": low_case["irr"],
                "high_irr": high_case["irr"],
                "low_delta_irr": low_irr_delta,
                "high_delta_irr": high_irr_delta,
                "delta_irr": _magnitude(low_irr_delta, high_irr_delta),
                "base_dscr": base["dscr"],
                "low_dscr": low_case["dscr"],
                "high_dscr": high_case["dscr"],
                "low_delta_dscr": low_dscr_delta,
                "high_delta_dscr": high_dscr_delta,
                "delta_dscr": _magnitude(low_dscr_delta, high_dscr_delta),
                "evidence_that_would_change_this": evidence,
                "not_computable": {
                    "low": low_case["not_computable"],
                    "high": high_case["not_computable"],
                },
            }
        )

    drivers.sort(
        key=lambda item: (
            item["delta_irr"] is not None,
            item["delta_irr"] if item["delta_irr"] is not None else -1.0,
            item["delta_dscr"] if item["delta_dscr"] is not None else -1.0,
        ),
        reverse=True,
    )
    for rank, driver in enumerate(drivers, start=1):
        driver["rank"] = rank

    assumptions = normalized_assumptions(deal_inputs)
    assumptions.update(
        {
            "supplied_spans": dict(spans),
            "sweep_method": "one driver at a time; interactions are not modeled",
            "ranking_method": "maximum absolute endpoint delta IRR, then delta DSCR",
        }
    )
    return {
        "honesty_label": (
            "CONVENTION: one-at-a-time sensitivity, not a probability or prediction"
        ),
        "base_case": {
            "irr": base["irr"],
            "dscr": base["dscr"],
            "not_computable": base["not_computable"],
        },
        "ranked_drivers": drivers,
        "top_3": [
            {
                "rank": driver["rank"],
                "driver": driver["driver"],
                "delta_irr": driver["delta_irr"],
                "delta_dscr": driver["delta_dscr"],
                "evidence_that_would_change_this": driver[
                    "evidence_that_would_change_this"
                ],
            }
            for driver in drivers[:3]
        ],
        "assumptions": assumptions,
        "general_honesty_label": HONESTY_LABEL,
    }
