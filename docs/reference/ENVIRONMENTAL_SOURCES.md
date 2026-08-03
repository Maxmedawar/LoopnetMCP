<!-- Researched by a background agent 2026-07-14; endpoints spot-verified by the agent, re-verify before building on any single endpoint. -->

# Environmental Data Sources for CRE Pre-Phase I Screening

**Scope:** Free, programmatically-accessible US environmental data sources suitable for automated screening of a commercial property (address or lat/lon) for Recognized Environmental Conditions (RECs) prior to commissioning a formal ASTM E1527-21 Phase I ESA.

**Intended use:** Feed a Python screening engine that ingests an address or coordinate, resolves nearby regulated facilities and hazards, and produces a risk-flag report. This document is a source-of-truth reference; it is not itself a Phase I substitute.

**Reliability grades used below:**
- **A** — Authoritative, primary-source, actively maintained, well-documented API.
- **B** — Authoritative but stale, semi-documented, or requires scraping/derivation.
- **C** — Useful signal but coverage/quality varies materially by geography or time.
- **D** — Best-effort only; treat as hint, not evidence.

---

## 1. EPA Federal Sources

### 1.1 EPA Envirofacts Data Service API

**Purpose:** Direct SQL-style REST access to virtually every table in EPA's internal databases (RCRAInfo, SEMS/Superfund, TRI, ACRES, ICIS, SDWIS, GHG, and the FRS reference layer). This is the single most valuable federal endpoint for CRE due diligence.

- **Base URL:** `https://data.epa.gov/efservice/`
- **URL pattern:** `https://data.epa.gov/efservice/{schema.table}/{column}/{operator}/{value}/{rows/N:M}/{format}`
- **Auth:** None. Public, unauthenticated GET.
- **Rate limits:** No formal published quota; row cap ~10,000 per request. Paginate with `/rows/N:M`.
- **Formats:** `JSON` (default in v2), `XML`, `CSV`, `EXCEL`, `PARQUET`, `PDF`.
- **Operators:** `equals`, `beginning`, `containing`, `greater_than`, `less_than`, `between`.
- **Docs:** https://www.epa.gov/enviro/envirofacts-data-service-api  |  https://www.epa.gov/enviro/web-services
- **Reliability: A** (schema drift happens; test against `/COUNT` before relying on a field).

**Tables that matter for CRE screening (schema.table):**

| Program | Table(s) | What it tells you |
|---|---|---|
| **FRS** (master registry) | `frs.frs_facilities`, `frs.frs_program_links`, `frs.frs_naics_codes` | Every EPA-regulated facility with lat/lon, address, and which program acronyms apply (RCRA, SEMS, TRI, etc.). Start here to enumerate anything regulated within X miles. |
| **RCRA** (hazardous waste) | `rcrainfo.rcra_handler`, `rcrainfo.hd_handler`, `rcrainfo.ca_authority` (corrective action), `rcrainfo.ce_citation` (violations) | Hazardous-waste generators/TSDs, corrective-action status, RCRA violations. VSQG/SQG/LQG status is a REC signal. |
| **Superfund (SEMS)** | `sems.envirofacts_site`, `sems.envirofacts_contaminants`, `sems.envirofacts_actions` | NPL and non-NPL Superfund sites, contaminants of concern, cleanup actions. |
| **Brownfields (ACRES)** | `acres.frs_properties`, `acres.frs_contaminants` | EPA-grant-funded brownfields with contaminants, cleanup status. |
| **TRI** (toxic releases) | `tri.tri_facility`, `tri.tri_reporting_form`, `tri.tri_release_qty` | Reported chemical releases by year — good indicator of on/off-site chemical loading. |
| **ICIS-AIR / NPDES** | `icis.icis_facilities`, `icis.icis_permits` | Clean Air Act and NPDES permit holders. |
| **UST (federal reference)** | Only partial coverage — federal has UST **program identifiers**, not tank rosters (see UST Finder below and state sources). | See §1.4. |

**Example queries:**

Enumerate all FRS-registered facilities in ZIP 77571 as JSON:
```
https://data.epa.gov/efservice/frs.frs_facilities/postal_code/equals/77571/JSON
```

RCRA handlers in Harris County, TX:
```
https://data.epa.gov/efservice/rcrainfo.rcra_handler/location_state/equals/TX/location_county/equals/HARRIS/JSON
```

TRI reports for a specific facility ID:
```
https://data.epa.gov/efservice/tri.tri_facility/tri_facility_id/equals/77571FRSHR8600F/JSON
```

