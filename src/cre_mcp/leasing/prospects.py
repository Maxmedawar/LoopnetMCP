"""Tenant prospect ranking over the committed Control Engine catalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.control import TENANTS
from cre_mcp.control.site_fit import match_tenants_to_site
from cre_mcp.enrichment.nearby import nearby_brands

from .watch import tenant_watch_report


_SEVERITY_WEIGHT = {
    "info": 0.0,
    "low": 0.01,
    "medium": 0.025,
    "moderate": 0.025,
    "high": 0.05,
    "critical": 0.08,
}
_POSITIVE_CHANGE_WORDS = frozenset(
    {"increase", "increased", "growth", "grew", "expansion", "expanding", "opening"}
)
_NEGATIVE_CHANGE_WORDS = frozenset(
    {"decrease", "decreased", "decline", "declined", "contraction", "closing", "closures"}
)


def _number(value: Any, label: str, *, positive: bool = False) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if positive and number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def _demographic(demographics: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in demographics:
            return demographics[key]
    return None


def _normalize_cotenancy(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("existing_cotenancy must be a list of brand names or mappings")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            brand = item.strip()
            if not brand:
                continue
            normalized.append({"brand": brand, "category": None, "distance_m": None})
            continue
        if not isinstance(item, Mapping):
            raise ValueError(f"existing_cotenancy[{index}] must be text or a mapping")
        brand = str(item.get("brand") or item.get("name") or "").strip()
        if not brand:
            raise ValueError(f"existing_cotenancy[{index}] requires brand or name")
        normalized.append(
            {
                **dict(item),
                "brand": brand,
                "category": item.get("category"),
                "distance_m": _number(
                    item.get("distance_m"),
                    f"existing_cotenancy[{index}].distance_m",
                ),
            }
        )
    return normalized


def _watch_adjustment(report: Mapping[str, Any]) -> tuple[float, list[str]]:
    """Translate accumulated signals into a small, fully exposed screen adjustment."""

    adjustment = 0.0
    reasons: list[str] = []
    signals = report.get("signals") or report.get("history") or []
    if not isinstance(signals, Sequence) or isinstance(signals, (str, bytes)):
        return adjustment, reasons
    for raw in signals:
        if not isinstance(raw, Mapping):
            continue
        signal_type = str(raw.get("signal_type") or "").strip().casefold()
        severity = str(raw.get("severity") or "medium").strip().casefold()
        magnitude = _SEVERITY_WEIGHT.get(severity, _SEVERITY_WEIGHT["medium"])
        direction = 0
        if signal_type in {"closure_news", "credit_downgrade"}:
            direction = -1
        elif signal_type == "store_count_change":
            words = set(str(raw.get("note") or "").casefold().replace("-", " ").split())
            if words & _POSITIVE_CHANGE_WORDS:
                direction = 1
            elif words & _NEGATIVE_CHANGE_WORDS:
                direction = -1
        delta = direction * magnitude
        if delta:
            adjustment += delta
            reasons.append(
                f"{signal_type}/{severity}: {delta:+.3f} convention adjustment"
            )
    return max(-0.15, min(0.10, adjustment)), reasons


def tenant_prospect_list(
    site: Mapping[str, Any],
    existing_cotenancy: Sequence[str | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rank the 30 committed tenants as a screening list, not a universe or forecast.

    ``existing_cotenancy`` makes the function deterministic and is the preferred
    input for underwriting.  When it is omitted and coordinates are present, the
    existing OpenStreetMap enrichment is queried.  An empty enrichment result is
    treated as unavailable evidence, never as proof of whitespace.
    """

    if not isinstance(site, Mapping):
        raise ValueError("site must be a mapping")
    sf = _number(site.get("sf"), "site.sf", positive=True)
    if sf is None:
        raise ValueError("site.sf is required")
    demographics_raw = site.get("demographics") or {}
    if not isinstance(demographics_raw, Mapping):
        raise ValueError("site.demographics must be a mapping")
    demographics = dict(demographics_raw)

    lat = _number(site.get("lat"), "site.lat")
    lon = _number(site.get("lon"), "site.lon")
    if (lat is None) != (lon is None):
        raise ValueError("site.lat and site.lon must be supplied together")
    if lat is not None and not -90 <= lat <= 90:
        raise ValueError("site.lat must be between -90 and 90")
    if lon is not None and not -180 <= lon <= 180:
        raise ValueError("site.lon must be between -180 and 180")

    radius_m = int(_number(site.get("whitespace_radius_m", 1609), "site.whitespace_radius_m", positive=True) or 1609)
    cotenancy_source = "supplied existing_cotenancy"
    if existing_cotenancy is None:
        if lat is not None and lon is not None:
            cotenancy = _normalize_cotenancy(
                nearby_brands(lat, lon, radius_m=radius_m)
            )
            cotenancy_source = "cre_mcp.enrichment.nearby OpenStreetMap lookup"
        else:
            cotenancy = []
            cotenancy_source = "unavailable: no supplied cotenancy or coordinates"
    else:
        cotenancy = _normalize_cotenancy(existing_cotenancy)

    nearby_categories = sorted(
        {
            str(item["category"]).strip()
            for item in cotenancy
            if item.get("category") not in (None, "")
        }
    )
    aadt = _number(
        _demographic(demographics, "traffic_aadt", "aadt"),
        "site.demographics.traffic_aadt",
    )
    population = _number(
        _demographic(demographics, "population", "population_3mi"),
        "site.demographics.population",
    )
    income = _number(
        _demographic(demographics, "median_income", "median_household_income"),
        "site.demographics.median_income",
    )
    parcel_acres = _number(site.get("parcel_acres"), "site.parcel_acres")
    frontage = _number(site.get("frontage"), "site.frontage")
    if frontage is None:
        frontage = _number(site.get("frontage_ft"), "site.frontage_ft")
    has_drive_thru_raw = site.get("has_drive_thru")
    if has_drive_thru_raw is not None and not isinstance(has_drive_thru_raw, bool):
        raise ValueError("site.has_drive_thru must be boolean")

    fit_results = match_tenants_to_site(
        aadt=None if aadt is None else int(aadt),
        population_3mi=None if population is None else int(population),
        median_income=None if income is None else int(income),
        parcel_acres=parcel_acres,
        building_sqft=int(sf),
        has_drive_thru=has_drive_thru_raw,
        nearby_categories=nearby_categories,
    )
    tenants_by_brand = {tenant.brand: tenant for tenant in TENANTS}
    supplied_brands = {str(item["brand"]).strip().casefold(): item for item in cotenancy}
    watch_db_path = site.get("watch_db_path")

    prospects: list[dict[str, Any]] = []
    for fit in fit_results:
        brand = str(fit["brand"])
        tenant = tenants_by_brand[brand]
        watch_report = tenant_watch_report(brand, db_path=watch_db_path)
        watch_delta, watch_reasons = _watch_adjustment(watch_report)
        same_brand = supplied_brands.get(brand.casefold())
        if same_brand is not None:
            distance = same_brand.get("distance_m")
            distance_note = (
                f" at {distance:g}m" if isinstance(distance, (int, float)) else " in the supplied search area"
            )
            whitespace_note = (
                f"Same-brand location supplied{distance_note}; review cannibalization and territory rights."
            )
            whitespace_status = "same_brand_present"
        elif cotenancy:
            whitespace_note = (
                f"No same-brand location appears in supplied/enriched cotenancy within {radius_m}m; "
                "screen only, not proof of market whitespace."
            )
            whitespace_status = "not_observed_in_inputs"
        else:
            whitespace_note = "Whitespace unknown because no usable nearby-brand evidence was available."
            whitespace_status = "unknown"

        frontage_note = None
        if frontage is not None and tenant.min_frontage_ft is not None:
            frontage_note = (
                f"supplied frontage {frontage:g} ft vs catalog minimum "
                f"{tenant.min_frontage_ft:g} ft"
            )
        base_fit = float(fit["fit_score"])
        prospect_score = round(max(0.0, min(1.0, base_fit + watch_delta)), 4)
        prospects.append(
            {
                **dict(fit),
                "category": tenant.category,
                "catalog_expansion_mode": tenant.expansion_mode,
                "catalog_source": tenant.source,
                "catalog_confidence": tenant.confidence,
                "base_fit_score": base_fit,
                "watch_adjustment": round(watch_delta, 4),
                "watch_adjustment_reasons": watch_reasons,
                "prospect_score": prospect_score,
                "whitespace_status": whitespace_status,
                "whitespace_note": whitespace_note,
                "frontage_screen": frontage_note,
                "signal_count": len(watch_report.get("signals") or watch_report.get("history") or []),
                "pursuit_disclaimer": "Screening lead only; no assertion that the tenant will pursue or sign a lease.",
            }
        )
    prospects.sort(
        key=lambda row: (
            -float(row["prospect_score"]),
            -float(row["base_fit_score"]),
            str(row["brand"]).casefold(),
        )
    )
    for rank, prospect in enumerate(prospects, start=1):
        prospect["rank"] = rank

    return {
        "prospects": prospects,
        "catalog_count": len(TENANTS),
        "catalog_coverage_note": (
            f"Catalog coverage is {len(TENANTS)} committed tenants, not the universe of possible tenants."
        ),
        "cotenancy_source": cotenancy_source,
        "cotenancy_observation_count": len(cotenancy),
        "whitespace_radius_m": radius_m,
        "ranking_method": (
            "Control Engine fit_score plus a capped, exposed leasing_watch convention adjustment; "
            "whitespace is reported separately and does not imply availability or demand."
        ),
        "watch_hook_note": (
            "Manual and tool-fed leasing_watch signals are screening context; automated feeds are a later phase."
        ),
        "site_inputs": dict(site),
    }


__all__ = ["tenant_prospect_list"]
