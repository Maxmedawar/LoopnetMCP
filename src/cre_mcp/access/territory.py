"""Territory matching for territory-limited profiles.

Grants are state codes ("TX"), exact "City, ST" strings, or exact 5-digit
ZIPs. Location arguments arrive as any of those three forms. Unresolvable
locations are treated as outside territory (restrictive default).

ZIP ownership and primary postal names come from a checked-in, versioned
GeoNames subset. A Census 2020 ZCTA-to-place relationship supplement covers
real municipalities and Census places that share a ZIP with a different
primary postal name. Broad three-digit prefix inference is forbidden: an
unassigned ZIP or a ZIP belonging to a different postal jurisdiction fails
closed.
"""

import gzip
import hashlib
import re
import unicodedata
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

from cre_mcp.geo.constants import STATE_FIPS

_STATES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
        "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
        "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
        "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
        "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
        "WY", "PR",
    }
)

_POSTAL_DATA_PATH = Path(__file__).with_name("data") / "geonames-us-pr-postal.tsv.gz"
_POSTAL_DATA_SHA256 = "2b36c86ce1c0fd53418d4d6018058272153d1b7ea01eeb60c2ed1b751fbcdddd"
_CENSUS_PLACE_DATA_PATH = (
    Path(__file__).with_name("data") / "census-2020-zcta-place.tsv.gz"
)
_CENSUS_PLACE_DATA_SHA256 = (
    "8a0d94a3743873cf2b9761c3aa79fa7884703903611f6f9163b758ddb0822476"
)
_NATIONAL_LOCATION_DATA_PATH = (
    Path(__file__).with_name("data") / "census-national-location-authority.tsv.gz"
)
_NATIONAL_LOCATION_DATA_SHA256 = (
    "ec28297f8f5bd29328c1cd696a7d007c3d80f083def465de3e6b017393e6b6e8"
)
_NON_PLACE_CITY_COUNTIES = MappingProxyType(
    {("DC", "WASHINGTON"): frozenset({"11001"})}
)
_NON_PLACE_CITY_IDENTITIES = frozenset(_NON_PLACE_CITY_COUNTIES)

_STATE_NAMES: dict[str, str] = {
    "AL": "ALABAMA",
    "AK": "ALASKA",
    "AZ": "ARIZONA",
    "AR": "ARKANSAS",
    "CA": "CALIFORNIA",
    "CO": "COLORADO",
    "CT": "CONNECTICUT",
    "DE": "DELAWARE",
    "DC": "DISTRICT OF COLUMBIA",
    "FL": "FLORIDA",
    "GA": "GEORGIA",
    "HI": "HAWAII",
    "ID": "IDAHO",
    "IL": "ILLINOIS",
    "IN": "INDIANA",
    "IA": "IOWA",
    "KS": "KANSAS",
    "KY": "KENTUCKY",
    "LA": "LOUISIANA",
    "ME": "MAINE",
    "MD": "MARYLAND",
    "MA": "MASSACHUSETTS",
    "MI": "MICHIGAN",
    "MN": "MINNESOTA",
    "MS": "MISSISSIPPI",
    "MO": "MISSOURI",
    "MT": "MONTANA",
    "NE": "NEBRASKA",
    "NV": "NEVADA",
    "NH": "NEW HAMPSHIRE",
    "NJ": "NEW JERSEY",
    "NM": "NEW MEXICO",
    "NY": "NEW YORK",
    "NC": "NORTH CAROLINA",
    "ND": "NORTH DAKOTA",
    "OH": "OHIO",
    "OK": "OKLAHOMA",
    "OR": "OREGON",
    "PA": "PENNSYLVANIA",
    "RI": "RHODE ISLAND",
    "SC": "SOUTH CAROLINA",
    "SD": "SOUTH DAKOTA",
    "TN": "TENNESSEE",
    "TX": "TEXAS",
    "UT": "UTAH",
    "VT": "VERMONT",
    "VA": "VIRGINIA",
    "WA": "WASHINGTON",
    "WV": "WEST VIRGINIA",
    "WI": "WISCONSIN",
    "WY": "WYOMING",
    "PR": "PUERTO RICO",
}
STATE_ALIASES: dict[str, str] = {
    **{code: code for code in _STATES},
    **{name: code for code, name in _STATE_NAMES.items()},
}

_ZIP_RE = re.compile(r"^[0-9]{5}(?:-[0-9]{4})?$")
_COUNTRY_SUFFIX_RE = re.compile(
    r"(?:\s*,?\s+)(?:U\.?S\.?(?:A\.?)?|UNITED\s+STATES(?:\s+OF\s+AMERICA)?)\.?$",
    re.IGNORECASE,
)
_DOTTED_DC_RE = re.compile(r"\bD\.\s*C\.?(?=\s|,|$)", re.IGNORECASE)
_STATE_ALIAS_PATTERN = "|".join(
    re.escape(alias)
    for alias in sorted(STATE_ALIASES, key=len, reverse=True)
)
_CITY_STATE_RE = re.compile(
    rf"^(?P<city>.+?)(?:\s*,\s*|\s+)(?P<state>{_STATE_ALIAS_PATTERN})"
    r"(?:(?:\s*,?\s+|\s*:\s*|\s+(?:ZIP(?:\s*CODE)?|ZIPCODE|"
    r"POSTAL\s+CODE)\s*[:#]?\s*)(?P<zip>[0-9]{5}(?:-[0-9]{4})?))?$",
    re.IGNORECASE,
)

