# Tech Lead Notes

## Purpose

This document captures architecture notes that are important for future reviews.

## Current Notes

- Matching Engine is deterministic and marketplace independent.
- Matching currently uses token preprocessing, Jaccard similarity, and fixed confidence thresholds.
- `MatchingService` depends on existing matching components rather than duplicating preprocessing or similarity logic.
- Repository contracts are database-independent.
- In-memory repositories are development implementations only.
- `RepositoryProvider` is the current boundary for exposing repository implementations.
- `MarketplacePipeline` persists parsed offers and price snapshots through
  `RepositoryProvider`, not through concrete repositories or a parallel service.
- Price-history ordering is chronological by collection timestamp with a
  deterministic backend tie-break for equal timestamps.
- Exact snapshot duplicates are suppressed by memory semantics and a PostgreSQL
  unique constraint with race-safe `ON CONFLICT DO NOTHING`.
- `MarketplaceApplicationRunner` owns the production-shaped run boundary; one
  PostgreSQL scope shares one session and transaction across repositories.
- Live PostgreSQL verification covers migration preflight, two-session conflicts,
  FK behavior, commit/rollback, retries, Scheduler delegation, and UTC timestamps.
- Durable market events now share the offer/snapshot ingestion transaction and use
  exact persistence-neutral snapshot identities.
- The Pydantic `PriceDropEvent` is a temporary post-commit adapter only; the
  durable `MarketEvent` owns identity and audit facts.
- Exact snapshot replay is suppressed before event construction. Repository-level
  compatible replay remains `EXISTING`; immutable conflicts fail explicitly.
- The next implementation task is durable event claiming and scoring. It must not
  hold database locks while running scoring policy and must not add AI or
  publication behavior.
- GGSEL-specific price fields are not fully normalized into `ParsedOffer.price` and `ParsedOffer.currency` yet.

## Review Notes

- Keep repository interfaces free from SQLAlchemy and PostgreSQL details.
- Keep matching free from AI, embeddings, and marketplace-specific assumptions unless explicitly requested.
- Keep parser extraction separate from domain matching and persistence decisions.
