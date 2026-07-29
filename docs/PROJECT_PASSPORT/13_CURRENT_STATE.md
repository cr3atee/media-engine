# Current State

## Purpose

This document records the current implementation state of MediaEngine.

## Status

Foundation is complete.

The current implementation includes the first marketplace processing path,
async memory and PostgreSQL repositories, deterministic matching/comparison,
repository-backed price history, transaction-bounded application execution,
durable post-commit event scoring, and Scheduler orchestration.

EPIC 12 is live-verified and complete against PostgreSQL 17.10.
EPIC 13 Task 6 is complete: deterministic price-drop events persist atomically,
are scored through durable claims, and produce persistent immutable content
attempts plus idempotent channel-independent publication intents.

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
  transaction and returns after the durable ingestion commit.
- One PostgreSQL repository scope shares one `AsyncSession` across all
  repositories and owns commit/rollback.
- Database constraints protect stable offer identity, exact snapshot identity,
  and canonical-product references.
- Active persistence timestamps are timezone-aware UTC values.
- Scheduler can retry and report a PostgreSQL-backed application run without
  owning business logic or database lifecycle.
- Memory and PostgreSQL providers expose `MarketEventRepository` in the same
  repository container as offers and price history.
- `PriceDropMarketEventBuilder` creates immutable Decimal-safe events from the
  active detector and exact snapshot identities.
- `MarketplaceApplicationRunner` reports durable event candidates, created and
  existing outcomes, event IDs, scored events, and post-commit errors.
- Live PostgreSQL ingestion verification confirms atomic commit/rollback,
  deterministic identity, replay suppression, marketplace isolation, and durable
  event retention across the ingestion/application boundary.
- `EventProcessingService` claims bounded batches, closes the claim transaction
  before scoring, and persists guarded success/failure in follow-up transactions.
- Active leases block competing workers; expired claims are recovered explicitly
  and idempotently according to the durable attempt budget.
- Transient scoring failures retry with bounded exponential backoff; invalid
  inputs and exhausted attempts reach explicit terminal states.
- Scheduler scoring and recovery jobs delegate only to the application service.
- A 14-check live isolated PostgreSQL verification confirms fresh-session
  durability, concurrency, rollback safety, retry/recovery, stale-token rejection,
  terminal failure, and Scheduler delegation.
- Memory and PostgreSQL providers expose generated-content and publication
  repositories through the same transaction scope as other persistence
  boundaries.
- `ContentGenerationProcessingService` claims immutable attempts in short
  transactions, runs AI/content generation without an open database scope, and
  persists guarded success or sanitized retryable failure.
- Successful generated content and its publication intent commit atomically when
  an explicit channel-independent target is configured.
- Expired content claims are abandoned; expired publication claims become
  protected ambiguous outcomes and are not automatically retried.
- Scheduler jobs delegate pending content generation and stale
  content/publication recovery to application services only.
- Revision `0008_content_publications` upgrades, downgrades to `0007`, re-applies,
  and matches SQLAlchemy metadata.
- An 18-check live isolated PostgreSQL verification confirms committed claims,
  transaction-free AI, retry, concurrency, rollback, fresh-session durability,
  idempotency, ambiguous-state protection, and Scheduler delegation.
- `app/analytics/price_change.py` is the sole detector; inactive duplicate
  detector/event modules were removed without changing calculation behavior.
- The unreferenced direct `MarketplacePipeline.process_after_commit()` helper was
  removed; production content has one durable claim-based processing path.

## Known Gaps

- GGSEL extracted price fields are preserved in raw `extra` data, but full price normalization from marketplace-specific fields is not complete.
- Snapshot creation is skipped when parsed offers do not contain normalized price and currency.
- Ingestion, scoring, and durable content processing are separate services and are
  not yet composed in one production process bootstrap.
- Scheduler has no explicit overlap or multi-process coordination policy.
- Publication delivery is not implemented; persisted publication rows are future
  delivery intents only.
- No production AI provider is wired into the marketplace pipeline.

## Architecture Review

Current architecture separates:

- marketplace retrieval and extraction;
- normalization into internal offer format;
- repository contracts and memory implementations;
- deterministic matching;
- pipeline orchestration.

EPIC 13 Task 6 adds shared content/publication contracts, focused
memory/PostgreSQL/Scheduler tests, reversible migration verification, and an
18-check live verification. The exact next task is final EPIC 13
production-shaped verification of ingestion -> scoring -> content -> publication
intent, including restart and overlap evidence. Actual Telegram delivery remains
a separate EPIC.
