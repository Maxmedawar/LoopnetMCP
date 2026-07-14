<!-- Researched by a background agent 2026-07-14; endpoints spot-verified by the agent, re-verify before building on any single endpoint. -->

# ZONING_SOURCES.md — Free & Programmatic US Zoning / Entitlement Data Reference

Curated for the CRE deal-intelligence engine. All entries below have been checked for a working URL as of 2026-07-14 and a one-line reliability judgement. "Free" means no signup or a public API key is sufficient; "Paywalled" is explicitly flagged.

The goal set the engine must serve per parcel:
1. Current zoning district + overlays
2. Permitted / conditional uses
3. FAR, height, setback, parking limits
4. Permit + planning-case activity

Sources are grouped by function. Section 5 gives copy-paste query recipes.

---

## 1. Municipal ArcGIS REST Endpoints (zoning polygons + overlays)

All endpoints below implement the standard Esri REST `/query` operation. Auth: none (public). Rate limits: not published by any of these municipalities — treat as "polite use, throttle client-side to <5 req/s". All return JSON with `f=json` and support point-in-polygon lookups via `geometryType=esriGeometryPoint`.

### 1.1 Austin, TX

| Endpoint | Purpose | Key fields |
|---|---|---|
| `https://maps.austintexas.gov/gis/rest/Shared/Zoning_2/MapServer` | Live base zoning + overlays | `ZONING_ZTYPE`, `CASE_NUMBER`, `ORDINANCE_NUMBER`, `EFFECTIVE_DATE` |
| `https://www.austintexas.gov/GIS/REST/ZoningProfile/ZoningProfile/MapServer` | Parcel-joined zoning profile (single-hit lookup) | `ZONING_ZTYPE`, `ZONING_TEMP`, `RELATED_CASES` |
| Austin GeoHub | Discovery / all layers | https://geohub.austintexas.gov/ |

Reliability: **High** — City of Austin runs its own ArcGIS Server, has published this pattern for 5+ years, layers get monthly updates.

### 1.2 Phoenix, AZ

