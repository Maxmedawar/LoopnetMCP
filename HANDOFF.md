# 1. GOAL

Finish and independently certify the Stripe/Skool provider-sync replay-authority repair so editable replay evidence cannot change a member's plan, profile, subject, scope, action, or access end date.

# 2. STATUS BOARD

| item | status | evidence |
|---|---|---|
| Stripe/Skool provider-sync foundation | 🟢 done and verified | Commit `e647a480758ce71ae9d7357c1b4ee7e2dd3345b7`; `git log --oneline -10` shows `e647a48 feat(platform): add Stripe and Skool provider synchronization`. |
| Exact-subject authority and explicit workspace JV authority | 🟢 done and verified | `tests/platform/test_provider_final_audit_repairs.py:402`, `:461`, `:518`, `:1107`; full command result: `1770 passed, 1 warning in 54.97s`. |
| Stripe paid-through period is authoritative | 🟢 done and verified | `tests/platform/test_provider_final_audit_repairs.py:46`; full suite passed. |
| Equal-time restrictive event ordering | 🟢 done and verified | `tests/platform/test_provider_final_audit_repairs.py:86`; full suite passed. |
| Stripe trialing remains non-granting | 🟢 done and verified | `tests/platform/test_provider_final_audit_repairs.py:164`; full suite passed. |
| Restrictive projection retry, bounded exhaustion, and replayability | 🟢 done and verified | `tests/platform/test_provider_final_audit_repairs.py:226`, `:325`, `:644`; full suite passed. |
| Private event-stream hash, restrictive rank, and covering index | 🟢 done and verified | `tests/platform/test_provider_final_audit_repairs.py:581`; full suite passed. |
| Forged cross-workspace and normalized identity replay rejection | 🟢 done and verified | `tests/platform/test_provider_final_audit_repairs.py:745`, `:979`; full suite passed. |
| Other-subject grant metadata isolation | 🟢 done and verified | `tests/platform/test_provider_final_audit_repairs.py:1168`; full suite passed. |
| Poisoned unknown selector cannot grant operator authority | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:309`; full suite passed. |
| Poisoned replay cannot upgrade Local Scout to Full Operator | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:363`; full suite passed. |
| Poisoned replay cannot extend paid-through to 2036 | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:432`; full suite passed. |
| Same-selector configuration remap cannot change authority | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:488`; full suite passed. |
| Legitimate plan/profile mapping can bind exactly once | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:543`; full suite passed. |
| Normalized event authority surface is explicit | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:622`; full suite passed. |
| Compatibility writer uses the same binding contract | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:656`; full suite passed. |
| Exact-action tampering is rejected | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:710`; full suite passed. |
| Same-workspace account/subject redirection is rejected | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:771`; full suite passed. |
| Replay after membership removal records a mismatch without losing evidence | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:832`; full suite passed. |
| Bound-scope disagreement is rejected | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:900`; full suite passed. |
| Older restrictive replay stays stale after newer positive authority | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:1003`; full suite passed. |
| Untrusted legacy receipt stays durably quarantined | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:1061`; full suite passed. |
| Fully bound valid replay reconciles | 🟢 done and verified | `tests/platform/test_provider_replay_receipt_bindings.py:1137`; full suite passed. |
| V5 fresh schema authority bindings | 🟢 done and verified | `tests/platform/test_provider_sync_migrations.py:1335`; full suite passed. |
| V5 hash and paired plan/profile bindings are write-once | 🟢 done and verified | `tests/platform/test_provider_sync_migrations.py:1383`; full suite passed. |
| V5 migration rollback preserves receipt evidence | 🟢 done and verified | `tests/platform/test_provider_sync_migrations.py:1576`; full suite passed. |
| V5 legacy policy retains evidence and restrictive safety | 🟢 done and verified | `tests/platform/test_provider_sync_migrations.py:1640`; full suite passed. |
| V5 concurrent initialization records once | 🟢 done and verified | `tests/platform/test_provider_sync_migrations.py:1937`; full suite passed. |
| Full repository test gate | 🟢 done and verified | `TMPDIR=/tmp/medawarcre-handoff.da9OZo PYTHONPATH=src /Users/maxmedawar/LoopnetMCP/.venv/bin/python -m pytest -q` → `1770 passed, 1 warning in 54.97s`, exit `0`. |
| Compile gate | 🟢 done and verified | `PYTHONPYCACHEPREFIX=/tmp/medawarcre-handoff.da9OZo/pycache /Users/maxmedawar/LoopnetMCP/.venv/bin/python -m compileall -q src` → no output, exit `0`. |
| Wheel build gate | 🟢 done and verified | `pip wheel --no-deps --no-build-isolation` → `Successfully built cre-mcp`; wheel SHA-256 `3e56e0bcb613b63945db5fee583e20d08a313e1513a38b2e291b888f4850ee3a`. |
| Diff whitespace gate | 🟢 done and verified | `git diff --check` produced no output. |
| Fresh independent Claude-b audit of V5 bytes | 🟢 done and verified | A second fresh, independent Claude-b certifier (separate session, no shared context with the prior crashed attempt) completed the full read-only protocol against tree hash `554268d78edf092b87e046e12a5ac031504e74afe6f21f705ee4ff44a8a02c76` at HEAD `e647a480758ce71ae9d7357c1b4ee7e2dd3345b7` and returned an explicit verdict: **APPROVE**. Full evidence recorded in the "FINAL SECURITY CERTIFICATION" section below. Supersedes the prior crashed attempt; do not re-run unless the tree changes. |
| Final security approval | 🟢 done and verified | **APPROVE.** `52 passed` on the three targeted files; `1770 passed, 1 warning` on the full suite; a fresh self-authored `/tmp` two-candidate ambiguity probe (18/18 checks passed) and a DB-bypass probe were run independently of the repo's own tests. Two non-blocking observations were recorded (neither exploitable, neither correctness-significant) — see "FINAL SECURITY CERTIFICATION" below. Final integrity re-check confirmed the reviewed bytes were unchanged from the identity captured at the start of the audit. |
| Skool production enablement | 🔴 not started — still blocked | `.claude/skills/stripe-skool-provider-sync/SKILL.md` and `docs/provider-sync-limitations.md` say production remains blocked until a trustworthy restrictive and current-state source exists. **The APPROVE verdict above certifies the replay-authority repair only. It does not clear this blocker and does not mean the product is launch-ready.** |
| Commit, merge, push, and deploy | 🟡 partially done, outside this certification | After the APPROVE verdict, the reviewed tree was committed as `f36ef46fe44a21a50967227b476a771030c24816` (`fix(platform): bind provider replay authority`) and the `feature/stripe-skool-sync` branch now matches `fork/feature/stripe-skool-sync` — i.e. it has moved to (or already reached) that remote. This action was **not** performed by the certification session and is recorded here only because the on-disk state changed between the audit and this update. No merge to `main`/`origin`, and no deploy, has occurred. |
| Project HTTP server continuity | ❌ tried and broken | Earlier command captured PID `2370` listening on `127.0.0.1:8000`; the final `lsof -i -P -n | grep LISTEN` has no port `8000`. Cause: UNKNOWN. |
| Handoff packet | 🟢 done and verified | `/Users/maxmedawar/LoopnetMCP-provider-sync/HANDOFF.md`; post-write verification commands are recorded below. |

# 2A. FINAL SECURITY CERTIFICATION (APPROVE)

**Verdict: APPROVE.** Performed by a fresh, independent Claude-b certifier operating strictly read-only (no edits, commits, stashes, resets, or server starts) against the tree captured below. This section is the durable record of that certification; do not overwrite it on future passes — append a new dated certification instead if the tree changes again.

**Identity verified (before and after review — identical):**
- pwd: `/Users/maxmedawar/LoopnetMCP-provider-sync`
- branch: `feature/stripe-skool-sync`
- HEAD: `e647a480758ce71ae9d7357c1b4ee7e2dd3345b7`
- tracked diff SHA-256: `554268d78edf092b87e046e12a5ac031504e74afe6f21f705ee4ff44a8a02c76`
- `tests/platform/test_provider_final_audit_repairs.py` SHA-256: `8bf5067fb2d898a0795e893d79950bf5ecdbf7feac69dab40ec2d25d655bb517`
- `tests/platform/test_provider_replay_receipt_bindings.py` SHA-256: `2ef4b4b5473a42700cab537fcf0d6d6186f8fcd96b1c638dfef1a5f252115278`
- `git diff --check`: no output, exit `0`, both before and after review.

**Inspected in full:** `HANDOFF.md`; `.claude/skills/stripe-skool-provider-sync/SKILL.md`; `.claude/specs/stripe-skool-provider-sync.md`; the complete tracked `git diff` for `entitlements.py` (~2235 lines), `providers/core.py` (~908 lines), `stripe.py`, `authority.py`, `admin.py`, `reconciliation.py`, `api.py`, `models.py`, `.env.example`, `docs/provider-sync-limitations.md`; direct reads of `entitlements.py:1-150,1648-1855,2211-2660` and `providers/core.py:689-1550`; both untracked test files in full; `test_provider_sync_migrations.py:1296-1970` (v4/v5 migration functions and tests).

**Commands run:**
- `PYTHONPATH=src .venv/bin/python -m pytest -q tests/platform/test_provider_final_audit_repairs.py tests/platform/test_provider_replay_receipt_bindings.py tests/platform/test_provider_sync_migrations.py` → `52 passed`.
- Full suite (fresh `TMPDIR`): `PYTHONPATH=src .venv/bin/python -m pytest -q` → `1770 passed, 1 warning` (only the known Authlib deprecation).
- Two independent, self-authored `/tmp`-only probes (not added to the repo): an ambiguity probe and a DB-bypass probe, detailed below.

**Real two-candidate ambiguity proof:** configured two selectors (`price_local→local/local_scout`, `price_operator→operator/full_operator`), each independently present in server config (individually "eligible") but resolving to distinct identities.
- *Live ingestion*: `ProviderSyncService._mapping()` builds its candidate set from both real, configured selectors and returns `(None, "conflicting_plan_mapping")`; `ingest()` quarantines; zero grant/subscription rows created; `bound_plan_key`/`bound_profile` stay NULL; both selectors remain visible in retained `normalized_data`.
- *V5 migration*: built a receipt fully bound per v4 (workspace/subject/scope/account-hash/object-hash all set) whose stored evidence names the same two distinct, presently-configured selectors, then ran the actual `PROVIDER_SYNC_MIGRATIONS` (v1→v5) over it. Migration quarantines it `legacy_receipt_binding_untrusted`; `entitlement_input_hash`/`bound_plan_key`/`bound_profile` all stay NULL; evidence is retained. A post-migration admin replay attempt (same two-candidate config still active) is also rejected, and the pre-existing grant/subscription rows are byte-for-byte unchanged.
- All 18 assertions in this probe passed.

**Database bypass analysis:** the v4/v5 write-once triggers are `BEFORE UPDATE`-only. A plain `UPDATE` of `bound_plan_key`/`entitlement_input_hash` is correctly blocked (matches `test_provider_sync_v5_hash_and_plan_profile_bindings_are_write_once`). A raw script additionally confirmed `INSERT OR REPLACE` and a manual `DELETE`+re-`INSERT` at the same row `id` **do** bypass the immutability trigger (no `BEFORE DELETE` guard exists on `platform_provider_events`, unlike `platform_admin_audit`, which has one). `grep` across `src/` confirms zero production code paths use these primitives against this table — exploiting the gap requires raw SQL/file-level DB access, a privilege that already defeats every other table in the schema equally. Recorded as a non-blocking hardening recommendation, not a finding against APPROVE.

**Field-by-field:** *action* — receipt's `canonical_action` must equal the reconstructed event's action exactly, immutable via trigger. *subject/workspace/scope* — resolved only from live `platform_external_accounts`/membership state (or, for restrictive events after mapping removal, from the unique `(source, external_ref)` grant row plus current membership), bound exactly once via a COALESCE-guarded conditional `UPDATE` that fails closed on any mismatch. *plan/profile* — resolved only from trusted in-memory config, bound exactly once, same-selector remap fails closed. *access end* — Stripe's `current_period_end` is authoritative only when it arrives on a fresh trusted event and is baked into the immutable `entitlement_input_hash`; replay tampering toward 2036 is rejected. Trialing is confirmed non-granting end-to-end.

**Two non-blocking observations** (neither exploitable, neither correctness-significant — preserve on future edits):
1. The legacy `apply_subscription_event` compatibility writer (`entitlements.py`) sets `bound_plan_key`/`bound_profile` unconditionally at insert, even for restrictive actions, unlike `providers/core.py`'s pipeline, which leaves them NULL for restrictive actions. This is inert (never read during restrictive projection), only reachable from trusted direct Python calls (tests), not from any webhook/HTTP surface, and it makes the legacy-restrictive-hash fallback strictly *less* available — i.e. more conservative, not less.
2. The DB bypass described above (`INSERT OR REPLACE` / delete+reinsert defeats write-once triggers on `platform_provider_events`) is real but requires raw DB file access that already defeats every other table's guarantees; no current application code path is capable of triggering it.

**Skool production status — unchanged, still blocked:** this certification covers the replay-authority repair only. `.claude/skills/stripe-skool-provider-sync/SKILL.md` and `docs/provider-sync-limitations.md` still state that production enablement remains blocked until a trustworthy restrictive and current-state source exists end to end. **APPROVE here does not mean the Skool integration, or the product as a whole, is launch-ready.**

# 3. STATE ON DISK

**Post-certification update:** after the APPROVE verdict above, the tree described below was committed as `f36ef46fe44a21a50967227b476a771030c24816` (`fix(platform): bind provider replay authority`), and `feature/stripe-skool-sync` now matches `fork/feature/stripe-skool-sync`. That commit/push was **not** performed by this documentation update or by the certification session — it was observed as already-done when this file was reopened. `git diff` against the new HEAD is now empty (nothing uncommitted); only `HANDOFF.md` remains untracked. The rest of this section is the verified snapshot *at the time of certification* (HEAD `e647a48`) and is preserved for the audit trail — it no longer describes the current working tree.

Repository root: `/Users/maxmedawar/LoopnetMCP-provider-sync`

Branch: `feature/stripe-skool-sync`

HEAD: `e647a480758ce71ae9d7357c1b4ee7e2dd3345b7`

Tracked binary diff SHA-256: `554268d78edf092b87e046e12a5ac031504e74afe6f21f705ee4ff44a8a02c76`

Last 10 commits:

```text
e647a48 (HEAD -> feature/stripe-skool-sync) feat(platform): add Stripe and Skool provider synchronization
7cbb1ac (feature/internal-admin-jv-apis) feat(platform): add internal admin and JV control APIs
49cab68 (feature/oauth-authoritative-mcp) feat(platform): make OAuth authoritative for remote MCP access
a87762c (feature/platform-entitlements-jv-api) feat: expose authenticated platform api
7958c1b fix: harden oauth session lifecycle
dd6921f feat: add subscription entitlement lifecycle
99da25e (feature/medawarcre-cloud-platform) feat: add tenant-scoped cloud platform foundation
c989dda (feature/tenant-access-control) feat: tenant-aware access control for hosted MCP (workspaces, profiles, territories)
aea1be0 (feature/cre-engine) docs: plain-English full-scope pitch for Cherif
349674d docs: checklist — TOTAL-COVERAGE PROGRAM COMPLETE
```

Uncommitted and untracked files after writing this packet:

```text
 M .claude/skills/internal-admin-jv-apis/SKILL.md
 M .claude/skills/stripe-skool-provider-sync/SKILL.md
 M .claude/specs/internal-admin-jv-apis.md
 M .claude/specs/stripe-skool-provider-sync.md
 M .env.example
 M docs/provider-sync-limitations.md
 M src/cre_mcp/platform/admin.py
 M src/cre_mcp/platform/api.py
 M src/cre_mcp/platform/authority.py
 M src/cre_mcp/platform/entitlements.py
 M src/cre_mcp/platform/models.py
 M src/cre_mcp/platform/providers/core.py
 M src/cre_mcp/platform/providers/reconciliation.py
 M src/cre_mcp/platform/providers/stripe.py
 M tests/platform/admin_helpers.py
 M tests/platform/test_admin_controls.py
 M tests/platform/test_api.py
 M tests/platform/test_authoritative_oauth.py
 M tests/platform/test_connection_lifecycle.py
 M tests/platform/test_entitlements.py
 M tests/platform/test_external_accounts.py
 M tests/platform/test_jv_control_scope.py
 M tests/platform/test_provider_containment.py
 M tests/platform/test_provider_reconciliation.py
 M tests/platform/test_provider_security_repairs.py
 M tests/platform/test_provider_sync_migrations.py
 M tests/platform/test_provider_webhooks.py
 M tests/test_config.py
 M tests/test_hosting.py
