"""Evidence-first appraisal divergence packaging for a lender ROV process.

This module performs transparent arithmetic and evidence assembly only.  It does
not offer an appraisal opinion, select a value, or speak as an appraiser.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any


ROV_FRAMING = (
    "submit through lender's ROV process; we do not impersonate a licensed appraiser"
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(
            str(value).replace("$", "").replace(",", "").replace("%", "").strip()
        )
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _cap_percent(value: Any) -> float | None:
    """Return a cap rate in percentage points (0.06 and 6 both become 6)."""

    parsed = _number(value)
    if parsed is None or parsed < 0:
        return None
    return parsed * 100 if 0 < parsed < 1 else parsed


def _first_number(record: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        parsed = _number(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _market_median(
    comps: Sequence[Any],
    keys: tuple[str, ...],
    *,
    cap_rate: bool = False,
) -> float | None:
    values: list[float] = []
    for item in comps:
        if not isinstance(item, Mapping):
            continue
        raw = next((item.get(key) for key in keys if item.get(key) is not None), None)
        value = _cap_percent(raw) if cap_rate else _number(raw)
        if value is not None:
            values.append(value)
    return round(float(median(values)), 6) if values else None


def _numeric_divergence(
    field: str,
    their_input: float | None,
    our_evidence: float | None,
    *,
    units: str,
    source: str,
    high_threshold: float = 0.10,
    moderate_threshold: float = 0.05,
) -> dict[str, Any]:
    delta = None
    delta_pct = None
    if their_input is not None and our_evidence is not None:
        delta = round(our_evidence - their_input, 6)
        if their_input != 0:
            delta_pct = round(delta / abs(their_input), 6)
    if delta is None:
        materiality = "not_assessable"
    elif delta_pct is None:
        materiality = "high" if delta != 0 else "none"
    elif abs(delta_pct) >= high_threshold:
        materiality = "high"
    elif abs(delta_pct) >= moderate_threshold:
        materiality = "moderate"
    elif delta != 0:
        materiality = "low"
    else:
        materiality = "none"
    return {
        "field": field,
        "their_input": their_input,
        "our_evidence": our_evidence,
        "delta": delta,
        "delta_pct": delta_pct,
        "units": units,
        "materiality": materiality,
        "evidence_basis": source,
    }


def _cap_divergence(
    their_cap: float | None,
    market_cap: float | None,
) -> dict[str, Any]:
    row = _numeric_divergence(
        "cap_rate_used",
        their_cap,
        market_cap,
        units="percentage_points",
        source="median cap rate among supplied market_comps with a cap-rate field",
        high_threshold=0.16,
        moderate_threshold=0.08,
    )
    row["delta_bps"] = (
        round(float(row["delta"]) * 100, 2) if row["delta"] is not None else None
    )
    # Cap-rate materiality is conventionally easier to read in basis points.
    basis_points = abs(row["delta_bps"]) if row["delta_bps"] is not None else None
    if basis_points is None:
        row["materiality"] = "not_assessable"
    elif basis_points >= 100:
        row["materiality"] = "high"
    elif basis_points >= 50:
        row["materiality"] = "moderate"
    elif basis_points > 0:
        row["materiality"] = "low"
    else:
        row["materiality"] = "none"
    return row


def _comp_identity(comp: Any) -> str:
    if isinstance(comp, Mapping):
        for key in ("id", "comp_id", "address", "name"):
            value = comp.get(key)
            if value not in (None, ""):
                return str(value).strip().casefold()
        return repr(sorted((str(key), repr(value)) for key, value in comp.items()))
    return str(comp).strip().casefold()


def _comps_divergence(their_comps: list[Any], market_comps: list[Any]) -> dict[str, Any]:
    their_ids = {_comp_identity(comp) for comp in their_comps}
    market_ids = {_comp_identity(comp) for comp in market_comps}
    overlap = sorted(their_ids & market_ids)
    omitted = [comp for comp in market_comps if _comp_identity(comp) not in their_ids]
    count_delta = len(market_comps) - len(their_comps)
    if not market_comps:
        materiality = "not_assessable"
    elif their_comps and len(overlap) == len(market_ids) == len(their_ids):
        materiality = "none"
    elif not overlap:
        materiality = "high"
    else:
        materiality = "moderate"
    return {
        "field": "comps_used",
        "their_input": their_comps,
        "our_evidence": market_comps,
        "delta": count_delta,
        "delta_pct": (
            round(count_delta / abs(len(their_comps)), 6) if their_comps else None
        ),
        "units": "comparable_count",
        "materiality": materiality,
        "evidence_basis": "identity/count comparison of supplied appraisal and market comps",
        "their_comp_count": len(their_comps),
        "market_comp_count": len(market_comps),
        "overlap_count": len(overlap),
        "additional_market_comps": omitted,
        "note": (
            "Count and identity differences are evidence-screening flags only; "
            "a licensed appraiser must judge comparability and adjustments."
        ),
    }


def challenge_appraisal(
    appraisal: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Build a line-by-line reconsideration-of-value evidence package.

    Missing evidence remains explicit.  The function does not invent expenses,
    market cap rates, adjustments, or an alternative appraisal conclusion.
    """

    if not isinstance(appraisal, Mapping):
        raise ValueError("appraisal must be a plain dictionary")
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence must be a plain dictionary")

    their_value = _number(appraisal.get("value"))
    their_cap = _cap_percent(appraisal.get("cap_rate_used"))
    their_rent = _number(appraisal.get("rent_psf_used"))
    their_expenses = _number(appraisal.get("expenses_used"))
    their_comps_raw = appraisal.get("comps_used")
    their_comps = (
        list(their_comps_raw)
        if isinstance(their_comps_raw, Sequence)
        and not isinstance(their_comps_raw, (str, bytes))
        else []
    )

    our_rent = _number(evidence.get("our_rent_roll_psf"))
    our_noi = _number(evidence.get("our_noi"))
    our_expenses = _first_number(
        evidence,
        ("our_expenses", "our_operating_expenses", "expense_total"),
    )
    market_raw = evidence.get("market_comps")
    market_comps = (
        list(market_raw)
        if isinstance(market_raw, Sequence) and not isinstance(market_raw, (str, bytes))
        else []
    )
    market_cap = _market_median(
        market_comps,
        ("cap_rate", "cap_rate_used", "cap_rate_pct"),
        cap_rate=True,
    )
    market_rent = _market_median(
        market_comps,
        ("rent_psf", "rent_psf_used", "asking_rent_psf"),
    )

    indicated_value = None
    if our_noi is not None and their_cap is not None and their_cap > 0:
        indicated_value = round(our_noi / (their_cap / 100), 2)
    implied_noi = None
    if their_value is not None and their_cap is not None:
        implied_noi = round(their_value * (their_cap / 100), 2)

    rows = [
        _numeric_divergence(
            "value",
            their_value,
            indicated_value,
            units="currency",
            source="our_noi capitalized only at the appraisal's own cap_rate_used",
        ),
        _cap_divergence(their_cap, market_cap),
        _numeric_divergence(
            "rent_psf_used",
            their_rent,
            our_rent,
            units="currency_per_square_foot",
            source="supplied our_rent_roll_psf",
        ),
        _numeric_divergence(
            "expenses_used",
            their_expenses,
            our_expenses,
            units="currency",
            source=(
                "optional supplied operating-expense evidence; our_noi alone does not "
                "prove a gross expense total"
            ),
        ),
        _comps_divergence(their_comps, market_comps),
        _numeric_divergence(
            "noi_implied_by_value_and_cap_rate",
            implied_noi,
            our_noi,
            units="currency_per_year",
            source="appraisal value multiplied by appraisal cap rate versus supplied our_noi",
        ),
    ]

    # Market rent is corroborative context, not a substitute for the rent roll.
    rent_row = rows[2]
    rent_row["market_comp_median_rent_psf"] = market_rent
    rent_row["market_comp_sample_size"] = sum(
        1
        for comp in market_comps
        if isinstance(comp, Mapping)
        and _first_number(comp, ("rent_psf", "rent_psf_used", "asking_rent_psf"))
        is not None
    )
    rows[1]["market_comp_sample_size"] = sum(
        1
        for comp in market_comps
        if isinstance(comp, Mapping)
        and any(comp.get(key) is not None for key in ("cap_rate", "cap_rate_used", "cap_rate_pct"))
    )

    material_rows = [
        row for row in rows if row["materiality"] in {"moderate", "high"}
    ]
    missing = [row["field"] for row in rows if row["materiality"] == "not_assessable"]
    return {
        "package_type": "reconsideration_of_value_evidence_package",
        "status": "DIVERGENCES_FOUND" if material_rows else "NO_MATERIAL_DIVERGENCE_SHOWN",
        "divergence_table": rows,
        "material_divergence_count": len(material_rows),
        "missing_or_unassessable": missing,
        "appraisal_inputs": dict(appraisal),
        "submitted_evidence": dict(evidence),
        "sample_sizes": {
            "appraisal_comps": len(their_comps),
            "market_comps": len(market_comps),
        },
        "requested_review": (
            "Ask the lender and its appraiser to review the cited factual inputs, source "
            "documents, comp selection, and arithmetic through the lender's formal ROV channel."
        ),
        "rov_framing": ROV_FRAMING,
        "mandatory_caveat": ROV_FRAMING,
        "honesty": (
            "This assembles recorded evidence and arithmetic; it is not an appraisal, "
            "appraisal review, USPAP opinion, value conclusion, or promise of a revised value."
        ),
    }


__all__ = ["ROV_FRAMING", "challenge_appraisal"]
