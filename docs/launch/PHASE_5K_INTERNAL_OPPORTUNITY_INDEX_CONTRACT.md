# Phase 5K internal combined opportunity index contract

Status: implementation checkpoint under test, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `93e3bbb` (the Phase 5J correction; see "Base state this phase assumes")

## Founder decision this implements

Internal staff may work from one combined, deduplicated opportunity list drawn
from every tenant workspace. Customers may not. Recorded in the frozen founder
decisions above the issue ledger and restated 2026-08-06:

- The index is internal-only. No customer route, no customer MCP tool, and no
  customer browser surface may read it, and no capability may be added that
  does.
- Aggregation happens on the server. The console never reaches across tenant
  databases and never assembles the list client-side.
- Tenant boundaries survive aggregation. An entry is a set of per-workspace
  observations, not a merged record whose origin has been erased.
- Global cross-customer model learning stays disabled. This index feeds human
  review, not training.

## Why the index is not a hosted domain repository

Every customer-reachable persistence port in this program is a field on
`HostedRequestRepositories`, bound to one fresh `AdmissionOutcome` for the
duration of one tool call. The index deliberately is not.

`HostedRequestRepositories` is reachable from tool code through
`current_hosted_request_repositories()`. Anything on it is one capability away
from a customer. So the index is built on the separate internal path that
already exists and is already proven: an `admin` runtime `PostgresDatabase` plus
`AuthorityContext.internal(actor, role, reason)`.

That path fails closed in two independent ways that a single mistake cannot open
together:

1. **Grant.** `medawarcre_app` holds no privilege of any kind on
   `internal_opportunities`, `internal_opportunity_sources`, or the tables this
   phase adds. A customer-role statement raises `InsufficientPrivilege` before
   row-level security is consulted.
2. **Runtime mode.** `PostgresDatabase.connection()` refuses internal authority
   on an `app` pool and refuses a missing internal role on an `admin` pool, so
   the customer pool cannot borrow staff authority even with a correct role
   string.

Row-level security is the third layer, not the first: `internal_authorized()`
requires a live, active, exactly matching `staff_roles` row plus a non-blank
`app.audit_reason`, and `internal_can_mutate()` narrows writes to `owner` and
`admin`.

## Required behaviour

### Retention — what an entry keeps

Every index entry retains, per contributing workspace, all of:

1. source workspace,
2. source user,
3. source saved search and source deal, whichever produced the observation,
4. property identity, normalized and stored alongside the raw observed values,
5. first-observed and last-observed timestamps, plus row create/update times,
6. score and score version,
7. stage,
8. outcome, where the tenant has recorded one,
9. provenance, as a structured object naming the exact tenant row it came from,
10. duplicate relationships, both within an entry and between entries,
11. access classification (`private`, `licensed`, `public`),
12. review history.

An entry that cannot carry all of the above for a contributing observation is
rejected. Partial admission is not permitted, because a missing source user or a
missing access class is exactly what turns an audited internal read into an
unattributable one.

Rejected means **rejected and counted** — one observation declined, the rest of
that workspace admitted. It does not mean the batch aborts. Ingestion runs one
transaction per workspace, so any single-row condition the repository lets reach
a database constraint takes down every other observation in that workspace, on
every retry, and rolls back the audit row that would have recorded the attempt.
Every tenant-supplied value must therefore be bounded at the boundary, before
SQL sees it, and every failed ingest must still leave an audit row saying staff
tried.

### Deduplication without provenance loss

The same property observed in two workspaces produces **one**
`internal_opportunities` row and **two** `internal_opportunity_sources` rows.
Deduplication is by `canonical_key`, derived server-side from normalized
property identity. Merging never overwrites, averages, or discards a
contributing workspace's score, stage, or outcome.

Two canonical entries later found to be the same property are linked, not
collapsed: the superseded entry moves to `status = 'merged'` and records
`merged_into_opportunity_id`.