SEMS sites in California with contaminants (left join):
```
https://data.epa.gov/efservice/sems.envirofacts_site/state/equals/CA/sems.envirofacts_contaminants/site_id/equals/fk_site_id/JSON
```

**Fields you will consume for screening (FRS core):**
`registry_id`, `primary_name`, `location_address`, `city_name`, `state_code`, `postal_code`, `latitude83`, `longitude83`, `pgm_sys_acrnm` (program acronym), `pgm_sys_id`, `interest_types`, `active_status`, `naics_codes`.

**Gaps / honest caveats:**
- Envirofacts is a **snapshot** of internal EPA warehouses refreshed on program-specific schedules (monthly to quarterly). Lag of 30–90 days is normal.
- Lat/lon quality varies. Many older RCRA/SEMS records geocode to the ZIP centroid or a nearby city intersection, not the actual parcel. Cross-check against FRS_INTERESTS ArcGIS layer geometry.
- Historical facility records may lack current names/owners; a site that changed hands twice will still appear under its 1990 name.
- No native radius query — you must either filter by state/city/ZIP or use the FRS ArcGIS endpoint (§1.2) or the FRS REST radius endpoint (§1.3).

---

### 1.2 EPA FRS ArcGIS REST (spatial radius / bounding-box)

**Purpose:** Spatial index over the FRS. Use this when you have lat/lon and want "everything EPA-regulated within N miles."

- **Base URL:** `https://geodata.epa.gov/arcgis/rest/services/OEI/FRS_INTERESTS/MapServer`
- **Layer 0 = FRS Interests** (points, all programs mixed)
- **Query endpoint pattern:**
  ```
  {base}/0/query?geometry={lon},{lat}&geometryType=esriGeometryPoint&inSR=4326&distance=1609.34&units=esriSRUnitMeter&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=json
  ```
- **Also useful:** `https://geopub.epa.gov/arcgis/rest/services/EMEF/efpoints/MapServer` — layers include Brownfields (5), Superfund, RCRA, TRI as separate IDs.
- **Auth:** None.
- **Rate limits:** ArcGIS Server default — no hard quota; be polite (< 5 req/sec).
- **Reliability: A** for geometry, but attribute fields are a subset of the Envirofacts view.
- **Pattern:** Radius search here → get `REGISTRY_ID` → deep-lookup in Envirofacts by `frs_facilities.registry_id`.

**Gaps:**
- Some ArcGIS layers only expose a summarized attribute set; corrective-action detail, violation history, TRI amounts are **not** on the map layer.
- `distance` requires meters when `units=esriSRUnitMeter`; conversion errors are the #1 bug here.

---

### 1.3 EPA FRS REST Services (radius by program)

**Purpose:** Legacy FRS REST endpoint that supports lat/lon + radius + program acronym. Simpler than ArcGIS when you want "give me all Superfund sites within 3 miles of this point."

- **Endpoint:** `https://frs-public.epa.gov/ords/frs_public2/frs_rest_services.get_facilities`
- **Query example:**
  ```
  https://frs-public.epa.gov/ords/frs_public2/frs_rest_services.get_facilities?latitude83=38.8&longitude83=-77.01&search_radius=3&pgm_sys_acrnm=SEMS&output=JSON
  ```
- **Key params:** `latitude83`, `longitude83`, `search_radius` (miles, max 5), `pgm_sys_acrnm`, `state_code`, `postal_code`, `output` (`JSON`/`XML`/`JSONP`).
- **Program acronyms of interest:** `SEMS` (Superfund), `RCRAINFO` (hazardous waste), `TRIS` (TRI), `ACRES` (brownfields), `NPDES`, `AIRS/AFS` or `ICIS-AIR` (air), `SDWIS` (drinking water), `E-GGRT` (GHG), `UST` (federally-tracked USTs — sparse).
- **Docs:** https://www.epa.gov/frs/frs-rest-services  |  https://www.epa.gov/frs/frs-api
- **Auth:** None. **Rate limits:** informal; 5 mile radius cap.
- **Coordinate system:** NAD83 (treat as ~WGS84 for CRE screening; sub-meter difference).
- **Reliability: A**.

**Gaps:**
- Radius capped at 5 miles per call — for wider sweeps, tile the area or use the ArcGIS endpoint.
- No violation/enforcement detail in the response — join by `registry_id` to ECHO or Envirofacts.

---

### 1.4 EPA UST Finder (national UST + release composite)

**Purpose:** EPA's national roll-up of state UST and LUST data. The best single national UST source when a state doesn't have a good open endpoint.

