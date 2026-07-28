# Current State

## Purpose

This document records the current implementation state of MediaEngine.

## Status

Foundation is complete.

The current implementation includes the first real marketplace processing path for GGSEL HTML retrieval, raw payload extraction, parsed offer normalization, in-memory offer persistence, deterministic matching infrastructure, and content generation infrastructure.

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

## Known Gaps

- GGSEL extracted price fields are preserved in raw `extra` data, but full price normalization from marketplace-specific fields is not complete.
- Snapshot creation is skipped when parsed offers do not contain normalized price and currency.
- PostgreSQL runtime still lacks one shared session and transaction boundary per
  complete marketplace run.
- Concurrent exact-snapshot duplicate protection is not enforced by a database
  uniqueness constraint.
- No Telegram delivery is implemented.
- No production AI provider is wired into the marketplace pipeline.

## Architecture Review

Current architecture separates:

- marketplace retrieval and extraction;
- normalization into internal offer format;
- repository contracts and memory implementations;
- deterministic matching;
- pipeline orchestration.

No application code was changed during this documentation sync.
