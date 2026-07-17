"""Heuristic portfolio-owner grouping and noncore-outlier screening."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import math
import re
from statistics import median
import unicodedata
from typing import Any


SIZE_RATIO_OUTLIER_THRESHOLD = 3.0
_RECOGNIZED_FIELDS = frozenset(
    {
        "owner_name",
        "business_name",
        "use",
        "property_type",
        "sf",
        "assessed_value",
        "address",
        "parcel_id",
        "property_id",
        "lat",
        "lon",
        "latitude",
        "longitude",
    }
)
_ENTITY_SUFFIXES = frozenset(
    {
        "co",
        "company",
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "llc",
        "llp",
        "lp",
        "ltd",
        "limited",
        "plc",
    }
)


def normalize_owner_name(value: object) -> str:
    """Normalize punctuation, case, accents, and trailing legal-form tokens."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"\bl[\W_]*l[\W_]*c\b", " llc ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bl[\W_]*l[\W_]*p\b", " llp ", text, flags=re.IGNORECASE)
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    while tokens and tokens[-1] in _ENTITY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _records_or_empty(records: Sequence[Mapping[str, Any]] | None) -> Sequence[Mapping[str, Any]]:
    if records is None:
        return ()
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise ValueError("records must be a sequence of mappings or null")
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"records[{index}] must be a mapping")
    return records


def _positive_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _coordinate(record: Mapping[str, Any]) -> tuple[float, float] | None:
    lat = _positive_or_negative_float(record.get("lat", record.get("latitude")))
    lon = _positive_or_negative_float(record.get("lon", record.get("longitude")))
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None
    return lat, lon


