"""Conservative cross-source listing identity checks.

Only listings with the same fully normalized address and locality are grouped as
duplicates.  Suite and fuzzy similarities are emitted as candidate matches for
human review; they are never added to one another's duplicate groups.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
import re
from typing import Any


ADDRESS_ABBREVIATIONS = {
    "north": "n",
    "n": "n",
    "south": "s",
    "s": "s",
    "east": "e",
    "e": "e",
    "west": "w",
    "w": "w",
    "northeast": "ne",
    "ne": "ne",
    "northwest": "nw",
    "nw": "nw",
    "southeast": "se",
    "se": "se",
    "southwest": "sw",
    "sw": "sw",
    "avenue": "ave",
    "ave": "ave",
    "boulevard": "blvd",
    "blvd": "blvd",
    "drive": "dr",
    "dr": "dr",
    "road": "rd",
    "rd": "rd",
    "lane": "ln",
    "ln": "ln",
    "highway": "hwy",
    "hwy": "hwy",
    "parkway": "pkwy",
    "pkwy": "pkwy",
    "court": "ct",
    "ct": "ct",
    "place": "pl",
    "pl": "pl",
    "circle": "cir",
    "cir": "cir",
    "trail": "trl",
    "trl": "trl",
    "street": "st",
    "st": "st",
    "suite": "ste",
    "ste": "ste",
}
"""Small, explicit address abbreviation table used by this module."""

_ORDINAL_WORDS = {
    "first": "1st",
    "second": "2nd",
    "third": "3rd",
    "fourth": "4th",
    "fifth": "5th",
    "sixth": "6th",
    "seventh": "7th",
    "eighth": "8th",
    "ninth": "9th",
    "tenth": "10th",
    "eleventh": "11th",
    "twelfth": "12th",
    "thirteenth": "13th",
    "fourteenth": "14th",
    "fifteenth": "15th",
    "sixteenth": "16th",
    "seventeenth": "17th",
    "eighteenth": "18th",
    "nineteenth": "19th",
    "twentieth": "20th",
}

FUZZY_TOKEN_OVERLAP_THRESHOLD = 0.75
"""Minimum Jaccard token overlap for a fuzzy candidate match."""

_REQUIRED_TEXT_FIELDS = ("source", "source_id", "address", "city", "state")
_SEEN_DATE_FIELDS = (
    "seen_date",
    "seen_at",
    "date_seen",
    "observed_at",
    "observed_date",
    "seen",
)


def _normalize_text(value: str) -> str:
    normalized = re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_address(address: str) -> str:
    """Normalize address spelling while retaining suite identity."""

    if not isinstance(address, str):
        raise TypeError("address must be a string")

    # Treat ``# 200`` as a suite marker.  If an explicit Suite/Ste precedes the
    # hash, the duplicate marker is collapsed after token normalization.
    value = re.sub(
        r"#\s*([\w-]+)",
        r" suite \1",
        address.casefold(),
        flags=re.UNICODE,
    )
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    tokens = [
        ADDRESS_ABBREVIATIONS.get(token, _ORDINAL_WORDS.get(token, token))
        for token in value.split()
    ]

    collapsed: list[str] = []
    for token in tokens:
        if token == "ste" and collapsed and collapsed[-1] == "ste":
            continue
        collapsed.append(token)
    return " ".join(collapsed)


def normalize_zip5(value: object) -> str:
    """Return the first five ZIP digits, or an empty string when unavailable."""

    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return f"{value:05d}" if 0 <= value <= 99_999 else ""
    match = re.search(r"(?<!\d)(\d{5})(?:-\d{4})?(?!\d)", str(value))
    return match.group(1) if match else ""


def token_overlap_score(left: str, right: str) -> float:
    """Calculate Jaccard overlap across normalized address tokens."""

    left_tokens = set(normalize_address(left).split())
    right_tokens = set(normalize_address(right).split())
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def _address_locality_key(listing: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        normalize_address(listing["address"]),
        _normalize_text(listing["city"]),
        _normalize_text(listing["state"]),
    )


def _split_suite(address: str) -> tuple[str, str]:
    tokens = normalize_address(address).split()
    if "ste" not in tokens:
        return " ".join(tokens), ""
    index = tokens.index("ste")
    return " ".join(tokens[:index]), " ".join(tokens[index + 1 :])


def _has_street_number(address: str) -> bool:
    first_token = address.split(" ", 1)[0]
    return bool(re.search(r"\d", first_token))


def _same_locality(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return (
        _normalize_text(left["city"]) == _normalize_text(right["city"])
        and _normalize_text(left["state"]) == _normalize_text(right["state"])
    )


def _candidate_relation(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> tuple[str, float] | None:
    if not _same_locality(left, right):
        return None

    left_base, left_suite = _split_suite(left["address"])
    right_base, right_suite = _split_suite(right["address"])
    if (
        left_base
        and left_base == right_base
        and _has_street_number(left_base)
        and left_suite != right_suite
    ):
        return "same_street_different_suite", 1.0

    score = token_overlap_score(left["address"], right["address"])
    if score >= FUZZY_TOKEN_OVERLAP_THRESHOLD:
        return "fuzzy_token_overlap", score
    return None


def _seen_date(listing: Mapping[str, Any]) -> str | None:
    for field in _SEEN_DATE_FIELDS:
        value = listing.get(field)
        if value is None or value == "":
            continue
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return str(value).strip()
    return None


def _seen_sort_key(value: str | None) -> tuple[int, float | str]:
    if value is None:
        return (2, "")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (0, parsed.timestamp())
    except ValueError:
        try:
            parsed_date = date.fromisoformat(value)
            parsed = datetime.combine(parsed_date, datetime.min.time(), timezone.utc)
            return (0, parsed.timestamp())
        except ValueError:
            return (1, value.casefold())


def _price_history(members: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for member in members:
        if member.get("price") is None:
            continue
        history.append(
            {
                "source": member["source"],
                "source_id": member["source_id"],
                "price": member["price"],
                "seen_date": _seen_date(member),
            }
        )
    history.sort(
        key=lambda item: (
            _seen_sort_key(item["seen_date"]),
            str(item["source"]).casefold(),
            str(item["source_id"]),
        )
    )
    return history


def _validate_listings(
    listings: object,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if isinstance(listings, (str, bytes)) or not isinstance(listings, Sequence):
        return None, "listings must be a sequence of listing objects"

    validated: list[dict[str, Any]] = []
    for index, listing in enumerate(listings):
        if not isinstance(listing, Mapping):
            return None, f"listing at index {index} must be an object"
        for field in _REQUIRED_TEXT_FIELDS:
            value = listing.get(field)
            if not isinstance(value, str) or not value.strip():
                return None, (
                    f"listing at index {index} requires non-empty string field "
                    f"'{field}'"
                )
        if not normalize_address(listing["address"]):
            return None, f"listing at index {index} has no normalizable address"
        validated.append(dict(listing))
    return validated, None


def _candidate_reference(group: Mapping[str, Any]) -> dict[str, Any]:
    canonical = group["canonical"]
    return {
        "source": canonical["source"],
        "source_id": canonical["source_id"],
        "address": canonical["address"],
        "city": canonical["city"],
        "state": canonical["state"],
        "zip": canonical.get("zip"),
    }


def dedupe_listings(
    listings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Group exact duplicates and separately report uncertain candidates.

    Candidate matches include a score and require human confirmation.  Their
    records remain in separate groups, even when the fuzzy score is 1.0.
    """

    records, error = _validate_listings(listings)
    if error is not None:
        return {"error": error}
    assert records is not None

    # First bucket by normalized address/locality, then handle optional ZIPs.
    # A missing ZIP is compatible with one known ZIP, but it must not bridge two
    # conflicting known ZIPs into a false duplicate cluster.
    address_buckets: dict[
        tuple[str, str, str], list[tuple[int, dict[str, Any]]]
    ] = {}
    for input_index, record in enumerate(records):
        address_buckets.setdefault(_address_locality_key(record), []).append(
            (input_index, record)
        )

    indexed_groups: list[list[tuple[int, dict[str, Any]]]] = []
    for bucket in address_buckets.values():
        provided_zips = {
            zip5
            for _, record in bucket
            if (zip5 := normalize_zip5(record.get("zip")))
        }
        if len(provided_zips) <= 1:
            indexed_groups.append(bucket)
            continue

        groups_by_zip: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for input_index, record in bucket:
            zip5 = normalize_zip5(record.get("zip"))
            groups_by_zip.setdefault(zip5, []).append((input_index, record))
        indexed_groups.extend(groups_by_zip.values())

    indexed_groups.sort(key=lambda group: group[0][0])
    grouped_records = [
        [record for _, record in indexed_group]
        for indexed_group in indexed_groups
    ]

    groups: list[dict[str, Any]] = []
    for members in grouped_records:
        groups.append(
            {
                "canonical": members[0],
                "members": members,
                "tier": "duplicate" if len(members) > 1 else "unique",
                "match_basis": (
                    "exact_normalized_address" if len(members) > 1 else None
                ),
                "price_history": _price_history(members),
            }
        )

    candidate_group_indexes: set[int] = set()
    candidate_matches: list[dict[str, Any]] = []
    for left_index, left_group in enumerate(groups):
        for right_index in range(left_index + 1, len(groups)):
            right_group = groups[right_index]
            relation = _candidate_relation(
                left_group["canonical"], right_group["canonical"]
            )
            if relation is None:
                continue
            reason, score = relation
            candidate_group_indexes.update((left_index, right_index))
            candidate_matches.append(
                {
                    "left": _candidate_reference(left_group),
                    "right": _candidate_reference(right_group),
                    "tier": "candidate",
                    "match_basis": reason,
                    "score": round(score, 4),
                    "requires_human_confirmation": True,
                }
            )

    for group_index in candidate_group_indexes:
        if groups[group_index]["tier"] == "unique":
            groups[group_index]["tier"] = "candidate"
            groups[group_index]["match_basis"] = "candidate_match_reported_separately"

    return {
        "groups": groups,
        "candidate_matches": candidate_matches,
        "fuzzy_threshold": FUZZY_TOKEN_OVERLAP_THRESHOLD,
        "honesty": (
            "Candidate matches are never merged; a human must confirm identity."
        ),
    }


__all__ = [
    "ADDRESS_ABBREVIATIONS",
    "FUZZY_TOKEN_OVERLAP_THRESHOLD",
    "dedupe_listings",
    "normalize_address",
    "normalize_zip5",
    "token_overlap_score",
]