- **App:** https://www.epa.gov/ust/ust-finder
- **Feature layer (item):** `88d551abd342485582c5ca4aac6ac0d6` on ArcGIS Online
- **FeatureServer example:** `https://services.arcgis.com/{org}/arcgis/rest/services/UST_Finder/FeatureServer/{0..N}/query`
- **Coverage:** States as of 2018–2019, US territories 2020–2021, Tribal lands 2025. Attributes include tank count, release status, distance to public drinking-water source, floodplain overlap, wildfire zone overlap.
- **Auth:** None. **Rate limits:** standard AGO.
- **Reliability: B** — national in coverage, but each state contributes on its own cadence. Use it as a screening backstop, then confirm with the state's own live system (§2).

**Gaps:**
- Not real-time; a release opened last month in Florida will not appear.
- No document-level records (closure letters, corrective action plans).
- Historic (closed pre-1998) tanks are inconsistently represented across states.

---

### 1.5 EPA ECHO (Enforcement and Compliance History Online)

**Purpose:** Enforcement, inspection, and violation history across CAA, CWA, RCRA, and SDWA — the "has this facility been in trouble?" layer.

- **Docs:** https://echo.epa.gov/tools/web-services
- **Core services:**
  - `get_facilities` — search/filter, returns `QID` for pagination.
  - `get_qid` — paginate results by QID (QIDs expire ~30 min).
  - `get_facility_info` — detail per facility.
  - `get_download` — CSV bulk of a QID.
  - `get_map` — thumbnail.
  - Program-specific: `air_rest_services`, `water_rest_services`, `dfr_rest_services` (Detailed Facility Report), `cwa_rest_services`.
- **Base URLs:**
  - All-data facility search: `https://echodata.epa.gov/echo/echo_rest_services.get_facilities`
  - Air: `https://echodata.epa.gov/echo/air_rest_services.get_facilities`
  - Water: `https://echodata.epa.gov/echo/cwa_rest_services.get_facilities`
  - RCRA: `https://echodata.epa.gov/echo/rcra_rest_services.get_facilities`
  - DFR: `https://echodata.epa.gov/echo/dfr_rest_services.get_dfr`
- **Spatial parameters:** `p_c1_lat`, `p_c1_long`, `p_c2_lat`, `p_c2_long` (bounding box), or `p_lat`, `p_long`, `p_sr` (search radius, miles — default 1, up to 20).
- **Example radius query:**
  ```
  https://echodata.epa.gov/echo/echo_rest_services.get_facilities?output=JSON&p_lat=29.7604&p_long=-95.3698&p_sr=1
  ```
- **Common filters:** `p_st` (state), `p_zip`, `p_ct` (city), `p_cnty` (county), `p_pid` (registry id), `p_fac` (facility name substring), `p_qivm` (quarters in violation), `p_pen` (has formal enforcement), `p_maj` (major facilities only).
- **Auth:** None. **Rate limits:** informal; QID expires 30 min; keep result sets <10k per QID.
- **Reliability: A**.

**Fields worth pulling for a REC signal:** `RegistryID`, `FacName`, `FacStreet`, `FacCity`, `FacState`, `FacZip`, `FacLat`, `FacLong`, `AIRIds`, `NPDESIds`, `RCRAIds`, `SDWAIds`, `TRIIds`, `CurrVioFlag`, `Insp5yr`, `Fea5yr` (formal enforcement actions), `Penalties`, `LastPenaltyAmt`, `QtrsWithNC` (quarters with non-compliance).

**Gaps:**
- ECHO reflects **regulatory compliance**, not actual soil/groundwater contamination. A clean ECHO record is not a clean site.
- State-lead enforcement outside RCRA/CWA/CAA/SDWA (e.g., state-only VCP cleanup) is not in ECHO.
- Attribution lag for state-delegated programs runs 60–180 days.

---

### 1.6 EPA ACRES / Brownfields (assessment & cleanup grants)

**Purpose:** Grant-funded brownfields properties — often, but not always, sites with historic industrial use even when not on Superfund.

- **Envirofacts tables:** `acres.frs_properties`, `acres.frs_contaminants`, `acres.frs_grants`.
- **ArcGIS layer (points):** `https://geopub.epa.gov/arcgis/rest/services/EMEF/efpoints/MapServer/5`
- **AGO item:** `becec3456e414008ab77b26b640331a8`
- **Auth:** None. **Reliability: A** (grantee-reported; refreshed monthly).

**Gaps:**
- ACRES only shows properties touched by an EPA Brownfields grant, TBA, or RLF loan. **Vast numbers of state-VCP brownfields do not appear.** State VCP registries (below) are the essential complement.
- Contaminant list is grantee-reported; may be incomplete.

