# Marketplace Polling History Verification

## Scope

This verification closes the retained-history gap discovered after guarded live
GGSEL, Playerok, and FunPay polling. It does not change marketplace parsing,
matching, comparison, scheduling policy, or credential handling.

## Durable Contract

`MarketplacePollingRun` is an immutable, tenant-owned record for one selected
integration attempt. It retains:

- integration and marketplace identity;
- succeeded, failed, or skipped terminal status;
- UTC start and finish timestamps;
- bounded ingestion, snapshot, price-change, event, and processing-error counts
  when the runner returns a `MarketplaceRunResult`;
- stable skipped reason or sanitized failure code and summary.

The record never stores source URLs, credential references, or raw exception
messages. Successful and failed latest-outcome metadata on
`MarketplaceIntegration` remains available for quick status reads.

## Persistence And Transactions

Alembic revision `0017_marketplace_polling_runs` adds:

- `marketplace_polling_runs`;
- a composite tenant/integration foreign key;
- outcome, timestamp, and non-negative count constraints;
- newest-first integration and status indexes;
- the supporting unique `(tenant_id, id)` integration identity.

The execution service writes the immutable run and updates latest integration
metadata in one short repository scope after external marketplace work has
finished. Repository or journal failures propagate to Scheduler ownership. An
ordinary marketplace exception remains isolated to its integration so later
sources can still run.

## Seller Read Boundary

Authorized tenant members with `INTEGRATIONS_READ` can request a bounded newest-
first history at:

`GET /api/v1/tenants/{tenant_id}/marketplace-integrations/{integration_id}/runs`

The route returns at most `100` records, hides foreign-tenant integration IDs,
and exposes only the safe durable fields.

## PostgreSQL Verification

`scripts/verify_marketplace_polling_history_postgres.py` passed `25/25` checks
against an isolated PostgreSQL 17 database named
`epic19_history_verify`. Verification covered:

- success, isolated failure, and missing-URL skip retention;
- application-result counters and safe processing-error count;
- newest-first ordering, bounded reads, and tenant isolation;
- constant failure summary without URL, credential, or exception text;
- latest outcome and immutable history consistency;
- schema constraints, indexes, and composite tenant ownership;
- rollback of both latest metadata and history on an identity conflict;
- fresh-engine persistence.

Alembic clean upgrade, `current`, `check`, downgrade to
`0016_canonical_offer_decisions`, upgrade back to head, and offline SQL generation
all passed.

## Quality Result

- Focused repository, service, runtime, and seller API tests: `26 passed`.
- Full Pytest: `471 passed, 58 skipped`.
- Full MyPy: `422 source files`.
- Ruff and Ruff format: passed for every touched Python file.
- Existing unrelated warning: FastAPI TestClient emits one
  `StarletteDeprecationWarning` about the future `httpx2` transition.

## Remaining Operational Limits

- Alert routing is not implemented.
- Production deployment and metrics export configuration are not supplied by
  this repository task.
- Authenticated marketplace sources still need an approved runtime secret-store
  retrieval design.
- History retention/pruning policy must be selected from observed production
  volume; no destructive automatic pruning is introduced here.
