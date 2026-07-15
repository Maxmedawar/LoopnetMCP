"""Incentive-expiration and clawback screening for valuation workpapers.

The calculation treats the supplied NOI as including every listed incentive and
then removes each incentive's annual value on its stated expiration date.  It
does not interpret eligibility, renewal rights, tax character, or clawback
language.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
import math
from typing import Any


DISCLAIMER = (
    "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
)
ALLOWED_TYPES = frozenset({"abatement", "pilot", "tif", "credit"})


def _number(value: Any, label: str, *, non_negative: bool = True) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number) or (non_negative and number < 0):
        qualifier = " non-negative" if non_negative else ""
        raise ValueError(f"{label} must be a finite{qualifier} number")
    return number


def _money_range(value: Any, label: str) -> dict[str, float]:
    """Normalize a scalar, low/high mapping, or two/three-value sequence."""

    if isinstance(value, Mapping):
        low = _number(value.get("low"), f"{label}.low")
        high = _number(value.get("high"), f"{label}.high")
        base = _number(value.get("base", (low + high) / 2), f"{label}.base")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
        if len(values) not in {2, 3}:
            raise ValueError(f"{label} sequence must contain two or three values")
        low = _number(values[0], f"{label}[0]")
        high = _number(values[-1], f"{label}[-1]")
        base = _number(values[1], f"{label}[1]") if len(values) == 3 else (low + high) / 2
    else:
        low = high = base = _number(value, label)
    if not low <= base <= high:
        raise ValueError(f"{label} must satisfy low <= base <= high")
    return {"low": low, "base": base, "high": high}


def _cents(value: Any, label: str) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative whole number of cents")
    try:
        cents = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative whole number of cents") from exc
    if not cents.is_finite() or cents < 0 or cents != cents.to_integral_value():
        raise ValueError(f"{label} must be a non-negative whole number of cents")
    return int(cents)


def _expiry(value: Any, label: str) -> tuple[str, str]:
    """Return sortable ISO date and an exposed normalization convention."""

    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} must be an ISO date or four-digit year")
    raw = str(value).strip()
    if len(raw) == 4 and raw.isdigit():
        year = int(raw)
        if year < 1 or year > 9999:
            raise ValueError(f"{label} contains an invalid year")
        return f"{year:04d}-12-31", "year-only expiry normalized to December 31"
    try:
        normalized = date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD or a four-digit year") from exc
    return normalized, "ISO expiration date used as supplied"


def _display_money(value: float) -> float:
    return round(value, 2)


def _scalar_or_range(value: Mapping[str, float]) -> float | dict[str, float]:
    displayed = {key: _display_money(amount) for key, amount in value.items()}
    if displayed["low"] == displayed["base"] == displayed["high"]:
        return displayed["base"]
    return displayed


def incentive_cliff(
    incentives: Sequence[Mapping[str, Any]] | None,
    noi: Mapping[str, Any] | Sequence[float] | float | None,
) -> dict[str, Any]:
    """Build the annual NOI cliff timeline implied by incentive expirations.

    ``annual_value_cents`` is accumulated as an integer before conversion to
    dollars, so same-date events do not introduce fractional-cent drift.  A
    year-only expiration is conservatively displayed as December 31 of that
    year; no tax or legal conclusion is inferred from that convention.
    """

    try:
        if incentives is None or isinstance(incentives, (str, bytes, Mapping)):
            raise ValueError("incentives must be a sequence of incentive mappings")
        noi_range = _money_range(noi, "noi")
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(incentives):
            if not isinstance(item, Mapping):
                raise ValueError(f"incentives[{index}] must be a mapping")
            kind = str(item.get("type") or "").strip().lower()
            if kind not in ALLOWED_TYPES:
                raise ValueError(
                    f"incentives[{index}].type must be one of {sorted(ALLOWED_TYPES)}"
                )
            expiry, expiry_convention = _expiry(
                item.get("expires"), f"incentives[{index}].expires"
            )
            annual_cents = _cents(
                item.get("annual_value_cents"),
                f"incentives[{index}].annual_value_cents",
            )
            clawback = item.get("clawback_terms")
            has_clawback = clawback is not None and (
                not isinstance(clawback, str) or bool(clawback.strip())
            )
            normalized.append(
                {
                    "index": index,
                    "type": kind,
                    "expires": expiry,
                    "expiry_convention": expiry_convention,
                    "annual_value_cents": annual_cents,
                    "annual_value_dollars": annual_cents / 100,
                    "clawback_terms": clawback,
                    "clawback_exposure": has_clawback,
                }
            )

        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in normalized:
            grouped.setdefault(str(item["expires"]), []).append(item)

        running = dict(noi_range)
        cumulative_cents = 0
        timeline: list[dict[str, Any]] = []
        for expiry in sorted(grouped):
            expiring = grouped[expiry]
            cliff_cents = sum(int(item["annual_value_cents"]) for item in expiring)
            cumulative_cents += cliff_cents
            cliff_dollars = cliff_cents / 100
            before = {key: _display_money(value) for key, value in running.items()}
            after = {
                key: _display_money(value - cliff_dollars)
                for key, value in running.items()
            }
            timeline.append(
                {
                    "expires": expiry,
                    "expiry": expiry,
                    "expiring_incentives": expiring,
                    "annual_cliff_cents": cliff_cents,
                    "annual_cliff_dollars": cliff_dollars,
                    "cumulative_cliff_cents": cumulative_cents,
                    "cumulative_cliff_dollars": cumulative_cents / 100,
                    "noi_before_range": before,
                    "noi_after_range": after,
                    "noi_before": _scalar_or_range(before),
                    "noi_after": _scalar_or_range(after),
                }
            )
            running = after

        clawback_flags = [
            {
                "incentive_index": item["index"],
                "type": item["type"],
                "expires": item["expires"],
                "exposure": "UNQUANTIFIED",
                "clawback_terms": item["clawback_terms"],
                "warning": (
                    "Clawback language is present; triggering events, lookback, "
                    "security, and repayment amount require document review."
                ),
            }
            for item in normalized
            if item["clawback_exposure"]
        ]
        total_cents = sum(int(item["annual_value_cents"]) for item in normalized)
        return {
            "status": "ANALYTICAL_ESTIMATE",
            "disclaimer": DISCLAIMER,
            "input_noi_range": {
                key: _display_money(value) for key, value in noi_range.items()
            },
            "timeline": timeline,
            "total_annual_incentive_cents": total_cents,
            "total_annual_incentive_dollars": total_cents / 100,
            "final_noi_range": {
                key: _display_money(value) for key, value in running.items()
            },
            "final_noi": _scalar_or_range(running),
            "clawback_exposure": bool(clawback_flags),
            "clawback_exposure_flags": clawback_flags,
            "counsel_verify": True,
            "cpa_verify": True,
            "professional_verification_flags": {
                "counsel": {
                    "required": True,
                    "reason": (
                        "Counsel must verify eligibility, expiration, renewal, assignment, "
                        "and clawback terms in the governing documents."
                    ),
                },
                "cpa": {
                    "required": True,
                    "reason": (
                        "A CPA or tax adviser must verify tax character, timing, and NOI treatment."
                    ),
                },
            },
            "method": (
                "Assume starting NOI includes all listed incentives; group integer-cent "
                "annual values by normalized expiry and subtract each group from every "
                "NOI range endpoint."
            ),
            "range_note": "Ranges are preserved; incentive cliffs are exact supplied annual cents.",
        }
    except Exception as exc:
        return {"error": f"incentive_cliff: {exc}"}


__all__ = ["incentive_cliff"]