---

## 2. State UST / LUST Databases

Most states publish tank rosters and leak/release incidents through either **ArcGIS REST** (ESRI feature/map services) or **Socrata SODA** (JSON with SoQL). Federal UST regulation is delegated to states, so state DBs are the primary source; EPA UST Finder (§1.4) is a rollup.

### 2.1 Texas — TCEQ (LPST, PST, Dry Cleaner, VCP)

- **LPST Points (Leaking Petroleum Storage Tank) — TCEQ ArcGIS Hub:**
  - Hub page: https://gis-tceq.opendata.arcgis.com/maps/TCEQ::lpst-points/about
  - FeatureServer query pattern (locate via the Hub "API" tab):
    ```
    {base}/FeatureServer/0/query?where=1=1&geometry={lon},{lat}&geometryType=esriGeometryPoint&distance=1609&units=esriSRUnitMeter&inSR=4326&outFields=*&f=json
    ```
- **Fields:** `LPST_ID`, `SITE_NAME`, `PHYSICAL_ADDRESS`, `CITY`, `COUNTY`, `ZIP`, `LATITUDE`, `LONGITUDE`, `REPORTED_DATE`, `CLOSURE_DATE`, `CLOSURE_STATUS`.
- **PST (active tanks):** searchable via TCEQ CID/registered dry cleaner lookups; a GIS feature service is not always exposed publicly for active PST inventory.
- **Dry Cleaner Registry:** https://www.tceq.texas.gov/agency/data/lookup-data/drycleaners-data-records.html — CSV/lookup available, not a REST API (scrapeable).
- **Auth:** None. **Reliability: A** for LPST layer.
- **Gaps:** Pre-1990 tank removals often absent; some rural closures missing lat/lon.

### 2.2 California — SWRCB GeoTracker (LUST + Cleanup Sites)

- **ArcGIS folder:** https://gispublic.waterboards.ca.gov/portalserver/rest/services/Geotracker
- **Portal REST root:** `https://gispublic.waterboards.ca.gov/portalserver/rest/services/Geotracker/{Service}/MapServer/{layerId}/query`
- **Also:** Bulk downloadable text files at `https://geotracker.waterboards.ca.gov/data_download` — updated nightly; often more current than any REST endpoint.
- **Coverage:** LUST cases, DoD, Land Disposal, Military Cleanup, SLIC (Spills, Leaks, Investigations, and Cleanups), Cleanup Program Sites, Permitted USTs.
- **Auth:** None for public data. **Reliability: A**.
- **Gaps:** ESI-submitted lab data requires deeper joins; DTSC EnviroStor (§below) is the parallel source for hazardous-waste cleanup that GeoTracker misses.

### 2.3 California — DTSC EnviroStor (parallel to GeoTracker)

- **Data portal:** https://www.envirostor.dtsc.ca.gov/public/data_download.asp
- **GIS services:** DTSC publishes ArcGIS feature layers via `https://services1.arcgis.com/pRnRZQdMd53CvTPU/arcgis/rest/services/` (search "EnviroStor").
- **Best combined use:** Query both GeoTracker (water) and EnviroStor (DTSC hazardous waste) for California — they cover overlapping-but-different case populations.

### 2.4 Florida — FDEP Contamination Locator Map

- **Base MapServer:** `https://ca.dep.state.fl.us/arcgis/rest/services/Map_Direct/Environment/MapServer`
- **Cleanup sites layer (all programs):** `.../MapServer/1`
- **Query example:**
  ```
  https://ca.dep.state.fl.us/arcgis/rest/services/Map_Direct/Environment/MapServer/1/query?geometry={lon},{lat}&geometryType=esriGeometryPoint&inSR=4326&distance=1609&units=esriSRUnitMeter&outFields=*&f=json
  ```
- **Program codes in `PROGRAM_TYPE`:** Brownfield, CERCLA, Drycleaning, Petroleum, RCRA, State Funded, Superfund, Waste Cleanup.
- **Open data hub:** https://mapdirect-fdep.opendata.arcgis.com/
- **Auth:** None. **Reliability: A**. FDEP is one of the cleaner state ArcGIS deployments.

### 2.5 Arizona — ADEQ

