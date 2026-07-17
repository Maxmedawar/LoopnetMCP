# Tenant-Aware Access Control — MedawarCRE

Status: LOCKED (Max, 2026-07-16) — implementation may not drift from this spec.
Branch: `feature/tenant-access-control` (off `feature/cre-engine`).

## Goal

Multi-tenant access control for the hosted (HTTP) mode of the MedawarCRE MCP
server (`cre_mcp`, FastMCP 2.14.x, 274 registered tools), while the local
stdio mode keeps its current behavior through an explicit **trusted local
workspace** — the same enforcement code path, not a bypass.

## Non-negotiable constraints (from Max)

1. **Server-authoritative context.** Workspace, role/profile, plan, territory,
   and record ownership are resolved server-side only. They are never read
   from MCP tool arguments; client-supplied values for them are ignored and
   the attempt is auditable.
2. **Dual enforcement.** Permissions filter `list_tools` AND are re-checked on
   every `call_tool`.
3. **Cloud default-deny.** A tool with no capability-matrix entry is denied in
   cloud mode.
4. **Local trusted workspace.** Local stdio mode runs the same machinery with
   a designated trusted workspace; existing local behavior is preserved.
5. **Test-first.** Tests are written and failing before implementation.
   Entire existing suite passes before any commit.
6. **Preserve unrelated work.** Only files created/edited for this feature are
   staged; untracked docs/fixtures are never touched.

## Access profiles

| Profile | Scope | Territory-limited | Transaction actions | Notes |
|---|---|---|---|---|
| `local_scout` | Scouting/read tools | YES | none | Denied outside granted territories |
| `national_scout` | Scouting/read tools | no | none | Nationwide read/scout |
| `full_operator` | All classified tools | no | allowed, but **sensitive transaction actions require approval** | Approval is a server-side pending record |
| `jv_partner` | Scout + JV-shared records | YES | none beyond JV records | Record-ownership rules: sees only records owned by or shared with its workspace |

Inactive access: a workspace or grant marked inactive/suspended is denied
everything (list shows nothing, calls denied, audit event emitted).

## Tenant context resolution

- Hosted (HTTP): bearer/API key on the connection → server-side workspace
  registry lookup → `TenantContext { workspace_id, profile, plan, territories,
  active, display_name }`. Unknown/missing credential → no tools, all calls denied.
- Local (stdio): `TenantContext` for the trusted local workspace
  (`workspace_id="local"`, full trust, approvals auto-satisfied, no territory
  limits, no quotas). Selected only when transport is stdio or explicitly
  configured; cloud can never resolve to it via client input.
- Registry storage: server-side (config-file/SQLite backed), managed
  out-of-band; never mutable through client-supplied MCP arguments.

## Capability matrix (machine-readable)

One entry per registered tool (completeness enforced by test against
`register_all`):

```
ToolCapability {
  tool: str                      # registered tool name
  allowed_profiles: set[str]     # subset of the four profiles
  sensitive: bool                # sensitive transaction action → approval gate
  sensitive_params: list[str]    # params that make a call sensitive when set
  territory_params: list[str]    # args carrying location (e.g. "location") — checked for territory-limited profiles
  ownership_relevant: bool       # record-scoped tool → JV/workspace ownership filter applies
  quota: str | None              # quota bucket (per-plan daily limits)
  approval: str | None           # approval class, e.g. "transaction"
}
```

Authored as data (Python module `capabilities.py`, category defaults per tool
module + explicit per-tool overrides), exported/validated as JSON for
machine-readability. Unclassified in cloud = denied.

## Enforcement seam

FastMCP middleware (`fastmcp.server.middleware.Middleware`):

- `on_list_tools`: filter to tools allowed for the resolved context.
- `on_call_tool`: resolve context → active check → matrix lookup (default-deny
  in cloud) → profile check → territory check (parse territory params against
  granted territories: state codes / metro names / zips) → ownership check →
  quota check → approval gate (sensitive + not locally trusted → require
  server-recorded approval) → execute → audit event.
- Both hooks emit audit events: `{ts, workspace, tool, decision, reason}` to a
  server-side append-only audit log.

## Workspace-scoped data

DealStore / saved searches / scores / history gain a `workspace_id` dimension.
Existing local records migrate (or are adapted) to the trusted local
workspace losslessly. JV records carry ownership metadata to support
`jv_partner` visibility rules. (Store inventory: see Addendum A — filled from
codebase survey.)

