# Postal and Census-place authority

`geonames-us-pr-postal.tsv.gz` is a deterministic, derived subset of the
GeoNames Postal Code files. It is used only to validate exact five-digit ZIP,
state, and primary-place combinations at the territory authorization boundary.

- Upstream project: [GeoNames](https://www.geonames.org/)
- Upstream directory and format notice:
  [download.geonames.org/export/zip](https://download.geonames.org/export/zip/)
- Source files retrieved 2026-08-02:
  [US.zip](https://download.geonames.org/export/zip/US.zip) and
  [PR.zip](https://download.geonames.org/export/zip/PR.zip)
- `US.zip` SHA-256:
  `87609ec6bfc28acecf785998340ede7f21bacbcce1a591d9899015bd82999e52`
- `PR.zip` SHA-256:
  `48d53034cfd49ddb733fb02732ff5b9e41563e2a6682774c8b8d9a8f7fb97fd6`
- Derived gzip SHA-256:
  `2b36c86ce1c0fd53418d4d6018058272153d1b7ea01eeb60c2ed1b751fbcdddd`

Transformation: retain only exact five-digit postal codes, the first-order
subdivision code, and primary place name; restrict the US file to the 50
states plus the District of Columbia; map rows from the separate Puerto Rico
file to `PR`; sort unique rows bytewise; and gzip with timestamp zero. Military
postal jurisdictions and other US territories are intentionally excluded so
they cannot be inferred from overlapping three-digit prefixes.

GeoNames distributes these postal-code files under the
[Creative Commons Attribution 4.0 license](https://creativecommons.org/licenses/by/4.0/)
and provides the data as-is without a warranty of accuracy, timeliness, or
completeness. This repository preserves attribution and treats an absent or
unresolvable code as unauthorized for restricted profiles.

## Census 2020 ZCTA-to-place supplement

`census-2020-zcta-place.tsv.gz` supplements the single primary GeoNames place
with incorporated places and Census-designated places that have a positive
land-area intersection with the same 2020 ZCTA. It never creates a ZIP or
changes a ZIP's state: a row is retained only when the ZIP already exists in
the integrity-checked GeoNames authority and both sources agree on the state.

- Upstream agency: [United States Census Bureau](https://www.census.gov/)
- Source relationship file retrieved 2026-08-02:
  [2020 ZCTA-to-place national relationship file](https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_place20_natl.txt)
- Source SHA-256:
  `698a5dad71ed419411677d0ffd8ecd9331067f59c472cdd239b92c12f698285d`
- Derived gzip SHA-256:
  `8a0d94a3743873cf2b9761c3aa79fa7884703903611f6f9163b758ddb0822476`
- Reproducible builder: `scripts/build_census_zcta_place_authority.py`

Transformation: retain rows with a populated ZCTA and place, active or
statistical place functional status, and positive intersecting land area;
require exact ZIP/state agreement with the GeoNames authority; remove one
terminal Census legal/statistical-area description such as `city`, `town`,
`village`, or `CDP`; preserve the seven-digit Census place GEOID; sort 52,565
unique `ZIP|state|place|place_geoid` rows deterministically; and gzip with
timestamp zero. Preserving place identity prevents a same-name city label from
collapsing distinct incorporated places or CDPs. A city claim is usable only
when all supplied city, ZIP, and county carriers leave one place GEOID, except
for an exact postal locality with no Census-place rows that is independently
anchored by its assigned ZIP.

United States Census Bureau data is in the public domain. ZCTAs approximate
postal delivery areas and are not a substitute for USPS delivery-route data,
so this relationship is used only as a place-name supplement. GeoNames remains
the configured authority for whether a ZIP is assigned and for its state.

## National county, place, ZIP, tract, and CBSA relationships

`census-national-location-authority.tsv.gz` lets the restricted-profile result
boundary reconcile county FIPS, place GEOIDs, tract GEOIDs, ZIPs, and CBSA
carriers nationally. It contains five deterministic relationship types: county
identity, Census place identity to county, assigned ZCTA to county, 2020 tract
identity to positive-land ZCTA intersections, and county to CBSA. Unknown
relationships fail closed.

Sources retrieved 2026-08-03:

- [2020 national county code file](https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt),
  SHA-256 `9f6e5f6eb6ac2f5e9a36d5fd01dec77991bddc75118f748a069441a4782970d6`
- [2020 national place-by-county code file](https://www2.census.gov/geo/docs/reference/codes2020/national_place_by_county2020.txt),
  SHA-256 `9996494d33cf6ee4527491508aa1b8dae85dcff3a979886e19b0b375e5d06ec6`
- [2020 national ZCTA-to-county relationship file](https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt),
  SHA-256 `3ed41278d637dc249e0323306f68be8a6c234e3090f4de88ef328dee71aeaaaf`
- [2020 national ZCTA-to-tract relationship file](https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_tract20_natl.txt),
  SHA-256 `6a25d8c3fff4cf612c4d2dccc2c0cd6cb5bc99b807ff3d5d107a2e9b9d68dde0`
- [July 2023 CBSA delineation file](https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list1_2023.xlsx),
  SHA-256 `952c4b1e78acbb54e6ec9412434b7602fedacbf021736351a63c181bdb753629`
- Derived gzip SHA-256:
  `ec28297f8f5bd29328c1cd696a7d007c3d80f083def465de3e6b017393e6b6e8`
- Reproducible builder: `scripts/build_national_location_authority.py`

Transformation: retain the 50 states, District of Columbia, and Puerto Rico;
normalize Census legal place and county-equivalent suffixes; preserve each
seven-digit place GEOID; keep active or statistical places; retain only
positive-land-area ZCTA/county and ZCTA/tract intersections; require every
ZCTA to exist in the separate integrity-checked postal authority with the same
state; and associate counties with the July 2023 CBSA delineation. The artifact
has 254,935 rows: 3,221 county identities, 33,298 place-GEOID/county
relationships, 46,777 ZCTA/county relationships, 169,733 tract identity/ZCTA
relationships, and 1,906 county/CBSA relationships. Rows are sorted bytewise
and gzip-compressed with timestamp zero.

The tract source proves existence, county, and ZCTA intersection. It does not
prove a common tract-to-place relationship. Restricted release therefore
rejects a tract carrier attached to a broader city GeoRef. The production
resolver projects that unsupported carrier away only for restricted profiles;
full operators retain the original response, and a raw or forged broader
city/tract protocol payload remains denied.

The July 2023 CBSA file uses Connecticut planning regions that do not share the
2020 county identities used by the other relationship sources. Those unmatched
rows are intentionally omitted and therefore fail closed. Census Bureau data is
in the public domain. The builder requires the `openpyxl` package to read the
official XLSX delineation file.
