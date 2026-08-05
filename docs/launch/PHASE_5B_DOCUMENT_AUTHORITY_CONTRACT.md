# Phase 5B hosted document authority contract

Status: RED-first implementation slice, not hosted launch approval

Branch: `integration/cloud-platform-launch`

Base: `b58dfe09da713642813f28ac928967ca408fbf53`

## Outcome and boundary

This slice certifies the request-scoped PostgreSQL read authority for external
document-rights attestations. It is the first real implementation behind one of
the eight hosted domain ports. Platform, provider, search, deal, privacy, job,
and truth-asset parity remain uncertified, so production hosted startup stays
fail closed.

The trusted local product keeps its existing SQLite attestation store. Hosted
execution never constructs, reads, writes, or falls back to that store.

## Durable record

PostgreSQL stores only the attested URL's SHA-256 digest, never the attested URL.
Each attestation is bound to one workspace UUID, actor UUID, OAuth session UUID,
allowed-purpose set, evidence URL and evidence digest, approving user, approval
time, expiry, and optional revocation time.

The identifier retains the existing `srcatt_` plus 32 lowercase hexadecimal
characters contract. URL and evidence digests are exactly 32 bytes. Purposes
are a non-empty subset of `retrieve`, `store`, `derive`, and `output` with no
duplicates. Approval and expiry are server timestamps with expiry strictly
after approval. Tenant, actor, session, and approver references use native
foreign keys.

## Request and RLS binding

Migration `0005` extends the admitted-request transaction with an exact
transaction-local OAuth session UUID. Pool reset clears it. The document table
uses row-level security that requires the current workspace, actor, and OAuth
session simultaneously. An app session that supplies only workspace and actor
sees no attestation row.

The repository is constructed from one app database and the exact fresh
admission. Every call opens only `PostgresDatabase.admitted_connection`, checks
that it is the exact document port in the currently active aggregate lease, and
compares the server-resolved `TenantContext` to the admission before querying.
Caller arguments never select tenant authority.

A repository reference captured by a detached task cannot be used after the
owner scope exits. A mismatch, missing row, revocation, expiry, URL digest
mismatch, missing purpose, malformed database value, unavailable database, or
inactive lease fails closed with a fixed source-rights denial. No database
exception or stored value reaches the client.

## Required evidence

- RED import and behavior tests before production implementation;
- native PostgreSQL success, workspace, actor, and OAuth-session isolation;
- exact URL and purpose matching, expiry, revocation, and malformed-input
  denials;
- active-scope and detached-reference revocation checks;
- exact app read-only ACL, RLS, backup, restore, readiness, migration, and pool
  reset coverage;
- unchanged trusted-local attestation behavior and unchanged customer surface;
- compile, diff, secret, deterministic package, PostgreSQL, and full-repository
  gates;
- two fresh read-only reviews of one unchanged candidate hash.

## Explicit non-scope

This slice does not:

- implement the internal admin approval or revocation workflow;
- implement the other seven hosted domain ports;
- return a production persistence bundle or enable hosted production startup;
- migrate any local attestation or customer record;
- permit SQLite, JSON, JSONL, local-blob, dual-write, shadow-write, reverse-sync,
  or fallback behavior in hosted execution;
- change the public MCP tool surface or customer-visible tool counts;
- deploy, provision, change DNS, activate billing, spend money, access customer
  data, or claim public launch approval.
