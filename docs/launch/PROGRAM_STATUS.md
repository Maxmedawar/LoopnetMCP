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
- Production secrets: managed secret store of the deployment platform, injected
  at runtime through least-privilege service identity. A local `.env` is a
  development artifact holding disposable values only, never the production
  source of truth. Recorded 2026-08-06.

## Repository baseline

| Item | Recorded truth |
| --- | --- |
| Control branch | `feature/final-launch-control` |
| Control base | `f36ef46fe44a21a50967227b476a771030c24816` |
| Strongest pushed spine | `feature/stripe-skool-sync` at `f36ef46` |
| OAuth certified phase | `88e3082109f80722e78d0712ed07028f050e015f` |
| OAuth certification candidate | Exact candidate `e96da4b8345099bb1bac64d5af54e397da8e7fcd0aee14d194a3abebfbc5ca65` passed both fresh read-only reviews unchanged and was committed as `88e3082109f80722e78d0712ed07028f050e015f` |
| Admin and JV APIs | `7cbb1ac1aed6e059ef7282ca0f6e45d4846eac07` |
| Provider sync base | `e647a48` plus replay-authority repair `f36ef46` |
| Customer portal commits | `8a44d4c`, `13abbf5`, local-only, superseded for product routing |
| PostgreSQL certified phase | Exact replacement candidate `f68a9a489602ef0b22614e899e5800820c0579e12002afce83c7aaa613f0e9e6` passed both fresh read-only reviews unchanged and was committed as `5089748aaa6f9f726db5801f866a130974d1eb89` |
| Source-rights certified phase | Exact replacement candidate `4c33265f12dec0927fb34a6c344158174ef5bb89f8bda2a2c3363fd873986f04` passed both fresh read-only reviews unchanged and was committed as `3185ccb595cf305f9c69f15ae2730f2d6fa75ee7` |
| Cloud integration phase | `integration/cloud-platform-launch` at `830c914`; certified OAuth, PostgreSQL, source rights, connection-only Clerk, internal Operations, Stripe test, and Skool lifecycle histories integrated; OAuth/JV repair, fail-closed hosted persistence, exact service roles, migration `0002`, and the one-snapshot OAuth authority repository committed; 4,568 repository tests passed. Superseded 2026-08-06: the branch tip is `5452be3` after eighteen further commits through Phase 5J; see the reconciliation below |
| Cloud integration tip | `integration/cloud-platform-launch`. This row was written while the tip was `5452be3`; the commit carrying this row moves it, so read the tip from `git log`, not from here. Migrations `0001`–`0008` and Phases 5–5J are on it |
| Customer MCP surface | Commit `802b16cec823f74fc41cab10cb4de9602d56fea7`; 274 internal capabilities retained, 253 exact actions grouped, 21 MCP capabilities internal-only, all 45 historical IDs reconciled; visible counts Local 8, National 10, Full 20, JV 14 as recorded then. Superseded: JV became 12 at Phase 5G (`49adb9e`) and 11 at the hosted withholding correction 2026-08-06 |
| SQLite dbops salvage | 4,513 uncommitted lines in the protected dbops worktree; not production DR |
| Protected backup | SHA-256 `8361a9db47bb4ea5276f009309cdc8b0401c0272dc4ae6b8711d9f4b0e489095`, read-only integrity `ok` |

## Issue ledger

| Status | Work item | Evidence needed to turn green |
| --- | --- | --- |
| 🟢 | No-customer-portal decision locked | Founder goal and this contract |
| 🟢 | Internal combined opportunity list approved | Founder goal and this contract |
| 🟢 | Global learning deferred | Founder goal and this contract |
| 🟢 | Secure multi-tenant foundation reported and recovered | Commit archaeology; independent integrated verification still tracked below |
| 🟢 | Exact profile counts re-derived | Local 103, national 115, full 274, JV 170 from the live matrix **as recorded then**. Superseded: JV entitlement became 165 at `49adb9e` and 164 at `039cacf`. Local, national, and full are unchanged and still re-derive exactly. Found by a reviewer 2026-08-06, in the same round whose subject was that number |
| 🟢 | OAuth live authority implementation recovered | Commit `49cab68`; 1,521-test verification and focused strict lifecycle verification |
| 🟢 | OAuth SSE warning ownership explained | Upstream-only reproduction plus JSON-response application path with owned-task teardown test |
| 🟢 | Provider replay-authority repair recovered | Pushed commit `f36ef46` |
| 🟢 | Admin and JV APIs recovered | Commit `7cbb1ac` |
| 🟢 | Hosted persistence authority inventory | Every SQLite, JSON, JSONL, and local-blob authority mapped to a PostgreSQL or object-storage seam |
| 🟢 | Superseded portal salvage boundary mapped | Reicon provenance, connection/privacy primitives, and tests isolated from forbidden customer dashboard code |
| 🟢 | OAuth launch certification | Exact candidate `e96da4b...` passed access, opposite-order, repository, packaging, lifecycle, capability-count, compile, and diff gates; two fresh read-only reviewers independently approved the unchanged hash; committed as `88e3082` |
| 🟢 | Production PostgreSQL and recovery | Candidate `2af2a907...` was rejected and repaired. Exact replacement `f68a9a4...` separates direct from inherited ownership; 69 PostgreSQL and 1,839 repository tests passed; two fresh reviewers approved the unchanged hash; committed as `5089748` |
| 🟢 | Launch integration branch | Certified OAuth `88e3082`, PostgreSQL `5089748`, and source rights `3185ccb` integrated as `0b5a87b`; shared enforcement-order regressions repaired; 4,444 repository tests passed |
| 🟢 | Consolidated customer MCP surface | Hosted HTTP uses 20 coherent grouped facades with profile listings Local 8, National 10, Full 20, JV 14 as recorded then, JV now 11 after the hosted withholding correction 2026-08-06; all grouped actions resolve to exact server-owned capability IDs; internal services and 21 internal MCP capabilities remain unexposed; commit `802b16c`; 4,459 repository tests passed |
| 🟢 | Hosted OAuth PostgreSQL authority checkpoint | Exact 1,024-file candidate `2bf5a43d...`, migration checksum `3058382c...`, catalog fingerprint `40f025fc...`, 102 PostgreSQL tests, 4,568 repository tests, local image build and truth-import smoke, final wheel `324f777c...`, and two hash-stable independent approvals; committed as `830c914` |
| 🟡 | Clerk identity and connection flow | Implementation and local gates complete: official Clerk adapter, connection-only React screen, OAuth discovery/DCR/PKCE/revocation, live authority rechecks, and a real hosted MCP call. Phase 5I then closed a first-sign-in takeover: the adapter accepted an unverified Clerk primary email as the join key to a preprovisioned user. Committed as `d68028f` with four enumerated lifecycle flows pinned in `e78d390`. Integrated audit remains scheduled after Stripe and Skool per the founder-approved sequence, and a live Clerk test instance is still an unmet staging gate. This row is yellow for the external gate only; local Clerk engineering is complete and committed and must not be read as red |
| 🟡 | Internal Operations Console | Implementation and local gates complete: separate React control ledger, pinned Reicon provenance, opaque Clerk operator sessions, live staff and JV separation, exact Origin and Host, CSRF, reasoned mutations, provider quarantine, source rights, health, and append-only audit. Integrated security and real-browser staging gates remain scheduled |
| 🟢 | Search and deal persistence | Superseded red. Phase 5F committed `b0947d7` (migration `0007`) and Phase 5G committed `49adb9e` (migration `0008`); both passed their gates and two fresh read-only reviews each. The carried Phase 5G finding — a ledger-backed JV deal-existence oracle — was closed separately in `039cacf`. Residual: privacy and job are the two unported domains, tracked in their own rows |
| 🔴 | Combined opportunity index | Server-side deduplication, provenance, staff-only access, pagination and conflict tests. Next active phase as of 2026-08-06; no contract or implementation exists on this tip |
| 🔴 | Scheduled saved searches | Idempotent queue, current entitlement and territory checks, audit, internal status |
| 🟡 | Stripe test integration | Implementation and local gates complete: test-only credentials and mode enforcement, rotating signed webhooks, durable lifecycle journal, fixed-host GET-only complete-list reconciliation, atomic projection repair, active-session effects, and reasoned operator audit. Representative fixtures still require a real Stripe test-account staging proof; integrated audit remains scheduled after Skool |
| 🟡 | Skool reconciliation | Local gates complete: operator-only supported join tasks, exact member binding without implicit grant, rotating signed relay secrets, payload-free timestamped review receipts, stale and partial uncertainty, restrictive mismatch handling, manual revoke, OAuth invalidation, and internal Console controls. Private staging must prove the configured relay and operator runbook |
| 🔴 | Privacy and retention | Notice, export, correction, deletion, retention, processor propagation, audit |
| 🟢 | Source-rights controls | First replacement `e58c721...` was rejected and repaired. Exact replacement `4c33265...` fails closed on contradictory local/hosted policy and cleanly imports; 164 focused and 1,950 repository tests passed; two fresh reviewers approved the unchanged hash; committed as `3185ccb` |
| 🟡 | Production secret boundary | Phase 5J: every credential field is `SecretStr`, environment injection outranks the optional `.env`, rotation needs no rebuild, a missing secret fails closed, no route discloses a value and no *rendered* message or traceback does (the serialization claim is qualified below: a `ValidationError` still carries the rejected input on `errors()[0]["input"]` and in `.json()`, which nothing in `src/` calls), and `deploy/DEPLOY.md` records exact names and least-privilege consumers. Committed as `5452be3`, which was **red at the tip and mis-recorded**: it shipped 415 lines of production source while claiming none, described a module it actually committed as deleted, broke two fail-closed hosting tests, and left six database credentials out of the runbook. Corrected in the Phase 5J correction below. No provider chosen; a live Clerk network smoke test is an external staging gate |
| 🟢 | Hosted dead-capability withholding | Fifteen capabilities that were entitled, counted, and advertised while every hosted call failed are withheld from the hosted surface and fail closed on a direct call; committed as `a828717` with the contract at `docs/launch/HOSTED_WITHHOLDING_CONTRACT.md`. JV Partner is 11 visible grouped tools and 164 **entitled** capabilities, 11 of which are hosted-withheld and fail closed on a direct call, leaving **102** reachable through those 11 tools. Two earlier versions of this row were wrong: "164 capabilities" without a qualifier, then "160 reachable", which is impossible — it exceeds the 153 ceiling (164 entitled minus 11 entitled-and-withheld) because it counts every capability grouped onto tools JV can see, including ones JV is not entitled to. This row is green; any earlier reading of the withholding work as red is stale |
| 🔴 | Proxy credential reaches a log in trusted-local stdio | `http/browser.py:146` passes `CRE_PROXY_URL` into Chromium argv; `nodriver` logs its launch arguments at INFO into the root sink `server.py:38` installs, so a configured proxy's password prints to the process's own stderr. Found by an independent reviewer 2026-08-06 and traced end to end. Not hosted-reachable — hosted browser navigation fails closed at the source-rights gate — but live in the shipped stdio product. Fixing it means supplying proxy credentials over CDP rather than argv, which is a product change and not part of this correction |
| 🔴 | Private staging | Reproducible package, TLS, migrations, workers, monitoring, backup and restore exercise, rollback |
| 🔴 | Integrated security audit | OAuth consent, public-client, route exposure, request-bound, browser-session, logout, and identity-wide JV findings repaired in `d82e600`; all public HTTP entrypoints fail closed through `5bcd5c0`; exact service roles, migration `0002`, and the one-snapshot OAuth authority repository are committed through `830c914`; PostgreSQL domain repositories, durable atomic admission/audit, jobs/privacy, and deployment correctness remain open blockers |
| 🔴 | Production-readiness packet | Exact hashes, artifacts, evidence, limitations, credentials, rollback, first-user plan |
| 🔴 | Public production cutover | Explicit founder approval after the readiness packet only |

No row may be deleted. Superseded work stays visible with its disposition.

## Ledger reconciliation 2026-08-06

The ledger above was audited against `git log` on `integration/cloud-platform-launch`
rather than against its own prose. Recorded because four rows disagreed with the
committed tree, and a stale row is indistinguishable from an open blocker to a
reader who does not re-derive it.

| Row | Was | Is | Why it moved |
| --- | --- | --- | --- |
| Search and deal persistence | 🔴 | 🟢 | `b0947d7` and `49adb9e` are on the tip with migrations `0007`/`0008`; the row predates both |
| Hosted dead-capability withholding | absent | 🟢 | `a828717` is on the tip; the work was recorded only in a narrative section, so the ledger never showed it |
| Cloud integration phase | `830c914` | tip `5452be3` | eighteen further commits, including all of Phases 5–5J |
| Exact profile counts re-derived | JV 170 | JV 164 | Stale rather than wrong when written; 165 at `49adb9e`, 164 at `039cacf`. Missed by the first pass of this very reconciliation, which looked for rows marked red that were done and not for green rows whose numbers had moved. Found by a reviewer |

All **five** yellow rows, enumerated rather than summarised, because an earlier
version of this paragraph accounted for four and read as complete: Clerk
identity and the production secret boundary are locally complete and committed,
each waiting on one external staging gate; Stripe and Skool wait on
real-provider staging proofs; the **Internal Operations Console** waits on the
integrated security audit and a real-browser staging pass. None is blocked on
local engineering.

All **eight** red rows: combined opportunity index, scheduled saved searches,
privacy and retention, the proxy credential reaching a log in trusted-local
stdio, private staging, integrated security audit, readiness packet, and public
cutover.

Seven of the eight credit no implementation commit. The **integrated security
audit** row is the exception: it credits `d82e600`, `5bcd5c0`, and `830c914`,
all ancestors of this tip and all real implementation commits, and is red
because the audit has not been *run* against the current tree rather than
because nothing has been built. An earlier version said "six of the eight …
two do not fit", counting the proxy-credential row as the second exception; that
row credits no commit either — what is implemented on this tip is the browser
proxy support the defect lives in, which is not the same predicate. It is red
for a third reason again: the defect is real, found by an independent reviewer,
and deliberately not fixed here.

### A locale-dependent gate, found while measuring the baseline

The first baseline run of the complete suite on this tip reported `2 failed,
4746 passed, 4 skipped, 229 errors`. Every error was a PostgreSQL fixture
failure, and the cause was environmental rather than a defect in the tree: with
`LC_ALL` unset, macOS makes the postmaster multithreaded during startup and
`pg_ctl` refuses to start the disposable cluster —
`FATAL: postmaster became multithreaded during startup`. With `LC_ALL=C` the
same command reproduces the recorded result.

This is recorded rather than quietly worked around because the numbers are the
same shape as a real regression: `4746 + 229 + 2 = 4977`, exactly the recorded
Phase 5J total, so a reader who saw only the failing run would have concluded
the PostgreSQL work had broken. A suite whose result depends on ambient shell
locale cannot serve as release evidence, so the fixture now pins the child
server's locale itself; see the correction below.

The residual `2 failed` in that run is not locale-dependent and is not the same
story. It is a real regression at the tip, recorded next.

## Phase 5J correction 2026-08-06: the tip was red and the record was false

Re-running the complete suite on a clean environment at `5452be3` reports
**`2 failed, 4975 passed, 4 skipped`**, not the recorded `4,977 passed`. The two
failures are `tests/test_hosting.py::test_http_app_fails_closed_before_local_state_without_postgres`
and its `test_standalone_...` sibling. Both pass at the parent `e78d390`,
verified in a separate read-only worktree at that commit, so `5452be3`
introduced them.

Three claims in the Phase 5J record and in that commit's own message do not
match the committed tree:

| Claim | Tree |
| --- | --- |
| "Tests and documentation only; no source change" | `src/cre_mcp/platform/secrets.py` is 415 new lines of production source and `src/cre_mcp/postgres/runtime.py` gained 16 |
| The unprovenanced module was "read and deleted" | A module of that name and purpose is committed and imported by `runtime.py` |
| "Repository gate 4,977 passed" | `2 failed, 4975 passed, 4 skipped` on a clean environment |

The behaviour the commit added is right and is kept: `build_postgres_hosted_persistence`
now verifies that the managed store injected every required credential *before*
it opens a connection or binds a socket, and reports the absent variable
**names**. A deployment missing a credential stops at the boundary instead of
surfacing a connection error whose real cause is a missing secret.

What was wrong is that inserting a new first gate silently changed what two
existing fail-closed tests were testing. They assert `match="PostgreSQL"`; the
preflight's message does not contain that word, so they failed. Worse was the
near miss: had the preflight's message happened to contain it, both tests would
have gone on passing while no longer reaching the PostgreSQL gate at all.

### Repair

Both tests now inject the three required connection strings as non-blank,
unparseable values, so the preflight is satisfied, psycopg rejects the string
before opening a socket, and the database gate is genuinely exercised. They also
assert the exact refusal `hosted PostgreSQL is unavailable` rather than the bare
word, because every terminal message on that path contains "PostgreSQL" —
including the unconditional "domain repositories are not yet certified" raise at
the end of the function. Under the loose match, deleting the database gate
entirely left both tests green; under the exact one it fails them. That
survival is what drove the change, and it is disclosed because a substring
assertion that cannot distinguish two doors is not a gate.

A third test pins the new door: with the secrets absent, start-up refuses,
names all three variables, creates no cache database, no `registry.json`, and no
`audit.jsonl`, and carries no value.

`tests/platform/test_production_secret_inventory.py` pins the module that
shipped with none. The sharpest is
`test_every_activation_condition_names_a_real_setting`. The module Phase 5J
*did* delete was rejected for gating credentials behind `CRE_STRIPE_ENABLED` and
`CRE_SKOOL_ENABLED` — flags nothing in this codebase reads — so those secrets
would silently never have been required. Nothing prevented the surviving module
from acquiring the identical defect; the pin resolves every `activated_by`
variable against `CreConfig`'s accepted names and its value against the field's
permitted literals.

`test_the_runbook_names_every_secret_a_deployer_must_provide` failed on arrival
and found a second real gap: **none** of the six `MEDAWARCRE_*` database
credentials appeared anywhere in `deploy/DEPLOY.md`, including the three whose
absence now refuses start-up. Phase 5J recorded that the runbook "records exact
names and least-privilege consumers" and that "every name in that table was
verified present on `CreConfig`" — true of the `CRE_*` rows, and the reason the
gap survived is that the three required ones are not `CreConfig` fields at all,
so a check written against the model could not see them. `deploy/DEPLOY.md` now
carries them with their exact per-service roles and marks the three operator
credentials as absent from the serving process.

### Mutation evidence

Control 45 passed, against the working copy on each run.

| Mutation | Result |
| --- | --- |
| Drop the start-up secret preflight | 1 failed |
| Delete the whole database open and readiness gate | 2 failed |
| Blank injection counts as present | 6 failed |
| Environment-variable-name guard dropped | 2 failed |
| Self-gating secrets become start-up-required | 12 failed |
| Conditional activation always true | 12 failed |
| Canonical ordering of missing names dropped | 2 failed |

Two further mutations, added after review against a control of 47 passed, kill
the two gaps a reviewer demonstrated were open:

| Mutation | Result |
| --- | --- |
| An inventory entry names a consumer module that does not exist | 1 failed |
| The `MEDAWARCRE_MIGRATION_DATABASE_URL` entry — the only DDL credential — is deleted outright | 1 failed |

Five more after round two, against a control of 54 passed. Each kills a mutant a
reviewer had demonstrated surviving:

| Mutation | Result |
| --- | --- |
| The psycopg cause is chained back into the database-gate refusal | 1 failed |
| `CRE_STRIPE_API_KEY` deleted from the inventory | 1 failed |
| `CRE_SKOOL_WEBHOOK_SECRET` deleted from the inventory | 1 failed |
| `CRE_PROXY_URL` deleted from the inventory | 1 failed |
| Every `least_privilege` replaced with "unrestricted superuser on every database" | 1 failed |

One change is listed rather than counted, on the standard this program already
set for equivalent mutants: removing the `.strip()` from
`PostgresSettings.from_env` leaves the hosting suite green, because the
`from None` above it already closes the disclosure. It is pinned directly
instead, by asserting the presence check and the consumer agree on what counts
as injected.

Six more after round three, against a control of 59 passed:

| Mutation | Result |
| --- | --- |
| `oauth_authority` chains the DSN-echoing cause back in | 1 failed |
| `admission` chains it back in | 1 failed |
| `backup._command_connection` chains it back in | 1 failed |
| The request-path `least_privilege` claims superuser and full DDL | 1 failed |
| `runtime` drops the readiness re-raise | 1 failed |
| `runtime` drops `finally: database.close()` | 1 failed |

Six more after round four, against a control of 67 passed. Every one closes a
gap a reviewer demonstrated. (An earlier caption said "eight", which was that
round's pin delta, not its mutation count; every other caption in this series
equals its table's row count.)

| Mutation | Result |
| --- | --- |
| `CreConfig` drops `hide_input_in_errors` | 3 failed |
| `_command_connection` keeps the password in argv (`pop` → `get`) | 1 failed |
| `_command_connection` keeps `sslpassword` in argv | 1 failed |
| `PostgresSettings.__repr__` interpolates the DSN | 1 failed |
| The terminal fail-closed refusal becomes a `return` | 1 failed |
| `0008` grants `CREATE ON SCHEMA` to the app role | 1 failed |

Round five, against a control of 68 passed. The two bypasses of the round-four
fail-closed pin are **not** in this table; they are recorded in the current-tree
table further down, because they could not be stated honestly here. Round five
first recorded them as `9 failed` / `8 failed` measured against
`tests/test_hosting.py` alone while printing a control for both modules; round
six "corrected" that to `12` / `11`, which were measurements on the *later*
tree placed under the earlier control; and a round-seven reviewer reconstructed
the round-five tree and measured `9` / `9`. Rather than carry a third version of
a number this document has now got wrong twice, the mutations are re-measured
against the current tree and control, where any reviewer can reproduce them.

| Mutation | Result |
| --- | --- |
| `MigrationRunner` drops the DSN strip | 1 failed |
| The inventory claims the pool *accepts* a session resolving to any other role | 1 failed |
| `pool.py` no longer asserts an exact group session | 1 failed |
| A lower-case DDL grant is appended to `0001` | 1 failed |
| The same appended to `0005` | 1 failed |
| The same appended to `0008` | 1 failed |
| The same appended to `restore_privileges.sql` | 1 failed |

Two harness errors in this round are disclosed, since each first produced a
number that meant nothing. A mutation anchor was written against text the source
wraps across two string literals, so the replacement never applied and the
mutant "survived" vacuously. And the restore helper reused the loop variable
name, so three appends meant for three different SQL files all hit the last one.

A third, worse one belongs here too, because it took two rounds to stop being
wrong: the two bypass rows were first measured against `tests/test_hosting.py`
alone under a control printed for both modules, then "corrected" with numbers
measured on a later tree under the earlier tree's control. Both versions were
plausible. Neither was reproducible. They are now measured on the current tree
in the round-seven table, where a reviewer can re-run them.

Counted plainly, and recounted twice because both attempts were short. **Four**
in round one: a restore that read git `HEAD` instead of the working copy; an
unquoted zsh selector that ran nothing; a database-gate mutation that commented
out only `database.open(...)` and survived for a reason the record then
described wrongly; and an ordering mutation written with unbalanced parentheses
that reported errors rather than failures. **Two** in round five: an anchor that
never matched, and a clobbered loop variable. And **three successive wrong
publications of the same two bypass numbers** — measured against a narrower
selection than the printed control, then re-measured on a later tree under the
earlier control, then carried forward unchanged into a table promising
current-tree numbers.

Plus one more found while correcting this round's numbers: two malformed
mutations of the OAuth-authority and admission pre-connects, which produced
collection errors rather than measurements and are reported as unmeasured rather
than as survivors.

And **one** in Phase 5K round four: a full repository run that returned 2
failures and 20 errors under a load average of 56 on a 10-core machine, caused
by three concurrent test suites belonging to an unrelated program on this
workstation plus my own concurrently-started gates. Detailed at the Phase 5K
evidence section below.

That is **twelve**. The first count said five, the second seven, the third nine,
the fourth ten, the fifth eleven — each contradicted by disclosures elsewhere in this same
document, which is itself the pattern the count is about: a summary number
drifting from the material it summarises. Two reviewers found the same shortfall
independently, and the honest reading is that this record is better trusted for
its individual measurements, each printed beside its control, than for any
figure that aggregates them.

Every one produced a plausible number. That is the reason every table here is
printed beside its control, the reason a control must come from the identical
command as the rows beneath it, and the reason the rows that kept moving are now
stated only against the tree a reader has in front of them.

Round six, against a control of 71 passed:

| Mutation | Result |
| --- | --- |
| `starlette_app` catches the terminal refusal and returns a file-backed bundle | 1 failed |
| `0008` grants `medawarcre_app` membership of the DDL role | 1 failed |
| `0008` gains a single-line `ALTER DEFAULT PRIVILEGES … GRANT ALL` | 1 failed |
| `bootstrap_roles.sql` gives `medawarcre_app` `CREATEDB CREATEROLE` | 1 failed |

Rounds seven through ten, against a control of **78** passed — the current tree,
so every row below is reproducible today. The two bypass rows are here, measured
on this tree, after being published wrong three times. The control read 77 until
round ten added the builder call-site pin to one of the two modules; a
confirmation reviewer caught the stale caption, which is the same defect as the
mixed controls above, one round after that defect was written up.

| Mutation | Result |
| --- | --- |
| `create_http_app` recovers, gated on a variable the old pin stripped | 1 failed |
| `main` recovers, gated on `CRE_HTTP_HOST` | 1 failed |
| `main` recovers ungated — both arms see it | 2 failed |
| Recovery gated on `CRE_HTTP_HOST`, which the Dockerfile's `ENV` sets | 1 failed |
| `__main__.py` rebinds the builder before `main` runs | 1 failed |
| `build_postgres_hosted_persistence` gains a `functools.wraps` decorator whose wrapper returns a bundle unconditionally | 17 failed |
| The module rebinds the name to a `functools.wraps` wrapper that calls the strict function and returns a bundle on `HostedPersistenceUnavailable` | 16 failed |
| A comma-separated role-membership grant in `0008` | 1 failed |
| A membership grant hidden in `bootstrap_roles.sql` | 1 failed |
| A second `ALTER ROLE … SUPERUSER CREATEDB CREATEROLE BYPASSRLS` | 1 failed |
| A second `ALTER ROLE … LOGIN` | 1 failed |
| `ALTER ROLE … SUPERUSER` written without the optional `WITH` | 1 failed |
| A `GRANT` that is not the first token on its line | 1 failed |
| The `PGOPTIONS` scrub is deleted | 1 failed |

A reviewer predicted the two bypass rows must be symmetric, since both trip the
same identity assertion. They are not, and the reason is behavioural rather than
structural: the decorator mutant returns a bundle unconditionally, while the
rebinding mutant calls the strict function first and recovers only from
`HostedPersistenceUnavailable`, so one further test that drives a different
failure sees different behaviour. Recorded because the prediction was reasonable
and the measurement disagrees with it.

Both rows carry their mutant's exact shape because a later reviewer could not
reconstruct the 16 from prose and landed on 9 or 17 depending on how it read the
description — a row is only reproducible if the mutation is stated precisely
enough to rebuild. Both re-measured on the current tree at control 78: 17 and
16.

Each table is scoped to the control printed above it and to the tree of its own
round. They are a record of what was measured when, not a suite to re-run: later
rounds add pins, so an earlier row's failure count is lower than the same
mutation produces today — deleting the database gate was 2 failures in round
one and is 7 now. Two reviewers independently reconciled the earlier tables by
subtracting the intervening pins and found them consistent.

Two harness corrections are disclosed because both first produced a number that
meant nothing.

The database-gate mutation initially commented out only `database.open(...)`,
and it survived — which is what produced the assertion tightening above. An
earlier version of this paragraph explained that survival by saying
`check_readiness` then raised into the same handler and produced the same
message. That was false, and an independent reviewer reproduced the real
mechanism: `check_readiness` catches every exception and *returns*
`ok=False, code="database_unavailable"`, so control takes the `if not
readiness.ok` branch and raises `hosted PostgreSQL is not release-ready
(database_unavailable)` through the `except HostedPersistenceUnavailable: raise`
path — a different message through a different handler. It survived because that
message also contains the word "PostgreSQL", which is the whole point: the loose
match could not tell the two doors apart. Under the exact assertion the same
mutant fails both tests.

That correction is left in place rather than smoothed away, because a false
mechanism inside the paragraph whose subject is harness honesty is precisely the
defect this record exists to catch.

The ordering mutation was first written with unbalanced parentheses and reported
`2 errors` rather than failures; a syntax error is not a surviving mutant, so it
was redone as a valid one. A mutation result is only meaningful beside a green
control run with the identical command.

### The locale pin

`tests/postgres/conftest.py` now runs all five of its subprocess spawns — two
`psql`, `pg_ctl` start and stop, and `initdb` — under `LC_ALL=C` instead of
inheriting the shell's. No assertion changed. Both reviewers independently
confirmed the pin masks nothing: `initdb --no-locale` was already fixing the
cluster to `C` collation and ctype regardless of the process environment, and
one reviewer re-ran the whole PostgreSQL suite with the pin set to
`en_US.UTF-8` instead and got the same 274 passed.

### Evidence

The complete suite was run with **both `LC_ALL` and `LANG` explicitly unset** —
the exact condition that produced 229 errors before the pin:

`5034 passed, 4 skipped, 1 warning in 187.72s (0:03:07)`

That is `4,975` previously passing, plus the `2` repaired, plus `57` new pins.
The count grew across ten review rounds and every step is reproducible: `5001`
on the first candidate, then `5003`, `5010`, `5015`, `5023`, `5024`, `5027`,
`5032`, `5033`, `5033`, `5034` as each round added `2`, `7`, `5`, `8`, `1`, `3`,
`5`, `1`, `0`, and `1`. Each pair of reviewers independently reproduced the
count of the candidate they were given. Only the categorized third-party Authlib
deprecation appears.

The per-round deltas understate the later rounds, in both directions. Round
eight added one pin while doubling an existing eight-arm pin's coverage and
**removing** three assertions that could not fail. Round nine added none at all:
it strengthened four pins that reviewers had walked around and deleted another
that could not fail. Round ten — the first to return two approvals — added the
builder call-site pin and made a value-shaped assertion falsifiable by putting a
value in scope, which is the third attempt at that particular block and the
first that can fail.

The growth is the honest shape of this correction: every one of those 57 pins
exists because something was found unpinned. Most were added after a reviewer
demonstrated the guard could be deleted with the whole suite green — the exact
per-round attribution is not restated as a single number here, because an
earlier version did and it was an assertion about review history rather than
anything reproducible from the tree. The per-round counts understate the later
rounds: much of rounds five and six was **strengthening** pins that already
existed and could be walked around, which changes no count at all.

Static gates: `compileall` clean over `src` and `tests`; `git diff --check`
clean; changed-content credential scan clean; no port-8000 listener; no
dependency or lockfile change; no migration change. Capability inventory
`84578ae71567ed18` with 274 capabilities and 15 hosted-withheld; visible counts
Local 8, National 10, Full Operator 20, JV Partner 11 — all unchanged. An
isolated wheel packages the source-rights registry and all eight numbered
migrations plus `restore_privileges.sql`.

Three production entrypoints reach this boundary — `create_http_app`,
`starlette_app`, and `run_server` — and each calls
`build_postgres_hosted_persistence()` before any connection, any socket bind,
and any local state. Not before *any* work: `create_http_app` constructs
`CreConfig()` first, and `run_server` constructs it and resolves the transport
first. An earlier version of this line said "before any other work", which
overstated it; both reviewers caught the same sentence.

A later version then said only two of the three were covered by a test and that
`run_server` rested on "an argument from the call site". That is stale: all
three, plus `main` and `__main__.py`, are pinned by
`test_no_entrypoint_recovers_from_the_terminal_refusal` and its shim check —
see the fail-closed section below. Both reviewers caught this sentence too,
which is the second time a paragraph here has understated its own later work.

### Findings from the two independent reviews, and what changed

Both reviewers reproduced the frozen candidate hash unchanged at start and
finish, reproduced `5001 passed, 4 skipped` independently, and reproduced all
seven mutation rows. Both returned CHANGES REQUIRED. Every finding below was
verified against the tree before it was accepted.

| Finding | Disposition |
| --- | --- |
| The mutation-disclosure paragraph explained the surviving mutant with a mechanism the code does not have | Corrected above, with the real mechanism and the fact that it was wrong |
| The Phase 5K contract was inside the candidate, undisclosed in this record, and its own text said the correction must land first | Removed from this commit. It belongs to the phase it describes |
| `secrets.py` described `medawarcre_app` as `NOLOGIN NOINHERIT`; `bootstrap_roles.sql` declares it `NOLOGIN INHERIT` | Corrected. `INHERIT` is deliberate — the login member inherits exactly that group, which is what `assert_exact_group_session` requires |
| An inventory entry could name a fictional consumer, or be deleted entirely — including the only DDL credential — with the suite green | Two pins added; both mutants fail. Round two showed the deletion half was still narrow — see below |
| Two `psql` spawns in the PostgreSQL fixture still inherited the shell locale | Pinned, for consistency with the three that were |
| "before any other work" overstated the entrypoint ordering | Corrected. Both reviewers flagged the same sentence |
| "164 capabilities" restated the entitled count without its qualifier | Corrected to "164 entitled, 160 reachable" — which round two proved was itself false. Now 164 entitled, 11 withheld, 102 reachable |

### Second review round: a real credential disclosure, and two false numbers

Both fresh reviewers reproduced the repaired candidate hash unchanged, both
reproduced `5003 passed, 4 skipped`, both reproduced all nine mutation rows —
and both returned CHANGES REQUIRED again.

**Both independently derived the same blocking finding, and they were right.**
The replacement sentence written to fix the round-one "164 capabilities"
complaint said "160 reachable". That is false. The true figure is **102**, and
160 is not merely wrong but impossible: 11 of the 15 hosted-withheld
capabilities are JV-entitled, so the ceiling is `164 − 11 = 153`. 160 is the
union of the *non-withheld* capabilities grouped onto the 11 tools JV can see,
counted without regard to entitlement — those facades are shared with other
profiles, so most of the extra capabilities belong to them. Counting the
withheld ones too gives 168. Three numbers describe those eleven tools and only
one of them answers "what can JV actually call": 168 grouped, 160 grouped and
not withheld, **102** grouped, not withheld, and entitled to JV.

The origin matters more than the number. A round-one reviewer supplied 160, the
builder ran their snippet, got 160, and wrote it into the ledger without
deriving what it measured. **Reproducing a number is not checking that it
measures what the sentence claims.** That is two consecutive rounds in which the
correction to an overstatement was itself an overstatement, which is why the
row above now carries both retracted versions rather than only the answer.

**One reviewer found a real credential-disclosure path**, and it is repaired
rather than carried. The round-one record described the `_pgconn` exposure as
reachable only by introspecting a private attribute. That generalization was
wrong. When psycopg cannot parse a DSN as a URL it falls back to keyword/value
parsing and echoes the first whitespace-delimited token verbatim — and for a
URL-form DSN that token is the entire connection string. One leading space is
enough, which is an ordinary managed-store or copy-paste artifact, and it passes
the preflight because `_present()` strips only for the presence test while the
unstripped value goes to psycopg. Reproduced:

```
psycopg.ProgrammingError: missing "=" after
  "postgresql://appuser:REALPASSWORD@10.0.0.5:5432/medawarcre"
  in connection info string
```

Present in `str`, `repr`, `args`, and `traceback.format_exception()` of the
chained cause, on the ordinary `hosted PostgreSQL is unavailable` path. A plain
`logging.exception()` discloses it. This violates the non-negotiable invariant
that secrets do not enter logs.

Two production changes repair it. The database gate no longer chains the
psycopg cause — it raises `from None` and names only the exception *type* — and
`PostgresSettings.from_env` now strips the DSN so the presence check and the
consumer agree on what counts as injected. Chaining the cause back in fails the
new regression; the strip is defence in depth behind it and is pinned separately
rather than counted as falsified by that test.

Stated precisely, because the unqualified version of this is what got two
earlier rounds rejected: `raise ... from None` sets `__cause__` to `None` and
`__suppress_context__` to true, but does **not** clear `__context__`. Every
renderer tested honours the suppression flag — `traceback.format_exception`
under both signatures, `format_exc`, `format_exception_only`,
`print_exception`, `TracebackException` compact and not and with
`chain=True/False`, `logging.exception`, the default `sys.excepthook`,
`rich.traceback`, and pytest's `getrepr` — across two independent reviews, with
no renderer found that ignores it.

**One** residual is carried rather than claimed closed: the original exception
is reachable by reading `exc.__context__` directly, which is introspection
rather than rendering.

An earlier version of this paragraph claimed a second — that the psycopg
exception stays bound to the frame local `error`, so a locals-rendering mode
would disclose it without touching `__context__`. That is false. CPython
compiles `except E as error:` with an implicit `finally: error = None; del
error` which runs during unwinding, so the frame holds only `settings` and
`database`; both reviewers independently drove `rich.traceback(show_locals=True)`
and pytest `--showlocals` against a production-shaped call and measured no
disclosure. One of them noted the confound that most likely produced the claim,
because it caught them too on a first attempt: a probe harness that itself holds
the DSN in a caller frame.

That sentence was written to make the previous round's claim more precise, and
it was wrong — the second time in this correction that a reviewer's finding was
folded in without re-deriving it, after "160 reachable". The rule that keeps
being relearned: a reviewer's measurement is a lead, not a result.

**A third round found the fix had been applied to one site of four.** The same
`from error` chaining of a DSN-echoing psycopg parse error was still present in
`postgres/oauth_authority.py`, `postgres/admission.py`, and
`postgres/backup.py`. Neither repository is constructed by the hosted process
yet, and the backup CLI already collapses its error to a fixed code, so this was
not a live disclosure — but they hold the two credentials the new preflight
*requires* an operator to inject, and `cre_mcp.server` installs a root logging
sink that would render the chain as soon as the domain wiring lands. All three
are repaired, and the regression now covers the class rather than the one
reported instance: a parametrized pin drives each opener with an unreadable DSN
and asserts the canary reaches neither the message nor the formatted traceback.
`backup._command_connection` gets its own, because its entire purpose is to lift
a password out of the child's **command line** — where any local user can read
it with `ps` — into the child's environment, which makes chaining a
quote-it-back parse error the sharpest version of the defect. (This sentence was
the fourth place carrying that description backwards; a reviewer found it after
the other three were corrected.)

The lesson is the one this document keeps relearning from the other direction:
a reviewer reports an instance, and repairing exactly the instance leaves the
class open.

**One reviewer demonstrated the completeness pin was far narrower than its
name.** The source scan can only see `MEDAWARCRE_*_URL`, so 14 of the 21 entries
— including both webhook signing secrets — could be deleted outright with the
whole repository green, taking their runbook obligation with them. An exact-set
pin now fails on any deletion or rename. Deleting `CRE_STRIPE_API_KEY`,
`CRE_SKOOL_WEBHOOK_SECRET`, or `CRE_PROXY_URL` each now fails.

**One reviewer found the repaired tests had traded one ambient coupling for
another.** With `CRE_HUMAN_IDENTITY_PROVIDER=clerk` and no Clerk key set in the
shell — a supported configuration — the preflight demanded a fourth credential
and refused before the database gate, so both hosting tests failed for a reason
outside the repository. In the same commit whose locale rationale says exactly
that is not release evidence. They now clear every variable the inventory names
before setting what they need, and pass under the hostile environment that
previously failed them.

Also repaired: `least_privilege` was unpinned prose, including the single
sentence this commit changes; a mutant that read `os.environ` while building the
refusal was invisible to pins that pass synthetic mappings, and is now pinned;
the stale "23 pins" count is gone; and the locale subsection now says five
spawns rather than naming two of the five. Round three added two more pins for
behaviours in `postgres/runtime.py` that were deletable with the suite green —
the `finally: database.close()` that keeps a refused start-up from leaking a
pool, and the `except HostedPersistenceUnavailable: raise` re-raise, which is
the exact handler the corrected mutation mechanism above depends on.

The `least_privilege` pin needed two attempts, and the first attempt is why this
paragraph exists. It checked only that `NOLOGIN` and `INHERIT` appeared in both
the role contract and the claim, so a reviewer rewrote "holds no DDL" to "holds
full DDL and is a superuser" and the entire suite stayed green — while the
record said "a pin now holds the request-path claim". It now also requires the
role to be `NOSUPERUSER` in `bootstrap_roles.sql`, requires the claim to say the
role holds no DDL, rejects a claim asserting superuser or full DDL, and checks
that no `GRANT ... TO medawarcre_app` in `0001_authoritative_cloud.sql` confers
`CREATE` or `ALL`. Written the first way, that check also had a false positive
of its own — a bare substring test matched the column name `CREATED_AT` — so it
is word-bounded.

### Fourth review round: a live disclosure, and a door with no test

**One reviewer found a fifth disclosure site, and this one was live.** Pydantic
renders `input_value=...` into every `ValidationError`, so the validator that
exists to reject a live Stripe key *printed that key*. Setting
`CRE_STRIPE_API_KEY=sk_live_...` produced an uncaught traceback on stderr
containing it, at **import** of `cre_mcp.server` — via the module-level
`CreConfig()` in `http/policies.py`, before any entrypoint runs. That
contradicted three separate written claims, including Phase 5J's own "no raised
error carries a value" and the test module's "nothing reachable by a browser, a
client, a log, or a serialization can disclose them". The existing pin could not
see it: its sentinel is an `sk_test_` value, which the validator accepts.

Repaired at the class rather than the instance — `hide_input_in_errors=True` on
`CreConfig` — and pinned for a credential field and two non-credential fields,
so the next validator to reject something cannot reintroduce it.

Scoped precisely, because the first version of this sentence said the setting
"suppresses the value for every validated field" and that is wider than the
truth. It suppresses the value from the **rendered message**, which is what
closes the stderr traceback. The exception object still carries the raw input
on `errors()[0]["input"]` and in `ValidationError.json()`. Nothing in `src/`
calls either on a configuration error today, and both are serializations rather
than renders, but `tests/platform/test_secret_boundary.py` claims nothing
reachable by "a log, or a serialization" can disclose a secret, and that claim
is now qualified there too. One further residual: for `dict`-valued settings the
error `loc` reproduces the input dict **key** — none of which is a credential on
this model (source names, community ids, price ids, client names).

**The other reviewer found the terminal fail-closed refusal had no test at
all.** `build_postgres_hosted_persistence` ends by refusing unconditionally, and
its docstring says that is what stops a reachable PostgreSQL from accidentally
reviving SQLite or file-backed hosted authority. Nothing exercised that line:
every working-app test patches the builder outright and every real-call test
stops at an earlier gate. The reviewer replaced the final `raise` with a
file-backed bundle — `PlatformApi` on the local SQLite cache, `WorkspaceRegistry`
on `access/registry.json`, `AuditLog` on `access/audit.jsonl` — and got a
**working ASGI app** out of both entrypoints against a live migrated cluster,
with the whole repository green.

That is the most serious gap this correction found. Round three had added pins
for two *other* behaviours inside the same function and left the door itself
open.

The first repair was pinned with `inspect.getsource`, and **round five walked
past it twice, independently**. `inspect.getsourcelines` calls `inspect.unwrap`
first, so a `functools.wraps` decorator — or a module-level rebinding to a
wrapper — leaves the AST reading the strict function while a different callable
answers to the name. One reviewer used the decorator, the other the rebinding;
both got a working hosted ASGI app against a live migrated cluster with the
whole suite green. The behavioural half could not catch either, because it
monkeypatches the preconditions, so an override gated on anything the suite
never sets survives it.

The pin now reads the source from the module file by name rather than from the
object, and requires the object bound to that name to be the function defined
there: no `__wrapped__`, `__code__.co_name` and `co_filename` and `co_firstlineno`
all matching the definition, and an empty `decorator_list`. `functools.wraps`
copies `__name__` and `__qualname__` but never `__code__`, which is what makes
those checks survive a wrapper that impersonates the original. Both bypasses now
fail, at the counts recorded in the round-seven table. An earlier version of
this sentence said they fail "nine and eight assertions respectively", which was
the retracted mismeasurement relabelled as assertions — and pytest stops a test
at its first failing assertion, so it was not reproducible as written either.

The lesson generalises past this function: a structural pin that reads a
callable through `inspect` is checking whatever `inspect` decides to resolve to,
not what will run.

**And round six moved the same instance one frame further out.** Both reviewers
independently left the hardened builder untouched and put the six lines in its
*caller*: `starlette_app` catching `HostedPersistenceUnavailable`, building a
file-backed bundle, and returning a working ASGI app with 59 routes and a cache
database on disk — against a live migrated cluster, with the whole suite green.
The builder pin could not see it because the builder was never modified, and the
two DSN tests could not either, because they stop at the database gate where the
shim re-raises. The behavioural half ran only through `create_http_app`.

**Round seven moved it once more, and found the pin's own hiding place.** Both
reviewers put the recovery in `main` — the frame the Dockerfile actually runs,
`CMD ["python", "-m", "cre_mcp", "--http"]` — which the three-entrypoint
parametrization did not cover, and whose only existing test patches `run_server`
with a Mock so the handler never runs. One of them also gated a recovery in
`create_http_app` on `MEDAWARCRE_MIGRATION_DATABASE_URL`: a variable every real
deployment sets and which the pin's own `_clear_inventory_environment` helper
deletes before each arm. **Stripping the environment to make the test
deterministic was itself the hiding place.** Both bypasses served a hosted app —
60 routes, a cache database on disk — with the whole suite green.

A reviewer also showed the `run_server` arm did not fail on a bypass; it bound
`0.0.0.0:8000` and blocked, so the arm meant to catch the defect turned it into
an indefinite hang and a live listener, contradicting this program's own
no-port-8000 gate. `FastMCP.run` is now replaced with a raising stub in the pin.

The refusal is pinned at four entrypoints — `create_http_app`, `starlette_app`,
`run_server`, and `main` — each under **two** environments, stripped and
production-shaped. A reviewer's independent enumeration confirms no production
module under `src/` constructs a `HostedPersistenceBundle` at all, and that the
only way to obtain one is the builder, called from exactly three sites, all
pinned.

**Round eight relocated it twice more, and both times the pin's own idea of
"production" was the hiding place.** One reviewer put the recovery in
`src/cre_mcp/__main__.py` — the module `python -m cre_mcp` enters *before*
`main`, which nothing in the repository read — and served a hosted app with a
397 KB cache database on disk. Both reviewers, independently, gated a recovery
on a variable from the **Dockerfile's own `ENV` block** (`CRE_HTTP_HOST=0.0.0.0`,
`CRE_HTTP_PORT=8000`): the container sets them on every real run, and the
hand-written "production-shaped" list set neither.

