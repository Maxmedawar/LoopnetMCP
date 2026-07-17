"""Uncalibrated stale-listing and negotiability heuristics."""

from __future__ import annotations

from typing import Any, Iterable

from ._time import maybe_datetime
from .snapshots import changes_from_snapshots

STALE_DOM_DAYS = 90
VERY_STALE_DOM_DAYS = 180


def stale_listing_signals(
    snapshots: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Infer a transparent negotiability hypothesis from persisted snapshots.

    This is a HEURISTIC CONVENTION and is explicitly UNCALIBRATED. DOM and asking
    price behavior do not prove seller motivation or an achievable discount.
    """
    ordered = sorted(
        (dict(snapshot) for snapshot in snapshots),
        key=lambda item: (str(item.get("captured_at") or ""), int(item.get("snapshot_id") or 0)),
    )
    listing_key = (
        str(ordered[-1].get("listing_key"))
        if ordered and ordered[-1].get("listing_key") is not None
        else None
    )
    convention = {
        "label": "HEURISTIC CONVENTION — UNCALIBRATED",
        "stale_dom_days": STALE_DOM_DAYS,
        "very_stale_dom_days": VERY_STALE_DOM_DAYS,
        "score_rules": {
            "dom_90_to_179": 2,
            "dom_180_plus": 3,
            "one_price_cut": 1,
            "two_plus_price_cuts": 2,
            "one_plus_cuts_per_30_days": 1,
            "two_plus_cuts_per_30_days": 2,
        },
    }
    if not ordered:
        return {
            "listing_key": listing_key,
            "negotiability_signal": "insufficient_data",
            "heuristic_score": 0,
            "evidence": {
                "snapshot_count": 0,
                "latest_dom": None,
                "price_cut_count": 0,
                "price_cut_velocity_per_30_days": None,
                "cumulative_price_change_pct": None,
            },
            "convention": convention,
            "thin_data": True,
            "note": "No snapshots exist; no stale-listing inference can be made.",
        }

    changes = changes_from_snapshots(ordered)
    cuts = [
        event
        for event in changes
        if event["event_type"] == "price_change" and event["direction"] == "decrease"
    ]
    latest_dom_value = ordered[-1].get("dom")
    try:
        latest_dom = int(latest_dom_value) if latest_dom_value is not None else None
    except (TypeError, ValueError):
        latest_dom = None
    first_time = maybe_datetime(ordered[0].get("captured_at"))
    last_time = maybe_datetime(ordered[-1].get("captured_at"))
    observation_days = (
        max((last_time - first_time).total_seconds() / 86400, 0.0)
        if first_time is not None and last_time is not None
        else None
    )
    velocity = (
        round(len(cuts) * 30 / observation_days, 2)
        if observation_days is not None and observation_days > 0
        else None
    )
    prices = [
        float(snapshot["price"])
        for snapshot in ordered
        if snapshot.get("price") is not None
    ]
    cumulative = (
        round(((prices[-1] - prices[0]) / prices[0]) * 100, 2)
        if len(prices) >= 2 and prices[0] != 0
        else None
    )

    score = 0
    if latest_dom is not None:
        if latest_dom >= VERY_STALE_DOM_DAYS:
            score += 3
        elif latest_dom >= STALE_DOM_DAYS:
            score += 2
    if len(cuts) >= 2:
        score += 2
    elif len(cuts) == 1:
        score += 1
    if velocity is not None:
        if velocity >= 2:
            score += 2
        elif velocity >= 1:
            score += 1

    if score >= 5:
        signal = "strong"
    elif score >= 3:
        signal = "moderate"
    elif score >= 1:
        signal = "weak"
    else:
        signal = "none"
    thin_reasons = []
    if len(ordered) < 2:
        thin_reasons.append("only one snapshot")
    if latest_dom is None:
        thin_reasons.append("no DOM data")
    if observation_days is None or observation_days <= 0:
        thin_reasons.append("no measurable observation window")
    return {
        "listing_key": listing_key,
        "negotiability_signal": signal,
        "heuristic_score": score,
        "evidence": {
            "snapshot_count": len(ordered),
            "latest_dom": latest_dom,
            "price_cut_count": len(cuts),
            "price_cut_velocity_per_30_days": velocity,
            "cumulative_price_change_pct": cumulative,
            "observation_days": round(observation_days, 2) if observation_days is not None else None,
        },
        "convention": convention,
        "thin_data": bool(thin_reasons),
        "note": (
            "Asking-price and DOM behavior may support a negotiation hypothesis, but this "
            "uncalibrated signal does not establish seller motivation or discountability."
            + (f" Thin data: {', '.join(thin_reasons)}." if thin_reasons else "")
        ),
    }


__all__ = ["STALE_DOM_DAYS", "VERY_STALE_DOM_DAYS", "stale_listing_signals"]
