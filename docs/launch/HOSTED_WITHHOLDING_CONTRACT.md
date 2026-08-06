# Hosted withholding correction contract

## Why this is a separate boundary

Fifteen customer capabilities are entitled and are counted in the locked 253
grouped actions. Before this correction they were also advertised by the hosted
grouped tools, while every hosted call failed.

The criterion is routing, not any particular store class. `DealStore.__init__`
raises `AdmittedRequestUnavailable("deal persistence unavailable")` whenever
hosted repositories are bound or the context is untrusted. A capability is
therefore:

- **alive on hosted** when it goes through `get_deal_store()` or
  `get_search_store()`, which return `hosted.require(...)` — the certified
  hosted port — when one is bound;
- **dead on hosted** when it reaches a *direct* `DealStore(...)` construction,
  because that constructor refuses every hosted context unconditionally.

The dead capabilities, by construction path:

| Capability | Group | Direct construction reached |
| --- | --- | --- |
| `counterparty_dossier` | `cre_contact` | `cre_mcp.relations` |
| `meeting_briefing` | `cre_contact` | `cre_mcp.relations` |
| `who_to_call` | `cre_contact` | `cre_mcp.relations` |
| `flag_unattended` | `cre_pipeline` | `cre_mcp.command._db` |
| `morning_queue` | `cre_pipeline` | `cre_mcp.command._db` |
| `overnight_changes` | `cre_pipeline` | `cre_mcp.command._db` |
| `record_listing_snapshot` | `cre_pipeline` | `cre_mcp.command._db` |
| `stale_listing_signals` | `cre_pipeline` | `cre_mcp.command._db` |
| `data_room_index` | `cre_close` | `dataroom.index.DataRoomStore` |
| `init_data_room` | `cre_close` | `dataroom.index.DataRoomStore` |
| `update_data_room_item` | `cre_close` | `dataroom.index.DataRoomStore` |
| `closing_runway` | `cre_close` | `dataroom.dependencies.DependencyStore` |
| `init_transaction_plan` | `cre_close` | `dataroom.dependencies.DependencyStore` |
| `transaction_critical_path` | `cre_close` | `dataroom.dependencies.DependencyStore` |
| `closing_day_runbook` | `cre_close` | same, via the `cre_mcp.dataroom` re-export |

Advertising an action that always fails is a surface defect: it is visible in
`tools/list`, it is billable attention, and it teaches a customer's agent to
retry a call that can never succeed.

### On the count

The prior inventory recorded seven. It was incomplete, and so was the
fourteen-capability set that replaced it: the derivation behind that set did not
resolve package `__init__.py` re-exports, which hid `closing_day_runbook`
(`closing.tools` → `closing.command_center` → the `cre_mcp.dataroom` re-export
of `dependencies.closing_runway` → `DependencyStore` → `DealStore`).

Two things must not be conflated: how the set was *established*, and what the
test suite *guards*.

**Established by runtime evidence.** Independent reviewers in successive rounds
bound a real `HostedRequestRepositories` — under which a direct `DealStore(...)`
raises while `get_deal_store()` returns the port — and executed every grouped
action. Each such repositories-bound run reproduced exactly these fifteen, with
no sixteenth and none of the fifteen alive. One also re-seeded on `TruthStore`,
`PlatformRepository`, and `EntitlementStore` and found no additional dead
grouped action. Which rounds those were is not restated here: the review-history
table in the launch ledger is the record, and earlier drafts of this paragraph
twice attributed the work to the wrong rounds. That re-seed
surfaces `trace_input_lineage` under a path-insensitive reading: it does
construct `TruthStore` directly, but only on its explicit `db_path` branch,
while the default hosted path routes through `get_truth_store()`. It is alive
on hosted and correctly not withheld.

**Guarded by a static drift detector.**
`test_withheld_set_equals_the_capabilities_that_reach_a_direct_deal_store`
derives the set by AST reachability
and asserts equality with `HOSTED_WITHHELD_CAPABILITIES`, so any source change
that moves the derived set turns the pin red in either direction. It is a
tripwire, not a proof: static resolution is unsound both ways, and a red result
means "the source moved, go look", never "add whatever it now reports".

A per-capability runtime probe additionally confirms each withheld capability
fails closed. That probe binds no repositories, so `get_deal_store()` also
raises on an untrusted context and it cannot by itself tell dead from alive; it
is deliberately not claimed as proof of deadness.

## Narrow contract

Withhold the fifteen from the hosted surface only:

- they are absent from every hosted grouped tool's advertised action list, so
  they never appear in `tools/list`;
- `CustomerSurfaceCatalog.resolve` refuses them, so both the hosted dispatcher
  and the middleware adapter `resolve_surface_call` deny a direct call with the
  existing fail-closed `grouped action is not available` error;
- hosted tool visibility is computed from the reachable actions, so a grouped
  tool disappears for a profile whose last reachable action is withheld.

## Explicit non-scope

This correction does not:

- change `allowed_profiles` for any capability. Emptying them breaks
  `test_matrix_entries_are_well_formed_and_machine_readable`, which requires at
  least one profile per capability, and breaks the tests that exercise these
  capabilities through `full_operator`;