Both are closed, and the second is closed at its cause rather than its instance:
the production-shaped arm now **parses the `ENV` block out of the Dockerfile**
instead of transcribing names, so the next `ENV` line is covered without anyone
remembering. That was a reviewer's recommendation and it is the right one — a
hand-written list of what "production" means had failed twice by then, once per
round. `__main__.py` is pinned as a pure shim: imports, one call to `main`, no
`try`, and no mention of the builder or the bundle type.

Round nine relocated it twice more: the shim's `main` was re-pointed at a **new
module** that wrapped the real one (the shape check held; nothing required the
name to come from `cre_mcp.server`), and a recovery was gated on
`CRE_CLERK_PUBLISHABLE_KEY` — documented in `DEPLOY.md`, correctly not a secret
so not in `PRODUCTION_SECRETS`, and not in the Dockerfile. Both are closed, the
second again at its cause: the arm now also derives names from the **runbook**,
so "what a deployment sets" comes from the two files that define it rather than
from anyone's memory.

Six rounds, eight relocations of one defect: body, decorator, module rebinding,
caller, entrypoint, module shim, a delegating module, and three times the
test's own idea of the environment. Each repair was correct for the instance it
was given.

Round ten was the first to return two approvals, and both reviewers were asked
directly whether the paragraph below is honest or an excuse. Both judged it
honest and correctly scoped; one went looking for the realistic-regression
counterexample it invites and reported finding none unpinned — its sharpest
candidate, deleting the pre-connect that keeps `psycopg_pool`'s WARNING channel
shut, already fails 12 tests in the module it names and 17 across
`tests/postgres/`. Both also observed that the frame list
`_HOSTED_ENTRYPOINTS` was still hand-written while the environment had been
derived twice, which is the failure mode this correction says it learned. The
set of builder call sites in `src/` is now derived and pinned at three, so a new
caller fails the suite until someone decides whether it needs an arm.

**What this does and does not establish.** Every one of these was an
*adversarial insertion of new code* by a reviewer with write access to a copy —
not a regression of existing code. No test suite can prove the absence of a
deliberately added recovery path; a sufficiently determined insertion can always
find one more frame. Eight rounds of reviewers driving the real system agree the
**shipped behaviour is correct**: every entrypoint refuses under every hostile
environment tried, including a live fully-migrated cluster, and creates no local
state. What the pins buy is regression resistance — the property is now asserted
at every frame that can express it, under an environment derived from the
Dockerfile and the runbook rather than transcribed. That is the honest claim,
and it is narrower than "this cannot be bypassed".

**A third gap:** `backup._command_connection` exists to move a password out of
the connection string before it becomes `pg_dump` argv, where any local user can
read it with `ps`. Changing its `pop("password")` to `get("password")` left the
entire repository green while putting the credential back on the command line.
The postgres suite could not see it — its fixture DSNs carry no password. Now
pinned, along with `sslpassword` and the `PGOPTIONS` scrub.

That sentence was wrong twice, in the same way, one variable at a time. The
`PGOPTIONS` half was false for two rounds. The repair then set all three
variables in the parent — and still left `PGPASSWORD` and `PGSSLPASSWORD`
unfalsifiable, because the test's DSN supplies both, so `_command_connection`
re-sets them whether or not the scrub ran; a reviewer deleted both scrubs with
the whole repository green. The pin now also drives a **passwordless** DSN, the
shape a socket, trust, `.pgpass`, or IAM deployment uses — and the one this
repository's own PostgreSQL fixtures use — where an ambient `PGPASSWORD` for an
unrelated database would otherwise reach the `pg_dump` child.

The original way it was false is still worth keeping: the assertion existed and
passed, but **vacuously**.
`_command_connection` copies `os.environ`, and the test process had no
`PGOPTIONS`, so `assert "PGOPTIONS" not in environment` held whether or not the
scrub ran — a reviewer deleted the scrub and the repository stayed green. The
pin now sets `PGOPTIONS`, `PGPASSWORD`, and `PGSSLPASSWORD` in the parent before
calling. An assertion that cannot fail is not coverage, and this one was
recorded as coverage in a paragraph enumerating what had been closed.

**A fourth:** the redacting `__repr__` on `PostgresSettings`,
`PostgresOAuthAuthorityRepository`, and `PostgresAdmissionRepository` was
unpinned at all three sites, under a module docstring reading "redaction-safe"
and a class docstring promising "without a printable connection string". The
chain-suppression class had been closed at four sites and pinned at four; the
redaction class was closed at three and pinned at none. Now pinned at all three.

Also this round: the GRANT scan read only `0001`, so adding
`GRANT CREATE ON SCHEMA medawarcre TO medawarcre_app` to `0008` kept it green —
it now reads all nine shipped SQL files; and two operator-path sites the builder
found by sweeping rather than waiting to be told are repaired,
`MigrationRunner` storing an unstripped DSN and the `from error` chain around
the restore smoke test.

Recorded honestly about what is still *not* pinned: a consumer must resolve, but
it need not be the module that actually reads the variable — pointing an entry
at some other real module survives. `purpose` and `rotation` remain unchecked
prose. `least_privilege` is now partly checked for the request-path entry only;
the other twenty entries' least-privilege sentences remain prose. The exact-set
pin catches deletion, not a wrong description. Two guards a reviewer showed are
deletable with the suite green are listed rather than pinned, both
defence-in-depth against a caller that does not exist: `_activated`'s
`.casefold()` (the provider field is a `Literal`, so a non-exact value fails
configuration first) and `MigrationRunner`'s `role != MIGRATION_ROLE` guard
(both production callers use the default). And `restore_backup`'s new
`from None` is unpinned — reverting it to `from error` leaves the suite green,
because reaching that handler needs a full dump, manifest and cluster; it is
listed here rather than counted, on the same standard as the `.strip()` above,
which by contrast *is* pinned directly.

Two disclosure surfaces are carried rather than closed, both recorded so the
staging security audit has them in scope, and both stated at the severity a
reviewer measured rather than the one first written.

`backup.py` retains **six** `psycopg.connect` calls with no conversion, so a
parse error propagates raw. An earlier version said seven — the seventh, in
`_backup_service_smoke`, is reached only from inside the `from None` handler
this commit adds, so it no longer propagates. `migrations.py` holds **two** more,
carrying the only DDL credential — a reviewer pointed out they had the same
posture as the six but were outside the scope this paragraph hands to the
staging audit, so they are named here. All eight are reachable only through
`medawarcre-postgres`, whose CLI collapses `psycopg.Error` to a fixed code and
prints no traceback.

One channel is named here because a reviewer traced it and it is currently held
shut by something that looks removable. `psycopg_pool` logs
`error connecting in %r: %s` at WARNING, and for an unparseable DSN that message
is the whole connection string, into the same root sink. No shipped opener
reaches it: `pool.py`, `oauth_authority.py`, and `admission.py` each run a
standalone `psycopg.connect(dsn)` **before** opening the pool, so a bad DSN
raises into the `from None` handler and the pool never starts. Those three
pre-connects look redundant beside the pool's own `configure` callback, which is
exactly the shape of a well-meaning deletion — so a reviewer tried both
plausible refactors and each fails.

Measured here rather than restated: deleting the **runtime pool's** pre-connect
(`pool.py:194-196`, the `with psycopg.connect(...)` block inside
`PostgresDatabase.open`) fails **12** tests in
`tests/postgres/test_release_audit_regressions.py` and **17** across
`tests/postgres/`, the extra five being in `test_pool_health.py`. Load-bearing,
already pinned, and now written down so the next reader knows the pre-connect is
not redundant with the pool's own `configure` callback.

An earlier version of this sentence said "each fails 17 tests in
`tests/postgres/test_release_audit_regressions.py`" and attributed it to all
three pre-connects. Both halves are wrong: 17 is the package figure, and that
module holds 40 tests of which 12 fail. The number came from a round-ten
reviewer and was written down without re-deriving it — the **fourth** time in
this correction a reviewer's measurement was folded in as a result rather than
treated as a lead, after "160 reachable", the frame-local `error` residual, and
the bypass-row counts. Both confirmation reviewers caught it independently.

No equivalent claim is made for the OAuth-authority and admission pre-connects,
because I could not measure them: both mutations were malformed — a regex that
removed a `with` statement and orphaned its body — and produced collection
errors rather than failures. A broken mutant is not a survivor and not a result.
That is the tenth harness error disclosed in this record, of eleven as of Phase
5K round four — "eighth" here in an
earlier draft, contradicting the tally in "Mutation evidence" above — which
both approving reviewers measured at some 575 lines away, not the "twenty" that
draft asserted, so the cross-reference is now by name rather than by distance.
That is the same drift
the tally itself is about.

`http/browser.py:146` puts `CRE_PROXY_URL` — which this inventory itself
describes as a URL that "embeds its own credentials" — into Chromium argv under
a docstring claiming it builds options "without exposing configured secrets".
An earlier version of this paragraph said that made it readable via `ps`. It is
worse than that: a reviewer traced it end to end into a **log**. `nodriver`
logs its launch arguments at INFO, and `server.py:38` installs a root
`basicConfig(level=INFO, stream=sys.stderr)` sink, so the process prints
`--proxy-server=http://user:PASSWORD@host:8080` to its own stderr. That is the
channel this program calls non-negotiable. It is not hosted-reachable — hosted
browser navigation fails closed at the source-rights gate before any launch —
but it is **live in the shipped stdio product whenever a proxy is configured**,
so it is now its own ledger row rather than a footnote here.

This commit therefore changes production source in eight places — `config.py`,
`platform/secrets.py`, `postgres/runtime.py`, `postgres/config.py`,
`postgres/oauth_authority.py`, `postgres/admission.py`, `postgres/backup.py`,
and `postgres/migrations.py`. Stated plainly, because the commit it corrects
claimed "no source change" while adding 415 lines of it.

### A process failure worth recording

During round seven a reviewer appended a mutation to
`deploy/postgres/bootstrap_roles.sql` **in the shared working tree** rather than
in its own copy, then reverted it. Its own report disclosed this. The candidate
hash was correct before and after, and that reviewer re-derived every result on
a verified byte-identical copy — but for a window, a second reviewer's rsync
captured a mutated tree and reported 123 PostgreSQL failures that were not the
candidate's.

Separately, a round-four reviewer's waiter process stayed attached after that
reviewer had delivered its report, re-reported later against a by-then
superseded candidate, and correctly called the hash mismatch blocking. Nothing
was lost — every one of its findings had already been applied, and it said so
after inspecting the moved tree — but it is the same shape as a failure this
document already records from the hosted-withholding phase.

A third instance followed in round nine, and this one was mine: clearing
accumulated reviewer copies to recover disk space, I deleted by prefix and swept
two live reviewers' working directories out from under running mutation batches.
Nothing was lost — both re-derived their results on fresh byte-identical copies
and the shared checkout hash verified intact — but it cost a reviewer a
measurement round.

Three rules follow, each written down only after being violated: a reviewer must
never write to the shared checkout; a candidate must stay frozen until every
attached reviewer has reported *and detached*, because a completion notification
is not the same thing as a released hash; and cleanup must name its own
directories exactly, never by prefix glob.

### Boundary

No deployment, DNS, billing, provider mutation, or customer-data action. No
schema, migration, dependency, capability, or surface-count change: migrations
`0001`–`0008` and `pyproject.toml` are untouched, the capability inventory is
`84578ae71567ed18` with 274 capabilities and 15 hosted-withheld, and the visible
counts remain Local 8, National 10, Full Operator 20, JV Partner 11. `5452be3`
is not rewritten; the correction lands as its own commit so both states stay
visible.

Fourteen paths change: `deploy/DEPLOY.md`, `docs/launch/PROGRAM_STATUS.md`,
eight production modules (`config.py`, `platform/secrets.py`,
`postgres/runtime.py`, `postgres/config.py`, `postgres/oauth_authority.py`,
`postgres/admission.py`, `postgres/backup.py`, `postgres/migrations.py`), three
existing test modules, and one new test module.

## Phase 5K internal opportunity index opened 2026-08-07

Contract: `docs/launch/PHASE_5K_INTERNAL_OPPORTUNITY_INDEX_CONTRACT.md`.
Base `93e3bbb`, clean worktree, complete suite `5,034 passed, 4 skipped`.

RED recorded before any implementation:
`tests/postgres/test_opportunity_index.py` →
`ModuleNotFoundError: No module named 'cre_mcp.postgres.opportunity_index'`,
`1 error in 0.25s`, 11 tests blocked on it.

The first draft of that module used `pytest.importorskip`, which reported
`1 skipped` — a green-looking result asserting nothing. It was replaced with a
plain import so the absence of the module is a failure rather than a skip. That
is the same defect class the Phase 5J correction spent eleven rounds on, caught
here in the first five minutes because the correction taught the shape.

Two structural decisions the contract fixes, both recorded now so a reviewer can
hold the implementation to them:

- **The index is not a hosted domain repository.** Every customer-reachable port
  is a field on `HostedRequestRepositories`, which tool code reaches through
  `current_hosted_request_repositories()`. The index deliberately is not, and
  three of the eleven RED tests are that boundary — a grant test proving
  `medawarcre_app` is refused by PostgreSQL before RLS is consulted, a test that
  the bundle has no such field, and a static test that no module outside
  `platform/` imports it.
- **The deduplication key reuses `cre_mcp.access.territory`.** The access engine
  already decides where a property is from the same declared fields, using a
  pinned offline Census authority that survived seven audit rounds. A second
  normalizer would let "the same property" drift from "where is this property".
  Confirmed against the live authority: `Burbank, CA` does **not** converge
  without a county or ZIP, so an observation carrying it is rejected and counted
  rather than guessed.

### Implementation and evidence

Migration `0009_internal_opportunity_index.sql` extends the two relations
migration `0001` already reserved and adds `internal_opportunity_reviews`.
`src/cre_mcp/postgres/opportunity_index.py` is the staff-only repository.

The gate numbers below are the **post-round-twelve-repair tree**. Each earlier set
is named rather than overwritten silently: 11 focused / 285 PostgreSQL / 5,045
repository at the opening; 288 / 5,048 after round two; 18 / 292 / 5,052 for the
round-four reviewers; 27 / 301 / 5,061 for round five; 36 / 310 / 5,070 for
round six; 47 / 321 / 5,081 for round seven; 59 / 333 / 5,093 for round eight;
63 / 337 / 5,097 for round nine; 67 / 341 / 5,101 for round ten; and
71 / 345 / 5,105 for round eleven; and 74 / 348 / 5,108 for round twelve; and 78 / 352 / 5,112 for round thirteen; and 81 / 355 / 5,115 for round fourteen; and 85 / 359 / 5,119 for round fifteen.
All are superseded.

Gates, all green: **89** focused tests across two files — `test_opportunity_index.py`
and the new `test_opportunity_index_guards.py`, which exists because round seven
found the database guards pinned by a constant rather than by behaviour;
**363** PostgreSQL tests, up from 274 by exactly these eighty-nine; **5,123
passed, 4 skipped** in the repository suite in 273.69s, up from 5,034 by the same
eighty-nine — with `LC_ALL` and `LANG` genuinely unset in the invoking shell,
which is what the `tests/postgres/conftest.py` pin exists to
survive, and load 5.33 at start and 4.33 at end. Compile and `git diff --check`
pass. No `pyproject.toml`, `Dockerfile`,
or `bootstrap_roles.sql` change. The isolated wheel packages
`opportunity_index.py`, `capability_matrix.json`, and all **ten** SQL resources
— nine numbered migrations plus `restore_privileges.sql`. Capability inventory
`84578ae71567ed18`, 274 capabilities, 15 hosted-withheld, Local 8, National 10,
Full Operator 20, JV Partner 11 — verified from the loaded catalog, unchanged,
as this phase adds no capability.

**The twelfth harness error, and the one that mattered.** In round seven a
multi-edit Python script raised `AssertionError` partway through, before its
single `write_text` at the end — so the *entire* batch was discarded. Its
traceback printed on the same screen as `compiles` and `47 passed`, and I read
the screen as success and recorded the repair as landed. Two round-eight
reviewers found the code did not contain it. Unlike the eleven before it, this
one did not produce a wrong number; it produced a **true-looking record of work
that had not happened**. The rule it earns: an edit batch is verified by reading
the file back, never by the exit status of whatever runs next.

**A process rule this program had already written down and I failed to apply.**
A round-nine reviewer delivered a complete verdict, I began applying its
findings, and it then woke, re-computed the freeze hash, and correctly reported
that the candidate it had reviewed no longer existed on disk. Its evidence was
unaffected — every measurement predated the edit, and its harnesses ran against
its own copies with `PYTHONPATH` forced — and its verdict attaches to the
candidate it measured. But the ledger already carried this exact rule from an
earlier phase: *a completion notification is not the same thing as a released
hash; the candidate stays frozen until every attached reviewer has both reported
**and detached**, or a late waiter produces a mismatch indistinguishable from
real drift.* I had the note and did not apply it. Repairs during a held review
belong in a staging copy; the tree the reviewers were handed does not move until
they are gone.

**The eleventh harness error, disclosed rather than retried away.** A
full-suite run on this tree returned `2 failed, 5030 passed, 4 skipped, 20
errors`, with the failures and errors in `tests/postgres` — most visibly
`test_request_scoped_domains.py`. It is not a regression, and here is why,
measured rather than asserted:

- `uptime` reported a load average of **56** on a 10-core machine. An unrelated
  program on this workstation — an ERIKA Quest promotion audit, in a separate
  tree that touches no file of this repository — was running three concurrent
  `pytest tests/` suites of its own. Each PostgreSQL test here starts a
  disposable postmaster; at 5.6× oversubscription those starts time out and the
  fixture errors.
- `tests/postgres/test_request_scoped_domains.py` run on its own immediately
  afterwards: `8 passed in 15.48s`.
- The same contended window also had my own wheel build, surface suite, and
  several probes running against the machine, which I had started concurrently.
  That part was my error.

- The clean run, started only once load had fallen to `5.10` and finished at
  `5.25`, returned `5,052 passed, 4 skipped` in **263.78s**. The contended run
  took **1,461.29s** for the same work — 5.5× slower. That ratio is itself the
  corroboration: a code regression does not make a suite five times slower.

This is the same class as the `LC_ALL` gate: a red that comes from outside the
repository is not release evidence, and neither is a green obtained by rerunning
until the machine cooperates without saying so. Both runs are recorded, with
the load average at the start and end of each, so a reviewer can judge the
explanation rather than accept it.

Two more gates need their result stated precisely rather than as a pass:

- **Credential scan.** Restated, because the earlier version of this bullet was
  false and both round-four reviewers caught it. It claimed "exactly one hit …
  No source, config, or test file hits" — asserted from a scan I had piped
  through `grep -v "^tests/"`, so the clause about test files was excluded from
  the measurement that was supposed to establish it. The same
  vacuous-measurement shape as the empty-`all()` assertion below. The real
  result, over every tracked and untracked non-ignored file with the pattern
  `sk_live_|sk_test_[A-Za-z0-9]{10,}|pk_live_|whsec_[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----`:
  **10 hits in 5 files** — 4 in this document, 3 in
  `tests/platform/test_production_secret_inventory.py`, and 1 each in
  `tests/platform/test_secret_boundary.py`, `tests/platform/test_stripe_launch.py`
  and `tests/test_hosting.py`. Every one is a synthetic canary with no key
  material: the tests that prove live keys are rejected necessarily contain
  live-shaped strings, and this document quotes them when describing what was
  fixed. The invariant holds; the sentence that claimed it did not.

  The count has now moved twice for the same reason, and both moves were mine.
  Round-four reviewers measured 8; writing the correction added `sk_live_` a
  third time, inside the pattern the bullet quotes, making 9; round five's
  write-up added a fourth, making 10. That is the smallest possible
  demonstration of why this gate reports a count and a file list rather than an
  absolute — a scan whose own write-up moves the number needs the number shown,
  not asserted, and a reviewer who reproduces 10 rather than 9 has found
  bookkeeping, not a leak.
- **Listener.** There is no MedawarCRE listener on any port. There *is* an
  unrelated listener on 127.0.0.1:8000 — a system Python 3.9
  `http.server`, PPID 1, started 05:15 today, outside this repository and its
  virtualenv. So the gate as historically written, "no port-8000 listener,"
  does not pass; the invariant it exists to protect — that no hosted server of
  ours is accidentally exposed — does. It is left running, because it is not
  this program's process to stop.

Catalog fingerprint moves deliberately, from
`bf1bc746d6269d976d4b687b8ccef685a1088bb23d580fa629dd3c856da05e70` to
`e452f1486a6d2c22731b0f854498d9a4728a9375ac602a5ab217629265a1cbf6`, recomputed
from a disposable cluster with all nine migrations applied. It moved seven times
across this phase — and did **not** move in round seven, whose repairs were all
in the module; recomputing it from a clean cluster and finding it unchanged is
itself the check that no schema drifted. The moves: at the opening; when the archival trigger was added; when
the trigger condition widened; when the keyset index was corrected; when the
round-four repairs added the canonical-merge-target trigger and made the
membership key deferrable; and when the round-five repairs dropped
`property_type` from the shared entry, added the dependents check and the target
lock, and admitted `suppressed` to the merge CHECK; and when the round-six repairs
made the market index an expression index and narrowed the saved-search
`ON DELETE SET NULL` to one column. Each move is a schema change this record
names rather than a value quietly refreshed to make a test pass. Six reviewers
across three rounds recomputed the then-current value from their own clean
clusters and matched; this one awaits the same.

### Four defects the gates found, none of them in the index itself

Recorded because each was a latent assumption that only a ninth migration could
expose, and three were in tests rather than in the new code.

1. **`restore_privileges.sql` did not know about the new table.** The backup
   suite failed on a fingerprint mismatch *after restore* — the source database
   had the reviews grants and the restored one did not. Exactly what that
   contract exists to catch, and it caught it.
2. **Three tests encoded "the last migration" when they meant "0008".**
   `migrations[:-1]` meant "everything before the deal upgrade" only while 0008
   happened to be last; adding 0009 silently turned it into "everything
   including 0008", so a pre-0008 legacy row could no longer be inserted and the
   failure surfaced as an unrelated-looking RLS violation on `deals`. They now
   slice by version.
3. **The `test_isolation` fixture predated mandatory provenance.** Migration
   `0009` makes `origin`, `observed_property_identity` and `source_observed_at`
   NOT NULL and binds the origin to its tenant record, so a fixture inserting
   only the `0001` columns fails. An earlier version of this sentence said
   `source_user_id` was NOT NULL. It is not — `0009` adds it as a bare nullable
   column, and its composite membership foreign key is MATCH SIMPLE, so NULL
   satisfies it. A reviewer inserted a source row with no source user and the
   database accepted it. The rejection of unattributable observations rests
   entirely on one Python guard. An earlier version said it was pinned; a
   reviewer deleted it and the suite stayed green, so it is pinned now; making the column NOT NULL
   belongs to a follow-up migration. It now supplies a real deal
   and member — a faithful fixture, not a relaxed assertion; that test's own
   expectations are unchanged.
4. **My first RED module used `pytest.importorskip`** and reported `1 skipped`,
   which asserts nothing. Replaced with a plain import so a missing module is a
   failure. Caught in minutes because the Phase 5J correction taught the shape.

### A tension this phase discovered and did not resolve

**Two** of the twenty-two foreign keys to `workspaces` do not cascade:
`staff_audit_log_workspace_id_fkey` and `access_decision_audit_workspace_id_fkey`.
Every other tenant-scoped table cascades. A workspace referenced by either can
no longer be deleted: audit immutability and tenant erasure are in direct
conflict, and today audit wins silently.

Three earlier versions of this paragraph were wrong, each in a new direction,
and each was caught independently by both reviewers. Recorded in full because a
sentence that keeps being wrong is worth more as a pattern than as a fact.

1. It said `staff_audit_log` was the only such key. `access_decision_audit` is
   the other.
2. It said the workspace becomes undeletable "once any member of staff has
   inspected" it. That overstated the index's role.
3. Correcting (2), it said "a `list_opportunities` call writes a NULL
   `workspace_id`, so inspection alone does **not** block deletion", and then
   that "staff *reads* write a NULL workspace id and do not block deletion".
   Both are false. `list_opportunities` passes
   `workspace_id=filters.workspace_id` into its audit insert, so a
   **workspace-filtered** staff read writes a non-NULL workspace id and blocks
   deletion exactly as an ingest does. Only an unfiltered read writes NULL.

The accurate statement is narrow. **Two** distinct index actions write a
non-NULL `staff_audit_log.workspace_id` and therefore make a workspace
undeletable: a *successful* `ingest_workspace`, and a *successful*
`list_opportunities` call carrying a `workspace_id` filter that names a
workspace which exists. Nothing else does — `get_opportunity`, `record_review`,
`merge_opportunities`, `unmerge_opportunity`, unfiltered listings, a listing
filtered by an absent workspace, a filtered listing **refused** for an invalid
`limit` or `cursor`, and a **failed** ingest all write NULL.

That second "successful" is the seventh correction to this paragraph, and a
round-ten reviewer measured the full action matrix to establish it.

This paragraph has now been wrong six rounds running, and three of the errors
were introduced by the corrections themselves. Round four said "Three" and then
enumerated two. Round five's replacement said `ingest_workspace` "always" writes
non-NULL. Round six's replacement said a failed ingest writes NULL, which was
false as written: `_audit_out_of_band` tried the *linked* row first and only
fell back to NULL when the foreign key itself failed, so a failure on an
existing workspace linked it. Both round-six reviewers measured that
independently.

The sentence is true now because the **code** changed to make it true, not
because it was reworded a fourth time: a failed ingest writes an unlinked row
deliberately, so an action that did not happen cannot create a tenant-erasure
blocker, and a test reads `workspace_id` and then deletes the workspace to prove
it. Six rewrites of a sentence is a signal the underlying behaviour was the
thing that needed fixing. Separately,
`access_decision_audit` records a workspace-scoped row on every authenticated
customer tool call, so any workspace that has ever made one call was already
undeletable before this phase existed. So the index widens an existing tension
rather than creating it, and it widens it further than the previous correction
admitted.

Resolving it belongs to the privacy and retention phase, which must decide
whether audit rows are anonymized, detached, or retained under a lawful-basis
exception.

Deal-level deletion does propagate correctly and is pinned: removing a deal
removes its contribution and leaves the other workspace's intact. An entry whose
last observation is gone is archived by trigger. Archival removes it from
default listings; the row keeps its `property_identity`, and a staff request
with `include_archived` still sees it — so the honest claim is that the address
stops being *listed*, not that it stops existing.

### First review round: both rejected, and both were right

Two fresh reviewers reproduced the frozen hash unchanged, every gate number, the
RED, the fingerprint from a clean cluster, and the whole customer boundary — one
of them by forcing `GRANT ALL` onto `medawarcre_app` and confirming each of the
three layers still holds *alone*. Both then returned CHANGES REQUIRED.