?? HANDOFF.md
?? tests/platform/test_provider_final_audit_repairs.py
?? tests/platform/test_provider_replay_receipt_bindings.py
```

Staged files: none. `git diff --cached --name-status` produced no output.

Stashes: none. `git stash list` produced no output.

Tracked diff stat from `git diff --stat`:

```text
 .claude/skills/internal-admin-jv-apis/SKILL.md     |    5 +-
 .claude/skills/stripe-skool-provider-sync/SKILL.md |   80 +++++-
 .claude/specs/internal-admin-jv-apis.md            |   22 +-
 .claude/specs/stripe-skool-provider-sync.md        |  150 +++++++++--
 .env.example                                       |   15 ++
 docs/provider-sync-limitations.md                  |   11 +-
 src/cre_mcp/platform/admin.py                      |   91 +++++--
 src/cre_mcp/platform/api.py                        |   12 +-
 src/cre_mcp/platform/authority.py                  |   10 +-
 src/cre_mcp/platform/entitlements.py               | 2050 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++--------------------------
 src/cre_mcp/platform/models.py                     |    1 +
 src/cre_mcp/platform/providers/core.py             |  676 +++++++++++++++++++++++++++++++++++++++-------
 src/cre_mcp/platform/providers/reconciliation.py   |    4 +-
 src/cre_mcp/platform/providers/stripe.py           |   11 +
 tests/platform/admin_helpers.py                    |    6 +
 tests/platform/test_admin_controls.py              |    2 +
 tests/platform/test_api.py                         |    5 +
 tests/platform/test_authoritative_oauth.py         |    6 +
 tests/platform/test_connection_lifecycle.py        |    2 +
 tests/platform/test_entitlements.py                |   87 +++++-
 tests/platform/test_external_accounts.py           |   58 +++-
 tests/platform/test_jv_control_scope.py            |    2 +
 tests/platform/test_provider_containment.py        |   42 ++-
 tests/platform/test_provider_reconciliation.py     |  129 ++++++++-
 tests/platform/test_provider_security_repairs.py   |   26 +-
 tests/platform/test_provider_sync_migrations.py    | 1789 +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++-
 tests/platform/test_provider_webhooks.py           |   10 +-
 tests/test_config.py                               |   19 ++
 tests/test_hosting.py                              |    2 +
 29 files changed, 4750 insertions(+), 573 deletions(-)