- **UST/LUST legacy search:** https://legacy.azdeq.gov/databases/lustsearch_drupal.html (HTML — no REST)
- **UST Place Facilities ArcGIS Hub:** https://hub.arcgis.com/datasets/ADEQ::ust-place-facilities — Hub-hosted FeatureServer with standard query pattern.
- **LUST mapper:** http://gisweb.azdeq.gov/arcgis/emaps/?topic=assessed (viewer; underlying services enumerable at `http://gisweb.azdeq.gov/arcgis/rest/services/`).
- **Auth:** None. **Reliability: B** — data regenerated daily but ADEQ documents its services as "general reference only." Cross-check with EPA UST Finder.

### 2.6 Georgia — EPD (HSI, UST)

- **Georgia Community Mapping Tool:** https://experience.arcgis.com/experience/056d171fd64241fabbffeb189f8fb7c8 — the underlying FeatureServers can be discovered from the network tab; primary layers include HSI (Hazardous Site Inventory) and UST facilities.
- **HSI download (PDF, updated July annually):** https://epd.georgia.gov/document/document/hsi-list-countypdf/download — the annual PDF is authoritative; the ArcGIS layer is a derivative.
- **ArcGIS layer (HSI 2019 version cached):** https://www.arcgis.com/home/item.html?id=ed5339dca8e94002b5e183901a727fd7
- **Auth:** None. **Reliability: B** — the ArcGIS service lags the annual PDF by weeks-to-months. If HSI status is dispositive, parse the PDF.

### 2.7 Colorado — OPS (petroleum) + CDPHE

- **OPS Petroleum maps portal:** https://ops.colorado.gov/Petroleum/maps — links interactive viewer to underlying COSTIS storage-tank database.
- **CDPHE Open Data Hub:** https://data-cdphe.opendata.arcgis.com/ (Hub-standard REST via each dataset's FeatureServer).
- **Auth:** None. **Reliability: B** — OPS does not publish an official REST endpoint; the viewer's backing services are discoverable but not formally documented. Fallback to EPA UST Finder for programmatic Colorado UST access.

### 2.8 Nevada — NDEP

- **Site Cleanup Database:** https://ndep.nv.gov/environmental-cleanup/site-cleanup-program/site-cleanup-database — HTML export, refreshed quarterly, **not a REST API**.
- **UST Finder (ArcGIS item — also used as Nevada layer):** `88d551abd342485582c5ca4aac6ac0d6`
- **Reliability: C** — quarterly HTML export is the primary channel. For programmatic Nevada UST/LUST, EPA UST Finder is the practical answer; anything more current requires HTML scraping.

### 2.9 North Carolina — NCDEQ

- **UST Incidents FeatureServer:** discoverable from https://data-ncdenr.opendata.arcgis.com/datasets/ust-incidents (Hub-standard `/FeatureServer/0/query`).
- **RUST (Regulated USTs) layer:** https://data-ncdenr.opendata.arcgis.com/datasets/rust
- **AST Incidents layer:** https://data-ncdenr.opendata.arcgis.com/datasets/79aa8ce8bb344a698fc47d74255b9898_0
- **Fields:** incident number, discovery date, site name/address, incident media (soil/groundwater/free product), status, closure date.
- **Auth:** None. **Reliability: A** — NCDEQ Hub is well-maintained.

### 2.10 Cross-cutting pattern (all states above)

Every ArcGIS Hub-hosted dataset exposes a `FeatureServer/{layerId}/query` endpoint that accepts:
- `where` (SQL WHERE clause on attribute)
- `geometry` + `geometryType` + `inSR` + `distance` + `units` (spatial filter)
- `outFields=*` and `f=json` (or `geojson`)
- `resultOffset` + `resultRecordCount` for pagination (default page = 1000; hard cap usually 2000)

For Socrata (many state open-data portals, notably data.ny.gov, data.wa.gov, healthdata.gov, cityofchicago):
- `https://{host}/resource/{4x4}.json?$where=within_circle(location, {lat}, {lon}, {meters})&$limit=1000`
- App token recommended (`X-App-Token` header) — anonymous allowed but throttled.

---

## 3. Historical-Use Risk Signals

### 3.1 Dry cleaners (a top REC generator — PCE/TCE)

- **Best programmatic source per state:** the state dry cleaner registry (e.g., Texas TCEQ, Indiana IDEM, Wisconsin DNR). Coverage is inconsistent — some states dropped or never had statutory registries.
- **National fallback:** join EPA FRS `naics_codes` for **NAICS 812320 (Drycleaning and Laundry Services except Coin-Operated)** and **812310 (Coin-Operated Laundries and Drycleaners)** against `frs.frs_naics_codes`.
- **Reliability: C.** State registries capture only *registered/active* cleaners; historical operators (the ones that matter — 1960s–1980s PCE releases) are typically **not** in any modern registry.

