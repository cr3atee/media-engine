# PostgreSQL Verification

## Status

PostgreSQL persistence, the EPIC 12 runtime, EPIC 13 transactional market-event
ingestion, durable scoring, generated content, and publication-intent state are
live-verified. Final EPIC 13 verification passed 83 checks against isolated
PostgreSQL 17.10 at revision `0008_content_publications` without using a project
or production database.

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
- Revision `0008_content_publications` creates immutable generated-content
  attempts and channel-independent publication intents. Offline SQL generation,
  live upgrade, downgrade to `0007`, and re-upgrade pass.
- Content and publication identity, active-attempt uniqueness, lifecycle payload,
  complete claim metadata, optimistic version, event/content lookup, and lease
  recovery rules are database constrained and indexed.
- Generated-content and publication foreign keys use `ON DELETE RESTRICT` so
  event/content audit history is not destroyed by cascade deletion.

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
- Durable scoring claims only pending/retry-eligible rows. Active leases block
  other workers, while expired claims are exposed only to explicit recovery.
- Guarded scoring completion persists score and success state atomically and
  rejects stale claim tokens and optimistic versions.
- Transient retry state, terminal permanent failure, UTC timestamps, and score
  precision survive fresh sessions.
- Shared generated-content and publication contracts pass against memory and
  PostgreSQL repositories, including immutable attempt ordering, retries, review
  transitions, terminal-state protection, ambiguous publication state, stale
  claim tokens, and optimistic-version conflicts.
- PostgreSQL-specific tests verify two-session generation/publication contention,
  durable fresh-session round trips, unique idempotency, rollback, and atomic
  content/publication completion.

## Verified Transactions

- One repository scope supplies one `AsyncSession` to all repositories.
- Repositories do not commit independently.
- Event insertion and claim changes roll back with the caller-owned transaction.
- Event claims lock only the selection/update transaction; the repository scope
  is closed before deterministic scoring starts.
- Each scoring completion or failure uses a new short transaction. A completion
  rollback cannot falsely mark the event scored; lease recovery can make the
  retained claim retryable.
- Successful runner scope exit commits once.
- Offer, snapshot, deterministic processing, and commit failures roll back the
  complete run and skip post-commit work.
- Active ingestion ends after durable event commit and does not invoke the legacy
  in-memory scoring/content path.
- Active ingestion inserts offers, exact snapshots, and deterministic market
  events in one shared-session transaction.
- First observations, increases, unchanged prices, reverse chronology, and exact
  duplicate snapshots do not create price-drop events.
- Event insertion failure rolls back the offer, current snapshot, and event; no
  post-commit scoring/content runs.
- Equal external IDs on GGSEL and Playerok produce independent event identities.
- Exact ingestion replay creates no duplicate event row, and stored identity
  matches domain recomputation from exact snapshot facts.
- Content claims commit before AI execution. Provider calls run with no repository
  scope open; completion/failure uses a new short transaction.
- Generated text and publication intent commit atomically. A simulated completion
  transaction failure leaves the attempt claimed for recovery and creates no
  partial publication row.
- Expired generation claims become abandoned. Expired publication claims become
  ambiguous and cannot be automatically reclaimed for delivery.

## Remaining Limits

- Durable ingestion, scoring, and content processing are implemented as separate
  production-shaped services but are not yet composed in one process bootstrap.
- External publication delivery is not implemented; publication rows are durable
  delivery intents only.
- Scheduler overlap and multi-process coordination are not implemented.
- Null external IDs remain intentionally append-only.
- Legacy foundation tables remain present and inactive.

Complete evidence is recorded in `EPIC_12_FINAL_VERIFICATION.md`.
EPIC 13 Task 3 evidence is implemented by
`verify_epic13_market_events_postgres.py` and the shared/focused market-event
repository tests. EPIC 13 Task 4 ingestion evidence is implemented by
`verify_epic13_ingestion_postgres.py` and the focused marketplace event
integration tests. EPIC 13 Task 5 evidence is implemented by
`verify_epic13_event_processing_postgres.py`: all 14 live checks pass, covering
durable success, fresh sessions, duplicate suppression, transaction boundaries,
concurrency, retry, active leases, recovery, stale tokens, terminal failure, and
Scheduler delegation.
Task 6 evidence is implemented by
`verify_epic13_content_publication_postgres.py`: all 18 live checks pass, covering
migration, scored-event eligibility, committed claims, transaction-free AI,
durable success/failure/retry, fresh sessions, worker contention, rollback,
idempotency, ambiguous publication protection, and Scheduler delegation.

Final evidence is recorded in `EPIC_13_FINAL_VERIFICATION.md` and implemented by
`verify_epic13_end_to_end_postgres.py`. Clean migration, downgrade/re-upgrade,
schema constraints, fresh-session restart, idempotency, rollback, concurrency,
audit linkage, and complete Scheduler orchestration all pass. External delivery
remains intentionally unimplemented.