```

`git diff --stat` does not include the two untracked test files or this untracked handoff file.

Test command was selected from `pyproject.toml`, which sets `testpaths = ["tests"]` and declares pytest in the `dev` extra:

```text
$ TMPDIR=/tmp/medawarcre-handoff.da9OZo PYTHONPATH=src /Users/maxmedawar/LoopnetMCP/.venv/bin/python -m pytest -q
................................................................................................................................ [ 10%]
................................................................................................................................ [ 21%]
................................................................................................................................ [ 32%]
................................................................................................................................ [ 43%]
................................................................................................................................ [ 54%]
................................................................................................................................ [ 65%]
................................................................................................................................ [ 75%]
................................................................................................................................ [ 86%]
................................................................................................................................ [ 97%]
..........................................                                                                                       [100%]
warnings summary:
/Users/maxmedawar/LoopnetMCP/.venv/lib/python3.11/site-packages/fastmcp/server/auth/providers/jwt.py:10: AuthlibDeprecationWarning: authlib.jose module is deprecated, please use joserfc instead.
1770 passed, 1 warning in 54.97s
$ echo $?
0
```

Build commands were selected from the setuptools build backend in `pyproject.toml` and the repository skill/spec compile gate:

```text
$ PYTHONPYCACHEPREFIX=/tmp/medawarcre-handoff.da9OZo/pycache /Users/maxmedawar/LoopnetMCP/.venv/bin/python -m compileall -q src
$ echo $?
0