**Honest gap:** The single highest-value dry-cleaner data source — the property's actual **history** of who occupied it — is not resolvable from any free API. The Phase I environmental professional uses city directories (Polk, Cole, Haines), historic aerials, and Sanborn maps to establish this. Automated screening can flag current NAICS-812320 tenants and current-registered cleaners nearby, but cannot substitute for chain-of-title historical use research.

### 3.2 Sanborn Fire Insurance Maps

- **Free source:** Library of Congress digital collection — https://www.loc.gov/collections/sanborn-maps/
- **LoC API:** items are addressable as JSON via `?fo=json` on any LoC URL. Full collection metadata: `https://www.loc.gov/collections/sanborn-maps/?fo=json&c=100&sp={page}`.
- **Coverage:** All public-domain Sanborn sheets (pre-1923) are digitized; 1923–1930 sheets are partially online; **post-1930 sheets are NOT free** — they are proprietary to Environmental Data Resources (EDR) / LightBox and cost several hundred dollars per property lookup.
- **Programmatic use:** possible for pre-1923 coverage via LoC API — but you must geocode sheet metadata to a bounding box, then OCR/visually inspect the imagery. There is **no free API that returns "was there a gas station at this parcel in 1948."**
- **Reliability: D** for automated screening. Best treated as a documentary reference that a human ESA professional will consult manually. Do not attempt to make Sanborn a rules-engine feature.

### 3.3 Historical aerials

