# Verify-registry fixture capture notes

Captured on **2026-07-14** for offline parser/normalizer tests. Tests never make
live network requests; every `FetchClient.get_json` call is mocked.

- `brokercheck_individual_smith_ny.json`
  - URL: <https://api.brokercheck.finra.org/search/individual?hl=true&includePrevious=true&nrows=12&query=John%20Smith&r=25&sort=score%20desc&state=NY&wt=json>
  - The live response reported 23 hits. The fixture retains two returned hits
    (one with and one without the returned disclosure flag) and removes only
    unrelated hits/highlight blocks to keep the fixture reviewable. Registry
    `_source` values are unchanged.
- `iapd_individual_smith_ny.json`
  - URL: <https://api.adviserinfo.sec.gov/search/individual?query=Smith&state=NY&includePrevious=true&nrows=2&wt=json>
  - The fixture retains both returned `_source` records and removes highlight and
    inner-hit duplication; registry values are unchanged.
- `co_dora_real_estate.json`
  - URL: <https://data.colorado.gov/resource/4zse-6bnw.json?$limit=2>
  - Complete two-record response.
- `tx_tdlr_all_licenses.json`
  - URL: <https://data.texas.gov/resource/7358-krk7.json?$limit=2>
  - Complete two-record response.

The FINRA BrokerCheck and SEC IAPD JSON endpoints are undocumented and therefore
fragile. These captures are parser evidence, not a promise that the endpoints or
schemas will remain stable.
