"""Heuristics for finding permits that may represent stalled projects.

This module deliberately does not treat permit inactivity as evidence of owner
intent.  It reports an age/successor-activity heuristic that must be checked
with the issuing jurisdiction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
import re
from typing import Any


_COLLECTION_FIELDS = (
    "permits",
    "results",
    "records",
    "features",
    "items",
    "data",
)
_ADDRESS_FIELDS = (
    "address",
    "site_address",
    "project_address",
    "property_address",
    "location_address",
    "full_address",
    "street_address",
)
_DATE_FIELDS = (
    "issued_date",
    "issue_date",
    "issuance_date",
    "permit_date",
    "filing_date",
    "filed_date",
    "application_date",
    "applied_date",
    "created_date",
    "created_at",
    "date",
)
_PERMIT_ID_FIELDS = (
    "permit_number",
    "permit_no",
    "permit_id",
    "record_number",
    "record_id",
    "permit_",
    "id",
)
_STREET_NUMBER_FIELDS = ("street_number", "address_number", "house_number")
_STREET_DIRECTION_FIELDS = ("street_direction", "pre_direction", "direction")
_STREET_NAME_FIELDS = ("street_name", "street")
_STREET_SUFFIX_FIELDS = ("suffix", "street_suffix", "street_type")


def _as_date(value: Any) -> date | None:
    """Parse common assessor/ArcGIS date representations."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            seconds = float(value) / 1000.0 if abs(float(value)) >= 100_000_000_000 else float(value)
            return datetime.fromtimestamp(seconds, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _as_date(int(text))

    iso_text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_text).date()
    except ValueError:
        pass

    for pattern in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%Y/%m/%d",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _normalize_address(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    replacements = {
        "STREET": "ST",
        "ROAD": "RD",
        "AVENUE": "AVE",
        "BOULEVARD": "BLVD",
        "DRIVE": "DR",
        "LANE": "LN",
        "COURT": "CT",
        "HIGHWAY": "HWY",
    }
    tokens = [replacements.get(token, token) for token in text.split()]
    return " ".join(tokens) or None


