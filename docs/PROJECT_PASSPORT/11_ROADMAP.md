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

## Current Status

MediaEngine has a live-verified PostgreSQL runtime foundation for repository-backed
offers, price history, and deterministic market events; bounded transactions;
durable post-commit scoring and content generation with recovery; persisted
publication intent; and Scheduler orchestration.

## Not Present Yet

- Full price normalization for GGSEL extracted fields.
- Scheduler overlap and multi-process coordination.
- Actual Telegram delivery implementation.
- Production AI provider integration in the pipeline.

## Recommended Next EPIC

**Telegram Publication Adapter and Delivery Workflow**.