What survives on the superseded entry is the **link** and its review history —
not its source rows. An earlier version of this line promised the source rows
stayed attached "so the history of the mistake stays inspectable", and that is
false: the next ordinary re-ingest re-binds them to the canonical head, because
a live observation belongs where staff can see it, and the orphan trigger then
archives the emptied entry. The merge itself is inspectable through the retained
link, the review history, and the `staff_audit_log` row that records who merged
what and why. That is the honest guarantee, and it is the one the code makes.

A merge target must itself be canonical, an entry that is itself a merge target
cannot be merged onward, and a merge can be undone. All three are requirements
rather than implementation details. Without the first, A→B followed by B→A
removed both entries from every staff listing permanently and captured the future
observations of workspaces that had nothing to do with either. Without the
second, C→A followed by A→B built a chain whose head was itself merged, so "what
is C a duplicate of?" had no answer a human could act on. Without the third, a
wrong duplicate call had no remedy at all. "Linked, not collapsed" only means
something if a human can still reach both entries and reverse the link.

These are database guarantees, not repository conventions: the target check must
lock the target, because two concurrent merges that each read the other as
canonical will otherwise both commit and build the cycle anyway.

An observation of a merged property files under the **canonical** entry. Staff
have said the two are the same property, so a later observation of the
superseded one belongs where staff can see it. Filing it under the superseded
entry made a live tenant record invisible: it appeared in no default listing and
matched no facet filter, while the ingest reported it admitted.

Merging and unmerging preserve `suppressed`. Suppression is the only mechanism
staff have for hiding an entry, and a merge round-trip that silently cleared it
would make the hiding unreliable in exactly the case someone bothered to use it.

### Conflicting outcomes are reported, not resolved

When contributing workspaces disagree — one passed, one closed; scores that
differ beyond a fixed tolerance; incompatible stages — the entry is returned
with the conflict described and every side attributed. The index states that the
workspaces disagree and who holds which position. It does not pick a winner.

**Between workspaces, and only between workspaces.** A conflict requires two
workspaces whose *views differ* — not merely two workspaces and two values.
Counting them separately is a different question, and answering the easier one
reported two tenants who each saved the building from the same two providers,
and therefore held identical `{office, retail}` views, as being in three
cross-tenant conflicts. Views are compared as sets; for scores, as ranges,
where two workspaces agree when both ends of their ranges coincide within the
tolerance. One tenant saving the same building from
two providers is an ordinary path — `deals` is unique on `(workspace_id, source,
source_record_id)` — and reporting that tenant as disagreeing with itself made
the report say something false about the thing this section is for. A reviewer
measured it naming the same workspace and the same user on both sides.

**A tenant contradicting itself is therefore not surfaced.** That is a real
data-quality signal and this phase does not report it. Stated as a limit rather
than left to be inferred from the absence of a conflict.

Two consequences of that limit, both measured and neither obvious. A tenant's
self-contradiction is invisible when it is alone **and** must stay invisible
when a second workspace contributes — an earlier repair let it reappear,
relabelled as cross-tenant, the moment anyone else touched the property. And
conflict *positions* are per-observation, not per-workspace: a genuine
cross-workspace conflict can legitimately show the same workspace on two of its
sides, because that workspace holds two values. The conflict is between the
workspaces; the positions show every observation behind it.

One consequence worth naming: an entry's single derived `property_type` is
`None` whenever its observations do not agree on one value, including when the
disagreement is inside a single workspace. The conflict report and the derived
label answer slightly different questions, and this is the narrower of the two.

### Staff access

Every read and every mutation:

- requires a live internal role, re-derived from the database on each call;
- requires a reason code from a fixed vocabulary and a free-text reason;
- is timestamped;
- writes exactly one `staff_audit_log` row in the same transaction as the work
  it describes, recording actor, role, reason, reason code, workspace, object
  type, object id, action, and result.

