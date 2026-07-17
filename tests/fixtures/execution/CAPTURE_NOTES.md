# Execution contact fixture capture notes

- `tx_sos_search.json` and `tx_sos_detail.json` are trimmed real responses captured
  live on 2026-07-13 from the official Texas Comptroller franchise-tax JSON service.
  The detail response labels its officer rows `SOURCE: SOS` and returns the public
  registered-agent fields surfaced by the Comptroller's Secretary-of-State record view.
- The Arizona, Nevada, Florida, and Georgia public search pages were reached live on
  2026-07-13, but no stable automation endpoint was confirmed: Arizona is session-bound,
  Nevada presented Incapsula, and Florida/Georgia presented Cloudflare. They remain
  configured, explicitly logged coverage gaps rather than unverified scrapers.
