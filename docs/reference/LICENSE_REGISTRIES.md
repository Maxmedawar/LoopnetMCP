<!-- Researched by a background agent 2026-07-14; endpoints spot-verified by the agent, re-verify before building on any single endpoint. -->

# License & Registration Verification Sources — US CRE Counterparties

*Reference document for the Python vetting engine. Scope: free, programmatically-accessible primary sources for verifying licenses, registrations, and disciplinary history of brokers, mortgage originators, contractors, appraisers, property managers, and investment advisers involved in US commercial real estate.*

*Last researched: 2026-07-14.*

---

## 0. TL;DR — Access Tier Summary

| Source | Coverage | Access | Free? | Discipline |
|---|---|---|---|---|
| FINRA BrokerCheck | Broker-dealers, reps (CRD) | Undocumented public JSON API | Yes | Yes |
| SEC IAPD / Form ADV | RIAs, IARs, ERAs | Bulk CSV/ZIP downloads | Yes | Yes (Part 1A DRPs) |
| ASC National Registry | Appraisers, AMCs | Web query + Excel export + daily-change reports | Yes | Yes |
| NMLS Consumer Access | Mortgage MLOs, cos. | Web lookup only (free); B2B API paid | Partial | Yes |
| TX TREC | Real estate | Daily Socrata + flat-file downloads | Yes | Yes |
| CA DRE | Real estate | Free Excel roster downloads + HTML lookup | Yes | Yes (separate) |
| FL DBPR (incl. CILB) | Real estate + contractors | Weekly ASCII/CSV bulk + web lookup | Yes | Yes |
| AZ ADRE | Real estate | Free CSV list downloads | Yes | Yes |
| GA GREC | Real estate | Web form only | Yes (view) | Yes (in profile) |
| CO DORA | Real estate + all pro licenses | Socrata SODA API (data.colorado.gov) | Yes | Partial |
| NV RED | Real estate | Monthly Excel roster + web lookup | Yes | Web only |
| NC NCREC | Real estate | Web lookup (free) + paid data subscription | Partial | Web only |
| CA CSLB | Contractors | Free bulk file (LICENSE MASTER) + web lookup | Yes | Yes |
| TX TDLR | Trade contractors | Socrata SODA API (data.texas.gov) | Yes | Yes |

---

## 1. NMLS Consumer Access — Mortgage Originators & Companies

**Regulator:** Conference of State Bank Supervisors (CSBS) / State Regulatory Registry LLC. Covers all state-licensed mortgage loan originators (MLOs), lenders, brokers, servicers, and (via federal registrants) depository-institution MLOs under the SAFE Act.

- **Public web lookup (free):** `https://www.nmlsconsumeraccess.org/` (search by NMLS ID, name, city/state/zip). Individual and company records include license status, employment history, and regulatory actions.
- **Programmatic API (free):** **None.** No public API is exposed to the general public. NMLS explicitly states data is provided "in a look-up format."
- **B2B Subscription Service (paid):** CSBS operates the "NMLS Consumer Access Subscription Service" for compliance firms, lenders, investors. Provides bulk data feeds. Requires application/contract with CSBS — not free.
  - Reference: `https://mortgage.nationwidelicensingsystem.org/about/sitepages/NMLSB2BAccess.aspx`
- **Scraping:** The site uses JavaScript and rate-limits aggressively. Terms of Use prohibit "automated means" for scraping. **Do not scrape from a production vetting engine** — it is a legal/reputational risk with a regulator-operated site. Third-party Apify/RELD scrapers exist but sit outside the terms of use.