$ TMPDIR=/tmp/medawarcre-handoff.da9OZo /Users/maxmedawar/LoopnetMCP/.venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/medawarcre-handoff.da9OZo/dist .
Processing /Users/maxmedawar/LoopnetMCP-provider-sync
Preparing metadata (pyproject.toml) ... done
Building wheel for cre-mcp (pyproject.toml) ... done
Created wheel for cre-mcp: filename=cre_mcp-0.1.0-py3-none-any.whl size=1226484 sha256=3e56e0bcb613b63945db5fee583e20d08a313e1513a38b2e291b888f4850ee3a
Successfully built cre-mcp
```

# 4. SESSION ACCESS

Current `tmux ls` output:

```text
ccm-handoff-write-20260730: 1 windows (created Wed Jul 29 21:51:29 2026)
```

Current complete pane output:

```text
ccm-handoff-write-20260730:0.0 | tmux | /Users/maxmedawar/LoopnetMCP-provider-sync
```

Attach or reattach after a disconnect:

```bash
tmux attach -t ccm-handoff-write-20260730
```

The pane is the handoff collection shell in `/Users/maxmedawar/LoopnetMCP-provider-sync`. The command field was `tmux` while the exact pane-list command was running. No Claude, Codex, or project-server tmux pane exists in the final live tmux list.

Current listeners from `lsof -i -P -n | grep LISTEN`:

```text
ControlCe  455 maxmedawar    9u  IPv4  TCP *:7000 (LISTEN)
ControlCe  455 maxmedawar   10u  IPv6  TCP *:7000 (LISTEN)
ControlCe  455 maxmedawar   11u  IPv4  TCP *:5000 (LISTEN)
ControlCe  455 maxmedawar   12u  IPv6  TCP *:5000 (LISTEN)
python3.1  671 maxmedawar    4u  IPv4  TCP *:8787 (LISTEN)
node       679 maxmedawar   14u  IPv4  TCP 127.0.0.1:8788 (LISTEN)
cloudflar  698 maxmedawar   12u  IPv4  TCP 127.0.0.1:20241 (LISTEN)
Spotify    840 maxmedawar   76u  IPv4  TCP 127.0.0.1:7768 (LISTEN)
Spotify    840 maxmedawar   95u  IPv4  TCP *:57621 (LISTEN)
Spotify    840 maxmedawar  106u  IPv4  TCP *:49303 (LISTEN)
lghub_age  950 maxmedawar   29u  IPv4  TCP 127.0.0.1:9010 (LISTEN)
Ollama    1063 maxmedawar    4u  IPv4  TCP 127.0.0.1:49375 (LISTEN)
ollama    1080 maxmedawar    3u  IPv4  TCP 127.0.0.1:11434 (LISTEN)
app_inkwe 1359 maxmedawar   16u  IPv4  TCP 127.0.0.1:49683 (LISTEN)
```

Port `8000` is not listening. No current listener is verified as required for this repository task; necessity is UNKNOWN. Do not kill unrelated listeners.

# 5. NEXT ACTION

The prior next action (obtain an explicit fresh independent Claude-b verdict) is **done**: APPROVE, evidence in "2A. FINAL SECURITY CERTIFICATION". The reviewed tree is now committed (`f36ef46`) and the branch matches `fork/feature/stripe-skool-sync`, both observed as already-done rather than performed here.

Remaining before this can be called launch-ready:

1. Decide with Max whether to re-run the full pytest/compileall/wheel/`git diff --check` gate set against the new HEAD `f36ef46` (expected to be identical to the pre-commit results already recorded, since the bytes are unchanged, but not yet re-confirmed against this exact commit).
2. No merge to `main`/`origin` and no deploy has happened — that decision, plus timing, is Max's to make.
3. The Skool production blocker is untouched by this repair: production enablement still needs a trustworthy restrictive/current-state source integrated end to end before it can be turned on.

# 6. DEAD ENDS

- The independent Claude-b audit did not finish. Its pane showed `T7 is fully clean`, then admitted the T6 fixture did not create real ambiguity, then ended with `API Error: Server error mid-response.` It produced no approval. Do not cite it as a completed audit. **Resolved:** a subsequent fresh independent Claude-b session completed the full protocol, including a genuine two-candidate ambiguity probe (see "2A. FINAL SECURITY CERTIFICATION"), and returned an explicit APPROVE.
- The original replay audit reproduced three failures before V5: poisoned unknown selector to operator, Local Scout to Full Operator, and paid-through extension to 2036. Those old failures are evidence for the fixed attack surface, not permission to revert to the earlier V4 diff hash.
- The old audit and builder panes disappeared during a Tandem gateway timeout. Final live `tmux ls` contains only `ccm-handoff-write-20260730`. Cause: UNKNOWN. Do not try to attach to vanished pane names.
- The previously running project HTTP server was PID `2370` from `/Users/maxmedawar/LoopnetMCP`, but the final listener check has no port `8000`. Cause: UNKNOWN. Do not claim the server is protected or alive until a fresh command proves it.
- System `python3` is Python `3.9.6`; `python3 -m pytest --version` failed with `No module named pytest`, and `python3 -m build --version` failed with `No module named build`. Use `/Users/maxmedawar/LoopnetMCP/.venv/bin/python`.
- The first venv pytest probe failed before collection with `FileNotFoundError: No usable temporary directory found`; `df` then showed only `116Mi` free. A manually created `/tmp/medawarcre-handoff.da9OZo` allowed the suite to pass. Final `df` later showed `35Gi` free. The state change cause is UNKNOWN; always create and verify a fresh temp directory.
- `/Users/maxmedawar/LoopnetMCP/.venv/bin/python -c 'import cre_mcp; print(cre_mcp.__file__)'` resolves to `/Users/maxmedawar/LoopnetMCP/src/cre_mcp/__init__.py`. Running tests without `PYTHONPATH=src` can test the original checkout instead of this worktree.
- `python -m build` is unavailable in the shared venv. The verified package build path is `pip wheel --no-deps --no-build-isolation`; the verified static build gate is `compileall`.
- `git diff --stat` omits untracked files. The two untracked regression files must be included in review and eventual commit scope.

# 7. LANDMINES

- This is a linked Git worktree. `.git` contains `gitdir: /Users/maxmedawar/LoopnetMCP/.git/worktrees/LoopnetMCP-provider-sync`. Do not reset, clean, or switch the original checkout while this worktree is dirty.
- The current tracked diff is large: 29 files, 4,750 insertions, and 573 deletions, plus two untracked regression files and this handoff. Review by invariant and test, not by filename count alone.
- `src/cre_mcp/platform/entitlements.py:114-141` defines entitlement input hashing; `:1648-1855` owns V5 schema, triggers, and write-once rules; `:2424-2598` owns plan/profile binding and compatibility writes. These areas are coupled.
- `src/cre_mcp/platform/providers/core.py:1298-1845` contains receipt mismatch, ingestion, replay, and legacy quarantine paths. Mutable normalized JSON may remain writable evidence but must never choose authority.
- V5 plan and profile are a paired write-once binding. Do not permit only one field, NULL-to-value rebinding after the first bind, or selector-driven migration authority.
- Positive legacy receipts that cannot be proven must stay quarantined. Do not make legacy migration permissive to improve compatibility.
- The Skool source limitation is still explicit: production enablement remains blocked until a trustworthy restrictive and current-state source is integrated end to end.
- Port `8000` is absent in the final listener list. Any test or audit that assumes a running HTTP server will fail or may accidentally start a second server in the wrong checkout.
- The only full-suite warning was the third-party FastMCP/Authlib deprecation. Do not hide new warnings under that known warning.

# 8. NEEDED FROM MAX

Nothing is needed to close out the security certification itself (verdict: APPROVE, recorded in section 2A). Two decisions remain his and his alone, both already flagged in section 5:
- Whether/when to merge `feature/stripe-skool-sync` toward `main`/`origin` and deploy.
- What "trustworthy restrictive/current-state source" would satisfy the Skool production blocker, and when to pursue it.

# 9. FILE MAP

- `.claude/skills/internal-admin-jv-apis/SKILL.md` — internal-admin/JV implementation and verification contract.
- `.claude/skills/stripe-skool-provider-sync/SKILL.md` — provider-sync invariants, V5 replay binding contract, and production blockers.
- `.claude/specs/internal-admin-jv-apis.md` — internal admin and JV API design specification.
- `.claude/specs/stripe-skool-provider-sync.md` — provider synchronization, migration, replay, and verification specification.
- `.env.example` — documented provider configuration environment variables.
- `docs/provider-sync-limitations.md` — known provider and launch limitations.
- `pyproject.toml` — setuptools build backend, dependencies, and pytest `tests/` configuration.
- `src/cre_mcp/platform/admin.py` — internal admin provider/account control surface.
- `src/cre_mcp/platform/api.py` — platform API routes and response handling.
- `src/cre_mcp/platform/authority.py` — effective authority calculation.
- `src/cre_mcp/platform/entitlements.py` — entitlement schema, migrations, grant projection, V5 receipt bindings, and legacy policy.
- `src/cre_mcp/platform/models.py` — platform data models.
- `src/cre_mcp/platform/providers/core.py` — provider ingestion, event journal, replay, quarantine, and binding validation.
- `src/cre_mcp/platform/providers/reconciliation.py` — provider reconciliation behavior.
- `src/cre_mcp/platform/providers/stripe.py` — Stripe event normalization and trusted period handling.
- `tests/platform/admin_helpers.py` — shared admin test helpers.
- `tests/platform/test_admin_controls.py` — admin control regression coverage.
- `tests/platform/test_api.py` — API regression coverage.
- `tests/platform/test_authoritative_oauth.py` — OAuth authority-loss coverage.
- `tests/platform/test_connection_lifecycle.py` — connection lifecycle coverage.
- `tests/platform/test_entitlements.py` — entitlement and grant-scope coverage.
- `tests/platform/test_external_accounts.py` — provider-neutral and synchronized account-mapping coverage.
- `tests/platform/test_jv_control_scope.py` — JV scope coverage.
- `tests/platform/test_provider_containment.py` — provider ownership and containment coverage.
- `tests/platform/test_provider_final_audit_repairs.py` — untracked final-audit security regressions.
- `tests/platform/test_provider_reconciliation.py` — reconciliation and concurrency coverage.
- `tests/platform/test_provider_replay_receipt_bindings.py` — untracked V4/V5 adversarial replay-binding regressions.
- `tests/platform/test_provider_security_repairs.py` — provider security repair coverage.
- `tests/platform/test_provider_sync_migrations.py` — V2-V5 schema, migration, rollback, concurrency, and legacy-policy coverage.
- `tests/platform/test_provider_webhooks.py` — webhook behavior and security coverage.
- `tests/test_config.py` — provider configuration validation.
- `tests/test_hosting.py` — hosting boundary coverage.
- `HANDOFF.md` — this packet.

# 10. COPY-PASTE KICKOFF

```text
You are taking over the MedawarCRE Stripe/Skool provider-sync security repair with zero prior context.

