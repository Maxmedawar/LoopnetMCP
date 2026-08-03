# MedawarCRE Final Launch Program Status

This is the visible issue ledger and command-evidence index for the final
launch program. A claim becomes green only after the relevant command evidence
and an independent audit are recorded here.

## Frozen founder decisions

- Customer browser experience: connection-only
- Customer portal or dashboard: absent
- Operations Console: internal-only
- Combined opportunity list: internal-only, approved, provenance-preserving
- Cross-customer model learning: disabled and deferred
- Human identity: provider abstraction with Clerk as the preferred production
  adapter
- Authorization authority: MedawarCRE live server state

## Repository baseline

| Item | Recorded truth |
| --- | --- |
| Control branch | `feature/final-launch-control` |
| Control base | `f36ef46fe44a21a50967227b476a771030c24816` |
| Strongest pushed spine | `feature/stripe-skool-sync` at `f36ef46` |
| OAuth phase | `49cab683f0c5effd47f70d1a476a4b7c3de2bb22` |
| Admin and JV APIs | `7cbb1ac1aed6e059ef7282ca0f6e45d4846eac07` |
| Provider sync base | `e647a48` plus replay-authority repair `f36ef46` |
| Customer portal commits | `8a44d4c`, `13abbf5`, local-only, superseded for product routing |
| PostgreSQL | No implementation or dependency exists at inventory time |
| SQLite dbops salvage | 4,513 uncommitted lines in the protected dbops worktree; not production DR |
| Protected backup | SHA-256 `8361a9db47bb4ea5276f009309cdc8b0401c0272dc4ae6b8711d9f4b0e489095`, read-only integrity `ok` |

## Issue ledger

| Status | Work item | Evidence needed to turn green |
| --- | --- | --- |
| 🟢 | No-customer-portal decision locked | Founder goal and this contract |
| 🟢 | Internal combined opportunity list approved | Founder goal and this contract |
| 🟢 | Global learning deferred | Founder goal and this contract |
| 🟢 | Secure multi-tenant foundation reported and recovered | Commit archaeology; independent integrated verification still tracked below |
| 🟢 | Exact profile counts re-derived | Local 103, national 115, full 274, JV 170 from the live matrix |
| 🟢 | OAuth live authority implementation recovered | Commit `49cab68`; 1,521-test verification and focused strict lifecycle verification |
| 🟢 | OAuth SSE warning ownership explained | Upstream-only reproduction plus JSON-response application path with owned-task teardown test |
| 🟢 | Provider replay-authority repair recovered | Pushed commit `f36ef46` |
| 🟢 | Admin and JV APIs recovered | Commit `7cbb1ac` |
| 🟡 | OAuth launch certification | Returned-result and dual territory enforcement are implemented with permanent protocol regressions. Access, opposite-order, repository, packaging, lifecycle, capability-count, compile, and diff gates are green. Exact-hash freeze and two fresh independent approvals remain before commit |
| 🟡 | Production PostgreSQL and recovery | Schema, tenant isolation, migrations, pooling, backup, actual clean restore, rollback, recovery audit |
| 🔴 | Launch integration branch | Deliberate integration after independently verified OAuth and PostgreSQL commits |
| 🔴 | Clerk identity and connection flow | Fake provider first, Clerk adapter, connection-only browser routes, end-to-end OAuth client connection |
| 🔴 | Internal Operations Console | React, Reicon, role enforcement, browser authorization matrix, anti-slop audit |
| 🔴 | Search and deal persistence | Tenant records, evidence, score versions, object-ID isolation, privacy behavior |
| 🔴 | Combined opportunity index | Server-side deduplication, provenance, staff-only access, pagination and conflict tests |
| 🔴 | Scheduled saved searches | Idempotent queue, current entitlement and territory checks, audit, internal status |
| 🔴 | Stripe test integration | Signed webhook, replay and ordering, mappings, lifecycle, reconciliation, active-session effects |
| 🔴 | Skool reconciliation | Proven current-state source or explicit restrictive fallback, manual revoke, uncertainty state |
| 🔴 | Privacy and retention | Notice, export, correction, deletion, retention, processor propagation, audit |
| 🔴 | Source-rights controls | Machine-readable ledger and default-deny cloud source gate |
| 🔴 | Private staging | Reproducible package, TLS, migrations, workers, monitoring, backup and restore exercise, rollback |
| 🔴 | Integrated security audit | Fresh full-system attack pass, repairs, second audit, no critical or high open finding |
| 🔴 | Production-readiness packet | Exact hashes, artifacts, evidence, limitations, credentials, rollback, first-user plan |
| 🔴 | Public production cutover | Explicit founder approval after the readiness packet only |

No row may be deleted. Superseded work stays visible with its disposition.

## Preserved red evidence

### Returned-result territory leakage

A real FastMCP call through the production access middleware used a Local Scout
grant restricted to Texas. The request was `search_properties(location="Houston,
TX")`. The tool returned both a Houston record and `200 Ocean Dr, Miami, FL
33139`; middleware released both records. This proves the current system checks
territory arguments but not returned property records.

Required repair: a capability-declared, fail-closed post-result policy that
validates all returned property locations for territory-limited profiles without
silently trusting a result shape it cannot inspect.

### Mixed asyncio lifecycle leak

