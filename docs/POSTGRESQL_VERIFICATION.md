# PostgreSQL Verification

## Status

PostgreSQL persistence, the EPIC 12 runtime, and EPIC 13 Task 4 transactional
market-event ingestion are live-verified against isolated PostgreSQL 17.10.

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
- Revision `0007_create_market_events` creates only durable market-event storage
  and successfully upgrades, downgrades to `0006`, and re-applies.
- Event deterministic identity is protected by
  `uq_market_events_identity_key`; exact persisted snapshot transitions are
  protected by `uq_market_events_snapshot_transition`.
- Previous and current snapshots use named `ON DELETE RESTRICT` foreign keys;
  the optional canonical-product reference uses `ON DELETE SET NULL`.
- Event lifecycle checks enforce valid state values, non-negative attempts,
  score/state consistency, complete claim leases, paired error fields, and
  positive optimistic versions.
- Pending/retry claims, expired leases, offer timelines, and canonical-product
  timelines have explicit indexes matching repository queries.
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
- `PostgresMarketEventRepository` preserves typed payload fields, exact snapshot
  identities, `Decimal`, UTC timestamps, enum values, claims, errors, and
  optimistic versions through explicit mapping.
- Repeated compatible event creation returns the existing row; incompatible
  immutable facts raise `RepositoryIdentityConflictError` without overwriting the
  stored event.
- Shared market-event contracts pass against both memory and PostgreSQL
  implementations.
- Focused PostgreSQL tests pass for concurrent creation, identity conflict,
  `FOR UPDATE SKIP LOCKED`, one-event contention, lease recovery, stale versions,
  outer rollback, and exact precision.

## Verified Transactions

- One repository scope supplies one `AsyncSession` to all repositories.
- Repositories do not commit independently.
- Event insertion and claim changes roll back with the caller-owned transaction.
- Event claims lock only the selection/update transaction; scoring work is not
  performed while the row lock is held.
- Successful runner scope exit commits once.
- Offer, snapshot, deterministic processing, and commit failures roll back the
  complete run and skip post-commit work.
- Content failure after commit leaves persistence durable and is represented in
  `MarketplaceRunResult`.
- Active ingestion inserts offers, exact snapshots, and deterministic market
  events in one shared-session transaction.
- First observations, increases, unchanged prices, reverse chronology, and exact
  duplicate snapshots do not create price-drop events.
- Event insertion failure rolls back the offer, current snapshot, and event; no
  post-commit scoring/content runs.
- Equal external IDs on GGSEL and Playerok produce independent event identities.
- Exact ingestion replay creates no duplicate event row, and stored identity
  matches domain recomputation from exact snapshot facts.

## Remaining Limits

- Event scoring status is not yet updated by the active runtime; scoring remains a
  temporary post-commit operation.
- Generated-content and publication state are not persisted.
- Post-commit publication retry is not implemented.
- Scheduler overlap and multi-process coordination are not implemented.
- Null external IDs remain intentionally append-only.
- Legacy foundation tables remain present and inactive.

Complete evidence is recorded in `EPIC_12_FINAL_VERIFICATION.md`.
EPIC 13 Task 3 evidence is implemented by
`verify_epic13_market_events_postgres.py` and the shared/focused market-event
repository tests. EPIC 13 Task 4 ingestion evidence is implemented by
`verify_epic13_ingestion_postgres.py` and the focused marketplace event
integration tests.