Code lives at:
/Users/maxmedawar/LoopnetMCP-provider-sync

Current identity:
- branch: feature/stripe-skool-sync
- HEAD: e647a480758ce71ae9d7357c1b4ee7e2dd3345b7
- tracked binary diff SHA-256: 554268d78edf092b87e046e12a5ac031504e74afe6f21f705ee4ff44a8a02c76
- worktree: 29 modified tracked files, two untracked regression files, and HANDOFF.md
- staged files: none
- stashes: none
- current project HTTP server: not running; no port 8000 listener

Attach first:
tmux attach -t ccm-handoff-write-20260730

Read first, in order:
1. /Users/maxmedawar/LoopnetMCP-provider-sync/HANDOFF.md
2. /Users/maxmedawar/LoopnetMCP-provider-sync/.claude/skills/stripe-skool-provider-sync/SKILL.md
3. /Users/maxmedawar/LoopnetMCP-provider-sync/.claude/specs/stripe-skool-provider-sync.md
4. /Users/maxmedawar/LoopnetMCP-provider-sync/src/cre_mcp/platform/entitlements.py lines 114-141, 1648-1855, and 2424-2598
5. /Users/maxmedawar/LoopnetMCP-provider-sync/src/cre_mcp/platform/providers/core.py lines 1298-1845
6. /Users/maxmedawar/LoopnetMCP-provider-sync/tests/platform/test_provider_replay_receipt_bindings.py
7. /Users/maxmedawar/LoopnetMCP-provider-sync/tests/platform/test_provider_sync_migrations.py lines 1335-1970

Do first:
Verify HEAD and diff hash exactly. Then launch a fresh read-only Claude-b audit using CLAUDE_CONFIG_DIR=/Users/maxmedawar/.claude-b and /Users/maxmedawar/.local/bin/claude. The prior audit crashed with a server error and produced no verdict. Require an explicit APPROVE or REQUEST_CHANGES verdict against the exact current bytes. Do not edit, commit, merge, push, deploy, or start the HTTP server before that verdict.

If the audit requests changes, preserve the finding as a failing test first, make the smallest binding repair, and rerun the full suite with PYTHONPATH=src so this worktree—not /Users/maxmedawar/LoopnetMCP—is tested. Use a fresh verified temp directory. The current verified suite is 1,770 passing tests; compileall and pip wheel also pass.
```

PACKET VERIFIED
