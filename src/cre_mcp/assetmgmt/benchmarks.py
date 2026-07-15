"""Convention-labeled portfolio underperformance screens.

The defaults are deliberately exposed screening thresholds, not represented as
market facts.  Peer z-scores are calculated only within asset-type cohorts of
at least five observations; smaller cohorts receive no synthetic statistics.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import fmean, pstdev
from typing import Any


_METRICS = ("occupancy", "opex_psf", "collections_rate", "noi_psf")
_METRIC_ALIASES = {
    "occupancy": ("occupancy", "occupancy_rate"),
    "opex_psf": ("opex_psf", "opex_psf_cents"),
    "collections_rate": ("collections_rate", "collection_rate"),
    "noi_psf": ("noi_psf", "noi_psf_cents"),
}
_ASSET_META_KEYS = frozenset({"deal_id", "asset", "asset_type", "metrics"})
_BENCHMARK_RULE_KEYS = frozenset({"direction", "threshold", "minimum", "maximum"})
_RATE_METRICS = frozenset({"occupancy", "collections_rate"})
_MONEY_METRICS = frozenset({"opex_psf", "noi_psf"})
_DIRECTIONS = {
    "occupancy": "minimum",
    "opex_psf": "maximum",
    "collections_rate": "minimum",
    "noi_psf": "minimum",
}

# These are intentionally round, inspectable conventions.  They are not market
# survey data and must not be presented as such by downstream callers.
DEFAULT_BENCHMARK_CONVENTIONS: dict[str, dict[str, dict[str, Any]]] = {
    "default": {
        "occupancy": {"direction": "minimum", "threshold": 0.90},
        "opex_psf": {"direction": "maximum", "threshold": 1_200},
        "collections_rate": {"direction": "minimum", "threshold": 0.95},
        "noi_psf": {"direction": "minimum", "threshold": 1_000},
    },
    "industrial": {
        "occupancy": {"direction": "minimum", "threshold": 0.90},
        "opex_psf": {"direction": "maximum", "threshold": 700},
        "collections_rate": {"direction": "minimum", "threshold": 0.97},
        "noi_psf": {"direction": "minimum", "threshold": 900},
    },
    "office": {
        "occupancy": {"direction": "minimum", "threshold": 0.85},
        "opex_psf": {"direction": "maximum", "threshold": 1_500},
        "collections_rate": {"direction": "minimum", "threshold": 0.95},
        "noi_psf": {"direction": "minimum", "threshold": 1_000},
    },
    "retail": {
        "occupancy": {"direction": "minimum", "threshold": 0.88},
        "opex_psf": {"direction": "maximum", "threshold": 1_200},
        "collections_rate": {"direction": "minimum", "threshold": 0.96},
        "noi_psf": {"direction": "minimum", "threshold": 1_000},
    },
    "multifamily": {
        "occupancy": {"direction": "minimum", "threshold": 0.92},
        "opex_psf": {"direction": "maximum", "threshold": 900},
        "collections_rate": {"direction": "minimum", "threshold": 0.97},
        "noi_psf": {"direction": "minimum", "threshold": 1_100},
    },
}


def _finite_number(value: Any, *, name: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    if isinstance(value, int):
        result = float(value)
    elif isinstance(value, float):
        result = value
    else:
        try:
            result = float(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _rate(value: Any, *, name: str) -> float:
    result = _finite_number(value, name=name)
    if abs(result) > 1:
        result /= 100
    if result < 0 or result > 1:
        raise ValueError(f"{name} must be between 0 and 1 (or 0 and 100 percent)")
    return result


def _money_psf(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be integer cents per square foot")
    return value


def _metric_value(metrics: Mapping[str, Any], metric: str) -> float | int | None:
    raw: Any | None = None
    found_key: str | None = None
    for key in _METRIC_ALIASES[metric]:
        if key in metrics and metrics[key] is not None:
            raw = metrics[key]
            found_key = key
            break
    if found_key is None:
        return None
    if metric in _RATE_METRICS:
        return _rate(raw, name=found_key)
    return _money_psf(raw, name=found_key)


def _unknown_keys(
    value: Mapping[str, Any],
    allowed: set[str] | frozenset[str],
    *,
    path: str,
) -> list[str]:
    return [
        f"{path}.{key}"
        for key in value
        if not isinstance(key, str) or key not in allowed
    ]


def _audit_benchmarks(supplied: Mapping[str, Any] | None) -> list[str]:
    """Report benchmark fields normalization does not consume."""

    if supplied is None or not isinstance(supplied, Mapping):
        return []
    unknown: list[str] = []
    metric_keys = set(_METRICS)
    if any(metric in supplied for metric in _METRICS):
        unknown.extend(_unknown_keys(supplied, metric_keys, path="benchmarks"))
        metric_rules = supplied
        prefix = "benchmarks"
    else:
        metric_rules = None
        prefix = ""
        for raw_asset_type, raw_rules in supplied.items():
            if not isinstance(raw_rules, Mapping):
                continue
            asset_path = f"benchmarks.{raw_asset_type}"
            unknown.extend(_unknown_keys(raw_rules, metric_keys, path=asset_path))
            for metric in _METRICS:
                raw_rule = raw_rules.get(metric)
                if isinstance(raw_rule, Mapping):
                    unknown.extend(
                        _unknown_keys(
                            raw_rule,
                            _BENCHMARK_RULE_KEYS,
                            path=f"{asset_path}.{metric}",
                        )
                    )
    if metric_rules is not None:
        for metric in _METRICS:
            raw_rule = metric_rules.get(metric)
            if isinstance(raw_rule, Mapping):
                unknown.extend(
                    _unknown_keys(
                        raw_rule,
                        _BENCHMARK_RULE_KEYS,
                        path=f"{prefix}.{metric}",
                    )
                )
    return sorted(set(unknown))


def _audit_portfolio_item(
    item: Mapping[str, Any], index: int, raw_metrics: Mapping[str, Any]
) -> list[str]:
    """Report asset and metric fields that the screen does not consume."""

    metric_aliases = {
        alias for aliases in _METRIC_ALIASES.values() for alias in aliases
    }
    if item.get("metrics") is None:
        allowed_asset_keys = set(_ASSET_META_KEYS) | metric_aliases
        return _unknown_keys(item, allowed_asset_keys, path=f"portfolio[{index}]")
    unknown = _unknown_keys(item, _ASSET_META_KEYS, path=f"portfolio[{index}]")
    unknown.extend(
        _unknown_keys(
            raw_metrics,
            metric_aliases,
            path=f"portfolio[{index}].metrics",
        )
    )
    return unknown


def _copy_defaults() -> dict[str, dict[str, dict[str, Any]]]:
    return {
        asset_type: {
            metric: dict(rule) for metric, rule in rules.items()
        }
        for asset_type, rules in DEFAULT_BENCHMARK_CONVENTIONS.items()
    }


def _normalize_rule(metric: str, value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        direction = str(value.get("direction") or _DIRECTIONS[metric]).casefold()
        raw_threshold = value.get("threshold")
        if raw_threshold is None:
            raw_threshold = value.get("minimum")
            direction = "minimum" if raw_threshold is not None else direction
        if raw_threshold is None:
            raw_threshold = value.get("maximum")
            direction = "maximum" if raw_threshold is not None else direction
        if raw_threshold is None:
            raise ValueError(f"benchmark {metric} needs threshold, minimum, or maximum")
    else:
        direction = _DIRECTIONS[metric]
        raw_threshold = value
    if direction not in {"minimum", "maximum"}:
        raise ValueError(f"benchmark {metric}.direction must be minimum or maximum")
    threshold: float | int
    if metric in _RATE_METRICS:
        threshold = _rate(raw_threshold, name=f"benchmark {metric}")
    else:
        threshold = _money_psf(raw_threshold, name=f"benchmark {metric}")
    return {"direction": direction, "threshold": threshold}


def _conventions(
    supplied: Mapping[str, Any] | None,
) -> tuple[dict[str, dict[str, dict[str, Any]]], str]:
    conventions = _copy_defaults()
    if supplied is None:
        return conventions, "default exposed screening conventions"
    if not isinstance(supplied, Mapping):
        raise ValueError("benchmarks must be a mapping or null")

    # A flat metric mapping applies to every asset type through ``default``.
    if any(metric in supplied for metric in _METRICS):
        asset_rules: Mapping[str, Any] = supplied
        normalized: dict[str, dict[str, dict[str, Any]]] = {"default": {}}
        for metric in _METRICS:
            if metric in asset_rules:
                normalized["default"][metric] = _normalize_rule(
                    metric, asset_rules[metric]
                )
        return normalized, "caller-supplied screening conventions"

    normalized = {}
    for raw_asset_type, raw_rules in supplied.items():
        if not isinstance(raw_rules, Mapping):
            raise ValueError(f"benchmarks[{raw_asset_type}] must be a mapping")
        asset_type = str(raw_asset_type).strip().casefold() or "default"
        normalized[asset_type] = {}
        for metric in _METRICS:
            if metric in raw_rules:
                normalized[asset_type][metric] = _normalize_rule(
                    metric, raw_rules[metric]
                )
    if "default" not in normalized:
        normalized["default"] = conventions["default"]
    return normalized, "caller-supplied screening conventions"


def _adverse(direction: str, value: float, threshold: float) -> bool:
    return value < threshold if direction == "minimum" else value > threshold


def _threshold_deviation(
    direction: str, value: float, threshold: float
) -> tuple[float, float | None]:
    # Positive adverse deviation makes flag severity sortable in one direction.
    adverse_amount = threshold - value if direction == "minimum" else value - threshold
    denominator = abs(threshold)
    percent = adverse_amount / denominator if denominator else None
    return adverse_amount, percent


def _peer_stats(values: Sequence[float]) -> dict[str, float] | None:
    if len(values) < 5:
        return None
    mean = fmean(values)
    standard_deviation = pstdev(values)
    return {"mean": mean, "standard_deviation": standard_deviation}


def flag_underperformance(
    portfolio: Sequence[Mapping[str, Any]],
    benchmarks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return numbers-backed threshold and peer-deviation exceptions.

    ``opex_psf`` and ``noi_psf`` are integer cents per square foot.  Absolute
    thresholds always apply.  A same-asset-type peer z-score is an additional
    screening convention only when that cohort has at least five observations;
    an adverse z score of at least 1.5 in magnitude is flagged.
    """

    if isinstance(portfolio, (str, bytes)) or not isinstance(portfolio, Sequence):
        raise ValueError("portfolio must be a sequence of asset mappings")
    rules, benchmark_source = _conventions(benchmarks)
    unrecognized_inputs = _audit_benchmarks(benchmarks)
    assets: list[dict[str, Any]] = []
    for index, item in enumerate(portfolio):
        if not isinstance(item, Mapping):
            raise ValueError(f"portfolio[{index}] must be a mapping")
        deal_id = str(item.get("deal_id") or item.get("asset") or "").strip()
        if not deal_id:
            raise ValueError(f"portfolio[{index}] needs deal_id or asset")
        asset_type = str(item.get("asset_type") or "default").strip().casefold()
        raw_metrics = item.get("metrics")
        if raw_metrics is None:
            raw_metrics = item
        if not isinstance(raw_metrics, Mapping):
            raise ValueError(f"portfolio[{index}].metrics must be a mapping")
        unrecognized_inputs.extend(_audit_portfolio_item(item, index, raw_metrics))
        normalized_metrics = {
            metric: _metric_value(raw_metrics, metric) for metric in _METRICS
        }
        assets.append(
            {
                "deal_id": deal_id,
                "asset_type": asset_type,
                "metrics": normalized_metrics,
            }
        )

    cohorts: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        cohorts.setdefault(asset["asset_type"], []).append(asset)

    cohort_statistics: dict[str, dict[str, Any]] = {}
    for asset_type, cohort in sorted(cohorts.items()):
        metrics: dict[str, Any] = {}
        for metric in _METRICS:
            values = [
                float(asset["metrics"][metric])
                for asset in cohort
                if asset["metrics"][metric] is not None
            ]
            stats = _peer_stats(values)
            metrics[metric] = {
                "n": len(values),
                "mean": stats["mean"] if stats is not None else None,
                "standard_deviation": (
                    stats["standard_deviation"] if stats is not None else None
                ),
                "statistics_used": stats is not None,
                "honesty": (
                    "Peer population z-score convention enabled; n >= 5."
                    if stats is not None
                    else f"n={len(values)} < 5; no peer statistic is calculated."
                ),
            }
        cohort_statistics[asset_type] = {
            "asset_count": len(cohort),
            "metrics": metrics,
            "small_sample": len(cohort) < 5,
            "honesty": (
                "Cohort has at least five assets; peer screens remain conventions, "
                "not inferential claims."
                if len(cohort) >= 5
                else f"n={len(cohort)} < 5; threshold screens only, with no fake "
                "peer statistics."
            ),
        }

    flags: list[dict[str, Any]] = []
    missing_metrics: list[dict[str, Any]] = []
    for asset in assets:
        asset_type = asset["asset_type"]
        asset_rules = rules.get(asset_type, rules.get("default", {}))
        for metric in _METRICS:
            value = asset["metrics"][metric]
            if value is None:
                missing_metrics.append(
                    {"deal_id": asset["deal_id"], "metric": metric}
                )
                continue
            raw_rule = asset_rules.get(metric)
            if raw_rule is None:
                continue
            direction = str(raw_rule["direction"])
            threshold = float(raw_rule["threshold"])
            numeric_value = float(value)
            threshold_breach = _adverse(direction, numeric_value, threshold)
            deviation, deviation_pct = _threshold_deviation(
                direction, numeric_value, threshold
            )

            metric_stats = cohort_statistics[asset_type]["metrics"][metric]
            mean = metric_stats["mean"]
            standard_deviation = metric_stats["standard_deviation"]
            z_score: float | None = None
            adverse_z = False
            if (
                metric_stats["statistics_used"]
                and mean is not None
                and standard_deviation is not None
                and standard_deviation > 0
            ):
                raw_z = (numeric_value - float(mean)) / float(standard_deviation)
                z_score = raw_z
                adverse_z = raw_z <= -1.5 if direction == "minimum" else raw_z >= 1.5

            if not threshold_breach and not adverse_z:
                continue
            reasons: list[str] = []
            if threshold_breach:
                relation = "below" if direction == "minimum" else "above"
                reasons.append(
                    f"{metric} {value} is {relation} the exposed {direction} "
                    f"threshold {raw_rule['threshold']}"
                )
            if adverse_z:
                reasons.append(
                    f"adverse peer z-score {z_score:.3f} crosses the 1.5 convention"
                )
            flags.append(
                {
                    "deal_id": asset["deal_id"],
                    "asset_type": asset_type,
                    "metric": metric,
                    "value": value,
                    "unit": (
                        "rate" if metric in _RATE_METRICS else "cents_per_sf"
                    ),
                    "direction": direction,
                    "threshold": raw_rule["threshold"],
                    "threshold_breach": threshold_breach,
                    "adverse_deviation": deviation if threshold_breach else 0,
                    "adverse_deviation_pct": deviation_pct if threshold_breach else 0,
                    "peer_n": metric_stats["n"],
                    "peer_mean": mean,
                    "peer_standard_deviation": standard_deviation,
                    "peer_z_score": z_score,
                    "peer_z_breach": adverse_z,
                    "why_flagged": "; ".join(reasons),
                }
            )

    flags.sort(
        key=lambda item: (
            not item["threshold_breach"],
            -(item["adverse_deviation_pct"] or 0),
            item["deal_id"],
            item["metric"],
        )
    )
    small_metric_cohorts = [
        {
            "asset_type": asset_type,
            "metric": metric,
            "n": metric_detail["n"],
        }
        for asset_type, detail in cohort_statistics.items()
        for metric, metric_detail in detail["metrics"].items()
        if metric_detail["n"] < 5
    ]
    small_cohorts = sorted(
        {item["asset_type"] for item in small_metric_cohorts}
    )
    any_small_sample = not assets or bool(small_metric_cohorts)
    result = {
        "sample_size": len(assets),
        "flags": flags,
        "flag_count": len(flags),
        "benchmark_source": benchmark_source,
        "benchmark_conventions": rules,
        "conventions": {
            "labels": [
                "Screening thresholds are conventions, not market benchmarks or facts.",
                "Rates over 1 through 100 are interpreted as percentages.",
                "opex_psf and noi_psf are integer cents per square foot.",
                "Peer z-score convention: same asset type, population standard "
                "deviation, adverse magnitude >= 1.5, and metric n >= 5.",
            ],
            "metric_directions": dict(_DIRECTIONS),
            "peer_minimum_n": 5,
            "peer_z_threshold": 1.5,
        },
        "cohort_statistics": cohort_statistics,
        "statistical_method": (
            "peer population z-score convention where each metric n >= 5; "
            "otherwise threshold-only"
        ),
        "small_sample": any_small_sample,
        "small_sample_asset_types": small_cohorts,
        "small_sample_metric_cohorts": small_metric_cohorts,
        "small_sample_honesty": (
            "No assets were supplied; no performance or statistical conclusion is available."
            if not assets
            else (
                "At least one asset-type/metric cohort has n < 5; no peer mean, "
                "standard deviation, percentile, or z-score is calculated for "
                "those metrics."
                if small_metric_cohorts
                else "Every asset-type/metric cohort has n >= 5; peer statistics "
                "are labeled conventions."
            )
        ),
        "no_fake_statistics": any_small_sample,
        "fake_statistics_used": False,
        "missing_metrics": missing_metrics,
    }
    if unrecognized_inputs:
        result["unrecognized_inputs"] = sorted(set(unrecognized_inputs))
    return result


__all__ = ["DEFAULT_BENCHMARK_CONVENTIONS", "flag_underperformance"]
