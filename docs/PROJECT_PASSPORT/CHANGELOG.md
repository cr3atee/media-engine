# Changelog

## Purpose

This document records notable Project Passport updates.

## Unreleased

- Implemented EPIC 15 Task 1 read-only administration API for durable events,
  generated content, publications, related-resource reads, and health probes.
- Added fail-closed `X-Admin-API-Key` authentication, OpenAPI security metadata,
  bounded request correlation, stable sanitized errors, typed UTC filters, and
  signed deterministic keyset cursors.
- Added SQLAlchemy-independent query contracts with memory and PostgreSQL
  implementations returning immutable safe projections rather than ORM rows.
- Verified EPIC 15 Task 1 with 27 focused tests, 28 isolated PostgreSQL checks,
  full Pytest, strict MyPy, Ruff, Ruff format, and Alembic current/check/offline
  SQL.
- Added EPIC 14 Task 3 guarded live Telegram verification script with safe
  offline default mode, exact test-chat confirmation, allowlist checks, and no
  default network call.
- Expanded EPIC 14 PostgreSQL verifier with due-retry resumption,
  completion-rollback recovery, stale-claim recovery, one-publication/two-worker
  claim exclusivity, and token-redaction checks.
- Recorded that final EPIC 14 PostgreSQL/live verification is not complete in
  the current environment because no isolated PostgreSQL runtime or live
  Telegram credentials/test chat were available.
- Implemented EPIC 14 Task 2 durable Telegram publication delivery
  orchestration without live sending.
- Added generic channel-scoped publication claims and attempt-budget filtering
  for memory and PostgreSQL publication repositories.
- Added `PublicationDeliveryService` with short claim/read/completion scopes,
  retry/backoff policy, success, permanent failure, retryable failure, ambiguous
  outcome handling, and read-only dry-run.
- Added `PendingPublicationDeliveryJob` as an orchestration-only Scheduler job.
- Added focused delivery-service tests, PostgreSQL-guarded verification, and
  documentation updates for live Task 3 requirements.
- Completed final EPIC 13 production-shaped verification against isolated
  PostgreSQL 17.10: 83 end-to-end checks passed from ingestion through durable
  publication intent.
- Verified restart recovery, idempotency, rollback, multi-worker contention,
  short transaction boundaries, audit linkage, and orchestration-only Scheduler
  execution.
- Updated legacy EPIC 13 live scripts for migration head `0008` and restrictive
  downstream foreign keys; removed two obsolete MyPy ignore comments.
- Added revision `0008_content_publications` for immutable generated-content
  attempts and channel-independent publication intents.
- Added memory/PostgreSQL generated-content and publication repositories to
  `RepositoryProvider` with shared behavioral contracts.
- Added durable content processing with committed claims, transaction-free AI,
  atomic content/publication completion, bounded retry, safe persisted errors,
  and stale-claim recovery.
- Added Scheduler jobs for pending content generation and stale
  content/publication claim recovery without external delivery logic.
- Added PostgreSQL contention, rollback, fresh-session, retry, and recovery tests
  plus an 18-check live verification.
- Removed the inactive duplicate price detector and `app/core/events.py` hierarchy
  after redirecting the remaining legacy demo import to the active detector.
- Removed the unreferenced direct marketplace post-commit scoring/content helper,
  leaving one durable claim-based content-generation path.
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
