"""The authorization engine.

Decision order (spec): active -> matrix (default-deny in cloud) -> profile ->
territory -> ownership -> quota -> approval. The engine never derives
identity from arguments; it strips identity-shaped and storage-path arguments
in cloud mode before the tool ever sees them.
"""

import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ValidationError

from cre_mcp.access.capabilities import (
    CAPABILITIES,
    RequestTerritoryContract,
    ResultLocationBinding,
    ResultTerritoryContract,
    ResultTerritoryRecord,
    ToolCapability,
)
from cre_mcp.access.context import TenantContext
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.access.result_models import RESULT_MODEL_EXPORTS
from cre_mcp.access.territory import (
    STATE_ALIASES,
    canonical_permit_property,
    canonicalize_location_text,
    city_claim_is_unambiguous,
    city_county_fips,
    city_state_is_authoritative,
    city_zip_pair_is_authoritative,
    county_cbsa_codes,
    county_fips_for_name,
    county_identity_for_fips,
    location_parts,
    location_state,
    non_place_city_county_fips,
    normalize_city,
    normalize_state,
    normalize_zip,
    permit_full_address,
    strip_country_suffix,
    tract_identity_for_geoid,
    tract_zip_codes,
    zip_county_fips,
)
from cre_mcp.geo.constants import STATE_FIPS
from cre_mcp.models import (
    GeoRef,
    OwnerRecord,
    ParcelRecord,
    RentComparable,
    RentComps,
    SaleComp,
)
from cre_mcp.models.listings import (
    AggregatedSearchResult,
    Listing,
    MarketOverview,
    PropertyDetail,
    PropertySummary,
    SearchResult,
)

# Arguments a client might use to smuggle identity; server context always wins.
RESERVED_IDENTITY_ARGS = frozenset(
    {"workspace_id", "workspace", "role", "profile", "territory", "territories", "owner_workspace"}
)
# Arguments that would let a client choose storage locations.
STORAGE_ARGS = frozenset({"db_path", "watch_db_path"})
APPROVAL_ARG = "_approval_id"
RESULT_TERRITORY_DENIAL = (
    "access denied: tool result is outside or unresolvable for this "
    "workspace's territory"
)
_RESULT_ZIP_AT_END_RE = re.compile(r"\b([0-9]{5})(?:-[0-9]{4})?\s*$")
_RESULT_CITY_STATE_TAIL_RE = re.compile(
    r",\s*([A-Za-z]{2})(?:\s+[0-9]{5}(?:-[0-9]{4})?)?\s*$"
)
_RESULT_ADDRESS_STATE_RE = re.compile(
    r",\s*([A-Za-z]{2})\b(?:\s*,?\s+([0-9]{5})(?:-[0-9]{4})?)?",
    re.IGNORECASE,
)
_RESULT_ADDRESS_STANDALONE_ZIP_RE = re.compile(
    r"(?:^|[,;/|()\[\]:+\\]|\bAND\b|\s+-\s+)\s*"
    r"([0-9]{5})(?:-[0-9]{4})?"
    r"(?=\s*(?:$|[,;/|()\[\]:+\\]|\bAND\b|\s+-\s+))",
    re.IGNORECASE,
)
_RESULT_ANY_ASCII_ZIP_RE = re.compile(
    r"\b(?P<zip>[0-9]{5}(?:-[0-9]{4})?)\b"
)
_RESULT_UNPUNCTUATED_STATE_ZIP_RE = re.compile(
    r"\b([A-Za-z]{2})\s+([0-9]{5}(?:-[0-9]{4})?)\b",
    re.IGNORECASE,
)
_RESULT_UNPUNCTUATED_STATE_RE = re.compile(
    r"\b([A-Za-z]{2})\b",
    re.IGNORECASE,
)
_RESULT_ZIP_AFTER_STATE_RE = re.compile(
    r"^\s+[0-9]{5}(?:-[0-9]{4})?\b"
)
# Any punctuation can delimit adversarially concatenated address claims. Keep
# an unspaced hyphen out because it can be part of a legitimate place name.
_RESULT_ADDRESS_CLAIM_BOUNDARY_RE = re.compile(
    r"^(?:\bAND\b|[^\w\s-]|-(?=\s|$))",
    re.IGNORECASE,
)
_RESULT_ADDRESS_CLAIM_SEPARATOR_RE = re.compile(
    r"[,;/|()]|\+|\bAND\b|\s+-\s+",
    re.IGNORECASE,
)
_RESULT_AMBIGUOUS_STREET_TAIL_STATE_CODES = frozenset({"CT", "IN", "NE", "OR"})
_RESULT_COUNTRY_PATTERN = (
    r"(?:U\.?S\.?(?:A\.?)?|UNITED\s+STATES(?:\s+OF\s+AMERICA)?)\."
    r"?"
)
_RESULT_UNIT_LABEL_PATTERN = (
    r"(?:APT|APARTMENT|BLDG|BUILDING|FLOOR|LOT|STE|SUITE|UNIT)\.?"
)
_RESULT_UNIT_FRAGMENT_PATTERN = (
    rf"(?:{_RESULT_UNIT_LABEL_PATTERN}\s+#?\s*[A-Za-z0-9-]+"
    r"|#\s*[A-Za-z0-9-]+"
    r"|[0-9]+(?:ST|ND|RD|TH)\s+FLOOR\.?)"
)
_RESULT_UNIT_ONLY_RE = re.compile(
    rf"^{_RESULT_UNIT_FRAGMENT_PATTERN}$",
    re.IGNORECASE,
)
_RESULT_UNIT_ONLY_WITH_COUNTRY_RE = re.compile(
    rf"^{_RESULT_UNIT_FRAGMENT_PATTERN}"
    rf"(?:\s*,?\s+{_RESULT_COUNTRY_PATTERN})?$",
    re.IGNORECASE,
)
_RESULT_TRAILING_UNIT_RE = re.compile(
    rf"(?:^|[\s,]+)(?P<unit>{_RESULT_UNIT_FRAGMENT_PATTERN})"
    rf"(?:\s*,?\s+{_RESULT_COUNTRY_PATTERN})?\s*$",
    re.IGNORECASE,
)
_RESULT_LEADING_UNIT_LOCALITY_RE = re.compile(
    rf"^{_RESULT_UNIT_FRAGMENT_PATTERN}\s*,\s*(?P<locality>.+)$",
    re.IGNORECASE,
)
_RESULT_STREET_POSTFIX_RE = re.compile(
    rf"^(?:(?:N|S|E|W|NE|NW|SE|SW)\.?\s*)?"
    rf"(?:{_RESULT_UNIT_FRAGMENT_PATTERN})?$",
    re.IGNORECASE,
)
_RESULT_LABELED_UNIT_ZIP_RE = re.compile(
    rf"\b{_RESULT_UNIT_LABEL_PATTERN}\s+#?\s*"
    r"(?P<zip>[0-9]{5}(?:-[0-9]{4})?)\b",
    re.IGNORECASE,
)
_RESULT_LABELED_UNIT_ZIP_AT_END_RE = re.compile(
    rf"\b{_RESULT_UNIT_LABEL_PATTERN}"
    r"\s+#?\s*[0-9]{5}(?:-[0-9]{4})?"
    rf"(?:\s*,?\s+{_RESULT_COUNTRY_PATTERN})?\s*$",
    re.IGNORECASE,
)
_RESULT_STREET_RE = re.compile(
    r"\b(?:ALY|AVE|AVENUE|BLVD|BOULEVARD|CIR|COURT|CT|DR|DRIVE|HWY|"
    r"HIGHWAY|LANE|LN|PARKWAY|PKWY|PLACE|PL|PLAZA|PLZ|RD|ROAD|SQ|"
    r"SQUARE|ST|STREET|TER|TERRACE|TRL|WAY)\.?\b",
    re.IGNORECASE,
)
_RESULT_NUMBERED_STREET_START_RE = re.compile(
    r"^[0-9]+[A-Za-z]?(?:-[0-9]+)?\s+[A-Za-z]",
    re.IGNORECASE,
)
_RESULT_STATE_ALIAS_PATTERN = "|".join(
    re.escape(alias)
    for alias in sorted(STATE_ALIASES, key=len, reverse=True)
)
_RESULT_FULL_STATE_ALIAS_PATTERN = "|".join(
    re.escape(alias)
    for alias in sorted(STATE_ALIASES, key=len, reverse=True)
    if len(alias) > 2
)
_RESULT_FULL_STATE_TOKEN_RE = re.compile(
    rf"\b(?P<state>{_RESULT_FULL_STATE_ALIAS_PATTERN})\b",
    re.IGNORECASE,
)
_RESULT_COUNTY_NAME_RE = re.compile(
    rf"^(?P<entity>(?P<county>.+?)\s+(?:CITY\s+AND\s+BOROUGH|"
    rf"CENSUS\s+AREA|MUNICIPALITY|MUNICIPIO|BOROUGH|PARISH|COUNTY))"
    rf"(?:\s*,?\s+(?P<state>{_RESULT_STATE_ALIAS_PATTERN}))?$",
    re.IGNORECASE,
)
_RESULT_INDEPENDENT_CITY_NAME_RE = re.compile(
    rf"^(?P<entity>(?P<county>.+?)\s+CITY)"
    rf"(?:\s*,\s*(?P<state>{_RESULT_STATE_ALIAS_PATTERN}))?$",
    re.IGNORECASE,
)
_RESULT_CENSUS_PLACE_SUFFIX_RE = re.compile(
    r"\s+(?:CITY\s+AND\s+BOROUGH|CONSOLIDATED\s+GOVERNMENT|"
    r"METROPOLITAN\s+GOVERNMENT|UNIFIED\s+GOVERNMENT|METRO\s+GOVERNMENT|"
    r"METRO\s+TOWNSHIP|URBAN\s+COUNTY|CONSOLIDATED\s+MUNICIPALITY|"
    r"MUNICIPALITY|CORPORATION|ZONA\s+URBANA|COMUNIDAD|BOROUGH|VILLAGE|"
    r"TOWN|CITY|CDP)\s*$",
    re.IGNORECASE,
)
_RESULT_STREET_ZIP_TAIL_RE = re.compile(
    rf"^(?:(?:IN|NE|OR)\s+)?(?P<zip>[0-9]{{5}}(?:-[0-9]{{4}})?)"
    rf"(?:\s*,?\s+{_RESULT_COUNTRY_PATTERN})?$",
    re.IGNORECASE,
)
_RESULT_ADDRESS_EXACT_LOCATION_RE = re.compile(
    rf"\b(?P<state>{_RESULT_STATE_ALIAS_PATTERN})\b"
    r"(?:\s*,?\s+(?P<zip>[0-9]{5}(?:-[0-9]{4})?))?"
    rf"(?:\s*,?\s+{_RESULT_COUNTRY_PATTERN})?"
    r"(?=\s*(?:$|[,;/|()\[\]:+\\]|\bAND\b|\s+-\s+))",
    re.IGNORECASE,
)
_RESULT_LABELED_POSTAL_RE = re.compile(
    r"\b(?:ZIP(?:\s*CODE)?|ZIPCODE|POSTAL\s+CODE)\s*[:#]?\s*"
    r"(?P<zip>[0-9]{5}(?:-[0-9]{4})?)\b",
    re.IGNORECASE,
)
_RESULT_ZIP_COUNTRY_AT_END_RE = re.compile(
    rf"\b(?P<zip>[0-9]{{5}}(?:-[0-9]{{4}})?)\s*,?\s+"
    rf"{_RESULT_COUNTRY_PATTERN}\s*$",
    re.IGNORECASE,
)
_UNKNOWN_LOCATION_VALUES = frozenset(
    {
        "-",
        "--",
        "N/A",
        "NA",
        "NONE",
        "NOT AVAILABLE",
        "NULL",
        "TBD",
        "UNKNOWN",
        "UNAVAILABLE",
    }
)
_MULTI_LOCATION_CITY_SEPARATOR_RE = re.compile(
    r"[;/|+\\]|\bAND\b|\s+-\s+",
    re.IGNORECASE,
)


