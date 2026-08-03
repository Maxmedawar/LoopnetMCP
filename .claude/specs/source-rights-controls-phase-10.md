# Phase 10: Source-rights controls

## Objective

Prevent hosted-cloud requests, caching, persistence, and output from using an
automated source unless a server-owned, machine-readable source-rights record
proves that the exact delivery mode is allowed. The control is fail closed at
the network boundary and is independent of ordinary feature/source toggles.

This phase does not approve any source. It records the evidence currently
available, preserves explicit trusted-local experimentation, and blocks every
hosted source whose rights, contract, delivery proof, or fixed operating policy
is incomplete.

## Scope

The implementation covers:

- every automated listing, government-data, parcel, sale-record, zoning,
  permit, environmental, hazard, regulatory-verification, skip-trace, and
  document-URL adapter in `src/cre_mcp`;
- the shared `FetchClient`, its browser fallback and warm-up path, and direct
  network adapters that currently bypass it;
- listing/deal raw payloads, HTTP response caches, and URL-document storage;
- server-owned URL-document rights attestations bound to workspace, actor,
  normalized URL hash, and evidence;
- attribution/disclaimer metadata for conditional sources, while leaving those
  sources disabled until the corresponding proof exists.

Static source links and embedded facts are catalogued separately as `link_only`
or `embedded`, and are not treated as permission for automated retrieval.

## Trust and deployment semantics

`trusted local` means an explicit trusted `TenantContext`, or stdio execution
with no hosted tenant context. It may use a source only when its feature toggle
is explicitly true. No source is enabled by omission.

`hosted cloud` means HTTP transport or any non-trusted tenant context. Hosted
requests must pass the rights gate before cache lookup, warm-up, browser launch,
or socket creation. The gate denies when any of these is true:

- the source ID, host, or URL route is unknown or ambiguous;
- the registry record is missing or invalid;
- hosted use is not explicitly allowed;
- a required contract, subscription, API key, accepted terms record, evidence
  record, attribution/disclaimer delivery proof, rate policy, concurrency
  policy, or retention policy is absent;
- the requested method, cache behavior, raw storage, or raw output exceeds the
  registry allowances.

Feature toggles cannot override rights. Missing configuration never enables a
source. Browser fallback and direct adapters use the same decision.

## Machine-readable registry

The canonical registry is packaged with the application and loaded through a
strict schema. Each resolved source record exposes all of these fields:

- stable source ID;
- source kind (`automated`, `direct_adapter`, `external_document`,
  `link_only`, or `embedded`);
- owner and exact dataset/service;
- retrieval method and URL match rules;
- enabled-by-default flag;
- rights state (`PROHIBITED`, `CONDITIONAL`, `CONTRACT_REQUIRED`, or
  `UNKNOWN`);
- hosted-cloud allowance and trusted-local-only status;
- official evidence URL and verified date;
- signed-contract requirement and required proof items;
- allowances for commercial display, derived analytics, AI/ML use, raw
  retention, and redistribution;
- attribution and disclaimer requirements;
- robots/API-policy status;
- fixed delay, concurrency, memory-cache TTL, persistent-cache TTL, and raw
  retention policy;
- query credential names that must be redacted from cache keys, logs, errors,
  and metadata;
- raw storage and raw output allowances.

Registry loading rejects duplicate source IDs, duplicate or ambiguous match
rules, missing required fields, non-positive concurrency, negative delays or
TTLs, a hosted-enabled record with unknown rights, and any hosted-enabled record
whose proof requirements are incomplete.

The initial registry is intentionally deny-only for hosted automated access.
It inventories the current adapters and known evidence without fabricating a
license or approval.

## Required rights decisions

- **LoopNet:** `PROHIBITED` for hosted automation. Scraping, data extraction,
  and database creation remain blocked without written permission.
- **Crexi:** `PROHIBITED` for hosted automation. Automated scraping and
  unauthorized automated gathering remain blocked.
- **Auction.com:** `PROHIBITED` for hosted automation. Scraping, monitoring,
  copying, and circumvention remain blocked.
- **FRED:** `PROHIBITED` for this delivery. Current terms prohibit ML/AI use
  and storage/cache/archive, so the source cannot be fetched or cached.
- **BLS:** `CONDITIONAL`, blocked. It requires access-date citation, the
  specified quality disclaimer, rate compliance, and proof that every output
  path delivers them.
- **Census:** `CONDITIONAL`, blocked. It requires non-reidentification controls
  and a prominent non-endorsement notice with delivery proof.
- **IRS SOI migration:** `CONDITIONAL`, blocked pending exact dataset-specific
  verification even though federal works are generally reusable.
- **FHFA:** `CONDITIONAL`, blocked until every using application prominently
  delivers the required FHFA non-endorsement notice and fixed call-limit
  controls are proven. Evidence:
  `https://www.fhfa.gov/about/fhfa-policies/api-terms-of-service`.
