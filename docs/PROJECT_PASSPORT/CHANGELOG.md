# Changelog

## Purpose

This document records notable Project Passport updates.

## Unreleased

- Added durable bounded market-event claiming and scoring through
  `EventProcessingService`.
- Added the explicit durable-event scoring adapter, immutable processing result
  DTOs, safe error categories, bounded exponential retry policy, and idempotent
  stale-claim recovery.
- Added Scheduler jobs for pending scoring and stale scoring-claim recovery while
  preserving orchestration-only boundaries.
- Stopped active ingestion from invoking the legacy immediate scoring/content
  path before durable claims.
- Added memory, PostgreSQL, concurrency, rollback, retry/recovery, and Scheduler
  coverage plus a 14-check live PostgreSQL verification.
- Integrated deterministic market-event persistence into the existing ingestion
  transaction.
- Added event repositories to memory/PostgreSQL providers and preserved one shared
  PostgreSQL session per run.
- Added a Decimal-safe event builder, exact snapshot identity mapping, idempotent
  insertion, rollback coverage, and a temporary post-commit legacy event adapter.
- Added focused memory/PostgreSQL integration tests and live EPIC 13 Task 4
  verification.
- Completed EPIC 12 live verification against PostgreSQL 17.10.
- Verified migration preflight, constraints, indexes, concurrency, FK behavior,
  transaction rollback, retry, Scheduler execution, and practical overlap.
- Added reversible UTC-aware timestamp migration `0006_use_utc_timestamps` after
  live `asyncpg` verification exposed a timezone schema mismatch.
- Recorded the final EPIC 12 acceptance checklist and production limitations.
- Migrated active runtime price history to `RepositoryProvider.price_history`.
- Removed the duplicate standalone `PriceHistoryService`.
- Documented deterministic snapshot ordering and duplicate behavior.
- Updated scheduler and PostgreSQL verification paths for repository-backed history.
- Synchronized Project Passport with the current implementation state.
- Documented completed Matching Engine components.
- Documented `MatchingService`.
- Documented repository contracts.
- Documented in-memory repositories.
- Documented `RepositoryProvider`.
- Documented `MarketplacePipeline` parsed offer persistence through `RepositoryProvider`.
- Documented current known gaps around GGSEL price normalization, price history persistence, Telegram delivery, and production AI wiring.

## Previous Notes

- Initial Project Passport structure was created.
- First local Architecture Review was recorded for the price-change processing flow.