class Decision(BaseModel):
    outcome: Literal["allowed", "denied", "approval_required"]
    reason: str = ""
    approval_id: str | None = None


def _denied(reason: str) -> Decision:
    return Decision(outcome="denied", reason=reason)


def args_fingerprint(args: dict) -> str:
    canonical = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _has_value(value: object) -> bool:
    """Whether a supplied argument counts as present for the approval gate.

    ``None``, an empty string, and empty containers read as absent; every
    other value — crucially numeric ``0`` and ``False`` — reads as present.
    (A plain ``not in (None, False, "")`` test wrongly drops ``0`` because
    ``0 == False`` in Python.)
    """
    if value is None:
        return False
    if isinstance(value, (str, bytes, list, tuple, set, dict)):
        return len(value) > 0
    return True


def _territory_values(value: object) -> tuple[str, ...] | None:
    """Normalize one scalar or a strict JSON location array.

    ``None`` means the caller supplied a collection whose shape cannot be
    authorized.  Invalid members must not be filtered out because one valid
    sibling would then authorize a request containing unknown targets.
    """
    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()
    if isinstance(value, (list, tuple, set)):
        if type(value) is not list or any(
            type(item) is not str or not item.strip() for item in value
        ):
            return None
        return tuple(
            item.strip()
            for item in value
        )
    return ()


def _is_direct_property_address(value: str) -> bool:
    """Mirror tools whose reference argument also accepts a full address."""

    return (
        not value.startswith(("http://", "https://"))
        and re.search(r"[0-9]", value) is not None
        and re.search(r"\s", value) is not None
    )


def _normalized_city(value: str) -> str:
    """Normalize an exact city name without broadening its meaning."""
    return normalize_city(value) or ""


def _contains_non_ascii_decimal(value: str) -> bool:
    """Reject Unicode decimal lookalikes in US location fields.

    USPS ZIP syntax is ASCII-only.  Checking the whole declared location value
    prevents a non-ASCII ZIP from becoming invisible when the ASCII parsers
    correctly decline to recognize it.
    """
    return any(char.isdecimal() and char not in "0123456789" for char in value)


def _contains_unicode_format(value: str) -> bool:
    """Reject invisible Unicode format controls in a location string."""
    return any(unicodedata.category(char) == "Cf" for char in value)


def _is_unknown_location_value(value: str) -> bool:
    """Recognize common provider placeholders as missing, not literal places."""
    normalized = canonicalize_location_text(value).upper().strip(" ,.")
    return normalized in _UNKNOWN_LOCATION_VALUES


def _looks_like_street(value: str) -> bool:
    normalized = canonicalize_location_text(value)
    if (
        not normalized
        or re.search(r"[A-Za-z]", normalized) is None
        or re.match(rf"^\s*{_RESULT_UNIT_LABEL_PATTERN}\b", normalized, re.IGNORECASE)
    ):
        return False
    # A numbered address needs actual street text after the number. Bare
    # values such as "0", "90", and "123" are identifiers, not locations.
    if re.search(r"\b[0-9]+[A-Za-z]?(?:-[0-9]+)?\s+[A-Za-z]", normalized):
        return True
    # Preserve legitimate unnumbered street lines only when a suffix has a
    # substantive street name before it. A bare "Street" is incomplete.
    return any(
        re.search(r"[A-Za-z0-9]", normalized[: match.start()]) is not None
        for match in _RESULT_STREET_RE.finditer(normalized)
    )


def _structured_address_tail_matches(
    value: str,
    declared_city: str,
    declared_state: str,
    declared_zip: str | None,
) -> bool:
    """Require every visible locality tail to be complete and consistent.

    A structured record may carry a street-only address because its city and
    state live in separate required fields. Once the address itself includes a
    locality tail, however, that tail must parse as one complete US location.
    This rejects ambiguous or obfuscated tails instead of trusting the sibling
    fields over visible text such as ``Miami F.L.``.
    """
    normalized = canonicalize_location_text(value)
    if (
        not _looks_like_street(normalized)
        or _MULTI_LOCATION_CITY_SEPARATOR_RE.search(normalized) is not None
    ):
        return False

    tail = ""
    if "," in normalized:
        street, tail = normalized.split(",", 1)
        street_matches = tuple(_RESULT_STREET_RE.finditer(street))
        if not street_matches:
            return False
        street_postfix = street[street_matches[-1].end() :].strip(" ,.")
        if _RESULT_STREET_POSTFIX_RE.fullmatch(street_postfix) is None:
            return False
        tail = tail.strip(" ,")
        if _RESULT_UNIT_ONLY_WITH_COUNTRY_RE.fullmatch(tail):
            return True
        if "," in tail:
            first, remainder = tail.split(",", 1)
            if _RESULT_UNIT_ONLY_RE.fullmatch(first.strip(" ,")):
                tail = remainder.strip(" ,")
    else:
        street_matches = tuple(_RESULT_STREET_RE.finditer(normalized))
        if street_matches:
            tail = normalized[street_matches[-1].end() :].strip(" ,.")
            if _RESULT_UNIT_ONLY_WITH_COUNTRY_RE.fullmatch(tail):
                return True

    if not tail:
        return True
    # A ZIP-only street tail is complete when the sibling structured city and
    # state fields are required and the ZIP independently resolves to that
    # same state. IN/NE/OR are accepted here only as the narrow prose or
    # directional collisions seen immediately after a proven street suffix.
    # They never become location claims and cannot override a conflicting ZIP.
    zip_tail = _RESULT_STREET_ZIP_TAIL_RE.fullmatch(tail)
    if zip_tail is not None:
        tail_zip = normalize_zip(zip_tail.group("zip"))
        return bool(
            tail_zip is not None
            and location_state(tail_zip) == declared_state
            and (declared_zip is None or tail_zip == declared_zip)
        )

    # "123 Main St in Dallas TX" is ordinary prose, not an Indiana claim.
    # Strip the preposition only when the remainder is itself one complete
    # locality that must still agree with all sibling structured fields.
    if tail.upper().startswith("IN "):
        candidate = tail[3:].strip()
        candidate_parts = location_parts(candidate)
        if candidate_parts is not None and candidate_parts[1] is not None:
            tail = candidate
    trailing_unit = _RESULT_TRAILING_UNIT_RE.search(tail)
    if trailing_unit is not None and trailing_unit.start() > 0:
        candidate = tail[: trailing_unit.start()].strip(" ,.")
        if location_parts(candidate) is not None:
            tail = candidate
    parts = location_parts(tail)
    if parts is None:
        return False
    tail_state, tail_city, tail_zip = parts
    if tail_city is None:
        return False
    if tail_state != declared_state or tail_city != declared_city:
        return False
    return declared_zip is None or tail_zip is None or tail_zip == declared_zip


def _exact_state(value: str) -> str | None:
    return normalize_state(value)


def _exact_zip(value: str) -> str | None:
    return normalize_zip(value)


def _result_county_name_match(value: str) -> re.Match[str] | None:
    """Match a county equivalent without treating ordinary city tails as one."""

    return _RESULT_COUNTY_NAME_RE.fullmatch(
        value
    ) or _RESULT_INDEPENDENT_CITY_NAME_RE.fullmatch(value)


def _authoritative_county_identity(
    value: str,
) -> tuple[str, str, str] | None:
    """Return the exact canonical county name, state, and five-digit FIPS.

    Unknown or ambiguous names fail closed instead of being treated as cities
    or trusting a caller-supplied state/FIPS prefix.
    """
    normalized = canonicalize_location_text(value).strip(" ,")
    if not normalized or _is_unknown_location_value(normalized):
        return None
    without_country = strip_country_suffix(normalized).strip(" ,")
    match = _result_county_name_match(without_country)
    if match is None:
        return None
    state_token = match.group("state")
    if state_token is None or (state := normalize_state(state_token)) is None:
        return None
    county = normalize_city(match.group("entity"))
    if county is None:
        return None
    county_fips = county_fips_for_name(county, state)
    if len(county_fips) != 1:
        return None
    fips = next(iter(county_fips))
    identity = county_identity_for_fips(fips)
    if identity is None or identity[0] != state:
        return None
    return identity[1], state, fips


def _authoritative_county_name_for_state(
    value: str,
    state: str,
) -> tuple[str, str] | None:
    """Resolve an output county name, allowing state omission beside FIPS."""
    normalized = canonicalize_location_text(value).strip(" ,")
    if not normalized or _is_unknown_location_value(normalized):
        return None
    without_country = strip_country_suffix(normalized).strip(" ,")
    # The District of Columbia is the sole county-equivalent whose canonical
    # Census name is also the complete jurisdiction name and carries no county
    # grammar suffix.  Keep this exception exact: accepting every bare county
    # authority name here would make an ordinary city such as ``Dallas`` look
    # county-shaped solely because a same-name county exists.
    if state == "DC" and normalize_city(without_country) == "DISTRICT OF COLUMBIA":
        county_fips = county_fips_for_name(without_country, state)
        if len(county_fips) != 1:
            return None
        fips = next(iter(county_fips))
        identity = county_identity_for_fips(fips)
        if identity is None or identity[0] != state:
            return None
        return identity[1], fips
    match = _result_county_name_match(without_country)
    if match is None:
        return None
    state_token = match.group("state")
    if state_token is not None and normalize_state(state_token) != state:
        return None
    county = normalize_city(match.group("entity"))
    if county is None:
        return None
    county_fips = county_fips_for_name(county, state)
    if len(county_fips) != 1:
        return None
    fips = next(iter(county_fips))
    identity = county_identity_for_fips(fips)
    if identity is None or identity[0] != state:
        return None
    return identity[1], fips


def _authoritative_geo_city_name(
    value: str,
    state: str,
    zips: set[str],
) -> tuple[str, str | None] | None:
    """Resolve a GeoRef city, including Census legal-place suffixes.

    Census geocoder place names may end in an LSAD such as ``city``, ``town``,
    ``village``, or ``CDP``.  Prefer the complete name first so intrinsic names
    such as Carson City remain intact; strip one recognized LSAD only when the
    complete name is not itself authoritative.
    """
    candidates = [value]
    stripped = _RESULT_CENSUS_PLACE_SUFFIX_RE.sub("", value).strip(" ,")
    if stripped and stripped != value:
        candidates.append(stripped)

    for candidate in candidates:
        embedded_zip: str | None = None
        # A Census place name can itself end in text that resembles a state
        # name (``Fort Washington``, ``West New York``), and many valid Census
        # places are not postal locality labels at all.  Resolve an exact place
        # identity in the already-declared state before asking the generic
        # city/state parser to split the string.  County/ZIP/CBSA convergence
        # and one-place ambiguity are still enforced by ``_geo_record_claims``
        # after this helper returns.
        direct_city = normalize_city(candidate)
        if direct_city is not None and (
            city_county_fips(direct_city, state)
            or non_place_city_county_fips(direct_city, state)
        ):
            return direct_city, None
        parts = location_parts(candidate)
        if parts is not None and parts[1] is not None:
            candidate_state, city, embedded_zip = parts
            if candidate_state != state:
                continue
            if embedded_zip is not None and zips and embedded_zip not in zips:
                continue
        else:
            city = normalize_city(candidate)
        if city is None:
            continue
        city_state = f"{city}, {state}"
        effective_zips = zips or ({embedded_zip} if embedded_zip is not None else set())
        if effective_zips:
            if all(
                city_zip_pair_is_authoritative(city_state, zip5)
                for zip5 in effective_zips
            ):
                return city, embedded_zip
        elif city_state_is_authoritative(city_state):
            return city, None
    return None