A read whose audit row cannot be written does not return data. Mutations are
`owner`/`admin` only. Reviews are append-only and enforced by trigger, not by
convention.

**Refusals are audited too, and this needs saying separately because the
transaction cannot carry them.** An action refused for lack of role, or against
an object that does not exist, writes its row on a fresh connection: the
transaction that would have carried it is being rolled back precisely because
the action did not happen. Without that, a `read_only_analyst` attempting four
mutations left no trace at all, and staff could probe for the existence of any
entry untracked. An attempted privilege escalation is the event you least want
missing from the log, and `denied` is in the result vocabulary for it.

**With one exception this clause must carry, because the design cannot close
it.** An actor who *lies about their role*, or holds no `staff_roles` row at
all, cannot have their denial recorded: the audit table's own row-level security
requires a live staff role, so the refusal row is itself refused. The honest
attempt is logged and the dishonest one is not. Nothing leaks — every such path
returns zero rows — but the log is silent, and a reviewer was right that the
unqualified sentence promised more than the code can do. Closing it needs an
audit path that does not depend on the actor's own authority, which is the
privacy and retention phase's problem, not this one's.

Concurrency is part of this, not an implementation detail. Ingestion runs one
transaction per workspace, so any lock order the index can choose must be a
total order — otherwise one tenant's ordinary address correction aborts an
unrelated tenant's entire ingest, which reviewers measured at 29 failures in 30
attempts. Where a cycle involves locks this phase does not control, ingestion
retries rather than surfacing a transient deadlock as a staff-visible failure.

### Query surface

- Keyset pagination on a stable, total order. No `OFFSET`.
- Filters: market, property type, score range, stage, outcome, source user,
  source workspace. Every one of them except market answers from the
  **per-workspace observation**, not from the shared entry: the shared row is
  written by whichever workspace observed the property first, so filtering it
  hid a second workspace's declared property type on exactly the structure built
  to combine tenants. Market is the one exception, because it is derived from
  the normalized key every contributor agrees on by construction.
- Where workspaces disagree on a filterable attribute, the disagreement is
  reported as a conflict with both sides named. An entry's own label never
  settles it — and where an entry exposes a single value for such an attribute,
  that value is `None` when the workspaces disagree, because a label that
  silently picks one side is the smoothing this contract forbids two paragraphs
  above.
- A bounded maximum page size. An earlier version of this line also promised
  "a fixed cap on total scanned rows"; nothing implemented it, and a constant
  named `MAX_SCAN` sat unreferenced making it look implemented. Both are gone.
  What protects a large result set is keyset pagination on an indexed immutable
  order plus the page bound — not a scan cap.
- Filter arguments are validated before they reach SQL — both the name and the
  **value**. An unknown filter name is an error rather than a silently ignored
  argument, and a malformed value is a `ValueError` rather than a raw database
  error. An earlier version of this line said only "arguments", and the
  implementation read that as names alone: a field name is half an argument.
- A read filtered by a workspace that does not exist returns an empty page. It
  must not raise, and it must not distinguish an absent workspace from a real
  one — the audit row's own foreign key made that distinction observable, which
  turned a staff read into an existence oracle.

### Deletion and privacy

The index is derived data, so tenant deletion propagates into it rather than
outliving it:

- Deleting the originating search result or deal removes the source row that
  cited it.
- Deleting a workspace removes its source rows — *if the workspace can be
  deleted at all*. An earlier version of this line stated that without the
  condition, and a reviewer showed the condition is usually false: one ingest
  writes a `staff_audit_log` row whose workspace foreign key does not cascade,
  and those rows are append-only, so the workspace delete is refused and the
  refusal cannot be cleared. An ordinary customer tool call does the same
  through `access_decision_audit`. This is a pre-existing conflict between audit
  immutability and tenant erasure that the index widens rather than creates, and
  resolving it belongs to the privacy and retention phase.
