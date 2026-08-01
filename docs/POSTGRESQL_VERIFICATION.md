# PostgreSQL Verification

## Status

PostgreSQL persistence, the EPIC 12 runtime, EPIC 13 transactional market-event
ingestion, durable scoring, generated content, and publication-intent state are
live-verified. Final EPIC 13 verification passed 83 checks against isolated
PostgreSQL 17.10 at revision `0008_content_publications` without using a project
or production database. EPIC 14 delivery verification additionally passed
`39/39` checks against a separate isolated PostgreSQL 17 container at the same
revision.

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
- Telegram publication delivery is implemented and verified with mocked transport;
  guarded live test-chat delivery has not been performed.
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

## EPIC 14 Task 2 Update

Telegram publication delivery orchestration is implemented on top of the
existing PostgreSQL publication repository without adding a migration. The
existing `publications` schema already stores channel, destination, claim token,
lease, attempt count, retry timestamp, external message ID, published timestamp,
safe processing error, and optimistic version.

The repository contract now supports generic channel-scoped claiming and an
optional attempt budget. PostgreSQL applies the channel predicate before
`FOR UPDATE SKIP LOCKED`, so a Telegram worker does not temporarily claim
non-Telegram publications.

`PublicationDeliveryService` uses short claim/read/completion repository scopes
and calls Telegram adapters outside database transactions. Confirmed success,
retryable failure, permanent failure, and ambiguous outcomes are persisted
through existing guarded publication transitions. Dry-run is read-only.

`scripts/verify_epic14_delivery_service_postgres.py` is the offline PostgreSQL
verification entry point for this task. In environments without an isolated
`EPIC14_DATABASE_URL`, it reports the missing prerequisite instead of fabricating
success. No live Telegram message is sent by this verification path.

## EPIC 14 Task 3 Update

The PostgreSQL verifier now includes additional final-verification checks for:

- due retry resumption;
- completion rollback after a successful adapter response;
- stale-claim recovery to `ambiguous` after that rollback;
- one-publication/two-worker claim exclusivity;
- token redaction of provider messages and client representations.

Task 3 PostgreSQL execution passed `39/39` checks against an isolated
`epic14_verify` database. The checks cover due retry resumption, completion
rollback, stale recovery, channel isolation, two-worker exclusivity, dry-run,
fresh-session persistence, transaction-free Telegram calls, Scheduler
delegation, and token redaction.

## EPIC 14 Task 3 Retry (2026-07-31)

Docker Desktop was started successfully and a temporary `postgres:17-alpine`
container exposed only `127.0.0.1:55432` for the isolated `epic14_verify`
database. `scripts/verify_epic14_delivery_service_postgres.py` passed `39/39`.
`alembic current` reported `0008_content_publications (head)`, `alembic check`
reported no new upgrade operations, and offline upgrade SQL generated all eight
migrations in `342` lines.

**EPIC 14 functionally complete; guarded live Telegram test-chat verification
not performed.**

## EPIC 15 Task 1 Read API

`scripts/verify_epic15_read_api_postgres.py` was executed against a temporary
isolated PostgreSQL 16 container and database named `epic15_verify`. It rebuilt
the isolated public schema, applied all migrations through
`0008_content_publications`, seeded durable records through existing repository
contracts, and exercised the real FastAPI ASGI application.

All `28/28` named checks passed: liveness, readiness, missing/invalid/valid API
key authentication, event/content/publication lists and details, typed
price-drop payloads, filters, deterministic pagination, safe destinations,
claim-token absence, sanitized errors, invalid cursors, UTC range validation,
request correlation, absence of mutation routes, absence of Telegram calls, and
fresh-session restart reads.

`alembic current` reported `0008_content_publications (head)`, `alembic check`
reported no new upgrade operations, and offline upgrade SQL generated
successfully through current head. Task 1 required no migration.