## Approval flow (sensitive transaction actions)

1. `full_operator` calls a sensitive tool → engine records a pending approval
   `{id, workspace, tool, args_hash, ts}` and returns a structured
   `approval_required` response (not an exception smuggling data loss).
2. Approval is granted server-side (out-of-band admin action in the registry).
3. Retried call referencing the pending approval id (server verifies workspace
   + tool + args_hash match) proceeds and is audited.
4. Local trusted workspace: approvals auto-satisfied (current UX preserved).

## Test plan (write first; must fail before implementation)

`tests/access/`:
1. Profile matrix — each of the four profiles allowed/denied per category.
2. Workspace separation — records written under workspace A invisible to B.
3. Territory rules — local_scout/jv_partner denied outside granted territories
   (state, metro, zip forms); allowed inside.
4. Inactive access — inactive workspace/grant → empty tool list, denied calls.
5. JV records — jv_partner sees owned/shared records only.
6. Operator approvals — sensitive tool → approval_required; approved retry
   succeeds; mismatched retry denied.
7. Unknown tools — unclassified tool denied in cloud; matrix completeness test
   (every registered tool classified).
8. Audit events — allowed/denied/approval decisions all emit audit entries.
9. Local compatibility — stdio/trusted-local context: full tool list, no
   approval friction, existing stores keep working, existing suite green.
10. Server-authoritative context — args like `workspace_id`/`role`/`territory`
    in tool calls never override server context.
11. Dual enforcement — a tool absent from a tenant's filtered list is also
    denied at call time (list filtering alone is not the barrier).

## Agent roster (per agentic-engineering Phase 2)

- Lead/orchestration: this session (Claude Code main loop).
- Implementer A: access engine + middleware + capability matrix.
- Implementer B: workspace scoping of stores + migration/adapter.
- Reviewer (CONCURRENT): code-reviewer teammate auditing diffs as tasks land.
- Research (standby): store survey agent (already dispatched).
- QA: test suite authored first by main loop; full-suite run gates commit.

## Phases

1. RED: author `tests/access/` (all failing), plus matrix completeness test.
2. Capability matrix for all 274 tools (category defaults + overrides).
3. Engine + middleware + registry + audit log.
4. Store scoping + local migration/adapter.
5. GREEN: access suite passes; entire existing suite passes; concurrent
   reviewer findings addressed; final audit against this spec; commit.

## Addendum A — store inventory (from codebase survey)

- Single shared SQLite file: every store resolves
  `(config or CreConfig()).cache_db_path` (default `~/.cache/cre_mcp/cache.db`;
  Docker `/home/cremcp/.cache/cre_mcp/cache.db`). Stores: DealStore
  (`deals/store.py`), TruthStore (+ blob store at `db_path.parent/"documents"`),
  BookStore, LedgerStore, LeasingWatchStore, disposition, finops, relations,
  mlops, compliance, assetmgmt, pmops, construction, negotiation, dataroom,
  fund, command snapshots, leaseops, geo crosswalk, IRS SOI, HTTP cache.
- **Isolation strategy: per-workspace DB path.** Cloud workspace →
  `cache_db_path.parent / "workspaces" / <workspace_id> / "cache.db"` (blob
  store follows automatically). Trusted local workspace → the unchanged legacy
  `cache_db_path` — existing local records are preserved with no data
  rewrite (the adapter is the path mapping itself).
- **Leaks to close:**
  1. Hardcoded home paths bypassing config: `construction/draws.py:227`,
     `construction/tracking.py:73`, `pmops/turns.py:120` → must resolve via
     config/context.
  2. Module-level singletons binding one DB process-wide: `ledger/store.py`
     `get_ledger_store()/_STORE` holds tenant data → context-keyed. (Shared
     scraper/HTTP-cache/geo singletons hold public reference data only —
     acceptable shared, documented.)
  3. 62 registered tool signatures expose `db_path`/`watch_db_path` kwargs →
     cloud mode strips/denies client-supplied storage paths
     (server-authoritative); local trusted mode keeps them working.
- No existing auth, middleware, or per-request context anywhere; Cloudflare
  Access fronts the deployment today (DEPLOY.md).

## Addendum B — pinned API contract (tests are written against this)

Package `src/cre_mcp/access/`:

- `profiles.py`: `Profile` str-enum: `LOCAL_SCOUT`, `NATIONAL_SCOUT`,
  `FULL_OPERATOR`, `JV_PARTNER`.
- `context.py`: `TenantContext` (frozen pydantic model): `workspace_id: str`,
  `profile: Profile`, `plan: str = "standard"`, `territories: tuple[str, ...]`
  (state codes / metro names / zips; empty = unlimited for non-territory
  profiles), `active: bool = True`, `trusted: bool = False`,
  `display_name: str = ""`. Helpers: `current_context() -> TenantContext |
  None`, `use_context(ctx)` (contextmanager, ContextVar-backed),
  `local_context() -> TenantContext` (workspace_id="local",
  profile=FULL_OPERATOR, trusted=True).
- `registry.py`: `WorkspaceRegistry(path)` — server-side workspace records +
  API-key → workspace resolution (`resolve_key(key) -> TenantContext | None`),
  plus approvals: `request_approval(workspace_id, tool, args_hash) -> str`,
  `grant_approval(approval_id)`, `check_approval(approval_id, workspace_id,
  tool, args_hash) -> bool`. JSON-file backed; server-owned; never mutable via
  MCP args.
- `capabilities.py`: `ToolCapability` model per spec; `CAPABILITIES:
  dict[str, ToolCapability]` covering every registered tool;
  `capability_for(tool_name) -> ToolCapability | None`;
  `export_matrix() -> dict` (machine-readable JSON).
- `engine.py`: `Decision` (`allowed | denied | approval_required`, with
  `reason`, `approval_id`); `AccessEngine(registry)`:
  `check_tool(ctx, tool_name) -> Decision` (listing-level),
  `check_call(ctx, tool_name, args) -> tuple[Decision, dict]` (execution-level;
  returns sanitized args with server-authoritative/storage params stripped in
  cloud mode). Order: active → matrix (default-deny when not trusted) →
  profile → territory → ownership → quota → approval.
- `territory.py`: `location_within(location_value, territories) -> bool` —
  matches state codes ("TX"), "City, ST" strings, and 5-digit zips (zip→state
  via prefix table or stdlib-only mapping).
- `audit.py`: `AuditLog(path)` — append `AuditEvent {ts, workspace_id, tool,
  decision, reason}`; `events(workspace_id=None) -> list[AuditEvent]`.
  JSONL, server-side.
- `storage.py`: `workspace_db_path(ctx, config) -> Path` per Addendum A;
  applied during request handling so stores constructed inside a tool call
  resolve the workspace DB (trusted/local → legacy path unchanged).
- `middleware.py`: `AccessMiddleware(Middleware)` — `on_list_tools` filters by
  `check_tool`; `on_call_tool` resolves identity (HTTP: bearer/API key header
  via registry; stdio: `local_context()`), applies `check_call`, sets the
  context + workspace storage for the call, emits audit events, raises
  ToolError for denials, returns structured `approval_required` payloads.
- `server.py` wiring: middleware installed on the single `mcp` instance;
  hosted identity config (`CRE_ACCESS_REGISTRY_PATH`, `CRE_ACCESS_AUDIT_PATH`)
  via `CreConfig`.

Sensitive-parameter rule: a call is sensitive when the tool is marked
`sensitive` OR any listed `sensitive_params` is present and non-null in args.

JV semantics (v1): a JV is itself a workspace. Each API key maps to exactly
one workspace; an operator participating in a JV holds a second key bound to
the JV workspace (registry-side, out of band). "JV partner sees owned/shared
records only" therefore reduces to workspace separation: the JV workspace's
records are visible, every other workspace's records are not. `jv_partner`
remains territory-limited and has no transaction tools.

Approval retry contract: an `approval_required` decision returns a structured
tool RESULT `{"approval_required": true, "approval_id": ..., "tool": ...}`
(not an error). After server-side grant, the client retries the same call with
reserved argument `_approval_id`; middleware pops it before schema validation,
verifies `(workspace, tool, args_hash)` server-side, and lets the call
proceed. Mismatched or unknown approval ids are denied. `args_hash` =
sha256 of canonical JSON of args excluding `_approval_id`.

Audit on listing: `on_list_tools` emits one summary event
(tool=`__list_tools__`, reason=`filtered <total>-><visible>`); `on_call_tool`
emits one event per call with the final decision.