- **EPA FRS/ECHO:** `CONDITIONAL`, blocked pending dataset-specific
  metadata/license evidence and current api.data.gov credential/rate rules.
  Evidence: `https://www.epa.gov/data/application-programming-interface-api`.
- **HUD USPS crosswalk:** `CONTRACT_REQUIRED`, blocked pending the exact HUD
  sublicense, security conditions, and proprietary-notice delivery proof.
  Evidence: `https://www.huduser.gov/portal/usps/sublicense_agreement.html`.
- **RentCast:** `CONTRACT_REQUIRED`, blocked pending an active subscription and
  API-key evidence, accepted terms, and fixed rate configuration. The registry
  records the described derivative/internal analytics, storage, display,
  resale, and distribution allowances as contract-dependent, not as active
  permission. Evidence: `https://www.rentcast.io/terms-api`.
- **ATTOM:** `CONTRACT_REQUIRED`, blocked pending a product-specific data
  license. Published developer access is evaluation-only absent a data license,
  prohibits database enhancement/distribution, and limits cache to 24 hours.
  Evidence: `https://api.developer.attomdata.com/legal`.
- **Regrid:** `CONTRACT_REQUIRED`, blocked pending an active contract and exact
  permissions for integration, search, use, storage, and output. Evidence:
  `https://regrid.com/terms/api`.
- **Zillow Research ZORI:** `CONDITIONAL`, blocked pending exact research-file
  license evidence and per-page attribution delivery. It is distinct from the
  Zillow Public Data API, whose no-cache/no-retention/no-bulk constraints do not
  silently authorize research downloads. Evidence:
  `https://www.zillow.com/research/data/` and
  `https://www.zillow.com/corporate/terms-of-use/`.
- **All other current automated/direct sources:** `UNKNOWN` or
  `CONTRACT_REQUIRED`, blocked until exact primary evidence or an operative
  contract is recorded and the delivery requirements are proven.

## HTTP, caching, and credential controls

Authorization occurs before cache reads. A cache hit can never bypass rights.
Unknown hosts have no hosted fallback policy. Trusted-local unknown-host use, if
explicitly invoked, receives a conservative nonzero delay and concurrency of
one.

Every authorized hosted source must have a fixed source policy. Source policy,
not a generic host fallback, controls rate, concurrency, and cache/retention.

Cache keys use a normalized, credential-redacted URL plus a hash of a
credential-redacted body. Query/header credentials and configured secret values
must not appear in cache keys, logs, errors, audit metadata, or returned source
metadata. Raw response caching is denied unless the source record explicitly
allows the requested memory/persistent retention.

## Raw payload and output controls

Hosted output may contain normalized fields, provenance, and required
attribution/disclaimer metadata. It may not expose source-native `raw` payloads
unless the registry explicitly allows raw output. Hosted deal persistence may
not store source-native `raw` payloads unless explicitly allowed. The sanitizer
is recursive so nested listings in deals cannot bypass it.

Conditional attribution/disclaimer metadata is present in registry-derived
provenance, but no conditional source is activated until actual output-path
tests prove the required disclosure is always delivered.

## External URL-document attestation

Uploaded local files remain supported under the existing trusted upload path.
An external URL is denied in hosted cloud unless the caller supplies an
attestation ID that resolves in a server-owned store to all of:

- the active workspace ID;
- the active actor/user ID and session ID;
- the SHA-256 hash of the normalized URL;
- an official evidence URL and evidence hash;
- the allowed retrieval/storage/output purposes;
- an unexpired approval created by an authorized administrator.

Tool arguments cannot create or self-assert an attestation. The download guard
runs before the direct HTTP call and redirects are not allowed to escape the
attested source classification. The attestation ID, not its evidence contents,
may be accepted by the ingestion tool.

## Initial RED tests

Before production edits, focused tests must demonstrate the current failures:

1. listing sources are enabled by default;
2. a missing source toggle enables a source;
3. an unknown host receives a zero-delay policy in hosted mode;
4. FRED responses are cacheable/persistent;
5. raw source payloads reach hosted listing/deal output;
6. query credentials appear in a cache key;
7. an unclassified/direct adapter can bypass the rights gate;
8. a hosted external document URL is accepted without an attestation.

The exact RED command and failure count are captured before implementation.

## Acceptance checks

- focused source-rights tests pass;
- related source registry, HTTP, market, truth, deal, and access tests pass;
- full test suite passes;
- package compiles;
- registry inventory has no automated/direct URL adapter absent from the
  source catalog;
- registry schema and no-secret cache/log tests pass;
- untracked files and diff are reviewed;
- staged diff is empty;
- port 8000 ownership is checked without stopping another process;
- no secrets are present in the diff;
- the work stops for fresh audit without staging or committing.

## Non-goals

- no source is contractually approved in this phase;
- no terms are accepted, subscriptions purchased, credentials provisioned, or
  external parties contacted;
- no deployment, push, merge, or commit;
- no UI change. The anti-slop design law remains applicable to future UI work,
  but this phase has no visual surface.