- An entry whose last source row is gone becomes `archived` and stops appearing
  in default listings — unless staff have `suppressed` it, in which case it stays
  `suppressed` and still does not appear. Suppression is a deliberate staff
  decision and outlives the loss of its sources; the operative half of this
  clause, that the entry leaves default listings, holds either way. A reviewer
  measured the exception and was right that the sentence did not carry it.
- The shared entry carries exactly one tenant-supplied value: the **normalized
  street address**, in `property_identity` and in the derived label. That is
  stated plainly because two stronger versions of this line were both false.
  "No tenant free text" was false while `property_type` was refreshed onto the
  row. "No *column* that could hold it" was false the moment it was written,
  because `listing.address` is a column that does exist and was unbounded — a
  reviewer put 88,011 characters through it onto a cross-tenant row that stayed
  active and outlived that tenant's erasure.

  A property index has to record which property. So the requirement is not
  absence, it is: the address is **bounded** (120 characters — longer than any
  real US street address), normalized, rejected-and-counted when it exceeds
  that, and disclosed here as the thing that survives an erasure. Every other
  tenant value — property type, score, stage, outcome, the raw declared identity
  — lives only on source rows, which cascade away with the record that supplied
  them. Nothing else may be added to the shared entry, and "derived at read
  time" is the test for whether a new value belongs there.
- Review history survives, because it records what a named member of staff did
  and when, and references only the internal entry — never tenant content. One
  consequence to state plainly: an entry that has been reviewed cannot be
  deleted by any role, including `medawarcre_migration`, because the cascade
  reaches the append-only reject trigger. It can only be updated in place.

## Explicit non-scope

- No Operations Console UI. The console consumes this in the next phase; this
  phase ships the server-side index and its contract only.
- No scheduled or background ingestion. Ingestion is an explicit, reason-coded,
  audited internal call. Bounded scheduled jobs are their own later phase.
- No change to the capability matrix, the locked visible counts (Local 8,
  National 10, Full Operator 20, JV Partner 11), the 274 internal capabilities,
  the withheld fifteen, or any customer-facing behaviour.
- No cross-customer learning, no model training, no scoring changes. The index
  reads scores; it does not compute or revise them.
- No change to OAuth, admission, quota, territory, approval, source-rights, or
  lifecycle behaviour.
- No new dependency.

## What this contract does not claim

It does not claim staff have used the index. There is no console yet.

It does not claim the index is complete for any real tenant, because ingestion
is explicit and no production data exists.

It does not claim the deduplication key is correct for every property shape in
the world. It claims the key is derived only from normalized declared
identity fields, that two observations agreeing on that identity merge, and that
disagreement is preserved rather than smoothed — and it names the cases where a
human must decide, rather than guessing on their behalf.

## Base state this phase assumes

Branch `integration/cloud-platform-launch` at `93e3bbb`, clean worktree.

`5452be3` was red at the tip and its gate was mis-recorded; that is repaired in
its own commit — see the Phase 5J correction in `PROGRAM_STATUS.md` — which two
independent reviewers approved unchanged. This phase therefore starts from a
tree whose complete suite reproduces on a clean environment at `5,034 passed,
4 skipped`. No opportunity-index work was written against the broken tip.

## Why the dedup key reuses the territory authority

The index must decide when two workspaces are looking at the same property. The
access engine already decides where a property is, from the same declared
fields, using a pinned offline Census place/ZCTA/county authority that survived
seven audit rounds. Building a second normalizer would let "the same property"
drift from "where is this property" — two answers to adjacent questions, able to
disagree.

So the canonical key derives only from `cre_mcp.access.territory`'s
`normalize_city`, `normalize_state`, `normalize_zip` and the convergence checks
`city_zip_pair_is_authoritative` and `city_claim_is_unambiguous`, over the
capability-declared `address`, `city`, `state`, and `zip_code` fields — never
provider `raw`, never arbitrary nested mappings. An observation whose identity
does not resolve unambiguously is **rejected and counted**, not guessed.