def _city_state_claim(value: str) -> str | None:
    """Extract one exact city/state claim from a declared field."""
    parts = location_parts(value)
    if parts is None:
        return None
    state, city, _zip5 = parts
    if city is None:
        return None
    return f"{city}, {state}"


def _street_tail_city_candidates(value: str) -> frozenset[str]:
    """Return city-like text following a numbered street suffix."""
    candidates: set[str] = set()
    for match in _RESULT_STREET_RE.finditer(value):
        if re.search(r"\d", value[: match.start()]) is None:
            continue
        tail = _normalized_city(value[match.end() :].strip(" ,."))
        if tail.startswith("IN "):
            # "123 Main St in Dallas TX" uses a preposition between the
            # street and city.  IN is prose here, not an Indiana claim.
            tail = tail[3:].strip()
        if tail:
            candidates.add(tail)
    return frozenset(candidates)


def _inferred_city_candidate(value: str) -> str | None:
    """Infer one city only when an address segment is unambiguous."""
    candidates = _street_tail_city_candidates(value)
    if len(candidates) == 1:
        return next(iter(candidates))
    if candidates or _looks_like_street(value):
        return None
    return _normalized_city(value)


def _segment_start(value: str, position: int) -> int:
    """Return the start of the address segment containing ``position``."""
    start = 0
    for match in _RESULT_ADDRESS_CLAIM_SEPARATOR_RE.finditer(value, 0, position):
        start = match.end()
    comma = value.rfind(",", start, position)
    return comma + 1 if comma >= start else start


def _segment_end(value: str, position: int) -> int:
    """Return the end of the address segment containing ``position``."""
    comma = value.find(",", position)
    separator = _RESULT_ADDRESS_CLAIM_SEPARATOR_RE.search(value, position)
    candidates = [
        boundary
        for boundary in (
            comma if comma >= 0 else None,
            separator.start() if separator is not None else None,
        )
        if boundary is not None
    ]
    return min(candidates) if candidates else len(value)


def _zip_token_is_numbered_street(value: str, start: int, end: int) -> bool:
    """Whether a five-digit token is the number starting a street segment."""
    if value[_segment_start(value, start) : start].strip():
        return False
    segment_end = _segment_end(value, end)
    suffix = value[end:segment_end]
    street = _RESULT_STREET_RE.search(suffix)
    if street is None:
        return False
    return re.search(r"[0-9]", suffix[: street.start()]) is None


def _state_token_is_numbered_street_name(
    value: str,
    start: int,
    end: int,
) -> bool:
    """Whether a state-name token occurs inside a numbered street name."""
    segment_start = _segment_start(value, start)
    prefix = value[segment_start:start]
    if re.search(r"[0-9]", prefix) is None:
        return False
    segment_end = _segment_end(value, end)
    suffix = value[end:segment_end]
    prior_street = _RESULT_STREET_RE.search(prefix)
    if prior_street is not None:
        # The one supported token after an already-complete street is the
        # ordinary conjunction in "123 Main St or 456 Elm St". Keep this
        # narrow so an earlier jurisdiction in "Miami FL to 100 Main Street"
        # cannot borrow the later street suffix and disappear as a false
        # street-name collision.
        return bool(
            value[start:end].upper() == "OR"
            and re.match(
                rf"^\s+[0-9]+[A-Za-z]?(?:-[0-9]+)?\s+"
                rf"(?:[A-Za-z0-9.'-]+\s+){{0,2}}{_RESULT_STREET_RE.pattern}",
                suffix,
                re.IGNORECASE,
            )
        )

    street = _RESULT_STREET_RE.search(suffix)
    if street is None:
        return False
    before_street = suffix[: street.start()]
    if re.search(r"\b[0-9]{2,}\b", before_street) is not None:
        return False
    # A real state-code/full-state collision is adjacent to the rest of the
    # street name (for example "NE 2nd Ave" or "Texas Avenue"), not separated
    # from a later address by an arbitrary prose run.
    return len(before_street.split()) <= 2


def _address_location_claims(
    value: str,
    declared_city: str | None,
    *,
    infer_city: bool = False,
) -> tuple[frozenset[str], frozenset[str], frozenset[str]] | None:
    """Collect every recognizable claim inside the declared address field."""
    if _contains_non_ascii_decimal(value) or _contains_unicode_format(value):
        return None
    value = canonicalize_location_text(value)
    if not value or _is_unknown_location_value(value):
        return None
    states: set[str] = set()
    city_states: set[str] = set()
    zips: set[str] = set()

    # A provider may label a ZIP before the street text. It is still an exact
    # location claim and cannot be hidden by a later in-scope city/state tail.
    for match in _RESULT_LABELED_POSTAL_RE.finditer(value):
        zip5 = _exact_zip(match.group("zip"))
        if zip5 is None:
            return None
        zip_state = location_state(zip5)
        if zip_state is None:
            return None
        zips.add(zip5)
        states.add(zip_state)

    # Collect every ASCII ZIP claim regardless of punctuation. The only
    # exception is a number explicitly labeled as an apartment, building,
    # floor, lot, suite, or unit. This closes delimiter-enumeration gaps while
    # preserving known unit-number feeds such as "Unit 33101".
    unit_zip_spans = {
        match.span("zip") for match in _RESULT_LABELED_UNIT_ZIP_RE.finditer(value)
    }
    for match in _RESULT_ANY_ASCII_ZIP_RE.finditer(value):
        if match.span("zip") in unit_zip_spans:
            continue
        if _zip_token_is_numbered_street(
            value,
            match.start("zip"),
            match.end("zip"),
        ):
            continue
        zip5 = _exact_zip(match.group("zip"))
        if zip5 is None:
            return None
        zip_state = location_state(zip5)
        if zip_state is None:
            return None
        zips.add(zip5)
        states.add(zip_state)

    # Full state names are authoritative location claims even when a provider
    # follows them with punctuation or prose that is not in a delimiter list.
    # Preserve the real city-name and street-name collisions: Washington, DC;
    # Kansas City, MO; and Texas Avenue must not become WA, KS, and TX claims.
    for match in _RESULT_FULL_STATE_TOKEN_RE.finditer(value):
        state = _exact_state(match.group("state"))
        if state is None:
            return None
        normalized_match = _normalized_city(match.group("state"))
        raw_tail = value[match.start() :]
        normalized_tail = " ".join(raw_tail.upper().split())
        if declared_city is not None and normalized_tail.startswith(declared_city):
            boundary = normalized_tail[len(declared_city) : len(declared_city) + 1]
            if not boundary or not boundary.isalnum():
                continue
        if infer_city:
            tail_parts = location_parts(raw_tail.strip(" ,."))
            if (
                tail_parts is not None
                and tail_parts[1] is not None
                and (
                    tail_parts[1] == normalized_match
                    or tail_parts[1].startswith(f"{normalized_match} ")
                )
            ):
                continue
        if _state_token_is_numbered_street_name(
            value,
            match.start("state"),
            match.end("state"),
        ):
            continue
        suffix = value[match.end() :].lstrip(" .")
        if _RESULT_STREET_RE.match(suffix) is not None:
            continue
        states.add(state)

    # First collect exact location tails using the same state-name, case, ZIP,
    # and country normalization as request-time enforcement.  This catches
    # provider forms such as "Miami FL USA", "Portland OR", and
    # "Miami Florida" without treating a numbered "123 Oak Ct" street tail as
    # Connecticut.
    for match in _RESULT_ADDRESS_EXACT_LOCATION_RE.finditer(value):
        state = _exact_state(match.group("state"))
        if state is None:
            continue
        normalized_match = _normalized_city(match.group("state"))
        if (
            declared_city is not None
            and normalized_match == declared_city
        ):
            # A city may itself be a state name.  In "Washington, DC", the
            # first locality token is the declared city, not a hidden WA claim.
            continue
        if infer_city:
            tail_parts = location_parts(value[match.start() :].strip(" ,"))
            if tail_parts is not None and tail_parts[1] == normalized_match:
                # Request fields have no separate city declaration. A complete
                # tail such as "Washington, DC 20001" still proves that the
                # state-name token is the city and the following state is the
                # actual jurisdiction.
                continue
        prefix = value[: match.start()].rstrip(" ,")
        segment = _RESULT_ADDRESS_CLAIM_SEPARATOR_RE.split(prefix)[-1]
        segment = segment.rsplit(",", 1)[-1].strip()
        candidates = _street_tail_city_candidates(segment)
        city_candidate: str | None = None
        if candidates:
            if declared_city is not None:
                if declared_city not in candidates:
                    return None
                city_candidate = declared_city
            elif infer_city and len(candidates) == 1:
                city_candidate = next(iter(candidates))
            else:
                return None
        elif segment and not _looks_like_street(segment):
            city_candidate = _normalized_city(segment)
            if declared_city is not None and city_candidate != declared_city:
                return None
            if declared_city is None and not infer_city:
                return None
        elif state in _RESULT_AMBIGUOUS_STREET_TAIL_STATE_CODES:
            # The final token in a numbered street line may be a suffix or
            # directional that happens to equal a USPS code.
            continue

        states.add(state)
        if city_candidate:
            city_states.add(f"{city_candidate}, {state}")
        if match.group("zip") is not None:
            zip5 = _exact_zip(match.group("zip"))
            if zip5 is None:
                return None
            zips.add(zip5)
            zip_state = location_state(zip5)
            if zip_state is None:
                return None
            states.add(zip_state)

    for match in _RESULT_ADDRESS_STATE_RE.finditer(value):
        state = _exact_state(match.group(1))
        if state is None:
            continue
        if declared_city is not None:
            following_segment = value[match.start(1) :].split(",", 1)[0]
            if _normalized_city(following_segment) == declared_city:
                # A city such as "Mt Kisco" begins with a USPS state code,
                # but the complete comma-delimited segment is the declared
                # city rather than an independent Montana claim.
                continue
        states.add(state)

        prefix = value[: match.start()].rstrip()
        city = prefix.rsplit(",", 1)[-1].strip()
        if city and ("," in prefix or not _looks_like_street(city)):
            city_states.add(f"{_normalized_city(city)}, {state}")

        if match.group(2) is not None:
            zip5 = match.group(2)
            zips.add(zip5)
            zip_state = location_state(zip5)
            if zip_state is None:
                return None
            states.add(zip_state)

    for match in _RESULT_UNPUNCTUATED_STATE_ZIP_RE.finditer(value):
        state = _exact_state(match.group(1))
        zip5 = _exact_zip(match.group(2))
        if state is None or zip5 is None:
            continue
        prefix = value[: match.start()].rstrip()
        raw_segment = prefix.rsplit(",", 1)[-1]
        if (
            state in _RESULT_AMBIGUOUS_STREET_TAIL_STATE_CODES
            and _looks_like_street(raw_segment)
        ):
            # Ct, IN, NE, and OR can be street suffixes, prose, or
            # directionals immediately before an otherwise authoritative ZIP.
            # The ZIP scanner above still records the exact jurisdiction.
            continue
        states.add(state)
        zips.add(zip5)
        zip_state = location_state(zip5)
        if zip_state is None:
            return None
        states.add(zip_state)

        if prefix.endswith(","):
            # The comma-aware parser above owns ordinary "City, ST ZIP".
            continue
        segment = _normalized_city(raw_segment)
        inferred_city = (
            _inferred_city_candidate(raw_segment) if infer_city else None
        )
        if declared_city is not None and not (
            segment == declared_city or segment.endswith(f" {declared_city}")
        ):
            # Without the expected declared city at the end of this segment,
            # the punctuation-free location is ambiguous and cannot be safely
            # reconciled with the record's other exact claims.
            return None
        city = declared_city or inferred_city
        if city is None:
            return None
        city_states.add(f"{city}, {state}")

    for match in _RESULT_UNPUNCTUATED_STATE_RE.finditer(value):
        state = _exact_state(match.group(1))
        if state is None:
            continue

        if _state_token_is_numbered_street_name(
            value,
            match.start(1),
            match.end(1),
        ):
            # Preserve state-code collisions inside a real street name or
            # between two numbered street alternatives: "123 NE 2nd Ave",
            # "123 Or Drive", and "123 Main St or 456 Elm St".
            continue

        suffix = value[match.end() :]
        if _RESULT_ZIP_AFTER_STATE_RE.match(suffix) is not None:
            # The stronger state-plus-ZIP scanner above owns this claim.
            continue
        prefix = value[: match.start()].rstrip()
        if prefix.endswith(","):
            # The comma-aware parser above owns ordinary "City, ST".
            continue
        segment = _RESULT_ADDRESS_CLAIM_SEPARATOR_RE.split(prefix)[-1].strip()
        candidates = _street_tail_city_candidates(segment)
        if not candidates:
            if _RESULT_STREET_RE.fullmatch(match.group(1)) is not None:
                # "123 Oak Ct" ends in a street suffix, not Connecticut.
                continue
            # Bare IN/OR/NE tokens after a street suffix are ordinarily prose
            # or directionals, not state claims. A preceding city candidate or
            # a state-plus-ZIP claim remains authoritative.
            if state in _RESULT_AMBIGUOUS_STREET_TAIL_STATE_CODES and _looks_like_street(
                segment
            ):
                continue
            if not _looks_like_street(segment):
                candidate = _normalized_city(segment)
                if not candidate:
                    continue
                states.add(state)
                if declared_city is not None and candidate != declared_city:
                    return None
                if declared_city is None and not infer_city:
                    return None
                city_states.add(f"{candidate}, {state}")
                continue
            states.add(state)
            continue

        states.add(state)
        if declared_city is not None and declared_city not in candidates:
            # The segment visibly names a different city than the record's
            # declared city, so no exact grant may reconcile the record.
            return None
        if declared_city is None:
            if not infer_city or len(candidates) != 1:
                return None
            city = next(iter(candidates))
        else:
            city = declared_city
        city_states.add(f"{city}, {state}")

    for match in _RESULT_ADDRESS_STANDALONE_ZIP_RE.finditer(value):
        zip5 = match.group(1)
        zips.add(zip5)
        zip_state = location_state(zip5)
        if zip_state is None:
            return None
        states.add(zip_state)

    # Preserve support for an otherwise unparseable address ending in a ZIP.
    if (
        _RESULT_LABELED_UNIT_ZIP_AT_END_RE.search(value) is None
        and (match := _RESULT_ZIP_AT_END_RE.search(value)) is not None
    ):
        zip5 = match.group(1)
        zips.add(zip5)
        zip_state = location_state(zip5)
        if zip_state is None:
            return None
        states.add(zip_state)

    if (
        _RESULT_LABELED_UNIT_ZIP_AT_END_RE.search(value) is None
        and (match := _RESULT_ZIP_COUNTRY_AT_END_RE.search(value)) is not None
    ):
        zip5 = _exact_zip(match.group("zip"))
        if zip5 is None:
            return None
        zips.add(zip5)
        zip_state = location_state(zip5)
        if zip_state is None:
            return None
        states.add(zip_state)

    return frozenset(states), frozenset(city_states), frozenset(zips)


