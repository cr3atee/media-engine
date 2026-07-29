# PostgreSQL Verification

## Status

PostgreSQL persistence and the EPIC 12 runtime are live-verified against
PostgreSQL 17.10 in an isolated Compose environment.

## Verified Schema

- Revision `0005_add_persistence_integrity` applies, downgrades to `0004`, and
  re-applies successfully.
- Duplicate offers, duplicate snapshots, and orphan canonical references each
  stop migration `0005` without changing data.
- Offer stable identity is enforced by a partial unique index.
- Exact snapshot identity is enforced by a unique constraint.
- History and canonical lookup indexes exist.
- Canonical product references reject missing IDs and use
  `ON DELETE SET NULL`.
- Revision `0006_use_utc_timestamps` aligns active PostgreSQL columns with the
  UTC-aware application runtime and is reversible.
- `alembic check` reports no pending schema operations.

## Verified Repositories

- Offer insert, update, optional-value preservation, marketplace isolation,
  nullable identity, canonical assignment, and `Decimal` precision pass.
- Price snapshot conflict suppression, ordering, latest/previous queries,
  out-of-order insertion, equal-timestamp tie-breaking, and marketplace
  isolation pass.
- Two-session offer and snapshot conflicts complete without leaving failed
  transactions.
- Memory and PostgreSQL repositories retain the same public async contract.

## Verified Transactions

- One repository scope supplies one `AsyncSession` to all repositories.
- Repositories do not commit independently.
- Successful runner scope exit commits once.
- Offer, snapshot, deterministic processing, and commit failures roll back the
  complete run and skip post-commit work.
- Content failure after commit leaves persistence durable and is represented in
  `MarketplaceRunResult`.

## Remaining Limits

- Event and publication state are not persisted.
- Post-commit publication retry is not implemented.
- Scheduler overlap and multi-process coordination are not implemented.
- Null external IDs remain intentionally append-only.
- Legacy foundation tables remain present and inactive.

Complete evidence is recorded in `EPIC_12_FINAL_VERIFICATION.md`.
