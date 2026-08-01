# Architecture

## Purpose

This document describes the current high-level architecture of MediaEngine as it exists in the repository.

## Layers

- `app/parsers`: marketplace data retrieval, raw extraction, raw marketplace offer models, and parsed offer normalization.
- `app/matching`: deterministic product title preprocessing, similarity scoring, confidence classification, and matching service.
- `app/models`: domain-level and persistence-facing models, including `CanonicalProduct`.
- `app/repositories`: repository contracts, in-memory implementations, and `RepositoryProvider`.
- `app/services`: orchestration services, including marketplace processing and content generation.
- `app/domain`: database-independent events and price snapshots.
- `app/analytics`: price change detection and related analytics models.
- `app/insights`: event scoring.
- `app/ai`: AI provider abstractions, fake provider, and prompt builders.
- `app/api`: FastAPI transport schemas, authentication, correlation, stable error
  handling, health probes, and read-only administration routes.
- `app/repositories/queries`: SQLAlchemy-independent read contracts, immutable
  projections, and memory/PostgreSQL query adapters.

## Current Data Flow

Current marketplace flow:

1. GGSEL HTML is fetched.
2. Raw GGSEL product payload is extracted.
3. Raw offers are normalized into `ParsedOffer`.
4. Parsed offers are saved through `RepositoryProvider.offers`.
5. Snapshots are attempted from parsed offers.
6. The latest persisted snapshot is loaded through `RepositoryProvider.price_history`.
7. The current snapshot is persisted through the same repository boundary.
8. Price changes are detected synchronously when a comparable snapshot exists.
9. Price drops are converted into deterministic immutable market events.
10. Events are inserted idempotently through `RepositoryProvider.events` in the
    same transaction as offers and snapshots.
11. Ingestion commits and returns with the durable event in `pending` scoring
    state.
12. `EventProcessingService` claims a bounded event batch in a short transaction.
13. The durable event is adapted to the existing scorer input and scored after
    the claim transaction closes.
14. Scoring success/failure is persisted in a new short transaction guarded by
    claim token and optimistic version.
15. A separate bounded recovery operation handles expired scoring claims.
16. `ContentGenerationProcessingService` selects successfully scored eligible
    events and creates/claims immutable content attempts in a short transaction.
17. Prompt adaptation and AI/content generation execute after that transaction
    closes.
18. A short completion transaction persists generated text and checksum and,
    when an explicit target exists, creates one idempotent channel-independent
    publication intent atomically.
19. Separate recovery services abandon expired generation claims and protect
    expired publication claims as ambiguous.
20. `PublicationDeliveryService` claims due Telegram publications by generic
    channel filter, prepares durable content/event DTOs, calls the delivery
    adapter outside repository transactions, and persists guarded success,
    retryable failure, permanent failure, or ambiguous state.
21. `PendingPublicationDeliveryJob` delegates bounded publication delivery to
    the service without owning repositories, formatting, retry policy, or
    Telegram HTTP calls.

## Matching Flow

Current matching flow:

1. `MatchingPreprocessor` normalizes, tokenizes, removes stop words, and expands aliases.
2. `SimilarityEngine` calculates token similarity.
3. `ConfidenceEngine` classifies the similarity score.
4. `MatchingService` selects the best canonical product candidate for a `ParsedOffer`.

## Repository Boundary

Repository contracts are defined independently from any database technology.

Current repository layer includes:

- `CanonicalProductRepository`
- `OfferRepository`
- `PriceHistoryRepository`
- `MarketEventRepository`
- `GeneratedContentRepository`
- `PublicationRepository`
- `MarketEventQueryRepository`
- `GeneratedContentQueryRepository`
- `PublicationQueryRepository`
- in-memory implementations under `app/repositories/memory`
- PostgreSQL implementations under `app/repositories/postgres`
- `RepositoryProvider`
- `create_memory_provider()`
- `create_postgres_provider()`

Repository access is asynchronous for both memory and PostgreSQL backends.
PostgreSQL is not hardcoded as the default backend. Memory and PostgreSQL
providers both include event repositories. Production-shaped execution
uses `MarketplaceApplicationRunner` with one repository scope, one shared
`AsyncSession`, and one transaction for a bounded marketplace run. HTTP and
normalization execute before that scope; offer, snapshot, and durable event writes
execute inside it. Durable scoring is a separate claim-based application-service
flow. Durable content generation is a subsequent claim-based service; it does not
run inside ingestion or scoring transactions.

## Boundaries

- Parsers do not persist data directly.
- Repository interfaces do not depend on SQLAlchemy or PostgreSQL.
- Matching does not depend on marketplace-specific code.
- Matching does not use AI, embeddings, or external services.
- Marketplace pipeline persists parsed offers, price snapshots, and deterministic
  market events only through `RepositoryProvider`.
- Scheduler jobs delegate to application services and do not own repositories,
  sessions, scoring policy, or business logic.
- Scoring never runs while a claim repository scope or row lock remains open.
- AI/content providers are called only after the generation-claim transaction has
  committed.
- Publication persistence is channel independent; Telegram delivery is connected
  through a channel-aware application service and adapter composition, not
  Telegram-specific repository APIs.
- Generated content and publication intent share one completion transaction when
  an explicit destination is configured.
- Telegram network calls occur outside database transactions. Ambiguous outcomes
  are never retried automatically.
- Administration routes depend on application query services and immutable read
  projections, never ORM rows, sessions, lifecycle repositories, or Telegram
  adapters.
- Read requests open caller-owned short repository scopes and never commit,
  claim, or change lifecycle state.

## Read Administration Flow

The EPIC 15 Task 1 flow is:

1. Correlation middleware validates or creates a bounded request ID.
2. `X-Admin-API-Key` authentication fails closed and uses constant-time
   comparison.
3. FastAPI validates typed filters, UTC ranges, allow-listed sorting, and page
   bounds.
4. Application query services call SQLAlchemy-independent read contracts.
5. PostgreSQL query adapters perform deterministic keyset queries and map ORM
   records to immutable safe projections.
6. API mappers return versioned payloads, plain generated text, hashed
   destination references, and sanitized errors.

The read API introduces no lifecycle mutation, migration, Telegram call, or AI
call.

## EPIC 13 Verification

The complete repository-backed lifecycle was verified on PostgreSQL 17.10 with
fresh services at every durable boundary. Ingestion, scoring, AI generation, and
publication-intent persistence retain their existing layer direction: external
work is outside transactions, repositories own no policy, and Scheduler jobs only
delegate. No alternate active event or content-processing path remains.

## EPIC 14 Verification

Telegram delivery architecture remains channel-boundary oriented: repositories
stay channel independent, `PublicationDeliveryService` owns durable lifecycle
orchestration, and `TelegramPublicationAdapter` owns only outbound provider I/O.

The expanded PostgreSQL verifier passed `39/39` checks against an isolated
database. No production delivery path is enabled by default, and live Telegram
delivery must not be claimed verified until one approved test-chat message is
sent through the normal service path and its external message ID is persisted.