def _record_location_claims(
    record: Mapping[str, object],
    location_fields: tuple[str, ...],
) -> tuple[frozenset[str], frozenset[str], frozenset[str]] | None:
    """Derive exact claims only from the capability-declared location fields."""
    declared: dict[str, str] = {}
    required_location_fields = frozenset({"address", "city", "state"})
    for field in location_fields:
        if field not in record:
            if field in required_location_fields:
                return None
            continue
        raw = record[field]
        if raw is None:
            if field in required_location_fields:
                return None
            continue
        if type(raw) is not str:
            return None
        value = raw.strip()
        if not value:
            # An optional ZIP may be omitted or null. Once present, even an
            # optional location field must contain a valid value.
            return None
        if _contains_non_ascii_decimal(value) or _contains_unicode_format(value):
            return None
        value = canonicalize_location_text(value)
        if not value or _is_unknown_location_value(value):
            return None
        declared[field] = value

    states: set[str] = set()
    city_states: set[str] = set()
    zips: set[str] = set()

    state_value = declared.get("state")
    if state_value is not None:
        state = _exact_state(state_value)
        if state is None:
            return None
        states.add(state)
        structured_state = state
    else:
        return None

    declared_zip_values = [
        declared[field]
        for field in ("zip_code", "zip", "zipcode", "postal_code")
        if field in declared
    ]
    canonical_zips: set[str] = set()
    for zip_value in declared_zip_values:
        zip5 = _exact_zip(zip_value)
        if zip5 is None:
            return None
        canonical_zips.add(zip5)
    # Alias spellings are accepted only when they make one identical claim.
    # A conflicting shadow alias is an ambiguous request and fails closed.
    if len(canonical_zips) > 1:
        return None
    if canonical_zips:
        zip5 = next(iter(canonical_zips))
        zips.add(zip5)
        zip_state = location_state(zip5)
        if zip_state is None:
            return None
        states.add(zip_state)

    city = declared.get("city")
    if city is None:
        return None
    unpaired_city: str | None = None
    normalized_original = canonicalize_location_text(city).strip(" ,")
    city_parts = location_parts(city)
    if city_parts is not None:
        city_state, city_name, city_zip = city_parts
        # A city field cannot be a state-only or ZIP-only location. It is
        # either one nonempty plain city or a complete city+state(+ZIP).
        if city_name is None:
            if city_zip is not None or strip_country_suffix(city) != normalized_original:
                return None
            # A full state name can also be a real city name. Treat it as the
            # separately declared city and let the authoritative city/state
            # and city/ZIP checks below decide it. State codes remain
            # incomplete city values. This supports split provider fields for
            # Washington, DC and New York, NY without making "Texas, TX" an
            # authoritative place.
            if len(normalized_original) == 2:
                return None
            unpaired_city = _normalized_city(city)
            if not unpaired_city:
                return None
            declared_city = unpaired_city
        else:
            states.add(city_state)
            city_states.add(f"{city_name}, {city_state}")
            if city_zip is not None:
                zips.add(city_zip)
                zip_state = location_state(city_zip)
                if zip_state is None:
                    return None
                states.add(zip_state)
            declared_city = city_name
    else:
        if strip_country_suffix(city) != normalized_original:
            # A country suffix asserts that the field is a compound location;
            # without a state it is incomplete rather than a literal city.
            return None
        if _RESULT_CITY_STATE_TAIL_RE.search(city):
            return None
        if _MULTI_LOCATION_CITY_SEPARATOR_RE.search(city) is not None:
            return None
        unpaired_city = _normalized_city(city)
        if not unpaired_city:
            return None
        declared_city = unpaired_city

    address = declared.get("address")
    if address is not None:
        structured_zip = next(iter(zips)) if len(zips) == 1 else None
        if not _structured_address_tail_matches(
            address,
            declared_city,
            structured_state,
            structured_zip,
        ):
            return None
        address_claims = _address_location_claims(
            address,
            declared_city,
        )
        if address_claims is None:
            return None
        address_states, address_city_states, address_zips = address_claims
        states.update(address_states)
        city_states.update(address_city_states)
        zips.update(address_zips)

    if len(states) != 1:
        return None
    state = next(iter(states))
    if unpaired_city:
        city_states.add(f"{unpaired_city}, {state}")

    if len(city_states) > 1 or len(zips) > 1:
        return None
    return frozenset(states), frozenset(city_states), frozenset(zips)


