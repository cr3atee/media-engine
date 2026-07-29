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

## Current Status

MediaEngine has a live-verified PostgreSQL runtime foundation for repository-backed
offers, price history, and deterministic market events; bounded transactions;
durable post-commit scoring with recovery; and Scheduler orchestration.

## Not Present Yet

- Full price normalization for GGSEL extracted fields.
- Duplicate detector and inactive legacy event cleanup.
- Generated-content and publication persistence.
- Content-generation and publication retry.
- Scheduler overlap and multi-process coordination.
- Telegram delivery implementation.
- Production AI provider integration in the pipeline.
