# EPIC 20 - Guarded Catalog Onboarding

## Status

Tasks 1 and 2 are implemented and verified.

## Goal

Give an authorized tenant operator an accurate view of catalog onboarding
progress without weakening matching rules or creating unreviewed canonical
links.

## Delivered

- A tenant-scoped onboarding summary derived from the existing offer,
  canonical-product, link, decision, and matching boundaries.
- A single onboarding workspace projection that returns the complete summary
  and bounded review/proposal queues from one repository state and one matching
  pass.
- Protected seller endpoints:
  - `GET /api/v1/tenants/{tenant_id}/catalog/onboarding-summary`
  - `GET /api/v1/tenants/{tenant_id}/catalog/onboarding-workspace`
- Market Terminal review metrics for total, linked, unresolved, queued, and
  unqueued offers, canonical products, immutable decisions, and per-marketplace
  progress.
- Compatibility with the existing candidate and proposal endpoints and all
  existing idempotent catalog commands.
- An isolated operator-to-public-catalog verification path that confirms one
  synthetic `NO_MATCH` proposal, records one immutable decision, links the
  source offer, and exposes the resulting product through the existing public
  product, detail, offer, and comparison routes.
- Exact command replay remains idempotent: the second request reuses the same
  decision and does not duplicate the canonical product or link.

## Counting Semantics

- `total_offers`: every offer visible to the tenant repository scope.
- `linked_offers`: offers with a reviewed canonical product link.
- `unresolved_offers`: total offers minus linked offers.
- `review_candidates`: unresolved offers classified as `REVIEW` by the existing
  matching thresholds.
- `product_proposals`: unresolved offers that produce the existing deterministic
  `NO_MATCH` proposal.
- `unqueued_offers`: unresolved offers not represented by either actionable
  queue, including automatic-confidence or incomplete source records. This
  count is visibility only and never creates an automatic link.
- `canonical_products`: tenant-owned canonical products.
- `terminal_decisions`: immutable tenant-owned catalog review decisions.

The workspace `limit` bounds each returned queue to `1..200`; summary counts
always cover the complete tenant catalog and are not inferred from the bounded
lists.

## Guardrails

- No matching threshold changed.
- No offer is linked automatically.
- No canonical product, alias, link, or review decision is created by a read.
- No cross-tenant data is included.
- No marketplace identity is inferred from title similarity alone.
- No database migration is required.

## Verification

- Isolated PostgreSQL 17.10 catalog-review verifier: `21/21` checks passed.
- Alembic current: `0017_marketplace_polling_runs` (head).
- Alembic check: no new upgrade operations detected.
- Alembic offline upgrade SQL: generated successfully.
- Full Pytest: `479 passed, 58 skipped` with one known unrelated Starlette
  deprecation warning.
- Full MyPy: no issues in `425` source files.
- Focused Ruff and Ruff format checks: passed.
- Review JavaScript syntax check: passed.
- Isolated memory-backed onboarding-to-public-catalog verifier: `33/33` checks
  passed.
- Browser verification confirmed the complete reviewer action and subsequent
  public product selection, offer, and comparison views without horizontal
  overflow on the exercised desktop viewport.

## Operational State

The saved-data operator preview contains `60` GGSEL, `20` Playerok, and `1`
FunPay offer. With no curated catalog identities, the honest starting state is
`81` unresolved product proposals and no fabricated links.

The next operational step is a bounded human-reviewed onboarding batch using
the existing confirm, reject, create-product, and resolve-to-existing commands.
Source coverage and reviewed decisions must be recorded before a catalog is
presented as production-ready.

The Task 2 verification uses synthetic, isolated data. It proves the wiring and
transaction outcome but does not claim that any of the `81` saved real offers
has been reviewed or linked.
