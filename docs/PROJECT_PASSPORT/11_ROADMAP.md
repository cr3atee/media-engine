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

## Current Status

MediaEngine has a live-verified PostgreSQL runtime foundation for repository-backed
offers, price history, and deterministic market events; bounded transactions;
post-commit scoring/content; and Scheduler orchestration.

## Not Present Yet

- Full price normalization for GGSEL extracted fields.
- Durable event scoring and claim-based event processing.
- Generated-content and publication persistence.
- Content/publication retry after post-commit failure.
- Scheduler overlap and multi-process coordination.
- Telegram delivery implementation.
- Production AI provider integration in the pipeline.
