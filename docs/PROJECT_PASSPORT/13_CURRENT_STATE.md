# Current State

## Purpose

This document records the current implementation state of MediaEngine.

## Status

Foundation is complete.

The current implementation includes the first marketplace processing path,
async memory and PostgreSQL repositories, deterministic matching/comparison,
repository-backed price history, transaction-bounded application execution,
post-commit content generation, and Scheduler orchestration.

EPIC 12 is live-verified and complete against PostgreSQL 17.10.

## Active Capabilities

- GGSEL catalog HTML can be fetched through the shared HTTP client.
- GGSEL raw product objects can be extracted from embedded payloads.
- Raw marketplace offers are represented by `RawMarketplaceOffer`.
- Raw offers can be normalized into `ParsedOffer`.
- Parsed offers can be persisted through `RepositoryProvider.offers`.
- Canonical products are represented by `CanonicalProduct`.
- Product titles can be normalized, tokenized, filtered by stop words, and expanded through aliases.
- Similarity scores can be calculated deterministically.
- Similarity scores can be classified into `AUTO_MATCH`, `REVIEW`, or `NO_MATCH`.
- `MatchingService` can select the best canonical product candidate for a parsed offer.
- Repository contracts exist for canonical products, offers, and price history.
- Async in-memory and PostgreSQL repository implementations exist.
- `MarketplacePipeline` persists parsed offers and price snapshots through
  `RepositoryProvider`.
- Price-change detection reads the latest persisted snapshot before storing and
  evaluating the current snapshot.
- `MarketplaceApplicationRunner` keeps HTTP/normalization before the database
  transaction and content generation after commit.
- One PostgreSQL repository scope shares one `AsyncSession` across all
  repositories and owns commit/rollback.
- Database constraints protect stable offer identity, exact snapshot identity,
  and canonical-product references.
- Active persistence timestamps are timezone-aware UTC values.
- Scheduler can retry and report a PostgreSQL-backed application run without
  owning business logic or database lifecycle.

## Known Gaps

- GGSEL extracted price fields are preserved in raw `extra` data, but full price normalization from marketplace-specific fields is not complete.
- Snapshot creation is skipped when parsed offers do not contain normalized price and currency.
- Market events and publication attempts are not persisted.
- Post-commit content failures cannot be resumed reliably.
- Scheduler has no explicit overlap or multi-process coordination policy.
- No Telegram delivery is implemented.
- No production AI provider is wired into the marketplace pipeline.

## Architecture Review

Current architecture separates:

- marketplace retrieval and extraction;
- normalization into internal offer format;
- repository contracts and memory implementations;
- deterministic matching;
- pipeline orchestration.

The final EPIC 12 verification passed 89 live PostgreSQL checks, 47 tests, and
strict MyPy across 105 source files. Full-project Ruff still has pre-existing
legacy/demo debt; all EPIC 12 files pass.