- reclassify anything as internal-only. Internal-only is keyed by module
  (`_INTERNAL_MODULE_REASONS`), and for `cre_mcp.relations.tools` and
  `cre_mcp.closing.tools` the module also holds working capabilities, so a
  module-keyed reclassification would hide those too. For
  `cre_mcp.command.tools` (5 of 5 withheld) and `cre_mcp.dataroom.tools` (6 of
  6 withheld) that obstacle does not exist; those eleven are left grouped
  because reclassifying them would move the locked grouped-action count of 253
  and the internal-only count of 21, which is the actual reason and a separate
  reviewed change;
- move the classification counts. Internal capabilities stay 274, grouped
  actions stay 253, internal-only stays 21.
- change trusted local stdio. `AccessEngine._gate` allows a trusted context
  before the profile check, and the stdio path never installs the catalog;
- certify any store, or implement privacy or scheduled-job persistence.

## The JV surface moves from 12 to 11, by founder decision

Withholding is designed not to move the customer grouped-tool counts, and it
does not for Local 8, National 10, or Full Operator 20. It does move
`jv_partner` from 12 to 11, because **all four** of `cre_close`'s JV-entitled
actions — `closing_day_runbook`, `closing_runway`, `data_room_index`, and
`transaction_critical_path` — are dead. `cre_close` has therefore never worked
for `jv_partner`, and the locked count of 12 was already overstating the working
JV surface by one tool.

Presented with the choice between publishing 11 working tools and keeping the
count at 12 by continuing to advertise a capability that fails on every call,
the founder chose 11 on 2026-08-06. The mechanism is `visible_names` and
`is_visible` computing from `hosted_capability_ids`: a tool that loses its last reachable action for one
profile stops being listed for that profile, pinned by
`test_withholding_a_profiles_last_action_hides_that_tool_for_it` and the two
count assertions. This is NOT the empty-tool guard, which rejects only a
withholding that would empty a tool for every profile at once.

## Reversal condition

An entry is removed from `HOSTED_WITHHELD_CAPABILITIES` only after that
capability routes through a certified hosted port — that is, once it no longer
reaches a direct `DealStore` construction — under the same review ceremony as
any other surface change. Certifying a store class is not by itself sufficient,
because the capability must actually be re-routed to it.

## Fail-closed guards

Three guards make a careless future edit fail when `cre_mcp.surface.catalog` is
imported, which happens while building the hosted server. `import
cre_mcp.server` itself still succeeds — the surface is imported lazily — so a
guard violation stops hosted from starting while leaving trusted local stdio
working. That split is intended:

- a withheld capability that is not a grouped customer action is rejected, so
  withholding can never be used to quietly hide an internal-only capability;
- a withheld capability that is a legacy tool id is rejected, because the
  legacy reconciliation would still report it as reachable;
- a withheld set that would empty a grouped tool is rejected, so a tool can
  never vanish for *every* profile without review. A tool may still stop being
  listed for one profile whose last reachable action is withheld; that is
  intended and is pinned by its own test.

The static drift detector replaced a weaker per-module guard that review showed
was evaded by aliased imports, by attribute calls, and by any module named
`store.py`. It resolves import aliases, package `__init__` re-exports, attribute
calls qualified by a module alias, and every method of a class — so a class is
marked dead when ANY method reaches a dead callee, not only `__init__`. Each was
demonstrated by mutation.

Its unsoundness is stated rather than implied away, and the list is known-so-far
rather than exhaustive. It can MISS: a subclass of `DealStore`; the class bound
to a module-level name and called through it; a construction at module scope;
a call whose qualifier is not a known module alias when the attribute name is
not bound in that module; and any callee that is itself a `Call` or `Subscript`
node, which covers `getattr(mod, "DealStore")()` and dict dispatch `_D["k"]()`.
A fully-dotted `cre_mcp.deals.store.DealStore()` after a plain dotted import is
missed as well, but by the module-scope fallback above rather than that family:
its callee is an `Attribute` whose value is itself an `Attribute`. It can OVER-MARK: the same non-module-qualifier
fallback matches by attribute name, so an unrelated instance method sharing a
name bound in the module taints its caller, and whole-class walking taints every
constructor of a class any of whose methods is dead. None of these is exercised
by shipping code — there are nine `DealStore` construction sites, all bare-name,
seven in module-level functions and two in `__init__`, and no subclass — which
is why the derived set matches the runtime-established set today.

Promoting the repositories-bound runtime derivation to a second pin would remove
every one of those blind spots and is the recommended follow-up; it is left out
of this narrow correction deliberately, as new fixture code carries its own
review burden.

## Evidence required before commit

- a RED test before implementation;
- per-capability pins that the action is unadvertised, unresolvable through the
  catalog and the middleware adapter, and denied end to end through a live
  client for every profile that entitles it;
- a set-equality drift pin between the withheld set and the statically derived
  set, which turns red in both directions on any source change that moves it;
- a per-capability pin that each withheld capability fails closed under an
  untrusted context, stated without claiming it distinguishes dead from alive;
- pins that entitlement, grouped classification, and every locked count are
  unchanged;
- pins for all three fail-closed guards and for profile-specific visibility;
- mutation evidence that every new pin fails when its behaviour is deleted.
  The alias-depth assertion in the derivation is excluded: it is a defensive
  tripwire that cannot fire on this tree (deepest real chain is 2 hops), so
  deleting it changes nothing;
  including the end-to-end denial pin, whose internal-server fixture registers
  each withheld capability so the denial cannot pass by fall-through;
- full repository suite, compile, diff, changed-content credential, package,
  surface-count, catalog-fingerprint, and listener gates;
- two fresh independent read-only reviews of one unchanged candidate.
