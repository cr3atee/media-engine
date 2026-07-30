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
- Durable content processing uses three boundaries: attempt preparation/claim,
  provider execution with no open repository scope, and guarded completion or
  failure persistence.
- Generated text and publication intent are atomic when a target is supplied;
  missing target configuration leaves generated content valid without inventing
  delivery metadata.
- Failed generation retries create new immutable attempts. Expired content claims
  become abandoned; expired publication claims become ambiguous and cannot be
  automatically resent.
- Publication delivery uses three boundaries: short channel-scoped claim
  transaction, Telegram adapter call with no open repository scope, and short
  guarded completion transaction.
- Retry/backoff policy lives in `PublicationDeliveryService`, not in Telegram
  adapter, Scheduler, or repositories.
- Telegram `429` stops the current delivery batch after persisting a durable
  retry timestamp. Ambiguous delivery outcomes are terminal for automatic
  processing and require future manual resolution.
- Dry-run is a separate read-only operation and must not be routed through the
  normal claim path.
- `RepositoryProvider` exposes generated-content and publication repositories for
  both memory and PostgreSQL scopes; PostgreSQL repositories share the
  caller-owned session and never commit.
- Scheduler content/recovery jobs delegate only to application services and own
  neither retry policy nor delivery behavior.
- The duplicate price detector and inactive `app/core/events.py` hierarchy were
  removed after targeted reference verification. `PriceDropEvent` remains only a
  transient adapter for existing scoring/prompt interfaces.
- Final EPIC 13 production-shaped verification passed 83 live PostgreSQL checks
  across ingestion, scoring, content, publication intent, restart, concurrency,
  rollback, Scheduler delegation, and audit linkage.
- The exact next implementation task is **guarded Telegram live test-chat
  verification**. It must preserve publication idempotency, token secrecy, and
  ambiguous-state protection.
- GGSEL-specific price fields are not fully normalized into `ParsedOffer.price` and `ParsedOffer.currency` yet.

## Review Notes

- Keep repository interfaces free from SQLAlchemy and PostgreSQL details.
- Keep matching free from AI, embeddings, and marketplace-specific assumptions unless explicitly requested.
- Keep parser extraction separate from domain matching and persistence decisions.