def _territory_claims(
    territories: tuple[str, ...],
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Normalize grants without state-level broadening of city or ZIP grants."""
    states: set[str] = set()
    city_states: set[str] = set()
    zips: set[str] = set()
    for territory in territories:
        if not isinstance(territory, str):
            continue
        value = territory.strip()
        if not value:
            continue
        if (state := _exact_state(value)) is not None:
            states.add(state)
        elif (zip5 := _exact_zip(value)) is not None:
            zips.add(zip5)
        elif (city_state := _city_state_claim(value)) is not None:
            city_states.add(city_state)
    return frozenset(states), frozenset(city_states), frozenset(zips)


def _has_unresolved_compound_tail(value: str) -> bool:
    """Whether a scalar hides an unparsed suffix after a proven location.

    Compound separators may legitimately appear before the locality in a
    street description. They may not be used after an already complete state,
    city/state, ZIP, or address claim to append a second unresolved target.
    A labeled unit is the only non-location suffix accepted at that point.
    """

    normalized = canonicalize_location_text(value)
    for separator in _MULTI_LOCATION_CITY_SEPARATOR_RE.finditer(normalized):
        prefix = normalized[: separator.start()].strip(" ,")
        suffix = normalized[separator.end() :].strip(" ,")
        prefix_parts = location_parts(prefix)
        prefix_claims = (
            None
            if prefix_parts is not None
            else _address_location_claims(prefix, None, infer_city=True)
        )
        has_location_prefix = prefix_parts is not None or bool(
            prefix_claims is not None and any(prefix_claims)
        )
        if not has_location_prefix:
            continue
        if not suffix or _RESULT_UNIT_ONLY_WITH_COUNTRY_RE.fullmatch(suffix) is None:
            return True
    return False


def _has_incomplete_street_locality_tail(value: str) -> bool:
    """Reject street text followed by a non-authoritative locality fragment."""

    normalized = canonicalize_location_text(value)
    if not _looks_like_street(normalized):
        return False
    street_matches = tuple(_RESULT_STREET_RE.finditer(normalized))
    if not street_matches:
        return False
    tail = normalized[street_matches[-1].end() :].strip(" ,.")
    if (
        not tail
        or _RESULT_UNIT_ONLY_WITH_COUNTRY_RE.fullmatch(tail) is not None
        or _RESULT_STREET_ZIP_TAIL_RE.fullmatch(tail) is not None
    ):
        return False

    candidate = tail
    leading_unit = _RESULT_LEADING_UNIT_LOCALITY_RE.fullmatch(candidate)
    if leading_unit is not None:
        candidate = leading_unit.group("locality").strip(" ,.")
    trailing_unit = _RESULT_TRAILING_UNIT_RE.search(candidate)
    if trailing_unit is not None:
        if trailing_unit.start() == 0:
            return False
        candidate = candidate[: trailing_unit.start()].strip(" ,.")
    if candidate.upper().startswith("IN "):
        candidate = candidate[3:].strip(" ,.")
    return location_parts(candidate) is None


def _request_location_claims(
    value: str,
) -> tuple[frozenset[str], frozenset[str], frozenset[str]] | None:
    """Resolve an exact request value or every location claim in an address.

    ``None`` means malformed or internally contradictory. Three empty sets mean
    a non-locating scalar such as a street line without a city/state. The
    distinction lets multi-parameter tools tolerate that street component while
    still requiring another independently in-scope location value.
    """
    if _contains_non_ascii_decimal(value) or _contains_unicode_format(value):
        return None
    if _has_unresolved_compound_tail(value):
        return None
    if _has_incomplete_street_locality_tail(value):
        return None
    normalized_county = canonicalize_location_text(value).strip(" ,")
    county_without_country = strip_country_suffix(normalized_county).strip(" ,")
    if _result_county_name_match(county_without_country) is not None:
        county_identity = _authoritative_county_identity(value)
        if county_identity is None:
            return None
        _county_name, state, _county_fips = county_identity
        return frozenset({state}), frozenset(), frozenset()
    parts = location_parts(value)
    if parts is not None:
        state, city, zip5 = parts
        return (
            frozenset({state}),
            frozenset({f"{city}, {state}"}) if city is not None else frozenset(),
            frozenset({zip5}) if zip5 is not None else frozenset(),
        )

    # A value that is not one complete scalar above must be an actual street
    # expression before the address parser may derive any locality claim.
    # Otherwise a valid trailing city or ZIP could launder an unresolved
    # prefix, alternate place, or provider placeholder.
    normalized_value = canonicalize_location_text(value)
    starts_like_zip_with_residue = bool(
        re.match(r"^[0-9]{5}(?:-[0-9]{4})?\s+", normalized_value)
        and _RESULT_STREET_RE.search(normalized_value) is None
    )
    if starts_like_zip_with_residue or not _looks_like_street(value):
        return None

    claims = _address_location_claims(value, None, infer_city=True)
    if claims is None:
        return None
    states, city_states, zips = claims
    if not any(claims):
        normalized_original = value.strip().strip(" ,")
        if (
            strip_country_suffix(value) != normalized_original
            or not _looks_like_street(value)
        ):
            # A bare/country-only locality is ambiguous, while a street-only
            # component may be combined with a separately scoped county.
            return None
    if len(states) > 1 or len(city_states) > 1 or len(zips) > 1:
        return None
    return claims


def _location_claims_intersect_territories(
    claims: tuple[frozenset[str], frozenset[str], frozenset[str]],
    territories: tuple[str, ...],
) -> bool:
    states, city_states, zips = claims
    granted_states, granted_city_states, granted_zips = _territory_claims(territories)
    if any(not city_state_is_authoritative(claim) for claim in city_states):
        return False
    if len(city_states) > 1 or len(zips) > 1:
        return False
    claim_zip = next(iter(zips), None)
    for claim in city_states:
        city, state = claim.rsplit(",", 1)
        if not city_claim_is_unambiguous(
            city.strip(),
            state.strip(),
            zip_value=claim_zip,
        ):
            return False
    for territory in territories:
        granted = location_parts(territory)
        if granted is None:
            return False
        granted_state, granted_city, granted_zip = granted
        if granted_city is not None and not city_claim_is_unambiguous(
            granted_city,
            granted_state,
            zip_value=granted_zip,
        ):
            return False
    if city_states and zips:
        # City and ZIP claims must agree independently of grant breadth. A
        # state grant is not permission to release a contradictory or unknown
        # city/ZIP combination.
        if len(city_states) != 1 or len(zips) != 1:
            return False
        if not city_zip_pair_is_authoritative(
            next(iter(city_states)),
            next(iter(zips)),
        ):
            return False
    if states & granted_states:
        return True

    matches_exact_grant = bool(
        city_states & granted_city_states or zips & granted_zips
    )
    if not matches_exact_grant:
        return False
    if city_states and zips:
        return True
    return True


def location_value_within_territories(
    value: object,
    territories: tuple[str, ...],
) -> bool:
    """Return whether one complete scalar location is authoritative and granted.

    Service-layer workflows use this before invoking a nested search that does
    not pass back through FastMCP middleware, such as a persisted alert.
    """
    if type(value) is not str:
        return False
    claims = _request_location_claims(value)
    return bool(
        claims is not None
        and any(claims)
        and _location_claims_intersect_territories(claims, territories)
    )


def structured_property_within_territories(
    record: Mapping[str, object],
    territories: tuple[str, ...],
    *,
    location_fields: tuple[str, ...] = ("address", "city", "state", "zip_code"),
) -> bool:
    """Validate one structured property before it influences or leaves a tool."""
    claims = _record_location_claims(record, location_fields)
    return bool(
        claims is not None
        and _location_claims_intersect_territories(claims, territories)
    )


def _same_json_value(left: object, right: object) -> bool:
    """Exact, type-sensitive JSON equality with object key order ignored."""
    pending: list[tuple[object, object]] = [(left, right)]
    while pending:
        first, second = pending.pop()
        if type(first) is not type(second):
            return False
        if isinstance(first, Mapping):
            if first.keys() != second.keys():
                return False
            pending.extend((first[key], second[key]) for key in first)
        elif isinstance(first, list):
            if len(first) != len(second):
                return False
            pending.extend(zip(first, second, strict=True))
        elif first != second:
            return False
    return True


_RESULT_MODEL_TYPES = (
    AggregatedSearchResult,
    GeoRef,
    Listing,
    MarketOverview,
    OwnerRecord,
    ParcelRecord,
    PropertyDetail,
    PropertySummary,
    RentComparable,
    RentComps,
    SaleComp,
    SearchResult,
    *RESULT_MODEL_EXPORTS,
)
_RESULT_MODELS = {model.__name__: model for model in _RESULT_MODEL_TYPES}
_STATE_BY_FIPS = {fips: state for state, fips in STATE_FIPS.items()}


def _strict_result_model(
    model_name: str,
    payload: object,
    *,
    allow_extra_fields: bool = False,
) -> bool:
    """Validate one value with strict JSON semantics and no unknown fields."""
    model = _RESULT_MODELS.get(model_name)
    if model is None:
        return False
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        model.model_validate_json(
            encoded,
            strict=True,
            extra="allow" if allow_extra_fields else "forbid",
        )
    except (ValidationError, TypeError, ValueError, OverflowError):
        return False
    return True


def _result_path_values(
    payload: Mapping[str, object],
    path: str,
) -> tuple[object, ...] | None:
    """Resolve a declared result path without recursively scanning payloads."""
    if path == "$":
        return (payload,)
    values: tuple[object, ...] = (payload,)
    for segment in path.split("."):
        is_many = segment.endswith("[]")
        key = segment[:-2] if is_many else segment
        resolved: list[object] = []
        for current in values:
            if not isinstance(current, Mapping):
                return None
            if key == "*":
                candidates = tuple(current.values())
            elif key not in current:
                # Strict envelope validation already decides whether a field
                # is required. A missing optional branch contains no records.
                continue
            else:
                candidates = (current[key],)
            for candidate in candidates:
                if candidate is None:
                    continue
                if is_many:
                    if type(candidate) is not list:
                        return None
                    resolved.extend(candidate)
                else:
                    resolved.append(candidate)
        values = tuple(resolved)
    return values


def _request_path_key_present(payload: Mapping[str, object], path: str) -> bool:
    """Return whether every named key in a request representation is present."""

    current: tuple[object, ...] = (payload,)
    for segment in path.split("."):
        is_many = segment.endswith("[]")
        key = segment[:-2] if is_many else segment
        next_values: list[object] = []
        found = False
        for value in current:
            if not isinstance(value, Mapping) or key not in value:
                continue
            found = True
            candidate = value[key]
            if is_many and type(candidate) is list:
                next_values.extend(candidate)
            else:
                next_values.append(candidate)
        if not found:
            return False
        current = tuple(next_values)
    return True


def _request_policy_representation_present(
    payload: Mapping[str, object],
    path: str,
) -> bool:
    """Select a request shape without treating a safe sibling as authority."""

    segments = path.split(".")
    current: tuple[object, ...] = (payload,)
    for index, segment in enumerate(segments):
        is_many = segment.endswith("[]")
        key = segment[:-2] if is_many else segment
        last = index == len(segments) - 1
        next_values: list[object] = []
        found = False
        for value in current:
            if not isinstance(value, Mapping) or key not in value:
                continue
            found = True
            candidate = value[key]
            if last:
                if is_many:
                    return type(candidate) is list or not isinstance(candidate, Mapping)
                return not isinstance(candidate, list)
            if is_many:
                if type(candidate) is not list:
                    return False
                next_values.extend(candidate)
            else:
                next_values.append(candidate)
        if not found:
            return False
        current = tuple(next_values)
    return False


def _request_contract_is_strictly_typed(
    payload: Mapping[str, object],
    contract: RequestTerritoryContract,
) -> bool:
    """Distinguish alternative request shapes using their closed DTOs.

    Shape paths alone cannot distinguish a single permit mapping from a
    collection envelope because both occupy the same top-level argument.  A
    contract is selectable only when its declared envelope and record DTOs
    validate, preventing several alternatives from matching one mapping.
    """

    if contract.envelope_model is not None:
        envelope_values = _result_path_values(
            payload,
            contract.envelope_path or "",
        )
        if (
            envelope_values is None
            or len(envelope_values) != 1
            or not isinstance(envelope_values[0], Mapping)
            or not _strict_result_model(
                contract.envelope_model,
                envelope_values[0],
                allow_extra_fields=contract.allow_envelope_extra_fields,
            )
        ):
            return False

    for policy in contract.records:
        records = _result_path_values(payload, policy.path)
        required_subject = "." not in policy.path
        if records is None or (required_subject and not records):
            return False
        if any(
            not isinstance(record, Mapping)
            or not _strict_result_model(
                policy.model,
                record,
                allow_extra_fields=policy.allow_extra_fields,
            )
            for record in records
        ):
            return False
    return True


def _address_record_within(
    record: Mapping[str, object],
    location_fields: tuple[str, ...],
    territories: tuple[str, ...],
) -> bool:
    """Require every declared full-address carrier to resolve in territory."""
    for field in location_fields:
        raw = record.get(field)
        if type(raw) is not str:
            return False
        if _contains_non_ascii_decimal(raw) or _contains_unicode_format(raw):
            return False
        value = canonicalize_location_text(raw)
        if not value or _is_unknown_location_value(value):
            return False
        claims = _request_location_claims(value)
        if claims is None or not any(claims):
            return False
        if not _location_claims_intersect_territories(claims, territories):
            return False
    return True


def _property_address_record_within(
    record: Mapping[str, object],
    location_fields: tuple[str, ...],
    territories: tuple[str, ...],
) -> bool:
    """Require each declared property address to contain street and locality."""

    for field in location_fields:
        raw = record.get(field)
        if type(raw) is not str:
            return False
        if _contains_non_ascii_decimal(raw) or _contains_unicode_format(raw):
            return False
        value = canonicalize_location_text(raw)
        if (
            not value
            or _is_unknown_location_value(value)
            or not _looks_like_street(value)
            or _RESULT_NUMBERED_STREET_START_RE.match(value) is None
        ):
            return False
        claims = _request_location_claims(value)
        if claims is None:
            return False
        states, city_states, zips = claims
        if len(states) != 1 or len(city_states) != 1 or len(zips) > 1:
            return False
        city_state = next(iter(city_states))
        city, state = city_state.rsplit(",", 1)
        if not _structured_address_tail_matches(
            value,
            city.strip(),
            state.strip(),
            next(iter(zips)) if zips else None,
        ):
            return False
        if not _location_claims_intersect_territories(claims, territories):
            return False
    return True


def _location_values_record_within(
    record: Mapping[str, object],
    location_fields: tuple[str, ...],
    territories: tuple[str, ...],
) -> bool:
    """Validate every scalar in one or more explicit location-value fields.

    Unlike ``_territory_values``, this boundary helper rejects malformed list
    members instead of silently dropping them.  Closed request/result DTOs
    decide which aliases may coexist; this function proves every supplied
    value resolves inside the granted territory.
    """

    found = False
    for field in location_fields:
        raw = record.get(field)
        if raw is None:
            continue
        if type(raw) is str:
            values = (raw,)
        elif type(raw) is list and raw and all(type(item) is str for item in raw):
            values = tuple(raw)
        else:
            return False
        found = True
        for raw_value in values:
            if (
                _contains_non_ascii_decimal(raw_value)
                or _contains_unicode_format(raw_value)
            ):
                return False
            value = canonicalize_location_text(raw_value)
            if not value or _is_unknown_location_value(value):
                return False
            claims = _request_location_claims(value)
            if claims is None or not any(claims):
                return False
            if not _location_claims_intersect_territories(claims, territories):
                return False
    return found


def _geo_record_claims(
    record: Mapping[str, object],
) -> tuple[frozenset[str], frozenset[str], frozenset[str]] | None:
    """Derive claims only when every populated GeoRef carrier reconciles."""
    level = record.get("level")
    state_fips = record.get("state_fips")
    name = record.get("name")
    if type(level) is not str or type(state_fips) is not str or type(name) is not str:
        return None
    if _contains_non_ascii_decimal(name) or _contains_unicode_format(name):
        return None
    state = _STATE_BY_FIPS.get(state_fips)
    normalized_name = canonicalize_location_text(name)
    if state is None or not normalized_name or _is_unknown_location_value(name):
        return None

    county_fips = record.get("county_fips")
    if county_fips is not None and (
        type(county_fips) is not str
        or re.fullmatch(r"[0-9]{5}", county_fips) is None
        or not county_fips.startswith(state_fips)
        or county_identity_for_fips(county_fips) is None
    ):
        return None
    tract = record.get("tract")
    tract_identity: tuple[str, str] | None = None
    if tract is not None:
        if type(tract) is not str:
            return None
        tract_identity = tract_identity_for_geoid(tract)
        if tract_identity is None or tract_identity[0] != state:
            return None
    cbsa = record.get("cbsa")
    if cbsa is not None and (
        type(cbsa) is not str or re.fullmatch(r"[0-9]{5}", cbsa) is None
    ):
        return None

    if level not in {"state", "county", "city", "zip", "tract"}:
        return None
    if level == "county" and county_fips is None:
        return None
    if level == "tract" and (tract_identity is None or county_fips is None):
        return None
    if level == "city" and county_fips is None:
        return None
    # A more-specific tract carrier on a broader GeoRef cannot be proven to
    # share one Census place with a city name from county and ZCTA relations
    # alone.  It is accepted only when the record itself is tract-level.
    if tract is not None and level != "tract":
        return None
    if level == "state" and any(
        value is not None for value in (county_fips, cbsa, record.get("zip"), tract)
    ):
        return None

    states = {state}
    cities: set[str] = set()
    zips: set[str] = set()
    raw_zip = record.get("zip")
    if raw_zip is not None:
        if (
            type(raw_zip) is not str
            or _contains_non_ascii_decimal(raw_zip)
            or _contains_unicode_format(raw_zip)
        ):
            return None
        zip5 = normalize_zip(raw_zip)
        if zip5 is None or location_state(zip5) != state:
            return None
        zips.add(zip5)
    if level == "zip" and not zips:
        return None

    city_identity: str | None = None
    possible_counties: set[str] | None = None

    if level == "state":
        if normalize_state(normalized_name) != state:
            return None
    elif level == "county":
        county_identity = _authoritative_county_name_for_state(
            normalized_name,
            state,
        )
        if county_identity is None or county_identity[1] != county_fips:
            return None
        possible_counties = {county_identity[1]}
    elif level == "city":
        city_name_identity = _authoritative_geo_city_name(
            normalized_name,
            state,
            zips,
        )
        if city_name_identity is None:
            return None
        city_identity, embedded_zip = city_name_identity
        if embedded_zip is not None:
            zips.add(embedded_zip)
        city_state = f"{city_identity}, {state}"
        cities.add(city_state)
        possible_counties = set(city_county_fips(city_identity, state))
        if not possible_counties:
            possible_counties = set(
                non_place_city_county_fips(city_identity, state)
            )
        if not possible_counties:
            return None
        if not city_claim_is_unambiguous(
            city_identity,
            state,
            county_fips=county_fips,
            zip_value=next(iter(zips), None),
        ):
            return None
    elif level == "tract":
        assert tract is not None and tract_identity is not None
        if tract_identity[1] != county_fips:
            return None
        tract_code = tract[-6:]
        integer = str(int(tract_code[:4]))
        fraction = tract_code[4:]
        tract_label = integer if fraction == "00" else f"{integer}.{fraction}"
        allowed_names = {
            tract,
            f"TRACT {tract_label}",
            f"CENSUS TRACT {tract_label}",
        }
        if normalized_name.upper().strip(" ,") not in allowed_names:
            return None
        possible_counties = {county_fips}
    else:
        zip5 = next(iter(zips))
        exact_name_zip = normalize_zip(normalized_name)
        if exact_name_zip != zip5:
            name_claims = _request_location_claims(normalized_name)
            if name_claims is None or not any(name_claims):
                return None
            name_states, name_cities, name_zips = name_claims
            if name_states and name_states != frozenset({state}):
                return None
            if name_zips and name_zips != frozenset({zip5}):
                return None
            if name_cities:
                if len(name_cities) != 1:
                    return None
                city_state = next(iter(name_cities))
                if not city_zip_pair_is_authoritative(city_state, zip5):
                    return None
                city_name, city_state_code = city_state.rsplit(",", 1)
                city_authority = set(
                    city_county_fips(city_name.strip(), city_state_code.strip())
                )
                if city_authority:
                    possible_counties = city_authority
                else:
                    # Assigned postal localities such as Bronx and Staten
                    # Island are not Census places.  Their exact city + ZIP
                    # pair may still be released when the ZIP supplies the
                    # county anchor and every supplied carrier converges.
                    if not city_claim_is_unambiguous(
                        city_name.strip(),
                        city_state_code.strip(),
                        county_fips=county_fips,
                        zip_value=zip5,
                    ):
                        return None
                    possible_counties = set(zip_county_fips(zip5))
                    if not possible_counties:
                        return None
                cities.add(city_state)
            elif not name_zips:
                return None

    if zips:
        zip5 = next(iter(zips))
        if tract is not None and zip5 not in tract_zip_codes(tract):
            return None
        zip_authority = set(zip_county_fips(zip5))
        if not zip_authority:
            return None
        if possible_counties is None:
            possible_counties = zip_authority
        else:
            possible_counties.intersection_update(zip_authority)
            if not possible_counties:
                return None

    if (
        county_fips is not None
        and possible_counties is not None
        and county_fips not in possible_counties
    ):
        return None
    if level in {"city", "county", "tract"} and county_fips is None:
        return None

    if cbsa is not None:
        if county_fips is None or cbsa not in county_cbsa_codes(county_fips):
            return None

    if cities and zips:
        if len(cities) != 1 or len(zips) != 1:
            return None
        if not city_zip_pair_is_authoritative(next(iter(cities)), next(iter(zips))):
            return None
    if cities:
        city, city_state = next(iter(cities)).rsplit(",", 1)
        if not city_claim_is_unambiguous(
            city.strip(),
            city_state.strip(),
            county_fips=county_fips,
            zip_value=next(iter(zips), None),
        ):
            return None

    return frozenset(states), frozenset(cities), frozenset(zips)


def _county_sale_address_claims(
    address: str,
) -> tuple[frozenset[str], frozenset[str], frozenset[str]] | None:
    """Parse a sale address without mistaking a five-digit house number for ZIP.

    King County's real feed includes ``11745 24TH AVE NE``. The general
    adversarial parser must treat arbitrary five-digit tokens as ZIP claims,
    but a typed county-sale address may use one as the leading house number.
    Retry only that exact leading-number shape after replacing the house number
    with a non-ZIP placeholder; every later state, city, and ZIP claim remains
    visible to the normal parser.
    """
    claims = _request_location_claims(address)
    if claims is not None:
        return claims
    normalized = canonicalize_location_text(address)
    if (
        _looks_like_street(normalized)
        and re.match(r"^[0-9]{5}(?:-[0-9]+)?\s+", normalized) is not None
    ):
        masked = re.sub(
            r"^[0-9]{5}(?:-[0-9]+)?(?=\s)",
            "1",
            normalized,
            count=1,
        )
        return _request_location_claims(masked)
    return None


def _county_fips_reconciles_location_claims(
    county_fips: str,
    city_states: frozenset[str],
    zips: frozenset[str],
) -> bool:
    """Reconcile duplicated county and exact city/ZIP claims fail closed."""

    if zips:
        for zip5 in zips:
            possible = zip_county_fips(zip5)
            if not possible or county_fips not in possible:
                return False
    if city_states and len(zips) > 1:
        return False
    for city_state in city_states:
        city, state = city_state.rsplit(",", 1)
        normalized_city = normalize_city(city)
        normalized_state = normalize_state(state)
        if normalized_city is None or normalized_state is None:
            return False
        possible = city_county_fips(
            normalized_city,
            normalized_state,
        )
        if not possible:
            possible = non_place_city_county_fips(
                normalized_city,
                normalized_state,
            )
        zip5 = next(iter(zips)) if len(zips) == 1 else None
        if possible and county_fips not in possible:
            return False
        if not city_claim_is_unambiguous(
            normalized_city,
            normalized_state,
            county_fips=county_fips,
            zip_value=zip5,
        ):
            return False
    return True


def _county_sale_record_within(
    record: Mapping[str, object],
    territories: tuple[str, ...],
) -> bool:
    """Authorize a county sale comp only for an exact granted state.

    Public county adapters commonly provide a street-only or null address.
    Their configured five-digit county FIPS is still authoritative for a state
    grant, but it cannot prove a narrower city or ZIP grant.  Any recognizable
    address claim must agree with the FIPS state.
    """
    county_fips = record.get("county_fips")
    if type(county_fips) is not str or re.fullmatch(r"[0-9]{5}", county_fips) is None:
        return False
    state = _STATE_BY_FIPS.get(county_fips[:2])
    if state is None:
        return False
    known_county = county_identity_for_fips(county_fips) is not None

    address = record.get("address")
    claims: tuple[frozenset[str], frozenset[str], frozenset[str]] | None = None
    if address is None:
        if not known_county:
            return False
    else:
        if type(address) is not str:
            return False
        claims = _county_sale_address_claims(address)
        if claims is None:
            return False
        states, city_states, zips = claims
        if states and states != frozenset({state}):
            return False
        if city_states and any(
            not claim.endswith(f", {state}") for claim in city_states
        ):
            return False
        if zips and any(location_state(zip5) != state for zip5 in zips):
            return False
        if city_states and zips:
            if len(city_states) != 1 or len(zips) != 1:
                return False
            if not city_zip_pair_is_authoritative(
                next(iter(city_states)),
                next(iter(zips)),
            ):
                return False
        if not _county_fips_reconciles_location_claims(
            county_fips,
            city_states,
            zips,
        ):
            return False
        complete_location = bool(city_states or zips)
        if not known_county and not complete_location:
            # An arbitrary provider FIPS is not sufficient authority by
            # itself. Unknown counties require an independently complete
            # address whose state agrees with the FIPS prefix.
            return False
        if complete_location:
            return _location_claims_intersect_territories(claims, territories)

    granted_states, _granted_cities, _granted_zips = _territory_claims(territories)
    return state in granted_states


def _non_geographic_text_record_is_safe(
    record: Mapping[str, object],
    location_fields: tuple[str, ...],
) -> bool:
    """Allow on-site descriptors while rejecting embedded regional locations."""
    for field in location_fields:
        raw = record.get(field)
        if raw is None:
            continue
        if type(raw) is not str:
            return False
        if _contains_non_ascii_decimal(raw) or _contains_unicode_format(raw):
            return False
        claims = _request_location_claims(raw)
        if claims is not None and any(claims):
            return False
        if claims is None and (
            _RESULT_ANY_ASCII_ZIP_RE.search(raw) is not None
            or _RESULT_ADDRESS_EXACT_LOCATION_RE.search(raw) is not None
            or _RESULT_FULL_STATE_TOKEN_RE.search(raw) is not None
        ):
            # A malformed, contradictory, or ambiguous string that still
            # carries obvious jurisdiction syntax is not an on-site descriptor.
            return False
    return True


_PERMIT_COLLECTION_FIELDS = (
    "permits",
    "results",
    "records",
    "features",
    "items",
    "data",
)


def _permit_property_record_within(
    record: Mapping[str, object],
    territories: tuple[str, ...],
    *,
    fallback_location: str | None = None,
) -> bool:
    canonical = canonical_permit_property(
        record,
        fallback_location=fallback_location,
    )
    return bool(
        canonical is not None
        and structured_property_within_territories(canonical, territories)
    )


def _permit_collection_record_within(
    record: Mapping[str, object],
    territories: tuple[str, ...],
) -> bool:
    """Validate every row in one supported permit mapping representation."""

    actual_by_token: dict[str, list[object]] = {}
    for key in record:
        token = re.sub(r"[^a-z0-9]", "", str(key).casefold())
        actual_by_token.setdefault(token, []).append(key)
    collection_keys: dict[str, object] = {}
    for field in _PERMIT_COLLECTION_FIELDS:
        token = re.sub(r"[^a-z0-9]", "", field.casefold())
        actual = actual_by_token.get(token, [])
        if len(actual) > 1:
            return False
        if actual:
            collection_keys[field] = actual[0]
    supplied_collections = list(collection_keys)
    if supplied_collections:
        # Multiple recognized collections are ambiguous even though the public
        # parser historically chose the first one.
        if len(supplied_collections) != 1:
            return False
        rows = record.get(collection_keys[supplied_collections[0]])
        if type(rows) is not list or not rows:
            return False
        city_keys = actual_by_token.get("city", [])
        if len(city_keys) > 1:
            return False
        fallback = record.get(city_keys[0]) if city_keys else None
        if fallback is not None and type(fallback) is not str:
            return False
        return all(
            isinstance(row, Mapping)
            and _permit_property_record_within(
                row,
                territories,
                fallback_location=fallback,
            )
            for row in rows
        )

    # A mapping with no collection field is the public single-permit shape.
    return _permit_property_record_within(record, territories)


def _stalled_signal_record_within(
    record: Mapping[str, object],
    territories: tuple[str, ...],
) -> bool:
    """Validate all duplicated location claims in one stalled-project signal."""

    address = record.get("address")
    normalized_address = record.get("normalized_address")
    source_record = record.get("record")
    if (
        type(address) is not str
        or type(normalized_address) is not str
        or not isinstance(source_record, Mapping)
    ):
        return False
    if any(
        _contains_non_ascii_decimal(value) or _contains_unicode_format(value)
        for value in (address, normalized_address)
    ):
        return False
    canonical_address = canonicalize_location_text(address).strip()
    canonical_normalized = canonicalize_location_text(normalized_address).strip()
    if (
        not canonical_address
        or not canonical_normalized
        or canonical_address.casefold() != canonical_normalized.casefold()
    ):
        return False
    if not _address_record_within(record, ("address",), territories):
        return False
    canonical_source = canonical_permit_property(source_record)
    source_address = (
        permit_full_address(canonical_source)
        if canonical_source is not None
        else None
    )
    return bool(
        source_address is not None
        and canonicalize_location_text(source_address).strip().casefold()
        == canonical_address.casefold()
    )


def _result_record_within(
    record: Mapping[str, object],
    policy: ResultTerritoryRecord,
    territories: tuple[str, ...],
) -> bool:
    """Validate one typed record using its explicitly declared location mode."""
    if policy.location_mode == "structured_property":
        claims = _record_location_claims(record, policy.location_fields)
        return bool(
            claims is not None
            and _location_claims_intersect_territories(claims, territories)
        )
    if policy.location_mode == "address":
        return _address_record_within(record, policy.location_fields, territories)
    if policy.location_mode == "property_address":
        return _property_address_record_within(
            record,
            policy.location_fields,
            territories,
        )
    if policy.location_mode == "location_values":
        return _location_values_record_within(
            record,
            policy.location_fields,
            territories,
        )
    if policy.location_mode == "county_sale":
        return _county_sale_record_within(record, territories)
    if policy.location_mode == "non_geographic_text":
        return _non_geographic_text_record_is_safe(record, policy.location_fields)
    if policy.location_mode == "permit_property":
        return _permit_property_record_within(record, territories)
    if policy.location_mode == "permit_collection":
        return _permit_collection_record_within(record, territories)
    if policy.location_mode == "stalled_signal":
        return _stalled_signal_record_within(record, territories)
    claims = _geo_record_claims(record)
    return bool(
        claims is not None
        and _location_claims_intersect_territories(claims, territories)
    )


_LocationIdentity = tuple[str, str, str]


def _scalar_location_identity(value: object) -> _LocationIdentity | None:
    """Return one level-preserving identity for a complete location scalar."""

    if type(value) is not str:
        return None
    if _contains_non_ascii_decimal(value) or _contains_unicode_format(value):
        return None
    county_identity = _authoritative_county_identity(value)
    if county_identity is not None:
        return "county", county_identity[1], county_identity[2]
    claims = _request_location_claims(value)
    if claims is None or not any(claims):
        return None
    states, city_states, zips = claims
    if len(states) != 1 or len(city_states) > 1 or len(zips) > 1:
        return None
    state = next(iter(states))
    if zips:
        return "zip", state, next(iter(zips))
    if city_states:
        city_state = next(iter(city_states))
        city, city_state_code = city_state.rsplit(",", 1)
        normalized_city = normalize_city(city)
        if normalized_city is None or city_state_code.strip() != state:
            return None
        return "city", state, normalized_city
    if normalize_state(value) == state:
        return "state", state, state
    return None


def _geo_location_identity(value: object) -> _LocationIdentity | None:
    """Return the declared GeoRef level after full carrier reconciliation."""

    if not isinstance(value, Mapping):
        return None
    claims = _geo_record_claims(value)
    if claims is None:
        return None
    states, city_states, zips = claims
    if len(states) != 1:
        return None
    state = next(iter(states))
    level = value.get("level")
    if level == "state":
        return "state", state, state
    if level == "county":
        county_fips = value.get("county_fips")
        return (
            ("county", state, county_fips)
            if type(county_fips) is str
            else None
        )
    if level == "city":
        if len(city_states) != 1:
            return None
        city = next(iter(city_states)).rsplit(",", 1)[0]
        normalized_city = normalize_city(city)
        return (
            ("city", state, normalized_city)
            if normalized_city is not None
            else None
        )
    if level == "zip":
        return ("zip", state, next(iter(zips))) if len(zips) == 1 else None
    if level == "tract":
        tract = value.get("tract")
        return ("tract", state, tract) if type(tract) is str else None
    return None


def _binding_values(
    source: Literal["request", "result"],
    path: str,
    payload: Mapping[str, object],
    request_args: Mapping[str, object],
) -> tuple[object, ...] | None:
    carrier = request_args if source == "request" else payload
    return _result_path_values(carrier, path)


def _binding_identities(
    values: tuple[object, ...],
    mode: Literal["location", "geo"],
) -> tuple[_LocationIdentity, ...] | None:
    resolver = _scalar_location_identity if mode == "location" else _geo_location_identity
    resolved = tuple(resolver(value) for value in values)
    if any(identity is None for identity in resolved):
        return None
    return tuple(identity for identity in resolved if identity is not None)


def _scalar_location_within_geo(value: object, geo: object) -> bool:
    """Prove one evidence location is contained in one reconciled GeoRef."""

    if type(value) is not str or not isinstance(geo, Mapping):
        return False
    geo_identity = _geo_location_identity(geo)
    claims = _request_location_claims(value)
    if geo_identity is None or claims is None or not any(claims):
        return False
    level, state, key = geo_identity
    states, city_states, zips = claims
    if states != frozenset({state}):
        return False
    if level == "state":
        return True
    if level == "zip":
        return zips == frozenset({key})
    if level == "city":
        geo_city_state = f"{key}, {state}"
        if city_states:
            return city_states == frozenset({geo_city_state})
        return bool(
            len(zips) == 1
            and city_zip_pair_is_authoritative(geo_city_state, next(iter(zips)))
        )
    if level == "county":
        county_identity = _authoritative_county_identity(value)
        if county_identity is not None:
            return county_identity[2] == key
        if zips or city_states:
            return _county_fips_reconciles_location_claims(
                key,
                city_states,
                zips,
            )
    return False


def _location_binding_matches(
    binding: ResultLocationBinding,
    payload: Mapping[str, object],
    request_args: Mapping[str, object],
) -> bool:
    left_values = _binding_values(
        binding.left_source,
        binding.left_path,
        payload,
        request_args,
    )
    right_values = _binding_values(
        binding.right_source,
        binding.right_path,
        payload,
        request_args,
    )
    if left_values is None or right_values is None:
        return False

    if binding.relation == "each_within":
        if len(left_values) != 1:
            return False
        return all(
            _scalar_location_within_geo(value, left_values[0])
            for value in right_values
        )

    left_identities = _binding_identities(left_values, binding.left_mode)
    right_identities = _binding_identities(right_values, binding.right_mode)
    if left_identities is None or right_identities is None:
        return False
    if binding.relation == "exact":
        return (
            len(left_identities) == len(right_identities) == 1
            and left_identities[0] == right_identities[0]
        )
    if binding.relation == "exact_multiset":
        return Counter(left_identities) == Counter(right_identities)
    return len(left_identities) == len(right_identities) and all(
        left == right
        for left, right in zip(left_identities, right_identities, strict=True)
    )


def _result_contract_matches(
    payload: Mapping[str, object],
    contract: ResultTerritoryContract,
    request_args: Mapping[str, object],
    territories: tuple[str, ...],
) -> bool:
    """Validate one complete typed result contract and all property paths."""
    if not _strict_result_model(contract.envelope_model, payload):
        return False

    if contract.request_location_param is not None:
        requested = request_args.get(contract.request_location_param)
        returned_values = _result_path_values(
            payload,
            contract.result_location_field or "",
        )
        returned = (
            returned_values[0]
            if returned_values is not None and len(returned_values) == 1
            else None
        )
        if type(requested) is not str or type(returned) is not str:
            return False
        if (
            _contains_non_ascii_decimal(requested)
            or _contains_unicode_format(requested)
            or _contains_non_ascii_decimal(returned)
            or _contains_unicode_format(returned)
        ):
            return False
        requested_parts = location_parts(requested)
        if requested_parts is None or location_parts(returned) != requested_parts:
            return False

    if any(
        not _location_binding_matches(binding, payload, request_args)
        for binding in contract.location_bindings
    ):
        return False

    for path in contract.forbid_nonempty_paths:
        values = _result_path_values(payload, path)
        if values is None or any(_has_value(value) for value in values):
            return False

    for policy in contract.records:
        records = _result_path_values(payload, policy.path)
        if records is None:
            return False
        for record in records:
            if not isinstance(record, Mapping):
                return False
            if not _strict_result_model(policy.model, record):
                return False
            if not _result_record_within(record, policy, territories):
                return False
    return True


class AccessEngine:
    def __init__(
        self,
        registry: WorkspaceRegistry | None,
        capabilities: dict[str, ToolCapability] | None = None,
    ) -> None:
        self.registry = registry
        self.capabilities = CAPABILITIES if capabilities is None else capabilities

    def _gate(self, ctx: TenantContext | None, tool_name: str) -> tuple[Decision, ToolCapability | None]:
        """Checks shared by listing and execution: identity, active, matrix, profile."""
        if ctx is None:
            return _denied("access denied: no authenticated workspace"), None
        if not ctx.active:
            return _denied("access denied: workspace access is inactive"), None
        if ctx.trusted:
            return Decision(outcome="allowed"), None
        cap = self.capabilities.get(tool_name)
        if cap is None:
            return _denied(f"access denied: unclassified tool {tool_name!r}"), None
        if ctx.profile.value not in cap.allowed_profiles:
            return _denied(
                f"access denied: profile {ctx.profile.value!r} may not use {tool_name!r}"
            ), cap
        return Decision(outcome="allowed"), cap

    def check_tool(self, ctx: TenantContext | None, tool_name: str) -> Decision:
        """Listing-level check (no arguments yet)."""
        decision, _cap = self._gate(ctx, tool_name)
        return decision

    def requires_result_territory_check(
        self,
        ctx: TenantContext | None,
        tool_name: str,
    ) -> bool:
        """Whether this exact call has a declared post-result policy."""
        decision, cap = self._gate(ctx, tool_name)
        return bool(
            decision.outcome == "allowed"
            and ctx is not None
            and not ctx.trusted
            and ctx.profile in TERRITORY_LIMITED
            and cap is not None
            and cap.result_territory_contracts
        )

    def _check_call(
        self,
        ctx: TenantContext | None,
        tool_name: str,
        args: dict | None,
        *,
        enforce_stateful: bool,
    ) -> tuple[Decision, dict]:
        """Run shared call policy, optionally applying local mutable gates."""
        args = dict(args or {})
        approval_id = args.pop(APPROVAL_ARG, None)

        decision, cap = self._gate(ctx, tool_name)
        if decision.outcome != "allowed":
            return decision, args
        if ctx.trusted:
            # Trusted local workspace: current behavior, including explicit
            # db_path arguments, is preserved.
            return decision, args

        fingerprint = args_fingerprint(args)
        # Identity-shaped names are stripped so a client can never smuggle
        # identity — EXCEPT where a tool legitimately declares one as a
        # business parameter (e.g. verify_license's `role`, set_buyer_profile's
        # `profile`). Storage-path args are always stripped in cloud mode.
        preserved = cap.preserve_params if cap is not None else ()
        sanitized = {
            key: value
            for key, value in args.items()
            if not (
                (key in RESERVED_IDENTITY_ARGS and key not in preserved)
                or key in STORAGE_ARGS
            )
        }

        if ctx.profile in TERRITORY_LIMITED and cap is not None:
            for param in cap.property_reference_params:
                raw_reference = sanitized.get(param)
                if type(raw_reference) is not str or not raw_reference.strip():
                    return _denied(
                        "access denied: a property reference is required"
                    ), sanitized
                # The production tool treats every Unicode decimal as an
                # address signal. Reject confusable decimal/format characters
                # before choosing the direct-address versus opaque-ID branch
                # so the authorization classifier cannot disagree with it.
                if (
                    _contains_non_ascii_decimal(raw_reference)
                    or _contains_unicode_format(raw_reference)
                ):
                    return _denied(
                        "access denied: a property request is outside or "
                        "unresolvable for this workspace's territory"
                    ), sanitized
                if _is_direct_property_address(raw_reference):
                    claims = _request_location_claims(raw_reference)
                    if (
                        claims is None
                        or not any(claims)
                        or not _location_claims_intersect_territories(
                            claims,
                            ctx.territories,
                        )
                    ):
                        return _denied(
                            "access denied: a property request is outside or "
                            "unresolvable for this workspace's territory"
                        ), sanitized
            for policy in cap.request_territory_records:
                records = _result_path_values(sanitized, policy.path)
                # A top-level request record is the authorization subject, so
                # omitting it, sending null, or sending an empty collection
                # must fail closed.  Nested collections (for example optional
                # appraisal comps) may legitimately be empty once their
                # required parent record has passed its own policy.
                required_subject = "." not in policy.path
                if records is None or (required_subject and not records):
                    return _denied(
                        "access denied: a property request is outside or unresolvable "
                        "for this workspace's territory"
                    ), sanitized
                for record in records:
                    if (
                        not isinstance(record, Mapping)
                        or not _strict_result_model(
                            policy.model,
                            record,
                            allow_extra_fields=policy.allow_extra_fields,
                        )
                        or not _result_record_within(
                            record,
                            policy,
                            ctx.territories,
                        )
                    ):
                        return _denied(
                            "access denied: a property request is outside or "
                            "unresolvable for this workspace's territory"
                        ), sanitized
            if cap.request_territory_contracts:
                selected_contracts = [
                    contract
                    for contract in cap.request_territory_contracts
                    if all(
                        _request_policy_representation_present(
                            sanitized,
                            policy.path,
                        )
                        for policy in contract.records
                    )
                    and not any(
                        _request_path_key_present(sanitized, path)
                        for path in contract.forbid_present_paths
                    )
                    and _request_contract_is_strictly_typed(
                        sanitized,
                        contract,
                    )
                ]
                if len(selected_contracts) != 1:
                    return _denied(
                        "access denied: a property request is outside or "
                        "unresolvable for this workspace's territory"
                    ), sanitized
                selected_contract = selected_contracts[0]
                if selected_contract.envelope_model is not None:
                    envelope_values = _result_path_values(
                        sanitized,
                        selected_contract.envelope_path or "",
                    )
                    if (
                        envelope_values is None
                        or len(envelope_values) != 1
                        or not isinstance(envelope_values[0], Mapping)
                        or not _strict_result_model(
                            selected_contract.envelope_model,
                            envelope_values[0],
                            allow_extra_fields=(
                                selected_contract.allow_envelope_extra_fields
                            ),
                        )
                    ):
                        return _denied(
                            "access denied: a property request is outside or "
                            "unresolvable for this workspace's territory"
                        ), sanitized
                for policy in selected_contract.records:
                    records = _result_path_values(sanitized, policy.path)
                    required_subject = "." not in policy.path
                    if records is None or (required_subject and not records):
                        return _denied(
                            "access denied: a property request is outside or "
                            "unresolvable for this workspace's territory"
                        ), sanitized
                    for record in records:
                        if (
                            not isinstance(record, Mapping)
                            or not _strict_result_model(
                                policy.model,
                                record,
                                allow_extra_fields=policy.allow_extra_fields,
                            )
                            or not _result_record_within(
                                record,
                                policy,
                                ctx.territories,
                            )
                        ):
                            return _denied(
                                "access denied: a property request is outside or "
                                "unresolvable for this workspace's territory"
                            ), sanitized
            any_value = False
            has_in_scope_value = False
            for param in cap.territory_params:
                raw = sanitized.get(param)
                # Each item of a list-valued argument is an independent target,
                # so it must resolve inside the territory on its own — an
                # unresolvable list item (e.g. a bare city with no state) is
                # outside by definition and denied even beside an in-scope
                # sibling. A scalar argument that cannot be resolved at all is a
                # non-locating component (e.g. a street line) and is tolerated
                # so long as some other argument establishes the territory.
                is_collection = isinstance(raw, (list, tuple, set))
                territory_values = _territory_values(raw)
                if territory_values is None:
                    return _denied(
                        "access denied: a location collection contains an invalid value"
                    ), sanitized
                for value in territory_values:
                    any_value = True
                    claims = _request_location_claims(value)
                    if claims is None:
                        return _denied(
                            f"access denied: {value!r} is outside this workspace's territory"
                        ), sanitized
                    has_location_claim = any(claims)
                    if has_location_claim and _location_claims_intersect_territories(
                        claims,
                        ctx.territories,
                    ):
                        has_in_scope_value = True
                    elif has_location_claim or is_collection:
                        return _denied(
                            f"access denied: {value!r} is outside this workspace's territory"
                        ), sanitized
            if cap.territory_params and not any_value:
                return _denied(
                    "access denied: a resolvable territory argument is required"
                ), sanitized
            if any_value and not has_in_scope_value:
                return _denied(
                    "access denied: the supplied location could not be resolved to this workspace's territory"
                ), sanitized

        if not enforce_stateful:
            return Decision(outcome="allowed"), sanitized

        if cap is not None and cap.quota:
            limit = ctx.quota_limits.get(cap.quota)
            if limit is not None and self.registry.usage_today(
                ctx.workspace_id, cap.quota
            ) >= limit:
                return _denied(
                    f"access denied: daily quota exceeded for {cap.quota!r}"
                ), sanitized

        is_sensitive = cap is not None and (
            cap.sensitive
            or any(_has_value(sanitized.get(p)) for p in cap.sensitive_params)
        )
        if is_sensitive:
            if approval_id is not None:
                if not self.registry.consume_approval(
                    approval_id, ctx.workspace_id, tool_name, fingerprint
                ):
                    return _denied(
                        "access denied: approval is missing, ungranted, spent, or does not match this call"
                    ), sanitized
            else:
                pending = self.registry.request_approval(
                    ctx.workspace_id, tool_name, fingerprint
                )
                return Decision(
                    outcome="approval_required",
                    reason=f"sensitive transaction action {tool_name!r} requires approval",
                    approval_id=pending,
                ), sanitized

        if cap is not None and cap.quota:
            self.registry.record_usage(ctx.workspace_id, cap.quota)
        return Decision(outcome="allowed"), sanitized

    def check_call(
        self, ctx: TenantContext | None, tool_name: str, args: dict | None
    ) -> tuple[Decision, dict]:
        """Apply complete local execution policy and mutable local gates."""
        return self._check_call(
            ctx,
            tool_name,
            args,
            enforce_stateful=True,
        )

    def check_call_policy(
        self, ctx: TenantContext | None, tool_name: str, args: dict | None
    ) -> tuple[Decision, dict]:
        """Apply hosted-safe policy without local quota or approval mutation."""
        return self._check_call(
            ctx,
            tool_name,
            args,
            enforce_stateful=False,
        )

    def call_admission_requirements(
        self,
        tool_name: str,
        sanitized_args: Mapping[str, object],
    ) -> tuple[str | None, bool]:
        """Return the exact stateful gates for one policy-approved call."""
        cap = self.capabilities.get(tool_name)
        if cap is None:
            return None, False
        requires_approval = cap.sensitive or any(
            _has_value(sanitized_args.get(param))
            for param in cap.sensitive_params
        )
        return cap.quota, requires_approval

    def check_result(
        self,
        ctx: TenantContext | None,
        tool_name: str,
        payloads: tuple[Mapping[str, object], ...] | None,
        request_args: Mapping[str, object] | None,
    ) -> Decision:
        """Enforce an explicitly declared post-result territory contract."""
        decision, cap = self._gate(ctx, tool_name)
        if decision.outcome != "allowed":
            return decision
        if not self.requires_result_territory_check(ctx, tool_name):
            return decision
        if not payloads:
            return _denied(RESULT_TERRITORY_DENIAL)
        if request_args is None or cap is None:
            return _denied(RESULT_TERRITORY_DENIAL)

        reference = payloads[0]
        if any(
            not _same_json_value(reference, representation)
            for representation in payloads[1:]
        ):
            return _denied(RESULT_TERRITORY_DENIAL)

        for payload in payloads:
            matches = tuple(
                contract
                for contract in cap.result_territory_contracts
                if _result_contract_matches(
                    payload,
                    contract,
                    request_args,
                    ctx.territories,
                )
            )
            if len(matches) != 1:
                return _denied(RESULT_TERRITORY_DENIAL)

        return decision