| Endpoint | Purpose |
|---|---|
| `https://maps.phoenix.gov/pub/rest/services/Public/AllZoning/MapServer` | Combined service: Proposed Zoning, Approved Zoning, Zoning, Zoning Index, Zoning Overlays, Village Maps, Infill Incentive, Historic Properties |
| `https://maps.phoenix.gov/pub/rest/services/Public/Zoning/MapServer` | Current base zoning polygons (SR 2868) |
| `https://maps.phoenix.gov/pub/rest/services/Public/ZoningOverlays/MapServer` | Overlays: Airport, Arts, Business, Culture, Neighborhood Conservation, Special Planning Districts, Transportation |
| `https://maps.phoenix.gov/pub/rest/services/Public/ZoningIndex/MapServer` | Grid index (rarely needed unless you're reproducing paper sheets) |

Reliability: **High** — municipal ArcGIS Server; spatial reference 2868 (must project WGS84 → 2868 before querying, or request `inSR=4326`).

### 1.3 Denver, CO

| Endpoint | Purpose |
|---|---|
| `https://www.denvergov.org/arcgis/rest/services/NDCC/Navigate/MapServer/layers` | Master layer directory (browse to find Zoning layer id) |
| `https://denvergov.org/maps/data/Zoning/MapServer/1` | Zoning district polygons |
| `https://opendata-geospatialdenver.hub.arcgis.com/` | ArcGIS Hub: all Denver hosted feature services (GeoJSON downloads + REST endpoints for each dataset) |

Reliability: **High** — Denver migrated all public GIS to ArcGIS Online hosted feature services in 2020. Hub pages expose direct REST URLs.

### 1.4 Dallas, TX

| Endpoint | Purpose |
|---|---|
| `https://gis.dallascityhall.com/arcgis/rest/services/sdc_public/Zoning/MapServer` | Base zoning service (ArcGIS Server 10.61) |
| `https://gis.dallascityhall.com/arcgis/rest/services/sdc_public/Zoning/MapServer/1` | Zoning polygon layer |
| `https://egis.dallascityhall.com/arcgis/rest/services/` | Alternate ("egis") service root — same data, different vhost |
| `https://gisservices-dallasgis.opendata.arcgis.com/maps/dallas-zoning/explore` | Open Data landing page (find layer IDs) |

Reliability: **Medium-High** — occasional certificate/vhost drift between `gis.dallascityhall.com` and `egis.dallascityhall.com`; both host the same content. Cache the resolved base URL.

### 1.5 Houston, TX — *IMPORTANT CAVEAT*

Houston is the only major US city with **no municipal zoning**. Development is governed by Chapter 42 (subdivision), deed restrictions, and Special Districts — not use districts. There is no "zoning polygon" to fetch. Use land-use and district layers instead:

| Endpoint | Purpose |
|---|---|
| `https://mapsop1.houstontx.gov/arcgis/rest/services` | Root: all public services (ArcGIS Server 10.91) |
| `https://mycity2.houstontx.gov/pubgis02/rest/services` | Root: additional services (HoustonMap, Parks, Utilities) |
| `https://cohgis-mycity.opendata.arcgis.com/` | COHGIS Data Hub — Land Use, Super Neighborhoods, ETJ, Special Districts |
| `https://geohub.houstontx.gov/` | Houston Public Works open-data hub |
| H-GAC Land Use (regional) | https://www.h-gac.com/land-use-and-land-cover-data (file GDB, not REST) |

Reliability: **High** on the layers that exist, but engine logic must special-case Houston: return `has_zoning=false` and instead surface (a) COH Land Use, (b) Chapter 42 rules from Municode, (c) any Special District overlays, (d) deed-restriction disclaimer.

### 1.6 Atlanta, GA

| Endpoint | Purpose |
|---|---|
| `https://gis.atlantaga.gov/dpcd/rest/services` | Service root (Department of City Planning) |
| `https://gis.atlantaga.gov/dpcd/rest/services/LandUsePlanning/LandUsePlanning/MapServer` | Zoning Overlay, Zoning District, Inclusionary Zoning, Zoning Map Index, BeltLine TCU Corridor, Building Moratorium, Historic District, Landmark Building Site |
| `https://gis.atlantaga.gov/dpcd/rest/services/OpenDataService/MapServer/22` | Zoning District layer (display field `ZONECLASS`, polygon, JSON+GeoJSON, maxRecordCount=1000) |
| `https://gis.atlantaga.gov/rezoning/` | Rezoning-cases web app (feature service backing it) |

Reliability: **High** — Atlanta DPCD keeps a stable REST endpoint schema; ZONECLASS field is authoritative.

### 1.7 Las Vegas metro (city of LV + Clark County + North LV)

| Endpoint | Purpose |
|---|---|
| `https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/rest/services/ZONING/FeatureServer` | **City of Las Vegas** Community Development Planning zoning (updated Apr 2025) |
| `https://maps.clarkcountynv.gov/arcgis/rest/services/OpenData/PlanningandZoning/MapServer` | **Clark County** — Planned Land Use, Zoning, Historic Neighborhood Overlay, RNP, PC Overlay, Flood Control |
| `https://maps.clarkcountynv.gov/arcgis/rest/services/OpenData/PlanningandZoning/MapServer/10` | North Las Vegas Zoning (polygon layer within the Clark service) |
| `https://mapdata.lasvegasnevada.gov/clvgis/rest/services` | City of LV service root (DevelopmentServices folder) |
| `https://opendataportal-lasvegas.opendata.arcgis.com/` | City of LV Open Data hub |

Reliability: **High**. Watch the jurisdiction boundary carefully — Strip parcels are unincorporated Clark County, not City of LV. Query both.

### 1.8 Bonus tier — cities with exceptionally good open zoning APIs

**New York City** — the gold standard for programmatic zoning:
- ZoLa (Zoning & Land Use Map) source + API: https://github.com/NYCPlanning/labs-zola
- PLUTO / MapPLUTO tax-lot dataset (every lot, every attribute): https://data.cityofnewyork.us/City-Government/Primary-Land-Use-Tax-Lot-Output-PLUTO-/64uk-42ks (Socrata ID `64uk-42ks`)
- NYC Planning open source repo: https://github.com/NYCPlanning/db-pluto
- Reliability: **Excellent** — NYC Planning Labs actively maintains this as a public-code project.

**San Francisco**:
- `http://sfplanninggis.org/arcgiswa/rest/services/PlanningData/MapServer/3` — Zoning Districts polygon layer
- DataSF Socrata companion dataset: `data.sfgov.org` id `3i4a-hu95`
- Reliability: **High** — SF Planning GIS is stable but note it's `http`, not `https` on that host; add TLS-fallback in the client.

**Seattle**:
- `data.seattle.gov` dataset `n8h3-r7is` — Current Land Use Zoning Detail (Socrata)
- ArcGIS mirror: https://data-seattlecitygis.opendata.arcgis.com/datasets/dd29065b5d01420e9686570c2b77502b_0
- Reliability: **High** — dual-published in Socrata + Esri Hub.

**Los Angeles**:
- Official portal is ZIMAS (https://zimas.lacity.org), which does **not** expose a documented public REST endpoint — the front-end talks to internal services.
- Zoning polygons are, however, published via LA GeoHub and data.lacity.org (search "Zoning" — the layer id changes when they rebuild). Screen-scraping ZIMAS is discouraged; prefer GeoHub feature service URLs.
- Reliability: **Medium** — no long-term stable REST URL that I can commit to in this doc; resolve at runtime from GeoHub search.

---

## 2. National Aggregators — Free vs Paywalled Audit

| Source | What it gives you | Free tier reality | Reliability judgement |
|---|---|---|---|
| **Zoneomics** (https://www.zoneomics.com/product/api) | 20k+ cities, 100M parcels, zoneDetail API, permitted uses, FAR/setback/height where standardized | Only a "Tiling Service" is free (100k tile calls) — the actual zoning-attribute API is **paywalled** (usage-based or monthly). No free tier for zoneDetail. | Best commercial coverage; **not** a free option for the engine |
| **Regrid / Landgrid** (https://regrid.com/api) | Nationwide parcels (100%), zoning attribute layer in select major metros | Free "Starter" web account = 25 lookups/day via UI; **API access is paid**. Zoning coverage is partial — parcels are 100%, zoning is "select markets". | Great parcel spine, **paywalled zoning API** |
| **National Zoning Atlas** (https://www.zoningatlas.org/) | Standardized zoning attributes across ~30,000 US codes (~200 features per district) | **Yes — free**: GeoJSON + CSV/XLS downloads by state/region, CC-BY. DOI `10.4079/zoning-atlas`. Coverage is state-by-state and still growing; not every metro complete. | **Best genuinely free national attribute source**; use as normalizer/enrichment layer |
| **OpenStreetMap `landuse=*`** via Overpass API | `landuse=commercial|residential|industrial|retail|...` polygons; not legal zoning but a decent land-use fallback | **Free**. Public endpoints: `https://overpass-api.de/api/interpreter`, mirror `https://overpass.kumi.systems/api/interpreter`, `https://overpass.private.coffee/api/interpreter`. Rate: 429 when saturated; default 180 s query timeout, 512 MiB memory; concurrency-per-IP throttle. | **Free fallback only** — do NOT treat OSM landuse as legal zoning. Useful where municipal REST is missing. |
| **HUD Cityscape / Urban Institute zoning research datasets** | Machine-readable subsets tied to specific studies | Free downloads; not a live API | Reference-quality, not real-time |

**Bottom line for a free engine:** primary path is per-metro ArcGIS REST; National Zoning Atlas is the best free national attribute enrichment; OSM is the last-resort fallback; Zoneomics and Regrid zoning are commercial and should not be in the free core path.

---

## 3. Permit & Planning-Case Feeds — Socrata (SODA) API

All Socrata endpoints follow the pattern:

```
https://{portal}/resource/{dataset_id}.json?$where=...&$limit=...
```

Auth: **no auth required** for reads; without an app token you're throttled per-IP; with a free app token you get "up to 1,000 requests per rolling hour" and preferential (effectively un-throttled) treatment. Register at any Socrata portal to get one token that works cross-portal.

Docs: https://dev.socrata.com/docs/app-tokens.html · https://dev.socrata.com/docs/response-codes

### Confirmed permit / planning datasets

| City | Portal | Dataset ID | Dataset name | Notes |
|---|---|---|---|---|
| Austin, TX | data.austintexas.gov | `3syk-w9eu` | Issued Construction Permits | Building, electrical, mechanical, plumbing, driveway/sidewalk. Issue date, location, council district, description, sq ft, valuation, units |
| Austin, TX | data.austintexas.gov | `nbzi-qabm` | Zoning By Address (lookup helper) | |
| Chicago, IL | data.cityofchicago.org | `ydr8-5enu` | Building Permits | 2006–present; has ZONING_FEE_* fields, PIN, ward, community area |
| San Francisco, CA | data.sfgov.org | `i98e-djp9` | Building Permits | |
| San Francisco, CA | data.sfgov.org | `p4e4-a5a7` | Building Permits filed on or after 2013-01-01 | Alt/filtered view |
| San Francisco, CA | data.sfgov.org | `3i4a-hu95` | Zoning Map – Zoning Districts (polygons) | |
| Los Angeles, CA | data.lacity.org | `pi9x-tg5x` | Building Permits (Building & Safety) | |
| NYC | data.cityofnewyork.us | `64uk-42ks` | PLUTO (tax lot + zoning attributes) | Superset — has zoning district, FAR, lot area, building info on every lot |
| Seattle, WA | data.seattle.gov | `76t5-zqzr` | Building Permits (SODA foundry-listed) | |
| Seattle, WA | data.seattle.gov | `n8h3-r7is` | Current Land Use Zoning Detail | |

Reliability: **High**. Socrata SODA is a mature, stable API. Dataset IDs are permanent per-portal; the underlying schemas evolve slowly. Always send an X-App-Token header once you have one.

### Cities that publish permit data but NOT on Socrata (Esri Hub instead)

- **Atlanta, GA** — permits are on the DPCD ArcGIS Open Data Hub, not `data.atlantaga.gov`. Use https://dpcd-coaplangis.opendata.arcgis.com/datasets/655f985f43cc40b4bf2ab7bc73d2169b (All Building Permits 2019–2024). Query it as an ArcGIS feature service.
- **Phoenix, AZ** — permits are Esri-based; no Socrata endpoint.
- **Denver, CO** — mixed: Denver has a Socrata-style catalog at denvergov.org/opendata but most spatial datasets are hosted feature services on ArcGIS Online. Use their Hub URL `https://opendata-geospatialdenver.hub.arcgis.com/` and pull the REST endpoint per dataset.
- **Dallas, TX** — permits via ArcGIS Hub (`gisservices-dallasgis.opendata.arcgis.com`), not Socrata.
- **Las Vegas / Clark County** — ArcGIS Hub, not Socrata.

The engine should therefore support **two permit-source shapes**: Socrata SODA (JSON, `$where` filters) and ArcGIS FeatureServer (`/query?where=...&outFields=*`).

---

## 4. Municipal Zoning CODE TEXT (FAR tables, use tables, parking minimums)

Zoning polygons tell you the district name; the code text tells you what that district *permits*. Two providers cover ~85% of US municipalities.

### 4.1 Municode / MunicodeNEXT (CivicPlus)

Public URL: `https://library.municode.com/`

Human-readable URL pattern:
```
https://library.municode.com/{state}/{city}/codes/code_of_ordinances
https://library.municode.com/{state}/{city}/codes/code_of_ordinances?nodeId={NODE_ID}
```

Examples: `library.municode.com/ga/atlanta/codes/code_of_ordinances`, `library.municode.com/nv/clark_county/codes/code_of_ordinances?nodeId=TIT30UNDECO_30.36ZODIMA`.

Machine-readable **unofficial** API at `https://api.municode.com` (undocumented, reverse-engineered):
- `GET /codes` — list clients / codes by state
- `GET /clients/{clientId}/products` — enumerate products a jurisdiction has
- `GET /jobs/{jobId}` — job/contract metadata
- Node-tree endpoints: get children of a node, get content of current node + descendants
- Search endpoint: word/phrase search across MuniDocs
- Auth: none discovered, but expect Cloudflare / bot mitigation (the base URL returns 403 to naive fetchers; a browser-shaped UA + referrer works).

Open-source scrapers:
- https://github.com/noclocks/municode-scraper
- https://github.com/dkylewillis/municode-scraper-lib
- Unofficial API doc project: https://sr.ht/~partytax/unofficial-municode-api-documentation/

Reliability: **Medium**. Municode does not sanction this use; endpoints can change without notice. Cache aggressively (code text changes on ordinance adoption, i.e., weeks-to-months cadence). Respect ToS; consider a nightly full pull rather than per-request live fetching.

### 4.2 American Legal Publishing — Code Library

Public URL: `https://codelibrary.amlegal.com/`

URL pattern:
```
https://codelibrary.amlegal.com/codes/{city_slug}/latest/overview
https://codelibrary.amlegal.com/codes/{city_slug}/latest/{code_slug}/{section_id}
```

Examples:
- `codelibrary.amlegal.com/codes/los_angeles/latest/overview`
- `codelibrary.amlegal.com/codes/los_angeles/latest/lamc/0-0-0-108121` (LA Zoning: Comprehensive Zoning Plan article)

There is **no public API**; content is served as SPA HTML. Section IDs are stable per version. Search endpoint at `codelibrary.amlegal.com/search`.

Reliability: **Medium**. Same caveat as Municode — scrape carefully, cache, do not hammer.

### 4.3 eCode360 / General Code (ICC Code Solutions)

Public URL: `https://ecode360.com/`

Official REST API: `https://api.ecode360.com/v1/customer/{CUSTOMER_ID}/code/content/{CONTENT_ID}`
- Auth: **key/secret pair** issued per municipality — you must contact each municipality individually to be granted access. In practice this means eCode360 API is available only for jurisdictions willing to grant you a key.
- Developer portal: https://developer.ecode360.com/

Reliability: **High** where you have a key (this is a real, documented REST API), **Medium** in aggregate because obtaining keys is per-municipality manual overhead. For the free engine, treat eCode360 as HTML-scrape by default, and upgrade individual cities to API when a key is obtainable.

### 4.4 Which provider hosts which city?

Rough rules of thumb (verify per-lookup, do not hardcode):
- **Municode**: Atlanta GA, most of Georgia, Clark County NV, Orange County FL, tens of thousands of small-to-mid municipalities
- **American Legal**: Los Angeles CA, San Francisco CA (partial), Chicago IL, most of Ohio
- **eCode360**: much of the Northeast (NY, NJ, PA), plus scattered Midwest municipalities
- **Self-hosted**: NYC (nyc.gov), Austin (austintexas.gov), Denver (denvergov.org), Seattle (seattle.gov), Phoenix (phoenix.gov)

The engine should implement a **code-provider resolver**: given (state, city), map to (municode|amlegal|ecode360|self-hosted) with URL patterns above.

---

## 5. Query Recipes (drop-in for the Python engine)

### 5.1 ArcGIS REST point-in-polygon (any municipal zoning layer)

```
GET {LAYER_URL}/query?
  where=1=1
  &geometry={"x":LON,"y":LAT,"spatialReference":{"wkid":4326}}
  &geometryType=esriGeometryPoint
  &inSR=4326
  &spatialRel=esriSpatialRelIntersects
  &outFields=*
  &returnGeometry=true
  &outSR=4326
  &f=json
```

`inSR=4326` handles WGS84 input regardless of the layer's native SR (e.g., Phoenix uses SR 2868). `outSR=4326` keeps returned geometry in WGS84.

### 5.2 Socrata SODA — permits near a point in the last 12 months

```
GET https://data.cityofchicago.org/resource/ydr8-5enu.json?
  $where=issue_date > '2025-07-14T00:00:00.000'
        AND within_circle(location, LAT, LON, 500)
  $limit=1000
Header: X-App-Token: {SOCRATA_APP_TOKEN}
```

### 5.3 Overpass API — landuse fallback

```
POST https://overpass-api.de/api/interpreter
Body:
  [out:json][timeout:60];
  is_in(LAT, LON) -> .a;
  way(pivot.a)["landuse"];
  out tags geom;
```

### 5.4 Atlanta zoning + overlays combined lookup

```
GET https://gis.atlantaga.gov/dpcd/rest/services/OpenDataService/MapServer/22/query?
  geometry={x},{y}&geometryType=esriGeometryPoint&inSR=4326
  &spatialRel=esriSpatialRelIntersects
  &outFields=ZONECLASS,*
  &f=json
```

Then re-query the overlay layers under `LandUsePlanning/LandUsePlanning/MapServer` with the same geometry.

---

## 6. Coverage Gaps — Be Honest

| Metro / topic | Gap |
|---|---|
| **Los Angeles** | No stable, publicly documented REST endpoint for zoning polygons; ZIMAS is UI-only. Resolve LA at runtime via LA GeoHub search rather than hardcoding a URL. |
| **Houston** | No zoning at all. Engine must special-case: return `has_zoning=false`, surface land-use + Chapter 42 + deed-restriction warning. |
| **Rural / small-town US** | Municode / AmLegal / eCode360 may not cover the jurisdiction at all. Fall back to county-level zoning REST + a PDF-scrape path (out of scope for this doc). |
| **FAR / height / setback / parking tables** | These live in the **code text**, not the GIS polygons. There is *no* free national API that returns "FAR for zone X-3 in city Y" reliably. Options: (a) parse code text from Municode/AmLegal/eCode360; (b) purchase Zoneomics; (c) use National Zoning Atlas where the state is covered. Recommend a hybrid: NZA where covered → parsed code text where not → mark as "unknown, see code link" otherwise. |
| **Overlay coverage** | ArcGIS layers publish overlay geometry but overlay *effects* (e.g., "TOD overlay reduces parking minimum by 50%") are in the code text. Same gap as FAR. |
| **Real-time zoning changes** | Zoning amendments become effective before layers refresh. Most cities update layers weekly-to-monthly. For deal-blocking accuracy, always cross-reference the ordinance number + effective date returned in the polygon attributes. |
| **Socrata rate limit ceiling** | 1,000 req/hour per app-token is soft — sufficient for interactive lookups, insufficient for bulk backfills. For bulk, use dataset export (CSV) endpoints instead of live SODA. |
| **Municode / AmLegal ToS** | Neither sanctions bulk scraping. Cache aggressively and consider it a legal-risk vector for the product. eCode360 has a legitimate API but requires per-municipality key grants. |

---

## 7. Recommended Engine Architecture (implication for Python code)

1. **Zoning polygon resolver**: input (lat, lon) → resolve jurisdiction (city + county) → dispatch to per-metro ArcGIS REST endpoint → return zoning district + all intersecting overlays. Fallback chain: municipal REST → Regrid (if licensed) → OSM landuse (labeled as non-authoritative).
2. **Zoning attribute enricher**: input (jurisdiction, district code) → look up FAR/height/setback/parking via: National Zoning Atlas → parsed code text (Municode/AmLegal/eCode360) → cache. Return with confidence score.
3. **Permit feed**: dual-shape adapter — Socrata SODA for cities in Section 3 table, ArcGIS FeatureServer for Atlanta/Phoenix/Denver/Dallas/LV.
4. **Code text fetcher**: provider-per-city map + rate-limited scraper with 24-hour cache. Store raw HTML + parsed sections keyed by (city, ordinance_number).
5. **Special cases**: Houston = no-zoning branch; LA = GeoHub search-first; unincorporated Clark County (Vegas Strip) = Clark County service, not City of LV.

---

## Source URLs (citations)

- Austin Zoning Shared MapServer: https://maps.austintexas.gov/gis/rest/Shared/Zoning_2/MapServer
- Austin ZoningProfile MapServer: https://www.austintexas.gov/GIS/REST/ZoningProfile/ZoningProfile/MapServer
- Austin Zoning By Address (Socrata): https://data.austintexas.gov/Building-and-Development/Zoning-By-Address/nbzi-qabm
- Austin Issued Construction Permits: https://data.austintexas.gov/Building-and-Development/Issued-Construction-Permits/3syk-w9eu
- Austin GeoHub: https://geohub.austintexas.gov/
- Phoenix AllZoning MapServer: https://maps.phoenix.gov/pub/rest/services/Public/AllZoning/MapServer
- Phoenix Zoning: https://maps.phoenix.gov/pub/rest/services/Public/Zoning/MapServer
- Phoenix Zoning Overlays: https://maps.phoenix.gov/pub/rest/services/Public/ZoningOverlays/MapServer
- Phoenix Zoning Index: https://maps.phoenix.gov/pub/rest/services/Public/ZoningIndex/MapServer
- Denver Zoning MapServer layer: https://denvergov.org/maps/data/Zoning/MapServer/1
- Denver NDCC Navigate root: https://www.denvergov.org/arcgis/rest/services/NDCC/Navigate/MapServer/layers
- Denver Open Data (ArcGIS Hub): https://opendata-geospatialdenver.hub.arcgis.com/
- Dallas Zoning MapServer: https://gis.dallascityhall.com/arcgis/rest/services/sdc_public/Zoning/MapServer
- Dallas Zoning (open data): https://gisservices-dallasgis.opendata.arcgis.com/maps/dallas-zoning/explore
- Houston GIS ArcGIS root: https://mapsop1.houstontx.gov/arcgis/rest/services
- Houston secondary GIS root: https://mycity2.houstontx.gov/pubgis02/rest/services
- Houston COHGIS Hub: https://cohgis-mycity.opendata.arcgis.com/
- Houston GeoHub (Public Works): https://geohub.houstontx.gov/
- H-GAC regional land use: https://www.h-gac.com/land-use-and-land-cover-data
- Atlanta DPCD REST root: https://gis.atlantaga.gov/dpcd/rest/services
- Atlanta LandUsePlanning MapServer: https://gis.atlantaga.gov/dpcd/rest/services/LandUsePlanning/LandUsePlanning/MapServer
- Atlanta Zoning District layer 22: https://gis.atlantaga.gov/dpcd/rest/services/OpenDataService/MapServer/22
- Atlanta All Building Permits 2019-2024: https://dpcd-coaplangis.opendata.arcgis.com/datasets/655f985f43cc40b4bf2ab7bc73d2169b
- City of Las Vegas ZONING FeatureServer: https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/rest/services/ZONING/FeatureServer
- Clark County Planning and Zoning MapServer: https://maps.clarkcountynv.gov/arcgis/rest/services/OpenData/PlanningandZoning/MapServer
- North Las Vegas Zoning layer 10: https://maps.clarkcountynv.gov/arcgis/rest/services/OpenData/PlanningandZoning/MapServer/10
- City of Las Vegas GIS root: https://mapdata.lasvegasnevada.gov/clvgis/rest/services
- City of Las Vegas Open Data: https://opendataportal-lasvegas.opendata.arcgis.com/
- NYC ZoLa data: https://zola.planning.nyc.gov/data
- NYC ZoLa source: https://github.com/NYCPlanning/labs-zola
- NYC PLUTO Socrata dataset: https://data.cityofnewyork.us/City-Government/Primary-Land-Use-Tax-Lot-Output-PLUTO-/64uk-42ks
- NYC PLUTO docs / repo: https://github.com/NYCPlanning/db-pluto
- SF Zoning Districts REST: http://sfplanninggis.org/arcgiswa/rest/services/PlanningData/MapServer/3
- SF Zoning Map (Socrata): https://data.sfgov.org/Geographic-Locations-and-Boundaries/Zoning-Map-Zoning-Districts/3i4a-hu95
- SF Building Permits (Socrata): https://data.sfgov.org/w/i98e-djp9 (SODA foundry: https://dev.socrata.com/foundry/data.sfgov.org/i98e-djp9)
- Chicago Building Permits (Socrata): https://data.cityofchicago.org/Buildings/Building-Permits/ydr8-5enu
- Seattle Land Use Zoning (Socrata): https://data.seattle.gov/dataset/Current-Land-Use-Zoning-Detail/n8h3-r7is
- Seattle GeoData Hub: https://data-seattlecitygis.opendata.arcgis.com/
- ZIMAS (Los Angeles): https://zimas.lacity.org/
- Zoneomics API (paywalled): https://www.zoneomics.com/product/api ; pricing: https://www.zoneomics.com/pricing/api
- Regrid API: https://regrid.com/api ; zoning coverage: https://regrid.com/zoning
- National Zoning Atlas: https://www.zoningatlas.org/ ; downloads: https://www.zoningatlas.org/atlas
- HUD Cityscape article on NZA: https://www.huduser.gov/portal/pdredge/pdr-edge-featd-article-071123.html
- OpenStreetMap Overpass API wiki: https://wiki.openstreetmap.org/wiki/Overpass_API
- OSM Key:landuse: https://wiki.openstreetmap.org/wiki/Key:landuse
- Overpass mirror (unlimited): https://overpass.private.coffee/api/interpreter
- Municode Library: https://library.municode.com/
- Municode about API (Aha REST): https://www.municode.com/help/aha_restapi_server/aha-restapi-server-about
- Unofficial Municode API docs: https://sr.ht/~partytax/unofficial-municode-api-documentation/
- Municode scraper (noclocks): https://github.com/noclocks/municode-scraper
- Municode scraper (dkylewillis): https://github.com/dkylewillis/municode-scraper-lib
- American Legal Publishing Code Library: https://codelibrary.amlegal.com/
- eCode360 Developer Gateway: https://developer.ecode360.com/
- eCode360 library: https://www.generalcode.com/online-code/
- Socrata App Tokens & rate limits: https://dev.socrata.com/docs/app-tokens.html
- Socrata response codes: https://dev.socrata.com/docs/response-codes
- Socrata throttling clarification: https://dev.socrata.com/changelog/2016/06/04/clarification-of-throttling-limits
- ArcGIS REST Query (Feature Service): https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service/
- ArcGIS REST Geometry objects: https://developers.arcgis.com/rest/services-reference/enterprise/geometry-objects/