**Two data-correctness defects in the new code, both repaired.**

The `ON CONFLICT` update list omitted `opportunity_id` and the observed identity
columns, so an observation stayed filed under whichever property it was *first*
seen at. A reviewer corrected a deal's address, re-ingested, and got two
workspaces reported as looking at the same building when the data said otherwise
— plus a second, sourceless entry nobody contributed to. That is the failure the
contract names as worst, and it is now re-bound on conflict.

Pagination could skip entries, because the sort key `last_observed_at` is
mutated by re-ingest — the contract's own supported workflow. Ordering now uses
the immutable `created_at`, so the order a cursor pages through cannot change
underneath it.

**Three false sentences in this record, all mine, all corrected above.** The
`source_user_id` NOT NULL claim (it is nullable; a reviewer inserted a source
row without one). The claim that `staff_audit_log` was the only non-cascading
foreign key to `workspaces` (`access_decision_audit` is the other). And the claim
that staff inspection makes a workspace undeletable. The replacement written in
this round — "a `list` writes a NULL workspace id" — was itself false, and is
corrected in the workspace-deletion paragraph above; it is named here only as
the first of four attempts at that one sentence, not restated as fact.

**Two contract promises were not implemented.** An entry whose last observation
is deleted is now archived by an `AFTER DELETE` trigger — repository code could
not do it, because the deletion happens in the tenant's own tables and cascades
here without the index being called. Before this, a normalized property address
survived the deletion of every record it came from and stayed in the default
staff listing. And `MAX_SCAN` was declared and never referenced, making a
scan-cap requirement look implemented; the constant is removed, and the contract
sentence — which a later reviewer found still standing after the code change,
making the contract rather than the code the thing that lied — is withdrawn too.

Adding the trigger moved the catalog fingerprint again, to
`72b6ef04f27cd147aaa66098627c5db24dc49b84ad9acd7ebc20fa2a9198d2ae`, and required
declaring `archive_sourceless_opportunity` in the release function contract —
the backup suite caught its absence, the second time in this phase that contract
has caught something real.

### Second review round: the repairs interacted, and both reviewers found it

Both reviewers reproduced the repaired hash, every gate, the fingerprint, and
the customer boundary — one re-probing all three layers independently — and both
returned CHANGES REQUIRED again. Three of the findings were **created by the
interaction of the previous round's own two repairs**, which is the sharpest
lesson of this phase.

Re-binding moves a source row by **UPDATE**; the archival trigger fired only
`AFTER DELETE`. So correcting the address of a property's only observation
vacated its entry without deleting anything, leaving an `active` entry with zero
sources still in the staff listing — the exact artifact the trigger was added to
prevent. One reviewer then showed it outliving complete tenant erasure: every
tenant record deleted, and a normalized address still listed with no
contributors. The trigger now fires on `DELETE OR UPDATE OF opportunity_id`.

Archival was a one-way door. A tenant deleting and re-creating a deal got
`admitted=1` and an entry that stayed `archived` and invisible — a live tenant
record bound to a listing staff could not see. Re-observation now returns an
archived entry to `active`, and only from `archived`, so a merge link is never
silently undone.

The trigger was narrowed to `status='active'` while the default listing admits
`merged` and `suppressed`. A merged entry whose last deal was deleted stayed
visible with zero contributors, reachable through the public
`merge_opportunities`. Widening it exposed a real schema conflict: the merge
constraint was an equivalence, `(status='merged') = (merged_into IS NOT NULL)`,
which made archiving a merged entry impossible. Since the contract requires
duplicate relationships be retained, archival must not clear the link — so the
equivalence is now two implications and the link survives.

Two more from the same round. The keyset index still indexed
`last_observed_at` after the sort key moved to `created_at`, so every page was a
sequential scan and sort — the index added for keyset pagination no longer
served it. And the `MAX_SCAN` removal had landed in code only: the contract still
promised a scan cap, making the *contract* rather than the code the thing that
lied. This record then said "Both fixed." Only the contract sentence was: the
index was still led by `status`, which no listing predicate is equality-bound
on, so it still did not serve the order. Round three caught that, and the round
two sentence was a claim rather than a measurement. It is `(created_at DESC,
id DESC)` now, and pinned by a test that reads the index definition and the
listing's `ORDER BY` and requires them to agree.

**And two more false sentences of mine.** The claim that the attribution guard
"is now pinned" — a reviewer deleted `or created_by is None` and all 285
PostgreSQL tests stayed green; `deals.created_by_user_id` is nullable, so a row
predating the 0008 attribution upgrade would have been admitted with a null
source user. It is pinned now, by a test that nulls the column. And the claim
that "the index does not make the tension bite" over-corrected the previous
round's overstatement into a new one — see the corrected workspace-deletion
paragraph above, which is the third rewrite of that sentence.

Three new pins cover the re-bind orphan, merged-entry archival, and the
attribution guard. Suite `5,048 passed, 4 skipped`; PostgreSQL `288 passed`;
fingerprint moved again to
`28e240cd9384a49f640b3d8c4d0ee80522b01a79bcb3c37cef4ac031602c2eb3`.

### Third review round: the round-two repairs interacted again

Both reviewers reproduced the frozen candidate
`e8ffe0e42c4aa530b2754c4cbbce0ed51adff6e141d48e831faf74b71904456c` unchanged and
both returned CHANGES REQUIRED with two HIGH findings — and, for the second
round running, both findings were produced by the *interaction of the previous
round's own repairs* rather than by the original code.

**Merging an already-archived entry resurrected it.** Round two made
re-observation lift an entry from `archived` back to `active`, and widened the
archival trigger to cover `merged`. `merge_opportunities` set `status='merged'`
unconditionally, so merging an entry that the trigger had already archived put
it back in the default staff listing with zero sources and no way to leave —
re-observation only lifts entries whose merge link is NULL. Merge now preserves
`archived`, and the re-observation lift is narrowed to entries with a NULL
merge link.

**A merge → delete → re-create → re-ingest sequence aborted the whole ingest,
across tenants.** The relaxed merge CHECK still forbade `status='active'` with a
non-NULL `merged_into_opportunity_id`, so lifting a merged-then-archived entry
back to `active` on re-observation violated it. Because `ingest_workspace` runs
one transaction per workspace, that CHECK violation aborted the entire ingest —
and one reviewer confirmed the blast radius crosses tenants: an unrelated
workspace C sharing nothing with the merged property could no longer be ingested
at all. This is the sharpest finding of the phase, because it is the one place
where a per-workspace failure escaped its workspace. Fixed by the same
narrowing: an entry carrying a merge link is never lifted to `active`.

Three new pins cover both: a merged duplicate surviving deletion and
re-observation, a merge against a missing id being refused rather than audited
as a success, and the keyset index matching the listing's order.

**Two more false sentences of mine, both corrected above.** The
workspace-deletion sentence, wrong for the third consecutive round and in a new
direction each time. And the "Both fixed" claim about the keyset index, which
was a claim rather than a measurement.

### Fourth round: two gaps closed before the reviewers were asked again

The carried-limitations list below said "four of the seven filters" were
unpinned. That number was propagated, not measured; a reviewer said six. So I
measured it: eight mutations, each making exactly one filter argument silently
ignored, each run against the focused suite, with a green control from the
identical command.

| Filter argument | Before the new pin | After the new pin | After the round-four repairs |
| --- | --- | --- | --- |
| control (unmutated) | 17 passed | 18 passed | 27 passed |
| `market` | 17 passed — **survived** | 1 failed, 17 passed — killed | 1 failed, 26 passed — killed |
| `property_type` | 17 passed — **survived** | 1 failed, 17 passed — killed | 1 failed, 26 passed — killed |
| `min_score` | 17 passed — **survived** | 1 failed, 17 passed — killed | 1 failed, 26 passed — killed |
| `max_score` | 17 passed — **survived** | 1 failed, 17 passed — killed | 1 failed, 26 passed — killed |
| `stage` | 1 failed, 16 passed — killed | 2 failed, 16 passed — killed | 2 failed, 25 passed — killed |
| `outcome` | 17 passed — **survived** | 1 failed, 17 passed — killed | 1 failed, 26 passed — killed |
| `source_user_id` | 17 passed — **survived** | 1 failed, 17 passed — killed | 1 failed, 26 passed — killed |
| `workspace_id` | 17 passed — **survived** | 1 failed, 17 passed — killed | 1 failed, 26 passed — killed |

The third column re-measures after the round-four repairs moved `property_type`
onto the per-source path, so the mutation targets that column instead of the
canonical one. Restoring the file reproduced the control in every run.

Seven of the eight filter arguments — six of the seven contract facets — were
unpinned. Both my "four" and the reviewer's "six" were stated without this
table; the measured answer is above. The restored tree reproduced the control
in both runs, so neither column is a broken-harness artifact.

The single existing filter test applied five filters at once and asserted only
`0 < len(entries) < 7`, which any one of them satisfies alone. The new
`test_each_declared_filter_facet_narrows_on_its_own` builds three observations
that every facet splits differently and asserts the **exact** returned set for
each facet on its own. The right-hand column is that test being re-measured by
the identical command, not a claim that it works.

This is a coverage gap closed rather than a defect fixed: no filter was wrong,
and no customer boundary was involved. It matters because a quietly ignored
filter on a cross-tenant staff index returns another workspace's observation to
someone who asked not to see it.

**And a vacuous assertion in the most important test of the phase, found by
re-reading rather than by a reviewer.**
`test_no_customer_capability_can_name_the_index` walked `src/` for modules
importing the index and asserted `all(o.startswith("cre_mcp/platform/") for o
in offenders)`. Nothing imports the index yet, so `offenders` was empty and that
`all()` passed without inspecting anything — and the test closed with
`assert CUSTOMER_SURFACE is not None`, which asserts nothing at all. It was
green, it was one of the three customer-boundary tests written first on purpose,
and it was proving nothing. This is the third appearance of this exact shape in
the program, after the `importorskip` skip and the assertion replaced by another
vacuous assertion under a comment claiming otherwise.

Rewritten with both controls and a scan floor: the import detector must flag
four realistic import spellings and must *not* flag a bare string mention, and
the walk must visit more than 200 modules or fail — it visits **472**, since
`src` holds 473 `.py` files and the walk skips `opportunity_index.py` itself. An
earlier version of this sentence said 473; a reviewer counted. Then proven rather
than asserted: appending one `from cre_mcp.postgres.opportunity_index import
InternalOpportunityIndex` to `src/cre_mcp/surface/catalog.py` — a
customer-surface module — turned it red (`1 failed in 2.52s`); restoring the
file turned it green again (`1 passed in 1.60s`), with `git diff --stat`
confirming the victim was left unmodified.

### Fourth review round: both rejected, and the boundary held again

Both fresh reviewers reproduced candidate
`5e9c60d4770c22c3172ee7ba360b5b48ba33e8e61db2b7e710550f6e0407b8a7` (1072 files)
unchanged at start and end, and both returned CHANGES REQUIRED. Both were given
the load-average warning and both recorded that every run sat between 4.9 and
9.4 on the 10-core machine, so no result below is contended.

**The customer boundary held, attacked harder than in any previous round.**
Both reviewers ran `GRANT ALL` on all three index relations to `medawarcre_app`
— one also granting `EXECUTE` on `internal_authorized()` and
`internal_can_mutate()` — against a **populated** index rather than an empty
one, which matters because "0 rows" from an empty table proves nothing. A
customer session then read 0 rows from all three relations; still 0 rows when it
forged `app.internal_role='owner'` with a reason; and still 0 rows when the
forged actor was a **real, live, active** `staff_roles` owner. Every policy on
these relations is `TO medawarcre_admin`, so no policy applies to the app role
and RLS denies wholesale. Layer 2 and layer 3 were then each confirmed alone.
84 of 84 grant probes across seven non-admin service roles raised
`InsufficientPrivilege`. No reachable path was found from any customer surface.

Both also reproduced every gate number, the fingerprint from their own clean
clusters, the wheel contents, the locked counts, and the round-four filter
mutation table **cell for cell** — one rebuilt the "before" column by deleting
the new pin.

**Two HIGH defects, one of which both reviewers found independently.**

*A tenant-controlled string aborted a whole workspace's ingest, untraced.*
`internal_opportunities_property_type_check` bounds that column; ingestion is
one transaction per workspace; nothing validated the tenant-supplied value. An
empty string, an untrimmed one, or one over 128 characters aborted every other
deal in that workspace — permanently, on every retry, with **no audit row at
all**, because the audit insert is the last statement in the transaction. One
reviewer drove it through the customer role's own column grant: an ordinary
`UPDATE deals SET listing = listing || '{"property_type":""}'` inside the
tenant's own workspace turned a working `admitted=4` into a total abort. No
attacker is needed — the Crexi mapper emits an unbounded `", ".join(types)` and
LoopNet's comes from scraped HTML. Blast radius is one workspace, but this is
the exact class round three declared closed, and it contradicts the contract's
own stated failure mode: an observation the index cannot carry is *rejected and
counted*, which is what `IngestSummary.rejections` exists for.

Fixed at the boundary: blank and untrimmed values normalize, an over-long one is
rejected and counted rather than truncated — truncating would make the
`property_type` filter answer for a value the tenant never declared. A failed
ingest now writes `result='failed'` on its own connection, falling back to an
unlinked audit row when the workspace foreign key is itself the reason the work
failed.

*The `property_type` filter answered from one workspace only.* The `ON CONFLICT`
update list refreshed only `last_observed_at`, `status` and `updated_at`, so
`title`, `market`, `property_identity` and `property_type` on the canonical row
were write-once by whichever workspace observed the property first — and the
filter read that canonical row rather than the per-source `EXISTS` every other
facet uses. A reviewer had workspace B declare the same building industrial;
staff filtering the cross-tenant index for industrial were not shown it. On the
one structure in this program built to combine tenants, a declared facet
silently dropped a tenant's answer. The same write-once behaviour made a
correction unreachable: a deal's only observation could say industrial while the
entry still filtered as office. This is round one's defect, repaired on the
source row and left standing on the parent row.

Fixed three ways: the filter reads `s.observed_property_type`; the canonical row
refreshes on conflict; and `property_type` joins outcome and stage as a reported
**conflict**, with both workspaces named, because two tenants can legitimately
call the same building different things and the entry's label should not settle
that silently.

**A merge cycle was a permanent, cross-tenant black hole.** A→B then B→A was
accepted, and both entries left every default listing for good: re-observation
only lifts entries whose merge link is NULL, and `grep` confirms nothing in the
product ever cleared that link. A reviewer then showed an uninvolved workspace C
observing the same property, being told `admitted=1`, and having its observation
filed under an invisible entry. Fixed by requiring the merge target to be
canonical — enforced by a `BEFORE INSERT OR UPDATE` trigger, since a CHECK
cannot see another row — which makes a cycle of any length unconstructible and
caps chains at depth one. And `unmerge_opportunity` is added, because merge was
otherwise a one-way door, the same shape the archival repair had in round two.

**Concurrent ingest deadlocked, and this one did cross tenants.** Two workspaces
observing the same properties took the `ON CONFLICT` row locks in each
workspace's own deal-id order. A reviewer measured deadlocks in **6 of 8** trials
with the losing side arbitrary, no retry, and no audit row. That falsifies this
record's round-three claim that the CHECK violation was "the one place where a
per-workspace failure escaped its workspace" — it was not. Fixed by resolving
every identity first and taking the contended rows in canonical-key order, which
gives them a total order.

**And the deadlock repair's own test found one more.** With the lock order
fixed, concurrent ingest started failing
`internal_opportunities_observed_order_check`. `statement_timestamp()` is the
real clock time a statement began, so a transaction that blocked on another's
row lock applied a timestamp from *before* the winner had inserted the row, and
`last_observed_at >= first_observed_at` refused it — aborting the whole
workspace ingest again, the third distinct instance of that class this round.
Both `ON CONFLICT` clauses now advance the clock with `GREATEST(first_observed,
last_observed, statement_timestamp())`. Recorded because it was found by the
test written for a *different* repair, which is the argument for pinning a fix
with the scenario rather than the assertion.

**Migration 0009 defeated 0008's deliberate deferrable design.**
`internal_opportunity_sources_user_membership_fkey` was immediate while 0008 had
made the equivalent `deals` keys `DEFERRABLE INITIALLY DEFERRED` precisely so one
offboarding transaction could delete a membership and the rows citing it
together. The identical transaction aborted — but only for workspaces staff had
ingested, so tenant deletion succeeded or failed depending on whether the index
had run. Now deferrable, and pinned.

**Tenant free text lived in the one cross-tenant table.** A reviewer deleted
every source record and read `'Confidential off-market assemblage for Acme
Holdings'` — the tenant's own deal title — back out of the archived entry, which
no role including `medawarcre_migration` can delete once a single review cites
it. The entry label is derived from the normalized address now; the tenant's
words stay in `observed_property_identity` on source rows, which cascade away
with the record that supplied them.

**Raw psycopg errors and an existence oracle.** Filter *names* were validated by
the frozen dataclass; *values* were not, so `workspace_id='not-a-uuid'` reached
SQL. Worse, the audit row's workspace foreign key meant a read filtered by a
non-existent workspace raised `ForeignKeyViolation` **from the audit insert**
while a real one succeeded — a crash where an empty page is correct, and an
oracle distinguishing a real workspace from an absent one. Values are validated
now, an unknown workspace audits without a link and returns an empty page, and
`record_review` and `merge_opportunities` raise `LookupError` instead of leaking
a foreign-key error.

**Three more false sentences of mine**, all corrected above: "Three distinct
index actions" followed by an enumeration of two — a new failure mode for a
paragraph that has now been wrong four rounds running; "it visits 473" when the
walk skips its own module and visits 472; and the credential-scan bullet, which
asserted "No source, config, or test file hits" from a scan I had piped through
`grep -v "^tests/"`. That last is the same vacuous-measurement shape as the
empty-`all()` assertion it sits beside, committed in the very act of writing up
that assertion.

### Fifth review round: three HIGH, all of them round four's repairs colliding

Both fresh reviewers reproduced candidate
`d28be216fc0cac6df13f174128c1e43c8f7c4c874d23d8bead4267b0235fc624` (1072 files)
unchanged start to end, both recorded load between 4.9 and 10.6 throughout, and
both returned CHANGES REQUIRED. **For the fourth round running, every HIGH came
from the previous round's own repairs interacting** — this time with each other.

**The boundary held again, and one reviewer closed a channel I had not
considered.** Both ran `GRANT ALL` plus `GRANT EXECUTE` on the authority
functions against a populated index, forged a real live active `staff_roles`
owner as the actor — `internal_authorized()` returned `true` — and still read
zero rows. One went after the statistics side channel: with SELECT granted and
after `ANALYZE`, `pg_stats` returned **zero rows** for all three relations,
because the view itself carries `row_security_active()`. 84 of 84 grant probes
refused. One reviewer also confirmed the append-only review triggers hold
against `medawarcre_migration` itself, that `medawarcre_admin` can neither
`DISABLE TRIGGER` nor set `session_replication_role`, and that restore parity is
exact at column level, 0 missing and 0 extra.

**And the CHECK-abort class round four closed is genuinely closed.** A reviewer
enumerated every constraint on both relations from the catalog and drove every
value `ingest_workspace` can pass: 16-case `property_type` battery, the
`json.dumps`→`inf` round-trip asymmetry, a 200 KB listing, a 40 KB address, and
the longest authoritative Census city name in the country. `admitted=21,
rejected=0`, no aborts. That was the sharpest defect of round four and it stayed
fixed.

**Tenant free text came straight back through a different column.** Round four
moved `deals.title` off the shared entry and, *in the same round*, made
`property_type` refresh onto it to fix the write-once filter. A reviewer wrote
`'Acme Holdings LP - seller distressed, do not disclose'` through the customer's
own `deals.listing` UPDATE grant, arranged for that workspace to ingest last so
its string won the refresh, then deleted every one of its records — and the
entry was still `active`, still in the **default** listing, still serving those
words. Stronger than the round-four finding, which needed an archived entry.

`internal_opportunities` now has no `property_type` column at all. The filter and
the conflict report already read the per-workspace value; the entry's is derived
at read time, so it disappears exactly when the source rows do. A column that
does not exist cannot hold a tenant's words.

**And my pin was vacuous, for the third time in this phase.** The round-four
test planted the secret in `deals.title` — the one column that had just stopped
being copied — and asserted over `title` and `property_identity` only. It never
read `property_type`. It is rewritten to enumerate **every** text and jsonb
column of the table from `information_schema`, with a positive control that the
secret was actually planted, so it needs no edit when a column is added and
cannot pass because nothing was written.

**Deadlocks got worse, not better.** Round four's canonical-key ordering did not
cover the lock the archival trigger takes: `AFTER UPDATE OF opportunity_id`
fires an `UPDATE` on the entry an observation moves *off*, a row not in the
planned sequence at all. Two workspaces correcting addresses that swap entries
then walked the rows in opposite orders. One reviewer measured 3 aborted ingests
in 10 trials, the other **29 in 30** — against 6 in 8 for the defect round four
was fixing. The setup is two ordinary tenant address corrections, which is the
exact workflow the re-bind repair exists to support. Every involved entry is now
locked up front in `id` order, which is a total order both transactions agree on
and which covers the trigger's row.

**Merge cycles and chains were both still constructible.** The trigger inspected
only the target, with an unlocked `SELECT`. So `C→A` then `A→B` built a depth-2
chain with **no concurrency at all** — "what is C a duplicate of?" answered with
a row that was itself merged, directly falsifying the comment I wrote in
migration 0009 claiming depth is capped at one. And two concurrent merges each
read the other as canonical: 34 cycles in 40 trials through the public call,
rebuilding round four's black hole exactly. The trigger now takes the target
`FOR UPDATE` and refuses an entry that is itself a merge target.

**A merged-then-archived entry swallowed an uninvolved workspace's live
observation.** Staff merge A into B; A's tenant deletes its deal so the trigger
archives A with the link retained; an unrelated workspace then genuinely
acquires A's property and is told `admitted=1` while its observation lands on an
entry that appears in no default listing and matches no facet filter. Caused by
round three's narrowing of the re-observation lift composed with the archival
trigger. Observations now file under the canonical entry — the one staff said
the property is the same as — which is both semantically right and visible.

**A merge round-trip laundered a suppressed entry back into the listing.** Merge
preserved only `archived` and unmerge chose only between `active` and
`archived`, so merge-then-unmerge silently cleared the only mechanism staff have
for hiding an entry. Both now preserve `suppressed`, and the merge CHECK admits
it.

**Refusals were untraced.** `_require_mutation` raised before opening a
transaction, so a `read_only_analyst` attempting four mutations produced four
`PermissionError`s and **zero** audit rows — an attempted privilege escalation
being the case you least want missing from the log. And five existence probes
raised `LookupError` from inside a transaction that rolled its own audit row
back. Both now write out of band, on a fresh connection, because a doomed
transaction cannot carry its own audit.

Also fixed: ingest retries a deadlock three times, so a staff batch survives the
one lock cycle this code cannot order — a tenant deletion takes its locks in
tenant-record order, and a reviewer showed a privacy erasure rolled back in full
because staff ingested at that moment. The deletion side's retry is not this
phase's code and is handed to the privacy phase rather than implied away. And
both `ON CONFLICT` clauses share one `transaction_timestamp()`, so an entry no
longer claims an observation older than its own newest source — measured at
−0.65 ms quiet and **−3.13 s** under contention.

**Three of my nine new pins were decoration, and I caught it by mutating them.**
Reverting each repair should turn its pin red; three did not. The
merge-target-lock and re-bind-deadlock tests raced two threads and hoped, and
the window is too small for hope: both passed with the fix removed. The
timestamp test was fine but my *mutation* was wrong — reverting only the entry
clock leaves the source on the earlier `transaction_timestamp()`, so no lag
appears and the mutant survives vacuously.

Rewritten: the cycle test sequences the two transactions explicitly so the
second statement is *known* to begin before the first commits, and the re-bind
test drives the un-retried path — `ingest_workspace`'s retry would otherwise
hide exactly what it looks for. Its width was measured, not guessed:

| Configuration | Detection without the fix | False positives with it |
| --- | --- | --- |
| 2 properties × 6 rounds | 0 of 1 | — |
| 8 properties × 6 rounds | 1 of 3 | — |
| 8 properties × 30 rounds | 4 of 5 | 0 of 5 |
| **20 properties × 30 rounds** | **6 of 6** | **0 of 6** |

All nine repairs then re-measured against the corrected mutations: every one
kills its pin, with the control and the restored tree both at 36 passed.

### Sixth review round: the pins were the defect

Both fresh reviewers reproduced candidate
`f059f4b8352f4a79d0cc19e89da5183e89d60c867f094e53eca89cb6f0178f8a` (1072 files)
unchanged start to end, recorded load between 5.3 and 11.4 throughout, and both
returned CHANGES REQUIRED. This round is different from the five before it: the
code was mostly right, and **what failed review was the evidence**.

**The boundary held, against three side channels nobody had tried.** Beyond
`pg_stats` (0 rows, because the view carries `row_security_active()`), a reviewer
checked `pg_class.reltuples` — **−1**, never analysed, and the app role cannot
`ANALYZE` — `pg_stat_all_tables`, all zeros, and `pg_total_relation_size`, which
returns the base allocation and no cardinality. **168 privilege probes** across 8
non-admin roles × 3 relations × 7 privileges found exactly **three** grants, all
`medawarcre_backup SELECT`. The only `SECURITY DEFINER` function the app role can
call names no index relation. The other reviewer independently repeated the
populated-index `GRANT ALL` attack with a forged live staff owner and also got
zero rows.

**I claimed all nine round-five repairs killed their pin. Eight did not.** I ran
nine mutations; one reviewer ran **34** and the other **13**, and between them
they found that the following were verified by nothing: the whole read-time
`property_type` derivation — `grep '\.property_type'` over the test file returned
**nothing**, so no test read round five's headline repair at all; the same
derivation picking a winner where workspaces disagree, which the contract
forbids; the pre-lock's `ORDER BY id`, which is the *entire* argument for that
repair; the three-attempt deadlock retry, which survived even across all 310
PostgreSQL tests; the repository half of the merge cycle guard; the canonical
head being lifted out of `archived`; `source_observed_at` being refreshed; and
the per-source `property_type` index.

The lesson is sharper than the three vacuous-assertion findings before it. I did
run a mutation matrix, and I did report it honestly — but **I chose the nine
mutations**, and I chose them from the same understanding that wrote the code.
A builder's mutation matrix measures what the builder thought to doubt.

Ten new pins close all eight, and the matrix that proves it is now fourteen
mutations wide.

**A reviewer also found the harness trap that makes this worse.** An editable
`.pth` pins `cre_mcp` to this working tree, so a mutation harness that copies the
repo and edits the copy silently tests the *original* — that reviewer's first
full run reported all 13 mutants surviving, which is the signature. My own script
mutates this tree in place with backup and restore, so it was never affected, but
any reviewer building a copy-based harness will hit it and should force
`PYTHONPATH`.

**Tenant free text was still on the shared entry, through a third channel.**
Round four closed `deals.title`; round five closed `property_type` by deleting
the column and wrote "a column that does not exist cannot hold a tenant's
words". `listing.address` was the column that does exist. `_normalized_street`
uppercases and strips punctuation and bounded nothing, so a reviewer put
**88,011 characters** of tenant text onto `internal_opportunities.title` and
`property_identity` — admitted, entry `active`, still in the *default* listing
after that tenant's total erasure, still serving the words.

And **my round-five pin missed it in the fourth instance of the same shape**: it
enumerated every text and jsonb column correctly, then planted the secret only in
`deals.title` and `listing.property_type` — the two channels already closed —
while leaving `listing.address` clean, and its positive control checked the
source rows, which did receive it. Green, and testing nothing that was still
open.

The address is bounded now at 120 characters, rejected and counted like any
other observation the index cannot carry. The honest claim is narrower than the
one I withdrew: a normalized street address is tenant-supplied and does reach
the cross-tenant entry, because identifying a property across tenants is what
this structure is *for*. It is bounded, normalized, and disclosed — not absent.

**Both reviewers found the pre-lock incomplete, independently.** It covered
planned canonical keys and entries this workspace's sources already point at.
When a matched entry is merged the observation files under the head, and the
foreign key takes `FOR KEY SHARE` on that head — a row in neither set, free to
sort earlier. Measured at **13 aborted ingests in 30 rounds** by one reviewer and
as a deterministic deadlock sequenced through `pg_stat_activity` by the other.
The locked set is now closed under merge links.

**And `merge_opportunities` did not use the order it demanded of everyone else.**
It locked the target first and then updated the source, so whenever
`source.id < target.id` it walked the same pair opposite to the ingest pre-lock
and two ordinary public calls deadlocked. A total order is only total if every
writer uses it. Merge now takes both rows in `id` order before inspecting either.

**A deadlocked mutation wrote no audit row at all.** `_Refused` covered the
checks the code makes and never covered the transaction dying underneath them —
the same untraced-action class round five closed for role denials and missing
objects, left standing for aborts, and made reachable by the two findings above.
All three mutations now audit any failure out of band.

**The workspace-deletion sentence was wrong for the sixth consecutive round**, and
for the second consecutive time the error was introduced by the correction.
`_audit_out_of_band` tries the linked row first, so a failed ingest of an
*existing* workspace wrote the link and made that workspace permanently
undeletable exactly as a success does. Fixed in the behaviour rather than the
prose: an ingest that did not happen no longer creates an erasure blocker, and
the workspace id stays on the row in `object_id` so nothing is lost.

Two smaller ones, both in things round five had touched: the market index was
rebuilt as `(market, status)` while the listing filters `lower(o.market)`, so
every market filter was a sequential scan — the same defect the keyset index had
in round two, in an index rebuilt to fix something else; and
`internal_opportunity_sources_saved_search_fkey` used a composite `ON DELETE SET
NULL`, which nulls *every* referencing column including `workspace_id NOT NULL`,
so the day `origin='search_result'` is written a tenant deleting a saved search
would get a raw `NotNullViolation` out of a cross-tenant table.

### Seventh review round: a fingerprint is not a pin

Both fresh reviewers reproduced candidate
`fbd508b125f0bc5bf67ee5db2581bb7520f25b10d29227d166e151cbd09f9843` unchanged,
recorded load between 4.6 and 8.7, and both returned CHANGES REQUIRED. Between
them they chose **155 mutations of their own** — 114 and 41 — against my
fourteen.

**The structural finding, and the most important one of the phase.** Every CHECK
constraint, every row-level-security policy, and half the merge trigger on the
Phase 5K relations were "verified" by exactly five tests, none of which exercises
the behaviour: they compare the live catalog to `EXPECTED_CATALOG_FINGERPRINT`.
A reviewer demonstrated the consequence end to end — delete the second
implication from `internal_opportunities_merge_check`, recompute the fingerprint,
patch the constant, and `321 passed`.

A fingerprint is a **drift detector**. It says the schema changed without your
noticing. It is not a **behaviour pin**: it says nothing about what the schema
does, and this record documents refreshing it *seven times in this phase* as
routine. Treating one as the other is how the reviews RLS layer — layer three of
the three-layer boundary story, for one of the three index relations — the
merge-target-is-merged check, and eleven CHECK constraints came to be covered by
nothing at all.

`tests/postgres/test_opportunity_index_guards.py` is the answer: each guard is
now stated as "the database refuses this", exercised through a statement that
violates it. The proof runs **only** the two behavioural files and none of the
five fingerprint tests, so a kill cannot be the fingerprint noticing drift:

| Guard reverted | Result |
| --- | --- |
| merge check, second implication | 1 failed, 51 passed |
| no-self-merge | 1 failed, 51 passed |
| observed-order | 1 failed, 51 passed |
| market bound and trim | 1 failed, 51 passed |
| canonical-key bound and trim | 1 failed, 51 passed |
| entry status vocabulary | 1 failed, 51 passed |
| source score range | 1 failed, 51 passed |
| source origin binding | 1 failed, 51 passed |
| **reviews RLS read policy** | 1 failed, 51 passed |
| **reviews forgery guard** | 1 failed, 51 passed |
| merge trigger, target-is-merged | 1 failed, 51 passed |

Control and restored tree both `52 passed`.

**Four contract retention items had no test at all.** Blanking `provenance`
(item 9), flipping `access_class` from `'private'` to `'public'` (item 11), and
dropping the `score`/`stage`/`outcome` refresh from the source upsert (items 6,
7, 8) each left all 321 PostgreSQL tests green. The record even called the
access-class constant "fail-safe in direction" — nothing enforced the direction.
All are pinned now, by a test that ingests, has the tenant advance the deal, and
re-ingests.

**A code comment of mine was false, and the mutation that shows it survived.**
The pre-lock comment claimed entries created inside the transaction "cannot
deadlock: a concurrent insert of the same canonical key blocks on the unique
index, which is a single wait, not a cycle." True of one key, false of two: two
ingests creating K1 and K2 in opposite orders each hold one speculative
unique-index entry and wait on the other. `planned.sort` is what prevents it,
deleting it left the suite green, and the retry masked it.

**Two HIGH from the other reviewer, both real.**

An ordinary tenant deleting one of its own deals mid-ingest raised
`ForeignKeyViolation`, which the retry did not catch, so the **entire
workspace's batch was lost** — measured at 6 and 14 failures in 30 trials through
two ordinary public calls. The record claimed the retry meant "a staff batch
survives"; it did not, it failed through a different door at a comparable rate.
The retry now covers the transient set, and the FK case is transient in the sense
that matters: re-reading `deals` finds the row simply gone.

And **every failing read was untraced.** The audit guard had been applied to
mutations only, so under an identical induced failure merge, review and ingest
each wrote one `failed` row while `list_opportunities` and `get_opportunity`
wrote none — against a contract that says "every read **and** every mutation".
It was role-inconsistent too: a bad verdict and a self-merge validated *outside*
the guard, so an analyst attempting them was audited `denied` and an **owner**
was not audited at all.

**This paragraph then claimed "Both reads are wrapped now and both validations
moved inside", and that was false — the repair was never applied.** See the
round-eight section; it is the most serious record error of the phase, and it is
corrected there rather than quietly rewritten here.

**Two more of my pins claimed more than they measured.** The keyset test's name
and docstring say it reads the index definition *and the listing's `ORDER BY`*;
it read only the SQL file, and reverting the listing to the mutable
`last_observed_at` key left 47 focused and 274 other PostgreSQL tests green —
the fifth appearance of this phase's signature shape, in a test written to close
the fourth. And the clock test only fired when *both* upsert clauses were
reverted, so mutating the entry clause alone survived, which a reviewer measured
aborting a whole workspace ingest in 1 of 20 concurrent trials.

**Three corrections to this record and one to the migration.** The migration
still asserted, verbatim, the sentence the contract had already retracted about
merged entries keeping their source rows. "It held in all three rounds" was
written when there had been three. And the unpinned list said "the city/ZIP
convergence check" when a reviewer measured the two branches separately: the
no-ZIP branch **is** pinned and only the ZIP branch is not.

**And round six's side-channel evidence was an artifact.** I recorded
`reltuples = -1` and `pg_stat_all_tables` all zeros as proof that cross-tenant
cardinality does not reach the customer role. A reviewer ran `ANALYZE` and got
`n_live_tup 7 / 14` and `reltuples 7.0 / 14.0` through world-readable catalog
views — autovacuum does this in any real deployment. No *values* leak, because
`pg_stats` carries `row_security_active()` and stays empty, and the other
reviewer confirmed `EXPLAIN` short-circuits to `One-Time Filter: false` with
`Plan Rows: 0`. But exact row counts do, and the measurement I drew the
conclusion from was taken on a cluster that had never been analysed. It is a
PostgreSQL-wide property rather than something this phase introduced, and it is
carried below rather than restated as closed.

### Eighth review round: a repair I recorded as done had never been applied

Both fresh reviewers reproduced candidate
`5aab4c54d8ce0e6f0fbfc4cfcb624b024ec292086ff961494043301364d03919` (1073 files)
unchanged, both recorded load between 4.5 and 8.9, both chose their own
mutations — **126** and a full behavioural fuzz — and both returned CHANGES
REQUIRED with the same blocking finding.

**Round seven's read-audit repair was not in the code.** `_audited_action` had
three use sites, not five; `list_opportunities` had no exception handling at
all, `get_opportunity` only a bare `except _Refused`, and the verdict and
self-merge checks were still outside their guards. Both reviewers measured the
pre-repair behaviour verbatim:

```
INDUCED-FAILURE list:    raised='LockNotAvailable' audit=[]
INDUCED-FAILURE inspect: raised='LockNotAvailable' audit=[]
INDUCED-FAILURE merge:   raised='LockNotAvailable' audit=[('merge','failed')]
owner-bad-verdict:   ('ValueError', [])
analyst-bad-verdict: ('PermissionError', [('review','denied')])
```