- **USGS EarthExplorer** (https://earthexplorer.usgs.gov/) — free imagery, includes DOQ, NAIP, and historic aerial photography catalog. Machine-to-machine access via the USGS M2M API (registered account required, no fee).
- **NAIP (National Agriculture Imagery Program):** free, 2003–present, ~1m resolution. Older historical (1930s–1990s) available for many counties.
- **Reliability: B** for automated OCR/change-detection; **A** for human review.

### 3.4 City directory / occupancy history

- No free national API exists. Ancestry, EDR, and paid state-archive scrapes are the professional sources. This is a known gap for any free automated screener. Flag it in the deliverable to users.

---

## 4. FEMA — Flood Hazard

### 4.1 National Flood Hazard Layer (NFHL) — ArcGIS REST

- **MapServer:** `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer`
- **FeatureServer (AGO-hosted, monthly refresh):** `https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/FEMA_National_Flood_Hazard_Layer/FeatureServer`
- **Key layers:**
  - `28` — Flood Hazard Zones (polygons; A, AE, AO, AH, X, VE, D, etc.)
  - `27` — Flood Hazard Boundaries
  - `14` — Base Flood Elevations
  - `16` — LOMRs (Letters of Map Revision)
  - `2` — Political Jurisdictions (community IDs)
  - `3` — S_FIRM_Pan (FIRM Panel index)

**Point-in-polygon query (flood zone at a lat/lon):**
```
https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query
?geometry={lon},{lat}
&geometryType=esriGeometryPoint
&inSR=4326
&spatialRel=esriSpatialRelIntersects
&outFields=FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE
&returnGeometry=false
&f=json
```

- **Fields for CRE screening:** `FLD_ZONE` (A/AE/X/VE/D/…), `SFHA_TF` (Special Flood Hazard Area boolean), `STATIC_BFE` (base flood elevation ft), `ZONE_SUBTY`.
- **Auth:** None. **Rate limits:** informal (be polite).
- **Reliability: A.** Refreshed monthly with LOMR incorporation.

**Gaps:**
- NFHL only covers areas with a FIRM. Non-mapped rural areas return null; treat as "not evaluated" not "no risk."
- FEMA maps understate pluvial (surface-water) and future-climate risk; First Street Foundation risk scores (freemium, not truly free API) are the popular supplement.
- LOMA (Letter of Map Amendment) status for a specific structure is not on the raw layer — you must query `Layer 15` (LOMA) with the parcel geometry.

---

## 5. Wildfire, Earthquake, and Other Physical Hazards

### 5.1 Wildfire Hazard Potential (WHP) — USFS

- **2023 MapServer:** `https://apps.fs.usda.gov/arcx/rest/services/RDW_Wildfire/RMRS_WildfireHazardPotential_2023/MapServer`
- **Latest ImageServer (composite):** `https://apps.fs.usda.gov/fsgisx01/rest/services/RDW_Wildfire/RMRS_WRC_WildfireHazardPotential/ImageServer`
- **Point sampling pattern (ImageServer identify):**
  ```
  {base}/identify?geometry={lon},{lat}&geometryType=esriGeometryPoint&sr=4326&returnGeometry=false&f=json
  ```
- **Values:** 270m raster → classes 1 (very low) to 5 (very high) plus non-burnable and water sentinels.
- **Auth:** None. **Reliability: A.** Update cadence ~annual.

**Companion layer — Wildfire Risk to Communities (Conditional Risk to Potential Structures):**
- `https://apps.fs.usda.gov/fsgisx01/rest/services/RDW_Wildfire/RMRS_WRC_ConditionalRiskToPotentialStructures/ImageServer`

**Gaps:**
- WHP is landscape-scale (270m). Individual parcel risk depends on defensible space, structure hardening, and micro-topography — none of which WHP knows.
- State-level equivalents (CAL FIRE FHSZ, TX A&M Forest Service) are more actionable for specific state due diligence.

### 5.2 Earthquake / Seismic Design — USGS

- **Design Maps Web Services (ASCE 7, IBC, ASCE 41, AASHTO):**
  - Base: `https://earthquake.usgs.gov/ws/designmaps/`
  - Example (ASCE 7-22, site class default): `https://earthquake.usgs.gov/ws/designmaps/asce7-22.json?latitude=34.05&longitude=-118.25&riskCategory=II&siteClass=D&title=Site`
- **Returns:** `SS`, `S1`, `SMS`, `SM1`, `SDS`, `SD1` design spectral values.
- **National Seismic Hazard Model API:** `https://earthquake.usgs.gov/nshmp/` — hazard curves, disaggregation, response spectra.
- **Earthquake Catalog (FDSN):** `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&latitude={lat}&longitude={lon}&maxradiuskm=50&minmagnitude=2.5`
- **Auth:** None. **Reliability: A.**

**Gaps:**
- Design maps assume a default site class if not supplied — real Phase I / geotech uses a measured Vs30 or borehole. Screener should flag "requires site-specific geotech" not "safe."
- Fault-proximity is not directly returned; use USGS Quaternary Faults GIS (`https://earthquake.usgs.gov/hazards/qfaults/`) for fault-in-radius queries.

### 5.3 Additional useful free layers

| Hazard | Source | Endpoint / access |
|---|---|---|
| Landslide susceptibility | USGS | `https://www.sciencebase.gov/catalog/` — search "landslide susceptibility"; also state DOTs. |
| Radon zones | EPA | `https://www.epa.gov/radon/find-information-about-local-radon-zones-and-state-contact-information` — zone shapefile, county-level. |
| Naturally occurring asbestos | USGS | https://mrdata.usgs.gov/asbestos/ — feature service, mostly Western US. |
| Karst / sinkhole | USGS | Karst map via ScienceBase; state geological surveys have finer data. |
| Coastal Barrier Resources (CBRA) | USFWS | ArcGIS feature service — flood insurance ineligibility zones. |
| Historical hazardous liquid pipeline | PHMSA | https://www.phmsa.dot.gov/data-and-statistics — CSV bulk; NPMS public viewer redacts precise locations. |

---

## 6. What This Automated Stack Cannot Replace

A licensed Phase I ESA under ASTM E1527-21 delivers several things that **no free API can produce**:

1. **Chain-of-title / owner history** — deeds, tax records for prior owners. Public but not consolidated; requires county recorder access.
2. **Historical use establishment** — Sanborns 1930–present, city directories, historic aerials interpreted by an EP. Free APIs give raw imagery but not the professional narrative.
3. **On-site reconnaissance** — visual identification of stained soil, transformers (PCB), floor drains, ASTs, vent pipes, distressed vegetation. There is no substitute for site walk.
4. **Interviews** — with current/past owners, occupants, and local officials (fire marshal, health dept records).
5. **Vapor Encroachment Screen (ASTM E2600)** — separate standard; requires site-specific geology and plume orientation reasoning.
6. **Regulatory file review** — going to the state agency and pulling paper files for adjacent LUST sites often reveals plume direction, contaminants, and closure conditions that are **not** in any database field.
7. **Non-scope items commonly addressed anyway:** asbestos, lead-based paint, mold, radon, wetlands, endangered species, cultural resources — mostly outside E1527, but often bundled in the actual report.
8. **Data currency for state programs without an API** — e.g., Nevada NDEP releases a quarterly HTML export. If a release opened last month, it will not appear in any free feed until the state next dumps.
9. **Off-site plume migration & vapor intrusion** — depends on hydrogeology, not on the presence of a database record.

**Design implication:** The Python screening engine should produce a **REC-candidate list with confidence bands**, explicitly citing (a) which sources returned hits, (b) which sources were queried and returned null, and (c) which categories of REC risk are structurally uncoverable by free data. Deliver this as a Pre-Phase I Screening memo — never as a substitute for Phase I.

---

## 7. Recommended Query Pipeline (implementation guidance)

Recommended order of operations for a property at `(lat, lon)`:

1. **Geocode & parcel resolution** — Census Geocoder (`https://geocoding.geo.census.gov/geocoder/`) for address→coord; county GIS parcels for precise geometry.
2. **Federal spatial sweep** (parallel):
   - FRS ArcGIS radius query (0.25 / 0.5 / 1 mile rings)
   - EPA UST Finder radius query
   - ECHO `get_facilities` radius query
   - SEMS via `frs_rest_services.get_facilities?pgm_sys_acrnm=SEMS`
   - ACRES ArcGIS layer
3. **Deep-lookup per hit** — for each `registry_id`, hit Envirofacts `rcra_handler`, `sems.envirofacts_actions`, `tri.tri_reporting_form`, ECHO DFR.
4. **State overlay** — dispatch to the correct state module (§2) using the state code; capture LUST/LPST, VCP/HSI, and dry cleaner registry.
5. **Physical hazards** — FEMA NFHL point-in-polygon, USFS WHP point-sample, USGS design maps, USGS earthquake catalog radius.
6. **Historical signal (best-effort)** — flag current NAICS 812310/812320 in radius; note absence of historic data as an explicit uncoverable-gap.
7. **Score & format** — distance-weighted risk bands, per-source citations, structured JSON + human-readable narrative.

**Rate-limit hygiene:** cache per-endpoint responses (address + radius + endpoint hash → 24h TTL); throttle to <5 req/sec per host; use `If-Modified-Since` where the server supports it; run all federal queries in parallel behind an `asyncio` gather.

---

## 8. Source Register

| Source | URL | Auth | Reliability |
|---|---|---|---|
| EPA Envirofacts | https://www.epa.gov/enviro/envirofacts-data-service-api | None | A |
| EPA FRS ArcGIS | https://geodata.epa.gov/arcgis/rest/services/OEI/FRS_INTERESTS/MapServer | None | A |
| EPA FRS REST | https://www.epa.gov/frs/frs-rest-services | None | A |
| EPA UST Finder | https://www.epa.gov/ust/ust-finder | None | B |
| EPA ECHO | https://echo.epa.gov/tools/web-services | None | A |
| EPA ACRES | https://geopub.epa.gov/arcgis/rest/services/EMEF/efpoints/MapServer/5 | None | A |
| TX TCEQ LPST | https://gis-tceq.opendata.arcgis.com/maps/TCEQ::lpst-points | None | A |
| TX TCEQ Dry Cleaner | https://www.tceq.texas.gov/agency/data/lookup-data/drycleaners-data-records.html | None | C |
| CA GeoTracker | https://gispublic.waterboards.ca.gov/portalserver/rest/services/Geotracker | None | A |
| CA EnviroStor | https://www.envirostor.dtsc.ca.gov/public/data_download.asp | None | A |
| FL FDEP CLM | https://ca.dep.state.fl.us/arcgis/rest/services/Map_Direct/Environment/MapServer | None | A |
| AZ ADEQ | https://legacy.azdeq.gov/databases/lustsearch_drupal.html + Hub | None | B |
| GA EPD HSI | https://epd.georgia.gov/about-us/land-protection-branch/hazardous-waste/hazardous-site-inventory | None | B |
| CO OPS | https://ops.colorado.gov/Petroleum/maps | None | B |
| NV NDEP | https://ndep.nv.gov/environmental-cleanup/site-cleanup-program/site-cleanup-database | None | C |
| NC DEQ | https://data-ncdenr.opendata.arcgis.com/ | None | A |
| Sanborn (LoC) | https://www.loc.gov/collections/sanborn-maps/ | None | D (auto) / B (manual) |
| USGS EarthExplorer | https://earthexplorer.usgs.gov/ | Free account for M2M | B |
| FEMA NFHL | https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer | None | A |
| USFS WHP | https://apps.fs.usda.gov/arcx/rest/services/RDW_Wildfire/RMRS_WildfireHazardPotential_2023/MapServer | None | A |
| USGS Design Maps | https://earthquake.usgs.gov/ws/designmaps/ | None | A |
| USGS FDSN Earthquake Catalog | https://earthquake.usgs.gov/fdsnws/event/1/ | None | A |

---

**Save target:** `docs/reference/ENVIRONMENTAL_SOURCES.md`