OAuth-focused strict lifecycle tests pass. A separate mixed selection can leave
pytest-asyncio's replacement loop and socketpair descriptors open when a sync
entitlement test invokes `asyncio.run()` after an async test. The repair is to
convert those entitlement tests to native async tests, not to filter warnings or
cancel unrelated tasks.

## Current OAuth certification checkpoint 2026-08-03

The control repository's
`/Users/maxmedawar/LoopnetMCP-final-launch/docs/launch/PROGRAM_STATUS.md` is the
canonical program ledger. This phase-local copy records the current OAuth
evidence so it cannot be mistaken for the earlier 1,521-test baseline.

OAuth is dirty, uncommitted, and yellow. The locked real FastMCP/middleware
priority selection passes all 24 cross-profile/collection escapes, all 48 exact
state/city/ZIP escapes, all 48 required address/city/state malformations, and
all four real Crexi-shaped empty-location cases. Result contracts are closed
and unknown fields are recursively forbidden. Six nested provider-shaped
GeoRef carrier aliases are permanent denials across both restricted profiles.

Pinned Census place and tract relationships now make same-name city resolution
fail closed. Assigned postal localities without Census place identities are
accepted only when an exact assigned city/ZIP pair and the ZIP's authoritative
county set converge. Permanent Bronx 10451 and Staten Island 10301 controls
cover both ZIP-level GeoRefs and county-contained rent comparables. Ambiguous
Burbank, Chevy Chase, Pewaukee, and Superior requests remain pre-execution
denials.

The checked-in authority artifacts rebuild byte-for-byte from the pinned
official inputs: 52,565 ZCTA/place rows at SHA-256
`8a0d94a3743873cf2b9761c3aa79fa7884703903611f6f9163b758ddb0822476`
and 254,935 county/place/ZCTA/tract/CBSA rows at SHA-256
`ec28297f8f5bd29328c1cd696a7d007c3d80f083def465de3e6b017393e6b6e8`.

All builder verification gates are green on the current dirty tree. One exact
stable candidate hash and two new independent reviews against that unchanged
hash remain mandatory.

## Verified command evidence

| Date | Scope | Command summary | Result |
| --- | --- | --- | --- |
| 2026-08-01 | Capability matrix | Import production server and compare registered names to matrix | 274 registered, 274 classified, no missing or stale entries |
| 2026-08-01 | Profiles | Recompute allowed tools from the live matrix | Local 103; National 115; Full 274; JV 170 |
| 2026-08-01 | OAuth full suite | `PYTHONPATH=<oauth>/src ... python -m pytest -p no:cacheprovider -q` | 1,521 passed; one categorized third-party Authlib deprecation |
| 2026-08-01 | OAuth strict lifecycle | OAuth test file with asyncio debug and lifecycle warnings promoted | 35 passed; no pending application task |
| 2026-08-01 | OAuth focused repetition | Real HTTP initialize and cleanup selection repeated ten times | 20 total focused passes; no pending-task stderr |
| 2026-08-03 | OAuth locked priority protocol gate | Approved Python 3.11.15; permanent 24 + 48 escape matrices, 48 required-field malformations, and four real Crexi empty-location cases through FastMCP and installed middleware | 125 passed; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth focused post-authority corpus | Typed results, place/GeoRef authority, release/portfolio regressions, store-backed workflows, and expanded market/ambiguity controls | 1,047 + 302 + 808 + 86 + 169 passed; no focused failure; OAuth remains yellow |
| 2026-08-03 | OAuth authority reproducibility | Rebuild both Census artifacts from pinned official inputs to temporary files, `cmp` against checked-in files, and run `gzip -t` | Byte-identical; 52,565 and 254,935 rows; SHA-256 `8a0d94a3...` and `ec28297f...` |
| 2026-08-03 | OAuth complete access gate | Approved Python 3.11.15; isolated runtime root; cache provider disabled | 2,484 passed in 26.74 seconds; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth opposite-order stability gates | The four previously unstable territory modules run in both collection orders from separate isolated runtime roots | 2,283 passed in 31.14 seconds and 2,283 passed in 24.32 seconds; one categorized third-party Authlib deprecation per process |
| 2026-08-03 | OAuth repository-wide gate | Approved Python 3.11.15; isolated runtime root; cache provider disabled | 4,195 passed in 86.50 seconds; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth strict lifecycle gate | Asyncio debug enabled; ResourceWarning, RuntimeWarning, and pytest unraisable warnings promoted to errors | 4 passed in 1.56 seconds; no owned lifecycle warning; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth packaging and static gates | Compile source, diff whitespace, package-data-only manifest review, wheel inspection, authority gzip integrity, release-locked capability counts, and port 8000 check | Green; 274 capabilities; Local 103, National 115, Full 274, JV 170; no port-8000 listener; dependencies and lockfiles unchanged |
| 2026-08-01 | Protected backup | SQLite URI read-only integrity and FK checks | `integrity_check=ok`; zero FK violations; file unchanged |

## Phase evidence template

For each phase, append:

- Worktree, branch, base, and final commit
- Narrow contract and explicit non-scope
- Exact red command and failure
- Files changed
- Focused and regression commands with counts
- Full-suite command with count and warning classification
- Compile, diff, migration, integrity, and security checks
- First independent audit findings
- Repairs and their regression tests
- Second independent audit verdict
- SecondBrain note URI or path and reopen verification
- Residual limitations and the next active phase
