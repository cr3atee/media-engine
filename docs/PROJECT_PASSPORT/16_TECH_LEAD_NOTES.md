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
- Exact snapshot duplicates are suppressed in repositories; database-enforced
  protection against concurrent duplicate writes remains pending.
- The next persistence step is shared PostgreSQL session and transaction ownership
  for a complete runtime pipeline execution.
- GGSEL-specific price fields are not fully normalized into `ParsedOffer.price` and `ParsedOffer.currency` yet.

## Review Notes

- Keep repository interfaces free from SQLAlchemy and PostgreSQL details.
- Keep matching free from AI, embeddings, and marketplace-specific assumptions unless explicitly requested.
- Keep parser extraction separate from domain matching and persistence decisions.
