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

## Current Data Flow

Current marketplace flow:

1. GGSEL HTML is fetched.
2. Raw GGSEL product payload is extracted.
3. Raw offers are normalized into `ParsedOffer`.
4. Parsed offers are saved through `RepositoryProvider.offers`.
5. Snapshots are attempted from parsed offers.
6. Price changes are detected when comparable snapshots exist.
7. Price drop events are built when prices decrease.
8. Events are scored.
9. Content is generated through the existing content generator and AI provider abstraction.

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
- in-memory implementations under `app/repositories/memory`
- `RepositoryProvider`
- `create_memory_provider()`

## Boundaries

- Parsers do not persist data directly.
- Repository interfaces do not depend on SQLAlchemy or PostgreSQL.
- Matching does not depend on marketplace-specific code.
- Matching does not use AI, embeddings, or external services.
- Marketplace pipeline persists parsed offers only through `RepositoryProvider`.
