# PostgreSQL Verification

## Purpose

This document records the current PostgreSQL persistence and transaction
verification state after EPIC 12 Task 5.

## Runtime Architecture

- `MarketplaceApplicationRunner` separates ingestion, transactional processing,
  and post-commit content work.
- `create_postgres_repository_scope()` creates one `AsyncSession` and one
  `session.begin()` transaction per bounded marketplace run.
- All repositories in the run share that session.
- Repositories execute statements or flush when required, but never commit,
  rollback, close, or create hidden sessions.
- Scoring and content generation run only after successful transaction exit.

## Revision 0005

Migration: `0005_add_persistence_integrity`.

Constraints and indexes:

- `uq_offers_marketplace_external_id_not_null`: partial unique index on
  `offers(marketplace, external_id)` where `external_id IS NOT NULL`;
- `ix_offers_canonical_product_id`: lookup index for canonical associations;
- `fk_offers_canonical_product_id_canonical_products`: nullable foreign key to
  `canonical_products.id` with `ON DELETE SET NULL`;
- `uq_price_snapshots_exact_identity`: unique constraint on marketplace,
  external ID, collection timestamp, price, and currency;
- `ix_price_snapshots_history_order`: B-tree index on marketplace, external ID,
  collection timestamp, and record ID. Forward scans support complete history;
  backward scans support latest and previous queries.

Before applying DDL, the migration checks for duplicate stable offer identities,
exact duplicate snapshots, and orphan canonical references. It raises a clear
manual-cleanup error and does not choose survivors or silently modify data.

The downgrade removes all Task 5 indexes and constraints in reverse dependency
order. Legacy foundation tables are unaffected.

## Repository Semantics

### Offers

- Non-null `(marketplace, external_id)` is the stable identity.
- PostgreSQL uses `INSERT ... ON CONFLICT DO UPDATE` against the partial unique
  index.
- Title, URL, price, currency, seller fields, and canonical product ID update only
  when the incoming value is non-null.
- Existing `id` and `created_at` are preserved on conflict.
- A null `external_id` remains an append-only record and receives no synthetic ID.
- Memory persistence follows the same identity and non-null update semantics.
- Concurrent stable-identity writes converge on one row. With no source revision
  field, the last successful non-null upsert in PostgreSQL execution order wins.

### Price snapshots

- Exact identity is `(marketplace, external_id, collected_at, price, currency)`.
- PostgreSQL uses `ON CONFLICT DO NOTHING` on the exact identity constraint.
- Expected exact duplicates are non-fatal and do not create another row.
- `PriceHistoryRepository.add()` returns `True` for a new row and `False` for a
  suppressed exact duplicate, so application result counts remain accurate.
- Same price at a new timestamp remains valid.
- Different prices at the same timestamp remain valid.
- Out-of-order snapshots remain valid and history ordering is deterministic by
  collection timestamp and persistent ID.

### Canonical products

- Offers may have a null canonical product ID.
- Valid IDs reference `canonical_products.id`.
- Deleting a canonical product sets linked offer IDs to null instead of deleting
  offers.
- Matching output is not automatically persisted; administrator confirmation and
  rejection decisions remain unchanged.

## Verification Completed

- SQLAlchemy metadata contains every Task 5 constraint and index.
- PostgreSQL-dialect SQL compilation confirms partial-index offer upsert with
  non-null field preservation.
- PostgreSQL-dialect SQL compilation confirms exact-snapshot
  `ON CONFLICT DO NOTHING`.
- Offline Alembic upgrade SQL generation reaches revision `0005` successfully.
- Offline downgrade SQL generation from `0005` to `0004` succeeds.
- Memory repository tests cover update identity, marketplace isolation, nullable
  append-only offers, non-null field preservation, exact snapshot suppression,
  equal timestamps, new timestamps, ordering, and identity isolation.
- Application runner rollback and post-commit behavior remain covered by the full
  test suite.

## Live Verification Limitation

The configured PostgreSQL hostname `db` does not resolve in the current local
environment (`getaddrinfo failed`). Therefore the following are not claimed as
live-verified:

- migration upgrade or downgrade against a running PostgreSQL database;
- preflight behavior against existing duplicate/orphan data;
- two-session concurrent offer upsert;
- two-session concurrent snapshot insertion;
- foreign-key rejection and `ON DELETE SET NULL` execution;
- PostgreSQL-backed application-runner and Scheduler retry execution.

These require the final EPIC 12 live verification task.

## Legacy Schema

`marketplaces`, `products`, and `prices` originate from the initial foundation
migration. Active repositories use `offers`, `canonical_products`, and
`price_snapshots`; no current repository reads or writes the legacy tables. Task 5
keeps them as deprecated foundation schema because ownership and data-retention
policy have not been approved. Removal requires a separate cleanup migration.

## Remaining Risks

- Nullable offer external IDs are intentionally not deduplicated.
- Event and publication intent are not persisted, so a crash after commit can
  lose post-commit content work.
- Scheduler overlap and multi-process coordination are not implemented.
- Timestamp columns remain timezone-naive at the PostgreSQL schema level even
  though runtime values are produced in UTC.
- `Numeric(12, 2)` capacity has not been validated for every future marketplace.

## Recommended Final EPIC 12 Task

Run revision `0005`, repository concurrency scenarios, application-runner
commit/rollback, repeated ingestion, and Scheduler retry against live PostgreSQL.
Update this document and Scheduler verification with observed results only. No
new product functionality is required.