_PERMIT_ADDRESS_FIELDS = (
    "address",
    "site_address",
    "project_address",
    "property_address",
    "location_address",
    "full_address",
    "street_address",
)
_PERMIT_CITY_FIELDS = ("city", "city_name", "municipality")
_PERMIT_STATE_FIELDS = ("state", "state_code", "state_abbr")
_PERMIT_ZIP_FIELDS = ("zip_code", "zip", "zipcode", "postal_code")
_PERMIT_STREET_NUMBER_FIELDS = (
    "street_number",
    "address_number",
    "house_number",
)
_PERMIT_STREET_DIRECTION_FIELDS = (
    "street_direction",
    "pre_direction",
    "direction",
)
_PERMIT_STREET_NAME_FIELDS = ("street_name", "street")
_PERMIT_STREET_SUFFIX_FIELDS = ("suffix", "street_suffix", "street_type")
_PERMIT_SAFE_FIELDS = (
    "permit_number",
    "permit_no",
    "permit_id",
    "permit_",
    "record_number",
    "record_id",
    "id",
    "issued_date",
    "issue_date",
    "issueddate",
    "issuance_date",
    "permit_date",
    "filing_date",
    "filed_date",
    "application_date",
    "application_start_date",
    "applied_date",
    "created_date",
    "created_at",
    "date",
    "type",
    "permit_type",
    "work_type",
    "desc",
    "description",
    "work_description",
    "permit_status",
)
_UNKNOWN_PERMIT_LOCATION_VALUES = frozenset(
    {"-", "--", "N/A", "NA", "NONE", "NULL", "TBD", "UNKNOWN", "UNAVAILABLE"}
)


def _unsafe_location_characters(value: str) -> bool:
    return any(
        (character.isdecimal() and character not in "0123456789")
        or unicodedata.category(character) == "Cf"
        for character in value
    )


def canonicalize_location_text(value: str) -> str:
    """Normalize compatibility characters and all runs of whitespace.

    NFKC turns fullwidth ASCII lookalikes into their ordinary forms. Collapsing
    whitespace makes multiword state names parse identically across spaces,
    tabs, and non-breaking spaces instead of creating an authorization bypass.
    """
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    return _DOTTED_DC_RE.sub("DC", normalized)


def strip_country_suffix(value: str) -> str:
    """Remove one recognized US country suffix without changing locality text."""
    normalized = canonicalize_location_text(value)
    return _COUNTRY_SUFFIX_RE.sub("", normalized).strip(" ,")


def normalize_state(value: str) -> str | None:
    """Normalize an exact state code or full state name to its USPS code."""
    if type(value) is not str:
        return None
    normalized = " ".join(strip_country_suffix(value).upper().split()).strip(" ,.")
    return STATE_ALIASES.get(normalized)


def normalize_zip(value: str) -> str | None:
    """Normalize an exact ZIP or ZIP+4, optionally followed by a US suffix."""
    if type(value) is not str:
        return None
    normalized = strip_country_suffix(value)
    return normalized[:5] if _ZIP_RE.fullmatch(normalized) else None


def normalize_city(value: str) -> str | None:
    """Return a narrow, accent- and punctuation-stable city comparison key."""
    if type(value) is not str:
        return None
    normalized = unicodedata.normalize("NFKD", canonicalize_location_text(value))
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    ).upper()
    normalized = re.sub(r"['’.-]", " ", normalized)
    normalized = " ".join(normalized.strip(" ,").split())
    for short, long in (("ST", "SAINT"), ("FT", "FORT"), ("MT", "MOUNT")):
        prefix = f"{short} "
        if normalized.startswith(prefix):
            normalized = f"{long} {normalized[len(prefix):]}"
            break
    if normalized.startswith("MC "):
        normalized = f"MC{normalized[3:]}"
    return normalized or None


def _city_authority_aliases(value: str) -> frozenset[str]:
    """Return narrow spelling aliases used by US postal place names."""
    normalized = normalize_city(value)
    if normalized is None:
        return frozenset()
    aliases = {normalized}
    return frozenset(aliases)


