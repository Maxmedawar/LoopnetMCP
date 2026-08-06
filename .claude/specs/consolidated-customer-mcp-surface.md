# Consolidated customer MCP surface

## Release decision

The current cloud platform remains the authority. Its internal FastMCP server
retains all 274 registered capabilities. Hosted HTTP customers receive a
separate grouped facade built from that server. The older 45-tool branch is
inventory evidence only and is neither imported nor deployed.

The authoritative implementation is:

- `src/cre_mcp/surface/catalog.py` for reconciliation and grouping
- `src/cre_mcp/surface/server.py` for grouped dispatch
- `src/cre_mcp/access/middleware.py` for exact-capability enforcement
- `src/cre_mcp/server.py` for hosted HTTP construction

The complete machine-readable mapping is exported with:

```bash
PYTHONPATH=src python scripts/export_customer_mcp_surface.py
```

## Inventory reconciliation

The catalog locks the full capability matrix to the SHA-256 held in
`CAPABILITY_INVENTORY_SHA256` (`src/cre_mcp/surface/catalog.py`), currently
`84578ae71567ed1862ff931564f97fbc54985afe0b850ca962cb0e61ea8c7dc5`.
Construction fails if that matrix changes before the surface is reviewed and
re-locked. The constant is the authority; this document quotes it and can lag,
as it did at `3ef968d8...` from `802b16c` until 2026-08-06.

| Inventory class | Count | Treatment |
|---|---:|---|
| Current server-owned capabilities | 274 | Retained |
| Historical broad-server tool IDs | 45 | Exact subset of current inventory |
| Customer-grouped actions | 253 | Routed through 20 coherent facade tools |
| — of those, hosted-withheld | 15 | Dead on hosted; unadvertised and denied |
| — of those, hosted-reachable | 238 | Advertised and executable on hosted |
| Internal MCP capabilities | 21 | Never registered on the customer facade |

Every grouped `action` string is an exact key in `CAPABILITIES`. There are no
aliases that bypass the access engine. All 45 historical IDs map to one of the
same grouped tools. Admin, billing-platform, database, security,
provider-repair, and combined-opportunity operations remain outside the
customer MCP surface. Combined-opportunity MCP capabilities are classified as
internal explicitly; the other internal classes are platform services rather
than customer MCP actions.

## Profile surfaces

Visibility requires both the facade's profile classification and at least one
currently entitled exact action that is also hosted-reachable. The
release-locked counts are:

| Profile | Visible grouped tools | Target |
|---|---:|---:|
| Local Scout | 8 | 8-12 |
| National Scout | 10 | 10-15 |
| Full Operator | 20 | 15-22 |
| JV Partner | 11 | 10-15 |

JV Partner was 14 when this spec was written, became 12 at Phase 5G (`49adb9e`),
and became 11 at the hosted withholding correction of 2026-08-06, when
`cre_close` stopped being listed for `jv_partner` because all four of its
JV-entitled actions are dead on hosted. The live authority is
`reconciliation_report()["profile_tool_counts"]`, pinned by
`tests/surface/test_catalog.py` and `tests/surface/test_server.py`.

The grouped tool vocabulary is domain-specific: discovery, property, market,
evaluation, offer, contact, finance, diligence, pipeline, closing, comparison,
disposition, leasing, structure, capital, partner, portfolio, operations,
construction, and books. A profile sees only the groups for which it has a
live allowed action.

## Enforcement sequence

For a call such as:

```json
{
  "tool": "cre_discover",
  "arguments": {
    "action": "search_properties",
    "arguments": {"location": "Dallas, TX"}
  }
}
```

the hosted middleware resolves `search_properties` before authorization. The
existing access engine then applies profile entitlement, live grant state,
quota, territory, approval fingerprinting, and result-territory checks to that
exact capability and its exact arguments. The sanitized arguments are wrapped
back into the facade call. Source-rights collection and result sanitization run
after the exact internal tool executes. Audit events record the exact
capability ID, not only the grouped facade name.

Unknown actions, cross-group actions, internal actions, malformed nested
arguments, missing hosted identity, and direct calls to the 274-tool internal
server all fail closed at the customer facade.

## Runtime boundary

- Hosted HTTP constructs the grouped customer server.
- Stdio continues to run the complete internal server for trusted local use.
- OAuth and PostgreSQL authority remain unchanged.
- Existing platform routes remain on the current cloud-platform app and retain
  their route-specific authorization.
- No deployment is part of this change.
- No code from the older 45-tool HTTP implementation is used to replace the
  current server, OAuth, territory, PostgreSQL, or source-rights paths.

## Release evidence

Tests lock the inventory fingerprint, 274-way accounting, all historical
mapping, profile counts, live tool listing, exact quota and territory behavior,
approval binding, source-rights sanitization, exact audit IDs, and fail-closed
internal-action behavior. The full repository suite must pass before release.
