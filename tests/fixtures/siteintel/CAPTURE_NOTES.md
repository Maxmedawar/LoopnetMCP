# Site-intelligence fixture capture notes

Captured on 2026-07-14 (America/Los_Angeles). The WARN parser test reads the
local Texas JSON sample; no test contacts the network.

## Texas WARN JSON sample

- Publisher: Texas Workforce Commission through Texas Open Data.
- Dataset metadata: `https://data.texas.gov/api/views/8w53-c4f6`
- Data endpoint: `https://data.texas.gov/resource/8w53-c4f6.json`
- Captured request: `https://data.texas.gov/resource/8w53-c4f6.json?$select=notice_date%2Cjob_site_name%2Ccounty_name%2Ctotal_layoff_number%2Clayoff_date%2Ccity_name&$where=notice_date%20%3E%3D%20%272026-01-01T00%3A00%3A00.000%27&$order=notice_date%20DESC&$limit=5`
- Fixture: `tx_warn_2026_sample.json`; five rows were retained verbatim, with
  whitespace-only formatting changes, from the JSON response.

TWC also links a current XLSX workbook from
`https://www.twc.texas.gov/data-reports/warn-notice` at
`https://www.twc.texas.gov/sites/default/files/oei/docs/warn-act-listings-2026-twc.xlsx`.
The Socrata JSON dataset is used by the live adapter because it is structured,
programmatically reachable, and compatible with `FetchClient.get_json`.

## California WARN workbook

- Publisher: California Employment Development Department (EDD).
- Landing page: `https://edd.ca.gov/en/jobs_and_training/layoff_services_warn`
- Exact download URL: `https://edd.ca.gov/siteassets/files/jobs_and_training/warn/warn_report1.xlsx`
- Fixture: `ca_warn_report_current.xlsx`
- Capture SHA-256: `d2633e5a486808207f9e7d52a969acee5f766cf08fd97cec6465bccc6235a95d`
- Response format at capture: XLSX
- Server `Last-Modified` observed at capture: `Fri, 10 Jul 2026 14:40:02 GMT`

The raw workbook is retained to document and allow future regression work
against the real EDD format. The shared `FetchClient` exposes text and JSON, not
binary response bytes. Consequently the current implementation deliberately
reports live California access as `UNSUPPORTED`; it does not pretend that
decoding an XLSX response as text is safe. Historical EDD reports are PDF and
are not substituted for the current structured feed.
