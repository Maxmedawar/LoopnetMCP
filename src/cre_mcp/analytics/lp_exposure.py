"""Limited-partner portfolio exposure rollups and concentration screens.

This module is deliberately a look-through calculator, not a risk rating.  It
uses only caller-supplied position data and labels every default threshold as a
screening convention.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any


DEFAULT_THRESHOLDS: dict[str, float] = {
    "sponsor": 0.25,
    "market": 0.25,
    "asset_type": 0.25,
    "maturity_year": 0.25,
    "tenant_concentration": 0.25,
}

_POSITION_FIELDS = frozenset(
    {
        "sponsor",
        "asset_type",
        "market",
        "equity_cents",
        "debt_maturity",
        "tenant_concentration",
    }
)
_THRESHOLD_ALIASES = {
    "sponsor": "sponsor",
    "sponsor_share": "sponsor",
    "market": "market",
    "market_share": "market",
    "asset_type": "asset_type",
    "asset_type_share": "asset_type",
    "maturity_year": "maturity_year",
    "maturity_year_share": "maturity_year",
    "debt_maturity": "maturity_year",
    "tenant": "tenant_concentration",
    "tenant_concentration": "tenant_concentration",
}


def _sequence(value: Any, *, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be a sequence")
    return value


def _required_text(value: Any, *, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} cannot be null")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _equity_cents(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _ratio(value: Any, *, name: str, allow_percent: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if allow_percent and 1 < result <= 100:
        result /= 100
    if result < 0 or result > 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _maturity_year(value: Any) -> tuple[str, str | None]:
    if value is None:
        return "UNKNOWN", None
    if isinstance(value, bool):
        return "UNKNOWN", "boolean is not a recognized debt maturity"
    if isinstance(value, datetime):
        return str(value.date().year), None
    if isinstance(value, date):
        return str(value.year), None
    if isinstance(value, int):
        if 1900 <= value <= 3000:
            return str(value), None
        return "UNKNOWN", f"integer year {value!r} is outside 1900-3000"
    normalized = str(value).strip()
    if not normalized:
        return "UNKNOWN", "blank debt maturity is not recognized; use null for unknown"
    if len(normalized) == 4 and normalized.isdigit():
        year = int(normalized)
        if 1900 <= year <= 3000:
            return normalized, None
    candidates = (normalized, f"{normalized}-01" if len(normalized) == 7 else "")
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return str(date.fromisoformat(candidate).year), None
        except ValueError:
            continue
    return "UNKNOWN", f"{value!r} is not an ISO date, YYYY-MM, or YYYY"


def _normalize_thresholds(
    supplied: Mapping[str, Any] | None,
) -> tuple[dict[str, float], list[str]]:
    result = dict(DEFAULT_THRESHOLDS)
    if supplied is None:
        return result, []
    if not isinstance(supplied, Mapping):
        raise ValueError("thresholds must be a mapping or null")
    unrecognized = [
        f"thresholds.{key}" for key in supplied if key not in _THRESHOLD_ALIASES
    ]
    for raw_key, raw_value in supplied.items():
        target = _THRESHOLD_ALIASES.get(raw_key)
        if target is None:
            continue
        result[target] = _ratio(raw_value, name=f"thresholds.{raw_key}")
    return result, sorted(unrecognized)


def _rollup(
    positions: Sequence[Mapping[str, Any]],
    field: str,
    total_equity_cents: int,
) -> dict[str, dict[str, int | float | None]]:
    amounts: dict[str, int] = {}
    counts: dict[str, int] = {}
    for position in positions:
        label = str(position[field])
        amounts[label] = amounts.get(label, 0) + int(position["equity_cents"])
        counts[label] = counts.get(label, 0) + 1
    return {
        label: {
            "equity_cents": amount,
            "portfolio_share": (
                amount / total_equity_cents if total_equity_cents else None
            ),
            "position_count": counts[label],
        }
        for label, amount in sorted(amounts.items())
    }


def _lp_portfolio_exposure(
    positions: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Roll LP equity exposure up by sponsor, market, type, and maturity year.

    ``tenant_concentration`` is a position-level decimal fraction (values from
    1 through 100 are accepted as percentages).  A null debt maturity or tenant
    concentration remains explicitly unknown.  Unknown fields are surfaced and
    cause a boundary-style error instead of being silently discarded.
    """

    rows = _sequence(positions, name="positions")
    normalized_thresholds, threshold_unknown = _normalize_thresholds(thresholds)
    unrecognized_fields = list(threshold_unknown)
    normalized: list[dict[str, Any]] = []
    unrecognized_values: list[dict[str, Any]] = []
    percent_normalizations: list[str] = []

    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"positions[{index}] must be a mapping")
        unrecognized_fields.extend(
            f"positions[{index}].{key}" for key in raw if key not in _POSITION_FIELDS
        )
        sponsor = _required_text(raw.get("sponsor"), name=f"positions[{index}].sponsor")
        asset_type = _required_text(
            raw.get("asset_type"), name=f"positions[{index}].asset_type"
        )
        market = _required_text(raw.get("market"), name=f"positions[{index}].market")
        equity = _equity_cents(
            raw.get("equity_cents"), name=f"positions[{index}].equity_cents"
        )
        year, maturity_issue = _maturity_year(raw.get("debt_maturity"))
        if maturity_issue is not None:
            unrecognized_values.append(
                {
                    "path": f"positions[{index}].debt_maturity",
                    "value": raw.get("debt_maturity"),
                    "reason": maturity_issue,
                    "rollup_bucket": "UNKNOWN",
                }
            )
        raw_tenant = raw.get("tenant_concentration")
        tenant_ratio = None
        if raw_tenant is not None:
            tenant_ratio = _ratio(
                raw_tenant,
                name=f"positions[{index}].tenant_concentration",
                allow_percent=True,
            )
            try:
                if float(raw_tenant) > 1:
                    percent_normalizations.append(
                        f"positions[{index}].tenant_concentration normalized from percent to decimal"
                    )
            except (TypeError, ValueError):
                pass
        normalized.append(
            {
                "position_index": index,
                "sponsor": sponsor,
                "asset_type": asset_type,
                "market": market,
                "equity_cents": equity,
                "maturity_year": year,
                "tenant_concentration": tenant_ratio,
            }
        )

    if unrecognized_fields:
        return {
            "error": "unrecognized input fields",
            "unrecognized_inputs": sorted(set(unrecognized_fields)),
        }

    total_equity = sum(int(row["equity_cents"]) for row in normalized)
    rollups = {
        "sponsor": _rollup(normalized, "sponsor", total_equity),
        "market": _rollup(normalized, "market", total_equity),
        "asset_type": _rollup(normalized, "asset_type", total_equity),
        "maturity_year": _rollup(normalized, "maturity_year", total_equity),
    }
    flags: list[dict[str, Any]] = []
    for dimension in ("sponsor", "market", "asset_type", "maturity_year"):
        threshold = normalized_thresholds[dimension]
        for label, exposure in rollups[dimension].items():
            if dimension == "maturity_year" and label == "UNKNOWN":
                continue
            share = exposure["portfolio_share"]
            if share is not None and share >= threshold:
                flags.append(
                    {
                        "dimension": dimension,
                        "value": label,
                        "equity_cents": exposure["equity_cents"],
                        "portfolio_share": share,
                        "threshold": threshold,
                        "rule": "portfolio_share >= exposed screening threshold",
                    }
                )
    tenant_threshold = normalized_thresholds["tenant_concentration"]
    for row in normalized:
        concentration = row["tenant_concentration"]
        if concentration is not None and concentration >= tenant_threshold:
            flags.append(
                {
                    "dimension": "tenant_concentration",
                    "value": f"position[{row['position_index']}]",
                    "sponsor": row["sponsor"],
                    "market": row["market"],
                    "equity_cents": row["equity_cents"],
                    "tenant_concentration": concentration,
                    "threshold": tenant_threshold,
                    "rule": "tenant_concentration >= exposed screening threshold",
                }
            )

    return {
        "total_equity_cents": total_equity,
        "positions": normalized,
        "exposure_rollups": rollups,
        "by_sponsor": rollups["sponsor"],
        "by_market": rollups["market"],
        "by_asset_type": rollups["asset_type"],
        "by_maturity_year": rollups["maturity_year"],
        "concentration_flags": flags,
        "thresholds": normalized_thresholds,
        "threshold_basis": "caller-supplied or exposed screening conventions; not risk limits",
        "unknown_debt_maturity_equity_cents": int(
            rollups["maturity_year"].get("UNKNOWN", {}).get("equity_cents", 0)
        ),
        "unknown_tenant_concentration_equity_cents": sum(
            int(row["equity_cents"])
            for row in normalized
            if row["tenant_concentration"] is None
        ),
        "unrecognized_inputs": [],
        "unrecognized_values": unrecognized_values,
        "normalizations": percent_normalizations,
        "honest_gaps": [
            "Exposure is measured by contributed equity cents only; look-through NAV, unfunded commitments, guarantees, and cross-collateralization are not inferred.",
            "Concentration flags are mechanical screens, not investment-risk conclusions.",
        ],
    }


def lp_portfolio_exposure(
    positions: Sequence[Mapping[str, Any]] | None,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Stable public boundary for the LP exposure calculator."""

    try:
        return _lp_portfolio_exposure(positions, thresholds)  # type: ignore[arg-type]
    except Exception as exc:
        message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
        return {"error": f"lp_portfolio_exposure: {message or exc.__class__.__name__}"}


__all__ = ["DEFAULT_THRESHOLDS", "lp_portfolio_exposure"]