The cause is recorded as the twelfth harness error above: an edit script raised
before its write, and I read the traceback as success. **This is the most
serious record error of the phase.** Every earlier vacuous-pin finding was a
test that measured too little; this was a *record asserting work that did not
exist*, in the one area — the audit trail — the contract states as an absolute,
and the third consecutive round in which this document declared the
untraced-action class closed.

It is applied now, verified by reading the file back rather than by the exit
status of the test that followed, and pinned twice: one test drives all five
actions under a held `ACCESS EXCLUSIVE` lock and requires a `failed` row from
each, and one requires an owner's invalid argument to be audited exactly as an
analyst's refused call is.

**And round seven's foreign-key retry was verified by nothing.** Removing
`ForeignKeyViolation` from `_TRANSIENT` — reverting the fix for a defect that
loses an entire workspace's ingest at 6–14 in 30 trials — survived at *every*
scope: 59 focused, 333 PostgreSQL, and the whole repository. The neighbouring
`attempts = 3 → 1` mutation **is** killed, which is exactly what made the gap
easy to miss: the retry looked covered. Pinned now by a test that induces the
foreign-key case specifically.

**Layer one of the customer boundary was pinned for `SELECT` only.** The test
titled "holds no privilege on any index relation" probed one privilege. Granting
`INSERT, UPDATE, DELETE` on the deliberately cross-tenant table to
`medawarcre_app` passed every gate this repository has — not a live breach,
since RLS still denied, but the layer the design leans on hardest
("a grant boundary before it is a policy boundary, so a policy mistake cannot
open the index on its own") had no behavioural pin for writes. It is now 147
probes: 7 customer-reachable roles × 3 relations × 7 privileges, all required to
be denied.

**What both reviewers could not break, and it is the strongest result yet.** The
boundary held on every layer in isolation against a populated index, including
two channels no prior round tried: a **unique-key existence oracle** (PostgreSQL
evaluates the RLS `WITH CHECK` before index insertion, so an existing and a
non-existing `canonical_key` return byte-identical errors) and a **foreign-key
TOCTOU oracle** on `deals` (closed by column-level grants). 147 and 168
privilege probes each found exactly the three genuine `medawarcre_backup SELECT`
grants. Concurrency: **0 of 30** ingest-vs-tenant-delete on the retried path
against **29 of 30** un-retried — the retry doing precisely the job it was added
for — and 0 of 60 ingest-vs-ingest and 0 of 30 ingest-vs-merge on both paths.
Tenant erasure in six orders confirmed round seven **removed** the blocker
rather than moving it. Five randomized 70-step staff sequences held every
invariant. And the workspace-link paragraph — wrong for six consecutive rounds —
was verified correct in all ten of its cases by one reviewer and all twelve by
the other.

### Ninth review round: layer two of the boundary had no test at all

Both fresh reviewers reproduced candidate
`ff6bce4087adc523d8a17e635552e946547fa1360ce2acad04c5c73080dd5d38` and both
returned CHANGES REQUIRED. One chose **76** mutations, the other **24** plus a
1,500-step randomized staff fuzz.

**The blocking finding: `PostgresDatabase.connection()` refusing internal
authority on an `app` pool was pinned by nothing.** The contract names exactly
two independent fail-closed mechanisms and this is the second; the module
docstring calls it one of "three separate ways". A reviewer replaced the guard
with `pass` and the focused suite, all of `tests/postgres`, and the whole
repository stayed green — because `AuthorityContext.internal` is constructed
**zero times anywhere in `tests/`**. Four neighbouring mutations survived too:
an admin pool accepting a tenant context, `AuthorityContext.internal` accepting
a role outside the vocabulary, the same accepting a blank reason, and the pool's
`_reset` of all five `app.*` context keys deleted entirely.

`test_the_index_refuses_a_non_admin_runtime` looked like the pin and is not: it
tests the *index constructor's* `runtime_mode` check, a different mechanism from
the one the contract states. That check is pinned; the stated one was not. Four
of the five are pinned by one test that drives both wrong-authority directions,
both contextless branches, and the two `AuthorityContext.internal` validations.

**An earlier version of this sentence said "All five are pinned now" and it was
false.** That test drives six things and `_reset` is not among them; a round-ten
reviewer deleted the `_CONTEXT_KEYS` loop and 5,099 tests stayed green. The
fifth is pinned in round ten — see the note there on why it had to be pinned by
reading the source rather than by behaviour.

**The read path kept the audit gap round eight closed for the mutations.** Round
eight moved the verdict and self-merge checks inside their guards so an owner's
invalid argument is recorded — and left `list_opportunities`' own `limit` and
`cursor` validation above its guard. A reviewer measured **96 unrecorded
refusals across 1,500 randomized staff steps**, the only invariant that run
violated. `list_opportunities` is now a thin wrapper that opens the guard before
delegating, so the validation happens inside it.

**And the positive half of the six-times-rewritten workspace claim had no pin.**
Mutating the audit link to `None` survived 63 focused and 337 PostgreSQL tests
while turning a workspace that should be undeletable into a deletable one. The
negative branch was pinned; this one was not. It now asserts the link *and* the
consequence — the workspace delete is refused.

**Two smaller ones.** The round-eight layer-one pin used `has_table_privilege`,
which cannot see **column-level** grants — the dominant idiom in this schema, 45
of them in `restore_privileges.sql` alone. A reviewer appended
`GRANT SELECT (canonical_key, title, market, status) … TO medawarcre_app` and
all 147 probes passed. Worth stating precisely: the boundary still held — layer
3 returned 0 rows with that grant live, and `test_backup_restore`'s
`has_column_privilege` check caught it *behaviourally*, surviving the
fingerprint-refresh demonstration. Only the test that claims to defend layer one
was blind. And `object_type` was the constant `'internal_opportunity'` on every
row including `ingest`, whose `object_id` is a workspace — an audit row that
misnames its object being the same category of defect as one that is missing.

**What neither reviewer could break.** The customer boundary, each layer alone,
against a populated index: 72 read probes across three actor postures including
a forged real live active staff owner, plus `COPY`, `TABLESAMPLE`, `ctid`/`xmin`,
CTEs, and `string_agg` — 0 rows every time. Every escalation refused, including
`SET SESSION AUTHORIZATION`, `DISABLE ROW LEVEL SECURITY`, `CREATE POLICY`,
`CREATE FUNCTION … SECURITY DEFINER`, and a foreign key referencing the index.
New channels neither prior round tried: column-level grants (none shipped),
`pg_locks` (0 rows), `pg_stat_activity` query text (`<insufficient privilege>`
for the staff session), and the cascade-write channel (the app role holds no
table privilege on `deals` and cannot DELETE at all). All three concurrency
races at 0/32 on both the retried and un-retried paths, with a positive control
that detected 5 of 5 induced deadlocks. Every round-eight repair verified real
and pinned — including all five `_audited_action` call sites, counted rather
than read.

### Tenth review round: the first approval, and a pattern named

Both reviewers reproduced candidate
`1fcf88805028fde2a306662450d966d47df8a5f998a2c7e862f982262340da49` unchanged at
both ends — the tree did not move this time — and one of them **APPROVED**. That
is the first approval in ten rounds and eighteen reviewers.

The approving reviewer drove 6,000 randomized staff steps across four seeds with
a hard per-call invariant and recorded **zero** zero-row calls, zero multi-row
calls and zero attribution violations; paged at ten different limits against an
unpaged baseline with field-by-field comparison of every entry; ran 8 × 35
concurrency trials at **0/35** on the public path in all six shapes plus four
4-way configurations; walked tenant erasure in nine orders; and killed 35 of 35
self-chosen mutations. It confirmed round nine's 96 unrecorded refusals per
1,500 steps are gone, and that the `list_opportunities` split changed nothing a
read returns.

**The other returned CHANGES REQUIRED on a record error of mine, the third of
its exact kind.** Round nine's section said the pool guards were "All five
pinned now"; the test drives six things and `_reset` is not among them.
Round eight was a repair recorded as applied that never was. Round nine was a
test that defended an adjacent mechanism. This is a claim written from what I
*intended* a test to cover rather than what it executes.

The rule that earns, and it is mechanical: **run the mutation before writing the
"is pinned" sentence.** It paid immediately — my first attempt at pinning the
four pool guards was itself vacuous for two of them, and mutating first is what
caught it.

**Why two of those had to be pinned by reading the source.** `_reset` and the
transaction scope of `set_config` are *redundant*: with the context set
transaction-locally it vanishes at commit whether or not `_reset` runs, and
`_reset` clears it whether or not the scope is transaction-local. Neither is
observable alone. The reviewer reached the same conclusion from the other
direction — it tried to compose both mutations into an authority leak and could
not, because `bind_admitted_request` re-sets the tenant keys and blanks the
internal ones transaction-locally. Redundant defence is worth keeping and cannot
be pinned by behaviour; asserting the source says what the design says is the
alternative to a passing probe pretending to have measured it.

**Both reviewers independently found the same three things**, which is what made
them the priority: the round-nine guard could make one read write **two** audit
rows (the success row commits with the transaction, then anything raising during
page assembly added a `failed` row beside it — no data-driven trigger found, but
the contract says exactly one); two "still unpinned" entries had gone stale; and
the workspace paragraph needed its seventh correction, because a filtered read
*refused* for a bad argument writes NULL.

**And one more vacuous assertion, found by the approving reviewer.**
`assert all(position.source_user_id for position in outcome.positions)` is a
truthiness check, so substituting `workspace_id` for `source_user_id` survived
every scope. "Every side attributed" was pinned as "attributed to something"
rather than "attributed to the right person". It now asserts the exact user set.

Also closed: `MUTATING_ROLES` widened to include `support` survived every scope
— it fails closed at layer three, but the audited result degrades from `denied`
to `failed`, so the log stops distinguishing "this role may not" from "the
database refused"; the `UUID()` half of `_decode_cursor`; and layer one's own
test, which used `has_table_privilege` and so was blind to **column** grants —
the dominant idiom in this schema, 45 in `restore_privileges.sql` alone. Both
reviewers confirmed the boundary itself held with such a grant live, and that
`test_backup_restore` caught it behaviourally; only the test named for the
property was blind.

### Eleventh review round: a reviewer disproved a claim I had settled

Both reviewers reproduced candidate
`40c005409b953ad0f34e1eac57e8c19bb36c7a4da24a1253cc25f111885a81ae` unchanged at
both ends and both returned CHANGES REQUIRED, converging on the same blocking
finding.

**My new pool test named a guard it did not touch.** It claimed to pin the
tenant-context workspace requirement via
`pytest.raises(ValueError): AuthorityContext.tenant(None, …)`. But `tenant()`
does `cls(str(workspace_id), …)`, so `None` becomes the string `"None"` and dies
in the UUID check — the guard the line names is never reached, and mutating it to
`pass` survives every scope. One reviewer proved the branch is unreachable from
anywhere: `grep -rn "AuthorityContext(" src/ tests/` returns exactly one direct
construction, which passes a real workspace id.

This is the fourth instance of the shape round ten named, and it sat inside the
repair written to answer round ten, under the rule adopted in response to it.
So the rule needed a second half. "Run the mutation before writing the sentence"
was necessary and not sufficient: I *did* run four mutations and two died. What
I did not check is that each died **for its own reason**. A bare
`pytest.raises(ValueError)` cannot tell two guards apart, so a matrix of
indistinguishable assertions looks complete while measuring one guard twice.
Every assertion in that test now carries `match=`.

**And a reviewer disproved something this record had settled.** I wrote that
`_reset`'s key scrub and the transaction scope of `set_config` are redundant
defences, each masking the other's absence, and therefore *cannot* be pinned by
behaviour — and pinned them by reading the source. That was wrong. A reviewer
isolated one layer at a time, which is the method this phase already uses on the
customer boundary, and built both:

- Set all five keys at **session** scope on a borrowed pooled connection, hand
  it back, borrow it again. Transaction scope cannot mask this, because nothing
  is in a transaction.
- Subclass the pool overriding `_reset` to drop only the scrub, then drive an
  ordinary tenant context through it.

Each kills exactly its own mutation and is blind to the other. It also pointed
out my source assertions were strictly weaker than its tests —
`assert "for key in _CONTEXT_KEYS:" in reset` still passes if `_CONTEXT_KEYS` is
narrowed to one key. Both source assertions are gone and its tests are in. The
claim is corrected here rather than quietly dropped, because "this cannot be
tested" is exactly the kind of conclusion that should have to survive a
reviewer.

**Three more, each the same shape as a defect a previous round closed.**
`LockNotAvailable` sat in `_TRANSIENT` pinned by nothing, while its two
neighbours were pinned — so the retry *looked* covered, which is how the
foreign-key member hid two rounds earlier. The score branch of `_conflicts`
builds its own `ConflictPosition`, and round ten's attribution repair only
reached the shared loop, so "every side attributed" stayed half unmeasured.
Non-finite filter values passed validation and reached SQL, where `inf` returned
nothing, `-inf` returned everything and `nan` returned nothing — silently, with
no error of any kind.

**A duplicate entry in the carried list, for the second time** — and this one
had been added inside the very parenthetical recording that a reviewer caught
the first.

**What neither reviewer could break.** Between them: 161 self-chosen mutations;
23 filter sets × 16 limits paged to exhaustion and diffed field-by-field against
an unpaged baseline with **0 mismatches**; `list` versus `get_opportunity`
compared on every field including all conflict positions across 30 entries;
**6,000 randomized staff steps** across four seeds and 18 action shapes with
zero violations of exactly-one-row or of any attribution field; concurrency
**0/105** on the retried path with 24/35 un-retried as a positive control that
the harness induces what the retry absorbs; tenant erasure across 54 attempts;
and the customer boundary with layer one removed entirely — `GRANT ALL` plus
column-level `GRANT SELECT` on every column to all seven customer roles plus
`GRANT EXECUTE ON ALL FUNCTIONS`, with a forged live active staff owner for whom
`internal_authorized()` returned true — still zero rows, and `INSERT` refused by
the RLS `WITH CHECK`. One reviewer additionally verified the boundary **after**
`restore_privileges.sql`, not merely after migration, which is where the
layer-one pin measures.

### Twelfth review round: a wrong answer, not a missing pin

Both reviewers reproduced the tree unchanged across their reviews and both
returned CHANGES REQUIRED. Between them: 137 self-chosen mutations, 1,750
randomized staff steps, 249 read checks across 18 page limits, facets re-checked
against a **raw-SQL oracle** rather than the repository's own view, 126
concurrency trials, and tenant erasure in seven orders.

**One workspace disagreeing with itself was reported as workspaces
disagreeing.** `_conflicts` partitioned by source row, never by workspace, and
`deals` is unique on `(workspace_id, source, source_record_id)` — so one tenant
saving one building from two providers, the designed-for path, produced a full
conflict report naming the same workspace and the same user on both sides, with
`distinct workspaces holding positions: 1`, and blanked the entry's property
type. In the two-workspace case both tenants' current view agreed and the index
still reported three cross-tenant conflicts.

This is the first wrong *answer* in several rounds rather than a missing pin,
and it is on the behaviour the contract gives its own section to. A conflict now
requires positions from more than one workspace.

The fix forces an admission rather than allowing a quiet repair: **a tenant
contradicting itself is now not surfaced at all.** That is a real data-quality
signal this phase does not report, and it is stated in the contract as a limit.
So is the subtlety underneath it — the derived `property_type` and the conflict
report answer slightly different questions, and the label stays the more
conservative of the two.

**`object_id` was pinned for one audit-row shape out of eleven.** Exactly round
nine's finding, one field over: `object_type` had been a constant for nine
rounds because nothing read it, and the repair's own test is named *"the kind of
object its **id** refers to"* while reading only the type. Six independent
mutations replacing `object_id` with a constant survived focused,
`tests/postgres` and the full repository. Now asserted across every action shape
— entry-scoped actions naming their entry, ingest naming its workspace, a
refused inspect naming the id that was probed for.

**Multi-facet filters answered by one source row were unpinned, and material.**
Splitting the combined `EXISTS` into one per predicate survives every focused
test and *changes answers*: `workspace A AND stage=loi` goes from 0 entries to 1
when no single row in A is at that stage — the cross-tenant confusion the filter
clause exists to prevent.

**Three record errors, and a process one.** The gate-numbers paragraph still
said "post-round-eight-repair tree" while listing round-eleven numbers four
lines below, self-contradicted inside its own paragraph and stale across four
rounds. A carried entry was wrong in three of four measured directions. And the
published freeze hash was stale by one edit — I computed it, wrote the
round-eleven record, then built the brief around the pre-edit hash. Both
reviewers caught it, both proved the tree had not moved for the duration, and
both attached their measurements to what they had actually measured. The order
is now fixed: **record first, freeze second, dispatch third.**

**The contract gained a qualification it could not keep without.** "An action
refused for lack of role writes its row" is false for an actor who *lies* about
their role or holds no staff row: the audit table's own RLS requires a live
staff role, so the refusal row is itself refused. The honest attempt is logged
and the dishonest one is not. Nothing leaks — every such path returns zero rows
— but the clause promised more than the design can do, and closing it needs an
audit path independent of the actor's own authority, which belongs to the
privacy and retention phase.

**What neither could break.** The customer boundary with layer one removed
entirely and a live active staff owner forged in, across seven statement shapes
× three relations × three contexts, measured both after migration **and after
`restore_privileges.sql`**: zero rows every time, `INSERT` refused by the RLS
`WITH CHECK`, `UPDATE`/`DELETE` at `rowcount=0` with the data intact. Layer
three removed with layer one intact: refused. All four pool guards confirmed to
die each for its own reason, and the `Unscrubbed` subclass confirmed a faithful
isolation of the shipped `_reset` minus only its scrub loop.

### Thirteenth review round: the same fix wrong twice

Both reviewers reproduced the candidate unchanged and both returned CHANGES
REQUIRED on the same defect, from different directions. Between them: 33 and 15
self-chosen mutations, 2,100 randomized staff steps across 22 action shapes,
**7,772** paged read comparisons against an unpaged baseline and a raw-SQL
oracle, and 140 read/write boundary probes.

**Round twelve's conflict repair was wrong in both of its branches, and I wrote
two contract sentences asserting otherwise.**

One reviewer showed the *categorical* predicate asks the wrong question:
"more than one distinct value AND more than one distinct workspace" is satisfied
by two tenants who each saved the building from the same two providers, hold
identical `{office, retail}` views, and agree exactly — reported as three
cross-tenant conflicts. It reproduced the round-twelve record's own sentence
verbatim on the repaired tree, and found it arising spontaneously in **4 of 9**
randomized multi-provider seeds.

The other showed the *score* branch never got even that: only a presence gate,
with the magnitude still `max − min` over every row, so one tenant's 10-vs-45
split supplied the whole spread while a second workspace merely had to exist.

Then my first correction was **also** wrong, and my own new test caught it:
comparing scores pairwise across workspaces reported two tenants who both hold
`{41, 88}` as disagreeing by 47, by pairing one side's 41 with the other's 88.
The rule that works is the numeric analogue of the categorical one — compare
each workspace's score **range**, and treat them as agreeing when both ends
coincide within the tolerance.

Three attempts to state "do these workspaces disagree" in code; the first two
were plausible enough to survive my own review. That is the argument for the
gate rather than against it.

**Two more, both real.** `get_opportunity`'s conflicts were read by no test at
any scope — returning `()` survived everything, and that is the single-entry
read staff use to inspect one property. And the surviving half of the
round-twelve predicate was unpinned: replacing the value-distinctness clause
with `True` survived focused, `tests/postgres` and the full repository while
turning agreement into nonsense (`stage: ['lead', 'lead']`).

**The mutation matrix now carries a deliberate no-op control** — a change that
alters nothing and must survive. It did. Without it, a column of red results
only shows the tests are sensitive to something; with it, they are shown to
discriminate.

**What neither reviewer could break.** The customer boundary with layer one
removed — `GRANT ALL` plus column-level `GRANT SELECT` on every column plus
`GRANT EXECUTE ON ALL FUNCTIONS` to all seven customer roles — and then with
layers one **and three** removed together, `internal_authorized()` and
`internal_can_mutate()` replaced by `SELECT true` and confirmed returning true
to the customer role: **zero leaks**, every shape, including `COPY`, LATERAL
joins onto readable tenant tables, and `UNION ALL` with `workspaces`. Measured
again after `restore_privileges.sql`. 2,100 audit rows with zero attribution
violations. Concurrency 0/32 on the retried path against 32/32 and 12/32
un-retried as working positive controls. Tenant erasure in six orders.

One reviewer also disclosed the limit of its own harness — its opposite-rotation
re-bind test produced no failures even with `ORDER BY id` deleted, so it proves
nothing about that cycle either way, and said so rather than counting it as
evidence.

### Fourteenth review round: the fixtures could not see the defect

Both reviewers reproduced the candidate unchanged and both returned CHANGES
REQUIRED. Neither found a wrong answer. Both found that the tests **could not
have** found one.

**Eight mutations inside `_conflicts` survived every scope**, each with a
counterexample showing it is not equivalent. Two of them reverted the exact
defect round thirteen rejected — partitioning by `source_user_id` instead of
`workspace_id` — and the reason they survived is structural, not an oversight:
`_seed` inserts exactly **one** membership per workspace, and all 83 deal call
sites pair `workspace_a↔user_a` and `workspace_b↔user_b`. Workspace and user are
perfectly correlated in every test in this phase, so **nothing in the suite can
distinguish "partition by workspace" from "partition by user"**. No number of
additional assertions over that fixture would have found it.

The other six were the geometry of the range rule: `min` instead of `max` of the
two end-differences, comparing only high ends, comparing only low ends, building
the range's high end with `min()`, the tolerance boundary at `>=` instead of
`>`, and dropping the `is not None` filter so a workspace that declared nothing
became a position with the literal value `'None'`. Each hides a real 40-to-50
point cross-workspace disagreement, or fabricates one from absence.

All eight are now pinned by exercising `_conflicts` directly — a workspace with
**two distinct members**, and explicit range geometries — and each mutation dies
while a deliberate no-op survives.

**And the multi-facet pin covered five of seven facets.** Round thirteen's
reviewer demonstrated that defect with three facets; I pinned those three. The
rule is "every facet must be satisfied by the same source row", and there are
seven — the fixture set no `property_type` and made no `deal_outcomes` row, so
splitting either out of the combined `EXISTS` survived all 5,115 tests while
changing answers: `property_type="office" AND stage="loi"` returning an entry no
workspace described that way.

**Two rounds running, the finding is the same shape: a test written to the
example rather than to the invariant.** That is a different failure from the
vacuous assertions earlier in this phase — these measure the right thing over
too small a domain. The rule it earns: when a reviewer demonstrates a defect
with N cases, pin the *rule*, then check the domain the rule ranges over.

**A stale docstring, corrected.** `_derived_property_type` claimed `None` meant
the workspaces disagree and the conflict report names both sides. A reviewer
measured two shapes where the label is blank and the conflict tuple is empty —
two workspaces each holding `{office, retail}`, and one workspace holding both.
The contract stated this correctly; the docstring did not.

**What neither could break.** The customer boundary with layer one removed and
`internal_authorized()` returning **true** to `medawarcre_app`: zero rows from
all three relations, `rowcount=0` on forged writes, measured after migration and
after `restore_privileges.sql`. A `CREATE TEMP VIEW` over the index succeeds and
reading it is still refused. 34 and 39 self-chosen mutations with green controls
and no-op controls at both ends. 19 page sizes against an unpaged baseline and
an independent raw-SQL oracle. 420 randomized staff steps with exactly one
correct audit row each. Concurrency 30/30 un-retried against 0/30 retried.
Erasure in five orders. And the workspace-deletion paragraph measured across 14
action shapes — correct.

### Fifteenth review round: a lesson that did not transfer

Both reviewers reproduced the candidate unchanged and both returned CHANGES
REQUIRED, converging on the same blocking finding. Neither produced a wrong
answer from the shipped code.

**Round fourteen's fixture-correlation lesson was applied in one place and not
the other.** Round fourteen found `workspace_id` and `source_user_id` perfectly
correlated across all 83 deal call sites. I broke that correlation in the
`_conflicts` unit tests and nowhere else — so the *filter* path had still never
seen a workspace with two members, my comment claiming the pin "exercises all
seven facets" was false (it reached five), and splitting `source_user_id` or
`max_score` out of the shared `EXISTS` survived 85 focused and **359**
PostgreSQL tests while changing real answers, 0 to 1. The same surgery on
`min_score` and `workspace_id` died, so the technique was sound and only the
domain was short.

I had written the rule down after round fourteen — *pin the rule, then check the
domain it ranges over* — and applied it to `_conflicts` in the same session I
edited the filter pin without applying it there.

**Four more invariants stated somewhere and defended nowhere**, each with a
reproduction:

- **Provenance transposed still validates.** Swapping the `source` and
  `source_record_id` bind parameters survives every scope, because
  `(workspace_id, source, source_record_id)` is the unique key of *both* tables:
  the transposition is self-consistent, so deduplication and re-ingest keep
  working while **zero** observations join back to the tenant rows they cite.
  The only assertion touching them was `assert source.source or
  source.source_record_id` — a truthiness OR a transposition satisfies on both
  halves. Retention item 9.
- **The blank-label state** the contract and the round-fourteen docstring
  describe was read by no test, although two existing tests already produce it.
  Returning `sorted(declared)[0]` — picking a winner — survived everything.
- **Collapsing conflict positions to one per workspace** survived, contradicting
  the contract sentence written the round before saying positions are
  per-observation.
- **The keyset cursor's tie-breaking `id`** could be dropped and survive, though
  the contract requires a *total* order and two entries created in one statement
  share `created_at`.

Also: `_derived_property_type`'s absence filter was unpinned, so one workspace
declaring a type and another declaring nothing — the commonest real shape, since
`Listing.property_type` is `str | None` — could silently become a blank label.

**The risk I flagged when dispatching did not materialise, and the check was
worth asking for.** Round fourteen's fix escaped a fixture blind spot by
building `OpportunitySource` objects by hand, which risks pinning a shape the
database never produces. A reviewer verified `_source` against `_load`
field-for-field and type-for-type — `score` is `float` not `Decimal`, ids are
`str`, jsonb columns are `dict`, timestamps tz-aware — with zero mismatches, and
reproduced all ten scenarios end to end through real ingest.

**What neither could break.** `_conflicts` against a contract-derived oracle over
**8,000** randomized shapes plus 24 end-to-end: zero mismatches, zero conflicts
naming fewer than two workspaces. Behaviour against an independent oracle built
from raw table dumps, with three workspaces and six members: **933** filter
checks and 76 paging sequences, zero mismatches. 192 concurrency runs — zero
failures retried, 7 of 32 un-retried, so the retry is load-bearing rather than
decorative. And the customer boundary with layers one **and** three removed
together, which is the configuration that shows what is actually doing the work:
every policy is `TO medawarcre_admin`, so RLS default-denies a role no policy
names. One reviewer also chased the customer's own `DELETE` cascading into
`internal_opportunity_sources` to fire the archival trigger as a cross-tenant
existence oracle — unreachable, because `medawarcre_app` holds no grant of any
kind on `medawarcre.deals`.

### What the reviews found that is not fixed here

Recorded rather than quietly carried, because a reviewer measured each one.

One reviewer mutation-tested 42 guards in `opportunity_index.py` and **26
survived**. That figure is from round two and predates the six pins added since;
it is carried unrecomputed and should be read as an upper bound on what is still
unpinned, not a current measurement.

The suite pins the customer boundary, deduplication, provenance, outcome
conflicts, the audit row's existence, the attribution guard, the re-bind orphan,
merged-entry archival, merge-against-a-missing-id, the keyset index matching the
listing order, and — as of the fourth round, measured rather than asserted —
every one of the seven declared filter facets individually.

Round fifteen added these, each measured by a reviewer and none of them closed:

- **`internal_opportunity_sources_user_membership_fkey`** can be dropped and the
  focused suite stays green. The guards file pins every CHECK, both merge-trigger
  branches and the reviews RLS, but of `0009`'s foreign keys only the
  saved-search one is pinned.
- **Three of the five declared indexes** are unread by
  `test_the_declared_facet_indexes_can_serve_the_queries_that_use_them`, which
  reads two.
- **The `medawarcre_backup` grant on `internal_opportunity_reviews`.**
- **Per-entry source ordering**, which no contract clause specifies.

Round eight added these, each measured by a reviewer choosing its own mutations:

- **The guard file pins guard *deletion*, not guard *weakening*.** Every guard a
  reviewer deleted was killed, and the bounds are tight — 200→201 and 512→513
  both die. But *widening a vocabulary* survived in all six cases (`status`,
  `origin`, `stage`, `outcome`, `reviewer_role`, `verdict`): each test names one
  rejected literal, so what is pinned is "the database refuses **this** value",
  not "the vocabulary is closed". Also surviving: both directions of the
  origin-binding **exclusivity** rule — the SQL's own "exactly one tenant record
  backs an observation", contract retention item 3 — the reviews `no_delete`
  trigger, which is half of "append-only … enforced by trigger", and the merge
  trigger's target-exists branch.
- **`score::text NOT IN ('NaN','Infinity',…)` is dead code.** A numeric `NaN`
  already fails `BETWEEN 0 AND 100`.
- **Contract-relevant rules with no pin**, each measured surviving at the
  333-test scope: the `went_bad`/`closed` precedence (and nothing forbids a
  tenant setting both); ZIP as part of the normalized identity, whose removal
  collapses genuinely different properties into one cross-tenant entry; two of
  the three folds in the dedup key (accent and punctuation — suffix folding *is*
  pinned); retention item 10 (`merged_into_opportunity_id` reported), item 1
  (`workspace_public_id` rather than the internal id) and item 12 (the review
  note); the `IngestSummary.rejections`/`opportunities` reporting surface; and
  `StaffRequest`'s actor-UUID validation.
- **Deduplication splits on apostrophes and hyphens.** `100 O'Brien Ave` and
  `100 OBrien Avenue` become two entries — the same family as the carried
  ZIP-omission split, and not named in the contract's disclaimer.
- **A whitespace-padded staff reason breaks every call, untraced.**
  `StaffRequest` validates `reason.strip()` and stores the raw string;
  `AuthorityContext.internal` strips it into `app.audit_reason`; the RLS forgery
  guards require exact equality. A console textarea produces it.
- **An actor with no staff role leaves no trace at all.** `_audit_out_of_band`'s
  blanket `except Exception: return` swallows the RLS refusal of its own insert
  — and the audit table's own policy requires a live staff role, so such an
  actor structurally cannot write their own denial. Recorded as a real limit of
  the design rather than a bug to paper over, and it is the counter-example to
  this record's line that `denied` covers attempted escalation. Relatedly, an
  unauthorised actor claiming `owner` is told "no such workspace" — an existence
  claim standing in for a permission one.
- **The entry clock repair covers only the `ON CONFLICT` branch.** On a first
  observation both INSERTs fall through to `DEFAULT statement_timestamp()` and
  the source's statement begins later — 6 of 6 entries trail, worst lag 2,138 ms
  under contention. On a merged head the `GREATEST` advance lands on the
  superseded row, so the visible entry's `last_observed_at` freezes at the
  moment before the merge. And the round-five pin ingests **twice** before
  asserting, so the `ON CONFLICT` branch repairs the state before the assertion
  runs.
- **The contract was not updated when the retry widened.** It authorises
  retrying "a transient deadlock"; the code retries four classes including
  `ForeignKeyViolation`.

Round seven added these, each measured by a reviewer:

- **Cross-tenant row counts reach the customer role once `ANALYZE` has run.**
  `pg_stat_all_tables.n_live_tup` and `pg_class.reltuples` are world-readable and
  are not filtered by row-level security; `pg_stats` is, and stays empty, so no
  *values* leak. Autovacuum runs `ANALYZE` in any real deployment. A
  PostgreSQL-wide property, not one this phase introduced, and in scope for the
  staging security audit rather than for a workaround here.
- **The entry-side refresh of `title`, `property_identity` and `market` cannot
  change any value.** `canonical_key` is a hash over exactly the fields those
  three derive from, so `EXCLUDED.*` always equals the stored value and a
  corrected identity produces a *different row*, not an updated one. The round-five
  note calling that refresh a repair for "a corrected identity never reached the
  entry" describes something that cannot happen. Harmless, and left in place
  because it is the correct expression of the intent, but the record should not
  claim it fixed anything.
- **`0009`'s `REVOKE ALL … FROM medawarcre_app, …` on the two pre-existing index
  relations is a no-op** — `0001` never granted those roles anything there, and
  deleting the REVOKE does not even move the fingerprint. The comment
  ("Restated rather than assumed") is honest about being belt-and-braces; the
  grant boundary that the customer-role test proves comes from `0001`.
- **57 of one reviewer's 113 mutations, and 3 of the other's 41, had no
  behavioural pin.** Round seven closed the ones with contract or boundary
  consequences — every database guard, the retention items, the listing order,
  the plan order, the clock, the runtime gate. The remainder are ordinary
  robustness paths, and the honest position is that this list is now a floor
  rather than a ceiling: a reviewer choosing different mutations would find more.

Round five added to this list rather than removing from it:

- **`merge_opportunities` re-pointing an existing link.** A→B then A→C is still
  silently accepted. Round five closed chains and cycles; this is neither.
- **Ingest racing a tenant deletion.** Either side can be the victim, and a
  reviewer showed a privacy erasure rolling back in full because staff ingested
  at that moment. Ingest now retries; the deletion side is not this phase's code
  and its retry obligation belongs to the privacy and retention phase.
- **The archival trigger never archives a `suppressed` entry** that loses every
  source. Deliberate — suppression is a staff decision and should outlive the
  loss of sources — but it means a suppressed entry can hold a normalized
  address with nothing contributing to it, and nothing pins that choice.
- **`include_archived=True` un-hides `merged` and `suppressed` too.** Intended
  for a staff override, but the parameter name does not say so.

Still unpinned, and carried deliberately:

- The audit insert sharing a transaction with the read. The test counts rows, so
  moving the insert to its own connection survives it.
- The `reason_code` vocabulary.
- The **ZIP** branch of the convergence check (`city_zip_pair_is_authoritative`).
  A reviewer measured the two branches separately and found this entry wrong in
  both directions: the no-ZIP branch (`city_claim_is_unambiguous`) **is** pinned,
  and only the ZIP branch is not.
- ~~The stage half of conflict detection, and the score tolerance.~~ **Struck
  at round thirteen** — a reviewer measured both tolerance directions now dying
  (`> 0.0` and `> 1000.0`), and round thirteen pinned the stage half. Carried
  here through three rounds of being progressively less true; the lesson is
  that a carried entry needs re-measuring when the code near it changes, not
  only when someone complains about it. Two reviewers measured this entry and it was wrong
  in three of four directions: score-conflict detection is pinned, and the
  tolerance is pinned against widening (100000 and 200 both die); only removing
  stage detection and narrowing the tolerance to 0 survive. Round twelve pinned
  the stage half, so what remains is the narrowing direction alone.
- ~~The page-size bound and cursor validation.~~ **Both are pinned as of round
  ten**, by the refused-argument audit test — two reviewers independently
  confirmed those mutations now die. What remained was narrower and is closed
  separately: the `UUID()` half of `_decode_cursor`, whose removal let
  `…|not-a-uuid` reach SQL as the raw database error the contract forbids.
- `MAX_PAGE`'s specific value. The contract requires the page be *bounded*, and
  it is; nothing pins that the bound is 200 rather than 10,000.
Round four's reviewers named these; each was measured, and each is listed rather
than described as closed. Two entries have now been de-duplicated here after a
reviewer caught them: `merge_opportunities` re-pointing an existing link, in
round seven, and `include_archived=True` un-hiding `merged` and `suppressed`, in
round eleven — the second inside the very parenthetical that recorded the first.
Both are stated once, above.

Also open: `access_class` is the literal `'private'` for every observation, so
retention item 11 is satisfied by a constant rather than a classification —
fail-safe in direction, but not a classification. The same property fails to
merge when one workspace omits the ZIP. `NORTH→N` folding applies to every token
rather than a directional prefix, so `100 North St` and `100 N St` collide.
Reviews declare `ON DELETE CASCADE` under a
reject trigger that makes the cascade unreachable. And `origin='search_result'`
is schema-reachable but never written, because ingestion reads only `deals` —
which also means `suppressed` is a status no code in `src/` ever sets. Three
round-five repairs exist to preserve it and its pin has to write it with raw
`medawarcre_migration` SQL; the Operations Console phase is what will set it.
The "`get_opportunity` … probe for existence untraced" entry that stood here was
**stale**: round five fixed and pinned it a hundred lines above in this same
document, and a round-six reviewer caught the contradiction.

**Tenant erasure is not achievable end to end, and this phase should stop
implying otherwise.** A reviewer walked it: deleting a workspace raises
`ForeignKeyViolation` on `staff_audit_log_workspace_id_fkey`; deleting those
audit rows first raises `ObjectNotInPrerequisiteState`, because they are
append-only. So one ingest — or one ordinary customer tool call, via
`access_decision_audit` — makes a workspace permanently undeletable. Separately,
an index entry that has been reviewed even once cannot be deleted by any role
including `medawarcre_migration`, because the cascade to
`internal_opportunity_reviews` hits the reject trigger; it can only be updated
in place. Round four removed the tenant free text from that residue, so what
survives is a normalized address and staff's own review history. The contract
still lists "Deleting a workspace removes its source rows" as required
behaviour, which is unreachable after the first ingest — that sentence is
corrected in the contract, and the resolution belongs to the privacy and
retention phase, which must decide whether audit rows are anonymized, detached,
or retained under a lawful-basis exception.

None of these is a customer-boundary defect — every reviewer attacked that
hardest and it has held in all seven rounds — but the honest summary is that this
phase's *behaviour* is better verified than its *guards*. The filter gap is
closed with a measurement rather than a claim; the rest are named above so the
next phase inherits a list, not a surprise.

## Stripe test integration evidence

- Repository gate: `4496 passed, 1 warning in 127.21s (0:02:07)`
- Platform gate: `402 passed, 1 warning in 21.61s`
- Operations Console: `8 passed`; production build completed; `npm audit`
  reported `found 0 vulnerabilities`
- Stripe access is disabled without an explicit `sk_test_` or `rk_test_` key.
  Live keys and live-mode webhook objects are rejected.
- Reconciliation reads only the fixed Stripe subscriptions endpoint, consumes
  every bounded page, validates the complete item-level price and period state,
  and commits projection repair plus the operator audit in one transaction.
- `customer.updated` and active-entitlement summary events are durable
  reconciliation signals only. They cannot grant access by themselves.
- Fixtures contain invented test identifiers and follow Stripe's documented
  list and subscription schemas. A real test-account capture remains a private
  staging gate.
- Official contract references: `https://docs.stripe.com/webhooks`,
  `https://docs.stripe.com/api/events/object`,
  `https://docs.stripe.com/api/subscriptions/list`, and
  `https://docs.stripe.com/api/subscriptions/object`.

## Skool lifecycle evidence

- Repository gate: `4507 passed, 1 warning in 183.33s (0:03:03)`
- Platform gate: `413 passed, 1 warning in 42.62s`
- Operations Console: `10 passed`; production build completed; `npm audit`
  reported `found 0 vulnerabilities`
- Joining is deliberately operator-bounded. The system creates an audited task
  for Skool Admin Invite or Zapier Invite, then waits for the member to click
  JOIN NOW and for an operator to bind the exact member id.
- Completing a join task creates no grant. A signed event or a complete,
  current, confirmed member review remains the next authority gate.
- Reconciliation stores only a hash receipt and operational metadata. Stale,
  partial, provisional, or unverified reviews are visibly uncertain and cannot
  strengthen access.
- Missing members and restrictive statuses revoke. An unmapped tier is a
  conflict and revokes existing Skool authority rather than guessing a plan.
- Manual revocation removes Skool authority and invalidates the affected OAuth
  session and pending authorization codes in the same audited transaction.
- The Operations Console exposes join tasks, evidence age, certainty,
  discrepancies, conflicts, exact mappings, and reason-gated manual revocation.
- Official operating references:
  `https://help.skool.com/article/14-how-do-i-invite-members-to-my-community`,
  `https://help.skool.com/article/56-zapier-integration`, and
  `https://help.skool.com/article/141-how-to-remove-a-member`.

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

### OAuth certification audit round one: changes required

The first independent audit rejected the initial Phase 1 implementation even
though its full suite passed 1,800 tests. The following findings remain part of
the permanent evidence trail until a repaired implementation passes a fresh
second audit:

- High: exact city and ZIP grants accepted same-state contradictory declared
  address fields.
- High: unchecked client-visible protocol channels could carry denied property
  data through result metadata, text-block metadata or extras, and duplicate
  JSON keys.
- Medium: structured and text representations were validated separately but
  were not required to be semantically identical.
- Medium: malformed content containers and deeply invalid JSON could bypass the
  ordinary generic denial audit through an internal exception.

The approved repair boundary remains narrow. It may derive claims only from the
declared `address`, `city`, `state`, and `zip_code` fields. It must not scan
arbitrary nested mappings or provider `raw` payloads. Hosted serialization of
provider `raw` data is tracked as a separate product-security decision.

### Hosted persistence cannot use a generic compatibility shim

Read-only call-site archaeology found four durable authority classes in the
current hosted runtime: central platform SQLite, per-workspace MCP SQLite,
mutable `registry.json` plus `audit.jsonl`, and local truth-document blobs. The
HTTP server currently constructs these concrete stores and registers the full
tool catalog. A PostgreSQL error or miss must never fall back to any of them.

The SQLite stores embed domain-specific DDL, SQL, identifiers, file paths, and
transaction behavior. Emulating `sqlite3.Connection`, translating arbitrary
SQLite SQL, or storing opaque database state in JSONB would erase launch
invariants and is rejected. Cloud integration instead requires an explicit
request-scoped persistence bundle with domain repositories. Local stdio keeps
its existing SQLite behavior. Each hosted persistent capability remains
fail-closed until its repository parity tests pass.

The minimum cloud order is:

1. Reject HTTP startup before opening a socket or creating local state unless a
   healthy PostgreSQL bundle is available.
2. Add narrow OAuth and provider bootstrap roles or fixed-search-path security
   functions because workspace identity is not known before token or provider
   binding resolution.
3. Resolve token, client, membership, account, grant, plan, territory, and
   staff authority from one database snapshot.
4. Atomically bind access admission to workspace, actor, OAuth session, tool,
   canonical argument hash, single-use approval, quota, and durable audit.
5. Port platform control, provider, search, deal, privacy, job, document, and
   remaining stateful tool domains behind explicit contracts. No dual write,
   shadow write, reverse sync, or fallback is permitted.

The current `TenantContext` has no authoritative actor or OAuth-session fields,
and file-backed approvals bind only workspace, tool, and argument hash. Those
are launch blockers because one workspace member could otherwise consume
another member's approval and creator/updater attribution would be unprovable.
The PostgreSQL foundation may supply the schema primitives, but Phase 3 must
perform the runtime rewiring and prove the actual restored service path.

### OAuth certification audit round two: changes required

The fresh second auditor rejected the repaired Phase 1 snapshot with two
additional high-severity result-disclosure paths:

- A punctuation-free earlier address claim such as `Miami FL 33139` or
  `Austin TX 73301` could be hidden before a safe `Dallas, TX 75201` tail. The
  parser collected only the comma-delimited tail, so Local Scout and JV Partner
  city or ZIP grants could release the contradictory record and log `allowed`.
- Result validation accepted a `ToolResult` subclass or an exact instance with
  a shadowing `to_mcp_result` attribute. FastMCP later invoked that unvalidated
  serializer and released a denied property even though middleware had checked
  safe attributes and recorded `allowed`.

Required repair: collect every recognizable state, city-state, ZIP, and ZIP+4
claim from capability-declared fields regardless of comma punctuation, and make
the eventual serialized result exactly the representation that was validated.
Nested undeclared data and provider `raw` remain outside the territory scanner.

### OAuth certification audit round three: changes required

A new read-only auditor rejected the second repaired snapshot after preserving
an identical tracked patch hash at audit start and finish. Its end-to-end matrix
released all 36 contradictory records across Local Scout and JV Partner,
`properties` and `listings`, semicolon, slash, and whitespace separators, and
exact city, ZIP, and ZIP+4 grant cases. Earlier `Austin TX 73301` or `Miami FL
33139` claims disappeared when a declared `Dallas` / `TX` / `75201` tail was
present, so middleware returned the record and recorded an ordinary `allowed`
event.

The same audit found that an exact `TextContent` object could be mutated from
the `text` discriminator to `image` after construction. Result extraction
checked the Python class and text body but not the discriminator, so the invalid
client-visible block passed validation and was returned with an `allowed` audit
event.

Two false-denial controls also became mandatory: `123 Oak Ct` must not treat the
street suffix as Connecticut, and `100 Main St Unit 33101` must not treat an
explicitly labeled unit number as a Florida ZIP. The repair must begin with the
full rejected matrix and these controls as red tests, then recognize and
reconcile every exact address claim without broad scanning or ordinary-address
false positives. A fourth fresh audit is required after the complete gate set.

### OAuth certification audit round four: changes required

After the third repair passed 1,959 tests, the controller and a new independent
auditor found the same remaining high-severity boundary. A state-only earlier
claim without a ZIP was still recognized only before a comma or the end of the
string. Semicolon, slash, and whitespace separators could therefore hide
`Miami FL` or `Austin TX` before a declared `Dallas TX 75201` tail.

The auditor reproduced the release through real FastMCP middleware in all 48
combinations of Local Scout and JV Partner, `properties` and `listings`, exact
Dallas city and `75201` ZIP grants, and the six contradictory addresses. Every
call returned the record and wrote an ordinary `allowed` event. This invalidates
the otherwise green suite and blocks a commit.

The next repair must preserve that full matrix as red evidence, reconcile
state-only address claims across the same separators, and add collision controls
so broader recognition does not reinterpret ordinary `in`, `or`, `Ct`, `NE`,
unit numbers, or street-name tokens as locations. Every full gate and another
brand-new audit remain mandatory.

### OAuth certification audit round five: changes required

A fifth independent protocol review rejected the next repaired snapshot even
though its existing focused selection passed 321 tests. The review exercised
the real FastMCP client, production access middleware, exact tool result, and
client-visible `CallToolResult` path.

The review reproduced all 24 expected denials across Local Scout and JV Partner
profiles and the declared `properties` and `listings` collections as releases.
It separately reproduced all 48 city, state, and ZIP expected denials as
releases across both profiles and both collection forms. Case variants, full
state names and codes, country suffixes, bare city-state claims, and bare ZIP
claims followed by a country suffix were not reconciled safely.

Required location fields that were omitted or null also reached the client. A
Crexi `map_asset`-shaped property with empty `address` and `city`, declared
Texas state, and Miami data only in undeclared text or raw fields was released.
At the same time, a valid country-text control without a state was denied. This
proves the current result contract is neither sufficiently typed nor safely
normalized.

The next repair must first preserve the 24-case and 48-case protocol matrices,
the Crexi-shaped case, and every omitted/null case as permanent red tests. It
must then validate or intersect the requested search and independently validate
every returned property. Restricted profiles must fail closed on unknown,
ambiguous, incomplete, undeclared, or conflicting location data without using
arbitrary provider raw payloads as authority. Two new independent approvals are
required after all focused and repository-wide gates pass.

### OAuth certification audit round six: changes required

After preserving the fifth-review matrices and passing 2,342 repository tests,
a fresh neutral reviewer inspected a frozen OAuth snapshot through the real
FastMCP protocol path. Its independently computed composite fingerprint was
identical at review start and finish:
`0e27d093af6457f9717ca73a84209c5017b3d357d500e3776b2d2d0a2c4a94f9`.
The reviewer made no worktree edits.

The review rejected the snapshot with four reproducible findings:

- High: a Texas Local Scout could execute `owner_lookup` for
  `90 Ocean Drive, Miami, FL` when an in-scope `Harris County, TX` argument was
  supplied beside it. The numbered address was treated as unresolvable and
  ignored instead of intersected with the grant.
- High: a Texas result containing
  `33101; 100 Main St Dallas TX 75201` was released because the earlier Florida
  ZIP claim was not reconciled with the safe trailing claim.
- High: an exact `75202` ZIP grant released a record whose declared city was
  `Dallas TX 75201` and whose separate `zip_code` was `75202`; the ZIP embedded
  in the city field was discarded.
- Medium: a legitimate `100 Main Street, Washington, DC 20001` result was
  denied because the city name `Washington` was misread as the state of
  Washington.

Controller inspection added permanent contract cases for country-suffixed city
values that omit state, state-only and ZIP-only city values, present-but-empty
ZIP values, non-ASCII digit lookalikes, and labeled unit numbers followed by a
country suffix. The next repair begins with all reviewer and controller cases
as real-protocol red tests. The rejected review does not count toward the two
fresh approvals required on the final repaired hash.

### OAuth certification clean-context audit: changes required

The frozen candidate preserved the earlier round-six escapes and later
property-bearing egress inventory as real FastMCP client and
production-middleware regressions, but a genuinely clean-context audit found
additional release blockers. That hash is rejected and cannot be committed.

The candidate is frozen and uncommitted at composite tracked-plus-untracked
content hash
`764037631b70be2c394fa42e3a98d2b44ae99e93faa57e7f988f808a31c4437d`.
Controller verification on 2026-08-03 independently passed the permanent
24-case and 48-case protocol matrices and adjacent required-location cases
inside a 155-test selector, all 1,889 access tests, the strict three-test mixed
lifecycle gate, and all 3,600 repository tests. Only the categorized upstream
Authlib deprecation remains.

The clean audit reproduced a nested Miami, Florida property release for every
one of these Texas-restricted JV-visible tools through a real FastMCP client and
the production access middleware: `overnight_changes`,
`stale_listing_signals`, `match_buyers`, `meeting_briefing`, `deal_timeline`,
`counterparty_dossier`, and `match_lenders`. Each tool had no request territory
parameter and no result territory contract, so middleware released the payload
and recorded an `allowed` event. The strongest production implementation case
used `deal_timeline`, whose store persists arbitrary event detail JSON and
returns it verbatim.

The same audit reproduced a false denial for a complete canonical result under
an exact `Washington, DC` grant and request when the result used the
production-shaped split `address="100 Main Street"`, `city="Washington"`,
`state="DC"`, and `zip_code="20001"`. The parser misclassified the city as the
state of Washington and required the street-only address to repeat the city.
`New York, NY` and other municipality/state-name collisions share the defect.

The authority normalization review also found six exact, unambiguous place
names present in the pinned Census/postal data but rejected before tool
execution because the request parser forbids every digit in a city name:
`Route 7 Gateway, CT 06877`; `Kickapoo Site 1, KS 66439`; `Kickapoo Site 2, KS
66439`; `Kickapoo Site 5, KS 66439`; `Kickapoo Site 7, KS 66439`; and `Kickapoo
Site 6, KS 66527`. Real FastMCP calls with matching exact grants and requests
were denied before execution even though the checked-in authority recognized
each city/state/ZIP combination.

Tests-first repair evidence is now preserved. Before geography production
edits, the new real-protocol selector reported `16 failed, 1 passed`; after the
narrow authority fix it reports `17 passed`, and the combined relevant
territory selection reports `1,849 passed`. Before any seven-tool production
edit, the new store-workflow selector reported `7 failed, 1 passed`, with all
seven releases audited `allowed`. The store-workflow repair is still in
progress and has no green status. After adding exact-denial, positive-flow, and
malformed-carrier controls but before the tailored production repair, that
selector reports `28 failed, 8 passed`. Controller rerun of the locked priority
matrices now reports `125 passed`: the permanent 24 cross-profile/collection
cases, 48 exact state/city/ZIP cases, 48 required address/city/state
omitted-null-empty-type cases, and four real Crexi-mapping blank-location cases.
The first completed store-backed boundary, the production `deal_timeline`
wrapper using the actual `DealStore`, reports `8 passed, 32 deselected`; the
second, the production `match_buyers` wrapper using the owned buyer store,
reports `9 passed, 43 deselected` on approved Python 3.11.15, with all 50
disposition tests also green.
The third, the production `match_lenders` wrapper using the workspace-owned
lender database, reports `17 passed, 35 deselected`, with all 19 financing
operations tests green. The production `overnight_changes` and
`stale_listing_signals` wrappers now add actual SnapshotStore/DealStore
positive and denial paths; together they report `18 passed, 42 deselected`,
with all 10 command tests green. The two relation workflows remain in
progress, so this is not a phase approval.
An independent approved-Python selector covering normalized case, state
names/codes, country suffixes, ZIP/ZIP+4 equivalence, exact city/state pairs,
and incomplete or ambiguous city failures reports `120 passed`.
A separate read-only inventory confirmed the locked matrices are exact real
FastMCP client plus production-middleware tests, but also recorded two
pre-commit obligations: `tests/access/test_result_territory.py` is still an
untracked certification file and therefore is not permanent until included in
the eventual approved commit, and the phase specification cited the wrong
containing module. The specification citation and its stale approval language
are now corrected; inclusion of the untracked regression module remains a
commit-time gate. A separate 12-case real-protocol selector confirms that an
unknown supplied city/state/ZIP combination fails closed even under a valid
state grant.

A preliminary read-only location-contract QA then reproduced another request
escape through the real FastMCP client and installed middleware: list-valued
territory parameters silently discarded null, numeric, and whitespace-only
members, allowing a valid Dallas sibling to authorize and execute the call.
The exact two-profile protocol selector first reported `6 failed`. After the
request parser was changed to require a JSON list whose every member is a
nonblank string, the complete round-seven geography module reports `23 passed`;
the adjacent legacy territory selectors report `24 passed`. This finding is
preserved and OAuth remains yellow.

One earlier reported approval remains excluded because its reviewer
participated in rejected rounds. OAuth remains yellow and uncommitted until all
new findings are permanent real-protocol regressions, the repair is fully
gated, and two fresh independent reviews approve the new stable hash.

### OAuth round-seven controller reconciliation 2026-08-03: tree is RED

Independent read-only controller verification on 2026-08-03 contradicts the
green evidence recorded above. The recorded `4,112 passed` repository result is
not reproducible on the current tree. The same command, on the approved Python
3.11.15 interpreter with `-p no:cacheprovider` and an isolated `CRE_MCP_ROOT`,
now reports **52 failed and 4,078 passed**, reproduced twice at 97.36 and 91.76
seconds. Only the categorized third-party Authlib deprecation warning appears.

The failure set is not stable. It changes with test execution order:

| Selection | Result |
| --- | --- |
| Full repository | 52 failed, 4,078 passed |
| `tests/access` | 4 failed, 2,415 passed (a different set) |
| `test_result_territory.py` alone | 30 failed, 1,016 passed |
| `test_territory_release_regressions.py` alone | 8 failed, 763 passed |
| `test_territory_round7_market_binding.py` alone | 140 passed |
| `test_territory_round7_geo.py` alone | 2 failed, 263 passed |
| `test_territory.py` alone | 17 passed |
| `test_result_territory.py` then round-seven geography | 32 failed, 1,279 passed |
| `test_territory_round7_market_binding.py` then geography | 2 failed, 401 passed |

`test_market_intel_releases_exact_national_city_and_zip_georefs` passes all
eight cases when run alone and fails all eight inside the full repository run.
Adding more tests makes some failures disappear and others appear, so the
authorization outcome depends on module import order rather than on the request,
the grant, and the returned record alone. Failures surface through the
`unresolvable` branch of `access denied: tool result is outside or unresolvable
for this workspace's territory`.

Three defects are now recorded as the active blockers:

1. Territory enforcement is order dependent. This is an authorization defect,
   not only a test-isolation defect, because a load order can change whether a
   record is released. Consequently every previously recorded green number for
   this phase, including `4,112 passed`, `2,401 passed`, and the focused
   `132`/`389`/`406` results, is order conditional and is not valid release
   evidence.
2. A live release escape exists.
   `test_ambiguous_same_name_city_grant_fails_closed_before_release` is a
   fail-closed control. It passes in isolation and fails inside `tests/access`,
   so an ambiguous same-name city grant releases under some orders.
3. Deterministic false denials remain.
   `test_market_intel_releases_census_geocoder_city_name_shape` fails in
   isolation for both restricted profiles, and the round-six Washington, DC
   split-location control
   `test_exact_state_name_city_grant_releases_split_location_record[washington-dc-*]`
   still reproduces.

A structural gap is also recorded. `_geo_record_claims` in
`src/cre_mcp/access/engine.py` is documented as deriving claims only when every
populated GeoRef carrier reconciles, but it inspects only `level`,
`state_fips`, `name`, `county_fips`, `tract`, `cbsa`, and `zip`. There is no
declared-key allowlist, so any other populated key such as `zip_code`,
`place_fips`, `csa`, `county_name`, `state_name`, or `metro` is silently ignored
and cannot contradict a grant. Both of the two most recent reviewer findings
were this class. Enumerating carriers one reviewer at a time has now failed
seven rounds.

No candidate hash may be frozen and no reviewer may be commissioned until the
full suite is green and proven order stable across at least three independent
orderings. OAuth remains yellow and uncommitted. The PostgreSQL and
source-rights worktrees remain frozen and untouched.

### OAuth round-seven authority reconciliation 2026-08-03: focused gates GREEN, phase YELLOW

This checkpoint supersedes the active-defect description immediately above,
but it does not erase that rejected evidence. OAuth remains dirty,
uncommitted, and ineligible for review approval until the wider ordering,
repository, packaging, lifecycle, and exact-tree gates are complete.

The current repair replaces name-only city inference with pinned Census place,
county, ZCTA, tract, and CBSA relationships. Same-name city claims require one
surviving Census place after county and ZIP intersection. Exact assigned postal
localities that are not Census places, including Bronx and Staten Island, may
fall back only when an assigned city/ZIP pair and the ZIP's authoritative
county set converge. A real tract carrier must exist in the pinned Census tract
authority; a city-level result carrying any tract remains denied because the
available public relationships cannot prove tract-to-place containment.

The earlier GeoRef declared-key gap is now locked at the actual result boundary:
the closed typed result is recursively validated with unknown fields forbidden,
and six provider-shaped nested carrier aliases are permanent real FastMCP tests
for both restricted profiles. Postal fallback consistency is also permanent at
two protocol boundaries: ZIP-level market GeoRefs and county-contained rent
comparables for Bronx 10451 and Staten Island 10301. Ambiguous Burbank, Chevy
Chase, Pewaukee, and Superior grants remain pre-execution denials.

Current command evidence:

- the locked 24 cross-profile/collection, 48 exact state/city/ZIP, 48 required
  address/city/state malformation, and four real Crexi-shaped empty-location
  cases pass as one 125-test real FastMCP/middleware gate;
- `test_result_territory.py` passes 1,047 tests;
- `test_territory.py` plus `test_territory_round7_geo.py` pass 302 tests;
- release-regression plus portfolio-property modules pass 808 tests;
- all seven store-backed workflow regressions pass 86 tests;
- the expanded market/GeoRef module plus same-name ambiguity controls pass 169
  tests;
- deterministic rebuilds from the pinned official inputs are byte-identical:
  52,565 ZCTA/place rows at SHA-256
  `8a0d94a3743873cf2b9761c3aa79fa7884703903611f6f9163b758ddb0822476`,
  and 254,935 national relationship rows (`C=3,221`, `P=33,298`,
  `Z=46,777`, `T=169,733`, `B=1,906`) at SHA-256
  `ec28297f8f5bd29328c1cd696a7d007c3d80f083def465de3e6b017393e6b6e8`.

The earlier order-dependence finding is cleared by the 2,484-case access run,
both 2,283-case opposite-order runs, and the 4,195-case repository run recorded
below. Two fresh neutral reviewers independently repeated the gates, inspected
the full diff, reproduced the exact `e96da4b...` hash, and approved it with no
blocking finding. The exact candidate was committed as `88e3082`.

### Superseded portal branches: selective salvage only

Read-only archaeology confirmed backend tip `8a44d4c` and frontend tip
`13abbf5` must not be merged or cherry-picked wholesale. The frontend is native
DOM JavaScript with no React dependency, JSX, package lock, or React build. Its
customer Deals, Search, entitlements, saved-deal, and pseudo-router surfaces are
forbidden by the founder's connection-only decision.

Safe inputs are limited to:

- pinned `reicon@1.1.103` MIT provenance, tarball integrity, source digests, and
  digest tests as a pattern; the required React entry must be independently
  verified before use;
- exact redirect, PKCE, replay, live bearer, owned-session, and revocation
  invariants already rooted in the OAuth lineage;
- self-scoped consent and privacy queue primitives, after adding correction,
  fulfillment, processor propagation, evidence, and concurrency controls;
- internal role, reason, live recheck, append-only audit, rollback, route-shape,
  accessibility, reduced-motion, CSP, and browser-test patterns.

The inherited browser lacks real production authentication. Its tests inject a
bearer through loopback middleware while the UI sends only same-origin cookies.
The launch build therefore needs a real secure browser-session/BFF boundary with
CSRF controls. The internal console also needs a separately protected origin or
router, workforce identity, and network controls. Path hiding on the customer
application is insufficient. Host-derived absolute redirects are rejected
unless trusted-host validation is proven.

## Verified command evidence

| Date | Scope | Command summary | Result |
| --- | --- | --- | --- |
| 2026-08-01 | Capability matrix | Import production server and compare registered names to matrix | 274 registered, 274 classified, no missing or stale entries |
| 2026-08-01 | Profiles | Recompute allowed tools from the live matrix | Local 103; National 115; Full 274; JV 170 |
| 2026-08-01 | OAuth full suite | `PYTHONPATH=<oauth>/src ... python -m pytest -p no:cacheprovider -q` | 1,521 passed; one categorized third-party Authlib deprecation |
| 2026-08-01 | OAuth strict lifecycle | OAuth test file with asyncio debug and lifecycle warnings promoted | 35 passed; no pending application task |
| 2026-08-01 | OAuth focused repetition | Real HTTP initialize and cleanup selection repeated ten times | 20 total focused passes; no pending-task stderr |
| 2026-08-01 | OAuth audit round one | Independent result-policy and lifecycle review after 1,800 passing tests | Changes required: 2 high and 2 medium findings; no approval |
| 2026-08-01 | OAuth audit round two | Fresh read-only diff audit plus end-to-end adversarial serializer and hidden-location probes | Rejected: 2 high disclosure paths; checked-in focused selection was 87 passed |
| 2026-08-01 | OAuth audit round three | Fresh read-only stable-diff audit plus a 36-case middleware matrix and mutated discriminator probe | Rejected: 36/36 contradictory records released, invalid `TextContent` discriminator released, and 2 ordinary-address false denials; focused baseline was 111 passed |
| 2026-08-01 | OAuth audit round four | New independent FastMCP matrix after 1,959 green tests | Rejected: 48/48 state-only contradictory records released and audited as allowed across profile, collection, separator, and exact-grant variants |
| 2026-08-01 | OAuth audit round five | New independent real-FastMCP protocol matrices after a 321-test focused baseline | Rejected: 24/24 cross-profile/collection denials and 48/48 city/state/ZIP denials released; incomplete typed locations and a Crexi-shaped blank-location record also released |
| 2026-08-02 | OAuth audit round six | Fresh neutral stable-fingerprint diff review plus independent real-FastMCP probes after 2,342 green tests | Rejected: one multi-field request escape, two returned-location contradictions, and one Washington, DC false denial; no reviewer edits |
| 2026-08-03 | OAuth mandatory protocol confirmation | Root-run real FastMCP/middleware selector covering the permanent 24 and 48 matrices, required fields, Crexi blank locations, unknown envelopes, and refreshed-detail denial | 155 passed; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth access confirmation | `PYTHONPATH=<oauth-cert>/src ... python -m pytest -p no:cacheprovider -q tests/access` with isolated temporary root | 1,889 passed; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth strict lifecycle confirmation | Real HTTP OAuth test followed by two entitlement tests with asyncio debug and lifecycle warnings promoted | 3 passed; no unclosed loop, socket, transport, stream, task, or coroutine |
| 2026-08-03 | OAuth full-suite confirmation | `PYTHONPATH=<oauth-cert>/src ... python -m pytest -p no:cacheprovider -q` with isolated temporary root | 3,600 passed in 74.01 seconds; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth locked territory matrices | Approved Python 3.11.15 interpreter; real FastMCP client plus installed production middleware: count lock, 24 cross-profile/collection cases, 48 exact state/city/ZIP cases, 48 required-field cases, and four Crexi blank-location cases | 125 passed; one categorized third-party Authlib deprecation; OAuth remains yellow |
| 2026-08-03 | OAuth store workflow incremental boundary | Production `deal_timeline` wrapper with actual `DealStore`, in-scope and denied/malformed cases through FastMCP middleware | 8 passed, 32 deselected; one categorized third-party Authlib deprecation; six workflows remain |
| 2026-08-03 | OAuth buyer-match incremental boundary | Approved Python 3.11.15; production `match_buyers` wrapper with actual owned buyer store, nested request-location enforcement, typed release projection, and denied/malformed cases through FastMCP middleware | 9 passed, 43 deselected; all 50 disposition tests passed; one categorized third-party Authlib deprecation; five workflows remain at this checkpoint |
| 2026-08-03 | OAuth lender-match incremental boundary | Approved Python 3.11.15; production `match_lenders` wrapper with actual workspace-owned lender database, list-valued request intersection, closed result projection, whole-call mixed-location denial, and full-operator compatibility | 17 passed, 35 deselected; all 19 financing-operations tests passed; one categorized third-party Authlib deprecation; four workflows remain |
| 2026-08-03 | OAuth command-workflow incremental boundary | Approved Python 3.11.15; production `overnight_changes` and `stale_listing_signals` wrappers backed by actual SnapshotStore/DealStore records, mixed-result denial, malformed/unknown/key-mismatch denial, and full-operator compatibility | 18 passed, 42 deselected; all 10 command tests passed; one categorized third-party Authlib deprecation; two relation workflows remain |
| 2026-08-03 | OAuth normalization boundary | Approved Python 3.11.15 interpreter; real FastMCP/middleware selectors for case, state names/codes, country suffixes, ZIP/ZIP+4, exact city/state pairs, and unknown/ambiguous cities | 120 passed; one categorized third-party Authlib deprecation; OAuth remains yellow |
| 2026-08-03 | OAuth protocol regression inventory | Independent read-only count and helper-path inspection plus approved-Python reproduction | Exact 73-node count-plus-24-plus-48 selector and 72-node required-field/Crexi/optional-ZIP selector passed; test module remains untracked and spec citation must be corrected before freeze |
| 2026-08-03 | OAuth specification integrity | Correct stale module citation, rejected-candidate approval language, and unknown-combination policy; approved-Python state-grant regression selector | 12 passed for nonexistent supplied city/state/ZIP fail-closed behavior; regression module still must be included in the eventual commit; OAuth remains yellow |
| 2026-08-03 | OAuth strict location-array boundary | Preliminary QA real-FastMCP reproduction across Local Scout and JV Partner, followed by tests-first repair on approved Python 3.11.15 | RED: 6 failed because null, numeric, and blank members were discarded beside Dallas; GREEN: 23 round-seven geography tests and 24 adjacent territory tests passed; OAuth remains yellow |
| 2026-08-03 | OAuth seven store-backed workflow boundary | Approved Python 3.11.15; all seven rejected JV-visible workflows exercised through production-backed stores, tailored closed result projections, real FastMCP client, and installed middleware, followed by native relation tests | 108 passed: 86 store-workflow protocol cases plus 22 native relation tests; no generic transitional result DTO remains; broader OAuth phase remains yellow |
| 2026-08-03 | OAuth round-seven scalar and property geography boundary | Approved Python 3.11.15; real FastMCP/middleware matrix covering invalid collection members, unresolved compound tails, incomplete street/locality tails, strict parcel addresses, structured-address contradictions, empty owner parcels, county-FIPS conflicts, and valid unit formats | RED captured 24 valid-unit false denials; repair rerun is 195 passed with one categorized third-party Authlib deprecation; independent preflight is still expanding permanent escape coverage, so OAuth remains yellow |
| 2026-08-03 | OAuth market and GeoRef binding RED | Approved Python 3.11.15; tests-only real FastMCP/middleware matrix for exact request-to-GeoRef binding, GeoRef carrier reconciliation, every rent-comparable location, and exact compare-market multisets | 107 collected; RED is 68 failed and 39 passed after adding six independently reproduced carrier contradictions and four controls; no production change was made for this matrix at the checkpoint |
| 2026-08-03 | OAuth adjacent positive-control gate RED | Approved Python 3.11.15; combined `test_result_territory.py`, `test_territory_round7_geo.py`, and `test_territory_release_regressions.py` run against the current uncommitted tree | 2,006 passed and 6 failed: valid `NE`/`OR` directional-address requests and Denver county-comp controls are over-restricted; must be repaired without weakening fail-closed territory enforcement |
| 2026-08-03 | OAuth round-seven binding and typed-location repair | Approved Python 3.11.15; root and independent reruns of the expanded geography, exact market/result binding, and portfolio property-address modules through real FastMCP clients and installed production middleware | 406 passed; every earlier market escape is closed; explicit same-place `Dallas, TX: 75201` and `Dallas, TX zip 75201` controls pass under both restricted profiles; one categorized third-party Authlib deprecation; OAuth remains yellow |
| 2026-08-03 | OAuth portfolio property-address boundary | Approved Python 3.11.15; malformed request and returned addresses, empty owner-property collections, count consistency, and valid property anchors through FastMCP/middleware | 37 passed; typed owner properties are nonempty and every returned property carries a complete authoritative address; one categorized third-party Authlib deprecation; OAuth remains yellow |
| 2026-08-03 | OAuth capability-schema focused gate | Approved Python 3.11.15; capability coverage and declaration validation after adding typed result-location bindings | 11 passed; one categorized third-party Authlib deprecation; broader gates and independent approvals remain |
| 2026-08-03 | OAuth wider territory/profile gate RED | Approved Python 3.11.15; 16-file focused selection spanning result territory, release regressions, round-seven matrices, profiles, dual enforcement, server authority, relations, geo, and market tools | 2,396 passed and 12 failed: two production-emitted county GeoRefs used a city-shaped name, while ten pre-binding positive fixtures no longer provided exact request/result identity; OAuth remains yellow |
| 2026-08-03 | OAuth county-producer and stale-control repair | Approved Python 3.11.15; exact rerun of the prior failing analyze-deal, authoritative county, and property-bearing positive-control families through FastMCP/middleware | 42 passed and 1,775 deselected; the producer now emits a county-shaped authoritative name and controls use exact request/result levels with required rent-comparable locations; one categorized third-party Authlib deprecation; full focused rerun remains |
| 2026-08-03 | OAuth wider territory/profile gate GREEN | Approved Python 3.11.15; exact rerun of the 16-file result-territory, release-regression, round-seven, profile, dual-enforcement, server-authority, relations, geo, and market selection | 2,408 passed in 22.90 seconds; one categorized third-party Authlib deprecation; the earlier 12 failures are repaired without weakening exact binding; OAuth remains yellow pending access/full gates and two fresh approvals |
| 2026-08-03 | OAuth complete access gate GREEN | Approved Python 3.11.15; `pytest -p no:cacheprovider -q tests/access` with an isolated cache database | 2,381 passed in 22.39 seconds; one categorized third-party Authlib deprecation; OAuth remains yellow pending repository-wide and independent approval gates |
| 2026-08-03 | OAuth repository-wide gate GREEN | Approved Python 3.11.15; `pytest -p no:cacheprovider -q` with an isolated cache database after exact-binding and county-producer repairs | 4,092 passed in 87.46 seconds; one categorized third-party Authlib deprecation; this suite does not override later independent gaps and OAuth remains yellow |
| 2026-08-03 | OAuth national GeoRef authority gap RED | Independent read-only real FastMCP/middleware probes using exact request, grant, and returned identity | Dallas/75201 controls release, but exact Seattle and Los Angeles city GeoRefs and 98101/90001 ZIP GeoRefs are denied after execution because result reconciliation depends on 13-city and six-ZIP fallback tables; add permanent protocol regressions and authoritative national reconciliation before review |
| 2026-08-03 | OAuth national GeoRef regressions locked | Approved Python 3.11.15; permanent real FastMCP client plus production-middleware city/ZIP controls and same-state contradiction controls across both restricted profiles | RED: 8 exact Seattle/Los Angeles and 98101/90001 releases denied after execution; 8 wrong-county/CBSA contradictions already denied; full market-binding module baseline was 8 failed and 116 passed |
| 2026-08-03 | OAuth national relationship repair | Integrity-checked Census county, place/county, assigned ZCTA/county, and July 2023 county/CBSA authority; exact national release and contradiction selectors followed by full market-binding module | 16 targeted protocol cases passed; 124 market-binding cases passed; data artifact SHA-256 `9953a1130ec03c8d050cf85187fdf3a0eaf66a42a026bebcc49fdcb7207bd9db`; OAuth remains yellow |
| 2026-08-03 | OAuth national-normalization collision repair | Complete access gate found an independent-city grammar collision with unpunctuated `Kansas City MO` street tails; grammar narrowed while preserving county-equivalent identities and exact national controls | RED: 2 access failures; focused repair selector passed 21; complete access rerun passed 2,401 with one categorized third-party Authlib deprecation; OAuth remains yellow pending repository-wide and review gates |
| 2026-08-03 | OAuth post-national repository-wide gate GREEN | Approved Python 3.11.15; captured `PYTHONPATH=<oauth-cert>/src ... python -m pytest -q --disable-warnings` session after national authority and normalization-collision repair | Exit 0; 4,112 passed in 78.02 seconds; one categorized third-party Authlib deprecation; OAuth remains yellow pending two fresh independent approvals |
| 2026-08-03 | OAuth post-repair review candidate frozen | Deterministic SHA-256 over sorted tracked plus untracked non-ignored working files, executable bits, and bytes in `/Users/maxmedawar/LoopnetMCP-oauth-launch-cert` | `b443393d62e20acba8e77f539630524be2c7cfee2320bd4c49008a982494c3c3` across 932 files; dirty and uncommitted; two fresh neutral reviews commissioned against this exact hash |
| 2026-08-03 | OAuth final locked-priority gate | Approved Python 3.11.15; exact count-lock plus permanent 24 cross-profile/collection, 48 state/city/ZIP, 48 omitted/null/empty/non-string required-location, and four Crexi blank-location real FastMCP selectors | 125 passed in 1.34 seconds; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth final strict lifecycle gate | `PYTHONASYNCIODEBUG=1`; ResourceWarning and RuntimeWarning promoted for real HTTP OAuth initialize/list/call/close followed by two async entitlement tests | 3 passed in 1.49 seconds; no owned lifecycle warning; only categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth authority reproducibility and packaging gate | Re-download pinned Census sources, rebuild to temporary output, byte-compare artifact, build wheel without dependencies, inspect packaged authority files, recheck dependency/lock diff, capability counts, port 8000, compile, and diff whitespace | Rebuild byte-identical at `9953a113...`; all three gzip authorities plus attribution in wheel; no dependency or lock change; 274 capabilities and 103/115/274/170 profile counts unchanged; no port-8000 listener; compile and `git diff --check` pass |
| 2026-08-03 | OAuth frozen-candidate relation escape RED | Fresh neutral reviewer B, exact frozen hash `b443393d...`, real FastMCP client and installed production middleware, exact `00601` request/grant | A ZIP GeoRef named `Adjuntas, PR 00601` carrying Utuado county FIPS `72141` released under both restricted profiles even though authoritative Adjuntas city counties and ZIP counties had no common intersection with that carrier; frozen candidate rejected and review approvals invalidated |
| 2026-08-03 | OAuth city/ZIP/county intersection repair | Tests-first permanent GeoRef and county-sale property regressions through real FastMCP and production middleware across Local Scout and JV Partner; shared reconciliation repair | RED: 2 GeoRef and 2 returned-property releases; GREEN: all 4 exact cases pass and the complete round-seven market plus geography modules pass 389 tests; OAuth remains yellow pending diagnostic findings, full gates, a new hash, and two fresh reviews |
| 2026-08-03 | OAuth embedded GeoRef ZIP carrier RED | Fresh neutral reviewer A, real FastMCP client and installed production middleware, exact Dallas request/grant | A city GeoRef named `Dallas, TX 78701` released under both restricted profiles because its embedded Austin ZIP was discarded when the dedicated ZIP field was absent; current repair tree rejected and no approval permitted |
| 2026-08-03 | OAuth embedded GeoRef ZIP repair | Permanent contradictory and matching embedded-ZIP controls across Local Scout and JV Partner, with embedded name ZIP promoted into the shared carrier set before city/county/ZIP reconciliation | RED: 2 contradictory releases and 2 matching controls passed; GREEN: all 4 exact cases and all 132 round-seven market-binding tests pass; OAuth remains yellow pending remaining diagnostics, full gates, a new hash, and two fresh reviews |
| 2026-08-03 | OAuth controller repository-wide reverification RED | Independent read-only controller rerun of the recorded full-suite command on approved Python 3.11.15 with `-p no:cacheprovider` and an isolated `CRE_MCP_ROOT`, executed twice | 52 failed and 4,078 passed in 97.36 and 91.76 seconds; the recorded `4,112 passed` does not reproduce; only the categorized third-party Authlib deprecation appears; OAuth moved to RED |
| 2026-08-03 | OAuth order-dependence isolation matrix | Same interpreter and flags; each implicated access module run alone and in pairs to test outcome stability | `tests/access` 4 failed / 2,415 passed; `test_result_territory.py` alone 30 failed / 1,016 passed; `test_territory_release_regressions.py` alone 8 failed / 763 passed; `test_territory_round7_market_binding.py` alone 140 passed; `test_territory_round7_geo.py` alone 2 failed / 263 passed; `test_territory.py` alone 17 passed; result-territory then geography 32 failed / 1,279 passed; market-binding then geography 2 failed / 401 passed |
| 2026-08-03 | OAuth order-dependent authorization outcome | `test_market_intel_releases_exact_national_city_and_zip_georefs` run alone and inside the full repository suite | 8 passed alone and 8 failed in the full run; authorization outcome depends on module import order, so every prior green number for this phase is order conditional and is not release evidence |
| 2026-08-03 | OAuth fail-closed control escape RED | `test_ambiguous_same_name_city_grant_fails_closed_before_release` run alone and inside `tests/access` | Passes in isolation and fails inside the access suite; an ambiguous same-name city grant releases under some orders |
| 2026-08-03 | OAuth deterministic false denials RED | Isolated real-FastMCP reruns of the affected positive controls | `test_market_intel_releases_census_geocoder_city_name_shape` fails for both restricted profiles in isolation; the round-six `washington-dc` split-location control still reproduces |
| 2026-08-03 | OAuth GeoRef declared-key gap | Read-only inspection of `_geo_record_claims` in `src/cre_mcp/access/engine.py` | No declared-key allowlist exists; only `level`, `state_fips`, `name`, `county_fips`, `tract`, `cbsa`, and `zip` are inspected, so populated undeclared carriers such as `zip_code`, `place_fips`, `csa`, `county_name`, `state_name`, and `metro` cannot contradict a grant |
| 2026-08-03 | OAuth frozen-worktree confirmation | Read-only status of every MedawarCRE worktree plus listener check | oauth-cert 42 modified and 6 untracked paths; postgres 6 uncommitted paths; source-rights 114 uncommitted files, both left untouched; no listener on port 8000 |
| 2026-08-03 | OAuth locked priority protocol gate after authority repair | Approved Python 3.11.15; count lock plus permanent 24 cross-profile/collection, 48 exact state/city/ZIP, 48 required-field, and four real Crexi empty-location cases through real FastMCP and installed middleware | 125 passed in 1.95 seconds; one categorized third-party Authlib deprecation; OAuth remains yellow |
| 2026-08-03 | OAuth closed nested GeoRef carrier gate | Six provider-shaped undeclared location aliases injected inside an otherwise valid Dallas GeoRef across Local Scout and JV Partner, through real FastMCP and installed middleware | 13 passed including matrix cardinality; every alias denied after execution by the closed recursive result contract |
| 2026-08-03 | OAuth exact postal GeoRef and county-containment repair | Tests-first Bronx 10451 and Staten Island 10301 controls across ZIP-level market GeoRefs and county-contained rent comparables, both restricted profiles; same-name ambiguity controls included | RED: four market and four rent controls denied; GREEN: expanded market plus ambiguity selection passed 169; postal fallback is allowed only with exact assigned ZIP and authoritative county convergence |
| 2026-08-03 | OAuth focused post-authority corpus | Approved Python 3.11.15; typed results, place/GeoRef authority, release/portfolio regressions, and store-backed workflows run in four isolated commands | 1,047 + 302 + 808 + 86 passed; one categorized third-party Authlib deprecation per process; no focused failure |
| 2026-08-03 | OAuth Census authority deterministic rebuild | Pinned official county, place, ZCTA/county, ZCTA/tract, CBSA, and ZCTA/place inputs; approved builder scripts; temporary outputs byte-compared with checked-in gzip artifacts | 52,565 ZCTA/place rows, SHA-256 `8a0d94a3...`; 254,935 national rows (`C=3221`, `P=33298`, `Z=46777`, `T=169733`, `B=1906`), SHA-256 `ec28297f...`; both byte-identical and `gzip -t` clean |
| 2026-08-03 | OAuth complete access gate | Approved Python 3.11.15; isolated runtime root; cache provider disabled | 2,484 passed in 26.74 seconds; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth opposite-order stability gates | The four previously unstable territory modules run in both collection orders from separate isolated runtime roots | 2,283 passed in 31.14 seconds and 2,283 passed in 24.32 seconds; one categorized third-party Authlib deprecation per process |
| 2026-08-03 | OAuth repository-wide gate | Approved Python 3.11.15; isolated runtime root; cache provider disabled | 4,195 passed in 86.50 seconds; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth strict lifecycle gate | Asyncio debug enabled; ResourceWarning, RuntimeWarning, and pytest unraisable warnings promoted to errors | 4 passed in 1.56 seconds; no owned lifecycle warning; one categorized third-party Authlib deprecation |
| 2026-08-03 | OAuth packaging and static gates | Compile source, diff whitespace, package-data-only manifest review, wheel inspection, authority gzip integrity, release-locked capability counts, and port 8000 check | Green; 274 capabilities; Local 103, National 115, Full 274, JV 170; no port-8000 listener; dependencies and lockfiles unchanged |
| 2026-08-03 | OAuth review candidate frozen | SHA-256 over sorted tracked plus untracked non-ignored files, framed by path length/path, executable or symlink mode, content length, and bytes | `e96da4b8345099bb1bac64d5af54e397da8e7fcd0aee14d194a3abebfbc5ca65` across 932 files; candidate worktree unchanged after freeze; two fresh neutral approvals required |
| 2026-08-03 | OAuth independent release review A | Fresh read-only exact-hash review; full diff, adversarial result-release probes, complete access, both opposite orders, lifecycle, repository, package, compile, capability, and integrity gates | APPROVED exact `e96da4b...`; 2,484 access, 2,283 plus 2,283 opposite-order, 4 lifecycle, and 4,195 repository tests passed; no blocking finding |
| 2026-08-03 | OAuth independent release review B | Fresh read-only exact-hash review; authoritative lifecycle, live entitlement and quota, migration, cleanup, complete repository, both opposite orders, package, compile, capability, and integrity gates | APPROVED exact `e96da4b...`; 4,195 repository, 4 lifecycle, and both 2,283 opposite-order runs passed; no blocking finding |
| 2026-08-03 | OAuth certification commit | Stage the unchanged twice-approved candidate, recheck staged diff, and commit one phase boundary | `88e3082109f80722e78d0712ed07028f050e015f` (`feat: certify authoritative OAuth territory enforcement`) |
| 2026-08-03 | PostgreSQL repaired candidate frozen | SHA-256 over sorted tracked plus untracked non-ignored files using the same path, mode, and content framing as OAuth | `2af2a9077a2f933110cf68b7386a0830ef814df327756420e82f38abf20c6388` across 940 files; 62 native PostgreSQL and 1,832 repository tests passed; compile, wheel SQL resource, secret-pattern, diff, and port checks green; two fresh neutral approvals required |
| 2026-08-03 | PostgreSQL independent reviews reject first candidate | Two fresh read-only release-correctness reviews of exact `2af2a907...` | Both reviewers found the same high-severity migration preflight gap: a relation directly owned by the migration login passed because direct and inherited ownership were conflated; candidate invalidated without commit |
| 2026-08-03 | PostgreSQL direct-ownership regression and repair | Minimal ordinary-table reproduction first captured RED; authority query then separated direct owner OIDs from effective group ownership | RED: relation case did not raise; GREEN: database, schema, relation, function, and type direct ownership rejected, pre-mutation database-owner rejection passed, and group-inherited ownership remained accepted |
| 2026-08-03 | PostgreSQL replacement gates | Sequential native PostgreSQL and repository suites plus compile, wheel-resource, secret-pattern, diff-whitespace, and port checks | 69 PostgreSQL tests passed in 22.37 seconds; 1,839 repository tests passed in 108.46 seconds; packaged SQL resources present; no secret-pattern hit or port-8000 listener |
| 2026-08-03 | PostgreSQL replacement candidate frozen | Deterministic SHA-256 over sorted tracked plus untracked non-ignored files with path, mode, length, and content framing | `f68a9a489602ef0b22614e899e5800820c0579e12002afce83c7aaa613f0e9e6` across 940 files; two fresh neutral approvals required |
| 2026-08-03 | PostgreSQL replacement independent review C | Fresh read-only exact-hash contract, authority, PG16, migration, RLS, recovery, package, and repository review | APPROVED exact `f68a9a4...`; 7 ownership regressions, 69 PostgreSQL tests, and 1,839 repository tests passed; no blocking finding or hash drift |
| 2026-08-03 | PostgreSQL replacement independent review D | Fresh read-only exact-hash static and isolated execution review | APPROVED exact `f68a9a4...`; deterministic hash reproduced across 940 paths; no candidate assertion failure or release blocker; environmental cluster restart failure did not alter the verdict |
| 2026-08-03 | PostgreSQL certification commit | Stage the unchanged twice-approved candidate, check the staged diff, and commit one phase boundary | `5089748aaa6f9f726db5801f866a130974d1eb89` (`feat: add certified PostgreSQL persistence foundation`); worktree clean |
| 2026-08-01 | PostgreSQL repair snapshot | Release-audit regressions, PostgreSQL selection, full repository, native restore/service smoke, compile, wheel, diff, secret, and artifact checks | 31 release regressions passed; 62 PostgreSQL tests passed; 1,832 full tests passed; first audit findings repaired; two fresh approvals still required |
| 2026-08-01 | Source-rights implementation snapshot | Source-rights selection, impacted selection, full repository, compile, diff, secret, artifact, and egress inventory checks | 64 source-rights tests passed; 1,946 full tests passed; independent egress inventory clear; two fresh release approvals still required |
| 2026-08-03 | Source-rights wheel registry RED and repair | Pre-review wheel inspection followed by a package-data regression and smallest `pyproject.toml` repair | RED: `cre_mcp/source_rights/registry.json` absent from wheel; GREEN: package-data test passed and rebuilt wheel contains the canonical registry |
| 2026-08-03 | Source-rights replacement gates | Sequential focused and repository suites plus compile, wheel, inventory, secret, diff, and port checks | 161 source-rights tests passed; 1,947 repository tests passed in 65.33 seconds; registry packaged; no secret-pattern hit or port-8000 listener |
| 2026-08-03 | Source-rights review candidate frozen | Deterministic SHA-256 over sorted tracked plus untracked non-ignored files with path, mode, length, and content framing | `e58c7215ce7a75c9d2f0740423be93753728864536585d634b7db8a54e158503` across 929 files; two fresh neutral approvals required |
| 2026-08-03 | Source-rights first candidate rejected | Two fresh read-only release-correctness reviews of exact `e58c721...` | Valid blockers: the registry admitted `hosted_cloud_allowed=true` with `trusted_local_only=true`, the hosted gate ignored the contradictory local-only flag, and a clean interpreter import of the gate cycled through eager access middleware; no approval or commit |
| 2026-08-03 | Source-rights fail-closed policy and import repair | Tests first at registry load, public hosted gate, and clean-interpreter import boundaries | RED: both contradictory-policy paths released and the clean import raised a partial-initialization `ImportError`; GREEN: schema rejects the contradiction, gate defense-in-depth denies it, and access middleware exports load lazily without breaking their public imports |
| 2026-08-03 | Source-rights repaired gates | Sequential source-rights and repository suites plus compile, wheel-resource, secret-pattern, diff-whitespace, and port checks | 164 source-rights tests passed in 4.30 seconds; 1,950 repository tests passed in 71.88 seconds; canonical registry and runtime modules are packaged; no secret-pattern hit or port-8000 listener |
| 2026-08-03 | Source-rights repaired candidate frozen | Deterministic SHA-256 over sorted tracked plus untracked non-ignored files with path, mode, length, and content framing | `4c33265f12dec0927fb34a6c344158174ef5bb89f8bda2a2c3363fd873986f04` across 929 files; two fresh neutral approvals required |
| 2026-08-03 | Source-rights repaired independent review C | Fresh read-only exact-hash contract, adversarial, full-suite, registry, gate-ordering, egress, output/storage, and packaging review | APPROVED exact `4c33265...`; 217 focused/adversarial and 1,950 repository tests passed; hash reproduced before and after; no release-correctness blocker |
| 2026-08-03 | Source-rights repaired independent review D | Fresh read-only exact-hash contract, focused, related, full-suite, wheel-install, secret, import, and static review | APPROVED exact `4c33265...`; 164 focused, 394 related, and 1,950 repository tests passed; hash reproduced before and after; no release-correctness blocker |
| 2026-08-03 | Source-rights certification commit | Stage the unchanged twice-approved candidate, check the staged diff, and commit one phase boundary | `3185ccb595cf305f9c69f15ae2730f2d6fa75ee7` (`feat: enforce certified source-rights controls`); worktree clean |
| 2026-08-03 | Certified cloud-platform integration | New `integration/cloud-platform-launch` worktree based on certified OAuth; cherry-pick certified PostgreSQL and source-rights commits; reconcile enforcement order at the shared middleware and internal snapshot projection seams; run the complete repository suite | `0b5a87b05901018ccadde6cf45eccdbd4c8e3e0a`; 4,444 passed in 144.38 seconds; one categorized third-party Authlib deprecation; worktree clean; no old 45-tool server implementation merged |
| 2026-08-03 | Consolidated customer MCP surface | Lock and export the full 45-versus-274 reconciliation; construct a separate hosted facade; preserve exact entitlement, quota, territory, source-rights, approval, result, and audit enforcement; verify real HTTP OAuth and full repository | `802b16cec823f74fc41cab10cb4de9602d56fea7`; 4,459 passed in 164.56 seconds; one categorized third-party Authlib deprecation; 253 grouped actions, 21 internal-only MCP capabilities, profile counts 8/10/20/14; no old server implementation imported and no deployment performed |
| 2026-08-04 | Integrated audit round one RED | Fresh independent authorization, database/isolation, provider/deployment, source-rights, and lifecycle review of integrated HEAD `4167d50` | Critical consentless OAuth code exfiltration; high uncertified hosted deal exposure, hosted SQLite authority, obsolete deployment path, approval/audit/jobs/privacy gaps; medium historical-JV, logout CORS, request exhaustion, and cookie-site findings; no public action performed |
| 2026-08-04 | OAuth/JV audit repair and second review | Tests-first exact-client DCR, explicit consent, exact Origin and Host, CSRF, one-time pending requests, public deal-route removal, streamed body caps, bounded/rate-limited public state, one-per-user browser sessions, identity-wide live JV separation, and retryable consent | Independent reviewer rejected two intermediate candidates, then approved the repaired candidate after adversarial concurrency and cross-workspace checks; 140 focused tests, 4,526 repository tests, 5 connection tests, 10 Operations tests, both builds and audits, compile, pip, secret-pattern, and diff gates passed; committed as `d82e600286682c70639c3130e4f96661d7085a3c` |
| 2026-08-04 | Exact hosted PostgreSQL service-role checkpoint | Add dormant no-login, no-inherit OAuth, provider-ingress, provider-reconciliation, worker, and scheduler roles; require one exact login membership; pin `search_path` before every shared preflight and restore it on pool reset; reject group ownership, direct ACLs, and default ACLs across the current database; extend catalog and clean-restore verification | First reviewer rejected the candidate for late/resettable `search_path`, unverified group-role ACLs, and stale restore inventory. A second reviewer found broader shared-preflight and cross-schema variants. All findings were repaired. Final independent revalidation found no remaining scope finding; 82 PostgreSQL and 4,548 repository tests passed; committed as `46e79a8` |
| 2026-08-01 | Protected backup | SQLite URI read-only integrity and FK checks | `integrity_check=ok`; zero FK violations; file unchanged |
| 2026-08-01 | Hosted persistence archaeology | Enumerate every direct SQLite connector plus JSON, JSONL, and blob authority from HTTP registration to storage | Generic compatibility shim rejected; explicit cloud persistence bundle and domain-port migration required |
| 2026-08-01 | Portal salvage archaeology | Inspect backend `8a44d4c` and frontend `13abbf5` with file-level provenance and route boundaries | No wholesale merge; React rebuild required; exact safe primitives and forbidden customer surfaces mapped |

## Clerk connection-only checkpoint 2026-08-04

The browser surface contains only sign-in, connection status, precise safe
failure guidance, and the OAuth resume action. It has no customer dashboard,
deal, billing, profile, or settings surface. Clerk proves a person, while
MedawarCRE binds only a preprovisioned identity and re-reads membership and
account state before issuing an authorization code. Suspended workspaces,
removed memberships, ambiguous memberships, revoked browser sessions, CSRF
failures, non-S256 challenges, injected authority selectors, invalid redirects,
replayed grants, and stale entitlement state fail closed.

The standalone Clerk credential is intentionally absent. The adapter was
verified through the official SDK boundary using a deterministic provider fake,
and no development secret is required until private staging. The integrated
security audit and fresh post-repair review remain deliberately later in the
founder-approved launch sequence, so this row remains yellow rather than making
an unsupported release claim.

Evidence:

- Worktree `/Users/maxmedawar/LoopnetMCP-cloud-integration`, branch
  `integration/cloud-platform-launch`, base `802b16cec823f74fc41cab10cb4de9602d56fea7`.
- Initial red: the focused identity tests failed to import
  `cre_mcp.platform.connection` before implementation.
- Focused backend gate: 67 passed, followed by a final 58-test OAuth, identity,
  schema, and configuration recheck after bounding OAuth state input. Both runs
  carried one categorized third-party Authlib deprecation.
- Complete repository gate: 4,475 passed in 121.14 seconds with the same
  categorized warning.
- Connection UI: 4 Vitest cases passed; TypeScript and production Vite build
  succeeded; npm audit reported zero vulnerabilities.
- Static gates: source and tests compile, `pip check` is clean, and
  `git diff --check` is clean.
- Real hosted proof: fake verified Clerk session to preprovisioned identity,
  opaque browser session, dynamic client registration, S256 code exchange,
  OAuth token, MCP initialize, and authorized `cre_pipeline.list_searches` call.
- Exact phase commit is recorded by the following program checkpoint because a
  Git commit cannot contain its own content-derived hash.
- Canonical SecondBrain note was not present on the local filesystem or an
  available connector. This ledger is the reopened canonical repository record;
  the missing external note remains an evidence limitation, not a release claim.
- Fresh integrated security review remains scheduled in the founder-approved
  audit step. No public deployment, DNS, billing, or customer data action ran.

## Internal Operations Console checkpoint 2026-08-04

The Operations Console is a separate, internal-only React application. It is
not served by the customer connection origin and contains no customer portal,
deal, pricing, billing, or account-management surface. Clerk proves the staff
identity once; MedawarCRE exchanges that proof for an opaque, short-lived,
HttpOnly, Secure, SameSite=Strict operator cookie. Only token and CSRF digests
are stored. Every request then re-reads the server-owned internal role. Support
is read-only, platform administrators may perform reasoned mutations, and any
identity with a live JV grant is denied even if it also appears in the internal
operator table.

The server exposes bounded workspace lookup and details, membership and grant
state, territory and provider mappings, account state, payload-free provider
quarantine and replay, source-rights state, runtime health, and append-only
audit. Exact Origin and Host checks, credentialed CORS, CSRF, target ownership,
reason codes, and reason text gate mutations. Provider payloads and credentials
are never returned to the browser.

Evidence:

- Worktree `/Users/maxmedawar/LoopnetMCP-cloud-integration`, branch
  `integration/cloud-platform-launch`, base
  `103d08e3d1b2066d13ead198e70d15c109308d9d`.
- Backend authorization and BFF gate: 9 Operations Console tests; related
  operations, admin, OAuth, source-rights, schema, and configuration gate:
  57 passed with one categorized third-party Authlib deprecation.
- Complete repository gate: 4,485 passed in 132.09 seconds with the same
  categorized warning.
- Operations application gate: 7 Vitest cases passed; TypeScript and production
  Vite build succeeded; npm audit reported zero vulnerabilities.
- Dependency provenance: `reicon@1.1.103` is locked with its npm integrity and
  MIT upstream commit in `web/operations/REICON_PROVENANCE.md`.
- Static gates: source and tests compile, `pip check` is clean, and
  `git diff --check` is clean.
- Anti-slop review: the surveyor field-ledger world uses one restrained
  warm-charcoal palette, a custom populated survey plat, a treated section
  index, sharp chamfered geometry, native controls, and specific operational
  data. It has no purple gradient, generic hero, pill clutter, icon tiles,
  decorative glow, card lift, fake controls, hidden entrance content, or hover
  movement. Responsive and reduced-motion rules are present. A real contrast
  defect found during review was repaired: placeholder text now measures
  5.13:1 against its field.
- The in-app Browser runtime reported no available browser instance, so a real
  pointer, keyboard, zoom, and viewport pass was not fabricated. That check is
  retained as a private-staging gate, and this row remains yellow pending the
  integrated audit.
- No public deployment, DNS, billing, or real customer-data action ran.
- The exact phase commit is recorded by the following program checkpoint because
  a Git commit cannot contain its own content-derived hash.

## Integrated audit repair checkpoint 2026-08-04

The first full-system audit is complete but the integrated audit phase remains
red. The OAuth, connection, hosted-route, logout, request-exhaustion, and JV
separation findings are repaired and independently cleared in `d82e600`. Public
registration now maps only an exact server-owned client shape, advertises only
`mcp:tools`, and cannot expose uncertified deal routes. A passive GET cannot
issue a code. The connection screen presents client, destination, workspace,
and access before an exact-origin, exact-host, CSRF-protected POST consumes a
single pending request.

Public request bodies are streamed under pre-append byte caps. Registration is
deduplicated under an immediate transaction. Registration, authorization,
token, revocation, and Clerk exchange have source-scoped process limits, while
private-edge limits remain mandatory. Pending and browser-session stores are
transactionally bounded; browser sessions are one per user. Cross-host browser
cookies deliberately use `SameSite=None; Secure` under the existing Origin,
Host, and CSRF checks. A failed authorization-code write restores the explicit
consent request for retry. Any identity holding a live JV grant in any workspace
is denied internal-admin authority; revoked, future, and expired grants do not
create a permanent block.

Evidence:

- Repair commit: `d82e600286682c70639c3130e4f96661d7085a3c` on
  `integration/cloud-platform-launch`.
- Final focused security gate: 140 passed with one categorized third-party
  Authlib deprecation.
- Final repository gate: 4,526 passed in 204.82 seconds with the same warning.
- Connection application: 5 Vitest cases, production build, and zero npm audit
  findings. Operations application: 10 Vitest cases, production build, and
  zero npm audit findings.
- Source and tests compile; `pip check`, secret-pattern review,
  `git diff --check`, and staged diff checks passed.
- The required embedded browser runtime exposed no `eb_*` tools. No external
  browser substitute was used. DOM interactions were clicked in Vitest; real
  pointer, keyboard, zoom, and viewport proof remains a private-staging gate.
- No deployment, DNS, billing, provider mutation, customer-data access, or
  production action occurred.

The active phase remains hosted persistence correctness. Commit `5bcd5c0`
establishes the first fail-closed boundary: `create_http_app`, `run_server`, the
standalone Starlette factory, and the exported global MCP catalog cannot bind a
public HTTP surface through SQLite, JSON, or JSONL. They require the PostgreSQL
builder, verify pool and schema readiness, and currently reject startup after
that check because the hosted domain repositories are not yet certified. Legacy
persistence can enter HTTP tests only through a test-owned patched builder.

That boundary passed 4,535 repository tests in 194.11 seconds with the one
categorized third-party Authlib deprecation, plus compile, dependency, secret,
and diff checks. A fresh read-only reviewer found and drove closure of bundle
lifecycle leaks, uncertified standalone deal-route mounting, the raw internal
MCP HTTP bypass, and default stdio compatibility, then approved the unchanged
boundary as safe to commit. It does not certify hosted functionality.

Commit `46e79a8` establishes separate dormant OAuth, provider-ingress,
provider-reconciliation, worker, and scheduler database group roles. Migration
`0002` and commit `830c914` activate only the narrow OAuth function boundary.
The other service roles remain dormant. Exact login, object-authority, default
ACL, ownership, catalog, backup, and restore contracts fail closed.

## Reconciled persistence phase records (imported 2026-08-06)

The nine sections below were written on the control branch
`feature/final-launch-control` and were absent from this branch's ledger,
even though every commit they describe is in this branch's own history:
`ccc24a3`, `7be60ef`, `b58dfe0`, `aac18a8`, `fb505a3`, `7a03724`,
`cef768f`, `b0947d7`, and `49adb9e`. They are imported verbatim so the
canonical ledger records the work this branch actually contains.

Nothing else was taken from the control branch. Its dead-hosted-capability
inventory section is deliberately NOT imported: the
`Hosted withholding correction checkpoint 2026-08-05 to 2026-08-06` section
in this file supersedes it, and the control branch's issue ledger and
repository baseline predate the 2026-08-06 JV corrections recorded here.

No code was merged: this change touches `PROGRAM_STATUS.md` and nothing else
from that branch. An earlier draft of this paragraph said "the two branches
share no source file", which is false — they diverge across 149 files under
`src/` because the control branch sits at an older base. The operative claim is
the narrow one, and it is the one stated.

## Atomic PostgreSQL request admission completed 2026-08-04

The integration branch now contains the bounded atomic-admission foundation at
`ccc24a36f93a3dfa0c34f7363228b5c7febd3606`. The exact reviewed candidate was
`3851500191d4a6b7e1aa1fdae153fb033448068af7f92834b8892ec0393c5a7a`
across 1,030 tracked plus untracked non-ignored files.

Migration `0003` provides one atomic admission transaction and one bound final
audit function. It revalidates live OAuth and tenant authority, binds every
effective request and policy input, consumes approval and UTC quota together,
and writes a durable append-only audit. Legacy independently callable approval,
quota, and audit functions are unavailable to the admission role. Only a fresh,
non-replayed allow owns execution.

Two audit rounds found and repaired incomplete invocation binding, padded and
Unicode-whitespace quota drift, replay execution and finalization risk,
incomplete denial and UTC evidence, and invalid-Unicode error escape. The final
shared quota grammar is exactly `^[a-z][a-z0-9_]{0,63}$` with no stripping or
normalization in the repository, OAuth resolver, or SQL. Replayed and finalized
outcomes are rejected before final-audit database access.

Final gates are 42 atomic tests, 144 PostgreSQL 16.14 tests, and 4,610 complete
repository tests, plus compile, native backup and distinct-cluster restore,
readiness, immutable-`0002` upgrade, exact ACL, packaging, secret, diff, and
deterministic hash checks. Catalog fingerprint
`c93a3060257613ef34b13f9bd8d75c6784ff46f6df3e1bde5f5006bc8f13bffd`,
migration checksum
`34c363ef3cb1efad079a21140367d8d1e8dab8ca593784d8c995d9c0e82f4b6a`,
and wheel digest
`237252f4950b00cf0591430f4ad04b863a68154dbb92c9aa62bc66e288d6fd61`
were independently reproduced. Two fresh read-only reviewers approved the
unchanged final candidate with no finding.

The Codex Security preflight still could not inherit `PYTHON`, so the controller
did not repeat that loop and used the required fresh-reviewer fallback. No
interface file changed. No deployment, DNS, billing, paid resource, provider,
customer-data, or production action occurred.

Hosted HTTP remains fail-closed. The exact unfinished phase is hosted request
lifecycle wiring for the one-snapshot authority and atomic admission
repositories, followed by explicit request-scoped platform, provider, search,
deal, privacy, job, document, and truth-asset repositories without local-state
fallback. Private staging, final integrated security approval, readiness packet,
and founder-approved cutover remain red.

## Hosted request lifecycle wiring completed 2026-08-04

The integration branch now connects the certified one-snapshot OAuth authority
and atomic PostgreSQL admission repository to the real hosted MCP middleware.
The exact twice-reviewed candidate was
`15b00840e99dcbb37a6534a8b01b5b2272d2084509a15e21254cd76a8454b3e0`
across 1,033 tracked plus untracked non-ignored files. It was committed as
`7be60ef05d1aa245d4e03d4717460897261ff371` (`feat(hosting): wire atomic
request lifecycle`).

Hosted OAuth resolution, admission, and final recording run off the event loop.
Every call binds workspace, actor, OAuth session, MCP transport session, typed
JSON-RPC request ID, exact capability, and sanitized arguments before atomic
admission. Only a fresh, non-replayed, non-finalized allow owns execution.
Cancellation and failure paths record a bound failed final decision, and a
successful result is not released until result-territory and source-rights
checks pass and its successful final audit is durable. Hosted installation
requires explicit OAuth, admission, and audit authorities, rejects a local
registry, and restores the exact prior middleware and authentication state if
reconfiguration fails.

The first frozen review candidate was rejected for missing stable logical
request identity and incomplete middleware rollback. Both defects were captured
as failing regressions and repaired. The next release review rejected the
repaired candidate because `capability_matrix.json` was absent from the wheel,
which made an isolated install load zero capabilities. Package data now includes
the matrix and a missing matrix fails closed. The rebuilt isolated wheel digest
is `4d3463905ffe0125ea5f70263dfa62a4823f4ccd201c1b7c2c780306d3d339b5`.
It loads 274 capabilities, 253 grouped customer actions, and 21 internal-only
capabilities with customer counts Local 8, National 10, Full Operator 20, and JV
Partner 14.

Final gates are 4,640 complete repository tests and 144 PostgreSQL 16.14 tests,
plus 81 focused lifecycle, surface, and package checks, compile, diff, changed-
file secret, UI-scope, and isolated-wheel checks. Two fresh read-only reviewers
independently reproduced the exact 1,033-file candidate, reran security,
authorization, isolation, replay, database, source-rights, package, surface, and
startup checks, and approved it with no finding.

`PYTHON` remained absent in Codex Security and both fresh reviewer shells. The
controller did not repeat the failed helper loop; every gate used the explicit
approved interpreter at `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`. No
interface file changed. No deployment, DNS, billing, paid resource, provider,
customer-data, or production action occurred.

Hosted HTTP remains intentionally fail-closed because the production persistence
builder still rejects the uncertified customer-domain layer. The exact next
phase is request-scoped PostgreSQL persistence for platform, provider, search,
deal, privacy, job, document, and truth-asset state with no SQLite, JSON, JSONL,
local-blob, dual-write, shadow-write, or fallback path. Private staging, the
final integrated security audit, readiness packet, and founder-approved public
cutover remain red.

## Request-scoped PostgreSQL domain authority completed 2026-08-04

The integration branch now contains the bounded Phase 5A authority substrate at
`b58dfe09da713642813f28ac928967ca408fbf53` (`feat(postgres): bind
request-scoped domain authority`). The exact twice-reviewed repaired candidate
was `073d42f3d4062d8a1421b0956b087f71c451e0d24c2791e26c5dca99c199b4c3`
across 1,037 tracked plus untracked non-ignored files.

Hosted requests now require one aggregate repository bundle containing explicit
platform, provider, search, deal, privacy, job, document, and truth-asset ports.
The bundle is available only inside the admitted request scope. Migration
`0004` binds the exact fresh allow to transaction-local RLS identity and uses a
shared transaction advisory lock to serialize binding against finalization.
Aggregate and document authority use revocable leases, so detached task copies
cannot retain authority after the request scope exits. The source-rights
document check receives the exact injected document repository during execution.

The first frozen candidate, `d33b7c9...`, was rejected by the independent
reviews. The findings were retained as regressions: a detached task could retain
raw aggregate authority, admission binding could race finalization, and the
document repository was not bridged into source-rights execution. The three
focused regressions first failed, then passed after the repair. A reverse-order
PostgreSQL race proves a binder waiting behind an uncommitted final decision
rechecks and rejects that finalized invocation. A separate detached-document
test proves document authority is also revoked.

Final gates are 122 focused lifecycle, OAuth, hosting, source-rights, and
PostgreSQL scope tests, 152 native PostgreSQL 16 tests, and 4,652 complete
repository tests, plus compile, diff, changed-file secret, UI-scope,
deterministic-wheel, and isolated-wheel checks. Catalog fingerprint
`dac27380da49dd88e8cebfeb656a12096e50a364fc9d099af23d6049218c8ab9`
and wheel digest
`f00794a22d6110671829dd7986eae30df5f10a4ba9375dcece8f02870a44d937`
were recorded. The isolated wheel loads 274 capabilities, 253 grouped customer
actions, and 21 internal-only capabilities with visible counts Local 8,
National 10, Full Operator 20, and JV Partner 14. Both fresh read-only reviewers
approved the unchanged final candidate with no remaining finding. The
post-commit lifecycle gate passed 30 tests and the code worktree is clean.

Codex Security still did not inherit `PYTHON` after restart. The controller did
not repeat the failed loop and used the explicit interpreter at
`/Users/maxmedawar/LoopnetMCP/.venv/bin/python` plus two fresh read-only
reviewers. No interface file changed. No deployment, DNS, billing, paid
resource, provider, customer-data, or production action occurred.

This checkpoint does not claim production domain parity. The production builder
still fails closed with `hosted PostgreSQL domain repositories are not yet
certified`. The exact next phase is implementing and certifying the eight real
PostgreSQL domain repositories behind these ports with no SQLite, JSON, JSONL,
local-blob, dual-write, shadow-write, or fallback path. Private staging, the
final integrated security audit, readiness packet, and founder-approved public
cutover remain red.

## PostgreSQL document-attestation read authority completed 2026-08-04

Phase 5B is certified and committed on `integration/cloud-platform-launch` as
`aac18a8ca6100a9f5c4a2beae8cc7ac7afb57c3b` (`feat(postgres): add document
attestation authority`). The exact twice-reviewed candidate was
`78fd0950367edc1d828fb9f0dae76b9797b3c75e35cf85fb5a03bd62e2e6cee7`
across 1,041 tracked plus untracked non-ignored files.

Migration `0005` adds a PostgreSQL document-rights record that stores the
attested URL only as a SHA-256 digest. It binds each record to one workspace,
actor, and exact OAuth session through native foreign keys. The app role has
read-only access under row-level security that requires all three current
request values. A same-workspace session belonging to another actor cannot be
attached to the record and cannot select it.

The repository accepts only the exact active document port, admission, and
server context. It uses the admitted PostgreSQL transaction, returns the
existing source-rights record contract, and fails closed on inactive scope,
database failure, missing or revoked records, expiry, malformed values, URL
digest mismatch, or insufficient purpose. The existing source-rights bridge
calls this repository in hosted execution. It never constructs or falls back
to the trusted-local SQLite authority.

The preserved RED was
`ModuleNotFoundError: No module named 'cre_mcp.postgres.document_attestations'`.
During controller review, a native adversarial test exposed that a workspace-only
session foreign key could attach another actor's session. The final migration
uses a three-column workspace, session, and actor constraint, and the attack is
now rejected by PostgreSQL.

Final evidence is 14 focused document-authority tests, 166 native PostgreSQL 16
tests, and 4,666 complete repository tests. The post-commit document and
source-rights selector passed 36 tests. Compile, dependency, diff, changed-content
secret, package-resource, isolated-wheel, customer-surface, and listener checks
passed. Catalog fingerprint
`e6240265c6f31b5c4cd8e4a7946c354c7a0b87182940db6780bf5694f06d3c50`,
migration digest
`89b5ab0672dc3f3b9cdeb72fa33582ef3506a41b91fd8dd5fb05baf191a5c83e`,
and fixed-epoch wheel digest
`21c714992435d7b05e0bcaa62cd218edf6c3df0f59ade09473e6af9d48af615c`
were recorded. The isolated wheel preserves 274 capabilities, 253 grouped
actions, 21 internal-only capabilities, and visible counts 8/10/20/14.

Two fresh read-only security and release-correctness reviewers independently
reproduced the candidate before and after review and approved it with no
finding. Their independent coverage included exact-session RLS probes, restore,
backup, catalog, source-rights, lifecycle, installed-wheel, surface, and
production fail-closed checks. No interface file changed, so the complete
anti-slop interface audit found no applicable UI defect.

No deployment, DNS, billing, paid resource, provider mutation, customer-data,
or production action occurred. Production hosted startup remains intentionally
blocked until the other seven repositories are certified and wired together.
Internal document approval and revocation also remain out of this slice. The
next bounded implementation phase is PostgreSQL truth-asset persistence for the
document pipeline. Platform, provider, search, deal, privacy, job, staging,
integrated security, readiness, and founder-approved cutover remain red.

## PostgreSQL truth-asset persistence completed 2026-08-04

Phase 5C is certified and committed on `integration/cloud-platform-launch` as
`fb505a39d2d1172938440103d8acf6ff323a69e0` (`feat(postgres): add truth asset
persistence`). The exact twice-reviewed repaired candidate was
`c670742f1c47397f8133071bac2ba551f2d4184502db1c68149c7e74a5285bcb`
across 1,045 tracked plus untracked non-ignored files.

Migration `0006` adds workspace-scoped raw document blobs, structured document
metadata, and claim lineage under PostgreSQL row-level security. PostgreSQL
checks every blob digest, rejects non-finite numeric and bounding-box values,
and cascades workspace deletion through the full blob, document, and claim
graph. The app role can insert raw blobs and read only their workspace and
digest keys. It cannot select raw document content. Backup and restore roles
retain their explicit least-authority contracts.

Hosted document ingestion now requires the exact active truth-asset repository,
admission, and workspace, actor, and OAuth-session binding. A detached task
cannot regain a trusted-local store after the request lease is revoked. Saves
are transactional and idempotent, mutable document metadata and claims are
replaced together, malformed stored values fail closed, and cancellation cannot
escape while a PostgreSQL worker remains active.

External document URLs still require attestation before retrieval and again at
the socket boundary. Retrieval pins the validated public DNS answer. It uses a
synchronous curl receipt callback with no producer queue, aborts with
`CURL_WRITEFUNC_ERROR` before an over-limit chunk enters retained body storage,
and does not let cancellation unwind the request or attestation lease while the
network worker remains active. Hosted local paths remain denied. Trusted local
stdio preserves its existing SQLite and filesystem behavior.

The preserved implementation RED was `ModuleNotFoundError: No module named
'cre_mcp.postgres.truth_assets'`. Initial independent reviews then found valid
detached fallback, unbounded URL buffering, worker cancellation, metadata
replacement, IPv6 canonicalization, workspace teardown, and non-finite numeric
gaps. Each finding was captured by a failing regression before repair. A second
security review found the intermediate curl stream queue and URL cancellation
gaps; receipt-callback and blocked-worker regressions failed first and then
passed after the final repair.

Final evidence is 45 focused source-rights and truth-asset tests, 185 native
PostgreSQL 16 tests, and 4,689 complete repository tests. The post-commit
focused gate passed 45 tests. Compile, dependency, diff, changed-file secret,
package-resource, isolated-wheel, production fail-closed, customer-surface, and
listener checks passed. Catalog fingerprint
`0a0dcb2208e81bea14780d2c386b077f8c35f139a3d1c6d83a69ee2f40ac98ef`,
migration digest
`3fbe32d39e7fde4347b9205eb831781158554a1f94b028841dcfda375ebd5ebd`,
and fixed-epoch wheel digest
`57d506b4963072926e08ee9366fd44efc57116ca5f9c04da7c66436a5fe23884`
were recorded. The isolated wheel contains the capability matrix, migration
`0006`, restore privileges, and the truth-asset repository. It preserves 274
capabilities, 253 grouped actions, 21 internal-only capabilities, and visible
counts Local 8, National 10, Full Operator 20, and JV Partner 14.

Two fresh read-only security and release-correctness reviewers independently
reproduced the candidate before and after review and approved it with no
finding. They verified receipt-time URL bounds, cancellation containment,
admission binding, RLS and ACL isolation, raw-content denial, transactions,
teardown, local parity, backup and restore, packaging, surfaces, and production
fail-closed behavior. PID 65710 remained untouched in
`/Users/maxmedawar/LoopnetMCP`, listening only on `127.0.0.1:8000`.

No interface file changed, so the complete anti-slop interface audit found no
applicable UI defect. No deployment, DNS, billing, paid resource, provider
mutation, customer-data, or production action occurred. Production hosted
startup remains intentionally blocked until the six remaining platform,
provider, search, deal, privacy, and job repositories are certified and wired
together. The exact next bounded slice is PostgreSQL platform-domain
persistence. Private staging, integrated security, readiness, and
founder-approved cutover remain red.

## PostgreSQL platform-context persistence completed 2026-08-04

Phase 5D is certified and committed on `integration/cloud-platform-launch` as
`7a03724e7ec39dd6d08bfe2d7ebc739bcbb898b6` (`feat(postgres): add platform
context persistence`). The exact repaired candidate was
`8e4c480c90b956f96d767b80c62e844a0c78b86ab394a99b15e47af6a2dba4bc`
across 1,048 tracked plus untracked non-ignored files.

The new read-only PostgreSQL port returns one current actor and workspace
context snapshot: actor, workspace, active membership, workspace account,
optional plan, and deterministically ordered territories. It accepts only its
exact fresh admission and active platform port, with matching workspace, actor,
and OAuth session. Every database access uses the admitted transaction and
transaction-local RLS. Hosted execution cannot construct or recover the local
SQLite repository, while trusted local stdio retains existing behavior.

The implementation began RED because
`cre_mcp.postgres.platform_context` did not exist. The first frozen candidate
`2306bbbf...` passed its test gates but both independent reviewers reproduced a
release-blocking integrity race: separate READ COMMITTED identity and territory
queries could return a mixed-time combination that never existed. A permanent
concurrent-commit regression failed with the old workspace name plus the new
territory set. The repair performs the complete read in one ordered SQL
statement, validates identical repeated identity projections, and rejects
malformed or non-ASCII state codes through the fixed unavailable error.

Final evidence is 15 focused Phase 5D tests, 200 native PostgreSQL 16 tests, and
4,704 complete repository tests. The post-commit focused gate passed 15 tests.
Compile, dependency, diff, changed-file secret, deterministic wheel, unpacked
wheel, production fail-closed, customer-surface, and listener checks passed.
The existing catalog fingerprint remains
`0a0dcb2208e81bea14780d2c386b077f8c35f139a3d1c6d83a69ee2f40ac98ef`.
The two fixed-epoch wheels were byte-identical at
`8b0aca23214a5f3ff4df57ae8fbb38490fc7b335f64a56d94e347dcd131a398f`.
The unpacked wheel contains the capability matrix, platform-context repository,
migration `0006`, restore privileges, and source-rights registry. It preserves
274 capabilities, 253 grouped actions, 21 internal-only capabilities, and
customer surfaces Local 8, National 10, Full Operator 20, and JV Partner 14.

Both first reviewers rejected only the mixed-time snapshot. After the repair,
two new read-only security and release-correctness reviewers independently
reproduced the exact final candidate before and after review and approved it
with no finding. They verified admission and lease binding, RLS and ACL
isolation, one-statement snapshot coherence, malformed-row fail-closure,
cancellation, no local fallback, source-rights non-regression, packaging, and
production fail-closed behavior.

Codex Security still did not inherit the requested `PYTHON` variable after the
restart, so the controller did not repeat that failed loop. Every Python gate
used `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`, and the authorized fresh
read-only reviewer fallback supplied the independent reviews. PID 65710 remained
untouched in `/Users/maxmedawar/LoopnetMCP`, listening only on
`127.0.0.1:8000`.

No interface file changed, so the complete anti-slop interface audit found no
applicable UI defect. No deployment, DNS, billing, paid resource, provider
mutation, customer-data, or production action occurred. Hosted production
remains intentionally fail closed. Five domain ports remain: provider, search,
deal, privacy, and job. The exact next bounded slice is PostgreSQL provider-domain
persistence. Private staging, integrated security, the readiness packet, and
founder-approved public cutover remain red.

## PostgreSQL provider-entitlement persistence completed 2026-08-04

Phase 5E is certified and committed on `integration/cloud-platform-launch` as
`cef768f26712212113f329019b6886ea49aec990` (`feat(postgres): add provider
entitlement persistence`). The exact repaired candidate was
`d8ebf294c7ef55e8321fded24df18850c5f4ee2fe1d5cbbee3c28d88100712dc`
across 1,051 tracked plus untracked non-ignored files.

The new request-scoped, read-only PostgreSQL port returns a safe provider
entitlement projection for the admitted actor and workspace: subscription state
and actor- or workspace-visible access grants in deterministic order. It does
not return external subscription, customer, grant, or account identifiers,
provider payloads, provider events, or provider attempts. Webhook ingress,
reconciliation, billing mutation, and provider-side writes remain separate and
out of scope.

The repository requires the exact admission object, exact active aggregate
`provider` lease, active untrusted request context, and matching workspace,
actor, and OAuth session. One SQL statement reads through the admitted
transaction and transaction-local RLS using `current_workspace_id()` and
`current_actor_user_id()`. Existing column grants and RLS policies enforce the
projection, so no migration was needed. Hosted failures use the fixed message
`provider persistence unavailable`; trusted local behavior remains unchanged.

The implementation began RED because
`cre_mcp.postgres.provider_entitlements` did not exist. The first frozen
candidate `c1344c3c...` passed its controller gates, but the first security
review rejected two medium release-correctness defects: an in-flight provider
worker result could return after aggregate lease revocation, and hosted
repository binding ran before `use_context(ctx)`, allowing a binder to construct
the local SQLite `EntitlementStore`.

Permanent regressions first reproduced six failures across provider,
platform-context, and truth-asset result-after-revocation paths plus hosted
provider-store construction. The repair rechecks exact active scope after
worker completion, including the adjacent platform and truth repositories;
truth writes also recheck inside the transaction before commit. Hosted binding
now runs under the exact request context, and `EntitlementStore` construction is
denied under an active hosted repository lease or any untrusted context. An
over-broad attempt to deny the legacy deal store during binding broke explicit
test-owned compatibility adapters and was fully reverted before freeze.

Final evidence is 299 focused and adjacent tests, 219 native PostgreSQL 16
tests, and 4,724 complete repository tests. The provider repository file passed
15 tests, and the post-commit lifecycle selector passed 20 tests. Compile,
dependency, diff, changed-file secret, dash, deterministic-wheel, unpacked-wheel,
production fail-closed, surface, migration, and listener checks passed. The
catalog fingerprint remains
`0a0dcb2208e81bea14780d2c386b077f8c35f139a3d1c6d83a69ee2f40ac98ef`.
The controller's fixed-epoch wheels were byte-identical at
`fa2288f55494be7d06062a4d87d0659293f02f3860def8d774c7b68ca579be8c`.
The unpacked wheel imports the provider repository, retains required access,
source-rights, and SQL assets, and preserves 274 capabilities, 253 grouped
actions, 21 internal-only capabilities, and customer surfaces Local 8,
National 10, Full Operator 20, and JV Partner 14.

Two fresh read-only security and release-correctness reviewers independently
reproduced the exact final candidate before and after review and approved it
with no finding. They verified the two prior repairs, admission and lifecycle
binding, RLS and ACL isolation, fixed errors, cancellation containment,
data minimization, no local fallback, source-rights non-regression, packaging,
test-only compatibility, and production fail-closed behavior.

Codex Security still did not inherit the requested `PYTHON` variable after the
restart, so the controller did not repeat that failed loop. Every Python gate
used `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`, and the authorized fresh
read-only reviewer fallback supplied equivalent independent coverage. PID 65710
remained untouched in `/Users/maxmedawar/LoopnetMCP`, listening only on
`127.0.0.1:8000`.

No interface file changed, so the complete anti-slop interface audit found no
applicable UI defect. No deployment, DNS, billing, paid resource, provider
mutation, customer-data, or production action occurred. Hosted production
remains intentionally fail closed. Four domain ports remain: search, deal,
privacy, and job. The exact next bounded slice is PostgreSQL search-domain
persistence. Private staging, integrated security, the readiness packet, and
founder-approved public cutover remain red.

## PostgreSQL search persistence completed 2026-08-05

Phase 5F is certified and committed on `integration/cloud-platform-launch` as
`b0947d724f734cebadc16ebacb27917de90acca6` (`feat(postgres): add search
persistence`). The exact repaired candidate was
`fde8de7f8019443a32a0253e4ec831f8df45fb17d459b4236f91f05eae0d3a8d`
across 1,055 tracked plus untracked non-ignored files.

The new request-scoped PostgreSQL port persists actor-private saved searches
and their seen-result ledger for the admitted workspace. It preserves opaque
UUID hosted identifiers and trusted-local integer compatibility, requires
exact workspace public-ID and actor projection matches, and keeps searches
private to the actor even inside JV workspaces. PostgreSQL application roles
receive only `SELECT` and `INSERT` on these relations. `claim_unseen` performs
one atomic claim so concurrent alert checks cannot release the same deal twice.

The implementation began RED because `cre_mcp.postgres.searches` did not
exist. The first frozen candidate was rejected by independent review for three
valid blockers: detached or revoked hosted scope could fall back to local
SQLite, projected workspace identity was parsed but not matched to admission,
and `check_alerts()` could claim an earlier search before a later stale
territory error discarded all output, permanently suppressing the deal.

Permanent regressions reproduced each defect before repair. Hosted search
construction now rejects every untrusted fallback and requires an active
search lease; repository operations bind and recheck the exact admitted actor,
workspace, OAuth session, and public workspace projection; and alert checking
completes territory preflight for every selected search before provider or
claim side effects. Runtime failure of one already-preflighted search remains
isolated from the others.

Final evidence is 27 search-repository tests, 246 native PostgreSQL 16 tests,
and 4,752 complete repository tests, with one categorized third-party Authlib
deprecation warning. The surface selection passed 15 tests and preserved
customer-visible tool counts Local 8, National 10, Full Operator 20, and JV
Partner 14. Compile, dependency, diff, changed-content credential, wheel,
migration, catalog, production fail-closed, and listener checks passed. The
catalog fingerprint is
`15215ce6ae3eabe2c8799eeef258a7d1cf896aa9e5a6d66d94f5cb4e163b6323`;
migration `0007_search_persistence.sql` is
`47eb926512f49e355e91f7f098a17b4f3b4831d35c4fda97b4a6f1b742eccffe`;
and the inspected wheel is
`3cde98ae2b79b3eac8e6f000d1a0b0d2a2b936b051b43be7799f62d9c6765919`.

Two fresh read-only security and release-correctness reviewers independently
reproduced the exact repaired candidate before and after review and approved it
unchanged with no release blocker. They covered repository authorization,
isolation, lifecycle, database and ACL behavior, source-rights interactions,
alert side-effect ordering, packaging, compatibility, and deployment
correctness.

Codex Security still did not inherit the requested `PYTHON` variable after the
restart, so the controller did not repeat the failed loop. Every Python gate
used `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`, and the authorized fresh
read-only reviewer fallback supplied equivalent independent coverage. PID
65710 remained untouched in `/Users/maxmedawar/LoopnetMCP`, listening only on
`127.0.0.1:8000`.

No interface file changed, so the complete anti-slop interface audit found no
applicable UI defect. No deployment, DNS, billing, paid resource, provider
mutation, customer-data, or production action occurred. Hosted production
remains intentionally fail closed. Three domain ports remain: deal, privacy,
and job. The exact next bounded slice is Phase 5G PostgreSQL deal persistence.
Private staging, integrated security, the readiness packet, and
founder-approved public cutover remain red.

## PostgreSQL deal persistence completed 2026-08-05

Phase 5G is certified and committed on `integration/cloud-platform-launch` as
`49adb9e` (`feat(postgres): add deal persistence`). The exact repaired
candidate was
`1baea746e8a62fc6aef27a974c3ac9278fcd2522a8fa4825bd2902198b2b70f8`
across 1,059 tracked plus untracked non-ignored files.

The new request-scoped PostgreSQL port persists the complete non-search
`DealStore` surface for the admitted workspace. Deals are collaborative
workspace state rather than actor-owned rows, so migration `0008` converts
`owner_user_id` into `created_by_user_id`/`updated_by_user_id` attribution and
narrows the application role to exact column-level ACLs across eleven
relations. Hosted investor, commitment, exchange, deal-event and IC identifiers
are opaque UUID strings while trusted-local integers are preserved. Diligence
and operating workflows use capability-level composite methods that refresh the
sanitized deal and replace the complete child plan in one admitted transaction,
and replacement identification serializes on the exchange row while enforcing
the day-45 and 3-property/200% rules before mutation.

This phase took four review rounds and rejected three candidates. Nine valid
defects were found and repaired, each reproduced as a failing regression first.
Three of them were defects in earlier repairs, which is the reason the round
count is recorded rather than smoothed over:

- the restore preflight reported an unsupported PostgreSQL target as a
  smoke-identity failure, masking the version error;
- `build_noi_bridge` and `deal_truth_report` broke trusted-local behaviour for
  a deal_id with ingested claims that was never saved, and for a saved listing
  with the blank address the Crexi mapper emits by design;
- `list_deal_documents` let a `jv_partner` confirm the existence of, and read
  the document origin for, a deal outside its territory;
- `trace_input_lineage` leaked the same way and is now withheld from
  `jv_partner`; it was found by writing the first leak's regression as a
  structural invariant rather than a single-case assertion;
- rows predating `0008` stayed visible but became permanently unstageable and
  unassignable, and one undecodable listing denied `list_deals` for an entire
  workspace;
- `title` and `asking_price` reached SQL CHECK constraints unvalidated, and a
  provider price at or above 1e17 overflowed `numeric(19, 2)` and permanently
  poisoned every hosted write for that listing;
- five `_METHOD_TOOLS` entries granted a method to a capability no production
  call graph invokes;
- multi-statement reads took a fresh snapshot per statement, contradicting the
  written transaction contract;
- `list_deal_documents` held `get_deal` authority with no matching projection
  branch, so the capability was denied on every `jv_partner` call including
  in-territory deals in its own workspace.

The last defect is the clearest lesson of the phase: it was introduced by the
repair for the first territory leak, it passed a full green suite, and it was
invisible to the new tests because they patched a local `DealStore` that always
returns a listing. Three separate rounds produced a defect that a fully green
suite concealed, so suite-green was not treated as evidence of correctness. The
final correctness reviewer mutation-tested all nine new pins plus four of its
own choosing and confirmed every one fails when the behaviour it claims to pin
is deleted.

Final evidence is 274 native PostgreSQL 16 tests and 4,785 complete repository
tests, with one categorized third-party Authlib deprecation warning. Compile,
dependency, diff, changed-content credential, wheel, migration, catalog,
production fail-closed, and listener checks passed.
`build_postgres_hosted_persistence` still raises `HostedPersistenceUnavailable`,
so hosted production remains intentionally fail closed. The catalog fingerprint
is `eae1d0da2d249c97b3007539d7935ec58e06bef45c00afa4b93f4f597f9c857d`;
migration `0008_deal_persistence.sql` is
`8a7440a3025af9f4cc3e68015476b0fc7135e7677b420afcb982adb9445f76a8`;
`0007_search_persistence.sql` is unchanged at
`47eb926512f49e355e91f7f098a17b4f3b4831d35c4fda97b4a6f1b742eccffe`;
and the inspected wheel is
`cb55bc67ffe2076290225b355abe925fadc2ab528677e9ac1d07669da2b76afb`.

One locked surface count changed under review. JV Partner drops from 14 visible
grouped tools and 170 capabilities to 12 and 165, withholding
`unassigned_deals`, `exchange_status`, `list_investors`, `ic_scorecard`, and
`trace_input_lineage`. Those five are locationless or unmodelled aggregate
surfaces: they return deal, investor, exchange, or claim identities with no
property location a territory policy can inspect, so a territory-limited JV
grant would learn of deals outside its territory. `list_deal_documents` was
bound rather than withheld, matching its two `deal_id` siblings. Every
remaining JV-visible deal capability carries a declared property reference and
a result territory contract, and a locked invariant now asserts that every
territory-limited capability taking a `deal_id` and reaching a certified hosted
port declares one. Local 8, National 10, and Full Operator 20 are unchanged,
all 274 internal capabilities are retained, and 253 exact actions remain
grouped.

Two fresh read-only reviewers independently reproduced the exact candidate
before and after review and approved it unchanged with no release blocker. They
covered projection-versus-authority pairing, territory enumeration by
independent call-graph analysis, method authority in both directions, the
numeric bounding and its effect on the 1031 rules, source-rights re-derivation,
transaction isolation, RLS and column ACLs, migration backfill safety,
atomicity, statutory boundaries, trusted-local parity, packaging, and recovery.

One finding is deliberately carried rather than repaired. Both reviewers
independently reproduced an unpoliced per-deal existence and content oracle
reachable by `jv_partner` through `counterparty_track_record`, `who_to_call`,
and `counterparty_dossier`, which read a workspace-scoped SQLite `LedgerStore`
that is not fail closed in hosted execution. It is present at the base commit
`b0947d7`, never touches the deal port this phase certifies, and falls under
the phase's explicit non-scope for separate local stores. It is recorded above
as an open red hosted-launch blocker. It also makes one sentence of the Phase 5G
contract inaccurate: separate file-backed modules do not all remain fail closed
in hosted execution, and that text must be corrected in the next slice.

Related, and recorded so it is not mistaken for coverage: this phase's
tightening of `DealStore.__init__` closes `counterparty_dossier`,
`meeting_briefing`, `overnight_changes`, `who_to_call`, `data_room_index`,
`transaction_critical_path`, and `closing_runway` for untrusted contexts. They
remain entitled and counted in the 165 but are denied on every hosted call, and
the round-seven store-workflow tests now bind a local `DealStore` as the hosted
deal port, so they can no longer be cited as evidence those capabilities work
in hosted execution.

No interface file changed, so the complete anti-slop interface audit found no
applicable UI defect. No deployment, DNS, billing, paid resource, provider
mutation, customer-data, or production action occurred. Nothing was pushed. Two
domain ports remain: privacy and job. The exact next bounded slice is Phase 5H
PostgreSQL privacy-domain persistence. Private staging, integrated security,
the readiness packet, and founder-approved public cutover remain red.

## One-snapshot PostgreSQL OAuth authority checkpoint 2026-08-04

Commit `830c91463ea5335f687b088f7bbb9f577e9aec03` adds migration
`0002_hosted_lifecycle_and_oauth_authority.sql`, a dedicated OAuth connection
pool, and one fixed statement that derives token, client, user, workspace,
membership, account, grant, plan, quota, territory, staff, and identity-wide JV
authority from one PostgreSQL snapshot. Raw bearer tokens are hashed before the
database call. The OAuth role has only schema usage and exact function execute
authority. Pool setup, checkout, reset, backup, restore, and catalog checks
reject authority drift.

The 1,024-file reviewed candidate was
`2bf5a43d0367cc087a85ae99f754e6c7dfd4d20a432dc9035f70b04a24b2fac5`.
Migration `0002` is
`3058382c0943220e19bfa6b7754cda09fe823e478dc86397f8283047cc309b8f`;
the PostgreSQL 16 catalog fingerprint is
`40f025fcf85251cf340428438c5e5ebf3b20462ea8ee59c5ac882f9a94e47eef`.
The final wheel is
`324f777c57694962146c18adfe919a1f8354d4dda8eaafe0b2af549447c3974d`.

Evidence:

- PostgreSQL 16.14: 102 passed. Complete repository: 4,568 passed in 170.04
  seconds. The only warning is the known third-party FastMCP/Authlib
  deprecation.
- Compile, dependency, server import, packaged migration, secret review, and
  diff checks passed.
- Local Docker build `medawarcre-oauth-review:local` succeeded as image
  `sha256:84872a140166765718c53ba32251996b54b609605d3ee28658f82ddd36b04e00`.
  It runs as `cremcp`; server, OpenPyXL 3.1.5, and PDFPlumber 0.11.10 imports
  passed inside the image.
- Two fresh read-only reviewers independently reproduced the candidate hash,
  migration, catalog, and wheel evidence and returned hash-stable approval.
- `printenv PYTHON` was still empty after the Codex restart. The controller did
  not repeat the failed Security-helper loop and used the required fresh
  read-only reviewer fallback.
- No interface file changed. The complete anti-slop recheck found no applicable
  UI defect.
- No deployment, DNS, billing, paid resource, provider mutation, customer-data
  access, or production action occurred.

This is not hosted-functionality approval. The exact unfinished checkpoint is
request-scoped domain repositories plus atomic approval, quota, and durable
decision audit. Jobs, privacy, provider service paths, container rollout,
migration operations, recovery, private staging, the final integrated audit,
readiness packet, and founder-approved cutover remain red.

## Hosted withholding correction checkpoint 2026-08-05 to 2026-08-06

Fifteen capabilities were entitled, counted, and advertised by the hosted
grouped tools while every hosted call failed. They are now withheld from the
hosted surface and denied on a direct call. The contract is
`docs/launch/HOSTED_WITHHOLDING_CONTRACT.md`.

**Two successive inventories were incomplete.** The recorded seven were
`counterparty_dossier`, `meeting_briefing`, `who_to_call`, `overnight_changes`,
`data_room_index`, `transaction_critical_path`, and `closing_runway`. Review
round one rejected that candidate: seven more are dead for the same reason and
were still advertised — `init_data_room`, `update_data_room_item`,
`init_transaction_plan`, `morning_queue`, `flag_unattended`,
`record_listing_snapshot`, and `stale_listing_signals`. Review round two
rejected the resulting fourteen: the derivation behind it did not resolve
package `__init__.py` re-exports and so missed a fifteenth,
`closing_day_runbook`, which reaches the same `DependencyStore` through
`closing.command_center` and the `cre_mcp.dataroom` re-export.

How the set was established and what the suite guards are two different things,
and earlier drafts conflated them. **Established:** independent reviewers in
successive rounds bound a real `HostedRequestRepositories` — under which a
direct `DealStore(...)` raises while `get_deal_store()` returns the port — and
executed every grouped action. Each such repositories-bound run reproduced
exactly these fifteen, with no sixteenth and none of the fifteen alive; one also
re-seeded on `TruthStore`, `PlatformRepository`, and `EntitlementStore` and
found no additional dead grouped action. Which rounds those were is not restated
here: the review-history table below is the record, and earlier drafts of this
paragraph twice attributed the work to the wrong rounds. **Guarded:** a static AST derivation asserts
set equality with `HOSTED_WITHHELD_CAPABILITIES`, turning red in either
direction on any source change that moves it. It is a tripwire, not a proof.
The earlier claim that the set had been "derived two independent ways"
overstated the evidence and was withdrawn; the claim that the static pin
establishes completeness is likewise withdrawn.

The criterion is routing, not a store class. `DealStore.__init__` refuses every
hosted or untrusted context, so a capability is alive on hosted when it goes
through `get_deal_store`/`get_search_store` (which return the certified hosted
port) and dead when it constructs the store directly. An earlier draft
attributed `transaction_critical_path` and `closing_runway` to `DataRoomStore`;
they use `DependencyStore`, and because the reversal condition had been keyed to
the store name, that error could have re-advertised two still-dead actions. The
reversal condition is now keyed to the capability routing through a certified
port.

The original attempt was reverted because it withheld by emptying
`allowed_profiles`, which breaks the matrix well-formedness invariant and the
trusted local capability. This correction withholds at the hosted surface
instead, so entitlement, grouped classification, the locked counts, and trusted
local stdio are all untouched, and no per-capability internal-only mechanism was
needed.

Evidence:

- Worktree `/Users/maxmedawar/LoopnetMCP-cloud-integration`, branch
  `integration/cloud-platform-launch`, base `cd0f335`.
- Initial red: `ImportError: cannot import name 'HOSTED_WITHHELD_CAPABILITIES'
  from 'cre_mcp.surface.catalog'` before implementation.
- Files changed, ten in total: `src/cre_mcp/surface/catalog.py` and
  `src/cre_mcp/surface/server.py`; the JV count in
  `tests/surface/test_catalog.py` and `tests/surface/test_server.py`; new
  `tests/surface/test_hosted_withholding.py` and new
  `docs/launch/HOSTED_WITHHOLDING_CONTRACT.md`; and dated corrections to this
  ledger, `docs/launch/PHASE_5G_DEAL_PERSISTENCE_CONTRACT.md`,
  `.claude/specs/consolidated-customer-mcp-surface.md`, and
  `.claude/specs/oauth-launch-certification-phase-1.md`.
- Focused gate: 98 surface tests passed with 4 skips, the skips being the
  withheld capabilities not entitled to `jv_partner`. Local behaviour is
  unchanged: 169 passed from `pytest tests/relations tests/command tests/dataroom
  tests/closing tests/leaseops
  tests/access/test_territory_round7_store_workflows.py` — 83 from the five
  directories and 86 from that one territory file.
- Complete repository gate: 4,868 passed and 4 skipped, up from the 4,785
  baseline by exactly the new pins, with one categorized third-party Authlib
  deprecation and no regression. Wall time varies by run and machine load
  (187-236 seconds observed) and is not an evidential figure. The four skips
  are the withheld capabilities not entitled to `jv_partner`.
- Mutation evidence: emptying `HOSTED_WITHHELD_CAPABILITIES` entirely fails 62
  of the 83 pins in the withholding suite, including every parametrization of
  the end-to-end denial pin. Targeted mutations each fail their own pin —
  advertising withheld actions, resolving withheld actions, dropping each of
  the three import-time guards, and ignoring withholding in `visible_names`.
  The set-equality drift pin fails in BOTH directions: removing
  `closing_day_runbook` from the withheld map fails it, and adding the live,
  accessor-routed `unassigned_deals` to the map also fails it. That two-way failure is what guards against withholding a
  working capability; the runtime probe cannot, and is no longer claimed to.
- Surface gates: 274 internal capabilities, 253 grouped actions, 21
  internal-only, 15 hosted-withheld, 238 hosted-reachable, customer grouped-tool
  counts Local 8, National 10, Full Operator 20, and JV Partner 11, JV entitled
  capabilities 164, catalog fingerprint `84578ae71567ed18...` unchanged, and no
  withheld action reachable through any hosted path.
- **The JV grouped-tool count moves from 12 to 11 by founder decision on
  2026-08-06.** All four of `cre_close`'s JV-entitled actions are dead, so
  `cre_close` has never worked for `jv_partner` and the locked 12 was already
  overstating the working JV surface. Offered the choice between publishing 11
  working tools and holding 12 by continuing to advertise a capability that
  fails on every call, the founder chose 11. Local, National, and Full Operator
  counts are unchanged. The release-locked assertions in
  `tests/surface/test_catalog.py`, `tests/surface/test_server.py`, and the
  withholding suite were updated to 11 to match this decision.
- Static and packaging gates: source and tests compile, `git diff --check` is
  clean, the changed-content credential scan is clean, no port-8000 listener,
  and an isolated wheel builds and packages the capability matrix,
  the source-rights registry, the surface catalog, and all eight numbered
  migrations plus `restore_privileges.sql`. No wheel digest is recorded: the
  build is not byte-reproducible — the digest moved across three review rounds
  with no packaged source byte changed — so a digest here would assert a
  content property it does not have.
- Connection UI recheck: 5 Vitest cases passed, unchanged by this correction.
- Three fail-closed guards were added so a careless future edit fails at import:
  withholding a non-grouped capability is rejected, withholding a legacy tool id
  is rejected because the legacy reconciliation would still report it reachable,
  and withholding that would empty a grouped tool is rejected. A set-equality
  DRIFT pin against the statically derived set replaced a weaker per-module
  guard that review showed was evaded by aliased imports, attribute calls, and
  any module named `store.py`. That pin does NOT establish completeness — see
  the framing above; it turns red in either direction when a source change
  moves the derived set, which is a prompt to look, not a proof.
- No deployment, DNS, billing, provider mutation, or customer-data action
  occurred.

Review history. Every round in the table below was rejected on correctness, and
each found a real defect the previous round missed. No round after round two
found a defect in shipped `src/` behaviour: from round three onward the findings
were in this ledger, in the contract, or in the claims made for the tests —
though rounds four and five also drove repairs to the test-side derivation
itself. Counts are deliberately not restated in this sentence; the table is the
record, and restating them is what failed review in rounds seven and eight:

| Round | Correctness | Security | Rejected for |
| --- | --- | --- | --- |
| 1 | REJECTED | APPROVED | Wrong store named for two capabilities while the reversal condition keyed on that name; the seven-capability set was incomplete; the end-to-end denial pin was vacuous because the fixture internal server was empty |
| 2 | REJECTED | APPROVED | A fifteenth capability, `closing_day_runbook`, missed because the derivation did not resolve package `__init__` re-exports; the ledger asserted a completeness the evidence did not support; the "genuinely dead" pin could not distinguish dead from alive |
| 3 | REJECTED | APPROVED | The normative scope line of this contract and the pin file's module docstring still said "fourteen" while fifteen were withheld |
| 4 | REJECTED | APPROVED | The authoritative surface spec still release-locked JV Partner at 14; the internal-only rationale ("the affected modules also hold working capabilities") is false for `cre_mcp.command.tools` and `cre_mcp.dataroom.tools`, where every capability is withheld; the blind-spot disclosure was incomplete and mis-located, missing attribute-qualified calls at every propagation step |
| 5 | REJECTED | REJECTED (process) | The completeness pin's own docstring said a class is dead only via `__init__`, the opposite of the round-5 code, and the contract and ledger repeated it; the residual-limitation disclosure was again incomplete, missing subclassing, module-level name binding, module-scope construction, and the over-marking direction entirely |
| 6 | REJECTED | APPROVED | The evidence list reinstated the completeness claim the same section had withdrawn 72 lines earlier; the OAuth-certification JV amendment could not close arithmetically (170 − 1 ≠ 164) and erased five Phase 5G withholdings |
| 7 | REJECTED | APPROVED | The review-history summary line said "three rejected rounds … two of the three in the verification" while the table beneath it recorded six rejections, four of them verification or ledger defects |
| 8 | REJECTED | REJECTED | The summary sentence restated a count that drifted from the table again, one round after being fixed for exactly that; and the round-attribution self-correction contradicted the contract and this file, leaving three passages disagreeing on the runtime evidence |
| 9 | pending | pending | — |

Round five's security reviewer rejected on process, not on the code: the working
tree was edited while that review was in flight, so its start and end hashes
differed and no verdict could attach to a candidate. That was an operator error
— the correctness blockers were repaired without first waiting for the security
review to return. Its findings against the bytes it did read were folded in
anyway: it confirmed `src/` was comment-only versus the prior approved state,
that the reworded internal-only rationale is arithmetically right, that the
derivation terminates in three passes with bounded recursion and no side
effects, and that 16,275 hostile input shapes produced zero resolutions of a
withheld capability. It also demonstrated three further static evasions and a
silent alias-depth truncation, both now addressed: the truncation raises instead
of returning a partial resolution.

Round six was rejected for a claim that had been withdrawn elsewhere in the
same document and for an amendment whose arithmetic did not close. The JV
entitlement history was then verified directly from the capability matrix at
each commit: `88e3082` 170, `49adb9e` 165 (five withheld — `exchange_status`,
`ic_scorecard`, `list_investors`, `trace_input_lineage`, `unassigned_deals`),
`039cacf` 164 (one withheld — `counterparty_track_record`).

Round five stopped patching the disclosure and changed what is claimed: the
static derivation is now described as a drift tripwire that is unsound in both
directions, with completeness attributed to the runtime evidence instead. Three
rounds of incomplete blind-spot enumerations preceded that reframing.

Round four also drove a code repair rather than a disclosure: the completeness
derivation now resolves attribute calls qualified by a module alias and walks
every method of a class, closing three evasions demonstrated by mutation — an
attribute construction making a live capability dead, a module-alias call to a
dead function, and a store constructed lazily outside `__init__`. The derived
set is unchanged at fifteen.

Round-three security additionally verified the change is purely restrictive by
rebuilding the catalog at zero, fourteen, and fifteen withheld and diffing every
observable surface: no profile gains a tool, an action, or a resolvable pair,
and roughly 26,800 hostile input shapes produced zero resolutions of a withheld
capability. Reviewers in that round also reproduced the set of fifteen by
methods stronger than the shipped derivation and confirmed no sixteenth and no
wrongly-withheld live capability; the repositories-bound method is described
once above rather than re-attributed per round.

Known limitations, disclosed rather than implied away and recorded as
known-so-far rather than exhaustive. The static drift detector resolves import
aliases, package `__init__` re-exports, attribute calls qualified by a module
alias, and every method of a class — so a class is marked dead when any method
reaches a dead callee, not only `__init__`. It can MISS a `DealStore` subclass,
the class bound to a module-level name and called through it, a construction at
module scope, a call whose qualifier is not a known module alias when the
attribute name is not bound in that module, and any callee that is itself a
`Call` or `Subscript` node (`getattr(...)()`, dict dispatch). A fully-dotted
`cre_mcp.deals.store.DealStore()` after a plain dotted import is missed too,
but by the module-scope fallback rather than that family: its callee is an
`Attribute` whose value is itself an `Attribute`. It can OVER-MARK through the same
fallback, which matches by attribute name, and through whole-class walking.
None is exercised by shipping code: nine construction sites, all bare-name,
seven in module-level functions and two in `__init__`, and no subclass.
Promoting the repositories-bound runtime derivation to a second pin removes all
of these and is the recommended follow-up. Note for anyone repeating a
reference-taint (bytecode) derivation: it over-reports `add_to_pipeline`,
`due_diligence_plan`, and `operating_playbook`. All three are alive — they route
store access through `get_deal_store()` and touch `DealStore` only via the
staticmethods `_validate_stage`/`deal_id_for` and a type annotation, none of
which is a construction.

This corrects a surface defect only. It certifies no store and re-routes no
capability. Removing an entry from `HOSTED_WITHHELD_CAPABILITIES` requires that
the capability actually route through a certified hosted port, under the same
review ceremony; certifying a store class is not by itself sufficient.

## Phase 5I Clerk identity verification 2026-08-06

Contract: `docs/launch/PHASE_5I_CLERK_IDENTITY_VERIFICATION_CONTRACT.md`.

Worktree `/Users/maxmedawar/LoopnetMCP-cloud-integration`, branch
`integration/cloud-platform-launch`, base `a828717`.

### What was wrong

`ClerkHumanIdentityVerifier.verify_bearer` returned the Clerk user's primary
email address without ever inspecting `EmailAddress.verification`.
`HumanIdentityStore.resolve_or_bind` then used exactly that string to pick which
preprovisioned MedawarCRE user a Clerk subject becomes on first sign-in.

In the installed `clerk-backend-api`, `verification` is `Nullable[Verification]`
and its `status` can be `unverified`, `failed`, or `expired`. An address a Clerk
account holder had added but not proven ownership of therefore carried full
binding authority. The result is a first-sign-in account takeover against any
MedawarCRE user who has not yet signed in — at launch, all of them. Once bound,
the mapping is stable by subject, so the takeover is durable rather than
transient, and every downstream check is correct while resolving the wrong user.

This is the exact class the founder decision forbids: authority taken from
user-editable identity-provider metadata.

Two adjacent omissions in the same twelve lines are closed with it:
`user.deprovisioned` was not refused although `banned` and `locked` were, and
the fetched record's `id` was never compared to the authenticated `sub`.

### Round one, and why it was not enough

The first frozen candidate `ccc3d015...` scoped the repair to the adapter
alone. Two fresh independent read-only reviews audited that exact hash and
reported the same value at start and finish; neither modified the tree.

Correctness **APPROVED**: it reproduced the red state, every number, the
mutation table line for line, confirmed the fixture change weakened no
assertion, and verified the nine imported ledger sections are byte-identical to
the control branch with all nine commits confirmed ancestors of HEAD.

Security **CHANGES REQUIRED**, and correctly so. The adapter was hardened while
the lookup that consumes its output was left alone, and that is where the
remaining defects were. Findings, all repaired in round two:

| # | Severity | Defect |
| --- | --- | --- |
| 1 | Medium | `EmailAddress.id` and `primary_email_address_id` are both optional; an unset pair matched on `None == None` and promoted a non-primary address |
| 2 | Medium | `str.casefold()` in Python against SQLite `lower()` in SQL — `straße@corp.test` bound to a stored `strasse@corp.test` row, and non-ASCII uppercase rows were permanently unreachable |
| 3 | Low | `hmac.compare_digest` raises on non-ASCII and sat outside the provider `try`, so a 500 instead of `None` |
| 4 | Low | A whitespace-only address raised out of the dataclass |
| 5 | Low | Two distinct binding-refusal messages, echoed to the browser, enumerated provisioned addresses |
| 6 | Low | No pin constructed a real `clerk_backend_api` model |

Finding 2 is the one worth remembering. It was a genuine cross-account bind
*and* a permanent lockout, in the same two lines, and both directions came from
assuming two functions named "lowercase" are the same function. Round one's
contract had listed `HumanIdentityStore` as non-scope; that boundary was wrong,
because the join key is the adapter and the lookup together.

### Round two, and the defect that survived it

Candidate `2e1881be...` was frozen and audited by two fresh reviewers, both
reporting the same hash at start and finish and neither touching the tree.

**Both rejected it, and both found the same defect independently.** The round-one
repair had hardened the reader while `AdminControlStore.provision_workspace`
— the internal Operations Console provisioning path — still stored
`owner_email.casefold()`. The two folds then disagreed by construction on
exactly the character class the contract named:

```
operator provisions 'Straße@corp.test'  ->  row stored as 'strasse@corp.test'
holder of 'strasse@corp.test'           ->  BINDS to that row
holder of 'Straße@corp.test' (rightful) ->  DENIED, permanently
```

So the cross-account bind was not closed, it was relocated from the read fold
to the write fold — and a regression was added, because at base `a828717` the
rightful owner did resolve. The contract's own claims that the change
"collapses nothing" and was "read-path only" were false at the system level.

Additional findings, all repaired: `user.id` was compared without the
`isinstance` guard applied to `email.id`; the predicate's docstring claimed
Clerk proof stronger than `verification_admin` actually establishes; no
Unicode normalization meant an NFD address from the provider could never reach
an NFC row; and two statements in this ledger were wrong — see below.

The lesson is the one the reviews stated: a normalization applied at one end of
a join key is not a normalization. The repair therefore defines one canonical
form for the column in `cre_mcp/platform/models.py` and applies it at all three
write sites and the read, matching by exact equality so no SQL engine's case
rules participate.

### Evidence

- Round-one red, new pins only: **12 failed, 4 passed**. The four passes are the
  two positive controls and the already-refused `banned` and `locked` siblings.
- Round-two red, repair pins only: **7 failed, 17 passed**. The real-SDK-model
  pin passed on arrival, confirming the predicate already handled genuine
  models rather than only fakes.
- Round-ten green: **97 passed** across the new module and the existing
  `test_human_identity.py`.
- Focused regression: `tests/platform tests/surface
  tests/access/test_profiles_matrix.py` — **636 passed, 4 skipped** (546 at
  base; 562, 572, 580, 584, 585, 595, 596, 608, and 621 at rounds one through
  nine).
- Complete repository gate: **4,958 passed, 4 skipped**, one categorized
  third-party Authlib deprecation. The re-verified base measured **4,868
  passed, 4 skipped** on the same interpreter, so the delta is exactly the 90
  pins this phase adds and nothing regressed — including no fallout from
  normalizing every write site.
- Connection UI recheck: **5 Vitest cases passed**, unchanged.

### Round three, and the fold that was wrong in the other direction

Candidate `f521306a...` was audited by two fresh reviewers, hash stable at both
ends, neither touching the tree. Correctness **APPROVED** with no code defect,
reproducing every number and the round-three mutation table exactly. Security
**REJECTED** it, and was right again.

The round-two repair had replaced `casefold()` with an ASCII-only fold,
reasoning that it could not collapse anything. It cannot — but it also folds
only `A`–`Z`, so every other capital survives:

```
operator types 'MÜLLER@corp.test'  ->  stored 'mÜller@corp.test'
Clerk reports  'müller@corp.test'  ->  key    'müller@corp.test'   REFUSED
base a828717                                                       BOUND
```

Same for `JOSÉ@`, `ИВАН@`, `ΑΝΝΑ@`. A false denial and a regression, from a
fold that was case-insensitive for some customers and not others. `str.lower()`
is the correct answer and was available the whole time: it does **not** collapse
`ß`, `ﬁ`, or `ſ` — only `casefold()` does — so it gives case-insensitivity
across the whole alphabet while keeping separate mailboxes separate. Verified
over every Unicode code point: idempotent, NFC-stable, no collision group
beyond ordinary case and canonical equivalence. It also makes the application
form agree with PostgreSQL's `lower(email)` index, which the ASCII fold did
not — two rows legal in SQLite that one PostgreSQL unique index could not hold.

The pin that should have caught this existed and passed, because it used the
same string on both sides of the write and the read and so could not observe a
case difference. The pins now differ deliberately between what the operator
types and what the provider reports. A pin for `update_user`, the one write
site left unpinned, was added in the same round.

### Round four

Candidate `793da460...` was audited by two fresh reviewers, hash stable at both
ends, neither touching the tree.

Security **APPROVED**. It could not construct any Clerk response shape yielding
an identity for an unproven address, swept all 1,114,112 code points plus
64,414 multi-character sequences against the canonical form for collisions and
idempotence, and loaded 1,109,579 canonical values into a real PostgreSQL 16
cluster across three collations to check the unique index agrees. All four
previously rejected defects confirmed closed rather than relocated.

Correctness **REJECTED**, on documentation only — no code defect, every number
and the round-four mutation table reproduced exactly. The blocking finding was
that this ledger still contained the sentence "every guard is now individually
falsifiable" six lines after the paragraph retracting it, and that a *second*
guard was in the same undisclosed position. That is the same standard the three
prior rounds were rejected on, applied to the document rather than the code.

Round five is that repair: the sentence is deleted, the second guard is pinned
instead of excused, three code comments that justified a design with a fact
this commit invalidated are corrected, and the contract's overstatement about
pre-existing rows is narrowed to match the ledger.

### Round five, and the sigma regression

Candidate `7c13c810...` was audited by two fresh reviewers, hash stable, tree
untouched. Both rejected it.

Security found a **HIGH**: `str.lower()` is not a per-code-point map. It
implements Unicode's `Final_Sigma` rule, so `Σ` lowercases to `ς` at a word
boundary and `σ` elsewhere:

```
operator types  'ΓΙΩΡΓΟΣ@CORP.TEST'  ->  stored 'γιωργος@corp.test'  (ς)
owner's Clerk address 'γιωργοσ@…' (σ) ->  REFUSED, permanently
holder of 'γιωργος@…' (ς)             ->  BOUND to the owner's row
```

Worse in kind than the ASCII-fold defect it replaced: that one produced an
unreachable row, this one keyed the row to a **different live mailbox**. And a
regression against base, where `casefold()` mapped both sigma forms to `σ` and
matched the owner correctly. The repair folds per code point and unifies `ς`
onto `σ`, which is what `casefold()` did and the only way `Σ` can fold at all.

The pin that should have caught it existed: the parameterized case table had a
Greek name in it — `ΑΝΝΑ`, the one Greek name containing no sigma. The table
now carries `ΓΙΩΡΓΟΣ` and `ΟΔΥΣΣΕΥΣ` in both spellings.

Correctness rejected the same candidate on documentation, and its finding is
the more useful one: the replacement sentence "one guard is not individually
falsifiable" was itself false — three further guards and two claimed properties
survived deletion with the whole suite green. That is the third consecutive
round rejected for a claim about coverage rather than for the coverage itself.

### Four false statements in this ledger, corrected

Recorded rather than quietly edited, because each was caught by review and not
by me:

- "The two branches share no source file" was false; they diverge across 149
  files under `src/` because the control branch sits at an older base. The
  import paragraph now states the narrow, true claim instead.
- The round-one mutation row read "Verification predicate always returns true",
  but a literal `return True` on the whole predicate kills 10 pins, not 9. The
  mutation actually run neutered the status comparison while leaving the
  null-`verification` guard in place. The row is relabelled to what was run.
- "Every guard is now individually falsifiable" was false: the `len(matches)
  != 1` arm is unreachable on SQLite and kills nothing. It is now recorded as
  an unfalsifiable-but-correct guard instead of counted as covered.
- That same sentence then survived in a second place in this section, after
  being recorded as retracted — and a second guard, the `.value` normalization
  in `_clerk_email_is_verified`, turned out to be unfalsifiable too, with the
  existing enum pin's docstring claiming the opposite. The sentence is deleted
  and that guard is now pinned with a non-`str` enum.

Every mutation table before round ten was measured against a candidate that
was superseded and never committed, so none of them is reproducible against the
committed tree. They are kept because they record what was found and when. An
earlier version of this note scoped the disclaimer to rounds one and two, which
implied the later ones were re-runnable; they are not, and an earlier version
also referred to "their tables" for rounds that have none.

### Mutation evidence

Each guard broken in place against a working-copy snapshot, with a green
control before and after every set. Tables appear newest first.

Round ten, control 97 passed:

| Mutation | Result |
| --- | --- |
| NFC applied before the fold rather than after | 15 failed |

Round nine, control 82 passed:

| Mutation | Result |
| --- | --- |
| `deprovisioned` `getattr` default dropped | 1 failed |
| `email.id ==` becomes `is` | 1 failed |
| `record_id !=` becomes `is not` | 1 failed |
| Canonical form uses NFD | 1 failed |
| Canonical form uses `.strip(" ")` | 4 failed |
| `getattr(email, "verification", …)` becomes attribute access | 1 failed |
| `getattr(user, "id", …)` becomes attribute access | 1 failed |
| `getattr(user, "primary_email_address_id", …)` becomes attribute access | 1 failed |
| `getattr(primary_email, "email_address", …)` becomes attribute access | 1 failed |

Round eight, control 69 passed:

| Mutation | Result |
| --- | --- |
| Canonical form uses NFKC | 3 failed |
| Canonical form drops `.strip()` | 1 failed |
| `create_user` reverts to `casefold()` | 6 failed |
| `update_user` reverts to `casefold()` | 2 failed |
| Primary-address scan truncated to the first entry | 1 failed |
| Final-sigma unification dropped | 3 failed |
| `isinstance(status, str)` dropped | 1 failed |
| `isinstance(primary_id, str)` dropped | 1 failed |
| `isinstance(primary, str)` dropped | 1 failed |
| Connection route forwards `str(exc)` again | 1 failed |
| Operations route forwards `str(exc)` again | 1 failed |
| `_identity_from_user` hoisted out of the `try` | 1 failed |
| `getattr(status, "value", status)` dropped | 1 failed |

The round-six version of this table carried a row labelled "whole-string
`lower()` restored", scored at 3 failed. That label was wrong: reverting only
the loop while keeping the unification kills nothing — the 3 failures came from
reverting the whole canonical form, which drops the unification too. The row is
gone along with the loop, and the unification carries the 3.

There is no round-five table. Round five added one pin and changed
documentation; it introduced no guard to mutate.

Rounds one through nine were measured against candidates that were superseded
and never committed, with controls of 23, 33, 41, 45, 46, 56, 57, 69 and 82
against the committed tree's 97. Rounds one to four, eight and nine have tables;
five, six and seven are narrated without one. Those tables record what was found
and when, and none of them is re-runnable against the committed tree — the round
nine table sits above this line and is no more reproducible than the ones below
it. Its "canonical form uses NFD" row, for instance, measures 16 rather than 1
against the committed tree, because round ten added pins that mutation also
kills.

Round one, control 23 passed:

| Mutation | Result |
| --- | --- |
| Status comparison always returns true (null-verification guard retained) | 9 failed |
| Status comparison becomes case-insensitive | 1 failed |
| Any verified address rescues the primary | 1 failed |
| `deprovisioned` no longer refused | 1 failed |
| Record-id/subject binding dropped | 1 failed |
| Null verification treated as verified | 1 failed |

Round two, control 33 passed:

| Mutation | Result |
| --- | --- |
| Fold reverts to `casefold()` | 2 failed |
| Ambiguous candidate set accepted | 1 failed |
| `primary_email_address_id` guard dropped | 1 failed |
| `email.id` string guard dropped | 1 failed |
| Subject check reverts to `compare_digest` | 1 failed |
| Blank-address guard weakened to falsiness | 1 failed |
| Distinct refusal messages restored | 2 failed |

Round three, control 41 passed:

| Mutation | Result |
| --- | --- |
| `provision_workspace` reverts to `casefold()` | 5 failed |
| `create_user` drops normalization | 1 failed |
| Canonical form drops NFC | 1 failed |
| Canonical form uses `casefold()` | 1 failed |
| `user.id` isinstance guard dropped | 1 failed |
| Lookup reverts to `lower(email)` | 1 failed |

The lookup mutation survived its first run: with every write canonical,
SQLite's ASCII-only `lower()` is indistinguishable from exact equality, so the
change is unobservable on this backend. Rather than report it as covered, a pin
was added for the property exact equality actually buys — a row written in some
other form is unreachable rather than matched approximately, which is what
keeps PostgreSQL's Unicode-aware `lower()` from changing the answer at cutover.

Round four, control 45 passed:

| Mutation | Result |
| --- | --- |
| Canonical form reverts to the ASCII-only fold | 5 failed |
| Canonical form uses `casefold()` | 1 failed |
| Canonical form drops NFC | 1 failed |
| `update_user` drops normalization | 1 failed |
| `provision_workspace` reverts to `casefold()` | 4 failed |
| `create_user` drops normalization | 2 failed |

These mutations survive with the whole suite green. They are listed, not
counted — six consecutive rounds were rejected for a false claim about
coverage, never for the coverage itself, and twice the false claim was the
sentence written to replace the previous false claim.

| Survivor | Why it cannot fail |
| --- | --- |
| `len(matches) != 1` → `if not matches` | `platform_users.email` is UNIQUE and every writer stores the canonical form, so an exact-equality select returns at most one row on SQLite |
| `primary = primary.strip()` removed | the canonical form strips, so only the returned dataclass field would carry padding |
| `if verification is None: return False` removed | `getattr(None, "status", None)` already fails the `isinstance` check below it |
| `primary_email is None or` removed | `_clerk_email_is_verified(None)` already returns `False` |
| `bool(...)` around `deprovisioned` removed | truthiness is what the `or` chain already evaluates; the `getattr` default in the same expression is the half that carries a claim, and it is pinned |

All are kept. The first is real defence for a backend without that constraint;
the rest are ordinary defensive clarity, and unlike the per-code-point loop
deleted in round seven, none carries a comment claiming a safety it does not
provide. That distinction is the standard: delete a guard that misdirects the
next reader, keep one that merely restates a guarantee, and say which it is.

An earlier version of this table listed five and was short by six. Those six
are now pinned rather than listed, because each had an observable consequence:
dropping the `getattr(user, "deprovisioned", False)` default denies every
record from an SDK predating the field; comparing either identifier with `is`
instead of `==` refuses every production sign-in while passing tests that reuse
one interned literal on both sides; `NFD` instead of `NFC` changes the stored
form; `.strip(" ")` leaves tab and newline padding; and plain attribute access
instead of `getattr` turns an absent SDK field into an error. Writing that last
pin found a real gap — `primary_email.email_address` had no `getattr` guard, so
an absent address raised instead of refusing, contradicting requirement 5. The
guard is now there.

The guards below were in that position across rounds five through nine and are
pinned rather than excused, each found by review rather than by the builder.
The list is deliberately not summarised by a count; count the rows.

| Guard | Pin that now kills it |
| --- | --- |
| `getattr(status, "value", status)` | a plain `enum.Enum` status, which fails `isinstance(x, str)` |
| `isinstance(status, str)` | a status object whose `__eq__` answers true |
| `isinstance(primary_id, str)` | a truthy `primary_email_address_id` that compares equal to anything |
| `isinstance(primary, str)` | a non-string address, through the direct call |
| the connection route's fixed error body | an HTTP POST to `/v1/browser/session` asserting the store's text is not forwarded |
| the operations route's fixed error body | the same assertion against `/v1/operations/session` |
| `_identity_from_user` inside the provider `try` | a record whose attribute access raises |
| NFC rather than NFKC | `ﬁnance`/`finance`, `ſam`/`sam`, `µicro`/`μicro` as separate people |
| `create_user` and `update_user` normalization | collapse-sensitive, NFD, and sigma-bearing addresses driven through each |
| the canonical form's `.strip()` | padded addresses using space, tab, newline, and CRLF |
| the primary-address scan | a primary sitting at index 1 |
| the `getattr(user, "deprovisioned", False)` default | a record with the attribute deleted |
| `==` rather than `is` on both identifiers | identifiers built at runtime, so the two sides are different objects |
| NFC rather than NFD | the stored bytes asserted composed |
| `getattr` on five optional SDK fields | each field deleted, through the direct call |
| NFC applied after the fold, not before | Greek capitals with a combining mark, where composing first leaves the result un-composed |

One further guard was not pinned but deleted. The per-code-point lowering loop was an
equivalent mutant: with the `ς → σ` unification applied it computes the same
value as whole-string `str.lower()` on every input, so it could not fail, and
its comment credited it with closing the sigma defect that the unification
actually closes. Two reviews measured zero differences independently.

The two error bodies were one row in an earlier version of this table, and that
row was false: only the connection route was pinned, and reverting the
operations route to `str(exc)` left the entire repository green. They are two
rows now because they are two code paths.

Round eight is the sharpest instance of the same pattern. The parameterized
write/read table carried eleven rows, and its docstring said every row differed
between the typed and the reported spelling — the repair round six had made.
Two rows, `ﬁnance` and `ſam`, still passed the identical string on both sides.
Those were two of the three addresses whose non-collapse nothing else pinned —
the third being the micro sign, which `casefold()` and NFKC both map to `μ` —
so switching the canonical form from NFC to NFKC passed all 4,918 tests and
would have restored the cross-account bind for ligature, long-s, and
micro-sign addresses. A docstring asserting a property of a table is not a
check that the table has it.

Round nine found the same shape one layer down: a comment on the last two rows
of that table claimed they discriminated the final-sigma unification, and they
do not — without it both sides fold to the same value and meet anyway. The
rows above them are what pins the unification. The comment now says so, and
the rows are kept as positive controls.

The history of this claim is the part worth keeping. "Every guard is now
individually falsifiable" was asserted, then recorded as retracted while the
assertion itself still stood a few paragraphs below — the document claiming and
disclaiming the same thing at once. It was then replaced with "one guard is not
falsifiable", which was also false: three more guards and two claimed
properties survived deletion. The lesson is that a summary count is the wrong
shape for this evidence. The table above names each guard and the pin that
kills it, so a future reader checks entries rather than trusting an adjective.

Three of the round-two seven survived their first run. `primary_email_address_id` and
`email.id` masked each other, and the try/except masked the blank-address
guard, so all three passed while proving nothing. Rather than report six of
seven, pins were added that isolate each: a blank id on both sides, an object
whose `__eq__` answers true to everything, and a direct call to
`_identity_from_user` that bypasses the try.

Two harness defects are recorded because both produced plausible numbers that
were wrong. The first restored from git `HEAD` instead of the working copy,
silently reverting the implementation so every run after the first measured the
unfixed tree. The second passed a two-path test selector through an unquoted
zsh variable, which does not word-split, so pytest received one nonexistent
path and reported "no tests ran" — read as a result rather than as a broken
harness, that would have been seven fabricated survivals. A mutation number is
only meaningful next to a green control that used the identical command.

### Test-side corrections, disclosed

Two changes were made to the pre-existing `test_human_identity.py`, not one. An
earlier version of this section listed only the first and presented itself as
complete.

The first: in
`test_clerk_adapter_uses_official_verifier_authorized_party_and_user_record`,
the substituted Clerk user object had no `id`, no `deprovisioned`, and no
`verification` on its email address. The real SDK model carries all three, so
that fixture could not have exercised any of these boundaries. It is now shaped
after the installed model — a fixture becoming faithful, not an assertion being
relaxed; the test's expectations are unchanged.

The second: the assertion on the binding-refusal message changed from
`"preprovisioned" in str(exc) or "already linked" in str(exc)` to exact
equality with `_IDENTITY_NOT_BINDABLE`. That is a strengthening — the old form
accepted either of two texts, the new one accepts exactly one — and it was
required because collapsing the two messages is what closes the enumeration
oracle. It is disclosed because a reader auditing which assertions moved should
find both here, not one.

### Unchanged invariants, re-derived rather than asserted

274 total capabilities, 253 grouped actions, 21 internal-only, 15
hosted-withheld, 238 hosted-reachable; catalog fingerprint `84578ae71567ed18`;
visible tools Local 8, National 10, Full Operator 20, JV Partner 11. Source and
tests compile, `git diff --check` is clean, the changed-content credential scan
is clean, no port-8000 listener, no migration or dependency change, and an
isolated wheel packages the capability matrix, the source-rights registry, the
surface catalog, and all eight numbered migrations plus `restore_privileges.sql`.

### Lifecycle matrix follow-up 2026-08-06

The Phase 5I contract's lifecycle inventory said the founder's enumerated flows
were already covered by existing tests. Auditing that claim rather than
restating it found four enumerated flows with no store-level pin at all:
a stale consent handle, concurrent approval of one handle, replay after
consumption, and reconnect after session revocation. Four pins were added
(`4,958` to `4,962`).

What they pin, stated precisely because measuring it changed the answer:

- **Single-use consent is pinned.** The replay pin fails when the
  `consumed_at IS NULL` select filter and the single-row UPDATE guard are
  removed *together*. Each alone is masked by the other — defence in depth,
  and neither is individually falsifiable.
- **Concurrency is documented, not pinned.** Eight threads racing one handle
  produce exactly one authorization, but removing `BEGIN IMMEDIATE`, or the
  UPDATE guard, or both, leaves the test green: SQLite serializes writers on
  its own. The test asserts the property; it does not establish that the
  locking is what provides it. The test comment says so.
- **Stale rejection is documented, not pinned.** `consume` deletes expired rows
  before selecting, so the explicit expiry comparison is unreachable — an
  equivalent mutant.
- **Reconnect after revocation is pinned** by behaviour: a revoked token stays
  dead and the next sign-in issues a different token and CSRF pair.

Recorded this way because the alternative — writing four tests and calling four
guards covered — is precisely the error that rejected five earlier rounds.

### Open items this phase records but does not close

- No unbind path exists: there is no `DELETE FROM platform_human_identities`
  anywhere in `src/`, so a wrong binding is permanent short of deleting the
  user and cascading away their data.
- `medawarcre.human_identities` in PostgreSQL lacks the
  `UNIQUE (provider, user_id)` the SQLite table has, and
  `0001_authoritative_cloud.sql` indexes `lower(email)` under a Unicode-aware
  `lower()`. Both are unreachable today — there is no PostgreSQL identity
  binding code — and both are blockers for the hosted identity cutover.
- A `platform_users` row written before this change is unreachable by design
  **only if its stored value is not already the canonical form**. Pure-ASCII
  addresses written by the old `provision_workspace` path were `.casefold()`ed,
  which is byte-identical to the new form, so those rows are unaffected. Rows
  carrying a casefold-collapsing or non-ASCII-capital character must be
  re-keyed in private staging before first production use. An earlier version
  of this line said every prior row was unreachable, which overstated it.
- The Clerk instance's verify-at-sign-up setting and its enabled
  social/enterprise connection set are now load-bearing deployment decisions.

### Boundary

No deployment, DNS change, billing activation, provider mutation, or
customer-data action occurred. No real Clerk credential was used or requested;
the adapter is proven against the official SDK's types through a substituted
client, and a live Clerk test instance remains the next external blocker for
this thread.

## Phase 5J production secret boundary 2026-08-06

Contract: `docs/launch/PHASE_5J_SECRET_BOUNDARY_CONTRACT.md`. Base `e78d390`.

Founder decision, recorded above: a local `.env` is never the production source
of truth for a real Clerk, Stripe, Skool, or database credential.

### What this phase found

The mechanism the decision requires already existed and was never stated or
proven. `CreConfig` is a `pydantic-settings` model with `env_prefix="CRE_"`, so
environment variables already outrank the optional `.env` file — which is
exactly the managed-secret injection path — and every credential field was
already `SecretStr`. This phase did not build machinery. It made the guarantees
explicit, pinned them, and wrote the operational contract.

Fifteen pins were added, thirteen of which passed on arrival. That is the
honest shape of it: the properties held, nothing established that they held,
and nothing would have caught a regression.

The two that failed were both in the pins themselves. The type sweep flagged
`oauth_token_rate_limit_per_minute` — an `int` matching the `token` marker, a
rate limit rather than a credential, now an audited exemption with its reason.
And the exemption-rot check caught that two of the four exemption names I had
written did not exist on the model at all, which is the failure mode that check
exists for: a stale exemption silently excuses whatever later reuses the name.

### Evidence

Secret-boundary module 15 passed. Repository gate 4,977 passed, 4 skipped, up
from 4,962 by exactly these fifteen. Both mutations kill: typing
`clerk_secret_key` as `str` errors the whole module, and typing
`stripe_api_key` as `str` fails five pins.

Every credential field is `SecretStr`; the only non-secret name match is the
rate limit. `.env` is untracked, gitignored, and not required — configuration
loads from the process environment alone, and an injected value beats a stale
file. No `repr`, `str`, or JSON dump discloses a value; no raised error carries
one; a missing Clerk secret answers `503 human_identity_unconfigured` rather
than degrading; and a sweep of every registered route found none emitting
secret material.

### An unprovenanced module, read and deleted

An untracked `src/cre_mcp/platform/secrets.py` appeared in the worktree during
this session. I did not write it; the likeliest origin is a review agent
writing into the repository despite read-only instructions. It is recorded
because an unexplained source file in a security phase is exactly the thing
that should never be quietly absorbed.

It was read in full rather than deleted on sight, because it implemented the
requested boundary competently: provider-neutral, no new dependency, names-only
so no value could be logged or raised, and resolved at call time so rotation
needs no rebuild. Its PostgreSQL variable names check out against the code.

It was deleted anyway, for a specific reason: `CRE_STRIPE_ENABLED` and
`CRE_SKOOL_ENABLED`, the flags its conditional logic gates the Stripe and Skool
credentials behind, **do not exist in this codebase**. Nothing reads them. So
those secrets would never have been treated as required, silently, while the
module read as though it checked them. It was also entirely unused — no import,
no test.

Plausible and wrong is worse than absent. The boundary the founder decision
asks for already exists in `pydantic-settings` environment precedence, is now
proven by fifteen pins, and its inventory lives in `deploy/DEPLOY.md` as a
table a reader can check against the model. Every name in that table was
verified present on `CreConfig`; none is invented.

### External staging integration gate

A real Clerk network smoke test is the only unverified item in the identity
thread and is recorded as an external gate rather than a blocker. The secret
Max supplied was rejected by Clerk's own API as invalid — verified not to be a
transcription fault: 50 characters, correct prefix, no whitespace, no non-ASCII,
and the publishable key decodes to exactly the configured issuer host. A
development-instance key is needed to close it. Local engineering does not wait
on it.

### Boundary

No provider chosen, no infrastructure provisioned, no deployment, no DNS, no
billing, no spend. Tests and documentation only; no source change.

## Ledger reconciliation 2026-08-16: the boot blocker is lifted

The rows above were written while `build_postgres_hosted_persistence` refused
unconditionally. Eight commits from `f5955ec` to `6b2972f` changed that, so the
statuses are re-derived here rather than left to be read as current. No row is
deleted; this section is their disposition.

| Row | Was | Is | Why it moved |
| --- | --- | --- | --- |
| Combined opportunity index | 🔴 | 🟢 | `f5955ec` (Phase 5K) predates this work and the row predates it |
| Clerk identity and connection flow | 🟡 | 🟡 | Unchanged. Local engineering complete; a real Clerk test instance is still the one external gate |
| Internal Operations Console | 🟡 | 🟢 | Reads the real PostgreSQL rows, proven in `test_platform_bridge_runtime.py`. Found and fixed a bare column under `GROUP BY` that would have broken every Console workspace search on PostgreSQL |
| Scheduled saved searches | 🔴 | 🟢 | `postgres/jobs.py` and `postgres/worker.py`; idempotent enqueue, `SKIP LOCKED` claiming, lease expiry, backoff, live entitlement and territory recheck, and a running loop |
| Stripe test integration | 🟡 | 🟢 | All eight requirements proven on the hosted PostgreSQL path in `test_stripe_lifecycle_postgres.py`. A real Stripe test-account run remains an external gate |
| Skool reconciliation | 🟡 | 🟢 | The launch gate now runs on the real hosted path, including that the *scheduled* worker stops for a revoked member |
| Privacy and retention | 🔴 | 🟢 | `postgres/privacy.py` plus `medawarcre-postgres privacy {list,submit,advance,export}` |
| Production secret boundary | 🟡 | 🟢 | The inventory refused an unlisted worker credential twice, which is the boundary working |
| Private staging | 🔴 | 🟢 | `deploy/local_staging.sh`, asserting a 401 on an unauthenticated initialize, no local state file, and a worker tick |
| Integrated security audit | 🔴 | 🟡 | Run. Four confirmed defects in migration 0012, all closed by 0013 and pinned by `test_projection_is_a_projection.py`. A confirmatory re-review is the remaining step |
| Production-readiness packet | 🔴 | 🟢 | `docs/launch/PRODUCTION_READINESS.md` |
| Public production cutover | 🔴 | 🔴 | Unchanged, and deliberately so |
| Proxy credential reaches a log in trusted-local stdio | 🔴 | 🔴 | Unchanged. Not touched by this work and not hosted-reachable |

**What the audit found, recorded because it is the most important thing in this
round.** Migration 0012's projection accepted the values it wrote as arguments
and never checked them against the platform authority, while its own header
claimed the opposite. A hand-built context naming a workspace that does not
exist was projected and admitted. Three consequences followed, one of which was
a launch-gate violation: a revoked Skool member's projected grant stayed active,
and the scheduler's documented "live entitlement recheck" reads that row, so the
worker would have kept running their saved searches. `tools/call` was correctly
shut; this was the back door. Migration 0013 makes both functions read the
`platform_*` relations and refuse when the row is not there.

Two corrections to this program's own tests came out of the same audit. One
assertion — "a refused admission leaves no tenant behind" — was made through an
RLS-filtered connection where the count is zero for every input, so it asserted
nothing; the reviewer confirmed the row was there. The other was a claim in a
test docstring that extending the projection needed a pin widened, which stopped
being true when the pin was widened deliberately.


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
