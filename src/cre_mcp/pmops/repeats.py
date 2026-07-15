"""Recurring-repair clusters and transparent repair-versus-replace framing.

Work orders are read from ``pm_workorders``; this module owns no table.  The
replacement convention is imported read-only from :mod:`cre_mcp.physical.rul`.
When a quantity basis is absent, only the physical unit-rate convention is
shown and no replacement total is fabricated.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.physical.rul import replacement_cost_convention

from .workorders import WorkOrderStore


DEFAULT_WINDOW_MONTHS = 24


def _iso_date(value: date | datetime | str | None, name: str) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _months(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("window_months must be a positive integer")
    return value


def _validate_quantity_inputs(building_sf: Any, floors: Any) -> None:
    """Reject malformed quantity inputs before cluster-dependent cost work."""

    if building_sf is not None:
        if isinstance(building_sf, bool):
            raise ValueError("building_sf must be a finite positive number")
        try:
            sf = float(building_sf)
        except (TypeError, ValueError) as exc:
            raise ValueError("building_sf must be a finite positive number") from exc
        if not isfinite(sf) or sf <= 0:
            raise ValueError("building_sf must be a finite positive number")
    if isinstance(floors, bool) or not isinstance(floors, int) or floors <= 0:
        raise ValueError("floors must be a positive integer")


def _subtract_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 - months
    year, zero_month = divmod(index, 12)
    month = zero_month + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _system(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("system must be a non-blank string when provided")
    return value.strip().casefold().replace("-", "_").replace(" ", "_")


def _usd_to_cents(value: Any) -> int:
    """Convert an exposed physical USD convention using decimal half-up cents."""

    return int(
        (Decimal(str(value)) * Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def _replacement_range(
    system: str,
    *,
    building_sf: float | None,
    floors: int,
    extent: float | int | None,
) -> dict[str, Any]:
    try:
        physical = replacement_cost_convention(
            system,
            building_sf=building_sf,
            floors=floors,
            extent=extent,
        )
    except KeyError as exc:
        return {
            "status": "unavailable_for_system",
            "system": system,
            "reason": str(exc),
            "physical_source": "cre_mcp.physical.rul.replacement_cost_convention",
        }
    except ValueError as exc:
        # Work-order systems are caller-authored operational vocabulary, so an
        # unsupported recorded system remains a disclosed convention gap.  Bad
        # supplied quantities, floors, or extents are input errors and must
        # cross the stable tool error boundary instead of masquerading as a
        # missing physical convention.
        if str(exc).startswith("unknown system"):
            return {
                "status": "unavailable_for_system",
                "system": system,
                "reason": str(exc),
                "physical_source": "cre_mcp.physical.rul.replacement_cost_convention",
            }
        raise

    rate_range_cents = {
        "low": _usd_to_cents(physical["low"] if physical["status"] == "unit_convention_only" else physical["rate_range"]["low"]),
        "high": _usd_to_cents(physical["high"] if physical["status"] == "unit_convention_only" else physical["rate_range"]["high"]),
        "unit": physical["unit"] if physical["status"] == "unit_convention_only" else physical["rate_range"]["unit"],
    }
    result: dict[str, Any] = {
        "status": physical["status"],
        "capex_system": physical["capex_system"],
        "rate_range_cents": rate_range_cents,
        "basis": physical["basis"],
        "source_note": physical["source_note"],
        "physical_source": "cre_mcp.physical.rul.replacement_cost_convention",
        "money_conversion": "physical USD values multiplied by 100 and rounded to integer cents, ROUND_HALF_UP",
    }
    if physical["status"] == "unit_convention_only":
        result.update(
            {
                "replacement_cost_range_cents": None,
                "quantity_required_for_total": True,
                "description": physical.get("description"),
            }
        )
        return result

    result.update(
        {
            "replacement_cost_range_cents": {
                "low": _usd_to_cents(physical["low"]),
                "high": _usd_to_cents(physical["high"]),
            },
            "quantity": physical["quantity"],
            "quantity_unit": physical["quantity_unit"],
            "quantity_note": physical["quantity_note"],
            "quantity_required_for_total": False,
            "input_scope_note": physical["input_scope_note"],
            "disclaimer": physical["disclaimer"],
        }
    )
    return result


def _framing(
    known_cost_cents: int,
    missing_cost_count: int,
    replacement: dict[str, Any],
) -> dict[str, Any]:
    cost_basis = "complete_recorded_cost" if missing_cost_count == 0 else "partial_recorded_cost"
    replacement_range = replacement.get("replacement_cost_range_cents")
    if not isinstance(replacement_range, dict):
        return {
            "status": "not_comparable_without_replacement_total",
            "recorded_repair_cost_cents": known_cost_cents,
            "recorded_cost_basis": cost_basis,
            "replacement_cost_range_cents": None,
            "arithmetic": (
                "A unit-rate convention is shown, but replacement total and ratios are withheld "
                "until building_sf/quantity is supplied."
            ),
            "root_cause_review_required": True,
        }

    low = int(replacement_range["low"])
    high = int(replacement_range["high"])
    if known_cost_cents >= high:
        band = "recorded_repairs_at_or_above_replacement_high"
    elif known_cost_cents >= low:
        band = "recorded_repairs_within_replacement_range"
    else:
        band = "recorded_repairs_below_replacement_low"
    if missing_cost_count:
        band = f"partial_{band}"
    return {
        "status": band,
        "recorded_repair_cost_cents": known_cost_cents,
        "recorded_cost_basis": cost_basis,
        "replacement_cost_range_cents": {"low": low, "high": high},
        "repair_cost_as_percent_of_replacement_low": (
            round(known_cost_cents * 100 / low, 2) if low else None
        ),
        "repair_cost_as_percent_of_replacement_high": (
            round(known_cost_cents * 100 / high, 2) if high else None
        ),
        "arithmetic": {
            "known_repair_cost_cents": known_cost_cents,
            "replacement_low_cents": low,
            "replacement_high_cents": high,
            "low_ratio_formula": "100 * known_repair_cost_cents / replacement_low_cents",
            "high_ratio_formula": "100 * known_repair_cost_cents / replacement_high_cents",
        },
        "interpretation": (
            "Cost-band framing only, not a replace recommendation; verify remaining useful life, "
            "failure mode, quantity, and root cause."
        ),
        "root_cause_review_required": True,
    }


def repeat_repair_analysis(
    system: str | None = None,
    window_months: int = DEFAULT_WINDOW_MONTHS,
    as_of: date | datetime | str | None = None,
    building_sf: float | None = None,
    floors: int = 1,
    extent: float | int | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Find asset/system clusters with two or more orders in the selected window."""

    months = _months(window_months)
    _validate_quantity_inputs(building_sf, floors)
    on_date = _iso_date(as_of, "as_of")
    window_start = _subtract_months(on_date, months)
    normalized_system = _system(system) if system is not None else None
    rows = WorkOrderStore(db_path).list_workorders(
        system=normalized_system,
        opened_from=window_start,
        opened_to=on_date,
    )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["asset"]), str(row["system"])), []).append(row)

    clusters: list[dict[str, Any]] = []
    for (asset, cluster_system), orders in grouped.items():
        if len(orders) < 2:
            continue
        known_costs = [int(order["cost_cents"]) for order in orders if order["cost_cents"] is not None]
        missing_cost_count = len(orders) - len(known_costs)
        replacement = _replacement_range(
            cluster_system,
            building_sf=building_sf,
            floors=floors,
            extent=extent,
        )
        known_cost_total = sum(known_costs)
        replacement_total = replacement.get("replacement_cost_range_cents")
        clusters.append(
            {
                "asset": asset,
                "system": cluster_system,
                "order_count": len(orders),
                "repeat_order_count": len(orders) - 1,
                "first_opened": orders[0]["opened"],
                "last_opened": orders[-1]["opened"],
                "units": sorted({str(order["unit"]) for order in orders if order["unit"] is not None}),
                "workorder_ids": [order["workorder_id"] for order in orders],
                "cumulative_cost_cents": known_cost_total,
                "missing_cost_count": missing_cost_count,
                "replacement_cost_range_cents": replacement_total,
                "recorded_repair_cost": {
                    "known_cost_order_count": len(known_costs),
                    "missing_cost_order_count": missing_cost_count,
                    "cumulative_known_cost_cents": known_cost_total,
                    "coverage_complete": missing_cost_count == 0,
                    "arithmetic": "sum(cost_cents) for recorded non-null costs in cluster",
                },
                "replacement_cost_convention": replacement,
                "repair_vs_replace": _framing(
                    known_cost_total, missing_cost_count, replacement
                ),
                "root_cause_prompt": (
                    "Investigate common failure mode, installation quality, maintenance history, "
                    "and whether repeated repairs address symptoms rather than root cause."
                ),
            }
        )

    clusters.sort(
        key=lambda row: (
            -int(row["order_count"]),
            -int(row["recorded_repair_cost"]["cumulative_known_cost_cents"]),
            str(row["asset"]),
            str(row["system"]),
        )
    )
    return {
        "system_filter": normalized_system,
        "as_of": on_date.isoformat(),
        "window_start": window_start.isoformat(),
        "window_months": months,
        "orders_in_window": len(rows),
        "repeat_cluster_threshold_orders": 2,
        "cluster_grouping": "asset + system",
        "status": "repeat_clusters_found" if clusters else "no_repeat_clusters",
        "clusters": clusters,
        "conventions": {
            "window": "inclusive calendar-month lookback through as_of",
            "replacement_source": "read-only cre_mcp.physical.rul.replacement_cost_convention",
            "money_unit": "integer cents",
            "quantity_rule": (
                "No replacement total is produced without building_sf; only the physical unit-rate "
                "range is shown."
            ),
            "decision_rule": "framing only; no automatic repair/replace recommendation",
        },
    }


__all__ = ["DEFAULT_WINDOW_MONTHS", "repeat_repair_analysis"]
