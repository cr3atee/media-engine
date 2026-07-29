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
- The Pydantic `PriceDropEvent` is a temporary scoring/content adapter only; the
  durable `MarketEvent` owns identity and audit facts.
- Exact snapshot replay is suppressed before event construction. Repository-level
  compatible replay remains `EXISTING`; immutable conflicts fail explicitly.
- Durable scoring uses three boundaries: short claim transaction, deterministic
  scoring with no open repository scope, and short guarded completion/failure
  transaction.
- Expired `in_progress` claims are never silently stolen by normal claim polling;
  only the explicit recovery operation invalidates and reschedules them.
- Application retry policy owns backoff and failure classification. Repositories
  expose only lifecycle-specific async transitions and typed outcomes.
- Scheduler event jobs only delegate bounded service calls; persisted work-item
  retries are separate from Scheduler invocation retries/statistics.
- The exact next implementation task is Task 6: duplicate detector and legacy
  event cleanup after targeted import and behavior-parity verification.
- Generated-content persistence, publication persistence, AI execution, and
  delivery remain outside the active durable event-processing flow.
- GGSEL-specific price fields are not fully normalized into `ParsedOffer.price` and `ParsedOffer.currency` yet.

## Review Notes

- Keep repository interfaces free from SQLAlchemy and PostgreSQL details.
- Keep matching free from AI, embeddings, and marketplace-specific assumptions unless explicitly requested.
- Keep parser extraction separate from domain matching and persistence decisions.