def _mapping_with_attributes(row: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten an ArcGIS feature's attributes without discarding top-level data."""

    flattened = dict(row)
    attributes = row.get("attributes")
    if isinstance(attributes, Mapping):
        flattened.update(attributes)
    return flattened


def _first_present(row: Mapping[str, Any], names: Sequence[str]) -> tuple[str | None, Any]:
    lower_to_key = {re.sub(r"[^a-z0-9]", "", str(key).lower()): key for key in row}
    for name in names:
        actual = lower_to_key.get(re.sub(r"[^a-z0-9]", "", name.lower()))
        if actual is not None:
            value = row[actual]
            if value is not None and str(value).strip():
                return str(actual), value
    return None, None


def _address_parts(row: Mapping[str, Any]) -> tuple[str | None, str | None]:
    number_field, number = _first_present(row, _STREET_NUMBER_FIELDS)
    direction_field, direction = _first_present(row, _STREET_DIRECTION_FIELDS)
    name_field, name = _first_present(row, _STREET_NAME_FIELDS)
    suffix_field, suffix = _first_present(row, _STREET_SUFFIX_FIELDS)
    if number is None or name is None:
        return None, None
    parts = [number, direction, name, suffix]
    address = " ".join(str(part).strip() for part in parts if part is not None and str(part).strip())
    fields = [number_field, direction_field, name_field, suffix_field]
    provenance = "composed:" + ",".join(field for field in fields if field is not None)
    return provenance, address


def _permit_rows(value: Any) -> tuple[list[Any], list[str]]:
    if value is None:
        return [], ["permit input was null; no rows were evaluated"]
    if isinstance(value, Mapping):
        token_to_key = {
            re.sub(r"[^a-z0-9]", "", str(key).lower()): key for key in value
        }
        for field in _COLLECTION_FIELDS:
            actual = token_to_key.get(re.sub(r"[^a-z0-9]", "", field.lower()))
            candidate = value.get(actual) if actual is not None else None
            if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
                return list(candidate), []
        # A single permit mapping is useful structured input, even without an envelope.
        recognized_tokens = {
            re.sub(r"[^a-z0-9]", "", field.lower())
            for field in _ADDRESS_FIELDS + _DATE_FIELDS + _STREET_NUMBER_FIELDS + _STREET_NAME_FIELDS
        }
        if any(re.sub(r"[^a-z0-9]", "", str(key).lower()) in recognized_tokens for key in value):
            return [value], ["input mapping was interpreted as one permit row"]
        return [], [
            "permit envelope had no recognized collection field; expected one of "
            + ", ".join(_COLLECTION_FIELDS)
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value), []
    raise TypeError("permits must be a permit sequence, a permits_near-style mapping, or null")


def stalled_projects(
    permits: Sequence[Mapping[str, Any] | None] | Mapping[str, Any] | None,
    min_age_days: int | None = 365,
    as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Return old permits having no strictly later permit at the same address.

    The result is a prospecting heuristic, not a finding that construction has
    actually stopped.  Missing addresses/dates are retained in
    ``unrecognized_records`` instead of being silently dropped.
    """

    threshold = 365 if min_age_days is None else min_age_days
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
        raise ValueError("min_age_days must be a non-negative integer or null")
    effective_as_of = date.today() if as_of is None else _as_date(as_of)
    if effective_as_of is None:
        raise ValueError("as_of must be a recognizable date or null")

    rows, input_notes = _permit_rows(permits)
    recognized: list[dict[str, Any]] = []
    unrecognized: list[dict[str, Any]] = []

    for index, raw_row in enumerate(rows):
        if not isinstance(raw_row, Mapping):
            unrecognized.append(
                {
                    "index": index,
                    "reason": "permit row was not an object",
                    "value_type": type(raw_row).__name__,
                }
            )
            continue

        row = _mapping_with_attributes(raw_row)
        address_field, raw_address = _first_present(row, _ADDRESS_FIELDS)
        if raw_address is None:
            address_field, raw_address = _address_parts(row)
        date_field, raw_date = _first_present(row, _DATE_FIELDS)
        permit_id_field, permit_id = _first_present(row, _PERMIT_ID_FIELDS)
        normalized_address = _normalize_address(raw_address)
        permit_date = _as_date(raw_date)
        missing: list[str] = []
        if normalized_address is None:
            missing.append("recognized address")
        if permit_date is None:
            missing.append("recognized permit date")
        if missing:
            unrecognized.append(
                {
                    "index": index,
                    "reason": "missing or unrecognized " + " and ".join(missing),
                    "available_fields": sorted(str(key) for key in row),
                    "raw_address": raw_address,
                    "raw_date": raw_date,
                }
            )
            continue

        recognized.append(
            {
                "index": index,
                "record": dict(raw_row),
                "address": str(raw_address).strip(),
                "normalized_address": normalized_address,
                "address_field": address_field,
                "permit_date": permit_date,
                "date_field": date_field,
                "permit_id": permit_id,
                "permit_id_field": permit_id_field,
            }
        )

    future_record_count = sum(1 for row in recognized if row["permit_date"] > effective_as_of)
    if future_record_count:
        input_notes.append(
            f"{future_record_count} future-dated recognized permit record(s) were ignored for "
            "successor activity as of the effective date"
        )

    dates_by_address: dict[str, list[date]] = {}
    for row in recognized:
        if row["permit_date"] <= effective_as_of:
            dates_by_address.setdefault(row["normalized_address"], []).append(row["permit_date"])

    signals: list[dict[str, Any]] = []
    for row in recognized:
        permit_date = row["permit_date"]
        age_days = (effective_as_of - permit_date).days
        if age_days < threshold:
            continue
        later_dates = [
            candidate
            for candidate in dates_by_address.get(row["normalized_address"], [])
            if candidate > permit_date
        ]
        if later_dates:
            continue
        signals.append(
            {
                "permit_id": row["permit_id"],
                "permit_id_field": row["permit_id_field"],
                "address": row["address"],
                "normalized_address": row["normalized_address"],
                "address_field": row["address_field"],
                "permit_date": permit_date.isoformat(),
                "date_field": row["date_field"],
                "age_days": age_days,
                "threshold_days": threshold,
                "successor_activity_found": False,
                "heuristic_basis": (
                    f"permit is at least {threshold} days old and no strictly later permit "
                    "was present at the same normalized address in the supplied records through "
                    "the effective date"
                ),
                "inference_label": "HEURISTIC; inactivity does not establish owner intent or project status",
                "source_record_index": row["index"],
                "record": row["record"],
            }
        )

    signals.sort(key=lambda item: (-item["age_days"], item["normalized_address"], item["source_record_index"]))
    return {
        "signals": signals,
        "signal_count": len(signals),
        "records_evaluated": len(recognized),
        "min_age_days": threshold,
        "as_of": effective_as_of.isoformat(),
        "heuristic_basis": (
            "A supplied permit is flagged when its age meets the threshold and the supplied "
            "dataset contains no permit with a later date at the same normalized address through "
            "the effective date. Address normalization is text-based and may not reconcile units, "
            "aliases, or jurisdiction-specific address identifiers."
        ),
        "inference_label": "HEURISTIC; no owner-intent inference is made",
        "verification_notice": "verify with the jurisdiction",
        "unrecognized_records": unrecognized,
        "input_notes": input_notes,
    }


__all__ = ["stalled_projects"]
