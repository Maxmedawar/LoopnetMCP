# Zoning fixture provenance

All four fixtures are real public responses captured with `curl` on 2026-07-14.
`jq -c` changed whitespace only. No app token or other credential was used.
Tests load these files and make no network requests.

## Austin zoning

- Source endpoint: `https://maps.austintexas.gov/gis/rest/Shared/Zoning_1/MapServer/0/query`
- Layer: `0 — Zoning`
- Point: South Lamar, `30.256,-97.763`
- Parameters: `f=json`, `where=1=1`, WGS84 point geometry, `inSR=4326`,
  `spatialRel=esriSpatialRelIntersects`,
  `outFields=ZONING_ZTYPE,ZONING_BASE`, `outSR=4326`
- Fixture: `austin_zoning.json`

The documented `Zoning_2` service was inspected first and contained only overlay
layers on capture day. The adjacent official Shared service `Zoning_1`, layer 0,
was therefore used for the live base district. An initial downtown civic-area
probe returned a valid empty feature list before the South Lamar capture.

## Atlanta zoning

- Source endpoint: `https://gis.atlantaga.gov/dpcd/rest/services/LandUsePlanning/LandUsePlanning/MapServer/0/query`
- Layer: `0 — Zoning District`
- Point: Downtown Atlanta, `33.749,-84.388`
- Parameters: the same WGS84 point-intersection parameters, with
  `outFields=ZONECLASS,ZONEDESC,LASTUPDATE,CASEIN,CASEOUT,SUNRISE,SUNSET`
- Fixture: `atlanta_zoning.json`

The reference's `OpenDataService/MapServer/22` metadata URL returned the official
ArcGIS `Service OpenDataService/MapServer not found` response on capture day.
The reference also lists the LandUsePlanning service; its live base layer 0 has
the authoritative `ZONECLASS` schema and was used instead.

## Clark County zoning

- Source endpoint: `https://maps.clarkcountynv.gov/arcgis/rest/services/OpenData/PlanningandZoning/MapServer/11/query`
- Layer: `11 — Clark County Zoning`
- Point: Las Vegas Strip (unincorporated Clark County), `36.1147,-115.1728`
- Parameters: the same WGS84 point-intersection parameters, with
  `outFields=ZNCLASS,MLL_ZNCLASS,Description,created_date,last_edited_date`
- Fixture: `clark_county_zoning.json`

## Chicago permits (Socrata)

- Source endpoint: `https://data.cityofchicago.org/resource/ydr8-5enu.json`
- Layer/dataset: `Building Permits (ydr8-5enu)`
- Query: `$where=issue_date > '2025-07-14T00:00:00.000' AND
  within_circle(location, 41.8781, -87.6298, 500)` and `$limit=2`
- Fixture: `chicago_permits.json`

An earlier Austin Socrata attempt was rejected with HTTP 400 because the shell
command quoted `$where` incorrectly; it yielded no fixture. The corrected,
documented Chicago query above is the captured permit response.

The three ArcGIS fixture captures used `returnGeometry=false` solely to avoid
storing large polygon rings. Production query construction follows §5.1 and
uses `returnGeometry=true` plus `outSR=4326`.