@lru_cache(maxsize=1)
def _postal_authority() -> MappingProxyType:
    """Load and integrity-check exact postal and Census-place authority."""
    compressed = _POSTAL_DATA_PATH.read_bytes()
    if hashlib.sha256(compressed).hexdigest() != _POSTAL_DATA_SHA256:
        raise ValueError("postal authority integrity check failed")
    decoded = gzip.decompress(compressed).decode("utf-8")
    mutable: dict[str, tuple[str, set[str]]] = {}
    for line in decoded.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            raise ValueError("malformed postal authority row")
        zip5, state, city = parts
        if _ZIP_RE.fullmatch(zip5) is None or state not in _STATES:
            raise ValueError("invalid postal authority row")
        city_aliases = set(_city_authority_aliases(city))
        if not city_aliases:
            raise ValueError("postal authority city is empty")
        existing = mutable.get(zip5)
        if existing is None:
            mutable[zip5] = (state, city_aliases)
        elif existing[0] != state:
            raise ValueError("postal authority ZIP has conflicting states")
        else:
            existing[1].update(city_aliases)

    census_compressed = _CENSUS_PLACE_DATA_PATH.read_bytes()
    if (
        hashlib.sha256(census_compressed).hexdigest()
        != _CENSUS_PLACE_DATA_SHA256
    ):
        raise ValueError("Census place authority integrity check failed")
    census_decoded = gzip.decompress(census_compressed).decode("utf-8")
    for line in census_decoded.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            raise ValueError("malformed Census place authority row")
        zip5, state, city, place_geoid = parts
        if (
            _ZIP_RE.fullmatch(zip5) is None
            or state not in _STATES
            or re.fullmatch(r"[0-9]{7}", place_geoid) is None
            or STATE_FIPS.get(state) != place_geoid[:2]
        ):
            raise ValueError("invalid Census place authority row")
        city_aliases = set(_city_authority_aliases(city))
        if not city_aliases:
            raise ValueError("Census place authority city is empty")
        existing = mutable.get(zip5)
        if existing is None or existing[0] != state:
            raise ValueError("Census place does not match assigned postal ZIP")
        existing[1].update(city_aliases)
    frozen = {
        zip5: (state, frozenset(cities))
        for zip5, (state, cities) in mutable.items()
    }
    return MappingProxyType(frozen)


