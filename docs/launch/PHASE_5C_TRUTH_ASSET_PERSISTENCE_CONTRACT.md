# Phase 5C hosted truth-asset persistence contract

Status: RED-first implementation slice, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `aac18a8ca6100a9f5c4a2beae8cc7ac7afb57c3b`

## Outcome and boundary

This slice certifies request-scoped PostgreSQL persistence for the document
truth pipeline. It replaces the hosted SQLite and local-filesystem boundary
with one durable repository while preserving the trusted local product.

Platform, provider, search, deal, privacy, and job parity remain uncertified.
Production hosted startup therefore stays fail closed. Internal document
approval, revocation, and server-owned upload bindings are not part of this
slice.

## Durable asset and claim records

PostgreSQL stores a workspace-scoped content blob, document metadata, and
structured claims. Raw content is stored as bounded `bytea` for this launch
slice, so no cloud object-store account, paid resource, or external lifecycle
dependency is introduced.

The document identifier is exactly the lowercase SHA-256 digest of the raw
content. Code validates it with a constant-time comparison, and PostgreSQL
independently checks the digest against the stored bytes. Content is never
deduplicated across workspaces. A document may be associated with more than
one deal reference inside a workspace without duplicating its blob.
Workspace removal cascades from the blob through document metadata and claims,
so this graph cannot block an authorized tenant teardown.

Deal references remain immutable source-qualified text rather than a foreign
key because the public document contract permits ingestion before a deal is in
the deal store. Metadata retains the existing document kind, source channel,
lineage-safe origin, format, page count, parse state, redaction count, and
ingestion time. Hosted records do not invent or expose a local blob path.

Claims use native bounded columns for field, subject, typed value, unit,
confidence, lineage, extraction method, and flags. The repository reconstructs
the existing `FieldClaim` shape exactly. It does not persist an opaque claim
object as the authority. Duplicate claim keys and lineage that disagrees with
the parent document fail closed. PostgreSQL and the read boundary independently
reject non-finite numbers and bounding-box coordinates.

## Transaction and concurrency contract

One save call validates all inputs before mutation and then performs blob
insert, document upsert, prior-claim removal, and replacement-claim insertion
inside one admitted PostgreSQL transaction. Any error rolls back the entire
operation. Repeating the same valid save is idempotent. Concurrent saves cannot
publish a partial asset or claims set. Resaving replaces every mutable metadata
field, including source channel and format, alongside its claims. A canceled
async caller cannot release its request lease while its database worker is
still running.

The app role may insert blobs and may read and mutate document metadata and
claims only through workspace row-level security. It has no blob read, update,
or delete privilege. The backup role remains read-only and complete. Restore
privileges reproduce the same least-authority contract.

## Request and RLS binding

The repository is constructed from one app database and one exact fresh
admission. Every call requires that it is the exact truth-asset port in the
currently active aggregate repository lease and that the active untrusted
`TenantContext` matches the admission workspace, actor, and OAuth session.
Every database operation uses only `PostgresDatabase.admitted_connection`.

Row-level security derives the workspace UUID from the admitted transaction.
Caller arguments never select tenant authority. Asset visibility is shared
within that workspace and is not permanently tied to the OAuth session that
created it. A captured repository reference cannot be used after its request
lease ends.

A malformed input, digest mismatch, lineage mismatch, inactive scope, database
failure, or malformed stored value raises the same fixed truth-asset
unavailable error. Hosted reads never convert database failure into an empty
success and never fall back to SQLite, JSON, JSONL, or the local filesystem.
This remains true for a detached task that retains an untrusted context after
the aggregate repository lease has been revoked.

## Document pipeline bridge

An externally hosted URL must still pass the exact document-attestation check
before network access and again at the socket boundary. With the truth-asset
port active, its content is streamed into a bounded in-memory buffer and the
transfer's synchronous receipt callback aborts before byte 52,428,801 can be
retained. The URL worker must finish or terminate before caller cancellation
can unwind the request and attestation leases. Valid bounded content may
proceed through the existing deterministic parser and into PostgreSQL. Hosted
local paths remain denied until a separate server-owned upload-binding
repository is certified.

The public MCP input and output shapes do not change. Listing, reconciliation,
NOI, reporting, and lineage consumers continue to use the truth-store public
methods and receive the same document and claim dictionaries.

## Required evidence

- RED import and behavior tests before production implementation;
- native PostgreSQL digest, transaction, idempotence, and replacement tests;
- workspace isolation, exact active-scope, detached-reference, and RLS tests;
- structured claim round-trip parity for null, number, text, location, and flags;
- fixed-error database failure tests with no local fallback or empty success;
- hosted URL pipeline coverage proving attestation before retrieval and durable
  persistence after retrieval, receipt-time memory bounds, and cancellation
  containment;
- exact app ACL, RLS, backup, restore, readiness, migration, and pool-reset
  coverage;
- unchanged trusted-local truth behavior and unchanged customer surface;
- compile, diff, secret, deterministic package, PostgreSQL, and full-repository
  gates;
- two fresh read-only reviews of one unchanged candidate hash.

## Explicit non-scope

This slice does not:

- implement internal document approval or revocation;
- implement server-owned upload bindings or allow hosted filesystem paths;
- implement the other six hosted domain ports;
- return a production persistence bundle or enable hosted production startup;
- migrate any local document, blob, claim, or customer record;
- add a customer-facing raw-blob retrieval capability;
- permit local persistence, dual-write, shadow-write, reverse-sync, or fallback
  behavior in hosted execution;
- change the public MCP tool surface or customer-visible tool counts;
- deploy, provision, change DNS, activate billing, spend money, access customer
  data, or claim public launch approval.
