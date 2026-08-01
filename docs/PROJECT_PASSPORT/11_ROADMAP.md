# Roadmap

## Purpose

This document tracks only work that is reflected by the current repository state.

## Completed

- Project foundation.
- Configuration foundation.
- Database foundation.
- Alembic foundation.
- Domain events foundation.
- Pipeline foundation.
- GGSEL response analysis.
- GGSEL raw product extraction from saved HTML payloads.
- Typed raw marketplace offer model.
- Parsed offer normalization boundary.
- Canonical product domain model.
- Matching Engine preprocessing.
- Matching Engine similarity scoring.
- Matching Engine confidence classification.
- MatchingService.
- Repository contracts.
- In-memory repositories.
- RepositoryProvider.
- MarketplacePipeline parsed offer persistence through RepositoryProvider.
- PostgreSQL repository implementations.
- Async repository contracts for memory and PostgreSQL backends.
- Repository-backed runtime price history.
- Shared PostgreSQL session and transaction scope per marketplace run.
- `MarketplaceApplicationRunner` transaction and post-commit boundary.
- Race-safe offer upsert and exact snapshot conflict suppression.
- PostgreSQL constraints, indexes, canonical-product FK, and UTC timestamps.
- Live PostgreSQL migration, concurrency, rollback, retry, and Scheduler
  verification for EPIC 12.
- Persistent market-event domain contracts and deterministic identity.
- Memory and PostgreSQL market-event repositories.
- Atomic offer/snapshot/event ingestion through `RepositoryProvider.events`.
- Live PostgreSQL verification of event identity, replay, rollback, marketplace
  isolation, and post-commit compatibility.
- Durable bounded market-event claiming and scoring persistence.
- Guarded scoring completion with claim-token and optimistic-version conflicts.
- Bounded retry/backoff and idempotent stale scoring-claim recovery.
- Scheduler scoring and stale-recovery jobs that delegate only to
  `EventProcessingService`.
- Live PostgreSQL verification of scoring transactions, concurrent workers,
  retry/recovery, terminal failure, and Scheduler delegation.
- Generated-content and publication domain contracts with shared memory and
  PostgreSQL repository behavior.
- Migration `0008_content_publications` with reversible live verification.
- Durable content generation outside repository transactions with immutable
  attempts, bounded retry, and stale-claim recovery.
- Atomic generated-content completion and idempotent channel-independent
  publication-intent creation.
- Scheduler jobs for content processing and stale content/publication recovery.
- Removal of the inactive duplicate price detector and event hierarchy after
  targeted reference verification.
- An 18-check live PostgreSQL content/publication verification.
- Final 83-check production-shaped EPIC 13 PostgreSQL verification covering the
  complete ingestion-to-publication-intent lifecycle.
- Telegram delivery contracts, plain-text formatter, direct Bot API client, and
  offline adapter verification.
- Channel-scoped publication claims for memory and PostgreSQL repositories.
- Durable `PublicationDeliveryService` with short claim/read/completion scopes,
  retry/backoff policy, permanent failure handling, ambiguous-state persistence,
  and read-only dry-run.
- `PendingPublicationDeliveryJob` that delegates bounded delivery processing
  without owning repositories or Telegram HTTP calls.
- Guarded live Telegram verification script with exact test-chat confirmation
  and safe offline default mode.
- Expanded EPIC 14 PostgreSQL verifier checks for retry resumption,
  completion-rollback recovery, one-publication/two-worker claim exclusivity,
  and token redaction.
- EPIC 14 final PostgreSQL verification: `39/39` checks at revision `0008`.
- EPIC 15 Task 1 authenticated read-only administration API for events,
  generated content, and publications.
- SQLAlchemy-independent administration query contracts and PostgreSQL query
  implementations with typed filters and deterministic keyset pagination.
- Stable API errors, request correlation IDs, API-key OpenAPI security, and
  liveness/readiness endpoints.
- EPIC 15 PostgreSQL read verification: `28/28` checks with no Telegram calls.
- EPIC 15 Task 2 guarded administration commands for content approve/reject,
  publication retry/cancel, and ambiguous resolution.
- Immutable `admin_actions` audit persistence with migration
  `0009_admin_actions`, memory/PostgreSQL repositories, idempotency, optimistic
  concurrency, and transaction rollback verification.
- EPIC 15 Task 2 PostgreSQL verification: `26/26` checks on PostgreSQL 17.10 at
  revision `0009_admin_actions`.

## Current Status

MediaEngine has a live-verified PostgreSQL runtime foundation for repository-backed
offers, price history, deterministic market events, bounded transactions,
durable post-commit scoring and content generation with recovery, persisted
publication intent, PostgreSQL-verified Telegram delivery orchestration, guarded
live-test tooling, Scheduler delegation, a PostgreSQL-verified read-only
administration API, and PostgreSQL-verified guarded administration commands with
immutable audit history.

## Not Present Yet

- Full price normalization for GGSEL extracted fields.
- Scheduler overlap and multi-process coordination.
- Optional guarded live Telegram test-chat message.
- Production AI provider integration in the pipeline.
- EPIC 15 Task 3 dashboard summary and operational completion.

## Recommended Next EPIC

**EPIC 15 Task 3: operational completion for the administration API.**