def _postal_entry(zip5: str) -> tuple[str, frozenset[str]] | None:
    """Return one exact postal entry, failing closed on data errors."""
    try:
        return _postal_authority().get(zip5)
    except (OSError, EOFError, UnicodeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _census_zip_place_geoids() -> Mapping[tuple[str, str, str], frozenset[str]]:
    """Load exact normalized city, ZIP, and Census place GEOID relations."""

    compressed = _CENSUS_PLACE_DATA_PATH.read_bytes()
    if hashlib.sha256(compressed).hexdigest() != _CENSUS_PLACE_DATA_SHA256:
        raise ValueError("Census place authority integrity check failed")
    decoded = gzip.decompress(compressed).decode("utf-8")
    mutable: dict[tuple[str, str, str], set[str]] = {}
    for line in decoded.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            raise ValueError("malformed Census place authority row")
        zip5, state, city, place_geoid = parts
        city_key = normalize_city(city)
        if (
            re.fullmatch(r"[0-9]{5}", zip5) is None
            or state not in _STATES
            or city_key is None
            or re.fullmatch(r"[0-9]{7}", place_geoid) is None
            or STATE_FIPS.get(state) != place_geoid[:2]
        ):
            raise ValueError("invalid Census place authority row")
        postal = _postal_entry(zip5)
        if postal is None or postal[0] != state:
            raise ValueError("Census place does not match assigned postal ZIP")
        mutable.setdefault((state, city_key, zip5), set()).add(place_geoid)
    return MappingProxyType(
        {key: frozenset(values) for key, values in mutable.items()}
    )


def city_zip_pair_is_authoritative(city_state: str, zip_value: str) -> bool:
    """Whether one normalized postal/Census place and assigned ZIP agree."""
    if type(city_state) is not str or type(zip_value) is not str:
        return False
    try:
        city_value, state_value = city_state.rsplit(",", 1)
    except ValueError:
        return False
    city = normalize_city(city_value)
    state = normalize_state(state_value)
    zip5 = normalize_zip(zip_value)
    if city is None or state is None or zip5 is None:
        return False
    entry = _postal_entry(zip5)
    if entry is None or entry[0] != state:
        return False
    return bool(_city_authority_aliases(city) & entry[1])


@lru_cache(maxsize=4096)
def city_state_is_authoritative(city_state: str) -> bool:
    """Whether an exact normalized postal city exists in the claimed state."""
    if type(city_state) is not str:
        return False
    try:
        city_value, state_value = city_state.rsplit(",", 1)
    except ValueError:
        return False
    city_aliases = _city_authority_aliases(city_value)
    state = normalize_state(state_value)
    if not city_aliases or state is None:
        return False
    try:
        return any(
            entry_state == state and bool(city_aliases & cities)
            for entry_state, cities in _postal_authority().values()
        )
    except (OSError, EOFError, UnicodeError, ValueError):
        return False


@lru_cache(maxsize=1)
def _national_location_authority() -> tuple[
    Mapping[str, tuple[str, str]],
    Mapping[tuple[str, str], frozenset[str]],
    Mapping[tuple[str, str], frozenset[str]],
    Mapping[str, frozenset[str]],
    Mapping[str, frozenset[str]],
    Mapping[str, tuple[str, str]],
    Mapping[str, frozenset[str]],
    Mapping[str, frozenset[str]],
]:
    """Load integrity-checked national place, county, ZIP, tract, and CBSA data."""

    compressed = _NATIONAL_LOCATION_DATA_PATH.read_bytes()
    if hashlib.sha256(compressed).hexdigest() != _NATIONAL_LOCATION_DATA_SHA256:
        raise ValueError("national location authority integrity check failed")
    decoded = gzip.decompress(compressed).decode("utf-8")

    counties: dict[str, tuple[str, str]] = {}
    county_names: dict[tuple[str, str], set[str]] = {}
    city_places: dict[tuple[str, str], set[str]] = {}
    place_names: dict[str, tuple[str, str]] = {}
    place_counties: dict[str, set[str]] = {}
    zip_counties: dict[str, set[str]] = {}
    tract_counties: dict[str, tuple[str, str]] = {}
    tract_zips: dict[str, set[str]] = {}
    county_cbsas: dict[str, set[str]] = {}

    for line in decoded.splitlines():
        parts = line.split("|")
        if not parts:
            raise ValueError("malformed national location authority row")
        kind = parts[0]
        if kind == "C":
            if len(parts) != 4:
                raise ValueError("malformed national county authority row")
            _kind, first, second, third = parts
            fips, state, county = first, second, third
            if (
                re.fullmatch(r"[0-9]{5}", fips) is None
                or state not in _STATES
                or STATE_FIPS.get(state) != fips[:2]
                or not county
            ):
                raise ValueError("invalid national county authority row")
            identity = (state, county)
            prior = counties.setdefault(fips, identity)
            if prior != identity:
                raise ValueError("national county FIPS has conflicting identities")
        elif kind == "P":
            if len(parts) != 5:
                raise ValueError("malformed national place authority row")
            _kind, state, city, place_geoid, fips = parts
            city_key = normalize_city(city)
            if (
                state not in _STATES
                or city_key is None
                or re.fullmatch(r"[0-9]{7}", place_geoid) is None
                or STATE_FIPS.get(state) != place_geoid[:2]
                or re.fullmatch(r"[0-9]{5}", fips) is None
            ):
                raise ValueError("invalid national place authority row")
            place_name = (state, city_key)
            prior_name = place_names.setdefault(place_geoid, place_name)
            if prior_name != place_name:
                raise ValueError("national place GEOID has conflicting names")
            city_places.setdefault(place_name, set()).add(place_geoid)
            place_counties.setdefault(place_geoid, set()).add(fips)
        elif kind == "Z":
            if len(parts) != 4:
                raise ValueError("malformed national ZIP authority row")
            _kind, first, second, third = parts
            zip5, state, fips = first, second, third
            if (
                re.fullmatch(r"[0-9]{5}", zip5) is None
                or state not in _STATES
                or re.fullmatch(r"[0-9]{5}", fips) is None
            ):
                raise ValueError("invalid national ZIP authority row")
            zip_counties.setdefault(zip5, set()).add(fips)
        elif kind == "T":
            if len(parts) != 5:
                raise ValueError("malformed national tract authority row")
            _kind, tract, state, fips, zip5 = parts
            if (
                re.fullmatch(r"[0-9]{11}", tract) is None
                or state not in _STATES
                or STATE_FIPS.get(state) != tract[:2]
                or re.fullmatch(r"[0-9]{5}", fips) is None
                or not tract.startswith(fips)
                or (zip5 and re.fullmatch(r"[0-9]{5}", zip5) is None)
            ):
                raise ValueError("invalid national tract authority row")
            identity = (state, fips)
            prior_identity = tract_counties.setdefault(tract, identity)
            if prior_identity != identity:
                raise ValueError("national tract GEOID has conflicting counties")
            tract_zips.setdefault(tract, set())
            if zip5:
                tract_zips[tract].add(zip5)
        elif kind == "B":
            if len(parts) != 4:
                raise ValueError("malformed national CBSA authority row")
            _kind, first, second, third = parts
            fips, cbsa, empty = first, second, third
            if (
                empty
                or re.fullmatch(r"[0-9]{5}", fips) is None
                or re.fullmatch(r"[0-9]{5}", cbsa) is None
            ):
                raise ValueError("invalid national CBSA authority row")
            county_cbsas.setdefault(fips, set()).add(cbsa)
        else:
            raise ValueError("unknown national location authority row type")

    if (
        not counties
        or not city_places
        or not place_counties
        or not zip_counties
        or not tract_counties
        or not county_cbsas
    ):
        raise ValueError("national location authority is incomplete")

    for fips, (state, county) in counties.items():
        county_key = normalize_city(county)
        if county_key is None:
            raise ValueError("national county authority name is empty")
        county_names.setdefault((state, county_key), set()).add(fips)

    for place_geoid, fips_values in place_counties.items():
        state = place_names[place_geoid][0]
        if any(counties.get(fips, (None,))[0] != state for fips in fips_values):
            raise ValueError("national place authority crosses county state")
    for zip5, fips_values in zip_counties.items():
        postal = _postal_entry(zip5)
        if postal is None:
            raise ValueError("national ZIP authority creates a postal assignment")
        state = postal[0]
        if any(counties.get(fips, (None,))[0] != state for fips in fips_values):
            raise ValueError("national ZIP authority crosses county state")
    for tract, (state, fips) in tract_counties.items():
        if counties.get(fips, (None,))[0] != state:
            raise ValueError("national tract authority crosses county state")
        for zip5 in tract_zips[tract]:
            postal = _postal_entry(zip5)
            if postal is None or postal[0] != state:
                raise ValueError("national tract authority crosses ZIP state")
    for fips, cbsa_values in county_cbsas.items():
        if fips not in counties or len(cbsa_values) != 1:
            raise ValueError("national CBSA authority has an ambiguous county")

    return (
        MappingProxyType(counties),
        MappingProxyType(
            {key: frozenset(values) for key, values in county_names.items()}
        ),
        MappingProxyType(
            {key: frozenset(values) for key, values in city_places.items()}
        ),
        MappingProxyType(
            {key: frozenset(values) for key, values in place_counties.items()}
        ),
        MappingProxyType(
            {key: frozenset(values) for key, values in zip_counties.items()}
        ),
        MappingProxyType(tract_counties),
        MappingProxyType(
            {key: frozenset(values) for key, values in tract_zips.items()}
        ),
        MappingProxyType(
            {key: frozenset(values) for key, values in county_cbsas.items()}
        ),
    )


def county_identity_for_fips(county_fips: str) -> tuple[str, str] | None:
    """Return ``(state, canonical county name)`` for one exact FIPS."""

    if type(county_fips) is not str or re.fullmatch(r"[0-9]{5}", county_fips) is None:
        return None
    try:
        return _national_location_authority()[0].get(county_fips)
    except (OSError, EOFError, UnicodeError, ValueError):
        return None


def county_fips_for_name(county: str, state: str) -> frozenset[str]:
    """Return every authoritative FIPS for an exact county-equivalent name."""

    if type(county) is not str or type(state) is not str:
        return frozenset()
    county_key = normalize_city(county)
    state_code = normalize_state(state)
    if county_key is None or state_code is None:
        return frozenset()
    try:
        return _national_location_authority()[1].get(
            (state_code, county_key),
            frozenset(),
        )
    except (OSError, EOFError, UnicodeError, ValueError):
        return frozenset()


def city_county_fips(city: str, state: str) -> frozenset[str]:
    """Return all counties authoritatively intersecting an exact Census place."""

    if type(city) is not str or type(state) is not str:
        return frozenset()
    city_key = normalize_city(city)
    state_code = normalize_state(state)
    if city_key is None or state_code is None:
        return frozenset()
    try:
        authority = _national_location_authority()
        place_geoids = authority[2].get(
            (state_code, city_key),
            frozenset(),
        )
        return frozenset(
            county_fips
            for place_geoid in place_geoids
            for county_fips in authority[3].get(place_geoid, frozenset())
        )
    except (OSError, EOFError, UnicodeError, ValueError):
        return frozenset()


def non_place_city_county_fips(city: str, state: str) -> frozenset[str]:
    """Return counties for an explicit non-Census-place city jurisdiction."""

    if type(city) is not str or type(state) is not str:
        return frozenset()
    city_key = normalize_city(city)
    state_code = normalize_state(state)
    if city_key is None or state_code is None:
        return frozenset()
    return _NON_PLACE_CITY_COUNTIES.get((state_code, city_key), frozenset())


def city_place_geoids(
    city: str,
    state: str,
    *,
    county_fips: str | None = None,
    zip_value: str | None = None,
) -> frozenset[str]:
    """Resolve one city claim to every surviving Census place GEOID.

    County and ZIP carriers are intersections, never substitutions.  The
    caller decides whether the remaining set is sufficiently narrow; a city
    identity is unambiguous only when exactly one GEOID survives.
    """

    if type(city) is not str or type(state) is not str:
        return frozenset()
    city_key = normalize_city(city)
    state_code = normalize_state(state)
    if city_key is None or state_code is None:
        return frozenset()
    if county_fips is not None and (
        type(county_fips) is not str
        or re.fullmatch(r"[0-9]{5}", county_fips) is None
    ):
        return frozenset()
    zip5: str | None = None
    if zip_value is not None:
        if type(zip_value) is not str:
            return frozenset()
        zip5 = normalize_zip(zip_value)
        if zip5 is None:
            return frozenset()
    try:
        authority = _national_location_authority()
        candidates = set(
            authority[2].get((state_code, city_key), frozenset())
        )
        if county_fips is not None:
            candidates = {
                place_geoid
                for place_geoid in candidates
                if county_fips in authority[3].get(place_geoid, frozenset())
            }
        if zip5 is not None:
            zip_places = _census_zip_place_geoids().get(
                (state_code, city_key, zip5),
                frozenset(),
            )
            if zip_places:
                candidates.intersection_update(zip_places)
            elif not (
                len(candidates) == 1
                and city_zip_pair_is_authoritative(
                    f"{city_key}, {state_code}",
                    zip5,
                )
            ):
                candidates.clear()
        return frozenset(candidates)
    except (OSError, EOFError, UnicodeError, ValueError):
        return frozenset()


def city_claim_is_unambiguous(
    city: str,
    state: str,
    *,
    county_fips: str | None = None,
    zip_value: str | None = None,
) -> bool:
    """Return whether all supplied city carriers converge on one place."""

    candidates = city_place_geoids(
        city,
        state,
        county_fips=county_fips,
        zip_value=zip_value,
    )
    if len(candidates) == 1:
        return True
    # Some assigned postal localities, including New York City borough labels
    # and PO-box ZIPs, are not Census places or ZCTAs.  They remain exact when
    # an assigned ZIP independently proves the city/state pair.  This fallback
    # is forbidden whenever same-name Census place candidates exist, because a
    # postal label may not collapse multiple governmental identities.
    state_code = normalize_state(state)
    city_key = normalize_city(city)
    if (
        zip_value is None
        and state_code is not None
        and city_key is not None
        and (state_code, city_key) in _NON_PLACE_CITY_IDENTITIES
    ):
        counties = non_place_city_county_fips(city_key, state_code)
        return bool(
            counties
            and (county_fips is None or county_fips in counties)
            and city_state_is_authoritative(f"{city_key}, {state_code}")
        )
    if zip_value is None or city_place_geoids(city, state):
        return False
    zip5 = normalize_zip(zip_value) if type(zip_value) is str else None
    if zip5 is None or state_code is None or city_key is None:
        return False
    if not city_zip_pair_is_authoritative(f"{city_key}, {state_code}", zip5):
        return False
    if county_fips is not None and county_fips not in zip_county_fips(zip5):
        return False
    return True


def zip_county_fips(zip_value: str) -> frozenset[str]:
    """Return all counties with a positive land intersection for one ZCTA."""

    zip5 = normalize_zip(zip_value) if type(zip_value) is str else None
    if zip5 is None:
        return frozenset()
    try:
        return _national_location_authority()[4].get(zip5, frozenset())
    except (OSError, EOFError, UnicodeError, ValueError):
        return frozenset()


def tract_identity_for_geoid(tract: str) -> tuple[str, str] | None:
    """Return ``(state, county_fips)`` for an exact 2020 Census tract."""

    if type(tract) is not str or re.fullmatch(r"[0-9]{11}", tract) is None:
        return None
    try:
        return _national_location_authority()[5].get(tract)
    except (OSError, EOFError, UnicodeError, ValueError):
        return None


def tract_zip_codes(tract: str) -> frozenset[str]:
    """Return positive-land-intersection ZCTAs for one exact Census tract."""

    if type(tract) is not str or re.fullmatch(r"[0-9]{11}", tract) is None:
        return frozenset()
    try:
        return _national_location_authority()[6].get(tract, frozenset())
    except (OSError, EOFError, UnicodeError, ValueError):
        return frozenset()


def county_cbsa_codes(county_fips: str) -> frozenset[str]:
    """Return the authoritative July 2023 CBSA for one county, when assigned."""

    if type(county_fips) is not str or re.fullmatch(r"[0-9]{5}", county_fips) is None:
        return frozenset()
    try:
        return _national_location_authority()[7].get(county_fips, frozenset())
    except (OSError, EOFError, UnicodeError, ValueError):
        return frozenset()


def location_parts(
    value: str,
) -> tuple[str, str | None, str | None] | None:
    """Parse one exact state, city/state, or ZIP claim.

    The result is ``(state, normalized_city_or_none, zip5_or_none)``.  Bare
    cities and address-looking prefixes are rejected instead of guessed.
    """
    if type(value) is not str:
        return None
    text = strip_country_suffix(value)
    if not text:
        return None
    if (zip5 := normalize_zip(text)) is not None:
        state = _state_for_zip(zip5)
        return (state, None, zip5) if state is not None else None
    if (state := normalize_state(text)) is not None:
        return state, None, None
    match = _CITY_STATE_RE.fullmatch(text)
    if match is None:
        return None
    city_text = match.group("city").strip(" ,")
    if not city_text:
        return None
    state = normalize_state(match.group("state"))
    city = normalize_city(city_text)
    zip_value = match.group("zip")
    zip5 = normalize_zip(zip_value) if zip_value is not None else None
    if state is None or city is None:
        return None
    # Some real Census places contain digits. Permit one only when the exact
    # city/state pair is present in the integrity-checked authority; arbitrary
    # numbered street text must remain unresolvable.
    if re.search(r"[0-9]", city_text) and not city_state_is_authoritative(
        f"{city}, {state}"
    ):
        return None
    if zip5 is not None and _state_for_zip(zip5) != state:
        return None
    return state, city, zip5


def _permit_key_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _permit_row(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Flatten and canonicalize the exact keys recognized by permit parsers."""

    flattened_items = [
        (key, value)
        for key, value in record.items()
        if key != "attributes"
    ]
    attributes = record.get("attributes")
    if isinstance(attributes, Mapping):
        flattened_items.extend(attributes.items())
    recognized = (
        *_PERMIT_ADDRESS_FIELDS,
        *_PERMIT_CITY_FIELDS,
        *_PERMIT_STATE_FIELDS,
        *_PERMIT_ZIP_FIELDS,
        *_PERMIT_STREET_NUMBER_FIELDS,
        *_PERMIT_STREET_DIRECTION_FIELDS,
        *_PERMIT_STREET_NAME_FIELDS,
        *_PERMIT_STREET_SUFFIX_FIELDS,
        *_PERMIT_SAFE_FIELDS,
    )
    actual_by_token: dict[str, list[tuple[object, Any]]] = {}
    for key, value in flattened_items:
        actual_by_token.setdefault(_permit_key_token(key), []).append(
            (key, value)
        )
    canonical: dict[str, Any] = {}
    for field in recognized:
        actual = actual_by_token.get(_permit_key_token(field), [])
        if len(actual) > 1:
            # The production parsers collapse key spelling before selection;
            # duplicate spellings are ambiguous and must not choose a hidden
            # later value.
            return None
        if actual:
            canonical[field] = actual[0][1]
    return canonical


def _permit_text_values(
    record: Mapping[str, Any],
    fields: tuple[str, ...],
    *,
    optional_null: bool = False,
) -> tuple[bool, list[str]]:
    values: list[str] = []
    for field in fields:
        if field not in record:
            continue
        raw = record[field]
        if raw is None and optional_null:
            continue
        if type(raw) is not str:
            return False, []
        if _unsafe_location_characters(raw):
            return False, []
        value = canonicalize_location_text(raw).strip(" ,")
        if not value or value.upper().strip(" .") in _UNKNOWN_PERMIT_LOCATION_VALUES:
            return False, []
        values.append(value)
    return True, values


def _one_permit_text(
    record: Mapping[str, Any],
    fields: tuple[str, ...],
    normalizer,
    *,
    required: bool,
    optional_null: bool = False,
) -> tuple[bool, str | None]:
    ok, values = _permit_text_values(
        record,
        fields,
        optional_null=optional_null,
    )
    if not ok or (required and not values):
        return False, None
    if not values:
        return True, None
    normalized = [normalizer(value) for value in values]
    if any(value is None for value in normalized) or len(set(normalized)) != 1:
        return False, None
    return True, normalized[0]


def canonical_property_from_full_address(
    value: str,
) -> dict[str, str | None] | None:
    """Split one comma-delimited US street address into a canonical identity."""

    if type(value) is not str:
        return None
    if _unsafe_location_characters(value):
        return None
    normalized = canonicalize_location_text(value).strip(" ,")
    if not normalized:
        return None
    comma_positions = [index for index, character in enumerate(normalized) if character == ","]
    for position in comma_positions:
        street = normalized[:position].strip(" ,")
        locality = normalized[position + 1 :].strip(" ,")
        parts = location_parts(locality)
        if not street or parts is None or parts[1] is None:
            continue
        state, city, zip5 = parts
        return {
            "address": normalized,
            "city": city,
            "state": state,
            "zip_code": zip5,
        }
    return None


def canonical_permit_property(
    record: Mapping[str, Any],
    *,
    fallback_location: str | None = None,
) -> dict[str, str | None] | None:
    """Return one exact canonical property identity from a supported permit row.

    Provider records may use address aliases, split street columns, or an
    ArcGIS ``attributes`` wrapper.  A first-party ``permits_near`` envelope may
    supply the city/state for otherwise street-only rows.  Conflicting aliases,
    partial split addresses, ambiguous fallback locations, and missing required
    fields all fail closed.
    """

    if not isinstance(record, Mapping):
        return None
    row = _permit_row(record)
    if row is None:
        return None

    ok, addresses = _permit_text_values(row, _PERMIT_ADDRESS_FIELDS)
    if not ok:
        return None
    normalized_addresses = {
        canonicalize_location_text(value).casefold() for value in addresses
    }
    if len(normalized_addresses) > 1:
        return None
    address = addresses[0] if addresses else None

    split_fields = (
        *_PERMIT_STREET_NUMBER_FIELDS,
        *_PERMIT_STREET_DIRECTION_FIELDS,
        *_PERMIT_STREET_NAME_FIELDS,
        *_PERMIT_STREET_SUFFIX_FIELDS,
    )
    has_split_value = any(field in row and row[field] is not None for field in split_fields)
    if has_split_value:
        number_values: list[str] = []
        for field in _PERMIT_STREET_NUMBER_FIELDS:
            if field not in row:
                continue
            raw = row[field]
            if type(raw) not in (str, int) or isinstance(raw, bool):
                return None
            if type(raw) is str and _unsafe_location_characters(raw):
                return None
            value = canonicalize_location_text(str(raw)).strip()
            if not value:
                return None
            number_values.append(value)
        if not number_values or len({value.casefold() for value in number_values}) != 1:
            return None
        ok, street_names = _permit_text_values(row, _PERMIT_STREET_NAME_FIELDS)
        if not ok or not street_names or len({value.casefold() for value in street_names}) != 1:
            return None
        ok, directions = _permit_text_values(
            row,
            _PERMIT_STREET_DIRECTION_FIELDS,
            optional_null=True,
        )
        if not ok or len({value.casefold() for value in directions}) > 1:
            return None
        ok, suffixes = _permit_text_values(
            row,
            _PERMIT_STREET_SUFFIX_FIELDS,
            optional_null=True,
        )
        if not ok or len({value.casefold() for value in suffixes}) > 1:
            return None
        split_address = " ".join(
            part
            for part in (
                number_values[0],
                directions[0] if directions else None,
                street_names[0],
                suffixes[0] if suffixes else None,
            )
            if part
        )
        if address is not None and canonicalize_location_text(address).casefold() != canonicalize_location_text(split_address).casefold():
            return None
        address = split_address
    if address is None:
        return None

    address_identity = canonical_property_from_full_address(address)

    ok, raw_cities = _permit_text_values(row, _PERMIT_CITY_FIELDS)
    if not ok:
        return None
    city_values: list[str] = []
    embedded_states: list[str] = []
    embedded_zips: list[str] = []
    for raw_city in raw_cities:
        parts = location_parts(raw_city)
        if parts is not None:
            embedded_state, embedded_city, embedded_zip = parts
            if embedded_city is None:
                return None
            city_values.append(embedded_city)
            embedded_states.append(embedded_state)
            if embedded_zip is not None:
                embedded_zips.append(embedded_zip)
        else:
            city = normalize_city(raw_city)
            if city is None or any(character.isdecimal() for character in raw_city):
                return None
            city_values.append(city)
    if len(set(city_values)) > 1:
        return None

    ok, state = _one_permit_text(
        row,
        _PERMIT_STATE_FIELDS,
        normalize_state,
        required=False,
    )
    if not ok:
        return None
    ok, zip5 = _one_permit_text(
        row,
        _PERMIT_ZIP_FIELDS,
        normalize_zip,
        required=False,
        optional_null=True,
    )
    if not ok:
        return None

    if fallback_location is not None and _unsafe_location_characters(fallback_location):
        return None
    fallback_parts = location_parts(fallback_location) if fallback_location is not None else None
    if fallback_location is not None and (
        fallback_parts is None or fallback_parts[1] is None
    ):
        return None
    fallback_state = fallback_parts[0] if fallback_parts is not None else None
    fallback_city = fallback_parts[1] if fallback_parts is not None else None
    fallback_zip = fallback_parts[2] if fallback_parts is not None else None

    address_state = address_identity["state"] if address_identity is not None else None
    address_city = address_identity["city"] if address_identity is not None else None
    address_zip = address_identity["zip_code"] if address_identity is not None else None
    all_states = [
        value
        for value in (state, *embedded_states, fallback_state, address_state)
        if value
    ]
    all_cities = [
        value for value in (*city_values, fallback_city, address_city) if value
    ]
    all_zips = [
        value for value in (zip5, *embedded_zips, fallback_zip, address_zip) if value
    ]
    if len(set(all_states)) != 1 or len(set(all_cities)) != 1 or len(set(all_zips)) > 1:
        return None

    return {
        "address": canonicalize_location_text(address),
        "city": all_cities[0],
        "state": all_states[0],
        "zip_code": all_zips[0] if all_zips else None,
    }


def project_permit_property(
    record: Mapping[str, Any],
    *,
    fallback_location: str | None = None,
) -> dict[str, Any] | None:
    """Project a provider permit into the closed restricted-result DTO."""

    canonical = canonical_permit_property(
        record,
        fallback_location=fallback_location,
    )
    if canonical is None:
        return None
    row = _permit_row(record)
    if row is None:
        return None
    projected = {
        field: row[field]
        for field in _PERMIT_SAFE_FIELDS
        if field in row
        and type(row[field]) in (str, int, float, bool, type(None))
    }
    projected.update(canonical)
    return projected


def permit_full_address(record: Mapping[str, Any]) -> str | None:
    """Format a projected permit property as one independently scoped address."""

    address = record.get("address")
    city = record.get("city")
    state = record.get("state")
    zip_code = record.get("zip_code")
    if not all(type(value) is str and value.strip() for value in (address, city, state)):
        return None
    street = canonicalize_location_text(address).split(",", 1)[0].strip()
    if not street:
        return None
    tail = f"{city}, {state}"
    if type(zip_code) is str and zip_code.strip():
        tail += f" {zip_code}"
    return f"{street}, {tail}"


def _state_for_zip(zip5: str) -> str | None:
    """Map only an exact assigned ZIP to its supported state or territory."""
    entry = _postal_entry(zip5)
    return entry[0] if entry is not None else None


def location_state(value: str) -> str | None:
    """Return the state for one exact, unambiguous location argument."""
    parts = location_parts(value)
    return parts[0] if parts is not None else None


def location_within(value: str, territories: tuple[str, ...]) -> bool:
    """True when the location falls inside one of the granted territories."""
    if not territories:
        return False
    requested = location_parts(value)
    if requested is None:
        return False
    requested_state, requested_city, requested_zip = requested
    if (
        requested_city is not None
        and not city_state_is_authoritative(
            f"{requested_city}, {requested_state}"
        )
    ):
        return False
    if (
        requested_city is not None
        and requested_zip is not None
        and not city_zip_pair_is_authoritative(
            f"{requested_city}, {requested_state}",
            requested_zip,
        )
    ):
        return False
    if requested_city is not None and not city_claim_is_unambiguous(
        requested_city,
        requested_state,
        zip_value=requested_zip,
    ):
        return False
    for territory in territories:
        granted = location_parts(territory)
        if granted is None:
            continue
        granted_state, granted_city, granted_zip = granted
        if granted_city is not None and not city_claim_is_unambiguous(
            granted_city,
            granted_state,
            zip_value=granted_zip,
        ):
            continue
        if granted_zip is not None:
            if requested_zip != granted_zip:
                continue
            if requested_zip == granted_zip:
                return True
            continue
        if granted_city is not None:
            if (
                requested_city == granted_city
                and requested_state == granted_state
            ):
                return True
            continue
        if requested_state == granted_state:
            return True
    return False
