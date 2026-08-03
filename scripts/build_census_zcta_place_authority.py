#!/usr/bin/env python3
"""Build the deterministic Census place supplement for postal validation.

The input is the Census Bureau's national 2020 ZCTA-to-place relationship
file.  Rows are retained only when a currently assigned GeoNames postal code
and a positive land-area intersection agree on the state.  The generated
``zip|state|place|place_geoid`` rows supplement primary postal place names with
real Census places that share a ZIP while preserving distinct same-name places.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
from pathlib import Path

from cre_mcp.geo.constants import STATE_FIPS

_CENSUS_RELATIONSHIP_SHA256 = (
    "698a5dad71ed419411677d0ffd8ecd9331067f59c472cdd239b92c12f698285d"
)
_PLACE_SUFFIXES = tuple(
    sorted(
        (
            " consolidated government",
            " metropolitan government",
            " unified government",
            " city and borough",
            " metro government",
            " metro township",
            " urban county",
            " municipality",
            " corporation",
            " zona urbana",
            " comunidad",
            " borough",
            " village",
            " town",
            " city",
            " cdp",
        ),
        key=len,
        reverse=True,
    )
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _postal_states(path: Path) -> dict[str, str]:
    states: dict[str, str] = {}
    decoded = gzip.decompress(path.read_bytes()).decode("utf-8")
    for line in decoded.splitlines():
        zip5, state, _city = line.split("|", 2)
        prior = states.setdefault(zip5, state)
        if prior != state:
            raise ValueError(f"postal ZIP {zip5} crosses configured states")
    return states


def _bare_place_name(value: str) -> str:
    place = " ".join(value.split())
    if place.casefold().endswith(" (balance)"):
        place = place[: -len(" (balance)")].rstrip()
    folded = place.casefold()
    for suffix in _PLACE_SUFFIXES:
        if folded.endswith(suffix):
            place = place[: -len(suffix)].rstrip()
            break
    if not place or "|" in place or "\n" in place or "\r" in place:
        raise ValueError(f"invalid Census place name: {value!r}")
    return place


def build(relationship_path: Path, postal_path: Path, output_path: Path) -> None:
    if _sha256(relationship_path) != _CENSUS_RELATIONSHIP_SHA256:
        raise ValueError("unexpected Census relationship source hash")

    postal_states = _postal_states(postal_path)
    state_by_fips = {fips: state for state, fips in STATE_FIPS.items()}
    rows: set[tuple[str, str, str, str]] = set()

    with relationship_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter="|")
        for record in reader:
            zip5 = record["GEOID_ZCTA5_20"]
            place_geoid = record["GEOID_PLACE_20"]
            place_name = record["NAMELSAD_PLACE_20"]
            if not zip5 or not place_geoid or not place_name:
                continue
            if record["FUNCSTAT_PLACE_20"] not in {"A", "S"}:
                continue
            try:
                land_area = int(record["AREALAND_PART"])
            except (TypeError, ValueError):
                raise ValueError("invalid Census relationship land area") from None
            if land_area <= 0:
                continue
            state = state_by_fips.get(place_geoid[:2])
            if state is None or postal_states.get(zip5) != state:
                continue
            if (
                len(place_geoid) != 7
                or not place_geoid.isascii()
                or not place_geoid.isdecimal()
            ):
                raise ValueError(f"invalid Census place GEOID: {place_geoid!r}")
            rows.add((zip5, state, _bare_place_name(place_name), place_geoid))

    payload = "".join(
        f"{zip5}|{state}|{place}|{place_geoid}\n"
        for zip5, state, place, place_geoid in sorted(
            rows,
            key=lambda row: (
                row[0],
                row[1],
                row[2].casefold(),
                row[2],
                row[3],
            ),
        )
    ).encode("utf-8")
    output_path.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
    print(
        f"wrote {len(rows)} rows to {output_path} "
        f"sha256={_sha256(output_path)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relationship", required=True, type=Path)
    parser.add_argument("--postal", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.relationship, args.postal, args.output)


if __name__ == "__main__":
    main()
