# MedawarCRE Internal Admin and JV APIs

Status: approved for implementation

Branch: `feature/internal-admin-jv-apis`

Base: `49cab683f0c5effd47f70d1a476a4b7c3de2bb22`

## Goal

Add a small hosted control-plane API for trusted MedawarCRE operators and a
read-only JV API for authenticated JV partners. Keep all tenant authority live,
server-owned, and fail-closed. Make every successful control-plane mutation and
its audit event one indivisible SQLite transaction.

## Scope

### Internal admin routes

- `POST /v1/admin/workspaces`
- `GET /v1/admin/workspaces/{workspace_id}`
- `PATCH /v1/admin/workspaces/{workspace_id}/memberships/{membership_id}`
- `POST /v1/admin/workspaces/{workspace_id}/grants`
- `DELETE /v1/admin/workspaces/{workspace_id}/grants/{grant_id}`
- `POST /v1/admin/workspaces/{workspace_id}/territories`
- `DELETE /v1/admin/workspaces/{workspace_id}/territories/{territory_id}`
- `POST /v1/admin/workspaces/{workspace_id}/external-accounts`
- `GET /v1/admin/workspaces/{workspace_id}/external-accounts`
- `DELETE /v1/admin/workspaces/{workspace_id}/external-accounts/{mapping_id}`
- `POST /v1/admin/workspaces/{workspace_id}/account-state`

### JV routes

- `GET /v1/jv/workspace`
- `GET /v1/jv/members`

## Explicit deferrals

- Per-membership territories
- Invites and self-registration
- Unfiltered cross-workspace search or listing
- Provider SDKs, provider webhooks, and provider-specific execution
- Plan CRUD
- Audit export APIs
- Frontend work
- HTTP bootstrap or internal-admin management endpoints

## Authority model

### Internal operators

`platform_internal_admins` is a server-owned user-scoped authority table.
It is independent of tenant membership, grants, profiles, token claims, and
`TenantContext`.

Allowed roles:

- `platform_admin`: read and mutate
- `support`: read only

Every admin request requires:

1. A valid hosted OAuth bearer token.
2. A live workspace membership for the token-bound identity, as already
   required by hosted OAuth.
3. The `admin:controls` OAuth scope.
4. A live, active `platform_internal_admins` row.
5. `platform_admin` for any mutation.

The scope is necessary but never sufficient. Missing, inactive, or unknown
internal authority returns 403. The mutation transaction re-reads the internal
admin row and takes the audit actor role from that row, closing the
authorization-to-write race.

No internal role is added to access or refresh tokens. No internal role is
added to `TenantContext`.

### JV authority

JV endpoints require a live effective `jv_partner` grant. Each request uses the
existing live authority resolver, so membership, workspace, account, profile,
and workspace territories are read from SQLite for that request. Separately,
admin authorization is denied when any grant row for the authenticated
workspace has `profile='jv_partner'`, independent of status, expiry, or ranking.
This immutable authority outcome flag is not exposed in tokens, `TenantContext`,
`/v1/me`, or MCP claims.

The token-bound workspace is authoritative. Client-supplied `workspace_id`,
`role`, `profile`, or territory filters are rejected with 422. They never
select or expand authority. Returned members and territories are constrained to
the authenticated live workspace. JV identities cannot use admin routes,
including a defensively tested identity that is deliberately dual-seeded with
internal authority and the dedicated scope.

## Additive schema and migration

Add the independent `admin-controls` migration component at version 1. It has no
backfill and makes no changes to existing columns.

### `platform_internal_admins`

- `user_id` primary key and foreign key to `platform_users`
- `role` constrained to `platform_admin` or `support`
- `active` constrained to 0 or 1
- timestamps

The first administrator is seeded out of band or by test setup. There is no
bootstrap route. No internal-admin mutation route is part of this phase, so
last-active-platform-admin protection is not exposed in this API.

### `platform_external_accounts`

- `id`
- `workspace_id`
- normalized nonblank `provider`
- trimmed, nonblank, case-preserving `external_account_id`
- canonical JSON `metadata`
- timestamps
- global uniqueness on `(provider, external_account_id)`

This is a provider-neutral mapping only. Existing
`platform_subscriptions.external_customer_id` and
`platform_access_grants.external_ref` remain unchanged.
Provider matching is case-normalized. External account identifiers remain
case-sensitive because provider identifier semantics may require it.

### `platform_admin_audit`

- `id`
- `actor_user_id`
- `actor_role`
- `action`
- nullable target `workspace_id`
- `target_type`
- `target_id`
- `reason_code`
- `reason`
- canonical `before_json`
- canonical `after_json`
- `created_at`

SQLite triggers reject audit updates and deletes. Snapshots use sorted,
compact JSON with stable enum and datetime serialization. Absence is JSON
`null`.

## Structural transaction invariant

All admin mutations go through `AdminControlStore._mutate`.

1. Open one SQLite connection.
2. Apply schema before beginning the operation.
3. `BEGIN IMMEDIATE`.
4. Re-read the actor's active internal authority and require
   `platform_admin`.
