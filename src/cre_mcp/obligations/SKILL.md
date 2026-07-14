# Wave 2 Track B implementation contract

## Scope

Build a deterministic obligation collision detector, transfer-consent screen,
and estoppel comparison surface for checklist jobs 75, 126, 127, and 214.
All implementation and tests are isolated to new files in
`src/cre_mcp/obligations/` and `tests/obligations/`.

## Invariants

- Reuse `cre_mcp.leases.models.CitedClaim` for every document-derived fact.
- Sanitize all raw document text with `cre_mcp.truth.sanitize.sanitize_text`.
- Preserve source quotes verbatim and bounded to 200 characters.
- Treat silence as missing and disclose gaps; never fill from market custom.
- Use deterministic regular expressions and a documented, small synonym table;
  do not use an LLM or network source.
- Collision output is an advisory screen: quote both sides, describe possible
  overlap, ask a transaction-specific question, and route legal conclusions to
  CRE counsel.
- Typical consent timing is labeled as a convention, not lease language.
- Plain tool functions remain unregistered and JSON-friendly.

## Architecture

- `restrictions.py`: cited restriction models and section-aware extraction for
  leases and recorded CC&Rs.
- `collisions.py`: deterministic category/synonym overlap, conservative
  `possible_conflict` handling, and cited collision records.
- `consent.py`: lease/loan transfer trigger screen with explicit missing-loan
  disclosure and the master-lease absolute-prohibition fatal flag.
- `estoppels.py`: cited lease-side mismatch exceptions plus SNDA presence and
  missing-input metadata on a list-compatible result.
- `tools.py`: file-or-text loading and dataclass serialization only; no MCP
  registration.
- `__init__.py`: focused public exports.

## Verification

Tests use the executed Dollar Tree HTML fixture and synthetic clauses covering
exclusive-use overlap, prohibited uses, co-tenancy, ambiguous overlap,
master-lease transfer blocking, missing loan terms, and cited estoppel rent
mismatches. Run only:

`.venv/bin/python -m pytest tests/obligations -q`