**Recommended pattern for the engine:**
- Accept an NMLS ID as input; store the deep-link URL `https://www.nmlsconsumeraccess.org/EntityDetails.aspx/INDIVIDUAL/{nmlsId}` (or `/COMPANY/{nmlsId}`) as evidence of manual verification.
- For automated verification: (a) budget for the paid B2B subscription, or (b) fall back to state-level license databases where the mortgage originator's state license number is known.
- Cross-reference: state DFI / banking-division rosters (many are separately downloadable — outside this doc's scope but a fallback path).

**Fields available (web):** NMLS Unique ID, legal name, other trade names, employment history (with dates), state licenses (with status), federal registrations, regulatory actions, disclosure explanations.

**Reliability:** Very high — this is the authoritative federal-state registry mandated by the SAFE Act. The gap is the absence of a free API.

**Honest gap:** No free programmatic path. Any Python engine relying solely on free tools will need either (a) manual link-out for MLO checks, or (b) scraping under Terms-of-Use risk, or (c) paid B2B feed.

---

## 2. FINRA BrokerCheck — Broker-Dealers & Registered Representatives

**Regulator:** Financial Industry Regulatory Authority (FINRA). Covers Series-7/63/65/66/etc. licensed persons and broker-dealer firms. Relevant to CRE for placement agents, private-placement offering intermediaries, and any counterparty raising capital via a broker-dealer.

**Two distinct FINRA API surfaces — do not confuse them:**

### 2a. Public BrokerCheck JSON API (undocumented, free, no auth)

The consumer BrokerCheck site (`https://brokercheck.finra.org/`) is backed by a public Elasticsearch/Solr-style JSON API at `api.brokercheck.finra.org`. It is undocumented by FINRA but has been stable for years and is used by every third-party BrokerCheck scraper and community wrapper.

- **Base:** `https://api.brokercheck.finra.org`
- **Individual search endpoint:** `GET /search/individual`
- **Firm search endpoint:** `GET /search/firm`
- **Common query parameters (observed):**
  - `query=` — free-text name or CRD
  - `hl=true` — highlighting
  - `includePrevious=true` — include formerly-registered persons (essential for full history)
  - `nrows=` — page size (default ~12)
  - `start=` or `r=25` — pagination offset
  - `state=` — 2-letter state
  - `sort=score+desc`
  - `wt=json` — response format
  - `json.wrf=` — JSONP callback (omit for straight JSON)
- **Example (individual by name in NY):** `https://api.brokercheck.finra.org/search/individual?hl=true&includePrevious=true&nrows=12&query=John+Smith&r=25&sort=score+desc&state=NY&wt=json`
- **Detail:** individual detail can be fetched from the summary hit, then `https://files.brokercheck.finra.org/individual/individual_{CRD}.pdf` for the full report PDF.

**Terms of use:** The BrokerCheck Terms of Use at `https://brokercheck.finra.org/terms-and-conditions` govern use. Read before wiring into production. Data is explicitly "made publicly available" but usage restrictions exist (no bulk redistribution as a competing product, etc.). For a vetting engine that queries per-counterparty, this is fine; a bulk crawl of all 600K reps would not be.

**Reliability:** High. This API is what BrokerCheck.finra.org itself uses. It has been de facto stable for 5+ years. Risk: FINRA could formalize/change/authenticate it at any time — code defensively (log HTTP status, fail closed with clear error).

**Fields returned (individual):**
- CRD number, first/middle/last names, other names used
- Current employer firm(s) with location
- Total years experience, previous registrations
- Exams passed (S7, S63, S65, S66, etc.)
- State registrations held
- Disclosure count (regulatory, customer disputes, criminal, civil, financial, terminations)
- Detail records under `content.previousemployments` and `content.disclosures` when full record is fetched via CRD detail endpoint

### 2b. FINRA Developer Center Query API (documented, OAuth, paid tiers)

- **URL:** `https://developer.finra.org/`
- **Endpoints:** `GET /metadata`, `GET/POST /data`, `GET /datasets`, `GET /partitions` on `https://api.finra.org`
- **Auth:** OAuth 2.0 client-credentials via `https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token`
- **Free credentials tier:** "Public Credentials" (public market data) and "Mock Credentials." "Registered Individual Search" and "Firm Profile" are available as datasets.
- **Documentation:** `https://developer.finra.org/docs/api-explorer/query_api-registration-registered_individual_search`
- **Verdict:** Overkill for CRE counterparty vetting compared to 2a, and the individual/firm datasets on the Query API contain similar fields to BrokerCheck. Use 2a unless you already need Query API for market data.

### 2c. FINRA Disciplinary Actions

- **Web tool:** `https://www.finra.org/rules-guidance/oversight-enforcement/finra-disciplinary-actions-online` — searchable, 2005–present
- **Monthly PDF summaries:** `https://www.finra.org/rules-guidance/oversight-enforcement/disciplinary-actions` (one PDF per month; e.g., `disciplinary-actions-august-2025.pdf`)
- **Note:** Disciplinary content also surfaces in a person's BrokerCheck disclosures. In practice, hitting BrokerCheck by CRD is sufficient — the monthly PDFs are useful for a periodic sweep of "new actions this month."
- **OpenSanctions mirror:** `https://www.opensanctions.org/datasets/us_finra_actions/` — daily-refreshed enforcement dataset (secondary; use FINRA as primary).

---

## 3. SEC IAPD / Form ADV — Investment Advisers

**Regulator:** SEC (for RIAs and ERAs) and state securities regulators (state-registered IAs). Relevant to CRE for real-estate-focused private funds, sponsor GPs registered as RIAs, and any counterparty holding themselves out as an investment adviser.

### 3a. Investment Adviser Public Disclosure (IAPD) — Firm & Individual Profiles

- **Public web lookup:** `https://adviserinfo.sec.gov/` — searchable by firm name, individual name, CRD/IARD number
- **Firm summary URL pattern:** `https://adviserinfo.sec.gov/firm/summary/{firmCRD}`
- **Individual summary URL pattern:** `https://adviserinfo.sec.gov/individual/summary/{indCRD}`
- **PDF reports:** `https://reports.adviserinfo.sec.gov/reports/individual/individual_{CRD}.pdf`

### 3b. Search API (undocumented, free)

Similar to BrokerCheck's pattern, IAPD is backed by a public JSON API at `api.adviserinfo.sec.gov`. Same operator (FINRA operates IARD for the SEC). Endpoint patterns mirror BrokerCheck:
- `GET https://api.adviserinfo.sec.gov/search/individual?query=…`
- `GET https://api.adviserinfo.sec.gov/search/firm?query=…`

Parameters: `query`, `hl`, `includePrevious`, `nrows`, `r`, `sort`, `state`, `wt=json`. Undocumented; same reliability caveats as §2a.

### 3c. Form ADV Bulk Downloads (documented, free) — The workhorse

**Primary landing page:** `https://www.sec.gov/foia-services/frequently-requested-documents/form-adv-data` and `https://adviserinfo.sec.gov/compilation`

**What you get:**
- **Historical Form ADV Part 1A + Schedules + DRPs (Disclosure Reporting Pages) for SEC-registered IAs** — quarterly CSV files, coverage from Jan 2001 through most recent quarter. Contains firm identifiers (SEC #, CRD, CIK, LEI), AUM, employees, client types, service types, and — critically — full disciplinary DRP records (regulatory actions, criminal, civil, bankruptcy, disciplinary).
- **Exempt Reporting Advisers (ERAs)** — same, Dec 2011 → present.
- **Form ADV-W (withdrawals)** — CSV.
- **Investment Adviser Statistics Reports** — SEC-published aggregated summaries.
- **Publishing lag:** ~1 month after quarter close.
- **Newer:** From 2025 onward, monthly/current compilation is on `https://adviserinfo.sec.gov/compilation`.

**File structure:** ZIPs containing multiple CSVs — one per Form ADV section (Part 1A base, Schedule A/B/D, DRPs). To rebuild an adviser record you join on CRD.

**Reliability:** Very high — this is the SEC's own bulk feed of the same data underlying IAPD.

**Recommended engine pattern:**
- Ingest quarterly ZIPs into a local table keyed on `Filing_ID`/`CRD`. Refresh monthly.
- For real-time single-record lookup, hit `api.adviserinfo.sec.gov` by CRD (§3b).
- Flag any DRP records as disciplinary; count active regulatory actions in the disclosure schedule.

---

## 4. State Real-Estate Boards

### 4a. Texas — TREC (Texas Real Estate Commission)

- **Web lookup:** `https://www.trec.texas.gov/apps/license-holder-search/`
- **Bulk downloads (free, daily):** `https://www.trec.texas.gov/public/high-value-data-sets`
  - Four datasets: (1) Broker & Sales Agent License Holders, (2) Inspectors, (3) Easement/ROW Agents, (4) Applications.
  - Hosted on **data.texas.gov (Socrata)** — reachable via Socrata SODA API.
  - Format: tab-delimited, newline-separated flat files; also queryable as JSON/CSV via SODA.
  - Update: daily.
- **Instructions:** `https://www.trec.texas.gov/public/trec-public-information-files-instructions`
- **Disciplinary:** Individual records include license status; separate disciplinary action orders are published under `https://www.trec.texas.gov/agency-information/enforcement/disciplinary-actions`.
- **Reliability:** Very high. TREC is one of the most developer-friendly state real-estate boards.

### 4b. California — DRE (Department of Real Estate)

- **Web lookup:** `https://www2.dre.ca.gov/PublicASAP/` (query by license ID → single HTTPS GET returns full HTML result — parseable).
- **Bulk downloads (free):** `https://dre.ca.gov/Licensees/ExamineeLicenseeListDataFiles.html` — Excel files of examinees and licensees, downloadable free.
- **API:** None official. The HTML lookup accepts `LICENSE_ID` as a GET parameter and returns a static, session-free page (safe to scrape at low volume for single-record verification).
- **Disciplinary:** DRE publishes separate enforcement action lists (monthly bulletins). Not merged into the licensee data files.
- **Reliability:** High. The Excel bulk feed is the primary programmatic path; per-record HTML fetch works for real-time checks.

### 4c. Florida — DBPR (Department of Business & Professional Regulation) — Real Estate Commission + CILB

Both real estate (FREC) and contractors (CILB) run on the same DBPR licensing platform.

- **Web lookup:** `https://www.myfloridalicense.com/wl11.asp` and `https://www2.myfloridalicense.com/portalsearches/VerifyLicensee`
- **Bulk downloads (free, weekly):**
  - Real Estate Commission public records: `https://www2.myfloridalicense.com/real-estate-commission/public-records/`
  - Construction Industry public records: `https://www2.myfloridalicense.com/construction-industry/public-records/`
  - Global bulk portal: `https://licenseesearch.fldfs.com/BulkDownload`
  - Instant public records: `https://www2.myfloridalicense.com/instant-public-records/`
- **Format:** ASCII text, quote-comma-delimited (readme at `https://www2.myfloridalicense.com/sto/documents/readme.pdf`). Refreshed weekly.
- **Disciplinary:** DBPR publishes disciplinary orders separately; individual records show discipline status.
- **Reliability:** High. Weekly refresh is the trade-off vs. web lookup being real-time.

### 4d. Arizona — ADRE (Department of Real Estate)

- **Web lookup:** `https://services.azre.gov/publicdatabase/SearchIndividuals.aspx` and `.../SearchEntities.aspx`
- **Bulk downloads (free):** `https://services.azre.gov/PdbWeb/List/ViewLists` — comma-delimited CSVs with header row. Downloadable filtered lists (by license type, status, etc.) and full rosters.
- **API:** None official. Bulk CSVs are the programmatic path.
- **Disciplinary:** Individual license records surface disciplinary actions and employment history; ADRE also publishes separate enforcement action notices.
- **Reliability:** High. Straightforward CSV pipeline.

### 4e. Georgia — GREC (Real Estate Commission)

- **Web lookup:** `https://ata.grec.state.ga.us/Account/Search` (name + license number required)
- **Bulk API/download:** **None free from GREC.** Certified license history requires a fillable order form (paid).
- **Disciplinary:** Surfaced in individual records; no bulk feed.
- **Reliability:** Web-form only. This is a gap.

**Recommended engine pattern:** Store the ATA lookup URL as an evidence link for manual verification; scrape with rate limits only for high-priority counterparties (site is public but no formal API allowance).

### 4f. Colorado — DORA / Division of Real Estate

- **Web lookup (real estate specifically):** `https://apps2.colorado.gov/dre/licensing/lookup/licenselookup.aspx`
- **General DORA lookup:** `https://apps2.colorado.gov/dora/licensing/lookup/licenselookup.aspx`
- **Programmatic (free):** **Colorado Information Marketplace** — Socrata SODA API at `https://data.colorado.gov/`. Key datasets:
  - **Licensed Real Estate Professionals in Colorado**: dataset ID **`4zse-6bnw`** → API endpoint `https://data.colorado.gov/resource/4zse-6bnw.json`
  - **Professional and Occupational Licenses in Colorado**: dataset ID **`7s5z-vewr`** → covers all DORA license types
  - **License Types lookup**: **`349y-twqi`**
- **Update:** Nightly per CIM documentation.
- **SODA API:** Public, unauthenticated. Register a Socrata app token for higher throughput. Standard SODA `$where`, `$select`, `$limit`, `$offset` filters apply.
- **Disciplinary:** License status field indicates active/expired/revoked; separate DORA enforcement actions live outside the CIM feed.
- **Reliability:** Excellent — a real API, well-maintained.

### 4g. Nevada — RED (Real Estate Division)

- **Web lookup:** `https://red.prod.secure.nv.gov/Lookup/LicenseLookup.aspx`
- **Bulk downloads (free, monthly):** `https://red.nv.gov/Content/Administration/Active_Licensee_Lists/` — Excel spreadsheets, updated monthly.
  - Direct examples:
    - `https://red.nv.gov/uploadedFiles/rednvgov/Content/Administration/Public_Records/NRED-ACTIVE-BROKERS.xlsx`
    - `https://red.nv.gov/uploadedFiles/rednvgov/Content/Administration/Public_Records/NRED-ACTIVE-BROKER-SALESPERSONS.xlsx`
- **API:** None official.
- **Disciplinary:** Web-lookup only per individual; separate disciplinary decisions PDFs on RED site.
- **Reliability:** Adequate. Monthly staleness on rosters + real-time single-record via web lookup.

### 4h. North Carolina — NCREC

- **Web lookup:** `https://license.ncrec.gov/ncrec/oecgi3.exe/O4W_LIC_SEARCH_NEW`
- **Bulk data:** Available only via **paid data-subscription service** — order form at `https://www.ncrec.gov/orderform`. Contact `datasubscriptions@ncrec.gov`. Files include licensee list, corporation list, trade-names list, affiliations list.
- **Free API:** **None.**
- **Disciplinary:** Web-lookup individual records include discipline; NCREC also publishes disciplinary bulletins.
- **Reliability:** Web-lookup only for free use. This is a gap unless paid feed is purchased.

---

## 5. State Contractor Boards

Contractor licensing is state-level and highly heterogeneous. Key points for CRE (developers, GCs, subs):

### 5a. California — CSLB (Contractors State License Board)

- **Web lookup:** `https://www.cslb.ca.gov/onlineservices/checklicenseII/checklicense.aspx`
- **Public Data Portal:** `https://www.cslb.ca.gov/onlineservices/dataportal/`
  - **Master List of California Licensed Contractors:** `https://www.cslb.ca.gov/onlineservices/dataportal/ContractorList` — full file broken into three parts: License Master, Workers' Comp, Personnel File. 700K+ records.
  - **List by Classification and County:** `https://www.cslb.ca.gov/onlineservices/dataportal/ListByCounty`
- **Format:** Fixed-width and delimited text (NOT Excel). Documentation with the download.
- **Fields:** License #, business name, address, phone, license status, issue/expiration dates, classifications (A, B, C-XX), bond info, workers' comp status.
- **Disciplinary:** License-status flags (Suspended, Revoked) appear in the master file. Separate disciplinary orders/citation history are surfaced in the web lookup but not fully in the bulk file. Full disciplinary detail may require FOIA / Data Services Unit request.
- **Cost:** Free.
- **Reliability:** Excellent. CSLB is one of the best contractor sources in the country.

### 5b. Texas — TDLR

Texas does not license general contractors statewide, but licenses trades (HVAC, electrical, plumbing, elevator, etc.). CRE due diligence should still hit TDLR for subs.

- **Web lookup:** `https://www.tdlr.texas.gov/verify.htm`
- **Bulk / API:** **Socrata dataset on data.texas.gov**
  - Dataset: **TDLR - All Licenses**, ID **`7358-krk7`**
  - API: `https://data.texas.gov/resource/7358-krk7.json`
  - Docs: `https://dev.socrata.com/foundry/data.texas.gov/7358-krk7`
  - Fields: license type, license number, business county, business name, address, phone, status, geocoded lat/lon
  - Updated: daily
- **Disciplinary:** Individual license records + separate order downloads on tdlr.texas.gov.
- **Reliability:** Excellent — proper Socrata API.

### 5c. Florida — DBPR CILB (Construction Industry Licensing Board)

Same platform as §4c above. Contractor records via:
- Web: `https://www.myfloridalicense.com/wl11.asp` (choose "Construction Industry")
- Bulk: `https://www2.myfloridalicense.com/construction-industry/public-records/`
- Format: ASCII quote-comma-delimited, weekly.
- Only **state-certified contractors** with status **Current, Active** or **Probation, Active** may work statewide. State-registered contractors are limited to specific counties.

### 5d. Other target states — contractor status

- **Arizona ROC (Registrar of Contractors):** Separate agency from ADRE. Search at `https://azroc.my.site.com/AZRoc/s/contractor-search`. Downloadable data lists via ROC public records; no free API.
- **Georgia:** Residential/GC licensing via Secretary of State → Professional Licensing Boards. Search: `https://verify.sos.ga.gov/Verification`. Web-only.
- **Colorado:** State does not license general contractors — municipal-level only. DORA covers electricians, plumbers via §4f Socrata feed (dataset `7s5z-vewr` includes all professions).
- **Nevada:** NSCB (Nevada State Contractors Board). Search: `https://app.nvcontractorsboard.com/Clients/NVSCB/Public/ContractorLicenseSearch/ContractorLicenseSearch.aspx`. No free bulk API.
- **North Carolina:** NCLBGC (Licensing Board for General Contractors). Search: `https://portal.nclbgc.org/Public/Search`. Web-only.

**Honest gap:** Outside CA and TX, most state contractor boards are web-form-only. Automated multi-state contractor verification requires either scraping (with per-site risk) or a commercial aggregator (Cobalt Intelligence, API Processing) — outside "free" scope.

---

## 6. Appraisers — ASC National Registry (Federal)

**Regulator:** Appraisal Subcommittee (ASC) of the FFIEC. Congressionally-mandated single national registry of state-credentialed appraisers and Appraisal Management Companies (AMCs). Every appraiser doing FRT (federally-related transaction) work — most CRE appraisals — must be on this registry.

- **Landing page:** `https://www.asc.gov/national-registries`
- **Appraiser advanced search:** `https://www.asc.gov/appraiser/advanced` — search by name, license, state, credential type; results are exportable to Excel.
- **AMC advanced search:** `https://www.asc.gov/amc`
- **Bulk data (free):**
  - A ~35 MB text file with ~310K appraiser records is available for daily download from ASC (documented publicly; specific URL retrievable from the "Public Records" section — `https://www.asc.gov/resources/public-records`).
  - You may also download all filtered search results to Excel from the advanced search UI.
- **Daily change reports:** `https://www.asc.gov/national-registries/notices` — daily PDF/list emails of new registrations, expirations, and **disciplinary actions**.
- **State-by-state active credentials report:** `https://asc.gov/national-registries/appraiser-credentials`
- **Compliance review findings (state-agency-level):** `https://www.asc.gov/states/appraiser-findings`

**Fields:** State, credential number, full name, credential type (Certified General, Certified Residential, Licensed, Trainee), status (Active/Inactive/Expired/Suspended/Revoked/Voluntarily Surrendered), effective and expiration dates, company/employer, business address, contact info.

**Disciplinary:** Registry status flags (Suspended, Revoked, Voluntarily Surrendered) directly reflect state disciplinary actions. Daily notice emails include the discipline-driven changes. This is one of the cleanest disciplinary trails available across US professional licensure.

**Reliability:** Very high. Federal, monthly-refreshed-from-states, purpose-built for public verification.

**Recommended engine pattern:**
- Nightly download of the daily-change file to keep the local table current.
- Real-time single-record verification: HTTPS GET against advanced-search results endpoint (parse the returned HTML/Excel export).

**Honest gap:** No official REST/JSON API — data is served as web search + downloadable files. For high-volume automation, scrape the search-results page or maintain a mirror from the daily download.

---

## 7. Property Managers

**There is no federal property-manager registry.** State treatment varies:

- Most states require a real-estate broker license to manage residential rental property for others → they fall under §4 above.
- Community Association Managers (CAMs) are separately licensed in FL, GA, NV, CA (CID managers), CO (historically — sunsetted), IL, VA, DC. In FL and NV they surface via DBPR / RED main license portals (already covered above).
- Some states (e.g., MT, OR, SD) have specific property-manager licenses issued by their real-estate divisions — accessible via the same state real-estate portals as §4.

**Recommended engine pattern:** Treat PM verification as a real-estate broker check via the counterparty's state (§4), and if the state has a separate PM/CAM license type, filter the same state feed on that license type.

**Honest gap:** No single federal source; multi-state coverage requires the state-by-state coverage in §4.

---

## 8. Disciplinary / Enforcement — Cross-Reference

| Source | Discipline surface | Data structure |
|---|---|---|
| FINRA BrokerCheck | Full disclosures per individual + firm; monthly PDF summaries | JSON API returns `disclosures[]` per record |
| SEC Form ADV | Disclosure Reporting Pages (DRPs) in quarterly bulk CSVs | Separate DRP tables in the ZIP |
| ASC National Registry | Status flags (Suspended/Revoked/Surrendered) + daily change notices | In-record status + daily reports |
| NMLS Consumer Access | "Regulatory Actions" section in individual/company profile | Web-only (or paid B2B) |
| TX TREC | License status + separate disciplinary orders list | Field in bulk file + separate page |
| CA DRE | License status + separate enforcement bulletins | Excel roster + separate bulletins |
| FL DBPR | License status + separate discipline records | Weekly bulk file + separate lookup |
| AZ ADRE | Discipline shown in individual record + separate notices | CSV roster + separate notices |
| GA GREC | Web-only per record | Web-form only |
| CO DORA | Status field in Socrata feed; enforcement PDFs separate | SODA field + separate PDFs |
| NV RED | Web-only per record | Web + monthly Excel roster |
| NC NCREC | Web-lookup per record; paid data feed for bulk | Web + paid subscription |
| CA CSLB | Status flag in master file; full history in web lookup | Bulk file + separate discipline history |
| TX TDLR | Status field in Socrata feed; orders published separately | SODA + separate PDFs |

**Practical rule for the engine:** Two-stage discipline check per counterparty:
1. Pull the current license status from the appropriate source (bulk table or per-record fetch). Status ≠ "Active" is an immediate red flag.
2. Do a text/keyword search against the source's disciplinary action listings (FINRA monthly PDFs, ASC daily notices, state enforcement bulletins) keyed on name + license #.

---

## 9. Commercial-CRE-Specific Notes

- **Placement agents in a syndication / Reg D offering** → verify via **FINRA BrokerCheck** (§2). Ask for CRD number in intake.
- **Sponsor GP that acts as an RIA** → verify via **SEC IAPD Form ADV** (§3). Ask for CRD/SEC number.
- **Mortgage brokers on a CRE bridge/perm loan** → the SAFE Act mostly regulates residential-mortgage MLOs. **Commercial-only mortgage brokers may not be in NMLS.** Fall back to state DFI/banking-division license (varies by state — e.g., CA CFL, NY MB, TX SML for regulated CRE lenders).
- **General contractor / development team** → CA/FL license verifications are strongest; TX has no state GC license; most other states are web-only.
- **Appraiser on an FRT appraisal** → ASC National Registry is authoritative and sufficient (§6).
- **Property manager on multifamily / commercial asset** → treat as broker license under state RE portal (§4), unless the property is a HOA/condo where a CAM license applies.

---

## 10. Recommended Python-Engine Source Priority

For a "verify licenses, registrations, and disciplinary history before engagement" engine, wire sources in this order (highest ROI first):

1. **FINRA BrokerCheck JSON** (`api.brokercheck.finra.org/search/{individual,firm}`) — no auth, real-time, disclosures included.
2. **SEC IAPD JSON** (`api.adviserinfo.sec.gov/search/{individual,firm}`) + quarterly Form ADV ZIP ingestion — no auth, real-time + local bulk table.
3. **ASC National Registry** — daily bulk file ingestion; per-record advanced-search fallback.
4. **State real-estate boards** with real APIs / clean bulk feeds:
   - CO DORA via Socrata (`4zse-6bnw`, `7s5z-vewr`) — nightly refresh.
   - TX TREC via data.texas.gov / TREC High Value Data Sets — daily.
   - AZ ADRE via `PdbWeb/List/ViewLists` — periodic CSV pull.
   - FL DBPR via `licenseesearch.fldfs.com/BulkDownload` — weekly.
   - CA DRE via Excel roster + per-record HTML lookup.
   - NV RED via monthly Excel roster + per-record web lookup.
5. **State contractor boards** with real APIs:
   - CA CSLB Master List (weekly bulk pull).
   - TX TDLR via Socrata `7358-krk7`.
6. **Web-form-only sources** (GA GREC, NC NCREC, NV NSCB, most other state boards) → link-out to human verification with the deep URL stored in the counterparty record; scrape only for prioritized deals under rate limits.
7. **NMLS Consumer Access** → link-out only unless paid B2B feed is procured.

---

## 11. Honest Gaps & Risks

- **No free unified API for MLOs.** NMLS Consumer Access is web-only free; API is paid. This is the single largest gap for a CRE engine that touches financing.
- **BrokerCheck and IAPD JSON APIs are undocumented.** They have been stable for 5+ years but could be changed or authenticated at any time. Code defensively; fail closed with clear error.
- **State real-estate boards are inconsistent.** GA (no free bulk), NC (paid only), NV (monthly staleness), many mid-size states not covered here rely on web forms.
- **General-contractor coverage outside CA/TX is patchy.** Multi-state contractor verification without paid aggregators requires per-state scraping.
- **Disciplinary "current status" ≠ historical discipline.** A revoked-then-reinstated license shows "Active" today; a full check requires reading the disclosure/DRP history from FINRA, SEC, or state enforcement bulletins.
- **Property manager licensing is fragmented.** No single national source; falls under state real-estate broker licenses in most states.
- **Data latency varies.** BrokerCheck/IAPD are real-time; ASC and TX TREC are daily; FL DBPR is weekly; SEC ADV bulk is quarterly; NV RED is monthly. Treat status as authoritative only up to the source's refresh cadence.
- **Terms of Use matter.** BrokerCheck, IAPD, NMLS, and most state boards have ToS restrictions on bulk redistribution and automated access. Per-counterparty lookups in a vetting workflow are generally within permitted use; scraping-and-republishing is not.

---

## 12. Source Links (Consolidated)

**Federal / cross-state:**
- NMLS Consumer Access: `https://www.nmlsconsumeraccess.org/`
- NMLS B2B Subscription info: `https://mortgage.nationwidelicensingsystem.org/about/sitepages/NMLSB2BAccess.aspx`
- FINRA BrokerCheck: `https://brokercheck.finra.org/` and API `https://api.brokercheck.finra.org/`
- FINRA Developer Center: `https://developer.finra.org/`
- FINRA Disciplinary Actions Online: `https://www.finra.org/rules-guidance/oversight-enforcement/finra-disciplinary-actions-online`
- FINRA Monthly Disciplinary Actions: `https://www.finra.org/rules-guidance/oversight-enforcement/disciplinary-actions`
- SEC IAPD: `https://adviserinfo.sec.gov/`
- SEC Form ADV Data: `https://www.sec.gov/foia-services/frequently-requested-documents/form-adv-data`
- SEC Investment Adviser Data compilation: `https://adviserinfo.sec.gov/compilation`
- SEC IA information: `https://www.sec.gov/data-research/sec-markets-data/information-about-registered-investment-advisers-exempt-reporting-advisers`
- ASC National Registries: `https://www.asc.gov/national-registries`
- ASC Appraiser search: `https://www.asc.gov/appraiser/advanced`
- ASC AMC search: `https://www.asc.gov/amc`
- ASC Public Records: `https://www.asc.gov/resources/public-records`
- ASC Daily Notices: `https://www.asc.gov/national-registries/notices`

**State real estate:**
- TX TREC High Value Data Sets: `https://www.trec.texas.gov/public/high-value-data-sets`
- TX TREC search: `https://www.trec.texas.gov/apps/license-holder-search/`
- CA DRE licensee files: `https://dre.ca.gov/Licensees/ExamineeLicenseeListDataFiles.html`
- CA DRE lookup: `https://www2.dre.ca.gov/PublicASAP/`
- FL DBPR RE public records: `https://www2.myfloridalicense.com/real-estate-commission/public-records/`
- FL DBPR bulk downloads: `https://licenseesearch.fldfs.com/BulkDownload`
- FL DBPR license search: `https://www.myfloridalicense.com/wl11.asp`
- AZ ADRE public database: `https://services.azre.gov/publicdatabase/`
- AZ ADRE downloads: `https://services.azre.gov/PdbWeb/List/ViewLists`
- GA GREC ATA lookup: `https://ata.grec.state.ga.us/`
- CO DORA lookup: `https://apps2.colorado.gov/dre/licensing/lookup/licenselookup.aspx`
- CO Licensed Real Estate Professionals dataset: `https://data.colorado.gov/Regulations/Licensed-Real-Estate-Professionals-in-Colorado/4zse-6bnw`
- CO Professional and Occupational Licenses dataset: `https://data.colorado.gov/Regulations/Professional-and-Occupational-Licenses-in-Colorado/7s5z-vewr`
- NV RED lookup: `https://red.prod.secure.nv.gov/Lookup/LicenseLookup.aspx`
- NV RED active licensee lists: `https://red.nv.gov/Content/Administration/Active_Licensee_Lists/`
- NC NCREC search: `https://license.ncrec.gov/ncrec/oecgi3.exe/O4W_LIC_SEARCH_NEW`
- NC NCREC data subscription order form: `https://www.ncrec.gov/orderform`

**State contractors:**
- CA CSLB check license: `https://www.cslb.ca.gov/onlineservices/checklicenseII/checklicense.aspx`
- CA CSLB Public Data Portal: `https://www.cslb.ca.gov/onlineservices/dataportal/`
- CA CSLB Master List: `https://www.cslb.ca.gov/onlineservices/dataportal/ContractorList`
- TX TDLR license search: `https://www.tdlr.texas.gov/verify.htm`
- TX TDLR All Licenses (Socrata): `https://data.texas.gov/dataset/TDLR-All-Licenses/7358-krk7`
- TX TDLR Socrata docs: `https://dev.socrata.com/foundry/data.texas.gov/7358-krk7`
- FL CILB public records: `https://www2.myfloridalicense.com/construction-industry/public-records/`
- AZ ROC search: `https://azroc.my.site.com/AZRoc/s/contractor-search`
- GA SOS Verify: `https://verify.sos.ga.gov/Verification`
- NV NSCB search: `https://app.nvcontractorsboard.com/Clients/NVSCB/Public/ContractorLicenseSearch/ContractorLicenseSearch.aspx`
- NC NCLBGC search: `https://portal.nclbgc.org/Public/Search`