5. Execute one mutation callback using the same connection.
6. Capture its typed before and after snapshots.
7. Insert exactly one audit row automatically. A temporary SQLite trigger
   prevents callbacks from inserting audit rows, and the connection change
   counter verifies that the executor insert produced exactly one row without
   scanning the append-only audit table.
8. Commit.

Any validation, authorization, conflict, missing-target, database, or audit
failure rolls back the entire transaction. Route handlers cannot perform a
control-plane write through the ordinary repository and cannot opt out of
audit insertion.

## Request validation

Every mutation body contains:

- `reason_code`: one value from the exported fixed allowlist
- `reason`: a nonblank human explanation

The initial allowlist is:

- `initial_provisioning`
- `customer_request`
- `billing_correction`
- `entitlement_correction`
- `security_response`
- `support_resolution`
- `data_correction`

Malformed JSON returns 400 through the existing envelope. Invalid fields,
missing reasons, unknown reason codes, and prohibited JV selectors return 422.
Scoped missing resources return 404. Uniqueness and state conflicts return 409.
Hosted authentication remains strict 401/403.
Conflict responses use fixed operation-level messages and never expose SQLite
constraint strings or column names. Distinguishable audit insertion failures
return a fixed 500 `admin_audit_failed` envelope.

## Resource contracts

### Trusted provisioning

`POST /v1/admin/workspaces` accepts:

- `name`
- optional `slug`
- optional `plan_id`
- `owner_email`
- `owner_name`
- optional `account_state`, default `active`
- required audit reason fields

It creates the workspace, owner user, owner membership, account row, and one
audit event atomically. An existing owner email, invalid plan, duplicate slug,
or audit failure leaves none of those rows behind.
When `plan_id` is supplied, the plan is validated inside the same write
transaction before the first insert; a missing plan returns 422.

### Workspace read

The admin workspace response includes the workspace, account, memberships with
their users, active and inactive grants, workspace territories, and external
account mappings. Support may read it.

### Membership role

Only `role` and audit reason fields are accepted. The path workspace and
membership are authoritative. Role changes are visible on the target user's
next request over an existing OAuth session.

### Grants

Create accepts the current entitlement fields: source, external reference,
profile, plan key, optional status and effective dates. Delete is scoped by
both path workspace and grant id. Existing grant schema and columns are reused.

### Territories

Create accepts name, state, market, and asset type. Delete is scoped by both
path workspace and territory id. Territories remain workspace-level.

### External accounts

Create accepts provider, external account id, and optional JSON metadata. List
and delete are path-workspace scoped. A provider/external id already mapped
anywhere returns 409.

### Account state

Accepts a target state and reason fields. Existing account transition rules are
enforced. The audit before and after snapshots carry the live state.

## Known phase couplings

- Hosted internal operators continue to require a live tenant membership to
  obtain and use the existing hosted OAuth session. This is an availability
  and lockout coupling, not a source of internal authority, and is unchanged in
  this repair.
- `platform_admin_audit.actor_user_id` retains its existing non-cascading
  foreign key to `platform_users`. User erasure therefore remains coupled to
  retained audit history and is deferred rather than changed in this phase.

## Deterministic red tests

New focused files:

- `tests/platform/test_admin_authority.py`
- `tests/platform/test_admin_controls.py`
- `tests/platform/test_jv_control_scope.py`
- `tests/platform/test_admin_audit.py`
- `tests/platform/test_external_accounts.py`
- `tests/platform/test_admin_resource_lifecycle.py`

Migration coverage extends `test_migrations.py` and `test_schema.py`.

The initial failing suite must demonstrate:

1. Owner, admin, member, viewer, inactive internal admins, missing-scope admins,
   and support cannot mutate. Only active `platform_admin` with
   `admin:controls` can.
2. Support can use read-only admin routes.
3. JV users cannot use admin routes, cannot read another workspace's members
   or territories, and cannot widen scope with client fields.
4. A membership role change is visible on the next request with the same token.
5. Fresh and upgraded databases receive version 1 without backfill or changes
   to legacy provider reference columns.
6. Missing, blank, and invalid reasons produce 422 and no write.
7. A failed mutation produces no audit row.
8. Duplicate external mappings produce 409.
9. Audit JSON is canonical and actor identity and role come from live internal
   authority.
10. Provisioning rolls back workspace, user, membership, and account rows on
    failure.

## Verification

Use only:

```text
PYTHONPATH=/Users/maxmedawar/LoopnetMCP-admin-jv/src
/Users/maxmedawar/LoopnetMCP/.venv/bin/python
```

Run:

1. Focused new platform tests.
2. Existing platform, access, hosting, and config tests.
3. The focused and regression sets with `PYTHONASYNCIODEBUG=1` and
   `RuntimeWarning`, `ResourceWarning`, and `PytestUnraisableExceptionWarning`
   promoted to errors.
4. Full pytest.
5. `compileall`.
6. `git diff --check`.
7. Dependency and lockfile diff inspection.
8. Branch, HEAD, and status inspection.
9. Read-only verification that the prohibited checkout's tracked state and
   port 8000 PID/cwd match the recorded baseline.

Do not commit, push, merge, deploy, bind to or contact port 8000, or edit either
prohibited checkout.
