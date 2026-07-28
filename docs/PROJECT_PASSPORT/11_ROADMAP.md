# Roadmap

## Purpose

This document tracks only work that is reflected by the current repository state.

## Completed

- Project foundation.
- Configuration foundation.
- Database foundation.
- Alembic foundation.
- Domain events foundation.
- Pipeline foundation.
- GGSEL response analysis.
- GGSEL raw product extraction from saved HTML payloads.
- Typed raw marketplace offer model.
- Parsed offer normalization boundary.
- Canonical product domain model.
- Matching Engine preprocessing.
- Matching Engine similarity scoring.
- Matching Engine confidence classification.
- MatchingService.
- Repository contracts.
- In-memory repositories.
- RepositoryProvider.
- MarketplacePipeline parsed offer persistence through RepositoryProvider.
- PostgreSQL repository implementations.
- Async repository contracts for memory and PostgreSQL backends.
- Repository-backed runtime price history.

## Current Status

MediaEngine has a working foundation for fetching GGSEL HTML, extracting raw product payloads, normalizing them into parsed offers, persisting offers and price history through a repository provider, and running deterministic product matching against canonical products.

## Not Present Yet

- Full price normalization for GGSEL extracted fields.
- Shared PostgreSQL session and transaction ownership for a complete pipeline run.
- Database-level concurrent duplicate protection for price snapshots.
- Telegram delivery implementation.
- Production AI provider integration in the pipeline.
