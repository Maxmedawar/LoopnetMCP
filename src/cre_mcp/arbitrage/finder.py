"""Screen spaces for positive master-lease arbitrage spreads."""

from __future__ import annotations

import math
from typing import Any

from cre_mcp.arbitrage.economics import master_lease_arbitrage


class _OpportunityList(list[dict[str, Any]]):
    """List-compatible result retaining screening metadata even when empty."""

    def __init__(
        self,
        values: list[dict[str, Any]],
        screening_summary: dict[str, Any],
    ) -> None:
        super().__init__(values)
        self.screening_summary = screening_summary


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _from_space_or_defaults(
    space: dict[str, Any], defaults: dict[str, Any], key: str
) -> float | None:
    value = _number(space.get(key))
    return value if value is not None else _number(defaults.get(key))


def find_arbitrage_opportunities(
    spaces: list[dict[str, Any]],
    *,
    achievable_sublease_psf: float | None = None,
    defaults: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return positive-spread spaces ranked by modeled first-year net cash flow.

    Missing inputs are skipped rather than invented. Screening metadata is attached
    to each retained result and to the returned list's ``screening_summary``
    attribute, allowing callers to audit filtered or skipped spaces.
    """

    if not isinstance(spaces, list):
        raise ValueError("spaces must be a list of dictionaries")
    settings = dict(defaults or {})
    supplied_sublease_psf = _number(achievable_sublease_psf)
    opportunities: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    filtered_non_positive_count = 0

    optional_economics_keys = (
        "sublease_occupancy",
        "ti_psf",
        "free_rent_months",
        "mgmt_pct",
        "other_annual_costs",
        "term_years",
        "your_rent_escalation_pct",
        "sublease_escalation_pct",
        "personal_guarantee",
    )

    for index, raw_space in enumerate(spaces):
        if not isinstance(raw_space, dict):
            skipped.append(
                {
                    "space": f"space_{index + 1}",
                    "reason": "space must be a dictionary",
                }
            )
            continue
        space = dict(raw_space)
        identifier = str(
            space.get("id") or space.get("address") or f"space_{index + 1}"
        )
        sqft = _from_space_or_defaults(space, settings, "building_sqft")
        master_rent = _from_space_or_defaults(
            space, settings, "master_rent_annual"
        )
        asking_rent_psf = _from_space_or_defaults(
            space, settings, "asking_rent_psf"
        )
        if master_rent is None and asking_rent_psf is not None and sqft is not None:
            master_rent = asking_rent_psf * sqft

        space_sublease_psf = _number(space.get("achievable_sublease_psf"))
        sublease_psf = (
            space_sublease_psf
            if space_sublease_psf is not None
            else supplied_sublease_psf
        )
        if sublease_psf is None:
            sublease_psf = _number(settings.get("achievable_sublease_psf"))

        missing: list[str] = []
        if sqft is None:
            missing.append("building_sqft")
        if master_rent is None:
            missing.append("master_rent_annual or asking_rent_psf")
        if sublease_psf is None:
            missing.append("achievable_sublease_psf")
        if missing:
            skipped.append(
                {
                    "space": identifier,
                    "reason": f"missing required inputs: {', '.join(missing)}",
                }
            )
            continue

        economics_options: dict[str, Any] = {}
        for key in optional_economics_keys:
            if key in space:
                economics_options[key] = space[key]
            elif key in settings:
                economics_options[key] = settings[key]
        try:
            economics = master_lease_arbitrage(
                master_rent_annual=master_rent,
                building_sqft=sqft,
                sublease_rent_psf=sublease_psf,
                **economics_options,
            )
        except (TypeError, ValueError) as exc:
            skipped.append({"space": identifier, "reason": str(exc)})
            continue

        if economics["net_cash_flow_annual"] <= 0:
            filtered_non_positive_count += 1
            continue

        opportunity = dict(space)
        opportunity.update(
            {
                "master_rent_annual": master_rent,
                "achievable_sublease_psf": sublease_psf,
                "economics": economics,
                "opportunity_label": "positive_spread_candidate",
                "risk_label": (
                    "fragile"
                    if "thin_coverage" in economics["risk_flags"]
                    or "fragile_occupancy" in economics["risk_flags"]
                    else "underwrite_further"
                ),
                "caveat": (
                    "Modeled positive spread is not guaranteed; master rent remains "
                    "payable during vacancy or subtenant default."
                ),
            }
        )
        opportunities.append(opportunity)

    opportunities.sort(
        key=lambda item: (
            -float(item["economics"]["net_cash_flow_annual"]),
            str(item.get("address") or item.get("id") or "").casefold(),
        )
    )
    summary: dict[str, Any] = {
        "input_count": len(spaces),
        "positive_count": len(opportunities),
        "filtered_non_positive_count": filtered_non_positive_count,
        "filtered_count": filtered_non_positive_count,
        "skipped_missing_or_invalid_count": len(skipped),
        "skipped_spaces": skipped,
    }
    for rank, opportunity in enumerate(opportunities, start=1):
        opportunity["rank"] = rank
        opportunity["filtered_count"] = filtered_non_positive_count
        opportunity["filtered_non_positive_count"] = filtered_non_positive_count
        opportunity["skipped_missing_or_invalid_count"] = len(skipped)
        opportunity["screening_summary"] = summary

    return _OpportunityList(opportunities, summary)


__all__ = ["find_arbitrage_opportunities"]