def _positive_or_negative_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _haversine_miles(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * 3958.7613 * math.asin(min(1.0, math.sqrt(haversine)))


def _dispersion_note(records: list[tuple[int, Mapping[str, Any]]]) -> str:
    coordinates = [coordinate for _, record in records if (coordinate := _coordinate(record))]
    if len(coordinates) < 2:
        return "Geographic dispersion not evaluated: fewer than two usable coordinates."
    maximum = max(
        _haversine_miles(coordinates[first], coordinates[second])
        for first in range(len(coordinates))
        for second in range(first + 1, len(coordinates))
    )
    qualifier = "all" if len(coordinates) == len(records) else f"{len(coordinates)} of {len(records)}"
    return (
        f"Observed maximum pairwise separation is {maximum:.1f} miles using {qualifier} "
        "records with coordinates; this is descriptive, not a calibrated seller signal."
    )


def _canonical_use(record: Mapping[str, Any]) -> str | None:
    value = record.get("use")
    if value is None:
        value = record.get("property_type")
    if value is None or not str(value).strip():
        return None
    return " ".join(str(value).casefold().split())


def portfolio_owner_scan(
    records: Sequence[Mapping[str, Any]] | None,
    min_properties: int = 2,
) -> dict[str, Any]:
    """Group normalized owners and flag type/size profile outliers.

    An outlier is a diligence prompt, not evidence that an asset is noncore or
    that its owner intends to sell.  Type outliers differ from a unique modal
    use represented by at least two records.  Size outliers are at least 3x or
    at most 1/3 of the group's median positive square footage.
    """

    if isinstance(min_properties, bool) or not isinstance(min_properties, int) or min_properties < 1:
        raise ValueError("min_properties must be an integer of at least 1")
    source_records = _records_or_empty(records)
    grouped: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    skipped: list[dict[str, Any]] = []
    all_unrecognized: set[str] = set()

    for index, record in enumerate(source_records):
        unrecognized = sorted(set(record).difference(_RECOGNIZED_FIELDS))
        all_unrecognized.update(unrecognized)
        normalized = normalize_owner_name(record.get("owner_name"))
        if not normalized:
            skipped.append(
                {
                    "record_index": index,
                    "reason": "missing or unusable owner_name",
                    "unrecognized_fields": unrecognized,
                }
            )
            continue
        grouped.setdefault(normalized, []).append((index, record))

    owners: list[dict[str, Any]] = []
    for normalized_owner, owner_records in grouped.items():
        if len(owner_records) < min_properties:
            continue

        uses = [_canonical_use(record) for _, record in owner_records]
        use_counts = Counter(use for use in uses if use is not None)
        modal_use: str | None = None
        if use_counts:
            most_common_count = max(use_counts.values())
            winners = sorted(use for use, count in use_counts.items() if count == most_common_count)
            if len(winners) == 1 and most_common_count >= 2:
                modal_use = winners[0]

        sizes = [_positive_float(record.get("sf")) for _, record in owner_records]
        usable_sizes = [size for size in sizes if size is not None]
        median_sf = median(usable_sizes) if usable_sizes else None
        properties: list[dict[str, Any]] = []

        for position, (record_index, record) in enumerate(owner_records):
            use = uses[position]
            size = sizes[position]
            reasons: list[str] = []
            if modal_use is not None and use is not None and use != modal_use:
                reasons.append(f"use '{use}' differs from the modal use '{modal_use}'")
            size_ratio: float | None = None
            if median_sf is not None and size is not None and len(usable_sizes) >= 3:
                size_ratio = size / median_sf
                if (
                    size_ratio >= SIZE_RATIO_OUTLIER_THRESHOLD
                    or size_ratio <= 1 / SIZE_RATIO_OUTLIER_THRESHOLD
                ):
                    reasons.append(
                        f"size is {size_ratio:.2f}x the portfolio median, outside the "
                        f"1/{SIZE_RATIO_OUTLIER_THRESHOLD:.0f}x–{SIZE_RATIO_OUTLIER_THRESHOLD:.0f}x convention"
                    )
            properties.append(
                {
                    "record_index": record_index,
                    "address": record.get("address"),
                    "parcel_id": record.get("parcel_id"),
                    "property_id": record.get("property_id"),
                    "use": record.get("use", record.get("property_type")),
                    "sf": record.get("sf"),
                    "size_to_median_ratio": round(size_ratio, 4) if size_ratio is not None else None,
                    "noncore_outlier_flag": bool(reasons),
                    "signal_label": "HEURISTIC INFERENCE" if reasons else "HEURISTIC SCREEN",
                    "basis": reasons or ["within the available type/size profile conventions"],
                    "inference_caution": (
                        "A profile outlier may warrant diligence; it does not establish noncore "
                        "status or intent to sell."
                    ),
                    "unrecognized_fields": sorted(set(record).difference(_RECOGNIZED_FIELDS)),
                }
            )

        owners.append(
            {
                "normalized_owner_name": normalized_owner,
                "owner_name_variants": sorted(
                    {
                        str(record.get("owner_name"))
                        for _, record in owner_records
                        if record.get("owner_name") is not None
                    }
                ),
                "property_count": len(owner_records),
                "signal_label": "HEURISTIC PORTFOLIO GROUP",
                "grouping_basis": "case/punctuation/accent normalized owner name without legal suffix",
                "profile": {
                    "use_counts": dict(sorted(use_counts.items())),
                    "modal_use_for_outlier_test": modal_use,
                    "median_sf": median_sf,
                    "usable_size_count": len(usable_sizes),
                    "size_ratio_outlier_threshold": SIZE_RATIO_OUTLIER_THRESHOLD,
                },
                "dispersion_note": _dispersion_note(owner_records),
                "noncore_outlier_count": sum(
                    property_record["noncore_outlier_flag"] for property_record in properties
                ),
                "properties": properties,
                "seller_intent_caution": (
                    "Portfolio grouping and outlier status are heuristic; neither establishes "
                    "owner intent to sell."
                ),
            }
        )

    owners.sort(key=lambda owner: (-owner["property_count"], owner["normalized_owner_name"]))
    return {
        "methodology": {
            "label": "HEURISTIC; noncore and seller-intent conclusions are inferences",
            "minimum_properties": min_properties,
            "type_outlier_convention": (
                "different from a unique modal use represented by at least two records"
            ),
            "size_outlier_convention": (
                f"at least {SIZE_RATIO_OUTLIER_THRESHOLD:.0f}x or at most "
                f"1/{SIZE_RATIO_OUTLIER_THRESHOLD:.0f}x median positive sf; requires 3 usable sizes"
            ),
        },
        "record_count": len(source_records),
        "owner_group_count": len(owners),
        "owners": owners,
        "skipped_records": skipped,
        "unrecognized_input_fields": sorted(all_unrecognized),
    }


__all__ = [
    "SIZE_RATIO_OUTLIER_THRESHOLD",
    "normalize_owner_name",
    "portfolio_owner_scan",
]
